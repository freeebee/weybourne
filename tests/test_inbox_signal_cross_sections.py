"""Strategy groups, dispersion and breadth — the cross-sectional readings.

All three run on figures managers stated in their letters, so they need no
stored track records. What they do need is to count *managers*, which is where
the first version of them went wrong.
"""
from src.features.inbox_signal import views
from src.schemas import FundRecord


def _letter(org, month_pcts, fund="Main Fund", period="p0"):
    """One letter reporting (month, pct) pairs."""
    return {
        "org": org, "period": period, "date": "2026-01-01", "stance": "neutral",
        "themes": [], "quotes": [], "source": "monthly letter",
        "reported_returns": [{"month": m, "pct": p, "fund": fund, "basis": "net"}
                             for m, p in month_pcts],
    }


class TestManagerMonths:
    def test_one_manager_reporting_several_funds_counts_once(self):
        # Regression: three share classes from one firm read as a three-manager
        # month whose best, median and worst were all the same firm.
        letters = [
            _letter("Long Corridor", [("2025-07", 9.6)], fund="LCAO"),
            _letter("Long Corridor", [("2025-07", 9.6)], fund="LCAO Feeder"),
            _letter("Long Corridor", [("2025-07", 9.6)], fund="LCAO Onshore"),
        ]
        rows = views._manager_months(letters)
        assert len(rows) == 1
        assert rows[0]["org"] == "Long Corridor"
        assert rows[0]["figures"] == 3

    def test_several_funds_in_a_month_are_averaged(self):
        letters = [_letter("Acme", [("2026-01", 2.0)], fund="A"),
                   _letter("Acme", [("2026-01", 4.0)], fund="B")]
        assert views._manager_months(letters)[0]["pct"] == 3.0

    def test_distinct_managers_stay_distinct(self):
        letters = [_letter("Acme", [("2026-01", 2.0)]),
                   _letter("Beta", [("2026-01", 4.0)])]
        assert len(views._manager_months(letters)) == 2


class TestDispersion:
    def _many(self, month, pcts):
        return [_letter(f"M{i}", [(month, p)]) for i, p in enumerate(pcts)]

    def test_reports_best_median_and_worst_with_who(self):
        letters = self._many("2026-01", [5.0, 1.0, -3.0])
        s = views.dispersion_view(letters)["series"][0]
        assert (s["best"], s["median"], s["worst"]) == (5.0, 1.0, -3.0)
        assert s["best_org"] == "M0" and s["worst_org"] == "M2"
        assert s["spread"] == 8.0

    def test_a_month_below_the_minimum_is_excluded_and_counted(self):
        # A spread between two managers is not a spread.
        letters = self._many("2026-01", [5.0, -3.0])
        out = views.dispersion_view(letters)
        assert out["series"] == []
        assert out["months_too_thin"] == 1

    def test_the_minimum_is_in_managers_not_figures(self):
        # Three figures, one manager — still too thin.
        letters = [_letter("Solo", [("2026-01", 1.0)], fund="A"),
                   _letter("Solo", [("2026-01", 2.0)], fund="B"),
                   _letter("Solo", [("2026-01", 3.0)], fund="C")]
        out = views.dispersion_view(letters)
        assert out["series"] == []
        assert out["months_too_thin"] == 1

    def test_median_of_an_even_count_is_the_midpoint(self):
        letters = self._many("2026-01", [4.0, 2.0, 1.0, -1.0])
        assert views.dispersion_view(letters)["series"][0]["median"] == 1.5


class TestBreadth:
    def test_counts_positive_against_reporters(self):
        letters = [_letter(f"M{i}", [("2026-01", p)])
                   for i, p in enumerate([3.0, 1.0, -2.0, 0.0])]
        s = views.breadth_view(letters)["series"][0]
        assert (s["positive"], s["negative"], s["flat"], s["reporters"]) == (2, 1, 1, 4)
        assert s["share"] == 0.5

    def test_thin_months_are_kept_unlike_dispersion(self):
        # One-of-one is a true statement about breadth, where a spread of one
        # manager is not.
        letters = [_letter("Solo", [("2026-01", 1.0)])]
        s = views.breadth_view(letters)["series"][0]
        assert s["reporters"] == 1 and s["positive"] == 1


class TestStrategyGroups:
    FUNDS = [
        FundRecord(id="f1", name="Acme Absolute Return Fund",
                   asset_class=["Hedge Funds - Single strategy"]),
        FundRecord(id="f2", name="Beta Buyout Fund IV", asset_class=["PE - Buyout"]),
        FundRecord(id="f3", name="Gamma Fund", asset_class=[]),
    ]

    def test_groups_by_the_notion_asset_class(self):
        letters = [_letter("Acme", [("2026-01", 2.0)]),
                   _letter("Beta Buyout", [("2026-01", 1.0)])]
        out = views.strategy_groups_view(letters, self.FUNDS)
        assert {g["group"] for g in out["groups"]} == {
            "Hedge Funds - Single strategy", "PE - Buyout"}

    def test_an_unmatched_manager_is_unclassified_not_guessed(self):
        letters = [_letter("Nowhere Capital", [("2026-01", 2.0)])]
        out = views.strategy_groups_view(letters, self.FUNDS)
        assert out["groups"] == []
        assert out["unclassified"] == ["Nowhere Capital"]

    def test_a_lookalike_firm_is_not_given_a_strategy(self):
        # 'AM Squared' scored above dedupe's REVIEW threshold against 'Hamilton
        # Square', and 'Tribeca Investment Partners' against 'Green Investment
        # Partners'. The review band means "a person should look"; there is no
        # person in this loop, so nothing below duplicate strength may classify.
        funds = [FundRecord(id="f1", name="Hamilton Square",
                            asset_class=["PE - Venture Capital"]),
                 FundRecord(id="f2", name="Green Investment Partners",
                            asset_class=["PE - Buyout"])]
        letters = [_letter("AM Squared", [("2026-01", 2.0)]),
                   _letter("Tribeca Investment Partners", [("2026-01", 1.0)])]
        out = views.strategy_groups_view(letters, funds)
        assert out["groups"] == []
        assert out["unclassified"] == ["AM Squared", "Tribeca Investment Partners"]

    def test_a_manager_still_reaches_a_fund_that_carries_its_name(self):
        # Ownership is the route that does the real work, and raising the
        # identity bar must not touch it.
        funds = [FundRecord(id="f1", name="Albizia ASEAN Opportunities Fund",
                            asset_class=["Global Equities - Active"])]
        out = views.strategy_groups_view([_letter("Albizia", [("2026-01", 2.0)])], funds)
        assert [g["group"] for g in out["groups"]] == ["Global Equities - Active"]
        assert out["unclassified"] == []

    def test_a_fund_without_an_asset_class_is_unclassified(self):
        letters = [_letter("Gamma", [("2026-01", 2.0)])]
        out = views.strategy_groups_view(letters, self.FUNDS)
        assert out["unclassified"] == ["Gamma"]

    def test_no_taxonomy_means_everything_is_unclassified_not_an_error(self):
        # Notion unreachable: the grouping loses its taxonomy, the page does not
        # lose the section.
        letters = [_letter("Acme", [("2026-01", 2.0)])]
        out = views.strategy_groups_view(letters, [])
        assert out["groups"] == []
        assert out["unclassified"] == ["Acme"]

    def test_every_month_carries_its_manager_count(self):
        letters = [_letter("Acme", [("2026-01", 2.0), ("2026-02", 1.0)])]
        g = views.strategy_groups_view(letters, self.FUNDS)["groups"][0]
        assert all("managers" in p for p in g["series"])

    def test_the_cumulative_line_compounds_the_monthly_means(self):
        letters = [_letter("Acme", [("2026-01", 10.0), ("2026-02", 10.0)])]
        g = views.strategy_groups_view(letters, self.FUNDS)["groups"][0]
        assert g["series"][-1]["cumulative"] == 21.0   # 1.1 * 1.1 - 1


class TestStandoutsDeduplicate:
    def test_the_same_figure_from_two_letters_is_ranked_once(self):
        # The same number reaches the store from more than one letter routinely
        # — an estimate then the final, or a forward under a second id.
        letter = _letter("Long Corridor", [("2025-07", 9.6)], fund="LCAO")
        out = views.standouts_and_strained([letter, dict(letter), dict(letter)])
        assert len(out["standouts"]) == 1

    def test_genuinely_different_funds_both_rank(self):
        letters = [_letter("Acme", [("2025-07", 9.6)], fund="A"),
                   _letter("Acme", [("2025-07", 9.6)], fund="B")]
        assert len(views.standouts_and_strained(letters)["standouts"]) == 2


class TestQuoteThemesAreNotTheLetters:
    """A letter's themes describe the letter, not each passage inside it.

    Real case: RPD's May 2026 letter ranged over AI, semiconductors, the Gulf,
    degrossing and option writing. Printed against a quote about ZoomInfo's
    guidance reset, those tags claimed the passage was about Iran and Hormuz.
    """

    LETTER = {
        "org": "RPD", "period": "p3", "date": "2026-06-05", "stance": "cautious",
        "themes": ["ai", "semis", "iran", "degross"],
        "quotes": [
            {"quote": "Management kitchen sinked their full-year guidance.",
             "context": "", "themes": []},
            {"quote": "Investor focus remained squarely on the AI growth narrative.",
             "context": "", "themes": ["ai"]},
        ],
    }

    def test_a_quote_carries_its_own_themes(self):
        voices = views.voices_view([self.LETTER])
        ai = next(v for v in voices if "AI growth narrative" in v["quote"])
        assert ai["themes"] == ["ai"]
        assert ai["themes_are_the_letters"] is False

    def test_a_quote_about_none_of_them_claims_none_of_them(self):
        voices = views.voices_view([self.LETTER])
        zi = next(v for v in voices if "kitchen sinked" in v["quote"])
        assert zi["themes"] == []
        assert "iran" not in zi["themes"]

    def test_letters_extracted_before_the_change_fall_back_and_say_so(self):
        # The 87 letters already on disk have no per-quote themes and are not
        # worth re-buying; they fall back to the letter's, flagged as such.
        old = {**self.LETTER,
               "quotes": [{"quote": "Something the manager said.", "context": ""}]}
        v = views.voices_view([old])[0]
        assert v["themes"] == ["ai", "semis", "iran", "degross"]
        assert v["themes_are_the_letters"] is True
