"""Pure fixed-point POOLER.SQL state machine; no Badgeware imports.

THE THEME IS THE CONNECTION POOLER, and it is the mechanic rather than a coat
of paint over one.  The player IS a client connection.  The obstacles are the
pool's PIPES, and the gap between an upper and a lower pipe is the one route
through.  Clearing a pipe pair is a QUERY SERVED.  Gravity is the idle timer
reclaiming a connection that has stopped talking, and the tap that lifts the
client is a KEEPALIVE — stop tapping and the connection sinks and is dropped,
which is exactly what an idle pooled connection does.  Contact with a pipe, the
floor or the ceiling is the pool refusing you: POOL EXHAUSTED.

Every length in this file and in the state it builds is in 1/16-pixel units
(``UNIT``) unless a name or comment says ``_px``.  Two reasons, both
load-bearing and both copied from `pong_model`: MicroPython floats on the
RP2350 are software and the render loop cannot afford them, and a float model
has no exact expected value, so every geometry test would have to carry a
tolerance.  Everything below is exact, so the tests assert equality.
"""


# ---- geometry ---------------------------------------------------------------
#
# The world is the 160x120 LORES panel minus the 16 px status strip, expressed
# in WORLD-LOCAL pixels.  The view adds its own Y_OFFSET; the model never knows
# the strip exists, which is what lets the whole file be tested without a
# screen.  104 px is Snake's and Pong's playfield height, so all three games
# put their world in the same place.
WORLD_W = 160
WORLD_H = 104

UNIT = 16

# The lethal boundaries, and the rails the view draws ON them.  A 2 px rail at
# the top and bottom of the world is drawn at exactly the y that kills, so what
# the player can see is what he can hit — a decorative rail inset from an
# invisible kill line is a lie the panel cannot correct.
RAIL = 2
CEILING = RAIL
FLOOR = WORLD_H - RAIL

# The client connection: an 8 px square, 3 mm on the panel at 0.375 mm/px.
# Square rather than tall so the same number bounds it in both axes and the
# collision test is four compares.
CLIENT = 8
# The client's x NEVER CHANGES.  The world scrolls past it, which is the
# original's arrangement and the reason there is no horizontal tunnelling case
# in this file at all.  24 px is far enough left that the NEXT pipe is fully on
# the panel while the client is flying through the current one — 24 + 112 + 14
# = 150 against a 160 px canvas — which is the one piece of information a
# player needs and cannot recover any other way.
CLIENT_X = 24

PIPE_W = 14
# Left edge to left edge, the same at every load.
#
# 112 px is set by the flap cycle, not by taste.  A keepalive rises for ten
# steps and falls back over ten more, so one cycle is 20 steps; the original
# gives its player between three and four cycles between pipes.  112 px buys
# 74 steps at level 1 (3.7 cycles) falling to 30 at level 9 (1.5), so the
# rhythm tightens with load as a CONSEQUENCE of the speed rather than as a
# third dial nobody asked for.  An 80 px spacing was tried first and level 8
# had 24 steps between pipes against a 20-step cycle — barely one flap of room,
# and the reachability fuzz failed on it.
PIPE_SPACING = 112
# Playable band kept clear of each rail, so a gap is never flush against a
# lethal edge and no level ever demands rail-hugging to pass.
GAP_MARGIN = 8
# Where the first pipe of a run is placed.  Off the right edge by half a
# spacing on top of the full width, so the opening runway is 192 px — 1.3 s
# even at the fastest level, on top of the ready hold below.
FIRST_PIPE_X = WORLD_W + PIPE_SPACING // 2

CLIENT_SUB = CLIENT * UNIT
CLIENT_X_SUB = CLIENT_X * UNIT
CLIENT_RIGHT_SUB = CLIENT_X_SUB + CLIENT_SUB
PIPE_W_SUB = PIPE_W * UNIT
PIPE_SPACING_SUB = PIPE_SPACING * UNIT
WORLD_W_SUB = WORLD_W * UNIT
CEILING_SUB = CEILING * UNIT
FLOOR_SUB = FLOOR * UNIT


# ---- flight -----------------------------------------------------------------
#
# Sub-pixels of downward velocity added per step, the velocity a keepalive
# SETS (not adds), and the terminal fall.  At STEP_MS = 25 that is 40 steps a
# second, so gravity is 400 px/s^2, a keepalive is 110 px/s of lift and the
# fall caps at 140 px/s.
#
# The shape those three make is the whole feel of the game, so here is the
# arithmetic.  A keepalive climbs 36+32+28+24+20+16+12+8+4 = 180 sub-pixels —
# 11.25 px — over ten steps (250 ms), then takes ten more to fall back: a
# 500 ms round trip, which is the original's.
#
# THE RATIO THAT MATTERS IS SLACK OVER CLIMB, and it is why FLAP is -40 rather
# than the -44 this was first written with.  The gap leaves 38 px of slack
# around the client at level 1 and 22 px at level 9; against an 11.25 px climb
# that is 3.4 and 1.96, and the original's own figure is about 2.05.  So level
# 1 is markedly more forgiving than the original and level 9 sits just inside
# it.  At -44 the climb was 13.75 px, level 9 came out at 1.6, and the
# reachability fuzz could not fly it at a human tap rate — which is the whole
# reason that fuzz exists.
GRAVITY = 4
FLAP = -40
MAX_FALL = 56

# THE MOVEMENT INTERVAL IS ABOVE THE FRAME PERIOD ON PURPOSE, and this is
# `pong_model`'s number for `pong_model`'s reason.  Snake's device frame is
# ~22.8 ms (43.8 fps measured); the browser runtime is faster.  An interval
# BELOW the frame period makes "at most one step per frame" the real limit, and
# the game then runs at whatever rate the platform renders.  25 ms is above
# both, so the world scrolls at the same rate on either and the e2e lane
# measures the same game the badge plays.
STEP_MS = 25

# Steps at the start of a run during which the world scrolls but gravity does
# not apply and the client holds its line.  16 steps is 400 ms.  Without it the
# client is already falling before a player at a booth has found it on the
# panel, and the first thing the game does is punish him for looking.  A
# keepalive ends the hold early, so it costs an eager player nothing.  This is
# `pong_model.SERVE_TICKS` doing the same job for the same reason.
READY_TICKS = 16


# ---- the ladder -------------------------------------------------------------
#
# LEVEL IS POOL LOAD, and load moves both dials: a pooler under load serves
# faster and has less room in it.  Nine rungs of scroll speed paired with nine
# of gap height, so level 9 is a different game rather than the same game sped
# up.  The intro says `A/C LOAD n` for that reason — "level" would name the
# ladder without naming what it does, and two dials moving together need the
# one word that explains why.
#
# Scroll is sub-pixels of world travel per step; each rung is roughly 11%
# faster than the one below, which is about the smallest speed change a hand
# reads as a different game.  Level 1 is 60 px/s and level 9 is 145 px/s.
MIN_LEVEL = 1
MAX_LEVEL = 9
LEVEL_SCROLL = (24, 27, 30, 34, 38, 42, 47, 52, 58)
# Gap height in PIXELS, 2 px a rung.  With an 8 px client that is 38 px of
# slack at level 1 and 22 px at level 9.
LEVEL_GAP = (46, 44, 42, 40, 38, 36, 34, 32, 30)

# Net sub-pixels of climb a player can bank per step while tapping at the
# reference cadence of one keepalive every five steps (125 ms, eight taps a
# second — brisk, and comfortably inside what a thumb does).  Five steps after
# a keepalive the velocities are -36 -32 -28 -24 -20, which is 140 sub-pixels
# up over five steps, so 28 per step.
CLIMB_SUB = 28

# The fraction of a gap's slack that ``reach`` is allowed to spend.  Two
# thirds, so consecutive gaps ALWAYS OVERLAP by at least a third of the slack —
# 7 px at level 9, 12 px at level 1.
#
# This is the bound that actually binds, and it was learned the hard way.  The
# first version bounded a gap's movement only by the climb budget, which at
# level 8 came out equal to the whole slack: two consecutive gaps could then
# touch at exactly one point, so the only surviving line through them was a
# single sub-pixel.  A player cannot fly that and neither could the autopilot.
# A budget that says "you could get there" is not the same as a shape that can
# be flown, and only the second one is worth generating.
OVERLAP_NUM = 2
OVERLAP_DEN = 3


def next_step_clock(now, last_step, interval, ticks_diff, ticks_add):
    """Return the next movement clock when due, otherwise ``None``.

    Advancing by the configured interval avoids quantising the interval to the
    render frame.  At most one movement is still emitted per app frame.  If a
    long hitch leaves a second full interval outstanding, reset to ``now`` so
    later frames do not replay a dangerous backlog.

    This is `snake_model.next_step_clock` verbatim and deliberately so: it is
    measured platform truth, it was paid for with device time, and a second
    slightly-different copy of a timing rule is how two apps end up disagreeing
    about what a hitch means.
    """
    deadline = ticks_add(last_step, interval)
    if ticks_diff(now, deadline) < 0:
        return None
    if ticks_diff(now, deadline) >= interval:
        return now
    return deadline


def beats_record(score, high_score):
    """Whether this run has just become the badge's best run.

    Gated on there being a record at all: beating a stored zero is not an
    achievement and must not be celebrated on a badge that has never been
    played.  ``update_high_score`` still persists such a run — this decides
    only whether to say so on screen.
    """
    return high_score > 0 and score > high_score


def clamp_level(level):
    """Levels are 1..9 and nothing else, wherever they arrive from."""
    return max(MIN_LEVEL, min(MAX_LEVEL, int(level)))


def level_scroll(level):
    """Sub-pixels of world travel per step at this level."""
    return LEVEL_SCROLL[clamp_level(level) - 1]


def level_gap(level):
    """Gap height in PIXELS at this level."""
    return LEVEL_GAP[clamp_level(level) - 1]


def pipe_steps(scroll):
    """Movement steps between one pipe's leading edge and the next's."""
    return PIPE_SPACING_SUB // scroll


def reach(scroll, gap):
    """Pixels a generated gap may move vertically from the one before it.

    ``gap`` is the gap HEIGHT in pixels; the slack the client actually has
    inside it is ``gap - CLIENT``.

    THIS IS THE REACHABILITY BUDGET AND IT IS DERIVED, NOT TASTED.  Between two
    pipes the client has ``pipe_steps`` steps, and at the reference tap cadence
    it banks ``CLIMB_SUB`` per step, so the raw climb available is
    ``pipe_steps * CLIMB_SUB / UNIT`` pixels.  Half of that is spent here and
    half is kept back, because the client also has to hold station inside the
    gap while ``PIPE_W + CLIENT`` = 22 px of pipe goes past it, and because
    descending — which gravity does for free at up to 3.5 px a step — must
    never be the constrained direction.

    THE SECOND BOUND IS THE ONE THAT BINDS ON EVERY SHIPPED RUNG, and it is
    about shape rather than budget: a gap may move at most ``OVERLAP_NUM /
    OVERLAP_DEN`` of its own slack, so consecutive gaps always share a third of
    it.  Without that, a level whose climb budget happens to equal its slack
    generates two gaps that touch at one point — reachable in principle,
    unflyable in fact.

    Worked at both ends of the ladder: level 9 has 30 steps between pipes, so
    a 30 px climb budget against a 14 px overlap bound; level 1 has 74 steps,
    a 74 px budget against a 25 px bound.  The budget is never the smaller,
    which `test_the_climb_budget_is_never_the_binding_bound` pins — if it ever
    became so, the ladder would have moved somewhere it was not intended to.

    The claim this arithmetic makes is proved rather than asserted:
    `test_flappy.ReachabilityTests` flies an autopilot limited to the same
    reference cadence through 40 pipes at every level, over many seeds.
    """
    budget = pipe_steps(scroll) * CLIMB_SUB // UNIT // 2
    slack = (gap - CLIENT) * OVERLAP_NUM // OVERLAP_DEN
    return min(budget, slack)


def gap_band(gap):
    """``(low, high)`` pixel bounds for a gap's top edge at this gap height."""
    return CEILING + GAP_MARGIN, FLOOR - GAP_MARGIN - gap


def place_gap(previous, gap, span, random_below):
    """Choose the next gap's top edge, in PIXELS.

    ``previous`` is the previous gap's top edge, or ``None`` for the first pipe
    of a run — which is centred on the client's starting line, so a run never
    opens by demanding a climb the player has not been given a reason to
    expect.

    Later gaps are drawn from ``[previous - span, previous + span]`` and then
    clamped into the band.  Clamping a candidate that is already within ``span``
    of ``previous`` can only move it TOWARDS ``previous`` — ``previous`` is
    itself inside the band, because it came out of this function — so the
    clamp can never widen the step it is there to bound.  That is the property
    `test_flappy.PlacementTests` pins, and it is why the reachability argument
    in ``reach`` survives contact with the edges of the panel.

    An absolute placement with no memory of the previous gap is the obvious
    alternative and it is the one this rejects: it would put a level-9 run one
    coin flip away from a 54 px jump against a 22 px budget, which is not
    difficulty, it is a run the player was never able to finish.
    """
    low, high = gap_band(gap)
    if high <= low:
        # Defensive only: no shipped level reaches it (the narrowest band is
        # 38 px).  Returning the top of the band beats raising on a badge.
        return low
    if previous is None:
        return max(low, min(high, WORLD_H // 2 - gap // 2))
    candidate = previous + random_below(2 * span + 1) - span
    return max(low, min(high, candidate))


def _spawn(state, x_sub, random_below):
    """Append one pipe pair at ``x_sub``, placed against the newest one."""
    pipes = state["pipes"]
    previous = pipes[-1][1] // UNIT if pipes else None
    gap = state["gap"] // UNIT
    top = place_gap(previous, gap, state["reach"], random_below)
    # A pipe is ``[x, gap_top, served]``: x and gap_top in sub-pixels like
    # every other length in the state, and a flag so one pipe pays once.
    pipes.append([x_sub, top * UNIT, False])
    return pipes[-1]


def new_game(level, random_below):
    level = clamp_level(level)
    scroll = level_scroll(level)
    state = {
        "level": level,
        # Both cached because every step reads them, and both are fixed for the
        # life of the run: the level is read once, at the intro, so a run's
        # geometry cannot change under a player who is mid-flight.
        "scroll": scroll,
        "gap": level_gap(level) * UNIT,
        "reach": reach(scroll, level_gap(level)),
        # The client's TOP edge.  Its x is a constant.
        "y": (WORLD_H // 2 - CLIENT // 2) * UNIT,
        "vy": 0,
        "pipes": [],
        "score": 0,
        "ready": READY_TICKS,
        "status": "playing",
        # Total world travel, so the view can scroll the floor's dashes at the
        # same rate as the pipes without keeping its own clock.
        "scrolled": 0,
        # Where the client was when the pool refused it, and what it hit.  The
        # finished screen re-draws the client in red at exactly this y, so the
        # frozen world answers "where did I lose it?" without a second marker.
        "fatal": None,
        "cause": None,
    }
    _spawn(state, FIRST_PIPE_X * UNIT, random_below)
    return state


def flap(state):
    """One keepalive.  Returns whether it was taken.

    The impulse SETS the velocity rather than adding to it, so a fast tapper
    cannot stack lift and climb faster than the ladder was designed around.
    That also makes the control honest: one tap is always exactly one 15 px
    climb, whatever the client was doing when it landed.

    A keepalive during the opening hold ends the hold, so an eager player is
    never made to wait out a window that exists for a hesitant one.
    """
    if state["status"] != "playing":
        return False
    state["vy"] = FLAP
    state["ready"] = 0
    return True


def collide(state):
    """What the client is touching, or ``None``.

    Public because it is a pure question about a position, and the fast lane
    asks it directly: driving a whole step to test a boundary would move the
    client before the boundary was examined, and the sub-pixel either side of a
    lethal edge is exactly what these tests are for.

    Rails first, then pipes.  There is no horizontal tunnelling case to guard:
    the client's x is a constant and the fastest pipe covers 3.6 px in a step
    against its own 14 px width, so a pipe can never step across the client.
    Vertically the client covers at most 3.5 px a step against pipe bodies that
    run from the gap to the edge of the world, so there is no thin surface to
    pass through either — which is why this is an overlap test and not the
    plane-crossing test `pong_model` needs.
    """
    y = state["y"]
    if y < CEILING_SUB:
        return "ceiling"
    if y + CLIENT_SUB > FLOOR_SUB:
        return "floor"
    gap = state["gap"]
    for pipe in state["pipes"]:
        x = pipe[0]
        if x + PIPE_W_SUB <= CLIENT_X_SUB or x >= CLIENT_RIGHT_SUB:
            continue
        top = pipe[1]
        if y < top or y + CLIENT_SUB > top + gap:
            return "pipe"
    return None


def step(state, random_below):
    """Advance the world one movement tick and name what happened.

    Returns exactly one event — ``ready``, ``moved``, ``served`` or ``dead`` —
    because one tick is one thing that happened and a caller that has to unpick
    a list of them will get it wrong.

    ``dead`` outranks ``served``, and a step CAN be both: a pipe is paid the
    moment its trailing edge passes the client's leading edge, at which point
    it can no longer be hit, but the floor still can.  The score is banked
    first and the event reports the death, so a run that ends on the floor half
    a pixel after clearing a pipe keeps the query it served.
    """
    if state["status"] != "playing":
        return state["status"]

    ready = state["ready"]
    if ready > 0:
        state["ready"] = ready - 1
        # Held, not merely un-accelerated: an opening hold that let the client
        # keep a velocity from somewhere would be a hold that does not hold.
        state["vy"] = 0
    else:
        vy = state["vy"] + GRAVITY
        if vy > MAX_FALL:
            vy = MAX_FALL
        state["vy"] = vy
        state["y"] += vy

    scroll = state["scroll"]
    state["scrolled"] += scroll
    pipes = state["pipes"]
    for pipe in pipes:
        pipe[0] -= scroll
    while pipes and pipes[0][0] + PIPE_W_SUB < 0:
        pipes.pop(0)
    # Spawned at an exact multiple of the spacing from the pipe before it
    # rather than at a fixed x, so the rhythm of the run cannot drift with the
    # remainder of a division.  The trigger is the newest pipe reaching the
    # right edge rather than reaching one spacing inside it, which keeps a pipe
    # placed a full spacing beyond the panel at all times: the view never draws
    # it, but it is what lets a player — and the autopilot that stands in for
    # one — position for the gap AFTER the one being flown.
    if pipes and pipes[-1][0] <= WORLD_W_SUB:
        _spawn(state, pipes[-1][0] + PIPE_SPACING_SUB, random_below)

    event = "ready" if ready > 0 else "moved"
    for pipe in pipes:
        if not pipe[2] and pipe[0] + PIPE_W_SUB <= CLIENT_X_SUB:
            pipe[2] = True
            state["score"] += 1
            event = "served"

    cause = collide(state)
    if cause is not None:
        state["status"] = "dead"
        state["fatal"] = state["y"]
        state["cause"] = cause
        return "dead"
    return event
