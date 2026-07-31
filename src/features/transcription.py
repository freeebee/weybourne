"""Live meeting transcript + on-the-fly question generation.

STATUS: scaffold. The user has an existing artifact for this feature and more
detail to follow, so this module deliberately implements only the parts that are
already settled and leaves the transcription backend behind an interface.

What is settled and implemented here:

* ``TranscriptBuffer`` — accumulates transcript segments during a meeting and
  can hand back the recent window (what a live question generator needs).
* ``generate_live_questions`` — given the transcript so far and the questions
  already asked, produce the next questions worth asking. It tracks what has
  been covered so suggestions do not repeat, which mirrors the "ledger" idea in
  the existing ``live-followup-questions`` skill.
* ``QuestionLedger`` — tracks asked / answered / outstanding across a meeting.

What is intentionally NOT decided here:

* The transcription backend. ``Transcriber`` is an interface; a local Whisper
  process, a streaming cloud STT service, or Teams' own live captions can all
  satisfy it. Audio capture in particular needs a real microphone, so it cannot
  be exercised in a cloud container — it should be wired and tested locally.

Once the artifact lands, the concrete transcriber slots in behind ``Transcriber``
without the question-generation logic changing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from src.config import REASONING_MODEL


# --------------------------------------------------------------------------- #
# Transcript plumbing
# --------------------------------------------------------------------------- #

@dataclass
class TranscriptSegment:
    text: str
    speaker: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class TranscriptBuffer:
    """Accumulates a meeting transcript as it arrives."""
    segments: list[TranscriptSegment] = field(default_factory=list)

    def add(self, text: str, speaker: str = "") -> None:
        if text and text.strip():
            self.segments.append(TranscriptSegment(text=text.strip(), speaker=speaker))

    def full_text(self) -> str:
        return "\n".join(
            f"{s.speaker + ': ' if s.speaker else ''}{s.text}" for s in self.segments
        )

    def recent_text(self, max_chars: int = 6000) -> str:
        """The tail of the transcript — what the live question generator reads."""
        text = self.full_text()
        return text[-max_chars:] if len(text) > max_chars else text

    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.segments)


class Transcriber(Protocol):
    """Interface a transcription backend must satisfy.

    Implementations are expected to run in a background thread/process and push
    text into a ``TranscriptBuffer`` as it is recognised.
    """

    def start(self, buffer: TranscriptBuffer) -> None: ...

    def stop(self) -> None: ...


@dataclass
class ManualTranscriber:
    """Fallback 'backend' for when there is no audio pipeline.

    The user (or a paste from Teams live captions / a Notion transcript page)
    feeds text in directly. This makes the live-questions half of the feature
    fully usable before audio capture is wired up.
    """
    buffer: TranscriptBuffer | None = None

    def start(self, buffer: TranscriptBuffer) -> None:
        self.buffer = buffer

    def feed(self, text: str, speaker: str = "") -> None:
        if self.buffer is not None:
            self.buffer.add(text, speaker)

    def stop(self) -> None:
        self.buffer = None


# --------------------------------------------------------------------------- #
# Question ledger
# --------------------------------------------------------------------------- #

@dataclass
class QuestionLedger:
    """Tracks which questions have been asked and which remain outstanding."""
    asked: list[str] = field(default_factory=list)
    answered: list[str] = field(default_factory=list)
    outstanding: list[str] = field(default_factory=list)

    def propose(self, questions: list[str]) -> list[str]:
        """Add newly suggested questions, skipping ones already seen."""
        seen = {q.lower().strip() for q in self.asked + self.answered + self.outstanding}
        fresh = [q for q in questions if q.lower().strip() not in seen]
        self.outstanding.extend(fresh)
        return fresh

    def mark_asked(self, question: str) -> None:
        if question in self.outstanding:
            self.outstanding.remove(question)
        if question not in self.asked:
            self.asked.append(question)

    def mark_answered(self, question: str) -> None:
        for bucket in (self.outstanding, self.asked):
            if question in bucket:
                bucket.remove(question)
        if question not in self.answered:
            self.answered.append(question)


# --------------------------------------------------------------------------- #
# Live question generation
# --------------------------------------------------------------------------- #

QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "why": {"type": "string", "description": "What this question tests"},
                    "urgency": {"type": "string", "enum": ["now", "soon", "later"]},
                },
                "required": ["question", "why", "urgency"],
                "additionalProperties": False,
            },
        },
        "covered": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Outstanding questions that the transcript now appears to answer",
        },
    },
    "required": ["questions", "covered"],
    "additionalProperties": False,
}

LIVE_QUESTIONS_SYSTEM_PROMPT = """You are listening to a live meeting alongside a senior \
investment manager at Weybourne, a family office investing in funds. Your job is to suggest \
the questions worth asking RIGHT NOW, based on what has just been said.

Standards:
- Questions must follow from what was actually said in the transcript — quote or reference it \
implicitly. No generic diligence checklist items.
- Probe the real engine: where returns actually come from, what must be true for the strategy \
to work, what would break it. Push on anything asserted without evidence.
- Prefer the one question that would most change our view over five safe ones.
- Do not repeat anything in the already-asked list, or anything the transcript already answers.
- Mark urgency "now" only if the moment will pass — it follows directly from the last exchange.
- Keep each question to one sentence a person can say out loud."""


def generate_live_questions(
    client,
    buffer: TranscriptBuffer,
    ledger: QuestionLedger,
    context: str = "",
    max_questions: int = 4,
) -> list[dict]:
    """Suggest the next questions to ask, given the transcript so far.

    Also updates the ledger: questions the transcript now answers are moved to
    ``answered``, and fresh suggestions are added to ``outstanding``.
    """
    asked = ledger.asked + ledger.outstanding
    user = (
        f"MEETING CONTEXT\n{context or '(none supplied)'}\n\n"
        f"ALREADY ASKED / OUTSTANDING\n"
        + ("\n".join(f"- {q}" for q in asked) if asked else "(nothing yet)")
        + f"\n\nTRANSCRIPT SO FAR\n{buffer.recent_text()}\n\n"
        f"Suggest at most {max_questions} questions."
    )
    response = client.messages.create(
        model=REASONING_MODEL,
        max_tokens=1500,
        system=LIVE_QUESTIONS_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": QUESTIONS_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    parsed = json.loads(raw)

    for covered in parsed.get("covered", []):
        ledger.mark_answered(covered)
    questions = parsed.get("questions", [])
    fresh = ledger.propose([q["question"] for q in questions])
    return [q for q in questions if q["question"] in fresh]
