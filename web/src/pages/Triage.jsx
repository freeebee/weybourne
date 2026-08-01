import React from "react";
import { get, post } from "../api.js";
import {
  Banner, Button, Card, ErrorNote, Field, Mascot, PageHeader, Pill, Stat,
  inputStyle,
} from "../ui.jsx";

export default function Triage() {
  const [days, setDays] = React.useState(3);
  const [top, setTop] = React.useState(25);
  const [messages, setMessages] = React.useState(null);
  const [notionLive, setNotionLive] = React.useState(true);
  const [results, setResults] = React.useState({});   // id -> triage result
  const [selected, setSelected] = React.useState(new Set());
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState(null);
  const [notice, setNotice] = React.useState(null);

  async function scan() {
    setBusy("scan"); setError(null); setResults({}); setNotice(null);
    try {
      const data = await get(`/api/inbox?days=${days}&top=${top}`);
      setMessages(data.messages);
      setSelected(new Set(data.messages.map((m) => m.id)));   // all in by default
      setNotionLive(data.notion_live);
    } catch (e) { setError(e.message); }
    setBusy("");
  }

  function toggle(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function triageSelected() {
    setBusy("triage"); setError(null);
    for (const m of messages.filter((m) => selected.has(m.id))) {
      try {
        const r = await post("/api/triage", { message: m });
        setResults((prev) => ({ ...prev, [m.id]: r }));
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
      setNotice(`Moved to Deleted Items — recoverable in Outlook.`
        + (r.live ? "" : " (Demo mode — nothing was actually moved.)"));
    } catch (e) { setError(e.message); }
    setBusy("");
  }

  const flagged = Object.values(results).filter((r) => r.is_investment).length;

  return (
    <div className="fade-in">
      <PageHeader eyebrow="MAIL · TRIAGE" title="Inbox triage">
        Flag investment-relevant mail, check it against Notion, screen it against our
        preferences, and draft a reply. Nothing is sent or written without your approval.
      </PageHeader>

      <Card style={{ marginBottom: "1rem" }}>
        <span className="eyebrow">SCOPE · TOP-LEVEL INBOX</span>
        <p className="muted small" style={{ margin: "0 0 .8rem" }}>
          Anything filed into a subfolder is treated as dealt with and skipped.
        </p>
        <div className="row">
          <Button busy={busy === "scan"} onClick={scan}>Scan inbox</Button>
          <Field label="Look back (days)"><input type="number" min="1" max="30" value={days}
            onChange={(e) => setDays(+e.target.value)} style={{ ...inputStyle, width: 90 }} /></Field>
          <Field label="Max messages"><input type="number" min="5" max="100" value={top}
            onChange={(e) => setTop(+e.target.value)} style={{ ...inputStyle, width: 90 }} /></Field>
        </div>
      </Card>

      <ErrorNote error={error} />

      {messages === null && <Mascot state="coffee" text="Press Scan inbox to begin." />}
      {messages?.length === 0 && (
        <Mascot state="celebrating" text={`Nothing in the Inbox from the last ${days} day(s) — everything is filed or already dealt with.`} />
      )}

      {messages?.length > 0 && (
        <>
          <div className="spread" style={{ margin: "1rem 0" }}>
            <span className="eyebrow" style={{ margin: 0 }}>
              {messages.length} MESSAGE(S) · {selected.size} SELECTED · LAST {days} DAY(S)
            </span>
            <div className="row">
              {Object.keys(results).length > 0 && (
                <>
                  <Stat label="Investment-relevant" value={flagged} />
                  <Stat label="Not relevant" value={Object.keys(results).length - flagged} />
                </>
              )}
              <Button variant="ghost" onClick={() =>
                setSelected(selected.size === messages.length
                  ? new Set() : new Set(messages.map((m) => m.id)))}>
                {selected.size === messages.length ? "Deselect all" : "Select all"}
              </Button>
              <Button variant="secondary" busy={busy === "triage"}
                disabled={!selected.size} onClick={triageSelected}>
                Triage {selected.size} selected
              </Button>
            </div>
          </div>
          {notice && <Banner tone="success">{notice}</Banner>}
          {busy === "triage" && <Mascot state="crunching" width={80}
            text={`Triaging — one call per message, ${Object.keys(results).length}/${messages.length} done…`} />}
          {!notionLive && Object.keys(results).length > 0 && (
            <Banner tone="warning">
              <b>Not connected to your Notion</b> — dedupe ran against sample data, so
              “appears to be new” only means new to the sample set. Set NOTION_TOKEN in .env.
            </Banner>
          )}
          {messages.map((m) => (
            <MessageCard key={m.id} msg={m} result={results[m.id]}
              included={selected.has(m.id)} onToggle={() => toggle(m.id)}
              onDelete={() => deleteMessage(m)} deleting={busy === `del-${m.id}`} />
          ))}
        </>
      )}
    </div>
  );
}

function MessageCard({ msg, result, included, onToggle, onDelete, deleting }) {
  const [open, setOpen] = React.useState(true);
  const isInv = result?.is_investment;
  const badge = result ? (isInv ? "●" : "○") : "·";
  React.useEffect(() => { if (isInv) setOpen(true); }, [isInv]);

  return (
    <Card style={{ marginBottom: ".7rem", padding: 0, opacity: included ? 1 : 0.55 }}>
      <div style={{ display: "flex", gap: ".7rem", alignItems: "baseline",
                    padding: ".85rem 1.2rem" }}>
        <input type="checkbox" checked={included} onChange={onToggle}
          title="Include in triage" style={{ transform: "translateY(2px)" }} />
        <span className="mono" style={{ color: isInv ? "var(--teal-600)" : "var(--stone-400)" }}>{badge}</span>
        <button onClick={() => setOpen(!open)} style={{
          flex: 1, background: "none", border: "none", cursor: "pointer",
          textAlign: "left", fontSize: ".95rem", color: "var(--ink-800)",
          fontWeight: 500, padding: 0,
        }}>
          {msg.subject} <span className="muted" style={{ fontStyle: "italic", fontWeight: 400 }}>— {msg.sender_name}</span>
        </button>
        <button onClick={onDelete} disabled={deleting} title="Move to Deleted Items"
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: "var(--critical-500)", fontSize: ".85rem", fontFamily: "var(--mono)",
          }}>
          {deleting ? "…" : "delete"}
        </button>
        <button onClick={() => setOpen(!open)} className="mono muted small"
          style={{ background: "none", border: "none", cursor: "pointer" }}>
          {open ? "−" : "+"}
        </button>
      </div>
      {open && (
        <div style={{ padding: "0 1.2rem 1rem" }}>
          <div className="muted small">{msg.sender_email} · {msg.received}</div>
          <p className="small">{msg.body_preview || (msg.body || "").slice(0, 400)}</p>
          {!result && <Banner>Not yet triaged.</Banner>}
          {result && <TriageDetail msg={msg} result={result} />}
        </div>
      )}
    </Card>
  );
}

function TriageDetail({ msg, result }) {
  const [screen, setScreen] = React.useState(null);
  const [options, setOptions] = React.useState(null);
  const [chosen, setChosen] = React.useState(0);
  const [draftBody, setDraftBody] = React.useState("");
  const [approved, setApproved] = React.useState(
    () => new Set((result.proposals || []).filter((p) => !p.needs_review).map((p) => p.kind)),
  );
  const [busy, setBusy] = React.useState("");
  const [notice, setNotice] = React.useState(null);
  const [error, setError] = React.useState(null);

  async function call(name, fn) {
    setBusy(name); setError(null);
    try { await fn(); } catch (e) { setError(e.message); }
    setBusy("");
  }

  const applyPlan = () => call("apply", async () => {
    const r = await post("/api/notion/apply", {
      proposals: result.proposals, approved_kinds: [...approved],
    });
    setNotice(
      `Created: ${r.created.map((c) => c[0]).join(", ") || "none"}.` +
      (r.skipped.length ? ` Skipped: ${r.skipped.map((s) => s[0]).join(", ")}.` : "") +
      (r.live ? "" : " (Demo mode — nothing was actually written.)"),
    );
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

  return (
    <div>
      <p className="small"><b>{result.category}</b> · confidence {Math.round(result.confidence * 100)}%<br />{result.rationale}</p>
      {!result.is_investment && <Banner>Not investment-relevant — nothing further to do.</Banner>}
      {result.is_investment && (
        <>
          {result.key_facts?.length > 0 && (
            <ul className="small">{result.key_facts.map((f, i) => <li key={i}>{f}</li>)}</ul>
          )}

          <span className="eyebrow">STEP 1 · NOTION</span>
          {Object.entries(result.dedupe || {}).map(([kind, d]) => (
            <Banner key={kind} tone={d.action === "link_existing" ? "success" : d.action === "review" ? "warning" : "info"}>
              <b style={{ textTransform: "capitalize" }}>{kind}</b> — {
                d.action === "link_existing" ? <>already in Notion as “{d.match}” ({d.reason}). Will not create a duplicate.</>
                : d.action === "review" ? <>“{d.name}” looks similar to “{d.match}” ({Math.round((d.score || 0) * 100)}%). Needs your call.</>
                : <>“{d.name}” appears to be new.</>
              }
            </Banner>
          ))}

          {result.proposals?.length > 0 && (
            <>
              <p className="small" style={{ fontWeight: 600 }}>Proposed new Notion entries</p>
              {result.proposals.map((p) => (
                <div key={p.kind} style={{ margin: "0 0 .8rem" }}>
                  <label className="small" style={{ display: "flex", gap: ".5rem", alignItems: "center" }}>
                    <input type="checkbox" checked={approved.has(p.kind)} onChange={(e) => {
                      const next = new Set(approved);
                      e.target.checked ? next.add(p.kind) : next.delete(p.kind);
                      setApproved(next);
                    }} />
                    Create {p.kind}: <b>{p.title}</b>
                    {p.needs_review && <Pill tone="flag">needs review</Pill>}
                  </label>
                  {p.needs_review && <div className="muted small" style={{ marginLeft: "1.6rem" }}>{p.review_reason}</div>}
                  <div style={{ marginLeft: "1.6rem", borderLeft: "2px solid var(--paper-300)", padding: ".3rem .8rem", display: "grid", gridTemplateColumns: "140px 1fr", gap: "2px 12px" }}>
                    {p.properties.map(([k, v]) => (
                      <React.Fragment key={k}>
                        <span className="eyebrow" style={{ margin: 0 }}>{k}</span>
                        <span className="small">{v}</span>
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              ))}
              <Button variant="secondary" busy={busy === "apply"} disabled={!approved.size} onClick={applyPlan}>
                Create in Notion
              </Button>
            </>
          )}

          <div style={{ marginTop: "1rem" }}>
            <span className="eyebrow">STEP 2 · PREFERENCES</span>
            <Button variant="secondary" busy={busy === "screen"} onClick={runScreen}>Run preference screen</Button>
            {screen && (
              <div style={{ marginTop: ".6rem" }}>
                <Banner tone={{ Fit: "success", Partial: "warning", "Non-fit": "error", Unclear: "info" }[screen.overall_fit]}>
                  <b>{screen.overall_fit}</b> · {screen.sleeve} — {screen.summary}
                </Banner>
                <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
                  <div><b className="small">Fits</b><ul className="small">{screen.fit_points.map((p, i) => <li key={i}>{p}</li>)}</ul></div>
                  <div><b className="small">Non-fits</b><ul className="small">{screen.non_fit_points.map((p, i) => <li key={i}>{p}</li>)}</ul></div>
                </div>
              </div>
            )}
          </div>

          {screen && (
            <div style={{ marginTop: "1rem" }}>
              <span className="eyebrow">STEP 3 · REPLY</span>
              <Button variant="secondary" busy={busy === "drafts"} onClick={genDrafts}>Generate reply options</Button>
              {options && (
                <div style={{ marginTop: ".6rem" }}>
                  <div className="row">
                    {options.map((o, i) => (
                      <Button key={i} variant={i === chosen ? "primary" : "ghost"}
                        onClick={() => { setChosen(i); setDraftBody(o.body); }}>{o.label}</Button>
                    ))}
                  </div>
                  <textarea value={draftBody} onChange={(e) => setDraftBody(e.target.value)}
                    rows={10} style={{ ...inputStyle, marginTop: ".6rem", fontFamily: "var(--sans)" }} />
                  <Button busy={busy === "save"} onClick={saveDraft} style={{ marginTop: ".5rem" }}>
                    Save as draft in Outlook
                  </Button>
                </div>
              )}
            </div>
          )}
        </>
      )}
      {notice && <Banner tone="success">{notice}</Banner>}
      <ErrorNote error={error} />
    </div>
  );
}
