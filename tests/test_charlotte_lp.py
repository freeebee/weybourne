"""Charlotte's Web — LP reference-candidate tiers."""
from src.features.charlotte import graph as graphmod
from src.features.charlotte import lp

NOTE = {"kind": "note", "id": "n1", "title": "Alpha update",
        "date": "2026-06-01", "note_type": "GP Meeting"}
LP_NOTE = {"kind": "note", "id": "n2", "title": "LP call on Alpha",
           "date": "2026-06-02", "note_type": "LP Meeting"}


def build(extra_edges=(), extra_nodes=None, inferred=None):
    nodes = {
        "f1": {"kind": "fund", "label": "Alpha Fund"},
        "k1": {"kind": "contact", "label": "Known Lp",
               "contact_type": "Other"},
        "a1": {"kind": "contact", "label": "Lp Attendee",
               "contact_type": "LP - Institutional / SFO"},
        "b1": {"kind": "contact", "label": "Lp Introducer",
               "contact_type": "GP/LP - MFO / Fund of Funds"},
        "c1": {"kind": "contact", "label": "Mystery Guest",
               "contact_type": "Other"},
        "i1": {"kind": "contact", "label": "Colleague",
               "contact_type": "Internal"},
    }
    nodes.update(extra_nodes or {})
    edges = [
        {"a": "f1", "b": "k1", "type": "known_lp"},
        {"a": "a1", "b": "f1", "type": "discussed", "evidence": [NOTE]},
        {"a": "f1", "b": "b1", "type": "introduced_by"},
        {"a": "c1", "b": "f1", "type": "discussed", "evidence": [LP_NOTE]},
        {"a": "i1", "b": "f1", "type": "discussed", "evidence": [LP_NOTE]},
    ] + list(extra_edges)
    snap = {"version": 1, "crawled_at": "", "counts": {},
            "nodes": nodes, "edges": edges, "texts": {}}
    return graphmod.build_graph(snap, inferred)


class TestTiers:
    def test_each_tier_lands_where_it_should(self):
        rows = {r["id"]: r for r in lp.candidates(build(), "f1")}
        assert rows["k1"]["tier"] == "T0"   # explicit relation beats typing
        assert rows["a1"]["tier"] == "T1"
        assert rows["b1"]["tier"] == "T2"
        assert rows["c1"]["tier"] == "T3"

    def test_internal_contacts_never_qualify(self):
        rows = {r["id"] for r in lp.candidates(build(), "f1")}
        assert "i1" not in rows

    def test_best_tier_wins_and_evidence_merges(self):
        # a1 is both an LP attendee (T1) and the fund's introducer (T2).
        g = build(extra_edges=[{"a": "f1", "b": "a1", "type": "introduced_by"}])
        row = next(r for r in lp.candidates(g, "f1") if r["id"] == "a1")
        assert row["tier"] == "T1"
        assert len(row["evidence"]) >= 2

    def test_t3_evidence_is_only_the_lp_meetings(self):
        row = next(r for r in lp.candidates(build(), "f1") if r["id"] == "c1")
        assert all(e["note_type"] == "LP Meeting" for e in row["evidence"])

    def test_inferred_mentions_arrive_as_t4(self):
        inferred = {"f1": {"fp": "x", "found": [
            {"kind": "lp", "name": "Isomer Capital", "quote": "LPs include Isomer"}]}}
        rows = lp.candidates(build(inferred=inferred), "f1")
        t4 = [r for r in rows if r["tier"] == "T4"]
        assert len(t4) == 1 and t4[0]["inferred"] is True
        assert rows == sorted(rows, key=lambda r: (r["tier"], r["name"].lower()))

    def test_non_fund_center_returns_nothing(self):
        assert lp.candidates(build(), "a1") == []
