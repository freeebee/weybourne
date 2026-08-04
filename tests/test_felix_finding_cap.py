"""A run stops once enough findings are waiting on the user.

Felix used to work through the whole workspace in one go and dump everything
into the review queue at once. Ten at a time is a session's worth; clearing
them is what starts the next run.

Only rows that need a decision count — proposals and recommendations. The
deterministic High-confidence fixes are applied and reversible, so they never
sit in the queue and never bring the run to a halt.
"""
import pytest

from src.connectors.notion_client import NotionConnector
from src.features.felix import run as runmod
from src.features.felix import store
from src.features.felix.models import RunOptions
from src.features.felix.run import felix_run


def run_felix(base, **opt):
    j = {"stages": [], "partial": {}}
    return j, felix_run(j, NotionConnector(), None, RunOptions(**opt), base=base)


class TestDefaults:
    def test_ten_findings_by_default(self):
        assert RunOptions().max_findings == 10

    def test_runs_are_live_by_default(self):
        """The dry-run mode and the switch that enabled it are gone."""
        assert RunOptions().dry_run is False


class TestStopIsNotAFailure:
    """Hitting the cap unwinds the run from wherever it had got to. The
    summary is carried out with the exception so the caller sees a completed
    run, not a crash."""

    def test_the_carried_summary_is_returned(self, monkeypatch):
        summary = {"run_id": "r1", "status": "done", "stopped_at_cap": 10}
        monkeypatch.setattr(runmod, "_felix_run",
                            lambda *a, **k: (_ for _ in ()).throw(
                                runmod._FindingsFull(summary)))
        assert felix_run({}, None, None, RunOptions()) == summary

    def test_other_failures_still_surface(self, monkeypatch):
        monkeypatch.setattr(runmod, "_felix_run",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("notion is down")))
        with pytest.raises(RuntimeError):
            felix_run({}, None, None, RunOptions())


class TestUncappedRun:
    def test_a_run_that_never_reaches_the_cap_completes(self, tmp_path):
        _j, out = run_felix(tmp_path, max_findings=10)
        assert out["status"] == "done" and out["stopped_at_cap"] == 0

    def test_applied_fixes_do_not_count_towards_the_cap(self, tmp_path):
        """The mock workspace's issues are all High-confidence mechanical
        fixes. A cap of one must not cut the run short over them."""
        _j, out = run_felix(tmp_path, max_findings=1)
        assert out["status"] == "done" and out["stopped_at_cap"] == 0
        applied = [c for c in store.list_all_changes(base=tmp_path, limit=500)
                   if c.execution_status == "Applied"]
        assert len(applied) > 1

    def test_zero_disables_the_cap(self, tmp_path):
        _j, out = run_felix(tmp_path, max_findings=0)
        assert out["status"] == "done" and out["stopped_at_cap"] == 0
