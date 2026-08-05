"""Web searches only fire while the complex-case review queue has room.

An ordinary run now researches ambiguous cases (duplicates, tags the notes
can't settle) on its own — see run.py's should_research_now and
TestShouldResearchNow in test_felix_run.py for that gate directly. This mock
workspace has no such ambiguous case to search for in the first place (its
only duplicate is an exact-identifier match, settled without a model call),
so a normal run against it makes no web call regardless of the gate — these
tests pin that absence of noise, not the gate's on/off logic itself.
"""
from src.connectors.notion_client import NotionConnector
from src.features.felix import detect, enrich, store
from src.features.felix.models import RunOptions
from src.features.felix.run import felix_run
from tests.fakes import FakeClient


class SpyClient(FakeClient):
    """Records whether any call was given web tools."""

    def __init__(self, payload):
        super().__init__(payload)

    @property
    def web_calls(self):
        return [c for c in self.calls if c.get("extra_allowed_tools")]


def test_a_run_against_a_workspace_with_nothing_ambiguous_makes_no_web_call(tmp_path):
    client = SpyClient({"verdict": "unsure", "confidence": "low",
                        "lean": "none", "employer_check": "",
                        "explanation": "", "evidence": "",
                        "pairs": [], "fills": [], "proposals": [],
                        "employer": "", "title": "", "description": "",
                        "linkedin_url": "", "photo_url": "", "used_web": False,
                        "company": "", "attendees": [], "note_type": ""})
    felix_run({"stages": [], "partial": {}}, NotionConnector(), client,
              RunOptions(dry_run=True), base=tmp_path)
    assert client.web_calls == [], "a default run must not spend a web search"


def test_the_run_records_what_it_could_not_settle(tmp_path):
    client = SpyClient({"verdict": "unsure", "confidence": "low",
                        "lean": "none", "employer_check": "",
                        "explanation": "", "evidence": "",
                        "pairs": [], "fills": [], "proposals": [],
                        "employer": "", "title": "", "description": "",
                        "linkedin_url": "", "photo_url": "", "used_web": False,
                        "company": "", "attendees": [], "note_type": ""})
    felix_run({"stages": [], "partial": {}}, NotionConnector(), client,
              RunOptions(dry_run=True), base=tmp_path)
    pending = store.load_pending_research(tmp_path)
    assert "items" in pending
    for item in pending["items"]:
        assert item["kind"] in ("employer", "contact_field", "fund_company",
                                "fund_tags", "duplicate")
        assert item["record_name"]


def test_the_pending_list_is_rewritten_not_accumulated(tmp_path):
    store.save_pending_research([{"kind": "employer", "record_name": "stale"}],
                                tmp_path)
    store.save_pending_research([{"kind": "fund_tags", "record_name": "fresh"}],
                                tmp_path)
    items = store.load_pending_research(tmp_path)["items"]
    assert [i["record_name"] for i in items] == ["fresh"]


class TestNoWebMode:
    """With use_web off the model is given no search tools and is told to say
    so rather than guess."""

    PAYLOAD = {"employer": "", "title": "", "description": "",
               "linkedin_url": "", "photo_url": "", "confidence": "low",
               "evidence": "the notes do not say", "used_web": False}

    def test_contact_research_withholds_the_tools(self):
        client = FakeClient(self.PAYLOAD)
        enrich.research_contact(client, {"name": "X", "email": "", "domain": "",
                                         "plain": {}}, "some note", use_web=False)
        call = client.calls[0]
        assert "extra_allowed_tools" not in call
        assert "do NOT search the web" in call["system"]

    def test_contact_research_offers_the_tools_when_asked(self):
        client = FakeClient(self.PAYLOAD)
        enrich.research_contact(client, {"name": "X", "email": "", "domain": "",
                                         "plain": {}}, "", use_web=True)
        assert client.calls[0]["extra_allowed_tools"] == ["WebSearch", "WebFetch"]


class TestPropertyNames:
    """The live workspace prefixes property names with emoji; matching them
    literally silently found nothing, which read as 'no gaps'."""

    def test_emoji_prefixed_properties_are_matched(self):
        props = {"🏢 Employed By", "Type", "Name"}
        assert detect.match_prop(props, "Employed By") == "🏢 Employed By"

    def test_an_absent_property_returns_empty(self):
        assert detect.match_prop({"Name"}, "Employed By") == ""

    def test_missing_props_finds_the_emoji_property(self):
        card = {"id": "c1", "db": "contacts", "name": "A", "archived": False,
                "plain": {"🏢 Employed By": "", "Type": "GP - Investments"},
                "relations": {}, "raw": {}, "title_prop": "Name",
                "email": "", "domain": "", "url": "", "created": ""}
        out = detect.find_missing_props([card], "contacts",
                                        {"🏢 Employed By", "Type"})
        assert out and out[0]["missing"] == ["🏢 Employed By"]
