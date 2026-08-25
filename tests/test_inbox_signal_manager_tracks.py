"""Per-manager track records, and the arithmetic behind them.

Every figure on that table is computed from months a manager put in writing,
and those are sparse. The tests that matter here are the ones that stop a
four-month total being read as a year.
"""
from src.features.inbox_signal import views
from src.schemas import FundRecord


def _letter(org, period, date, stance, months, fund="Flagship"):
    return {"org": org, "message_id": f"{org}-{period}", "period": period, "date": date,
            "stance": stance, "themes": [], "quotes": [],
            "reported_returns": [{"month": m, "pct": p, "fund": fund} for m, p in months]}


FUNDS = [FundRecord(id="f1", name="Acme Absolute Return Fund",
                    asset_class=["Hedge Funds - Single strategy"]),
         FundRecord(id="f2", name="Beta Buyout Fund IV", asset_class=["PE - Buyout"])]


class TestArithmetic:
    def test_the_total_compounds_rather_than_adds(self):
        # +10% then -10% is -1%, not 0%.
        assert views._cumulative([10.0, -10.0]) == -1.0

    def test_drawdown_is_peak_to_trough_along_the_path(self):
        # Up 20, down 20 (to 0.96 of a 1.20 peak) = -20% from the peak.
        assert views._max_drawdown([20.0, -20.0]) == -20.0

    def test_a_rising_path_has_no_drawdown(self):
        assert views._max_drawdown([1.0, 2.0, 3.0]) == 0.0

    def test_drawdown_survives_a_recovery(self):
        # The trough still happened, even though the path came back.
        assert views._max_drawdown([-10.0, 30.0]) == -10.0

    def test_no_months_is_not_an_error(self):
        assert views._max_drawdown([]) == 0.0 and views._cumulative([]) == 0.0


class TestManagerTracks:
    LETTERS = [
        _letter("Acme", "p0", "2025-09-02", "constructive", [("2025-08", 4.0)]),
        _letter("Acme", "p2", "2026-03-03", "cautious", [("2026-02", -2.0)]),
        _letter("Beta Buyout", "p0", "2025-09-02", "neutral", [("2025-08", 1.0)]),
    ]

    def test_managers_are_grouped_by_their_notion_strategy(self):
        out = views.manager_tracks_view(self.LETTERS, FUNDS)
        assert {g["group"] for g in out["groups"]} == {"Hedge Funds - Single strategy",
                                                       "PE - Buyout"}

    def test_the_reported_count_is_carried_so_a_total_is_not_read_as_a_year(self):
        out = views.manager_tracks_view(self.LETTERS, FUNDS)
        acme = next(m for g in out["groups"] for m in g["managers"] if m["org"] == "Acme")
        assert acme["reported"] == 2
        assert acme["total"] == views._cumulative([4.0, -2.0])

    def test_months_are_ordered_oldest_first(self):
        out = views.manager_tracks_view(self.LETTERS, FUNDS)
        acme = next(m for g in out["groups"] for m in g["managers"] if m["org"] == "Acme")
        assert [m["month"] for m in acme["months"]] == ["2025-08", "2026-02"]

    def test_tone_has_one_slot_per_sampled_window_and_gaps_stay_gaps(self):
        # A window with no letter is None, not a neutral — the distinction the
        # whole page rests on.
        out = views.manager_tracks_view(self.LETTERS, FUNDS)
        acme = next(m for g in out["groups"] for m in g["managers"] if m["org"] == "Acme")
        assert len(acme["tone"]) == len(out["periods"])
        assert acme["tone"][0]["stance"] == "constructive"
        assert acme["tone"][2]["stance"] == "cautious"
        assert acme["tone"][1] is None and acme["tone"][4] is None

    def test_an_unmatched_manager_is_listed_rather_than_filed_wrongly(self):
        letters = self.LETTERS + [_letter("Nowhere", "p0", "2025-09-02", "neutral",
                                          [("2025-08", 3.0)])]
        out = views.manager_tracks_view(letters, FUNDS)
        assert [m["org"] for m in out["unclassified"]] == ["Nowhere"]
        assert all(m["org"] != "Nowhere" for g in out["groups"] for m in g["managers"])

    def test_one_manager_reporting_two_funds_in_a_month_counts_once(self):
        # Same rule as every other cross-section: share classes are not managers.
        two = {**_letter("Acme", "p0", "2025-09-02", "constructive", []),
               "reported_returns": [{"month": "2025-08", "pct": 4.0, "fund": "A"},
                                    {"month": "2025-08", "pct": 6.0, "fund": "B"}]}
        out = views.manager_tracks_view([two], FUNDS)
        acme = out["groups"][0]["managers"][0] if out["groups"] else out["unclassified"][0]
        assert acme["reported"] == 1 and acme["total"] == 5.0


class TestGroupSeries:
    def test_each_chart_is_re_read_per_group_not_sliced(self):
        # A month thin across the desk may be thinner still inside one mandate,
        # and only re-running applies that test where it belongs.
        letters = TestManagerTracks.LETTERS
        out = views._group_series(letters, FUNDS, views.breadth_view)
        assert "all" in out and "by_group" in out
        for group, view in out["by_group"].items():
            assert view["series"], f"{group} kept an empty series"
            assert view["managers"] >= 1


class TestToneCarriesItsEvidence:
    """A coloured square that cannot be opened asks to be taken on trust."""

    def _letter(self, org, period, date, stance, quotes, source="August letter"):
        return {"org": org, "message_id": f"{org}-{date}", "period": period,
                "date": date, "stance": stance, "themes": [],
                "person": "A Person", "source": source,
                "web_link": f"https://outlook/{date}",
                "quotes": [{"quote": q, "context": "why"} for q in quotes],
                "reported_returns": [{"month": "2025-08", "pct": 1.0, "fund": "Acme Fund"}]}

    def _cell(self, letters, i=0):
        out = views.manager_tracks_view(letters, FUNDS)
        acme = next(m for g in out["groups"] for m in g["managers"] if m["org"] == "Acme")
        return acme["tone"][i]

    def test_a_box_carries_the_letter_behind_it(self):
        cell = self._cell([self._letter("Acme", "p0", "2025-09-02", "cautious",
                                        ["We trimmed risk into the print."])])
        assert cell["stance"] == "cautious"
        assert len(cell["letters"]) == 1
        letter = cell["letters"][0]
        assert letter["quotes"][0]["quote"] == "We trimmed risk into the print."
        assert letter["web_link"] == "https://outlook/2025-09-02"
        assert letter["source"] == "August letter"

    def test_two_letters_in_one_window_are_both_kept(self):
        # The square takes the latest stance, as it always has. Showing only
        # that letter would hide the other one entirely.
        cell = self._cell([
            self._letter("Acme", "p0", "2025-09-02", "constructive", ["Early view."]),
            self._letter("Acme", "p0", "2025-09-20", "negative", ["Later view."])])
        assert cell["stance"] == "negative"
        assert [x["date"] for x in cell["letters"]] == ["2025-09-02", "2025-09-20"]
        assert [x["stance"] for x in cell["letters"]] == ["constructive", "negative"]

    def test_a_letter_with_no_quotes_still_opens(self):
        # A bare NAV notice has a stance and a link but nothing to quote; the
        # drawer must not present that as an error.
        cell = self._cell([self._letter("Acme", "p0", "2025-09-02", "neutral", [])])
        assert cell["letters"][0]["quotes"] == []
        assert cell["letters"][0]["web_link"]

    def test_a_window_with_no_letter_stays_empty(self):
        cell = self._cell([self._letter("Acme", "p0", "2025-09-02", "cautious", ["x"])], i=1)
        assert cell is None
