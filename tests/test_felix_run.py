"""End-to-end pipeline in mock mode: the full dry run, live-mode execution
against the mock connector, and the undo engine's conflict discipline."""
from src.connectors.notion_client import NotionConnector
from src.features.felix import store, undo
from src.features.felix.models import RunOptions
from src.features.felix.run import felix_run


def job():
    return {"stages": [], "partial": {}}


def run_felix(base, dry=True, client=None, **opt):
    j = job()
    out = felix_run(j, NotionConnector(), client,
                    RunOptions(dry_run=dry, **opt), base=base)
    return j, out


class TestDryRun:
    def test_full_dry_run_plans_without_writing(self, tmp_path):
        j, out = run_felix(tmp_path, dry=True)
        assert out["status"] == "done" and out["dry_run"]
        c = out["counts"]
        assert c["planned"] > 0 and c["applied"] == 0
        # The mock workspace's deliberate issues are all found:
        changes = store.list_all_changes(base=tmp_path, limit=500)
        types = {ch.change_type for ch in changes}
        assert "fix_formatting" in types       # "  Allan  Fife "
        assert "fix_relation" in types         # dangling Employed By
        assert "fill_missing" in types         # employer via fife.com domain
        assert "merge" in types                # duplicate Josh Katzin (same email)
        assert all(ch.execution_status in ("Planned (dry-run)", "Recommended")
                   for ch in changes)
        # Stages narrate the phases; events feed the game.
        assert any(s["label"] == "Scanning" for s in j["stages"])
        assert j["partial"]["events"]

    def test_merge_picks_richer_survivor(self, tmp_path):
        run_felix(tmp_path, dry=True)
        merges = store.list_all_changes(base=tmp_path, change_type="merge")
        assert len(merges) == 1
        # mc3 (with employer relation) survives; mc2 is the loser.
        assert merges[0].record_id == "mc2"
        assert "mc3" in merges[0].new_value


class TestLiveMock:
    def test_live_run_applies_and_snapshots(self, tmp_path):
        j, out = run_felix(tmp_path, dry=False)
        c = out["counts"]
        assert c["applied"] > 0 and c["planned"] == 0
        applied = store.list_all_changes(base=tmp_path, status="Applied")
        assert applied
        # Every applied non-merge change has its snapshot on disk.
        # (merge children are covered by the parent's merge snapshot)
        simple = [ch for ch in applied
                  if ch.change_type in ("fix_formatting", "fix_relation",
                                        "fill_missing")
                  and not ch.parent_change_id]
        assert simple
        for ch in simple:
            assert store.load_snapshot(ch.change_id, base=tmp_path) is not None

    def test_max_writes_defers_overflow(self, tmp_path):
        j, out = run_felix(tmp_path, dry=True, max_writes=1)
        assert out["counts"]["deferred"] >= 1


class TestUndo:
    def test_undo_restores_from_snapshot(self, tmp_path):
        run_felix(tmp_path, dry=False)
        ch = store.list_all_changes(base=tmp_path, status="Applied",
                                    change_type="fix_formatting")[0]
        out = undo.undo_change(NotionConnector(), ch.change_id, base=tmp_path)
        assert out["status"] == "Undone"
        assert store.find_change(ch.change_id,
                                 base=tmp_path).execution_status == "Undone"

    def test_undo_refuses_without_snapshot(self, tmp_path):
        run_felix(tmp_path, dry=False)
        ch = store.list_all_changes(base=tmp_path, status="Applied",
                                    change_type="fix_formatting")[0]
        snap = tmp_path / "snapshots" / f"{ch.change_id}.json"
        snap.unlink()
        out = undo.undo_change(NotionConnector(), ch.change_id, base=tmp_path)
        assert "manual restore required" in out["result"]
        assert store.find_change(ch.change_id,
                                 base=tmp_path).execution_status == "Applied"

    def test_undo_merge_roundtrip(self, tmp_path):
        run_felix(tmp_path, dry=False)
        merge = store.list_all_changes(base=tmp_path, change_type="merge")[0]
        assert merge.execution_status == "Applied"
        out = undo.undo_merge(NotionConnector(), merge.change_id, base=tmp_path)
        assert out["status"] == "Undone"

    def test_pending_change_not_undoable(self, tmp_path):
        run_felix(tmp_path, dry=True)
        ch = store.list_all_changes(base=tmp_path)[0]
        out = undo.undo_change(NotionConnector(), ch.change_id, base=tmp_path)
        assert out["status"] in ("error", "Applied")
