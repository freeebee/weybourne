"""Generate selectable draft email replies for a triaged opportunity.

The user picks from a few options rather than getting one take-it-or-leave-it
draft. Options fall into two families:

* **Pass** — several rationales for declining, each grounded in the specific
  non-fits the CHAO preference screen surfaced (not generic brush-offs), so the
  user can click through to the reasoning they actually want to give.
* **Offer a meeting** — proposes concrete times drawn from genuinely free slots
  in the Outlook calendar.

Plus a "request more information" option for when the screen was inconclusive.

Nothing is sent. Drafts are created in Outlook for review
(``GraphConnector.create_reply_draft``), or simply displayed.
"""
from __future__ import annotations

import json

from src.config import REASONING_MODEL
from src.schemas import (
    DraftReplyOption,
    EmailMessage,
    ExtractedEntity,
    PreferenceScreen,
    TimeSlot,
)

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "options": {
            "type": "array",
            "description": "Between 3 and 5 alternative replies the user can choose from",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "stable snake_case id"},
                    "label": {
                        "type": "string",
                        "description": "Short button label, e.g. 'Pass — strategy fit' (max ~40 chars)",
                    },
                    "intent": {"type": "string", "enum": ["pass", "meeting", "info", "hold"]},
                    "subject": {"type": "string"},
                    "body": {"type": "string", "description": "Full email body, ready to send"},
                },
                "required": ["key", "label", "intent", "subject", "body"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["options"],
    "additionalProperties": False,
}

DRAFT_SYSTEM_PROMPT = """You draft replies on behalf of a senior investment manager at \
Weybourne, a family office investing in funds across private and public markets.

House style: direct, efficient, to the point, courteous and professional. British English. \
No effusive praise, no filler, no hard sell. Short paragraphs. Sign off as the user (leave \
the signature as just their first name).

Produce a set of ALTERNATIVE replies the user can choose between — not a sequence. Include:
- Two or three distinct PASS options, each giving a DIFFERENT genuine rationale drawn from \
the non-fit points supplied. Be specific about the reason (strategy/sleeve fit, stage, \
liquidity, size, timing//capacity, fees) without being unkind or over-explaining. Never \
invent a reason that is not supported by the screen. Keep the door open where appropriate.
- One MEETING option if free calendar slots are supplied: offer the specific times given, \
verbatim, as options.
- One INFO option requesting the specific missing information named in the open questions.

Never commit to an investment, never quote internal targets, thresholds or portfolio data, \
and never disclose the internal preference framework or that the email was screened \
automatically."""


def _fallback_options(
    entity: ExtractedEntity, screen: PreferenceScreen, slots: list[TimeSlot]
) -> list[DraftReplyOption]:
    """Deterministic drafts used when no model client is available.

    Keeps the feature usable (and testable) without an API key.
    """
    who = entity.contact_name.split()[0] if entity.contact_name else "there"
    fund = entity.fund_name or entity.company_name or "the fund"
    reason = screen.non_fit_points[0] if screen.non_fit_points else "it is not a fit for our current focus"
    options = [
        DraftReplyOption(
            key="pass_fit",
            label="Pass — fit",
            intent="pass",
            subject=f"RE: {fund}",
            body=(
                f"Hi {who},\n\nThank you for thinking of us, and for the detail on {fund}.\n\n"
                f"Having looked at it, we are going to pass on this occasion — {reason}.\n\n"
                "Do keep us on your distribution list; we would be glad to look again as things "
                "develop.\n\nBest,\nJinghan"
            ),
        ),
        DraftReplyOption(
            key="pass_timing",
            label="Pass — timing",
            intent="pass",
            subject=f"RE: {fund}",
            body=(
                f"Hi {who},\n\nThank you for sending this through.\n\nThe strategy is interesting, "
                "but the timing does not work for us for this vintage. We will pass for now.\n\n"
                "Please do come back to us on the next one.\n\nBest,\nJinghan"
            ),
        ),
        DraftReplyOption(
            key="request_info",
            label="Request more info",
            intent="info",
            subject=f"RE: {fund}",
            body=(
                f"Hi {who},\n\nThank you for the introduction to {fund}.\n\nBefore we take a view, "
                "could you send through:\n"
                + "\n".join(f"- {q}" for q in (screen.open_questions[:4] or ["the track record and terms"]))
                + "\n\nBest,\nJinghan"
            ),
        ),
    ]
    if slots:
        offered = "\n".join(f"- {s.label()}" for s in slots[:3])
        options.append(
            DraftReplyOption(
                key="offer_meeting",
                label="Offer a meeting",
                intent="meeting",
                subject=f"RE: {fund}",
                body=(
                    f"Hi {who},\n\nThank you for the note on {fund} — happy to find time for an "
                    f"introductory call.\n\nAny of the following work at our end:\n{offered}\n\n"
                    "If none of those suit, send over a few times that do.\n\nBest,\nJinghan"
                ),
            )
        )
    return options


def generate_draft_options(
    client,
    email: EmailMessage,
    entity: ExtractedEntity,
    screen: PreferenceScreen,
    slots: list[TimeSlot] | None = None,
) -> list[DraftReplyOption]:
    """Produce the selectable reply options for one opportunity.

    Falls back to deterministic drafts when ``client`` is None.
    """
    slots = slots or []
    if client is None:
        return _fallback_options(entity, screen, slots)

    slot_block = (
        "\n".join(f"- {s.label()}" for s in slots[:4])
        if slots
        else "(no free slots supplied — do not offer specific times)"
    )
    user = (
        f"ORIGINAL EMAIL\nFrom: {entity.contact_name} <{entity.contact_email}>\n"
        f"Subject: {email.subject}\n\n{email.body or email.body_preview}\n\n"
        f"OPPORTUNITY\nFund: {entity.fund_name}\nManager: {entity.company_name}\n"
        f"Asset class: {entity.asset_class}\nSleeve: {screen.sleeve}\n\n"
        f"PREFERENCE SCREEN\nOverall fit: {screen.overall_fit}\n"
        f"Fits:\n" + "\n".join(f"- {p}" for p in screen.fit_points) + "\n"
        f"NON-FITS (use these as the pass rationales):\n"
        + "\n".join(f"- {p}" for p in screen.non_fit_points)
        + "\nOpen questions:\n"
        + "\n".join(f"- {q}" for q in screen.open_questions)
        + f"\n\nFREE CALENDAR SLOTS (offer these verbatim if proposing a meeting):\n{slot_block}"
    )
    response = client.messages.create(
        model=REASONING_MODEL,
        max_tokens=3000,
        system=DRAFT_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": DRAFT_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    parsed = json.loads(raw)
    return [DraftReplyOption.model_validate(o) for o in parsed.get("options", [])]
