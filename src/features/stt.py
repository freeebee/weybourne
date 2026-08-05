"""Local speech-to-text for the live meeting page.

Uses faster-whisper (CPU, int8) so nothing leaves the machine — meeting audio
is sensitive. The model (~75MB for "base") downloads from Hugging Face on first
use and is cached locally after that.
"""
from __future__ import annotations

import io
import os
import threading

# Windows without Developer Mode can't create symlinks, so the HF cache copies
# files instead — harmless, and the warning about it just alarms people.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_model = None
# One transcription at a time: the model is CPU-bound and not thread-safe, and
# serialising here keeps a burst of chunks from saturating every core.
_transcribe_lock = threading.Lock()

MODEL_SIZE = os.environ.get("WHISPER_MODEL", "base")
# 0 = ctranslate2 picks its own thread count. Benchmarked on this machine
# (22 logical processors) with a representative ~15s spoken clip: forcing
# 6, 8, 10 or 16 threads was consistently SLOWER than the default (roughly
# 7-9s vs ~4.2s avg) — more threads fighting over a workload this small
# costs more in synchronisation/cache contention than it gains in
# parallelism. Left at auto; override here only after benchmarking again on
# the actual target machine, not by assuming more cores helps.
WHISPER_CPU_THREADS = int(os.environ.get("WHISPER_CPU_THREADS", "0"))
# "cpu" today; override to "cuda" on a machine with a supported GPU.
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")

# Weybourne's meetings are in English or Mandarin, and nothing else. Whisper's
# open detection routinely mishears accented English as Welsh, Dutch or Korean
# on a short chunk and then transcribes it as gibberish in that language.
# Constraining the choice to these two removes that failure mode entirely.
ALLOWED_LANGUAGES = ("en", "zh")


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(MODEL_SIZE, device=WHISPER_DEVICE, compute_type="int8",
                             cpu_threads=WHISPER_CPU_THREADS)
    return _model


def _better_of_allowed(info) -> str:
    """Whichever of English and Mandarin whisper thought more likely."""
    probs = dict(getattr(info, "all_language_probs", None) or [])
    return max(ALLOWED_LANGUAGES, key=lambda code: probs.get(code, 0.0))


def warm_model() -> None:
    """Load the Whisper model now, off the request path. The model is lazy
    (see _get_model) so it would otherwise load on the FIRST real recorded
    chunk, adding its load time on top of that chunk's own transcription —
    called when the Live page starts recording so that cost is already
    paid by the time real audio arrives. Best-effort: a failed warm-up just
    means the first real call loads it instead, same as today."""
    try:
        _get_model()
    except Exception:  # noqa: BLE001
        pass


def transcribe_wav(wav_bytes: bytes, language: str = "") -> dict:
    """Transcribe a recorded audio segment.

    Returns {"text", "language", "language_probability"}. ``language`` pins the
    input language; empty or "auto" lets whisper detect it. Detection is
    constrained to ALLOWED_LANGUAGES — anything else it thinks it hears is
    re-read as whichever of the two scored higher.

    Raises RuntimeError with an actionable message when the backend is missing.
    """
    try:
        model = _get_model()
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is not installed — run "
            "`pip install faster-whisper` in the app's environment."
        ) from e

    pin = (language or os.environ.get("WHISPER_LANGUAGE", "")).strip().lower()
    if pin not in ALLOWED_LANGUAGES:
        pin = ""          # "auto", blank, or anything we do not accept

    def _run(lang: str):
        return model.transcribe(
            io.BytesIO(wav_bytes),
            vad_filter=True,
            # Defaults are tuned for long recordings and are far too aggressive
            # for quiet meeting audio (screen-share sound especially): at the
            # stock 0.5 threshold whole chunks of soft speech vanish. Keep VAD
            # only as a hallucination guard on true silence.
            vad_parameters={"threshold": 0.25, "min_silence_duration_ms": 1500,
                            "speech_pad_ms": 500},
            # Live chunks arrive every 8 seconds — latency wins over the last
            # few points of accuracy. Greedy decoding (beam 1) is 2-3x faster
            # than the default beam of 5.
            beam_size=1,
            language=lang or None,
            condition_on_previous_text=False,
        )

    with _transcribe_lock:
        segments, info = _run(pin)
        # `segments` is lazy, so a detection we reject costs nothing but the
        # detection itself — the decode never runs.
        if not pin and (getattr(info, "language", "") or "") not in ALLOWED_LANGUAGES:
            segments, info = _run(_better_of_allowed(info))
        text = " ".join(seg.text.strip() for seg in segments).strip()
    return {
        "text": text,
        "language": getattr(info, "language", "") or "",
        "language_probability": round(getattr(info, "language_probability", 0.0) or 0.0, 2),
    }
