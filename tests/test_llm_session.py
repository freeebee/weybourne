"""Persistent live-meeting CLI sessions (src/llm_session.py).

The real process is always stubbed via an injectable popen_factory, so this
suite never spawns the real CLI.
"""
import json

import pytest

from src import llm, llm_session
from src.llm_session import LiveSession, end_meeting, get_session, reap_idle, register_lane

SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}},
          "required": ["text"], "additionalProperties": False}


class FakeStdin:
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, s):
        self.writes.append(s)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FakeStdout:
    """Serves one scripted list of raw lines per turn, in order."""

    def __init__(self, turns):
        self._turns = [list(t) for t in turns]
        self._current: list[str] = []

    def readline(self):
        if not self._current:
            if not self._turns:
                return ""   # EOF: simulates a dead/crashed process
            self._current = self._turns.pop(0)
        if not self._current:
            return ""
        return self._current.pop(0)


class FakeStderr:
    def __init__(self, text=""):
        self._text = text

    def read(self):
        return self._text


class FakeProcess:
    def __init__(self, turns=(), stderr_text=""):
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(turns)
        self.stderr = FakeStderr(stderr_text)
        self._killed = False

    def poll(self):
        return None if not self._killed else 1

    def kill(self):
        self._killed = True

    def wait(self, timeout=None):
        return 0


def result_line(structured_output=None, result_text="", is_error=False, stop_reason="tool_use"):
    return json.dumps({
        "type": "result", "is_error": is_error, "result": result_text,
        "structured_output": structured_output, "stop_reason": stop_reason,
    })


def noise_lines(n=2):
    return [json.dumps({"type": "system", "subtype": "thinking_tokens"}) for _ in range(n)]


class FactoryOf:
    """popen_factory that hands out pre-built FakeProcesses in order and
    records how many times it was called (i.e. how many real spawns
    happened)."""

    def __init__(self, *processes):
        self.processes = list(processes)
        self.calls = 0

    def __call__(self, argv):
        self.calls += 1
        self.argv_seen = argv
        return self.processes[self.calls - 1]


class TestArgvConstruction:
    def test_stream_json_both_ways_fixed_schema_system_and_model(self):
        factory = FactoryOf(FakeProcess(turns=[[*noise_lines(), result_line({"text": "hi"})]]))
        session = LiveSession(model="claude-sonnet-5", system_prompt="Be terse.",
                               schema=SCHEMA, popen_factory=factory)
        session.send("hello")
        argv = factory.argv_seen
        assert argv[argv.index("--input-format") + 1] == "stream-json"
        assert argv[argv.index("--output-format") + 1] == "stream-json"
        assert argv[argv.index("--system-prompt") + 1] == "Be terse."
        assert json.loads(argv[argv.index("--json-schema") + 1]) == SCHEMA
        assert argv[argv.index("--model") + 1] == "sonnet"

    def test_never_passes_bare(self):
        factory = FactoryOf(FakeProcess(turns=[[result_line({"text": "hi"})]]))
        session = LiveSession(model="claude-sonnet-5", system_prompt="s",
                               schema=SCHEMA, popen_factory=factory)
        session.send("hello")
        assert "--bare" not in factory.argv_seen


class TestTurnTaking:
    def test_first_turn_spawns_and_returns_the_result_event(self):
        factory = FactoryOf(FakeProcess(turns=[[*noise_lines(3), result_line({"text": "pong"})]]))
        session = LiveSession(model="haiku", system_prompt="s", schema=SCHEMA, popen_factory=factory)
        event = session.send("ping")
        assert event["structured_output"] == {"text": "pong"}
        assert factory.calls == 1

    def test_second_turn_reuses_the_same_process(self):
        proc = FakeProcess(turns=[[result_line({"text": "one"})], [result_line({"text": "two"})]])
        factory = FactoryOf(proc)
        session = LiveSession(model="haiku", system_prompt="s", schema=SCHEMA, popen_factory=factory)
        first = session.send("turn one")
        second = session.send("turn two")
        assert first["structured_output"] == {"text": "one"}
        assert second["structured_output"] == {"text": "two"}
        assert factory.calls == 1   # no respawn between turns
        assert len(proc.stdin.writes) == 2

    def test_a_dead_process_triggers_exactly_one_respawn_and_retry(self):
        dead = FakeProcess(turns=[])   # immediate EOF -- simulates a crash
        alive = FakeProcess(turns=[[result_line({"text": "recovered"})]])
        factory = FactoryOf(dead, alive)
        session = LiveSession(model="haiku", system_prompt="s", schema=SCHEMA, popen_factory=factory)
        event = session.send("ping")
        assert event["structured_output"] == {"text": "recovered"}
        assert factory.calls == 2

    def test_error_result_is_classified_not_returned_raw(self):
        # send() itself is a raw turn primitive (mirrors _create's use of the
        # raw subprocess runner) -- classification happens one level up, in
        # the messages.create() shim, matching ClaudeCodeClient's contract.
        blob = result_line(structured_output=None, result_text="usage limit reached", is_error=True)
        factory = FactoryOf(FakeProcess(turns=[[blob]]))
        session = LiveSession(model="haiku", system_prompt="s", schema=SCHEMA, popen_factory=factory)
        with pytest.raises(llm.ClaudeCodeRateLimited):
            session.messages.create(messages=[{"role": "user", "content": "ping"}])

    def test_close_closes_stdin_and_drops_the_process(self):
        proc1 = FakeProcess(turns=[[result_line({"text": "hi"})]])
        proc2 = FakeProcess(turns=[[result_line({"text": "hi again"})]])
        factory = FactoryOf(proc1, proc2)
        session = LiveSession(model="haiku", system_prompt="s", schema=SCHEMA, popen_factory=factory)
        session.send("ping")
        session.close()
        assert proc1.stdin.closed
        session.send("ping again")
        assert factory.calls == 2   # closed sessions respawn fresh on next use


class TestMessagesShim:
    def test_create_mimics_the_anthropic_shaped_response(self):
        factory = FactoryOf(FakeProcess(turns=[[result_line({"text": "hi there"})]]))
        session = LiveSession(model="haiku", system_prompt="s", schema=SCHEMA, popen_factory=factory)
        response = session.messages.create(
            model="ignored-here", max_tokens=100, system="ignored-here",
            output_config={"format": {"schema": SCHEMA}},
            messages=[{"role": "user", "content": "hello"}],
        )
        assert json.loads(response.content[0].text) == {"text": "hi there"}
        assert response.content[0].type == "text"

    def test_falls_back_to_the_text_result_when_no_structured_output(self):
        factory = FactoryOf(FakeProcess(
            turns=[[result_line(structured_output=None, result_text="plain answer")]]))
        session = LiveSession(model="haiku", system_prompt="s", schema=SCHEMA, popen_factory=factory)
        response = session.messages.create(messages=[{"role": "user", "content": "hi"}])
        assert response.content[0].text == "plain answer"


class TestRegistry:
    def setup_method(self):
        register_lane("test-lane", lambda: LiveSession(
            model="haiku", system_prompt="s", schema=SCHEMA,
            popen_factory=FactoryOf(FakeProcess(turns=[[result_line({"text": "x"})]]))))

    def teardown_method(self):
        end_meeting("meeting-a")
        end_meeting("meeting-b")

    def test_same_meeting_and_lane_returns_the_same_session(self):
        a = get_session("meeting-a", "test-lane")
        b = get_session("meeting-a", "test-lane")
        assert a is b

    def test_different_meetings_get_different_sessions(self):
        a = get_session("meeting-a", "test-lane")
        b = get_session("meeting-b", "test-lane")
        assert a is not b

    def test_end_meeting_removes_it_from_the_registry(self):
        before = get_session("meeting-a", "test-lane")
        end_meeting("meeting-a")
        after = get_session("meeting-a", "test-lane")
        assert before is not after

    def test_end_meeting_on_an_unknown_meeting_is_a_no_op(self):
        end_meeting("never-existed")   # must not raise

    def test_reap_idle_closes_only_sessions_past_the_limit(self):
        fresh = get_session("meeting-a", "test-lane")
        stale = get_session("meeting-b", "test-lane")
        stale.last_used -= 1000
        reap_idle(max_idle_seconds=500)
        assert get_session("meeting-a", "test-lane") is fresh   # untouched
        assert get_session("meeting-b", "test-lane") is not stale   # reaped and recreated
