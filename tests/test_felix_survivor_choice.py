"""The reviewer picks which copy of a duplicate survives, overriding Felix's
richer-copy default; the side-by-side carries the ids that choice needs."""
import json

from src.features.felix import store
from src.features.felix.run import merge_pair_now
from tests.test_felix_merge_now import FakeNotion, _page


def test_reviewer_choice_overrides_the_richer_copy(tmp_path):
    rich = _page("pa", "Laure Goupil", "2023-01-01T00:00:00Z", extra={
        "Email": {"type": "email", "email": "lgoupil@axeleo.com"}})
    poor = _page("pb", "Laure Goupi", "2024-01-01T00:00:00Z")
    notion = FakeNotion([rich, poor])

    # Felix would keep 'pa'; the reviewer chose 'pb'.
    out = merge_pair_now(notion, ["pa", "pb"], "contacts", source="review",
                         reason="duplicate", survivor_id="pb", base=tmp_path)

    assert out["status"] == "Applied"
    assert out["survivor"] == "Laure Goupi"
    assert notion.pages["pa"]["archived"] is True
    assert notion.pages["pb"]["archived"] is False


def test_side_by_side_carries_record_ids(tmp_path):
    """The UI maps a click to a record id, so each side must carry one."""
    a = _page("pa", "Rich", "2023-01-01T00:00:00Z", extra={
        "Email": {"type": "email", "email": "r@x.com"}})
    b = _page("pb", "Poor", "2024-01-01T00:00:00Z")
    merge_pair_now(FakeNotion([a, b]), ["pa", "pb"], "contacts",
                   source="s", reason="r", base=tmp_path)
    merge = store.list_all_changes(base=tmp_path, change_type="merge")[0]
    d = json.loads(merge.detail)
    assert d["keep"]["id"] == "pa"
    assert d["archive"]["id"] == "pb"
    assert d["pair"] == ["pa", "pb"]
