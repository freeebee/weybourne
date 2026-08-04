import React from "react";
import { useNavigate } from "react-router-dom";
import { get, getRetry } from "../api.js";
import * as liveStore from "../liveStore.js";
import { Banner, Button, Card, Chip, ErrorNote, Mascot, SectionHead, fmtDate, fmtTime } from "../ui.jsx";
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

/* Thin-stroke line icons for the workspace ledger — house style, no emoji. */
function WsIcon({ to }) {
  const paths = {
    "/triage": ["M3 5.5h18v13H3z", "M3 6.5l9 6.5 9-6.5"],
    "/prep": ["M6 3.5h9l4 4v13H6z", "M15 3.5v4h4", "M9.5 12h5", "M9.5 15.5h5"],
    "/live": ["M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3z",
              "M6.5 12a5.5 5.5 0 0 0 11 0", "M12 17.5V21", "M9 21h6"],
    "/track-records": ["M5 20v-9", "M11 20V5", "M17 20v-6", "M3 20h18"],
    "/fund-data": ["M3 20h18", "M4 16l5-6 4 3 7-8"],
    "/whats-new": ["M12 4a5 5 0 0 1 5 5v3l2 3.5H5L7 12V9a5 5 0 0 1 5-5z",
                   "M10 18.5a2 2 0 0 0 4 0"],
  }[to] || [];
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none"
         stroke="var(--teal-700)" strokeWidth="1.5" strokeLinecap="round"
         strokeLinejoin="round" style={{ marginTop: 5 }}>
      {paths.map((d, i) => <path key={i} d={d} />)}
    </svg>
  );
}

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

  React.useEffect(() => {
    getRetry("/api/calendar?days=7").then((d) => setEvents(d.events)).catch(() => {});
    get("/api/jobs").then(({ jobs: js }) =>
      setJobs(js.filter((j) => j.status === "done").slice(0, 5))).catch(() => {});
    // A refresh started on another visit (or before a reload) keeps its
    // countdown — re-attach to it.
    uiStore.restoreOutlookRefresh();
  }, []);

  const refresh = uiStore.ui.refresh;
  const refreshLeft = Math.max(0, (refresh.eta || 0) - (refresh.elapsed || 0));

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
          <button className="mono" title="Watch the opening animation again"
            onClick={() => window.dispatchEvent(new Event("wb-replay-splash"))}
            style={{ background: "none", border: "none", cursor: "pointer",
                     padding: "2px 0", fontSize: 10, letterSpacing: ".14em",
                     color: "var(--stone-400)" }}>
            REPLAY OPENING
          </button>
        </div>
      </div>

      {!refresh.running ? (
        <div className="row" style={{ marginBottom: 8 }}>
          <Button variant="ghost" onClick={uiStore.startOutlookRefresh}>Refresh Outlook data</Button>
        </div>
      ) : (
        <Card style={{ margin: "0 0 14px", padding: "14px 18px" }}>
          <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
            <Mascot state="crunching" width={54} />
            <div style={{ flex: 1 }}>
              <span className="microlabel">REFRESHING OUTLOOK · FULL EMAIL BODIES VIA YOUR CLAUDE CONNECTOR</span>
              <div className="mono" style={{ fontSize: 11.5, color: "var(--teal-700)", marginTop: 3 }}>
                {refresh.elapsed}S ELAPSED · {refreshLeft > 0 ? `~${refreshLeft}S LEFT` : "WRAPPING UP"}
              </div>
              <div style={{ height: 2, background: "var(--paper-200)", marginTop: 8, borderRadius: 1 }}>
                <div style={{ height: 2, background: "var(--teal-500)", transition: "width 2s linear",
                  width: `${Math.min(97, refresh.eta > 0 ? (refresh.elapsed / refresh.eta) * 100 : 25)}%` }} />
              </div>
              <span className="muted" style={{ fontSize: "12px", display: "block", marginTop: 6 }}>
                Runs in the background — leave this page or use other tools; it keeps going.
              </span>
            </div>
          </div>
        </Card>
      )}
      {refresh.note && <Banner tone={refresh.note.tone}>{refresh.note.text}</Banner>}
      <ErrorNote error={null} />

      <div className="panes" style={{ gap: "40px 56px" }}>
        {/* Workspaces ledger */}
        <section style={{ flex: "1 1 520px", minWidth: "min(100%,440px)" }}>
          <SectionHead label="WORKSPACES" right={String(WORKSPACES.length).padStart(2, "0")} />
          {WORKSPACES.map(([to, title, meta, blurb], i) => (
            <button key={to} onClick={() => nav(to)} className="rrow click" style={{
              display: "grid", gridTemplateColumns: "34px 32px minmax(0,1fr) auto",
              gap: "10px 14px", padding: "18px 14px 18px 0", width: "100%",
              textAlign: "left", background: "none", border: "none",
              borderTop: "1px solid var(--paper-200)", cursor: "pointer",
            }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--stone-400)", paddingTop: 6 }}>
                {String(i + 1).padStart(2, "0")}
              </span>
              <WsIcon to={to} />
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
                    <span className="mono" style={{ fontSize: 12 }}>{fmtTime(next.start)}</span>
                    <span className="mono" style={{ fontSize: 10, color: "var(--stone-400)" }}>
                      {fmtDate(next.start)}
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
                      {fmtTime(e.start)}
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
