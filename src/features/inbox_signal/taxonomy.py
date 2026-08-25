"""The vocabulary the dashboard reasons in: stances, themes, severities.

Seeded from the themes that actually recurred in this mailbox over the sampled
year. It is a **seed, not a cap**: the extractor may propose a theme outside the
list, and ``normalise_theme`` keeps it rather than forcing it into an
ill-fitting bucket. A fixed enum would quietly relabel next quarter's real
concern as whatever 2025-26 happened to care about, which is the sort of error
nobody notices because the chart still looks fine.

Stance is deliberately four coarse values rather than a score. The evidence is
a manager's prose, which supports "constructive" or "cautious" honestly and
does not support 0.62.
"""
from __future__ import annotations

# Order matters — it is the display order on the stance matrix and legend.
STANCES = ["constructive", "cautious", "negative", "neutral"]

STANCE_LABELS = {
    "constructive": "Constructive",
    "cautious": "Cautious",
    "negative": "Negative",
    "neutral": "Neutral",
}

# Theme id -> label. Ids are stable; labels are display-only.
THEMES: dict[str, str] = {
    "ai": "AI unwind",
    "degross": "Degrossing & leverage",
    "semis": "Semiconductors",
    "real": "Real assets & hedges",
    "iran": "Iran & Hormuz",
    "vol": "Dispersion vs index vol",
    "crude": "Crude & long rates",
    "liquidity": "Venture liquidity",
    "china": "China",
    "digital": "Digital assets",
    "cat": "Cat risk",
    "power": "Onsite power",
    "credit": "Private credit",
}

# Watchlist severities, ranked most urgent first.
SEVERITIES = ["urgent", "attention", "watch"]

SEVERITY_LABELS = {"urgent": "Urgent", "attention": "Attention", "watch": "Watch"}


def normalise_stance(value: str) -> str:
    """Coerce to a known stance, defaulting to neutral.

    Neutral is the right default for an unrecognised value: it is the reading
    that asserts least about a manager who may simply have been reporting.
    """
    v = (value or "").strip().lower()
    return v if v in STANCES else "neutral"


def normalise_theme(value: str) -> str:
    """Slug a theme id, keeping unknown ones rather than discarding them."""
    v = (value or "").strip().lower().replace(" ", "-")
    return v or ""


def theme_label(theme_id: str) -> str:
    """Display label, falling back to a tidied version of an unknown id."""
    if theme_id in THEMES:
        return THEMES[theme_id]
    return theme_id.replace("-", " ").replace("_", " ").capitalize()
