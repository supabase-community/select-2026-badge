"""LORES Snake renderer using injected Badgeware APIs."""

# The five games' one palette (`shared/game_palette.py`, vendored here by
# `scripts/sync_ui.py`).  Every pen below that is not part of THIS game's own
# argument comes from it, so the ten pens the five views used to duplicate can
# be changed in one place.  Tuples only -- a pen can only be minted through the
# injected `color` API, which the palette has no access to and should not.
import game_palette as P


# The food's own brand green, and the two ink rows the sheet carries.
FOOD_BRAND = (0x3F, 0xCF, 0x8E)
FOOD_ROW_BRAND = 0
FOOD_ROW_AMBER = 1
FOOD_ROW_THRESHOLD = 150


def pick_food_row(accent, brand=FOOD_BRAND, threshold=FOOD_ROW_THRESHOLD):
    """Choose the food's ink so it never dissolves into the snake's own colour.

    The body is drawn in the profile accent and the default accent is the
    Supabase green to within one unit, so a brand-green mark can sit inside a
    long snake on a stock badge.  BOTH rows in the sheet are the brand ramp;
    row 1 carries a dark keyline, so the colliding case is separated without
    the mark giving up its colour.  Manhattan distance from the four shipped
    skin accents to the brand green is 1, 205, 351 and 357, so the threshold
    sits in a wide gap and only the colliding skin takes the keyline.

    ``FOOD_ROW_AMBER`` keeps its name from when row 1 really was amber; it is
    now the keylined row, and the constant did not move so its tests did not
    have to.
    """
    distance = 0
    for index in range(3):
        distance += abs(accent[index] - brand[index])
    return FOOD_ROW_AMBER if distance < threshold else FOOD_ROW_BRAND


# ---------------------------------------------------------------------------
# THE CONTINUOUS TUBE (docs/design/snake-art.md §4.1).
#
# The body used to be one 6x6 rectangle per cell inset +1,+1, which leaves 2 px
# of board between consecutive cores: the snake read as a dotted line rather
# than as a snake.  It is now merged into MAXIMAL STRAIGHT RUNS -- one rectangle
# per straight section -- with one small patch bridging the 2 px gap at each
# turn.  This is the same geometry `snake2x` ships at HIRES, ported here so the
# two apps differ ONLY in resolution: the snake/snake2x A/B was confounded by
# two variables at once (docs/badge-games.md §9) and this is what un-confounds
# it.
#
# Seven ints per run -- the run's box, then the cell and direction of the
# junction leaving it -- written into a buffer the view owns, because this runs
# every frame and the render path must not allocate.
RUN_STRIDE = 7
# Junction directions, in the model's own clockwise order (UP RIGHT DOWN LEFT),
# with 0 for "this run ends the snake".  `step_code` returns one of these
# instead of a `(dx, dy)` tuple ON PURPOSE: a tuple per body cell per frame is
# 259 heap allocations on a full board, and MicroPython would pay for every one
# of them inside the draw path.
JOIN_NONE = 0
JOIN_UP = 1
JOIN_RIGHT = 2
JOIN_DOWN = 3
JOIN_LEFT = 4


def step_code(here, there):
    """The unit step from `here` to `there`, or ``JOIN_NONE`` if not touching.

    WRAPPING IS NOT ADJACENCY, and this is the one place the tube can go
    visibly wrong.  ``snake_model.step`` wraps with ``% cols`` and ``% rows``,
    so two consecutive body cells can sit at x=19 and x=0 -- neighbours in the
    list and opposite edges of the panel.  Treated as adjacent they merge into
    one run box and the snake renders as a stripe straight across the board.
    """
    dx = there[0] - here[0]
    dy = there[1] - here[1]
    if dy == 0:
        if dx == 1:
            return JOIN_RIGHT
        if dx == -1:
            return JOIN_LEFT
    elif dx == 0:
        if dy == 1:
            return JOIN_DOWN
        if dy == -1:
            return JOIN_UP
    return JOIN_NONE


def merge_runs_into(body, buffer):
    """Fill `buffer` with the body's maximal straight runs; return the count.

    Each run occupies `RUN_STRIDE` slots: ``x0, y0, x1, y1`` -- the run's box in
    CELL space, with ``x0 <= x1`` and ``y0 <= y1`` -- then ``jx, jy, join``: the
    cell the run ENDS on and the direction the body leaves it in, or
    ``JOIN_NONE`` when the run is the tail or the body wraps out of it.

    One rectangle per straight section is the whole performance argument, and
    the junction patch is what makes those rectangles a tube rather than a row
    of beads.  Two adjacent cell cores are ``2 * INSET`` apart, so each junction
    costs ONE more rectangle, at the turning cell only.

    THE PATCH IS A PATCH AND NOT A FATTER RUN.  Widening a whole run's edge
    toward its neighbour is the cheaper-looking idea and it is wrong: a
    serpentine row extended toward the row below meets it along its ENTIRE
    length, and a long snake renders as one solid green field with the coils
    invisible.  `snake2x` saw that in the browser before it was fixed.

    Writes into a caller-owned buffer: called every frame, and this renderer's
    rule is that the draw path does not allocate.
    """
    count = len(body)
    index = 0
    runs = 0
    slot = 0
    while index < count:
        first = index
        run_code = JOIN_NONE
        while index + 1 < count:
            code = step_code(body[index], body[index + 1])
            if code == JOIN_NONE or (run_code != JOIN_NONE and code != run_code):
                break
            run_code = code
            index += 1
        ax, ay = body[first]
        bx, by = body[index]
        buffer[slot] = ax if ax <= bx else bx
        buffer[slot + 1] = ay if ay <= by else by
        buffer[slot + 2] = bx if ax <= bx else ax
        buffer[slot + 3] = by if ay <= by else ay
        buffer[slot + 4] = bx
        buffer[slot + 5] = by
        # A junction exists only where the next cell is a REAL neighbour: a
        # patch drawn across a wrap would be a wart on the board edge pointing
        # at nothing.
        if index + 1 < count:
            buffer[slot + 6] = step_code(body[index], body[index + 1])
        else:
            buffer[slot + 6] = JOIN_NONE
        slot += RUN_STRIDE
        runs += 1
        index += 1
    return runs


def merge_runs(body):
    """`merge_runs_into` as a list of tuples. For tests and probes only."""
    buffer = [0] * (len(body) * RUN_STRIDE + RUN_STRIDE)
    count = merge_runs_into(body, buffer)
    return [
        tuple(buffer[index * RUN_STRIDE:(index + 1) * RUN_STRIDE])
        for index in range(count)
    ]


# ---------------------------------------------------------------------------
# THE PHOSPHOR PASS -- a whole-frame native filter over the live board.
#
# THE OWNER'S RULING, 2026-08-21, after playing the three-snake A/B on glass:
# *"lores and phosphor green looks best on snake.  i think lores just has a
# nicer look for the games."*  He was looking at
# `docs/design/mockups/72-filter-phosphor-lores.png`, which is this app's own
# play frame under `screen.phosphor()`.  This is that frame, shipped.
#
# IT IS NOT ADDED ARTWORK, so `game-art.md` §7 -- "does Snake need anything?
# No" -- is not being reopened.  §7's binding half is about per-CELL art: the
# body is the one element in the five games whose cost is multiplied by 260, so
# nothing may be added per segment.  A filter is ONE fixed-cost native pass over
# the framebuffer whichever way the snake is lying.  §8's rejection of animated
# Glyph backdrops is not reopened either: nothing here moves, allocates, or
# draws a second object that could be mistaken for a game object.
#
# WHAT IT COSTS, and every number here is measured rather than estimated.
#
#   * `phosphor(tint)` at LORES is **9.340 ms median, 9.407 p99** on device
#     (v3.0.2, the reference badge, 100 samples -- see
#     `benchmark/results/reports/2026-08-20-v3.0.2-filter-matrix.md`).  At HIRES
#     it is **35.232 ms**: three frames for one filter, and that is most of why
#     LORES won the ruling rather than taste alone.
#   * The frame budget is QUANTISED by VSYNC at **11.43 ms**, so the only
#     question is which bucket a frame lands in.  The matrix's own headroom
#     column says phosphor leaves **2.09 ms** of app work inside one quantum.
#   * Snake's worst REACHABLE frame is **91 primitive calls** -- an 80-cell
#     staircase (the longest turn-on-every-step path the 20x13 torus allows
#     before it eats itself) with a three-mark critter live and the HUD drawn:
#     86 rectangles, one clear, one blit, three texts.  The documented
#     259-cell full board is *cheaper*, at 33, because the tube merges it into
#     13 runs.  At the device's own ~0.063 ms per individual draw call
#     (4.515 ms for 72 calls, same firmware), 91 calls is about **5.7 ms**.
#   * So the worst frame is about **15.0 ms of work: the SECOND bucket,
#     22.821 ms, 43.8 FPS**, and a short snake's ~10 ms stays in the first at
#     11.43 ms / 87 FPS.  Without the filter both are in the first bucket.
#
# WHY THE SECOND BUCKET IS AN ACCEPTABLE PRICE AND NOT A STUTTER.
#
#   * Snake's motion is driven by `next_step_clock`, not by frame rate.  At the
#     default level 4 the snake steps every 160 ms, so 22.821 ms is still SEVEN
#     renders per step.  The second bucket costs render smoothness and nothing
#     about how the game plays.
#   * **A THIRD BUCKET IS UNREACHABLE, and that is the safety argument.**  It
#     would need 22.86 ms of work, so 13.5 ms of drawing, so about 214 calls --
#     and the merged tube cannot produce more than 91 (`test_snake_app`
#     pins it).  43.8 FPS is therefore a FLOOR, not a midpoint.
#   * Which matters because of the trap in `docs/badge-games.md` §10: price a
#     frame against the MOVEMENT INTERVAL, not only against the quantum.  The
#     tightest interval this app has is level 9's 25 ms, and 22.821 < 25, so
#     even level 9 still gets its nominal 40 steps a second.  A third bucket
#     (34.2 ms) would have slowed it, which is exactly why the bound above is
#     worth having.
#   * And 43-44 FPS is not new here: this app measured **43.35/43.65 FPS** under
#     the Glyph ambient backdrop and the owner played it.  That backdrop was
#     rejected on VISUAL grounds, never on performance.
#
# WHERE IT IS NOT APPLIED, decided by rendering it rather than by argument.
# `phosphor` is a monochrome tint: it takes every pen on the frame to one hue.
# On the board that is the whole point.  On the POST-MORTEM it deletes the two
# readings `game_palette.py` calls load-bearing -- "RED is death and expiry",
# "YELLOW is a record or an armed state" -- and rendered, the `FATAL` headline
# comes back a dim green and the red ring around the fatal cell disappears into
# the body it is drawn over.  The owner approved that screen in full colour and
# has never seen it green.  The intro is left alone for the same reason in
# miniature: the yellow above level 7 is the stake warning, not decoration.
# `game-scenes.md` §6 argues the stopped screens are where a treatment earns
# most; on a monochrome filter over a colour-coded verdict, the opposite holds.
#
# THE TRIM LADDER, per `badge-games.md` §10: one edit, in cost order.
#   1. `PHOSPHOR = False` below -- the filter is gone, everything else stays.
#   2. Nothing else needs cutting: the pass is one native call and one pen
#      built at construction.  There is no per-frame allocation to reclaim.
PHOSPHOR = True


class SnakeView:
    CELL = 8
    # The body's core is the cell inset by this much on every side, so the gap
    # between two consecutive cores is `2 * INSET` and a junction patch of that
    # thickness closes it exactly.  1 px = 0.375 mm, and `snake2x` derives the
    # same value as `CELL // 8` at HIRES, so both games' tubes have the same
    # PHYSICAL wall thickness.
    INSET = 1
    # The last quarter of a critter's twenty-tick life, drawn blinking.
    WARN_MOVES = 5
    # ONE SHAPE PER CRITTER KIND, indexed by the model's `bonus_kind`, as
    # rectangles inside the cell: (x, y, w, h) in cell-local pixels.  Four
    # pixel rows are all there is above the timer bar, so these are marks
    # rather than pictures -- what tells the kinds apart at 0.375 mm a pixel is
    # the three-letter tag on the strip, and the shapes make it obvious that
    # the thing on the board CHANGED.  Cheaper than a sprite sheet by a whole
    # asset, a palette and a licence question.
    BONUS_MARKS = (
        ((1, 1, 6, 2), (1, 4, 6, 1)),                   # VAC: rows reclaimed
        ((1, 1, 2, 4), (4, 1, 2, 4)),                    # IDX: two index rails
        ((2, 1, 4, 4),),                                 # HIT: one page, served
        ((1, 1, 3, 2), (3, 3, 3, 2)),                    # REP: an offset copy
        ((1, 1, 2, 2), (5, 1, 2, 2), (3, 3, 2, 2)),      # RPC: a call fanning out
    )
    COLS = 20
    ROWS = 13
    Y_OFFSET = 16

    def __init__(
        self,
        screen,
        image_api,
        color_api,
        font_api,
        vec2_api,
        accent,
        backdrop=None,
        backdrop_dim=P.BACKDROP_DIM,
    ):
        self.screen = screen
        self.color = color_api
        self.font = font_api
        self.vec2 = vec2_api
        sheet = image_api.load("assets/food-p8.png")
        # The food is drawn at 2x2 cells because the mark is a blob at 8 px, and
        # centred on its cell. Purely visual: the model still occupies one cell.
        self.FOOD_CELL = int(sheet.height) // 2
        self.FOOD_INSET = (self.FOOD_CELL - self.CELL) // 2
        self.FOOD_FRAMES = int(sheet.width) // self.FOOD_CELL
        self.food_row = pick_food_row(accent)
        grid = sheet.spritesheet(self.FOOD_FRAMES, 2)
        # Build every frame once: the render path must not allocate.
        self.food = tuple(grid.sprite(index, self.food_row) for index in range(self.FOOD_FRAMES))
        self.dark = color_api.rgb(*P.DARK)
        self.panel = color_api.rgb(*P.PANEL)
        self.white = color_api.rgb(*P.WHITE)
        self.grey = color_api.rgb(*P.GREY)
        self.red = color_api.rgb(*P.RED)
        self.yellow = color_api.rgb(*P.YELLOW)
        self.accent_tuple = accent
        self.accent = color_api.rgb(*accent)
        self.backdrop = backdrop
        self.backdrop_dim = backdrop_dim
        self.backdrop_scrim = color_api.rgb(0, 0, 0, backdrop_dim)
        self.backdrop_panel = color_api.rgb(*P.BACKDROP_PANEL)
        # Pause dims the playfield and lays a translucent card over it, so the
        # frozen run stays visible underneath and nothing feels destroyed.
        self.pause_scrim = color_api.rgb(*P.PAUSE_SCRIM)
        self.pause_card = color_api.rgb(*P.PAUSE_CARD)
        # Heavier than the pause scrim: the result has to dominate, and the
        # board behind it is an answer, not the subject.
        self.finish_scrim = color_api.rgb(*P.FINISH_SCRIM)
        # The phosphor tint, and it is the palette's `BRAND` rather than a
        # literal: `3ECF8E` is both the Select ramp's player green and the stock
        # launcher's own `phosphor` pen (`launcher/menu/ui.py`), so the filter
        # the owner picked is tinted with the colour the badge already glows in.
        self.phosphor_tint = color_api.rgb(*P.BRAND)
        # BOUND ONCE, and through `getattr` because that is the idiom the device
        # filter probe uses.  27 native filters exist on v3.0.2 and on the pinned
        # playground runtime, but a view that hard-calls `screen.phosphor` would
        # raise inside the frame loop on any runtime that lacks it -- and an
        # exception inside `update()` is a badge RESET, not a missing effect.
        self.phosphor = getattr(screen, "phosphor", None)
        # The tube's scratch buffer, allocated ONCE here and rewritten in place
        # every frame.  Sized for the worst body a player can produce: a
        # staircase turns on every step, and each wrap can start a one-cell run,
        # so one run per cell is the bound.
        #
        # WHAT THE RUN-PACKING BUYS is draw calls, not bytes: a full board draws
        # 26 accent rectangles instead of 259, and 28 instead of 261 counting the
        # panel and the eye -- 233 fewer native calls at the worst body.  A list
        # comprehension here would be correct, allocate every frame, and undo it.
        self.runs = [0] * (self.COLS * self.ROWS * RUN_STRIDE + RUN_STRIDE)

    def phosphor_pass(self):
        """Tint the finished frame green, once, in native code.

        Called by the app AFTER a whole board frame -- the status strip
        included, because a filter over the game but not over the UI reads as a
        bug rather than as a look.  Applied twice it would compound, which is
        why `paused()` does not carry it: `paused()` draws through `play()`, so
        the app calls this once for whichever of the two it just drew.

        A no-op when the runtime has no such filter, and a no-op when
        ``PHOSPHOR`` is off.  Neither case is a fallback look -- it is the app
        exactly as it shipped before 2026-08-21.
        """
        if PHOSPHOR and self.phosphor is not None:
            self.phosphor(self.phosphor_tint)

    def set_backdrop(self, backdrop, dim=P.BACKDROP_DIM):
        """Opt into a retained app background without changing game timing.

        ``backdrop`` supplies ``draw_to(screen)``.  The default remains None,
        preserving the shipped opaque Snake renderer exactly.  A dark scrim
        keeps the snake, bolt and score readable over moving artwork.
        """
        self.backdrop = backdrop
        self.backdrop_dim = dim
        self.backdrop_scrim = self.color.rgb(0, 0, 0, dim)

    def _draw_backdrop(self):
        self.backdrop.draw_to(self.screen)
        if self.backdrop_dim:
            self.screen.pen = self.backdrop_scrim
            self.screen.rectangle(0, 0, 160, 120)

    def _center(self, text, y, scale=1):
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int((160 - width) // 2), y, scale)

    def _right(self, text, y, scale=1, margin=3):
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int(160 - width - margin), y, scale)

    def high_line(self, high_score, high_level=0):
        """``HIGH 118 @9`` — the record and the level that earned it.

        A score without its level is not comparable to anything, which is the
        whole point of a wager ladder.  ``high_level`` is 0 for a record set
        before the badge recorded levels at all, and then the tag is omitted
        rather than invented: the badge does not know, so it does not say.
        """
        if high_level:
            return "HIGH {:03d} @{}".format(high_score, high_level)
        return "HIGH {:03d}".format(high_score)

    def intro(self, level, high_score, high_level=0, accent_source=None):
        """The app root: one press to play, and every key named.

        ``accent_source`` is accepted and ignored.  It used to be printed at the
        player, which told a wearer nothing; it survives on the SNAKE_OPEN line,
        where developer telemetry belongs.
        """
        if self.backdrop is None:
            self.screen.pen = self.dark
            self.screen.clear()
        else:
            self._draw_backdrop()
        self.screen.font = self.font.sins
        self.screen.pen = self.accent
        self._center("SNAKE.SQL", 10, 2)
        self.screen.pen = self.grey
        self._center(self.high_line(high_score, high_level), 40)
        self.screen.pen = self.white
        self._center("B  CONNECT", 58)
        # THE LADDER IS A WAGER AND THE SCREEN HAS TO SAY SO.  It used to read
        # `A/C SPEED n`, which describes a difficulty setting; the level now
        # also multiplies every row the run scores, so the payout is named on
        # the one screen where the choice can still be made.  104 px in
        # `font.sins` against the 160 px canvas.  The top third of the ladder
        # is drawn in the same yellow this app uses for its record states,
        # because 7-9 is where the stake stops being a detail.
        self.screen.pen = self.yellow if level >= 7 else self.grey
        self._center("A/C LEVEL {}  PAYS x{}".format(level, level), 76)
        self.screen.pen = self.grey
        # TWO VERBS, BECAUSE THE TWO PAIRS NO LONGER DO THE SAME THING.  UP and
        # DOWN point where they are drawn; A and C turn the snake left and
        # right from wherever its head is pointing, so calling all four "STEER"
        # would now be a lie by omission on the one screen a player reads
        # before playing.  Measured at 106 px in `font.sins` against the 160 px
        # canvas, and re-used verb-first on the pause card at the same width.
        self._center("UP DN STEER  A C TURN", 92)
        # HOME is silicon and cannot be rebound, so naming it is the only honest
        # way to offer a labelled route to the launcher.
        self._center("HOME  EXIT", 106)

    def _head(self, state):
        """A full-cell block cursor with the eye knocked out of it.

        docs/design/snake-art.md §4.2.  The head used to be a 6x6 core exactly
        like a body segment, so it read as "the segment with the dot on it".  A
        filled 8x8 cell is 3.0 mm against the body's 2.25 mm, which is what
        makes it read as a head -- and to anyone who lives in a terminal, a
        filled block with a character knocked out of it is a block cursor
        sitting on the insert position, which is literally what the head is.

        Raster, not the rounded vector snout `snake2x` draws, and that was
        settled by rendering both at LORES rather than by argument -- the
        captures are `15-head-block.png` and `16-head-rounded.png`.  At 8 px a
        `CELL // 4` radius produces NO curve and no antialiasing whatsoever:
        picovector removes exactly three of the head's 64 pixels, all of them
        on its right side, so the "rounded snout" is an asymmetric one-pixel
        nick out of a square with the eye sitting flush against it.  A curve
        needs pixels to live in and at 3.0 mm there are none to spare.

        Two rectangles, O(1), so it cannot move the length at which the frame
        cost steps.  The eye keeps its existing leading-edge logic exactly --
        `+5` or `+1` per axis by heading -- now inside a full cell rather than a
        6 px core.  It is not blinked: `snake2x` does not blink either, and the
        A/B this change exists to settle must vary resolution and nothing else.
        """
        x, y = state["body"][0]
        px = x * self.CELL
        py = y * self.CELL + self.Y_OFFSET
        self.screen.pen = self.accent
        self.screen.rectangle(px, py, self.CELL, self.CELL)
        direction = state["direction"]
        eye_x = px + (5 if direction != 3 else 1)
        eye_y = py + (5 if direction == 2 else 1)
        self.screen.pen = self.dark
        self.screen.rectangle(eye_x, eye_y, 2, 2)

    def _bonus_mark(self, state):
        """The critter and its timer bar, drawn rather than blitted.

        Snake II's bonus was a creature with a timer bar beside it, and the bar
        is the part worth copying: it is the only thing on the board that says
        "this is going" without the player reading a number.  Ours is the bottom
        pixel row of the critter's own cell, shrinking from six pixels to one,
        so the countdown travels with the thing it belongs to and costs one
        rectangle.

        Above it sits a mark chosen by kind, so consecutive critters are
        visibly different things and not one thing with a different label.

        Both blink red for the last `WARN_MOVES` moves, off the model's own
        countdown rather than a clock, so a frozen board stays frozen.
        """
        x, y = state["bonus"]
        px = x * self.CELL
        py = y * self.CELL + self.Y_OFFSET
        left = state["bonus_left"]
        expiring = left <= self.WARN_MOVES and left & 1
        self.screen.pen = self.red if expiring else self.yellow
        kind = state["bonus_kind"] % len(self.BONUS_MARKS)
        for mx, my, mw, mh in self.BONUS_MARKS[kind]:
            self.screen.rectangle(px + mx, py + my, mw, mh)
        # Scaled off value-against-peak rather than the model's tick window, so
        # the bar and the number in the strip are the SAME fraction and cannot
        # drift apart, and the view still needs nothing from the model.  Never
        # zero-width while the critter is on the board: it is a countdown, not a
        # fuel gauge, and one pixel still reads as "now".
        width = max(1, 6 * state["bonus_value"] // (state["bonus_peak"] or 1))
        self.screen.rectangle(px + 1, py + 6, min(6, width), 1)

    def _board(self, state, food_frame=0):
        """Background, playfield, snake and food — no HUD, no chrome."""
        if self.backdrop is None:
            self.screen.pen = self.dark
            self.screen.clear()
            self.screen.pen = self.panel
        else:
            self._draw_backdrop()
            self.screen.pen = self.backdrop_panel
        self.screen.rectangle(0, self.Y_OFFSET, 160, 104)
        self.screen.font = self.font.sins
        self.screen.pen = self.accent
        # ONE RECTANGLE PER STRAIGHT SECTION, plus one patch per turn.  A
        # `while` rather than `for _ in range(count)` because `range` allocates
        # and this is the draw path.
        cell = self.CELL
        inset = self.INSET
        offset = self.Y_OFFSET
        runs = self.runs
        core = cell - inset - inset
        span = inset + inset
        slot = 0
        end = merge_runs_into(state["body"], runs) * RUN_STRIDE
        while slot < end:
            self.screen.rectangle(
                runs[slot] * cell + inset,
                runs[slot + 1] * cell + offset + inset,
                (runs[slot + 2] - runs[slot] + 1) * cell - span,
                (runs[slot + 3] - runs[slot + 1] + 1) * cell - span,
            )
            join = runs[slot + 6]
            if join:
                # The gap between this run's last cell and the first cell of the
                # next one: the corner, and nothing else.
                jx = runs[slot + 4] * cell
                jy = runs[slot + 5] * cell + offset
                if join == JOIN_DOWN:
                    self.screen.rectangle(jx + inset, jy + cell - inset, core, span)
                elif join == JOIN_UP:
                    self.screen.rectangle(jx + inset, jy - inset, core, span)
                elif join == JOIN_RIGHT:
                    self.screen.rectangle(jx + cell - inset, jy + inset, span, core)
                else:
                    self.screen.rectangle(jx - inset, jy + inset, span, core)
            slot += RUN_STRIDE
        self._head(state)
        if state["bonus"] is not None:
            self._bonus_mark(state)
        if state["food"] is not None:
            self.screen.blit(
                self.food[food_frame % self.FOOD_FRAMES],
                self.vec2(
                    state["food"][0] * self.CELL - self.FOOD_INSET,
                    state["food"][1] * self.CELL + self.Y_OFFSET - self.FOOD_INSET,
                ),
            )

    def play(self, state, high_score, food_frame=0, hint="B  PAUSE", hint_pen=None, best=False):
        self._board(state, food_frame)
        self.screen.pen = self.white
        self.screen.text("ROWS {:03d}".format(state["score"]), 2, 2)
        # The status strip already existed, so labelling B here costs no
        # playfield and is drawn for the life of the screen rather than on a
        # timer.  A and C are directions during play — turns, since 2026-08-17
        # — and must never be labelled as commands, which is why there is no
        # bottom softkey bar.
        self.screen.pen = self.grey if hint_pen is None else hint_pen
        self._center(hint, 2)
        # THE CRITTER'S COUNTDOWN TAKES THE NUMBER SLOT, NEVER THE KEY LABEL.
        # It is the one thing on screen that is falling while the player
        # decides, so it has to be readable — but the centre slot is where B is
        # named, and this app's own rule is that a key is named for the life of
        # the screen and never on a timer.  The right-hand slot already changes
        # meaning (it becomes BEST once the record falls), so a figure that can
        # wait five seconds yields to one that cannot.  `VAC 90` is the widest
        # this can get: 33 px against the 29 px `HI 000` it replaces.
        if state["bonus_value"]:
            self.screen.pen = self.yellow
            self._right("{} {}".format(state["bonus_tag"], state["bonus_value"]), 2)
        elif best:
            # The stored number stopped being a target the moment it was
            # passed, and ROWS already carries the live score, so the slot
            # carries the state instead of repeating a figure.
            self.screen.pen = self.yellow
            self._right("BEST", 2)
        else:
            self.screen.pen = self.grey
            self._right("HI {:03d}".format(high_score), 2)

    def paused(self, state, high_score, food_frame=0, best=False, confirm=False):
        """The frozen board, dimmed, under a card carrying the way out.

        The board is drawn first and stays visible through the card, so pausing
        visibly did not destroy the run.  The status strip does not move: only
        its middle word changes, so the eye does not have to re-find ROWS or HI.

        The key map lives here — the pause screen IS the map, rather than a
        labelled command that opens yet another screen — but it is written verb
        first (``STEER UP DN  TURN A C``) while every live command on this card
        is written key first (``B   RESUME``).  A is named in both, so the two
        forms have to be distinguishable: one describes the game, the other
        names this screen's keys.  The map carries both verbs because A and C
        are relative turns while UP and DOWN are absolute.  ``confirm`` is the belt to that brace.  The
        first A does not quit; it turns the map line into the question and the
        A label red, and only the second A ends the run.  A player who taps A
        expecting to steer therefore loses nothing.

        Row positions do not move between the two states, so answering the
        question is not a moving target.
        """
        self.play(state, high_score, food_frame, "PAUSED", self.yellow, best)
        self.screen.pen = self.pause_scrim
        self.screen.rectangle(0, self.Y_OFFSET, 160, 104)
        self.screen.pen = self.pause_card
        self.screen.rectangle(12, 26, 136, 88)
        # The label slot is always drawn, so the layout never jumps.
        self.screen.pen = self.yellow if best else self.grey
        self._center("NEW HIGH" if best else "HIGH", 30)
        self.screen.pen = self.yellow if best else self.accent
        self._center("{:03d}".format(state["score"] if best else high_score), 42, 2)
        # The stake, restated where the hero number is.  A player comparing
        # their run against the record needs the level of the run they are in
        # to read either number, and this card is the only screen with room to
        # spell it out.  84 px inside the 136 px card.
        self.screen.pen = self.grey
        self._center("LEVEL {}  PAYS x{}".format(state["level"], state["level"]), 60)
        if confirm:
            self.screen.pen = self.yellow
            self._center("QUIT THIS RUN?", 72)
        else:
            self.screen.pen = self.grey
            self._center("STEER UP DN  TURN A C", 72)
        self.screen.pen = self.white
        self._center("B   RESUME", 86)
        self.screen.pen = self.red if confirm else self.grey
        self._center("A   QUIT NOW" if confirm else "A   QUIT", 100)

    HEADLINE_BOTTOM = 62

    # THE POST-MORTEM'S SHARED FOOTER, so the win screen and the death screen
    # answer B and A on the SAME rows.  A key that moves between two endings is
    # a key the player has to re-find on the one screen they read hardest.
    FOOTER_SCORE = 69
    # Reserved for the one line the badge only prints when it has bad news:
    # a record it could not store.  The row exists whether or not it is used,
    # because rows that move when a state appears make the state harder to read
    # than the state itself (the pause card's own rule, applied here).
    FOOTER_WARNING = 82
    FOOTER_RECONNECT = 93
    FOOTER_MENU = 106

    def _death_dump(self, fatal):
        """The death screen as a psql error, in Flappy's shipped FATAL idiom.

        `docs/design/snake-art.md` §4.4 made the argument and the owner approved
        the render (`docs/design/mockups/sheet-deaths.png`, frame
        `20-death-snake-23505`).  The screen used to say `CONNECTION TERMINATED`,
        which is product voice and is also **not what happened** — the
        connection was fine.  The head tried to occupy a cell that was already
        occupied, which is a duplicate primary key, and because
        `snake_model.step` WRAPS at every edge, self-collision is the only way
        to die in this game.  So `23505` is correct on 100% of deaths with no
        special case.  If walls were ever added that stops being true and this
        screen needs a second code.

        Four details, each doing real work:

        * **`23505` is the real SQLSTATE for `unique_violation`,** and error
          text is the cheapest theming on this badge: no asset, no licence, no
          frame budget, and it is the screen a developer photographs
          (`docs/badge-games.md` §7.1).
        * **`DETAIL` carries `state["fatal"]`,** the exact cell the head tried
          to enter.  Since 2026-08-22 it is the only place the COLUMN is stated:
          `_fatal_marker` is a stub on the left edge naming the ROW, because no
          mark on the cell itself can stay out of this block's line boxes.  The
          two still answer "what killed me" together — the row as a picture and
          the cell as a fact — and the fact is the precise half.
        * **The headline does not vary with the cause.** Flappy's pass found
          that a per-death HEADLINE costs the screen its identity while a
          per-cause `HINT` row does not, because `HINT` is the row Postgres
          itself varies.  Snake has one cause, so its HINT is fixed too.
        * **Lowercase below the headline.** Postgres does not shout, and a
          transcript is what gets photographed.  `font.sins` has real lowercase
          glyphs.  The uppercase `FATAL` is the emotional beat; everything under
          it is the dump.

        Widths, measured through `font.sins` in the pinned runtime rather than
        estimated: `FATAL` 58 px at scale 2, `23505 unique_violation` 123 px,
        `DETAIL  key (x,y)=(11,7)` 118 px, `HINT  it ate its own key` 117 px —
        all against the 160 px canvas.
        """
        self.screen.pen = self.red
        self._center("FATAL", 3, 2)                          # 58 px
        self._center("23505 unique_violation", 27)           # 123 px
        self.screen.pen = self.grey
        self._center(
            "DETAIL  key (x,y)=({},{})".format(fatal[0], fatal[1])
            if fatal is not None
            else "DETAIL  table is full",
            41,
        )                                                    # 118 px
        self._center("HINT  it ate its own key", 55)         # 117 px

    # ---- the death card's one mark, and the lane it lives in ----------------
    #
    # A 3 PX STUB ON THE PANEL'S LEFT EDGE, ON THE FATAL ROW.  It used to be a
    # hollow RING around the fatal cell, and that was wrong: `font.sins`
    # occupies a 12 px line box at scale 1 (measured through
    # `screen.measure_text` in the pinned runtime), the psql block's rows tile
    # y 3..118 of a 120 px panel, and the ring can be at any of 260 cells — so
    # rendered at 13 heights the ring landed inside a row's line box at five of
    # them, one of them the `23505 unique_violation` row it shares a hue with.
    #
    # THE RING'S OWN DOCSTRING ADMITTED THIS and treated it as acceptable:
    # "nearly half of all deaths put this marker on top of CONNECTION
    # TERMINATED; a filled block deletes a letter there, a ring draws a box
    # around one."  The owner's 2026-08-22 ruling, after playing Flappy on
    # hardware, is that a box around a letter is not acceptable either: RED ink
    # on a RED row is contrast ratio 1.0, so a keyline between two glyphs erases
    # them whether or not the glyph draws on top.  No marker ink of any kind may
    # share a text row's line box.
    #
    # THE LEFT EDGE IS THE ONLY LANE WITH A REAL MARGIN, and this is the
    # measurement rather than an eyeball.  Every row on this card is centred by
    # `_center`, so its x start is `(160 - width) // 2`; the widest string the
    # card can print is `WARNING  record not written` at 141 px, which starts at
    # x 9.  A 3 px stub at x 0..2 therefore clears the widest row by SIX pixels
    # and the next widest -- `DETAIL  key (x,y)=(18,10)`, 124 px, x 18 -- by
    # fifteen.  There is no comparable lane anywhere else: the only free
    # horizontal band is y 118..119, two pixels between `A  MENU`'s line box and
    # the panel edge, and a two-pixel stub with zero clearance is a marker one
    # row move deletes.
    #
    # WHAT IS LOST AND WHAT IS NOT.  The stub names the ROW, not the cell.  The
    # cell is not lost: `_death_dump` prints it in words on the `DETAIL` row --
    # `DETAIL  key (x,y)=(11,7)` -- which is more precise than a ring ever was.
    # This is also the shape `pong_view._fatal_marker` already ships, on the
    # badge the owner has been playing, with no complaint against it.
    #
    # Snake does NOT take Flappy's answer, which was to drop the marker
    # entirely.  Flappy could: its frozen world still holds the client sprite at
    # the death height under the scrim, so the screen keeps its picture for free.
    # Snake's fatal cell holds an ordinary body segment and nothing distinguishes
    # it once the ring is gone, so dropping the mark here would leave the card
    # with no picture at all.
    MARKER_W = 3

    def _fatal_marker(self, fatal):
        """Mark the board row the head died trying to enter, at full red.

        One rectangle on the panel's left edge, where the four of the old ring
        were.  See the block above for the arithmetic that put it there and for
        why this game keeps a mark where Flappy drops one.
        """
        self.screen.pen = self.red
        self.screen.rectangle(
            0, fatal[1] * self.CELL + self.Y_OFFSET, self.MARKER_W, self.CELL
        )

    def finished(self, state, high_score, food_frame=0, best=False,
                 save_failed=False):
        """The board that ended the run, held under the result.

        The first question on dying is "what killed me?", and the board used to
        vanish instantly, taking the answer with it.  The board is now held under
        the scrim, the fatal cell is named in words on the `DETAIL` row, and its
        ROW is marked in red on the panel's left edge.  This is a render state,
        not a phase: B and A are live from the first frame and nothing is gated
        on a timer, so an impatient player at a booth is never made to wait.

        ``save_failed`` IS NOT DECORATION.  The high-score write is caught in
        `bank_run` so that a full volume cannot turn every death into a reboot,
        and the record on disk survives intact either way -- but a run that beat
        the record and could not store it must not sit here in the yellow this
        app uses for `BEST` and let the player believe it was banked.  When the
        flag is set the run's line drops back to white and one row says so.
        """
        self._board(state, food_frame)
        self.screen.pen = self.finish_scrim
        self.screen.rectangle(0, 0, 160, 120)
        won = state["status"] == "won"
        fatal = None if won else state.get("fatal")
        # AFTER the scrim, never under it.  Drawn first the 195-alpha black
        # multiplied (245,58,88) down to a near-black maroon — measured at
        # RGB(57,14,21) on this app's own committed evidence, against a (3,7,8)
        # panel.  The one thing the screen exists to answer was the one thing
        # on it that could not be read.
        if fatal is not None:
            self._fatal_marker(fatal)
        if won:
            self.screen.pen = self.yellow
            self._center("TABLE FULL", 18, 2)      # 112 px
        else:
            self._death_dump(fatal)
        # YELLOW HERE IS A CLAIM, so a failed commit takes it away.  `best`
        # latched during play against the record that was on disk; if the write
        # then failed, `high_score` is still the OLD number and this line would
        # read "you beat 118" in the record colour beside a HIGH that is still
        # 118.  White plus the warning row is the honest pair.
        self.screen.pen = self.yellow if best and not save_failed else self.white
        # The run's level rides with the run's number, because "255" answers
        # nothing on a ladder where the same play is worth nine times more at
        # the top. 113 px against the 160 px canvas at three digits each.
        self._center(
            "ROWS {:03d} @{}  HIGH {:03d}".format(
                state["score"], state["level"], high_score
            ),
            self.FOOTER_SCORE,
        )
        if save_failed:
            # YELLOW, NOT RED, and the pen is the argument.  On this screen red
            # is the CAUSE OF DEATH -- the headline and the stub on the fatal
            # row -- and a failed flash write did not kill the run.
            # Yellow is this app's record channel (`BEST`, `NEW HIGH`, the top
            # of the stake ladder), and what this row reports is the record's
            # state.  141 px against the 160 px canvas.
            self.screen.pen = self.yellow
            self._center("WARNING  record not written", self.FOOTER_WARNING)
        self.screen.pen = self.accent
        self._center("B  RECONNECT", self.FOOTER_RECONNECT)
        # A badge that died in a pocket must not sit lit on a death screen all
        # day with a restart as its only offer.
        self.screen.pen = self.grey
        self._center("A  MENU", self.FOOTER_MENU)
