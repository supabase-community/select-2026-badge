"""The Settings tile: the permanent extra launcher tile of OWNER-DECISIONS #2.

The owner's ruling, 2026-08-17 and SETTLED in the 2026-08-19 addendum: not a
bare Pair tile but a **general-purpose Settings app** that HOSTS the Pair entry,
because other settings-shaped needs are already planned (battery visibility among
them) and the launcher should pay its extra-tile cost once instead of growing a
tile per need. The addendum adds a **network status** view — connected /
stopped-because-revoked-or-expired / unreachable — with an on-screen "reboot to
retry" instruction, because a badge stopped on a 403 holds until the next boot
(#14; `polltransport._enter_revoked`).

**THE PAIR ENTRY THAT JUSTIFIED THE TILE IS DELETED (owner, 2026-08-28):** *"can
you completely remove the phone linked thing, because that's going to be just
removed from the system anyway as part of the new update."* The tile stands on
the rest of the same ruling -- the general-purpose app, six rows of
settings-shaped needs, and the launcher's extra-tile cost paid once.

⚠ THE ROW WAS ALSO BROKEN, and this file is where. `settings_model.Settings` has
a `driver=` seam that performs the pairstate server legs, and **this seam never
passed one** -- so every press of the first row of the menu resolved straight to
`pair_start_failed` and the wearer's first impression of Settings was "Could not
reach the server." A freeze triage found it; the owner's instruction retired the
feature before anybody had to decide whether to wire it.

WHAT IS HERE AND WHAT IS ELSEWHERE. This file is the hardware seam and nothing
else: the mode, the guarded imports, the boot read of the wearer's panel level,
the two impure things the rows ask for — `badge.sleep`
and `display.backlight` — the poll loop and `run(update)`. Every decision is in
`settings_model` (pure, CPython-tested) and every pixel is in `settings_view`.

THE GUARDED IMPORTS, AND WHY NONE OF THEM IS A BROWSER ACCOMMODATION.

* `store` lives in **`/system/lib`** (decision #1), reachable only through the
  one `sys.path.append("/system/lib")` line `/system/main.py` carries. This tile
  and that payload are installed by two
  different steps, so a badge can have one without the other — and a bare import
  on such a badge raises INSIDE `launch()`, which resets the badge, every time,
  for ever (`docs/deploy.md`). Guarded, the tile says so in copy instead.

  **IT IS A PRESENCE PROBE AND NOTHING IS CALLED ON IT SINCE 2026-08-28.** The
  tile used to load the durable pair record through it (`store.load()` ->
  `pairstate.restore_durable`); with the Phone row gone there is no record to
  restore, and this module consumes no shared API at all. What survives is the
  one FACT the Network, Updates and Diagnostics screens each have to state
  honestly -- "is BadgeLink installed on this badge?" -- and an import is how a
  MicroPython app asks that without touching the filesystem. Do not delete it as
  unused: `library=0` is what makes those three screens say "BadgeLink is not
  installed" instead of inventing a connection state, and the badge that SHIPS is
  the badge where that matters.
* `scorebox` is in the same payload and is guarded SEPARATELY, because the Scores
  row erases the games' own high-score files, which are the wearer's own data and
  nothing to do with networking. The production roster requires `/system/lib`,
  but this local erase must still work if that separate install is missing or
  damaged.
`settings_view` guarded `qrcode` -- an undocumented native firmware usermod --
on the same argument until 2026-08-28. The claim square was the only thing that
used it and it went with the row, so that file now imports nothing conditional.

`launcher/menu/ui.py` guards `import loading` for exactly this reason, and its
comment names the same failure: `launch()` -> `fatal_error` -> modal ->
`machine.reset()` -> the same failing import, for ever.

NO SOCKET IS OWNED HERE. `/system/main.py` installs the fail-soft boot pump and
parks its controller on `builtins`; this tile reads that live state and asks the
controller to change the durable physical-holder preference. The controller
defers its first step so this screen paints CONNECTING before the measured
blocking handshake. A stale/missing boot pump still degrades to the old honest
"Not connected" row.
"""

import sys
import time


# DERIVED, NEVER A LITERAL. Launched, `__name__` is already the install path;
# imported by name it is the bare app name and the prefix is the address the
# device would have used. `identity` records why the literal is a real defect and
# not a tidiness one.
APP_ROOT = (__name__ if __name__.startswith("/system/apps/")
            else "/system/apps/" + __name__)
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

import badgeware  # noqa: F401,E402 - presence check; the API arrives as globals

# BEFORE ANYTHING IS CONSTRUCTED. `badge.mode` rebinds `builtins.screen` to a new
# surface and `ui.Chrome()` reads `screen.width` in its constructor, so a mode set
# after the chrome is built leaves it sized to the wrong canvas.
#
# HIRES, AND THIS APP HAS NO OTHER BUILD. 320x240 at 1:1, so `ui.Chrome` loads
# `MonaSans-Medium` and every string is a real vector outline instead of a
# pixel-doubled bitmap. The owner's 2026-08-21 verdict on the LORES Confirm
# screen was three defects in one screenshot -- `DECLINE` clipped at both ends,
# the prompt ellipsized on a mostly empty panel, and all of it chunky -- and the
# first two were LORES running out of columns, not layout bugs on top of it.
# `settings_view`'s docstring has the measurements.
#
# ONE APP, NOT TWO, and that is now true product-wide: the identity surfaces are
# HIRES-only, so there is no `variant.py`, no `build_variants.py` and nothing to
# branch on here or in `setup`.
badge.mode(HIRES | VSYNC)
badge.caselights(0)

import backlight  # noqa: E402
import brightness_store  # noqa: E402
import clock_set  # noqa: E402
import idle  # noqa: E402
import score_wipe  # noqa: E402
import settings_model  # noqa: E402
import settings_view  # noqa: E402
import ui  # noqa: E402

# THE /system/lib PRESENCE PROBE. See the docstring: nothing is CALLED on this
# module, and that is deliberate rather than leftover -- the import is how the
# tile learns whether the BadgeLink payload is installed, which is the one thing
# the Network, Updates and Diagnostics screens may not guess at.
try:
    import store  # noqa: F401 - presence probe; see the module docstring
except ImportError as exc:
    store = None
    # Printed once, so a badge without the payload says so on the serial port
    # instead of looking like a tile that simply does nothing.
    print("SETTINGS_LIB missing={} path={}".format(exc, "/system/lib"))

# THE UNDELIVERED SCORE SPOOL, GUARDED SEPARATELY FROM THE THREE ABOVE, and the
# separation is the point rather than tidiness. Those three are one coupled
# payload and half of it is useless; `scorebox` is independent, and the Scores row
# must work WITHOUT it: erasing the games' own high-score files is the wearer's
# own data on their own volume. The production payload requires `/system/lib`,
# but a badge with a missing or damaged library still erases the local files it
# can and reports honestly on the spool it cannot reach.
#
# `except Exception`, not `except ImportError`, for `system/main.py`'s reason: a
# half-refreshed `/system/lib` can fail an import in more ways than one, and a
# raise at module scope inside `launch()` RESETS THE BADGE.
try:
    import scorebox
except Exception as _score_error:  # noqa: BLE001 - a reset is the alternative
    scorebox = None
    print("SETTINGS_SPOOL missing={} path={}".format(
        _score_error.__class__.__name__, "/system/lib"))

# NO LOADING SCREEN, DELIBERATELY. `docs/deploy.md` requires a `loading.spec.ts`
# WIRED row for any app that calls `loading.begin`, and this one does not: it
# imports two small pure modules and decodes no PNG, loads no font and opens no
# asset pack. The shared screen in front of that would be decoration, and the
# same argument the two keyboard benches make for two stages makes for none here.

# Firmware-injected builtins must be read as bare names. MicroPython's
# ``builtins`` module attribute lookup bypasses its override dictionary (the
# same reason Badgeware itself reads ``screen`` bare), while normal name lookup
# sees values installed by ``builtins.badgelink_network = ...``.
try:
    _network = badgelink_network
except NameError:
    _network = None

# THE EXTERNAL PCF85063A, READ AS A BARE NAME for the same MicroPython reason
# `badgelink_network` is: Badgeware injects it into `builtins` and an attribute
# lookup on the `builtins` MODULE bypasses that dictionary. `import badgeware`
# above is what constructs it (`rtc.py:80`), so on the badge it is always there.
#
# GUARDED ANYWAY, and the guard is the whole difference between "set for now" and
# a reset: the Clock row's write is called from inside `update()`, where a
# NameError reaches `fatal_error` and `machine.reset()`s the badge. `None` here
# downgrades a commit to a SYSTEM-clock-only write, which is honest -- the wearer
# is told it is lost with the battery -- rather than a crash on the one screen
# that exists to repair a badge nothing else can reach.
try:
    _rtc = rtc
except NameError:
    _rtc = None

if store is None:
    # A controller without the rest of the coupled /system/lib payload is not
    # an operable BadgeLink install. Keep the old fail-soft "Not ready" view.
    _network = None

# The P6 doorbell's control, when the boot pump has one. `push_control()` is
# None on a badge whose `/system/main.py` installed the polling baseline without
# a push factory, and then the Updates row does not exist at all rather than
# describing a transport this badge does not carry. Guarded with getattr because
# an OLDER `/system/lib` has a `network_runtime` with no such method, and an
# AttributeError here is a reset.
_push_control = None
if _network is not None:
    _reader = getattr(_network, "push_control", None)
    if callable(_reader):
        try:
            _push_control = _reader()
        except Exception as _push_error:
            print("SETTINGS_PUSH unavailable={}".format(
                _push_error.__class__.__name__))

# THE WEARER'S PANEL LEVEL, READ FROM THE ONE STORE BEFORE THE FIRST FRAME.
# `brightness_store.read` is total by contract, so a missing or hostile file
# gives the factory level rather than an exception on the launch path.
_brightness = brightness_store.read()

app = settings_model.Settings(
    library=store is not None,
    transport=_network,
    network_control=_network,
    push_control=_push_control,
    brightness=_brightness,
    score_control=score_wipe.ScoreWipe(settings_model.GAME_SCORE_PATHS,
                                       scorebox),
    # THE HAND-SET CLOCK'S ONE WRITER. Constructed unconditionally, like the
    # score wipe and unlike `push_control`: a badge with no plausible clock
    # cannot open the TLS session that would fetch one, so the repair must not
    # depend on the separately installed library whose absence it repairs.
    clock_control=clock_set.ClockSet(rtc=_rtc),
)
chrome = settings_view.build()
# THE STORED LEVEL, NOT `backlight.NORMAL`, and that changed with the BRIGHTNESS
# row (owner ruling, 2026-08-24). This tile inherited the shared 85 % that every
# app which predates the wearer's ladder still opens at; hosting the CONTROL
# makes that a lie the wearer can see. A badge set to DIM would have jumped to
# 85 % on opening Settings and then shown a screen reading "The screen is set to
# DIM" -- and the first press of the ladder would have looked like a jump DOWN
# rather than one rung. The launcher, `nametag` and `setup` already open at
# the stored level; this is the fourth reader agreeing with them.
display.backlight(backlight.fraction(_brightness))

BUTTONS = (
    ("UP", BUTTON_UP),
    ("DOWN", BUTTON_DOWN),
    ("A", BUTTON_A),
    ("B", BUTTON_B),
    ("C", BUTTON_C),
)

# One repeat curve, on the scroll keys only (button rules B4). Command keys never
# repeat, which is why A/B/C are read as bare edges below -- AND WHY THE PAGED
# SCREENS ARE READ AS BARE EDGES TOO. A page turn is a COMMAND, not a scroll: the
# axis saturates at 20 steps a second, which on a paged screen is 20 page turns
# and 20 `SETTINGS_SCREEN` key changes a second. With no host draining the USB
# CDC that is the measured stall generator -- 192 gaps in 485 s, modal 1,018 ms,
# worst 3,032 ms, against ZERO with the cable in
# (`benchmark/results/raw/2026-08-27-usb-cdc-print-blocking/`) -- so the repeat
# curve on the diagnostic screens would manufacture the exact fault they exist
# to find.
_scroll = ui.Axis(BUTTON_UP, BUTTON_DOWN)

#: The screens whose UP/DOWN turn a page, mapped to how many pages they have.
#:
#: **THE MODEL'S OWN TABLE, READ ONCE AT IMPORT, AND NOT THROUGH `getattr`.**
#: It was a `getattr` with an empty default for one commit, while the model half
#: (`PAGES`, `_page`, the `page=` keyword on both builders) was still landing --
#: and that default has to go now that it has, because a silent fallback here is
#: a silent hole: a rename would leave UP and DOWN inert on the two screens
#: ~200 badges depend on at a venue, and the drift detector in
#: `test_settings_seam` would SKIP rather than fail. A bare reference makes the
#: same mistake an import error on the bench. Both halves are one app package
#: installed in one step, so they cannot be out of step on a badge -- which is
#: what made the guard unnecessary as well as harmful.
#:
#: READ AT IMPORT rather than per frame because it never changes and `update()`
#: runs ~37 times a second.
_PAGED_SCREENS = settings_model.PAGES

# `bright=` is APPENDED rather than inserted, because three documents and three
# browser assertions match the head of this line as a substring.
print("SETTINGS_OPEN library={} rows={} canvas={}x{} bright={}".format(
    1 if app.library else 0, len(app.rows), screen.width, screen.height,
    _brightness))

_last_ms = time.ticks_ms()
_last_screen = None
_frame = settings_view.RetainedFrame(badge, app.menu_label)
_return_idle = idle.ReturnToNametag(time.ticks_ms)
_next_app = None


def on_exit():
    """Real, and called from the HOME IRQ as well as from a normal return.

    SINCE 2026-08-23 THERE IS A THIRD DOOR INTO IT: `_sleep()` below calls this
    before `badge.sleep()`. `docs/engineering-findings.md:1223-1225` is explicit
    that `on_exit` is called from both the HOME IRQ and a normal return and must
    never be the ONLY write path; a manual sleep is neither of those two, and
    waking is a FULL REBOOT (`docs/design/constraints.md:115`) with nothing
    surviving in RAM, so anything this function puts back has to be put back
    here or not at all.
    """
    _frame.restore()
    # `paired=` was dropped from this line on 2026-08-28 with the Phone row: the
    # badge holds no pairing record, so the field could only ever have printed 0.
    print("SETTINGS_EXIT screen={}".format(app.screen))
    return _next_app


def _sleep():
    """Take the badge dormant. The only route to off in the whole product.

    `badge.sleep()` WITH NO ARGUMENT, and the choice is forced rather than
    stylistic. Measured on device 2026-08-21 (report §6): the API is bimodal --
    `sleep()` reaches `powman.sleep()` and arms A/B/C/UP/DOWN as wake sources,
    while `sleep(n)` reaches `goto_dormant_for` and arms the alarm ALONE, so
    buttons are ignored until a timer the wearer did not set expires. With HOME
    not a wake source either way, the timed form would be a badge nobody can
    turn back on without a RESET tap.

    THE ORDER IS THE WHOLE OF THE SAFETY. `on_exit` first, because waking is a
    reboot and nothing survives; the network down next, because a socket left
    open across dormancy is a socket the server keeps waiting on; the print
    LAST-but-one so a serial log shows the intent even if the call does not
    return -- which it does not, on hardware.

    NEVER RAISES. An exception here would reach `fatal_error`, which draws a
    modal and resets: the wearer would get a crash for asking the badge to
    sleep. A sleep that failed leaves them on the note, which is wrong but not
    frightening, and HOME still works.
    """
    try:
        on_exit()
    except Exception as error:  # noqa: BLE001
        print("SETTINGS_SLEEP_FAIL stage=exit error={!r}".format(error))
    if _network is not None:
        try:
            _network.set_active(False)
        except Exception as error:  # noqa: BLE001
            print("SETTINGS_SLEEP_FAIL stage=network error={!r}".format(error))
    print("SETTINGS_SLEEP indefinite=1")
    try:
        badge.sleep()
        # ONLY REACHED IF THE CALL RETURNED, which on hardware it never does.
        app.sleep_failed()
    except Exception as error:  # noqa: BLE001
        # THE BROWSER'S REBOOT IS NOT A FAILURE, and the browser lane found this
        # rather than review. `playground/src/compat/.../powman.py` models sleep
        # as an event plus `machine.reset()`, which RAISES
        # `MachineResetRequested` -- and `pg_runtime.step_frame` catches that
        # exact type to end the session. A bare `except Exception` here caught it
        # first and turned a working sleep into `SETTINGS_SLEEP_FAIL`.
        #
        # THE TYPE NAME, not an import: `machine.MachineResetRequested` does not
        # exist in the firmware, so importing it would be a browser conditional
        # in shipping code, which `AGENTS.md` forbids. On hardware this branch is
        # unreachable, because `powman.sleep()` does not return at all.
        if type(error).__name__ == "MachineResetRequested":
            raise
        print("SETTINGS_SLEEP_FAIL stage=sleep error={!r}".format(error))
        # A dark panel is the only thing worse than a note that will not go
        # away, and this is neither: the wearer lands back on the menu.
        app.sleep_failed()


def _note_panel_level(fraction):
    """Tell BadgeLink the wearer just chose a panel level. Never raises.

    THE CALLING HALF OF A CROSS-LANE SEAM, `docs/design/effect-library.md` §4,
    against `NetworkService.note_panel_level`. Without this call a fleet `glyph`
    effect overwrites the wearer's brightness presses on every changed frame --
    up to ~24 a second, so the row looks broken -- and then restores whatever
    level the runtime last believed. MEASURED BEFORE THIS CALL EXISTED, driving
    the real service over the real player: a press of 0.2 during a show started
    at fleet base 1.0 held for one frame, the next nine wrote 0.4375 through
    0.83125, and the show's exit put the panel back to 1.0 and left it there.
    `/state/badgecard.json` held the wearer's 20 throughout, which is what made
    it a panel defect rather than a persistence one.

    A FRACTION, NEVER THE PERCENT. `note_panel_level` feeds `display.backlight`
    directly, and the pinned firmware reads that as a float and multiplies by
    255 (`network_runtime.install`'s comment has the binding), while this app's
    unit is a 20..100 int. Handing over 20 would ask the panel for 5100 and
    poison every later restore, and nothing on either side of the seam would
    have caught it -- the parameter is called "level" in both files.

    IT INFORMS THE RUNTIME AND IS NEVER READ BACK AS THE LEVEL. The wearer's
    choice lives in `/state/badgecard.json`, one file with four readers;
    `_panel_base` is a RECORD OF WHAT WAS WRITTEN, and a fleet `set_backlight`
    moves it too. Reading it back as authority would let a stale runtime belief
    overwrite a real press, which is this defect inverted.

    GUARDED, AND THE GUARD IS THE RESET RULE RATHER THAN DEFENSIVE STYLE. An
    `AttributeError` inside `update()` reaches `fatal_error`, which draws a
    modal and `machine.reset()`s, so an unguarded call would reset the badge on
    a BRIGHTNESS PRESS -- every press, for ever -- on any badge whose
    `/system/lib` predates this method or is damaged. Same four steps as
    `push_control` above and as `set_active` in `nametag` and `schedule`.
    """

    if _network is None:
        return
    setter = getattr(_network, "note_panel_level", None)
    if not callable(setter):
        return
    try:
        setter(fraction)
    except Exception as error:  # noqa: BLE001 - a reset is the alternative
        print("SETTINGS_BRIGHT_FAIL stage=notify error={!r}".format(error))


def _set_brightness(level):
    """One rung: the PANEL first, then the file. Never raises.

    THE ORDER IS THE WHOLE OF THE FEEL (button rule B6, "update the screen
    first, write later"). The flash write stalls up to 185 ms (measured) and the
    wearer is looking at the exact thing the press changed, so a write that went
    first would put a fifth of a second between the press and the light.

    THE STORE IS `/state/badgecard.json` AND THERE MUST NEVER BE A SECOND ONE.
    Leaving an app is `machine.reset()`, so nothing about this level reaches the
    launcher, `nametag` or `setup` in RAM -- persistence is the only way a
    level can hold, and all four apps read that one file.
    `brightness_store`'s docstring has the refusal rules that keep a brightness
    press from destroying five saved badges.

    NEITHER HALF MAY RAISE. A backlight call that throws inside `update()`
    reaches `fatal_error`, which draws a modal and resets the badge: the wearer
    would get a crash for asking for a dimmer screen. A failed WRITE is a
    smaller failure and is reported as itself -- the level is on the panel for
    this session and will not survive the next reset -- because the alternative
    (a rollback to keep the panel and the file in step) would take away the
    thing the wearer just asked for to preserve a consistency they cannot see.
    """
    try:
        display.backlight(backlight.fraction(level))
    except Exception as error:  # noqa: BLE001
        print("SETTINGS_BRIGHT_FAIL stage=panel error={!r}".format(error))
    # BADGELINK SECOND, so nothing stands between the press and the light. This
    # call preempts a running fleet show, and a preempt writes the show's own
    # restore frame to the panel before the wearer's level goes back -- three
    # register writes instead of one, none of them a present. Both orders end
    # with the wearer's level on the panel (`test_play_effect_applier`'s
    # `test_it_wins_in_EITHER_call_order` pins that), so this is B6 feel rather
    # than correctness: the wearer is looking at the exact thing the press
    # changed, and a preempt plus an attribute lookup do not belong in front of
    # it. Still ahead of the store, which stalls up to 185 ms.
    #
    # `fraction` TWICE RATHER THAN HOISTED: it is a clamp and a divide on a
    # once-per-press path, and `display.backlight(backlight.fraction(level))` is
    # matched as a literal substring by the networking lane's contract test.
    _note_panel_level(backlight.fraction(level))
    stored = None
    try:
        stored = brightness_store.write(level)
    except Exception as error:  # noqa: BLE001
        print("SETTINGS_BRIGHT_FAIL stage=store error={!r}".format(error))
    print("SETTINGS_BRIGHT level={} stored={}".format(
        level, 1 if stored is not None else 0))


def update():
    global _last_ms, _last_screen, _next_app
    now = time.ticks_ms()
    timeout_ms = (idle.DRAFT_RETURN_MS if app.idle_draft()
                  else idle.APP_RETURN_MS)
    if _return_idle.frame(
            bool(badge.held()), busy=app.idle_busy(), timeout_ms=timeout_ms):
        _next_app = idle.NAMETAG_APP
        return "idle"
    elapsed = time.ticks_diff(now, _last_ms)
    _last_ms = now
    if elapsed > 0:
        # The countdown is the Pair screen's whole honesty: a code that has
        # expired must stop being offered, whether or not anything else happened.
        # Since 2026-08-23 it also counts the sleep note down, and that is the
        # one action `tick` can return.
        for action in app.tick(elapsed):
            if action.get("type") == "sleep":
                _sleep()
                return None

    # UP/DOWN through the shared repeat curve; A/B/C as single edges.
    if app.screen in _PAGED_SCREENS:
        # BARE EDGES, NO REPEAT CURVE (B4), for the measured reason recorded on
        # `_scroll` above: a held DOWN at the axis's terminal 20 steps a second
        # is 20 page turns and 20 key-change prints a second, and a print per
        # frame into an undrained USB CDC is the 1,018 ms modal stalled frame.
        #
        # `suppress()` RATHER THAN JUST NOT CALLING `delta`, and it is not
        # bookkeeping. The axis keeps counting while this branch ignores it, so
        # a thumb held through a BACK press would dump the whole accumulated
        # burst into the menu the instant the screen changed. `Repeat.block`'s
        # own docstring is this rule -- the press that opens a screen must not
        # act on it -- and this is the same press arriving from the other side.
        _scroll.suppress()
        if badge.pressed(BUTTON_UP):
            app.press("UP")
        if badge.pressed(BUTTON_DOWN):
            app.press("DOWN")
    else:
        delta = _scroll.delta(now)
        while delta < 0:
            app.press("UP")
            delta += 1
        while delta > 0:
            app.press("DOWN")
            delta -= 1
    for name, button in BUTTONS[2:]:
        if badge.pressed(button):
            actions = app.press(name)
            for action in actions:
                if action.get("type") == "network_set":
                    print("SETTINGS_NETWORK enabled={}".format(
                        1 if action.get("enabled") else 0))
                elif action.get("type") == "push_set":
                    print("SETTINGS_PUSH enabled={} mode={}".format(
                        1 if action.get("enabled") else 0, app.push_mode()))
                elif action.get("type") == "brightness_set":
                    _set_brightness(action.get("level"))
                elif action.get("type") == "clock_set":
                    # ON THE PRESS, never per frame, and the epoch is printed
                    # because it is the value a later serial capture has to
                    # correlate a certificate failure against. `clock_set` has
                    # already printed the failing half of a partial write.
                    #
                    # THE EPOCH IS UTC, NOT THE EVENT-LOCAL DIGITS THE PANEL
                    # SHOWED. Since 2026-08-28 the editor's fields are
                    # event-local and `settings_model` converts before it
                    # validates or writes, so this line and the badge's stored
                    # clock are the same instant -- which is the only thing that
                    # makes it correlatable against a TLS failure. A reader
                    # comparing it to the stamp on the panel is looking at two
                    # frames seven hours apart, on purpose.
                    print("SETTINGS_CLOCK result={} epoch={}".format(
                        action.get("result"), action.get("epoch")))
                elif action.get("type") == "clock_rejected":
                    # THE REFUSAL IS THE INTERESTING LINE. A badge that keeps
                    # failing TLS after somebody "set the clock" is explained by
                    # exactly this: the value never reached either clock.
                    print("SETTINGS_CLOCK rejected={}".format(
                        action.get("reason")))

    if _network is not None:
        # DIAGNOSTICS IS IN THIS TUPLE SINCE 2026-08-27, REVERSING `3e4a0460`,
        # and the reversal is a priced trade rather than a tidy-up. That commit
        # left DIAG out to keep the screen a NON-PERTURBING instrument: with no
        # grant, nothing new is attempted while it is up, so the previous-cause
        # latch and the counters hold whatever state the wearer walked in with.
        # The cost was that the one screen built to watch a connection happen
        # was also the one screen that forbade it -- the owner sat on
        # Diagnostics under an NB_CONNECT=ON build and watched it never connect.
        #
        # THE ARGUMENT IS THE DEFECT, NOT A FRAME NUMBER, and that ordering is
        # deliberate. An instrument that forbids the event it displays is broken
        # whatever an establishment costs; the exclusion made "watch it connect"
        # unperformable, and this screen has no other purpose.
        #
        # ⚠ THE FRAME NUMBER OFFERED FOR THIS IS NOT EVIDENCE FOR IT. Three
        # same-night owner readings -- `Worst frame` 5163 ms (OFF, edge of
        # Wi-Fi), 5166 ms (OFF, Faraday cage), 126 ms (NB_CONNECT=ON, same cage)
        # -- are unfiled and CONFOUNDED for this purpose. In a cage the radio
        # gate alone withholds every moment (`network_runtime._service_push`:
        # `elif not online: moment = None`), so the ON reading is the price of
        # attempting NOTHING, and the TLS handshake is device-measured at
        # 735.362 ms inside ONE atomic `update()` that `open_step`'s soft budget
        # cannot pre-empt (VAL-031-BLT, `device_link.py`) -- a 126 ms frame is
        # below the floor for a frame that contained an establishment.
        # `ATTRIBUTION-LEDGER.md` Q4 still reads `NO MEASUREMENT EXISTS`.
        #
        # THE LATCH IS NOT DELETED BY THIS, WHICH IS WHY IT IS AFFORDABLE. The
        # transition that fills it is root -> a granting screen, and the ROOT is
        # still withholding: stepping root -> Diagnostics now fills the latch
        # exactly as root -> Updates already did. What is genuinely lost is that
        # Diagnostics perturbs what it shows -- its counters and the latch move
        # because you are looking. The counters are cumulative for the boot, so
        # they still read; the latch a wearer walked in with can now be
        # overwritten by the establishment this grant permits.
        #
        # REVERTING IS THIS ONE TUPLE ENTRY. `test_settings_seam.
        # PlacementScopeTests` asserts the set STRUCTURALLY (it asserted exactly
        # NETWORK/PAIR/PUSH before that change), so the set cannot widen again
        # without a visible diff.
        #
        # PAIR LEFT THIS TUPLE ON 2026-08-28 BECAUSE THE SCREEN DID, so the
        # granted set is three rather than four. It was the only entry that
        # NEEDED the grant to do its job -- the other three watch a connection
        # they do not create -- and the structural assertion is what stops that
        # from being read as room to add something back.
        _network.set_active(app.screen in (settings_model.NETWORK,
                                           settings_model.PUSH,
                                           settings_model.DIAG))

    model = app.view()
    _frame.draw(model)

    # ON CHANGE, never per frame: a per-frame print distorts frame timing and
    # makes the browser's deterministic traces unreadable.
    #
    # THE DIAGNOSTICS SCREEN IS KEYED WITHOUT ITS LINES, AND THAT IS NOT A
    # CONVENIENCE. Its body carries live counters, and `doorbells_filtered`
    # moves once per broadcast on a SHARED topic -- an 800-badge fleet show is
    # 799 suppressions on every badge, so "on change" there is a print per
    # frame. With no host draining the USB CDC that is the measured 1,018 ms
    # modal stalled frame, 192 of them in 485 s
    # (`benchmark/results/raw/2026-08-27-usb-cdc-print-blocking/`) -- the
    # instrument manufacturing the exact fault the screen was built to find.
    # The transition INTO the screen still prints, because the key still carries
    # the screen id and the bar.
    # THE CLOCK EDITOR IS KEYED WITHOUT ITS LINES FOR THE SAME MEASURED REASON
    # THE DIAGNOSTICS SCREEN IS, and it is the one screen in this tile where a
    # key AUTO-REPEATS over changing copy. Its stamp changes on every step of
    # UP/DOWN, and `ui.Axis`'s terminal rate is 20 steps a second (button rule
    # B4), so keying on the lines would be ~20 prints a second while a thumb is
    # held. With no host draining the USB CDC that is the measured stall
    # generator: 192 gaps in 485 s, modal 1,018 ms, worst 3,032 ms, against ZERO
    # with the cable in (`benchmark/results/raw/2026-08-27-usb-cdc-print-blocking/`).
    # Nothing is lost: the transition INTO the screen still prints, the bar
    # changing to the result note still prints, and the value that matters is
    # printed once by `SETTINGS_CLOCK` on the press that commits it.
    # THE PAGE JOINS THE KEY, or a page turn is invisible to a serial reader and
    # to the browser's deterministic traces -- and on a paged screen the page IS
    # the transition. It is `.get`, so every unpaged screen contributes `None`
    # and its key is what it was before paging existed.
    #
    # AND NETWORK JOINS DIAGNOSTICS AND THE CLOCK EDITOR IN DROPPING ITS LINES.
    # Its body was static copy, so keying on it was safe; it now carries
    # `Tries {}  fails {}` off `ResilientWiFi.attempts`/`failures`, which CLIMB
    # on a badge that is retrying -- which is precisely the badge somebody is
    # standing in a hall staring at. Keying on those lines is a print per frame,
    # i.e. the 1,018 ms stall above, on the screen built to explain a stall.
    # Nothing is lost: the key still carries the screen id, the status, the page
    # and the bar, so entering the screen and every page turn still print.
    key = (model["screen"], model.get("status"), model.get("page"),
           tuple(model["softkeys"]),
           () if model["screen"] in (settings_model.DIAG,
                                     settings_model.NETWORK,
                                     settings_model.CLOCK)
           else tuple(model.get("lines") or ()))
    if key != _last_screen:
        _last_screen = key
        # `page=` is APPENDED rather than inserted, for `bright=`'s reason on
        # `SETTINGS_OPEN`: documents and browser assertions match the HEAD of
        # this line as a substring.
        print("SETTINGS_SCREEN screen={} status={} keys={}|{}|{} lines=[{}] page={}".format(
            model["screen"], model.get("status", "-"),
            model["softkeys"][0] or "-",
            model["softkeys"][1] or "-",
            model["softkeys"][2] or "-",
            " / ".join(model.get("lines") or ()),
            model.get("page", "-")))


# Browser Badgeware captures this callback and returns immediately; firmware
# blocks here. In both runtimes HOME calls ``on_exit``, which is therefore the
# lifecycle seam that restores the managed clear. A module-scope ``finally``
# would restore immediately in the browser and blank every retained step.
run(update)
