"""LORES POOLER.SQL renderer using injected Badgeware APIs.

Draws and nothing else.  It reads the model's state the way it reads the score
— as data — and never computes a game rule, so the whole file can be exercised
against a recording screen with no runtime at all.

Everything here is rectangles and text EXCEPT THE CLIENT, which is the Supabase
mark: one 336-byte P8 sheet, decoded once at construction, blitted once a frame.
This file used to say "there is no sprite sheet, no asset pack and no PNG decode
on the load path" and held the `image`/`vec2` seam open anyway, in as many words,
for exactly this.  The owner closed it: *"i think the flappy bird bird should be
the supabase logo or something."*  `flappy/PROVENANCE.md` has the licence trail
and `docs/design/game-art.md` §12 has the measurement that says it survives at
this size -- 41% ink coverage at 8 px, against the Postgres elephant's 5%.

THERE IS NOW SCENERY, AND THE OLD COLOUR RULE IS REPLACED BY AN ORDERING.  This
file used to say "there is no scenery", and that was the honest description of a
game that flew through flat panel.  The owner asked the obvious question —
"is there a background scene or anything? I think the original flappy has a
small backdrop with a paralax effect" — so there is a room now, and the rule
that keeps it playable is a CONTRAST ORDER rather than an absence:

    room  <  pipe shaft  <  occupied slot  <  collar  <  client

Everything in the room is dimmer than a pipe, so no part of the backdrop can be
mistaken for the structure the player has to fly between; the collar stays the
brightest thing on a pipe because it is both the edge he aims at and the edge
that kills him; and the client is the badge's own green because it is the thing
the player IS.  The order is stated once, as arithmetic, in `flappy_scene` and
asserted by `flappy/tests/test_flappy_scene.py` — so a later contributor cannot
brighten a rack past a pipe by eye.
"""

import flappy_model as M
import flappy_scene as S

# The five games' one palette (`shared/game_palette.py`, vendored here by
# `scripts/sync_ui.py`).  Every pen below that is not part of THIS game's own
# argument comes from it, so the ten pens the five views used to duplicate can
# be changed in one place.  Tuples only -- a pen can only be minted through the
# injected `color` API, which the palette has no access to and should not.
import game_palette as P


# The Supabase green, to within a unit.
ACCENT = P.BRAND


class FlappyView:
    # The status strip is 16 px, exactly Snake's and Pong's, so all three
    # games put their world in the same place on the panel.
    Y_OFFSET = 16
    WORLD_W = M.WORLD_W
    WORLD_H = M.WORLD_H

    # The collar at the mouth of each pipe: 3 px deep and 1 px proud either
    # side.  It is the original's silhouette, and it is also the only part of a
    # pipe a player actually aims at, so it is drawn in the brighter teal.
    COLLAR_H = 3
    COLLAR_OUT = 1
    # The floor's moving dashes: 6 px of light every 12 px of rail.  The rails
    # are the only surface that can carry motion without intruding on the band
    # the client flies in, and they are drawn ON the lethal y rather than
    # inset from it.
    DASH = 6
    DASH_PITCH = 12

    # The prompt rule: 1 px of pool colour on the strip's last row, so the
    # status strip reads as a command line and the world below it as the
    # output.  `docs/design/snake-art.md` §4.3 calls this the cheapest
    # high-value pixel in the art pass and it is one rectangle.  It is the POOL
    # teal rather than the accent green: the accent belongs to the client, and
    # a full-width accent rule would put the brightest ink on the panel
    # somewhere the player is not looking.
    RULE_Y = 15

    # ---- the client, which is the mark ------------------------------------
    #
    # THE SHEET'S EIGHT FRAMES ARE A VALUE RAMP, NOT A SHAPE RAMP, and that is
    # what makes four of them the right four.  `snake/host/generate_food.py`
    # measured that the mark's usable geometric range at this size is only
    # 0.93..1.00 -- scaling it for animation collapses eight phases into three
    # masks and loses the top tip -- so the life in the sheet is brightness
    # instead: frames 0-3 and 7 sit at the brand green, 4 and 6 step up to the
    # palette's PALE and 5 is its MIST peak.
    #
    # So the four frames this game needs are the four brightnesses of a
    # connection between a keepalive that has just landed and one the idle timer
    # is about to reclaim -- and they are indexed by the SAME
    # `flappy_scene.cable_ink_index` the cable's four pens are, so the client
    # and the connection it is holding brighten and dim together off one value.
    # That is the whole of `docs/design/game-art.md` §5's "brightens on every
    # keepalive and fades as the idle timer closes in", for no model change and
    # no new state.
    CLIENT_FRAMES = (5, 4, 0, 0)
    # Ink row 0 is the bare brand ramp; row 1 is the same ramp with a dark
    # keyline.  ROW 0, and this was decided by rendering BOTH through the real
    # runtime over the real room and looking at them at 18x.
    #
    # The keyline costs the mark nothing -- it is drawn in the transparent border
    # OUTSIDE the silhouette, so both rows light the same 60 green pixels and row
    # 1 simply adds 40 dark ones around them.  It buys nothing either, and that
    # is the reason: the keyline's ink is (5, 12, 18), the playfield panel is
    # (11, 28, 34), and at 0.375 mm a pixel those are the same colour.  It could
    # only separate the client from something BRIGHTER than itself, and by the
    # contrast order at the top of this file there is nothing brighter than the
    # client anywhere in the world it flies through.
    #
    # The one screen where it would have paid was the death card, back when the
    # mark sat on a red field -- and there the field was the point and a keyline
    # between the two would have softened the only reading that screen has to
    # deliver.  The field is gone (see the geometry block below), so the death
    # card is now the DIMMEST place the mark is drawn rather than the
    # brightest, and row 0 is right there for the same reason it is right
    # everywhere else: nothing near it is brighter than it is.
    #
    # Snake reaches for row 1 for a reason this game does not have: its body is
    # drawn in the profile accent, so a brand-green mark can land inside a
    # brand-green snake.  The client has no body to disappear into.
    CLIENT_ROW = 0

    # ---- the death card's own geometry, and why it carries NO marker --------
    #
    # `font.sins` LINE BOX IS 12 PX AT SCALE 1 AND 24 AT SCALE 2, measured
    # through `screen.measure_text` in the pinned runtime rather than assumed.
    # That number is why this card has no death marker at all.  The error
    # block's EIGHT rows occupy line boxes 3..26, 27..38, 41..52, 55..66,
    # 67..78, 79..90, 91..102 and 103..114, so the largest gutter anywhere on
    # the card is TWO pixels — and the client's cell is TWELVE.  There is no
    # lane for it.
    #
    # IT WAS SEVEN ROWS AND A FIVE-PIXEL GUTTER until the save-failure row
    # landed (see `FOOTER_WARNING`).  The footer tightened to make room and the
    # bottom row did NOT move: the card still ends at 114, which is what the
    # rejected-relocation arithmetic below and Breakout's floor stub both
    # measure their clearance against.
    #
    # The client's drawn cell can also be at any of those heights.  It spans
    # rows `Y_OFFSET + CEILING - CLIENT_INSET` .. `Y_OFFSET + FLOOR - CLIENT +
    # CLIENT_INSET + CLIENT_CELL`, which is 16..119 — the whole card below the
    # strip.  So "move one of them clear of the other" was never available in
    # either direction.
    #
    # THE KEYLINE WAS THE PREVIOUS ANSWER AND IT WAS STILL WRONG.  A 1 px red
    # box on the client's footprint paints no glyph body, so the test that
    # walked every death height passed — but the marker is RED and the SQLSTATE
    # row is RED, a contrast ratio of 1.0, so the keyline crossing `53300`
    # deleted the digits it drew between.  The owner found it on hardware on
    # 2026-08-22 and the ruling is the bar: no marker ink of any kind, filled or
    # keyline or single pixel, may share a text row's line box.  "Thin" is not a
    # defence at ratio 1.0 and neither is "the text draws on top".
    #
    # OF THE THREE FIXES ON THE TABLE, ONLY THIS ONE IS FREE OF A NEW RISK, and
    # the frames that decided it are `12-death-*.png` in
    # `results/evidence/playground`:
    #
    # * **Under the scrim, pre-compensated** — rejected by arithmetic that no
    #   ink can beat.  `finish_scrim` is a 195-alpha black, and rendered in the
    #   pinned runtime this red comes back at RGB(13, 3, 5) beneath it.  PURE
    #   WHITE comes back at RGB(14, 14, 14).  There is nothing above white, so
    #   there is no ink whose post-scrim result is red; the ceiling is 14.
    # * **Relocated to an edge, Breakout-style** — Breakout's floor stub works
    #   because it need not encode a position.  This marker does, so the only
    #   relocation that keeps the height is a stub at x 0..2 — and
    #   `53300 too_many_connections` measures 149 px, so it starts at x 5.  Two
    #   pixels, 0.75 mm, between a red stub and red text, on the one screen this
    #   game is photographed for.  Not a margin worth having.
    # * **Dropped** — this file already argued it: the world is frozen exactly
    #   where it stopped, so the client is still standing on the thing that
    #   refused it.  Rendered, the client's cell reads RGB(35, 54, 43) under the
    #   scrim against the field's RGB(3, 7, 8) — luma 47.1 against 5.9, a ratio
    #   of 8.0 to 1.  The death height is still on the panel; only the box
    #   around it is gone, and four rectangles a death frame come back.
    LINE_H = 12
    # The `HINT` row's own y, named because it is the row a test pins clear and
    # the row a photograph is read for.
    HINT_Y = 55

    # ---- the post-mortem's footer, and why it is four rows in 67..114 -------
    #
    # 67 / 79 / 91 / 103 tiles four 12 px line boxes with ZERO gutter, and both
    # ends of that band are pinned by something outside this file.  The top
    # cannot rise: the `HINT` box ends at 66.  The bottom cannot fall: `A MENU`
    # ends at 114, and Breakout — which copies this footer to the pixel — puts
    # its floor marker at 117..119, the only opaque ink above its scrim.  Move
    # `A MENU` down and that stub lands inside a text row's line box, which is
    # exactly the RED-on-RED failure the owner photographed on 2026-08-22.
    #
    # Zero gutter is not tight for this font: the 12 px box carries the
    # leading, and Snake's shipped footer runs an ELEVEN px step (82 -> 93) on
    # hardware the owner has played.
    FOOTER_SCORE = 67
    # Reserved for the one line the badge only prints when it has bad news: a
    # record it could not store.  The row exists whether or not it is used,
    # because rows that move when a state appears make the state harder to read
    # than the state itself (Snake's rule, and this card's whole identity is
    # that its rows are a fixed table).
    FOOTER_WARNING = 79
    FOOTER_RECONNECT = 91
    FOOTER_MENU = 103

    def __init__(self, screen, image_api, color_api, font_api, vec2_api,
                 accent=ACCENT, backdrop=None, backdrop_dim=P.BACKDROP_DIM, room=True):
        self.screen = screen
        # THE SEAM THIS FILE HELD OPEN, NOW USED.  The comment that was here
        # said `image_api` and `vec2_api` were "KEPT AND UNUSED, DELIBERATELY...
        # holding the seam open means a sibling that DOES want a sprite copies a
        # constructor that already has one rather than rediscovering which
        # globals Badgeware injects."  That is exactly what happened, in this
        # file, and the seam cost nothing while it waited.  `pong_view` and
        # `breakout_view` still keep theirs unused for the same reason.
        self.image = image_api
        self.vec2 = vec2_api
        # Every dimension comes off the sheet's own height, the way
        # `snake_view` derives its food from `FOOD_CELL = height // 2`, so the
        # generator's `CELL` is the entire size control and no code here moves
        # when it does.  The MODEL still owns exactly `M.CLIENT` = 8 px and
        # collides on that; the 2 px of overhang per side is purely visual, and
        # it is what the coverage measurement bought -- at 8 px the mark is a
        # 26-pixel blob, at 12 px it is the mark.
        sheet = image_api.load("assets/client-p8.png")
        self.CLIENT_CELL = int(sheet.height) // 2
        self.CLIENT_INSET = (self.CLIENT_CELL - M.CLIENT) // 2
        grid = sheet.spritesheet(int(sheet.width) // self.CLIENT_CELL, 2)
        # Built once, indexed straight by `cable_ink_index`, so the draw path is
        # one list index and one blit and allocates nothing.
        self.client_sprites = tuple(
            grid.sprite(frame, self.CLIENT_ROW) for frame in self.CLIENT_FRAMES
        )
        self.color = color_api
        self.font = font_api
        self.dark = color_api.rgb(*P.DARK)
        self.panel = color_api.rgb(*P.PANEL)
        self.pipe = color_api.rgb(*S.PIPE_INK)
        self.collar = color_api.rgb(*S.COLLAR_INK)
        self.white = color_api.rgb(*P.WHITE)
        self.grey = color_api.rgb(*P.GREY)
        self.red = color_api.rgb(*P.RED)
        self.yellow = color_api.rgb(*P.YELLOW)
        self.accent_tuple = accent
        # KEPT AND STILL USED, though no longer for the client itself: the
        # accent is the intro's title rule and the finish card's headline, which
        # are the two places this app says its own name.
        self.accent = color_api.rgb(*accent)
        # Pause dims the world and lays a translucent card over it, so the
        # frozen run stays visible underneath and nothing feels destroyed.
        self.pause_scrim = color_api.rgb(*P.PAUSE_SCRIM)
        self.pause_card = color_api.rgb(*P.PAUSE_CARD)
        # Heavier than the pause scrim: the result has to dominate, and the
        # world behind it is an answer, not the subject.
        self.finish_scrim = color_api.rgb(*P.FINISH_SCRIM)

        # ---- the room -------------------------------------------------------
        #
        # Every pen below comes from `flappy_scene`, which is the only place the
        # inks are written down and the only place a test can check them.
        self.aisle = color_api.rgb(*S.AISLE_INK)
        self.sky = color_api.rgb(*S.SKY_INK)
        self.near = color_api.rgb(*S.NEAR_INK)
        self.rack_lit = color_api.rgb(*S.RACK_LIT_INK)
        self.tray = color_api.rgb(*S.TRAY_INK)
        self.wall = color_api.rgb(*S.WALL_INK)
        self.drift = color_api.rgb(*S.DRIFT_INK)
        self.slot = color_api.rgb(*S.SLOT_INK)
        self.slot_lit = color_api.rgb(*S.SLOT_LIT_INK)
        # Four pens, built once here rather than per frame, for the four
        # brightnesses the connection cable steps down through as the idle
        # timer closes in.  A tuple comprehension at construction time is not a
        # draw path; `_cable` indexes it and allocates nothing.
        self.cable_pens = tuple(color_api.rgb(*ink) for ink in S.CABLE_INK)
        self.room = room

        # ---- the glyph seam, held open and shipped OFF ----------------------
        #
        # Identical in shape to `SnakeView`'s, and shipped in the same state:
        # off.  `glyph/badge/glyph/glyph_backdrop.py` will blit any of eighteen
        # Supabase-branded animations into this app in two lines, and the seam
        # is here so the owner or a sibling game can A/B one without editing a
        # renderer.  POOLER.SQL does not use it, and `flappy/README.md` records
        # what it looked like when it was rendered and why the procedural room
        # won: a glyph deck gives MOTION but it cannot give PARALLAX, because
        # its clock is its own and knows nothing about how fast the world is
        # scrolling past the client.
        #
        # `room` and `backdrop` are independent on purpose, so all four
        # combinations can be captured by a host script and looked at.
        self.backdrop = backdrop
        self.backdrop_dim = backdrop_dim
        self.backdrop_scrim = color_api.rgb(0, 0, 0, backdrop_dim)
        self.backdrop_panel = color_api.rgb(*P.BACKDROP_PANEL)

    def set_backdrop(self, backdrop, dim=P.BACKDROP_DIM):
        """Swap the glyph backdrop at runtime, as `SnakeView.set_backdrop` does."""
        self.backdrop = backdrop
        self.backdrop_dim = dim
        self.backdrop_scrim = self.color.rgb(0, 0, 0, dim)

    def _draw_backdrop(self):
        self.backdrop.draw_to(self.screen)
        if self.backdrop_dim:
            self.screen.pen = self.backdrop_scrim
            self.screen.rectangle(0, 0, 160, 120)
        # THE STRIP KEEPS ITS DARK FIELD, and `SnakeView` does not do this.  A
        # `GlyphBackdrop` surface is the whole 160x120 panel, so without this the
        # animation runs BEHIND `SERVED 027` and `HI 042` — the one part of the
        # screen every one of the five games keeps flat on purpose.  Rendering
        # `ring-buffer` through this seam is what found it: the strip filled with
        # drifting arrow glyphs and the score became the hardest thing to read on
        # the panel.  One rectangle, and only when a backdrop is set at all.
        self.screen.pen = self.dark
        self.screen.rectangle(0, 0, 160, self.Y_OFFSET)

    def _clear(self):
        """Lay down the field every screen starts from.

        Returns the pen the playfield panel should be filled with, which is
        opaque without a glyph backdrop and translucent with one.
        """
        if self.backdrop is None:
            self.screen.pen = self.dark
            self.screen.clear()
            return self.panel
        self._draw_backdrop()
        return self.backdrop_panel

    # ---- text helpers -------------------------------------------------------

    def _center(self, text, y, scale=1):
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int((160 - width) // 2), y, scale)

    def _right(self, text, y, scale=1, margin=3):
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int(160 - width - margin), y, scale)

    def _center_between(self, text, left, right, y, scale=1):
        """Centre a label in the gap two other labels have left it.

        THE STATUS STRIP CANNOT USE `_center` AND THIS IS THE REASON.  The left
        slot is `SERVED 000` at 57 px and the right is `HI 000` at 32 px, so a
        canvas-centred `A  PAUSE` (42 px) would start at x = 59 — exactly where
        the score ends.  Zero gutter reads as one run-on word.  Centring in the
        REMAINING space instead puts 12 px either side, which is the clearance
        the button rules ask of the softkey bar, and it is measured rather than
        nudged.
        """
        width, _height = self.screen.measure_text(text, scale)
        self.screen.text(text, int(left + (right - left - width) // 2), y, scale)

    def high_line(self, high_score):
        return "HIGH {:03d}".format(high_score)

    # SQLSTATE 53300 is `too_many_connections`, and it is the real Postgres
    # error for the thing that has just happened to this client: it asked the
    # pool for a slot and there was not one.  A class-level constant rather than
    # a literal in `finished`, so the string a photograph will carry is written
    # down once and a test can name it.
    SQLSTATE = "53300"
    CONDITION = "too_many_connections"

    # WHAT KILLED THE CLIENT, in the pool's own words, keyed on the `cause` the
    # model has stored since the day this app shipped.  A `HINT` row is what
    # Postgres itself uses to explain a FATAL, and it is the whole reason the
    # error block is worth three rows instead of one.
    HINTS = {
        "floor": "HINT  keepalive was overdue",
        "ceiling": "HINT  keepalive overshoot",
        "pipe": "HINT  that slot was in use",
    }
    # A run can only reach the finished screen by dying, so this is defensive
    # only — but a badge that renders `None` into a photograph is worse than one
    # that renders a true general statement.
    HINT_DEFAULT = "HINT  the pool closed it"

    def sqlstate_line(self):
        """The error the pool raised, exactly as Postgres spells it."""
        return "{} {}".format(self.SQLSTATE, self.CONDITION)

    def detail_line(self, state):
        """Which request was refused — a real fact about the run.

        The query that was refused is the one after the last one served, so this
        says WHICH pipe killed you and not merely that one did.  ``DETAIL`` is
        the row Postgres puts it on, so the block reads as a transcript rather
        than as a game over.
        """
        return "DETAIL  query {:03d} refused".format(state["score"] + 1)

    def hint_line(self, state):
        """The pooler's explanation, one row, keyed on what was touched."""
        return self.HINTS.get(state["cause"], self.HINT_DEFAULT)

    # ---- screens ------------------------------------------------------------

    def intro(self, level, high_score):
        """The app root: one press to play, and every key named.

        The room is drawn here too, at a standstill and WITHOUT its lit aisle:
        the intro's last two rows of grey text sit exactly where the near
        cabinets stand, and a lit band behind them would cost more legibility
        than the depth is worth.  What is left is a whisper — two silhouettes
        barely off the dark field, and the lit top edge of each near cabinet —
        so the app root looks like a place the game happens in rather than a
        title on a void, and every string on it still reads at 2.6 mm.
        """
        self._clear()
        self.screen.font = self.font.sins
        if self.room:
            self._intro_room()
        self.screen.pen = self.accent
        # 58 px at scale 1, so 116 px at scale 2 against the 160 px canvas.
        self._center("POOLER.SQL", 10, 2)
        self.screen.pen = self.grey
        self._center(self.high_line(high_score), 40)
        self.screen.pen = self.white
        self._center("B  CONNECT", 58)
        # LOAD, NOT LEVEL.  The ladder moves two dials at once — the pool
        # serves faster and has less room in it — and `LOAD` is the one word
        # that names both.  `LEVEL` would name the ladder without saying what
        # it does, and a player who has just read `LOAD 9` is not surprised
        # when the gaps tighten.
        self.screen.pen = self.yellow if level >= 7 else self.grey
        self._center("A/C LOAD {}".format(level), 76)
        # 80 px.  B and UP are one verb because they do one thing; naming them
        # separately would imply they differ.
        self.screen.pen = self.grey
        self._center("B UP  KEEPALIVE", 92)
        # HOME is silicon and cannot be rebound, so naming it is the only
        # honest way to offer a labelled route to the launcher.
        self._center("HOME  EXIT", 106)

    # ---- the room -----------------------------------------------------------

    def _rack_row(self, scrolled, divisor, period, racks, body, edge):
        """One repeating row of cabinets, at ``1 / divisor`` of the world's speed.

        Two passes over the same row rather than one, so the pen is written
        twice for the whole row instead of three times per cabinet.  Nothing in
        either pass allocates: the cabinet table is a tuple of tuples built at
        import and this walks it by index.
        """
        offset = S.parallax_offset(scrolled, divisor, period)
        floor = self.Y_OFFSET + M.FLOOR
        self.screen.pen = body
        base = -offset
        while base < self.WORLD_W:
            for rack in racks:
                x = base + rack[0]
                if x + rack[1] <= 0 or x >= self.WORLD_W:
                    continue
                self.screen.rectangle(x, floor - rack[2], rack[1], rack[2])
            base += period
        if edge is None:
            return
        # The lit top edge and one status light per cabinet.  Only the NEAR row
        # gets them: a cabinet you can read the lights on is a cabinet that is
        # close, and giving both rows lights flattens the two into one.
        self.screen.pen = edge
        base = -offset
        while base < self.WORLD_W:
            for rack in racks:
                x = base + rack[0]
                if x + rack[1] <= 0 or x >= self.WORLD_W:
                    continue
                # A DARK RACK GETS A DARK TOP EDGE, which is both the honest
                # picture and where the skyline's primitives came from.  This
                # used to light the top edge of every cabinet including the ones
                # whose `led_x` is -1 — a rack with its lights out, wearing a lit
                # edge.  Skipping those is one compare, it costs the row nothing
                # a viewer can name, and it is three primitives a frame.
                if rack[3] < 0:
                    continue
                top = floor - rack[2]
                self.screen.rectangle(x, top, rack[1], 1)
                # The light is 1 px wide and is placed relative to the cabinet,
                # so a cabinet straddling the right edge can put its light
                # entirely off the panel — visible only as a wasted primitive.
                # `test_flappy_scene` caught it; one compare closes it.
                led = x + rack[3]
                if 0 <= led < self.WORLD_W:
                    self.screen.rectangle(led, top + 4, 1, 2)
            base += period

    def _skyline(self, scrolled):
        """San Francisco, one step off the wall, at an eighth of the world's speed.

        The row this replaced was three uneven cabinets, and the owner read them
        as a city before anyone called them one — *"i do like flappy buffer with
        the city sky line but would be way better if it was san fransisco."*  So
        this is the same layer with the silhouette it was already being taken
        for, which is why it costs about what the cabinets did instead of what a
        third row would.  `flappy_scene.SKYLINE` carries the two buildings that
        make it San Francisco and the reason those two.

        The base band is ONE rectangle for every low building in the city, and it
        does not scroll: a uniform strip has no motion to lose, and it is the
        merge `docs/badge-games.md` §2 records from Snake's tube — the primitives
        it saves are what pay for the two landmarks.
        """
        floor = self.Y_OFFSET + M.FLOOR
        self.screen.pen = self.sky
        self.screen.rectangle(
            0, floor - S.SKY_BASE_H, self.WORLD_W, S.SKY_BASE_H
        )
        offset = S.parallax_offset(scrolled, S.FAR_DIV, S.SKY_PERIOD)
        base = -offset
        while base < self.WORLD_W:
            for shape in S.SKYLINE:
                x = base + shape[0]
                if x + shape[1] <= 0 or x >= self.WORLD_W:
                    continue
                self.screen.rectangle(
                    x, floor - shape[2] - shape[3], shape[1], shape[3]
                )
            base += S.SKY_PERIOD

    def _tray(self, scrolled):
        """The ceiling's cable tray: two rules and the hangers between them.

        The upper third of the world is otherwise flat wall, and two 1 px rules
        with hangers are the cheapest thing that says "indoors" rather than
        "sky".  At an eighth speed they are the slowest-moving thing on the
        panel, which is what puts them furthest away.
        """
        self.screen.pen = self.tray
        for y in S.TRAY_Y:
            self.screen.rectangle(0, self.Y_OFFSET + y, self.WORLD_W, 1)
        offset = S.parallax_offset(
            scrolled, S.FAR_DIV, S.TRAY_HANGER_PITCH
        )
        top = self.Y_OFFSET + S.TRAY_Y[0]
        x = -offset
        if x < 0:
            # A hanger is 1 px wide, so a negative x is entirely off the panel
            # and drawing it is a primitive spent on nothing.  The rack rows get
            # the same treatment through their own width test; this row needed
            # its own because its members have no width to test against.
            x += S.TRAY_HANGER_PITCH
        while x < self.WORLD_W:
            self.screen.rectangle(x, top, 1, S.TRAY_HANGER_H)
            x += S.TRAY_HANGER_PITCH

    def _drift(self, scrolled):
        """The pool's other connections, drifting through the flat middle band.

        The layer that answers "why is the middle of the panel empty" without
        putting anything in the middle of the panel that has to be avoided.
        Half speed, horizontal, and one step above the wall in ink.
        """
        offset = S.parallax_offset(scrolled, S.DRIFT_DIV, S.DRIFT_PERIOD)
        self.screen.pen = self.drift
        base = -offset
        while base < self.WORLD_W:
            for spot in S.DRIFT_CONNECTIONS:
                x = base + spot[0]
                if x >= self.WORLD_W:
                    continue
                y = self.Y_OFFSET + spot[1]
                # BODY AND TAIL ARE CLIPPED SEPARATELY, and both cases really
                # happen: a capsule leaving to the left has an invisible body
                # and a visible tail, and one arriving on the right has the
                # reverse.  `test_flappy_scene` found both by walking the whole
                # scroll cycle and asserting nothing is drawn off the panel.
                if x + S.DRIFT_W > 0:
                    self.screen.rectangle(x, y, S.DRIFT_W, S.DRIFT_H)
                # The tail trails BEHIND, which here means to the right: the
                # world moves left, so a thing being left behind is a thing
                # whose tail points the way it came from.
                tail = x + S.DRIFT_W
                if tail < self.WORLD_W and tail + S.DRIFT_TAIL > 0:
                    self.screen.rectangle(tail, y, S.DRIFT_TAIL, 1)
            base += S.DRIFT_PERIOD

    def _room(self, scrolled):
        """The pool room, back to front, at a fraction of the world's speed."""
        self.screen.pen = self.aisle
        self.screen.rectangle(
            0, self.Y_OFFSET + S.AISLE_Y, self.WORLD_W, M.FLOOR - S.AISLE_Y
        )
        self._tray(scrolled)
        self._drift(scrolled)
        self._skyline(scrolled)
        self._rack_row(
            scrolled,
            S.NEAR_DIV,
            S.NEAR_PERIOD,
            S.NEAR_RACKS,
            self.near,
            self.rack_lit,
        )
        # The pool's own wall, and the thing the connection cable is plugged
        # into.  It is scenery, so a pipe passes in FRONT of it — which is
        # right: a pooled connection is nearer the client than the wall the pool
        # lives behind.
        self.screen.pen = self.wall
        self.screen.rectangle(
            0, self.Y_OFFSET + M.CEILING, S.WALL_W, M.FLOOR - M.CEILING
        )

    def _intro_room(self):
        """A ceiling and a floor for the app root, and deliberately nothing else.

        See `flappy_scene.INTRO_TRAY_Y` for the rendered reason: the playfield's
        room cuts through three of the intro's five text rows, so the intro gets
        only the parts of a room that cannot touch a glyph.
        """
        self.screen.pen = self.tray
        for y in S.INTRO_TRAY_Y:
            self.screen.rectangle(0, y, self.WORLD_W, 1)
        x = 0
        while x < self.WORLD_W:
            self.screen.rectangle(
                x, S.INTRO_TRAY_Y[0], 1, S.INTRO_TRAY_Y[1] - S.INTRO_TRAY_Y[0]
            )
            x += S.TRAY_HANGER_PITCH
        self.screen.pen = self.rack_lit
        self.screen.rectangle(0, S.INTRO_FLOOR_Y, self.WORLD_W, 1)

    def _cable(self, state, held=False):
        """The connection the pool is holding open, and the timer coming for it.

        THIS IS THE PICTURE THE WHOLE THEME WAS MISSING.  Two rectangles: a 1 px
        line from the pool's wall to the client's left edge, and a bright head
        travelling out along it.  The line's brightness steps down four times
        between a keepalive and terminal velocity, and the head is the idle
        timer walking from the pool towards the client — when it arrives, the
        connection has been reclaimed, and by then the client is already falling
        at its cap.  The mechanic (stop tapping, sink, die) and the picture (the
        line dims, the pool comes to take it back) are one statement.

        No model change paid for any of it.  ``vy`` already said how many steps
        ago the client last spoke to the pool, spelled as a velocity, and
        `flappy_scene.idle_age` reads it back.

        ``held`` is the pause card's case: a paused pool is holding the
        connection open deliberately, so the cable is drawn at full brightness
        and the timer's head is parked at the wall.  That is what `PAUSE` means
        in a pooler.
        """
        y = self.Y_OFFSET + state["y"] // M.UNIT + M.CLIENT // 2
        vy = state["vy"]
        self.screen.pen = self.cable_pens[0 if held else S.cable_ink_index(vy)]
        self.screen.rectangle(S.WALL_W, y, M.CLIENT_X - S.WALL_W, 1)
        # THE HEAD NEEDS A CROSSBAR TO BE FINDABLE.  Rendered as a bare 3x1 of
        # the brightest cable ink against a 1 px body one step below it, the
        # difference was invisible at 160x120 — a hairline is a hairline.  A
        # 1x3 upright at its leading edge turns it into a mark that reads as a
        # thing travelling along a wire, for one more rectangle.
        head = S.WALL_W if held else S.reclaim_x(vy)
        self.screen.pen = self.cable_pens[0]
        self.screen.rectangle(head, y, S.RECLAIM_W, 1)
        self.screen.rectangle(head + S.RECLAIM_W - 1, y - 1, 1, 3)

    # ---- the world ----------------------------------------------------------

    def _slot_run(self, x, start, step, low, high, mask):
        """A pipe's slot faces, from the mouth outwards until one no longer fits.

        The faces are inset 1 px either side of the 14 px shaft, so the pipe
        keeps an unbroken 1 px frame and its SILHOUETTE — the thing collision is
        actually about — is never interrupted by the decoration inside it.
        """
        left = x + S.SLOT_INSET
        width = M.PIPE_W - 2 * S.SLOT_INSET
        index = 0
        y = start
        while y >= low and y + S.SLOT_H <= high:
            self.screen.pen = self.slot_lit if S.slot_lit(mask, index) else self.slot
            self.screen.rectangle(left, y, width, S.SLOT_H)
            index += 1
            y += step

    def _pipes(self, state):
        gap = state["gap"] // M.UNIT
        floor = self.Y_OFFSET + self.WORLD_H
        level = state["level"]
        for pipe in state["pipes"]:
            x = pipe[0] // M.UNIT
            # The model keeps a pipe placed a full spacing beyond the panel so
            # the next gap exists before it is needed; drawing it would put a
            # column on the right edge that is not really there.
            if x >= self.WORLD_W or x + M.PIPE_W <= 0:
                continue
            top_px = pipe[1] // M.UNIT
            top = self.Y_OFFSET + top_px
            bottom = top + gap
            self.screen.pen = self.pipe
            self.screen.rectangle(x, self.Y_OFFSET, M.PIPE_W, top - self.Y_OFFSET)
            self.screen.rectangle(x, bottom, M.PIPE_W, floor - bottom)
            # A PIPE IS A RACK OF POOLED CONNECTIONS AND NOT A SLAB, which is
            # the change that makes the picture and the mechanic say the same
            # thing.  Occupancy is a pure function of the pipe's own gap top —
            # a number the model fixes at spawn and never touches — so a given
            # pipe's slots never flicker while it crosses the panel, and no
            # per-pipe state was added to store them.
            mask = S.slot_mask(top_px, level)
            self._slot_run(
                x,
                top - self.COLLAR_H - S.SLOT_H,
                -S.SLOT_PITCH,
                self.Y_OFFSET,
                top,
                mask,
            )
            self._slot_run(
                x, bottom + self.COLLAR_H, S.SLOT_PITCH, bottom, floor, mask
            )
            self.screen.pen = self.collar
            self.screen.rectangle(
                x - self.COLLAR_OUT,
                top - self.COLLAR_H,
                M.PIPE_W + 2 * self.COLLAR_OUT,
                self.COLLAR_H,
            )
            self.screen.rectangle(
                x - self.COLLAR_OUT,
                bottom,
                M.PIPE_W + 2 * self.COLLAR_OUT,
                self.COLLAR_H,
            )

    def _rails(self, state):
        """The two lethal edges, drawn on exactly the y that kills.

        A decorative rail inset from an invisible kill line is a lie the panel
        cannot correct, so these are not decoration: `flappy_model.CEILING` and
        `FLOOR` are these two rectangles.
        """
        self.screen.pen = self.pipe
        self.screen.rectangle(0, self.Y_OFFSET, self.WORLD_W, M.RAIL)
        self.screen.rectangle(
            0, self.Y_OFFSET + M.FLOOR, self.WORLD_W, self.WORLD_H - M.FLOOR
        )
        # The floor's dashes scroll with the world, so the run reads as moving
        # even while the client is holding a line between two pipes.  Derived
        # from the model's own odometer rather than from a frame counter, so a
        # paused world's floor is as still as its pipes.
        offset = (state["scrolled"] // M.UNIT) % self.DASH_PITCH
        self.screen.pen = self.collar
        x = -offset
        while x < self.WORLD_W:
            self.screen.rectangle(
                x, self.Y_OFFSET + M.FLOOR, self.DASH, self.WORLD_H - M.FLOOR
            )
            x += self.DASH_PITCH

    def _client(self, state, pen=None):
        """The Supabase mark, a state field behind it, and a tilt pip on it.

        THE MARK'S COLOUR IS BAKED INTO THE SHEET, so the two readings the old
        8x8 rectangle carried in its pen cannot be a pen any more -- and both are
        MEANING pens the palette is not allowed to flatten: yellow is an armed
        state and red is death.  They become a field the size of the sprite's own
        footprint with the mark blitted on top, so the client still says which of
        the three states it is in AND still reads as the client while it says so.
        On a normal frame there is no field at all and the mark is the only ink.

        AND THE TILT PIP IS GONE, WHICH IS A DELETION DECIDED BY LOOKING.  The
        old client was an 8x8 square plus a 2x2 white pip that slid up and down
        its right edge, and the pip was the right idea for a square: picovector
        can turn a sprite, but a rotation per frame is the per-pixel work the
        frame budget forbids, so tilt was INDICATED rather than drawn.

        Two things killed it, and only the second one is obvious in advance.

        It stopped being on an edge.  The sprite is 12 px on the model's 8, so
        `M.CLIENT_X + M.CLIENT - 2` is no longer the client's right edge -- it is
        3 px INSIDE the mark.  Rendered at 18x out of a real captured frame it
        reads as a hole punched in the logo, which is the "it does not read as a
        picture, it reads as a rendering fault" failure `game-art.md` §12 names
        for the elephant.  Moving it clear of the sprite would have made it a
        detached dot flying alongside the client instead.

        And it stopped being needed, which is the real reason.  The pip's job was
        to say which way the client is going, in three states -- climbing, level,
        sinking.  The mark's own value ramp now says exactly that, in three
        states, off the SAME `vy`: MIST on a keepalive that has just landed, PALE
        as it levels, the brand green as it sinks.  Same information, over 60 lit
        pixels instead of 4, and it is the animation the sheet was generated to
        carry.  A 2x2 corner repeating what the whole mark already says is not an
        instrument, it is a blemish.

        So the frame is one blit where it was two rectangles -- which is what
        `game-art.md` §12 predicted, though not for the reason it gave.
        """
        y = self.Y_OFFSET + state["y"] // M.UNIT
        left = M.CLIENT_X - self.CLIENT_INSET
        top = y - self.CLIENT_INSET
        ring = pen if pen is not None else (self.yellow if state["ready"] else None)
        if ring is not None:
            self.screen.pen = ring
            self.screen.rectangle(left, top, self.CLIENT_CELL, self.CLIENT_CELL)
        # One index and one blit.  The frame is the same bucket the cable's pen
        # comes from, so a keepalive brightens the client and its connection in
        # the same frame and the idle timer dims both.
        self.screen.blit(
            self.client_sprites[S.cable_ink_index(state["vy"])],
            self.vec2(left, top),
        )

    def _world(self, state, client_pen=None, held=False):
        """Back to front: field, room, pipes, rails, cable, client.

        THE CABLE IS DRAWN AFTER THE PIPES, DELIBERATELY.  A pipe the client has
        just cleared sits between it and the wall, and the connection trails
        over that pipe rather than behind it — which is correct, because the
        connection is the client's and the pipe is only the slot it borrowed.
        """
        self.screen.pen = self._clear()
        self.screen.rectangle(0, self.Y_OFFSET, self.WORLD_W, self.WORLD_H)
        self.screen.font = self.font.sins
        if self.room:
            self._room(state["scrolled"])
        self._pipes(state)
        self._rails(state)
        self._cable(state, held)
        self._client(state, client_pen)

    def play(self, state, high_score, hint="A  PAUSE", hint_pen=None,
             best=False, held=False):
        self._world(state, held=held)
        # The prompt rule, one rectangle, on the strip's last row.
        self.screen.pen = self.pipe
        self.screen.rectangle(0, self.RULE_Y, self.WORLD_W, 1)
        score_text = "SERVED {:03d}".format(state["score"])
        self.screen.pen = self.white
        self.screen.text(score_text, 2, 2)
        score_width, _height = self.screen.measure_text(score_text)
        if best:
            # The stored number stopped being a target the moment it was
            # passed, and SERVED already carries the live score, so the slot
            # carries the state instead of repeating a figure.
            right_text = "BEST"
            right_pen = self.yellow
        else:
            right_text = "HI {:03d}".format(high_score)
            right_pen = self.grey
        right_width, _height = self.screen.measure_text(right_text)
        self.screen.pen = right_pen
        self._right(right_text, 2)
        # A, NOT B.  B is the keepalive and is pressed constantly, so it cannot
        # also be the pause; the strip names the key that does pause, for the
        # life of the screen rather than on a timer.
        self.screen.pen = self.grey if hint_pen is None else hint_pen
        self._center_between(hint, 2 + score_width, 160 - right_width - 3, 2)

    def paused(self, state, high_score, best=False, confirm=False):
        """The frozen world, dimmed, under a card carrying the way out.

        The world is drawn first and stays visible through the card, so pausing
        visibly did not destroy the run.  The status strip does not move: only
        its middle word changes, so the eye does not have to re-find SERVED
        or HI.

        ``confirm`` is the belt to the brace, and this app needs it more than
        its siblings do: A is the key that OPENED this card, so a player who
        taps A twice out of habit would otherwise end his own run with the
        second tap.  The first A does not quit; it turns the key-map line into
        the question, turns the A label red and changes its wording to
        `A   QUIT NOW`.  Only the second A ends the run, and B clears the
        question by resuming.  Row positions do not move between the two
        states, so answering the question is not a moving target.
        """
        self.play(state, high_score, "PAUSED", self.yellow, best, held=True)
        self.screen.pen = self.pause_scrim
        self.screen.rectangle(0, self.Y_OFFSET, self.WORLD_W, self.WORLD_H)
        self.screen.pen = self.pause_card
        self.screen.rectangle(12, 26, 136, 88)
        # The label slot is always drawn, so the layout never jumps.
        self.screen.pen = self.yellow if best else self.grey
        self._center("NEW HIGH" if best else "HIGH", 30)
        self.screen.pen = self.yellow if best else self.accent
        self._center("{:03d}".format(state["score"] if best else high_score), 42, 2)
        self.screen.pen = self.grey
        self._center("LOAD {}".format(state["level"]), 60)
        if confirm:
            self.screen.pen = self.yellow
            self._center("QUIT THIS RUN?", 72)
        else:
            # `PAUSE` IS A REAL POOLER COMMAND AND THAT IS THE WHOLE POINT.
            # pgbouncer's admin console has `PAUSE <db>`: it lets the queries in
            # flight finish and then holds the pool without dropping a single
            # client.  That is exactly what this screen does — the run is frozen
            # and the connection is still open — so the card says it in the
            # pool's own syntax instead of repeating a key map the intro already
            # gave.  It is also why `_cable` is drawn at full brightness here:
            # a paused pool is holding the connection open deliberately, and
            # the idle timer's head is parked back at the wall.
            self.screen.pen = self.collar
            self._center("PAUSE pooler;", 72)
        self.screen.pen = self.white
        self._center("B   RESUME", 86)
        self.screen.pen = self.red if confirm else self.grey
        self._center("A   QUIT NOW" if confirm else "A   QUIT", 100)

    def finished(self, state, high_score, best=False, save_failed=False):
        """The world that ended the run, held under the result.

        This is a render state, not a phase: B and A are live from the first
        frame after the arming window and nothing is gated on a timer, so an
        impatient player at a booth is never made to wait.

        WHAT IS ABOVE THE SCRIM IS SEVEN ROWS OF TEXT AND NOTHING ELSE — no
        marker, no keyline, not one rectangle.  That is the invariant that keeps
        this card readable, the geometry block above is the argument for it, and
        `test_flappy_scene.DeathCardTests` walks every reachable death height
        and fails if any ink at all appears over a row again.

        ``save_failed`` IS NOT DECORATION.  The high-score write is caught in
        `finish_game` so that a full volume cannot turn every dropped
        connection into a reboot, and the record on disk survives intact either
        way -- but a run that beat the record and could not store it must not
        sit here in the yellow this app uses for a bank and let the player
        believe it was taken.  When the flag is set the run's line drops back to
        white and one row says so.

        The card needs no separate symbol: the world is frozen exactly where it
        stopped, so the client is still standing on the thing that refused it,
        at RGB(35, 54, 43) under the scrim against a RGB(3, 7, 8) field.  Two
        earlier answers were wrong in the same direction and are worth naming
        so neither is reinvented — a FILLED 12 px cell with the mark blitted on
        it, which deleted twelve columns of whichever sentence the run died on,
        and then a 1 px KEYLINE, which painted no glyph body but crossed the
        red `53300` row in red and cost it its digits anyway.
        """
        self._world(state)
        self.screen.pen = self.finish_scrim
        self.screen.rectangle(0, 0, 160, 120)
        self.screen.pen = self.red
        # THIS IS THE SCREEN A DEVELOPER PHOTOGRAPHS, and `docs/badge-games.md`
        # §7 says why it is also the cheapest theming on the badge: a real
        # SQLSTATE costs strings, needs no asset, no licence and no frame
        # budget.  `53300 too_many_connections` is the actual Postgres error for
        # what just happened to this client, and it is not a pun on one.
        #
        # `FATAL` rather than `POOL EXHAUSTED` at scale 2: it is the severity
        # prefix psql really prints, it is 30 px at scale 1 so it fits on ONE
        # line at scale 2 where `POOL EXHAUSTED` needed two, and the line it
        # frees is what pays for the DETAIL and HINT rows below.
        self._center("FATAL", 3, 2)
        self._center(self.sqlstate_line(), 27)
        self.screen.pen = self.grey
        self._center(self.detail_line(state), 41)
        # THE HINT NAMES WHAT HAPPENED, and the headline still does not.  The
        # README rejected a per-CAUSE HEADLINE and that rejection stands: the
        # first two lines of this screen are the same three words for every
        # death, so the screen has one identity.  A `HINT` row underneath is a
        # different thing — it is the row Postgres itself uses for exactly this,
        # it adds no state (the model has stored `cause` since the day it
        # shipped and prints it to serial), and it turns "I died" into "the idle
        # timer got me" at the cost of one dictionary lookup.
        self._center(self.hint_line(state), self.HINT_Y)
        # YELLOW HERE IS A CLAIM, so a failed commit takes it away.  `best`
        # latched during play against the record that was on disk; if the write
        # then failed, `high_score` is still the OLD number and this line would
        # read "you beat 118" in the record colour beside a HIGH that is still
        # 118.  White plus the warning row is the honest pair.
        self.screen.pen = self.yellow if best and not save_failed else self.white
        # The load is NOT on this line: it does not price the score, so
        # `SERVED 040` means the same thing at load 1 and load 9 and a tag here
        # would imply otherwise.
        self._center(
            "SERVED {:03d}  HIGH {:03d}".format(state["score"], high_score),
            self.FOOTER_SCORE,
        )
        if save_failed:
            # YELLOW, NOT RED, and the pen is the argument.  On this card red is
            # the CAUSE -- `FATAL` and the SQLSTATE -- and a full volume did not
            # refuse the connection.  Yellow is this app's record channel, and
            # what this row reports is the record's state.  `WARNING` is also a
            # severity psql really prints, so the row stays inside the
            # transcript idiom the card is photographed for.  141 px against the
            # 160 px canvas — second only to the 149 px SQLSTATE row.
            self.screen.pen = self.yellow
            self._center("WARNING  record not written", self.FOOTER_WARNING)
        self.screen.pen = self.accent
        self._center("B  RECONNECT", self.FOOTER_RECONNECT)
        # A badge that lost its connection in a pocket must not sit lit on a
        # death screen all day with a restart as its only offer.
        self.screen.pen = self.grey
        self._center("A  MENU", self.FOOTER_MENU)
