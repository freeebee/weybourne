"""Persistent Claude Code CLI sessions for the live-meeting loop.

Every other caller in this app (src/llm.py's ``ClaudeCodeClient``) gets a
fresh ``claude -p`` subprocess per call. That's the right shape across
FEATURES — prep, triage and Felix each have their own fixed system prompt,
so one process can never correctly serve two of them; only a dedicated
session per feature (like this module gives tidy and read) would even be
sound. It is the wrong shape WITHIN a live meeting specifically: tidy fires
every ~8s and read every 30-60s, for the same meeting, for as long as it
runs, and each fresh spawn pays ~5-6s of CLI bootstrap (feature-flag fetch,
connector list, a hidden session-title API call) that has nothing to do with
the prompt — measured directly against this app's own CLI invocation, see
the LIVE_PERSISTENT_SESSIONS comment in src/config.py.

A live meeting's tidy calls (and, separately, its read calls) are genuinely
turns in ONE ongoing task, so this module keeps one
``claude --input-format stream-json --output-format stream-json`` process
alive per (meeting, lane) and feeds it turns instead of respawning. Measured
against the real CLI: the first turn on a fresh process still pays the full
bootstrap (plus a little more, since structured output is produced via an
internal tool-call round trip in this mode), but every turn after that lands
in ~2-3s with no bootstrap at all.

This module's registry (get_session/end_meeting/reap_idle) is not specific
to meetings — it is keyed by any (id, lane) pair, so a dedicated inbox-triage
lane, reused across the emails triaged in one sitting, is a structurally
plausible follow-up (triage's own system prompt IS fixed across emails, same
as tidy/read's). Not done here because the shape differs in ways that need
their own design pass, not just wiring: triage calls fire on demand rather
than a tight fixed cadence, so the win per "session" is smaller, and — the
same problem read had — each email's draft would need to stop resending
full context and send only what's new, or an inbox worked for an hour would
accumulate every earlier email's content in one growing conversation.
Prep and Felix don't fit this shape at all: their calls aren't repeated
turns on one ongoing thing the way triaging emails in one sitting is.

Read's prompt needed to change to fit this shape: read_transcript_batch (the
one-shot sibling) deliberately resends the WHOLE transcript on every read —
correct there, because the process is thrown away right after. Resending the
whole transcript every turn on a session that already remembers every prior
turn would make its context grow roughly quadratically over a long meeting.
read_transcript_batch_delta (src/features/transcription.py) sends only the
new speech since the last read instead, relying on the session's own memory
for everything earlier. Tidy already only ever sent a short tail plus the
new chunk, so it needed no prompt change — only a transport change.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from typing import Callable, Optional

from src import config, llm


class _SessionMessages:
    """Presents the same ``.messages.create(**kwargs) -> response`` surface
    as ClaudeCodeClient, so tidy/read prompt-building code doesn't need to
    know whether it's talking to a fresh process or a persistent session."""

    def __init__(self, session: "LiveSession"):
        self._session = session

    def create(self, **kwargs) -> llm._Response:
        messages = kwargs.get("messages", [])
        prompt, _images = llm._extract_prompt(messages)
        event = self._session.send(prompt)
        if event.get("is_error"):
            raise llm._classify_error(event, "")
        if "structured_output" in event and event["structured_output"] is not None:
            text = json.dumps(event["structured_output"])
        else:
            text = event.get("result", "")
        return llm._Response(content=[llm._TextBlock(text=text)],
                             stop_reason=event.get("stop_reason") or "end_turn")


class LiveSession:
    """One long-lived ``claude`` process, fixed to one model/system/schema
    for its whole life, fed one turn at a time over stdin/stdout."""

    def __init__(self, model: str, system_prompt: str, schema: dict,
                 cli_path: Optional[str] = None, timeout: Optional[int] = None,
                 popen_factory: Optional[Callable] = None):
        self.model = model
        self.system_prompt = system_prompt
        self.schema = schema
        self.cli_path = cli_path or config.CLAUDE_CLI_PATH
        self.timeout = timeout or config.CLAUDE_CLI_TIMEOUT
        self._popen_factory = popen_factory or self._real_popen
        self._proc = None
        self._lock = threading.Lock()
        self.last_used = time.monotonic()
        self.messages = _SessionMessages(self)

    # -- process lifecycle ------------------------------------------------ #
    def _build_argv(self) -> list[str]:
        argv = [self.cli_path, "-p",
                "--input-format", "stream-json", "--output-format", "stream-json",
                "--verbose",
                "--mcp-config", '{"mcpServers":{}}', "--strict-mcp-config",
                "--system-prompt", self.system_prompt,
                "--json-schema", json.dumps(self.schema)]
        cli_model = llm._cli_model(self.model)
        if cli_model:
            argv += ["--model", cli_model]
        return argv

    def _real_popen(self, argv: list[str]):
        resolved = llm.resolve_cli_path(self.cli_path) or self.cli_path
        argv = [resolved, *argv[1:]]
        try:
            return subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", bufsize=1, cwd=str(llm._scratch_dir()),
            )
        except FileNotFoundError as e:
            raise llm.ClaudeCodeUnavailable(
                f"Claude Code CLI not found at {self.cli_path!r}.") from e

    def _ensure_started(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = self._popen_factory(self._build_argv())

    def _kill(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self._proc = None

    def close(self) -> None:
        with self._lock:
            if self._proc is None:
                return
            try:
                self._proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self._proc.kill()
            self._proc = None

    # -- one turn ----------------------------------------------------------- #
    def _send_and_wait(self, prompt: str) -> dict:
        line = json.dumps({"type": "user",
                            "message": {"role": "user",
                                        "content": [{"type": "text", "text": prompt}]}})
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise llm.ClaudeCodeError(f"Live CLI session pipe broke: {e}") from e

        # A hung process must not hang the meeting: same watchdog-timer shape
        # as llm.stream_text — readline() has no timeout of its own.
        killer = threading.Timer(self.timeout, self._proc.kill)
        killer.start()
        try:
            while True:
                raw_line = self._proc.stdout.readline()
                if not raw_line:
                    stderr = ""
                    try:
                        stderr = self._proc.stderr.read() or ""
                    except Exception:  # noqa: BLE001
                        pass
                    raise llm.ClaudeCodeError(
                        f"Live CLI session ended unexpectedly: {stderr[:400] or 'no output'}")
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "result":
                    return event
        finally:
            killer.cancel()

    def send(self, prompt: str) -> dict:
        """Run one turn, transparently respawning once on a dead/broken process."""
        with self._lock:
            self.last_used = time.monotonic()
            try:
                self._ensure_started()
                return self._send_and_wait(prompt)
            except (BrokenPipeError, OSError, llm.ClaudeCodeError):
                self._kill()
                self._ensure_started()
                return self._send_and_wait(prompt)


# --------------------------------------------------------------------------- #
# Registry: one LiveSession per (meeting id, lane), lazily created.
# --------------------------------------------------------------------------- #

_registry_lock = threading.Lock()
_sessions: dict[tuple[str, str], LiveSession] = {}
_lane_factories: dict[str, Callable[[], LiveSession]] = {}


def register_lane(name: str, factory: Callable[[], LiveSession]) -> None:
    """Declare how to build a fresh session for a lane (called once at import
    time by transcription.py, which owns the model/system-prompt/schema for
    "live-tidy" and "live-read"). Keeps this module free of feature-specific
    prompt knowledge."""
    _lane_factories[name] = factory


def get_session(meeting_id: str, lane: str) -> LiveSession:
    key = (meeting_id, lane)
    with _registry_lock:
        session = _sessions.get(key)
        if session is None:
            session = _lane_factories[lane]()
            _sessions[key] = session
        return session


def end_meeting(meeting_id: str) -> None:
    """Tear down every lane's session for one meeting. Safe to call for a
    meeting with no live sessions (e.g. one that never used the persistent
    path) — a no-op in that case."""
    with _registry_lock:
        keys = [k for k in _sessions if k[0] == meeting_id]
        closing = [_sessions.pop(k) for k in keys]
    for session in closing:
        session.close()


def reap_idle(max_idle_seconds: Optional[float] = None) -> None:
    """Close sessions nobody has used in a while — the backstop for a meeting
    that never called end_meeting (crashed tab, closed laptop lid)."""
    limit = max_idle_seconds if max_idle_seconds is not None else config.LIVE_SESSION_IDLE_SECONDS
    now = time.monotonic()
    with _registry_lock:
        stale_keys = [k for k, s in _sessions.items() if now - s.last_used > limit]
        closing = [_sessions.pop(k) for k in stale_keys]
    for session in closing:
        session.close()


def active_session_count() -> int:
    with _registry_lock:
        return len(_sessions)
