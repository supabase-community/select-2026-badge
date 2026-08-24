"""LORES REPLICA.SQL renderer using injected Badgeware APIs.

Draws and nothing else.  It reads the model's state the way it reads the score
— as data — and never computes a game rule, so the whole file can be exercised
against a recording screen with no runtime at all.

Everything here is rectangles and text.  There is no sprite sheet, no asset
pack and no PNG decode on the load path: the one asset this app installs is its
24x24 launcher icon, which the launcher draws and this file never opens.
"""

import pong_model as M

# The five games' one palette (`shared/game_palette.py`, vendored here by
# `scripts/sync_ui.py`).  Every pen below that is not part of THIS game's own
# argument comes from it, so the ten pens the five views used to duplicate can
# be changed in one place.  Tuples only -- a pen can only be minted through the
# injected `color` API, which the palette has no access to and should not.
import game_palette as P


# The Supabase green, to within a unit.  Used for the PRIMARY's own paddle,
# because the primary is the thing the player IS.
ACCENT = P.BRAND

# THE COURT'S OWN MATERIAL, and the one ink in this file that is not in the
# palette.  `game_palette` deliberately owns the pens the five games SHARE; the
# net has always been Pong's own (see `self.net`), and these two rules are the
# same kind of thing -- a court texture no other game has a use for, sitting in
# the 6-unit gap between `P.PANEL` and the net.  `docs/design/game-art.md` §3
# specifies (17, 38, 45) and `test_pong_app` pins the resulting contrast ORDER
# rather than the hex, so the three inks cannot be reshuffled by accident:
#
#     panel (24.8) < rule (33.9) < net (52.0)      Rec. 601 luma
#
# The court is the dimmest thing, the log the record travels along is next, and
# the wire the record travels ON is the brightest of the three -- and all three
# stay far below the 4 px segment, which is the element the player is aiming at.
RULE = (17, 38, 45)
# The dashed centre line, module-scope so a test can order it against the two
# inks either side of it.  Dim enough to read as a guide rather than an
# obstacle: the segment crosses it constantly and it must never be mistaken for
# something the segment can hit.
NET = (30, 58, 66)


class PongView:
    # The status strip is 16 px, exactly Snake's, so the court below it is the
    # same 104 px and the two games' playfields are the same size.
    Y_OFFSET = 16
    COURT_W = M.COURT_W
    COURT_H = M.COURT_H

    # The dashed centre line: the replication link the segment travels along.
    NET_X = 79
    NET_W = 2
    NET_DASH = 4
    NET_GAP = 4

    # ---- the court is the log (`docs/design/game-art.md` §3) ---------------
    #
    # Six 1 px rules, so the court reads as a ruled log rather than as a void.
    # STATIC, on purpose: `docs/design/game-scenes.md` §5.1 rendered five
    # animated candidates behind this game and rejected every one of them, and
    # §7.2's argument for static furniture is that it does not re-open the
    # ruling those renders settled.  20 px apart from y 28 so no rule lands on
    # the status strip's seam at y 16 or on the floor at y 119.
    RULE_YS = (28, 44, 60, 76, 92, 108)

    # Both bats are three stacked pages rather than one bar: primary and
    # replica are two stacks of the SAME pages, which is the database fact, and
    # it is said without a label.  `test_pong_app` pins the arithmetic --
    # 6 + 1 + 6 + 1 + 6 == `M.PADDLE_H` -- because a bat that is not exactly as
    # tall as the model's would draw a silhouette the physics does not use.
    BAT_BLOCK_H = 6
    BAT_BLOCKS = 3
    BAT_GAP = 1

    # The log the record has already written, ramping down behind it.  Widths
    # and heights only -- the ink is one pen, and the ramp is by COVERAGE.  See
    # `_segment` for why that is not the brightness ramp §3 asked for.
    TRAIL_STEPS = ((4, 2), (4, 1), (4, 1))
    # The record's header, on its leading edge.
    HEADER_W = 2

    def __init__(self, screen, image_api, color_api, font_api, vec2_api,
                 accent=ACCENT):
        self.screen = screen
        # KEPT AND UNUSED, DELIBERATELY.  This game is procedural and never
        # blits, so it needs neither the image loader nor vec2 — but this app is
        # the pilot for three more, and holding the seam open means a sibling
        # that DOES want a sprite copies a constructor that already has one
        # rather than rediscovering which globals Badgeware injects.
        self.image = image_api
        self.vec2 = vec2_api
        self.color = color_api
        self.font = font_api
        self.dark = color_api.rgb(*P.DARK)
        self.panel = color_api.rgb(*P.PANEL)
        self.net = color_api.rgb(*NET)
        # The log's rules, and the two inks the WAL record is drawn in.  MIST
        # is the ramp's top step, which `game_palette` describes as "a keyline,
        # or a mark's top step" -- a header on a record is exactly that.  DEEP
        # is "the same thing, subordinate", and the log a record has already
        # written is precisely that: this is DEEP's first use in the five games.
        self.rule = color_api.rgb(*RULE)
        self.header = color_api.rgb(*P.MIST)
        self.trail = color_api.rgb(*P.DEEP)
        self.white = color_api.rgb(*P.WHITE)
        self.grey = color_api.rgb(*P.GREY)
        self.red = color_api.rgb(*P.RED)
        self.yellow = color_api.rgb(*P.YELLOW)
        self.accent_tuple = accent
        self.accent = color_api.rgb(*accent)
        # Pause dims the court and lays a translucent card over it, so the
        # frozen run stays visible underneath and nothing feels destroyed.
        self.pause_scrim = color_api.rgb(*P.PAUSE_SCRIM)
        self.pause_card = color_api.rgb(*P.PAUSE_CARD)
        # Heavier than the pause scrim: the result has to dominate, and the
        # court behind it is an answer, not the subject.
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
        left slot is `ROWS 000` at 46 px; ours is `SYNCED 000` at 57 px, and a
        canvas-centred `B  PAUSE` starts at x = 59 — exactly where the score
        ends.  Zero gutter reads as one run-on word.  Centring in the REMAINING
        space instead puts 12 px either side of the hint, which is the same
        clearance the button rules ask of the softkey bar, and it is measured
        rather than nudged.
        """
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int(left + (right - left - width) // 2), y, scale)

    def high_line(self, high_score):
        return "HIGH {:03d}".format(high_score)

    # ---- screens ------------------------------------------------------------

    def intro(self, level, high_score):
        """The app root: one press to play, and every key named."""
        self.screen.pen = self.dark
        self.screen.clear()
        self.screen.font = self.font.sins
        self.screen.pen = self.accent
        # 126 px at scale 2 against the 160 px canvas.
        self._center("REPLICA.SQL", 10, 2)
        self.screen.pen = self.grey
        self._center(self.high_line(high_score), 40)
        self.screen.pen = self.white
        self._center("B  CONNECT", 58)
        # LEVEL IS SPEED AND THE SCREEN SAYS ONLY THAT.  Snake's equivalent row
        # reads `PAYS xn` because its level prices every row; ours does not, so
        # claiming a payout here would be a lie and naming the ladder anything
        # richer than it is would be worse.
        self.screen.pen = self.yellow if level >= 7 else self.grey
        self._center("A/C LEVEL {}".format(level), 76)
        self.screen.pen = self.grey
        # ONE VERB, because only one pair of keys does anything in play.  A and
        # C are inert during a rally and are therefore not named as if they
        # steered something.
        self._center("UP DN  PADDLE", 92)
        # HOME is silicon and cannot be rebound, so naming it is the only honest
        # way to offer a labelled route to the launcher.
        self._center("HOME  EXIT", 106)

    def _net(self):
        y = self.Y_OFFSET
        end = self.Y_OFFSET + self.COURT_H
        self.screen.pen = self.net
        while y < end:
            self.screen.rectangle(
                self.NET_X, y, self.NET_W, min(self.NET_DASH, end - y)
            )
            y += self.NET_DASH + self.NET_GAP

    def _rules(self):
        """The log the record travels along: six dim 1 px rules.

        Drawn UNDER the net and over the panel, so the court reads as ruled
        paper rather than as a void, and nothing here can be mistaken for
        something the segment can hit -- the whole width is one pixel tall and
        the ink is 8 units above the panel it sits on.
        """
        self.screen.pen = self.rule
        for y in self.RULE_YS:
            self.screen.rectangle(0, y, self.COURT_W, 1)

    def _bat(self, x, top, pen):
        """A bat as three stacked pages with 1 px seams between them.

        6 + 1 + 6 + 1 + 6 is exactly the `M.PADDLE_H` the model simulates, so
        the silhouette the player aims at is the rectangle the physics uses.
        The seams are the only part of the bat that is not solid, and they are
        1 px, so a segment arriving at a seam is still returned -- the model
        never sees them.
        """
        self.screen.pen = pen
        for index in range(self.BAT_BLOCKS):
            self.screen.rectangle(
                x,
                top + index * (self.BAT_BLOCK_H + self.BAT_GAP),
                M.PADDLE_W,
                self.BAT_BLOCK_H,
            )

    def _segment(self, state):
        """The segment, drawn as what it currently IS.

        `docs/design/game-art.md` §3: replication is not symmetric, so the two
        directions must not look like the same object going two ways.

        * Waiting to ship -- YELLOW, the palette's "armed state", and this is
          the one reading on this screen that predates the art pass and is
          tested.  A player glancing down mid-serve can tell the segment has
          not left yet without counting frames.
        * SHIPPING (travelling right, primary to replica) -- the brand green
          body with a bright MIST header on its leading edge, dragging three
          steps of the log it has already written.  This is a WAL record.
        * RETURNING (travelling left) -- a plain white square.  An
          acknowledgement is not data, so it has no header and, above all, it
          writes NOTHING, which is why it has no trail.

        TWO DEVIATIONS FROM §3, both recorded rather than silent:

        1. **§3 draws the ACK leg in `yellow`; this draws it white.**  §3 was
           written before `game_palette.py` existed and could not know that
           YELLOW would be pinned to one meaning per game.  In THIS game yellow
           already means "the segment has not left yet" -- argued in the source
           since the day it shipped and asserted by `test_pong_app` -- so a
           yellow return leg would make one 4 px square say two different
           things.  White is the leg's shipped colour, it is nowhere near the
           green family the WAL leg now owns, and the asymmetry §3 exists to
           show is carried by the header and the trail, not by the hue.
        2. **§3 ramps the trail's BRIGHTNESS; this ramps its COVERAGE.**  The
           palette has exactly one green below BRAND -- DEEP -- and
           `game_palette` records that BRAND and DEEP are 7.7% apart in luma
           and unusable as two objects at 3 px.  A three-step brightness ramp
           is therefore not available without a new pen, and `game-art.md` §12
           established that on this panel COVERAGE and not brightness is what
           sets a mark's floor.  So the trail is one pen at 4x2, 4x1, 4x1: it
           fades by getting thinner, which is the same visual result reached
           with an ink the repository already owns.
        """
        x = state["ball"][0] // M.UNIT
        y = self.Y_OFFSET + state["ball"][1] // M.UNIT
        if state["serve"]:
            self.screen.pen = self.yellow
            self.screen.rectangle(x, y, M.BALL, M.BALL)
            return
        if state["vel"][0] < 0:
            self.screen.pen = self.white
            self.screen.rectangle(x, y, M.BALL, M.BALL)
            return
        # The log, first, so the record is drawn over its own tail.  Clipped at
        # the left goal line rather than handed a negative x: the segment can
        # sit within 12 px of it while still shipping, and a rectangle at a
        # negative coordinate is the class of argument this project does not
        # hand an untested rasteriser on the morning of a demo.
        self.screen.pen = self.trail
        for index, (width, height) in enumerate(self.TRAIL_STEPS):
            left = x - width * (index + 1)
            if left < 0:
                width += left
                left = 0
            if width <= 0:
                break
            self.screen.rectangle(
                left, y + (M.BALL - height) // 2, width, height
            )
        self.screen.pen = self.accent
        self.screen.rectangle(x, y, M.BALL, M.BALL)
        self.screen.pen = self.header
        self.screen.rectangle(
            x + M.BALL - self.HEADER_W, y, self.HEADER_W, M.BALL
        )

    def _court(self, state):
        """The court as a ruled log: rules, net, both bats and the segment.

        `docs/design/game-art.md` §3, "the court is the log".  Everything here
        is still a rectangle and everything is still static except the segment
        itself, so nothing in this method re-opens a settled question.
        """
        self.screen.pen = self.dark
        self.screen.clear()
        self.screen.pen = self.panel
        self.screen.rectangle(0, self.Y_OFFSET, self.COURT_W, self.COURT_H)
        self._rules()
        self.screen.font = self.font.sins
        self._net()
        # THE PADDLES ARE COLOUR-CODED BY WHO OWNS THEM, not by side.  The
        # player's is the badge's own accent because it is the thing the player
        # is; the replica's is the same grey every other app uses for a control
        # nobody is touching.
        #
        # A GREEN REPLICA WAS TRIED AND IT LOST, 2026-08-21, and the record is
        # here because the argument for it is good enough that somebody will
        # think of it again.  The model calls these two the PRIMARY and the
        # REPLICA, both of them are Postgres, and grey says "inert chrome" about
        # one of them -- which is exactly the "named in the model, drawn as
        # something else" failure `docs/badge-games.md` §7 warns about.  So the
        # replica was painted `P.DEEP`, the Select ramp's step below the
        # primary's own BRAND, and rendered.
        #
        # It is not legible.  BRAND and DEEP are 7.7% apart in Rec. 601 luma
        # (156,235 against 144,185) and share a hue, so at 3 px wide the two bats
        # read as one colour; grey is 19% below BRAND *and* differs in hue, which
        # is the stronger cue of the two.  Telling the bats apart is a
        # REQUIREMENT here and the theme is a preference, so the requirement
        # wins.  A four-step green ramp cannot separate two objects at its own
        # bottom end -- that is a fact about the ramp, not about this game.
        #
        # `_segment` DOES use DEEP, and that is not a contradiction: there the
        # two greens are one object and its own tail, where 7.7% apart is the
        # right distance.  The finding is about telling two DIFFERENT things
        # apart, not about shading one.
        self._bat(
            M.PADDLE_X, self.Y_OFFSET + state["paddle"] // M.UNIT, self.accent
        )
        self._bat(
            self.COURT_W - M.PADDLE_X - M.PADDLE_W,
            self.Y_OFFSET + state["replica"] // M.UNIT,
            self.grey,
        )
        self._segment(state)

    def play(self, state, high_score, hint="B  PAUSE", hint_pen=None, best=False):
        self._court(state)
        score_text = "SYNCED {:03d}".format(state["score"])
        self.screen.pen = self.white
        self.screen.text(score_text, 2, 2)
        score_width, _height = self.screen.measure_text(score_text)
        if best:
            # The stored number stopped being a target the moment it was
            # passed, and SYNCED already carries the live score, so the slot
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
        its middle word changes, so the eye does not have to re-find SYNCED
        or HI.

        ``confirm`` is the belt to the brace.  A is the destructive key here,
        and while A does nothing during a rally it IS the key that steps the
        level down one screen earlier.  The first A does not quit; it turns the
        map line into the question and the A label red, and only the second A
        ends the run.  Row positions do not move between the two states, so
        answering the question is not a moving target.
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
        self._center("LEVEL {}".format(state["level"]), 60)
        if confirm:
            self.screen.pen = self.yellow
            self._center("QUIT THIS RUN?", 72)
        else:
            self.screen.pen = self.grey
            self._center("UP DN  PADDLE", 72)
        self.screen.pen = self.white
        self._center("B   RESUME", 86)
        self.screen.pen = self.red if confirm else self.grey
        self._center("A   QUIT NOW" if confirm else "A   QUIT", 100)

    def _fatal_marker(self, fatal):
        """Mark the goal line where the segment got past.

        Drawn AFTER the scrim, never under it — Snake paid for that lesson: a
        195-alpha black multiplies this red down to a near-black maroon, and the
        one thing the screen exists to answer becomes the one thing on it that
        cannot be read.

        A 3 px stub on the goal line rather than a ring around the ball,
        because by the time the run ends the segment is off the court entirely
        and there is nothing left to ring.  It sits at x 0-2, and the widest
        row on this screen is the 142 px `DETAIL` line at x 9-151, so a filled
        block deletes no letter here at any score.
        """
        self.screen.pen = self.red
        self.screen.rectangle(
            0, self.Y_OFFSET + fatal // M.UNIT, 3, M.BALL
        )

    def sqlstate_line(self):
        """The real Postgres error for what just happened, code and all.

        `docs/badge-games.md` §7 calls this the cheapest theming on the badge
        and it is right: it costs strings, no asset, no licence and no frame
        budget, and it is the screen a developer photographs.

        `57014 query_canceled` IS THE APPROVED CODE FOR THIS GAME.  It is the
        one on `docs/design/mockups/sheet-deaths.png`, which the owner looked at
        and approved, and on `21-death-pong-57014.png` beside it.  Two things a
        later reader will otherwise get wrong:

        * **It is not `40P01`.**  `40P01 deadlock_detected` is CURSOR.SQL's, for
          the DEADLOCK chaser (`23-death-pacman-40P01.png`).  Nothing in this
          game deadlocks, and putting Pac-Man's code here would be a joke about
          a mechanic REPLICA.SQL does not have.
        * **No document ASSIGNS Pong a SQLSTATE**, and
          `docs/design/mockups/README.md` says so out loud: `game-art.md` §13
          maps 57014 to Pac-Man's TIMEOUT chaser and the mock-up author borrowed
          it.  It survives because a replica that stops acknowledging really
          does leave the primary waiting on a reply that is then given up on --
          which is what `query_canceled` means -- and because it is the string
          the owner approved.  It is a borrowed code, not a derived one, and
          that is worth knowing before anyone "corrects" it.
        """
        return "57014 query_canceled"

    def detail_line(self, state):
        """`DETAIL` names the record that never came back.

        The score is the number of segments SYNCED, so the one in flight when
        the run ended is the next one.  142 px, the widest row on the screen.
        """
        return "DETAIL  record {:03d} unacked".format(state["score"] + 1)

    def hint_line(self):
        """`HINT` says what to look at, which is the row psql uses it for.

        A constant rather than a lookup: unlike Flappy, this game has exactly
        one way to die -- the segment got past the primary -- so a per-cause
        table here would be one branch with one arm.
        """
        return "HINT  no ack from replica"

    def finished(self, state, high_score, best=False):
        """The court that ended the run, held under the result.

        This is a render state, not a phase: B and A are live from the first
        frame and nothing is gated on a timer, so an impatient player at a booth
        is never made to wait.

        THE HEADLINE IS `FATAL` AND NOT `REPLICATION BROKEN`, which is a change
        and not a simplification.  Flappy already shipped this block --
        `FATAL` at scale 2, the SQLSTATE, a `DETAIL` row and a `HINT` row -- and
        the owner approved the five-game sheet drawn in that one idiom
        (`docs/design/mockups/sheet-deaths.png`).  Three things pay for it:
        `FATAL` is the severity prefix psql really prints; it is 58 px at
        scale 2 where `REPLICATION` + `BROKEN` needed two lines and 126 px; and
        the line that frees is exactly what the `DETAIL` and `HINT` rows cost.
        The event is still called REPLICATION BROKEN everywhere it is a
        mechanic -- the model, the README and the serial log -- because that is
        what it is.  This screen reports it the way Postgres would.

        Row positions are Flappy's, to the pixel, so the five games' death
        screens are one screen with five payloads rather than five layouts.
        """
        self._court(state)
        self.screen.pen = self.finish_scrim
        self.screen.rectangle(0, 0, 160, 120)
        fatal = state.get("fatal")
        if fatal is not None:
            # After the scrim, never under it.  A 195-alpha black multiplies
            # this red down to a near-black maroon.
            self._fatal_marker(fatal)
        self.screen.pen = self.red
        # 58 px at scale 2, and 116 px, against the 160 px canvas.
        self._center("FATAL", 3, 2)
        self._center(self.sqlstate_line(), 27)
        self.screen.pen = self.grey
        # 142 px and 133 px: the two widest rows this app draws.
        self._center(self.detail_line(state), 41)
        self._center(self.hint_line(), 55)
        self.screen.pen = self.yellow if best else self.white
        # 106 px.  The level is NOT on this line: it does not price the score,
        # so `SYNCED 040` means the same thing at level 1 and level 9 and a
        # tag here would imply otherwise.
        self._center(
            "SYNCED {:03d}  HIGH {:03d}".format(state["score"], high_score), 71
        )
        self.screen.pen = self.accent
        self._center("B  RECONNECT", 87)
        # A badge that lost the stream in a pocket must not sit lit on a death
        # screen all day with a restart as its only offer.
        self.screen.pen = self.grey
        self._center("A  MENU", 103)
