import React from "react";
import { Link, NavLink, Route, HashRouter as Router, Routes } from "react-router-dom";
import { get } from "./api.js";
import * as liveStore from "./liveStore.js";
import FundData from "./pages/FundData.jsx";
import Home from "./pages/Home.jsx";
import Live from "./pages/Live.jsx";
import Prep from "./pages/Prep.jsx";
import TrackRecords from "./pages/TrackRecords.jsx";
import Triage from "./pages/Triage.jsx";
import WhatsNew from "./pages/WhatsNew.jsx";
import { Spinner } from "./ui.jsx";

const NAV = [
  ["/", "Home"],
  ["/triage", "Inbox triage"],
  ["/prep", "Meeting prep"],
  ["/track-records", "Track records"],
  ["/live", "Live meeting"],
  ["/fund-data", "Fund data"],
  ["/whats-new", "What's new"],
];

const JOB_ROUTE = { prep: "/prep", "whats-new-team": "/whats-new",
                    "whats-new-inbox": "/whats-new", "outlook-refresh": "/" };

function LiveChip() {
  React.useSyncExternalStore(liveStore.subscribe, liveStore.getVersion);
  const s = liveStore.S;
  if (!s.running) return null;
  const words = s.transcript ? s.transcript.split(/\s+/).length : 0;
  return (
    <Link to="/live" style={{
      display: "flex", alignItems: "center", gap: ".55rem",
      color: "var(--teal-300)", fontSize: ".82rem", padding: ".35rem .8rem",
      textDecoration: "none",
    }}>
      <span style={{
        width: 8, height: 8, borderRadius: "50%", background: "var(--teal-300)",
        animation: "wb-pulse 1.6s ease-in-out infinite",
      }} />
      Live meeting · recording · {words} words
    </Link>
  );
}

function JobsTray() {
  const [jobs, setJobs] = React.useState([]);

  React.useEffect(() => {
    let timer;
    const poll = async () => {
      try {
        const { jobs: js } = await get("/api/jobs");
        setJobs(js.filter((j) => j.status === "running"));
      } catch { /* backend briefly away — keep the last state */ }
      timer = setTimeout(poll, 3000);
    };
    poll();
    return () => clearTimeout(timer);
  }, []);

  if (!jobs.length) return null;
  return (
    <div style={{ marginTop: "auto", padding: ".6rem .5rem", borderTop: "1px solid rgba(255,255,255,.12)" }}>
      {jobs.map((j) => (
        <Link key={j.id} to={JOB_ROUTE[j.kind] || "/"} style={{
          display: "flex", alignItems: "center", gap: ".55rem",
          color: "var(--teal-300)", fontSize: ".82rem", padding: ".25rem .3rem",
          textDecoration: "none",
        }}>
          <Spinner size={12} />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {j.label} · {j.elapsed}s
          </span>
        </Link>
      ))}
    </div>
  );
}

export default function App() {
  return (
    <Router>
      <div className="shell">
        <nav className="sidebar">
          <img className="mark" src="/brand/weybourne-mark-light.png" alt="Weybourne" />
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) => "nav" + (isActive ? " active" : "")}>
              {label}
            </NavLink>
          ))}
          <LiveChip />
          <JobsTray />
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
