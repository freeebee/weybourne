import React from "react";
import { postFile } from "../api.js";
import { Button, Card, ErrorNote, Mascot, PageHeader, Stat } from "../ui.jsx";

export default function TrackRecords() {
  const [file, setFile] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [record, setRecord] = React.useState(null);
  const [error, setError] = React.useState(null);

  async function analyse() {
    setBusy(true); setError(null);
    try { setRecord(await postFile("/api/track-record", file)); }
    catch (e) { setError(e.message); }
    setBusy(false);
  }

  const fmt = (v, suffix = "") => (v === null || v === undefined ? "—" : `${v}${suffix}`);

  return (
    <div className="fade-in">
      <PageHeader eyebrow="PERFORMANCE · ANALYSIS" title="Track record analysis">
        Private and public market track records, however the manager formatted them,
        normalised into one common shape.
      </PageHeader>

      <Card style={{ marginBottom: "1rem" }}>
        <div className="row">
          <input type="file" accept=".xlsx,.xlsm,.xls,.csv,.tsv,.pdf"
            onChange={(e) => setFile(e.target.files[0])} />
          <Button busy={busy} disabled={!file} onClick={analyse}>Analyse</Button>
        </div>
      </Card>
      {busy && <Mascot state="crunching" text="Reading and normalising — typically under a minute…" />}
      <ErrorNote error={error} />

      {record && (
        <>
          <Card style={{ marginBottom: "1rem" }}>
            <div className="spread">
              <div>
                <h3 style={{ fontWeight: 500, margin: 0 }}>{record.fund || record.manager || "Track record"}</h3>
                <p className="muted small" style={{ margin: ".2rem 0 0" }}>
                  {[record.manager, record.strategy, record.vehicle_type !== "unknown" && record.vehicle_type,
                    record.currency, record.fee_basis].filter(Boolean).join(" · ")}
                </p>
              </div>
            </div>
            <div className="row" style={{ gap: "2.5rem", marginTop: "1rem" }}>
              <Stat label="Cumulative return" value={fmt(record.stats?.cumulative_return_pct?.toFixed?.(1), "%")} />
              <Stat label="Max drawdown" value={fmt(record.stats?.max_drawdown_pct?.toFixed?.(1), "%")} />
              <Stat label="Best period" value={record.stats?.best ? `${record.stats.best.period}` : "—"}
                caption={record.stats?.best?.return_pct != null ? `${record.stats.best.return_pct}%` : ""} />
              <Stat label="Worst period" value={record.stats?.worst ? `${record.stats.worst.period}` : "—"}
                caption={record.stats?.worst?.return_pct != null ? `${record.stats.worst.return_pct}%` : ""} />
            </div>
          </Card>

          {record.summary_stats?.length > 0 && (
            <Card style={{ marginBottom: "1rem" }}>
              <span className="eyebrow">HEADLINE STATS (AS DISCLOSED)</span>
              <table className="small" style={{ borderCollapse: "collapse", width: "100%" }}>
                <tbody>
                  {record.summary_stats.map((s, i) => (
                    <tr key={i} style={{ borderBottom: "1px dotted var(--paper-300)" }}>
                      <td style={{ padding: ".4rem 0" }}>{s.name}</td>
                      <td className="mono" style={{ textAlign: "right" }}>{s.value}{s.unit}</td>
                      <td className="muted" style={{ paddingLeft: "1rem" }}>{s.basis}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          {record.periods?.length > 0 && (
            <Card>
              <span className="eyebrow">PERIODS · {record.periods.length}</span>
              <div style={{ overflowX: "auto" }}>
                <table className="small mono" style={{ borderCollapse: "collapse", width: "100%" }}>
                  <thead>
                    <tr className="eyebrow" style={{ textAlign: "right" }}>
                      <th style={{ textAlign: "left", padding: ".3rem .6rem .3rem 0" }}>Period</th>
                      <th>Return %</th><th>NAV</th><th>Called</th><th>Distributed</th>
                      <th>DPI</th><th>TVPI</th><th>Net IRR %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {record.periods.map((p, i) => (
                      <tr key={i} style={{ borderBottom: "1px dotted var(--paper-200)", textAlign: "right" }}>
                        <td style={{ textAlign: "left", padding: ".3rem .6rem .3rem 0" }}>{p.period}</td>
                        {[p.return_pct, p.nav, p.called, p.distributed, p.dpi, p.tvpi, p.net_irr_pct]
                          .map((v, j) => <td key={j}>{fmt(v)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {record.caveats?.length > 0 && (
            <p className="muted small">Caveats: {record.caveats.join(" · ")}</p>
          )}
        </>
      )}
    </div>
  );
}
