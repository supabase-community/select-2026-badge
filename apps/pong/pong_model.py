"""Pure fixed-point REPLICA.SQL state machine; no Badgeware imports.

The whole game is integer arithmetic in 1/16th-pixel units (``UNIT``).  Two
reasons, both load-bearing: MicroPython floats on the RP2350 are software and
the render loop cannot afford them, and a float model has no exact expected
value, so every geometry test would have to carry a tolerance.  Everything
below is exact, so the tests assert equality.

THE THEME IS REPLICATION, and the nouns are the mechanics rather than a coat of
paint over them.  The ball is a WAL segment in flight.  The left paddle is the
PRIMARY and belongs to the player; the right paddle is the REPLICA and is
played by the machine.  A return by the player is one segment SYNCED.  A
segment that gets past the primary is REPLICATION BROKEN and ends the run.  A
segment the replica fails to apply forces a RESYNC, which pays and re-serves.
"""


# ---- geometry ---------------------------------------------------------------
#
# The court is the 160x120 LORES panel minus the 16 px status strip, expressed
# in COURT-LOCAL pixels.  The view adds its own Y_OFFSET; the model never knows
# the strip exists, which is what lets the whole file be tested without a
# screen.
COURT_W = 160
COURT_H = 104

# Sub-pixels per logical pixel.  16 was chosen because every velocity below is
# a sixteenth of a speed, so a component is one multiply and one shift-sized
# divide, and because 16 sub-pixels is finer than the panel can show — the
# renderer's `// UNIT` throws the fraction away, so sub-pixel residue is never
# something a player can see.
UNIT = 16

BALL = 4
PADDLE_W = 3
PADDLE_H = 20
# The primary's paddle sits 3 px off the goal line, so a beaten paddle is
# visibly beaten rather than merged into the edge of the panel.
PADDLE_X = 3

COURT_W_SUB = COURT_W * UNIT
COURT_H_SUB = COURT_H * UNIT
BALL_SUB = BALL * UNIT
PADDLE_H_SUB = PADDLE_H * UNIT
# The two faces the ball can be returned from, as x planes in sub-pixels.  The
# primary's face is the RIGHT side of the left paddle; the replica's face is
# the LEFT side of the right paddle.
FACE_PRIMARY = (PADDLE_X + PADDLE_W) * UNIT
FACE_REPLICA = (COURT_W - PADDLE_X - PADDLE_W) * UNIT
# The travel available to a paddle's top edge.
PADDLE_TRAVEL = COURT_H_SUB - PADDLE_H_SUB
BALL_TRAVEL = COURT_H_SUB - BALL_SUB


# ---- the ladder -------------------------------------------------------------
#
# Level is ball speed and NOTHING ELSE.  It is deliberately not a score
# multiplier: one return is one segment synced at every level, so `SYNCED 40`
# means the same thing whoever set it, and the badge's stored record needs no
# companion field to be readable.  (Snake made the opposite choice for good
# reasons — its level prices every row — and therefore has to store
# `high_level` beside `high_score`.  This game is simpler and pays for it in
# nothing.)
MIN_LEVEL = 1
MAX_LEVEL = 9
# Sub-pixels of ball travel per model step.  At STEP_MS = 25 that is 40 steps a
# second, so level 1 is 40 px/s (four seconds across the court) and level 9 is
# 170 px/s (0.94 s).  The rungs are spaced so each is about 15% faster than the
# one below, which is roughly the smallest speed change a hand reads as a
# different game.
LEVEL_SPEED = (16, 21, 26, 32, 38, 45, 52, 60, 68)

# THE MOVEMENT INTERVAL IS ABOVE THE FRAME PERIOD ON PURPOSE.  Snake's device
# frame is ~22.8 ms (43.8 fps measured); the browser runtime is faster.  An
# interval BELOW the frame period makes "at most one step per frame" the real
# limit, and the game then runs at whatever rate the platform renders — faster
# in the browser than on the badge.  25 ms is above both, so the ball travels
# 40 px-steps a second on either, and the e2e lane measures the same game the
# badge plays.
STEP_MS = 25

# How long the ball sits at the centre before a serve leaves, in steps.
# 12 steps is 300 ms.  Without it a RESYNC teleports the ball to the middle of
# the court already moving, which at level 9 is 0.4 s of warning for a ball the
# player did not see arrive.
SERVE_TICKS = 12

# What beating the replica pays.  A return is worth 1, so a RESYNC is worth
# five returns — deliberately more than the rally it interrupts, because a
# bonus worth the same as carrying on would make beating the replica a thing
# the player should AVOID doing.
RESYNC_BONUS = 5


# ---- the deflection table ---------------------------------------------------
#
# Where the segment hits the bat decides the angle it leaves at: dead centre is
# shallow, the tip is steep.  FIFTEEN RUNGS across each half of the contact
# range, mirrored, so thirty outcomes across the bat.
#
# THIS TABLE HAD FOUR RUNGS UNTIL 2026-08-21 AND THAT WAS THE BUG THE OWNER
# FOUND BY PLAYING: "you can leave the pong paddle in one place and it will
# always bounce back to where you were".  Four rungs makes the rally's
# return map PIECEWISE FLAT -- every arrival inside one 2.5 px band leaves at
# exactly the same angle -- and a piecewise-flat map on a finite integer state
# space has short cycles everywhere.  The shipped game had a PERIOD-ONE orbit:
# at level 4, parked at y = 14.5 px, the segment came back to sub-pixel 333
# every single rally, forever.  Fourteen per cent of all parked entry states
# never missed.  `pong/README.md` carries the whole derivation and the sweep.
#
# Fifteen rungs makes the same map EXPANDING instead: one sub-pixel of
# difference in where the segment lands is about eleven sub-pixels of
# difference in where it comes back, so a parked bat's orbit wanders the court
# instead of sitting on a point.  That is the fix a player can LEARN -- centre
# is still shallow, tip is still steep, and aiming still works, at 0.67 px of
# resolution instead of 2.5 px.
#
# Each entry is (ax, ay) out of ANGLE_UNIT, and every pair is within 0.57% of
# the same magnitude (the four-rung table was 0.96%), so english changes the
# DIRECTION of the segment and never its speed.  That property is what makes
# the level the only speed control in the game, and `test_pong` pins it.
#
# WHY 64ths AND NOT 16ths.  The magnitude property is what limits the rung
# count: out of 16 there are only FOUR integer pairs near magnitude 16 with
# distinct ay, and five if the tolerance is doubled -- exhaustively searched,
# not guessed.  Out of 64 there are fifteen inside 0.6%.  The envelope is
# unchanged: rung 0 is 12/64 = 3/16 and rung 14 is 44/64 = 11/16, the same
# shallowest and steepest angles the four-rung table shipped, so no level got
# faster, the replica's difficulty derivation below still holds and the
# steepest vertical speed on the ladder is the same integer it always was.
#
# THE REALISED velocities are looser than the table, because the components are
# integers: after `scale`'s rounding the worst level spreads by 3.96% (the
# four-rung table was 3.49%) against the table's own 0.57%.  That is measured,
# it is bounded, and it is invisible at 0.375 mm a pixel.
#
# THERE IS NO FLAT ZONE, IN EITHER SENSE.  ay is never 0, so the ball always
# drifts vertically, always eventually reaches a wall, and the geometry of a
# rally can never become stationary.  AND no band of contact points shares an
# outgoing angle by SATURATION -- see CONTACT_SPAN, which is the second half of
# this fix and was a real flat spot in the shipped game.
ANGLE_UNIT = 64
ANGLES = (
    (64, 12), (63, 16), (62, 20), (61, 23), (60, 25),
    (59, 27), (58, 29), (57, 31), (56, 33), (55, 35),
    (54, 36), (53, 38), (52, 39), (49, 43), (48, 44),
)

# The contact range the overlap test actually admits, as a half-span in
# sub-pixels.  `_overlaps` returns True from `paddle - BALL_SUB + 1` to
# `paddle + PADDLE_H_SUB - 1`, so the segment's centre can sit up to half a bat
# PLUS half a segment from the bat's centre: 160 + 32 = 192, not 160.
#
# THE SHIPPED GAME USED 160 AND CLAMPED, AND THAT WAS THE SECOND HALF OF THE
# BUG.  Every contact in the outer 2 px of the bat at each end -- a third of a
# ball's width, hit constantly -- saturated onto the steepest rung, so the
# deflection map was flat there no matter how many rungs the table had.  Every
# parked orbit that survived the fifteen-rung table lived in exactly that dead
# band; removing it is what took the survivor count to zero.  The `min` below
# is now defensive only: no contact `_overlaps` admits can reach it.
CONTACT_SPAN = PADDLE_H_SUB // 2 + BALL_SUB // 2

# The replica's paddle speed, as sixteenths of the ball's speed.
#
# THIS NUMBER IS THE ENTIRE DIFFICULTY OF THE GAME, so here is the arithmetic.
# The replica tracks the ball's centre every step, so over a long approach its
# error converges to zero whenever its speed exceeds the ball's VERTICAL speed.
# The four zones give |vy| of 3, 6, 8 and 11 sixteenths of the speed.  At 9/16
# the replica out-runs zones 0-2 and is out-run by zone 3 alone: only the
# steepest return can beat it, and only if it reaches the far side without a
# wall bounce resetting the chase.
#
# The margin is 11/16 - 9/16 = one eighth of the ball's speed per step, over
# the ~3200/speed steps a full crossing takes, which is 400 sub-pixels — 25 px
# of gain against the 12 px (half a paddle plus half a ball) it must beat.
# Comfortable enough to be a repeatable skill, tight enough that a lazy return
# is simply returned.
REPLICA_NUM = 9
REPLICA_DEN = 16

# How far the replica's apply point wanders, in sub-pixels, drawn once per
# rally.  1.5 px against a 12 px bat-plus-segment half-span, which is about two
# rungs of the table above.
#
# WHY THERE IS ANY RANDOMNESS HERE AT ALL, since a deterministic function of
# the impact point is the better mechanism and is what the table above is:
# a parked bat makes the whole rally an AUTONOMOUS deterministic map on a
# finite integer state space, and every such map cycles.  Pigeonhole, not bad
# luck.  So no purely deterministic physics can promise that a parked bat
# eventually misses -- the table above takes the survivors from 14% of parked
# entry states to 0.4%, and the last 0.4% are fixed points that no amount of
# extra resolution removes, only moves.  Something in the loop has to be
# non-autonomous.
#
# IT IS ON THE MACHINE'S SIDE OF THE COURT, DELIBERATELY.  The player's own
# return stays a pure, exact function of where the segment struck the bat, so
# aiming is still learnable and a good hit is still repeatable.  What wobbles
# is the REPLICA's acknowledgement -- and a replica that applies a record a
# byte or two from where it received it is the thematically honest place to put
# it.  One `random_below` pair per rally, through the seam the serve already
# uses.
REPLICA_LAG = 24

# The player's paddle is 25% faster than the segment it is chasing, at every
# level.  A paddle slower than the ball is not a difficulty setting, it is a
# game the player cannot play; a paddle very much faster removes the reason to
# read the ball early.
PLAYER_NUM = 5
PLAYER_DEN = 4


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


def level_speed(level):
    """Sub-pixels of ball travel per step at this level."""
    return LEVEL_SPEED[clamp_level(level) - 1]


def player_speed(speed):
    """Sub-pixels the primary's paddle covers per step."""
    return max(1, speed * PLAYER_NUM // PLAYER_DEN)


def replica_speed(speed):
    """Sub-pixels the replica's paddle covers per step."""
    return max(1, speed * REPLICA_NUM // REPLICA_DEN)


def fold(value, span):
    """Reflect ``value`` into ``[0, span]``, and say whether it flipped.

    A vertical wall bounce is a reflection, and any number of reflections is
    one fold of the number line.  Doing it in closed form rather than as a
    while-loop means the arithmetic is exact for a ball travelling any distance
    in one step, including the interpolated crossing point computed below —
    where a naive "did it hit a wall on the way" test would have to give up and
    approximate.

    ``divmod`` floors, so a negative value lands on ``q = -1`` with a positive
    remainder and the odd-``q`` branch reflects it back off zero correctly.

    The interval is closed at both ends and the two ends are not quite
    symmetric: a value landing exactly on ``span`` is reported flipped, one
    landing exactly on 0 is not and reflects on the following step instead.
    That costs one step, in the case where a sub-pixel lands exactly on a
    boundary, and closing it would cost a branch in the hot path.
    """
    if span <= 0:
        return 0, False
    quotient, remainder = divmod(value, span)
    if quotient % 2:
        return span - remainder, True
    return remainder, False


def _clamp_paddle(y):
    return max(0, min(PADDLE_TRAVEL, y))


def scale(speed, numerator):
    """``speed * numerator / ANGLE_UNIT``, ROUNDED rather than truncated.

    Every velocity component in the game goes through here.  The angle table
    is within 1% of one magnitude in exact arithmetic, but the components are
    integers, and truncating each of them costs up to half a sub-pixel EVERY
    TIME — which at the slow end of the ladder is a real fraction of the whole
    velocity.  Measured across all nine levels and all four zones: truncation
    spreads the realised speed by up to 4.76%, rounding by up to 3.49%.  One
    add buys the difference, and the residue is documented rather than hidden
    because it cannot be removed without leaving integers behind.

    ``ANGLE_UNIT`` and not ``UNIT``: the deflection table is expressed in
    64ths so that fifteen rungs can share one magnitude (see ANGLES).  The
    sub-pixel grid the rest of the model lives on is still ``UNIT``.
    """
    return (speed * numerator + ANGLE_UNIT // 2) // ANGLE_UNIT


def _english(offset, speed, sign_x):
    """Turn a hit position into a velocity.

    ``offset`` is the ball's centre minus the paddle's centre in sub-pixels;
    ``sign_x`` is +1 to send the segment right (a primary return) and -1 to
    send it left (a replica's acknowledgement).

    Exact, total and pure: the same contact point always leaves at the same
    angle, which is what makes the primary's return something a player can aim
    and repeat.  Nothing random reaches this function -- the replica's apply
    lag is folded into ``offset`` by its caller, so that the asymmetry between
    the two bats is visible where it is decided rather than hidden in here.

    The magnitude is divided by ``CONTACT_SPAN + 1`` and NOT by half a bat.
    Dividing by half a bat left the outer 2 px at each end of the contact
    range sharing one rung, and that flat spot is where every parked-bat orbit
    that survived the table's resolution turned out to live.
    """
    if offset < 0:
        sign_y = -1
        magnitude = -offset
    else:
        sign_y = 1
        magnitude = offset
    if magnitude > CONTACT_SPAN:
        magnitude = CONTACT_SPAN
    rung = magnitude * len(ANGLES) // (CONTACT_SPAN + 1)
    ax, ay = ANGLES[rung]
    return sign_x * scale(speed, ax), sign_y * scale(speed, ay)


def _apply_lag(offset, lag):
    """Move a contact point along the bat by ``lag``, REFLECTING at its ends.

    Folded and not clamped, and that is the entire point of the function: a
    clamp at the end of the bat is a flat spot in the deflection map, a flat
    spot is what a parked bat farms, and clamping the lag would have put the
    flat spot straight back at the two contact points where it did the most
    damage.  ``fold`` is the same reflection the walls use.
    """
    folded, _flipped = fold(offset + lag + CONTACT_SPAN, 2 * CONTACT_SPAN)
    return folded - CONTACT_SPAN


def _draw_lag(state, random_below):
    """Choose where the replica will apply the segment now heading at it.

    Drawn ONCE per rally, when the primary ships the segment, so the replica
    still tracks smoothly and its bat never jitters on screen -- what varies is
    the sub-pixel it acknowledges from, which is a thing no pixel shows.

    Two draws rather than one so that a ``random_below`` returning zero -- the
    fixture every geometry test in this app uses -- means NO LAG.  The
    deterministic core of this game stays exactly testable, and the
    characterisation tests describe the same machine they always did.
    """
    lag = random_below(REPLICA_LAG + 1)
    state["lag"] = -lag if random_below(2) else lag


def _serve(state, random_below):
    """Put the segment back at the centre, aimed at the primary.

    Always aimed at the PLAYER, never at the replica.  The score counts the
    player's returns, so a serve the replica meets first would open every rally
    with a beat the player has no part in, and a RESYNC would hand the ball
    straight back to the side that just failed.
    """
    speed = state["speed"]
    zone = random_below(len(ANGLES))
    sign_y = 1 if random_below(2) else -1
    ax, ay = ANGLES[zone]
    state["ball"] = [
        (COURT_W_SUB - BALL_SUB) // 2,
        (COURT_H_SUB - BALL_SUB) // 2,
    ]
    state["vel"] = [-scale(speed, ax), sign_y * scale(speed, ay)]
    state["serve"] = SERVE_TICKS
    # A serve travels at the PLAYER, so no acknowledgement is pending and the
    # replica has nothing to have decided yet.  Zeroing it here keeps a
    # re-served run byte-identical to a fresh one.
    state["lag"] = 0


def new_game(level, random_below):
    speed = level_speed(level)
    state = {
        "level": clamp_level(level),
        # Cached because every step reads it and `LEVEL_SPEED[level - 1]` in
        # the hot path is a lookup the model can do once.  It is also the one
        # thing a saved state would need to stay consistent, which is why the
        # level is fixed for the whole run.
        "speed": speed,
        "ball": [0, 0],
        "vel": [0, 0],
        "paddle": _clamp_paddle((COURT_H_SUB - PADDLE_H_SUB) // 2),
        "replica": _clamp_paddle((COURT_H_SUB - PADDLE_H_SUB) // 2),
        "score": 0,
        "serve": 0,
        # Where the replica will apply the segment currently heading at it,
        # relative to the contact point it would otherwise read, in sub-pixels.
        # `_serve` overwrites it below; it is declared here so the shape of a
        # pong state is one dict literal a reader can see whole.
        "lag": 0,
        "status": "playing",
        # Where on the goal line the segment got past, in sub-pixels, so the
        # finished screen can answer "where did I lose it?".  It is never a
        # position the ball still occupies, which is why the renderer cannot
        # work it out for itself.
        "fatal": None,
    }
    _serve(state, random_below)
    return state


def move_paddle(state, delta):
    """Move the primary's paddle, clamped to the court.

    Separate from ``step`` so the clamp is testable on its own and so a caller
    can nudge the paddle without advancing the world — which is what the app's
    tests do and what a future replay probe would want.
    """
    state["paddle"] = _clamp_paddle(state["paddle"] + delta)
    return state["paddle"]


def _track_replica(state):
    """The replica follows the stream, every step, with a speed cap.

    It tracks whichever way the segment is travelling rather than idling back
    to the middle when the ball is away.  A replica that parks in the centre
    would be beaten by any steep return regardless of skill, which is a
    difficulty setting disguised as behaviour; one that follows continuously is
    beaten only by out-running it, which is the thing the angle table exists to
    let a player do.
    """
    target = _clamp_paddle(
        state["ball"][1] + BALL_SUB // 2 - PADDLE_H_SUB // 2
    )
    current = state["replica"]
    limit = replica_speed(state["speed"])
    if target > current:
        state["replica"] = min(target, current + limit)
    elif target < current:
        state["replica"] = max(target, current - limit)


def _overlaps(paddle_y, ball_y):
    """Whether a ball whose top edge is ``ball_y`` meets that paddle."""
    return ball_y + BALL_SUB > paddle_y and ball_y < paddle_y + PADDLE_H_SUB


def _crossing_y(state, face, edge_offset):
    """The ball's top edge where its ``edge_offset`` edge crosses ``face``.

    Linear interpolation along the step, then folded into the court, so a step
    that would have bounced off a wall before reaching the paddle is resolved
    exactly rather than approximated.  ``vx`` is never zero (every angle has
    ax >= 12), so the division is always safe.
    """
    ball_x, ball_y = state["ball"]
    vx, vy = state["vel"]
    travelled = face - (ball_x + edge_offset)
    raw = ball_y + vy * travelled // vx
    folded, _flipped = fold(raw, BALL_TRAVEL)
    return folded


def step(state, random_below, move=0):
    """Advance the world one movement tick and name what happened.

    ``move`` is -1, 0 or +1 and is a HELD direction, not an edge: the paddle is
    a position, not a command, so it moves on the model's own clock and at the
    model's own rate on every platform.  Steering is resolved before the ball
    moves, which is what makes a paddle arriving on the same tick as the
    segment a save rather than a near miss.

    Returns exactly one event, paddle events taking priority over walls,
    because one tick is one thing that happened and a caller that has to
    unpick a list of them will get it wrong.
    """
    if state["status"] != "playing":
        return state["status"]

    if move:
        move_paddle(state, move * player_speed(state["speed"]))
    # BOTH paddles are positioned before the segment moves, and both read the
    # segment's position as it stood at the end of the previous step.  Tracking
    # the replica afterwards instead would quietly hand the player a one-step
    # advantage over the machine on every single return.
    _track_replica(state)

    if state["serve"] > 0:
        state["serve"] -= 1
        return "serving"

    ball_x, ball_y = state["ball"]
    vx, vy = state["vel"]
    next_x = ball_x + vx
    event = "moved"

    # ---- the two faces, tested as PLANE CROSSINGS, not as overlaps ----------
    #
    # At level 9 the segment covers up to 4.34 px a step against a 3 px paddle,
    # so an overlap test would let it tunnel straight through — the classic bug
    # in every hand-written Pong.  Asking "did the leading edge cross the face
    # during this step" cannot miss, whatever the speed, and costs one compare.
    #
    # 4.34 and not 4.25: the figure is the worst REALISED step over the whole
    # deflection table, `hypot(51, 47)` on the steepest rung, and not
    # `LEVEL_SPEED[8]` — which is exact only while english cannot change the
    # speed, and english changes it by up to 3.96% after `scale` rounds.
    if vx < 0 and ball_x >= FACE_PRIMARY > next_x:
        hit_y = _crossing_y(state, FACE_PRIMARY, 0)
        if _overlaps(state["paddle"], hit_y):
            offset = hit_y + BALL_SUB // 2 - (state["paddle"] + PADDLE_H_SUB // 2)
            vx, vy = _english(offset, state["speed"], 1)
            state["vel"] = [vx, vy]
            # Restart the step from the face rather than reflecting the whole
            # travel: the segment left the paddle at a NEW angle, so the
            # distance it had left is not the distance it now covers.
            ball_x, ball_y = FACE_PRIMARY, hit_y
            next_x = ball_x + vx
            state["score"] += 1
            event = "sync"
            # The replica decides its apply point for THIS rally now, at the
            # moment the record is shipped.
            _draw_lag(state, random_below)
    elif vx > 0 and ball_x + BALL_SUB <= FACE_REPLICA < next_x + BALL_SUB:
        hit_y = _crossing_y(state, FACE_REPLICA, BALL_SUB)
        if _overlaps(state["replica"], hit_y):
            offset = hit_y + BALL_SUB // 2 - (state["replica"] + PADDLE_H_SUB // 2)
            # THE ONE ASYMMETRY IN THE PHYSICS, and it is on the machine's side
            # on purpose: the player's return is exact, the replica's
            # acknowledgement is applied a sub-pixel or two from where it
            # landed.  Without it a parked bat farms the game forever, because
            # a parked rally is an autonomous map on a finite state space and
            # every one of those cycles.
            offset = _apply_lag(offset, state["lag"])
            vx, vy = _english(offset, state["speed"], -1)
            state["vel"] = [vx, vy]
            ball_x, ball_y = FACE_REPLICA - BALL_SUB, hit_y
            next_x = ball_x + vx
            event = "ack"

    next_y, flipped = fold(ball_y + vy, BALL_TRAVEL)
    if flipped:
        state["vel"][1] = -vy
        if event == "moved":
            event = "wall"
    state["ball"] = [next_x, next_y]

    # ---- the two goal lines ------------------------------------------------
    #
    # Resolved on the TRAILING edge, so the segment is visibly all the way past
    # the paddle before anything is decided.  A miss called at the face would
    # freeze the court with the ball still touching the paddle it just beat,
    # which reads as a bug rather than a loss.
    if next_x + BALL_SUB <= 0:
        state["status"] = "broken"
        state["fatal"] = next_y
        return "broken"
    if next_x >= COURT_W_SUB:
        state["score"] += RESYNC_BONUS
        _serve(state, random_below)
        return "resync"
    return event
