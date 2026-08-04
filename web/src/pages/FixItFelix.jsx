/* Fix-it Felix — the Notion clean-up agent's workshop. The scene is theatre;
   the change log below is the record. Floating "fixed!" labels come only from
   real change events. */
import React from "react";
import * as fx from "../felixStore.js";
import {
  Banner, Button, Card, Chip, ErrorNote, Mascot, PageHeader, SectionHead,
  fmtDT, inputStyle,
} from "../ui.jsx";

const STATION_X = { contacts: 8, companies: 29, funds: 50, notes: 70, research: 90 };

function Station({ kind, x, active }) {
  const art = {
    contacts: (
      <svg viewBox="0 0 90 110" width="72">
        <rect x="10" y="8" width="70" height="94" rx="4" fill="#C9B392" />
        {[0, 1, 2].map((i) => (
          <g key={i}>
            <rect x="16" y={14 + i * 30} width="58" height="24" rx="2" fill="#B39C79" />
            <rect x="38" y={23 + i * 30} width="14" height="5" rx="2" fill="#8A6642" />
          </g>
        ))}
      </svg>),
    companies: (
      <svg viewBox="0 0 90 110" width="72">
        <rect x="8" y="6" width="74" height="98" rx="3" fill="#C9B392" />
        {[0, 1, 2].map((i) => (
          <rect key={i} x="14" y={14 + i * 30} width="62" height="4" fill="#8A6642" />
        ))}
        {[0, 1, 2].map((i) => (
          <g key={i}>
            <rect x={16 + i * 4} y={18 + i * 30 - 12} width="0" height="0" />
            <rect x="18" y={-8 + 30 * (i + 1)} width="9" height="18" rx="1" fill="#2F6688" />
            <rect x="30" y={-6 + 30 * (i + 1)} width="9" height="16" rx="1" fill="#249692" />
            <rect x="42" y={-9 + 30 * (i + 1)} width="9" height="19" rx="1" fill="#B0894E" />
            <rect x="54" y={-7 + 30 * (i + 1)} width="9" height="17" rx="1" fill="#41688A" />
          </g>
        ))}
      </svg>),
    funds: (
      <svg viewBox="0 0 90 110" width="72">
        <rect x="12" y="10" width="66" height="92" rx="6" fill="#2F6688" />
        <rect x="18" y="16" width="54" height="80" rx="4" fill="#41688A" />
        <circle cx="45" cy="52" r="15" fill="none" stroke="#C9B392" strokeWidth="5" />
        <circle cx="45" cy="52" r="5" fill="#C9B392" />
        <rect x="60" y="46" width="7" height="12" rx="2" fill="#B0894E" />
      </svg>),
    notes: (
      <svg viewBox="0 0 90 110" width="72">
        <rect x="6" y="66" width="78" height="8" rx="2" fill="#C9B392" />
        <rect x="12" y="74" width="8" height="30" fill="#B39C79" />
        <rect x="70" y="74" width="8" height="30" fill="#B39C79" />
        <rect x="16" y="38" width="34" height="28" rx="2" fill="#F7F3EA" stroke="#C9B392" />
        <g stroke="#8298A6" strokeWidth="2">
          <path d="M21 46 h24" /><path d="M21 52 h24" /><path d="M21 58 h16" />
        </g>
        <rect x="54" y="46" width="22" height="20" rx="2" fill="#249692" opacity=".8" />
      </svg>),
    research: (
      <svg viewBox="0 0 90 110" width="72">
        <rect x="6" y="66" width="78" height="8" rx="2" fill="#C9B392" />
        <rect x="12" y="74" width="8" height="30" fill="#B39C79" />
        <rect x="70" y="74" width="8" height="30" fill="#B39C79" />
        <rect x="22" y="28" width="46" height="32" rx="3" fill="#1C2430" />
        <rect x="26" y="32" width="38" height="24" fill="#249692" />
        <g fill="#F7F3EA">
          <rect x="29" y="36" width="20" height="2" />
          <rect x="29" y="41" width="28" height="2" />
          <rect x="29" y="46" width="16" height="2" />
          <rect x="29" y="51" width="24" height="2" />
        </g>
        <rect x="41" y="60" width="8" height="6" fill="#1C2430" />
        <rect x="28" y="61" width="26" height="5" rx="1" fill="#41688A" />
      </svg>),
  }[kind];
  return (
    <div style={{ position: "absolute", left: `${x}%`, top: 132,
                  transform: "translateX(-50%)", textAlign: "center",
                  transformOrigin: "50% 100%",
                  animation: active ? "fx-wobble .55s ease-in-out infinite" : "none" }}>
      {art}
      <div className="mono" style={{ fontSize: 9.5, letterSpacing: ".14em",
                                     color: "var(--stone-500)", marginTop: 2 }}>
        {kind.toUpperCase()}
      </div>
    </div>
  );
}

function Scene({ scene }) {
  const x = STATION_X[scene.zone] ?? 50;
  const fixing = scene.activity === "fix";
  const typing = scene.activity === "type";
  return (
    <Card style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ position: "relative", height: 330,
                    background: "linear-gradient(var(--paper-050) 72%, var(--paper-200) 72.5%, var(--paper-100) 73%)" }}>
        {Object.entries(STATION_X).map(([kind, sx]) => (
          <Station key={kind} kind={kind} x={sx}
            active={(fixing || typing) && scene.zone === kind} />
        ))}

        {/* POWER UP splash on run start */}
        {scene.power && scene.powerBanner > 0 && (
          <div key={scene.powerBanner} className="mono"
            style={{ position: "absolute", left: "50%", top: "42%", zIndex: 5,
                     transform: "translate(-50%,-50%)",
                     background: "var(--ink-800)", color: "#FDE68A",
                     border: "3px solid #E25822", borderRadius: 4,
                     padding: "10px 22px", fontSize: 20, fontWeight: 700,
                     letterSpacing: ".22em", textIndent: ".22em",
                     animation: "fx-power 2.8s steps(24) forwards" }}>
            POWER UP
          </div>
        )}

        {/* Felix — his wrench hand is on his right (viewer left), so he
            stands just right of the station and works on it. Fixing swaps
            the hero/strike frames; walking bounces the hero pose along. */}
        <div className={"fx-sprite" + (scene.power ? " powered" : "")}
          style={{ position: "absolute",
                   left: `calc(${x}% - ${scene.activity === "walk" ? 55 : 6}px)`,
                   top: 118, width: 110,
                   animation: scene.activity === "walk"
                     ? "fx-hop .38s ease-in-out infinite" : "none" }}>
          <div style={{ position: "relative", height: 134 }}>
            {fixing || typing ? (
              <>
                {/* Typing at the research desk swaps the frames twice as
                    fast — furious keyboard work rather than wrench swings. */}
                <div style={{ position: "absolute", inset: 0,
                              animation: `px-swapA ${typing ? ".24s" : ".52s"} steps(1) infinite` }}>
                  <Mascot state="felix-hero" width={110} />
                </div>
                <div style={{ position: "absolute", inset: 0,
                              animation: `px-swapB ${typing ? ".24s" : ".52s"} steps(1) infinite` }}>
                  <Mascot state="felix-strike" width={110} />
                </div>
              </>
            ) : (
              <Mascot state="felix-hero" width={110} />
            )}
          </div>
          {scene.labels.map((l, i) => (
            <div key={l.id}
              onAnimationEnd={() => fx.dropLabel(l.id)}
              style={{ position: "absolute", top: -14 - i * 6, left: "50%",
                       whiteSpace: "nowrap", zIndex: 6,
                       fontSize: 13.5, fontWeight: 700, padding: "5px 12px",
                       borderRadius: 10, background: "#FFFFFF",
                       border: "2px solid var(--ink-800)",
                       boxShadow: "2px 2px 0 rgba(28,36,48,.25)",
                       color: l.tone === "positive" ? "var(--teal-700)"
                         : l.tone === "caution" ? "var(--caution-600)"
                         : "var(--ink-700)",
                       animation: "fx-bubble 2.4s steps(20) forwards" }}>
              {l.text}
              <span style={{ position: "absolute", left: 16, bottom: -7,
                             width: 0, height: 0,
                             borderLeft: "6px solid transparent",
                             borderRight: "6px solid transparent",
                             borderTop: "7px solid var(--ink-800)" }} />
            </div>
          ))}
        </div>
        <div className="mono" style={{ position: "absolute", left: 14, bottom: 10,
              fontSize: 10.5, letterSpacing: ".1em", color: "var(--stone-500)" }}>
          {scene.caption.toUpperCase()}{scene.power ? " · POWERED UP" : ""}
        </div>
      </div>
    </Card>
  );
}

/* Game-Dev-Story-style tracker: pixel icon + chunky count, everything Felix
   has cleaned up since the start. */
function Tracker({ stats }) {
  if (!stats) return null;
  const icon = (draw) => (
    <svg viewBox="0 0 10 10" width="22" shapeRendering="crispEdges">{draw}</svg>
  );
  const wrench = icon(<>
    <rect x="2" y="6" width="6" height="2" fill="#9FB2BD" transform="rotate(-45 5 7)" />
    <rect x="6" y="1" width="3" height="3" fill="#9FB2BD" />
    <rect x="7" y="2" width="2" height="1" fill="#F7F3EA" /></>);
  const pair = icon(<>
    <rect x="1" y="2" width="3" height="3" fill="#41688A" />
    <rect x="6" y="2" width="3" height="3" fill="#B0894E" />
    <rect x="2" y="6" width="6" height="2" fill="#249692" /></>);
  const link = icon(<>
    <rect x="1" y="4" width="4" height="2" fill="#249692" />
    <rect x="5" y="4" width="4" height="2" fill="#41688A" />
    <rect x="4" y="3" width="2" height="4" fill="#1C2430" /></>);
  const drop = icon(<>
    <rect x="4" y="1" width="2" height="2" fill="#41688A" />
    <rect x="3" y="3" width="4" height="4" fill="#41688A" />
    <rect x="2" y="5" width="6" height="3" fill="#2F6688" /></>);
  const flag = icon(<>
    <rect x="2" y="1" width="1" height="8" fill="#1C2430" />
    <rect x="3" y="1" width="5" height="3" fill="#D97706" /></>);
  const rewind = icon(<>
    <rect x="1" y="4" width="3" height="2" fill="#8C4038" />
    <rect x="4" y="3" width="2" height="4" fill="#8C4038" />
    <rect x="6" y="2" width="2" height="6" fill="#8C4038" /></>);
  const items = [
    [wrench, stats.applied_total, "fixes"],
    [pair, stats.by_type?.merge || 0, "merges"],
    [drop, stats.by_type?.fill_missing || 0, "fills"],
    [link, stats.by_type?.fix_relation || 0, "links"],
    [flag, stats.recommendations, "flagged"],
    [rewind, stats.undone, "undone"],
  ];
  return (
    <div style={{ display: "flex", gap: 26, alignItems: "center",
                  flexWrap: "wrap", padding: "10px 16px", margin: "14px 0 18px",
                  background: "var(--paper-000)",
                  border: "1px solid var(--paper-200)",
                  borderRadius: "var(--radius)" }}>
      <span className="mono" style={{ fontSize: 9.5, letterSpacing: ".14em",
                                      color: "var(--stone-400)" }}>
        CLEANED UP SINCE THE START
      </span>
      {items.map(([ic, v, label], i) => (
        <span key={i} title={label}
          style={{ display: "inline-flex", gap: 7, alignItems: "center" }}>
          {ic}
          <b style={{ fontSize: 21, color: "var(--ink-600)",
                      fontVariantNumeric: "tabular-nums" }}>
            {(v ?? 0).toLocaleString()}
          </b>
        </span>
      ))}
    </div>
  );
}

function RunPanel({ s }) {
  const job = s.runJob;
  const running = job?.status === "running";
  const cfg = s.status || {};
  const [confirmLive, setConfirmLive] = React.useState(false);
  if (running) {
    const left = Math.max(0, (job.eta || 0) - (job.elapsed || 0));
    return (
      <Card accent="teal" style={{ marginBottom: 18 }}>
        <div className="spread">
          <span className="microlabel">
            RUNNING · {job.label?.toUpperCase()} · {job.elapsed}S ELAPSED ·
            {left > 0 ? ` ~${left}S LEFT` : " OVERRUNNING"}
          </span>
          <Button variant="ghost" onClick={fx.cancelRun}>Cancel</Button>
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
          <Chip tone={cfg.live_enabled ? "positive" : "teal"}>
            {cfg.live_enabled ? "LIVE MODE" : "DRY RUN MODE"}
          </Chip>
          {!cfg.live && <Chip tone="neutral">NOTION: DEMO DATA</Chip>}
        </div>
        <label className="mono" style={{ fontSize: 10.5, letterSpacing: ".1em",
                display: "flex", gap: 7, alignItems: "center",
                color: "var(--stone-500)" }}>
          <input type="checkbox" checked={!!cfg.auto_run_enabled}
            onChange={(e) => fx.setConfig({ auto_run_enabled: e.target.checked })} />
          DAILY AUTO-RUN
          <select value={cfg.auto_run_hour ?? 7} style={{ ...inputStyle, padding: "3px 6px", width: "auto" }}
            onChange={(e) => fx.setConfig({ auto_run_hour: +e.target.value })}>
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>
            ))}
          </select>
        </label>
      </div>
      {!cfg.live_enabled && (s.stats?.runs || 0) > 0 && (
        <div style={{ marginTop: 12, borderTop: "1px solid var(--paper-200)",
                      paddingTop: 10 }}>
          {confirmLive ? (
            <div className="row">
              <span style={{ fontSize: "13px" }}>
                Felix will make real, reversible edits to your Notion workspace
                automatically. Sure?
              </span>
              <Button variant="dark" onClick={() => {
                fx.setConfig({ live_enabled: true }); setConfirmLive(false);
              }}>Enable live runs</Button>
              <Button variant="ghost" onClick={() => setConfirmLive(false)}>Not yet</Button>
            </div>
          ) : (
            <Button variant="ghost" onClick={() => setConfirmLive(true)}>
              Enable live runs (reviewed the dry run)
            </Button>
          )}
        </div>
      )}
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

/* Each change in plain words: what was wrong, what Felix did (or suggests),
   and one Approve / Discard choice. Merge sub-steps are folded into their
   parent rather than listed. */
function describeChange(c) {
  const q = (v) => `“${v}”`;
  const done = c.execution_status === "Applied";
  // What pressing Approve will actually DO — stated on every row so there is
  // never any guessing.
  const approve = done
    ? "Approve files it as reviewed (it is already done). Discard undoes it in Notion."
    : c.change_type === "merge"
      ? "Approve records your OK; the merge itself runs on the next live Felix run. Discard drops it."
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
function MergeCompare({ detail }) {
  let d;
  try { d = JSON.parse(detail); } catch { return null; }
  if (!d || !d.keep || !d.archive) return null;
  const col = (rec, label, tone) => (
    <div style={{ flex: "1 1 220px", minWidth: 200, padding: "8px 11px",
                  background: "var(--paper-050)",
                  border: "1px solid var(--paper-200)",
                  borderTop: `2px solid var(${tone})`,
                  borderRadius: 4 }}>
      <div className="mono" style={{ fontSize: 9.5, letterSpacing: ".1em",
                                     color: "var(--stone-500)" }}>{label}</div>
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
      </div>
    </div>
  );
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {col(d.keep, "KEPT — THE RICHER COPY", "--positive-600")}
        {col(d.archive, "ARCHIVED — THE DUPLICATE", "--caution-600")}
      </div>
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

function ReviewTable({ s }) {
  const f = s.changesFilter;
  const setF = (patch) => fx.fetchChanges({ ...f, ...patch });
  const sel = (key, opts) => (
    <select value={f[key] || ""} style={{ ...inputStyle, width: "auto", padding: "5px 8px" }}
      onChange={(e) => setF({ [key]: e.target.value })}>
      {opts.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
    </select>
  );
  const rows = s.changes.filter((c) => !c.parent_change_id);
  return (
    <div style={{ marginTop: 22 }}>
      <SectionHead label="WHAT FELIX FOUND" right={`${rows.length} SHOWN`} />
      <div className="row" style={{ marginBottom: 10, flexWrap: "wrap" }}>
        {sel("review", [["Awaiting Review", "Needs your OK"], ["", "Everything"],
                        ["Approved", "Approved"], ["Dismissed", "Discarded"],
                        ["Undo Requested", "Undo requested"]])}
        {sel("db", [["", "All databases"], ["contacts", "Contacts"],
                    ["companies", "Companies"], ["funds", "Funds"], ["notes", "Notes"]])}
      </div>
      {rows.length === 0 && (
        <p className="muted small">Nothing waiting — run Felix, or switch the
          filter to Everything to see past changes.</p>
      )}
      {rows.map((c) => {
        const d = describeChange(c);
        const [statusWord, statusTone] = STATUS_WORDS[c.execution_status]
          || [c.execution_status.toUpperCase(), "neutral"];
        const awaiting = c.review_status === "Awaiting Review";
        const applied = c.execution_status === "Applied";
        return (
          <Card key={c.change_id} style={{ padding: "13px 16px", marginBottom: 8 }}>
            <div className="spread" style={{ gap: 10, flexWrap: "wrap" }}>
              <b style={{ fontSize: "14px" }}>
                {c.record_name || "(unnamed record)"}
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
            {c.change_type === "merge" && c.detail && (
              <MergeCompare detail={c.detail} />
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
                  <Button variant="dark" busy={s.busy === `review-${c.change_id}`}
                    onClick={() => fx.review(c.change_id, "approve")}>Approve</Button>
                  <Button variant="ghost" busy={s.busy === `review-${c.change_id}`}
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
          </Card>
        );
      })}
    </div>
  );
}

export default function FixItFelix() {
  React.useSyncExternalStore(fx.subscribe, fx.getVersion);
  const s = fx.S;

  React.useEffect(() => { fx.restore(); }, []);

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
          Felix's dash-and-fix theatrics stay in view while reviewing. */}
      <div style={{ position: "sticky", top: 8, zIndex: 30 }}>
        <Scene scene={s.scene} />
      </div>
      <Tracker stats={s.stats} />
      <RunPanel s={s} />
      <ReviewTable s={s} />
    </div>
  );
}
