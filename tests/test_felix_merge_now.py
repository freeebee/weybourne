"""Approve-time merges: approving a duplicate finding executes the
consolidation on the spot — richer record kept, data transferred, loser
archived — and settles the pair for good."""
import json

from src.features.felix import store
from src.features.felix.run import merge_pair_now


def _page(pid, name, created, extra=None, archived=False):
    props = {"Name": {"type": "title", "title": [{"plain_text": name}]}}
    props.update(extra or {})
    return {"id": pid, "url": f"https://notion.so/{pid}", "icon": None,
            "archived": archived, "created_time": created,
            "last_edited_time": created, "properties": props}


class FakeNotion:
    live = True

    def __init__(self, pages):
        self.pages = {p["id"]: p for p in pages}
        self.updates = []

    def get_page(self, pid):
        return self.pages[pid]

    def retrieve_database(self, db_id):
        return {"properties": {}}

    def query_database_raw(self, db_id, **kwargs):
        return []

    def update_page(self, pid, properties=None, icon=None, archived=None):
        self.updates.append({"id": pid, "properties": properties,
                             "archived": archived})
        page = self.pages[pid]
        if archived is not None:
            page["archived"] = archived
        for k, v in (properties or {}).items():
            page["properties"][k] = {**v, "type": next(iter(v))}

    def append_blocks(self, block_id, children):
        return {"results": [{"id": "blk-pointer"}]}


def test_merge_pair_now_keeps_richer_archives_other(tmp_path):
    rich = _page("pa", "Laure Goupil", "2023-01-01T00:00:00Z", extra={
        "Email": {"type": "email", "email": "lgoupil@axeleo.com"},
        "Weybourne Comments": {"type": "rich_text",
                               "rich_text": [{"plain_text": "IR at Axeleo"}]},
    })
    poor = _page("pb", "Laure Goupi", "2024-06-01T00:00:00Z", extra={
        "Phone": {"type": "phone_number", "phone_number": "+33 1 23 45 67 89"},
    })
    notion = FakeNotion([rich, poor])

    out = merge_pair_now(notion, ["pb", "pa"], "contacts",
                         source="test", reason="confirmed duplicate",
                         base=tmp_path)

    assert out["status"] == "Applied"
    assert out["survivor"] == "Laure Goupil"
    assert out["loser"] == "Laure Goupi"
    # The poorer copy is archived; its phone number moved to the survivor.
    assert notion.pages["pb"]["archived"] is True
    assert notion.pages["pa"]["properties"]["Phone"]["phone_number"] \
        == "+33 1 23 45 67 89"
    # The merge is logged with the side-by-side detail, and the pair is
    # settled so no future run re-flags it.
    merge = store.list_all_changes(base=tmp_path, change_type="merge")[0]
    d = json.loads(merge.detail)
    assert d["keep"]["name"] == "Laure Goupil"
    assert d["archive"]["name"] == "Laure Goupi"
    assert store.pair_key("pa", "pb") in store.load_resolved_pairs(tmp_path)


def test_merge_pair_now_skips_an_already_archived_pair(tmp_path):
    a = _page("pa", "Nick Massey", "2023-01-01T00:00:00Z")
    b = _page("pb", "Nick Mansey", "2024-01-01T00:00:00Z", archived=True)
    out = merge_pair_now(FakeNotion([a, b]), ["pa", "pb"], "contacts",
                         source="test", reason="dup", base=tmp_path)
    assert out["status"] == "Skipped"
    assert "already archived" in out["note"]


def test_merge_pair_now_honours_a_recorded_survivor(tmp_path):
    # A planned merge already chose its survivor — approve must not re-decide,
    # even when the recorded survivor is the poorer record.
    rich = _page("pa", "Rich Copy", "2023-01-01T00:00:00Z", extra={
        "Email": {"type": "email", "email": "rich@x.com"},
    })
    poor = _page("pb", "Poor Copy", "2024-01-01T00:00:00Z")
    notion = FakeNotion([rich, poor])
    out = merge_pair_now(notion, ["pb", "pa"], "contacts",
                         source="test", reason="dup", survivor_id="pb",
                         base=tmp_path)
    assert out["status"] == "Applied"
    assert out["survivor"] == "Poor Copy"
    assert notion.pages["pa"]["archived"] is True
