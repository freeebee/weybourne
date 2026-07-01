"""Structured extraction: markdown -> financial metrics + narrative notes.

Uses Claude's structured outputs (a JSON schema enforced via output_config.format)
to guarantee shape, then re-validates with pydantic for business rules
(period format, non-blank fields) that the JSON schema alone can't express.
Anything that fails pydantic validation is returned for the caller to flag,
never silently dropped.
"""
import json
from dataclasses import dataclass, field

import anthropic
from pydantic import ValidationError

from src.config import EXTRACTION_MODEL, MAX_DOC_CHARS_PER_CALL
from src.schemas import ExtractionResult, FinancialMetric, NarrativeNote

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "financial_metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fund_id": {"type": "string", "description": "Fund or entity identifier"},
                    "metric_name": {"type": "string", "description": "e.g. AUM, IRR, distributions"},
                    "value": {"type": "number"},
                    "unit": {"type": "string", "description": "e.g. USD, %, x"},
                    "period": {"type": "string", "description": "Reporting period as YYYY-Qn, e.g. 2026-Q1"},
                    "source_doc": {"type": "string"},
                },
                "required": ["fund_id", "metric_name", "value", "unit", "period", "source_doc"],
                "additionalProperties": False,
            },
        },
        "narrative_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "period": {"type": "string", "description": "Reporting period as YYYY-Qn, e.g. 2026-Q1"},
                    "note_text": {"type": "string"},
                    "topic_tag": {"type": "string", "description": "Short topic label, e.g. 'litigation', 'leadership change'"},
                    "source_doc": {"type": "string"},
                },
                "required": ["entity_id", "period", "note_text", "topic_tag", "source_doc"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["financial_metrics", "narrative_notes"],
    "additionalProperties": False,
}

EXTRACTION_SYSTEM_PROMPT = """You extract structured data from private equity / financial fund documents.

For every financial figure mentioned (AUM, IRR, distributions, NAV, commitments, etc.),
emit a financial_metrics entry. For every narrative comment about a fund or portfolio
company (leadership changes, litigation, market commentary, outlook), emit a
narrative_notes entry.

Determine "period" from the document's own content (the quarter/year the figures or
commentary describe), formatted as YYYY-Qn. If a document covers multiple periods,
tag each record with its own period. If you cannot determine a period from the
document content, use the fallback period provided in the prompt.

Set source_doc to the filename given in the prompt for every record."""


def _chunk_markdown(markdown: str, max_chars: int) -> list[str]:
    """Split assembled per-page markdown into <=max_chars chunks on page boundaries."""
    sections = markdown.split("\n\n<!-- page ")
    if len(sections) == 1:
        return [markdown] if markdown else []
    sections = [sections[0]] + [f"<!-- page {s}" for s in sections[1:]]
    chunks, current = [], ""
    for section in sections:
        if current and len(current) + len(section) > max_chars:
            chunks.append(current)
            current = section
        else:
            current = f"{current}\n\n{section}" if current else section
    if current:
        chunks.append(current)
    return chunks


@dataclass
class ExtractionOutcome:
    metrics: list[FinancialMetric] = field(default_factory=list)
    notes: list[NarrativeNote] = field(default_factory=list)
    flagged: list[tuple[str, str]] = field(default_factory=list)  # (reason, raw_content)


def _extract_chunk(
    client: anthropic.Anthropic, chunk: str, source_doc: str, fallback_period: str | None
) -> ExtractionOutcome:
    outcome = ExtractionOutcome()
    user_prompt = (
        f"Source document filename: {source_doc}\n"
        f"Fallback period (use only if the document content doesn't indicate a period): "
        f"{fallback_period or 'unknown'}\n\n"
        f"Document content:\n\n{chunk}"
    )
    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=8192,
        system=EXTRACTION_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
        messages=[{"role": "user", "content": user_prompt}],
    )
    if response.stop_reason == "refusal":
        outcome.flagged.append(("model_refusal", ""))
        return outcome

    raw_text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        outcome.flagged.append((f"invalid_json: {e}", raw_text))
        return outcome

    try:
        result = ExtractionResult.model_validate(parsed)
    except ValidationError:
        # Fall back to validating each record individually so one bad record
        # doesn't discard the whole chunk's valid extractions.
        for m in parsed.get("financial_metrics", []):
            try:
                outcome.metrics.append(FinancialMetric.model_validate(m))
            except ValidationError as e:
                outcome.flagged.append((f"invalid_metric: {e}", json.dumps(m)))
        for n in parsed.get("narrative_notes", []):
            try:
                outcome.notes.append(NarrativeNote.model_validate(n))
            except ValidationError as e:
                outcome.flagged.append((f"invalid_note: {e}", json.dumps(n)))
        return outcome

    outcome.metrics.extend(result.financial_metrics)
    outcome.notes.extend(result.narrative_notes)
    return outcome


def extract_document(
    client: anthropic.Anthropic,
    markdown: str,
    source_doc: str,
    fallback_period: str | None = None,
    max_chars_per_call: int = MAX_DOC_CHARS_PER_CALL,
) -> ExtractionOutcome:
    """Run structured extraction over a document's markdown, chunking if needed."""
    combined = ExtractionOutcome()
    for chunk in _chunk_markdown(markdown, max_chars_per_call):
        chunk_outcome = _extract_chunk(client, chunk, source_doc, fallback_period)
        combined.metrics.extend(chunk_outcome.metrics)
        combined.notes.extend(chunk_outcome.notes)
        combined.flagged.extend(chunk_outcome.flagged)
    return combined
