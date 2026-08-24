"""Every draw call in the app, and it mutates nothing.

THE DIVISION OF LABOUR.  `card_app` owns the state and draws no pixels; this
owns the pixels and changes no state.  The thing between them is the plan dict,
so neither can be wrong about the other in a way a test cannot see.

THE BADGE IS ALWAYS BEHIND YOU.  Every editing screen draws the wearer's actual
badge first and puts its own chrome over it through a scrim, rather than
replacing it with a settings page.  That is `identity`'s design and it is kept
for the reason its own contact sheets proved: a mark is placed against the NAME
and the ARTWORK as much as against the canvas, and a chooser that hides what it
is changing is a chooser you have to leave to evaluate.

WHAT THE CONTACT SHEETS ALREADY CAUGHT, so it is not re-learned here:

* `poster.name` bleeds through a translucent list panel.  Every list screen
  therefore draws the badge with `name=False`; `identity`'s mark list shipped
  the bug first and a screenshot found it, not a review.
* A plain white placement marquee VANISHES on the pale skins.  It is marching
  ants with a black keyline.
* Fifteen of the 76 backgrounds are pale enough that flat white type is
  invisible over them, which is what `poster`'s measured 0.36 polarity flip and
  eight-pass outline exist for.  Nothing here draws bare type over artwork.
* The renderer drops out-of-bounds glyphs SILENTLY -- that is how `profile`
  shipped an editor whose entry point was invisible on the physical device -- so
  every bounded label is drawn into a `rect` with `ELLIPSES`.

EVERY PIXEL CONSTANT IS A LOGICAL PIXEL times `chrome.scale`.  A logical pixel is
0.375 mm on the ruler-measured 60x45 mm panel at BOTH resolutions, so a constant
here is a PHYSICAL quantity that survives the flip.  There is no literal 160,
120, 320 or 240 in this file and `test_card_purity.ResolutionLiteralTests` walks
its AST to keep it that way.  (There is no `test_card_view.py`; the file this
docstring named for two weeks does not exist, which is the kind of citation a
reader trusts and then cannot find.)
"""

import backlight
import card_board
import card_faces as faces
import card_model as model
import effects
import identity_catalogue as catalogue
import identity_marks as marks
import poster as poster_module
import ui


# Content is inset from either edge by this much, so every line of copy has
# `width - 2 * TEXT_X` to live in.  `poster.TEXT_X`, so the chrome and the badge
# share a margin.
TEXT_X = 6

# The scrim an editing screen puts between the badge and its own chrome.  Dark
# enough to read white type over the brightest artwork in the catalogue,
# transparent enough that the badge is still legibly THERE -- the same 210 the
# softkey bar uses, so a screen and its bar are one surface rather than two.
SCRIM_ALPHA = 210

# The header block: one row of type plus air, over a slightly denser band.
HEAD_PAD = 2

# A mark's selection ring, and the placement marquee's dash.
RING = 2
DASH = 3

# THE HOME-SCREEN PREVIEW IS GONE (owner ruling, 2026-08-21): the wearer does
# not need an extra screen to confirm a save.  Its six geometry fractions -- the
# frame, the launcher's two bands and its six icon centres -- went with it, and
# `git log` is where they live now.  `card_bake` still knows the real launcher
# geometry, which is the copy that decides pixels.

# THE SAVE-TO-HOME ROW'S BUTTON.  A filled pill behind the value, sized to the
# word plus this much padding either side, in logical pixels: enough to read as
# a control rather than as a highlight, and small enough that the widest value
# still clears the label column.
PILL_PAD = 3

# How many filmstrip cells the sticker chooser shows.  Three: the one you are
# on, and enough of its neighbours to tell you the strip moves.
STRIP_CELLS = 3


def escaped(message):
    """`message` with every `[` doubled, which is the platform's own escape.

    `[` IN DATA IS A CRASH, NOT A CHARACTER.  The rect form of `screen.text` is
    the only form that parses `[markup]` (`badgeware-docs/api/text.md`: "Markup
    is only read when you draw into a `rect`"), and the wearer types their own
    name on a QWERTY board whose symbol plane carries `[` on its first row.
    Measured in the pinned runtime by `badgecard/host/markup_probe.mjs`, with
    the firmware's own registry line installed, three exceptions come out of a
    rect-form draw and every one of them fits inside `NAME_MAX`'s twelve
    characters: `[sprite:x]` raises `KeyError`, `[pen:1]` `TypeError` and
    `[pen:a,b,c]` `ValueError`.  All three land inside `update()`, which the
    frame loop LATCHES into the plain-name painter for the rest of the session
    -- so a wearer with a bracket in their name loses the whole editor until
    they relaunch, and relaunching reads the same name back off the disk.

    Doubling is unconditional rather than clever, because the invariant is a
    PROPERTY and not a list of hostile strings: no run of `[` in the output may
    have odd length.  `[[` in the wearer's name has to become `[[[[` for that to
    hold -- each literal bracket needs its own escape -- which `replace` gives
    for free and a scanner that tried to be smart about already-escaped input
    would get wrong.

    The same probe measured the two things this must NOT do.  `measure_text`
    does not parse markup, so an escaped string measures WIDER than it draws;
    that is why nothing here escapes on the way into `_width`.  And a rect form
    collapses `[[` to one bracket while a point form draws two, so the
    point-form draws -- `_text`, the editor's field, the poster's `outlined`,
    the baker -- must be left alone or a doubled bracket would SHOW as two.
    """
    return message.replace("[", "[[") if message else message


class CardView:
    """All the drawing.  Badgeware APIs injected, never read as globals.

    `ui.Chrome` is constructed HERE and therefore after the seam has called
    `badge.mode(...)`, which rebinds `screen`.  A chrome built before that call
    would size itself to the wrong canvas -- and would do it silently, because
    both canvases are valid.
    """

    def __init__(self, screen_api, image_api, color_api, font_api, vec2_api,
                 rect_api, chrome=None):
        self.screen = screen_api
        self.image = image_api
        self.color = color_api
        self.font = font_api
        self.vec2 = vec2_api
        self.rect = rect_api
        self.chrome = chrome if chrome is not None else ui.Chrome()
        chrome = self.chrome
        scale = chrome.scale
        self.scale = scale

        self.text_x = TEXT_X * scale
        self.ring = RING * scale
        self.dash = DASH * scale
        self.row_h = chrome.text_h + 2 * scale
        self.head_h = self.row_h + 2 * HEAD_PAD * scale

        self.dark = color_api.rgb(9, 14, 24)
        self.white = color_api.rgb(255, 255, 255)
        self.black = color_api.rgb(0, 0, 0)
        self.accent = color_api.rgb(62, 207, 142)
        self.grey = color_api.rgb(150, 160, 175)
        self.dim = color_api.rgb(255, 255, 255, 120)
        self.red = color_api.rgb(245, 80, 96)
        self.scrim = color_api.rgb(0, 0, 0, SCRIM_ALPHA)
        self.band = color_api.rgb(0, 0, 0, 210)
        self.head = color_api.rgb(0, 0, 0, 235)
        self.rule = color_api.rgb(255, 255, 255, 64)
        self.plate = color_api.rgb(8, 16, 20, 245)

        # THE ONE RENDERER FOR THE BADGE, shared byte-identically with the
        # `poster` app by `scripts/sync_ui.py`.  This view DELEGATES; it holds
        # no copy and draws no artwork of its own.  A badge app that "looks
        # about right" is the exact failure that arrangement exists to prevent.
        self.poster = poster_module.Poster(screen_api, image_api, color_api,
                                           font_api, vec2_api, rect_api,
                                           chrome)

        # THE POSTER'S OWN STATE SHAPE, held once and refreshed per frame.
        # `poster.Poster` reads six keys and this app's badge carries four of
        # them: there is no second line and no motion switch, because the owner
        # ruled the menu is five rows and neither is one of them.  Adapting here
        # rather than persisting two dead fields keeps them out of every saved
        # badge and out of `repair`.
        self._pstate = {
            "name": "", "line2": "", "face": "", "background": "",
            "stickers": [], "motion": True,
        }
        self._pplan = {"state": self._pstate, "animate": "", "now": 0,
                       "frame": 0}

        # NO `ui.ListView`, and that is a deliberate omission rather than an
        # oversight.  Its virtue is a HIRES plate cache for a long list of
        # vector outlines, and the only list here long enough to want one -- the
        # 76 backgrounds -- is not a list at all: the skin browser shows the
        # whole badge, because the owner's ruling made the skin decide the FACE
        # and a list of names is a list of things you cannot see.  The three
        # short lists that remain draw a right-hand value column no plate can
        # hold, and at five rows the cache would buy nothing and cost an
        # allocation per visible row.
        #
        # The sticker sheet is acquired through the poster's own single lazy
        # path, so the chooser and the badge cannot end up holding two sheets
        # or -- worse -- two different ones at HIRES.
        self.strip_cells = STRIP_CELLS

        # THE NAME EDITOR, BUILT LAZILY.  It resolves one pixel table per plane
        # in its constructor and constructs a second `ui.Chrome` (the shared
        # `kb_shell.KeyboardView` builds its own and that file is byte-frozen),
        # and a wearer who never opens the name row should not pay for either.
        self._keyboard = None

    # -- primitives ----------------------------------------------------------

    def _type_ready(self):
        """Put the surface into the state TYPE has to be drawn in.

        THE STATE IS THE FILL RULE, AND THIS EXISTS BECAUSE A SKIN TOOK IT AWAY
        (2026-08-21).  `fill_rule` is STICKY PER SURFACE, `skins.animate(dst,
        ...)` is handed the SCREEN, and the rebuilt SUPABASE animator stopped on
        `NON_ZERO`.  Everything drawn afterwards inherited it -- and at HIRES
        this chrome is a `.af` OUTLINE face, where NON_ZERO fills the counter of
        any glyph whose inner contour winds the same way as its body.  The owner
        photographed his badge reading "SUPA[]ASE", "[]ADGES", "()FF" and
        "SAVE T() H()ME".  It looked like a broken font; the font was perfect.

        THE SKIN IS FIXED AND THIS IS STILL WORTH HAVING, because the two
        guarantees differ: a skin restoring what it borrows keeps every surface
        right, and this keeps THE MENU right no matter what a future artwork
        forgets.  A wearer whose menu is unreadable cannot navigate to the skin
        that did it, so the recovery path defends itself.

        EVEN_ODD is not a preference: it is picovector's own per-surface default
        and the only rule that draws a hole from an inner contour whichever way
        it is wound (`playground/e2e/vector-counters.spec.ts` measures both).

        NOT IN `shared/ui.py`, where the softkey bar lives, and that is
        deliberate: `kbgrid` freezes every byte of its vendored `ui.py` for the
        owner's keyboard A/B (`kb/tests/test_kb_sameness.py`), and this defect
        belongs to the two apps that draw skin artwork.  `badgecard` is the only
        one with a chrome MENU, so the fix lives here and covers it.
        """
        self.screen.fill_rule = self.image.EVEN_ODD

    def _text(self, message, x, y, pen=None):
        # Per CALL rather than once per frame: the skin browser draws live
        # artwork AFTER its own chrome, so there is no single point in a frame
        # after which nothing can leak.
        self._type_ready()
        if pen is not None:
            self.screen.pen = pen
        self.screen.text(message, x, y, font_size=self.chrome.font_size)

    def _width(self, message):
        """How wide this string draws, ROUNDED UP.

        Up, and never truncated, because every caller uses the answer as a
        BOUNDING BOX: `int(53.7)` is 53, a rect of 53 does not hold a 53.7 px
        string, and picovector answers a box one fraction too small by
        ELLIPSING.  At LORES the bitmap face measures whole pixels and nothing
        showed; at HIRES the vector face measures fractions and every value in
        the menu came out as `SAM...` and `3 OF...`.  Invisible in the code,
        obvious in the first HIRES screenshot.
        """
        if not message:
            return 0
        measured = self.screen.measure_text(
            message, font_size=self.chrome.font_size)[0]
        rounded = int(measured)
        return rounded + 1 if measured > rounded else rounded

    def _right(self, message, y, pen=None):
        self._text(message, self.chrome.width - self.text_x
                   - self._width(message), y, pen)

    def _bounded(self, message, x, y, width, pen=None, align=None):
        """Type inside a box, ELLIPSED rather than silently clipped.

        The renderer drops out-of-bounds glyphs with no mark at all, so a value
        that outgrew its column would simply not be there and nothing on the
        panel would say why.  This is the same guard `ui.Chrome.bar` applies to
        a softkey label, for the same reason.

        THE ONE RECT-FORM DRAW IN THIS FILE, so it is also the one place the
        markup escape belongs.  Five paths reach it with the wearer's own name
        in them -- the menu header, the menu's NAME value, the saved-badges
        list, the delete question and the home preview's footer -- and a sixth
        added tomorrow gets the same protection by construction.  `escaped`
        says what the escape costs and why it is not in the model.
        """
        self._type_ready()
        if pen is not None:
            self.screen.pen = pen
        self.screen.text(
            escaped(message), self.rect(x, y, width, self.row_h),
            font_size=self.chrome.font_size,
            align=align or (self.image.LEFT, self.image.MIDDLE),
            overflow=self.image.ELLIPSES)

    # -- the badge behind everything -----------------------------------------

    def _sync(self, plan, background=None, face=None, name=None):
        """Point the shared poster at this frame's badge.  Mutates no state."""
        badge = plan["badge"]
        # SPELLED OUT rather than aliased to a local, because
        # `test_card_purity.ViewPurityTests` reads this file's AST to prove the
        # view writes into nothing but its own two adapter dicts, and a local
        # alias would hide the target from that check.
        self._pstate["background"] = background or badge["background"]
        self._pstate["face"] = face or badge["face"]
        self._pstate["name"] = badge["name"] if name is None else name
        self._pstate["stickers"] = badge["stickers"]
        self._pplan["animate"] = plan["animate"]
        self._pplan["now"] = plan["now"]
        self._pplan["frame"] = plan["frame"]
        # THE EFFECT IS AN ATTRIBUTE ON THE RENDERER, NOT A FIELD OF THE PLAN,
        # and `shared/poster.Poster.__init__` says why: `identity` calls `worn`
        # with a plan whose state has no such key, and a `KeyError` in a draw
        # path is a reset.  Set every frame rather than on entry, so an APPLY
        # shows on the next paint and a BACK puts it back on the one after.
        #
        # An ATTRIBUTE assignment, which `test_card_purity.ViewPurityTests`
        # permits and a subscript write would not -- the rule there is that the
        # view may not write through the PLAN, and this writes to the renderer
        # the view owns.
        self.poster.effect = plan["effect"]
        return self._pplan

    def _behind(self, plan, name=False, marks_on=True, skip=-1):
        """The badge, then a scrim over the content area.

        `name=False` by default and that is the defect-driven default: the
        poster's name sits at 30% of the canvas, which is behind the second row
        of every list in this app, and text bleeding through a translucent band
        is a thing this repository has already shipped once.
        """
        pplan = self._sync(plan)
        self.poster.badge(pplan, skip=skip, name=name, marks=marks_on)
        self.screen.pen = self.scrim
        self.screen.rectangle(0, 0, self.chrome.width, self.chrome.content_h)

    def _header(self, left, right="", right_pen=None):
        """One line of context, over a denser band, with a hairline under it.

        ALWAYS PRESENT ON AN EDITING SCREEN and never on the resting badge.  It
        is what makes "which badge am I changing" answerable without leaving the
        screen, which on a five-slot app is the question a wearer will actually
        have.
        """
        chrome = self.chrome
        self.screen.pen = self.head
        self.screen.rectangle(0, 0, chrome.width, self.head_h)
        self.screen.pen = self.rule
        self.screen.rectangle(0, self.head_h - self.scale, chrome.width,
                              self.scale)
        self.screen.font = chrome.font
        y = HEAD_PAD * self.scale
        width = chrome.width - 2 * self.text_x
        if right:
            # TWO MARGINS OF CLEARANCE, not one.  With a single margin the
            # title's ellipsis lands hard against the status word and the two
            # read as one string -- `SAVE TO HOME SCREENNOT SET` was exactly
            # that, and it was invisible in the code.
            width -= self._width(right) + 2 * self.text_x
            self._right(right, y, right_pen or self.grey)
        self._bounded(left, self.text_x, y, width, self.accent)
        return self.head_h

    def _rows(self, plan, top, labels, values, marks_pen=None, button=-1):
        """A short list with a right-hand value column.

        The value is what turns five nouns into a status screen: NAME says what
        the name IS, SKIN says which skin, SAVE TO HOME says whether it is on.
        A menu that only names its rows makes the wearer open each one to find
        out what it holds, which on a badge is four presses to learn nothing.

        `button` is the row whose value is an ACTION rather than a state, drawn
        as a filled pill.  The owner asked for exactly this on 2026-08-21 --
        *"can the save to home option just appear as a kind of button? so it's
        more obvious"* -- and the pill is the answer to the "more obvious" half:
        a row that reads `SAVE TO HOME   [SAVE]` offers a press, where
        `SAVE TO HOME   OFF` describes a setting somebody has to go and find.
        Only ONE row may be a button, and -1 is none.
        """
        chrome = self.chrome
        screen = self.screen
        screen.font = chrome.font
        index = plan["index"]
        room = (chrome.content_h - top) // self.row_h
        total = len(labels)
        first = 0
        if index >= room:
            first = index - room + 1
        if first > total - room:
            first = max(0, total - room)
        for offset in range(room):
            position = first + offset
            if position >= total:
                break
            y = top + offset * self.row_h
            chosen = position == index
            if chosen:
                screen.pen = self.accent
                screen.rectangle(0, y, chrome.width - 3 * self.scale,
                                 self.row_h)
            value = values[position] if position < len(values) else ""
            width = chrome.width - 2 * self.text_x
            if value:
                width -= self._width(value) + self.text_x
                value_x = chrome.width - self.text_x - self._width(value)
                if position == button:
                    # THE PILL INVERTS ON THE SELECTED ROW, because the row's
                    # own band is already the accent: an accent pill on an
                    # accent row is an invisible button.  Ink and panel simply
                    # swap, so the control reads the same either way.
                    pad = PILL_PAD * self.scale
                    self.screen.pen = self.black if chosen else self.accent
                    self.screen.rectangle(value_x - pad, y,
                                          self._width(value) + 2 * pad,
                                          self.row_h)
                    self._bounded(value, value_x, y, self._width(value),
                                  self.accent if chosen else self.black)
                else:
                    self._bounded(value, value_x, y, self._width(value),
                                  self.black if chosen
                                  else (marks_pen or self.grey))
            self._bounded(labels[position], self.text_x, y, width,
                          self.black if chosen else self.white)
        # BOTH AFFORDANCES ARE GATED ON THE LIST ACTUALLY SCROLLING.
        # `ui.Chrome.position` draws its rail whenever `total > 1`, which on a
        # five-row menu that fits the panel is two columns of chrome promising
        # movement that cannot happen -- and it lands in the four pixels
        # between the value column and the edge, which is exactly where the eye
        # is already reading.
        if total > room:
            chrome.scroll_hints(True, True)
            chrome.position(index, total)

    def _toast(self, plan):
        """One sentence over the bar, and it is drawn LAST.

        Aligned from the BOTTOM of the content area rather than from the top,
        because `identity` learned that a band aligned from the top cut a
        foot-row screen's third row in half the first time one raised a toast in
        place.
        """
        message = plan["toast"]
        if not message:
            return
        chrome = self.chrome
        y = chrome.content_h - self.row_h
        self.screen.pen = self.band
        self.screen.rectangle(0, y, chrome.width, self.row_h)
        self.screen.pen = self.rule
        self.screen.rectangle(0, y, chrome.width, self.scale)
        self.screen.font = chrome.font
        self._bounded(message, self.text_x, y,
                      chrome.width - 2 * self.text_x, self.accent)

    # -- the frame -----------------------------------------------------------

    def draw(self, plan):
        view = plan["view"]
        if view == model.BADGE:
            self.badge_screen(plan)
            return
        if view == model.MENU:
            self.menu_screen(plan)
        elif view == model.NAME:
            self.name_screen(plan)
        elif view == model.SKIN:
            self.skin_screen(plan)
        elif view == model.EFFECT:
            self.effect_screen(plan)
        elif view == model.MARKS:
            self.marks_screen(plan)
        elif view == model.PICK:
            self.pick_screen(plan)
        elif view == model.PLACE:
            self.place_screen(plan)
        elif view == model.CARDS:
            self.cards_screen(plan)
        elif view == model.CONFIRM:
            self.confirm_screen(plan)
        elif view == model.BAKING:
            self.baking_screen(plan)
        elif view == model.BRIGHT:
            self.bright_screen(plan)
        self._toast(plan)
        # THE BAR IS DRAWN LAST, over everything, because "no content in the
        # band" is unshippable on a canvas this small: something always reaches
        # the bottom thirteen pixels, and a bar underneath it is a bar with a
        # sticker through it.
        labels = plan["labels"]
        if labels[0] or labels[1] or labels[2]:
            # The bar is `shared/ui.Chrome`'s to draw and this app's to set up:
            # "[]ACK" and "()PEN" are two of the six words the owner
            # photographed.  See `_type_ready`.
            self._type_ready()
            self.chrome.bar(labels, ink=self.white, panel=self.band)

    # -- the resting badge ---------------------------------------------------

    def badge_screen(self, plan):
        """D1: at rest the badge is a poster.  Zero chrome, one name.

        `worn` is the whole picture including the empty badge's one line of
        affordance, which is what stops an unconfigured badge being an abstract
        wash with nothing on screen naming a key.
        """
        self.poster.worn(self._sync(plan))

    # THE TWO STAGED ARRIVAL FRAMES, called by the seam and by nothing else.
    # They are the SAME composition with one layer switched off rather than
    # simplified copies of it, which is what makes "the staged picture and the
    # final picture cannot drift" a property of the code rather than a claim.

    def stage_name(self, plan):
        """The name alone, at its final face, size and position.

        Costs the renderer and two leaf tables and no artwork module at all, so
        it is the cheapest frame on which the badge is already readable at a
        metre -- which is most of what a badge is for.
        """
        self.poster.name(self._sync(plan))

    def stage_artwork(self, plan):
        """The artwork behind that name, with the marks not yet drawn.

        THROUGH `worn(hint=False, marks=False)` RATHER THAN `badge(marks=False)`,
        which is the same composition and one thing more: the wearer's effect.
        `hint=False` keeps the affordance line off exactly as `badge()` did, so
        the pixels are unchanged for a badge wearing NONE.

        WHY IT MATTERS THAT THE ARTWORK ARRIVES ALREADY FILTERED.  If the filter
        waited for the first real frame, an `invert` badge would show its
        artwork straight and then flip it a frame later -- a second visible
        event, on the frame after the one the staged arrival exists to make
        smooth.  Filtering here folds it into the arrival of the picture, which
        is a change the eye is already being shown.  `stage_name` is left alone
        deliberately: there is no artwork on it to flatter, and it is the
        latency-critical frame (46-58 ms at HIRES, measured over 160 arrivals).
        """
        self.poster.worn(self._sync(plan), hint=False, marks=False)

    # -- the menu ------------------------------------------------------------

    def menu_screen(self, plan):
        state = plan["state"]
        badge = plan["badge"]
        self._behind(plan)
        slot = "%d/%d" % (state["active"] + 1, len(state["badges"]))
        top = self._header(badge["name"] or "UNNAMED BADGE", slot)
        # THE ROW SAYS WHAT PRESSING IT WILL DO, or that there is nothing to do.
        # `OUT OF DATE` used to live here and the owner removed it by name:
        # *"they don't need to see outdated"*.  A wearer who has edited their
        # badge does not need to be told the wallpaper is behind -- they need a
        # button that says SAVE, which is what a stale film and an absent one
        # both get.  A film that already matches has nothing to offer, so it
        # states the fact and drops the pill.
        home_ready = plan["installed"] and not plan["stale"]
        count = len(badge["stickers"])
        values = (
            badge["name"] or "-",
            catalogue.label(badge["background"]),
            "%d" % count if count else "-",
            "%d OF %d" % (len(state["badges"]), model.MAX_BADGES),
            effects.label(badge["effect"]),
            "ON" if home_ready else model.SAVE,
            # THE WORD, NOT THE NUMBER.  `HIGH` is what the wearer chose and
            # `80` is how the panel is driven; a menu that reported the second
            # would be asking somebody to learn a scale to read a status line.
            backlight.name(plan["brightness"]),
        )
        self._rows(plan, top, model.MENU_ITEMS, values,
                   button=-1 if home_ready
                   else model.MENU_ITEMS.index(model.MENU_HOME))

    # -- the name ------------------------------------------------------------

    def name_screen(self, plan):
        """The QWERTY board, over a plain field.

        NO BADGE BEHIND IT, and that is the one editing screen where the rule is
        broken deliberately: the board is four rows of keys running to the foot
        of the panel with no softkey bar, so there is nothing left to see the
        badge through and an artwork behind 126 cells is noise.  The header
        carries the field's name, the text and the cap instead.
        """
        if plan["board"] is None:
            return
        if self._keyboard is None:
            self._keyboard = card_board.NameBoard(
                self.screen, self.image, self.color, self.font, self.rect)
        self._keyboard.draw(plan)

    # -- the skin browser ----------------------------------------------------

    def skin_screen(self, plan):
        """THE WHOLE BADGE, live, under the entry the wearer is scrubbing.

        This is a preview browser rather than a list, which is `namebadge`'s
        shape and is the right one here for a reason the owner's ruling created:
        the skin now dictates the FACE, so the thing being chosen is the badge's
        whole appearance and not a background.  A list of 105 names
        would be a list of things you cannot see.

        The name is drawn in the CANDIDATE'S face and TRUNCATED to the
        candidate's own cap, so a face that will not fit the wearer's name says
        so here rather than after they commit.
        """
        choice = plan["choice"]
        cap = faces.cap_for(choice, self.chrome.width // self.scale,
                            ceiling=model.NAME_MAX)
        pplan = self._sync(plan, background=choice,
                           face=faces.face_of(choice),
                           name=plan["badge"]["name"][:cap])
        self.poster.badge(pplan)
        chrome = self.chrome
        # ONE BAND, at the foot of the content area: the group and the entry on
        # one line, the position on the other end.  Two rows of chrome over a
        # picture the wearer is judging would be two rows too many.
        y = chrome.content_h - self.row_h
        self.screen.pen = self.band
        self.screen.rectangle(0, y, chrome.width, self.row_h)
        self.screen.pen = self.rule
        self.screen.rectangle(0, y, chrome.width, self.scale)
        self.screen.font = chrome.font
        position = "%d/%d" % (plan["index"] + 1, catalogue.COUNT)
        width = self._width(position)
        self._right(position, y + self.scale, self.grey)
        label = "%s  %s" % (catalogue.group_of(choice, "?"),
                            catalogue.label(choice))
        self._bounded(label, self.text_x, y,
                      chrome.width - 2 * self.text_x - width - self.text_x,
                      self.white)
        chrome.scroll_hints(True, True)
        chrome.position(plan["index"], catalogue.COUNT)

    # -- the effect browser --------------------------------------------------

    def effect_screen(self, plan):
        """THE CARD, WEARING THE HIGHLIGHTED FILTER, under one band of chrome.

        The skin browser's shape, because it is the same kind of question: the
        thing being chosen is how the finished card LOOKS, and a list of fifteen
        words is a list of things you cannot see.

        THROUGH `worn` AND NOT `badge`, which is the whole screen.  `worn` is the
        one place the effect is applied, so routing this preview through it is
        what makes "what you see here is what you will wear" a property of the
        code rather than a second implementation of the filter.  `hint=False`
        because the band below replaces the affordance line in the same pixels.

        AND THE CHROME IS DRAWN AFTER THE FILTER, DELIBERATELY.  `worn` filters
        the panel and then this band lands on top of it unfiltered, so the label
        stays legible under `INK`, `INVERT` and `ONE BIT` -- three filters that
        would otherwise make the control for turning them off unreadable.  On
        the WORN badge there is no chrome at all (D1), so full-card there really
        is the full card; here the wearer needs one thing that is not filtered,
        and it is the thing they are pressing.
        """
        self.poster.worn(self._sync(plan), hint=False)
        chrome = self.chrome
        y = chrome.content_h - self.row_h
        self.screen.pen = self.band
        self.screen.rectangle(0, y, chrome.width, self.row_h)
        self.screen.pen = self.rule
        self.screen.rectangle(0, y, chrome.width, self.scale)
        self.screen.font = chrome.font
        position = "%d/%d" % (plan["index"] + 1, effects.COUNT)
        width = self._width(position)
        self._right(position, y + self.scale, self.grey)
        self._bounded(effects.label(plan["effect"]), self.text_x, y,
                      chrome.width - 2 * self.text_x - width - self.text_x,
                      self.white)
        chrome.scroll_hints(True, True)
        chrome.position(plan["index"], effects.COUNT)

    # -- the stickers --------------------------------------------------------

    def marks_screen(self, plan):
        """The badge, then the list, with the SELECTED mark ringed on it.

        The ring is drawn on the badge rather than only in the list because a
        list of nine `SUPABASE` rows is nine identical rows: the only way to say
        WHICH one is to point at it on the picture.
        """
        badge = plan["badge"]
        stickers = badge["stickers"]
        selected = plan["index"] - 1
        self._behind(plan)
        if 0 <= selected < len(stickers):
            self._ring(stickers[selected], self.accent)
        top = self._header("STICKERS", "%d/%d" % (len(stickers),
                                                  model.MAX_STICKERS))
        labels = ["+  ADD A STICKER"]
        values = [""]
        for mark in stickers:
            labels.append(marks.label(mark["kind"]))
            values.append("")
        self._rows(plan, top, labels, values)

    def _outline(self, x, y, width, height, pen):
        """A hollow rectangle `self.ring` thick.  Four fills, never a plate.

        HOLLOW AND NOT FILLED, everywhere it is used, because a filled cell
        behind a mark hides the mark: twelve of the 116 are emerald or near it
        (`supabase`, `node-js`, `mongodb`, `vim`, `neovim`, `vue-js`, `nginx`,
        `nvidia`, `android`, `upstash`, `nuxt`, `vitest`), and an emerald sticker
        on an emerald plate is an empty box.  The count used to read "a good
        third of the 69", which was never true of any sheet -- it is one in ten,
        which is still enough for the rule.
        """
        self.screen.pen = pen
        self.screen.rectangle(x, y, width, self.ring)
        self.screen.rectangle(x, y + height - self.ring, width, self.ring)
        self.screen.rectangle(x, y, self.ring, height)
        self.screen.rectangle(x + width - self.ring, y, self.ring, height)

    def _ring(self, mark, pen):
        """A hollow ring around one placed mark, on the badge behind the list.

        Drawn AFTER the scrim, so the scrim cannot dim it -- `identity` shipped
        exactly that bug: the selected mark's ring was dimmed by the same band
        that made the list readable, which is most of the badge.
        """
        cell_w, cell_h = self.poster.mark_w, self.poster.mark_h
        x, y = poster_module.mark_origin(mark["x"], mark["y"],
                                         self.chrome.width,
                                         self.chrome.height, cell_w, cell_h)
        self._outline(x - self.ring, y - self.ring, cell_w + 2 * self.ring,
                      cell_h + 2 * self.ring, pen)

    def pick_screen(self, plan):
        """A three-cell filmstrip hard against the right edge, and a title.

        THE SELECTED CELL IS CENTRED BETWEEN THE TWO PHYSICAL SCROLL KEYS, at
        `(scroll_y[0] + scroll_y[1]) / 2`, so the thing that moves is level with
        the thumb that moves it.  `namebadge`'s geometry, and the adjacency is
        the whole affordance.
        """
        self._behind(plan)
        chrome = self.chrome
        top = self._header("CHOOSE A STICKER",
                           "%d/%d" % (plan["pick"] + 1, marks.COUNT))
        cell_w, cell_h = self.poster.mark_w, self.poster.mark_h
        strip_x = chrome.width - cell_w - 5 * self.scale
        centre = (chrome.scroll_y[0] + chrome.scroll_y[1]) // 2 - cell_h // 2
        for offset in range(-(self.strip_cells // 2),
                            self.strip_cells // 2 + 1):
            index = (plan["pick"] + offset) % marks.COUNT
            y = centre + offset * (cell_h + 2 * self.scale)
            if offset == 0:
                self._outline(strip_x - self.ring, y - self.ring,
                              cell_w + 2 * self.ring, cell_h + 2 * self.ring,
                              self.accent)
            self.poster.mark(marks.MARKS[index][0],
                             (strip_x + cell_w / 2.0) / chrome.width,
                             (y + cell_h / 2.0) / chrome.height,
                             plan["now"])
        mark = marks.MARKS[plan["pick"]]
        y = top + self.row_h
        self.screen.font = chrome.font
        self._bounded(mark[1], self.text_x, y,
                      strip_x - 2 * self.text_x, self.white)
        note = "ANIMATED" if mark[3] > 1 else "STILL"
        self._bounded(note, self.text_x, y + self.row_h,
                      strip_x - 2 * self.text_x, self.grey)

    def place_screen(self, plan):
        """The badge with the mark under the cursor, and marching ants round it.

        MARCHING ANTS WITH A BLACK KEYLINE, not a plain white box: fifteen of
        the THEN-76 backgrounds were pale enough that a white marquee disappeared
        entirely, which a contact sheet found and a code review did not.  That
        count is evidence from the 76-entry catalogue and has NOT been
        re-measured against 105; the keyline is unconditional, so the number
        informs nothing at runtime.  The dashes also MOVE, which is what tells the wearer the thing
        under them is the thing the keys are driving.

        The mark being moved is passed to the renderer as `skip`, so an existing
        mark is not drawn twice -- without it a move reads as a duplicate.
        """
        pplan = self._sync(plan)
        self.poster.badge(pplan, skip=plan["editing"])
        fx, fy = plan["place"]
        if plan["editing"] >= 0:
            kind = plan["badge"]["stickers"][plan["editing"]]["kind"]
        else:
            kind = marks.MARKS[plan["pick"]][0]
        self.poster.mark(kind, fx, fy, plan["now"])
        cell_w, cell_h = self.poster.mark_w, self.poster.mark_h
        x, y = poster_module.mark_origin(fx, fy, self.chrome.width,
                                         self.chrome.height, cell_w, cell_h)
        self._ants(x - self.ring, y - self.ring, cell_w + 2 * self.ring,
                   cell_h + 2 * self.ring, plan["now"])

    def _ants(self, x, y, width, height, now_ms):
        screen = self.screen
        phase = (now_ms // 90) % (2 * self.dash)
        screen.pen = self.black
        screen.rectangle(x - self.scale, y - self.scale,
                         width + 2 * self.scale, self.scale)
        screen.rectangle(x - self.scale, y + height,
                         width + 2 * self.scale, self.scale)
        screen.rectangle(x - self.scale, y, self.scale, height)
        screen.rectangle(x + width, y, self.scale, height)
        screen.pen = self.white
        step = 2 * self.dash
        for offset in range(-step, width + step, step):
            at = x + offset + phase
            run = _span(at, self.dash, x, x + width)
            if run:
                screen.rectangle(run[0], y, run[1], self.scale)
                screen.rectangle(run[0], y + height - self.scale, run[1],
                                 self.scale)
        for offset in range(-step, height + step, step):
            at = y + offset + phase
            run = _span(at, self.dash, y, y + height)
            if run:
                screen.rectangle(x, run[0], self.scale, run[1])
                screen.rectangle(x + width - self.scale, run[0], self.scale,
                                 run[1])

    # -- the saved badges ----------------------------------------------------

    def cards_screen(self, plan):
        state = plan["state"]
        self._behind(plan)
        top = self._header("YOUR BADGES", "%d/%d" % (len(state["badges"]),
                                                     model.MAX_BADGES))
        labels = []
        values = []
        for position in range(len(state["badges"])):
            entry = state["badges"][position]
            labels.append(entry["name"] or "UNNAMED")
            if position == state["active"]:
                values.append("WEARING")
            else:
                values.append(catalogue.label(entry["background"]))
        if len(state["badges"]) < model.MAX_BADGES:
            labels.append("+  NEW BADGE")
            values.append("")
        self._rows(plan, top, labels, values)

    def confirm_screen(self, plan):
        """One question, centred, with the consequence spelled out.

        THE NAME OF THE THING BEING DELETED IS IN THE QUESTION.  "Are you sure?"
        is a dialog a thumb dismisses; "DELETE SAM MEECH?" is a sentence it
        reads.  B is inert here and the bar says so by leaving its slot empty
        rather than filling it with a word.
        """
        state = plan["state"]
        chrome = self.chrome
        self._behind(plan)
        doomed = plan["doomed"]
        badges = state["badges"]
        name = "UNNAMED"
        if 0 <= doomed < len(badges):
            name = badges[doomed]["name"] or "UNNAMED"
        last = len(badges) == 1
        lines = (
            "DELETE" if not last else "RESET",
            name,
            "" if not last else "",
            "IT CANNOT BE BROUGHT BACK" if not last
            else "THIS IS YOUR ONLY BADGE, SO IT",
            "" if not last else "GOES BACK TO A BLANK ONE",
        )
        height = self.row_h * len([line for line in lines if line]) \
            + 4 * self.scale
        y = (chrome.content_h - height) // 2
        self.screen.pen = self.plate
        self.screen.rectangle(0, y, chrome.width, height)
        self.screen.pen = self.red
        self.screen.rectangle(0, y, chrome.width, self.scale)
        self.screen.rectangle(0, y + height - self.scale, chrome.width,
                              self.scale)
        self.screen.font = chrome.font
        row = y + 2 * self.scale
        pens = (self.red, self.white, None, self.grey, self.grey)
        for index in range(len(lines)):
            if not lines[index]:
                continue
            self._bounded(lines[index], self.text_x, row,
                          chrome.width - 2 * self.text_x, pens[index],
                          align=(self.image.CENTER, self.image.MIDDLE))
            row += self.row_h

    # -- brightness -----------------------------------------------------------

    def bright_screen(self, plan):
        """The ladder, over the wearer's own badge.

        THE BADGE IS BEHIND IT ON PURPOSE, where a settings screen would
        normally draw over a plate: brightness is the one setting whose effect
        is not on the screen but IN it, so the wearer has to be looking at their
        own artwork at their own brightness to judge it.  The scrim `_behind`
        applies is the same one every list screen uses, so what moves between
        rungs is the PANEL rather than the picture.

        FIVE PIPS AND A WORD.  The pips are the ladder made visible -- five
        rungs, the current one filled, so "how much further can this go" is
        answered without pressing anything, which is what the softkey labels
        cannot do (they name the next value in each direction and nothing
        beyond).  The word is the same one the menu row shows, so the two
        screens agree by construction.
        """
        chrome = self.chrome
        percent = plan["brightness"]
        self._behind(plan)
        top = self._header(model.MENU_BRIGHT, "%d%%" % percent)
        levels = backlight.LEVELS
        # The pip row, centred in the content area under the header.
        pip = self.row_h - 2 * self.scale
        gap = pip // 2
        span = len(levels) * pip + (len(levels) - 1) * gap
        x = (chrome.width - span) // 2
        y = top + (chrome.content_h - top - pip - self.row_h) // 2
        for level in levels:
            filled = level <= percent
            self.screen.pen = self.accent if filled else self.rule
            self.screen.rectangle(x, y, pip, pip)
            if not filled:
                # An outline rather than a fill, so an unreached rung reads as a
                # place the ladder can still go rather than as a dead cell.
                self.screen.pen = self.plate
                self.screen.rectangle(x + self.scale, y + self.scale,
                                      pip - 2 * self.scale,
                                      pip - 2 * self.scale)
            x += pip + gap
        self.screen.font = chrome.font
        self._bounded(backlight.name(percent), self.text_x, y + pip + self.scale,
                      chrome.width - 2 * self.text_x, self.white,
                      align=(self.image.CENTER, self.image.MIDDLE))

    # -- the wallpaper's progress modal ---------------------------------------

    def baking_screen(self, plan):
        """The modal, with a bar driven by REAL step counts.

        Never an animated fake: a progress bar that moves on a timer while the
        work is stalled is worse than no bar, because it is a lie the wearer
        cannot detect.  `plan["progress"]` is `index / steps` on the job itself.
        """
        chrome = self.chrome
        self._behind(plan)
        height = self.row_h * 3 + 6 * self.scale
        y = (chrome.content_h - height) // 2
        self.screen.pen = self.plate
        self.screen.rectangle(0, y, chrome.width, height)
        self.screen.pen = self.accent
        self.screen.rectangle(0, y, chrome.width, self.scale)
        self.screen.font = chrome.font
        self._bounded("SAVING TO HOME SCREEN", self.text_x,
                      y + 2 * self.scale, chrome.width - 2 * self.text_x,
                      self.white, align=(self.image.CENTER, self.image.MIDDLE))
        self._bounded(plan["stage"], self.text_x,
                      y + 2 * self.scale + self.row_h,
                      chrome.width - 2 * self.text_x, self.grey,
                      align=(self.image.CENTER, self.image.MIDDLE))
        rail = chrome.width - 4 * self.text_x
        bar_y = y + 4 * self.scale + 2 * self.row_h
        self.screen.pen = self.color.rgb(255, 255, 255, 50)
        self.screen.rectangle(2 * self.text_x, bar_y, rail, 2 * self.scale)
        self.screen.pen = self.accent
        self.screen.rectangle(2 * self.text_x, bar_y,
                              int(rail * plan["progress"]), 2 * self.scale)


def _span(at, length, low, high):
    """Clip one dash to a run.  `(x, width)`, or None when it falls outside."""
    start = at
    end = at + length
    if start < low:
        start = low
    if end > high:
        end = high
    if end <= start:
        return None
    return (start, end - start)
