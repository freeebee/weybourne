"""The Felix run — the work() the jobs framework executes.

Phases: preflight (schemas, relation map, options) → undo sweep → strict full
scan → deterministic detection → LLM adjudication → ordered execution (merges
last) → summary. Dry-run walks the whole pipeline and records planned changes
without a single Notion write.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from src import config
from src.connectors.notion_client import NotionPartialResult
from src.features.felix import adjudicate, detect, execute, store, undo
from src.features.felix.models import ChangeRecord, RunOptions, RunRecord

# Scan-property allowlist where computed properties 500 inside Notion.
_FUNDS_SCAN_PROPS = ["Fund Name", "Name", "Asset Class", "Geographic Focus",
                     "Strategy Description", "Status", "Company Name",
                     "Responsible Person", "Company", "Representatives"]

_DB_IDS = {
    "contacts": lambda: config.NOTION_CONTACTS_DB,
    "companies": lambda: config.NOTION_COMPANIES_DB,
    "funds": lambda: config.NOTION_FUNDS_DB,
    "notes": lambda: config.NOTION_NOTES_DB,
}

_EVENT_TEXT = {
    "fix_formatting": "tidied",
    "fix_icon": "icon polished",
    "fix_relation": "relation repaired",
    "fill_missing": "filled in",
    "merge": "duplicate merged",
    "merge_transfer": "detail transferred",
    "archive": "duplicate archived",
    "recommendation": "flagged for review",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stage(job: dict, label: str, detail: str = "") -> None:
    job["stages"].append({"label": label, "detail": detail})


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


def felix_run(job: dict, notion, client, options: RunOptions,
              checkpoint=lambda: None, base: Optional[Path] = None) -> dict:
    run_id = store.new_run_id()
    run = RunRecord(run_id=run_id, started=_now(), dry_run=options.dry_run,
                    databases=options.databases)
    store.save_run(run, base)
    job["felix_run_id"] = run_id
    seq = 1
    counts: dict = {"applied": 0, "planned": 0, "failed": 0, "skipped": 0,
                    "recommendations": 0, "merges": 0, "relations_repaired": 0,
                    "missing_filled": 0, "formatting_fixed": 0, "icons_added": 0,
                    "high": 0, "medium": 0, "deferred": 0, "undone": 0}

    def _finish(status: str, error: str = "") -> dict:
        run.finished = _now()
        run.status = status
        run.counts = counts
        run.error = error
        store.save_run(run, base)
        return {"run_id": run_id, "counts": counts, "dry_run": options.dry_run,
                "status": status, "error": error}

    def record_recommendation(db_card: dict, prop: str, reason: str,
                              source: str = "", new_value: str = "") -> None:
        nonlocal seq
        rec = ChangeRecord(
            change_id=store.change_id_for(run_id, seq), run_id=run_id,
            timestamp=_now(), database=db_card["db"],
            record_name=db_card["name"], record_id=db_card["id"],
            record_url=db_card["url"], change_type="recommendation",
            property_changed=prop, new_value=new_value, source=source,
            reason=reason, confidence="Low", execution_status="Recommended")
        seq += 1
        store.append_change(rec, base)
        _emit(job, rec)
        counts["recommendations"] += 1

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
    job["partial"] = job.get("partial") or {}
    job["partial"]["scanned"] = {k: len(v) for k, v in cards_by_db.items()}

    # ---- Phase 3: deterministic detection ---------------------------------- #
    _stage(job, "Detecting issues", "duplicates, gaps, broken links, formatting")
    checkpoint()
    planned: list[dict] = []       # simple changes
    merges: list[dict] = []

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
            planned.append({
                "db": key, "card": f["card"], "change_type": "fix_formatting",
                "property": prop, "previous": f["from"], "new": f["to"],
                "payload": {"properties": {prop: payload}},
                "expect_prop": prop, "scanned_plain": f["from"],
                "confidence": "High",
                "source": "mechanical formatting rule",
                "reason": "whitespace/case normalisation"})

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

    # Exact duplicates — High merges.
    for key, cards in cards_by_db.items():
        for group in detect.find_exact_duplicate_groups(cards):
            survivor, losers = detect.choose_survivor(group["cards"])
            for loser in losers:
                merges.append({
                    "db": key, "survivor": survivor, "loser": loser,
                    "confidence": "High",
                    "source": f"exact {group['evidence']} match: {group['key']}",
                    "reason": "records share an exact identifier"})

    # ---- Phase 4: LLM adjudication ----------------------------------------- #
    fuzzy_all = []
    for key, cards in cards_by_db.items():
        for p in detect.find_fuzzy_duplicate_pairs(cards):
            p["db"] = key
            fuzzy_all.append(p)
    if fuzzy_all:
        _stage(job, "Adjudicating look-alikes",
               f"{len(fuzzy_all)} candidate pair(s)")
        checkpoint()
    merged_ids = {m["loser"]["id"] for m in merges} | \
                 {m["survivor"]["id"] for m in merges}
    for verdict in adjudicate.adjudicate_duplicates(
            client, fuzzy_all, max_calls=max(1, options.max_llm_calls // 2)):
        p = verdict["pair"]
        if verdict["verdict"] == "duplicate" and verdict["survivor_card"]:
            surv = verdict["survivor_card"]
            loser = p["a"] if surv["id"] == p["b"]["id"] else p["b"]
            if surv["id"] in merged_ids or loser["id"] in merged_ids:
                continue
            merged_ids |= {surv["id"], loser["id"]}
            merges.append({"db": p["db"], "survivor": surv, "loser": loser,
                           "confidence": "Medium",
                           "source": f"name similarity {p['score']} + model "
                                     f"adjudication: {verdict['reason'][:150]}",
                           "reason": "adjudicated as the same entity"})
        elif verdict["verdict"] == "unsure":
            record_recommendation(
                p["a"], "(possible duplicate)",
                f"may duplicate '{p['b']['name']}' — {verdict['reason'][:200]}",
                source=f"name similarity {p['score']}")
        elif verdict["verdict"] == "deferred":
            counts["deferred"] += 1

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
            record_recommendation(
                card, t["property"],
                f"model proposed '{prop_fill['value']}' but the evidence quote "
                "did not verify — review manually",
                source=t.get("source_label", "linked notes"))
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
            "source": f"{t.get('source_label', 'linked note')} — \"{prop_fill['evidence_quote'][:180]}\"",
            "reason": "explicit information in linked material"})

    # ---- Phase 5: plan + order --------------------------------------------- #
    order = {"fix_formatting": 0, "fix_icon": 1, "fill_missing": 2,
             "fix_relation": 3}
    planned.sort(key=lambda p: order.get(p["change_type"], 2))
    merges = merges[:options.max_merges]
    budget = options.max_writes
    run_list = planned[:budget]
    deferred_now = len(planned) - len(run_list)
    counts["deferred"] += deferred_now

    # ---- Phase 6: execute --------------------------------------------------- #
    mode = "recording the would-do plan" if options.dry_run else "applying fixes"
    _stage(job, "Executing", f"{len(run_list)} change(s) + "
                             f"{len(merges)} merge(s) — {mode}")
    job["total"] = len(run_list) + len(merges)
    job["done"] = 0
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

    for m in merges:
        checkpoint()
        transfers = detect.plan_merge_transfers(m["survivor"], m["loser"])
        records, seq = execute.execute_merge(
            notion, run_id, seq, m["survivor"], m["loser"], transfers,
            all_cards, prop_ids, m["confidence"], m["source"], m["reason"],
            dry_run=options.dry_run, quiet_minutes=options.quiet_minutes,
            base=base, on_change=lambda c: _emit(job, c))
        job["done"] += 1
        parent = records[0]
        if parent.execution_status == "Applied":
            counts["applied"] += 1
            counts["merges"] += 1
            counts["high" if parent.confidence == "High" else "medium"] += 1
        elif parent.execution_status == "Planned (dry-run)":
            counts["planned"] += 1
            counts["merges"] += 1
        elif parent.execution_status == "Failed":
            counts["failed"] += 1

    # ---- Phase 7: summarise ------------------------------------------------- #
    if not options.dry_run and (counts["applied"] or counts["undone"]):
        notion.invalidate_cache()
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
