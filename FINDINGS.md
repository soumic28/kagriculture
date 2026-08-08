# Ground Truth from `kaggriculture.py`

Verified by reading the installed env source
(`.venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py`).
Where this contradicts `README.md`/`AGENTS.md`, **this file wins** — the docs are
wrong in several places.

## CORRECTION: sustainable demand, not dump ceilings

**The revenue-ceiling table further down this file is misleading, and building on it
cost us a day.** It costs each product as a single dump against its glut curve. But
town shops drain market inventory *continuously*, so price recovers, and what governs
income is the **sustainable rate** — how fast the town removes stock.

Shops consume 1 unit per demanded product every 4 turns (6/day); single-product shops
double it. The town centre takes 1 of every non-fertilizer product every 12 turns,
doubling after day 10 and quadrupling after day 20 (so 8/day late).

| Product | Town demand | Base | Sustainable $/day |
|---|---|---|---|
| **Milk** | 26/day | $160 | **$4,160** |
| **Wool** | 20/day | $200 | **$4,000** |
| **Strawberry** | 32/day | $120 | **$3,840** |
| Melon | 8/day | $250 | $2,000 |
| Tomato | 20/day | $60 | $1,200 |
| Egg | 20/day | $50 | $1,000 |
| Wheat | 38/day | $25 | $950 |
| Carrot | 26/day | $35 | $910 |
| **Fertilizer** | **0/day** | $100 | **$0** |

Because the town drains faster than either player sells, these markets **inflate**. In
ranked episode 90318832 strawberry ran 120 → 256, milk 160 → 303 and wool 200 → 245
by day 22. Melon and fertilizer are the exceptions — no shop demands either, so they
only ever fall. **Those were the two products this agent was originally built around.**

The strongest farm observed (199,688) followed the implication exactly: 22 melon tiles
to day 11, dump for ~$22k, then STRAWBERRY:71 COW:13 SHEEP:10 sold into a rising
market. That plan is implemented behind `KAG_PHASED` but is **off** — see below.

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

## Why the phased plan is off

`KAG_PHASED=1` reproduces the 199,688 farm and executes correctly (22 melon tiles,
harvest day 10 for ~$22k, then convert). It still loses:

- 2/6 head-to-head against the diversified build
- self-play collapses to ~11,000 — when **both** farms open all-in on melon they crash
  it together and neither can fund phase two

It is the right play only against a field that leaves melon alone. Ours does not.

Two real bugs were found building it, both fixed: land was bought on **day 0**,
starving the opening seed budget, and the herd plan claimed **23 of the 25 opening
tiles as pens** before any crop was allocated.

## Herd and mix, retuned on sustainable demand

| Setting | Result |
|---|---|
| 0 geese / 8 cows / 6 sheep | **98,977** |
| 0 geese / 8 cows / 10 sheep | 77,852 |
| 4 geese (any other setting) | consistently worse |
| Strawberry-heavy mix (0.28) | 72,450 vs 83,108 for the existing mix |

Geese are gone: egg is the weakest animal market and each bird still costs a daily
feed run. Bigger herds lose to **feed round-trips, not to the price curve** — which is
also why the strawberry-heavy mix underperforms despite strawberry's strong demand.
Strawberry occupies a tile for 17 days, and watering throughput is the binding limit.

**Actions, not tiles, are the constraint.** Movement is ~52% of all actions and PASS
another 9%. Until routing improves, extra livestock and long-cycle crops cannot be
serviced, which is the single biggest thing standing between us and the 100k+ farms.

## The elite build (episode 90338757, Ben Hamilton 115,481 v Winter Lamb 109,426)

Two top-3 agents playing each other. They converge on almost the same farm, steady
from day 14: **strawberry 40, melon 12-13, cow 8, sheep 6, wheat 3-7, no carrot, no
tomato**. Our herd (8 cows / 6 sheep) already matches; our crop split does not.

They also buy **livestock on day 2**, spending nearly the whole opening bank, and Ben
**pivots into wheat late** (7 → 19 → 31 → 38 tiles over days 22-28) once strawberry
cannot fit another cycle and wheat has climbed to $52-55.

Prices in that game:

| Product | Behaviour |
|---|---|
| **Milk** | never crashes — $190-220 all season, 26/day demand absorbs 8 cows |
| **Wheat** | **rises 25 → $55** — 38/day demand, almost nobody grows it |
| Wool | collapses 222 → 11 by day 20 with 6 sheep on both sides |
| Strawberry | rises to 212, then crashes to 3 as both farms dump late |
| Melon | falls all game — no shop demands it |

**Copying their configuration makes us worse**, measured:

| Change toward the elite build | Result |
|---|---|
| Their crop mix (STRAW 0.55, no carrot/tomato) | **loses 1/6 h2h**; 74,875 vs starter |
| Earlier livestock (`HERD_MIN_MONEY` 1200→600→250) | 97,867 → 83,660 → 78,064 |

Every dial is at a local optimum. The gap is **execution, not allocation** — they can
service 40 strawberry tiles and day-2 livestock, and our engine starves when asked to.
See `PLAN.md`.

## What now decides a game (v12, 41 ranked episodes, 21W-20L)

Our score tracks the **milk and wool price** almost perfectly. Across all 41 replays:

| Final milk / wool price | Our score |
|---|---|
| milk 230-300, wool 220-250 | **100,000-122,000** |
| milk < 150 or wool < 50 | **22,000-70,000** |

Every disaster game (22k, 29k, 63k, 64k, 67k, 69k) has milk and/or wool collapsed to
near the $1 floor. **Strawberry never crashed** — it held 208-280 in all 41 games.

The supply arithmetic explains it exactly. Two standard farms against town demand:

| Product | Town/day | 2-farm supply/day | Ratio |
|---|---|---|---|
| Strawberry | 32 | 18.8 | **0.59** safe |
| Wool | 20 | 16.0 | 0.80 |
| Milk | 26 | 24.0 | **0.92** on the edge |

Milk and wool sit at the limit with two *standard* farms, and opponents now run herds
of 9-28 head, which pushes past 1.0 and collapses both. Strawberry has real headroom.

**The field has converged.** Two days ago most opponents grew melon or nothing;
now nearly every one runs livestock (herd 9-28) and strawberry (30-47 tiles). Scores
on both sides fall in the later episodes as the shared markets get contested harder.

### Neither obvious response works

| Response | Result |
|---|---|
| Leaner herd (5 cows / 3 sheep) to stop crashing wool and milk | **loses 0/8** |
| More strawberry (0.62) to lean on the market with headroom | **loses 3/8** |
| More strawberry *under a forced crash* (12 cows / 10 sheep both sides) | **loses 2/8** |

Cutting supply is the melon lesson again: it is a race, not a commons. Unilateral
restraint just hands the town's demand to the rival, who sells into it instead.

The remaining variance is therefore **opponent-driven and not fixable by allocation**.
The untried angle is to stop *spending actions* on a collapsed product — a cow at a
$5 milk price still costs feed, care and harvest every day, and those actions would be
worth more on crops. `KAG_CARE` exists but is not price-aware.

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
