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

import pandas as pd
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src import config, llm
from src.connectors.graph import CALENDAR_SNAPSHOT, INBOX_SNAPSHOT, GraphConnector
from src.connectors.notion_client import NotionConnector
from src.db import init_db
from src.features import notion_sync
from src.features.dedupe import dedupe_entity
from src.features.draft_reply import generate_draft_options
from src.features.inbox_triage import triage_email
from src.features.meeting_prep import build_context, counterparty_from_event
from src.features.preferences import screen_opportunity
from src.features.stt import transcribe_wav
from src.features.transcription import (
    TranscriptBuffer,
    draft_meeting_note,
    note_to_markdown,
    read_transcript_batch,
    sharpen_question,
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
        decisions = dedupe_entity(
            result.entity, _notion.list_contacts(),
            _notion.list_companies(), _notion.list_funds(),
        )
        proposals = notion_sync.plan_creations(result.entity, decisions,
                                               comments=result.rationale)
        out["dedupe"] = {
            k: {"action": d.recommended_action, "name": d.name,
                "match": d.best_match.matched_name if d.best_match else None,
                "match_id": d.best_match.matched_id if d.best_match else None,
                "score": d.best_match.score if d.best_match else None,
                "reason": d.best_match.reason if d.best_match else None}
            for k, d in decisions.items()
        }
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


@app.post("/api/notion/apply")
def notion_apply(body: ApplyIn):
    props = []
    for p in body.proposals:
        raw = dict(p["raw_properties"])
        for prop_name, value in (body.edits.get(p["kind"]) or {}).items():
            if prop_name in raw:
                raw[prop_name] = notion_sync.patch_property(raw[prop_name], value)
        props.append(notion_sync.CreationProposal(
            kind=p["kind"], db_id=p.get("db_id"), title=p["title"],
            properties=raw, needs_review=p.get("needs_review", False),
            review_reason=p.get("review_reason", ""),
        ))
    res = notion_sync.apply_plan(props, _notion, approved_kinds=set(body.approved_kinds))
    return {"created": res.created, "skipped": res.skipped, "errors": res.errors,
            "live": _notion.live}


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


@app.get("/api/questions")
def get_questions(entity: str = ""):
    p = _questions_path(entity)
    if not p.exists():
        return {"entity": entity, "questions": []}
    return json.loads(p.read_text(encoding="utf-8"))


class QuestionsIn(BaseModel):
    entity: str
    questions: list[dict]   # [{q, src}]


@app.post("/api/questions")
def save_questions(body: QuestionsIn):
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    _questions_path(body.entity).write_text(
        json.dumps({"entity": body.entity, "questions": body.questions}, indent=1),
        encoding="utf-8")
    return {"saved": len(body.questions)}


class SaveMeetingNoteIn(BaseModel):
    title: str
    note_type: str = "GP Meeting"
    markdown: str = ""
    overall_impression: str = ""
    who: str = ""
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

    attendee_ids: list[str] = []
    attendee_names: list[str] = []
    try:
        contacts = _notion.list_contacts()
        owner_email = (config.MS_USER or "").strip().lower()
        owner_name = owner_email.split("@", 1)[0].replace(".", " ")
        for c in (_find_contact(contacts, "", body.who),
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
                "Companies": "",
                "Fund": "",
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
            attendee_ids = _ids_for_names(e["Attendees"], _notion.list_contacts())
        except Exception:  # noqa: BLE001
            pass
    company_ids: list[str] = []
    if e.get("Companies"):
        try:
            company_ids = _ids_for_names(e["Companies"], _notion.list_companies())
        except Exception:  # noqa: BLE001
            pass
    fund_ids: list[str] = []
    if e.get("Fund"):
        try:
            fund_ids = _ids_for_names(e["Fund"], _notion.list_funds())
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
    return {"url": page.get("url", ""), "id": page.get("id", ""),
            "live": _notion.live}


class ScreenIn(BaseModel):
    entity: dict
    key_facts: list[str] = []


@app.post("/api/screen")
def screen(body: ScreenIn):
    entity = ExtractedEntity.model_validate(body.entity)
    result: PreferenceScreen = _run(screen_opportunity, _client(), entity,
                                    body.key_facts, _notion)
    return result.model_dump()


class DraftIn(BaseModel):
    message: dict
    entity: dict
    screen: dict | None = None
    dedupe: dict | None = None
    offer_slots: bool = True


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
            slots = _graph.find_free_slots(max_slots=4)
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
    result = _graph.create_reply_draft(body.message_id, body.body)
    return {"result": result, "live": _graph.live}


class DeleteIn(BaseModel):
    message_id: str


@app.post("/api/messages/delete")
def delete_message(body: DeleteIn):
    """Soft delete: moves to Deleted Items, recoverable from Outlook."""
    result = _graph.delete_message(body.message_id)
    return {"result": result, "live": _graph.live}


# --------------------------------------------------------------------------- #
# Meeting prep
# --------------------------------------------------------------------------- #

@app.get("/api/calendar")
def calendar(days: int = 21):
    events = _graph.upcoming_events(days=days)
    out = []
    for e in events:
        name, email = counterparty_from_event(e)
        out.append({**e.model_dump(), "counterparty_name": name,
                    "counterparty_email": email})
    return {"events": out}


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
        company_name=body.company, event=event, research=lambda q: "",
    )
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
             "outlook-refresh": 480}


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
            research=lambda q: "",
        )
        notion_note = "live Notion" if _notion.live else "sample data — not your live Notion"
        deck_note = (f"deck read ({len(ctx.document_text):,} chars)"
                     if ctx.document_text else "no deck attached")
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
            return screen_opportunity(client, entity, [], _notion).model_dump()

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
async def stt(file: UploadFile):
    audio = await file.read()
    try:
        text = transcribe_wav(audio)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
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

_REFRESH_PARTS = {
    "inbox": (_MCP_PREAMBLE
              + "Fetch my top-level Outlook Inbox: the 20 most recent messages from "
                "the last 7 days. JSON array shape:\n" + _EMAIL_SHAPE),
    "calendar": (_MCP_PREAMBLE
                 + "Fetch my Outlook calendar events for the next 21 days. JSON array "
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
                 "--allowedTools", _M365_READONLY_TOOLS + ",ToolSearch"],
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
                rows = fetch(prompt)
                if not rows:
                    # Connector attaches asynchronously — one retry on empty.
                    job["stages"].append({"label": f"{part} empty — retrying once",
                                          "detail": "connector may have been slow to attach"})
                    rows = fetch(prompt)
                target = data_dir / _SNAPSHOT_FILES[part]
                if rows or not target.exists():
                    target.write_text(json.dumps(rows, indent=1), encoding="utf-8")
                    counts[part] = len(rows)
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
                              "detail": "full message bodies via your Microsoft 365 connector"})
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(fetch_part, part, prompt)
                       for part, prompt in _REFRESH_PARTS.items()]
            for f in futures:
                f.result()
        job["stages"].append({"label": "Done", "detail": ""})
        return counts

    return _job_summary(_start_job("outlook-refresh", "Outlook refresh", work))


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
