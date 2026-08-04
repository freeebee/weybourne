"""Gap-filling: identity resolution, company creation guards, and the
evidence-before-web contract."""
import pytest

from src.config import LIVE_MODEL
from src.features.felix import enrich
from tests.fakes import FakeClient


def _co(cid, name):
    return {"id": cid, "name": name, "archived": False, "plain": {},
            "relations": {}, "db": "companies"}


class TestResolveName:
    COMPANIES = [_co("c1", "Axeleo Capital"), _co("c2", "Axiom Asia"),
                 _co("c3", "Blackstone")]

    def test_exact_name_links_straight_through(self):
        hit = enrich.resolve_name("Axeleo Capital", self.COMPANIES)
        assert hit["match"]["id"] == "c1"
        assert hit["near"] is None

    def test_a_near_miss_never_links_itself(self):
        """'Axonia' must not silently attach to 'Axiom Asia' — a wrong
        relation is invisible once written."""
        hit = enrich.resolve_name("Axonia Partners", self.COMPANIES)
        assert hit["match"] is None

    def test_an_unknown_name_matches_nothing(self):
        hit = enrich.resolve_name("Rothesay Partners", self.COMPANIES)
        assert hit["match"] is None and hit["near"] is None

    def test_archived_records_are_not_matched(self):
        archived = [{**_co("c9", "Axeleo Capital"), "archived": True}]
        assert enrich.resolve_name("Axeleo Capital", archived)["match"] is None


class TestContactResearch:
    PAYLOAD = {"employer": "Axeleo Capital", "title": "Head of IR",
               "description": "Investor relations lead.",
               "linkedin_url": "https://linkedin.com/in/lgoupil",
               "photo_url": "https://media.example.com/p.jpg",
               "confidence": "high", "evidence": "Axeleo team page",
               "used_web": True}

    def test_runs_on_sonnet_with_web_access(self):
        client = FakeClient(self.PAYLOAD)
        card = {"name": "Laure Goupil", "email": "lgoupil@axeleo.com",
                "domain": "axeleo.com", "plain": {}}
        out = enrich.research_contact(client, card, "", ["employer"])
        assert out["employer"] == "Axeleo Capital"
        call = client.calls[0]
        assert call["model"] == LIVE_MODEL
        assert call["extra_allowed_tools"] == ["WebSearch", "WebFetch"]

    def test_workspace_notes_are_put_before_the_web(self):
        client = FakeClient(self.PAYLOAD)
        card = {"name": "Laure Goupil", "email": "", "domain": "", "plain": {}}
        enrich.research_contact(client, card, "Note: Laure joined Axeleo in 2021.")
        user = client.calls[0]["messages"][0]["content"]
        assert "Laure joined Axeleo in 2021" in user
        assert "WORKSPACE EVIDENCE" in user
        assert "supplied workspace evidence" in client.calls[0]["system"].lower()


class TestNoteInference:
    def test_note_type_outside_the_options_is_dropped(self):
        """The model may only choose from the live select options."""
        client = FakeClient({"attendees": ["Josh Katzin"],
                             "note_type": "Coffee chat", "confidence": "high",
                             "evidence": "met Josh"})
        out = enrich.infer_note_fields(
            client, {"name": "Call with Cavamont"}, "Josh Katzin attended.",
            ["GP Meeting", "Internal"])
        assert out["note_type"] == ""
        assert out["attendees"] == ["Josh Katzin"]

    def test_a_valid_option_survives(self):
        client = FakeClient({"attendees": [], "note_type": "GP Meeting",
                             "confidence": "high", "evidence": "pitch"})
        out = enrich.infer_note_fields(
            client, {"name": "Cavamont pitch"}, "They pitched Fund III.",
            ["GP Meeting", "Internal"])
        assert out["note_type"] == "GP Meeting"

    def test_attendees_must_have_been_present(self):
        system = enrich._NOTE_SYSTEM
        assert "PRESENT" in system
        assert "never infer an attendee" in system.lower()
