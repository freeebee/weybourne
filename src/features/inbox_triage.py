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

from src.config import REASONING_MODEL
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
            },
            "required": [
                "fund_name", "company_name", "company_domain", "contact_name",
                "contact_email", "contact_title", "asset_class", "geography",
                "sleeve", "summary",
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

When it is an investment, extract the fund, the management company (and its email domain if you \
can infer it from the sender address), the primary contact, the asset class and geography, and \
the most likely strategy sleeve. Prefer the sender's own email domain for company_domain. Leave \
a field as an empty string if it is not present — never guess an email address."""


def _default_entity_from_email(email: EmailMessage) -> ExtractedEntity:
    """Cheap heuristic entity used as a fallback / seed (no model call)."""
    domain = email.sender_email.split("@", 1)[1].lower() if "@" in email.sender_email else ""
    return ExtractedEntity(
        contact_name=email.sender_name,
        contact_email=email.sender_email,
        company_domain=domain,
        summary=email.subject,
    )


def triage_email(client, email: EmailMessage) -> InvestmentTriage:
    """Classify + extract for a single email. Returns a validated InvestmentTriage."""
    content = (
        f"From: {email.sender_name} <{email.sender_email}>\n"
        f"Subject: {email.subject}\n"
        f"Received: {email.received}\n"
        f"Has attachments: {email.has_attachments}\n\n"
        f"{email.body or email.body_preview}"
    )
    response = client.messages.create(
        model=REASONING_MODEL,
        max_tokens=1500,
        system=TRIAGE_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": TRIAGE_SCHEMA}},
        messages=[{"role": "user", "content": content}],
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
    # Backfill contact email/domain from the sender when the model left them blank.
    if triage.is_investment:
        if not triage.entity.contact_email and email.sender_email:
            triage.entity.contact_email = email.sender_email
        if not triage.entity.company_domain and "@" in email.sender_email:
            triage.entity.company_domain = email.sender_email.split("@", 1)[1].lower()
    return triage
