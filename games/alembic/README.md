# Alembic & Ash

A potion-brewing game. One self-contained HTML file, no build step and no
dependencies — open `index.html` in a browser, or serve the folder:

```bash
npx http-server games/alembic -p 8899
```

Progress saves to `localStorage`. "Start over" lives at the bottom of the
in-game **Rules** panel.

> Unrelated to the Weybourne app — it shares the repo, nothing else. Nothing
> here is imported by `src/`, `api/` or `web/`.

## The mechanic

Every potion is scored on three independent axes, so there are three different
ways to ruin one.

**Balance** — each ingredient carries four essences (Ember, Tide, Verdant,
Umbra). A formula wants them in a *ratio*, not in absolute amounts, so the
score is the cosine similarity between the brew's essence vector and the
formula's target. Cosine ignores magnitude, which is what makes potency a
genuinely separate axis rather than a restatement of the same thing.

**Potency** — ingredient potencies simply sum. The formula names a target and
scores the absolute miss against it. Two ingredients exist purely to let you
move one axis without the other: Spring Water shifts balance while adding
almost no potency, Crystal Dust adds potency without shifting balance.

**Infusion** — fills only while the pot's temperature sits inside the
formula's band, fastest dead centre. The five fire settings (18/42/62/82/104°)
are deliberately spaced so most formulas have one setting comfortably inside
their band but *none* dead centre — holding the centre means riding between two
settings. Wildfire Charge has no setting inside its band at all; it can only be
brewed by riding the dial, which is why it gates behind standing 32.

Working against all three: **turbulence**, which climbs with the square of
temperature and with how crowded the pot is, and is knocked back by stirring.
Reach 100% and the pot boils over — infusion is lost and the mark stays on the
finished potion.

Two details that came out of playtesting rather than design:

- Time spent heating up doesn't count as drifting off the band. The off-band
  penalty only starts accruing once the pot has reached the band at least
  once, otherwise every brew was docked for its own warm-up.
- Infusion is weighted as heavily as balance (0.38 each, potency 0.24).
  At a lower weight a half-infused potion still graded *Fine*, which made
  patience optional.

## Balancing the economy

Commissions expire, closing shop costs 6 coin, and standing gates the better
formulas. If you ever end a day with no ingredients, no bottles and less than
the cheapest stall price, an old debt pays out 20 coin — the one guard against
an unrecoverable dead state.

## Tuning

All of it is data at the top of the `<script>`: `INGREDIENTS`, `RECIPES`,
`TIERS`, `HEATS`. Changing a band or a target needs no other edits. The scoring
weights sit in `judge()` and the physics in `tick()`.
