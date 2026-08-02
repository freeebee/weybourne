import React from "react";
import * as ts from "../triageStore.js";
import {
  Banner, Button, Card, Chip, ErrorNote, Mascot, PageHeader, Spinner,
} from "../ui.jsx";

const FLAG_META = {
  delete: ["critical", "SUGGEST DELETE"],
  no_response: ["critical", "NO RESPONSE NEEDED · SUGGEST DELETE"],
  shared: ["neutral", "TO SHARED INBOX"],
  triage: ["teal", "TRIAGE"],
  read: ["neutral", "SUGGEST READING"],
  respond: ["caution", "NEEDS RESPONSE"],
  priority: ["caution", "PRIORITY"],   // legacy value, still rendered
};

export default function Triage() {
  React.useSyncExternalStore(ts.subscribe, ts.getVersion);
  const s = ts.S;

  React.useEffect(() => { ts.restore(); }, []);

  const triaged = Object.keys(s.results).length;
  const relevant = Object.values(s.results).filter((r) => r.is_investment).length;
  const active = s.messages?.find((m) => m.id === s.activeId);
  const jobList = Object.values(s.jobs);
  const running = jobList.length > 0;
  const agg = jobList.reduce((a, j) => ({
    done: a.done + (j.done || 0), total: a.total + (j.total || 0),
    current: a.current || j.current,
    etaLeft: Math.max(a.etaLeft, j.eta > 0 ? j.eta - j.elapsed : 0),
  }), { done: 0, total: 0, current: "", etaLeft: 0 });
  const queueable = ts.triageable().length;

  return (
    <div className="fade-in">
      <PageHeader eyebrow="MAIL · TRIAGE" title="Inbox triage"
        actions={
          <>
            <label className="microlabel" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              LOOK BACK
              <select value={s.days} onChange={(e) => ts.set({ days: +e.target.value })}>
                {[3, 7, 14].map((d) => <option key={d} value={d}>{d} days</option>)}
              </select>
            </label>
            <label className="microlabel" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              MAX
              <select value={s.top} onChange={(e) => ts.set({ top: +e.target.value })}>
                {[25, 50, 100].map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <Button busy={s.scanBusy} onClick={ts.scan}>Scan inbox</Button>
          </>
        }>
        Flag investment-relevant mail, check it against Notion, screen it against our
        preferences, and draft a reply. Nothing is sent or written without your approval.
      </PageHeader>

      <ErrorNote error={s.error} />
      {s.notice && <Banner tone="success">{s.notice}</Banner>}

      {s.messages === null && !running &&
        <Mascot state="coffee" width={64} text="Press Scan inbox to begin." />}
      {s.messages?.length === 0 && (
        <Mascot state="celebrating" width={64}
          text={`Nothing in the Inbox from the last ${s.days} day(s) — everything is filed or already dealt with.`} />
      )}

      {s.messages?.length > 0 && (
        <>
          {/* Sticky meta bar — stays put while the list scrolls. */}
          <div style={{ position: "sticky", top: 0, zIndex: 5,
                        background: "var(--paper-050)", padding: "10px 0 12px",
                        borderBottom: "1px solid var(--paper-200)", marginBottom: 4 }}>
            <div className="spread" style={{ flexWrap: "wrap", gap: 12 }}>
              <div className="row" style={{ gap: 14 }}>
                <Mascot state={running ? "crunching" : "filing"} width={44} />
                <div>
                  <span className="mono" style={{ fontSize: 11, letterSpacing: ".12em",
                    textTransform: "uppercase", color: "var(--stone-500)", display: "block" }}>
                    {s.messages.length} MESSAGES · {triaged} TRIAGED · {relevant} RELEVANT
                    {s.flagsBusy && <span style={{ color: "var(--teal-700)" }}> · PRE-SORTING…</span>}
                  </span>
                  {running && (
                    <span className="mono" style={{ fontSize: 10.5, color: "var(--teal-700)" }}>
                      TRIAGING {agg.done}/{agg.total}
                      {agg.etaLeft > 0 && ` · ~${agg.etaLeft}S LEFT`}
                      {agg.current && ` · ${agg.current.slice(0, 44).toUpperCase()}`}
                    </span>
                  )}
                </div>
              </div>
              <div className="row">
                <span className="muted small">{s.selected.size} of {s.messages.length} selected</span>
                <Button variant="ghost"
                  onClick={() => ts.selectAll(s.selected.size !== s.messages.length)}>
                  {s.selected.size === s.messages.length ? "Deselect all" : "Select all"}
                </Button>
                <Button variant="dark" disabled={!queueable} onClick={ts.startTriage}>
                  {running ? `Queue ${queueable} more` : `Triage ${queueable} selected`}
                </Button>
              </div>
            </div>
          </div>
          {running && (
            <p className="muted" style={{ fontSize: "12.5px", margin: "6px 0 12px" }}>
              Runs in the background — leave this page, keep selecting, and queue more
              while it works; results keep landing.
            </p>
          )}
          {!s.notionLive && triaged > 0 && (
            <Banner tone="warning">
              Dedupe ran against sample data, not your live Notion.
            </Banner>
          )}

          <div className="panes">
            {/* Message list */}
            <div style={{ flex: "1 1 320px", minWidth: "min(100%,300px)", maxWidth: 440 }}>
              {s.messages.map((m) => {
                const r = s.results[m.id];
                const fl = s.flags[m.id];
                const isActive = m.id === s.activeId;
                const relevantRow = r?.is_investment;
                const inFlight = s.inFlight.has(m.id);
                return (
                  <div key={m.id} onClick={() => ts.set({ activeId: m.id })}
                    className="rrow click" style={{
                      padding: "14px", display: "flex", flexDirection: "column", gap: 6,
                      background: isActive ? "var(--paper-000)" : "transparent",
                      borderLeft: isActive ? "2px solid var(--teal-500)" : "2px solid transparent",
                      opacity: r && !relevantRow ? 0.6 : 1, cursor: "pointer",
                    }}>
                    <div style={{ display: "flex", gap: 9, alignItems: "baseline" }}>
                      <input type="checkbox" checked={s.selected.has(m.id)}
                        disabled={inFlight || !!r}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => ts.toggle(m.id)} />
                      <span className="dot" style={{
                        width: 7, height: 7, marginTop: 4, flex: "none",
                        background: relevantRow ? "var(--teal-500)" : "transparent",
                        border: relevantRow ? "none" : "1px solid var(--stone-300)",
                      }} />
                      <span style={{ fontSize: "14.5px", flex: 1,
                        fontWeight: isActive ? 600 : 400,
                        color: r && !relevantRow ? "var(--stone-600)" : "var(--ink-800)" }}>
                        {m.subject}
                      </span>
                      {inFlight && <Spinner size={12} />}
                      <button onClick={(e) => { e.stopPropagation(); ts.deleteMessage(m); }}
                        title="Move to Deleted Items" style={{
                          background: "none", border: "none", cursor: "pointer",
                          color: "var(--critical-600)", fontFamily: "var(--mono)", fontSize: 11,
                        }}>×</button>
                    </div>
                    <span style={{ fontSize: 13, color: "var(--stone-600)" }}>
                      {m.sender_name || m.sender_email}{m.has_attachments ? " · attachment" : ""}
                    </span>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <span className="mono" style={{ fontSize: 10, letterSpacing: ".1em",
                        textTransform: "uppercase", color: "var(--stone-400)" }}>
                        {(m.received || "").slice(5, 16).replace("T", " ")}
                        {r && ` · ${r.category} · ${Math.round(r.confidence * 100)}%`}
                      </span>
                      {fl && fl.flag !== "none" && (
                        <Chip tone={FLAG_META[fl.flag]?.[0] || "neutral"}>
                          {FLAG_META[fl.flag]?.[1] || fl.flag}
                        </Chip>
                      )}
                    </div>
                    {fl && fl.flag !== "none" && fl.reason && (
                      <span className="muted" style={{ fontSize: "11.5px", fontStyle: "italic" }}>
                        {fl.reason}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Detail pane — sticky, scrolls with you. */}
            <div style={{ flex: "3 1 460px", minWidth: "min(100%,320px)",
                          position: "sticky", top: 96, alignSelf: "flex-start",
                          maxHeight: "calc(100vh - 120px)", overflowY: "auto" }}>
              {active
                ? <DetailPane msg={active} result={s.results[active.id]} flag={s.flags[active.id]} />
                : <p className="muted small">Select a message.</p>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function DetailPane({ msg, result, flag }) {
  // All workflow state lives in the store, so a running preference screen or
  // draft generation keeps going when you navigate away and is here on return.
  const w = ts.getWork(msg.id);
  const { screen, options, chosen = 0, draftBody = "", busy = "", notice, error } = w;
  const approved = new Set(w.approved || []);

  const setApproved = (next) => ts.setWork(msg.id, { approved: [...next] });
  const applyPlan = () => ts.applyPlan(msg);
  const runScreen = () => ts.runScreen(msg);
  const genDrafts = () => ts.genDrafts(msg);
  const saveDraft = () => ts.saveDraft(msg);

  const verdictColor = screen && { Fit: "var(--positive-600)", Partial: "var(--caution-600)",
    "Non-fit": "var(--critical-600)", Unclear: "var(--stone-500)" }[screen.overall_fit];

  if (result?.error) {
    return <Card><ErrorNote error={`This message failed to triage: ${result.error}`} /></Card>;
  }

  return (
    <Card style={{ padding: 0 }}>
      <div style={{ padding: "22px 24px 18px", borderBottom: "1px solid var(--paper-200)" }}>
        <div className="row" style={{ marginBottom: 10 }}>
          {result && (result.is_investment
            ? <Chip tone="teal">INVESTMENT-RELEVANT</Chip>
            : <Chip tone="neutral">NOT RELEVANT</Chip>)}
          {flag && flag.flag !== "none" && (
            <Chip tone={FLAG_META[flag.flag]?.[0] || "neutral"}>{FLAG_META[flag.flag]?.[1]}</Chip>
          )}
          {result && (
            <span className="mono" style={{ fontSize: 10, letterSpacing: ".1em",
              textTransform: "uppercase", color: "var(--stone-400)" }}>
              {result.category} · {Math.round(result.confidence * 100)}%
            </span>
          )}
        </div>
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
        {!result && <Banner>Not yet triaged — include it in a triage run.</Banner>}
        {result && !result.is_investment && (
          <Banner>
            Not investment-relevant — but the sender has still been checked
            against Notion below, and you can save the email, screen it, or
            draft a reply as usual.
          </Banner>
        )}

        {result && (
          <>
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
              {result.proposals?.map((p) => {
                const editing = !!w.editing?.[p.kind];
                const edits = w.edits?.[p.kind] || {};
                return (
                  <div key={p.kind} style={{ margin: "10px 0 0" }}>
                    <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: "13.5px" }}>
                      <input type="checkbox" checked={approved.has(p.kind)} onChange={(e) => {
                        const next = new Set(approved);
                        e.target.checked ? next.add(p.kind) : next.delete(p.kind);
                        setApproved(next);
                      }} />
                      Create {p.kind}: <b>{edits.Name ?? p.title}</b>
                      {p.needs_review && <Chip tone="caution">REVIEW</Chip>}
                      <button onClick={(e) => { e.preventDefault(); ts.toggleProposalEdit(msg.id, p.kind); }}
                        style={{ background: "none", border: "none", cursor: "pointer",
                                 color: "var(--teal-700)", fontFamily: "var(--mono)",
                                 fontSize: 10.5, letterSpacing: ".1em" }}>
                        {editing ? "DONE" : "EDIT"}
                      </button>
                    </label>
                    <div style={{ marginLeft: 24, display: "grid",
                      gridTemplateColumns: "130px 1fr", gap: "2px 12px", marginTop: 4 }}>
                      {p.properties.map(([k, v]) => (
                        <React.Fragment key={k}>
                          <span className="microlabel" style={{ paddingTop: editing ? 6 : 0 }}>{k}</span>
                          {editing ? (
                            <input value={edits[k] ?? v}
                              onChange={(e) => ts.setProposalEdit(msg.id, p.kind, k, e.target.value)}
                              style={{ fontSize: "12.5px", padding: "4px 8px",
                                       background: "var(--paper-050)",
                                       border: "1px solid var(--paper-200)",
                                       borderRadius: 4, color: "var(--ink-700)" }} />
                          ) : (
                            <span style={{ fontSize: "12.5px",
                              color: k in edits ? "var(--teal-700)" : "inherit" }}>
                              {edits[k] ?? v}
                            </span>
                          )}
                        </React.Fragment>
                      ))}
                    </div>
                  </div>
                );
              })}
              <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
                {result.proposals?.length > 0 && (
                  <Button variant="ghost" busy={busy === "apply"} disabled={!approved.size}
                    onClick={applyPlan}>
                    Create {approved.size} approved {approved.size === 1 ? "entry" : "entries"}
                  </Button>
                )}
                {w.emailNoteUrl ? (
                  <span className="muted" style={{ fontSize: "12.5px" }}>
                    Saved to Notion —{" "}
                    <a href={w.emailNoteUrl} target="_blank" rel="noreferrer"
                       style={{ color: "var(--teal-700)" }}>open the note</a>
                  </span>
                ) : !w.emailNote && (
                  <Button variant="ghost" busy={busy === "emailnote"}
                    onClick={() => ts.previewEmailNote(msg)}>
                    Save email to Notion
                  </Button>
                )}
              </div>

              {/* Preview of the exact note before it is written — everything
                  visible, the text properties editable. */}
              {w.emailNote && !w.emailNoteUrl && (
                <div style={{ marginTop: 12, padding: "14px 16px",
                              background: "var(--paper-050)",
                              border: "1px solid var(--paper-200)",
                              borderRadius: "var(--radius)" }}>
                  <span className="microlabel">NOTE TO BE CREATED — REVIEW AND EDIT</span>
                  <div style={{ display: "grid", gridTemplateColumns: "150px 1fr",
                                gap: "6px 12px", marginTop: 10 }}>
                    {Object.entries(w.emailNote.editable || {}).map(([k, v]) => (
                      <React.Fragment key={k}>
                        <span className="microlabel" style={{ paddingTop: 6 }}>{k}</span>
                        {k === "Thoughts / Considerations" ? (
                          <textarea rows={3}
                            value={w.emailNoteEdits?.[k] ?? v}
                            onChange={(e) => ts.setEmailNoteEdit(msg.id, k, e.target.value)}
                            style={{ fontSize: "12.5px", padding: "6px 8px",
                                     background: "var(--paper-000)",
                                     border: "1px solid var(--paper-200)",
                                     borderRadius: 4, color: "var(--ink-700)",
                                     fontFamily: "inherit", lineHeight: 1.5 }} />
                        ) : (
                          <input value={w.emailNoteEdits?.[k] ?? v}
                            onChange={(e) => ts.setEmailNoteEdit(msg.id, k, e.target.value)}
                            style={{ fontSize: "12.5px", padding: "5px 8px",
                                     background: "var(--paper-000)",
                                     border: "1px solid var(--paper-200)",
                                     borderRadius: 4, color: "var(--ink-700)" }} />
                        )}
                      </React.Fragment>
                    ))}
                    {(w.emailNote.fixed || []).map(([k, v]) => (
                      <React.Fragment key={k}>
                        <span className="microlabel">{k}</span>
                        <span style={{ fontSize: "12.5px", color: "var(--stone-600)" }}>{v}</span>
                      </React.Fragment>
                    ))}
                  </div>
                  <div className="row" style={{ marginTop: 12 }}>
                    <Button variant="dark" busy={busy === "emailnote"}
                      onClick={() => ts.saveEmailNote(msg)}>
                      Create the note
                    </Button>
                    <Button variant="ghost" onClick={() => ts.cancelEmailNote(msg.id)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </Step>

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

            <Step n={3} label="REPLY · DRAFT ONLY" state={options ? "done" : "current"} last>
              {!options && (
                <>
                  <Button variant="ghost" busy={busy === "drafts"} onClick={genDrafts}>
                    Generate reply options
                  </Button>
                  {!screen && (
                    <span className="muted" style={{ fontSize: "12.5px", marginLeft: 10 }}>
                      Works without the preference screen — run it first and the reply
                      will reflect the verdict.
                    </span>
                  )}
                </>
              )}
              {options && (
                <>
                  <div className="row" style={{ marginBottom: 10 }}>
                    {options.map((o, i) => (
                      <Button key={i} variant={i === chosen ? "primary" : "ghost"}
                        style={{ fontSize: "12.5px", padding: "7px 12px" }}
                        onClick={() => ts.setWork(msg.id, { chosen: i, draftBody: o.body })}>{o.label}</Button>
                    ))}
                  </div>
                  <textarea value={draftBody}
                    onChange={(e) => ts.setWork(msg.id, { draftBody: e.target.value })}
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
