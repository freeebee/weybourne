"""Screen an investment opportunity against the CHAO preference pages.

Mirrors how the CHAO agent operates: always load General preferences + Learnings,
plus the strategy-sleeve preference page relevant to the opportunity, then judge
fit. The output separates genuine fits from non-fits and lists the open questions
that would move the decision — feeding both the draft-reply screen (rationale for
passing) and the meeting-prep screen.

The screening call is a Claude structured-output call; preference text is loaded
via the Notion connector (mock text offline). Tests inject a fake client and
preference text, so no network/model calls run in CI.
"""
from __future__ import annotations

import json

from src.config import CHAO_PAGES, REASONING_MODEL
from src.connectors.notion_client import NotionConnector, sleeve_page_id
from src.schemas import ExtractedEntity, PreferenceScreen

SCREEN_SCHEMA = {
    "type": "object",
    "properties": {
        "sleeve": {"type": "string",
                   "enum": ["Private Growth", "Public Growth", "Diversifiers", "Unclear"]},
        "overall_fit": {"type": "string", "enum": ["Fit", "Partial", "Non-fit", "Unclear"]},
        "fit_points": {"type": "array", "items": {"type": "string"},
                       "description": "Concrete ways this fits Weybourne preferences"},
        "non_fit_points": {"type": "array", "items": {"type": "string"},
                           "description": "Concrete ways this does NOT fit; be specific"},
        "open_questions": {"type": "array", "items": {"type": "string"},
                           "description": "Questions that would most change the conclusion"},
        "summary": {"type": "string", "description": "One-paragraph allocator-style read"},
    },
    "required": ["sleeve", "overall_fit", "fit_points", "non_fit_points", "open_questions", "summary"],
    "additionalProperties": False,
}

SCREEN_SYSTEM_PROMPT = """You are screening a prospective fund/investment against Weybourne's \
documented investment preferences. You are given the relevant preference pages verbatim. Judge \
fit honestly and specifically.

Rules of the house (from the preference framework):
- Do not accept the manager's own framing at face value; evaluate the underlying engine.
- Exclude table-stakes attractions every manager would claim ("experienced team", "aligned").
- Surface the single most obvious deal-specific risk even if it maps to no stated preference.
- Non-fits must be concrete and tied to the preferences or to the opportunity's specifics.
- If the sleeve is unclear or key facts are missing, say so and put them in open_questions.

Return fit_points and non_fit_points as short, specific bullets, plus the questions that would \
most change the conclusion."""


def _load_preference_text(notion: NotionConnector, sleeve: str) -> dict[str, str]:
    """Load General + Learnings always, plus the relevant sleeve page."""
    text = {
        "general": notion.get_page_text(CHAO_PAGES["general"]),
        "learnings": notion.get_page_text(CHAO_PAGES["learnings"]),
    }
    page_id = sleeve_page_id(sleeve)
    if page_id:
        text[sleeve] = notion.get_page_text(page_id)
    else:
        # Sleeve unclear: load all three so the screen can reason about placement.
        for name, key in (("Private Growth", "private_growth"),
                          ("Public Growth", "public_growth"),
                          ("Diversifiers", "diversifiers")):
            text[name] = notion.get_page_text(CHAO_PAGES[key])
    return text


def _format_opportunity(entity: ExtractedEntity, key_facts: list[str], extra: str = "") -> str:
    facts = "\n".join(f"- {f}" for f in key_facts) if key_facts else "- (none extracted)"
    return (
        f"Fund: {entity.fund_name or '(unknown)'}\n"
        f"Manager/company: {entity.company_name or '(unknown)'}\n"
        f"Asset class: {entity.asset_class or '(unknown)'}\n"
        f"Geography: {entity.geography or '(unknown)'}\n"
        f"Likely sleeve: {entity.sleeve}\n"
        f"Summary: {entity.summary}\n"
        f"Key facts:\n{facts}\n"
        f"{extra}"
    )


def screen_opportunity(
    client,
    entity: ExtractedEntity,
    key_facts: list[str],
    notion: NotionConnector | None = None,
    extra_context: str = "",
) -> PreferenceScreen:
    """Screen an extracted opportunity against the CHAO preference pages."""
    notion = notion or NotionConnector()
    prefs = _load_preference_text(notion, entity.sleeve)
    prefs_block = "\n\n".join(f"=== {name} ===\n{body}" for name, body in prefs.items() if body)
    user = (
        "PREFERENCE PAGES (verbatim):\n\n"
        f"{prefs_block}\n\n"
        "OPPORTUNITY UNDER EVALUATION:\n\n"
        f"{_format_opportunity(entity, key_facts, extra_context)}"
    )
    response = client.messages.create(
        model=REASONING_MODEL,
        max_tokens=2000,
        system=SCREEN_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": SCREEN_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    parsed = json.loads(raw)
    return PreferenceScreen.model_validate(parsed)
