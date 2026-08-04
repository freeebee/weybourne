"""Duplicate detection covers entity databases only.

Meeting notes repeat their titles by design, so name similarity across notes
generated a vast bucket of meaningless pairs that crowded genuine contact
duplicates out of the adjudication budget.
"""
from src.features.felix import detect
from src.features.felix.run import DEDUPE_DBS


def _card(cid, name, db):
    return {"id": cid, "db": db, "name": name, "email": "", "domain": "",
            "url": "", "icon": None, "archived": False, "created": "",
            "edited": "", "plain": {}, "raw": {}, "relations": {},
            "title_prop": "Name"}


def test_notes_are_out_of_scope():
    assert "notes" not in DEDUPE_DBS
    assert set(DEDUPE_DBS) == {"contacts", "companies", "funds"}


def test_repeated_meeting_titles_would_otherwise_pair_up():
    """Guards the reason for the exclusion: these titles DO score as
    look-alikes, which is exactly why notes must not be scanned."""
    notes = [_card("n1", "Call with Axiom Asia", "notes"),
             _card("n2", "Call with Axiom Asia Fund", "notes"),
             _card("n3", "Call with Axiom Asia Ltd", "notes")]
    pairs = detect.find_fuzzy_duplicate_pairs(notes)
    assert pairs, "expected note titles to look alike by name score"
