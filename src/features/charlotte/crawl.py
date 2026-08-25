"""Raw-crawl the four Notion databases into the Charlotte's Web snapshot.

Runs as a background job (api.main._start_job) with per-database
job["current"] ticks — the felix live-scan discipline: a rate-limited
crawl of ~35k pages takes 5-10 minutes and reads as wedged without a
live counter. Property names are resolved through felix detect.match_prop,
never compared literally (the workspace's names carry emoji prefixes),
and the weaving itself is a pure function so tests can feed it fixture
cards without any Notion at all.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Optional

from src import config
from src.connectors.notion_client import NotionPartialResult
from src.features.felix import detect
from src.features.charlotte import store

_DB_IDS = {
    "contacts": lambda: config.NOTION_CONTACTS_DB,
    "companies": lambda: config.NOTION_COMPANIES_DB,
    "funds": lambda: config.NOTION_FUNDS_DB,
    "notes": lambda: config.NOTION_NOTES_DB,
}

# Funds carry computed properties that 500 inside Notion when queried, so
# the crawl narrows to named properties — same defense as list_funds and
# the felix scan. Names here are candidates; the live (possibly renamed or
# emoji-prefixed) forms are resolved in preflight and added alongside.
_FUNDS_PROP_CANDIDATES = [
    "Fund Name", "Name", "Status", "Quality", "Asset Class",
    "Geographic Focus", "Strategy Description", "Weybourne Comments",
    "Company", "Company Name", "Introduced By", "Represented By",
    "Known LPs", "Recommended By", "Responsible Analyst",
]

# Evidence entries kept per edge — a fund discussed in thirty meetings does
# not need all thirty on the wire; the count is what matters past a few.
_EVIDENCE_PER_EDGE = 8


def _stage(job: dict, label: str, detail: str = "") -> None:
    job.setdefault("stages", []).append(
        {"label": label, "detail": detail, "at": time.time()})
    job["current"] = ""


def _sha1(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def _values(v) -> list:
    """Multi-select plain values, whatever shape the card parser gave them
    (list of options, or one comma-joined string) -> clean list of str."""
    if isinstance(v, (list, tuple)):
        return [s for s in (str(x).strip() for x in v) if s]
    s = str(v or "").strip()
    return [p.strip() for p in s.split(",") if p.strip()] if s else []


def _name_key(s) -> str:
    """Whitespace-collapsed, casefolded name for matching a Notion user's
    display name against a contact label."""
    return " ".join(str(s or "").split()).casefold()


# User-confirmed identities for analyst display names no safe rule can
# decide (23 Aug 2026): e.g. the Notion user "Claudio" is Claudio Cadei —
# Contacts also holds a Claudio Siniscalco and a Claudio Giuliano, so
# containment matching rightly refuses to guess. Keys and values in
# _name_key form.
_ANALYST_ALIASES = {
    "claudio": "claudio cadei",
    "alex k": "alex kummelstedt",
    "jessica": "jessica yap",
}


def match_analyst_contacts(nodes: dict) -> dict:
    """Analyst display name -> contact node id, for every name found on a
    fund node's "analyst" list. Shared by weave() and any snapshot repair.

    The ladder (each rung tried only when the previous found nothing, and
    every rung requires EXACTLY ONE hit — ambiguity always means no link;
    observed misses from the 23 Aug crawl in parentheses):
      user-confirmed alias -> exact name -> an email's local part with
      dots as spaces (gabriella.waspe@… -> Gabriella Waspe) ->
      word-order-insensitive (Chen Jinghan -> Jinghan Chen) -> unique
      containment for truncated display names (Liang Jie -> Liang Jie
      Choo), guarded to >= 6 chars so a bare first name can't match."""
    by_name: dict = {}
    for nid, n in nodes.items():
        if n.get("kind") == "contact":
            by_name.setdefault(_name_key(n.get("label")), []).append(nid)
    by_sorted: dict = {}
    for k, nids in by_name.items():
        by_sorted.setdefault(" ".join(sorted(k.split())), []).extend(nids)
    out: dict = {}
    names = {nm for n in nodes.values() if n.get("kind") == "fund"
             for nm in (n.get("analyst") or [])}
    for nm in names:
        k = _name_key(nm)
        k = _ANALYST_ALIASES.get(k, k)
        hits = by_name.get(k) or []
        if not hits and "@" in k:
            k = " ".join(k.split("@", 1)[0].replace(".", " ").split())
            hits = by_name.get(k) or []
        if not hits:
            hits = by_sorted.get(" ".join(sorted(k.split()))) or []
        if not hits and len(k) >= 6:
            hits = [nid for nk, nids in by_name.items()
                    if k in nk for nid in nids]
        if len(hits) == 1:
            out[nm] = hits[0]
    return out


def resolve_props(schemas: dict) -> dict:
    """Live property names for everything the weave reads. A missing
    property resolves to "" and its edges are simply skipped — "Past
    Employers" only exists once the Phase-2 setup step has been done."""
    return {
        "employed_by": detect.match_prop(schemas["contacts"], "Employed By"),
        "contact_type": detect.match_prop(schemas["contacts"], "Type"),
        "contact_desc": detect.match_prop(schemas["contacts"], "Description"),
        "past_employers": detect.match_prop(schemas["contacts"], "Past Employers"),
        "fund_company": detect.match_prop(schemas["funds"], "Company"),
        "introduced_by": detect.match_prop(schemas["funds"], "Introduced By"),
        "represented_by": detect.match_prop(schemas["funds"], "Represented By"),
        # Renamed 21 Aug 2026 from the dormant "Recommended By" — the
        # explicit LP-investment relation. Legacy name kept as fallback for
        # any workspace where the rename has not landed.
        "known_lps": detect.match_prop(schemas["funds"], "Known LPs",
                                       "Recommended By"),
        "fund_status": detect.match_prop(schemas["funds"], "Status"),
        "fund_quality": detect.match_prop(schemas["funds"], "Quality"),
        "fund_asset_class": detect.match_prop(schemas["funds"], "Asset Class"),
        "fund_geography": detect.match_prop(schemas["funds"],
                                            "Geographic Focus"),
        # A Notion *people* property (workspace users, not a relation) —
        # run_crawl resolves the user ids to display names, and the weave
        # matches those names to Contacts to draw the analyst edges.
        "fund_analyst": detect.match_prop(schemas["funds"],
                                          "Responsible Analyst"),
        "fund_comments": detect.match_prop(schemas["funds"], "Weybourne Comments"),
        "fund_strategy": detect.match_prop(schemas["funds"], "Strategy Description"),
        "note_fund": detect.match_prop(schemas["notes"], "Fund"),
        "note_attendees": detect.match_prop(schemas["notes"], "Attendees"),
        "note_type": detect.match_prop(schemas["notes"], "Note Type"),
        "note_date": detect.match_prop(schemas["notes"], "Date"),
    }


def weave(cards_by_db: dict, props: dict,
          user_names: Optional[dict] = None) -> tuple:
    """Cards (felix card_from_page shape) -> (nodes, edges, texts).
    user_names maps Notion user ids -> display names (for the funds'
    Responsible Analyst people property, resolved by run_crawl).

    Blank-named or archived pages never become nodes, and edges touching
    them are dropped with them — one empty-named company row once joined
    every employer-less contact into a phantom hub (travel/planner.py's
    documented incident)."""
    p = props
    nodes: dict = {}
    texts: dict = {}

    def usable(c: dict) -> bool:
        return bool((c.get("name") or "").strip()) and not c.get("archived")

    for key, kind in (("contacts", "contact"), ("companies", "company"),
                      ("funds", "fund")):
        for c in cards_by_db.get(key, []):
            if not usable(c):
                continue
            n: dict = {"kind": kind, "label": c["name"].strip()}
            plain = c.get("plain") or {}
            if kind == "contact":
                n["contact_type"] = str(plain.get(p["contact_type"]) or "")
                desc = str(plain.get(p["contact_desc"]) or "").strip()
                if desc:
                    texts[c["id"]] = {"description": desc, "fp": _sha1(desc)}
            elif kind == "fund":
                n["status"] = str(plain.get(p["fund_status"]) or "")
                n["quality"] = str(plain.get(p["fund_quality"]) or "")
                # Multi-selects, kept as lists — the grouping layers in
                # the global view read the FIRST value as primary.
                n["asset_class"] = _values(plain.get(p["fund_asset_class"]))
                n["geography"] = _values(plain.get(p["fund_geography"]))
                comments = str(plain.get(p["fund_comments"]) or "").strip()
                strategy = str(plain.get(p["fund_strategy"]) or "").strip()
                if comments or strategy:
                    texts[c["id"]] = {"comments": comments,
                                      "strategy": strategy,
                                      "fp": _sha1(comments + "\n" + strategy)}
            nodes[c["id"]] = n

    edge_index: dict = {}

    def add_edge(a: str, b: str, etype: str, ev: Optional[dict] = None) -> None:
        if a not in nodes or b not in nodes or a == b:
            return
        e = edge_index.get((a, b, etype))
        if e is None:
            e = {"a": a, "b": b, "type": etype, "evidence": []}
            edge_index[(a, b, etype)] = e
        if ev and len(e["evidence"]) < _EVIDENCE_PER_EDGE:
            e["evidence"].append(ev)

    relation_edges = (
        ("contacts", p["employed_by"], "employed_by"),
        # Solid once Phase 2 has written it — a real Notion relation.
        ("contacts", p["past_employers"], "previously_at"),
        ("funds", p["fund_company"], "managed_by"),
        ("funds", p["introduced_by"], "introduced_by"),
        ("funds", p["represented_by"], "represented_by"),
        ("funds", p["known_lps"], "known_lp"),
    )
    for db, prop, etype in relation_edges:
        if not prop:
            continue
        for c in cards_by_db.get(db, []):
            if not usable(c):
                continue
            for other in (c.get("relations") or {}).get(prop) or []:
                add_edge(c["id"], other, etype)

    # Responsible Analyst: a *people* property, so the plain value is
    # Notion user ids — resolved to display names upstream, stored on the
    # fund node, then matched to Contacts by name (Weybourne's own staff
    # appear in the contact list under the same name; the conservative
    # ladder lives in match_analyst_contacts).
    if p["fund_analyst"] and user_names:
        for c in cards_by_db.get("funds", []):
            if not usable(c):
                continue
            uids = (c.get("plain") or {}).get(p["fund_analyst"]) or []
            if not isinstance(uids, (list, tuple)):
                uids = [uids]
            names = [nm for nm in (user_names.get(str(u), "") for u in uids)
                     if nm]
            if names:
                nodes[c["id"]]["analyst"] = names
        resolved = match_analyst_contacts(nodes)
        for nid, n in nodes.items():
            if n.get("kind") != "fund":
                continue
            for nm in n.get("analyst") or []:
                cid = resolved.get(nm)
                if cid:
                    add_edge(cid, nid, "responsible_for")

    # Notes are nodes too (kind "note"): the meeting page, linked to its
    # fund ("about") and attendees ("attended") so the web can show and
    # filter meetings. The direct contact—fund "discussed" edge REMAINS —
    # LP tiers and the two-hop story read from it, and nameless notes still
    # contribute that evidence even though they never render as nodes.
    for note in cards_by_db.get("notes", []):
        if note.get("archived"):
            continue
        rel = note.get("relations") or {}
        fund_ids = rel.get(p["note_fund"]) or []
        attendee_ids = rel.get(p["note_attendees"]) or []
        if not fund_ids and not attendee_ids:
            continue
        plain = note.get("plain") or {}
        title = (note.get("name") or "").strip()
        ev = {"kind": "note", "id": note.get("id", ""),
              "title": title,
              "date": str(plain.get(p["note_date"]) or "")[:10],
              "note_type": str(plain.get(p["note_type"]) or "")}
        if title:
            nodes[note["id"]] = {"kind": "note", "label": title,
                                 "date": ev["date"],
                                 "note_type": ev["note_type"]}
            for f in fund_ids:
                add_edge(note["id"], f, "about")
            for a in attendee_ids:
                add_edge(a, note["id"], "attended")
        for f in fund_ids:
            for a in attendee_ids:
                add_edge(a, f, "discussed", ev)

    return nodes, list(edge_index.values()), texts


def run_crawl(job: dict, notion, base: Optional[Path] = None) -> dict:
    if not getattr(notion, "live", False):
        return {"status": "failed",
                "error": "Notion is not configured — the web needs the live workspace"}

    _stage(job, "Preflight", "confirming live database schemas")
    db_ids = {k: (f() or "") for k, f in _DB_IDS.items()}
    missing = [k for k, v in db_ids.items() if not v]
    if missing:
        return {"status": "failed",
                "error": "missing database id(s): " + ", ".join(missing)}
    schemas = {}
    for key, dbid in db_ids.items():
        schema = notion.retrieve_database(dbid)
        schemas[key] = set(schema.get("properties") or {})
    props = resolve_props(schemas)

    _stage(job, "Scanning", "contacts + companies + funds + notes")
    cards_by_db: dict = {}
    for key in ("contacts", "companies", "funds", "notes"):
        scanned = {k: len(v) for k, v in cards_by_db.items()}
        job["current"] = " · ".join(
            [f"{k} {n}" for k, n in scanned.items()]
            + [f"pulling every {key} page…"])
        pids = None
        if key == "funds":
            wanted = list(dict.fromkeys(
                _FUNDS_PROP_CANDIDATES
                + [v for k, v in props.items()
                   if v and k.startswith(("fund_", "introduced", "represented",
                                          "known_lps"))]))
            pids = notion._property_ids(db_ids[key], wanted) or None
        try:
            pages = notion.query_database_raw(db_ids[key], strict=True,
                                              property_ids=pids)
        except NotionPartialResult as e:
            return {"status": "failed",
                    "error": f"partial scan of {key} ({len(e.rows)} rows) — "
                             "aborted: the web must not be built from an "
                             "incomplete database"}
        cards_by_db[key] = [detect.card_from_page(pg, key) for pg in pages]
    job["current"] = " · ".join(f"{k} {len(v)}" for k, v in cards_by_db.items())

    # Responsible Analyst arrives as user ids; resolve each unique id to a
    # display name once (resolve_user caches to disk indefinitely, so this
    # is a handful of API calls on the first crawl and zero after).
    user_names: dict = {}
    if props.get("fund_analyst"):
        uids: set = set()
        for c in cards_by_db.get("funds", []):
            v = (c.get("plain") or {}).get(props["fund_analyst"]) or []
            uids.update(str(u) for u in
                        (v if isinstance(v, (list, tuple)) else [v]) if u)
        if uids:
            job["current"] = f"resolving {len(uids)} analyst names"
            user_names = {u: notion.resolve_user(u) for u in sorted(uids)}

    _stage(job, "Weaving", "nodes, edges, evidence")
    nodes, edges, texts = weave(cards_by_db, props, user_names)

    snap = {"version": 1,
            "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "counts": {k: len(v) for k, v in cards_by_db.items()},
            "nodes": nodes, "edges": edges, "texts": texts}
    _stage(job, "Saving", f"{len(nodes)} nodes · {len(edges)} edges")
    store.save_snapshot(snap, base)
    return {"status": "done", "counts": snap["counts"],
            "nodes": len(nodes), "edges": len(edges)}
