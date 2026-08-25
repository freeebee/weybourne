#!/usr/bin/env python3
"""Write the shared-mailbox snapshot the Inbox Signal dashboard reads.

Why this exists
---------------
Same reason as ``refresh_outlook_snapshot.py``: reaching Outlook directly needs
an Entra ID (Azure AD) app registration. Until that exists, real mail still
reaches the app because **Claude** reads it through its own Microsoft 365
connector and writes it here, and ``GraphConnector.list_shared_inbox`` picks it
up automatically whenever ``graph_configured()`` is false.

    data/inbox_signal_snapshot.json   -> list of email objects

The moment an Entra registration exists, this file stops being read and nothing
downstream changes. That is the whole point of the arrangement — transport is
the only thing that differs between the two modes.

Note this is NOT ``data/shared_inbox_snapshot.json``, which looks like the
obvious home for it. That file belongs to ``POST /api/jobs/outlook-refresh``,
which rewrites it with "the 20 most recent messages from the last 7 days" every
time the app opens. Writing here instead means a year of sampled correspondence
is not silently replaced by the last week the next time anyone opens the app.
``GraphConnector.list_shared_inbox`` reads the union of both files, so the two
coexist and neither writer can destroy the other's work.

What to collect
---------------
The dashboard reads the year through **five fixed sampled windows**, defined in
``src/features/inbox_signal/periods.py``. Collect mail for those windows only,
from the **top-level Inbox** of ``wbinvestments@weybourne.co.uk``:

    1–5 Sep 2025 · 1–5 Dec 2025 · 2–6 Mar 2026 · 2–6 Jun 2026 · 22 Jul–5 Aug 2026

Filter hard before writing
--------------------------
The mailbox holds thousands of messages and most are not manager correspondence:
market newsletters (Bloomberg, Reuters), spam-quarantine digests, custodian and
administrator notices, signatory paperwork. **Every message written to this file
costs a model call downstream**, so exclude anything that is not a manager
writing about their fund. Keep:

  * letters, commentaries and CIO updates from a manager or their IR
  * performance estimates and NAV notices naming a fund
  * anything with a track-record attachment

Drop newsletters, quarantine digests, pure administrivia, and internal-only
threads. When genuinely unsure, keep it — the extractor is instructed to emit
nothing rather than invent, so a false positive costs one call, whereas a false
negative silently loses a manager's voice for that window.

Attachments
-----------
Record attachment **metadata** — name, content type, size. Claude's connector
cannot return attachment bytes ("Binary attachment — content cannot be returned
inline"), and that is expected: the sweep records such attachments as *pending*
and parses them once live Graph can fetch them. Do not attempt to inline
base64 content.

Usage
-----
Ask Claude (in a session with the Microsoft 365 connector enabled):

    "Collect wbinvestments@weybourne.co.uk top-level Inbox mail for the five
     windows in src/features/inbox_signal/periods.py, keep only manager
     correspondence, and write data/shared_inbox_snapshot.json using the shape
     from scripts/refresh_shared_inbox_snapshot.py --format."

Or run this directly:

    python scripts/refresh_shared_inbox_snapshot.py --format     # print the shape
    python scripts/refresh_shared_inbox_snapshot.py --windows    # print the windows
    python scripts/refresh_shared_inbox_snapshot.py --validate   # parse what exists
    python scripts/refresh_shared_inbox_snapshot.py --sample     # write a sample file
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.connectors.graph import (  # noqa: E402
    INBOX_SIGNAL_SNAPSHOT,
    _SAMPLE_SHARED_INBOX,
    GraphConnector,
)
from src.features.inbox_signal.periods import PERIODS  # noqa: E402

SHARED_INBOX_FORMAT = [
    {
        "id": "unique message id",
        "subject": "Subject line",
        "sender_name": "Sender Name",
        "sender_email": "sender@example.com",
        "received": "2026-08-04T09:16:00",
        "folder": "Inbox",
        "body_preview": "First ~200 characters",
        "body": "Full plain-text body — the extractor quotes from this, so it "
                "must be the real message text, not a summary",
        "has_attachments": True,
        "attachments": [
            {
                "name": "20260807_MTD Performance Estimate.PDF",
                "content_type": "application/pdf",
                "size": 31349,
            }
        ],
        "web_link": "https://outlook.office.com/... (optional)",
    }
]


def print_format() -> None:
    print("data/shared_inbox_snapshot.json — a JSON list of:\n")
    print(json.dumps(SHARED_INBOX_FORMAT, indent=2))
    print(
        "\nRaw Microsoft Graph JSON is also accepted (a {'value': [...]} wrapper with "
        "'from.emailAddress' nesting) — both shapes parse."
    )
    print(
        "\nbody must be the real message text. The extractor is required to quote "
        "verbatim and will happily quote a summary if you give it one, producing "
        "attributed quotes the manager never wrote."
    )
    print(
        "\nattachments carries metadata only. Bytes are unreachable through the "
        "connector; the sweep records them as pending and parses them once live "
        "Graph access exists."
    )


def print_windows() -> None:
    print("Collect the top-level Inbox of the shared mailbox for these windows:\n")
    for p in PERIODS:
        print(f"  {p.key}  {p.label:<22} {p.sub:<20} "
              f"{p.start:%Y-%m-%d} .. {p.end:%Y-%m-%d}")
    print("\nManager correspondence only — see this script's docstring for what to drop.")


PARTS_DIR = INBOX_SIGNAL_SNAPSHOT.parent / "shared_inbox_parts"


def merge_parts() -> int:
    """Combine data/shared_inbox_parts/*.json into the snapshot.

    Collecting five windows is naturally split across several passes (and, in
    practice, across parallel workers), so each writes its own part file and
    this merges them. De-duplicates on message id, because windows can be
    re-collected independently and the same message must not be extracted — and
    paid for — twice under two different entries.
    """
    if not PARTS_DIR.exists():
        print(f"no parts directory at {PARTS_DIR}")
        return 1
    merged: dict[str, dict] = {}
    for f in sorted(PARTS_DIR.glob("*.json")):
        try:
            records = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"{f.name}: FAILED to read — {e}")
            return 1
        if not isinstance(records, list):
            print(f"{f.name}: expected a JSON list, got {type(records).__name__}")
            return 1
        for r in records:
            mid = str(r.get("id") or "")
            if mid:
                merged[mid] = r
        print(f"{f.name}: {len(records)} records")

    out = sorted(merged.values(), key=lambda r: r.get("receivedDateTime") or "")
    INBOX_SIGNAL_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    INBOX_SIGNAL_SNAPSHOT.write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    size_kb = INBOX_SIGNAL_SNAPSHOT.stat().st_size / 1024
    print(f"\nWrote {INBOX_SIGNAL_SNAPSHOT} — {len(out)} unique messages, {size_kb:.0f} KB")
    return 0


def write_sample() -> None:
    INBOX_SIGNAL_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    INBOX_SIGNAL_SNAPSHOT.write_text(
        json.dumps([m.model_dump(mode="json") for m in _SAMPLE_SHARED_INBOX], indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {INBOX_SIGNAL_SNAPSHOT}")


def validate() -> int:
    if not INBOX_SIGNAL_SNAPSHOT.exists():
        print(f"no snapshot at {INBOX_SIGNAL_SNAPSHOT} (the app will use sample data)")
        return 0
    graph = GraphConnector()
    if graph.live:
        print("Graph is configured — the snapshot is ignored in live mode.")
    ok = True
    total = 0
    for p in PERIODS:
        try:
            msgs = graph.list_shared_inbox(top=500, start=p.start, end=p.end)
        except Exception as e:  # noqa: BLE001
            print(f"{p.key}: FAILED — {e}")
            ok = False
            continue
        withatt = sum(1 for m in msgs if m.attachments)
        senders = len({m.sender_email.lower() for m in msgs if m.sender_email})
        total += len(msgs)
        print(f"{p.key}  {p.label:<22} {len(msgs):>4} messages  "
              f"{senders:>3} senders  {withatt:>3} with attachments")
    print(f"\n{total} messages across the five windows.")
    if total == 0:
        print("Nothing matched — check the 'received' timestamps fall inside the windows.")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format", action="store_true", help="Print the expected JSON shape")
    parser.add_argument("--windows", action="store_true", help="Print the sampled windows")
    parser.add_argument("--merge", action="store_true",
                        help="Combine data/shared_inbox_parts/*.json into the snapshot")
    parser.add_argument("--sample", action="store_true", help="Write a sample snapshot file")
    parser.add_argument("--validate", action="store_true", help="Parse and summarise the snapshot")
    args = parser.parse_args()

    if args.format:
        print_format()
    elif args.windows:
        print_windows()
    elif args.merge:
        return merge_parts()
    elif args.sample:
        write_sample()
    elif args.validate:
        return validate()
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
