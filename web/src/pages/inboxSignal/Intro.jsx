import React from "react";
import { Button } from "../../ui.jsx";

/* The Inbox Signal opening.

   Ported from the standalone dashboard's intro, with one substantive change:
   its orbiting terms were a hardcoded list, so the opening said the same thing
   whatever the mailbox held. These are the real top themes with their real
   counts, which makes the opening a reading of this mailbox rather than
   decoration in front of it.

   Motion is driven frame by frame rather than by CSS transitions, because the
   words orbit continuously and the disintegration needs per-particle control.
   Two safety rails, both load-bearing:

   * ``onEnter`` is fired by a timer as well as by the animation finishing, so a
     dropped frame or a throttled background tab can never strand the reader on
     the splash with no way through.
   * ``prefers-reduced-motion`` skips the orbit and the dust entirely — the
     button still works, it simply goes straight in.
*/

const WORD_COUNT = 16;

/* Orbits are derived from the theme's index, not randomised: the opening looks
   the same on every replay within a session, and there is no frame-one jump
   while random values settle. */
/* The radii floor at 0.70/0.62 rather than filling the field: the copy sits in
   an 860px column down the middle, and a tighter ring puts orbiting terms
   straight through the headline and the stats row. This keeps them in a band
   outside the text while still crossing the corners. */
function orbitFor(i, n, weight) {
  const dir = i % 2 === 0 ? 1 : -1;
  return {
    a: (i / n) * Math.PI * 2 + (i % 3) * 0.11,
    rx: 0.70 + ((i * 7) % 5) * 0.05,
    ry: 0.62 + ((i * 3) % 5) * 0.07,
    sp: dir * (0.045 + ((i * 11) % 6) / 110),
    size: 1.1 + weight * 1.35,
    op: 0.26 + weight * 0.2,
  };
}

export default function Intro({ data, onEnter }) {
  const hostRef = React.useRef(null);
  const canvasRef = React.useRef(null);
  const btnRef = React.useRef(null);
  const phaseRef = React.useRef("orbit");
  const doneRef = React.useRef(false);

  const counts = data.counts || {};
  const themes = data.themes || [];

  const words = React.useMemo(() => {
    const top = themes.slice(0, WORD_COUNT);
    const max = Math.max(1, ...top.map((t) => t.total));
    return top.map((t, i) => ({
      text: t.label,
      count: t.total,
      ...orbitFor(i, top.length || 1, t.total / max),
      tint: i % 3 === 0 ? "var(--teal-300)" : "var(--stone-400)",
    }));
  }, [themes]);

  const finish = React.useCallback(() => {
    if (doneRef.current) return;
    doneRef.current = true;
    onEnter();
  }, [onEnter]);

  // ---- orbit + disintegration, one loop ----------------------------------- //
  React.useEffect(() => {
    const reduce = typeof matchMedia === "function"
      && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return undefined;

    let raf = 0;
    const t0 = performance.now();
    let collapseAt = 0, parts = null, wordEls = null, bx = 0, by = 0, dustEnd = 0;

    const nodes = () => Array.from(hostRef.current?.querySelectorAll("[data-word]") || []);

    const centreOf = (w, host, t) => {
      const a = w.a + t * w.sp * (Math.PI / 2);
      return {
        x: host.width / 2 + Math.cos(a) * w.rx * (host.width / 2),
        y: host.height / 2 + Math.sin(a) * w.ry * (host.height / 2),
      };
    };

    const step = (now) => {
      raf = requestAnimationFrame(step);
      const host = hostRef.current;
      if (!host) return;
      const hr = host.getBoundingClientRect();
      const t = (now - t0) / 1000;
      const els = nodes();

      if (phaseRef.current === "orbit") {
        els.forEach((el, i) => {
          const w = words[i];
          if (!w) return;
          const c = centreOf(w, hr, t), c0 = centreOf(w, hr, 0);
          el.style.transform =
            `translate(-50%, -50%) translate(${(c.x - c0.x).toFixed(1)}px, ${(c.y - c0.y).toFixed(1)}px)`;
        });
        return;
      }

      // ---- collapse: every term is sampled into dust that spirals into the
      //      button, furthest term first so the field ripples inward.
      const canvas = canvasRef.current;
      if (!canvas) { finish(); return; }
      const ctx = canvas.getContext("2d");
      const elapsed = now - collapseAt;
      ctx.clearRect(0, 0, hr.width, hr.height);

      // Terms not yet broken carry on orbiting until their own turn arrives.
      wordEls.forEach((wd) => {
        if (elapsed >= wd.delay + 40) return;
        const c = centreOf(wd.w, hr, t), c0 = centreOf(wd.w, hr, 0);
        wd.el.style.transform =
          `translate(-50%, -50%) translate(${(c.x - c0.x).toFixed(1)}px, ${(c.y - c0.y).toFixed(1)}px)`;
        });

      parts.forEach((p) => {
        const pt = (elapsed - p.delay) / p.life;
        if (pt <= 0 || pt >= 1) return;
        const wd = wordEls[p.wi];
        const at = (collapseAt + p.delay - t0) / 1000;
        const c = centreOf(wd.w, hr, at);
        const sx = c.x + p.lx - bx, sy = c.y + p.ly - by;
        const rad = Math.hypot(sx, sy), ang0 = Math.atan2(sy, sx);
        const e = 1 - Math.pow(1 - pt, 2.6);
        // A short outward puff before the pull-in, so the word crumbles rather
        // than simply sliding to the button.
        const puff = Math.sin(Math.min(1, pt / 0.4) * Math.PI) * 0.2;
        const radius = rad * (1 - e) * (1 + puff) + p.drift * (1 - e);
        const angle = ang0 + wd.w.sp * (Math.PI / 2) * (pt * p.life / 1000) * 2.4
          + p.spin * e * 1.9;
        ctx.globalAlpha = Math.max(0, pt < 0.18 ? pt * 4.4 : 0.85 * (1 - Math.pow(pt, 3.2)));
        ctx.fillStyle = p.colour;
        ctx.beginPath();
        ctx.arc(bx + Math.cos(angle) * radius, by + Math.sin(angle) * radius,
                p.size * (1 - 0.45 * e), 0, 6.2832);
        ctx.fill();
      });
      ctx.globalAlpha = 1;
      if (elapsed >= dustEnd) { ctx.clearRect(0, 0, hr.width, hr.height); finish(); }
    };

    const build = () => {
      const host = hostRef.current, canvas = canvasRef.current;
      if (!host || !canvas) return false;
      const hr = host.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(hr.width * dpr);
      canvas.height = Math.round(hr.height * dpr);
      canvas.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);

      const br = btnRef.current?.getBoundingClientRect();
      bx = br ? br.left + br.width / 2 - hr.left : hr.width / 2;
      by = br ? br.top + br.height / 2 - hr.top : hr.height / 2;

      wordEls = nodes().map((el, i) => {
        const r = el.getBoundingClientRect();
        return {
          el, w: words[i], width: r.width, height: r.height,
          colour: getComputedStyle(el).color,
          distance: Math.hypot(r.left - hr.left + r.width / 2 - bx,
                               r.top - hr.top + r.height / 2 - by),
        };
      }).filter((x) => x.w);
      if (!wordEls.length) return false;
      wordEls.sort((a, b) => b.distance - a.distance);

      parts = [];
      wordEls.forEach((wd, order) => {
        wd.delay = order * 46;
        const n = Math.max(16, Math.round(wd.width / 3.6));
        for (let k = 0; k < n; k++) {
          parts.push({
            wi: order,
            lx: (Math.random() - 0.5) * wd.width,
            ly: (Math.random() - 0.5) * wd.height,
            spin: (Math.random() < 0.5 ? -1 : 1) * (0.8 + Math.random() * 1.3),
            size: 0.9 + Math.random() * 1.7,
            colour: wd.colour,
            delay: wd.delay + Math.random() * 150,
            drift: (Math.random() - 0.5) * 24,
            life: 430 + Math.random() * 210,
          });
        }
        setTimeout(() => { wd.el.style.opacity = "0"; }, wd.delay + 40);
      });
      dustEnd = Math.max(...parts.map((p) => p.delay + p.life)) + 40;
      return true;
    };

    const onStart = () => {
      if (phaseRef.current === "collapse") return;
      if (!build()) { finish(); return; }
      collapseAt = performance.now();
      phaseRef.current = "collapse";
    };
    window.addEventListener("wb-signal-enter", onStart);
    raf = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("wb-signal-enter", onStart);
    };
  }, [words, finish]);

  const enter = () => {
    const reduce = typeof matchMedia === "function"
      && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { finish(); return; }
    window.dispatchEvent(new Event("wb-signal-enter"));
    // The way through never depends on the animation finishing, or on any
    // frames running at all.
    setTimeout(finish, 1500);
  };

  const stats = [
    ["Managers heard from", counts.organisations || 0],
    ["Letters read", counts.letters || 0],
    ["Quotes held", counts.quotes || 0],
    ["Themes tracked", themes.length],
  ];

  return (
    <div className="wb-intro">
      <div className="wb-intro-field" ref={hostRef} aria-hidden="true">
        <canvas ref={canvasRef} className="wb-intro-dust" />
        {words.map((w, i) => (
          <span
            key={w.text} data-word="1"
            style={{
              position: "absolute",
              left: `${(50 + Math.cos(w.a) * w.rx * 50).toFixed(2)}%`,
              top: `${(50 + Math.sin(w.a) * w.ry * 50).toFixed(2)}%`,
              transform: "translate(-50%, -50%)",
              fontFamily: "var(--serif)", fontSize: `${w.size}rem`, fontWeight: 300,
              color: w.tint, opacity: w.op, whiteSpace: "nowrap",
              willChange: "transform, opacity",
            }}
          >
            {w.text}
          </span>
        ))}
      </div>

      <div className="wb-intro-body">
        <div className="wb-intro-lockup">
          <img src="/brand/weybourne-mark-light.png" alt="" />
          <span className="mono">Weybourne Investments · Shared inbox</span>
        </div>

        <h1>Collective intelligence</h1>
        <div className="wb-intro-rule" />

        <p className="wb-intro-lead">
          The desk already holds a view. It is scattered across {counts.letters || 0}{" "}
          {counts.letters === 1 ? "letter" : "letters"} from {counts.organisations || 0}{" "}
          {counts.organisations === 1 ? "manager" : "managers"}.
        </p>
        <p className="wb-intro-sub">
          Manager letters, risk reports and macro research, read together rather than one at
          a time. Where the desk agrees. Where it does not. Who has changed their mind.
        </p>

        <div className="wb-intro-stats">
          {stats.map(([label, value]) => (
            <div key={label}>
              <span className="mono wb-intro-figure">{value}</span>
              <span className="mono wb-intro-statlabel">{label}</span>
            </div>
          ))}
        </div>

        <div ref={btnRef} className="wb-intro-cta">
          <Button onClick={enter}>Enter dashboard</Button>
        </div>

        <div className="mono wb-intro-foot">
          {data.coverage || ""} · wbinvestments@weybourne.co.uk
        </div>
      </div>
    </div>
  );
}
