/* Fix-it Felix — the Notion clean-up agent's workshop. The scene is theatre;
   the change log below is the record. Floating "fixed!" labels come only from
   real change events. */
import React from "react";
import * as fx from "../felixStore.js";
import PixelOfficeScene, {
  CleanupHud, StationStrip, StatusConsole,
} from "./PixelOffice.jsx";
import {
  Banner, Button, Card, Chip, ErrorNote, PageHeader, SectionHead,
  fmtDT, inputStyle,
} from "../ui.jsx";

function RunPanel({ s }) {
  const job = s.runJob;
  const running = job?.status === "running";
  const cfg = s.status || {};
  const cap = cfg.max_findings || 10;
  if (running) {
    const left = Math.max(0, (job.eta || 0) - (job.elapsed || 0));
    return (
      <Card accent="teal" style={{ marginBottom: 18 }}>
        <div className="spread">
          <span className="microlabel">
            RUNNING · {job.label?.toUpperCase()} · {job.elapsed}S ELAPSED ·
            {left > 0 ? ` ~${left}S LEFT` : " OVERRUNNING"}
          </span>
          <Button variant="ghost" onClick={fx.cancelRun}>Stop Felix</Button>
        </div>
        {(job.stages || []).slice(-4).map((st, i, arr) => (
          <div key={i} style={{ fontSize: "13px", marginTop: 5 }}>
            <span style={{ color: i === arr.length - 1 ? "var(--teal-700)"
                             : "var(--positive-600)", marginRight: 7 }}>
              {i === arr.length - 1 ? "›" : "✓"}
            </span>
            {st.label}{st.detail ? ` — ${st.detail}` : ""}
          </div>
        ))}
      </Card>
    );
  }
  return (
    <Card style={{ marginBottom: 18 }}>
      <div className="spread" style={{ flexWrap: "wrap", gap: 10 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Button busy={s.busy === "start"} onClick={() => fx.startRun({})}>
            Run Felix
          </Button>
          {!cfg.live && <Chip tone="neutral">NOTION: DEMO DATA</Chip>}
        </div>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".1em",
                color: "var(--stone-500)" }}>
          STOPS AT {cap} FOR APPROVAL · RESTARTS WHEN THE QUEUE IS CLEAR
        </span>
      </div>
      <PendingResearch s={s} />
      {s.lastResult && (
        <div style={{ marginTop: 12, borderTop: "1px solid var(--paper-200)",
                      paddingTop: 10, display: "flex", gap: 16, flexWrap: "wrap" }}>
          {Object.entries(s.lastResult.counts || {})
            .filter(([, v]) => v > 0)
            .map(([k, v]) => (
              <span key={k} className="mono" style={{ fontSize: 10.5,
                    letterSpacing: ".08em", color: "var(--stone-500)" }}>
                {k.replaceAll("_", " ").toUpperCase()} <b style={{ color: "var(--ink-700)" }}>{v}</b>
              </span>
            ))}
        </div>
      )}
    </Card>
  );
}

/* What the last run could not settle from the meeting notes. Web searches
   cost real time and tokens, so they are never spent automatically — this
   says exactly what would be looked up, and waits to be asked. */
const PENDING_LABEL = {
  employer: ["contact", "no employer, and the notes do not say who they work for"],
  contact_field: ["contact", "missing details the notes do not cover"],
  fund_company: ["fund", "no manager linked, and the notes do not name one"],
  fund_tags: ["fund", "missing asset class or geography"],
  duplicate: ["possible duplicate", "needs checking against the record online"],
};

function PendingResearch({ s }) {
  const p = s.status?.pending_research;
  const [open, setOpen] = React.useState(false);
  // Say so when there is nothing to look up, rather than hiding the whole
  // mechanism — otherwise the web search looks like it does not exist.
  if (!p || !p.total) {
    if (!s.lastResult) return null;
    return (
      <div style={{ marginTop: 12, borderTop: "1px solid var(--paper-200)",
                    paddingTop: 11, display: "flex", gap: 12, flexWrap: "wrap",
                    alignItems: "center" }}>
        <span className="muted" style={{ fontSize: "12.5px" }}>
          Nothing is waiting on the web — the last run settled everything from
          your notes and records.
        </span>
        <Button variant="ghost"
          busy={s.busy === "search" || s.runJob?.status === "running"}
          onClick={() => fx.startRun({ webResearch: true })}>
          Run with web searches anyway
        </Button>
      </div>
    );
  }
  const searching = s.busy === "search" || s.runJob?.status === "running";
  return (
    <div style={{ marginTop: 12, borderTop: "1px solid var(--paper-200)",
                  paddingTop: 11 }}>
      <div className="spread" style={{ gap: 12, flexWrap: "wrap" }}>
        <div>
          <span className="microlabel" style={{ color: "var(--caution-600)" }}>
            {p.total} THING{p.total === 1 ? "" : "S"} THE NOTES COULD NOT SETTLE
          </span>
          <div style={{ fontSize: "13px", marginTop: 4 }}>
            {p.groups.map((g, i) => {
              const [noun] = PENDING_LABEL[g.kind] || [g.kind];
              return (
                <span key={g.kind}>
                  {i > 0 ? " · " : ""}
                  <b>{g.count}</b> {noun}{g.count === 1 ? "" : "s"}
                </span>
              );
            })}
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <Button variant="ghost" onClick={() => setOpen(!open)}>
            {open ? "Hide the list" : "See the list"}
          </Button>
          <Button variant="dark" busy={searching}
            onClick={() => fx.startRun({ webResearch: true })}>
            {searching ? "Searching…" : "Search the web for these"}
          </Button>
        </div>
      </div>
      {open && (
        <div style={{ marginTop: 10 }}>
          {p.groups.map((g) => {
            const [noun, why] = PENDING_LABEL[g.kind] || [g.kind, ""];
            return (
              <div key={g.kind} style={{ marginBottom: 9 }}>
                <div className="mono" style={{ fontSize: 9.5, letterSpacing: ".1em",
                      color: "var(--stone-500)" }}>
                  {noun.toUpperCase()}S — {why}
                </div>
                {g.records.map((r, i) => (
                  <div key={i} style={{ fontSize: "12.5px", padding: "2px 0" }}>
                    {r.url
                      ? <a href={r.url} target="_blank" rel="noreferrer"
                           style={{ color: "var(--teal-700)" }}>{r.name}</a>
                      : r.name}
                    {r.field && (
                      <span className="muted"> — {r.field}</span>
                    )}
                    {r.detail && (
                      <span className="muted"> — {r.detail}</span>
                    )}
                  </div>
                ))}
                {g.count > g.records.length && (
                  <div className="muted" style={{ fontSize: "12px" }}>
                    …and {g.count - g.records.length} more
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* Each change in plain words: what was wrong, what Felix did (or suggests),
   and one Approve / Discard choice. Merge sub-steps are folded into their
   parent rather than listed. */
function describeChange(c) {
  const q = (v) => `“${v}”`;
  const done = c.execution_status === "Applied";
  // What pressing Approve will actually DO — stated on every row so there is
  // never any guessing.
  const isDupRec = c.change_type === "recommendation"
    && (c.property_changed || "").includes("duplicate");
  const isDistinct = isDupRec && (c.reason || "").includes("DISTINCT");
  const approve = done
    ? "Approve files it as reviewed (it is already done). Discard undoes it in Notion."
    : c.change_type === "merge"
      ? "Approve merges the pair in Notion right now: data moves to the kept copy, links repoint, the duplicate is archived (undoable in one click). Discard files them as not duplicates — nothing changes."
      : c.change_type === "create_company"
      ? `Approve creates ${q(c.new_value)} in Companies and links this record to it, right now. The name is re-checked against every existing company first. Discard drops it.`
      : c.change_type === "add_photo"
      ? "Approve puts the photo into this contact's Notion page, right now. Discard drops it."
      : isDistinct
        ? "Approve accepts the research: the two records stay separate and the pair is never flagged again. Discard just files this row away."
        : isDupRec
          ? "Approve merges the pair in Notion right now: the richer record is kept, the other's data moves over, links repoint, and the duplicate is archived (undoable). Discard files them as NOT duplicates — never flagged again, nothing written."
          : c.new_value && c.property_changed && c.execution_status !== "Recommended"
            ? `Approve writes ${c.property_changed} = ${q(c.new_value)} to this record in Notion, right now. Discard drops it.`
            : "Approve only files this away as seen — nothing is written to Notion. Discard drops it.";
  const base = (() => {
    switch (c.change_type) {
      case "fix_formatting":
        return { problem: `Untidy text in ${c.property_changed} — ${c.reason || "stray spaces or casing"}.`,
                 fix: `${done ? "Changed" : "Will change"} ${q(c.previous_value)} to ${q(c.new_value)}.` };
      case "fill_missing":
        return { problem: `${c.property_changed} was empty.`,
                 fix: `${done ? "Filled it in with" : "Will fill it in with"} ${q(c.new_value)}.`,
                 source: c.source };
      case "fix_relation":
        return { problem: `${c.property_changed} pointed at a record that no longer exists.`,
                 fix: `${done ? "Removed" : "Will remove"} the dead link and ${done ? "kept" : "keep"} the valid ones.` };
      case "fix_icon":
        return { problem: "The page had no icon.",
                 fix: `${done ? "Added" : "Will add"} the standard ${q(c.new_value)} icon.` };
      case "create_company":
        return { problem: `${c.property_changed} was empty, and the company it should point to is not in the workspace yet.`,
                 fix: done
                   ? `Created ${q(c.new_value)} in Companies and linked it.`
                   : `Will create ${q(c.new_value)} in Companies and link it here. The name is checked against every existing company again first, so it cannot make a second copy.`,
                 source: c.source };
      case "add_photo":
        return { problem: "The contact page has no photo.",
                 fix: done ? "Added their profile photo to the page."
                           : "Will add their profile photo to the top of the page body.",
                 source: c.source };
      case "merge":
        return { problem: "This record exists twice — a duplicate.",
                 fix: done
                   ? "Merged everything into the richer copy and archived this one. Nothing was lost, and it can be unwound in one click."
                   : "Will merge everything into the richer copy and archive this one. Nothing gets lost, and it can be unwound in one click.",
                 source: c.source };
      case "recommendation":
        return { problem: c.reason || "Something needs your judgement.",
                 fix: c.new_value ? `Suggestion: ${c.new_value}` :
                      "Nothing was changed — this one is your call.",
                 source: c.source };
      default:
        return { problem: c.reason || c.change_type.replaceAll("_", " "),
                 fix: c.new_value ? `${q(c.previous_value || "(empty)")} → ${q(c.new_value)}` : "" };
    }
  })();
  return { ...base, approve };
}

/* The two records of a proposed merge, side by side — everything each copy
   holds, what moves over, and any conflicting values — so approving needs no
   digging around in Notion. */
function MergeCompare({ detail, done, keepId, onPick }) {
  let d;
  try { d = JSON.parse(detail); } catch { return null; }
  if (!d || !d.keep || !d.archive) return null;
  // Older rows carry no per-record id; keep is pair[0], archive is pair[1].
  const idOf = (rec, i) => rec.id || (d.pair || [])[i] || "";
  const pickable = !!onPick && !done;
  const col = (rec, label, tone, i) => {
    const id = idOf(rec, i);
    const chosen = pickable && keepId === id;
    const other = pickable && keepId && keepId !== id;
    return (
    <div onClick={pickable ? () => onPick(id) : undefined}
         role={pickable ? "button" : undefined}
         tabIndex={pickable ? 0 : undefined}
         onKeyDown={pickable ? (e) => {
           if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(id); }
         } : undefined}
         style={{ flex: "1 1 220px", minWidth: 200, padding: "8px 11px",
                  background: chosen ? "var(--teal-050, #EAF4F3)"
                    : other ? "var(--paper-100)" : "var(--paper-050)",
                  border: `1px solid ${chosen ? "var(--teal-500)" : "var(--paper-200)"}`,
                  borderTop: `2px solid ${chosen ? "var(--teal-500)" : `var(${tone})`}`,
                  borderRadius: 4,
                  opacity: other ? 0.62 : 1,
                  cursor: pickable ? "pointer" : "default",
                  transition: "background .15s ease, opacity .15s ease, border-color .15s ease" }}>
      <div className="mono" style={{ fontSize: 9.5, letterSpacing: ".1em",
                                     color: chosen ? "var(--teal-700)" : "var(--stone-500)" }}>
        {chosen ? "KEEPING THIS ONE" : other ? "WILL BE ARCHIVED" : label}
      </div>
      <b style={{ fontSize: "13px" }}>{rec.name}</b>
      {rec.created && (
        <span className="mono" style={{ fontSize: 9.5, marginLeft: 6,
                                        color: "var(--stone-400)" }}>
          SINCE {rec.created}
        </span>
      )}
      <div style={{ marginTop: 5 }}>
        {Object.keys(rec.fields || {}).length === 0 && (
          <div className="muted" style={{ fontSize: "12px", fontStyle: "italic" }}>
            No other fields filled in.
          </div>
        )}
        {Object.entries(rec.fields || {}).map(([k, v]) => (
          <div key={k} style={{ fontSize: "12px", marginBottom: 2 }}>
            <span className="mono" style={{ fontSize: 9.5, letterSpacing: ".06em",
                                            color: "var(--stone-500)" }}>
              {k.toUpperCase()}
            </span>{" "}{v}
          </div>
        ))}
        {/* Meeting history is the strongest signal of which copy is real. */}
        <div style={{ fontSize: "12px", marginTop: 4, paddingTop: 4,
                      borderTop: "1px solid var(--paper-200)" }}>
          <span className="mono" style={{ fontSize: 9.5, letterSpacing: ".06em",
                                          color: "var(--stone-500)" }}>
            LINKED NOTES
          </span>{" "}
          {rec.note_count
            ? `${rec.note_count} — ${(rec.notes || []).join(", ")}`
            : <span className="muted" style={{ fontStyle: "italic" }}>
                none
              </span>}
        </div>
      </div>
    </div>
    );
  };
  return (
    <div style={{ marginTop: 8 }}>
      {pickable && (
        <div className="mono" style={{ fontSize: 9.5, letterSpacing: ".08em",
                                       color: "var(--stone-500)", marginBottom: 5 }}>
          CLICK THE COPY TO KEEP — THE OTHER IS ARCHIVED
        </div>
      )}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {col(d.keep, done ? "KEPT — THE RICHER COPY" : "FELIX WOULD KEEP THIS",
             "--positive-600", 0)}
        {col(d.archive, done ? "ARCHIVED — THE DUPLICATE" : "WOULD BE ARCHIVED",
             "--caution-600", 1)}
      </div>
      {d.web_check && (
        <div style={{ fontSize: "12px", marginTop: 6,
                      color: d.web_check.startsWith("not yet")
                        ? "var(--caution-600)" : "var(--stone-600)" }}>
          <span className="mono" style={{ fontSize: 9.5, letterSpacing: ".08em",
                                          color: "var(--stone-500)" }}>
            ONLINE CHECK
          </span>{" "}{d.web_check}
        </div>
      )}
      {(d.moves || []).length > 0 && (
        <div style={{ fontSize: "12px", marginTop: 6 }}>
          <span style={{ color: "var(--teal-700)", fontWeight: 600 }}>Moves over: </span>
          {d.moves.join(", ")} — nothing on the archived copy is lost.
        </div>
      )}
      {(d.conflicts || []).map((cf) => (
        <div key={cf.property} style={{ fontSize: "12px", marginTop: 3,
                                        color: "var(--caution-600)" }}>
          Both records fill {cf.property}: keeping “{cf.keep}”, the duplicate’s
          “{cf.loses}” is logged here but not written.
        </div>
      ))}
    </div>
  );
}

const STATUS_WORDS = {
  "Applied": ["FIXED", "positive"],
  "Planned (dry-run)": ["READY — APPROVE TO FIX", "teal"],
  "Proposed": ["PROPOSED — YOUR CALL", "caution"],
  "Recommended": ["SUGGESTION", "caution"],
  "Failed": ["COULDN'T FIX", "critical"],
  "Undone": ["UNDONE", "neutral"],
  "Skipped": ["SKIPPED", "neutral"],
  "Pending": ["IN PROGRESS", "teal"],
};

/* High-confidence mechanical rows — the ones Felix would do unattended in
   live mode. They get their own EASY FIXES view with a fix-everything button;
   everything needing judgement stays under NEEDS YOUR OKAY. */
const EASY_TYPES = ["fix_formatting", "fix_icon", "fix_relation"];
const isEasyFix = (c) => c.confidence === "High"
  && EASY_TYPES.includes(c.change_type);

/* A row can join a bulk approval only while it is still an open question —
   once decided (or already written to Notion) there is nothing left to queue. */
const isAwaiting = (c) => c.review_status === "Awaiting Review";

function ReviewTable({ s }) {
  const f = s.changesFilter;
  const [bulkDone, setBulkDone] = React.useState(0);
  const [bulkTotal, setBulkTotal] = React.useState(0);
  // Multi-select for approving several findings at once. A Set of change_ids
  // rather than page state per row, so it survives re-renders as new events
  // stream in without needing to touch every ChangeRow.
  const [picked, setPicked] = React.useState(() => new Set());
  const setF = (patch) => { setPicked(new Set()); fx.fetchChanges({ ...f, ...patch }); };
  const sel = (key, opts) => (
    <select value={f[key] || ""} style={{ ...inputStyle, width: "auto", padding: "5px 8px" }}
      onChange={(e) => setF({ [key]: e.target.value })}>
      {opts.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
    </select>
  );
  const all = s.changes.filter((c) => !c.parent_change_id);
  // Something already written to Notion is not waiting on your okay, whatever
  // its review flag says — it belongs under "Already fixed", where it can
  // still be undone. Leaving applied merges in this lane made the queue read
  // as work outstanding when the work was done.
  const rows = f.review === "easy" ? all.filter(isEasyFix)
    : f.review === "Awaiting Review"
      ? all.filter((c) => !isEasyFix(c) && c.execution_status !== "Applied")
    : f.review === "done" ? all.filter((c) => c.execution_status === "Applied")
    : all;
  // A row that scrolled out of view (superseded, applied elsewhere, filtered
  // away) drops out of the selection rather than queueing a decision on
  // something no longer on screen.
  const selectableIds = new Set(rows.filter(isAwaiting).map((c) => c.change_id));
  React.useEffect(() => {
    setPicked((p) => {
      const next = new Set([...p].filter((id) => selectableIds.has(id)));
      return next.size === p.size ? p : next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows.map((c) => c.change_id).join(",")]);
  const togglePick = (id) => setPicked((p) => {
    const next = new Set(p);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });
  const allPicked = selectableIds.size > 0 && picked.size === selectableIds.size;
  const toggleAll = () => setPicked(allPicked ? new Set() : new Set(selectableIds));

  const fixAll = async () => {
    const list = [...rows];
    setBulkTotal(list.length); setBulkDone(0);
    for (const c of list) {
      await fx.review(c.change_id, "approve");
      setBulkDone((n) => n + 1);
    }
    setBulkTotal(0);
  };
  // The picked rows, in the order they are currently shown — queued one at a
  // time (fx.review already serialises via S.busy) so Felix's dash-and-fix
  // theatrics land in the same order you approved them in.
  const runOnPicked = async (action) => {
    const list = rows.filter((c) => picked.has(c.change_id));
    setBulkTotal(list.length); setBulkDone(0);
    for (const c of list) {
      await fx.review(c.change_id, action);
      setBulkDone((n) => n + 1);
    }
    setBulkTotal(0);
    setPicked(new Set());
  };
  return (
    <div style={{ marginTop: 22 }}>
      <SectionHead label="WHAT FELIX FOUND" right={`${rows.length} SHOWN`} />
      <div className="row" style={{ marginBottom: 10, flexWrap: "wrap" }}>
        {sel("review", [["Awaiting Review", "Needs your okay"],
                        ["easy", "Easy fixes"],
                        ["done", "Already fixed"],
                        ["Approved", "Approved"], ["Dismissed", "Discarded"],
                        ["Undo Requested", "Undo requested"]])}
        {sel("db", [["", "All databases"], ["contacts", "Contacts"],
                    ["companies", "Companies"], ["funds", "Funds"], ["notes", "Notes"]])}
        {f.review === "easy" && rows.length > 0 && (
          <Button onClick={fixAll} disabled={bulkTotal > 0}>
            {bulkTotal > 0 ? `Fixing ${bulkDone}/${bulkTotal}…`
              : `Fix all ${rows.length}`}
          </Button>
        )}
      </div>
      {f.review === "easy" && (
        <p className="muted small" style={{ marginBottom: 8 }}>
          High-confidence mechanical fixes (formatting, icons, dead links) —
          the kind Felix applies automatically in live mode. Fix all runs the
          lot; each one stays individually undoable.
        </p>
      )}
      {selectableIds.size > 0 && (
        <div className="row" style={{ marginBottom: 10, gap: 10,
                     padding: "8px 11px", background: "var(--paper-050)",
                     border: "1px solid var(--paper-200)", borderRadius: 4,
                     alignItems: "center" }}>
          <label className="row" style={{ gap: 6, cursor: "pointer",
                                          alignItems: "center" }}>
            <input type="checkbox" checked={allPicked} onChange={toggleAll}
              style={{ width: 15, height: 15, cursor: "pointer" }} />
            <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".08em",
                  color: "var(--stone-500)" }}>
              SELECT ALL {selectableIds.size} SHOWN
            </span>
          </label>
          {picked.size > 0 && (
            <>
              <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".08em",
                    color: "var(--teal-700)" }}>
                {picked.size} SELECTED
              </span>
              <Button variant="dark" disabled={bulkTotal > 0}
                onClick={() => runOnPicked("approve")}>
                {bulkTotal > 0 ? `Approving ${bulkDone}/${bulkTotal}…`
                  : `Approve ${picked.size}`}
              </Button>
              <Button variant="ghost" disabled={bulkTotal > 0}
                onClick={() => runOnPicked("dismiss")}>
                Discard {picked.size}
              </Button>
            </>
          )}
        </div>
      )}
      {rows.length === 0 && (
        <p className="muted small">Nothing waiting — run Felix, or switch the
          view to see easy fixes or past decisions.</p>
      )}
      {rows.map((c) => (
        <ChangeRow key={c.change_id} c={c} s={s}
          checked={picked.has(c.change_id)}
          onToggleCheck={isAwaiting(c) ? togglePick : undefined}
          bulkBusy={bulkTotal > 0} />
      ))}
    </div>
  );
}

/* One finding: what was wrong, the evidence, and the decision. Duplicate rows
   let the reviewer pick which copy survives before approving. */
/* Amend a suggested value before approving it. Tag properties get the
   workspace's own options rather than a free-text box, because a tag Notion
   has never heard of is a new tag, not a correction. */
function ValueEdit({ c, edit, onChange }) {
  const [open, setOpen] = React.useState(false);
  const multi = c.value_kind === "multi_select";
  const tagged = c.value_kind === "select" || c.value_kind === "status" || multi;
  const current = multi
    ? (edit?.values ?? (c.new_value ? c.new_value.split(",").map((x) => x.trim())
                                        .filter(Boolean) : []))
    : (edit?.value ?? c.new_value ?? "");

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="mono"
        style={{ background: "var(--paper-050)", cursor: "pointer",
                 border: "1px solid var(--paper-200)", borderRadius: 4,
                 padding: "3px 9px", marginTop: 6, color: "var(--teal-700)",
                 fontSize: 10, letterSpacing: ".1em" }}>
        {edit ? "EDITED — CHANGE AGAIN" : "EDIT THIS"}
      </button>
    );
  }
  return (
    <div style={{ marginTop: 7, padding: "10px 12px",
                  background: "var(--paper-050)", borderRadius: 4,
                  border: "1px solid var(--paper-200)" }}>
      <div className="microlabel" style={{ marginBottom: 6 }}>
        {(c.property_changed || "VALUE").toUpperCase()}
      </div>
      {tagged && c.value_options?.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {c.value_options.map((opt) => {
            const on = multi ? current.includes(opt) : current === opt;
            return (
              <button key={opt} onClick={() => onChange(multi
                ? { values: on ? current.filter((v) => v !== opt)
                                : [...current, opt] }
                : { value: on ? "" : opt })}
                style={{ cursor: "pointer", borderRadius: 4, padding: "4px 10px",
                         fontSize: "12.5px",
                         border: `1px solid ${on ? "var(--teal-500)" : "var(--paper-200)"}`,
                         background: on ? "var(--teal-100)" : "var(--paper-000)",
                         color: on ? "var(--teal-700)" : "var(--stone-600)" }}>
                {opt}
              </button>
            );
          })}
        </div>
      ) : (
        <textarea value={current} rows={3}
          onChange={(e) => onChange({ value: e.target.value })}
          style={{ width: "100%", padding: "8px 10px", fontSize: "13px",
                   background: "var(--paper-000)", borderRadius: 4,
                   border: "1px solid var(--paper-200)" }} />
      )}
      <div className="row" style={{ marginTop: 8, gap: 8 }}>
        <Button variant="ghost" onClick={() => setOpen(false)}>Done</Button>
        {edit && (
          <Button variant="ghost"
            onClick={() => { onChange(null); setOpen(false); }}>
            Revert to Felix's version
          </Button>
        )}
      </div>
    </div>
  );
}

function ChangeRow({ c, s, checked, onToggleCheck, bulkBusy }) {
  const [keepId, setKeepId] = React.useState("");
  // The reviewer's own wording or tags. null until they touch it, so an
  // untouched row approves exactly what Felix planned.
  const [edit, setEdit] = React.useState(null);
  const d = describeChange(c);
  const [statusWord, statusTone] = STATUS_WORDS[c.execution_status]
    || [c.execution_status.toUpperCase(), "neutral"];
  const awaiting = c.review_status === "Awaiting Review";
  const applied = c.execution_status === "Applied";
  const isDup = c.detail && (c.change_type === "merge"
    || (c.property_changed || "").includes("duplicate"));
  // A distinct verdict is not a merge proposal, so there is nothing to pick.
  const canPick = isDup && awaiting && !applied
    && !(c.reason || "").includes("DISTINCT");
  // Either decision locks the row, but only the pressed button spins. While a
  // bulk approval is running every row locks — an individual click landing
  // mid-queue would race the queue's own call on the same row.
  const rowBusy = (s.busy || "").startsWith(`review-${c.change_id}-`) || bulkBusy;
  return (
          <Card style={{ padding: "13px 16px", marginBottom: 8, display: "flex", gap: 10 }}>
            {/* Only an untouched, awaiting row can join a bulk approval —
                queueing one still mid-edit would silently discard the edit. */}
            {onToggleCheck && (
              <input type="checkbox" checked={!!checked} disabled={bulkBusy}
                onChange={() => onToggleCheck(c.change_id)}
                aria-label={`Select ${c.record_name || "this row"} for bulk approval`}
                style={{ marginTop: 3, flex: "none", width: 15, height: 15,
                         cursor: bulkBusy ? "default" : "pointer" }} />
            )}
            <div style={{ flex: 1, minWidth: 0 }}>
            <div className="spread" style={{ gap: 10, flexWrap: "wrap" }}>
              {/* The field is part of the identity of the row: one contact
                  can have a Title proposal approved and a Description
                  proposal still open, and without this they looked like the
                  same suggestion coming back. */}
              <b style={{ fontSize: "14px" }}>
                {c.record_name || "(unnamed record)"}
                {c.property_changed && !c.property_changed.startsWith("(") && (
                  <span className="mono" style={{ fontSize: 10, marginLeft: 8,
                        letterSpacing: ".08em", color: "var(--teal-700)",
                        background: "var(--teal-100)", padding: "2px 6px",
                        borderRadius: 3 }}>
                    {c.property_changed.toUpperCase()}
                  </span>
                )}
                <span className="mono" style={{ fontSize: 10, marginLeft: 8,
                      letterSpacing: ".1em", color: "var(--stone-400)" }}>
                  {c.database.toUpperCase()} · {fmtDT(c.timestamp)}
                </span>
              </b>
              <Chip tone={statusTone}>{statusWord}</Chip>
            </div>
            <div style={{ fontSize: "13.5px", marginTop: 6 }}>
              <span style={{ color: "var(--caution-600)", fontWeight: 600 }}>Problem: </span>
              {d.problem}
            </div>
            {d.fix && (
              <div style={{ fontSize: "13.5px", marginTop: 3 }}>
                <span style={{ color: "var(--teal-700)", fontWeight: 600 }}>Fix: </span>
                {d.fix}
              </div>
            )}
            {/* Any duplicate finding shows both records side by side, not
                just an executed merge — the evidence is what makes the call. */}
            {isDup && (
              <MergeCompare detail={c.detail} done={applied}
                keepId={keepId} onPick={canPick ? setKeepId : undefined} />
            )}
            {/* A suggested value is a draft. Correct the wording, or pick
                different tags from the workspace's own options, and Approve
                writes what you settled on. */}
            {awaiting && !applied && c.value_kind && (
              <ValueEdit c={c} edit={edit} onChange={setEdit} />
            )}
            {d.source && (
              <div className="muted" style={{ fontSize: "12px", marginTop: 3 }}>
                Why Felix is confident: {d.source}
              </div>
            )}
            {awaiting && d.approve && (
              <div style={{ fontSize: "12px", marginTop: 5, padding: "5px 9px",
                            background: "var(--paper-050)",
                            border: "1px solid var(--paper-200)",
                            borderRadius: 4, color: "var(--stone-600)" }}>
                {d.approve}
              </div>
            )}
            <div className="row" style={{ marginTop: 9, alignItems: "center" }}>
              {awaiting ? (
                <>
                  <Button variant="dark"
                    busy={s.busy === `review-${c.change_id}-approve`}
                    disabled={rowBusy}
                    onClick={() => fx.review(c.change_id, "approve", keepId, edit)}>
                    {edit ? "Approve your version"
                      : canPick && keepId ? "Approve — keep the chosen copy"
                      : "Approve"}
                  </Button>
                  <Button variant="ghost"
                    busy={s.busy === `review-${c.change_id}-${applied ? "undo" : "dismiss"}`}
                    disabled={rowBusy}
                    onClick={() => fx.review(c.change_id,
                                             applied ? "undo" : "dismiss")}>
                    Discard{applied ? " (undo it)" : ""}
                  </Button>
                </>
              ) : (
                <span className="microlabel">{c.review_status.toUpperCase()}</span>
              )}
              {c.record_url && (
                <a href={c.record_url} target="_blank" rel="noreferrer"
                   className="mono" style={{ fontSize: 10.5, letterSpacing: ".08em",
                     color: "var(--teal-700)" }}>
                  OPEN IN NOTION
                </a>
              )}
              {c.undo_result && (
                <span className="muted" style={{ fontSize: "12px" }}>{c.undo_result}</span>
              )}
            </div>
            </div>
          </Card>
  );
}

export default function FixItFelix() {
  React.useSyncExternalStore(fx.subscribe, fx.getVersion);
  const s = fx.S;
  const [narrow, setNarrow] = React.useState(
    typeof window !== "undefined" && window.innerWidth < 820);

  React.useEffect(() => { fx.restore(); }, []);

  React.useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 820);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return (
    <div className="fade-in">
      <PageHeader eyebrow="UPKEEP · NOTION" title="Fix-it Felix"
        actions={null}>
        Felix keeps the workspace clean: duplicates merged, gaps filled, broken
        links repaired — every change logged, reviewable and reversible below.
        Nothing is ever deleted and nothing is ever guessed.
      </PageHeader>

      <ErrorNote error={s.error} />
      {s.status && !s.status.live && (
        <Banner>Notion is in demo mode — runs exercise sample data only.</Banner>
      )}

      {/* Sticky: the workshop scrolls WITH you through the change log, so
          Felix's dash-and-fix theatrics stay in view while reviewing. Flush
          to top: 8 (0) left a sliver of the scrolled-past review text visible
          through the gap above the pinned scene. Below ~820px there is no
          room for a cinematic room, so the stations become a plain row of
          buttons doing exactly the same thing. */}
      {narrow ? (
        <StationStrip scene={s.scene} onSelect={fx.selectStation} />
      ) : (
        <div style={{ position: "sticky", top: 0, zIndex: 30 }}>
          <PixelOfficeScene scene={s.scene} stats={s.stats}
            onSelect={fx.selectStation} />
        </div>
      )}
      <div className="px-hudrow">
        <StatusConsole scene={s.scene} />
        <CleanupHud stats={s.stats} />
      </div>
      <RunPanel s={s} />
      <ReviewTable s={s} />
    </div>
  );
}
