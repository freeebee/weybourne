"""Charlotte's Web — API surface over a temp snapshot."""
import pytest
from fastapi.testclient import TestClient

import api.main as api
from src.features.charlotte import store as cstore

SNAP = {
    "version": 1, "crawled_at": "2026-08-21T00:00:00Z",
    "counts": {"contacts": 1, "companies": 1, "funds": 1, "notes": 1},
    "nodes": {
        "f1": {"kind": "fund", "label": "Alpha Fund", "status": "Met"},
        "co1": {"kind": "company", "label": "Alpha Capital"},
        "p1": {"kind": "contact", "label": "Jane Doe",
               "contact_type": "LP - Institutional / SFO"},
    },
    "edges": [
        {"a": "f1", "b": "co1", "type": "managed_by"},
        {"a": "p1", "b": "f1", "type": "discussed",
         "evidence": [{"kind": "note", "id": "n1", "title": "Alpha catch-up",
                       "date": "2026-05-01", "note_type": "GP Meeting"}]},
    ],
    "texts": {},
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(cstore, "_DATA", tmp_path)
    monkeypatch.setattr(cstore, "_CACHE", None)
    return TestClient(api.app)


class TestStatusAndSearch:
    def test_not_ready_before_first_crawl(self, client):
        body = client.get("/api/charlotte/status").json()
        assert body["ready"] is False
        assert client.get("/api/charlotte/ego?node=f1").json()["ready"] is False

    def test_search_returns_ids_with_context(self, client):
        cstore.save_snapshot(SNAP)
        body = client.get("/api/charlotte/search?q=alpha fund").json()
        assert body["ready"] is True
        top = body["results"][0]
        assert top["id"] == "f1" and top["kind"] == "fund"
        assert top["sub"] == "Alpha Capital"   # the manager, for disambiguation

    def test_search_kind_filter(self, client):
        cstore.save_snapshot(SNAP)
        body = client.get("/api/charlotte/search?q=alpha&kinds=company").json()
        assert [r["id"] for r in body["results"]] == ["co1"]


class TestEgo:
    def test_fund_center_carries_lp_candidates(self, client):
        cstore.save_snapshot(SNAP)
        body = client.get("/api/charlotte/ego?node=f1").json()
        assert body["ready"] is True
        assert {n["id"] for n in body["nodes"]} == {"f1", "co1", "p1"}
        assert body["lp_candidates"][0]["id"] == "p1"
        assert body["lp_candidates"][0]["tier"] == "T1"
        lp_node = next(n for n in body["nodes"] if n["id"] == "p1")
        assert lp_node["lp_candidate"] is True
        assert body["meta"]["crawled_at"] == "2026-08-21T00:00:00Z"

    def test_wild_params_are_clamped_not_errors(self, client):
        cstore.save_snapshot(SNAP)
        body = client.get(
            "/api/charlotte/ego?node=f1&hops=99&max_nodes=999999").json()
        assert body["ready"] is True and len(body["nodes"]) == 3

    def test_unknown_node_is_a_404(self, client):
        cstore.save_snapshot(SNAP)
        assert client.get("/api/charlotte/ego?node=nope").status_code == 404


class TestRefreshGuards:
    def test_refresh_refuses_during_a_recording(self, client, monkeypatch):
        monkeypatch.setattr(api, "live_recording_active", lambda: True)
        r = client.post("/api/charlotte/refresh")
        assert r.status_code == 409
        assert "recording" in r.json()["detail"].lower()

    def test_refresh_refuses_beside_a_felix_run(self, client, monkeypatch):
        monkeypatch.setattr(api, "live_recording_active", lambda: False)
        job = {"id": "x", "kind": "felix", "status": "running"}
        monkeypatch.setitem(api._JOBS, "x", job)
        r = client.post("/api/charlotte/refresh")
        assert r.status_code == 409
        assert "rate limit" in r.json()["detail"].lower()
