"""Transcription sheds load rather than queueing behind it.

The live page feeds two independent 8-second chunk loops into one whisper
lock. When the machine cannot keep up, an unbounded queue does not "catch up
later" — it grows, and because whisper saturates the box the browser's own
chunk timer slips too, so the next chunks arrive longer and take longer still.
A meeting on 17 Aug 2026 went from 20-second gaps to 4m38s to nothing.

Dropping a chunk loses a sentence. Queueing it loses the rest of the meeting.
"""
import threading

import pytest

from src.features import stt


class FakeInfo:
    language = "en"
    language_probability = 0.9
    all_language_probs = [("en", 0.9)]


class BlockingModel:
    """Holds every transcribe call until released, so a backlog can be built
    deterministically rather than by racing real work."""

    def __init__(self):
        self.release = threading.Event()
        self.entered = threading.Semaphore(0)
        self.calls = 0

    def transcribe(self, _audio, **_kw):
        self.calls += 1
        self.entered.release()
        self.release.wait(timeout=5)
        return (iter([]), FakeInfo())


@pytest.fixture
def blocked(monkeypatch):
    """One transcription in flight and holding the lock."""
    model = BlockingModel()
    monkeypatch.setattr(stt, "_get_model", lambda: model)
    # Fail fast: these tests are about refusal, not about waiting out a real
    # timeout. The occupying call is released explicitly at the end.
    monkeypatch.setattr(stt, "MAX_WAIT_SECONDS", 0.05)
    holder = threading.Thread(target=stt.transcribe_wav, args=(b"x",), daemon=True)
    holder.start()
    assert model.entered.acquire(timeout=5), "the occupying call never started"
    yield model
    model.release.set()
    holder.join(timeout=5)


def test_a_chunk_that_cannot_be_transcribed_promptly_is_dropped(blocked):
    out = stt.transcribe_wav(b"y")
    assert out["dropped"] is True
    assert out["text"] == ""
    # Refused at the door: the model was never asked to do the work.
    assert blocked.calls == 1


def test_a_dropped_chunk_reports_no_language(blocked):
    """A chunk nobody listened to says nothing about what was spoken — the
    caller must not fold it into the language streak that pins the recogniser.
    """
    out = stt.transcribe_wav(b"y")
    assert out["language"] == ""
    assert out["language_probability"] == 0.0


def test_the_queue_is_bounded(blocked, monkeypatch):
    """Past MAX_WAITING, latecomers are refused immediately instead of each
    sitting through the wait — which is what let the backlog outgrow the
    meeting."""
    monkeypatch.setattr(stt, "MAX_WAITING", 1)
    assert stt.transcribe_wav(b"y")["dropped"] is True


def test_normal_transcription_is_not_marked_dropped(monkeypatch):
    class Model:
        def transcribe(self, _audio, **_kw):
            return (iter([type("S", (), {"text": " we closed fund two "})()]),
                    FakeInfo())

    monkeypatch.setattr(stt, "_get_model", lambda: Model())
    out = stt.transcribe_wav(b"x")
    assert out["dropped"] is False
    assert out["text"] == "we closed fund two"


def test_capacity_is_returned_after_a_drop(monkeypatch):
    """The shed is momentary, not a latch: once the backlog clears the next
    chunk is admitted normally. A meeting recovers on its own."""
    model = BlockingModel()
    monkeypatch.setattr(stt, "_get_model", lambda: model)
    monkeypatch.setattr(stt, "MAX_WAIT_SECONDS", 0.05)
    holder = threading.Thread(target=stt.transcribe_wav, args=(b"x",), daemon=True)
    holder.start()
    assert model.entered.acquire(timeout=5)
    assert stt.transcribe_wav(b"y")["dropped"] is True

    model.release.set()
    holder.join(timeout=5)
    assert stt.transcribe_wav(b"z")["dropped"] is False
