import React from "react";
import { get } from "../api.js";
import { Banner, Button, Card, ErrorNote, Mascot, PageHeader, Pill } from "../ui.jsx";

const MOVE_TONE = { new: "demo", completed: "live", "in progress": "neutral" };

/* Each part runs automatically as a background job on first visit; coming back
   re-attaches to the running job or shows the last result. */
function useAutoJob(kind, startUrl) {
  const [result, setResult] = React.useState(null);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState(null);
  const pollRef = React.useRef(null);
  const startedRef = React.useRef(false);

  const attach = React.useCallback((jobId) => {
    clearInterval(pollRef.current);
    setRunning(true);
    pollRef.current = setInterval(async () => {
      try {
        const j = await get(`/api/jobs/${jobId}`);
        if (j.status !== "running") {
          clearInterval(pollRef.current);
          setRunning(false);
          if (j.status === "error") setError(j.error);
          else setResult(j.result);
        }
      } catch (e) {
        clearInterval(pollRef.current);
        setRunning(false); setError(e.message);
      }
    }, 1500);
  }, []);

  const start = React.useCallback(async () => {
    setError(null); setResult(null);
    try {
      const res = await fetch(startUrl, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      attach((await res.json()).id);
    } catch (e) { setError(e.message); }
  }, [startUrl, attach]);

  React.useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    get(`/api/jobs?kind=${kind}`).then(({ jobs }) => {
      const latest = jobs[0];
      if (!latest) { start(); return; }
      if (latest.status === "running") attach(latest.id);
      else get(`/api/jobs/${latest.id}`).then((j) => {
        if (j.status === "error") setError(j.error); else setResult(j.result);
      });
    }).catch(() => start());
    return () => clearInterval(pollRef.current);
  }, [kind, start, attach]);

  return { result, running, error, refresh: start };
}

export default function WhatsNew() {
  const team = useAutoJob("whats-new-team", "/api/jobs/whats-new-team");
  const inbox = useAutoJob("whats-new-inbox", "/api/jobs/whats-new-inbox");

  return (
    <div className="fade-in">
      <PageHeader eyebrow="BRIEFING · WEEKLY" title="What's new">
        The last 7 days in one sitting — built automatically when you open this page.
      </PageHeader>

      <section>
        <div className="spread">
          <div>
            <span className="eyebrow">PART ONE · NOTION</span>
            <h3 style={{ fontWeight: 500 }}>What's going on in the team</h3>
          </div>
          {team.result && <Button variant="ghost" onClick={team.refresh}>Refresh</Button>}
        </div>
        {team.running && <Mascot state="reading" text="Reading the week's notes and the execution dashboard…" />}
        <ErrorNote error={team.error} />
        {team.result && <TeamView team={team.result} />}
      </section>

      <hr className="rule" />

      <section>
        <div className="spread">
          <div>
            <span className="eyebrow">PART TWO · SHARED INBOX</span>
            <h3 style={{ fontWeight: 500 }}>What people are saying</h3>
          </div>
          {inbox.result && <Button variant="ghost" onClick={inbox.refresh}>Refresh</Button>}
        </div>
        {inbox.running && <Mascot state="filing" text="Sorting the shared inbox into themes…" />}
        <ErrorNote error={inbox.error} />
        {inbox.result && <InboxView pulse={inbox.result} />}
      </section>

      <hr className="rule" />

      <section>
        <span className="eyebrow">PART THREE · PORTFOLIO</span>
        <h3 style={{ fontWeight: 500 }}>What's going on in the portfolio</h3>
        <Card>
          <Mascot state="sleeping" width={90}
            text="Not wired up yet. This will run a news search across every position and surface only what's material — it needs the position list (not in the system yet) and a search backend." />
        </Card>
      </section>
    </div>
  );
}

function TeamView({ team }) {
  return (
    <>
      <p style={{ fontStyle: "italic" }}>{team.headline}</p>

      {team.key_insights?.length > 0 && (
        <Card style={{ marginBottom: "1rem", borderTop: "2px solid var(--brass-500)" }}>
          <span className="eyebrow">KEY INSIGHTS · THE WEEK ON THE INVESTMENTS SIDE</span>
          <ul style={{ margin: ".2rem 0 0", paddingLeft: "1.1rem" }}>
            {team.key_insights.map((k, i) => (
              <li key={i} style={{ marginBottom: ".45rem", fontSize: ".95rem" }}>{k}</li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", alignItems: "start" }}>
        <div>
          <span className="eyebrow">INVESTMENT · MEETINGS TAKEN</span>
          {team.investment_updates.map((u, i) => (
            <Card key={i} style={{ marginBottom: ".7rem" }}>
              <div className="spread"><b>{u.title}</b><span className="mono muted small">{u.date}</span></div>
              <p className="small" style={{ margin: ".4rem 0 0" }}>{u.insight}</p>
              {u.follow_up && <p className="muted small" style={{ margin: ".3rem 0 0" }}>Follow-up: {u.follow_up}</p>}
            </Card>
          ))}
        </div>
        <div>
          <span className="eyebrow">OPERATIONAL · EXECUTION DASHBOARD</span>
          {team.operational_updates.map((o, i) => (
            <Card key={i} style={{ marginBottom: ".7rem" }}>
              <b className="small">{o.item}</b>
              <Pill tone={MOVE_TONE[o.movement] || "neutral"}>{o.movement}</Pill>
              {o.detail && <p className="muted small" style={{ margin: ".3rem 0 0" }}>{o.detail}</p>}
            </Card>
          ))}
        </div>
      </div>

      {team.interesting_points?.length > 0 && (
        <div style={{ marginTop: "1rem" }}>
          <span className="eyebrow">WORTH REPEATING</span>
          {team.interesting_points.map((p, i) => (
            <p key={i} style={{
              fontFamily: "var(--serif)", fontStyle: "italic", fontSize: "1rem",
              borderLeft: "2px solid var(--teal-500)", paddingLeft: ".8rem",
              margin: "0 0 .6rem",
            }}>{p}</p>
          ))}
        </div>
      )}

      <p className="muted small">
        From {team._sources?.notes ?? 0} note(s) and {team._sources?.execution ?? 0} execution item(s).
      </p>
    </>
  );
}

function InboxView({ pulse }) {
  return (
    <>
      <p style={{ fontStyle: "italic" }}>{pulse.headline}</p>
      {(pulse.insights || []).map((t, i) => (
        <Card key={i} style={{ marginBottom: ".7rem" }}>
          <b>{t.insight}</b>
          <p className="small" style={{ margin: ".4rem 0 0" }}>{t.detail}</p>
          <div className="mono muted" style={{ fontSize: ".7rem", marginTop: ".35rem" }}>
            → {t.source}
          </div>
          {t.action_needed && <Banner tone="warning">Action: {t.action_needed}</Banner>}
        </Card>
      ))}
      {!(pulse.insights || []).length && (
        <p className="muted small">No market-relevant content in the window — only
          reporting and operational traffic.</p>
      )}
      <p className="muted small">
        From {pulse._sources?.messages ?? 0} message(s)
        {pulse.excluded_count ? ` · ${pulse.excluded_count} reporting/ops item(s) ignored` : ""}.
      </p>
    </>
  );
}
