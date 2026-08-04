"""Approving a company creation re-checks for duplicates first.

The scan that proposed it may be old, and the whole point of Felix is not to
leave a second copy of a company behind.
"""
from src.features.felix.models import ChangeRecord
from src.features.felix.run import add_photo_to_page, create_company_and_link


class FakeNotion:
    live = True

    def __init__(self, companies=()):
        self.companies = list(companies)
        self.created = []
        self.updates = []
        self.blocks = []
        self.fail_blocks = False

    def query_database_raw(self, db_id, **kw):
        return self.companies

    def create_page(self, db_id, properties, children=None, icon=None):
        name = properties["Name"]["title"][0]["text"]["content"]
        self.created.append(name)
        return {"id": f"new-{len(self.created)}", "url": "https://notion.so/x"}

    def update_page(self, pid, properties=None, icon=None, archived=None):
        self.updates.append({"id": pid, "properties": properties})

    def append_blocks(self, block_id, children):
        if self.fail_blocks:
            raise RuntimeError("image rejected")
        self.blocks.append({"id": block_id, "children": children})
        return {"results": [{"id": "b1"}]}


def _company_page(pid, name):
    return {"id": pid, "url": "", "icon": None, "archived": False,
            "created_time": "", "last_edited_time": "",
            "properties": {"Name": {"type": "title",
                                    "title": [{"plain_text": name}]}}}


def _change():
    return ChangeRecord(change_id="FLX-1", run_id="r", timestamp="",
                        database="contacts", record_name="Laure Goupil",
                        record_id="p1", record_url="",
                        change_type="create_company",
                        property_changed="Employed By")


SNAP = {"kind": "create_company", "record_id": "p1", "database": "contacts",
        "company_name": "Axeleo Capital", "link_property": "Employed By",
        "existing_ids": []}


def test_creates_and_links_when_genuinely_new(tmp_path):
    n = FakeNotion([])
    out = create_company_and_link(n, SNAP, _change(), base=tmp_path, db_id="companies-db")
    assert out["status"] == "Applied" and out["created"] is True
    assert n.created == ["Axeleo Capital"]
    assert n.updates[0]["properties"]["Employed By"]["relation"][0]["id"] \
        == "new-1"


def test_links_the_existing_company_instead_of_creating_a_twin(tmp_path):
    n = FakeNotion([_company_page("c1", "Axeleo Capital")])
    out = create_company_and_link(n, SNAP, _change(), base=tmp_path, db_id="companies-db")
    assert out["status"] == "Applied" and out["created"] is False
    assert n.created == []
    assert n.updates[0]["properties"]["Employed By"]["relation"][0]["id"] == "c1"


def test_a_near_name_stops_rather_than_risking_a_duplicate(tmp_path):
    n = FakeNotion([_company_page("c1", "Axeleo Capital Partners SAS")])
    out = create_company_and_link(n, SNAP, _change(), base=tmp_path, db_id="companies-db")
    assert out["status"] == "Skipped"
    assert n.created == [] and n.updates == []


def test_existing_relations_are_preserved(tmp_path):
    n = FakeNotion([])
    snap = {**SNAP, "existing_ids": ["keepme"]}
    create_company_and_link(n, snap, _change(), base=tmp_path, db_id="companies-db")
    ids = [r["id"] for r in n.updates[0]["properties"]["Employed By"]["relation"]]
    assert ids == ["keepme", "new-1"]


def test_photo_failure_is_reported_not_swallowed(tmp_path):
    n = FakeNotion()
    n.fail_blocks = True
    out = add_photo_to_page(n, {"record_id": "p1",
                                "photo_url": "https://x/p.jpg"},
                            _change(), base=tmp_path)
    assert out["status"] == "Failed"
    assert "image" in out["note"]


def test_photo_is_added_with_the_profile_link(tmp_path):
    n = FakeNotion()
    out = add_photo_to_page(
        n, {"record_id": "p1", "photo_url": "https://x/p.jpg",
            "profile_url": "https://linkedin.com/in/x"},
        _change(), base=tmp_path)
    assert out["status"] == "Applied"
    kinds = [b["type"] for b in n.blocks[0]["children"]]
    assert kinds == ["image", "paragraph"]
