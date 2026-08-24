"""LORES CURSOR.SQL renderer using injected Badgeware APIs.

Draws and nothing else.  It reads the model's state the way it reads the score
— as data — and never computes a game rule, so the whole file can be exercised
against a recording screen with no runtime at all.

Everything here is rectangles and text.  There is no sprite sheet, no asset
pack and no PNG decode on the load path: the one asset this app installs is its
24x24 launcher icon, which the launcher draws and this file never opens.

THE DRAW PATH ALLOCATES NOTHING, IN EVERY STATE, AND THERE IS NO EXCEPTION.  The
maze is static, so its walls are run-length merged into a tuple of pixel
rectangles once, in ``__init__``, and every frame walks that tuple.  The rows are
the only thing that changes and they are read straight out of the model's
``bytearray`` rows.

There WAS one exception between 2026-08-21 and 2026-08-22: ``_plans`` drew each
chaser's target vector while SUPERUSER held, which meant asking
``pacman_model.ghost_target`` for a tuple per chaser on those frames.  **The owner
removed the feature** -- *"take that vector line thing out of pacman"* -- so the
allocation went with it.  ``ghost_target`` itself stays: it is the model's own
steering rule and ``pacman_model._step_ghost`` is its real caller.
"""

import pacman_model as M

# The five games' one palette (`shared/game_palette.py`, vendored here by
# `scripts/sync_ui.py`).  Every pen below that is not part of THIS game's own
# argument comes from it, so the ten pens the five views used to duplicate can
# be changed in one place.  Tuples only -- a pen can only be minted through the
# injected `color` API, which the palette has no access to and should not.
import game_palette as P


# The Supabase green, to within a unit.  The cursor is the thing the player IS,
# so it wears the badge's own accent.
ACCENT = P.BRAND


def wall_runs(maze, cell, y_offset):
    """Merge the maze's wall cells into as few rectangles as will cover them.

    Horizontally first, then a second pass that folds a run into the one
    directly above it when the two share an x and a width.  56 rectangles
    become 42, which is not a large saving and is a completely free one: this
    runs once at construction and the render loop then has no maze logic in it
    at all.

    Returned as a tuple of tuples so nothing on the draw path can append to it.
    """
    runs = []
    for y, row in enumerate(maze):
        x = 0
        width = len(row)
        while x < width:
            if row[x] != "#":
                x += 1
                continue
            start = x
            while x < width and row[x] == "#":
                x += 1
            rect = [start * cell, y * cell + y_offset, (x - start) * cell, cell]
            merged = False
            for previous in runs:
                if (
                    previous[0] == rect[0]
                    and previous[2] == rect[2]
                    and previous[1] + previous[3] == rect[1]
                ):
                    previous[3] += cell
                    merged = True
                    break
            if not merged:
                runs.append(rect)
    return tuple(tuple(rect) for rect in runs)


class PacmanView:
    CELL = 8
    COLS = M.COLS
    ROWS = M.ROWS
    # The status strip is 16 px, exactly Snake's and Pong's, so all three
    # games' playfields are the same 160x104 and a player's eye finds the score
    # in the same place in each.  13 rows of 8 px is 104 exactly: the maze fills
    # the playfield with no letterboxing and no half cell.
    Y_OFFSET = 16
    # The cursor and the ghosts are 6 px inside their 8 px cells, so a corridor
    # always shows a pixel of floor either side and two things in adjacent
    # cells never look like one thing.
    SPRITE = 6

    # THE FOUR BODIES AND THE FOUR CROWNS -- the fix for the owner's report that
    # "the pacman sprites just can't be seen" (2026-08-21).
    #
    # MEASURED, NOT ARGUED.  The method is `docs/design/game-scenes.md` §4.1's
    # SWALLOW figure -- the percentage of playfield pixels whose Rec. 601 luma
    # reaches HALF the element's own peak -- run over a real captured LORES
    # framebuffer by `pacman/results/evidence/playground/measure_marks.py`.
    # §4.1's calibration point is a human judging Snake's 6 px accent body
    # legible at 2.11%, so 2.11% is the bar and it is an observation rather
    # than a threshold anybody chose.  On the shipped frame:
    #
    #   DEADLOCK  peak luma 117.3   swallow 55.77%   26.4x the bar
    #   TIMEOUT   peak luma 161.8   swallow  4.52%    2.1x
    #   ROLLBACK  peak luma 169.9   swallow  4.52%    2.1x
    #   OOM       peak luma 159.9   swallow  4.52%    2.1x
    #
    # DEADLOCK was being eaten by the MAZE: the wall is (36, 74, 112), luma
    # 67.0, which is ABOVE red's own half-way mark of 58.6, so 55.8% of the
    # panel had less to distinguish it from than half its own brightness.  And
    # the other three were not passing either -- 4.52% is this board's own
    # FLOOR, set by the 117 rows at luma 163.5, which are BRIGHTER than
    # DEADLOCK's entire body.  The chasers had no luminance headroom at all.
    #
    # SO THIS IS A CONTRAST FAILURE (§4.1) AND NOT SHAPE DISSOLUTION (§4.3),
    # which matters because the first attempt at it assumed the opposite.
    # `game-art.md` §6 proposed carving the silhouettes -- 6x3 over a 4x3,
    # 4x6 with a 2x4 step -- and rendered, three of the four "read as damaged
    # squares" (`docs/design/mockups/README.md`).  Of course they did: carving
    # SUBTRACTS the ink coverage `game-art.md` §12 measured as a mark's floor,
    # so it makes an already-dim mark dimmer.  Only OOM's 8x8 landed, because
    # OOM's was the one change that ADDED.
    #
    # The crown adds.  Every chaser gets a 1 px rail in `P.WHITE`: luma 255,
    # clear of the rows (163.5), the pellets (204.0) and the wall (67.0), so
    # every chaser carries ink that nothing else on the board can match.  The
    # rail's SHAPE is then a second cue underneath hue, which is what stops the
    # four being four hues of one square:
    #
    #   DEADLOCK  a rail broken in two    two holders, neither one yielding
    #   TIMEOUT   one unbroken rail       the bar filled and the clock ran out
    #   ROLLBACK  railed top AND bottom   wound on, then wound back off again
    #   OOM       the same rail, on a body that is the whole cell
    #
    # THE RAIL SITS ON THE CELL EDGE, NOT ON THE BODY, and that is the second
    # version of this.  Drawn on the body's own top row a rail is 6 px long and
    # it spends 6 px of the chaser's hue to buy them -- and hue is the cue the
    # owner has already approved.  On the cell edge it is 8 px long, the body
    # keeps all 36 px of its colour, the eyes go back exactly where they
    # shipped, and the bright feature is four times the length of a row (2 px)
    # and brighter than a pellet (luma 204).  Same call count, strictly more
    # ink, one less thing changed.
    #
    # Offsets are from the BODY origin (`px`, `py`), which is 1 px inside the
    # cell, so -1 is the cell edge and 6 is its far edge.  Tuples, so nothing
    # on the draw path can build them.
    #
    # WHITE IS SAFE HERE, and it is only safe because of 2026-08-21's earlier
    # correction: the SUPERUSER cursor used to be white and is now `P.PALE`.
    # Nothing else on the playfield is white except a fleeing chaser's eyes, so
    # a white rail cannot be read as the player.
    BODIES = (
        (0, 0, SPRITE, SPRITE),        # DEADLOCK
        (0, 0, SPRITE, SPRITE),        # TIMEOUT
        (0, 0, SPRITE, SPRITE),        # ROLLBACK
        # OOM FILLS ITS CELL, and that is `game-art.md` §6's idea worth having:
        # out of memory is the failure whose whole nature is "it did not fit",
        # so it is drawn as the one thing on the board too big for the cell it
        # stands in -- and 8x8 is exactly the cell, so it still cannot bleed
        # into a neighbour.
        (-1, -1, 8, 8),                # OOM
    )
    CROWNS = (
        ((-1, -1, 3, 1), (4, -1, 3, 1)),   # DEADLOCK: broken, 2 px of gap
        ((-1, -1, 8, 1),),                 # TIMEOUT: unbroken
        ((-1, -1, 8, 1), (-1, 6, 8, 1)),   # ROLLBACK: both edges
        ((-1, -1, 8, 1),),                 # OOM: the same rail, a bigger body
    )


    # THE ONE SQLSTATE THIS GAME PRINTS, and `40P01 deadlock_detected` is the
    # doc-assigned one: `game-art.md` §13.1 maps it to the DEADLOCK chaser and
    # `docs/design/mockups/23-death-pacman-40P01.png` is the frame on the sheet
    # the owner approved.
    #
    # ONE CODE AND NOT FOUR, which is a real decision and not a simplification.
    # §13.1 maps a code to each chaser -- 40P01, 57014, 25P02, 53200 -- and the
    # mock-up patch switched on the killer.  But `57014 query_canceled` SHIPPED
    # as REPLICA.SQL's code on 2026-08-21 (`pong_view.sqlstate_line`, which says
    # in as many words that 40P01 is this game's), and two of the five games
    # printing one code is worse than one game printing one code.  So the code
    # is the game's and the chaser is the DETAIL.  The five are now 40P01 here,
    # 57014 Pong, 55P03 Breakout, 23505 Snake, 53300 Flappy, and
    # `test_pacman_app` pins the disjointness as a set rather than a memory.
    #
    # AND IT IS TRUE OF EVERY CATCH, not only DEADLOCK's.  A deadlock is two
    # transactions each wanting a row the other holds; a catch in this game is
    # the cursor and a chaser wanting the same cell on the same tick, which is
    # the same sentence.  `pacman_model._catch` fires for all four the same way.
    SQLSTATE = "40P01"
    CONDITION = "deadlock_detected"
    # The HINT row, per chaser, VERBATIM from the approved sheet
    # (`docs/design/mockups/patches/pacman_death_psql.py`, the copy beside
    # `sheet-deaths.png`).  All four, and the fourth one nearly did not survive:
    # `HINT  the scan ran too long` is 136 px in the real ROM `font.sins` and
    # fits the 160 px canvas with 24 to spare, but the host harness used to
    # charge a flat 6 px a character and reported 162, which would have made
    # `_center` compute a negative x in every test.  The right answer was to fix
    # the RULER, not the owner's copy: `app_harness` now imports the measured
    # table from `shared/tests/sins_ruler.py`, which is where all fourteen
    # hand-copies of it were consolidated once this bug showed what a private
    # ruler costs.  It turned out the flat model was also
    # UNDER-charging `M`/`W`/`m`/`w`, so the old gate could have passed a label
    # that clipped the panel.  No copy was cut in the end.
    HINTS = (
        "two cursors, one row",
        "the scan ran too long",
        "roll it back first",
        "it did not fit",
    )

    def __init__(self, screen, image_api, color_api, font_api, vec2_api,
                 accent=ACCENT):
        self.screen = screen
        # KEPT AND UNUSED, DELIBERATELY.  This game is procedural and never
        # blits, so it needs neither the image loader nor vec2 — but holding
        # the seam open means the constructor matches every other game in the
        # repository and a later change that DOES want a sprite does not have
        # to rediscover which globals Badgeware injects.
        self.image = image_api
        self.vec2 = vec2_api
        self.color = color_api
        self.font = font_api
        self.dark = color_api.rgb(*P.DARK)
        self.panel = color_api.rgb(*P.PANEL_DARK)
        # A blue wall on a near-black floor: the corridors are what the player
        # reads, so the walls are the thing that must not compete with the
        # rows, the cursor or four coloured chasers.
        self.wall = color_api.rgb(36, 74, 112)
        # The pen door, in the arcade's pink.  It is the only cell in the maze
        # that behaves differently for the cursor and the ghosts, so it is the
        # only one drawn in a colour of its own.
        self.door = color_api.rgb(196, 128, 158)
        self.dot = color_api.rgb(150, 168, 176)
        self.white = color_api.rgb(*P.WHITE)
        self.grey = color_api.rgb(*P.GREY)
        self.red = color_api.rgb(*P.RED)
        self.yellow = color_api.rgb(*P.YELLOW)
        self.accent_tuple = accent
        self.accent = color_api.rgb(*accent)
        # The cursor under SUPERUSER.  See `_cursor` for why it is not white.
        self.super_pen = color_api.rgb(*P.PALE)
        # THE FOUR WAYS A QUERY DIES, in four colours a wearer can tell apart
        # at 0.375 mm a pixel: red, orange, cyan, violet.  Chosen around the
        # colour wheel rather than by taste — a 6 px block carries hue and
        # almost nothing else, so two chasers that share a hue are one chaser
        # as far as the player is concerned.  The order is the model's.
        #
        # NOT IN THE SHARED PALETTE, deliberately: four ways a query dies is
        # this game's own argument, the owner has looked at these four on glass,
        # and a green ramp cannot say "orange chaser".  The first one is
        # `P.RED` rather than a fourth copy of (245, 58, 88) because it really
        # IS the death pen -- the two were byte-identical in two files and
        # nobody could see that they were, which is worth making visible even
        # though nothing about the pixel changes.
        self.ghost_pens = (
            color_api.rgb(*P.RED),
            color_api.rgb(255, 140, 30),
            color_api.rgb(86, 200, 235),
            color_api.rgb(186, 130, 245),
        )
        # A fleeing ghost is a single deep blue whoever it is: under SUPERUSER
        # they stop being four threats and become one opportunity, and telling
        # them apart would be information the player has no use for.
        self.flee = color_api.rgb(52, 92, 220)
        self.flee_warn = color_api.rgb(235, 235, 245)
        # Pause dims the maze and lays a translucent card over it, so the
        # frozen run stays visible underneath and nothing feels destroyed.
        self.pause_scrim = color_api.rgb(*P.PAUSE_SCRIM)
        # This game's field is the darker one, so its card is too.  It shipped
        # as the standard card over the dark field, which is a card three units
        # lighter than the maze under it for no reason anyone chose.
        self.pause_card = color_api.rgb(*P.PAUSE_CARD_DARK)
        # Heavier than the pause scrim: the result has to dominate, and the
        # maze behind it is an answer, not the subject.
        self.finish_scrim = color_api.rgb(*P.FINISH_SCRIM)

        self.walls = wall_runs(M.MAZE, self.CELL, self.Y_OFFSET)
        # The door is two cells and never moves, so it is a constant too.
        self.doors = tuple(
            (x * self.CELL, y * self.CELL + self.Y_OFFSET)
            for y, row in enumerate(M.MAZE)
            for x, char in enumerate(row)
            if char == "D"
        )
        # The four pellet cells, precomputed, so the blink pass visits four
        # cells rather than all 260.
        self.pellets = tuple(
            (x, y, x * self.CELL + 2, y * self.CELL + self.Y_OFFSET + 2)
            for y, row in enumerate(M.MAZE)
            for x, char in enumerate(row)
            if char == "o"
        )

    # ---- text helpers -------------------------------------------------------

    def _center(self, text, y, scale=1):
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int((160 - width) // 2), y, scale)

    def _right(self, text, y, scale=1, margin=3):
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int(160 - width - margin), y, scale)

    def _center_between(self, text, left, right, y, scale=1):
        """Centre a label in the gap two other labels have left it.

        THE STATUS STRIP CANNOT USE `_center` AND THIS IS THE REASON.  This
        game's left slot is a score AND three life pips, so a canvas-centred
        hint would start inside them.  Centring in the REMAINING space instead
        keeps a real gutter either side of the hint whatever the score reads,
        and it is measured rather than nudged.  Copied from `pong_view`, which
        hit the same wall with a wider score word.
        """
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int(left + (right - left - width) // 2), y, scale)

    def _pair(self, left_text, left_pen, right_text, right_pen, y, gap=8):
        """Two labels, each in its own pen, centred as one block.

        The four ghost names are the joke and the joke only lands if the name
        and the colour arrive together, so each is drawn in the pen its chaser
        wears on the board.  Both halves are measured and the pair is centred
        as a unit, so neither name has a hand-placed x.
        """
        left_width, _height = self.screen.measure_text(left_text)
        right_width, _height = self.screen.measure_text(right_text)
        start = int((160 - (left_width + gap + right_width)) // 2)
        self.screen.pen = left_pen
        self.screen.text(left_text, start, y)
        self.screen.pen = right_pen
        self.screen.text(right_text, start + left_width + gap, y)

    def high_line(self, high_score):
        return "HIGH {:04d}".format(high_score)

    # ---- screens ------------------------------------------------------------

    def intro(self, level, high_score):
        """The app root: one press to play, every key named, and the four
        chasers introduced by name and by colour before they are ever seen."""
        self.screen.pen = self.dark
        self.screen.clear()
        self.screen.font = self.font.sins
        self.screen.pen = self.accent
        self._center("CURSOR.SQL", 4, 2)
        self.screen.pen = self.grey
        self._center(self.high_line(high_score), 24)
        self.screen.pen = self.white
        self._center("B  CONNECT", 36)
        # LEVEL IS GHOST SPEED AND THE SCREEN SAYS ONLY THAT.  Snake's
        # equivalent row reads `PAYS xn` because its level prices every row;
        # ours does not, so claiming a payout here would be a lie, and naming
        # the ladder anything richer than it is would be worse.
        self.screen.pen = self.yellow if level >= 7 else self.grey
        self._center("A/C LEVEL {}".format(level), 48)
        self.screen.pen = self.grey
        # ALL FOUR KEYS ARE DIRECTIONS AND ALL FOUR ARE ABSOLUTE, so the row
        # says which is which rather than calling them all STEER.  Snake needs
        # two verbs here because its A and C are relative turns; this game has
        # a real 2-D axis and therefore does not.
        self._center("UP DN  A LEFT  C RIGHT", 60)
        # The four ways a query dies, in the colours they wear on the board.
        # Two rows rather than one: at four names and three gaps a single row
        # runs past the canvas, and a joke that is clipped is not one.
        self._pair(
            M.GHOST_NAMES[0], self.ghost_pens[0],
            M.GHOST_NAMES[1], self.ghost_pens[1], 76,
        )
        self._pair(
            M.GHOST_NAMES[2], self.ghost_pens[2],
            M.GHOST_NAMES[3], self.ghost_pens[3], 86,
        )
        # HOME is silicon and cannot be rebound, so naming it is the only
        # honest way to offer a labelled route to the launcher.
        self.screen.pen = self.grey
        self._center("HOME  EXIT", 106)

    # ---- the board ----------------------------------------------------------

    def _cursor(self, state, chomp):
        """The cursor, with a bite taken out of its leading edge.

        The bite is the heading, drawn rather than animated: it says which way
        the thing is going on a frame where it has not moved yet, which on a
        130 ms tick is most frames.  It opens and closes on the app's animation
        clock so a stationary cursor still reads as alive.
        """
        px = state["x"] * self.CELL + 1
        py = state["y"] * self.CELL + self.Y_OFFSET + 1
        # THE PALETTE'S PALE STEP UNDER SUPERUSER, and this fixes a collision
        # the previous pen created rather than merely restyling it.
        #
        # The rule stated here was right: the cursor's own state is the one thing
        # a player must never have to infer from the ghosts.  The pen broke it.
        # It was `self.white`, and a fleeing chaser's EYES are white too, and
        # `flee_warn` -- the blink that means SUPERUSER is about to run out -- is
        # (235, 235, 245).  So at the one moment in the game where the player
        # most needs to know whose state is whose, the cursor and the blinking
        # chasers were the same colour.
        #
        # `P.PALE` is the ramp's step above the cursor's own BRAND: the player
        # stays green, gets visibly brighter for the duration, and cannot be
        # confused with a blue chaser or a near-white blink.
        self.screen.pen = self.super_pen if state["super"] else self.accent
        self.screen.rectangle(px, py, self.SPRITE, self.SPRITE)
        if not chomp:
            return
        self.screen.pen = self.dark
        direction = state["direction"]
        if direction == M.UP:
            self.screen.rectangle(px + 2, py, 2, 3)
        elif direction == M.RIGHT:
            self.screen.rectangle(px + 3, py + 2, 3, 2)
        elif direction == M.DOWN:
            self.screen.rectangle(px + 2, py + 3, 2, 3)
        else:
            self.screen.rectangle(px, py + 2, 3, 2)

    def _ghost(self, ghost, pen, eye_pen, crown_pen):
        """One chaser: a body, a bright crown, and two eyes.

        See `BODIES` and `CROWNS` for the measurement that put the crown here.
        Five rectangles at most, against the three this drew before, so all
        four chasers together cost six more calls a frame.
        """
        index = ghost["index"]
        px = ghost["x"] * self.CELL + 1
        py = ghost["y"] * self.CELL + self.Y_OFFSET + 1
        self.screen.pen = pen
        dx, dy, width, height = self.BODIES[index]
        self.screen.rectangle(px + dx, py + dy, width, height)
        # The crown goes down after the body, which matters only for OOM: its
        # 8x8 reaches the cell edge, so for that one chaser the rail is the
        # body's own top row rather than a line above it.
        self.screen.pen = crown_pen
        for dx, dy, width, height in self.CROWNS[index]:
            self.screen.rectangle(px + dx, py + dy, width, height)
        # Two eyes, shifted a pixel towards the heading.  One pixel is all the
        # room a 6 px body has, and it is enough: a player reads which way a
        # chaser is looking long before they read its colour.  TWO of them, and
        # not the single heading bar `game-art.md` §6 costed: rendered, "two
        # eyes read as a face" and the one-bar version loses that, which is the
        # one thing worth more than the call it would have saved.  Unchanged
        # from the frame that shipped -- the crown is on the cell edge, so it
        # never wanted this row.
        direction = ghost["dir"]
        eye_x = px + 1 + (1 if direction == M.RIGHT else -1 if direction == M.LEFT else 0)
        eye_y = py + 1 + (1 if direction == M.DOWN else -1 if direction == M.UP else 0)
        self.screen.pen = eye_pen
        self.screen.rectangle(eye_x, eye_y, 1, 2)
        self.screen.rectangle(eye_x + 3, eye_y, 1, 2)

    def _board(self, state, anim=0):
        """Walls, rows, pellets, the four chasers and the cursor.

        ``anim`` is a 0..3 counter the app advances on its own millisecond
        deadline.  One counter drives three things — the cursor's bite, the
        pellets' blink and the SUPERUSER expiry warning — because three clocks
        would be three things to keep in step and the player reads them as one
        heartbeat anyway.
        """
        chomp = anim & 1
        self.screen.pen = self.dark
        self.screen.clear()
        self.screen.pen = self.panel
        self.screen.rectangle(0, self.Y_OFFSET, 160, 104)
        self.screen.font = self.font.sins
        self.screen.pen = self.wall
        for x, y, width, height in self.walls:
            self.screen.rectangle(x, y, width, height)
        self.screen.pen = self.door
        for x, y in self.doors:
            self.screen.rectangle(x, y + 3, self.CELL, 2)

        cells = state["cells"]
        # One pen, one pass, no allocation: 260 byte reads and one rectangle
        # per surviving row.
        self.screen.pen = self.dot
        for y in range(self.ROWS):
            row = cells[y]
            py = y * self.CELL + self.Y_OFFSET + 3
            for x in range(self.COLS):
                if row[x] == M.DOT:
                    self.screen.rectangle(x * self.CELL + 3, py, 2, 2)
        if anim != 3:
            # Four known cells rather than another sweep of 260.
            self.screen.pen = self.yellow
            for x, y, px, py in self.pellets:
                if cells[y][x] == M.PELLET:
                    self.screen.rectangle(px, py, 4, 4)

        warn = state["super"] and state["super"] <= M.SUPER_WARN_TICKS and chomp
        for ghost in state["ghosts"]:
            if ghost["state"] == M.EATEN:
                # A consumed chaser is simply not on the board.  There is
                # deliberately no eyes-return-to-base animation: it is the most
                # expensive part of the original to get right and it changes no
                # outcome the player can act on.
                continue
            if ghost["state"] == M.FLEE:
                self._ghost(
                    ghost,
                    self.flee_warn if warn else self.flee,
                    self.dark if warn else self.white,
                    # ON THE WARN BEAT THE CROWN INVERTS.  `flee_warn` is
                    # (235, 235, 245) -- luma 236, already brighter than
                    # anything the crown exists to clear -- so a white rail on
                    # it would be invisible and pointless.  Dark instead: the
                    # blink that says the window is closing then reads as a
                    # whole sprite flipping rather than a body changing shade.
                    self.dark if warn else self.white,
                )
            else:
                self._ghost(
                    ghost, self.ghost_pens[ghost["index"]], self.dark, self.white
                )
        self._cursor(state, chomp)

    def _lives(self, state):
        """The lives left, as pips inlaid into the maze's bottom wall band.

        NOT ON THE STATUS STRIP, and that is a measured decision rather than a
        stylistic one.  The strip has to carry `SCAN nnnn`, a centred `B
        PAUSE` and `HI nnnn`; measured at this app's worst case those three
        leave about 16 px of gutter in the whole 160, and three pips plus their
        clearance need 17.  The strip loses.

        Row 12 of the maze is solid wall from edge to edge, eight pixels of
        chrome that nothing else ever draws on, and putting the lives there is
        also the arcade's own convention — Pac-Man counts its lives below the
        maze, not beside the score.  Free space, zero contention, and the
        player's eye finds it in the same place whatever the score reads.
        """
        self.screen.pen = self.accent
        y = (self.ROWS - 1) * self.CELL + self.Y_OFFSET + 2
        for index in range(max(0, state["lives"])):
            self.screen.rectangle(3 + index * 6, y, 4, 4)

    def play(self, state, high_score, anim=0, hint=None, hint_pen=None,
             best=False):
        """The board, and the status strip over it.

        THE STRIP SAYS `B  PAUSE` FOR THE WHOLE LIFE OF THE SCREEN, and it used
        to swap in an `EXPLAIN` label for the six seconds of the SUPERUSER
        window.  That label went out with the thing it labelled: the target
        vectors were removed on 2026-08-22 on the owner's word -- *"take that
        vector line thing out of pacman"* -- and a strip announcing `EXPLAIN`
        with nothing revealed on the maze is worse than no announcement.  The
        window is still legible without it: all four chasers turn `flee` blue
        the instant a pellet is scanned, and they blink `flee_warn` when it is
        about to close.  `docs/design/game-art.md` §6 records the removal so the
        next lane does not rebuild it.
        """
        if hint is None:
            hint = "B  PAUSE"
            if hint_pen is None:
                hint_pen = self.grey
        self._board(state, anim)
        self._lives(state)
        score_text = "SCAN {:04d}".format(state["score"])
        self.screen.pen = self.white
        self.screen.text(score_text, 2, 2)
        score_width, _height = self.screen.measure_text(score_text)
        if best:
            # The stored number stopped being a target the moment it was
            # passed, and SCAN already carries the live score, so the slot
            # carries the state instead of repeating a figure.
            right_text = "BEST"
            right_pen = self.yellow
        else:
            right_text = "HI {:04d}".format(high_score)
            right_pen = self.grey
        right_width, _height = self.screen.measure_text(right_text)
        self.screen.pen = right_pen
        self._right(right_text, 2)
        # The status strip already existed, so labelling B here costs no
        # playfield and is drawn for the life of the screen rather than on a
        # timer.  All four direction keys are directions during play and must
        # never be labelled as commands, which is why there is no softkey bar.
        self.screen.pen = self.grey if hint_pen is None else hint_pen
        self._center_between(hint, 2 + score_width, 160 - right_width - 3, 2)

    def paused(self, state, high_score, anim=0, best=False, confirm=False):
        """The frozen maze, dimmed, under a card carrying the way out.

        The maze is drawn first and stays visible through the card, so pausing
        visibly did not destroy the run.  The status strip does not move: only
        its middle word changes, so the eye does not have to re-find SCAN or
        HI.

        ``confirm`` is the belt to the brace.  A is the destructive key here
        and it is ALSO the key that walks the cursor left one screen earlier,
        so a player who taps it out of muscle memory must not lose the run.
        The first A does not quit; it turns the map line into the question and
        the A label red, and only the second A ends it.  Row positions do not
        move between the two states, so answering the question is not a moving
        target.
        """
        self.play(state, high_score, anim, "PAUSED", self.yellow, best)
        self.screen.pen = self.pause_scrim
        self.screen.rectangle(0, self.Y_OFFSET, 160, 104)
        self.screen.pen = self.pause_card
        self.screen.rectangle(12, 26, 136, 88)
        # The label slot is always drawn, so the layout never jumps.
        self.screen.pen = self.yellow if best else self.grey
        self._center("NEW HIGH" if best else "HIGH", 30)
        self.screen.pen = self.yellow if best else self.accent
        self._center("{:04d}".format(state["score"] if best else high_score), 42, 2)
        self.screen.pen = self.grey
        self._center(
            "LEVEL {}  ROWS {}".format(state["level"], state["dots"]), 62
        )
        if confirm:
            self.screen.pen = self.yellow
            self._center("QUIT THIS RUN?", 74)
        else:
            self.screen.pen = self.grey
            self._center("UP DN  A LEFT  C RIGHT", 74)
        self.screen.pen = self.white
        self._center("B   RESUME", 86)
        self.screen.pen = self.red if confirm else self.grey
        self._center("A   QUIT NOW" if confirm else "A   QUIT", 100)

    def finished(self, state, high_score, anim=0, best=False):
        """The maze that ended the run, held under the result.

        The board is drawn first and stays visible through the scrim, so the
        first question — how much was left to scan? — is answered by the
        picture rather than by a number.  This is a render state, not a phase:
        B and A are live from the first frame and nothing is gated on a timer,
        so an impatient player at a booth is never made to wait.

        TWO SCREENS, not one with a word swapped, because the two results are
        not the same kind of event.  A cleared maze is a RESULT and keeps the
        headline it shipped with.  A cancelled query is an ERROR, and it is now
        printed the way a developer has read one at 2 a.m.: `FATAL`, a real
        five-character SQLSTATE, a `DETAIL` row and a `HINT` row.

        THE ROW POSITIONS ARE FLAPPY'S AND PONG'S, TO THE PIXEL -- 3, 27, 41,
        55, 71, 87, 103 -- so the five games' death screens are one screen with
        five payloads rather than five layouts.  `FATAL` is 58 px at scale 2
        where `QUERY` + `CANCELED` needed two lines and 96 px, and the line
        that frees is exactly what the `DETAIL` and `HINT` rows cost.  Being
        caught is still called QUERY CANCELED everywhere it is a MECHANIC --
        the model, the README, the serial log -- because that is what it is.
        This screen reports it the way Postgres would.
        """
        self._board(state, anim)
        self.screen.pen = self.finish_scrim
        self.screen.rectangle(0, 0, 160, 120)
        killer = state.get("caught_by", -1)
        if state["status"] == "won":
            self._won(state, high_score, best)
            return
        if not 0 <= killer < len(M.GHOST_NAMES):
            # A run can end without a chaser having ended it, and a psql dump
            # that cannot name a cause would be the wrong shape for it.
            self._cancelled_without_a_cause(state, high_score, best)
            return
        self.screen.pen = self.red
        # 58 px at scale 2, and 129 px, against the 160 px canvas.
        self._center("FATAL", 3, 2)
        self._center("{} {}".format(self.SQLSTATE, self.CONDITION), 27)
        # NAMING THE KILLER IS THE POINT OF THE FOUR NAMES, and `DETAIL` is
        # where a psql dump puts the specific fact.  Two pens on one measured
        # line, 34 + 8 + up to 48 = 90 px: the label stays furniture and the
        # name arrives in the colour its chaser wore on the board.
        #
        # THE APPROVED SHEET PUT ITS OWN JARGON HERE INSTEAD -- "waiting on
        # ShareLock", "statement timeout", "txn is aborted", "could not
        # allocate" -- and identified the chaser by PEN alone.  That is the one
        # part of the sheet that cannot ship, and its own README says why:
        # "drawing the DETAIL row in the killer's own pen is INVISIBLE for
        # DEADLOCK, whose pen is already the same red as the headline."  So on
        # one death in four, the thing this game exists to tell you was
        # unreadable.  The name is in words now and the pen is the bonus.
        self._pair(
            "DETAIL", self.grey,
            M.GHOST_NAMES[killer], self.ghost_pens[killer], 41,
        )
        self.screen.pen = self.grey
        # 94-134 px: the widest row on the screen after the SQLSTATE.
        self._center("HINT  {}".format(self.HINTS[killer]), 55)
        self.screen.pen = self.yellow if best else self.white
        self._center(
            "SCAN {:04d}  HIGH {:04d}".format(state["score"], high_score), 71
        )
        self.screen.pen = self.accent
        self._center("B  RECONNECT", 87)
        # A badge whose query was cancelled in a pocket must not sit lit on a
        # death screen all day with a restart as its only offer.
        self.screen.pen = self.grey
        self._center("A  MENU", 103)

    def _won(self, state, high_score, best):
        """`FULL SCAN COMPLETE` — unchanged, and deliberately not an error.

        A cleared maze is not a `FATAL` anything, so it keeps its own headline,
        its own `LEVEL` row and its own row positions.  Nothing about the psql
        block belongs on the screen a player earned.
        """
        self.screen.pen = self.yellow
        # Two lines at scale 2, because 102 and 96 px will not share one at
        # 160 px and the headline does not abbreviate without losing the joke.
        self._center("FULL SCAN", 12, 2)
        self._center("COMPLETE", 34, 2)
        self.screen.pen = self.grey
        self._center("LEVEL {}".format(state["level"]), 56)
        self.screen.pen = self.yellow if best else self.white
        self._center(
            "SCAN {:04d}  HIGH {:04d}".format(state["score"], high_score), 72
        )
        self.screen.pen = self.accent
        self._center("B  RECONNECT", 90)
        self.screen.pen = self.grey
        self._center("A  MENU", 104)

    def _cancelled_without_a_cause(self, state, high_score, best):
        """The run stopped and no chaser owns it.

        `caught_by` is -1 on a fresh run and every path into `finished` that is
        not a catch leaves it there, so this is reachable and must not print a
        `DETAIL` row naming a chaser that did nothing.  It is the pre-SQLSTATE
        screen, kept for exactly that case.
        """
        self.screen.pen = self.red
        self._center("QUERY", 12, 2)
        self._center("CANCELED", 34, 2)
        self.screen.pen = self.grey
        self._center("LEVEL {}".format(state["level"]), 56)
        self.screen.pen = self.yellow if best else self.white
        self._center(
            "SCAN {:04d}  HIGH {:04d}".format(state["score"], high_score), 72
        )
        self.screen.pen = self.accent
        self._center("B  RECONNECT", 90)
        self.screen.pen = self.grey
        self._center("A  MENU", 104)
