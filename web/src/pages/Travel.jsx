import React from "react";
import { getRetry, patch, post } from "../api.js";
import { Banner, Button, Card, Chip, ErrorNote, SearchSelect, SectionHead, Spinner, useTabScrollMemory } from "../ui.jsx";
import * as uiStore from "../uiStore.js";

const TABS = [
  { key: "trip", label: "Trip" },
  { key: "map", label: "Map & hotels" },
  { key: "itinerary", label: "Itinerary" },
  { key: "outreach", label: "Outreach" },
];

const today = () => new Date().toISOString().slice(0, 10);
const plusDays = (n) => {
  const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10);
};

let mapsPromise;
function loadGoogleMaps(key) {
  if (window.google?.maps) return Promise.resolve(window.google);
  if (!mapsPromise) mapsPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly`;
    script.async = true; script.onload = () => resolve(window.google); script.onerror = reject;
    document.head.appendChild(script);
  });
  return mapsPromise;
}

function Field({ label, children }) {
  return <label className="travel-field"><span className="microlabel">{label}</span>{children}</label>;
}

function IntegrationStrip({ integrations }) {
  if (!integrations) return null;
  return <div className="travel-integrations">
    {[["NOTION", true], ["OUTLOOK WRITE", integrations.graph_write],
      ["GOOGLE MAPS", integrations.maps], ["AMADEUS", integrations.hotels]].map(([label, live]) =>
      <span key={label}><i data-live={live ? "1" : "0"} />{label} · {live ? "LIVE" : "DEMO"}</span>)}
  </div>;
}

export function filterTravelCandidates(candidates, anchor) {
  if (anchor.type === "country" && anchor.id) return candidates.filter((c) => c.country === anchor.id);
  if (anchor.type === "manager" && anchor.id) {
    if (anchor.city) return candidates.filter((c) => c.city === anchor.city && (!anchor.country || c.country === anchor.country));
    return candidates.filter((c) => c.company_id === anchor.id);
  }
  if (anchor.type === "event" && anchor.city) return candidates.filter((c) => c.city === anchor.city);
  return candidates;
}

/* Rows the planner added for the firm itself rather than a person — the
   usual thing to add is the fund to meet, not a named contact. */
export const isManagerRow = (c) => String(c.id || "").startsWith("company-");

/* The search matches the funds behind a manager as well as the row's own
   fields, so typing a fund's name surfaces who runs it. */
export function candidateMatchesQuery(c, needle) {
  return [c.name, c.title, c.company, c.city, c.country, c.email,
    ...((c.signals && c.signals.funds) || [])]
    .some((value) => String(value || "").toLowerCase().includes(needle));
}

export function candidateSignalChips(signals) {
  if (!signals) return [];
  const chips = [];
  const status = (signals.status || "").toUpperCase();
  if (["INVESTED", "TRACK", "IN DILIGENCE", "EXITED"].includes(status))
    chips.push({ text: status, tone: status === "INVESTED" ? "brass" : "teal" });
  if (signals.quality === "High") chips.push({ text: "HIGH QUALITY", tone: "teal" });
  if (signals.reccos > 0) chips.push({
    text: `RECCOS · ${signals.reccos}`, tone: "teal",
    hint: (signals.recommenders || []).length
      ? `Recommended by ${signals.recommenders.join(", ")}${signals.reccos > signals.recommenders.length ? " and others" : ""}`
      : undefined,
  });
  if (signals.notes > 0) chips.push({
    text: `NOTES · ${signals.notes}`, tone: "plain",
    hint: signals.last_note ? `Last note ${signals.last_note}` : undefined,
  });
  return chips;
}

function SignalLine({ signals }) {
  const chips = candidateSignalChips(signals);
  if (!chips.length && !signals?.comment) return null;
  return <span className="travel-signals">
    {chips.map((chip) => <i key={chip.text} data-tone={chip.tone} title={chip.hint}>{chip.text}</i>)}
    {signals?.comment && <em title={signals.comment}>{signals.comment}</em>}
  </span>;
}

export function travelMapPoints(trip, visible) {
  const points = [];
  trip.candidates.filter((c) => visible.has(c.id) && c.office.latitude != null).forEach((c) =>
    points.push({ id: c.id, label: c.company, lat: c.office.latitude, lng: c.office.longitude, kind: "office" }));
  trip.hotels.filter((h) => h.selected && h.latitude != null).forEach((h) =>
    points.push({ id: h.id, label: h.name, lat: h.latitude, lng: h.longitude, kind: "hotel" }));
  return points;
}

function CandidatePicker({ options, anchor, selected, setSelected }) {
  const [query, setQuery] = React.useState("");
  React.useEffect(() => setQuery(""), [anchor.type, anchor.id]);
  const allRows = filterTravelCandidates(options?.candidates || [], anchor);
  const needle = query.trim().toLowerCase();
  const matchingRows = needle
    ? allRows.filter((c) => candidateMatchesQuery(c, needle)) : allRows;
  const rows = matchingRows.slice(0, 100);
  const toggle = (id) => setSelected((old) => old.includes(id) ? old.filter((x) => x !== id) : [...old, id]);
  return <Card style={{ padding: 0, overflow: "hidden" }}>
    <div className="travel-list-head"><span>Suggested meetings · {matchingRows.length}</span>
      <button type="button" onClick={() => setSelected((old) => [...new Set([...old, ...rows.map((c) => c.id)])])}>Select shown</button></div>
    <div className="travel-candidate-search">
      <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter by fund, manager, person, or city…" aria-label="Filter suggested meetings" />
      {matchingRows.length > rows.length && <small>Showing the first {rows.length}. Refine your search to narrow the list.</small>}
    </div>
    <div className="travel-candidates">
      {rows.map((c) => <button type="button" key={c.id} className="travel-candidate" data-on={selected.includes(c.id) ? "1" : "0"}
        onClick={() => toggle(c.id)}>
        <span className="travel-check">{selected.includes(c.id) ? "✓" : ""}</span>
        <span><b>{c.name}</b><small>{isManagerRow(c)
          ? ((c.signals?.funds || []).slice(0, 2).join(" · ") || "Manager")
          : `${c.title || "Contact"} · ${c.company}`}</small>
          <SignalLine signals={c.signals} /></span>
        <span className="mono travel-place">{c.city || "NO CITY"}<br />{c.country}</span>
      </button>)}
      {!rows.length && <div className="travel-empty">No managers or contacts match this destination.</div>}
    </div>
  </Card>;
}

function TripSetup({ options, onCreated, busy, setBusy, setError }) {
  const [type, setType] = React.useState("country");
  const [anchorId, setAnchorId] = React.useState("");
  const [name, setName] = React.useState("Investment meetings");
  const [start, setStart] = React.useState(plusDays(14));
  const [end, setEnd] = React.useState(plusDays(18));
  const [budget, setBudget] = React.useState(250);
  const [selected, setSelected] = React.useState([]);
  const values = type === "country" ? (options?.countries || []).map((x) => ({ id: x, label: x }))
    : type === "manager" ? (options?.managers || []).map((x) => ({ id: x.id, label: `${x.name} · ${x.city || "No city"} · ${x.country || "No country"}` }))
    : (options?.events || []).map((x) => ({ id: x.id, label: `${x.subject} · ${x.start.slice(0, 10)} · ${x.location}` }));
  const choice = values.find((x) => x.id === anchorId);
  const manager = type === "manager" ? options.managers.find((x) => x.id === anchorId) : null;
  const event = type === "event" ? options.events.find((x) => x.id === anchorId) : null;
  const eventCity = event ? [...new Set(options.candidates.map((c) => c.city).filter(Boolean))]
    .find((city) => event.location.toLowerCase().includes(city.toLowerCase())) : "";
  const anchor = { type, id: anchorId, label: choice?.label || "", city: manager?.city || eventCity || "", country: manager?.country || "" };
  React.useEffect(() => { setAnchorId(""); setSelected([]); }, [type]);
  const create = async () => {
    setBusy(true); setError(null);
    try {
      const trip = await post("/api/travel/trips", {
        name, anchor, start_date: start, end_date: end, candidate_ids: selected,
        settings: { nightly_budget_gbp: Number(budget), work_start: "09:00", work_end: "17:30",
          lunch_start: "12:30", lunch_end: "13:30", default_duration_minutes: 60,
          travel_mode: "DRIVE", hotel_price_weight: .4, hotel_travel_weight: .35,
          hotel_quality_weight: .25 },
      });
      onCreated(trip);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const blockedReason = !anchorId ? "Choose a destination above to see suggested meetings."
    : !selected.length ? "Select at least one suggested meeting to create the plan."
    : end < start ? "The departure date must be on or after the arrival date." : "";
  return <div className="travel-stack">
    <Card accent="teal">
      <SectionHead label="TRIP ANCHOR" right="01" />
      <div className="travel-form-grid">
        <Field label="START FROM"><select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="country">Country</option><option value="manager">Manager</option><option value="event">Outlook event</option>
        </select></Field>
        <Field label={type.toUpperCase()}>{type === "manager" ?
          <SearchSelect value={choice?.label || ""} options={values.map((x) => x.label)} allowCreate={false}
            placeholder="Search managers by name or location…" onChange={(label) => {
              const picked = values.find((x) => x.label === label);
              if (picked) { setAnchorId(picked.id); setSelected([]); }
            }} /> : <select value={anchorId} onChange={(e) => {
          setAnchorId(e.target.value); setSelected([]);
          if (type === "event") {
            const picked = options.events.find((x) => x.id === e.target.value);
            if (picked?.start) {
              const d = new Date(picked.start); const weekday = (d.getDay() + 6) % 7;
              const monday = new Date(d); monday.setDate(d.getDate() - weekday);
              const friday = new Date(monday); friday.setDate(monday.getDate() + 4);
              setStart(monday.toISOString().slice(0, 10)); setEnd(friday.toISOString().slice(0, 10)); setName(picked.subject || name);
            }
          }
        }}>
          <option value="">Choose…</option>{values.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select>}</Field>
        <Field label="TRIP NAME"><input type="text" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="NIGHTLY CAP · GBP"><input type="number" min="1" value={budget} onChange={(e) => setBudget(e.target.value)} /></Field>
        <Field label="ARRIVE"><input type="date" min={today()} value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="DEPART"><input type="date" min={start} value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
      </div>
    </Card>
    {anchorId && <CandidatePicker options={options} anchor={anchor} selected={selected} setSelected={setSelected} />}
    <div className="travel-create-row"><Button busy={busy} disabled={Boolean(blockedReason)} onClick={create}>Create travel plan</Button>
      {blockedReason && <span>{blockedReason}</span>}</div>
  </div>;
}

function GoogleMap({ points, apiKey }) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    let live = true;
    loadGoogleMaps(apiKey).then((google) => {
      if (!live || !ref.current) return;
      const centre = points.length ? { lat: points[0].lat, lng: points[0].lng } : { lat: 51.5074, lng: -.1278 };
      const map = new google.maps.Map(ref.current, { center: centre, zoom: points.length ? 11 : 3,
        mapTypeControl: false, streetViewControl: false, fullscreenControl: false });
      const bounds = new google.maps.LatLngBounds();
      points.forEach((p) => {
        new google.maps.Marker({ map, position: { lat: p.lat, lng: p.lng }, title: p.label,
          label: p.kind === "hotel" ? "H" : undefined });
        bounds.extend({ lat: p.lat, lng: p.lng });
      });
      if (points.length > 1) map.fitBounds(bounds, 48);
    }).catch(() => {});
    return () => { live = false; };
  }, [apiKey, JSON.stringify(points)]);
  return <div ref={ref} className="travel-map" role="img" aria-label="Google map of selected meetings and hotels" />;
}

function MapView({ trip, visible, browserKey }) {
  const points = travelMapPoints(trip, visible);
  const lats = points.map((p) => p.lat), lngs = points.map((p) => p.lng);
  const minLat = Math.min(...lats, 0), maxLat = Math.max(...lats, 1), minLng = Math.min(...lngs, 0), maxLng = Math.max(...lngs, 1);
  if (browserKey) return <GoogleMap points={points} apiKey={browserKey} />;
  return <div className="travel-map" role="img" aria-label="Map of selected meetings and hotels">
    <div className="travel-map-grid" />
    {!points.length && <div className="travel-map-empty">Resolve and confirm offices to place them on the map.</div>}
    {points.map((p, i) => <div key={p.id} className={`travel-marker ${p.kind}`}
      style={{ left: `${12 + 76 * ((p.lng - minLng) / (maxLng - minLng || 1))}%`,
               top: `${12 + 70 * (1 - (p.lat - minLat) / (maxLat - minLat || 1))}%` }}>
      <span>{p.kind === "hotel" ? "H" : i + 1}</span><label>{p.label}</label>
    </div>)}
    <span className="travel-demo-map">LOCATION OVERVIEW</span>
  </div>;
}

/* Recovery path for an office Places couldn't find: the bulk resolve builds
   its query from the stored record, and when that returns nothing the row
   used to show a dead UNRESOLVED chip with no control at all. Here the user
   words the search themselves. */
function OfficeSearch({ trip, candidate, act }) {
  const [q, setQ] = React.useState(candidate.office.query
    || [candidate.company, candidate.city].filter(Boolean).join(", "));
  return <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
    <input type="search" value={q} onChange={(e) => setQ(e.target.value)}
      aria-label={`Office search for ${candidate.company}`}
      style={{ fontSize: 12, padding: "5px 8px", width: 170 }} />
    <Button variant="ghost" style={{ padding: "5px 9px" }} disabled={!q.trim()}
      onClick={() => act(() => post(`/api/travel/trips/${trip.id}/locations/search`,
        { candidate_id: candidate.id, query: q }))}>
      Find
    </Button>
  </span>;
}

function MapHotels({ trip, update, integrations, busy, setBusy, setError }) {
  const [visible, setVisible] = React.useState(() => new Set(trip.candidates.map((c) => c.id)));
  const act = async (fn) => { setBusy(true); setError(null); try { update(await fn()); } catch (e) { setError(e); } finally { setBusy(false); } };
  const resolve = () => act(() => post(`/api/travel/trips/${trip.id}/locations/resolve`));
  const confirm = (candidate) => act(() => post(`/api/travel/trips/${trip.id}/locations/confirm`, { candidate_id: candidate.id, choice_index: 0 }));
  const hotelSearch = (city) => act(async () => { await post(`/api/travel/trips/${trip.id}/hotels/search`, { city_id: city.id }); return getRetry(`/api/travel/trips/${trip.id}`); });
  const selectHotel = (id) => act(() => post(`/api/travel/trips/${trip.id}/hotels/select`, { hotel_id: id }));
  const editSetting = (key, value) => update({ ...trip, settings: { ...trip.settings, [key]: value } }, false);
  const saveHotelSettings = () => act(() => patch(`/api/travel/trips/${trip.id}`, { settings: trip.settings }));
  const toggle = (id) => setVisible((old) => { const next = new Set(old); next.has(id) ? next.delete(id) : next.add(id); return next; });
  return <div className="travel-stack">
    <Card><SectionHead label="HOTEL RANKING" right="PRICE · TRAVEL · QUALITY" />
      <div className="travel-form-grid compact">
        <Field label="NIGHTLY CAP · GBP"><input type="number" min="1" value={trip.settings.nightly_budget_gbp} onChange={(e) => editSetting("nightly_budget_gbp", Number(e.target.value))} /></Field>
        <Field label="PRICE WEIGHT"><input type="number" min="0" max="1" step="0.05" value={trip.settings.hotel_price_weight} onChange={(e) => editSetting("hotel_price_weight", Number(e.target.value))} /></Field>
        <Field label="TRAVEL WEIGHT"><input type="number" min="0" max="1" step="0.05" value={trip.settings.hotel_travel_weight} onChange={(e) => editSetting("hotel_travel_weight", Number(e.target.value))} /></Field>
        <Field label="QUALITY WEIGHT"><input type="number" min="0" max="1" step="0.05" value={trip.settings.hotel_quality_weight} onChange={(e) => editSetting("hotel_quality_weight", Number(e.target.value))} /></Field>
      </div><Button variant="ghost" busy={busy} onClick={saveHotelSettings} style={{ marginTop: 14 }}>Save ranking weights</Button>
    </Card>
    <div className="travel-map-layout">
      <Card><SectionHead label="MEETING LOCATIONS" right={`${trip.candidates.filter((c) => c.office.confirmed).length}/${trip.candidates.length}`} />
        <div className="travel-location-list">
          {trip.candidates.map((c) => <div key={c.id} className="travel-location" data-on={visible.has(c.id) ? "1" : "0"}>
            <button type="button" onClick={() => toggle(c.id)}><span className="travel-check">{visible.has(c.id) ? "✓" : ""}</span>
              <span><b>{c.company}</b><small>{c.name} · {c.city}</small></span></button>
            {c.office.latitude == null ? <OfficeSearch trip={trip} candidate={c} act={act} />
              : c.office.confirmed ? <Chip tone="teal">CONFIRMED</Chip>
              : <Button variant="ghost" onClick={() => confirm(c)} style={{ padding: "5px 9px" }}>Confirm</Button>}
          </div>)}
        </div>
        <Button variant="ghost" busy={busy} onClick={resolve} style={{ marginTop: 14 }}>Resolve offices</Button>
      </Card>
      <MapView trip={trip} visible={visible} browserKey={integrations.browser_maps_key} />
    </div>
    {trip.cities.map((city) => {
      const hotels = trip.hotels.filter((h) => h.city_id === city.id);
      return <Card key={city.id}>
        <div className="travel-city-head"><div><span className="eyebrow brass">{city.start_date} — {city.end_date}</span>
          <h2>{city.name}</h2></div><Button variant="ghost" busy={busy} onClick={() => hotelSearch(city)}>Search hotels</Button></div>
        {!hotels.length && <div className="travel-empty">No hotel search yet, or no offer is within the £{trip.settings.nightly_budget_gbp} nightly cap.</div>}
        <div className="travel-hotels">{hotels.map((h, i) => <button type="button" key={h.id} data-on={h.selected ? "1" : "0"} onClick={() => selectHotel(h.id)}>
          <span className="mono travel-rank">{String(i + 1).padStart(2, "0")}</span><span><b>{h.name}</b><small>{h.rating ? `${h.rating.toFixed(1)} rating · ` : ""}{h.aggregate_travel_minutes ?? 0} min avg travel · score {h.score}</small></span>
          <span className="travel-price"><b>£{h.nightly_gbp.toFixed(0)}</b><small>/ night</small></span></button>)}</div>
      </Card>;
    })}
  </div>;
}

function Itinerary({ trip, update, busy, setBusy, setError }) {
  const act = async (fn) => { setBusy(true); setError(null); try { update(await fn()); } catch (e) { setError(e); } finally { setBusy(false); } };
  const confirmTransfers = () => act(() => patch(`/api/travel/trips/${trip.id}`, {
    transfers: trip.transfers.map((t) => ({ ...t, confirmed: true })),
  }));
  const editTransfer = (id, key, value) => update({ ...trip,
    transfers: trip.transfers.map((t) => t.id === id ? { ...t, [key]: value, confirmed: false } : t) }, false);
  const changeCandidate = (id, values) => act(() => patch(`/api/travel/trips/${trip.id}`, {
    candidates: trip.candidates.map((c) => c.id === id ? { ...c, ...values } : c),
  }));
  const editSetting = (key, value) => update({ ...trip, settings: { ...trip.settings, [key]: value } }, false);
  const saveSettings = () => act(() => patch(`/api/travel/trips/${trip.id}`, { settings: trip.settings }));
  const optimize = () => act(() => post(`/api/travel/trips/${trip.id}/optimize`));
  return <div className="travel-stack">
    <Card><SectionHead label="WORKING PATTERN" right={trip.settings.travel_mode} />
      <div className="travel-form-grid compact">
        <Field label="WORK START"><input type="time" value={trip.settings.work_start} onChange={(e) => editSetting("work_start", e.target.value)} /></Field>
        <Field label="WORK END"><input type="time" value={trip.settings.work_end} onChange={(e) => editSetting("work_end", e.target.value)} /></Field>
        <Field label="LUNCH START"><input type="time" value={trip.settings.lunch_start} onChange={(e) => editSetting("lunch_start", e.target.value)} /></Field>
        <Field label="LUNCH END"><input type="time" value={trip.settings.lunch_end} onChange={(e) => editSetting("lunch_end", e.target.value)} /></Field>
        <Field label="DEFAULT DURATION"><select value={trip.settings.default_duration_minutes} onChange={(e) => editSetting("default_duration_minutes", Number(e.target.value))}><option value="30">30 min</option><option value="45">45 min</option><option value="60">60 min</option><option value="90">90 min</option></select></Field>
        <Field label="TRAVEL MODE"><select value={trip.settings.travel_mode} onChange={(e) => editSetting("travel_mode", e.target.value)}><option value="DRIVE">Driving</option><option value="TRANSIT">Public transit</option><option value="WALK">Walking</option></select></Field>
      </div><Button variant="ghost" busy={busy} onClick={saveSettings} style={{ marginTop: 14 }}>Save working pattern</Button>
    </Card>
    {!!trip.transfers.length && <Card accent={trip.transfers.every((t) => t.confirmed) ? "teal" : undefined}>
      <SectionHead label="INTER-CITY TRANSFERS" right={trip.transfers.every((t) => t.confirmed) ? "LOCKED" : "REQUIRED"} />
      {trip.transfers.map((t) => <div className="travel-transfer edit" key={t.id}><span><b>{trip.cities.find((c) => c.id === t.from_city_id)?.name}</b> → <b>{trip.cities.find((c) => c.id === t.to_city_id)?.name}</b></span><input type="datetime-local" value={t.start.slice(0, 16)} onChange={(e) => editTransfer(t.id, "start", `${e.target.value}:00`)} /><input type="datetime-local" value={t.end.slice(0, 16)} onChange={(e) => editTransfer(t.id, "end", `${e.target.value}:00`)} /><input type="text" value={t.details} onChange={(e) => editTransfer(t.id, "details", e.target.value)} aria-label="Transfer details" /></div>)}
      {!trip.transfers.every((t) => t.confirmed) && <><Banner tone="warning">Replace these estimates with actual train or flight times if needed. Confirming makes them hard scheduling blocks.</Banner><Button onClick={confirmTransfers}>Confirm transfer blocks</Button></>}
    </Card>}
    <Card><div className="travel-city-head"><div><span className="eyebrow brass">CONSTRAINT SCHEDULE</span><h2>Meeting options</h2></div><Button busy={busy} disabled={trip.transfers.some((t) => !t.confirmed)} onClick={optimize}>Optimize itinerary</Button></div>
      <div className="travel-itinerary">{trip.candidates.map((c) => <div key={c.id} className="travel-meeting">
        <div><b>{c.name}</b><small>{c.company} · {c.city}</small></div>
        <div><div className="travel-tier"><button type="button" data-on={c.tier === 1 ? "1" : "0"} onClick={() => changeCandidate(c.id, { tier: 1 })}>TIER 1</button><button type="button" data-on={c.tier === 2 ? "1" : "0"} onClick={() => changeCandidate(c.id, { tier: 2 })}>TIER 2</button></div><div className="travel-meeting-controls"><select value={c.duration_minutes} onChange={(e) => changeCandidate(c.id, { duration_minutes: Number(e.target.value) })}><option value="30">30m</option><option value="45">45m</option><option value="60">60m</option><option value="90">90m</option></select><select value={c.venue} onChange={(e) => changeCandidate(c.id, { venue: e.target.value })}><option value="office">Office</option><option value="hotel">Hotel</option><option value="neutral">Neutral</option><option value="online">Online</option></select></div></div>
        <div className="travel-slots">{c.slots.map((s) => <span key={s.id}>{new Date(s.start).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>)}{!c.slots.length && <small>{c.explanation || "Not optimized yet"}</small>}</div>
      </div>)}</div>
    </Card>
  </div>;
}

function Outreach({ trip, update, integrations, busy, setBusy, setError }) {
  const [tier, setTier] = React.useState(1);
  const act = async (fn) => { setBusy(true); setError(null); try { update(await fn()); } catch (e) { setError(e); } finally { setBusy(false); } };
  const draft = () => act(async () => { await post(`/api/travel/trips/${trip.id}/outreach/draft`, { tier }); return getRetry(`/api/travel/trips/${trip.id}`); });
  const setBody = (id, body) => update({ ...trip, outreach: trip.outreach.map((m) => m.id === id ? { ...m, body } : m) }, false);
  const send = () => {
    const count = trip.outreach.filter((m) => m.tier === tier && m.state !== "sent").length;
    if (!count || !window.confirm(`Send ${count} Tier ${tier} message(s)? Clear acceptances may automatically create calendar invitations.`)) return;
    act(async () => { await patch(`/api/travel/trips/${trip.id}`, { outreach: trip.outreach }); await post(`/api/travel/trips/${trip.id}/outreach/send`, { tier, demo: !integrations.graph_write }); return getRetry(`/api/travel/trips/${trip.id}`); });
  };
  const sync = () => act(async () => { await post(`/api/travel/trips/${trip.id}/replies/sync`); return getRetry(`/api/travel/trips/${trip.id}`); });
  const setReplyDraft = (id, draft_response) => update({ ...trip, replies: trip.replies.map((r) => r.id === id ? { ...r, draft_response } : r) }, false);
  const review = (reply, state) => act(async () => { await post(`/api/travel/trips/${trip.id}/replies/review`, { reply_id: reply.id, state, draft_response: reply.draft_response }); return getRetry(`/api/travel/trips/${trip.id}`); });
  const messages = trip.outreach.filter((m) => m.tier === tier);
  return <div className="travel-stack">
    <Card accent="teal"><div className="travel-city-head"><div><span className="eyebrow brass">GUARDRAILED OUTREACH</span><h2>Coordinate the trip</h2></div><div className="travel-tier big"><button type="button" data-on={tier === 1 ? "1" : "0"} onClick={() => setTier(1)}>TIER 1</button><button type="button" data-on={tier === 2 ? "1" : "0"} onClick={() => setTier(2)}>TIER 2</button></div></div>
      <p className="muted">Each tier is drafted and launched separately. Tier 2 never sends automatically. Offered slots are exclusive across active recipients.</p>
      <div className="row"><Button variant="ghost" busy={busy} onClick={draft}>Draft Tier {tier}</Button><Button busy={busy} disabled={!messages.length} onClick={send}>{integrations.graph_write ? "Approve & send wave" : "Simulate approved wave"}</Button><Button variant="ghost" busy={busy} onClick={sync}>Sync replies</Button></div>
    </Card>
    {messages.map((m) => <Card key={m.id}><div className="travel-message-head"><span><b>{trip.candidates.find((c) => c.id === m.candidate_id)?.name}</b><small>{m.subject}</small></span><Chip tone={m.state === "sent" ? "teal" : m.state === "failed" ? "critical" : "neutral"}>{m.state.toUpperCase()}</Chip></div><textarea rows="10" value={m.body} disabled={m.state === "sent"} onChange={(e) => setBody(m.id, e.target.value)} />{m.error && <Banner tone="error">{m.error}</Banner>}</Card>)}
    <Card><SectionHead label="REPLY LEDGER" right={String(trip.replies.length).padStart(2, "0")} />
      {!trip.replies.length && <div className="travel-empty">No matched replies yet.</div>}
      {trip.replies.map((r) => <div className="travel-reply" key={r.id}><span><b>{trip.candidates.find((c) => c.id === r.candidate_id)?.name}</b><small>{r.evidence}</small>{r.draft_response && <textarea rows="3" value={r.draft_response} onChange={(e) => setReplyDraft(r.id, e.target.value)} />}{r.state === "pending" && <span className="row"><Button variant="ghost" onClick={() => review(r, "handled")}>Mark handled</Button><Button variant="ghost" onClick={() => review(r, "ignored")}>Ignore</Button></span>}</span><Chip tone={r.kind === "accepted" ? "teal" : r.kind === "ambiguous" ? "brass" : "neutral"}>{r.kind.toUpperCase()} · {r.state.toUpperCase()}</Chip></div>)}
    </Card>
  </div>;
}

export default function Travel() {
  const [tab, setTab] = React.useState("trip");
  const switchTab = useTabScrollMemory(tab, setTab);
  const [options, setOptions] = React.useState(null);
  const [trips, setTrips] = React.useState([]);
  const [trip, setTrip] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  React.useEffect(() => {
    Promise.all([getRetry("/api/travel/options"), getRetry("/api/travel/trips")])
      .then(([o, t]) => {
        setOptions(o); setTrips(t.trips || []);
        const remembered = localStorage.getItem("wb-travel-trip");
        const current = (t.trips || []).find((x) => x.id === remembered);
        if (current) setTrip(current);
      }).catch(setError);
  }, []);
  React.useEffect(() => {
    uiStore.setSubnav({ title: "TRAVEL PLANNER", items: TABS, active: tab, onSelect: switchTab });
    return () => uiStore.setSubnav(null);
  }, [tab]);
  const update = (value, persist = true) => {
    setTrip(value);
    if (persist && value?.id) { localStorage.setItem("wb-travel-trip", value.id); setTrips((old) => [value, ...old.filter((t) => t.id !== value.id)]); }
  };
  const openTrip = async (id) => { setBusy(true); try { update(await getRetry(`/api/travel/trips/${id}`)); } catch (e) { setError(e); } finally { setBusy(false); } };
  return <div className="fade-in travel-page">
    <div className="pagehead"><div className="lead"><span className="eyebrow brass">TRAVEL · MEETINGS · OUTREACH</span><h1 className="xl">Travel planner</h1><p className="desc">Build a meeting-dense trip without turning your calendar into a negotiation spreadsheet.</p></div>
      <div className="actions">{trips.length > 0 && <select value={trip?.id || ""} onChange={(e) => e.target.value ? openTrip(e.target.value) : setTrip(null)}><option value="">New plan</option>{trips.map((t) => <option key={t.id} value={t.id}>{t.name} · {t.start_date}</option>)}</select>}</div></div>
    <IntegrationStrip integrations={options?.integrations} />
    {error && <ErrorNote error={error} />}
    {!options ? <Spinner /> : tab === "trip" && !trip ? <TripSetup options={options} onCreated={(t) => { update(t); setTab("map"); }} busy={busy} setBusy={setBusy} setError={setError} />
      : !trip ? <Banner tone="warning">Create or open a travel plan first.</Banner>
      : tab === "trip" ? <Card><SectionHead label="ACTIVE PLAN" right={trip.status.toUpperCase()} /><h2>{trip.name}</h2><p>{trip.anchor.label} · {trip.start_date} — {trip.end_date} · {trip.candidates.length} selected meeting(s) · {trip.cities.length} city stop(s)</p><Button variant="ghost" onClick={() => { localStorage.removeItem("wb-travel-trip"); setTrip(null); setTab("trip"); }}>Start a new plan</Button></Card>
      : tab === "map" ? <MapHotels trip={trip} update={update} integrations={options.integrations} busy={busy} setBusy={setBusy} setError={setError} />
      : tab === "itinerary" ? <Itinerary trip={trip} update={update} busy={busy} setBusy={setBusy} setError={setError} />
      : <Outreach trip={trip} update={update} integrations={options.integrations} busy={busy} setBusy={setBusy} setError={setError} />}
  </div>;
}
