"""Pure fixed-point VACUUM.SQL state machine; no Badgeware imports.

Integer arithmetic throughout, in 1/16th-pixel units (``UNIT``).  Two reasons,
both load-bearing and both borrowed from `pong_model` rather than re-derived:
MicroPython floats on the RP2350 are software and the render loop cannot
afford them, and a float model has no exact expected value, so every geometry
test would have to carry a tolerance.  Everything below is exact, so the tests
assert equality.

THE THEME IS VACUUM, and the mechanic and the database operation are the same
idea rather than a label stuck on top.  The bricks are BLOAT: dead tuples still
occupying heap pages.  The ball is the vacuum WORKER, and the paddle is the
SCAN — the position in the heap the sweep has reached, which is exactly what a
paddle is and why it belongs on the horizontal axis.  Clearing a page reclaims
it; clearing the whole heap is TABLE
COMPACTED; running out of passes is VACUUM ABORTED.  The score counts pages
reclaimed, and the table never grows while you do it, which is the one thing a
real VACUUM promises.

WHY THE TOP ROWS PAY MORE.  A real VACUUM can only hand space back to the
filesystem by truncating free pages off the END of the heap; everything else it
reclaims is reusable but the file stays the size it was.  The rows furthest
from the scan are that tail, so reclaiming them is worth more.  The value
ladder is the database fact, not a difficulty curve.
"""


# ---- geometry ---------------------------------------------------------------
#
# The court is the 160x120 LORES panel minus the 16 px status strip, expressed
# in COURT-LOCAL pixels.  The view adds its own Y_OFFSET; the model never knows
# the strip exists, which is what lets the whole file be tested without a
# screen.  These are Snake's and Pong's numbers, so all three games' playfields
# are the same size.
COURT_W = 160
COURT_H = 104

# Sub-pixels per logical pixel.  16, matching Pong, because every velocity below
# is a sixteenth of a speed, so a component is one multiply and one shift-sized
# divide, and because 16 sub-pixels is finer than the panel can show — the
# renderer's `// UNIT` throws the fraction away, so sub-pixel residue is never
# something a player can see.
UNIT = 16

BALL = 4
SCAN_W = 24
SCAN_H = 3
# The scan's top edge, court-local.  10 px of floor below it, so a worker that
# beat the scan is visibly past it for two ticks at the fastest level before
# the pass is called lost — a miss you can see rather than a ball that vanishes.
SCAN_Y = 94

# ---- the heap ---------------------------------------------------------------
#
# COLLISION USES WHOLE CELLS; the mortar is drawn, not simulated.  Each page
# owns a 16x6 cell and the view draws it 15x5, so the 1 px gap the eye reads as
# a seam is not a gap the worker can fall into.  A simulated seam would make a
# steep return rattle between two pages for several ticks, which looks like a
# bug and is not one.
BRICK_COLS = 10
BRICK_ROWS = 5
BRICK_W = 16
BRICK_H = 6
# Ceiling above the heap.  10 px is enough for the worker to get ABOVE the top
# row and clear it out sideways, which is the one piece of tactics this game
# has and the reason the ceiling is not flush with the first row.
BRICK_TOP = 10

# Pages reclaimed per row, tail first.  Sums to 150 for a full table, which
# fits the three-digit score slot the strip and the record share.
ROW_VALUE = (5, 4, 3, 2, 1)

BRICK_COUNT = BRICK_ROWS * BRICK_COLS
BRICK_BOTTOM = BRICK_TOP + BRICK_ROWS * BRICK_H
TOTAL_PAGES = BRICK_COLS * sum(ROW_VALUE)

COURT_W_SUB = COURT_W * UNIT
COURT_H_SUB = COURT_H * UNIT
BALL_SUB = BALL * UNIT
SCAN_W_SUB = SCAN_W * UNIT
# The plane the worker is caught on: the TOP face of the scan.
SCAN_FACE = SCAN_Y * UNIT
SCAN_TRAVEL = COURT_W_SUB - SCAN_W_SUB
BALL_TRAVEL_X = COURT_W_SUB - BALL_SUB


# ---- the ladder -------------------------------------------------------------
#
# Level is ball speed and NOTHING ELSE.  It is deliberately not a score
# multiplier: a page is worth its row at every level, so `PAGES 090` means the
# same thing whoever set it and the stored record needs no companion field to
# be readable.  (Snake made the opposite choice for good reasons — its level
# prices every row — and therefore has to store `high_level` beside
# `high_score`.  Pong made this one.  This game follows Pong.)
MIN_LEVEL = 1
MAX_LEVEL = 9
# Sub-pixels of worker travel per model step.  Pong's ladder verbatim: at
# STEP_MS = 25 that is 40 steps a second, so level 1 is 40 px/s and level 9 is
# 170 px/s, and each rung is about 15% faster than the one below — roughly the
# smallest speed change a hand reads as a different game.
LEVEL_SPEED = (16, 21, 26, 32, 38, 45, 52, 60, 68)

# THE MOVEMENT INTERVAL IS ABOVE THE FRAME PERIOD ON PURPOSE.  Snake's device
# frame is ~22.8 ms (43.8 fps measured); the browser runtime is faster.  An
# interval BELOW the frame period makes "at most one step per frame" the real
# limit, and the game then runs at whatever rate the platform renders — faster
# in the browser than on the badge.  25 ms is above both, so the worker travels
# 40 px-steps a second on either, and the e2e lane measures the same game the
# badge plays.
STEP_MS = 25

# Passes a run gets.  Three, and they are the lives: a pass is one sweep of the
# heap, and a worker that gets past the scan has ended that sweep with the
# table no smaller.
PASSES = 3

# How long the worker rides the scan before it is released, in steps.  16
# steps is 400 ms.  It is longer than Pong's 300 ms serve because here the
# player can STEER during it — the worker sits on the scan, so the wait is the
# aim, not a delay imposed on them.
LAUNCH_TICKS = 16


# ---- the angle table --------------------------------------------------------
#
# Where on the scan the worker lands decides the angle it leaves at.  This is
# Pong's table transposed and re-purposed: there the offset steepened the
# VERTICAL component, here it steepens the HORIZONTAL one, because the worker
# always leaves the scan going up, and what the player is choosing is where
# across the heap to send it.  Dead centre is nearly straight up; the tip is a
# shallow cross-court shot.
#
# THIS TABLE HAD FOUR RUNGS UNTIL 2026-08-21 -- `(3,16) (6,15) (11,12) (14,8)`
# out of 16 -- and it carried the same defect class the owner found by playing
# Pong: *"you can leave the pong paddle in one place and it will always bounce
# back to where you were"*.  Four rungs over the contact range made the
# arrival->arrival map PIECEWISE FLAT over 3.06 px at a time, which is worse
# than the 2.5 px that gave Pong a period-one orbit.  `README.md` carries the
# whole derivation, the sweep and the one way this game's version of the defect
# is genuinely different from Pong's.
#
# TWENTY-THREE RUNGS, out of ANGLE_UNIT = 64.  The ENVELOPE IS UNCHANGED: rung 0
# is 12/64 = 3/16 and rung 22 is 56/64 = 14/16, exactly the shallowest and
# steepest the four-rung table shipped.  So no level got faster, the scan's
# 5/4 margin over the worst horizontal component is the same inequality it
# always was, and every timing and frame claim in the README still holds.  What
# changed is resolution: 0.61 px a rung instead of 3.06 px, with no saturating
# band at either end (see CONTACT_SPAN).
#
# Each entry is (ax, ay) out of ANGLE_UNIT, and BOTH spread figures are
# BYTE-FOR-BYTE THE SHIPPED ONES: 0.957% in exact arithmetic and 3.489% once
# `scale` has rounded the components to integers.  Not "close to" and not
# "inside the same bound" -- the same numbers, because the chain was searched
# under both as hard constraints.  So the landing point changes the DIRECTION of
# the worker and never its speed, to exactly the degree it always did, and
# `test_breakout` pins both without either bound being relaxed.
#
# WHY THE REALISED SPREAD IS THE BINDING CONSTRAINT AND NOT THE TABLE'S.  The
# table's own magnitudes are easy to keep tight; what is not is what survives
# `scale`.  At level 1 the worker moves 16 sub-pixels a step, so a realised
# component is an integer in 0..16 and a rung whose exact magnitude is perfect
# can still round to a realised one 5% off.  A 29-rung chain that met the
# table's 0.957% took the realised spread to 7.331% -- past the 5% the shipped
# test has always allowed, and worse than truncating -- which would have made
# the level stop being the only speed control in the game.  Searched under both
# constraints instead: out of 16 there are six admissible pairs (the shipped
# table used four), out of 32 eight, out of 64 TWENTY-THREE.  Out of 128 there
# are fifty and they buy nothing measurable -- a 58-rung table left 2,624
# endless parked orbits against the 29-rung table's 2,607, which is the floor
# below being proved rather than guessed at.
#
# THERE IS NO VERTICAL ZONE.  ax is never 0, so the worker always drifts
# sideways and a rally can never become a piston bouncing on one column
# forever.  A (0, 64) centre zone is the obvious choice and it is the one thing
# that would let a patient player farm a single repeating trajectory.
ANGLE_UNIT = 64
ANGLES = (
    (12, 64), (14, 63), (22, 61), (24, 60), (27, 59), (29, 58), (31, 57),
    (33, 56), (34, 55), (36, 54), (39, 52), (40, 51), (42, 49), (44, 48),
    (45, 47), (47, 45), (48, 44), (49, 42), (51, 40), (52, 39), (54, 36),
    (55, 34), (56, 32),
)

# The contact range the landing test actually admits, as a half-span in
# sub-pixels.  `_overlaps_scan` returns True from `scan - BALL_SUB + 1` to
# `scan + SCAN_W_SUB - 1`, so the worker's centre can sit up to half a scan
# PLUS half a worker from the scan's centre: 192 + 32 = 224, not 192.
#
# THE SHIPPED GAME DIVIDED BY 192 AND CLAMPED, AND THAT WAS THE SECOND FLAT
# SPOT.  Every landing in the outer 1.94 px at each end of the range -- a
# 31 sub-pixel band, hit constantly, half a worker's width -- saturated onto the
# shallowest-crossing rung, so the map was flat there no matter how many rungs
# the table had.  The `min` below is now defensive only: no landing
# `_overlaps_scan` admits can reach it, and `DeflectionMapTests` proves the
# clamp is dead code in play.
CONTACT_SPAN = SCAN_W_SUB // 2 + BALL_SUB // 2

# How far the worker's turnaround at the CEILING wanders, in sub-pixels, drawn
# once per ceiling contact.  0.75 px against a 14 px scan-plus-worker half-span,
# which is a little over one rung of the table above, and half of the 1.5 px
# Pong gives its replica.
#
# TWELVE AND NOT FOUR OR TWENTY-FOUR, and the number was measured rather than
# picked.  Re-running the 2,295 endless parked orbits the deterministic physics
# leaves, eight seeds each, the drift needed to end EVERY one of them inside a
# 200-contact budget is 4 sub-pixels; but at 4 the worst orbit still took 197
# contacts to break, which is a rally that ends without the player noticing it
# was ever stuck.  At 8 the worst is 118, at 12 it is 49 and at 16 it is 34.
# Twelve is where the curve stops paying: it buys a 2.4x margin under the
# 120-contact cap `ParkedScanTests` uses, for three quarters of a pixel of
# wander in a place no frame shows.
#
# WHY THERE IS ANY RANDOMNESS HERE AT ALL, since a deterministic function of the
# landing point is the better mechanism and is what the table above is.  Because
# the table CANNOT finish the job, and the reason is a proof rather than a
# measurement.  Park the scan and take the bricks away and the rally is an
# autonomous map on the landing point alone.  Inside one rung the outgoing
# velocity is CONSTANT, so the flight time back to the scan is constant too, and
# the return map is `x -> x + vx*T` -- a translation, slope +1.  Put ONE side-
# wall fold in that flight, which is what a shallow return does, and it becomes
# `x -> K - x`: slope MINUS ONE, an involution, and every point of it is on a
# period-two orbit with a period-ONE fixed point in the middle.  Refining the
# table shrinks the band that involution covers; it cannot remove the fixed
# point inside it.  Measured, and the measurement is what closes the question:
# a finer table took the never-ending endgame orbits from 9,923 of 1.12M parked
# states to 2,607, and DOUBLING the table again moved it to 2,624 -- up, not
# down.  Something in the loop has to be non-autonomous.
#
# IT IS AT THE CEILING, AND THAT IS THE MACHINE'S END OF THE COURT.  The
# player's own return stays a pure, exact function of where the worker struck
# the scan, so aiming is still learnable and a good landing is still exactly
# repeatable -- `DeflectionMapTests` drives it with a noisy RNG and asserts the
# same landing always gives the same velocity.  What wobbles is where the worker
# turns around at the far end of the heap, which is a sub-pixel no frame shows.
#
# IT IS ALSO PROVABLY IN THE RIGHT PLACE.  A parked orbit that never ends can
# never touch a page -- a page it touched would be reclaimed, and the geometry
# would change -- so it must fly clear to the ceiling on every single rally.
# The one seam every endless orbit is forced through is the one that got the
# perturbation.  `ParkedScanTests` is the sweep and `CeilingDriftTests` is the
# bound.
CEILING_DRIFT = 12

# The scan is 25% faster than the worker it is chasing, at every level — the
# same ratio Pong gives the player's paddle.  A scan slower than the worker is
# not a difficulty setting, it is a game the player cannot play; a very much
# faster one removes the reason to read the worker early.  It only ever has to
# beat the worker's HORIZONTAL component, which the table caps at 14/16 of the
# speed, so the margin is real at every level.
SCAN_NUM = 5
SCAN_DEN = 4


def next_step_clock(now, last_step, interval, ticks_diff, ticks_add):
    """Return the next movement clock when due, otherwise ``None``.

    Advancing by the configured interval avoids quantising the interval to the
    render frame.  At most one movement is still emitted per app frame.  If a
    long hitch leaves a second full interval outstanding, reset to ``now`` so
    later frames do not replay a dangerous backlog.

    This is `snake_model.next_step_clock` verbatim, by way of `pong_model`, and
    deliberately so: it is measured platform truth, it was paid for with device
    time, and a third slightly-different copy of a timing rule is how three
    apps end up disagreeing about what a hitch means.
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


def level_speed(level):
    """Sub-pixels of worker travel per step at this level."""
    return LEVEL_SPEED[clamp_level(level) - 1]


def scan_speed(speed):
    """Sub-pixels the scan covers per step."""
    return max(1, speed * SCAN_NUM // SCAN_DEN)


def fold(value, span):
    """Reflect ``value`` into ``[0, span]``, and say whether it flipped.

    A side-wall bounce is a reflection, and any number of reflections is one
    fold of the number line.  Doing it in closed form rather than as a
    while-loop means the arithmetic is exact for a worker travelling any
    distance in one step, including the interpolated crossing point computed
    below — where a naive "did it hit a wall on the way" test would have to give
    up and approximate.

    ``divmod`` floors, so a negative value lands on ``q = -1`` with a positive
    remainder and the odd-``q`` branch reflects it back off zero correctly.

    The interval is closed at both ends and the two ends are not quite
    symmetric: a value landing exactly on ``span`` is reported flipped, one
    landing exactly on 0 is not and reflects on the following step instead.
    That costs one step, in the case where a sub-pixel lands exactly on a
    boundary, and closing it would cost a branch in the hot path.

    `pong_model.fold` verbatim.  Only the horizontal axis uses it here: the
    ceiling is a wall but the floor is a goal line, so the vertical axis is
    reflected on one side only, by hand, in ``step``.
    """
    if span <= 0:
        return 0, False
    quotient, remainder = divmod(value, span)
    if quotient % 2:
        return span - remainder, True
    return remainder, False


def scale(speed, numerator):
    """``speed * numerator / ANGLE_UNIT``, ROUNDED rather than truncated.

    Every velocity component in the game goes through here.  The angle table is
    within 1% of one magnitude in exact arithmetic, but the components are
    integers, and truncating each of them costs up to half a sub-pixel EVERY
    TIME — which at the slow end of the ladder is a real fraction of the whole
    velocity.  One add buys the difference; the residue that remains is
    measured by `test_breakout` rather than hidden, because it cannot be
    removed without leaving integers behind.

    ``ANGLE_UNIT`` and not ``UNIT``: the deflection table is expressed in 64ths
    so that twenty-three rungs can share one magnitude (see ANGLES).  The
    sub-pixel grid the rest of the model lives on is still ``UNIT``.
    """
    return (speed * numerator + ANGLE_UNIT // 2) // ANGLE_UNIT


def _clamp_scan(x):
    return max(0, min(SCAN_TRAVEL, x))


def brick_row(index):
    return index // BRICK_COLS


def brick_value(index):
    """Pages reclaimed by clearing this cell."""
    return ROW_VALUE[index // BRICK_COLS]


def brick_rect(index):
    """The cell's DRAWN rectangle in court-local pixels, mortar excluded.

    The view's only source of brick geometry, so the drawn seam and the
    collision cell can never drift apart in two files.
    """
    row, col = divmod(index, BRICK_COLS)
    return (col * BRICK_W, BRICK_TOP + row * BRICK_H, BRICK_W - 1, BRICK_H - 1)


def _english(offset, speed):
    """Turn a landing point on the scan into an outgoing velocity.

    ``offset`` is the worker's centre minus the scan's centre in sub-pixels.
    The worker always leaves going UP; the offset chooses how far across it
    goes.  A dead-centre landing (offset 0) is treated as the right-hand side of
    centre and leaves at the shallowest angle the table has, which is
    12/64 = 3/16 — deliberately not zero, so no landing produces a purely
    vertical worker.

    Exact, total and pure: the same landing point always leaves at the same
    angle, which is what makes the return something a player can aim and
    repeat.  Nothing random reaches this function — the one non-autonomous
    ingredient in the physics is at the ceiling, on the far side of the flight,
    so the asymmetry is visible where it is decided rather than hidden in here.

    The magnitude is divided by ``CONTACT_SPAN + 1`` and NOT by half a scan.
    Dividing by half a scan left the outer 1.94 px at each end of the contact
    range sharing one rung, and that flat spot is where a good share of the
    parked orbits lived.
    """
    if offset < 0:
        sign_x = -1
        magnitude = -offset
    else:
        sign_x = 1
        magnitude = offset
    if magnitude > CONTACT_SPAN:
        magnitude = CONTACT_SPAN
    zone = magnitude * len(ANGLES) // (CONTACT_SPAN + 1)
    ax, ay = ANGLES[zone]
    return sign_x * scale(speed, ax), -scale(speed, ay)


def _drift_ceiling(ball_x, random_below):
    """Move the worker's turnaround along the ceiling, REFLECTING at the walls.

    Folded and not clamped, and that is the entire point of the function: a
    clamp at the end of the court is a flat spot, a flat spot is what a parked
    scan farms, and clamping this drift would have put one back at the two
    turnaround points nearest the walls -- which is exactly where the parked
    orbits congregate, because a side-wall fold is what makes their return map
    an involution in the first place.  ``fold`` is the same reflection the walls
    already use.

    TWO DRAWS RATHER THAN ONE so that a ``random_below`` returning zero -- the
    fixture every geometry test in this app uses -- means NO DRIFT.  The
    deterministic core of the game stays exactly testable and the
    characterisation tests describe the same machine they always did.

    IT IS SAFE TO MOVE THE WORKER SIDEWAYS HERE, whatever the drift, and the
    bound is worth writing down because the rest of ``step`` depends on it: at a
    ceiling reflection the worker's top edge is ``-(ball_y + vy)`` with
    ``ball_y + vy < 0``, so it is at most ``vy - 1 <= 67`` sub-pixels and its
    bottom edge at most 131 -- 8.19 px, against a heap that starts at
    ``BRICK_TOP`` = 10 px.  No page can be overlapped at any x, so the drift
    cannot smuggle the worker inside a live page and the ``brick_at`` call that
    follows it is free to run unchanged.  `CeilingDriftTests` pins the bound.
    """
    drift = random_below(CEILING_DRIFT + 1)
    if random_below(2):
        drift = -drift
    drifted, _flipped = fold(ball_x + drift, BALL_TRAVEL_X)
    return drifted


def _ride(state):
    """Park the worker on the scan, centred, ready to be released."""
    state["ball"] = [
        _clamp_ball_x(state["scan"] + SCAN_W_SUB // 2 - BALL_SUB // 2),
        SCAN_FACE - BALL_SUB,
    ]
    state["vel"] = [0, 0]


def _clamp_ball_x(x):
    return max(0, min(BALL_TRAVEL_X, x))


def _park(state):
    """Start a pass: the worker rides the scan for ``LAUNCH_TICKS``."""
    state["launch"] = LAUNCH_TICKS
    _ride(state)


def _release(state, random_below):
    """Send the worker up the heap at one of the table's four angles.

    Randomised so a run cannot be opened from memory, and injected so a test
    can make it a fixture.  Always upward: there is nothing below the scan
    but the floor.
    """
    zone = random_below(len(ANGLES))
    sign_x = 1 if random_below(2) else -1
    ax, ay = ANGLES[zone]
    speed = state["speed"]
    state["vel"] = [sign_x * scale(speed, ax), -scale(speed, ay)]


def new_game(level, random_below):
    """A fresh run.  THE HEAP IS THE SAME EVERY TIME, on purpose.

    No layout ladder, no power-ups and no per-level board: the only thing the
    player chose is the speed, so the only thing that changes is the speed.  A
    static heap also means two runs at the same level are comparable, which is
    what makes one stored high score meaningful across nine of them.
    """
    speed = level_speed(level)
    state = {
        "level": clamp_level(level),
        # Cached because every step reads it and `LEVEL_SPEED[level - 1]` in the
        # hot path is a lookup the model can do once.
        "speed": speed,
        "ball": [0, 0],
        "vel": [0, 0],
        "scan": _clamp_scan((COURT_W_SUB - SCAN_W_SUB) // 2),
        # One byte per page: 50 bytes against a list's few hundred, and
        # `sum(bricks)` is the live count for free.
        "bricks": bytearray(b"\x01" * BRICK_COUNT),
        "left": BRICK_COUNT,
        "score": 0,
        "passes": PASSES,
        "launch": 0,
        "status": "playing",
        # Where on the floor the worker got past, in sub-pixels, so the finished
        # screen can answer "where did I lose it?".  It is never a position the
        # worker still occupies, which is why the renderer cannot work it out
        # for itself.
        "fatal": None,
    }
    _park(state)
    return state


def move_scan(state, delta):
    """Move the scan, clamped to the court.

    Separate from ``step`` so the clamp is testable on its own and so a caller
    can nudge the scan without advancing the world — which is what the app's
    tests do.
    """
    state["scan"] = _clamp_scan(state["scan"] + delta)
    return state["scan"]


def brick_at(state, ball_x, ball_y):
    """The index of a live page the worker's rect overlaps, or ``None``.

    At most four cells can be touched at once (the worker is 4 px against a
    16x6 cell), and the search is row-major from the top-left of that block,
    so the answer is a fixed function of the position and never of iteration
    order.  ONE TICK CLEARS AT MOST ONE PAGE PER AXIS: a corner landing that
    touches two live cells takes the upper-left one now and the other on the
    tick after, which keeps "one tick, one thing that happened" true of the
    event this function feeds.
    """
    bottom = (ball_y + BALL_SUB - 1) // UNIT
    if bottom < BRICK_TOP:
        return None
    top = ball_y // UNIT
    if top >= BRICK_BOTTOM:
        return None
    first_row = (top - BRICK_TOP) // BRICK_H
    if first_row < 0:
        first_row = 0
    last_row = (bottom - BRICK_TOP) // BRICK_H
    if last_row > BRICK_ROWS - 1:
        last_row = BRICK_ROWS - 1
    first_col = (ball_x // UNIT) // BRICK_W
    last_col = ((ball_x + BALL_SUB - 1) // UNIT) // BRICK_W
    if last_col > BRICK_COLS - 1:
        last_col = BRICK_COLS - 1
    bricks = state["bricks"]
    for row in range(first_row, last_row + 1):
        base = row * BRICK_COLS
        for col in range(first_col, last_col + 1):
            if bricks[base + col]:
                return base + col
    return None


def _reclaim(state, index):
    """Clear one page and bank what it was worth."""
    state["bricks"][index] = 0
    state["left"] -= 1
    state["score"] += brick_value(index)


def _crossing_x(state, face):
    """The worker's left edge where its BOTTOM edge crosses ``face``.

    Linear interpolation along the step, then folded between the side walls, so
    a step that would have bounced off a wall before reaching the scan is
    resolved exactly rather than approximated.  Only ever called with
    ``vy > 0``, so the division is always safe.
    """
    ball_x, ball_y = state["ball"]
    vx, vy = state["vel"]
    travelled = face - (ball_y + BALL_SUB)
    raw = ball_x + vx * travelled // vy
    folded, _flipped = fold(raw, BALL_TRAVEL_X)
    return folded


def _overlaps_scan(scan, ball_x):
    """Whether a worker whose left edge is ``ball_x`` lands on the scan."""
    return ball_x + BALL_SUB > scan and ball_x < scan + SCAN_W_SUB


def step(state, random_below, move=0):
    """Advance the world one movement tick and name what happened.

    ``move`` is -1, 0 or +1 and is a HELD direction, not an edge: the scan is
    a position, not a command, so it moves on the model's own clock and at the
    model's own rate on every platform.  Steering is resolved BEFORE the worker
    moves, which is what makes a scan arriving on the same tick as the worker
    a save rather than a near miss.

    Returns exactly one event, because one tick is one thing that happened and
    a caller that has to unpick a list of them will get it wrong.  The priority
    is: the run ending, then a page, then the scan, then a wall.

    THE STEP IS AXIS-SEPARATED — x resolved against the heap, then y — for the
    same reason every tile-grid game is: it is the only cheap way to know WHICH
    face was struck when a moving box lands on a static one, and a diagonal
    landing that reflected both components at once would send the worker back
    the way it came instead of across.  A page reflects the axis that reached
    it and the worker steps back to its last legal position on that axis, which
    keeps the invariant the whole file rests on: at the top of a tick the
    worker never overlaps a live page.
    """
    if state["status"] != "playing":
        return state["status"]

    if move:
        move_scan(state, move * scan_speed(state["speed"]))

    if state["launch"] > 0:
        state["launch"] -= 1
        # The worker rides the scan, so the wait is aim rather than delay.
        _ride(state)
        if state["launch"] == 0:
            _release(state, random_below)
        return "launching"

    # ---- the scan, tested as a PLANE CROSSING, not as an overlap ----------
    #
    # At level 9 the worker covers 4.25 px a step against a 3 px scan, so an
    # overlap test would let it tunnel straight through — the classic bug in
    # every hand-written paddle game.  Asking "did the bottom edge cross the
    # face during this step" cannot miss, whatever the speed, and costs one
    # compare.  Resolved FIRST and to the exclusion of everything else this
    # tick: the worker lands ON the face with a new angle and spends the rest
    # of the tick there, which costs it 25 ms of travel once per return and
    # buys an ordering that has no diagonal cases in it at all.
    ball_x, ball_y = state["ball"]
    vx, vy = state["vel"]
    if vy > 0 and ball_y + BALL_SUB <= SCAN_FACE < ball_y + vy + BALL_SUB:
        hit_x = _crossing_x(state, SCAN_FACE)
        if _overlaps_scan(state["scan"], hit_x):
            offset = hit_x + BALL_SUB // 2 - (
                state["scan"] + SCAN_W_SUB // 2
            )
            state["vel"] = list(_english(offset, state["speed"]))
            state["ball"] = [hit_x, SCAN_FACE - BALL_SUB]
            return "caught"

    event = "moved"

    # ---- horizontal --------------------------------------------------------
    next_x, wall = fold(ball_x + vx, BALL_TRAVEL_X)
    if wall:
        vx = -vx
        event = "wall"
    index = brick_at(state, next_x, ball_y)
    if index is not None:
        # A page reached at the same tick as a side wall keeps the WALL's
        # reflection: the worker is being put back against the wall, so the
        # outward velocity is the physical one and flipping it twice would
        # drive it into the panel edge.
        if not wall:
            vx = -vx
        next_x = ball_x
        _reclaim(state, index)
        event = "reclaim"
    ball_x = next_x

    # ---- vertical ----------------------------------------------------------
    next_y = ball_y + vy
    if next_y < 0:
        # The ceiling is a wall; the floor is a goal line.  One reflection is
        # always enough: the fastest worker covers 4.34 px against a 104 px
        # court.
        next_y = -next_y
        vy = -vy
        # THE ONE NON-AUTONOMOUS INGREDIENT IN THE PHYSICS, and it is at the
        # far end of the flight on purpose -- see CEILING_DRIFT.  Without it a
        # parked scan with the heap nearly cleared farms an endless rally,
        # because a parked rally with no pages left is an autonomous map whose
        # return leg folds off a side wall, and a folded return map has slope
        # minus one and therefore a fixed point that no table resolution can
        # remove.
        ball_x = _drift_ceiling(ball_x, random_below)
        if event == "moved":
            event = "wall"
    index = brick_at(state, ball_x, next_y)
    if index is not None:
        vy = -vy
        next_y = ball_y
        _reclaim(state, index)
        event = "reclaim"

    state["ball"] = [ball_x, next_y]
    state["vel"] = [vx, vy]

    if state["left"] == 0:
        state["status"] = "compacted"
        return "compacted"

    # ---- the floor ---------------------------------------------------------
    #
    # Resolved on the TRAILING edge, so the worker is visibly all the way past
    # the scan before anything is decided.  A loss called at the face would
    # freeze the court with the ball still touching the scan it just beat,
    # which reads as a bug rather than a miss.
    if next_y >= COURT_H_SUB:
        state["fatal"] = _clamp_ball_x(ball_x)
        state["passes"] -= 1
        if state["passes"] <= 0:
            state["status"] = "aborted"
            return "aborted"
        _park(state)
        return "lost"
    return event
