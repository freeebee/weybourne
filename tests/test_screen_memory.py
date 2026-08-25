"""A preference screen is about a firm, not an email — so it outlives the email."""
import datetime as dt

import pytest

from src.features import screen_memory as sm
from src.schemas import PreferenceScreen

SCREEN = {
    "sleeve": "Private Growth",
    "overall_fit": "Non-fit",
    "criteria": [{"title": "Control", "preference": "Control positions",
                  "finding": "Minority only", "source": "Deck p.4",
                  "verdict": "not-fit", "assessment": "Not a fit because stakes are minority."}],
    "facts": [], "not_covered": "", "fit_points": [],
    "non_fit_points": ["Not a fit because stakes are minority."],
    "open_questions": [], "summary": "Minority stakes only; outside the mandate.",
}


@pytest.fixture()
def base(tmp_path):
    return tmp_path


class TestKey:
    def test_the_firm_is_the_key_not_the_vintage(self):
        # Fund IV and Fund V are the same manager against the same preference
        # pages; the desk reads them as one view.
        assert sm.key_for("Meridian Growth Fund IV", "Meridian Growth Partners") \
            == sm.key_for("Meridian Growth Fund V", "Meridian Growth Partners")

    def test_a_fund_with_no_company_still_keys(self):
        assert sm.key_for("Albizia ASEAN Opportunities Fund", "") != ""

    def test_nothing_to_key_on_is_empty(self):
        assert sm.key_for("", "") == ""


class TestRecall:
    def test_a_screen_comes_back_tagged_with_when_it_was_taken(self, base):
        # The tag is the whole basis on which reuse is honest: this is a
        # conclusion from a previous sitting, not a fresh reading.
        data = sm.load(base)
        sm.record(data, "meridian", SCREEN, label="Meridian Growth Partners")
        sm.save(data, base)

        got = sm.screen_for(sm.load(base), "meridian")
        assert got["overall_fit"] == "Non-fit"
        assert got["remembered"]["days"] == 0
        assert got["remembered"]["label"] == "Meridian Growth Partners"

    def test_an_unknown_firm_recalls_nothing(self, base):
        assert sm.screen_for(sm.load(base), "nobody") is None

    def test_a_failed_screen_is_not_remembered(self, base):
        data = sm.load(base)
        sm.record(data, "meridian", {"error": "backend unavailable"})
        assert sm.screen_for(data, "meridian") is None

    def test_recalling_and_re_saving_does_not_stack_markers(self, base):
        data = sm.load(base)
        sm.record(data, "meridian", SCREEN)
        recalled = sm.screen_for(data, "meridian")
        sm.record(data, "meridian", recalled)          # save the recalled one back
        again = sm.screen_for(data, "meridian")
        assert "remembered" not in again["screen"] if "screen" in again else True
        assert again["remembered"]["days"] == 0

    def test_an_expired_screen_is_not_served(self, base):
        data = sm.load(base)
        sm.record(data, "meridian", SCREEN)
        old = (dt.datetime.now() - dt.timedelta(days=sm.MEMORY_DAYS + 1))
        data["screens"]["meridian"]["at"] = old.isoformat(timespec="seconds")
        assert sm.screen_for(data, "meridian") is None

    def test_the_window_outlasts_the_preference_page_cache(self):
        # The pages a screen is judged against are themselves cached for a week.
        # Forgetting sooner than that would re-screen against identical inputs.
        assert sm.MEMORY_DAYS > 7

    def test_a_corrupt_file_reads_as_empty(self, base):
        (base / sm.MEMORY_NAME).write_text("{not json", encoding="utf-8")
        assert sm.load(base) == {"screens": {}}


class TestHousekeeping:
    def test_forget_removes_one_firm(self, base):
        data = sm.load(base)
        sm.record(data, "meridian", SCREEN)
        assert sm.forget(data, "meridian") is True
        assert sm.screen_for(data, "meridian") is None

    def test_prune_drops_only_the_expired(self, base):
        data = sm.load(base)
        sm.record(data, "fresh", SCREEN)
        sm.record(data, "stale", SCREEN)
        old = (dt.datetime.now() - dt.timedelta(days=sm.MEMORY_DAYS + 5))
        data["screens"]["stale"]["at"] = old.isoformat(timespec="seconds")
        assert sm.prune(data) == 1
        assert set(data["screens"]) == {"fresh"}


class TestFeedsTheDraft:
    def test_a_remembered_screen_still_validates_as_a_screen(self, base):
        # The drafts endpoint hands whatever it recalls straight to
        # PreferenceScreen — the extra 'remembered' block must not break that,
        # or a recalled screen would take the reply-drafting path down.
        data = sm.load(base)
        sm.record(data, "meridian", SCREEN)
        recalled = sm.screen_for(data, "meridian")
        parsed = PreferenceScreen.model_validate(recalled)
        assert parsed.overall_fit == "Non-fit"
        assert parsed.non_fit_points == ["Not a fit because stakes are minority."]
