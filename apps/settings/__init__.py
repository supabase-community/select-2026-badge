"""The Settings tile: the permanent extra launcher tile of OWNER-DECISIONS #2.

The owner's ruling, 2026-08-17 and SETTLED in the 2026-08-19 addendum: not a
bare Pair tile but a **general-purpose Settings app** that HOSTS the Pair entry,
because other settings-shaped needs are already planned (battery visibility among
them) and the launcher should pay its extra-tile cost once instead of growing a
tile per need. The addendum adds a **network status** view — connected / paired /
stopped-because-revoked-or-expired / unreachable — with an on-screen "reboot to
retry" instruction, because a badge stopped on a 403 holds until the next boot
(#14; `polltransport._enter_revoked`).

WHAT IS HERE AND WHAT IS ELSEWHERE. This file is the hardware seam and nothing
else: the mode, the guarded imports, the boot reads (the durable pair state, and
the wearer's panel level), the two impure things the rows ask for — `badge.sleep`
and `display.backlight` — the poll loop and `run(update)`. Every decision is in
`settings_model` (pure, CPython-tested) and every pixel is in `settings_view`.
The Pair and Confirm screens are Card E's landed `badgelink.pairview`
view-models, consumed and not reimplemented. **There is no badge-side unpair in
v2** and this app offers none.

THE THREE GUARDED IMPORTS, AND WHY NONE OF THEM IS A BROWSER ACCOMMODATION.

* `pairview` / `pairstate` / `store` live in **`/system/lib`** (decision #1),
  reachable only through the one `sys.path.append("/system/lib")` line
  `/system/main.py` carries. This tile and that payload are installed by two
  different steps, so a badge can have one without the other — and a bare import
  on such a badge raises INSIDE `launch()`, which resets the badge, every time,
  for ever (`docs/deploy.md`). Guarded, the tile shows one honest row instead.
* `qrcode` (in `settings_view`) is an undocumented native firmware usermod. Same
  argument: present on this firmware, not guaranteed on another.

`launcher/menu/ui.py` guards `import loading` for exactly this reason, and its
comment names the same failure: `launch()` -> `fatal_error` -> modal ->
`machine.reset()` -> the same failing import, for ever.

NO SOCKET IS OWNED HERE. `/system/main.py` installs the fail-soft boot pump and
parks its controller on `builtins`; this tile reads that live state and asks the
controller to change the durable physical-holder preference. The controller
defers its first step so this screen paints CONNECTING before the measured
blocking handshake. A stale/missing boot pump still degrades to the old honest
"Not connected" row, and pairing state is never edited by the switch.
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
# branch on here or in `badgecard`.
badge.mode(HIRES | VSYNC)
badge.caselights(0)

import backlight  # noqa: E402
import brightness_store  # noqa: E402
import settings_model  # noqa: E402
import settings_view  # noqa: E402
import ui  # noqa: E402

# THE /system/lib PAYLOAD. All three or none: `settings_model` refuses half a
# library loudly, and `store` without `pairstate` would have nothing to restore
# into.
try:
    import pairstate
    import pairview
    import store
except ImportError as exc:
    pairstate = None
    pairview = None
    store = None
    # Printed once, so a half-installed badge says which half is missing instead
    # of looking like a tile that simply does nothing.
    print("SETTINGS_LIB missing={} path={}".format(exc, "/system/lib"))

# NO LOADING SCREEN, DELIBERATELY. `docs/deploy.md` requires a `loading.spec.ts`
# WIRED row for any app that calls `loading.begin`, and this one does not: it
# imports two small pure modules and decodes no PNG, loads no font and opens no
# asset pack. The shared screen in front of that would be decoration, and the
# same argument the two keyboard benches make for two stages makes for none here.

_pair_state = None
if store is not None:
    # The durable half of the pair state (`paired` + `owner_hint`) survives a
    # reboot; codes never do. `store.load` is fail-soft by contract, so a corrupt
    # file degrades to unpaired rather than blocking the boot.
    try:
        _pair_state = pairstate.restore_durable(store.load())
    except (OSError, ValueError) as exc:
        print("SETTINGS_STATE rejected={}".format(exc))

# Firmware-injected builtins must be read as bare names. MicroPython's
# ``builtins`` module attribute lookup bypasses its override dictionary (the
# same reason Badgeware itself reads ``screen`` bare), while normal name lookup
# sees values installed by ``builtins.badgelink_network = ...``.
try:
    _network = badgelink_network
except NameError:
    _network = None
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
    pairview=pairview,
    pairstate=pairstate,
    pair_state=_pair_state,
    transport=_network,
    network_control=_network,
    push_control=_push_control,
    brightness=_brightness,
)
chrome = settings_view.build(pairview.qr_layout if pairview is not None else None)
# THE STORED LEVEL, NOT `backlight.NORMAL`, and that changed with the BRIGHTNESS
# row (owner ruling, 2026-08-24). This tile inherited the shared 85 % that every
# app which predates the wearer's ladder still opens at; hosting the CONTROL
# makes that a lie the wearer can see. A badge set to DIM would have jumped to
# 85 % on opening Settings and then shown a screen reading "The screen is set to
# DIM" -- and the first press of the ladder would have looked like a jump DOWN
# rather than one rung. The launcher, `poster` and `badgecard` already open at
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
# repeat, which is why A/B/C are read as bare edges below.
_scroll = ui.Axis(BUTTON_UP, BUTTON_DOWN)

# `bright=` is APPENDED rather than inserted, because three documents and three
# browser assertions match the head of this line as a substring.
print("SETTINGS_OPEN library={} rows={} canvas={}x{} bright={}".format(
    1 if app.library else 0, len(app.rows), screen.width, screen.height,
    _brightness))

_last_ms = time.ticks_ms()
_last_screen = None
_frame = settings_view.RetainedFrame(badge, app.menu_label)


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
    print("SETTINGS_EXIT screen={} paired={}".format(
        app.screen, 1 if app.library and app.pair.get("paired") else 0))


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


def _set_brightness(level):
    """One rung: the PANEL first, then the file. Never raises.

    THE ORDER IS THE WHOLE OF THE FEEL (button rule B6, "update the screen
    first, write later"). The flash write stalls up to 185 ms (measured) and the
    wearer is looking at the exact thing the press changed, so a write that went
    first would put a fifth of a second between the press and the light.

    THE STORE IS `/state/badgecard.json` AND THERE MUST NEVER BE A SECOND ONE.
    Leaving an app is `machine.reset()`, so nothing about this level reaches the
    launcher, `poster` or `badgecard` in RAM -- persistence is the only way a
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
    stored = None
    try:
        stored = brightness_store.write(level)
    except Exception as error:  # noqa: BLE001
        print("SETTINGS_BRIGHT_FAIL stage=store error={!r}".format(error))
    print("SETTINGS_BRIGHT level={} stored={}".format(
        level, 1 if stored is not None else 0))


def update():
    global _last_ms, _last_screen
    now = time.ticks_ms()
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

    if _network is not None:
        _network.set_active(app.screen in (settings_model.NETWORK,
                                           settings_model.PAIR,
                                           settings_model.PUSH))

    model = app.view()
    _frame.draw(model)

    # ON CHANGE, never per frame: a per-frame print distorts frame timing and
    # makes the browser's deterministic traces unreadable.
    key = (model["screen"], model.get("status"), tuple(model["softkeys"]),
           tuple(model.get("lines") or ()))
    if key != _last_screen:
        _last_screen = key
        print("SETTINGS_SCREEN screen={} status={} keys={}|{}|{} lines=[{}]".format(
            model["screen"], model.get("status", "-"),
            model["softkeys"][0] or "-",
            model["softkeys"][1] or "-",
            model["softkeys"][2] or "-",
            " / ".join(model.get("lines") or ())))


# Browser Badgeware captures this callback and returns immediately; firmware
# blocks here. In both runtimes HOME calls ``on_exit``, which is therefore the
# lifecycle seam that restores the managed clear. A module-scope ``finally``
# would restore immediately in the browser and blank every retained step.
run(update)
