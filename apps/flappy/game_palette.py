"""The five games' one palette: the Supabase Select ramp, and the pens around it.

Vendored into all five games by `scripts/sync_ui.py`.  Edit this file; never a
copy.  Nothing here imports Badgeware, allocates, or builds a pen — every name
is an ``(r, g, b)`` tuple, because a pen can only be minted through the
``color`` API the runtime injects into an app, which this module has no access
to and should not.  A view does:

    import game_palette as P
    self.accent = color_api.rgb(*P.BRAND)

WHY THIS FILE EXISTS.  `docs/design/game-art.md` §2 recorded that the four
newer games each copied the same ten pens out of Snake rather than sharing
them, and the owner read the result off the panel: *"i guess it's just hard to
make it database and supabase related in these things.  but one thing that
might be an easy win is to use the supabase select color pallet."*  He was
describing five games that had each invented their own greens.  Before this
file there were 79 ``color.rgb(...)`` literals across the five views — snake
13, pong 11, breakout 11, flappy 25, pacman 19 — and no two of them could be
changed together.

WHAT THIS FILE IS NOT.  It is not a theme engine and it does not own every ink
in every game.  Three sets of inks are deliberately NOT here, and each absence
is a decision rather than an omission:

* **`flappy_scene`'s room, pipe and cable inks.**  Those are not hue choices at
  all, they are a CONTRAST ORDER — ``room < shaft < occupied slot < collar <
  client`` — stated as arithmetic and asserted over the pixels the runtime drew
  (`flappy/tests/test_flappy_scene.py`).  Recolouring the structure green would
  either break that order or put the pool's own furniture in the player's
  colour, which is the one thing the order exists to prevent.
* **`BreakoutView.ROW_PENS`.**  Five pens on a heat ramp where the colour and
  the row's VALUE are one statement, plus a test that no row may share a pen
  with a UI element.  A green ramp cannot say "hottest row, tail of the heap".
* **`PacmanView.ghost_pens` and the maze wall.**  Four chasers are four ways a
  query dies, the owner has looked at them, and the maze is arcade blue because
  the maze IS the picture.

---

## The ramp, and what each step is for

Four hexes, handed over by the owner on 2026-08-21 as the Select palette.
Listed here in ascending Rec. 601 luma, which is the order they are usable in:
a four-step ramp is exactly what a body, a highlight, a dim state and a keyline
want, and `test_game_palette.py` pins the ordering so a later edit cannot
quietly reshuffle them.

| Name | Hex | Luma | The role it carries | Used by |
|---|---|---:|---|---|
| `DEEP` | `46BD6C` | 144,185 | the same thing, subordinate — a replica of a primary | **nothing.  See below** |
| `BRAND` | `3ECF8E` | 156,235 | **THE PLAYER.**  The thing the player IS | all five games' accent |
| `PALE` | `95E6B8` | 200,537 | the player's own state, brighter | Pac-Man's SUPERUSER cursor |
| `MIST` | `DAEFD2` | 229,415 | a keyline, or a mark's top step | Flappy's client, top of its keepalive flash |

**`DEEP` IS DEFINED AND UNUSED, and that is a finding rather than an oversight.**
It is one of the four hexes the owner handed over, so it belongs in the palette;
but the one place in these five games that wants "the same thing, subordinate"
is Pong's REPLICA bat, and painting it `DEEP` was tried on 2026-08-21 and lost.
`DEEP` and `BRAND` are 7.7% apart in luma and share a hue, so at 3 px wide the
two bats read as one colour, where the shared `GREY` is 19% below `BRAND` *and*
differs in hue.  `pong_view._court` carries the full reasoning and
`test_pong_app` pins it as an inequality, so the rejection is checkable rather
than remembered.

The general lesson, which is about the ramp and not about Pong: **a four-step
ramp of one hue cannot separate two objects at its own bottom end.**  Use the
ramp for STATES OF ONE THING — a body and its highlight, a mark and its flash —
and reach outside it when two different things have to be told apart.

`BRAND` is `3ECF8E` **exactly**, and that is a correction.  `snake_profile.py`
already had the true hex in its `FALLBACK`; the other four games each carried a
hand-typed `ACCENT = (0x3F, 0xCF, 0x8E)`, one unit off on the red channel, in
four separate files.  Nobody could see the difference — that is the point.  It
is the shape of the drift this module removes, not the size of it.

One place the ramp is baked rather than named: Snake's food sheet and Flappy's
client sheet are the same 336-byte P8 file, and its three green palette entries
are computed by `snake/host/generate_food.py` mixing the brand green toward
white at `RAMP = (0.0, 0.40, 0.82)`.  That yields `3FCF8E` / `8CE2BB` /
`DCF6EB` against this file's `3ECF8E` / `95E6B8` / `DAEFD2`.  The largest
single-channel difference is 25/255 and at 0.375 mm per pixel it is not
visible; closing it needs PIL, which this build host does not have, and touches
`snake2x`'s pinned asset hashes.  `flappy/PROVENANCE.md` records it.

## The ten pens the games actually shared

These were byte-identical in all five views and are moved here unchanged.  The
two that carry MEANING are unchanged ON PURPOSE and must stay that way:

* **`RED` is death and expiry** — a fatal cell, a critter about to go, the
  QUIT confirmation, a loss headline.
* **`YELLOW` is a record or an armed state** — `BEST`, level 7 and up, a ball
  that has not left yet, Pac-Man's pellets.

The button rules and four games' death screens depend on those two readings,
so the Select ramp is added BESIDE them rather than over them.  A green
palette does not get to say "you died".
"""


# ---- the Select ramp --------------------------------------------------------

DEEP = (0x46, 0xBD, 0x6C)
BRAND = (0x3E, 0xCF, 0x8E)
PALE = (0x95, 0xE6, 0xB8)
MIST = (0xDA, 0xEF, 0xD2)

# Ascending luma, which is also ascending usefulness as a foreground ink.  The
# tuple exists so a test can walk the ramp without naming four constants, and
# so a future fifth step has one place to be inserted in order.
RAMP = (DEEP, BRAND, PALE, MIST)


# ---- the pens every game already shared ------------------------------------

# The field a game clears to, and the playfield panel over it.
DARK = (5, 12, 18)
PANEL = (11, 28, 34)
# Pac-Man's field is darker than the other four's, and that is deliberate
# rather than drift: the owner's expectation behind CURSOR.SQL is black with
# the maze as the only art (`docs/badge-games.md` §7.1), and the maze is drawn
# in blue over it.  Named here so it is a decision with a home instead of a
# literal that looks like a typo.
PANEL_DARK = (8, 18, 24)

# Neutral live text, and the ball/segment/worker in flight.  White, because the
# score has to be the most legible thing on the strip and a tinted white is
# strictly worse at that job.
WHITE = (255, 255, 255)
# A control nobody is touching: hints, the softkey legend, an inactive row.
GREY = (112, 132, 138)
# DEATH AND EXPIRY.  Do not put this on anything that is not lethal.
RED = (245, 58, 88)
# A RECORD, OR AN ARMED STATE.  Do not put this on anything that is neither.
YELLOW = (255, 205, 66)

# The three scrims, identical in all five games.  Alpha is the fourth channel,
# so these are 4-tuples and are not part of `RAMP`.
PAUSE_SCRIM = (0, 0, 0, 140)
PAUSE_CARD = PANEL + (225,)
# Pac-Man's card, over Pac-Man's darker field.  It shipped as `PAUSE_CARD` over
# `PANEL_DARK`, which is a card three units lighter than the maze it is laid on
# -- a seam nobody put there on purpose.  Same alpha, its own field.
PAUSE_CARD_DARK = PANEL_DARK + (225,)
FINISH_SCRIM = (0, 0, 0, 195)
# The translucent playfield a glyph backdrop is seen through, for the two games
# that hold that seam open (`SnakeView`, `FlappyView`).
BACKDROP_PANEL = PANEL + (72,)
BACKDROP_DIM = 170


def luminance(ink):
    """Rec. 601 luma in integer thousandths, for ordering inks in a test.

    NOT USED IN ANY DRAW PATH, and that is why it is safe for it to live in a
    module every game imports: it costs one function object at import and is
    never called on a frame.  It exists so a contrast rule can be stated as
    arithmetic rather than as a comment nobody checks — `flappy_scene` proved
    the pattern and re-exports this rather than keeping a second copy.

    Accepts a 3- or 4-tuple; alpha is ignored, because a scrim's luma is a
    property of what is behind it and this function cannot know that.
    """
    return 299 * ink[0] + 587 * ink[1] + 114 * ink[2]
