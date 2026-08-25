"""Trip construction and constraint-based meeting-slot allocation."""
from __future__ import annotations

import datetime as dt
import re
import uuid
from collections import defaultdict

from src.features.offices import office_for_city
from src.schemas import CalendarEvent, CompanyRecord, ContactRecord, FundRecord, NoteRecord
from .models import (
    DestinationAnchor, MeetingCandidate, MeetingSlot, TransferBlock,
    TravelSettings, TravelTrip, TripCity,
)
from .providers import CITY_TIMEZONES, GoogleTravelConnector, city_coordinates, haversine_km
from .store import utcnow


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "unknown"


# Why a manager is worth the meeting, ranked. Statuses come from the Funds
# DB verbatim; declined variants ("Track (Declined)") deliberately score 0.
_STATUS_RANK = {"Invested": 6, "Track": 5, "In diligence": 4, "Exited": 3, "Met": 2}
_QUALITY_RANK = {"High": 3, "Medium": 1}


def company_signals(companies: list[CompanyRecord], contacts: list[ContactRecord],
                    funds: list[FundRecord], notes: list[NoteRecord]) -> dict:
    """Per-company conviction signals, keyed by casefolded company name.

    Companies with nothing on record are absent from the result — the
    caller treats a miss as "no signals" rather than a row of zeros.
    """
    company_by_id = {c.id: c.name.casefold() for c in companies
                     if c.id and (c.name or "").strip()}
    funds_by_company: dict[str, list[FundRecord]] = defaultdict(list)
    for fund in funds or []:
        # The 'Company' relation is authoritative; the free-text 'Company
        # Name' (blank on many rows) is the fallback join.
        key = next((company_by_id[cid] for cid in fund.company_ids
                    if cid in company_by_id), "") \
            or (fund.company or "").strip().casefold()
        if key:
            funds_by_company[key].append(fund)
    contact_names = {c.id: c.name for c in contacts if c.id}
    fund_company: dict[str, str] = {}
    for key, group in funds_by_company.items():
        for fund in group:
            if fund.id:
                fund_company[fund.id] = key
    note_ids: dict[str, set] = defaultdict(set)
    last_note: dict[str, str] = {}
    for note in notes or []:
        if not note.id:
            continue
        keys = {company_by_id[cid] for cid in note.company_ids if cid in company_by_id}
        keys |= {fund_company[fid] for fid in note.fund_ids if fid in fund_company}
        for key in keys:
            note_ids[key].add(note.id)
            if note.date and note.date > last_note.get(key, ""):
                last_note[key] = note.date
    signals = {}
    for key in set(funds_by_company) | set(note_ids):
        group = funds_by_company.get(key, [])
        ranked = sorted(group, key=lambda f: (
            -_QUALITY_RANK.get(f.quality, 0), -_STATUS_RANK.get(f.status, 0), f.name))
        status = max((f.status for f in group),
                     key=lambda s: _STATUS_RANK.get(s, 0), default="")
        quality = ranked[0].quality if ranked else ""
        recommenders = set()
        for fund in group:
            recommenders.update(fund.recommended_by_ids)
        comment = next((" ".join(f.comments.split()) for f in ranked if f.comments.strip()), "")
        entry = {
            "status": status if _STATUS_RANK.get(status, 0) >= 2 else "",
            "quality": quality,
            # The funds behind the signal, best first — what the suggested
            # list's search matches when the user types a fund's name.
            "funds": [f.name for f in ranked if (f.name or "").strip()][:6],
            "reccos": len(recommenders),
            "recommenders": sorted(contact_names[i] for i in recommenders
                                   if i in contact_names)[:3],
            "notes": len(note_ids.get(key, ())),
            "last_note": last_note.get(key, ""),
            "comment": comment[:157] + "…" if len(comment) > 160 else comment,
        }
        entry["score"] = (_STATUS_RANK.get(status, 0) * 20
                          + _QUALITY_RANK.get(quality, 0) * 10
                          + min(entry["reccos"], 5) * 6
                          + min(entry["notes"], 10))
        if entry["score"] or entry["notes"]:
            signals[key] = entry
    return signals


def directory(companies: list[CompanyRecord], contacts: list[ContactRecord],
              funds: list[FundRecord] | None = None,
              notes: list[NoteRecord] | None = None) -> dict:
    # Blank names on either side must never join: one empty-named company row
    # in Notion turned every employer-less contact into a "matched" candidate
    # with no city, and the whole trip planned around a city called
    # Unresolved (17 Aug 2026 — all 10,867 contacts, one phantom company).
    by_name = {c.name.casefold(): c for c in companies if (c.name or "").strip()}
    signals = company_signals(companies, contacts, funds or [], notes or [])
    candidates = []
    # Managers first: trips are planned around funds to meet, not named
    # people (user, 21 Aug 2026). Every company with a fund on record gets a
    # selectable row of its own; its contacts follow at the same signal
    # score, so the stable sort below keeps the manager above them.
    for company in companies:
        key = (company.name or "").strip().casefold()
        sig = signals.get(key) if key else None
        if not (sig and sig.get("funds")):
            continue
        candidates.append((MeetingCandidate(
            id=f"company-{company.id or slug(company.name)}",
            company_id=company.id or "", name=company.name, email="",
            title="Manager", company=company.name, city=company.city,
            country=company.country, selected=False, status="candidate",
            office={"query": company.office_address or company.name},
        ), sig))
    for person in contacts:
        if not (person.company or "").strip():
            continue
        # ContactRecord.company joins multiple employers with "; " — the
        # first that resolves wins.
        company = next((by_name[part.casefold()] for part in person.company.split("; ")
                        if part.casefold() in by_name), None)
        if not company:
            continue
        candidates.append((MeetingCandidate(
            id=person.id or f"contact-{slug(person.name)}", contact_id=person.id or "",
            company_id=company.id or "", name=person.name, email=person.email,
            title=person.title, company=company.name, city=company.city,
            country=company.country, selected=False, status="candidate",
            office={"query": company.office_address or company.name},
        ), signals.get(company.name.casefold())))
    # Strongest reasons to meet first; the sort is stable, so companies
    # without signals keep their existing (Notion) order.
    candidates.sort(key=lambda pair: -(pair[1] or {}).get("score", 0))
    managers = [{"id": c.id or slug(c.name), "name": c.name, "city": c.city,
                 "country": c.country, "office_address": c.office_address,
                 "signals": signals.get(c.name.casefold())}
                for c in companies]
    countries = sorted({c.country for c in companies if c.country})
    return {"countries": countries, "managers": managers,
            "candidates": [{**c.model_dump(), "signals": sig} for c, sig in candidates]}


def allocate_cities(candidates: list[MeetingCandidate], start: str, end: str) -> list[TripCity]:
    groups: dict[tuple[str, str], list[MeetingCandidate]] = defaultdict(list)
    for c in candidates:
        groups[(c.city or "Unresolved", c.country)].append(c)
    ranked = sorted(groups, key=lambda k: (-len(groups[k]), k[0]))
    ordered = ranked[:1]
    remaining = ranked[1:]
    while remaining:
        prior = city_coordinates(*ordered[-1])
        nearest = min(remaining, key=lambda k: haversine_km(prior, city_coordinates(*k)))
        ordered.append(nearest)
        remaining.remove(nearest)
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    days = (last - first).days + 1
    cities = []
    cursor = first
    remaining_weight = sum(len(groups[k]) for k in ordered) or 1
    for i, key in enumerate(ordered):
        remaining_days = (last - cursor).days + 1
        if i == len(ordered) - 1:
            span = remaining_days
        else:
            span = max(1, round(days * len(groups[key]) / remaining_weight))
            span = min(span, remaining_days - (len(ordered) - i - 1))
        finish = cursor + dt.timedelta(days=max(0, span - 1))
        lat, lng = city_coordinates(*key)
        cities.append(TripCity(id=slug(f"{key[0]}-{key[1]}"), name=key[0], country=key[1],
                               start_date=cursor.isoformat(), end_date=finish.isoformat(),
                               latitude=lat, longitude=lng,
                               timezone=CITY_TIMEZONES.get(key[0].casefold(), "UTC"), order=i))
        cursor = finish + dt.timedelta(days=1)
        remaining_weight -= len(groups[key])
    return cities


def new_trip(name: str, anchor: DestinationAnchor, start: str, end: str,
             candidates: list[MeetingCandidate], settings: TravelSettings) -> TravelTrip:
    now = utcnow()
    selected = []
    for c in candidates:
        copy = c.model_copy(deep=True)
        copy.selected = True
        copy.status = "selected"
        copy.duration_minutes = settings.default_duration_minutes
        selected.append(copy)
    cities = allocate_cities(selected, start, end)
    transfers = []
    for left, right in zip(cities, cities[1:]):
        day = dt.date.fromisoformat(right.start_date)
        transfers.append(TransferBlock(
            id=f"transfer-{left.id}-{right.id}", from_city_id=left.id,
            to_city_id=right.id, start=f"{day.isoformat()}T07:00:00",
            end=f"{day.isoformat()}T09:00:00", details="Confirm train/flight details",
        ))
    return TravelTrip(id=str(uuid.uuid4()), name=name, anchor=anchor,
                      start_date=start, end_date=end, settings=settings,
                      timezone=cities[0].timezone if cities else "UTC",
                      cities=cities, transfers=transfers, candidates=selected,
                      created_at=now, updated_at=now)


def resolve_locations(trip: TravelTrip, companies: list[CompanyRecord],
                      google: GoogleTravelConnector) -> TravelTrip:
    company_by_id = {c.id: c for c in companies}
    company_by_name = {c.name.casefold(): c for c in companies}
    for candidate in trip.candidates:
        company = company_by_id.get(candidate.company_id) or company_by_name.get(candidate.company.casefold())
        # Multi-office records (one per line, "City, Country — address") hint
        # the office in the city being visited — never the whole list.
        stored = company.office_address if company else ""
        candidate.office = google.resolve_office(
            candidate.company, candidate.city, candidate.country,
            office_for_city(stored, candidate.city),
        )
    for city in trip.cities:
        if city.latitude is not None and city.longitude is not None:
            city.timezone = google.timezone_at(city.latitude, city.longitude, city.name)
    if trip.cities:
        trip.timezone = trip.cities[0].timezone
    return trip


def _parse_hhmm(value: str) -> dt.time:
    return dt.time.fromisoformat(value)


def _busy(events: list[CalendarEvent], transfers: list[TransferBlock]) -> list[tuple[dt.datetime, dt.datetime]]:
    out = []
    for e in events:
        try:
            out.append((dt.datetime.fromisoformat(e.start.replace("Z", "+00:00")).replace(tzinfo=None),
                        dt.datetime.fromisoformat(e.end.replace("Z", "+00:00")).replace(tzinfo=None)))
        except (ValueError, TypeError):
            pass
    for t in transfers:
        if not t.confirmed:
            continue
        try:
            out.append((dt.datetime.fromisoformat(t.start), dt.datetime.fromisoformat(t.end)))
        except ValueError:
            pass
    return out


def optimize(trip: TravelTrip, events: list[CalendarEvent], options_per_person: int = 3,
             google: GoogleTravelConnector | None = None) -> TravelTrip:
    """Offer globally exclusive, pairwise travel-feasible slots.

    Accepted/scheduled meetings remain fixed. CP-SAT is used when available;
    the fallback applies the same deterministic constraints for demo installs
    that have not refreshed requirements yet.
    """
    city_by_name = {(c.name.casefold(), c.country.casefold()): c for c in trip.cities}
    busy = _busy(events, trip.transfers)
    # Times already promised to someone stay off the table: accepted slots
    # are booked, and slots in a sent wave ("offered") are live offers a
    # recipient may still take. Re-optimizing used to wipe offered slots and
    # could hand the exact times just emailed to a different candidate.
    # "released" slots (declined, superseded) return to the pool.
    fixed = []
    for c in trip.candidates:
        for s in c.slots:
            if s.status in ("accepted", "offered"):
                fixed.append((dt.datetime.fromisoformat(s.start), dt.datetime.fromisoformat(s.end)))
        if c.status not in ("accepted", "scheduled", "offered"):
            c.slots = []
            c.explanation = ""
    busy += fixed
    active = [c for c in trip.candidates if c.selected and c.email
              and c.status not in ("accepted", "scheduled", "declined", "offered")]
    all_slots: list[tuple[MeetingCandidate, dt.datetime, dt.datetime, str]] = []
    for candidate in active:
        city = city_by_name.get((candidate.city.casefold(), candidate.country.casefold()))
        if not city or not candidate.office.confirmed:
            candidate.explanation = "Confirm the office location before scheduling."
            continue
        day = dt.date.fromisoformat(city.start_date)
        last = dt.date.fromisoformat(city.end_date)
        duration = dt.timedelta(minutes=candidate.duration_minutes)
        while day <= last:
            if day.weekday() < 5:
                cursor = dt.datetime.combine(day, _parse_hhmm(trip.settings.work_start))
                finish = dt.datetime.combine(day, _parse_hhmm(trip.settings.work_end))
                lunch_s = dt.datetime.combine(day, _parse_hhmm(trip.settings.lunch_start))
                lunch_e = dt.datetime.combine(day, _parse_hhmm(trip.settings.lunch_end))
                while cursor + duration <= finish:
                    end = cursor + duration
                    if not (cursor < lunch_e and lunch_s < end) and not any(cursor < be and bs < end for bs, be in busy):
                        all_slots.append((candidate, cursor, end, city.id))
                    cursor += dt.timedelta(minutes=15)
            day += dt.timedelta(days=1)
    travel: dict[tuple[str, str], float] = {}
    located = [c for c in active if c.office.latitude is not None and c.office.longitude is not None]
    if located:
        points = [(c.office.latitude, c.office.longitude) for c in located]
        matrix = (google or GoogleTravelConnector()).route_minutes(
            points, points, trip.settings.travel_mode)
        for i, a in enumerate(located):
            for j, b in enumerate(located):
                travel[(a.id, b.id)] = matrix[i][j]
    chosen = _solve(active, all_slots, options_per_person, travel)
    for candidate, start, end, city_id in chosen:
        candidate.slots.append(MeetingSlot(
            id=f"slot-{candidate.id}-{start.strftime('%Y%m%d%H%M')}",
            start=start.isoformat(), end=end.isoformat(), city_id=city_id,
        ))
    for candidate in active:
        candidate.slots.sort(key=lambda s: s.start)
        if len(candidate.slots) < 2 and not candidate.explanation:
            candidate.explanation = (
                "Fewer than two conflict-free options. Extend the trip, shorten the meeting, "
                "or move this person to the next wave."
            )
    trip.status = "ready" if all(len(c.slots) >= 2 for c in active) and all(t.confirmed for t in trip.transfers) else "planning"
    return trip


def _solve(active: list[MeetingCandidate], rows, options_per_person: int,
           travel_by_pair: dict[tuple[str, str], float]):
    if not rows:
        return []
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return _greedy(rows, options_per_person, travel_by_pair)
    model = cp_model.CpModel()
    variables = [model.new_bool_var(f"x{i}") for i in range(len(rows))]
    by_candidate, by_start = defaultdict(list), defaultdict(list)
    for i, (candidate, start, _end, _city) in enumerate(rows):
        by_candidate[candidate.id].append(i)
        by_start[start].append(i)
    covered = {}
    for candidate in active:
        indexes = by_candidate.get(candidate.id, [])
        if not indexes:
            continue
        covered[candidate.id] = model.new_bool_var(f"covered_{slug(candidate.id)}")
        model.add(sum(variables[i] for i in indexes) >= 2 * covered[candidate.id])
        model.add(sum(variables[i] for i in indexes) <= options_per_person)
    for indexes in by_start.values():
        model.add(sum(variables[i] for i in indexes) <= 1)
    # Every possible pair of accepted offers must leave enough travel time.
    for i, (a, astart, aend, _acity) in enumerate(rows):
        if a.office.latitude is None:
            continue
        for j in range(i + 1, len(rows)):
            b, bstart, bend, _bcity = rows[j]
            if a.id == b.id or astart.date() != bstart.date() or b.office.latitude is None:
                continue
            travel = 0 if a.city != b.city else max(5, round(travel_by_pair.get(
                (a.id, b.id), haversine_km(
                    (a.office.latitude, a.office.longitude),
                    (b.office.latitude, b.office.longitude)) / 25 * 60)))
            incompatible = (astart < bend + dt.timedelta(minutes=travel)
                            and bstart < aend + dt.timedelta(minutes=travel))
            if incompatible:
                model.add(variables[i] + variables[j] <= 1)
    objective = []
    for c in active:
        if c.id in covered:
            objective.append(covered[c.id] * (100000 if c.tier == 1 else 10000))
    objective.extend(v * (100 - min(90, row[1].hour * 4 + row[1].minute // 15))
                     for v, row in zip(variables, rows))
    model.maximize(sum(objective))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 4
    solver.solve(model)
    return [row for row, var in zip(rows, variables) if solver.value(var)]


def _greedy(rows, options_per_person, travel_by_pair=None):
    chosen, counts = [], defaultdict(int)
    used = set()
    for row in sorted(rows, key=lambda r: (r[0].tier, r[1], r[0].name)):
        candidate, start, _end, _city = row
        if counts[candidate.id] >= options_per_person or start in used:
            continue
        chosen.append(row)
        counts[candidate.id] += 1
        used.add(start)
    return chosen
