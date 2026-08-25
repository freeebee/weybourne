"""Work nobody asked for stands down while a meeting is recording.

Transcription is soft real time on this one machine (see src/features/stt.py).
Heavy background work is pure Python, holds the GIL and competes with whisper
for the same cores: on 17 Aug 2026 the inbox-signal sweep fired on app open
during a meeting and the transcript's chunk gaps went 20s to 4m38s before
stopping altogether.

The line drawn here is automatic vs asked-for. A sweep that fires because the
app happened to open can wait; a sweep the investor clicked cannot be quietly
refused.
"""
import pytest

from api import main


@pytest.fixture(autouse=True)
def quiet():
    """No recording in progress unless a test says so."""
    main._clear_live_recording()
    yield
    main._clear_live_recording()


class TestTheHeartbeat:
    def test_nothing_recording_by_default(self):
        assert main.live_recording_active() is False

    def test_a_heartbeat_marks_a_recording_live(self):
        main._mark_live_recording()
        assert main.live_recording_active() is True

    def test_finishing_clears_it_immediately(self):
        main._mark_live_recording()
        main._clear_live_recording()
        assert main.live_recording_active() is False

    def test_it_lapses_on_a_recording_that_never_said_it_stopped(self, monkeypatch):
        """A crashed tab sends no /api/live/finish. Deferring background work
        forever on the strength of one old chunk would be worse than the bug
        this guard exists to fix."""
        main._mark_live_recording()
        t = main.time.monotonic() + main.LIVE_RECORDING_TTL + 1
        monkeypatch.setattr(main.time, "monotonic", lambda: t)
        assert main.live_recording_active() is False


class TestAutomaticJobsDeferWhileRecording:
    def test_the_app_open_sweep_defers(self):
        main._mark_live_recording()
        assert "deferred" in main.start_inbox_signal_job(auto=True)

    def test_the_app_open_week_in_review_defers(self):
        main._mark_live_recording()
        assert "deferred" in main.start_week_in_review_job(auto=True)

    def test_an_automatic_sweep_runs_when_nothing_is_recording(self, monkeypatch):
        started = []
        monkeypatch.setattr(main, "_client", lambda *a, **k: object())
        monkeypatch.setattr(main, "_start_job",
                            lambda kind, label, work: started.append(kind) or {"kind": kind})
        monkeypatch.setattr(main, "_job_summary", lambda j: j)
        main.start_inbox_signal_job(auto=True)
        assert started == ["inbox-signal"]

    def test_a_sweep_the_user_clicked_runs_even_mid_meeting(self, monkeypatch):
        """The page's own sweep button is an instruction, not a warm-up."""
        started = []
        monkeypatch.setattr(main, "_client", lambda *a, **k: object())
        monkeypatch.setattr(main, "_start_job",
                            lambda kind, label, work: started.append(kind) or {"kind": kind})
        monkeypatch.setattr(main, "_job_summary", lambda j: j)
        main._mark_live_recording()
        main.start_inbox_signal_job(auto=False)
        assert started == ["inbox-signal"]

    def test_the_half_hourly_outlook_refresh_defers(self, monkeypatch):
        """The 24 Aug 2026 reference call lost its 14:29 sentences to the
        14:28 auto-refresh — the daemon's tick now stands down and retries
        after the meeting instead."""
        started = []
        monkeypatch.setattr(main, "start_outlook_refresh",
                            lambda: started.append("outlook-refresh"))
        main._mark_live_recording()
        assert main._outlook_auto_tick() == "deferred"
        assert started == []

    def test_the_outlook_refresh_runs_once_the_recording_ends(self, monkeypatch):
        started = []
        monkeypatch.setattr(main, "start_outlook_refresh",
                            lambda: started.append("outlook-refresh"))
        assert main._outlook_auto_tick() == "started"
        assert started == ["outlook-refresh"]

    def test_the_outlook_refresh_never_doubles_up(self, monkeypatch):
        monkeypatch.setattr(main, "start_outlook_refresh",
                            lambda: pytest.fail("must not start a second refresh"))
        monkeypatch.setitem(main._JOBS, "j1",
                            {"kind": "outlook-refresh", "status": "running"})
        assert main._outlook_auto_tick() == "already-running"

    def test_the_felix_topup_defers(self, monkeypatch):
        """A felix scan is the heaviest automatic work on the box (a 5-10
        minute crawl) — it must never start itself mid-meeting."""
        monkeypatch.setattr(main, "complex_case_backlog",
                            lambda: pytest.fail("gate must fire before the backlog scan"))
        monkeypatch.setattr(main, "_start_job",
                            lambda *a, **k: pytest.fail("must not start a run"))
        main._mark_live_recording()
        main._felix_topup_if_low()

    def test_the_felix_topup_still_runs_when_nothing_records(self, monkeypatch):
        started = []
        monkeypatch.setitem(main._FELIX_TOPUP, "last", 0.0)
        monkeypatch.setattr(main, "complex_case_backlog", lambda: 0)
        monkeypatch.setattr(main, "_client", lambda *a, **k: object())
        monkeypatch.setattr(main, "_start_job",
                            lambda kind, label, work: started.append(kind) or {"kind": kind})
        monkeypatch.setattr(main, "_felix_eta", lambda j: j)
        main._felix_topup_if_low()
        assert started == ["felix"]


class TestTheStatusEndpoint:
    """GET /api/live/recording-active: the heartbeat, readable from outside.

    On 18 Aug 2026 a reload-safety gate inferred "no recording" from
    data/live_sessions mtimes while a meeting heartbeat through
    data/transcripts; the uvicorn reload and test runs that followed cost
    that meeting audio. File mtimes are a guess — this endpoint is the
    answer."""

    def test_reports_quiet(self):
        assert main.live_recording_status() == {"active": False}

    def test_reports_a_live_recording(self):
        main._mark_live_recording()
        assert main.live_recording_status() == {"active": True}
