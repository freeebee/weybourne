import React from "react";
import { useNavigate } from "react-router-dom";
import { get } from "../api.js";
import * as liveStore from "../liveStore.js";
import { Banner, Button, Card, Chip, ErrorNote, Mascot, SectionHead } from "../ui.jsx";
import * as uiStore from "../uiStore.js";

const WORKSPACES = [
  ["/triage", "Inbox triage", "MAIL →",
   "Scan the inbox for investment-relevant mail, check it against Notion, screen it against our preferences and draft a reply."],
  ["/prep", "Meeting prep", "PREPARATION →",
   "Pick an upcoming meeting, type a manager's name or attach a deck — the briefing and preference review run in the background."],
  ["/live", "Live meeting", "TRANSCRIPT →",
   "Stream the room or the call; every half-minute the new speech becomes the next questions worth asking."],
  ["/track-records", "Track records", "PERFORMANCE →",
   "Turn a manager's Excel or PDF track record into one common format, then compare and chart it."],
  ["/fund-data", "Fund data", "PORTFOLIO →",
   "The time-series dashboard over everything ingested from quarterly reports and statements."],
  ["/whats-new", "What's new", "BRIEFING →",
   "The last week in one sitting — team meetings, execution moves, and the shared inbox condensed."],
];

function todayEyebrow() {
  const d = new Date();
  const day = d.toLocaleDateString("en-GB", { weekday: "long" }).toUpperCase();
  const date = d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }).toUpperCase();
  return `${day} · ${date}`;
}

export default function Home() {
  const nav = useNavigate();
  React.useSyncExternalStore(uiStore.subscribe, uiStore.getVersion);
  React.useSyncExternalStore(liveStore.subscribe, liveStore.getVersion);
  const [events, setEvents] = React.useState([]);
  const [jobs, setJobs] = React.useState([]);
  const [refreshing, setRefreshing] = React.useState(false);
  const [refreshNote, setRefreshNote] = React.useState(null);
  const pollRef = React.useRef(null);

  React.useEffect(() => {
    get("/api/calendar?days=7").then((d) => setEvents(d.events)).catch(() => {});
    get("/api/jobs").then(({ jobs: js }) =>
      setJobs(js.filter((j) => j.status === "done").slice(0, 5))).catch(() => {});
    return () => clearInterval(pollRef.current);
  }, []);

  async function refreshOutlook() {
    setRefreshing(true); setRefreshNote(null);
    try {
      const res = await fetch("/api/jobs/outlook-refresh", { method: "POST" });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
      const job = await res.json();
      pollRef.current = setInterval(async () => {
        const j = await get(`/api/jobs/${job.id}`).catch(() => null);
        if (!j || j.status === "running") return;
        clearInterval(pollRef.current);
        setRefreshing(false);
        if (j.status === "error") setRefreshNote({ tone: "error", text: j.error });
        else {
          const r = j.result;
          setRefreshNote({ tone: "success",
            text: `Refreshed via your Claude Microsoft 365 connector: ${r.inbox} inbox, ${r.calendar} calendar, ${r.shared} shared item(s).` });
          get("/api/calendar?days=7").then((d) => setEvents(d.events)).catch(() => {});
        }
      }, 2000);
    } catch (e) { setRefreshing(false); setRefreshNote({ tone: "error", text: e.message }); }
  }

  const next = events[0];
  const rest = events.slice(1, 6);

  return (
    <div className="fade-in">
      <div className="pagehead">
        <div className="lead">
          <span className="eyebrow brass">{todayEyebrow()}</span>
          <h1 className="xl">Good {new Date().getHours() < 12 ? "morning" : new Date().getHours() < 18 ? "afternoon" : "evening"}.</h1>
          <p className="desc">
            {events.length ? `${events.length} meeting(s) in the next seven days` : "A quiet calendar this week"}
            {uiStore.ui.inboxCount != null ? ` · ${uiStore.ui.inboxCount} message(s) in the inbox window` : ""}
            {liveStore.S.running ? " · a live session is recording" : ""}.
          </p>
        </div>
        <div className="actions">
          <Mascot state="waving" width={88} />
          <Button onClick={() => nav("/triage")}>Triage the inbox</Button>
          <Button variant="ghost" onClick={() => nav("/prep")}>Prepare a meeting</Button>
        </div>
      </div>

      <div className="row" style={{ marginBottom: 8 }}>
        <Button variant="ghost" busy={refreshing} onClick={refreshOutlook}>Refresh Outlook data</Button>
        {refreshing && <span className="muted small">fetching via your Claude connector — typically a few minutes…</span>}
      </div>
      {refreshNote && <Banner tone={refreshNote.tone}>{refreshNote.text}</Banner>}
      <ErrorNote error={null} />

      <div className="panes" style={{ gap: "40px 56px" }}>
        {/* Workspaces ledger */}
        <section style={{ flex: "1 1 520px", minWidth: "min(100%,440px)" }}>
          <SectionHead label="WORKSPACES" right={String(WORKSPACES.length).padStart(2, "0")} />
          {WORKSPACES.map(([to, title, meta, blurb], i) => (
            <button key={to} onClick={() => nav(to)} className="rrow click" style={{
              display: "grid", gridTemplateColumns: "38px minmax(0,1fr) auto",
              gap: "10px 18px", padding: "18px 14px 18px 0", width: "100%",
              textAlign: "left", background: "none", border: "none",
              borderTop: "1px solid var(--paper-200)", cursor: "pointer",
            }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--stone-400)", paddingTop: 6 }}>
                {String(i + 1).padStart(2, "0")}
              </span>
              <span>
                <span style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <span style={{ font: "400 20px/1.25 var(--serif)", color: "var(--ink-800)" }}>{title}</span>
                  {to === "/triage" && uiStore.ui.inboxCount > 0 && (
                    <Chip tone="teal">{uiStore.ui.inboxCount} NEW</Chip>
                  )}
                  {to === "/live" && liveStore.S.running && (
                    <Chip tone="bare-rec" dot>RECORDING</Chip>
                  )}
                </span>
                <span style={{ display: "block", fontSize: 14, lineHeight: 1.5,
                               color: "var(--stone-600)", maxWidth: "56ch", marginTop: 4 }}>
                  {blurb}
                </span>
              </span>
              <span className="mono" style={{ fontSize: "10.5px", letterSpacing: ".12em",
                color: "var(--stone-400)", whiteSpace: "nowrap", paddingTop: 8 }}>{meta}</span>
            </button>
          ))}
        </section>

        {/* Rail */}
        <aside style={{ flex: "1 1 300px", maxWidth: 340, minWidth: 280,
                        display: "flex", flexDirection: "column", gap: 30 }}>
          <section>
            <SectionHead label="TODAY" />
            {next ? (
              <>
                <Card accent="teal" style={{ padding: "17px 17px 15px" }}>
                  <div className="spread">
                    <span className="mono" style={{ fontSize: 12 }}>{(next.start || "").slice(11, 16)}</span>
                    <span className="mono" style={{ fontSize: 10, color: "var(--stone-400)" }}>
                      {(next.start || "").slice(0, 10)}
                    </span>
                  </div>
                  <div style={{ font: "400 19px/1.3 var(--serif)", color: "var(--ink-800)", margin: "6px 0 4px" }}>
                    {next.subject}
                  </div>
                  <div style={{ fontSize: "13.5px", color: "var(--stone-600)" }}>
                    {next.counterparty_name || next.location || (next.is_online ? "Online" : "")}
                  </div>
                  <a href="#/prep" style={{ fontSize: "13.5px", fontWeight: 500, display: "inline-block", marginTop: 8 }}>
                    Open the briefing →
                  </a>
                </Card>
                {rest.map((e, i) => (
                  <div key={i} className="rrow" style={{ display: "flex", gap: 14 }}>
                    <span className="mono" style={{ fontSize: 12, width: 42, flex: "none", color: "var(--stone-500)" }}>
                      {(e.start || "").slice(11, 16)}
                    </span>
                    <span style={{ fontSize: "13.5px", color: "var(--stone-600)" }}>{e.subject}</span>
                  </div>
                ))}
              </>
            ) : <p className="muted small">Nothing scheduled.</p>}
          </section>

          <section>
            <SectionHead label="RECENT" />
            {jobs.length ? jobs.map((j) => (
              <div key={j.id} className="rrow">
                <div style={{ fontSize: "13.5px", color: "var(--ink-700)" }}>{j.label}</div>
                <div className="mono" style={{ fontSize: "10.5px", letterSpacing: ".08em", color: "var(--stone-400)" }}>
                  {j.created} · {j.elapsed}s
                </div>
              </div>
            )) : <p className="muted small">No completed runs yet.</p>}
          </section>
        </aside>
      </div>
    </div>
  );
}
