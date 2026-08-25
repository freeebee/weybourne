"""Stage 1 of a MENTIONS card: local assembly of what the firm already holds.

The card runs beside live transcription on a machine whisper saturates, so
the contract under test is as much about what it does NOT do as what it
returns: no index builds while recording, no unbounded waits on Graph, and
"no prior contact on record" as a first-class answer rather than a failure.
"""
import json
import threading
import time

import pytest

from src.schemas import CompanyRecord, ContactRecord, EmailMessage, FundRecord, NoteRecord
from src.features import live_entities


class FakeNotion:
    def __init__(self, contacts=(), companies=(), funds=(), notes=()):
        self._contacts = list(contacts)
        self._companies = list(companies)
        self._funds = list(funds)
        self._notes = list(notes)
        self.list_calls = 0

    def list_contacts(self):
        self.list_calls += 1
        return self._contacts

    def list_companies(self):
        self.list_calls += 1
        return self._companies

    def list_funds(self):
        self.list_calls += 1
        return self._funds

    def list_notes(self):
        self.list_calls += 1
        return self._notes


class FakeGraph:
    def __init__(self, messages=(), delay=0.0):
        self._messages = list(messages)
        self._delay = delay

    def messages_with(self, person, top=20, days=120):
        if self._delay:
            time.sleep(self._delay)
        return self._messages[:top]


@pytest.fixture(autouse=True)
def clean_caches():
    """Module-level caches leak across tests otherwise."""
    live_entities._INDEX_CACHE.clear()
    live_entities._NOTES_CACHE = None
    yield
    live_entities._INDEX_CACHE.clear()
    live_entities._NOTES_CACHE = None


@pytest.fixture
def stores(tmp_path):
    """Empty managers/transcripts/quick stores on disk."""
    managers = tmp_path / "managers"
    live = tmp_path / "live"
    lib = tmp_path / "lib"
    quick = tmp_path / "quick"
    for d in (managers, live, lib, quick):
        d.mkdir()
    return {"managers_base": managers, "live_dir": live, "lib_dir": lib,
            "quick_store": quick}


def build(name, notion=None, graph=None, **kw):
    return live_entities.build_entity_card(
        name, "company", notion=notion or FakeNotion(), graph=graph or FakeGraph(),
        **kw)


NOTION = lambda: FakeNotion(  # noqa: E731
    contacts=[ContactRecord(id="ct1", name="Allan Fife", email="af@fife.com",
                            title="CIO", company="Fife Capital")],
    companies=[CompanyRecord(id="co1", name="Fife Capital",
                             description="Australian real assets manager.",
                             city="Sydney", country="Australia")],
    funds=[FundRecord(id="f1", name="Fife Capital Fund 3", status="Active",
                      company="Fife Capital"),
           FundRecord(id="f2", name="Albizia ASEAN Opportunities Fund",
                      status="Active", company="Albizia Capital")],
    notes=[NoteRecord(id="n1", name="Meeting with Fife Capital", date="2026-05-01",
                      excerpt="Discussed the Sydney logistics pipeline.",
                      company_ids=["co1"]),
           NoteRecord(id="n2", name="Unrelated internal note", date="2026-06-01",
                      excerpt="Quarterly planning.")],
)


class TestAssembly:
    def test_a_known_company_gets_its_records(self, stores):
        card = build("Fife Capital", notion=NOTION(), **stores)
        assert card["matched"]["company"]["id"] == "co1"
        assert card["matched"]["contact"] is None   # contact is Allan Fife, not "Fife Capital"
        assert card["no_record"] is False
        # The note is found via the company relation.
        assert [n["title"] for n in card["notes"]] == ["Meeting with Fife Capital"]

    def test_ownership_finds_funds_no_similarity_score_would(self, stores):
        card = build("Albizia", notion=NOTION(), **stores)
        assert [f["name"] for f in card["related_funds"]] == \
            ["Albizia ASEAN Opportunities Fund"]

    def test_an_unknown_name_is_a_finding_not_a_failure(self, stores):
        card = build("Zephyr Crest Partners", notion=NOTION(), **stores)
        assert card["no_record"] is True
        assert card["news_status"] == "none"
        assert card["matched"] == {"contact": None, "company": None, "fund": None}

    def test_a_shared_noise_token_is_not_a_match(self, stores):
        """"Zephyr Crest Partners" scored 0.76 against the real "Harvest
        Partners" on nothing but the shared word "Partners" — dedupe's review
        band exists for a human reviewer, and a live card has none. Bare
        similarity must clear _SIMILARITY_DISPLAY_FLOOR instead."""
        notion = FakeNotion(companies=[CompanyRecord(id="c9", name="Harvest Partners")])
        card = build("Zephyr Crest Partners", notion=notion, **stores)
        assert card["matched"]["company"] is None

    def test_a_whisper_mishearing_still_matches(self, stores):
        """The floor must not cost transcription tolerance: a dropped letter
        is true similarity, not a shared suffix."""
        notion = FakeNotion(companies=[CompanyRecord(id="c1", name="Brookfield")])
        card = build("Brookfeld", notion=notion, **stores)
        assert card["matched"]["company"]["id"] == "c1"

    def test_an_acronym_still_matches_at_the_review_band(self, stores):
        """Acronym evidence is capped below 0.90 by design (initials collide,
        never auto-link) — the similarity floor must not silence it."""
        notion = FakeNotion(companies=[
            CompanyRecord(id="c2", name="Enhanced Investment Products Limited")])
        card = build("EIP", notion=notion, **stores)
        assert card["matched"]["company"]["id"] == "c2"

    def test_emails_arrive_from_graph(self, stores):
        graph = FakeGraph(messages=[EmailMessage(id="m1", subject="Fund III close",
                                                 sender_name="Allan Fife",
                                                 received="2026-08-01T09:00:00Z")])
        card = build("Fife Capital", notion=NOTION(), graph=graph, **stores)
        assert card["emails"][0]["subject"] == "Fund III close"

    def test_a_slow_graph_call_cannot_hold_the_card(self, stores):
        """The card has a time budget; mail past it is dropped, not awaited."""
        graph = FakeGraph(messages=[EmailMessage(id="m1", subject="late")],
                          delay=3.0)
        t0 = time.monotonic()
        card = build("Fife Capital", notion=NOTION(), graph=graph,
                     email_timeout=0.2, **stores)
        assert time.monotonic() - t0 < 2.0
        assert card["emails"] == []


class TestIndexDiscipline:
    def test_the_same_list_object_is_not_reindexed(self, stores):
        notion = NOTION()
        build("Fife Capital", notion=notion, **stores)
        calls_after_first = notion.list_calls
        build("Albizia", notion=notion, **stores)
        # list_* is consulted again (identity check) but the index is reused —
        # verified by the cache keeping the same object.
        assert live_entities._INDEX_CACHE["companies"][2] is notion._companies

    def test_allow_stale_never_touches_the_lists(self, stores):
        """The mid-meeting contract: whisper owns the machine, so a card may
        use only what is already built."""
        notion = NOTION()
        live_entities.warm_indexes(notion)
        calls_after_warm = notion.list_calls
        card = build("Fife Capital", notion=notion, allow_stale_index=True, **stores)
        assert notion.list_calls == calls_after_warm
        assert card["matched"]["company"]["id"] == "co1"   # warm index still matches

    def test_a_cold_collection_is_skipped_not_built(self, stores):
        """Recording started on a cold process and the warm thread has not
        landed: the card forgoes Notion matches rather than building indexes
        beside live whisper."""
        notion = NOTION()
        card = build("Fife Capital", notion=notion, allow_stale_index=True, **stores)
        assert notion.list_calls == 0
        assert card["matched"]["company"] is None
        # Everything index-free still works; nothing raised.
        assert card["no_record"] is True


class TestDossier:
    def test_a_stale_dossier_still_reaches_the_card(self, stores, monkeypatch):
        """For a live card a 20-day-old dossier beats nothing — its age is
        stated, not hidden (this is load_dossier, not get_dossier)."""
        from src.features import web_research
        key = web_research.research_key("Fife Capital")
        old = {"firm": "Australian real assets manager.", "recent": [],
               "gathered_at": time.time() - 20 * 86400, "gathered_on": "28 Jul 2026"}
        monkeypatch.setattr(live_entities, "load_dossier",
                            lambda k, store_dir=None: old if k == key and store_dir is None else None)
        card = build("Fife Capital", notion=NOTION(), **stores)
        assert card["dossier"]["age_days"] >= 19
        assert card["dossier"]["gathered_on"] == "28 Jul 2026"


class TestManagerThread:
    def test_the_thread_history_is_trimmed(self, stores):
        (stores["managers_base"] / "fife-capital.json").write_text(json.dumps({
            "entity": "Fife Capital", "aliases": [], "email": "",
            "company_name": "Fife Capital", "fund_name": "", "contact_name": "",
            "questions": [],
            "history": [{"at": f"2026-01-{d:02d}", "kind": "triage",
                         "subject": f"mail {d}"} for d in range(1, 11)],
        }), encoding="utf-8")
        card = build("Fife Capital", notion=NOTION(), **stores)
        assert card["manager_thread"]["entity"] == "Fife Capital"
        assert len(card["manager_thread"]["history"]) == 6
        assert card["manager_thread"]["history"][-1]["subject"] == "mail 10"


class TestNoteExcerpts:
    """A PRIOR CONTACT line must lead with what the note said about the
    ENTITY (user, 21 Aug 2026): an intro-call note's opening 200 characters
    describe the meeting, while the mention of the card's entity sits
    paragraphs in. When the note's text names the entity, the excerpt
    anchors on that mention; relation-only matches keep the opening."""

    @staticmethod
    def _notion(excerpt):
        return FakeNotion(
            companies=[CompanyRecord(id="co2", name="Advantage Partners")],
            notes=[NoteRecord(id="n3", name="Intro call with Lorient",
                              date="2026-07-31", excerpt=excerpt)])

    def test_excerpt_anchors_on_the_mention_not_the_opening(self, stores):
        text = ("Co-founder Jordan was a bit salesy, including saying 'being "
                "totally honest'. " + "More about their own systemisation. " * 12
                + "They benchmark themselves against Advantage Partners on "
                "Japan buyouts and claim lower entry multiples. Trailing text.")
        card = build("Advantage Partners", notion=self._notion(text), **stores)
        note = card["notes"][0]
        assert "Advantage Partners" in note["excerpt"]
        assert "lower entry multiples" in note["excerpt"]
        assert not note["excerpt"].startswith("Co-founder")
        # The wider window is what stage 2b's one-liner call reads.
        assert "Advantage Partners" in note["mention_context"]
        assert len(note["mention_context"]) >= len(note["excerpt"])

    def test_a_partial_name_still_anchors(self, stores):
        """Notes say plain "Advantage", not the full registered name — the
        distinguishing token anchors; the noise token never does."""
        text = ("Opening paragraph about the meeting itself. " * 8
                + "Compared unfavourably to Advantage on fees and pacing.")
        card = build("Advantage Partners", notion=self._notion(text), **stores)
        assert "Compared unfavourably to Advantage" in card["notes"][0]["excerpt"]

    def test_a_relation_only_match_keeps_the_opening(self, stores):
        card = build("Fife Capital", notion=NOTION(), **stores)
        assert card["notes"][0]["excerpt"] == \
            "Discussed the Sydney logistics pipeline."


class TestDescriptionTrim:
    """The card's DESCRIPTION must never end mid-clause with an ellipsis
    (user, 21 Aug 2026: "…drive value creation through…")."""

    def test_short_text_is_untouched(self):
        assert live_entities._trim_sentence("A manager.", 600) == "A manager."

    def test_long_text_ends_at_a_sentence_not_mid_clause(self):
        text = ("Focused on buyouts in Japan with operational depth. " * 30).strip()
        out = live_entities._trim_sentence(text, 600)
        assert out.endswith("depth.")
        assert len(out) <= 600

    def test_unpunctuated_text_falls_back_to_the_ellipsis_trim(self):
        out = live_entities._trim_sentence("word " * 300, 100)
        assert out.endswith("…") and len(out) <= 100

    def test_the_card_carries_whole_sentences(self, stores):
        long_desc = ("Focused on buyouts in Japan, this fund seeks companies "
                     "with growth potential. " * 20).strip()
        notion = FakeNotion(companies=[
            CompanyRecord(id="co3", name="Advantage Partners",
                          description=long_desc)])
        card = build("Advantage Partners", notion=notion, **stores)
        desc = card["matched"]["company"]["description"]
        assert desc.endswith("potential.")
        assert not desc.endswith("…")


class TestSaidBefore:
    """The mention card's footer quotes what was SAID about the entity in
    earlier meetings — our own transcripts, not news links."""

    @staticmethod
    def _file(tmp_path, sid, transcript, who="Fife Capital"):
        from src.features import transcript_library as tl
        tl.finish({"id": sid, "who": who, "transcript": transcript,
                   "started": f"2026-08-0{sid[-1]}T10:00:00"},
                  live_dir=tmp_path / "live", lib_dir=tmp_path / "lib")

    def test_quotes_the_surrounding_sentence(self, tmp_path):
        from src.features import live_entities
        self._file(tmp_path, "t1",
                   "We compared Brookfield's fee load to peers and passed on "
                   "the vintage for now.")
        out = live_entities.said_before(
            "Brookfield", live_dir=tmp_path / "live", lib_dir=tmp_path / "lib")
        assert out and "fee load" in out[0]["excerpt"]
        assert out[0]["title"] == "Fife Capital"

    def test_absent_names_and_the_current_session_are_skipped(self, tmp_path):
        from src.features import live_entities
        self._file(tmp_path, "t2", "Nothing about them here at all.")
        assert live_entities.said_before(
            "Zephyr Crest", live_dir=tmp_path / "live",
            lib_dir=tmp_path / "lib") == []
        self._file(tmp_path, "t3", "Albizia came up twice in passing.")
        assert live_entities.said_before(
            "Albizia", exclude_id="t3", live_dir=tmp_path / "live",
            lib_dir=tmp_path / "lib") == []
