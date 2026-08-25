"""Stage 2b of a MENTIONS card: one Haiku line per prior-contact item.

The user's words (18 Aug 2026): a raw note excerpt clipped mid-sentence is
not an answer — each PRIOR CONTACT and SAID BEFORE line must become one
sentence about the mentioned entity. Same safety invariants as the news
look: the SHARED one-subprocess semaphore, non-blocking drop, disk cache,
and a stage-1 card that only ever READS that cache.
"""
import threading
import time

import pytest

from src.features import live_entities
from tests.fakes import FakeClient


def _card(notes=None, said=None):
    return {
        "notes": notes if notes is not None else [
            {"date": "2026-08-05", "title": "Call with Powerlaw (Akkadian)",
             "note_type": "Meeting",
             "excerpt": "The pitch rested on a genuinely differentiated "
                        "structure: daily liquidity through a listed vehicle, "
                        "a 2.5% management fee with no carry."}],
        "said_before": said if said is not None else [
            {"date": "2026-08-12", "title": "GP catch-up",
             "excerpt": "…we compared Powerlaw's fee load against the usual "
                        "two and twenty and thought it competitive…"}],
    }


def _payload(card):
    items = live_entities.summary_items(card)
    return {"summaries": [
        {"ref": it["ref"], "line": f"One line about {it['kind']}."}
        for it in items]}


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


class TestSummaryKey:
    """The cache key must carry the ENTITY. research_key's second argument
    is a company override, not a namespace — passing "mention-lines" there
    (the original wiring, caught 18 Aug 2026) keyed every entity's summaries
    to the same file, so each gather overwrote the previous entity's."""

    def test_different_entities_get_different_keys(self):
        assert (live_entities._summary_key("Powerlaw")
                != live_entities._summary_key("Akkadian"))

    def test_key_is_distinct_from_the_news_key_for_the_same_entity(self):
        from src.features.web_research import research_key
        assert live_entities._summary_key("Powerlaw") != research_key("Powerlaw")

    def test_unkeyable_name_stays_unkeyable(self):
        assert live_entities._summary_key("") == ""


class TestSummaryItems:
    def test_notes_and_transcripts_become_items_with_stable_refs(self):
        items = live_entities.summary_items(_card())
        assert [it["kind"] for it in items] == ["note", "transcript"]
        assert items[0]["ref"] == "note:2026-08-05:Call with Powerlaw (Akkadian)"
        assert items[1]["ref"].startswith("said:2026-08-12:")

    def test_blank_excerpts_are_skipped(self):
        card = _card(notes=[{"date": "d", "title": "t", "excerpt": "  "}], said=[])
        assert live_entities.summary_items(card) == []

    def test_note_items_prefer_the_wider_mention_context(self):
        """Haiku reads the window around the mention, not the two-line
        display excerpt — a one-liner about the entity needs the sentences
        where the entity actually comes up."""
        card = _card(notes=[{
            "date": "2026-07-31", "title": "Intro call",
            "excerpt": "…benchmarked against Advantage…",
            "mention_context": "…the fuller discussion where they benchmarked "
                               "themselves against Advantage on Japan buyouts…"}],
            said=[])
        items = live_entities.summary_items(card)
        assert items[0]["text"].startswith("…the fuller discussion")


class TestSummarizeCall:
    def test_haiku_gets_entity_and_items_and_lines_come_back_by_ref(self):
        card = _card()
        client = FakeClient(_payload(card))
        out = live_entities.summarize_mentions(
            client, "Powerlaw", live_entities.summary_items(card))
        assert set(out["lines"]) == {it["ref"] for it in
                                     live_entities.summary_items(card)}
        kwargs = client.calls[0]
        assert kwargs["model"] == live_entities.config.FAST_MODEL
        user = kwargs["messages"][0]["content"]
        assert "ENTITY: Powerlaw" in user
        assert "daily liquidity through a listed vehicle" in user

    def test_whitespace_collapsed_and_blank_lines_dropped(self):
        card = _card()
        items = live_entities.summary_items(card)
        payload = {"summaries": [
            {"ref": items[0]["ref"], "line": "  A\n   multi line  answer. "},
            {"ref": items[1]["ref"], "line": "   "}]}
        out = live_entities.summarize_mentions(FakeClient(payload), "P", items)
        assert out["lines"][items[0]["ref"]] == "A multi line answer."
        assert items[1]["ref"] not in out["lines"]


class TestApplyFromCache:
    def test_round_trip_swaps_excerpts_and_reports_ready(self, tmp_path):
        card = _card()
        status = live_entities.request_mention_summaries(
            "Powerlaw", live_entities.summary_items(card),
            lambda: FakeClient(_payload(card)), quick_store=tmp_path)
        assert status == "pending"
        assert wait_for(lambda: live_entities.summaries_status(
            "Powerlaw", quick_store=tmp_path) == "ready")
        live_entities.apply_mention_summaries(card, "Powerlaw",
                                              quick_store=tmp_path)
        assert card["summaries"] == "ready"
        assert card["notes"][0]["excerpt"] == "One line about note."
        assert card["said_before"][0]["excerpt"] == "One line about transcript."

    def test_a_new_item_makes_the_cache_stale(self, tmp_path):
        card = _card()
        live_entities.request_mention_summaries(
            "Powerlaw", live_entities.summary_items(card),
            lambda: FakeClient(_payload(card)), quick_store=tmp_path)
        assert wait_for(lambda: live_entities.summaries_status(
            "Powerlaw", quick_store=tmp_path) == "ready")
        card["notes"].append({"date": "2026-08-18", "title": "New note",
                              "excerpt": "Fresh discussion of Powerlaw."})
        live_entities.apply_mention_summaries(card, "Powerlaw",
                                              quick_store=tmp_path)
        # The verbatim text stays on screen; status says a gather is needed.
        assert card["summaries"] == "none"
        assert "Fresh discussion" in card["notes"][-1]["excerpt"]

    def test_nothing_to_summarise_is_ready_not_pending(self, tmp_path):
        card = {"notes": [], "said_before": []}
        live_entities.apply_mention_summaries(card, "X", quick_store=tmp_path)
        assert card["summaries"] == "ready"


class TestSafetyInvariants:
    def test_busy_semaphore_drops_not_queues(self, tmp_path):
        card = _card()
        assert live_entities._QUICK_SEMAPHORE.acquire(blocking=False)
        try:
            status = live_entities.request_mention_summaries(
                "Powerlaw", live_entities.summary_items(card),
                lambda: FakeClient(_payload(card)), quick_store=tmp_path)
            assert status == "none"
            assert live_entities._QUICK_INFLIGHT == set()
        finally:
            live_entities._QUICK_SEMAPHORE.release()

    def test_a_failed_gather_frees_the_shared_slot(self, tmp_path):
        def boom():
            raise RuntimeError("no CLI")
        card = _card()
        status = live_entities.request_mention_summaries(
            "Powerlaw", live_entities.summary_items(card), boom,
            quick_store=tmp_path)
        assert status == "pending"
        assert wait_for(lambda: not live_entities._QUICK_INFLIGHT)
        # The slot is free again for anyone.
        assert live_entities._QUICK_SEMAPHORE.acquire(blocking=False)
        live_entities._QUICK_SEMAPHORE.release()
        assert live_entities.summaries_status("Powerlaw",
                                              quick_store=tmp_path) == "none"

    def test_summary_and_news_keys_do_not_collide(self, tmp_path):
        card = _card()
        live_entities.request_mention_summaries(
            "Powerlaw", live_entities.summary_items(card),
            lambda: FakeClient(_payload(card)), quick_store=tmp_path)
        assert wait_for(lambda: live_entities.summaries_status(
            "Powerlaw", quick_store=tmp_path) == "ready")
        status, _news = live_entities.news_status("Powerlaw", "",
                                                  quick_store=tmp_path)
        assert status == "none"   # a summary cache is not a news cache
