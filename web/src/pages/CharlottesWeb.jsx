/* Charlotte's Web — a fund-centered reference graph over the Notion CRM.
   Search a fund, see its web (manager, contacts, LP candidates), expand by
   clicking. The graph is a point-in-time snapshot built by a 5-10 minute
   background crawl; the "as of" line and rebuild button keep that honest.

   Once the web is ready the page is deliberately chrome-less: one compact
   control bar (search on the left, colored kind pills doubling as the
   legend) and the canvas filling the rest of the viewport — no scrolling
   to reach the graph. */
import React from "react";
import {
  Banner, Button, Card, ErrorNote, Mascot, PageHeader, Spinner, useScrollHold,
} from "../ui.jsx";
import { Pill } from "./inboxSignal/shared.jsx";
import * as cs from "./charlotte/charlotteStore.js";
import FundPicker from "./charlotte/FundPicker.jsx";
import GlobalWeb from "./charlotte/GlobalWeb.jsx";
import LpPanel from "./charlotte/LpPanel.jsx";
import Panel from "./charlotte/Panel.jsx";
import VizPanel from "./charlotte/VizPanel.jsx";
import Web from "./charlotte/Web.jsx";

function daysSince(iso) {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? 0 : Math.floor((Date.now() - t) / 86400000);
}

export default function CharlottesWeb() {
  React.useSyncExternalStore(cs.subscribe, cs.getVersion);
  React.useEffect(() => { cs.ensureStatus(); }, []);
  const hold = useScrollHold();
  const [showViz, setShowViz] = React.useState(true);
  const s = cs.S;
  const st = s.status;
  const building = s.job?.status === "running";
  // The filter pills count whichever world is on screen.
  const countSrc = s.mode === "global" && s.global.nodes
    ? s.global.nodes : Object.values(s.nodes);
  const kindCounts = {};
  for (const n of countSrc) {
    kindCounts[n.kind] = (kindCounts[n.kind] || 0) + 1;
  }

  return (
    <div className="fade-in">
      <PageHeader eyebrow="ANALYSIS · CHARLOTTE'S WEB" title="Charlotte's web">
        {!st?.ready && ("Search a fund and see everything the CRM connects "
          + "to it — the manager, the people, the meetings, and the LPs you "
          + "could call for a reference. Solid lines are Notion relations; "
          + "dashed lines are inferred and carry their evidence.")}
      </PageHeader>

      <ErrorNote error={s.error} />

      {!st && (
        <Card><div className="row"><Spinner size={16} />
          <span className="muted small">Checking for a built web…</span>
        </div></Card>
      )}

      {st && !st.ready && (
        <Card accent="teal">
          <Mascot state="coffee" width={56}
            text="No web yet — the first build crawls the whole workspace." />
          <p className="muted" style={{ fontSize: "13px", maxWidth: "68ch" }}>
            Building reads every contact, company, fund, and meeting note
            (~35,000 pages) at Notion&apos;s rate limit — expect 5-10 minutes.
            It runs in the background and lands as a snapshot, so it is a
            one-time wait; afterwards the web opens instantly and you rebuild
            only when you want a fresher picture.
          </p>
          <div className="row" style={{ marginTop: 8 }}>
            <Button busy={building} onClick={cs.startCrawl}>Build the web</Button>
            {building && s.job?.current && (
              <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".08em",
                    color: "var(--teal-700)" }}>
                {s.job.current}
              </span>
            )}
            {building && !s.job?.current && s.job?.stages?.length > 0 && (
              <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".08em",
                    color: "var(--teal-700)" }}>
                {s.job.stages[s.job.stages.length - 1].label.toUpperCase()}
              </span>
            )}
          </div>
        </Card>
      )}

      {st?.ready && (
        <>
          <div className="cw-topbar">
            {/* Picking a result always lands in the LOCAL view — searching
                from the global galaxy dives straight into that node's web. */}
            <FundPicker onPick={(r) => cs.openFromGlobal(r.id)} />
            <span className="mono" style={{ fontSize: 10,
                  letterSpacing: ".12em", color: "var(--stone-500)" }}>
              STEPS
            </span>
            {[1, 2, 3].map((n) => (
              <Pill key={n} on={s.hops === n}
                    onClick={() => hold(() => cs.setHops(n))}>
                {n}
              </Pill>
            ))}
            <Button variant="ghost" busy={building} onClick={cs.startCrawl}
              style={{ padding: "5px 10px", fontSize: "12px" }}>
              Rebuild
            </Button>
            <Button variant="ghost"
              onClick={() => {
                if (s.mode === "global") { cs.setMode("ego"); return; }
                cs.setMode("global");
                cs.loadGlobal();
              }}
              style={{ padding: "5px 10px", fontSize: "12px" }}>
              {s.mode === "global" ? "Local view" : "Global view"}
            </Button>
            <Button variant="ghost" onClick={() => setShowViz((x) => !x)}
              style={{ padding: "5px 10px", fontSize: "12px" }}>
              Settings
            </Button>
            <span className="mono cw-asof">
              AS OF {String(st.crawled_at).slice(0, 10)} ·{" "}
              {st.nodes?.toLocaleString?.() || st.nodes} NODES ·{" "}
              {st.edges?.toLocaleString?.() || st.edges} EDGES
            </span>
            {daysSince(st.crawled_at) > 7 && (
              <span className="chip caution">OVER A WEEK OLD</span>
            )}
            {building && s.job?.current && (
              <span className="mono" style={{ fontSize: 10, color: "var(--teal-700)" }}>
                {s.job.current}
              </span>
            )}
          </div>

          {s.mode === "global" && (
            <div className="cw-layout">
              <div style={{ minWidth: 0 }}>
                {s.global.loading && (
                  <Card><div className="row"><Spinner size={16} />
                    <span className="muted small">
                      Loading the full web —{" "}
                      {st.nodes?.toLocaleString?.() || st.nodes} nodes…
                    </span>
                  </div></Card>
                )}
                {s.global.nodes && (
                  <div className="cw-stage">
                    {showViz ? (
                      <div className="cw-side">
                        <VizPanel onClose={() => setShowViz(false)}
                                  kindCounts={kindCounts} />
                      </div>
                    ) : (
                      <button type="button" className="mono cw-side-tab"
                        onClick={() => setShowViz(true)}>
                        GRAPH SETTINGS
                      </button>
                    )}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <GlobalWeb />
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {s.mode !== "global" && !s.center && (
            <Card>
              <Mascot state="filing" width={56}
                text="Search a fund above to spin its web." />
              <p className="muted" style={{ fontSize: "12.5px", margin: 0 }}>
                Companies and contacts work too — any node can be a center.
              </p>
            </Card>
          )}

          {s.mode !== "global" && s.center && (
            <div className="cw-layout">
              <div style={{ minWidth: 0 }}>
                <div className="cw-stage">
                  {showViz ? (
                    <div className="cw-side">
                      <VizPanel onClose={() => setShowViz(false)}
                                kindCounts={kindCounts} />
                    </div>
                  ) : (
                    <button type="button" className="mono cw-side-tab"
                      onClick={() => setShowViz(true)}>
                      GRAPH SETTINGS
                    </button>
                  )}
                  <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
                    <Web />
                    {/* The LP card floats over the canvas so the graph keeps
                        the full area; long lists scroll inside the card. */}
                    <div className="cw-lp-overlay"><LpPanel /></div>
                    {s.loadingEgo && (
                      <div style={{ position: "absolute", bottom: 10, left: 12 }}>
                        <Spinner size={16} />
                      </div>
                    )}
                  </div>
                </div>
                {s.meta?.truncated && (
                  <p className="muted" style={{ fontSize: "12px", margin: "6px 0 0" }}>
                    Showing {Object.keys(s.nodes).length} of{" "}
                    {s.meta.total_nodes_available} connected records — the
                    densest neighbors are in view; expand a node (double-click)
                    to pull in more.
                  </p>
                )}
                {Object.keys(s.nodes).length <= 1 && !s.loadingEgo && (
                  <Banner>
                    This record has no connections in the web yet — no
                    relations and no tagged meeting notes.
                  </Banner>
                )}
              </div>
            </div>
          )}
        </>
      )}
      <Panel />
    </div>
  );
}
