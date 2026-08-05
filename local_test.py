"""
Local test harness for the Kaggriculture agent.

Usage:
    python local_test.py                          # 1 episode, main.py vs random, short
    python local_test.py --full                    # full 720-turn season
    python local_test.py --opponent starter
    python local_test.py --episodes 10 --full       # 10 full-season episodes, report mean/stdev/win-rate
    python local_test.py --seed 42                  # reproducible single episode (for debugging)
    python local_test.py --render                   # dump replay.json (single episode only)

Note on variance: kaggle_environments.evaluate(..., num_episodes=N>1) returns
the SAME result N times in this environment (its internal RNG appears to be
seeded once per evaluate() call, not per episode within the batch) -- verified
empirically, not documented. To get real variance from weed-spawn randomness
and/or a stochastic opponent, this script calls evaluate() N separate times
in a loop instead. If you ever see identical scores across all N episodes,
that's this quirk resurfacing, not a bug in your agent.
"""
import argparse
import json
import statistics

from kaggle_environments import evaluate, make


def run_single(opponent, steps, seed, render):
    config = {"episodeSteps": steps}
    if seed is not None:
        config["seed"] = seed
    env = make("kaggriculture", configuration=config, debug=True)
    env.run(["main.py", opponent])

    final = env.steps[-1]
    print(f"\n{'agent':<10} vs {opponent:<10} | {steps} turns" + (f" | seed={seed}" if seed is not None else ""))
    print("-" * 40)
    for i, s in enumerate(final):
        who = "main.py" if i == 0 else opponent
        print(f"Player {i} ({who:<10}): reward={s.reward}, status={s.status}")

    if render:
        with open("replay.json", "w") as f:
            json.dump(env.toJSON(), f)
        print("\nWrote replay.json (drag into the Kaggle simulation visualizer)")


def run_many(opponent, steps, episodes, seed):
    config = {"episodeSteps": steps}
    if seed is not None:
        config["seed"] = seed  # fixed seed + N episodes = N identical runs, mostly useful for regression checks

    mine, theirs = [], []
    for i in range(episodes):
        r = evaluate("kaggriculture", ["main.py", opponent], configuration=config, num_episodes=1)[0]
        mine.append(r[0])
        theirs.append(r[1])
        print(f"  episode {i+1:>3}/{episodes}: main.py={r[0]:>8.0f}  {opponent}={r[1]:>8.0f}")

    wins = sum(1 for a, b in zip(mine, theirs) if a > b)
    ties = sum(1 for a, b in zip(mine, theirs) if a == b)
    print(f"\n{'agent':<10} vs {opponent:<10} | {steps} turns | {episodes} episodes")
    print("-" * 50)
    print(f"main.py  mean={statistics.mean(mine):>8.1f}  stdev={statistics.pstdev(mine):>7.1f}")
    print(f"{opponent:<8} mean={statistics.mean(theirs):>8.1f}  stdev={statistics.pstdev(theirs):>7.1f}")
    print(f"win rate: {wins}/{episodes} ({100*wins/episodes:.0f}%)" + (f", {ties} tie(s)" if ties else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--opponent", default="random", choices=["random", "pass", "starter"])
    parser.add_argument("--full", action="store_true", help="run the full 720-turn season instead of a 200-turn smoke test")
    parser.add_argument("--episodes", type=int, default=1, help="run N episodes and report mean/stdev/win-rate")
    parser.add_argument("--seed", type=int, default=None, help="fixed seed for reproducible runs (debugging / regression checks)")
    parser.add_argument("--render", action="store_true", help="dump replay.json (single-episode runs only)")
    args = parser.parse_args()

    steps = 720 if args.full else 200

    if args.episodes > 1:
        if args.render:
            print("--render is ignored when --episodes > 1 (no single episode to dump)")
        run_many(args.opponent, steps, args.episodes, args.seed)
    else:
        run_single(args.opponent, steps, args.seed, args.render)
