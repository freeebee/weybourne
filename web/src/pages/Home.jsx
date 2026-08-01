import React from "react";
import { Link } from "react-router-dom";
import { get } from "../api.js";
import { Banner, Button, Card, Mascot, Pill } from "../ui.jsx";

const FEATURES = [
  ["/triage", "MAIL", "Inbox triage", "Scan the inbox for investment-relevant mail, check it against Notion, screen it against our preferences and draft a reply."],
  ["/prep", "PREPARATION", "Meeting prep", "Pick an upcoming meeting, type a manager's name or attach a deck — get a quick brief or the full DD briefing."],
  ["/track-records", "PERFORMANCE", "Track record analysis", "Turn a manager's Excel or PDF track record into one common format, then compare and chart it."],
  ["/live", "IN PROGRESS", "Live meeting", "Stream the room from your microphone; every half-minute the new speech becomes the next questions worth asking."],
  ["/fund-data", "PORTFOLIO", "Fund data", "The time-series dashboard over everything ingested from quarterly reports and statements."],
  ["/whats-new", "BRIEFING", "What's new", "The last week in one sitting — team meetings and execution moves, the shared inbox condensed, and portfolio news."],
];

export default function Home() {
  const [status, setStatus] = React.useState(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [refreshNote, setRefreshNote] = React.useState(null);
  const pollRef = React.useRef(null);

  React.useEffect(() => {
    get("/api/status").then(setStatus).catch(() => setStatus(null));
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
          const problems = ["inbox", "calendar", "shared"]
            .filter((k) => r[`${k}_error`])
            .map((k) => `${k}: ${r[`${k}_error`]}`).join(" · ");
          setRefreshNote({
            tone: problems ? "warning" : "success",
            text: `Refreshed from your Claude Microsoft 365 connector: ${r.inbox} inbox, `
              + `${r.calendar} calendar, ${r.shared} shared-mailbox item(s).`
              + (problems ? ` Issues — ${problems}` : ""),
          });
          get("/api/status").then(setStatus).catch(() => {});
        }
      }, 2000);
    } catch (e) {
      setRefreshing(false);
      setRefreshNote({ tone: "error", text: e.message });
    }
  }

  return (
    <div className="fade-in">
      <div className="hero" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: "1.5rem" }}>
        <div>
          <h1 style={{ letterSpacing: ".18em", fontSize: "2.1rem" }}>WEYBOURNE</h1>
          <span className="eyebrow">INVESTMENT CONNECTOR · FAMILY OFFICE</span>
          <p>Outlook and Notion, joined up — inbox triage, meeting prep, track records and live meetings.</p>
        </div>
        <Mascot state="waving" width={104} />
      </div>

      {status && (
        <div className="row" style={{ gap: "2.5rem", marginBottom: ".8rem" }}>
          {[["Outlook", status.outlook], ["Notion", status.notion],
            [status.ai.label || "Claude", status.ai]].map(([label, s]) => (
            <div key={label}>
              <b>{label}</b>
              <Pill tone={s.ok ? "live" : "demo"}>{s.ok ? "connected" : "demo"}</Pill>
              <div className="muted small">{s.detail}</div>
            </div>
          ))}
          <Button variant="secondary" busy={refreshing} onClick={refreshOutlook}>
            Refresh Outlook data
          </Button>
        </div>
      )}
      {refreshing && <Mascot state="filing" width={72}
        text="Fetching mail and calendar through your Claude Microsoft 365 connector — typically 1–3 minutes…" />}
      {refreshNote && <Banner tone={refreshNote.tone}>{refreshNote.text}</Banner>}
      <div style={{ marginBottom: ".8rem" }} />

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
        {FEATURES.map(([to, eyebrow, title, blurb]) => (
          <Link key={to} to={to} className="feature-card"
            style={{ textDecoration: "none", color: "inherit", display: "block" }}>
            <Card style={{ display: "flex", flexDirection: "column", gap: ".4rem",
                           height: "100%", cursor: "pointer",
                           transition: "box-shadow .15s ease, transform .15s ease" }}>
              <span className="eyebrow" style={{ margin: 0 }}>{eyebrow}</span>
              <h3 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 500 }}>{title}</h3>
              <p className="muted small" style={{ margin: 0, flex: 1 }}>{blurb}</p>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
