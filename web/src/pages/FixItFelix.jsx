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

function Scene({ scene }) {
  const state = { walk: "felix-walk", fix: "felix-fix", inspect: "felix-inspect",
                  sleep: "felix-sleep" }[scene.activity] || "felix-inspect";
  const x = scene.activity === "sleep" ? 50 : STATION_X[scene.zone] ?? 50;
  return (
    <Card style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ position: "relative", height: 330,
                    background: "linear-gradient(var(--paper-050) 72%, var(--paper-200) 72.5%, var(--paper-100) 73%)" }}>
        {Object.entries(STATION_X).map(([kind, sx]) => (
          <Station key={kind} kind={kind} x={sx} />
        ))}
        {/* Felix */}
        <div className="fx-sprite" style={{ position: "absolute",
              left: `calc(${x}% - 62px)`, top: 158, width: 124 }}>
          <Mascot state={state} width={124} />
          {scene.labels.map((l, i) => (
            <div key={l.id} className="mono"
              onAnimationEnd={() => fx.dropLabel(l.id)}
              style={{ position: "absolute", top: -6 - i * 4, left: "50%",
                       transform: "translateX(-50%)", whiteSpace: "nowrap",
                       fontSize: 11, letterSpacing: ".08em", padding: "3px 9px",
                       borderRadius: 4, background: "var(--paper-000)",
                       border: "1px solid var(--paper-200)",
                       color: l.tone === "positive" ? "var(--positive-600)"
                         : l.tone === "caution" ? "var(--caution-600)"
                         : "var(--teal-700)",
                       animation: "fx-label 2.6s ease-out forwards" }}>
              {l.text}
            </div>
          ))}
        </div>
        <div className="mono" style={{ position: "absolute", left: 14, bottom: 10,
              fontSize: 10.5, letterSpacing: ".1em", color: "var(--stone-500)" }}>
          {scene.caption.toUpperCase()}
        </div>
      </div>
    </Card>
  );
}

function Hud({ stats }) {
  if (!stats) return null;
  const items = [
    ["FIXES ALL-TIME", stats.applied_total],
    ["TODAY", stats.applied_today],
    ["MERGES", stats.by_type?.merge || 0],
    ["FOR REVIEW", stats.recommendations],
    ["UNDONE", stats.undone],
    ["RUNS", stats.runs],
  ];
  return (
    <div style={{ display: "flex", gap: 22, flexWrap: "wrap", margin: "16px 2px" }}>
      {items.map(([k, v]) => (
        <div key={k}>
          <div style={{ fontFamily: "var(--serif)", fontSize: 30, lineHeight: 1 }}>
            {(v ?? 0).toLocaleString()}
          </div>
          <div className="microlabel" style={{ marginTop: 3 }}>{k}</div>
        </div>
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
      <Hud stats={s.stats} />
      <RunPanel s={s} />
      <ReviewTable s={s} />
    </div>
  );
}
