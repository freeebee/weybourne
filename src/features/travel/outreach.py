"""Guardrailed outreach drafting, reply interpretation and state transitions."""
from __future__ import annotations

import datetime as dt
import re
import uuid
from zoneinfo import ZoneInfo

from src import config
from src.connectors.graph import GraphConnector
from src.schemas import EmailMessage
from .models import MeetingCandidate, OutreachMessage, ReplyDecision, TravelTrip
from .store import TravelStore, utcnow


def slot_label(value: str) -> str:
    moment = dt.datetime.fromisoformat(value)
    return f"{moment.strftime('%A')} {moment.day} {moment.strftime('%B at %H:%M')}"


def draft_wave(trip: TravelTrip, tier: int, template: str = "") -> list[OutreachMessage]:
    targets = [c for c in trip.candidates if c.selected and c.tier == tier
               and c.status in ("selected", "candidate", "needs-review")]
    if len(targets) > config.TRAVEL_MAX_WAVE_RECIPIENTS:
        raise ValueError(
            f"A wave cannot contain more than {config.TRAVEL_MAX_WAVE_RECIPIENTS} recipients")
    blocked = [c.name for c in targets if len(c.slots) < 2]
    if blocked:
        raise ValueError("At least two feasible slots are required for: " + ", ".join(blocked))
    # Manager rows (added without a person) carry no address to write to.
    # Refusing the whole wave names them, so the user picks a contact or
    # fills the email in on the itinerary rather than sending into a void.
    no_email = [c.name for c in targets if not (c.email or "").strip()]
    if no_email:
        raise ValueError("No email on record for: " + ", ".join(no_email)
                         + ". Add a contact for them or set an email on the itinerary.")
    existing = {m.candidate_id: m for m in trip.outreach if m.tier == tier and m.state != "failed"}
    result = []
    for c in targets:
        if c.id in existing:
            result.append(existing[c.id])
            continue
        options = "\n".join(f"{i + 1}. {slot_label(s.start)}" for i, s in enumerate(c.slots))
        default = (
            "Hi {first_name},\n\n"
            "I will be in {city} from {start_date} to {end_date} and would be delighted "
            "to catch up at {company}. Would any of these times work for you?\n\n"
            "{slots}\n\n"
            "All times are local to {city}.\n\nBest,\nJinghan"
        )
        source = template.strip() or default
        body = source.format(
            first_name=c.name.split()[0] if c.name else "there", city=c.city,
            country=c.country, company=c.company, start_date=trip.start_date,
            end_date=trip.end_date, slots=options,
        )
        result.append(OutreachMessage(
            id=str(uuid.uuid4()), candidate_id=c.id, tier=tier,
            subject=f"Meeting in {c.city} — {trip.name}", body=body,
        ))
    trip.outreach = [m for m in trip.outreach if m.tier != tier] + result
    return result


def send_wave(trip: TravelTrip, tier: int, graph: GraphConnector,
              store: TravelStore, allow_demo: bool = False) -> list[OutreachMessage]:
    if not graph.live and not allow_demo:
        raise PermissionError("Live Microsoft Graph is required to send outreach")
    messages = [m for m in trip.outreach if m.tier == tier]
    if not messages:
        raise ValueError("Draft this wave before sending it")
    candidates = {c.id: c for c in trip.candidates}
    for message in messages:
        if message.state == "sent":
            continue
        person = candidates.get(message.candidate_id)
        if not person or not person.email:
            message.state, message.error = "failed", "Recipient has no email address"
            continue
        key = f"send-wave-{tier}-{message.id}"
        try:
            if not message.graph_message_id:
                draft = graph.create_message_draft(person.email, message.subject,
                                                   message.body, trip.id)
                message.graph_message_id = draft.get("id", "")
                message.conversation_id = draft.get("conversationId", "")
            if store.action_once(trip.id, key, "send-outreach", {
                "candidate_id": person.id, "draft_id": message.graph_message_id,
            }):
                graph.send_draft(message.graph_message_id)
            message.state, message.sent_at, message.error = "sent", utcnow(), ""
            person.status = "offered"
            for slot in person.slots:
                slot.status = "offered"
        except Exception as exc:  # retain partial progress for safe retry
            message.state, message.error = "failed", str(exc)
    trip.status = "coordinating"
    return messages


def _new_text(body: str) -> str:
    text = body or ""
    for marker in ("-----Original Message-----", "\nFrom:", "\nOn "):
        if marker in text:
            text = text.split(marker, 1)[0]
    return text.strip()


def classify_reply(message: EmailMessage, candidate: MeetingCandidate) -> ReplyDecision:
    text = _new_text(message.body or message.body_preview)
    low = text.casefold()
    selected = ""
    ordinal = {"option 1": 0, "first option": 0, "option 2": 1,
               "second option": 1, "option 3": 2, "third option": 2}
    for phrase, index in ordinal.items():
        if phrase in low and index < len(candidate.slots):
            selected = candidate.slots[index].id
            break
    if not selected:
        for slot in candidate.slots:
            moment = dt.datetime.fromisoformat(slot.start)
            tokens = [moment.strftime("%H:%M")]
            # Windows does not support %-d; the portable day token covers it.
            day_token = f"{moment.day} {moment.strftime('%B')}".casefold()
            if tokens[0] in text and day_token in low:
                selected = slot.id
                break
    accepts = any(x in low for x in ("works for me", "that works", "i can do", "confirm", "option "))
    declines = any(x in low for x in ("none of", "cannot make", "can't make", "not available", "decline"))
    question = "?" in text and not selected
    proposed = re.search(r"(20\d\d-\d\d-\d\d)[ T](\d\d:\d\d)", text)
    if selected and accepts:
        kind, confidence = "accepted", .99
    elif declines and proposed:
        kind, confidence = "counterproposal", .94
    elif declines:
        kind, confidence = "declined", .9
    elif proposed:
        kind, confidence = "counterproposal", .88
    elif question:
        kind, confidence = "question", .8
    else:
        kind, confidence = "ambiguous", .35
    start = ""
    end = ""
    if proposed:
        start_dt = dt.datetime.fromisoformat(f"{proposed.group(1)}T{proposed.group(2)}:00")
        start, end = start_dt.isoformat(), (start_dt + dt.timedelta(minutes=candidate.duration_minutes)).isoformat()
    return ReplyDecision(
        id=str(uuid.uuid4()), candidate_id=candidate.id, message_id=message.id,
        kind=kind, confidence=confidence, selected_slot_id=selected,
        proposed_start=start, proposed_end=end, evidence=text[:500],
        draft_response=(
            "Thanks for coming back to me. Let me check the rest of the trip and "
            "I will confirm a workable time shortly."
            if kind in ("counterproposal", "ambiguous", "question") else ""
        ),
    )


def match_replies(trip: TravelTrip, messages: list[EmailMessage]) -> list[ReplyDecision]:
    already = {r.message_id for r in trip.replies}
    outbound = {m.candidate_id: m for m in trip.outreach if m.state == "sent"}
    candidates = {c.id: c for c in trip.candidates}
    additions = []
    for message in messages:
        if message.id in already:
            continue
        match = None
        for candidate_id, sent in outbound.items():
            candidate = candidates.get(candidate_id)
            same_thread = sent.conversation_id and message.conversation_id == sent.conversation_id
            same_sender = candidate and candidate.email.casefold() == message.sender_email.casefold()
            if same_thread or same_sender:
                match = candidate
                break
        if match:
            additions.append(classify_reply(message, match))
    trip.replies.extend(additions)
    return additions


def apply_declines(trip: TravelTrip) -> list[str]:
    """Release the slots of confidently declined candidates.

    Pure state, no external side effect — so unlike acceptance handling this
    runs in demo mode too. Without it a declined candidate stayed "offered"
    forever and their slots kept blocking those times for everyone else
    (slot status "released" existed in the model but was never assigned).
    Low-confidence declines stay pending for the review ledger.
    """
    declined = []
    candidates = {c.id: c for c in trip.candidates}
    for reply in trip.replies:
        if reply.state != "pending" or reply.kind != "declined" or reply.confidence < .9:
            continue
        candidate = candidates.get(reply.candidate_id)
        if not candidate or candidate.status in ("accepted", "scheduled"):
            continue
        candidate.status = "declined"
        for slot in candidate.slots:
            slot.status = "released"
        reply.state = "handled"
        declined.append(candidate.id)
    return declined


def apply_clear_acceptances(trip: TravelTrip, graph: GraphConnector,
                            store: TravelStore, events: list) -> list[str]:
    """Create invites only for deterministic, still-feasible acceptances."""
    created = []
    candidates = {c.id: c for c in trip.candidates}
    busy = []
    for event in events:
        try:
            busy.append((dt.datetime.fromisoformat(event.start.replace("Z", "+00:00")).replace(tzinfo=None),
                         dt.datetime.fromisoformat(event.end.replace("Z", "+00:00")).replace(tzinfo=None)))
        except ValueError:
            pass
    for reply in trip.replies:
        if reply.state != "pending" or reply.kind not in ("accepted", "counterproposal"):
            continue
        candidate = candidates.get(reply.candidate_id)
        if not candidate:
            continue
        slot = next((s for s in candidate.slots if s.id == reply.selected_slot_id), None)
        start = slot.start if slot else reply.proposed_start
        end = slot.end if slot else reply.proposed_end
        if not start or not end or reply.confidence < .9:
            candidate.status = "needs-review"
            continue
        s, e = dt.datetime.fromisoformat(start), dt.datetime.fromisoformat(end)
        if any(s < be and bs < e for bs, be in busy):
            candidate.status = "needs-review"
            candidate.explanation = "The accepted time now conflicts with the calendar."
            continue
        key = f"calendar-{candidate.id}-{start}"
        city_id = slot.city_id if slot else ""
        city = next((c for c in trip.cities if c.id == city_id), None)
        if not city:
            city = next((c for c in trip.cities if c.name == candidate.city), None)
        timezone_name = city.timezone if city else trip.timezone
        try:
            tz = ZoneInfo(timezone_name)
            graph_start = s.replace(tzinfo=tz).astimezone(dt.timezone.utc).replace(tzinfo=None).isoformat()
            graph_end = e.replace(tzinfo=tz).astimezone(dt.timezone.utc).replace(tzinfo=None).isoformat()
        except Exception:
            graph_start, graph_end = start, end
        if store.action_once(trip.id, key, "create-calendar-event", {
            "candidate_id": candidate.id, "start": start, "end": end,
        }):
            result = graph.create_event(
                f"Meeting with {candidate.company}", graph_start, graph_end, candidate.email,
                candidate.name, candidate.office.address or candidate.company,
                f"Meeting arranged through the {trip.name} travel plan.", key,
            )
            candidate.scheduled_event_id = result.get("id", "")
        candidate.status = "scheduled"
        candidate.slots = [slot] if slot else []
        if candidate.slots:
            candidate.slots[0].status = "accepted"
        reply.state = "handled"
        created.append(candidate.id)
        busy.append((s, e))
    return created
