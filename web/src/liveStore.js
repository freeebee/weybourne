/* Live-meeting session store — lives at module scope, OUTSIDE React, so the
   audio pipeline, timers and transcript keep running when the user navigates
   to another page. The Live page (and the sidebar chip) subscribe to it. */
import { post, postFile } from "./api.js";

const CHUNK_MS = 8000;          // recorder restart interval → self-contained blobs
export const CADENCE_S = 30;    // read the new speech every 30 seconds
const MIN_NEW_WORDS = 5;

export const S = {
  running: false, who: "", goal: "", source: "system", deviceId: "",
  transcript: "", items: [], batches: [], reads: 0, unreadWords: 0,
  lastTail: "", lastReadAt: 0, reading: false, nextIn: CADENCE_S,
  error: null, note: null, sharp: null, busy: "", seq: 1, version: 0,
};

let listeners = new Set();
let micStream = null, displayStream = null, audioCtx = null, analyser = null,
    recorder = null, chunkTimer = null, countdown = null, raf = 0, canvas = null;

function emit() { S.version++; listeners.forEach((f) => f()); }
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function getVersion() { return S.version; }

export function set(patch) { Object.assign(S, patch); emit(); }

function context() {
  return [S.who ? `Meeting with ${S.who}.` : "", S.goal].filter(Boolean).join(" ");
}

export function attachCanvas(el) { canvas = el; }

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
      S.items = [...S.items, ...(parsed.questions || []).map((q) => ({
        id: S.seq++, batch: bid, q: q.q, flag: !!q.flag, answer: null,
      }))];
    }
  } catch (e) { S.error = e.message; }
  S.reading = false; S.busy = ""; emit();
}

// ---- audio pipeline ------------------------------------------------------- //

export async function start() {
  S.error = null; S.note = null; emit();
  try {
    audioCtx = new AudioContext();
    const mixed = audioCtx.createMediaStreamDestination();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024; analyser.smoothingTimeConstant = 0.75;

    micStream = await navigator.mediaDevices.getUserMedia({
      audio: S.deviceId ? { deviceId: { exact: S.deviceId } } : true,
    });
    const micSrc = audioCtx.createMediaStreamSource(micStream);
    micSrc.connect(mixed); micSrc.connect(analyser);

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
      sysSrc.connect(mixed); sysSrc.connect(analyser);
      audioTracks[0].addEventListener("ended", () => stop());
    }

    const stream = mixed.stream;
    S.running = true; S.lastReadAt = Date.now(); emit();
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
            S.unreadWords += text.split(/\s+/).length;
            emit();
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
  S.running = false;
  clearTimeout(chunkTimer); clearInterval(countdown);
  cancelAnimationFrame(raf);
  if (recorder && recorder.state !== "inactive") recorder.stop();
  micStream?.getTracks().forEach((t) => t.stop()); micStream = null;
  displayStream?.getTracks().forEach((t) => t.stop()); displayStream = null;
  audioCtx?.close().catch(() => {}); audioCtx = null; analyser = null;
  emit();
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
    const bh = Math.max(2, v * (h - 8));
    ctx.fillStyle = v > 0.02 ? "#249692" : "#D3C9B4";
    ctx.fillRect(i * bw + 1, (h - bh) / 2, bw - 2, bh);
  }
}

// ---- user actions --------------------------------------------------------- //

export async function addPaste(text, read) {
  S.transcript += (S.transcript ? " " : "") + text;
  S.unreadWords += text.split(/\s+/).length;
  emit();
  if (read) await performRead();
}

export async function sharpen(rough) {
  S.busy = "sharpen"; S.error = null; emit();
  try {
    S.sharp = await post("/api/live/sharpen", {
      transcript: S.transcript, rough, context: context(),
    });
  } catch (e) { S.error = e.message; }
  S.busy = ""; emit();
}

export function keepSharp() {
  const sharp = S.sharp;
  if (!sharp) return;
  S.items = [...S.items, {
    id: S.seq++, batch: 0, q: sharp.question, flag: false,
    answer: sharp.status === "answered" ? sharp.evidence : null,
  }];
  S.sharp = null; emit();
}

export function dropSharp() { S.sharp = null; emit(); }

export function discardItem(id) {
  S.items = S.items.filter((it) => it.id !== id);
  emit();
}

export async function draftNote() {
  S.busy = "note"; S.error = null; emit();
  try {
    S.note = await post("/api/live/note", {
      transcript: S.transcript, context: context(),
      unanswered: S.items.filter((it) => !it.answer).map((it) => it.q),
    });
  } catch (e) { S.error = e.message; }
  S.busy = ""; emit();
}

export function newSession() {
  stop();
  Object.assign(S, {
    transcript: "", items: [], batches: [], reads: 0, unreadWords: 0,
    lastTail: "", lastReadAt: 0, nextIn: CADENCE_S, error: null, note: null,
    sharp: null, busy: "", seq: 1,
  });
  emit();
}
