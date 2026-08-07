# Submission Log

Update this on every `kaggle competitions submit`. Keeps a paper trail across
sessions so you (or a fresh Claude Code session) can see what's actually been
tried, not just what's in the current working tree.

| Date | Git commit | Description | Local (vs starter) | Self-play | Kaggle submission ID | Public LB |
|------|-----------|-------------|--------------------|-----------|----------------------|-----------|
| 2026-08-05 | `a45bfac` | v2 engine + melon | 60,569 | — | _not submitted_ | — |
| 2026-08-05 | `e3f632f` | v2 tuned, geese off | 61,541 | — | _not submitted_ | — |
| 2026-08-05 | `6806577` | v3 opponent-aware, h2h tuned | 60,601 | 27,617 | 55268942 | 602.1 |
| 2026-08-05 | `dcbbe11` | v4 opening melon race (frac 0.3) | 56,200 | 25,315 | 55269367 | 599.0 |
| 2026-08-05 | `d746c8f` | v5 diversified mix + 4 geese | 67,515 | 41,151 | 55269657 | 584.3 |
| 2026-08-05 | `c1c2d48` | v6 full livestock | 70,355 | 49,019 | 55270133 | 604.5 (12W-13L) |
| 2026-08-06 | `6fcfb42` | v7 sustainable-demand retune, no geese | 98,019 | 68,752 | 55287828 | _pending_ |
| 2026-08-06 | `543d78b` | v8 reads config, horizon-aware, crash-proof | 102,067 | 67,691 | 55288320 | _pending_ |
| 2026-08-06 | `3e0e5f2` | v9 buy feed wheat (herd stops starving) | 126,185 | 83,205 | 55289366 | **762.6** (22W-19L) |
| 2026-08-06 | `HEAD` | **v10 full-cycle guard for ongoing crops** | **121,710** | **85,145** | **55290xxx** | _pending_ |


v4 scores *lower* than v3 against `starter` on purpose. It beats v3 **4/4 head-to-head**
(29,030 vs 20,760), which is what the leaderboard actually measures. See FINDINGS.md.

### Ranked episode 90166459 -- the loss that produced v4

Lost 20,606 to 25,230. No crash, no timeout (max 38 ms). The rival sowed 24 melon
tiles on day 0, reached market on day 11 at $278 and banked ~$22k in a single harvest,
then replanted. We didn't sell melon until day 16, by which time they had crashed it
to $115. **Reading that replay was worth more than a day of local tuning** -- it
contains the opponent's whole farm, turn by turn.

**Leaderboard scores are a skill rating, not money.** Every submission seeds at 600.0
and climbs as it plays ranked episodes; the top of the board was ~2,985 at submission
time. Don't read the initial 600 as a failure -- re-check after it has played.

**Limit: 5 submissions/day.** Standard Kaggle simulation policy is that only your
latest 2 are tracked for final evaluation and only your best shows on the leaderboard,
so a weak experiment can displace a good agent. Keep the melon build standing.

Historical local scores for reference:

| Build | vs starter |
|---|---|
| v1 wheat loop | 3,371 (loses 0/5) |
| v2 engine, territory dispatch | 17,634 |
| v2 + melon | 60,569 |
| v2 tuned (current) | ~62,000 |

## First-time Kaggle setup (once)

```bash
# 1. Authenticate -- opens a browser
./.venv/Scripts/kaggle.exe auth login
#    ...or drop an API token from https://www.kaggle.com/settings/api into
#    ~/.kaggle/access_token  (chmod 600)

# 2. Accept the rules IN THE BROWSER -- CLI submits fail until you do
#    https://www.kaggle.com/competitions/kaggriculture  -> "Join Competition"

# 3. Verify
./.venv/Scripts/kaggle.exe competitions list --group entered
```

## How to fill this in after a submit

```bash
git rev-parse --short HEAD                                      # -> git commit
./.venv/Scripts/python.exe local_test.py --full --opponent starter --episodes 5
./.venv/Scripts/kaggle.exe competitions submissions kaggriculture   # -> submission ID
./.venv/Scripts/kaggle.exe competitions leaderboard kaggriculture -s  # -> public LB
```

## Reviewing a ranked loss

```bash
kaggle competitions episodes <SUBMISSION_ID>     # find episode ids
kaggle competitions replay <EPISODE_ID>          # replay json
kaggle competitions logs <EPISODE_ID> 0          # our agent's stderr
```

Worth doing on any loss: the open risk is an opponent who also sells melon and
crashes the price we depend on. The replay will show it in `market.prices`.
