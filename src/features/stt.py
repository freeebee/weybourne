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


def transcribe_wav(wav_bytes: bytes) -> str:
    """Transcribe a recorded audio segment to plain text.

    Raises RuntimeError with an actionable message when the backend is missing.
    """
    try:
        model = _get_model()
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is not installed — run "
            "`pip install faster-whisper` in the app's environment."
        ) from e

    segments, _info = model.transcribe(io.BytesIO(wav_bytes), vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()
