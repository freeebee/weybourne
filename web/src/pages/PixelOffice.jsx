/* Fix-it Felix's office — a side-view pixel scene with five working stations.

   The scene is drawn at a fixed design size and scaled as one unit, so the
   furniture, the plaques and Felix always keep their relative sizes and can
   never overlap at a narrow width. Positions are integers in design space;
   the only floating-point number in the whole file is the scale factor.

   Every station is a real button: it filters the review list below to that
   database, which is the same action the filter chips perform. The scene is
   theatre, but the theatre is wired to the record.
*/
import React from "react";
import * as fx from "../felixStore.js";
import { Mascot } from "../ui.jsx";

/* -- design space ---------------------------------------------------------- */
export const SCENE_W = 1600;
export const SCENE_H = 430;
const FLOOR_Y = 300;          // where the wall stops and the boards start
const PLAQUE_Y = 348;         // brass labels sit below the walk line
const MASCOT_H = 116;

/* Station order is the reference's order, left to right, and doubles as the
   patrol route. `x` is the centre in design pixels. */
export const STATIONS = [
  { id: "contacts", x: 210, label: "CONTACTS", db: "contacts" },
  { id: "companies", x: 505, label: "COMPANIES", db: "companies" },
  { id: "funds", x: 790, label: "FUNDS", db: "funds" },
  { id: "notes", x: 1110, label: "NOTES", db: "notes" },
  { id: "research", x: 1410, label: "RESEARCH", db: "" },
];
const STATION_BY_ID = Object.fromEntries(STATIONS.map((s) => [s.id, s]));

/* -- palette --------------------------------------------------------------- */
const C = {
  wall: "#F0E8D8", wallLit: "#F6F0E3", wallShade: "#E4D9C3",
  floor: "#C6A67C", floorDark: "#B6926A", board: "#BE9B70",
  skirt: "#A8814F", mat: "#DDCDAB", matEdge: "#CBB791",
  sand: "#C9B392", sandDark: "#AE9670", sandLight: "#DAC7A6",
  wood: "#A97C4B", woodDark: "#8A6642",
  brass: "#B0894E", brassLight: "#CDA76A",
  navy: "#1C2E44", cobalt: "#2F5D8A", cobaltLight: "#43769F",
  steel: "#8FA6B5", teal: "#2E6B66", tealBright: "#249692", tealPale: "#7FBDB8",
  paper: "#F7F3EA", ink: "#1C2430", leaf: "#4E7D52", leafDark: "#3B6340",
};

/* Tiny helper: a filled rect. Everything here is axis-aligned integers, which
   is what keeps the edges crisp at any scale. */
const R = (x, y, w, h, fill, key) => (
  <rect key={key} x={x} y={y} width={w} height={h} fill={fill} />
);

/* -- furniture ------------------------------------------------------------- */
/* Each piece draws in its own local coordinates with its feet on y=0, so a
   station can be moved by changing one number above. */

function ContactsArt() {
  return (
    <g>
      {/* filing cabinet */}
      {R(0, -118, 62, 118, C.sand)}
      {R(0, -118, 62, 4, C.sandLight)}
      {[0, 1, 2].map((i) => (
        <g key={i}>
          {R(6, -110 + i * 37, 50, 31, C.sandDark)}
          {R(6, -110 + i * 37, 50, 2, C.sandLight)}
          {R(24, -98 + i * 37, 14, 5, C.woodDark)}
        </g>
      ))}
      {/* plant on top */}
      {R(22, -140, 18, 22, C.sandDark)}
      {R(24, -138, 14, 4, C.wood)}
      {R(28, -160, 6, 22, C.leafDark)}
      {R(18, -156, 12, 6, C.leaf)}
      {R(32, -164, 14, 6, C.leaf)}
      {R(22, -148, 10, 5, C.leaf)}
      {/* desk unit */}
      {R(74, -86, 130, 10, C.wood)}
      {R(74, -86, 130, 3, C.brassLight)}
      {R(78, -76, 122, 76, C.sand)}
      {R(78, -76, 58, 76, C.sandDark)}
      {R(140, -76, 60, 76, C.sandDark)}
      {R(100, -44, 14, 4, C.woodDark)}
      {R(162, -44, 14, 4, C.woodDark)}
      {/* document tray + card */}
      {R(88, -116, 54, 30, C.wood)}
      {R(92, -112, 46, 22, C.sandLight)}
      {R(100, -106, 30, 3, C.woodDark)}
      {R(100, -100, 24, 3, C.woodDark)}
      {R(150, -112, 46, 26, C.paper)}
      {R(150, -112, 46, 3, C.steel)}
      {R(155, -104, 12, 12, C.cobalt)}
      {R(171, -104, 20, 3, C.steel)}
      {R(171, -98, 16, 3, C.steel)}
      {R(171, -92, 20, 3, C.steel)}
    </g>
  );
}

function CompaniesArt() {
  const shelf = (y, books) => (
    <g key={y}>
      {R(8, y, 188, 6, C.woodDark)}
      {books.map(([bx, bw, bh, col], i) =>
        R(12 + bx, y - bh, bw, bh, col, `b${y}-${i}`))}
    </g>
  );
  return (
    <g>
      {/* case */}
      {R(0, -196, 204, 196, C.wood)}
      {R(8, -190, 188, 184, C.sandDark)}
      {R(0, -196, 204, 6, C.brassLight)}
      {shelf(-136, [[0, 12, 44, C.teal], [14, 10, 40, C.cobalt],
                    [26, 13, 46, C.brass], [41, 9, 38, C.navy],
                    [52, 12, 44, C.teal], [66, 11, 41, C.wood],
                    [120, 14, 30, C.sandLight], [136, 14, 30, C.paper]])}
      {shelf(-76, [[0, 13, 46, C.cobalt], [15, 11, 42, C.teal],
                   [28, 12, 44, C.navy], [42, 10, 39, C.brass],
                   [54, 13, 45, C.teal]])}
      {shelf(-16, [[0, 12, 42, C.navy], [14, 12, 42, C.cobalt],
                   [28, 12, 42, C.teal], [42, 12, 42, C.brass],
                   [120, 40, 14, C.wood]])}
      {/* pinned report */}
      {R(96, -118, 46, 60, C.paper)}
      {R(102, -110, 34, 3, C.steel)}
      {R(102, -102, 26, 3, C.steel)}
      {R(102, -94, 30, 3, C.cobalt)}
      {R(102, -86, 22, 3, C.steel)}
      {R(102, -78, 28, 3, C.steel)}
      {/* bull + plant on top */}
      {R(40, -212, 30, 10, C.brass)}
      {R(44, -220, 10, 8, C.brass)}
      {R(64, -218, 8, 6, C.brass)}
      {R(150, -216, 20, 20, C.wood)}
      {R(156, -238, 6, 22, C.leafDark)}
      {R(146, -234, 12, 6, C.leaf)}
      {R(160, -242, 14, 7, C.leaf)}
    </g>
  );
}

function FundsArt() {
  return (
    <g>
      {/* vault body */}
      {R(0, -186, 132, 186, C.cobalt)}
      {R(0, -186, 132, 5, C.cobaltLight)}
      {R(8, -178, 116, 170, C.navy)}
      {R(14, -172, 104, 158, C.cobalt)}
      {/* dial */}
      {R(48, -110, 36, 36, C.steel)}
      {R(54, -104, 24, 24, C.navy)}
      {R(62, -96, 8, 8, C.steel)}
      {R(64, -118, 4, 10, C.steel)}
      {R(64, -78, 4, 10, C.steel)}
      {R(38, -94, 10, 4, C.steel)}
      {R(84, -94, 10, 4, C.steel)}
      {/* handle + hinges */}
      {R(102, -104, 8, 24, C.brass)}
      {R(122, -150, 8, 16, C.steel)}
      {R(122, -70, 8, 16, C.steel)}
      {/* monitor on top */}
      {R(28, -226, 76, 40, C.navy)}
      {R(34, -220, 64, 28, C.tealBright)}
      {R(40, -212, 12, 12, C.paper)}
      {R(56, -212, 34, 4, C.navy)}
      {R(56, -204, 26, 4, C.navy)}
      {/* keypad tower */}
      {R(136, -122, 44, 122, C.navy)}
      {R(142, -116, 32, 34, C.cobalt)}
      {R(152, -108, 12, 16, C.brassLight)}
      {[0, 1, 2].map((r) => [0, 1, 2].map((c2) =>
        R(146 + c2 * 10, -74 + r * 10, 6, 6, C.steel, `k${r}-${c2}`)))}
      {R(142, -38, 32, 4, C.steel)}
      {/* plant */}
      {R(108, -206, 18, 20, C.wood)}
      {R(114, -226, 6, 20, C.leafDark)}
      {R(104, -222, 12, 6, C.leaf)}
      {R(118, -230, 12, 6, C.leaf)}
    </g>
  );
}

function NotesArt() {
  return (
    <g>
      {/* desk */}
      {R(0, -96, 210, 12, C.wood)}
      {R(0, -96, 210, 3, C.brassLight)}
      {R(6, -84, 10, 84, C.woodDark)}
      {R(194, -84, 10, 84, C.woodDark)}
      {R(120, -84, 84, 84, C.sand)}
      {R(128, -70, 68, 22, C.sandDark)}
      {R(154, -62, 16, 5, C.woodDark)}
      {R(128, -40, 68, 22, C.sandDark)}
      {R(154, -32, 16, 5, C.woodDark)}
      {/* lamp */}
      {R(14, -104, 26, 8, C.brass)}
      {R(24, -150, 6, 46, C.brass)}
      {R(10, -172, 40, 10, C.brassLight)}
      {R(16, -162, 28, 12, C.brass)}
      {/* open document */}
      {R(64, -132, 60, 36, C.paper)}
      {R(70, -126, 40, 3, C.steel)}
      {R(70, -120, 46, 3, C.steel)}
      {R(70, -114, 34, 3, C.steel)}
      {R(70, -108, 42, 3, C.steel)}
      {R(70, -102, 28, 3, C.steel)}
      {/* pen pot */}
      {R(150, -122, 20, 26, C.teal)}
      {R(154, -136, 4, 16, C.brass)}
      {R(160, -140, 4, 20, C.cobalt)}
      {R(166, -134, 4, 14, C.navy)}
      {/* chair */}
      {R(58, -74, 40, 8, C.teal)}
      {R(74, -66, 8, 40, C.steel)}
      {R(60, -26, 36, 6, C.steel)}
      {R(56, -110, 8, 36, C.teal)}
      {R(56, -110, 44, 8, C.teal)}
    </g>
  );
}

function ResearchArt() {
  return (
    <g>
      {/* teal desk */}
      {R(0, -92, 190, 12, C.teal)}
      {R(0, -92, 190, 3, C.tealPale)}
      {R(8, -80, 10, 80, "#245A56")}
      {R(172, -80, 10, 80, "#245A56")}
      {/* monitor */}
      {R(40, -186, 116, 78, C.navy)}
      {R(46, -180, 104, 62, "#12403E")}
      {[0, 1, 2, 3, 4].map((i) => (
        <g key={i}>
          {R(52, -172 + i * 11, 6, 4, C.tealBright)}
          {R(62, -172 + i * 11, 30 + (i % 3) * 16, 4, C.tealPale)}
        </g>
      ))}
      {R(88, -108, 20, 16, C.navy)}
      {R(72, -96, 52, 6, C.navy)}
      {/* keyboard */}
      {R(52, -102, 76, 10, C.steel)}
      {R(56, -100, 68, 5, "#6E8492")}
      {/* plant */}
      {R(4, -114, 18, 22, C.wood)}
      {R(10, -134, 6, 22, C.leafDark)}
      {R(0, -130, 12, 6, C.leaf)}
      {R(14, -138, 12, 6, C.leaf)}
      {/* chair */}
      {R(96, -70, 42, 8, C.teal)}
      {R(114, -62, 8, 38, C.steel)}
      {R(100, -24, 36, 6, C.steel)}
      {R(132, -108, 8, 38, C.teal)}
      {/* binder cabinet */}
      {R(196, -104, 62, 104, C.teal)}
      {R(196, -104, 62, 4, C.tealPale)}
      {R(202, -96, 50, 44, "#245A56")}
      {[0, 1, 2, 3].map((i) =>
        R(206 + i * 12, -92 + 4, 8, 32, [C.paper, C.brass, C.cobalt, C.sandLight][i], `f${i}`))}
      {R(202, -46, 50, 38, "#245A56")}
      {R(218, -30, 18, 5, C.steel)}
    </g>
  );
}

const ART = {
  contacts: { draw: <ContactsArt />, ox: -102, w: 204 },
  companies: { draw: <CompaniesArt />, ox: -102, w: 204 },
  funds: { draw: <FundsArt />, ox: -90, w: 180 },
  notes: { draw: <NotesArt />, ox: -105, w: 210 },
  research: { draw: <ResearchArt />, ox: -110, w: 258 },
};

/* -- wall dressing --------------------------------------------------------- */

function WallArt() {
  const frame = (x, y, w, h, inner) => (
    <g>
      {R(x, y, w, h, C.brass)}
      {R(x + 4, y + 4, w - 8, h - 8, C.paper)}
      {inner}
    </g>
  );
  return (
    <g>
      {/* window */}
      {R(30, 40, 130, 128, C.sandLight)}
      {R(38, 48, 114, 112, "#AFC8DC")}
      {R(38, 120, 114, 40, "#8FB08F")}
      {R(50, 78, 18, 42, "#8FA6C4")}
      {R(76, 62, 22, 58, "#9DB2CC")}
      {R(106, 86, 20, 34, "#8FA6C4")}
      {R(92, 48, 6, 112, C.sandLight)}
      {R(38, 100, 114, 6, C.sandLight)}
      {R(30, 30, 130, 12, C.sand)}
      {/* clock */}
      {R(268, 56, 60, 60, C.brass)}
      {R(274, 62, 48, 48, C.paper)}
      {R(296, 72, 4, 18, C.ink)}
      {R(296, 86, 16, 4, C.ink)}
      {/* charts */}
      {frame(470, 46, 118, 84, <g>
        {R(486, 96, 14, 22, C.cobalt)}
        {R(504, 78, 14, 40, C.tealBright)}
        {R(522, 88, 14, 30, C.brass)}
        {R(540, 66, 14, 52, C.navy)}
        {R(482, 58, 40, 4, C.steel)}
      </g>)}
      {frame(1020, 40, 130, 88, <g>
        {R(1036, 62, 40, 40, C.cobalt)}
        {R(1036, 62, 20, 20, C.tealBright)}
        {R(1086, 62, 48, 6, C.brass)}
        {R(1086, 76, 48, 6, C.steel)}
        {R(1086, 90, 34, 6, C.tealBright)}
      </g>)}
      {frame(1330, 44, 124, 86, <g>
        {R(1346, 108, 92, 4, C.steel)}
        {R(1346, 96, 16, 8, C.tealBright)}
        {R(1366, 84, 16, 20, C.tealBright)}
        {R(1386, 70, 16, 34, C.tealBright)}
        {R(1406, 60, 16, 44, C.tealBright)}
      </g>)}
    </g>
  );
}

/* -- station --------------------------------------------------------------- */

function OfficeStation({ station, active, selected, onSelect }) {
  const art = ART[station.id];
  const half = Math.round(art.w / 2) + 26;
  return (
    <g>
      {/* floor mat — a hint that the station has its own patch of floor, not
          a slab: at full contrast the row of them read as a shelf. */}
      {R(station.x - half, FLOOR_Y + 6, half * 2, 26,
         selected ? C.mat : "#C1A176")}
      {R(station.x - half, FLOOR_Y + 6, half * 2, 2,
         selected ? C.matEdge : "#CBAE85")}
      {/* Two groups on purpose: a CSS transform on an SVG element REPLACES
          its transform attribute, so animating the same node that carries
          the translate would fling the furniture to the top-left corner. The
          outer group places it; the inner one is free to shake. */}
      <g transform={`translate(${station.x + art.ox} ${FLOOR_Y})`}>
        <g className={active ? "px-station-active" : undefined}>
          {art.draw}
        </g>
      </g>
      {/* brass plaque — the button */}
      <g transform={`translate(${station.x - 84} ${PLAQUE_Y})`}
         className="px-plaque" role="button" tabIndex={0}
         aria-label={`${station.label} station — show its clean-up items`}
         aria-pressed={selected}
         onClick={() => onSelect(station.id)}
         onKeyDown={(e) => {
           if (e.key === "Enter" || e.key === " ") {
             e.preventDefault();
             onSelect(station.id);
           }
         }}>
        <rect x="0" y="0" width="168" height="34" rx="2"
              fill={selected ? C.brassLight : C.brass} />
        <rect x="0" y="0" width="168" height="3" fill={C.brassLight} />
        <rect x="4" y="4" width="160" height="26" rx="1" fill="none"
              stroke={C.woodDark} strokeWidth="2" />
        {R(10, 13, 6, 6, C.woodDark)}
        {R(152, 13, 6, 6, C.woodDark)}
        <text x="84" y="23" textAnchor="middle" fill={C.ink}
              style={{ font: "600 15px var(--mono)", letterSpacing: "1.6px" }}>
          {station.label}
        </text>
      </g>
    </g>
  );
}

/* -- mascot ---------------------------------------------------------------- */

/* One two-frame pair per activity, all drawn on the same grid with the feet
   on the same row (tools/gen_felix_sprites.py), so a swap never makes him
   hop. Idle is a single frame — the CSS bob is his breathing. */
const FRAMES = {
  walk: ["felix-walk-a", "felix-walk-b", ".34s"],
  fix: ["felix-fix-a", "felix-fix-b", ".52s"],
  type: ["felix-type-a", "felix-type-b", ".22s"],
};

function FelixMascot({ scene, x }) {
  const walking = scene.activity === "walk";
  const pair = FRAMES[scene.activity];
  return (
    <div className={"px-felix" + (scene.power ? " powered" : "")}
      style={{ transform: `translate3d(${Math.round(x)}px, 0, 0)` }}>
      <div className={"px-felix-body" + (walking ? " walking" : "")}>
        {pair ? (
          <>
            <div className="px-frame"
                 style={{ animation: `px-swapA ${pair[2]} steps(1) infinite` }}>
              <Mascot state={pair[0]} width={MASCOT_H} />
            </div>
            <div className="px-frame"
                 style={{ animation: `px-swapB ${pair[2]} steps(1) infinite` }}>
              <Mascot state={pair[1]} width={MASCOT_H} />
            </div>
          </>
        ) : (
          <Mascot state="felix-idle" width={MASCOT_H} />
        )}
      </div>
      {scene.labels.map((l, i) => (
        <div key={l.id} className="px-bubble"
          onAnimationEnd={() => fx.dropLabel(l.id)}
          style={{ bottom: MASCOT_H + 8 + i * 30,
                   color: l.tone === "positive" ? "var(--teal-700)"
                     : l.tone === "caution" ? "var(--caution-600)"
                     : "var(--ink-700)" }}>
          {l.text}
          <span className="px-bubble-tail" />
        </div>
      ))}
    </div>
  );
}

/* -- HUD ------------------------------------------------------------------- */

function StatusConsole({ scene }) {
  return (
    <div className="px-console">
      <span className={"px-led" + (scene.power ? " on" : "")} />
      <span className="px-console-text">
        {scene.caption.toUpperCase()}
        {scene.power ? " · POWERED UP" : ""}
      </span>
    </div>
  );
}

const HUD_ICON = {
  wrench: <><rect x="2" y="6" width="6" height="2" fill="#8FA6B5"
                  transform="rotate(-45 5 7)" />
            <rect x="6" y="1" width="3" height="3" fill="#8FA6B5" />
            <rect x="7" y="2" width="2" height="1" fill="#F7F3EA" /></>,
  merge: <><rect x="1" y="2" width="3" height="3" fill="#2F5D8A" />
           <rect x="6" y="2" width="3" height="3" fill="#B0894E" />
           <rect x="2" y="6" width="6" height="2" fill="#249692" /></>,
  fill: <><rect x="4" y="1" width="2" height="2" fill="#2F5D8A" />
          <rect x="3" y="3" width="4" height="4" fill="#2F5D8A" />
          <rect x="2" y="5" width="6" height="3" fill="#1C2E44" /></>,
  link: <><rect x="1" y="4" width="4" height="2" fill="#249692" />
          <rect x="5" y="4" width="4" height="2" fill="#2F5D8A" />
          <rect x="4" y="3" width="2" height="4" fill="#1C2430" /></>,
  flag: <><rect x="2" y="1" width="1" height="8" fill="#1C2430" />
          <rect x="3" y="1" width="5" height="3" fill="#D97706" /></>,
  undo: <><rect x="1" y="4" width="3" height="2" fill="#8C4038" />
          <rect x="4" y="3" width="2" height="4" fill="#8C4038" />
          <rect x="6" y="2" width="2" height="6" fill="#8C4038" /></>,
};

function CleanupHud({ stats }) {
  const items = [
    ["wrench", stats?.applied_total, "fixes applied"],
    ["merge", stats?.by_type?.merge, "duplicates merged"],
    ["fill", stats?.by_type?.fill_missing, "fields filled"],
    ["link", stats?.by_type?.fix_relation, "relations repaired"],
    ["flag", stats?.recommendations, "flagged for review"],
    ["undo", stats?.undone, "undone"],
  ];
  return (
    <div className="px-hud">
      <span className="px-hud-title">CLEANED UP SINCE THE START</span>
      <div className="px-hud-counts">
        {items.map(([k, v, label]) => (
          <span key={k} className="px-hud-item" title={label}>
            <svg viewBox="0 0 10 10" width="20" shapeRendering="crispEdges"
                 aria-hidden="true">{HUD_ICON[k]}</svg>
            <b>{(v ?? 0).toLocaleString()}</b>
            <span className="px-sr">{label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/* -- the scene ------------------------------------------------------------- */

export default function PixelOfficeScene({ scene, stats, onSelect }) {
  const wrapRef = React.useRef(null);
  const [scale, setScale] = React.useState(1);

  // One scale factor for the whole scene: furniture, plaques and Felix grow
  // and shrink together, so nothing can ever collide at an awkward width.
  React.useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width;
      setScale(Math.min(1, Math.max(0.34, w / SCENE_W)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const station = STATION_BY_ID[scene.zone] || STATIONS[0];
  // Felix stands to the right of whatever he is working on, clear of the art.
  const felixX = Math.round(station.x + (ART[station.id].w / 2) + 18);

  return (
    <div className="px-office" ref={wrapRef}
         style={{ height: Math.round(SCENE_H * scale) }}>
      <div className="px-stage"
           style={{ width: SCENE_W, height: SCENE_H,
                    transform: `scale(${scale})` }}>
        <svg viewBox={`0 0 ${SCENE_W} ${SCENE_H}`} width={SCENE_W} height={SCENE_H}
             shapeRendering="crispEdges" className="px-svg" aria-hidden="true">
          {/* Wall. The light from the window falls off in a stepped wedge —
              flat bands with hard edges read as three different rooms. */}
          {R(0, 0, SCENE_W, FLOOR_Y, C.wall)}
          {[[0, 300, C.wallLit], [300, 170, "#F4EDDF"], [470, 130, "#F2EADB"]]
            .map(([x, w, fill]) => R(x, 0, w, FLOOR_Y, fill, `lit${x}`))}
          <WallArt />
          {/* floor */}
          {R(0, FLOOR_Y - 12, SCENE_W, 12, C.skirt)}
          {R(0, FLOOR_Y - 12, SCENE_W, 2, "#C0966A")}
          {R(0, FLOOR_Y, SCENE_W, SCENE_H - FLOOR_Y, C.floor)}
          {Array.from({ length: 14 }, (_, i) =>
            R(i * 116, FLOOR_Y, 3, SCENE_H - FLOOR_Y, C.board, `p${i}`))}
          {[18, 52, 96].map((y) =>
            R(0, FLOOR_Y + y, SCENE_W, 2, C.board, `g${y}`))}
          {R(0, SCENE_H - 22, SCENE_W, 3, C.floorDark)}
          {STATIONS.map((st) => (
            <OfficeStation key={st.id} station={st}
              active={(scene.activity === "fix" || scene.activity === "type")
                      && scene.zone === st.id}
              selected={scene.selected === st.id}
              onSelect={onSelect} />
          ))}
        </svg>

        {/* Real buttons over the plaques: the SVG carries the look, these
            carry the semantics, the focus ring and the keyboard. */}
        {STATIONS.map((st) => (
          <button key={st.id} className="px-hit"
            aria-pressed={scene.selected === st.id}
            onClick={() => onSelect(st.id)}
            style={{ left: st.x - 84, top: PLAQUE_Y, width: 168, height: 34 }}>
            <span className="px-sr">
              {st.label} — show its clean-up items
            </span>
          </button>
        ))}

        {scene.power && scene.powerBanner > 0 && (
          <div key={scene.powerBanner} className="px-powerup">POWER UP</div>
        )}
        <FelixMascot scene={scene} x={felixX} />
      </div>
    </div>
  );
}

/* The narrow fallback: no room for a cinematic room, so the stations become a
   plain row of buttons and Felix takes a bow. */
export function StationStrip({ scene, onSelect }) {
  return (
    <div className="px-strip">
      {STATIONS.map((st) => (
        <button key={st.id} onClick={() => onSelect(st.id)}
          aria-pressed={scene.selected === st.id}
          className={"px-strip-btn" + (scene.selected === st.id ? " on" : "")}>
          {st.label}
        </button>
      ))}
    </div>
  );
}

export { StatusConsole, CleanupHud, OfficeStation, FelixMascot };

/* ---------------------------------------------------------------------------
   THE SPRITE

   Felix's seven frames — idle, walk-a/b, fix-a/b, type-a/b — are drawn by
   tools/gen_felix_sprites.py onto a shared 36x44 grid and written out as SVG.
   The body is defined once and only the limbs vary per frame, so his head and
   feet cannot drift between frames; edit the poses there and re-run it rather
   than hand-editing the SVGs.

   The original mascot-felix-hero / mascot-felix-strike pair is left in place:
   the splash still uses it.
--------------------------------------------------------------------------- */
