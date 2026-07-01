import pytest
from pydantic import ValidationError

from src.schemas import ExtractionResult, FinancialMetric, NarrativeNote


def test_financial_metric_valid():
    m = FinancialMetric(
        fund_id="Fund I", metric_name="AUM", value=123.4, unit="USD",
        period="2026-Q1", source_doc="doc.pdf",
    )
    assert m.period == "2026-Q1"


@pytest.mark.parametrize("bad_period", ["2026", "2026-Q5", "Q1-2026", "26-Q1", ""])
def test_financial_metric_rejects_bad_period(bad_period):
    with pytest.raises(ValidationError):
        FinancialMetric(
            fund_id="Fund I", metric_name="AUM", value=1.0, unit="USD",
            period=bad_period, source_doc="doc.pdf",
        )


def test_financial_metric_rejects_blank_fund_id():
    with pytest.raises(ValidationError):
        FinancialMetric(
            fund_id="   ", metric_name="AUM", value=1.0, unit="USD",
            period="2026-Q1", source_doc="doc.pdf",
        )


def test_narrative_note_valid():
    n = NarrativeNote(
        entity_id="Fund I", period="2026-Q1", note_text="hello",
        topic_tag="outlook", source_doc="doc.pdf",
    )
    assert n.topic_tag == "outlook"


def test_narrative_note_rejects_blank_text():
    with pytest.raises(ValidationError):
        NarrativeNote(
            entity_id="Fund I", period="2026-Q1", note_text="  ",
            topic_tag="outlook", source_doc="doc.pdf",
        )


def test_extraction_result_defaults_to_empty_lists():
    result = ExtractionResult()
    assert result.financial_metrics == []
    assert result.narrative_notes == []


def test_extraction_result_parses_nested_records():
    result = ExtractionResult.model_validate(
        {
            "financial_metrics": [
                {
                    "fund_id": "Fund I", "metric_name": "AUM", "value": 1.0,
                    "unit": "USD", "period": "2026-Q1", "source_doc": "doc.pdf",
                }
            ],
            "narrative_notes": [],
        }
    )
    assert len(result.financial_metrics) == 1
