"""Supabase-themed presentation layer for the pinned Badgeware launcher.

The stock launcher's ``app.py`` imports this module and relies on ``phosphor``,
``draw_background`` and ``draw_header``. Keeping that small interface means app
discovery, navigation and launching remain stock while the visual layer is ours.

``commit`` is the second thing this module owns, and it is the whole of the
badge app's long press: `launcher/host/build_menu.py` routes the stock
launcher's B-commit through it in three lines, and every line of POLICY -- the
hold clock, the dead zone, the stale-key rule, the missing-app guard, both
feedback channels -- is here, in code this repository owns outright.

`load_step`/`load_tick`/`load_end` are the third thing, and they are the whole
of the LOADING SCREEN ON THE WAY HOME -- see the bootstrap immediately below.
**And since 2026-08-24 this file also owns the one boot that does NOT get that
screen: a first-wake boot whose opening sequence painted goes straight to home.
§THE SUPPRESSION below carries the owner's design, and the three constraints
that leave `loading.begin()`'s CALL as the only place it can be implemented --
`shared/loading.py` is byte-frozen and paints inside its own constructor.**

The SHUFFLE is the fourth, added 2026-08-23: one native whole-surface filter,
picked at random on each arrival and animated over the frozen wallpaper for the
whole visit. `SHUFFLE_ENABLED` turns it off in one word. Its section carries the
frame budget that chose its five rows, and `launcher/README.md` carries the
arithmetic behind that budget. **Both were re-cut on 2026-08-24 against device
numbers and an owner ruling that three quanta -- a constant 29.2 FPS -- is the
accepted home-screen envelope, and the POOL was cut again the same day on the
owner's eye: `contrast` out, `crt` and `grid` animated harder.**

THE LAUNCHER IS THE ONE APP WHOSE FAILURE NEEDS USB TO RECOVER. `commit` now
runs inside its frame, so it is wrapped head to toe and returns None on any
exception: the worst a bug in it can do is take the shortcut away, never the
launcher.

THE ONE PLACE THIS FILE DEVIATES FROM EVERY APP IN THE REPOSITORY: its
`import loading` IS GUARDED. Every app's is bare, and `shared/loading.py` says
why -- `scripts/sync_ui.py --check` runs in the production lane and guarantees
the file is beside the app, so a try/except there would trade a failure the
hand-run lane catches for one it does not. That guarantee is about the
REPOSITORY, not about a hand-run `rsync` into `/Volumes/TUFTY/apps/menu/`. In
an app, a missing module is a modal and a reset back into a launcher that still
works; in
the launcher it is `launch()` -> `fatal_error` -> modal -> `machine.reset()` ->
boot -> the same failing import, which is the USB-recovery loop. The three
forwarders are defined UNCONDITIONALLY for the same reason: the patched pinned
base calls them by name, and an `AttributeError` there is that same loop.
"""

import time

# ---------------------------------------------------------------------------
# The first-wake ripple, and it is the ONLY thing ahead of the loading screen
# ---------------------------------------------------------------------------

# ON A RESET, NOT ON A TRIP HOME. `first_wake.play()` reads the wake register
# and returns immediately on every wake that is not a deliberate RESET tap (241)
# or a cold attach (255) -- which is every HOME exit, because leaving an app is
# `machine.reset()` and the RP2350 serves that through the watchdog (242). So
# the common boot pays one register read and one `print`, and the ceremony
# happens exactly when the owner asked for it: "If you hit HOME you go home --
# NO animation between apps or on home."
#
# AHEAD OF THE LOADING SCREEN DELIBERATELY. That screen is the animation
# that covers the trip home; this is the one that covers a reset. Two ceremonies
# on one boot would be a ripple the wearer waits through before waiting through
# an editor -- which is why, since 2026-08-24, a boot that plays the sequence
# does not get the editor AT ALL. See §THE SUPPRESSION below.
#
# GUARDED LIKE `import loading` BELOW, AND FOR THE SAME REASON. A raise here is
# `launch()` -> `fatal_error` -> modal -> `machine.reset()` -> boot -> the same
# failing import, which is the USB-recovery loop. `first_wake.play()` is total
# on its own account; this is the second belt, and the cost of being wrong is a
# launcher with no ripple rather than a badge that needs a cable.
#
# THE RETURN VALUE IS READ NOW, and `(0, "off")` is the value that means "this
# never ran at all" -- distinct from `first_wake`'s own `(0, "resume")` for a
# declined boot and `(0, "heap")` for a skipped one. All three suppress nothing,
# which is the property that matters; the token only has to tell an operator
# which happened.
_ripple = (0, "off")
try:
    import first_wake

    _ripple = first_wake.play()
except Exception:                                            # noqa: BLE001
    pass

# ---------------------------------------------------------------------------
# The loading screen, and it starts before anything else in this file
# ---------------------------------------------------------------------------

# WHY THE HOME SCREEN NEEDS ONE AT ALL. Leaving an app is not a return into a
# resident launcher: `badgeware.reset()` is `while BUTTON_HOME is down: pass`
# then `machine.reset()`, and the HOME irq (`quit_to_launcher` -> `do_exit()`
# -> `reset()`) takes the same road sooner. So every trip home is MCU reset ->
# MicroPython init -> `import badgeware` (which CONSTRUCTS the ST7789, which is
# why the panel goes black rather than holding the app's last picture) ->
# frozen `main.py` -> `/system/main` -> `launch("/system/apps/menu")` -> this
# module. The wearer sees black for all of it and the owner asked for that to
# stop.
#
# WHAT WE CAN AND CANNOT FILL. Everything up to the first statement of the
# menu's `__init__.py` is the firmware's; no Python of ours runs there, threads
# are compiled out, and no hook exists. What is ours is the menu's module body,
# and `launcher/host/build_menu.py` interleaves four `ui.load_step` calls
# through it. `Apps("/system/apps")` dominates that body -- it stats every
# entry under /system/apps and decodes an icon PNG per app -- so `app.py` gets
# one `ui.load_tick(name)` per installed app and the bar moves through the
# scan rather than sitting still under it.
#
# FRAME 0 IS PAINTED HERE, at the top of the first project-owned module the
# launcher imports, ahead of `import wallpaper` (22.5 KB of source to compile)
# and ahead of every pen below.
#
# `app="menu"` IS REQUIRED, NOT DECORATION. `loading._app_name()` derives the
# name from `sys.path[0]`, which is what `launch()` inserted -- but the menu's
# own `__init__.py` inserts "/" AFTER its directory, so `sys.path[0]` is "/"
# and the derived name is the empty string. Every log line would read `app=`.
#
# ---------------------------------------------------------------------------
# §THE SUPPRESSION -- the loading screen is skipped on a first-wake boot ONLY
# ---------------------------------------------------------------------------
#
# OWNER DESIGN, 2026-08-24, both halves in one breath: on the first-wake path the
# opening sequence must run straight into home with no editor in between, AND
# *"that generic loading screen that appears between every screen -- I love it,
# we got to keep that there."* So this is a one-path carve-out, not a retreat
# from the loading screen.
#
# WHY IT IS ONE `if` AROUND `begin()` AND NOTHING ELSE. Three constraints meet
# here and only this shape satisfies all of them:
#
#   1. `shared/loading.py` MUST NOT BE EDITED. It is one of the seven files
#      byte-frozen by SHA-256 in `kb/tests/test_kb_sameness.py::ControlTests`
#      (`loading.py` and `loading_sql.py` are both on that list), and
#      `scripts/sync_ui.py --check` copies it into eleven apps. A `suppress=`
#      flag there would turn every app's copy red.
#   2. NOTHING INSIDE `begin()` CAN BE SUPPRESSED FROM OUTSIDE IT. `_Loader`
#      paints its window and calls `display.update()` inside `__init__`, so by
#      the time `begin()` returns a handle, frame 0 is already latched on the
#      panel. There is no drawing left to switch off after the call, which is
#      why this is a decision about whether to MAKE the call.
#   3. THE PANEL MUST KEEP THE SEQUENCE'S LAST FRAME. `first_wake._clear()`
#      blacks the framebuffer WITHOUT presenting, on purpose, so the panel goes
#      on holding terminal-marquee's final frame until the home screen's own
#      first paint replaces it. That is the "ends on home directly" the owner
#      asked for, and it happens by SUBTRACTION -- one fewer present -- rather
#      than by any new timing. The rejected alternative was to time the sequence
#      to end as the launcher's build completes, which would need a clock the
#      launcher does not have and would still show an editor if it guessed low.
#
# WHAT IS NOT SUPPRESSED, AND THIS IS THE POINT OF THE FRAME COUNT. The gate is
# `frames > 0`, i.e. THE SEQUENCE ACTUALLY PAINTED -- not merely
# `wants_ripple(reason)`. A 241 boot on a badge with no glyph app, or one whose
# heap gate fired, returns 0 frames and gets the ordinary loading screen: the
# soft dependency stays soft, and the wearer never trades a ceremony for a black
# panel. That is a deliberate refinement of "register-scoped": the register
# decides whether to TRY, the frame count decides what the boot is left with.
#
# WHAT THE PLUMBING DOES ON A SUPPRESSED BOOT: everything it always did. The
# patched pinned base still calls `ui.load_step`, `ui.load_tick` and
# `ui.load_end` by name; all three are already total against `_load is None`
# (that is the "badge whose `loading.py` is missing" path `launcher/README.md`
# warns about, and it has been tested since the screen shipped). `load_end()`
# still runs `idle_begin()` and `_shuffle_begin()`, which sit OUTSIDE its `_load`
# guard -- so the idle clock and the wallpaper shuffle start on a suppressed boot
# exactly as they do on every other one. Nothing about the launcher's own load
# changes; one screen is not drawn over it.
_load = None
if _ripple[0] < 1:
    try:
        import loading

        _load = loading.begin(4, app="menu")
    except Exception:                                        # noqa: BLE001
        # Deliberately silent and deliberately total. There is no recovery from
        # a raising home screen except a cable, and a launcher with no loading
        # screen is exactly the launcher the owner has been using all along.
        _load = None

# THE ONE NUMBER NOBODY HAS EVER MEASURED for this feature: milliseconds from
# interpreter start to the first pixel of the home screen, which is the black
# prefix minus only the pre-interpreter MCU boot. It is free here --
# `time.ticks_ms()` on the badge is measured from interpreter start -- and it
# is read over serial on the next trip home.
#
# ⚠ SINCE 2026-08-23 IT IS ONLY COMPARABLE WITHIN ONE WAKE REASON. On a boot
# that earned the ripple this number includes the whole pass, so a 241 boot and
# a 242 boot are measuring different things. The line above it says which:
# `FIRSTWAKE … ripple=0` means this reading is the black prefix alone.
#
# `ripple=` AND `suppressed=` ARE THE HONEST ACCOUNT OF §THE SUPPRESSION, and
# they are here rather than in `shared/loading.py` because that file is frozen
# and because a suppressed screen must not be reported as a FAILED one. Without
# them a suppressed boot and a badge whose painter is missing both read
# `screen=none`, and an operator would have no way to tell the feature from the
# fault. `ripple=` is the frame count the decision was made on, so the line
# carries its own reason.
#
# ITS OWN `try`, and that is not tidiness. A `print` or a missing `ticks_ms`
# inside the block above would have been caught by that block's `except`, which
# clears `_load` -- so a failure to REPORT the loading screen would have thrown
# the working loading screen away, and left it un-ended.
try:
    print("LAUNCHER_LOADING first_frame_ms=%d screen=%s ripple=%d suppressed=%d"
          % (time.ticks_ms(),
             "none" if _load is None else _load.screen_kind,
             _ripple[0], 1 if _ripple[0] >= 1 else 0))
except Exception:                                            # noqa: BLE001
    pass

# Every tick is a present, and a present is a full panel transfer (the measured
# VSYNC floor is ~11.4 ms). Ten installed apps is ten of them. This is the one
# number to turn down if the motion costs more than the black it replaced: 2
# presents on every other tick, 0 disables ticking entirely (the four `step`
# calls, which carry the actual percentage, are not affected either way).
#
# It counts EVERY `load_tick`, not only the pinned scan's, so the free one over
# the film codec's compile below shares the ladder rather than sitting outside
# it. That is deliberate: the wearer sees presents, not their reasons.
ICON_TICK_STRIDE = 1
_icon_ticks = 0

# THE ONE WORD THAT TURNS THE HOME-SCREEN SHUFFLE OFF. `False` here and the
# launcher is exactly the launcher it was before 2026-08-23: a still wallpaper,
# no filter, no roll, no log line, and `_shuffle_frame` returns on its first
# statement. Kept beside `ICON_TICK_STRIDE` because this file is where the
# launcher's tuning lives, so an owner who rejects the motion does not have to
# find the section that implements it.
SHUFFLE_ENABLED = True

# AND THE SECOND CONSTANT, which is a SCOPE rather than a switch: the shuffle
# runs over a BAKED WALLPAPER only, never over the procedural Supabase theme.
#
# THE OWNER'S WORDS ARE THE FIRST REASON -- *"on the home screen with your
# static background"*. A badge with no baked card has no "your static
# background"; it has the fallback theme, and animating a fallback is decorating
# an error state.
#
# ⚠ THE BUDGET WAS THE SECOND REASON AND THE DEVICE TOOK IT AWAY. This comment
# said the film path's one full-surface blit buys headroom the procedural theme
# (measured 3.23-3.25x a blit in the pinned rasteriser) cannot, so the theme path
# had "no slack to derive". On device, 2026-08-24, the theme body is **12.858 ms
# against the film's 14.063** -- the theme is the CHEAPER path, the host ratio
# did not transfer, and it changed sign rather than shrinking. So the scope now
# rests on the owner's words alone, which is enough: animating a fallback is
# decorating an error state. Setting this True->False would put the filter on a
# path that has never been measured with one, and both paths' real numbers are in
# `benchmark/results/reports/2026-08-24-wave-validation.md` §3.
SHUFFLE_NEEDS_FILM = True


def load_step(note=""):
    """One completed stage of the launcher's own load. NEVER RAISES.

    Called by name from the patched pinned `__init__.py`, so it must exist and
    must be harmless even when `loading` could not be imported at all.
    """
    try:
        if _load is not None:
            _load.step(note)
    except Exception:                                        # noqa: BLE001
        pass


def load_tick(note=""):
    """Motion from inside a piece of work. NEVER RAISES.

    Called by name from the patched pinned `app.py`, once per installed app,
    and once from this module over the film codec's compile.
    `ICON_TICK_STRIDE` decides how many of those actually present.
    """
    global _icon_ticks
    try:
        if _load is None or ICON_TICK_STRIDE < 1:
            return
        _icon_ticks += 1
        if _icon_ticks % ICON_TICK_STRIDE:
            return
        _load.tick(note)
    except Exception:                                        # noqa: BLE001
        pass


def load_end():
    """Tear the loading screen down. NEVER RAISES; safe to call twice.

    The reference is dropped so the radar's tile bank and its 10,752-byte
    payload are collectable before the frame loop starts asking for a film.
    """
    global _load
    try:
        if _load is not None:
            _load.end()
    except Exception:                                        # noqa: BLE001
        pass
    finally:
        _load = None
    # THE IDLE CLOCK STARTS WITH THE FRAME LOOP, not with the module body. The
    # loading screen above can take a second on a badge with a full grid, and
    # counting that second as idleness would mean a slow boot arriving already
    # part-way to a dim. Defined below; this is the one seam that runs once.
    idle_begin()
    # AND SO DOES THE SHUFFLE'S ROLL, for the plainer reason that this is the
    # only place in the launcher that runs exactly once per arrival and runs
    # AFTER the loading screen has released the panel. Rolling in the module
    # body would put the pick behind the app scan, where a filter bound to a
    # `screen` the loading screen is still presenting through has nothing to
    # gain and one more thing to go wrong. Both calls are total; neither can
    # take the launcher down.
    _shuffle_begin()


import os                                                    # noqa: E402

import wallpaper                                             # noqa: E402
# THE TWO IDLE MODULES RIDE UNDER THE SAME PRESENT as the film codec, and they
# are the cheapest imports in this file: `backlight` is numbers and imports
# nothing at all, `idle` is one class and imports only `time`. Both are
# `scripts/sync_ui.py` copies of `shared/`; edit them there.
#
# UNGUARDED, unlike `loading` above, and the difference is deliberate. The
# loading screen is decoration and its import is wrapped because a badge that
# cannot draw a progress bar must still boot. These two are pure Python with no
# assets, no Badgeware calls and no file access at import time -- there is
# nothing for them to fail ON -- and a guard would mean a launcher that silently
# never idles, which is the failure this feature exists to remove.
import backlight                                             # noqa: E402
import idle                                                  # noqa: E402
# A free present over the film codec's own compile, and the first evidence on
# the panel that frame 0 was not the end of it.
load_tick("-- wallpaper")

# Loaded once and then remembered, including the negative: a badge with no film
# must not re-stat it sixty times a second.
_film = None
# WHICH FRAME OF THE FILM THE HOME SCREEN SHOWS -- resolved once beside the
# film, because it is a property of the film and not of the clock.  See
# `_still_index`.
_still = 0


black = color.rgb(1, 4, 4)
background = color.rgb(5, 18, 16)
phosphor = color.rgb(62, 207, 142)

header = color.rgb(3, 11, 10, 245)
grid = color.rgb(62, 207, 142, 20)
bolt_shadow = color.rgb(26, 112, 81, 70)
bolt_glow = color.rgb(62, 207, 142, 105)
bolt_hot = color.rgb(126, 249, 191, 175)
battery_empty = color.rgb(7, 29, 24)

BANDS = (
    color.rgb(5, 18, 16),
    color.rgb(5, 21, 18),
    color.rgb(5, 24, 20),
    color.rgb(5, 27, 22),
    color.rgb(5, 24, 20),
    color.rgb(5, 21, 18),
    color.rgb(5, 18, 16),
)


# ---------------------------------------------------------------------------
# The badge app's long press
# ---------------------------------------------------------------------------

# Where the wearer's badge lives. Checked once, because a launcher that offered
# a shortcut to an app that is not installed would hand `launch()` a path it
# cannot import -- and that raises into `fatal_error`, which blocks the HOME
# SCREEN behind a modal and resets the badge. The guard is the affordance too:
# no app, no bar, so nothing is ever offered that cannot happen.
POSTER_APP = "/system/apps/nametag"

# The owner's 2026-08-16 feel adjustment, as one named constant.
HOLD_MS = 1500
# Nothing is drawn and nothing is armed for this long. Without it every
# ordinary navigation press flashes a bar and the launcher acquires a permanent
# twitch; with it no normal press ever shows anything, and the first time
# anybody leans on a key for a beat the bar teaches the gesture by itself.
HOLD_LEAD_MS = 250
# A poll gap larger than this cannot prove the button remained continuously
# down: the wearer may have released and pressed again while Python was not
# polling.  Reset the gesture instead of turning a stalled launcher frame into
# an instant long press.  The measured launcher is normally 23--30 ms/frame.
HOLD_POLL_MAX_MS = 250

# EVERY key, which is what the owner asked for and what costs B its press-edge
# launch. Order is fixed because the state below indexes into it.
HOLD_KEYS = (BUTTON_A, BUTTON_B, BUTTON_C, BUTTON_UP, BUTTON_DOWN)
_B = 1

# The bottom band, and the only strip of the panel nothing else occupies: icons
# are centred at y 42 and 90 and reach y 110, the label plate is y 100..115 and
# pagination is a 5 px column at x 150. Everything `ui` draws is drawn FIRST --
# `__init__.py` calls `draw_background`, then `draw_header`, then the icons --
# so a ring around the grid would be painted over. Three logical pixels is
# 1.125 mm on the ruler-measured panel: thin, but it is a MOVING EDGE, which is
# what the eye catches.
BAR_Y = 116
BAR_H = 3

# Set once per frame by `commit`, painted at the tail of `draw_background`.
_progress = 0.0
# Which of `HOLD_KEYS` is being held, or -1.
_holding = -1
# Milliseconds proven by consecutive Badgeware input polls with the same key
# down.  Use the input layer's own latched delta rather than subtracting two
# absolute counters: the 2026-08-16 hardware trace reproduced a 29 ms tap being
# classified as a completed hold through that absolute-counter path.
_held_ms = 0
# Keys whose down level was inherited rather than pressed on this bright frame.
# Their UP edge stays stale so a wake tap cannot launch app 0. The one exception
# is an uninterrupted wake HOLD: the 2026-08-25 ruling starts its existing clock
# at the wake frame, while `_stale` continues to suppress that eventual release.
_stale = None
# Is the badge app installed? None until asked, then True or False forever.
_ready = None
# Last caselight level written, so an idle launcher makes no PWM calls at all.
_lit = 0.0


def _installed(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Idle: the dim at 20 s, and the trip home to the badge at 30 s
# ---------------------------------------------------------------------------
#
# THE OWNER'S DESIGN, 2026-08-23, RETUNED 2026-08-24 (`docs/design/idle-and-off.md`
# §1). Owner verbatim: *"should dim after 20 seconds of being inactive on the
# home screen and then switch to the nametag after another 10 seconds"*. So
# twenty seconds without input dims the panel, thirty opens the nametag, and
# there is NO third rung -- the automatic path always returns to the badge and
# never to a dark panel. The numbers were 30 s and 45 s for one day.
#
# THE SCOPE IS THIS SCREEN, which the ruling states itself ("on the home
# screen"), and it is why the launcher takes `idle.Panel`'s DEFAULTS while
# `setup` passes `dim_ms=idle.CARD_DIM_MS` to keep the 30 s it shipped with.
# That asymmetry is unruled; §5.1 of the design record carries it.
#
# WHY IT LIVES HERE AND NOT IN A GLOBAL SEAM, which is the design record's §4.3
# and the one question a builder had to answer with evidence rather than taste.
# The only truly global per-frame seam on this badge is the firmware's own
# managed loop -- `badgeware.__init__._run.__call__`, which is `badge.clear()`,
# `update()`, `display.update()`, `badge.poll()` -- and that file is the PINNED
# base: it is not committed here, it is not redistributable, and §9.3 of the
# button rules has the supervisor's boot-ownership question still open. It
# cannot be patched, so `run(update)` hands each app exactly ONE callback and
# there is no per-frame code any app shares. There is therefore no global choke
# point to put this in, and inventing one would mean a call in every app's
# frame loop -- N chances to forget, in a tree with 81 vendored module copies.
#
# So the clock is ONE implementation (`shared/idle.py`, vendored by
# `scripts/sync_ui.py` so the copies cannot drift) wired HERE and in
# `setup`. It is deliberately NOT in `nametag`, which had it for one day:
# the owner ruled on 2026-08-24 that the nametag never dims, because it is the
# resting state this ladder exists to REACH. D1's justification is that the badge
# "spends ~99 % of its life being read by strangers at 1-2 m" -- so the honest
# statement of reach is that this screen is where a badge nobody is using SITS,
# and the destination it hands off to holds the wearer's own brightness forever.
# What is not covered is a wearer parked inside a game or `settings`; see the
# design record for what each of those would cost.
#
# AND THE SECOND RUNG COULD NOT LIVE ANYWHERE ELSE EVEN IF IT WANTED TO.
# Only the launcher can open an app: `supervisor/system/stock-v3.0.1-main.py`
# takes ONE path out of `launch("/system/apps/menu")` and `reset()`s when that
# app returns, so an app's own idle timer could reach the nametag only by exiting
# to the launcher and waiting out a second 30 s. The launcher is where this rung
# belongs, and the existing 1500 ms hold already proves the handoff works.

# WHERE THE WEARER'S BRIGHTNESS LIVES. `setup`'s store, read-only, and the
# root of it rather than a badge inside it: brightness is a property of the
# PANEL, so switching between five saved badges must not change how bright the
# screen is.
#
# THIS IS NOT A DEPENDENCY ON THE BADGE APP and the distinction is the one
# `scripts/sync_ui.py` draws for `shared/backdrop.py` ("the LAUNCHER is
# deliberately NOT here ... its dependency on the badge app must stay exactly
# zero"). That rule is about IMPORTS -- a module vendored out of a neighbour's
# directory makes one app refuse to start unless another is installed. This is a
# FILE, read totally, defaulting on every failure, and the launcher already
# consumes another of the badge app's outputs exactly this way: `/state/
# wallpaper.pgw`, baked by `card_bake` and played by `wallpaper.load`.
BRIGHTNESS_PATH = "/state/badgecard.json"

# The `idle.Panel` -- clock plus brightness -- built by `load_end()` so the
# first frame of the grid starts it.  None until then, and None forever on a
# badge where that failed, which is the inert state: the launcher keeps every
# gesture it had and simply never idles.
_idle = None
# `_idle_step`'s answer when a press did nothing but restore the brightness.
_WOKE = "woke"


def _read_brightness():
    """The wearer's brightness percent. TOTAL: never raises, always legible.

    A missing file, a directory, unparseable bytes, a JSON array, a `brightness`
    of `"80"` or of `True` -- every one of them is `backlight.DEFAULT`, because
    the alternative on the home screen is `fatal_error` and a USB recovery.
    `backlight.clamp` owns the last two cases and this function owns the rest.

    `json` is imported HERE rather than at module scope so a badge whose store
    does not exist never compiles it. It is one read at start-up; nothing in the
    frame loop touches the filesystem.
    """
    try:
        import json
        with open(BRIGHTNESS_PATH) as handle:
            value = json.loads(handle.read())
        if isinstance(value, dict):
            return backlight.clamp(value.get("brightness", backlight.DEFAULT))
    except Exception:                                        # noqa: BLE001
        pass
    return backlight.DEFAULT


def _apply_backlight(percent):
    """The one panel write, injected into `idle.Panel` rather than imported.

    THE LAUNCHER NEVER SET THE BACKLIGHT AT ALL until this feature, and neither
    do the keyboard apps: both inherited whatever the previous app left on the
    panel. That was invisible while every app opened at its own fixed level, and
    it becomes a CORRECTNESS problem the moment an idle dim can leave the panel
    at 20 % -- the next app the wearer opens would inherit the dim. Somebody has
    to own the restore, and on the screen that does the dimming it can only be
    this file.

    "Only when it moves" is `idle.Panel`'s job, not this function's -- the same
    discipline `_caselights` implements by hand one section above, in the one
    place a shared module could not reach.
    """
    display.backlight(backlight.fraction(percent))


def idle_begin():
    """Start the idle clock and put the wearer's brightness on the panel.

    Called once from `load_end()`, which the END substitution already places
    immediately above `run(update)` -- so this needs no fifth patch of the
    pinned base, and `launcher/README.md`'s four-substitution table is unchanged.

    NEVER RAISES, for `load_end`'s own reason: it is called from the patched
    pinned base and an `AttributeError` or an escaping exception there is the
    USB-recovery loop.

    THE CLOCK STARTS EVEN IF THE PANEL WRITE FAILS, which is why the two are
    separately guarded: the 45-second trip home needs no backlight call at all,
    so a badge whose `display.backlight` raises should lose the dim and keep the
    half of the feature that still works.
    """
    global _idle
    try:
        _idle = idle.Panel(_apply_backlight, time.ticks_ms,
                           _read_brightness(),      # total by construction
                           backlight.IDLE_PERCENT)
    except Exception:                                        # noqa: BLE001
        _idle = None
        return
    try:
        _idle.restore()
    except Exception:                                        # noqa: BLE001
        pass


def _idle_step(down):
    """One frame of the idle ladder. `POSTER_APP`, `_WOKE`, or None.

    Called from `_commit` on the SAME poll that sampled the buttons, so the
    interval it measures is the interval those button levels are evidence for.

    ANY KEY DOWN IS INPUT, which is a deliberately blunt definition and the
    right one here: the launcher's own gestures are a press edge (navigation), a
    release (B's commit) and a held level (the 1.5 s hold), so a wearer part-way
    through any of the three is a wearer using the badge. A definition built on
    edges alone would dim the panel under a thumb that had been resting on a key
    for twenty seconds.
    """
    if _idle is None:
        return None
    touched = False
    for level in down:
        if level:
            touched = True
            break
    # The panel is already written by the time this returns; what comes back is
    # only what the LAUNCHER has to do about it.
    signal = _idle.frame(touched)
    if signal == idle.WAKE:
        return _WOKE
    if signal == idle.NAMETAG:
        # THE SAME GUARD AS THE HOLD'S, for the same reason: handing `launch()`
        # a path it cannot import raises into `fatal_error`, which blocks the
        # home screen behind a modal and resets the badge. No badge app, no
        # automatic trip -- the launcher simply stays dim, which is safe because
        # there is no rung after this one.
        return POSTER_APP if _ready else None
    return None


# The grid order data. Generated from `apps-roster.json` and shipped beside the
# launcher by every builder that stages it — one app-directory name per line, in
# grid order. A launcher without the file is a valid stock install and boots
# alphabetical.
ORDER_FILE = "/system/apps/menu/order.txt"


def launcher_order(names):
    """The grid: the roster's order, minus whatever the backend gated off.

    Called from the pinned base's own scan loop (the ORDER patch — the loop
    header is the one line that cannot live here), so it must NEVER raise: a
    launcher that dies ordering its grid is a badge with no way into any app.
    Names the roster does not know sort alphabetically AFTER the listed ones,
    so an unlisted app is late in the grid, never missing from it.

    TWO INDEPENDENT STEPS, EACH WITH ITS OWN TOTAL FALLBACK, and that split is
    the whole safety argument for putting a network-supplied value on the home
    screen's boot path: ordering that fails still gates, and gating that fails
    still orders. The worst either half can do is give back the full roster.
    """
    names = list(names)
    try:
        ordered = _roster_order(names)
    except Exception:                                        # noqa: BLE001
        ordered = sorted(names)
    try:
        allowed = _gate_allowed()
        if not allowed:
            # THE UNGATED BADGE PAYS NOTHING. Returning here rather than letting
            # `_apply_gate` answer rule 1 keeps `_gate_tile` off the boot path of
            # every badge that has never been told to gate anything, which is all
            # of them until a console says otherwise.
            return ordered
        return _apply_gate(ordered, allowed, _gate_tile)
    except Exception:                                        # noqa: BLE001
        return ordered


def _roster_order(names):
    """`order.txt`'s ranking, alphabetical for anything it does not list."""
    try:
        with open(ORDER_FILE) as handle:
            roster = [line.strip() for line in handle if line.strip()]
    except OSError:
        return sorted(names)
    try:
        listed = [n for n in roster if n in names]
        return listed + sorted(n for n in names if n not in listed)
    except Exception:                                        # noqa: BLE001
        return sorted(names)


# ---------------------------------------------------------------------------
# §THE ENABLED-APPS GATE — `public.badges.enabled_apps`, on the grid
# ---------------------------------------------------------------------------
#
# WHAT IT IS. The console can turn apps off per badge. BadgeLink fetches the
# column in its profile read and writes an allow-list note to `/state`
# (`badgelink/badge/badgelink/enabled_apps.py`, which owns the format); this
# reads the note and drops the gated names before the pinned scan ever builds a
# tile for them.
#
# WHY A FILE AND NOT AN IMPORT. `/system/lib` and this launcher are installed by
# two different steps, so a badge can hold one without the other, and a
# module-scope import of a file a half-refreshed lib does not carry raises inside
# `launch()` — `fatal_error` → modal → `machine.reset()` → boot → the same
# failing import, which is the USB-recovery loop on THE ONE APP WHOSE FAILURE
# NEEDS USB TO RECOVER. So the two sides share a FILE and this module carries its
# own reader. `launcher/tests/test_app_gating.py` runs both copies over one table
# of payloads and fails on any drift. This is the same trade `_read_brightness`
# already makes for `/state/badgecard.json` further up this file.
#
# THE OWNER'S RULE HAS ONE DIRECTION: missing, empty, corrupt or unparseable
# means ALL-ENABLED, never an empty launcher. A badge that cannot read the
# setting is a fully working badge. So every branch that cannot produce a
# trustworthy list answers None, and None means no gate — which makes the
# cheapest path (one failed `open` on a badge that has never seen a network) the
# safe one too.
#
# GATED APPS DISAPPEAR; THEY ARE NOT DRAWN INERT. Three reasons, in the order
# they decided it:
#   1. AN INERT TILE CANNOT BE BUILT HERE. Tile identity, position, colour, the
#      six-per-page arithmetic and the B-commit launch are all in the PINNED
#      base (`App.__init__` takes `self.index = len(collection)`;
#      `draw_pagination` pages on `len(self.apps)`), which this repository owns
#      no line of and republishes none of. "Inert" means teaching that base a
#      disabled state — a fifth substitution, against a four-substitution
#      boundary that exists for licensing and is asserted by a test.
#   2. A DEAD TILE IS INDISTINGUISHABLE FROM A BROKEN BADGE. The grid has an
#      icon and a name and no copy channel, so a tile that swallows B cannot say
#      why. The owner's tie-breaker was "the one that cannot confuse a wearer",
#      and a badge that ignores its launch key is the more confusing of the two.
#   3. ABSENCE IS ALREADY THE LAUNCHER'S WORD FOR "NOT HERE". The pinned scan
#      already omits a directory with no `__init__`, so a badge that shipped
#      without `pet` shows seven tiles and surprises nobody. Gating rides an
#      existing, understood presentation instead of inventing one — and
#      pagination stays correct for free, because it counts what it drew.
#
# THE WEARER IS NEVER STRANDED, which is the owner's other hard line. HOME is
# firmware (`machine.reset()` → boot → the launcher) and nothing here can reach
# it; the launcher itself is never a tile; and `GATE_PROTECTED` keeps the three
# names a payload must never be able to take away.

GATE_PATH = "/state/badgelink-enabled-apps.json"
GATE_SCHEMA = 1

# `enabled_apps` is an unbounded `text[]` server-side. The badge ships 8 apps and
# the largest roster one has carried is 11, so 32 is ~3x the largest real
# payload: a list past it did not come from a console configuring this fleet, and
# it is REFUSED WHOLE rather than truncated (truncating would gate every app past
# the cut on the strength of a payload we just decided we do not understand).
GATE_MAX_APPS = 32

# The pre-decode bound. A full 32-slug payload is about 2.2 KB, so 4 KB is twice
# the largest legitimate file — and the read is capped BEFORE `json.loads`,
# because the home screen must never spend an unbounded parse on a file anything
# with filesystem access could have grown.
GATE_MAX_BYTES = 4096

# THE NAMES A BACKEND PAYLOAD CAN NEVER REMOVE. Each is here because gating it
# takes away a way BACK rather than a feature:
#   `menu`     the launcher itself. The pinned scan already skips it when it
#              builds tiles, so listing it changes nothing a wearer sees — it
#              makes gating the home screen structurally impossible rather than
#              incidentally impossible.
#   `nametag`   the name badge, and the one app reachable WITHOUT the grid: the
#              1.5 s hold and the idle ladder both launch `POSTER_APP` directly.
#              Gating its tile would leave a hardware gesture opening an app the
#              grid says is not installed.
#   `settings` "a permanent 5th launcher tile" by owner ruling (2026-08-17,
#              badgelink/OWNER-DECISIONS #2), and the badge's only local control
#              surface: brightness, sleep, and the network-status view whose job
#              is to tell a wearer networking has stopped. Gating it with a
#              payload that arrived over that network is the one failure this
#              feature can cause and cannot undo.
# Pinned equal to `enabled_apps.PROTECTED`; that tuple and this one are the knob.
GATE_PROTECTED = ("menu", "nametag", "settings")

# WHERE THE PINNED SCAN LOOKS, AND THE ONE DIRECTORY IT SKIPS BY NAME. The scan
# receives its root as an argument (`Apps("/system/apps")`) and this module never
# sees it, so `_gate_tile` has to name the same tree to ask the same question.
# Rebindable because the tests point it at a temp tree, exactly as they do with
# `GATE_PATH` and `ORDER_FILE`.
APPS_ROOT = "/system/apps"
LAUNCHER_APP = "menu"


def _gate_allowed():
    """The recorded allow-list, or None for "no gate". TOTAL: never raises.

    DELIBERATELY LAXER THAN THE WRITER, which validates each name against the
    payload slug class before recording it. Re-validating here would buy nothing
    a wearer can see: a name that is not a slug cannot match a directory the scan
    accepted, so it is already inert. The two rules that ARE safety and so live
    on both sides are the byte cap and `GATE_MAX_APPS`.
    """
    try:
        import json
        with open(GATE_PATH) as handle:
            raw = handle.read(GATE_MAX_BYTES + 1)
        if len(raw) > GATE_MAX_BYTES:
            return None
        value = json.loads(raw)
        # The two key names are `enabled_apps`'s, which owns the format; they are
        # literals here because the pin test compares the two sides' OUTPUT, so
        # a rename over there fails this suite rather than silently reading None.
        if not isinstance(value, dict) or value.get("schema") != GATE_SCHEMA:
            return None
        apps = value.get("apps")
        if not isinstance(apps, list) or len(apps) > GATE_MAX_APPS:
            return None
        allowed = [name for name in apps if isinstance(name, str) and name]
        return allowed or None
    except Exception:                                        # noqa: BLE001
        return None


def _gate_tile(name):
    """Would the pinned scan turn this name into a TILE? Never raises.

    RULE 2 COUNTS TILES BECAUSE AN EMPTY GRID IS A CRASH, and counting NAMES let
    a well-formed payload reach it (fixed 2026-08-26). `os.listdir` returns two
    classes of name the scan then throws away: `menu`, which it skips by name,
    and any directory with no `__init__.py`/`.mpy`, which is what an interrupted
    Deploy leaves. So `{"schema": 1, "apps": ["menu"]}` against a tree whose
    `nametag/` and `settings/` were half-copied "matched" on `menu`, kept the
    three protected names, and drew NOTHING — and the pinned base's
    `Apps.active` is `self.apps[self.active_index]`, read on the launcher's first
    frame, so zero tiles is an `IndexError` inside `launch()`: `fatal_error` →
    modal → `machine.reset()` → boot → the same note → the same raise. The
    USB-recovery loop, on the one app that needs a cable.

    THE PREDICATE IS THE SCAN'S, TRANSCRIBED: `path != "menu"` and either entry
    file. BOTH extensions matter — a deployed badge runs `.mpy` and only the
    playground and a hand-copied tree carry `.py`, so a `.py`-only check would
    silently take the "nothing matched" branch on every real badge and turn
    gating off. `_commit`'s `_ready` carries a comment about the same trap.

    IT COSTS STATS ONLY ON A GATED BADGE. A badge with no note never gets here
    (`launcher_order` returns before the call), and a badge with one stops at the
    first match — one or two `stat` calls in front of the first grid frame.
    """
    if name == LAUNCHER_APP:
        return False
    base = APPS_ROOT + "/" + name
    return (_installed(base + "/__init__.py")
            or _installed(base + "/__init__.mpy"))


def _apply_gate(ordered, allowed, tile=None):
    """The names that survive the gate, in the order they arrived.

    Byte-different from and behaviour-identical to `enabled_apps.gate`; the pin
    test is the contract, because the import is impossible (see §THE
    ENABLED-APPS GATE). Three rules, each a fail-soft direction:

    1. No allow-list is no gate.
    2. AN ALLOW-LIST THAT MATCHES NO INSTALLED TILE IS DISCARDED. It describes
       some other badge — a fleet-wide list for a different lineup, or a list of
       typos — and honouring it would leave a launcher holding only
       `GATE_PROTECTED`. This is also the second half of "a payload disabling
       everything is refused": `[]` is caught by rule 1, `["typo"]` here.
    3. `GATE_PROTECTED` survives any list.

    `tile` ANSWERS "could this name become a tile", and None means "assume every
    one can" — the pure-algorithm reading, which is the only thing a caller with
    no filesystem can say and what `enabled_apps.gate` documents. THE LAUNCHER
    ALWAYS PASSES `_gate_tile`; see it for why the difference is a crash and not
    a nicety.

    WHAT THIS GUARANTEES, precisely: the GATE can never reduce the grid to zero
    tiles. Rule 2 needs a match the scan will actually draw, and that name is in
    the kept list. It does NOT promise a non-empty grid — a badge with nothing
    installed has an empty one, and that is the stock launcher's own landmine
    with no payload involved.
    """
    if not allowed:
        return ordered
    matched = False
    for name in ordered:
        if name in allowed and (tile is None or tile(name)):
            matched = True
            break
    if not matched:
        return ordered
    return [name for name in ordered
            if name in allowed or name in GATE_PROTECTED]


def commit(default):
    """The launcher's commit, and the hold clock. Never raises.

    Returns the badge app's path when a 1.5-second hold completes, `default`
    when B is released below the threshold, and None otherwise.

    THE ONE REAL BEHAVIOUR CHANGE IS THAT B COMMITS ON RELEASE. It has to: B's
    press edge is what the stock launcher launches on, so B cannot be held for
    1.5 seconds without moving that. The cost is a human release time on the
    launcher's most-used key, and the collision is honest -- somebody who
    habitually leans on B gets the badge app instead of their app. Excluding B
    would preserve the press-edge launch exactly and break "any button"; the
    owner asked for any button.

    The four direction keys are NOT deferred to release, deliberately. It would
    fix the cosmetic one-cell cursor nudge a hold on A or DOWN causes, at the
    price of ~80 ms of lag on every navigation press -- a real cost on the most
    frequent interaction in the launcher, to fix an artefact that appears only
    during a deliberate 1.5-second hold and is discarded anyway, because the
    return trip resets the launcher to index 0.
    """
    try:
        return _commit(default)
    except Exception:                                        # noqa: BLE001
        _reset_hold()
        return None


def _reset_hold():
    global _holding, _progress, _held_ms
    _holding = -1
    _held_ms = 0
    _progress = 0.0
    _caselights(0.0)


def _caselights(level):
    """Four PWM LEDs, written only when the level actually moves.

    The channel that cannot be occluded and that works while the badge is held
    up to somebody else and nobody is looking at the screen. It also carries
    ACROSS the handoff: the launcher leaves them lit at the moment it hands
    over, which is exactly the window in which the badge app's screen is still
    filling in.
    """
    global _lit
    if level != _lit:
        _lit = level
        badge.caselights(level)


def _commit(default):
    global _holding, _held_ms, _progress, _stale, _ready

    if _ready is None:
        # A deployed badge runs compiled bytecode, so the nametag's entry file
        # is __init__.mpy there and __init__.py only on a source install
        # (the dev playground, or a hand-copied tree). Checking just .py
        # silently disabled the hold on every bytecode badge.
        _ready = (_installed(POSTER_APP + "/__init__.py")
                  or _installed(POSTER_APP + "/__init__.mpy"))

    down = [badge.held(key) for key in HOLD_KEYS]
    if _stale is None:
        # HELD BUT NOT PRESSED is what "stale" actually means, and the
        # distinction is `main.py`'s: it calls `badge.poll()` once before
        # launching the menu, "to eat the wakeup button press", so a key held
        # from before the launcher existed arrives with its edge already
        # consumed. A key that goes down ON this frame shows a press edge and
        # is a real gesture, even if this is the launcher's very first frame.
        _stale = [down[index] and not badge.pressed(HOLD_KEYS[index])
                  for index in range(len(HOLD_KEYS))]

    # Read this BEFORE clearing an UP key's stale latch. A B press that woke
    # the panel must still be identifiable as consumed on its release frame,
    # even though that same latch now permits its continuous HOLD to charge.
    released = _holding >= 0 and not down[_holding]
    released_stale = released and _stale[_holding]
    for index in range(len(HOLD_KEYS)):
        if not down[index]:
            _stale[index] = False

    # THE IDLE LADDER, on the same poll that sampled the buttons above.
    step = _idle_step(down)
    if step == POSTER_APP:
        # The badge, by the same route the 1.5-second hold uses -- `commit`'s
        # return value IS the launch, so part (2) of the owner's design is the
        # existing shortcut reached by a different trigger and not a new
        # destination. Nothing is dropped: a hold in progress is discarded
        # because the badge is where a completed hold was going anyway.
        _reset_hold()
        return POSTER_APP
    if step == _WOKE:
        # THE UN-DIM PRESS IS CONSUMED, and this is the decision the design
        # record left open (§4.2). It is D1's own rule generalised: "the first
        # press wakes the bar and does nothing else". At 20 s the panel is dim
        # but the screen underneath is still live and still holds its key map,
        # so a press that both un-dims AND commits is a press the wearer aimed
        # at a screen they have not looked at for half a minute.
        #
        # OWNER RULING 2026-08-25 settles the tension with the bar-arming rule:
        # the TAP is consumed, but keeping the same key down is the already
        # labelled 1.5 s hold and must work through the wake. No new threshold
        # is invented; the split is between release semantics and held level.
        #
        # WHAT IT COVERS AND WHAT IT DOES NOT. `_stale` keeps suppressing B's
        # release-launch until UP, so a wake TAP still wakes and does nothing.
        # But a continuous hold starts HERE, at the wake frame: making stale
        # suppress both meanings left a continuous hold dead indefinitely
        # and no idle rung, because `_idle_step` also touches the clock on every
        # down level. One uninterrupted key is therefore seeded into `_holding`
        # at zero progress and may charge the EXISTING 1.5 s clock below; a
        # chord remains unarmed. This does NOT suppress the grid cursor, which
        # UP/DOWN/A/C move inside the pinned `__init__.py`; reaching that would
        # need a fifth substitution to buy nothing, since a cursor nudge commits
        # nothing and the trip home resets the launcher to index 0 anyway.
        wake_index = -1
        for index in range(len(HOLD_KEYS)):
            if down[index]:
                _stale[index] = True
                if wake_index == -1:
                    wake_index = index
                else:
                    wake_index = -2
        _reset_hold()
        if wake_index >= 0:
            _holding = wake_index
        return None

    live = [index for index in range(len(HOLD_KEYS))
            if down[index]
            and (not _stale[index] or index == _holding)]

    if released:
        index = _holding
        _reset_hold()
        if index == _B and not released_stale:
            # A short press of B is the stock launcher's launch, one release
            # edge later than it used to be. A stale B woke the panel, so its
            # release is still consumed even though a continuous hold was live.
            return default
        return None

    if len(live) != 1:
        # No chords, and nothing armed while a stale key is still down.
        if _holding >= 0 or _progress:
            _reset_hold()
        return None

    index = live[0]
    if _holding != index:
        if not badge.pressed(HOLD_KEYS[index]):
            # Only a press seen INSIDE the launcher may start a hold.
            return None
        _holding = index
        _held_ms = 0
    else:
        # `ticks_delta` is sampled by the SAME poll that sampled `held`, so it
        # is the interval for which these two consecutive button levels are
        # evidence.  An implausibly large gap proves nothing and restarts the
        # gesture fail-closed; it must never make a tap look long.
        delta = badge.ticks_delta
        if delta < 0 or delta > HOLD_POLL_MAX_MS:
            _held_ms = 0
        else:
            _held_ms += delta

    if not _ready:
        # No badge app: no bar, no light, and B still commits on release.
        return None

    # MILLISECONDS, never frames. The launcher's frame rate moves with what it
    # is drawing, and the device says so louder than the host figures this
    # comment used to quote: 29.2 FPS with a shuffle filter rolling against
    # 43.6 with none, both measured on the reference badge (2026-08-24). A counted
    # hold would be a different gesture on a badge with a wallpaper, and a
    # different one again on the row that holds two quanta.
    elapsed = _held_ms - HOLD_LEAD_MS
    span = HOLD_MS - HOLD_LEAD_MS
    if elapsed <= 0:
        _progress = 0.0
        _caselights(0.0)
        return None
    _progress = elapsed / span
    if _progress >= 1.0:
        _progress = 1.0
        _caselights(_progress)
        # Fire on the first poll at or beyond the threshold, while `down` still
        # proves the initiating key is physically held. Deferring this one more
        # frame creates a release-trigger window: the wearer can lift between
        # the full-bar frame and the next poll and see the app open on key-up.
        return POSTER_APP
    _caselights(_progress)
    return None


# ---------------------------------------------------------------------------
# The home-screen shuffle: ONE filter per arrival, animated over the still
# ---------------------------------------------------------------------------
#
# THE OWNER'S DESIGN, 2026-08-23, verbatim: *"shuffle as the default animation
# for the home screen: on the home screen with your static background, a
# shuffling of the filters is the animation. when you go home, it's one
# (randomly selected) filter as an animation. the next time you go home it's a
# different / randomly selected one. no random on the actual badge."*
#
# HOW THAT LAST CLAUSE IS HONOURED, because it looks like a contradiction and is
# not. "No random on the actual badge" is the ruling that put a FIXED effect on
# `setup` (`shared/effects.py`: "no shuffle id, no `random` import, nothing
# here reads a clock"). The wearer's CARD is a saved artefact and a shuffling
# card would mean a badge that looks different every time somebody reads it.
# The LAUNCHER is not the card: it is a screen the wearer passes through, it
# persists nothing, and this feature is the animation ON it. So the rule holds
# where it was aimed and the shuffle lives only here.
#
# AND HOW IT RECONCILES WITH THE 2026-08-17 STILL RULING, which `_still_index`
# below quotes: that ruling killed the FILM's frame cycling, because twelve
# 80x60 frames stretched to 160x120 "looked laggy and blocky next to the same
# badge rendered live in `nametag`". It was a judgement about a low-resolution
# film played back badly, not about motion on the home screen in general. The
# film is still frozen to one frame and this feature does not touch that; what
# moves is a native whole-surface filter OVER that frozen frame, which has the
# film's full sharpness underneath it. Newer ruling, narrower target, no
# conflict -- and if the owner's eye disagrees, `SHUFFLE_ENABLED = False`.
#
# WHY IT FILTERS THE WALLPAPER AND NOTHING ELSE, which is D1 ("the overlay must
# not add chrome or obscure the wallpaper's identity") satisfied by ORDERING
# rather than by clipping. The pinned base's `update()` calls
# `ui.draw_background()` FIRST, then `ui.draw_header()`, then the icon grid and
# the label plate. A whole-surface filter applied at the tail of
# `_paint_background` therefore sees the wallpaper ALONE: the header, the icons,
# their labels, the pagination column and the hold bar are all painted after it
# and are never touched. Nothing is added to the panel, nothing is drawn over
# the card, and the identity underneath keeps its own geometry -- the only
# filters here are the ones that modulate light, colour and texture.
#
# ⚠ AND THE POOL WAS CUT AGAIN ON 2026-08-24, ON THE OWNER'S EYE, AFTER HE
# WATCHED IT ON GLASS. Verbatim: *"only animate the ones that definitely have a
# good animation ... contrast, vignette and maybe others don't animate great ...
# crt and grid seem very static -- can they be animated harder?"* Two things
# followed and both are below: `contrast` is OUT (`vignette` was already out on
# the flicker measurement), and `crt` and `grid` are RETUNED, not removed.
#
# **`contrast` IS AN EYE CALL AND THE INSTRUMENT DOES NOT SUPPORT IT.** Said
# plainly because the temptation is to dress a taste verdict as a measurement.
# Measured over six card films (`launcher/host/shuffle_cost.mjs`, MAGNITUDE
# columns), `contrast(6..40)` moves 0.15-1.29 of 255 per sweep step -- which is
# BETTER than `saturation`'s 0.00-1.24 and about the same as the old `crt`. So
# nothing here ranks it last, and the owner's eye is the authority. The one
# measured fact that agrees with him: on the three light card films `contrast`
# pushes the mean luma UP and toward the rail (163.5 -> 168.8, 218.5 -> 228.2)
# rather than modulating it, so what it animates on a pale badge is the panel
# getting brighter, which is the direction a badge has least room in.
#
# THE BUDGET, AND IT IS THE WHOLE REASON THIS SET IS FIVE ROWS AND NOT FOURTEEN.
# `benchmark/results/reports/2026-08-20-v3.0.2-filter-matrix.md` timed all 27
# whole-surface operations at both panels on the reference badge; 22 of
# the 27 fit one 11.43 ms VSYNC quantum at LORES. **A launcher frame is not an
# empty quantum**, so the matrix's `1Q` verdict is not the gate here.
#
# ⚠ THE FIRST DERIVATION OF THIS BUDGET WAS WRONG BY 6x AND ITS ARITHMETIC IS
# GONE FROM THIS FILE. It reasoned from the launcher's two-quantum FRAME ceiling
# of 22.868 ms and concluded "8.68 ms of the second quantum is free, so a
# 6.78 ms ceiling and a 4.50 ms gate". A frame is a body PLUS a present, and the
# present's non-waiting work sits inside the same quanta, so most of that 8.68
# was never there: measured on device, five of the seven rows it passed spilled
# into a third quantum and one of them FLICKERED between two and three. The
# record of how the wrong number was reached is `launcher/README.md`
# §"The derivation that was wrong by 6x, kept as a record" (the live budget is
# the section above it); the measurement that killed it
# is `benchmark/results/reports/2026-08-24-wave-validation.md` §3, and §4 of that
# report is the same lesson caught twice in one night (the ripple's duration
# model). **Do not re-derive a launcher frame budget from an FPS figure.**
#
# THE OWNER'S RULING, 2026-08-24: *"29.4fps is great"* -- option (a) of that
# report's §3. **THREE QUANTA IS THE ACCEPTED ENVELOPE FOR THE HOME SCREEN**, at
# a CONSTANT 29.2 FPS, which is what the deck below is now cut against. Nothing
# on this screen moves fast: it is a frozen film under a filter whose one
# argument sweeps over 4.7-7.3 s.
#
# THE MODEL, ALL DEVICE-MEASURED, NOT RE-DERIVED HERE (report §3, and
# `docs/engineering-findings.md` §"Under VSYNC an FPS reading cannot size a
# budget" states the general form `body <= N * quantum - present_floor`):
#
#   3 quanta                     34.299 ms   (3 x 11.433)
#   - the present's own floor      7.3  ms   bracketed by grid/vignette/contrast
#   = the BODY ceiling            27.0  ms
#   - the film-path control body  14.063 ms   measured, film + header + grid
#   = slack for the filter        12.9  ms
#
# THE GATE APPLIED TO THE TABLE BELOW IS 6.00 ms, AND THE MARGIN IS THE FLICKER
# LESSON RATHER THAN A GUESS. A row's device cost is its matrix `lores_ms` times
# 1.05-1.18x (measured, all seven rows, and that factor already carries the
# shuffle's own per-frame Python), so the gate keeps the worst case a half
# quantum -- 5.7 ms -- clear of the next boundary: 12.9 - 5.7 = 7.2 ms of
# allowed body delta, / 1.18 = 6.1, called **6.00**. Being marginal is worse
# than being out: see the exclusion band below.
#
# THE 2Q/3Q EXCLUSION BAND, WHICH IS A REAL CUT AND NOT A SAFETY MARGIN. Three
# device points bracket the two-quantum boundary: `grid` at 0.882 ms holds two
# quanta (43.12 FPS), `vignette` at 1.409 ms **FLICKERS** between two and three
# (38.84 FPS), `contrast` at 1.988 ms spills cleanly into three (31.20 FPS). So
# a row must be decisively one side of it -- `lores_ms <= 0.90` or
# `>= 1.95` -- and **`vignette` was REMOVED from the deck on the ruling** for
# landing in the middle. A constant rate is the product; a rate that changes
# frame to frame on the one screen a wearer stares at is not.
#
# ⚠ TWO OF THOSE THREE DEVICE POINTS ARE NO LONGER DECK ROWS, AND THAT DOES NOT
# WEAKEN THE BAND. `vignette` left on the flicker itself and `contrast` on the
# owner's eye (2026-08-24), but `SHUFFLE_CLEAN_3Q_MS = 1.95` is named after a
# MEASUREMENT and not after a membership: `contrast` at 1.988 ms is still the
# cheapest row anybody has watched spill cleanly into three quanta on hardware,
# so it is still the right lower bound. Deleting a row does not un-measure it.
#
# WHAT FELL TO THAT GATE, by measured LORES median: `phosphor` 9.340, `c64`
# 10.341, `cga` 11.520, `synthwave` 11.676, `zoom` 14.592, `edgeglow` 22.099 and
# `oilpaint` 61.483. `phosphor` is the nearest of them and it is out on the
# margin as well as on the emerald: 9.340 x 1.18 puts the body at 25.1 ms
# against a 27.0 ceiling, 0.17 of a quantum clear, which is exactly the
# marginal case `vignette` proves is the worst outcome available. **The 4.50 gate
# was the only thing keeping `gameboy` 4.884, `bloom` 4.888 and `blur` 4.906
# out, and the 6.00 gate admits all three -- so all three now fall to the cuts
# below instead:** `gameboy` takes no argument to animate, `blur` reduces
# legibility by definition, and `bloom` was re-checked against the new envelope
# and cut on a content measurement made the same day (its own paragraph, below
# the table).
#
# WHAT FELL TO HAVING NOTHING TO ANIMATE, which is a cut the cost matrix cannot
# make: `invert`, `monochrome`, `onebit`, `dither`, `nightvision`, `gameboy`,
# `c64`, `cga` and `synthwave` take NO ARGUMENTS in picovector's own API
# definition, so there is no parameter to vary over time and a "shuffle" of them
# would be a deck of static overlays. The owner asked for an animation.
#
# **`invert` IS WORTH NAMING TWICE, because it is the one a reader will ask
# about.** `invert()` takes nothing -- picovector's own signature -- so there is
# no argument to sweep and no version of this feature in which it animates. It is
# ⚛ inherent to the filter, not tool-fixable. If what was liked was a picture
# going negative and coming back, the row that does that is `saturation`, whose
# sweep runs -96 to -16: a colour DRAIN toward grey and back, in the deck, and
# staying.
#
# WHAT FELL TO NOT ANIMATING EVEN WITH AN ARGUMENT: `glitch` and `chromatic`.
# That cut needed its own instrument and the paragraph above `SHUFFLE` has both
# the instrument and the numbers.
#
# WHAT FELL TO LEGIBILITY, which beats prettiness and beats cost: `threshold`
# (INK) and `palette_dither` (NAMETAG) both quantise the panel -- `shared/
# effects.py` already records that on the palest skin in the catalogue the
# artwork "collapses to a black blob and the name partly disappears into it" --
# and `blur` reduces legibility by definition, which is the one thing a badge
# may not do. `phosphor` would also take the emerald out of a Supabase badge,
# and it is the most expensive candidate, so it loses twice.
#
# ONE FINDING THE SETUP ROW HAS THAT THIS SET DELIBERATELY DOES NOT INHERIT.
# `shared/effects.py` drops `saturation` because `saturation(-256)` is
# BYTE-IDENTICAL to `monochrome`. That is a statement about ONE argument value.
# `saturation` here sweeps -96 to -16 and never reaches -256, so it is a colour
# DRAIN and back rather than greyscale, and `monochrome` is not in this set at
# all. The dedupe does not apply and saying so is cheaper than somebody
# re-deriving it.
#
# NO PERSISTENCE AND NO SETTINGS, as asked. The roll happens once per arrival in
# `_shuffle_begin`, holds for the whole visit, and is re-rolled by the next trip
# home -- which is a `machine.reset()`, so "next arrival" is literally a fresh
# interpreter and there is nothing to clear. Five rows means a 1-in-5 chance the
# re-roll repeats; suppressing that would need the previous pick to survive a
# reset, which is persistence. (A device pass on 2026-08-24 read ten real trips
# home and got six distinct picks out of the seven rows shipping that night,
# which is the seed working -- and a 1-trip and a 2-trip smoke run first returned
# the exact signature of a stuck one, so ten is the sample size, not a round
# number. Report §2. ⚠ That run cannot be reproduced name-for-name: it drew
# `vignette` and `contrast`, and neither is in the deck.)

# HOW A PICK IS ANIMATED: ONE INTEGER, ON A TRIANGLE. Each row names the native
# filter, the LOW and HIGH of the one scalar that moves, the full down-and-back
# PERIOD in milliseconds, and the filter's own measured LORES median from the
# matrix, carried as data so a reader can re-add the budget without leaving the
# file.
#
# A TRIANGLE RATHER THAN A SINE, and integer-only: a sine needs `math` (an
# import in the one app whose failure needs USB to recover) and a float
# multiply per frame to buy an easing nobody can see at the 4-7 second periods
# below. `_shuffle_level` is three integer operations.
#
# EVERY ROW IS APPLIED ON EVERY FRAME, so the launcher's frame cost is CONSTANT.
# The obvious alternative was a duty cycle -- skip the call except during a short
# burst, which is cheaper on average and is what the brief's "glitch ticks"
# literally describes. It is not done, deliberately: a frame loop whose cost is
# bimodal wobbles between two and three quanta on the one screen a wearer stares
# at, and a 43.7-to-29.2 FPS flicker in the icon grid is a worse artefact than
# the effect is an improvement. **THAT ARGUMENT WAS MADE BEFORE ANY DEVICE
# NUMBER AND THE DEVICE THEN VINDICATED IT TWICE**: it is why `vignette` (which
# measured that exact flicker) is out of the deck, and it is the reasoning the
# owner ruled with when he accepted a constant 29.2 FPS over a two-quantum deck
# of one row. Four of the five rows below hold three quanta constantly; the
# fifth, `grid`, holds two for its whole visit, which is equally constant.
#
# THE PERIODS ARE MUTUALLY PRIME-ISH ON PURPOSE (4.3 to 7.3 s, no two equal and
# none a multiple of another): only one runs per visit, so this buys nothing
# today, but it means a future stacked pair could never beat in phase.
#
# ⚠ TWO ROWS WERE BUILT, MEASURED AND THEN CUT, AND THE MEASUREMENT IS THE WHOLE
# REASON -- neither the cost matrix nor any legibility judgement could have made
# these calls. `launcher/host/shuffle_cost.mjs` counts, for each candidate, how
# many of eight steps along its own sweep produce a DIFFERENT framebuffer. A row
# that fails that is not an animation, however cheap and however pretty:
#
#   `glitch(amount, strength)` IS NEAR-INERT ON THIS RUNTIME. Swept over 5
#   amounts x 5 strengths against photo-ish content, comparing every pixel
#   rather than an 8x8 grid, it changed **0.0% of the surface in 17 of 25
#   cells**, and the eight that moved were NON-MONOTONIC -- `glitch(4, ...)`
#   changed nothing at any strength while `glitch(8, 0.8)` reached 4.1% and
#   `glitch(8, 1.0)` fell back to 0.7%. It is deterministic (identical args
#   twice give identical bytes), so this is not a clock. **This SETTLED the
#   filter matrix's own open caveat rather than merely strengthening it**: that
#   report recorded `mutated: false` for `glitch` and read it as "likely a false
#   negative in the guard, not a no-op" because the 8x8 grid can straddle narrow
#   bands. A full-surface byte comparison has no such blind spot and still finds
#   nothing, so the guard's one complaint in 27 rows was its one correct call.
#   Recorded here because it was evidence about a shipped `setup` effect and
#   not only about this feature -- and **on 2026-08-24 that landed: `glitch` is
#   removed from `shared/effects.SHIPPED` too** (13 filters plus NONE -> 12 plus
#   NONE), on these numbers, with nothing re-measured.
#
#   `chromatic(offset, strength)` CAN ONLY STEP. `strength` scales the
#   DISPLACEMENT and the product is truncated to whole pixels, so the reach goes
#   0.0% / 11.2% / 21.4% / 30.8% in four jumps and only **2 of 8 sweep steps**
#   change the picture at all. A three-step throb is not the ambience that was
#   asked for, and an RGB split across a name is the one artefact a badge may
#   least afford. `wave` shares the truncation but survives it: `strength` there
#   also scales the sine's sub-pixel sampling, so 7 of 8 steps are distinct at a
#   1 px amplitude.
#
# ⚠ THE GATE MOVED, THE ROW THAT WAS FIRST IN THE QUEUE WAS RE-CHECKED, AND IT
# STILL DOES NOT SHIP -- FOR A REASON NOBODY HAD MEASURED. This comment used to
# say `bloom(180, intensity)` was out "on 4.888 ms against a 4.50 ms gate and
# nothing else": 8 of 8 sweep steps distinct, 48.9% of the surface between the
# ends of a 90-to-190 intensity sweep, and legibility-POSITIVE because what it
# glows is the brightest thing on the panel and on a badge that is the name.
#
# THE TIMING HALF PASSED, WITH THE LARGEST MARGIN OF ANY NON-`grid` ROW:
# 4.888 x 1.18 = 5.77 ms of body delta puts the frame body at 19.8 ms against
# the 27.0 ms three-quantum ceiling, 7.2 ms -- 0.63 of a quantum -- clear of the
# next boundary. Cost is not why it is out.
#
# **IT IS OUT BECAUSE IT IS THE ONLY CANDIDATE WHOSE EFFECT DEPENDS ON WHAT THE
# WEARER'S CARD LOOKS LIKE.** `bloom` is a THRESHOLD filter: it glows what is
# already brighter than 180 and writes nothing anywhere else. Measured in the
# pinned runtime over five card-like films
# (`launcher/host/shuffle_cost.mjs`, the CANDIDATE CONTENT section):
#
#   card                   mean luma       reach   ends   steps
#   flat dark              44.7 -> 44.7     0.0%   0.0%   0/8  <- DEAD: an
#       arrival that rolled it would look like the shuffle is off
#   dark ground/light type 75.0 -> 86.0    51.4%  46.8%   8/8  <- the intended
#       effect, and it is lovely
#   mid                   163.5 -> 190.3   53.7%  49.7%   8/8
#   light ground/dark type 218.5 -> 246.1  99.0%   8.4%   8/8  <- RAILED
#   paper-white           234.2 -> 245.6   38.7%   8.4%   8/8  <- RAILED
#
# ("ends" is how much the sweep's two extremes differ, so a railed panel shows a
# big reach and a tiny ends: the filter is doing a lot and ANIMATING almost
# nothing.) So on a light skin it is not an animation, it is a WASH-OUT: +28 of
# mean luma into the 255 rail, which is the one thing a badge may not do to a
# name, and the browser lane's own "blew the panel out" gate (mean < 232) would
# fail it. On a flat dark skin it does nothing at all. The catalogue had 88 skins
# when this was measured and has 26 since the 2026-08-27 cut; both kinds are
# still in it (8 of the 26 are pale enough to take black type), so a 1-in-7 roll
# would have been a no-op for some wearers and a white-out for others. The rows that ship are whole-field or
# structural modulations whose reach does not depend on the card's lightness --
# `contrast` animated on all five of those films too, and still lost its place on
# the owner's eye rather than on this measurement.
#
# THE RULE THIS FALLS UNDER IS ALREADY WRITTEN, TWO PARAGRAPHS UP: a row that
# fails the eight-step test is not an animation, however cheap and however
# pretty. `glitch` and `chromatic` failed it on every content; `bloom` fails it
# on the content half the catalogue produces, which is the same cut. And the
# 48.9%/8-of-8 figure that made it a candidate was measured on ONE photo-ish
# surface -- the one lightness band where it behaves.
#
# THERE IS NOTHING ELSE IN THE QUEUE. `gameboy` 4.884 and `blur` 4.906 are now
# inside the gate but fall to the two cuts below (no argument to animate;
# reduces legibility by definition), and the next cheapest candidate of any kind
# is `phosphor` at 9.340. **The deck is closed at five rows** -- and it is closed
# DOWNWARD now, not upward: the 2026-08-24 pool ruling is that the deck should
# hold only rows that definitely animate, so the next change to it is more likely
# a removal than an addition. Growing it would need option (c) of report §3 --
# buying body budget back out of the header/icon-grid path -- and nothing here
# needs re-reading for that.
#
# WHY THERE IS NO SCANLINE PHASE DRIFT, which the brief asked for by name.
# `crt(spacing, darkness, strength)` and `grid(spacing, darkness, strength)`
# expose NO offset or phase parameter in picovector's API definition, so the
# scanlines cannot be slid. Moving `spacing` instead changes the LINE COUNT,
# which reads as the whole grid snapping to a new density rather than drifting.
# So both rows breathe `darkness`, and the brief's phrase is answered with a
# limit rather than with a worse implementation. ⚛ Inherent to the filter's
# parameter list, not tool-fixable from here.
#
# ⚠ AND THAT IS WHY THE 2026-08-24 ANSWER TO *"can they be animated harder?"* IS
# A WIDER SWEEP OF THE SAME ARGUMENT AND NOTHING CLEVERER. The scanlines cannot
# slide and `spacing` cannot move without changing the line COUNT (and the cost),
# so the only knob is how dark the lines get -- and the old sweeps used a
# twentieth of its range. `crt` went 20..56 and `grid` 14..40, out of 0..255.
# Both now run **16..208**: not 0..255, because a low end of 0 is the filter
# switched OFF at the trough and an arrival would spend part of its visit looking
# like the shuffle is not running (the same objection that took `bloom` out on a
# flat dark card), and not 255 at the top, because the peak is what legibility has
# to survive. 16 is a faint lattice that is always there; 208 is emphatic.
#
# WHAT THAT BOUGHT, MEASURED over six card films by
# `launcher/host/shuffle_cost.mjs`'s MAGNITUDE columns. The figure is the mean
# absolute per-channel delta between consecutive sweep steps -- the browser
# lane's own `moved()` metric -- as a range across the six films, so the LOW end
# of each range is the worst card:
#
#            per-step motion        sweep ends differ
#   crt      0.20-1.06  ->  1.22-6.53      1.85-9.82  ->  9.88-52.30
#   grid     0.27-1.52  ->  2.27-12.29     2.51-13.32 -> 18.42-98.47
#
# **6.1x and 8.4x on the worst card, 5.3x and 7.3x end to end.** For scale, the
# row nobody has ever called static is `noise` at 5.43-8.73 per step. The old
# `crt` at 0.20 of 255 was a fifth of a level per step on the darkest card, which
# is the honest form of the validator's original *"you may not see it move"*.
#
# THE PERIODS ALSO SHORTENED, 5900 -> 4300 and 6700 -> 5100, which multiplies
# per-FRAME motion on top of the range: motion per frame is span / half-period,
# so `crt` goes 0.0122 to 0.0893 darkness-units per ms (7.3x) and `grid` 0.0078
# to 0.0753 (9.7x). At 29.2 FPS that is about 3.0 and 2.6 levels a frame -- a
# smooth ramp, not a strobe, which is why the range did most of the work and the
# period only some.
#
# ⚠ AND THE COST DID NOT MOVE, WHICH IS THE ONLY REASON THE `lores_ms` COLUMN
# BELOW IS STILL TRUE. This retune changes an ARGUMENT of a row whose device
# figure was measured at `darkness=64`, so it owes an answer to "does the shipped
# recipe cost what the row that measured it says it costs".
#
# ✅ **CLOSED ON DEVICE, 2026-08-24, on the reference badge** --
# `benchmark/badge/shuffle_darkness_probe.py`, 200 isolated calls per level over
# the real wallpaper. `darkness` IS FREE, and by a margin nothing has to be
# argued about:
#
#            min / median us across d = 0, 16, 64, 128, 208, 255
#   grid     880 / 883-884, between-level variation **1 us**
#   crt      2635-2637 / **2641 at every one of the six levels**
#
# Within-level spread is 11-28 us, so the between-level variation is an order of
# magnitude inside the instrument's own noise. The quantity that mattered was
# **26 us** (3% of grid's 0.882 ms, the amount that would drop this row into the
# 2Q/3Q flicker band that removed `vignette`); the measured variation across the
# WHOLE 0..255 range is 1 us. And the pinned frame agrees: `grid` at 208 holds two
# quanta at a 15.342 ms body against 15.339 at 16 -- **3 us apart** -- while `crt`
# is cleanly three quanta at both ends (100% of frames, min frame 33.5 ms).
#
# **The two figures below are now DEVICE figures, confirmed to 0.2%:** `grid`
# 0.882 against 883-884 us measured, `crt` 2.637 against 2641 us measured.
#
# ⚠ THE HOST LANE GOT THE SHAPE RIGHT AND THE MAGNITUDE WRONG BY AN ORDER OF
# MAGNITUDE, and that is the part to carry forward. It measured (pinned runtime,
# best-of-82 short passes) `grid(3, d)` at 77.5-87.5 us and `crt(3, d)` at
# 305.0-362.5 us, non-monotonic, no trend -- the right CONCLUSION from numbers
# that are **12.2x and 8.6x** off the device's. So a host measurement of a
# whole-surface native filter is evidence about shape and never about magnitude,
# which is the same rule the filter matrix already carries (host filter ratios
# 2.7x-7.6x out). `crt` stays 2.637 and `grid` stays 0.882.
SHUFFLE = (
    #  native         low   high  period  LORES ms
    ("saturation",    -96,   -16,   7300,  2.236),
    ("noise",          12,    22,   4700,  2.406),
    ("crt",            16,   208,   4300,  2.637),
    ("grid",           16,   208,   5100,  0.882),
    ("wave",           60,   100,   5300,  3.769),
)
# `vignette(72..168)` WAS THE FIRST ROW OF THIS TABLE UNTIL 2026-08-24 AND IS
# DELIBERATELY ABSENT. It is not a cost cut -- at 1.409 ms it is the second
# cheapest filter in the deck -- it is the flicker cut: measured on device at
# 38.84 FPS, it lands in two quanta on some frames and three on others instead of
# holding a rate, which is the artefact this file argued against before it had a
# device number for it. Re-adding it means deleting an assertion in
# `launcher/tests/test_menu_ui.py::ShuffleTests` that names this reason.
#
# `contrast(6..40)` WAS THE ROW ABOVE `saturation` UNTIL LATER THE SAME DAY, and
# it left for a different kind of reason: the owner watched the deck and said
# *"contrast, vignette and maybe others don't animate great"*. It is inside the
# gate (1.988 ms), decisively in three quanta, and it animates on all five card
# films -- so nothing mechanical excludes it and no test can. Its absence is a
# taste ruling and the paragraph above `SHUFFLE_BUDGET_MS` records what the
# instrument does and does not support about it. Re-adding it is one line here and
# one in `_shuffle_args`; do it only if the owner asks.

# `noise(amount, interval, strength)` -- "interval = refresh period in ms
# (0 = static)". THE GRAIN ANIMATES ITSELF NATIVELY, which is why this row's own
# `amount` sweep is the narrowest in the table (12..22): the shimmer is the
# native refresh and the sweep only breathes its depth. It is also why
# `shared/effects.py` could truthfully call `noise` deterministic and this file
# can truthfully call it animated -- that row passes the default 0.
NOISE_INTERVAL_MS = 90

# The gate the table above was cut with, so the number is not only in prose.
# **6.00 ms, on the owner's 2026-08-24 ruling that three quanta at a constant
# 29.2 FPS is the accepted home-screen envelope** (it was 4.50 under a
# two-quantum model whose slack was 6x out; the section header carries both the
# corrected arithmetic and the wrong one it replaced). The gate is the matrix's
# LORES median, and a row's device body delta is 1.05-1.18x that, so 6.00 keeps
# the worst case half a quantum clear of the four-quantum boundary.
# `launcher/tests/test_menu_ui.py` asserts every shipped row is inside it, that
# no row lands in the 2Q/3Q flicker band, and that the worst case is still clear
# of the ceiling.
SHUFFLE_BUDGET_MS = 6.00

# The rest of the device-measured envelope, as numbers rather than as prose, so
# a test can assert against the model instead of against a remembered figure.
# All four are measured on the reference badge, 2026-08-24 (report §3).
SHUFFLE_QUANTA = 3                  # the accepted envelope, owner ruling
SHUFFLE_PRESENT_FLOOR_MS = 7.3      # the present's own non-waiting work
SHUFFLE_CONTROL_BODY_MS = 14.063    # the film path with no filter over it
SHUFFLE_COST_TRANSFER = 1.18        # worst matrix-median -> device body delta
# The 2Q/3Q flicker band, from the three device points that bracket it: `grid`
# 0.882 holds two quanta, `vignette` 1.409 flickers, `contrast` 1.988 spills
# cleanly. A row must be at or under the first or at or over the second.
SHUFFLE_HOLDS_2Q_MS = 0.90
SHUFFLE_CLEAN_3Q_MS = 1.95

# Which row is in play for this visit, or -1 for none. -1 is also the retired
# state: one raise from a filter takes the shuffle away for the session rather
# than raising sixty times a second, exactly as one failed film blit retires
# `_film`.
_shuffle = -1
# The BOUND native method, resolved once at pick time. Resolving it per frame
# would be a dict lookup in the hot loop and, worse, would defer the
# "this runtime does not have that filter" answer to a moment where the only
# honest response is to draw nothing; resolved here, a missing filter simply
# loses its turn in the deck.
_shuffle_call = None


def _shuffle_level(ticks, low, high, period_ms):
    """The animated scalar for this millisecond. Integer only, no allocation.

    A triangle: `low` at phase 0, `high` at the half period, back to `low`.
    `high` may be BELOW `low` (`saturation` sweeps -96 to -16 the other way
    round and the arithmetic is the same), and the caller's `ticks` is
    Badgeware's own monotonic millisecond counter, so no `time` call is made in
    the frame path at all.
    """
    half = period_ms >> 1
    if half < 1:
        return low
    step = ticks % period_ms
    if step >= half:
        step = period_ms - step
    return low + (high - low) * step // half


def _shuffle_args(native, level):
    """The argument tuple for one filter at one level.

    Mirrors `shared/effects._args` on purpose -- one place per filter, keyed on
    the native name -- with the difference that exactly one argument moves.
    Every static value here is the matrix's own, so a shipped row costs what the
    row that measured it says it costs; a `crt(1, ...)` at every row instead of
    every third would be a different filter wearing a measured number.

    `level / 100.0` is how an integer table drives a FLOAT parameter. Three
    filters here take picovector's near-universal `strength` float, which is the
    subtlest knob in the whole API: it scales the effect without moving any
    geometry, so a breathing `strength` is an effect fading in and out rather
    than anything on the panel travelling.
    """
    if native == "saturation":
        return (level,)                       # a colour drain and back
    if native == "noise":
        return (level, NOISE_INTERVAL_MS)     # film grain, natively refreshed
    if native == "crt":
        return (3, level)                     # every 3rd row, darkness breathes
    if native == "grid":
        return (3, level)                     # rows AND columns, same breathe
    # `contrast` had a branch here until the 2026-08-24 pool ruling. Deleted
    # rather than left dead: an argument builder for a filter no row names is a
    # thing a reader has to check the table to rule out.
    if native == "wave":
        return (1, 1, level / 100.0)          # a 1 px sine warp, shimmering
    return ()


def _shuffle_pick(seed):
    """Which row this arrival wears. Pure, so a test can walk the whole deck.

    Returns an index into `SHUFFLE`, or -1 when the feature is off or the deck
    is empty. The modulo is the entire selection: one row, uniformly, from a
    seed the caller is responsible for making varied.
    """
    if not SHUFFLE_ENABLED or not SHUFFLE:
        return -1
    return seed % len(SHUFFLE)


def _shuffle_seed():
    """A number that must DIFFER between two trips home. Never raises.

    THIS IS THE ONE PART OF THE FEATURE THAT CAN FAIL SILENTLY AND STILL LOOK
    LIKE IT WORKS, so it is worth the paragraph. A trip home is a
    `machine.reset()` down a fixed code path, so `time.ticks_ms()` at this
    moment is very nearly a CONSTANT -- the same boot doing the same app scan
    arrives here at the same millisecond, and a millisecond seed would hand
    every arrival the same "random" filter while every test still passed. Three
    things guard against that:

      `ticks_us` FIRST. A microsecond counter has three more decimal digits of
      boot jitter than a millisecond one, and flash timing and the ADC put real
      noise in them. It is reached through `time` rather than assumed, because
      CPython has no such function and the host lane must fall back cleanly.

      THE BATTERY, which is physics. `badge.battery_voltage()` is an averaged
      ADC read, and `draw_header`'s own comment records how noisy this hardware
      makes it: "a millivolt of ADC noise near the knee moves the answer by
      several points". Its low bits cannot be the same twice.

      ONE LCG ROUND, because `% 9` reads only the low bits of whatever it is
      given, and a monotonic counter's low bits can be quantised by the clock
      that produced them. A multiply-and-shift decorrelates them; it is the same
      constant `benchmark/badge/filter_matrix_probe.py` uses to place its test
      content.

    ⚠ WHETHER THE SPREAD IS REAL IS DEVICE-PENDING, and no host lane can close
    it: the playground's clock is virtual and its battery is a fixed 4.05 V, so
    a browser run measures this function's ARITHMETIC and not its entropy. The
    check on the badge is ten trips home and ten `LAUNCHER_SHUFFLE pick=` lines
    read over serial; anything under about four distinct names in ten means the
    seed is not moving and the mixer above needs a real source.
    """
    seed = 0
    try:
        seed = time.ticks_us()
    except Exception:                                        # noqa: BLE001
        try:
            seed = time.ticks_ms()
        except Exception:                                    # noqa: BLE001
            seed = 0
    try:
        seed ^= int(badge.battery_voltage() * 100000.0)
    except Exception:                                        # noqa: BLE001
        pass
    seed &= 0xFFFFFF
    return ((seed * 1103515245 + 12345) >> 13) & 0x3FFFFF


def _shuffle_begin():
    """Roll this arrival's filter and bind it. NEVER RAISES.

    Called once from `load_end()`, beside `idle_begin()`, for the same reason
    that seam was chosen: the END substitution already puts it immediately above
    `run(update)`, so this needs no fifth patch of the pinned base.

    A ROW WHOSE FILTER IS ABSENT LOSES ITS TURN rather than costing the wearer
    the feature. 27 filters exist on v3.0.2 and on the pinned playground
    runtime, but `getattr` is how `shared/effects.apply` and `snake_view` both
    reach a native filter, and a build without one must degrade to a different
    row instead of to an exception inside `update()` -- which is a badge reset,
    not a missing animation. The walk starts at the rolled index so the roll is
    still the roll.
    """
    global _shuffle, _shuffle_call
    _shuffle = -1
    _shuffle_call = None
    try:
        if not SHUFFLE_ENABLED or not SHUFFLE:
            return
        start = _shuffle_pick(_shuffle_seed())
        if start < 0:
            return
        count = len(SHUFFLE)
        for offset in range(count):
            index = (start + offset) % count
            method = getattr(screen, SHUFFLE[index][0], None)
            if method is not None:
                _shuffle = index
                _shuffle_call = method
                print("LAUNCHER_SHUFFLE pick=%s index=%d of=%d period_ms=%d "
                      "lores_ms=%.3f skipped=%d"
                      % (SHUFFLE[index][0], index, count, SHUFFLE[index][3],
                         SHUFFLE[index][4], offset))
                return
        print("LAUNCHER_SHUFFLE pick=none of=%d reason=nofilters" % count)
    except Exception as error:                               # noqa: BLE001
        _shuffle = -1
        _shuffle_call = None
        try:
            print("LAUNCHER_SHUFFLE pick=none reason=%r" % (error,))
        except Exception:                                    # noqa: BLE001
            pass


def _shuffle_frame():
    """This frame of the arrival's filter. Cheap, and total.

    Drawn from the tail of `draw_background`, so the surface it filters is the
    WALLPAPER and nothing else -- see the section header for why that is D1
    satisfied by ordering.

    A BADGE WITH NO BAKED FILM GETS NOTHING, by `SHUFFLE_NEEDS_FILM`: the owner
    asked for an animation over "your static background", and a badge with no
    baked card has no such thing. (The second reason that constant used to give
    -- that the theme path has no derivable slack -- did not survive the device:
    the theme body is the CHEAPER of the two. See the note beside the constant.)

    IT KEEPS ANIMATING WHILE THE PANEL IS DIMMED, and that is correct rather
    than an oversight. `idle.Panel` dims by writing `display.backlight`, which
    touches the panel's brightness and not the framebuffer, so a dimmed home
    screen shows the same animation darker. It also costs nothing extra: the
    dim's own per-frame work is `idle.Panel.frame`, which writes the backlight
    only when the level MOVES -- once per idle spell -- so the combined cost of
    this feature and the dim is this feature's cost plus a handful of integer
    comparisons.

    ONE RAISE RETIRES IT FOR THE SESSION. A filter that fails on some surface
    geometry must cost the wearer their animation and not their launcher, and
    retrying it every frame would also mean printing sixty lines a second down
    the serial port somebody is reading the pick off.
    """
    global _shuffle, _shuffle_call
    if _shuffle < 0:
        return
    if SHUFFLE_NEEDS_FILM and not _film:
        # `_paint_background` has already run and has already resolved `_film`
        # -- to a decoded film, or to False for "no film, or one that failed" --
        # so this reads the branch that was actually taken rather than guessing
        # it. A badge whose film goes bad mid-session loses the shuffle on the
        # same frame it loses the wallpaper, which is the right coupling: the
        # animation exists to move the wearer's card, and there is no card.
        return
    native, low, high, period, _cost = SHUFFLE[_shuffle]
    try:
        _shuffle_call(*_shuffle_args(
            native, _shuffle_level(badge.ticks, low, high, period)))
    except Exception as error:                               # noqa: BLE001
        _shuffle = -1
        _shuffle_call = None
        try:
            print("LAUNCHER_SHUFFLE retired=%s reason=%r" % (native, error))
        except Exception:                                    # noqa: BLE001
            pass


def _hold_bar():
    """The growing bar, centre-out, in the one clear band on the panel.

    Drawn at the tail of `draw_background` so it survives BOTH paths through
    it -- a wearer with a baked wallpaper gets the same affordance as one
    without, and the early return under a film would otherwise skip it.

    Nothing is drawn at zero: this must be invisible until somebody means it.
    """
    if _progress <= 0.0:
        return
    width = int(160 * _progress)
    if width < 2:
        width = 2
    # Ramped toward the hot phosphor as it approaches the threshold, so it
    # reads in peripheral vision as well as head-on.
    screen.pen = bolt_hot if _progress >= 1.0 else phosphor
    screen.rectangle((160 - width) // 2, BAR_Y, width, BAR_H)


def draw_background():
    """The wearer's own badge, if they baked one; otherwise the theme below.

    THE HOME SCREEN IS THE ONE APP WHOSE FAILURE NEEDS USB TO RECOVER. There is
    no launcher to launch a repair from, so every path through here has to end
    in something drawn. `wallpaper.load` is total by construction — a missing,
    truncated, corrupt, future-versioned or absurdly-dimensioned film all return
    None rather than raising, proven by nine gates in `shared/tests` — and the
    bare `except` below exists anyway, because "total by construction" is a
    claim about code I can read today and this file has to survive code I
    cannot.

    ⚠ IT IS NOT CHEAPER THAN THE THEME IT REPLACES, AND THIS DOCSTRING CLAIMED
    IT WAS UNTIL 2026-08-24. The host figures behind that claim (a launcher frame
    body of 429.3 us with a film against 517.4 us procedural, 0.830x, from the
    pinned rasteriser) did not transfer: measured on device, the film body is
    14.063 ms against the theme's 12.858, so the film is **1.205 ms MORE
    expensive** and the comparison had the sign backwards. It is invisible in FPS
    because both land in two quanta with no filter over them, and it does not
    change this path -- a full-surface blit is still the cheapest way to put the
    wearer's own badge on the panel -- but the 0.830x must not be quoted again.
    Device numbers: `benchmark/results/reports/2026-08-24-wave-validation.md` §3.

    The film is a CACHE, not state: it is regenerated from the badge app in two
    presses, so a launcher that quietly ignores a bad one loses nothing the
    wearer cannot restore.

    THE FILM DOES NOT MOVE. One frame of it, chosen once, for the whole session
    -- see `_still_index`. SINCE 2026-08-23 THE PANEL DOES: `_shuffle_frame`
    runs one native filter over that frozen frame, with its parameters varying
    on a several-second cycle. The sharpness is the film's; the motion is the
    filter's; the two claims are not in conflict and the shuffle section above
    reconciles the two owner rulings behind them.

    THE HOLD BAR IS DRAWN HERE, at the tail, in both paths. Everything else the
    launcher draws is drawn after this call, so this is the last chance to put
    something on the panel that the icons will not cover -- and the early
    return under a film would otherwise leave a wearer with a wallpaper no
    affordance at all.

    ORDER MATTERS AND IT IS THE FEATURE'S WHOLE D1 ARGUMENT: background, then
    the filter, then the bar. The filter is a whole-surface pass, so anything
    drawn BEFORE it is filtered and anything drawn after it is not. The
    wallpaper is meant to be; the hold bar is an affordance and must stay the
    exact phosphor green the wearer learned, so it goes last.
    """
    _paint_background()
    _shuffle_frame()
    _hold_bar()


def _still_index(film):
    """WHICH single frame the home screen wears. Never raises.

    THE HOME SCREEN IS A STILL, AND IT IS THE LAUNCHER THAT MAKES IT ONE. That
    is an owner ruling twice over: the wallpaper's default became STILL because
    a SMOOTH film "looked laggy and blocky next to the same badge rendered live
    in `nametag`" (`identity_model.DEFAULT_HOME_MOTION`), and on 2026-08-17 he
    looked at a badge that was still animating and said so again. The home
    screen is a sharp static badge; `nametag` is where the CARD's motion lives.

    ⚠ THAT LAST SENTENCE WAS UNQUALIFIED UNTIL 2026-08-23 AND IS NOW SCOPED.
    The 2026-08-23 shuffle ruling puts an animated FILTER over this frozen
    frame, so the home screen is no longer a wholly still picture -- but the
    FILM is still frozen and this function is still the whole of that. What was
    rejected in 2026-08-17 was a blocky 80x60 film cycling its frames; what
    ships now is a full-sharpness still under a native pass whose parameters
    move. The shuffle section above owns the reconciliation.

    WHY THE DECISION IS HERE AND NOT IN THE BAKE. A default only governs a
    badge nobody has baked yet. The owner's badge holds a twelve-frame film
    baked under the old default, `Baker.reconcile` treats the disk as truth and
    copies its stamp back into the state, so nothing on that badge ever
    disagrees with itself and nothing ever asks it to change. Changing what the
    baker WRITES cannot reach a film that is already written; freezing what the
    launcher READS reaches every film there will ever be, including that one,
    with no re-bake, no migration and no state at all. The launcher's
    dependency on the badge app stays exactly zero, which is the contract this
    whole PGW1 design exists to keep.

    THE MIDPOINT, NOT FRAME 0, and that is the baker's own rule rather than a
    taste: `test_a_still_film_samples_the_middle_of_the_loop` pins a STILL bake
    to frame 6 of a 12-step walk, because "nothing about a still says its
    picture should be the instant the loop happens to restart on". A frozen
    multi-frame film should therefore show what a STILL bake of the same badge
    would have shown, and `count // 2` is that frame.

    WHAT THIS DOES NOT FIX. A multi-frame film is 80x60 -- twelve 160x120
    frames are 921,616 bytes and do not fit -- so freezing one stops the motion
    but cannot invent the sharpness. The pixels for that do not exist in the
    installed file and only a re-bake can produce them, which is what the
    schema 2 migration in `identity` is for. This is the half that needs
    nothing from the wearer.
    """
    try:
        count = film.count
        if count > 1:
            return count // 2
    except Exception:                                        # noqa: BLE001
        pass
    return 0


def _paint_background():
    global _film, _still
    if _film is None:
        try:
            _film = wallpaper.load(image) or False
        except Exception:                                    # noqa: BLE001
            _film = False
        if _film:
            _still = _still_index(_film)
    if _film:
        # USE THE RETURN VALUE. `blit_at` catches its own failure and returns
        # False, so the `try/except` that used to wrap this could never fire —
        # and the unconditional `return` under it made `_draw_supabase()`
        # structurally unreachable whenever a film was loaded. The wearer baked
        # a wallpaper and got a BLACK HOME SCREEN: no badge, and the theme it
        # replaced gone too.
        #
        # The defensive layer defended against the wrong thing. I wrapped this
        # in a bare `except` reasoning that "total by construction" is a claim
        # about code I can read today — and the callee's totality is exactly
        # what made my own error silent.
        #
        # A RECT, not a point, and not the `vec2` CLASS I passed before. A
        # multi-frame film is 80x60, so the destination has to be the
        # full-screen rectangle it scales into; a point would paint the
        # top-left quarter and look like a different bug.
        #
        # `blit`, NOT `blit_at`, and the difference is the whole of the owner's
        # 2026-08-17 ruling: `blit_at` picks `(badge.ticks // period) % count`
        # and is the only reason the home screen ever moved. `_still` is
        # resolved once, above, from the film itself.
        if _film.blit(screen, rect(0, 0, screen.width, screen.height), _still):
            return
        # One failure retires it for the session rather than retrying every
        # frame; the theme below is a complete home screen on its own.
        _film = False
    _draw_supabase()


def _draw_supabase():
    # Preserve the badge's rounded-screen language while replacing the rust CRT
    # with Supabase near-black and emerald depth.
    screen.pen = black
    screen.rectangle(0, 0, 160, 120)
    screen.pen = background
    screen.shape(shape.rounded_rectangle(0, 0, 160, 120, 8))

    band_h = 14
    for index, pen in enumerate(BANDS):
        screen.pen = pen
        screen.rectangle(3, 16 + index * band_h, 154, band_h)

    # Low-contrast grid so icons and labels remain dominant.
    screen.pen = grid
    for x in range(8, 160, 16):
        screen.rectangle(x, 17, 1, 82)
    for y in range(22, 100, 13):
        screen.rectangle(3, y, 154, 1)

    # Large abstract Supabase bolt behind the icon grid.
    screen.pen = bolt_shadow
    screen.triangle(5, 103, 59, 18, 48, 62)
    screen.triangle(48, 62, 39, 108, 111, 24)
    screen.pen = bolt_glow
    screen.triangle(17, 94, 58, 30, 49, 65)
    screen.pen = bolt_hot
    screen.triangle(49, 65, 45, 91, 87, 39)


# WHAT THE BATTERY GAUGE IS ALLOWED TO DO PER SECOND, and why it needs saying.
#
# The stock launcher reads `badge.battery_level()` fresh on EVERY frame and
# renders it into a fill twelve pixels wide -- so one pixel is 8.3% and the
# reading only has to wobble across a boundary to make the gauge flicker. It
# does wobble: the firmware derives the percentage from
# `123 - 123 / (1 + (v/3.2)**80)**0.165`, and an exponent of 80 is a very steep
# sigmoid, so a millivolt of ADC noise near the knee moves the answer by
# several points. `battery_voltage()` averages ten samples, which is not
# enough. The owner saw it as "jumping a few millimetres" on a badge that was
# simply discharging.
#
# THIS IS STOCK BEHAVIOUR, NOT OURS. Pimoroni's own menu does the same thing at
# the same coordinates; we inherited it when the launcher was themed. It is
# fixed here because we own this file, not because we broke it.
#
# Two rules, and both are needed. A minimum interval, because a battery cannot
# meaningfully change in 33 ms and anything faster is measuring noise; and a
# margin, because a level parked on a pixel boundary would otherwise flip every
# time the interval expired. Five percent is under one pixel of the twelve, so
# a real discharge still shows up promptly and a jittering one does not.
_BATTERY_PERIOD_MS = 1000
_BATTERY_MARGIN = 5
_battery_shown = None
_battery_checked = 0


def battery_percent(now):
    """The percentage to DRAW, which is not the percentage just measured.

    Charging is unchanged and deliberately not smoothed: `(now // 20) % 101` is
    an animation rather than a reading, sweeping the fill about every two
    seconds to say "charging" without a second icon.
    """
    global _battery_shown, _battery_checked
    if badge.is_charging():
        return (now // 20) % 101
    if _battery_shown is None:
        _battery_shown = max(0, min(100, int(badge.battery_level())))
        _battery_checked = now
        return _battery_shown
    if time.ticks_diff(now, _battery_checked) >= _BATTERY_PERIOD_MS:
        _battery_checked = now
        reading = max(0, min(100, int(badge.battery_level())))
        if abs(reading - _battery_shown) >= _BATTERY_MARGIN:
            _battery_shown = reading
    return _battery_shown


def draw_header():
    now = time.ticks_ms()

    screen.pen = header
    screen.rectangle(0, 0, 160, 15)
    screen.pen = phosphor
    screen.rectangle(0, 14, 160, 1)

    # THE WORDMARK, AND NO LOGO. The bolt was two procedural triangles at x=4
    # and the wordmark started at 17; the owner asked for the product name
    # instead. "SUPABASE SELECT" measures 87 px against the 134 available
    # before the battery at x=138, so it fits at the same left margin the bolt
    # used and needs no second face and no bitmap.
    screen.pen = phosphor
    screen.text("SUPABASE SELECT", 4, 2)

    battery_level = battery_percent(now)

    x, y, width, height = 138, 4, 16, 8
    screen.pen = phosphor
    screen.rectangle(x, y, width, height)
    screen.rectangle(x + width, y + 2, 1, 4)
    screen.pen = battery_empty
    screen.rectangle(x + 1, y + 1, width - 2, height - 2)
    fill = (width - 4) * battery_level // 100
    if fill:
        screen.pen = phosphor
        screen.rectangle(x + 2, y + 2, fill, height - 4)
