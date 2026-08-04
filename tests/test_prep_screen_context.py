"""The preference screen reads the materials, not a 600-character summary.

The prep job gathers the deck and our Notion records once, then forks into the
screen and the briefing. The briefing got the full context; the screen got a
truncated summary field — so it was asked to cite 'Deck p.28' for a deck it had
never seen.
"""
from src.features.meeting_prep import PrepContext
from src.features.preferences import _format_opportunity
from src.schemas import ExtractedEntity


def _extra(ctx: PrepContext) -> str:
    """The context assembly used by the prep job's run_screen()."""
    return "\n\n".join(x for x in (
        f"OUR RECORDS:\n{ctx.notion_context}" if ctx.notion_context else "",
        f"MATERIALS SUPPLIED:\n{ctx.document_text}" if ctx.document_text else "",
    ) if x)


class TestScreenContext:
    def test_the_whole_deck_reaches_the_prompt(self):
        deck = "TARGET SIZE $1.6bn. " + ("filler. " * 500) + "FEES 2.0/20/8."
        ctx = PrepContext(counterparty_name="Northlight", document_text=deck)
        user = _format_opportunity(ExtractedEntity(fund_name="Northlight"), [],
                                   _extra(ctx))
        assert "FEES 2.0/20/8." in user          # past the old 600-char cut
        assert "TARGET SIZE $1.6bn." in user

    def test_our_records_reach_the_prompt(self):
        ctx = PrepContext(counterparty_name="Northlight",
                          notion_context="Fund: Northlight III — status 'Passed'")
        assert "status 'Passed'" in _extra(ctx)

    def test_nothing_gathered_means_no_empty_headings(self):
        assert _extra(PrepContext(counterparty_name="Northlight")) == ""
