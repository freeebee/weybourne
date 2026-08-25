import React from "react";
import { get } from "../../api.js";
import { Card, ErrorNote, SectionHead, Spinner, useScrollHold } from "../../ui.jsx";
import {
  Drawer, Empty, Pct, Pill, QuoteBlock, SEVERITY_COLOR, SEVERITY_LABEL, SEVERITY_TONE,
  STANCE_COLOR, STANCE_LABEL, StanceChip,
} from "./shared.jsx";

/* Heatmap cell styling.

   The original dashboard used generic emerald/rose; this app already has
   semantic tokens for exactly this ("did well" / "did badly"), so those are
   used instead. Intensity tracks |r| in two steps rather than a continuous
   ramp — a reader cannot tell 0.41 from 0.48 by shade, and pretending
   otherwise implies a precision twelve monthly points do not support. */
function cellStyle(r, isActive) {
  const base = {
    textAlign: "center", fontFamily: "var(--mono)", fontSize: 12,
    padding: "5px 4px", borderRadius: 2, fontVariantNumeric: "tabular-nums",
    outline: isActive ? "1px solid var(--ink-700)" : "none",
    fontWeight: isActive ? 600 : 400,
  };
  if (r === null || r === undefined) {
    return { ...base, color: "var(--stone-400)", background: "transparent" };
  }
  const a = Math.abs(r);
  if (a < 0.25) return { ...base, color: "var(--stone-500)", background: "var(--paper-100)" };
  if (r > 0) {
    return a > 0.55
      ? { ...base, background: "var(--positive-600)", color: "var(--paper-000)", fontWeight: 600 }
      : { ...base, background: "var(--positive-100)", color: "var(--positive-600)" };
  }
  return a > 0.55
    ? { ...base, background: "var(--critical-600)", color: "var(--paper-000)", fontWeight: 600 }
    : { ...base, background: "var(--critical-100)", color: "var(--critical-600)" };
}

/* What each factor is a proxy for, and what it is not. Kept beside the table
   because "Rates & duration +0.6" is actively misleading without knowing TLT
   rises when yields fall. */
function Methodology({ factors, min }) {
  return (
    <Card style={{ marginTop: 14 }}>
      <span className="microlabel">METHODOLOGY</span>
      <h3 style={{ font: "500 17px/1.2 var(--serif)", color: "var(--ink-800)",
                   margin: "5px 0 12px" }}>
        How this is calculated
      </h3>

      <p style={{ fontSize: 13, lineHeight: 1.6, margin: "0 0 11px", maxWidth: 760 }}>
        Each manager's stored monthly returns are compared, one factor at a time, against the
        months the two series genuinely share. The statistic in every cell is a{" "}
        <b>Pearson correlation coefficient</b> — a value from −1 to +1 measuring how closely a
        manager's month-to-month moves track a factor's, computed as the covariance of the two
        series over the product of their standard deviations. Near +1 the manager was up when
        the factor was up and down when it was down; near −1 the opposite; near 0 there is no
        consistent relationship. It is a same-month comparison with no lead or lag tested.
      </p>

      <p style={{ fontSize: 13, lineHeight: 1.6, margin: "0 0 11px", maxWidth: 760 }}>
        Correlation is not exposure. It says nothing about magnitude — a manager could move a
        fraction of a percent for every point the factor moves, or several points, and show the
        same coefficient, because the statistic captures direction and consistency, not size.
        That would need a regression beta, which this table does not compute. Nor is it "the
        share of return explained": that is r², which shrinks fast — a 0.5 correlation accounts
        for 25% of the variance.
      </p>

      <p style={{ fontSize: 13, lineHeight: 1.6, margin: "0 0 14px", maxWidth: 760 }}>
        Alignment is by calendar month, never by position, so a manager whose record starts
        mid-year is compared against the right months rather than the first ones. Below{" "}
        {min} shared months a cell reads “—” rather than a number, and the overlap can differ
        from column to column because the factor series do not all reach equally far back —
        hover any cell for the months actually used.
      </p>

      <div style={{ display: "grid", gap: "12px 22px",
                    gridTemplateColumns: "repeat(auto-fit,minmax(210px,1fr))",
                    borderTop: "1px solid var(--paper-200)", paddingTop: 13 }}>
        {factors.map((f) => (
          <div key={f.id}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink-800)" }}>
              {f.name}
            </div>
            <div className="muted" style={{ fontSize: 11.5, lineHeight: 1.5, marginTop: 2 }}>
              {f.description}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function FactorHeatmap() {
  const [matrix, setMatrix] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [sortBy, setSortBy] = React.useState(null);
  const hold = useScrollHold();

  React.useEffect(() => {
    get("/api/manager-factors").then(setMatrix).catch((e) => setError(e.message));
  }, []);

  if (error) {
    return (
      <Card>
        <ErrorNote error={error} />
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
          Factor data has no demo mode on purpose: a correlation computed against
          invented market data looks exactly like a real one. Set FRED_API_KEY and
          POLYGON_API_KEY in .env to switch this section on.
        </p>
      </Card>
    );
  }
  if (!matrix) {
    return (
      <Card>
        <div className="row">
          <Spinner />
          <span className="muted" style={{ fontSize: 13 }}>Fetching factor series…</span>
        </div>
      </Card>
    );
  }

  const { factors = [], managers = [], excluded = [], counts = {}, minimum_months: min } = matrix;

  const rows = sortBy
    ? [...managers].sort((a, b) => {
        const av = a.by_factor[sortBy]?.r, bv = b.by_factor[sortBy]?.r;
        if (av === null || av === undefined) return 1;
        if (bv === null || bv === undefined) return -1;
        return bv - av;
      })
    : managers;

  return (
    <>
      {managers.length > 0 && (
        <div className="row" style={{ gap: 5, marginBottom: 14 }}>
          <span className="microlabel" style={{ marginRight: 4 }}>RANK BY</span>
          <Pill on={!sortBy} onClick={() => hold(() => setSortBy(null))}>Manager name</Pill>
          {factors.map((f) => (
            <Pill key={f.id} on={f.id === sortBy}
                  onClick={() => hold(() => setSortBy(f.id === sortBy ? null : f.id))}>
              {f.name}
            </Pill>
          ))}
        </div>
      )}

      <Card style={{ overflowX: "auto", padding: "18px 20px" }}>
        {managers.length === 0 ? (
          <Empty>
            No manager has a stored return series yet. Correlation needs at least {min} aligned
            months, which a letter never carries — upload a track record on the Track records
            page, or connect Graph so emailed track records can be read automatically.
          </Empty>
        ) : (
          <>
            <table className="wb">
              <thead>
                <tr>
                  <th>Manager</th>
                  <th>Months</th>
                  {factors.map((f) => (
                    <th key={f.id} title={f.description}
                        style={{ color: f.id === sortBy ? "var(--ink-800)" : undefined }}>
                      {f.ticker}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((m) => (
                  <tr key={m.org}>
                    <td>
                      {m.org}
                      {m.strategy && (
                        <div className="muted" style={{ fontSize: 11.5 }}>{m.strategy}</div>
                      )}
                    </td>
                    <td className="muted" title={`${m.window.from} to ${m.window.to}`}>{m.months}</td>
                    {factors.map((f) => {
                      const cell = m.by_factor[f.id] || {};
                      const has = cell.r !== null && cell.r !== undefined;
                      return (
                        <td key={f.id} style={{ padding: "4px 3px" }}>
                          <div style={cellStyle(cell.r, f.id === sortBy)}
                               title={has ? `r = ${cell.r} over ${cell.n} months (${cell.from} to ${cell.to})`
                                          : `${cell.n || 0} overlapping months — below the ${min}-month minimum`}>
                            {has ? `${cell.r > 0 ? "+" : ""}${cell.r.toFixed(2)}` : "—"}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
              {counts.qualifying} of {counts.records_held} stored{" "}
              {counts.records_held === 1 ? "record" : "records"} had enough overlap to correlate.
              Olive cells are positive, brick negative, faint cells sit near zero; a dash means
              too few shared months, not a correlation of zero.
            </p>
          </>
        )}
      </Card>

      {excluded.length > 0 && (
        <div style={{ marginTop: 14 }}>
          {excluded.map((e, i) => (
            <div key={i} className="rrow">
              <div className="spread">
                <b style={{ fontSize: 13.5 }}>{e.org}</b>
                <span className="chip neutral">Not correlated</span>
              </div>
              <p className="muted" style={{ fontSize: 12.5, margin: "4px 0 0" }}>{e.reason}</p>
            </div>
          ))}
        </div>
      )}

      {factors.length > 0 && <Methodology factors={factors} min={min} />}
    </>
  );
}

/* Best and worst reported months, as editorial cards rather than a table: each
   one is a single figure a manager put in writing, and the basis it was stated
   on matters as much as the number. */
function Extremes({ title, tone, rows, empty }) {
  return (
    <section style={{ flex: "1 1 320px", minWidth: 0 }}>
      <div className="spread" style={{ paddingBottom: 10 }}>
        <span className="microlabel" style={{ color: tone }}>{title}</span>
      </div>
      {rows.length === 0 && <Empty>{empty}</Empty>}
      <Card style={{ padding: "6px 18px 14px" }}>
        {rows.map((r, i) => (
          <div key={i} style={{
            display: "grid", gridTemplateColumns: "1fr auto", gap: "4px 14px",
            padding: "12px 0", borderTop: i === 0 ? "none" : "1px solid var(--paper-200)",
          }}>
            <b style={{ fontSize: 13.5 }}>{r.org}</b>
            <span style={{ fontSize: 17, textAlign: "right" }}><Pct value={r.pct} /></span>
            <div className="mono" style={{ gridColumn: "1 / -1", fontSize: 10,
                                           letterSpacing: ".08em", textTransform: "uppercase",
                                           color: "var(--stone-400)" }}>
              {[r.month, r.basis].filter(Boolean).join(" · ")}
            </div>
            {r.fund && (
              <div className="muted" style={{ gridColumn: "1 / -1", fontSize: 12.5,
                                              lineHeight: 1.45 }}>
                {r.fund}
              </div>
            )}
          </div>
        ))}
      </Card>
    </section>
  );
}

const MONTH_LABEL = (m) => {
  const [y, mo] = (m || "").split("-");
  const names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[Number(mo)] || m} ${(y || "").slice(2)}`;
};

/* Best / median / worst reported month, drawn as a band.

   The band is the point: a month where the desk ranged from +17% to −1% is a
   different month from one where everybody landed within a point of each other,
   and a single average hides exactly that. Months carrying fewer than the
   backend's minimum number of reporting managers are absent by design, and the
   count of them is printed rather than left to be inferred from a gap. */
/* Group filter shared by the two cross-sectional charts. The subsets arrive
   from the backend already re-read per group (see _group_series in views.py)
   rather than sliced here, so a month too thin inside one mandate is excluded
   there too. */
function GroupPills({ groups, active, onSelect }) {
  if (!groups.length) return null;
  const pill = (on) => ({
    font: "500 10.5px/1 var(--mono)", letterSpacing: ".08em", textTransform: "uppercase",
    padding: "7px 11px", borderRadius: "var(--radius)", cursor: "pointer",
    border: `1px solid ${on ? "var(--teal-600)" : "var(--paper-300)"}`,
    background: on ? "var(--teal-600)" : "transparent",
    color: on ? "var(--paper-000)" : "var(--ink-700)",
  });
  return (
    <div className="row" style={{ gap: 6, flexWrap: "wrap", alignItems: "center" }}>
      <span className="microlabel" style={{ marginRight: 2 }}>GROUP</span>
      <button type="button" style={pill(!active)} onClick={() => onSelect("")}>All groups</button>
      {groups.map((g) => (
        <button type="button" key={g} style={pill(active === g)} onClick={() => onSelect(g)}>{g}</button>
      ))}
    </div>
  );
}

/* Stroke colours for the multi-line index, in draw order. Seven distinguishable
   strokes taken from the design system rather than a generated ramp — past
   about seven the reader is matching swatches instead of reading a chart. */
const VIZ = ["var(--teal-500)", "var(--ink-700)", "var(--brass-500)",
             "var(--slate-500)", "var(--teal-300)", "var(--stone-400)",
             "var(--critical-500)"];

/* A 760x300 frame with the right margin held open for end labels, so every
   line is named where it finishes rather than only in a legend the eye has to
   travel back to. */
const IDX = { w: 760, h: 300, padL: 48, padR: 150, padT: 16, padB: 30 };

/* "Hedge Funds - Single strategy" at the end of a line would need a margin
   wider than the plot. The family is initialised and the strategy kept whole,
   because the strategy is what tells one line from another; the legend below
   carries every name in full. */
function shortGroup(name) {
  const parts = String(name || "").split(" - ");
  const clip = (s) => (s.length > 20 ? `${s.slice(0, 19)}…` : s);
  if (parts.length < 2) return clip(String(name || ""));
  const family = parts[0].split(/\s+/).map((word) => word[0] || "").join("").toUpperCase();
  return clip(`${family} ${parts.slice(1).join(" · ")}`);
}

/* Every strategy group on one axis, equal weighted, rebased to 100.

   The charts below read one month at a time. This one reads the whole window,
   which is the only place on the page where mandates are set against each
   other — so the distance between two lines has to be trustworthy. Two things
   protect it: a month a group did not report is drawn as a dashed carry rather
   than a flat month, and the manager count sits in the legend, because a line
   whose constituents change is not a track record. */
function GroupIndex({ index }) {
  const months = index?.months || [];
  const groups = index?.groups || [];
  const unclassified = index?.unclassified || [];

  if (!groups.length || !months.length) {
    return (
      <Empty>
        No reporting manager resolved to a fund carrying an asset class, so there is nothing
        to index yet. The grouping is the <b>Asset Class</b> property on the Notion Funds
        database — it is never inferred from the letters.
      </Empty>
    );
  }

  const { w, h, padL, padR, padT, padB } = IDX;
  const values = groups.flatMap((g) => g.values).concat([index.base]);
  const min = Math.min(...values) * 0.98;
  const max = Math.max(...values) * 1.02;
  const span = max - min || 1;
  const xAt = (i) => padL + (months.length === 1 ? 0.5 : i / (months.length - 1))
                     * (w - padL - padR);
  const yAt = (v) => padT + (1 - (v - min) / span) * (h - padT - padB);

  /* Consecutive segments of the same kind are gathered into one path so the
     line keeps its joins, rather than being emitted a segment at a time. */
  const lines = groups.map((g, i) => {
    const runs = [];
    for (let j = 1; j < g.values.length; j += 1) {
      const carried = !g.reported[j];
      const last = runs[runs.length - 1];
      if (last && last.carried === carried) last.pts.push(j);
      else runs.push({ carried, pts: [j - 1, j] });
    }
    return {
      ...g,
      color: VIZ[i % VIZ.length],
      runs: runs.map((r) => ({
        carried: r.carried,
        d: r.pts.map((j, k) => `${k ? "L" : "M"}${xAt(j).toFixed(1)} ${yAt(g.values[j]).toFixed(1)}`)
          .join(" "),
      })),
    };
  });

  /* End labels stack rather than collide: sorted down the axis, each pushed
     clear of the one above it. Groups finishing a point apart is the common
     case, and an unreadable pile of labels is what this avoids. */
  const ends = lines
    .map((l, i) => ({
      key: i, color: l.color,
      y: yAt(l.values[l.values.length - 1]) + 4,
      text: `${shortGroup(l.group)} ${Math.round(l.end)}`,
    }))
    .sort((a, b) => a.y - b.y);
  for (let k = 1; k < ends.length; k += 1) {
    if (ends[k].y - ends[k - 1].y < 13) ends[k].y = ends[k - 1].y + 13;
  }

  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    f, y: padT + f * (h - padT - padB), label: Math.round(max - f * span),
  }));
  const tickStep = Math.max(1, Math.ceil(months.length / 6));
  const baseY = yAt(index.base);
  const carriedAnywhere = groups.some((g) => g.reported.some((r) => !r));

  return (
    <Card style={{ padding: "20px 22px 16px", marginBottom: 16 }}>
      <div className="spread" style={{ alignItems: "baseline", gap: 24, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0, font: "500 19px/1.2 var(--serif)", color: "var(--ink-900)",
                     letterSpacing: "-.015em" }}>
          Strategy group index, equal weighted
        </h3>
        <span className="microlabel">
          {index.base} = START OF {MONTH_LABEL(index.base_month).toUpperCase()}
        </span>
      </div>

      <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: "auto",
                                              display: "block", marginTop: 14 }}>
        {grid.map((g) => (
          <line key={g.f} x1={padL} x2={w - padR} y1={g.y} y2={g.y}
                stroke="var(--paper-200)" strokeWidth="1" />
        ))}
        {grid.map((g) => (
          <text key={`l${g.f}`} x={padL - 8} y={g.y + 4} textAnchor="end"
                fill="var(--stone-400)"
                style={{ fontFamily: "var(--mono)", fontSize: "10px" }}>
            {g.label}
          </text>
        ))}

        {/* Where the index started. Drawn rather than plotted: no month sits
            at 100, because every point already carries that month's return. */}
        <line x1={padL} x2={w - padR} y1={baseY} y2={baseY}
              stroke="var(--stone-400)" strokeWidth="1" strokeDasharray="3 3" />

        {months.map((m, i) => (i % tickStep === 0 ? (
          <text key={m} x={xAt(i)} y={h - 8} textAnchor="middle" fill="var(--stone-400)"
                style={{ fontFamily: "var(--mono)", fontSize: "10px" }}>
            {MONTH_LABEL(m)}
          </text>
        ) : null))}

        {lines.map((l) => (
          <g key={l.group}>
            <title>
              {`${l.group} — ${l.manager_count} manager(s), `
               + `${l.months_reported} of ${months.length} months reported, `
               + `index ${l.end.toFixed(1)}`}
            </title>
            {l.runs.map((r, k) => (
              <path key={k} d={r.d} fill="none" stroke={l.color} strokeWidth="1.75"
                    strokeLinejoin="round"
                    strokeDasharray={r.carried ? "3 3" : undefined}
                    opacity={r.carried ? 0.55 : 1} />
            ))}
            {months.length === 1 && (
              <circle cx={xAt(0)} cy={yAt(l.values[0])} r="3" fill={l.color} />
            )}
          </g>
        ))}

        {ends.map((e) => (
          <text key={e.key} x={w - padR + 8} y={e.y} textAnchor="start" fill={e.color}
                style={{ fontFamily: "var(--mono)", fontSize: "10.5px" }}>
            {e.text}
          </text>
        ))}
      </svg>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "12px 28px",
                    borderTop: "1px solid var(--paper-200)", paddingTop: 14, marginTop: 4 }}>
        {lines.map((l) => (
          <span key={l.group} title={(l.managers || []).join(" · ")}
                style={{ display: "inline-flex", alignItems: "center", gap: 8,
                         fontSize: 12, color: "var(--stone-600)" }}>
            <span style={{ width: 10, height: 2, background: l.color, display: "inline-block" }} />
            {l.group}
            <span className="mono" style={{ color: "var(--stone-400)", fontSize: 11 }}>
              {l.manager_count} {l.manager_count === 1 ? "manager" : "managers"}
            </span>
          </span>
        ))}
      </div>

      <p className="muted" style={{ fontSize: 11.5, lineHeight: 1.55, margin: "12px 0 0" }}>
        Each line compounds the equal-weighted mean of its group's managers, from the months
        those managers put in writing. It is not a track record: the set reporting changes
        month to month, which is why the manager count sits beside every name.
        {carriedAnywhere && " A dashed stretch is a month the group reported nothing — the "
         + "index is carried at its level rather than assumed flat."}
        {unclassified.length > 0 && ` ${unclassified.length} reporting manager(s) did not `
         + `resolve to a fund carrying an asset class and are indexed nowhere above: `
         + `${unclassified.join(", ")}.`}
      </p>
    </Card>
  );
}

/* Best to worst manager, every month: a shaded band between the best and worst
   reported month with the median through it. A wide band under a flat median is
   the shape worth worrying about — the desk average hiding a scattering
   underneath it. */
const DISP = { w: 760, h: 240, padL: 48, padR: 24, padT: 16, padB: 30 };

function Dispersion({ dispersion }) {
  const byGroup = dispersion?.by_group || {};
  const [group, setGroup] = React.useState("");
  const [hover, setHover] = React.useState(null);
  const hold = useScrollHold();
  const view = (group && byGroup[group]) || dispersion?.all || {};
  const series = view.series || [];

  const widest = series.reduce((a, b) => (a === null || b.spread > a.spread ? b : a), null);
  const narrowest = series.reduce((a, b) => (a === null || b.spread < a.spread ? b : a), null);
  const widestAt = widest ? series.indexOf(widest) : -1;

  const { w, h, padL, padR, padT, padB } = DISP;
  const lo = series.length ? Math.min(...series.map((s) => s.worst)) : 0;
  const hi = series.length ? Math.max(...series.map((s) => s.best)) : 0;
  const bottom = lo - 2, top = hi + 2;
  const span = top - bottom || 1;
  const y = (v) => padT + (1 - (v - bottom) / span) * (h - padT - padB);
  const x = (i) => padL + (series.length === 1 ? 0.5 : i / (series.length - 1))
                   * (w - padL - padR);
  const line = (key) => series
    .map((s, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(s[key]).toFixed(1)}`).join(" ");
  const band = series.length
    ? line("best") + " " + series.slice().reverse()
        .map((s, i) => `L${x(series.length - 1 - i).toFixed(1)} ${y(s.worst).toFixed(1)}`)
        .join(" ") + " Z"
    : "";
  const grid = [0, 0.5, 1].map((f) => ({
    f, y: padT + f * (h - padT - padB), label: Math.round(top - f * span),
  }));
  const tickStep = Math.max(1, Math.ceil(series.length / 6));
  /* The widest month is called out in place. Its label is pushed inside the
     frame at either end so it is never clipped by the plot edge. */
  const markAnchor = series.length - 1 - widestAt <= 2 ? "end"
    : widestAt <= 2 ? "start" : "middle";
  const markX = widestAt < 0 ? 0
    : markAnchor === "end" ? x(widestAt) - 6
    : markAnchor === "start" ? x(widestAt) + 6 : x(widestAt);
  const at = hover === null ? null : series[hover];

  return (
    <Card style={{ padding: "20px 22px 14px", marginBottom: 16 }}>
      <div className="spread" style={{ alignItems: "flex-start", gap: 24, flexWrap: "wrap" }}>
        <div style={{ maxWidth: 620 }}>
          <h3 style={{ margin: 0, font: "500 19px/1.2 var(--serif)", color: "var(--ink-900)" }}>
            Best to worst manager, every month
          </h3>
          <p className="muted" style={{ fontSize: 12, lineHeight: 1.5, margin: "6px 0 0" }}>
            {widest
              ? `Widest spread between the best and worst manager in a single month, in ${MONTH_LABEL(widest.month)}. The narrowest was ${narrowest.spread.toFixed(1)} points.`
              : "Not enough reporting managers in any month to read a spread."}
          </p>
        </div>
        {widest && (
          <div className="mono" style={{ font: "500 30px/1 var(--mono)", color: "var(--ink-900)",
                                         fontVariantNumeric: "tabular-nums" }}>
            {widest.spread.toFixed(1)} points
          </div>
        )}
      </div>

      <div style={{ margin: "14px 0 10px" }}>
        <GroupPills groups={Object.keys(byGroup)} active={group}
                    onSelect={(g) => hold(() => setGroup(g))} />
      </div>

      {series.length === 0 ? (
        <Empty>
          No month here has {view.min_reporters || 3} managers reporting a figure, which is the
          fewest that makes a spread mean anything.
        </Empty>
      ) : (
        <>
          <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: "auto",
                                                  display: "block" }}>
            {grid.map((g) => (
              <line key={g.f} x1={padL} x2={w - padR} y1={g.y} y2={g.y}
                    stroke="var(--paper-200)" strokeWidth="1" />
            ))}
            {grid.map((g) => (
              <text key={`l${g.f}`} x={padL - 8} y={g.y + 4} textAnchor="end"
                    fill="var(--stone-400)"
                    style={{ fontFamily: "var(--mono)", fontSize: "10px" }}>
                {g.label}%
              </text>
            ))}

            <path d={band} fill="var(--teal-100)" stroke="none" />
            {bottom < 0 && top > 0 && (
              <line x1={padL} x2={w - padR} y1={y(0)} y2={y(0)}
                    stroke="var(--stone-400)" strokeWidth="1" />
            )}
            <path d={line("median")} fill="none" stroke="var(--ink-700)" strokeWidth="1.75"
                  strokeLinejoin="round" />

            {widestAt >= 0 && series.length > 1 && (
              <>
                <line x1={x(widestAt)} x2={x(widestAt)} y1={padT + 8} y2={h - padB}
                      stroke="var(--brass-500)" strokeWidth="1" strokeDasharray="2 3" />
                <text x={markX} y={padT + 12} textAnchor={markAnchor} fill="var(--brass-700)"
                      style={{ fontFamily: "var(--mono)", fontSize: "10px" }}>
                  {`${MONTH_LABEL(widest.month)} · ${widest.spread.toFixed(1)} points`}
                </text>
              </>
            )}

            {series.map((s, i) => (i % tickStep === 0 ? (
              <text key={s.month} x={x(i)} y={h - 8} textAnchor="middle" fill="var(--stone-400)"
                    style={{ fontFamily: "var(--mono)", fontSize: "10px" }}>
                {MONTH_LABEL(s.month)}
              </text>
            ) : null))}

            {hover !== null && (
              <line x1={x(hover)} x2={x(hover)} y1={padT} y2={h - padB}
                    stroke="var(--ink-700)" strokeWidth="1" strokeDasharray="2 2" />
            )}

            {series.map((s, i) => {
              const cw = (w - padL - padR) / series.length;
              return (
                <rect key={s.month} x={padL + i * cw} y="0" width={cw} height={h}
                      fill="transparent" style={{ cursor: "default" }}
                      onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                  <title>
                    {`${s.month} — best ${s.best_org} ${s.best > 0 ? "+" : ""}`
                     + `${s.best.toFixed(2)}%  ·  worst ${s.worst_org} `
                     + `${s.worst.toFixed(2)}%  ·  ${s.reporters} managers`}
                  </title>
                </rect>
              );
            })}
          </svg>

          {/* Held open whether or not anything is hovered: a readout that
              appears and disappears reflows the section under the cursor. */}
          <div className="mono" style={{ fontSize: 11.5, minHeight: 34, marginTop: 8,
                borderRadius: "var(--radius)", padding: "8px 11px",
                color: at ? "var(--ink-700)" : "var(--stone-400)",
                background: at ? "var(--paper-100)" : "transparent",
                border: `1px solid ${at ? "var(--paper-300)" : "transparent"}` }}>
            {at
              ? `${MONTH_LABEL(at.month)} — best ${at.best_org} ${at.best > 0 ? "+" : ""}`
                + `${at.best.toFixed(2)}%  ·  median ${at.median.toFixed(2)}%  ·  worst `
                + `${at.worst_org} ${at.worst.toFixed(2)}%  ·  ${at.reporters} managers`
              : "Hover a month for the best and worst manager in it."}
          </div>
        </>
      )}
      <p className="muted" style={{ fontSize: 11.5, lineHeight: 1.5, margin: "12px 0 0" }}>
        Shaded band spans the best and worst reported month across every manager; the dark line is
        the median. A wide band with a flat median is the shape the desk should worry about. Hover
        any month for the best and worst manager. A manager stating several funds for one month
        counts once, averaged.
        {view.months_too_thin > 0 && ` ${view.months_too_thin} further month(s) had fewer than ${view.min_reporters} managers reporting and are left out.`}
      </p>
    </Card>
  );
}

/* How widely, rather than how much: each bar is the full set of managers who
   reported that month, split by sign. Every month appears, thin ones included —
   one-of-one is a true statement about breadth, where a "spread" of one manager
   is not — with the count under each bar so a single-manager month is never
   read as a verdict on the desk. */
const BRD = { w: 760, h: 210, padL: 48, padR: 24, padT: 18, padB: 44 };

function Breadth({ breadth }) {
  const byGroup = breadth?.by_group || {};
  const [group, setGroup] = React.useState("");
  const hold = useScrollHold();
  const view = (group && byGroup[group]) || breadth?.all || {};
  const series = view.series || [];

  const { w, h, padL, padR, padT, padB } = BRD;
  const H = h - padT - padB;
  const colW = series.length ? (w - padL - padR) / series.length : 0;
  const barW = Math.max(3, colW - 10);
  const midY = padT + 0.5 * H;
  const anyFlat = series.some((s) => s.flat > 0);
  const tickStep = Math.max(1, Math.ceil(series.length / 8));

  return (
    <Card style={{ padding: "20px 22px 16px" }}>
      <h3 style={{ margin: 0, font: "500 19px/1.2 var(--serif)", color: "var(--ink-900)" }}>
        Breadth — share of managers positive each month
      </h3>
      <div style={{ margin: "12px 0 14px" }}>
        <GroupPills groups={Object.keys(byGroup)} active={group}
                    onSelect={(g) => hold(() => setGroup(g))} />
      </div>

      {series.length === 0 ? <Empty>No reported months yet.</Empty> : (
        <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: "auto", display: "block" }}>
          {[0, 1].map((f) => (
            <line key={f} x1={padL} x2={w - padR} y1={padT + f * H} y2={padT + f * H}
                  stroke="var(--paper-200)" strokeWidth="1" />
          ))}
          {[0, 0.5, 1].map((f) => (
            <text key={f} x={padL - 8} y={padT + f * H + 4} textAnchor="end"
                  fill="var(--stone-400)"
                  style={{ fontFamily: "var(--mono)", fontSize: "10px" }}>
              {Math.round(100 - f * 100)}%
            </text>
          ))}

          {series.map((s, i) => {
            const x = padL + i * colW + (colW - barW) / 2;
            const cx = x + barW / 2;
            // Three segments, not two. A manager who reported exactly flat is
            // neither up nor down, and colouring it as a loss overstates how
            // badly a month went.
            const upH = (s.positive / s.reporters) * H;
            const flatH = (s.flat / s.reporters) * H;
            const downH = H - upH - flatH;
            const thin = s.reporters < 3;
            return (
              <g key={s.month} opacity={thin ? 0.5 : 1}>
                <rect x={x} y={padT} width={barW} height={upH} fill="var(--teal-500)" />
                {flatH > 0 && (
                  <rect x={x} y={padT + upH} width={barW} height={flatH} fill="var(--stone-300)" />
                )}
                <rect x={x} y={padT + upH + flatH} width={barW} height={downH}
                      fill="var(--critical-500)" />
                <text x={cx} y={padT - 6} textAnchor="middle" fill="var(--ink-800)"
                      style={{ fontFamily: "var(--mono)", fontSize: "10px" }}>
                  {Math.round(s.share * 100)}%
                </text>
                {i % tickStep === 0 && (
                  <text x={cx} y={h - 26} textAnchor="middle" fill="var(--stone-400)"
                        style={{ fontFamily: "var(--mono)", fontSize: "9px" }}>
                    {MONTH_LABEL(s.month)}
                  </text>
                )}
                <text x={cx} y={h - 12} textAnchor="middle" fill="var(--stone-400)"
                      style={{ fontFamily: "var(--mono)", fontSize: "8px" }}>
                  {s.positive}/{s.reporters}
                </text>
                <rect x={padL + i * colW} y="0" width={colW} height={h} fill="transparent">
                  <title>
                    {`${s.month} — ${s.positive} of ${s.reporters} positive `
                     + `(${Math.round(s.share * 100)}%), ${s.negative} negative`
                     + (s.flat ? `, ${s.flat} flat` : "")}
                  </title>
                </rect>
              </g>
            );
          })}

          {/* Half the desk. The line the eye actually compares each bar against. */}
          <line x1={padL} x2={w - padR} y1={midY} y2={midY} stroke="var(--ink-700)"
                strokeWidth="1" strokeDasharray="3 3" />
        </svg>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: "12px 28px", flexWrap: "wrap",
                    borderTop: "1px solid var(--paper-200)", paddingTop: 14, marginTop: 4 }}>
        {[["Positive", "var(--teal-500)"],
          ...(anyFlat ? [["Flat", "var(--stone-300)"]] : []),
          ["Negative", "var(--critical-500)"]].map(([label, colour]) => (
            <span key={label} style={{ display: "inline-flex", alignItems: "center", gap: 8,
                                       fontSize: 12, color: "var(--stone-600)" }}>
              <span style={{ width: 12, height: 12, borderRadius: 2, background: colour,
                             display: "inline-block" }} />
              {label}
            </span>
          ))}
      </div>

      <p className="muted" style={{ fontSize: 11.5, lineHeight: 1.5, margin: "12px 0 0" }}>
        Each bar is the full set of managers reporting that month, split by sign; the figure above
        is the share positive and the figure below the count. The dashed rule is half the desk.
        Faded bars rest on fewer than three managers and describe those managers, not the desk.
      </p>
    </Card>
  );
}

/* "Manager performance" — reported figures, and their relationship to markets. */
export default function Managers({ data }) {
  const groupIndex = data.group_index || {};
  const tracks = data.manager_tracks || {};
  // Dispersion and breadth now arrive as {all, by_group} so each chart can be
  // filtered to one mandate — see _group_series in views.py for why the subset
  // is re-read rather than sliced.
  const dispersion = data.dispersion || {};
  const breadth = data.breadth || {};
  const monitor = data.monitor || [];

  return (
    <div className="fade-in">
      <SectionHead
        label="CORRELATION TO THE STANDARD FACTORS"
        right={data.track_records_held ? `${data.track_records_held} TRACK RECORDS HELD` : ""} />
      <FactorHeatmap />

      {/* One consolidated reading rather than a card per group: the question
          this section answers is which mandate is ahead of which, and that is
          a comparison, not a set of separate small facts. */}
      <SectionHead
        label="HOW EACH STRATEGY GROUP IS DOING"
        right={groupIndex.groups?.length ? `${groupIndex.groups.length} GROUP(S)` : ""}
        style={{ paddingTop: 30 }} />
      <GroupIndex index={groupIndex} />

      <ManagerTracks tracks={tracks} />

      <div className="panes" style={{ marginTop: 30 }}>
        <Extremes title="STANDING OUT" tone="var(--positive-600)" rows={data.standouts || []}
                  empty="No reported figures yet. These come from months a manager put a number to in writing." />
        <Extremes title="UNDER STRAIN" tone="var(--critical-600)" rows={data.strained || []}
                  empty="Nothing reported yet." />
      </div>

      <SectionHead label="ACROSS EVERY MANAGER" style={{ paddingTop: 30 }} />
      <Dispersion dispersion={dispersion} />
      <Breadth breadth={breadth} />

      {/* The watchlist reads the reported figures and the silences around them,
          so it belongs beside the performance it is drawn from rather than on
          the desk view where the themes live. */}
      <Watchlist monitor={monitor} />
    </div>
  );
}

/* One manager per row, inside its strategy group. Every figure is computed from
   months the manager stated in writing, and the SOURCE column says how many
   that was — a total built from two reported months is not a year, and that
   column is what stops it being read as one. */
const TRACK_COLS = "minmax(150px,1.6fr) minmax(90px,1.1fr) 78px 78px 78px 92px 74px";

function Sparkline({ months }) {
  if (months.length < 2) {
    return (
      <span className="mono" style={{ fontSize: 10, color: "var(--stone-400)" }}>
        {months.length ? "one month" : "—"}
      </span>
    );
  }
  const pts = [];
  let level = 1;
  months.forEach((m) => { level *= 1 + m.pct / 100; pts.push(level); });
  const lo = Math.min(...pts), hi = Math.max(...pts);
  const span = hi - lo || 1;
  const d = pts.map((p, i) => {
    const x = (i / (pts.length - 1)) * 100;
    const y = 22 - ((p - lo) / span) * 20;
    return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const up = pts[pts.length - 1] >= pts[0];
  return (
    <svg viewBox="0 0 100 24" preserveAspectRatio="none"
         style={{ width: "100%", height: 24, display: "block" }}>
      <path d={d} fill="none" strokeWidth="1.4" vectorEffect="non-scaling-stroke"
            stroke={up ? "var(--positive-600)" : "var(--critical-600)"} />
    </svg>
  );
}

/* Stance per sampled window, oldest left. An empty box is a window the manager
   did not write in — a gap, not a neutral, which is the distinction the whole
   page rests on.

   A box with a letter behind it opens it. The stance is a reading of that
   letter, and a coloured square nobody can open asks to be taken on trust —
   so the square is the claim and the drawer is the evidence for it. */
function Tone({ tone, periods, org, onOpen }) {
  return (
    <div className="row" style={{ gap: 3 }}>
      {tone.map((cell, i) => {
        const stance = cell?.stance || "";
        const box = {
          width: 11, height: 11, borderRadius: 1, padding: 0,
          border: `1px solid ${stance ? "transparent" : "var(--paper-300)"}`,
          background: stance ? (STANCE_COLOR[stance] || "var(--stone-400)") : "transparent",
        };
        if (!cell) {
          return <span key={i} style={box}
                       title={`${periods[i]?.short || ""}: no letter`} />;
        }
        const n = cell.letters?.length || 0;
        return (
          <button key={i} type="button" style={{ ...box, cursor: "pointer" }}
                  onClick={() => onOpen({ org, cell, period: periods[i] })}
                  aria-label={`${org}, ${periods[i]?.short || "window"}: ${stance}`
                              + ` — open ${n} letter${n === 1 ? "" : "s"}`}
                  title={`${periods[i]?.short || ""}: ${stance} — click to read`} />
        );
      })}
    </div>
  );
}

/* What sits behind one tone box: every letter the manager wrote in that
   window, its quotes, and the way back to the original message. */
function ToneDrawer({ open, onClose }) {
  const letters = open?.cell?.letters || [];
  return (
    <Drawer
      open={!!open}
      onClose={onClose}
      eyebrow={`${open?.period?.short || ""} · ${STANCE_LABEL[open?.cell?.stance] || ""}`}
      title={open?.org || ""}>
      <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.55, margin: "0 0 4px" }}>
        {letters.length === 1
          ? "The letter this window's stance was read from."
          : `${letters.length} letters in this window. The box takes the stance of the `
            + "latest; all of them are here."}
      </p>

      {letters.map((l, i) => (
        <section key={i} style={{ marginTop: 16 }}>
          <div className="spread" style={{ alignItems: "baseline", gap: 10 }}>
            <span className="row" style={{ gap: 8 }}>
              <StanceChip stance={l.stance} />
              <span className="mono" style={{ fontSize: 10.5, color: "var(--stone-400)" }}>
                {l.date}
              </span>
            </span>
            {l.web_link && (
              <a href={l.web_link} target="_blank" rel="noreferrer" className="mono"
                 style={{ fontSize: 10, letterSpacing: ".1em", textTransform: "uppercase",
                          color: "var(--teal-700)", whiteSpace: "nowrap" }}>
                Open in Outlook
              </a>
            )}
          </div>
          {(l.source || l.person) && (
            <div className="mono" style={{ fontSize: 10, letterSpacing: ".08em",
                  textTransform: "uppercase", color: "var(--stone-400)", marginTop: 4 }}>
              {[l.person, l.source].filter(Boolean).join(" · ")}
            </div>
          )}
          {l.quotes.length === 0 ? (
            <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.5, margin: "10px 0 0" }}>
              Nothing was quotable from this one — it reported without commenting. The stance
              is the letter's posture, and the link above is the letter itself.
            </p>
          ) : (
            l.quotes.map((q, j) => (
              <QuoteBlock key={j} showOrg={false}
                          v={{ ...q, date: "", org: open.org, person: l.person }} />
            ))
          )}
        </section>
      ))}
    </Drawer>
  );
}

function ManagerTracks({ tracks }) {
  const groups = tracks?.groups || [];
  const periods = tracks?.periods || [];
  const unclassified = tracks?.unclassified || [];
  const [openTone, setOpenTone] = React.useState(null);

  if (!groups.length) {
    return (
      <>
        <SectionHead label="MANAGER BY MANAGER" style={{ paddingTop: 30 }} />
        <Empty>
          No manager has reported a figure that could be matched to a strategy yet.
        </Empty>
      </>
    );
  }

  const row = (m, i, last) => (
    <div key={m.org} style={{ display: "grid", gridTemplateColumns: TRACK_COLS,
                              alignItems: "center", gap: 12, padding: "11px 0",
                              borderBottom: last ? "none" : "1px solid var(--paper-200)" }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--ink-800)" }}>{m.org}</div>
        {m.mandate && (
          <div className="muted" style={{ fontSize: 11.5, overflow: "hidden",
                                          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {m.mandate}
          </div>
        )}
      </div>
      <Sparkline months={m.months} />
      <div className="mono" style={{ textAlign: "right", fontSize: 14, fontWeight: 600,
            color: m.total >= 0 ? "var(--positive-600)" : "var(--critical-600)" }}>
        {m.total >= 0 ? "+" : ""}{m.total.toFixed(1)}%
      </div>
      <div className="mono" style={{ textAlign: "right", fontSize: 12.5, color: "var(--critical-600)" }}>
        {m.worst.toFixed(1)}%
      </div>
      <div className="mono" style={{ textAlign: "right", fontSize: 12.5, color: "var(--stone-600)" }}>
        {m.max_drawdown ? `${m.max_drawdown.toFixed(1)}%` : "—"}
      </div>
      <Tone tone={m.tone} periods={periods} org={m.org} onOpen={setOpenTone} />
      <div className="mono" style={{ textAlign: "right", fontSize: 10, letterSpacing: ".06em",
            textTransform: "uppercase", color: "var(--stone-400)" }}>
        {m.reported} rep.
      </div>
    </div>
  );

  return (
    <>
      <SectionHead label="MANAGER BY MANAGER"
                   right={`${groups.reduce((n, g) => n + g.manager_count, 0)} REPORTING`}
                   style={{ paddingTop: 30 }} />
      <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.55, margin: "0 0 14px" }}>
        Totals compound only the months each manager put in writing, so they are not
        twelve-month returns and the count on the right says what they actually are. Max drawdown
        runs along that same reported path. Tone is the stance of each letter across the five
        sampled windows, oldest first; an empty box is a window with no letter. Click any
        filled box to read the letter it was drawn from.
      </p>

      {groups.map((g) => (
        <Card key={g.group} style={{ padding: "18px 22px", marginBottom: 14, overflowX: "auto" }}>
          <div className="spread" style={{ alignItems: "baseline", marginBottom: 10 }}>
            <h3 style={{ margin: 0, font: "500 17px/1.2 var(--serif)", color: "var(--ink-900)" }}>
              {g.group}
            </h3>
            <span className="mono" style={{ fontSize: 11, color: "var(--stone-500)" }}>
              {g.manager_count} {g.manager_count === 1 ? "manager" : "managers"}
              {"  "}
              <span style={{ color: g.mean_total >= 0 ? "var(--positive-600)" : "var(--critical-600)" }}>
                {g.mean_total >= 0 ? "+" : ""}{g.mean_total.toFixed(1)}% mean
              </span>
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: TRACK_COLS, gap: 12,
                        paddingBottom: 6, borderBottom: "1px solid var(--ink-600)" }}>
            {[["Manager", "left"], ["Reported months", "left"], ["Total", "right"],
              ["Worst", "right"], ["Max DD", "right"], ["Tone", "left"], ["Source", "right"]]
              .map(([h, align]) => (
                <span key={h} className="microlabel" style={{ textAlign: align }}>{h}</span>
              ))}
          </div>
          {g.managers.map((m, i) => row(m, i, i === g.managers.length - 1))}
        </Card>
      ))}

      {unclassified.length > 0 && (
        <p className="muted" style={{ fontSize: 12, lineHeight: 1.55, margin: "0 0 8px" }}>
          {unclassified.length} further {unclassified.length === 1 ? "manager reports" : "managers report"}
          {" "}figures but could not be matched to a fund in Notion, so they carry no strategy:
          {" "}{unclassified.map((m) => m.org).join(", ")}. A wrong strategy label would be worse
          than this gap.
        </p>
      )}

      <ToneDrawer open={openTone} onClose={() => setOpenTone(null)} />
    </>
  );
}

/* Managers to keep an eye on. Built from gaps rather than from figures — a
   reported drawdown with no commentary, a manager gone quiet, a track record
   nobody can open — which is why it sits with the performance it reads. */
function Watchlist({ monitor }) {
  const [severity, setSeverity] = React.useState("all");
  // The watchlist is the page's last section: filtering 45 cards down to 13
  // removes more height than sits below the scroll, and the browser's clamp
  // read as "back to the top" (user, 21 Aug 2026).
  const hold = useScrollHold();
  const counts = { urgent: 0, attention: 0, watch: 0 };
  monitor.forEach((m) => { if (counts[m.severity] !== undefined) counts[m.severity] += 1; });
  const shown = severity === "all" ? monitor : monitor.filter((m) => m.severity === severity);

  return (
    <>
      <SectionHead label="THE WATCHLIST"
                   right={monitor.length ? `${shown.length} OF ${monitor.length}` : ""}
                   style={{ paddingTop: 30 }} />
      <h3 style={{ margin: "0 0 6px", font: "400 26px/1.2 var(--serif)", color: "var(--ink-900)" }}>
        Managers to keep an eye on
      </h3>
      <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.55, margin: "0 0 14px",
                                    maxWidth: 720 }}>
        Flags are read straight from the correspondence and the reported figures — nothing is
        inferred beyond what a manager sent, or conspicuously did not.
      </p>

      {monitor.length === 0 ? (
        <Empty>
          Nothing flagged. This list is built from gaps — a reported drawdown with no commentary,
          a manager who has gone quiet, a track record nobody can open.
        </Empty>
      ) : (
        <>
          <div className="row" style={{ gap: 6, marginBottom: 16 }}>
            <Pill on={severity === "all"} onClick={() => hold(() => setSeverity("all"))}
                  count={monitor.length}>
              All
            </Pill>
            {["urgent", "attention", "watch"].map((s) => (
              <Pill key={s} on={severity === s} onClick={() => hold(() => setSeverity(s))}
                    count={counts[s]}>
                {SEVERITY_LABEL[s]}
              </Pill>
            ))}
          </div>
          <div style={{ display: "grid", gap: 14,
                        gridTemplateColumns: "repeat(auto-fit,minmax(340px,1fr))" }}>
            {shown.map((m, i) => (
              <Card key={i} style={{ borderLeft: `3px solid ${SEVERITY_COLOR[m.severity] || "var(--stone-400)"}`,
                                     display: "flex", flexDirection: "column", gap: 7 }}>
                <div className="spread" style={{ alignItems: "baseline" }}>
                  <b style={{ fontSize: 14 }}>{m.org}</b>
                  <span className={`chip ${SEVERITY_TONE[m.severity] || "neutral"}`}>
                    {SEVERITY_LABEL[m.severity] || m.severity}
                  </span>
                </div>
                <span className="microlabel">{m.category}</span>
                <p style={{ font: "400 14px/1.45 var(--serif)", color: "var(--ink-800)", margin: 0 }}>
                  {m.headline}
                </p>
                {m.detail && (
                  <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.5, margin: 0 }}>
                    {m.detail}
                  </p>
                )}
                {m.date && (
                  <div className="mono" style={{ fontSize: 10, letterSpacing: ".08em",
                        textTransform: "uppercase", color: "var(--stone-400)", marginTop: "auto",
                        paddingTop: 8, borderTop: "1px solid var(--paper-200)" }}>
                    Heard {m.date}
                  </div>
                )}
              </Card>
            ))}
          </div>
        </>
      )}
    </>
  );
}
