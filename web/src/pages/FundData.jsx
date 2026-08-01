import React from "react";
import { get } from "../api.js";
import { Card, ErrorNote, Mascot, PageHeader, Stat, Tabs } from "../ui.jsx";

export default function FundData() {
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [tab, setTab] = React.useState("Metrics");
  const [metric, setMetric] = React.useState("");

  React.useEffect(() => {
    get("/api/fund-data").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="fade-in"><PageHeader eyebrow="PORTFOLIO" title="Fund data" /><ErrorNote error={error} /></div>;
  if (!data) return <div className="fade-in"><PageHeader eyebrow="PORTFOLIO" title="Fund data" /><Mascot state="working" text="Loading…" /></div>;

  const metrics = [...new Set(data.facts.map((f) => f.metric_name))];
  const active = metric || metrics[0];
  const series = {};
  data.facts.filter((f) => f.metric_name === active).forEach((f) => {
    (series[f.fund_name] = series[f.fund_name] || []).push(f);
  });
  Object.values(series).forEach((s) => s.sort((a, b) => String(a.period).localeCompare(String(b.period))));

  return (
    <div className="fade-in">
      <PageHeader eyebrow="PORTFOLIO · TIME SERIES" title="Fund data">
        The dashboard over everything ingested from quarterly reports and statements.
      </PageHeader>

      <div className="row" style={{ gap: "2.5rem", marginBottom: "1rem" }}>
        <Stat label="Last updated" value={data.last_updated || "never"} />
        <Stat label="Documents ingested" value={data.manifest_count} />
        <Stat label="Flagged for review" value={data.flagged.length} />
      </div>

      {data.facts.length === 0 ? (
        <Card><Mascot state="confused"
          text="No data yet — run `python update.py` (or scripts/seed_test_data.py) to ingest PDFs into the database." /></Card>
      ) : (
        <>
          <Tabs tabs={["Metrics", "Narrative notes", "Ingestion log"]} active={tab} onChange={setTab} />

          {tab === "Metrics" && (
            <Card>
              <div className="row" style={{ marginBottom: "1rem" }}>
                <span className="eyebrow" style={{ margin: 0 }}>METRIC</span>
                <select value={active} onChange={(e) => setMetric(e.target.value)}
                  style={{ padding: ".4rem .6rem", fontFamily: "var(--mono)", fontSize: ".85rem",
                           border: "1px solid var(--paper-300)", background: "var(--paper-000)" }}>
                  {metrics.map((m) => <option key={m}>{m}</option>)}
                </select>
              </div>
              <LineChart series={series} />
            </Card>
          )}

          {tab === "Narrative notes" && (
            <Card>
              {data.notes.map((n, i) => (
                <div key={i} style={{ borderBottom: "1px dotted var(--paper-300)", padding: ".6rem 0" }}>
                  <div className="spread">
                    <b className="small">{n.fund_name}</b>
                    <span className="mono muted small">{n.period}</span>
                  </div>
                  <p className="small" style={{ margin: ".3rem 0 0" }}>{n.note_text || n.text || ""}</p>
                </div>
              ))}
            </Card>
          )}

          {tab === "Ingestion log" && (
            <Card>
              <table className="small mono" style={{ width: "100%", borderCollapse: "collapse" }}>
                <tbody>
                  {data.log.map((l, i) => (
                    <tr key={i} style={{ borderBottom: "1px dotted var(--paper-200)" }}>
                      <td style={{ padding: ".3rem .8rem .3rem 0" }}>{l.timestamp || l.run_date || ""}</td>
                      <td>{l.filename || l.file || ""}</td>
                      <td className="muted">{l.status || l.message || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

const PALETTE = ["#249692", "#16415C", "#B0894E", "#4F6D7C", "#84C7C2", "#9A9385"];

function LineChart({ series }) {
  const names = Object.keys(series);
  const all = names.flatMap((n) => series[n]);
  if (!all.length) return <p className="muted small">No rows for this metric.</p>;
  const periods = [...new Set(all.map((f) => f.period))].sort();
  const values = all.map((f) => +f.metric_value).filter((v) => !isNaN(v));
  const [min, max] = [Math.min(...values), Math.max(...values)];
  const W = 900, H = 300, PX = 60, PY = 24;
  const x = (p) => PX + periods.indexOf(p) * ((W - PX * 2) / Math.max(1, periods.length - 1));
  const y = (v) => H - PY - ((v - min) / (max - min || 1)) * (H - PY * 2);

  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 600 }}>
        {[0, 0.5, 1].map((t) => {
          const v = min + t * (max - min);
          return (
            <g key={t}>
              <line x1={PX} x2={W - PX} y1={y(v)} y2={y(v)} stroke="#E4DCCB" strokeWidth="1" />
              <text x={PX - 8} y={y(v) + 4} textAnchor="end"
                fontSize="10" fontFamily="IBM Plex Mono" fill="#7A7468">{v.toFixed(1)}</text>
            </g>
          );
        })}
        {periods.map((p) => (
          <text key={p} x={x(p)} y={H - 6} textAnchor="middle"
            fontSize="10" fontFamily="IBM Plex Mono" fill="#7A7468">{p}</text>
        ))}
        {names.map((n, i) => (
          <g key={n}>
            <polyline fill="none" stroke={PALETTE[i % PALETTE.length]} strokeWidth="2"
              points={series[n].map((f) => `${x(f.period)},${y(+f.metric_value)}`).join(" ")} />
            {series[n].map((f, j) => (
              <circle key={j} cx={x(f.period)} cy={y(+f.metric_value)} r="3"
                fill={PALETTE[i % PALETTE.length]} />
            ))}
          </g>
        ))}
      </svg>
      <div className="row small" style={{ gap: "1.2rem" }}>
        {names.map((n, i) => (
          <span key={n}><span style={{
            display: "inline-block", width: 10, height: 10, borderRadius: 2,
            background: PALETTE[i % PALETTE.length], marginRight: 6 }} />{n}</span>
        ))}
      </div>
    </div>
  );
}
