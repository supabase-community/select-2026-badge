"""Pure bounded Snake state machine; no Badgeware imports."""


UP = 0
RIGHT = 1
DOWN = 2
LEFT = 3
# UP, RIGHT, DOWN, LEFT is a clockwise cycle, which is what makes OPPOSITE a
# +2 and the two steering tables below a +/-1 apart from their one exception.
DIRECTIONS = (UP, RIGHT, DOWN, LEFT)
DELTAS = ((0, -1), (1, 0), (0, 1), (-1, 0))
OPPOSITE = (DOWN, LEFT, UP, RIGHT)

# ---- the two side keys, per heading -----------------------------------------
#
# WHAT A AND C MEAN IS A TABLE, NOT A ROTATION, and the table is the owner's
# 2026-08-17 ruling written out rather than derived:
#
#   heading    A        C          because
#   -------    -----    -----      -------------------------------------------
#   UP         LEFT     RIGHT      vertical: A is the SCREEN's left
#   DOWN       LEFT     RIGHT      vertical: A is the SCREEN's left
#   RIGHT      UP       DOWN       horizontal: A is the SNAKE's left
#   LEFT       DOWN     UP         horizontal: A is the SNAKE's left
#
# So the keys are ABSOLUTE while the snake travels vertically and RELATIVE
# while it travels horizontally.  Going up the two agree, which is why this
# differs from the pure relative scheme it replaced on exactly one heading --
# DOWN, where riding the snake's shoulder used to send A to the right of the
# screen and a thumb reaching for "left" got the opposite.  Going horizontally
# there is nothing to be absolute about: screen-left is either the way the
# snake is already going or a reversal, so the snake's own left is the only
# reading that can steer.
#
# Every entry is perpendicular to its heading, so no A or C press can ever be a
# reversal or a no-op, and A and C are always each other's opposite: the two
# keys always offer the two legal turns.  `test_snake` pins all three of those
# properties against DELTAS rather than against these names, because a table is
# exactly the kind of thing a later edit renumbers by accident.
STEER_LEFT = (LEFT, UP, LEFT, DOWN)
STEER_RIGHT = (RIGHT, DOWN, RIGHT, UP)
MIN_LEVEL = 1
MAX_LEVEL = 9
# THE LADDER LIVES HERE, not in the app, because the level is game data now:
# it prices every row (`step`) and sizes the bonus window (below).  The app
# re-exports it as SPEEDS_MS and owns only which rung the intro is standing on.
LEVEL_MS = (300, 240, 200, 160, 125, 95, 70, 45, 25)

# ---- the bonus critters ----------------------------------------------------
#
# After every fifth row a critter appears somewhere free.  It pays and does NOT
# grow the snake, so it is always worth a detour, and it is worth MORE the
# sooner it is reached.  Skipping one is not free either: the table bloats and
# the next one reclaims more.  Snake II's own rules, and its own numbers.
BONUS_EVERY = 5
# TWENTY TICKS, WHICH IS THE ORIGINAL'S NUMBER, not a duration in seconds.
# This app shipped a five-seconds-of-real-time window first, on the argument
# that a flat tick count leaves a level-9 critter only 500 ms of wall clock and
# so charges the top of the ladder for a bonus it cannot reach.  That argument
# is sound and Snake II does not care: the bug appears every five foods and
# vanishes after twenty ticks at every level, which is exactly why the flex was
# never bonus farming at level 9.  The owner asked for the original's feel, so
# fidelity wins and the consequence is deliberate -- at speed most critters go
# unclaimed, the bloat ladder climbs, and the ones you do reach are enormous.
# Nothing here reads a clock; `step` counts.
BONUS_TICKS = 20
# THE CRITTER IS A DIFFERENT THING EACH TIME, which is also the original: the
# most faithful published clone recreated the pixel art of "each bonus point
# food type" rather than one.  All five of ours are operations that PAY WITHOUT
# ADDING A ROW, which is the mechanical rule the critter needs -- none of them
# can grow the snake and stay honest.  The tag is what the status strip has
# room for; the name is what it means.
BONUS_TAGS = ("VAC", "IDX", "HIT", "REP", "RPC")
BONUS_NAMES = ("VACUUM", "INDEX SCAN", "CACHE HIT", "READ REPLICA", "RPC CALL")
# A fresh critter pays `level * BONUS_UNIT` at the instant it appears -- four
# rows' worth, so it is several goodies but never the whole game -- and each
# skipped one adds `level * BLOAT_STEP` to the next, up to BLOAT_MAX skips.
# Claiming one reclaims the bloat with it and resets the ladder to fresh.
BONUS_UNIT = 4
BLOAT_STEP = 2
BLOAT_MAX = 3


def next_step_clock(now, last_step, interval, ticks_diff, ticks_add):
    """Return the next movement clock when due, otherwise ``None``.

    Advancing by the configured interval avoids quantising a 25 ms setting to
    every second 22.8 ms render frame.  At most one movement is still emitted
    per app frame.  If a long hitch leaves a second full interval outstanding,
    reset to ``now`` so later frames do not replay a dangerous backlog.
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


def next_animation_frame(frame, frames, now, clock, interval, ticks_diff, ticks_add):
    """Advance a looping sprite animation on its own millisecond deadline.

    Shares ``next_step_clock``'s semantics deliberately: at most one frame per
    rendered frame, and a long hitch is discarded rather than replayed as a
    burst.  Returns the new ``(frame, clock)`` pair.
    """
    due = next_step_clock(now, clock, interval, ticks_diff, ticks_add)
    if due is None:
        return frame, clock
    return (frame + 1) % frames, due


def _free_cell(body, cols, rows, random_below):
    free_count = cols * rows - len(body)
    if free_count <= 0:
        return None
    target = random_below(free_count)
    occupied = set((cell[0], cell[1]) for cell in body)
    seen = 0
    for y in range(rows):
        for x in range(cols):
            if (x, y) in occupied:
                continue
            if seen == target:
                return [x, y]
            seen += 1
    raise AssertionError("free-cell accounting drift")


def clamp_level(level):
    """Levels are 1..9 and nothing else, wherever they arrive from."""
    return max(MIN_LEVEL, min(MAX_LEVEL, int(level)))


def bonus_peak(level, bloat):
    """What the next critter is worth the instant it appears."""
    return clamp_level(level) * (BONUS_UNIT + BLOAT_STEP * min(bloat, BLOAT_MAX))


def bonus_worth(peak, left, window):
    """Its value now: linear in the moves it has left, never below one.

    The floor matters.  A critter that decays to nothing is one the player
    stops reading halfway through its life, and the point of the countdown is
    that it is still a decision at the end.
    """
    if left <= 0:
        return 0
    return max(1, peak * left // window)


def _bonus_window(state):
    """Kept as a function because the window used to depend on the level, and
    the call sites read better asking than indexing."""
    return BONUS_TICKS


def _pick_kind(previous, random_below):
    """A different critter from the last one, every time.

    Never the same twice running: with five kinds a plain draw repeats one time
    in five, and "a different database thing each time" is the point.  Picking
    from the other four makes the variety a guarantee rather than a
    probability, and costs one modulo.
    """
    if previous < 0:
        return random_below(len(BONUS_TAGS))
    return (previous + 1 + random_below(len(BONUS_TAGS) - 1)) % len(BONUS_TAGS)


def _clear_bonus(state, reclaimed):
    """Take the critter off the board, and remember whether it was reached.

    Claiming reclaims the accumulated bloat with it; letting one expire adds to
    it, which is what makes the next one worth more.  ``bonus_kind`` is left
    alone deliberately: it is the memory of the last critter, and the next
    spawn reads it to pick a different one.
    """
    state["bonus"] = None
    state["bonus_left"] = 0
    state["bonus_peak"] = 0
    state["bonus_value"] = 0
    state["bloat"] = 0 if reclaimed else min(state["bloat"] + 1, BLOAT_MAX)


def _spawn_bonus(state, random_below):
    cell = _free_cell(
        _occupied(state), state["cols"], state["rows"], random_below
    )
    if cell is None:
        return
    kind = _pick_kind(state["bonus_kind"], random_below)
    state["bonus"] = cell
    state["bonus_kind"] = kind
    # The tag is stored, not looked up by the renderer, for the same reason
    # `bonus_value` is: the view stays a view and reads state like any other
    # field.
    state["bonus_tag"] = BONUS_TAGS[kind]
    state["bonus_left"] = _bonus_window(state)
    state["bonus_peak"] = bonus_peak(state["level"], state["bloat"])
    state["bonus_value"] = state["bonus_peak"]


def _occupied(state):
    """Every cell something already stands on: body, food and critter.

    ``_free_cell`` counts the list it is given, so food and the critter must be
    in it or the two marks can land on top of each other -- which would make
    one step both a meal and a reclaim, and only one of those can be returned.

    A mark the head has just moved onto is skipped, because it is already in
    the body: `_free_cell` derives its free count from the length of this list,
    so one cell counted twice makes that arithmetic wrong.
    """
    cells = list(state["body"])
    for cell in (state["food"], state["bonus"]):
        if cell is not None and cell not in cells:
            cells.append(cell)
    return cells


def new_game(cols, rows, random_below, level=MIN_LEVEL):
    if cols < 7 or rows < 3:
        raise ValueError("grid too small")
    center_x = cols // 2
    center_y = rows // 2
    body = [[center_x - offset, center_y] for offset in range(5)]
    return {
        "cols": cols,
        "rows": rows,
        "body": body,
        "direction": RIGHT,
        "queued": RIGHT,
        "turn_locked": False,
        "food": _free_cell(body, cols, rows, random_below),
        "score": 0,
        # Rows eaten, which is NOT the score once the level prices them, and is
        # what the critter's every-fifth-row clock counts.
        "eaten": 0,
        "bonus": None,
        # -1 is "no critter has appeared yet", so the first one may be any of
        # the five and every one after it differs from the one before.
        "bonus_kind": -1,
        "bonus_tag": "",
        "bonus_left": 0,
        "bonus_peak": 0,
        # Kept in the state rather than recomputed by the renderer, so the view
        # stays a renderer: it reads this the way it reads the score.
        "bonus_value": 0,
        "bloat": 0,
        # THE WAGER, fixed for the whole run.  It sets the movement interval in
        # the app AND the price of every row, so a level-2 run cannot reach a
        # level-9 run's score however long it lives.  Nothing may change it
        # mid-run: that is the entire point of choosing it on the intro.
        "level": clamp_level(level),
        "status": "playing",
        # The cell the head died trying to enter, so the death screen can answer
        # "what killed me?" — it is never part of the body, which is why the
        # renderer cannot work it out for itself.
        "fatal": None,
    }


def queue_direction(state, direction):
    if state["status"] != "playing" or direction not in DIRECTIONS:
        return False
    if state["turn_locked"] or direction == OPPOSITE[state["direction"]]:
        return False
    state["queued"] = direction
    state["turn_locked"] = True
    return True


def queue_steer(state, table):
    """Queue what one of the two side keys means from the current heading.

    ``table`` is ``STEER_LEFT`` or ``STEER_RIGHT``; the wrappers below are the
    call sites, because "left" reads differently to a player and to the screen
    and the table is where that difference is resolved.

    Read from ``direction`` rather than ``queued`` because ``direction`` is what
    the player can see.  The choice cannot change an outcome: the two differ
    only while ``turn_locked`` is set, and a locked turn is refused whichever
    heading it was computed from.

    One press is one quarter turn, and the lock means the second press inside a
    movement tick is dropped rather than banked -- so a fast double tap of A is
    one turn, not a U-turn stored up for the next two ticks.
    """
    return queue_direction(state, table[state["direction"]])


def queue_steer_left(state):
    """The A key: the screen's left going vertically, the snake's going across."""
    return queue_steer(state, STEER_LEFT)


def queue_steer_right(state):
    """The C key: the screen's right going vertically, the snake's going across."""
    return queue_steer(state, STEER_RIGHT)


def step(state, random_below):
    if state["status"] != "playing":
        return state["status"]
    direction = state["queued"]
    dx, dy = DELTAS[direction]
    head = state["body"][0]
    new_head = [(head[0] + dx) % state["cols"], (head[1] + dy) % state["rows"]]
    ate = state["food"] is not None and new_head == state["food"]
    collision_body = state["body"] if ate else state["body"][:-1]
    if new_head in collision_body:
        state["status"] = "dead"
        state["turn_locked"] = False
        state["fatal"] = new_head
        return "dead"

    state["direction"] = direction
    state["turn_locked"] = False
    state["body"].insert(0, new_head)
    if not ate:
        state["body"].pop()

    # THE CRITTER IS RESOLVED BEFORE THE MEAL, and the two can never coincide:
    # `_occupied` keeps them off each other's cells, so one move is a reclaim
    # or a meal or neither, and one event can describe it.
    claimed = state["bonus"] is not None and new_head == state["bonus"]
    if claimed:
        # PURE PROFIT, NO TAIL PENALTY.  The body is not extended here, which
        # is the whole reason a detour across the board is worth taking.
        state["score"] += state["bonus_value"]
        _clear_bonus(state, True)
    elif state["bonus"] is not None:
        state["bonus_left"] -= 1
        if state["bonus_left"] <= 0:
            _clear_bonus(state, False)
        else:
            state["bonus_value"] = bonus_worth(
                state["bonus_peak"], state["bonus_left"], _bonus_window(state)
            )

    if not ate:
        return "vacuum" if claimed else "moved"

    # THE PRICE OF A ROW IS THE LEVEL.  One goody is worth `level`, so the
    # ladder is a wager and not a difficulty slider: the same run played at 9
    # scores nine times what it scores at 1, and the badge's stored record
    # carries the level it was set at because the number means nothing without
    # it.
    state["score"] += state["level"]
    state["eaten"] += 1
    if len(state["body"]) == state["cols"] * state["rows"]:
        state["food"] = None
        state["bonus"] = None
        state["bonus_value"] = 0
        state["status"] = "won"
        return "won"
    state["food"] = _free_cell(
        _occupied(state), state["cols"], state["rows"], random_below
    )
    if state["eaten"] % BONUS_EVERY == 0 and state["bonus"] is None:
        _spawn_bonus(state, random_below)
    return "ate"


def serpentine_win_state(cols, rows, level=MIN_LEVEL):
    """Return a legal one-food-from-full state for the max-length probe."""
    path = []
    for y in range(rows):
        xs = range(cols) if y % 2 == 0 else range(cols - 1, -1, -1)
        for x in xs:
            path.append([x, y])
    body = list(reversed(path[:-1]))
    head = body[0]
    food = path[-1]
    dx = food[0] - head[0]
    dy = food[1] - head[1]
    direction = RIGHT if dx == 1 else LEFT if dx == -1 else DOWN if dy == 1 else UP
    return {
        "cols": cols,
        "rows": rows,
        "body": body,
        "direction": direction,
        "queued": direction,
        "turn_locked": False,
        "food": food,
        # Priced at the level like any other run, so the probe's number is the
        # one the app would really show.  The default keeps it at 255.
        "score": (len(body) - 5) * clamp_level(level),
        "level": clamp_level(level),
        "eaten": len(body) - 5,
        # A board with one free cell has nowhere to put a critter, which is why
        # the probe carries none rather than an unreachable one.
        "bonus": None,
        "bonus_kind": -1,
        "bonus_tag": "",
        "bonus_left": 0,
        "bonus_peak": 0,
        "bonus_value": 0,
        "bloat": 0,
        "status": "playing",
        "fatal": None,
    }
