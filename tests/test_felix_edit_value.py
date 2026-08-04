"""A suggested value is a draft the reviewer can amend before approving.

Approve used to execute exactly what Felix planned, so a description that was
almost right had to be dismissed and fixed by hand in Notion.
"""
from api.main import _revalue_payload
from src.features.felix.run import _clip


class TestRevalue:
    def test_text_keeps_being_text(self):
        planned = {"properties": {"Description": {
            "rich_text": [{"text": {"content": "Felix's wording"}}]}}}
        out = _revalue_payload(planned, "mine", None)
        assert out["properties"]["Description"]["rich_text"][0]["text"]["content"] == "mine"

    def test_tags_keep_being_tags(self):
        planned = {"properties": {"Asset Class": {
            "multi_select": [{"name": "PE - Buyout"}]}}}
        out = _revalue_payload(planned, None, ["PE - Growth", "Venture"])
        assert out["properties"]["Asset Class"]["multi_select"] == [
            {"name": "PE - Growth"}, {"name": "Venture"}]

    def test_a_single_select_takes_one_name(self):
        planned = {"properties": {"Note Type": {"select": {"name": "Call"}}}}
        out = _revalue_payload(planned, "Meeting", None)
        assert out["properties"]["Note Type"]["select"]["name"] == "Meeting"

    def test_clearing_a_select_sends_null_not_an_empty_name(self):
        planned = {"properties": {"Note Type": {"select": {"name": "Call"}}}}
        assert _revalue_payload(planned, "", None)["properties"]["Note Type"] == {
            "select": None}

    def test_a_property_we_do_not_understand_is_left_alone(self):
        """Relations are not retypable — an edit must not mangle them."""
        planned = {"properties": {"Company": {"relation": [{"id": "abc"}]}}}
        assert _revalue_payload(planned, "something", None) == planned

    def test_no_edit_leaves_the_plan_untouched(self):
        planned = {"properties": {"Description": {
            "rich_text": [{"text": {"content": "as planned"}}]}}}
        assert _revalue_payload(planned, None, None) == planned


class TestClip:
    def test_short_evidence_is_untouched(self):
        assert _clip("a short quote", 900) == "a short quote"

    def test_a_long_quote_stops_at_a_word(self):
        """'This directly ti' was the old behaviour — cut mid-word."""
        out = _clip("word " * 400, 100)
        assert out.endswith("…")
        assert "wor…" not in out

    def test_trailing_punctuation_is_not_stranded_before_the_ellipsis(self):
        assert _clip("alpha beta, gamma delta", 12).endswith("…")
        assert ",…" not in _clip("alpha beta, gamma delta", 12)
