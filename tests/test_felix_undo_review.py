"""API-level guards for requesting an undo from Felix's change history."""

import pytest
from fastapi import HTTPException

import api.main as api_main
from src.features.felix.models import ChangeRecord


def _change(*, execution_status="Applied", review_status="Approved"):
    return ChangeRecord(
        change_id="FLX-undo",
        run_id="run-1",
        timestamp="2026-08-18T10:00:00",
        database="contacts",
        execution_status=execution_status,
        review_status=review_status,
    )


def test_undo_rejects_a_change_that_felix_did_not_apply(monkeypatch):
    monkeypatch.setattr(api_main.felix_store, "find_change",
                        lambda _change_id: _change(execution_status="Proposed"))
    started = []
    monkeypatch.setattr(api_main, "_start_job",
                        lambda *args: started.append(args))

    with pytest.raises(HTTPException) as exc:
        api_main.felix_review(
            "FLX-undo", api_main.FelixReviewIn(action="undo"))

    assert exc.value.status_code == 409
    assert started == []


def test_research_queue_item_cannot_be_reviewed(monkeypatch):
    queued = _change(execution_status="Recommended",
                     review_status="Awaiting Review")
    queued.recommendation_kind = "research_queued"
    monkeypatch.setattr(api_main.felix_store, "find_change",
                        lambda _change_id: queued)

    with pytest.raises(HTTPException) as exc:
        api_main.felix_review(
            "FLX-undo", api_main.FelixReviewIn(action="approve"))

    assert exc.value.status_code == 409
    assert "not a review decision" in exc.value.detail


def test_undo_marks_the_row_and_returns_a_trackable_job(monkeypatch):
    monkeypatch.setattr(api_main.felix_store, "find_change",
                        lambda _change_id: _change())
    updates = []
    monkeypatch.setattr(api_main.felix_store, "update_change",
                        lambda *args: updates.append(args))
    monkeypatch.setattr(api_main, "_start_job", lambda kind, label, work: {
        "id": "undo-job", "kind": kind, "label": label,
        "status": "running", "stages": [], "elapsed": 0,
        "created": "10:00",
    })

    result = api_main.felix_review(
        "FLX-undo", api_main.FelixReviewIn(action="undo"))

    assert updates == [("FLX-undo", {"review_status": "Undo Requested"})]
    assert result["review_status"] == "Undo Requested"
    assert result["job"]["id"] == "undo-job"
    assert result["job"]["kind"] == "felix-undo"


def test_a_second_undo_request_does_not_start_another_job(monkeypatch):
    monkeypatch.setattr(
        api_main.felix_store, "find_change",
        lambda _change_id: _change(review_status="Undo Requested"))
    started = []
    monkeypatch.setattr(api_main, "_start_job",
                        lambda *args: started.append(args))

    result = api_main.felix_review(
        "FLX-undo", api_main.FelixReviewIn(action="undo"))

    assert result == {
        "change_id": "FLX-undo",
        "review_status": "Undo Requested",
        "note": "undo already requested",
    }
    assert started == []
