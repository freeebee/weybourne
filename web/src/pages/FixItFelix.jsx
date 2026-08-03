/* Fix-it Felix — the Notion clean-up agent's workshop. The scene is theatre;
   the change log below is the record. Floating "fixed!" labels come only from
   real change events. */
import React from "react";
import * as fx from "../felixStore.js";
import {
  Banner, Button, Card, Chip, ErrorNote, Mascot, PageHeader, SectionHead,
  fmtDT, inputStyle,
} from "../ui.jsx";

const STATION_X = { contacts: 10, companies: 36, funds: 62, notes: 87 };

function Station({ kind, x }) {
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
  }[kind];
  return (
    <div style={{ position: "absolute", left: `${x}%`, top: 26,
                  transform: "translateX(-50%)", textAlign: "center" }}>
      {art}
      <div className="mono" style={{ fontSize: 9.5, letterSpacing: ".14em",
                                     color: "var(--stone-500)", marginTop: 2 }}>
        {kind.toUpperCase()}
      </div>
    </div>
  );
}

/* 8-bit flames, two frames flipped by the px-swap pair — shown when Felix is
   in POWER UP mode (a run is underway). */
function PixelFire({ width = 150 }) {
  const px = (cells, fill) => cells.map(([cx, cy, w = 1, h = 1], i) => (
    <rect key={fill + i} x={cx} y={cy} width={w} height={h} fill={fill} />
  ));
  return (
    <svg viewBox="0 0 26 14" width={width} shapeRendering="crispEdges"
      style={{ position: "absolute", bottom: -4, left: "50%",
               transform: "translateX(-50%)", pointerEvents: "none" }}>
      <g style={{ animation: "px-swapA .28s steps(1) infinite" }}>
        {px([[1, 6], [2, 4], [3, 8], [5, 3], [6, 6], [19, 5], [21, 3], [22, 7],
             [24, 5], [0, 9, 2, 4], [3, 10, 3, 3], [18, 9, 3, 4], [23, 8, 3, 5]],
            "#E25822")}
        {px([[2, 7], [4, 9], [5, 6], [20, 6], [22, 9], [24, 7],
             [1, 11, 2, 2], [19, 11, 2, 2]], "#F59E0B")}
        {px([[2, 10], [4, 11], [20, 10], [24, 11]], "#FDE68A")}
      </g>
      <g style={{ animation: "px-swapB .28s steps(1) infinite" }}>
        {px([[0, 4], [2, 6], [4, 2], [5, 7], [20, 2], [21, 6], [23, 4], [25, 7],
             [1, 8, 3, 5], [4, 9, 2, 4], [19, 8, 3, 5], [23, 9, 3, 4]],
            "#E25822")}
        {px([[1, 6], [3, 8], [5, 10], [20, 7], [22, 8], [24, 10],
             [2, 11, 2, 2], [21, 11, 3, 2]], "#F59E0B")}
        {px([[3, 11], [1, 10], [21, 9], [23, 12]], "#FDE68A")}
      </g>
    </svg>
  );
}

function Scene({ scene }) {
  const state = scene.activity === "walk" ? "felix-walk" : "felix-fix";
  const x = STATION_X[scene.zone] ?? 50;
  return (
    <Card style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ position: "relative", height: 330,
                    background: "linear-gradient(var(--paper-050) 72%, var(--paper-200) 72.5%, var(--paper-100) 73%)" }}>
        {Object.entries(STATION_X).map(([kind, sx]) => (
          <Station key={kind} kind={kind} x={sx} />
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

        {/* Felix */}
        <div className={"fx-sprite" + (scene.power ? " powered" : "")}
          style={{ position: "absolute", left: `calc(${x}% - 62px)`,
                   top: 158, width: 124 }}>
          {scene.power && <PixelFire />}
          <div style={{ position: "relative" }}>
            <Mascot state={state} width={124} />
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

function ReviewTable({ s }) {
  const f = s.changesFilter;
  const setF = (patch) => fx.fetchChanges({ ...f, ...patch });
  const sel = (key, opts) => (
    <select value={f[key] || ""} style={{ ...inputStyle, width: "auto", padding: "5px 8px" }}
      onChange={(e) => setF({ [key]: e.target.value })}>
      {opts.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
    </select>
  );
  return (
    <div style={{ marginTop: 22 }}>
      <SectionHead label="CHANGE LOG" right={`${s.changes.length} SHOWN`} />
      <div className="row" style={{ marginBottom: 10, flexWrap: "wrap" }}>
        {sel("review", [["", "All review states"], ["Awaiting Review", "Awaiting review"],
                        ["Approved", "Approved"], ["Undo Requested", "Undo requested"]])}
        {sel("status", [["", "All statuses"], ["Applied", "Applied"],
                        ["Planned (dry-run)", "Planned (dry-run)"],
                        ["Recommended", "Recommended"], ["Failed", "Failed"],
                        ["Undone", "Undone"], ["Skipped", "Skipped"]])}
        {sel("db", [["", "All databases"], ["contacts", "Contacts"],
                    ["companies", "Companies"], ["funds", "Funds"], ["notes", "Notes"]])}
      </div>
      {s.changes.length === 0 && (
        <p className="muted small">Nothing here yet — run Felix to populate the log.</p>
      )}
      {s.changes.map((c) => (
        <Card key={c.change_id} style={{ padding: "12px 16px", marginBottom: 8 }}>
          <div className="spread" style={{ gap: 10, flexWrap: "wrap" }}>
            <span className="mono" style={{ fontSize: 10, letterSpacing: ".08em",
                  color: "var(--stone-400)" }}>
              {c.change_id} · {fmtDT(c.timestamp)} · {c.database.toUpperCase()}
            </span>
            <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <Chip tone={c.confidence === "High" ? "positive"
                : c.confidence === "Medium" ? "teal" : "neutral"}>
                {(c.confidence || "?").toUpperCase()}
              </Chip>
              <Chip tone={c.execution_status === "Applied" ? "positive"
                : c.execution_status === "Failed" ? "critical"
                : c.execution_status === "Undone" ? "neutral" : "teal"}>
                {c.execution_status.toUpperCase()}
              </Chip>
            </span>
          </div>
          <div style={{ fontSize: "13.5px", marginTop: 5 }}>
            <b>{c.record_name || c.record_id}</b>
            {" — "}{c.change_type.replaceAll("_", " ")}
            {c.property_changed && c.property_changed !== "(whole record)"
              ? ` · ${c.property_changed}` : ""}
            {c.record_url && (
              <a href={c.record_url} target="_blank" rel="noreferrer"
                 className="mono" style={{ marginLeft: 8, fontSize: 10.5,
                   letterSpacing: ".08em", color: "var(--teal-700)" }}>
                OPEN
              </a>
            )}
          </div>
          {(c.previous_value || c.new_value) && (
            <div style={{ fontSize: "12.5px", marginTop: 4,
                          display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <span style={{ color: "var(--stone-500)", overflowWrap: "anywhere" }}>
                {c.previous_value || "(empty)"}
              </span>
              <span style={{ color: "var(--teal-700)", overflowWrap: "anywhere" }}>
                {c.new_value || "(empty)"}
              </span>
            </div>
          )}
          {(c.source || c.reason) && (
            <div className="muted" style={{ fontSize: "12px", marginTop: 4 }}>
              {c.reason}{c.source ? ` — ${c.source}` : ""}
            </div>
          )}
          <div className="row" style={{ marginTop: 8 }}>
            {c.review_status === "Awaiting Review" &&
              c.execution_status === "Applied" && (
              <>
                <Button variant="ghost" busy={s.busy === `review-${c.change_id}`}
                  onClick={() => fx.review(c.change_id, "approve")}>Approve</Button>
                <Button variant="ghost" busy={s.busy === `review-${c.change_id}`}
                  onClick={() => fx.review(c.change_id, "undo")}>Undo</Button>
              </>
            )}
            {c.review_status !== "Awaiting Review" && (
              <span className="microlabel">{c.review_status.toUpperCase()}</span>
            )}
            {c.undo_result && (
              <span className="muted" style={{ fontSize: "12px" }}>{c.undo_result}</span>
            )}
          </div>
        </Card>
      ))}
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

      <Scene scene={s.scene} />
      <Tracker stats={s.stats} />
      <RunPanel s={s} />
      <ReviewTable s={s} />
    </div>
  );
}
