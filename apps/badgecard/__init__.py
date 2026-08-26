"""BADGE CARD -- the worn badge, and the five things you can change about it.

ONE CARD, NOT FIVE, SINCE 2026-08-24.  The owner removed the save slots and put
a RESET BADGE row in their place: *"you create your name badge, if you don't like
it you can edit it, or you can wipe it and start over."*  The five things above
are still five -- name, skin, stickers, effect, home screen -- and there is now
one badge wearing them.  A FULL wipe, which is a different thing, is staff-only
over serial: `scripts/badge-wipe.sh` and `docs/staff-badge-wipe.md`.

THE HARDWARE SEAM AND NOTHING ELSE.  Badgeware's globals arrive here as
builtins, are handed to a pure controller and a view, and never leave this file.
`card_app.frame(now_ms, buttons) -> plan` reads a clock it is given and writes
through a callable it is given; `card_view.draw(plan)` owns every pixel.  That
split is what lets the whole app be tested on CPython in seconds, and it is
`identity`'s, which proved it.

WHAT THIS APP IS.  A supplemental fun nametag -- every attendee already has a
paper badge with their real name on it -- so a crash is unacceptable and
legibility is a nice-to-have rather than the product.  That ordering decides the
`_try` wrapper below and the plain-name painter of last resort.

    at rest      the badge.  Zero chrome, one name (D1).
    any press    the menu.  NAME, SKIN, STICKERS, EFFECT, SAVE TO HOME,
                 RESET BADGE.
    HOME         the launcher.  `on_exit` runs first, so nothing is lost.

HOW IT ARRIVES, and this file's shape is that answer.  Threads are compiled out
(`MICROPY_PY_THREAD (0)`), so nothing animates during a blocking call -- but a
module body is a SEQUENCE of statements and `badgeware.launch()` blocks inside
`__import__` of THIS module, so every `display.update()` between two statements
below is a frame the wearer actually sees.  The arrival is `poster`'s, staged
cheapest-first:

    stage 0   a dark field, before a single import.  It replaces the launcher's
              leftover frame, which is the difference between "it opened" and
              "it hung".
    stage 1   THE NAME, at its final face, size and position.  The badge is
              already readable at a metre here, which is most of what a badge
              is for.
    stage 2   the artwork behind it.  Exactly ONE of `skins` (667,219 B) or
              `glyphskin` (42,075 B) is parsed, chosen by the catalogue.
    stage 3   the marks, and only if the badge has any.

DEGRADE, NEVER FAIL.  An escaping exception here is not a log line:
`badgeware.fatal_error` flips the panel to HIRES, draws a modal, BLOCKS until a
keypress and then RESETS the badge.  So every stage is wrapped, a failure leaves
the last good stage on screen, and a failure inside the frame loop latches a
plain-name painter.  The app always reaches `run()`, because a badge showing
only a name is still a badge and a modal is not.
"""

import sys


# WHERE THIS APP WAS INSTALLED, DERIVED AND NEVER HARDCODED.  Both
# `badgeware.launch()` and the playground's `pg_runtime.launch_app` start an app
# with `__import__(path)` against its install directory, so this module's own
# `__name__` IS that directory.  A literal here is a real defect and not a
# tidiness one: `identity`'s records a build that would have prepended the
# NEIGHBOUR's directory to its own search path and imported that app's modules
# instead of its own -- silently running HIRES as LORES.
APP_ROOT = (__name__ if __name__.startswith("/system/apps/")
            else "/system/apps/badgecard")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

import badgeware  # noqa: F401,E402 - presence check; the API arrives as globals


# THE PANEL MODE BEFORE THE FIRST PAINT AND BEFORE ANY CHROME.  `badge.mode`
# rebinds `builtins.screen` to a new surface, and `ui.Chrome.__init__` reads
# `screen.width` to derive its scale, face, point size and every band.  A chrome
# built before this line would size itself to the wrong canvas -- silently,
# because both canvases are valid.
#
# HIRES, UNCONDITIONALLY, BY THE OWNER RULING OF 2026-08-21: this app and
# `poster` are the identity surfaces and they are 320x240 1:1.  There is no
# second build any more -- `variant.py` and `badgecard/host/build_variants.py`
# are deleted, one source tree is one app -- so the panel is a CONSTANT here
# rather than a substituted line, and there is nothing left to disagree about.
# `badgecard/tests/test_card_resolution.py` walks the package's AST and fails if
# any module names a panel mode, because everything downstream is supposed to
# read the resolution off the surface it was handed: `ui.Chrome` off
# `screen.width`, `glyphskin` off the cell geometry, `skins` off the buffer, the
# mark sheet off `chrome.scale`.
badge.mode(HIRES | VSYNC)

# THE CASELIGHTS ARE NOT THIS APP'S, WHICH IS EXACTLY WHY IT ZEROES THEM.
# `badge.caselights` is process-global and survives a `launch()`, so a badge
# whose previous app left them lit would arrive here glowing for no reason --
# and one of the previous apps IS the launcher, whose hold indicator drives them
# to full.
badge.caselights(0)

# The dark field stage 0 paints and the fallback painter falls back to.  The
# same three channels `poster.DARK_RGB` gives the renderer, held as a literal
# because stage 0 runs before any import at all; `test_card_app.py` reads both
# out of the source and fails if they ever differ, so this is a CHECKED
# duplicate rather than a hopeful one.
DARK = (9, 14, 24)

# THE FRAME CLEAR MOVES INTO THIS APP, AND WITHOUT CHANGING COLOUR.  The managed
# loop calls `badge.clear()` at the top of every frame and `Badge.clear` skips
# the fill when `default_clear` is None.  Taking the fill over -- with the pen
# the loop would have used, captured here -- is what lets the staged paints below
# survive until the app chooses to overwrite them.
#
# IT IS NOT AN OPTIONAL FILL.  A skin's artwork is not guaranteed opaque in every
# pixel (`skin.supabase` composites 53 of them at less than full alpha), so a
# full-screen blit over the PREVIOUS frame is not the same picture as the same
# blit over black.
_previous_clear = badge.default_clear
_clear_pen = _previous_clear
badge.default_clear = None
screen.pen = color.rgb(DARK[0], DARK[1], DARK[2])
screen.clear()
display.update()
print("CARD_STAGE n=0 modules=%d" % len(sys.modules))

import loading  # noqa: E402

# Five units of real work between here and the first interactive frame.  The
# app name is DERIVED from the install path rather than passed, so a tile
# installed under any name logs itself correctly with no argument -- and `begin`
# never raises: a failure returns a handle whose every method does nothing, so
# the app that follows is unchanged.
_load = loading.begin(5)

import card_model as model  # noqa: E402
_load.tick("-- schema")
import card_store as store  # noqa: E402
_load.tick("-- store")
import ui  # noqa: E402
import poster as poster_module  # noqa: E402
_load.step("-- renderer")
import card_app  # noqa: E402
_load.step("-- controller")
import card_view  # noqa: E402
_load.step("-- view")
import card_bake  # noqa: E402
_load.step("-- wallpaper")
import card_cache  # noqa: E402
import time  # noqa: E402


state, load_status = store.load()
_load.step("-- 1 badge from %s" % store.STATE_PATH)

chrome = ui.Chrome()

# THE BAKER IS CONSTRUCTED, NOT USED.  Nothing in it allocates until the first
# bake -- the 76,800-byte work canvas, the mark sheet and the glyph pack are all
# lazy -- and `card_bake` itself defers `skins` and `glyphskin`, so building it
# here costs a handful of `color.rgb` objects and buys the boot-time
# reconciliation below.
baker = card_bake.Baker(image, color, vec2, rect, font)

_writes = 0


def _write(value, milestone=False):
    """THE ONLY `card_store.save()` CALL SITE, and the controller is HANDED it.

    An injected callable rather than an import is what keeps `card_app` free of
    file I/O, and it is also the one place a write can be counted: the fast lane
    passes a list's `append` and asserts exactly which presses commit and which
    are navigation (B6).
    """
    global _writes
    _writes += 1
    store.save(value, milestone=milestone)
    print("CARD_SAVE n=%d milestone=%d" % (_writes, 1 if milestone else 0))


# A store that did not load cleanly is written back at once by the controller,
# so the next boot reads a good file rather than recovering again.

# THE DISK IS THE TRUTH AND THE STATE IS THE CACHE.  The launcher reads
# `/state/wallpaper.pgw` without consulting this app at all, so a film deleted
# by a host -- or a state restored from a backup written before the bake -- would
# otherwise leave the two permanently disagreeing about whether the home screen
# is the wearer's badge.  One 16-byte read, once.
try:
    if baker.reconcile(state):
        _write(state)
except Exception as _error:  # noqa: BLE001 - a wallpaper is not worth a reset
    print("CARD_FAIL stage=reconcile error=%r" % _error)

# THE PANEL AND THE IDLE CLOCK, one object (`docs/design/idle-and-off.md`).
#
# `panel.restore()` PUTS THE WEARER'S STORED LEVEL ON THE PANEL AT OPEN, and
# since the owner moved the BRIGHTNESS row to `settings` (2026-08-24) that is the
# only thing this app does with it: it reads `state["brightness"]` and never
# writes it.  It has to read it -- leaving an app is `machine.reset()`, so the
# level the wearer chose in `settings` reaches this app through the file and
# through nothing else, and an app that skipped the restore would open at
# whatever the last app left on the panel.  (Before 2026-08-23 this app never set
# the backlight at all; a paragraph of that history is in `idle-and-off.md` §5.2,
# under the entry-file cap.)
#
# `poster_ms=None`: this app dims and stops.  Only the LAUNCHER can open an app
# (`stock-v3.0.1-main.py` takes one path out of the menu and `reset()`s when it
# returns), so a second rung here could only mean exiting the editor mid-edit.
# `badgecard/README.md` §Idle records that limitation rather than hiding it.
#
# `dim_ms=idle.CARD_DIM_MS`: 30 s, EXPLICITLY.  The module default moved to 20 s
# on 2026-08-24 and this app did not -- that ruling scoped itself to the home
# screen -- so naming the number keeps the divergence a decision rather than an
# inheritance.  `shared/idle.py`'s `CARD_DIM_MS` has the rest.
import backlight  # noqa: E402
import idle  # noqa: E402

def _light(pct):
    """The panel, and NEVER a reset for it: `panel.frame()` runs in the frame
    loop, where an escaping exception reaches `fatal_error`."""
    try:
        display.backlight(backlight.fraction(pct))
    except Exception as error:  # noqa: BLE001
        print("CARD_FAIL stage=backlight error=%r" % error)


panel = idle.Panel(_light, time.ticks_ms, state["brightness"],
                   backlight.IDLE_PERCENT,
                   dim_ms=idle.CARD_DIM_MS, poster_ms=None)
panel.restore()

app = card_app.CardApp(
    state, _write,
    bake=baker.bake, unbake=baker.remove, recipe=card_bake.stamp,
    now_ms=time.ticks_ms(), load_status=load_status,
    ticks_diff=time.ticks_diff,
    logical=(chrome.width // chrome.scale, chrome.height // chrome.scale))


class Buttons:
    """The five keys, as the controller's `pressed`/`held` contract.

    A named object rather than the raw `badge` module so the controller can be
    driven by a fake, and so the key NAMES are strings the tests can write
    rather than firmware constants they would have to import.
    """

    _MAP = {"A": BUTTON_A, "B": BUTTON_B, "C": BUTTON_C,
            "UP": BUTTON_UP, "DOWN": BUTTON_DOWN}

    def pressed(self, key):
        return badge.pressed(self._MAP[key])

    def held(self, key):
        return badge.held(self._MAP[key])


buttons = Buttons()
view = None
failed = ""
plain = False


def _stage(number):
    display.update()
    print("CARD_STAGE n=%d modules=%d" % (number, len(sys.modules)))


def _try(number, draw):
    """Draw a stage, present it, and never let it reach `fatal_error`.

    A failed stage leaves the LAST GOOD one on the panel, which is why the
    stages are ordered by value: a badge that got as far as its name and then
    lost its artwork still says who is wearing it.
    """
    global failed, view
    try:
        draw()
    except Exception as error:  # noqa: BLE001 - see the module docstring
        if number == 1:
            view = None
        failed = "%s:%s" % (number, error)
        print("CARD_FAIL stage=%d error=%r" % (number, error))
        sys.print_exception(error)
        return False
    _stage(number)
    return True


def _clear():
    if _clear_pen is not None:
        screen.pen = _clear_pen
        screen.clear()


def _plain_badge():
    """The painter of last resort: a dark field and the name in the ROM face.

    Reached only when the renderer itself has raised, so it may not touch it.
    Deliberately the simplest thing that is still a badge -- if the artwork
    cannot be drawn, the wearer's name still can be, and a name on a dark field
    is a name badge.
    """
    screen.pen = color.rgb(DARK[0], DARK[1], DARK[2])
    screen.clear()
    screen.font = font.sins
    screen.pen = color.white
    screen.text(model.active(state)["name"] or "BADGE", 6, 50, 2)


# -- stage 1: the name, over that field --------------------------------------
#
# The face, the size and the position are FINAL here: the renderer runs the same
# face / fit / outlined ladder the product uses, so the artwork simply appears
# behind the name and nothing reflows.
_boot_plan = app.plan(time.ticks_ms())


def _name_only():
    global view
    view = card_view.CardView(screen, image, color, font, vec2, rect, chrome)
    view.stage_name(_boot_plan)


def _artwork():
    _clear()
    view.stage_artwork(_boot_plan)


def _whole_badge():
    _clear()
    view.badge_screen(_boot_plan)


_try(1, _name_only)

# -- stage 2: the artwork, behind the name -----------------------------------
#
# ARMED BETWEEN THE STAGES, exactly as `poster` arms it and with the same stamp,
# so the editor and the badge agree about what a cached picture is -- or they
# miss and re-render.  Design: `docs/design/backdrop-cache.md`.
if view is not None:
    try:
        view.poster.cache_stamp = poster_module.cache_stamp(APP_ROOT)
    except Exception as _error:  # noqa: BLE001 - a cache is not worth a stage
        print("CARD_FAIL stage=cache error=%r" % _error)
    _try(2, _artwork)

# -- stage 3: the marks, only if the badge has any ---------------------------
if view is not None and model.active(state)["stickers"]:
    _try(3, _whole_badge)


_badge = model.active(state)
# `variant=` IS GONE FROM THIS LINE, deliberately.  It reported a CONSTANT, and
# with one build a constant can only ever repeat what the next field already
# proves: `canvas=` is read off the surface the panel actually handed us, so it
# cannot lie about the resolution the way a literal could.  Device logs from
# before 2026-08-21 carry `variant=lores|hires` and stay readable as history.
print("CARD_BOOT canvas=%dx%d scale=%d softkeys=%s scroll=%s"
      % (chrome.width, chrome.height, chrome.scale,
         chrome.softkey_x, chrome.scroll_y))
print("CARD_OPEN name=%s background=%s face=%s marks=%d badges=%d active=%d"
      " home=%d effect=%s status=%s failed=%s"
      % (_badge["name"], _badge["background"], _badge["face"],
         len(_badge["stickers"]), len(state["badges"]), state["active"],
         1 if state["home"]["on"] else 0, _badge["effect"], load_status,
         failed or "-"))

_view_name = ""

# The backdrop cache's scheduler, primed from what stage 2 found.  This app owns
# the WRITE because `poster` is read-only by ruling; `card_cache` holds the why.
cache = card_cache.Scheduler(view.poster if view is not None else None,
                             log=print)
if view is not None:
    cache.prime(_badge["background"], view.poster.cached)


def on_exit():
    """Put back everything that outlives this app, and say so.

    `badge.default_clear` is process-global and the launcher's next app would
    inherit a panel that never clears itself.  `main.py` resets after a normal
    return, so this is a backstop -- but the HOME irq route does not, and a
    backstop that costs two assignments is worth having on the one setting that
    could make the NEXT app look broken.

    THERE IS NOTHING TO FLUSH.  Every commit in this app is written
    synchronously at the press that made it (`card_app._commit`), which is the
    one deliberate departure from `ui.Saver`'s debounce: a badge editor commits
    on five discrete actions rather than on a continuously dragged value, so
    there is no burst to coalesce and no window in which HOME can lose a write.
    `namebadge` needed the debounce and paid for it with a real lost-commit bug
    (`test_namebadge_app.py:104`); this app removes the window instead of
    guarding it.
    """
    badge.default_clear = _previous_clear
    # A half-written cache goes with us: it is short, so nothing would read it,
    # but 300 KB of rubbish is 300 KB the wearer's state might need.
    cache.abandon()
    print("CARD_EXIT frames=%d writes=%d cached=%d failed=%s"
          % (app.frames, _writes, cache.writes, failed or "-"))


def update():
    """One frame: input, then state, then pixels.  Never raises."""
    global plain, _view_name
    # THE IDLE CLOCK, FIRST AND ON EVERY PATH INCLUDING THE FALLBACK PAINTER: a
    # badge that lost its renderer still dims, because the dim is the wearer's
    # only signal that nothing is wrong beyond the picture.  A WAKE press is
    # CONSUMED (D1's "the first press wakes ... and does nothing else"), and
    # returning here is the whole consume: `default_clear` is None, so the panel
    # keeps the frame it already has and no key reaches the controller.
    if panel.frame(bool(badge.held())) == idle.WAKE:
        return None
    if plain or view is None:
        # NO EXIT KEY HERE EITHER.  HOME is the labelled route to the launcher
        # for every app in this portfolio (owner ruling 2026-08-16, option (c)
        # in `docs/badge-button-rules.md` section 9.4), and it works from the
        # fallback painter exactly as it works from a healthy frame: the HOME
        # IRQ calls `on_exit` before `machine.reset()`.
        _plain_badge()
        return None
    plan = app.frame(time.ticks_ms(), buttons)
    if plan["view"] != _view_name:
        _view_name = plan["view"]
        print("CARD_VIEW %s" % _view_name)
    try:
        _clear()
        view.draw(plan)
        # AFTER THE DRAW.  The surface now holds the picture this frame is about
        # to present, which is the only moment its bytes and the wearer's badge
        # are known to be the same thing.
        cache.step(plan["badge"]["background"], plan["view"])
    except Exception as error:  # noqa: BLE001
        # LATCHED, NOT RETRIED.  A renderer that raised once will raise every
        # frame, and thirty tracebacks a second is a badge that has locked up in
        # a way nobody can read.  From here on it is a name on a field.
        plain = True
        print("CARD_FAIL stage=frame error=%r" % error)
        sys.print_exception(error)
    if plan["exit"]:
        return "exit"
    return None


_load.end()
run(update)
