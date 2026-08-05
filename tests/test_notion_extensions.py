"""Connector extensions for the clean-up agent: strict queries, extended
writes, and the generic property normaliser."""
import pytest

from src.connectors import notion_client as nc


class TestPlainValue:
    def test_text_kinds(self):
        assert nc.plain_value({"type": "title", "title": [
            {"plain_text": "Fife "}, {"plain_text": "Capital"}]}) == ("title", "Fife Capital")
        assert nc.plain_value({"type": "rich_text", "rich_text": [
            {"text": {"content": "hi"}}]}) == ("rich_text", "hi")
        assert nc.plain_value({"type": "email", "email": "a@b.co"}) == ("email", "a@b.co")
        assert nc.plain_value({"type": "email", "email": None}) == ("email", "")

    def test_lists_are_order_insensitive(self):
        a = nc.plain_value({"type": "relation", "relation": [{"id": "b"}, {"id": "a"}]})
        b = nc.plain_value({"type": "relation", "relation": [{"id": "a"}, {"id": "b"}]})
        assert a == b == ("relation", ["a", "b"])
        assert nc.plain_value({"type": "multi_select", "multi_select": [
            {"name": "Z"}, {"name": "A"}]}) == ("multi_select", ["A", "Z"])

    def test_select_date_checkbox(self):
        assert nc.plain_value({"type": "select", "select": {"name": "GP"}}) == ("select", "GP")
        assert nc.plain_value({"type": "select", "select": None}) == ("select", "")
        assert nc.plain_value({"type": "date", "date": {"start": "2026-08-03", "end": None}}) \
            == ("date", "2026-08-03")
        assert nc.plain_value({"type": "checkbox", "checkbox": False}) == ("checkbox", False)

    def test_type_inferred_when_absent(self):
        assert nc.plain_value({"select": {"name": "GP"}}) == ("select", "GP")


class TestPageHelpers:
    PAGE = {"icon": {"type": "emoji", "emoji": "*"}, "properties": {
        "Employed By": {"type": "relation", "relation": [{"id": "co1"}], "has_more": False},
        "Deck": {"type": "files", "files": [
            {"name": "deck.pdf", "file": {"url": "https://s3/x"}},
            {"name": "site", "external": {"url": "https://a.co"}}]},
    }}

    def test_relation_and_files(self):
        assert nc.relation_ids(self.PAGE, "Employed By") == ["co1"]
        assert nc.relation_has_more(self.PAGE, "Employed By") is False
        assert nc.files_of(self.PAGE, "Deck") == [
            {"name": "deck.pdf", "url": "https://s3/x"},
            {"name": "site", "url": "https://a.co"}]
        assert nc.page_icon(self.PAGE) == {"type": "emoji", "emoji": "*"}


class TestMockModeWrites:
    def setup_method(self):
        self.n = nc.NotionConnector()
        assert not self.n.live   # tests run without NOTION_TOKEN

    def test_update_page_carries_icon_and_archived(self):
        out = self.n.update_page("p1", icon={"type": "emoji", "emoji": "*"}, archived=True)
        assert out["mock"] and out["archived"] is True

    def test_query_raw_and_blocks_are_safe(self):
        assert self.n.query_database_raw("db") == []
        assert self.n.get_page("p1")["id"] == "p1"
        assert self.n.retrieve_database("db") == {}
        assert self.n.append_blocks("p1", [{}])["mock"]
        assert self.n.set_block_archived("b1", True)["archived"] is True


class TestStrictQuery:
    def test_partial_result_carries_rows(self):
        e = nc.NotionPartialResult("db1", [{"id": "a"}])
        assert e.db_id == "db1" and len(e.rows) == 1
        assert "only 1 rows" in str(e)


class TestInvalidateCache:
    """The snapshot is 27,000 rows across three databases and takes minutes to
    rebuild. Invalidation drops the in-memory copy — enough for the next delta
    sync to pick up edits — and keeps the snapshot itself."""

    def _conn(self, tmp_path, monkeypatch, records=None):
        n = nc.NotionConnector()
        monkeypatch.setattr(nc.NotionConnector, "_DISK_PATH", tmp_path / "cache.json")
        n._disk_save({"contacts": {"records": records or [{"id": "a"}, {"id": "b"}]},
                      "funds": {"records": []}, "page_text": {}})
        n._list_cache["contacts"] = (0, [])
        return n

    def test_the_memory_cache_is_dropped(self, tmp_path, monkeypatch):
        n = self._conn(tmp_path, monkeypatch)
        n.invalidate_cache(["contacts"])
        assert "contacts" not in n._list_cache

    def test_the_snapshot_survives(self, tmp_path, monkeypatch):
        """Deleting it forced a full workspace re-pull, which stalled triage
        and meeting prep for minutes after every applied change."""
        n = self._conn(tmp_path, monkeypatch)
        n.invalidate_cache(["contacts"])
        store = n._disk_load()
        assert [r["id"] for r in store["contacts"]["records"]] == ["a", "b"]

    def test_an_archived_id_is_removed_from_the_snapshot(self, tmp_path, monkeypatch):
        """The one thing a delta sync cannot see."""
        n = self._conn(tmp_path, monkeypatch)
        n.invalidate_cache(archived_ids=["a"])
        store = n._disk_load()
        assert [r["id"] for r in store["contacts"]["records"]] == ["b"]

    def test_an_unknown_archived_id_changes_nothing(self, tmp_path, monkeypatch):
        n = self._conn(tmp_path, monkeypatch)
        n.invalidate_cache(archived_ids=["zz", None, ""])
        assert len(n._disk_load()["contacts"]["records"]) == 2

    def test_other_collections_are_untouched(self, tmp_path, monkeypatch):
        n = self._conn(tmp_path, monkeypatch)
        n.invalidate_cache(["contacts"], archived_ids=["a"])
        assert "funds" in n._disk_load() and "page_text" in n._disk_load()


class TestDiskCacheInMemoryMirror:
    """_disk_load used to re-read and re-parse the whole (multi-MB in the
    live workspace) cache file on every call, including hits — get_page_text
    alone calls it once per lookup, dozens of times in a single Felix run."""

    def _conn(self, tmp_path, monkeypatch):
        n = nc.NotionConnector()
        monkeypatch.setattr(nc.NotionConnector, "_DISK_PATH", tmp_path / "cache.json")
        return n

    def test_the_file_is_read_from_disk_only_once(self, tmp_path, monkeypatch):
        n = self._conn(tmp_path, monkeypatch)
        n._disk_save({"contacts": {"records": [{"id": "a"}]}})
        calls = []
        real_read_text = type(n._DISK_PATH).read_text

        def spy_read_text(self, *a, **k):
            calls.append(1)
            return real_read_text(self, *a, **k)

        monkeypatch.setattr(type(n._DISK_PATH), "read_text", spy_read_text)
        for _ in range(5):
            n._disk_load()
        assert calls == []   # already in memory from the _disk_save above — never re-read

    def test_a_fresh_connector_still_reads_disk_once_then_caches(self, tmp_path, monkeypatch):
        path = tmp_path / "cache.json"
        monkeypatch.setattr(nc.NotionConnector, "_DISK_PATH", path)
        n1 = nc.NotionConnector()
        n1._disk_save({"contacts": {"records": [{"id": "a"}]}})

        n2 = nc.NotionConnector()   # simulates a new process/instance
        calls = []
        real_read_text = type(path).read_text

        def spy_read_text(self, *a, **k):
            calls.append(1)
            return real_read_text(self, *a, **k)

        monkeypatch.setattr(type(path), "read_text", spy_read_text)
        n2._disk_load()
        n2._disk_load()
        n2._disk_load()
        assert len(calls) == 1   # the first load reads disk, the rest hit memory

    def test_a_save_updates_the_in_memory_mirror_without_a_disk_read(self, tmp_path, monkeypatch):
        n = self._conn(tmp_path, monkeypatch)
        n._disk_load()   # establishes the (empty) in-memory mirror
        n._disk_save({"contacts": {"records": [{"id": "new"}]}})
        assert n._disk_load()["contacts"]["records"] == [{"id": "new"}]

    def test_get_page_text_does_not_reread_disk_on_a_cache_hit(self, tmp_path, monkeypatch):
        n = self._conn(tmp_path, monkeypatch)
        n.live = True
        n._disk_save({"page_text": {"p1": {"text": "hello", "at": 9999999999}}})
        calls = []
        real_read_text = type(n._DISK_PATH).read_text

        def spy_read_text(self, *a, **k):
            calls.append(1)
            return real_read_text(self, *a, **k)

        monkeypatch.setattr(type(n._DISK_PATH), "read_text", spy_read_text)
        assert n.get_page_text("p1") == "hello"
        assert n.get_page_text("p1") == "hello"
        assert calls == []


def test_a_collection_is_loaded_once_under_concurrent_readers(tmp_path, monkeypatch):
    """Two requests arriving together must not each start a minutes-long pull."""
    import threading

    n = nc.NotionConnector()
    monkeypatch.setattr(nc.NotionConnector, "_DISK_PATH", tmp_path / "cache.json")
    calls = []
    start = threading.Event()

    def loader():
        calls.append(1)
        start.wait(timeout=2)
        return ["row"]

    threads = [threading.Thread(target=lambda: n._cached("contacts", loader))
               for _ in range(4)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join(timeout=5)
    assert len(calls) == 1


class TestContactEmployerResolution:
    """ContactRecord.company used to always be "" — the Employed By relation
    was read (elsewhere) but never resolved to the employer's actual name,
    so meeting prep and dedupe's cross-corroboration could never match a
    contact to their employer except by a literal name match."""

    PAGE = {"properties": {
        "Name": {"type": "title", "title": [{"plain_text": "Lisa Wong"}]},
        "Email": {"type": "email", "email": "lisa@biotrack.com"},
        "Employed By": {"type": "relation", "relation": [{"id": "co1"}]},
    }}

    def test_the_employer_relation_resolves_to_a_name(self):
        contact = nc._contact_from_page(self.PAGE, {"co1": "BioTrack Capital"})
        assert contact.company == "BioTrack Capital"

    def test_an_unresolvable_relation_id_leaves_company_blank(self):
        """The linked company wasn't in the lookup (e.g. archived) — better
        blank than a raw, meaningless page id."""
        contact = nc._contact_from_page(self.PAGE, {})
        assert contact.company == ""

    def test_no_employer_relation_at_all_is_a_plain_empty_company(self):
        page = {"properties": {"Name": {"type": "title",
                                        "title": [{"plain_text": "No Employer"}]}}}
        contact = nc._contact_from_page(page, {"co1": "BioTrack Capital"})
        assert contact.company == ""

    def test_multiple_employers_join_by_name(self):
        page = {"properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Dual Hat"}]},
            "Employed By": {"type": "relation",
                           "relation": [{"id": "co1"}, {"id": "co2"}]},
        }}
        contact = nc._contact_from_page(
            page, {"co1": "BioTrack Capital", "co2": "Other Fund"})
        assert contact.company == "BioTrack Capital; Other Fund"


class TestNoteFromPage:
    PAGE = {"properties": {
        "Name": {"type": "title", "title": [{"plain_text": "Call with BioTrack"}]},
        "Note Type": {"type": "select", "select": {"name": "GP Meeting"}},
        "Date": {"type": "date", "date": {"start": "2026-07-01", "end": None}},
        "Thoughts / Considerations": {"type": "rich_text", "rich_text": [
            {"plain_text": "Discussed Fund II close."}]},
        "Attendees": {"type": "relation", "relation": [{"id": "c1"}]},
        "\U0001f3e2 Companies": {"type": "relation", "relation": [{"id": "co1"}]},
        "Fund": {"type": "relation", "relation": [{"id": "f1"}]},
    }, "last_edited_time": "2026-07-02T00:00:00.000Z"}

    def test_fields_and_relations_are_read(self):
        note = nc._note_from_page(self.PAGE)
        assert note.name == "Call with BioTrack"
        assert note.note_type == "GP Meeting"
        assert note.date == "2026-07-01"
        assert note.excerpt == "Discussed Fund II close."
        assert note.attendee_ids == ["c1"]
        assert note.company_ids == ["co1"]
        assert note.fund_ids == ["f1"]

    def test_an_undated_note_falls_back_to_last_edited_time(self):
        page = {"properties": {"Name": {"type": "title", "title": [{"plain_text": "x"}]}},
                "last_edited_time": "2026-07-02T00:00:00.000Z"}
        note = nc._note_from_page(page)
        assert note.date == "2026-07-02"


class TestPageTitle:
    def test_a_page_titles_by_its_title_property_whatever_its_called(self):
        page = {"object": "page", "properties": {
            "Fund Name": {"type": "title",
                         "title": [{"plain_text": "BioTrack USD Fund II"}]}}}
        assert nc.page_title(page) == "BioTrack USD Fund II"

    def test_a_database_titles_from_its_own_title_field(self):
        db = {"object": "database", "title": [{"plain_text": "Deal Memos"}]}
        assert nc.page_title(db) == "Deal Memos"

    def test_no_title_property_is_a_blank_string(self):
        assert nc.page_title({"properties": {}}) == ""


class TestNotesCollectionMockMode:
    def test_mock_mode_serves_sample_notes(self):
        n = nc.NotionConnector()
        notes = n.list_notes()
        assert notes and all(isinstance(r, nc.NoteRecord) for r in notes)


class TestSearchGuards:
    """search() is a supplementary call layered onto meeting prep — it must
    never attempt a live request outside live mode or with nothing to ask."""

    def test_mock_mode_returns_nothing(self):
        n = nc.NotionConnector()
        assert n.search("BioTrack") == []

    def test_a_blank_query_returns_nothing_even_if_live(self):
        n = nc.NotionConnector()
        n.live = True
        assert n.search("   ") == []
