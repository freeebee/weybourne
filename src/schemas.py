"""Pydantic models for validated extraction output and DB records."""
import re
from typing import Optional

from pydantic import BaseModel, field_validator

PERIOD_RE = re.compile(r"^\d{4}-Q[1-4]$")


class FinancialMetric(BaseModel):
    fund_id: str
    metric_name: str
    value: float
    unit: str
    period: str
    source_doc: str

    @field_validator("period")
    @classmethod
    def validate_period(cls, v: str) -> str:
        if not PERIOD_RE.match(v):
            raise ValueError(f"period must look like YYYY-Qn, got {v!r}")
        return v

    @field_validator("fund_id", "metric_name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class NarrativeNote(BaseModel):
    entity_id: str
    period: str
    note_text: str
    topic_tag: str
    source_doc: str

    @field_validator("period")
    @classmethod
    def validate_period(cls, v: str) -> str:
        if not PERIOD_RE.match(v):
            raise ValueError(f"period must look like YYYY-Qn, got {v!r}")
        return v

    @field_validator("entity_id", "note_text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class ExtractionResult(BaseModel):
    """Top-level shape the extraction prompt is asked to return."""
    financial_metrics: list[FinancialMetric] = []
    narrative_notes: list[NarrativeNote] = []


class ManifestEntry(BaseModel):
    filename: str
    file_hash: str
    period: Optional[str] = None
    processed_date: Optional[str] = None
