"""Feature-module behaviour, driven by a fake Claude client (no API calls)."""
import json

import pytest

from src.features import notion_sync, track_record
from src.features.draft_reply import _fallback_options, generate_draft_options
from src.features.inbox_triage import triage_email
from src.features.meeting_prep import (
    company_from_email_domain,
    counterparty_from_event,
    external_attendees,
)
from src.features.preferences import screen_opportunity
from src.features.transcription import QuestionLedger, TranscriptBuffer, generate_live_questions
from src.schemas import (
    Attendee,
    CalendarEvent,
    DedupeDecision,
    DedupeMatch,
    EmailMessage,
    ExtractedEntity,
    PreferenceScreen,
    TimeSlot,
)
from tests.fakes import FakeClient, FakeResponse, FakeTextBlock

EMAIL = EmailMessage(
    id="m1", subject="Cendana Capital Fund VII", sender_name="Katie Courtney",
    sender_email="katie.courtney@cendanacapital.com", received="2026-07-30T08:12:00",
    body="We are opening Fund VII, a $470m seed-stage vehicle.",
)

TRIAGE_PAYLOAD = {
    "is_investment": True, "confidence": 0.92, "category": "New fund intro",
    "rationale": "A seed-stage venture fund being marketed to us.",
    "key_facts": ["$470m target", "1.0% management fee"],
    "entity": {
        "fund_name": "Cendana Capital Fund VII", "company_name": "Cendana Capital",
        "company_domain": "", "contact_name": "Katie Courtney", "contact_email": "",
        "contact_title": "Executive Assistant", "asset_class": "Venture Capital",
        "geography": "US", "sleeve": "Private Growth", "summary": "Seed-stage FoF.",
    },
}


class TestTriage:
    def test_parses_a_classification(self):
        result = triage_email(FakeClient(TRIAGE_PAYLOAD), EMAIL)
        assert result.is_investment
        assert result.entity.fund_name == "Cendana Capital Fund VII"
        assert result.message_id == "m1"

    def test_backfills_contact_email_and_domain_from_the_sender(self):
        # The model left both blank; the sender address is authoritative.
        result = triage_email(FakeClient(TRIAGE_PAYLOAD), EMAIL)
        assert result.entity.contact_email == "katie.courtney@cendanacapital.com"
        assert result.entity.company_domain == "cendanacapital.com"

    def test_unparseable_output_is_flagged_not_raised(self):
        client = FakeClient(handler=lambda **_: FakeResponse(
            content=[FakeTextBlock(text="not json")]))
        result = triage_email(client, EMAIL)
        assert result.category == "parse_error"
        assert not result.is_investment

    def test_refusal_is_handled(self):
        client = FakeClient(handler=lambda **_: FakeResponse(content=[], stop_reason="refusal"))
        assert triage_email(client, EMAIL).category == "refused"


class TestPreferenceScreen:
    PAYLOAD = {
        "sleeve": "Private Growth", "overall_fit": "Partial",
        "fit_points": ["Venture exposure fits the growth engine"],
        "non_fit_points": ["Fund-of-funds adds a fee layer"],
        "open_questions": ["What is the look-through fee load?"],
        "summary": "Interesting but the double fee layer is the sticking point.",
    }

    def test_returns_a_validated_screen(self):
        entity = ExtractedEntity(fund_name="Cendana VII", sleeve="Private Growth")
        screen = screen_opportunity(FakeClient(self.PAYLOAD), entity, ["$470m"])
        assert screen.overall_fit == "Partial"
        assert screen.non_fit_points

    def test_loads_the_preference_pages_into_the_prompt(self):
        entity = ExtractedEntity(fund_name="X", sleeve="Diversifiers")
        client = FakeClient(self.PAYLOAD)
        screen_opportunity(client, entity, [])
        prompt = client.calls[0]["messages"][0]["content"]
        # General + Learnings always, plus the sleeve page.
        assert "general" in prompt.lower()
        assert "Diversifiers" in prompt

    CRITERIA_PAYLOAD = {
        "sleeve": "Private Growth", "overall_fit": "Non-fit",
        "summary": "Not a fit as offered.",
        "not_covered": "co-investment rights",
        "open_questions": ["What discount applies at $50m?"],
        "facts": [{"label": "Target size", "value": "$1.6bn hard cap"}],
        "criteria": [
            {"title": "Fee savings quantified", "preference": "Discounts stated",
             "rationale": "Undocumented discounts do not survive a re-up.",
             "finding": "2.0 / 20 / 8 with no discount schedule.",
             "source": "Deck p.31", "verdict": "not-fit",
             "assessment": "Not a fit because no discount is quantified."},
            {"title": "Portable playbook", "preference": "Repeatable process",
             "rationale": "One-off wins do not compound.",
             "finding": "The materials do not describe it.", "source": "",
             "verdict": "unevidenced",
             "assessment": "Unevidenced because the deck never sets it out."},
            {"title": "Equity-like return bar", "preference": "2x net or better",
             "rationale": "It must beat the public alternative.",
             "finding": "2.5x / 20% net target.", "source": "Deck p.4",
             "verdict": "fit", "assessment": "A fit because the target clears the bar."},
        ],
    }

    def test_criteria_drive_the_flat_fit_lists(self):
        """The pass rationales and triage view read the flat lists, so they
        must be derived from the criteria rather than separately invented."""
        entity = ExtractedEntity(fund_name="Northlight III", sleeve="Private Growth")
        screen = screen_opportunity(FakeClient(self.CRITERIA_PAYLOAD), entity, [])
        assert len(screen.criteria) == 3
        assert screen.non_fit_points == [
            "Not a fit because no discount is quantified."]
        assert screen.fit_points == [
            "A fit because the target clears the bar."]
        # An unevidenced criterion counts as neither a fit nor a non-fit.
        unevidenced = [c for c in screen.criteria if c.verdict == "unevidenced"]
        assert unevidenced and not unevidenced[0].source
        assert screen.facts[0].value == "$1.6bn hard cap"
        assert screen.not_covered == "co-investment rights"

    def test_prompt_forbids_scoring_the_unevidenced(self):
        from src.features.preferences import SCREEN_SYSTEM_PROMPT
        assert "Absence of evidence is not evidence" in SCREEN_SYSTEM_PROMPT


class TestDraftReplies:
    SCREEN = PreferenceScreen(
        sleeve="Private Growth", overall_fit="Non-fit",
        fit_points=[], non_fit_points=["the double fee layer of a fund-of-funds"],
        open_questions=["look-through fees?"], summary="Pass.",
    )
    ENTITY = ExtractedEntity(fund_name="Cendana VII", contact_name="Katie Courtney")

    def test_model_options_are_parsed(self):
        payload = {"options": [
            {"key": "pass_fit", "label": "Pass — fit", "intent": "pass",
             "subject": "RE: X", "body": "..."},
        ]}
        options = generate_draft_options(FakeClient(payload), EMAIL, self.ENTITY, self.SCREEN)
        assert options[0].intent == "pass"

    def test_fallback_works_without_a_client(self):
        options = generate_draft_options(None, EMAIL, self.ENTITY, self.SCREEN)
        assert options
        assert any(o.intent == "pass" for o in options)

    def test_fallback_pass_cites_the_screens_non_fit(self):
        options = _fallback_options(self.ENTITY, self.SCREEN, [])
        body = next(o.body for o in options if o.key == "pass_fit")
        assert "double fee layer" in body

    def test_meeting_option_only_appears_when_slots_are_supplied(self):
        assert not any(o.intent == "meeting" for o in _fallback_options(self.ENTITY, self.SCREEN, []))
        slots = [TimeSlot(start="2026-08-04T10:00:00", end="2026-08-04T10:30:00")]
        options = _fallback_options(self.ENTITY, self.SCREEN, slots)
        meeting = next(o for o in options if o.intent == "meeting")
        assert "10:00" in meeting.body

    def test_slots_are_passed_to_the_model_verbatim(self):
        client = FakeClient({"options": []})
        slots = [TimeSlot(start="2026-08-04T10:00:00", end="2026-08-04T10:30:00")]
        generate_draft_options(client, EMAIL, self.ENTITY, self.SCREEN, slots)
        assert "10:00" in client.calls[0]["messages"][0]["content"]


class TestNotionSync:
    ENTITY = ExtractedEntity(
        fund_name="Cendana Capital Fund VII", company_name="Cendana Capital",
        contact_name="Katie Courtney", contact_email="katie@cendanacapital.com",
        asset_class="Venture Capital", geography="US", summary="Seed FoF.",
    )

    def _decision(self, kind, action, name="x"):
        match = DedupeMatch(db="funds", matched_name="Existing", score=0.8) if action == "review" else None
        return DedupeDecision(entity_kind=kind, name=name,
                              is_duplicate=action == "link_existing",
                              best_match=match, recommended_action=action)

    def test_plans_pages_for_new_entities(self):
        decisions = {k: self._decision(k, "create") for k in ("contact", "company", "fund")}
        proposals = notion_sync.plan_creations(self.ENTITY, decisions)
        assert {p.kind for p in proposals} == {"contact", "company", "fund"}
        assert not any(p.needs_review for p in proposals)

    def test_existing_entities_are_never_recreated(self):
        decisions = {"fund": self._decision("fund", "link_existing")}
        assert notion_sync.plan_creations(self.ENTITY, decisions) == []

    def test_borderline_matches_are_flagged_for_review(self):
        decisions = {"fund": self._decision("fund", "review")}
        proposal = notion_sync.plan_creations(self.ENTITY, decisions)[0]
        assert proposal.needs_review
        assert "possible duplicate" in proposal.review_reason

    def test_review_items_are_not_created_without_explicit_approval(self):
        decisions = {"fund": self._decision("fund", "review")}
        proposals = notion_sync.plan_creations(self.ENTITY, decisions)
        result = notion_sync.apply_plan(proposals)
        assert not result.created
        assert result.skipped

    def test_approved_review_items_are_created(self):
        decisions = {"fund": self._decision("fund", "review")}
        proposals = notion_sync.plan_creations(self.ENTITY, decisions)
        result = notion_sync.apply_plan(proposals, approved_kinds={"fund"})
        assert len(result.created) == 1

    def test_contact_properties_use_the_email_field(self):
        props = notion_sync.contact_properties(self.ENTITY)
        assert props["Email"]["email"] == "katie@cendanacapital.com"
        assert props["Name"]["title"][0]["text"]["content"] == "Katie Courtney"

    def test_new_funds_enter_the_pipeline_unreviewed(self):
        props = notion_sync.fund_properties(self.ENTITY)
        assert props["Status"]["status"]["name"] == "Not reviewed"
        assert props["Asset Class"]["multi_select"][0]["name"] == "Venture Capital"


class TestMeetingPrep:
    EVENT = CalendarEvent(
        id="e1", subject="GP meeting — Old Well Labs", start="2026-08-04T10:00:00",
        end="2026-08-04T11:00:00",
        attendees=[
            Attendee(name="Jinghan Chen", email="Jinghan.Chen@weybourneholdings.com"),
            Attendee(name="Old Well Labs", email="ir@oldwelllabs.com"),
        ],
    )

    def test_internal_colleagues_are_not_the_counterparty(self):
        externals = external_attendees(self.EVENT)
        assert len(externals) == 1
        assert externals[0].email == "ir@oldwelllabs.com"

    def test_counterparty_resolved_from_external_attendee(self):
        name, email = counterparty_from_event(self.EVENT)
        assert email == "ir@oldwelllabs.com"

    def test_counterparty_falls_back_to_the_subject(self):
        event = CalendarEvent(id="e2", subject="GP meeting — Old Well Labs",
                              start="", end="", attendees=[])
        name, email = counterparty_from_event(event)
        assert name == "Old Well Labs"
        assert email == ""

    def test_company_derived_from_domain(self):
        assert company_from_email_domain("ir@oldwelllabs.com") == "Oldwelllabs"

    def test_internal_domain_yields_no_company(self):
        assert company_from_email_domain("x@weybourneholdings.com") == ""


class TestTrackRecord:
    def _periods(self, returns):
        return [track_record.PeriodicRecord(period=f"2026-Q{i+1}", return_pct=r)
                for i, r in enumerate(returns)]

    def test_cumulative_return_compounds(self):
        # 1.10 * 1.10 = 1.21 -> +21%
        assert track_record.cumulative_return_pct(self._periods([10, 10])) == 21.0

    def test_cumulative_handles_losses(self):
        assert track_record.cumulative_return_pct(self._periods([50, -50])) == -25.0

    def test_cumulative_is_none_without_returns(self):
        assert track_record.cumulative_return_pct([]) is None

    def test_max_drawdown_is_peak_to_trough(self):
        assert track_record.max_drawdown_pct(self._periods([10, -20, 5])) == -20.0

    def test_max_drawdown_is_zero_when_only_gains(self):
        assert track_record.max_drawdown_pct(self._periods([5, 5])) == 0.0

    def test_best_and_worst_periods(self):
        best, worst = track_record.best_worst_period(self._periods([3, -7, 11]))
        assert best.return_pct == 11 and worst.return_pct == -7

    def test_normalises_into_the_common_schema(self):
        payload = {
            "manager": "ActusRay", "fund": "Trend UCITS", "vehicle_type": "public",
            "strategy": "Managed futures", "currency": "USD", "inception": "2022",
            "fee_basis": "net", "benchmark": "SG Trend",
            "periods": [{"period": "2026-Q1", "return_pct": 4.1, "nav": None,
                         "called": None, "distributed": None, "dpi": None,
                         "tvpi": None, "net_irr_pct": None, "note": ""}],
            "summary_stats": [{"name": "Annualised", "value": 11.0, "unit": "%",
                               "basis": "reported", "note": ""}],
            "caveats": ["Includes simulated history before 2022"],
        }
        record = track_record.normalise_track_record(FakeClient(payload), "x", "tr.xlsx")
        assert record.vehicle_type == "public"
        assert record.summary_stats[0].basis == "reported"
        assert record.caveats
        assert record.source_file == "tr.xlsx"

    def test_flattens_to_fact_rows_skipping_nulls(self):
        record = track_record.TrackRecord(
            fund="Trend UCITS", currency="USD", source_file="tr.xlsx",
            periods=[track_record.PeriodicRecord(period="2026-Q1", return_pct=4.1, nav=101.2)],
        )
        rows = track_record.to_fact_rows(record)
        assert {r["metric_name"] for r in rows} == {"return_pct", "nav"}
        assert all(r["fund_id"] == "Trend UCITS" for r in rows)

    def test_rejects_unsupported_file_types(self, tmp_path):
        path = tmp_path / "notes.docx"
        path.write_text("x")
        with pytest.raises(ValueError, match="unsupported"):
            track_record.read_document(path)


class TestTranscription:
    def test_buffer_accumulates_and_ignores_blanks(self):
        buf = TranscriptBuffer()
        buf.add("We run a trend model.", "Manager")
        buf.add("   ")
        assert len(buf.segments) == 1
        assert "Manager: We run a trend model." in buf.full_text()

    def test_recent_text_is_truncated_to_the_tail(self):
        buf = TranscriptBuffer()
        buf.add("x" * 100)
        assert len(buf.recent_text(max_chars=50)) == 50

    def test_ledger_does_not_repeat_questions(self):
        ledger = QuestionLedger()
        assert ledger.propose(["What is the capacity?"]) == ["What is the capacity?"]
        assert ledger.propose(["What is the capacity?"]) == []

    def test_ledger_moves_questions_between_states(self):
        ledger = QuestionLedger()
        ledger.propose(["Capacity?"])
        ledger.mark_asked("Capacity?")
        assert ledger.asked == ["Capacity?"] and not ledger.outstanding
        ledger.mark_answered("Capacity?")
        assert ledger.answered == ["Capacity?"] and not ledger.asked

    def test_generated_questions_update_the_ledger(self):
        payload = {
            "questions": [{"question": "What drives the crisis alpha?",
                           "why": "Tests the real engine", "urgency": "now"}],
            "covered": [],
        }
        buf = TranscriptBuffer()
        buf.add("We target crisis alpha.")
        ledger = QuestionLedger()
        fresh = generate_live_questions(FakeClient(payload), buf, ledger)
        assert len(fresh) == 1
        assert "What drives the crisis alpha?" in ledger.outstanding

    def test_questions_the_transcript_answers_are_marked_covered(self):
        payload = {"questions": [], "covered": ["Capacity?"]}
        ledger = QuestionLedger()
        ledger.propose(["Capacity?"])
        buf = TranscriptBuffer()
        buf.add("Capacity is $2bn.")
        generate_live_questions(FakeClient(payload), buf, ledger)
        assert ledger.answered == ["Capacity?"]
