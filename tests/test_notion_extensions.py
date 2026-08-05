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
