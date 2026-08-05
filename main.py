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
# collects its final unit before being pulled.
P_WATER_BONUS = 9
P_HARVEST = 8
P_WATER_SURVIVE = 7
P_PLANT = 6
P_DIG = 4

# Carry this many items before a unit walks back to the shed to unload.
DROP_THRESHOLD = 10


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

    Wheat's glut curve is logarithmic, so it still fetches ~$18 after 2400 units,
    while carrot hits the $1 floor at 866. Carrot only appears at the very end of the
    season, when its shorter maturity is the only thing that still fits.
    """
    if day + CROPS["WHEAT"]["maxday"] <= LAST_DAY:
        return "WHEAT"
    if day + CROPS["CARROT"]["maxday"] <= LAST_DAY:
        return "CARROT"
    return None


def _melon_target(day, unlocked_tiles, money):
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
    if day < 2 or money < 900:
        return 0
    return min(28, unlocked_tiles // 3)


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

    # ---------------------------------------------------------------- survey
    jobs = []          # (priority, x, y, action)
    empty = []
    unlocked_tiles = 0
    melon_count = 0

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

    # Fill free tiles with melon up to its ceiling, then the cash-flow staple.
    # Never emit more PLANT jobs than seeds held: the env drops *all* PLANT requests
    # for a crop when they exceed supply, so these counters decrement per job.
    staple = _staple(day)
    melon_slots = max(0, _melon_target(day, unlocked_tiles, money) - melon_count)
    melon_seeds = seeds.get("MELON", 0)
    staple_seeds = seeds.get(staple, 0) if staple else 0
    melon_wanted = melon_slots

    for x, y in empty:
        if melon_slots > 0 and melon_seeds > 0:
            jobs.append((P_PLANT, x, y, ["PLANT", "MELON"]))
            melon_slots -= 1
            melon_seeds -= 1
        elif staple and staple_seeds > 0:
            jobs.append((P_PLANT, x, y, ["PLANT", staple]))
            staple_seeds -= 1

    # ------------------------------------------------------------ unload runs
    # A unit holding a big load (or anything at all on the final evening) walks to
    # the nearest unlocked shed-access tile and dumps, making the goods sellable.
    open_shed = [(sx, sy) for (sx, sy) in _shed_tiles(n) if tiles[sy][sx] != "LOCKED"]
    endgame = day >= LAST_DAY and hour >= 10

    assigned = [False] * n_units
    for i in range(n_units):
        inv = invs[i] if i < len(invs) else {}
        load = sum(inv.values()) if inv else 0
        if not load or not open_shed:
            continue
        if load < DROP_THRESHOLD and not endgame:
            continue
        px, py = positions[i]
        target = min(open_shed, key=lambda s: abs(s[0] - px) + abs(s[1] - py))
        assigned[i] = True
        acts[i] = ["DROP"] if (px, py) == target else _step_toward(positions[i], target)

    # -------------------------------------------------------------- dispatch
    # Territory, not free-for-all. Assigning every job to the globally nearest unit
    # makes units thrash: assignments flip as they move and they spend the day
    # walking past each other. Instead each unit owns a contiguous vertical strip and
    # works it nearest-first, which is a greedy TSP tour over a small area.
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
        best, best_key = None, None
        # Distance dominates and priority only breaks ties: movement is the scarce
        # resource, and a unit's own strip is small enough to finish in a day anyway.
        for pool in (mine[i], jobs):
            for job in pool:
                cell = (job[1], job[2])
                if cell in taken:
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
    for item in PRODUCTS:
        held = shed.get(item, 0)
        if held > 0:
            market.append(["SELL", item, held])

    n_extra = len(me["unlocked_quadrants"]) - 1
    if n_extra < len(LAND_PRICES):
        cost = LAND_PRICES[n_extra]
        # Land needs time to earn back: ~25 tiles at roughly $15/tile/day.
        if money >= cost + 400 and day <= 22:
            market.append(["BUY_LAND"])

    # Melon seed first -- it is the scarce, high-value allocation; the staple soaks up
    # whatever tiles are left over.
    if melon_wanted > 0:
        have = seeds.get("MELON", 0)
        spare = int(money) - 600
        if have < melon_wanted and spare > 0:
            buy = min(melon_wanted - have, spare // CROPS["MELON"]["seed"])
            if buy > 0:
                market.append(["BUY_SEED", "MELON", buy])

    if staple is not None:
        want = min(len(empty) + 4, 40)
        have = seeds.get(staple, 0)
        spare = int(money) - 300
        if have < want and spare > 0:
            buy = min(want - have, spare // CROPS[staple]["seed"])
            if buy > 0:
                market.append(["BUY_SEED", staple, buy])

    # Hiring is wildly underpriced (fib costs: 10 hands = $143 for 240 extra actions).
    # Scale the crew to the amount of workable land.
    target_hands = max(2, min(12, unlocked_tiles // 8))
    if hour <= 3 and me["hires_today"] < target_hands:
        room = MAX_ORDERS - len(market)
        for _ in range(min(target_hands - me["hires_today"], max(0, room))):
            market.append(["HIRE"])

    return {
        "farmer": acts[0],
        "hands": acts[1:],
        "market": market[:MAX_ORDERS],
    }
