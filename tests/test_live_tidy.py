"""The Haiku tidy step: raw whisper chunks → clean sentences in the chosen
output language, without losing content."""
from src.config import FAST_MODEL
from src.features.transcription import tidy_transcript_chunk
from tests.fakes import FakeClient


def test_tidy_returns_cleaned_text_and_briefs_the_model():
    client = FakeClient(payload={"text": "We closed the fund at $300 million."})
    out = tidy_transcript_chunk(
        client,
        raw="we closed the fund at ah three hundred million",
        prev_tail="The manager walked through the raise.",
        output_language="English",
        detected_language="en",
    )
    assert out == "We closed the fund at $300 million."

    call = client.calls[0]
    assert call["model"] == FAST_MODEL
    user = call["messages"][0]["content"]
    assert "OUTPUT LANGUAGE: English" in user
    assert "DETECTED SPOKEN LANGUAGE: en" in user
    assert "The manager walked through the raise." in user
    assert "we closed the fund at ah three hundred million" in user


def test_tidy_translates_into_the_output_language_brief():
    client = FakeClient(payload={"text": "They will send the deck tomorrow."})
    tidy_transcript_chunk(client, raw="明天他们会把材料发过来",
                          output_language="English", detected_language="zh")
    user = client.calls[0]["messages"][0]["content"]
    assert "OUTPUT LANGUAGE: English" in user
    assert "DETECTED SPOKEN LANGUAGE: zh" in user


def test_tidy_noise_chunk_comes_back_empty():
    client = FakeClient(payload={"text": ""})
    assert tidy_transcript_chunk(client, raw="uh hmm") == ""
