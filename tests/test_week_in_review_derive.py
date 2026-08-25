"""Pure derivation logic: window maths, duplicate detection, stats. Nothing
here touches Notion or the model — see src/features/week_in_review's
package docstring for why that separation matters."""
from datetime import date

from src.features.week_in_review import derive


def note(id_, title, note_type="GP Meeting", thoughts="", body="",
        created="2026-08-04T09:00:00.000Z"):
    return {"id": id_, "title": title, "note_type": note_type, "date": "2026-08-04",
            "thoughts": thoughts, "body": body, "fund_ids": [],
            "created_time": created, "last_edited_time": created,
            "url": f"https://notion.so/{id_}"}


def fund(id_, name, status="Track", created="2026-07-01T00:00:00.000Z"):
    return {"id": id_, "name": name, "status": status, "quality": "High",
            "asset_class": [], "geographic_focus": [],
            "created_time": created, "last_edited_time": created,
            "url": f"https://notion.so/{id_}"}


class TestSubjectKey:
    def test_call_with_and_meeting_with_collapse_together(self):
        assert (derive.subject_key("Call with Axiom Asia")
                == derive.subject_key("Meeting with Axiom Asia"))

    def test_different_parentheticals_stay_distinct(self):
        a = derive.subject_key("Trivest (interview)")
        b = derive.subject_key("Trivest (reference call)")
        assert a != b


class TestFindDuplicateSets:
    def test_keeps_the_longer_content_note_as_keeper(self):
        a = note("a", "Call with Axiom Asia", thoughts="short")
        b = note("b", "Meeting with Axiom Asia",
                 body="a much longer write-up of the same meeting, in the page body")
        sets = derive.find_duplicate_sets([a, b])
        assert len(sets) == 1
        assert sets[0]["keeper"]["id"] == "b"

    def test_note_template_is_never_grouped(self):
        a = note("a", "Note Template")
        b = note("b", "Note Template")
        assert derive.find_duplicate_sets([a, b]) == []

    def test_distinct_subjects_are_not_a_duplicate_set(self):
        a = note("a", "Call with Axiom Asia", thoughts="x")
        b = note("b", "Call with REVA", thoughts="y")
        assert derive.find_duplicate_sets([a, b]) == []


class TestNoteContent:
    def test_body_wins_when_it_already_contains_the_thoughts_summary(self):
        n = note("a", "x", thoughts="the short version",
                 body="the short version, expanded with a lot more detail")
        assert derive.note_content(n) == n["body"]

    def test_both_are_joined_when_the_body_is_independent(self):
        n = note("a", "x", thoughts="thought A", body="unrelated body B")
        out = derive.note_content(n)
        assert "thought A" in out and "unrelated body B" in out


class TestDeclinedNames:
    def test_matches_the_declined_suffix_only(self):
        funds = [fund("f1", "Track Fund", status="Track"),
                 fund("f2", "Declined Fund", status="Track (Declined)")]
        assert derive.declined_names(funds) == ["Declined Fund"]

    def test_a_bare_status_without_the_suffix_is_not_declined(self):
        assert derive.declined_names([fund("f1", "X", status="Declined")]) == []


class TestDeriveStats:
    def test_engagements_excludes_duplicate_surplus_templates_and_emails(self):
        notes = [
            note("a", "Call with Axiom Asia", thoughts="x"),
            note("b", "Meeting with Axiom Asia", body="y"),   # duplicate of a
            note("c", "REVA — annual review", note_type="LP Meeting", thoughts="z"),
            note("d", "Weekly pipeline review", note_type="Internal", thoughts="w"),
            note("e", "Fund admin", note_type="Email", thoughts="v"),
            note("f", "Note Template", thoughts=""),
        ]
        raw = {"window": {"start": "2026-08-03", "end": "2026-08-07"},
               "notes": notes, "funds": [], "contacts": []}
        stats = derive.derive_stats(raw)
        # 6 notes - 1 duplicate surplus - 1 template - 1 email = 3
        assert stats["engagements"] == 3
        assert stats["note_records"] == 6
        assert stats["duplicate_sets"] == 1
        assert stats["gp_meetings"] == 2   # both a and b are GP Meeting
        assert stats["lp_meetings"] == 1
        assert stats["internal_meetings"] == 1

    def test_declined_and_new_fund_records(self):
        raw = {"window": {"start": "2026-08-03", "end": "2026-08-07"}, "notes": [],
               "funds": [fund("f1", "New This Week", status="Track",
                              created="2026-08-05T00:00:00.000Z"),
                        fund("f2", "Old And Declined", status="Track (Declined)",
                              created="2025-01-01T00:00:00.000Z")],
               "contacts": []}
        stats = derive.derive_stats(raw)
        assert stats["declined"] == 1
        assert stats["new_fund_records"] == 1
        assert stats["funds_touched"] == 2

    def test_firms_represented_counts_distinct_employers(self):
        raw = {"window": {"start": "2026-08-03", "end": "2026-08-07"}, "notes": [],
               "funds": [],
               "contacts": [{"employer_ids": ["co1"]}, {"employer_ids": ["co1"]},
                            {"employer_ids": ["co2"]}]}
        assert derive.derive_stats(raw)["firms_represented"] == 2
        assert derive.derive_stats(raw)["new_contacts"] == 3


class TestWindowMaths:
    def test_prior_week_is_the_monday_to_friday_before_the_current_week(self):
        # 2026-08-05 is a Wednesday, so the current week is Aug 3-7 and the
        # prior (reported) week is the one before it, July 27-31.
        w = derive.prior_week(date(2026, 8, 5))
        assert w == {"start": "2026-07-27", "end": "2026-07-31"}

    def test_window_label_same_month(self):
        w = {"start": "2026-08-03", "end": "2026-08-07"}
        assert derive.window_label(w) == "3 – 7 August 2026"

    def test_window_label_spanning_months(self):
        w = {"start": "2026-07-27", "end": "2026-08-01"}
        assert derive.window_label(w) == "27 July – 1 August 2026"

    def test_iso_week_ref(self):
        w = {"start": "2026-08-03", "end": "2026-08-07"}
        assert derive.iso_week_ref(w) == "WB-WR-2026-W32"
