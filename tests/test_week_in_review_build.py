"""End-to-end: mock-mode Notion + a fake model call, through build()."""
from tests.fakes import FakeClient

from src.config import REASONING_MODEL
from src.connectors.notion_client import NotionConnector
from src.features.week_in_review import derive
from src.features.week_in_review.build import build
from src.features.week_in_review.summarise import PROMPT_VERSION

PAYLOAD = {
    "headline": "A quiet week with one real signal",
    "standfirst": "Axiom Asia showed improved co-invest terms.",
    "urgent": None,
    "moved": [{"fund_id": "wf1", "focus": "ASIA GP", "why": "Terms improved."}],
    "declined": [{"fund_id": "wf2", "focus": "CREDIT", "why": "Track record too thin."}],
    "reads": [
        {"id": f"r{i}", "title": f"Read {i}", "meta": "4 August", "wide": i == 0,
         "badge": {"label": "Track", "tone": "positive"}, "paragraphs": ["Something happened."],
         "quote": None, "note": None,
         "sources": [{"label": "Axiom", "url": "https://notion.so/wn2"}]}
        for i in range(6)
    ],
}


def test_build_returns_every_required_field():
    client = FakeClient(PAYLOAD)
    notion = NotionConnector()
    window = derive.prior_week()
    out = build(client, notion, window)
    for key in ("window", "window_label", "ref", "headline", "standfirst", "stats",
               "urgent", "moved", "declined", "declined_names", "reads", "generated_at",
               "provenance"):
        assert key in out
    assert out["provenance"] == {"model": REASONING_MODEL, "prompt_version": PROMPT_VERSION}


def test_moved_is_reattached_from_real_fund_data():
    client = FakeClient(PAYLOAD)
    notion = NotionConnector()
    out = build(client, notion, derive.prior_week())
    assert out["moved"][0] == {"id": "wf1", "url": "https://notion.so/wf1",
                               "name": "Axiom Asia Fund VII", "status": "Track",
                               "focus": "ASIA GP", "why": "Terms improved.",
                               "declined": False, "why_evidenced": True}


def test_declined_is_reattached_from_real_fund_data():
    client = FakeClient(PAYLOAD)
    notion = NotionConnector()
    out = build(client, notion, derive.prior_week())
    assert out["declined"] == [{"id": "wf2", "url": "https://notion.so/wf2",
                                "name": "Legacy Credit Partners III",
                                "status": "Track (Declined)", "focus": "CREDIT",
                                "why": "Track record too thin."}]


class TestDeclinedFundsAreRowsNotAFootnote:
    """Declining a fund is a decision, so it belongs in the table that reports
    decisions — with all four columns filled, whatever the notes did or did not
    explain."""

    def _row(self, out, name):
        return next(m for m in out["moved"] if m["name"] == name)

    def test_a_declined_fund_appears_under_what_moved(self):
        client = FakeClient(PAYLOAD)
        out = build(client, NotionConnector(), derive.prior_week())
        row = self._row(out, "Legacy Credit Partners III")
        assert row["declined"] is True
        assert row["status"] == "Track (Declined)"
        assert row["url"] == "https://notion.so/wf2"

    def test_a_grounded_reason_is_used_and_marked_as_evidenced(self):
        client = FakeClient(PAYLOAD)
        out = build(client, NotionConnector(), derive.prior_week())
        row = self._row(out, "Legacy Credit Partners III")
        assert row["why"] == "Track record too thin."
        assert row["focus"] == "CREDIT"
        assert row["why_evidenced"] is True

    def test_an_ungrounded_decline_still_gets_every_field(self):
        # Previously this fund fell out of the table into a bare list of names,
        # which told the reader a decision had happened while withholding what
        # it was about.
        client = FakeClient({**PAYLOAD, "declined": []})
        out = build(client, NotionConnector(), derive.prior_week())
        row = self._row(out, "Legacy Credit Partners III")
        assert row["declined"] is True
        assert row["status"] == "Track (Declined)"
        assert row["why"]           # says nothing was recorded, rather than nothing
        assert row["why_evidenced"] is False

    def test_an_ungrounded_reason_is_never_invented(self):
        client = FakeClient({**PAYLOAD, "declined": []})
        out = build(client, NotionConnector(), derive.prior_week())
        row = self._row(out, "Legacy Credit Partners III")
        assert "No reason for the decline appears" in row["why"]

    def test_focus_falls_back_to_the_funds_own_notion_fields(self):
        # Not the model's invention — the record's own geography and asset
        # class, geography first.
        client = FakeClient({**PAYLOAD, "declined": []})
        out = build(client, NotionConnector(), derive.prior_week())
        row = self._row(out, "Legacy Credit Partners III")
        assert row["focus"].startswith("US · ")
        assert "PRIVATE CREDIT" in row["focus"]

    def test_focus_is_blank_rather_than_invented_when_the_record_is_bare(self):
        assert derive.focus_label({"name": "X"}) == ""
        assert derive.focus_label({"asset_class": [], "geographic_focus": []}) == ""

    def test_a_fund_that_both_moved_and_declined_appears_once(self):
        client = FakeClient({
            **PAYLOAD,
            "moved": [{"fund_id": "wf2", "focus": "CREDIT", "why": "Terms improved."}],
            "declined": [],
        })
        out = build(client, NotionConnector(), derive.prior_week())
        rows = [m for m in out["moved"] if m["id"] == "wf2"]
        assert len(rows) == 1
        assert rows[0]["declined"] is True
        # The model's write-up survives rather than being replaced by the
        # "nothing recorded" fallback.
        assert rows[0]["why"] == "Terms improved."

    def test_declined_names_still_lists_every_declined_fund(self):
        # Kept for the header summary and for reviews stored under the old shape.
        client = FakeClient(PAYLOAD)
        out = build(client, NotionConnector(), derive.prior_week())
        assert out["declined_names"] == ["Legacy Credit Partners III"]


def test_defaults_to_the_prior_week_when_no_window_given():
    client = FakeClient(PAYLOAD)
    notion = NotionConnector()
    out = build(client, notion)
    assert out["window"] == derive.prior_week()
