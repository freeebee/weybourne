"""Microsoft Graph connector — Outlook mail and calendar.

There are three modes, tried in order:

1. **Live** — the Graph REST API with an Entra ID (Azure AD) app registration
   (client-credentials flow via MSAL). Requires ``MS_TENANT_ID`` /
   ``MS_CLIENT_ID`` / ``MS_CLIENT_SECRET``. Only needed for the standalone app
   to reach Outlook unattended.
2. **Snapshot bridge** — if ``data/inbox_snapshot.json`` /
   ``data/calendar_snapshot.json`` exist, they are used. This is how *real*
   Outlook data reaches the app today without an Entra registration: Claude
   fetches mail/events through its own Microsoft 365 connector and writes the
   snapshot files (see ``scripts/refresh_outlook_snapshot.py`` for the shape).
3. **Sample data** — representative mock records, so the connector and every
   screen built on it work end to end with no credentials at all.

Only read + draft operations are exposed. Nothing here sends mail or mutates a
calendar; drafts are created for the user to review and send from Outlook. This
is deliberate: the connector should never take an irreversible, outward-facing
action on the user's behalf without an explicit, separate confirmation step.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional

from src import config
from src.schemas import Attendee, CalendarEvent, EmailMessage, TimeSlot

# Snapshot files written by Claude's Microsoft 365 connector (see module docstring).
INBOX_SNAPSHOT = config.BASE_DIR / "data" / "inbox_snapshot.json"
CALENDAR_SNAPSHOT = config.BASE_DIR / "data" / "calendar_snapshot.json"
SHARED_INBOX_SNAPSHOT = config.BASE_DIR / "data" / "shared_inbox_snapshot.json"


def _load_snapshot(path: Path) -> list[dict] | None:
    """Return the records in a snapshot file, or None if it's absent/unreadable."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    records = data.get("value", data) if isinstance(data, dict) else data
    return records if isinstance(records, list) else None

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

_SAMPLE_SHARED_INBOX = [
    EmailMessage(
        id="shared-1",
        subject="FW: Nephila — capacity reopening for existing LPs",
        sender_name="Tom Osborne",
        sender_email="t.osborne@placementpartners.com",
        received="2026-07-31T10:02:00",
        body_preview="Nephila is reopening capacity in the climate strategy for existing "
                     "LPs only, closing end of August...",
        body="Nephila is reopening limited capacity in the climate strategy for existing "
             "LPs, closing end of August. Minimum $10m. Happy to set up a call.",
    ),
    EmailMessage(
        id="shared-2",
        subject="Q2 letters — consolidated pack",
        sender_name="Weybourne Investments",
        sender_email="wbinvestments@weybourne.co.uk",
        received="2026-07-30T09:15:00",
        body_preview="All Q2 manager letters received to date are filed in the shared "
                     "drive; three managers outstanding...",
        body="All Q2 manager letters received to date are filed. Outstanding: REVA, "
             "Cavamont, Dockside. Chasers sent 29 July.",
    ),
    EmailMessage(
        id="shared-3",
        subject="Invitation: Asia allocators roundtable — Singapore, 12 Sept",
        sender_name="Institutional Investor Events",
        sender_email="events@institutionalinvestor.com",
        received="2026-07-28T14:30:00",
        body_preview="You are invited to an allocators-only roundtable on Asian private "
                     "markets...",
        body="Allocators-only roundtable on Asian private markets, Singapore, 12 Sept. "
             "Peer group: 20 family offices and endowments.",
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
    def list_inbox(self, top: Optional[int] = None, days: Optional[int] = None) -> list[EmailMessage]:
        """Recent mail from the **top-level Inbox** only.

        Scope, per how the mailbox is actually used:

        * Only messages sitting directly in the Inbox. Anything filed into a
          subfolder has been dealt with and is not returned — filing is the
          "done" signal.
        * Both Focused and Other, since cold fund intros frequently land in
          Other.
        * Only the last ``days`` days (rolling window, default
          ``config.TRIAGE_LOOKBACK_DAYS``).
        """
        top = config.TRIAGE_MAX_MESSAGES if top is None else top
        days = config.TRIAGE_LOOKBACK_DAYS if days is None else days
        cutoff = _now() - dt.timedelta(days=days)

        if not self.live:
            snapshot = _load_snapshot(INBOX_SNAPSHOT)
            if snapshot is not None:
                records = [m for m in snapshot if _in_main_inbox(m)]
                messages = [_email_from_snapshot(m) for m in records]
            else:
                messages = list(_SAMPLE_INBOX)
            recent = [m for m in messages if _received_within(m.received, cutoff)]
            recent.sort(key=lambda m: m.received, reverse=True)
            return recent[:top]

        # /mailFolders/inbox/messages returns only messages directly in the
        # Inbox - subfolders are excluded by Graph itself, which is exactly the
        # behaviour wanted here. $filter and $orderby both use receivedDateTime,
        # so Graph won't reject the combination as too complex.
        data = self._get(
            f"/users/{self.user}/mailFolders/inbox/messages",
            params={
                "$top": top,
                "$select": "id,subject,from,receivedDateTime,bodyPreview,"
                           "hasAttachments,webLink,body,parentFolderId",
                "$orderby": "receivedDateTime desc",
                "$filter": f"receivedDateTime ge {_graph_timestamp(cutoff)}",
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

    def delete_message(self, message_id: str) -> dict:
        """Move a message to Deleted Items (soft delete — recoverable in Outlook).

        Deliberately not a hard delete: the app never destroys mail
        irrecoverably. Mock mode returns a no-op preview.
        """
        if not self.live:
            return {"id": message_id, "status": "mock-deleted"}
        return self._post(
            f"/users/{self.user}/messages/{message_id}/move",
            {"destinationId": "deleteditems"},
        )

    def list_shared_inbox(self, top: int = 40, days: int = 7) -> list[EmailMessage]:
        """Recent mail from the Investments shared mailbox (read-only).

        Live mode reads ``config.SHARED_MAILBOX`` via Graph (the app
        registration needs Mail.Read for that mailbox). Otherwise a snapshot at
        ``data/shared_inbox_snapshot.json`` is used if present, else samples.
        """
        cutoff = _now() - dt.timedelta(days=days)

        if not self.live:
            snapshot = _load_snapshot(SHARED_INBOX_SNAPSHOT)
            messages = ([_email_from_snapshot(m) for m in snapshot]
                        if snapshot is not None else list(_SAMPLE_SHARED_INBOX))
            recent = [m for m in messages if _received_within(m.received, cutoff)]
            recent.sort(key=lambda m: m.received, reverse=True)
            return recent[:top]

        data = self._get(
            f"/users/{config.SHARED_MAILBOX}/mailFolders/inbox/messages",
            params={
                "$top": top,
                "$select": "id,subject,from,receivedDateTime,bodyPreview,"
                           "hasAttachments,webLink,body,parentFolderId",
                "$orderby": "receivedDateTime desc",
                "$filter": f"receivedDateTime ge {_graph_timestamp(cutoff)}",
            },
        )
        return [_email_from_graph(m) for m in data.get("value", [])]

    # -- calendar --------------------------------------------------------- #
    def list_events(self, start: dt.datetime, end: dt.datetime) -> list[CalendarEvent]:
        if not self.live:
            snapshot = _load_snapshot(CALENDAR_SNAPSHOT)
            events = (
                [_event_from_snapshot(e) for e in snapshot]
                if snapshot is not None
                else list(_SAMPLE_EVENTS)
            )
            in_window = [
                e for e in events if start.isoformat() <= e.start <= end.isoformat()
            ]
            return in_window or events
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
        min_lead_hours: int = 24,
    ) -> list[TimeSlot]:
        """Return open working-hours slots not overlapping any calendar event.

        ``min_lead_hours`` keeps the offer realistic — proposing a call starting
        in ten minutes is worse than proposing nothing.
        """
        now = _now()
        busy = self.list_events(now, now + dt.timedelta(days=days_ahead))
        busy_intervals = _parse_busy(busy)
        return _compute_free_slots(
            now=now + dt.timedelta(hours=min_lead_hours),
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

# The built-in sample data is dated around this moment, so demo mode uses it as
# "now" to keep sample slots and the sample inbox window deterministic.
SAMPLE_CLOCK = dt.datetime(2026, 7, 31, 9, 0, 0)


def _serving_sample_data() -> bool:
    """True only when the built-in sample records are what's being served.

    Snapshot files hold *real* mail and calendar entries, so they must be judged
    against the real clock — freezing time for them would, for example, make a
    "last 3 days" window return nothing as soon as a snapshot is refreshed on a
    later date.
    """
    return not config.graph_configured() and not (
        INBOX_SNAPSHOT.exists() or CALENDAR_SNAPSHOT.exists()
    )


def _now() -> dt.datetime:
    return SAMPLE_CLOCK if _serving_sample_data() else dt.datetime.now()


def _graph_timestamp(value: dt.datetime) -> str:
    """Format a datetime for a Graph $filter comparison (UTC, 'Z'-suffixed)."""
    return _as_utc(value).replace(microsecond=0).isoformat() + "Z"


def _as_utc(value: dt.datetime) -> dt.datetime:
    """Normalise to naive UTC so timestamps from different sources compare.

    Microsoft Graph returns timezone-aware values ("...Z"); the sample and
    snapshot records are naive. Comparing the two directly raises TypeError, so
    everything is converted to naive UTC first. Naive input is assumed to be UTC.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(dt.timezone.utc).replace(tzinfo=None)


def _received_within(received: str, cutoff: dt.datetime) -> bool:
    """Whether an ISO-8601 timestamp is at or after ``cutoff``.

    An unparseable or missing timestamp is **kept**: dropping a real email
    because its date couldn't be read is worse than triaging one extra.
    """
    if not received:
        return True
    try:
        parsed = dt.datetime.fromisoformat(received.strip())
    except (ValueError, TypeError):
        return True
    return _as_utc(parsed) >= _as_utc(cutoff)


# Folder names that count as the top-level Inbox. Anything the user has filed
# into a subfolder (research, fund managers, ...) has been dealt with already.
_INBOX_FOLDER_NAMES = {"inbox", "focused", "other"}


def _in_main_inbox(record: dict) -> bool:
    """Whether a snapshot record belongs to the top-level Inbox.

    Records carrying no folder information are kept — absence of the field isn't
    evidence that the message was filed.
    """
    folder = (
        record.get("folder")
        or record.get("parentFolderName")
        or record.get("folder_name")
        or ""
    )
    if not folder:
        return True
    return folder.strip().lower() in _INBOX_FOLDER_NAMES


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


def _email_from_snapshot(m: dict) -> EmailMessage:
    """Parse a snapshot record, accepting either raw Graph JSON or a flat shape.

    Claude's Microsoft 365 connector returns a simplified shape; a raw Graph
    export nests sender under ``from.emailAddress``. Accept both so a snapshot
    can be dropped in from either source.
    """
    if "from" in m or "receivedDateTime" in m:
        return _email_from_graph(m)
    return EmailMessage(
        id=str(m.get("id") or m.get("message_id") or ""),
        subject=m.get("subject") or "",
        sender_name=m.get("sender_name") or m.get("sender") or "",
        sender_email=m.get("sender_email") or m.get("from_email") or "",
        received=m.get("received") or m.get("date") or "",
        body_preview=m.get("body_preview") or m.get("snippet") or "",
        body=m.get("body") or m.get("body_preview") or "",
        has_attachments=bool(m.get("has_attachments")),
        web_link=m.get("web_link"),
    )


def _event_from_snapshot(e: dict) -> CalendarEvent:
    """Parse a calendar snapshot record (raw Graph JSON or a flat shape)."""
    if "start" in e and isinstance(e.get("start"), dict):
        return _event_from_graph(e)
    attendees = []
    for a in e.get("attendees", []):
        if isinstance(a, dict):
            attendees.append(Attendee(name=a.get("name", ""), email=a.get("email", "")))
        elif isinstance(a, str):
            attendees.append(Attendee(name=a, email=a if "@" in a else ""))
    organizer = e.get("organizer")
    if isinstance(organizer, dict):
        organizer = Attendee(name=organizer.get("name", ""), email=organizer.get("email", ""))
    elif isinstance(organizer, str):
        organizer = Attendee(name=organizer, email=organizer if "@" in organizer else "")
    else:
        organizer = None
    return CalendarEvent(
        id=str(e.get("id") or ""),
        subject=e.get("subject") or e.get("title") or "",
        start=e.get("start") or "",
        end=e.get("end") or "",
        location=e.get("location") or "",
        organizer=organizer,
        attendees=attendees,
        is_online=bool(e.get("is_online")),
        body_preview=e.get("body_preview") or "",
    )


def _strip_html(html: str) -> str:
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+\n", "\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()
