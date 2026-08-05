"""Speech recognition only ever hears English or Mandarin.

Weybourne's meetings are in one or the other. Left to detect freely, whisper
regularly mishears accented English on a short chunk as Welsh, Dutch or Korean
and then transcribes it as gibberish in that language, which poisons the
transcript, the recaps and the note. A detection outside the two is re-read as
whichever of them scored higher.
"""
import pytest

from src.features import stt


class FakeInfo:
    def __init__(self, language, probs=None, prob=0.9):
        self.language = language
        self.language_probability = prob
        self.all_language_probs = list((probs or {}).items())


class FakeModel:
    """Records the language each transcribe call was asked for."""

    def __init__(self, *plan):
        self.plan = list(plan)     # (info, text) per call, in order
        self.asked = []

    def transcribe(self, _audio, **kw):
        self.asked.append(kw.get("language"))
        info, text = self.plan[min(len(self.asked) - 1, len(self.plan) - 1)]
        return (FakeSeg(t) for t in ([text] if text else [])), info


class FakeSeg:
    def __init__(self, text):
        self.text = text


@pytest.fixture
def model(monkeypatch):
    def install(*plan):
        m = FakeModel(*plan)
        monkeypatch.setattr(stt, "_get_model", lambda: m)
        return m
    return install


class TestDetection:
    def test_english_is_accepted_as_detected(self, model):
        m = model((FakeInfo("en"), "we closed fund two at two hundred million"))
        out = stt.transcribe_wav(b"x")
        assert out["language"] == "en"
        assert m.asked == [None]          # detected once, no second pass

    def test_mandarin_is_accepted_as_detected(self, model):
        m = model((FakeInfo("zh"), "我们的基金"))
        assert stt.transcribe_wav(b"x")["language"] == "zh"
        assert m.asked == [None]

    def test_anything_else_is_re_read_as_the_likelier_of_the_two(self, model):
        """Whisper hearing Welsh means it misheard, not that Welsh was spoken."""
        m = model((FakeInfo("cy", {"en": 0.31, "zh": 0.04}), "gibberish"),
                  (FakeInfo("en"), "the fund is targeting three hundred million"))
        out = stt.transcribe_wav(b"x")
        assert m.asked == [None, "en"]
        assert out["language"] == "en"
        assert "three hundred million" in out["text"]

    def test_mandarin_wins_when_it_scores_higher(self, model):
        m = model((FakeInfo("ja", {"en": 0.05, "zh": 0.44}), "x"),
                  (FakeInfo("zh"), "基金"))
        stt.transcribe_wav(b"x")
        assert m.asked == [None, "zh"]

    def test_english_is_the_fallback_with_no_scores_at_all(self, model):
        m = model((FakeInfo("ko"), "x"), (FakeInfo("en"), "hello"))
        stt.transcribe_wav(b"x")
        assert m.asked == [None, "en"]


class TestPinning:
    def test_an_allowed_pin_skips_detection(self, model):
        m = model((FakeInfo("zh"), "基金"))
        stt.transcribe_wav(b"x", "zh")
        assert m.asked == ["zh"]

    def test_auto_means_detect(self, model):
        m = model((FakeInfo("en"), "hello"))
        stt.transcribe_wav(b"x", "auto")
        assert m.asked == [None]

    def test_a_pin_we_do_not_accept_falls_back_to_detection(self, model):
        """The caller cannot pin the recogniser to a language we never write."""
        m = model((FakeInfo("en"), "hello"))
        stt.transcribe_wav(b"x", "fr")
        assert m.asked == [None]

    def test_the_env_override_is_constrained_too(self, model, monkeypatch):
        monkeypatch.setenv("WHISPER_LANGUAGE", "de")
        m = model((FakeInfo("en"), "hello"))
        stt.transcribe_wav(b"x")
        assert m.asked == [None]


def test_only_english_and_mandarin_are_allowed():
    assert stt.ALLOWED_LANGUAGES == ("en", "zh")
