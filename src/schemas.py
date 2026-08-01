"""Pydantic models for validated extraction output and DB records.

Two families of models live here:

1. The PDF-extraction pipeline models (``FinancialMetric``, ``NarrativeNote``,
   ``ExtractionResult``, ``ManifestEntry``) — unchanged.
2. The Weybourne Investment Connector models (Outlook/Notion connector shapes,
   triage, dedupe, preference screening, draft replies, meeting prep,
   track records) — added below the pipeline section.
"""
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

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


# =========================================================================== #
# Weybourne Investment Connector models
# =========================================================================== #

Sleeve = Literal["Private Growth", "Public Growth", "Diversifiers", "Unclear"]


# --- Outlook / Microsoft Graph shapes -------------------------------------- #

class EmailMessage(BaseModel):
    id: str
    subject: str = ""
    sender_name: str = ""
    sender_email: str = ""
    received: str = ""            # ISO-8601
    body_preview: str = ""
    body: str = ""               # full text/plain body when fetched
    has_attachments: bool = False
    web_link: Optional[str] = None


class Attendee(BaseModel):
    name: str = ""
    email: str = ""


class CalendarEvent(BaseModel):
    id: str
    subject: str = ""
    start: str = ""              # ISO-8601
    end: str = ""                # ISO-8601
    location: str = ""
    organizer: Optional[Attendee] = None
    attendees: list[Attendee] = Field(default_factory=list)
    is_online: bool = False
    body_preview: str = ""


class TimeSlot(BaseModel):
    start: str                   # ISO-8601
    end: str                     # ISO-8601

    def label(self) -> str:
        """Human-friendly label, e.g. 'Tue 4 Aug, 14:00–14:30'."""
        from datetime import datetime

        try:
            s = datetime.fromisoformat(self.start)
            e = datetime.fromisoformat(self.end)
        except ValueError:
            return f"{self.start} – {self.end}"
        return f"{s.strftime('%a %-d %b, %H:%M')}–{e.strftime('%H:%M')}"


# --- Notion database record shapes (subset of the Property Guidebook) ------- #

class ContactRecord(BaseModel):
    id: Optional[str] = None
    name: str = ""
    email: str = ""             # the key unique identifier for Contacts
    title: str = ""
    type: str = ""
    company: str = ""


class CompanyRecord(BaseModel):
    id: Optional[str] = None
    name: str = ""
    description: str = ""
    city: str = ""
    country: str = ""
    domain: str = ""            # derived, used for matching


class FundRecord(BaseModel):
    id: Optional[str] = None
    name: str = ""
    asset_class: list[str] = Field(default_factory=list)
    geographic_focus: list[str] = Field(default_factory=list)
    strategy_description: str = ""
    status: str = ""
    company: str = ""


# --- Triage & entity extraction -------------------------------------------- #

class ExtractedEntity(BaseModel):
    """The investment entity an email appears to be about."""
    fund_name: str = ""
    company_name: str = ""
    company_domain: str = ""
    contact_name: str = ""
    contact_email: str = ""
    contact_title: str = ""
    asset_class: str = ""
    geography: str = ""
    sleeve: Sleeve = "Unclear"
    summary: str = ""


class InvestmentTriage(BaseModel):
    """Result of classifying a single email for investment relevance."""
    message_id: str = ""
    is_investment: bool = False
    confidence: float = 0.0      # 0..1
    category: str = ""           # e.g. 'New fund intro', 'LP update', 'Not relevant'
    rationale: str = ""
    entity: ExtractedEntity = Field(default_factory=ExtractedEntity)
    key_facts: list[str] = Field(default_factory=list)


# --- Dedupe ---------------------------------------------------------------- #

class DedupeMatch(BaseModel):
    db: Literal["contacts", "companies", "funds"]
    matched_name: str
    matched_id: Optional[str] = None
    score: float                 # 0..1 similarity
    reason: str = ""


class DedupeDecision(BaseModel):
    entity_kind: Literal["contact", "company", "fund"]
    name: str
    is_duplicate: bool
    best_match: Optional[DedupeMatch] = None
    all_matches: list[DedupeMatch] = Field(default_factory=list)
    recommended_action: Literal["create", "link_existing", "review"] = "create"


# --- CHAO preference screening --------------------------------------------- #

class PreferenceScreen(BaseModel):
    sleeve: Sleeve
    overall_fit: Literal["Fit", "Partial", "Non-fit", "Unclear"]
    fit_points: list[str] = Field(default_factory=list)
    non_fit_points: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    summary: str = ""


# --- Draft replies --------------------------------------------------------- #

class DraftReplyOption(BaseModel):
    key: str                     # stable id, e.g. 'pass_polite'
    label: str                   # button label shown in the UI
    intent: Literal["pass", "meeting", "info", "hold"]
    subject: str = ""
    body: str = ""


# --- Meeting prep ---------------------------------------------------------- #

class MeetingPrep(BaseModel):
    counterparty_name: str = ""
    counterparty_title: str = ""
    company_name: str = ""
    meeting_subject: str = ""
    meeting_time: str = ""
    prep_markdown: str = ""
    diligence_questions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
