"""End-to-end pipeline in mock mode: the full dry run, live-mode execution
against the mock connector, and the undo engine's conflict discipline."""
import json

from src.connectors.notion_client import NotionConnector
from src.features.felix import execute, run as runmod
from src.features.felix import store, undo
from src.features.felix.models import ChangeRecord, RunOptions
from src.features.felix.run import felix_run


def job():
    return {"stages": [], "partial": {}}


def run_felix(base, dry=True, client=None, **opt):
    j = job()
    out = felix_run(j, NotionConnector(), client,
                    RunOptions(dry_run=dry, **opt), base=base)
    return j, out


def seed_change(base, n, change_type="fill_missing",
                execution_status="Proposed", review_status="Awaiting Review"):
    """A minimal change-log row, as if left over from an earlier run —
    for testing the backlog count without running the whole pipeline."""
    run_id = f"seed{n}"
    ch = ChangeRecord(
        change_id=f"FLX-seed-{n:04d}", run_id=run_id, timestamp="2026-01-01",
        database="contacts", record_name=f"Seed {n}", change_type=change_type,
        execution_status=execution_status, review_status=review_status)
    store.append_change(ch, base)
    return ch


class TestPendingWithoutModel:
    """An ordinary run's cheap, no-model-call decision on whether an
    uncached fuzzy pair is confident enough to surface as-is."""

    def test_a_contested_same_name_pair_always_qualifies(self):
        # score alone would not clear the bar, but a same-name group is its
        # own strong signal regardless of the raw similarity score.
        pair = {"score": 0.5, "contested": "different employers"}
        assert runmod._worth_pending_without_model(pair)

    def test_a_high_score_pair_qualifies(self):
        assert runmod._worth_pending_without_model({"score": 0.9})

    def test_a_borderline_review_threshold_score_does_not_qualify(self):
        # 0.72 clears detect.REVIEW_THRESHOLD (worth a model's attention)
        # but not the higher bar for showing it with none at all.
        assert not runmod._worth_pending_without_model({"score": 0.72})

    def test_exactly_at_the_threshold_qualifies(self):
        assert runmod._worth_pending_without_model(
            {"score": runmod.PENDING_WITHOUT_MODEL_THRESHOLD})


class TestComplexCaseBacklog:
    """The 10-at-a-time cap, and the auto-research watermark, both key off
    this count — everything awaiting review except the uncapped easy types."""

    def test_empty_queue_is_zero(self, tmp_path):
        assert runmod.complex_case_backlog(tmp_path) == 0

    def test_counts_proposed_and_recommended_and_planned(self, tmp_path):
        seed_change(tmp_path, 1, execution_status="Proposed")
        seed_change(tmp_path, 2, execution_status="Recommended")
        seed_change(tmp_path, 3, execution_status="Planned (dry-run)")
        assert runmod.complex_case_backlog(tmp_path) == 3

    def test_easy_change_types_are_excluded(self, tmp_path):
        for t in runmod.EASY_CHANGE_TYPES:
            seed_change(tmp_path, hash(t) % 10000, change_type=t)
        assert runmod.complex_case_backlog(tmp_path) == 0

    def test_decided_or_applied_rows_are_excluded(self, tmp_path):
        seed_change(tmp_path, 1, execution_status="Applied")
        seed_change(tmp_path, 2, execution_status="Failed")
        seed_change(tmp_path, 3, review_status="Approved")
        seed_change(tmp_path, 4, review_status="Dismissed")
        assert runmod.complex_case_backlog(tmp_path) == 0


class TestShouldResearchNow:
    """options.web_research is a manual override; otherwise an ordinary run
    researches ambiguous cases on its own exactly while the complex side of
    the queue has room — see COMPLEX_CASE_LOW_WATERMARK (5)."""

    def test_an_ordinary_run_researches_when_the_queue_is_short(self):
        opts = RunOptions(web_research=False)
        assert runmod._should_research_now(opts, backlog=0)
        assert runmod._should_research_now(
            opts, backlog=runmod.COMPLEX_CASE_LOW_WATERMARK - 1)

    def test_an_ordinary_run_pauses_at_the_watermark(self):
        opts = RunOptions(web_research=False)
        assert not runmod._should_research_now(
            opts, backlog=runmod.COMPLEX_CASE_LOW_WATERMARK)
        assert not runmod._should_research_now(opts, backlog=9)

    def test_the_manual_override_ignores_the_watermark(self):
        opts = RunOptions(web_research=True)
        assert runmod._should_research_now(opts, backlog=9)


class TestStageTimings:
    """Per-phase durations persist on the RunRecord — real minutes-per-stage,
    not just a whole-run elapsed counter, so a slow run can be explained
    after the fact."""

    def test_run_record_carries_a_duration_per_stage(self, tmp_path):
        _j, out = run_felix(tmp_path, dry=True)
        run = store.load_run(out["run_id"], base=tmp_path)
        assert run.stages
        labels = [s["label"] for s in run.stages]
        assert "Scanning" in labels
        assert "Detecting issues" in labels
        assert all(isinstance(s["duration_s"], (int, float)) for s in run.stages)
        assert all(s["duration_s"] >= 0 for s in run.stages)

    def test_stage_durations_sum_to_roughly_the_whole_run(self, tmp_path):
        import time

        t0 = time.time()
        _j, out = run_felix(tmp_path, dry=True)
        wall = time.time() - t0
        run = store.load_run(out["run_id"], base=tmp_path)
        total = sum(s["duration_s"] for s in run.stages)
        # Loose bound — this mock run is fast, but the sum must not run away
        # from the actual wall clock (e.g. double-counting a stage).
        assert total <= wall + 1.0


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
        # Nothing is ever written without a click, dry run or not — easy
        # fixes land as "Planned (dry-run)", everything needing a reason
        # (a fill, a merge) as "Proposed", pure information as "Recommended".
        assert all(ch.execution_status in ("Planned (dry-run)", "Proposed",
                                           "Recommended")
                   for ch in changes)
        # A merge always says why it's confident enough to propose, however
        # sure the match — here, an exact shared identifier.
        merge = next(ch for ch in changes if ch.change_type == "merge")
        assert "identifier" in merge.reason
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

    def test_resolved_pair_never_reflagged(self, tmp_path):
        # The user decided these two are NOT duplicates — later runs must not
        # propose the merge again.
        store.resolve_pair("mc2", "mc3", "user-not-duplicate", base=tmp_path)
        run_felix(tmp_path, dry=True)
        assert store.list_all_changes(base=tmp_path, change_type="merge") == []

    def test_the_cap_spans_runs_via_the_real_backlog(self, tmp_path):
        """A run starting while the complex queue is already full must stop
        at the very next complex finding rather than piling ten more on top
        of it — but easy fixes are exempt from the cap entirely, so all of
        those still show up regardless."""
        for i in range(10):
            seed_change(tmp_path, i)
        j, out = run_felix(tmp_path, dry=True)
        assert out["counts"]["stopped_at_cap"] >= 10
        changes = store.list_all_changes(base=tmp_path, limit=500)
        this_run = [ch for ch in changes if ch.run_id == out["run_id"]]
        # The cap check runs AFTER recording (findings += 1 then compare), so
        # the one complex finding that crosses the threshold is still filed
        # — that is what stops the run — but nothing beyond it is.
        complex_this_run = [ch for ch in this_run
                            if ch.change_type not in runmod.EASY_CHANGE_TYPES]
        assert len(complex_this_run) == 1
        # Formatting/relation fixes were filed anyway — uncapped.
        assert any(ch.change_type in runmod.EASY_CHANGE_TYPES for ch in this_run)


class TestLiveMock:
    def test_a_live_run_still_only_proposes_nothing_applies(self, tmp_path):
        """dry_run=False no longer means "write it" — a run of any kind only
        ever files change-log rows; approving each one is what applies it
        (see api/main.py's felix_review, or execute.apply_change directly)."""
        j, out = run_felix(tmp_path, dry=False)
        c = out["counts"]
        assert c["applied"] == 0
        assert c["planned"] > 0    # the easy fixes (formatting, relation)
        assert c["proposed"] > 0   # the fill and the merge
        assert store.list_all_changes(base=tmp_path, status="Applied") == []
        # Every property-change proposal has its snapshot on disk so
        # approving it later applies exactly what was planned here.
        simple = [ch for ch in store.list_all_changes(base=tmp_path, limit=500)
                  if ch.change_type in ("fix_formatting", "fix_relation",
                                        "fill_missing")]
        assert simple
        for ch in simple:
            assert store.load_snapshot(ch.change_id, base=tmp_path) is not None

    def test_easy_fixes_are_not_limited_by_max_writes(self, tmp_path):
        """max_writes no longer gates proposal creation for formatting/icon/
        relation fixes — only options.max_findings does, and easy fixes are
        exempt from that cap too (see EASY_CHANGE_TYPES)."""
        j, out = run_felix(tmp_path, dry=True, max_writes=1)
        easy = [ch for ch in store.list_all_changes(base=tmp_path, limit=500)
                if ch.change_type in runmod.EASY_CHANGE_TYPES]
        assert len(easy) > 1
        assert out["counts"]["deferred"] == 0


class TestUndo:
    """Undo only ever acts on an APPLIED change. Nothing a run files is
    applied on its own any more — these approve a proposal first (the same
    call felix_review makes, minus the API layer) before exercising undo."""

    def _approve_first(self, base, change_type="fix_formatting"):
        ch = store.list_all_changes(base=base, change_type=change_type)[0]
        snap = store.load_snapshot(ch.change_id, base=base)
        return execute.apply_change(
            NotionConnector(), ch, snap["planned"],
            expect_prop=snap.get("expect_prop", ""),
            scanned_plain=snap.get("scanned_plain"), dry_run=False,
            scanned_raw=snap.get("scanned_raw"), base=base)

    def test_undo_restores_from_snapshot(self, tmp_path):
        run_felix(tmp_path, dry=True)
        applied = self._approve_first(tmp_path)
        assert applied.execution_status == "Applied"
        out = undo.undo_change(NotionConnector(), applied.change_id, base=tmp_path)
        assert out["status"] == "Undone"
        assert store.find_change(applied.change_id,
                                 base=tmp_path).execution_status == "Undone"

    def test_undo_refuses_without_snapshot(self, tmp_path):
        run_felix(tmp_path, dry=True)
        applied = self._approve_first(tmp_path)
        snap = tmp_path / "snapshots" / f"{applied.change_id}.json"
        snap.unlink()
        out = undo.undo_change(NotionConnector(), applied.change_id, base=tmp_path)
        assert "manual restore required" in out["result"]
        assert store.find_change(applied.change_id,
                                 base=tmp_path).execution_status == "Applied"

    def test_undo_merge_roundtrip(self, tmp_path):
        run_felix(tmp_path, dry=True)
        proposal = store.list_all_changes(base=tmp_path, change_type="merge")[0]
        assert proposal.execution_status == "Proposed"    # never auto-merged
        pair = json.loads(proposal.detail)["pair"]
        out = runmod.merge_pair_now(NotionConnector(), pair, proposal.database,
                                    source="test", reason="test", base=tmp_path)
        assert out["status"] == "Applied"
        merge = store.list_all_changes(base=tmp_path, change_type="merge",
                                       status="Applied")[0]
        out = undo.undo_merge(NotionConnector(), merge.change_id, base=tmp_path)
        assert out["status"] == "Undone"

    def test_pending_change_not_undoable(self, tmp_path):
        run_felix(tmp_path, dry=True)
        ch = store.list_all_changes(base=tmp_path)[0]
        out = undo.undo_change(NotionConnector(), ch.change_id, base=tmp_path)
        assert out["status"] in ("error", "Applied")
