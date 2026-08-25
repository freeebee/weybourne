/* Node / edge inspector — the Drawer from the Inbox Signal kit. A node
   drawer shows this node's place in the web (its edges, with evidence)
   plus the existing entity-card payload (notes, emails, related funds);
   an edge drawer shows the evidence behind a connection, which is the
   whole point of a dashed edge. External nodes are quote-only: they are
   NOT in the CRM and never get an entity-card call. */
import React from "react";
import { post } from "../../api.js";
import { Button, Chip, Spinner, fmtDT } from "../../ui.jsx";
import { Drawer } from "../inboxSignal/shared.jsx";
import * as cs from "./charlotteStore.js";

/* Verbs read from the edge's a-side (edges are stored a → b). When the
   OPEN node sits on the b-side the same relation must read the other way:
   New Holland Capital EMPLOYS Bill Young — not "works at Bill Young". */
const EDGE_WORDS = {
  employed_by: "works at",
  previously_at: "previously at",
  managed_by: "managed by",
  introduced_by: "introduced by",
  represented_by: "represented by",
  known_lp: "known LP",
  discussed: "discussed",
  lp_mention: "named as LP of",
  about: "about",
  attended: "attended",
  responsible_for: "responsible analyst for",
};

const EDGE_WORDS_REV = {
  employed_by: "employs",
  previously_at: "formerly employed",
  managed_by: "manages",
  introduced_by: "introduced",
  represented_by: "represents",
  known_lp: "LP in",
  discussed: "discussed by",
  lp_mention: "commentary names",
  about: "covered in",
  attended: "attended by",
  responsible_for: "responsible analyst",
};

function EvidenceLines({ evidence }) {
  if (!evidence?.length) return null;
  return (
    <div style={{ marginTop: 4 }}>
      {evidence.slice(0, 5).map((ev, i) => (
        <div key={i} className="muted" style={{ fontSize: "12px", lineHeight: 1.5 }}>
          {ev.kind === "note"
            ? <>{ev.title || "meeting note"}{ev.date ? ` · ${ev.date}` : ""}{ev.note_type ? ` · ${ev.note_type}` : ""}</>
            : ev.kind === "quote"
              ? <em>“{ev.quote}”</em>
              : ev.label || ""}
        </div>
      ))}
    </div>
  );
}

export default function Panel() {
  React.useSyncExternalStore(cs.subscribe, cs.getVersion);
  const s = cs.S;
  // In the global view the clicked node may not be in the ego map — fall
  // back to the full-snapshot lookup (the ego record wins when both exist;
  // it carries the richer fields).
  const gById = s.global.byId || null;
  const node = s.selected
    ? (s.nodes[s.selected] || (gById && gById.get(s.selected)) || null)
    : null;
  const globalMode = s.mode === "global";
  const edge = !node ? s.selectedEdge : null;
  const [card, setCard] = React.useState(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    setCard(null);
    if (!node || node.kind === "external" || node.kind === "note") {
      return undefined;
    }
    let dead = false;
    setBusy(true);
    post("/api/live/entity-card", { name: node.label, kind: node.kind })
      .then((c) => { if (!dead) setCard(c); })
      .catch(() => {})
      .finally(() => { if (!dead) setBusy(false); });
    return () => { dead = true; };
  }, [s.selected]);   // eslint-disable-line react-hooks/exhaustive-deps

  const close = () => { cs.select(null); cs.selectEdge(null); };

  if (edge) {
    const a = s.nodes[edge.a] || {};
    const b = s.nodes[edge.b] || {};
    return (
      <Drawer open scrim={false} onClose={close} eyebrow="CONNECTION"
              title={`${a.label || "?"} — ${b.label || "?"}`}>
        <div className="row" style={{ gap: 8, marginBottom: 10 }}>
          <Chip tone={edge.inferred ? "brass" : "teal"}>
            {edge.inferred ? "INFERRED" : "NOTION RELATION"}
          </Chip>
          <span className="microlabel">{EDGE_WORDS[edge.type] || edge.type}</span>
        </div>
        {edge.inferred && (
          <p className="muted" style={{ fontSize: "12.5px" }}>
            Drawn from text, not from a Notion relation — the evidence below
            is the whole basis for this line.
          </p>
        )}
        <EvidenceLines evidence={edge.evidence} />
      </Drawer>
    );
  }

  if (!node) return null;
  // Global edges hold node references, ego edges hold ids — normalize to
  // the id shape the list below renders.
  const myEdges = globalMode && s.global.edges
    ? s.global.edges
        .filter((e) => e.a.id === s.selected || e.b.id === s.selected)
        .map((e) => ({ a: e.a.id, b: e.b.id, type: e.type,
                       inferred: e.inferred, evidence: [] }))
    : s.edges.filter((e) => e.a === s.selected || e.b === s.selected);

  return (
    <Drawer open scrim={false} onClose={close}
            eyebrow={(node.kind || "").toUpperCase()}
            title={node.label || ""}>
      <div className="row" style={{ gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        {node.kind === "external" && <Chip tone="neutral">EXTERNAL — NOT IN CRM</Chip>}
        {node.lp_candidate && <Chip tone="brass">LP CANDIDATE</Chip>}
        {node.contact_type && <Chip tone="neutral">{node.contact_type.toUpperCase()}</Chip>}
        {node.status && <Chip tone="teal">{node.status.toUpperCase()}</Chip>}
      </div>
      <div className="row" style={{ gap: 8, marginBottom: 14 }}>
        {globalMode ? (
          <Button variant="dark" onClick={() => cs.openFromGlobal(s.selected)}>
            Zoom in
          </Button>
        ) : (
          <>
            <Button variant="dark" onClick={() => cs.centerOn(s.selected)}>
              Re-center
            </Button>
            <Button variant="ghost" onClick={() => cs.expand(s.selected)}>
              Expand
            </Button>
          </>
        )}
      </div>

      <span className="microlabel">IN THIS WEB</span>
      <div style={{ margin: "6px 0 16px" }}>
        {myEdges.slice(0, 12).map((e, i) => {
          const fromA = e.a === s.selected;
          const otherId = fromA ? e.b : e.a;
          const other = s.nodes[otherId]
            || (gById && gById.get(otherId)) || {};
          const word = fromA
            ? (EDGE_WORDS[e.type] || e.type)
            : (EDGE_WORDS_REV[e.type] || EDGE_WORDS[e.type] || e.type);
          return (
            <div key={i} style={{ fontSize: "13px", padding: "3px 0" }}>
              <span className="mono" style={{ fontSize: 9.5, letterSpacing: ".08em",
                    color: e.inferred ? "var(--brass-700)" : "var(--stone-400)",
                    textTransform: "uppercase", marginRight: 8 }}>
                {word}{e.inferred ? " · INFERRED" : ""}
              </span>
              <button type="button" onClick={() => cs.select(otherId)}
                style={{ background: "none", border: 0, padding: 0, font: "inherit",
                         color: "var(--teal-700)", cursor: "pointer" }}>
                {other.label || "?"}
              </button>
              <EvidenceLines evidence={e.evidence} />
            </div>
          );
        })}
        {myEdges.length > 12 && (
          <div className="muted" style={{ fontSize: "12px" }}>
            …and {myEdges.length - 12} more connections in view.
          </div>
        )}
      </div>

      {node.kind !== "external" && node.kind !== "note" && (
        <>
          <span className="microlabel">FROM THE RECORD</span>
          {busy && <div style={{ padding: "10px 0" }}><Spinner size={16} /></div>}
          {card && (
            <div style={{ marginTop: 6 }}>
              {(card.related_funds || []).length > 0 && (
                <div style={{ fontSize: "12.5px", marginBottom: 8 }}>
                  <b>Related funds:</b>{" "}
                  {card.related_funds.slice(0, 5).map((f) => f.name || f).join(", ")}
                </div>
              )}
              {(card.notes || []).slice(0, 4).map((n, i) => (
                <div key={i} className="muted" style={{ fontSize: "12px", padding: "2px 0" }}>
                  {n.title || n.name}{n.date ? ` · ${fmtDT(n.date)}` : ""}
                </div>
              ))}
              {(card.notes || []).length === 0 && !busy && (
                <div className="muted" style={{ fontSize: "12px" }}>
                  No linked meeting notes.
                </div>
              )}
            </div>
          )}
        </>
      )}
    </Drawer>
  );
}
