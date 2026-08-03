"""Felix's local change log, snapshots and config."""
from src.features.felix import store
from src.features.felix.models import ChangeRecord, RunRecord


def change(cid, run_id="abc123def456", **over):
    base = dict(change_id=cid, run_id=run_id, timestamp="2026-08-03T10:00:00",
                database="contacts", change_type="fix_formatting",
                execution_status="Applied")
    base.update(over)
    return ChangeRecord(**base)


def test_change_id_scheme():
    from datetime import datetime

    cid = store.change_id_for("abc123def456", 7, datetime(2026, 8, 3))
    assert cid == "FLX-20260803-abc123-0007"


def test_changes_roundtrip_update_and_find(tmp_path):
    c1 = change("FLX-20260803-abc123-0001")
    c2 = change("FLX-20260803-abc123-0002", execution_status="Pending")
    store.save_changes("abc123def456", [c1, c2], base=tmp_path)
    assert store.find_change("FLX-20260803-abc123-0002", base=tmp_path).execution_status == "Pending"
    assert store.update_change("FLX-20260803-abc123-0002",
                               {"execution_status": "Applied"}, base=tmp_path)
    assert store.find_change("FLX-20260803-abc123-0002", base=tmp_path).execution_status == "Applied"
    assert store.find_change("FLX-nope", base=tmp_path) is None


def test_list_all_changes_filters(tmp_path):
    store.save_changes("run1", [
        change("FLX-20260803-run100-0001", run_id="run1"),
        change("FLX-20260803-run100-0002", run_id="run1",
               database="funds", execution_status="Failed"),
    ], base=tmp_path)
    assert len(store.list_all_changes(base=tmp_path)) == 2
    assert store.list_all_changes(base=tmp_path, status="Failed")[0].database == "funds"
    assert store.list_all_changes(base=tmp_path, db="contacts")[0].database == "contacts"


def test_snapshots_roundtrip(tmp_path):
    payload = {"before": {"Name": {"title": []}}, "after": None}
    store.save_snapshot("FLX-1", payload, base=tmp_path)
    assert store.load_snapshot("FLX-1", base=tmp_path) == payload
    assert store.load_snapshot("FLX-missing", base=tmp_path) is None


def test_config_defaults_and_merge(tmp_path):
    cfg = store.load_config(base=tmp_path)
    assert cfg["live_enabled"] is False          # dry-run until flipped
    store.save_config({"live_enabled": True}, base=tmp_path)
    cfg = store.load_config(base=tmp_path)
    assert cfg["live_enabled"] is True and cfg["auto_run_hour"] == 7


def test_stats_aggregates(tmp_path):
    store.save_run(RunRecord(run_id="run1", started="2026-08-03T09:00:00",
                             status="done", dry_run=False), base=tmp_path)
    store.save_changes("run1", [
        change("FLX-20260803-run100-0001", run_id="run1"),
        change("FLX-20260803-run100-0002", run_id="run1",
               execution_status="Undone"),
        change("FLX-20260803-run100-0003", run_id="run1",
               change_type="recommendation", execution_status="Recommended"),
    ], base=tmp_path)
    s = store.stats(base=tmp_path)
    assert s["applied_total"] == 1
    assert s["undone"] == 1
    assert s["recommendations"] == 1
    assert s["runs"] == 1 and s["last_run"]["run_id"] == "run1"
