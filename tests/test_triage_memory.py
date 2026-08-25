"""Triage memory — the record that stops the same mail being triaged twice."""
import datetime as dt
import json

from src.features import triage_memory as tm

RESULT = {"is_investment": True, "category": "New fund intro", "confidence": 0.9}


def _aged(base, message_id: str, days: float) -> None:
    """Backdate a stored entry, so expiry can be tested without waiting."""
    data = tm.load(base)
    stamp = dt.datetime.now() - dt.timedelta(days=days)
    data["messages"][message_id]["at"] = stamp.isoformat(timespec="seconds")
    tm.save(data, base)


class TestRoundTrip:
    def test_a_recorded_verdict_is_recalled(self, tmp_path):
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "m1", RESULT, subject="Fund intro")
        data = tm.load(tmp_path)
        assert tm.seen(data, "m1")
        assert tm.result_for(data, "m1") == RESULT

    def test_an_unknown_message_is_not_seen(self, tmp_path):
        assert not tm.seen(tm.load(tmp_path), "nope")

    def test_the_whole_verdict_is_kept_not_just_a_marker(self, tmp_path):
        # A bare skip-list would leave the row blank, and the only way to find
        # out what had been decided would be to triage it again.
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "m1", RESULT)
        assert tm.result_for(tm.load(tmp_path), "m1")["category"] == "New fund intro"


class TestExpiry:
    def test_a_fresh_entry_is_remembered(self, tmp_path):
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "m1", RESULT)
        _aged(tmp_path, "m1", tm.MEMORY_DAYS - 1)
        assert tm.seen(tm.load(tmp_path), "m1")

    def test_a_stale_entry_is_forgotten(self, tmp_path):
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "m1", RESULT)
        _aged(tmp_path, "m1", tm.MEMORY_DAYS + 1)
        data = tm.load(tmp_path)
        assert not tm.seen(data, "m1")
        assert tm.result_for(data, "m1") is None

    def test_memory_outlasts_the_inbox_lookback(self, tmp_path):
        # The window has to exceed TRIAGE_LOOKBACK_DAYS or the bug returns: a
        # message triaged on Monday reappears untriaged on Wednesday.
        from src import config
        assert tm.MEMORY_DAYS > config.TRIAGE_LOOKBACK_DAYS

    def test_prune_drops_only_the_stale(self, tmp_path):
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "old", RESULT)
            tm.record(mem.data, "new", RESULT)
        _aged(tmp_path, "old", tm.MEMORY_DAYS + 5)
        data = tm.load(tmp_path)
        assert tm.prune(data) == 1
        assert set(data["messages"]) == {"new"}

    def test_an_unreadable_timestamp_expires(self, tmp_path):
        # Safe direction: one needless re-triage, rather than a message hidden
        # forever by a stamp nothing can parse.
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "m1", RESULT)
        data = tm.load(tmp_path)
        data["messages"]["m1"]["at"] = "not-a-date"
        assert not tm.seen(data, "m1")


class TestFailuresAreNotRemembered:
    def test_an_errored_result_is_not_stored(self, tmp_path):
        # A failure is an attempt, not a verdict — it should be retried.
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "m1", {"error": "model refused"})
        assert not tm.seen(tm.load(tmp_path), "m1")


class TestOverrides:
    def test_forget_lets_one_message_be_triaged_again(self, tmp_path):
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "m1", RESULT)
            tm.record(mem.data, "m2", RESULT)
        data = tm.load(tmp_path)
        assert tm.forget(data, "m1")
        assert not tm.seen(data, "m1")
        assert tm.seen(data, "m2")

    def test_forgetting_an_unknown_message_reports_nothing_went(self, tmp_path):
        assert not tm.forget(tm.load(tmp_path), "nope")

    def test_clear_drops_everything(self, tmp_path):
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "m1", RESULT)
            tm.record(mem.data, "m2", RESULT)
        data = tm.load(tmp_path)
        assert tm.clear(data) == 2
        assert data["messages"] == {}


class TestDurability:
    def test_a_corrupt_file_reads_as_empty(self, tmp_path):
        # Costs a round of re-triage rather than wedging the feature shut.
        (tmp_path / tm.MEMORY_NAME).write_text("{not json", encoding="utf-8")
        assert tm.load(tmp_path) == {"messages": {}}

    def test_re_recording_refreshes_the_timestamp(self, tmp_path):
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "m1", RESULT)
        _aged(tmp_path, "m1", tm.MEMORY_DAYS + 1)
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "m1", RESULT)
        assert tm.seen(tm.load(tmp_path), "m1")

    def test_the_file_is_valid_json_on_disk(self, tmp_path):
        with tm.Memory(tmp_path) as mem:
            tm.record(mem.data, "m1", RESULT, subject="Fund intro")
        raw = json.loads((tmp_path / tm.MEMORY_NAME).read_text(encoding="utf-8"))
        assert raw["messages"]["m1"]["subject"] == "Fund intro"
