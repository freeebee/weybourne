/* Live meeting — a thin view over liveStore. The audio pipeline, timers and
   transcript live in the store at module scope, so navigating to another page
   does NOT stop the session; this page re-attaches on return. */
import React from "react";
import * as live from "../liveStore.js";
import {
  Banner, Button, Card, ErrorNote, Field, Mascot, PageHeader, inputStyle,
} from "../ui.jsx";
import { Markdown } from "./Prep.jsx";

export default function Live() {
  React.useSyncExternalStore(live.subscribe, live.getVersion);
  const s = live.S;

  const [devices, setDevices] = React.useState([]);
  const [rough, setRough] = React.useState("");
  const [paste, setPaste] = React.useState("");
  const [view, setView] = React.useState("timeline");
  const canvasRef = React.useRef(null);
  const transcriptBoxRef = React.useRef(null);

  React.useEffect(() => {
    live.attachCanvas(canvasRef.current);
    return () => live.attachCanvas(null);   // canvas gone; session keeps running
  }, [s.running]);

  React.useEffect(() => {
    const el = transcriptBoxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [s.transcript]);

  React.useEffect(() => {
    navigator.mediaDevices?.enumerateDevices?.().then((ds) =>
      setDevices(ds.filter((d) => d.kind === "audioinput")));
  }, [s.running]);

  const openItems = s.items.filter((it) => !it.answer);
  const answered = s.items.length - openItems.length;
  const words = s.transcript ? s.transcript.split(/\s+/).length : 0;

  return (
    <div className="fade-in">
      <PageHeader eyebrow="IN PROGRESS · LIVE" title="Live questions">
        Start listening and talk — the transcript grows as the meeting runs, and every
        30 seconds the new speech is recapped and turned into the next questions worth
        asking. Keeps running while you use other pages.
      </PageHeader>

      <Card style={{ marginBottom: "1rem" }}>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Field label="Who you are meeting">
            <input value={s.who} onChange={(e) => live.set({ who: e.target.value })}
              placeholder="Axiom Asia, Fund VII" style={inputStyle} />
          </Field>
          <Field label="What you want out of it" hint="Steers the questions, and what the note judges the meeting against.">
            <input value={s.goal} onChange={(e) => live.set({ goal: e.target.value })}
              placeholder="e.g. re-up decision — test the capacity story" style={inputStyle} />
          </Field>
        </div>
        <div className="row">
          {!s.running
            ? <Button onClick={live.start}>Start listening</Button>
            : <Button variant="secondary" onClick={live.stop}>Stop</Button>}
          <Field label="Meeting type"
            hint={s.source === "system"
              ? 'Mixes your microphone with what the computer is playing. Tick "Also share audio" in the picker.'
              : "Records the room through your microphone."}>
            <select value={s.source} onChange={(e) => live.set({ source: e.target.value })}
              disabled={s.running} style={{ ...inputStyle, width: 300 }}>
              <option value="system">Remote call — their audio + my microphone</option>
              <option value="mic">In person — microphone only</option>
            </select>
          </Field>
          <Field label="Microphone">
            <select value={s.deviceId} onChange={(e) => live.set({ deviceId: e.target.value })}
              disabled={s.running} style={{ ...inputStyle, width: 220 }}>
              <option value="">System default</option>
              {devices.map((d, i) => (
                <option key={d.deviceId} value={d.deviceId}>{d.label || `Microphone ${i + 1}`}</option>
              ))}
            </select>
          </Field>
        </div>
        <canvas ref={canvasRef} width={1200} height={56} style={{
          width: "100%", height: 56, display: s.running ? "block" : "none",
          background: "var(--paper-000)", border: "1px solid var(--paper-200)",
          borderRadius: "var(--radius-md)",
        }} />
        <div className="mono muted" style={{ fontSize: ".72rem", letterSpacing: ".1em", textTransform: "uppercase", marginTop: ".5rem" }}>
          <span style={{
            display: "inline-block", width: 8, height: 8, borderRadius: "50%",
            background: s.running ? "var(--teal-500)" : "var(--paper-300)", marginRight: 8,
          }} />
          open <b>{openItems.length}</b> · answered <b>{answered}</b> · reads <b>{s.reads}</b> · words <b>{words}</b>
          {s.running && (s.busy === "read"
            ? <> · reading the new speech…</>
            : s.nextIn > 0
              ? <> · next read in {s.nextIn}s</>
              : <> · read due — waiting for enough speech</>)}
        </div>

        {(s.running || s.transcript) && (
          <div ref={transcriptBoxRef} style={{
            maxHeight: 130, overflowY: "auto", marginTop: ".7rem",
            padding: ".6rem .8rem", background: "var(--paper-000)",
            border: "1px solid var(--paper-200)", borderRadius: "var(--radius-md)",
            fontFamily: "var(--serif)", fontSize: ".95rem", lineHeight: 1.55,
          }}>
            <span className="eyebrow" style={{ marginBottom: ".3rem" }}>LIVE TRANSCRIPT</span>
            {s.transcript
              ? <span>{s.transcript}</span>
              : <span className="muted" style={{ fontStyle: "italic" }}>
                  Listening — words appear here a few seconds behind the room…
                </span>}
            {s.running && s.transcript && <span className="muted"> ▌</span>}
          </div>
        )}
      </Card>

      <details style={{ marginBottom: "1rem" }}>
        <summary className="muted small" style={{ cursor: "pointer" }}>Paste text instead (Teams captions, a Notion transcript)</summary>
        <textarea value={paste} onChange={(e) => setPaste(e.target.value)} rows={4}
          style={{ ...inputStyle, margin: ".5rem 0" }} />
        <div className="row">
          <Button disabled={!paste} busy={s.busy === "read"}
            onClick={() => { live.addPaste(paste, true); setPaste(""); }}>Add and read</Button>
          <Button variant="ghost" disabled={!paste}
            onClick={() => { live.addPaste(paste, false); setPaste(""); }}>Add only</Button>
        </div>
      </details>

      <ErrorNote error={s.error} />

      <Card style={{ marginBottom: "1rem" }}>
        <span className="eyebrow">SKETCH A QUESTION</span>
        <div className="row">
          <input value={rough} onChange={(e) => setRough(e.target.value)}
            placeholder="rough is fine. e.g. fees? and lockup terms"
            style={{ ...inputStyle, flex: 1, width: "auto" }} />
          <Button variant="secondary" busy={s.busy === "sharpen"} disabled={!rough || !s.transcript}
            onClick={() => sharpenAndClear()}>Sharpen and check</Button>
        </div>
        {s.sharp && (
          <div style={{ marginTop: ".7rem" }}>
            <Banner tone={s.sharp.status === "answered" ? "success" : s.sharp.status === "partial" ? "warning" : "info"}>
              <b>{{ answered: "already answered", partial: "partly answered", open: "not covered yet" }[s.sharp.status]}</b>
              <div style={{ fontSize: "1.02rem", margin: ".3rem 0" }}>{s.sharp.question}</div>
              {s.sharp.evidence && <div className="small">They said: {s.sharp.evidence}</div>}
            </Banner>
            <div className="row">
              <Button variant="secondary" onClick={live.keepSharp}>
                {s.sharp.status === "answered" ? "File as answered" : "Add to outstanding"}
              </Button>
              <Button variant="ghost" onClick={live.dropSharp}>Discard</Button>
            </div>
          </div>
        )}
      </Card>

      {(s.items.length > 0 || s.batches.length > 0) && (
        <>
          <div className="row" style={{ marginBottom: ".5rem" }}>
            {["timeline", "outstanding"].map((v) => (
              <Button key={v} variant={view === v ? "primary" : "ghost"} onClick={() => setView(v)}>
                {v === "timeline" ? "Timeline" : `Outstanding (${openItems.length})`}
              </Button>
            ))}
          </div>
          {view === "outstanding"
            ? [...openItems.filter((i) => i.flag), ...openItems.filter((i) => !i.flag)]
                .map((it) => <QRow key={it.id} it={it} onDiscard={() => live.discardItem(it.id)} />)
            : (
              <>
                {s.items.filter((it) => it.batch === 0).length > 0 && (
                  <BatchBlock label="your questions"
                    rows={s.items.filter((it) => it.batch === 0)} />
                )}
                {s.batches.map((b) => (
                  <BatchBlock key={b.id} label={`read · ${b.at}`} recap={b.recap}
                    rows={s.items.filter((it) => it.batch === b.id)} />
                ))}
              </>
            )}
        </>
      )}

      {s.transcript && (
        <div style={{ marginTop: "1.4rem" }}>
          <hr className="rule" />
          <div className="row">
            <Button busy={s.busy === "note"} onClick={live.draftNote}>Draft the note</Button>
            <Button variant="ghost" onClick={live.newSession}>New session</Button>
          </div>
          {s.busy === "note" && <Mascot state="notes" text="Drafting the note from the full transcript…" />}
          {s.note && (
            <Card style={{ marginTop: "1rem" }}>
              <span className="eyebrow">NOTE DRAFT · {s.note.note.note_type}</span>
              <Markdown text={s.note.markdown} />
              <Button onClick={() => {
                const blob = new Blob([s.note.markdown], { type: "text/markdown" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob); a.download = "meeting-note.md"; a.click();
              }}>Download note (markdown)</Button>
            </Card>
          )}
        </div>
      )}
    </div>
  );

  function sharpenAndClear() {
    live.sharpen(rough).then(() => setRough(""));
  }
}

function QRow({ it, onDiscard }) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "26px 1fr 24px", gap: 10,
      padding: "7px 10px 7px 0", borderBottom: "1px dotted var(--paper-300)",
      background: it.flag && !it.answer ? "#fdf3e3" : "transparent",
      paddingLeft: it.flag && !it.answer ? 10 : 0,
    }}>
      <span className="mono small" style={{
        color: it.answer ? "var(--teal-600)" : it.flag ? "#9a5b12" : "var(--stone-500)",
      }}>{it.answer ? "✓" : it.flag ? "!" : it.id}</span>
      <div>
        <div style={{
          textDecoration: it.answer ? "line-through" : "none",
          color: it.answer ? "var(--stone-400)" : "var(--ink-700)",
        }}>{it.q}</div>
        {it.answer && (
          <div className="small" style={{ borderLeft: "2px solid var(--teal-500)", paddingLeft: 10, marginTop: 4 }}>
            <span style={{ fontVariantCaps: "all-small-caps", color: "var(--teal-700)", marginRight: 6 }}>They said</span>
            {it.answer}
          </div>
        )}
      </div>
      {onDiscard && (
        <button onClick={onDiscard} title="Discard this question" style={{
          background: "none", border: "none", cursor: "pointer",
          color: "var(--stone-400)", fontSize: "1rem", lineHeight: 1, padding: 0,
        }}>×</button>
      )}
    </div>
  );
}

function BatchBlock({ label, recap, rows }) {
  return (
    <div style={{ borderTop: "1px solid var(--paper-300)", padding: ".9rem 0 .3rem" }}>
      <div className="eyebrow">{label}</div>
      {recap && (
        <p style={{ fontSize: ".95rem", margin: "0 0 .7rem" }}>
          <span style={{ fontVariantCaps: "all-small-caps", color: "var(--teal-700)", marginRight: 6 }}>They said</span>
          {recap}
        </p>
      )}
      {rows.map((it) => (
        <QRow key={it.id} it={it} onDiscard={() => live.discardItem(it.id)} />
      ))}
    </div>
  );
}
