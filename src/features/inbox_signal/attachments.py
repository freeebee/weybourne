"""Decide what an attachment is, and parse it when the bytes can be had.

Pre-Entra this module mostly records intent. Claude's Microsoft 365 connector
returns attachment metadata but refuses the bytes, so a track record arriving
today is marked ``pending``: the dashboard can say it arrived and from whom, the
watchlist can flag a manager who sent numbers nobody has read, and the queue
drains itself once live Graph access exists. Nothing about the calling code
changes at that point — only whether ``graph.attachments_available()`` is true.

Classification is heuristic and free. A model call to disambiguate would be
reasonable in principle, but it would be spent deciding whether to spend a
second, larger call — and pre-Entra it could not act on the answer either way.
When live parsing lands and misclassification proves to be a real problem, this
is the place to add that escalation.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Optional

# Extensions ``analyse_file`` can actually read (src/features/track_record.py).
PARSEABLE = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".pdf"}

# Filename signals that a file carries a return series rather than prose.
_TRACK_HINTS = re.compile(
    r"track[\s_-]?record|performance|returns?\b|\bnav\b|\bmtd\b|\bytd\b|"
    r"tear[\s_-]?sheet|estimate|monthly|factsheet|fact[\s_-]?sheet",
    re.IGNORECASE,
)

# Signals it is paperwork, not performance. Checked first — "Performance Fee
# Schedule" and "Signatory List with NAV summary" both trip the hints above.
_ADMIN_HINTS = re.compile(
    r"signatory|kyc|aml|invoice|w-?9|w-?8|subscription|redemption[\s_-]?form|"
    r"capital[\s_-]?call|drawdown|wire|swift|confirmation|agreement|"
    r"prospectus|ppm|side[\s_-]?letter|tax|k-?1|audit",
    re.IGNORECASE,
)

TRACK_RECORD = "track_record"
DOCUMENT = "document"
IGNORE = "ignore"


def classify(name: str, content_type: str = "", size: int = 0) -> str:
    """What kind of attachment this is, from metadata alone.

    Returns ``TRACK_RECORD`` (worth parsing for a return series), ``DOCUMENT``
    (readable but prose — the body extraction already covers the manager's
    view), or ``IGNORE`` (images, signatures, unparseable formats).
    """
    suffix = Path(name or "").suffix.lower()
    if suffix not in PARSEABLE:
        return IGNORE
    # Inline signature images and logos routinely arrive as tiny files.
    if size and size < 8_000 and suffix == ".pdf":
        return IGNORE
    if _ADMIN_HINTS.search(name or ""):
        return IGNORE
    if suffix in {".xlsx", ".xlsm", ".xls", ".csv", ".tsv"}:
        # A spreadsheet from a manager is a return series far more often than
        # not, and it is the one format that is cheap and reliable to parse.
        return TRACK_RECORD
    if _TRACK_HINTS.search(name or ""):
        return TRACK_RECORD
    return DOCUMENT


def parse_track_record(client, graph, message_id: str, attachment, mailbox: str = ""):
    """Fetch and parse one attachment into a ``TrackRecord``.

    Raises ``AttachmentBytesUnavailable`` when the transport cannot supply the
    file, which is the expected pre-Entra path and is caught by the sweep.
    """
    from src.features.track_record import analyse_file

    if not graph.attachments_available():
        raise AttachmentBytesUnavailable(
            "attachment bytes need live Graph access (Entra app registration)")

    data = graph.download_attachment(message_id, attachment.id, user=mailbox or None)
    suffix = Path(attachment.name or "attachment").suffix or ".xlsx"
    tmp = Path(tempfile.gettempdir()) / f"inbox-signal-att{suffix}"
    tmp.write_bytes(data)
    try:
        return analyse_file(client, tmp)
    finally:
        # The bytes are a manager's confidential performance data; there is no
        # reason for them to outlive the parse in a shared temp directory.
        try:
            tmp.unlink()
        except OSError:
            pass


class AttachmentBytesUnavailable(RuntimeError):
    """The attachment is known but its content cannot be fetched in this mode."""


def plan_for_message(email, graph) -> list[dict]:
    """What to do with each attachment on a message, without doing it.

    Separating the decision from the action keeps the sweep readable and makes
    this testable with no transport at all.
    """
    out = []
    can_fetch = graph.attachments_available()
    for att in email.attachments:
        kind = classify(att.name, att.content_type, att.size)
        if kind == TRACK_RECORD:
            action = "parse" if can_fetch else "pending"
        else:
            action = "ignore"
        out.append({
            "name": att.name,
            "size": att.size,
            "content_type": att.content_type,
            "attachment_id": att.id,
            "kind": kind,
            "action": action,
        })
    return out
