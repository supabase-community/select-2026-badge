"""POSTER -- the badge you wear, opened in stages.

WHAT IT IS.  The picture the EDITOR shows when resting, and nothing else: the
wearer's artwork, their marks and their name, drawn by the same
`shared/poster.Poster` object the editor's own `worn()` screen calls.  It reads
`/state/badgecard.json`, passes identity's flat shape through, and writes
neither.  Any button returns to the launcher.

WHY IT EXISTS.  The editor is `badgecard`; a WORN badge needs a slice of it, 14
resident modules against 27.  This app is that slice.  It is not a second
rendering of the badge and must never become one: the renderer is vendored
byte-identically by `scripts/sync_ui.py`, and `playground/e2e/poster.spec.ts`
compares this app's framebuffer against `badgecard`'s, sha256 to sha256, over
ten fixtures.  That oracle was against archived `identity` and SKIPPED until
2026-08-21, while this paragraph cited it.  Never cite a skipped test here.

HOW IT ARRIVES, and this file's whole shape is that answer.  Threads are
compiled out (`MICROPY_PY_THREAD (0)`), so no progress bar is possible -- but
`badgeware.launch()` blocks inside `__import__` of THIS module and a module
body is a SEQUENCE, so every `display.update()` between two statements below is
a frame the wearer sees.  Pimoroni's `gallery` draws in its load loop for the
same reason.  So the arrival is staged cheapest-first:

    stage 0   a dark field, before a single import.  One `clear`, one
              `update`.  It replaces the launcher's leftover frame, which is
              the difference between "it opened" and "it hung".
    stage 1   THE NAME, at its final face, size and position, over that field.
              Costs `poster` + `ui` + the two leaf tables and one file read --
              no artwork module at all.  The badge is already readable at a
              metre here, which is most of what a badge is for.
    stage 2   the artwork, behind the name.  Exactly ONE of `skins`
              (666,336 B) or `glyphskin` (41,235 B) is imported, chosen by
              `identity_catalogue.kind_of`; identity imports both.
    stage 3   the marks, and only if the badge has any.  The mark sheet is an
              `image.load` a badge with no stickers has no reason to pay for.

Every stage after the first is one call into the SAME renderer with one layer
switched off, never a simplified copy of it -- `worn(marks=False)` is stage 2
and `worn()` is stage 3 and the steady state.  That is what makes "the staged
picture and the final picture cannot drift" a property of the code rather than
a claim in a comment.

THE STAGING IS WHAT MAKES HIRES SAFE -- but STAGE 1 IS NOT FREE, and this file
said otherwise until 2026-08-21.  At HIRES the name goes through `plated`, so
its frame pays a cold plate build LORES never pays; the numbers and the memory
gate are in `AGENTS.md` and `docs/engineering-findings.md`.  STAGE 2 IS THE BIG
ONE either way -- 63.752 ms median, 247.900 ms max -- so the worst skin delays
the ARTWORK by a quarter of a second and the NAME by nothing.  Since 2026-08-21
stage 2 READS that artwork from `/state/backdrop.bdr` when the editor has
cached it (`docs/design/backdrop-cache.md`), which is the owner's "the artwork
takes an extra half a second" answered; a miss renders exactly as before.
`playground/e2e/poster.spec.ts` pins the order, the present count and the
name's own PIXELS.

DEGRADE, NEVER FAIL.  This app is reachable from the home screen and an
escaping exception there is not a log line: `badgeware.fatal_error` draws a
modal, BLOCKS until a keypress and then resets the badge (its flip to HIRES is
a no-op here now).  So every stage is wrapped, a failure leaves the last good
stage on screen, and a failure inside the frame loop latches a plain-name
painter.  The app always reaches `run()`: a badge showing only a name is still a
badge and a modal is not.
"""

import sys


# WHERE THIS APP WAS INSTALLED, DERIVED AND NEVER HARDCODED.  Both
# `badgeware.launch()` and the playground's `pg_runtime.launch_app` start an
# app with `__import__(path)` against its install directory, so this module's
# own `__name__` IS that directory.  A literal here is a real defect and not a
# tidiness one: identity's records a build that would have prepended a
# NEIGHBOUR's directory to its own search path and imported that app's modules
# instead of its own.
APP_ROOT = (__name__ if __name__.startswith("/system/apps/")
            else "/system/apps/poster")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

import badgeware  # noqa: F401,E402  - presence check; the API arrives as globals


# The dark field stage 0 paints and the fallback painter falls back to.  The
# SAME three channels `poster.DARK_RGB` gives the renderer, held here as a
# literal because stage 0 runs before any import at all --
# `poster/tests/test_poster_app.py` reads both out of the source and fails if
# they ever differ, so this is a checked duplicate rather than a hopeful one.
DARK = (9, 14, 24)

# What the wearer's state lives in.  `badgecard`'S FILE, read-only: this app is
# a second window onto one badge, not a second badge.
#
# RETARGETED 2026-08-17, on the owner's ruling that the launcher's 1.5-second
# hold keeps opening THIS app rather than the editor.  `badge_state.select`
# picks the worn badge out of the five-slot store and still passes `identity`'s
# older flat shape straight through, so a badge that has not been migrated is
# not a badge that stops working.
STATE_PATH = "/state/badgecard.json"


def _stage(number):
    """Present what has been drawn, and say so on the console.

    The print is the browser lane's ordering oracle and costs nothing a wearer
    can perceive; the `update()` is the ~11.4 ms VSYNC floor and is the entire
    price of arriving in stages.
    """
    display.update()
    print("POSTER_STAGE n=%d modules=%d" % (number, len(sys.modules)))


# -- stage 0: a field, before anything is imported --------------------------
#
# HIRES BY THE OWNER RULING OF 2026-08-21: the identity surfaces -- this app and
# `badgecard` -- are 320x240 1:1, and no LORES build of either exists any more.
# Not a preference: the 24 px 1-bit mark sheet was deleted when the stickers
# went HIRES, so `assets/` carries `stickers-36-p8.png` alone and a LORES
# `chrome.scale == 1` takes `poster.marks`'s no-sheet path -- hollow squares
# where the wearer's marks are.
#
# `badge.mode` rebinds `builtins.screen`, so it runs BEFORE any paint.  The
# launcher is LORES, so the rebind really happens on every open rather than
# returning early: one surface allocation before the first fill, and everything
# downstream then reads 320x240 off the surface it was handed -- `ui.Chrome` off
# `screen.width`, `glyphskin` off the cell geometry, `skins` off the buffer,
# `poster.marks` off `chrome.scale`.  THE ONLY MODE DECISION IN THE APP;
# `poster/tests/test_poster_app.py` fails on a second one.
badge.mode(HIRES | VSYNC)
# THE CASELIGHTS ARE NOT THIS APP'S, and that is exactly why it zeroes them.
# `badge.caselights` is process-global and survives a `launch()`, so a badge
# whose previous app left them lit would arrive here glowing for no reason --
# and one of the previous apps IS the launcher, whose hold indicator drives
# them to full. It extinguishes them as it hands over; this is the backstop
# that makes the wearer's badge look the same however it was opened.
# `identity` opens with the same line for the same reason.
badge.caselights(0)
# THE FRAME CLEAR MOVES INTO THIS APP, and it moves WITHOUT CHANGING COLOUR.
#
# The managed loop calls `badge.clear()` at the top of every frame and
# `Badge.clear` skips the fill when `default_clear` is None.  Taking the fill
# over -- with the pen the loop would have used, captured here -- buys two
# things: the staged paints below survive until the app chooses to overwrite
# them, and a badge with `motion` off can skip the whole frame instead of
# clearing and redrawing an identical picture.
#
# IT IS NOT AN OPTIONAL FILL.  A skin's artwork is not guaranteed opaque in
# every pixel -- `skin.supabase` composites 53 of them at less than full alpha
# -- so a full-screen blit over the PREVIOUS frame is not the same picture as
# the same blit over black.  Dropping the clear "because the blit covers
# everything" moved those 53 pixels by one channel step, which is exactly the
# kind of drift `playground/e2e/poster.spec.ts` exists to catch, and did.
_previous_clear = badge.default_clear
_clear_pen = _previous_clear
badge.default_clear = None
screen.pen = color.rgb(DARK[0], DARK[1], DARK[2])
screen.clear()
_stage(0)

import badge_state  # noqa: E402
import poster as poster_module  # noqa: E402
import ui  # noqa: E402


state = badge_state.read(STATE_PATH)
plan = poster_module.plan_for(state)
frames = 0
failed = ""
plain = False
view = None


def _paint(marks=True):
    """The whole picture, over the same cleared field identity draws onto.

    ONE COMPOSITION FUNCTION for stage 2, stage 3 and every frame after them:
    `marks` is the only thing that varies, and it varies by switching a layer
    off inside the shared renderer rather than by calling something else.
    """
    if _clear_pen is not None:
        screen.pen = _clear_pen
        screen.clear()
    view.worn(plan, marks=marks)


def _plain_badge():
    """The painter of last resort: a dark field and the name in the ROM face.

    Reached only when the renderer itself has raised, so it may not touch it.
    Deliberately the simplest thing that is still a badge -- if the artwork
    cannot be drawn, the wearer's name still can be, and a name on a dark
    field is a name badge.
    """
    screen.pen = color.rgb(DARK[0], DARK[1], DARK[2])
    screen.clear()
    screen.font = font.sins
    screen.pen = color.white
    text = state["name"] or state["line2"] or "BADGE"
    screen.text(text, 6, 50, 2)


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
            # Without a renderer there is nothing later stages could add, so
            # the app runs its plain painter from here on.
            view = None
        failed = "%s:%s" % (number, error)
        print("POSTER_FAIL stage=%d error=%r" % (number, error))
        sys.print_exception(error)
        return False
    _stage(number)
    return True


# -- stage 1: the name, over that field -------------------------------------
#
# The face, the size and the position are FINAL here: `poster.name` runs the
# same `_poster_face` / `fit` / `outlined` ladder the product uses, so the
# artwork simply appears behind the name and nothing reflows.  `ink` starts
# white-on-black-outline, the polarity that is legible over both halves of the
# catalogue by construction; on the twelve pale skins stage 2 flips it, which
# reads as the badge developing rather than as a fault.
def _name_only():
    global view
    view = poster_module.Poster(screen, image, color, font, vec2, rect,
                                ui.Chrome())
    view.name(plan)


_try(1, _name_only)

# The panel is hardware and the wearer's brightness is a percentage.  Applied
# ONCE, here, rather than in the frame loop: it is a device call for a value
# that never moves again while this app is open.
#
# **THE POSTER NEVER DIMS.  OWNER RULING, 2026-08-24, verbatim: *"The poster app
# currently dims after a timeout.  Poster should never dim"*.**  So this app has
# no idle clock at all -- not a clock with its second rung removed, no clock --
# and it does not import `idle`.
#
# WHY THAT IS THE DESIGN AND NOT A RETREAT.  This app IS the resting state: the
# launcher's 20 s dim and 30 s handoff exist to GET a badge here, so a dim that
# fires once it has arrived is the ladder undoing its own destination.  The badge
# is being read by strangers at 1-2 m (D1), and the wearer's chosen brightness is
# their whole answer to how readable that should be.
#
# WHAT WENT WITH IT: the consumed un-dim press.  With no dim to un-dim, `pressed`
# means what it meant before 2026-08-23 -- leave -- and the launcher's own 30 s
# rung brings a bumped badge straight back.  No auto-sleep, still and always:
# `poster/README.md` "The poster never dims, and never sleeps".
import backlight  # noqa: E402
import time  # noqa: E402

def _light(pct):
    """The panel, and NEVER a reset for it.

    Guarded because an escaping exception at stage 1 reaches `fatal_error`: a
    modal, a blocked panel and a reset, for a backlight.  A badge at the wrong
    brightness is still a badge.
    """
    try:
        display.backlight(backlight.fraction(pct))
    except Exception as error:  # noqa: BLE001
        print("POSTER_FAIL stage=backlight error=%r" % error)


_light(state["brightness"])


# -- stage 2: the artwork, behind the name ----------------------------------
#
# ARMED BETWEEN THE STAGES, deliberately: the stamp is a file stat and a codec
# parse, cheap but not free, and it belongs after the NAME is on the panel and
# before the call that could rasterise a skin.  A hit skips the render AND the
# 666,336-byte `skins` import; a miss costs 64 bytes.  This app never WRITES the
# cache -- it is read-only by ruling, the editor fills it.
# Design, invalidation and measurements: `docs/design/backdrop-cache.md`.
if view is not None:
    try:
        view.cache_stamp = poster_module.cache_stamp(APP_ROOT)
    except Exception as _error:  # noqa: BLE001 - a cache is not worth a stage
        print("POSTER_FAIL stage=cache error=%r" % _error)
    # THE WEARER'S FULL-CARD EFFECT, SET ONCE.  It cannot change while this app
    # is open -- there is no editor here -- so it is an assignment beside the
    # cache stamp rather than anything in the frame loop, and `Poster.worn`
    # applies it at the end of every paint.
    #
    # IT DOES NOT TOUCH THE CACHE ARMED ON THE LINE ABOVE, which is the whole
    # reason this ordering is safe: the cache holds the UNFILTERED artwork
    # surface and the filter runs on the panel afterwards, so a badge whose
    # wearer changes their effect still gets a cache hit on their skin.
    view.effect = state["effect"]
    _try(2, lambda: _paint(marks=False))

# -- stage 3: the marks, only if there are any ------------------------------
if view is not None and state["stickers"]:
    _try(3, lambda: _paint())


print("POSTER_OPEN name=%s line2=%s face=%s background=%s marks=%d motion=%d"
      " brightness=%d effect=%s applied=%s source=%s failed=%s"
      % (state["name"], state["line2"], state["face"], state["background"],
         len(state["stickers"]), 1 if state["motion"] else 0,
         state["brightness"], state["effect"],
         view.effect_applied if view is not None else "-",
         badge_state.source, failed or "-"))

# AN ORACLE, NOT A DIAGNOSTIC.  `hits=1 renders=0` is a cached arrival and
# `hits=0 renders=1` is the one this app always had; nothing in the PIXELS can
# tell them apart, which is exactly what the cache promises.
if view is not None:
    print("POSTER_CACHE hits=%d renders=%d stamp=%d"
          % (view.hits, view.renders, view.cache_stamp))


def on_exit():
    """Put back everything that outlives this app.

    `badge.default_clear` is process-global and the launcher's next app would
    inherit a panel that never clears itself.  `main.py` resets after a normal
    return, so this is a backstop -- but the HOME irq route does not, and a
    backstop that costs two assignments is worth having on the one setting that
    could make the NEXT app look broken.
    """
    badge.default_clear = _previous_clear
    print("POSTER_EXIT frames=%d failed=%s" % (frames, failed or "-"))


def update():
    """One frame: the same `worn()` call every staged paint made.

    STILL BADGES DO NOT REDRAW.  With `motion` off nothing in the picture reads
    the clock -- marks are frozen at `now_ms = 0` and no animator runs -- so
    the frame is provably constant and the only thing skipping it omits is a
    redraw of an identical image.  `default_clear` is None, so what is already
    on the panel stays there and an idle worn badge costs one VSYNC wait.
    """
    global frames, plain
    pressed = bool(badge.pressed())
    # NO IDLE POLL, and its absence is the 2026-08-24 ruling rather than an
    # oversight: the poster never dims, so there is no clock to advance and no
    # WAKE press to consume.  See the brightness block above.
    if pressed:
        # THE LABELLED ROUTE OUT.  A non-None result ends the managed loop,
        # which returns control to `launch()` and therefore to the launcher.
        return "exit"
    frames += 1
    if plain or view is None:
        _plain_badge()
        return None
    if not state["motion"] and frames > 1:
        return None
    plan["now"] = time.ticks_ms()
    plan["frame"] = frames
    try:
        _paint()
    except Exception as error:  # noqa: BLE001
        # LATCHED, not retried.  A renderer that raised once will raise every
        # frame, and thirty tracebacks a second is a badge that has locked up
        # in a way nobody can read.  From here on it is a name on a field.
        plain = True
        print("POSTER_FAIL stage=frame error=%r" % error)
        sys.print_exception(error)
    return None


run(update)
