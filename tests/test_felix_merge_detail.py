"""The side-by-side behind a duplicate-merge decision.

The card exists to answer one question — which of these two records is the
real one — and the strategy description is usually what answers it. Cutting it
mid-word makes a truncated value look like a short one, which is the failure
this file guards.
"""
import json

from src.features.felix.run import _FIELD_CLIP, _NOTE_CLIP, _merge_detail

LONG = ("This fund focuses on direct lending to small and medium-sized enterprises "
        "(SMEs) across Europe. By providing flexible financing solutions, we support "
        "growth and buyout situations across the region and beyond.")


def _record(rid, name, fields=None, url="https://notion.so/x"):
    return {"id": rid, "name": name, "plain": dict(fields or {}), "relations": {},
            "created": "2025-09-03T00:00:00.000Z", "created_by": "Jinghan Chen",
            "url": url, "title_prop": "Name"}


def _detail(fields_a, fields_b=None, notes=None):
    a = _record("a", "RedRock", fields_a)
    b = _record("b", "Red Rock", fields_b or {})
    return json.loads(_merge_detail(a, b, {"transfers": [], "conflicts": []},
                                    {}, notes or {}))


class TestFieldsAreReadable:
    def test_a_long_value_stops_at_a_word_and_says_it_stopped(self):
        # 'By providing flexible fi' was the old behaviour: a bare 120-char
        # slice, no ellipsis, so the card read as the whole value.
        kept = _detail({"Strategy Description": LONG})["keep"]
        out = kept["fields"]["Strategy Description"]
        assert out.endswith("…")
        assert not out.endswith("fi…")
        assert out.rstrip("…").split()[-1] in LONG.split()

    def test_a_value_that_fits_is_untouched(self):
        short = "This residential real estate strategy seeks EUR 5 million."
        out = _detail({"Strategy Description": short})["keep"]
        assert out["fields"]["Strategy Description"] == short
        assert "…" not in out["fields"]["Strategy Description"]

    def test_short_fields_never_gain_an_ellipsis(self):
        out = _detail({"Asset Class": "PC - Legacy", "Status": "Not met (Declined)"})
        assert out["keep"]["fields"]["Asset Class"] == "PC - Legacy"
        assert out["keep"]["fields"]["Status"] == "Not met (Declined)"

    def test_the_clip_is_a_budget_not_a_hard_cut(self):
        # Backing up to a word boundary may land under the limit; it must never
        # land over it plus the ellipsis.
        out = _detail({"Strategy Description": LONG})["keep"]
        assert len(out["fields"]["Strategy Description"]) <= _FIELD_CLIP + 1

    def test_both_columns_are_clipped_the_same_way(self):
        out = _detail({"Strategy Description": LONG},
                      {"Strategy Description": LONG})
        assert out["keep"]["fields"]["Strategy Description"] \
            == out["archive"]["fields"]["Strategy Description"]


class TestNotes:
    def test_a_long_note_title_stops_at_a_word(self):
        title = "Quarterly review with the investment committee " * 4
        out = _detail({}, notes={"a": [title]})
        assert out["keep"]["notes"][0].endswith("…")
        assert len(out["keep"]["notes"][0]) <= _NOTE_CLIP + 1

    def test_the_count_is_the_real_one_not_the_shown_one(self):
        # Only five titles are carried; the count must still say how many
        # there are, or a record with twenty notes looks like one with five.
        out = _detail({}, notes={"a": [f"Note {i}" for i in range(20)]})
        assert len(out["keep"]["notes"]) == 5
        assert out["keep"]["note_count"] == 20


class TestTheDetailStaysParseable:
    """The UI does `try { JSON.parse(detail) } catch { return null }`.

    So invalid JSON does not shorten the card, it removes it — and the record
    rich enough to need comparing is the one most likely to run long. The
    detail used to be cut at 3800 characters with a bare slice, straight
    through whatever string happened to be there.
    """

    def test_a_record_with_many_long_fields_still_parses(self):
        many = {f"Property {i}": LONG for i in range(24)}
        out = _detail(many, many)          # json.loads inside — raises if broken
        assert len(out["keep"]["fields"]) == 24
        assert out["archive"]["fields"]["Property 23"].endswith("…")

    def test_the_last_field_is_whole_rather_than_severed(self):
        many = {f"Property {i}": LONG for i in range(24)}
        out = _detail(many)
        for value in out["keep"]["fields"].values():
            assert value.startswith("This fund focuses on direct lending")

    def test_long_conflicts_do_not_break_it_either(self):
        a, b = _record("a", "RedRock", {"X": LONG}), _record("b", "Red Rock", {"X": LONG})
        raw = _merge_detail(a, b, {"transfers": [],
                                   "conflicts": [{"property": "X", "survivor": LONG,
                                                  "loser": LONG}]}, {})
        parsed = json.loads(raw)
        assert parsed["conflicts"][0]["keep"].endswith("…")
        assert not parsed["conflicts"][0]["keep"].endswith("fi…")


class TestTheCardCanReachTheRecord:
    def test_each_side_carries_its_notion_url(self):
        # Values are clipped to keep the columns comparable, so there has to be
        # a way to the whole record.
        out = _detail({"Strategy Description": LONG})
        assert out["keep"]["url"] == "https://notion.so/x"
        assert out["archive"]["url"] == "https://notion.so/x"
