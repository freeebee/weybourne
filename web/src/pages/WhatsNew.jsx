import React from "react";
import { get } from "../api.js";
import { Button, Chip, ErrorNote, Mascot, PageHeader, SectionHead } from "../ui.jsx";

const MOVE_TONE = { new: "caution", completed: "positive", "in progress": "teal" };

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

function weekEyebrow() {
  const d = new Date();
  return `BRIEFING · WEEK TO ${d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }).toUpperCase()}`;
}

export default function WhatsNew() {
  const team = useAutoJob("whats-new-team", "/api/jobs/whats-new-team");
  const inbox = useAutoJob("whats-new-inbox", "/api/jobs/whats-new-inbox");
  const t = team.result;
  const p = inbox.result;

  return (
    <div className="fade-in">
      <PageHeader eyebrow={weekEyebrow()} eyebrowTone="brass" title="What's new"
        actions={
          <Button variant="ghost" busy={team.running || inbox.running}
            onClick={() => { team.refresh(); inbox.refresh(); }}>
            Rebuild the briefing
          </Button>
        }>
        Built automatically when you open this page — the last seven days across the
        team's Notion activity and the shared inbox.
      </PageHeader>

      <ErrorNote error={team.error || inbox.error} />

      {/* In short */}
      <div style={{ display: "flex", gap: 26, alignItems: "center", margin: "6px 0 30px" }}>
        <Mascot state="presenting" width={96} />
        <p style={{ font: "400 20px/1.6 var(--serif)", color: "var(--ink-800)",
                    maxWidth: "60ch", margin: 0 }}>
          {(team.running || inbox.running) && !t && !p
            ? "Reading the week's notes, the execution dashboard and the shared inbox…"
            : [t?.headline, p?.headline].filter(Boolean).join(" ") || "Nothing to report yet."}
        </p>
      </div>

      <div style={{ display: "grid",
        gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))", gap: 36 }}>
        {/* Execution moves */}
        <section>
          <SectionHead label="EXECUTION MOVES" right="FROM NOTION" />
          {team.running && <Mascot state="reading" width={48} text="Reading the execution dashboard…" />}
          {t?.operational_updates?.map((o, i) => (
            <div key={i} className="rrow">
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <b style={{ fontSize: "14.5px" }}>{o.item}</b>
                <Chip tone={MOVE_TONE[o.movement] || "neutral"}>{o.movement.toUpperCase()}</Chip>
              </div>
              {o.detail && <p style={{ fontSize: "13.5px", lineHeight: 1.55, margin: "5px 0 0" }}>{o.detail}</p>}
            </div>
          ))}
          {t && !t.operational_updates?.length && (
            <p className="muted small">No dashboard movement in the window.</p>
          )}
        </section>

        {/* Shared inbox condensed */}
        <section>
          <SectionHead label="SHARED INBOX, CONDENSED"
            right={p ? `${p._sources?.messages ?? 0} MESSAGES → ${p.insights?.length ?? 0} INSIGHTS` : ""} />
          {inbox.running && <Mascot state="filing" width={48} text="Sorting the shared inbox…" />}
          {p?.insights?.map((x, i) => (
            <div key={i} className="rrow" style={{ display: "grid",
              gridTemplateColumns: "32px minmax(0,1fr)", gap: 12 }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--brass-500)" }}>
                {String(i + 1).padStart(2, "0")}
              </span>
              <div>
                <b style={{ fontSize: "14px" }}>{x.insight}</b>
                <p style={{ fontSize: "13px", lineHeight: 1.5, margin: "4px 0 0" }}>{x.detail}</p>
                <span className="mono" style={{ fontSize: 10, color: "var(--stone-400)" }}>→ {x.source}</span>
                {x.action_needed && (
                  <div style={{ fontSize: "12.5px", color: "var(--caution-600)", marginTop: 3 }}>
                    Action: {x.action_needed}
                  </div>
                )}
              </div>
            </div>
          ))}
          {p && !p.insights?.length && (
            <p className="muted small">
              No market-relevant content in the window — only reporting and operational traffic
              ({p.excluded_count ?? 0} item(s) ignored).
            </p>
          )}
          {p?.insights?.length > 0 && p.excluded_count > 0 && (
            <p className="muted" style={{ fontSize: "12px", marginTop: 8 }}>
              {p.excluded_count} reporting/ops item(s) ignored.
            </p>
          )}
        </section>
      </div>

      {/* Meetings + insights — kept from the previous design (not in the handoff,
          preserved so nothing the digest produces is lost). */}
      {t && (
        <>
          {t.key_insights?.length > 0 && (
            <section style={{ marginTop: 34 }}>
              <SectionHead label="KEY INSIGHTS · THE WEEK ON THE INVESTMENTS SIDE" />
              {t.key_insights.map((k, i) => (
                <div key={i} className="rrow" style={{ display: "grid",
                  gridTemplateColumns: "32px minmax(0,1fr)", gap: 12 }}>
                  <span className="mono" style={{ fontSize: 11, color: "var(--teal-600)" }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontSize: "14px", lineHeight: 1.55 }}>{k}</span>
                </div>
              ))}
            </section>
          )}
          {t.investment_updates?.length > 0 && (
            <section style={{ marginTop: 34 }}>
              <SectionHead label="MEETINGS TAKEN" right={String(t.investment_updates.length)} />
              <div style={{ display: "grid",
                gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))", gap: "0 36px" }}>
                {t.investment_updates.map((u, i) => (
                  <div key={i} className="rrow">
                    <div className="spread">
                      <b style={{ fontSize: "14.5px" }}>{u.title}</b>
                      <span className="mono" style={{ fontSize: 11, color: "var(--stone-400)" }}>{u.date}</span>
                    </div>
                    <p style={{ fontSize: "13.5px", lineHeight: 1.55, margin: "5px 0 0" }}>{u.insight}</p>
                    {u.follow_up && (
                      <p className="muted" style={{ fontSize: "12.5px", margin: "4px 0 0" }}>
                        Follow-up: {u.follow_up}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
          {t.interesting_points?.length > 0 && (
            <section style={{ marginTop: 34 }}>
              <SectionHead label="WORTH REPEATING" />
              {t.interesting_points.map((x, i) => (
                <p key={i} style={{ font: "italic 400 15.5px/1.6 var(--serif)",
                  borderLeft: "2px solid var(--teal-500)", paddingLeft: 14, margin: "0 0 10px" }}>
                  {x}
                </p>
              ))}
            </section>
          )}
        </>
      )}

      <p className="muted" style={{ fontSize: "12.5px", marginTop: 34 }}>
        Portfolio news is not wired yet and is deliberately empty — it needs the
        position list and a search backend.
      </p>
    </div>
  );
}
