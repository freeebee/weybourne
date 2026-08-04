"""Drafts go out over the user's name, so no em dashes reach them.

Asking the model in the prompt is not a guarantee. Every option is cleaned on
the way through, including the deterministic fallbacks, which had em dashes
written into them.
"""
from src.features.draft_reply import (
    DRAFT_SYSTEM_PROMPT,
    _fallback_options,
    generate_draft_options,
    strip_dashes,
)
from src.schemas import DraftReplyOption, ExtractedEntity, PreferenceScreen, TimeSlot
from tests.fakes import FakeClient

ENTITY = ExtractedEntity(contact_name="Amy Zhao", fund_name="BAI Capital IV")
SCREEN = PreferenceScreen(sleeve="Private Growth", overall_fit="Non-fit",
                          summary="Not a fit.", non_fit_points=["fees are top of market"],
                          open_questions=["what is the GP commitment?"])


def _opt(**kw):
    base = dict(key="k", label="l", intent="pass", subject="s", body="b")
    return DraftReplyOption(**{**base, **kw})


class TestCleaner:
    def test_an_em_dash_becomes_a_comma(self):
        out = strip_dashes([_opt(body="We will pass — the fees are high.")])
        assert "—" not in out[0].body
        assert "pass, the fees" in out[0].body

    def test_en_dashes_go_too(self):
        assert "–" not in strip_dashes([_opt(body="2024 – 2025 vintages")])[0].body

    def test_the_subject_and_label_are_cleaned(self):
        out = strip_dashes([_opt(subject="RE: Fund — terms", label="Pass — fit")])
        assert "—" not in out[0].subject and "—" not in out[0].label

    def test_hyphens_in_compound_words_survive(self):
        body = "a co-investment in a mid-market buy-out"
        assert strip_dashes([_opt(body=body)])[0].body == body

    def test_a_dash_next_to_punctuation_does_not_leave_a_double(self):
        out = strip_dashes([_opt(body="the fees —, frankly, are high")])[0].body
        assert ",," not in out and ", ," not in out

    def test_a_minus_sign_becomes_a_hyphen_not_a_comma(self):
        assert strip_dashes([_opt(body="down −3% this year")])[0].body == "down -3% this year"


class TestBothPaths:
    def test_the_fallback_drafts_are_clean(self):
        """These are hand-written and had em dashes in them."""
        for o in strip_dashes(_fallback_options(ENTITY, SCREEN, [])):
            assert "—" not in o.body and "—" not in o.label

    def test_the_fallback_path_cleans_itself(self):
        for o in generate_draft_options(None, None, ENTITY, SCREEN):
            assert "—" not in o.body and "—" not in o.label

    def test_the_model_path_cleans_itself(self):
        payload = {"options": [{"key": "pass_fit", "label": "Pass — fit",
                                "intent": "pass", "subject": "RE: BAI — pass",
                                "body": "Hi Amy,\n\nWe will pass — the fees.\n\nBest"}]}
        from src.schemas import EmailMessage
        out = generate_draft_options(
            FakeClient(payload),
            EmailMessage(id="1", subject="s", body="b"), ENTITY, SCREEN)
        assert "—" not in out[0].body
        assert "—" not in out[0].subject
        assert "—" not in out[0].label

    def test_the_prompt_says_so_as_well(self):
        """Cleaning after the fact repairs the text but leaves the rhythm the
        model wrote for a dash; the instruction is what avoids that."""
        assert "NEVER use an em dash" in DRAFT_SYSTEM_PROMPT


class TestSlots:
    def test_a_meeting_draft_is_clean(self):
        slots = [TimeSlot(start="2026-08-10T09:00:00", end="2026-08-10T09:30:00")]
        for o in strip_dashes(_fallback_options(ENTITY, SCREEN, slots)):
            assert "—" not in o.body
