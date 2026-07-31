#!/usr/bin/env python3
"""Write Outlook snapshot files that the app reads when Graph isn't configured.

Why this exists
---------------
Reaching Outlook directly from the app needs an Entra ID (Azure AD) app
registration, which usually needs IT to consent to the mail/calendar scopes.
Until that exists, real Outlook data can still reach the app: **Claude** reads
your mail and calendar through its own Microsoft 365 connector and writes the
results here, and ``GraphConnector`` picks them up automatically.

    data/inbox_snapshot.json      -> list of email objects
    data/calendar_snapshot.json   -> list of calendar event objects

Usage
-----
Ask Claude (in a session with the Microsoft 365 connector enabled) something like:

    "Read my last 20 inbox messages and my calendar for the next two weeks, then
     write them to data/inbox_snapshot.json and data/calendar_snapshot.json using
     scripts/refresh_outlook_snapshot.py --format for the shape."

Or run this script directly to write example files / validate existing ones:

    python scripts/refresh_outlook_snapshot.py --format      # print the shapes
    python scripts/refresh_outlook_snapshot.py --validate    # check existing files
    python scripts/refresh_outlook_snapshot.py --sample      # write sample snapshots
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.connectors.graph import (  # noqa: E402
    CALENDAR_SNAPSHOT,
    INBOX_SNAPSHOT,
    _SAMPLE_EVENTS,
    _SAMPLE_INBOX,
    GraphConnector,
)

INBOX_FORMAT = [
    {
        "id": "unique message id",
        "subject": "Subject line",
        "sender_name": "Sender Name",
        "sender_email": "sender@example.com",
        "received": "2026-07-30T08:12:00",
        "body_preview": "First ~200 characters",
        "body": "Full plain-text body",
        "has_attachments": False,
        "web_link": "https://outlook.office.com/... (optional)",
    }
]

CALENDAR_FORMAT = [
    {
        "id": "unique event id",
        "subject": "Meeting title",
        "start": "2026-08-04T10:00:00",
        "end": "2026-08-04T11:00:00",
        "location": "Teams",
        "organizer": {"name": "Organiser", "email": "organiser@example.com"},
        "attendees": [{"name": "Attendee", "email": "attendee@example.com"}],
        "is_online": True,
        "body_preview": "Agenda or invite text",
    }
]


def print_format() -> None:
    print("data/inbox_snapshot.json — a JSON list of:\n")
    print(json.dumps(INBOX_FORMAT, indent=2))
    print("\ndata/calendar_snapshot.json — a JSON list of:\n")
    print(json.dumps(CALENDAR_FORMAT, indent=2))
    print(
        "\nRaw Microsoft Graph JSON is also accepted (a {'value': [...]} wrapper, with "
        "'from.emailAddress' and 'start.dateTime' nesting) — both shapes parse."
    )


def write_sample() -> None:
    INBOX_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    INBOX_SNAPSHOT.write_text(
        json.dumps([m.model_dump() for m in _SAMPLE_INBOX], indent=2)
    )
    CALENDAR_SNAPSHOT.write_text(
        json.dumps([e.model_dump() for e in _SAMPLE_EVENTS], indent=2)
    )
    print(f"Wrote {INBOX_SNAPSHOT}\nWrote {CALENDAR_SNAPSHOT}")


def validate() -> int:
    graph = GraphConnector()
    ok = True
    for label, path in (("inbox", INBOX_SNAPSHOT), ("calendar", CALENDAR_SNAPSHOT)):
        if not path.exists():
            print(f"{label}: no snapshot at {path} (the app will use sample data)")
            continue
        try:
            records = graph.list_inbox() if label == "inbox" else graph.upcoming_events(days=365)
            print(f"{label}: {len(records)} records parsed from {path.name}")
        except Exception as e:  # noqa: BLE001
            print(f"{label}: FAILED to parse {path.name} — {e}")
            ok = False
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format", action="store_true", help="Print the expected JSON shapes")
    parser.add_argument("--sample", action="store_true", help="Write sample snapshot files")
    parser.add_argument("--validate", action="store_true", help="Parse any existing snapshots")
    args = parser.parse_args()

    if args.format:
        print_format()
    elif args.sample:
        write_sample()
    elif args.validate:
        return validate()
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
