# Felix v2 production assets

These masters were generated together from the approved nose-free Felix animation
and four-task mock so the character identity and office palette remain consistent.

- `office-background.png` — uncompressed five-station source plate.
- `felix-sprite-sheet.png` — transparent 6×2 source sheet after chroma removal.
- Shipping assets — optimized office background and twelve aligned frames live in
  `web/public/mascot/felix-v2/`.

Frame order in the master sheet, left to right:

1. Idle, walk A, walk B, repair A, repair B, success.
2. Contacts A/B, Notes A/B, Research A/B.

All extracted frames use an identical 362×362 transparent canvas with their visible
baseline aligned to row 326. Do not trim individual frames: their shared padding is
what prevents animation jumps.

## V3 task actions

The three `felix-*-v3-source.png` masters replace the ambiguous desk and filing
poses. `tools/process_felix_v3.ps1` removes their magenta key, splits each pair,
and writes six aligned 362-by-362 shipping frames:

- Contacts: Felix stands to the right and lowers a contact card into the open drawer.
- Notes: Felix and the wooden chair are one rear three-quarter seated unit.
- Research: Felix sits fully back-facing in the teal rolling chair.

Only Companies and Funds use the furniture-shake effect. Filing and desk work stay
still so the actions read as deliberate rather than destructive.

## V3 8-bit office plate

`office-background-v3-8bit.png` is the shorter scene's current source plate. It
uses coarser pixel clusters, smaller and more widely spaced furniture, and open
Notes/Research desk bays. Their chairs now exist only in Felix's working sprites,
which prevents the double-chair overlap seen in the previous background.

## Cute V4 movement set

`felix-cute-v4-source.png` follows the supplied six-panel character reference:
larger expressive glasses, a rounder head, open smiles and more energetic strides.
`tools/process_felix_cute.ps1` extracts the idle, two reaction, two run and success
frames. The original shocked reaction is retained only as source history and is no
longer loaded by the app.

## Cute V5 complete action set

`felix-cute-work-v5-source.png` redraws Repair, Contacts, Notes and Research in the
same round-headed, smiley, coarse-pixel style as V4 movement. Notes includes one
wooden chair and Research one teal chair; their background stations contain no
second chair. `felix-cute-notice-v5-source.png` is the calmer, ready-to-run pose
with one small exclamation mark and no shocked expression.

`tools/process_felix_v5.ps1` removes the magenta key and writes ten aligned
362-by-362 runtime frames. The notice beat occurs only sometimes before travel,
and powered runs skip it, so it adds character without delaying every move.

## 8-bit V7 production set

`felix-8bit-v7-movement-source.png` and `felix-8bit-v7-work-source.png`
translate the approved Felix concept into a coarser late-1980s console style:
larger pixel clusters, hard stair-step contours, a reduced palette, and no soft
shading. The pose order remains compatible with the V4/V5 production sheets.

`tools/process_felix_8bit_v7.ps1` removes the magenta key and writes fourteen
versioned, baseline-aligned 362-by-362 runtime frames. The previous cute sprites
remain in the shipping directory as a non-destructive fallback.
