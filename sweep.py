"""
Dev tool: grid-search the strategy dials in main.py.

main.py reads its tunables from KAG_* environment variables (defaulting to the tuned
values), so a sweep is just "set env, run episodes, average". Each config is run in a
fresh subprocess because the env imports main.py once per process.

    python sweep.py --episodes 3 KAG_MELON_CAP=28,36,45 KAG_GOOSE_CAP=0,10,20
"""
import argparse
import itertools
import json
import os
import statistics
import subprocess
import sys

RUNNER = r"""
import json, os, sys
from kaggle_environments import evaluate
scores = []
for _ in range(int(sys.argv[1])):
    r = evaluate("kaggriculture", ["main.py", sys.argv[2]],
                 configuration={"episodeSteps": 720}, num_episodes=1)[0]
    scores.append(r[0])
sys.stderr.write("RESULT" + json.dumps(scores) + "\n")
"""


def run(env_overrides, episodes, opponent):
    env = dict(os.environ)
    env.update({k: str(v) for k, v in env_overrides.items()})
    proc = subprocess.run(
        [sys.executable, "-c", RUNNER, str(episodes), opponent],
        capture_output=True, text=True, env=env,
    )
    for line in proc.stderr.splitlines():
        if line.startswith("RESULT"):
            return json.loads(line[len("RESULT"):])
    print(proc.stderr[-2000:], file=sys.stderr)
    raise RuntimeError("no result from subprocess")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--opponent", default="starter")
    ap.add_argument("dials", nargs="+", help="NAME=v1,v2,v3")
    args = ap.parse_args()

    names, value_lists = [], []
    for spec in args.dials:
        name, _, values = spec.partition("=")
        names.append(name)
        value_lists.append(values.split(","))

    combos = list(itertools.product(*value_lists))
    print(f"{len(combos)} configs x {args.episodes} episodes\n")

    results = []
    for combo in combos:
        overrides = dict(zip(names, combo))
        scores = run(overrides, args.episodes, args.opponent)
        mean = statistics.mean(scores)
        sd = statistics.pstdev(scores) if len(scores) > 1 else 0.0
        results.append((mean, sd, overrides))
        label = " ".join(f"{k.replace('KAG_', '')}={v}" for k, v in overrides.items())
        print(f"  {label:<50} mean={mean:>9,.0f}  sd={sd:>7,.0f}")

    print("\nRanked:")
    for mean, sd, overrides in sorted(results, reverse=True, key=lambda r: r[0]):
        label = " ".join(f"{k.replace('KAG_', '')}={v}" for k, v in overrides.items())
        print(f"  {mean:>9,.0f}  (sd {sd:>6,.0f})  {label}")


if __name__ == "__main__":
    main()
