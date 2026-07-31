"""Microsoft Graph connector — Outlook mail and calendar.

Live mode uses the Graph REST API with an Azure AD app registration (client
credentials flow via MSAL). When the app is not configured (see
``config.graph_configured``) every method returns representative **sample data**
instead, so the connector — and every screen built on it — works end to end
with no secrets.

Only read + draft operations are exposed. Nothing here sends mail or mutates a
calendar; drafts are created for the user to review and send from Outlook. This
is deliberate: the connector should never take an irreversible, outward-facing
action on the user's behalf without an explicit, separate confirmation step.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from src import config
from src.schemas import Attendee, CalendarEvent, EmailMessage, TimeSlot

# --------------------------------------------------------------------------- #
# Sample data (mock mode) — grounded in the real Weybourne workflow.
# --------------------------------------------------------------------------- #

_SAMPLE_INBOX = [
    EmailMessage(
        id="mock-1",
        subject="Introduction — Cendana Capital Fund VII (seed/early VC)",
        sender_name="Katie Courtney",
        sender_email="katie.courtney@cendanacapital.com",
        received="2026-07-30T08:12:00",
        body_preview="Following up from the SuperReturn intro — we are opening Fund VII, "
        "a $470m seed-stage fund of funds and direct co-invest sleeve...",
        body=(
            "Hi Jinghan,\n\nGreat to connect at SuperReturn. As discussed, Cendana is "
            "opening Fund VII, a $470m vehicle backing seed-stage venture managers in the "
            "US with a co-investment sleeve. Target net returns 3x+ / ~25% IRR, 10-year "
            "term, 1.0% management fee stepping down after the investment period, 10% carry "
            "over an 8% hurdle. First close is targeted for October.\n\nWould you have "
            "time for an introductory call in the next couple of weeks?\n\nBest,\nKatie "
            "Courtney\nExecutive Assistant to the Managing Partners, Cendana Capital"
        ),
        has_attachments=True,
    ),
    EmailMessage(
        id="mock-2",
        subject="Q2 2026 LP letter — Piting Capital (China A-share L/S)",
        sender_name="Catherine Wu",
        sender_email="catherine@pitingcapital.com",
        received="2026-07-29T15:40:00",
        body_preview="Please find attached our Q2 letter. The fund returned +4.1% net in the "
        "quarter, bringing YTD to +9.6%...",
        body=(
            "Dear investors,\n\nPlease find attached our Q2 2026 letter. The fund returned "
            "+4.1% net in the quarter (+9.6% YTD). We reduced gross exposure into the June "
            "rally and remain constructive on domestic consumption names. AUM is now "
            "$1.3bn.\n\nRegards,\nCatherine Wu\nPiting Capital"
        ),
        has_attachments=True,
    ),
    EmailMessage(
        id="mock-3",
        subject="Re: dinner next week",
        sender_name="Simon Richards",
        sender_email="simon.richards@weybourneholdings.com",
        received="2026-07-29T09:05:00",
        body_preview="Sounds good — Thursday works for me. I'll book somewhere near the office.",
        body="Sounds good — Thursday works for me. I'll book somewhere near the office.",
        has_attachments=False,
    ),
    EmailMessage(
        id="mock-4",
        subject="Trend-following / managed futures — new UCITS launch",
        sender_name="Andrew Alexander",
        sender_email="aalexander@actusray.com",
        received="2026-07-28T11:22:00",
        body_preview="We are launching a systematic trend UCITS targeting crisis-alpha with "
        "daily liquidity — would love to share the track record...",
        body=(
            "Hi Jinghan,\n\nActusRay is launching a systematic trend-following / managed "
            "futures UCITS with daily liquidity, targeting positive convexity in equity "
            "drawdowns (crisis alpha). 15-year simulated + 4-year live track record, ~11% "
            "annualised, -0.1 correlation to MSCI World. 1.25% mgmt / 15% perf. Could we "
            "set up a call to walk through the track record?\n\nBest,\nAndrew Alexander\n"
            "CEO & CIO, ActusRay Partners"
        ),
        has_attachments=True,
    ),
    EmailMessage(
        id="mock-5",
        subject="You're invited: BVCA Summit 2026",
        sender_name="BVCA Events",
        sender_email="events@bvca.co.uk",
        received="2026-07-27T18:00:00",
        body_preview="Join 900+ GPs and LPs at the BVCA Summit in London this October...",
        body="Join 900+ GPs and LPs at the BVCA Summit in London this October. Register now.",
        has_attachments=False,
    ),
]

_SAMPLE_EVENTS = [
    CalendarEvent(
        id="evt-1",
        subject="GP meeting — Old Well Labs (venture secondaries)",
        start="2026-08-04T10:00:00",
        end="2026-08-04T11:00:00",
        location="Teams",
        organizer=Attendee(name="Jinghan Chen", email="Jinghan.Chen@weybourneholdings.com"),
        attendees=[
            Attendee(name="Old Well Labs", email="ir@oldwelllabs.com"),
            Attendee(name="Jinghan Chen", email="Jinghan.Chen@weybourneholdings.com"),
        ],
        is_online=True,
        body_preview="Intro to Old Well Labs' venture secondaries strategy.",
    ),
    CalendarEvent(
        id="evt-2",
        subject="Reference call — The James Irvine Foundation",
        start="2026-08-05T16:00:00",
        end="2026-08-05T16:30:00",
        location="Phone",
        organizer=Attendee(name="Jinghan Chen", email="Jinghan.Chen@weybourneholdings.com"),
        attendees=[
            Attendee(name="Jesús Argüelles", email="jarguelles@irvine.org"),
            Attendee(name="Jinghan Chen", email="Jinghan.Chen@weybourneholdings.com"),
        ],
        is_online=False,
        body_preview="Reference on a manager; exposures & concentration monitoring.",
    ),
    CalendarEvent(
        id="evt-3",
        subject="JH/SR catch up",
        start="2026-08-04T14:00:00",
        end="2026-08-04T14:30:00",
        location="Office",
        organizer=Attendee(name="Simon Richards", email="simon.richards@weybourneholdings.com"),
        attendees=[Attendee(name="Simon Richards", email="simon.richards@weybourneholdings.com")],
        is_online=False,
        body_preview="Weekly catch up.",
    ),
]


# --------------------------------------------------------------------------- #
# Connector
# --------------------------------------------------------------------------- #

class GraphConnector:
    """Read Outlook mail/calendar and create reply drafts.

    Instantiate once and reuse. ``self.live`` reports whether real Graph calls
    are being made; when False, all methods return sample data.
    """

    def __init__(self, user: Optional[str] = None):
        self.user = user or config.MS_USER
        self.live = config.graph_configured()
        self._token: Optional[str] = None

    # -- auth ------------------------------------------------------------- #
    def _access_token(self) -> str:
        if self._token:
            return self._token
        import msal  # imported lazily so mock mode needs no dependency

        app = msal.ConfidentialClientApplication(
            client_id=config.MS_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{config.MS_TENANT_ID}",
            client_credential=config.MS_CLIENT_SECRET,
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise RuntimeError(
                f"Graph auth failed: {result.get('error_description', result)}"
            )
        self._token = result["access_token"]
        return self._token

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        import requests

        url = f"{config.GRAPH_BASE_URL}{path}"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {self._access_token()}"},
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict) -> dict:
        import requests

        url = f"{config.GRAPH_BASE_URL}{path}"
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # -- mail ------------------------------------------------------------- #
    def list_inbox(self, top: int = 25) -> list[EmailMessage]:
        if not self.live:
            return list(_SAMPLE_INBOX)[:top]
        data = self._get(
            f"/users/{self.user}/mailFolders/inbox/messages",
            params={
                "$top": top,
                "$select": "id,subject,from,receivedDateTime,bodyPreview,hasAttachments,webLink,body",
                "$orderby": "receivedDateTime desc",
            },
        )
        return [_email_from_graph(m) for m in data.get("value", [])]

    def create_reply_draft(self, message_id: str, comment: str) -> dict:
        """Create (but do not send) a reply draft for a message."""
        if not self.live:
            return {"id": f"draft-for-{message_id}", "status": "mock-created"}
        return self._post(
            f"/users/{self.user}/messages/{message_id}/createReply",
            {"comment": comment},
        )

    # -- calendar --------------------------------------------------------- #
    def list_events(self, start: dt.datetime, end: dt.datetime) -> list[CalendarEvent]:
        if not self.live:
            return [
                e
                for e in _SAMPLE_EVENTS
                if start.isoformat() <= e.start <= end.isoformat()
            ] or list(_SAMPLE_EVENTS)
        data = self._get(
            f"/users/{self.user}/calendarView",
            params={
                "startDateTime": start.isoformat(),
                "endDateTime": end.isoformat(),
                "$select": "id,subject,start,end,location,organizer,attendees,isOnlineMeeting,bodyPreview",
                "$orderby": "start/dateTime",
                "$top": 100,
            },
        )
        return [_event_from_graph(e) for e in data.get("value", [])]

    def upcoming_events(self, days: int = 14) -> list[CalendarEvent]:
        now = _now()
        return self.list_events(now, now + dt.timedelta(days=days))

    def find_free_slots(
        self,
        days_ahead: int = 10,
        slot_minutes: int = 30,
        work_start_hour: int = 9,
        work_end_hour: int = 18,
        max_slots: int = 5,
    ) -> list[TimeSlot]:
        """Return open working-hours slots not overlapping any calendar event."""
        now = _now()
        busy = self.list_events(now, now + dt.timedelta(days=days_ahead))
        busy_intervals = _parse_busy(busy)
        return _compute_free_slots(
            now=now,
            days_ahead=days_ahead,
            slot_minutes=slot_minutes,
            work_start_hour=work_start_hour,
            work_end_hour=work_end_hour,
            max_slots=max_slots,
            busy_intervals=busy_intervals,
        )


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested without any network access)
# --------------------------------------------------------------------------- #

def _now() -> dt.datetime:
    # Fixed reference date in mock mode keeps sample slots deterministic and
    # aligned with the sample calendar. Live mode uses the real clock.
    if config.graph_configured():
        return dt.datetime.now()
    return dt.datetime(2026, 7, 31, 9, 0, 0)


def _parse_busy(events: list[CalendarEvent]) -> list[tuple[dt.datetime, dt.datetime]]:
    intervals = []
    for e in events:
        try:
            intervals.append((dt.datetime.fromisoformat(e.start), dt.datetime.fromisoformat(e.end)))
        except (ValueError, TypeError):
            continue
    return intervals


def _compute_free_slots(
    now: dt.datetime,
    days_ahead: int,
    slot_minutes: int,
    work_start_hour: int,
    work_end_hour: int,
    max_slots: int,
    busy_intervals: list[tuple[dt.datetime, dt.datetime]],
) -> list[TimeSlot]:
    """Walk working hours over the next N days, emitting non-overlapping slots."""
    slots: list[TimeSlot] = []
    delta = dt.timedelta(minutes=slot_minutes)
    day = now.date()
    for _ in range(days_ahead + 1):
        if day.weekday() >= 5:  # skip Sat/Sun
            day += dt.timedelta(days=1)
            continue
        cursor = dt.datetime.combine(day, dt.time(hour=work_start_hour))
        day_end = dt.datetime.combine(day, dt.time(hour=work_end_hour))
        # Never offer a slot in the past.
        if cursor < now:
            # advance to the next slot boundary after `now`
            while cursor < now:
                cursor += delta
        while cursor + delta <= day_end:
            slot_end = cursor + delta
            overlaps = any(bs < slot_end and cursor < be for bs, be in busy_intervals)
            if not overlaps:
                slots.append(TimeSlot(start=cursor.isoformat(), end=slot_end.isoformat()))
                if len(slots) >= max_slots:
                    return slots
            cursor = slot_end
        day += dt.timedelta(days=1)
    return slots


def _email_from_graph(m: dict) -> EmailMessage:
    sender = (m.get("from") or {}).get("emailAddress") or {}
    body = m.get("body") or {}
    return EmailMessage(
        id=m.get("id", ""),
        subject=m.get("subject") or "",
        sender_name=sender.get("name") or "",
        sender_email=sender.get("address") or "",
        received=m.get("receivedDateTime") or "",
        body_preview=m.get("bodyPreview") or "",
        body=_strip_html(body.get("content", "")) if body.get("contentType") == "html" else body.get("content", ""),
        has_attachments=bool(m.get("hasAttachments")),
        web_link=m.get("webLink"),
    )


def _event_from_graph(e: dict) -> CalendarEvent:
    org = ((e.get("organizer") or {}).get("emailAddress")) or {}
    attendees = [
        Attendee(
            name=(a.get("emailAddress") or {}).get("name", ""),
            email=(a.get("emailAddress") or {}).get("address", ""),
        )
        for a in e.get("attendees", [])
    ]
    return CalendarEvent(
        id=e.get("id", ""),
        subject=e.get("subject") or "",
        start=(e.get("start") or {}).get("dateTime", ""),
        end=(e.get("end") or {}).get("dateTime", ""),
        location=((e.get("location") or {}).get("displayName")) or "",
        organizer=Attendee(name=org.get("name", ""), email=org.get("address", "")),
        attendees=attendees,
        is_online=bool(e.get("isOnlineMeeting")),
        body_preview=e.get("bodyPreview") or "",
    )


def _strip_html(html: str) -> str:
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+\n", "\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()
