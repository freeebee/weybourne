"""A run stops once enough COMPLEX findings are waiting on the user.

Felix used to work through the whole workspace in one go and dump everything
into the review queue at once. Ten at a time is a session's worth; clearing
them is what starts the next run.

Only judgement calls count — a fill, a merge (however confident), a
recommendation. A formatting/icon/relation fix needs no judgement at all
(EASY_CHANGE_TYPES), so it never sits against the cap and never brings the
run to a halt, however low the cap is set. Nothing in either category is
ever applied without a click — the cap governs when a run stops FILING
change-log rows, not whether it writes to Notion.
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

    def test_easy_fixes_do_not_count_towards_the_cap(self, tmp_path):
        """The mock workspace's formatting/relation fixes need no judgement
        call. A cap of one must not cut them short — they are filed (never
        applied without a click) regardless of the cap."""
        _j, out = run_felix(tmp_path, max_findings=1)
        changes = store.list_all_changes(base=tmp_path, limit=500)
        easy = [c for c in changes if c.change_type in runmod.EASY_CHANGE_TYPES]
        assert len(easy) > 1
        assert all(c.execution_status == "Planned (dry-run)" for c in easy)

    def test_a_fill_or_merge_does_count_towards_the_cap(self, tmp_path):
        """Unlike a formatting fix, filling in a property or merging two
        records is a judgement call — even one of them is enough to stop a
        run capped at one, exactly as an ambiguous duplicate would."""
        _j, out = run_felix(tmp_path, max_findings=1)
        assert out["stopped_at_cap"] >= 1
        changes = store.list_all_changes(base=tmp_path, limit=500)
        complex_rows = [c for c in changes
                       if c.change_type not in runmod.EASY_CHANGE_TYPES]
        assert len(complex_rows) == 1

    def test_zero_disables_the_cap(self, tmp_path):
        _j, out = run_felix(tmp_path, max_findings=0)
        assert out["status"] == "done" and out["stopped_at_cap"] == 0
