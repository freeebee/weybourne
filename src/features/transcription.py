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

from src.config import FAST_MODEL, REASONING_MODEL


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


# --------------------------------------------------------------------------- #
# Panel-style reads (modelled on the live-questions-panel reference design:
# docs/reference/live-questions-panel.html). Each read returns a batch — a tight
# recap of the new speech, answers to open questions, and fresh flagged
# questions — which the page renders as a timeline.
# --------------------------------------------------------------------------- #

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "changed": {"type": "boolean"},
        "recap": {
            "type": "string",
            "description": "One tight paragraph on the concrete points just made: "
                           "figures, names, terms, claims, commitments. Empty if nothing new.",
        },
        "answered": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "answer": {"type": "string",
                               "description": "What they actually said, under 30 words, "
                                              "with the figure or name"},
                },
                "required": ["id", "answer"],
                "additionalProperties": False,
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "flag": {"type": "boolean",
                             "description": "True for the one or two sharpest risk items only"},
                },
                "required": ["q", "flag"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["changed", "recap", "answered", "questions"],
    "additionalProperties": False,
}

READ_SYSTEM_PROMPT = """You are helping an investor at Weybourne, a single family office, \
during a live meeting. Weybourne is on the LP side: they allocate, and they are probing the \
counterparty, so every question must be answerable by the counterparty in the room.

Rules:
- Check EVERY open question against the new speech, one by one, before anything else. If \
the new speech addresses one — even partially — report it in "answered" with what was \
actually said (a partial answer should say what is still missing). Never invent an answer. \
A vague or dodged reply does not count — leave it open and re-pose it sharper as a new \
question. Missing a genuinely answered question is the worst failure mode: it leaves the \
investor asking something the room already answered.
- Give 3 to 5 new questions, most useful first; flag true for the one or two sharpest risk \
items only. Probe capacity, economics and fees, valuation and marks, team lineage and \
attribution, process, key person risk, and any contradiction with what was said earlier.
- The transcript is machine generated: if a figure looks mistranscribed, ask them to confirm \
it rather than treating it as fact.
- If no meaningful new speech has appeared, set changed to false with empty recap, answered \
and questions.
- Keep each question one sentence a person can say out loud. Never use em dashes."""


def read_transcript_batch(
    client,
    buffer: TranscriptBuffer,
    open_items: list[dict],
    context: str = "",
    prior_recaps: str = "",
    last_tail: str = "",
) -> dict:
    """One panel-style read: recap of new speech + answered ids + fresh questions.

    ``open_items`` is a list of {"id": int, "q": str} still outstanding.
    """
    open_list = "\n".join(f"[{it['id']}] {it['q']}" for it in open_items) or "(none open)"
    user = (
        f"MEETING CONTEXT\n{context or '(none supplied)'}\n\n"
        f"TAIL AT PREVIOUS READ\n\"\"\"{last_tail or '(nothing seen yet)'}\"\"\"\n"
        "Everything after that point is new speech. Speaker labels are unreliable; infer who "
        "is talking.\n\n"
        f"OPEN QUESTIONS\n{open_list}\n\n"
        f"EARLIER IN THIS CALL\n\"\"\"{prior_recaps or '(nothing yet)'}\"\"\"\n\n"
        f"TRANSCRIPT (recent window)\n{buffer.recent_text()}"
    )
    response = client.messages.create(
        # Fast model: this fires every 30 seconds mid-call — latency beats
        # marginal quality here, and the read task is well within its range.
        model=FAST_MODEL,
        max_tokens=1500,
        system=READ_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": READ_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    return json.loads(raw)


SHARPEN_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "The rewritten question, under 45 words"},
        "status": {"type": "string", "enum": ["answered", "partial", "open"]},
        "evidence": {"type": "string",
                     "description": "If answered or partial: what they said, under 30 words. "
                                    "Otherwise empty."},
        "why": {"type": "string", "description": "What the rewrite sharpened, under 15 words"},
    },
    "required": ["question", "status", "evidence", "why"],
    "additionalProperties": False,
}


def sharpen_question(client, buffer: TranscriptBuffer, rough: str, context: str = "") -> dict:
    """Rewrite a rough mid-call sketch into one sharp question, checked against the transcript."""
    user = (
        f"MEETING CONTEXT\n{context or '(none supplied)'}\n\n"
        "The investor has sketched a rough question mid-call and wants it sharpened and "
        "checked against what has been said.\n\n"
        f"THEIR SKETCH (possibly shorthand)\n\"\"\"{rough}\"\"\"\n\n"
        "Rewrite it as one sharp question the counterparty can answer: keep the intent, make "
        "it specific, anchor it to figures, names or claims actually made, cut hedging. Then "
        "decide whether the transcript already covers it. Never invent an answer or figure. "
        "Never use em dashes.\n\n"
        f"TRANSCRIPT (recent window)\n{buffer.recent_text()}"
    )
    response = client.messages.create(
        # Fast model: the user is waiting mid-conversation for this rewrite.
        model=FAST_MODEL,
        max_tokens=800,
        system=READ_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": SHARPEN_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    return json.loads(raw)


NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "e.g. 'Call with Axiom Asia'"},
        "note_type": {
            "type": "string",
            "enum": ["GP Meeting", "LP Meeting", "Reference call", "3rd Party Marketer",
                     "Event", "Internal", "Service Provider", "Email"],
        },
        "overall_impression": {
            "type": "string",
            "description": "One paragraph of judgement on what they presented and how it held up",
        },
        "next_stage": {"type": "string", "description": "What happens next and by when"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["heading", "bullets"],
                "additionalProperties": False,
            },
        },
        "qa": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
                "required": ["q", "a"],
                "additionalProperties": False,
            },
            "description": "The most consequential exchanges, at most 10. Where a question "
                           "was dodged, say so plainly in the answer.",
        },
    },
    "required": ["title", "note_type", "overall_impression", "next_stage", "sections", "qa"],
    "additionalProperties": False,
}

NOTE_SYSTEM_PROMPT = """You draft a Weybourne meeting note from a live transcript.

House style: third person, past tense, plain institutional English. State what the manager \
said as their claim, not as fact. Keep every figure, name and date they gave. Never invent \
anything not in the transcript. Never use em dashes. One heading per substantive topic in the \
order discussed. Never include an Action Items section."""


def draft_meeting_note(
    client,
    buffer: TranscriptBuffer,
    context: str = "",
    unanswered: list[str] | None = None,
) -> dict:
    """Draft the end-of-call note from the full transcript."""
    open_qs = "\n".join(f"- {q}" for q in (unanswered or [])) or "(none)"
    user = (
        f"MEETING CONTEXT\n{context or '(none supplied)'}\n\n"
        f"QUESTIONS THAT NEVER GOT ANSWERED (note them under next steps)\n{open_qs}\n\n"
        f"FULL TRANSCRIPT\n{buffer.full_text()[:24000]}"
    )
    response = client.messages.create(
        model=REASONING_MODEL,
        max_tokens=4000,
        system=NOTE_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": NOTE_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    return json.loads(raw)


def note_to_markdown(note: dict) -> str:
    """The drafted note as markdown, ready to paste into Notion."""
    lines = [
        f"# {note['title']}",
        f"*{note['note_type']}*",
        "",
        "### Meeting Overview",
        "---",
        f"- **Overall Impression** - {note['overall_impression']}",
        f"- **Next Stage** - {note['next_stage']}",
        "",
    ]
    for sec in note.get("sections", []):
        lines += [f"### {sec['heading']}", "---"]
        lines += [f"- {b}" for b in sec["bullets"]]
        lines.append("")
    if note.get("qa"):
        lines += ["### Q&A", "---"]
        for pair in note["qa"]:
            lines += [f"**Q**: {pair['q']}", f"**A** - {pair['a']}", ""]
    return "\n".join(lines)


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
