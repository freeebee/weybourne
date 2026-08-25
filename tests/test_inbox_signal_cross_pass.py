"""The cross-document pass: pairing, adjudication, and never paying twice.

No model calls — the client is a stub returning canned JSON, as in the other
inbox-signal tests.
"""
import json
import types

import pytest

from src.features.inbox_signal import cross_pass, cross_store as cs, views


def _letter(org, mid, period, date, stance, themes, quotes, person="", source=""):
    return {"org": org, "message_id": mid, "period": period, "date": date,
            "stance": stance, "themes": themes, "person": person,
            "source": source or f"{org} letter",
            "quotes": [{"quote": q, "context": ""} for q in quotes]}


ALBIZIA_THEN = _letter("Albizia", "m1", "p0", "2025-09-02", "constructive", ["ai"],
                       ["We are adding to semiconductor exposure on every pullback."],
                       person="CR")
ALBIZIA_NOW = _letter("Albizia", "m2", "p2", "2026-03-03", "negative", ["ai"],
                      ["We have exited the position entirely and do not intend to return."],
                      person="CR")
PANGOLIN_NOW = _letter("Pangolin", "m3", "p2", "2026-03-04", "constructive", ["ai"],
                       ["The capex cycle has years left to run."], person="JH")


class _Stub:
    """A client whose every call returns the same canned payload."""

    def __init__(self, payload, *, refusal=False, raw=None):
        self.payload, self.refusal, self.raw = payload, refusal, raw
        self.calls = 0
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls += 1
        text = self.raw if self.raw is not None else json.dumps(self.payload)
        return types.SimpleNamespace(
            stop_reason="refusal" if self.refusal else "end_turn",
            content=[types.SimpleNamespace(type="text", text=text)],
        )


YES_REVERSAL = {"is_reversal": True, "summary": "Was adding; has now exited.",
                "earlier_quote": 0, "later_quote": 0, "confidence": "high"}
YES_CONFLICT = {"is_conflict": True, "question": "Does the AI capex cycle have further to run?",
                "summary": "One has exited, the other is still buying.",
                "a_quote": 0, "b_quote": 0, "confidence": "medium"}


# --------------------------------------------------------------------------- #
# Pairing — free, deterministic, and the thing that bounds the bill.
# --------------------------------------------------------------------------- #

class TestReversalCandidates:
    def test_a_flip_across_windows_on_a_shared_theme_is_a_candidate(self):
        cands = cross_pass.reversal_candidates([ALBIZIA_THEN, ALBIZIA_NOW])
        assert len(cands) == 1
        assert cands[0]["org"] == "Albizia" and cands[0]["theme"] == "ai"
        assert cands[0]["earlier"]["message_id"] == "m1"
        assert cands[0]["later"]["message_id"] == "m2"

    def test_cautious_to_negative_is_not_a_flip(self):
        # Both are risk-off. The difference is intensity, not direction, and
        # calling a worsening mood a reversal would flag half the mailbox.
        worse = {**ALBIZIA_NOW, "stance": "negative"}
        cautious = {**ALBIZIA_THEN, "stance": "cautious"}
        assert cross_pass.reversal_candidates([cautious, worse]) == []

    def test_neutral_never_pairs(self):
        # A manager who only reported figures took no position to reverse.
        quiet = {**ALBIZIA_THEN, "stance": "neutral"}
        assert cross_pass.reversal_candidates([quiet, ALBIZIA_NOW]) == []

    def test_a_flip_within_one_window_is_not_a_reversal(self):
        same = {**ALBIZIA_NOW, "period": "p0"}
        assert cross_pass.reversal_candidates([ALBIZIA_THEN, same]) == []

    def test_no_shared_theme_no_pair(self):
        other = {**ALBIZIA_NOW, "themes": ["china"]}
        assert cross_pass.reversal_candidates([ALBIZIA_THEN, other]) == []

    def test_a_letter_with_no_quotes_is_not_worth_a_call(self):
        # There would be nothing to show, and an unevidenced claim about a named
        # person is the one thing this feature must not publish.
        mute = {**ALBIZIA_NOW, "quotes": []}
        assert cross_pass.reversal_candidates([ALBIZIA_THEN, mute]) == []

    def test_adjacent_pairs_only(self):
        # Constructive → negative → constructive is two changes of mind, not
        # three: the first and last letters are not themselves a reversal.
        third = _letter("Albizia", "m9", "p3", "2026-06-03", "constructive", ["ai"], ["Back in."])
        cands = cross_pass.reversal_candidates([ALBIZIA_THEN, ALBIZIA_NOW, third])
        assert [(c["earlier"]["message_id"], c["later"]["message_id"]) for c in cands] \
            == [("m2", "m9"), ("m1", "m2")]


class TestConflictCandidates:
    def test_opposed_managers_in_one_window_are_a_candidate(self):
        cands, skipped = cross_pass.conflict_candidates([ALBIZIA_NOW, PANGOLIN_NOW])
        assert skipped == 0 and len(cands) == 1
        assert {cands[0]["a"]["org"], cands[0]["b"]["org"]} == {"Albizia", "Pangolin"}

    def test_a_firm_does_not_disagree_with_itself(self):
        # Same org, opposite stances, one window — that is a reversal question,
        # and pairing it here would double-report it.
        other_desk = _letter("Albizia", "m4", "p2", "2026-03-05", "constructive", ["ai"], ["Buying."])
        cands, _ = cross_pass.conflict_candidates([ALBIZIA_NOW, other_desk])
        assert cands == []

    def test_different_windows_do_not_pair(self):
        cands, _ = cross_pass.conflict_candidates([ALBIZIA_THEN, ALBIZIA_NOW, PANGOLIN_NOW])
        assert all(c["period"] == "p2" for c in cands)

    def test_beyond_the_cap_pairs_are_counted_not_dropped_silently(self):
        # A busy theme in a busy window is quadratic; the overflow has to show
        # up somewhere or a truncated section reads as a settled question.
        letters = [ALBIZIA_NOW] + [
            _letter(f"Bull {i}", f"b{i}", "p2", "2026-03-04", "constructive", ["ai"], ["Buying."])
            for i in range(cross_pass.MAX_PAIRS_PER_CELL + 2)
        ]
        cands, skipped = cross_pass.conflict_candidates(letters)
        assert len(cands) == cross_pass.MAX_PAIRS_PER_CELL
        assert skipped == 2

    def test_one_pair_per_pair_of_firms_not_per_pair_of_documents(self):
        # Real case: QSP filed a CIO letter, a monthly risk report and a fund
        # note in the same fortnight. Pairing each against the same opponent
        # buys one disagreement three times and then shows it three times.
        second = _letter("Albizia", "m2b", "p2", "2026-03-03", "negative", ["ai"],
                         ["Still out.", "No intention of returning."])
        cands, _ = cross_pass.conflict_candidates([ALBIZIA_NOW, second, PANGOLIN_NOW])
        assert len(cands) == 1
        # and it keeps the better-evidenced of the two documents
        assert cands[0]["b"]["message_id"] == "m2b"

    def test_the_most_evidenced_pairs_go_first(self):
        thin = _letter("Thin", "t1", "p2", "2026-03-04", "constructive", ["ai"], ["Buying."])
        thick = _letter("Thick", "k1", "p2", "2026-03-04", "constructive", ["ai"],
                        ["Buying.", "Adding.", "Doubling."])
        cands, _ = cross_pass.conflict_candidates([ALBIZIA_NOW, thin, thick])
        assert cands[0]["a"]["org"] == "Thick"


# --------------------------------------------------------------------------- #
# Adjudication — the model chooses quotes, it never writes them.
# --------------------------------------------------------------------------- #

class TestJudging:
    def test_an_affirmed_reversal_carries_both_stored_quotes(self):
        cand = cross_pass.reversal_candidates([ALBIZIA_THEN, ALBIZIA_NOW])[0]
        v = cross_pass.judge_reversal(_Stub(YES_REVERSAL), cand)
        assert v["found"] and v["quotes"]
        assert v["earlier"]["quote"] == ALBIZIA_THEN["quotes"][0]["quote"]
        assert v["later"]["quote"] == ALBIZIA_NOW["quotes"][0]["quote"]

    def test_a_rejected_pair_is_still_a_verdict(self):
        cand = cross_pass.reversal_candidates([ALBIZIA_THEN, ALBIZIA_NOW])[0]
        v = cross_pass.judge_reversal(_Stub({**YES_REVERSAL, "is_reversal": False}), cand)
        assert v["found"] is False and v["kind"] == cs.REVERSAL

    def test_an_index_pointing_nowhere_loses_the_finding(self):
        # The model can only cite by number. One that points off the end is not
        # resolved to "the nearest quote" — the finding simply fails to evidence
        # itself and is not displayed.
        cand = cross_pass.reversal_candidates([ALBIZIA_THEN, ALBIZIA_NOW])[0]
        v = cross_pass.judge_reversal(_Stub({**YES_REVERSAL, "later_quote": 7}), cand)
        assert v["found"] is True and v["quotes"] is False
        assert cs.held({"verdicts": {"k": v}}, cs.REVERSAL) == []

    def test_minus_one_means_no_quote_states_it(self):
        cand = cross_pass.reversal_candidates([ALBIZIA_THEN, ALBIZIA_NOW])[0]
        v = cross_pass.judge_reversal(_Stub({**YES_REVERSAL, "earlier_quote": -1}), cand)
        assert v["quotes"] is False

    def test_a_refusal_is_a_verdict_not_an_exception(self):
        cand = cross_pass.reversal_candidates([ALBIZIA_THEN, ALBIZIA_NOW])[0]
        v = cross_pass.judge_reversal(_Stub({}, refusal=True), cand)
        assert v["found"] is False and "no usable model output" in v["reason"]

    def test_unparseable_output_is_a_verdict_not_an_exception(self):
        cand = cross_pass.reversal_candidates([ALBIZIA_THEN, ALBIZIA_NOW])[0]
        v = cross_pass.judge_reversal(_Stub({}, raw="not json"), cand)
        assert v["found"] is False

    def test_a_conflict_carries_the_question_and_both_quotes(self):
        cand = cross_pass.conflict_candidates([ALBIZIA_NOW, PANGOLIN_NOW])[0][0]
        v = cross_pass.judge_conflict(_Stub(YES_CONFLICT), cand)
        assert v["found"] and v["quotes"]
        assert v["question"].startswith("Does the AI capex cycle")
        assert v["a"]["quote"] and v["b"]["quote"]

    def test_the_prompt_offers_quotes_by_number_only(self):
        cand = cross_pass.reversal_candidates([ALBIZIA_THEN, ALBIZIA_NOW])[0]
        stub = _Stub(YES_REVERSAL)
        sent = {}
        real = stub._create

        def spy(**kwargs):
            sent.update(kwargs)
            return real(**kwargs)

        stub.messages.create = spy
        cross_pass.judge_reversal(stub, cand)
        body = sent["messages"][0]["content"]
        assert "[0] We are adding to semiconductor exposure" in body
        assert sent["output_config"]["format"]["schema"] is cross_pass.REVERSAL_SCHEMA


# --------------------------------------------------------------------------- #
# The run and its cache.
# --------------------------------------------------------------------------- #

@pytest.fixture()
def base(tmp_path):
    return tmp_path


class TestRun:
    LETTERS = [ALBIZIA_THEN, ALBIZIA_NOW, PANGOLIN_NOW]

    def test_first_run_judges_every_candidate(self, base):
        stub = _Stub(YES_REVERSAL)
        summary = cross_pass.run(stub, self.LETTERS, base=base)
        assert summary["candidates"] == 2 and summary["judged"] == 2
        assert stub.calls == 2

    def test_a_second_run_costs_nothing(self, base):
        cross_pass.run(_Stub(YES_REVERSAL), self.LETTERS, base=base)
        again = _Stub(YES_REVERSAL)
        summary = cross_pass.run(again, self.LETTERS, base=base)
        assert again.calls == 0 and summary["judged"] == 0

    def test_a_rejected_pair_is_not_re_bought(self, base):
        # Most candidates are near-misses; a cache that only kept the hits would
        # spend nearly all of its money re-establishing the same negatives.
        cross_pass.run(_Stub({**YES_REVERSAL, "is_reversal": False,
                              "is_conflict": False}), self.LETTERS, base=base)
        again = _Stub(YES_REVERSAL)
        cross_pass.run(again, self.LETTERS, base=base)
        assert again.calls == 0

    def test_the_cap_defers_the_rest_and_says_so(self, base):
        summary = cross_pass.run(_Stub(YES_REVERSAL), self.LETTERS, base=base, max_pairs=1)
        assert summary["judged"] == 1 and summary["deferred"] == 1

    def test_cancellation_keeps_what_was_already_bought(self, base):
        calls = {"n": 0}

        def cancel():
            calls["n"] += 1
            return calls["n"] > 1        # let the first through, stop before the second

        summary = cross_pass.run(_Stub(YES_REVERSAL), self.LETTERS, base=base,
                                 check_cancel=cancel)
        assert summary["cancelled"] and summary["judged"] == 1
        assert cs.stats(cs.load(base))["pairs_judged"] == 1

    def test_a_transport_failure_leaves_the_pair_retryable(self, base):
        # Unlike an adjudicated "no", a thrown exception says nothing about the
        # pair, so storing it would burn a real finding on a network blip.
        class Boom:
            def __init__(self):
                self.messages = types.SimpleNamespace(create=self._create)

            def _create(self, **kwargs):
                raise RuntimeError("connection reset")

        summary = cross_pass.run(Boom(), self.LETTERS, base=base)
        assert summary["judged"] == 0
        assert cs.load(base)["verdicts"] == {}

    def test_the_switch_turns_the_whole_pass_off(self, base, monkeypatch):
        monkeypatch.setattr("src.config.INBOX_SIGNAL_ENABLED", False)
        stub = _Stub(YES_REVERSAL)
        assert cross_pass.run(stub, self.LETTERS, base=base)["skipped"] is True
        assert stub.calls == 0


class TestCrossStore:
    def test_a_corrupt_file_reads_as_empty(self, base):
        (base / cs.CROSS_NAME).write_text("{not json", encoding="utf-8")
        assert cs.load(base) == {"verdicts": {}, "runs": []}

    def test_only_evidenced_findings_are_held(self, base):
        data = {"verdicts": {
            "a": {"kind": cs.REVERSAL, "found": True, "quotes": True, "sort_date": "2026-03-03"},
            "b": {"kind": cs.REVERSAL, "found": True, "quotes": False, "sort_date": "2026-04-03"},
            "c": {"kind": cs.REVERSAL, "found": False, "sort_date": "2026-05-03"},
        }}
        assert [v["key"] for v in cs.held(data, cs.REVERSAL)] == ["a"]

    def test_runs_are_capped(self, base):
        data = cs._blank()
        for i in range(14):
            cs.record_run(data, {"judged": i})
        assert len(data["runs"]) == 10 and data["runs"][-1]["judged"] == 13


class TestCrossView:
    def test_coverage_is_reported_before_anything_is_judged(self, base):
        # A thin section has to read as unfinished work, not as a quiet desk.
        view = views.cross_view([ALBIZIA_THEN, ALBIZIA_NOW, PANGOLIN_NOW], cs.load(base))
        assert view["candidates"] == 2 and view["pending"] == 2
        assert view["reversals"] == [] and view["conflicts"] == []

    def test_judged_pairs_leave_the_pending_count(self, base):
        cross_pass.run(_Stub(YES_REVERSAL), [ALBIZIA_THEN, ALBIZIA_NOW], base=base)
        view = views.cross_view([ALBIZIA_THEN, ALBIZIA_NOW], cs.load(base))
        assert view["pending"] == 0 and len(view["reversals"]) == 1
        assert view["reversals"][0]["org"] == "Albizia"

    def test_the_dashboard_payload_carries_the_section(self, base):
        payload = views.build(voices_base=base / "voices", manifest_base=base,
                              records_base=base / "records", cross_base=base)
        assert "cross" in payload and payload["cross"]["candidates"] == 0
