"""The judgment layer: the schema-constrained call and, more importantly,
the post-processing that stops the model's output from being trusted
outright — see the package docstring for why."""
from tests.fakes import FakeClient

from src.config import REASONING_MODEL
from src.features.week_in_review import summarise


def fund(id_, name, status="Track", url="https://notion.so/f"):
    return {"id": id_, "name": name, "status": status, "url": url}


def note(id_, url):
    return {"id": id_, "url": url, "title": id_, "date": "2026-08-04",
            "note_type": "GP Meeting", "thoughts": "x", "body": ""}


PAYLOAD = {
    "headline": "h", "standfirst": "s", "urgent": None,
    "moved": [
        {"fund_id": "f1", "focus": "ASIA", "why": "real"},
        {"fund_id": "unknown", "focus": "GHOST", "why": "should be dropped"},
    ],
    "declined": [],
    "reads": [
        {"id": "r1", "title": "t1", "meta": "m", "wide": False,
         "badge": {"label": "Track", "tone": "positive"}, "paragraphs": ["p"],
         "quote": None, "note": None,
         "sources": [{"label": "real", "url": "https://notion.so/n1"}]},
        {"id": "r2", "title": "t2", "meta": "m", "wide": False,
         "badge": {"label": "Note", "tone": "neutral"}, "paragraphs": ["p"],
         "quote": None, "note": None,
         "sources": [{"label": "fake", "url": "https://notion.so/does-not-exist"}]},
    ],
}


class TestReattachFunds:
    def test_an_unresolved_fund_id_is_dropped(self):
        out = summarise._reattach_funds(
            [{"fund_id": "missing", "focus": "x", "why": "y"}], [fund("f1", "A")])
        assert out == []

    def test_a_fund_with_no_status_is_dropped(self):
        out = summarise._reattach_funds(
            [{"fund_id": "f1", "focus": "x", "why": "y"}],
            [fund("f1", "A", status="")])
        assert out == []

    def test_a_resolved_fund_gets_real_name_and_status_not_the_models(self):
        out = summarise._reattach_funds(
            [{"fund_id": "f1", "focus": "x", "why": "y"}], [fund("f1", "Real Name")])
        assert out == [{"id": "f1", "url": "https://notion.so/f", "name": "Real Name",
                        "status": "Track", "focus": "x", "why": "y"}]


class TestReattachDeclined:
    def test_an_unresolved_fund_id_is_dropped(self):
        out = summarise._reattach_declined(
            [{"fund_id": "missing", "focus": "x", "why": "y"}],
            [fund("f1", "A", status="Track (Declined)")])
        assert out == []

    def test_a_fund_that_is_not_actually_declined_is_dropped(self):
        # The model claimed a reason for a fund it never should have —
        # never trust that assertion over the fund's real status.
        out = summarise._reattach_declined(
            [{"fund_id": "f1", "focus": "x", "why": "y"}],
            [fund("f1", "A", status="Track")])
        assert out == []

    def test_a_genuinely_declined_fund_gets_real_name_and_status(self):
        out = summarise._reattach_declined(
            [{"fund_id": "f1", "focus": "x", "why": "not evidenced enough"}],
            [fund("f1", "Real Name", status="Track (Declined)")])
        assert out == [{"id": "f1", "url": "https://notion.so/f", "name": "Real Name",
                        "status": "Track (Declined)", "focus": "x",
                        "why": "not evidenced enough"}]


class TestDropInventedSources:
    def test_a_read_whose_only_source_is_invented_is_dropped(self):
        notes = [note("n1", "https://notion.so/n1")]
        out = summarise._drop_invented_sources(PAYLOAD["reads"], notes)
        assert [r["id"] for r in out] == ["r1"]

    def test_a_valid_source_among_several_is_kept_the_invented_one_is_not(self):
        read = {**PAYLOAD["reads"][0],
                "sources": [{"label": "real", "url": "https://notion.so/n1"},
                           {"label": "fake", "url": "https://notion.so/x"}]}
        out = summarise._drop_invented_sources([read], [note("n1", "https://notion.so/n1")])
        assert out[0]["sources"] == [{"label": "real", "url": "https://notion.so/n1"}]


class TestSummarise:
    def test_the_call_uses_the_reasoning_model_and_the_schema(self):
        client = FakeClient(PAYLOAD)
        window = {"start": "2026-08-03", "end": "2026-08-07"}
        summarise.summarise(client, window, {}, [fund("f1", "A")],
                            [note("n1", "https://notion.so/n1")])
        call = client.calls[0]
        assert call["model"] == REASONING_MODEL
        assert call["max_tokens"] == 16000
        assert call["output_config"]["format"]["schema"] == summarise.WEEK_IN_REVIEW_SCHEMA

    def test_post_processing_is_applied_to_the_response(self):
        client = FakeClient(PAYLOAD)
        window = {"start": "2026-08-03", "end": "2026-08-07"}
        out = summarise.summarise(client, window, {}, [fund("f1", "A")],
                                  [note("n1", "https://notion.so/n1")])
        assert [m["id"] for m in out["moved"]] == ["f1"]
        assert [r["id"] for r in out["reads"]] == ["r1"]

    def test_declined_is_reattached_through_the_full_call(self):
        client = FakeClient({**PAYLOAD, "declined": [
            {"fund_id": "f1", "focus": "x", "why": "y"}]})
        window = {"start": "2026-08-03", "end": "2026-08-07"}
        out = summarise.summarise(client, window, {},
                                  [fund("f1", "A", status="Track (Declined)")],
                                  [note("n1", "https://notion.so/n1")])
        assert [d["id"] for d in out["declined"]] == ["f1"]


class TestNotesForPrompt:
    def test_drops_the_empty_half_of_a_duplicate_pair(self):
        a = {"id": "a", "title": "Call with Axiom Asia", "thoughts": "", "body": "",
            "date": "2026-08-04"}
        b = {"id": "b", "title": "Meeting with Axiom Asia", "thoughts": "real content",
            "body": "", "date": "2026-08-04"}
        out = summarise.notes_for_prompt([a, b])
        assert [n["id"] for n in out] == ["b"]

    def test_zero_content_notes_are_dropped(self):
        a = {"id": "a", "title": "Empty note", "thoughts": "", "body": "", "date": "2026-08-04"}
        assert summarise.notes_for_prompt([a]) == []
