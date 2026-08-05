# Submission Log

Update this on every `kaggle competitions submit`. Keeps a paper trail across
sessions so you (or a fresh Claude Code session) can see what's actually been
tried, not just what's in the current working tree.

| Date | Git commit | Description | Local test (vs starter, 5 eps) | Kaggle submission ID | Public LB score |
|------|-----------|-------------|-------------------------------|----------------------|------------------|
| 2026-08-05 | `a45bfac` | v2 engine + melon | 60,569 | _not submitted_ | — |
| 2026-08-05 | _pending_ | v2 tuned, geese off | **61,541** (starter 3,504, 5/5) | _pending_ | _pending_ |

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
