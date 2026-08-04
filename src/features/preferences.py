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
        "facts": {
            "type": "array",
            "description": "The five headline terms of the offer, from the "
                           "materials. Typically strategy, target size, target "
                           "net return, fees, positions/concentration. Value "
                           "'Not stated' when the materials do not say.",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "e.g. 'Target size'"},
                    "value": {"type": "string",
                              "description": "Precise, with units: '$1.6bn hard cap'"},
                },
                "required": ["label", "value"],
                "additionalProperties": False,
            },
        },
        "criteria": {
            "type": "array",
            "description": "One entry per documented preference tested, "
                           "ordered worst first: not-fit, then conditional and "
                           "unevidenced, then fit.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string",
                              "description": "The preference in a few words, e.g. "
                                             "'Control, with no cross-fund rollovers'"},
                    "preference": {"type": "string",
                                   "description": "What we like to see, from the "
                                                  "preference page, in one sentence"},
                    "rationale": {"type": "string",
                                  "description": "Why we like to see it — the "
                                                 "reasoning behind the preference"},
                    "finding": {"type": "string",
                                "description": "What this fund actually does, from "
                                               "the materials. Say plainly when the "
                                               "materials are silent."},
                    "source": {"type": "string",
                               "description": "Where the finding came from, e.g. "
                                              "'Deck p.28' or 'Intro email'. Empty "
                                              "if nothing was found."},
                    "verdict": {"type": "string",
                                "enum": ["fit", "conditional", "unevidenced", "not-fit"],
                                "description": "'unevidenced' when the materials do "
                                               "not establish it either way; "
                                               "'conditional' when it works only if "
                                               "something is negotiated"},
                    "assessment": {"type": "string",
                                   "description": "A complete sentence beginning "
                                                  "'A fit because…' / 'Not a fit "
                                                  "because…' / 'Unevidenced because…' "
                                                  "/ 'A fit only if…', readable on "
                                                  "its own"},
                },
                "required": ["title", "preference", "rationale", "finding",
                             "source", "verdict", "assessment"],
                "additionalProperties": False,
            },
        },
        "open_questions": {"type": "array", "items": {"type": "string"},
                           "description": "Questions that would most change the conclusion"},
        "not_covered": {"type": "string",
                        "description": "What the materials do not address at all, "
                                       "in one phrase"},
        "summary": {"type": "string",
                    "description": "The headline verdict paragraph: the decision "
                                   "and the two or three things driving it"},
    },
    "required": ["sleeve", "overall_fit", "facts", "criteria", "open_questions",
                 "not_covered", "summary"],
    "additionalProperties": False,
}

SCREEN_SYSTEM_PROMPT = """You are screening a prospective fund/investment against Weybourne's \
documented investment preferences. You are given the relevant preference pages verbatim. Judge \
fit honestly and specifically.

Work preference by preference. For EACH preference you test, state what we like to see, why we \
like to see it, what this fund actually does, where you found that, and the verdict. Aim for six \
to ten criteria covering the preferences that genuinely bear on this opportunity — not every \
line of the page.

Rules of the house (from the preference framework):
- Do not accept the manager's own framing at face value; evaluate the underlying engine.
- Exclude table-stakes attractions every manager would claim ("experienced team", "aligned").
- Surface the single most obvious deal-specific risk even if it maps to no stated preference.
- Findings must be concrete and tied to the preferences or to the opportunity's specifics.
- If the sleeve is unclear or key facts are missing, say so and put them in open_questions.

Evidence discipline, which matters more than any judgement here:
- A preference the materials simply do not address is "unevidenced" — NEVER "fit" and never \
"not-fit". Absence of evidence is not evidence. Say what would settle it.
- Cite the source of every finding (page, section, or the email). If you cannot cite it, the \
verdict is unevidenced.
- Every assessment is a complete sentence that stands alone, beginning "A fit because…", \
"Not a fit because…", "Unevidenced because…" or "A fit only if…".
- Figures carry their units and are quoted precisely as the materials state them.

Order criteria worst first: not-fit, then conditional and unevidenced, then fit. The summary is \
the decision and what drives it, in plain institutional English."""


def _load_preference_text(notion: NotionConnector, sleeve: str) -> dict[str, str]:
    """Load General + Learnings always, plus the relevant sleeve page.

    A page the integration cannot read (not shared with it → Notion 404) is
    skipped with a note rather than failing the whole screen; the screen then
    runs on whatever preference pages are accessible.
    """
    def safe(page_id: str, label: str) -> str:
        try:
            return notion.get_page_text(page_id)
        except Exception:  # noqa: BLE001 - typically a 404: page not shared
            return (f"[The '{label}' preference page could not be read — share it "
                    "with the Notion integration to include it in screening.]")

    text = {
        "general": safe(CHAO_PAGES["general"], "General"),
        "learnings": safe(CHAO_PAGES["learnings"], "Learnings"),
    }
    page_id = sleeve_page_id(sleeve)
    if page_id:
        text[sleeve] = safe(page_id, sleeve)
    else:
        # Sleeve unclear: load all three so the screen can reason about placement.
        for name, key in (("Private Growth", "private_growth"),
                          ("Public Growth", "public_growth"),
                          ("Diversifiers", "diversifiers")):
            text[name] = safe(CHAO_PAGES[key], name)
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
    # The flat fit/non-fit lists are derived from the criteria, so the triage
    # view and the draft-reply pass rationales keep a single source of truth.
    crit = parsed.get("criteria") or []
    if crit:
        parsed.setdefault("non_fit_points",
                          [c["assessment"] for c in crit
                           if c.get("verdict") == "not-fit"])
        parsed.setdefault("fit_points",
                          [c["assessment"] for c in crit
                           if c.get("verdict") == "fit"])
    return PreferenceScreen.model_validate(parsed)
