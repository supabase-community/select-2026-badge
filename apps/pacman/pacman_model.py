"""Pure CURSOR.SQL maze state machine; no Badgeware imports, no floats.

THE THEME IS A TABLE SCAN and the nouns are the mechanics rather than a coat of
paint over them.  The player is a CURSOR walking the heap.  Every dot is a ROW
it has read; clearing the maze is a FULL SCAN COMPLETE.  A power pellet grants
SUPERUSER for a few seconds, during which the four ways a query dies run away
and can be consumed.  Being caught is QUERY CANCELED, and the badge names which
of the four did it.

Everything below is integer arithmetic on a fixed 20x13 grid.  Nothing here
reads a clock: the app owns the millisecond deadline and calls ``step`` at most
once per rendered frame (see ``next_step_clock``), and every duration in this
file is counted in TICKS so that a frozen board is genuinely frozen.
"""


# ---- directions -------------------------------------------------------------
#
# UP, RIGHT, DOWN, LEFT is a clockwise cycle, which is what makes OPPOSITE a
# +2.  Copied from `snake_model` deliberately: two grid games in one repository
# that number their directions differently is a bug waiting for the first
# person who reads them on the same afternoon.
UP = 0
RIGHT = 1
DOWN = 2
LEFT = 3
DIRECTIONS = (UP, RIGHT, DOWN, LEFT)
DELTAS = ((0, -1), (1, 0), (0, 1), (-1, 0))
OPPOSITE = (DOWN, LEFT, UP, RIGHT)

# THE FOUR KEYS ARE ABSOLUTE AND ALL FOUR ARE SPATIALLY TRUTHFUL.  This game
# has a real 2-D axis, unlike Snake, where A and C became relative turns
# because a snake travelling horizontally has nothing to be absolute about.
# Here the cursor may reverse at will, every cell is reachable from every
# heading, and so UP is up, DOWN is down, A is left and C is right on every
# frame of the game.  `pacman_view` names them that way on the intro and the
# pause card, and `test_pacman_app` pins all four.
KEY_LEFT = LEFT
KEY_RIGHT = RIGHT

# The classic junction preference, used ONLY to break a tie between two moves
# that are exactly the same distance from a ghost's target.  Up first, then
# left, then down, then right — the original arcade order, which is why two
# ghosts converging on the same corridor peel apart rather than stacking.
TURN_ORDER = (UP, LEFT, DOWN, RIGHT)


# ---- the maze ---------------------------------------------------------------
#
# ONE MAZE, hand-authored, 8 px cells in the 160x104 playfield below the status
# strip: 20 columns by 13 rows.  8 px is 3.0 mm on the panel and a 6 px sprite
# inside it is 2.25 mm, which is already at the edge of what reads on a lanyard;
# a finer grid would buy layout and lose the game.
#
#   #  wall          .  a row to scan (10)      o  power pellet (50, SUPERUSER)
#   D  pen door      G  pen interior            P  the cursor's start cell
#
# Four properties are pinned by `test_pacman.MazeTests` rather than trusted:
# the wall layout is mirror-symmetric; every open cell has at least two open
# neighbours (NO DEAD ENDS — a one-cell pocket in a game with four chasers is
# not a challenge, it is a trap); no 2x2 block is fully open, so the maze reads
# as corridors and not as a hall; and every open cell is reachable from the
# start, ghost cells included.
#
# ROW 6 IS THE TUNNEL and it is the only row with open cells on the border.
# Leaving column 0 arrives at column 19 and vice versa, which is Snake's board
# wrap and therefore code this repository has already proved.  The tunnel keeps
# its rows: a FULL SCAN means every cell, including the two the tunnel hides.
MAZE = (
    "####################",
    "#........##........#",
    "#o##.###.##.###.##o#",
    "#.##.###.##.###.##.#",
    "#..................#",
    "#.##.##.####.##.##.#",
    "....................",
    "#.##.##.#DD#.##.##.#",
    "#.......#GG#.......#",
    "#.##.##.####.##.##.#",
    "#.##.##.####.##.##.#",
    "#o.......P........o#",
    "####################",
)
COLS = 20
ROWS = 13

# Cell codes.  A byte per cell in a `bytearray` per row, so the live maze is
# thirteen small mutable buffers rather than 260 Python objects, and the
# renderer can read `cells[y][x]` without allocating anything.
WALL = 0
EMPTY = 1
DOT = 2
PELLET = 3
DOOR = 4
PEN = 5

_CHARS = {
    "#": WALL,
    ".": DOT,
    "o": PELLET,
    "D": DOOR,
    "G": PEN,
    "P": EMPTY,
    " ": EMPTY,
}

# THE CURSOR STARTS BELOW THE PEN, on the one cell of the maze that carries no
# row: standing on a row at spawn would score it before the player had moved.
START = (9, 11)
# The cell directly above the pen door.  A ghost inside the pen steers at this
# and nothing else, which is the whole of the "get out of the house" logic and
# is why no ghost needs a scripted exit path.
PEN_EXIT = (9, 6)


def _count(code):
    total = 0
    for row in MAZE:
        for char in row:
            if _CHARS[char] == code:
                total += 1
    return total


# Rows plus pellets: a pellet is a row that also grants SUPERUSER, so it counts
# towards the scan and FULL SCAN COMPLETE means the maze is genuinely empty.
TOTAL_DOTS = _count(DOT) + _count(PELLET)


def _build_cells():
    """A fresh mutable maze.  Never share one between runs."""
    return [bytearray(_CHARS[char] for char in row) for row in MAZE]


def cell_at(state, x, y):
    return state["cells"][y % ROWS][x % COLS]


# ---- the ladder -------------------------------------------------------------
#
# LEVEL IS GHOST SPEED AND NOTHING ELSE.  It is deliberately not a score
# multiplier: a row is worth ten rows at every level, so `SCAN 0640` means the
# same thing whoever set it and the stored record needs no companion field to
# be readable.  (Snake made the opposite choice for good reasons — its level
# prices every row — and pays for it with a `high_level` key beside the score.)
MIN_LEVEL = 1
MAX_LEVEL = 9
# Sixteenths of the cursor's own speed.  The cursor moves exactly one cell per
# tick; a ghost banks `LEVEL_RATE[level - 1]` sixteenths per tick and moves when
# it has banked a whole one, so ghost speed is a rational fraction of the
# player's and the arithmetic stays in integers.
#
# NO RUNG REACHES 16, and that is the design.  A ghost at or above the cursor's
# speed cannot be outrun in a straight corridor, which deletes the one thing
# that makes this genre fair — the player's ability to read a chase and leave.
# Level 9 is 15/16, fast enough that the gap closes over a long corridor and
# slow enough that a clean line still escapes.
LEVEL_RATE = (7, 8, 9, 10, 11, 12, 13, 14, 15)
RATE_UNIT = 16

# The movement interval, in milliseconds.  ABOVE THE FRAME PERIOD ON PURPOSE:
# Snake's device frame is ~22.8 ms (43.8 fps measured) and the browser runtime
# is faster, so an interval below the frame period would make "at most one step
# per frame" the real limit and the game would run at whatever rate the
# platform renders.  130 ms is above both, so the cursor covers 8 px every
# 130 ms — 61 px/s, about 2.6 seconds to cross the maze — on either.
STEP_MS = 130

LIVES = 3
DOT_POINTS = 10
PELLET_POINTS = 50
# 100, 200, 400, 800 within ONE superuser window, reset by the next pellet.
# Four ghosts in one window is 1500 with the pellet, a little over a tenth of
# the 1370 the rows themselves are worth, so hunting is a real strategy and not
# the only one.
GHOST_POINTS = (100, 200, 400, 800)

# SUPERUSER, in ticks.  48 x 130 ms is 6.2 s, close to the arcade's six, and
# the last twelve ticks (1.6 s) blink so the window's end is never a surprise.
SUPER_TICKS = 48
SUPER_WARN_TICKS = 12

# Chase and scatter, in ticks: 6.8 s of scatter against 19.5 s of chase, which
# is the arcade's 7/20 rhythm at this app's own tick.  A run opens in SCATTER so
# the first seconds of every life are survivable.
SCATTER = 0
CHASE = 1
SCATTER_TICKS = 52
CHASE_TICKS = 150

# How long a queued direction waits for a junction that can honour it.  THREE
# TICKS IS ~390 ms AND ABOUT TWO CELLS OF LEAD.  A press that arrives while the
# cursor is mid-corridor is what a player actually does — they aim at the turn
# they can see — and dropping it is the single thing that makes a maze game
# feel broken.  Snake's queue never expires because every perpendicular turn is
# always legal there; here most are not, so an unbounded queue would turn a
# stale press into a surprise turn half a maze later.
QUEUE_TICKS = 3

# The beat after QUERY CANCELED, and after it the cursor and all four are back
# at their start cells.  Nothing moves during it: the player has just lost a
# life and needs to see where everything now is.
RESPAWN_TICKS = 12
# A consumed ghost is simply gone for this long and then reappears at its start
# cell.  There is deliberately no eyes-return-to-base animation: it is the most
# expensive-to-verify part of the original and it changes no outcome.
GHOST_RESPAWN_TICKS = 24

# Ghost lifecycle.
HUNT = 0
FLEE = 1
EATEN = 2

# ---- the four ways a query dies ---------------------------------------------
#
# The joke is the point, so the names are printed on the intro in their own
# colours and the death screen names the one that did it.  Each personality is
# a TARGET CELL and a few lines of arithmetic; the movement rule underneath
# them is identical, which is what makes four of them cheap.
GHOST_NAMES = ("DEADLOCK", "TIMEOUT", "ROLLBACK", "OOM")
# Where each starts, and where a consumed one comes back.  DEADLOCK begins
# outside, on the tunnel row above the door, exactly as the arcade's red ghost
# does; the other three begin on the door and inside the pen and let themselves
# out.
GHOST_STARTS = ((9, 6), (10, 7), (9, 8), (10, 8))
# Ticks each one waits before it starts moving, on a fresh life as well as a
# fresh run: 0, 1.6 s, 3.9 s and 6.5 s.  Four chasers released at once is not a
# level-1 game.
GHOST_HOLD = (0, 12, 30, 50)
# The corner each retreats to during SCATTER.  Opposite corners for the two
# that hunt hardest, so a scatter phase genuinely opens the middle.
SCATTER_TARGETS = ((18, 1), (1, 1), (18, 11), (1, 11))
# TIMEOUT aims this many cells ahead of the cursor's heading.
TIMEOUT_LEAD = 4
# OOM gives up inside this radius, as a SQUARED distance so nothing takes a
# root: 8 cells, which at 8 px a cell is two thirds of the maze's width.
OOM_SHY_SQ = 64
# How often ROLLBACK re-rolls the cell it is heading for.  8 ticks is about a
# second — long enough to commit to a corridor, short enough that it never
# settles into a pursuit.
DRIFT_TICKS = 8


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


def level_rate(level):
    """Sixteenths of the cursor's speed a ghost covers per tick."""
    return LEVEL_RATE[clamp_level(level) - 1]


def distance_sq(ax, ay, bx, by):
    """Squared distance between two cells, FOLDED ACROSS THE TUNNEL.

    The horizontal fold is what makes the tunnel a real feature rather than a
    decoration: without it a ghost one cell from the player through the wrap
    reads as nineteen cells away and calmly walks the long way round, and the
    player learns that the tunnel is a free escape.  The vertical axis is not
    folded because rows 0 and 12 are solid wall, so no path ever wraps there.
    """
    dx = ax - bx
    if dx < 0:
        dx = -dx
    if COLS - dx < dx:
        dx = COLS - dx
    dy = ay - by
    if dy < 0:
        dy = -dy
    return dx * dx + dy * dy


# ---- movement legality ------------------------------------------------------


def player_can(state, x, y, direction):
    """Whether the cursor may leave ``(x, y)`` in ``direction``.

    Walls stop it, and so do the pen door and the pen: a cursor that could sit
    inside the house would be untouchable, which is not a game.
    """
    dx, dy = DELTAS[direction]
    code = state["cells"][(y + dy) % ROWS][(x + dx) % COLS]
    return code == EMPTY or code == DOT or code == PELLET


def ghost_can(state, x, y, direction):
    """Whether a ghost may leave ``(x, y)`` in ``direction``.

    Ghosts pass the door and the pen, but ONLY OUTWARDS: a ghost may enter a
    door or pen cell only when it is standing on one already.  That single
    condition is the entire "cannot go home" rule, and it is why a consumed
    ghost is respawned by the clock rather than pathed back.
    """
    dx, dy = DELTAS[direction]
    code = state["cells"][(y + dy) % ROWS][(x + dx) % COLS]
    if code == WALL:
        return False
    if code == DOOR or code == PEN:
        here = state["cells"][y % ROWS][x % COLS]
        return here == DOOR or here == PEN
    return True


def in_pen(state, x, y):
    here = state["cells"][y % ROWS][x % COLS]
    return here == DOOR or here == PEN


# ---- construction -----------------------------------------------------------


def _new_ghost(index):
    return {
        "index": index,
        "x": GHOST_STARTS[index][0],
        "y": GHOST_STARTS[index][1],
        # Where it stood BEFORE this tick's move, so a head-on swap with the
        # cursor is a collision rather than two things passing through each
        # other.  On a grid that case is otherwise invisible and it is the one
        # every hand-written maze game gets wrong.
        "px": GHOST_STARTS[index][0],
        "py": GHOST_STARTS[index][1],
        "dir": UP,
        "state": HUNT,
        "accum": 0,
        "hold": GHOST_HOLD[index],
        "respawn": 0,
        # Latched by a mode flip and consumed by the next move: the arcade's
        # "everything turns round" tell, which is the only way a player can see
        # that scatter has started.
        "reverse": False,
    }


def _reset_positions(state):
    """Put the cursor and all four back where a life begins."""
    state["x"], state["y"] = START
    state["direction"] = LEFT
    state["queued"] = LEFT
    state["queue_left"] = 0
    state["ghosts"] = [_new_ghost(index) for index in range(len(GHOST_NAMES))]
    state["mode"] = SCATTER
    state["mode_left"] = SCATTER_TICKS
    state["super"] = 0
    state["combo"] = 0


def new_game(level, random_below=None):
    """A fresh run.  ``random_below`` is accepted and unused at construction.

    Kept in the signature because every other app in this repository builds its
    state with an injected RNG and a caller that has to remember which one does
    not is a caller that will get it wrong.  ROLLBACK's first drift target is
    the middle of the maze, deterministically, and is re-rolled by ``step``.
    """
    level = clamp_level(level)
    state = {
        "cols": COLS,
        "rows": ROWS,
        "level": level,
        # Cached because every ghost reads it every tick and the level cannot
        # change mid-run.
        "rate": level_rate(level),
        "cells": _build_cells(),
        "dots": TOTAL_DOTS,
        "score": 0,
        "lives": LIVES,
        "status": "playing",
        "tick": 0,
        "respawn": 0,
        # The value the last consumed ghost paid, so the view can show it
        # without re-deriving the combo ladder.
        "last_ghost": 0,
        # Which of the four ended the run, so QUERY CANCELED can name it.  -1
        # until something does.
        "caught_by": -1,
        "drift": (COLS // 2, ROWS // 2),
    }
    _reset_positions(state)
    return state


# ---- input ------------------------------------------------------------------


def queue_direction(state, direction):
    """Queue the cursor's next heading.

    NO REVERSAL GUARD, unlike Snake.  Turning round is legal and useful in a
    maze — it is how a player escapes a corridor with a ghost at each end — so
    the only thing this refuses is a direction that is not one, or a press
    aimed at a run that is not live.

    The direction is held for ``QUEUE_TICKS`` ticks and applied on the first of
    them where it is actually legal, so a press aimed at a junction one or two
    cells ahead is honoured when the cursor arrives rather than dropped for
    being early.  It is never gated by the app's arming window: a direction is
    never destructive and is corrected by the next press.
    """
    if state["status"] != "playing" or direction not in DIRECTIONS:
        return False
    state["queued"] = direction
    state["queue_left"] = QUEUE_TICKS
    return True


# ---- ghost brains -----------------------------------------------------------


def ghost_target(state, ghost):
    """The cell this ghost is steering at right now.

    Four personalities, each a couple of lines, sharing one movement rule.  A
    target is a CELL and need not be reachable or even open — the arcade aims
    ghosts into walls constantly and the pathing rule copes, because it only
    ever compares the cells it can actually reach this step.
    """
    index = ghost["index"]
    if in_pen(state, ghost["x"], ghost["y"]):
        # Inside the house nothing else matters: steer at the cell above the
        # door and the ordinary rule walks it out.
        return PEN_EXIT
    if state["mode"] == SCATTER:
        return SCATTER_TARGETS[index]
    if index == 0:
        # DEADLOCK wants exactly the row you are on, and comes straight at it.
        return (state["x"], state["y"])
    if index == 1:
        # TIMEOUT is already waiting where the query was going: four cells
        # along the cursor's heading.  The column folds through the tunnel, the
        # row clamps, because there is no vertical wrap to fold into.
        dx, dy = DELTAS[state["direction"]]
        return (
            (state["x"] + dx * TIMEOUT_LEAD) % COLS,
            max(0, min(ROWS - 1, state["y"] + dy * TIMEOUT_LEAD)),
        )
    if index == 2:
        # ROLLBACK never finishes what it starts: it commits to a cell for
        # DRIFT_TICKS and then abandons it for another.  It is the one that
        # arrives from the direction nobody was watching.
        return state["drift"]
    # OOM grows towards you while there is room and gives up when it runs out,
    # falling back to its own corner until you are far away again.
    if distance_sq(ghost["x"], ghost["y"], state["x"], state["y"]) > OOM_SHY_SQ:
        return (state["x"], state["y"])
    return SCATTER_TARGETS[3]


def _legal_moves(state, ghost):
    """The directions this ghost may take, in the classic tie-break order.

    A list, allocated once per ghost move.  This is the MODEL, not the draw
    path: at four ghosts and roughly eight ticks a second it is thirty small
    lists a second against a render loop that must allocate nothing, and the
    readability is worth more here than the allocation is.
    """
    moves = []
    for direction in TURN_ORDER:
        if ghost_can(state, ghost["x"], ghost["y"], direction):
            moves.append(direction)
    return moves


def _advance_ghost(state, ghost, direction):
    dx, dy = DELTAS[direction]
    ghost["dir"] = direction
    ghost["x"] = (ghost["x"] + dx) % COLS
    ghost["y"] = (ghost["y"] + dy) % ROWS


def _step_ghost(state, ghost, random_below):
    moves = _legal_moves(state, ghost)
    if not moves:
        return
    back = OPPOSITE[ghost["dir"]]
    if ghost["reverse"]:
        # A latched reversal is spent whether or not it can be taken, so a
        # ghost pinned in a corridor does not turn round three cells later.
        ghost["reverse"] = False
        if back in moves:
            _advance_ghost(state, ghost, back)
            return
    forward = [direction for direction in moves if direction != back]
    if not forward:
        # A dead end would be the only way here, and the maze has none — but a
        # ghost that has just reversed into a stub must still be able to leave.
        forward = moves
    if ghost["state"] == FLEE:
        # A fleeing ghost does not steer, it bolts: a uniform choice among the
        # ways it did not come from.  That is the arcade's rule and it is what
        # makes hunting a judgement rather than a calculation.
        _advance_ghost(state, ghost, forward[random_below(len(forward))])
        return
    target_x, target_y = ghost_target(state, ghost)
    choice = forward[0]
    best = None
    for direction in forward:
        dx, dy = DELTAS[direction]
        score = distance_sq(
            (ghost["x"] + dx) % COLS, (ghost["y"] + dy) % ROWS, target_x, target_y
        )
        # STRICTLY smaller, so a tie keeps the earlier entry and TURN_ORDER is
        # the tie-break rather than an accident of iteration.
        if best is None or score < best:
            best = score
            choice = direction
    _advance_ghost(state, ghost, choice)


def _move_ghosts(state, random_below):
    for ghost in state["ghosts"]:
        ghost["px"] = ghost["x"]
        ghost["py"] = ghost["y"]
        if ghost["state"] == EATEN:
            ghost["respawn"] -= 1
            if ghost["respawn"] <= 0:
                start = GHOST_STARTS[ghost["index"]]
                ghost["x"] = start[0]
                ghost["y"] = start[1]
                ghost["px"] = start[0]
                ghost["py"] = start[1]
                ghost["state"] = HUNT
                ghost["dir"] = UP
                ghost["accum"] = 0
                ghost["reverse"] = False
            continue
        if ghost["hold"] > 0:
            ghost["hold"] -= 1
            continue
        rate = state["rate"]
        if ghost["state"] == FLEE:
            # Half speed while fleeing, which is the arcade's number and the
            # only reason a consumed ghost is ever catchable at level 9.
            rate = max(1, rate >> 1)
        ghost["accum"] += rate
        if ghost["accum"] < RATE_UNIT:
            continue
        # No `while`: the rate can never exceed RATE_UNIT, so a ghost takes at
        # most one cell per tick and can never tunnel through the cursor.
        ghost["accum"] -= RATE_UNIT
        _step_ghost(state, ghost, random_below)


# ---- timers -----------------------------------------------------------------


def _advance_timers(state, random_below):
    if state["super"] > 0:
        state["super"] -= 1
        if state["super"] == 0:
            for ghost in state["ghosts"]:
                if ghost["state"] == FLEE:
                    ghost["state"] = HUNT
                    ghost["reverse"] = True
    else:
        # THE CHASE/SCATTER CLOCK IS FROZEN WHILE SUPERUSER HOLDS, which is the
        # arcade's rule.  Without it a scatter phase can expire unseen inside a
        # power window and the ghosts come back out of it in chase with no
        # warning at all.
        state["mode_left"] -= 1
        if state["mode_left"] <= 0:
            state["mode"] = CHASE if state["mode"] == SCATTER else SCATTER
            state["mode_left"] = (
                CHASE_TICKS if state["mode"] == CHASE else SCATTER_TICKS
            )
            for ghost in state["ghosts"]:
                ghost["reverse"] = True
    if state["tick"] % DRIFT_TICKS == 0:
        state["drift"] = (random_below(COLS), random_below(ROWS))


# ---- the tick ---------------------------------------------------------------


def _catch(state, index):
    state["caught_by"] = index
    state["lives"] -= 1
    state["super"] = 0
    if state["lives"] <= 0:
        state["status"] = "dead"
        return "caught"
    _reset_positions(state)
    state["respawn"] = RESPAWN_TICKS
    return "caught"


def step(state, random_below):
    """Advance the world one movement tick and name what happened.

    Returns exactly ONE event, because one tick is one thing that happened and
    a caller handed a list of them will get the priority wrong.  The order is
    fixed and the reasoning is in it:

    ``cleared`` outranks ``caught`` — the scan finished before the ghosts had
    their move, and a player who reads the last row while something is landing
    on them has earned it.  ``caught`` outranks ``ghost`` — one of the four was
    still dangerous, and the consumed ones are still paid for on the way past.
    """
    if state["status"] != "playing":
        return state["status"]
    if state["respawn"] > 0:
        # A frozen beat after QUERY CANCELED.  Nothing moves and no timer runs:
        # the player has just lost a life and is reading the new board.
        state["respawn"] -= 1
        return "respawning"

    state["tick"] += 1
    _advance_timers(state, random_below)

    prev_x = state["x"]
    prev_y = state["y"]
    queued = state["queued"]
    if queued != state["direction"] and state["queue_left"] > 0:
        if player_can(state, prev_x, prev_y, queued):
            state["direction"] = queued
            state["queue_left"] = 0
        else:
            state["queue_left"] -= 1
            if state["queue_left"] == 0:
                state["queued"] = state["direction"]

    event = "blocked"
    if player_can(state, prev_x, prev_y, state["direction"]):
        dx, dy = DELTAS[state["direction"]]
        state["x"] = (prev_x + dx) % COLS
        state["y"] = (prev_y + dy) % ROWS
        event = "moved"

    code = state["cells"][state["y"]][state["x"]]
    if code == DOT:
        state["cells"][state["y"]][state["x"]] = EMPTY
        state["dots"] -= 1
        state["score"] += DOT_POINTS
        event = "dot"
    elif code == PELLET:
        state["cells"][state["y"]][state["x"]] = EMPTY
        state["dots"] -= 1
        state["score"] += PELLET_POINTS
        state["super"] = SUPER_TICKS
        state["combo"] = 0
        for ghost in state["ghosts"]:
            if ghost["state"] == HUNT:
                ghost["state"] = FLEE
                ghost["reverse"] = True
        event = "pellet"

    if state["dots"] <= 0:
        state["status"] = "won"
        return "cleared"

    _move_ghosts(state, random_below)

    caught_by = -1
    eaten = 0
    for ghost in state["ghosts"]:
        if ghost["state"] == EATEN:
            continue
        # Two ways to meet: land on the same cell, or trade cells head-on.  The
        # second is the one a grid hides, and without it a cursor and a ghost
        # walking into each other pass straight through.
        same = ghost["x"] == state["x"] and ghost["y"] == state["y"]
        swap = (
            ghost["x"] == prev_x
            and ghost["y"] == prev_y
            and ghost["px"] == state["x"]
            and ghost["py"] == state["y"]
        )
        if not (same or swap):
            continue
        if ghost["state"] == FLEE:
            value = GHOST_POINTS[min(state["combo"], len(GHOST_POINTS) - 1)]
            state["combo"] += 1
            state["score"] += value
            state["last_ghost"] = value
            ghost["state"] = EATEN
            ghost["respawn"] = GHOST_RESPAWN_TICKS
            eaten += 1
        else:
            caught_by = ghost["index"]

    if caught_by >= 0:
        # A consumed ghost on the same tick is still paid for: the score above
        # already banked it, and taking it back because a second ghost arrived
        # would be arithmetic the player cannot see.
        return _catch(state, caught_by)
    if eaten:
        return "ghost"
    return event


# ---- probes -----------------------------------------------------------------


def ahead_cell(state):
    """The first cell the cursor could actually step into, heading first.

    Used by the FULL SCAN probe below and by the tests; it never returns a wall
    and never returns the cell the cursor is standing on.
    """
    for direction in (state["direction"],) + DIRECTIONS:
        if player_can(state, state["x"], state["y"], direction):
            dx, dy = DELTAS[direction]
            return ((state["x"] + dx) % COLS, (state["y"] + dy) % ROWS)
    raise AssertionError("the cursor is walled in, which this maze forbids")


def prime_full_scan(state):
    """Strip the maze to one row, directly ahead of the cursor.

    The FULL SCAN COMPLETE probe: one legal step away from a finished scan,
    with the score already carrying everything the stripped cells were worth,
    so the number on the win screen is the number the app would really show.
    Returns the cell that is left.
    """
    keep = ahead_cell(state)
    gained = 0
    for y in range(ROWS):
        row = state["cells"][y]
        for x in range(COLS):
            if x == keep[0] and y == keep[1]:
                continue
            if row[x] == DOT:
                row[x] = EMPTY
                gained += DOT_POINTS
            elif row[x] == PELLET:
                row[x] = EMPTY
                gained += PELLET_POINTS
    # The kept cell is normally already a row and is simply left alone.  It is
    # forced to one only when the cursor happens to be facing an empty cell,
    # which a mid-run caller can arrange; the run then ends one row above the
    # maze's true maximum, and that is the probe's business rather than the
    # game's.
    if state["cells"][keep[1]][keep[0]] not in (DOT, PELLET):
        state["cells"][keep[1]][keep[0]] = DOT
    state["score"] += gained
    state["dots"] = 1
    return keep
