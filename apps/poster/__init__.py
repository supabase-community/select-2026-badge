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
              (667,219 B) or `glyphskin` (42,075 B) is imported, chosen by
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
# 667,219-byte `skins` import; a miss costs 64 bytes.  This app never WRITES the
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


# -- the BadgeLink placement opt-in ----------------------------------------
#
# TWO SOURCES, AND THEY SAY DIFFERENT THINGS -- worth separating here because
# conflating them would let a later reader find a roster in a ruling that does
# not contain one. OWNER RULING #22 establishes the MECHANISM (establishment is
# allowed at the launcher, or in an app that opted in via `set_active`) and names
# no apps. THE ROSTER is the owner's work order,
# `docs/handoff/networking-endstate-2026-08-26/FINAL_PROMPT_badge.md` §7.1:
# settings and home were already covered, poster and schedule are the two to
# add, and everything else is left alone.
#
# THE POSTER IS THE PRODUCT'S RESTING STATE, AND THAT IS WHY THIS IS HERE.
# `launcher/menu/idle.py` returns `poster` after 30 s, so an untouched badge
# spends its whole day in this app -- and `network_runtime.
# _placement_allows_establishment` is `at_launcher or active`, which means an
# app that never calls `set_active(True)` silently withholds every connect
# moment. Measured on hardware 2026-08-26: `wifi_online` at ~13 s, first push
# moment at ~15-19 s, poster at ~32 s -- a **12.7-second doorbell window per
# boot**, and then silence for the remaining 449 seconds of the capture. The
# owner's opt-in list is settings, home, poster and schedule; the games and
# badgecard are deliberately left out, because a game frame is the one place a
# TLS handshake must not land.
#
# AND THE SERVER-SIDE COST OF THIS ROSTER HAS NEVER BEEN PRICED, which is worth
# stating exactly here, beside the reason the roster exists, rather than in a
# capacity doc nobody reads while editing this line.
#
# The roster is a CAPACITY control as well as a reachability one, and only the
# reachability half was ever argued -- including by the review that asked for
# this opt-in and by the lane that implemented it. Follow the two facts above to
# their joint conclusion: the poster is join-allowed and it is where an untouched
# badge spends its day, and every app exit is a `machine.reset()` that lands the
# wearer at the LAUNCHER, which is also join-allowed. So **there is no ordinary
# wearer state in which a badge is not permitted to join.** The only spacing left
# is `pushlink.BOOT_JITTER_MS` -- twenty seconds, and it spaces a herd, not a
# rate.
#
# THAT IS THE SAME DECISION SEEN FROM TWO SIDES, NOT TWO DECISIONS IN TENSION.
# The 12.7-second window above is the wearer's complaint and this opt-in is its
# fix; the fix also removed the last placement-shaped limit on how often the
# fleet asks the server for a join. Nothing is reused across a switch either --
# no session, no TLS, no socket survives a reset -- so every join is a COLD join
# by construction and the fleet cannot amortise anything. If the join term turns
# out to be expensive server-side (see NETWORKING_LANE_STATE.md §6, an open
# measurement), the honest options are: keep the roster and pay it, widen
# BOOT_JITTER_MS and pay doorbell latency after every switch, or make the
# doorbell's recurrence cheaper than a fresh join -- which needs a soft reset
# this platform may not offer, and is a question only Pimoroni can answer.
#
# DO NOT ADD AN APP TO THIS ROSTER WITHOUT THAT NUMBER. Each addition multiplies
# fleet join rate by that app's share of wearer time, and this comment is the
# only place that says so.
#
# A FIRMWARE-INJECTED BUILTIN, READ AS A BARE NAME, for the reason `settings`
# spells out: MicroPython's `builtins` attribute lookup bypasses its own
# override dictionary, so `builtins.badgelink_network = ...` is only visible to
# ordinary name lookup.
try:
    _network = badgelink_network
except NameError:
    _network = None


def _network_active(active):
    """Tell BadgeLink this app is a tolerant place to establish, or stop.

    EVERY CALL IS GUARDED, and the guard is not defensive style -- it is the
    reset rule. An `AttributeError` raised on the launch path resets the badge
    (docs/deploy.md), and a badge whose `/system/lib` predates `set_active`
    would raise exactly that. So a missing seam makes the poster a poster, which
    is what it was before this block existed.
    """

    if _network is None:
        return
    setter = getattr(_network, "set_active", None)
    if not callable(setter):
        return
    try:
        setter(bool(active))
    except Exception as error:  # noqa: BLE001
        print("POSTER_NETWORK stage=set_active error=%r" % error)


def on_exit():
    """Put back everything that outlives this app.

    `badge.default_clear` is process-global and the launcher's next app would
    inherit a panel that never clears itself.  `main.py` resets after a normal
    return, so this is a backstop -- but the HOME irq route does not, and a
    backstop that costs two assignments is worth having on the one setting that
    could make the NEXT app look broken.

    THE NETWORK OPT-IN IS RELEASED HERE TOO, and it has to be released on the
    HOME route as well: `set_active` is a lasting property of where the badge is,
    so an app that opted in and never opted out would leave a WSS establishment
    admissible from inside the next app's frames.
    """
    badge.default_clear = _previous_clear
    _network_active(False)
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
    # IDEMPOTENT AND BEFORE THE PAINT. `NetworkService.set_active` raises
    # MOMENT_VIEW_TRANSITION on the False->True edge only, so calling it every
    # frame costs one attribute lookup and one bool compare after the first --
    # and doing it per frame rather than once at open is what survives a
    # `set_active(False)` from anywhere else while the poster is still up.
    _network_active(True)
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
