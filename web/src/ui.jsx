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

/* Searchable dropdown in the style of Notion's link-or-create picker: type to
   filter the known options; if nothing matches, a Create row uses the typed
   text as a new value. `multi` keeps a comma-separated list with removable
   chips; single-select replaces the value. */
export function SearchSelect({ value = "", onChange, options = [], multi = false,
                               placeholder, loading = false }) {
  const [q, setQ] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);

  React.useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const chosen = multi ? value.split(",").map((s) => s.trim()).filter(Boolean) : [];
  const pick = (name) => {
    if (multi) {
      if (!chosen.includes(name)) onChange([...chosen, name].join(", "));
      setQ("");
    } else {
      onChange(name); setQ(""); setOpen(false);
    }
  };
  const remove = (name) => onChange(chosen.filter((c) => c !== name).join(", "));

  // Relevance-ranked matching: exact, then prefix, then any-word prefix, then
  // all typed tokens appearing anywhere ("sim ric" finds Simon Richards).
  const norm = (s) => s.toLowerCase().replace(/\s+/g, " ").trim();
  const ql = norm(q);
  const rank = (o) => {
    const on = norm(o);
    if (on === ql) return 0;
    if (on.startsWith(ql)) return 1;
    if (on.split(" ").some((w) => w.startsWith(ql))) return 2;
    const tokens = ql.split(" ");
    if (tokens.every((t) => on.includes(t))) return 3;
    return -1;
  };
  const matches = (ql
    ? options.map((o) => [rank(o), o]).filter(([r]) => r >= 0)
        .sort((a, b) => a[0] - b[0] || a[1].localeCompare(b[1])).map(([, o]) => o)
    : options)
    .filter((o) => !chosen.includes(o))
    .slice(0, 50);
  const exact = options.some((o) => norm(o) === ql);
  const rowStyle = { padding: "6px 9px", fontSize: "13px", cursor: "pointer", borderRadius: 4 };
  const hover = (e, on) => { e.currentTarget.style.background = on ? "var(--paper-100)" : "transparent"; };

  return (
    <div ref={ref} style={{ position: "relative", flex: 1, minWidth: 0 }}>
      <div onClick={() => setOpen(true)}
        style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center",
                 background: "var(--paper-000)", border: "1px solid var(--paper-200)",
                 borderRadius: 4, padding: "4px 8px", cursor: "text" }}>
        {multi && chosen.map((c) => (
          <span key={c} className="chip teal" style={{ display: "inline-flex", gap: 5, alignItems: "center" }}>
            {c}
            <button onClick={(e) => { e.stopPropagation(); remove(c); }}
              style={{ all: "unset", cursor: "pointer", lineHeight: 1 }} title="Remove">×</button>
          </span>
        ))}
        <input
          value={multi || open ? q : value}
          onFocus={() => setOpen(true)}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (matches.length) pick(matches[0]);
              else if (ql) pick(q.trim());
            } else if (e.key === "Escape") setOpen(false);
          }}
          placeholder={multi ? (chosen.length ? "" : placeholder || "search or create…")
            : value && open ? value : placeholder || "search or create…"}
          style={{ border: "none", outline: "none", background: "transparent", flex: 1,
                   minWidth: 90, fontSize: "12.5px", fontFamily: "inherit",
                   color: "var(--ink-700)", padding: "2px 0" }} />
      </div>
      {open && (
        <div style={{ position: "absolute", zIndex: 40, top: "calc(100% + 4px)", left: 0,
                      minWidth: "100%", background: "var(--paper-000)",
                      border: "1px solid var(--paper-200)", borderRadius: "var(--radius)",
                      boxShadow: "0 10px 28px rgba(15,46,66,.14)", maxHeight: 250,
                      overflowY: "auto", padding: 4 }}>
          <div className="microlabel" style={{ padding: "4px 9px" }}>
            {ql ? "MATCHES" : "SELECT AN OPTION"}
          </div>
          {matches.map((o) => (
            <div key={o} onClick={() => pick(o)} style={rowStyle}
              onMouseEnter={(e) => hover(e, true)} onMouseLeave={(e) => hover(e, false)}>
              {o}
            </div>
          ))}
          {ql && !exact && !loading && (
            <div onClick={() => pick(q.trim())}
              style={{ ...rowStyle, color: "var(--teal-700)" }}
              onMouseEnter={(e) => hover(e, true)} onMouseLeave={(e) => hover(e, false)}>
              Create “{q.trim()}”
            </div>
          )}
          {loading && !options.length && (
            <div className="muted" style={{ padding: "6px 9px", fontSize: "12.5px" }}>
              Loading the directory…
            </div>
          )}
          {!matches.length && !ql && !loading && (
            <div className="muted" style={{ padding: "6px 9px", fontSize: "12.5px" }}>
              Type to search{options.length ? ` ${options.length} options` : ""}…
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* Styled file picker — the native "Choose File" control hidden behind a quiet
   mono button, with the chosen filename (and a clear ×) beside it. */
export function FilePick({ file, onChange, accept, label = "Choose file" }) {
  const ref = React.useRef(null);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
      <input ref={ref} type="file" accept={accept} hidden
        onChange={(e) => onChange(e.target.files[0] || null)} />
      <button type="button" onClick={() => ref.current?.click()} className="mono"
        onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--teal-500)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--paper-200)"; }}
        style={{ background: "var(--paper-000)", border: "1px solid var(--paper-200)",
                 borderRadius: 4, padding: "8px 15px", cursor: "pointer",
                 fontSize: 11, letterSpacing: ".12em", color: "var(--ink-700)",
                 transition: "border-color .2s" }}>
        {label.toUpperCase()}
      </button>
      {file ? (
        <span style={{ fontSize: "13px", display: "inline-flex", gap: 8,
                       alignItems: "center", minWidth: 0, overflowWrap: "anywhere" }}>
          {file.name}
          <button type="button" title="Remove"
            onClick={() => { onChange(null); if (ref.current) ref.current.value = ""; }}
            style={{ background: "none", border: "none", cursor: "pointer",
                     color: "var(--stone-400)", fontSize: 15, padding: 0, lineHeight: 1 }}>
            ×
          </button>
        </span>
      ) : (
        <span className="muted" style={{ fontSize: "12.5px" }}>No file chosen</span>
      )}
    </div>
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

/* ---- local-timezone date/time formatting --------------------------------- */
/* Calendar and mail timestamps arrive as ISO strings (often UTC "Z") — always
   render them in the viewer's own timezone (SGT in Singapore, etc.). Naive
   strings without an offset parse as local time, which is the right default. */
export function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? String(iso).slice(11, 16)
    : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? String(iso).slice(0, 10)
    : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

export function fmtDT(iso) {
  const dt = fmtDate(iso), tm = fmtTime(iso);
  return dt && tm ? `${dt} ${tm}` : dt || tm;
}
