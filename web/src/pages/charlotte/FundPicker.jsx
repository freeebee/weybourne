/* Type-to-search over the web's own snapshot — /api/charlotte/search
   returns node IDS (which /api/notion/names cannot), each with one line of
   context (a fund's manager, a contact's employer) so same-named records
   are tellable apart. Modeled on ui.jsx's SearchSelect, simplified to
   pick-only. */
import React from "react";
import { get } from "../../api.js";
import { Spinner } from "../../ui.jsx";

export default function FundPicker({ onPick, placeholder = "Search a fund, company, or contact…" }) {
  const [q, setQ] = React.useState("");
  const [rows, setRows] = React.useState([]);
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const ref = React.useRef(null);
  const timer = React.useRef(0);
  const seq = React.useRef(0);

  React.useEffect(() => {
    const close = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const search = (text) => {
    setQ(text);
    setOpen(true);
    clearTimeout(timer.current);
    if (!text.trim()) { setRows([]); return; }
    timer.current = setTimeout(async () => {
      const mine = ++seq.current;
      setBusy(true);
      try {
        const body = await get(
          `/api/charlotte/search?q=${encodeURIComponent(text)}`);
        if (mine === seq.current) setRows(body.results || []);
      } catch {
        if (mine === seq.current) setRows([]);
      } finally {
        if (mine === seq.current) setBusy(false);
      }
    }, 180);
  };

  const pick = (row) => {
    setOpen(false);
    setQ("");
    setRows([]);
    onPick(row);
  };

  return (
    <div ref={ref} style={{ position: "relative", minWidth: 260, flex: "0 1 340px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input value={q} placeholder={placeholder}
          onChange={(e) => search(e.target.value)}
          onFocus={() => q && setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && rows.length) { e.preventDefault(); pick(rows[0]); }
            if (e.key === "Escape") setOpen(false);
          }}
          style={{ width: "100%" }} />
        {busy && <Spinner size={14} />}
      </div>
      {open && q.trim() && (
        <div style={{ position: "absolute", top: "100%", left: 0, right: 0,
                      zIndex: 40, marginTop: 4, maxHeight: 280, overflowY: "auto",
                      background: "var(--paper-000)",
                      border: "1px solid var(--paper-200)",
                      borderRadius: "var(--radius)",
                      boxShadow: "0 10px 28px rgba(15,46,66,.14)", padding: 6 }}>
          {rows.length === 0 && !busy && (
            <div className="muted" style={{ fontSize: "12.5px", padding: "6px 9px" }}>
              Nothing in the web matches — it only knows what the last build saw.
            </div>
          )}
          {rows.map((r) => (
            <button key={r.id} type="button" onClick={() => pick(r)}
              style={{ display: "block", width: "100%", textAlign: "left",
                       background: "none", border: 0, cursor: "pointer",
                       padding: "6px 9px", borderRadius: 4, fontSize: "13px" }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--paper-100)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
              <span className="mono" style={{ fontSize: 9.5, letterSpacing: ".1em",
                    textTransform: "uppercase", color: "var(--stone-400)",
                    marginRight: 8 }}>
                {r.kind}
              </span>
              {r.label}
              {r.sub && (
                <span className="muted" style={{ fontSize: "12px", marginLeft: 8 }}>
                  {r.sub}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
