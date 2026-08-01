import React from "react";
import { postFile } from "../api.js";
import {
  Button, Card, ErrorNote, KpiBand, Mascot, PageHeader, SectionHead,
} from "../ui.jsx";

export default function TrackRecords() {
  const [file, setFile] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [record, setRecord] = React.useState(null);
  const [error, setError] = React.useState(null);
  const fileRef = React.useRef(null);

  async function analyse(f) {
    setBusy(true); setError(null);
    try { setRecord(await postFile("/api/track-record", f)); }
    catch (e) { setError(e.message); }
    setBusy(false);
  }

  const fmt = (v, suffix = "") => (v === null || v === undefined ? "—" : `${v}${suffix}`);
  const periods = record?.periods || [];
  const returns = periods.filter((p) => p.return_pct != null);

  return (
    <div className="fade-in">
      <PageHeader eyebrow="PERFORMANCE · ANALYSIS" title="Track records"
        actions={<Button busy={busy} onClick={() => fileRef.current?.click()}>Add a record</Button>}>
        Private and public market track records, however the manager formatted them,
        normalised into one common shape.
      </PageHeader>

      {/* Drop zone */}
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) { setFile(f); analyse(f); } }}
        onClick={() => fileRef.current?.click()}
        style={{ border: "1px dashed var(--paper-300)", borderRadius: "var(--radius)",
                 background: "var(--paper-000)", padding: "14px 18px", cursor: "pointer",
                 display: "flex", alignItems: "center", gap: 18, marginBottom: 6 }}>
        <Mascot state="reading" width={58} />
        <div>
          <span className="microlabel">DROP XLSX OR PDF</span>
          <div style={{ fontSize: "13.5px", color: "var(--stone-600)", marginTop: 3 }}>
            {file ? file.name : "A manager's track record in whatever format they sent it — spreadsheet, tearsheet, quarterly letter."}
          </div>
        </div>
        <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.xls,.csv,.tsv,.pdf" hidden
          onChange={(e) => { const f = e.target.files[0]; if (f) { setFile(f); analyse(f); } }} />
      </div>
      {busy && <Mascot state="crunching" width={54} text="Reading and normalising — typically under a minute…" />}
      <ErrorNote error={error} />

      {record && (
        <>
          <KpiBand items={[
            ["CUMULATIVE RETURN", fmt(record.stats?.cumulative_return_pct?.toFixed?.(1), "%")],
            ["MAX DRAWDOWN", fmt(record.stats?.max_drawdown_pct?.toFixed?.(1), "%"), record.stats?.max_drawdown_pct < -15],
            ["BEST PERIOD", record.stats?.best ? record.stats.best.period : "—", false,
              record.stats?.best?.return_pct != null ? `${record.stats.best.return_pct}%` : ""],
            ["WORST PERIOD", record.stats?.worst ? record.stats.worst.period : "—", true,
              record.stats?.worst?.return_pct != null ? `${record.stats.worst.return_pct}%` : ""],
          ]} />

          <div className="spread" style={{ marginBottom: 14 }}>
            <div>
              <div style={{ font: "400 22px/1.3 var(--serif)", color: "var(--ink-800)" }}>
                {record.fund || record.manager || "Track record"}
              </div>
              <div className="muted" style={{ fontSize: "13px" }}>
                {[record.manager, record.strategy, record.vehicle_type !== "unknown" && record.vehicle_type,
                  record.currency, record.fee_basis].filter(Boolean).join(" · ")}
              </div>
            </div>
          </div>

          <div className="panes">
            {/* Table */}
            <div style={{ flex: "2 1 460px", minWidth: "min(100%,320px)" }}>
              {record.summary_stats?.length > 0 && (
                <>
                  <SectionHead label="HEADLINE STATS · AS DISCLOSED" />
                  <table className="wb" style={{ marginBottom: 22 }}>
                    <tbody>
                      {record.summary_stats.map((s, i) => (
                        <tr key={i}>
                          <td>{s.name}</td>
                          <td>{s.value}{s.unit}</td>
                          <td style={{ fontFamily: "var(--mono)", fontSize: 11,
                            color: s.basis === "derived" ? "var(--caution-600)" : "var(--stone-400)" }}>
                            {s.basis.toUpperCase()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
              {periods.length > 0 && (
                <>
                  <SectionHead label={`PERIODS · ${periods.length}`} />
                  <div style={{ overflowX: "auto" }}>
                    <table className="wb">
                      <thead><tr>
                        <th>Period</th><th>Return %</th><th>NAV</th><th>Called</th>
                        <th>Distributed</th><th>DPI</th><th>TVPI</th><th>Net IRR %</th>
                      </tr></thead>
                      <tbody>
                        {periods.map((p, i) => (
                          <tr key={i}>
                            <td>{p.period}</td>
                            {[p.return_pct, p.nav, p.called, p.distributed, p.dpi, p.tvpi, p.net_irr_pct]
                              .map((v, j) => (
                                <td key={j} style={v == null ? { color: "var(--stone-400)" } : undefined}>
                                  {fmt(v)}
                                </td>
                              ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>

            {/* Chart */}
            {returns.length > 1 && (
              <div style={{ flex: "1 1 280px", maxWidth: 400, minWidth: "min(100%,260px)" }}>
                <SectionHead label="CUMULATIVE RETURN · %" />
                <Card><CumChart periods={returns} /></Card>
                <p className="muted" style={{ fontSize: "13px", marginTop: 10 }}>
                  Compounded from the periodic returns as disclosed — no smoothing, no
                  backfill; missing periods are left out rather than interpolated.
                </p>
              </div>
            )}
          </div>

          {record.caveats?.length > 0 && (
            <p className="muted" style={{ fontSize: "12.5px", marginTop: 14 }}>
              Caveats: {record.caveats.join(" · ")}
            </p>
          )}
        </>
      )}
    </div>
  );
}

function CumChart({ periods }) {
  const W = 360, H = 200, PX = 40, PY = 22;
  let cum = 1;
  const pts = periods.map((p) => ({ period: p.period, v: (cum *= 1 + p.return_pct / 100) }));
  const vals = pts.map((p) => (p.v - 1) * 100);
  const [min, max] = [Math.min(0, ...vals), Math.max(...vals)];
  const x = (i) => PX + i * ((W - PX - 10) / Math.max(1, pts.length - 1));
  const y = (v) => H - PY - ((v - min) / (max - min || 1)) * (H - PY * 2);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%" }}>
      {[min, (min + max) / 2, max].map((v, i) => (
        <g key={i}>
          <line x1={PX} x2={W - 10} y1={y(v)} y2={y(v)}
            stroke={i === 1 ? "#EFE9DC" : "#E4DCCB"} strokeWidth="1" />
          <text x={PX - 6} y={y(v) + 3} textAnchor="end" fontSize="9"
            fontFamily="IBM Plex Mono" fill="#9A9385">{v.toFixed(0)}</text>
        </g>
      ))}
      <polyline fill="none" stroke="#249692" strokeWidth="1.75"
        points={vals.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
      <text x={x(0)} y={H - 6} fontSize="9" fontFamily="IBM Plex Mono" fill="#9A9385">
        {pts[0]?.period}
      </text>
      <text x={x(pts.length - 1)} y={H - 6} textAnchor="end" fontSize="9"
        fontFamily="IBM Plex Mono" fill="#9A9385">{pts[pts.length - 1]?.period}</text>
    </svg>
  );
}
