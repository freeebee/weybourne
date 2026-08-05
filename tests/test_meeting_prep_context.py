"""gather_notion_context — matching a company/counterparty to Notion records,
and, crucially, to the meeting notes that reference them.

Before this fix the function only ever read Contacts/Companies/Funds: a
company linked to real meeting history (via its own notes, a linked fund, or
a linked contact) but not literally named in a note's title would report as
having no prior record at all — a false "no admissible internal record" for
a counterparty met a dozen times.
"""
from src.features.meeting_prep import gather_notion_context
from src.schemas import CompanyRecord, ContactRecord, FundRecord, NoteRecord


class FakeNotion:
    def __init__(self, contacts=None, companies=None, funds=None, notes=None,
                search_results=None):
        self._contacts = contacts or []
        self._companies = companies or []
        self._funds = funds or []
        self._notes = notes or []
        self._search_results = search_results or []

    def list_contacts(self):
        return self._contacts

    def list_companies(self):
        return self._companies

    def list_funds(self):
        return self._funds

    def list_notes(self):
        return self._notes

    def search(self, query, page_size=10):
        return self._search_results


class TestNotesSurfaceByRelation:
    def test_a_note_linked_to_the_matched_company_is_included(self):
        notion = FakeNotion(
            companies=[CompanyRecord(id="co1", name="BioTrack Capital")],
            notes=[NoteRecord(id="n1", name="Call with BioTrack", date="2026-07-01",
                              excerpt="Discussed Fund II close.", company_ids=["co1"])])
        text, sources = gather_notion_context(notion, "BioTrack Capital", "")
        assert "Discussed Fund II close." in text
        assert any("Notion Notes" in s for s in sources)

    def test_a_note_linked_via_the_fund_is_included(self):
        notion = FakeNotion(
            funds=[FundRecord(id="f1", name="BioTrack USD Fund II",
                              company="BioTrack Capital")],
            notes=[NoteRecord(id="n1", name="Quarterly update", date="2026-06-01",
                              excerpt="NAV update.", fund_ids=["f1"])])
        text, _ = gather_notion_context(notion, "", "BioTrack Capital")
        assert "NAV update." in text

    def test_a_note_linked_via_an_attendee_is_included(self):
        """This is the "we've met Lisa" case: her employer relation resolves
        her to the company, and her attendance links the note in turn."""
        notion = FakeNotion(
            contacts=[ContactRecord(id="c1", name="Lisa Wong",
                                    company="BioTrack Capital")],
            notes=[NoteRecord(id="n1", name="Coffee with Lisa", date="2026-05-01",
                              excerpt="Caught up on the fund raise.",
                              attendee_ids=["c1"])])
        text, _ = gather_notion_context(notion, "BioTrack Capital", "")
        assert "Caught up on the fund raise." in text

    def test_a_note_matched_only_by_its_own_title_is_still_included(self):
        """Not every note has its relations filled in — the text fallback
        catches those instead of silently dropping them."""
        notion = FakeNotion(
            notes=[NoteRecord(id="n1", name="Call with BioTrack Capital",
                              date="2026-04-01", excerpt="Intro call.")])
        text, _ = gather_notion_context(notion, "BioTrack Capital", "")
        assert "Intro call." in text

    def test_an_unrelated_note_is_excluded(self):
        notion = FakeNotion(
            notes=[NoteRecord(id="n1", name="Call with Acme Capital",
                              date="2026-04-01", excerpt="Nothing related here.")])
        text, _ = gather_notion_context(notion, "BioTrack Capital", "")
        assert "Acme" not in text

    def test_notes_are_capped_and_the_overflow_is_noted(self):
        notes = [NoteRecord(id=f"n{i}", name="Call with BioTrack",
                            date=f"2026-01-{i:02d}", excerpt=f"note {i}",
                            company_ids=["co1"]) for i in range(1, 15)]
        notion = FakeNotion(companies=[CompanyRecord(id="co1", name="BioTrack Capital")],
                            notes=notes)
        text, sources = gather_notion_context(notion, "BioTrack Capital", "")
        assert text.count("Meeting note") == 12
        assert any("older matching note" in s for s in sources)

    def test_no_records_at_all_reports_plainly(self):
        text, sources = gather_notion_context(FakeNotion(), "Nobody Capital", "")
        assert text == "(no matching records found in Notion)"
        assert sources == []


class TestSupplementarySearch:
    def test_a_matching_search_hit_outside_the_curated_dbs_is_included(self):
        hit = {"id": "p1", "url": "https://notion.so/p1", "properties": {
            "Name": {"type": "title",
                    "title": [{"plain_text": "BioTrack Capital — deal memo"}]}}}
        notion = FakeNotion(search_results=[hit])
        text, sources = gather_notion_context(notion, "BioTrack Capital", "")
        assert "deal memo" in text
        assert any("Notion search" in s for s in sources)

    def test_a_hit_already_surfaced_via_a_matched_record_is_not_duplicated(self):
        hit = {"id": "co1", "properties": {"Name": {
            "type": "title", "title": [{"plain_text": "BioTrack Capital"}]}}}
        notion = FakeNotion(companies=[CompanyRecord(id="co1", name="BioTrack Capital")],
                            search_results=[hit])
        text, _ = gather_notion_context(notion, "BioTrack Capital", "")
        assert text.count("BioTrack Capital") == 1

    def test_an_irrelevant_search_hit_is_dropped(self):
        hit = {"id": "p2", "properties": {"Name": {
            "type": "title", "title": [{"plain_text": "Unrelated wiki page"}]}}}
        notion = FakeNotion(search_results=[hit])
        text, _ = gather_notion_context(notion, "BioTrack Capital", "")
        assert "Unrelated" not in text
