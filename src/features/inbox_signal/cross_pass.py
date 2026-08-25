"""The two readings that need a model rather than a count.

``views.py`` answers its questions by counting: how often a theme came up, how
many managers were constructive, who has gone quiet. Two questions on the
dashboard cannot be answered that way, because both are about the *relationship
between two documents*:

* **Reversals** — one manager saying the opposite of what they said last time.
* **Conflicts** — two managers answering the same question opposite ways.

Counting cannot see either. A stance flip from constructive to cautious is not a
reversal if the two letters are about different things, and two managers holding
opposite stances in the same window are not in disagreement unless they are
actually addressing the same question. Only reading both documents together
settles it, and that costs a model call — which is why this is a separate,
cached pass and not another function in ``views.py``.

Three things keep it honest and cheap:

1. **Pairing is deterministic and free.** Candidates are found by counting —
   same manager, shared theme, stance direction flipped; or same window, shared
   theme, opposite directions. The model is only ever asked to adjudicate a
   pair, never to go looking for one. So the bill is bounded by arithmetic done
   before any call is made, and the pairing logic is testable without a client.

2. **The model selects quotes, it does not write them.** It is given each
   letter's already-verified quotes, numbered, and returns an index. A model
   that would otherwise paraphrase cannot: there is nowhere to put prose. This
   is a stronger guarantee than ``extract_letter``'s verbatim check, which has
   to compare against a body — here the source text is the only text there is.

3. **A "no" is stored like a "yes".** See ``cross_store``. Most candidate pairs
   are near-misses, so a cache that only kept the hits would re-buy the misses
   on every run.

Tests inject a fake client exposing ``messages.create``, as the other feature
modules do, so no model calls happen in CI.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from src import config
from src.config import EXTRACTION_MODEL
from src.features.inbox_signal import cross_store as cs
from src.features.inbox_signal.periods import BY_KEY, PERIODS
from src.features.inbox_signal.taxonomy import normalise_stance, theme_label

# Which way a stance leans on risk. Cautious and negative are both risk-off:
# the distinction between them is intensity, not direction, and treating a move
# from cautious to negative as a reversal would call every worsening mood a
# change of mind. Neutral is 0 and never pairs — a manager who only reported
# figures has not taken a position to reverse or to disagree with.
DIRECTION = {"constructive": 1, "cautious": -1, "negative": -1, "neutral": 0}

# Per (window, theme), the most opposed pairs to put up for judgement. Every
# constructive manager can be paired with every cautious one, so a busy theme
# in a busy window is quadratic; this bounds it. What is dropped is counted and
# reported rather than silently discarded.
MAX_PAIRS_PER_CELL = 3


def _leaning(letter: dict) -> int:
    return DIRECTION.get(normalise_stance(letter.get("stance")), 0)


def _period_rank(key: str) -> int:
    order = {p.key: i for i, p in enumerate(PERIODS)}
    return order.get(key or "", -1)


def _side(letter: dict) -> dict:
    """The part of a letter this pass reasons over and cites."""
    return {
        "message_id": letter.get("message_id", ""),
        "org": letter.get("org", ""),
        "person": letter.get("person", ""),
        "source": letter.get("source", ""),
        "date": letter.get("date", ""),
        "period": letter.get("period", ""),
        "period_label": (BY_KEY[letter["period"]].short
                         if letter.get("period") in BY_KEY else ""),
        "stance": normalise_stance(letter.get("stance")),
        "quotes": [q.get("quote", "") for q in (letter.get("quotes") or []) if q.get("quote")],
    }


# --------------------------------------------------------------------------- #
# Pairing — pure, free, and testable without a model.
# --------------------------------------------------------------------------- #

def reversal_candidates(letters: list[dict]) -> list[dict]:
    """Same manager, same theme, stance direction flipped between two windows.

    Adjacent pairs within each (manager, theme) sequence, not every combination:
    a manager who went constructive, cautious, constructive again has changed
    their mind twice, and both moments are worth a look, but the first and last
    letters are not themselves a reversal to be reported a third time.
    """
    by_org_theme: dict[tuple[str, str], list[dict]] = {}
    for letter in letters:
        org = (letter.get("org") or "").strip()
        if not org or not _leaning(letter):
            continue
        for theme in letter.get("themes") or []:
            by_org_theme.setdefault((org, theme), []).append(letter)

    out: list[dict] = []
    for (org, theme), group in sorted(by_org_theme.items()):
        group = sorted(group, key=lambda x: (x.get("date") or "", x.get("message_id") or ""))
        for earlier, later in zip(group, group[1:]):
            if earlier.get("period") == later.get("period"):
                continue
            if _leaning(earlier) == _leaning(later):
                continue
            a, b = _side(earlier), _side(later)
            if not a["quotes"] or not b["quotes"]:
                continue        # nothing quotable to show; not worth paying for
            out.append({
                "key": f"reversal|{org}|{theme}|{a['message_id']}|{b['message_id']}",
                "kind": cs.REVERSAL,
                "org": org,
                "theme": theme,
                "theme_label": theme_label(theme),
                "earlier": a,
                "later": b,
                "sort_date": b["date"],
            })
    out.sort(key=lambda c: c["sort_date"], reverse=True)
    return out


def conflict_candidates(letters: list[dict]) -> tuple[list[dict], int]:
    """Two managers, same window, same theme, opposite leanings.

    Returns (candidates, not_examined) — the second is how many opposed pairs
    exist beyond the per-cell cap. It is reported on the dashboard rather than
    dropped quietly, so a busy theme does not read as a settled one.
    """
    cells: dict[tuple[str, str], list[dict]] = {}
    for letter in letters:
        if not (letter.get("org") or "").strip() or not _leaning(letter):
            continue
        for theme in letter.get("themes") or []:
            cells.setdefault((letter.get("period") or "", theme), []).append(letter)

    out: list[dict] = []
    skipped = 0
    for (period, theme), group in sorted(cells.items()):
        pos = [x for x in group if _leaning(x) > 0]
        neg = [x for x in group if _leaning(x) < 0]
        # One pair per pair of firms, not per pair of documents. A manager who
        # sends a CIO letter, a monthly risk report and a fund note in the same
        # window is one voice on the theme, and pairing each of them against the
        # same opponent would buy the same disagreement three times and then
        # show it three times. Best-evidenced document per firm pair wins.
        best: dict[tuple[str, str], tuple[int, dict, dict]] = {}
        for p in pos:
            for n in neg:
                p_org, n_org = (p.get("org") or "").strip(), (n.get("org") or "").strip()
                if p_org == n_org:
                    continue        # a firm disagreeing with itself is a reversal, not a conflict
                a, b = _side(p), _side(n)
                if not a["quotes"] or not b["quotes"]:
                    continue
                weight = len(a["quotes"]) + len(b["quotes"])
                slot = (p_org, n_org)
                if weight > best.get(slot, (-1,))[0]:
                    best[slot] = (weight, a, b)
        # Most-evidenced first: a pair with more quoted view behind it is the
        # one most likely to be a real disagreement rather than a labelling
        # artefact, and is the one worth the call if only some can be made.
        pairs = sorted(best.values(), key=lambda t: (-t[0], t[1]["org"], t[2]["org"]))
        skipped += max(0, len(pairs) - MAX_PAIRS_PER_CELL)
        for _n, a, b in pairs[:MAX_PAIRS_PER_CELL]:
            out.append({
                "key": f"conflict|{period}|{theme}|{a['message_id']}|{b['message_id']}",
                "kind": cs.CONFLICT,
                "period": period,
                "period_label": (BY_KEY[period].short if period in BY_KEY else ""),
                "theme": theme,
                "theme_label": theme_label(theme),
                "a": a,
                "b": b,
                "sort_date": max(a["date"], b["date"]),
            })
    out.sort(key=lambda c: (-_period_rank(c["period"]), c["theme"]))
    return out, skipped


# --------------------------------------------------------------------------- #
# Judging — one model call per candidate pair.
# --------------------------------------------------------------------------- #

_QUOTE_INDEX = {
    "type": "integer",
    "description": "The number of the quote that carries the position, from the "
                   "numbered list for that letter. Use -1 if no quote in the list "
                   "actually states it.",
}

REVERSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "is_reversal": {
            "type": "boolean",
            "description": "True only if the later letter contradicts the position the "
                           "earlier one took on this subject. False if the two letters "
                           "are about different things, if the later one merely adds "
                           "nuance or reports a worsening of the same view, or if the "
                           "earlier letter took no position to reverse.",
        },
        "summary": {
            "type": "string",
            "description": "One sentence: what they held then, and what they hold now. "
                           "Written for someone about to meet them.",
        },
        "earlier_quote": _QUOTE_INDEX,
        "later_quote": _QUOTE_INDEX,
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["is_reversal", "summary", "earlier_quote", "later_quote", "confidence"],
    "additionalProperties": False,
}

CONFLICT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_conflict": {
            "type": "boolean",
            "description": "True only if the two managers are answering the SAME question "
                           "in opposite ways. False if they are writing about different "
                           "markets, different instruments or different time horizons, "
                           "even where the dashboard has filed both under one theme.",
        },
        "question": {
            "type": "string",
            "description": "The question they answer oppositely, phrased as a question.",
        },
        "summary": {"type": "string", "description": "One sentence on where the two part company."},
        "a_quote": _QUOTE_INDEX,
        "b_quote": _QUOTE_INDEX,
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["is_conflict", "question", "summary", "a_quote", "b_quote", "confidence"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You read fund manager correspondence for a family office and adjudicate \
whether two letters stand in a particular relationship to each other.

You are shown two letters, each reduced to quotes already verified as verbatim from the \
original. You never write a quote: you choose one from the numbered list given for each \
letter, by its number. If no quote in a list actually carries the position, return -1 for \
that letter rather than picking the nearest thing.

Say no. The pairs you are shown were selected by a crude filter — same manager and a \
changed stance label, or two managers with opposing stance labels in one window. Most such \
pairs are not what they look like: managers write about different holdings, different \
markets and different horizons under the same heading, and a stance label describes a \
letter's overall posture, not its view on any one subject. A false positive here becomes a \
claim on the dashboard that a named person contradicted themselves, or that two named \
managers disagree, and it is put in front of them at a meeting. An unreported real \
reversal costs a talking point. Judge accordingly, and set confidence to low rather than \
withholding a genuine finding.

Write in plain financial English, British spelling, no hype. Do not name a manager as \
having said something the chosen quote does not show."""


def _numbered(quotes: list[str]) -> str:
    return "\n".join(f"  [{i}] {q}" for i, q in enumerate(quotes)) or "  (none)"


def _letter_block(side: dict, label: str) -> str:
    who = f"{side['org']}" + (f" — {side['person']}" if side.get("person") else "")
    return (
        f"=== {label} ===\n"
        f"Manager: {who}\n"
        f"Document: {side.get('source') or '(untitled)'}\n"
        f"Date: {side.get('date')} (window {side.get('period_label') or side.get('period')})\n"
        f"Stance recorded for the letter as a whole: {side.get('stance')}\n"
        f"Quotes:\n{_numbered(side['quotes'])}"
    )


def _pick(index, quotes: list[str]) -> str:
    """Resolve a returned index to stored text, or empty if it points nowhere."""
    if not isinstance(index, int) or isinstance(index, bool):
        return ""
    return quotes[index] if 0 <= index < len(quotes) else ""


def _call(client, schema: dict, user: str) -> dict | None:
    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": user}],
    )
    if getattr(response, "stop_reason", None) == "refusal":
        return None
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def judge_reversal(client, cand: dict) -> dict:
    """Adjudicate one reversal candidate. Never raises on model trouble."""
    user = (
        f"Subject filed under: {cand['theme_label']}\n"
        f"Both letters are from {cand['org']}. Did they reverse their position on this "
        f"subject between the two?\n\n"
        + _letter_block(cand["earlier"], "EARLIER LETTER")
        + "\n\n"
        + _letter_block(cand["later"], "LATER LETTER")
    )
    parsed = _call(client, REVERSAL_SCHEMA, user)
    if parsed is None:
        return {"kind": cs.REVERSAL, "found": False, "reason": "no usable model output"}
    if not parsed.get("is_reversal"):
        return {"kind": cs.REVERSAL, "found": False, "reason": "adjudicated: not a reversal"}

    earlier = _pick(parsed.get("earlier_quote"), cand["earlier"]["quotes"])
    later = _pick(parsed.get("later_quote"), cand["later"]["quotes"])
    quotes = bool(earlier and later)
    return {
        "kind": cs.REVERSAL,
        "found": True,
        "quotes": quotes,
        "reason": "" if quotes else "affirmed but not evidenced by both letters",
        "org": cand["org"],
        "theme": cand["theme"],
        "theme_label": cand["theme_label"],
        "summary": (parsed.get("summary") or "").strip(),
        "confidence": (parsed.get("confidence") or "low").strip().lower(),
        "sort_date": cand["sort_date"],
        "earlier": {**{k: v for k, v in cand["earlier"].items() if k != "quotes"}, "quote": earlier},
        "later": {**{k: v for k, v in cand["later"].items() if k != "quotes"}, "quote": later},
    }


def judge_conflict(client, cand: dict) -> dict:
    """Adjudicate one conflict candidate. Never raises on model trouble."""
    user = (
        f"Subject filed under: {cand['theme_label']}\n"
        f"Window: {cand['period_label'] or cand['period']}\n"
        f"Are {cand['a']['org']} and {cand['b']['org']} answering the same question "
        f"in opposite ways?\n\n"
        + _letter_block(cand["a"], "MANAGER A")
        + "\n\n"
        + _letter_block(cand["b"], "MANAGER B")
    )
    parsed = _call(client, CONFLICT_SCHEMA, user)
    if parsed is None:
        return {"kind": cs.CONFLICT, "found": False, "reason": "no usable model output"}
    if not parsed.get("is_conflict"):
        return {"kind": cs.CONFLICT, "found": False, "reason": "adjudicated: not a disagreement"}

    a_quote = _pick(parsed.get("a_quote"), cand["a"]["quotes"])
    b_quote = _pick(parsed.get("b_quote"), cand["b"]["quotes"])
    quotes = bool(a_quote and b_quote)
    return {
        "kind": cs.CONFLICT,
        "found": True,
        "quotes": quotes,
        "reason": "" if quotes else "affirmed but not evidenced by both letters",
        "period": cand["period"],
        "period_label": cand["period_label"],
        "theme": cand["theme"],
        "theme_label": cand["theme_label"],
        "question": (parsed.get("question") or "").strip(),
        "summary": (parsed.get("summary") or "").strip(),
        "confidence": (parsed.get("confidence") or "low").strip().lower(),
        "sort_date": cand["sort_date"],
        "a": {**{k: v for k, v in cand["a"].items() if k != "quotes"}, "quote": a_quote},
        "b": {**{k: v for k, v in cand["b"].items() if k != "quotes"}, "quote": b_quote},
    }


# --------------------------------------------------------------------------- #
# The run.
# --------------------------------------------------------------------------- #

def _noop(*_args, **_kwargs) -> None:
    return None


def _never(*_args, **_kwargs) -> bool:
    return False


def run(client, letters: list[dict], *, base: Optional[Path] = None,
        max_pairs: Optional[int] = None,
        on_progress: Callable[[int, int, str], None] = _noop,
        check_cancel: Callable[[], bool] = _never) -> dict:
    """Judge every unjudged candidate pair, up to the cap.

    Returns a summary, also stored, so the dashboard can show what the pass cost
    without re-deriving it. Progress and cancellation come in as plain callables
    for the same reason the sweep takes them that way — ``src/`` keeps no
    dependency on the API layer.
    """
    if not config.INBOX_SIGNAL_ENABLED:
        return {"skipped": True, "reason": "INBOX_SIGNAL_ENABLED is off"}

    cap = max_pairs if max_pairs is not None else config.INBOX_SIGNAL_MAX_PAIRS_PER_PASS
    reversals = reversal_candidates(letters)
    conflicts, not_examined = conflict_candidates(letters)
    candidates = reversals + conflicts

    with cs.Cross(base) as store:
        pending = [c for c in candidates if not cs.judged(store.data, c["key"])]
    queued, deferred = pending[:cap], max(0, len(pending) - cap)

    judged = found = 0
    cancelled = False
    for i, cand in enumerate(queued):
        if check_cancel():
            cancelled = True
            break
        on_progress(i, len(queued), cand.get("org") or cand.get("theme_label") or "")
        try:
            verdict = (judge_reversal(client, cand) if cand["kind"] == cs.REVERSAL
                       else judge_conflict(client, cand))
        except Exception as exc:                              # noqa: BLE001
            # One awkward pair must not lose the verdicts already bought in this
            # run. Not stored: unlike an adjudicated "no", a transport failure
            # says nothing about the pair, so it stays eligible for a retry.
            on_progress(i, len(queued), f"failed: {exc.__class__.__name__}")
            continue
        judged += 1
        if verdict.get("found") and verdict.get("quotes"):
            found += 1
        with cs.Cross(base) as store:
            cs.record(store.data, cand["key"], verdict)

    summary = {
        "candidates": len(candidates),
        "judged": judged,
        "found": found,
        "deferred": deferred,
        "not_examined": not_examined,
        "cancelled": cancelled,
    }
    with cs.Cross(base) as store:
        cs.record_run(store.data, summary)
    return summary
