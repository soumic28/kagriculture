# Plan to climb the Kaggriculture ladder

Status as of 2026-08-06. Read `FINDINGS.md` for the mechanics and measured results
this plan rests on; this file is only the forward plan.

## Where we actually stand

| | Us (v8) | Elite (top 3) |
|---|---|---|
| vs `starter` (uncontested) | 102,067 | — |
| **Contested** (self-play / h2h) | **~68-80k** | **109-115k** |
| Ladder rating | ~600 | ~2,950-3,035 |

**The contested number is the only one that matters.** Episode 90338757 is Ben Hamilton
(115,481) vs Winter Lamb (109,426) — the #2 and #3 agents playing each other. We score
~68-80k in the equivalent situation. That ~40% gap is the whole problem.

## What the elite replay proves

Both top agents converge on almost the same farm, held steady from day 14:

| | Ben | Lamb | Us |
|---|---|---|---|
| Strawberry | 40 | 40 | ~14 |
| Melon | 12 | 13 | ~26 |
| **Cow** | **8** | **8** | **8** |
| **Sheep** | **6** | **6** | **6** |
| Wheat | 7 | 3 | ~22 |
| Carrot / Tomato | 0 / 0 | 0 / 0 | ~18 / ~20 |

Plus two behaviours we lack:
- **Livestock on day 2.** They spend nearly the entire $3,000 opening bank on 2 cows,
  2 sheep and pastures, so milk flows from day 10.
- **A late pivot into wheat.** Ben goes WHEA 7 → 19 → 31 → 38 across days 22-28, once
  strawberry cannot fit another cycle and wheat has risen to $52-55.

Price behaviour in that game:
- **Milk never crashes** ($190-220 all season) — 26/day of town demand absorbs 8 cows.
- **Wool collapses** (222 → 11 by day 20) when both players run 6 sheep.
- **Wheat rises 25 → $55** — 38/day demand and almost nobody grows it.
- Strawberry and melon both crash late as the two farms dump together.

## The uncomfortable finding

**Copying the elite configuration makes us worse.** Measured, not assumed:

| Change toward the elite build | Result |
|---|---|
| Their crop mix (STRAW 0.55 / MELON 0.16 / WHEAT 0.10 / no carrot or tomato) | **loses 1/6** head-to-head; 74,875 vs starter |
| Livestock earlier (`HERD_MIN_MONEY` 1200 → 600 → 250) | 97,867 → 83,660 → 78,064 |
| Bigger herd, strawberry-heavy, phased melon opening | all worse (see FINDINGS.md) |

Every dial is at a local optimum. **The gap is not allocation — it is execution.**
They can service 40 strawberry tiles and day-2 livestock; our engine cannot, and
starves when asked to.

## The actual bottleneck

Action budget. From the season action histogram:

```
movement (N/S/E/W)   52%
PASS (idle)           9%
productive work      39%
```

Six of every ten actions do nothing. Adding tiles or animals makes it worse, which is
exactly why every "more of the good thing" experiment regressed.

## Done since this plan was written

**The bottleneck was not movement.** Tracing revenue by product found milk earning
$332/unit but only 79 units sold against ~264 potential, and wool earning nothing at
all. The herd was starving -- COW:10 SHEEP:7 at day 16 down to COW:5 SHEEP:4 by day 22
-- because we only fed from wheat we grew. Buying feed wheat from the market fixed it:
beats v8 8/8, self-play 67,691 -> 83,205.

Priority 1 below (cut movement waste) was **measured and rejected**: 52% movement is
close to the floor for this board, and every attempt to reduce it (fewer/denser tiles,
larger crews, smaller crews) lost. Priority 2 (late wheat pivot, via price-adaptive
allocation) measured dead even at 4/8. Both dials remain in the code, defaulted off.

## Priorities

### 1. Cut movement waste — the only change that unlocks everything else
Everything below is blocked on this. Concrete ideas, cheapest first:

- **Day-route planning.** Each unit currently re-picks its nearest job every turn,
  greedily. Plan a whole-day tour at hour 0 over the unit's known jobs and follow it,
  replanning only on surprises. Greedy nearest-neighbour re-decided each turn is
  strictly worse than a planned tour.
- **Deadline-aware ordering.** Watering has an end-of-day deadline; harvest and plant
  do not. Order each unit's tour to hit deadline jobs first, then fill.
- **Co-locate multi-job tiles.** A tile needing water *and* harvest should be finished
  in consecutive turns without moving away. This partly happens by accident; make it
  explicit.
- **Rebalance strips by workload, not tile count.** Strips are equal-sized today; a
  strip of 8 strawberry tiles is far less work than 8 wheat tiles.

Target: movement under 40%, PASS under 4%. That is roughly a 30% increase in effective
actions, which is the size of the gap to the elite agents.

### 2. Late-season wheat pivot
Wheat reaches $52-55 by day 24 and has a 4-day cycle. Ben converts a third of his farm
to it. Our fallback only plants wheat when nothing else *can* mature — it should
actively prefer wheat late, on price. Cheap to implement, likely a real gain.

### 3. Reconsider sheep
Wool crashed to $11 by day 20 with 6 sheep on each side. Milk never crashed. Trading
sheep for cows may be strictly better in contested games — but note 8/6 already
measured best for us, so **test head-to-head before changing**.

### 4. Only then revisit the crop mix
Once actions are cheaper, retest the elite mix. It should become affordable, and it is
the configuration two independent top agents arrived at.

## Working rules

- **Decide with `h2h.py`, not `sweep.py`.** They disagree. `starter` never sells melon,
  eggs, milk or wool, so uncontested scores reward exploiting markets a real opponent
  contests. Rating comes from head-to-head wins.
- **Never submit an unmeasured change.** Only the latest 2 submissions count for final
  evaluation and only the best shows on the board, so a bad experiment can displace a
  good agent. 5/day.
- **Let a submission play before judging it.** v6 needed 25 games before its 12W-13L
  was trustworthy. A fresh submission reads 600 regardless of quality.
- **Mine every loss.** `kaggle competitions replay <EP> -p ./replays` then
  `python scout.py`. Every real gain so far came from a replay, never from a sweep.
- **Findings expire.** Geese measured harmful under monoculture and helpful under a
  diversified mix. Re-test after any structural change.
