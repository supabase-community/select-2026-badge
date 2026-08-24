"""All Pet rendering.  Everything that touches a Badgeware drawing primitive
lives here and arrives through the constructor, so nothing else in the package
needs a device or a browser to be tested.

It draws a render plan produced by `pet_app` and never reads a clock, a file or
an input.  Only C-backed primitives and blits are used: a full-screen pixel loop
in Python measured 703 ms on this hardware, and image filters cost 21-45 ms full
screen (and silently NO-OP on P8), so no filter is ever applied per frame.

SHEET ADDRESSING.  Three sheets - body, face, prop - and every source rectangle
comes from `pet_atlas`, which the host generator writes.  This module holds no
cell coordinates at all: the anchor table used to be duplicated here by hand,
with a comment admitting it, so a designer moving a head made every face float.

ANIMATION IS DRIVEN BY THE FRAME COUNTER, NEVER BY SIMULATED TIME.  The breathe
cycle, the blink, the gaze drift and the idle hop all key off `plan["frame"]`,
so a creature on the 120x clock still breathes and blinks at human speed.  None
of it touches the model, and none of it is stored.
"""

import pet_atlas as atlas
import pet_model as model
import ui
from pet_tuning import (LOW_HEALTH_T, PAUSE_BUTTON, PAUSE_FROM, PAUSE_LINE_1,
                        PAUSE_LINE_2, PAUSE_SUBJECT, WASTE_MAX)


ASSET_ROOT = "assets"

# The face a controller REACTION plays, by the outcome the model reported.  A
# reaction is view-only and lasts a few hundred ms: nothing about it is saved,
# and an unknown event simply falls through to the mood.
REACT_FACE = {
    "fed": "eat", "refused": "refuse", "overfed": "grossed", "full": "grossed",
    "cleaned": "relief", "cured": "relief", "dosed": "relief",
    "scolded": "scolded", "played": "cheer", "woke": "dizzy",
    "hatched": "hatch", "restoring": "relief",
}

# The breathe: frames 0,1,0,2 of the body column, one beat per seven frames, so
# a full cycle is about 0.93 s at 30 fps.
BREATHE = (0, 1, 0, 2)
BREATHE_FRAMES = 7
BOB = (0, 1, 0, -1)
# The idle float: an arc every ~6 s, so the creature is not welded to one spot on
# a badge somebody wears all day.
#
# THE RULE THIS TABLE OBEYS: never move more than ONE logical pixel per frame.
# One logical pixel is TWO physical pixels at LORES, so a 3 px step is a 6 px
# jump on the panel and reads as a twitch, not a hover. The previous table
# travelled 5 px in six frames — the whole float in 0.2 s — and was reported as
# "janky". Sixteen frames of 1 px is the same motion, legible.
#
# The X table exists for the same reason and obeys the same rule. It replaces a
# `1 if step % 2 else 0` term, which alternated the creature one pixel sideways
# on ALTERNATE FRAMES: a 15 Hz shimmer that never displaced it anywhere, so it
# paid for the jitter without buying the drift it was written for.
HOP = (0, -1, -2, -3, -4, -4, -5, -5, -5, -5, -4, -4, -3, -2, -1, 0)
HOP_X = (0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0)
HOP_PERIOD = 180
BLINK_PERIOD = 97
GAZE_FRAMES = 47

FLOOR_Y = 96
# The creature stands ON the floor: the atlas says which cell row its feet are
# on, so a designer who moves the feet moves this with them.
CREATURE_Y = FLOOR_Y - atlas.BODY_GROUND
CREATURE_X = 40                 # care: the 138 px playfield left of the ring
POSTER_X = 52                   # poster: the full 160 px canvas
NEWS_X = 96                     # news: right of a 86 px story panel
# Waste sits where the creature is not: two piles right of it, one far left.
WASTE_X = (100, 4, 120)
# Readout rows that fit between the header and the softkey bar, at 14 px each.
# The controller uses the same number to clamp the window it scrolls.
LIST_ROWS = 6
# The care ring lives on the RIGHT edge, spanning the UP/DOWN key centres at
# y = 33 and 87, because the affordance belongs beside the keys that drive it.
# Six 16 px icons from y=6 to y=102 clear the softkey bar at y=107.
RING_X = 141
RING_TOP = 6
RING_STEP = 16
BAR_W = 116
# The toast band sits under the health readout and ABOVE the creature's head:
# at the old y it cut straight across the legs of a 56 px creature.
TOAST_Y = 24
TOAST_H = 14
# ...except on the EGG, which is the one care screen that draws TEXT in that
# band.  The egg names its clock there, key C changes it, and every press of C
# raised a toast that landed exactly on top of the sentence it had just changed,
# so the headline feature's only affordance was illegible for 1.5 s at the one
# moment it mattered.  The egg's band therefore drops to the floor line, where
# it covers four rows of shell instead of a line of type, and it sits directly
# above the softkey bar that carries the key which raised it.
EGG_TOAST_Y = 92


# Model row -> atlas body column.  One entry per identity, written out rather
# than computed: an art sheet may legitimately lead or lag the model, and a
# creature drawn as the identity next door is a bug nobody would think to look
# for.  `test_pet_guards` asserts the two stay the same length.
BODY_COLUMN = (0, 1, 2, 3, 4, 5, 6, 7)


def body_row(state):
    """The atlas body column for this creature.

    Stages map straight through; the adult's three forms extend the run, so
    HA PROD, PROD and LEGACY are the last three identities on the sheet.
    """
    row = state["stage"]
    if row >= model.STAGE_COUNT - 1:
        row = model.STAGE_COUNT - 1 + state["form"]
    if row >= len(BODY_COLUMN):
        row = len(BODY_COLUMN) - 1
    return BODY_COLUMN[row]


def breathe(frame):
    """(body frame, vertical bob) - the whole idle animation, from one int."""
    beat = (frame // BREATHE_FRAMES) & 3
    return BREATHE[beat], BOB[beat]


def hop(frame):
    """(dx, dy) of the occasional idle float.  Both tables end at 0, so the
    creature always lands exactly where it started."""
    step = frame % HOP_PERIOD
    if step >= len(HOP):
        return 0, 0
    return HOP_X[step], HOP[step]


class PetView:
    def __init__(self, screen, image_api, color_api, font_api, vec2_api, rect_api,
                 asset_root=ASSET_ROOT, on_sheet=None):
        self.screen = screen
        self.image = image_api
        self.color = color_api
        self.font = font_api
        self.vec2 = vec2_api
        self.rect = rect_api
        # Loaded ONCE, at construction, and held.  Measured in the pinned
        # runtime: a decoded P8 is not reclaimed by the collection that follows
        # its release, so a load-per-screen scheme transiently holds several
        # sheets.  There is nothing to gain and a fragmented heap to lose.
        #
        # `on_sheet` IS THE LOADING SCREEN'S SEAM, and it exists because a P8
        # decode is ONE native call that cannot be animated through.  Three of
        # them back to back is the longest unbroken stretch in this app's load
        # (4,826 + 1,209 + 2,665 bytes), and while it runs a stage-driven
        # progress bar sits frozen -- which is exactly what reads as a crash.
        # The decodes cannot be subdivided, but they can be SEPARATED: the
        # callback runs between them, and `shared/loading.py` presents a frame
        # there.  Default None, so nothing else that builds a view changes.
        root = asset_root.rstrip("/")
        self.body_sheet = image_api.load(
            root + atlas.BODY_SHEET[len(ASSET_ROOT):])
        if on_sheet:
            on_sheet("-- pet-body-p8.png, 4826 B")
        self.face_sheet = image_api.load(
            root + atlas.FACE_SHEET[len(ASSET_ROOT):])
        if on_sheet:
            on_sheet("-- pet-face-p8.png, 1209 B")
        self.prop_sheet = image_api.load(
            root + atlas.PROP_SHEET[len(ASSET_ROOT):])
        if on_sheet:
            on_sheet("-- pet-prop-p8.png, 2665 B")
        self.chrome = ui.Chrome()

        self.dark = color_api.rgb(8, 13, 28)
        self.panel = color_api.rgb(18, 29, 50)
        self.floor = color_api.rgb(13, 22, 38)
        self.white = color_api.rgb(255, 255, 255)
        self.mint = color_api.rgb(62, 240, 174)
        self.yellow = color_api.rgb(255, 220, 74)
        self.red = color_api.rgb(245, 58, 88)
        self.green = color_api.rgb(45, 220, 135)
        self.grey = color_api.rgb(105, 112, 124)
        self.dim = color_api.rgb(10, 16, 30, 165)
        self.light_grey = color_api.rgb(207, 211, 216)
        self.paper = color_api.rgb(238, 240, 243)

    # -- primitives --------------------------------------------------------

    def _cell(self, sheet, source_xy, w, h, x, y):
        self.screen.blit(sheet,
                         self.rect(source_xy[0], source_xy[1], w, h),
                         self.rect(x, y, w, h))

    def _prop(self, source_xy, w, h, x, y):
        self._cell(self.prop_sheet, source_xy, w, h, x, y)

    def _text(self, message, x, y, pen=None, size=1):
        if pen is not None:
            self.screen.pen = pen
        self.screen.font = self.font.sins
        self.screen.text(message, x, y, size)

    def _bar(self, labels):
        self.chrome.bar(labels, ink=self.white, panel=self.color.rgb(0, 0, 0, 210))

    # -- shared furniture --------------------------------------------------

    def _health(self, state, rate, width_px=BAR_W, x=6):
        width = max(0, min(width_px, state["health"] * width_px // model.MAX))
        self.screen.pen = self.grey
        self.screen.rectangle(x, 3, width_px, 7)
        self.screen.pen = self.green if state["health"] > LOW_HEALTH_T else self.red
        self.screen.rectangle(x, 3, width, 7)
        self._text("DB HEALTH {:3d}%".format(state["health"] // 10), x, 12,
                   self.white)
        # The derivative, beside the level: a status app whose headline number is
        # an integral is unreadable without it.
        if rate:
            self._text("{}{}/H".format("+" if rate > 0 else "-", abs(rate) // 10),
                       x + width_px - 30, 12,
                       self.green if rate > 0 else self.red)

    def _creature(self, state, frame, x=CREATURE_X, y=CREATURE_Y, react="",
                  moving=True):
        """One creature: body, face, gaze, blink and the sleep mark.

        Three blits at rest, five when the eyes are open and blinking.  Every
        cycle is keyed off the FRAME counter, so the animation runs at human
        speed whatever the simulated clock is doing.
        """
        row = body_row(state)
        step, bob = breathe(frame) if moving else (0, 0)
        drift_x, drift_y = hop(frame) if moving else (0, 0)
        x += drift_x
        y += bob + drift_y
        self._cell(self.body_sheet,
                   (row * atlas.BODY_CELL, step * atlas.BODY_CELL),
                   atlas.BODY_CELL, atlas.BODY_CELL, x, y)
        if state["stage"] == 0:
            return                      # an egg has no face yet
        name = REACT_FACE.get(react) or model.mood_name(state)
        column = atlas.FACE_COLUMN.get(name, atlas.FACE_COLUMN["neutral"])
        anchor = atlas.FACE_ANCHOR[row]
        face_x = x + anchor[0]
        face_y = y + anchor[1]
        self._cell(self.face_sheet, atlas.FACE_XY[column],
                   atlas.FACE_W, atlas.FACE_H, face_x, face_y)
        if atlas.FACE_PUPILS[column]:
            # The face carries eye WHITES only; the gaze is an overlay, so
            # thirteen moods need no gaze variants and the creature can look
            # around for one extra blit.
            gaze = (frame // GAZE_FRAMES) % len(atlas.PUPIL_XY)
            self._cell(self.face_sheet, atlas.PUPIL_XY[gaze],
                       atlas.PUPIL_W, atlas.PUPIL_H, face_x + 4, face_y + 4)
            blink = frame % BLINK_PERIOD
            if blink < 4:
                phase = 0 if blink in (0, 3) else 1
                material = atlas.BODY_MATERIAL[row]
                self._cell(self.face_sheet, atlas.LID_XY[material][phase],
                           atlas.LID_W, atlas.LID_H, face_x, face_y + 2)
        if state["asleep"]:
            self._prop(atlas.ZZZ_XY[(frame // 12) % len(atlas.ZZZ_XY)],
                       atlas.SMALL, atlas.SMALL, x + atlas.BODY_CELL - 12, y - 4)

    def _room(self, width):
        """Two server racks and a grating, so the creature lives somewhere.

        Drawn with blits and C-backed rectangles only - a Python pixel loop over
        this area measured 703 ms full screen.
        """
        self._prop(atlas.RACK_XY, atlas.RACK_W, atlas.RACK_H,
                   2, FLOOR_Y - atlas.RACK_H)
        right = width - atlas.RACK_W - 2
        if right > CREATURE_X + atlas.BODY_CELL:
            self._prop(atlas.RACK_XY, atlas.RACK_W, atlas.RACK_H,
                       right, FLOOR_Y - atlas.RACK_H)
        self.screen.pen = self.panel
        for x in range(4, width - 4, 20):
            self.screen.rectangle(x, FLOOR_Y + 6, 12, 1)
            self.screen.rectangle(x + 6, FLOOR_Y + 14, 12, 1)

    def _waste(self, state, frame):
        """Two families of mess, so a full floor is not one blob three times."""
        piles = min(WASTE_MAX, state["waste"])
        for index in range(piles):
            cell = atlas.WASTE_XY[(index % 2) * 3 + min(2, index)]
            x = WASTE_X[index]
            self._prop(cell, atlas.WASTE_W, atlas.WASTE_H, x,
                       FLOOR_Y - atlas.WASTE_H + 6)
        if piles >= WASTE_MAX:
            # The mess is alive.  One 12 px blit, only at the cap.
            self._prop(atlas.FLY_XY[(frame // 6) % len(atlas.FLY_XY)],
                       atlas.FLY_W, atlas.FLY_H,
                       WASTE_X[0] + 4, FLOOR_Y - 34 + (frame // 9) % 3)

    def _ant(self, permille, tier, frame):
        """Four THREAT TIERS, not one walk cycle: a doorway silhouette, then
        walking in with a tablet, then the stylus up, then beside the creature
        with a finger over the button.  The controller already computes the
        closing distance; the old art threw all of it away."""
        if permille <= 0:
            return
        x = -atlas.ANT_W + (CREATURE_X + 12) * permille // 1000
        tier = 0 if tier < 0 else (atlas.ANT_TIERS - 1 if tier >= atlas.ANT_TIERS
                                   else tier)
        self._prop(atlas.ANT_XY[tier][frame % 3], atlas.ANT_W, atlas.ANT_H,
                   x, FLOOR_Y - atlas.ANT_H + 2)
        self.screen.pen = self.red
        self.screen.rectangle(0, 0, 2, FLOOR_Y)

    def _food_flight(self, state, react, permille):
        """A fed row flies from the ring icon to the mouth on an integer arc."""
        if react != "fed" or permille >= 1000:
            return
        kind = state["total_feeds"] % len(atlas.FOOD_XY)
        row = body_row(state)
        anchor = atlas.FACE_ANCHOR[row]
        start_x, start_y = RING_X, RING_TOP
        end_x = CREATURE_X + anchor[0] + 8
        end_y = CREATURE_Y + anchor[1] + 6
        x = start_x + (end_x - start_x) * permille // 1000
        y = start_y + (end_y - start_y) * permille // 1000
        y -= (1000 - abs(2 * permille - 1000)) * 12 // 1000
        self._prop(atlas.FOOD_XY[kind], atlas.FOOD_W, atlas.FOOD_H, x, y)

    def _floor(self, state, width=160):
        self.screen.pen = self.dark
        self.screen.clear()
        self.screen.pen = self.floor
        self.screen.rectangle(0, FLOOR_Y, width, 120 - FLOOR_Y)
        self.screen.pen = self.panel
        self.screen.rectangle(0, FLOOR_Y, width, 1)

    def _scroll_rail(self, top, total):
        """Chevrons that promise only movement that exists, plus a position rail.

        Both readouts scroll a WINDOW, so the affordance has to answer "can this
        key move anything" rather than "is this a list": drawing both chevrons
        unconditionally on a 13-row screen that shows 6 taught the wearer the key
        was broken every time the window was already at an end (R6).
        """
        highest = max(0, total - LIST_ROWS)
        self.chrome.scroll_hints(top > 0, top < highest)
        self.chrome.position(top, highest + 1)

    def _toast(self, message, width=134, y=TOAST_Y):
        """A band UNDER the health readout, not across the creature's shins.

        At the old y it ran straight through the legs of a 56 px creature; the
        message is a caption on the readout, so it belongs beside it.

        `y` exists for the ONE screen that already writes in that band - see
        EGG_TOAST_Y.  A band is opaque, so wherever it goes it must land on art
        it can afford to hide, never on type.
        """
        if not message:
            return
        self.screen.pen = self.color.rgb(0, 0, 0, 200)
        self.screen.rectangle(2, y, width, TOAST_H)
        self._text(message, 6, y + 1, self.yellow)

    # -- screens -----------------------------------------------------------

    def draw(self, plan):
        view = plan["view"]
        if view == model.POSTER:
            self.poster(plan)
        elif view == model.NEWS:
            self.news(plan)
        elif view == model.CARE:
            self.care(plan)
        elif view == model.STATS:
            self.stats(plan)
        elif view == model.LOG:
            self.log(plan)
        elif view == model.CONFIRM:
            self.confirm(plan)
        elif view == model.GAME:
            self.game(plan)
        elif view == model.PAUSED_VIEW:
            self.paused(plan)
        elif view == model.RESTORING_VIEW:
            self.restoring(plan)

    def poster(self, plan):
        """At rest the badge is a poster, not a UI: zero chrome, one creature."""
        state = plan["state"]
        frame = plan["frame"]
        self._floor(state)
        self._room(160)
        self._health(state, plan["rate"], 148, 6)
        self._waste(state, frame)
        self._creature(state, frame, POSTER_X)
        self._ant(plan["ant"], plan.get("ant_tier", 0), frame)
        self._text(model.stage_name(state), 6, 108, self.mint)
        label = "UP " + uptime(state)
        self._text(label, 154 - 6 * len(label), 108, self.grey)

    def care(self, plan):
        state = plan["state"]
        frame = plan["frame"]
        # An egg has no care actions, so the rail is hidden and the room is wide.
        width = 160 if state["stage"] == 0 else RING_X - 3
        self._floor(state, width)
        self._room(width)
        self._health(state, plan["rate"])
        self._waste(state, frame)
        self._creature(state, frame, CREATURE_X, react=plan.get("react", ""))
        self._food_flight(state, plan.get("react", ""),
                          plan.get("react_p", 1000))
        self._ant(plan["ant"], plan.get("ant_tier", 0), frame)
        if state["stage"] == 0:
            # The clock is chosen here and nowhere else, so it is NAMED here:
            # key C carries the other speed and the content says which one is on.
            fast = model.mode_of(state)
            self._text("CLOCK: FAST" if fast else "CLOCK: REAL", 6, 26,
                       self.mint if fast else self.white)
            self._text("1 HOUR EVERY 30 SEC" if fast else "1 HOUR EVERY HOUR",
                       6, 38, self.grey)
        self._ring(state, plan["index"], plan["suggest"])
        if plan["reveal"]:
            self._burst(plan)
        self._toast(plan["toast"],
                    y=EGG_TOAST_Y if state["stage"] == 0 else TOAST_Y)
        self._bar(plan["labels"])

    def _ring(self, state, index, suggest=-1):
        """Six fixed care icons in a rail down the right edge, spanning the UP
        and DOWN key centres.  The order never changes, so muscle memory survives
        a three-day wear; unavailable entries are dimmed rather than removed.

        The model's suggestion is drawn as a thin outline on its own icon rather
        than by moving the cursor.  Moving the cursor would relabel key B under
        the player's thumb; an outline is an invitation they can accept with one
        press of a direction key.
        """
        if state["stage"] == 0:
            return                      # an egg has no care actions at all
        self.screen.pen = self.panel
        self.screen.rectangle(RING_X - 3, 0, 160 - RING_X + 3, FLOOR_Y + 11)
        for slot, action in enumerate(model.RING):
            y = RING_TOP + slot * RING_STEP
            if slot == index:
                self.screen.pen = self.mint
                self.screen.rectangle(RING_X - 3, y - 1, 19, 18)
            elif slot == suggest:
                # A hollow box: the same colour as the cursor, so it reads as
                # "the cursor could be here", drawn as two C-backed rectangles
                # rather than a per-pixel outline.
                self.screen.pen = self.mint
                self.screen.rectangle(RING_X - 3, y - 1, 19, 18)
                self.screen.pen = self.panel
                self.screen.rectangle(RING_X - 2, y, 17, 16)
            self._prop(atlas.ICON_XY[slot], atlas.ICON_W, atlas.ICON_H,
                       RING_X, y)
            ok, _why = model.available(state, action)
            if not ok:
                self.screen.pen = self.dim
                self.screen.rectangle(RING_X, y, 16, 16)

    def _burst(self, plan):
        """Sparkles that FRAME the creature rather than covering its head.

        Both clear the toast band.  A stage-up ALWAYS raises an "EVOLVED: ..."
        toast on the same frame, so the upper sparkle at y=26 was drawn and then
        painted over, and every evolution showed one sparkle instead of two.
        """
        frame = plan["frame"] % len(atlas.SPARK_XY)
        self._prop(atlas.SPARK_XY[frame], atlas.SPARK_W, atlas.SPARK_H,
                   CREATURE_X - 8, TOAST_Y + TOAST_H + 6)
        self._prop(atlas.SPARK_XY[len(atlas.SPARK_XY) - 1 - frame],
                   atlas.SPARK_W, atlas.SPARK_H,
                   CREATURE_X + atlas.BODY_CELL - 8, 62)

    def news(self, plan):
        """The signature moment: the device cannot deliver an event, so the only
        place a six-hour story can be told is the moment of opening."""
        report = plan["news"] or {}
        state = plan["state"]
        self.screen.pen = self.dark
        self.screen.clear()
        # The panel narrows to make room for the creature: a 56 px cell drawn
        # where the old 40 px one sat ran off the right edge of the canvas.
        self.screen.pen = self.panel
        self.screen.rectangle(6, 6, 86, 88)
        self._text("AWAY " + span(report.get("away_s", 0)), 10, 10, self.yellow)
        self.screen.pen = self.grey
        self.screen.rectangle(10, 24, 78, 1)
        y = 30
        for line in news_lines(report)[:3]:
            self._text(line, 10, y, self.white)
            y += 14
        self._creature(state, plan["frame"], NEWS_X, CREATURE_Y - 6)
        self._bar(plan["labels"])

    def stats(self, plan):
        state = plan["state"]
        self.screen.pen = self.dark
        self.screen.clear()
        self._text("PROJECT STATUS", 6, 3, self.mint)
        self.screen.pen = self.grey
        self.screen.rectangle(6, 15, 148, 1)
        rows = model.stats_rows(state)
        top = _window_top(plan["top"], len(rows))
        y = 19
        for index in range(top, min(len(rows), top + LIST_ROWS)):
            name, value = rows[index]
            self._text(name, 6, y, self.grey)
            self._text(value, 84, y, self.white)
            y += 14
        self._scroll_rail(top, len(rows))
        self._bar(plan["labels"])

    def log(self, plan):
        state = plan["state"]
        self.screen.pen = self.dark
        self.screen.clear()
        self._text("EVENT LOG", 6, 3, self.mint)
        self.screen.pen = self.grey
        self.screen.rectangle(6, 15, 148, 1)
        lines = model.log_lines(state)
        if not lines:
            self._text("NOTHING YET", 6, 30, self.grey)
        y = 19
        top = _window_top(plan["top"], len(lines))
        for ago, text in lines[top:top + LIST_ROWS]:
            self._text(span(ago), 6, y, self.yellow)
            self._text(text, 56, y, self.white)
            y += 14
        self._scroll_rail(top, len(lines))
        self._bar(plan["labels"])

    def confirm(self, plan):
        """The ceremony, plus the one fact that turns it into a decision.

        At fast speed the reset is three presses from anywhere, so the guard
        that matters is INFORMATION rather than another press: the screen names
        what is about to be discarded, because it may be somebody else's
        three-day adult and not the egg the presser just made.
        """
        state = plan["state"]
        self.screen.pen = self.dark
        self.screen.clear()
        self.screen.pen = self.red
        self.screen.rectangle(0, 0, 160, 3)
        self._text("NEW PROJECT", 6, 12, self.red)
        self._text("THIS DELETES YOUR", 6, 34, self.white)
        self._text("CREATURE AND STARTS", 6, 48, self.white)
        self._text("AGAIN FROM AN EGG.", 6, 62, self.white)
        self._text("A BACKUP IS KEPT.", 6, 80, self.grey)
        self._text("{} UP {}".format(model.stage_name(state), uptime(state)),
                   6, 93, self.yellow)
        self._bar(plan["labels"])

    def game(self, plan):
        game = plan["game"]
        if game is None:
            # A frame-loop exception is a black screen with no way back, so the
            # renderer degrades to the care screen rather than raising.
            return self.care(plan)
        self.screen.pen = self.dark
        self.screen.clear()
        self._text("QUERY PLANNER", 6, 3, self.mint)
        self._text("ROUND {}/{}".format(min(game.round + 1, model.PLAY_ROUNDS),
                                        model.PLAY_ROUNDS), 104, 3, self.grey)
        self._text("PICK THE CHEAPER PLAN", 6, 17, self.white)
        for row in range(2):
            y = 34 + row * 26
            name, cost = game.rows[row]
            if plan["game_reveal"] and game.correct_row() == row:
                self.screen.pen = self.green
            elif game.cursor == row:
                self.screen.pen = self.panel
            else:
                self.screen.pen = self.floor
            self.screen.rectangle(6, y, 148, 22)
            if game.cursor == row:
                self.screen.pen = self.mint
                self.screen.rectangle(6, y, 3, 22)
            self._text(name, 14, y + 5, self.white)
            self._text("COST {}".format(cost), 96, y + 5, self.yellow)
        self._text("WON {}".format(game.wins), 6, 92, self.grey)
        self.chrome.scroll_hints(True, True)
        self._bar(plan["labels"])

    def paused(self, plan):
        """The money shot.  Our own wording; only the SHAPE of a service
        suspension notice is borrowed, and the product's own full-width button
        sits directly above key B."""
        self.screen.pen = self.light_grey
        self.screen.clear()
        self.screen.pen = self.grey
        self.screen.rectangle(6, 4, 148, 100)
        self.screen.pen = self.paper
        self.screen.rectangle(9, 7, 142, 94)
        self._text(PAUSE_FROM, 14, 11, self.dark)
        self._text(PAUSE_SUBJECT, 14, 24, self.grey)
        self.screen.pen = self.grey
        self.screen.rectangle(14, 37, 132, 1)
        self._text(PAUSE_LINE_1, 14, 43, self.dark)
        self._text(PAUSE_LINE_2, 14, 56, self.dark)
        self.screen.pen = self.red
        self.screen.rectangle(20, 74, 120, 20)
        self._text(PAUSE_BUTTON, 28, 79, self.white)
        self._bar(plan["labels"])

    def restoring(self, plan):
        state = plan["state"]
        remaining = state["restore_left_s"]
        self.screen.pen = self.dark
        self.screen.clear()
        self._text("RESTORING", 8, 12, self.yellow, 2)
        self._text("REPLAYING WAL", 30, 46, self.white)
        self._text("ABOUT {} MIN LEFT".format((remaining + 59) // 60), 28, 62,
                   self.grey)
        total = model.restore_s(state)
        done = total - remaining
        self.screen.pen = self.grey
        self.screen.rectangle(16, 84, 128, 8)
        self.screen.pen = self.green
        self.screen.rectangle(16, 84, max(0, min(128, done * 128 // total)), 8)
        self._bar(plan["labels"])


# -- pure text helpers, unit-testable without any drawing -------------------

span = model.span
stats_rows = model.stats_rows


def _window_top(top, total):
    """Clamp a scroll window to the rows that exist.  The controller already
    does this; the renderer repeats it so a hand-built plan (the host preview,
    the device capture probe) can never index past the end of the list."""
    if top < 0:
        return 0
    highest = max(0, total - LIST_ROWS)
    return highest if top > highest else top


def uptime(state):
    return model.span(state["age_s"])


def news_lines(report):
    """The away-report lines.  EVERY ONE MUST FIT NEWS_MAX_PX (82 px).

    `news` draws this panel at rect(6, 6, 86, 88) and then draws the CREATURE on
    top at x=96, so a line that overruns is not merely clipped - it is partly
    overdrawn by a sprite, which reads as corruption rather than as truncation.
    Three lines shipped over the limit (91, 90 and 88 px) because nothing
    measured them; `test_pet_ui_contract` now does.
    """
    lines = []
    if report.get("stage_up"):
        lines.append("IT EVOLVED")
    if report.get("paused"):
        lines.append("PROJECT PAUSED")
    if report.get("restored"):
        lines.append("RESTORED")
    if report.get("got_sick"):
        lines.append("IT GOT SICK")
    if report.get("misbehaved"):
        lines.append("UNRESTRICTED")
    if report.get("data_empty"):
        lines.append("DATA RAN OUT")
    if report.get("waste"):
        lines.append(_count(report["waste"], "DEAD TUPLE"))
    if report.get("mistakes"):
        lines.append(_count(report["mistakes"], "INCIDENT"))
    return lines


def _count(n, noun):
    """"+1 INCIDENT", not "+1 INCIDENTS".  The away panel is the one screen a
    player reads carefully, because it is the only place the badge can tell them
    what happened while they were gone."""
    return "+%d %s%s" % (n, noun, "" if n == 1 else "S")
