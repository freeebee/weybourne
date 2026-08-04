"""Online research escalation — for findings deterministic rules and cheap
batching cannot settle.

Two jobs, both through the CLI backend with web search enabled:

* ``research_duplicate`` — an "unsure" duplicate pair (similar names, different
  employers) is researched online: are these the same real person/company?
* ``research_fund_fields`` — a fund missing Asset Class / Geographic Focus with
  no note evidence gets a web lookup; values are validated against the live
  select options in code before anything is proposed.

Research NEVER writes anything directly: a "duplicate" verdict becomes a
planned merge (still approval-gated in dry-run), field values become Proposed
changes the user approves row by row.
"""
from __future__ import annotations

import json

from src.config import LIVE_MODEL

_DUP_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["duplicate", "distinct", "unsure"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "explanation": {"type": "string",
                        "description": "What the research found, one or two "
                                       "sentences a reviewer can act on"},
        "evidence": {"type": "string",
                     "description": "The key fact(s) found online, with the "
                                    "source site named"},
    },
    "required": ["verdict", "confidence", "explanation", "evidence"],
    "additionalProperties": False,
}

_DUP_SYSTEM = """You research whether two CRM records describe the SAME real \
person or company. Use web search: look the names up together with their \
employers/context. People can share similar names and work at different firms \
(distinct); one person can appear twice with their name written differently, or \
have moved firms (duplicate). Decide from what you actually find online — \
LinkedIn, company team pages, news. If the web gives no clear answer, say \
"unsure". Name the source of your key evidence."""


def research_duplicate(client, a: dict, b: dict,
                       employer_names: dict | None = None) -> dict:
    """Web-research an unsure duplicate pair. Returns
    {verdict, confidence, explanation, evidence}."""
    emp = employer_names or {}

    def line(c, tag):
        emp_names = [emp.get(i, "") for i in c.get("relations", {}).get("Employed By", [])]
        bits = [f"{tag}) {c['name']}"]
        if c.get("email"):
            bits.append(f"email {c['email']}")
        if any(emp_names):
            bits.append("employer: " + ", ".join(n for n in emp_names if n))
        for k, v in list(c.get("plain", {}).items())[:8]:
            if v and k not in ("Name", "Email") and not isinstance(v, list):
                bits.append(f"{k}: {str(v)[:80]}")
        return "; ".join(bits)

    response = client.messages.create(
        model=LIVE_MODEL, max_tokens=900, system=_DUP_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _DUP_SCHEMA}},
        extra_allowed_tools=["WebSearch", "WebFetch"],
        messages=[{"role": "user", "content":
                   "Are these two records the same real-world entity?\n"
                   f"{line(a, 'a')}\n{line(b, 'b')}"}],
    )
    raw = next((b_.text for b_ in response.content
                if getattr(b_, "type", None) == "text"), "{}")
    return json.loads(raw)


_FIELDS_SCHEMA = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "property": {"type": "string"},
                    "value": {"type": "string",
                              "description": "MUST be one of the allowed "
                                             "options for that property"},
                    "explanation": {"type": "string"},
                    "source": {"type": "string",
                               "description": "Where online this was found"},
                },
                "required": ["property", "value", "explanation", "source"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["proposals"],
    "additionalProperties": False,
}

_FIELDS_SYSTEM = """You classify an investment fund for a family office CRM \
using web search. Look the fund and its manager up and determine the requested \
properties. Each property lists its allowed options — the value MUST be exactly \
one of them; if the web evidence does not clearly support one option, omit that \
property rather than guessing. Name where you found each answer."""


def research_fund_fields(client, card: dict, wanted: list[dict],
                         company_name: str = "") -> list[dict]:
    """Web-research missing select fields on a fund.

    ``wanted``: [{"property": ..., "options": [...]}]. Returns verified
    proposals only — a value outside the allowed options is dropped in code.
    """
    if not wanted:
        return []
    want_lines = "\n".join(
        f"- {w['property']}: one of [{', '.join(w['options'])}]" for w in wanted)
    context = f"Fund: {card['name']}"
    if company_name:
        context += f"\nManager / company: {company_name}"
    strategy = card.get("plain", {}).get("Strategy Description")
    if strategy:
        context += f"\nKnown strategy notes: {str(strategy)[:300]}"
    response = client.messages.create(
        model=LIVE_MODEL, max_tokens=900, system=_FIELDS_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _FIELDS_SCHEMA}},
        extra_allowed_tools=["WebSearch", "WebFetch"],
        messages=[{"role": "user", "content":
                   f"{context}\n\nDetermine:\n{want_lines}"}],
    )
    raw = next((b_.text for b_ in response.content
                if getattr(b_, "type", None) == "text"), "{}")
    allowed = {w["property"]: set(w["options"]) for w in wanted}
    out = []
    for pr in json.loads(raw).get("proposals", []):
        prop, value = pr.get("property", ""), pr.get("value", "").strip()
        if prop in allowed and value in allowed[prop]:
            out.append({"property": prop, "value": value,
                        "explanation": pr.get("explanation", ""),
                        "source": pr.get("source", "")})
    return out
