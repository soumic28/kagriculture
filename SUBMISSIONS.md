# Submission Log

Update this on every `kaggle competitions submit`. Keeps a paper trail across
sessions so you (or a fresh Claude Code session) can see what's actually been
tried, not just what's in the current working tree.

| Date | Git commit | Description | Local test (vs starter, N eps) | Kaggle submission ID | Public LB score |
|------|-----------|-------------|-------------------------------|----------------------|------------------|
| YYYY-MM-DD | `xxxxxxx` | v1 wheat loop | not yet run at N>1 | _pending_ | _pending_ |

## How to fill this in after a submit

```bash
git rev-parse --short HEAD                          # -> git commit
python local_test.py --full --opponent starter --episodes 5   # -> local test column
kaggle competitions submissions kaggriculture        # -> submission ID
kaggle competitions leaderboard kaggriculture -s     # -> public LB score, once it's played
```
