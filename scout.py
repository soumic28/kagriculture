"""
Dev tool: mine downloaded ranked replays for what the opponents actually did.

Every replay carries both farms turn by turn, so a handful of ranked games is a direct
read on the meta -- far better evidence than local self-play. Reports, per episode:
our score vs theirs, when each side first planted and first sold melon (the race that
decides the game), and what their farm looked like at its peak.

    python scout.py [--dir ./replays]
"""
import argparse
import collections
import glob
import json
import os


def tile_counts(farm):
    c = collections.Counter()
    for row in farm["tiles"]:
        for t in row:
            if t == "LOCKED":
                c["locked"] += 1
            elif t is None:
                c["empty"] += 1
            elif isinstance(t, dict):
                kind = t.get("kind")
                if kind == "PLANT":
                    c[t["crop"]] += 1
                elif kind == "WEED":
                    c["WEED"] += 1
                elif "animal" in t:
                    c[t["animal"]] += 1
                else:
                    c[kind] += 1
    return c


def summarise(path, me_name):
    r = json.load(open(path, encoding="utf-8"))
    steps = r["steps"]
    rewards = r.get("rewards") or []

    # Seats alternate between ranked episodes -- we are not always player 0. Assuming
    # otherwise silently swaps us with the opponent and inverts every conclusion.
    names = (r.get("info") or {}).get("TeamNames") or []
    ours = 0
    for i, nm in enumerate(names):
        if me_name.lower() in (nm or "").lower():
            ours = i
            break

    first_melon = [None, None]      # day each side first had melon in the ground
    first_sale = [None, None]       # day each side's money first jumped hard
    peak = [collections.Counter(), collections.Counter()]
    peak_tiles = [0, 0]
    prev_money = [3000.0, 3000.0]
    quads = [1, 1]

    for snap in steps:
        obs = snap[0]["observation"]
        if "farms" not in obs:
            continue
        day = obs.get("day", 0)
        for p in (0, 1):
            farm = obs["farms"][p]
            c = tile_counts(farm)
            if c.get("MELON", 0) and first_melon[p] is None:
                first_melon[p] = day
            money = farm["money"]
            if money - prev_money[p] > 4000 and first_sale[p] is None:
                first_sale[p] = day
            prev_money[p] = money
            worked = sum(v for k, v in c.items() if k not in ("locked", "empty"))
            if worked > peak_tiles[p]:
                peak_tiles[p] = worked
                peak[p] = c
            quads[p] = max(quads[p], len(farm["unlocked_quadrants"]))

    them = 1 - ours
    order = [ours, them]
    return {
        "id": os.path.basename(path).split("-")[1],
        "names": [names[i] if i < len(names) else "?" for i in order],
        "rewards": [rewards[i] if i < len(rewards) else None for i in order],
        "first_melon": [first_melon[i] for i in order],
        "first_sale": [first_sale[i] for i in order],
        "peak": [peak[i] for i in order],
        "quads": [quads[i] for i in order],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="./replays")
    ap.add_argument("--me", default="soumic", help="substring of our Kaggle team name")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.dir, "*-replay.json")))
    if not files:
        raise SystemExit(f"no replays in {args.dir}")

    wins = losses = 0
    for path in files:
        s = summarise(path, args.me)
        us, them = (s["rewards"] + [None, None])[:2]
        verdict = "?"
        if us is not None and them is not None:
            verdict = "WIN " if us > them else "LOSS"
            wins += us > them
            losses += us <= them
        print(f"\n=== episode {s['id']}  {verdict}   us {us:,.0f}  "
              f"them {them:,.0f} ({s['names'][1]}) ===")
        for p, who in ((0, "us  "), (1, "them")):
            top = ", ".join(f"{k}:{v}" for k, v in s["peak"][p].most_common()
                            if k not in ("locked", "empty"))
            print(f"  {who}  melon planted day {str(s['first_melon'][p]):<5} "
                  f"first big sale day {str(s['first_sale'][p]):<5} "
                  f"quads {s['quads'][p]}")
            print(f"        peak farm: {top}")

    print(f"\n{wins} win(s), {losses} loss(es) across {len(files)} replays")


if __name__ == "__main__":
    main()
