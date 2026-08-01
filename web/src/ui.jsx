/* Weybourne UI kit — redesign per design_handoff_connector_redesign. */
import React from "react";

export function Button({ variant = "primary", disabled, busy, children, style, ...rest }) {
  const [hover, setHover] = React.useState(false);
  const palettes = {
    primary: { bg: hover ? "var(--teal-700)" : "var(--teal-600)", color: "var(--paper-000)", border: "transparent" },
    dark: { bg: hover ? "var(--ink-800)" : "var(--ink-700)", color: "var(--paper-050)", border: "transparent" },
    ghost: { bg: hover ? "var(--paper-000)" : "transparent", color: "var(--ink-700)", border: hover ? "var(--stone-400)" : "var(--paper-300)" },
  };
  const p = palettes[variant] || palettes.primary;
  return (
    <button
      disabled={disabled || busy}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex", alignItems: "center", gap: ".5rem",
        padding: "10px 17px", fontSize: "13.5px", fontWeight: 500,
        color: disabled || busy ? "var(--stone-400)" : p.color,
        background: disabled || busy ? "var(--paper-100)" : p.bg,
        border: `1px solid ${disabled || busy ? "var(--paper-300)" : p.border}`,
        borderRadius: "var(--radius)", cursor: disabled || busy ? "default" : "pointer",
        transition: "background .15s ease, border-color .15s ease", whiteSpace: "nowrap",
        ...style,
      }}
      {...rest}
    >
      {busy && <Spinner size={13} />}
      {children}
    </button>
  );
}

export function Spinner({ size = 16 }) {
  return (
    <span style={{
      width: size, height: size, flex: "none", borderRadius: "50%",
      border: "2px solid var(--paper-300)", borderTopColor: "var(--teal-600)",
      display: "inline-block", animation: "wbspin .8s linear infinite",
    }}>
      <style>{`@keyframes wbspin{to{transform:rotate(360deg)}}`}</style>
    </span>
  );
}

/* accent: "teal" = primary card, "brass" = finished artefact, none = quiet */
export function Card({ accent, children, style, ...rest }) {
  return (
    <div style={{
      background: "var(--paper-000)", border: "1px solid var(--paper-200)",
      borderTop: accent === "teal" ? "2px solid var(--teal-500)"
        : accent === "brass" ? "2px solid var(--brass-500)"
        : "1px solid var(--paper-200)",
      borderRadius: "var(--radius)", padding: "17px 18px", ...style,
    }} {...rest}>{children}</div>
  );
}

export function Chip({ tone = "neutral", dot, children }) {
  return (
    <span className={`chip ${tone}`}>
      {dot && <span className="dot" style={{ background: "currentColor" }} />}
      {children}
    </span>
  );
}

export function KpiBand({ items }) {
  return (
    <div className="kpis">
      {items.map(([label, value, warn, caption]) => (
        <div className="kpi" key={label}>
          <span className="microlabel">{label}</span>
          <div className={"kval" + (warn ? " warn" : "")}>{value}</div>
          {caption && <div className="muted" style={{ fontSize: "12px" }}>{caption}</div>}
        </div>
      ))}
    </div>
  );
}

export function Field({ label, hint, children, style }) {
  return (
    <label style={{ display: "block", margin: "0 0 1rem", ...style }}>
      <span className="microlabel" style={{ display: "block", marginBottom: 5 }}>{label}</span>
      {children}
      {hint && <div className="muted" style={{ marginTop: 4, fontSize: "12.5px", fontStyle: "italic" }}>{hint}</div>}
    </label>
  );
}

export const inputStyle = { width: "100%" };

export function PageHeader({ eyebrow, eyebrowTone, title, xl, children, actions }) {
  return (
    <div className="pagehead fade-in">
      <div className="lead">
        <span className={"eyebrow" + (eyebrowTone ? ` ${eyebrowTone}` : "")}>
          {eyebrowTone === "rec" && <span className="dot" style={{ background: "var(--positive-600)", marginRight: 7 }} />}
          {eyebrow}
        </span>
        <h1 className={xl ? "xl" : ""}>{title}</h1>
        {children && <p className="desc">{children}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}

export function SectionHead({ label, right, style }) {
  return (
    <div className="spread" style={{ paddingBottom: 12, ...style }}>
      <span className="microlabel">{label}</span>
      {right && <span className="microlabel" style={{ letterSpacing: ".1em" }}>{right}</span>}
    </div>
  );
}

export function ErrorNote({ error }) {
  if (!error) return null;
  return (
    <div style={{ borderTop: "1px solid var(--paper-200)", borderBottom: "1px solid var(--paper-200)",
                  padding: "12px 0", margin: "14px 0" }}>
      <span className="microlabel" style={{ color: "var(--critical-600)" }}>SOMETHING WENT WRONG</span>
      <div style={{ fontSize: "13.5px", marginTop: 4 }}>{String(error)}</div>
    </div>
  );
}

export function Banner({ tone = "info", children }) {
  const colors = { info: "var(--teal-700)", success: "var(--positive-600)",
                   warning: "var(--caution-600)", error: "var(--critical-600)" };
  return (
    <div style={{ borderTop: "1px solid var(--paper-200)", borderBottom: "1px solid var(--paper-200)",
                  padding: "10px 0", margin: "10px 0", fontSize: "13.5px" }}>
      <span className="dot" style={{ background: colors[tone] || colors.info, marginRight: 8 }} />
      {children}
    </div>
  );
}

/* The exported mascot SVGs are static frames, so the motion lives here. */
const MASCOT_MOTION = {
  working: "wb-wiggle 1.1s ease-in-out infinite",
  crunching: "wb-wiggle .9s ease-in-out infinite",
  notes: "wb-bob 1.6s ease-in-out infinite",
  reading: "wb-bob 2.6s ease-in-out infinite",
  filing: "wb-bob 2.2s ease-in-out infinite",
  thinking: "wb-pulse 2.4s ease-in-out infinite",
  confused: "wb-pulse 3.2s ease-in-out infinite",
  waving: "wb-wave 2.6s ease-in-out infinite",
  celebrating: "wb-wave 1.4s ease-in-out infinite",
  call: "wb-bob 2.4s ease-in-out infinite",
  presenting: "wb-bob 3s ease-in-out infinite",
  coffee: "wb-float 3.4s ease-in-out infinite",
  sleeping: "wb-float 4.2s ease-in-out infinite",
  avatar: "none",
};

const mascotCache = {};

export function Mascot({ state, width = 110, text, style }) {
  const [svg, setSvg] = React.useState(mascotCache[state] || "");

  React.useEffect(() => {
    if (mascotCache[state]) { setSvg(mascotCache[state]); return; }
    fetch(`/mascot/mascot-${state}.svg`)
      .then((r) => (r.ok ? r.text() : ""))
      .then((t) => {
        if (!t) return;
        t = t.replace(/\bid="/g, `id="${state}-`)
             .replaceAll('href="#', `href="#${state}-`)
             .replaceAll("url(#", `url(#${state}-`)
             .replace("<svg ", '<svg style="width:100%;height:auto;display:block" ');
        mascotCache[state] = t;
        setSvg(t);
      })
      .catch(() => {});
  }, [state]);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "14px", ...style }}>
      <div aria-label={`mascot ${state}`} style={{
        width, flex: "none", transformOrigin: "60% 90%",
        animation: MASCOT_MOTION[state] || "wb-bob 2.4s ease-in-out infinite",
      }} dangerouslySetInnerHTML={{ __html: svg }} />
      {text && <div className="muted" style={{ fontSize: "13.5px" }}>{text}</div>}
    </div>
  );
}
