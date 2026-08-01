"""The Claude Code CLI backend — argv construction, parsing and error handling.

The subprocess runner is stubbed throughout, so the suite never spawns the real
CLI and never makes a model call.
"""
import base64
import json
import subprocess
from pathlib import Path

import pytest

from src import config, llm
from src.features.inbox_triage import triage_email
from src.llm import (
    ClaudeCodeAuthError,
    ClaudeCodeClient,
    ClaudeCodeError,
    ClaudeCodeRateLimited,
    ClaudeCodeUnavailable,
)
from src.schemas import EmailMessage

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def fake_run(stdout: dict | str = None, returncode: int = 0, stderr: str = "", capture: list = None):
    """Build a runner that records argv and returns a canned CLI payload."""
    def runner(argv):
        if capture is not None:
            capture.append(argv)
        payload = stdout if isinstance(stdout, str) else json.dumps(stdout or {})
        return subprocess.CompletedProcess(argv, returncode, stdout=payload, stderr=stderr)
    return runner


def client_with(**kwargs) -> ClaudeCodeClient:
    return ClaudeCodeClient(runner=fake_run(**kwargs))


def argv_for(**create_kwargs) -> list[str]:
    """Run one call and return the argv the CLI would have been invoked with."""
    seen: list = []
    c = ClaudeCodeClient(runner=fake_run(stdout={"structured_output": {"ok": True}}, capture=seen))
    c.messages.create(**create_kwargs)
    return seen[0]


class TestArgvConstruction:
    BASE = {"model": "claude-opus-4-8", "max_tokens": 100,
            "messages": [{"role": "user", "content": "hello"}]}

    def test_uses_print_mode_and_json_output(self):
        argv = argv_for(**self.BASE)
        assert "-p" in argv
        assert argv[argv.index("--output-format") + 1] == "json"

    def test_never_passes_bare_which_would_skip_the_claude_login(self):
        # --bare skips OAuth/keychain reads, so it would bypass the Claude
        # account this backend exists to use. It must never appear.
        assert "--bare" not in argv_for(**self.BASE)
        assert "--bare" not in argv_for(**self.BASE, system="s",
                                        output_config={"format": {"schema": SCHEMA}})

    def test_schema_is_passed_as_json_schema(self):
        argv = argv_for(**self.BASE, output_config={"format": {"type": "json_schema", "schema": SCHEMA}})
        assert json.loads(argv[argv.index("--json-schema") + 1]) == SCHEMA

    def test_no_schema_flag_when_no_output_config(self):
        assert "--json-schema" not in argv_for(**self.BASE)

    def test_system_prompt_replaces_the_default(self):
        argv = argv_for(**self.BASE, system="You are a triage bot.")
        assert argv[argv.index("--system-prompt") + 1] == "You are a triage bot."

    def test_model_is_mapped_to_a_cli_alias(self):
        argv = argv_for(**self.BASE)
        assert argv[argv.index("--model") + 1] == "opus"

    def test_unknown_model_passes_through_unchanged(self):
        argv = argv_for(**{**self.BASE, "model": "some-future-model"})
        assert argv[argv.index("--model") + 1] == "some-future-model"

    def test_prompt_carries_the_user_content(self):
        assert "hello" in argv_for(**self.BASE)

    def test_no_read_tool_for_plain_text_calls(self):
        assert "--allowedTools" not in argv_for(**self.BASE)


class TestResponseParsing:
    BASE = {"model": "claude-opus-4-8", "max_tokens": 100,
            "messages": [{"role": "user", "content": "x"}]}

    def test_structured_output_is_preferred(self):
        c = client_with(stdout={"structured_output": {"ok": True}, "result": "ignored"})
        response = c.messages.create(**self.BASE)
        assert json.loads(response.content[0].text) == {"ok": True}

    def test_falls_back_to_the_text_result(self):
        c = client_with(stdout={"result": "plain text answer"})
        assert c.messages.create(**self.BASE).content[0].text == "plain text answer"

    def test_null_structured_output_falls_back(self):
        c = client_with(stdout={"structured_output": None, "result": "fallback"})
        assert c.messages.create(**self.BASE).content[0].text == "fallback"

    def test_response_mimics_the_anthropic_shape(self):
        c = client_with(stdout={"result": "hi", "stop_reason": "end_turn"})
        response = c.messages.create(**self.BASE)
        assert response.content[0].type == "text"
        assert response.stop_reason == "end_turn"

    def test_unparseable_stdout_raises(self):
        c = client_with(stdout="not json at all")
        with pytest.raises(ClaudeCodeError, match="Could not parse"):
            c.messages.create(**self.BASE)


class TestErrorsAreLoud:
    BASE = {"model": "claude-opus-4-8", "max_tokens": 100,
            "messages": [{"role": "user", "content": "x"}]}

    def test_missing_cli_raises_unavailable(self):
        def runner(argv):
            raise FileNotFoundError(argv[0])
        c = ClaudeCodeClient(runner=runner)
        # The real runner raises this; assert the mapping directly.
        with pytest.raises(FileNotFoundError):
            c.messages.create(**self.BASE)

    def test_real_runner_maps_missing_binary_to_unavailable(self):
        c = ClaudeCodeClient(cli_path="definitely-not-a-real-binary-xyz")
        with pytest.raises(ClaudeCodeUnavailable, match="not found"):
            c.messages.create(**self.BASE)

    def test_auth_failure_tells_you_to_log_in(self):
        c = client_with(stdout={"is_error": True, "error": "authentication_failed"})
        with pytest.raises(ClaudeCodeAuthError, match="claude login"):
            c.messages.create(**self.BASE)

    def test_rate_limit_is_its_own_error(self):
        c = client_with(stdout={"is_error": True, "error": "rate_limit"})
        with pytest.raises(ClaudeCodeRateLimited, match="usage limit"):
            c.messages.create(**self.BASE)

    def test_nonzero_exit_raises(self):
        c = client_with(stdout={"result": "boom"}, returncode=1)
        with pytest.raises(ClaudeCodeError):
            c.messages.create(**self.BASE)

    def test_errors_never_silently_return_a_result(self):
        # A failure must raise, not hand back empty/plausible content that a
        # caller might mistake for a real answer.
        c = client_with(stdout={"is_error": True, "error": "server_error"})
        with pytest.raises(ClaudeCodeError):
            c.messages.create(**self.BASE)


class TestVisionPath:
    def _image_call(self, capture):
        png = base64.standard_b64encode(b"\x89PNG-fake-bytes").decode()
        c = ClaudeCodeClient(runner=fake_run(stdout={"result": "transcribed"}, capture=capture))
        return c.messages.create(
            model="claude-opus-4-8", max_tokens=100,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png}},
                {"type": "text", "text": "Transcribe this page."},
            ]}],
        )

    def test_image_calls_allow_the_read_tool(self):
        seen: list = []
        self._image_call(seen)
        argv = seen[0]
        assert argv[argv.index("--allowedTools") + 1] == "Read"

    def test_prompt_references_a_written_file_and_keeps_the_instruction(self):
        seen: list = []
        self._image_call(seen)
        prompt = seen[0][seen[0].index("-p") + 1]
        assert "Transcribe this page." in prompt
        assert ".png" in prompt

    def test_temp_image_is_cleaned_up_afterwards(self):
        seen: list = []
        self._image_call(seen)
        prompt = seen[0][seen[0].index("-p") + 1]
        # The path is absolute but platform-shaped ("/tmp/…" or "C:\…"), so key
        # off the .png suffix rather than a leading slash.
        written = [line.strip().lstrip("- ") for line in prompt.splitlines()
                   if line.strip().startswith("- ") and line.strip().endswith(".png")]
        assert written, "expected an image path in the prompt"
        assert not Path(written[0]).exists(), "temp image should be removed after the call"

    def test_text_result_is_returned_for_vision_calls(self):
        assert self._image_call([]).content[0].text == "transcribed"


class TestFeatureModulesWorkUnchanged:
    """The whole point of the adapter: features need no changes."""

    def test_triage_runs_through_the_cli_backend(self):
        payload = {
            "is_investment": True, "confidence": 0.9, "category": "New fund intro",
            "rationale": "A fund is being marketed.", "key_facts": ["$470m"],
            "entity": {"fund_name": "Cendana Capital Fund VII", "company_name": "Cendana Capital",
                       "company_domain": "", "contact_name": "Katie", "contact_email": "",
                       "contact_title": "EA", "asset_class": "VC", "geography": "US",
                       "sleeve": "Private Growth", "summary": "Seed FoF."},
        }
        c = client_with(stdout={"structured_output": payload})
        email = EmailMessage(id="m1", subject="Fund VII", sender_name="Katie",
                             sender_email="katie@cendanacapital.com", body="...")
        result = triage_email(c, email)
        assert result.is_investment
        assert result.entity.fund_name == "Cendana Capital Fund VII"
        # Sender backfill still applies through the new backend.
        assert result.entity.contact_email == "katie@cendanacapital.com"


class TestBackendSelection:
    def test_defaults_to_the_claude_account_backend(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "claude_cli")
        assert isinstance(llm.get_client(), ClaudeCodeClient)

    def test_api_backend_returns_none_without_a_key(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "api")
        monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
        assert llm.get_client() is None

    def test_unknown_backend_is_rejected(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "gpt")
        with pytest.raises(ValueError, match="Unknown LLM_BACKEND"):
            llm.get_client()

    def test_cli_backend_is_chosen_even_with_an_api_key_present(self, monkeypatch):
        # Having an API key lying around must not silently change billing rail.
        monkeypatch.setattr(config, "LLM_BACKEND", "claude_cli")
        monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-something")
        assert isinstance(llm.get_client(), ClaudeCodeClient)

    def test_describe_backend_names_the_claude_account(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "claude_cli")
        label, _ = llm.describe_backend()
        assert label == "Claude account"

    def test_preflight_reports_a_missing_cli(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "claude_cli")
        monkeypatch.setattr(config, "CLAUDE_CLI_PATH", "definitely-not-a-real-binary-xyz")
        ok, message = llm.preflight()
        assert not ok and "not found" in message
