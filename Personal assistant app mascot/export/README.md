# Assistant mascot — animated SVG set

14 states, each a self-contained animated SVG (CSS keyframes inside the file).
Transparent background, 240x240 viewBox, scales to any size.

## Files
- `svg/mascot-working.svg` — Working
- `svg/mascot-crunching.svg` — Crunching (sweating)
- `svg/mascot-notes.svg` — Taking notes
- `svg/mascot-thinking.svg` — Thinking
- `svg/mascot-reading.svg` — Researching
- `svg/mascot-call.svg` — On a call
- `svg/mascot-presenting.svg` — Presenting
- `svg/mascot-filing.svg` — Filing
- `svg/mascot-waving.svg` — Greeting
- `svg/mascot-celebrating.svg` — Task complete
- `svg/mascot-confused.svg` — Not sure / empty
- `svg/mascot-coffee.svg` — Resting
- `svg/mascot-sleeping.svg` — Sleeping / offline
- `svg/mascot-avatar.svg` — Avatar

## Using them

**Static-ish (animation still runs):** an `<img>` tag does NOT run the CSS
animation in most browsers. Use one of these instead.

Inline in React — animation works:
```jsx
import { ReactComponent as MascotWorking } from './mascot/mascot-working.svg'; // CRA / svgr
<MascotWorking style={{ width: 160 }} />
```

Vite:
```jsx
import MascotWorking from './mascot/mascot-working.svg?react'; // vite-plugin-svgr
```

Plain HTML — object tag keeps the animation:
```html
<object data="mascot/mascot-working.svg" type="image/svg+xml" width="160"></object>
```

Or paste the file contents straight into your JSX.

## Suggested state mapping
| App state | Asset |
| --- | --- |
| assistant is running a task | mascot-working |
| long / heavy task, retries | mascot-crunching |
| capturing notes, summarising | mascot-notes |
| reasoning, planning | mascot-thinking |
| searching, reading sources | mascot-reading |
| voice / phone integration | mascot-call |
| showing a report or chart | mascot-presenting |
| organising files, bulk actions | mascot-filing |
| onboarding, first launch | mascot-waving |
| task finished | mascot-celebrating |
| no results, error | mascot-confused |
| idle, nothing queued | mascot-coffee |
| offline, do-not-disturb | mascot-sleeping |
| profile / header avatar | mascot-avatar |

Colours: jacket #4E7A9B / #41688A, ink #1C2430, accent teal #249692, brass #B0894E, skin #F3CBA8.
