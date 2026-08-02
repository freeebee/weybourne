import { useEffect, useRef } from 'react';
import './splash.css';
import MascotWaving from './assets/mascot-waving.svg?react'; // vite-plugin-svgr; CRA: { ReactComponent as MascotWaving }

/**
 * Weybourne FI assistant — opening animation.
 *
 * Mount it over your app on first load. It self-dismisses: the splash layer
 * fades at 4.0s and the app underneath rises in at 4.1s (x `speed`).
 *
 *   <WeybourneSplash onDone={() => setBooted(true)}>
 *     <AppShell />
 *   </WeybourneSplash>
 *
 * The splash is purely CSS-driven, so it costs nothing per frame in React.
 */
export default function WeybourneSplash({
  children,
  speed = 1,                                   // 1 = as designed; 1.5 = 50% slower
  greeting = 'CHAO at your service',
  onDone,
}) {
  const root = useRef(null);

  useEffect(() => {
    if (!onDone) return;
    const t = setTimeout(onDone, 4800 * speed);
    return () => clearTimeout(t);
  }, [onDone, speed]);

  const seen = typeof sessionStorage !== 'undefined' && sessionStorage.getItem('wb-splash-seen');
  useEffect(() => { sessionStorage.setItem('wb-splash-seen', '1'); }, []);
  if (seen) return <>{children}</>;             // play once per session — drop if you want it every load

  return (
    <div className="wb-splash-root" ref={root} style={{ '--wb-speed': speed }}>
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
            <MascotWaving className="wb-mascot" role="img" aria-label="Wey, the Weybourne assistant" />
            <span className="wb-greeting">{greeting}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
