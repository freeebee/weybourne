/* LP reference candidates for the centered fund, grouped by evidence tier.
   T0-T3 are recorded facts; T4 is inference and says so. Tier filter pills
   go through useScrollHold — filtering shrinks the list and must not throw
   the page to the top. */
import React from "react";
import { Card, Chip, useScrollHold } from "../../ui.jsx";
import { Pill } from "../inboxSignal/shared.jsx";
import * as cs from "./charlotteStore.js";

const TIER_TONE = { T0: "teal", T1: "neutral", T2: "neutral",
                    T3: "neutral", T4: "brass" };

export default function LpPanel() {
  React.useSyncExternalStore(cs.subscribe, cs.getVersion);
  const hold = useScrollHold();
  const [tier, setTier] = React.useState("");
  const s = cs.S;
  const center = s.center ? s.nodes[s.center] : null;
  if (!center || center.kind !== "fund") return null;

  const tiers = [...new Set(s.lp.map((r) => r.tier))].sort();
  const rows = tier ? s.lp.filter((r) => r.tier === tier) : s.lp;

  return (
    <Card style={{ minWidth: 0 }}>
      <div className="spread" style={{ marginBottom: 8 }}>
        <span className="microlabel">LP REFERENCE CANDIDATES</span>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".1em",
              color: "var(--stone-500)" }}>
          {s.lp.length || "NONE"}
        </span>
      </div>
      {s.lp.length === 0 && (
        <p className="muted" style={{ fontSize: "12.5px", margin: 0 }}>
          No LP signals for this fund yet — nothing in Known LPs, no LP-typed
          contact in its meetings, and no LP Meeting notes tagged to it.
        </p>
      )}
      {tiers.length > 1 && (
        <div className="row" style={{ gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
          <Pill on={tier === ""} onClick={() => hold(() => setTier(""))} count={s.lp.length}>
            ALL
          </Pill>
          {tiers.map((t) => (
            <Pill key={t} on={tier === t} onClick={() => hold(() => setTier(t))}
                  count={s.lp.filter((r) => r.tier === t).length}>
              {t}
            </Pill>
          ))}
        </div>
      )}
      {rows.map((r) => (
        <div key={r.id} className="rrow" style={{ padding: "8px 0" }}>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <button type="button" onClick={() => cs.select(r.id)}
              style={{ background: "none", border: 0, padding: 0, font: "inherit",
                       fontSize: "13.5px", fontWeight: 600,
                       color: "var(--ink-800)", cursor: "pointer" }}>
              {r.name}
            </button>
            <Chip tone={TIER_TONE[r.tier] || "neutral"}>
              {r.tier}{r.inferred ? " · INFERRED" : ""}
            </Chip>
          </div>
          <div className="muted" style={{ fontSize: "12px", marginTop: 2 }}>
            {r.tier_label}
            {r.evidence?.[0]?.kind === "note" && r.evidence[0].title
              ? ` — ${r.evidence[0].title}`
              : r.evidence?.[0]?.kind === "quote" && r.evidence[0].quote
                ? ` — “${r.evidence[0].quote.slice(0, 90)}”`
                : ""}
          </div>
        </div>
      ))}
    </Card>
  );
}
