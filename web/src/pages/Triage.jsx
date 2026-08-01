import React from "react";
import { get, post } from "../api.js";
import {
  Banner, Button, Card, Chip, ErrorNote, Mascot, PageHeader, SectionHead,
} from "../ui.jsx";
import * as uiStore from "../uiStore.js";

export default function Triage() {
  const [days, setDays] = React.useState(3);
  const [top, setTop] = React.useState(25);
  const [messages, setMessages] = React.useState(null);
  const [notionLive, setNotionLive] = React.useState(true);
  const [results, setResults] = React.useState({});
  const [selected, setSelected] = React.useState(new Set());
  const [activeId, setActiveId] = React.useState(null);
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState(null);
  const [notice, setNotice] = React.useState(null);

  async function scan() {
    setBusy("scan"); setError(null); setResults({}); setNotice(null); setActiveId(null);
    try {
      const data = await get(`/api/inbox?days=${days}&top=${top}`);
      setMessages(data.messages);
      setSelected(new Set(data.messages.map((m) => m.id)));
      setNotionLive(data.notion_live);
      setActiveId(data.messages[0]?.id ?? null);
      uiStore.setInboxCount(data.messages.length);
    } catch (e) { setError(e.message); }
    setBusy("");
  }

  async function triageSelected() {
    setBusy("triage"); setError(null);
    let firstRelevant = null;
    for (const m of messages.filter((m) => selected.has(m.id))) {
      try {
        const r = await post("/api/triage", { message: m });
        setResults((prev) => ({ ...prev, [m.id]: r }));
        if (!firstRelevant && r.is_investment) {
          firstRelevant = m.id;
          setActiveId(m.id);
        }
      } catch (e) {
        setError(`Stopped at “${m.subject}”: ${e.message}`);
        break;
      }
    }
    setBusy("");
  }

  async function deleteMessage(m) {
    if (!window.confirm(`Move “${m.subject}” to Deleted Items?`)) return;
    setBusy(`del-${m.id}`); setError(null);
    try {
      const r = await post("/api/messages/delete", { message_id: m.id });
      setMessages((prev) => prev.filter((x) => x.id !== m.id));
      setSelected((prev) => { const n = new Set(prev); n.delete(m.id); return n; });
      if (activeId === m.id) setActiveId(null);
      setNotice("Moved to Deleted Items — recoverable in Outlook."
        + (r.live ? "" : " (Demo mode — nothing was actually moved.)"));
    } catch (e) { setError(e.message); }
    setBusy("");
  }

  const triaged = Object.keys(results).length;
  const relevant = Object.values(results).filter((r) => r.is_investment).length;
  const active = messages?.find((m) => m.id === activeId);

  return (
    <div className="fade-in">
      <PageHeader eyebrow="MAIL · TRIAGE" title="Inbox triage"
        actions={
          <>
            <label className="microlabel" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              LOOK BACK
              <select value={days} onChange={(e) => setDays(+e.target.value)}>
                {[3, 7, 14].map((d) => <option key={d} value={d}>{d} days</option>)}
              </select>
            </label>
            <label className="microlabel" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              MAX
              <select value={top} onChange={(e) => setTop(+e.target.value)}>
                {[25, 50, 100].map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <Button busy={busy === "scan"} onClick={scan}>Scan inbox</Button>
          </>
        }>
        Flag investment-relevant mail, check it against Notion, screen it against our
        preferences, and draft a reply. Nothing is sent or written without your approval.
      </PageHeader>

      <ErrorNote error={error} />
      {notice && <Banner tone="success">{notice}</Banner>}

      {messages === null && <Mascot state="coffee" width={64} text="Press Scan inbox to begin." />}
      {messages?.length === 0 && (
        <Mascot state="celebrating" width={64}
          text={`Nothing in the Inbox from the last ${days} day(s) — everything is filed or already dealt with.`} />
      )}

      {messages?.length > 0 && (
        <>
          <div className="spread" style={{ margin: "0 0 18px", flexWrap: "wrap", gap: 12 }}>
            <div className="row" style={{ gap: 14 }}>
              <Mascot state="filing" width={44} />
              <span className="mono" style={{ fontSize: 11, letterSpacing: ".12em",
                textTransform: "uppercase", color: "var(--stone-500)" }}>
                {messages.length} MESSAGES · {triaged} TRIAGED · {relevant} INVESTMENT-RELEVANT · LAST {days} DAYS
              </span>
            </div>
            <div className="row">
              <span className="muted small">{selected.size} of {messages.length} selected</span>
              <Button variant="ghost" onClick={() =>
                setSelected(selected.size === messages.length
                  ? new Set() : new Set(messages.map((m) => m.id)))}>
                {selected.size === messages.length ? "Deselect all" : "Select all"}
              </Button>
              <Button variant="dark" busy={busy === "triage"}
                disabled={!selected.size} onClick={triageSelected}>
                Triage {selected.size} selected
              </Button>
            </div>
          </div>
          {busy === "triage" && (
            <p className="muted small">One call per message — {triaged}/{selected.size} done…</p>
          )}
          {!notionLive && triaged > 0 && (
            <Banner tone="warning">
              Dedupe ran against sample data, not your live Notion — “appears to be new”
              only means new to the sample set.
            </Banner>
          )}

          <div className="panes">
            {/* Message list */}
            <div style={{ flex: "1 1 320px", minWidth: "min(100%,300px)", maxWidth: 440 }}>
              {messages.map((m) => {
                const r = results[m.id];
                const isActive = m.id === activeId;
                const relevantRow = r?.is_investment;
                return (
                  <div key={m.id} onClick={() => setActiveId(m.id)} className="rrow click" style={{
                    padding: "16px 14px", display: "flex", flexDirection: "column", gap: 7,
                    background: isActive ? "var(--paper-000)" : "transparent",
                    borderLeft: isActive ? "2px solid var(--teal-500)" : "2px solid transparent",
                    opacity: r && !relevantRow ? 0.6 : 1, cursor: "pointer",
                  }}>
                    <div style={{ display: "flex", gap: 9, alignItems: "baseline" }}>
                      <input type="checkbox" checked={selected.has(m.id)}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => setSelected((prev) => {
                          const n = new Set(prev);
                          n.has(m.id) ? n.delete(m.id) : n.add(m.id);
                          return n;
                        })} />
                      <span className="dot" style={{
                        width: 7, height: 7, marginTop: 4,
                        background: relevantRow ? "var(--teal-500)" : "transparent",
                        border: relevantRow ? "none" : "1px solid var(--stone-300)",
                      }} />
                      <span style={{ fontSize: "14.5px", flex: 1,
                        fontWeight: isActive ? 600 : 400,
                        color: r && !relevantRow ? "var(--stone-600)" : "var(--ink-800)" }}>
                        {m.subject}
                      </span>
                      <button onClick={(e) => { e.stopPropagation(); deleteMessage(m); }}
                        title="Move to Deleted Items" style={{
                          background: "none", border: "none", cursor: "pointer",
                          color: "var(--critical-600)", fontFamily: "var(--mono)", fontSize: 11,
                        }}>
                        {busy === `del-${m.id}` ? "…" : "×"}
                      </button>
                    </div>
                    <span style={{ fontSize: 13, color: "var(--stone-600)" }}>
                      {m.sender_name || m.sender_email}{m.has_attachments ? " · attachment" : ""}
                    </span>
                    <span className="mono" style={{ fontSize: 10, letterSpacing: ".1em",
                      textTransform: "uppercase", color: "var(--stone-400)" }}>
                      {(m.received || "").slice(5, 16).replace("T", " ")}
                      {r && ` · ${r.category} · ${Math.round(r.confidence * 100)}%`}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Detail pane */}
            <div style={{ flex: "3 1 460px", minWidth: "min(100%,320px)" }}>
              {active
                ? <DetailPane msg={active} result={results[active.id]} />
                : <p className="muted small">Select a message.</p>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function DetailPane({ msg, result }) {
  const [screen, setScreen] = React.useState(null);
  const [options, setOptions] = React.useState(null);
  const [chosen, setChosen] = React.useState(0);
  const [draftBody, setDraftBody] = React.useState("");
  const [approved, setApproved] = React.useState(new Set());
  const [busy, setBusy] = React.useState("");
  const [notice, setNotice] = React.useState(null);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    setScreen(null); setOptions(null); setDraftBody(""); setNotice(null); setError(null);
    setApproved(new Set((result?.proposals || []).filter((p) => !p.needs_review).map((p) => p.kind)));
  }, [msg.id, result]);

  async function call(name, fn) {
    setBusy(name); setError(null);
    try { await fn(); } catch (e) { setError(e.message); }
    setBusy("");
  }

  const applyPlan = () => call("apply", async () => {
    const r = await post("/api/notion/apply", {
      proposals: result.proposals, approved_kinds: [...approved],
    });
    setNotice(`Created: ${r.created.map((c) => c[0]).join(", ") || "none"}.`
      + (r.live ? "" : " (Demo mode — nothing was actually written.)"));
  });

  const runScreen = () => call("screen", async () => {
    setScreen(await post("/api/screen", { entity: result.entity, key_facts: result.key_facts }));
  });

  const genDrafts = () => call("drafts", async () => {
    const r = await post("/api/drafts", { message: msg, entity: result.entity, screen });
    setOptions(r.options); setChosen(0); setDraftBody(r.options[0]?.body || "");
  });

  const saveDraft = () => call("save", async () => {
    const r = await post("/api/drafts/save", { message_id: msg.id, body: draftBody });
    setNotice("Draft saved to Outlook — review and send it there."
      + (r.live ? "" : " (Demo mode — no draft was actually created.)"));
  });

  const verdictColor = screen && { Fit: "var(--positive-600)", Partial: "var(--caution-600)",
    "Non-fit": "var(--critical-600)", Unclear: "var(--stone-500)" }[screen.overall_fit];

  return (
    <Card style={{ padding: 0 }}>
      {/* Head block */}
      <div style={{ padding: "22px 24px 18px", borderBottom: "1px solid var(--paper-200)" }}>
        {result && (
          <div className="row" style={{ marginBottom: 10 }}>
            {result.is_investment
              ? <Chip tone="teal">INVESTMENT-RELEVANT</Chip>
              : <Chip tone="neutral">NOT RELEVANT</Chip>}
            <span className="mono" style={{ fontSize: 10, letterSpacing: ".1em",
              textTransform: "uppercase", color: "var(--stone-400)" }}>
              {result.category} · {Math.round(result.confidence * 100)}%
            </span>
          </div>
        )}
        <div style={{ font: "400 24px/1.25 var(--serif)", color: "var(--ink-800)" }}>{msg.subject}</div>
        <div style={{ fontSize: "13.5px", color: "var(--stone-500)", margin: "6px 0 10px" }}>
          {msg.sender_name} &lt;{msg.sender_email}&gt; · {msg.received}
        </div>
        <p style={{ fontSize: "14.5px", lineHeight: 1.6, color: "var(--stone-600)",
                    maxWidth: "60ch", margin: 0 }}>
          {msg.body_preview || (msg.body || "").slice(0, 400)}
        </p>
        {result?.rationale && (
          <p className="muted" style={{ fontSize: "13px", margin: "10px 0 0" }}>{result.rationale}</p>
        )}
      </div>

      <div style={{ padding: "0 24px 20px" }}>
        {!result && <Banner>Not yet triaged — select it and run triage.</Banner>}
        {result && !result.is_investment && (
          <Banner>Not investment-relevant — nothing further to do.</Banner>
        )}

        {result?.is_investment && (
          <>
            {/* Step 1 — Notion */}
            <Step n={1} label="NOTION" state="done"
              right={result.proposals?.length
                ? `${result.proposals.length} TO CREATE · ${Object.values(result.dedupe || {}).filter((d) => d.action === "link_existing").length} LINKED`
                : "ALL LINKED"}>
              {Object.entries(result.dedupe || {}).map(([kind, d]) => (
                <div key={kind} className="rrow" style={{ display: "grid",
                  gridTemplateColumns: "80px minmax(0,1fr)", gap: 12 }}>
                  <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".12em",
                    textTransform: "uppercase", color: "var(--stone-400)", paddingTop: 2 }}>{kind}</span>
                  <span style={{ fontSize: "13.5px",
                    color: d.action === "link_existing" ? "var(--stone-600)"
                      : d.action === "review" ? "var(--caution-600)" : "var(--ink-700)" }}>
                    {d.action === "link_existing"
                      ? `Already in Notion as “${d.match}” (${d.reason}). Will not create a duplicate.`
                      : d.action === "review"
                        ? `“${d.name}” looks similar to “${d.match}” (${Math.round((d.score || 0) * 100)}%) — held for your call.`
                        : `“${d.name}” appears to be new.`}
                  </span>
                </div>
              ))}
              {result.proposals?.map((p) => (
                <div key={p.kind} style={{ margin: "10px 0 0" }}>
                  <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: "13.5px" }}>
                    <input type="checkbox" checked={approved.has(p.kind)} onChange={(e) => {
                      const next = new Set(approved);
                      e.target.checked ? next.add(p.kind) : next.delete(p.kind);
                      setApproved(next);
                    }} />
                    Create {p.kind}: <b>{p.title}</b>
                    {p.needs_review && <Chip tone="caution">REVIEW</Chip>}
                  </label>
                  <div style={{ marginLeft: 24, display: "grid",
                    gridTemplateColumns: "130px 1fr", gap: "2px 12px", marginTop: 4 }}>
                    {p.properties.map(([k, v]) => (
                      <React.Fragment key={k}>
                        <span className="microlabel">{k}</span>
                        <span style={{ fontSize: "12.5px" }}>{v}</span>
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              ))}
              {result.proposals?.length > 0 && (
                <Button variant="ghost" busy={busy === "apply"} disabled={!approved.size}
                  onClick={applyPlan} style={{ marginTop: 12 }}>
                  Create {approved.size} approved {approved.size === 1 ? "entry" : "entries"}
                </Button>
              )}
            </Step>

            {/* Step 2 — Preference screen */}
            <Step n={2} label="PREFERENCE SCREEN" state={screen ? "done" : "current"}
              right={screen && (
                <span style={{ color: verdictColor }}>
                  {screen.overall_fit.toUpperCase()} · {screen.sleeve.toUpperCase()}
                </span>
              )}>
              {!screen && (
                <Button variant="ghost" busy={busy === "screen"} onClick={runScreen}>
                  Run preference screen
                </Button>
              )}
              {screen && (
                <>
                  <p style={{ fontSize: 14, lineHeight: 1.55, margin: "0 0 10px" }}>{screen.summary}</p>
                  <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))", gap: 16 }}>
                    <div>
                      <span className="microlabel" style={{ color: "var(--positive-600)" }}>FITS</span>
                      <div style={{ fontSize: "13.5px", marginTop: 4 }}>
                        {screen.fit_points.join(" · ") || "—"}
                      </div>
                    </div>
                    <div>
                      <span className="microlabel" style={{ color: "var(--critical-600)" }}>NON-FITS</span>
                      <div style={{ fontSize: "13.5px", marginTop: 4 }}>
                        {screen.non_fit_points.join(" · ") || "—"}
                      </div>
                    </div>
                  </div>
                </>
              )}
            </Step>

            {/* Step 3 — Reply */}
            <Step n={3} label="REPLY · DRAFT ONLY" state={options ? "done" : screen ? "current" : "pending"} last>
              {!options && (
                <Button variant="ghost" busy={busy === "drafts"} disabled={!screen} onClick={genDrafts}>
                  Generate reply options
                </Button>
              )}
              {options && (
                <>
                  <div className="row" style={{ marginBottom: 10 }}>
                    {options.map((o, i) => (
                      <Button key={i} variant={i === chosen ? "primary" : "ghost"}
                        style={{ fontSize: "12.5px", padding: "7px 12px" }}
                        onClick={() => { setChosen(i); setDraftBody(o.body); }}>{o.label}</Button>
                    ))}
                  </div>
                  <textarea value={draftBody} onChange={(e) => setDraftBody(e.target.value)}
                    rows={10} style={{
                      width: "100%", background: "var(--paper-050)",
                      border: "1px solid var(--paper-200)", borderRadius: "var(--radius)",
                      font: "400 15px/1.65 var(--serif)", color: "var(--ink-700)",
                      padding: "14px 16px",
                    }} />
                  <div className="row" style={{ marginTop: 10 }}>
                    <Button variant="dark" busy={busy === "save"} onClick={saveDraft}>
                      Save as draft in Outlook
                    </Button>
                    <span className="muted" style={{ fontSize: "12.5px" }}>
                      Replies are drafts only — nothing is ever sent from here.
                    </span>
                  </div>
                </>
              )}
            </Step>
          </>
        )}
        {notice && <Banner tone="success">{notice}</Banner>}
        <ErrorNote error={error} />
      </div>
    </Card>
  );
}

function Step({ n, label, right, state, last, children }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "26px minmax(0,1fr)", gap: 14,
                  padding: "20px 0", borderBottom: last ? "none" : "1px solid var(--paper-200)" }}>
      <span className={`stepnum ${state === "current" ? "current" : state === "done" ? "done" : "pending"}`}>{n}</span>
      <div>
        <div className="spread" style={{ marginBottom: 8 }}>
          <span className="microlabel">{label}</span>
          {right && <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".1em" }}>{right}</span>}
        </div>
        {children}
      </div>
    </div>
  );
}
