import React from "react";
import { NavLink, Route, HashRouter as Router, Routes } from "react-router-dom";
import { get } from "./api.js";
import * as liveStore from "./liveStore.js";
import FundData from "./pages/FundData.jsx";
import Home from "./pages/Home.jsx";
import Live from "./pages/Live.jsx";
import Prep from "./pages/Prep.jsx";
import TrackRecords from "./pages/TrackRecords.jsx";
import Triage from "./pages/Triage.jsx";
import WhatsNew from "./pages/WhatsNew.jsx";
import * as uiStore from "./uiStore.js";

const GROUPS = [
  ["OVERVIEW", [["/", "Home"]]],
  ["WORKFLOW", [["/triage", "Inbox triage"], ["/prep", "Meeting prep"], ["/live", "Live meeting"]]],
  ["ANALYSIS", [["/track-records", "Track records"], ["/fund-data", "Fund data"], ["/whats-new", "What's new"]]],
];

function NavMeta({ to }) {
  React.useSyncExternalStore(uiStore.subscribe, uiStore.getVersion);
  React.useSyncExternalStore(liveStore.subscribe, liveStore.getVersion);
  if (to === "/triage" && uiStore.ui.inboxCount != null) {
    return <span className="meta">{uiStore.ui.inboxCount}</span>;
  }
  if (to === "/live" && liveStore.S.running) {
    return <span className="dot" style={{ background: "var(--teal-300)", animation: "wb-pulse 1.6s ease-in-out infinite" }} />;
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

export default function App() {
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
          </Routes>
        </main>
      </div>
    </Router>
  );
}
