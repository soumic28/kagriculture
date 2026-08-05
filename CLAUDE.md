# CLAUDE.md

Project context for Claude Code. Full specs live in `README.md` (game rules,
object tables, price function) and `AGENTS.md` (CLI setup, submission,
episode/replay workflow) — read those before making game-logic changes.
This file is the orientation layer, not a replacement.

## What this is
Kaggriculture: a 2-player farming-sim Kaggle competition (hosted by Kaggle +
Google, $50k prize pool, entry deadline Sept 23, 2026). `main.py` defines a
top-level `agent(obs) -> action` function. Win = most money in the bank at
the end of a 720-turn season (30 days × 24 turns/day).

## Hard constraints (easy to violate by accident)
- `actTimeout = 1s` per action call, `runTimeout = 1200s` per episode —
  `agent()` must return fast on every one of up to 720 calls. No per-turn
  LLM calls, no unbounded search/lookahead.
- Only `WHEAT` and `FERTILIZER` can be bought back via `BUY_PRODUCT`; every
  other sold product is gone for good. Don't oversell things you'll need.
- `maxMarketOrdersPerTurn = 10` — extra orders in a turn are silently
  *dropped*, not queued for next turn.
- Invalid actions are silent no-ops, never exceptions — bugs won't crash the
  episode, they'll just quietly do nothing. Verify behavior via replays, not
  by trusting the absence of errors.

## Current status
- `main.py` (v2): multi-unit task-assignment engine — territory dispatch, melon
  allocation, hired crew, land expansion. **~62,000 mean vs `starter` ~3,500,
  5/5 wins** over 5 full episodes. v1's wheat loop scored 3,371.
- **Read `FINDINGS.md` before changing strategy.** It records source-verified
  mechanics (the game docs are wrong in several places), the integrated price
  curves, every measured result, and the open risks. Don't re-derive it.
- Env is a project venv: use `./.venv/Scripts/python.exe`, not system Python.
- Kaggle submissions: see `SUBMISSIONS.md` — update it every time you submit,
  don't rely on memory or Kaggle's UI as the source of truth across sessions.

## What actually drives the score
**Diversification.** Every product has an independent price curve with its own
glut ceiling, so volume spread across products earns far more than the same
volume in one — summed ceilings are ~$119k against melon's ~$26k alone. Ranked
replays confirm it: the agents beating us farm all five crops plus livestock
(one scored 106,946), while our melon+wheat monoculture topped out near 60k.

Melon still matters for *timing*, not share: it cannot be harvested before age
10, so the first wave is winner-take-all — first to plant sells at ~$278, second
gets $25 then $1. Hence the opening push at ~0.3 of tiles.

**Optima are sharp and non-monotonic — always bracket a dial.** 4 geese beat 6
and 0, and 12 collapses. 33 melon tiles beat 50 and 25.

## Read the replays before tuning
This is the highest-value habit in this project. Each ranked replay contains the
opponent's whole farm turn by turn; `scout.py` mines them. Five games revealed
the diversification meta and reversed a strategy already tuned hard the wrong
way. Local tuning misleads because `starter` is a single-tile carrot loop that
never sells melon, eggs, milk or wool — beating it rewards exploiting whatever
it ignores, which looks like monoculture.

## Dev workflow
```bash
PY=./.venv/Scripts/python.exe

$PY local_test.py --full --opponent starter --episodes 5   # the standard comparison
$PY diagnose.py --opponent starter                          # per-day state + action histogram
$PY sweep.py --episodes 3 KAG_MELON_DIV=2,3,4               # grid-search strategy dials
$PY local_test.py --render                                  # dumps replay.json
./submit.sh "note"                                          # regression-gates, then submits
```
`diagnose.py` is the tool that finds problems — invalid actions are silent no-ops,
so a healthy-looking score can still hide a broken subsystem. Watch the action
histogram: movement above ~55% means dispatch is thrashing, and a HARVEST count far
below PLANT means crops are dying unwatered.

Strategy constants in `main.py` read `KAG_*` env vars (defaulting to tuned values)
so `sweep.py` can explore them without editing the file.

Multi-file agents: tar.gz with `main.py` at root (see AGENTS.md).

**Gotcha (verified empirically, not documented anywhere):**
`kaggle_environments.evaluate(..., num_episodes=N)` returns the *same*
result N times in this env — its RNG appears to be seeded once per
`evaluate()` call, not per episode in the batch. `local_test.py --episodes N`
works around this by calling `evaluate()` N separate times in a loop. If you
ever see identical scores across "different" episodes, this is why — check
you're not accidentally relying on `num_episodes=N` directly somewhere.

## Sustaining a ladder position
The rating is a skill rating seeded at 600, and it moves only as ranked episodes
play. The loop that works:
1. `kaggle competitions episodes <SUB_ID>` → download replays → `python scout.py`
2. Any loss where the opponent scored far higher: read what they farmed
3. Reproduce the idea locally, decide it with `h2h.py`, submit only if it wins
4. Log it in `SUBMISSIONS.md`

Only the latest 2 submissions count for final evaluation and only the best shows
on the board, so **never submit an unmeasured experiment** — it can displace a
good agent. 5/day.

## Roadmap (rough priority order)
1. **Contested-market robustness** — the biggest open risk. Self-play drops us
   from ~62k to ~28k because both players crash melon. A real opponent doing
   the same halves our return. Options: detect melon price collapse from
   `market.prices` and rotate into egg/fertilizer (uncontested, gentle curves),
   or sell melon earlier to win the race down the curve.
2. **Routing** — movement is still ~52% of actions. Strips are assigned by
   column index, not by walking cost; a better partition is free score.
3. **Price-aware sell scheduling** — we currently dump the shed every turn.
   Spreading melon sales across the day lets town consumption refill inventory
   between batches.
4. **Endgame liquidation** — verify nothing is stranded in unit inventories at
   turn 720; unsold goods score zero.
5. **Revisit geese with a ranch layout** — they lose today mostly on feed
   logistics. Coops abutting the shed would cut the round-trip that killed them.

Settled, don't redo: melon density (~33 tiles is optimal), geese as currently
implemented (net negative), crew size (flat 12-20). See `FINDINGS.md`.

## Conventions
- Keep `agent()` fast; push heavy precompute (e.g. price-curve tables) to
  module load time, not per-call.
- Every strategy change gets a `local_test.py --full --opponent starter` run
  before commit; note the resulting score in the commit message.
