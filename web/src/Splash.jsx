/* Weybourne Investment Connector — opening animation.
   Ported natively from the Remotion "precision opening" (design bundle
   weybourne-remotion-opening): precision grid, brand blades flying in,
   editorial hero, signal lines converging, and the ENTER APP gate. Runs as
   CSS timeline over the real app shell, so pressing ENTER APP dissolves the
   veil straight into the live interface — no pre-rendered video, no mock
   screen. Plays once per session; prefers-reduced-motion collapses it. */
import React from "react";
import { Mascot } from "./ui.jsx";
import "./splash.css";

const SIGNALS = [
  ["INBOX", "Triage with context"],
  ["MEETINGS", "Notes that write themselves"],
  ["NOTION", "A workspace that keeps itself clean"],
];

export default function Splash({ children, speed = 1, onDone }) {
  // idle → the timeline plays and waits on ENTER APP.
  // hold → pressed: CHAO sits down and types while the desk "connects".
  // leave → the teal line sweeps and the veil dissolves into the live app.
  const [phase, setPhase] = React.useState("idle");

  React.useEffect(() => {
    sessionStorage.setItem("wb-splash-seen", "1");
  }, []);

  const enter = () => {
    if (phase !== "idle") return;
    setPhase("hold");
    setTimeout(() => setPhase("leave"), 2600 * speed);
    if (onDone) setTimeout(onDone, 3700 * speed);   // after the veil dissolve
  };

  const entered = phase !== "idle";
  return (
    <div className={"wb-splash-root"
                    + (entered ? " wb-activated" : "")
                    + (phase === "leave" ? " wb-entered" : "")}
         style={{ "--wb-speed": speed }}>
      <div className="wb-app">{children}</div>

      <div className="wb-veil">
        {/* Precision grid + roaming scan line + teal glow */}
        <div className="wb-grid" />
        <div className="wb-scan" />
        <div className="wb-veil-glow" />

        <div className="wb-corner wb-corner-l">
          WEYBOURNE FAMILY OFFICE · LONDON · SINGAPORE
        </div>
        <div className="wb-corner wb-corner-r">
          <i className="wb-brass-tick" />INVESTMENT CONNECTOR
        </div>

        <div className="wb-stage">
          {/* Left: the hero */}
          <div className="wb-hero">
            <div className="wb-mark-slot">
              <div className="wb-mark">
                <i className="wb-stroke" /><i className="wb-stroke" /><i className="wb-stroke" />
                <i className="wb-stroke" /><i className="wb-stroke" />
              </div>
            </div>
            <div className="wb-eyebrow">OUTLOOK · NOTION · CALENDAR · MEETINGS</div>
            <h1 className="wb-headline">Connecting your<br />investment tools.</h1>
            <div className="wb-rule" />
            <div className="wb-sub">
              One desk that reads the inbox, preps the meeting, takes the note
              and keeps the workspace clean.
            </div>
            <button type="button" className="wb-enter" onClick={enter}>
              <span className="wb-sheen" />
              <span className="wb-enter-ring" />
              ENTER APP <span className="wb-arrow">→</span>
            </button>
          </div>

          {/* Right: the mascot and the signals that converge on him */}
          <div className="wb-side">
            <div className="wb-mascot-block">
              <span className="wb-mascot" role="img"
                    aria-label="CHAO, the Weybourne assistant">
                {/* Both poses stay mounted; activation crossfades wave →
                    typing-at-the-laptop instead of hard-swapping the SVG. */}
                <span className="wb-pose wb-pose-wave">
                  <Mascot state="waving" width={176} />
                </span>
                <span className="wb-pose wb-pose-work">
                  <Mascot state="working" width={176} />
                </span>
              </span>
              <span className="wb-greeting">
                {entered ? "CHAO is wiring up your desk…" : "CHAO at your service"}
              </span>
            </div>
            <div className="wb-signals">
              {SIGNALS.map(([label, detail], i) => (
                <div key={label} className="wb-signal" style={{ "--i": i }}>
                  <span className="wb-diamond" />
                  <span className="wb-signal-label">{label}</span>
                  <span className="wb-signal-line" />
                  <span className="wb-signal-detail">{detail}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Activation: the teal line that sweeps across on ENTER APP */}
        <div className="wb-centerline" />
      </div>
    </div>
  );
}
