"""Stage 2 of a MENTIONS card: one bounded quick web look, cached on disk.

The invariants under test are the ones that keep a meeting safe: at most one
quick-look subprocess at a time machine-wide, excess demand dropped rather
than queued, a failed gather freeing its slot, and the quick cache never
bleeding into web_research's real dossier store (which would starve prep of
a genuine gather for 14 days).
"""
import json
import threading
import time

import pytest

from src.features import live_entities, web_research
from tests.fakes import FakeClient


PAYLOAD = {"summary": "An Australian real assets manager.",
           "news": [{"headline": "Closed Fund IV", "date": "Aug 2026",
                     "url": "https://example.com/a"}],
           "confidence": "high", "not_found": False}


@pytest.fixture(autouse=True)
def clean_state():
    live_entities._QUICK_INFLIGHT.clear()
    yield
    live_entities._QUICK_INFLIGHT.clear()


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestCacheRoundTrip:
    def test_a_gather_lands_in_the_quick_store_and_serves_cached(self, tmp_path):
        status = live_entities.request_quick_news(
            "Fife Capital", "", "discussed their fund", lambda: FakeClient(PAYLOAD),
            quick_store=tmp_path)
        assert status == "pending"
        assert wait_for(lambda: live_entities.news_status(
            "Fife Capital", "", quick_store=tmp_path)[0] == "cached")
        status, news = live_entities.news_status("Fife Capital", "",
                                                 quick_store=tmp_path)
        assert news["summary"].startswith("An Australian")
        # And a fresh request is served straight from disk, no new call.
        counting = FakeClient(PAYLOAD)
        assert live_entities.request_quick_news(
            "Fife Capital", "", "", lambda: counting, quick_store=tmp_path) == "cached"
        assert counting.calls == []

    def test_the_quick_ttl_is_three_days_not_fourteen(self, tmp_path):
        key = web_research.research_key("Fife Capital")
        web_research.save_dossier(key, {**PAYLOAD,
                                        "gathered_at": time.time() - 4 * 86400},
                                  store_dir=tmp_path)
        assert live_entities.news_status("Fife Capital", "",
                                         quick_store=tmp_path)[0] == "none"

    def test_quick_files_are_invisible_to_the_real_research_store(self, tmp_path, monkeypatch):
        """A quick blob in data/research/ proper would satisfy prep's
        freshness check while carrying none of the fields prep reads."""
        monkeypatch.setattr(live_entities, "QUICK_DIR", tmp_path / "quick")
        status = live_entities.request_quick_news(
            "Fife Capital", "", "", lambda: FakeClient(PAYLOAD))
        assert status == "pending"
        assert wait_for(lambda: live_entities.news_status("Fife Capital", "")[0] == "cached")
        key = web_research.research_key("Fife Capital")
        assert web_research.load_dossier(key, store_dir=tmp_path / "quick") is not None
        assert web_research.get_dossier(None, "Fife Capital", gather=False) == (None, "none")


class TestBounds:
    def test_a_second_request_for_the_same_key_does_not_spawn_twice(self, tmp_path):
        release = threading.Event()

        def slow_factory():
            release.wait(timeout=5)
            return FakeClient(PAYLOAD)

        first = live_entities.request_quick_news("Fife Capital", "", "",
                                                 slow_factory, quick_store=tmp_path)
        second = live_entities.request_quick_news("Fife Capital", "", "",
                                                  slow_factory, quick_store=tmp_path)
        assert (first, second) == ("pending", "pending")
        assert len(live_entities._QUICK_INFLIGHT) == 1
        release.set()

    def test_at_capacity_a_new_entity_is_dropped_not_queued(self, tmp_path):
        """The whole point of the semaphore: a backlog that cannot form."""
        release = threading.Event()

        def slow_factory():
            release.wait(timeout=5)
            return FakeClient(PAYLOAD)

        assert live_entities.request_quick_news(
            "Fife Capital", "", "", slow_factory, quick_store=tmp_path) == "pending"
        assert live_entities.request_quick_news(
            "Brookfield", "", "", slow_factory, quick_store=tmp_path) == "none"
        assert "brookfield" not in {k for k in live_entities._QUICK_INFLIGHT}
        release.set()
        assert wait_for(lambda: live_entities.news_status(
            "Fife Capital", "", quick_store=tmp_path)[0] == "cached")

    def test_a_failed_gather_frees_its_slot(self, tmp_path):
        """The finally contract: failure must not leak the semaphore, or the
        feature silently dies for the rest of the server's life."""
        def broken_factory():
            raise RuntimeError("no backend")

        live_entities.request_quick_news("Fife Capital", "", "",
                                         broken_factory, quick_store=tmp_path)
        assert wait_for(lambda: not live_entities._QUICK_INFLIGHT)
        # Nothing cached, and the slot is free for the next attempt.
        assert live_entities.news_status("Fife Capital", "",
                                         quick_store=tmp_path)[0] == "none"
        assert live_entities.request_quick_news(
            "Fife Capital", "", "", lambda: FakeClient(PAYLOAD),
            quick_store=tmp_path) == "pending"
        assert wait_for(lambda: live_entities.news_status(
            "Fife Capital", "", quick_store=tmp_path)[0] == "cached")


class TestQuickLook:
    def test_news_is_trimmed_to_three(self):
        many = {**PAYLOAD, "news": [{"headline": f"h{i}", "date": "", "url": ""}
                                    for i in range(6)]}
        out = live_entities.quick_look(FakeClient(many), "Fife Capital")
        assert len(out["news"]) == 3
        assert out["gathered_on"]

    def test_web_tools_are_requested_with_a_typeerror_fallback(self):
        """CLI clients take extra_allowed_tools; the SDK backend raises
        TypeError on the unknown kwarg and the call runs without web."""
        seen = []

        class Messages:
            def create(self, **kwargs):
                seen.append(kwargs)
                if "extra_allowed_tools" in kwargs:
                    raise TypeError("unexpected keyword")
                from tests.fakes import FakeResponse, FakeTextBlock
                return FakeResponse(content=[FakeTextBlock(text=json.dumps(PAYLOAD))])

        class Client:
            messages = Messages()

        out = live_entities.quick_look(Client(), "Fife Capital")
        assert seen[0]["extra_allowed_tools"] == ["WebSearch", "WebFetch"]
        assert "extra_allowed_tools" not in seen[1]
        assert out["summary"]
