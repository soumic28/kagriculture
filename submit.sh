#!/usr/bin/env bash
# Usage: ./submit.sh "submission message" [min_mean]
#
# Runs a 5-episode full-season regression check before submitting, and refuses to
# submit if the agent lost ground. Two gates:
#   1. must beat the `starter` baseline on mean score
#   2. must clear `min_mean` (default REGRESSION_FLOOR below) -- catches the case
#      where a change still beats starter but is far worse than the last good build
#
# Prefers the project venv, since kaggle-environments and the kaggle CLI are
# installed there rather than system-wide.
set -euo pipefail

# Roughly 90% of the best measured mean vs starter. Raise this as the agent improves.
REGRESSION_FLOOR=55000

MSG="${1:?Usage: ./submit.sh \"submission message\" [min_mean]}"
FLOOR="${2:-$REGRESSION_FLOOR}"

cd "$(dirname "$0")"

if [[ -x .venv/Scripts/python.exe ]]; then
  PY=.venv/Scripts/python.exe            # Windows venv
  KAGGLE=.venv/Scripts/kaggle.exe
elif [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python                    # POSIX venv
  KAGGLE=.venv/bin/kaggle
else
  PY=python
  KAGGLE=kaggle
fi

OUT="$(mktemp -t kaggriculture_check.XXXXXX)"
trap 'rm -f "$OUT"' EXIT

echo "== Regression check: main.py vs starter, 5 episodes, full season =="
"$PY" local_test.py --full --opponent starter --episodes 5 | tee "$OUT"

# Parse and compare in Python: `bc` is not present in Git Bash on Windows, and the
# original grep -oP / bc pipeline failed silently there.
if ! "$PY" - "$OUT" "$FLOOR" <<'EOF'
import re, sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
floor = float(sys.argv[2])

def mean_for(prefix):
    m = re.search(rf"^{prefix}\s+mean=\s*([0-9.]+)", text, re.M)
    return float(m.group(1)) if m else None

main_mean, starter_mean = mean_for("main.py"), mean_for("starter")
if main_mean is None or starter_mean is None:
    print("\nFAIL: could not parse means from the test output.")
    sys.exit(1)

print(f"\nmain.py mean {main_mean:,.0f}   starter mean {starter_mean:,.0f}   floor {floor:,.0f}")
ok = True
if main_mean <= starter_mean:
    print("FAIL: does not beat the starter baseline.")
    ok = False
if main_mean < floor:
    print(f"FAIL: {main_mean:,.0f} is below the regression floor {floor:,.0f}.")
    ok = False
sys.exit(0 if ok else 1)
EOF
then
  echo
  read -r -p "Regression check failed. Submit anyway? [y/N] " confirm
  [[ "$confirm" == [yY] ]] || { echo "Aborted."; exit 1; }
fi

if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  echo
  read -r -p "Working tree is dirty; the submission will not match any commit. Continue? [y/N] " confirm
  [[ "$confirm" == [yY] ]] || { echo "Aborted -- commit first."; exit 1; }
fi

echo
echo "== Submitting to Kaggle =="
"$KAGGLE" competitions submit kaggriculture -f main.py -m "$MSG"

echo
echo "== Now log this in SUBMISSIONS.md =="
echo "git commit: $(git rev-parse --short HEAD 2>/dev/null || echo 'not a git repo')"
echo "$KAGGLE competitions submissions kaggriculture   # to get the submission ID"
