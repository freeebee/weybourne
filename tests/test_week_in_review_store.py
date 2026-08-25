from src.features.week_in_review import store


def test_save_and_load_round_trip(tmp_path):
    review = {"window": {"start": "2026-08-03", "end": "2026-08-07"}, "headline": "h"}
    store.save_review(review, base=tmp_path)
    assert store.load_review("2026-08-03", base=tmp_path) == review


def test_a_missing_week_is_none(tmp_path):
    assert store.load_review("2026-01-05", base=tmp_path) is None


def test_a_rebuild_overwrites_the_same_week(tmp_path):
    first = {"window": {"start": "2026-08-03", "end": "2026-08-07"}, "headline": "first"}
    second = {"window": {"start": "2026-08-03", "end": "2026-08-07"}, "headline": "second"}
    store.save_review(first, base=tmp_path)
    store.save_review(second, base=tmp_path)
    assert store.load_review("2026-08-03", base=tmp_path)["headline"] == "second"


def test_a_corrupt_file_is_treated_as_no_stored_review(tmp_path):
    path = store._path("2026-08-03", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    assert store.load_review("2026-08-03", base=tmp_path) is None
