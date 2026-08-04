"""Felix's model-in-the-loop steps — batched, capped, and distrusted.

Two jobs only: (1) verdicts on fuzzy duplicate pairs, (2) evidence-based
proposals for missing properties. Everything the model returns is checked in
code: an evidence quote that is not a verbatim substring of the evidence we
supplied downgrades the proposal to a recommendation. The model classifies;
it never invents values that get written unchecked.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from src.config import FAST_MODEL, LIVE_MODEL

DUP_BATCH = 20
FILL_BATCH = 10

_DUP_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pair_id": {"type": "integer"},
                    "verdict": {"type": "string",
                                "enum": ["duplicate", "distinct", "unsure"]},
                    "survivor": {"type": "string", "enum": ["a", "b", ""]},
                    "reason": {"type": "string"},
                },
                "required": ["pair_id", "verdict", "survivor", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}

_DUP_SYSTEM = """You adjudicate possible duplicate records in a family office's \
Notion workspace. For each pair, decide whether the two records describe the SAME \
real-world entity. Similar names alone do NOT prove duplication — different funds \
share naming patterns (Fund I vs Fund II are DISTINCT), different people share \
names, and regional affiliates are distinct companies. Judge from every field \
shown: identifiers, roles, relationships, dates. If the evidence does not clearly \
establish sameness, answer "unsure" — a wrong "duplicate" merges real records. \
For duplicates, pick the survivor: the record with the richer relationships and \
more complete information."""

_FILL_SCHEMA = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "property": {"type": "string"},
                    "value": {"type": "string"},
                    "evidence_quote": {
                        "type": "string",
                        "description": "VERBATIM substring of the supplied "
                                       "evidence that supports the value"},
                    "confidence": {"type": "string",
                                   "enum": ["high", "medium", "low"]},
                },
                "required": ["task_id", "property", "value", "evidence_quote",
                             "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["proposals"],
    "additionalProperties": False,
}

_FILL_SYSTEM = """You complete missing properties on records in a family office's \
Notion workspace, using ONLY the evidence supplied for each record (linked meeting \
notes, email domains, linked record names). Propose a value only when the evidence \
supports it, and quote the exact supporting passage VERBATIM in evidence_quote — \
it will be checked as a literal substring of the evidence, and any proposal whose \
quote does not match is discarded. Where a property lists its allowed options, the \
value must be one of them exactly. Never infer from a name alone. When the \
evidence is insufficient, simply omit the proposal."""


def _pair_card(c: dict) -> str:
    bits = [f"name: {c['name']}"]
    if c.get("email"):
        bits.append(f"email: {c['email']}")
    for k, v in list(c.get("plain", {}).items())[:12]:
        if v and k not in ("Name",):
            bits.append(f"{k}: {v}")
    bits.append(f"relations: {sum(len(x) for x in c.get('relations', {}).values())}")
    bits.append(f"created: {c.get('created', '')[:10]}")
    return "; ".join(str(b)[:160] for b in bits)


def adjudicate_duplicates(client, pairs: list[dict],
                          max_calls: int = 30) -> list[dict]:
    """Verdicts for fuzzy pairs. Returns [{pair, verdict, survivor_card,
    reason}]; pairs beyond the call budget are returned as 'deferred'."""
    if client is None or not pairs:
        return [{"pair": p, "verdict": "deferred", "survivor_card": None,
                 "reason": "no model"} for p in pairs]

    batches = [pairs[i:i + DUP_BATCH] for i in range(0, len(pairs), DUP_BATCH)]
    allowed = batches[:max_calls]

    def _one(batch):
        lines = []
        for i, p in enumerate(batch):
            lines.append(f"PAIR {i} (name similarity {p['score']}):\n"
                         f"  a) {_pair_card(p['a'])}\n"
                         f"  b) {_pair_card(p['b'])}")
        response = client.messages.create(
            model=FAST_MODEL, max_tokens=2500, system=_DUP_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _DUP_SCHEMA}},
            messages=[{"role": "user", "content":
                       "Adjudicate these possible duplicates:\n\n" + "\n\n".join(lines)}],
        )
        raw = next((b.text for b in response.content
                    if getattr(b, "type", None) == "text"), "")
        verdicts = json.loads(raw).get("verdicts", [])
        out = []
        for v in verdicts:
            idx = v.get("pair_id", -1)
            if 0 <= idx < len(batch):
                p = batch[idx]
                survivor = p["a"] if v.get("survivor") == "a" else \
                    p["b"] if v.get("survivor") == "b" else None
                out.append({"pair": p, "verdict": v.get("verdict", "unsure"),
                            "survivor_card": survivor,
                            "reason": v.get("reason", "")})
        return out

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for batch_out in pool.map(_safe(_one), allowed):
            results.extend(batch_out)
    # Anything not judged (over budget, failed batch, model skipped a pair)
    # comes back marked deferred so the summary can count it honestly.
    judged = {tuple(sorted((r["pair"]["a"]["id"], r["pair"]["b"]["id"])))
              for r in results}
    for p in pairs:
        if tuple(sorted((p["a"]["id"], p["b"]["id"]))) not in judged:
            results.append({"pair": p, "verdict": "deferred",
                            "survivor_card": None,
                            "reason": "not adjudicated this run"})
    return results


def evaluate_missing_info(client, tasks: list[dict],
                          max_calls: int = 10) -> list[dict]:
    """Evidence-based fill proposals.

    ``tasks``: [{card, property, options (list, for selects), evidence (str)}].
    Returns [{task, value, evidence_quote, confidence, verified}] — `verified`
    is the in-code substring check; unverified proposals must not be applied.
    """
    if client is None or not tasks:
        return []

    batches = [tasks[i:i + FILL_BATCH] for i in range(0, len(tasks), FILL_BATCH)]
    batches = batches[:max_calls]

    def _one(batch):
        lines = []
        for i, t in enumerate(batch):
            opts = (f" (allowed options: {', '.join(t['options'])})"
                    if t.get("options") else "")
            lines.append(
                f"TASK {i}: record '{t['card']['name']}' "
                f"({t['card']['db']}), missing property '{t['property']}'{opts}\n"
                f"EVIDENCE:\n{t['evidence'][:4000]}")
        response = client.messages.create(
            # Sonnet: reading evidence out of meeting notes and deciding
            # whether it actually supports a value is a judgement call, and a
            # wrong fill is written into the workspace.
            model=LIVE_MODEL, max_tokens=2500, system=_FILL_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _FILL_SCHEMA}},
            messages=[{"role": "user", "content":
                       "Propose values where the evidence supports them:\n\n"
                       + "\n\n".join(lines)}],
        )
        raw = next((b.text for b in response.content
                    if getattr(b, "type", None) == "text"), "")
        out = []
        for pr in json.loads(raw).get("proposals", []):
            idx = pr.get("task_id", -1)
            if not (0 <= idx < len(batch)):
                continue
            t = batch[idx]
            quote = pr.get("evidence_quote", "")
            verified = bool(quote) and quote in t["evidence"]
            value = pr.get("value", "").strip()
            if t.get("options") and value not in t["options"]:
                verified = False        # never invent a select option
            if value:
                out.append({"task": t, "value": value, "evidence_quote": quote,
                            "confidence": pr.get("confidence", "low"),
                            "verified": verified})
        return out

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for batch_out in pool.map(_safe(_one), batches):
            results.extend(batch_out)
    return results


def _safe(fn):
    """A batch that errors yields nothing rather than killing the run."""
    def inner(batch):
        try:
            return fn(batch)
        except Exception:  # noqa: BLE001
            return []
    return inner
