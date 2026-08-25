/* Obsidian-style graph settings panel. FILTERS is a tree: kind pills
   (doubling as the legend), each expanding to its sub-filter dimensions
   (funds: asset class / geography / quality; contacts: contact type) —
   every dimension both GROUPs the layout and hides values via chips.
   GROUP ORDER (shown when 2+ fund groupings are on) sets nesting.
   Then Highlight, Display, Forces. All state lives in the store so both
   canvases react live. */
import React from "react";
import { useScrollHold } from "../../ui.jsx";
import { Pill } from "../inboxSignal/shared.jsx";
import * as cs from "./charlotteStore.js";
import { FUND_LAYER_LABELS } from "./layers.js";

const QUALITY_ORDER = ["High", "Medium", "Low", "Legacy", ""];

const KIND_HEX = cs.KIND_COLORS;
const KIND_PLURAL = { fund: "FUNDS", company: "COMPANIES",
                      contact: "CONTACTS", note: "NOTES",
                      external: "EXTERNAL" };

/* Sub-filter dimensions per kind. Each doubles as a grouping layer via
   its GROUP pill; its value chips hide nodes outright. */
const KIND_SUBS = {
  fund: [["asset_class", "ASSET CLASS"], ["geography", "GEOGRAPHY"],
         ["quality", "QUALITY"]],
  contact: [["contact_type", "CONTACT TYPE"]],
};
const layerScope = (key) => (key === "contact_type" ? "contact" : "fund");
const layerOn = (s, key) => {
  const list = key === "contact_type" ? s.layers.contact : s.layers.fund;
  return !!list.find((l) => l.key === key)?.on;
};

/* Reset one section's settings to their defaults, leaving the rest. */
function ResetRow({ keys }) {
  const patch = Object.fromEntries(keys.map((k) => [k, cs.VIZ_DEFAULTS[k]]));
  return (
    <button type="button" className="mono cw-viz-reset"
      onClick={() => cs.setViz(patch)}>
      RESET TO DEFAULTS
    </button>
  );
}

function Section({ title, open, onToggle, children }) {
  return (
    <div className="cw-viz-section">
      <button type="button" className="mono cw-viz-head" onClick={onToggle}>
        <span className="cw-viz-chev">{open ? "▾" : "▸"}</span>{title}
      </button>
      {open && <div className="cw-viz-body">{children}</div>}
    </div>
  );
}

function Slider({ label, hint, min, max, step, value, onChange }) {
  return (
    <label className="cw-viz-slider">
      <span className="mono">{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))} />
      {hint && <span className="cw-viz-hint">{hint}</span>}
    </label>
  );
}

/* One layer's value chips (behind the row's ▸ arrow): on = shown,
   toggling off removes those nodes from BOTH views. */
function ValueChips({ field, values, counts, hold }) {
  const s = cs.S;
  return (
    <div className="row"
      style={{ gap: 6, flexWrap: "wrap", padding: "2px 0 6px 18px" }}>
      {values.length === 0 && (
        <span className="cw-viz-hint">Open a view to load values.</span>
      )}
      {values.map((v) => (
        <Pill key={v || "blank"}
              on={!(s.valueHidden[field] || []).includes(v)}
              onClick={() => hold(() => cs.toggleValueHidden(field, v))}
              count={counts[v]}>
          {(v || "BLANK").toUpperCase()}
        </Pill>
      ))}
    </div>
  );
}

export default function VizPanel({ onClose, kindCounts }) {
  React.useSyncExternalStore(cs.subscribe, cs.getVersion);
  const hold = useScrollHold();
  const [open, setOpen] = React.useState(
    { filters: true, layers: true, highlight: true, display: false,
      forces: true });
  const [dragIdx, setDragIdx] = React.useState(null);
  const [overIdx, setOverIdx] = React.useState(null);
  const [openKinds, setOpenKinds] = React.useState({});
  const [openDims, setOpenDims] = React.useState({});
  const toggle = (k) => setOpen((o) => ({ ...o, [k]: !o[k] }));
  const s = cs.S;
  const v = s.viz;
  // Value chips count whichever world is loaded — the global snapshot
  // when present, else the open local web (memoized: slider drags
  // re-render this panel constantly).
  const gNodes = s.global.nodes;
  const egoCount = Object.keys(s.nodes).length;
  const valueCounts = React.useMemo(() => {
    const out = { asset_class: {}, geography: {},
                  quality: {}, contact_type: {} };
    const src = gNodes || Object.values(cs.S.nodes);
    for (const n of src) {
      if (n.kind === "fund") {
        for (const f of ["asset_class", "geography", "quality"]) {
          const val = n[f] || "";
          out[f][val] = (out[f][val] || 0) + 1;
        }
      } else if (n.kind === "contact") {
        const val = n.contact_type || "";
        out.contact_type[val] = (out.contact_type[val] || 0) + 1;
      }
    }
    return out;
  }, [gNodes, egoCount]);
  const valuesFor = (key) => {
    const counts = valueCounts[key] || {};
    if (key === "quality") return QUALITY_ORDER.filter((q) => counts[q]);
    return Object.keys(counts).sort(
      (a, b) => counts[b] - counts[a] || (a < b ? -1 : 1));
  };

  return (
    <div className="cw-viz">
      <div className="cw-viz-top">
        <span className="mono">GRAPH SETTINGS</span>
        <button type="button" title="Reset to defaults"
          onClick={cs.resetViz}>↺</button>
        <button type="button" title="Close" onClick={onClose}>×</button>
      </div>

      <Section title="FILTERS" open={open.filters}
        onToggle={() => toggle("filters")}>
        <span className="cw-viz-hint">
          Toggle a type off to remove those nodes. ▸ opens its
          sub-filters: GROUP arranges the graph by that field; the value
          chips hide single values. Both views react.
        </span>
        {Object.keys(KIND_PLURAL)
          .filter((k) => kindCounts?.[k])
          .map((k) => (
          <React.Fragment key={k}>
            <div className="cw-layer-row" style={{ cursor: "default" }}>
              <Pill on={!s.hidden.includes(k)}
                    onClick={() => hold(() => cs.toggleHidden(k))}
                    count={kindCounts?.[k] || undefined}>
                <span style={{ display: "inline-block", width: 8, height: 8,
                               borderRadius: "50%", background: KIND_HEX[k],
                               marginRight: 6 }} />
                {KIND_PLURAL[k]}
              </Pill>
              <span style={{ flex: 1 }} />
              {KIND_SUBS[k] && (
                <button type="button" className="mono cw-layer-arrow"
                  title="Sub-filters"
                  onClick={() => hold(() => setOpenKinds((o) =>
                    ({ ...o, [k]: !o[k] })))}>
                  {openKinds[k] ? "▾" : "▸"}
                </button>
              )}
            </div>
            {openKinds[k] && KIND_SUBS[k].map(([dk, dLabel]) => (
              <React.Fragment key={dk}>
                <div className="cw-layer-row cw-dim-row">
                  <button type="button" className="mono cw-layer-arrow"
                    title="Values"
                    onClick={() => hold(() => setOpenDims((o) =>
                      ({ ...o, [dk]: !o[dk] })))}>
                    {openDims[dk] ? "▾" : "▸"}
                  </button>
                  <span className="mono cw-layer-name">{dLabel}</span>
                  <Pill on={layerOn(s, dk)}
                        onClick={() => hold(() =>
                          cs.toggleLayer(layerScope(dk), dk))}>
                    GROUP
                  </Pill>
                </div>
                {openDims[dk] && (
                  <ValueChips field={dk} values={valuesFor(dk)}
                              counts={valueCounts[dk]} hold={hold} />
                )}
              </React.Fragment>
            ))}
          </React.Fragment>
        ))}
        {s.hidden.length > 0 && (
          <button type="button" className="mono"
            onClick={() => hold(() => cs.clearHidden())}
            style={{ background: "none", border: 0, cursor: "pointer",
                     fontSize: 10, letterSpacing: ".1em",
                     color: "var(--teal-700)" }}>
            SHOW ALL
          </button>
        )}
      </Section>

      {s.layers.fund.filter((l) => l.on).length >= 2 && (
        <Section title="GROUP ORDER" open={open.layers}
          onToggle={() => toggle("layers")}>
          <span className="cw-viz-hint">
            Drag to reorder — the top grouping splits the graph first.
          </span>
          {s.layers.fund.filter((l) => l.on).map((row, i, act) => (
            <div key={row.key}
              className={"cw-layer-row" + (overIdx === i ? " over" : "")}
              draggable
              onDragStart={() => setDragIdx(i)}
              onDragOver={(e) => { e.preventDefault(); setOverIdx(i); }}
              onDragLeave={() => setOverIdx((x) => (x === i ? null : x))}
              onDrop={(e) => {
                e.preventDefault();
                if (dragIdx !== null && dragIdx !== i) {
                  // Display rows are the ACTIVE subset — map back to the
                  // underlying ordered list before moving.
                  const from = s.layers.fund.findIndex(
                    (l) => l.key === act[dragIdx].key);
                  const to = s.layers.fund.findIndex(
                    (l) => l.key === act[i].key);
                  cs.moveLayer("fund", from, to);
                }
                setDragIdx(null);
                setOverIdx(null);
              }}
              onDragEnd={() => { setDragIdx(null); setOverIdx(null); }}>
              <span className="cw-layer-grip">≡</span>
              <span className="mono cw-layer-name">
                {FUND_LAYER_LABELS[row.key] || row.key.toUpperCase()}
              </span>
            </div>
          ))}
        </Section>
      )}

      <Section title="HIGHLIGHT" open={open.highlight}
        onToggle={() => toggle("highlight")}>
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          {Object.keys(KIND_PLURAL)
            .filter((k) => kindCounts?.[k] && !s.hidden.includes(k))
            .map((k) => (
            <Pill key={k} on={s.kinds.includes(k)}
                  onClick={() => hold(() => cs.toggleKind(k))}>
              <span style={{ display: "inline-block", width: 8, height: 8,
                             borderRadius: "50%", background: KIND_HEX[k],
                             marginRight: 6 }} />
              {KIND_PLURAL[k]}
            </Pill>
          ))}
          {s.kinds.length > 0 && (
            <button type="button" className="mono"
              onClick={() => hold(() => cs.clearKinds())}
              style={{ background: "none", border: 0, cursor: "pointer",
                       fontSize: 10, letterSpacing: ".1em",
                       color: "var(--teal-700)" }}>
              CLEAR
            </button>
          )}
        </div>
        <span className="cw-viz-hint">
          Chosen types stay full strength and get named from further out;
          everything else fades back.
        </span>
      </Section>

      <Section title="DISPLAY" open={open.display}
        onToggle={() => toggle("display")}>
        <div className="row" style={{ gap: 6 }}>
          <Pill on={v.arrows}
                onClick={() => hold(() => cs.setViz({ arrows: !v.arrows }))}>
            ARROWS
          </Pill>
        </div>
        <Slider label="TEXT SIZE" min={0.6} max={2} step={0.05}
          value={v.textScale}
          onChange={(x) => cs.setViz({ textScale: x })} />
        <Slider label="NODE SIZE" min={0.5} max={2.5} step={0.05}
          value={v.nodeScale}
          onChange={(x) => cs.setViz({ nodeScale: x })} />
        <Slider label="FADE LEVEL" min={0} max={0.95} step={0.05}
          value={v.fadeAmount}
          onChange={(x) => cs.setViz({ fadeAmount: x })} />
        <ResetRow keys={["arrows", "textScale", "nodeScale", "fadeAmount"]} />
      </Section>

      <Section title="FORCES" open={open.forces}
        onToggle={() => toggle("forces")}>
        <Slider label="CENTER FORCE" min={0} max={2.5} step={0.05}
          hint="Pulls the whole graph toward the middle — higher makes a
                tighter, rounder cloud."
          value={v.center} onChange={(x) => cs.setViz({ center: x })} />
        <Slider label="REPEL FORCE" min={0} max={2.5} step={0.05}
          hint="How hard nodes push each other apart — turn up to spread
                out crowded clusters."
          value={v.repel} onChange={(x) => cs.setViz({ repel: x })} />
        <Slider label="LINK FORCE" min={0} max={2} step={0.05}
          hint="How tightly connected nodes pull together — rubber bands,
                loose to taut."
          value={v.linkForce} onChange={(x) => cs.setViz({ linkForce: x })} />
        <Slider label="LINK DISTANCE" min={0.3} max={2.5} step={0.05}
          hint="Resting length of the lines between connected nodes."
          value={v.linkDist} onChange={(x) => cs.setViz({ linkDist: x })} />
        <Slider label="GROUP PULL" min={0} max={2.5} step={0.05}
          hint="Global view layers: how hard grouped nodes are pulled
                into their sector — 0 switches the grouping force off."
          value={v.groupPull} onChange={(x) => cs.setViz({ groupPull: x })} />
        <Slider label="GROUP TIES" min={0} max={2.5} step={0.05}
          hint="How much links still tug grouped nodes — higher lets
                connections drag funds out of their sectors."
          value={v.groupTies} onChange={(x) => cs.setViz({ groupTies: x })} />
        <ResetRow keys={["center", "repel", "linkForce", "linkDist",
                         "groupPull", "groupTies"]} />
      </Section>
    </div>
  );
}
