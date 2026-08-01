"""Shared test fixtures.

Tests must not depend on the developer's local `data/` state: once real
Outlook snapshots exist there (written by the app's refresh job), the Graph
connector would leave sample mode and the frozen sample clock. Point the
snapshot paths at an empty temp directory for every test.
"""
import pytest

from src.connectors import graph


@pytest.fixture(autouse=True)
def _isolate_snapshots(monkeypatch, tmp_path):
    monkeypatch.setattr(graph, "INBOX_SNAPSHOT", tmp_path / "inbox_snapshot.json")
    monkeypatch.setattr(graph, "CALENDAR_SNAPSHOT", tmp_path / "calendar_snapshot.json")
    monkeypatch.setattr(graph, "SHARED_INBOX_SNAPSHOT", tmp_path / "shared_inbox_snapshot.json")
