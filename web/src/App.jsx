import React from "react";
import { NavLink, Route, HashRouter as Router, Routes } from "react-router-dom";
import { get } from "./api.js";
import * as felixStore from "./felixStore.js";
import * as liveStore from "./liveStore.js";
import ContactCard from "./pages/ContactCard.jsx";
import FixItFelix from "./pages/FixItFelix.jsx";
import FundData from "./pages/FundData.jsx";
import Home from "./pages/Home.jsx";
import Live from "./pages/Live.jsx";
import Prep from "./pages/Prep.jsx";
import TrackRecords from "./pages/TrackRecords.jsx";
import Triage from "./pages/Triage.jsx";
import WhatsNew from "./pages/WhatsNew.jsx";
import Splash from "./Splash.jsx";
import * as uiStore from "./uiStore.js";

const GROUPS = [
  ["OVERVIEW", [["/", "Home"]]],
  ["WORKFLOW", [["/triage", "Inbox triage"], ["/prep", "Meeting prep"], ["/live", "Note taker"]]],
  ["ANALYSIS", [["/track-records", "Track records"], ["/fund-data", "Fund data"], ["/whats-new", "What's new"]]],
  ["UPKEEP", [["/felix", "Fix-it Felix"], ["/contact-card", "Contact creator"]]],
];

function NavMeta({ to }) {
  React.useSyncExternalStore(uiStore.subscribe, uiStore.getVersion);
  React.useSyncExternalStore(liveStore.subscribe, liveStore.getVersion);
  React.useSyncExternalStore(felixStore.subscribe, felixStore.getVersion);
  if (to === "/triage" && uiStore.ui.inboxCount != null) {
    return <span className="meta">{uiStore.ui.inboxCount}</span>;
  }
  if (to === "/live" && liveStore.S.running) {
    return <span className="dot" style={{ background: "var(--teal-300)", animation: "wb-pulse 1.6s ease-in-out infinite" }} />;
  }
  if (to === "/felix" && felixStore.S.runJob?.status === "running") {
    return <span className="dot" style={{ background: "var(--brass-500)", animation: "wb-pulse 1.6s ease-in-out infinite" }} />;
  }
  return null;
}

function SideFoot() {
  React.useSyncExternalStore(liveStore.subscribe, liveStore.getVersion);
  const [jobs, setJobs] = React.useState([]);
  const [status, setStatus] = React.useState(null);

  React.useEffect(() => {
    let timer;
    const poll = async () => {
      try {
        const { jobs: js } = await get("/api/jobs");
        setJobs(js.filter((j) => j.status === "running"));
      } catch { /* keep last */ }
      timer = setTimeout(poll, 3000);
    };
    poll();
    get("/api/status").then(setStatus).catch(() => {});
    return () => clearTimeout(timer);
  }, []);

  const liveRunning = liveStore.S.running;
  const words = liveStore.S.transcript ? liveStore.S.transcript.split(/\s+/).length : 0;

  return (
    <div className="sidefoot">
      {(liveRunning || jobs.length > 0) && (
        <>
          <span className="flabel">Running</span>
          {liveRunning && (
            <NavLink to="/live" className="frow live">
              <span className="dot" style={{ background: "var(--teal-300)" }} />
              Live meeting · {words} words
            </NavLink>
          )}
          {jobs.map((j) => (
            <NavLink key={j.id} to="/prep" className="frow">
              <span className="dot" style={{ background: "var(--brass-500)" }} />
              {j.label} · {j.elapsed}s
            </NavLink>
          ))}
          <hr />
        </>
      )}
      {status && (
        <>
          {[["Outlook", status.outlook], ["Notion", status.notion],
            ["Claude", status.ai]].map(([name, s]) => (
            <div className="conn" key={name}>
              <span className="cname">{name}</span>
              <span className={"cstate " + (s.ok ? "live" : "demo")}>
                {s.ok ? "LIVE" : "DEMO"}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

/* Kick off the What's new digests as soon as the app opens, so the briefing
   is ready (or well under way) by the time the page is visited. The page's
   own auto-job hook then attaches to the running job or shows the result. */
function useWarmWhatsNew() {
  React.useEffect(() => {
    ["whats-new-team", "whats-new-inbox"].forEach(async (kind) => {
      try {
        const { jobs } = await get(`/api/jobs?kind=${kind}`);
        if (!jobs.length) await fetch(`/api/jobs/${kind}`, { method: "POST" });
      } catch { /* backend warming up — the page will start it on visit */ }
    });
    // Re-attach to a running Outlook refresh no matter which page loads first.
    uiStore.restoreOutlookRefresh();
    // Same for a running Felix clean-up (and the sidebar's activity dot).
    felixStore.restore();
  }, []);
}

export default function App() {
  useWarmWhatsNew();
  // Opening animation — once per session; afterwards the shell renders bare.
  // The homepage's "Replay opening" button fires wb-replay-splash to bring
  // it back on demand.
  const [booted, setBooted] = React.useState(
    () => !!sessionStorage.getItem("wb-splash-seen"));
  React.useEffect(() => {
    const replay = () => setBooted(false);
    window.addEventListener("wb-replay-splash", replay);
    return () => window.removeEventListener("wb-replay-splash", replay);
  }, []);
  const shell = <AppShell />;
  if (!booted) return <Splash onDone={() => setBooted(true)}>{shell}</Splash>;
  return shell;
}

function AppShell() {
  return (
    <Router>
      <div className="shell">
        <nav className="sidebar">
          <div className="lockup">
            <img src="/brand/weybourne-mark-light.png" alt="" />
            <div>
              <div className="word">WEYBOURNE</div>
              <div className="sub">INVESTMENT CONNECTOR</div>
            </div>
          </div>
          <div className="navgroups">
            {GROUPS.map(([glabel, items]) => (
              <div className="navgroup" key={glabel}>
                <span className="glabel">{glabel}</span>
                {items.map(([to, label]) => (
                  <NavLink key={to} to={to} end={to === "/"}
                    className={({ isActive }) => "nav" + (isActive ? " active" : "")}>
                    {label}
                    <NavMeta to={to} />
                  </NavLink>
                ))}
              </div>
            ))}
          </div>
          <SideFoot />
        </nav>
        <main className="main">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/triage" element={<Triage />} />
            <Route path="/prep" element={<Prep />} />
            <Route path="/track-records" element={<TrackRecords />} />
            <Route path="/live" element={<Live />} />
            <Route path="/fund-data" element={<FundData />} />
            <Route path="/whats-new" element={<WhatsNew />} />
            <Route path="/felix" element={<FixItFelix />} />
            <Route path="/contact-card" element={<ContactCard />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}
