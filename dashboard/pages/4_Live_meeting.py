"""Live meeting — transcript plus questions worth asking next.

Preview. Audio capture is not wired up yet (it needs a microphone, so it must be
run locally rather than in a hosted container, and the user has an existing
design artifact to fold in). The live-questions half is fully working: paste or
stream text in and it generates questions and tracks what has been covered.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import page_setup, require_claude  # noqa: E402

from src.features.transcription import (  # noqa: E402
    QuestionLedger,
    TranscriptBuffer,
    generate_live_questions,
)

page_setup("Live meeting", icon="🎙️")
st.title("🎙️ Live meeting")
st.caption("Follow the conversation and get the question worth asking next.")

st.info(
    "**Preview.** Recording and automatic transcription are not wired up yet — they need "
    "a local microphone and the design artifact still to come. Everything downstream of "
    "the transcript works now: paste text in (or Teams live captions) and the questions "
    "update as the meeting moves."
)

client = require_claude()

if "buffer" not in st.session_state:
    st.session_state.buffer = TranscriptBuffer()
    st.session_state.ledger = QuestionLedger()

buffer: TranscriptBuffer = st.session_state.buffer
ledger: QuestionLedger = st.session_state.ledger

context = st.text_input(
    "Meeting context (optional)",
    placeholder="e.g. First call with a systematic trend manager, Diversifiers sleeve",
)

col_in, col_q = st.columns([1, 1], gap="large")

with col_in:
    st.markdown("#### Transcript")
    new_text = st.text_area("Add what was just said", height=140, key="feed")
    speaker = st.text_input("Speaker (optional)", key="speaker")
    c1, c2 = st.columns(2)
    if c1.button("Add to transcript", use_container_width=True, disabled=not new_text):
        buffer.add(new_text, speaker)
        st.rerun()
    if c2.button("Clear", use_container_width=True):
        st.session_state.buffer = TranscriptBuffer()
        st.session_state.ledger = QuestionLedger()
        st.rerun()

    if buffer.segments:
        st.caption(f"{len(buffer.segments)} segments · {buffer.word_count()} words")
        with st.container(height=260):
            for seg in buffer.segments:
                st.markdown(f"**{seg.speaker or 'Speaker'}:** {seg.text}")
    else:
        st.caption("Nothing captured yet.")

with col_q:
    st.markdown("#### Questions to ask")
    if st.button("Suggest questions", type="primary",
                 disabled=client is None or not buffer.segments):
        with st.spinner("Listening…"):
            try:
                fresh = generate_live_questions(client, buffer, ledger, context)
                st.session_state.latest = fresh
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not generate questions: {e}")

    for q in st.session_state.get("latest", []):
        urgency = {"now": "🔴", "soon": "🟠", "later": "⚪"}.get(q.get("urgency"), "•")
        with st.container(border=True):
            st.markdown(f"{urgency} **{q['question']}**")
            st.caption(q.get("why", ""))
            if st.button("Mark as asked", key=f"asked-{q['question'][:40]}"):
                ledger.mark_asked(q["question"])
                st.rerun()

    if ledger.outstanding:
        with st.expander(f"Outstanding ({len(ledger.outstanding)})"):
            for q in ledger.outstanding:
                st.markdown(f"- {q}")
    if ledger.asked:
        with st.expander(f"Asked ({len(ledger.asked)})"):
            for q in ledger.asked:
                st.markdown(f"- {q}")
    if ledger.answered:
        with st.expander(f"Answered ({len(ledger.answered)})"):
            for q in ledger.answered:
                st.markdown(f"- {q}")

if buffer.segments:
    st.divider()
    st.download_button(
        "Download transcript",
        buffer.full_text(),
        file_name="meeting-transcript.md",
    )
