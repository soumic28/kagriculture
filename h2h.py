"""
Dev tool: play two parameter settings of the agent against each other.

Leaderboard rating is decided by head-to-head wins, and both agents in one episode
share a process (so shared KAG_* env vars cannot differentiate them). This generates
two copies of main.py with the dial defaults baked in, then plays them off, swapping
seats each round so seat advantage cancels.

    python h2h.py --episodes 4 A:KAG_MELON_RIVAL_SHARE=0.5 B:KAG_MELON_RIVAL_SHARE=1.0
"""
import argparse
import os
import re
import statistics

from kaggle_environments import evaluate

A_PATH, B_PATH = "_h2h_a.py", "_h2h_b.py"


def make_variant(path, overrides):
    src = open("main.py", encoding="utf-8").read()
    for key, value in overrides.items():
        pattern = rf'_env\(\s*"{re.escape(key)}"\s*,\s*[^)]*\)'
        new_src, count = re.subn(pattern, f'_env("_PINNED_{key}", {value})', src)
        if not count:
            raise SystemExit(f"dial {key} not found in main.py")
        src = new_src
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)


def parse(specs, tag):
    out = {}
    for spec in specs:
        side, _, kv = spec.partition(":")
        if side != tag:
            continue
        key, _, value = kv.partition("=")
        out[key] = value
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=4)
    ap.add_argument("dials", nargs="+", help="A:NAME=value / B:NAME=value")
    args = ap.parse_args()

    a_over, b_over = parse(args.dials, "A"), parse(args.dials, "B")
    make_variant(A_PATH, a_over)
    make_variant(B_PATH, b_over)

    print(f"A: {a_over or 'defaults'}")
    print(f"B: {b_over or 'defaults'}\n")

    a_scores, b_scores, a_wins = [], [], 0
    try:
        for i in range(args.episodes):
            # Swap seats every other episode so any seat advantage cancels out.
            order = [A_PATH, B_PATH] if i % 2 == 0 else [B_PATH, A_PATH]
            r = evaluate("kaggriculture", order,
                         configuration={"episodeSteps": 720}, num_episodes=1)[0]
            a, b = (r[0], r[1]) if i % 2 == 0 else (r[1], r[0])
            a_scores.append(a)
            b_scores.append(b)
            a_wins += a > b
            print(f"  ep{i+1}: A={a:>9,.0f}  B={b:>9,.0f}  -> {'A' if a > b else 'B'}")
    finally:
        for p in (A_PATH, B_PATH):
            if os.path.exists(p):
                os.remove(p)

    print(f"\nA mean {statistics.mean(a_scores):>9,.0f}   "
          f"B mean {statistics.mean(b_scores):>9,.0f}")
    print(f"A wins {a_wins}/{args.episodes}")


if __name__ == "__main__":
    main()
