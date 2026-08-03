/* Live-meeting session store — lives at module scope, OUTSIDE React, so the
   audio pipeline, timers and transcript keep running when the user navigates
   to another page. The Live page (and the sidebar chip) subscribe to it. */
import { get, post, postFile, postStream } from "./api.js";

const CHUNK_MS = 8000;          // recorder restart interval → self-contained blobs
export const CADENCE_S = 30;    // read the new speech every 30 seconds
const MIN_NEW_WORDS = 5;

export const S = {
  running: false, who: "", goal: "", source: "system", deviceId: "",
  questions: true,   // live question suggestions — toggleable; recaps always run
  manager: null,     // the loaded manager thread (entity, Notion links, history)
  transcript: "", entries: [], items: [], batches: [], reads: 0, unreadWords: 0,
  lastTail: "", lastReadAt: 0, startedAt: 0, reading: false, nextIn: CADENCE_S,
  error: null, note: null, noteDraftText: "", sharp: null, sharpPending: "", busy: "", seq: 1, version: 0,
  noteSave: null, noteSaveEdits: {}, noteSaveEditing: {}, noteSaveUrl: "",
  sessionId: "", librarySaved: false,
};

function stamp() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

let listeners = new Set();
let micStream = null, displayStream = null, audioCtx = null, analyser = null,
    micAnalyser = null, sysAnalyser = null,
    recorder = null, chunkTimer = null, countdown = null, raf = 0, canvas = null;
let lastMicAt = 0, lastSysAt = 0;

function levelOf(an) {
  if (!an) return 0;
  const data = new Uint8Array(512);
  an.getByteFrequencyData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i++) sum += data[i];
  return sum / data.length / 255;
}

function emit() { S.version++; listeners.forEach((f) => f()); }
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function getVersion() { return S.version; }

export function set(patch) {
  const renamed = ("who" in patch && patch.who !== S.who)
    || ("goal" in patch && patch.goal !== S.goal);
  Object.assign(S, patch);
  emit();
  if (renamed) persistLibraryRecord();
}

/* A stopped session that lives in the library keeps its stored copy fresh:
   picking who the meeting was with (calendar, managers, typing) retitles the
   library record from "Untitled meeting" to the real name. Debounced. */
let persistTimer = null;
export function persistLibraryRecord() {
  if (!S.sessionId || S.running || !S.transcript.trim()) return;
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    post("/api/live/finish", sessionPayload())
      .then(() => { S.librarySaved = true; emit(); })
      .catch(() => { /* the autosave copy still stands */ });
  }, 800);
}

function context() {
  return [S.who ? `Meeting with ${S.who}.` : "", S.goal].filter(Boolean).join(" ");
}

export function attachCanvas(el) { canvas = el; }

// ---- autosave: mirror the session to disk so a crash loses nothing -------- //

function ensureSessionId() {
  if (!S.sessionId) {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    S.sessionId = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
    S.librarySaved = false;
  }
}

function sessionPayload() {
  return {
    id: S.sessionId, who: S.who, goal: S.goal,
    started: S.startedAt ? new Date(S.startedAt).toISOString() : "",
    transcript: S.transcript,
    entries: S.entries,
    recaps: S.batches.map((b) => ({ at: b.at, recap: b.recap })).filter((b) => b.recap),
    questions: S.items.map((it) => ({
      q: it.q, starred: !!it.starred, flag: !!it.flag, answer: it.answer || null,
    })),
  };
}

let autosaving = false;
async function autosaveNow() {
  if (autosaving || !S.sessionId || !S.transcript.trim()) return;
  autosaving = true;
  try { await post("/api/live/autosave", sessionPayload()); }
  catch { /* best-effort — never disturb the recording */ }
  autosaving = false;
}

// ---- read loop ------------------------------------------------------------ //

export async function performRead() {
  if (S.reading || !S.transcript.trim()) return;
  S.reading = true; S.busy = "read"; emit();
  try {
    const parsed = await post("/api/live/read", {
      transcript: S.transcript,
      open_items: S.items.filter((it) => !it.answer).map((it) => ({ id: it.id, q: it.q })),
      context: context(),
      prior_recaps: S.batches.slice(0, 3).map((b) => b.recap).filter(Boolean).join(" | "),
      last_tail: S.lastTail,
    });
    S.lastTail = S.transcript.slice(-240);
    S.unreadWords = 0; S.lastReadAt = Date.now(); S.reads++;
    if (parsed.answered?.length) {
      S.items = S.items.map((it) => {
        const hit = parsed.answered.find((a) => a.id === it.id);
        return hit && !it.answer ? { ...it, answer: hit.answer } : it;
      });
    }
    if (parsed.changed && (parsed.questions?.length || parsed.recap)) {
      const bid = Date.now();
      S.batches = [{ id: bid, at: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), recap: parsed.recap || "" }, ...S.batches];
      if (S.questions) {
        S.items = [...S.items, ...(parsed.questions || []).map((q) => ({
          id: S.seq++, batch: bid, q: q.q, flag: !!q.flag, answer: null,
        }))];
      }
    }
  } catch (e) { S.error = e.message; }
  S.reading = false; S.busy = ""; emit();
  autosaveNow();     // capture the fresh recap and questions on disk too
}

// ---- audio pipeline ------------------------------------------------------- //

export async function start() {
  S.error = null; S.note = null;
  ensureSessionId();
  emit();
  try {
    audioCtx = new AudioContext();
    const mixed = audioCtx.createMediaStreamDestination();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024; analyser.smoothingTimeConstant = 0.75;

    micStream = await navigator.mediaDevices.getUserMedia({
      audio: S.deviceId ? { deviceId: { exact: S.deviceId } } : true,
    });
    const micSrc = audioCtx.createMediaStreamSource(micStream);
    micAnalyser = audioCtx.createAnalyser(); micAnalyser.fftSize = 1024;
    micSrc.connect(mixed); micSrc.connect(analyser); micSrc.connect(micAnalyser);

    if (S.source === "system") {
      const display = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: { echoCancellation: false, noiseSuppression: false },
      });
      displayStream = display;
      const audioTracks = display.getAudioTracks();
      if (!audioTracks.length) {
        display.getTracks().forEach((t) => t.stop());
        micStream.getTracks().forEach((t) => t.stop());
        throw new Error('no audio in the share — pick a tab or screen AND tick "Also share audio" in the picker');
      }
      const sysSrc = audioCtx.createMediaStreamSource(new MediaStream(audioTracks));
      sysAnalyser = audioCtx.createAnalyser(); sysAnalyser.fftSize = 1024;
      sysSrc.connect(mixed); sysSrc.connect(analyser); sysSrc.connect(sysAnalyser);
      audioTracks[0].addEventListener("ended", () => stop());
    }

    const stream = mixed.stream;
    S.running = true; S.lastReadAt = Date.now();
    S.startedAt = S.startedAt || Date.now();
    emit();
    drawLoop();

    const recordChunk = () => {
      if (!S.running) return;
      const rec = new MediaRecorder(stream);
      const parts = [];
      rec.ondataavailable = (e) => e.data.size && parts.push(e.data);
      rec.onstop = async () => {
        if (!parts.length) return;
        const blob = new Blob(parts, { type: rec.mimeType });
        try {
          const { text } = await postFile("/api/stt", blob, "chunk.webm");
          if (text) {
            S.transcript += (S.transcript ? " " : "") + text;
            S.entries = [...S.entries, { at: stamp(), text }];
            S.unreadWords += text.split(/\s+/).length;
            emit();
            autosaveNow();
          }
        } catch (e) { S.error = e.message; emit(); }
      };
      rec.start();
      recorder = rec;
      chunkTimer = setTimeout(() => {
        if (rec.state !== "inactive") rec.stop();
        recordChunk();
      }, CHUNK_MS);
    };
    recordChunk();

    countdown = setInterval(() => {
      const due = CADENCE_S - (Date.now() - S.lastReadAt) / 1000;
      S.nextIn = Math.max(0, Math.round(due));
      // Per-source "am I hearing it?" indicators, with a 3-second hold.
      const now = Date.now();
      if (levelOf(micAnalyser) > 0.015) lastMicAt = now;
      if (levelOf(sysAnalyser) > 0.015) lastSysAt = now;
      S.hearMic = now - lastMicAt < 3000;
      S.hearSystem = now - lastSysAt < 3000;
      emit();
      if (S.running && !S.reading && due <= 0 && S.unreadWords >= MIN_NEW_WORDS) {
        performRead();
      }
    }, 1000);
  } catch (e) {
    S.error = `Audio unavailable: ${e.message}`;
    emit();
  }
}

export function stop() {
  const wasRunning = S.running;
  S.running = false;
  clearTimeout(chunkTimer); clearInterval(countdown);
  cancelAnimationFrame(raf);
  if (recorder && recorder.state !== "inactive") recorder.stop();
  micStream?.getTracks().forEach((t) => t.stop()); micStream = null;
  displayStream?.getTracks().forEach((t) => t.stop()); displayStream = null;
  audioCtx?.close().catch(() => {}); audioCtx = null; analyser = null;
  micAnalyser = null; sysAnalyser = null;
  S.hearMic = false; S.hearSystem = false;
  emit();
  // File the session in the transcript library. The last audio chunk may still
  // be transcribing, so give it a moment to land before the final write.
  if (wasRunning && S.sessionId && S.transcript.trim()) {
    setTimeout(async () => {
      try {
        await post("/api/live/finish", sessionPayload());
        S.librarySaved = true; emit();
      } catch { /* the autosave copy still exists on disk */ }
    }, 2500);
  }
}

function drawLoop() {
  if (!S.running) return;
  raf = requestAnimationFrame(drawLoop);
  if (!canvas || !analyser) return;
  const ctx = canvas.getContext("2d");
  const data = new Uint8Array(1024);
  analyser.getByteFrequencyData(data);
  const N = 96, w = canvas.width, h = canvas.height, bw = w / N;
  ctx.clearRect(0, 0, w, h);
  for (let i = 0; i < N; i++) {
    const a = Math.floor(i * 360 / N), b = Math.floor((i + 1) * 360 / N);
    let v = 0;
    for (let j = a; j < b; j++) v = Math.max(v, data[j]);
    v /= 255;
    const bh = Math.max(2, v * (h - 6));
    // Drawn on the ink control strip: teal-300 for signal, ink-500 for quiet.
    ctx.fillStyle = v > 0.02 ? "#84C7C2" : "#2F6688";
    ctx.fillRect(i * bw + 1, (h - bh) / 2, bw - 2, bh);
  }
}

// ---- user actions --------------------------------------------------------- //

export async function addPaste(text, read) {
  ensureSessionId();
  S.transcript += (S.transcript ? " " : "") + text;
  S.entries = [...S.entries, { at: stamp(), text }];
  S.unreadWords += text.split(/\s+/).length;
  emit();
  autosaveNow();
  if (read) await performRead();
}

export async function sharpen(rough) {
  S.busy = "sharpen"; S.sharpPending = rough; S.sharp = null; S.error = null; emit();
  try {
    S.sharp = await post("/api/live/sharpen", {
      transcript: S.transcript, rough, context: context(),
    });
  } catch (e) { S.error = e.message; }
  S.busy = ""; S.sharpPending = ""; emit();
}

export function keepSharp() {
  const sharp = S.sharp;
  if (!sharp) return;
  S.items = [...S.items, {
    id: S.seq++, batch: 0, q: sharp.question, flag: false, starred: true,
    answer: sharp.status === "answered" ? sharp.evidence : null,
  }];
  S.sharp = null; emit();
}

/* Your own question, added verbatim — marked as key (starred). */
export function addOwnQuestion(q, starred = true) {
  const text = (q || "").trim();
  if (!text || S.items.some((it) => it.q === text)) return;
  S.items = [...S.items, {
    id: S.seq++, batch: 0, q: text, flag: false, answer: null, starred,
  }];
  emit();
}

/* ---- manager thread: the context that follows a manager through the app -- */

export function setManagerContext(thread) {
  if (!thread || !thread.entity) return;
  S.manager = thread;
  S.who = S.who || thread.entity;
  (thread.questions || []).forEach((k) => addOwnQuestion(k.q, true));
  emit();
  persistLibraryRecord();   // retitle the stored session if one is loaded
}

/* Fuzzy-resolve any name (calendar counterparty, subject, typed) to a
   manager thread and load it. Returns the thread or null. */
export async function resolveManager(q) {
  if (!q) return null;
  try {
    const d = await get(`/api/managers/resolve?q=${encodeURIComponent(q)}`);
    if (d && d.entity) { setManagerContext(d); return d; }
  } catch { /* no thread — plain session */ }
  return null;
}

export function dropSharp() { S.sharp = null; emit(); }

export function discardItem(id) {
  S.items = S.items.filter((it) => it.id !== id);
  emit();
}

export function toggleStar(id) {
  S.items = S.items.map((it) =>
    it.id === id ? { ...it, starred: !it.starred } : it);
  emit();
}

export async function draftNote() {
  S.busy = "note"; S.error = null; S.note = null; S.noteDraftText = ""; emit();
  const payload = {
    transcript: S.transcript, context: context(),
    unanswered: S.items.filter((it) => !it.answer).map((it) => it.q),
  };
  try {
    // Streamed draft: the markdown renders as the model writes it. Repaints
    // are throttled — the text arrives faster than re-parsing it is worth.
    let lastPaint = 0;
    const md = await postStream("/api/live/note-stream", payload, (_c, full) => {
      S.noteDraftText = full;
      const now = Date.now();
      if (now - lastPaint > 120) { lastPaint = now; emit(); }
    });
    if (!md.trim() || md.includes("[[STREAM-FAILED]]")) {
      S.noteDraftText = ""; emit();
      S.note = await post("/api/live/note", payload);   // non-streamed fallback
    } else {
      const fields = await post("/api/live/note-parse", { markdown: md });
      S.note = { note: fields, markdown: md };
    }
  } catch (e) {
    // Streaming unavailable at the transport level — fall back quietly.
    try { S.note = await post("/api/live/note", payload); }
    catch (e2) { S.error = e2.message; }
  }
  S.noteDraftText = ""; S.busy = ""; emit();
}

export function newSession() {
  stop();
  Object.assign(S, {
    transcript: "", entries: [], items: [], batches: [], reads: 0, unreadWords: 0,
    lastTail: "", lastReadAt: 0, startedAt: 0, nextIn: CADENCE_S, error: null,
    note: null, noteDraftText: "", sharp: null, sharpPending: "", busy: "", seq: 1, manager: null,
    noteSave: null, noteSaveEdits: {}, noteSaveEditing: {}, noteSaveUrl: "",
    sessionId: "", librarySaved: false,
  });
  emit();
}

/* Reopen a library transcript: restores the text, context and questions so the
   note can be drafted (or the meeting resumed) as if the session never closed. */
export async function loadFromLibrary(sid) {
  const rec = await get(`/api/transcripts/${encodeURIComponent(sid)}`);
  newSession();
  S.sessionId = rec.id; S.librarySaved = !rec.unfinished;
  S.who = rec.who || ""; S.goal = rec.goal || "";
  S.transcript = rec.transcript || "";
  S.entries = rec.entries || [];
  S.batches = (rec.recaps || []).map((r, i) => ({ id: i + 1, at: r.at, recap: r.recap }));
  S.items = (rec.questions || []).map((q) => ({
    id: S.seq++, batch: 0, q: q.q, flag: !!q.flag, starred: !!q.starred,
    answer: q.answer || null,
  }));
  if (rec.started) S.startedAt = Date.parse(rec.started) || 0;
  emit();
  if (rec.who) resolveManager(rec.who);
}

// ---- save the drafted note to Notion (preview → edit → create) ----------- //

export async function previewNoteSave() {
  if (!S.note) return;
  S.busy = "notesave"; S.error = null; emit();
  try {
    S.noteSave = await post("/api/notion/save-meeting-note", {
      title: S.note.note.title, note_type: S.note.note.note_type,
      markdown: S.note.markdown,
      overall_impression: S.note.note.overall_impression || "",
      who: S.who, entity: S.manager?.entity || "", preview: true,
    });
    S.noteSaveEdits = {}; S.noteSaveEditing = {};
  } catch (e) { S.error = e.message; }
  S.busy = ""; emit();
}

export function setNoteSaveEdit(prop, value) {
  S.noteSaveEdits = { ...S.noteSaveEdits, [prop]: value }; emit();
}

export function toggleNoteSaveFieldEdit(prop) {
  S.noteSaveEditing = { ...S.noteSaveEditing, [prop]: !S.noteSaveEditing[prop] };
  emit();
}

export function cancelNoteSave() {
  S.noteSave = null; S.noteSaveEdits = {}; S.noteSaveEditing = {}; emit();
}

/* Rewrite Thoughts / Considerations so it absorbs the investor's own added
   thoughts. Returns true on success so the input can clear. */
export async function refineThoughts(additions) {
  if (!(additions || "").trim() || !S.noteSave) return false;
  S.busy = "refine"; S.error = null; emit();
  let ok = false;
  try {
    const current = S.noteSaveEdits["Thoughts / Considerations"]
      ?? S.noteSave.editable?.["Thoughts / Considerations"] ?? "";
    const res = await post("/api/live/refine-thoughts", {
      current, additions, context: context(),
    });
    if (res.text) { setNoteSaveEdit("Thoughts / Considerations", res.text); ok = true; }
  } catch (e) { S.error = e.message; }
  S.busy = ""; emit();
  return ok;
}

export async function saveNoteToNotion() {
  if (!S.note) return;
  S.busy = "notesave"; S.error = null; emit();
  try {
    const res = await post("/api/notion/save-meeting-note", {
      title: S.note.note.title, note_type: S.note.note.note_type,
      markdown: S.note.markdown,
      overall_impression: S.note.note.overall_impression || "",
      who: S.who, entity: S.manager?.entity || "",
      edits: { ...(S.noteSave?.editable || {}), ...S.noteSaveEdits },
    });
    S.noteSaveUrl = res.url; S.noteSave = null;
  } catch (e) { S.error = e.message; }
  S.busy = ""; emit();
}
