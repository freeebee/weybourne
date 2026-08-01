/* Weybourne UI kit — component idiom from the Weybourne Design System
   (quiet cards, hairline rules, mono badges, restrained states). */
import React from "react";

export function Button({ variant = "primary", disabled, busy, children, style, ...rest }) {
  const [hover, setHover] = React.useState(false);
  const palettes = {
    primary: { bg: hover ? "var(--teal-700)" : "var(--teal-600)", color: "#fff", border: "transparent" },
    secondary: { bg: hover ? "var(--paper-050)" : "var(--paper-000)", color: "var(--ink-800)", border: hover ? "var(--stone-400)" : "var(--paper-300)" },
    ghost: { bg: hover ? "var(--paper-100)" : "transparent", color: "var(--ink-700)", border: "transparent" },
  };
  const p = palettes[variant] || palettes.primary;
  return (
    <button
      disabled={disabled || busy}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex", alignItems: "center", gap: ".5rem",
        height: "2.25rem", padding: "0 1rem", fontSize: ".92rem", fontWeight: 600,
        color: disabled || busy ? "var(--stone-400)" : p.color,
        background: disabled || busy ? "var(--paper-100)" : p.bg,
        border: `1px solid ${disabled || busy ? "var(--paper-300)" : p.border}`,
        borderRadius: "var(--radius-md)", cursor: disabled || busy ? "default" : "pointer",
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

export function Card({ children, style, ...rest }) {
  return (
    <div style={{
      background: "var(--paper-000)", border: "1px solid var(--paper-200)",
      borderRadius: "var(--radius-lg)", padding: "1.1rem 1.3rem",
      boxShadow: "var(--shadow-sm)", ...style,
    }} {...rest}>{children}</div>
  );
}

export function Pill({ tone = "neutral", children }) {
  const tones = {
    live: { bg: "var(--positive-100)", fg: "var(--positive-600)", bd: "var(--positive-600)" },
    demo: { bg: "var(--caution-100)", fg: "var(--caution-600)", bd: "var(--caution-500)" },
    flag: { bg: "var(--brass-100)", fg: "var(--brass-700)", bd: "var(--brass-500)" },
    neutral: { bg: "var(--paper-100)", fg: "var(--stone-600)", bd: "var(--paper-300)" },
    critical: { bg: "var(--critical-100)", fg: "var(--critical-600)", bd: "var(--critical-500)" },
  };
  const t = tones[tone] || tones.neutral;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", height: "1.35rem", padding: "0 .5rem",
      font: "500 .62rem/1 var(--mono)", letterSpacing: ".08em", textTransform: "uppercase",
      color: t.fg, background: t.bg, border: `1px solid ${t.bd}`,
      borderRadius: "var(--radius-sm)", marginLeft: ".4rem", whiteSpace: "nowrap",
    }}>{children}</span>
  );
}

export function Banner({ tone = "info", children }) {
  const tones = {
    info: { bg: "var(--teal-100)", bd: "var(--teal-600)" },
    success: { bg: "var(--positive-100)", bd: "var(--positive-600)" },
    warning: { bg: "var(--caution-100)", bd: "var(--caution-500)" },
    error: { bg: "var(--critical-100)", bd: "var(--critical-500)" },
  };
  const t = tones[tone] || tones.info;
  return (
    <div style={{
      background: t.bg, borderLeft: `3px solid ${t.bd}`,
      border: `1px solid var(--paper-200)`, borderLeftWidth: 3, borderLeftColor: t.bd,
      borderRadius: "var(--radius-sm)", padding: ".7rem 1rem", fontSize: ".92rem",
      margin: ".6rem 0",
    }}>{children}</div>
  );
}

export function Stat({ label, value, caption }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ".35rem" }}>
      <span className="eyebrow" style={{ margin: 0 }}>{label}</span>
      <span className="mono" style={{ fontSize: "1.8rem", color: "var(--ink-800)", lineHeight: 1 }}>
        {value}
      </span>
      {caption && <span className="muted small">{caption}</span>}
    </div>
  );
}

export function Tabs({ tabs, active, onChange }) {
  return (
    <div style={{ display: "flex", gap: "1.4rem", borderBottom: "1px solid var(--paper-200)", margin: "1rem 0" }}>
      {tabs.map((t) => (
        <button key={t} onClick={() => onChange(t)} style={{
          background: "none", border: "none", cursor: "pointer", padding: ".5rem 0",
          fontSize: ".95rem", fontWeight: 500,
          color: t === active ? "var(--teal-700)" : "var(--stone-500)",
          borderBottom: t === active ? "2px solid var(--teal-600)" : "2px solid transparent",
          marginBottom: -1,
        }}>{t}</button>
      ))}
    </div>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label style={{ display: "block", margin: "0 0 1rem" }}>
      <span className="eyebrow">{label}</span>
      {children}
      {hint && <div className="muted small" style={{ marginTop: 4, fontStyle: "italic" }}>{hint}</div>}
    </label>
  );
}

export const inputStyle = {
  width: "100%", padding: ".55rem .7rem", fontSize: ".95rem", fontFamily: "var(--sans)",
  color: "var(--ink-700)", background: "var(--paper-000)",
  border: "1px solid var(--paper-300)", borderRadius: "var(--radius-sm)", outline: "none",
};

/* The exported mascot SVGs are static frames, so the motion lives here:
   each state gets a CSS animation applied to the inlined figure. */
const MASCOT_MOTION = {
  working: "wb-wiggle 1.1s ease-in-out infinite",
  crunching: "wb-wiggle .7s ease-in-out infinite",
  notes: "wb-bob 1.6s ease-in-out infinite",
  reading: "wb-bob 2.2s ease-in-out infinite",
  filing: "wb-bob 1.4s ease-in-out infinite",
  thinking: "wb-pulse 2.4s ease-in-out infinite",
  confused: "wb-pulse 3s ease-in-out infinite",
  waving: "wb-wave 1.6s ease-in-out infinite",
  celebrating: "wb-wave 1s ease-in-out infinite",
  call: "wb-bob 2s ease-in-out infinite",
  presenting: "wb-bob 2s ease-in-out infinite",
  coffee: "wb-float 3.4s ease-in-out infinite",
  sleeping: "wb-float 4s ease-in-out infinite",
  avatar: "none",
};

const mascotCache = {};

export function Mascot({ state, width = 110, text }) {
  const [svg, setSvg] = React.useState(mascotCache[state] || "");

  React.useEffect(() => {
    if (mascotCache[state]) { setSvg(mascotCache[state]); return; }
    fetch(`/mascot/mascot-${state}.svg`)
      .then((r) => (r.ok ? r.text() : ""))
      .then((t) => {
        if (!t) return;
        // Namespace ids so two mascots on one page can't collide, and make the
        // svg fill its container.
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
    <div style={{ display: "flex", alignItems: "center", gap: "1.1rem", padding: ".4rem 0" }}>
      <div aria-label={`mascot ${state}`} style={{
        width, flex: "none", transformOrigin: "50% 92%",
        animation: MASCOT_MOTION[state] || "wb-bob 2.4s ease-in-out infinite",
      }} dangerouslySetInnerHTML={{ __html: svg }} />
      {text && <div className="muted" style={{ fontSize: ".92rem" }}>{text}</div>}
    </div>
  );
}

export function PageHeader({ eyebrow, title, children }) {
  return (
    <div className="hero fade-in">
      <span className="eyebrow">{eyebrow}</span>
      <h1>{title}</h1>
      {children && <p>{children}</p>}
    </div>
  );
}

export function ErrorNote({ error }) {
  if (!error) return null;
  return <Banner tone="error"><b>Something went wrong</b> — {String(error)}</Banner>;
}
