"""
Dev tool: run one episode and report where the season actually went.

Invalid actions in this env are silent no-ops, so "it ran without errors" proves
nothing. This dumps per-day state (money, land, crew, tile usage, prices) plus an
action histogram, which is how you spot units idling or jobs never being reached.

    python diagnose.py [--opponent starter] [--steps 720]
"""
import argparse
import collections

from kaggle_environments import make


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opponent", default="starter")
    ap.add_argument("--steps", type=int, default=720)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    cfg = {"episodeSteps": args.steps}
    if args.seed is not None:
        cfg["seed"] = args.seed

    env = make("kaggriculture", configuration=cfg, debug=True)
    env.run(["main.py", args.opponent])

    ops = collections.Counter()
    daily = {}

    for step_idx, snap in enumerate(env.steps):
        s0 = snap[0]
        obs = s0.observation
        act = s0.action if isinstance(s0.action, dict) else {}

        for unit_action in [act.get("farmer")] + list(act.get("hands") or []):
            if isinstance(unit_action, list) and unit_action:
                ops[unit_action[0]] += 1
        for order in act.get("market") or []:
            if isinstance(order, list) and order:
                ops["mkt:" + order[0]] += 1

        farms = obs.get("farms")
        if not farms:
            continue
        farm = farms[0]
        day = obs.get("day", 0)

        counts = collections.Counter()
        for row in farm["tiles"]:
            for t in row:
                if t == "LOCKED":
                    counts["locked"] += 1
                elif t is None:
                    counts["empty"] += 1
                elif isinstance(t, dict):
                    k = t.get("kind")
                    if k == "PLANT":
                        counts["plant"] += 1
                    elif k == "WEED":
                        counts["weed"] += 1
                    else:
                        counts["struct"] += 1

        daily[day] = {
            "money": farm["money"],
            "quads": len(farm["unlocked_quadrants"]),
            "hires": farm["hires_today"],
            "hands": len(farm["hands"]),
            "plant": counts["plant"],
            "empty": counts["empty"],
            "weed": counts["weed"],
            "locked": counts["locked"],
            "shed": sum((obs.get("private") or {}).get("shed", {}).values()),
            "prices": dict(obs["market"]["prices"]),
        }

    print(f"{'day':>4} {'money':>9} {'quad':>4} {'hire':>4} {'plant':>5} "
          f"{'empty':>5} {'weed':>4} {'shed':>4} {'$wheat':>6} {'$egg':>5} {'$melon':>6}")
    print("-" * 72)
    for day in sorted(daily):
        d = daily[day]
        p = d["prices"]
        print(f"{day:>4} {d['money']:>9,.0f} {d['quads']:>4} {d['hires']:>4} "
              f"{d['plant']:>5} {d['empty']:>5} {d['weed']:>4} {d['shed']:>4} "
              f"{p.get('WHEAT', 0):>6} {p.get('EGG', 0):>5} {p.get('MELON', 0):>6}")

    print("\nAction histogram (player 0, whole season):")
    total_unit_ops = sum(v for k, v in ops.items() if not k.startswith("mkt:"))
    for op, cnt in ops.most_common():
        share = "" if op.startswith("mkt:") else f"  ({100 * cnt / total_unit_ops:.1f}%)"
        print(f"  {op:<22} {cnt:>6}{share}")

    final = env.steps[-1]
    print("\nFinal:")
    for i, s in enumerate(final):
        who = "main.py" if i == 0 else args.opponent
        print(f"  Player {i} ({who}): reward={s.reward}")


if __name__ == "__main__":
    main()
