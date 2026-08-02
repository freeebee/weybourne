/* Weybourne FI assistant — opening animation (design_handoff_opening_animation).
   Mounts OVER the app shell; the veil dissolves at 4.0s and the app rises in
   underneath. Purely CSS-driven — React only runs the completion timer.
   Plays once per session; prefers-reduced-motion collapses it to instant. */
import React from "react";
import { Mascot } from "./ui.jsx";
import "./splash.css";

export default function Splash({ children, speed = 1, onDone }) {
  React.useEffect(() => {
    sessionStorage.setItem("wb-splash-seen", "1");
    if (!onDone) return;
    const t = setTimeout(onDone, 4800 * speed);
    return () => clearTimeout(t);
  }, [onDone, speed]);

  return (
    <div className="wb-splash-root" style={{ "--wb-speed": speed }}>
      <div className="wb-app">{children}</div>

      <div className="wb-veil">
        <div className="wb-veil-glow" />
        <div className="wb-lockup">
          <div className="wb-mark-slot">
            <div className="wb-mark">
              <i className="wb-stroke" /><i className="wb-stroke" /><i className="wb-stroke" />
              <i className="wb-stroke" /><i className="wb-stroke" />
            </div>
          </div>

          <div className="wb-text">
            <div className="wb-wordmark">Weybourne</div>
            <div className="wb-rule" />
            <div className="wb-eyebrow">FI ASSISTANT</div>
          </div>

          <div className="wb-mascot-block">
            <span className="wb-mascot" role="img" aria-label="Wey, the Weybourne assistant">
              <Mascot state="waving" width={176} />
            </span>
            <span className="wb-greeting">CHAO at your service</span>
          </div>
        </div>
      </div>
    </div>
  );
}
