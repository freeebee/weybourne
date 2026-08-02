"""Model backends: the Claude Code CLI (your Claude account) or the Anthropic API.

Why this exists
---------------
The app's AI calls can run on either billing rail:

* ``claude_cli`` (default) — shells out to the **Claude Code CLI**, which runs on
  whatever ``claude login`` established, i.e. your **Claude account**. No
  Anthropic API key is involved.
* ``api`` — the ordinary ``anthropic.Anthropic()`` client, billed to an Anthropic
  **API** account via ``ANTHROPIC_API_KEY``.

There is no way to point the ``anthropic`` SDK at a Claude subscription: the two
are separate billing rails. Driving the CLI is the supported route, which is what
``ClaudeCodeClient`` does.

How the adapter works
---------------------
Every model call in this codebase has the same shape::

    client.messages.create(model=, max_tokens=, system=, output_config=, messages=)
    -> response.content[i].text / response.stop_reason

``ClaudeCodeClient`` presents exactly that surface, so swapping the backend needs
no changes in the feature modules (and the test fakes keep working unchanged).

Under the hood a call becomes::

    claude -p <content> --output-format json --system-prompt <system> \
           --json-schema <schema> --model <alias>

``--json-schema`` gives real schema-validated output in the response's
``structured_output`` field, which maps directly onto the API's
``output_config={"format": {"type": "json_schema", ...}}``.

Two things are deliberate and load-bearing:

* **``--bare`` is never passed.** It is the faster startup path, but it "skips
  OAuth and keychain reads" — it would bypass your Claude login and fall back to
  an API key, defeating the whole point.
* **Failures are loud.** A missing CLI, a missing login, or an exhausted rate
  limit each raise a specific error. Nothing here silently falls back to the API,
  because silently switching billing rails is worse than stopping.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src import config


# --------------------------------------------------------------------------- #
# Errors — each one actionable, none of them a silent fallback
# --------------------------------------------------------------------------- #

class ClaudeCodeError(RuntimeError):
    """Base class for Claude Code CLI backend failures."""


class ClaudeCodeUnavailable(ClaudeCodeError):
    """The CLI isn't installed or isn't on PATH."""


class ClaudeCodeAuthError(ClaudeCodeError):
    """The CLI is installed but not logged in (or the login has expired)."""


class ClaudeCodeRateLimited(ClaudeCodeError):
    """The Claude account's usage limit has been reached."""


# --------------------------------------------------------------------------- #
# Response objects mimicking the Anthropic SDK's shape
# --------------------------------------------------------------------------- #

@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _Response:
    content: list[_TextBlock] = field(default_factory=list)
    stop_reason: str = "end_turn"


# --------------------------------------------------------------------------- #
# Claude Code CLI backend
# --------------------------------------------------------------------------- #

# Map the configured model names onto CLI --model aliases. The CLI accepts
# aliases and full ids; anything unrecognised is passed straight through.
_MODEL_ALIASES = {
    "claude-opus-4-8": "opus",
    "claude-opus-5": "opus",
    "claude-sonnet-5": "sonnet",
    "claude-haiku-4-5": "haiku",
    "claude-haiku-4-5-20251001": "haiku",
}


def _cli_model(model: Optional[str]) -> Optional[str]:
    if not model:
        return None
    return _MODEL_ALIASES.get(model, model)


def _scratch_dir() -> Path:
    """An empty directory to run the CLI from.

    The CLI is run without ``--bare`` so it keeps OAuth (your Claude login), but
    that also means it auto-discovers CLAUDE.md, .mcp.json, hooks and skills from
    its working directory. Running from an empty scratch directory keeps that
    discovery from loading a pile of irrelevant context into every call.
    """
    path = Path(config.CLAUDE_CLI_SCRATCH_DIR or (Path(tempfile.gettempdir()) / "weybourne-llm"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _extract_prompt(messages: list[dict]) -> tuple[str, list[Path]]:
    """Flatten message content into a prompt string.

    Returns ``(prompt, image_paths)``. Image blocks (used by the PDF OCR path)
    cannot be inlined into a CLI argument, so they are written to temp files and
    referenced by path; the caller then allows the Read tool so Claude can open
    them.
    """
    parts: list[str] = []
    images: list[Path] = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            parts.append(content)
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "image":
                images.append(_write_image(block))
    prompt = "\n\n".join(p for p in parts if p)
    if images:
        listed = "\n".join(f"- {p}" for p in images)
        prompt = (
            f"Read the following image file(s) and use them as the input for this task:\n"
            f"{listed}\n\n{prompt}"
        )
    return prompt, images


def _write_image(block: dict) -> Path:
    """Persist a base64 image block to a temp PNG the CLI can read."""
    import base64

    source = block.get("source", {}) or {}
    data = source.get("data", "")
    media_type = source.get("media_type", "image/png")
    suffix = "." + media_type.split("/")[-1]
    fd, name = tempfile.mkstemp(prefix="weybourne-page-", suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(base64.standard_b64decode(data))
    return Path(name)


def _classify_error(payload: dict, stderr: str) -> ClaudeCodeError:
    """Turn a CLI failure into the most actionable exception available."""
    blob = f"{json.dumps(payload)} {stderr}".lower()
    if "authentication_failed" in blob or "oauth" in blob or "not logged in" in blob:
        return ClaudeCodeAuthError(
            "Claude Code is not logged in. Run `claude login` in a terminal, then retry. "
            "(Set LLM_BACKEND=api to use an Anthropic API key instead.)"
        )
    if "rate_limit" in blob or "usage limit" in blob:
        return ClaudeCodeRateLimited(
            "Your Claude account's usage limit has been reached. Wait for it to reset, "
            "or set LLM_BACKEND=api to use an Anthropic API key instead."
        )
    detail = payload.get("result") or payload.get("error") or stderr.strip() or "unknown error"
    return ClaudeCodeError(f"Claude Code CLI call failed: {detail}")


class _Messages:
    def __init__(self, client: "ClaudeCodeClient"):
        self._client = client

    def create(self, **kwargs: Any) -> _Response:
        return self._client._create(**kwargs)


class ClaudeCodeClient:
    """Anthropic-shaped client backed by the Claude Code CLI (your Claude account)."""

    def __init__(self, cli_path: Optional[str] = None, timeout: Optional[int] = None,
                 runner=None):
        self.cli_path = cli_path or config.CLAUDE_CLI_PATH
        self.timeout = timeout or config.CLAUDE_CLI_TIMEOUT
        # Injectable for tests so the suite never spawns the real CLI.
        self._runner = runner or self._run_subprocess
        self.messages = _Messages(self)

    # -- process execution ------------------------------------------------ #
    def _run_subprocess(self, argv: list[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                argv,
                capture_output=True,
                text=True,
                # The CLI emits UTF-8; without this Windows decodes as cp1252
                # and em-dashes arrive as "â€”" in every downstream surface.
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                stdin=subprocess.DEVNULL,  # else the CLI waits ~3s for stdin
                cwd=str(_scratch_dir()),
            )
        except FileNotFoundError as e:
            raise ClaudeCodeUnavailable(
                f"Claude Code CLI not found at {self.cli_path!r}. Install Claude Code and "
                "ensure it is on PATH (or set CLAUDE_CLI_PATH). "
                "(Set LLM_BACKEND=api to use an Anthropic API key instead.)"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise ClaudeCodeError(
                f"Claude Code CLI timed out after {self.timeout}s."
            ) from e

    # -- the adapter ------------------------------------------------------ #
    def _build_argv(self, system: Optional[str], prompt: str, schema: Optional[dict],
                    model: Optional[str], needs_read: bool) -> list[str]:
        # A prompt that begins with "-" (e.g. a markdown bullet list) would be
        # parsed by the CLI's option parser as an unknown flag. A leading
        # newline is invisible to the model and defuses it.
        if prompt.startswith("-"):
            prompt = "\n" + prompt
        argv = [self.cli_path, "-p", prompt, "--output-format", "json"]
        # NOTE: --bare is deliberately never passed; it skips OAuth and would
        # bypass the Claude account login this backend exists to use.
        if system:
            argv += ["--system-prompt", system]
        if schema:
            argv += ["--json-schema", json.dumps(schema)]
        cli_model = _cli_model(model)
        if cli_model:
            argv += ["--model", cli_model]
        if needs_read:
            argv += ["--allowedTools", "Read"]
        return argv

    def _create(self, **kwargs: Any) -> _Response:
        messages = kwargs.get("messages", [])
        system = kwargs.get("system")
        output_config = kwargs.get("output_config") or {}
        schema = ((output_config.get("format") or {}).get("schema"))

        prompt, images = _extract_prompt(messages)
        argv = self._build_argv(system, prompt, schema, kwargs.get("model"), bool(images))

        try:
            completed = self._runner(argv)
            stdout = (completed.stdout or "").strip()
            stderr = completed.stderr or ""

            try:
                payload = json.loads(stdout) if stdout else {}
            except json.JSONDecodeError:
                raise ClaudeCodeError(
                    f"Could not parse Claude Code CLI output: {stdout[:400] or stderr[:400]}"
                ) from None

            if completed.returncode != 0 or payload.get("is_error"):
                raise _classify_error(payload, stderr)

            # Prefer the schema-validated object; fall back to the text result.
            if "structured_output" in payload and payload["structured_output"] is not None:
                text = json.dumps(payload["structured_output"])
            else:
                text = payload.get("result", "")

            return _Response(content=[_TextBlock(text=text)],
                             stop_reason=payload.get("stop_reason") or "end_turn")
        finally:
            for path in images:
                path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Backend selection
# --------------------------------------------------------------------------- #

def get_client():
    """Return the configured model client, or None if none is usable.

    Returning None means "no AI backend available" and the UI shows demo mode.
    It never means "quietly billed something else": selecting the CLI backend and
    failing to reach it raises rather than falling back to the API.
    """
    backend = (config.LLM_BACKEND or "claude_cli").strip().lower()

    if backend == "api":
        if not config.anthropic_configured():
            return None
        import anthropic

        return anthropic.Anthropic()

    if backend in ("claude_cli", "claude-cli", "cli", "claude"):
        return ClaudeCodeClient()

    raise ValueError(
        f"Unknown LLM_BACKEND {backend!r}. Use 'claude_cli' (your Claude account) or 'api'."
    )


def describe_backend() -> tuple[str, str]:
    """(label, detail) describing the active backend, for the UI status strip."""
    backend = (config.LLM_BACKEND or "claude_cli").strip().lower()
    if backend == "api":
        return ("Anthropic API", "live" if config.anthropic_configured() else "no API key")
    return ("Claude account", f"via Claude Code CLI ({config.CLAUDE_CLI_PATH})")


def preflight() -> tuple[bool, str]:
    """Cheap check that the active backend looks usable. (ok, message)."""
    backend = (config.LLM_BACKEND or "claude_cli").strip().lower()
    if backend == "api":
        return (config.anthropic_configured(),
                "ANTHROPIC_API_KEY is set" if config.anthropic_configured()
                else "ANTHROPIC_API_KEY is not set")

    import shutil

    resolved = shutil.which(config.CLAUDE_CLI_PATH)
    if not resolved:
        return (False,
                f"Claude Code CLI not found ({config.CLAUDE_CLI_PATH}). Install it and run "
                "`claude login`, or set LLM_BACKEND=api.")
    return (True, f"Claude Code CLI found at {resolved}")
