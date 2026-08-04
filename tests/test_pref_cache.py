"""Page-text cache resilience: an expired entry whose refetch fails serves
the stale copy instead of erroring (the preference screen keeps working
through a Notion outage)."""
import time

from src.connectors.notion_client import NotionConnector


def test_stale_page_text_served_when_refetch_fails(monkeypatch):
    n = NotionConnector.__new__(NotionConnector)
    n.live = True

    stored = {"page_text": {"p1": {"text": "the preferences", "at": 0}}}  # ancient
    monkeypatch.setattr(NotionConnector, "_disk_load", lambda self: stored)
    monkeypatch.setattr(NotionConnector, "_disk_save", lambda self, s: None)

    def boom(self, page_id, depth=0, max_depth=2):
        raise RuntimeError("notion down")
    monkeypatch.setattr(NotionConnector, "_blocks_text", boom)

    assert n.get_page_text("p1") == "the preferences"


def test_fresh_cache_hit_skips_the_network(monkeypatch):
    n = NotionConnector.__new__(NotionConnector)
    n.live = True
    stored = {"page_text": {"p1": {"text": "cached", "at": time.time()}}}
    monkeypatch.setattr(NotionConnector, "_disk_load", lambda self: stored)

    def boom(self, page_id, depth=0, max_depth=2):
        raise AssertionError("should not fetch")
    monkeypatch.setattr(NotionConnector, "_blocks_text", boom)

    assert n.get_page_text("p1") == "cached"
