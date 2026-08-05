"""A meeting with our own people is prepared differently.

Weybourne, Weybourne Partners and Tarenna addresses are all internal. When
every attendee is one of ours there is no counterparty: nothing to research
about them, and nothing to screen against the preference pages. The prep is
built from what the two of you have been mailing each other instead.
"""
import pytest

from src.features import meeting_prep as mp
from src.features.brief_builder import INTERNAL_BRIEFING_NOTE, synthesize_briefing
from src.schemas import Attendee, CalendarEvent
from tests.fakes import FakeClient


def event(*attendees, subject="Catch-up"):
    return CalendarEvent(
        id="e1", subject=subject, start="2026-08-05T10:00:00", end="",
        attendees=[Attendee(name=n, email=e) for n, e in attendees])


class TestWhoIsInternal:
    @pytest.mark.parametrize("email", [
        "ally@weybourne.co.uk",
        "simon.richards@weybourneholdings.com",
        "x@weybournepartners.com",
        "y@tarenna.com",
        "Z@TARENNA.CO.UK",
        "a@mail.weybourne.co.uk",          # a subdomain is still us
    ])
    def test_our_domains(self, email):
        assert mp.is_internal(email)

    @pytest.mark.parametrize("email", [
        "adam@denmancapital.com",
        "catherine@pitingcapital.com",
        "someone@notweybourne.com",        # not a suffix match
    ])
    def test_outside_domains(self, email):
        assert not mp.is_internal(email)

    def test_a_name_with_no_address_can_still_read_as_internal(self):
        assert mp.is_internal("", "Weybourne Investments")
        assert mp.is_internal("", "Tarenna Ops")

    def test_a_plain_outside_name_does_not(self):
        assert not mp.is_internal("", "Amy Zhao")


class TestEventClassification:
    def test_all_internal_attendees_is_an_internal_meeting(self):
        ev = event(("Ally", "ally@weybourne.co.uk"),
                   ("Jinghan", "jinghan@weybourneholdings.com"))
        assert mp.event_is_internal(ev)

    def test_one_outsider_makes_it_external(self):
        ev = event(("Ally", "ally@weybourne.co.uk"),
                   ("Amy Zhao", "amy@baifund.com"))
        assert not mp.event_is_internal(ev)

    def test_an_invitation_with_no_attendees_is_not_internal(self):
        """A calendar entry typed for yourself is the commonest way a prep is
        requested, and the counterparty is the name in the subject."""
        ev = event(subject="GP meeting — Old Well Labs")
        assert not mp.event_is_internal(ev)
        assert mp.counterparty_from_event(ev)[0] == "Old Well Labs"

    def test_the_colleague_is_the_subject_of_an_internal_prep(self):
        ev = event(("Ally Tan", "ally@weybourne.co.uk"))
        assert mp.counterparty_from_event(ev) == ("Ally Tan", "ally@weybourne.co.uk")

    def test_the_outsider_is_picked_out_of_a_mixed_invitation(self):
        ev = event(("Ally", "ally@weybourne.co.uk"),
                   ("Amy Zhao", "amy@baifund.com"))
        assert mp.counterparty_from_event(ev) == ("Amy Zhao", "amy@baifund.com")


class FakeMail:
    def __init__(self, *msgs):
        self.msgs = list(msgs)
        self.asked = []

    def __call__(self, who):
        self.asked.append(who)
        return self.msgs


class Msg:
    def __init__(self, subject, body, received="2026-08-01T09:00:00"):
        self.subject, self.body, self.received = subject, body, received
        self.body_preview = body[:80]
        self.sender_name, self.sender_email = "Ally Tan", "ally@weybourne.co.uk"


class TestContext:
    def test_the_mail_history_is_gathered(self, monkeypatch):
        monkeypatch.setattr(mp, "gather_notion_context", lambda *a, **k: ("", []))
        mail = FakeMail(Msg("Q3 pacing", "We still need the pacing model by Friday."))
        ctx = mp.build_context(None, "Ally Tan", "ally@weybourne.co.uk",
                               internal=True, emails=mail)
        assert ctx.internal
        assert "pacing model by Friday" in ctx.email_context
        assert mail.asked == ["ally@weybourne.co.uk"]
        assert any("Outlook" in s for s in ctx.sources)

    def test_no_mail_is_gathered_for_an_outside_party(self, monkeypatch):
        monkeypatch.setattr(mp, "gather_notion_context", lambda *a, **k: ("", []))
        mail = FakeMail(Msg("x", "y"))
        ctx = mp.build_context(None, "Amy Zhao", "amy@baifund.com", emails=mail)
        assert mail.asked == [] and ctx.email_context == ""

    def test_a_colleague_gets_no_company_from_their_domain(self, monkeypatch):
        """Weybourne is not the counterparty's firm — there is no firm."""
        monkeypatch.setattr(mp, "gather_notion_context", lambda *a, **k: ("", []))
        ctx = mp.build_context(None, "Ally", "ally@weybourne.co.uk", internal=True)
        assert ctx.company_name == ""

    def test_a_broken_mailbox_does_not_fail_the_prep(self, monkeypatch):
        monkeypatch.setattr(mp, "gather_notion_context", lambda *a, **k: ("", []))

        def boom(_who):
            raise RuntimeError("Graph is down")

        ctx = mp.build_context(None, "Ally", "ally@weybourne.co.uk",
                               internal=True, emails=boom)
        assert "could not read the mail history" in ctx.email_context


class TestBriefing:
    def _brief(self, ctx):
        client = FakeClient(payload={"entity": "Ally Tan", "descriptor": "colleague"})
        synthesize_briefing(client, ctx)
        return client.calls[0]

    def test_an_internal_briefing_is_told_not_to_research(self):
        ctx = mp.PrepContext(counterparty_name="Ally Tan", internal=True,
                             email_context="[2026-08-01] Q3 pacing — from Ally")
        call = self._brief(ctx)
        user = call["messages"][0]["content"]
        assert INTERNAL_BRIEFING_NOTE in user
        assert "Q3 pacing" in user
        assert "BACKGROUND RESEARCH" not in user

    def test_an_internal_briefing_is_given_no_web_tools(self):
        """Handing a search tool to a call about a colleague's name is an
        invitation to search for them."""
        ctx = mp.PrepContext(counterparty_name="Ally Tan", internal=True)
        assert "extra_allowed_tools" not in self._brief(ctx)

    def test_an_external_briefing_still_researches(self):
        ctx = mp.PrepContext(counterparty_name="BAI Capital")
        call = self._brief(ctx)
        assert call["extra_allowed_tools"] == ["WebSearch", "WebFetch"]
        assert "BACKGROUND RESEARCH" in call["messages"][0]["content"]
        assert INTERNAL_BRIEFING_NOTE not in call["messages"][0]["content"]


class TestMailFormatting:
    def test_each_message_carries_its_date_and_subject(self):
        out = mp.format_email_history([Msg("Q3 pacing", "the model is late")])
        assert "[2026-08-01]" in out and "Q3 pacing" in out
        assert "the model is late" in out

    def test_long_bodies_are_trimmed(self):
        out = mp.format_email_history([Msg("s", "word " * 500)])
        assert len(out) < 900

    def test_the_history_is_capped(self):
        out = mp.format_email_history([Msg(f"s{i}", "b") for i in range(30)], limit=5)
        assert out.count("from Ally Tan") == 5
