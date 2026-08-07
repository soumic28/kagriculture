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
    "WHEAT":      {"seed": 10,  "first": 2,  "maxday": 4,  "maxyield": 6, "ongoing": False},
    "CARROT":     {"seed": 20,  "first": 2,  "maxday": 3,  "maxyield": 4, "ongoing": False},
    "MELON":      {"seed": 80,  "first": 10, "maxday": 12, "maxyield": 6, "ongoing": False},
    "TOMATO":     {"seed": 50,  "first": 8,  "maxday": 8,  "maxyield": 4, "ongoing": True, "interval": 1},
    "STRAWBERRY": {"seed": 100, "first": 10, "maxday": 10, "maxyield": 4, "ongoing": True, "interval": 2},
}

# Target share of workable tiles per crop.
#
# Every product has its OWN price curve with its own glut ceiling, so volume spread
# across products earns far more than the same volume in one. Summed ceilings are
# ~$119k against melon's ~$26k alone -- and ranked replays bear it out: the agents
# beating us run every crop plus livestock (one scored 106,946 with eight products on
# the board) while our melon-and-wheat monoculture topped out around 60k.
#
# Shares are set so each crop's season output lands near its own ceiling rather than
# past it: melon saturates at ~300 units, strawberry at only ~62, wheat effectively
# never. Wheat also doubles as animal feed.
CROP_MIX = {
    "MELON":      float(_env("KAG_MIX_MELON", 0.26)),
    "WHEAT":      float(_env("KAG_MIX_WHEAT", 0.22)),
    "CARROT":     float(_env("KAG_MIX_CARROT", 0.18)),
    "TOMATO":     float(_env("KAG_MIX_TOMATO", 0.20)),
    "STRAWBERRY": float(_env("KAG_MIX_STRAWBERRY", 0.14)),
}

# Sustainable demand, in units the town removes from the market per day once all
# shops are open (shops take 1 per 4 turns each, single-product shops double; the
# town centre takes 1 per 12 turns, x4 after day 20):
#
#   MILK 26/day x $160 = $4,160     STRAWBERRY 32/day x $120 = $3,840
#   WOOL 20/day x $200 = $4,000     MELON       8/day x $250 = $2,000
#   TOMATO 20 x $60 = $1,200        EGG 20 x $50 = $1,000
#   WHEAT 38 x $25 = $950           CARROT 26 x $35 = $910    FERTILIZER 0
#
# Because the town drains faster than either player sells, these markets *inflate*:
# in a ranked episode strawberry ran 120 -> 256, milk 160 -> 303, wool 200 -> 245 by
# day 22. Melon is the opposite -- no shop demands it, so it only ever falls.
#
# Hence two phases, copied from the strongest farm observed (199,688):
#   phase 1, to day ~11: melon only. It is the one crop that pays before day 10, and
#            its whole value is the opening race.
#   phase 2, after the melon harvest: strawberry plus cattle and sheep, i.e. the three
#            highest sustainable-demand goods, sold into a rising market.
PHASE1_END = int(_env("KAG_PHASE1_END", 7))
# Opening: melon and wheat only -- both cheap and fast, and melon is the one crop
# that pays before day 10. On 25 tiles this is 12 melon and 7 wheat, matching every
# top farm observed. Strawberry seed is $100 and yields nothing until day 10, so
# sowing it now simply empties the bank (we measured $10 left on day 0, plants dying
# by day 8, and no cows all season).
PHASE1_MIX = {
    "MELON": float(_env("KAG_P1_MELON", 0.48)),
    "WHEAT": float(_env("KAG_P1_WHEAT", 0.28)),
}
# From day 8, funded by the melon harvest: strawberry becomes the bulk of the farm,
# with melon and wheat held at the counts the top agents keep.
PHASE2_MIX = {
    "STRAWBERRY": float(_env("KAG_P2_STRAWBERRY", 0.42)),
    "MELON":      float(_env("KAG_P2_MELON", 0.12)),
    "WHEAT":      float(_env("KAG_P2_WHEAT", 0.07)),
    "CARROT":     float(_env("KAG_P2_CARROT", 0.0)),
    "TOMATO":     float(_env("KAG_P2_TOMATO", 0.0)),
}
# ON by default. An earlier all-in-melon version of this idea lost, but that was the
# wrong opening, not the wrong idea: sequencing is what the top farms actually do.
# Melon and wheat fund days 0-7, then the melon harvest pays for the strawberry block
# and the full herd. Sowing strawberry from day 0 instead empties the bank ($10 left
# on day 0, plants dying by day 8, no cows all season) -- the mix was never the
# problem, the order was. Measured 10/10 head-to-head, 113,907 against 88,789.
PHASED = int(_env("KAG_PHASED", 1))


# Base sale price per crop, used to read how far a market has moved from its start.
CROP_BASE = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 250}

# How hard to tilt the tile allocation toward crops whose price has risen. 0 keeps the
# fixed shares; 1 makes a crop trading at twice its base price get twice the tiles.
#
# This is what lets the farm follow the market instead of a plan. Wheat climbs to
# ~$55 late (38/day of town demand and almost nobody grows it) while melon and
# strawberry crash as both farms dump -- the strongest ranked agent converts a third
# of its tiles to wheat over days 22-28 for exactly this reason.
PRICE_ALPHA = float(_env("KAG_PRICE_ALPHA", 0.0))


def _crop_mix(day, prices=None):
    base = CROP_MIX
    if PHASED:
        base = PHASE1_MIX if day <= PHASE1_END else PHASE2_MIX
    if not PRICE_ALPHA or not prices:
        return base
    # Weight each share by how far its price sits above or below base, then renormalise
    # so the total tile demand is unchanged.
    tilted = {}
    for crop, share in base.items():
        ratio = prices.get(crop, CROP_BASE.get(crop, 1)) / float(CROP_BASE.get(crop, 1))
        tilted[crop] = share * (max(0.05, ratio) ** PRICE_ALPHA)
    total = sum(tilted.values()) or 1.0
    scale = sum(base.values()) / total
    return {c: v * scale for c, v in tilted.items()}

PRODUCTS = (
    "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
    "EGG", "MILK", "WOOL", "FERTILIZER",
)

MAX_ORDERS = 10
# Fallbacks only. The real season length is read from the configuration the framework
# passes as the agent's second argument -- hard-coding 30 days meant a shorter episode
# was played with crops that could never ripen (a 360-step season scored 998).
SEASON_DAYS = 30
LAST_DAY = SEASON_DAYS - 1


def _season_last_day(config):
    """Final 0-indexed day of the season, from configuration where available."""
    try:
        steps = int(config["episodeSteps"])
        per_day = max(1, int(config["turnsPerDay"]))
        return max(0, (steps // per_day) - 1)
    except Exception:
        return LAST_DAY
LAND_PRICES = (1000, 2000, 4000)

# Job priorities. Watering inside the bonus window outranks harvesting so a plant
# collects its final unit before being pulled. Distance dominates dispatch, so these
# mostly act as tie-breaks within a unit's own strip.
# Jobs at or above this are *urgent*: skipping one today causes permanent loss, not
# just a smaller harvest. An animal dies after two consecutive unfed days ($400-500
# gone) and a plant becomes a weed after two unwatered days. Dispatch normally lets
# distance dominate, which meant a nearby watering job outranked a distant feed and
# over half the herd starved between day 16 and day 22.
P_URGENT = 20
# 1 lets life-or-death jobs outrank distance; 0 keeps pure distance-first dispatch.
URGENCY = int(_env("KAG_URGENCY", 0))
# 1 counts animals walking to their pen against the herd target; 0 ignores them.
# 0 by default, and it is not an oversight: not counting them over-buys slightly,
# and that surplus is a buffer against the animals still lost to missed feeds.
# Measured 5/8 ahead of the 'correct' accounting.
COUNT_CARRIED = int(_env("KAG_COUNT_CARRIED", 0))
# Buy wheat from the market to keep the feed store stocked.
BUY_FEED = int(_env("KAG_BUY_FEED", 1))
# Spare pens beyond the herd target. Cows and sheep share pastures and we
# deliberately over-buy as a death buffer, so without slack the cows (bought first)
# occupy pens the sheep were counted for.
PEN_BUFFER = int(_env("KAG_PEN_BUFFER", 4))
# Cash never spent on seed. Running the bank to zero mid-season blocks feed buying
# and livestock exactly when the herd is scaling, and the elite farms sit on
# ~$14k at day 12 while we were hitting $0.
CASH_FLOOR = int(_env("KAG_CASH_FLOOR", 300))

# Base price of every sellable product, used to tell a depressed market from a
# healthy one.
PRODUCT_BASE = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
                "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100}
# Hold stock back while its price is under this fraction of base. The town keeps
# draining inventory every turn, so a crashed market recovers on its own -- dumping
# into the floor converts goods to almost nothing. 0 disables the hold.
SELL_MIN_RATIO = float(_env("KAG_SELL_MIN_RATIO", 0.0))
P_FEED_URGENT = 21
P_WATER_URGENT = 20

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

# Livestock. Every animal yields 1 fertilizer/day whether or not it was fed or cared
# for, and CARE banks a bonus paid out on the next scheduled production -- so a
# fed-and-cared animal produces (1 + interval) units per cycle.
LIVESTOCK = {
    "GOOSE": {"cost": 300, "struct": "COOP",    "build": "BUILD_COOP",    "product": "EGG",  "first": 4},
    "COW":   {"cost": 400, "struct": "PASTURE", "build": "BUILD_PASTURE", "product": "MILK", "first": 8},
    "SHEEP": {"cost": 500, "struct": "PASTURE", "build": "BUILD_PASTURE", "product": "WOOL", "first": 6},
}

# Days of production a capital purchase needs before it repays itself. Used to stop
# buying land or livestock that the remaining season cannot pay back -- on a short
# episode the old fixed day-20/day-22 cutoffs happily bought both and lost money.
LAND_PAYBACK_DAYS = 8
ANIMAL_PAYBACK_DAYS = 5

# Wheat kept in the shed as animal feed rather than sold.
FEED_RESERVE_PER_ANIMAL = 2
# Wheat a unit picks up per feed run. Each run is a shed round-trip, so carrying more
# per trip is what makes a large herd affordable in actions.
FEED_CARRY = int(_env("KAG_FEED_CARRY", 6))
# 0 feeds every day; 1 feeds only when the animal would otherwise starve (it dies on
# two consecutive missed days). Skipping a day costs the banked CARE bonus on that
# cycle but not the base yield, and fertilizer accrues either way -- so for a herd kept
# mainly for fertilizer, thrift buys back a lot of actions.
FEED_THRIFT = int(_env("KAG_FEED_THRIFT", 0))
# Likewise for CARE: it only pays on a day the animal is also fed.
CARE_ENABLED = int(_env("KAG_CARE", 1))

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
# A small flock pays, but only alongside a diversified crop mix -- the trade flipped
# once tiles stopped being a melon monoculture. Under monoculture a melon tile
# returned ~$150 per unit-action against a goose's ~$25 and birds lost outright; with
# the mix in place they open two markets nothing else reaches (egg is logarithmic and
# effectively never gluts, and fertilizer accrues 1/animal/day whether or not the
# animal was fed or cared for).
#
# Measured at 5 episodes: 4 birds 68,600, 6 birds 64,491, none 64,059 -- and 12 birds
# collapses to ~41,000, where feed round-trips and $300/head crowd out the crops.
#
# Head count per species. Cow and sheep are pricier and slower to first yield, but
# milk and wool are two more untouched markets, and the ranked leaders run ~10 cows.
# Each animal also adds a daily fertilizer, which sells near $100 early.
# Swept: 4/8/6 scored 83,712 against 78,674 for 4/4/3 and 65,102 for 8/8/6. Cow-heavy
# and goose-light, which independently matches the profile of the strongest agent seen
# in ranked replays (COW:10 SHEEP:8 GOOSE:4). Geese are the cheapest head but eat a
# feed run each; cows yield 3 milk per 2 days once cared for.
# Milk and wool are the two best sustainable markets ($4,160 and $4,000/day of town
# demand), so cattle and sheep are the engine, not a side bet. Geese are dropped by
# default: egg is only $1,000/day of demand and each bird still costs a feed run.
# The strongest ranked farm observed ran COW:13 SHEEP:10 and no geese at all.
# Swept: 0/8/6 scored 98,977 against 77,852 for 0/8/10. Geese lose at every setting
# tested -- egg is only ~$1,000/day of town demand against milk's $4,160 and wool's
# $4,000, and each bird still costs a daily feed run. Bigger herds lose too: past
# ~14 head the feed round-trips and the $400-500 apiece crowd out the crops.
HERD = {
    "GOOSE": int(_env("KAG_N_GOOSE", 0)),
    "COW":   int(_env("KAG_N_COW", 8)),
    "SHEEP": int(_env("KAG_N_SHEEP", 6)),
}
# Livestock buying stops here: a bird needs 4 days to first lay, a cow 8.
HERD_LAST_DAY = int(_env("KAG_HERD_LAST_DAY", 20))
# Cash floor kept clear of livestock spending, so seed and land are never starved.
HERD_MIN_MONEY = int(_env("KAG_HERD_MIN_MONEY", 1200))
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



def _melon_target(day, unlocked_tiles, money, melon_price, rival_melon, last_day):
    """How many tiles should be carrying melon right now.

    Melon is worth roughly 14x wheat per unit and *fewer* actions per tile-day, but
    its glut curve is quadratic: past ~158 units sold it pins to the $1 floor for the
    rest of the season, and no town shop demands melon to drain the surplus. So the
    tile count is chosen to land near that ceiling across two waves, not maximised.

    Day 0 is deliberately wheat-only: melon locks a tile for 11 days with no income,
    and the opening needs cash for land and crew.
    """
    if day + CROPS["MELON"]["maxday"] > last_day:
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


def _herd_target(day, money, have, last_day):
    """Head count wanted per species right now, as {animal: n}.

    Livestock opens four markets crops cannot reach -- egg, milk, wool and the daily
    fertilizer every animal drops regardless of care. Egg and fertilizer curves are
    gentle; milk and wool glut fast (floors at 76 and 59 units) so their herds stay
    small and are really there for the fertilizer and the untouched early price.

    Never shrinks below what is already standing: an animal is a sunk $300-500 and
    keeps producing, so a temporary cash dip must not read as "sell the herd".
    """
    if money < HERD_MIN_MONEY:
        return dict(have)
    # No pens during the melon opening. Pens are allocated before crops, so a herd
    # plan of 23 head would claim 23 of the 25 opening tiles and leave nothing to
    # plant -- and the animals are unaffordable until the melon money lands anyway.
    if PHASED and day <= PHASE1_END:
        # A seed herd only. The top farms run 2 cows and 2 sheep from day 2, which
        # starts milk on day 10, but a full herd here would take the pens and the cash
        # that the opening melon needs.
        seed_herd = {"GOOSE": 0, "COW": 2, "SHEEP": 2}
        return {a: max(seed_herd.get(a, 0), have.get(a, 0)) for a in LIVESTOCK}
    # Only stock a species that still has time to produce: a cow needs 8 days to
    # first milk, so buying one near the end is a pure loss.
    out = {}
    for a, spec in LIVESTOCK.items():
        standing = have.get(a, 0)
        ripe_in_time = day + spec["first"] + ANIMAL_PAYBACK_DAYS <= last_day
        out[a] = max(HERD.get(a, 0), standing) if ripe_in_time else standing
    return out


def agent(obs, config=None):
    """Entry point. Must never raise and must never be slow.

    A thrown exception or a call over `actTimeout` forfeits the turn, and with 720
    turns an episode is lost to a single bad observation. Everything below degrades to
    a legal no-op rather than propagating, and the hand list is still sized correctly
    so the fallback stays a valid action.
    """
    try:
        return _decide(obs, config)
    except Exception:
        n_hands = 0
        try:
            n_hands = len(obs["farms"][obs["player"]].get("hands") or [])
        except Exception:
            pass
        return {"farmer": ["PASS"], "hands": [["PASS"]] * n_hands, "market": []}


def _decide(obs, config=None):
    player = obs.get("player", 0)
    farms = obs.get("farms") or []
    if not farms or player >= len(farms):
        return {"farmer": ["PASS"], "hands": [], "market": []}
    me = farms[player]
    priv = obs.get("private") or {}
    last_day = _season_last_day(config)
    day = obs.get("day", 0)
    hour = obs.get("hour", 0)
    money = me.get("money", 0)
    tiles = me.get("tiles") or []
    n = len(tiles)
    if n == 0:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    seeds = priv.get("seeds") or {}
    shed = priv.get("shed") or {}
    invs = priv.get("inventories") or []

    # Board size is read from the observation rather than assumed, so a non-default
    # boardSize still works: shed-access tiles and quadrants are derived from `n`.
    positions = [list(me["farmer"])] + [list(p) for p in (me.get("hands") or [])]
    n_units = len(positions)
    acts = [["PASS"] for _ in range(n_units)]

    prices = (obs.get("market") or {}).get("prices") or {}

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
    grown = {}         # crop -> tiles currently carrying it
    herd = {}          # animal -> head standing
    structures = {}    # "COOP"/"PASTURE" -> built count
    open_pens = {}     # "COOP"/"PASTURE" -> [cells] built but unoccupied
    animal_count = 0   # total head, drives the wheat feed reserve
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
                grown[crop] = grown.get(crop, 0) + 1
                age = day - t["planted_day"]
                watered = t["watered_today"]
                units = t["yield_units"]
                # Ongoing crops (tomato, strawberry) get no watering bonus and are not
                # pulled on harvest -- they keep producing on a schedule, so take the
                # fruit the moment it appears and leave the plant standing.
                if c["ongoing"]:
                    in_window = False
                    ripe = units > 0 and age >= c["first"]
                else:
                    in_window = _window_start(crop) <= age <= c["maxday"]
                    ripe = age >= c["first"] and units > 0 and (
                        units >= c["maxyield"] or age >= c["maxday"]
                    )
                if in_window and not watered:
                    jobs.append((P_WATER_BONUS, x, y, ["WATER"]))
                elif ripe:
                    jobs.append((P_HARVEST, x, y, ["HARVEST"]))
                elif not watered and t["consecutive_unwatered"] >= 1:
                    jobs.append((P_WATER_URGENT if URGENCY else P_WATER_SURVIVE, x, y, ["WATER"]))
            elif kind in ("COOP", "PASTURE"):
                structures[kind] = structures.get(kind, 0) + 1
                if "animal" not in t:
                    open_pens.setdefault(kind, []).append((x, y))
                    continue
                herd[t["animal"]] = herd.get(t["animal"], 0) + 1
                animal_count += 1
                # Feeding is what keeps the animal alive (two missed days and it is
                # gone) and it also unlocks the banked CARE bonus. Harvest before
                # yield_units reaches max_held or production is wasted.
                hungry = not t["fed_today"] and (
                    not FEED_THRIFT or t["consecutive_unfed"] >= 1
                )
                if hungry:
                    unfed.add((x, y))
                    starving = t["consecutive_unfed"] >= 1
                    jobs.append((P_FEED_URGENT if (URGENCY and starving) else P_FEED, x, y, ["FEED"]))
                if t["yield_units"] > 0:
                    jobs.append((P_HARVEST, x, y, ["HARVEST"]))
                if t["fertilizer_available"]:
                    jobs.append((P_FERT, x, y, ["COLLECT_FERTILIZER"]))
                # CARE only banks a bonus on a day the animal is also fed.
                if CARE_ENABLED and not t["cared_today"] and (
                    t["fed_today"] or hungry
                ):
                    jobs.append((P_CARE, x, y, ["CARE"]))

    # Decide how many tiles each crop should hold, then fill the gaps. Crops are
    # ordered by how badly they are under quota so no single crop monopolises a burst
    # of free tiles.
    deficits = []
    for crop, share in _crop_mix(day, prices).items():
        c = CROPS[crop]
        # Nothing that cannot reach its first yield before the season ends. For the
        # ongoing crops, insist on the *whole* cycle: strawberry fruits at ages 10,
        # 12, 14 and 16, so one sown after day 13 can never finish, and the tile is
        # worth more under a fast crop. Sowing them to the first-yield deadline was
        # why strawberry averaged 2.4 units a plant instead of 4.
        span = c["first"]
        if c["ongoing"]:
            span += (c["maxyield"] - 1) * c.get("interval", 1)
        if day + span > last_day:
            continue
        if crop == "MELON" and not PHASED:
            target = _melon_target(day, unlocked_tiles, money,
                                   prices.get("MELON", 250), rival_melon, last_day)
        else:
            target = int(unlocked_tiles * share)
        # A crop already at the $1 floor is worth less than bare dirt.
        if prices.get(crop, 99) <= 2:
            target = 0
        gap = target - grown.get(crop, 0)
        if gap > 0:
            deficits.append((gap, crop))
    deficits.sort(reverse=True)

    # How many pens of each kind the herd plan needs beyond what already exists.
    # Geese need coops; cows and sheep share pastures.
    want_herd = _herd_target(day, money, herd, last_day)
    need_pen = {}
    for animal, n_want in want_herd.items():
        if not n_want:
            continue
        kind = LIVESTOCK[animal]["struct"]
        need_pen[kind] = need_pen.get(kind, 0) + n_want
    if PEN_BUFFER:
        for kind in list(need_pen):
            need_pen[kind] += PEN_BUFFER
    pen_slots = {k: max(0, v - structures.get(k, 0)) for k, v in need_pen.items()}

    # Pens go on the tiles closest to the shed: every animal needs a wheat delivery
    # from the shed every day, so feed-run distance is a recurring cost, unlike a
    # crop tile which is only visited by its own strip's unit.
    mid = (n - 1) / 2.0
    pen_sites = {}
    total_pens = sum(pen_slots.values())
    if total_pens:
        near = sorted(empty, key=lambda c: abs(c[0] - mid) + abs(c[1] - mid))
        i = 0
        for kind, count in pen_slots.items():
            for cell in near[i:i + count]:
                pen_sites[cell] = kind
            i += count

    # Allocate every free tile to a purpose first, independent of the seed actually in
    # hand, so seed buying can be driven by the real plan. Otherwise an all-melon
    # opening still buys a stack of wheat seed for tiles that will never take it.
    plan = []
    queue = [[gap, crop] for gap, crop in deficits]
    for x, y in empty:
        if (x, y) in pen_sites:
            plan.append((x, y, pen_sites[(x, y)]))
            continue
        # Round-robin over the under-quota crops, worst deficit first, so a batch of
        # freed tiles gets spread across the mix instead of going to one crop.
        pick = next((q for q in queue if q[0] > 0), None)
        if pick is None:
            break
        pick[0] -= 1
        plan.append((x, y, pick[1]))
        queue.sort(reverse=True)

    # Emit work only where the seed exists: the env drops *all* PLANT requests for a
    # crop when they exceed supply, so a single over-request wastes the whole turn.
    on_hand = {crop: seeds.get(crop, 0) for crop in CROPS}
    demand = {}
    for x, y, what in plan:
        if what in ("COOP", "PASTURE"):
            jobs.append((P_BUILD, x, y,
                         ["BUILD_COOP" if what == "COOP" else "BUILD_PASTURE"]))
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
    endgame = day >= last_day and hour >= 8
    closing = day >= last_day and hour >= 14
    if closing:
        jobs = [j for j in jobs if j[3][0] in ("HARVEST", "DIG")]
    if day >= last_day and hour >= 20:
        jobs = []

    shed_wheat = shed.get("WHEAT", 0)
    # Free pens per structure kind, and the animals waiting in the shed for one.
    pens_free = {k: list(v) for k, v in open_pens.items()}
    shed_stock = {a: shed.get(a, 0) for a in LIVESTOCK}
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
        my_unfed = sum(1 for c in unfed if owner.get(c) == i)

        # 1. Carrying an animal: it is worth $300-500 and earns nothing until it is
        #    housed, and it only goes onto a pen of its own kind. Prefer one on this
        #    unit's own patch, but house it anywhere rather than carry it all day.
        carried = next((a for a in LIVESTOCK if inv.get(a, 0) > 0), None)
        if carried:
            kind = LIVESTOCK[carried]["struct"]
            free = pens_free.get(kind) or []
            if free:
                pool = [c for c in free if owner.get(c) == i] or free
                target = min(pool, key=lambda c: abs(c[0] - px) + abs(c[1] - py))
                free.remove(target)
                assigned[i] = True
                acts[i] = (["PLACE", carried] if (px, py) == target
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

        # 3. Fetch an animal from the shed for an empty pen on this unit's own patch.
        fetch = next(
            (a for a in LIVESTOCK
             if shed_stock.get(a, 0) > 0
             and any(owner.get(c) == i for c in pens_free.get(LIVESTOCK[a]["struct"], []))),
            None,
        )
        if fetch:
            shed_stock[fetch] -= 1
            _shed_run(i, ["PICKUP", fetch, 1])
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
                key = (0 if (URGENCY and job[0] >= P_URGENT) else 1,
                       abs(px - job[1]) + abs(py - job[2]), -job[0])
                if best_key is None or key < best_key:
                    best, best_key = job, key
            if best is not None:
                break   # only range beyond the home strip when it is fully clear
        if best is None:
            continue
        taken.add((best[1], best[2]))
        assigned[i] = True
        # best_key is (urgent_flag, distance, -priority) -- distance is element 1.
        # Reading element 0 here silently turned every non-urgent job into an endless
        # walk and fired urgent ones as no-ops from across the farm.
        on_tile = best_key[1] == 0
        acts[i] = best[3] if on_tile else _step_toward(positions[i], (best[1], best[2]))

    # ---------------------------------------------------------------- market
    market = []

    # Only 10 market orders clear per turn and the rest are silently dropped, so slots
    # are a real budget. A HIRE buys 24 unit-actions for a few dollars -- far and away
    # the best value per slot -- but sell orders are one *per product*, and after the
    # end-of-day drop nine products can hold stock and swallow the entire queue,
    # leaving nothing for hiring. So reserve the morning's hiring slots up front.
    target_hands = max(2, min(HAND_CAP, unlocked_tiles // HAND_DIV))
    hire_need = max(0, target_hands - me["hires_today"]) if hour <= 3 else 0
    sell_budget = max(2, MAX_ORDERS - min(hire_need, 6) - 2)

    # Wheat is the one product that is also a consumable -- animals eat it out of the
    # shed -- so hold a reserve back rather than selling the flock's dinner. On the
    # final day the herd has no future left to feed, and unsold wheat scores nothing,
    # so the reserve is released.
    reserve = 0 if day >= last_day else animal_count * FEED_RESERVE_PER_ANIMAL
    # Room left in the shed. Once it is tight, hold-backs stop: overflow at the
    # end-of-day drop is discarded outright, which is worse than a poor price.
    shed_used = sum(v for v in shed.values() if v > 0)
    tight = shed_used > 70 or day >= last_day - 1

    sellable = []
    for item in PRODUCTS:
        held = shed.get(item, 0)
        if item == "WHEAT":
            held -= reserve
        if held <= 0:
            continue
        price = prices.get(item, 1)
        if (SELL_MIN_RATIO and not tight
                and price < SELL_MIN_RATIO * PRODUCT_BASE.get(item, price)):
            continue      # depressed; let town demand pull the price back up
        sellable.append((held * price, item, held))
    # Highest-value stock first, so a capped queue still books the money that matters.
    sellable.sort(reverse=True)
    for _value, item, held in sellable[:sell_budget]:
        market.append(["SELL", item, held])

    # Hire before the remaining buys: the hands work all day, whereas a seed bought a
    # turn later costs almost nothing.
    for _ in range(hire_need):
        if len(market) >= MAX_ORDERS:
            break
        market.append(["HIRE"])

    n_extra = len(me["unlocked_quadrants"]) - 1
    if n_extra < len(LAND_PRICES):
        cost = LAND_PRICES[n_extra]
        # Land needs time to earn back, but during the melon opening it is strictly
        # worse than seed: an extra quadrant sits idle until the harvest pays, whereas
        # $1,000 is twelve more melon plants that all mature on day 10. Buy after the
        # melon money lands, not before.
        if (money >= cost + 400
                and day + LAND_PAYBACK_DAYS <= last_day
                and (not PHASED or day > PHASE1_END)):
            market.append(["BUY_LAND"])

    # Buy exactly what the tile plan calls for. Melon goes first -- it is the scarce,
    # high-value allocation and during the opening race it takes priority over the
    # cash buffer entirely.
    # Melon goes first -- during the opening race it takes priority over the cash
    # buffer entirely. Order the rest by seed cost so a cheap crop is never blocked
    # behind an unaffordable one, and cap the orders so market slots stay free for
    # selling and hiring.
    opening = day <= MELON_OPENING_DAYS
    order = ["MELON"] + sorted((c for c in CROPS if c != "MELON"),
                               key=lambda c: CROPS[c]["seed"])
    for crop in order:
        if len(market) >= MAX_ORDERS - 2:
            break
        want = demand.get(crop, 0)
        if not want:
            continue
        reserve = (100 if opening else max(600, CASH_FLOOR)) if crop == "MELON" else CASH_FLOOR
        have = seeds.get(crop, 0)
        spare = int(money) - reserve
        if want > have and spare > 0:
            buy = min(want - have, spare // CROPS[crop]["seed"])
            if buy > 0:
                market.append(["BUY_SEED", crop, buy])

    # Top the feed store up from the market rather than relying on our own wheat.
    # An animal is $400-500 plus its daily production; wheat is $25-55, so buying
    # insurance against a missed feed is cheap. BUY_PRODUCT lands in the shed and
    # silently fails when the shed is full, which is why produce is sold every turn.
    if BUY_FEED and animal_count and len(market) < MAX_ORDERS - 1:
        short_feed = animal_count * FEED_RESERVE_PER_ANIMAL - shed.get("WHEAT", 0)
        if short_feed > 0 and money > 800:
            price = max(1, prices.get("WHEAT", 25))
            buy = min(short_feed, int((money - 800) // price))
            if buy > 0:
                market.append(["BUY_PRODUCT", "WHEAT", buy])

    # Stock each empty pen, cheapest species first so a goose is never blocked behind
    # an unaffordable cow. BUY_ANIMAL lands in the shed and silently fails when the
    # shed is at capacity, which is why produce is sold off every turn.
    #
    # Pens are counted per structure kind, but cows and sheep share pastures -- so
    # only buy up to this species' own shortfall, or one species would take every pen.
    if True:
        pen_budget = {k: len(v) for k, v in pens_free.items()}
        # Order by how soon the animal starts producing, not by price. Cows and
        # sheep share pastures, so buying cheapest-first let cows claim every pen
        # as it was built and sheep waited on cash -- sheep reached only 53% of
        # their possible animal-days against the cows' 98%. Sheep first-yield on
        # day 6 against a cow's day 8, and wool is worth $4,000/day of town demand
        # against milk's $4,160, so the cheaper animal was not the better buy.
        for animal in sorted(LIVESTOCK, key=lambda a: (LIVESTOCK[a]["first"],
                                                       LIVESTOCK[a]["cost"])):
            if len(market) >= MAX_ORDERS - 1:
                break
            kind = LIVESTOCK[animal]["struct"]
            # Count animals already in transit in a unit's hands as well as those
            # standing and those in the shed, or we keep re-buying stock that is
            # simply walking to its pen (17 head bought against a target of 14).
            carried_n = sum((iv or {}).get(animal, 0) for iv in invs) if COUNT_CARRIED else 0
            short = (want_herd.get(animal, 0) - herd.get(animal, 0)
                     - shed.get(animal, 0) - carried_n)
            room = min(short, pen_budget.get(kind, 0))
            if room <= 0:
                continue
            afford = int(money - 400) // LIVESTOCK[animal]["cost"]
            buy = min(room, afford)
            if buy > 0:
                market.append(["BUY_ANIMAL", animal, buy])
                pen_budget[kind] -= buy

    # Any hires that did not fit the reserved slots above can use whatever is left.
    if hour <= 3:
        placed = sum(1 for o in market if o[0] == "HIRE")
        for _ in range(max(0, hire_need - placed)):
            if len(market) >= MAX_ORDERS:
                break
            market.append(["HIRE"])

    return {
        "farmer": acts[0],
        "hands": acts[1:],
        "market": market[:MAX_ORDERS],
    }
