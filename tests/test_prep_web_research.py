"""Meeting prep verifies against the web.

Briefings were coming back saying "web verification was not available in this
session" while holding the search tools the whole time: nothing pre-gathered
the research, so the prompt read "(none gathered)" and the model concluded the
web was closed to it.
"""
from src.features.brief_builder import BRIEFING_SYSTEM_PROMPT, synthesize_briefing
from src.features.meeting_prep import (
    PREP_SYSTEM_PROMPT,
    PrepContext,
    synthesize_prep,
)
from tests.fakes import FakeClient

PREP_PAYLOAD = {
    "counterparty_name": "Northlight", "company_name": "Northlight",
    "summary": "s", "strategy": "s", "history": "h",
    "questions": ["q"], "watch_outs": ["w"], "sources": [],
}


def _ctx():
    return PrepContext(counterparty_name="Northlight Software Partners",
                       counterparty_email="ir@northlight.com",
                       notion_context="(nothing on record)")


class TestQuickPrep:
    def test_the_search_tools_are_offered(self):
        client = FakeClient(PREP_PAYLOAD)
        synthesize_prep(client, _ctx())
        assert client.calls[0]["extra_allowed_tools"] == ["WebSearch", "WebFetch"]

    def test_an_empty_research_slot_asks_for_a_search(self):
        """It must not read as 'the web was unavailable to you'."""
        client = FakeClient(PREP_PAYLOAD)
        synthesize_prep(client, _ctx())
        user = client.calls[0]["messages"][0]["content"]
        assert "none gathered" not in user
        assert "WebSearch" in user

    def test_the_prompt_forbids_claiming_the_web_was_unavailable(self):
        assert "Never write that web verification was" in PREP_SYSTEM_PROMPT

    def test_shared_research_is_not_searched_again(self):
        """The dossier is the searches; repeating them is what we removed."""
        ctx = _ctx()
        ctx.web_context = "[Web research on Northlight, gathered just now.]"
        client = FakeClient(PREP_PAYLOAD)
        synthesize_prep(client, ctx)
        user = client.calls[0]["messages"][0]["content"]
        assert "gathered just now" in user
        assert "do not repeat them" in user


class TestFullBriefing:
    PAYLOAD = {"entity": "Northlight", "is_manager": True,
               "deals_omit_text": "", "meetings": [], "other_mentions": [],
               "no_meetings_text": "none", "background": [], "ledger": [],
               "deal_cards": [], "questions": [], "sources": []}

    def test_an_empty_research_slot_asks_for_a_search(self):
        client = FakeClient(self.PAYLOAD)
        try:
            synthesize_briefing(client, _ctx())
        except Exception:
            pass                      # schema shape is not what is under test
        user = client.calls[0]["messages"][0]["content"]
        assert "none gathered" not in user
        assert "WebSearch" in user

    def test_the_prompt_forbids_claiming_the_web_was_unavailable(self):
        assert "Never write that web verification was" in BRIEFING_SYSTEM_PROMPT
