"""The web research is gathered once and shared.

The screen and the briefing are two readings of the same firm. Before this they
researched independently — and preparing them at different times meant paying
for the same searches twice.
"""
import json
import time

import pytest

from src.features.web_research import (
    dossier_sources,
    dossier_text,
    gather_dossier,
    get_dossier,
    is_fresh,
    research_block,
    research_key,
)
from tests.fakes import FakeClient

DOSSIER = {
    "entity": "Northlight Software Partners",
    "firm": "Founded 2011, Boston. Employee-owned.",
    "people": [{"name": "R. Okafor", "role": "Managing partner",
                "note": "No meaningful public record found."}],
    "vehicles": "Fund II closed at $900m in 2022. Fund III in market.",
    "recent": [{"headline": "Fund III first close", "detail": "$600m",
                "date": "22 May 2026", "url": "https://example.com/close"}],
    "flags": [],
    "collisions": "Unrelated to Northlight Capital (Sydney).",
    "not_found": "No LPA or side-letter terms are public.",
    "sources": [{"title": "Trade press", "url": "https://example.com/close",
                 "note": "First close"}],
}


@pytest.fixture
def store(tmp_path):
    return tmp_path / "research"


class TestKey:
    def test_the_firm_is_the_key_not_the_person(self):
        """A contact prep and a fund screen ask about one organisation."""
        assert (research_key("Amy Zhao", "BAI Capital")
                == research_key("BAI Capital", ""))

    def test_vintages_share_one_dossier(self):
        """Fund III and Fund IV are the same manager."""
        assert (research_key("Northlight Software Partners III")
                == research_key("Northlight Software Partners IV"))

    def test_legal_suffixes_do_not_split_the_cache(self):
        assert (research_key("Northlight Software Partners LP")
                == research_key("Northlight Software"))

    def test_nothing_to_research_has_no_key(self):
        assert research_key("", "") == ""


class TestSharing:
    def test_the_second_consumer_does_not_search(self, store):
        """The screen runs, then the briefing — one set of searches."""
        client = FakeClient(DOSSIER)
        first, origin = get_dossier(client, "Northlight", store_dir=store)
        assert origin == "gathered"
        second, origin2 = get_dossier(client, "Northlight", store_dir=store)
        assert origin2 == "cache"
        assert second["firm"] == first["firm"]
        assert len(client.calls) == 1

    def test_sharing_survives_the_process(self, store):
        """Run one today, the other next week: the dossier is on disk."""
        get_dossier(FakeClient(DOSSIER), "Northlight", store_dir=store)
        fresh_client = FakeClient(DOSSIER)
        _, origin = get_dossier(fresh_client, "Northlight", store_dir=store)
        assert origin == "cache"
        assert fresh_client.calls == []

    def test_a_contact_prep_feeds_a_fund_screen(self, store):
        get_dossier(FakeClient(DOSSIER), "Amy Zhao", "BAI Capital", store_dir=store)
        client = FakeClient(DOSSIER)
        _, origin = get_dossier(client, "BAI Capital Fund IV", store_dir=store)
        assert origin == "cache" and client.calls == []

    def test_stale_research_is_re_gathered(self, store):
        client = FakeClient(DOSSIER)
        get_dossier(client, "Northlight", store_dir=store)
        _, origin = get_dossier(client, "Northlight", ttl_days=0, store_dir=store)
        assert origin == "gathered"
        assert len(client.calls) == 2

    def test_refresh_ignores_a_fresh_dossier(self, store):
        client = FakeClient(DOSSIER)
        get_dossier(client, "Northlight", store_dir=store)
        _, origin = get_dossier(client, "Northlight", refresh=True, store_dir=store)
        assert origin == "gathered"

    def test_reuse_only_never_spends_a_search(self, store):
        """Inbox triage takes research if it exists but does not wait for it."""
        client = FakeClient(DOSSIER)
        dossier, origin = get_dossier(client, "Northlight", gather=False,
                                      store_dir=store)
        assert (dossier, origin) == (None, "none")
        assert client.calls == []
        get_dossier(FakeClient(DOSSIER), "Northlight", store_dir=store)
        dossier, origin = get_dossier(client, "Northlight", gather=False,
                                      store_dir=store)
        assert origin == "cache" and dossier["firm"] == DOSSIER["firm"]


class TestFailure:
    def test_a_failed_search_does_not_sink_the_prep(self, store):
        class Boom(FakeClient):
            def __init__(self):
                super().__init__(handler=self._raise)

            @staticmethod
            def _raise(**_kwargs):
                raise RuntimeError("no network")

        dossier, origin = get_dossier(Boom(), "Northlight", store_dir=store)
        assert (dossier, origin) == (None, "failed")

    def test_stale_research_beats_none_when_a_refresh_fails(self, store):
        get_dossier(FakeClient(DOSSIER), "Northlight", store_dir=store)

        def boom(**_kwargs):
            raise RuntimeError("no network")

        dossier, origin = get_dossier(FakeClient(handler=boom), "Northlight",
                                      ttl_days=0, store_dir=store)
        assert origin == "cache" and dossier["firm"] == DOSSIER["firm"]


class TestGather:
    def test_the_search_tools_are_offered(self):
        client = FakeClient(DOSSIER)
        gather_dossier(client, "Northlight")
        assert client.calls[0]["extra_allowed_tools"] == ["WebSearch", "WebFetch"]

    def test_an_api_client_without_the_kwarg_still_works(self):
        """The API backend takes no extra_allowed_tools — same call without it."""
        class Strict(FakeClient):
            def __init__(self):
                super().__init__(handler=self._h)

            @staticmethod
            def _h(**kwargs):
                if "extra_allowed_tools" in kwargs:
                    raise TypeError("unexpected keyword")
                from tests.fakes import FakeResponse, FakeTextBlock
                return FakeResponse(content=[FakeTextBlock(text=json.dumps(DOSSIER))])

        assert gather_dossier(Strict(), "Northlight")["entity"] == DOSSIER["entity"]

    def test_the_dossier_is_stamped_with_its_age(self):
        d = gather_dossier(FakeClient(DOSSIER), "Northlight")
        assert is_fresh(d)
        assert d["subject"] == "Northlight"


class TestRendering:
    def test_the_prompt_block_states_when_it_was_gathered(self):
        text = dossier_text(gather_dossier(FakeClient(DOSSIER), "Northlight"))
        assert "gathered just now" in text
        assert "Fund III first close" in text
        assert "Unrelated to Northlight Capital" in text

    def test_an_empty_flags_list_says_so_rather_than_going_silent(self):
        """Nothing found is a finding; a missing heading reads as unchecked."""
        text = dossier_text(gather_dossier(FakeClient(DOSSIER), "Northlight"))
        assert "None found by the searches run." in text

    def test_the_age_is_reported_in_days(self):
        d = dict(DOSSIER, gathered_at=time.time() - 3 * 86400,
                 gathered_on="01 Aug 2026", subject="Northlight")
        assert "3 days ago" in dossier_text(d)

    def test_sources_carry_into_the_preps_source_list(self):
        assert dossier_sources(DOSSIER) == [
            "Web: Trade press — https://example.com/close"]

    def test_nothing_gathered_renders_as_nothing(self):
        assert dossier_text({}) == "" and dossier_sources({}) == []


class TestResearchBlock:
    def test_with_research_the_searches_are_not_repeated(self):
        block = research_block(dossier_text(DOSSIER))
        assert "do not repeat them" in block
        assert "only for gaps" in block

    def test_without_research_the_call_must_search_itself(self):
        block = research_block("")
        assert "run the searches yourself now" in block
        assert "none gathered" not in block      # never read as 'web unavailable'
