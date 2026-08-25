"""Turn stored correspondence into the three tabs' payloads.

Everything here is plain aggregation over what the extractor already found — no
model calls, no network. That is deliberate: these views are recomputed on every
page load, and anything expensive would either need its own cache or would
quietly make opening a tab cost money.

The harder, genuinely model-derived views (a manager reversing their position
across windows; two managers answering the same question oppositely) are not
computed here for exactly that reason — they need cross-document reasoning, so
they live in ``cross_pass.py`` and are paid for once. What this module does with
them is read the verdicts already stored and say honestly how much of the ground
has been covered: ``cross_view`` counts the candidate pairs (free, by the same
counting as everything else here) and reports how many are still unjudged, so a
thin section reads as unfinished work rather than as a quiet desk.

A rule observed throughout: **absence is reported, not hidden.** A theme nobody
mentioned in a window is a zero, not a gap; a manager who went quiet is a
watchlist entry, not a missing row.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.features import track_record_store
from src.features.inbox_signal import cross_pass
from src.features.inbox_signal import cross_store as cs
from src.features.inbox_signal import manifest as mf
from src.features.inbox_signal import retheme
from src.features.inbox_signal import store
from src.features.inbox_signal.periods import COVERAGE_LABEL, PERIODS
from src.features.inbox_signal.taxonomy import (
    SEVERITIES, STANCES, normalise_stance, theme_label,
)

# A month at or below this is a drawdown worth a manager explaining.
_DRAWDOWN_PCT = -5.0
# Quotes below this count means the manager reported without commenting.
_SILENT_QUOTES = 1
# A month needs at least this many reporting managers before a cross-sectional
# reading (best/median/worst) says anything about the desk rather than about
# whoever happened to write that month.
_MIN_MONTH_REPORTERS = 3
# Where every strategy group's index starts, at the beginning of the first
# month any of them reported.
_INDEX_BASE = 100
# An index is a path, and one point is not a path. A group reporting a single
# month would be drawn as a flat line across the whole axis with one step in
# it — indistinguishable in weight from a group that reported nine, and read
# side by side with them. Those groups are named beneath the chart instead.
_MIN_INDEX_MONTHS = 2


def _period_index() -> dict[str, int]:
    return {p.key: i for i, p in enumerate(PERIODS)}


def periods_view(letters: list[dict]) -> list[dict]:
    """The five windows with what was actually found in each."""
    idx = _period_index()
    per: list[dict] = [{
        "key": p.key, "label": p.label, "short": p.short, "sub": p.sub,
        "orgs": 0, "letters": 0, "quotes": 0,
    } for p in PERIODS]
    orgs: dict[int, set] = {i: set() for i in range(len(PERIODS))}

    for letter in letters:
        i = idx.get(letter.get("period"))
        if i is None:
            continue
        per[i]["letters"] += 1
        per[i]["quotes"] += len(letter.get("quotes") or [])
        orgs[i].add(letter.get("org", ""))
    for i, slot in enumerate(per):
        slot["orgs"] = len(orgs[i] - {""})
    return per


def themes_view(letters: list[dict]) -> list[dict]:
    """Each theme's frequency across the five windows, most-discussed first.

    ``stances`` is a **breakdown**, not a verdict, and that distinction matters.
    The stance the extractor records is a letter's overall posture toward risk;
    it is not a judgement on any one theme within that letter. Collapsing it to
    a single majority produced labels like "AI unwind — Constructive", which
    reads as the desk being constructive about an unwind. A manager can be
    constructive overall precisely because they think the unwind is a buying
    opportunity, and can equally be constructive while flagging it as the risk.
    Showing "3 constructive · 1 cautious" says exactly what is known — how the
    managers raising this theme are positioned — and claims nothing more.
    """
    idx = _period_index()
    counts: dict[str, list[int]] = {}
    stances: dict[str, list[str]] = {}

    for letter in letters:
        i = idx.get(letter.get("period"))
        if i is None:
            continue
        for theme in letter.get("themes") or []:
            counts.setdefault(theme, [0] * len(PERIODS))[i] += 1
            stances.setdefault(theme, []).append(normalise_stance(letter.get("stance")))

    out = []
    for theme, series in counts.items():
        votes = stances.get(theme, [])
        out.append({
            "id": theme,
            "label": theme_label(theme),
            "stances": {s: votes.count(s) for s in STANCES if votes.count(s)},
            "series": series,
            "total": sum(series),
        })
    out.sort(key=lambda t: (-t["total"], t["label"]))
    return out


def stance_by_org(letters: list[dict]) -> list[dict]:
    """Each organisation's stance in each window, or None where they were silent.

    None is load-bearing: it distinguishes "neutral — they wrote and had no
    view" from "we did not hear from them", which look identical if silence is
    coerced to a value.
    """
    idx = _period_index()
    by_org: dict[str, list[Optional[str]]] = {}
    for letter in letters:
        i = idx.get(letter.get("period"))
        org = letter.get("org")
        if i is None or not org:
            continue
        row = by_org.setdefault(org, [None] * len(PERIODS))
        row[i] = normalise_stance(letter.get("stance"))
    return [{"org": org, "stances": row} for org, row in sorted(by_org.items())]


def stance_matrix(letters: list[dict], max_themes: int = 6) -> dict:
    """Organisation × theme grid: "+" constructive, "~" mixed or cautious, "" silent."""
    themes = [t["id"] for t in themes_view(letters)[:max_themes]]
    labels = [theme_label(t) for t in themes]

    grid: dict[str, dict[str, list[str]]] = {}
    for letter in letters:
        org = letter.get("org")
        if not org:
            continue
        stance = normalise_stance(letter.get("stance"))
        for theme in letter.get("themes") or []:
            if theme in themes:
                grid.setdefault(org, {}).setdefault(theme, []).append(stance)

    rows = []
    for org in sorted(grid):
        cells = []
        for theme in themes:
            votes = grid[org].get(theme, [])
            if not votes:
                cells.append("")
            elif votes.count("constructive") > len(votes) / 2:
                cells.append("+")
            else:
                cells.append("~")
        rows.append({"org": org, "cells": cells})
    return {"cols": labels, "rows": rows}


def voices_view(letters: list[dict]) -> list[dict]:
    """The correspondence log: one entry per quote, newest first.

    ``themes`` are the quote's own where the extractor recorded them, and the
    letter's only as a fallback — with ``themes_are_the_letters`` saying which.
    The distinction is not cosmetic. A letter ranging over AI, semiconductors
    and the Gulf had every one of those tags printed under a quote about one
    software company's guidance reset, so a passage that mentions none of them
    was labelled 'Iran & Hormuz'. Letter-level themes describe a letter; printed
    against a single passage they assert something about that passage that
    nobody established.
    """
    out = []
    for letter in letters:
        for q in letter.get("quotes") or []:
            # `None` means no extractor ever looked at this quote; `[]` means one
            # looked and found none of the themes present. Only the first is a
            # reason to fall back to the letter's — treating an empty list as
            # "unknown" reinstates exactly the bug this fixes, because the quotes
            # that engage no theme are the ones the letter's tags libel worst.
            own = q.get("themes")
            out.append({
                "period": letter.get("period", ""),
                "org": letter.get("org", ""),
                "person": letter.get("person", ""),
                "date": letter.get("date", ""),
                "stance": normalise_stance(letter.get("stance")),
                "themes": (letter.get("themes") or []) if own is None else own,
                "themes_are_the_letters": own is None,
                "quote": q.get("quote", ""),
                "context": q.get("context", ""),
                "source": letter.get("source", ""),
                "web_link": letter.get("web_link", ""),
            })
    out.sort(key=lambda v: v["date"], reverse=True)
    return out


def disclosed_view(letters: list[dict]) -> list[dict]:
    out = []
    for letter in letters:
        for d in letter.get("disclosed") or []:
            out.append({"who": letter.get("org", ""), "value": d.get("value", ""),
                        "label": d.get("label", ""), "note": d.get("note", ""),
                        "date": letter.get("date", "")})
    out.sort(key=lambda d: d["date"], reverse=True)
    return out


def reported_returns_view(letters: list[dict]) -> list[dict]:
    """Every month a manager put a number to, newest first."""
    out = []
    for letter in letters:
        for r in letter.get("reported_returns") or []:
            out.append({"org": letter.get("org", ""), "fund": r.get("fund", ""),
                        "month": r.get("month", ""), "pct": r.get("pct"),
                        "basis": r.get("basis", ""), "source": letter.get("source", ""),
                        "date": letter.get("date", "")})
    out.sort(key=lambda r: (r["month"], r["org"]), reverse=True)
    return out


def standouts_and_strained(letters: list[dict], limit: int = 6) -> dict:
    """Best and worst reported months, from figures managers actually stated.

    Deduplicated on manager, fund, month and figure. The same number reaches
    the store from more than one letter routinely — a monthly estimate followed
    by the confirmed final, a letter forwarded twice under different ids — and
    each copy is a legitimate record of what was said. As a *ranking*, though,
    they are one fact, and leaving them in filled the top of the list with one
    manager's single month repeated three times.
    """
    rows = [r for r in reported_returns_view(letters) if isinstance(r.get("pct"), (int, float))]
    seen: set[tuple] = set()
    unique = []
    for r in rows:
        key = (r.get("org", ""), r.get("fund", ""), r.get("month", ""), r["pct"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    best = sorted(unique, key=lambda r: r["pct"], reverse=True)[:limit]
    worst = sorted(unique, key=lambda r: r["pct"])[:limit]
    return {"standouts": best, "strained": worst}


def _numeric_returns(letters: list[dict]) -> list[dict]:
    return [r for r in reported_returns_view(letters)
            if isinstance(r.get("pct"), (int, float))]


def _manager_months(letters: list[dict]) -> list[dict]:
    """One row per manager per month — the unit every cross-section counts in.

    Managers report per fund, and several report two or three vehicles for the
    same month. Counting raw figures made a single manager's three share
    classes look like three managers: July 2025 read as a three-manager month
    whose best, median and worst were all the same firm, which is not a
    cross-section of anything. Where a manager states several funds for one
    month they are averaged into one equal-weighted reading, so the phrase
    "managers reporting" means what it says.
    """
    merged: dict[tuple[str, str], dict] = {}
    for r in _numeric_returns(letters):
        key = (r.get("org", ""), r["month"])
        slot = merged.setdefault(key, {"org": key[0], "month": key[1],
                                       "pcts": [], "funds": []})
        slot["pcts"].append(r["pct"])
        if r.get("fund"):
            slot["funds"].append(r["fund"])
    out = []
    for slot in merged.values():
        out.append({
            "org": slot["org"], "month": slot["month"],
            "pct": round(sum(slot["pcts"]) / len(slot["pcts"]), 4),
            "funds": sorted(set(slot["funds"])),
            "figures": len(slot["pcts"]),
        })
    out.sort(key=lambda r: (r["month"], r["org"]))
    return out


def _by_month(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["month"], []).append(r)
    return out


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _cumulative(pcts: list[float]) -> float:
    """Compounded return over the months given, in per cent."""
    total = 1.0
    for p in pcts:
        total *= 1 + p / 100
    return round((total - 1) * 100, 3)


def _max_drawdown(pcts: list[float]) -> float:
    """Largest peak-to-trough fall along the compounded path, in per cent.

    Over reported months ONLY, and those are sparse — a manager who stated four
    months of a year has a drawdown across those four readings, not across the
    year. The caller carries the reported count next to it so the figure is read
    for what it is.
    """
    if not pcts:
        return 0.0
    level, peak, worst = 1.0, 1.0, 0.0
    for p in pcts:
        level *= 1 + p / 100
        peak = max(peak, level)
        worst = min(worst, level / peak - 1)
    return round(worst * 100, 3)


def manager_tracks_view(letters: list[dict], funds: Optional[list] = None,
                        group_of: Optional[dict] = None) -> dict:
    """Every manager's reported months, grouped by strategy, best total first.

    The per-manager counterpart to ``strategy_groups_view``: that one asks how a
    mandate did, this one asks who inside it did it. One row per manager, with
    the months they actually stated, what those compound to, their worst single
    month, the drawdown across the path they reported, and the stance of each
    letter behind it.

    Every figure here is computed from months a manager put in writing, and
    ``reported`` says how many that was. The distinction matters more than
    usual: a twelve-month total built from four reported months is not a
    twelve-month return, and the column that says "4 reported" is what stops it
    being read as one.
    """
    rows = _manager_months(letters)
    if group_of is None:
        group_of = _group_by_org(rows, funds or [])

    # Stance per window, so the tone column reads as a row of five boxes in
    # sampled order rather than as one averaged mood.
    #
    # Each box carries the correspondence behind it, because a stance is a
    # reading of a letter and the letter is the evidence for it — a coloured
    # square that cannot be opened asks to be taken on trust, which is the one
    # thing this page does not do. Where a manager wrote more than once in a
    # window every letter is kept: the square takes the latest stance, as it
    # always has, and the drawer shows them all rather than quietly picking
    # one.
    idx = _period_index()
    stances: dict[str, list] = {}
    for letter in sorted(letters, key=lambda x: x.get("date") or ""):
        org = (letter.get("org") or "").strip()
        i = idx.get(letter.get("period"))
        if not org or i is None:
            continue
        slot = stances.setdefault(org, [None] * len(PERIODS))
        cell = slot[i] or {"stance": "", "letters": []}
        cell["stance"] = normalise_stance(letter.get("stance"))
        cell["letters"].append({
            "date": letter.get("date", ""),
            "person": letter.get("person", ""),
            "source": letter.get("source", ""),
            "web_link": letter.get("web_link", ""),
            "stance": normalise_stance(letter.get("stance")),
            "quotes": [{"quote": q.get("quote", ""), "context": q.get("context", "")}
                       for q in (letter.get("quotes") or [])],
        })
        slot[i] = cell

    by_org: dict[str, list[dict]] = {}
    for r in rows:
        by_org.setdefault(r["org"], []).append(r)

    managers = []
    for org, rs in by_org.items():
        rs = sorted(rs, key=lambda r: r["month"])
        pcts = [r["pct"] for r in rs]
        funds_named = sorted({f for r in rs for f in (r.get("funds") or [])})
        managers.append({
            "org": org,
            "group": group_of.get(org, ""),
            "mandate": ", ".join(funds_named[:2]),
            "months": [{"month": r["month"], "pct": r["pct"]} for r in rs],
            "reported": len(rs),
            "total": _cumulative(pcts),
            "worst": round(min(pcts), 3),
            "best": round(max(pcts), 3),
            "max_drawdown": _max_drawdown(pcts),
            "tone": stances.get(org, [None] * len(PERIODS)),
        })
    managers.sort(key=lambda m: -m["total"])

    grouped: dict[str, list[dict]] = {}
    for m in managers:
        grouped.setdefault(m["group"] or "", []).append(m)

    groups = []
    for name in sorted(k for k in grouped if k):
        rs = grouped[name]
        groups.append({
            "group": name,
            "managers": rs,
            "manager_count": len(rs),
            "mean_total": round(sum(m["total"] for m in rs) / len(rs), 3),
        })
    groups.sort(key=lambda g: -g["mean_total"])
    return {
        "groups": groups,
        "unclassified": grouped.get("", []),
        "periods": [{"key": p.key, "short": p.short} for p in PERIODS],
    }


def _group_series(letters: list[dict], funds: Optional[list], fn,
                  group_of: Optional[dict] = None) -> dict:
    """Run a cross-section over every manager, then again per strategy group.

    The charts carry a group filter, and the honest way to build it is to run
    the same reading over a subset rather than to slice a finished result: a
    month that was too thin across the whole desk may be thinner still inside
    one mandate, and only re-running applies that test where it belongs.
    """
    if group_of is None:
        group_of = _group_by_org(_manager_months(letters), funds or [])
    orgs_by_group: dict[str, set] = {}
    for org, group in group_of.items():
        orgs_by_group.setdefault(group, set()).add(org)

    out = {"all": fn(letters), "by_group": {}}
    for group, orgs in sorted(orgs_by_group.items()):
        subset = [x for x in letters if (x.get("org") or "").strip() in orgs]
        result = fn(subset)
        if result.get("series"):
            out["by_group"][group] = {**result, "managers": len(orgs)}
    return out


def dispersion_view(letters: list[dict]) -> dict:
    """Best, median and worst reported month, per month.

    Runs on figures managers stated in writing, so it needs no stored track
    records — the spread between the best and worst manager in a month is
    readable from the letters alone.

    Months with fewer than ``_MIN_MONTH_REPORTERS`` are excluded rather than
    drawn thin: a "spread" between two managers is not a spread, and a chart
    that silently mixes a 12-manager month with a 2-manager one invites exactly
    the wrong reading. The count of excluded months is returned so the omission
    is visible instead of tacit.
    """
    rows = _manager_months(letters)
    months = _by_month(rows)
    series, thin = [], 0
    for month in sorted(months):
        pcts = [r["pct"] for r in months[month]]
        if len(pcts) < _MIN_MONTH_REPORTERS:
            thin += 1
            continue
        best = max(months[month], key=lambda r: r["pct"])
        worst = min(months[month], key=lambda r: r["pct"])
        series.append({
            "month": month, "reporters": len(pcts),
            "best": best["pct"], "best_org": best["org"],
            "worst": worst["pct"], "worst_org": worst["org"],
            "median": round(_median(pcts), 3),
            "spread": round(best["pct"] - worst["pct"], 3),
        })
    return {"series": series, "months_too_thin": thin,
            "min_reporters": _MIN_MONTH_REPORTERS}


def breadth_view(letters: list[dict]) -> dict:
    """How many of the managers who reported a month were positive in it.

    The plainest cross-sectional reading the letters support: not how much was
    made, but how widely. Every month that carries a figure appears here,
    including thin ones — a breadth of 1-of-1 is still true, where a *spread*
    of one manager is not — with the reporter count alongside so a two-manager
    month is never mistaken for a verdict on the desk.
    """
    rows = _manager_months(letters)
    months = _by_month(rows)
    series = []
    for month in sorted(months):
        pcts = [r["pct"] for r in months[month]]
        up = sum(1 for p in pcts if p > 0)
        series.append({
            "month": month, "reporters": len(pcts), "positive": up,
            "negative": sum(1 for p in pcts if p < 0),
            "flat": sum(1 for p in pcts if p == 0),
            "share": round(up / len(pcts), 4),
        })
    return {"series": series}


def strategy_groups_view(letters: list[dict], funds: Optional[list] = None,
                         group_of: Optional[dict] = None) -> dict:
    """Reported months grouped by the desk's own asset-class taxonomy.

    The grouping is not invented here and not inferred from the letters. It is
    the ``Asset Class`` property already curated on the Notion Funds database —
    'Hedge Funds - Multi-strategy', 'PE - Buyout' and the rest — reached by
    matching the reporting organisation to a fund record by name. Anything that
    does not resolve to a fund carrying an asset class is collected under
    ``unclassified`` and counted, never quietly dropped and never assigned to a
    group on a guess.

    Each group carries the equal-weighted mean of its managers' reported months.
    That mean is a *monthly average*, not an index: the set of managers
    reporting changes month to month, so ``managers`` travels with every point
    and the cumulative line is offered only as the compounding of those
    averages. Chained silently, with no constituent count, it would look like a
    track record — which is the one thing this page must never manufacture.
    """
    rows = _manager_months(letters)
    if group_of is None:
        group_of = _group_by_org(rows, funds or [])

    grouped: dict[str, list[dict]] = {}
    unclassified: set[str] = set()
    for r in rows:
        group = group_of.get(r["org"])
        if not group:
            unclassified.add(r["org"])
            continue
        grouped.setdefault(group, []).append(r)

    groups = []
    for name in sorted(grouped):
        rs = grouped[name]
        months = _by_month(rs)
        series, cumulative = [], 1.0
        for month in sorted(months):
            pcts = [x["pct"] for x in months[month]]
            mean = sum(pcts) / len(pcts)
            cumulative *= 1 + mean / 100
            series.append({
                "month": month, "mean": round(mean, 3),
                "managers": len({x["org"] for x in months[month]}),
                "cumulative": round((cumulative - 1) * 100, 3),
            })
        best = max(rs, key=lambda x: x["pct"])
        worst = min(rs, key=lambda x: x["pct"])
        groups.append({
            "group": name,
            "managers": sorted({x["org"] for x in rs}),
            "manager_count": len({x["org"] for x in rs}),
            "months": len(months),
            "figures": len(rs),
            "series": series,
            "mean": round(sum(x["pct"] for x in rs) / len(rs), 3),
            "best": {"org": best["org"], "month": best["month"], "pct": best["pct"]},
            "worst": {"org": worst["org"], "month": worst["month"], "pct": worst["pct"]},
        })
    groups.sort(key=lambda g: (-g["manager_count"], g["group"]))
    return {
        "groups": groups,
        "unclassified": sorted(unclassified),
        "taxonomy": "Notion Funds · Asset Class",
    }


def group_index_view(letters: list[dict], funds: Optional[list] = None,
                     group_of: Optional[dict] = None) -> dict:
    """Every strategy group on one axis, equal weighted, rebased to 100.

    The cross-sections above answer "how did the desk do *this month*". This
    answers the other question — which mandates have actually compounded — by
    putting the groups on a single axis, where the distance between the lines
    is the whole reading.

    Two properties of real correspondence the design this follows never had to
    face, because it was drawn against a complete 12x12 grid:

    * **Groups do not report the same months.** The axis is therefore the union
      of every month any group reported, and a group's index is carried *flat*
      through a month it did not report. The alternative — each group on its
      own axis — would put curves of different lengths in one frame and invite
      reading a short line as a poor one. Which months a group actually
      reported travels with the series as ``reported`` so the carried stretches
      can be drawn as the assumptions they are.
    * **The constituents change underneath the line.** ``managers`` carries the
      count behind every month, and the total behind the group, because an
      index whose membership moves is not a track record and this page must
      never manufacture one.

    Level at month *i* is the index at the **end** of that month, so the base
    of 100 belongs to the start of ``base_month`` — which is why the dashed
    rule at 100 is drawn, rather than a point plotted at it.
    """
    rows = _manager_months(letters)
    if group_of is None:
        group_of = _group_by_org(rows, funds or [])

    grouped: dict[str, list[dict]] = {}
    unclassified: set[str] = set()
    for r in rows:
        group = group_of.get(r["org"])
        if not group:
            unclassified.add(r["org"])
            continue
        grouped.setdefault(group, []).append(r)

    months = sorted({r["month"] for r in rows if group_of.get(r["org"])})
    if not months:
        return {"months": [], "groups": [], "unclassified": sorted(unclassified),
                "base": _INDEX_BASE, "base_month": "",
                "taxonomy": "Notion Funds · Asset Class"}

    groups = []
    for name in sorted(grouped):
        by_month = _by_month(grouped[name])
        level = float(_INDEX_BASE)
        values, reported, managers = [], [], []
        for month in months:
            here = by_month.get(month) or []
            if here:
                level *= 1 + (sum(x["pct"] for x in here) / len(here)) / 100
            values.append(round(level, 3))
            reported.append(bool(here))
            managers.append(len({x["org"] for x in here}))
        groups.append({
            "group": name,
            "managers": sorted({x["org"] for x in grouped[name]}),
            "manager_count": len({x["org"] for x in grouped[name]}),
            "managers_by_month": managers,
            "months_reported": sum(reported),
            "values": values,
            "reported": reported,
            "end": values[-1],
        })
    # Best first: the legend then reads top to bottom in the same order the
    # lines finish, which is the order the eye already picked off the chart.
    groups.sort(key=lambda g: (-g["end"], g["group"]))
    drawable = [g for g in groups if g["months_reported"] >= _MIN_INDEX_MONTHS]
    thin = [{"group": g["group"], "manager_count": g["manager_count"],
             "months_reported": g["months_reported"], "end": g["end"]}
            for g in groups if g["months_reported"] < _MIN_INDEX_MONTHS]
    # An axis stretching past the last month anybody drawable reported would be
    # empty on the right for no reason the reader can see.
    if drawable:
        last = max(i for g in drawable for i, r in enumerate(g["reported"]) if r)
        if last < len(months) - 1:
            months = months[:last + 1]
            for g in drawable:
                for key in ("values", "reported", "managers_by_month"):
                    g[key] = g[key][:last + 1]
                g["end"] = g["values"][-1]
            drawable.sort(key=lambda g: (-g["end"], g["group"]))

    return {
        "months": months if drawable else [],
        "base": _INDEX_BASE,
        "base_month": months[0] if drawable else "",
        "groups": drawable,
        "thin": thin,
        "min_months": _MIN_INDEX_MONTHS,
        "unclassified": sorted(unclassified),
        "taxonomy": "Notion Funds · Asset Class",
    }


def _group_by_org(rows: list[dict], funds: list) -> dict[str, str]:
    """Reporting organisation -> asset class, matched by name against Notion.

    Two ways a manager reaches a fund record, because the question here is not
    the one dedupe answers:

    * **Ownership.** A fund whose name *begins with* the manager's name is that
      manager's fund. 'Albizia' and 'Albizia ASEAN Opportunities Fund' are not
      the same entity, so no identity measure will ever score them highly, but
      the second plainly belongs to the first — and that is the overwhelmingly
      common shape of a manager letter reporting its own vehicle. This is the
      route that classifies almost everything.
    * **Same name.** The CRM's own matcher, reused rather than reimplemented —
      the function that decides whether an email's sender is an existing company
      decides whether a letter's author is an existing manager.

    That second route demands **duplicate-strength** evidence, not dedupe's
    review threshold, and the difference is the whole point. A review-band score
    means *a person should look at this*; there is no person in this loop, so
    the score has to mean *these are the same firm*. Accepting the review band
    put five wrong strategy labels on this page — 'AM Squared' filed under
    'Hamilton Square', 'ANDA Asset Management' and 'Grand Alliance Asset
    Management' both under 'Sultana Asset Management', 'Tribeca Investment
    Partners' under 'Green Investment Partners' — every one of them a firm the
    desk has never met, and every one of them indistinguishable on screen from a
    real classification.

    Where a manager owns several funds the shortest name wins, which is the
    least-qualified and so the most likely to be the flagship. Anything
    unresolved stays unclassified: a wrong strategy label is worse than an
    honest gap, and the unclassified list is shown.
    """
    # Indexed rather than scanned. Notion holds ~9,000 funds and the desk has
    # ~50 reporting managers; comparing every pair meant a quarter of a million
    # name comparisons on every page load, which is what made this dashboard
    # take twenty seconds to open. The index narrows each org to the handful of
    # funds that could match it at all — without changing which ones do, since
    # every candidate is still put through the same matcher.
    from src.features.dedupe import DUPLICATE_THRESHOLD, NameIndex, prepare_name, prepared_match

    index = NameIndex(
        (getattr(f, "name", "") or "", (getattr(f, "asset_class", None) or [None])[0])
        for f in funds
        if (getattr(f, "asset_class", None) or []) and (getattr(f, "name", "") or "")
    )

    out: dict[str, str] = {}
    for org in {r["org"] for r in rows if r.get("org")}:
        org_prepared = prepare_name(org)
        org_tokens = org_prepared.normalised.split()
        # Too little left after normalisation to identify anyone by.
        if len("".join(org_tokens)) < 3:
            continue

        owned = index.starting_with(org_tokens)
        pool = {i: (p, group)
                for i, p, group in index.candidates(org_prepared, DUPLICATE_THRESHOLD)}
        pool.update({i: (p, group) for i, p, group in owned})
        owns_ids = {i for i, _p, _g in owned}

        best = None
        for i, (prepared, group) in pool.items():
            owns = i in owns_ids
            try:
                # Below the bar the score is only ever used to rank candidates
                # that already cleared it, so flooring the comparison changes
                # nothing that is read.
                score = prepared_match(org_prepared, prepared,
                                       floor=DUPLICATE_THRESHOLD)[0]
            except Exception:  # noqa: BLE001 - never let one odd name break the page
                score = 0.0
            if not owns and score < DUPLICATE_THRESHOLD:
                continue
            # Ownership beats similarity; among owned funds, the shortest name.
            tokens = prepared.normalised.split()
            rank = (0 if owns else 1, len(tokens) - len(org_tokens) if owns else 0, -score)
            if best is None or rank < best[0]:
                best = (rank, group)

        if best:
            out[org] = best[1]
    return out


def monitor_view(letters: list[dict], manifest_data: dict) -> list[dict]:
    """The watchlist: where the evidence itself is the concern.

    Three rules, each one a gap rather than a number:

    * a manager reported a bad month and said nothing about it;
    * a track record arrived that nobody can read yet;
    * a manager who used to write has gone quiet in the latest window.
    """
    items: list[dict] = []
    latest = PERIODS[-1].key

    by_org: dict[str, list[dict]] = {}
    for letter in letters:
        by_org.setdefault(letter.get("org", ""), []).append(letter)

    for org, org_letters in by_org.items():
        if not org:
            continue
        for letter in org_letters:
            for r in letter.get("reported_returns") or []:
                pct = r.get("pct")
                if isinstance(pct, (int, float)) and pct <= _DRAWDOWN_PCT \
                        and len(letter.get("quotes") or []) <= _SILENT_QUOTES:
                    items.append({
                        "org": org,
                        "severity": "urgent" if pct <= 2 * _DRAWDOWN_PCT else "attention",
                        "category": "Silent on a drawdown",
                        "headline": f"{pct:+.2f}% in {r.get('month', 'the period')} "
                                    f"arrived with no commentary behind it.",
                        "detail": f"Reported via {letter.get('source') or 'correspondence'}. "
                                  f"The figure is theirs; the explanation is missing.",
                        "date": letter.get("date", ""),
                    })

        periods_seen = {x.get("period") for x in org_letters}
        if latest not in periods_seen and len(periods_seen) >= 2:
            items.append({
                "org": org,
                "severity": "watch",
                "category": "Gone quiet",
                "headline": f"Wrote in {len(periods_seen)} earlier windows, nothing in the current one.",
                "detail": "Silence is not evidence of a problem, but it is the absence of "
                          "evidence against one.",
                "date": max((x.get("date", "") for x in org_letters), default=""),
            })

    for att in mf.pending_attachments(manifest_data):
        items.append({
            "org": att.get("org") or "unattributed",
            "severity": "attention",
            "category": "Numbers nobody has read",
            "headline": f"{att.get('name', 'A track record')} arrived but could not be opened.",
            "detail": "Attachment content needs live Graph access (an Entra app "
                      "registration). Until then, upload the file on the Track records "
                      "page to bring it into the performance view.",
            "date": att.get("at", "")[:10],
        })

    rank = {s: i for i, s in enumerate(SEVERITIES)}
    items.sort(key=lambda i: (rank.get(i["severity"], 9), i["org"]))
    return items


def cross_view(letters: list[dict], cross_data: dict) -> dict:
    """Stored reversals and disagreements, plus how much ground is still unread.

    No model call: the verdicts were bought by ``cross_pass``, and the candidate
    counts are the same free pairing arithmetic that pass uses to decide what to
    buy. The coverage numbers are the point of doing it here — a section showing
    two reversals means something different when four pairs remain unjudged than
    when none do, and only this module knows both figures.
    """
    reversal_cands = cross_pass.reversal_candidates(letters)
    conflict_cands, not_examined = cross_pass.conflict_candidates(letters)
    judged = cross_data.get("verdicts", {})
    pending = sum(1 for c in reversal_cands + conflict_cands if c["key"] not in judged)

    return {
        "reversals": cs.held(cross_data, cs.REVERSAL),
        "conflicts": cs.held(cross_data, cs.CONFLICT),
        "candidates": len(reversal_cands) + len(conflict_cands),
        "pending": pending,
        "not_examined": not_examined,
        "stats": cs.stats(cross_data),
    }


def build(voices_base: Optional[Path] = None, manifest_base: Optional[Path] = None,
          records_base: Optional[Path] = None, funds: Optional[list] = None,
          cross_base: Optional[Path] = None) -> dict:
    """The whole dashboard payload, minus the factor matrix (its own endpoint).

    ``funds`` is the Notion Funds list, supplied by the caller because this
    module does no I/O of its own. Without it the strategy grouping simply has
    no taxonomy to group by and reports everything as unclassified, which is
    the honest degradation — the other views are unaffected.
    """
    letters = store.all_letters(voices_base)
    manifest_data = mf.load(manifest_base)
    extremes = standouts_and_strained(letters)
    # Matching every reporting manager against every fund in Notion is the most
    # expensive thing on this page (~9,000 records). Four views below want the
    # result, so it is computed once here rather than once each.
    group_of = _group_by_org(_manager_months(letters), funds or [])

    return {
        "coverage": COVERAGE_LABEL,
        "mailbox_periods": periods_view(letters),
        "themes": themes_view(letters),
        "stance_by_org": stance_by_org(letters),
        "stance_matrix": stance_matrix(letters),
        "voices": voices_view(letters),
        "disclosed": disclosed_view(letters),
        "reported_returns": reported_returns_view(letters),
        "standouts": extremes["standouts"],
        "strained": extremes["strained"],
        "dispersion": _group_series(letters, funds, dispersion_view, group_of),
        "breadth": _group_series(letters, funds, breadth_view, group_of),
        "strategy_groups": strategy_groups_view(letters, funds, group_of),
        "group_index": group_index_view(letters, funds, group_of),
        "manager_tracks": manager_tracks_view(letters, funds, group_of),
        "cross": cross_view(letters, cs.load(cross_base)),
        # How many quotes still show their letter's themes rather than their
        # own. Counting only — the repair itself is a job the desk starts.
        "retheme": retheme.stats(letters),
        "monitor": monitor_view(letters, manifest_data),
        "track_records_held": len(track_record_store.list_all(records_base)),
        "sweep": mf.stats(manifest_data),
        "counts": {
            "organisations": len({x.get("org") for x in letters if x.get("org")}),
            "letters": len(letters),
            "quotes": sum(len(x.get("quotes") or []) for x in letters),
        },
    }
