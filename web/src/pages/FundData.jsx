import React from "react";
import { get } from "../api.js";
import {
  Card, ErrorNote, KpiBand, Mascot, PageHeader, SectionHead,
} from "../ui.jsx";

const PALETTE = ["#249692", "#16415C", "#B0894E", "#4F6D7C", "#84C7C2", "#9A9385"];
const WIDTHS = [2, 2, 1.75, 1.5, 1.5, 1.5];

export default function FundData() {
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [metric, setMetric] = React.useState("");

  React.useEffect(() => {
    get("/api/fund-data").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="fade-in"><PageHeader eyebrow="PORTFOLIO" title="Fund data" /><ErrorNote error={error} /></div>;
  if (!data) return <div className="fade-in"><PageHeader eyebrow="PORTFOLIO" title="Fund data" /><Mascot state="working" width={64} text="Loading…" /></div>;

  const metrics = [...new Set(data.facts.map((f) => f.metric_name))];
  const active = metric || metrics[0];
  const series = {};
  data.facts.filter((f) => f.metric_name === active).forEach((f) => {
    (series[f.fund_name] = series[f.fund_name] || []).push(f);
  });
  Object.values(series).forEach((s) => s.sort((a, b) => String(a.period).localeCompare(String(b.period))));

  return (
    <div className="fade-in">
      <PageHeader eyebrow="PORTFOLIO · TIME SERIES" title="Fund data"
        actions={metrics.length > 0 && (
          <label className="microlabel" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            METRIC
            <select value={active} onChange={(e) => setMetric(e.target.value)}>
              {metrics.map((m) => <option key={m}>{m}</option>)}
            </select>
          </label>
        )}>
        The dashboard over everything ingested from quarterly reports and statements.
      </PageHeader>

      <KpiBand items={[
        ["DOCUMENTS INGESTED", data.manifest_count],
        ["FACTS EXTRACTED", data.facts.length.toLocaleString()],
        ["FLAGGED FOR REVIEW", data.flagged.length, data.flagged.length > 0],
        ["LAST RUN", data.last_updated ? String(data.last_updated).slice(0, 10) : "never"],
      ]} />

      {data.facts.length === 0 ? (
        <Card>
          <Mascot state="confused" width={54}
            text="No data yet — run `python update.py` (or scripts/seed_test_data.py) to ingest PDFs into the database." />
        </Card>
      ) : (
        <>
          <SectionHead label={`${(active || "").toUpperCase()} · BY FUND`}
            right={data.last_updated ? `AS AT ${String(data.last_updated).slice(0, 10)}` : ""} />
          <Card style={{ padding: "22px 24px", marginBottom: 26 }}>
            <LineChart series={series} />
          </Card>

          <div style={{ display: "grid",
            gridTemplateColumns: "repeat(auto-fit,minmax(320px,1fr))", gap: 36 }}>
            <section>
              <SectionHead label="NARRATIVE NOTES" right={String(data.notes.length)} />
              {data.notes.slice(0, 12).map((n, i) => (
                <div key={i} className="rrow">
                  <div className="spread">
                    <b style={{ fontSize: "14px" }}>{n.fund_name}</b>
                    <span className="mono" style={{ fontSize: 11, color: "var(--stone-400)" }}>{n.period}</span>
                  </div>
                  <p style={{ fontSize: "13.5px", lineHeight: 1.55, margin: "5px 0 0" }}>
                    {n.note_text || n.text || ""}
                  </p>
                </div>
              ))}
            </section>

            <section>
              <div style={{ display: "flex", alignItems: "center", gap: 12, paddingBottom: 12 }}>
                <Mascot state="confused" width={42} />
                <span className="microlabel">
                  FLAGGED FOR REVIEW · <span style={{ color: "var(--caution-600)" }}>{data.flagged.length}</span>
                </span>
              </div>
              {data.flagged.length === 0 && <p className="muted small">Nothing flagged.</p>}
              {data.flagged.map((f, i) => (
                <div key={i} className="rrow" style={{ display: "grid",
                  gridTemplateColumns: "minmax(0,1fr) auto", gap: "4px 14px" }}>
                  <b style={{ fontSize: "14px" }}>{f.fund_name || f.filename || "record"}</b>
                  <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".1em",
                    color: "var(--caution-600)" }}>
                    {(f.reason || f.issue || "REVIEW").toUpperCase().slice(0, 22)}
                  </span>
                  <span className="muted" style={{ fontSize: "12.5px", gridColumn: "1 / -1" }}>
                    {f.detail || f.raw_value || ""}
                  </span>
                </div>
              ))}
              <p className="muted" style={{ fontSize: "12.5px", marginTop: 10 }}>
                Nothing is written to the fact table with a guessed value — flagged rows wait
                for a human call.
              </p>
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function LineChart({ series }) {
  const names = Object.keys(series);
  const all = names.flatMap((n) => series[n]);
  if (!all.length) return <p className="muted small">No rows for this metric.</p>;
  const periods = [...new Set(all.map((f) => f.period))].sort();
  const values = all.map((f) => +f.metric_value).filter((v) => !isNaN(v));
  const [min, max] = [Math.min(...values), Math.max(...values)];
  const W = 900, H = 260, PX = 60, PY = 26;
  const x = (p) => PX + periods.indexOf(p) * ((W - PX * 2) / Math.max(1, periods.length - 1));
  const y = (v) => H - PY - ((v - min) / (max - min || 1)) * (H - PY * 2);

  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 600 }}>
        {[0, 0.5, 1].map((t, i) => {
          const v = min + t * (max - min);
          return (
            <g key={t}>
              <line x1={PX} x2={W - PX} y1={y(v)} y2={y(v)}
                stroke={i === 1 ? "#EFE9DC" : "#E4DCCB"} strokeWidth="1" />
              <text x={PX - 8} y={y(v) + 4} textAnchor="end" fontSize="11"
                fontFamily="IBM Plex Mono" fill="#9A9385">{v.toFixed(1)}</text>
            </g>
          );
        })}
        {periods.map((p) => (
          <text key={p} x={x(p)} y={H - 8} textAnchor="middle" fontSize="11"
            fontFamily="IBM Plex Mono" fill="#9A9385">{p}</text>
        ))}
        {names.map((n, i) => (
          <polyline key={n} fill="none" stroke={PALETTE[i % PALETTE.length]}
            strokeWidth={WIDTHS[i % WIDTHS.length]}
            strokeDasharray={i === 2 ? "5 4" : undefined}
            points={series[n].map((f) => `${x(f.period)},${y(+f.metric_value)}`).join(" ")} />
        ))}
      </svg>
      <div style={{ borderTop: "1px solid var(--paper-200)", marginTop: 12, paddingTop: 10,
                    display: "flex", gap: 22, flexWrap: "wrap" }}>
        {names.map((n, i) => (
          <span key={n} style={{ fontSize: "12.5px", display: "inline-flex", alignItems: "center", gap: 7 }}>
            <span style={{ width: 14, height: 2, background: PALETTE[i % PALETTE.length], display: "inline-block" }} />
            {n}
          </span>
        ))}
      </div>
    </div>
  );
}
