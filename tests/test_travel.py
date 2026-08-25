"""Travel planner domain, persistence and safety invariants."""
import datetime as dt

import pytest

from src.connectors.graph import GraphConnector
from src.features.travel.models import DestinationAnchor, MeetingCandidate, TravelSettings
from src.features.travel.outreach import classify_reply, draft_wave, send_wave
from src.features.travel.models import OfficeResolution
from src.features.travel.planner import (
    allocate_cities, directory, new_trip, optimize, resolve_locations,
)
from src.features.travel.providers import AmadeusHotelConnector, GoogleTravelConnector, rank_hotels
from src.features.travel.store import TravelStore
from src.schemas import CompanyRecord, ContactRecord, EmailMessage, FundRecord, NoteRecord


def candidate(cid="p1", city="London", tier=1):
    return MeetingCandidate(
        id=cid, name=f"Person {cid}", email=f"{cid}@example.com", company=f"Firm {cid}",
        city=city, country="UK", tier=tier, selected=True, status="selected",
        office={"address": f"1 {cid} Street", "latitude": 51.5 + len(cid) * .002,
                "longitude": -.12, "confidence": .9, "confirmed": True},
    )


def trip_with(*people, start="2026-09-07", end="2026-09-11"):
    return new_trip("London week", DestinationAnchor(type="country", id="UK", label="UK"),
                    start, end, list(people), TravelSettings(nightly_budget_gbp=250))


def test_directory_joins_contacts_to_company_location():
    result = directory(
        [CompanyRecord(id="co", name="Alpha", city="London", country="UK")],
        [ContactRecord(id="p", name="Ada", email="a@alpha.com", company="Alpha")],
    )
    assert result["countries"] == ["UK"]
    assert result["candidates"][0]["city"] == "London"


def test_directory_never_joins_blank_names():
    """One empty-named company row in Notion turned every employer-less
    contact into a 'matched' candidate with no city, and the whole trip
    planned around a city called Unresolved (17 Aug 2026)."""
    result = directory(
        [CompanyRecord(id="ghost", name="", city="", country=""),
         CompanyRecord(id="co", name="Alpha", city="London", country="UK")],
        [ContactRecord(id="p1", name="No Employer", email="x@y.com", company=""),
         ContactRecord(id="p2", name="Ada", email="a@alpha.com", company="Alpha")],
    )
    assert [c["name"] for c in result["candidates"]] == ["Ada"]


def test_directory_resolves_the_first_of_joined_employers():
    """ContactRecord.company holds multiple employers as 'A; B'."""
    result = directory(
        [CompanyRecord(id="co", name="Beta", city="Paris", country="France")],
        [ContactRecord(id="p", name="Ada", email="a@b.com", company="Alpha; Beta")],
    )
    assert result["candidates"][0]["city"] == "Paris"


def test_directory_signals_aggregate_and_rank_the_suggested_list():
    companies = [CompanyRecord(id="co-a", name="Alpha", city="London", country="UK"),
                 CompanyRecord(id="co-b", name="Beta", city="London", country="UK")]
    contacts = [ContactRecord(id="p1", name="Ada", email="a@alpha.com", company="Alpha"),
                ContactRecord(id="p2", name="Bob", email="b@beta.com", company="Beta"),
                ContactRecord(id="lp-1", name="Lena Park", email="l@lp.com", company="Beta"),
                ContactRecord(id="lp-2", name="Omar Reyes", email="o@lp.com", company="Beta")]
    funds = [FundRecord(id="f1", name="Alpha Fund I", company="Alpha", status="Track",
                        quality="High", comments="Worth  tracking closely.",
                        recommended_by_ids=["lp-1", "lp-2"]),
             FundRecord(id="f2", name="Alpha Fund II", company="Alpha",
                        status="Not met", recommended_by_ids=["lp-1"])]
    notes = [NoteRecord(id="n1", name="GP call", date="2026-03-01", company_ids=["co-a"]),
             NoteRecord(id="n2", name="Reference", date="2026-06-12", fund_ids=["f1"]),
             NoteRecord(id="n3", name="Both relations", date="2026-01-05",
                        company_ids=["co-a"], fund_ids=["f2"])]
    result = directory(companies, contacts, funds=funds, notes=notes)
    # Alpha carries the signals, so it leads the suggested list — the manager
    # row itself first (trips are planned around funds to meet, not named
    # people), then its contact.
    assert [c["name"] for c in result["candidates"]][:2] == ["Alpha", "Ada"]
    manager = result["candidates"][0]
    assert manager["id"].startswith("company-") and manager["email"] == ""
    assert manager["signals"]["funds"] == ["Alpha Fund I", "Alpha Fund II"]
    signals = result["candidates"][0]["signals"]
    assert signals["status"] == "Track" and signals["quality"] == "High"
    # Union across funds: lp-1 recommends both funds but counts once.
    assert signals["reccos"] == 2
    assert signals["recommenders"] == ["Lena Park", "Omar Reyes"]
    # A note related through both the company and one of its funds counts once.
    assert signals["notes"] == 3 and signals["last_note"] == "2026-06-12"
    assert signals["comment"] == "Worth tracking closely."
    # Beta has nothing on record: no fabricated row of zeros, and no
    # manager row either — only fund-backed companies earn one.
    beta = next(c for c in result["candidates"] if c["name"] == "Bob")
    assert beta["signals"] is None
    assert not any(c["name"] == "Beta" for c in result["candidates"])
    # The managers list carries the same signals for anchor search.
    assert next(m for m in result["managers"] if m["name"] == "Alpha")["signals"] == signals


def test_directory_signals_join_funds_by_company_relation_id():
    """Many fund rows have a blank free-text 'Company Name'; the Company
    relation still ties them to their manager."""
    result = directory(
        [CompanyRecord(id="co-a", name="Innovius", city="Boston", country="US")],
        [ContactRecord(id="p", name="Ada", email="a@i.com", company="Innovius")],
        funds=[FundRecord(id="f", name="Innovius Fund II", company="",
                          company_ids=["co-a"], status="Met", quality="High",
                          recommended_by_ids=["lp-9"])],
        notes=[],
    )
    signals = result["candidates"][0]["signals"]
    assert signals["quality"] == "High" and signals["reccos"] == 1


def test_directory_signals_ignore_declined_and_unreviewed_funds():
    result = directory(
        [CompanyRecord(id="co", name="Alpha", city="London", country="UK")],
        [ContactRecord(id="p", name="Ada", email="a@alpha.com", company="Alpha")],
        funds=[FundRecord(id="f", name="Fund", company="Alpha",
                          status="Track (Declined)", quality="Low")],
        notes=[],
    )
    assert result["candidates"][0]["signals"] is None


def test_resolve_locations_hints_the_office_in_the_visited_city():
    """A multi-office Address record (Felix's 'City, Country — address'
    lines) must geocode the office in the city being visited, never the
    whole list and never another city's office."""
    class FakeGoogle:
        def __init__(self):
            self.hints = []

        def resolve_office(self, company, city, country, hint):
            self.hints.append(hint)
            return OfficeResolution()

        def timezone_at(self, lat, lng, city):
            return "UTC"

    trip = trip_with(candidate("p1", city="Sydney"))
    company = CompanyRecord(
        id="co", name="Firm p1", city="London", country="UK",
        office_address=("London, UK — 25 Old Broad Street\n"
                        "Sydney, Australia — Level 15, 1 Macquarie Place"))
    google = FakeGoogle()
    resolve_locations(trip, [company], google)
    assert google.hints == ["Level 15, 1 Macquarie Place"]


def test_city_allocation_is_contiguous_and_weighted():
    cities = allocate_cities([candidate("a", "London"), candidate("b", "London"),
                              candidate("c", "Edinburgh")], "2026-09-07", "2026-09-11")
    assert [c.name for c in cities] == ["London", "Edinburgh"]
    assert cities[0].start_date == "2026-09-07"
    assert cities[-1].end_date == "2026-09-11"


def test_optimizer_requires_confirmed_office_and_produces_exclusive_slots():
    a, b = candidate("a"), candidate("b")
    trip = trip_with(a, b)
    trip.candidates[1].office.confirmed = False
    optimize(trip, [])
    assert len(trip.candidates[0].slots) >= 2
    assert not trip.candidates[1].slots
    starts = [s.start for c in trip.candidates for s in c.slots]
    assert len(starts) == len(set(starts))


def test_optimizer_respects_lunch_and_calendar_busy_time():
    trip = trip_with(candidate())
    from src.schemas import CalendarEvent
    event = CalendarEvent(id="busy", start="2026-09-07T09:00:00", end="2026-09-07T12:30:00")
    optimize(trip, [event])
    for slot in trip.candidates[0].slots:
        start = dt.datetime.fromisoformat(slot.start)
        end = dt.datetime.fromisoformat(slot.end)
        assert not (start.date() == dt.date(2026, 9, 7) and start.time() < dt.time(13, 30))
        assert not (start.time() < dt.time(13, 30) and dt.time(12, 30) < end.time())


def test_hotel_hard_cap_and_balanced_ranking():
    connector = AmadeusHotelConnector()
    connector.live = False
    hotels = connector.search("london-uk", "London", "UK", "2026-09-07", "2026-09-10", 200, (51.5, -.12))
    ranked = rank_hotels(hotels, [(51.51, -.11)], GoogleTravelConnector(), TravelSettings(nightly_budget_gbp=200))
    assert ranked
    assert all(h.nightly_gbp <= 200 for h in ranked)
    assert ranked == sorted(ranked, key=lambda h: (-h.score, h.nightly_gbp, h.name))


def test_store_round_trip_and_action_idempotency(tmp_path):
    store = TravelStore(tmp_path / "travel.db")
    trip = store.save(trip_with(candidate()))
    assert store.get(trip.id).name == trip.name
    assert store.action_once(trip.id, "send-1", "send", {"x": 1})
    assert not store.action_once(trip.id, "send-1", "send", {"x": 1})


def test_wave_refuses_targets_with_no_email(tmp_path):
    """A manager row is added without a person, so it has no address to
    write to — the wave names it rather than sending into a void."""
    manager = candidate("company-alpha")
    manager.email = ""
    manager.slots = [
        {"start": "2026-09-08T09:00:00", "end": "2026-09-08T10:00:00"},
        {"start": "2026-09-08T11:00:00", "end": "2026-09-08T12:00:00"},
    ]
    trip = trip_with(manager)
    with pytest.raises(ValueError, match="No email on record"):
        draft_wave(trip, 1)


def test_wave_requires_two_slots_and_never_double_sends(tmp_path):
    trip = trip_with(candidate())
    with pytest.raises(ValueError, match="two feasible"):
        draft_wave(trip, 1)
    optimize(trip, [])
    messages = draft_wave(trip, 1)
    assert len(messages) == 1 and "1." in messages[0].body
    store = TravelStore(tmp_path / "travel.db")
    graph = GraphConnector()
    send_wave(trip, 1, graph, store, allow_demo=True)
    first_id = messages[0].graph_message_id
    send_wave(trip, 1, graph, store, allow_demo=True)
    assert messages[0].graph_message_id == first_id
    assert len(store.actions(trip.id)) == 1


def test_reply_exact_option_is_accepted_but_vague_yes_is_ambiguous():
    trip = trip_with(candidate())
    optimize(trip, [])
    person = trip.candidates[0]
    exact = classify_reply(EmailMessage(id="r1", body="Option 2 works for me"), person)
    vague = classify_reply(EmailMessage(id="r2", body="Yes, sounds good"), person)
    assert exact.kind == "accepted" and exact.selected_slot_id == person.slots[1].id
    assert vague.kind == "ambiguous"


def test_reoptimize_preserves_offered_slots_and_their_times():
    """Re-optimizing after a wave went out must keep what was emailed:
    the offered candidate's slots verbatim, and their times off-limits to
    everyone else. Both used to be violated — optimize wiped offered slots
    and could hand the exact emailed times to another candidate."""
    trip = trip_with(candidate("a"), candidate("b"))
    optimize(trip, [])
    person = trip.candidates[0]
    offered = [s.start for s in person.slots]
    person.status = "offered"          # what send_wave sets
    for s in person.slots:
        s.status = "offered"
    optimize(trip, [])
    assert [s.start for s in person.slots] == offered
    assert all(s.status == "offered" for s in person.slots)
    taken = set(offered)
    other = trip.candidates[1]
    assert other.slots and all(s.start not in taken for s in other.slots)


def test_confident_decline_releases_slots_and_frees_the_times():
    from src.features.travel.models import ReplyDecision
    from src.features.travel.outreach import apply_declines

    trip = trip_with(candidate("a"), candidate("b"))
    optimize(trip, [])
    person = trip.candidates[0]
    person.status = "offered"
    for s in person.slots:
        s.status = "offered"
    trip.replies.append(ReplyDecision(id="r", candidate_id=person.id,
                                      message_id="m1", kind="declined",
                                      confidence=.9))
    assert apply_declines(trip) == [person.id]
    assert person.status == "declined"
    assert all(s.status == "released" for s in person.slots)
    assert trip.replies[0].state == "handled"
    # The next optimize clears the declined candidate and reuses the pool.
    optimize(trip, [])
    assert not person.slots


def test_low_confidence_decline_stays_in_the_review_ledger():
    from src.features.travel.models import ReplyDecision
    from src.features.travel.outreach import apply_declines

    trip = trip_with(candidate("a"))
    person = trip.candidates[0]
    trip.replies.append(ReplyDecision(id="r", candidate_id=person.id,
                                      message_id="m1", kind="declined",
                                      confidence=.5))
    assert apply_declines(trip) == []
    assert trip.replies[0].state == "pending" and person.status == "selected"
