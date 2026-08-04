"""FastAPI backend for the React front-end.

Thin HTTP layer over the existing feature modules in src/ — no business logic
lives here. Serves the built React app from web/dist when present.

Run:  .venv/Scripts/python -m uvicorn api.main:app --port 8000
Dev:  the Vite dev server (web/) proxies /api to this port.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

try:  # .env is optional
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass

import json
import sqlite3
import threading
import time
from typing import Optional

import pandas as pd
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src import config, llm
from src.connectors.graph import CALENDAR_SNAPSHOT, INBOX_SNAPSHOT, GraphConnector
from src.connectors.notion_client import NotionConnector
from src.db import init_db
from src.features import managers, notion_sync, transcript_library
from src.features.felix import store as felix_store
from src.features.felix import undo as felix_undo
from src.features.felix.models import RunOptions as FelixRunOptions
from src.features.felix.run import felix_run
from src.features.dedupe import dedupe_entity, domain_of, match_company, match_contact
from src.features.draft_reply import generate_draft_options
from src.features.inbox_triage import triage_email
from src.features.meeting_prep import build_context, counterparty_from_event
from src.features.preferences import screen_opportunity
from src.features.web_research import (
    age_days,
    dossier_sources,
    dossier_text,
    get_dossier,
)
from src.features.stt import transcribe_wav
from src.features.transcription import (
    TranscriptBuffer,
    draft_meeting_note,
    note_from_markdown,
    note_stream_args,
    note_to_markdown,
    read_transcript_batch,
    refine_thoughts,
    sharpen_question,
    tidy_transcript_chunk,
)
from src.features.track_record import (
    analyse_file,
    best_worst_period,
    cumulative_return_pct,
    max_drawdown_pct,
)
from src.features.whats_new import inbox_whats_new, portfolio_whats_new, team_whats_new
from src.schemas import EmailMessage, ExtractedEntity, InvestmentTriage, PreferenceScreen

app = FastAPI(title="Weybourne Investment Connector API")

# The UI polls /api/jobs every few seconds (sidebar tray + job pages), which
# would otherwise flood the access log. Drop just those lines.
import logging  # noqa: E402


class _QuietJobPolling(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return '"GET /api/jobs' not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_QuietJobPolling())
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],   # vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

_graph = GraphConnector()
_notion = NotionConnector()


def _client():
    ok, msg = llm.preflight()
    if not ok:
        raise HTTPException(status_code=503, detail=f"AI backend unavailable: {msg}")
    return llm.get_client()


def _run(fn, *args, **kwargs):
    """Run a feature call, translating backend failures into HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except llm.ClaudeCodeAuthError as e:
        raise HTTPException(status_code=401, detail=f"Not signed in to Claude: {e}")
    except llm.ClaudeCodeRateLimited as e:
        raise HTTPException(status_code=429, detail=f"Claude usage limit reached: {e}")
    except llm.ClaudeCodeError as e:
        raise HTTPException(status_code=502, detail=f"Claude Code error: {e}")


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #

@app.get("/api/status")
def status():
    if _graph.live:
        outlook = {"ok": True, "detail": "live (Microsoft Graph)"}
    elif INBOX_SNAPSHOT.exists() or CALENDAR_SNAPSHOT.exists():
        outlook = {"ok": True, "detail": "snapshot (via Claude connector)"}
    else:
        outlook = {"ok": False, "detail": "sample data"}
    label, detail = llm.describe_backend()
    backend_ok, backend_msg = llm.preflight()
    return {
        "outlook": outlook,
        "notion": {"ok": _notion.live,
                   "detail": "live" if _notion.live else "sample data"},
        "ai": {"ok": backend_ok, "label": label,
               "detail": detail if backend_ok else backend_msg},
    }


# --------------------------------------------------------------------------- #
# Inbox triage
# --------------------------------------------------------------------------- #

@app.get("/api/inbox")
def inbox(days: int = config.TRIAGE_LOOKBACK_DAYS, top: int = config.TRIAGE_MAX_MESSAGES):
    return {"messages": [m.model_dump() for m in _graph.list_inbox(top=top, days=days)],
            "notion_live": _notion.live}


_ADJUDICATE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["same", "different", "unsure"]},
        "reason": {"type": "string", "description": "One sentence"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


def _existing_details(kind: str, rec) -> dict:
    """The existing CRM record's fields, for adjudication and the side-by-side."""
    if kind == "contact":
        return {"Name": rec.name, "Email": rec.email, "Title": rec.title,
                "Company": rec.company}
    if kind == "company":
        return {"Name": rec.name, "Domain": rec.domain, "City": rec.city,
                "Country": rec.country, "Description": rec.description}
    return {"Name": rec.name, "Asset class": ", ".join(rec.asset_class),
            "Geography": ", ".join(rec.geographic_focus),
            "Strategy": rec.strategy_description, "Status": rec.status,
            "Company": rec.company}


def _proposed_details(kind: str, e: ExtractedEntity) -> dict:
    if kind == "contact":
        return {"Name": e.contact_name, "Email": e.contact_email,
                "Title": e.contact_title, "Company": e.company_name}
    if kind == "company":
        return {"Name": e.company_name, "Domain": e.company_domain,
                "City": e.company_city, "Country": e.company_country,
                "Description": e.company_description}
    return {"Name": e.fund_name, "Asset class": e.asset_class,
            "Geography": e.geography, "Strategy": e.strategy_description,
            "Vintage": e.vintage, "Target size": e.target_size}


def _adjudicate_duplicate(client, kind: str, proposed: dict, existing: dict) -> dict:
    """Fast-model judgement on an uncertain match: same entity or not?

    Weighs the evidence a name score can't — a contact whose CRM record sits
    at the same firm, matching cities, matching strategies. Returns
    {"verdict": same|different|unsure, "reason"} and never raises.
    """
    def lines(d):
        return "\n".join(f"  {k}: {v}" for k, v in d.items() if v)
    try:
        response = client.messages.create(
            model=config.FAST_MODEL,
            max_tokens=200,
            system=("You resolve possible duplicates in a family-office CRM. Decide "
                    "whether the proposed record and the existing record are the SAME "
                    "real-world entity. Weigh corroborating fields (a contact's firm, "
                    "a company's city or domain, a fund's strategy), spelling and "
                    "concatenation variants ('FIFECAPITAL' = 'Fife Capital'), and be "
                    "wary of same-named but unrelated entities in different "
                    "geographies. 'unsure' is a valid answer."),
            output_config={"format": {"type": "json_schema", "schema": _ADJUDICATE_SCHEMA}},
            messages=[{"role": "user", "content":
                       f"PROPOSED {kind.upper()} (from an email)\n{lines(proposed)}\n\n"
                       f"EXISTING {kind.upper()} (already in the CRM)\n{lines(existing)}"}],
        )
        raw = next((b.text for b in response.content
                    if getattr(b, "type", None) == "text"), "")
        return json.loads(raw)
    except Exception:  # noqa: BLE001 - adjudication is an enhancement, never a blocker
        return {"verdict": "unsure", "reason": "adjudication unavailable"}


def _linked_fields(decisions: dict) -> dict:
    """Manager-thread fields from dedupe's link_existing matches."""
    fields = {}
    for kind, id_key, name_key in (("contact", "contact_id", "contact_name"),
                                   ("company", "company_id", "company_name"),
                                   ("fund", "fund_id", "fund_name")):
        d = decisions.get(kind)
        if d and d.best_match and d.recommended_action == "link_existing":
            fields[id_key] = d.best_match.matched_id or ""
            fields[name_key] = d.best_match.matched_name
    return fields


def _triage_one(client, msg: EmailMessage, progress=None) -> dict:
    def say(what: str):
        if progress:
            progress(what)

    say(f"Reading “{msg.subject[:50]}”")
    result: InvestmentTriage = triage_email(client, msg)
    out = result.model_dump()
    # Dedupe runs for every email, not only investment-relevant ones — knowing
    # whether the sender is already in Notion matters for a personal catch-up
    # too, and the screen/draft steps stay available downstream.
    if True:
        say(f"Checking Notion for {result.entity.company_name or result.entity.fund_name or result.entity.contact_name or 'the sender'}")
        contacts = _notion.list_contacts()
        companies = _notion.list_companies()
        funds = _notion.list_funds()
        decisions = dedupe_entity(result.entity, contacts, companies, funds)

        records_by_id = {
            "contact": {c.id: c for c in contacts if c.id},
            "company": {c.id: c for c in companies if c.id},
            "fund": {f.id: f for f in funds if f.id},
        }
        # Review-band matches get a fast-model second opinion that weighs the
        # actual record fields (firm, city, strategy), not just the name.
        adjudications: dict[str, dict] = {}
        for k, d in decisions.items():
            if d.recommended_action != "review" or not d.best_match:
                continue
            rec = records_by_id[k].get(d.best_match.matched_id)
            if rec is None:
                continue
            say(f"Weighing whether '{d.name}' is the existing '{d.best_match.matched_name}'")
            verdict = _adjudicate_duplicate(
                client, k, _proposed_details(k, result.entity),
                _existing_details(k, rec))
            adjudications[k] = verdict
            if verdict.get("verdict") == "same":
                d.recommended_action = "link_existing"  # type: ignore[assignment]
                d.is_duplicate = True
            elif verdict.get("verdict") == "different":
                d.recommended_action = "create"  # type: ignore[assignment]

        proposals = notion_sync.plan_creations(result.entity, decisions,
                                               comments=result.rationale)

        def _dedupe_row(k: str, d) -> dict:
            rec = (records_by_id[k].get(d.best_match.matched_id)
                   if d.best_match else None)
            return {
                "action": d.recommended_action, "name": d.name,
                "match": d.best_match.matched_name if d.best_match else None,
                "match_id": d.best_match.matched_id if d.best_match else None,
                "score": d.best_match.score if d.best_match else None,
                "reason": d.best_match.reason if d.best_match else None,
                "existing": _existing_details(k, rec) if rec else None,
                "proposed": _proposed_details(k, result.entity),
                "ai": adjudications.get(k),
            }

        out["dedupe"] = {k: _dedupe_row(k, d) for k, d in decisions.items()}

        # Feed the manager thread: a linked company/fund (or an investment
        # email) means we now know who this manager is in Notion, so a later
        # prep or meeting note starts warm.
        linked = {k: d for k, d in decisions.items()
                  if d.recommended_action == "link_existing" and d.best_match}
        if linked and (result.is_investment or "company" in linked or "fund" in linked):
            try:
                thread_name = (result.entity.company_name or result.entity.fund_name
                               or result.entity.contact_name or msg.sender_name)
                managers.upsert(
                    thread_name,
                    aliases=[result.entity.contact_name, result.entity.fund_name,
                             msg.sender_name],
                    email=result.entity.contact_email,
                    add_history={"kind": "triage", "subject": msg.subject[:80]},
                    **_linked_fields(decisions))
            except Exception:  # noqa: BLE001 - the thread is an enhancement, never a blocker
                pass
        out["proposals"] = [
            {"kind": p.kind, "title": p.title, "needs_review": p.needs_review,
             "review_reason": p.review_reason,
             "properties": notion_sync.describe_properties(p.properties),
             "raw_properties": p.properties, "db_id": p.db_id}
            for p in proposals
        ]
    return out


class TriageIn(BaseModel):
    message: dict


@app.post("/api/triage")
def triage(body: TriageIn):
    msg = EmailMessage.model_validate(body.message)
    return _run(_triage_one, _client(), msg)


class TriageJobIn(BaseModel):
    messages: list[dict]


@app.post("/api/jobs/triage")
def start_triage_job(body: TriageJobIn):
    """Triage a batch as a background job: survives navigation, exposes
    per-message progress and partial results as they land."""
    msgs = [EmailMessage.model_validate(m) for m in body.messages]
    client = _client()

    def work(job: dict):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        job["total"] = len(msgs)
        job["done"] = 0
        job["partial"] = {}
        t_start = time.time()

        def one(msg: EmailMessage):
            job["current"] = msg.subject[:80]
            try:
                return msg.id, _triage_one(
                    client, msg,
                    progress=lambda what: job.__setitem__("current", what[:90]))
            except (llm.ClaudeCodeAuthError, llm.ClaudeCodeRateLimited):
                raise   # backend-level: stop the whole batch with a clear error
            except Exception as e:  # noqa: BLE001 - one bad message shouldn't stop the rest
                return msg.id, {"error": str(e)[:200]}

        # Each triage is its own CLI process, so running three at once is a
        # straight wall-clock win with no extra memory pressure to speak of.
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(one, m) for m in msgs]
            try:
                for fut in as_completed(futures):
                    _checkpoint(job)
                    mid, res = fut.result()
                    job["partial"][mid] = res
                    job["done"] += 1
                    avg = (time.time() - t_start) / job["done"]
                    job["eta_override"] = int(
                        job["elapsed"] + avg * (len(msgs) - job["done"]))
            except BaseException:
                for f in futures:
                    f.cancel()
                raise
        job["current"] = ""
        return {"results": job["partial"]}

    return _job_summary(_start_job("triage", f"Triage · {len(msgs)} messages", work))


@app.get("/api/jobs/{job_id}/partial")
def job_partial(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")
    return {"partial": job.get("partial", {}), "done": job.get("done", 0),
            "total": job.get("total", 0), "current": job.get("current", "")}


FLAGS_SCHEMA = {
    "type": "object",
    "properties": {
        "flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "flag": {"type": "string",
                             "enum": ["delete", "no_response", "shared", "triage",
                                      "read", "respond", "none"]},
                    "reason": {"type": "string", "description": "Five words or fewer"},
                },
                "required": ["id", "flag", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["flags"],
    "additionalProperties": False,
}

FLAGS_PROMPT = """You pre-sort a Weybourne investment inbox. For each message, one flag:
- "delete" — marketing, webcast replays, event blasts, system reminders (Concur etc.), \
newsletters with no specific opportunity.
- "no_response" — legitimate mail that requires nothing from the user (confirmations, \
FYIs, thank-yous closing a thread) and can be deleted or filed without action.
- "shared" — manager updates, LP letters, research and market commentary that belong in \
the shared investments mailbox rather than a personal one.
- "triage" — inbound from a manager or intermediary about a fund, deal, meeting or \
introduction: the ones worth running full triage on.
- "read" — worth the user's attention to read (relevant analysis, a reference reply, \
meaningful context) but no reply needed.
- "respond" — addressed to the user and needing their own reply: colleagues, direct 1:1 \
scheduling, questions put to them personally.
- "none" — anything that fits nothing above.
Judge from sender + subject + preview only. Reply for every message."""


class FlagsIn(BaseModel):
    messages: list[dict]


@app.post("/api/inbox/flags")
def inbox_flags(body: FlagsIn):
    """One fast model pass over the scan: a flag per message."""
    client = _client()
    lines = "\n".join(
        f"- id={m.get('id')} | from: {m.get('sender_name')} <{m.get('sender_email')}> | "
        f"subject: {m.get('subject')} | preview: {(m.get('body_preview') or '')[:150]}"
        for m in body.messages
    )

    def call():
        response = client.messages.create(
            model=config.FAST_MODEL,
            max_tokens=2000,
            system=FLAGS_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": FLAGS_SCHEMA}},
            messages=[{"role": "user", "content": lines}],
        )
        raw = next((b.text for b in response.content
                    if getattr(b, "type", None) == "text"), "")
        return json.loads(raw)

    return _run(call)


class ApplyIn(BaseModel):
    proposals: list[dict]
    approved_kinds: list[str]
    # Per-kind user edits made in the UI: {"fund": {"Name": "…", …}, …}.
    # Values are plain text; the payload type is preserved server-side.
    edits: dict[str, dict[str, str]] = {}


def _snap_to_options(kind: str, raw: dict) -> dict:
    """Map select/multi-select values onto the DB's ACTUAL options.

    The model writes e.g. 'Venture Capital' where the database's option is
    'PE - Venture'; without snapping, applying the page silently creates a new
    stray option. Exact (case-insensitive) match first, then containment, then
    a fuzzy match; a value with no plausible option is kept as written.
    """
    import difflib

    try:
        options = _OPTIONS_CACHE.get(kind)
        if options is None:
            db_id = {"fund": config.NOTION_FUNDS_DB, "company": config.NOTION_COMPANIES_DB,
                     "contact": config.NOTION_CONTACTS_DB}.get(kind)
            options = _notion.database_options(db_id or "")
            _OPTIONS_CACHE[kind] = options
    except Exception:  # noqa: BLE001
        return raw

    def snap(prop_name: str, value: str) -> str:
        opts = options.get(prop_name) or []
        if not value or not opts:
            return value
        low = value.strip().lower()
        for o in opts:
            if o.strip().lower() == low:
                return o
        contains = [o for o in opts if low in o.lower() or o.lower() in low]
        if len(contains) == 1:
            return contains[0]
        best = difflib.get_close_matches(value, opts, n=1, cutoff=0.6)
        return best[0] if best else value

    out = {}
    for name, payload in raw.items():
        if "select" in payload and payload["select"]:
            out[name] = {"select": {"name": snap(name, payload["select"]["name"])}}
        elif "multi_select" in payload:
            out[name] = {"multi_select": [{"name": snap(name, o["name"])}
                                          for o in payload["multi_select"]]}
        else:
            out[name] = payload
    return out


@app.post("/api/notion/apply")
def notion_apply(body: ApplyIn):
    props = []
    for p in body.proposals:
        raw = dict(p["raw_properties"])
        for prop_name, value in (body.edits.get(p["kind"]) or {}).items():
            if prop_name in raw:
                raw[prop_name] = notion_sync.patch_property(raw[prop_name], value)
        raw = _snap_to_options(p["kind"], raw)
        props.append(notion_sync.CreationProposal(
            kind=p["kind"], db_id=p.get("db_id"), title=p["title"],
            properties=raw, needs_review=p.get("needs_review", False),
            review_reason=p.get("review_reason", ""),
        ))
    res = notion_sync.apply_plan(props, _notion, approved_kinds=set(body.approved_kinds))
    return {"created": res.created, "skipped": res.skipped, "errors": res.errors,
            "live": _notion.live}


_OPTIONS_CACHE: dict = {}


@app.get("/api/notion/options")
def notion_options(kind: str):
    """Select/status/multi-select options per property for a DB kind — cached
    in memory for the process lifetime (schemas change rarely)."""
    db_id = {"fund": config.NOTION_FUNDS_DB, "company": config.NOTION_COMPANIES_DB,
             "contact": config.NOTION_CONTACTS_DB,
             "note": config.NOTION_NOTES_DB}.get(kind)
    if kind not in _OPTIONS_CACHE:
        try:
            _OPTIONS_CACHE[kind] = _notion.database_options(db_id or "")
        except Exception:  # noqa: BLE001 - dropdowns degrade to free text
            _OPTIONS_CACHE[kind] = {}
    return {"kind": kind, "options": _OPTIONS_CACHE[kind]}


_NAMES_CACHE: dict = {}


@app.get("/api/notion/names")
def notion_names(kind: str):
    """Names of every page in a relation-target DB, for searchable pickers
    (attendees, companies, funds). Cached ten minutes."""
    getter = {"contact": _notion.list_contacts, "company": _notion.list_companies,
              "fund": _notion.list_funds}.get(kind)
    if getter is None:
        raise HTTPException(status_code=400, detail=f"Unknown kind {kind!r}")
    entry = _NAMES_CACHE.get(kind)
    if not entry or time.time() - entry[0] > 600:
        try:
            names = sorted({(getattr(r, "name", "") or "").strip()
                            for r in getter()} - {""}, key=str.lower)
        except Exception:  # noqa: BLE001 - picker degrades to free text
            names = []
        _NAMES_CACHE[kind] = (time.time(), names)
    return {"kind": kind, "names": _NAMES_CACHE[kind][1]}


@app.post("/api/preferences/refresh")
def refresh_preferences():
    """Drop the cached CHAO preference-page text; the next screen re-pulls."""
    return {"dropped": _notion.refresh_page_text_cache()}


class UpdateExistingIn(BaseModel):
    page_id: str
    raw_properties: dict
    # The user chose "update my existing entry" in the duplicate side-by-side.


@app.post("/api/notion/update")
def notion_update(body: UpdateExistingIn):
    """Merge a proposal's details into an existing page instead of creating a
    duplicate. The existing page's Name is never changed; only non-empty
    proposed fields are written."""
    props = {}
    for name, payload in body.raw_properties.items():
        if name == "Name":
            continue   # never rename the existing record
        if "rich_text" in payload and not payload["rich_text"]:
            continue   # skip empty values — merge, don't blank
        if "multi_select" in payload and not payload["multi_select"]:
            continue
        props[name] = payload
    # Snap select/multi values to the DBs' actual options before writing; the
    # target kind isn't sent, so run all three snappers (each only touches
    # properties it has options for).
    props = _snap_to_options("fund", _snap_to_options("company",
            _snap_to_options("contact", props)))
    if not props:
        return {"updated": False, "detail": "nothing to update", "live": _notion.live}
    page = _notion.update_page(body.page_id, props)
    return {"updated": True, "url": page.get("url", ""), "live": _notion.live}


class SaveEmailNoteIn(BaseModel):
    message: dict
    summary: str = ""
    company_name: str = ""
    contact_ids: list[str] = []
    company_ids: list[str] = []
    fund_ids: list[str] = []
    company_names: list[str] = []
    fund_names: list[str] = []
    preview: bool = False
    # User edits from the preview step, keyed by the displayed property name.
    # Every field is editable; relation fields carry comma-separated names
    # which are resolved back to Notion records on save.
    edits: dict[str, str] = {}


def _find_contact(contacts, email: str = "", name: str = ""):
    """Exact email match first (the unique key), exact name second."""
    email, name = email.strip().lower(), name.strip().lower()
    if email:
        for c in contacts:
            if (c.email or "").strip().lower() == email:
                return c
    if name:
        for c in contacts:
            if (c.name or "").strip().lower() == name:
                return c
    return None


def _email_note_attendees(msg: EmailMessage,
                          extra_ids: list[str]) -> tuple[list[str], list[str]]:
    """(contact page ids, display names) for the note's Attendees relation.

    Inferred from the email itself: the SENDER (by email, falling back to
    their display name) and the mailbox owner — both looked up in the Notion
    contacts. Any ids the dedupe already matched are merged in.
    """
    try:
        contacts = _notion.list_contacts()
    except Exception:  # noqa: BLE001 - attendee inference must never block saving
        return list(extra_ids), []
    ids: list[str] = []
    names: list[str] = []
    owner_email = (config.MS_USER or "").strip().lower()
    owner_name = owner_email.split("@", 1)[0].replace(".", " ")
    for c in (_find_contact(contacts, msg.sender_email or "", msg.sender_name or ""),
              _find_contact(contacts, owner_email, owner_name)):
        if c and c.id and c.id not in ids:
            ids.append(c.id)
            names.append((c.name or "").strip())
    by_id = {c.id: c for c in contacts if c.id}
    for i in extra_ids:
        if i and i not in ids:
            ids.append(i)
            n = (getattr(by_id.get(i), "name", "") or "").strip()
            if n:
                names.append(n)
    return ids, names


def _ids_for_names(csv_text: str, records) -> list[str]:
    """Resolve a comma-separated list of names back to Notion record ids
    (exact case-insensitive name match; unknown names are dropped)."""
    out: list[str] = []
    for raw in (csv_text or "").split(","):
        wanted = raw.strip().lower()
        if not wanted:
            continue
        for r in records:
            if (getattr(r, "name", "") or "").strip().lower() == wanted and r.id:
                if r.id not in out:
                    out.append(r.id)
                break
    return out


def _ids_for_names_or_create(csv_text: str, records, db_id: str,
                             cache_kind: str = "") -> list[str]:
    """Like _ids_for_names, but a name with no existing page gets a minimal
    page created in the target DB (the picker's explicit "create new")."""
    out: list[str] = []
    for raw in (csv_text or "").split(","):
        name = raw.strip()
        if not name:
            continue
        match = next((r for r in records
                      if (getattr(r, "name", "") or "").strip().lower() == name.lower()
                      and r.id), None)
        if match:
            if match.id not in out:
                out.append(match.id)
            continue
        if not db_id and _notion.live:
            continue
        try:
            page = _notion.create_page(db_id or "mock-db", {
                "Name": {"title": [{"text": {"content": name[:200]}}]}})
            if page.get("id"):
                out.append(page["id"])
                _NAMES_CACHE.pop(cache_kind, None)   # the list just grew
        except Exception:  # noqa: BLE001 - a failed create must not block the note
            pass
    return out


@app.post("/api/notion/save-email")
def notion_save_email(body: SaveEmailNoteIn):
    """Save an email into the Notes DB following the workspace's convention for
    Note Type = Email notes. With preview=true nothing is written — the exact
    properties are returned for review/editing first."""
    msg = EmailMessage.model_validate(body.message)
    if _notion.live and not config.NOTION_NOTES_DB:
        raise HTTPException(status_code=503, detail="NOTION_NOTES_DB is not configured")

    contact_ids, attendee_names = _email_note_attendees(msg, body.contact_ids)
    who = " / ".join(x for x in (msg.sender_name, body.company_name) if x)
    default_title = f"Email: {msg.subject}" + (f" — {who}" if who else "")
    body_text = msg.body or msg.body_preview

    if body.preview:
        # Thoughts / Considerations should be a real summary of the email, in
        # the style of the existing Email notes — not the triage one-liner.
        summary = body.summary
        try:
            client = _client()
            response = client.messages.create(
                model=config.FAST_MODEL,
                max_tokens=300,
                system=("Summarise emails for a family-office CRM note. One to three "
                        "plain sentences: who wrote (name, role, firm if evident), "
                        "what they want or announced, and any concrete specifics "
                        "(dates, places, figures, names). Neutral third person. "
                        "No preamble, no markdown."),
                messages=[{"role": "user", "content":
                           f"From: {msg.sender_name} <{msg.sender_email}>\n"
                           f"Subject: {msg.subject}\n\n{body_text}"}],
            )
            generated = next((b.text for b in response.content
                              if getattr(b, "type", None) == "text"), "").strip()
            summary = generated or summary
        except Exception:  # noqa: BLE001 - a summary hiccup must not block the preview
            pass
        return {
            "editable": {
                "Name": default_title,
                "Note Type": "Email",
                "Date": (msg.received or "")[:10],
                "Done": "Yes",
                "Attendees": ", ".join(n for n in attendee_names if n),
                "Companies": ", ".join(body.company_names),
                "Fund": ", ".join(body.fund_names),
                "Thoughts / Considerations": summary,
            },
            "fixed": [
                ["Page body", f"full email text ({len(body_text):,} chars)"],
            ],
            "live": _notion.live,
        }

    # Every field arrives via edits (the preview values are the baseline, user
    # changes override). Relation fields carry names — resolve them back to
    # the actual records; a cleared field clears the relation.
    e = body.edits
    title = e.get("Name") or default_title
    summary = e.get("Thoughts / Considerations", body.summary)
    received = e.get("Date") or msg.received
    note_type = (e.get("Note Type") or "Email").strip()
    done = (e.get("Done") or "Yes").strip().lower() in ("yes", "y", "true", "1", "done")
    if "Attendees" in e:
        try:
            contact_ids = _ids_for_names(e["Attendees"], _notion.list_contacts())
        except Exception:  # noqa: BLE001
            pass
    company_ids = body.company_ids
    if "Companies" in e:
        try:
            company_ids = _ids_for_names(e["Companies"], _notion.list_companies())
        except Exception:  # noqa: BLE001
            pass
    fund_ids = body.fund_ids
    if "Fund" in e:
        try:
            fund_ids = _ids_for_names(e["Fund"], _notion.list_funds())
        except Exception:  # noqa: BLE001
            pass

    props = notion_sync.email_note_properties(
        subject="", sender_name="", company_name="",
        received=received, summary=summary,
        contact_ids=contact_ids, company_ids=company_ids,
        fund_ids=fund_ids,
    )
    props["Name"] = {"title": [{"text": {"content": title[:2000]}}]}
    props["Note Type"] = {"select": {"name": note_type}} if note_type else {"select": None}
    props["Done"] = {"checkbox": done}
    children = notion_sync.email_note_children(body_text)
    page = _notion.create_page(config.NOTION_NOTES_DB or "mock-db", props,
                               children=children)
    return {"url": page.get("url", ""), "id": page.get("id", ""),
            "live": _notion.live}


# --------------------------------------------------------------------------- #
# Key-questions library — questions starred in a briefing (or added by hand)
# persist per entity, and the note taker preloads them for the same meeting.
# --------------------------------------------------------------------------- #

QUESTIONS_DIR = BASE / "data" / "questions"


def _questions_path(entity: str):
    import re as _re

    slug = _re.sub(r"[^a-z0-9]+", "-", (entity or "").lower()).strip("-") or "unnamed"
    return QUESTIONS_DIR / f"{slug}.json"


# Questions now live on the manager THREAD — the per-manager context file
# that triage, prep, the note taker and Notion saves all share. Legacy
# per-entity question files are absorbed once at startup.
managers.migrate_legacy_questions(QUESTIONS_DIR)


@app.get("/api/questions")
def get_questions(entity: str = ""):
    thread = managers.find(entity)
    if thread:
        return {"entity": thread["entity"], "questions": thread.get("questions", [])}
    return {"entity": entity, "questions": []}


class QuestionsIn(BaseModel):
    entity: str
    questions: list[dict]   # [{q, src}]
    aliases: list[str] = [] # other names this meeting goes by (counterparty, company, email)


@app.post("/api/questions")
def save_questions(body: QuestionsIn):
    managers.upsert(body.entity, aliases=body.aliases, questions=body.questions)
    return {"saved": len(body.questions)}


@app.get("/api/managers")
def list_managers():
    """Recent manager threads — feeds the note taker's context picker."""
    return {"managers": managers.list_all()[:30]}


@app.get("/api/managers/resolve")
def resolve_manager(q: str = ""):
    """Fuzzy-resolve a name (calendar counterparty, subject, typed) to a thread."""
    thread = managers.find(q)
    return thread or {}


class SaveMeetingNoteIn(BaseModel):
    title: str
    note_type: str = "GP Meeting"
    markdown: str = ""
    overall_impression: str = ""
    who: str = ""
    entity: str = ""   # manager-thread name, when the session had one loaded
    preview: bool = False
    edits: dict[str, str] = {}


@app.post("/api/notion/save-meeting-note")
def notion_save_meeting_note(body: SaveMeetingNoteIn):
    """Save a drafted meeting note into the Notes DB. Same contract as
    save-email: preview=true returns every property for review/editing,
    then the save call applies the edits."""
    import datetime as dt

    if _notion.live and not config.NOTION_NOTES_DB:
        raise HTTPException(status_code=503, detail="NOTION_NOTES_DB is not configured")

    # The manager thread pre-fills what the prep already worked out: the
    # Notion contact, company and fund this meeting belongs to.
    thread = managers.find(body.entity or body.who) or {}

    attendee_ids: list[str] = []
    attendee_names: list[str] = []
    try:
        contacts = _notion.list_contacts()
        owner_email = (config.MS_USER or "").strip().lower()
        owner_name = owner_email.split("@", 1)[0].replace(".", " ")
        for c in (_find_contact(contacts, "", body.who),
                  _find_contact(contacts, thread.get("email", ""),
                                thread.get("contact_name", "")),
                  _find_contact(contacts, owner_email, owner_name)):
            if c and c.id and c.id not in attendee_ids:
                attendee_ids.append(c.id)
                attendee_names.append((c.name or "").strip())
    except Exception:  # noqa: BLE001
        pass

    if body.preview:
        return {
            "editable": {
                "Name": body.title,
                "Note Type": body.note_type,
                "Date": dt.date.today().isoformat(),
                "Done": "Yes",
                "Attendees": ", ".join(n for n in attendee_names if n),
                "Companies": thread.get("company_name", ""),
                "Fund": thread.get("fund_name", ""),
                "Thoughts / Considerations": body.overall_impression,
            },
            "fixed": [
                ["Page body", f"the full drafted note ({len(body.markdown):,} chars)"],
            ],
            "live": _notion.live,
        }

    e = body.edits
    if "Attendees" in e:
        try:
            attendee_ids = _ids_for_names_or_create(
                e["Attendees"], _notion.list_contacts(),
                config.NOTION_CONTACTS_DB, "contact")
        except Exception:  # noqa: BLE001
            pass
    company_ids: list[str] = []
    if e.get("Companies"):
        try:
            company_ids = _ids_for_names_or_create(
                e["Companies"], _notion.list_companies(),
                config.NOTION_COMPANIES_DB, "company")
        except Exception:  # noqa: BLE001
            pass
    fund_ids: list[str] = []
    if e.get("Fund"):
        try:
            fund_ids = _ids_for_names_or_create(
                e["Fund"], _notion.list_funds(),
                config.NOTION_FUNDS_DB, "fund")
        except Exception:  # noqa: BLE001
            pass

    note_type = (e.get("Note Type") or body.note_type).strip()
    done = (e.get("Done") or "Yes").strip().lower() in ("yes", "y", "true", "1", "done")
    props = notion_sync.email_note_properties(
        subject="", sender_name="", company_name="",
        received=e.get("Date") or dt.date.today().isoformat(),
        summary=e.get("Thoughts / Considerations", body.overall_impression),
        contact_ids=attendee_ids, company_ids=company_ids, fund_ids=fund_ids,
    )
    props["Name"] = {"title": [{"text": {"content": (e.get("Name") or body.title)[:2000]}}]}
    props["Note Type"] = {"select": {"name": note_type}} if note_type else {"select": None}
    props["Done"] = {"checkbox": done}
    children = notion_sync.markdown_children(body.markdown)
    page = _notion.create_page(config.NOTION_NOTES_DB or "mock-db", props,
                               children=children)
    # The saved note joins the manager's history.
    try:
        managers.upsert(
            thread.get("entity") or body.entity or body.who or body.title,
            add_history={"kind": "note", "url": page.get("url", ""),
                         "title": (e.get("Name") or body.title)[:80]})
    except Exception:  # noqa: BLE001
        pass
    return {"url": page.get("url", ""), "id": page.get("id", ""),
            "live": _notion.live}


class ScreenIn(BaseModel):
    entity: dict
    key_facts: list[str] = []


@app.post("/api/screen")
def screen(body: ScreenIn):
    entity = ExtractedEntity.model_validate(body.entity)
    # Reuse-only: if a prep already researched this manager the screen reads it
    # for free, but triage does not wait on a search it did not ask for.
    dossier, _ = get_dossier(_client(), entity.fund_name or entity.company_name,
                             entity.company_name or "", gather=False)
    result: PreferenceScreen = _run(screen_opportunity, _client(), entity,
                                    body.key_facts, _notion,
                                    extra_context=dossier_text(dossier) if dossier else "")
    return result.model_dump()


class DraftIn(BaseModel):
    message: dict
    entity: dict
    screen: dict | None = None
    dedupe: dict | None = None
    offer_slots: bool = True
    slot_minutes: int = 30   # 30 / 45 / 60-minute blocks, checked against the calendar


def _relationship_context(dedupe: dict | None) -> str:
    """Turn the triage dedupe result into prose for the draft prompt, so a
    reply to someone already in the CRM reads like a reply to someone we know."""
    lines = []
    for kind, d in (dedupe or {}).items():
        if (d or {}).get("action") == "link_existing" and d.get("match"):
            lines.append(f"- The {kind} '{d['match']}' is already in our Notion CRM "
                         f"({d.get('reason') or 'matched'}) — an existing relationship, "
                         "not a cold inbound.")
    return "\n".join(lines)


@app.post("/api/drafts")
def drafts(body: DraftIn):
    """Reply drafts. A preference screen is optional — when supplied the drafts
    incorporate its verdict; without one they stay neutral on fit."""
    msg = EmailMessage.model_validate(body.message)
    entity = ExtractedEntity.model_validate(body.entity)
    scr = (PreferenceScreen.model_validate(body.screen) if body.screen
           else PreferenceScreen(
               sleeve=entity.sleeve, overall_fit="Unclear",
               summary="No preference screen was run — keep the reply neutral on "
                       "fit; acknowledge, gather materials, and leave the door open.",
           ))
    slots = []
    if body.offer_slots:
        try:
            slots = _graph.find_free_slots(
                max_slots=4, slot_minutes=max(15, min(120, body.slot_minutes)))
        except Exception:
            # A calendar hiccup must never block reply drafting — just
            # draft without offering meeting slots.
            slots = []
    options = _run(generate_draft_options, _client(), msg, entity, scr, slots,
                   relationship=_relationship_context(body.dedupe))
    return {"options": [o.model_dump() for o in options]}


class SaveDraftIn(BaseModel):
    message_id: str
    body: str


@app.post("/api/drafts/save")
def save_draft(body: SaveDraftIn):
    """Create the reply as a REAL Outlook draft (never sent).

    With Graph credentials this uses the Graph API; without them it goes
    through the M365 connector like delete/forward do — previously the
    no-credentials path silently mocked the save, so the button did nothing.
    """
    if _graph.live:
        return {"result": _graph.create_reply_draft(body.message_id, body.body),
                "live": True}
    # Send tools are deliberately NOT in the allowlist — drafts only, ever.
    _mcp_mail_action(
        f'Create a DRAFT reply (draft ONLY — never send) to the Outlook message '
        f'with id "{body.message_id}" using the outlook_create_reply_draft tool. '
        f'The draft body, verbatim:\n\n' + body.body,
        ["mcp__claude_ai_Microsoft_365__outlook_create_reply_draft"],
    )
    return {"result": {"saved": True}, "live": True}


class DeleteIn(BaseModel):
    message_id: str


@app.post("/api/messages/delete")
def delete_message(body: DeleteIn):
    """Soft delete: moves to Deleted Items, recoverable from Outlook.

    With Graph credentials this calls the Graph API; without them (the MCP
    bridge setup) it performs the trash through the M365 connector — a real
    delete either way, never a silent no-op.
    """
    if _graph.live:
        return {"result": _graph.delete_message(body.message_id), "live": True}
    _mcp_mail_action(
        f'Move the Outlook message with id "{body.message_id}" to Deleted Items '
        "(trash — soft delete, never permanent) using outlook_batch_delete_messages "
        "or outlook_trash_thread.",
        ["mcp__claude_ai_Microsoft_365__outlook_batch_delete_messages",
         "mcp__claude_ai_Microsoft_365__outlook_trash_thread"],
    )
    return {"result": {"status": "deleted"}, "live": True}


# --------------------------------------------------------------------------- #
# Meeting prep
# --------------------------------------------------------------------------- #

@app.get("/api/calendar")
def calendar(days: int = 21, back: int = 0):
    """Calendar window: ``days`` ahead and optionally ``back`` days into the
    past (the note taker's picker scrolls to previous meetings)."""
    events = (_graph.events_window(back, days) if back > 0
              else _graph.upcoming_events(days=days))
    out = []
    for e in sorted(events, key=lambda ev: ev.start or ""):
        name, email = counterparty_from_event(e)
        out.append({**e.model_dump(), "counterparty_name": name,
                    "counterparty_email": email})
    return {"events": out}


def _attach_research(ctx: PrepContext, name: str, company: str = "") -> str:
    """Hang the shared web dossier on a prep context.

    One gather per firm, reused by every consumer: the screen, the quick prep
    and the full briefing all read the same searches, whether they run together
    or weeks apart. Returns a line describing what happened, for the job log.
    """
    dossier, origin = get_dossier(_client(), name, company)
    if not dossier:
        return ("research could not be gathered — the synthesis calls will "
                "search for themselves" if origin == "failed"
                else "no counterparty to research")
    ctx.web_context = dossier_text(dossier)
    ctx.sources.extend(dossier_sources(dossier))
    n = len(dossier.get("sources") or [])
    if origin == "cache":
        days = int(age_days(dossier))
        return (f"reused the research gathered {'today' if days < 1 else f'{days} day(s) ago'}"
                f" — {n} source(s), no new searches")
    return f"searched the web — {n} source(s), shared with every pass on this firm"


class PrepIn(BaseModel):
    name: str
    email: str = ""
    company: str = ""
    event: dict | None = None
    depth: str = "quick"          # quick | full


@app.post("/api/prep")
def prep(body: PrepIn):
    from src.schemas import CalendarEvent

    event = CalendarEvent.model_validate(body.event) if body.event else None
    ctx: PrepContext = build_context(
        _notion, counterparty_name=body.name, counterparty_email=body.email,
        company_name=body.company, event=event, research=None,
    )
    _attach_research(ctx, body.name, body.company)
    if body.depth == "full":
        data, html_out = _run(build_briefing, _client(), ctx)
        return {"kind": "briefing", "entity": data.get("entity"), "html": html_out}
    result = _run(synthesize_prep, _client(), ctx)
    return {"kind": "quick", **result.model_dump()}


# --------------------------------------------------------------------------- #
# Background jobs — long work survives navigation; the UI polls for progress.
# In-memory store: this is a single-user local app, and jobs are cheap to redo.
# --------------------------------------------------------------------------- #

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()

# Rolling durations of completed jobs per kind → a learned ETA. Seeded with
# rough first-run figures so the very first job still shows an estimate.
_DURATIONS: dict[str, list[float]] = {}
_ETA_SEED = {"prep": 150, "whats-new-team": 60, "whats-new-inbox": 50,
             "outlook-refresh": 180, "felix": 600, "felix-undo": 30}


def _eta(kind: str) -> int:
    seen = _DURATIONS.get(kind)
    if seen:
        return int(sum(seen) / len(seen))
    return _ETA_SEED.get(kind, 90)


class _Cancelled(Exception):
    pass


def _checkpoint(job: dict) -> None:
    """Raise if the user cancelled — called by work() between stages."""
    if job.get("cancel"):
        raise _Cancelled()


def _job_summary(j: dict) -> dict:
    out = {**{k: j[k] for k in ("id", "kind", "label", "status", "stages",
                                "elapsed", "created")},
           "eta": j.get("eta_override") or _eta(j["kind"])}
    for k in ("done", "total", "current"):
        if k in j:
            out[k] = j[k]
    return out


def _start_job(kind: str, label: str, work) -> dict:
    """Run `work(job)` in a thread. `work` appends stages and returns a result."""
    import uuid

    job = {"id": uuid.uuid4().hex[:12], "kind": kind, "label": label,
           "status": "running", "stages": [], "elapsed": 0,
           "created": time.strftime("%H:%M"), "result": None, "error": None,
           "cancel": False, "_t0": time.time()}
    with _JOBS_LOCK:
        _JOBS[job["id"]] = job

    def run():
        # A cancelled job's status is set by the cancel endpoint the moment the
        # user clicks — this thread must never resurrect it to done/error when
        # the in-flight model call finally returns.
        try:
            result = work(job)
            if job["status"] == "running":
                job["result"] = result
                job["status"] = "done"
                _DURATIONS.setdefault(kind, []).append(time.time() - job["_t0"])
                del _DURATIONS[kind][:-5]   # keep the last five runs
        except _Cancelled:
            job["status"] = "cancelled"
        except llm.ClaudeCodeAuthError as e:
            if job["status"] == "running":
                job["status"], job["error"] = "error", f"Not signed in to Claude: {e}"
        except llm.ClaudeCodeRateLimited as e:
            if job["status"] == "running":
                job["status"], job["error"] = "error", f"Claude usage limit reached: {e}"
        except Exception as e:  # noqa: BLE001
            if job["status"] == "running":
                job["status"], job["error"] = "error", str(e)
        job["elapsed"] = int(time.time() - job["_t0"])

    def tick():
        while job["status"] == "running":
            job["elapsed"] = int(time.time() - job["_t0"])
            time.sleep(1)

    threading.Thread(target=run, daemon=True).start()
    threading.Thread(target=tick, daemon=True).start()
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")
    job["cancel"] = True
    # Cancellation is immediate from the user's point of view: the job reads
    # as cancelled now, and the worker thread discards whatever its in-flight
    # model call eventually returns.
    if job["status"] == "running":
        job["status"] = "cancelled"
        job["elapsed"] = int(time.time() - job["_t0"])
    return {"status": "cancelled"}


@app.get("/api/jobs")
def jobs(kind: str = ""):
    with _JOBS_LOCK:
        items = [j for j in _JOBS.values() if not kind or j["kind"] == kind]
    items.sort(key=lambda j: j["_t0"], reverse=True)
    return {"jobs": [_job_summary(j) for j in items[:20]]}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")
    return {**_job_summary(job), "result": job["result"], "error": job["error"]}


@app.post("/api/jobs/prep")
async def start_prep_job(
    name: str = Form(...),
    email: str = Form(""),
    company: str = Form(""),
    event: str = Form(""),
    include_briefing: str = Form("1"),
    include_screen: str = Form("0"),
    file: UploadFile | None = None,
):
    """Meeting prep as a background job — keeps running if the user navigates
    away. Produces the structured briefing (rendered by the page) and/or a
    preference review against the Notion CHAO pages.
    """
    from src.schemas import CalendarEvent

    ev = CalendarEvent.model_validate(json.loads(event)) if event else None
    pdf_path = None
    if file is not None:
        suffix = Path(file.filename or "deck.pdf").suffix or ".pdf"
        pdf_path = Path(tempfile.gettempdir()) / f"prep-deck-{name[:20]}{suffix}"
        pdf_path.write_bytes(await file.read())

    want_brief = include_briefing == "1"
    want_screen = include_screen == "1"
    client = _client()   # fail fast with a clear 503 before creating the job

    def work(job: dict):
        from src.features.brief_builder import synthesize_briefing

        job["stages"].append({"label": "Resolve the counterparty",
                              "detail": name + (f" ({email})" if email else "")})
        # Announce the Notion read BEFORE doing it: a cold cache pull over a
        # 10k-record workspace takes minutes, and without this stage the job
        # looks stuck on "Resolve the counterparty".
        job["stages"].append({
            "label": "Read Notion records",
            "detail": ("syncing changes since the last run — only the first-ever "
                       "sync pulls the whole workspace"
                       if _notion.live else "sample data"),
        })
        ctx = build_context(
            _notion, counterparty_name=name, counterparty_email=email,
            company_name=company, event=ev, pdf_path=pdf_path,
            # No pre-gathering step: the synthesis call has WebSearch itself and
        # does the research inline. A stub that returns "" used to log a
        # "Web research:" source for a search that never happened.
        research=None,
        )
        notion_note = "live Notion" if _notion.live else "sample data — not your live Notion"
        deck_note = (f"deck read ({len(ctx.document_text):,} chars)"
                     if ctx.document_text else "no deck attached")
        # One research pass, before the fork — so the screen and the briefing
        # read the same facts, and so running one of them later reuses rather
        # than repeats the searches.
        job["stages"].append({"label": "Background research",
                              "detail": "checking for research already gathered "
                                        "on this firm"})
        _checkpoint(job)
        job["stages"][-1]["detail"] = _attach_research(ctx, name, company)
        job["stages"].append({"label": "Context gathered",
                              "detail": f"{len(ctx.sources)} source(s) against {notion_note} · {deck_note}"})

        result: dict = {"kind": "prep", "entity": name,
                        "email": email, "company": company}

        def run_screen():
            entity = ExtractedEntity(
                fund_name=name, company_name=company or "",
                contact_email=email,
                summary=(ctx.document_text[:600] or ctx.meeting_subject or name),
            )
            # The screen reads the SAME gathered context as the briefing — the
            # deck in full, our own records and the shared web research.
            # Screening a criterion against a 600-character summary cannot
            # produce a cited finding, only a guess dressed as one.
            extra = "\n\n".join(x for x in (
                f"OUR RECORDS:\n{ctx.notion_context}" if ctx.notion_context else "",
                f"INDEPENDENT WEB RESEARCH:\n{ctx.web_context}" if ctx.web_context else "",
                f"MATERIALS SUPPLIED:\n{ctx.document_text}" if ctx.document_text else "",
            ) if x)
            return screen_opportunity(client, entity, [], _notion,
                                      extra_context=extra).model_dump()

        def run_brief():
            data = synthesize_briefing(client, ctx)
            data["meeting_details"] = " · ".join(
                x for x in (ctx.meeting_subject, ctx.meeting_time) if x)
            return data

        _checkpoint(job)
        if want_screen and want_brief:
            # Independent model calls — run them side by side rather than
            # serially, which roughly halves the wall-clock for a full prep.
            from concurrent.futures import ThreadPoolExecutor

            job["stages"].append({
                "label": "Preference review + briefing (in parallel)",
                "detail": "screening against the CHAO pages while the "
                          "briefing synthesises — typically 1–3 minutes",
            })
            with ThreadPoolExecutor(max_workers=2) as pool:
                f_screen = pool.submit(run_screen)
                f_brief = pool.submit(run_brief)
                result["screen"] = f_screen.result()
                result["briefing"] = f_brief.result()
            _checkpoint(job)
        elif want_screen:
            job["stages"].append({"label": "Preference review",
                                  "detail": "screening against the CHAO preference pages"})
            result["screen"] = run_screen()
            _checkpoint(job)
        elif want_brief:
            job["stages"].append({
                "label": "Synthesise the briefing",
                "detail": "typically 1–3 minutes on the Claude account backend",
            })
            result["briefing"] = run_brief()
            _checkpoint(job)

        job["stages"].append({"label": "Done", "detail": ""})
        _save_prep(job, result)
        # Stamp the manager thread: resolve the counterparty against Notion
        # and record this prep, so the note taker (and the next prep) starts
        # with the linkage already made.
        try:
            entity_name = (result.get("briefing") or {}).get("entity") or name
            ent = ExtractedEntity(
                contact_name="" if "@" in name else name,
                contact_email=email, company_name=company or name, fund_name=name)
            dec = dedupe_entity(ent, _notion.list_contacts(),
                                _notion.list_companies(), _notion.list_funds())
            managers.upsert(
                entity_name, aliases=[name, company, email], email=email,
                add_history={"kind": "prep", "id": job["id"], "label": job["label"]},
                **_linked_fields(dec))
        except Exception:  # noqa: BLE001 - the thread is an enhancement
            pass
        return result

    parts = [p for p, on in (("briefing", want_brief), ("preferences", want_screen)) if on]
    return _job_summary(_start_job("prep", f"{' + '.join(parts) or 'prep'} · {name}", work))


# --------------------------------------------------------------------------- #
# Track records
# --------------------------------------------------------------------------- #

@app.post("/api/track-record")
async def track_record(file: UploadFile):
    suffix = Path(file.filename or "upload").suffix or ".xlsx"
    tmp = Path(tempfile.gettempdir()) / f"tr-upload{suffix}"
    tmp.write_bytes(await file.read())
    record = _run(analyse_file, _client(), tmp)
    out = record.model_dump()
    best, worst = best_worst_period(record.periods)
    out["stats"] = {
        "cumulative_return_pct": cumulative_return_pct(record.periods),
        "max_drawdown_pct": max_drawdown_pct(record.periods),
        "best": best.model_dump() if best else None,
        "worst": worst.model_dump() if worst else None,
    }
    return out


# --------------------------------------------------------------------------- #
# Live meeting
# --------------------------------------------------------------------------- #

@app.post("/api/stt")
async def stt(file: UploadFile, lang: str = "auto"):
    """Transcribe one recorded chunk. ``lang`` pins the spoken language
    ("auto" lets whisper detect it per chunk, so multilingual meetings work).

    Whisper is CPU-bound and must NOT run on the event loop — inline it wedges
    every other endpoint for the duration of a busy recording session."""
    from starlette.concurrency import run_in_threadpool

    audio = await file.read()
    try:
        result = await run_in_threadpool(transcribe_wav, audio, lang)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return result


class TidyIn(BaseModel):
    raw: str
    prev_tail: str = ""
    output_language: str = "English"
    detected_language: str = ""


@app.post("/api/live/tidy")
def live_tidy(body: TidyIn):
    """Raw whisper chunk → clean sentences in the chosen output language
    (Haiku). The page shows this cleaned text, never the raw transcript."""
    if not body.raw.strip():
        return {"text": ""}
    text = _run(tidy_transcript_chunk, _client(), body.raw, body.prev_tail,
                body.output_language, body.detected_language)
    return {"text": text}


class ReadIn(BaseModel):
    transcript: str
    open_items: list[dict] = []
    context: str = ""
    prior_recaps: str = ""
    last_tail: str = ""


def _buffer_from(text: str) -> TranscriptBuffer:
    buf = TranscriptBuffer()
    if text.strip():
        buf.add(text)
    return buf


@app.post("/api/live/read")
def live_read(body: ReadIn):
    parsed = _run(read_transcript_batch, _client(), _buffer_from(body.transcript),
                  body.open_items, body.context, body.prior_recaps, body.last_tail)
    return parsed


class SharpenIn(BaseModel):
    transcript: str
    rough: str
    context: str = ""


@app.post("/api/live/sharpen")
def live_sharpen(body: SharpenIn):
    return _run(sharpen_question, _client(), _buffer_from(body.transcript),
                body.rough, body.context)


class NoteIn(BaseModel):
    transcript: str
    context: str = ""
    unanswered: list[str] = []


@app.post("/api/live/note")
def live_note(body: NoteIn):
    note = _run(draft_meeting_note, _client(), _buffer_from(body.transcript),
                body.context, body.unanswered)
    return {"note": note, "markdown": note_to_markdown(note)}


@app.post("/api/live/note-stream")
def live_note_stream(body: NoteIn):
    """The note draft as it is written — plain-text markdown chunks, so the
    page can render the draft forming instead of a spinner. On any failure a
    sentinel line is emitted and the client falls back to /api/live/note."""
    system, prompt = note_stream_args(
        _buffer_from(body.transcript), body.context, body.unanswered)

    def gen():
        try:
            yield from llm.stream_text(prompt, system=system,
                                       model=config.REASONING_MODEL)
        except Exception as e:  # noqa: BLE001 - surfaced via the sentinel
            yield f"\n[[STREAM-FAILED]] {str(e)[:200]}"

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8",
                             headers={"X-Accel-Buffering": "no"})


@app.post("/api/live/note-parse")
def live_note_parse(body: dict):
    """Fields the Notion save needs, recovered from a streamed markdown note."""
    return note_from_markdown(str(body.get("markdown") or ""))


class RefineThoughtsIn(BaseModel):
    current: str = ""
    additions: str
    context: str = ""


@app.post("/api/live/refine-thoughts")
def live_refine_thoughts(body: RefineThoughtsIn):
    """Rewrite the note's Thoughts / Considerations giving effect to the
    investor's own added thoughts."""
    text = _run(refine_thoughts, _client(), body.current, body.additions, body.context)
    return {"text": text}


# --------------------------------------------------------------------------- #
# Live-session autosave + transcript library. The browser is the only place a
# recording lives, so the store mirrors its state to disk every few seconds
# (autosave) and files the session permanently on Stop (finish).
# --------------------------------------------------------------------------- #

class LiveSessionIn(BaseModel):
    id: str
    who: str = ""
    goal: str = ""
    started: str = ""
    transcript: str = ""
    entries: list[dict] = []
    recaps: list[dict] = []
    questions: list[dict] = []
    # The drafted note travels with the session, so reopening a library
    # transcript brings the written note back too.
    note_markdown: str = ""
    note_fields: dict = {}


def _session_record(body: LiveSessionIn) -> dict:
    return {"id": body.id, "who": body.who, "goal": body.goal,
            "started": body.started, "transcript": body.transcript,
            "entries": body.entries, "recaps": body.recaps,
            "questions": body.questions,
            "note_markdown": body.note_markdown,
            "note_fields": body.note_fields}


@app.post("/api/live/autosave")
def live_autosave(body: LiveSessionIn):
    transcript_library.autosave(_session_record(body))
    return {"ok": True}


@app.post("/api/live/finish")
def live_finish(body: LiveSessionIn):
    return transcript_library.finish(_session_record(body))


@app.get("/api/transcripts")
def transcripts_list():
    return {"transcripts": transcript_library.list_all()}


@app.get("/api/transcripts/{sid}")
def transcript_detail(sid: str):
    rec = transcript_library.load(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="No such transcript")
    return rec


@app.delete("/api/transcripts/{sid}")
def transcript_delete(sid: str):
    if not transcript_library.delete(sid):
        raise HTTPException(status_code=404, detail="No such transcript")
    return {"deleted": sid}


# --------------------------------------------------------------------------- #
# Prep library — completed preps persist to disk for future reference.
# --------------------------------------------------------------------------- #

PREPS_DIR = BASE / "data" / "preps"


def _save_prep(job: dict, result: dict) -> None:
    """Persist a completed prep. Failures never break the job itself."""
    try:
        PREPS_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "id": job["id"],
            "name": result.get("entity") or job["label"],
            "label": job["label"],
            "created": time.strftime("%Y-%m-%d %H:%M"),
            "outputs": [k for k in ("briefing", "screen") if k in result],
            "result": result,
        }
        (PREPS_DIR / f"{job['id']}.json").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


@app.get("/api/preps")
def list_preps():
    if not PREPS_DIR.exists():
        return {"preps": []}
    out = []
    for f in sorted(PREPS_DIR.glob("*.json"),
                    key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({k: d[k] for k in ("id", "name", "created", "outputs")})
        except Exception:  # noqa: BLE001
            continue
    return {"preps": out[:50]}


@app.get("/api/preps/{prep_id}")
def get_prep(prep_id: str):
    path = PREPS_DIR / f"{prep_id}.json"
    if not path.exists() or ".." in prep_id or "/" in prep_id:
        raise HTTPException(status_code=404, detail="No such prep")
    return json.loads(path.read_text(encoding="utf-8"))


@app.delete("/api/preps/{prep_id}")
def delete_prep(prep_id: str):
    path = PREPS_DIR / f"{prep_id}.json"
    if not path.exists() or ".." in prep_id or "/" in prep_id:
        raise HTTPException(status_code=404, detail="No such prep")
    path.unlink()
    return {"deleted": prep_id}


# Warm the Notion list cache in the background at startup, so the first triage
# or prep doesn't pay the multi-minute cold pull interactively.
def _warm_notion_cache():
    if not _notion.live:
        return
    try:
        _notion.list_contacts()
        _notion.list_companies()
        _notion.list_funds()
    except Exception:  # noqa: BLE001
        pass


threading.Thread(target=_warm_notion_cache, daemon=True).start()


# --------------------------------------------------------------------------- #
# Outlook refresh via the Claude Code MCP bridge (no Entra registration).
# The user's claude.ai Microsoft 365 connector is available to the Claude CLI,
# so a headless call with the READ-ONLY mail/calendar tools fetches real data
# and this endpoint writes it into the snapshot files the Graph connector reads.
# --------------------------------------------------------------------------- #

_M365_READONLY_TOOLS = ",".join([
    "mcp__claude_ai_Microsoft_365__outlook_email_search",
    "mcp__claude_ai_Microsoft_365__outlook_calendar_search",
    # The search tool caps bodies at ~250 chars; read_resource fetches the
    # complete message so triage and saved notes see the full email.
    "mcp__claude_ai_Microsoft_365__read_resource",
])

_MCP_PREAMBLE = """The claude.ai Microsoft 365 connector may still be connecting when you
start — if the outlook tools are not yet visible, use ToolSearch with the query
"outlook email calendar search" to load them, and retry a few times over ~20
seconds before concluding they are unavailable. Reply with ONLY a JSON array,
no fences, no commentary. Use empty strings for anything unavailable. Never
invent content. If access fails entirely, reply with [].
"""

_EMAIL_SHAPE = """[{"id": str, "subject": str, "sender_name": str,
"sender_email": str, "received": ISO8601 str, "body_preview": str (~200 chars),
"body": str (the COMPLETE plain-text body of the message — do not truncate,
summarise, or abbreviate it; include signatures), "has_attachments": bool,
"folder": "Inbox"}]

IMPORTANT: the email search tool returns only a ~250-character preview of each
body. That is NOT the complete body. For EVERY message in the result, fetch the
full content with the read_resource tool (each search result carries a resource
URI) and put the complete plain text in "body". Only fall back to the preview
for a message whose full read fails."""

# Incremental refresh: bodies already held in the snapshot are not re-fetched —
# the agent returns a bare id for those and the server splices the stored row
# back in. On a routine 30-minute auto-refresh this cuts the work from ~20 full
# message reads to only whatever is genuinely new.
_CACHED_IDS_HINT = """

EXCEPTION — already-cached messages. The complete bodies of these message ids
are already stored locally:
{ids}
For any search result whose id is in that list, do NOT call read_resource and do
NOT output its body or other fields — output just {{"id": "<the id>"}} for it.
Fetch complete bodies only for messages NOT in the list."""


def _merge_cached_rows(rows: list, prev_by_id: dict) -> tuple[list, int]:
    """Splice previously stored rows in place of the agent's bare-id markers."""
    merged: list = []
    reused = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "")
        if rid in prev_by_id and not (r.get("body") or "").strip():
            merged.append(prev_by_id[rid])
            reused += 1
        else:
            merged.append(r)
    return merged, reused

_REFRESH_PARTS = {
    "inbox": (_MCP_PREAMBLE
              + "Fetch my top-level Outlook Inbox: the 20 most recent messages from "
                "the last 7 days. JSON array shape:\n" + _EMAIL_SHAPE),
    "calendar": (_MCP_PREAMBLE
                 + "Fetch my Outlook calendar events in TWO separate searches, "
                   "then merge the results into ONE JSON array: search 1 = "
                   "today through 21 days ahead (do this first — never lose "
                   "the upcoming meetings to a result cap); search 2 = the "
                   "past 30 days up to today. If a search caps its results, "
                   "keep the events closest to today. JSON array "
                   'shape:\n[{"id": str, "subject": str, "start": ISO8601 str, '
                   '"end": ISO8601 str, "location": str, "organizer": {"name": str, '
                   '"email": str}, "attendees": [{"name": str, "email": str}], '
                   '"is_online": bool, "body_preview": str}]'),
    "shared": (_MCP_PREAMBLE
               + "Fetch the Inbox of the shared mailbox {shared}: the 20 most recent "
                 "messages from the last 7 days. If you cannot access that mailbox, "
                 "reply []. JSON array shape:\n" + _EMAIL_SHAPE),
}

_SNAPSHOT_FILES = {
    "inbox": "inbox_snapshot.json",
    "calendar": "calendar_snapshot.json",
    "shared": "shared_inbox_snapshot.json",
}


@app.post("/api/jobs/outlook-refresh")
def start_outlook_refresh():
    import subprocess

    def work(job: dict):
        cli = llm.resolve_cli_path(config.CLAUDE_CLI_PATH) or config.CLAUDE_CLI_PATH
        data_dir = BASE / "data"
        data_dir.mkdir(exist_ok=True)

        def fetch(prompt: str) -> list:
            proc = subprocess.run(
                [cli, "-p", prompt.replace("{shared}", config.SHARED_MAILBOX),
                 "--allowedTools", _M365_READONLY_TOOLS + ",ToolSearch",
                 # Copying mail bodies is transcription, not reasoning — the
                 # fast model streams them out several times quicker.
                 "--model", llm._cli_model(config.FAST_MODEL) or "haiku"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                # Search + a full read_resource per message takes a while.
                timeout=900, stdin=subprocess.DEVNULL,
            )
            raw = (proc.stdout or "").strip()
            start, end = raw.find("["), raw.rfind("]")
            if start == -1 or end == -1:
                raise RuntimeError(
                    f"No JSON in the connector reply: {(raw or proc.stderr)[:250]}")
            return json.loads(raw[start:end + 1])

        counts: dict = {}

        def fetch_part(part: str, prompt: str):
            try:
                target = data_dir / _SNAPSHOT_FILES[part]
                # Incremental: tell the agent which bodies we already hold so it
                # only does full reads for genuinely new messages.
                prev_by_id: dict = {}
                if part in ("inbox", "shared") and target.exists():
                    try:
                        prev_by_id = {
                            str(r["id"]): r
                            for r in json.loads(target.read_text(encoding="utf-8"))
                            if isinstance(r, dict) and r.get("id")}
                    except Exception:  # noqa: BLE001 - corrupt snapshot → full fetch
                        prev_by_id = {}
                if prev_by_id:
                    prompt = prompt + _CACHED_IDS_HINT.format(
                        ids="\n".join(prev_by_id))
                rows = fetch(prompt)
                if not rows:
                    # Connector attaches asynchronously — one retry on empty.
                    job["stages"].append({"label": f"{part} empty — retrying once",
                                          "detail": "connector may have been slow to attach"})
                    rows = fetch(prompt)
                reused = 0
                if prev_by_id:
                    rows, reused = _merge_cached_rows(rows, prev_by_id)
                if rows or not target.exists():
                    target.write_text(json.dumps(rows, indent=1), encoding="utf-8")
                    counts[part] = len(rows)
                    if reused:
                        counts[f"{part}_cached"] = reused
                else:
                    # Never clobber a good snapshot with an empty fetch — a
                    # missed connector attach must not erase real data.
                    counts[part] = 0
                    counts[f"{part}_note"] = "empty result — kept the previous snapshot"
            except Exception as e:  # noqa: BLE001 - one part failing shouldn't kill the rest
                counts[part] = 0
                counts[f"{part}_error"] = str(e)[:200]

        # The three mailbox fetches are independent CLI processes — run them
        # side by side; with full per-message reads a serial pass is too slow.
        from concurrent.futures import ThreadPoolExecutor

        job["stages"].append({"label": "Fetch inbox + calendar + shared (in parallel)",
                              "detail": "incremental — full bodies fetched only for new messages"})
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(fetch_part, part, prompt)
                       for part, prompt in _REFRESH_PARTS.items()]
            for f in futures:
                f.result()
        job["stages"].append({"label": "Done", "detail": ""})
        return counts

    return _job_summary(_start_job("outlook-refresh", "Outlook refresh", work))


# Keep the Outlook snapshots fresh automatically: one refresh shortly after
# the server starts, then every OUTLOOK_AUTO_REFRESH_MIN minutes (0 disables).
def _auto_outlook_refresh():
    import os

    every_min = int(os.environ.get("OUTLOOK_AUTO_REFRESH_MIN", "30"))
    if every_min <= 0:
        return
    time.sleep(15)   # let the server finish booting first
    while True:
        try:
            already = any(j.get("kind") == "outlook-refresh" and j.get("status") == "running"
                          for j in _JOBS.values())
            if not already:
                start_outlook_refresh()
        except Exception:  # noqa: BLE001 - a failed cycle just waits for the next
            pass
        time.sleep(every_min * 60)


threading.Thread(target=_auto_outlook_refresh, daemon=True).start()


# --------------------------------------------------------------------------- #
# Felix — the autonomous Notion clean-up agent (src/features/felix/).
# Runs go through the jobs framework; the change log, snapshots and config
# live under data/felix/, so review and stats never round-trip to Notion.
# --------------------------------------------------------------------------- #

class FelixRunIn(BaseModel):
    dry_run: Optional[bool] = None      # None → dry unless live mode is enabled
    max_writes: Optional[int] = None
    databases: Optional[list[str]] = None
    # Ordinary runs never search the web; the user asks for that separately
    # once they have seen what could not be settled from the notes.
    web_research: bool = False


@app.post("/api/jobs/felix")
def start_felix_job(body: Optional[FelixRunIn] = None):
    body = body or FelixRunIn()
    cfg = felix_store.load_config()
    live_ok = bool(cfg.get("live_enabled"))
    dry = body.dry_run if body.dry_run is not None else (not live_ok)
    if not dry and not live_ok:
        raise HTTPException(status_code=400,
                            detail="Live runs are disabled — review a dry run "
                                   "and enable live mode first")
    with _JOBS_LOCK:
        if any(j["kind"] == "felix" and j["status"] == "running"
               for j in _JOBS.values()):
            raise HTTPException(status_code=409,
                                detail="A Felix run is already in progress")
    opts = FelixRunOptions(dry_run=dry, web_research=bool(body.web_research))
    if body.max_writes:
        opts.max_writes = max(1, min(200, body.max_writes))
    if body.databases:
        opts.databases = [d for d in body.databases
                          if d in ("contacts", "companies", "funds", "notes")]
    client = _client()

    def work(job: dict):
        return felix_run(job, _notion, client, opts,
                         checkpoint=lambda: _checkpoint(job))

    label = "Felix clean-up" + (" (dry run)" if dry else "")
    return _job_summary(_start_job("felix", label, work))


@app.get("/api/felix/runs")
def felix_runs():
    return {"runs": [r.model_dump() for r in felix_store.list_runs()]}


@app.get("/api/felix/runs/{run_id}")
def felix_run_detail(run_id: str):
    run = felix_store.load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such run")
    return {**run.model_dump(),
            "changes": [c.model_dump()
                        for c in felix_store.load_changes(run_id)]}


@app.get("/api/felix/changes")
def felix_changes(status: str = "", review: str = "", db: str = "",
                  change_type: str = "", run_id: str = "", limit: int = 100,
                  offset: int = 0):
    rows = felix_store.list_all_changes(
        status=status, review=review, db=db, change_type=change_type,
        run_id=run_id, limit=max(1, min(500, limit)), offset=max(0, offset))
    return {"changes": [c.model_dump() for c in rows]}


class FelixReviewIn(BaseModel):
    action: str          # approve | undo
    # Which record of a duplicate pair to keep. Empty means Felix's own pick
    # (the richer copy); the reviewer can override it in the side-by-side.
    survivor_id: str = ""


_FELIX_TOPUP = {"last": 0.0}


def _felix_topup_if_low():
    """Keep the review queue stocked: when clearing decisions drops the pool
    of outstanding suggestions below ten, quietly start another dry run (which
    researches the next unsure items — decided pairs are never re-searched)."""
    if time.time() - _FELIX_TOPUP["last"] < 900:
        return
    with _JOBS_LOCK:
        if any(j["kind"] == "felix" and j["status"] == "running"
               for j in _JOBS.values()):
            return
    waiting = [c for c in felix_store.list_all_changes(
                   review="Awaiting Review", limit=300)
               if c.execution_status in ("Proposed", "Recommended",
                                         "Planned (dry-run)")]
    if len(waiting) >= 10:
        return
    client = _client()
    if client is None:
        return
    _FELIX_TOPUP["last"] = time.time()
    opts = FelixRunOptions(dry_run=True)

    def work(job: dict):
        return felix_run(job, _notion, client, opts,
                         checkpoint=lambda: _checkpoint(job))

    _start_job("felix", "Felix top-up (dry run)", work)


def _resolve_reviewed_pair(change, action: str) -> None:
    """A human decision on a duplicate finding settles that pair for good —
    future runs neither re-flag nor re-research it."""
    try:
        pair = (json.loads(change.detail or "{}")).get("pair") or []
    except Exception:  # noqa: BLE001
        pair = []
    if len(pair) != 2:
        return
    if (change.change_type == "recommendation"
            and "duplicate" in change.property_changed):
        felix_store.resolve_pair(pair[0], pair[1], f"user-{action}")
    elif change.change_type == "merge" and action == "dismiss":
        felix_store.resolve_pair(pair[0], pair[1], "user-not-duplicate")


@app.post("/api/felix/changes/{change_id}/review")
def felix_review(change_id: str, body: FelixReviewIn):
    change = felix_store.find_change(change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="No such change")
    def _supersede_siblings():
        """The same finding often appears twice across runs (a dry-run row
        plus the applied one, or a re-detected duplicate). Deciding one
        decides them all — the twins are marked Superseded, not left queued."""
        for other in felix_store.list_all_changes(review="Awaiting Review",
                                                  limit=5000):
            if (other.change_id != change_id
                    and other.record_id == change.record_id
                    and other.change_type == change.change_type
                    and other.property_changed == change.property_changed):
                felix_store.update_change(other.change_id,
                                          {"review_status": "Superseded"})

    if body.action == "approve":
        # Approve EXECUTES the stored plan when the row hasn't been applied
        # yet (dry-run plans, model proposals). The exact payload was written
        # to the snapshot at plan time — nothing is re-derived. Explicit
        # per-row human approval is its own consent, so this is not gated on
        # live_enabled (which governs autonomous writes only).
        result = {"change_id": change_id, "review_status": "Approved"}
        snap = felix_store.load_snapshot(change_id)
        try:
            _pair = (json.loads(change.detail or "{}")).get("pair") or []
        except Exception:  # noqa: BLE001
            _pair = []
        # A duplicate finding where the evidence points AT a duplicate —
        # approving it means "merge them". A researched-DISTINCT row is the
        # opposite claim, so approving that only files the pair as settled.
        is_dup_rec = (change.change_type == "recommendation"
                      and "duplicate" in change.property_changed
                      and "DISTINCT" not in (change.reason or ""))
        if snap and snap.get("kind") == "create_company":
            from src.features.felix import run as felix_runmod
            out = felix_runmod.create_company_and_link(_notion, snap, change)
            result["execution_status"] = out.get("status", "")
            if out.get("note"):
                result["note"] = out["note"]
            if out.get("status") == "Applied":
                _notion.invalidate_cache()
        elif snap and snap.get("kind") == "add_photo":
            from src.features.felix import run as felix_runmod
            out = felix_runmod.add_photo_to_page(_notion, snap, change)
            result["execution_status"] = out.get("status", "")
            if out.get("note"):
                result["note"] = out["note"]
        elif (change.execution_status in ("Proposed", "Planned (dry-run)",
                                          "Recommended")
                and snap and snap.get("planned")):
            from src.features.felix import execute as felix_execute
            updated = felix_execute.apply_change(
                _notion, change, snap["planned"],
                expect_prop=snap.get("expect_prop", ""),
                scanned_plain=snap.get("scanned_plain"),
                dry_run=False, quiet_minutes=0,
                scanned_raw=snap.get("scanned_raw"))
            if updated.execution_status == "Applied":
                _notion.invalidate_cache()
            result["execution_status"] = updated.execution_status
            if updated.execution_status == "Skipped":
                result["note"] = ("not written: " +
                                  (updated.undo_result or "the record moved on "
                                   "since the scan"))
        elif (len(_pair) == 2
              and (is_dup_rec or (change.change_type == "merge"
                                  and change.execution_status != "Applied"))):
            # Approve EXECUTES the merge: fetch fresh, keep the richer record
            # (or the planned survivor), transfer, repoint, archive.
            from src.features.felix import run as felix_runmod
            # The reviewer's choice of which copy to keep wins over Felix's.
            chosen = body.survivor_id if body.survivor_id in _pair else ""
            out = felix_runmod.merge_pair_now(
                _notion, _pair, change.database,
                source="approved in review — " + (change.source or "")[:150],
                reason=(change.reason or "")[:300],
                survivor_id=chosen or (_pair[0] if change.change_type == "merge"
                                       else ""))
            result["execution_status"] = out.get("status", "")
            if out.get("status") == "Applied":
                _notion.invalidate_cache()
                result["note"] = (f"merged: kept '{out.get('survivor')}', "
                                  f"archived '{out.get('loser')}'")
            elif out.get("note"):
                result["note"] = out["note"]
        elif (change.change_type == "recommendation"
              and "duplicate" in change.property_changed):
            result["note"] = ("noted as distinct — this pair will not be "
                              "flagged again")
        elif change.change_type in ("merge", "merge_transfer", "archive"):
            result["note"] = ("already applied" if change.execution_status
                              == "Applied" else "approve the parent merge row "
                              "to consolidate the pair")
        elif change.execution_status in ("Proposed", "Planned (dry-run)"):
            result["note"] = ("this row predates apply-on-approve and has no "
                              "stored payload — re-run Felix to regenerate it")
        felix_store.update_change(change_id, {"review_status": "Approved"})
        _supersede_siblings()
        _resolve_reviewed_pair(change, "approve")
        _felix_topup_if_low()
        return result
    if body.action == "dismiss":
        felix_store.update_change(change_id, {"review_status": "Dismissed"})
        _supersede_siblings()
        _resolve_reviewed_pair(change, "dismiss")
        _felix_topup_if_low()
        return {"change_id": change_id, "review_status": "Dismissed"}
    if body.action == "undo":
        felix_store.update_change(change_id,
                                  {"review_status": "Undo Requested"})

        def work(job: dict):
            out = felix_undo.undo_change(_notion, change_id)
            if out.get("status") == "Undone":
                _notion.invalidate_cache()
            return out

        return {"change_id": change_id, "review_status": "Undo Requested",
                "job": _job_summary(_start_job(
                    "felix-undo", f"Undo {change_id}", work))}
    raise HTTPException(status_code=400,
                        detail="action must be approve, dismiss or undo")


@app.get("/api/felix/stats")
def felix_stats():
    return felix_store.stats()


@app.get("/api/felix/status")
def felix_status():
    cfg = felix_store.load_config()
    with _JOBS_LOCK:
        running = next((_job_summary(j) for j in _JOBS.values()
                        if j["kind"] == "felix" and j["status"] == "running"),
                       None)
    return {"live": _notion.live, "live_enabled": bool(cfg.get("live_enabled")),
            "auto_run_enabled": bool(cfg.get("auto_run_enabled")),
            "auto_run_hour": cfg.get("auto_run_hour", 7),
            "running": running,
            "pending_research": felix_pending(),
            "stats": felix_store.stats()}


@app.get("/api/felix/pending")
def felix_pending():
    """What the last run could not settle from the notes, grouped so the user
    can see what a web search would actually be spent on."""
    data = felix_store.load_pending_research()
    items = data.get("items", [])
    groups: dict = {}
    for it in items:
        g = groups.setdefault(it.get("kind", "other"),
                              {"kind": it.get("kind", "other"), "count": 0,
                               "records": []})
        g["count"] += 1
        if len(g["records"]) < 12:
            g["records"].append({"name": it.get("record_name", ""),
                                 "field": it.get("field", ""),
                                 "url": it.get("record_url", ""),
                                 "detail": it.get("detail", "")})
    return {"at": data.get("at", ""), "total": len(items),
            "groups": sorted(groups.values(), key=lambda g: -g["count"])}


class FelixConfigIn(BaseModel):
    live_enabled: Optional[bool] = None
    auto_run_enabled: Optional[bool] = None
    auto_run_hour: Optional[int] = None


@app.post("/api/felix/config")
def felix_config(body: FelixConfigIn):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "auto_run_hour" in patch:
        patch["auto_run_hour"] = max(0, min(23, patch["auto_run_hour"]))
    felix_store.save_config(patch)
    return felix_store.load_config()


def _auto_felix_run():
    """One automatic clean-up run per day at the configured hour — only once
    live mode has been explicitly enabled (auto dry-runs would just spam)."""
    time.sleep(120)
    while True:
        try:
            cfg = felix_store.load_config()
            now = time.localtime()
            today = time.strftime("%Y-%m-%d", now)
            due = (cfg.get("auto_run_enabled") and cfg.get("live_enabled")
                   and now.tm_hour >= int(cfg.get("auto_run_hour", 7))
                   and cfg.get("last_auto_run_date") != today)
            if due:
                with _JOBS_LOCK:
                    busy = any(j["kind"] == "felix" and j["status"] == "running"
                               for j in _JOBS.values())
                if not busy:
                    felix_store.save_config({"last_auto_run_date": today})
                    opts = FelixRunOptions(dry_run=False)
                    client = _client()
                    _start_job("felix", "Felix clean-up (scheduled)",
                               lambda job: felix_run(
                                   job, _notion, client, opts,
                                   checkpoint=lambda: _checkpoint(job)))
        except Exception:  # noqa: BLE001 - the scheduler must never die
            pass
        time.sleep(600)


threading.Thread(target=_auto_felix_run, daemon=True).start()


# --------------------------------------------------------------------------- #
# Contact creator — business card (photo / file / paste) → a Notion contact.
# Vision extraction via the existing image path (base64 → temp file → Read),
# dedupe against live contacts/companies, schema-aware property mapping, and
# a best-effort LinkedIn lookup whose photo becomes the page icon.
# --------------------------------------------------------------------------- #

_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "title": {"type": "string", "description": "Job title / role"},
        "company": {"type": "string"},
        "website": {"type": "string"},
        "address": {"type": "string"},
        "linkedin_url": {"type": "string"},
        "notes": {"type": "string",
                  "description": "Anything else legible on the card"},
    },
    "required": ["name", "email", "phone", "title", "company", "website",
                 "address", "linkedin_url", "notes"],
    "additionalProperties": False,
}

_CARD_SYSTEM = """You read business cards. Extract ONLY what is actually printed \
on the card image — no inference, no completion of partial text. Empty string for \
anything not present. Emails and websites verbatim; keep phone numbers exactly as \
formatted on the card."""


@app.post("/api/contact-card")
async def contact_card(file: UploadFile):
    """Extract a business card image into prefilled, editable contact fields."""
    import base64

    client = _client()
    if client is None:
        raise HTTPException(status_code=503, detail="No AI backend available")
    data = await file.read()
    media = file.content_type if (file.content_type or "").startswith("image/") \
        else "image/jpeg"
    response = _run(
        client.messages.create,
        model=config.FAST_MODEL, max_tokens=700, system=_CARD_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _CARD_SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media,
                                         "data": base64.b64encode(data).decode()}},
            {"type": "text", "text": "Extract this business card."},
        ]}],
    )
    raw = next((b.text for b in response.content
                if getattr(b, "type", None) == "text"), "{}")
    card = json.loads(raw)

    # Dedupe against the live workspace.
    contacts = _notion.list_contacts()
    companies = _notion.list_companies()
    dup = match_contact(card.get("email", ""), card.get("name", ""), contacts)
    co_dup = match_company(card.get("company", ""),
                           domain_of(card.get("email", "")), companies)
    existing = None
    if dup.action in ("link_existing", "review") and dup.matches:
        m = dup.matches[0]
        rec = next((c for c in contacts if c.id == m.id), None)
        existing = {"id": m.id, "name": m.name,
                    "score": round(m.score, 2), "action": dup.action,
                    "email": getattr(rec, "email", ""),
                    "title": getattr(rec, "title", "")}

    # Editable fields, shaped by what the live Contacts DB actually has.
    schema = _notion.retrieve_database(config.NOTION_CONTACTS_DB or "")
    props = schema.get("properties") or {}
    linkedin_prop = next((n for n, p in props.items()
                          if p.get("type") == "url" and "linked" in n.lower()), "")
    phone_prop = next((n for n, p in props.items()
                       if p.get("type") == "phone_number"), "")
    editable = {
        "Name": card.get("name", ""),
        "Email": card.get("email", ""),
        "Title": card.get("title", ""),
        "Type": notion_sync.default_contact_type(card.get("email", "")),
        "Employed By": (co_dup.matches[0].name
                        if co_dup.action == "link_existing" and co_dup.matches
                        else card.get("company", "")),
    }
    if phone_prop or not _notion.live:
        editable["Phone"] = card.get("phone", "")
    if linkedin_prop or not _notion.live:
        editable["LinkedIn"] = card.get("linkedin_url", "")
    editable["Description"] = " · ".join(
        x for x in (card.get("website", ""), card.get("address", ""),
                    card.get("notes", "")) if x)
    return {"card": card, "editable": editable, "existing": existing,
            "company_known": bool(co_dup.action == "link_existing"),
            "props": {"linkedin": linkedin_prop, "phone": phone_prop},
            "live": _notion.live}


class ContactCreateIn(BaseModel):
    fields: dict
    icon_url: str = ""
    linkedin_prop: str = ""
    phone_prop: str = ""


@app.post("/api/contact-card/create")
def contact_card_create(body: ContactCreateIn):
    """Create the contact page from the reviewed fields."""
    f = {k: (v or "").strip() for k, v in body.fields.items()}
    if not f.get("Name"):
        raise HTTPException(status_code=400, detail="The contact needs a name")
    props: dict = {"Name": {"title": [{"text": {"content": f["Name"][:200]}}]}}
    if f.get("Email"):
        props["Email"] = {"email": f["Email"]}
    if f.get("Title"):
        props["Title"] = {"rich_text": [{"text": {"content": f["Title"][:500]}}]}
    if f.get("Type"):
        props["Type"] = {"select": {"name": f["Type"]}}
    if f.get("Description"):
        props["Description"] = {"rich_text": [{"text": {"content": f["Description"][:1900]}}]}
    if f.get("Phone") and body.phone_prop:
        props[body.phone_prop] = {"phone_number": f["Phone"][:100]}
    if f.get("LinkedIn") and body.linkedin_prop:
        props[body.linkedin_prop] = {"url": f["LinkedIn"][:500]}
    if f.get("Employed By"):
        try:
            ids = _ids_for_names_or_create(
                f["Employed By"], _notion.list_companies(),
                config.NOTION_COMPANIES_DB, "company")
            if ids:
                props["Employed By"] = {"relation": [{"id": i} for i in ids]}
        except Exception:  # noqa: BLE001 - the relation is best-effort
            pass
    props = _snap_to_options("contact", props)
    icon = ({"type": "external", "external": {"url": body.icon_url}}
            if body.icon_url.startswith("http") else None)
    page = _notion.create_page(config.NOTION_CONTACTS_DB or "mock-db", props,
                               icon=icon)
    _NAMES_CACHE.pop("contact", None)
    return {"url": page.get("url", ""), "id": page.get("id", ""),
            "live": _notion.live}


_LINKEDIN_SCHEMA = {
    "type": "object",
    "properties": {
        "profile_url": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low", "none"]},
        "image_url": {"type": "string",
                      "description": "Direct URL of the profile photo, if one "
                                     "could be found; empty otherwise"},
        "evidence": {"type": "string"},
    },
    "required": ["profile_url", "confidence", "image_url", "evidence"],
    "additionalProperties": False,
}

_LINKEDIN_SYSTEM = """You verify a person's LinkedIn profile using real web \
searches. Search for the person's name together with their company. Report high \
confidence ONLY when a public LinkedIn profile clearly matches BOTH the name and \
the company; a name match alone is medium at best. If you can retrieve a direct \
profile-photo URL (media.licdn.com), include it; if the page is blocked, leave \
image_url empty — do not guess. Report none if no plausible profile is found."""


class LinkedInIn(BaseModel):
    name: str
    company: str = ""


@app.post("/api/contact-card/linkedin")
def contact_card_linkedin(body: LinkedInIn):
    client = _client()
    if client is None:
        raise HTTPException(status_code=503, detail="No AI backend available")
    response = _run(
        client.messages.create,
        model=config.REASONING_MODEL, max_tokens=800, system=_LINKEDIN_SYSTEM,
        output_config={"format": {"type": "json_schema",
                                  "schema": _LINKEDIN_SCHEMA}},
        extra_allowed_tools=["WebSearch", "WebFetch"],
        messages=[{"role": "user", "content":
                   f"Find the LinkedIn profile of {body.name}"
                   + (f" at {body.company}" if body.company else "") + "."}],
    )
    raw = next((b.text for b in response.content
                if getattr(b, "type", None) == "text"), "{}")
    return json.loads(raw)


# --------------------------------------------------------------------------- #
# Mail actions via the MCP bridge — real forwards/deletes without Entra.
# --------------------------------------------------------------------------- #

_MCP_ACTION_PREAMBLE = """The claude.ai Microsoft 365 connector may still be connecting when
you start — if the outlook tools are not yet visible, use ToolSearch with the query
"outlook mail" to load them, and retry a few times over ~20 seconds. When the action has
been performed, reply with exactly DONE. If it cannot be performed, reply FAILED: <reason>.
"""


def _mcp_mail_action(instruction: str, tools: list[str]) -> None:
    """Run one write action through the user's M365 connector; raise on failure."""
    import subprocess

    cli = llm.resolve_cli_path(config.CLAUDE_CLI_PATH) or config.CLAUDE_CLI_PATH
    proc = subprocess.run(
        [cli, "-p", _MCP_ACTION_PREAMBLE + instruction,
         "--allowedTools", ",".join([*tools, "ToolSearch"])],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=240, stdin=subprocess.DEVNULL,
    )
    out = (proc.stdout or "").strip()
    if "FAILED" in out.upper() or "DONE" not in out.upper():
        raise HTTPException(status_code=502,
                            detail=f"Mail action failed: {(out or proc.stderr)[:200]}")


class ToSharedIn(BaseModel):
    message_id: str
    subject: str = ""


@app.post("/api/messages/to-shared")
def message_to_shared(body: ToSharedIn):
    """Forward a message to the Investments shared mailbox."""
    _mcp_mail_action(
        f'Forward the Outlook message with id "{body.message_id}"'
        + (f' (subject: "{body.subject}")' if body.subject else "")
        + f" to {config.SHARED_MAILBOX} using the outlook_forward_mail tool, "
          "with no added comment.",
        ["mcp__claude_ai_Microsoft_365__outlook_forward_mail"],
    )
    return {"forwarded": True, "to": config.SHARED_MAILBOX}


# --------------------------------------------------------------------------- #
# What's new
# --------------------------------------------------------------------------- #

@app.post("/api/jobs/whats-new-team")
def start_team_job():
    client = _client()
    return _job_summary(_start_job(
        "whats-new-team", "Team digest",
        lambda job: team_whats_new(client, _notion),
    ))


@app.post("/api/jobs/whats-new-inbox")
def start_inbox_job():
    client = _client()
    return _job_summary(_start_job(
        "whats-new-inbox", "Shared inbox digest",
        lambda job: inbox_whats_new(client, _graph),
    ))


@app.get("/api/whats-new/portfolio")
def whats_new_portfolio():
    return {"available": portfolio_whats_new() is not None}


# --------------------------------------------------------------------------- #
# Fund data
# --------------------------------------------------------------------------- #

@app.get("/api/fund-data")
def fund_data():
    init_db()
    conn = sqlite3.connect(str(config.DB_PATH))
    try:
        def q(sql: str) -> list[dict]:
            return pd.read_sql_query(sql, conn).to_dict(orient="records")

        facts = q("SELECT * FROM fact_table")
        manifest = q("SELECT * FROM manifest_table")
        flagged = q("SELECT * FROM flagged_table WHERE resolved = 0 ORDER BY id DESC")
        notes = q("SELECT * FROM notes_table ORDER BY id DESC LIMIT 200")
        log = q("SELECT * FROM ingestion_log ORDER BY id DESC LIMIT 100")
    finally:
        conn.close()
    last = max((m.get("processed_date") or "" for m in manifest), default=None)
    return {"facts": facts, "notes": notes, "manifest_count": len(manifest),
            "flagged": flagged, "log": log, "last_updated": last}


# --------------------------------------------------------------------------- #
# Static front-end (web/dist, when built)
# --------------------------------------------------------------------------- #

DIST = BASE / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")
    if (DIST / "mascot").exists():
        app.mount("/mascot", StaticFiles(directory=DIST / "mascot"), name="mascot")
    if (DIST / "brand").exists():
        app.mount("/brand", StaticFiles(directory=DIST / "brand"), name="brand")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        target = DIST / full_path
        if full_path and target.exists() and target.is_file():
            return FileResponse(target)
        return HTMLResponse((DIST / "index.html").read_text(encoding="utf-8"))
