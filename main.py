"""
Kaggriculture agent — v2: multi-tile crop engine with farm hands and land expansion.

v1 was a single farmer working a single tile. This replaces it with a task-assignment
engine: every turn we derive the set of jobs the farm needs doing, rank them, and
greedily hand each job to the nearest idle unit (farmer + hired hands).

Design notes (see FINDINGS.md for the source-verified mechanics these rely on):
  - HARVEST fills the *unit's* inventory, and SELL reads only the *shed*, so units
    carrying a load walk to a shed-access tile and DROP. We sell from the shed every
    turn, which keeps it far below the 100-item cap -- important, because a full shed
    silently blocks BUY_ANIMAL / BUY_PRODUCT.
  - Plants start at consecutive_unwatered = 1, so the planting day must be watered.
    After that, alternate-day watering keeps a plant alive; daily watering only pays
    inside the bonus window, so we water on exactly those two conditions.
  - If PLANT requests for a crop exceed seeds held, the env drops *all* of them. We
    never emit more PLANT jobs than seeds in hand.
  - Market slots (not quantities) are capped at 10/turn, so one SELL order can dump an
    unlimited amount. Selling is price-limited, never throughput-limited.

Kaggle requires this file to define a top-level `agent(obs) -> action`.
"""
import os


def _env(name, default):
    return os.environ.get(name, default)

# Mirrors CROPS in kaggriculture.py. `maxday` is max_yield_day, `first` is
# first_yield_day. Only one-time crops are used; the ongoing crops (tomato,
# strawberry) have low revenue ceilings and are not worth the tile-days.
CROPS = {
    "WHEAT":  {"seed": 10, "first": 2,  "maxday": 4,  "maxyield": 6},
    "CARROT": {"seed": 20, "first": 2,  "maxday": 3,  "maxyield": 4},
    "MELON":  {"seed": 80, "first": 10, "maxday": 12, "maxyield": 6},
}

PRODUCTS = (
    "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
    "EGG", "MILK", "WOOL", "FERTILIZER",
)

MAX_ORDERS = 10
SEASON_DAYS = 30
LAST_DAY = SEASON_DAYS - 1
LAND_PRICES = (1000, 2000, 4000)

# Job priorities. Watering inside the bonus window outranks harvesting so a plant
# collects its final unit before being pulled. Distance dominates dispatch, so these
# mostly act as tie-breaks within a unit's own strip.
P_FEED = 9
P_WATER_BONUS = 9
P_HARVEST = 8
P_WATER_SURVIVE = 7
P_CARE = 7
P_FERT = 7
P_PLANT = 6
P_BUILD = 6
P_DIG = 4

# Carry this many items before a unit walks back to the shed to unload. Higher means
# fewer round trips but risks the end-of-day drop overflowing the 100-item shed,
# where the excess is discarded outright.
DROP_THRESHOLD = int(_env("KAG_DROP_THRESHOLD", 10))

GOOSE_COST = 300
# Wheat kept in the shed as animal feed rather than sold.
FEED_RESERVE_PER_ANIMAL = 2
# Wheat a unit picks up per feed run.
FEED_CARRY = 6

# Strategy dials. Defaults are the tuned values; the environment overrides exist so
# sweep.py can explore combinations without rewriting this file.
MELON_CAP = int(_env("KAG_MELON_CAP", 40))
MELON_DIV = int(_env("KAG_MELON_DIV", 3))
MELON_MIN_DAY = int(_env("KAG_MELON_MIN_DAY", 2))
# Opening melon push: for the first N days, this fraction of owned tiles goes to melon
# ignoring the usual cash reserve. See the race note in _melon_target.
MELON_OPENING_DAYS = int(_env("KAG_MELON_OPENING_DAYS", 1))
# 0.3 is a sharp optimum, settled head-to-head: it beats 0.0 (4/4), 0.2 (4/4),
# 0.35 (4/4) and 0.5 (4/4, and 0.5 collapses -- past ~a third of tiles the seed spend
# starves land and crew). Note this *costs* ~4% against `starter` while gaining ~40%
# contested; the leaderboard scores head-to-head wins, so contested is what counts.
MELON_OPENING_FRAC = float(_env("KAG_MELON_OPENING_FRAC", 0.3))
# Cash floor below which melon planting pauses outside the opening.
MELON_MIN_MONEY = int(_env("KAG_MELON_MIN_MONEY", 900))
# Stop sowing melon once the market has been driven this low: past here the marginal
# melon is heading for the $1 floor and the tile is worth more under wheat.
MELON_PRICE_MIN = int(_env("KAG_MELON_PRICE_MIN", 90))
# How strongly to back off when the opponent is also growing melon. Both farms are
# public, so contention is visible on day 2 rather than when the price collapses on
# day 10.
#
# Measured at 0: backing off LOSES head-to-head 0/4. Melon is a race down a shared
# curve, and conceding acreage just hands the profitable stretch to the rival. Mutual
# backoff does raise both scores -- a cooperative equilibrium -- but a leaderboard
# opponent will not honour it, so we race. Kept as a dial because the trade would
# flip if scoring ever rewarded absolute money over head-to-head wins.
MELON_RIVAL_SHARE = float(_env("KAG_MELON_RIVAL_SHARE", 0.0))
# Geese are off by default. Measured head-to-head they cost more than they earn: a
# melon tile returns ~$150 per unit-action against a goose's ~$25, and $300/bird
# starves the melon-seed and land pipeline exactly when it matters. The husbandry
# code is kept because that trade flips if an opponent contests the melon market --
# egg and fertilizer demand is untouched by both built-in agents.
GOOSE_CAP = int(_env("KAG_GOOSE_CAP", 0))
GOOSE_DIV = int(_env("KAG_GOOSE_DIV", 5))
GOOSE_MIN_DAY = int(_env("KAG_GOOSE_MIN_DAY", 0))
HAND_CAP = int(_env("KAG_HAND_CAP", 16))
HAND_DIV = int(_env("KAG_HAND_DIV", 8))
# Cash-flow crop filling tiles that melon does not take.
#
# Wheat, measured: 61,151 vs carrot's 24,302. Carrot has the better price on the
# volume we actually produce (staple output stays well under its 866-unit floor), but
# that is swamped by capital cost -- $20/seed against wheat's $10, on a shorter cycle,
# so it burns roughly double the cash per tile-day and starves melon seed and land
# exactly when they compound.
STAPLE = _env("KAG_STAPLE", "WHEAT")


def _window_start(crop):
    return (CROPS[crop]["maxday"] + 1) // 2


def _shed_tiles(n):
    half = n // 2
    return ((half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half))


def _step_toward(pos, target):
    """One move that reduces Manhattan distance. y grows downward, so SOUTH is +y."""
    px, py = pos[0], pos[1]
    tx, ty = target
    if px < tx:
        return ["EAST"]
    if px > tx:
        return ["WEST"]
    if py < ty:
        return ["SOUTH"]
    if py > ty:
        return ["NORTH"]
    return ["PASS"]


def _staple(day):
    """Cash-flow crop for a free tile, given how many days are left to mature.

    Wheat wins on capital efficiency rather than price -- see the STAPLE note above.
    Falls back to whatever still has time to ripen as the season runs out.
    """
    for crop in (STAPLE, "CARROT", "WHEAT"):
        if day + CROPS[crop]["maxday"] <= LAST_DAY:
            return crop
    return None


def _melon_target(day, unlocked_tiles, money, melon_price, rival_melon):
    """How many tiles should be carrying melon right now.

    Melon is worth roughly 14x wheat per unit and *fewer* actions per tile-day, but
    its glut curve is quadratic: past ~158 units sold it pins to the $1 floor for the
    rest of the season, and no town shop demands melon to drain the surplus. So the
    tile count is chosen to land near that ceiling across two waves, not maximised.

    Day 0 is deliberately wheat-only: melon locks a tile for 11 days with no income,
    and the opening needs cash for land and crew.
    """
    if day + CROPS["MELON"]["maxday"] > LAST_DAY:
        return 0
    if melon_price < MELON_PRICE_MIN:
        return 0

    # The opening melon wave is winner-take-all. Melon cannot be harvested before
    # age 10 no matter how well it is tended, so the first farm to plant is the first
    # to sell, and it sells into an uncrashed curve -- ~$22k for ~144 melons at $278.
    # Whoever arrives second gets the remainder at $25, then $1.
    #
    # Losing that race cost us a ranked episode (20,606 vs 25,230): the rival sowed 24
    # tiles on day 0 while we were still building land and crew, so we reached market
    # on day 16 at $115 instead of day 11 at $278.
    #
    # But going all-in is worse still (loses 0/4 head-to-head): 25 tiles of melon eat
    # the whole opening bank, and with no wheat income the farm cannot buy land or
    # crew for eleven days, which costs more than the windfall earns. So we take a
    # fraction early -- enough to reach market on time, not so much that growth stops.
    if day <= MELON_OPENING_DAYS:
        return int(unlocked_tiles * MELON_OPENING_FRAC)

    if day < MELON_MIN_DAY or money < MELON_MIN_MONEY:
        return 0
    target = min(MELON_CAP, unlocked_tiles // MELON_DIV)
    # Every melon the rival grows eats the same finite stretch of curve above the
    # $1 floor, so their planted acreage directly displaces the value of ours.
    return max(0, target - int(rival_melon * MELON_RIVAL_SHARE))


def _goose_target(day, unlocked_tiles, money, current):
    """How many coops the farm should be running.

    A cared-for goose lays 2 eggs/day and every surviving animal yields 1 fertilizer
    per day whether or not it was fed -- together roughly $230/day against a $300
    bird, so they repay themselves in days. Both markets use gentle curves (egg is
    logarithmic, fertilizer linear) and neither built-in agent touches them, so they
    absorb volume that melon and wheat cannot.

    Birds need 4 days to start laying, so buying stops well before the season ends.
    """
    if day > 22 or day < GOOSE_MIN_DAY:
        return current
    if money < 1200:
        return current   # melon seed and land come first
    return min(GOOSE_CAP, unlocked_tiles // GOOSE_DIV)


def agent(obs):
    player = obs["player"]
    me = obs["farms"][player]
    priv = obs["private"]
    day = obs["day"]
    hour = obs["hour"]
    money = me["money"]
    tiles = me["tiles"]
    n = len(tiles)
    seeds = priv["seeds"]
    shed = priv["shed"]
    invs = priv["inventories"]

    positions = [list(me["farmer"])] + [list(p) for p in me["hands"]]
    n_units = len(positions)
    acts = [["PASS"] for _ in range(n_units)]

    prices = obs["market"]["prices"]

    # Both farms are public. Counting the rival's melon plots reveals a coming glut
    # around day 10 while there is still time to plant something else, instead of
    # finding out when the price collapses with our own crop already in the ground.
    rival_melon = 0
    for other in range(len(obs["farms"])):
        if other == player:
            continue
        for row in obs["farms"][other]["tiles"]:
            for t in row:
                if isinstance(t, dict) and t.get("crop") == "MELON":
                    rival_melon += 1

    # ---------------------------------------------------------------- survey
    jobs = []          # (priority, x, y, action)
    empty = []
    unlocked_tiles = 0
    melon_count = 0
    coop_count = 0
    animal_count = 0
    open_coops = []    # built but unoccupied
    unfed = set()      # cells with a hungry animal, used to route feed runs

    for y in range(n):
        row = tiles[y]
        for x in range(n):
            t = row[x]
            if t == "LOCKED":
                continue
            unlocked_tiles += 1
            if t is None:
                empty.append((x, y))
                continue
            kind = t.get("kind")
            if kind == "WEED":
                jobs.append((P_DIG, x, y, ["DIG"]))
            elif kind == "PLANT":
                crop = t["crop"]
                c = CROPS.get(crop)
                if c is None:
                    continue
                if crop == "MELON":
                    melon_count += 1
                age = day - t["planted_day"]
                in_window = _window_start(crop) <= age <= c["maxday"]
                watered = t["watered_today"]
                units = t["yield_units"]
                ripe = age >= c["first"] and units > 0 and (
                    units >= c["maxyield"] or age >= c["maxday"]
                )
                if in_window and not watered:
                    jobs.append((P_WATER_BONUS, x, y, ["WATER"]))
                elif ripe:
                    jobs.append((P_HARVEST, x, y, ["HARVEST"]))
                elif not watered and t["consecutive_unwatered"] >= 1:
                    jobs.append((P_WATER_SURVIVE, x, y, ["WATER"]))
            elif kind in ("COOP", "PASTURE"):
                coop_count += 1
                if "animal" not in t:
                    open_coops.append((x, y))
                    continue
                animal_count += 1
                # Feeding is what keeps the bird alive (two missed days and it is
                # gone) and it also unlocks the banked CARE bonus. Harvest before
                # yield_units reaches max_held or production is wasted.
                if not t["fed_today"]:
                    unfed.add((x, y))
                    jobs.append((P_FEED, x, y, ["FEED"]))
                if t["yield_units"] > 0:
                    jobs.append((P_HARVEST, x, y, ["HARVEST"]))
                if t["fertilizer_available"]:
                    jobs.append((P_FERT, x, y, ["COLLECT_FERTILIZER"]))
                if not t["cared_today"]:
                    jobs.append((P_CARE, x, y, ["CARE"]))

    # Fill free tiles with melon up to its ceiling, then the cash-flow staple.
    # Never emit more PLANT jobs than seeds held: the env drops *all* PLANT requests
    # for a crop when they exceed supply, so these counters decrement per job.
    staple = _staple(day)
    melon_slots = max(0, _melon_target(
        day, unlocked_tiles, money, prices.get("MELON", 250), rival_melon) - melon_count)
    melon_seeds = seeds.get("MELON", 0)
    staple_seeds = seeds.get(staple, 0) if staple else 0
    melon_wanted = melon_slots

    goose_goal = _goose_target(day, unlocked_tiles, money, coop_count)
    coop_slots = max(0, goose_goal - coop_count)

    # Coops go on the tiles closest to the shed: every animal needs a wheat delivery
    # from the shed every day, so feed-run distance is a recurring cost, unlike a
    # crop tile which is only visited by its own strip's unit.
    mid = (n - 1) / 2.0
    coop_sites = set()
    if coop_slots:
        near = sorted(empty, key=lambda c: abs(c[0] - mid) + abs(c[1] - mid))
        coop_sites = set(near[:coop_slots])

    # Allocate every free tile to a purpose first, independent of the seed actually in
    # hand, so seed buying can be driven by the real plan. Otherwise an all-melon
    # opening still buys a stack of wheat seed for tiles that will never take it.
    plan = []
    want_melon = melon_slots
    for x, y in empty:
        if (x, y) in coop_sites:
            plan.append((x, y, "COOP"))
        elif want_melon > 0:
            plan.append((x, y, "MELON"))
            want_melon -= 1
        elif staple:
            plan.append((x, y, staple))

    # Emit work only where the seed exists: the env drops *all* PLANT requests for a
    # crop when they exceed supply, so a single over-request wastes the whole turn.
    on_hand = {"MELON": melon_seeds}
    if staple:
        on_hand[staple] = staple_seeds
    demand = {}
    for x, y, what in plan:
        if what == "COOP":
            jobs.append((P_BUILD, x, y, ["BUILD_COOP"]))
            continue
        demand[what] = demand.get(what, 0) + 1
        if on_hand.get(what, 0) > 0:
            jobs.append((P_PLANT, x, y, ["PLANT", what]))
            on_hand[what] -= 1

    # ------------------------------------------------------------- territory
    # Territory, not free-for-all. Assigning every job to the globally nearest unit
    # makes units thrash: assignments flip as they move and they spend the day
    # walking past each other. Instead each unit owns a contiguous vertical strip and
    # works it nearest-first, which is a greedy TSP tour over a small area.
    #
    # This has to be computed before logistics, so an errand can be scoped to the unit
    # that actually owns the animal or coop it concerns. Scoping matters a lot: when
    # every unit reacted to every hungry animal, the whole crew stampeded to the shed
    # each morning and crop work collapsed.
    cells = []
    for x in range(n):
        ys = range(n) if x % 2 == 0 else range(n - 1, -1, -1)
        for y in ys:
            if tiles[y][x] != "LOCKED":
                cells.append((x, y))

    owner = {}
    if n_units and cells:
        per = (len(cells) + n_units - 1) // n_units
        for idx, cell in enumerate(cells):
            owner[cell] = min(idx // per, n_units - 1)

    # ------------------------------------------------------- logistics runs
    # Errands that a tile job cannot express, because they depend on what a unit is
    # carrying rather than on what a tile needs. Each claims its unit for the turn.
    open_shed = [(sx, sy) for (sx, sy) in _shed_tiles(n) if tiles[sy][sx] != "LOCKED"]
    # Goods in the shed or in a unit's hands at the buzzer score nothing, and the
    # end-of-day drop never runs on the final day. So from here units run everything
    # back; past `closing` they stop picking up new work that could not be sold.
    endgame = day >= LAST_DAY and hour >= 8
    closing = day >= LAST_DAY and hour >= 14
    if closing:
        jobs = [j for j in jobs if j[3][0] in ("HARVEST", "DIG")]
    if day >= LAST_DAY and hour >= 20:
        jobs = []

    shed_geese = shed.get("GOOSE", 0)
    shed_wheat = shed.get("WHEAT", 0)
    coops_free = list(open_coops)
    assigned = [False] * n_units

    def _shed_run(i, action):
        """Send unit i to the nearest usable shed tile, then perform `action` there."""
        px, py = positions[i]
        target = min(open_shed, key=lambda s: abs(s[0] - px) + abs(s[1] - py))
        assigned[i] = True
        acts[i] = action if (px, py) == target else _step_toward(positions[i], target)

    for i in range(n_units):
        inv = invs[i] if i < len(invs) else {}
        load = sum(inv.values()) if inv else 0
        px, py = positions[i]
        my_coops = [c for c in coops_free if owner.get(c) == i]
        my_unfed = sum(1 for c in unfed if owner.get(c) == i)

        # 1. Carrying a bird: it is worth $300 and earns nothing until it is housed.
        #    Prefer a coop on this unit's own patch, but house it anywhere rather than
        #    carry it around all day.
        if inv.get("GOOSE", 0) > 0 and coops_free:
            pool = my_coops or coops_free
            target = min(pool, key=lambda c: abs(c[0] - px) + abs(c[1] - py))
            coops_free.remove(target)
            assigned[i] = True
            acts[i] = (["PLACE", "GOOSE"] if (px, py) == target
                       else _step_toward(positions[i], target))
            continue

        if not open_shed:
            continue

        # 2. Full hands (or the last evening): unload so the goods become sellable.
        #    SELL reads the shed only, so produce still in a unit's hands is dead.
        if load and (load >= DROP_THRESHOLD or endgame):
            _shed_run(i, ["DROP"])
            continue

        if endgame:
            continue

        # 3. Fetch a bird for an empty coop on this unit's own patch.
        if shed_geese > 0 and my_coops:
            shed_geese -= 1
            _shed_run(i, ["PICKUP", "GOOSE", 1])
            continue

        # 4. Carry feed out to hungry animals this unit is responsible for. FEED
        #    consumes wheat from the *unit's* inventory, not the shed, so this run is
        #    what makes the FEED jobs above executable at all.
        if my_unfed and shed_wheat > 0 and not inv.get("WHEAT", 0):
            take = min(FEED_CARRY, shed_wheat, my_unfed)
            shed_wheat -= take
            _shed_run(i, ["PICKUP", "WHEAT", take])
            continue

    # -------------------------------------------------------------- dispatch
    mine = [[] for _ in range(n_units)]
    for job in jobs:
        who = owner.get((job[1], job[2]))
        if who is not None:
            mine[who].append(job)

    taken = set()
    for i in range(n_units):
        if assigned[i]:
            continue
        px, py = positions[i]
        has_wheat = (invs[i] if i < len(invs) else {}).get("WHEAT", 0) > 0
        best, best_key = None, None
        # Distance dominates and priority only breaks ties: movement is the scarce
        # resource, and a unit's own strip is small enough to finish in a day anyway.
        for pool in (mine[i], jobs):
            for job in pool:
                cell = (job[1], job[2])
                if cell in taken:
                    continue
                # FEED draws wheat from this unit's own inventory; empty-handed it
                # would walk over and silently no-op.
                if job[3][0] == "FEED" and not has_wheat:
                    continue
                key = (abs(px - job[1]) + abs(py - job[2]), -job[0])
                if best_key is None or key < best_key:
                    best, best_key = job, key
            if best is not None:
                break   # only range beyond the home strip when it is fully clear
        if best is None:
            continue
        taken.add((best[1], best[2]))
        assigned[i] = True
        acts[i] = best[3] if best_key[0] == 0 else _step_toward(positions[i], (best[1], best[2]))

    # ---------------------------------------------------------------- market
    market = []

    # Sell first: money booked here is available to HIRE / BUY_LAND orders later in
    # the same queue, since orders resolve in list order.
    # Wheat is the one product that is also a consumable -- animals eat it out of the
    # shed -- so hold a reserve back rather than selling the flock's dinner.
    reserve = animal_count * FEED_RESERVE_PER_ANIMAL
    for item in PRODUCTS:
        held = shed.get(item, 0)
        if item == "WHEAT":
            held -= reserve
        if held > 0:
            market.append(["SELL", item, held])

    n_extra = len(me["unlocked_quadrants"]) - 1
    if n_extra < len(LAND_PRICES):
        cost = LAND_PRICES[n_extra]
        # Land needs time to earn back: ~25 tiles at roughly $15/tile/day.
        if money >= cost + 400 and day <= 22:
            market.append(["BUY_LAND"])

    # Buy exactly what the tile plan calls for. Melon goes first -- it is the scarce,
    # high-value allocation and during the opening race it takes priority over the
    # cash buffer entirely.
    opening = day <= MELON_OPENING_DAYS
    for crop, reserve in (("MELON", 100 if opening else 600), (staple, 300)):
        if not crop:
            continue
        want = demand.get(crop, 0)
        if crop == staple and not opening:
            want = min(want + 4, 40)   # small buffer so tiles never idle mid-season
        have = seeds.get(crop, 0)
        spare = int(money) - reserve
        if want > have and spare > 0:
            buy = min(want - have, spare // CROPS[crop]["seed"])
            if buy > 0:
                market.append(["BUY_SEED", crop, buy])

    # Buy a bird for every coop that is standing empty and not already spoken for by
    # one sitting in the shed. BUY_ANIMAL lands in the shed and silently fails when
    # the shed is at capacity, which is why produce is sold off every turn.
    want_birds = len(open_coops) - shed.get("GOOSE", 0)
    if want_birds > 0 and day <= 23:
        afford = int(money - 400) // GOOSE_COST
        buy = min(want_birds, afford)
        if buy > 0:
            market.append(["BUY_ANIMAL", "GOOSE", buy])

    # Hiring is wildly underpriced (fib costs: 10 hands = $143 for 240 extra actions).
    # Scale the crew to the amount of workable land.
    target_hands = max(2, min(HAND_CAP, unlocked_tiles // HAND_DIV))
    if hour <= 3 and me["hires_today"] < target_hands:
        room = MAX_ORDERS - len(market)
        for _ in range(min(target_hands - me["hires_today"], max(0, room))):
            market.append(["HIRE"])

    return {
        "farmer": acts[0],
        "hands": acts[1:],
        "market": market[:MAX_ORDERS],
    }
