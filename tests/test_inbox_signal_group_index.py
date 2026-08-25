"""The strategy group index — every mandate on one axis, rebased to 100.

The design this follows was drawn against a complete grid where every group
reported every month. Real correspondence is ragged, and almost everything
worth testing here is about that raggedness: a shared axis built from an
irregular union, groups that start late, groups that skip a month, and a base
that has to mean the same thing for all of them.
"""
from src.features.inbox_signal import views
from src.schemas import FundRecord


def _letter(org, month_pcts, fund="Main Fund"):
    return {
        "org": org, "period": "p0", "date": "2026-01-01", "stance": "neutral",
        "themes": [], "quotes": [], "source": "monthly letter",
        "reported_returns": [{"month": m, "pct": p, "fund": fund, "basis": "net"}
                             for m, p in month_pcts],
    }


FUNDS = [
    FundRecord(id="f1", name="Acme Absolute Return Fund",
               asset_class=["Hedge Funds - Single strategy"]),
    FundRecord(id="f2", name="Beta Buyout Fund IV", asset_class=["PE - Buyout"]),
    FundRecord(id="f3", name="Cedar Buyout Partners II", asset_class=["PE - Buyout"]),
]


class TestTheIndexItself:
    def test_the_level_compounds_the_equal_weighted_mean(self):
        out = views.group_index_view([_letter("Acme", [("2026-01", 10.0),
                                                       ("2026-02", 10.0)])], FUNDS)
        g = out["groups"][0]
        assert g["values"] == [110.0, 121.0]

    def test_the_base_is_the_start_of_the_first_month_not_a_plotted_point(self):
        # 100 is where the index begins, so the first plotted value already
        # carries January's return. Plotting a point at 100 would put a month
        # on the axis that nobody reported.
        out = views.group_index_view(
            [_letter("Acme", [("2026-01", 5.0), ("2026-02", 0.0)])], FUNDS)
        assert out["base"] == 100
        assert out["base_month"] == "2026-01"
        assert out["groups"][0]["values"] == [105.0, 105.0]
        assert out["months"] == ["2026-01", "2026-02"]

    def test_managers_are_weighted_equally_not_by_figures_filed(self):
        # Beta files two share classes, Cedar one. Both are PE - Buyout, and
        # the group mean must not tilt towards whoever writes more often.
        letters = [_letter("Beta Buyout", [("2026-01", 10.0), ("2026-02", 0.0)], fund="A"),
                   _letter("Beta Buyout", [("2026-01", 10.0), ("2026-02", 0.0)], fund="B"),
                   _letter("Cedar Buyout", [("2026-01", 0.0), ("2026-02", 0.0)])]
        g = views.group_index_view(letters, FUNDS)["groups"][0]
        assert g["values"] == [105.0, 105.0]
        assert g["manager_count"] == 2


class TestTheSharedAxis:
    def test_the_axis_is_the_union_of_every_group(self):
        letters = [_letter("Acme", [("2026-01", 1.0), ("2026-04", 1.0)]),
                   _letter("Beta Buyout", [("2026-02", 1.0), ("2026-03", 1.0)])]
        assert views.group_index_view(letters, FUNDS)["months"] == \
            ["2026-01", "2026-02", "2026-03", "2026-04"]

    def test_a_group_that_starts_late_sits_at_the_base_until_it_reports(self):
        letters = [_letter("Acme", [("2026-01", 10.0), ("2026-02", 10.0),
                                    ("2026-03", 0.0)]),
                   _letter("Beta Buyout", [("2026-02", 5.0), ("2026-03", 0.0)])]
        out = views.group_index_view(letters, FUNDS)
        beta = next(g for g in out["groups"] if g["group"] == "PE - Buyout")
        assert beta["values"] == [100.0, 105.0, 105.0]
        assert beta["reported"] == [False, True, True]

    def test_a_skipped_month_carries_flat_and_says_so(self):
        # The one place this could mislead: a flat stretch is an absence of a
        # report, not a flat month. The series has to admit which it is.
        letters = [_letter("Acme", [("2026-01", 10.0), ("2026-03", 10.0)]),
                   _letter("Beta Buyout", [("2026-02", 1.0)])]
        out = views.group_index_view(letters, FUNDS)
        acme = next(g for g in out["groups"] if g["group"].startswith("Hedge"))
        assert out["months"] == ["2026-01", "2026-02", "2026-03"]
        assert acme["values"] == [110.0, 110.0, 121.0]
        assert acme["reported"] == [True, False, True]
        assert acme["months_reported"] == 2

    def test_every_group_spans_the_whole_axis(self):
        # Ragged lengths in one frame would read as short lines rather than
        # late starts.
        letters = [_letter("Acme", [("2026-01", 1.0), ("2026-02", 1.0)]),
                   _letter("Beta Buyout", [("2026-02", 1.0), ("2026-03", 1.0)])]
        out = views.group_index_view(letters, FUNDS)
        assert len(out["groups"]) == 2, "fixture must leave something to assert on"
        assert all(len(g["values"]) == len(out["months"]) for g in out["groups"])
        assert all(len(g["reported"]) == len(out["months"]) for g in out["groups"])
        assert all(len(g["managers_by_month"]) == len(out["months"])
                   for g in out["groups"])

    def test_the_manager_count_travels_with_every_month(self):
        letters = [_letter("Beta Buyout", [("2026-01", 1.0), ("2026-02", 1.0)]),
                   _letter("Cedar Buyout", [("2026-02", 1.0)])]
        g = views.group_index_view(letters, FUNDS)["groups"][0]
        assert g["managers_by_month"] == [1, 2]
        assert g["manager_count"] == 2


class TestWhatIsLeftOut:
    def test_an_unclassified_manager_is_named_not_grouped(self):
        letters = [_letter("Acme", [("2026-01", 1.0), ("2026-02", 1.0)]),
                   _letter("Nowhere Capital", [("2026-01", 99.0), ("2026-02", 99.0)])]
        out = views.group_index_view(letters, FUNDS)
        assert out["unclassified"] == ["Nowhere Capital"]
        assert len(out["groups"]) == 1

    def test_an_unclassified_month_does_not_widen_the_axis(self):
        # Regression: building the axis from every reported month rather than
        # every *grouped* month left a column no line could ever cross.
        letters = [_letter("Acme", [("2026-01", 1.0), ("2026-02", 1.0)]),
                   _letter("Nowhere Capital", [("2026-06", 1.0), ("2026-07", 1.0)])]
        assert views.group_index_view(letters, FUNDS)["months"] == \
            ["2026-01", "2026-02"]

    def test_no_taxonomy_is_an_empty_chart_not_an_error(self):
        out = views.group_index_view(
            [_letter("Acme", [("2026-01", 1.0), ("2026-02", 1.0)])], [])
        assert out["groups"] == []
        assert out["months"] == []
        assert out["base_month"] == ""
        assert out["unclassified"] == ["Acme"]

    def test_no_letters_at_all(self):
        out = views.group_index_view([], FUNDS)
        assert out["groups"] == [] and out["months"] == []


class TestAGroupTooThinToIndex:
    """One reported month is not a path, and must not be drawn as one.

    Real data: four of seven groups had reported a single month. Each would
    have been drawn flat across the whole axis with one step in it, in the same
    weight as a group that reported nine — an invitation to compare them.
    """

    def test_a_single_reported_month_is_held_out_and_named(self):
        letters = [_letter("Acme", [("2026-01", 1.0), ("2026-02", 1.0)]),
                   _letter("Beta Buyout", [("2026-02", -14.7)])]
        out = views.group_index_view(letters, FUNDS)
        assert [g["group"] for g in out["groups"]] == ["Hedge Funds - Single strategy"]
        assert [t["group"] for t in out["thin"]] == ["PE - Buyout"]
        assert out["thin"][0]["months_reported"] == 1

    def test_the_held_out_group_keeps_its_figures_for_the_footnote(self):
        # Named, not silently dropped: the reader is told what was left out and
        # what it was worth.
        letters = [_letter("Acme", [("2026-01", 1.0), ("2026-02", 1.0)]),
                   _letter("Beta Buyout", [("2026-02", 10.0)])]
        thin = views.group_index_view(letters, FUNDS)["thin"][0]
        assert thin["end"] == 110.0
        assert thin["manager_count"] == 1

    def test_two_reported_months_is_enough(self):
        letters = [_letter("Acme", [("2026-01", 1.0), ("2026-02", 1.0)])]
        out = views.group_index_view(letters, FUNDS)
        assert len(out["groups"]) == 1 and out["thin"] == []
        assert out["min_months"] == 2

    def test_nothing_drawable_leaves_no_axis_behind(self):
        # A chart with an axis and no lines reads as a loading failure.
        out = views.group_index_view([_letter("Acme", [("2026-01", 1.0)])], FUNDS)
        assert out["groups"] == []
        assert out["months"] == [] and out["base_month"] == ""
        assert [t["group"] for t in out["thin"]] == ["Hedge Funds - Single strategy"]

    def test_the_axis_stops_at_the_last_month_anybody_drawable_reported(self):
        # Regression: a held-out group reporting a late month left the axis
        # stretching into empty space no line could reach.
        letters = [_letter("Acme", [("2026-01", 1.0), ("2026-02", 1.0)]),
                   _letter("Beta Buyout", [("2026-09", 1.0)])]
        out = views.group_index_view(letters, FUNDS)
        assert out["months"] == ["2026-01", "2026-02"]
        assert len(out["groups"][0]["values"]) == 2
        assert len(out["groups"][0]["reported"]) == 2

    def test_a_trailing_carry_inside_the_drawable_set_is_kept(self):
        # Only months past *everybody* are trimmed. A group that stopped
        # reporting while another carried on still shows the carry.
        letters = [_letter("Acme", [("2026-01", 1.0), ("2026-02", 1.0)]),
                   _letter("Beta Buyout", [("2026-01", 1.0), ("2026-03", 1.0)])]
        out = views.group_index_view(letters, FUNDS)
        assert out["months"] == ["2026-01", "2026-02", "2026-03"]
        acme = next(g for g in out["groups"] if g["group"].startswith("Hedge"))
        assert acme["reported"] == [True, True, False]


class TestOrdering:
    def test_groups_are_ranked_by_where_they_finish(self):
        # The legend then reads in the order the lines finish, which is the
        # order the eye takes off the chart anyway.
        letters = [_letter("Acme", [("2026-01", 1.0), ("2026-02", 0.0)]),
                   _letter("Beta Buyout", [("2026-01", 20.0), ("2026-02", 0.0)])]
        out = views.group_index_view(letters, FUNDS)
        assert [g["group"] for g in out["groups"]] == [
            "PE - Buyout", "Hedge Funds - Single strategy"]

    def test_a_tie_falls_back_to_the_name_so_the_order_is_stable(self):
        letters = [_letter("Acme", [("2026-01", 5.0), ("2026-02", 0.0)]),
                   _letter("Beta Buyout", [("2026-01", 5.0), ("2026-02", 0.0)])]
        out = views.group_index_view(letters, FUNDS)
        assert [g["group"] for g in out["groups"]] == [
            "Hedge Funds - Single strategy", "PE - Buyout"]


class TestItReachesTheDashboard:
    def test_build_carries_the_group_index(self, tmp_path):
        out = views.build(voices_base=tmp_path, manifest_base=tmp_path,
                          records_base=tmp_path, funds=[], cross_base=tmp_path)
        assert "group_index" in out
        assert out["group_index"]["groups"] == []
