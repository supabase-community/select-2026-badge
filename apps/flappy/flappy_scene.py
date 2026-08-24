"""The POOLER.SQL scene: pure integer geometry for the room the game flies in.

No Badgeware imports, no clock reads, no allocation in anything the view calls
per frame.  This file answers geometry questions with integers and hands back
tuples that were built at IMPORT time; the view walks them and draws.  That
split is the whole reason the scene is testable in the fast lane: a parallax
offset, a rack silhouette and a keepalive ramp are arithmetic, and arithmetic
can be pinned to an expected value without a screen.

WHY THERE IS A SCENE AT ALL.  The game shipped flying through flat panel, and
the owner asked the obvious question: "is there a background scene or anything?
I think the original flappy has a small backdrop with a paralax effect."  The
theme answers what the scene should BE without inventing anything: the player
is a client connection, the pipes are the pool's connection slots, and a pool
lives in a room full of racks.  So the backdrop is that room, seen from inside
it, and it moves at a fraction of the world's speed because it is further away.

THE ONE HARD CONSTRAINT IS LEGIBILITY, AND IT IS NOT SOLVED BY BANDING.  The
first instinct is to confine the scene to a band the client never enters.  There
is no such band: the client is alive anywhere between the two rails, so it can
occupy any world row from ``CEILING`` to ``FLOOR``.  The gap's top edge alone
ranges over 10..94 across the ladder (`flappy_model.gap_band`).  So the scene is
kept readable by CONTRAST ORDERING instead, and the ordering is a rule this file
enforces by construction:

    every colour in the scene is dimmer than ``FlappyView.pipe``

The pipes are the thing the player must see, the collars are the thing he aims
at, and the client is the badge's own green.  Those three are the only bright
things on the panel, in that order, and nothing in the room is allowed to reach
the bottom of that stack.  `flappy/tests/test_flappy_scene.py` asserts it over
every colour this module names, so a later contributor cannot brighten a rack
past a pipe by eye.

Lengths here are PIXELS unless a name says ``_sub``.  The parallax offsets take
the model's own ``scrolled`` odometer in sub-pixels, because deriving the room's
position from the world's travel rather than from a frame counter is what makes
a paused room as still as a paused pipe.
"""

import flappy_model as M


# ---- the contrast order, which is the legibility rule made checkable --------
#
# The two inks the game cannot afford to lose, repeated here as the reference
# the room is measured against.  They are `FlappyView.pipe` and
# `FlappyView.collar`, and `test_flappy_scene.py` asserts the copies agree, so
# this file cannot drift away from the thing it is constraining.
PIPE_INK = (30, 74, 84)
COLLAR_INK = (52, 112, 124)

# THE ROOM.  Every one of these is dimmer than ``PIPE_INK``, by test, so no
# part of the backdrop can ever be mistaken for the structure the player has to
# fly between.  A silhouette dimmer than the wall behind it is also the
# original's own arrangement: its city is darker than its sky.
AISLE_INK = (14, 34, 41)
# THE CITY'S OWN INK, AND ITS VALUE WAS SET BY A RENDER.  It was (9, 23, 28)
# while this row was three cabinets standing inside the lit aisle, where it had
# 49% of separation to work with.  A skyline rises OUT of that band into flat
# wall, where the background is the panel at 23,601 and 19,384 is 18% away --
# rendered, the towers' upper halves simply were not there.  15,167 is 36% below
# the panel and still 19% above ``NEAR_INK``, so the city reads at any height
# AND the racks in front of it stay the darkest thing in the room, which is what
# keeps the depth order the right way round.
SKY_INK = (7, 18, 22)
NEAR_INK = (6, 15, 19)
RACK_LIT_INK = (22, 52, 60)
TRAY_INK = (16, 39, 46)
WALL_INK = (18, 44, 51)
DRIFT_INK = (13, 32, 39)
ROOM_INKS = (
    AISLE_INK,
    SKY_INK,
    NEAR_INK,
    RACK_LIT_INK,
    TRAY_INK,
    WALL_INK,
    DRIFT_INK,
)

# THE PIPES, which are foreground and are allowed to be brighter than the room.
# An idle slot face is darker than the shaft it is cut into and an occupied one
# is brighter, so the shaft reads as a frame either way and the collar stays the
# brightest thing on a pipe — which matters, because the collar is the edge the
# player actually aims at and the edge that kills him.
SLOT_INK = (20, 50, 58)
SLOT_LIT_INK = (38, 88, 98)


def luminance(ink):
    """Rec. 601 luma in integer thousandths, for ordering inks in a test.

    Not used in any draw path.  It exists so `test_flappy_scene.py` can state
    the contrast rule as arithmetic rather than as a comment nobody checks.
    """
    red, green, blue = ink
    return 299 * red + 587 * green + 114 * blue


# ---- the room ---------------------------------------------------------------
#
# The aisle: the lower band of the room is lit, the upper band is not.  One
# rectangle, static, and it is what turns a flat wall into a floor with a
# distance to it.  It is also the band the city is legible in -- see
# ``SKY_INK`` -- so 76 now buys two things.
#
# THE ORDER IT MARKS HAS INVERTED, DELIBERATELY.  This used to read "76 is
# chosen so the taller near racks break the line and the shorter far ones sit
# under it".  With San Francisco behind them it is the CITY that breaks the
# line and the racks that sit under it, which is the only arrangement that can
# be true: a city a mile away is taller than a cabinet three metres away, and
# a row of racks tall enough to hide downtown is a row of racks in front of
# nothing.  Rendered both ways; the racks were cut down and the city grew.
AISLE_Y = 76

# THE RACKS ARE DARKER THAN THE WALL BEHIND THEM, which is the original's own
# arrangement — its city silhouette is darker than its sky — and it is also the
# arrangement that cannot hurt legibility: a silhouette dimmer than the panel
# can never be mistaken for a pipe, because a pipe is brighter than the panel.
# Nearer is darker: the skyline behind is one step off the wall, the near row is
# a hard shadow.
#
# A cabinet is ``(x, width, height, led_x)`` inside one period of the row, and
# it stands ON the floor rail: its bottom is ``M.FLOOR`` and it rises by
# ``height``.  ``led_x`` is the column of a single 1x2 status light on the
# cabinet face, or -1 for a cabinet with its lights out — an idle rack.
#
# Heights are deliberately uneven and deliberately not a sawtooth: a repeating
# ramp reads as a pattern the moment it scrolls, and the period is short enough
# that a player will see it twice a second.
NEAR_PERIOD = 52
# CUT DOWN FROM 21/28/15 SO THE CITY BEHIND THEM EXISTS.  At the old heights the
# tallest cabinet reached world row 74 and downtown reached 72, so the skyline
# was two pixels of nothing above a wall of racks -- rendered, and it is why the
# first version of this pass looked identical to the one before it.  These read
# as racks at 10..17 px just as well, and the 20 px they give back are what the
# Transamerica Pyramid and the Salesforce Tower are drawn in.
NEAR_RACKS = (
    (0, 18, 13, 5),
    (24, 13, 17, 8),
    (41, 8, 10, -1),
)

# Parallax divisors, against a world that scrolls at 1.  The room's two rows
# move at an eighth and a quarter of the pipes, so at level 1 (60 px/s) they
# drift 7.5 and 15 px/s and at level 9 (145 px/s) 18 and 36 px/s.  Slow is the
# point: a fast background behind a 30 px gap is the thing that makes this game
# unplayable, and the ratio between the two rows (2:1) is what reads as depth.
FAR_DIV = 8
NEAR_DIV = 4


# ---- San Francisco, which is what the far row is now ------------------------
#
# THE OWNER READ THE FAR ROW AS A CITY BEFORE ANYONE CALLED IT ONE: *"i do like
# flappy buffer with the city sky line but would be way better if it was san
# fransisco."*  Three uneven cabinets one step off the wall, scrolling at an
# eighth of the world, already read as a skyline — so this is not a new layer,
# it is the SAME layer with the silhouette it was already being mistaken for.
# That matters for cost: a third row would have to be paid for, and a reshape
# does not.
#
# TWO BUILDINGS DO THE WORK AND THE REST IS MASS.  At 160x120 a skyline is not
# a drawing of a city, it is two shapes a person recognises plus something for
# them to stand out of.  For San Francisco those two are not a choice:
#
# * the **Transamerica Pyramid** — a tapered square pyramid ending in a needle,
#   and the only building in the set whose silhouette is unique enough to be
#   read at 26 px.  It is drawn as four stacked steps, 13 -> 9 -> 5 -> 1 px
#   wide, all centred on the same column, so the taper is exact rather than
#   suggested and the needle is a real 1 px spire.
# * the **Salesforce Tower** — the tallest thing in the city and a smooth taper
#   with no setbacks, so three stacked steps 8 -> 6 -> 4 read as one column
#   narrowing.  It is deliberately the TALLEST entry here, because that is the
#   fact about it that a silhouette can carry.
#
# Everything else is a mid-rise: one rectangle each, and only the ones that rise
# clear of the base band below are worth a primitive at all.
#
# THE BASE BAND IS WHY THIS IS AFFORDABLE, and it is the trick
# `docs/badge-games.md` §2 records from Snake's continuous tube: merging what
# does not need to be separate is a LOOK change that buys primitives.  Every
# low building in a 160 px skyline shares one silhouette — a band along the
# bottom — so it is drawn as ONE rectangle rather than nine.  The band does not
# scroll and does not need to: a uniform strip has no motion to lose, and the
# buildings that DO scroll are the ones with a top edge to see move.
SKY_BASE_H = 8

# ``(x, width, base, height)``: a rectangle ``base`` pixels above the floor
# rail, ``height`` tall.  ``base = 0`` stands on the rail.  Stacked entries are
# how a taper is drawn, so unlike a cabinet row these DO share columns.
SKY_PERIOD = 160
SKYLINE = (
    # the mid-rises, one rectangle each: the city either side of downtown
    (14, 9, 0, 20),
    (55, 11, 0, 15),
    (130, 12, 0, 13),
    # the Salesforce Tower: podium, shaft, crown, all centred on 2x + w = 61
    (26, 9, 0, 17),
    (27, 7, 17, 12),
    (28, 5, 29, 11),
    # the Transamerica Pyramid: three steps and a needle, all on 2x + w = 161
    (72, 17, 0, 11),
    (75, 11, 11, 9),
    (78, 5, 20, 8),
    (80, 1, 28, 7),
)

# THE SKYLINE'S CEILING IS STILL A BOUND, and it is now about the ROOM rather
# than about contrast, because ``SKY_INK`` settled the contrast.  The aisle band
# is ``M.FLOOR - AISLE_Y`` = 26 px and the Salesforce Tower is 40, so downtown
# rises 14 px into the flat wall — which is the whole point of a skyline and is
# why the ink had to change first.  What the bound stops is a tower growing into
# the CEILING TRAY's band (the top 16 px of the world) or into the drifting
# connections at rows 24..57, either of which would put scenery in the middle of
# the panel where the client lives.  40 px of building tops out at world row 62,
# five clear of the lowest capsule.
SKY_MAX_ABOVE_AISLE = 14

# The ceiling tray: two 1 px conduits with hangers, at an eighth.  It fills the
# upper third — which is otherwise flat wall — and it is the cheapest way to
# say "indoors" rather than "sky".  Both rules sit inside the top 16 px of the
# world, above every gap band's top edge but reachable by a client that is
# climbing hard, so they are drawn in the dimmest ink the room has.
TRAY_Y = (7, 13)
TRAY_HANGER_PITCH = 24
TRAY_HANGER_H = 6

# THE INTRO GETS ITS OWN CEILING AND FLOOR AND NOTHING ELSE, and that is a
# rendered decision rather than a preference — see `flappy/README.md`.  The app
# root's five text rows occupy y 10..118 with no 16 px strip above them, so the
# playfield's room cuts straight through three of them: the ceiling tray's rules
# at 23 and 29 run through the middle of `POOLER.SQL`, and the near cabinets'
# lit top edges run through `B UP  KEEPALIVE` and `HOME  EXIT`.  What is left is
# the part that cannot collide: a conduit ABOVE the title and a floor line BELOW
# the last row.
INTRO_TRAY_Y = (2, 6)
INTRO_FLOOR_Y = 118

# ---- the other connections in the pool --------------------------------------
#
# THE MIDDLE OF THE PANEL IS THE PROBLEM THIS SOLVES.  The racks stand on the
# floor and the tray hangs from the ceiling, which leaves roughly 45 px of flat
# wall through the middle — 40% of the playfield, and the band the client spends
# most of its life in.  The original's answer there is clouds.  Ours is the rest
# of the pool: THE OTHER CONNECTIONS, drifting, quiet, none of them yours.
#
# It is the one layer that is a statement rather than a set: the game already
# says you are a client connection, and this says how many others the pool is
# holding at the same time.  Each is a 7x2 capsule with a 3x1 tail, drifting at
# half the world's speed — near enough to read as traffic, far enough that it is
# plainly not a thing to be flown through, and horizontal so it can never be
# mistaken for a pipe.  One step above the wall in ink, which is what keeps it
# from competing with the gap.
#
# ``(x, y)`` inside one period.  The y values stay inside the flat band and are
# deliberately unequal, because a row of them at one altitude reads as a rule.
#
# THREE PER 80 PX AND NOT FIVE PER 67, and the count was set by a measurement
# rather than by eye.  The first pass drew 24 primitives a frame here — the most
# expensive layer in the room after the two rack rows, for the faintest thing on
# the panel.  Halving it to 12 costs nothing visible (they are meant to be
# occasional, the way the original's clouds are) and it is the cheapest 12
# primitives of headroom against `flappy_model.STEP_MS`, which is the number
# that actually binds.  See `flappy/README.md` for the trim ladder.
DRIFT_PERIOD = 80
DRIFT_CONNECTIONS = (
    (4, 24),
    (30, 55),
    (57, 38),
)
DRIFT_DIV = 2
DRIFT_W = 7
DRIFT_H = 2
DRIFT_TAIL = 3


# ---- the pool's slots -------------------------------------------------------
#
# A pipe is a rack of connection SLOTS and not a slab, which is the one change
# in this app that makes the picture and the mechanic say the same thing: the
# thing you fly between is a set of discrete pooled connections, so it is drawn
# as a set of discrete pooled connections.
#
# 7 px pitch with a 5 px face leaves a 2 px seam of shaft colour between slots,
# so the pipe still reads as one solid column at arm's length and only resolves
# into slots when looked at.  The faces are inset 1 px either side of the 14 px
# shaft for the same reason: the pipe keeps a continuous 1 px frame, so its
# silhouette — the thing collision is actually about — is never broken.
SLOT_PITCH = 7
SLOT_H = 5
SLOT_INSET = 1

# WHICH SLOTS ARE IN USE, and why it is a table rather than a random number.
# The view must be able to draw frame N+1 the same as frame N without storing
# anything, so occupancy is a pure function of a pipe's gap top — a value the
# model fixes when the pipe is spawned and never touches again.  Seven bits,
# one per slot away from the mouth; bit 0 is the slot at the collar.
SLOT_MASKS = (
    0b0100100,
    0b0010001,
    0b1001000,
    0b0100010,
    0b0001001,
    0b1010000,
    0b0010100,
    0b0101001,
)

# LOAD IS VISIBLE IN THE POOL, and this is where.  A pooler under load has more
# of its connections in use, so a higher load ORs in more masks and more slot
# faces light up.  The thresholds are the two points on the ladder where the
# gap has visibly tightened, so the pool looks busier exactly when it is being
# harder to fly.  Monotonic by construction and pinned by a test: the set of
# lit slots at load N is always a subset of the set at load N+1.
SLOT_BUSY_LEVEL = 5
SLOT_FULL_LEVEL = 8

# ---- the connection --------------------------------------------------------
#
# The cable from the pool's wall to the client, and the best idea in the design
# record per unit of work: one line, no new model state, and it makes the
# game's central metaphor visible for the first time.  You are not a bird.  You
# are a connection someone is holding open, and the moment you stop asking for
# it the pool takes it back.
#
# The wall plate is a 3 px column at x 0 that the cable leaves from.  It is
# scenery, so it is drawn with the room and a pipe may pass in front of it.
WALL_W = 3

# How stale the connection is, in movement steps since the last keepalive, and
# it is READ OFF THE VELOCITY rather than counted.  A keepalive SETS vy to
# ``FLAP``; gravity then adds ``GRAVITY`` every step until ``MAX_FALL``, so vy
# alone says how many steps ago the client last spoke to the pool.  That is why
# this costs no model change: the number was already in the state, spelled as a
# velocity.
IDLE_STEPS = (M.MAX_FALL - M.FLAP) // M.GRAVITY

# The cable's four brightnesses, from a keepalive that has just landed to a
# connection the idle timer is about to reclaim.  The last is barely above the
# wall it comes out of, so a player who has stopped tapping can SEE the line
# going out before the floor tells him.
CABLE_INK = (
    (52, 112, 124),
    (38, 88, 98),
    (26, 62, 70),
    (16, 39, 46),
)


def parallax_offset(scrolled_sub, divisor, period):
    """Pixels to shift a repeating row left, for a row at ``1 / divisor`` speed.

    ``scrolled_sub`` is `flappy_model`'s odometer in sub-pixels.  Integer
    division twice over, in this order, and the order matters: dividing the
    sub-pixel count by ``UNIT * divisor`` keeps the row's motion smooth to the
    pixel, where dividing the pixel count would quantise an eighth-speed row to
    one pixel every eight and make it visibly step.

    Always in ``0 .. period - 1``, so a caller can start its loop at
    ``-period - offset`` and know it has covered the left edge.
    """
    return (scrolled_sub // (M.UNIT * divisor)) % period


def slot_mask(gap_top_px, level):
    """Which of a pipe's seven slots are in use, as a 7-bit mask.

    Pure in the pipe's own gap top, which the model fixes at spawn, so the
    occupancy of a given pipe never flickers while it crosses the panel.
    """
    mask = SLOT_MASKS[gap_top_px % len(SLOT_MASKS)]
    if level >= SLOT_BUSY_LEVEL:
        mask |= SLOT_MASKS[(gap_top_px + 3) % len(SLOT_MASKS)]
    if level >= SLOT_FULL_LEVEL:
        mask |= SLOT_MASKS[(gap_top_px + 5) % len(SLOT_MASKS)]
    return mask


def slot_lit(mask, index):
    """Whether slot ``index`` away from the mouth is in use.

    The mask is seven bits and a pipe can be taller than seven slots, so the
    index wraps.  A rack whose pattern repeats down a long shaft is what a rack
    looks like; a shaft that runs out of pattern and goes blank is not.
    """
    return bool(mask >> (index % 7) & 1)


def idle_age(vy):
    """Movement steps since the last keepalive, clamped to ``0..IDLE_STEPS``.

    Reads a velocity as a clock.  During the opening hold the model pins vy to
    0, which lands mid-ramp — correct, because a held client is neither fresh
    nor stale, it is parked.
    """
    age = (vy - M.FLAP) // M.GRAVITY
    if age < 0:
        return 0
    if age > IDLE_STEPS:
        return IDLE_STEPS
    return age


RECLAIM_W = 3


def reclaim_x(vy):
    """Where the idle timer's head has got to along the cable, in pixels.

    THE IDLE TIMER MADE VISIBLE.  It starts at the pool's wall the instant a
    keepalive lands and walks towards the client as the connection goes quiet;
    when it arrives, the connection has been reclaimed — and by then the client
    is already falling at ``MAX_FALL``, so the picture and the physics agree
    without either being told about the other.

    Bounded to the cable's own span by construction, so it can never be drawn
    over the client or off the left edge: `test_flappy_scene.py` pins both ends
    and the monotonicity in between.
    """
    span = M.CLIENT_X - WALL_W - RECLAIM_W
    return WALL_W + idle_age(vy) * span // IDLE_STEPS


def cable_ink_index(vy):
    """Which of ``CABLE_INK``'s four brightnesses the cable is at.

    Bucketed rather than interpolated: four inks over 25 steps means the line
    visibly steps down three times between a keepalive and the fall, which a
    player reads as a countdown.  A smooth ramp over 25 values would need 25
    pens constructed at import and would read as nothing at all on this panel.
    """
    return idle_age(vy) * len(CABLE_INK) // (IDLE_STEPS + 1)
