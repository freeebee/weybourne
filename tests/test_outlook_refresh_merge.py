"""The outlook-refresh writer never writes the same message twice.

The snapshot rows come from a CLI agent, and agents repeat themselves: the
same message returned by two searches, or a cached-id stub emitted twice.
Each repeated stub used to be spliced with the SAME stored row and written
through — one email then showed up twice in triage (17 Aug 2026,
byte-identical adjacent rows in inbox_snapshot.json).
"""
from api.main import _merge_cached_rows


FULL = {"id": "A", "subject": "RE: SecondQuarter Fund 3", "body": "long body",
        "sender_email": "ian@secondquarter.vc"}
STUB = {"id": "A"}                       # bare-id marker: "use your cached copy"
OTHER = {"id": "B", "subject": "other", "body": "text"}


class TestDedupe:
    def test_a_repeated_cached_stub_is_spliced_once(self):
        """The exact 17 Aug failure: two stubs for one id, one stored row."""
        merged, reused, dropped = _merge_cached_rows([STUB, dict(STUB)], {"A": FULL})
        assert merged == [FULL]
        assert reused == 1
        assert dropped == 1

    def test_a_repeated_full_row_is_written_once(self):
        merged, _reused, dropped = _merge_cached_rows([FULL, dict(FULL), OTHER], {})
        assert [r["id"] for r in merged] == ["A", "B"]
        assert dropped == 1

    def test_a_full_row_followed_by_its_own_stub_keeps_the_full_row(self):
        merged, reused, _ = _merge_cached_rows([FULL, STUB], {"A": FULL})
        assert merged == [FULL]
        assert reused == 0               # the full row came first; no splice needed

    def test_distinct_messages_all_survive(self):
        merged, _, _ = _merge_cached_rows([FULL, OTHER], {})
        assert len(merged) == 2


class TestExistingContract:
    """The behaviours the function already had, still intact."""

    def test_a_stub_with_no_stored_body_is_dropped_not_written(self):
        merged, reused, dropped = _merge_cached_rows([STUB], {})
        assert merged == [] and reused == 0 and dropped == 1

    def test_a_cached_stub_is_spliced_from_the_store(self):
        merged, reused, _ = _merge_cached_rows([STUB], {"A": FULL})
        assert merged == [FULL] and reused == 1

    def test_non_dict_rows_are_ignored(self):
        merged, _, _ = _merge_cached_rows(["junk", None, FULL], {})
        assert merged == [FULL]
