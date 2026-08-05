/* Live-meeting session store — lives at module scope, OUTSIDE React, so the
   audio pipeline, timers and transcript keep running when the user navigates
   to another page. The Live page (and the sidebar chip) subscribe to it. */
import { get, post, postFile, postStream } from "./api.js";

const CHUNK_MS = 8000;          // recorder restart interval → self-contained blobs
const MIN_NEW_WORDS = 5;
// The very first read doesn't wait for a full cadence (30/45/60s) — that's
// dead air before the first recap or question appears, on top of whatever
// the model round trip itself takes. Once there's been at least one read
// this session, the normal cadence/MIN_NEW_WORDS pacing takes over.
const FIRST_READ_SECONDS = 15;
const FIRST_READ_WORDS = 30;
const FRESH_LOCK_MS = 2000;     // a just-generated question can't be deleted yet
// Matches src/features/transcription.py's MAX_OPEN_QUESTIONS — the backend
// already budgets each read against this, this is just the backstop.
const MAX_OPEN_QUESTIONS = 20;

export const S = {
  running: false, who: "", goal: "", source: "system", deviceId: "",
  systemLost: false,   // the share ended mid-meeting; the mic carries on
  questions: true,   // live question suggestions — toggleable; recaps always run
  manager: null,     // the loaded manager thread (entity, Notion links, history)
  cadence: 30,       // seconds between reads — 30 / 45 / 60, user-selectable
  // The transcript is always written in English: Mandarin is translated as it
  // is cleaned up, so one meeting reads as one document and everything
  // downstream (recaps, questions, the note) works off English.
  outputLang: "English",
  detectedLang: "", detectedProb: 0,   // what whisper heard on the last chunk
  tidyPending: 0,    // chunks transcribed but still being cleaned up by Haiku
  rawPending: "",    // heard and already on screen, not yet cleaned up
  transcript: "", entries: [], items: [], batches: [], reads: 0, unreadWords: 0,
  lastTail: "", lastReadAt: 0, startedAt: 0, reading: false, nextIn: 30,
  error: null, note: null, noteDraftText: "", sharp: null, sharpPending: "", busy: "", seq: 1, version: 0,
  // The note draft gets its own flag rather than sharing `busy`. `busy` is one
  // slot for seven operations, and a recap read finishing mid-draft cleared it:
  // the streaming panel vanished, the questions sprang back open and the
  // button re-armed, so a second draft could be started on top of the first.
  noteBusy: false,
  // Questions and recaps fold away while the note has the floor, and stay
  // folded when you come back to a transcript that already has one. Lives here
  // rather than in the page so leaving and returning does not reopen them.
  panesMin: false,
  noteSave: null, noteSaveEdits: {}, noteSaveEditing: {}, noteSaveUrl: "",
  sessionId: "", librarySaved: false,
  // Left-pane tabs: the live questions (existing view), the meeting prep
  // document for whoever S.manager resolved to, and the deck attached to
  // that prep, if any. `wide` maximizes this pane and shrinks the
  // transcription side, mirroring the Prep page's widen handle.
  tab: "questions", tabWide: false,
  prepDoc: null, prepDocLoading: false,
};

function stamp() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

let listeners = new Set();
let micStream = null, displayStream = null, audioCtx = null, analyser = null,
    micAnalyser = null, sysAnalyser = null,
    recorder = null, chunkTimer = null, countdown = null, raf = 0, canvas = null;
// The recorder runs off `mixedDest`, never off a device stream directly. That
// is what lets a source be swapped mid-meeting: rewire the graph feeding the
// destination and the recording carries on without a gap.
let mixedDest = null, micSrcNode = null, sysSrcNode = null;
let lastMicAt = 0, lastSysAt = 0, chunkNo = 0;
let langStreak = { lang: "", n: 0 };   // consecutive confident detections

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
    // The drafted note is part of the session: it survives Stop, lives in the
    // library record, and comes back when the transcript is reopened.
    note_markdown: S.note?.markdown || "",
    note_fields: S.note?.note || {},
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

// ---- tidy queue ----------------------------------------------------------- //
/* Raw whisper chunks are cleaned into proper sentences (and translated into
   the chosen output language) by Haiku before they join the transcript.
   One cleanup call runs at a time so chunks land in speaking order — but the
   queue COALESCES: when the call in flight returns, everything waiting goes
   into the next call together. A cleanup that runs slower than the chunk
   cadence therefore drains in one call instead of falling further and further
   behind (the old strictly-serial chain starved the live window). On any
   failure the raw text goes in instead — nothing is ever lost to a cleanup
   error. */
let tidyQueue = [];
let tidyBusy = false;
let tidyWaiters = [];

function appendTranscript(text, countWords = true) {
  S.transcript += (S.transcript ? " " : "") + text;
  S.entries = [...S.entries, { at: stamp(), text }];
  if (countWords) S.unreadWords += text.split(/\s+/).length;
  emit();
  autosaveNow();
}

/* Whisper's raw text goes on screen the moment it lands, and is replaced by
   the cleaned version when that returns. Waiting for the cleanup before
   showing anything made a "live" transcript arrive fifteen to twenty seconds
   after the words were spoken: an eight-second chunk, then whisper, then a
   Haiku round trip. The rough text is readable immediately and the polish
   catches up. */
export function hearChunk(raw) {
  tidyQueue.push(raw);
  S.rawPending = (S.rawPending ? S.rawPending + " " : "") + raw;
  // Counted here, not on append: the read loop should react to speech as it
  // happens, not to how quickly the cleanup keeps up.
  S.unreadWords += raw.split(/\s+/).length;
  S.tidyPending = tidyQueue.length + (tidyBusy ? 1 : 0);
  emit();
  pumpTidy();
}

async function pumpTidy() {
  if (tidyBusy || !tidyQueue.length) return;
  tidyBusy = true;
  const raw = tidyQueue.splice(0).join(" ");   // take the whole backlog
  S.tidyPending = 1; emit();
  let text = raw;
  try {
    const r = await post("/api/live/tidy", {
      raw,
      prev_tail: S.transcript.slice(-350),
      output_language: S.outputLang,
      detected_language: S.detectedLang,
      session_id: S.sessionId,
    });
    // An empty cleanup claims the chunk held no speech. When whisper heard
    // actual words that claim is wrong, and taking it at face value deleted
    // them: the words showed on screen in grey, then vanished, and because a
    // read needs a transcript the recaps and questions stopped with them.
    // Rough text beats missing text.
    text = (r.text ?? "").trim() || raw;
  } catch { /* keep the raw text — better rough than missing */ }
  tidyBusy = false;
  S.tidyPending = tidyQueue.length;
  // Drop exactly the raw this call consumed; anything that arrived while it
  // was in flight is still provisional and stays on screen.
  S.rawPending = S.rawPending.startsWith(raw)
    ? S.rawPending.slice(raw.length).trim()
    : tidyQueue.join(" ");
  if (text.trim()) appendTranscript(text.trim(), false);
  else emit();
  if (tidyQueue.length) pumpTidy();
  else tidyWaiters.splice(0).forEach((res) => res());
}

/* Resolves once every queued chunk has been cleaned and appended. */
function tidyDrained() {
  if (!tidyBusy && !tidyQueue.length) return Promise.resolve();
  return new Promise((res) => tidyWaiters.push(res));
}

// ---- read loop ------------------------------------------------------------ //

export async function performRead() {
  // The tidied transcript PLUS whatever's still in the cleanup queue — once
  // any tidied text exists, rawPending is never stale overlap (pumpTidy
  // strips off exactly what each cleanup call consumed), so this is always
  // "everything heard so far," not a duplicate. Reading only S.transcript
  // left the most recent speech invisible to recaps/questions for however
  // long cleanup was backed up, which on a slow stretch could be the entire
  // read cycle.
  const text = [S.transcript.trim(), S.rawPending.trim()].filter(Boolean).join(" ");
  if (S.reading || !text) return;
  // Snapshotted BEFORE the request fires: lastReadAt anchors the next
  // cadence tick to when this read STARTED, not when it finished, so a
  // 30s cadence stays 30s instead of 30s-plus-however-long-the-model-took.
  // unreadWordsAtStart is subtracted (not zeroed) on completion so words
  // that arrive while this request is in flight are still counted, not
  // silently discarded.
  const unreadWordsAtStart = S.unreadWords;
  S.reading = true; S.busy = "read"; S.lastReadAt = Date.now(); emit();
  try {
    const parsed = await post("/api/live/read", {
      transcript: text,
      open_items: S.items.filter((it) => !it.answer).map((it) => ({ id: it.id, q: it.q })),
      context: context(),
      prior_recaps: S.batches.slice(0, 3).map((b) => b.recap).filter(Boolean).join(" | "),
      last_tail: S.lastTail,
      session_id: S.sessionId,
    });
    S.lastTail = text.slice(-240);   // where this read got to, whatever it read
    S.unreadWords = Math.max(0, S.unreadWords - unreadWordsAtStart); S.reads++;
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
        // The backend already budgets each read against MAX_OPEN_QUESTIONS,
        // reading the open count as of when the request was built — this is
        // the backstop against that count having moved (or the model simply
        // not following the budget) by the time the response lands.
        const openNow = S.items.filter((it) => !it.answer).length;
        const room = Math.max(0, MAX_OPEN_QUESTIONS - openNow);
        // born: fresh suggestions carry a short delete-lock so a question that
        // appears mid-clear-out isn't swept away by an accidental click.
        S.items = [...S.items, ...(parsed.questions || []).slice(0, room).map((q) => ({
          id: S.seq++, batch: bid, q: q.q, flag: !!q.flag, answer: null,
          born: Date.now(),
        }))];
        setTimeout(emit, FRESH_LOCK_MS + 200);   // repaint once the lock lifts
      }
    }
  } catch (e) { S.error = e.message; }
  S.reading = false; S.busy = ""; emit();
  autosaveNow();     // capture the fresh recap and questions on disk too
}

// ---- audio pipeline ------------------------------------------------------- //

/* The microphones the browser can see. Labels are only populated once audio
   permission has been granted, which is true from the moment recording starts —
   before that the list is real but unnamed, so we say so rather than showing
   a row of blanks. */
export async function listMics() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "audioinput")
      .map((d, i) => ({ id: d.deviceId, label: d.label || `Microphone ${i + 1}` }));
  } catch { return []; }
}

/* Point the microphone leg of the graph at `deviceId`, replacing whatever was
   there. Safe to call mid-meeting: the old node is only dropped once the new
   one is live, so a failed switch leaves the existing audio untouched. */
async function attachMic(deviceId) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: deviceId ? { deviceId: { exact: deviceId } } : true,
  });
  const src = audioCtx.createMediaStreamSource(stream);
  micAnalyser = audioCtx.createAnalyser(); micAnalyser.fftSize = 1024;
  src.connect(mixedDest); src.connect(analyser); src.connect(micAnalyser);

  micSrcNode?.disconnect();
  micStream?.getTracks().forEach((t) => t.stop());
  micSrcNode = src; micStream = stream;
}

/* Same for the shared tab/screen audio. Throws with the usual advice when the
   share came back without an audio track, having left the old one running. */
async function attachSystem() {
  const display = await navigator.mediaDevices.getDisplayMedia({
    video: true,
    audio: { echoCancellation: false, noiseSuppression: false },
  });
  const audioTracks = display.getAudioTracks();
  if (!audioTracks.length) {
    display.getTracks().forEach((t) => t.stop());
    throw new Error('no audio in the share — pick a tab or screen AND tick "Also share audio" in the picker');
  }
  // Only the audio is ever used — the picker is unavoidable (that consent
  // dialogue is the only way a browser will hand a page system audio at
  // all), but nothing needs the video, so end that capture immediately
  // rather than leaving the screen/tab actively shared for the whole
  // meeting.
  display.getVideoTracks().forEach((t) => t.stop());
  const src = audioCtx.createMediaStreamSource(new MediaStream(audioTracks));
  sysAnalyser = audioCtx.createAnalyser(); sysAnalyser.fftSize = 1024;
  src.connect(mixedDest); src.connect(analyser); src.connect(sysAnalyser);

  sysSrcNode?.disconnect();
  displayStream?.getTracks().forEach((t) => t.stop());
  sysSrcNode = src; displayStream = display;
  S.systemLost = false;

  // Ending the share no longer ends the meeting. The mic is still recording,
  // and losing the room audio is exactly the fault you would want to fix by
  // re-sharing rather than by starting again.
  audioTracks[0].addEventListener("ended", () => {
    if (displayStream === display && S.running) {
      S.systemLost = true; S.hearSystem = false; emit();
    }
  });
}

/* Dismissing the browser's share or microphone dialogue is a decision, not a
   fault. It used to surface as "Permission denied by user" under SOMETHING
   WENT WRONG, which reads like the app broke. */
function isCancelled(e) {
  return e?.name === "NotAllowedError"
    || /permission denied|dismissed|cancell?ed/i.test(e?.message || "");
}

/* Swap the microphone without interrupting the recording. Before the meeting
   starts this only remembers the choice. */
export async function switchMic(deviceId) {
  S.deviceId = deviceId;
  if (!S.running || !audioCtx) { emit(); return; }
  S.busy = "switching microphone"; emit();
  try {
    await attachMic(deviceId);
    S.error = null;
  } catch (e) {
    if (!isCancelled(e)) S.error = `Could not switch microphone: ${e.message}`;
  }
  S.busy = ""; emit();
}

/* Re-open the screen/tab picker mid-meeting: the fix for shared the wrong tab,
   forgot to tick the audio box, or the share dropped. */
export async function reshareSystem() {
  if (!S.running || !audioCtx) return;
  S.busy = "re-sharing audio"; emit();
  try {
    await attachSystem();
    S.source = "system";
    S.error = null;
  } catch (e) {
    // Changed your mind at the picker: nothing is wrong, and the meeting is
    // still recording whatever it was recording before.
    if (!isCancelled(e)) S.error = e.message;
  }
  S.busy = ""; emit();
}

export async function start() {
  S.error = null; S.note = null;
  chunkNo = 0; langStreak = { lang: "", n: 0 };
  ensureSessionId();
  emit();
  // Fire-and-forget: load the Whisper model and spin up this meeting's
  // persistent tidy/read CLI sessions now, while the user is still granting
  // mic/screen-share permissions, so the first real chunk and first read
  // don't pay that startup cost on top of everything else. Never awaited —
  // a failed or slow warm-up must not delay (or block) recording start.
  post("/api/live/warm", { session_id: S.sessionId }).catch(() => {});
  try {
    audioCtx = new AudioContext();
    mixedDest = audioCtx.createMediaStreamDestination();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024; analyser.smoothingTimeConstant = 0.75;

    await attachMic(S.deviceId);

    if (S.source === "system") {
      try {
        await attachSystem();
      } catch (e) {
        micStream?.getTracks().forEach((t) => t.stop());
        throw e;
      }
    }

    const stream = mixedDest.stream;
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
          // Pin the language only once THREE consecutive chunks agree with
          // high confidence — whisper is routinely confident-and-wrong on a
          // single short chunk, and a wrong pin garbles everything after it.
          // Every 5th chunk re-detects so a mid-meeting language switch is
          // still picked up, and a pinned chunk that hears nothing drops the
          // pin entirely (the pin itself may be what is failing).
          chunkNo++;
          const pin = langStreak.n >= 3 && chunkNo % 5 !== 0 ? langStreak.lang : "auto";
          const res = await postFile(`/api/stt?lang=${encodeURIComponent(pin)}`, blob, "chunk.webm");
          const prob = res.language_probability || 0;
          if (res.language && prob >= 0.9) {
            langStreak = res.language === langStreak.lang
              ? { lang: res.language, n: langStreak.n + 1 }
              : { lang: res.language, n: 1 };
          } else if (pin === "auto") {
            langStreak = { lang: "", n: 0 };   // low-confidence read breaks the streak
          }
          if (res.language) {
            S.detectedLang = res.language;
            S.detectedProb = prob;
            emit();
          }
          if (res.text) hearChunk(res.text);
          else if (pin !== "auto") langStreak = { lang: "", n: 0 };
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
      const isFirstRead = S.reads === 0;
      const cadenceSecs = isFirstRead ? Math.min(S.cadence, FIRST_READ_SECONDS) : S.cadence;
      const minWords = isFirstRead ? FIRST_READ_WORDS : MIN_NEW_WORDS;
      const due = cadenceSecs - (Date.now() - S.lastReadAt) / 1000;
      S.nextIn = Math.max(0, Math.round(due));
      // Per-source "am I hearing it?" indicators, with a 3-second hold.
      const now = Date.now();
      if (levelOf(micAnalyser) > 0.015) lastMicAt = now;
      if (levelOf(sysAnalyser) > 0.015) lastSysAt = now;
      S.hearMic = now - lastMicAt < 3000;
      S.hearSystem = now - lastSysAt < 3000;
      emit();
      if (S.running && !S.reading && due <= 0 && S.unreadWords >= minWords) {
        performRead();
      }
    }, 1000);
  } catch (e) {
    S.error = isCancelled(e)
      ? "Recording not started — the microphone or screen-share prompt was dismissed."
      : `Audio unavailable: ${e.message}`;
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
  mixedDest = null; micSrcNode = null; sysSrcNode = null;
  S.hearMic = false; S.hearSystem = false; S.systemLost = false;
  emit();
  // File the session in the transcript library. The last audio chunk may still
  // be transcribing, so give it a moment to land before the final write.
  if (wasRunning && S.sessionId && S.transcript.trim()) {
    setTimeout(async () => {
      try {
        await tidyDrained();   // let the final chunks finish their Haiku cleanup
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
export function addOwnQuestion(q, starred = true, fromThread = false) {
  const text = (q || "").trim();
  if (!text || S.items.some((it) => it.q === text)) return;
  S.items = [...S.items, {
    id: S.seq++, batch: 0, q: text, flag: false, answer: null, starred,
    fromThread,
  }];
  emit();
}

/* ---- manager thread: the context that follows a manager through the app -- */

export function setManagerContext(thread) {
  if (!thread || !thread.entity) return;
  const previous = S.manager;
  if (previous && previous.entity !== thread.entity) {
    // Switching managers: the OLD thread's prepped questions leave with it —
    // even when the new manager has none prepped. Questions the user typed
    // or that came from reads stay.
    S.items = S.items.filter((it) => !it.fromThread);
    if (S.who === previous.entity) S.who = thread.entity;
  }
  S.manager = thread;
  S.who = S.who || thread.entity;
  (thread.questions || []).forEach((k) => addOwnQuestion(k.q, true, true));
  emit();
  persistLibraryRecord();   // retitle the stored session if one is loaded
  loadPrepDoc(thread);
}

/* The most recent prep this manager thread has on file — fetched so the note
   taker can show it as its own tab instead of making you leave the meeting
   to go read it on the Prep page. Best-effort: no prep on file is the normal
   case for most meetings, not an error. */
async function loadPrepDoc(thread) {
  const preps = (thread?.history || []).filter((h) => h.kind === "prep");
  const latest = preps[preps.length - 1];
  if (!latest) {
    S.prepDoc = null;
    if (S.tab !== "questions") S.tab = "questions";
    emit();
    return;
  }
  S.prepDocLoading = true; emit();
  try {
    S.prepDoc = await get(`/api/preps/${encodeURIComponent(latest.id)}`);
  } catch {
    S.prepDoc = null;
  }
  S.prepDocLoading = false;
  // Don't strand the user on a tab that just lost its content — e.g. the
  // deck tab was showing a previous manager's deck and this one has none.
  if (S.tab === "deck" && !S.prepDoc?.has_deck) S.tab = "questions";
  if (S.tab === "prep" && !S.prepDoc) S.tab = "questions";
  emit();
}

export function setTab(tab) { S.tab = tab; emit(); }
export function setTabWide(wide) { S.tabWide = wide; emit(); }

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

/* True while a just-generated suggestion is still delete-locked. */
export function isFresh(it) {
  return !!it.born && Date.now() - it.born < FRESH_LOCK_MS;
}

export function discardItem(id) {
  const it = S.items.find((x) => x.id === id);
  if (it && isFresh(it)) return;   // just appeared — protect it from the sweep
  S.items = S.items.filter((x) => x.id !== id);
  emit();
}

export function toggleStar(id) {
  S.items = S.items.map((it) =>
    it.id === id ? { ...it, starred: !it.starred } : it);
  emit();
}

let noteAbort = null;

/* Stop a draft in flight. The half-written text goes with it — the point of
   cancelling is to write it again differently. */
export function cancelNote() {
  noteAbort?.abort();
}

export async function draftNote() {
  // One draft at a time. Two in flight race to set S.note, and the second one
  // wins whatever the first was worth.
  if (S.noteBusy) return;
  noteAbort = new AbortController();
  const { signal } = noteAbort;
  S.noteBusy = true; S.busy = "note"; S.error = null;
  S.note = null; S.noteDraftText = "";
  S.panesMin = true;      // the draft takes the floor
  emit();
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
    }, signal);
    if (!md.trim() || md.includes("[[STREAM-FAILED]]")) {
      S.noteDraftText = ""; emit();
      S.note = await post("/api/live/note", payload, signal);   // non-streamed fallback
    } else {
      const fields = await post("/api/live/note-parse", { markdown: md }, signal);
      S.note = { note: fields, markdown: md };
    }
  } catch (e) {
    if (signal.aborted) {
      S.panesMin = false;      // give the questions their room back
    } else {
      // Streaming unavailable at the transport level — fall back quietly.
      try { S.note = await post("/api/live/note", payload, signal); }
      catch (e2) { if (!signal.aborted) S.error = e2.message; }
    }
  }
  noteAbort = null;
  S.noteDraftText = ""; S.noteBusy = false;
  if (S.busy === "note") S.busy = "";
  emit();
  // File the finished note with the session straight away — pressing
  // "Back to start" later must not lose it.
  if (S.note) {
    if (S.running) autosaveNow();
    else if (S.sessionId && S.transcript.trim()) {
      post("/api/live/finish", sessionPayload())
        .then(() => { S.librarySaved = true; emit(); })
        .catch(() => { /* the autosave copy still stands */ });
    }
  }
}

export function newSession() {
  cancelNote();
  stop();
  tidyQueue = []; chunkNo = 0; langStreak = { lang: "", n: 0 };
  Object.assign(S, {
    transcript: "", entries: [], items: [], batches: [], reads: 0, unreadWords: 0,
    lastTail: "", lastReadAt: 0, startedAt: 0, nextIn: S.cadence, error: null,
    detectedLang: "", detectedProb: 0, tidyPending: 0, rawPending: "",
    note: null, noteDraftText: "", sharp: null, sharpPending: "", busy: "", seq: 1, manager: null,
    noteSave: null, noteSaveEdits: {}, noteSaveEditing: {}, noteSaveUrl: "",
    sessionId: "", librarySaved: false, panesMin: false,
    tab: "questions", tabWide: false, prepDoc: null, prepDocLoading: false,
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
  // A note drafted in the original session reappears with it — and the note is
  // what you came back for, so it opens with the questions folded away.
  if (rec.note_markdown) {
    S.note = { note: rec.note_fields || {}, markdown: rec.note_markdown };
    S.panesMin = true;
  }
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
