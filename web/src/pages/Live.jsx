/* Live meeting — thin view over liveStore; redesign per handoff. */
import React from "react";
import { del, get } from "../api.js";
import * as live from "../liveStore.js";
import {
  Banner, Button, Card, ErrorNote, Field, Mascot, PageHeader, SearchSelect,
  SectionHead, fmtDate, fmtTime, inputStyle,
} from "../ui.jsx";
import { Markdown } from "./Prep.jsx";

/* Calendar picker — a scrollable list rather than a native select, so past
   meetings are reachable too: scroll up for earlier days (tinted brown),
   TODAY jumps back to the present. Picking fills "who" and loads the
   manager thread, exactly as before. */
function CalendarPick() {
  const [events, setEvents] = React.useState([]);
  const [open, setOpen] = React.useState(false);
  const [picked, setPicked] = React.useState("");
  const wrapRef = React.useRef(null);
  const todayRef = React.useRef(null);

  React.useEffect(() => {
    get("/api/calendar?days=7&back=30")
      .then((d) => setEvents(d.events || [])).catch(() => {});
  }, []);

  React.useEffect(() => {
    if (!open) return;
    const close = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    // Land on today — the past sits above, one scroll away.
    setTimeout(() => todayRef.current?.scrollIntoView({ block: "start" }), 0);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const startOfToday = new Date(); startOfToday.setHours(0, 0, 0, 0);
  const firstCurrentIdx = events.findIndex(
    (e) => new Date(e.start) >= startOfToday);
  const scrollToToday = () =>
    todayRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });

  const pick = async (ev) => {
    setPicked(`${fmtDate(ev.start)} ${fmtTime(ev.start)} · ${ev.subject}`);
    setOpen(false);
    // Only "who" is filled from the calendar — the goal box is yours.
    live.set({ who: ev.counterparty_name || ev.subject });
    // Fuzzy-resolve to the manager thread (prep questions, Notion links).
    const hit = await live.resolveManager(ev.counterparty_name);
    if (!hit && ev.subject) await live.resolveManager(ev.subject);
  };

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <button type="button" onClick={() => setOpen(!open)}
        style={{ ...inputStyle, width: "100%", textAlign: "left",
                 cursor: "pointer", background: "var(--paper-000)",
                 whiteSpace: "nowrap", overflow: "hidden",
                 textOverflow: "ellipsis",
                 color: picked ? "inherit" : "var(--stone-400)" }}>
        {picked || "— pick a meeting —"}
      </button>
      {open && (
        <div style={{ position: "absolute", zIndex: 40, left: 0, right: 0,
                      top: "calc(100% + 4px)", background: "var(--paper-000)",
                      border: "1px solid var(--paper-200)",
                      borderRadius: "var(--radius)",
                      boxShadow: "0 10px 30px rgba(28,36,48,.14)" }}>
          <div className="spread" style={{ padding: "7px 12px",
                        borderBottom: "1px solid var(--paper-200)" }}>
            <span className="mono" style={{ fontSize: 9.5, letterSpacing: ".1em",
                                            color: "var(--stone-400)" }}>
              SCROLL UP FOR PAST MEETINGS
            </span>
            <button type="button" className="mono" onClick={scrollToToday}
              style={{ background: "none", border: "1px solid var(--paper-200)",
                       borderRadius: 4, cursor: "pointer", padding: "2px 8px",
                       fontSize: 9.5, letterSpacing: ".1em",
                       color: "var(--teal-700)" }}>
              TODAY
            </button>
          </div>
          <div style={{ maxHeight: 280, overflowY: "auto" }}>
            {events.length === 0 && (
              <div className="muted" style={{ padding: "10px 12px",
                                              fontSize: "12.5px" }}>
                No calendar entries in the window.
              </div>
            )}
            {events.map((e, i) => {
              const past = i < firstCurrentIdx || firstCurrentIdx === -1;
              return (
                <div key={e.id || i}
                  ref={i === firstCurrentIdx ? todayRef : undefined}
                  onClick={() => pick(e)}
                  style={{ padding: "8px 12px", cursor: "pointer",
                           fontSize: "12.5px", lineHeight: 1.4,
                           borderTop: i === firstCurrentIdx
                             ? "2px solid var(--teal-500)" : "none",
                           color: past ? "var(--brass-700)" : "inherit",
                           background: past ? "var(--brass-100)" : "transparent" }}
                  onMouseEnter={(ev) => { ev.currentTarget.style.background = "var(--paper-100)"; }}
                  onMouseLeave={(ev) => { ev.currentTarget.style.background = past ? "var(--brass-100)" : "transparent"; }}>
                  <span className="mono" style={{ fontSize: 10,
                        letterSpacing: ".06em", marginRight: 8,
                        color: past ? "var(--brass-700)" : "var(--teal-700)" }}>
                    {past ? "PAST · " : ""}{fmtDate(e.start)} {fmtTime(e.start)}
                  </span>
                  {e.subject}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function ManagerPick() {
  const [list, setList] = React.useState([]);
  const [val, setVal] = React.useState("");

  React.useEffect(() => {
    get("/api/managers").then((d) => setList(d.managers || [])).catch(() => {});
  }, []);

  if (!list.length) return null;
  return (
    <select value={val} style={inputStyle} onChange={(e) => {
      setVal(e.target.value);
      if (e.target.value) live.resolveManager(e.target.value);
    }}>
      <option value="">— pick a manager —</option>
      {list.map((m) => (
        <option key={m.entity} value={m.entity}>
          {m.entity}
          {m.questions ? ` · ${m.questions} question${m.questions === 1 ? "" : "s"}` : ""}
          {m.last_prep ? ` · prep ${m.last_prep}` : ""}
        </option>
      ))}
    </select>
  );
}

/* The loaded manager thread, made visible — always know what the session is
   anchored to. */
function ContextChip() {
  const m = live.S.manager;
  if (!m) return null;
  const history = m.history || [];
  const notes = history.filter((h) => h.kind === "note").length;
  const preps = history.filter((h) => h.kind === "prep");
  const bits = [
    `${(m.questions || []).length} key question${(m.questions || []).length === 1 ? "" : "s"}`,
    preps.length ? `prep ${preps[preps.length - 1].at}` : null,
    notes ? `${notes} note${notes === 1 ? "" : "s"}` : null,
    m.company_id ? "Notion: company linked" : m.contact_id ? "Notion: contact linked" : null,
  ].filter(Boolean);
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap",
                  padding: "8px 12px", background: "var(--paper-000)",
                  border: "1px solid var(--paper-200)",
                  borderLeft: "2px solid var(--brass-500)",
                  borderRadius: "var(--radius)", marginBottom: 12 }}>
      <b style={{ fontSize: "13.5px" }}>{m.entity}</b>
      <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".08em",
                                      color: "var(--stone-500)" }}>
        {bits.join(" · ").toUpperCase()}
      </span>
    </div>
  );
}

/* Past sessions, autosaved to disk and filed on Stop — reopen any of them to
   draft the note or pick the meeting back up, or delete for good. */
function TranscriptLibrary() {
  const [list, setList] = React.useState([]);
  const [showAll, setShowAll] = React.useState(false);
  const [confirmDel, setConfirmDel] = React.useState("");

  React.useEffect(() => {
    get("/api/transcripts").then((d) => setList(d.transcripts || [])).catch(() => {});
  }, []);

  const remove = async (id) => {
    try {
      await del(`/api/transcripts/${encodeURIComponent(id)}`);
      setList((l) => l.filter((t) => t.id !== id));
    } catch { /* already gone */ }
    setConfirmDel("");
  };

  if (!list.length) return null;
  return (
    <div style={{ marginBottom: 20 }}>
      <SectionHead label="TRANSCRIPT LIBRARY" right={`${list.length} SAVED`} />
      {(showAll ? list : list.slice(0, 4)).map((t) => (
        <Card key={t.id} style={{ padding: "12px 16px", marginBottom: 8 }}>
          <div className="spread" style={{ alignItems: "center", gap: 12 }}>
            <div style={{ minWidth: 0 }}>
              <b style={{ fontSize: "13.5px" }}>{t.title}</b>
              <span className="mono" style={{ fontSize: 10.5, marginLeft: 10,
                letterSpacing: ".06em", color: "var(--stone-500)" }}>
                {(t.started || t.saved_at)
                  ? `${fmtDate(t.started || t.saved_at)} ${fmtTime(t.started || t.saved_at)} · ` : ""}
                {(t.words || 0).toLocaleString()} WORDS
                {t.has_note && <span style={{ color: "var(--teal-700)" }}> · NOTE DRAFTED</span>}
                {t.unfinished && <span style={{ color: "var(--caution-600)" }}> · UNFINISHED</span>}
              </span>
              {t.goal && (
                <div className="muted" style={{ fontSize: "12.5px", marginTop: 2 }}>{t.goal}</div>
              )}
            </div>
            <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Button variant="ghost" onClick={() => live.loadFromLibrary(t.id)}>Reopen</Button>
              {confirmDel === t.id ? (
                <>
                  <Button variant="ghost" onClick={() => remove(t.id)}>
                    <span style={{ color: "var(--critical-600)" }}>Delete for good</span>
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirmDel("")}>Keep</Button>
                </>
              ) : (
                <button onClick={() => setConfirmDel(t.id)} title="Delete transcript"
                  style={{ background: "none", border: "none", cursor: "pointer",
                           color: "var(--stone-400)", fontSize: 16, lineHeight: 1 }}>
                  ×
                </button>
              )}
            </span>
          </div>
        </Card>
      ))}
      {list.length > 4 && (
        <Button variant="ghost" onClick={() => setShowAll(!showAll)}>
          {showAll ? "Show fewer" : `Show all ${list.length}`}
        </Button>
      )}
    </div>
  );
}

/* Languages the cleaned transcript can be written in, and friendly names for
   the codes whisper detects. */
const OUTPUT_LANGS = ["English", "Chinese", "French", "German", "Spanish", "Italian",
  "Japanese", "Korean", "Portuguese", "Dutch", "Hindi", "Arabic"];

const LANG_NAMES = {
  en: "English", zh: "Chinese", yue: "Cantonese", es: "Spanish", fr: "French",
  de: "German", it: "Italian", ja: "Japanese", ko: "Korean", pt: "Portuguese",
  nl: "Dutch", ru: "Russian", hi: "Hindi", ar: "Arabic", id: "Indonesian",
  ms: "Malay", ta: "Tamil", th: "Thai", vi: "Vietnamese", tr: "Turkish",
  pl: "Polish", sv: "Swedish", da: "Danish", no: "Norwegian", fi: "Finnish",
  he: "Hebrew", uk: "Ukrainian", cs: "Czech", el: "Greek", ro: "Romanian",
  hu: "Hungarian", tl: "Tagalog",
};
const langName = (code) => LANG_NAMES[code] || (code || "").toUpperCase();

/* The cleaned-up live transcript, sentence by sentence — whisper hears any
   language, Haiku tidies it into the chosen output language. The chip shows
   what is being heard and what is being written; click it to change the
   output language mid-meeting. */
function LiveTranscript() {
  const s = live.S;
  const boxRef = React.useRef(null);
  const [pickLang, setPickLang] = React.useState(false);

  React.useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;   // newest line at the bottom
  }, [s.entries.length]);

  if (!s.running && !s.entries.length) return null;
  return (
    <div style={{ marginTop: 14 }}>
      <SectionHead label="LIVE TRANSCRIPT"
        right={s.tidyPending > 0 ? "CLEANING…" : `${s.entries.length} SEGMENTS`} />
      <button className="mono" onClick={() => setPickLang(!pickLang)}
        title="Auto-detected spoken language and the language the transcript is written in — click to change the output"
        style={{ background: "var(--paper-000)", border: "1px solid var(--paper-200)",
                 borderRadius: 4, cursor: "pointer", padding: "4px 10px",
                 fontSize: 10.5, letterSpacing: ".08em", marginBottom: 8,
                 color: "var(--teal-700)" }}>
        HEARING {s.detectedLang ? langName(s.detectedLang).toUpperCase() : "—"}
        {s.detectedLang && s.detectedProb ? ` ${Math.round(s.detectedProb * 100)}%` : ""}
        {" · WRITING "}{s.outputLang.toUpperCase()} ▾
      </button>
      {pickLang && (
        <select value={s.outputLang} style={{ ...inputStyle, marginBottom: 8 }}
          onChange={(e) => { live.set({ outputLang: e.target.value }); setPickLang(false); }}>
          {OUTPUT_LANGS.map((l) => <option key={l} value={l}>{l}</option>)}
        </select>
      )}
      <Card style={{ padding: "12px 14px" }}>
        <div ref={boxRef} style={{ maxHeight: 240, overflowY: "auto" }}>
          {!s.entries.length && (
            <span className="muted" style={{ fontSize: "13px", fontStyle: "italic" }}>
              The cleaned-up transcript appears here as speech comes in.
            </span>
          )}
          {s.entries.slice(-60).map((en, i) => (
            <p key={i} style={{ fontSize: "12.5px", lineHeight: 1.5, margin: "0 0 6px" }}>
              <span className="mono" style={{ fontSize: 9.5, color: "var(--stone-400)",
                                              marginRight: 6 }}>{en.at}</span>
              {en.text}
            </p>
          ))}
          {s.tidyPending > 0 && (
            <span className="mono" style={{ fontSize: 10, color: "var(--teal-600)",
                                            letterSpacing: ".08em" }}>
              CLEANING THE LAST CHUNK…
            </span>
          )}
        </div>
      </Card>
    </div>
  );
}

function fmtElapsed(ms) {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export default function Live() {
  React.useSyncExternalStore(live.subscribe, live.getVersion);
  const s = live.S;

  const [devices, setDevices] = React.useState([]);
  const [rough, setRough] = React.useState("");
  const [paste, setPaste] = React.useState("");
  const [, forceTick] = React.useReducer((x) => x + 1, 0);
  const canvasRef = React.useRef(null);
  const transcriptBoxRef = React.useRef(null);

  React.useEffect(() => {
    live.attachCanvas(canvasRef.current);
    return () => live.attachCanvas(null);
  }, [s.running]);

  React.useEffect(() => {
    if (!s.running) return;
    const t = setInterval(forceTick, 1000);   // elapsed clock in the header
    return () => clearInterval(t);
  }, [s.running]);

  // Recaps are newest-first, so the latest lives at the TOP of the box. When
  // a fresh one lands, jump up to it — unless the user is mid-scroll through
  // the older text (any manual scroll in the last few seconds holds position).
  const lastUserScrollAt = React.useRef(0);
  const progScrollUntil = React.useRef(0);
  React.useEffect(() => {
    const el = transcriptBoxRef.current;
    if (!el) return;
    const idleMs = Date.now() - lastUserScrollAt.current;
    if (idleMs > 4000 || el.scrollTop < 8) {
      progScrollUntil.current = Date.now() + 900;   // our own smooth-scroll events
      el.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [s.batches.length]);

  React.useEffect(() => {
    navigator.mediaDevices?.enumerateDevices?.().then((ds) =>
      setDevices(ds.filter((d) => d.kind === "audioinput")));
  }, [s.running]);

  // Options for the note-save pickers: the Notes DB's select options plus page
  // names for each relation target. Fetched as soon as a note exists — well
  // before the preview opens — so the pickers are never racing their data.
  const [noteOpts, setNoteOpts] = React.useState({});
  const [nameLists, setNameLists] = React.useState({});
  const pickerDataLoaded = React.useRef(false);
  React.useEffect(() => {
    if ((!s.note && !s.noteSave) || pickerDataLoaded.current) return;
    pickerDataLoaded.current = true;
    get("/api/notion/options?kind=note")
      .then((d) => setNoteOpts(d.options || {})).catch(() => {});
    ["contact", "company", "fund"].forEach((k) =>
      get(`/api/notion/names?kind=${k}`)
        .then((d) => setNameLists((p) => ({ ...p, [k]: d.names || [] })))
        .catch(() => setNameLists((p) => ({ ...p, [k]: [] }))));
  }, [!!s.note, !!s.noteSave]);
  const [refine, setRefine] = React.useState("");
  const [copied, setCopied] = React.useState(false);

  // Writing the note minimises the questions + recap panes so the draft gets
  // the room; they come back via SHOW, or when the note is gone.
  const [panesMin, setPanesMin] = React.useState(false);
  React.useEffect(() => {
    if (!s.note && s.busy !== "note") setPanesMin(false);
  }, [!!s.note, s.busy]);

  const openItems = s.items.filter((it) => !it.answer);
  const answeredItems = s.items.filter((it) => it.answer);
  const words = s.transcript ? s.transcript.split(/\s+/).length : 0;
  const newest = s.batches[0];

  return (
    <div className="fade-in">
      <PageHeader
        eyebrow={s.running ? `RECORDING · ${fmtElapsed(Date.now() - s.startedAt)} ELAPSED` : "MEETINGS · NOTES"}
        eyebrowTone={s.running ? "rec" : undefined}
        title="Meeting note taker"
        actions={s.running
          ? <>
              <Button variant="ghost" onClick={live.stop}>Stop</Button>
              <Button variant="dark" busy={s.busy === "note"}
                onClick={() => { setPanesMin(true); live.draftNote(); }}>Write the note</Button>
            </>
          : <>
              {(s.transcript || s.note) && (
                <Button variant="ghost" onClick={live.newSession}
                  title="File this session away and go back to the start screen">
                  Back to start
                </Button>
              )}
              {s.transcript && (
                <Button variant="dark" busy={s.busy === "note"}
                  onClick={() => { setPanesMin(true); live.draftNote(); }}>
                  Write the note
                </Button>
              )}
              <Button onClick={live.start}>Start listening</Button>
            </>}>
        {s.who ? `With ${s.who}. ` : ""}
        {s.goal || `Transcribes the meeting continuously and drafts the Weybourne note at the end. Live question suggestions are optional — recaps land every ${s.cadence} seconds either way.`}
        {!s.running && s.librarySaved && s.transcript ? " Transcript saved to the library." : ""}
      </PageHeader>

      {!s.running && (
        <Card style={{ marginBottom: 20 }}>
          <ContextChip />
          <div className="panes" style={{ gap: 18 }}>
            <Field label="FROM MY CALENDAR (OPTIONAL)" style={{ flex: "1 1 260px" }}
              hint="Picking a meeting loads who, key questions and Notion links.">
              <CalendarPick />
            </Field>
            <Field label="RECENT MANAGERS (OPTIONAL)" style={{ flex: "1 1 240px" }}
              hint="Managers you've prepped, triaged or met — no calendar entry needed.">
              <ManagerPick />
            </Field>
            <Field label="WHO YOU ARE MEETING" style={{ flex: "1 1 220px" }}
              hint="Typing a known manager's name loads their thread too.">
              <input value={s.who} onChange={(e) => live.set({ who: e.target.value })}
                onBlur={() => { if (s.who && !s.manager) live.resolveManager(s.who); }}
                placeholder="Axiom Asia, Fund VII" style={inputStyle} />
            </Field>
            <Field label="WHAT YOU WANT OUT OF IT" style={{ flex: "2 1 300px" }}
              hint="Steers the AI: suggested questions, recaps and the final note all weigh what you say here.">
              <input value={s.goal} onChange={(e) => live.set({ goal: e.target.value })}
                placeholder="e.g. re-up decision — test the capacity story" style={inputStyle} />
            </Field>
            <Field label="MEETING TYPE" style={{ flex: "1 1 260px" }}
              hint={s.source === "system"
                ? 'Mixes your mic with the computer audio — tick "Also share audio" in the picker.'
                : "Laptop microphone records the room."}>
              <select value={s.source} onChange={(e) => live.set({ source: e.target.value })} style={inputStyle}>
                <option value="system">Remote call — their audio + my microphone</option>
                <option value="mic">In person — microphone only</option>
              </select>
            </Field>
            <Field label="MICROPHONE" style={{ flex: "1 1 200px" }}>
              <select value={s.deviceId} onChange={(e) => live.set({ deviceId: e.target.value })} style={inputStyle}>
                <option value="">System default</option>
                {devices.map((d, i) => (
                  <option key={d.deviceId} value={d.deviceId}>{d.label || `Microphone ${i + 1}`}</option>
                ))}
              </select>
            </Field>
            <Field label="TRANSCRIPT LANGUAGE" style={{ flex: "1 1 180px" }}
              hint="Speech in any language is auto-detected; the transcript is cleaned up and written in this language.">
              <select value={s.outputLang} onChange={(e) => live.set({ outputLang: e.target.value })} style={inputStyle}>
                {OUTPUT_LANGS.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </Field>
            <Field label="READ EVERY" style={{ flex: "0 1 140px" }}
              hint="How often the recap and question read runs.">
              <select value={s.cadence} onChange={(e) => live.set({ cadence: +e.target.value })} style={inputStyle}>
                <option value={30}>30 seconds</option>
                <option value={45}>45 seconds</option>
                <option value={60}>60 seconds</option>
              </select>
            </Field>
          </div>
        </Card>
      )}

      {!s.running && !s.transcript && <TranscriptLibrary />}

      {/* Control strip */}
      {s.running && (
        <div style={{ background: "var(--ink-800)", borderRadius: "var(--radius)",
                      padding: "14px 18px", display: "flex", alignItems: "center",
                      gap: 22, flexWrap: "wrap", marginBottom: 24 }}>
          <canvas ref={canvasRef} width={900} height={34}
            style={{ height: 34, flex: "1 1 260px", minWidth: 200 }} />
          {[["OPEN", openItems.length], ["ANSWERED", answeredItems.length],
            ["READS", s.reads], ["WORDS", words.toLocaleString()]].map(([k, v]) => (
            <span key={k} className="mono" style={{ fontSize: 11, letterSpacing: ".1em", color: "var(--slate-300)" }}>
              {k} <b style={{ color: "var(--paper-050)", fontWeight: 500 }}>{v}</b>
            </span>
          ))}
          <span className="mono" style={{ fontSize: 11, letterSpacing: ".1em", color: "var(--teal-300)" }}>
            {s.busy === "read" ? "READING…" : s.nextIn > 0 ? `NEXT READ ${s.nextIn}S` : "READ DUE"}
          </span>
          <button onClick={() => live.set({ cadence: { 30: 45, 45: 60, 60: 30 }[s.cadence] || 30 })}
            className="mono" title="How often the recap + question read runs — click to change"
            style={{ background: "none", border: "1px solid var(--ink-500)",
                     borderRadius: 4, cursor: "pointer", padding: "3px 8px",
                     fontSize: 10.5, letterSpacing: ".1em", color: "var(--slate-300)" }}>
            EVERY {s.cadence}S
          </button>
          <button onClick={() => live.set({ questions: !s.questions })}
            className="mono" title="Toggle suggested questions from reads — your own sketches always work"
            style={{ background: "none", border: "1px solid var(--ink-500)",
                     borderRadius: 4, cursor: "pointer", padding: "3px 8px",
                     fontSize: 10.5, letterSpacing: ".1em",
                     color: s.questions ? "var(--teal-300)" : "var(--slate-300)" }}>
            SUGGESTIONS {s.questions ? "ON" : "OFF"}
          </button>
        </div>
      )}

      <ErrorNote error={s.error} />

      {panesMin ? (
        <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap",
                      padding: "10px 15px", background: "var(--paper-000)",
                      border: "1px solid var(--paper-200)",
                      borderRadius: "var(--radius)", marginBottom: 4 }}>
          <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".1em",
                                          color: "var(--stone-500)" }}>
            QUESTIONS · {openItems.length} OPEN · {answeredItems.length} ANSWERED
            &nbsp;&nbsp;RECAPS · {s.batches.filter((b) => b.recap).length}
          </span>
          <button className="mono" onClick={() => setPanesMin(false)}
            style={{ background: "none", border: "1px solid var(--paper-200)",
                     borderRadius: 4, cursor: "pointer", padding: "3px 10px",
                     fontSize: 10.5, letterSpacing: ".1em", color: "var(--teal-700)" }}>
            SHOW
          </button>
        </div>
      ) : (
      <div className="panes">
        {/* Questions pane — always visible: the toggle only controls whether
            reads ADD suggestions; sketching your own works either way. */}
        <div style={{ flex: "1.4 1 440px", minWidth: "min(100%,320px)" }}>
          <SectionHead label="QUESTIONS WORTH ASKING" right={
            <span style={{ display: "inline-flex", gap: 12, alignItems: "baseline" }}>
              {`${openItems.length} OPEN`}
              <button className="mono" onClick={() => setPanesMin(true)}
                title="Tuck the questions and recaps away so the note below gets the room"
                style={{ background: "none", border: "1px solid var(--paper-200)",
                         borderRadius: 4, cursor: "pointer", padding: "2px 8px",
                         fontSize: 10, letterSpacing: ".1em", color: "var(--teal-700)" }}>
                MINIMIZE
              </button>
            </span>} />

          {/* Sketch — available before the meeting starts too, so key
              questions can be prepared in advance. */}
          <div className="row" style={{ marginBottom: 14 }}>
            <input value={rough} onChange={(e) => setRough(e.target.value)}
              placeholder="sketch a question — rough is fine"
              style={{ flex: 1, minWidth: 180 }} />
            <Button variant="ghost" busy={s.busy === "sharpen"} disabled={!rough}
              onClick={() => { const r = rough; setRough(""); live.sharpen(r); }}>Sharpen</Button>
            <Button variant="ghost" disabled={!rough}
              onClick={() => { live.addOwnQuestion(rough); setRough(""); }}>Add as key</Button>
          </div>
          {s.busy === "sharpen" && s.sharpPending && (
            <Card style={{ marginBottom: 14, borderLeft: "2px solid var(--teal-500)" }}>
              <span className="microlabel" style={{ color: "var(--teal-700)" }}>SHARPENING…</span>
              <div style={{ fontSize: 15, margin: "6px 0", color: "var(--stone-400)" }}>
                {s.sharpPending}
              </div>
            </Card>
          )}
          {s.sharp && (
            <Card accent="teal" style={{ marginBottom: 14 }}>
              <span className="microlabel" style={{
                color: s.sharp.status === "answered" ? "var(--positive-600)"
                  : s.sharp.status === "partial" ? "var(--caution-600)" : "var(--teal-700)" }}>
                {{ answered: "ALREADY ANSWERED", partial: "PARTLY ANSWERED", open: "NOT COVERED YET" }[s.sharp.status]}
              </span>
              <div style={{ fontSize: 15, margin: "6px 0" }}>{s.sharp.question}</div>
              {s.sharp.evidence && <div className="muted" style={{ fontSize: "13px" }}>They said: {s.sharp.evidence}</div>}
              <div className="row" style={{ marginTop: 8 }}>
                <Button variant="ghost" onClick={live.keepSharp}>
                  {s.sharp.status === "answered" ? "File as answered" : "Add to outstanding"}
                </Button>
                <Button variant="ghost" onClick={live.dropSharp}>Discard</Button>
              </div>
            </Card>
          )}

          {openItems.length === 0 && s.batches.length === 0 && (
            <p className="muted small">
              {s.questions
                ? "Questions appear here after the first read — or sketch your own above."
                : "Automatic suggestions are off — sketch your own questions above."}
            </p>
          )}
          {[...openItems]
            .sort((a, b) => ((b.starred ? 1 : 0) - (a.starred ? 1 : 0)) || (b.id - a.id))
            .map((it) => {
              const isNew = newest && it.batch === newest.id;
              return (
                <Card key={it.id} style={{
                  padding: "15px 17px", marginBottom: 10,
                  background: it.starred ? "var(--brass-100)" : "var(--paper-000)",
                  borderLeft: it.starred ? "2px solid var(--brass-500)"
                    : isNew ? "2px solid var(--teal-500)" : "1px solid var(--paper-200)",
                }}>
                  <div className="spread" style={{ marginBottom: 6 }}>
                    <span className="mono" style={{ fontSize: 10, letterSpacing: ".1em",
                      color: it.starred ? "var(--brass-700)"
                        : isNew ? "var(--teal-700)" : "var(--stone-400)" }}>
                      {it.starred ? "MARKED · ASK THIS"
                        : isNew ? "NEW · FROM THE LAST READ"
                        : it.batch === 0 ? "YOURS"
                        : `READ · ${s.batches.find((b) => b.id === it.batch)?.at || ""}`}
                      {it.flag && <span style={{ color: "var(--caution-600)" }}> · RISK</span>}
                    </span>
                    <span style={{ display: "flex", gap: 10 }}>
                      <button onClick={() => live.toggleStar(it.id)}
                        title={it.starred ? "Unmark" : "Mark as important — ask this"}
                        style={{ background: "none", border: "none", cursor: "pointer",
                          color: it.starred ? "var(--brass-700)" : "var(--stone-400)",
                          fontSize: 14, lineHeight: 1, padding: 0 }}>✓</button>
                      {(() => {
                        // Fresh suggestions are delete-locked for two seconds
                        // so a mid-clear-out arrival can't be swept away.
                        const locked = live.isFresh(it);
                        return (
                          <button onClick={() => live.discardItem(it.id)}
                            title={locked ? "Just added — deletable in a moment" : "Discard"}
                            style={{ background: "none", border: "none",
                              cursor: locked ? "default" : "pointer",
                              color: locked ? "var(--paper-200)" : "var(--stone-400)",
                              fontSize: 15, lineHeight: 1, padding: 0 }}>×</button>
                        );
                      })()}
                    </span>
                  </div>
                  <div style={{ fontSize: 15, lineHeight: 1.5 }}>{it.q}</div>
                </Card>
              );
            })}

          {answeredItems.length > 0 && (
            <div style={{ borderTop: "1px solid var(--paper-200)", paddingTop: 12, marginTop: 6 }}>
              <span className="microlabel" style={{ color: "var(--positive-600)" }}>
                ANSWERED · {answeredItems.length}
              </span>
              {answeredItems.map((it) => (
                <div key={it.id} className="rrow">
                  <div style={{ fontSize: "13.5px", textDecoration: "line-through",
                                color: "var(--stone-400)" }}>{it.q}</div>
                  <div style={{ fontSize: "13px", borderLeft: "2px solid var(--teal-500)",
                                paddingLeft: 10, marginTop: 4 }}>
                    <span style={{ fontVariantCaps: "all-small-caps",
                      color: "var(--teal-700)", marginRight: 6 }}>They said</span>
                    {it.answer}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right pane — audio check + what was said */}
        <div style={{ flex: "1 1 300px", maxWidth: 420,
                      minWidth: "min(100%,280px)" }}>
          {s.running && <ContextChip />}
          {/* Meeting context stays settable mid-recording — pick from the
              calendar, recent managers, or just type the name. */}
          {s.running && (
            <details style={{ marginBottom: 12 }}>
              <summary className="microlabel" style={{ cursor: "pointer",
                       listStyle: "none", padding: "4px 0" }}>
                {s.who ? `MEETING: ${s.who.toUpperCase()}` : "SET WHO YOU'RE MEETING"}
                <span style={{ color: "var(--teal-700)", marginLeft: 8 }}>CHANGE</span>
              </summary>
              <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                <CalendarPick />
                <ManagerPick />
                <input value={s.who} onChange={(e) => live.set({ who: e.target.value })}
                  onBlur={() => { if (s.who && !s.manager) live.resolveManager(s.who); }}
                  placeholder="or type who you're meeting" style={inputStyle} />
              </div>
            </details>
          )}
          {s.running && (
            <Field label="WHAT YOU WANT OUT OF IT" style={{ marginBottom: 12 }}
              hint="Editable mid-meeting — steers the reads and the final note.">
              <input value={s.goal} onChange={(e) => live.set({ goal: e.target.value })}
                placeholder="e.g. re-up decision — test the capacity story" style={inputStyle} />
            </Field>
          )}
          {s.running && (
            <Card style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                <Mascot state="call" width={54} />
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {s.source === "system" && (
                    <span style={{ fontSize: "13.5px",
                      color: s.hearSystem ? "var(--positive-600)" : "var(--stone-400)" }}>
                      {s.hearSystem ? "✓ I'm hearing the call audio"
                        : "· Waiting for call audio…"}
                    </span>
                  )}
                  <span style={{ fontSize: "13.5px",
                    color: s.hearMic ? "var(--positive-600)" : "var(--stone-400)" }}>
                    {s.hearMic ? "✓ I'm hearing your microphone"
                      : "· Your microphone is quiet"}
                  </span>
                  {s.busy === "read" && (
                    <span className="mono" style={{ fontSize: 11, color: "var(--teal-600)" }}>
                      READING THE NEW SPEECH…
                    </span>
                  )}
                </div>
              </div>
            </Card>
          )}

          <SectionHead label="WHAT WAS SAID" right={`${words.toLocaleString()} WORDS`} />
          <Card style={{ padding: "14px 16px" }}>
            <div ref={transcriptBoxRef} style={{ maxHeight: 420, overflowY: "auto" }}
              onScroll={() => {
                // Ignore the events our own smooth jump fires; anything else
                // is the user reading — hold their place on the next recap.
                if (Date.now() > progScrollUntil.current) lastUserScrollAt.current = Date.now();
              }}>
              {s.batches.filter((b) => b.recap).length === 0 && (
                <span className="muted" style={{ fontSize: "13.5px", fontStyle: "italic" }}>
                  {s.running
                    ? "A recap of the conversation lands here after each read."
                    : "Start listening, or paste captions below."}
                </span>
              )}
              {s.batches.filter((b) => b.recap).map((b) => (
                <div key={b.id} className="rrow">
                  <span className="mono" style={{ fontSize: 10, color: "var(--stone-400)" }}>{b.at}</span>
                  <p style={{ fontSize: "13.5px", lineHeight: 1.55, margin: "4px 0 0" }}>{b.recap}</p>
                </div>
              ))}
            </div>
          </Card>
          <LiveTranscript />
          <Field label="PASTE CAPTIONS (TEAMS, A NOTION TRANSCRIPT)" style={{ marginTop: 14 }}>
            <textarea value={paste} onChange={(e) => setPaste(e.target.value)} rows={3}
              style={{ width: "100%", padding: "11px 13px" }} />
          </Field>
          <div className="row">
            <Button variant="ghost" disabled={!paste} busy={s.busy === "read"}
              onClick={() => { live.addPaste(paste, true); setPaste(""); }}>Add and read</Button>
            <Button variant="ghost" disabled={!paste}
              onClick={() => { live.addPaste(paste, false); setPaste(""); }}>Add only</Button>
          </div>
        </div>
      </div>
      )}

      {/* The draft forming in real time — replaced by the finished card below */}
      {!s.note && s.busy === "note" && (
        <Card accent="brass" style={{ marginTop: 24 }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <Mascot state="working" width={44} />
            <span className="microlabel">NOTE DRAFT · BEING WRITTEN…</span>
          </div>
          {s.noteDraftText
            ? <Markdown text={s.noteDraftText} />
            : <p className="muted" style={{ fontSize: "13.5px", marginTop: 10 }}>
                Reading the full transcript…
              </p>}
        </Card>
      )}

      {s.note && (
        <Card accent="brass" style={{ marginTop: 24 }}>
          <span className="microlabel">NOTE DRAFT · {(s.note.note.note_type || "MEETING NOTE").toUpperCase()}</span>
          <Markdown text={s.note.markdown} />
          <div className="row" style={{ flexWrap: "wrap" }}>
            <Button onClick={() => {
              navigator.clipboard.writeText(s.note.markdown)
                .then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); })
                .catch(() => {});
            }}>{copied ? "Copied" : "Copy note to clipboard"}</Button>
            {s.noteSaveUrl ? (
              <span className="muted" style={{ fontSize: "12.5px" }}>
                Saved to Notion —{" "}
                <a href={s.noteSaveUrl} target="_blank" rel="noreferrer"
                   style={{ color: "var(--teal-700)" }}>open the note</a>
              </span>
            ) : !s.noteSave && (
              <Button variant="dark" busy={s.busy === "notesave"}
                onClick={live.previewNoteSave}>
                Save to Notion
              </Button>
            )}
          </div>

          {/* Preview of the exact Notion note — every field shown, EDIT to change */}
          {s.noteSave && !s.noteSaveUrl && (
            <div style={{ marginTop: 14, padding: "14px 16px",
                          background: "var(--paper-050)",
                          border: "1px solid var(--paper-200)",
                          borderRadius: "var(--radius)" }}>
              <span className="microlabel">NOTE TO BE CREATED</span>
              <div style={{ display: "grid", gridTemplateColumns: "150px 1fr",
                            gap: "6px 12px", marginTop: 10 }}>
                {Object.entries(s.noteSave.editable || {}).map(([k, v]) => {
                  const editing = !!s.noteSaveEditing?.[k];
                  const value = s.noteSaveEdits?.[k] ?? v;
                  const editStyle = { fontSize: "12.5px", padding: "5px 8px",
                                      background: "var(--paper-000)",
                                      border: "1px solid var(--paper-200)",
                                      borderRadius: 4, color: "var(--ink-700)",
                                      fontFamily: "inherit", lineHeight: 1.5, flex: 1 };
                  // Selectable fields get the searchable pick-or-create
                  // dropdown; relation fields search real Notion pages.
                  const pickers = {
                    "Note Type": { options: noteOpts["Note Type"]
                      || ["GP Meeting", "LP Meeting", "Reference call", "3rd Party Marketer",
                          "Event", "Internal", "Service Provider", "Email"], multi: false },
                    "Done": { options: ["Yes", "No"], multi: false },
                    "Attendees": { options: nameLists.contact || [], multi: true,
                                   loading: nameLists.contact === undefined },
                    "Companies": { options: nameLists.company || [], multi: true,
                                   loading: nameLists.company === undefined },
                    "Fund": { options: nameLists.fund || [], multi: true,
                              loading: nameLists.fund === undefined },
                  };
                  const picker = pickers[k];
                  return (
                    <React.Fragment key={k}>
                      <span className="microlabel" style={{ paddingTop: 3 }}>{k}</span>
                      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                        {editing ? (
                          picker
                            ? <SearchSelect value={value} options={picker.options}
                                multi={picker.multi} loading={picker.loading}
                                onChange={(nv) => live.setNoteSaveEdit(k, nv)} />
                            : k === "Thoughts / Considerations"
                              ? <textarea rows={3} value={value} style={editStyle}
                                  onChange={(e) => live.setNoteSaveEdit(k, e.target.value)} />
                              : <input value={value} style={editStyle}
                                  onChange={(e) => live.setNoteSaveEdit(k, e.target.value)} />
                        ) : (
                          <span style={{ fontSize: "12.5px", flex: 1,
                            color: k in (s.noteSaveEdits || {}) ? "var(--teal-700)" : "inherit" }}>
                            {value}
                          </span>
                        )}
                        <button onClick={() => live.toggleNoteSaveFieldEdit(k)}
                          style={{ background: "none", border: "none", cursor: "pointer",
                                   color: "var(--teal-700)", fontFamily: "var(--mono)",
                                   fontSize: 10, letterSpacing: ".1em", paddingTop: 3 }}>
                          {editing ? "DONE" : "EDIT"}
                        </button>
                      </div>
                      {/* Refine: your own thoughts, woven into the paragraph
                          above by the model. */}
                      {k === "Thoughts / Considerations" && (
                        <>
                          <span />
                          <div>
                            <textarea rows={2} value={refine}
                              placeholder="add your own thoughts — the paragraph above is rewritten to give effect to them"
                              onChange={(e) => setRefine(e.target.value)}
                              style={{ ...editStyle, width: "100%", marginTop: 2 }} />
                            <Button variant="ghost" busy={s.busy === "refine"}
                              disabled={!refine.trim()}
                              onClick={async () => {
                                const ok = await live.refineThoughts(refine);
                                if (ok) setRefine("");
                              }}>
                              Refine thoughts / considerations
                            </Button>
                          </div>
                        </>
                      )}
                    </React.Fragment>
                  );
                })}
                {(s.noteSave.fixed || []).map(([k, v]) => (
                  <React.Fragment key={k}>
                    <span className="microlabel">{k}</span>
                    <span style={{ fontSize: "12.5px", color: "var(--stone-600)" }}>{v}</span>
                  </React.Fragment>
                ))}
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <Button variant="dark" busy={s.busy === "notesave"}
                  onClick={live.saveNoteToNotion}>
                  Create the note
                </Button>
                <Button variant="ghost" onClick={live.cancelNoteSave}>Cancel</Button>
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
