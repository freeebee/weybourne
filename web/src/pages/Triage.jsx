import React from "react";
import * as ts from "../triageStore.js";
import {
  Banner, Button, Card, Chip, ErrorNote, Mascot, PageHeader, Spinner, fmtDT,
} from "../ui.jsx";

/* Select/status/multi-select options per DB kind, fetched once per session so
   proposal edits can offer dropdowns instead of free text. */
const OPT_CACHE = {};
async function loadOptions(kind) {
  if (OPT_CACHE[kind]) return OPT_CACHE[kind];
  try {
    const res = await fetch(`/api/notion/options?kind=${kind}`);
    OPT_CACHE[kind] = (await res.json()).options || {};
  } catch { OPT_CACHE[kind] = {}; }
  return OPT_CACHE[kind];
}

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
                      {(inFlight || s.moving?.has(m.id)) && <Spinner size={12} />}
                      <button onClick={(e) => { e.stopPropagation(); ts.toShared(m); }}
                        disabled={s.moving?.has(m.id)}
                        title="Forward to the Investments shared mailbox" style={{
                          background: "none", border: "none", cursor: "pointer",
                          color: "var(--teal-700)", fontFamily: "var(--mono)", fontSize: 12,
                        }}>»</button>
                      <button onClick={(e) => { e.stopPropagation(); ts.deleteMessage(m); }}
                        disabled={s.moving?.has(m.id)}
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
                        {fmtDT(m.received)}
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
  const { screen, options, chosen = 0, draftBody = "", notice, error } = w;
  const busy = Array.isArray(w.busy) ? w.busy : [];
  const isBusy = (k) => busy.includes(k);
  const approved = new Set(w.approved || []);

  // Dropdown options for select/status/multi properties, per proposal kind.
  const [dbOptions, setDbOptions] = React.useState({});
  React.useEffect(() => {
    (result?.proposals || []).forEach((p) => {
      loadOptions(p.kind).then((o) =>
        setDbOptions((prev) => (prev[p.kind] ? prev : { ...prev, [p.kind]: o })));
    });
  }, [result]);

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
          {msg.sender_name} &lt;{msg.sender_email}&gt; · {fmtDT(msg.received)}
        </div>
        <p style={{ fontSize: "14.5px", lineHeight: 1.6, color: "var(--stone-600)",
                    maxWidth: "68ch", margin: 0, whiteSpace: "pre-wrap",
                    maxHeight: 300, overflowY: "auto" }}>
          {msg.body || msg.body_preview}
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
                const drow = result.dedupe?.[p.kind];
                const updated = (w.updatedKinds || []).includes(p.kind);
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
                      gridTemplateColumns: "130px minmax(0,1fr)", gap: "2px 12px", marginTop: 4 }}>
                      {p.properties.map(([k, v]) => {
                        const value = edits[k] ?? v;
                        const raw = p.raw_properties?.[k] || {};
                        const opts = dbOptions[p.kind]?.[k];
                        const isSelect = ("select" in raw || "status" in raw) && opts?.length;
                        const isMulti = "multi_select" in raw && opts?.length;
                        const fieldStyle = { fontSize: "12.5px", padding: "4px 8px",
                                             background: "var(--paper-050)",
                                             border: "1px solid var(--paper-200)",
                                             borderRadius: 4, color: "var(--ink-700)",
                                             width: "100%", fontFamily: "inherit",
                                             lineHeight: 1.5 };
                        return (
                          <React.Fragment key={k}>
                            <span className="microlabel" style={{ paddingTop: editing ? 6 : 0 }}>{k}</span>
                            {!editing ? (
                              <span style={{ fontSize: "12.5px", overflowWrap: "anywhere",
                                whiteSpace: "pre-wrap", minWidth: 0,
                                color: k in edits ? "var(--teal-700)" : "inherit" }}>
                                {value}
                              </span>
                            ) : isSelect ? (
                              <select value={value} style={fieldStyle}
                                onChange={(e) => ts.setProposalEdit(msg.id, p.kind, k, e.target.value)}>
                                {!opts.includes(value) && <option value={value}>{value}</option>}
                                {opts.map((o) => <option key={o} value={o}>{o}</option>)}
                              </select>
                            ) : isMulti ? (
                              <span style={{ minWidth: 0 }}>
                                <textarea rows={1} value={value} style={fieldStyle}
                                  onChange={(e) => ts.setProposalEdit(msg.id, p.kind, k, e.target.value)} />
                                <select value="" style={{ ...fieldStyle, width: "auto", marginTop: 3 }}
                                  onChange={(e) => {
                                    const cur = value ? value.split(",").map((x) => x.trim()) : [];
                                    if (e.target.value && !cur.includes(e.target.value)) {
                                      ts.setProposalEdit(msg.id, p.kind, k,
                                        [...cur, e.target.value].join(", "));
                                    }
                                  }}>
                                  <option value="">add an option…</option>
                                  {opts.map((o) => <option key={o} value={o}>{o}</option>)}
                                </select>
                              </span>
                            ) : (
                              <textarea value={value} style={fieldStyle}
                                rows={Math.min(6, Math.max(1, Math.ceil((value || "").length / 70)))}
                                onChange={(e) => ts.setProposalEdit(msg.id, p.kind, k, e.target.value)} />
                            )}
                          </React.Fragment>
                        );
                      })}
                    </div>

                    {/* Possible duplicate: side-by-side against the existing
                        record, with merge-or-create as YOUR call. */}
                    {p.needs_review && drow?.existing && (
                      <div style={{ marginLeft: 24, marginTop: 10, padding: "12px 14px",
                                    background: "var(--paper-050)",
                                    border: "1px solid var(--paper-200)",
                                    borderRadius: "var(--radius)" }}>
                        <span className="microlabel" style={{ color: "var(--caution-600)" }}>
                          POSSIBLE DUPLICATE · COMPARE BEFORE CREATING
                        </span>
                        {drow.ai && (
                          <p className="muted" style={{ fontSize: "12px", margin: "5px 0 0",
                                                        fontStyle: "italic" }}>
                            Assessment: {drow.ai.verdict === "same"
                              ? "likely the same" : drow.ai.verdict === "different"
                                ? "likely different" : "unclear"} — {drow.ai.reason}
                          </p>
                        )}
                        <div style={{ display: "grid",
                          gridTemplateColumns: "110px 1fr 1fr", gap: "3px 12px", marginTop: 8 }}>
                          <span />
                          <span className="microlabel" style={{ color: "var(--teal-700)" }}>PROPOSED (NEW)</span>
                          <span className="microlabel">EXISTING · {(drow.match || "").toUpperCase()}</span>
                          {[...new Set([...Object.keys(drow.proposed || {}),
                                        ...Object.keys(drow.existing || {})])].map((k) => (
                            <React.Fragment key={k}>
                              <span className="microlabel">{k}</span>
                              <span style={{ fontSize: "12.5px" }}>{drow.proposed?.[k] || "—"}</span>
                              <span style={{ fontSize: "12.5px", color: "var(--stone-600)" }}>
                                {drow.existing?.[k] || "—"}
                              </span>
                            </React.Fragment>
                          ))}
                        </div>
                        <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
                          {updated ? (
                            <span className="muted" style={{ fontSize: "12.5px" }}>
                              Existing entry updated with the new details.
                            </span>
                          ) : (
                            <Button variant="ghost" busy={isBusy(`update-${p.kind}`)}
                              onClick={() => ts.updateExisting(msg, p)}>
                              Merge into the existing entry
                            </Button>
                          )}
                          <span className="muted" style={{ fontSize: "12px" }}>
                            …or tick the box above to create a new entry, or do
                            neither to keep the existing one unchanged.
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
              <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
                {result.proposals?.length > 0 && (
                  <Button variant="ghost" busy={isBusy("apply")} disabled={!approved.size}
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
                  <Button variant="ghost" busy={isBusy("emailnote")}
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
                  <span className="microlabel">NOTE TO BE CREATED</span>
                  <div style={{ display: "grid", gridTemplateColumns: "150px 1fr",
                                gap: "6px 12px", marginTop: 10 }}>
                    {Object.entries(w.emailNote.editable || {}).map(([k, v]) => {
                      const editing = !!w.emailNoteEditing?.[k];
                      const value = w.emailNoteEdits?.[k] ?? v;
                      const inputStyle = { fontSize: "12.5px", padding: "5px 8px",
                                           background: "var(--paper-000)",
                                           border: "1px solid var(--paper-200)",
                                           borderRadius: 4, color: "var(--ink-700)",
                                           fontFamily: "inherit", lineHeight: 1.5,
                                           flex: 1 };
                      return (
                        <React.Fragment key={k}>
                          <span className="microlabel" style={{ paddingTop: 3 }}>{k}</span>
                          <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                            {editing ? (
                              k === "Thoughts / Considerations"
                                ? <textarea rows={3} value={value} style={inputStyle}
                                    onChange={(e) => ts.setEmailNoteEdit(msg.id, k, e.target.value)} />
                                : <input value={value} style={inputStyle}
                                    onChange={(e) => ts.setEmailNoteEdit(msg.id, k, e.target.value)} />
                            ) : (
                              <span style={{ fontSize: "12.5px", flex: 1,
                                color: k in (w.emailNoteEdits || {}) ? "var(--teal-700)" : "inherit" }}>
                                {value}
                              </span>
                            )}
                            <button onClick={() => ts.toggleEmailNoteFieldEdit(msg.id, k)}
                              style={{ background: "none", border: "none", cursor: "pointer",
                                       color: "var(--teal-700)", fontFamily: "var(--mono)",
                                       fontSize: 10, letterSpacing: ".1em", paddingTop: 3 }}>
                              {editing ? "DONE" : "EDIT"}
                            </button>
                          </div>
                        </React.Fragment>
                      );
                    })}
                    {(w.emailNote.fixed || []).map(([k, v]) => (
                      <React.Fragment key={k}>
                        <span className="microlabel">{k}</span>
                        <span style={{ fontSize: "12.5px", color: "var(--stone-600)" }}>{v}</span>
                      </React.Fragment>
                    ))}
                  </div>
                  <div className="row" style={{ marginTop: 12 }}>
                    <Button variant="dark" busy={isBusy("emailnote")}
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

            <Step n={2} label="REPLY · DRAFT ONLY"
              state={options ? "done" : isBusy("drafts") ? "current" : "current"}
              right={isBusy("drafts") && <span style={{ color: "var(--teal-700)" }}>DRAFTING…</span>}>
              <div className="row" style={{ marginBottom: options ? 10 : 0, flexWrap: "wrap" }}>
                {!options && !isBusy("drafts") && (
                  <Button variant="ghost" onClick={genDrafts}>Generate reply options</Button>
                )}
                {isBusy("drafts") && !options && (
                  <span className="muted" style={{ fontSize: "12.5px" }}>
                    Drafting automatically from the triage…
                  </span>
                )}
                <label className="microlabel" style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  MEETING SLOTS
                  <select value={w.slotMinutes || 30}
                    onChange={(e) => ts.setWork(msg.id, { slotMinutes: +e.target.value })}
                    style={{ fontSize: "12px" }}>
                    <option value={30}>30 min</option>
                    <option value={45}>45 min</option>
                    <option value={60}>1 hour</option>
                  </select>
                </label>
                {options && (
                  <Button variant="ghost" busy={isBusy("drafts")} onClick={genDrafts}>
                    Regenerate
                  </Button>
                )}
                <span className="muted" style={{ fontSize: "12px" }}>
                  Offered times are checked against your Outlook calendar.
                </span>
              </div>
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
                    <Button variant="dark" busy={isBusy("save")} onClick={saveDraft}>
                      Save as draft in Outlook
                    </Button>
                    <span className="muted" style={{ fontSize: "12.5px" }}>
                      Replies are drafts only — nothing is ever sent from here.
                    </span>
                  </div>
                </>
              )}
            </Step>

            <Step n={3} label="PREFERENCE SCREEN" state={screen ? "done" : "current"} last
              right={screen && (
                <span style={{ color: verdictColor }}>
                  {screen.overall_fit.toUpperCase()} · {screen.sleeve.toUpperCase()}
                </span>
              )}>
              {!screen && (
                <div className="row" style={{ flexWrap: "wrap" }}>
                  <Button variant="ghost" busy={isBusy("screen")} onClick={runScreen}>
                    Run preference screen
                  </Button>
                  <span style={{ fontSize: "12.5px", color: "var(--teal-700)" }}>
                    Sharpens the reply drafts — they are refreshed with the
                    verdict when the screen lands, even while still drafting.
                  </span>
                </div>
              )}
              {screen && (
                <>
                  <p style={{ fontSize: 14, lineHeight: 1.55, margin: "0 0 10px" }}>{screen.summary}</p>
                  <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))", gap: 16 }}>
                    <div>
                      <span className="microlabel" style={{ color: "var(--positive-600)" }}>FITS</span>
                      {(screen.fit_points.length ? screen.fit_points : ["—"]).map((x, i) => (
                        <div key={i} style={{ fontSize: "13.5px", lineHeight: 1.5,
                                              padding: "4px 0" }}>{x}</div>
                      ))}
                    </div>
                    <div>
                      <span className="microlabel" style={{ color: "var(--critical-600)" }}>NON-FITS</span>
                      {(screen.non_fit_points.length ? screen.non_fit_points : ["—"]).map((x, i) => (
                        <div key={i} style={{ fontSize: "13.5px", lineHeight: 1.5,
                                              padding: "4px 0" }}>{x}</div>
                      ))}
                    </div>
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
