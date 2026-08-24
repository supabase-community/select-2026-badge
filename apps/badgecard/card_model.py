"""The pure core: the schema, a total `repair`, the screen list and the labels.

THE LAW OF THIS FILE.  It imports `card_faces` and nothing else -- no clock, no
file, no `json`, and above all no Badgeware global.  Every function takes its
input as an argument and returns a value.  That is what lets the whole of
`badgecard/tests` run on CPython in seconds, and it is worth more than any
amount of browser testing (`docs/badge-app-quickstart.md` section 6).

THE FIVE DEFECTS THIS SCHEMA MAKES UNREPRESENTABLE, inherited wholesale from
`identity_model` because they were paid for once already, in `profile` and
`namebadge`, with real lost badges:

1.  A BACKGROUND IS A FROZEN STRING, NEVER AN INDEX.  `profile` and `namebadge`
    persist `skin: <int>`, a position in a tuple, so inserting one artwork
    rewrites every wearer's badge and the catalogue can never be improved in the
    middle.
2.  A STICKER'S KIND IS A FROZEN STRING for the same reason.  `namebadge`
    persists `kind: <int>` into `stickers_data.STICKERS`.
3.  AN UNKNOWN ID IS KEPT, NOT DISCARDED.  A badge configured on a newer build
    degrades to "wrong picture" rather than to "your badge is gone", and starts
    working again the moment the asset is reinstalled.
4.  A COORDINATE IS A FRACTION OF THE CANVAS, so one state file drives both
    resolutions and puts every mark in the same PHYSICAL place.
5.  `repair` IS TOTAL.  Anything at all that is a `dict` becomes a drawable
    badge; every other input becomes a fresh one.  Nothing here raises.

AND ONE THIS APP ADDS.  THE FACE IS DERIVED, NEVER STORED AS AN INDEPENDENT
CHOICE.  The owner ruled on 2026-08-17 that the skin dictates the face
(`docs/design/authoring-a-skin/consuming-a-skin.md`, option A), so `repair`
recomputes `face` from `background` on every load and a hand-edited file cannot
separate them.  It is written into the badge rather than resolved at draw time
for exactly one reason: `poster` -- the app the launcher's 1.5-second hold opens
-- reads `state["face"]`, and a derived field on disk is what keeps that app's
change to one line.
"""

import backlight
import card_faces as faces
import effects


SCHEMA = 1

# HOW MANY LEGACY SLOT ENTRIES SURVIVE A LOAD.  NOT A PRODUCT CAP -- there is no
# cap any more, because there is no choice any more.
#
# THE OWNER RULED ON 2026-08-24: *"remove the 5 different name badge save spots.
# So basically you create your name badge, if you don't like it you can edit it,
# or you can wipe it and start over."*  One live card, and the BADGES row, the
# CARDS screen and the five-slot product all went with that sentence.
#
# THE LIST DID NOT GO WITH THEM, AND THE REASON IS THAT THIS FILE DOES NOT OWN
# THE FORMAT ALONE.  `/state/badgecard.json` is a SHARED file with three other
# apps in it, and two of them spell `{"active": <int>, "badges": [ ... ]}` by
# name:
#
#   `poster/badge/poster/badge_state.select`   READS `badges[active]` and draws
#                                              it.  It is the app the launcher's
#                                              1.5-second hold opens.
#   `badgelink/.../badgecard_state.py`         WRITES one key on the ACTIVE
#                                              badge for a remote `set_name` or
#                                              `set_skin`, carrying every other
#                                              byte verbatim.
#   `settings`' brightness store               writes the ROOT `brightness` and
#                                              must carry the list past it --
#                                              its own comments say a careless
#                                              write here destroys saved badges.
#   the launcher's brightness read             reads the ROOT `brightness`.
#
# Re-rooting the shape to a bare `badge` dict would be a four-app format break
# bought for zero wearer-visible gain: the wearer already sees one card either
# way.  So the list stays as the FORMAT, and the app draws index `active` and
# offers no way to change it.
#
# WHICH MAKES THIS A CARRY BOUND RATHER THAN A CHOICE BOUND, and the difference
# decides the migration.  A dev badge that already holds five slots keeps them on
# disk and keeps wearing the one it was wearing -- IGNORED, not deleted, which is
# schema rule 3 (an unknown value is kept) pointed at the wearer's own old data.
# The one press that deletes them is RESET, which is a press the wearer asked
# for.  Five, because five is what an old file can hold; the bound exists so a
# hostile file cannot turn a load into an unbounded repair loop, exactly as
# `STICKER_SCAN_MAX` does for marks.
CARRY_BADGES = 5

# The name cap, and it is `poster`'s.  `badge_state.NAME_MAX` truncates a longer
# name before drawing it, and `poster` is what the launcher's hold opens, so an
# editor that accepted more would show the wearer a name their own home screen
# then cut short.  `card_faces.cap_for` applies this as a CEILING over the
# skin's own, narrower, per-face cap.
NAME_MAX = 12

# `poster`'s cap too, and `namebadge`'s before it.  Twenty-four 24 px marks is
# about 4 ms of blitting against a ~22.8 ms frame (docs/engineering-findings.md).
MAX_STICKERS = 24
# How far into a hostile list to look before giving up.  A list of a million
# entries is not a badge and scanning it is a launch that never finishes.
STICKER_SCAN_MAX = 256

# What a badge nobody has configured wears.  `poster`'s defaults, restated here
# rather than imported because that app must not depend on this one; the tests
# pin every one of them against `poster/badge/poster/badge_state.py`.
DEFAULT_BACKGROUND = "skin.supabase"
DEFAULT_NAME = ""
# THE EFFECT A NEW BADGE WEARS. One line, and it is the owner's to swap;
# `shared/effects.py` holds the shipped set and the evidence behind the pick.
DEFAULT_EFFECT = effects.DEFAULT


# ---------------------------------------------------------------------------
# the screens
# ---------------------------------------------------------------------------

# Strings rather than an enum: MicroPython has no enum, and a string prints
# itself in a traceback and in the `CARD_VIEW` marker the browser lane reads.
BADGE = "badge"
MENU = "menu"
NAME = "name"
SKIN = "skin"
MARKS = "marks"
PICK = "pick"
PLACE = "place"
# THERE IS NO `CARDS` SCREEN, and there was one from 2026-08-17 to 2026-08-24.
# It was the list of five saved badges -- WEAR, NEW, DEL -- and the owner removed
# the whole feature: *"remove the 5 different name badge save spots."*  What went
# with it: `card_app._route_cards`, `card_rows`, `CardView.cards_screen`, the
# `%d OF %d` value on the menu row, the `n/m` slot counter in the menu header,
# and the `count` argument this file's `softkeys` took to label WEAR against NEW.
#
# `CONFIRM` OUTLIVED IT AND CHANGED JOBS.  It was "delete the badge you selected
# in the list"; it is now "reset the one card you have", which is the same
# screen, the same B7 bar and the same question with one subject instead of five.
# Reusing it rather than inventing a second confirmation is the point: this app
# now has exactly one destructive action and exactly one screen that asks about
# one, so a wearer who ever sees a red-ruled modal here knows what kind of press
# put it there.
CONFIRM = "confirm"
BAKING = "baking"
EFFECT = "effect"
# THERE IS NO `BRIGHT` SCREEN, and there was one from 2026-08-23 to 2026-08-24.
# The owner's ruling: *"Take brightness out of badgecard. That should only exist
# in settings."*  The ladder, its screen and its menu row moved wholesale to the
# `settings` tile; what stayed here is the STORE (`new_state`'s `brightness`,
# `repair`'s clamp and `invariants`' range check) because
# `/state/badgecard.json` is still the one file every reader shares -- the
# launcher, `poster`, `settings` and this app's own `panel.restore()`.  A schema
# that dropped the field would take the wearer's level with it.

# THERE IS NO `HOME` SCREEN, and there was one until 2026-08-21.  The owner's
# ruling: *"can the save to home option just appear as a kind of button? so it's
# more obvious. they don't need to see outdated and they don't need an extra
# screen to confirm. it should just be save to home as an option, select it,
# done."*  So the menu row IS the button: B bakes, C clears, and the only screen
# between the press and the wallpaper is `BAKING`, which is a progress modal for
# a second of real work rather than a question.
#
# What went with it: a framed preview of the launcher, its "NOT SET" /
# "OUT OF DATE" / "SHOWING THIS BADGE" status line, and the press that opened
# it.  The preview answered "is this the right picture" -- a good question, and
# one the wearer can answer by looking at the badge the menu is drawn over.
VIEWS = (BADGE, MENU, NAME, SKIN, MARKS, PICK, PLACE, CONFIRM, BAKING,
         EFFECT)

# The screens whose background is the wearer's own artwork and may therefore
# move.  Everything else draws over a plate and would be paying a skin's
# animator for pixels nobody can see.
# EFFECT IS HERE TOO, and it is the whole point of the screen: the filter is
# applied to the card, so a chooser that showed a still card would be showing the
# wearer the one thing they are not choosing.
ANIMATED = (BADGE, SKIN, EFFECT)

# THE MENU.  The owner enumerated the first five on 2026-08-17 and ruled out a
# SHOW BADGE row, because the badge is what you get when you leave the menu.
#
# SIX ROWS.  It was seven for a day: two lanes each landed an owner-asked
# row on 2026-08-23, and the owner took one of them back out on 2026-08-24 --
# *"Take brightness out of badgecard. That should only exist in settings."*  So
# the ruling that is still live is "the menu is what the owner enumerates", not
# "the menu is five rows" and not "the menu only grows": the COUNT was never the
# thing being protected, and what is protected instead is that a row buys its
# place -- and can be told to give it up.
#
# IT IS STILL SIX AND THE SIXTH IS A DIFFERENT ROW.  BADGES left and RESET BADGE
# arrived in the same owner ruling on 2026-08-24, which is worth reading as one
# sentence rather than two changes: *"a setting in badgecard to 'reset name
# badge' ... so it's easy to redo it from scratch. Also remove the 5 different
# name badge save spots. So basically you create your name badge, if you don't
# like it you can edit it, or you can wipe it and start over."*  The five slots
# were the old answer to "I don't like this one"; RESET is the new one, and it is
# one row instead of a list, one card instead of five, and no bookkeeping.
#
# WHERE BRIGHTNESS WENT, because a reader who comes here looking for it needs
# one pointer rather than a search: the `settings` tile, whose own `ROWS`
# already carries SLEEP and was built for exactly this class of row.  The ladder
# is unchanged (`shared/backlight.py`, one press per rung, clamped) and so is
# the store -- it is still `/state/badgecard.json`'s root `brightness`, which
# this schema still owns and this app still applies at open.
#
# EFFECT came with *"awesome, let's do it"*, and one correction attached that
# this file obeys: *"no random on the actual badge, just pick one."*  It buys its
# place as the only per-wearer choice about how the finished card LOOKS that is
# not a choice of artwork.
#
# THE ORDER.  NAME, SKIN, STICKERS and EFFECT are the four things a card IS, in
# the order a wearer builds one.  Then the two rows that are BUTTONS rather than
# screens, because a button belongs at the end of a list of settings rather than
# in the middle of things a wearer scrolls past.
#
# RESET IS LAST, AND B3'S WRAP IS WHY THAT IS SAFE RATHER THAN RECKLESS.  Lists
# wrap, so the first UP from row 0 lands on the last row -- a press a wearer
# makes blind, before the menu has been read.  That target used to be SAVE TO
# HOME, and this comment used to concede it was "the least harmless row left",
# because a single B there writes a 76,816-byte film with no question asked.
# RESET is strictly safer in that seat: B on it OPENS a confirmation and destroys
# NOTHING, B is inert on that confirmation (B7), and the only key that resets
# anything is a C the wearer presses after reading a modal that names their
# badge.  So the most destructive row in the app is also the one that costs the
# most deliberate presses, and the blind wrap got cheaper rather than dearer.
#
# AND IT STILL DOES NOT SCROLL, WHICH WAS WORTH CHECKING RATHER THAN ASSUMING.
# `card_view._rows` turns the rail and the chevrons on when `total > room`, and
# `room` is `(chrome.content_h - head_h) // row_h`: measured through a real
# `CardView` it is NINE rows at LORES (107 - 14) // 10 and SIXTEEN at HIRES
# (214 - 20) // 12.  So SIX fits with three spare at the tighter panel, the
# scroll affordances stay off, and the ledger entry about a rail on a list that
# cannot move is still fixed.  `test_card_home.MenuRoomTests` pins the headroom
# so that the row which finally overflows it does so as a red test rather than
# as a rail nobody expected.
MENU_NAME = "NAME"
MENU_SKIN = "SKIN"
MENU_MARKS = "STICKERS"
MENU_EFFECT = "EFFECT"
MENU_HOME = "SAVE TO HOME"
# "RESET BADGE" AND NOT "RESET NAME BADGE", which is the owner's own phrase.
# Inside this app every noun is already the badge, so the second word would be
# carried by every other row too and none of them says it; the register the other
# five rows set is NAME / SKIN / STICKERS / EFFECT / SAVE TO HOME.  The full
# phrase survives where a wearer might actually need the disambiguation: the
# confirmation modal, which spells out what goes and what stays.
MENU_RESET = "RESET BADGE"
MENU_ITEMS = (MENU_NAME, MENU_SKIN, MENU_MARKS, MENU_EFFECT, MENU_HOME,
              MENU_RESET)


# ---------------------------------------------------------------------------
# the softkey bar
# ---------------------------------------------------------------------------

# EVERY LABEL IS FIVE CHARACTERS OR FEWER, because `ui.LABEL_MAX_PX` is 34
# logical pixels and `font.sins` advances 6-7 px an uppercase glyph.  `SELECT`,
# `DELETE`, `SWITCH` and `SHUFFLE` all bust it -- measured, not eyeballed, and
# `badgecard/tests/test_card_labels.py` measures every one of these against the
# real advance table rather than counting characters.
BACK = "BACK"
OPEN = "OPEN"
APPLY = "APPLY"
JUMP = "JUMP"
ADD = "ADD"
MOVE = "MOVE"
DEL = "DEL"
DROP = "DROP"
LEFT = "LEFT"
RIGHT = "RIGHT"
PLACE_LABEL = "PLACE"
KEEP = "KEEP"
SAVE = "SAVE"
CLEAR = "CLEAR"
# THE ONE KEY IN THIS APP THAT RESETS ANYTHING.  29 px against `ui.LABEL_MAX_PX`
# of 34, measured through the real `font.sins` advance table by
# `test_card_labels` like every string in this block -- not counted in
# characters, which is the mistake that put `SELECT` and `DELETE` on a panel with
# their last glyph silently dropped.
#
# `DEL` was what this slot said while the confirmation was about deleting one of
# five badges; a card that is being put back to factory is not being deleted, and
# a bar that said DEL over a modal headed RESET BADGE would be two words for one
# press.  `WEAR` and `NEW` left with the CARDS screen on 2026-08-24.
RESET = "RESET"

# A screen that draws no bar at all.  Two of them, and for two different
# reasons: `BADGE` is the resting poster and D1 says a resting badge draws zero
# chrome; `NAME` is the QWERTY board, whose softkey bar the owner removed on
# 2026-08-16 (kb deviation D9, an explicit overrule of I5) so its four rows
# could grow from 19 px to 22.
NO_BAR = ("", "", "")


def softkeys(view, index=0, installed=False):
    """The three labels for a screen, as `(A, B, C)`.  Never raises.

    `count` LEFT THIS SIGNATURE WITH THE CARDS SCREEN (2026-08-24).  It said how
    many badges were saved, and the only branch that read it chose WEAR against
    NEW on a row of that list.  A parameter nothing reads is a parameter every
    caller has to guess a value for, and `labels()` below would have gone on
    sweeping three values of it forever to measure strings that cannot be drawn.

    ONE FUNCTION OWNS THE BAR, and it is pure, so the browser lane can assert
    what a screen offers without rendering it and the label ruler can measure
    every string this app can ever draw by calling this over every combination.
    An empty slot is an inert key that draws nothing -- `ui.Chrome.bar` already
    treats it that way -- and never a key that does something unlabelled, which
    is the I5 failure this signature exists to make impossible.
    """
    if view == BADGE or view == NAME or view == BAKING:
        return NO_BAR
    if view == MENU:
        # THE SAVE-TO-HOME ROW IS A BUTTON, so its keys say so: B is SAVE rather
        # than OPEN because nothing opens, and C offers CLEAR only when there is
        # a film to remove.  The MARKS and CARDS screens already label B and C
        # per ROW for the same reason -- a key labelled for what it will
        # actually do beats a key labelled for the screen it lives on.
        if index == MENU_ITEMS.index(MENU_HOME):
            return (BACK, SAVE, CLEAR if installed else "")
        # AND THE RESET ROW IS NOT A BUTTON, WHICH IS THE WHOLE GATE.  Its B says
        # OPEN because a screen is what it opens; nothing on this menu can reset
        # anything.  A row that said RESET here would be one press from a wiped
        # badge and would be reading its label off the same B every other row
        # uses to browse -- which is precisely the "wake and fire" shape I5
        # forbids, one screen further in.
        return (BACK, OPEN, "")
    if view == SKIN:
        return (BACK, APPLY, JUMP)
    if view == EFFECT:
        # THE SAME BAR AS SKIN, MINUS JUMP, and both halves are deliberate.
        # Same, because it is the same kind of screen -- browse a list, commit
        # with B -- and B2 says B is the primary action everywhere; a browse
        # screen that spelled its commit differently from the browse screen next
        # door would be teaching the wearer two words for one press.
        # Minus JUMP, because JUMP exists to cross 76 skins in fifteen presses
        # and this list is 15 long: UP/DOWN wraps, so the farthest entry is
        # seven presses away and a third key would be chrome for nothing.
        return (BACK, APPLY, "")
    if view == MARKS:
        # Row 0 is ADD; every row after it is a mark the wearer placed.  B and C
        # therefore mean different things on the first row, and both are
        # labelled for what they will actually do rather than greyed.
        if index == 0:
            return (BACK, ADD, "")
        return (BACK, MOVE, DEL)
    if view == PICK:
        return (BACK, PLACE_LABEL, "")
    if view == PLACE:
        # ALL FOUR DIRECTION KEYS PLUS B, so there is no room for a labelled
        # cancel.  This is `identity`'s recorded D3 exception to I2 and it is
        # carried here deliberately: `DROP` is non-destructive, it lands back on
        # the mark list with the placed mark selected, and `DEL` is one press
        # away.  The two costed alternatives -- pay a press per placement to
        # keep a cancel on A, or build the button rules' 9.2 odometer -- are
        # still open and still not free.
        return (LEFT, DROP, RIGHT)
    if view == CONFIRM:
        # B IS INERT ON A CONFIRMATION.  B7, and `identity` learned it the hard
        # way: B is the primary action on every other screen in the app, so a
        # thumb that has been pressing B all afternoon must not be able to
        # destroy a badge with the press it has already started.
        return (KEEP, "", RESET)
    return NO_BAR


def labels():
    """Every softkey string this app can draw, for the ruler to measure.

    Derived by CALLING `softkeys` over every screen and every branch rather than
    listed beside it: a list and a function that are two descriptions of one bar
    are two things that can disagree, and the way that bug presents is a label
    nobody measured appearing on a physical panel with its last glyph silently
    dropped.
    """
    out = []
    for view in VIEWS:
        for index in range(len(MENU_ITEMS) + 1):
            for installed in (False, True):
                for label in softkeys(view, index, installed):
                    if label and label not in out:
                        out.append(label)
    return tuple(out)


# ---------------------------------------------------------------------------
# the badge
# ---------------------------------------------------------------------------

def new_badge():
    """One unconfigured badge.  A FRESH DICT EVERY CALL.

    A module-level default that callers mutate is how `profile` ended up writing
    defaults over real state.  Nothing here writes anything, but the same dict
    handed to two readers is the same class of bug.
    """
    return {
        "name": DEFAULT_NAME,
        "background": DEFAULT_BACKGROUND,
        "face": faces.face_of(DEFAULT_BACKGROUND),
        "stickers": [],
        # A BADGE NOBODY HAS CONFIGURED SHIPS WEARING THE DEFAULT EFFECT, and a
        # badge that ALREADY EXISTS does not gain one -- see `repair_badge`.
        # The asymmetry is the point: the feature is discoverable on a new
        # badge, and nobody who already made one wakes up to a filtered card
        # after an update they did not ask for.
        "effect": DEFAULT_EFFECT,
    }


def new_state():
    """A badge nobody has configured, in a store nobody has used."""
    return {
        "schema": SCHEMA,
        "active": 0,
        "badges": [new_badge()],
        "home": {"on": False, "recipe": 0},
        # THE PANEL, NOT A BADGE, which is why it sits at the root beside
        # `active` rather than inside `new_badge()`: brightness is a property of
        # the screen, so nothing the wearer does to their CARD may move it.
        # That used to be argued from switching between five saved badges; the
        # slots are gone and the rule got a sharper case instead -- RESET BADGE
        # replaces the whole `badges` list and must leave the panel exactly where
        # `settings` put it.  `reset_card` below is where that is enforced, and
        # it is enforced by not naming this key.
        # `poster/badge/poster/badge_state.DEVICE_KEYS` is
        # the reader that agrees with this, and it had to be TAUGHT to -- before
        # 2026-08-23 it read `brightness` out of the selected badge, so the
        # format described a per-badge value nothing could write.
        #
        # THIS APP NO LONGER WRITES IT (owner ruling, 2026-08-24): the control
        # is the `settings` tile's, and this file is the SCHEMA the four readers
        # share -- the launcher, `poster`, `settings` and this app's own
        # `panel.restore()`.  It stays in the schema because a badge's chosen
        # level has to survive the exit that every app makes: leaving an app is
        # `machine.reset()`, so nothing is handed over in RAM and persistence is
        # the only way a level can hold.
        "brightness": backlight.DEFAULT,
    }


# The five keys every draw path indexes without checking.  Named once, so
# `active` and `invariants` cannot disagree about what "a badge" means.
BADGE_KEYS = ("name", "background", "face", "stickers", "effect")


def active(state):
    """The badge being worn.  Always a DRAWABLE badge, whatever it is handed.

    Total because every caller is a draw path: a view that has to check for None
    before it can paint is a view with a branch nobody exercises, and the branch
    nobody exercises is the one that raises on a stranger's badge.

    "A dict" IS NOT ENOUGH, and that is the bug this shape closes.  Returning
    `badges[0]` because it passed `isinstance(..., dict)` hands the view an
    EMPTY dict for a state like `{"badges": [{}]}`, and the very next line is
    `badge["background"]` -- a KeyError on the launch path, which reaches
    `badgeware.fatal_error` and RESETS the badge.  So the keys are checked, and
    a badge missing any of them is repaired into one that has them.

    The repaired badge is a COPY, so a mutation would not persist.  That is
    correct rather than a compromise: this arm is only reachable for a state
    `repair` never processed, and every state the app itself holds came through
    `card_store.load`.  It is the difference between a wrong pixel and a reset.
    """
    badges = state.get("badges")
    if not isinstance(badges, list) or not badges:
        return new_badge()
    index = state.get("active")
    if not isinstance(index, int) or isinstance(index, bool):
        index = 0
    if index < 0 or index >= len(badges):
        index = 0
    badge = badges[index]
    if not isinstance(badge, dict):
        return new_badge()
    for key in BADGE_KEYS:
        if key not in badge:
            return repair_badge(badge)
    return badge


def reset_card(state):
    """Put the WEARER'S CARD back to a factory one, in place.  Total.

    THE OWNER'S RULING OF 2026-08-24 IS THE SPEC, and its second half matters as
    much as its first: *"which takes the home screen background, poster, and name
    badge back to the original system defaults without a name or anything ...
    network and game scores and everything else will persist. The only way to
    wipe a badge [fully] will be someone at the event plugs it into a supabase
    machine and wipes it for you."*  So this is a CARD reset and never a badge
    wipe, and the boundary is not a promise in a comment -- it is this function's
    body.  Three keys are named here and nothing else in the store is reachable
    from it:

        badges   -> ONE factory card.  Every legacy slot goes, and this is the
                    only place in the app that deletes one (see `CARRY_BADGES`:
                    ignored on load, deleted on reset, and never in between).
        active   -> 0, because there is exactly one entry to point at.
        home.on  -> False, with `home.recipe` back to 0.  The FILM ITSELF is a
        home.recipe  file on disk and this module opens none, so the caller
                    deletes it through the injected `unbake`; clearing the flag
                    without the file would leave `card_bake.reconcile` turning it
                    straight back on at the next boot, which is the disk-is-the-
                    truth rule working exactly as designed and against us.

    WHAT IT CANNOT TOUCH, said as code rather than as a list.  `brightness` is a
    sibling key it never names, so the level `settings` wrote survives.  The
    carried unknown keys `repair` preserved at the root survive for the same
    reason.  And every OTHER file under `/state` -- the badgelink pairing state,
    the network preference, the schedule, the five games' scores -- is not
    reachable from this app at all: `card_app` is pure (`test_card_purity` walks
    its AST), and the seam hands it exactly two write capabilities, a writer for
    `/state/badgecard.json` and an `unbake` for `/state/wallpaper.pgw`.  The
    scope boundary is a property of the wiring, which is why it is checkable.

    THE POSTER NEEDS NO LINE HERE, and that was verified rather than assumed.
    `poster` persists nothing: it reads `/state/badgecard.json`, selects
    `badges[active]` through its own total `badge_state.select`, and draws.  So a
    card put back to factory IS a factory poster, on the next open, with no
    second store to keep in step.
    """
    state["badges"] = [new_badge()]
    state["active"] = 0
    home = state.get("home")
    if not isinstance(home, dict):
        # A hand-edited or half-repaired store still has to come out of this
        # function resettable.  `_home` is the same shape `repair` installs.
        home = _home(None)
        state["home"] = home
    home["on"] = False
    home["recipe"] = 0
    return state


# ---------------------------------------------------------------------------
# repair
# ---------------------------------------------------------------------------

def _text(value, fallback, limit):
    if isinstance(value, str):
        return value[:limit]
    return fallback


def _ident(value, fallback, limit=48):
    """An id: bounded text with the surrounding whitespace removed.

    Stripped where a name is not, because a name with a trailing space is the
    wearer's business while an id with one is a lookup that silently misses.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped[:limit]
    return fallback


def _frac(value):
    """A canvas fraction, or None when this is not one.

    `bool` is rejected before `int`, because `True` IS an `int` in Python and a
    mark at x=True is a mark hard against the right-hand edge.  NaN and the
    infinities are caught arithmetically -- `value != value` for the first,
    `value * 0 != 0` for the second -- because this build has no `math`.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value * 0 != 0:
        return None
    if value < 0 or value > 1:
        return None
    return float(value)


# How deep an unknown value is followed before it is dropped.  Four is deeper
# than any shape this schema has ever had and shallow enough that a maliciously
# nested file cannot turn a load into a stack overflow.
CARRY_DEPTH = 4


def _carryable(value, depth=0):
    """Can this unknown value survive a `json.dumps` round trip?

    THE CARRY RULE EXISTS FOR ONE PURPOSE: a badge configured on a NEWER BUILD
    keeps its data through a downgrade.  That data arrived as JSON, so anything
    JSON cannot express did not come from a newer build -- it came from a
    hand-built dict or a test -- and carrying it would produce a state
    `card_store.save` then refuses to serialise.  A `TypeError` inside
    `json.dumps` is not a cosmetic failure: it is the wearer's commit, lost, on
    the frame they pressed DONE.

    NaN and the infinities are refused with `bytes` and everything else,
    because they are not valid JSON either -- CPython emits `NaN` and a stricter
    reader on the other side of a sync would reject the whole file.
    """
    if value is None or isinstance(value, (bool, str)):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return value == value and value * 0 == 0
    if depth >= CARRY_DEPTH:
        return False
    if isinstance(value, (list, tuple)):
        for item in value:
            if not _carryable(item, depth + 1):
                return False
        return True
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                return False
            if not _carryable(value[key], depth + 1):
                return False
        return True
    return False


def _stickers(value):
    if not isinstance(value, (list, tuple)):
        return []
    marks = []
    for item in value[:STICKER_SCAN_MAX]:
        if len(marks) >= MAX_STICKERS:
            break
        if not isinstance(item, dict):
            continue
        kind = _ident(item.get("kind"), "")
        if not kind:
            continue
        x = _frac(item.get("x"))
        y = _frac(item.get("y"))
        if x is None or y is None:
            # Park an unreadable coordinate at the centre rather than dropping
            # it.  THIS APP CAN MOVE A MARK, which is the whole difference from
            # `poster`, where the same case is dropped: a viewer that stacked
            # every damaged mark in the middle of somebody's face would be
            # damaging a picture nobody asked it to touch, while an editor that
            # dropped one would be losing a sticker the wearer placed.
            x = 0.5 if x is None else x
            y = 0.5 if y is None else y
        marks.append({"kind": kind, "x": x, "y": y})
    return marks


def repair_badge(value):
    """Anything at all into one drawable badge.  Never raises.

    UNKNOWN KEYS ARE CARRIED.  A badge configured on a newer build loses the
    FEATURES on a downgrade and not the DATA, which is the difference between
    "this build cannot show your new thing" and "your badge is gone".
    """
    badge = new_badge()
    if not isinstance(value, dict):
        return badge
    for key in value:
        if (key not in BADGE_KEYS
                and isinstance(key, str) and _carryable(value[key])):
            badge[key] = value[key]
    badge["name"] = _text(value.get("name"), DEFAULT_NAME, NAME_MAX)
    badge["background"] = _ident(value.get("background"), DEFAULT_BACKGROUND)
    badge["stickers"] = _stickers(value.get("stickers"))
    # A LEGACY BADGE HAS NO EFFECT AND DOES NOT GAIN ONE.  Every badge written
    # before 2026-08-23 is missing this key, and `new_badge`'s default is for a
    # badge nobody has made yet -- honouring it here would filter a card the
    # wearer already looked at and approved.  So an absent key is NONE, and only
    # a fresh badge or an explicit APPLY produces anything else.
    #
    # AN UNRECOGNISED ID IS KEPT, which is rule 3 of this schema applied to one
    # more field: a badge configured on a build with more effects than this one
    # degrades to "no effect" on the panel and keeps the id on disk, so it starts
    # working again on the way back up. `effects.apply` is the one place that
    # decides an unknown id draws as NONE, and it is shared with `poster`.
    if "effect" in value:
        badge["effect"] = _ident(value.get("effect"), effects.NONE)
    else:
        badge["effect"] = effects.NONE
    # DERIVED, ALWAYS, AND NEVER READ BACK.  Whatever `face` the file carried is
    # discarded: the owner's ruling is that the skin dictates it, so a state
    # that disagrees is a state that was hand-edited or written by a build with
    # a different rule, and honouring it would be honouring the rule this app
    # does not have.
    badge["face"] = faces.face_of(badge["background"])
    return badge


def _home(value):
    home = {"on": False, "recipe": 0}
    if not isinstance(value, dict):
        return home
    if value.get("on") is True:
        home["on"] = True
    recipe = value.get("recipe")
    if isinstance(recipe, int) and not isinstance(recipe, bool):
        if 0 <= recipe <= 0xFFFF:
            home["recipe"] = recipe
    return home


def repair(value):
    """Anything at all into a whole state.  Never raises.  Total.

    `badgecard/tests/test_card_fuzz.py` drives this over generated garbage and
    asserts two things of every result: `invariants` is empty, and repairing it
    a second time changes nothing.  Idempotence is the property that makes a
    save/load round trip safe to run a thousand times.
    """
    state = new_state()
    if not isinstance(value, dict):
        return state
    for key in value:
        if (key not in ("schema", "active", "badges", "home", "brightness")
                and isinstance(key, str) and _carryable(value[key])):
            state[key] = value[key]
    state["schema"] = SCHEMA

    # CLAMPED RATHER THAN CARRIED.  Left out of the known-key list above it
    # would arrive as an unvalidated pass-through, and `display.backlight` takes
    # whatever it is handed: a hand-edited 0 is a panel the wearer cannot read
    # their way out of, which is the exact trap the ladder's floor exists to
    # close.  A non-number is the factory level, not an end of the ladder.
    state["brightness"] = backlight.clamp(value.get("brightness"))

    # EVERY CARRIED ENTRY IS REPAIRED, NOT JUST THE WORN ONE, and that is not
    # wasted work on a feature that no longer exists.  `invariants` is asserted
    # over whole states by the fuzz suite, `card_store.save` has to be able to
    # serialise every byte it is handed, and `badgelink` writes this file with a
    # rule of "change one key, carry the rest verbatim" -- so a legacy slot that
    # repair skipped would be an unvalidated dict riding inside a state three
    # other apps read.  Repairing it costs a load nobody watches and keeps the
    # file's ONE promise: anything in it is drawable.
    raw = value.get("badges")
    badges = []
    if isinstance(raw, (list, tuple)):
        for item in raw[:CARRY_BADGES]:
            badges.append(repair_badge(item))
    if not badges:
        badges = [new_badge()]
    state["badges"] = badges

    index = value.get("active")
    if not isinstance(index, int) or isinstance(index, bool):
        index = 0
    if index < 0 or index >= len(badges):
        index = 0
    state["active"] = index

    state["home"] = _home(value.get("home"))
    return state


def invariants(state):
    """Every rule this schema promises, as a list of the ones it is breaking.

    A LIST RATHER THAN A BOOL, because a failing invariant has to say WHICH one
    in a test's message; `assertEqual([], invariants(s))` prints the violation
    where `assertTrue(ok(s))` prints `False is not True`.
    """
    bad = []
    if state.get("schema") != SCHEMA:
        bad.append("schema")
    brightness = state.get("brightness")
    if (isinstance(brightness, bool) or not isinstance(brightness, int)
            or brightness < backlight.MIN or brightness > backlight.MAX):
        bad.append("brightness")
    badges = state.get("badges")
    if not isinstance(badges, list):
        bad.append("badges is not a list")
        return bad
    if not badges:
        bad.append("badges is empty")
    if len(badges) > CARRY_BADGES:
        bad.append("more than %d carried badges" % CARRY_BADGES)
    index = state.get("active")
    if not isinstance(index, int) or isinstance(index, bool):
        bad.append("active is not an int")
    elif badges and (index < 0 or index >= len(badges)):
        bad.append("active is out of range")
    for position in range(len(badges)):
        badge = badges[position]
        if not isinstance(badge, dict):
            bad.append("badge %d is not an object" % position)
            continue
        for key in BADGE_KEYS:
            if key not in badge:
                bad.append("badge %d has no %s" % (position, key))
        if not isinstance(badge.get("name"), str):
            bad.append("badge %d name" % position)
        elif len(badge["name"]) > NAME_MAX:
            bad.append("badge %d name is too long" % position)
        if not isinstance(badge.get("background"), str):
            bad.append("badge %d background" % position)
        elif badge.get("face") != faces.face_of(badge["background"]):
            bad.append("badge %d face does not follow its skin" % position)
        # A STRING, AND NOT NECESSARILY A KNOWN ONE.  Asserting membership of
        # `effects.SHIPPED` here would make rule 3 unrepresentable: a state from
        # a build with more effects is a valid state that this build draws
        # without the effect, and an invariant that called it broken would have
        # `repair` throwing the id away to satisfy itself.
        if not isinstance(badge.get("effect"), str) or not badge["effect"]:
            bad.append("badge %d effect" % position)
        marks = badge.get("stickers")
        if not isinstance(marks, list):
            bad.append("badge %d stickers" % position)
            continue
        if len(marks) > MAX_STICKERS:
            bad.append("badge %d has more than %d stickers"
                       % (position, MAX_STICKERS))
        for mark in marks:
            if not isinstance(mark, dict):
                bad.append("badge %d has a mark that is not an object"
                           % position)
                continue
            if not isinstance(mark.get("kind"), str) or not mark["kind"]:
                bad.append("badge %d mark kind" % position)
            for axis in ("x", "y"):
                if _frac(mark.get(axis)) is None:
                    bad.append("badge %d mark %s" % (position, axis))
    home = state.get("home")
    if not isinstance(home, dict):
        bad.append("home")
    else:
        if home.get("on") not in (True, False):
            bad.append("home.on")
        recipe = home.get("recipe")
        if (not isinstance(recipe, int) or isinstance(recipe, bool)
                or recipe < 0 or recipe > 0xFFFF):
            bad.append("home.recipe")
    return bad


# ---------------------------------------------------------------------------
# the wallpaper recipe
# ---------------------------------------------------------------------------

# How finely a mark's position is stamped into the recipe.  Ten-thousandths of
# the canvas: finer than either pixel grid can resolve (a LORES pixel is 1/160
# of the width), so two states that would bake identical films stamp identical
# recipes and two that would not, do not.
RECIPE_UNITS = 10000

# Bumped whenever the BAKER changes what it draws from the same state.  The
# recipe is "would re-baking produce the same film?", and the answer is no when
# the painter has changed even though nothing the wearer owns has.
#
# 2 since 2026-08-21: the baker asked for the 24 px mark sheet, which had been
# deleted with the rest of LORES, so every mark in a baked film came out a hollow
# emerald square.  It now opens the 36 px sheet and downscales at blit.  A badge
# that baked a wallpaper before that fix holds a film full of empty boxes and a
# stamp that still matches its state -- so without this bump the app would compare
# recipes, find them equal, and go on showing it.
BAKE_VERSION = 2


def units(value):
    return int(value * RECIPE_UNITS + 0.5)


def recipe_parts(state):
    """What the installed film is a function of, as hashable parts.

    THE SCHEMA'S OWN STATEMENT of the bake's inputs, kept here beside the fields
    rather than in the baker, so adding a field that changes the picture and
    forgetting to stamp it is a change to THIS function and shows up in its
    test.

    DELIBERATELY ABSENT: `active`, and any other entry in `badges`.  The film is
    a picture of the badge being WORN, so a position in a list cannot move a
    pixel.  That argument was written against the five-slot product, where it
    also stopped a re-bake every time the wearer switched to an identical badge;
    the slots are gone (2026-08-24) and the rule outlived them unchanged, because
    a store that still CARRIES legacy entries must not stamp them into the recipe
    -- a badge whose ignored slot 3 differed from another's would otherwise
    re-bake an identical wallpaper.  A field that is switched off contributes a
    constant rather than nothing, so turning it back on cannot collide with a
    state that never had it.

    DELIBERATELY ABSENT TOO, AND FOR A DIFFERENT REASON: `effect`.  It is not
    that stamping it would be expensive -- it is that the baked wallpaper does
    not carry it.  The owner ruled on 2026-08-18 that a baked film is *the
    artwork with only the scrim over it*, and `card_bake._finish` ships all five
    of its filter scales at zero because of that ruling.  An effect that changed
    the film would be re-opening a decision this lane was not asked to reopen,
    so the effect is a property of the CARD and not of the home screen, and this
    function stays the statement of what the FILM is a function of.  If that is
    ever reversed, the change is one part here plus a `BAKE_VERSION` bump, and
    the constant-rather-than-nothing rule above is how to add it.
    """
    badge = active(state)
    parts = ["pgw", BAKE_VERSION, badge["background"]]
    if badge["name"]:
        parts.append("name")
        parts.append(badge["name"])
        parts.append(badge["face"])
    else:
        parts.append("noname")
    marks = badge["stickers"]
    if marks:
        for mark in marks:
            parts.append(mark["kind"])
            parts.append(units(mark["x"]))
            parts.append(units(mark["y"]))
    else:
        parts.append("nomarks")
    return tuple(parts)
