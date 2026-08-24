"""LORES VACUUM.SQL renderer using injected Badgeware APIs.

Draws and nothing else.  It reads the model's state the way it reads the score
— as data — and never computes a game rule, so the whole file can be exercised
against a recording screen with no runtime at all.

Everything here is rectangles and text.  There is no sprite sheet, no asset
pack and no PNG decode on the load path: the one asset this app installs is its
24x24 launcher icon, which the launcher draws and this file never opens.
"""

import breakout_model as M

# The five games' one palette (`shared/game_palette.py`, vendored here by
# `scripts/sync_ui.py`).  Every pen below that is not part of THIS game's own
# argument comes from it, so the ten pens the five views used to duplicate can
# be changed in one place.  Tuples only -- a pen can only be minted through the
# injected `color` API, which the palette has no access to and should not.
import game_palette as P


# The Supabase green, to within a unit.  Used for the SCAN bar, because the
# scan is the thing the player IS.
ACCENT = P.BRAND


class BreakoutView:
    # The status strip is 16 px, exactly Snake's and Pong's, so the court below
    # it is the same 104 px and all three games' playfields are the same size.
    Y_OFFSET = 16
    COURT_W = M.COURT_W
    COURT_H = M.COURT_H

    # Remaining passes, as pips in the floor margin below the scan lane.
    # THEY ARE NOT IN THE STATUS STRIP AND THAT IS MEASURED, NOT TASTE: the
    # strip's three slots already spend 125 of 160 px, and inserting even three
    # 3 px pips drops the hint's gutters from 15 px to 6, under the 11 px the
    # button rules ask for.  The floor margin is empty, it is beside the thing
    # the pips are about, and the worker crosses it only on the tick it is lost.
    PIP = 3
    PIP_GAP = 2
    PIP_X = 2
    PIP_Y = M.COURT_H - 5

    # One pen per heap row, hottest at the tail, because the tail rows are the
    # ones a real VACUUM can truncate and they are the ones that pay most.  A
    # row's colour and its value are the same statement.
    #
    # NONE OF THE FIVE IS ONE OF THE UI PENS, and that is a rule rather than a
    # coincidence: the first draft made row 2 exactly `self.yellow`, which is
    # the colour of the worker while it rides the scan, so a row of pages and
    # the ball were the same ink.  `test_breakout_app` pins the disjointness.
    ROW_PENS = (
        (238, 74, 74),
        (243, 130, 60),
        (232, 186, 62),
        (108, 158, 152),
        (58, 92, 104),
    )

    # ---- the free-space inks ------------------------------------------------
    #
    # THE TABLE NEVER GROWS, which is the one thing a real VACUUM promises and
    # the one thing this picture used to contradict: a reclaimed page simply
    # stopped being drawn, so the heap appeared to shrink to nothing and the
    # reward for playing well was an emptier panel.  Measured through this
    # app's own harness, a full heap was 60 ops a frame and a compacted one was
    # **10** — the screen really did empty out.
    #
    # `docs/design/game-art.md` §4 and `docs/design/game-scenes.md` §5.2 are
    # the specification, and the composed version was rendered before it was
    # built (`docs/design/mockups/patches/breakout_vacuum.py`, frames
    # `07`/`08-breakout-*-after` and `43`-`45-breakout-pile-*`).  Four inks, and
    # NONE OF THEM IS IN `shared/game_palette.py` for the reason that file
    # states about `ROW_PENS` itself: an ink that is part of ONE game's argument
    # is not shared style.  These four are the argument — they are the heap's
    # own free-space map — and the ten pens that ARE shared still come from `P`.
    #
    # A reclaimed page: the page is still in the heap and it is free now.  Also
    # the pen the reclaimed pile is stacked in, deliberately the same ink,
    # because it is the same fact seen from the other end of the screen.
    FREE_PEN = (30, 54, 62)
    # HEAP END: the 1 px rule under the lowest surviving row is what truncation
    # would hand back.  NOT the accent, and that is on purpose — a full-width
    # accent rule on this court reads as a second scan, which is
    # `game-scenes.md` §4.2's false-positive failure mode and is not fixable by
    # dimming.  A desaturated teal is in the heap's own family instead.
    HEAP_END_PEN = (120, 170, 180)
    # THE COURT'S FURNITURE, ONE INK.  Two marks share it because they are the
    # same kind of thing — the structure of the file, not an object in it:
    #
    #   * the page-boundary rules, one down each of the nine mortar columns the
    #     model's `BRICK_W` pitch already defines, so the court reads as a
    #     fifty-slot heap FILE instead of a void with bricks in it;
    #   * the full-width rule the scan rides, because the scan is a POSITION IN
    #     THE HEAP and a position needs something to be a position along.
    #
    # Barely off the panel (11, 28, 34) on purpose.  Two dim pens a unit apart
    # is exactly the drift `shared/game_palette.py` was built to remove, so
    # this is one constant with two callers rather than two constants.
    RULE_PEN = (17, 38, 45)
    # Each live page's 1 px header, 45% of the way toward black from the row's
    # own pen, so a page reads as a PAGE rather than as a band of colour.
    # Derived from `ROW_PENS` rather than typed out, so a row recolour cannot
    # leave its header behind — and integer arithmetic, because
    # `int(channel * 0.55)` and `channel * 55 // 100` agree on all fifteen
    # channels and only one of them is float-free.
    HEADER_PENS = tuple(
        tuple(channel * 55 // 100 for channel in pen) for pen in ROW_PENS
    )

    def __init__(self, screen, image_api, color_api, font_api, vec2_api,
                 accent=ACCENT):
        self.screen = screen
        # KEPT AND UNUSED, DELIBERATELY.  This game is procedural and never
        # blits, so it needs neither the image loader nor vec2 — but the seam is
        # the one Pong and Snake hold open, and a sibling that DOES want a
        # sprite should copy a constructor that already has one rather than
        # rediscovering which globals Badgeware injects.
        self.image = image_api
        self.vec2 = vec2_api
        self.color = color_api
        self.font = font_api
        self.dark = color_api.rgb(*P.DARK)
        self.panel = color_api.rgb(*P.PANEL)
        self.white = color_api.rgb(*P.WHITE)
        self.grey = color_api.rgb(*P.GREY)
        self.red = color_api.rgb(*P.RED)
        self.yellow = color_api.rgb(*P.YELLOW)
        self.accent_tuple = accent
        self.accent = color_api.rgb(*accent)
        self.rows = tuple(color_api.rgb(*pen) for pen in self.ROW_PENS)
        self.headers = tuple(color_api.rgb(*pen) for pen in self.HEADER_PENS)
        self.free = color_api.rgb(*self.FREE_PEN)
        self.heap_end = color_api.rgb(*self.HEAP_END_PEN)
        self.rule = color_api.rgb(*self.RULE_PEN)
        # THE BACKDROP DECISION, AS ONE FLAG.  `docs/design/game-scenes.md`
        # §5.2 calls Breakout "the one genuinely open case" for a scene and says
        # to decide by looking; the renders are in
        # `results/evidence/playground/` and the README says which way it went
        # and why.  Set this False and VACUUM.SQL is an Atari void again — nine
        # rectangles, one line, no other behaviour changes — which is the trim
        # `docs/badge-games.md` §10 asks a scene to publish so the owner can cut
        # it in one commit if it does not land on glass.  `FlappyView.room` is
        # the same seam for the same reason.
        self.ruled = True
        # Pause dims the court and lays a translucent card over it, so the
        # frozen run stays visible underneath and nothing feels destroyed.
        self.pause_scrim = color_api.rgb(*P.PAUSE_SCRIM)
        self.pause_card = color_api.rgb(*P.PAUSE_CARD)
        # Heavier than the pause scrim: the result has to dominate, and the
        # heap behind it is an answer, not the subject.
        self.finish_scrim = color_api.rgb(*P.FINISH_SCRIM)

    # ---- text helpers -------------------------------------------------------

    def _center(self, text, y, scale=1):
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int((160 - width) // 2), y, scale)

    def _right(self, text, y, scale=1, margin=3):
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int(160 - width - margin), y, scale)

    def _center_between(self, text, left, right, y, scale=1):
        """Centre a label in the gap two other labels have left it.

        THE STATUS STRIP CANNOT USE `_center` AND THIS IS THE REASON.  Snake's
        left slot is `ROWS 000` at 46 px and Pong's is `SYNCED 000` at 57; ours
        is `PAGES 000` at 51, and a canvas-centred `B  PAUSE` starts at x = 59
        — eight pixels after the score ends.  That gutter reads as one run-on
        word.  Centring in the REMAINING space instead puts 15 px either side
        of the hint, comfortably past the 11 px clearance the button rules ask
        of the softkey bar, and it is measured rather than nudged.
        """
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int(left + (right - left - width) // 2), y, scale)

    def high_line(self, high_score):
        return "HIGH {:03d}".format(high_score)

    # ---- the error block ----------------------------------------------------
    #
    # SQLSTATE 55P03 is `lock_not_available`, and it is the real Postgres error
    # for the thing that has just happened: a VACUUM that cannot take the lock
    # it needs on a page gives up on that page.  `docs/design/game-art.md` §13.1
    # assigns the code, `docs/design/game-scenes.md` §7.1 endorses it, and
    # `docs/badge-games.md` §7 calls it the cheapest theming on the badge —
    # strings, no asset, no licence, no frame budget, and it is the screen a
    # developer photographs.  Rendered as `docs/design/mockups/22-death-breakout-55P03.png`
    # before it was built, and the owner approved that sheet.
    #
    # Class-level constants rather than literals inside `finished`, so the
    # string a photograph will carry is written down once and a test can name
    # it.  Flappy's shipped `FATAL` block is the idiom being followed; the five
    # games' death screens are meant to read as one product.
    SQLSTATE = "55P03"
    CONDITION = "lock_not_available"
    # ONE HINT, NOT A TABLE, because this game has exactly one way to die.
    # Flappy keys its HINT on the model's `cause`; the worker getting past the
    # scan is the only cause here, so a dictionary would be a lookup with one
    # entry pretending to be a mechanism.
    HINT = "HINT  the worker got past"

    def sqlstate_line(self):
        """The error the vacuum raised, exactly as Postgres spells it."""
        return "{} {}".format(self.SQLSTATE, self.CONDITION)

    def detail_line(self, state):
        """How many pages the sweep never got to — a real fact about the run.

        `state["left"]` is the model's own live count, maintained by `_reclaim`,
        so this costs a dictionary read rather than a scan of the heap: a `sum`
        over fifty bytes on the frame the screen appears is affordable, but a
        generator expression in a draw path is the habit, not the cost.
        """
        return "DETAIL  lock on page {:02d}".format(max(0, state["left"]))

    # ---- screens ------------------------------------------------------------

    def intro(self, level, high_score):
        """The app root: one press to play, and every key named."""
        self.screen.pen = self.dark
        self.screen.clear()
        self.screen.font = self.font.sins
        self.screen.pen = self.accent
        # 118 px at scale 2 against the 160 px canvas.
        self._center("VACUUM.SQL", 10, 2)
        self.screen.pen = self.grey
        self._center(self.high_line(high_score), 40)
        self.screen.pen = self.white
        self._center("B  CONNECT", 58)
        # LEVEL IS SPEED AND THE SCREEN SAYS ONLY THAT.  Snake's equivalent row
        # reads `PAYS xn` because its level prices every row; ours does not, so
        # claiming a payout here would be a lie.
        self.screen.pen = self.yellow if level >= 7 else self.grey
        self._center("A/C LEVEL {}".format(level), 76)
        self.screen.pen = self.grey
        # A AND C DO TWO THINGS IN THIS APP and the screen has to say so
        # without contradicting itself: here they pick the level, in a run they
        # are the scan.  The qualifier is what makes the two rows one
        # statement instead of two competing ones.
        self._center("IN PLAY  A/C SCAN", 92)
        # HOME is silicon and cannot be rebound.  Naming it is the honest way
        # to offer a labelled route to the launcher, and it is what Snake and
        # Pong both print; `docs/badge-button-rules.md` §10 argues against it,
        # and that disagreement is recorded in this app's README rather than
        # settled here by a third game inventing a third answer.
        self._center("HOME  EXIT", 106)

    # ---- the court ----------------------------------------------------------

    def _heap(self, state):
        """The whole heap — live pages, free space and the truncation edge.

        FIFTY PAGE SLOTS ARE ALWAYS DRAWN, and that is the point of the pass:
        a live page is a 15x5 fill in its row's pen with a 1 px header on top,
        and a reclaimed one is a 15x1 keyline in the shared free-space pen.  So
        the page rectangle total is a constant 50 for the whole run and the
        heap cannot visibly shrink — which is exactly what a real VACUUM does,
        because it makes space REUSABLE rather than handing it back.

        Batched three pen writes per row rather than one per cell: the pen is
        the state change and the rectangle is the cheap part.  Within a row the
        fills all precede the headers, and a header only ever lands on its own
        cell's fill, so the framebuffer is identical to a per-cell interleave
        for a fifth of the pen traffic.

        `M.brick_rect` is still the only source of page geometry, called ONCE
        PER ROW instead of once per cell: `y`, `width` and `height` are
        constant across a row and only `x` advances, by the model's own
        `BRICK_W`.  That is 5 calls a frame where the old loop made 50, and
        `test_the_row_batched_geometry_agrees_with_brick_rect` walks all fifty
        cells asserting the two agree, so the saving cannot become a drift.

        Returns the number of reclaimed pages, because the caller needs it for
        the pile and this loop has already counted it.
        """
        bricks = state["bricks"]
        freed = 0
        lowest_alive = -1
        for row in range(M.BRICK_ROWS):
            base = row * M.BRICK_COLS
            _x, y, width, height = M.brick_rect(base)
            top = self.Y_OFFSET + y
            self.screen.pen = self.rows[row]
            for col in range(M.BRICK_COLS):
                if bricks[base + col]:
                    self.screen.rectangle(col * M.BRICK_W, top, width, height)
                    lowest_alive = row
            self.screen.pen = self.headers[row]
            for col in range(M.BRICK_COLS):
                if bricks[base + col]:
                    self.screen.rectangle(col * M.BRICK_W, top, width, 1)
            self.screen.pen = self.free
            for col in range(M.BRICK_COLS):
                if not bricks[base + col]:
                    freed += 1
                    self.screen.rectangle(
                        col * M.BRICK_W, top + height - 1, width, 1
                    )
        # HEAP END: what truncation would hand back, right now.  Drawn under
        # the lowest surviving row because `ROW_PENS` is hottest at the tail and
        # `ROW_VALUE` is 5-4-3-2-1 from the tail down, so the bottom of the
        # heap is the end of the file.  Nothing standing means nothing to
        # truncate off, so the rule is not drawn at all.
        if lowest_alive >= 0:
            self.screen.pen = self.heap_end
            self.screen.rectangle(
                0,
                self.Y_OFFSET + M.BRICK_TOP + (lowest_alive + 1) * M.BRICK_H - 1,
                self.COURT_W,
                1,
            )
        return freed

    def _pile(self, freed):
        """The reclaimed pages, stacked from the floor up in the heap's grid.

        THE GAME CONSERVES ITS INK.  The heap empties from wherever the player
        swept and the pile fills from the floor, one dim page per page freed, so
        the panel is at its fullest exactly when the run is going well —
        `game-scenes.md` §5.2 calls this the best idea in the document and the
        reason is that it inverts the flagged defect instead of decorating
        around it.

        Same 10-wide grid and same 15x5 page as the heap, because it is the
        same fifty pages.  The two regions are DISJOINT by construction — the
        heap ends at court y 40 and the pile's top row starts at 64 with every
        page freed — so no legibility question arises between them, and the pen
        is 47.7 in Rec. 601 luma against the near row's 85.2, the scan's 156.2
        and the worker's 255, so it cannot be mistaken for any of them either.

        Counted rows rather than `divmod` per page: `divmod` allocates a tuple
        on every one of up to fifty iterations of a draw path, and this loop
        allocates nothing.  A partial row fills from the left, which is the
        order the mock-up rendered.
        """
        if not freed:
            return
        self.screen.pen = self.free
        row = 0
        remaining = freed
        while remaining > 0:
            count = remaining if remaining < M.BRICK_COLS else M.BRICK_COLS
            top = self.Y_OFFSET + M.SCAN_Y - (row + 1) * M.BRICK_H
            for col in range(count):
                self.screen.rectangle(
                    col * M.BRICK_W, top, M.BRICK_W - 1, M.BRICK_H - 1
                )
            remaining -= count
            row += 1

    def _rules(self):
        """The heap file's page boundaries, ruled down the whole court.

        THE BACKDROP, AND IT IS THE ONE THE MECHANIC ALREADY OWNS.  Every
        vertical is a mortar column the model defines: a page cell is
        `BRICK_W` = 16 px wide and the view draws 15 of it, so `col * BRICK_W -
        1` is the seam, and nine of them is the whole file.  So the court stops
        being an empty void that happens to have bricks at the top and becomes
        the fifty-slot heap the game is about — which is the same sentence as
        the mechanic, not decoration laid over it.

        Why this is safe by construction rather than by tuning, in the terms
        `game-scenes.md` §4 sets out:

        * **Contrast.**  The ink is 32.5 in Rec. 601 luma against the court's
          23.6, so it is visible; and it is below the free-space pen's 47.7,
          which is itself below every game object.  Nothing can be swallowed.
        * **False positives** (§4.2, the mode dimming cannot fix).  Impossible
          here: this game's vocabulary is a 15x5 page, a 24x3 bar and a 4x4
          worker, and none of them is a 1 px full-height line.
        * **Shape dissolution** (§4.3).  Impossible: the rules are additive and
          static, not an aperture cut into a structural element.

        NINE RULES, NEVER TEN, and never a count that depends on the run: a
        scene that can grow with the score is the one thing `badge-games.md`
        §10 says a scene may not be.  The outer two boundaries are the panel
        edges and are deliberately unruled, so the file has no frame.
        """
        self.screen.pen = self.rule
        for col in range(1, M.BRICK_COLS):
            self.screen.rectangle(
                col * M.BRICK_W - 1, self.Y_OFFSET, 1, self.COURT_H
            )

    def _passes(self, state):
        """The passes this run has left, as pips in the floor margin."""
        self.screen.pen = self.white
        for index in range(max(0, state["passes"])):
            self.screen.rectangle(
                self.PIP_X + index * (self.PIP + self.PIP_GAP),
                self.Y_OFFSET + self.PIP_Y,
                self.PIP,
                self.PIP,
            )

    def _court(self, state):
        """Background, court, heap, scan, worker and the remaining passes."""
        self.screen.pen = self.dark
        self.screen.clear()
        self.screen.pen = self.panel
        self.screen.rectangle(0, self.Y_OFFSET, self.COURT_W, self.COURT_H)
        if self.ruled:
            self._rules()
        self.screen.font = self.font.sins
        self._pile(self._heap(state))
        # The rule the scan rides.  Drawn before the bar so the bar sits ON it,
        # and one pixel down from the bar's top edge so it reads as a track
        # under the scan rather than as an underline of it.
        self.screen.pen = self.rule
        self.screen.rectangle(
            0, self.Y_OFFSET + M.SCAN_Y + 1, self.COURT_W, 1
        )
        self.screen.pen = self.accent
        self.screen.rectangle(
            state["scan"] // M.UNIT,
            self.Y_OFFSET + M.SCAN_Y,
            M.SCAN_W,
            M.SCAN_H,
        )
        # The worker is yellow while it is riding the scan and white the
        # moment it is released.  A state, continuously indicated — not a flash
        # on a timer — so a player glancing down mid-launch can tell that the
        # worker has not left yet without counting frames.
        self.screen.pen = self.yellow if state["launch"] else self.white
        self.screen.rectangle(
            state["ball"][0] // M.UNIT,
            self.Y_OFFSET + state["ball"][1] // M.UNIT,
            M.BALL,
            M.BALL,
        )
        self._passes(state)

    def play(self, state, high_score, hint="B  PAUSE", hint_pen=None, best=False):
        self._court(state)
        score_text = "PAGES {:03d}".format(state["score"])
        self.screen.pen = self.white
        self.screen.text(score_text, 2, 2)
        score_width, _height = self.screen.measure_text(score_text)
        if best:
            # The stored number stopped being a target the moment it was
            # passed, and PAGES already carries the live score, so the slot
            # carries the state instead of repeating a figure.
            right_text = "BEST"
            right_pen = self.yellow
        else:
            right_text = "HI {:03d}".format(high_score)
            right_pen = self.grey
        right_width, _height = self.screen.measure_text(right_text)
        self.screen.pen = right_pen
        self._right(right_text, 2)
        # The status strip already existed, so labelling B here costs no court
        # and is drawn for the life of the screen rather than on a timer.
        self.screen.pen = self.grey if hint_pen is None else hint_pen
        self._center_between(hint, 2 + score_width, 160 - right_width - 3, 2)

    def paused(self, state, high_score, best=False, confirm=False):
        """The frozen court, dimmed, under a card carrying the way out.

        The court is drawn first and stays visible through the card, so pausing
        visibly did not destroy the run.  The status strip does not move: only
        its middle word changes, so the eye does not have to re-find PAGES
        or HI.

        ``confirm`` is the belt to the brace, and this game needs it more than
        Pong did.  A is the destructive key here, and A IS ALSO THE SCAN'S
        LEFT during the run the player just paused — the most recently pressed
        key on the badge, quite possibly still down.  The first A does not
        quit; it turns the map line into the question and the A label red, and
        only the second A ends the run.  Row positions do not move between the
        two states, so answering the question is not a moving target.
        """
        self.play(state, high_score, "PAUSED", self.yellow, best)
        self.screen.pen = self.pause_scrim
        self.screen.rectangle(0, self.Y_OFFSET, self.COURT_W, self.COURT_H)
        self.screen.pen = self.pause_card
        self.screen.rectangle(12, 26, 136, 88)
        # The label slot is always drawn, so the layout never jumps.
        self.screen.pen = self.yellow if best else self.grey
        self._center("NEW HIGH" if best else "HIGH", 30)
        self.screen.pen = self.yellow if best else self.accent
        self._center("{:03d}".format(state["score"] if best else high_score), 42, 2)
        self.screen.pen = self.grey
        # Both facts on one row: the run's speed and what it has left.
        self._center(
            "LEVEL {}  PASSES {}".format(state["level"], max(0, state["passes"])),
            60,
        )
        if confirm:
            self.screen.pen = self.yellow
            self._center("QUIT THIS RUN?", 72)
        else:
            self.screen.pen = self.grey
            self._center("A/C  SCAN", 72)
        self.screen.pen = self.white
        self._center("B   RESUME", 86)
        self.screen.pen = self.red if confirm else self.grey
        self._center("A   QUIT NOW" if confirm else "A   QUIT", 100)

    def _fatal_marker(self, fatal):
        """Mark the floor where the worker got past.

        Drawn AFTER the scrim, never under it — Snake paid for that lesson: a
        195-alpha black multiplies this red down to a near-black maroon, and
        the one thing the screen exists to answer becomes the one thing on it
        that cannot be read.

        A stub on the floor rather than a ring around the worker, because by
        the time the run ends the worker is off the court entirely and there is
        nothing left to ring.

        IT IS THE ONLY OPAQUE THING ABOVE THE SCRIM AND IT MUST STAY OFF EVERY
        TEXT ROW.  `font.sins` occupies a 12 px line box at scale 1, not 8 --
        measured through `screen.measure_text` in the pinned runtime on
        2026-08-21 -- so the last row, `A  MENU` at y 103, really covers y
        103-114, and this stub's three rows are 117-119.  Three pixels of
        clearance, and the reason to write the number down is that Flappy shipped
        the same idea as a FILLED 12 px cell at an arbitrary height and it ate
        twelve columns out of whichever sentence the run died on: `GREY` is 126.7
        in Rec. 601 luma against `RED`'s 117.3, a ratio of 1.08, so the row did
        not dim, it vanished.  A fixed stub on the floor cannot do that, and
        `test_the_floor_marker_stays_clear_of_every_text_row` proves it rather
        than trusting this paragraph.
        """
        self.screen.pen = self.red
        self.screen.rectangle(
            fatal // M.UNIT, self.Y_OFFSET + self.COURT_H - 3, M.BALL, 3
        )

    def finished(self, state, high_score, best=False):
        """The heap the run ended on, held under the result.

        This is a render state, not a phase: B and A are live from the first
        frame and nothing is gated on a timer, so an impatient player at a
        booth is never made to wait.
        """
        self._court(state)
        self.screen.pen = self.finish_scrim
        self.screen.rectangle(0, 0, 160, 120)
        won = state["status"] == "compacted"
        fatal = state.get("fatal")
        # Only on a loss.  A run that dropped a worker early and then compacted
        # the table anyway still carries that `fatal`, and marking it under a
        # win would answer a question nobody asked.
        if fatal is not None and not won:
            self._fatal_marker(fatal)
        if won:
            # THE WIN KEEPS ITS OWN HEADLINE and is deliberately untouched by
            # the error block below: `TABLE COMPACTED` is the success message
            # and a SQLSTATE is not.  Postgres has no error code for a VACUUM
            # that worked.
            self.screen.pen = self.accent
            # 58/108 px at scale 2 against the 160 px canvas.
            self._center("TABLE", 18, 2)
            self._center("COMPACTED", 43, 2)
            self.screen.pen = self.yellow if best else self.white
            # 101 px at its widest.  The level is NOT on this line: it does not
            # price the score, so `PAGES 090` means the same thing at level 1
            # and level 9 and a tag here would imply otherwise.
            self._center(
                "PAGES {:03d}  HIGH {:03d}".format(state["score"], high_score), 72
            )
            self.screen.pen = self.accent
            self._center("B  RECONNECT", 90)
            # A badge that finished in a pocket must not sit lit on a result
            # screen all day with a restart as its only offer.
            self.screen.pen = self.grey
            self._center("A  MENU", 104)
            return
        # THE LOSS IS A POSTGRES ERROR BLOCK, and this is the screen a developer
        # photographs.  `FATAL` at scale 2 rather than `VACUUM` / `ABORTED`: it
        # is the severity prefix psql really prints, it is 29 px at scale 1 so
        # it fits on ONE line where the old headline needed two, and the row it
        # frees is what pays for the DETAIL and HINT rows below.  The headline
        # is the same three words however the run ended, so the screen has one
        # identity and the variation sits on the rows Postgres itself uses —
        # `docs/badge-games.md` §10 records that finding from Flappy's pilot,
        # along with the reason the block is lowercase: Postgres does not shout,
        # and a transcript is what gets photographed.
        self.screen.pen = self.red
        self._center("FATAL", 3, 2)
        self._center(self.sqlstate_line(), 27)
        self.screen.pen = self.grey
        self._center(self.detail_line(state), 41)
        self._center(self.HINT, 55)
        self.screen.pen = self.yellow if best else self.white
        self._center(
            "PAGES {:03d}  HIGH {:03d}".format(state["score"], high_score), 71
        )
        self.screen.pen = self.accent
        self._center("B  RECONNECT", 87)
        self.screen.pen = self.grey
        self._center("A  MENU", 103)
