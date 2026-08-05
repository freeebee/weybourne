"""The Felix run — the work() the jobs framework executes.

Phases: preflight (schemas, relation map, options) → undo sweep → strict full
scan → deterministic detection → LLM adjudication → ordered execution (merges
last) → summary. Dry-run walks the whole pipeline and records planned changes
without a single Notion write.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from src import config
from src.connectors.notion_client import NotionPartialResult
from src.features.felix import (
    adjudicate,
    detect,
    enrich,
    execute,
    research,
    store,
    undo,
)
from src.features.felix.models import ChangeRecord, RunOptions, RunRecord

# Scan-property allowlist where computed properties 500 inside Notion.
_FUNDS_SCAN_PROPS = ["Fund Name", "Name", "Asset Class", "Geographic Focus",
                     "Strategy Description", "Status", "Company Name",
                     "Responsible Person", "Company", "Representatives"]

# Duplicate detection covers the entity databases only. Meeting notes
# legitimately repeat their titles ("Call with X" every quarter), so name
# similarity there is meaningless: it produced one enormous comparison bucket
# that swamped the adjudicator and starved real contact duplicates.
DEDUPE_DBS = ("contacts", "companies", "funds")

_DB_IDS = {
    "contacts": lambda: config.NOTION_CONTACTS_DB,
    "companies": lambda: config.NOTION_COMPANIES_DB,
    "funds": lambda: config.NOTION_FUNDS_DB,
    "notes": lambda: config.NOTION_NOTES_DB,
}

_EVENT_TEXT = {
    "create_company": "company added",
    "add_photo": "photo added",
    "fix_formatting": "tidied",
    "fix_icon": "icon polished",
    "fix_relation": "relation repaired",
    "fill_missing": "filled in",
    "merge": "duplicate merged",
    "merge_transfer": "detail transferred",
    "archive": "duplicate archived",
    "recommendation": "flagged for review",
}

_FORMAT_REASONS = {
    "title_whitespace": "whitespace normalisation",
    "name_case": "proper name capitalisation",
    "email_case": "lowercased the address",
    "email_extract": "the email field held extra text; keeping only the address",
}


def _merge_detail(survivor: dict, loser: dict, transfers: dict,
                  names_by_id: dict, notes_by_id: Optional[dict] = None,
                  web_check: str = "") -> str:
    """Side-by-side of both records (JSON, for the review UI) so an approve
    decision needs no digging: what each copy holds, which meeting notes point
    at it, whether the pair was verified online, what moves over, and any
    conflicting values."""
    import json as _json

    notes_by_id = notes_by_id or {}

    def snap(c):
        fields = {}
        for k, v in c["plain"].items():
            # Unticked checkboxes carry no information about identity — a
            # column of "False" only crowds out what matters.
            if detect._empty(v) or v is False or k == c.get("title_prop"):
                continue
            if k in c["relations"]:
                v = [names_by_id.get(i, "(unknown)") for i in c["relations"][k]]
            s = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
            fields[k] = s[:120]
        return {"id": c["id"], "name": c["name"],
                "created": (c.get("created") or "")[:10],
                "url": c.get("url", ""),
                "fields": fields,
                "notes": [n[:70] for n in notes_by_id.get(c["id"], [])[:5]],
                "note_count": len(notes_by_id.get(c["id"], []))}

    return _json.dumps({
        "pair": [survivor["id"], loser["id"]],
        "keep": snap(survivor),
        "archive": snap(loser),
        "web_check": web_check,
        "moves": [t["property"] for t in transfers["transfers"]],
        "conflicts": [{"property": cf["property"],
                       "keep": str(cf["survivor"])[:90],
                       "loses": str(cf["loser"])[:90]}
                      for cf in transfers["conflicts"]],
    })[:3800]


def _prop_payload(ptype: str, value: str) -> dict:
    if ptype == "select":
        return {"select": {"name": value}}
    if ptype == "multi_select":
        # Asset Class and Geographic Focus are multi-selects; sending a
        # single-select payload to one is rejected outright by Notion.
        vals = value if isinstance(value, list) else [value]
        return {"multi_select": [{"name": str(v)} for v in vals if str(v).strip()]}
    if ptype == "status":
        return {"status": {"name": value}}
    if ptype == "phone_number":
        return {"phone_number": value}
    if ptype == "url":
        return {"url": value}
    return {"rich_text": [{"text": {"content": str(value)[:1900]}}]}


def _clip(text: str, limit: int = 900) -> str:
    """Trim to a word boundary with an ellipsis.

    Evidence used to be cut mid-word at 180-300 characters — "This directly
    ti" — which is worse than useless: the reviewer cannot tell whether the
    sentence supported the change or contradicted it. These strings sit in a
    local JSON file, so the old limits were buying nothing.
    """
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    cut = s[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit * 0.6 else cut).rstrip(" ,;:—-") + "…"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stage(job: dict, label: str, detail: str = "") -> None:
    job["stages"].append({"label": label, "detail": detail, "at": time.time()})


def _stage_durations(stages: list[dict]) -> list[dict]:
    """Each stage's wall-clock duration: the gap to the NEXT stage's start,
    or to now for whichever stage was still open when the run ended (either
    finished normally or stopped at the findings cap). This is what actually
    explains why one run took 21 minutes and another took 72 — see the
    per-phase breakdown on a RunRecord rather than a single elapsed total."""
    now = time.time()
    out = []
    for i, s in enumerate(stages):
        end = stages[i + 1]["at"] if i + 1 < len(stages) else now
        out.append({"label": s["label"], "detail": s["detail"],
                    "duration_s": round(end - s.get("at", end), 1)})
    return out


def _emit(job: dict, change: ChangeRecord) -> None:
    part = job.setdefault("partial", {})
    events = part.setdefault("events", [])
    events.append({"change_id": change.change_id, "db": change.database,
                   "record": change.record_name, "type": change.change_type,
                   "status": change.execution_status,
                   "label": _EVENT_TEXT.get(change.change_type, "fixed"),
                   "at": time.time()})
    del events[:-400]
    counts = part.setdefault("counts", {})
    counts[change.execution_status] = counts.get(change.execution_status, 0) + 1


class _FindingsFull(Exception):
    """Enough findings are waiting on the user — the run stops where it is.

    Carries the finished run summary so the caller returns a normal result
    rather than an error: stopping at the cap is a completed run, not a fault.
    """

    def __init__(self, result: dict):
        super().__init__("finding cap reached")
        self.result = result


def felix_run(job: dict, notion, client, options: RunOptions,
              checkpoint=lambda: None, base: Optional[Path] = None) -> dict:
    try:
        return _felix_run(job, notion, client, options, checkpoint, base)
    except _FindingsFull as full:
        return full.result


def _felix_run(job: dict, notion, client, options: RunOptions,
               checkpoint=lambda: None, base: Optional[Path] = None) -> dict:
    run_id = store.new_run_id()
    run = RunRecord(run_id=run_id, started=_now(), dry_run=options.dry_run,
                    databases=options.databases)
    store.save_run(run, base)
    job["felix_run_id"] = run_id
    seq = 1
    counts: dict = {"applied": 0, "planned": 0, "failed": 0, "skipped": 0,
                    "recommendations": 0, "proposed": 0, "merges": 0,
                    "relations_repaired": 0, "missing_filled": 0,
                    "formatting_fixed": 0, "icons_added": 0,
                    "high": 0, "medium": 0, "deferred": 0, "undone": 0}

    findings = 0

    def _finish(status: str, error: str = "") -> dict:
        run.finished = _now()
        run.status = status
        run.counts = counts
        run.error = error
        run.stages = _stage_durations(job.get("stages", []))
        store.save_run(run, base)
        return {"run_id": run_id, "counts": counts, "dry_run": options.dry_run,
                "status": status, "error": error,
                "stopped_at_cap": counts.get("stopped_at_cap", 0)}

    def _note_finding() -> None:
        """Every row that needs the user's say-so counts towards the cap.

        Felix works until ten are waiting and then stops. A run that keeps
        going past that just buries the queue; clearing it starts him again.
        """
        nonlocal findings
        findings += 1
        if options.max_findings and findings >= options.max_findings:
            counts["stopped_at_cap"] = findings
            raise _FindingsFull(_finish("done"))

    def record_recommendation(db_card: dict, prop: str, reason: str,
                              source: str = "", new_value: str = "",
                              detail: str = "") -> None:
        nonlocal seq
        _supersede_older(db_card["id"], prop, "recommendation")
        rec = ChangeRecord(
            change_id=store.change_id_for(run_id, seq), run_id=run_id,
            timestamp=_now(), database=db_card["db"],
            record_name=db_card["name"], record_id=db_card["id"],
            record_url=db_card["url"], change_type="recommendation",
            property_changed=prop, new_value=new_value, source=source,
            reason=reason, confidence="Low", execution_status="Recommended",
            detail=detail)
        seq += 1
        store.append_change(rec, base)
        _emit(job, rec)
        counts["recommendations"] += 1
        _note_finding()

    # Rows this run replaces. A finding re-detected on a later run used to be
    # appended alongside the old one, so the queue kept showing the FIRST
    # wording for ever — including evidence written under an older, shorter
    # truncation limit. The newest row wins; the old one is marked Superseded
    # rather than deleted, so the history stays intact.
    def _supersede_older(card_id: str, prop: str, ctype: str) -> None:
        for old in store.list_all_changes(base=base, review="Awaiting Review",
                                          limit=5000):
            if (old.run_id != run_id and old.record_id == card_id
                    and old.property_changed == prop
                    and old.change_type == ctype
                    and old.execution_status != "Applied"):
                store.update_change(old.change_id,
                                    {"review_status": "Superseded"}, base)

    def record_proposal(db_card: dict, prop: str, value: str, ptype: str,
                        reason: str, source: str = "") -> None:
        """A concrete, ready-to-apply change that waits for the user's
        approval. The exact Notion payload is stored in the snapshot so
        pressing Approve executes precisely this — nothing is re-derived."""
        nonlocal seq
        _supersede_older(db_card["id"], prop, "fill_missing")
        cid = store.change_id_for(run_id, seq)
        seq += 1
        # Carry what kind of value this is, and the workspace's own options
        # for it, so the reviewer can correct the wording or pick different
        # tags before approving rather than approving something not quite right.
        kind = ptype if ptype in ("select", "multi_select", "status",
                                  "rich_text", "title", "url",
                                  "phone_number") else ""
        rec = ChangeRecord(
            change_id=cid, run_id=run_id, timestamp=_now(),
            database=db_card["db"], record_name=db_card["name"],
            record_id=db_card["id"], record_url=db_card["url"],
            change_type="fill_missing", property_changed=prop,
            previous_value=str(db_card["plain"].get(prop) or ""),
            new_value=str(value)[:1900], source=source, reason=reason,
            confidence="Medium", execution_status="Proposed",
            value_kind=kind,
            value_options=list((options_by_db.get(db_card["db"]) or {})
                               .get(prop) or []))
        store.save_snapshot(cid, {
            "kind": "proposal", "record_id": db_card["id"],
            "database": db_card["db"],
            "planned": {"properties": {prop: _prop_payload(ptype, value)}},
            "expect_prop": prop,
            "scanned_plain": db_card["plain"].get(prop),
            "scanned_raw": db_card["raw"]}, base)
        store.append_change(rec, base)
        _emit(job, rec)
        counts["proposed"] = counts.get("proposed", 0) + 1
        _note_finding()

    def record_proposal_payload(db_card: dict, prop: str, shown: str,
                                payload: dict, reason: str, source: str = "",
                                previous: str = "", new_ids=None,
                                prev_ids=None) -> None:
        """Same contract as record_proposal for changes whose payload is built
        by the caller — relations, where the ids matter and a formatted value
        would lose them."""
        nonlocal seq
        cid = store.change_id_for(run_id, seq)
        seq += 1
        rec = ChangeRecord(
            change_id=cid, run_id=run_id, timestamp=_now(),
            database=db_card["db"], record_name=db_card["name"],
            record_id=db_card["id"], record_url=db_card["url"],
            change_type="fill_missing", property_changed=prop,
            previous_value=str(previous)[:1900], new_value=str(shown)[:1900],
            previous_relation_ids=prev_ids or [], new_relation_ids=new_ids or [],
            source=source, reason=reason,
            confidence="Medium", execution_status="Proposed")
        store.save_snapshot(cid, {
            "kind": "proposal", "record_id": db_card["id"],
            "database": db_card["db"], "planned": payload,
            "expect_prop": prop,
            "scanned_plain": db_card["plain"].get(prop),
            "scanned_raw": db_card["raw"]}, base)
        store.append_change(rec, base)
        _emit(job, rec)
        counts["proposed"] = counts.get("proposed", 0) + 1
        _note_finding()

    def record_create_company(db_card: dict, prop: str, company: str,
                              reason: str, source: str = "") -> None:
        """Approving this creates the company AND links it. Held as its own
        snapshot kind because it is a two-step write, not a property edit."""
        nonlocal seq
        cid = store.change_id_for(run_id, seq)
        seq += 1
        rec = ChangeRecord(
            change_id=cid, run_id=run_id, timestamp=_now(),
            database=db_card["db"], record_name=db_card["name"],
            record_id=db_card["id"], record_url=db_card["url"],
            change_type="create_company", property_changed=prop,
            previous_value="", new_value=company[:1900],
            source=source, reason=reason,
            confidence="Medium", execution_status="Proposed")
        store.save_snapshot(cid, {
            "kind": "create_company", "record_id": db_card["id"],
            "database": db_card["db"], "company_name": company,
            "link_property": prop,
            "existing_ids": db_card["relations"].get(prop, [])}, base)
        store.append_change(rec, base)
        _emit(job, rec)
        counts["proposed"] = counts.get("proposed", 0) + 1
        _note_finding()

    def record_photo(db_card: dict, photo_url: str, profile_url: str,
                     source: str) -> None:
        """A profile photo to drop into the contact's page body on approval."""
        nonlocal seq
        cid = store.change_id_for(run_id, seq)
        seq += 1
        rec = ChangeRecord(
            change_id=cid, run_id=run_id, timestamp=_now(),
            database=db_card["db"], record_name=db_card["name"],
            record_id=db_card["id"], record_url=db_card["url"],
            change_type="add_photo", property_changed="(page body)",
            previous_value="", new_value=photo_url[:1900],
            source=source,
            reason="profile photo found with the LinkedIn profile"
                   + (f" ({profile_url[:120]})" if profile_url else ""),
            confidence="Medium", execution_status="Proposed")
        store.save_snapshot(cid, {
            "kind": "add_photo", "record_id": db_card["id"],
            "database": db_card["db"], "photo_url": photo_url,
            "profile_url": profile_url}, base)
        store.append_change(rec, base)
        _emit(job, rec)
        counts["proposed"] = counts.get("proposed", 0) + 1
        _note_finding()

    # ---- Phase 0: preflight ------------------------------------------------ #
    _stage(job, "Preflight", "confirming live database schemas")
    checkpoint()
    live = notion.live
    db_ids = {k: (f() or "") for k, f in _DB_IDS.items()}
    schemas: dict = {}
    options_by_db: dict = {}
    relation_map: dict = {}
    prop_ids: dict = {}
    if live:
        def _norm(s: str) -> str:
            return (s or "").replace("-", "").lower()

        id_to_key = {_norm(v): k for k, v in db_ids.items() if v}
        for key in options.databases:
            if not db_ids.get(key):
                continue
            schema = notion.retrieve_database(db_ids[key])
            props = schema.get("properties") or {}
            schemas[key] = set(props)
            sel = {}
            for name, p in props.items():
                prop_ids[(key, name)] = p.get("id", "")
                if p.get("type") in ("select", "multi_select", "status"):
                    sel[name] = [o["name"] for o in p.get(p["type"], {})
                                 .get("options", [])]
                if p.get("type") == "relation":
                    target = (p.get("relation") or {}).get("database_id", "")
                    target_key = id_to_key.get(_norm(target), "")
                    if target_key:
                        relation_map[(key, name)] = target_key
            options_by_db[key] = sel
    else:
        fx = _mock_workspace()
        schemas = fx["schemas"]
        relation_map = fx["relation_map"]
        options_by_db = fx["options"]

    # ---- Phase 1: undo sweep ---------------------------------------------- #
    requested = store.list_all_changes(base, review="Undo Requested", limit=100)
    if requested and not options.dry_run:
        _stage(job, "Undo sweep", f"{len(requested)} undo request(s)")
        for c in requested:
            checkpoint()
            out = undo.undo_change(notion, c.change_id, base)
            if out.get("status") == "Undone":
                counts["undone"] += 1

    # ---- Phase 2: strict full scan ----------------------------------------- #
    _stage(job, "Scanning", " + ".join(options.databases))
    cards_by_db: dict[str, list[dict]] = {}
    for key in options.databases:
        checkpoint()
        if live:
            if not db_ids.get(key):
                continue
            pids = None
            if key == "funds":
                pids = notion._property_ids(db_ids[key], _FUNDS_SCAN_PROPS) or None
            try:
                pages = notion.query_database_raw(db_ids[key], strict=True,
                                                  property_ids=pids)
            except NotionPartialResult as e:
                return _finish("failed",
                               f"partial scan of {key} ({len(e.rows)} rows) — "
                               "aborted: clean-up decisions need the complete "
                               "database")
        else:
            pages = _mock_workspace()["pages"].get(key, [])
        cards_by_db[key] = [detect.card_from_page(p, key) for p in pages]
    ids_by_db = {k: {c["id"] for c in v if not c["archived"]}
                 for k, v in cards_by_db.items()}
    all_cards = [c for v in cards_by_db.values() for c in v]
    names_by_id = {c["id"]: c["name"] for c in all_cards}
    # Which meeting notes point at each record — a contact with real meeting
    # history is not the copy to archive, and it tells the reviewer at a
    # glance which of the two the workspace actually uses.
    notes_by_id: dict = {}
    notes_by_target: dict = {}
    for note in cards_by_db.get("notes", []):
        for ids in note["relations"].values():
            for i in ids:
                notes_by_id.setdefault(i, []).append(note["name"])
                notes_by_target.setdefault(i, []).append(note)
    job["partial"] = job.get("partial") or {}
    job["partial"]["scanned"] = {k: len(v) for k, v in cards_by_db.items()}

    # ---- Phase 3: deterministic detection ---------------------------------- #
    _stage(job, "Detecting issues", "duplicates, gaps, broken links, formatting")
    checkpoint()
    planned: list[dict] = []       # simple changes
    merges: list[dict] = []
    junk_fields: list[dict] = []   # email-field clutter → parse into proposals

    for key, cards in cards_by_db.items():
        # Formatting — High.
        for f in detect.find_formatting_issues(cards):
            prop = f["property"]
            payload = dict(f["card"]["raw"].get(prop, {}))
            ptype = payload.pop("type", "")
            payload.pop("id", None)
            if ptype == "title":
                payload = {"title": [{"text": {"content": f["to"]}}]}
            elif ptype == "email":
                payload = {"email": f["to"]}
            else:
                continue
            if f["kind"] == "email_extract" and len(f.get("junk", "")) >= 12:
                junk_fields.append({"card": f["card"], "original": f["from"]})
            planned.append({
                "db": key, "card": f["card"], "change_type": "fix_formatting",
                "property": prop, "previous": f["from"], "new": f["to"],
                "payload": {"properties": {prop: payload}},
                "expect_prop": prop, "scanned_plain": f["from"],
                "confidence": "High",
                "source": ("text that is not part of the address"
                           if f["kind"] == "email_extract"
                           else "mechanical formatting rule"),
                "reason": _FORMAT_REASONS.get(f["kind"],
                                              "whitespace/case normalisation")})

        # Dangling relations — High.
        for d in detect.find_dangling_relations(cards, relation_map, ids_by_db):
            planned.append({
                "db": key, "card": d["card"], "change_type": "fix_relation",
                "property": d["property"],
                "previous": ", ".join(d["dangling"] + d["keep"]),
                "new": ", ".join(d["keep"]),
                "prev_ids": d["dangling"] + d["keep"], "new_ids": d["keep"],
                "payload": {"properties": {d["property"]: {
                    "relation": [{"id": i} for i in d["keep"]]}}},
                "expect_prop": d["property"],
                "scanned_plain": sorted(d["dangling"] + d["keep"]),
                "confidence": "High",
                "source": f"target pages absent from the {relation_map.get((key, d['property']))} scan",
                "reason": "relation points at archived/removed pages"})

        # Missing icons — recommendation unless a standard icon is configured.
        cfg = store.load_config(base)
        std_icon = (cfg.get("standard_icons") or {}).get(key, "")
        for ic in detect.find_icon_issues(cards, std_icon):
            if std_icon:
                planned.append({
                    "db": key, "card": ic["card"], "change_type": "fix_icon",
                    "property": "(icon)", "previous": "none", "new": std_icon,
                    "payload": {"icon": {"type": "emoji", "emoji": std_icon}},
                    "expect_prop": "", "scanned_plain": None,
                    "confidence": "High",
                    "source": "standard icon configured for this database",
                    "reason": "missing icon"})
            # No configured standard → not even a recommendation; silence
            # beats hundreds of un-actionable rows.

    # Employer inference — exact corporate domain, High.
    if "contacts" in cards_by_db and "companies" in cards_by_db and \
            ("contacts", "Employed By") in relation_map or not live:
        inferred = detect.infer_employers(cards_by_db.get("contacts", []),
                                          cards_by_db.get("companies", []))
        for link in inferred["links"]:
            c = link["contact"]
            new_ids = c["relations"].get("Employed By", []) + [link["company"]["id"]]
            planned.append({
                "db": "contacts", "card": c, "change_type": "fill_missing",
                "property": "Employed By",
                "previous": "", "new": link["company"]["name"],
                "prev_ids": [], "new_ids": new_ids,
                "payload": {"properties": {"Employed By": {
                    "relation": [{"id": i} for i in new_ids]}}},
                "expect_prop": "Employed By", "scanned_plain": [],
                "confidence": "High",
                "source": f"exact corporate email-domain match: {link['domain']}",
                "reason": "employer identified by the contact's corporate domain"})
        for cand in inferred["company_candidates"]:
            record_recommendation(
                cand["contact"], "Employed By",
                "corporate domain matches no existing company — confirm before "
                "creating one", source=f"email domain {cand['domain']}")

    # Pairs the user has already decided (or research has settled) are done —
    # never re-flagged, never re-searched.
    resolved_pairs = store.load_resolved_pairs(base)

    def _pair_resolved(x: dict, y: dict) -> bool:
        return store.pair_key(x["id"], y["id"]) in resolved_pairs

    # Exact duplicates — High merges. A contested same-name group is NOT one:
    # it is routed to adjudication and the web alongside the fuzzy pairs.
    contested_pairs: list[dict] = []
    for key, cards in cards_by_db.items():
        if key not in DEDUPE_DBS:
            continue
        for group in detect.find_exact_duplicate_groups(cards):
            survivor, losers = detect.choose_survivor(group["cards"])
            for loser in losers:
                if _pair_resolved(survivor, loser):
                    continue
                if group.get("contested"):
                    contested_pairs.append({
                        "db": key, "a": survivor, "b": loser, "score": 1.0,
                        "contested": group["contested"]})
                    continue
                merges.append({
                    "db": key, "survivor": survivor, "loser": loser,
                    "confidence": "High",
                    "source": f"exact {group['evidence']} match: {group['key']}",
                    "reason": "records share an exact identifier",
                    "web_check": f"not needed — the two share an exact "
                                 f"{group['evidence']}"})

    # ---- Phase 3b: execute the deterministic fixes found so far ------------ #
    # Formatting, dangling relations, icons, employer-domain links and exact
    # duplicates need no model call — writing them now, before adjudication
    # and enrichment, means the run shows real applied progress within
    # seconds even on a workspace where the LLM/research phases end up
    # taking many minutes, and a crash or cancellation during those later
    # phases does not cost the cheap fixes this scan already found.
    write_remaining = options.max_writes
    merge_remaining = options.max_merges
    archived_ids: list[str] = []

    def _execute_batch(planned_items: list[dict], merge_items: list[dict],
                       stage_label: str) -> None:
        nonlocal seq, write_remaining, merge_remaining
        order = {"fix_formatting": 0, "fix_icon": 1, "fill_missing": 2,
                 "fix_relation": 3}
        planned_items = sorted(planned_items,
                               key=lambda p: order.get(p["change_type"], 2))
        merge_items = merge_items[:merge_remaining]
        merge_remaining -= len(merge_items)
        run_list = planned_items[:write_remaining]
        write_remaining -= len(run_list)
        counts["deferred"] += len(planned_items) - len(run_list)
        if not run_list and not merge_items:
            return
        mode = "recording the would-do plan" if options.dry_run else "applying fixes"
        _stage(job, stage_label, f"{len(run_list)} change(s) + "
                                 f"{len(merge_items)} merge(s) — {mode}")
        job["total"] = job.get("total", 0) + len(run_list) + len(merge_items)
        job.setdefault("done", 0)
        for p in run_list:
            checkpoint()
            change = ChangeRecord(
                change_id=store.change_id_for(run_id, seq), run_id=run_id,
                timestamp=_now(), database=p["db"], record_name=p["card"]["name"],
                record_id=p["card"]["id"], record_url=p["card"]["url"],
                change_type=p["change_type"], property_changed=p["property"],
                previous_value=str(p["previous"])[:1900],
                new_value=str(p["new"])[:1900],
                previous_relation_ids=p.get("prev_ids", []),
                new_relation_ids=p.get("new_ids", []),
                source=p["source"], reason=p["reason"], confidence=p["confidence"])
            seq += 1
            change = execute.apply_change(
                notion, change, p["payload"], expect_prop=p["expect_prop"],
                scanned_plain=p["scanned_plain"], dry_run=options.dry_run,
                quiet_minutes=options.quiet_minutes,
                scanned_raw=p["card"]["raw"], base=base)
            _emit(job, change)
            job["done"] += 1
            st = change.execution_status
            if st == "Applied":
                counts["applied"] += 1
                counts[{"fix_formatting": "formatting_fixed",
                        "fix_relation": "relations_repaired",
                        "fill_missing": "missing_filled",
                        "fix_icon": "icons_added"}.get(
                            change.change_type, "formatting_fixed")] += 1
                counts["high" if change.confidence == "High" else "medium"] += 1
            elif st == "Planned (dry-run)":
                counts["planned"] += 1
            elif st == "Failed":
                counts["failed"] += 1
            elif st == "Skipped":
                counts["skipped"] += 1

        for m in merge_items:
            checkpoint()
            transfers = detect.plan_merge_transfers(m["survivor"], m["loser"])
            records, seq = execute.execute_merge(
                notion, run_id, seq, m["survivor"], m["loser"], transfers,
                all_cards, prop_ids, m["confidence"], m["source"], m["reason"],
                dry_run=options.dry_run, quiet_minutes=options.quiet_minutes,
                base=base, on_change=lambda c: _emit(job, c),
                detail=_merge_detail(m["survivor"], m["loser"], transfers,
                                     names_by_id, notes_by_id,
                                     m.get("web_check", "")))
            job["done"] += 1
            parent = records[0]
            if parent.execution_status == "Applied":
                counts["applied"] += 1
                counts["merges"] += 1
                counts["high" if parent.confidence == "High" else "medium"] += 1
                archived_ids.append(m["loser"]["id"])
            elif parent.execution_status == "Planned (dry-run)":
                counts["planned"] += 1
                counts["merges"] += 1
            elif parent.execution_status == "Failed":
                counts["failed"] += 1

    # Ids already spoken for by an exact-duplicate merge — captured BEFORE
    # the reset below, and carried forward (Phase 4 adds to it as its own
    # merges are decided) so a web-research verdict can never propose merging
    # a record this run already archived.
    merged_ids = {m["loser"]["id"] for m in merges} | \
                 {m["survivor"]["id"] for m in merges}
    _execute_batch(planned, merges, "Executing mechanical fixes")
    # Fresh lists: everything from here on (evidence-based fills, web-research
    # -confirmed merges) is genuinely LLM/research-derived and executes later,
    # at the run's original point, with whatever write/merge budget remains.
    planned, merges = [], []

    # ---- Phase 4: LLM adjudication ----------------------------------------- #
    fuzzy_all = list(contested_pairs)   # same name, contradicting records
    for key, cards in cards_by_db.items():
        if key not in DEDUPE_DBS:
            continue
        for p in detect.find_fuzzy_duplicate_pairs(cards):
            if _pair_resolved(p["a"], p["b"]):
                continue                # decided in an earlier run — stay quiet
            if any(q["a"]["id"] == p["a"]["id"] and q["b"]["id"] == p["b"]["id"]
                   for q in contested_pairs):
                continue                # already queued as a contested name
            p["db"] = key
            fuzzy_all.append(p)

    # Pairs the cheap model has already classified, reused as long as
    # neither record has changed since (store.cached_verdict checks the
    # fingerprints). A cached "distinct" is settled and stays quiet, same as
    # a resolved pair; "duplicate"/"unsure" go straight into the same
    # research queue a fresh verdict of that kind would, without spending
    # another CLI call to re-derive what is already known.
    to_research: list[tuple] = []
    still_uncached: list[dict] = []
    for p in fuzzy_all:
        fp_a, fp_b = detect.card_fingerprint(p["a"]), detect.card_fingerprint(p["b"])
        cached = store.cached_verdict(p["a"]["id"], p["b"]["id"], fp_a, fp_b, base)
        if cached is None:
            still_uncached.append(p)
        elif cached["verdict"] != "distinct":
            to_research.append((p, {"verdict": cached["verdict"],
                                    "reason": cached.get("reason", "")
                                             or "cached from an earlier run"}))
    fuzzy_all = still_uncached

    # The cap applies here too, not just to what gets WRITTEN: adjudicating a
    # pair the run has no room left to act on is a wasted CLI call. Trimmed
    # to remaining findings headroom (worst case, one finding per pair) —
    # conservative on purpose, since some pairs resolve as merges or silent
    # "distinct" verdicts rather than findings at all. Whatever gets left
    # off this run stays a candidate for the next one.
    if fuzzy_all and options.max_findings:
        remaining = max(0, options.max_findings - findings)
        fuzzy_all = fuzzy_all[:remaining]
    if fuzzy_all:
        _stage(job, "Adjudicating look-alikes",
               f"{len(fuzzy_all)} candidate pair(s)")
        checkpoint()
    # EVERY look-alike pair goes to web research before anything is proposed:
    # a name score plus a model opinion is not evidence that two people are
    # the same person, and it cannot tell a shared name from a job move.
    for verdict in adjudicate.adjudicate_duplicates(
            client, fuzzy_all, max_calls=max(1, options.max_llm_calls // 2)):
        p = verdict["pair"]
        v = verdict["verdict"]
        if v in ("duplicate", "distinct", "unsure"):
            store.save_adjudication_verdict(
                p["a"]["id"], p["b"]["id"],
                detect.card_fingerprint(p["a"]), detect.card_fingerprint(p["b"]),
                v, verdict.get("reason", ""), base)
        if v in ("duplicate", "unsure"):
            to_research.append((p, verdict))
        elif v == "deferred":
            counts["deferred"] += 1

    # An ordinary run spends nothing on the web: it lists what it could not
    # settle and waits to be asked.
    pending: list[dict] = []

    def defer_to_web(kind: str, card: dict, field: str = "",
                     detail: str = "") -> None:
        pending.append({"kind": kind, "database": card.get("db", ""),
                        "record_id": card.get("id", ""),
                        "record_name": card.get("name", ""),
                        "record_url": card.get("url", ""),
                        "field": field, "detail": detail})

    research_budget = (options.max_research
                       if client is not None and options.web_research else 0)
    if to_research and not options.web_research:
        for p, verdict in to_research:
            why = p.get("contested")
            defer_to_web("duplicate", p["a"], "(possible duplicate)",
                         f"may duplicate '{p['b']['name']}' — "
                         + (f"same name, but {why}. " if why else "")
                         + verdict["reason"][:200])
        to_research = []
    if to_research and research_budget > 0:
        _stage(job, "Researching online",
               f"{min(len(to_research), research_budget)} look-alike pair(s)")
        checkpoint()

    def _pair_detail(a: dict, b: dict, web_check: str = "") -> str:
        """Side-by-side of both records — same evidence a merge row carries,
        so a possible-duplicate can be judged without opening Notion."""
        surv, losers = detect.choose_survivor([a, b])
        return _merge_detail(surv, losers[0],
                             detect.plan_merge_transfers(surv, losers[0]),
                             names_by_id, notes_by_id, web_check)

    for p, verdict in to_research:
        pair_detail = _pair_detail(p["a"], p["b"], "not yet web-checked")
        if research_budget <= 0:
            # Out of budget: never merge on similarity alone — flag it and let
            # a later run do the search.
            record_recommendation(
                p["a"], "(possible duplicate)",
                f"may duplicate '{p['b']['name']}' — "
                + (f"same name, but {p['contested']}. " if p.get("contested") else "")
                + f"{verdict['reason'][:600]} "
                "(queued for web research on a later run)",
                source=f"name similarity {p['score']}, not yet web-checked",
                detail=pair_detail)
            continue
        research_budget -= 1
        try:
            r = research.research_duplicate(client, p["a"], p["b"], names_by_id)
        except Exception:  # noqa: BLE001
            r = {"verdict": "unsure", "confidence": "low",
                 "explanation": "the research call failed", "evidence": "",
                 "employer_check": ""}
        emp = (r.get("employer_check") or "").strip()
        emp_txt = f" Employers: {emp[:300]}" if emp else ""
        _v = r.get("verdict", "unsure")
        pair_detail = _pair_detail(
            p["a"], p["b"],
            f"web-checked: {'same person' if _v == 'duplicate' else 'different people' if _v == 'distinct' else 'inconclusive'}"
            + (f" ({r['confidence']} confidence)" if r.get("confidence") else "")
            + (f" — {emp[:200]}" if emp else ""))
        if (r.get("verdict") == "duplicate"
                and r.get("confidence") in ("high", "medium")
                and p["a"]["id"] not in merged_ids
                and p["b"]["id"] not in merged_ids):
            surv, losers = detect.choose_survivor([p["a"], p["b"]])
            merged_ids |= {p["a"]["id"], p["b"]["id"]}
            store.resolve_pair(p["a"]["id"], p["b"]["id"],
                               "research-duplicate", base)
            merges.append({
                "db": p["db"], "survivor": surv, "loser": losers[0],
                "confidence": "Medium",
                "source": f"online research — {_clip(r.get('evidence', ''))}",
                "reason": "researched online: same entity — "
                          f"{r.get('explanation', '')[:500]}{emp_txt}",
                "web_check": f"web-checked: same person "
                             f"({r.get('confidence', '')} confidence)"
                             + (f" — {emp[:200]}" if emp else "")})
        elif r.get("verdict") == "distinct":
            store.resolve_pair(p["a"]["id"], p["b"]["id"],
                               "research-distinct", base)
            record_recommendation(
                p["a"], "(possible duplicate)",
                f"researched online: DISTINCT from '{p['b']['name']}' — "
                f"{r.get('explanation', '')[:600]}{emp_txt}",
                source=f"web research — {_clip(r.get('evidence', ''))}",
                detail=pair_detail)
        else:
            lean = r.get("lean", "")
            lean_txt = (f" On balance the research leans {lean.upper()}."
                        if lean in ("duplicate", "distinct") else "")
            record_recommendation(
                p["a"], "(possible duplicate)",
                f"may duplicate '{p['b']['name']}' — online research was "
                f"inconclusive: {r.get('explanation', '')[:600]}{emp_txt}"
                f"{lean_txt}",
                source=f"web research — {_clip(r.get('evidence', ''))}"
                       if r.get("evidence") else f"name similarity {p['score']}",
                detail=pair_detail)

    # Evidence-based fills for missing text/select properties.
    fill_tasks = _build_fill_tasks(cards_by_db, schemas, options_by_db,
                                   relation_map, notion, live)
    if fill_tasks:
        _stage(job, "Evaluating evidence",
               f"{len(fill_tasks)} missing propert(ies) with note evidence")
        checkpoint()
    for prop_fill in adjudicate.evaluate_missing_info(
            client, fill_tasks, max_calls=max(1, options.max_llm_calls // 2)):
        t = prop_fill["task"]
        card = t["card"]
        if not prop_fill["verified"]:
            # The quote check gates AUTOMATIC writes; a human reading the
            # proposal can still adopt it — so it becomes an approvable
            # proposal rather than a dead-end note.
            # Naming the note without saying what it said made this
            # unreviewable — the whole question is whether the passage
            # actually supports the value.
            quote = (prop_fill.get("evidence_quote") or "").strip()
            record_proposal(
                card, t["property"], prop_fill["value"],
                t.get("ptype", "rich_text"),
                reason="proposed from linked notes, but the supporting quote "
                       "did not verify word-for-word — approve only if it "
                       "reads right to you",
                source=(f"{t.get('source_label', 'linked notes')} — "
                        f"paraphrased as \"{_clip(quote, 600)}\"" if quote
                        else t.get("source_label", "linked notes")))
            continue
        ptype = t.get("ptype", "rich_text")
        payload = ({"select": {"name": prop_fill["value"]}} if ptype == "select"
                   else {"rich_text": [{"text": {"content": prop_fill["value"][:1900]}}]})
        planned.append({
            "db": card["db"], "card": card, "change_type": "fill_missing",
            "property": t["property"], "previous": "",
            "new": prop_fill["value"],
            "payload": {"properties": {t["property"]: payload}},
            "expect_prop": t["property"], "scanned_plain": "",
            "confidence": "High" if prop_fill["confidence"] == "high" else "Medium",
            "source": f"{t.get('source_label', 'linked note')} — \"{_clip(prop_fill['evidence_quote'], 600)}\"",
            "reason": "explicit information in linked material"})

    # Email-field clutter → parse job titles, phone numbers, descriptions out
    # of the junk and propose each as its own approvable field change.
    junk_tasks: list[dict] = []
    for j in junk_fields[:20]:
        card = j["card"]
        evidence = (f"Text found in the email field of \"{card['name']}\" "
                    f"alongside the address: \"{j['original']}\"")
        for prop, raw_payload in card["raw"].items():
            ptype = raw_payload.get("type", "")
            if ptype not in ("rich_text", "select", "phone_number", "url"):
                continue
            if not detect._empty(card["plain"].get(prop)):
                continue
            junk_tasks.append({
                "card": card, "property": prop, "ptype": ptype,
                "options": options_by_db.get(card["db"], {}).get(prop),
                "evidence": evidence,
                "source_label": "text found in the email field"})
            if len(junk_tasks) >= 40:
                break
    if junk_tasks:
        _stage(job, "Parsing email-field clutter",
               f"{len(junk_tasks)} candidate field(s)")
        checkpoint()
    for pr in adjudicate.evaluate_missing_info(client, junk_tasks, max_calls=4):
        t = pr["task"]
        note = ("" if pr["verified"]
                else " (not quoted word-for-word — double-check it)")
        record_proposal(
            t["card"], t["property"], pr["value"], t.get("ptype", "rich_text"),
            reason="parsed from the extra text that was sitting in the email "
                   f"field{note}",
            source=f"email field text — \"{_clip(pr['evidence_quote'], 500)}\"")

    # Asset class / geography gaps on funds → web lookup. Values are validated
    # against the live select options in code; each lands as a Proposed change
    # the user approves.
    if "funds" in cards_by_db:
        fund_opts = options_by_db.get("funds", {})
        research_props = [pr for pr in ("Asset Class", "Geographic Focus")
                          if fund_opts.get(pr)]
        targets = []
        for miss in detect.find_missing_props(cards_by_db["funds"], "funds",
                                              schemas.get("funds", set())):
            wanted = [{"property": pr, "options": fund_opts[pr]}
                      for pr in miss["missing"] if pr in research_props]
            if wanted:
                targets.append((miss["card"], wanted))
        if not options.web_research:
            for card, wanted in targets:
                for w in wanted:
                    defer_to_web("fund_tags", card, w["property"])
            targets = []
        if targets:
            _stage(job, "Researching fund classifications",
                   f"{min(len(targets), research_budget)} fund(s)")
            checkpoint()
        for card, wanted in targets:
            if research_budget <= 0:
                break
            research_budget -= 1
            comp_rel = (card["relations"].get("Company")
                        or card["relations"].get("Company Name") or [])
            company = names_by_id.get(comp_rel[0], "") if comp_rel else \
                str(card["plain"].get("Company Name") or "")
            try:
                found = research.research_fund_fields(client, card, wanted,
                                                      company)
            except Exception:  # noqa: BLE001
                found = []
            for pr in found:
                # These are multi-selects in the live workspace; the payload
                # type comes from the record itself rather than an assumption.
                ptype = (card["raw"].get(pr["property"], {}) or {}).get(
                    "type", "multi_select")
                record_proposal(
                    card, pr["property"], pr["value"], ptype,
                    reason=f"researched online: {_clip(pr['explanation'], 600)}",
                    source=f"web — {_clip(pr['source'], 500)}")

    # ---- Phase 4c: enrichment — the gaps rules cannot close ----------------- #
    # Notes and attachments first, the web second. Relations are proposed by
    # NAME and resolved against the real scan here; the model never supplies a
    # page id, and a name that matches nothing is either created (companies,
    # when the identification is solid) or left for the reviewer.
    def _notes_text_for(card_id: str, limit: int = 3) -> str:
        parts = []
        for n in notes_by_target.get(card_id, [])[:limit]:
            body = ""
            if live:
                try:
                    body = notion.get_page_text(n["id"], max_depth=1)[:2500]
                except Exception:  # noqa: BLE001
                    body = ""
            parts.append(f"Note \"{n['name']}\":\n{body}")
        return "\n\n".join(parts)

    def _relation_proposal(card, prop, target, reason, source):
        """Link an existing record — the payload keeps the relations already
        there and adds this one."""
        existing = card["relations"].get(prop, [])
        if target["id"] in existing:
            return
        new_ids = existing + [target["id"]]
        record_proposal_payload(
            card, prop, target["name"],
            {"properties": {prop: {"relation": [{"id": i} for i in new_ids]}}},
            reason=reason, source=source,
            previous=", ".join(names_by_id.get(i, "") for i in existing),
            new_ids=new_ids, prev_ids=existing)

    companies = cards_by_db.get("companies", [])
    contacts = cards_by_db.get("contacts", [])

    if client is not None:
        _stage(job, "Filling gaps",
               "from meeting notes" + (" and the web" if options.web_research
                                       else ""))
        checkpoint()

    # -- contacts: employer, title, description, LinkedIn photo -------------- #
    contact_props = set(schemas.get("contacts", set()))
    emp_prop = detect.match_prop(contact_props, "Employed By")
    for miss in detect.find_missing_props(contacts, "contacts", contact_props):
        if client is None:
            break
        card = miss["card"]
        wanted = []
        if emp_prop and emp_prop in miss["missing"]:
            wanted.append("employer")
        for label, key in (("Title", "title"), ("Description", "description")):
            prop = detect.match_prop(contact_props, label)
            if prop and prop in miss["missing"] and key not in wanted:
                wanted.append(key)
        if not wanted:
            continue
        notes_text = _notes_text_for(card["id"])
        # Without the user's go-ahead there is no web search. A contact with
        # linked notes can still be settled from them; one with nothing to
        # read goes straight on the list.
        if not options.web_research and not notes_text.strip():
            for w in wanted:
                defer_to_web("employer" if w == "employer" else "contact_field",
                             card, emp_prop if w == "employer" else w)
            continue
        if options.web_research and research_budget <= 0:
            break
        if options.web_research:
            research_budget -= 1
        checkpoint()
        try:
            found = enrich.research_contact(client, card, notes_text, wanted,
                                            use_web=options.web_research)
        except Exception:  # noqa: BLE001
            continue
        if not options.web_research and found.get("confidence") == "low":
            # The notes did not settle it — offer it up for searching.
            for w in wanted:
                defer_to_web("employer" if w == "employer" else "contact_field",
                             card, emp_prop if w == "employer" else w)
            continue
        if found.get("confidence") == "low":
            continue
        where = ("linked meeting notes" if not found.get("used_web")
                 else "web research")
        src = f"{where} — {_clip(found.get('evidence', ''))}"

        employer = (found.get("employer") or "").strip()
        if employer and emp_prop and emp_prop in miss["missing"]:
            hit = enrich.resolve_name(employer, companies)
            if hit["match"]:
                _relation_proposal(
                    card, emp_prop, hit["match"],
                    f"identified as working for {employer}", src)
            elif hit["near"]:
                record_recommendation(
                    card, emp_prop,
                    f"identified as working for '{employer}', which is close "
                    f"to the existing company '{hit['near']['name']}' "
                    f"(similarity {hit['score']}) but not the same name — "
                    "confirm which before linking",
                    source=src)
            elif found.get("confidence") == "high":
                # No such company on record: create it, then link. Only on a
                # solid identification, and only once the name has been
                # checked against every existing company above.
                record_create_company(card, emp_prop, employer,
                                      reason=f"'{card['name']}' works for "
                                             f"{employer}, which is not yet in "
                                             "Companies",
                                      source=src)
        elif emp_prop and emp_prop in miss["missing"] and not options.web_research:
            defer_to_web("employer", card, emp_prop)
        for label, key in (("Title", "title"), ("Description", "description")):
            prop = detect.match_prop(contact_props, label)
            value = (found.get(key) or "").strip()
            if value and prop and prop in miss["missing"]:
                record_proposal(card, prop, value, "rich_text",
                                reason=f"{where}: {_clip(found.get('evidence', ''), 600)}",
                                source=src)
        photo = (found.get("photo_url") or "").strip()
        if photo.startswith("http") and found.get("confidence") == "high":
            record_photo(card, photo, found.get("linkedin_url", ""), src)

    # -- funds: which manager runs this fund --------------------------------- #
    fund_props = set(schemas.get("funds", set()))
    co_prop = detect.match_prop(fund_props, "Company", "Manager")
    if co_prop and co_prop in {p for (d, p) in relation_map if d == "funds"}:
        for miss in detect.find_missing_props(cards_by_db.get("funds", []),
                                              "funds", fund_props):
            if client is None:
                break
            card = miss["card"]
            if co_prop not in miss["missing"]:
                continue
            notes_text = _notes_text_for(card["id"])
            if not options.web_research and not notes_text.strip():
                defer_to_web("fund_company", card, co_prop)
                continue
            if options.web_research and research_budget <= 0:
                break
            if options.web_research:
                research_budget -= 1
            checkpoint()
            try:
                found = enrich.research_fund_company(
                    client, card, notes_text, use_web=options.web_research)
            except Exception:  # noqa: BLE001
                continue
            name = (found.get("company") or "").strip()
            if not name or found.get("confidence") == "low":
                if not options.web_research:
                    defer_to_web("fund_company", card, co_prop)
                continue
            src = f"research — {_clip(found.get('evidence', ''))}"
            hit = enrich.resolve_name(name, companies)
            if hit["match"]:
                _relation_proposal(card, co_prop, hit["match"],
                                   f"{card['name']} is managed by {name}", src)
            elif hit["near"]:
                record_recommendation(
                    card, co_prop,
                    f"managed by '{name}', close to the existing company "
                    f"'{hit['near']['name']}' (similarity {hit['score']}) — "
                    "confirm which before linking", source=src)
            elif found.get("confidence") == "high":
                record_create_company(
                    card, co_prop, name,
                    reason=f"'{card['name']}' is managed by {name}, which is "
                           "not yet in Companies", source=src)

    # -- notes: who was actually there, and what kind of meeting it was ------ #
    note_props = set(schemas.get("notes", set()))
    att_prop = next((p for p in ("Attendees", "Participants", "People")
                     if p in note_props), "")
    type_opts = options_by_db.get("notes", {}).get("Note Type") or []
    for miss in detect.find_missing_props(cards_by_db.get("notes", []),
                                          "notes", note_props):
        if research_budget <= 0:
            break
        card = miss["card"]
        want_att = bool(att_prop) and att_prop in miss["missing"]
        want_type = "Note Type" in miss["missing"] and bool(type_opts)
        if not (want_att or want_type):
            continue
        body = ""
        if live:
            try:
                body = notion.get_page_text(card["id"], max_depth=1)[:8000]
            except Exception:  # noqa: BLE001
                body = ""
        if not body.strip():
            continue
        research_budget -= 1
        checkpoint()
        try:
            found = enrich.infer_note_fields(client, card, body, type_opts,
                                             want_att, want_type)
        except Exception:  # noqa: BLE001
            continue
        if found.get("confidence") == "low":
            continue
        src = f"the note's own text — \"{_clip(found.get('evidence', ''), 600)}\""
        if want_type and found.get("note_type"):
            record_proposal(card, "Note Type", found["note_type"], "select",
                            reason="inferred from what the meeting actually was",
                            source=src)
        if want_att and found.get("attendees"):
            matched, unmatched = [], []
            for person in found["attendees"][:12]:
                hit = enrich.resolve_name(person, contacts)
                (matched.append(hit["match"]) if hit["match"]
                 else unmatched.append(person))
            seen_ids, targets = set(), []
            for m in matched:
                if m["id"] not in seen_ids:
                    seen_ids.add(m["id"]); targets.append(m)
            if targets:
                existing = card["relations"].get(att_prop, [])
                new_ids = existing + [t["id"] for t in targets
                                      if t["id"] not in existing]
                if new_ids != existing:
                    record_proposal_payload(
                        card, att_prop,
                        ", ".join(t["name"] for t in targets),
                        {"properties": {att_prop: {
                            "relation": [{"id": i} for i in new_ids]}}},
                        reason="named in the note as present"
                               + (f"; no contact record for {', '.join(unmatched)}"
                                  if unmatched else ""),
                        source=src,
                        previous=", ".join(names_by_id.get(i, "") for i in existing),
                        new_ids=new_ids, prev_ids=existing)
            elif unmatched:
                record_recommendation(
                    card, att_prop,
                    "the note names " + ", ".join(unmatched)
                    + " as present, but none match a contact record — add them "
                      "as contacts first", source=src)

    # What the notes could not settle. Written whole each run, so the list the
    # user sees always reflects this scan — a gap filled since simply drops
    # off it. A web-research run clears it as it goes.
    store.save_pending_research(pending, base)
    counts["needs_web"] = len(pending)

    # ---- Phase 6: execute the LLM/research-derived changes ------------------ #
    # Same batch executor as Phase 3b — whatever write/merge budget the
    # mechanical fixes did not use is what these get.
    _execute_batch(planned, merges, "Executing")

    # ---- Phase 7: summarise ------------------------------------------------- #
    if not options.dry_run and (counts["applied"] or counts["undone"]):
        # Ids of pages this run archived: a delta sync cannot see an archive,
        # so they are dropped from the snapshot by name rather than by
        # throwing the whole snapshot away and re-pulling the workspace.
        notion.invalidate_cache(archived_ids=archived_ids)
    _stage(job, "Done", f"{counts['applied'] or counts['planned']} change(s) "
                        f"{'planned' if options.dry_run else 'applied'}, "
                        f"{counts['recommendations']} recommendation(s)")
    return _finish("done")


def _build_fill_tasks(cards_by_db: dict, schemas: dict, options_by_db: dict,
                      relation_map: dict, notion, live: bool,
                      cap: int = 30) -> list[dict]:
    """Missing text/select priority properties on records that have linked
    note evidence. Relations are never LLM-filled — page refs need identity,
    not inference."""
    notes = cards_by_db.get("notes", [])
    notes_by_target: dict[str, list[dict]] = {}
    for n in notes:
        for ids in n["relations"].values():
            for i in ids:
                notes_by_target.setdefault(i, []).append(n)

    tasks: list[dict] = []
    for key, cards in cards_by_db.items():
        if key == "notes":
            continue
        schema_props = schemas.get(key, set())
        for miss in detect.find_missing_props(cards, key, schema_props):
            card = miss["card"]
            linked_notes = notes_by_target.get(card["id"], [])[:3]
            if not linked_notes:
                continue
            evidence_parts = [f"record email domain: {card['domain']}"
                              if card["domain"] else ""]
            for n in linked_notes:
                text = ""
                if live:
                    try:
                        text = notion.get_page_text(n["id"], max_depth=1)[:3000]
                    except Exception:  # noqa: BLE001
                        text = ""
                evidence_parts.append(
                    f"Linked note \"{n['name']}\":\n{text or n['plain'].get('Thoughts / Considerations', '')}")
            evidence = "\n\n".join(p for p in evidence_parts if p)
            if len(evidence) < 40:
                continue
            for prop in miss["missing"]:
                raw = card["raw"].get(prop, {})
                ptype = raw.get("type", "")
                if ptype == "relation":
                    continue
                if ptype not in ("rich_text", "select"):
                    continue
                tasks.append({"card": card, "property": prop, "ptype": ptype,
                              "options": options_by_db.get(key, {}).get(prop),
                              "evidence": evidence,
                              "source_label": f"linked note \"{linked_notes[0]['name']}\""})
                if len(tasks) >= cap:
                    return tasks
    return tasks


# --------------------------------------------------------------------------- #
# Mock workspace — deliberate issues, so the whole pipeline (and its tests)
# runs end-to-end without a Notion token or a model.
# --------------------------------------------------------------------------- #

def _mk_page(pid, db, name, email=None, relations=None, icon=None, extra=None,
             created="2026-01-01T00:00:00.000Z"):
    props = {"Name": {"type": "title", "title": [{"plain_text": name}]}}
    if email is not None:
        props["Email"] = {"type": "email", "email": email}
    for prop, ids in (relations or {}).items():
        props[prop] = {"type": "relation",
                       "relation": [{"id": i} for i in ids], "has_more": False}
    props.update(extra or {})
    return {"id": pid, "url": f"https://notion.so/{pid}", "icon": icon,
            "archived": False, "created_time": created,
            "last_edited_time": "2026-01-01T00:00:00.000Z", "properties": props}


_MOCK = None


def _mock_workspace() -> dict:
    global _MOCK
    if _MOCK is not None:
        return _MOCK
    contacts = [
        _mk_page("mc1", "contacts", "Catherine Wu", "catherine@pitingcapital.com",
                 relations={"Employed By": ["mco1"]},
                 icon={"type": "emoji", "emoji": "*"}),
        # Exact duplicate pair (same email) — the second is richer.
        _mk_page("mc2", "contacts", "Josh Katzin", "josh@cavamont.com"),
        _mk_page("mc3", "contacts", "Joshua Katzin", "josh@cavamont.com",
                 relations={"Employed By": ["mco2"]}),
        # Whitespace formatting issue + inferable employer via domain.
        _mk_page("mc4", "contacts", "  Allan  Fife ", "allan@fife.com"),
        # Dangling relation to a page that no longer exists.
        _mk_page("mc5", "contacts", "Mary Osei", "mary@reva.com",
                 relations={"Employed By": ["gone-page"]}),
    ]
    companies = [
        _mk_page("mco1", "companies", "Piting Capital", None,
                 icon={"type": "emoji", "emoji": "*"},
                 extra={"Website": {"type": "url",
                                    "url": "https://pitingcapital.com"}}),
        _mk_page("mco2", "companies", "Cavamont", None,
                 extra={"Website": {"type": "url",
                                    "url": "https://cavamont.com"}}),
        _mk_page("mco3", "companies", "Fife Capital", None,
                 extra={"Website": {"type": "url",
                                    "url": "https://www.fife.com"}}),
    ]
    funds = [
        _mk_page("mf1", "funds", "Piting Capital Fund", None,
                 extra={"Status": {"type": "select",
                                   "select": {"name": "Track"}}}),
    ]
    notes = [
        _mk_page("mn1", "notes", "Call with Cavamont", None,
                 relations={"Attendees": ["mc2"]},
                 extra={"Thoughts / Considerations": {
                     "type": "rich_text",
                     "rich_text": [{"plain_text":
                                    "Josh Katzin is a Partner at Cavamont."}]}}),
    ]
    _MOCK = {
        "pages": {"contacts": contacts, "companies": companies,
                  "funds": funds, "notes": notes},
        "schemas": {"contacts": {"Name", "Email", "Employed By", "Type",
                                 "Weybourne Comments"},
                    "companies": {"Name", "Website", "Description", "City",
                                  "Country"},
                    "funds": {"Name", "Status", "Asset Class",
                              "Geographic Focus", "Strategy Description",
                              "Company Name", "Responsible Person"},
                    "notes": {"Name", "Attendees", "Note Type", "Date"}},
        "relation_map": {("contacts", "Employed By"): "companies",
                         ("notes", "Attendees"): "contacts"},
        "options": {"contacts": {"Type": ["GP - Investments",
                                          "LP - Institutional / SFO"]}},
    }
    return _MOCK


# --------------------------------------------------------------------------- #
# Approve-time merge — approving a duplicate finding IS the merge instruction.
# --------------------------------------------------------------------------- #

def merge_pair_now(notion, pair: list, db: str, source: str, reason: str,
                   survivor_id: str = "", base: Optional[Path] = None) -> dict:
    """Merge a reviewed duplicate pair on the spot.

    Both records are fetched fresh, the richer one survives (or the recorded
    survivor when one was already chosen), the loser's data transfers over,
    inbound relations are found by targeted contains-queries — no full rescan —
    and repointed, and the loser is archived. Same reversible machinery as a
    live run: full snapshot, undo works.
    """
    try:
        pages = [notion.get_page(pid) for pid in pair]
    except Exception as e:  # noqa: BLE001
        return {"status": "Failed",
                "note": f"could not read the two records: {e}"}
    cards = [detect.card_from_page(p, db) for p in pages]
    if any(c["archived"] for c in cards):
        return {"status": "Skipped",
                "note": "one of the pair is already archived — nothing left "
                        "to merge"}
    if survivor_id:
        if cards[1]["id"] == survivor_id:
            cards.reverse()
    else:
        surv, losers = detect.choose_survivor(cards)
        cards = [surv, losers[0]]
    survivor, loser = cards
    transfers = detect.plan_merge_transfers(survivor, loser)

    # Inbound relations: query only the relation properties that can point at
    # this database, filtered to pages containing the loser.
    def _norm(s: str) -> str:
        return (s or "").replace("-", "").lower()

    db_ids = {k: (f() or "") for k, f in _DB_IDS.items()}
    prop_ids: dict = {}
    inbound: dict = {}
    if getattr(notion, "live", False) and db_ids.get(db):
        for key, did in db_ids.items():
            if not did:
                continue
            try:
                schema = notion.retrieve_database(did)
            except Exception:  # noqa: BLE001
                continue
            for name, p in (schema.get("properties") or {}).items():
                prop_ids[(key, name)] = p.get("id", "")
                if p.get("type") != "relation":
                    continue
                target = (p.get("relation") or {}).get("database_id", "")
                if _norm(target) != _norm(db_ids[db]):
                    continue
                try:
                    rows = notion.query_database_raw(did, filter_payload={
                        "property": name,
                        "relation": {"contains": loser["id"]}})
                except Exception:  # noqa: BLE001
                    rows = []
                for row in rows:
                    c = detect.card_from_page(row, key)
                    if c["id"] != loser["id"]:
                        inbound[c["id"]] = c
    # The survivor repointing at itself would be nonsense; a stale relation to
    # the archived loser on the survivor is caught as dangling by the next run.
    inbound.pop(survivor["id"], None)

    # Names for the side-by-side detail (best-effort, capped).
    names_by_id: dict = {}
    rel_ids: list = []
    for c in (survivor, loser):
        for ids in c["relations"].values():
            for i in ids:
                if i not in rel_ids:
                    rel_ids.append(i)
    for i in rel_ids[:12]:
        try:
            names_by_id[i] = detect.card_from_page(notion.get_page(i), "")["name"]
        except Exception:  # noqa: BLE001
            pass

    run_id = store.new_run_id()
    run = RunRecord(run_id=run_id, started=_now(), dry_run=False,
                    databases=[db])
    store.save_run(run, base)
    records, _seq = execute.execute_merge(
        notion, run_id, 1, survivor, loser, transfers,
        list(inbound.values()), prop_ids, "High", source, reason,
        dry_run=False, quiet_minutes=0, base=base,
        detail=_merge_detail(survivor, loser, transfers, names_by_id))
    parent = records[0]
    run.finished = _now()
    run.status = "completed" if parent.execution_status == "Applied" else "failed"
    run.counts = {
        "applied": sum(1 for r in records if r.execution_status == "Applied"),
        "failed": sum(1 for r in records if r.execution_status == "Failed"),
        "merges": 1 if parent.execution_status == "Applied" else 0}
    store.save_run(run, base)
    store.resolve_pair(survivor["id"], loser["id"], "user-approved-merge", base)
    return {"status": parent.execution_status, "survivor": survivor["name"],
            "loser": loser["name"], "loser_id": loser["id"],
            "changes": len(records)}


def create_company_and_link(notion, snapshot: dict, change,
                            base: Optional[Path] = None,
                            db_id: Optional[str] = None) -> dict:
    """Approve-time: create the company, then link the record to it.

    The name is checked against Companies one more time before creating —
    the scan that proposed this may be minutes or days old, and creating a
    second copy of a company is exactly the mess Felix exists to prevent.
    """
    name = (snapshot.get("company_name") or "").strip()
    prop = snapshot.get("link_property") or ""
    if not name or not prop:
        return {"status": "Failed", "note": "the proposal is missing its "
                                            "company name or link property"}
    db_id = db_id or config.NOTION_COMPANIES_DB
    if not db_id:
        return {"status": "Failed", "note": "no Companies database configured"}

    # Re-check for an existing company, including any created since the scan.
    try:
        rows = notion.query_database_raw(db_id)
    except Exception as e:  # noqa: BLE001
        return {"status": "Failed", "note": f"could not read Companies: {e}"}
    existing = [detect.card_from_page(p, "companies") for p in rows]
    hit = enrich.resolve_name(name, existing)
    created = False
    if hit["match"]:
        company_id = hit["match"]["id"]
        company_name = hit["match"]["name"]
    elif hit["near"]:
        return {"status": "Skipped",
                "note": f"'{name}' now looks like the existing company "
                        f"'{hit['near']['name']}' — link it by hand rather "
                        "than risk a duplicate"}
    else:
        try:
            page = notion.create_page(db_id, {"Name": {"title": [
                {"text": {"content": name[:1900]}}]}})
        except Exception as e:  # noqa: BLE001
            return {"status": "Failed", "note": f"could not create it: {e}"}
        company_id = page.get("id", "")
        company_name = name
        created = True
        if not company_id:
            return {"status": "Failed", "note": "Notion returned no page id"}

    ids = list(snapshot.get("existing_ids") or [])
    if company_id not in ids:
        ids.append(company_id)
    try:
        notion.update_page(snapshot["record_id"], properties={
            prop: {"relation": [{"id": i} for i in ids]}})
    except Exception as e:  # noqa: BLE001
        return {"status": "Failed",
                "note": (f"created '{company_name}' but could not link it: {e}"
                         if created else f"could not link it: {e}")}
    change.execution_status = "Applied"
    change.new_value = company_name[:1900]
    change.new_relation_ids = ids
    store.append_change(change, base)
    return {"status": "Applied", "company": company_name, "created": created,
            "note": (f"created '{company_name}' and linked it"
                     if created else f"linked the existing '{company_name}'")}


def add_photo_to_page(notion, snapshot: dict, change,
                      base: Optional[Path] = None) -> dict:
    """Approve-time: put the profile photo in the contact's page body.

    Notion fetches external image URLs itself, so a dead or blocked link
    fails here rather than silently leaving a broken block.
    """
    url = (snapshot.get("photo_url") or "").strip()
    if not url.startswith("http"):
        return {"status": "Failed", "note": "no usable photo URL"}
    children = [{"object": "block", "type": "image",
                 "image": {"type": "external", "external": {"url": url}}}]
    profile = (snapshot.get("profile_url") or "").strip()
    if profile.startswith("http"):
        children.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [
                {"type": "text",
                 "text": {"content": "LinkedIn profile", "link": {"url": profile}}}]}})
    try:
        notion.append_blocks(snapshot["record_id"], children)
    except Exception as e:  # noqa: BLE001
        return {"status": "Failed",
                "note": f"Notion would not accept the image: {e}"}
    change.execution_status = "Applied"
    store.append_change(change, base)
    return {"status": "Applied", "note": "photo added to the page"}
