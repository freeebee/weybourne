import React from "react";

/* Vocabulary shared by the three Inbox Signal tabs.

   Colours come from theme.css tokens rather than literals wherever a class
   exists for the job — the original standalone dashboard was already built on
   these same tokens, so the port is a rename rather than a re-theme. Hex values
   appear only where an inline style needs one (SVG fills, computed heatmap
   backgrounds) and are the exact values of the corresponding var. */

export const STANCE_TONE = {
  constructive: "positive",
  cautious: "caution",
  negative: "critical",
  neutral: "neutral",
};

export const STANCE_LABEL = {
  constructive: "Constructive",
  cautious: "Cautious",
  negative: "Negative",
  neutral: "Neutral",
};

/* Fixed reading order, so a stance mix renders in the same sequence
   everywhere — a bar whose segments reorder between rows cannot be compared
   across rows. */
export const STANCE_ORDER = ["constructive", "cautious", "negative", "neutral"];

/* The stances that carry a view, for the sections that exist to be read.
   A neutral letter is one that reported without taking a position — a NAV
   notice, a factsheet, "we will circulate the official numbers on the 12th" —
   and quoting it under a heading about what the desk is saying fills the
   section with sentences nobody needs to read.

   Neutral stays in STANCE_ORDER because it is still a true fact about a
   letter: it is counted in the stance mixes, kept as a filter in the
   correspondence log, and still colours a tone box. It is only dropped from
   the places whose whole purpose is to surface an opinion. */
export const STANCE_WITH_A_VIEW = ["constructive", "cautious", "negative"];

export const STANCE_COLOR = {
  constructive: "var(--positive-600)",
  cautious: "var(--caution-600)",
  negative: "var(--critical-600)",
  neutral: "var(--stone-400)",
};

export const STANCE_SURFACE = {
  constructive: "var(--positive-100)",
  cautious: "var(--caution-100)",
  negative: "var(--critical-100)",
  neutral: "var(--paper-100)",
};

export const SEVERITY_TONE = {
  urgent: "critical",
  attention: "caution",
  watch: "teal",
};

export const SEVERITY_LABEL = {
  urgent: "Urgent",
  attention: "Attention",
  watch: "Watch",
};

export const SEVERITY_COLOR = {
  urgent: "var(--critical-600)",
  attention: "var(--caution-600)",
  watch: "var(--teal-600)",
};

/* theme.css values, needed where a CSS class cannot reach (SVG, computed bg). */
export const VIZ = ["var(--teal-500)", "var(--ink-700)", "var(--brass-500)",
                    "var(--slate-500)", "var(--teal-300)", "var(--stone-400)",
                    "var(--critical-500)"];

export const HEX = {
  teal500: "#2E8B84", ink700: "#1D3D52", brass500: "#B0894E",
  slate500: "#4F6D7C", teal300: "#84C7C2", stone400: "#9A9385",
  critical500: "#AE4A3C", paper200: "#EFE9DC", paper300: "#E4DCCB",
};

/* .main publishes its own side padding as --gutter (see theme.css) so a section
   can bleed to the full content width and pad itself back — the sticky lookback
   bar and the banded background both run edge to edge while their contents stay
   aligned with the rest of the page. Reading the variable rather than repeating
   the clamp keeps the bleed correct at mobile, where the padding drops to 16px. */
export const GUTTER = "var(--gutter)";

export function StanceChip({ stance }) {
  if (!stance) return <span className="muted" style={{ fontSize: 12 }}>—</span>;
  return <span className={`chip ${STANCE_TONE[stance] || "neutral"}`}>
    {STANCE_LABEL[stance] || stance}
  </span>;
}

/* A figure that carries its own sign and colour. Percentages are the one thing
   on this dashboard a reader scans rather than reads, so they get mono,
   tabular numerals and a consistent sign convention. */
export function Pct({ value, digits = 2 }) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return <span className="muted mono" style={{ fontSize: 12.5 }}>—</span>;
  }
  const tone = value > 0 ? "var(--positive-600)" : value < 0 ? "var(--critical-600)" : "var(--stone-500)";
  return (
    <span className="mono" style={{ color: tone, fontVariantNumeric: "tabular-nums" }}>
      {value > 0 ? "+" : ""}{Number(value).toFixed(digits)}%
    </span>
  );
}

/* Empty states say what is missing AND what would fill it. A bare "no data"
   leaves the reader unable to tell a broken feature from an idle one. */
export function Empty({ children }) {
  return (
    <p className="muted" style={{ fontSize: "13px", padding: "14px 0", margin: 0 }}>
      {children}
    </p>
  );
}

/* Small multiples for a theme's frequency across the five sampled windows.
   A sparkline rather than a number because the shape — when a concern appeared
   and whether it is still growing — is the whole point. */
export function Spark({ series, width = 96, height = 22 }) {
  const max = Math.max(1, ...series);
  const step = series.length > 1 ? width / (series.length - 1) : width;
  const y = (v) => height - 2 - (v / max) * (height - 6);
  const pts = series.map((v, i) => `${i * step},${y(v)}`).join(" ");
  return (
    <svg width={width} height={height} style={{ display: "block", overflow: "visible" }}>
      <polyline points={pts} fill="none" stroke={HEX.teal500} strokeWidth="1.5" />
      {series.map((v, i) => (
        <circle key={i} cx={i * step} cy={y(v)} r={i === series.length - 1 ? 2.5 : 1.5}
                fill={i === series.length - 1 ? HEX.teal500 : HEX.stone400} />
      ))}
    </svg>
  );
}

/* ---- Filter pill ---------------------------------------------------------- */

export function Pill({ on, onClick, children, count }) {
  return (
    <button type="button" onClick={onClick} className="mono is-pill" data-on={on ? "1" : "0"}>
      {children}
      {count !== undefined && (
        <span style={{ opacity: 0.65, marginLeft: 6 }}>{count}</span>
      )}
    </button>
  );
}

/* ---- Full-bleed band ------------------------------------------------------ */

/* Everything scoped to the selected window sits inside one tinted band, and
   everything below it covers the whole year. Without that split a reader has
   no way to tell which figures just moved when they dragged the scrubber. */
export function Band({ tone = "sunken", children, style }) {
  return (
    <div style={{
      margin: `0 calc(-1 * ${GUTTER})`,
      padding: `22px ${GUTTER} 26px`,
      background: tone === "sunken" ? "var(--paper-100)" : "transparent",
      borderTop: "1px solid var(--paper-200)",
      borderBottom: "1px solid var(--paper-200)",
      ...style,
    }}>{children}</div>
  );
}

export function BandLabel({ label, children, tone, style }) {
  return (
    <div className="row" style={{ gap: 12, alignItems: "baseline", marginBottom: 18, ...style }}>
      <span className="microlabel" style={{ color: tone || "var(--brass-700)" }}>{label}</span>
      {children && (
        <span className="muted" style={{ fontSize: 12.5, flex: "1 1 220px", minWidth: 0 }}>
          {children}
        </span>
      )}
    </div>
  );
}

/* ---- Lookback scrubber ---------------------------------------------------- */

/* Position runs 0…(n−1)×100 rather than 0…n−1 so the thumb slides continuously
   instead of snapping between five stops; the selected window is the nearest
   hundred. Sizes elsewhere interpolate off the raw position, but every figure
   shown is the selected window's own count — an interpolated *number* would be
   a figure no letter supports. */
export function PeriodScrubber({ periods, pos, onPos, index }) {
  if (!periods.length) return null;
  const max = Math.max(1, (periods.length - 1) * 100);
  const p = periods[index] || periods[0];

  return (
    <div style={{
      position: "sticky", top: 0, zIndex: 20,
      margin: `0 calc(-1 * ${GUTTER})`,
      padding: `14px ${GUTTER} 16px`,
      background: "var(--paper-050)",
      borderBottom: "1px solid var(--paper-300)",
    }}>
      <div className="row" style={{ gap: 12, alignItems: "baseline", marginBottom: 8 }}>
        <span className="microlabel">LOOKBACK</span>
        <span style={{ font: "400 20px/1.15 var(--serif)", color: "var(--ink-800)",
                       letterSpacing: "-.01em" }}>
          {p.label}
        </span>
        <span className="muted" style={{ fontSize: 12.5 }}>
          {p.orgs} {p.orgs === 1 ? "manager" : "managers"} · {p.letters}{" "}
          {p.letters === 1 ? "letter" : "letters"} · {p.quotes}{" "}
          {p.quotes === 1 ? "quote" : "quotes"}
        </span>
      </div>

      <input
        type="range" className="wb-scrub"
        min={0} max={max} step={1} value={pos}
        onChange={(e) => onPos(Number(e.target.value))}
        aria-label="Lookback position" />

      <div style={{ display: "grid", gridTemplateColumns: `repeat(${periods.length},minmax(0,1fr))` }}>
        {periods.map((q, i) => (
          <button type="button"
            key={q.key}
            onClick={() => onPos(i * 100)}
            className="mono"
            style={{
              background: "none", border: "none", cursor: "pointer", padding: "2px 0 0",
              fontSize: 10, letterSpacing: ".12em", textTransform: "uppercase",
              color: i === index ? "var(--teal-700)" : "var(--stone-500)",
              fontWeight: i === index ? 600 : 400,
              textAlign: i === 0 ? "left" : i === periods.length - 1 ? "right" : "center",
            }}
          >
            {q.short}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ---- Stance mix ----------------------------------------------------------- */

/* A theme's stance breakdown as proportion, never as a verdict.

   views.py is explicit about why the breakdown is not collapsed to one label:
   the stance recorded is a *letter's* overall posture, not a judgement on any
   one theme inside it, so "AI unwind — Constructive" reads as the desk being
   constructive about an unwind when it may mean the opposite. The template this
   layout follows colours each cloud term by a single stance; that is the one
   thing from it not carried over. Terms stay ink, and the mix rides underneath
   where it can be read as the split it actually is. */
export function StanceBar({ stances, width = "100%", height = 4 }) {
  const total = Object.values(stances || {}).reduce((a, b) => a + b, 0);
  if (!total) return null;
  return (
    <span style={{ display: "flex", width, height, gap: 1, marginTop: 5 }}
          title={STANCE_ORDER.filter((s) => stances[s])
            .map((s) => `${stances[s]} ${STANCE_LABEL[s].toLowerCase()}`).join(" · ")}>
      {STANCE_ORDER.filter((s) => stances[s]).map((s) => (
        <span key={s} style={{
          flex: `${stances[s]} 1 0`, background: STANCE_COLOR[s], borderRadius: 1,
        }} />
      ))}
    </span>
  );
}

/* ---- Theme cloud ---------------------------------------------------------- */

/* Size is the theme's share of the window's letters, interpolated across the
   scrubber so dragging re-weights the cloud rather than cutting between five
   fixed states. Themes nobody raised in the window stay visible but faded —
   dropping them would make a theme's disappearance indistinguishable from it
   never having existed. */
export function ThemeCloud({ themes, periods, index, frac, lo, hi, selected, onSelect }) {
  if (!themes.length) return null;

  const shareAt = (t, i) => {
    const letters = periods[i]?.letters || 0;
    return letters ? t.series[i] / letters : 0;
  };

  return (
    <div className="wb-cloud">
      {themes.map((t) => {
        const count = t.series[index] || 0;
        const share = shareAt(t, lo) + (shareAt(t, hi) - shareAt(t, lo)) * frac;
        const on = selected === t.id;
        // Presence saturates at a 25% share; above that the size alone carries it.
        const presence = Math.min(1, share / 0.25);
        return (
          <button type="button"
            key={t.id}
            onClick={() => onSelect(on ? null : t.id)}
            className="wb-term"
            data-on={on ? "1" : "0"}
            style={{
              // The share is handed to CSS rather than resolved to a px size
              // here, so the size ramp can be shortened at narrow widths (see
              // --cloud-ramp in theme.css) without this component knowing the
              // viewport. Everything stays in rem, so raising the browser text
              // size scales the terms and the cloud's reserved height together.
              "--share": share.toFixed(4),
              color: count ? "var(--ink-800)" : "var(--stone-400)",
              opacity: count ? 0.5 + 0.5 * presence : 0.42,
              fontWeight: share > 0.2 ? 500 : 400,
            }}
            title={count
              ? `${count} of ${periods[index]?.letters || 0} letters in this window`
              : `Not raised in this window · ${t.total} across the year`}
          >
            <span style={{ display: "inline-flex", flexDirection: "column" }}>
              <span>
                {t.label}
                <span className="mono" style={{ fontSize: ".42em", marginLeft: ".45em",
                                                color: "var(--stone-400)" }}>
                  {count || "—"}
                </span>
              </span>
              {count > 0 && <StanceBar stances={t.stances} height={3} />}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/* ---- Drift grid ----------------------------------------------------------- */

/* Theme × window, tinted by share of that window's letters, with the direction
   of travel spelt out in words. Comparing first and last sample is the whole
   claim — anything more (a trend line over five points) would be reading more
   into five samples than five samples hold. */
export function DriftGrid({ themes, periods }) {
  const share = (t, i) => {
    const letters = periods[i]?.letters || 0;
    return letters ? t.series[i] / letters : 0;
  };

  const direction = (t) => {
    const first = share(t, 0);
    const last = share(t, periods.length - 1);
    if (!t.series[0] && t.series[periods.length - 1]) return ["arrived", "var(--critical-600)"];
    if (t.series[0] && !t.series[periods.length - 1]) return ["gone quiet", "var(--stone-400)"];
    if (last - first > 0.06) return ["rising", "var(--critical-600)"];
    if (first - last > 0.06) return ["fading", "var(--stone-400)"];
    return ["steady", "var(--stone-500)"];
  };

  const head = {
    padding: "0 6px 9px", borderBottom: "1px solid var(--stone-300)",
    font: "500 10px/1.3 var(--mono)", letterSpacing: ".14em",
    textTransform: "uppercase", color: "var(--stone-500)", textAlign: "center",
  };

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: `minmax(150px,1.4fr) repeat(${periods.length},minmax(0,70px)) minmax(96px,.8fr)`,
      alignItems: "stretch", minWidth: 520,
    }}>
      <div style={{ ...head, textAlign: "left", paddingLeft: 0 }}>Theme</div>
      {periods.map((p) => <div key={p.key} style={head}>{p.short}</div>)}
      <div style={{ ...head, textAlign: "left", paddingLeft: 14 }}>Direction</div>

      {themes.map((t) => {
        const [word, colour] = direction(t);
        return (
          <React.Fragment key={t.id}>
            <div style={{ padding: "10px 10px 10px 0", borderBottom: "1px solid var(--paper-200)",
                          display: "flex", alignItems: "center", fontSize: 13.5,
                          color: "var(--ink-800)" }}>
              {t.label}
            </div>
            {periods.map((p, i) => {
              const s = share(t, i);
              return (
                <div key={p.key} style={{
                  padding: "10px 6px", borderBottom: "1px solid var(--paper-200)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontFamily: "var(--mono)", fontSize: 13,
                  fontVariantNumeric: "tabular-nums",
                  color: s > 0.22 ? "var(--paper-000)" : "var(--ink-700)",
                  // Tint depth is the share, so a wide window and a narrow one
                  // read alike — raw counts would make the busiest window look
                  // like the most concerned one.
                  background: t.series[i] ? `rgba(36,150,146,${(0.1 + s * 2.1).toFixed(3)})` : "transparent",
                }}>
                  {t.series[i] || ""}
                </div>
              );
            })}
            <div className="mono" style={{
              padding: "10px 0 10px 14px", borderBottom: "1px solid var(--paper-200)",
              display: "flex", alignItems: "center", fontSize: 10,
              letterSpacing: ".12em", textTransform: "uppercase", color: colour,
            }}>
              {word}
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}

/* ---- Slide-over drawer ---------------------------------------------------- */

export function Drawer({ open, onClose, eyebrow, title, children,
                         scrim = true }) {
  React.useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      {/* scrim=false renders NO backdrop at all: the page underneath keeps
          its own mouse handling (Charlotte's canvases pan and re-select
          with the drawer open, and close it on an empty-space click). */}
      {scrim && (
        <button type="button"
          onClick={onClose} aria-label="Close"
          style={{ position: "fixed", inset: 0, zIndex: 50, border: "none",
                   padding: 0, cursor: "pointer",
                   background: "rgba(15,46,66,.18)" }} />
      )}
      <aside className="wb-drawer">
        <div className="spread" style={{ alignItems: "flex-start", marginBottom: 10 }}>
          <span className="microlabel">{eyebrow}</span>
          <button type="button" onClick={onClose} className="mono"
                  style={{ background: "none", border: "none", cursor: "pointer", padding: 0,
                           fontSize: 10, letterSpacing: ".12em", textTransform: "uppercase",
                           color: "var(--stone-500)" }}>
            Close ✕
          </button>
        </div>
        <h2 style={{ font: "400 27px/1.15 var(--serif)", color: "var(--ink-800)",
                     letterSpacing: "-.015em", margin: "0 0 14px" }}>
          {title}
        </h2>
        {children}
      </aside>
    </>
  );
}

/* A quote as it appears in the drawer and the correspondence log: the words
   first, provenance around them. The extractor drops any quote it cannot find
   in the source body, so what is shown is always verbatim. */
export function QuoteBlock({ v, showOrg = true, dim = false }) {
  return (
    <article style={{ padding: "13px 0", borderTop: "1px solid var(--paper-200)" }}>
      <div className="spread" style={{ alignItems: "baseline", gap: 8 }}>
        {showOrg && (
          <b style={{ fontSize: 13.5 }}>
            {v.org}
            {v.person && <span className="muted" style={{ fontWeight: 400 }}> · {v.person}</span>}
          </b>
        )}
        <span className="mono" style={{ fontSize: 10.5, color: "var(--stone-400)" }}>{v.date}</span>
      </div>
      <blockquote style={{
        margin: "7px 0 0", paddingLeft: 12, borderLeft: "2px solid var(--teal-300)",
        font: `400 ${dim ? 13 : 14}px/1.55 var(--serif)`,
        color: dim ? "var(--stone-600)" : "var(--ink-800)",
      }}>
        “{v.quote}”
      </blockquote>
      {v.source && (
        <div className="mono" style={{ fontSize: 10, letterSpacing: ".08em",
                                       textTransform: "uppercase", color: "var(--stone-400)",
                                       marginTop: 6 }}>
          {v.source}
        </div>
      )}
    </article>
  );
}
