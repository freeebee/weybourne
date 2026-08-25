"""Charlotte's Web — weaving and ego-network extraction."""
import json

from src.features.charlotte import graph as graphmod
from src.features.charlotte import store as storemod
from src.features.charlotte.crawl import resolve_props, weave

# Live schemas carry emoji prefixes — fixtures reproduce that so a literal
# property comparison anywhere in the pipeline fails these tests.
SCHEMAS = {
    "contacts": {"Name", "🏢 Employed By", "Type", "Description"},
    "companies": {"Name"},
    "funds": {"Fund Name", "Company", "Introduced By", "Represented By",
              "Known LPs", "Status", "Quality", "Weybourne Comments",
              "Strategy Description", "Asset Class", "Geographic Focus",
              "Responsible Analyst"},
    "notes": {"Name", "Fund", "Attendees", "Note Type", "Date"},
}


def card(cid, name, relations=None, plain=None, archived=False):
    return {"id": cid, "name": name, "archived": archived,
            "plain": plain or {}, "relations": relations or {}}


class TestWeave:
    def test_emoji_property_names_resolve(self):
        props = resolve_props(SCHEMAS)
        assert props["employed_by"] == "🏢 Employed By"
        assert props["known_lps"] == "Known LPs"
        # Not yet added in Notion — resolves empty, never guessed.
        assert props["past_employers"] == ""

    def test_legacy_recommended_by_still_maps_to_known_lp(self):
        schemas = dict(SCHEMAS)
        schemas["funds"] = (SCHEMAS["funds"] - {"Known LPs"}) | {"Recommended By"}
        assert resolve_props(schemas)["known_lps"] == "Recommended By"

    def test_employment_edge_via_emoji_relation(self):
        props = resolve_props(SCHEMAS)
        cards = {
            "contacts": [card("p1", "Jane Doe",
                              relations={"🏢 Employed By": ["co1"]},
                              plain={"Type": "GP - Investments"})],
            "companies": [card("co1", "HyT Capital")],
            "funds": [], "notes": [],
        }
        nodes, edges, _ = weave(cards, props)
        assert nodes["p1"]["contact_type"] == "GP - Investments"
        assert edges == [{"a": "p1", "b": "co1", "type": "employed_by",
                          "evidence": []}]

    def test_responsible_analyst_links_contact_by_name(self):
        props = resolve_props(SCHEMAS)
        cards = {
            "contacts": [card("p1", "Jane Simpson"),
                         card("p2", "Amy Zhao"),
                         card("p3", "Amy Zhao")],
            "companies": [],
            "funds": [card("f1", "Quadrant Growth Fund",
                           plain={"Responsible Analyst":
                                  ["u-jane", "u-amy"]}),
                      card("f2", "Orphan Fund")],
            "notes": [],
        }
        user_names = {"u-jane": "jane  SIMPSON", "u-amy": "Amy Zhao"}
        nodes, edges, _ = weave(cards, props, user_names)
        # Matching is whitespace/case-insensitive; a name shared by two
        # contacts (the Amy Zhaos) is skipped, never guessed.
        assert edges == [{"a": "p1", "b": "f1", "type": "responsible_for",
                          "evidence": []}]
        # Resolved names ride on the fund node either way.
        assert nodes["f1"]["analyst"] == ["jane  SIMPSON", "Amy Zhao"]
        assert "analyst" not in nodes["f2"]

    def test_analyst_fallback_ladder_matches_conservatively(self):
        props = resolve_props(SCHEMAS)
        cards = {
            "contacts": [card("p1", "Jinghan Chen"),        # reversed order
                         card("p2", "Gabriella Waspe"),     # email display
                         card("p3", "Liang Jie Choo"),      # containment
                         card("p4", "Claudio Siniscalco"),
                         card("p5", "Claudio Giuliano"),
                         # "Claudio" alone is ambiguous — the confirmed
                         # alias points it at Cadei, never a guess.
                         card("p6", "Claudio Cadei")],
            "companies": [],
            "funds": [card("f1", "Fund A",
                           plain={"Responsible Analyst": ["u1"]}),
                      card("f2", "Fund B",
                           plain={"Responsible Analyst": ["u2"]}),
                      card("f3", "Fund C",
                           plain={"Responsible Analyst": ["u3"]}),
                      card("f4", "Fund D",
                           plain={"Responsible Analyst": ["u4"]})],
            "notes": [],
        }
        user_names = {"u1": "Chen Jinghan",
                      "u2": "gabriella.waspe@weybourne.co.uk",
                      "u3": "Liang Jie",
                      "u4": "Claudio"}
        _, edges, _ = weave(cards, props, user_names)
        got = {(e["a"], e["b"]) for e in edges}
        assert got == {("p1", "f1"), ("p2", "f2"), ("p3", "f3"),
                       ("p6", "f4")}

    def test_weave_without_user_names_adds_no_analyst_edges(self):
        props = resolve_props(SCHEMAS)
        cards = {
            "contacts": [card("p1", "Jane Simpson")],
            "companies": [],
            "funds": [card("f1", "Quadrant Growth Fund",
                           plain={"Responsible Analyst": ["u-jane"]})],
            "notes": [],
        }
        nodes, edges, _ = weave(cards, props)
        assert edges == [] and "analyst" not in nodes["f1"]

    def test_blank_named_company_never_becomes_a_hub(self):
        props = resolve_props(SCHEMAS)
        cards = {
            "contacts": [card("p1", "Jane Doe",
                              relations={"🏢 Employed By": ["ghost"]})],
            "companies": [card("ghost", "   ")],
            "funds": [], "notes": [],
        }
        nodes, edges, _ = weave(cards, props)
        assert "ghost" not in nodes
        assert edges == []

    def test_archived_pages_are_dropped_with_their_edges(self):
        props = resolve_props(SCHEMAS)
        cards = {
            "contacts": [card("p1", "Jane Doe",
                              relations={"🏢 Employed By": ["co1"]})],
            "companies": [card("co1", "Old Shop", archived=True)],
            "funds": [], "notes": [],
        }
        nodes, edges, _ = weave(cards, props)
        assert "co1" not in nodes and edges == []

    def test_notes_are_nodes_and_evidence(self):
        props = resolve_props(SCHEMAS)
        cards = {
            "contacts": [card("p1", "Jane"), card("p2", "Amir")],
            "companies": [],
            "funds": [card("f1", "Alpha Fund")],
            "notes": [card("n1", "Meeting with Alpha",
                           relations={"Fund": ["f1"],
                                      "Attendees": ["p1", "p2"]},
                           plain={"Note Type": "LP Meeting",
                                  "Date": "2026-07-01"})],
        }
        nodes, edges, _ = weave(cards, props)
        assert nodes["n1"]["kind"] == "note"
        triples = {(e["a"], e["b"], e["type"]) for e in edges}
        assert ("n1", "f1", "about") in triples
        assert ("p1", "n1", "attended") in triples
        assert ("p2", "n1", "attended") in triples
        # The direct evidence edge stays — LP tiers read from it.
        discussed = sorted(e["a"] for e in edges if e["type"] == "discussed")
        assert discussed == ["p1", "p2"]
        ev = next(e for e in edges
                  if e["type"] == "discussed")["evidence"][0]
        assert ev["title"] == "Meeting with Alpha"
        assert ev["note_type"] == "LP Meeting"

    def test_fund_multiselects_stored_as_lists(self):
        props = resolve_props(SCHEMAS)
        cards = {
            "contacts": [], "companies": [], "notes": [],
            "funds": [card("f1", "Alpha Fund",
                           plain={"Asset Class": ["PE - Buyout",
                                                  "PE - Growth Equity"],
                                  "Geographic Focus": "US, Europe"})],
        }
        nodes, _, _ = weave(cards, props)
        assert nodes["f1"]["asset_class"] == ["PE - Buyout",
                                              "PE - Growth Equity"]
        # A comma-joined string form normalizes to the same list shape.
        assert nodes["f1"]["geography"] == ["US", "Europe"]

    def test_fund_texts_carry_fingerprints(self):
        props = resolve_props(SCHEMAS)
        cards = {
            "contacts": [], "companies": [], "notes": [],
            "funds": [card("f1", "Alpha Fund",
                           plain={"Weybourne Comments": "LPs include KfW",
                                  "Strategy Description": "Credit"})],
        }
        _, _, texts = weave(cards, props)
        assert texts["f1"]["comments"] == "LPs include KfW"
        assert len(texts["f1"]["fp"]) == 16


def snapshot(nodes, edges):
    return {"version": 1, "crawled_at": "2026-08-21T00:00:00Z",
            "counts": {}, "nodes": nodes, "edges": edges, "texts": {}}


class TestEgo:
    def test_hop_limit_is_respected(self):
        g = graphmod.build_graph(snapshot(
            {"a": {"kind": "fund", "label": "A"},
             "b": {"kind": "company", "label": "B"},
             "c": {"kind": "contact", "label": "C"}},
            [{"a": "a", "b": "b", "type": "managed_by"},
             {"a": "c", "b": "b", "type": "employed_by"}]))
        one = graphmod.ego(g, "a", hops=1)
        assert {n["id"] for n in one["nodes"]} == {"a", "b"}
        two = graphmod.ego(g, "a", hops=2)
        assert {n["id"] for n in two["nodes"]} == {"a", "b", "c"}

    def test_no_per_node_fanout_cap(self):
        # A hub shows EVERY neighbor the node budget can hold — there is
        # no per-node cap (removed 23 Aug 2026; a 4k-fund analyst looked
        # like "80 connections"). Only max_nodes truncates, counted.
        nodes = {"hub": {"kind": "fund", "label": "Hub"}}
        edges = []
        spokes = 150
        for i in range(spokes):
            nodes[f"p{i}"] = {"kind": "contact", "label": f"P{i:03d}"}
            edges.append({"a": f"p{i}", "b": "hub", "type": "discussed"})
        g = graphmod.build_graph(snapshot(nodes, edges))
        view = graphmod.ego(g, "hub", hops=1)
        assert len(view["nodes"]) == spokes + 1
        assert view["meta"]["truncated"] is False
        budget = graphmod.ego(g, "hub", hops=1, max_nodes=100)
        assert len(budget["nodes"]) == 100
        hub = next(n for n in budget["nodes"] if n["id"] == "hub")
        assert hub["hidden_neighbors"] == spokes - 99
        assert budget["meta"]["truncated"] is True
        assert budget["meta"]["total_nodes_available"] == spokes + 1

    def test_max_nodes_cap(self):
        nodes = {"hub": {"kind": "fund", "label": "Hub"}}
        edges = []
        for i in range(10):
            nodes[f"p{i}"] = {"kind": "contact", "label": f"P{i}"}
            edges.append({"a": f"p{i}", "b": "hub", "type": "discussed"})
        g = graphmod.build_graph(snapshot(nodes, edges))
        view = graphmod.ego(g, "hub", hops=1, max_nodes=4)
        assert len(view["nodes"]) == 4
        assert view["meta"]["truncated"] is True

    def test_unknown_node_returns_none(self):
        g = graphmod.build_graph(snapshot({}, []))
        assert graphmod.ego(g, "nope") is None

    def test_access_of_prefix_families(self):
        assert graphmod.access_of(["PE - Buyout"]) == "Private"
        assert graphmod.access_of(["PC - Legacy"]) == "Private"
        assert graphmod.access_of(["PRA - Legacy", "PE - Buyout"]) == "Private"
        assert graphmod.access_of(["Hedge Funds - Single strategy"]) == "Public"
        assert graphmod.access_of(["Global Equities - Active"]) == "Public"
        assert graphmod.access_of(["Commods - Precious Metals"]) == "Public"
        assert graphmod.access_of(["Commodities - Others"]) == "Public"
        assert graphmod.access_of(["Other"]) == "Other"
        assert graphmod.access_of([]) == "Other"
        assert graphmod.access_of(None) == "Other"

    def test_ego_payload_carries_grouping_attrs(self):
        g = graphmod.build_graph(snapshot(
            {"f1": {"kind": "fund", "label": "Alpha",
                    "asset_class": ["PE - Buyout"], "geography": ["US"]},
             "c1": {"kind": "company", "label": "Mgr"}},
            [{"a": "f1", "b": "c1", "type": "managed_by"}]))
        by_id = {n["id"]: n for n in graphmod.ego(g, "f1")["nodes"]}
        assert by_id["f1"]["access"] == "Private"
        assert by_id["f1"]["asset_class"] == "PE - Buyout"
        assert by_id["f1"]["geography"] == "US"
        assert "asset_class" not in by_id["c1"]

    def test_full_payload_carries_grouping_attrs(self):
        g = graphmod.build_graph(snapshot(
            {"f1": {"kind": "fund", "label": "Alpha", "quality": "High",
                    "asset_class": ["PE - Buyout", "PE - Legacy"],
                    "geography": ["US"]},
             "p1": {"kind": "contact", "label": "Jane",
                    "contact_type": "GP - Investments"},
             "c1": {"kind": "company", "label": "Shop"}}, []))
        by_id = {n["id"]: n for n in graphmod.full(g)["nodes"]}
        assert by_id["f1"]["access"] == "Private"
        assert by_id["f1"]["asset_class"] == "PE - Buyout"   # first value
        assert by_id["f1"]["geography"] == "US"
        assert by_id["f1"]["quality"] == "High"
        assert by_id["p1"]["contact_type"] == "GP - Investments"
        assert "asset_class" not in by_id["c1"]

    def test_full_payload_uses_index_edges(self):
        g = graphmod.build_graph(snapshot(
            {"a": {"kind": "fund", "label": "A"},
             "b": {"kind": "company", "label": "B"}},
            [{"a": "a", "b": "b", "type": "managed_by"}]))
        out = graphmod.full(g)
        assert [n["id"] for n in out["nodes"]] == ["a", "b"]
        assert out["nodes"][0]["degree"] == 1
        ai, bi, inferred, ti = out["edges"][0]
        assert {out["nodes"][ai]["id"], out["nodes"][bi]["id"]} == {"a", "b"}
        assert inferred == 0
        assert out["types"][ti] == "managed_by"
        assert out["crawled_at"] == "2026-08-21T00:00:00Z"

    def test_old_snapshot_enriches_from_notion_cache(self, tmp_path):
        # A pre-23-Aug snapshot (no asset_class on funds) joins the shared
        # notion cache by page id at load time.
        snap = snapshot({"f1": {"kind": "fund", "label": "Alpha",
                                "status": "", "quality": "High"}}, [])
        (tmp_path / "charlotte_graph.json").write_text(
            json.dumps(snap), encoding="utf-8")
        cache = {"funds": {"records": {"f1": {
            "id": "f1", "asset_class": ["PE - Buyout"],
            "geographic_focus": ["US", " "]}}}}
        (tmp_path / "notion_cache.json").write_text(
            json.dumps(cache), encoding="utf-8")
        g = storemod.cached_graph(base=tmp_path)
        assert g["nodes"]["f1"]["asset_class"] == ["PE - Buyout"]
        assert g["nodes"]["f1"]["geography"] == ["US"]

    def test_new_snapshot_skips_notion_cache_join(self, tmp_path):
        snap = snapshot({"f1": {"kind": "fund", "label": "Alpha",
                                "asset_class": ["Woven - Value"],
                                "geography": []}}, [])
        (tmp_path / "charlotte_graph.json").write_text(
            json.dumps(snap), encoding="utf-8")
        cache = {"funds": {"records": {"f1": {
            "id": "f1", "asset_class": ["Cache - Value"]}}}}
        (tmp_path / "notion_cache.json").write_text(
            json.dumps(cache), encoding="utf-8")
        g = storemod.cached_graph(base=tmp_path)
        assert g["nodes"]["f1"]["asset_class"] == ["Woven - Value"]

    def test_inferred_lp_mention_creates_external_leaf(self):
        snap = snapshot({"f1": {"kind": "fund", "label": "Alpha"}}, [])
        inferred = {"f1": {"fp": "x", "found": [
            {"kind": "lp", "name": "British Business Bank",
             "quote": "Cornerstone investors include BBB"}]}}
        g = graphmod.build_graph(snap, inferred)
        ext = [n for n in g["nodes"] if n.startswith("ext:")]
        assert len(ext) == 1
        assert g["nodes"][ext[0]]["kind"] == "external"
        assert g["edges"][0]["inferred"] is True
        assert g["edges"][0]["type"] == "lp_mention"
