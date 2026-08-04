"""Local speech-to-text for the live meeting page.

Uses faster-whisper (CPU, int8) so nothing leaves the machine — meeting audio
is sensitive. The model (~75MB for "base") downloads from Hugging Face on first
use and is cached locally after that.
"""
from __future__ import annotations

import io
import os

# Windows without Developer Mode can't create symlinks, so the HF cache copies
# files instead — harmless, and the warning about it just alarms people.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_model = None

MODEL_SIZE = os.environ.get("WHISPER_MODEL", "base")


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def transcribe_wav(wav_bytes: bytes, language: str = "") -> dict:
    """Transcribe a recorded audio segment.

    Returns {"text", "language", "language_probability"}. ``language`` pins the
    input language (skips per-chunk detection); empty or "auto" lets whisper
    detect it, so multilingual meetings come through in whatever was spoken.

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
    segments, info = model.transcribe(
        io.BytesIO(wav_bytes),
        vad_filter=True,
        # Live chunks arrive every 8 seconds — latency wins over the last few
        # points of accuracy. Greedy decoding (beam 1) is 2-3x faster than the
        # default beam of 5.
        beam_size=1,
        language=pin if pin and pin != "auto" else None,
        condition_on_previous_text=False,
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return {
        "text": text,
        "language": getattr(info, "language", "") or "",
        "language_probability": round(getattr(info, "language_probability", 0.0) or 0.0, 2),
    }
