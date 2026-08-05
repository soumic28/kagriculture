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
- `main.py` (v1): single-crop wheat loop. Verified locally — beats `random`
  (3026 mean over 5 episodes), loses to built-in `starter` (~3375 vs ~3495
  full season). This is the floor, not the target.
- Kaggle submissions: see `SUBMISSIONS.md` — update it every time you submit,
  don't rely on memory or Kaggle's UI as the source of truth across sessions.

## Dev workflow
```bash
python local_test.py --opponent starter --full                 # single smoke test
python local_test.py --opponent starter --full --episodes 5    # real comparison (see gotcha below)
python local_test.py --seed 42 --opponent starter               # reproducible debug run
python local_test.py --render                                   # dumps replay.json if behavior looks wrong
./submit.sh "commit message"                                     # regression-checks vs starter, then submits + reminds you to update SUBMISSIONS.md
```
Multi-file agents: tar.gz with `main.py` at root (see AGENTS.md).

**Gotcha (verified empirically, not documented anywhere):**
`kaggle_environments.evaluate(..., num_episodes=N)` returns the *same*
result N times in this env — its RNG appears to be seeded once per
`evaluate()` call, not per episode in the batch. `local_test.py --episodes N`
works around this by calling `evaluate()` N separate times in a loop. If you
ever see identical scores across "different" episodes, this is why — check
you're not accidentally relying on `num_episodes=N` directly somewhere.

## Roadmap (rough priority order)
1. **Multi-crop diversification** — wheat alone caps income; add
   carrot/tomato/melon and animals as land allows.
2. **Land purchase timing** (NE/SW/SE @ $1k/$2k/$4k) — model payback period
   per quadrant before buying, don't buy on autopilot.
3. **Price-function-aware selling** — see README.md's Price Function table.
   Premium goods (strawberry, melon, milk, wool) have `above_target > 1` and
   crash to the $1 floor on modest gluts; stagger/batch sales. Wheat/carrot
   absorb gluts better — fine to sell in bulk.
4. **Animal husbandry** — the CARE+FEED banking mechanic rewards consistent
   daily attention; a hand dedicated to animal upkeep may pay for itself.
5. **Farm hand hiring economics** — Fibonacci hire cost resets daily; more
   hands early in one day is cheaper than spreading hires across days.
6. **Opponent modeling** — benchmark against `starter` and progressively
   more aggressive strategies, not just `random`.

## Conventions
- Keep `agent()` fast; push heavy precompute (e.g. price-curve tables) to
  module load time, not per-call.
- Every strategy change gets a `local_test.py --full --opponent starter` run
  before commit; note the resulting score in the commit message.
