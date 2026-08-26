"""Read the badge's state, and never do anything else to it.

TOTAL BY CONSTRUCTION.  Every path returns a drawable badge: no file, an empty
file, a directory where the file should be, bytes that are not JSON, JSON that
is not an object, an object whose every field is the wrong type -- each of them
is a poster, and none of them is a traceback.  That matters more here than it
does in the editor, because an escaping exception on the launch path reaches
`badgeware.fatal_error`, which flips the panel to HIRES, draws a modal, BLOCKS
until a keypress and then resets the badge.

WHY NOT `identity_store.load` AND `identity_model.repair`.  Two reasons, and
the first one is not about bytes:

* `identity_store` is a READ-WRITE module.  Its `save`, `erase` and
  `undo_erase` are the only unrecoverable data-loss shape in this repository,
  and a viewer that imports them is a viewer one typo away from owning them.
  This module has no `open(..., "w")` in it and `test_poster_app` asserts that
  the whole app directory has none either.
* `identity_model` is 48,490 bytes of schema, migration and enum tables to
  answer six questions about six fields, and it imports `json` to do it.  A
  worn badge parses that on every launch to draw a picture.  `card_model` is
  smaller and the same argument applies to it: this app is a VIEWER, and a
  viewer that imports an editor's schema is a viewer that has to be updated
  every time the editor is.

WHAT IT READS, AND WHY THAT MOVED.  The file is `badgecard`'s store, which
holds up to five badges and an `active` index; `select` picks the one being
worn and hands `coerce` the same flat six-field shape it has always been given,
so the agreement suite below is untouched by the change.  It used to read
`identity`'s `/state/identity.json`, and `select` still passes that flat shape
through unchanged -- a badge whose editor has not been replaced yet keeps
working, and so does one whose store this build has never seen.

WHAT THAT COSTS, STATED HONESTLY.  `repair` COERCES -- it will turn the string
"80" into brightness 80 and the integer 7 into the name "7".  This reader does
not: a field of the wrong type is the default instead.  The two therefore agree
on every state identity itself can write, which is the only kind a badge
actually has, and `poster/tests/test_badge_state.py` pins exactly that against
`identity_model.repair` over the editor's own corpus rather than leaving it as
a claim.  Where they differ -- a hand-edited file with a quoted number in it --
this app shows the default and the editor shows the coerced value.  That is a
visible difference on a badge nobody has, and the alternative is 48 KB on the
launch path of every badge that exists.

`source` records which arm ran, so the browser lane can tell "read the file"
apart from "fell back", which is a distinction no screenshot can make.
"""

import json

import backlight
import effects


# The five fields the picture is made of.  Held here as literals rather than
# imported from `identity_model` for the reason the docstring gives; the test
# pins every one of them against that module.
#
# BRIGHTNESS IS THE EXCEPTION AND IT IS NOT A LITERAL HERE ANY MORE.  It was
# `DEFAULT_BRIGHTNESS = 80` beside `BRIGHTNESS_MIN`/`MAX`, a verbatim duplicate
# of `identity_model`'s pair -- "two copies of one number, already a drift
# hazard", as `docs/design/idle-and-off.md` §3.3 put it.  Since 2026-08-23 the
# ladder has one home in `shared/backlight.py`, this app vendors it, and the
# idle dim reads the same constants, so the drift is gone rather than watched.
DEFAULT_NAME = ""
DEFAULT_LINE2 = ""
DEFAULT_FACE = "badgewaremax"
# MOVED WITH `card_model.DEFAULT_BACKGROUND`, 2026-08-26, and it has to move
# with it: `badgecard/tests/test_card_model.py` reads this file as TEXT and
# fails when the two literals disagree, because a viewer that defaulted
# differently from the editor would draw a different badge for the same file.
DEFAULT_BACKGROUND = "glyph.ring-buffer"
DEFAULT_MOTION = True
# NONE, AND NOT `effects.DEFAULT`.  This is the VIEWER's default -- what to draw
# when the file does not say -- and a file that does not say is a badge nobody
# has given an effect.  `card_model.DEFAULT_EFFECT` is the other kind of default:
# what a badge nobody has CONFIGURED ships wearing, which only the editor
# creates.  Two different questions, and answering them with one constant would
# mean a legacy badge acquired a filter by being looked at.
DEFAULT_EFFECT = effects.NONE

# The editor's own bounds.  A name longer than this is truncated rather than
# drawn, because the editor truncates it too and the two apps must draw the
# same string; a mark beyond the cap is dropped for the same reason.
NAME_MAX = 12
LINE2_MAX = 20
ID_MAX = 48
MAX_STICKERS = 24
# How far into a hostile stickers list to look before giving up.  The editor's
# number: a list of a million entries is not a badge, and scanning it is a
# launch that never finishes.
STICKER_SCAN_MAX = 256

# Which arm produced the last state: "file", "default" (nothing readable there)
# or "shape" (readable, but not an object).
source = "default"


def _text(value, fallback, limit):
    if isinstance(value, str):
        return value[:limit]
    return fallback


def _ident(value, fallback):
    """An id: bounded text with the surrounding whitespace removed.

    Stripped where a name is not, because a name with a trailing space is the
    wearer's business while an id with one is a lookup that silently misses.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped[:ID_MAX]
    return fallback


def _frac(value):
    """A canvas fraction, or None when this is not one.

    `bool` is rejected before `int`, because `True` is an `int` in Python and a
    mark at x=True is a mark at the right-hand edge of the canvas.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # NaN and the infinities: `value != value` catches the first and
    # `value * 0 != 0` the second, which is the test `identity_model` uses and
    # the only one that works without `math` on this build.
    if value != value or value * 0 != 0:
        return None
    if value < 0 or value > 1:
        return None
    return float(value)


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
            # The editor parks an unreadable coordinate at the centre so the
            # wearer can find and move it.  A viewer cannot move anything, and
            # stacking every damaged mark in the middle of somebody's face is
            # worse than leaving it out of a picture they did not ask for.
            continue
        marks.append({"kind": kind, "x": x, "y": y})
    return marks


def defaults():
    """A badge nobody has configured.  A fresh dict every call.

    A module-level default that callers mutate is how `profile` ended up
    writing defaults over real state; nothing here writes anything, but the
    same dict handed to two readers is the same class of bug.
    """
    return {
        "name": DEFAULT_NAME,
        "line2": DEFAULT_LINE2,
        "face": DEFAULT_FACE,
        "background": DEFAULT_BACKGROUND,
        "stickers": [],
        "brightness": backlight.DEFAULT,
        "motion": DEFAULT_MOTION,
        "effect": DEFAULT_EFFECT,
    }


def coerce(value):
    """Anything at all into the six fields the poster draws.  Never raises."""
    state = defaults()
    if not isinstance(value, dict):
        return state
    state["name"] = _text(value.get("name"), DEFAULT_NAME, NAME_MAX)
    state["line2"] = _text(value.get("line2"), DEFAULT_LINE2, LINE2_MAX)
    state["face"] = _ident(value.get("face"), DEFAULT_FACE)
    state["background"] = _ident(value.get("background"), DEFAULT_BACKGROUND)
    state["stickers"] = _stickers(value.get("stickers"))
    # THROUGH `backlight.clamp` UNCONDITIONALLY since 2026-08-23, where this
    # used to gate on `isinstance(..., int)` first.  That gate made this reader
    # disagree with the launcher's and the editor's on a FLOAT: a store holding
    # `55.5` gave them 55 and gave this app the factory 80, so the panel would
    # have jumped brightness across the 45-second handoff -- exactly the drift
    # `shared/backlight.py` exists to end.  `clamp` owns every hostile case
    # (bool before int, NaN, the infinities, a non-number) and returns an int.
    state["brightness"] = backlight.clamp(value.get("brightness"))
    motion = value.get("motion")
    if isinstance(motion, bool):
        state["motion"] = motion
    # KEPT AS WRITTEN, INCLUDING AN ID THIS BUILD DOES NOT KNOW.  This reader
    # does not decide what an effect means -- `effects.apply` does, in the one
    # place both apps share, and it draws an unrecognised id as NONE.  Coercing
    # it here would put a second opinion in a viewer, which is the drift this
    # module's docstring is about.
    state["effect"] = _ident(value.get("effect"), DEFAULT_EFFECT)
    return state


def select(value):
    """The badge being WORN, out of a store that may hold several.

    `badgecard` keeps up to five badges in one file -- `{"active": <int>,
    "badges": [ ... ]}` -- and exactly one of them is on the wearer's chest.
    This picks it; everything downstream sees the same flat six-field shape it
    always did, so `coerce` and its whole agreement suite are untouched.

    TOTAL, AND IT FALLS BACK TO THE VALUE ITSELF.  A file with no `badges` list
    is `identity`'s flat shape, which this app read for months and which a badge
    that has not been migrated still carries; a `badges` list that is empty, or
    an `active` index pointing past the end, is a store this app cannot make
    sense of and the defaults are a better answer than a traceback.

    `active` is validated the same way `card_model` validates it, and for the
    same reason: `True` IS an `int` in Python, so an `active` of `True` would
    select badge 1 rather than being rejected.

    IT ALSO CARRIES THE ROOT'S DEVICE FIELDS onto the selected badge -- see
    `DEVICE_KEYS` below for why brightness is one and nothing else is.
    """
    if not isinstance(value, dict):
        return value
    badges = value.get("badges")
    if not isinstance(badges, list) or not badges:
        return value
    index = value.get("active")
    if not isinstance(index, int) or isinstance(index, bool):
        index = 0
    if index < 0 or index >= len(badges):
        index = 0
    badge = badges[index]
    if not isinstance(badge, dict):
        # AN UNUSABLE BADGE IS NOT AN UNUSABLE PANEL.  This returned a bare `{}`
        # until 2026-08-23, which threw away the one field that is explicitly a
        # property of the SCREEN rather than of a badge -- so a store with a
        # broken badge in it also lost the wearer's brightness.
        return _device({}, value)
    return _device(badge, value)


# The fields that describe the PANEL rather than a badge, and therefore live at
# the ROOT of the store rather than inside one of its five badges.
#
# THERE IS EXACTLY ONE AND THE REASON IS THE WHOLE POINT: brightness is a
# property of the screen, so switching between five saved badges must not change
# how bright the badge is.  Before 2026-08-23 `coerce` read `brightness` out of
# whatever `select` returned, which for a multi-badge store is a BADGE -- so a
# per-badge brightness was what the format actually said, and no editor could
# write one.  `badgecard`'s BRIGHTNESS row writes the root; this is the reader
# that agrees with it.
DEVICE_KEYS = ("brightness",)


def _device(badge, root):
    """`badge` with the ROOT's device fields laid over it.

    A COPY, never a mutation: this module is read-only by ruling and by test,
    and writing into the parsed store would be a write.

    THE ROOT WINS, and that is what "device field" means (corrected 2026-08-23).
    This first carried the root's value only where the badge had none, on the
    theory that a hand-edited badge-local value should be honoured -- and that
    was a trap: `card_model.repair_badge` deliberately CARRIES unknown keys, so
    a badge dict that once held `"brightness": null` keeps it through every save
    and load, permanently masking the root, and `badgecard`'s BRIGHTNESS row --
    which writes the root -- could never clear it.  The wearer would have had a
    brightness slider with no effect and no way to find out why.

    `identity`'s older FLAT shape is unaffected either way: `select` returns
    early for a store with no `badges` list, so this is only ever reached for a
    real multi-badge store, where a badge-local device field is junk by
    construction.
    """
    if not isinstance(root, dict):
        return badge
    extra = None
    for key in DEVICE_KEYS:
        if key in root:
            if extra is None:
                extra = dict(badge)
            extra[key] = root[key]
    return badge if extra is None else extra


def read(path):
    """The badge on disk, or a default badge.  The app's only file access."""
    global source
    source = "default"
    try:
        with open(path) as handle:
            raw = handle.read()
    except Exception:  # noqa: BLE001 - OSError on device, more on a host
        return defaults()
    try:
        value = json.loads(raw)
    except Exception:  # noqa: BLE001 - ValueError, and whatever a truncated
        # file gives a future parser
        return defaults()
    source = "file" if isinstance(value, dict) else "shape"
    return coerce(select(value))
