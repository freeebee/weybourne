import React from "react";
import { useNavigate } from "react-router-dom";
import { get, getRetry } from "../api.js";
import * as live from "../liveStore.js";
import {
  Banner, Button, Card, ErrorNote, Field, FilePick, Mascot, PageHeader,
  SectionHead, fmtDate, fmtTime, inputStyle,
} from "../ui.jsx";

export default function Prep() {
  const [tab, setTab] = React.useState("calendar");   // calendar | name | deck
  const [wantBrief, setWantBrief] = React.useState(true);
  const [wantScreen, setWantScreen] = React.useState(true);
  const [events, setEvents] = React.useState([]);
  const [eventIdx, setEventIdx] = React.useState(0);
  const [typedName, setTypedName] = React.useState("");
  const [typedCompany, setTypedCompany] = React.useState("");
  const [deck, setDeck] = React.useState(null);
  const [deckName, setDeckName] = React.useState("");
  const [jobs, setJobs] = React.useState([]);          // all prep jobs, newest first
  const [library, setLibrary] = React.useState([]);    // saved preps on disk
  const [viewing, setViewing] = React.useState(null);  // {name, result}
  const [error, setError] = React.useState(null);
  const [showFull, setShowFull] = React.useState(false);
  const [justDone, setJustDone] = React.useState(null);   // {label, entity, email, company, vehicle}
  const [minimized, setMinimized] = React.useState({});   // {screen: bool, brief: bool}
  const pollRef = React.useRef(null);
  const doneSeen = React.useRef(new Set());

  // Retrying fetches: mounting this page during a backend reload (a few
  // seconds after any code change) must not blank the calendar and library.
  const refreshLibrary = React.useCallback(() => {
    getRetry("/api/preps").then((d) => setLibrary(d.preps)).catch(() => {});
  }, []);

  React.useEffect(() => {
    getRetry("/api/calendar").then((d) => setEvents(d.events)).catch(() => {});
    refreshLibrary();
  }, [refreshLibrary]);

  // One poller for ALL prep jobs — multiple runs go in parallel server-side.
  React.useEffect(() => {
    const poll = async () => {
      try {
        const { jobs: js } = await get("/api/jobs?kind=prep");
        setJobs(js);
        for (const j of js) {
          if (j.status === "done" && !doneSeen.current.has(j.id)) {
            doneSeen.current.add(j.id);
            const full = await get(`/api/jobs/${j.id}`);
            setViewing({ name: full.label, result: full.result });
            setJustDone({
              label: full.label,
              entity: full.result?.entity || "",
              email: full.result?.email || "",
              company: full.result?.company || "",
              vehicle: full.result?.briefing?.vehicle || "",
            });
            setMinimized({});
            refreshLibrary();
          }
          if (j.status === "error" && !doneSeen.current.has(j.id)) {
            doneSeen.current.add(j.id);
            const full = await get(`/api/jobs/${j.id}`);
            setError(`${j.label}: ${full.error}`);
          }
        }
      } catch { /* transient */ }
      pollRef.current = setTimeout(poll, 1500);
    };
    poll();
    return () => clearTimeout(pollRef.current);
  }, [refreshLibrary]);

  async function cancel(id) {
    try { await fetch(`/api/jobs/${id}/cancel`, { method: "POST" }); }
    catch { /* finishing anyway */ }
  }

  async function prepare(fields, file) {
    setError(null);
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
    } catch (e) { setError(e.message); }
  }

  async function openSaved(id) {
    try {
      const d = await get(`/api/preps/${id}`);
      setViewing({ name: d.name, result: d.result });
      setShowFull(false);
    } catch (e) { setError(e.message); }
  }

  async function deleteSaved(id) {
    if (!window.confirm("Delete this saved prep?")) return;
    try {
      await fetch(`/api/preps/${id}`, { method: "DELETE" });
      refreshLibrary();
    } catch (e) { setError(e.message); }
  }

  const ev = events[eventIdx];
  const nothingPicked = !wantBrief && !wantScreen;
  const running = jobs.filter((j) => j.status === "running");

  // Key questions — starred in the brief or added by hand, persisted per
  // entity so the note taker can preload them for the same meeting.
  const entityName = viewing?.result?.briefing?.entity || viewing?.result?.entity || "";
  const [keyQs, setKeyQs] = React.useState([]);
  React.useEffect(() => {
    if (!entityName) { setKeyQs([]); return; }
    get(`/api/questions?entity=${encodeURIComponent(entityName)}`)
      .then((d) => setKeyQs(d.questions || [])).catch(() => setKeyQs([]));
  }, [entityName]);
  const persistKeyQs = (next) => {
    setKeyQs(next);
    // Aliases let the note taker find these questions from the calendar's
    // counterparty name or email, which rarely match the entity verbatim.
    const aliases = [viewing?.result?.entity, viewing?.result?.company,
                     viewing?.result?.email, viewing?.name].filter(Boolean);
    fetch("/api/questions", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity: entityName, questions: next, aliases }),
    }).catch(() => {});
  };
  const toggleKey = (q) => {
    const exists = keyQs.some((k) => k.q === q.q);
    persistKeyQs(exists ? keyQs.filter((k) => k.q !== q.q)
      : [...keyQs, { q: q.q, src: q.src || "" }]);
  };
  const addKey = (text) => {
    const t = text.trim();
    if (t && !keyQs.some((k) => k.q === t)) persistKeyQs([...keyQs, { q: t, src: "added by you" }]);
  };

  // The manager thread for this entity — history line + note-taker handoff.
  const nav = useNavigate();
  const [thread, setThread] = React.useState(null);
  React.useEffect(() => {
    if (!entityName) { setThread(null); return; }
    get(`/api/managers/resolve?q=${encodeURIComponent(entityName)}`)
      .then((d) => setThread(d?.entity ? d : null)).catch(() => setThread(null));
  }, [entityName]);
  const threadLine = React.useMemo(() => {
    if (!thread) return "";
    const notes = (thread.history || []).filter((h) => h.kind === "note").length;
    const preps = (thread.history || []).filter((h) => h.kind === "prep");
    return [
      preps.length > 1 ? `prep ${preps[preps.length - 1].at}` : null,
      notes ? `${notes} note${notes === 1 ? "" : "s"}` : null,
      thread.company_id ? "Notion linked" : null,
    ].filter(Boolean).join(" · ");
  }, [thread]);
  async function openInNoteTaker() {
    const name = entityName || viewing?.name;
    if (name) {
      live.set({ who: viewing?.result?.entity || name });
      await live.resolveManager(name);
    }
    nav("/live");
  }

  return (
    <div className="fade-in">
      <PageHeader eyebrow="PREPARATION · BRIEFING" title="Meeting prep"
        actions={
          <>
            <Button variant={tab === "calendar" ? "dark" : "ghost"} onClick={() => setTab("calendar")}>From my calendar</Button>
            <Button variant={tab === "name" ? "dark" : "ghost"} onClick={() => setTab("name")}>By name</Button>
            <Button variant={tab === "deck" ? "dark" : "ghost"} onClick={() => setTab("deck")}>From a deck</Button>
          </>
        }>
        Who you're meeting, what they do, our history with them, and what to probe.
        Runs in the background — leave and come back.
      </PageHeader>

      {/* Outputs — up top so there's no scrolling to find them. */}
      <div className="row" style={{ margin: "0 0 18px", gap: 22,
        borderBottom: "1px solid var(--paper-200)", paddingBottom: 14, flexWrap: "wrap" }}>
        <span className="microlabel">OUTPUTS</span>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: "13.5px" }}>
          <input type="checkbox" checked={wantBrief} onChange={(e) => setWantBrief(e.target.checked)} />
          Full DD briefing
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: "13.5px" }}>
          <input type="checkbox" checked={wantScreen} onChange={(e) => setWantScreen(e.target.checked)} />
          Preference screen (Notion CHAO pages)
        </label>
        {nothingPicked && (
          <span style={{ fontSize: "12.5px", color: "var(--caution-600)" }}>
            Pick at least one output.
          </span>
        )}
        <Button style={{ marginLeft: "auto" }}
          disabled={nothingPicked
            || (tab === "calendar" && !ev)
            || (tab === "name" && !typedName)
            || (tab === "deck" && !deck)}
          onClick={() => {
            if (tab === "calendar") prepare({ name: ev.counterparty_name, email: ev.counterparty_email, event: JSON.stringify(ev) }, deck || undefined);
            else if (tab === "name") prepare({ name: typedName, company: typedCompany }, deck || undefined);
            else prepare({ name: deckName || deck.name.replace(/\.[^.]+$/, "") }, deck);
          }}>
          Prepare
        </Button>
      </div>

      <div className="panes">
        {/* Left pane — source */}
        <div style={{ flex: "1 1 300px", maxWidth: 400, minWidth: "min(100%,280px)" }}>
          {tab === "calendar" && (
            <>
              <SectionHead label="NEXT TWENTY-ONE DAYS" right={String(events.length)} />
              <div style={{ maxHeight: 480, overflowY: "auto",
                            border: "1px solid var(--paper-200)", borderRadius: "var(--radius)" }}>
              {events.map((e, i) => (
                <div key={i} onClick={() => setEventIdx(i)} className="rrow click" style={{
                  display: "grid", gridTemplateColumns: "58px minmax(0,1fr)", gap: 12,
                  padding: "14px", cursor: "pointer",
                  background: i === eventIdx ? "var(--paper-000)" : "transparent",
                  borderLeft: i === eventIdx ? "2px solid var(--teal-500)" : "2px solid transparent",
                }}>
                  <span className="mono" style={{ fontSize: 11, color: "var(--stone-500)", lineHeight: 1.5 }}>
                    {fmtDate(e.start)}<br />{fmtTime(e.start)}
                  </span>
                  <span>
                    <span style={{ fontSize: "14.5px", color: "var(--ink-800)", display: "block" }}>{e.subject}</span>
                    <span style={{ fontSize: "12.5px", color: "var(--stone-500)" }}>
                      {e.counterparty_name}{e.is_online ? " · online" : e.location ? ` · ${e.location}` : ""}
                    </span>
                  </span>
                </div>
              ))}
              </div>
              <Field label="DECK OR TEARSHEET (OPTIONAL, PDF)" style={{ marginTop: 12 }}
                hint="Attached to the selected meeting's briefing.">
                <FilePick file={deck} onChange={setDeck} accept=".pdf" label="Choose PDF" />
              </Field>
            </>
          )}
          {tab === "name" && (
            <>
              <Field label="MANAGER OR FIRM NAME">
                <input value={typedName} onChange={(e) => setTypedName(e.target.value)}
                  placeholder="e.g. Old Well Labs" style={inputStyle} />
              </Field>
              <Field label="COMPANY (OPTIONAL)">
                <input value={typedCompany} onChange={(e) => setTypedCompany(e.target.value)} style={inputStyle} />
              </Field>
            </>
          )}
          {tab === "deck" && (
            <>
              <Field label="DECK OR TEARSHEET (PDF)">
                <FilePick file={deck} onChange={setDeck} accept=".pdf" label="Choose PDF" />
              </Field>
              <Field label="COUNTERPARTY NAME (OPTIONAL)">
                <input value={deckName} onChange={(e) => setDeckName(e.target.value)} style={inputStyle} />
              </Field>
            </>
          )}

        </div>

        {/* Right pane — running jobs / result / library */}
        <div style={{ flex: "2 1 480px", minWidth: "min(100%,320px)" }}>
          {running.map((j) => (
            <Card key={j.id} style={{ padding: "18px 20px", marginBottom: 14 }}>
              <div className="spread" style={{ marginBottom: 12 }}>
                <span className="microlabel">RUNNING · {j.label.toUpperCase()}</span>
                <span className="mono" style={{ fontSize: 11, color: "var(--teal-700)" }}>
                  {j.elapsed}S ELAPSED
                  {j.eta > 0 && (j.eta - j.elapsed > 0
                    ? ` · ~${j.eta - j.elapsed}S LEFT` : " · OVERRUNNING")}
                </span>
              </div>
              <div style={{ display: "flex", gap: 18, alignItems: "flex-start" }}>
                <Mascot state="crunching" width={66} />
                <div style={{ flex: 1 }}>
                  {j.stages.map((st, i) => {
                    const isLast = i === j.stages.length - 1;
                    return (
                      <div key={i} style={{ display: "flex", gap: 9, alignItems: "baseline",
                        padding: "3px 0", fontSize: "13.5px",
                        color: isLast ? "var(--ink-800)" : "var(--stone-500)" }}>
                        <span className="mono" style={{ color: isLast ? "var(--teal-600)" : "var(--positive-600)" }}>
                          {isLast ? "›" : "✓"}
                        </span>
                        <span>{st.label}{st.detail && <span className="muted"> — {st.detail}</span>}</span>
                      </div>
                    );
                  })}
                  <div style={{ height: 2, background: "var(--paper-200)", marginTop: 12, borderRadius: 1 }}>
                    <div style={{ height: 2, background: "var(--teal-500)", transition: "width 1s linear",
                      width: `${Math.min(97, j.eta > 0 ? (j.elapsed / j.eta) * 100 : 30)}%` }} />
                  </div>
                </div>
                <Button variant="ghost" onClick={() => cancel(j.id)}>Cancel</Button>
              </div>
            </Card>
          ))}
          {running.length > 0 && (
            <p className="muted" style={{ fontSize: "12.5px", margin: "0 0 16px" }}>
              Runs in the background — start another prep, or leave and come back.
            </p>
          )}
          <ErrorNote error={error} />

          {/* Completion banner — the prep is done, here's exactly what for. */}
          {justDone && (
            <Card accent="teal" style={{ marginBottom: 16, padding: "16px 20px" }}>
              <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                <Mascot state="celebrating" width={58} />
                <div style={{ flex: 1 }}>
                  <span className="microlabel" style={{ color: "var(--positive-600)" }}>
                    MEETING PREP DONE
                  </span>
                  <div style={{ font: "400 17px/1.4 var(--serif)", color: "var(--ink-800)" }}>
                    {justDone.entity}
                    {justDone.vehicle ? ` · ${justDone.vehicle}` : ""}
                    {justDone.company && justDone.company !== justDone.entity
                      ? ` · ${justDone.company}` : ""}
                  </div>
                  {justDone.email && (
                    <span className="mono" style={{ fontSize: 11, color: "var(--stone-500)" }}>
                      {justDone.email}
                    </span>
                  )}
                </div>
                <Button variant="dark" onClick={openInNoteTaker}>Open in note taker</Button>
                <button onClick={() => setJustDone(null)} title="Dismiss" style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: "var(--stone-400)", fontFamily: "var(--mono)", fontSize: 14 }}>×</button>
              </div>
            </Card>
          )}

          {/* Group header — the meeting these outputs belong to. */}
          {viewing?.result && (viewing.result.screen || viewing.result.briefing) && (
            <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                          flexWrap: "wrap", margin: "0 0 10px" }}>
              <span className="microlabel">MEETING PREP</span>
              <span style={{ font: "500 18px/1.3 var(--serif)", color: "var(--ink-800)" }}>
                {viewing.result.entity || viewing.name}
              </span>
              {viewing.result.company && viewing.result.company !== viewing.result.entity && (
                <span className="muted" style={{ fontSize: "12.5px" }}>{viewing.result.company}</span>
              )}
              {viewing.result.email && (
                <span className="mono" style={{ fontSize: 10.5, color: "var(--stone-400)" }}>
                  {viewing.result.email}
                </span>
              )}
              {threadLine && (
                <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".08em",
                                                color: "var(--brass-700)" }}>
                  {threadLine.toUpperCase()}
                </span>
              )}
              <Button variant="ghost" onClick={openInNoteTaker}
                style={{ marginLeft: "auto" }}>
                Open in note taker
              </Button>
            </div>
          )}

          {viewing?.result?.screen && (
            minimized.screen ? (
              <MinimizedBar label={`PREFERENCE SCREEN · ${(viewing.result.entity || viewing.name || "").toUpperCase()} · ${viewing.result.screen.overall_fit.toUpperCase()}`}
                onExpand={() => setMinimized((m) => ({ ...m, screen: false }))} />
            ) : (
              <ScreenView screen={viewing.result.screen}
                entityName={viewing.result.entity || viewing.name || ""}
                onMinimize={() => setMinimized((m) => ({ ...m, screen: true }))} />
            )
          )}

          {viewing?.result?.briefing && (
            minimized.brief ? (
              <MinimizedBar style={{ marginTop: viewing?.result?.screen ? 12 : 0 }}
                label={`BRIEF · ${(viewing.result.briefing.entity || viewing.name || "").toUpperCase()}`}
                onExpand={() => setMinimized((m) => ({ ...m, brief: false }))} />
            ) : (
            <Card accent="brass" style={{ padding: "20px 22px 26px",
                                          marginTop: viewing?.result?.screen ? 20 : 0 }}>
              <div className="spread" style={{ marginBottom: 12 }}>
                <span className="microlabel">
                  BRIEF · {(viewing.result.briefing.entity || viewing.name || "").toUpperCase()}
                </span>
                <span className="row" style={{ gap: 12 }}>
                  <span className="mono" style={{ fontSize: 10.5, color: "var(--stone-400)" }}>
                    {viewing.result.briefing.meeting_details || ""}
                  </span>
                  <MiniBtn onClick={() => setMinimized((m) => ({ ...m, brief: true }))}>
                    MINIMIZE
                  </MiniBtn>
                </span>
              </div>
              <div style={{ font: "400 26px/1.25 var(--serif)", color: "var(--ink-800)", marginBottom: 10 }}>
                {viewing.result.briefing.descriptor}
              </div>
              <p style={{ font: "400 16.5px/1.65 var(--serif)", color: "var(--ink-700)",
                          maxWidth: "64ch", margin: "0 0 16px" }}>
                {viewing.result.briefing.relationship}
                {viewing.result.briefing.vehicle ? ` · ${viewing.result.briefing.vehicle}` : ""}
              </p>
              <SectionHead label="WHERE WE LEFT IT · MEETING HISTORY" />
              {(viewing.result.briefing.meetings || []).length ? (
                viewing.result.briefing.meetings.slice(0, 3).map((m, i) => (
                  <div key={i} className="rrow">
                    <div className="spread">
                      <b style={{ fontSize: "14px" }}>{m.title}</b>
                      <span className="mono" style={{ fontSize: 11, color: "var(--stone-400)" }}>{m.date}</span>
                    </div>
                    <p style={{ fontSize: "13.5px", lineHeight: 1.55, margin: "4px 0 0" }}>
                      {(m.summary || "").slice(0, 240)}{(m.summary || "").length > 240 ? "…" : ""}
                    </p>
                  </div>
                ))
              ) : (
                <p style={{ fontSize: "13.5px", lineHeight: 1.55 }}>
                  {viewing.result.briefing.no_meetings_text || "No qualifying meetings on record."}
                </p>
              )}
              <SectionHead label="BACKGROUND IN BRIEF" style={{ marginTop: 16 }} />
              <p style={{ fontSize: "13.5px", lineHeight: 1.6, maxWidth: "70ch" }}>
                {((viewing.result.briefing.manager_bg_md || viewing.result.briefing.landscape_md || "")
                  .replace(/[#*]/g, "").split("\n").map((x) => x.replace(/^- /, "").trim())
                  .filter(Boolean).join(" ")).slice(0, 420)}…
              </p>
              <div className="row" style={{ marginTop: 16 }}>
                <Button onClick={() => setShowFull(!showFull)}>
                  {showFull ? "Collapse full briefing" : "Open full briefing"}
                </Button>
              </div>
            </Card>
            )
          )}
          {viewing?.result?.briefing && !minimized.brief && showFull &&
            <BriefingView data={viewing.result.briefing}
              keyQs={keyQs} onToggleKey={toggleKey} onAddKey={addKey} />}

          {/* Library — every completed prep is saved automatically. */}
          <div style={{ marginTop: 28 }}>
            <SectionHead label="LIBRARY · SAVED PREPS" right={String(library.length)} />
            {library.length === 0 && (
              <p className="muted small">Completed preps are saved here automatically.</p>
            )}
            {library.map((p) => (
              <div key={p.id} className="rrow click" onClick={() => openSaved(p.id)}
                style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto auto",
                         gap: 14, alignItems: "baseline", padding: "12px 8px", cursor: "pointer" }}>
                <span>
                  <b style={{ fontSize: "14px" }}>{p.name}</b>
                  <span className="mono" style={{ fontSize: 10, color: "var(--stone-400)", marginLeft: 10 }}>
                    {(p.outputs || []).join(" + ").toUpperCase()}
                  </span>
                </span>
                <span className="mono" style={{ fontSize: 10.5, color: "var(--stone-400)" }}>{p.created}</span>
                <button onClick={(e) => { e.stopPropagation(); deleteSaved(p.id); }}
                  title="Delete" style={{ background: "none", border: "none", cursor: "pointer",
                    color: "var(--critical-600)", fontFamily: "var(--mono)", fontSize: 12 }}>×</button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function MiniBtn({ onClick, children }) {
  return (
    <button onClick={onClick} style={{
      background: "none", border: "1px solid var(--paper-200)", borderRadius: 4,
      cursor: "pointer", padding: "2px 8px", color: "var(--teal-700)",
      fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".1em" }}>
      {children}
    </button>
  );
}

function MinimizedBar({ label, onExpand, style }) {
  return (
    <div onClick={onExpand} className="click" style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: "10px 16px", background: "var(--paper-000)", cursor: "pointer",
      border: "1px solid var(--paper-200)", borderRadius: "var(--radius)",
      marginBottom: 12, ...style }}>
      <span className="microlabel">{label}</span>
      <MiniBtn onClick={onExpand}>EXPAND</MiniBtn>
    </div>
  );
}

function ScreenView({ screen, onMinimize, entityName }) {
  const color = { Fit: "var(--positive-600)", Partial: "var(--caution-600)",
    "Non-fit": "var(--critical-600)", Unclear: "var(--stone-500)" }[screen.overall_fit];
  return (
    <Card accent="teal" style={{ padding: "20px 22px" }}>
      <div className="spread" style={{ marginBottom: 8 }}>
        <span className="microlabel">
          PREFERENCE SCREEN · CHAO{entityName ? ` · ${entityName.toUpperCase()}` : ""}
        </span>
        <span className="row" style={{ gap: 12 }}>
          <span className="mono" style={{ fontSize: 11, letterSpacing: ".1em", color }}>
            {screen.overall_fit.toUpperCase()} · {screen.sleeve.toUpperCase()}
          </span>
          {onMinimize && <MiniBtn onClick={onMinimize}>MINIMIZE</MiniBtn>}
        </span>
      </div>
      <p style={{ fontSize: 14.5, lineHeight: 1.6, margin: "0 0 16px", maxWidth: "72ch" }}>
        {screen.summary}
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))",
                    gap: 24 }}>
        <div>
          <span className="microlabel" style={{ color: "var(--positive-600)" }}>FITS</span>
          {(screen.fit_points.length ? screen.fit_points : ["—"]).map((x, i) => (
            <div key={i} style={{ display: "flex", gap: 9, padding: "6px 0",
                                  borderBottom: "1px solid var(--paper-200)" }}>
              <span className="mono" style={{ fontSize: 10, color: "var(--positive-600)",
                                              paddingTop: 3, flex: "none" }}>
                {String(i + 1).padStart(2, "0")}
              </span>
              <span style={{ fontSize: "13.5px", lineHeight: 1.55 }}>{x}</span>
            </div>
          ))}
        </div>
        <div>
          <span className="microlabel" style={{ color: "var(--critical-600)" }}>NON-FITS</span>
          {(screen.non_fit_points.length ? screen.non_fit_points : ["—"]).map((x, i) => (
            <div key={i} style={{ display: "flex", gap: 9, padding: "6px 0",
                                  borderBottom: "1px solid var(--paper-200)" }}>
              <span className="mono" style={{ fontSize: 10, color: "var(--critical-600)",
                                              paddingTop: 3, flex: "none" }}>
                {String(i + 1).padStart(2, "0")}
              </span>
              <span style={{ fontSize: "13.5px", lineHeight: 1.55 }}>{x}</span>
            </div>
          ))}
        </div>
      </div>
      {screen.open_questions?.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <span className="microlabel">OPEN QUESTIONS</span>
          {screen.open_questions.map((q, i) => (
            <div key={i} style={{ fontSize: "13.5px", lineHeight: 1.55, padding: "4px 0" }}>{q}</div>
          ))}
        </div>
      )}
    </Card>
  );
}

function BriefingView({ data, keyQs = [], onToggleKey, onAddKey }) {
  const keySet = new Set(keyQs.map((k) => k.q));
  return (
    <div style={{ marginTop: 20 }}>
      <Section n="1" title="Historical meeting context">
        {data.meetings?.length
          ? data.meetings.map((m, i) => (
              <div key={i} className="rrow">
                <div className="spread"><b style={{ fontSize: "14.5px" }}>{m.title}</b>
                  <span className="mono" style={{ fontSize: 11, color: "var(--stone-400)" }}>{m.date}</span></div>
                <div className="mono" style={{ fontSize: 10.5, color: "var(--stone-400)" }}>{m.format} · {m.attendees}</div>
                <p style={{ fontSize: "13.5px", margin: "6px 0 0" }}>{m.summary}</p>
              </div>
            ))
          : <p style={{ fontSize: "13.5px" }}>{data.no_meetings_text || "No qualifying meetings on record."}</p>}
        {data.other_mentions?.map((mn, i) => (
          <div key={i} className="rrow" style={{ color: "var(--stone-600)", fontSize: "13px" }}>
            <span className="mono" style={{ fontSize: 10, color: "var(--stone-400)" }}>
              {mn.source} · {mn.date} · {mn.context}</span>
            <div>{mn.text}</div>
          </div>
        ))}
      </Section>
      <Section n="2" title="Background research">
        <SubHead>Sector &amp; market landscape</SubHead><Markdown text={data.landscape_md} />
        <SubHead>Manager background</SubHead><Markdown text={data.manager_bg_md} />
        <SubHead>Potential red flags</SubHead><Markdown text={data.red_flags_md} />
      </Section>
      <Section n="3" title="Strategy"><Markdown text={data.strategy_md} /></Section>
      <Section n="4" title="Questions for the manager">
        {/* The key list — starred below or written yourself; preloaded into
            the note taker when you pick this meeting from the calendar. */}
        <div style={{ background: "var(--brass-100)", border: "1px solid var(--paper-200)",
                      borderRadius: "var(--radius)", padding: "12px 16px", marginBottom: 16 }}>
          <span className="microlabel" style={{ color: "var(--brass-700)" }}>
            KEY QUESTIONS · SAVED FOR THIS MEETING ({keyQs.length})
          </span>
          {keyQs.length === 0 && (
            <p className="muted" style={{ fontSize: "12.5px", margin: "6px 0 0" }}>
              Tick a question below, or write your own — the list carries into
              the note taker for this meeting.
            </p>
          )}
          {keyQs.map((k, i) => (
            <div key={i} style={{ display: "flex", gap: 10, alignItems: "baseline",
                                  padding: "5px 0", fontSize: "13.5px" }}>
              <span className="mono" style={{ fontSize: 10, color: "var(--brass-700)" }}>
                {String(i + 1).padStart(2, "0")}
              </span>
              <span style={{ flex: 1 }}>{k.q}</span>
              <button onClick={() => onToggleKey?.(k)} title="Remove from key questions"
                style={{ background: "none", border: "none", cursor: "pointer",
                         color: "var(--stone-400)", fontFamily: "var(--mono)", fontSize: 12 }}>×</button>
            </div>
          ))}
          {onAddKey && <AddQuestion onAdd={onAddKey} />}
        </div>
        <SubHead>A. Strategy &amp; direction</SubHead>
        <QList items={data.questions_a || []} keySet={keySet} onToggle={onToggleKey} />
        <SubHead style={{ marginTop: 14 }}>B. Manager-level &amp; structural</SubHead>
        <QList items={data.questions_b || []} keySet={keySet} onToggle={onToggleKey} />
      </Section>
      <Section n="5" title="Deals">
        {!data.is_manager ? (
          <p style={{ fontSize: "13.5px", fontStyle: "italic", color: "var(--stone-500)" }}>
            {data.deals_omit_text || "Omitted: the relationship is not an investment manager or fund."}
          </p>
        ) : (
          <>
            {data.ledger?.length > 0 && (
              <div style={{ overflowX: "auto", marginBottom: 14 }}>
                <table className="wb">
                  <thead><tr>
                    {["Company", "Fund · sector", "Entry", "Cost", "Own.", "MoIC", "IRR", "Business"]
                      .map((h) => <th key={h}>{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {data.ledger.map((r, i) => (
                      <tr key={i} style={r.hot ? { background: "var(--paper-100)",
                        boxShadow: "inset 2px 0 0 var(--brass-500)" } : undefined}>
                        <td>{r.company}</td>
                        <td style={{ fontFamily: "var(--sans)", textAlign: "left" }}>{r.fund_sector}</td>
                        <td>{r.entry}</td><td>{r.cost}</td><td>{r.ownership}</td>
                        <td>{r.moic}</td><td>{r.irr}</td>
                        <td style={{ fontFamily: "var(--sans)", textAlign: "left",
                          color: "var(--stone-600)", fontSize: "12.5px" }}>{r.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {data.deal_cards?.map((c, i) => (
              <Card key={i} style={{ marginBottom: 12 }}>
                <div className="spread"><b>{c.name}</b>
                  <span className="mono" style={{ fontSize: 11, color: "var(--stone-400)" }}>{c.figs}</span></div>
                {[["BUSINESS", c.business], ["WHAT THE MANAGER DID", c.actions],
                  ["LATEST NEWSFLOW", c.newsflow]].map(([k, v]) => (
                  <div key={k} style={{ marginTop: 8 }}>
                    <span className="microlabel">{k}</span>
                    <p style={{ fontSize: "13.5px", margin: "3px 0 0" }}>{v}</p>
                  </div>
                ))}
                {c.questions?.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <span className="microlabel">QUESTIONS</span>
                    <QList items={c.questions} keySet={keySet} onToggle={onToggleKey} />
                  </div>
                )}
                {c.key_flag && (
                  <div style={{ borderLeft: "2px solid var(--brass-500)", background: "var(--brass-100)",
                                padding: "8px 12px", marginTop: 10, fontSize: "13px" }}>
                    <span className="microlabel" style={{ color: "var(--brass-700)" }}>KEY FLAG</span>
                    <div>{c.key_flag}</div>
                  </div>
                )}
              </Card>
            ))}
            {data.standouts_md && (<><SubHead>Standouts</SubHead><Markdown text={data.standouts_md} /></>)}
          </>
        )}
      </Section>
      <Section n="6" title="Sources" last>
        {(data.sources || []).map((s, i) => (
          <div key={i} className="rrow" style={{ fontSize: "13.5px" }}>
            <span className="mono" style={{ fontSize: 10, letterSpacing: ".1em",
              textTransform: "uppercase", color: "var(--stone-400)", marginRight: 12 }}>{s.kind}</span>
            {s.text}
          </div>
        ))}
        <p className="muted" style={{ fontSize: "12.5px", fontStyle: "italic", marginTop: 10 }}>
          Prepared from Notion, Outlook and independent research. Teams chat is never used as a source.
        </p>
      </Section>
    </div>
  );
}

function Section({ n, title, last, children }) {
  return (
    <section style={{ marginBottom: last ? 0 : 28 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    borderBottom: "1px solid var(--ink-800)", paddingBottom: 6, marginBottom: 14 }}>
        <span className="mono" style={{ fontSize: 12, color: "var(--teal-600)" }}>{n}</span>
        <h3 style={{ margin: 0, fontWeight: 500, fontSize: 20 }}>{title}</h3>
      </div>
      {children}
    </section>
  );
}

function SubHead({ children, style }) {
  return <div className="microlabel" style={{ color: "var(--ink-700)", margin: "10px 0 4px", ...style }}>{children}</div>;
}

function QList({ items, keySet, onToggle }) {
  return (
    <ol style={{ margin: 0, padding: 0, listStyle: "none" }}>
      {items.map((q, i) => {
        const isKey = keySet?.has(q.q);
        return (
          <li key={i} className="rrow" style={{ display: "grid",
            gridTemplateColumns: onToggle ? "28px minmax(0,1fr) auto" : "28px minmax(0,1fr)",
            gap: 10, background: isKey ? "var(--brass-100)" : "transparent" }}>
            <span className="mono" style={{ fontSize: 11, color: "var(--brass-500)" }}>
              {String(i + 1).padStart(2, "0")}
            </span>
            <div>
              <div style={{ font: "400 14.5px/1.5 var(--serif)" }}>{q.q}</div>
              <div className="mono" style={{ fontSize: 10, color: "var(--stone-400)", marginTop: 2 }}>→ {q.src}</div>
            </div>
            {onToggle && (
              <button onClick={() => onToggle(q)}
                title={isKey ? "Remove from key questions" : "Mark as a key question"}
                style={{ background: "none", border: "none", cursor: "pointer",
                         color: isKey ? "var(--brass-700)" : "var(--stone-300)",
                         fontSize: 14, lineHeight: 1, padding: "2px 4px" }}>✓</button>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function AddQuestion({ onAdd }) {
  const [text, setText] = React.useState("");
  return (
    <div className="row" style={{ marginTop: 10 }}>
      <input value={text} onChange={(e) => setText(e.target.value)}
        placeholder="write your own question"
        onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) { onAdd(text); setText(""); } }}
        style={{ flex: 1, minWidth: 180, fontSize: "13px", padding: "7px 10px",
                 background: "var(--paper-000)", border: "1px solid var(--paper-200)",
                 borderRadius: 4 }} />
      <Button variant="ghost" disabled={!text.trim()}
        onClick={() => { onAdd(text); setText(""); }}>Add</Button>
    </div>
  );
}

/* Tiny markdown renderer. */
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
  return <div style={{ fontSize: "13.5px", lineHeight: 1.6, margin: "4px 0 12px" }}
    dangerouslySetInnerHTML={{ __html: `<p>${html}</p>` }} />;
}
