"""Felix's web-research escalation and the merge side-by-side detail."""
import json

from src.connectors.notion_client import NotionConnector
from src.features.felix import research, store
from src.features.felix.models import RunOptions
from src.features.felix.run import felix_run
from tests.fakes import FakeClient


class TestDuplicateResearch:
    def test_researches_with_web_search_and_employer_context(self):
        client = FakeClient(payload={
            "verdict": "distinct", "confidence": "high",
            "explanation": "Different people at different firms.",
            "evidence": "LinkedIn shows both profiles."})
        a = {"name": "Alexandre Vaivre", "email": "", "plain": {},
             "relations": {"Employed By": ["co1"]}}
        b = {"name": "Alexandre De Vaivre", "email": "", "plain": {},
             "relations": {"Employed By": ["co2"]}}
        out = research.research_duplicate(client, a, b,
                                          {"co1": "Fund Alpha",
                                           "co2": "Beta Partners"})
        assert out["verdict"] == "distinct"
        call = client.calls[0]
        assert call["extra_allowed_tools"] == ["WebSearch", "WebFetch"]
        user = call["messages"][0]["content"]
        assert "Fund Alpha" in user and "Beta Partners" in user


class TestFundFieldResearch:
    def test_values_validated_against_options(self):
        client = FakeClient(payload={"proposals": [
            {"property": "Asset Class", "value": "Private Equity",
             "explanation": "Buyout fund per their site.",
             "source": "example.com"},
            {"property": "Geographic Focus", "value": "Mars",
             "explanation": "nonsense", "source": "nowhere"},
        ]})
        card = {"name": "Alpha Fund III", "plain": {}, "relations": {}}
        out = research.research_fund_fields(
            client, card,
            [{"property": "Asset Class",
              "options": ["Private Equity", "Credit"]},
             {"property": "Geographic Focus",
              "options": ["Asia", "Global"]}],
            company_name="Alpha Capital")
        # The invented option is dropped in code; the valid one survives.
        assert out == [{"property": "Asset Class", "value": "Private Equity",
                        "explanation": "Buyout fund per their site.",
                        "source": "example.com"}]
        assert "Alpha Capital" in client.calls[0]["messages"][0]["content"]


class TestMergeDetail:
    def test_dry_run_merge_carries_side_by_side(self, tmp_path):
        felix_run({"stages": [], "partial": {}}, NotionConnector(), None,
                  RunOptions(dry_run=True), base=tmp_path)
        merge = store.list_all_changes(base=tmp_path, change_type="merge")[0]
        d = json.loads(merge.detail)
        # Josh Katzin (poorer) archived into Joshua Katzin (richer).
        assert d["archive"]["name"] == "Josh Katzin"
        assert d["keep"]["name"] == "Joshua Katzin"
        assert "fields" in d["keep"] and "moves" in d
