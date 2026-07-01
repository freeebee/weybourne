import json
from dataclasses import dataclass, field
from typing import Callable

from src.extraction import _chunk_markdown, extract_document


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

    def create(self, **kwargs):
        return self._handler(**kwargs)


class FakeClient:
    def __init__(self, handler: Callable[..., FakeResponse]):
        self.messages = FakeMessages(handler)


VALID_METRIC = {
    "fund_id": "Fund I", "metric_name": "AUM", "value": 100.0,
    "unit": "USD", "period": "2026-Q1", "source_doc": "doc.pdf",
}
INVALID_METRIC = {
    "fund_id": "Fund II", "metric_name": "AUM", "value": 50.0,
    "unit": "USD", "period": "not-a-period", "source_doc": "doc.pdf",
}


def response_with(metrics=None, notes=None):
    payload = {"financial_metrics": metrics or [], "narrative_notes": notes or []}
    return FakeResponse(content=[FakeTextBlock(text=json.dumps(payload))])


def test_extract_document_happy_path():
    client = FakeClient(lambda **kw: response_with(metrics=[VALID_METRIC]))
    outcome = extract_document(client, "some markdown content", source_doc="doc.pdf")

    assert len(outcome.metrics) == 1
    assert outcome.metrics[0].fund_id == "Fund I"
    assert outcome.flagged == []


def test_extract_document_flags_invalid_json():
    client = FakeClient(lambda **kw: FakeResponse(content=[FakeTextBlock(text="not json")]))
    outcome = extract_document(client, "content", source_doc="doc.pdf")

    assert outcome.metrics == []
    assert len(outcome.flagged) == 1
    assert outcome.flagged[0][0].startswith("invalid_json")


def test_extract_document_partial_validation_keeps_valid_records():
    client = FakeClient(lambda **kw: response_with(metrics=[VALID_METRIC, INVALID_METRIC]))
    outcome = extract_document(client, "content", source_doc="doc.pdf")

    assert len(outcome.metrics) == 1
    assert outcome.metrics[0].fund_id == "Fund I"
    assert len(outcome.flagged) == 1
    assert outcome.flagged[0][0].startswith("invalid_metric")


def test_extract_document_flags_model_refusal():
    client = FakeClient(lambda **kw: FakeResponse(content=[], stop_reason="refusal"))
    outcome = extract_document(client, "content", source_doc="doc.pdf")

    assert outcome.metrics == []
    assert outcome.notes == []
    assert outcome.flagged[0][0] == "model_refusal"


def test_chunk_markdown_splits_on_page_boundaries():
    markdown = (
        "<!-- page 1 -->\n" + ("a" * 50) + "\n\n"
        "<!-- page 2 -->\n" + ("b" * 50) + "\n\n"
        "<!-- page 3 -->\n" + ("c" * 50)
    )
    chunks = _chunk_markdown(markdown, max_chars=80)

    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)  # some slack for markers/newlines
    assert "".join(chunks).count("page 1") == 1
    assert "".join(chunks).count("page 3") == 1


def test_chunk_markdown_single_chunk_when_small():
    markdown = "<!-- page 1 -->\nshort content"
    chunks = _chunk_markdown(markdown, max_chars=1000)
    assert len(chunks) == 1
