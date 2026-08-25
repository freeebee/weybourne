"""Deterministic derivation: window math, duplicate detection, stats.

Everything numeric lives here, not in the model — see the package docstring.
Every function is pure (no I/O), which is what makes this the easiest layer
to unit test directly.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

DECLINED_RE = re.compile(r"\(Declined\)$")
TEMPLATE_RE = re.compile(r"^(note template|template)\b", re.I)

_LEADING = [
    r"^meeting with\s+", r"^call with\s+", r"^reference call( with)?\s*",
    r"^follow[- ]up( call)?( with)?\s*", r"^intro(duction)? call( with)?\s*",
    r"^email (from|with)\s+", r"^note (re|on)\s+",
]
_FILLER = re.compile(r"\b(update|call|meeting|note)\b")
_VENUES = re.compile(r"\b(zoom|teams|webex|office|hq)\b")

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def prior_week(d: Optional[date] = None) -> dict:
    """Monday-Friday of the week before the one containing ``d`` (default:
    today) — the week that has just finished, so the briefing reports on
    what actually happened rather than a mostly-unelapsed week ahead."""
    d = d or date.today()
    monday = d - timedelta(days=d.weekday() + 7)
    friday = monday + timedelta(days=4)
    return {"start": monday.isoformat(), "end": friday.isoformat()}


def window_label(window: dict) -> str:
    a = datetime.strptime(window["start"], "%Y-%m-%d").date()
    b = datetime.strptime(window["end"], "%Y-%m-%d").date()
    if a.month == b.month and a.year == b.year:
        return f"{a.day} – {b.day} {_MONTHS[b.month - 1]} {b.year}"
    return f"{a.day} {_MONTHS[a.month - 1]} – {b.day} {_MONTHS[b.month - 1]} {b.year}"


def iso_week_ref(window: dict) -> str:
    """Letterhead ref, e.g. 'WB-WR-2026-W32' — the ISO week number of the
    window's end date."""
    end = datetime.strptime(window["end"], "%Y-%m-%d").date()
    iso_year, iso_week, _ = end.isocalendar()
    return f"WB-WR-{iso_year}-W{iso_week:02d}"


def subject_key(title: str) -> str:
    """A note title normalised to its comparable core, for duplicate
    detection. Keeps parenthetical content — it disambiguates genuinely
    distinct meetings sharing a subject (three different Trivest interviews,
    say) — while stripping leading verbs, known venues and filler words so
    'Call with Axiom Asia' and 'Meeting with Axiom Asia' collapse together."""
    t = (title or "").lower().strip()
    for pat in _LEADING:
        t = re.sub(pat, "", t)
    m = re.match(r"^(.*?)(\s*\([^)]*\))?$", t)
    base, paren = m.group(1), (m.group(2) or "")
    base = _VENUES.sub("", _FILLER.sub("", base))
    return re.sub(r"[^a-z0-9]+", "", base) + re.sub(r"[^a-z0-9]+", "", paren)


def content_length(note: dict) -> int:
    return len(note.get("thoughts") or "") + len(note.get("body") or "")


def note_content(note: dict) -> str:
    """The text to feed the model for one note — property first, body as
    backstop, never both in full if the body already contains the summary."""
    t = (note.get("thoughts") or "").strip()
    b = (note.get("body") or "").strip()
    if t and b and t[:80] in b:
        return b   # body already contains the summary — avoid duplicating it
    return "\n\n".join(x for x in (t, b) if x)


def find_duplicate_sets(notes: list[dict]) -> list[dict]:
    """Groups notes whose titles share a subject_key, skipping templates.
    Each group's ``keeper`` is the note with the most written content — the
    one to feed the model; the rest are the empty/thin half of a duplicate
    pair and are dropped before the notes ever reach the prompt."""
    groups: dict[str, list[dict]] = {}
    for n in notes:
        if TEMPLATE_RE.match(n.get("title") or ""):
            continue
        k = subject_key(n.get("title") or "")
        if k:
            groups.setdefault(k, []).append(n)
    return [
        {"key": k, "notes": g, "keeper": max(g, key=content_length)}
        for k, g in groups.items() if len(g) > 1
    ]


def declined_funds(funds: list[dict]) -> list[dict]:
    """Every fund whose status marks it declined, with its real record attached.

    Names alone were enough while declined funds were a footnote. They are not
    enough now that each one is a row carrying its status and focus, so this
    returns the records themselves — read straight off Notion, nothing inferred.
    """
    return sorted((f for f in funds
                   if f.get("status") and DECLINED_RE.search(f["status"])),
                  key=lambda f: f["name"])


def declined_names(funds: list[dict]) -> list[str]:
    return [f["name"] for f in declined_funds(funds)]


def focus_label(fund: dict) -> str:
    """A focus label built from the fund's own Notion fields.

    The model writes this line when it has read something worth writing; when
    it has not, the fund record still knows what it invests in. Geography
    first, then asset class, which is the order the desk says them in. Empty
    when the record carries neither — a blank cell is honest, and a label
    invented to fill the column is not.
    """
    parts = [*(fund.get("geographic_focus") or []), *(fund.get("asset_class") or [])]
    return " · ".join(p.strip().upper() for p in parts if p and p.strip())


def derive_stats(raw: dict) -> dict:
    """raw = {"window", "notes", "funds", "contacts"} -> WeekStats dict.
    The one function every count in the review comes from — see the package
    docstring for why the model is never asked to do this itself."""
    notes, funds, contacts = raw["notes"], raw["funds"], raw["contacts"]

    dup_sets = find_duplicate_sets(notes)
    surplus = sum(len(s["notes"]) - 1 for s in dup_sets)
    templates = sum(1 for n in notes if TEMPLATE_RE.match(n.get("title") or ""))
    emails = sum(1 for n in notes if n.get("note_type") == "Email")

    def by_type(t: str) -> int:
        return sum(1 for n in notes if n.get("note_type") == t
                   and not TEMPLATE_RE.match(n.get("title") or ""))

    employer_ids = {i for c in contacts for i in c.get("employer_ids", []) if i}
    start = raw["window"]["start"]

    return {
        "engagements": len(notes) - surplus - templates - emails,
        "note_records": len(notes),
        "duplicate_sets": len(dup_sets),
        "gp_meetings": by_type("GP Meeting"),
        "lp_meetings": by_type("LP Meeting"),
        "internal_meetings": by_type("Internal"),
        "service_meetings": by_type("Service Provider"),
        "declined": len(declined_names(funds)),
        "new_fund_records": sum(1 for f in funds
                                if (f.get("created_time") or "")[:10] >= start),
        "funds_touched": len(funds),
        "new_contacts": len(contacts),
        "firms_represented": len(employer_ids),
    }
