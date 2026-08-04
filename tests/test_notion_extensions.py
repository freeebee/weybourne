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
