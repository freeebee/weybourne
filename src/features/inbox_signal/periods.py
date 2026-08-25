"""The five sampled windows the dashboard reads the year through.

Why sample rather than read everything: the shared mailbox holds thousands of
messages, the large majority of them newsletters, custodian notices and
signatory administration. Reading all of it would cost a model call per message
to learn mostly nothing. Five short windows spread across the year answer the
question the dashboard actually asks — *what was the desk saying then, and how
has that moved since* — at a fraction of that.

The windows are **pinned constants, not derived from today's date**. Two
reasons. The dashboard is a record of a specific year (Sep 2025 – Aug 2026) and
must render the same way next month as it does now; and a sliding window would
silently invalidate every stored extraction each time it moved, since the
manifest keys work off message ids inside a fixed range.

``n`` (managers heard from) and ``total`` (messages seen) are deliberately
*not* here — those are counted from what the sweep actually found, not asserted
up front.
"""
from __future__ import annotations

import datetime as dt
from typing import NamedTuple


class Period(NamedTuple):
    key: str
    label: str      # full, for headings: "1–5 Sep 2025"
    short: str      # axis/tab label: "Sep 25"
    sub: str        # relative gloss: "12 months back"
    start: dt.datetime
    end: dt.datetime


def _window(y: int, m: int, d1: int, y2: int, m2: int, d2: int) -> tuple[dt.datetime, dt.datetime]:
    """Inclusive day range as [00:00:00, 23:59:59] so end-of-day mail is kept."""
    return (dt.datetime(y, m, d1, 0, 0, 0),
            dt.datetime(y2, m2, d2, 23, 59, 59))


PERIODS: list[Period] = [
    Period("p0", "1–5 Sep 2025", "Sep 25", "12 months back",
           *_window(2025, 9, 1, 2025, 9, 5)),
    Period("p1", "1–5 Dec 2025", "Dec 25", "9 months back",
           *_window(2025, 12, 1, 2025, 12, 5)),
    Period("p2", "2–6 Mar 2026", "Mar 26", "5 months back",
           *_window(2026, 3, 2, 2026, 3, 6)),
    Period("p3", "2–6 Jun 2026", "Jun 26", "2 months back",
           *_window(2026, 6, 2, 2026, 6, 6)),
    # The current fortnight is wider than the historical samples on purpose:
    # it is the one window read for "what is happening now" rather than "what
    # was being said then", so it needs enough traffic to be representative.
    Period("p4", "22 Jul – 5 Aug 2026", "Now", "Current fortnight",
           *_window(2026, 7, 22, 2026, 8, 5)),
]

BY_KEY = {p.key: p for p in PERIODS}

# The correspondence window the dashboard covers, as shown on the splash.
# Distinct from the manager return window (Aug 2025 – Jul 2026) used by
# factor_correlation — the two are different spans on purpose and neither
# should be nudged to match the other.
COVERAGE_LABEL = "Sep 2025 – Aug 2026"


def period_for(received: str) -> Period | None:
    """Which sampled window an ISO-8601 timestamp falls in, if any."""
    if not received:
        return None
    try:
        moment = dt.datetime.fromisoformat(received.strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(dt.timezone.utc).replace(tzinfo=None)
    for p in PERIODS:
        if p.start <= moment <= p.end:
            return p
    return None
