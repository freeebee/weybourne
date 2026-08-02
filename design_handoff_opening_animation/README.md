# Handoff: Weybourne FI assistant — opening animation

## Overview
A ~4.8 second launch animation for the Weybourne FI assistant app. The five strokes of the
Weybourne mark fly in from off-screen top-left, assemble into the logo, shrink with a single
clean 360° rotation, the "Weybourne" wordmark wipes in under it with a brass hairline and an
`FI ASSISTANT` eyebrow, the assistant mascot ("Wey") rises in and waves, and the whole splash
dissolves to reveal the app underneath.

## About the design files
The files in this bundle are **design references authored in HTML/CSS** — a prototype of the
intended look and timing, not production code to drop in verbatim. Recreate it in the target
codebase using its existing framework and conventions. `splash.css` and `WeybourneSplash.jsx`
are written to be adaptable directly if the app is React + plain CSS; translate them if not.

## Fidelity
**High fidelity.** Colours, type, geometry and the full motion timeline are final. Match them.

## Files in this bundle
| File | What it is |
| --- | --- |
| `splash.css` | The complete timeline as plain CSS. Single source of truth for all timings. |
| `WeybourneSplash.jsx` | React reference component that wraps your app shell and self-dismisses. |
| `assets/mascot-waving.svg` | Mascot, greeting pose. Used on the splash. |
| `assets/mascot-avatar.svg` | Mascot, avatar bust. Used in the app's ask bar afterwards. |
| `Weybourne FI Opening.dc.html` | The original prototype (design tool format, for visual reference). |

> Both SVGs in this bundle have had their missing `@keyframes` (`m-bob`, `m-wave`, `m-tilt`)
> embedded — the versions in the original mascot export reference those animations but never
> define them, so they render static. If you re-export the mascots, re-add the keyframes (they
> are also at the bottom of `splash.css`).

## Structure
```
.wb-splash-root                 full-viewport, background #0F2E42, overflow hidden
├── .wb-app                     your real app shell, revealed at the end
└── .wb-veil                    absolutely positioned cover, grid place-items:center
    ├── .wb-veil-glow           radial teal glow, pointer-events none
    └── .wb-lockup              column, centred, gap 34px
        ├── .wb-mark-slot       fixed 168px tall so the mark's scale-down reserves space
        │   └── .wb-mark        flex row, gap 8px — five .wb-stroke children
        ├── .wb-text            column, gap 18px, margin-top -18px
        │   ├── .wb-wordmark    "Weybourne"
        │   ├── .wb-rule        brass hairline, 320 x 1
        │   └── .wb-eyebrow     "FI ASSISTANT"
        └── .wb-mascot-block    column, gap 4px
            ├── svg.wb-mascot   mascot-waving, 176 x 147
            └── .wb-greeting    greeting line
```

## The mark
Five parallelograms, **not** an image: each is a `46 x 158px` div with `transform: skewX(22deg)`
and its own vertical gradient, `8px` apart. The 22° skew is the mark's signature lean and must
survive every transform — it is baked into the `wb-fly` keyframes, so any transform you add to
a stroke must re-append `skewX(22deg)`.

Stroke gradients (top → bottom), left to right:
1. `#2FAFA6 → #249692`  2. `#23928F → #1F8087`  3. `#1F7F84 → #1C6B78`
4. `#1B6C77 → #195A6C`  5. `#1A576D → #184564`

## Timeline (at `--wb-speed: 1`)
| t | Element | Animation | Duration / easing |
| --- | --- | --- | --- |
| 0.08–0.48s | five strokes, 100ms stagger | `wb-fly`: from `translate3d(-46vw…-38vw, -40vh…-48vh)` `rotate(-26°…-10°)` `scale(1.15)`, opacity 0 → resting | 700ms `cubic-bezier(.16,.84,.28,1)` |
| 1.16s | `.wb-mark` | `wb-settle`: `scale(1)→scale(.46)` + `rotate(0→360deg)` | 760ms `cubic-bezier(.45,0,.15,1)` |
| 1.70s | `.wb-wordmark` | `wb-wipe`: `clip-path` inset 100%→0 from the left, letter-spacing .14em→-.01em | 720ms `cubic-bezier(.2,.7,.2,1)` |
| 2.02s | `.wb-rule` | `wb-rule`: `scaleX(0→1)` from centre | 620ms same |
| 2.22s | `.wb-eyebrow` | `wb-rise`: opacity + 8px up | 560ms same |
| 2.48s | `.wb-mascot` | `wb-rise` | 700ms same |
| 2.76s | `.wb-greeting` | `wb-rise` | 620ms same |
| 4.00s | `.wb-veil` | `wb-veil`: opacity 1→0, then `visibility: hidden` | 620ms `cubic-bezier(.4,0,.2,1)` |
| 4.10s | `.wb-app` | `wb-app`: opacity 0→1, `translateY(14px)` + `scale(.995)` → none | 700ms `cubic-bezier(.2,.7,.2,1)` |
| ~4.80s | — | animation complete; `onDone()` fires | — |

Looping, inside the mascot SVG only: `m-bob` 2.6s (head, ±3.5px), `m-wave` 0.7s (raised arm,
−16°→12°, `transform-origin: 10% 100%`, `transform-box: fill-box`), `m-tilt` 5s (avatar head, ±2°).

Every delay and duration is multiplied by `--wb-speed`, so one variable retimes the whole thing.

## Behaviour & integration
- Mount the splash **over** the app; the app is a child (`.wb-app`), not a sibling — that is what
  lets it fade up underneath the dissolving veil.
- The splash is pure CSS. Nothing re-renders during playback; React only needs the completion timer.
- `onDone` fires at `4800ms x speed`. Use it to unmount the splash / flip a `booted` flag.
- The reference component gates on `sessionStorage['wb-splash-seen']` so it plays once per session.
  Delete that block if the animation should play on every load; move it to `localStorage` for once-per-device.
- `prefers-reduced-motion: reduce` collapses all durations and delays to ~0 so the app appears
  immediately. Keep this.
- The prototype also has a REPLAY control — that is a design-review affordance, **not** part of the
  product. Do not ship it.
- After the splash, `mascot-avatar.svg` appears at 34px in the assistant's ask bar (viewBox
  `60 40 130 140`, head and shoulders, circular `#EFE8DA` backing). Reuse it for the assistant
  avatar anywhere in the app.

## Design tokens
| Token | Value | Use |
| --- | --- | --- |
| Ink / navy | `#0F2E42` | splash background, app sidebar |
| Teal (accent) | `#249692` | lightest mark stroke, active states, links |
| Navy (mark base) | `#184564` | darkest mark stroke |
| Paper | `#F7F3EA` | app canvas, wordmark colour on ink |
| Paper (raised) | `#FCFAF5` / `#FFFFFF` | cards, ask bar |
| Hairline | `#E2DACB` | card borders |
| Brass | `#B0894E` | the divider rule only — tertiary, never a fill |
| Muted text | `#7A6E5E`, `rgba(247,243,234,.66–.72)` on ink | labels, eyebrows |
| Radii | 3px (controls) / 4px (cards) / 6px (app shell) | near-square by house rule |
| Easing | `cubic-bezier(.2,.7,.2,1)` standard, `cubic-bezier(.4,0,.2,1)` exits | no bounce, no spring |

## Type
- **Newsreader** 300 — wordmark (64px/1, `-.02em`) and app headings.
- **Hanken Grotesk** — UI text, greeting (13.5px).
- **IBM Plex Mono** — eyebrows (12px, `.34em` tracking, uppercase) and all figures.
All three are Google Fonts; load the weights you use, or swap for the licensed equivalents if
the codebase already has them.

## Copy
- Wordmark: `Weybourne` · Eyebrow: `FI ASSISTANT` · Greeting: `CHAO at your service`
- Sentence case everywhere else; mono eyebrows uppercase. Never emoji.

## Assets
Both mascot SVGs come from the existing 14-pose mascot set (`mascot-waving`, `mascot-avatar`);
240x240 viewBox, transparent, no external dependencies. Jacket `#4E7A9B`/`#41688A`, ink `#1C2430`,
skin `#F3CBA8`, accent teal `#249692`. If the app already ships that set, point at those files
instead of these copies — just make sure the keyframes are defined.
