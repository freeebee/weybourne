"""Shared fake Claude client for offline tests (no API calls anywhere in CI)."""
import json
from dataclasses import dataclass
from typing import Callable


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list
    stop_reason: str = "end_turn"


class FakeMessages:
    def __init__(self, handler: Callable[..., FakeResponse]):
        self._handler = handler
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._handler(**kwargs)


class FakeClient:
    """Client whose ``messages.create`` returns a canned JSON payload."""

    def __init__(self, payload=None, handler=None):
        if handler is None:
            def handler(**_kwargs):  # noqa: ANN003
                return FakeResponse(content=[FakeTextBlock(text=json.dumps(payload))])
        self.messages = FakeMessages(handler)

    @property
    def calls(self) -> list[dict]:
        return self.messages.calls
