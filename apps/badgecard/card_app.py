"""The controller.  Pure: `frame(now_ms, buttons) -> plan`, and nothing else.

WHAT PURE MEANS HERE, precisely, because it is the property the whole test lane
rests on: this module reads no clock, opens no file, and names no Badgeware
global.  The clock arrives as an argument, input arrives as an object with
`pressed(key)` and `held(key)`, persistence arrives as an injected callable, and
the wallpaper baker arrives as three more.  `badgecard/tests/test_card_purity.py`
walks this file's AST and fails if it ever imports anything but `card_model`,
`card_faces`, the two catalogues and `ui` -- and from `ui` it may name only
`Repeat` and `Saver`, which are the two pure classes in that module.
(`backlight` was on that list from 2026-08-23 to 2026-08-24, for the BRIGHTNESS
row; the owner moved that row to `settings`, so this controller no longer names
the ladder at all.  The `brightness` FIELD is still in `card_model`'s schema --
it is the one store every reader shares -- and this module simply never touches
it.)

`identity` proves the shape works: its controller is pure enough that a
four-figure test count runs on CPython in seconds, and every one of those tests
is a defect that cannot reach the badge.

THE PLAN IS THE WHOLE INTERFACE.  The view reads it and mutates nothing; this
module mutates state and draws nothing.  Neither can be wrong about the other in
a way a test cannot see, because the thing between them is a dict.
"""

import card_faces as faces
import card_model as model
import effects
import identity_catalogue as catalogue
import identity_keyboard as keyboard
import identity_marks as marks
import kbqwerty_board as board
import ui


# HOW LONG THE SKIN BROWSER WAITS BEFORE IT RASTERISES.  B5: scrub cheap, settle
# late.  Held between the repeat curve's two speeds so a key held down never
# rasterises at all and a single tap always does -- 180 is greater than
# `ui.REPEAT_SLOW_MS` (150) and less than `ui.REPEAT_DELAY_MS` (350), and
# `badgecard/tests/test_card_skin.py` asserts that ORDERING against those two
# constants rather than against the literal, so retuning the curve cannot
# silently turn a 76-entry scrub into 76 full-screen rasterises.
SETTLE_MS = 180

# How long a toast stays up.  Long enough to read four words at arm's length,
# short enough that it is gone before the next press lands.
TOAST_MS = 1200

# The wearer-facing sentences.  Here rather than in the view because the
# controller is what decides WHICH one, and a string constant beside the branch
# that raises it is one the browser lane can assert on.
SAVED = "SAVED"
FULL = "NAME FULL"
EMPTY = "NOTHING TO DELETE"
MARK_ADDED = "STICKER ADDED"
MARK_GONE = "STICKER REMOVED"
MARK_FULL = "24 STICKERS MAX"
# WHAT THE RESET SAYS WHEN IT LANDS.  `CARD_NEW`, `CARD_GONE`, `CARD_WORN` and
# `CARD_FULL` left with the five slots on 2026-08-24; this is the one sentence
# that replaces all four, because there is one card and one thing to do to it.
CARD_RESET = "BADGE RESET"
HOME_ON = "HOME SCREEN SET"
HOME_OFF = "HOME SCREEN CLEARED"
HOME_FAILED = "COULD NOT SAVE"

# The five keys, in the order the drain checks them.
KEYS = ("A", "B", "C", "UP", "DOWN")


class CardApp:
    """One badge editor.  Construct it with state and five callables.

    `write(state, milestone=False)` is the ONLY persistence this class can
    perform, and it is handed in rather than imported so the fast lane can pass
    a list's `append` and assert exactly which presses commit.  `bake`, `unbake`
    and `recipe` are the wallpaper baker's three entry points, injected for the
    same reason and one stronger: the baker is the one impure module in the app
    -- it draws pixels and writes a file -- and reaching it through a callable
    is what keeps this class runnable with no rasteriser at all.
    """

    def __init__(self, state, write, bake=None, unbake=None, recipe=None,
                 now_ms=0, load_status="loaded", ticks_diff=None,
                 logical=(0, 0)):
        self.state = state
        self._write = write
        self._bake = bake
        self._unbake = unbake
        self._recipe = recipe
        # THERE IS NO PANEL CALLABLE HERE ANY MORE.  One was injected from
        # 2026-08-23 to 2026-08-24 so the BRIGHTNESS row could reach real
        # hardware without making this class impure; the owner moved that row to
        # `settings`, so the seam's `idle.Panel` is now the only thing in this
        # app that writes the backlight -- at open, and on the idle dim.
        self._diff = ticks_diff if ticks_diff is not None else _plain_diff
        self.load_status = load_status

        # THE LOGICAL CANVAS, handed in by the seam as `chrome.width //
        # chrome.scale`.  A logical pixel is 0.375 mm at BOTH resolutions, so
        # this is the same 160x120 either way and the placement step below is a
        # PHYSICAL quantity that survives the flip.  Injected rather than
        # written down because `docs/design/constraints.md` forbids a literal
        # screen size anywhere, and because a test that passes the real chrome's
        # numbers is a test that would catch the day that stops being true.
        self.logical_w = logical[0] or _DEFAULT_LOGICAL[0]
        self.logical_h = logical[1] or _DEFAULT_LOGICAL[1]

        self.view = model.BADGE
        self.previous = model.BADGE
        self.index = 0
        self.exit = False
        self.frames = 0
        self.events = []

        # THE FIRST PRESS OPENS THE MENU AND DOES NOTHING ELSE.  `badge.pressed`
        # is an edge against the previous poll, and the previous poll at boot is
        # empty, so the launcher press that started this app is still live on
        # frame one.  Held until every key is seen up, which is M1's drain
        # applied to the resting screen.
        self._blocked = True

        self._toast = ""
        self._toast_at = 0

        # ONE REPEAT PAIR PER AXIS PER TUNING.  `ui.Repeat` rather than
        # `ui.Axis` because `Axis` reads `badge.held()` inside itself and a
        # controller built on it cannot be stepped off the device at all --
        # `identity_keyboard`'s docstring records the same choice for the same
        # reason.  The subtraction of two Repeats IS the axis.
        self._up = ui.Repeat()
        self._down = ui.Repeat()
        # The placement keys get the aggressive curve, because a mark is dragged
        # across a whole canvas rather than stepped down a list of five rows.
        self._place_up = ui.Repeat(ui.PLACE_REPEAT)
        self._place_down = ui.Repeat(ui.PLACE_REPEAT)
        self._place_left = ui.Repeat(ui.PLACE_REPEAT)
        self._place_right = ui.Repeat(ui.PLACE_REPEAT)
        self._suppress()

        # -- per-screen scratch, all of it navigation and none of it persisted
        self.board = None
        self.choice = ""
        self.choice_at = 0
        self.settled = True
        self.restore = ""
        self.pick = 0
        self.place_x = model.RECIPE_UNITS // 2
        self.place_y = model.RECIPE_UNITS // 2
        self.editing = -1
        # `self.doomed` LEFT WITH THE CARDS SCREEN (2026-08-24).  It held which
        # of five saved badges a confirmation was about, and the confirmation is
        # now about the only card there is -- so the screen needs no subject, and
        # a stale index can no longer point the destructive press at the wrong
        # badge.  `test_card_cards.test_a_confirmation_reached_with_a_stale_index
        # _cannot_delete` existed for exactly that failure; the field it guarded
        # is gone, so the failure is unrepresentable rather than merely tested.
        self.job = None
        # THE EFFECT BEING PREVIEWED, and the one to put back on BACK.  A pair
        # of its own rather than a reuse of `choice`/`restore`: those hold a
        # background entry id, the two browsers can be entered one after the
        # other, and a single slot holding "sometimes a skin, sometimes a
        # filter" is the shape that puts a filter id into `badge["background"]`
        # on the frame somebody adds a screen.
        #
        # NO `settled` COUNTERPART, and B5 is why rather than an exception to
        # it. Settling exists to keep an expensive representation off a scrubbed
        # frame; here the expensive thing is the ARTWORK, the filter runs over
        # whatever `advance()` already has cached, and every shipped filter is
        # under one 11.43 ms quantum. There is no cheap-and-expensive pair to
        # choose between, so the preview is simply live.
        self.effect = effects.NONE
        self.effect_was = effects.NONE

        # THE FILM'S RECIPE, memoised on the parts tuple.  `home_stale` is asked
        # once a frame on the HOME screen and the answer cannot move unless the
        # badge does, so hashing 70-odd parts every frame would be paying for an
        # answer that is already known.
        self._recipe_parts = None
        self._recipe_value = 0

        # A store that did not load cleanly is written back at once, so the next
        # boot reads a good file rather than recovering again.  A milestone,
        # because it is the only write that has happened and `.bak` should hold
        # it.
        if load_status != "loaded":
            self._commit(milestone=True)

    # -- small helpers -------------------------------------------------------

    def badge(self):
        return model.active(self.state)

    def _suppress(self):
        """Block every repeat, so the press that opened a screen cannot act.

        A `ui.Repeat` that is never stepped stays blocked and then eats the
        wearer's first real press, which is why every one of them is blocked
        together and stepped together rather than lazily.
        """
        self._up.block()
        self._down.block()
        self._place_up.block()
        self._place_down.block()
        self._place_left.block()
        self._place_right.block()

    def _goto(self, view):
        self.previous = self.view
        self.view = view
        self.index = 0
        self._suppress()
        self.events.append(view)

    def _menu_at(self, row):
        """Back to the menu, SELECTION ON `row` rather than on the top of it.

        THREE SCREENS NEEDED THIS AND THE FIRST TWO EACH WROTE IT OUT.  `_goto`
        resets `index` to 0, which is right for a list somebody navigated INTO
        and wrong for every return: the browser lane caught it as "the press
        after a save opened NAME", `_route_effect` hit the same thing, and the
        reset confirmation would have hit it a third time.  A helper, because the
        bug is not that the line is long -- it is that it is EASY TO OMIT, and
        the omission looks like a working screen.
        """
        self._goto(model.MENU)
        self.index = model.MENU_ITEMS.index(row)

    def _toast_now(self, now_ms, message):
        self._toast = message
        self._toast_at = now_ms

    def _commit(self, milestone=False):
        """Write, and mark the film stale by forgetting the memo.

        Every commit goes through here.  That is what makes "a navigation press
        never persists" (B6) checkable: the tests count calls to the injected
        writer, and a screen that scrolled without committing has made none.
        """
        self._recipe_parts = None
        self._write(self.state, milestone)
        self.events.append("save")

    def _scroll(self, now_ms, buttons):
        step = self._down.step(buttons.held("DOWN"), now_ms)
        return step - self._up.step(buttons.held("UP"), now_ms)

    def _move(self, step, total):
        """Move the list selection, WRAPPING at both ends.  B3.

        Wrapping is what makes the last row one press from the first, which on a
        five-row menu is the difference between one press and four.
        """
        if not total:
            self.index = 0
            return
        self.index = (self.index + step) % total

    # -- the wallpaper's staleness ------------------------------------------

    def home_recipe(self):
        """The stamp the badge as it stands now would bake.  Memoised."""
        if self._recipe is None:
            return 0
        parts = model.recipe_parts(self.state)
        if parts != self._recipe_parts:
            self._recipe_parts = parts
            self._recipe_value = self._recipe(parts)
        return self._recipe_value

    def home_installed(self):
        return bool(self.state["home"].get("on"))

    def home_stale(self):
        """Is the installed film a picture of a badge that no longer exists?

        Never stale when nothing is installed: there is no film to disagree with
        the badge, and offering to UPDATE something that is not there would be a
        label that lies.
        """
        if not self.home_installed():
            return False
        return self.state["home"].get("recipe") != self.home_recipe()

    # -- the frame -----------------------------------------------------------

    def frame(self, now_ms, buttons):
        self.frames += 1
        # CLEARED AT THE TOP OF EVERY FRAME, so `events` is what happened in
        # THIS one.  A list that accumulated for a session would grow without
        # bound on a badge, and it would also make the natural test assertion
        # -- tap, then read -- silently vacuous, which this repository has
        # shipped before as `assertIn("erased", ["erased"])`.
        self.events = []
        if self._blocked:
            down = False
            for key in KEYS:
                if buttons.held(key):
                    down = True
                    break
            if down:
                return self.plan(now_ms)
            self._blocked = False

        if self._toast and self._diff(now_ms, self._toast_at) >= TOAST_MS:
            self._toast = ""

        view = self.view
        if view == model.BADGE:
            self._route_badge(now_ms, buttons)
        elif view == model.MENU:
            self._route_menu(now_ms, buttons)
        elif view == model.NAME:
            self._route_name(now_ms, buttons)
        elif view == model.SKIN:
            self._route_skin(now_ms, buttons)
        elif view == model.MARKS:
            self._route_marks(now_ms, buttons)
        elif view == model.PICK:
            self._route_pick(now_ms, buttons)
        elif view == model.PLACE:
            self._route_place(now_ms, buttons)
        elif view == model.CONFIRM:
            self._route_confirm(now_ms, buttons)
        elif view == model.BAKING:
            self._route_baking(now_ms, buttons)
        elif view == model.EFFECT:
            self._route_effect(now_ms, buttons)
        return self.plan(now_ms)

    # -- the resting badge ---------------------------------------------------

    def _route_badge(self, now_ms, buttons):
        """D1: the resting screen draws zero chrome and the first press wakes it.

        WAKE AND DO NOTHING ELSE.  Every key opens the menu and none of them
        fires the command it will be labelled with there, which is the half of
        wake-and-fire that I5 actually forbids -- a thumb that started moving
        while the panel said nothing must not commit anything.
        """
        for key in KEYS:
            if buttons.pressed(key):
                self._goto(model.MENU)
                return

    # -- the menu ------------------------------------------------------------

    def _route_menu(self, now_ms, buttons):
        step = self._scroll(now_ms, buttons)
        if step:
            self._move(step, len(model.MENU_ITEMS))
        if buttons.pressed("A"):
            self._goto(model.BADGE)
            return
        if (buttons.pressed("C")
                and model.MENU_ITEMS[self.index] == model.MENU_HOME):
            # CLEAR, on the row's own C key.  No confirmation, and that is B7
            # applied rather than skipped: the film is a CACHE of the badge --
            # one press of SAVE puts it back, and `card_bake` says the same
            # ("it is regenerated from the badge app in two presses, so a
            # launcher that quietly ignores a bad one loses nothing").  A badge
            # is what gets a confirmation; its wallpaper is not.
            self._clear_home(now_ms)
            return
        if not buttons.pressed("B"):
            return
        row = model.MENU_ITEMS[self.index]
        if row == model.MENU_NAME:
            self._edit_name()
        elif row == model.MENU_SKIN:
            self._browse_skin()
        elif row == model.MENU_MARKS:
            self._goto(model.MARKS)
        elif row == model.MENU_EFFECT:
            self._browse_effect()
        # EXPLICIT, WHERE THIS USED TO BE A BARE `else`.  With five rows the
        # fall-through was unambiguous; with more an unhandled row would have
        # SAVED THE WALLPAPER, which is the loudest wrong answer available -- and
        # the menu has now gained and lost a row twice, which is exactly the
        # churn a bare `else` turns into a silent bake.  The stakes went up again
        # on 2026-08-24: the row that a fall-through would reach LAST is the one
        # that resets the badge, so an unhandled row must land nowhere at all.
        elif row == model.MENU_HOME:
            self._save_home(now_ms)
        elif row == model.MENU_RESET:
            # OPENING A QUESTION, NOT ANSWERING ONE.  Every other destructive
            # thing in this app is one press from done; this is the one that is
            # two screens from done, and B7 is why (`docs/badge-button-rules.md`
            # §5).  Nothing is written here -- `_route_confirm` is the only
            # place a reset can happen, and the tests count writes to prove it.
            self._goto(model.CONFIRM)

    # -- the name ------------------------------------------------------------

    def name_cap(self):
        """How many characters the CURRENT skin's face fits, capped at 12.

        The owner's ruling made visible in the one place a wearer meets it: pick
        a skin whose face is `futile` (widest glyph 19 px) and the field holds
        eight characters; pick one whose face is `winds` (6 px) and it holds the
        full twelve.  The name is not being arbitrarily shortened -- it is being
        held to what will actually fit on the badge at a readable size.
        """
        return faces.cap_for(self.badge()["background"], self.logical_w,
                             ceiling=model.NAME_MAX)

    def _edit_name(self):
        # BUILT FROM THE STORED TEXT, so BACK genuinely abandons: nothing in
        # `state` moves until DONE.
        #
        # `board.Model` rather than `PlaneModel` directly, because that function
        # IS the cold start: it calls `reset()` first, which puts the published
        # mirror back to LETTERS/uppercase.  Without it the playground -- where
        # app modules stay resident between launches, unlike hardware, where
        # `launch()` deletes them -- would hand the next session whichever plane
        # and case the last one ended on.  On a keyboard whose whole premise is
        # that a badge name is usually capitals.
        self.board = board.Model(text=self.badge()["name"],
                                 limit=self.name_cap())
        self._goto(model.NAME)

    def _route_name(self, now_ms, buttons):
        board = self.board
        if board is None:
            # There is no legitimate route here without a board, but a screen
            # that raises `AttributeError` is a screen with no way out at all,
            # and I2 is not conditional on the app being correct.
            self._goto(model.MENU)
            return
        step = self._scroll(now_ms, buttons)
        if step:
            board.move_row(step)
        if buttons.pressed("A"):
            board.move_column(-1)
        if buttons.pressed("C"):
            board.move_column(1)
        if not buttons.pressed("B"):
            return
        outcome = board.press()
        if outcome == keyboard.COMMITTED:
            self.badge()["name"] = board.text
            self._commit(milestone=True)
            self._goto(model.MENU)
            self._toast_now(now_ms, SAVED)
        elif outcome == keyboard.ABANDONED:
            # I2's route out that COMMITS NOTHING.
            self._goto(model.MENU)
        elif outcome == keyboard.REFUSED:
            # The one outcome the wearer has to be told about: a full field that
            # silently eats presses is how a name is truncated without anybody
            # noticing.
            self._toast_now(now_ms, FULL if board.full() else EMPTY)

    # -- the skin browser ----------------------------------------------------

    def _browse_skin(self):
        current = self.badge()["background"]
        self.restore = current
        self.choice = current
        self.settled = True
        self._goto(model.SKIN)
        index = catalogue.index_of(current)
        self.index = index if index >= 0 else 0

    def _route_skin(self, now_ms, buttons):
        step = self._scroll(now_ms, buttons)
        if step:
            self._move(step, catalogue.COUNT)
            self._retarget(now_ms)
        if buttons.pressed("C"):
            # JUMP: the first entry of the NEXT group, wrapping.  Thirteen groups
            # against 105 entries, so this is the difference between one press
            # and eighty-seven to reach the glyph decks.
            group = catalogue.group_of(self.choice, catalogue.GROUPS[0])
            following = catalogue.next_group(group)
            index = catalogue.index_of(catalogue.first_of_group(following))
            self.index = index if index >= 0 else 0
            self._retarget(now_ms)
        if buttons.pressed("A"):
            # BACK RESTORES.  Browsing is navigation, and navigation never
            # persists (B6) -- but the badge behind the list has been showing
            # the highlighted artwork the whole time, so leaving without putting
            # it back would look like a commit that did not save.
            self.choice = self.restore
            self.settled = True
            self._goto(model.MENU)
            return
        if not buttons.pressed("B"):
            # SETTLE.  The choice moved, then the wearer stopped; only now is it
            # worth rasterising, and `settled` is what tells the view so.
            if not self.settled and self._diff(now_ms, self.choice_at) >= SETTLE_MS:
                self.settled = True
            return
        badge = self.badge()
        badge["background"] = self.choice
        # THE FACE FOLLOWS THE SKIN.  The owner's ruling, applied at the one
        # point it can be applied: the moment the skin is chosen.
        badge["face"] = faces.face_of(self.choice)
        # AND THE NAME IS RE-CAPPED, because the new face may be wider.  Cutting
        # it here rather than at draw time is what stops the badge and the
        # editor disagreeing about what the wearer's name is.
        cap = self.name_cap()
        if len(badge["name"]) > cap:
            badge["name"] = badge["name"][:cap]
        self._commit(milestone=True)
        self._goto(model.MENU)
        self._toast_now(now_ms, SAVED)

    def _retarget(self, now_ms):
        entry = catalogue.ENTRIES[self.index][0]
        if entry != self.choice:
            self.choice = entry
            self.choice_at = now_ms
            self.settled = False

    # -- the effect browser --------------------------------------------------

    def _browse_effect(self):
        """Open on what the badge is wearing, or on NONE if it is unknown.

        `effects.index_of` answers 0 for an id this build does not carry, so a
        badge configured on a newer build opens the row on NONE rather than on
        nothing. The unknown id stays in `badge["effect"]` until the wearer
        presses APPLY over it, which is rule 3 of the schema: the DATA survives
        a downgrade even when the feature does not.
        """
        current = self.badge()["effect"]
        self.effect_was = current
        self.effect = current
        self._goto(model.EFFECT)
        self.index = effects.index_of(current)

    def _route_effect(self, now_ms, buttons):
        """B3 browse: UP/DOWN by one with wrap, B commits, A restores.

        THE PREVIEW IS THE BADGE ITSELF, filtered, with the list over it -- the
        same shape as the skin browser, and for the same reason the owner gave
        there: a list of names is a list of things you cannot see. Which means
        the card behind this list is drawn through the HIGHLIGHTED effect and
        not through the saved one, so moving the selection IS the preview and
        the wearer never has to commit to find out.
        """
        step = self._scroll(now_ms, buttons)
        if step:
            self._move(step, effects.COUNT)
            self.effect = effects.SHIPPED[self.index][0]
        if buttons.pressed("A"):
            # BACK RESTORES, B6.  Browsing is navigation and navigation never
            # persists -- and the card behind the list has been wearing the
            # highlighted filter the whole time, so leaving without putting it
            # back would look like a commit that did not save.
            self.effect = self.effect_was
            self._menu_at(model.MENU_EFFECT)
            return
        if not buttons.pressed("B"):
            return
        self.badge()["effect"] = self.effect
        # A MILESTONE, like the skin.  It is a visible property of the card the
        # wearer chose deliberately, so it belongs in the `.bak` that a corrupt
        # save falls back to; the alternative is a recovery that silently drops
        # the one thing they had just changed.
        self._commit(milestone=True)
        # RETURN THE SELECTION TO THE ROW IT CAME FROM -- see `_menu_at`.
        self._menu_at(model.MENU_EFFECT)
        self._toast_now(now_ms, SAVED)

    # -- the stickers --------------------------------------------------------

    def mark_rows(self):
        """One ADD row, then one row per sticker on the badge."""
        return len(self.badge()["stickers"]) + 1

    def _route_marks(self, now_ms, buttons):
        step = self._scroll(now_ms, buttons)
        if step:
            self._move(step, self.mark_rows())
        if buttons.pressed("A"):
            self._goto(model.MENU)
            return
        stickers = self.badge()["stickers"]
        if buttons.pressed("B"):
            if self.index == 0:
                if len(stickers) >= model.MAX_STICKERS:
                    self._toast_now(now_ms, MARK_FULL)
                    return
                self.editing = -1
                self.pick = 0
                self._goto(model.PICK)
            else:
                self.editing = self.index - 1
                mark = stickers[self.editing]
                self.place_x = model.units(mark["x"])
                self.place_y = model.units(mark["y"])
                self._goto(model.PLACE)
            return
        if buttons.pressed("C") and self.index > 0:
            # NO CONFIRMATION, and that is a judgement rather than an oversight.
            # B7 puts irreversible actions behind one; removing one sticker from
            # a badge that still has the other twenty-three is a press to undo,
            # not a loss, and a confirmation on every sticker would make placing
            # a full badge a hundred-press job.  Deleting a whole BADGE is the
            # action that does get one.
            del stickers[self.index - 1]
            self._commit(milestone=True)
            if self.index > len(stickers):
                self.index = len(stickers)
            self._toast_now(now_ms, MARK_GONE)

    def _route_pick(self, now_ms, buttons):
        step = self._scroll(now_ms, buttons)
        if step:
            self.pick = (self.pick + step) % marks.COUNT
        if buttons.pressed("A"):
            self._goto(model.MARKS)
            return
        if buttons.pressed("B"):
            self.editing = -1
            self.place_x = model.RECIPE_UNITS // 2
            self.place_y = model.RECIPE_UNITS // 2
            self._goto(model.PLACE)

    def place_step(self, speed, span):
        """Ten-thousandths of the canvas per step, ramping with the hold.

        `ui.PLACE_MIN_STEP` and `ui.PLACE_MAX_STEP` are LOGICAL PIXELS -- 6 and
        16 -- so the step is 2.25 mm to 6 mm on the ruler-measured panel at
        either resolution.  Quoted in the wearer's units rather than the
        panel's: the same fraction moves the same distance on glass whether the
        badge is drawing 160 pixels across or 320.
        """
        pixels = ui.PLACE_MIN_STEP + int(
            speed * (ui.PLACE_MAX_STEP - ui.PLACE_MIN_STEP))
        return max(1, pixels * model.RECIPE_UNITS // max(1, span))

    def _route_place(self, now_ms, buttons):
        right = self._place_right.step(buttons.held("C"), now_ms)
        left = self._place_left.step(buttons.held("A"), now_ms)
        down = self._place_down.step(buttons.held("DOWN"), now_ms)
        up = self._place_up.step(buttons.held("UP"), now_ms)
        if right or left:
            speed = (self._place_right.progress if right
                     else self._place_left.progress)
            step = self.place_step(speed, self.logical_w)
            self.place_x = _clamp(self.place_x + (right - left) * step, 0,
                                  model.RECIPE_UNITS)
        if down or up:
            speed = (self._place_down.progress if down
                     else self._place_up.progress)
            step = self.place_step(speed, self.logical_h)
            self.place_y = _clamp(self.place_y + (down - up) * step, 0,
                                  model.RECIPE_UNITS)
        if not buttons.pressed("B"):
            return
        stickers = self.badge()["stickers"]
        x = self.place_x / float(model.RECIPE_UNITS)
        y = self.place_y / float(model.RECIPE_UNITS)
        if self.editing >= 0 and self.editing < len(stickers):
            stickers[self.editing]["x"] = x
            stickers[self.editing]["y"] = y
            landed = self.editing + 1
            message = SAVED
        else:
            stickers.append({"kind": marks.MARKS[self.pick][0], "x": x, "y": y})
            landed = len(stickers)
            message = MARK_ADDED
        self.editing = -1
        self._commit(milestone=True)
        # LANDS ON THE MARK LIST WITH THE PLACED MARK SELECTED, which is the
        # whole mitigation for `PLACE` having no labelled cancel: `DROP` is
        # non-destructive and `DEL` is one press away on the row it lands on.
        self._goto(model.MARKS)
        self.index = landed
        self._toast_now(now_ms, message)

    # -- reset the badge ------------------------------------------------------

    def _route_confirm(self, now_ms, buttons):
        """The one destructive press in this app, behind the one confirmation.

        THE ROUTE OUT IS A AND IT COMMITS NOTHING (I2), and the route back is
        the menu ON THE ROW THAT ASKED -- not the top of it.  `_goto` resets the
        selection to 0, which would land a wearer who declined a reset on NAME,
        with a modal's worth of adrenaline and no idea what they just did.
        `_back_to_the_row` learned this on SAVE TO HOME and `_route_effect`
        learned it again; this is the third screen to need it.
        """
        if buttons.pressed("A"):
            self._menu_at(model.MENU_RESET)
            return
        # B IS INERT HERE.  B7, and it is the only screen in the app where the
        # primary key does nothing: a thumb that has been pressing B all
        # afternoon must not be able to reset a badge with a press it started
        # before it read the question.
        if not buttons.pressed("C"):
            return
        self._reset_badge(now_ms)

    def _reset_badge(self, now_ms):
        """Back to the original system defaults.  The card, and NOTHING else.

        THE OWNER'S SCOPE, 2026-08-24, verbatim: *"which takes the home screen
        background, poster, and name badge back to the original system defaults
        without a name or anything so it's easy to redo it from scratch ...
        network and game scores and everything else will persist. The only way to
        wipe a badge [fully] will be someone at the event plugs it into a
        supabase machine and wipes it for you."*  A full wipe is a STAFF
        procedure over serial (`scripts/badge-wipe.sh`, `docs/staff-badge-wipe.md`)
        and it is deliberately not reachable from any button on the badge.

        WHAT THIS CLEARS, as the exact files it can reach:

            /state/badgecard.json    `badges` -> one factory card, `active` -> 0,
                                     `home.on` -> False, `home.recipe` -> 0.
                                     Its root `brightness` is NOT NAMED and so
                                     survives -- that field belongs to the
                                     `settings` tile, and a wearer who resets
                                     their card has not asked for a bright panel.
            /state/wallpaper.pgw     deleted, through the injected `unbake`.

        WHAT IT CANNOT REACH, AND WHY THAT IS STRUCTURAL RATHER THAN CAREFUL.
        This module is PURE -- `test_card_purity` walks its AST and fails on any
        import outside the model, the two catalogues and `ui` -- so it opens no
        file at all.  The seam (`badgecard/__init__.py`) hands it exactly two
        write capabilities, the `card_store.save` above and `Baker.remove` for
        the film.  `/state/badgelink_state.json`, the network preference, the
        schedule and the five games' score files are therefore not reachable from
        this press by construction, not by discipline, and
        `test_card_reset.BoundaryTests` asserts the whole of `/state` around a
        real reset to keep it that way.

        THE FILM GOES BEFORE THE FLAG, and the order is load-bearing rather than
        tidy.  `card_bake.reconcile` runs at every boot on the rule that THE DISK
        IS THE TRUTH: if the state said `home.on = False` while the file was
        still on the volume, the next launch would read the header, disagree, and
        turn the wearer's old wallpaper straight back on.  Clearing the flag
        without deleting the file is not a partial reset -- it is a reset that
        undoes itself.

        A FAILED REMOVAL DOES NOT ABORT THE RESET, which is the mirror of
        `_clear_home` and of the same judgement.  `wallpaper.remove` is total and
        answers False for a file that was not there -- the overwhelmingly common
        case, since most badges never bake -- so a caller that treated False as
        an error would refuse to reset the majority of badges in the room.
        """
        if self._unbake is not None:
            self._unbake()
        model.reset_card(self.state)
        # A MILESTONE.  `.bak` is what a corrupt primary falls back to, and a
        # recovery that restored the badge the wearer just deliberately wiped
        # would be the loudest possible way to fail: they reset it because they
        # wanted it gone, and the badge would hand it back.
        self._commit(milestone=True)
        # BACK ON THE ROW THAT WAS PRESSED, like every other return in this app,
        # and it also happens to be one press from starting over: B3's lists
        # wrap, so a single DOWN from the last row lands on NAME -- which is what
        # the owner asked this feature for ("so it's easy to redo it from
        # scratch").
        self._menu_at(model.MENU_RESET)
        self._toast_now(now_ms, CARD_RESET)

    # -- save to home, from the menu row itself -------------------------------

    def _save_home(self, now_ms):
        """SELECT IT, DONE -- the owner's ruling of 2026-08-21.

        There is no preview screen and no confirmation between this and the
        wallpaper: the row was selected, so the answer is the wallpaper or a
        sentence saying why not.

        A FILM THAT ALREADY MATCHES IS NOT RE-BAKED, and the wearer is told so
        anyway.  Re-baking would be a second of modal and a 76,816-byte flash
        write to produce the file that is already there; the toast is the same
        `HOME SCREEN SET` either way, which is true in both cases and is what
        the wearer pressed the key to find out.  The recipe stamp is what makes
        this answerable without drawing anything (`card_bake.recipe_of`).
        """
        if self.home_installed() and not self.home_stale():
            self._toast_now(now_ms, HOME_ON)
            return
        self._start_bake(now_ms)

    def _clear_home(self, now_ms):
        if not self.home_installed():
            # INERT RATHER THAN A SENTENCE.  The key is unlabelled when nothing
            # is installed, so a press that reaches here is a thumb on a dead
            # key and has nothing to be told.
            return
        if self._unbake is not None:
            self._unbake()
        self.state["home"]["on"] = False
        self.state["home"]["recipe"] = 0
        self._commit(milestone=True)
        self._toast_now(now_ms, HOME_OFF)

    def _start_bake(self, now_ms):
        if self._bake is None:
            self._toast_now(now_ms, HOME_FAILED)
            return
        self.job = self._bake(self.state)
        if self.job is None:
            self._toast_now(now_ms, HOME_FAILED)
            return
        # A DECLARED MODAL STATE, stepped one unit per rendered frame.  The bake
        # is a second or two of real work and a silent freeze of that length is
        # an I4 violation, so the modal is DRAWN FIRST and the work happens
        # between frames the wearer can see.
        self._goto(model.BAKING)

    def _route_baking(self, now_ms, buttons):
        job = self.job
        if job is None:
            self._goto(model.MENU)
            return
        # EVERY REPEAT IS DRAINED EVERY FRAME even though nothing here reads
        # input.  A `ui.Repeat` that is never stepped stays blocked and then
        # eats the wearer's first real press once the modal clears.
        self._scroll(now_ms, buttons)
        self._place_left.step(buttons.held("A"), now_ms)
        self._place_right.step(buttons.held("C"), now_ms)
        self._place_up.step(buttons.held("UP"), now_ms)
        self._place_down.step(buttons.held("DOWN"), now_ms)
        job.step()
        if not job.finished:
            return
        self.job = None
        if job.ok:
            self.state["home"]["on"] = True
            self.state["home"]["recipe"] = job.recipe
            self._commit(milestone=True)
            self._back_to_the_row(now_ms, HOME_ON)
            return
        self._back_to_the_row(now_ms, job.note or HOME_FAILED)

    def _back_to_the_row(self, now_ms, message):
        """Return to SAVE TO HOME with the bake's verdict.  See `_menu_at`."""
        self._menu_at(model.MENU_HOME)
        self._toast_now(now_ms, message)

    # -- the plan ------------------------------------------------------------

    def plan(self, now_ms):
        """Everything the view needs, and nothing it could get wrong.

        `animate` is the one field worth explaining: it names the background
        entry that may MOVE this frame, or "" for none.  Only two screens show
        the wearer's own artwork -- the resting badge and the skin browser --
        and the browser may only animate an entry that has SETTLED, because
        animating one the wearer is scrubbing past would be paying a skin's
        animator for a frame nobody sees.
        """
        badge = self.badge()
        view = self.view
        if view == model.BADGE:
            animate = badge["background"]
        elif view == model.SKIN and self.settled:
            animate = self.choice
        elif view == model.EFFECT:
            # NO SETTLE GATE HERE.  The effect browser never changes the
            # BACKGROUND, so the entry behind the list is the one already
            # rendered and cached: there is no rasterisation to defer and
            # freezing the artwork mid-browse would make a moving skin look like
            # a side effect of opening this row.
            animate = badge["background"]
        else:
            animate = ""
        installed = self.home_installed()
        stale = self.home_stale()
        if view == model.MENU:
            rows = len(model.MENU_ITEMS)
        elif view == model.MARKS:
            rows = self.mark_rows()
        elif view == model.SKIN:
            rows = catalogue.COUNT
        elif view == model.EFFECT:
            rows = effects.COUNT
        else:
            rows = 0
        return {
            "view": view,
            "labels": model.softkeys(view, self.index, installed),
            "state": self.state,
            "badge": badge,
            "index": self.index,
            "rows": rows,
            "choice": self.choice,
            "settled": self.settled,
            # WHAT THE CARD IS DRAWN THROUGH THIS FRAME, which is the previewed
            # effect on the browser and the saved one everywhere else.  One
            # field rather than two, because the view must not have to decide
            # which of them applies: that decision is a screen's, and screens
            # are this controller's business.
            "effect": (self.effect if view == model.EFFECT
                       else badge["effect"]),
            "pick": self.pick,
            "place": (self.place_x / float(model.RECIPE_UNITS),
                      self.place_y / float(model.RECIPE_UNITS)),
            "editing": self.editing,
            # `doomed` LEFT THIS PLAN WITH THE CARDS SCREEN.  It named which of
            # five badges a confirmation was about; there is one card, so the
            # confirmation reads `badge` like every other screen does.
            "board": self.board,
            "cap": self.name_cap(),
            "animate": animate,
            "now": now_ms,
            "frame": self.frames,
            "awake": not self._blocked,
            "toast": self._toast,
            "home": self.state["home"],
            "installed": installed,
            "stale": stale,
            "progress": self.job.progress if self.job is not None else 0.0,
            "stage": self.job.stage if self.job is not None else "",
            "exit": self.exit,
        }


_DEFAULT_LOGICAL = (160, 120)


def _clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def _plain_diff(later, earlier):
    """`time.ticks_diff` for a host that has a monotonic integer clock.

    The device's version wraps at 30 bits and the seam injects it; this is the
    fallback so a test can construct the app with no clock at all.
    """
    return later - earlier
