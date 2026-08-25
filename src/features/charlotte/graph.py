"""Pure graph assembly and ego-network extraction for Charlotte's Web.

Everything here works on plain dicts so it is trivially testable with
fixtures. Edge shape throughout:
    {"a": id, "b": id, "type": str, "inferred": bool,
     "evidence": [{"kind": "note"|"relation"|"quote", ...}]}
Solid edges come from real Notion relations; inferred (dashed) ones from
the Phase-3 extraction cache, each carrying the quote that produced it.
"""
from __future__ import annotations

from typing import Iterator, Optional

HOPS_MAX = 3
# High ceiling: the local canvas renders with the global view's batched
# economics, so "everything a mega-hub touches" fits in one ego view
# (Jane Simpson: 6.6k unique hop-1 neighbors). Still a backstop — a
# 3-hop walk from a dense node would otherwise be the whole graph.
NODES_MAX = 20000
NODES_DEFAULT = 300
# There is deliberately NO per-node fanout cap (removed 23 Aug 2026 at the
# user's request — an analyst responsible for 4k funds looked like "80
# connections"). The only budget is max_nodes across the whole view, and
# whatever it drops is COUNTED on the node (hidden_neighbors) — a silent
# cut would read as "that's everyone".


def build_graph(snapshot: dict, inferred: Optional[dict] = None) -> dict:
    """Snapshot (+ optional inferred cache) -> adjacency-indexed graph."""
    nodes: dict = {}
    for nid, n in (snapshot.get("nodes") or {}).items():
        nodes[nid] = dict(n)
    edges: list = []
    adj: dict = {}

    def add_edge(e: dict) -> None:
        if e["a"] not in nodes or e["b"] not in nodes or e["a"] == e["b"]:
            return
        idx = len(edges)
        edges.append(e)
        adj.setdefault(e["a"], []).append(idx)
        adj.setdefault(e["b"], []).append(idx)

    for e in snapshot.get("edges") or []:
        add_edge({"a": e.get("a", ""), "b": e.get("b", ""),
                  "type": e.get("type", ""),
                  "inferred": bool(e.get("inferred")),
                  "evidence": e.get("evidence") or []})

    # Phase 3 extraction results: dashed edges. An LP name with no CRM match
    # becomes an explicit external leaf node — labeled, never silently
    # merged into a real record.
    for rec_id, entry in (inferred or {}).items():
        for f in entry.get("found") or []:
            quote_ev = [{"kind": "quote", "quote": f.get("quote", ""),
                         "source": f.get("source", "")}]
            kind = f.get("kind", "")
            if kind == "lp" and rec_id in nodes:
                other = f.get("matched_id") or ""
                if not other and (f.get("name") or "").strip():
                    other = "ext:" + " ".join(f["name"].lower().split())
                    nodes.setdefault(other, {
                        "kind": "external", "label": f["name"].strip()})
                if other:
                    add_edge({"a": other, "b": rec_id, "type": "lp_mention",
                              "inferred": True, "evidence": quote_ev})
            elif kind == "past_employer" and rec_id in nodes:
                other = f.get("matched_id") or ""
                if other:
                    add_edge({"a": rec_id, "b": other, "type": "previously_at",
                              "inferred": True, "evidence": quote_ev})

    degree = {nid: len(adj.get(nid, [])) for nid in nodes}
    return {"nodes": nodes, "edges": edges, "adj": adj, "degree": degree,
            "meta": {"crawled_at": snapshot.get("crawled_at", ""),
                     "counts": snapshot.get("counts") or {}}}


# Public/private is not a populated Notion property — it is implied by
# the Asset Class prefix family. The FIRST listed class wins for
# multi-class funds.
_PRIVATE_FAMILIES = {"PE", "PC", "PD", "PRA"}
_PUBLIC_FAMILIES = {"Hedge Funds", "Global Equities", "Liquid Credit",
                    "Commods", "Commodities"}


def access_of(asset_classes) -> str:
    """"Private" / "Public" / "Other" from a fund's asset-class list."""
    first = str((asset_classes or [""])[0] or "")
    family = first.split("-", 1)[0].strip()
    if family in _PRIVATE_FAMILIES:
        return "Private"
    if family in _PUBLIC_FAMILIES:
        return "Public"
    return "Other"


def full(graph: dict) -> dict:
    """The entire graph as one slim payload for the global view. Nodes carry
    only what the renderer needs; edges are index tuples into the node list
    plus a shared type table (IDs are 36-char UUIDs and type strings repeat
    tens of thousands of times — inlining either would bloat the payload).
    Grouping attrs ride along as plain strings, omitted when empty."""
    ids = list(graph["nodes"].keys())
    idx = {nid: i for i, nid in enumerate(ids)}
    nodes = []
    for nid in ids:
        n = graph["nodes"][nid]
        out = {"id": nid, "kind": n.get("kind", ""),
               "label": str(n.get("label", "")),
               "degree": graph["degree"].get(nid, 0)}
        if out["kind"] == "fund":
            ac = n.get("asset_class") or []
            gf = n.get("geography") or []
            out["access"] = access_of(ac)
            if ac:
                out["asset_class"] = str(ac[0])
            if gf:
                out["geography"] = str(gf[0])
            if n.get("quality"):
                out["quality"] = str(n["quality"])
        elif out["kind"] == "contact" and n.get("contact_type"):
            out["contact_type"] = str(n["contact_type"])
        nodes.append(out)
    type_ids: dict = {}
    types: list = []
    edges = []
    for e in graph["edges"]:
        ti = type_ids.get(e["type"])
        if ti is None:
            ti = type_ids[e["type"]] = len(types)
            types.append(e["type"])
        edges.append([idx[e["a"]], idx[e["b"]],
                      1 if e.get("inferred") else 0, ti])
    return {"nodes": nodes, "edges": edges, "types": types,
            "crawled_at": graph["meta"]["crawled_at"]}


def neighbors(graph: dict, node_id: str) -> Iterator[tuple]:
    """(other_id, edge) pairs for every edge touching node_id."""
    for idx in graph["adj"].get(node_id, []):
        e = graph["edges"][idx]
        yield (e["b"] if e["a"] == node_id else e["a"]), e


def ego(graph: dict, node_id: str, hops: int = 2,
        max_nodes: int = NODES_DEFAULT, lp_ids: Optional[set] = None) -> Optional[dict]:
    """BFS neighborhood of node_id with one honesty cap: the global node
    budget. Hop-1 fills completely before hop-2 is admitted (BFS order);
    whatever the budget drops is counted, never silently cut. Returns
    None for an unknown node."""
    if node_id not in graph["nodes"]:
        return None
    hops = max(1, min(HOPS_MAX, int(hops or 2)))
    max_nodes = max(1, min(NODES_MAX, int(max_nodes or NODES_DEFAULT)))
    lp_ids = lp_ids or set()

    included = {node_id}
    hidden: dict = {}
    truncated = False
    frontier = [node_id]
    for _hop in range(hops):
        nxt: list = []
        for nid in frontier:
            # Rank this node's neighbors: LP candidates first, then by how
            # much note evidence connects them, then by overall degree.
            weight: dict = {}
            for other, e in neighbors(graph, nid):
                w = weight.setdefault(other, 0)
                weight[other] = w + 1 + len(e.get("evidence") or [])
            ranked = sorted(
                weight,
                key=lambda o: (0 if o in lp_ids else 1, -weight[o],
                               -graph["degree"].get(o, 0),
                               str(graph["nodes"].get(o, {}).get("label", ""))))
            for other in ranked:
                if other in included:
                    continue
                if len(included) >= max_nodes:
                    hidden[nid] = hidden.get(nid, 0) + 1
                    truncated = True
                    continue
                included.add(other)
                nxt.append(other)
        frontier = nxt
    # Every edge with both ends in view — including edges between two
    # non-center nodes, which is what makes shared employers/funds legible.
    out_edges, seen = [], set()
    for nid in included:
        for idx in graph["adj"].get(nid, []):
            if idx in seen:
                continue
            e = graph["edges"][idx]
            if e["a"] in included and e["b"] in included:
                seen.add(idx)
                out_edges.append(e)
    out_nodes = []
    for nid in included:
        n = graph["nodes"][nid]
        out = {
            "id": nid, "kind": n.get("kind", ""), "label": n.get("label", ""),
            "degree": graph["degree"].get(nid, 0),
            "contact_type": n.get("contact_type", ""),
            "status": n.get("status", ""),
            "quality": n.get("quality", ""),
            "lp_candidate": nid in lp_ids,
            "hidden_neighbors": hidden.get(nid, 0)}
        # Grouping attrs, same shape as full() — the LAYERS panel works
        # on the local view too.
        if out["kind"] == "fund":
            ac = n.get("asset_class") or []
            gf = n.get("geography") or []
            out["access"] = access_of(ac)
            if ac:
                out["asset_class"] = str(ac[0])
            if gf:
                out["geography"] = str(gf[0])
        out_nodes.append(out)
    return {"center": node_id, "nodes": out_nodes, "edges": out_edges,
            "meta": {"truncated": truncated or bool(hidden),
                     "total_nodes_available": len(included) + sum(hidden.values())}}
