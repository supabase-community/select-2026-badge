"""BADGE-2 database Pet for Tufty Badgeware v3.0.2.

The hardware seam and nothing else: it wires Badgeware's injected globals into
`PetApp` (pure control) and `PetView` (all drawing), reads the wall clock exactly
once, and owns the only `store.save` call in the package.

The simulation itself lives in `pet_model`, which imports nothing and can be run
and fuzzed under CPython with no device and no browser.  `pet/README.md` explains
the split, the tuning dials and every deviation from the decided brief.
"""

import gc
import random
import sys
import time


# DERIVED, not a literal. `badgeware.launch()` and the playground's
# `pg_runtime.launch_app` both start an app with `__import__(path)` against its
# install directory, so this module's own `__name__` IS that directory, and the
# insert below is only a no-op backstop because both put it on `sys.path` first.
#
# Latent here rather than live: pet ships one build, so the literal is currently
# correct. It became a REAL defect the moment `identity` grew a second variant —
# `/system/apps/identity_hires` prepended `/system/apps/identity` to its own
# search path and imported every module, including the one thing that differed,
# out of the NEIGHBOURING app. It silently ran as the wrong resolution and would
# not have started at all on a badge carrying only the other build.
#
# Copied here because pet is the app most likely to grow a variant next, and
# because a latent defect with a known shape and a two-line fix is not worth
# leaving for someone to rediscover the hard way.
APP_ROOT = (__name__ if __name__.startswith("/system/apps/")
            else "/system/apps/pet")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

import badgeware  # noqa: F401  - presence check; the API arrives as globals

# THE MODE COMES BEFORE THE FIRST PAINT, and the loading screen paints before
# this app's first import.  `badge.mode` rebinds `builtins.screen`, so a paint
# in front of it goes into a surface the panel is about to discard.
badge.mode(LORES | VSYNC)

import loading  # noqa: E402
# FOUR STAGES, and the interesting part of pet's load is the THREE P8 DECODES
# inside `PetView`.  Each is one indivisible native call; there is no way to
# animate through one, so they are SEPARATED instead -- `PetView(on_sheet=...)`
# hands control back between them and a frame goes up each time.  Nothing else
# in this app's load blocks: `pet_model` is pure, `pet_store` is one short JSON
# read, and there is no `font.load` at LORES.
load = loading.begin(4)

import backlight  # noqa: E402
import pet_clock as clock  # noqa: E402
load.tick("-- pet_clock")
import pet_model as model  # noqa: E402
load.tick("-- pet_model")
import pet_store as store  # noqa: E402
from pet_app import PetApp  # noqa: E402
load.tick("-- pet_store, pet_app")
from pet_view import PetView  # noqa: E402
load.step("-- 6 modules imported")


BUTTONS = {
    "A": BUTTON_A,
    "B": BUTTON_B,
    "C": BUTTON_C,
    "UP": BUTTON_UP,
    "DOWN": BUTTON_DOWN,
}


class Buttons:
    """`pressed` is an edge against the previous poll; `held` is the level."""

    def pressed(self, key):
        return badge.pressed(BUTTONS[key])

    def held(self, key):
        return badge.held(BUTTONS[key])


# `badge.light_level()` is NOT a brightness fraction.  The firmware returns
# `LIGHT_SENSOR.read_u16()` — a raw 0-65535 ADC reading, with a TODO in
# badgeware/badge.py admitting as much — while `display.backlight()` takes 0..1
# and the stock firmware apps pass 0.5/1.0.  Passing the sensor straight through
# pinned the panel to full brightness on hardware and rendered pure white in the
# playground.  Pet therefore uses the shared normal app policy.
#
# An ambient-adaptive backlight is still the right idea for a badge worn all day,
# and this is the place it would go — but the u16-to-fraction curve has to be
# measured on the panel, not guessed, so it is deliberately not attempted here.
display.backlight(backlight.fraction(backlight.NORMAL))
badge.caselights(0)

# Wall time is read exactly ONCE, here.  Everything after this comes from the
# monotonic tick counter, so a badge whose RTC is wrong still plays correctly and
# the browser's virtual clock reproduces the device exactly.
_now_s = time.time()
state, load_status = store.load(_now_s)
state, open_events, open_report = clock.open_session(state, _now_s)
load.step("-- 1 row from /state/pet.json")

# Opening the app is NOT a reason to write.  `advance` is exactly additive, so a
# visit that decayed the creature and then wrote nothing is reconstructed bit for
# bit from the older `last_seen` on the next open - the fast lane asserts that
# law over whole dicts.  An unconditional boot save cost two atomic writes (up to
# 370 ms of a ten-second visit, plus flash wear on a badge opened dozens of times
# a day) and bought nothing.  What is NOT reconstructible is a save that had to be
# repaired, migrated or recovered from the backup, so that is the one case that
# still writes - and it writes a milestone, because the repaired form is what the
# backup slot should hold too.
save_count = 0
if load_status != "loaded":
    state = store.save(state, milestone=True)
    save_count = 1

buttons = Buttons()
view = PetView(screen, image, color, font, vec2, rect, APP_ROOT + "/assets",
               on_sheet=load.tick)
load.step("-- 3 sheets decoded")


def _write(value, milestone=False, previous=False):
    global save_count
    store.save(value, milestone=milestone, previous=previous)
    save_count += 1
    print("PET_SAVE n={} milestone={} previous={} health={}".format(
        save_count, 1 if milestone else 0, 1 if previous else 0,
        value["health"]))


app = PetApp(
    state,
    _write,
    now_ms=time.ticks_ms(),
    load_status=load_status,
    report=open_report,
    random_below=lambda limit: random.getrandbits(16) % limit,
    ticks_diff=time.ticks_diff,
)
load.step("-- simulation caught up")

print("PET_BOOT canvas={}x{} softkeys={} scroll={} schema={}".format(
    screen.width, screen.height, view.chrome.softkey_x, view.chrome.scroll_y,
    model.SCHEMA))
# APPEND-ONLY marker: the browser lane asserts a PREFIX of this line ending at
# away_s, so any new field goes on the END and nothing before it may move.
print("PET_OPEN status={} events={} state={} stage={} health={} data={} mood={}"
      " waste={} sick={} age_s={} feeds={} away_s={} heap_free={} clock={}".format(
          load_status, ",".join(open_events), state["state"],
          model.stage_name(state), state["health"], state["data"], state["mood"],
          state["waste"], state["sick"], state["age_s"], state["total_feeds"],
          open_report["away_s"], gc.mem_free(),
          "fast" if model.mode_of(state) else "real"))

_last_view = None
_last_lights = None


def on_exit():
    """Real, and called from both the HOME IRQ and a normal return.  Never the
    only write path: the debounce ceiling is 1000 ms so this is a backstop."""
    app.on_exit()
    print("PET_EXIT saves={} state={}".format(save_count, app.state["state"]))


def update():
    global _last_view, _last_lights
    plan = app.frame(time.ticks_ms(), buttons)
    view.draw(plan)
    lights = plan["lights"]
    if lights != _last_lights:
        badge.caselights(*lights)
        _last_lights = lights
    # Printed on CHANGE only: a per-frame print would distort frame timing and
    # make the browser's deterministic scenario traces unreadable.
    key = (plan["view"], plan["labels"], plan["mood"])
    if key != _last_view:
        _last_view = key
        print("PET_VIEW view={} mood={} keys={}|{}|{}".format(
            plan["view"], plan["mood"], *plan["labels"]))
    for event in app.events:
        if event:
            print("PET_ACT event={} health={} data={} waste={} sick={}".format(
                event, app.state["health"], app.state["data"],
                app.state["waste"], app.state["sick"]))


load.end()
run(update)
