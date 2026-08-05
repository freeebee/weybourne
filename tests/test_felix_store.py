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
    """Felix runs live and on demand — there is no dry-run mode to enable and
    no daily schedule to configure."""
    cfg = store.load_config(base=tmp_path)
    assert cfg["live_enabled"] is True
    assert "auto_run_enabled" not in cfg and "auto_run_hour" not in cfg
    store.save_config({"live_enabled": False}, base=tmp_path)
    assert store.load_config(base=tmp_path)["live_enabled"] is False


class TestAdjudicationCache:
    """Distinct from resolved_pairs: this is the cheap model's classification
    of a pair, good only as long as neither record's fingerprint changed."""

    def test_no_entry_is_a_cache_miss(self, tmp_path):
        assert store.cached_verdict("a", "b", "fp1", "fp2", base=tmp_path) is None

    def test_unchanged_fingerprints_hit(self, tmp_path):
        store.save_adjudication_verdict("a", "b", "fp1", "fp2", "distinct",
                                        "different employers", base=tmp_path)
        hit = store.cached_verdict("a", "b", "fp1", "fp2", base=tmp_path)
        assert hit is not None
        assert hit["verdict"] == "distinct"
        assert hit["reason"] == "different employers"

    def test_order_of_a_and_b_does_not_matter(self, tmp_path):
        # Notion pagination order can put either record first on a later
        # scan — the cache must not treat that as a different pair.
        store.save_adjudication_verdict("a", "b", "fp1", "fp2", "distinct",
                                        base=tmp_path)
        assert store.cached_verdict("b", "a", "fp2", "fp1", base=tmp_path) is not None

    def test_a_changed_fingerprint_is_a_miss(self, tmp_path):
        store.save_adjudication_verdict("a", "b", "fp1", "fp2", "distinct",
                                        base=tmp_path)
        # "a" was edited since — its fingerprint moved to fp1-new.
        assert store.cached_verdict("a", "b", "fp1-new", "fp2", base=tmp_path) is None

    def test_a_different_pair_with_the_same_fingerprints_is_still_a_miss(self, tmp_path):
        store.save_adjudication_verdict("a", "b", "fp1", "fp2", "distinct",
                                        base=tmp_path)
        assert store.cached_verdict("a", "c", "fp1", "fp2", base=tmp_path) is None

    def test_saving_again_overwrites_the_old_verdict(self, tmp_path):
        store.save_adjudication_verdict("a", "b", "fp1", "fp2", "unsure",
                                        base=tmp_path)
        store.save_adjudication_verdict("a", "b", "fp1-new", "fp2", "distinct",
                                        base=tmp_path)
        assert store.cached_verdict("a", "b", "fp1", "fp2", base=tmp_path) is None
        hit = store.cached_verdict("a", "b", "fp1-new", "fp2", base=tmp_path)
        assert hit["verdict"] == "distinct"


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
