"""Entity mentions ride the live read — detection without a new call.

Every read may flag up to three people/companies/funds whose mention carried
weight, for the MENTIONS tab to look up in the firm's own records. The rules
the prompt states are re-enforced here in code, because a prompt is a request
and a postprocess is a guarantee: the counterparty and Weybourne are never
flagged, an entity is flagged at most once per meeting, and a read can never
flood the tab.
"""
import pytest

from src.features import transcription
from src.features.transcription import _postprocess_entities


def ent(name, kind="company", context="discussed at length"):
    return {"name": name, "kind": kind, "context": context}


class TestSchema:
    def test_entities_is_part_of_the_read_schema_and_required(self):
        props = transcription.READ_SCHEMA["properties"]
        assert "entities" in props
        assert "entities" in transcription.READ_SCHEMA["required"]
        item = props["entities"]["items"]
        assert item["required"] == ["name", "kind", "context"]
        assert item["additionalProperties"] is False
        assert item["properties"]["kind"]["enum"] == ["person", "company", "fund"]

    def test_entities_is_the_last_property(self):
        """Question generation must stay first in the output — the questions
        are what the user is waiting on; mentions are a bonus."""
        assert list(transcription.READ_SCHEMA["properties"])[-1] == "entities"


class TestExclusion:
    def test_the_counterparty_is_never_flagged(self):
        out = _postprocess_entities([ent("Fife Capital")], [], ["Fife Capital"])
        assert out == []

    def test_exclusion_works_by_containment_in_both_directions(self):
        """Whisper renders the counterparty many ways mid-meeting — "Fife",
        "Fife Capital", "Allan Fife". Containment catches the variants the
        similarity score misses."""
        assert _postprocess_entities([ent("Fife")], [], ["Fife Capital"]) == []
        assert _postprocess_entities([ent("Fife Capital Partners")], [], ["Fife"]) == []

    def test_weybourne_itself_is_always_excluded(self):
        assert _postprocess_entities([ent("Weybourne")], [], []) == []
        assert _postprocess_entities([ent("Weybourne Holdings")], [], []) == []

    def test_an_unrelated_name_is_not_excluded(self):
        out = _postprocess_entities([ent("Brookfield")], [], ["Fife Capital"])
        assert [e["name"] for e in out] == ["Brookfield"]


class TestDedupe:
    def test_an_already_flagged_entity_is_not_flagged_again(self):
        assert _postprocess_entities([ent("Brookfield")], ["Brookfield"], []) == []

    def test_dedupe_is_strict_where_exclusion_is_loose(self):
        """"Blackstone Credit" after a notified "Blackstone" is genuinely new
        information — deduping it away would silently lose it. Dedupe fires
        only at DUPLICATE_THRESHOLD, not the looser exclusion band."""
        out = _postprocess_entities([ent("Blackstone Credit")], ["Blackstone"], [])
        assert [e["name"] for e in out] == ["Blackstone Credit"]

    def test_duplicates_within_one_read_collapse(self):
        out = _postprocess_entities(
            [ent("Brookfield"), ent("Brookfield Asset Management")], [], [])
        assert len(out) == 1

    def test_a_read_is_capped_at_three(self):
        out = _postprocess_entities(
            [ent(f"Firm {n}") for n in ("Alpha", "Beta", "Gamma", "Delta", "Epsilon")],
            [], [])
        assert len(out) == transcription.MAX_NEW_ENTITIES_PER_READ == 3


class TestDefensiveShapes:
    def test_empty_names_are_dropped(self):
        assert _postprocess_entities([ent(""), ent("   ")], [], []) == []

    def test_a_kind_outside_the_enum_is_coerced_to_company(self):
        out = _postprocess_entities([ent("Brookfield", kind="charity")], [], [])
        assert out[0]["kind"] == "company"

    def test_none_inputs_are_harmless(self):
        assert _postprocess_entities([ent("Brookfield")], None, None) != []


class TestBakedSchema:
    """A persistent live-read session bakes its schema at process spawn: a
    meeting already in flight when this feature shipped keeps answering in
    the old shape, with no entities key at all — and its one-shot fallback
    reads CAN carry the new shape, so one meeting may mix both."""

    def _fake_client(self, payload):
        import json as _json

        class Block:
            type = "text"
            def __init__(self, text):
                self.text = text

        class Response:
            def __init__(self, text):
                self.content = [Block(text)]

        class Messages:
            def create(self, **kwargs):
                return Response(_json.dumps(payload))

        class Client:
            messages = Messages()

        return Client()

    BASE = {"meeting_mode": "investment", "meeting_mode_confidence": "high",
            "changed": False, "recap": "", "answered": [], "questions": []}

    def test_an_old_schema_response_yields_an_empty_entities_list(self):
        client = self._fake_client(dict(self.BASE))     # no entities key
        parsed = transcription.read_transcript_batch_delta(client, "new speech", [])
        assert parsed["entities"] == []

    def test_a_new_schema_response_is_postprocessed(self):
        client = self._fake_client({**self.BASE,
                                    "entities": [ent("Brookfield"), ent("Weybourne")]})
        parsed = transcription.read_transcript_batch_delta(client, "new speech", [])
        assert [e["name"] for e in parsed["entities"]] == ["Brookfield"]

    def test_the_watchlist_reaches_the_prompt(self):
        sent = {}

        class Messages:
            def create(self, **kwargs):
                sent["user"] = kwargs["messages"][0]["content"]
                import json as _json

                class Block:
                    type = "text"
                    text = _json.dumps(TestBakedSchema.BASE)
                class Response:
                    content = [Block()]
                return Response()

        class Client:
            messages = Messages()

        transcription.read_transcript_batch_delta(
            Client(), "new speech", [], known_entities=["Brookfield", "KKR"])
        assert "ENTITY WATCHLIST" in sent["user"]
        assert "- Brookfield" in sent["user"]
        assert "- KKR" in sent["user"]


def test_the_kill_switch_is_a_single_constant():
    """MAX_NEW_ENTITIES_PER_READ = 0 must turn detection off outright."""
    assert _postprocess_entities([ent("Brookfield")], [], []) != []
    original = transcription.MAX_NEW_ENTITIES_PER_READ
    try:
        transcription.MAX_NEW_ENTITIES_PER_READ = 0
        assert _postprocess_entities([ent("Brookfield")], [], []) == []
    finally:
        transcription.MAX_NEW_ENTITIES_PER_READ = original
