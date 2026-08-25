/* Store-level regressions for the Felix review flow.

   Shipped bug covered here: S.busy was one global string, so approving a
   second change while the first approval was still in flight overwrote the
   key — the first row's pinwheel stopped mid-request and its buttons came
   back alive (double-submit risk). Reviews now track in-flight state per
   change+action in a Set. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api.js", () => ({
  get: vi.fn(),
  post: vi.fn(),
}));

let api, fx;

function gated() {
  let release;
  const promise = new Promise((resolve) => { release = resolve; });
  return { promise, release };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(async () => {
  vi.resetModules();
  api = await import("./api.js");
  fx = await import("./felixStore.js");
  api.get.mockReset();
  api.post.mockReset();
  // review() refreshes the list and status afterwards; keep those quiet.
  api.get.mockResolvedValue({ changes: [], stats: {} });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("concurrent reviews", () => {
  it("keeps each change's spinner alive independently", async () => {
    const a = gated(), b = gated();
    api.post
      .mockReturnValueOnce(a.promise)
      .mockReturnValueOnce(b.promise);

    const first = fx.review("FLX-1", "approve");
    const second = fx.review("FLX-2", "approve");
    expect(fx.isReviewBusy("FLX-1", "approve")).toBe(true);
    expect(fx.isReviewBusy("FLX-2", "approve")).toBe(true);

    a.release({ execution_status: "Applied" });
    await first;
    // The first finishing must not clear the second's spinner (the old
    // global string did exactly that).
    expect(fx.isReviewBusy("FLX-1", "approve")).toBe(false);
    expect(fx.isReviewBusy("FLX-2", "approve")).toBe(true);
    expect(fx.isRowBusy("FLX-2")).toBe(true);

    b.release({ execution_status: "Applied" });
    await second;
    expect(fx.isReviewBusy("FLX-2", "approve")).toBe(false);
    expect(fx.S.reviewing.size).toBe(0);
  });

  it("a failed review clears only its own key", async () => {
    const a = gated(), b = gated();
    api.post
      .mockReturnValueOnce(a.promise)
      .mockReturnValueOnce(b.promise);
    const first = fx.review("FLX-1", "approve");
    const second = fx.review("FLX-2", "dismiss");

    a.release(Promise.reject(new Error("boom")));
    await first;
    expect(fx.isReviewBusy("FLX-1", "approve")).toBe(false);
    expect(fx.S.error).toBe("boom");
    expect(fx.isReviewBusy("FLX-2", "dismiss")).toBe(true);

    b.release({ execution_status: "Applied" });
    await second;
    expect(fx.S.reviewing.size).toBe(0);
  });

  it("ignores a second action on a row already mid-request", async () => {
    const a = gated();
    api.post.mockReturnValueOnce(a.promise);
    const first = fx.review("FLX-1", "approve");
    await fx.review("FLX-1", "dismiss");   // returns without posting
    expect(api.post).toHaveBeenCalledTimes(1);
    a.release({ execution_status: "Applied" });
    await first;
  });
});

describe("merge overrides", () => {
  it("sends field corrections only when the reviewer made some", async () => {
    api.post.mockResolvedValue({ execution_status: "Applied" });
    await fx.review("FLX-1", "approve", "pa", null, { Title: "Head of IR" });
    expect(api.post).toHaveBeenCalledWith("/api/felix/changes/FLX-1/review",
      { action: "approve", survivor_id: "pa", overrides: { Title: "Head of IR" } });
    await fx.review("FLX-2", "approve", "", null, {});
    expect(api.post).toHaveBeenLastCalledWith("/api/felix/changes/FLX-2/review",
      { action: "approve", survivor_id: "" });
  });
});

describe("undo jobs", () => {
  it("attaches to the returned job until the undo result is refreshed", async () => {
    vi.useFakeTimers();
    try {
      api.post.mockResolvedValue({
        review_status: "Undo Requested",
        job: { id: "undo-job" },
      });
      api.get.mockImplementation((url) => {
        if (url === "/api/jobs/undo-job") {
          return Promise.resolve({ id: "undo-job", status: "running", stages: [] });
        }
        if (url === "/api/jobs/undo-job/partial") {
          return Promise.resolve({ partial: { events: [] } });
        }
        return Promise.resolve({ changes: [], stats: {} });
      });

      await fx.review("FLX-undo", "undo");
      await vi.advanceTimersByTimeAsync(2000);

      expect(api.post).toHaveBeenCalledWith(
        "/api/felix/changes/FLX-undo/review",
        { action: "undo", survivor_id: "" });
      expect(api.get).toHaveBeenCalledWith("/api/jobs/undo-job");
      expect(api.get).toHaveBeenCalledWith("/api/jobs/undo-job/partial");
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });
});

describe("list refresh races", () => {
  it("a slower stale fetch never overwrites a fresher one", async () => {
    const stale = gated(), fresh = gated();
    api.get
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);

    const first = fx.fetchChanges();
    const second = fx.fetchChanges();
    fresh.release({ changes: [{ change_id: "new" }] });
    await second;
    stale.release({ changes: [{ change_id: "old" }] });
    await first;
    await tick();
    expect(fx.S.changes.map((c) => c.change_id)).toEqual(["new"]);
  });
});
