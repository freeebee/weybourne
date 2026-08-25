"""A prep is two purchases, and one failing must not discard the other.

The briefing and the preference screen run side by side. The briefing is the
long pole — twenty-six schema fields, several of them per-deal tables — and
`max_tokens` cannot bound it on the CLI backend, so it is the one that hits the
timeout. Letting its exception propagate threw away a screen that had been
sitting finished beside it for minutes, and reported the whole prep as failed.
"""
import pytest

from src import config, llm


class TestTheBriefingGetsItsOwnCeiling:
    def test_the_briefing_ceiling_is_longer_than_the_shared_one(self):
        # The shared ceiling stays tight enough to catch a hung triage; only
        # the call that legitimately writes for many minutes is loosened.
        assert config.CLAUDE_BRIEFING_TIMEOUT > config.CLAUDE_CLI_TIMEOUT

    def test_a_client_takes_the_override(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "claude_cli")
        client = llm.get_client(timeout=1234)
        assert client.timeout == 1234

    def test_zero_keeps_the_configured_default(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "claude_cli")
        assert llm.get_client().timeout == config.CLAUDE_CLI_TIMEOUT
        assert llm.get_client(timeout=0).timeout == config.CLAUDE_CLI_TIMEOUT

    def test_the_override_does_not_disturb_effort_or_pool(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "claude_cli")
        client = llm.get_client(pool="live-tidy", effort="low", timeout=99)
        assert (client.effort, client.timeout) == ("low", 99)


class TestOnePartFailing:
    """The collection logic, exercised directly on futures.

    The endpoint body is not importable in isolation, so this pins the rule it
    implements: gather both, keep what arrived, and only fail when nothing did.
    """

    @staticmethod
    def _collect(results: dict):
        from concurrent.futures import ThreadPoolExecutor

        def make(value):
            def run():
                if isinstance(value, Exception):
                    raise value
                return value
            return run

        out, failed, first = {}, {}, None
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {k: pool.submit(make(v)) for k, v in results.items()}
            for key, future in futures.items():
                try:
                    out[key] = future.result()
                except Exception as e:  # noqa: BLE001
                    failed[key] = str(e) or e.__class__.__name__
                    first = first or e
        return out, failed, first

    def test_a_timed_out_briefing_keeps_the_finished_screen(self):
        out, failed, _ = self._collect({
            "screen": {"overall_fit": "possible"},
            "briefing": llm.ClaudeCodeError("Claude Code CLI timed out after 600s."),
        })
        assert out["screen"] == {"overall_fit": "possible"}
        assert "briefing" in failed and "timed out" in failed["briefing"]
        assert "briefing" not in out

    def test_a_failed_screen_keeps_the_briefing(self):
        out, failed, _ = self._collect({
            "screen": llm.ClaudeCodeError("boom"),
            "briefing": {"entity": "Acme"},
        })
        assert out["briefing"] == {"entity": "Acme"}
        assert list(failed) == ["screen"]

    def test_both_failing_surfaces_the_real_error(self):
        # Saving an empty prep that looks finished would be worse than failing.
        out, failed, first = self._collect({
            "screen": llm.ClaudeCodeAuthError("not signed in"),
            "briefing": llm.ClaudeCodeError("timed out"),
        })
        assert out == {}
        assert len(failed) == 2
        assert isinstance(first, Exception)
        with pytest.raises(llm.ClaudeCodeAuthError):
            raise first

    def test_both_succeeding_records_no_failure(self):
        out, failed, _ = self._collect({"screen": {"a": 1}, "briefing": {"b": 2}})
        assert failed == {}
        assert set(out) == {"screen", "briefing"}
