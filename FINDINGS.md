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

## Baseline (measured, 5 full episodes)

```
main.py (v1 wheat loop)  mean=3371.0  stdev=15.3
starter                  mean=3505.2  stdev= 8.6
win rate: 0/5
```

Episode runtime ~3.4s, so iteration is cheap. Variance is tiny (stdev ~15), so real
improvements are unambiguous at 5 episodes.
