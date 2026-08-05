"""
Kaggriculture agent — v1 baseline (wheat loop).

Verified locally: beats the built-in "random" agent over a 200-turn episode
(reward 3028 vs 2040). Still loses badly to the built-in "starter" agent over
a full 720-turn season, which is expected for a single-crop, single-unit v1 —
use this as your scaffold, not your final entry.

Kaggle requires this file to define a top-level `agent` function that takes
one `obs` dict and returns one action dict. See AGENTS.md / README.md for the
full observation/action schema.
"""


def agent(obs):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    fx, fy = me["farmer"]
    tile = me["tiles"][fy][fx]

    market = []

    # Keep exactly one wheat seed in hand at all times (if we can afford it).
    if private["seeds"].get("WHEAT", 0) == 0 and me["money"] >= 10:
        market.append(["BUY_SEED", "WHEAT", 1])

    # Sell off anything sitting in the shed.
    wheat_in_shed = private["shed"].get("WHEAT", 0)
    if wheat_in_shed > 0:
        market.append(["SELL", "WHEAT", wheat_in_shed])

    # Plant if the tile under the farmer is empty and we're holding a seed.
    if tile is None and private["seeds"].get("WHEAT", 0) > 0:
        return {"farmer": ["PLANT", "WHEAT"], "hands": [], "market": market}

    # If standing on a growing plant, water it or harvest it.
    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        crop_age = obs["day"] - tile["planted_day"]
        if crop_age >= 2:  # WHEAT first_yield_day = 2
            return {"farmer": ["HARVEST"], "hands": [], "market": market}
        if not tile["watered_today"]:
            return {"farmer": ["WATER"], "hands": [], "market": market}

    return {"farmer": ["PASS"], "hands": [], "market": market}
