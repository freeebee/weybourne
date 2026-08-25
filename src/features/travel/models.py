"""Stable data contracts for the travel planner.

The complete trip is stored as one versioned document while irreversible mail
and calendar actions have their own idempotency ledger in ``store.py``.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DestinationAnchor(BaseModel):
    type: Literal["country", "manager", "event"]
    id: str = ""
    label: str


class TripCity(BaseModel):
    id: str
    name: str
    country: str
    start_date: str
    end_date: str
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = "UTC"
    order: int = 0
    selected_hotel_id: str = ""


class TransferBlock(BaseModel):
    id: str
    from_city_id: str
    to_city_id: str
    start: str
    end: str
    details: str = ""
    confirmed: bool = False


class OfficeResolution(BaseModel):
    query: str = ""
    place_id: str = ""
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None
    confidence: float = 0
    confirmed: bool = False
    candidates: list[dict] = Field(default_factory=list)


class MeetingSlot(BaseModel):
    id: str
    start: str
    end: str
    city_id: str
    status: Literal["proposed", "offered", "accepted", "released"] = "proposed"


class MeetingCandidate(BaseModel):
    id: str
    contact_id: str = ""
    company_id: str = ""
    name: str
    email: str = ""
    title: str = ""
    company: str
    city: str
    country: str
    tier: Literal[1, 2] = 1
    duration_minutes: int = Field(default=60, ge=15, le=240)
    venue: Literal["office", "hotel", "neutral", "online"] = "office"
    selected: bool = True
    status: Literal[
        "candidate", "selected", "offered", "accepted", "declined",
        "needs-review", "scheduled",
    ] = "selected"
    office: OfficeResolution = Field(default_factory=OfficeResolution)
    slots: list[MeetingSlot] = Field(default_factory=list)
    scheduled_event_id: str = ""
    explanation: str = ""


class HotelOption(BaseModel):
    id: str
    provider_hotel_id: str = ""
    city_id: str
    name: str
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None
    nightly_gbp: float
    total_gbp: float
    taxes_gbp: float | None = None
    rating: float | None = None
    review_count: int | None = None
    stars: float | None = None
    aggregate_travel_minutes: float | None = None
    cancellation: str = ""
    booking_url: str = ""
    quoted_at: str
    score: float = 0
    selected: bool = False


class OutreachMessage(BaseModel):
    id: str
    candidate_id: str
    tier: Literal[1, 2]
    subject: str
    body: str
    state: Literal["draft", "approved", "sent", "failed"] = "draft"
    graph_message_id: str = ""
    conversation_id: str = ""
    error: str = ""
    sent_at: str = ""


class ReplyDecision(BaseModel):
    id: str
    candidate_id: str
    message_id: str
    kind: Literal["accepted", "declined", "counterproposal", "ambiguous", "question"]
    confidence: float = 0
    selected_slot_id: str = ""
    proposed_start: str = ""
    proposed_end: str = ""
    evidence: str = ""
    draft_response: str = ""
    state: Literal["pending", "handled", "ignored"] = "pending"


class TravelSettings(BaseModel):
    work_start: str = "09:00"
    work_end: str = "17:30"
    lunch_start: str = "12:30"
    lunch_end: str = "13:30"
    default_duration_minutes: int = 60
    travel_mode: Literal["DRIVE", "TRANSIT", "WALK"] = "DRIVE"
    nightly_budget_gbp: float = Field(default=250, gt=0)
    hotel_price_weight: float = 0.40
    hotel_travel_weight: float = 0.35
    hotel_quality_weight: float = 0.25

    @model_validator(mode="after")
    def weights_total(self):
        total = self.hotel_price_weight + self.hotel_travel_weight + self.hotel_quality_weight
        if abs(total - 1.0) > 0.001:
            raise ValueError("hotel ranking weights must add to 1")
        return self


class TravelTrip(BaseModel):
    id: str
    name: str
    anchor: DestinationAnchor
    start_date: str
    end_date: str
    timezone: str = "UTC"
    status: Literal["planning", "ready", "coordinating", "complete"] = "planning"
    settings: TravelSettings = Field(default_factory=TravelSettings)
    cities: list[TripCity] = Field(default_factory=list)
    transfers: list[TransferBlock] = Field(default_factory=list)
    candidates: list[MeetingCandidate] = Field(default_factory=list)
    hotels: list[HotelOption] = Field(default_factory=list)
    outreach: list[OutreachMessage] = Field(default_factory=list)
    replies: list[ReplyDecision] = Field(default_factory=list)
    inbox_delta_link: str = ""
    created_at: str
    updated_at: str
    version: int = 1

    @model_validator(mode="after")
    def valid_dates(self):
        if date.fromisoformat(self.end_date) < date.fromisoformat(self.start_date):
            raise ValueError("end_date must be on or after start_date")
        return self
