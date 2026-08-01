import React from "react";
import { get } from "../api.js";
import {
  Banner, Button, Card, ErrorNote, Field, Mascot, PageHeader, Pill, Tabs,
  inputStyle,
} from "../ui.jsx";

export default function Prep() {
  const [tab, setTab] = React.useState("From my calendar");
  const [wantBrief, setWantBrief] = React.useState(true);
  const [wantScreen, setWantScreen] = React.useState(true);
  const [events, setEvents] = React.useState([]);
  const [eventIdx, setEventIdx] = React.useState(0);
  const [typedName, setTypedName] = React.useState("");
  const [typedCompany, setTypedCompany] = React.useState("");
  const [deck, setDeck] = React.useState(null);
  const [deckName, setDeckName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [stages, setStages] = React.useState([]);
  const [elapsed, setElapsed] = React.useState(0);
  const [eta, setEta] = React.useState(0);
  const [jobId, setJobId] = React.useState(null);
  const [result, setResult] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [cancelled, setCancelled] = React.useState(false);

  React.useEffect(() => {
    get("/api/calendar").then((d) => setEvents(d.events)).catch(() => {});
  }, []);

  // The prep runs as a server-side job: it keeps going if you navigate away,
  // and this page re-attaches to the newest job when you come back.
  const pollRef = React.useRef(null);

  function attach(id) {
    clearInterval(pollRef.current);
    setBusy(true); setJobId(id); setCancelled(false);
    pollRef.current = setInterval(async () => {
      try {
        const j = await get(`/api/jobs/${id}`);
        setStages(j.stages); setElapsed(j.elapsed); setEta(j.eta || 0);
        if (j.status !== "running") {
          clearInterval(pollRef.current);
          setBusy(false); setJobId(null);
          if (j.status === "error") setError(j.error);
          else if (j.status === "cancelled") setCancelled(true);
          else setResult(j.result);
        }
      } catch (e) {
        clearInterval(pollRef.current);
        setBusy(false); setJobId(null); setError(e.message);
      }
    }, 1200);
  }

  async function cancel() {
    if (!jobId) return;
    try { await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" }); }
    catch { /* job may already be finishing */ }
  }

  React.useEffect(() => {
    get("/api/jobs?kind=prep").then(({ jobs }) => {
      const latest = jobs[0];
      if (!latest) return;
      if (latest.status === "running") { setStages(latest.stages); attach(latest.id); }
      else get(`/api/jobs/${latest.id}`).then((j) => {
        setStages(j.stages); setElapsed(j.elapsed);
        if (j.status === "error") setError(j.error); else setResult(j.result);
      });
    }).catch(() => {});
    return () => clearInterval(pollRef.current);
  }, []);

  async function prepare(fields, file) {
    setError(null); setResult(null); setStages([]); setElapsed(0);
    const fd = new FormData();
    Object.entries({
      ...fields,
      include_briefing: wantBrief ? "1" : "0",
      include_screen: wantScreen ? "1" : "0",
    }).forEach(([k, v]) => v != null && fd.append(k, v));
    if (file) fd.append("file", file, file.name);
    try {
      const res = await fetch("/api/jobs/prep", { method: "POST", body: fd });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const job = await res.json();
      setStages(job.stages);
      attach(job.id);
    } catch (e) { setError(e.message); }
  }

  const ev = events[eventIdx];
  const nothingPicked = !wantBrief && !wantScreen;

  return (
    <div className="fade-in">
      <PageHeader eyebrow="PREPARATION · BRIEFING" title="Meeting prep">
        Who you're meeting, what they do, our history with them, and what to probe.
      </PageHeader>

      <div className="row" style={{ marginBottom: ".4rem" }}>
        <span className="eyebrow" style={{ margin: 0 }}>PREPARE</span>
        <label className="small" style={{ display: "flex", gap: ".35rem", alignItems: "center" }}>
          <input type="checkbox" checked={wantBrief} onChange={(e) => setWantBrief(e.target.checked)} />
          Meeting briefing
        </label>
        <label className="small" style={{ display: "flex", gap: ".35rem", alignItems: "center" }}>
          <input type="checkbox" checked={wantScreen} onChange={(e) => setWantScreen(e.target.checked)} />
          Preference review (against the Notion CHAO pages)
        </label>
      </div>
      {nothingPicked && <Banner tone="warning">Pick at least one of briefing / preference review.</Banner>}

      <Tabs tabs={["From my calendar", "By manager name", "From an attachment"]}
        active={tab} onChange={setTab} />

      {tab === "From my calendar" && (
        <Card>
          <Field label="Upcoming meetings">
            <select value={eventIdx} onChange={(e) => setEventIdx(+e.target.value)} style={inputStyle}>
              {events.map((e, i) => (
                <option key={i} value={i}>{e.start?.slice(0, 16).replace("T", " ")} — {e.subject}</option>
              ))}
            </select>
          </Field>
          {ev && <p className="muted small">Counterparty detected: <b>{ev.counterparty_name}</b>{ev.counterparty_email && ` (${ev.counterparty_email})`}</p>}
          <Button busy={busy} disabled={!ev || nothingPicked}
            onClick={() => prepare({
              name: ev.counterparty_name, email: ev.counterparty_email,
              event: JSON.stringify(ev),
            })}>
            Prepare me
          </Button>
        </Card>
      )}

      {tab === "By manager name" && (
        <Card>
          <Field label="Manager or firm name">
            <input value={typedName} onChange={(e) => setTypedName(e.target.value)}
              placeholder="e.g. Old Well Labs" style={inputStyle} />
          </Field>
          <Field label="Company (optional)">
            <input value={typedCompany} onChange={(e) => setTypedCompany(e.target.value)} style={inputStyle} />
          </Field>
          <Button busy={busy} disabled={!typedName || nothingPicked}
            onClick={() => prepare({ name: typedName, company: typedCompany })}>
            Prepare me
          </Button>
        </Card>
      )}

      {tab === "From an attachment" && (
        <Card>
          <Field label="Deck or tearsheet (PDF)">
            <input type="file" accept=".pdf" onChange={(e) => setDeck(e.target.files[0])} />
          </Field>
          <Field label="Counterparty name (optional — helps matching)">
            <input value={deckName} onChange={(e) => setDeckName(e.target.value)} style={inputStyle} />
          </Field>
          <Button busy={busy} disabled={!deck || nothingPicked}
            onClick={() => prepare({
              name: deckName || deck.name.replace(/\.[^.]+$/, ""),
            }, deck)}>
            Prepare me
          </Button>
        </Card>
      )}

      {(busy || stages.length > 0) && !result && (
        <Card style={{ marginTop: "1rem" }}>
          {stages.map((s, i) => (
            <div key={i} style={{ display: "flex", gap: ".6rem", alignItems: "baseline", padding: ".25rem 0" }}>
              <span className="mono" style={{ color: "var(--teal-600)" }}>
                {i < stages.length - 1 || !busy ? "✓" : "·"}
              </span>
              <div>
                <b className="small">{s.label}</b>
                {s.detail && <span className="muted small"> — {s.detail}</span>}
                {busy && i === stages.length - 1 && elapsed > 0 && (
                  <span className="mono small" style={{ color: "var(--teal-700)" }}> · {elapsed}s</span>
                )}
              </div>
            </div>
          ))}
          {busy && (
            <>
              <div className="spread" style={{ alignItems: "center" }}>
                <Mascot state="thinking" width={84}
                  text={eta > 0
                    ? (eta - elapsed > 0
                        ? `≈${eta - elapsed}s remaining (based on recent runs)`
                        : "taking longer than recent runs — still working…")
                    : `${elapsed}s elapsed`} />
                <Button variant="secondary" onClick={cancel}>Cancel</Button>
              </div>
              <p className="muted small" style={{ margin: 0 }}>
                Runs in the background — you can move to another page and come back;
                the result will be waiting here. Cancel stops it at the next step and
                discards any in-flight output.
              </p>
            </>
          )}
        </Card>
      )}
      {cancelled && <Banner tone="warning">Preparation cancelled — nothing was produced.</Banner>}
      <ErrorNote error={error} />

      {result?.screen && <ScreenView screen={result.screen} />}
      {result?.briefing && <BriefingView data={result.briefing} />}
    </div>
  );
}

function ScreenView({ screen }) {
  const tone = { Fit: "success", Partial: "warning", "Non-fit": "error", Unclear: "info" }[screen.overall_fit];
  return (
    <Card style={{ marginTop: "1.4rem" }}>
      <span className="eyebrow">PREFERENCE REVIEW · CHAO</span>
      <Banner tone={tone}><b>{screen.overall_fit}</b> · {screen.sleeve} — {screen.summary}</Banner>
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div><b className="small">Fits</b>
          <ul className="small">{screen.fit_points.map((p, i) => <li key={i}>{p}</li>)}</ul></div>
        <div><b className="small">Non-fits</b>
          <ul className="small">{screen.non_fit_points.map((p, i) => <li key={i}>{p}</li>)}</ul></div>
      </div>
      {screen.open_questions?.length > 0 && (
        <><b className="small">Open questions</b>
          <ul className="small">{screen.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></>
      )}
    </Card>
  );
}

function SectionHead({ n, title }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: ".8rem",
                  borderBottom: "1px solid var(--ink-800)", padding: "0 0 .4rem",
                  margin: "1.8rem 0 1rem" }}>
      <span className="mono" style={{ color: "var(--teal-600)", fontSize: ".8rem" }}>{n}</span>
      <h3 style={{ margin: 0, fontWeight: 500 }}>{title}</h3>
    </div>
  );
}

function QList({ items }) {
  return (
    <ol style={{ margin: 0, padding: 0, listStyle: "none" }}>
      {items.map((q, i) => (
        <li key={i} style={{ display: "grid", gridTemplateColumns: "28px 1fr", gap: 10,
                             padding: ".55rem 0", borderBottom: "1px dotted var(--paper-300)" }}>
          <span className="mono small" style={{ color: "var(--brass-500)" }}>
            {String(i + 1).padStart(2, "0")}
          </span>
          <div>
            <div style={{ fontFamily: "var(--serif)", fontSize: ".97rem" }}>{q.q}</div>
            <div className="mono muted" style={{ fontSize: ".7rem", marginTop: 3 }}>→ {q.src}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}

function BriefingView({ data }) {
  return (
    <div style={{ marginTop: "1.4rem" }}>
      <Card style={{ background: "var(--ink-800)", color: "var(--paper-050)", border: "none" }}>
        <span className="eyebrow" style={{ color: "var(--teal-300)" }}>PRE-MEETING BRIEFING · PRIVATE &amp; CONFIDENTIAL</span>
        <h2 style={{ color: "var(--paper-050)", fontWeight: 300, fontSize: "2rem", margin: ".2rem 0" }}>
          {data.entity}
        </h2>
        <p style={{ fontStyle: "italic", color: "var(--teal-300)", margin: 0 }}>{data.descriptor}</p>
        <div className="row" style={{ marginTop: "1rem", gap: "2rem" }}>
          {[["Status", data.relationship], ["Meeting", data.meeting_details],
            ["Vehicle", data.vehicle]].filter(([, v]) => v).map(([k, v]) => (
            <div key={k}>
              <span className="eyebrow" style={{ margin: 0, color: "var(--stone-400)" }}>{k}</span>
              <div className="small" style={{ color: "var(--paper-050)" }}>{v}</div>
            </div>
          ))}
        </div>
      </Card>

      <SectionHead n="1" title="Historical meeting context" />
      {data.meetings?.length
        ? data.meetings.map((m, i) => (
            <div key={i} style={{ borderBottom: "1px dotted var(--paper-300)", padding: ".6rem 0" }}>
              <div className="spread"><b>{m.title}</b><span className="mono muted small">{m.date}</span></div>
              <div className="mono muted" style={{ fontSize: ".72rem" }}>{m.format} · {m.attendees}</div>
              <p className="small" style={{ margin: ".35rem 0 0" }}>{m.summary}</p>
              <div className="mono muted" style={{ fontSize: ".68rem", marginTop: 2 }}>{m.source}</div>
            </div>
          ))
        : <p className="small">{data.no_meetings_text || "No qualifying meetings on record."}</p>}
      {data.other_mentions?.length > 0 && (
        <>
          <b className="small" style={{ display: "block", marginTop: ".8rem" }}>Other mentions</b>
          {data.other_mentions.map((mn, i) => (
            <div key={i} style={{ borderLeft: "2px solid var(--paper-300)", padding: ".2rem .8rem",
                                  margin: ".5rem 0", fontSize: ".88rem", color: "var(--stone-600)" }}>
              <span className="mono" style={{ fontSize: ".68rem" }}>{mn.source} · {mn.date} · {mn.context}</span>
              <div>{mn.text}</div>
            </div>
          ))}
        </>
      )}

      <SectionHead n="2" title="Background research" />
      <b className="small">Sector &amp; market landscape</b><Markdown text={data.landscape_md} />
      <b className="small">Manager background</b><Markdown text={data.manager_bg_md} />
      <b className="small">Potential red flags</b><Markdown text={data.red_flags_md} />

      <SectionHead n="3" title="Strategy" />
      <Markdown text={data.strategy_md} />

      <SectionHead n="4" title="Questions for the manager" />
      <b className="small">A. Strategy &amp; direction</b>
      <QList items={data.questions_a || []} />
      <b className="small" style={{ display: "block", marginTop: "1rem" }}>B. Manager-level &amp; structural</b>
      <QList items={data.questions_b || []} />

      <SectionHead n="5" title="Deals" />
      {!data.is_manager ? (
        <p className="small" style={{ fontStyle: "italic", color: "var(--stone-500)" }}>
          {data.deals_omit_text || "Omitted: the relationship is not an investment manager or fund."}
        </p>
      ) : (
        <>
          {data.ledger?.length > 0 && (
            <div style={{ overflowX: "auto", marginBottom: "1rem" }}>
              <table className="small" style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead><tr>
                  {["Company", "Fund · sector", "Entry", "Cost", "Own.", "MoIC", "IRR", "Business"].map((h) => (
                    <th key={h} className="eyebrow" style={{ textAlign: "left", padding: ".3rem .6rem .3rem 0",
                      borderBottom: "1px solid var(--ink-600)" }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {data.ledger.map((r, i) => (
                    <tr key={i} style={{
                      borderBottom: "1px dotted var(--paper-300)",
                      background: r.hot ? "var(--paper-100)" : "transparent",
                      boxShadow: r.hot ? "inset 2px 0 0 var(--brass-500)" : "none",
                    }}>
                      <td style={{ padding: ".35rem .6rem .35rem 0", fontWeight: 600 }}>{r.company}</td>
                      <td>{r.fund_sector}</td>
                      <td className="mono">{r.entry}</td>
                      <td className="mono">{r.cost}</td>
                      <td className="mono">{r.ownership}</td>
                      <td className="mono">{r.moic}</td>
                      <td className="mono">{r.irr}</td>
                      <td className="muted">{r.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.deal_cards?.map((c, i) => (
            <Card key={i} style={{ marginBottom: ".8rem" }}>
              <div className="spread"><b>{c.name}</b><span className="mono muted small">{c.figs}</span></div>
              {[["Business", c.business], ["What the manager did", c.actions],
                ["Latest newsflow", c.newsflow]].map(([k, v]) => (
                <div key={k} style={{ marginTop: ".5rem" }}>
                  <span className="eyebrow" style={{ margin: 0 }}>{k}</span>
                  <p className="small" style={{ margin: ".15rem 0 0" }}>{v}</p>
                </div>
              ))}
              {c.questions?.length > 0 && (
                <div style={{ marginTop: ".5rem" }}>
                  <span className="eyebrow" style={{ margin: 0 }}>Questions</span>
                  <QList items={c.questions} />
                </div>
              )}
              {c.key_flag && (
                <div style={{ borderLeft: "2px solid var(--brass-500)", background: "var(--brass-100)",
                              padding: ".5rem .8rem", marginTop: ".6rem", fontSize: ".88rem" }}>
                  <span className="mono" style={{ fontSize: ".65rem", letterSpacing: ".12em",
                    textTransform: "uppercase", color: "var(--brass-700)", display: "block" }}>Key flag</span>
                  {c.key_flag}
                </div>
              )}
            </Card>
          ))}
          {data.standouts_md && (<><b className="small">Standouts</b><Markdown text={data.standouts_md} /></>)}
        </>
      )}

      <SectionHead n="6" title="Sources" />
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {(data.sources || []).map((s, i) => (
          <li key={i} className="small" style={{ padding: ".35rem 0", borderBottom: "1px dotted var(--paper-200)" }}>
            <span className="mono muted" style={{ fontSize: ".68rem", textTransform: "uppercase",
              letterSpacing: ".1em", marginRight: ".8rem" }}>{s.kind}</span>
            {s.text}
          </li>
        ))}
      </ul>
      <p className="muted small" style={{ fontStyle: "italic" }}>
        Prepared from Notion, Outlook and independent research. Teams chat is never used
        as a source.
      </p>
    </div>
  );
}

/* Tiny markdown renderer: headings, bold, bullets. */
export function Markdown({ text }) {
  const html = String(text || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/^### (.*)$/gm, "<h4>$1</h4>")
    .replace(/^## (.*)$/gm, "<h3>$1</h3>")
    .replace(/^# (.*)$/gm, "<h2>$1</h2>")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/^- (.*)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`)
    .replace(/\n{2,}/g, "</p><p>");
  return <div className="small" style={{ lineHeight: 1.6, margin: ".3rem 0 1rem" }}
    dangerouslySetInnerHTML={{ __html: `<p>${html}</p>` }} />;
}
