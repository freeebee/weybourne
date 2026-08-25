import { describe, expect, it } from "vitest";

import { filterReviewRows } from "./FixItFelix.jsx";

const row = (change_id, category, execution_status = "Proposed",
             review_status = "Awaiting Review", recommendation_kind = "") => ({
  change_id, category, execution_status, review_status, recommendation_kind,
});

describe("Felix review views", () => {
  it("keeps settled rows out of All errors", () => {
    const rows = [
      row("open-easy", "easy"),
      row("open-confident", "confident"),
      row("open-research", "needs_research"),
      row("already-applied", "easy", "Applied"),
      row("already-approved", "confident", "Proposed", "Approved"),
      row("already-dismissed", "needs_research", "Proposed", "Dismissed"),
      row("filed", "easy", "Proposed", "Deferred"),
      row("undone", "easy", "Undone"),
      row("needs-decision", "needs_research", "Recommended",
          "Awaiting Review", "action_required"),
      row("not-yet-actionable", "needs_research", "Recommended",
          "Awaiting Review", "research_queued"),
      row("audit-note", "needs_research", "Recommended",
          "Awaiting Review", "informational"),
    ];

    // "needs-decision" is Recommended (approve only files it away), so it
    // now rides with the one-click fixes rather than needs-your-okay.
    expect(filterReviewRows(rows, "all_open").map((r) => r.change_id))
      .toEqual(["open-research", "open-easy", "open-confident", "needs-decision"]);
  });

  it("also keeps applied rows out of One-click fixes", () => {
    const rows = [
      row("open", "easy"),
      row("applied", "easy", "Applied"),
    ];

    expect(filterReviewRows(rows, "easy").map((r) => r.change_id))
      .toEqual(["open"]);
  });

  it("gives queued research its own non-actionable view", () => {
    const rows = [
      row("decision", "needs_research", "Recommended",
          "Awaiting Review", "action_required"),
      row("queued", "needs_research", "Recommended",
          "Awaiting Review", "research_queued"),
      row("note", "needs_research", "Recommended",
          "Awaiting Review", "informational"),
    ];

    // A file-away flag is one-click work, never a needs-your-okay decision.
    expect(filterReviewRows(rows, "Awaiting Review").map((r) => r.change_id))
      .toEqual([]);
    expect(filterReviewRows(rows, "easy").map((r) => r.change_id))
      .toEqual(["decision"]);
    expect(filterReviewRows(rows, "research_queued").map((r) => r.change_id))
      .toEqual(["queued"]);
  });

  it("treats a researched-DISTINCT pair as a decision, not a note", () => {
    // Informational in kind (the pair is settled server-side at filing) but
    // it still asks the user to approve keep-separate or overrule and merge.
    const distinct = {
      ...row("distinct", "needs_research", "Recommended",
             "Awaiting Review", "informational"),
      change_type: "recommendation",
      property_changed: "(possible duplicate)",
      reason: "researched online: DISTINCT from 'Wes T.' — different firms",
    };
    const note = {
      ...row("plain-note", "needs_research", "Recommended",
             "Awaiting Review", "informational"),
      change_type: "recommendation",
      property_changed: "Employed By",
      reason: "audit note",
    };

    expect(filterReviewRows([distinct, note], "Awaiting Review")
      .map((r) => r.change_id)).toEqual(["distinct"]);
    expect(filterReviewRows([distinct, note], "all_open")
      .map((r) => r.change_id)).toEqual(["distinct"]);
  });
});
