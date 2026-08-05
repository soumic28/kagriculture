#!/usr/bin/env bash
# Usage: ./submit.sh "commit message / submission note"
#
# Runs a 5-episode full-season regression check against the `starter`
# baseline before submitting. Refuses to submit if main.py loses to starter
# on average -- change the threshold below if that's ever intentional
# (e.g. you're deliberately testing something experimental).
set -euo pipefail

MSG="${1:?Usage: ./submit.sh \"submission message\"}"

echo "== Regression check: main.py vs starter, 5 episodes, full season =="
python local_test.py --full --opponent starter --episodes 5 | tee /tmp/kaggriculture_check.txt

MAIN_MEAN=$(grep "^main.py" /tmp/kaggriculture_check.txt | grep -oP 'mean=\s*\K[0-9.]+')
STARTER_MEAN=$(grep "^starter" /tmp/kaggriculture_check.txt | grep -oP 'mean=\s*\K[0-9.]+')

if (( $(echo "$MAIN_MEAN < $STARTER_MEAN" | bc -l) )); then
  echo
  echo "main.py mean ($MAIN_MEAN) is below starter mean ($STARTER_MEAN)."
  read -p "Submit anyway? [y/N] " confirm
  [[ "$confirm" == [yY] ]] || { echo "Aborted."; exit 1; }
fi

echo
echo "== Submitting to Kaggle =="
kaggle competitions submit kaggriculture -f main.py -m "$MSG"

echo
echo "== Now log this in SUBMISSIONS.md =="
echo "git commit: $(git rev-parse --short HEAD 2>/dev/null || echo 'uncommitted -- commit first!')"
echo "kaggle competitions submissions kaggriculture   # to get the submission ID"
