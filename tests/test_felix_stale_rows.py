"""A finding re-detected on a later run replaces the older row.

Evidence kept appearing cut off at 323 characters long after the truncation
limit was raised. The rows were not being regenerated: two runs had died
before finishing, and even a run that completes used to append its findings
alongside the originals, so the queue went on showing the FIRST wording for
ever — including text written under the old, shorter limit.
"""
import pytest

from src.features.felix import store
from src.features.felix.models import ChangeRecord, RunRecord


@pytest.fixture
def base(tmp_path):
    return tmp_path


def _change(cid, run_id, **kw):
    return ChangeRecord(**{
        "change_id": cid, "run_id": run_id, "timestamp": "2026-08-04T23:45:00",
        "database": "contacts", "record_id": "rec1",
        "record_name": "Michael Calabrese", "change_type": "fill_missing",
        "property_changed": "Description", "execution_status": "Proposed",
        "review_status": "Awaiting Review", **kw})


class TestInterruptedRuns:
    def test_a_run_still_flagged_running_at_startup_was_interrupted(self, base):
        store.save_run(RunRecord(run_id="r1", started="2026-08-05T00:27:17",
                                 status="running"), base)
        assert store.mark_interrupted_runs(base) == ["r1"]
        assert store.load_run("r1", base).status == "interrupted"
        assert "restarted" in store.load_run("r1", base).error

    def test_a_finished_run_is_left_alone(self, base):
        store.save_run(RunRecord(run_id="r2", started="x", status="completed",
                                 finished="y"), base)
        assert store.mark_interrupted_runs(base) == []
        assert store.load_run("r2", base).status == "completed"

    def test_the_sweep_is_safe_with_no_runs_at_all(self, base):
        assert store.mark_interrupted_runs(base) == []


class TestSupersede:
    """The rule the run applies: same record, same field, same kind of change,
    from an earlier run, still awaiting — the newer row wins."""

    def _older(self, c, run_id):
        return (c.run_id != run_id and c.record_id == "rec1"
                and c.property_changed == "Description"
                and c.change_type == "fill_missing"
                and c.execution_status != "Applied"
                and c.review_status == "Awaiting Review")

    def test_an_earlier_awaiting_row_is_superseded(self, base):
        store.append_change(_change("old", "run1", source="x" * 323), base)
        store.append_change(_change("new", "run2", source="x" * 900), base)
        for c in store.list_all_changes(base=base, limit=50):
            if self._older(c, "run2"):
                store.update_change(c.change_id, {"review_status": "Superseded"}, base)
        rows = {c.change_id: c.review_status
                for c in store.list_all_changes(base=base, limit=50)}
        assert rows["old"] == "Superseded"
        assert rows["new"] == "Awaiting Review"

    def test_an_applied_row_is_never_superseded(self, base):
        """It is a record of something written to Notion, and undo needs it."""
        store.append_change(
            _change("applied", "run1", execution_status="Applied"), base)
        c = store.list_all_changes(base=base, limit=50)[0]
        assert not self._older(c, "run2")

    def test_a_different_field_on_the_same_record_survives(self, base):
        store.append_change(_change("title", "run1", property_changed="Title"), base)
        c = store.find_change("title", base)
        assert not self._older(c, "run2")

    def test_the_run_does_not_supersede_its_own_rows(self, base):
        store.append_change(_change("mine", "run2"), base)
        c = store.find_change("mine", base)
        assert not self._older(c, "run2")
