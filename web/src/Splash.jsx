/* Weybourne Investment Connector — opening animation.
   Ported natively from the Remotion "precision opening" (design bundle
   weybourne-remotion-opening): precision grid, brand blades flying in,
   editorial hero, signal lines converging, and the ENTER APP gate. Runs as
   CSS timeline over the real app shell, so pressing ENTER APP dissolves the
   veil straight into the live interface — no pre-rendered video, no mock
   screen. Plays once per session; prefers-reduced-motion collapses it. */
import React from "react";
import "./splash.css";

/* CHAO drawn as ONE inline SVG holding both poses, so activation is a real
   motion: the waving arm swings down onto the keyboard, the desk and laptop
   rise in, and the face refocuses — no crossfade between separate images.
   Parts are copied from mascot-waving.svg / mascot-working.svg. */
function WbChao() {
  const head = (variant) => (
    <g className={`wbc-head wbc-head-${variant}`} transform="translate(70,24)">
      {/* inner group so the rage head can be thrown back in CSS without
          clobbering the SVG translate above */}
      <g className="wbc-headin">
      <ellipse cx="24" cy="60" rx="5" ry="7.5" fill="#EBBB94" />
      <ellipse cx="76" cy="60" rx="5" ry="7.5" fill="#EBBB94" />
      <path d="M26 40 C26 31 34 25 50 25 C66 25 74 31 74 40 V57 C74 76 64 88 50 88 C36 88 26 76 26 57 Z" fill="#F3CBA8" />
      <path d="M50 11 C32 11 23 24 24 40 C24.3 44 26 44 26.6 41 C27.8 37 30 35 34.5 33.4 C44 36 62 35.5 70 39.5 C73.4 41.2 74.8 43 75.4 45 C76.2 47.6 78 47 78 42 C78 23 68 11 50 11 Z" fill="#1C2430" />
      <path d="M28 44 C29 31 37 25 50 25 C59 25 65 27.5 69 32 C60 29.5 45 30.5 37 36 C33 38.6 30 41 28 44 Z" fill="#232C3A" />
      {variant === "happy" ? (
        <g stroke="#1C2430" strokeWidth="2.6" strokeLinecap="round" fill="none">
          <path d="M31 46 q6 -3 12 -1" /><path d="M69 46 q-6 -3 -12 -1" />
        </g>
      ) : (
        <g stroke="#1C2430" strokeWidth="2.8" strokeLinecap="round" fill="none">
          <path d="M31 44 q6 1 12 3" /><path d="M69 44 q-6 1 -12 3" />
        </g>
      )}
      <g fill="#FFFFFF" opacity=".45">
        <rect x="28.5" y="50.5" width="18" height="14" rx="4.5" />
        <rect x="53.5" y="50.5" width="18" height="14" rx="4.5" />
      </g>
      <g fill="none" stroke="#23272E" strokeWidth="2.6" strokeLinecap="round">
        <rect x="28.5" y="50.5" width="18" height="14" rx="4.5" />
        <rect x="53.5" y="50.5" width="18" height="14" rx="4.5" />
        <path d="M46.5 55.5 h7" /><path d="M28.5 54 l-5.5 3" /><path d="M71.5 54 l5.5 3" />
      </g>
      {variant === "happy" && (
        <>
          <g stroke="#1C2430" strokeWidth="2.8" strokeLinecap="round" fill="none">
            <path d="M33 59.5 q4.5 -5.5 9 0" /><path d="M58 59.5 q4.5 -5.5 9 0" />
          </g>
          <path d="M40 72 q10 13 20 0 Z" fill="#8C4038" />
        </>
      )}
      {variant === "focus" && (
        <>
          <g fill="#1C2430">
            <circle cx="37.5" cy="58" r="2.9" /><circle cx="62.5" cy="58" r="2.9" />
          </g>
          <path d="M44 77 h12" stroke="#A2664B" strokeWidth="2.6" fill="none"
                strokeLinecap="round" />
        </>
      )}
      {variant === "rage" && (
        <>
          {/* eyes screwed shut + a huge open-mouthed yell, per the GIF */}
          <g stroke="#1C2430" strokeWidth="2.8" strokeLinecap="round" fill="none">
            <path d="M33 57 q4.5 5 9 0" /><path d="M58 57 q4.5 5 9 0" />
          </g>
          <ellipse cx="50" cy="76" rx="11.5" ry="10" fill="#8C4038" />
          <path d="M43 82 q7 5.5 14 0" fill="#6E2F29" />
          <path d="M40.5 69 h19" stroke="#FFFFFF" strokeWidth="2.6"
                strokeLinecap="round" />
        </>
      )}
      </g>
    </g>
  );

  return (
    <svg viewBox="0 0 240 240" width="176" height="176" aria-hidden="true">
      {/* desk (behind him) — rises in on activation */}
      <g className="wbc-deskpart">
        <rect x="0" y="198" width="240" height="7" rx="2" fill="#C9B392" />
        <rect x="0" y="205" width="240" height="6" fill="#B39C79" />
      </g>
      {/* torso + both heads (the face crossfades happy → focused in place) */}
      <g className="wbc-body">
        <path d="M110 104 h20 v18 h-20 Z" fill="#E0AC85" />
        <path d="M120 116 C103 116 84 127 79 147 C74 167 75 188 77 202 H163 C165 188 166 167 161 147 C156 127 137 116 120 116 Z" fill="#4E7A9B" />
        <path d="M103 123 L120 143 L137 123 C131 118 126 116 120 116 C114 116 109 118 103 123 Z" fill="#1B2A38" />
        <g stroke="#3F6A8B" strokeWidth="2.2" strokeLinecap="round" opacity=".85">
          <path d="M80 152 H160" /><path d="M78 172 H162" /><path d="M77 192 H163" />
        </g>
        {head("happy")}
        {head("focus")}
        {head("rage")}
      </g>
      {/* laptop (in front of him) — rises with the desk, jolts on the slams */}
      <g className="wbc-deskpart wbc-laptop">
        <rect x="88" y="148" width="64" height="40" rx="4" fill="#22394A" />
        <rect x="93" y="153" width="54" height="30" rx="2" fill="#31536A" />
        <circle cx="120" cy="168" r="6" fill="#249692" opacity=".85" />
        <path d="M74 188 h92 l10 12 h-112 Z" fill="#9FB2BD" />
        <path d="M74 188 h92 l2 3 h-96 Z" fill="#8298A6" />
      </g>
      {/* left arm: resting at his side → onto the keyboard */}
      <g className="wbc-armL-idle">
        <path d="M94 140 C70 150 64 174 74 188" stroke="#41688A" strokeWidth="15"
              strokeLinecap="round" fill="none" />
        <circle cx="75" cy="190" r="8.5" fill="#31567A" />
        <circle cx="75" cy="192" r="7.5" fill="#F3CBA8" />
      </g>
      <g className="wbc-armL-type">
        <path d="M89 146 C80 160 86 178 102 186" stroke="#41688A" strokeWidth="15"
              strokeLinecap="round" fill="none" />
        <circle cx="103" cy="186" r="7" fill="#F3CBA8" />
      </g>
      {/* right arm: waving overhead → swings down onto the keyboard */}
      <g className="wbc-armR-idle">
        <path d="M152 146 C168 138 172 112 168 92" stroke="#41688A" strokeWidth="15"
              strokeLinecap="round" fill="none" />
        <circle cx="167" cy="86" r="9" fill="#F3CBA8" />
      </g>
      <g className="wbc-sparks" stroke="#249692" strokeWidth="2.6"
         strokeLinecap="round" opacity=".85" fill="none">
        <path d="M182 74 l8 -6" /><path d="M184 86 l9 0" /><path d="M180 62 l5 -8" />
      </g>
      <g className="wbc-armR-type">
        <path d="M151 146 C160 160 154 178 138 186" stroke="#41688A" strokeWidth="15"
              strokeLinecap="round" fill="none" />
        <circle cx="137" cy="186" r="7" fill="#F3CBA8" />
      </g>
      {/* impact debris — flashes when the hands come down on the keyboard */}
      <g className="wbc-slam" stroke="#9FB2BD" strokeWidth="2.4"
         strokeLinecap="round" fill="none" opacity="0">
        <path d="M70 182 l-9 -5" /><path d="M68 192 l-10 1" />
        <path d="M170 182 l9 -5" /><path d="M172 192 l10 1" />
        <path d="M78 172 l-6 -8" /><path d="M163 172 l6 -8" />
      </g>
    </svg>
  );
}

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
    // The hold covers the whole bit: arms land (~0.8s), a long stretch of
    // accelerating typing (~1.5s), wind-up + double keyboard slam + grimace
    // (~2.5s). The veil then starts leaving almost on top of the scream —
    // the joke is the scream, and holding on it past the laugh kills it.
    setTimeout(() => setPhase("leave"), 2850 * speed);
    if (onDone) setTimeout(onDone, 3800 * speed);   // after the veil dissolve
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
                <WbChao />
              </span>
              <span className="wb-greeting">
                {entered ? "CHAO is preparing your workstation…" : "CHAO at your service"}
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
