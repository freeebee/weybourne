/* The note taker's store, which until now had no tests at all.

   Every bug these cover shipped: heard speech deleted by an empty cleanup,
   a recap read clearing the note draft's busy flag, and a second draft
   startable on top of the first. The store is plain module state, so it can be
   driven directly — no DOM, no React. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api.js", () => ({
  get: vi.fn(async () => ({})),
  getRetry: vi.fn(async () => ({})),
  del: vi.fn(async () => ({})),
  post: vi.fn(async () => ({})),
  postFile: vi.fn(async () => ({})),
  postStream: vi.fn(async () => ""),
}));

const api = await import("./api.js");
const live = await import("./liveStore.js");

const S = live.S;

/* A fresh store for each test. */
beforeEach(() => {
  vi.clearAllMocks();
  api.post.mockResolvedValue({});
  api.postStream.mockResolvedValue("");
  live.newSession();
});

afterEach(() => {
  live.newSession();
});

/* hearChunk is what the recorder calls when whisper returns text; waiting for
   tidyPending to reach zero waits for the cleanup round trip behind it. */
async function hear(raw) {
  live.hearChunk(raw);
  await vi.waitFor(() => expect(S.tidyPending).toBe(0));
}

describe("the cleanup never deletes what was heard", () => {
  it("keeps the cleaned text when the cleanup returns some", async () => {
    api.post.mockResolvedValue({ text: "We closed Fund II at $210m." });
    await hear("we closed fund two at two hundred and ten million");
    expect(S.transcript).toBe("We closed Fund II at $210m.");
  });

  it("falls back to the raw text when the cleanup returns empty", async () => {
    // Haiku returning "" means "no speech in this chunk". Taking that at face
    // value dropped real speech, and with it the recaps and the questions.
    api.post.mockResolvedValue({ text: "" });
    await hear("the fund is targeting three hundred million");
    expect(S.transcript).toBe("the fund is targeting three hundred million");
  });

  it("falls back to the raw text when the cleanup call fails", async () => {
    api.post.mockRejectedValue(new Error("HTTP 503"));
    await hear("eight people in singapore");
    expect(S.transcript).toBe("eight people in singapore");
  });

  it("counts the words as they are heard, not once they are cleaned", async () => {
    api.post.mockResolvedValue({ text: "Four words right here." });
    await hear("four words right here");
    expect(S.unreadWords).toBe(4);
  });
});

describe("the read that produces the recap and the questions", () => {
  beforeEach(() => {
    api.post.mockImplementation(async (url) => {
      if (url === "/api/live/tidy") return { text: "" };
      return { changed: true, recap: "They gave the target size.",
               answered: [], questions: [{ q: "How is that funded?", flag: true }] };
    });
  });

  it("produces a recap from speech the cleanup could not clean", async () => {
    /* The whole failure in one test: an empty cleanup used to leave the
       transcript empty, and performRead returned on its first line. */
    await hear("they are targeting three hundred million for fund three");
    await live.performRead();
    expect(S.batches[0].recap).toBe("They gave the target size.");
    expect(S.items).toHaveLength(1);
  });

  it("does nothing when there is no speech at all", async () => {
    await live.performRead();
    expect(S.batches).toHaveLength(0);
    expect(api.post).not.toHaveBeenCalledWith("/api/live/read", expect.anything());
  });

  it("clears the unread count so the next read waits for new speech", async () => {
    await hear("some words were said here");
    await live.performRead();
    expect(S.unreadWords).toBe(0);
  });
});

describe("writing the note", () => {
  /* A draft that never resolves until the test says so. */
  function pendingDraft() {
    let release;
    const gate = new Promise((r) => { release = r; });
    api.postStream.mockImplementation(async (_u, _b, _c, signal) => {
      await gate;
      if (signal?.aborted) throw Object.assign(new Error("aborted"), { name: "AbortError" });
      return "# Note\n\nThey said things.";
    });
    return () => { release(); };
  }

  it("cannot be started twice", async () => {
    const finish = pendingDraft();
    const first = live.draftNote();
    await live.draftNote();                    // the accidental second click
    expect(api.postStream).toHaveBeenCalledTimes(1);
    finish();
    await first;
  });

  it("survives a recap read finishing mid-draft", async () => {
    /* This is what made the note look like it had stopped: performRead set
       S.busy back to "" and the draft panel, which keyed off busy, vanished. */
    const finish = pendingDraft();
    const draft = live.draftNote();
    expect(S.noteBusy).toBe(true);
    S.transcript = "something was said";
    await live.performRead();
    expect(S.noteBusy).toBe(true);
    finish();
    await draft;
    expect(S.noteBusy).toBe(false);
  });

  it("folds the questions away while it writes", async () => {
    const finish = pendingDraft();
    const draft = live.draftNote();
    expect(S.panesMin).toBe(true);
    finish();
    await draft;
    expect(S.panesMin).toBe(true);             // still folded: the note has the floor
  });

  it("can be cancelled, and gives the questions their room back", async () => {
    const finish = pendingDraft();
    const draft = live.draftNote();
    live.cancelNote();
    finish();
    await draft;
    expect(S.noteBusy).toBe(false);
    expect(S.note).toBeNull();
    expect(S.panesMin).toBe(false);
    expect(S.error).toBeNull();                // cancelling is a decision, not a fault
  });

  it("can be started again after a cancel", async () => {
    const finish = pendingDraft();
    const draft = live.draftNote();
    live.cancelNote();
    finish();
    await draft;
    api.postStream.mockResolvedValue("# Note\n\nSecond attempt.");
    api.post.mockResolvedValue({ title: "Meeting" });
    await live.draftNote();
    expect(S.note.markdown).toContain("Second attempt");
  });
});
