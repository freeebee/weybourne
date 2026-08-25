"""Backfilling per-quote themes onto letters read before they existed.

The bug this repairs: a letter's themes printed under each of its quotes, so
QSP's July risk report — tagged vol, semis, Iran and crude — put a passage about
single-stock decorrelation under Semiconductors. The pass must fix that without
introducing the opposite failure, which is a backfill that invents themes,
loses quote text, or re-buys work it has already done.

No model calls: the client is a stub, as in the other feature tests.
"""
import json

import pytest

from src.features.inbox_signal import retheme, store


class FakeBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, payload, stop_reason="end_turn"):
        self.content = [FakeBlock(json.dumps(payload))]
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._payloads.pop(0) if self._payloads else {"passages": []}
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)


class FakeClient:
    def __init__(self, *payloads):
        self.messages = FakeMessages(payloads)


def _letter(quotes, themes=("vol", "semis", "iran"), mid="m1", org="QSP"):
    return {
        "org": org, "message_id": mid, "date": "2026-08-04", "period": "p4",
        "stance": "cautious", "source": "July 2026 monthly risk report",
        "themes": list(themes), "quotes": list(quotes), "reported_returns": [],
    }


def _q(text, themes=None):
    q = {"quote": text, "context": "why it matters"}
    if themes is not None:
        q["themes"] = themes
    return q


class TestWhatStillNeedsDoing:
    def test_a_quote_with_no_themes_key_needs_attributing(self):
        assert retheme.quotes_needing_themes(_letter([_q("a"), _q("b")])) == [0, 1]

    def test_an_empty_list_is_an_answer_and_is_not_re_bought(self):
        # "None of this letter's themes" costs a call to establish. Treating it
        # as unanswered would re-buy it on every run, and empty is the single
        # most common correct answer.
        letter = _letter([_q("a", []), _q("b")])
        assert retheme.quotes_needing_themes(letter) == [1]

    def test_a_letter_with_no_themes_of_its_own_is_not_queued(self):
        # There is nothing to choose from, so there is nothing to buy.
        assert retheme.pending([_letter([_q("a")], themes=[])]) == []

    def test_a_letter_with_no_quotes_is_not_queued(self):
        assert retheme.pending([_letter([])]) == []

    def test_stats_count_the_archive_honestly(self):
        letters = [_letter([_q("a", ["vol"]), _q("b")]),
                   _letter([_q("c")], mid="m2")]
        s = retheme.stats(letters)
        assert s == {"quotes": 3, "attributed": 1, "inheriting": 2,
                     "letters_pending": 2}


class TestAttribution:
    def test_each_passage_gets_only_its_own_themes(self):
        letter = _letter([_q("Single stock decorrelation is pronounced."),
                          _q("Semis remain the crowded trade.")])
        client = FakeClient({"passages": [{"index": 0, "themes": ["vol"]},
                                          {"index": 1, "themes": ["semis"]}]})
        assert retheme.attribute(client, letter) == {0: ["vol"], 1: ["semis"]}

    def test_a_passage_about_none_of_them_gets_none(self):
        # The whole point. This is the QSP case.
        letter = _letter([_q("Single stock decorrelation is pronounced.")])
        client = FakeClient({"passages": [{"index": 0, "themes": []}]})
        assert retheme.attribute(client, letter) == {0: []}

    def test_a_theme_the_letter_never_had_is_refused(self):
        # A backfill that could mint ids would rewrite the vocabulary the theme
        # drawer is built on.
        letter = _letter([_q("a")], themes=["vol"])
        client = FakeClient({"passages": [{"index": 0, "themes": ["vol", "crypto"]}]})
        assert retheme.attribute(client, letter) == {0: ["vol"]}

    def test_a_theme_is_matched_however_the_model_cases_it(self):
        letter = _letter([_q("a")], themes=["vol"])
        client = FakeClient({"passages": [{"index": 0, "themes": ["VOL"]}]})
        assert retheme.attribute(client, letter) == {0: ["vol"]}

    def test_repeats_are_collapsed(self):
        letter = _letter([_q("a")], themes=["vol"])
        client = FakeClient({"passages": [{"index": 0, "themes": ["vol", "vol"]}]})
        assert retheme.attribute(client, letter) == {0: ["vol"]}

    def test_an_index_pointing_nowhere_is_dropped(self):
        letter = _letter([_q("a")])
        client = FakeClient({"passages": [{"index": 7, "themes": ["vol"]},
                                          {"index": 0, "themes": ["vol"]}]})
        assert retheme.attribute(client, letter) == {0: ["vol"]}

    def test_a_quote_already_attributed_is_never_sent(self):
        letter = _letter([_q("done", ["vol"]), _q("todo")])
        client = FakeClient({"passages": [{"index": 1, "themes": ["semis"]}]})
        retheme.attribute(client, letter)
        sent = client.messages.calls[0]["messages"][0]["content"]
        assert "todo" in sent and "done" not in sent

    def test_the_letter_body_is_never_sent(self):
        # The saving that makes this affordable: quotes and ids, not the letter.
        letter = {**_letter([_q("a quoted line")]), "body": "THE ENTIRE LETTER BODY"}
        client = FakeClient({"passages": []})
        retheme.attribute(client, letter)
        assert "THE ENTIRE LETTER BODY" not in client.messages.calls[0]["messages"][0]["content"]


class TestModelTrouble:
    def test_a_refusal_leaves_the_letter_inheriting(self):
        letter = _letter([_q("a")])

        class Refusing(FakeClient):
            def __init__(self):
                super().__init__({"passages": []})
                self.messages.create = lambda **k: FakeResponse({}, stop_reason="refusal")

        assert retheme.attribute(Refusing(), letter) == {}

    def test_a_raising_client_does_not_propagate(self):
        client = FakeClient(RuntimeError("connection reset"))
        assert retheme.attribute(client, _letter([_q("a")])) == {}

    def test_unparseable_output_does_not_propagate(self):
        class Broken:
            class messages:
                @staticmethod
                def create(**kwargs):
                    class R:
                        content = [FakeBlock("not json")]
                        stop_reason = "end_turn"
                    return R()

        assert retheme.attribute(Broken(), _letter([_q("a")])) == {}


class TestWritingBack:
    def test_the_quote_text_and_context_survive(self, tmp_path):
        # The one thing a backfill must never do is lose the evidence.
        store.save({"org": "QSP", "letters": [_letter([_q("verbatim words")])]}, tmp_path)
        letter = store.all_letters(tmp_path)[0]
        client = FakeClient({"passages": [{"index": 0, "themes": ["vol"]}]})

        assert retheme.apply_to_letter(client, letter, tmp_path) == 1
        q = store.all_letters(tmp_path)[0]["quotes"][0]
        assert q["quote"] == "verbatim words"
        assert q["context"] == "why it matters"
        assert q["themes"] == ["vol"]

    def test_the_letters_own_themes_are_untouched(self, tmp_path):
        store.save({"org": "QSP", "letters": [_letter([_q("a")])]}, tmp_path)
        letter = store.all_letters(tmp_path)[0]
        retheme.apply_to_letter(FakeClient({"passages": [{"index": 0, "themes": []}]}),
                                letter, tmp_path)
        assert store.all_letters(tmp_path)[0]["themes"] == ["vol", "semis", "iran"]

    def test_a_sibling_letter_in_the_same_file_is_not_clobbered(self, tmp_path):
        # The record is re-read and matched by message_id rather than written
        # from the in-memory copy.
        store.save({"org": "QSP", "letters": [
            _letter([_q("first")], mid="m1"),
            _letter([_q("second")], mid="m2"),
        ]}, tmp_path)
        letter = next(x for x in store.all_letters(tmp_path) if x["message_id"] == "m1")
        retheme.apply_to_letter(FakeClient({"passages": [{"index": 0, "themes": ["vol"]}]}),
                                letter, tmp_path)

        after = {x["message_id"]: x for x in store.all_letters(tmp_path)}
        assert after["m1"]["quotes"][0]["themes"] == ["vol"]
        assert after["m2"]["quotes"][0]["quote"] == "second"
        assert "themes" not in after["m2"]["quotes"][0]

    def test_a_letter_no_longer_on_disk_is_skipped_not_created(self, tmp_path):
        client = FakeClient({"passages": [{"index": 0, "themes": ["vol"]}]})
        assert retheme.apply_to_letter(client, _letter([_q("a")]), tmp_path) == 0
        assert store.all_letters(tmp_path) == []


class TestTheRun:
    def _seed(self, tmp_path, n):
        store.save({"org": "QSP", "letters": [
            _letter([_q(f"quote {i}")], mid=f"m{i}") for i in range(n)]}, tmp_path)

    def test_it_reports_what_it_did_and_what_is_left(self, tmp_path):
        self._seed(tmp_path, 3)
        client = FakeClient({"passages": [{"index": 0, "themes": ["vol"]}]},
                            {"passages": [{"index": 0, "themes": []}]})
        out = retheme.run(client, limit=2, base=tmp_path)
        assert out == {"letters_examined": 2, "letters_updated": 2,
                       "quotes_attributed": 2, "letters_remaining": 1}

    def test_a_second_run_only_picks_up_what_is_left(self, tmp_path):
        # Resumable and idempotent: the cost is bounded by what remains.
        self._seed(tmp_path, 2)
        retheme.run(FakeClient({"passages": [{"index": 0, "themes": ["vol"]}]}),
                    limit=1, base=tmp_path)
        client = FakeClient({"passages": [{"index": 0, "themes": ["semis"]}]})
        out = retheme.run(client, limit=0, base=tmp_path)

        assert out["letters_examined"] == 1
        assert len(client.messages.calls) == 1
        assert out["letters_remaining"] == 0

    def test_a_finished_archive_costs_nothing(self, tmp_path):
        store.save({"org": "QSP", "letters": [_letter([_q("a", ["vol"])])]}, tmp_path)
        client = FakeClient()
        out = retheme.run(client, base=tmp_path)
        assert client.messages.calls == []
        assert out["letters_examined"] == 0

    def test_no_limit_takes_everything(self, tmp_path):
        self._seed(tmp_path, 3)
        client = FakeClient(*[{"passages": [{"index": 0, "themes": ["vol"]}]}] * 3)
        out = retheme.run(client, limit=0, base=tmp_path)
        assert out["letters_examined"] == 3 and out["letters_remaining"] == 0


class TestTheBugItRepairs:
    def test_the_qsp_case_end_to_end(self, tmp_path):
        """A vol passage in a letter tagged vol, semis, Iran and crude."""
        store.save({"org": "QSP", "letters": [_letter(
            [_q("There are some seriously pronounced market observations in the vol "
                "space... unseen single stock decorrelations, dampening index volatility."),
             _q("Semiconductor supply remains the binding constraint.")],
            themes=["vol", "semis", "iran", "crude"])]}, tmp_path)

        client = FakeClient({"passages": [{"index": 0, "themes": ["vol"]},
                                          {"index": 1, "themes": ["semis"]}]})
        retheme.run(client, base=tmp_path)

        quotes = store.all_letters(tmp_path)[0]["quotes"]
        assert quotes[0]["themes"] == ["vol"]
        assert "semis" not in quotes[0]["themes"]
        assert "iran" not in quotes[0]["themes"]
        assert quotes[1]["themes"] == ["semis"]

    def test_the_view_then_stops_calling_them_the_letters(self, tmp_path):
        from src.features.inbox_signal import views

        store.save({"org": "QSP", "letters": [_letter(
            [_q("A passage about volatility.")], themes=["vol", "semis"])]}, tmp_path)
        before = views.voices_view(store.all_letters(tmp_path))[0]
        assert before["themes_are_the_letters"] is True
        assert "semis" in before["themes"]

        retheme.run(FakeClient({"passages": [{"index": 0, "themes": ["vol"]}]}),
                    base=tmp_path)

        after = views.voices_view(store.all_letters(tmp_path))[0]
        assert after["themes_are_the_letters"] is False
        assert after["themes"] == ["vol"]
