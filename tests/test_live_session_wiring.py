"""The API-layer glue between a live meeting's HTTP calls and its persistent
CLI session: computing the delta a read session needs, and the fallback
contract when no persistent session is available."""
from api.main import _delta_since, _live_session_or_none
from src import config


class TestDeltaSince:
    def test_returns_everything_after_the_previous_tail(self):
        full = "They opened with the fund overview. Then they gave the size: $300m."
        tail = "the fund overview."
        assert _delta_since(full, tail) == " Then they gave the size: $300m."

    def test_empty_tail_means_the_whole_transcript_is_new(self):
        assert _delta_since("Everything said so far.", "") == "Everything said so far."

    def test_tail_not_found_falls_back_to_the_whole_transcript(self):
        # Defensive: should never happen in practice (the tail always came
        # from a slice of this same transcript), but a rewritten transcript
        # must not silently drop speech from the model's view.
        assert _delta_since("New text entirely.", "text nowhere in here") == "New text entirely."


class TestLiveSessionOrNone:
    def test_no_session_id_means_no_persistent_session(self):
        assert _live_session_or_none("", "live-tidy") is None

    def test_feature_flag_off_means_no_persistent_session(self, monkeypatch):
        monkeypatch.setattr(config, "LIVE_PERSISTENT_SESSIONS", False)
        assert _live_session_or_none("some-meeting", "live-tidy") is None
