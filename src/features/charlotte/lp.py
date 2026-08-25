"""LP reference candidates for a fund, in evidence tiers.

T0  listed in the fund's "Known LPs" relation — the explicit record.
T1  LP-typed contact who attended a meeting tagged to the fund.
T2  LP-typed contact on the fund's Introduced By / Represented By.
T3  attendee of an "LP Meeting" note tagged to the fund (any type).
T4  named in fund prose / note bodies by the Phase-3 extraction — INFERRED.

Tier strings sort correctly ("T0" < "T1" < …), so best-tier-wins is a
plain min(). Internal contacts never qualify; a contact hitting several
tiers reports the best one with the evidence merged.
"""
from __future__ import annotations

from src.features.charlotte.graph import neighbors

LP_TYPES = {"lp - institutional / sfo", "gp/lp - mfo / fund of funds"}

TIER_LABELS = {
    "T0": "listed in Known LPs",
    "T1": "LP attended a meeting on this fund",
    "T2": "LP introduced or represents this fund",
    "T3": "attended an LP Meeting on this fund",
    "T4": "named in fund commentary (inferred)",
}

_EVIDENCE_CAP = 6


def _ctype(node: dict) -> str:
    return " ".join(str(node.get("contact_type") or "").lower().split())


def _is_lp(node: dict) -> bool:
    return _ctype(node) in LP_TYPES


def candidates(graph: dict, fund_id: str) -> list:
    fund = graph["nodes"].get(fund_id)
    if not fund or fund.get("kind") != "fund":
        return []
    found: dict = {}

    def record(other_id: str, tier: str, evidence: list) -> None:
        cur = found.get(other_id)
        if cur is None:
            found[other_id] = {"tier": tier, "evidence": list(evidence)}
            return
        cur["tier"] = min(cur["tier"], tier)
        cur["evidence"].extend(evidence)

    for other, e in neighbors(graph, fund_id):
        n = graph["nodes"].get(other) or {}
        etype = e.get("type", "")
        ev = e.get("evidence") or []
        # Inferred mentions can point at contacts, companies, or external
        # leaf nodes — all are legitimate reference leads.
        if etype == "lp_mention":
            record(other, "T4", ev)
            continue
        if n.get("kind") != "contact" or _ctype(n) == "internal":
            continue
        if etype == "known_lp":
            record(other, "T0",
                   [{"kind": "relation", "label": TIER_LABELS["T0"]}])
        elif etype in ("introduced_by", "represented_by") and _is_lp(n):
            record(other, "T2", [{"kind": "relation",
                                  "label": etype.replace("_", " ")}])
        elif etype == "discussed":
            lp_meetings = [x for x in ev
                           if (x.get("note_type") or "") == "LP Meeting"]
            if _is_lp(n):
                record(other, "T1", ev)
            elif lp_meetings:
                record(other, "T3", lp_meetings)

    out = []
    for cid, d in found.items():
        node = graph["nodes"].get(cid) or {}
        out.append({"id": cid, "name": node.get("label", ""),
                    "kind": node.get("kind", ""),
                    "tier": d["tier"], "tier_label": TIER_LABELS[d["tier"]],
                    "inferred": d["tier"] == "T4",
                    "evidence": d["evidence"][:_EVIDENCE_CAP]})
    out.sort(key=lambda r: (r["tier"], r["name"].lower()))
    return out
