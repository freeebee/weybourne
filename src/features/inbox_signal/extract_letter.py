"""Turn one manager letter into structured, quotable evidence.

The output feeds three views that all make claims about what a named, real
person said. That puts a hard constraint on this module: **every quote must be
text the manager actually wrote.** A summarised or tidied quote, attributed to a
real individual and displayed in quotation marks, is a fabricated statement
about a real person — the worst failure this feature can have, and one that
looks completely normal on screen.

Two defences, because the prompt alone is not enough:

1. The prompt forbids paraphrase and requires verbatim spans.
2. ``_verify_quotes`` then checks each returned quote actually occurs in the
   source body, and silently drops any that does not. A model that paraphrases
   despite instruction loses the quote rather than publishing it.

The same principle governs figures: ``reported_returns`` carries only numbers
the manager stated for a named month. Nothing is computed, inferred, or
annualised here.

Tests inject a fake client exposing ``messages.create``, as the other feature
modules do, so no model calls happen in CI.
"""
from __future__ import annotations

import json
import re
import unicodedata

from src.config import EXTRACTION_MODEL
from src.features.inbox_signal.taxonomy import STANCES, THEMES, normalise_stance, normalise_theme
from src.schemas import EmailMessage

LETTER_SCHEMA = {
    "type": "object",
    "properties": {
        "is_manager_letter": {
            "type": "boolean",
            "description": "True only if this is a fund manager (or their investor "
                           "relations) writing about their own fund: a letter, "
                           "commentary, CIO update, NAV or performance notice. False for "
                           "newsletters, custodian/administrator paperwork, portal "
                           "notifications with no commentary, and internal-only threads.",
        },
        "org": {
            "type": "string",
            "description": "The manager or firm whose VIEW this is, as they would be "
                           "listed on a portfolio — e.g. 'Albizia', 'Pangolin Asia', "
                           "'New Holland'. Never the fund administrator, the mailing "
                           "platform, or a Weybourne colleague who forwarded it: if the "
                           "message is a forward or the sender is an administrator sending "
                           "on a manager's behalf, attribute it to the manager whose letter "
                           "is quoted in the body.",
        },
        "fund": {"type": "string", "description": "The specific fund named, if any. Empty if not stated."},
        "person": {
            "type": "string",
            "description": "Who signed or wrote it, with role if given — e.g. "
                           "'Asfy, CIO', 'James Hay'. Empty if unsigned.",
        },
        "source": {
            "type": "string",
            "description": "What the document is, in the manager's own framing — e.g. "
                           "'July CIO update letter', 'August 2025 monthly newsletter'.",
        },
        "stance": {
            "type": "string",
            "enum": STANCES,
            "description": "The writer's posture toward risk in THIS letter. "
                           "constructive = adding risk / seeing opportunity; cautious = "
                           "hedging, trimming, flagging concern; negative = actively "
                           "bearish or reporting damage; neutral = reporting only, no view.",
        },
        "themes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Theme ids this letter engages with. Prefer these known ids: "
                           + ", ".join(f"{k} ({v})" for k, v in THEMES.items())
                           + ". If the letter's real subject is genuinely not in that list, "
                             "coin a short lowercase-hyphenated id rather than forcing a "
                             "poor fit.",
        },
        "quotes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {
                        "type": "string",
                        "description": "A VERBATIM span copied character-for-character from "
                                       "the letter body. One to three sentences. Never "
                                       "paraphrased, never stitched from separate places, "
                                       "never tidied. If you cannot copy it exactly, omit it.",
                    },
                    "context": {
                        "type": "string",
                        "description": "One short sentence of your own explaining what the "
                                       "quote is about. This is the only field where you "
                                       "write in your own words.",
                    },
                    "themes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The theme ids THIS PASSAGE is about — a subset of the "
                                       "letter's themes, often just one, and empty when the "
                                       "passage is about something the theme list does not "
                                       "cover. Not the letter's themes copied down: a letter "
                                       "may range across AI, semiconductors and the Gulf while "
                                       "a given quote is about one company's guidance.",
                    },
                },
                "required": ["quote", "context", "themes"],
                "additionalProperties": False,
            },
            "description": "The passages that carry the manager's actual view. Two to five "
                           "for a substantive letter; an empty list for a bare NAV notice "
                           "with no commentary.",
        },
        "reported_returns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "The month the figure is FOR, as YYYY-MM"},
                    "pct": {"type": "number", "description": "Return in percent: 7.4 means +7.4%, -3.1 means -3.1%"},
                    "fund": {"type": "string", "description": "Which fund, if the letter covers several"},
                    "basis": {"type": "string", "description": "e.g. 'net', 'gross', 'estimate', 'MTD'. Empty if unstated."},
                },
                "required": ["month", "pct", "fund", "basis"],
                "additionalProperties": False,
            },
            "description": "Only figures the manager explicitly states for a specific month. "
                           "Do NOT compute, annualise, convert, or infer. A year-to-date or "
                           "since-inception number is NOT a monthly return — leave it out.",
        },
        "disclosed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "value": {"type": "string", "description": "As stated, e.g. '286%', '4x'"},
                    "label": {"type": "string", "description": "What it measures, e.g. 'Gross exposure, May 2026'"},
                    "note": {"type": "string"},
                },
                "required": ["value", "label", "note"],
                "additionalProperties": False,
            },
            "description": "Exposure, leverage or positioning figures the manager discloses.",
        },
    },
    "required": ["is_manager_letter", "org", "fund", "person", "source", "stance",
                 "themes", "quotes", "reported_returns", "disclosed"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You read fund manager correspondence for a family office and extract what the \
manager actually said, so it can be quoted back with attribution.

The output is displayed as quotations attributed to a named, real person. Therefore:

- Every string in `quotes[].quote` MUST be copied verbatim from the letter body, \
character for character. Do not paraphrase, summarise, tidy grammar, fix typos, merge \
sentences from different paragraphs, or translate. If you cannot reproduce a passage \
exactly, leave it out. An omitted quote costs nothing; an invented one puts words in a \
real person's mouth.
- Quote the passages carrying the manager's VIEW — what they think, what they changed, \
what worries them — not boilerplate, disclaimers, or contact details.
- `reported_returns` takes only figures the manager states for a specific named month. \
Never compute or infer one. Year-to-date, since-inception and annualised figures are not \
monthly returns.
- Leave any field empty rather than guessing. Absence is a valid, useful answer.
- Much of this mail arrives indirectly: forwarded by a colleague, or sent by a fund \
administrator on the manager's behalf. Attribute `org` and `person` to whoever actually \
holds the view being expressed — the manager quoted in the body — not to the forwarder, \
the administrator, or the mailing platform. A quote is still verbatim if it sits inside a \
forwarded block; quote it from there.

Set `is_manager_letter` false for newsletters, spam-quarantine digests, custodian and \
administrator paperwork, portal "a document has been posted" notices with no commentary, \
and internal-only threads. When false, the other fields may be empty — nothing further is \
read from them."""


# Forwarded threads in this mailbox reach 190k characters, nearly all of it
# quoted history repeated at each hop. Outlook puts the newest message at the
# top of the body, so the head is the part carrying the current view; the tail
# is older mail that has usually been extracted already under its own id.
# Capped rather than chunked deliberately — splitting a letter across calls
# risks a quote assembled from two halves, which would defeat the verbatim
# check by being individually plausible.
MAX_BODY_CHARS = 40_000


def _letter_block(email: EmailMessage) -> str:
    body = email.body or email.body_preview or ""
    truncated = len(body) > MAX_BODY_CHARS
    if truncated:
        body = body[:MAX_BODY_CHARS]
    attachments = ", ".join(a.name for a in email.attachments) or "none"
    tail = ("\n\n[Body truncated here. Older quoted history in this thread has been cut; "
            "extract only from what is above.]" if truncated else "")
    return (
        f"From: {email.sender_name} <{email.sender_email}>\n"
        f"Subject: {email.subject}\n"
        f"Received: {email.received}\n"
        f"Attachments: {attachments}\n\n"
        f"--- LETTER BODY ---\n{body}{tail}"
    )


def _normalise_for_match(text: str) -> str:
    """Fold the differences that survive an honest copy-paste.

    Mail bodies arrive with smart quotes, non-breaking spaces and hard-wrapped
    lines; a model reproducing a passage faithfully may still normalise those.
    Folding them keeps the verbatim check strict about *words* without failing
    on typography — which would push us toward dropping good quotes and, worse,
    toward relaxing the check itself.
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = (text.replace("‘", "'").replace("’", "'")
                .replace("“", '"').replace("”", '"')
                .replace("–", "-").replace("—", "-")
                .replace(" ", " "))
    return re.sub(r"\s+", " ", text).strip().lower()


def _verify_quotes(quotes: list[dict], body: str) -> tuple[list[dict], int]:
    """Keep only quotes that genuinely occur in the body. Returns (kept, dropped).

    This is the backstop that makes the feature trustworthy rather than merely
    well-prompted. A dropped quote is invisible in the product; a fabricated one
    would be indistinguishable from a real one.
    """
    haystack = _normalise_for_match(body)
    kept, dropped = [], 0
    for q in quotes:
        text = (q.get("quote") or "").strip().strip('"').strip("“”")
        if not text:
            dropped += 1
            continue
        if _normalise_for_match(text) in haystack:
            themes = []
            for t in q.get("themes") or []:
                norm = normalise_theme(t)
                if norm and norm not in themes:
                    themes.append(norm)
            kept.append({"quote": text, "context": (q.get("context") or "").strip(),
                         "themes": themes})
        else:
            dropped += 1
    return kept, dropped


def extract_letter(client, email: EmailMessage) -> dict:
    """Extract one letter. Returns a dict; ``is_manager_letter`` gates the rest.

    Never raises on model trouble — a refusal or unparseable response comes back
    as not-a-letter with a reason, so the sweep records it and moves on instead
    of failing the whole run over one awkward email.
    """
    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": LETTER_SCHEMA}},
        messages=[{"role": "user", "content": _letter_block(email)}],
    )
    if getattr(response, "stop_reason", None) == "refusal":
        return {"is_manager_letter": False, "reason": "model refused"}

    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"is_manager_letter": False, "reason": "unparseable extractor output"}

    if not parsed.get("is_manager_letter"):
        return {"is_manager_letter": False, "reason": "not manager correspondence"}

    body = email.body or email.body_preview or ""
    quotes, dropped = _verify_quotes(parsed.get("quotes") or [], body)

    themes = []
    for t in parsed.get("themes") or []:
        norm = normalise_theme(t)
        if norm and norm not in themes:
            themes.append(norm)

    return {
        "is_manager_letter": True,
        "message_id": email.id,
        "org": (parsed.get("org") or email.sender_name or "").strip(),
        "fund": (parsed.get("fund") or "").strip(),
        "person": (parsed.get("person") or "").strip(),
        "source": (parsed.get("source") or email.subject or "").strip(),
        "subject": email.subject,
        "date": (email.received or "")[:10],
        "stance": normalise_stance(parsed.get("stance")),
        "themes": themes,
        "quotes": quotes,
        "quotes_dropped": dropped,
        "reported_returns": _clean_returns(parsed.get("reported_returns") or []),
        "disclosed": [
            {"value": str(d.get("value") or "").strip(),
             "label": (d.get("label") or "").strip(),
             "note": (d.get("note") or "").strip()}
            for d in (parsed.get("disclosed") or [])
            if (d.get("value") or "").strip()
        ],
        "web_link": email.web_link or "",
    }


_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _clean_returns(rows: list[dict]) -> list[dict]:
    """Drop anything not a real percentage against a real ``YYYY-MM``.

    A malformed month would silently misalign a manager against the factor
    series — correlating their July against a factor's March — which produces a
    number that is wrong rather than absent. Absent is recoverable.
    """
    out = []
    for r in rows:
        month = str(r.get("month") or "").strip()
        if not _MONTH_RE.match(month):
            continue
        try:
            pct = float(r.get("pct"))
        except (TypeError, ValueError):
            continue
        out.append({
            "month": month,
            "pct": pct,
            "fund": (r.get("fund") or "").strip(),
            "basis": (r.get("basis") or "").strip(),
        })
    return out
