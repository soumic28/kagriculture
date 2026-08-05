"""
Dev tool: score a build on both the uncontested and the contested case.

Leaderboard rating comes from winning episodes against other teams' agents, not from
absolute money, so a build that only looks good against `starter` is mis-tuned. Two
numbers matter:

  vs starter -- the uncontested market, where we have melon to ourselves
  self-play  -- a strong opponent competing for the same melon supply

Also reports value left stranded at the buzzer: goods in the shed or in a unit's
hands at the final step score nothing.

    python eval.py [--episodes 3] [--opponent starter]
"""
import argparse
import statistics

from kaggle_environments import evaluate, make


def score(agents, episodes):
    a, b = [], []
    for _ in range(episodes):
        r = evaluate("kaggriculture", agents,
                     configuration={"episodeSteps": 720}, num_episodes=1)[0]
        a.append(r[0])
        b.append(r[1])
    return a, b


def stranded(opponent):
    """Money left on the table: unsold shed + carried inventory on the last step."""
    env = make("kaggriculture", configuration={"episodeSteps": 720}, debug=True)
    env.run(["main.py", opponent])
    obs = env.steps[-1][0].observation
    priv = obs.get("private") or {}
    prices = obs["market"]["prices"]

    shed = {k: v for k, v in (priv.get("shed") or {}).items() if v}
    carried = {}
    for inv in priv.get("inventories") or []:
        for k, v in (inv or {}).items():
            if v:
                carried[k] = carried.get(k, 0) + v

    def worth(d):
        return sum(prices.get(k, 0) * v for k, v in d.items())

    return shed, carried, worth(shed), worth(carried)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--opponent", default="starter")
    args = ap.parse_args()

    mine, theirs = score(["main.py", args.opponent], args.episodes)
    print(f"vs {args.opponent:<10} main={statistics.mean(mine):>9,.0f} "
          f"(sd {statistics.pstdev(mine):>6,.0f})   opp={statistics.mean(theirs):>9,.0f}   "
          f"wins {sum(1 for x, y in zip(mine, theirs) if x > y)}/{args.episodes}")

    p0, p1 = score(["main.py", "main.py"], args.episodes)
    both = p0 + p1
    print(f"self-play    mean={statistics.mean(both):>9,.0f} "
          f"(sd {statistics.pstdev(both):>6,.0f})   <- contested melon market")

    shed, carried, shed_v, carried_v = stranded(args.opponent)
    print(f"\nstranded at buzzer: shed ${shed_v:,.0f}  carried ${carried_v:,.0f}")
    if shed:
        print(f"  shed:    {shed}")
    if carried:
        print(f"  carried: {carried}")


if __name__ == "__main__":
    main()
