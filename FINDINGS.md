# Ground Truth from `kaggriculture.py`

Verified by reading the installed env source
(`.venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py`).
Where this contradicts `README.md`/`AGENTS.md`, **this file wins** — the docs are
wrong in several places.

## Doc errors

| Doc claim | Actual (source) |
|---|---|
| Tomato "Time to Max Yield 11 days" | `max_yield_day = 8`. Yields at ages 8,9,10,11 via `interval=1`, `max_yield=4`. |
| Melon "Time to Max Yield 10 days" | `max_yield_day = 12` (`first_yield_day=10`). Bonus window is ages 6–12; cap of 6 reached at age 10. |
| "`starter` is a deterministic baseline" | It is a **carrot loop on a single tile**. Never moves, never hires, never buys land. Uses 1 of 25 tiles all season. |

## Mechanics the docs omit or bury

1. **`SELL` reads the shed only** (`_commit_unit`). `HARVEST` puts produce in the
   *unit's inventory*. Inventory reaches the shed only via `DROP`/`PLACE` (shed-adjacent)
   or the end-of-day auto-drop. So harvest → sale has a lag unless you walk to the shed.

2. **A full shed blocks `BUY_ANIMAL` and `BUY_PRODUCT`.** Both check
   `sum(shed.values()) >= shed_capacity` and fail. Run the shed at 100/100 and you
   cannot buy geese or feed wheat. Always keep headroom.

3. **`FEED` and `FERTILIZE` consume from the *unit's inventory*, not the shed.**
   A hand must `PICKUP WHEAT n` at the shed before it can feed animals in the field.

4. **An unfed (but alive) animal still produces its base 1 unit.**
   In `_daily_refresh_animals`, `base = 1` is added whenever the production interval
   fires. Only the *care bonus* requires `fed_today`. Feeding every *other* day keeps
   `consecutive_unfed < 2` (alive) and still yields 1 product/day from a goose.

5. **`fertilizer_available = True` is set for every surviving animal every day**,
   fed or not, cared or not. `COLLECT_FERTILIZER` is free money — 1 action/animal/day.

6. **A fed+cared goose yields exactly 2/day.** Goose `interval=1`, so the care bank
   is spent every day and can never accumulate past 1. Capped by `max_held = 4`.

7. **Watering bonus window is `(max_yield_day + 1) // 2 .. max_yield_day`**, and the
   bonus only applies to *one-time* crops. Fertilizer doubles it (+2/day).

8. **Plants start at `consecutive_unwatered = 1`**, so the planting day *must* be
   watered. Afterwards, alternate-day watering is enough to survive — full daily
   watering is only needed inside the bonus window.

9. **Atomic PLANT validation**: if total `PLANT` requests for a crop in one turn exceed
   seeds held, **all** of them are dropped (not just the excess).

10. **`BUY_LAND` takes no argument.** Fixed order NE→SW→SE at $1000/$2000/$4000.

11. **Market order slots are capped, not quantities.** `q[:max_orders]` truncates to 10
    *orders*; a single `["SELL","WHEAT",500]` is one slot. Selling is never
    throughput-limited — only price-limited.

12. **Selling at the $1 floor does not add to market inventory**, so the floor is
    permanent for that resource until the town drains it back down.

13. **Hire spawns immediately** during market processing, but market runs *after* unit
    actions, so a hand hired on turn `t` first acts on turn `t+1`.

## Derived economics (integrating the real price curve)

Cumulative revenue selling N units into a fresh market, alone:

| Resource | Price hits $1 at | Rev @100u | Season ceiling |
|---|---|---|---|
| Egg | ~never (`log`) | $4.7k | ~$24k @ 600u |
| Melon | 158 units | **$21.7k** | ~$26.5k |
| Fertilizer | 495 units | $9.0k | ~$25k @ 300u |
| Wheat | ~never (`log`) | $2.2k | ~$12k @ 600u |
| Wool | 59 units | — | $7.9k |
| Milk | 76 units | — | $6.2k |
| Carrot | 866 units | $2.7k | $8.4k |
| Tomato | 537 units | $4.3k | ~$6k |
| Strawberry | 62 units | — | $3.8k |

- **Wheat and egg never glut** (log curve) — they are the volume resources.
- **Carrot is a trap at scale**: 100 tiles of carrot produce ~2100 units, far past its
  866-unit floor. Wheat at 2400 units still fetches ~$18.
- **Melon is a burst**: first 100 units are worth $21.7k, unit 158+ is worth $1
  permanently (no shop demands melon — only the town center drains it).
- **Hiring is drastically underpriced**: 10 hands = $143 for 240 extra actions
  ($0.60/action) against $13–45/action of value. Hire to the limit of *useful work*.

## Measured results (5 full episodes vs `starter` unless noted)

| Build | Mean | Note |
|---|---|---|
| v1 wheat loop (baseline) | 3,371 | loses to starter 0/5 |
| v2 engine, global nearest-unit dispatch | 6,689 | 77% of actions were movement |
| v2 + territory dispatch | 17,634 | strips cut thrash; 99/100 tiles planted |
| v2 + melon allocation | 60,569 | **melon is the dominant lever** |
| v2 + geese (unscoped logistics) | 21,660 | regression -- whole crew stampeded to shed |
| v2 + geese (scoped to owning unit) | 49,703 | still worse than no geese |
| **v2 tuned, geese off** | **~62,000** | 5/5 wins, `starter` ~3,500 |

Episode runtime ~3.4s, so iteration is cheap. Variance is small (sd 100-1000 at the
tuned config), so real improvements are unambiguous at 5 episodes.

Agent latency: mean 0.14 ms/call, max 0.64 ms, against the 1000 ms `actTimeout`.
Whole-episode agent time 0.10 s against the 1200 s `runTimeout`. Not a constraint.

### Why geese lose

Measured, not assumed. A melon tile returns roughly $150 per unit-action; a goose
returns roughly $25. Animal chores (FEED / CARE / HARVEST / COLLECT_FERTILIZER plus
the shed round-trip for feed) burned 998 actions -- 14.5% of the season -- and the
$300/bird capital starved melon seed and land purchases exactly when they compound.
Tile usage fell from ~99 to 42-74 and melon price barely moved, meaning the melon
market was left unexploited.

Swept `GOOSE_CAP` x `MELON_CAP`: geese lose at *every* melon level. They also lose
under a contested melon market (31,070 with geese vs 44,785 without, head to head).
The husbandry code is retained behind `KAG_GOOSE_CAP=0` because the trade could flip
with cheaper feed logistics (a dedicated ranch abutting the shed was never tried).

### Melon density is a real optimum

`MELON_DIV` (tiles per melon plot) swept at fixed crew:

| tiles/melon | melon tiles | mean |
|---|---|---|
| 2 | ~50 | 53,635 |
| **3** | **~33** | **61,145** |
| 4 | ~25 | 53,394 |

Denser crashes the price past its quadratic glut curve; sparser leaves the market
unexploited. Crew size (`HAND_CAP` 12 -> 20) moves the result under 1.5%, inside noise.

## Competitive findings (head-to-head, `h2h.py`)

Leaderboard rating comes from winning episodes, not absolute money, so these were
settled by playing parameter settings against each other with seats swapped -- not by
scoring against `starter`.

| Question | Result |
|---|---|
| Back off melon when the rival grows it? | **No** -- backing off loses 0/4 |
| Melon density under contention | **33 tiles wins 4/4** over 50 tiles |
| Plant melon from day 0 instead of day 2? | Wash (2/4), keep day 2 |
| Melon price guard at $90 | Inert -- never fires, kept as a safety valve |
| Staple crop: carrot instead of wheat? | **No** -- 24,302 vs wheat's 61,151 |
| Unload threshold | 10 optimal; 18+ collapses to ~43,000 |

Two of these are worth remembering because they are counterintuitive:

- **Melon is a race, not a commons to be managed.** Both farms are public, so a rival's
  melon acreage is visible on day 2. Backing off raises *both* scores -- a cooperative
  equilibrium -- but loses head-to-head, because conceding acreage hands the
  profitable stretch of the curve to the opponent. We race instead.
- **Carrot loses on capital, not price.** Its price genuinely is better on the volume
  we produce (staple output stays far under the 866-unit floor), but $20/seed on a
  shorter cycle burns ~2x the cash per tile-day and starves melon seed and land
  exactly when they compound. Unit economics lost to cash-flow timing.

Higher unload thresholds collapse the score because the end-of-day drop overflows the
100-item shed and the excess is **discarded**, not held over.

## The opening melon race (learned from a ranked loss)

Melon cannot be harvested before age 10 however well it is tended, so **the first
melon wave is winner-take-all**. The first farm to plant reaches an uncrashed curve
(~$278/unit, ~$22k for one 24-tile harvest); the second gets $25, then $1. No town
shop demands melon, so the price never recovers.

Opening fraction of tiles committed to melon (`KAG_MELON_OPENING_FRAC`), head-to-head:

| Matchup | Result |
|---|---|
| 0.3 vs 0.0 (no push) | **0.3 wins 4/4** — 29,030 vs 20,760 |
| 0.3 vs 0.2 | 0.3 wins 4/4 — 28,748 vs 21,730 |
| 0.3 vs 0.35 | 0.3 wins 4/4 — 26,223 vs 23,695 |
| 0.3 vs 0.5 | 0.3 wins 4/4 — 42,288 vs **15,080** (0.5 collapses) |
| all-in (1.0) vs 0.0 | all-in **loses** 0/4 |

Sharply peaked, and both extremes fail for opposite reasons: too little arrives ~5
days late to market; too much spends so heavily on seed that land and crew stall for
the eleven days before the first harvest. Note the rival that beat us played all-in —
their strategy was beatable, not optimal.

**`sweep.py` and `h2h.py` disagree here, and `h2h.py` is right.** `starter` never sells
melon, so vs-starter runs reward patient farm-building: the opening push costs ~4%
there (60,601 -> 56,200) while gaining ~40% contested. Rating comes from head-to-head
wins. Decide strategy with `h2h.py`.

## Open risks

1. **The melon market is shared, and this strategy depends on it.** In self-play the
   score falls from ~62,000 to ~28,000 as both players dump melon and crash the price.
   Against `starter` we have the melon market to ourselves; a real leaderboard
   opponent doing the same thing roughly halves the return. This is the single
   biggest unknown going into ranked play.

2. **The 30-day season length is hard-coded** (`SEASON_DAYS`). The observation exposes
   `day`/`hour` but not `episodeSteps`, so the "don't plant what cannot mature" guard
   assumes the documented 720-turn default. On a 200-turn episode the agent loses
   (1,158 vs 3,072) because it commits tiles to melon that never ripen. Harmless at
   the competition default; would need attention if the horizon ever changes.

3. Movement is still ~52% of all actions. Further gains likely live in routing
   (assigning strips by walking cost rather than by column index).
