/* Live meeting — thin view over liveStore; redesign per handoff. */
import React from "react";
import { get } from "../api.js";
import * as live from "../liveStore.js";
import {
  Banner, Button, Card, ErrorNote, Field, Mascot, PageHeader, SectionHead,
  inputStyle,
} from "../ui.jsx";
import { Markdown } from "./Prep.jsx";

function CalendarPick() {
  const [events, setEvents] = React.useState([]);
  const [idx, setIdx] = React.useState("");

  React.useEffect(() => {
    get("/api/calendar?days=2").then((d) => setEvents(d.events)).catch(() => {});
  }, []);

  return (
    <select value={idx} style={inputStyle} onChange={(e) => {
      setIdx(e.target.value);
      const ev = events[+e.target.value];
      if (ev) {
        live.set({
          who: ev.counterparty_name || ev.subject,
          goal: live.S.goal || ev.subject,
        });
      }
    }}>
      <option value="">— pick a meeting —</option>
      {events.map((e, i) => (
        <option key={i} value={i}>
          {(e.start || "").slice(5, 16).replace("T", " ")} · {e.subject}
        </option>
      ))}
    </select>
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

  React.useEffect(() => {
    const el = transcriptBoxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [s.batches.length]);

  React.useEffect(() => {
    navigator.mediaDevices?.enumerateDevices?.().then((ds) =>
      setDevices(ds.filter((d) => d.kind === "audioinput")));
  }, [s.running]);

  const openItems = s.items.filter((it) => !it.answer);
  const answeredItems = s.items.filter((it) => it.answer);
  const words = s.transcript ? s.transcript.split(/\s+/).length : 0;
  const newest = s.batches[0];

  return (
    <div className="fade-in">
      <PageHeader
        eyebrow={s.running ? `RECORDING · ${fmtElapsed(Date.now() - s.startedAt)} ELAPSED` : "IN PROGRESS · LIVE"}
        eyebrowTone={s.running ? "rec" : undefined}
        title="Live questions"
        actions={s.running
          ? <>
              <Button variant="ghost" onClick={live.stop}>Stop</Button>
              <Button variant="dark" busy={s.busy === "note"} onClick={live.draftNote}>Write the note</Button>
            </>
          : <Button onClick={live.start}>Start listening</Button>}>
        {s.who ? `With ${s.who}. ` : ""}
        {s.goal || "Every 30 seconds the new speech is recapped and turned into the next questions worth asking. Keeps running while you use other pages."}
      </PageHeader>

      {!s.running && (
        <Card style={{ marginBottom: 20 }}>
          <div className="panes" style={{ gap: 18 }}>
            <Field label="FROM MY CALENDAR (OPTIONAL)" style={{ flex: "1 1 260px" }}
              hint="Picking a meeting fills in who and what for.">
              <CalendarPick />
            </Field>
            <Field label="WHO YOU ARE MEETING" style={{ flex: "1 1 220px" }}>
              <input value={s.who} onChange={(e) => live.set({ who: e.target.value })}
                placeholder="Axiom Asia, Fund VII" style={inputStyle} />
            </Field>
            <Field label="WHAT YOU WANT OUT OF IT" style={{ flex: "2 1 300px" }}>
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
          </div>
        </Card>
      )}

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
        </div>
      )}

      <ErrorNote error={s.error} />

      <div className="panes">
        {/* Questions pane */}
        <div style={{ flex: "1.4 1 440px", minWidth: "min(100%,320px)" }}>
          <SectionHead label="QUESTIONS WORTH ASKING" right={`${openItems.length} OPEN`} />

          {/* Sketch */}
          <div className="row" style={{ marginBottom: 14 }}>
            <input value={rough} onChange={(e) => setRough(e.target.value)}
              placeholder="sketch a question — rough is fine"
              style={{ flex: 1, minWidth: 180 }} />
            <Button variant="ghost" busy={s.busy === "sharpen"} disabled={!rough || !s.transcript}
              onClick={() => live.sharpen(rough).then(() => setRough(""))}>Sharpen</Button>
          </div>
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
            <p className="muted small">Questions appear here after the first read.</p>
          )}
          {[...openItems].sort((a, b) => (b.starred ? 1 : 0) - (a.starred ? 1 : 0))
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
                        : isNew ? "NEW · FROM THE LAST 30 SECONDS"
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
                      <button onClick={() => live.discardItem(it.id)} title="Discard" style={{
                        background: "none", border: "none", cursor: "pointer",
                        color: "var(--stone-400)", fontSize: 15, lineHeight: 1, padding: 0 }}>×</button>
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
        <div style={{ flex: "1 1 300px", maxWidth: 420, minWidth: "min(100%,280px)" }}>
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
            <div ref={transcriptBoxRef} style={{ maxHeight: 420, overflowY: "auto" }}>
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
          <Field label="PASTE CAPTIONS (TEAMS, A NOTION TRANSCRIPT)" style={{ marginTop: 14 }}>
            <textarea value={paste} onChange={(e) => setPaste(e.target.value)} rows={3}
              style={{ width: "100%", padding: "11px 13px" }} />
          </Field>
          <div className="row">
            <Button variant="ghost" disabled={!paste} busy={s.busy === "read"}
              onClick={() => { live.addPaste(paste, true); setPaste(""); }}>Add and read</Button>
            <Button variant="ghost" disabled={!paste}
              onClick={() => { live.addPaste(paste, false); setPaste(""); }}>Add only</Button>
            <Button variant="ghost" onClick={live.newSession}>New session</Button>
          </div>
        </div>
      </div>

      {s.note && (
        <Card accent="brass" style={{ marginTop: 24 }}>
          <span className="microlabel">NOTE DRAFT · {s.note.note.note_type.toUpperCase()}</span>
          <Markdown text={s.note.markdown} />
          <Button onClick={() => {
            const blob = new Blob([s.note.markdown], { type: "text/markdown" });
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob); a.download = "meeting-note.md"; a.click();
          }}>Download note (markdown)</Button>
        </Card>
      )}
      {s.busy === "note" && <Mascot state="notes" width={64} text="Drafting the note from the full transcript…" />}
    </div>
  );
}
