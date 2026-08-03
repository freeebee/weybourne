"""Transcript library — autosave during a meeting, permanent filing on Stop."""
from src.features import transcript_library as tl


def _record(sid="20260803-140000", **over):
    rec = {"id": sid, "who": "Fife Capital", "goal": "capacity story",
           "started": "2026-08-03T14:00:00", "transcript": "one two three",
           "entries": [{"at": "14:00:08", "text": "one two three"}],
           "recaps": [{"at": "14:00", "recap": "They opened on capacity."}],
           "questions": [{"q": "A?", "starred": True, "flag": False, "answer": None}]}
    rec.update(over)
    return rec


def test_autosave_then_finish_moves_to_library(tmp_path):
    live, lib = tmp_path / "live", tmp_path / "lib"
    tl.autosave(_record(), live_dir=live)
    assert (live / "20260803-140000.json").exists()

    out = tl.finish(_record(), live_dir=live, lib_dir=lib)
    assert out == {"id": "20260803-140000", "title": "Fife Capital", "words": 3}
    assert (lib / "20260803-140000.json").exists()
    assert not (live / "20260803-140000.json").exists()   # autosave cleaned up


def test_orphaned_autosave_listed_as_unfinished(tmp_path):
    live, lib = tmp_path / "live", tmp_path / "lib"
    tl.autosave(_record("20260803-090000", who="Crashed Call"), live_dir=live)
    tl.finish(_record(), live_dir=live, lib_dir=lib)

    rows = tl.list_all(live_dir=live, lib_dir=lib)
    assert [r["title"] for r in rows] == ["Fife Capital", "Crashed Call"]
    assert [r["unfinished"] for r in rows] == [False, True]


def test_load_prefers_library_and_sanitises_id(tmp_path):
    live, lib = tmp_path / "live", tmp_path / "lib"
    tl.finish(_record(), live_dir=live, lib_dir=lib)
    rec = tl.load("../20260803-140000", live_dir=live, lib_dir=lib)
    assert rec and rec["transcript"] == "one two three"
    assert tl.load("nope", live_dir=live, lib_dir=lib) is None


def test_untitled_and_empty_transcript(tmp_path):
    live, lib = tmp_path / "live", tmp_path / "lib"
    out = tl.finish(_record(who="", transcript=""), live_dir=live, lib_dir=lib)
    assert out["title"] == "Untitled meeting"
    assert out["words"] == 0
