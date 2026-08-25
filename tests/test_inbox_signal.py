"""Tests for the Inbox Signal sweep, extraction and factor correlation.

The two properties worth most here are the ones whose failure is invisible in
the product: that a quote is never published unless it really occurs in the
letter, and that a sweep never pays to read the same message twice.
"""
import datetime as dt
import json

import pytest

from src import config
from src.connectors.graph import GraphConnector
from src.features import factor_correlation as fc
from src.features import track_record_store
from src.features.inbox_signal import attachments as att_mod
from src.features.inbox_signal import manifest as mf
from src.features.inbox_signal import store
from src.features.inbox_signal.extract_letter import extract_letter
from src.features.inbox_signal.periods import PERIODS, period_for
from src.features.inbox_signal.sweep import sweep
from src.features.track_record import TrackRecord
from src.schemas import EmailAttachment, EmailMessage
from tests.fakes import FakeClient

LETTER_BODY = (
    "Dear Investors,\n\n"
    "In August, the NAV of the Pangolin Asia Fund, net of all fees & expenses, "
    "fell 0.88% to USD530.99.\n\n"
    "The fund was up until last Friday's demonstrations sent the Indonesian "
    "market tumbling. We have recovered a bit this week.\n\n"
    "Best regards,\nJames"
)


def _email(**kw) -> EmailMessage:
    base = dict(
        id="msg-1",
        subject="Pangolin Asia Fund News & August NAV",
        sender_name="James Hay",
        sender_email="james@pangolinfund.com",
        received="2025-09-05T08:55:02Z",
        body=LETTER_BODY,
        has_attachments=False,
    )
    base.update(kw)
    return EmailMessage(**base)


def _payload(**over) -> dict:
    out = {
        "is_manager_letter": True,
        "org": "Pangolin Asia",
        "fund": "Pangolin Asia Fund",
        "person": "James Hay",
        "source": "August 2025 monthly letter",
        "stance": "cautious",
        "themes": ["asean"],
        "quotes": [{
            "quote": "In August, the NAV of the Pangolin Asia Fund, net of all fees & "
                     "expenses, fell 0.88% to USD530.99.",
            "context": "August NAV move.",
        }],
        "reported_returns": [
            {"month": "2025-08", "pct": -0.88, "fund": "Pangolin Asia Fund", "basis": "net"}],
        "disclosed": [],
    }
    out.update(over)
    return out


# --------------------------------------------------------------------------- #
# Verbatim guard — the property the feature's credibility rests on
# --------------------------------------------------------------------------- #

def test_verbatim_quote_survives():
    result = extract_letter(FakeClient(_payload()), _email())
    assert result["is_manager_letter"]
    assert len(result["quotes"]) == 1
    assert result["quotes_dropped"] == 0


def test_paraphrased_quote_is_dropped():
    """A quote the manager never wrote must not reach the dashboard."""
    payload = _payload(quotes=[{
        "quote": "The fund declined slightly in August amid Indonesian unrest.",
        "context": "Paraphrase, not a real span.",
    }])
    result = extract_letter(FakeClient(payload), _email())
    assert result["quotes"] == []
    assert result["quotes_dropped"] == 1


def test_quote_matching_tolerates_typography_not_wording():
    """Smart quotes and rewrapping are fine; changed words are not."""
    body = "We have “stepped in” and\nadded risk where entry points look attractive."
    ok = _payload(quotes=[{"quote": 'We have "stepped in" and added risk where entry '
                                    'points look attractive.', "context": "x"}])
    result = extract_letter(FakeClient(ok), _email(body=body))
    assert len(result["quotes"]) == 1

    reworded = _payload(quotes=[{"quote": "We have stepped in and added risk where entry "
                                          "points seemed attractive.", "context": "x"}])
    assert extract_letter(FakeClient(reworded), _email(body=body))["quotes"] == []


def test_non_letter_is_gated_out():
    result = extract_letter(FakeClient({"is_manager_letter": False}), _email())
    assert result["is_manager_letter"] is False


def test_unparseable_output_does_not_raise():
    from tests.fakes import FakeResponse, FakeTextBlock

    client = FakeClient(handler=lambda **_k: FakeResponse(content=[FakeTextBlock(text="not json")]))
    assert extract_letter(client, _email())["is_manager_letter"] is False


def test_returns_must_name_a_real_month():
    """A malformed month would misalign a manager against the factor series."""
    payload = _payload(reported_returns=[
        {"month": "2025-08", "pct": -0.88, "fund": "", "basis": ""},
        {"month": "August 2025", "pct": 1.0, "fund": "", "basis": ""},
        {"month": "2025-13", "pct": 1.0, "fund": "", "basis": ""},
        {"month": "2025-08", "pct": "n/a", "fund": "", "basis": ""},
    ])
    months = [r["month"] for r in extract_letter(FakeClient(payload), _email())["reported_returns"]]
    assert months == ["2025-08"]


# --------------------------------------------------------------------------- #
# Sweep — never pay twice
# --------------------------------------------------------------------------- #

class FakeGraph:
    """Snapshot-mode connector: messages in, no attachment bytes."""

    def __init__(self, messages, live=False):
        self._messages = messages
        self.live = live
        self.list_calls = 0

    def attachments_available(self):
        return self.live

    def list_shared_inbox(self, top=40, days=7, start=None, end=None):
        self.list_calls += 1
        if start is None:
            return self._messages
        return [m for m in self._messages
                if start <= dt.datetime.fromisoformat(
                    m.received.replace("Z", "+00:00")).replace(tzinfo=None) <= end]


def test_sweep_extracts_then_never_re_reads(tmp_path):
    email = _email()
    graph = FakeGraph([email])
    client = FakeClient(_payload())

    first = sweep(client, graph, base=tmp_path, voices_base=tmp_path / "voices",
                  records_base=tmp_path / "records")
    assert first["letters"] == 1
    calls_after_first = len(client.calls)
    assert calls_after_first == 1

    second = sweep(client, graph, base=tmp_path, voices_base=tmp_path / "voices",
                   records_base=tmp_path / "records")
    assert second["considered"] == 0
    assert second["letters"] == 0
    assert len(client.calls) == calls_after_first, "a second sweep must cost nothing"


def test_sweep_records_skips_so_noise_is_not_re_read(tmp_path):
    graph = FakeGraph([_email(subject="Bloomberg newsletter")])
    client = FakeClient({"is_manager_letter": False})

    assert sweep(client, graph, base=tmp_path, voices_base=tmp_path / "v",
                 records_base=tmp_path / "r")["not_letters"] == 1
    assert sweep(client, graph, base=tmp_path, voices_base=tmp_path / "v",
                 records_base=tmp_path / "r")["considered"] == 0
    assert len(client.calls) == 1


def test_sweep_cap_bounds_a_cold_run(tmp_path):
    emails = [_email(id=f"m{i}", received="2025-09-0%dT08:00:00Z" % ((i % 5) + 1))
              for i in range(10)]
    graph = FakeGraph(emails)
    client = FakeClient(_payload())

    summary = sweep(client, graph, base=tmp_path, voices_base=tmp_path / "v",
                    records_base=tmp_path / "r", max_messages=3)
    assert summary["considered"] == 3
    assert summary["capped"] is True
    assert summary["remaining"] == 7
    assert len(client.calls) == 3


def test_sweep_queues_attachments_when_bytes_unavailable(tmp_path):
    email = _email(has_attachments=True, attachments=[
        EmailAttachment(id="a1", name="Fund Performance July 2026.xlsx",
                        content_type="application/vnd.ms-excel", size=40_000)])
    graph = FakeGraph([email])  # not live -> no bytes

    summary = sweep(FakeClient(_payload()), graph, base=tmp_path,
                    voices_base=tmp_path / "v", records_base=tmp_path / "r")
    assert summary["attachments_pending"] == 1
    assert summary["attachments_parsed"] == 0

    pending = mf.pending_attachments(mf.load(tmp_path))
    assert len(pending) == 1
    assert pending[0]["name"].endswith(".xlsx")


def test_sweep_disabled_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "INBOX_SIGNAL_ENABLED", False)
    client = FakeClient(_payload())
    assert sweep(client, FakeGraph([_email()]), base=tmp_path)["skipped"] is True
    assert client.calls == []


# --------------------------------------------------------------------------- #
# Store and periods
# --------------------------------------------------------------------------- #

def test_store_replaces_rather_than_duplicates(tmp_path):
    letter = {"message_id": "m1", "period": "p0", "date": "2025-09-05", "quotes": []}
    store.add_letter("Pangolin Asia", letter, tmp_path)
    store.add_letter("Pangolin Asia", {**letter, "stance": "negative"}, tmp_path)
    letters = store.load("Pangolin Asia", tmp_path)["letters"]
    assert len(letters) == 1
    assert letters[0]["stance"] == "negative"


def test_period_lookup():
    assert period_for("2025-09-03T10:00:00Z").key == "p0"
    assert period_for("2026-08-04T10:00:00Z").key == "p4"
    assert period_for("2025-10-15T10:00:00Z") is None
    assert period_for("") is None


def test_periods_do_not_overlap():
    for a, b in zip(PERIODS, PERIODS[1:]):
        assert a.end < b.start


# --------------------------------------------------------------------------- #
# The two shared-mailbox snapshots must coexist
# --------------------------------------------------------------------------- #

def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def _record(mid, received, subject="x"):
    return {"id": mid, "subject": subject, "sender_name": "A Manager",
            "sender_email": "a@manager.com", "received": received,
            "body": "body", "folder": "Inbox"}


def test_both_snapshots_are_read(tmp_path):
    """outlook-refresh and Inbox Signal write different files; both must count.

    They used to share one path, so whichever job ran last silently destroyed
    the other's data — an app open would replace a year of sampled
    correspondence with the last week, and the dashboard just went empty.
    """
    from src.connectors import graph as g

    _write(g.SHARED_INBOX_SNAPSHOT, [_record("recent-1", "2026-08-04T09:00:00Z", "recent")])
    _write(g.INBOX_SIGNAL_SNAPSHOT, [_record("sampled-1", "2025-09-03T09:00:00Z", "sampled")])

    conn = GraphConnector()
    p0, p4 = PERIODS[0], PERIODS[4]
    assert [m.id for m in conn.list_shared_inbox(start=p0.start, end=p0.end)] == ["sampled-1"]
    assert [m.id for m in conn.list_shared_inbox(start=p4.start, end=p4.end)] == ["recent-1"]


def test_snapshot_union_dedupes_on_id(tmp_path):
    from src.connectors import graph as g

    _write(g.SHARED_INBOX_SNAPSHOT, [_record("dup", "2026-08-04T09:00:00Z")])
    _write(g.INBOX_SIGNAL_SNAPSHOT, [_record("dup", "2026-08-04T09:00:00Z")])

    found = GraphConnector().list_shared_inbox(start=PERIODS[4].start, end=PERIODS[4].end)
    assert len(found) == 1


def test_utf8_snapshot_is_readable(tmp_path):
    """Real mail is full of smart quotes; read_text() defaults to cp1252 on
    Windows, and the resulting failure looks like a missing snapshot."""
    from src.connectors import graph as g

    _write(g.INBOX_SIGNAL_SNAPSHOT,
           [_record("u1", "2025-09-03T09:00:00Z", subject="Unitree’s robot “tea”")])
    found = GraphConnector().list_shared_inbox(start=PERIODS[0].start, end=PERIODS[0].end)
    assert len(found) == 1
    assert "’" in found[0].subject


# --------------------------------------------------------------------------- #
# Attachment classification
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name,expected", [
    ("Fund Track Record 2026.xlsx", att_mod.TRACK_RECORD),
    ("returns.csv", att_mod.TRACK_RECORD),
    ("20260807_MTD Performance Estimate.PDF", att_mod.TRACK_RECORD),
    ("August 2025 Letter to Shareholders.pdf", att_mod.DOCUMENT),
    ("Authorised Signatory List.pdf", att_mod.IGNORE),
    ("Capital Call Notice.pdf", att_mod.IGNORE),
    ("logo.png", att_mod.IGNORE),
])
def test_attachment_classification(name, expected):
    assert att_mod.classify(name, size=40_000) == expected


# --------------------------------------------------------------------------- #
# Factor correlation
# --------------------------------------------------------------------------- #

def test_missing_keys_raise_rather_than_faking(monkeypatch):
    monkeypatch.setattr(config, "FRED_API_KEY", None)
    monkeypatch.setattr(config, "POLYGON_API_KEY", None)
    with pytest.raises(fc.FactorDataUnavailable):
        fc.get_factor_series(force_refresh=True)


def test_monthly_returns_drop_the_base_month():
    closes = [("2025-06", 100.0), ("2025-07", 110.0), ("2025-08", 99.0)]
    assert fc._monthly_returns(closes) == {"2025-07": 10.0, "2025-08": -10.0}


def test_correlation_aligns_on_month_not_position():
    """Offset windows must line up by date, or the numbers are quietly wrong."""
    manager = {"2025-01": 1.0, "2025-02": 2.0, "2025-03": 3.0, "2025-04": 4.0}
    factor = {"2024-11": 9.0, "2024-12": 9.0,
              "2025-01": 2.0, "2025-02": 4.0, "2025-03": 6.0, "2025-04": 8.0}
    out = fc.correlate(manager, factor, minimum=4)
    assert out["n"] == 4
    assert out["r"] == 1.0
    assert out["from"] == "2025-01" and out["to"] == "2025-04"


def test_thin_overlap_returns_none_not_a_number():
    manager = {"2025-01": 1.0, "2025-02": -2.0, "2025-03": 3.0}
    factor = {"2025-01": 2.0, "2025-02": -1.0, "2025-03": 5.0}
    out = fc.correlate(manager, factor)  # default minimum is 12
    assert out["r"] is None
    assert out["n"] == 3


def test_flat_series_is_undefined_not_zero():
    manager = {f"2025-{m:02d}": 1.0 for m in range(1, 13)}
    factor = {f"2025-{m:02d}": float(m) for m in range(1, 13)}
    assert fc.correlate(manager, factor)["r"] is None


def test_quarterly_record_is_excluded_with_a_reason(tmp_path, monkeypatch):
    record = TrackRecord(manager="PE Manager", fund="PE Fund III", vehicle_type="private",
                         periods=[{"period": "2025-Q1", "return_pct": 4.0},
                                  {"period": "2025-Q2", "return_pct": 2.0}])
    track_record_store.save(record, tmp_path)
    monkeypatch.setattr(fc, "get_factor_series", lambda: {f["id"]: {} for f in fc.FACTORS})

    matrix = fc.build_matrix(records_base=tmp_path)
    assert matrix["managers"] == []
    assert len(matrix["excluded"]) == 1
    assert "quarterly" in matrix["excluded"][0]["reason"]


def test_views_report_absence_rather_than_hiding_it(tmp_path):
    """Silence and neutrality must stay distinguishable."""
    from src.features.inbox_signal import views

    letters = [
        {"org": "Alpha", "period": "p0", "date": "2025-09-02", "stance": "constructive",
         "themes": ["ai"], "quotes": [{"quote": "q", "context": ""}], "reported_returns": []},
        {"org": "Alpha", "period": "p4", "date": "2026-08-01", "stance": "neutral",
         "themes": ["ai"], "quotes": [], "reported_returns": []},
        {"org": "Beta", "period": "p0", "date": "2025-09-03", "stance": "cautious",
         "themes": ["china"], "quotes": [], "reported_returns": []},
    ]
    rows = {r["org"]: r["stances"] for r in views.stance_by_org(letters)}
    # Alpha wrote in p0 and p4 and was silent between; Beta only ever in p0.
    assert rows["Alpha"] == ["constructive", None, None, None, "neutral"]
    assert rows["Beta"][0] == "cautious"
    assert rows["Beta"][4] is None, "silence must not be coerced into a stance"

    themes = {t["id"]: t for t in views.themes_view(letters)}
    assert themes["ai"]["series"] == [1, 0, 0, 0, 1]
    assert themes["china"]["series"] == [1, 0, 0, 0, 0]
    # A breakdown, never a single verdict: letter stance is the manager's
    # overall posture, so collapsing it yields "AI unwind - Constructive".
    assert themes["ai"]["stances"] == {"constructive": 1, "neutral": 1}
    assert "stance" not in themes["ai"]


def test_monitor_flags_a_silent_drawdown(tmp_path):
    from src.features.inbox_signal import views

    letters = [{
        "org": "Tees River", "period": "p4", "date": "2026-08-01", "stance": "neutral",
        "themes": [], "quotes": [], "source": "NAV estimate",
        "reported_returns": [{"month": "2026-07", "pct": -14.7, "fund": "", "basis": ""}],
    }]
    items = views.monitor_view(letters, {"messages": {}})
    drawdown = [i for i in items if i["category"] == "Silent on a drawdown"]
    assert len(drawdown) == 1
    assert drawdown[0]["severity"] == "urgent"
    assert "-14.70%" in drawdown[0]["headline"]


def test_monitor_flags_unreadable_attachments(tmp_path):
    from src.features.inbox_signal import views

    data = mf.load(tmp_path)
    mf.record_message(data, "m1", status=mf.DONE, period="p4", org="New Holland",
                      attachments={"a:1": {"status": mf.PENDING, "name": "MTD.pdf"}})
    items = views.monitor_view([], data)
    assert any(i["category"] == "Numbers nobody has read" for i in items)


def test_monthly_record_is_correlated(tmp_path, monkeypatch):
    months = {f"2025-{m:02d}": float(m % 5) - 2 for m in range(1, 13)}
    record = TrackRecord(manager="HF", fund="HF Master", vehicle_type="public",
                         periods=[{"period": k, "return_pct": v} for k, v in months.items()])
    track_record_store.save(record, tmp_path)
    monkeypatch.setattr(fc, "get_factor_series",
                        lambda: {f["id"]: {k: v * 1.5 for k, v in months.items()}
                                 for f in fc.FACTORS})

    matrix = fc.build_matrix(records_base=tmp_path)
    assert len(matrix["managers"]) == 1
    row = matrix["managers"][0]
    assert row["org"] == "HF Master"
    assert row["months"] == 12
    assert row["by_factor"]["ai"]["r"] == 1.0
    assert matrix["counts"]["qualifying"] == 1
