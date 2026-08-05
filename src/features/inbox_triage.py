"""Triage Outlook inbox mail for investment relevance and extract the entity.

Given an email, ask Claude (structured output) whether it looks like it relates
to an investment opportunity the Financial Investments team would care about,
and, if so, extract the fund / company / contact it concerns plus the likely
strategy sleeve. The shape is enforced by a JSON schema and re-validated with
pydantic, mirroring ``src/extraction.py``.

Tests inject a fake client (an object exposing ``messages.create``) so no API
calls happen in CI.
"""
from __future__ import annotations

import json

from src.config import FAST_MODEL
from src.schemas import EmailMessage, ExtractedEntity, InvestmentTriage

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_investment": {
            "type": "boolean",
            "description": "True if the email plausibly relates to a fund/investment "
            "opportunity, manager update, or co-investment the FI team would track.",
        },
        "confidence": {"type": "number", "description": "0..1 confidence in is_investment"},
        "category": {
            "type": "string",
            "description": "Short label, e.g. 'New fund intro', 'LP/manager update', "
            "'Co-investment', 'Event/marketing', 'Internal/admin', 'Not relevant'",
        },
        "rationale": {"type": "string", "description": "One or two sentences of reasoning"},
        "key_facts": {"type": "array", "items": {"type": "string"},
                      "description": "Salient facts (size, fees, returns, terms, geography)"},
        "entity": {
            "type": "object",
            "properties": {
                "fund_name": {"type": "string"},
                "company_name": {"type": "string", "description": "The management company"},
                "company_domain": {"type": "string", "description": "Company web domain if inferable"},
                "contact_name": {"type": "string"},
                "contact_email": {"type": "string"},
                "contact_title": {"type": "string"},
                "asset_class": {"type": "string"},
                "geography": {"type": "string"},
                "sleeve": {
                    "type": "string",
                    "enum": ["Private Growth", "Public Growth", "Diversifiers", "Unclear"],
                    "description": "Which Weybourne strategy sleeve this most likely belongs to",
                },
                "summary": {"type": "string"},
                "strategy_description": {
                    "type": "string",
                    "description": "The strategy in the manager's own terms — what it "
                                   "invests in, stage, approach. Fuller than summary.",
                },
                "company_description": {
                    "type": "string",
                    "description": "About the MANAGEMENT COMPANY itself: who they are, "
                                   "where based, who runs it, what they do as a firm. "
                                   "Never about one specific fund — a manager will have "
                                   "many funds. E.g. 'Sydney-based real assets manager "
                                   "founded and run by Allan Fife.'",
                },
                "vintage": {"type": "string", "description": "Fund vintage year if stated, e.g. '2026'"},
                "target_size": {"type": "string", "description": "Target fund size if stated, e.g. '$500m'"},
                "company_city": {"type": "string", "description": "Management company HQ city if stated or inferable"},
                "company_country": {"type": "string", "description": "Management company HQ country if stated or inferable"},
            },
            "required": [
                "fund_name", "company_name", "company_domain", "contact_name",
                "contact_email", "contact_title", "asset_class", "geography",
                "sleeve", "summary", "strategy_description", "company_description",
                "vintage", "target_size", "company_city", "company_country",
            ],
            "additionalProperties": False,
        },
    },
    "required": ["is_investment", "confidence", "category", "rationale", "key_facts", "entity"],
    "additionalProperties": False,
}

TRIAGE_SYSTEM_PROMPT = """You triage the inbox of a senior investment manager at Weybourne, a \
family office that invests in funds across private and public markets (sleeves: Private Growth, \
Public Growth, Diversifiers).

Flag an email as an investment if it plausibly concerns a fund manager, a fund opportunity, a \
co-investment, a manager/LP update, or diligence material the Financial Investments team would \
track. Do NOT flag pure internal/admin chatter, personal email, generic event marketing with no \
specific opportunity, or vendor spam.

When it is an investment, extract as much as the email supports: the fund (name, vintage, \
target size, strategy in the manager's own terms), the management company (name, email domain, \
HQ city and country if stated or clearly inferable, and a firm-level description — who they \
are and what they do as a manager, distinct from any one fund), the primary contact (name, \
email, title), the asset class and geography, and the most likely strategy sleeve. Prefer the sender's own \
email domain for company_domain. Leave a field as an empty string if it is not present — never \
guess an email address or a figure."""


def _default_entity_from_email(email: EmailMessage) -> ExtractedEntity:
    """Cheap heuristic entity used as a fallback / seed (no model call)."""
    domain = email.sender_email.split("@", 1)[1].lower() if "@" in email.sender_email else ""
    return ExtractedEntity(
        contact_name=email.sender_name,
        contact_email=email.sender_email,
        company_domain=domain,
        summary=email.subject,
    )


def _email_block(email: EmailMessage) -> str:
    return (
        f"From: {email.sender_name} <{email.sender_email}>\n"
        f"Subject: {email.subject}\n"
        f"Received: {email.received}\n"
        f"Has attachments: {email.has_attachments}\n\n"
        f"{email.body or email.body_preview}"
    )


def _backfill_from_sender(triage: InvestmentTriage, email: EmailMessage) -> InvestmentTriage:
    """Backfill from the sender for EVERY email, relevant or not — even a
    personal catch-up should still be checkable against the Notion contacts
    and answerable with a drafted reply."""
    if not triage.entity.contact_name and email.sender_name:
        triage.entity.contact_name = email.sender_name
    if not triage.entity.contact_email and email.sender_email:
        triage.entity.contact_email = email.sender_email
    if not triage.entity.company_domain and "@" in email.sender_email:
        triage.entity.company_domain = email.sender_email.split("@", 1)[1].lower()
    # NOTE: never backfill summary with the subject line — it leaks into Notion
    # Description fields and reads as nonsense. Blank is better than wrong.
    return triage


def triage_email(client, email: EmailMessage) -> InvestmentTriage:
    """Classify + extract for a single email. Returns a validated InvestmentTriage."""
    response = client.messages.create(
        model=FAST_MODEL,
        max_tokens=1500,
        system=TRIAGE_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": TRIAGE_SCHEMA}},
        messages=[{"role": "user", "content": _email_block(email)}],
    )
    if getattr(response, "stop_reason", None) == "refusal":
        return InvestmentTriage(message_id=email.id, category="refused",
                                rationale="model refused to classify")

    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return InvestmentTriage(message_id=email.id, category="parse_error",
                                rationale="could not parse classifier output",
                                entity=_default_entity_from_email(email))
    triage = InvestmentTriage.model_validate({**parsed, "message_id": email.id})
    return _backfill_from_sender(triage, email)


# --------------------------------------------------------------------------- #
# Batched classification — the bulk "Triage All" job's own lever, not a win
# for a single ad-hoc /api/triage call (there is nothing to batch it with).
#
# Every fresh CLI spawn pays ~5-6s of process bootstrap that has nothing to
# do with the prompt (measured directly — see LIVE_PERSISTENT_SESSIONS in
# src/config.py for the same finding applied to the live meeting). Batching
# several emails into ONE call cuts that tax by roughly the batch size for
# the bulk job, without any of the persistent-session complexity: this is
# still a single one-shot call, thrown away right after, with no memory
# carried into the NEXT batch.
#
# The risk it does carry is different in kind, not degree: within one call,
# could the model attribute email A's fact to email B? Guarded against by a
# simple integer id per email that the model must echo back exactly once —
# see triage_email_batch's id round-trip check below. A batch that fails
# that check (or fails to parse at all) raises, and the caller
# (api/main.py's triage job) falls back to triage_email one at a time for
# just that batch, so a malformed batch degrades to today's behaviour for
# those few emails rather than silently misattributing or losing results.
# --------------------------------------------------------------------------- #

TRIAGE_BATCH_SIZE = 5

_BATCH_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer",
               "description": "The EMAIL id this result is for, from its \"=== EMAIL <id> "
                              "===\" header — echoed back exactly, not renumbered."},
        **TRIAGE_SCHEMA["properties"],
    },
    "required": ["id", *TRIAGE_SCHEMA["required"]],
    "additionalProperties": False,
}

BATCH_TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {"type": "array", "items": _BATCH_ITEM_SCHEMA},
    },
    "required": ["results"],
    "additionalProperties": False,
}

BATCH_TRIAGE_SYSTEM_SUFFIX = """

You will be given several emails at once, each headed "=== EMAIL <id> ===". Classify EACH \
one independently on its own merits — never let one email's content, sender or figures \
influence another's classification or extracted entity. Return exactly one result per email \
in the "results" array, each carrying the exact integer "id" from its header. Every id given \
must appear exactly once — no id skipped, none invented, none repeated."""


def triage_email_batch(client, emails: list[EmailMessage]) -> dict[str, InvestmentTriage]:
    """Classify + extract for several emails in ONE call. Returns a dict keyed
    by email.id. Raises ValueError if the model's ids don't exactly match
    what was sent — the caller is expected to catch this and fall back to
    triage_email one at a time for this batch."""
    user = "\n\n".join(f"=== EMAIL {i} ===\n{_email_block(e)}" for i, e in enumerate(emails))
    response = client.messages.create(
        model=FAST_MODEL,
        max_tokens=1500 * len(emails),
        system=TRIAGE_SYSTEM_PROMPT + BATCH_TRIAGE_SYSTEM_SUFFIX,
        output_config={"format": {"type": "json_schema", "schema": BATCH_TRIAGE_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    results = json.loads(raw).get("results", [])

    expected_ids = set(range(len(emails)))
    seen_ids = [r.get("id") for r in results]
    if set(seen_ids) != expected_ids or len(seen_ids) != len(expected_ids):
        raise ValueError(
            f"batch triage id mismatch: expected {sorted(expected_ids)}, got {seen_ids}")

    by_id = {r["id"]: r for r in results}
    out: dict[str, InvestmentTriage] = {}
    for i, email in enumerate(emails):
        item = dict(by_id[i])
        item.pop("id", None)
        triage = InvestmentTriage.model_validate({**item, "message_id": email.id})
        out[email.id] = _backfill_from_sender(triage, email)
    return out
