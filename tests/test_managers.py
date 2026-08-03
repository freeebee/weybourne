"""Manager threads — the per-manager context shared across the app."""
import json

from src.features import managers


def test_slug():
    assert managers.slug("Fife Capital (Sydney)") == "fife-capital-sydney"
    assert managers.slug("") == "unnamed"


class TestUpsertAndFind:
    def test_creates_then_merges_without_twins(self, tmp_path):
        managers.upsert("Fife Capital", email="a@fife.com", base=tmp_path)
        # A different spelling attaches to the SAME thread, recording an alias.
        t = managers.upsert("FIFECAPITAL", company_id="co1",
                            company_name="Fife Capital", base=tmp_path)
        assert t["entity"] == "Fife Capital"
        assert "FIFECAPITAL" in t["aliases"]
        assert t["email"] == "a@fife.com"          # merged, not overwritten by blank
        assert t["company_id"] == "co1"
        assert len(list(tmp_path.glob("*.json"))) == 1

    def test_find_by_alias_and_containment(self, tmp_path):
        managers.upsert("Fife Capital", aliases=["Allan Fife"], base=tmp_path)
        assert managers.find("allan fife", base=tmp_path)["entity"] == "Fife Capital"
        # Containment: a calendar subject that merely contains the name.
        assert managers.find("Catch-up with Fife Capital", base=tmp_path) is not None

    def test_find_returns_none_for_strangers(self, tmp_path):
        managers.upsert("Fife Capital", base=tmp_path)
        assert managers.find("Blackstone", base=tmp_path) is None


class TestQuestionsAndHistory:
    def test_questions_replace_and_dedupe(self, tmp_path):
        managers.upsert("GIC", questions=[{"q": "A?"}, {"q": "A?"}, {"q": "B?"}],
                        base=tmp_path)
        t = managers.find("GIC", base=tmp_path)
        assert [q["q"] for q in t["questions"]] == ["A?", "B?"]
        # Omitting questions leaves them untouched.
        t = managers.upsert("GIC", email="x@gic.com", base=tmp_path)
        assert [q["q"] for q in t["questions"]] == ["A?", "B?"]

    def test_history_appends_and_caps(self, tmp_path):
        for i in range(45):
            managers.upsert("GIC", add_history={"kind": "triage", "subject": str(i)},
                            base=tmp_path)
        t = managers.find("GIC", base=tmp_path)
        assert len(t["history"]) == 40
        assert t["history"][-1]["subject"] == "44"
        assert all("at" in h for h in t["history"])


def test_legacy_questions_migration(tmp_path):
    legacy = tmp_path / "questions"
    legacy.mkdir()
    (legacy / "gic.json").write_text(json.dumps(
        {"entity": "GIC", "aliases": ["GIC Private"], "questions": [{"q": "A?"}]}),
        encoding="utf-8")
    threads = tmp_path / "managers"
    assert managers.migrate_legacy_questions(legacy, base=threads) == 1
    t = managers.find("GIC Private", base=threads)
    assert t and t["questions"] == [{"q": "A?"}]
    # Idempotent: a second run imports nothing.
    assert managers.migrate_legacy_questions(legacy, base=threads) == 0
