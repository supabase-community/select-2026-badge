"""Select 2026 Glyph viewer: ONE app, both recorded decks.

    A / C       previous / next entry
    B           toggle the rear-light animation
    UP / DOWN   faster / slower playback

This app replaced a PAIR. `glyph` (16x6) and `glyph2x` (32x12) were the same
viewer at two densities, kept side by side while the density question was open,
and the pair cost about 60% of the production payload on its own -- 4,011,102 B
of `glyph2x` against 692,724 for `glyph`. Consolidating was pre-approved as an
upgrade: the launcher wants ONE Glyph entry, and holding both halves of an
unmade decision in one hand is a review posture, not a product one. Both decks
are still here, still selectable, now behind one tile and one player. Note that
merging did NOT remove those bytes -- see `apps-roster.json`
§production.asset_profiles, which is what does.

THE DENSITY IS AN ENTRY, NOT A BINDING, and that is the whole design of it.
`docs/badge-button-rules.md` I5 bans chords and long-press commands BY NAME, and
§9.5(b) pre-refuses both for this app specifically -- "listed only so nobody
re-proposes it". UP/DOWN are screen directions "in every app, forever" (§1) and B
is the primary action "always" (B2), so there is no key to take and no gesture
allowed to invent one. The sanctioned move is `kbgrid`'s: put the extra
dimension IN the addressable content. So A/C walk one flat list of
(technique, density) entries and the HUD names the density it is showing. No new
key, no hidden gesture, no pixel taken from the animation.

The list is TECHNIQUE-MAJOR, DENSITY-MINOR: radar 16x6, radar 32x12, wave 16x6,
wave 32x12, ... so one C press is an A/B comparison of the same animation at
both grids. That is the shape of the open gate this consolidation inherits --
"nobody has compared 32x12-at-HIRES against 16x6-at-HIRES by eye" -- and it is
the owner's stated preference for comparison pairs, recorded for snake/snake2x
in `apps-roster.json`: adjacent, because a comparison has to be one thumb
movement. On a build that ships ONE deck the list collapses to 18 entries and
A/C behave exactly as they always did.

THREE DEFAULTS, EACH ONE LINE, AND ONE OF THEM IS STILL THE OWNER'S CALL.
`RESOLUTION` is settled: HIRES, measured ship-grade 2026-08-20 on v3.0.2 (radar
30.329/30.564 authored FPS, 2.86x headroom, zero steady dropped slots).
`DENSITY` picks which entry the app OPENS on and defaults to the geometry that
measurement covers -- 16x6 with 20x40 upsampled cells. THOSE UPSAMPLED MASKS
HAVE NOW BEEN LOOKED AT, and the answer is that there is nothing to see: at 16x6
the HIRES panel is a bit-exact pixel-double of the LORES one, so `RESOLUTION`
changes no pixel on the glass at this density. The live question is 16x6 versus
32x12, which is the only axis with a visible difference on it. See `DENSITY`
below. Nothing here hardcodes a resolution, a grid or a cell size.
"""

import gc
import sys
import time


APP_ROOT = "/system/apps/glyph"
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)


# ───────────────────── THE VARIANT SEAM (2026-08-22) ────────────────────────
# ONE PLAYER, SEVERAL TILES, AND NOT ONE LINE OF THIS FILE COPIED ANYWHERE.
#
# The owner wanted four ISOLATED comparison tiles on the dev badge -- 16x6 and
# 32x12, each at LORES and at HIRES -- so he can judge the density question on
# glass with four thumbs-width tiles instead of one app that changes underneath
# him. `glyph_lores1x/` and its three siblings are those tiles, and each one is
# a ~30-line entry plus a variant module of four constants. They import THIS
# PACKAGE, which is why they cannot drift from it: they run this player, off
# these modules, out of these assets. Nothing is vendored and nothing is
# generated from this file.
#
# The mechanism is `kbgrid`/`kbqwerty`'s, whose canonical entry says it best:
# the app's own name falls out of `__name__`, the board module's name falls out
# of the app's name, and no literal appears anywhere -- which is what lets every
# entry file be the same bytes. Here the "board" is the variant.
#
# THE SHIPPING TILE SUPPLIES NO VARIANT AND THAT IS THE POINT. `glyph` has no
# `glyph_variant.py`, so the ImportError arm runs and every default below is the
# shipping default, unchanged and still the only thing a reader of this file has
# to hold in their head. A tile aliases its own module into `sys.modules` under
# this name before importing the package. See `glyph/README.md`
# § "The four comparison tiles".
try:
    import glyph_variant as _variant  # noqa: E402
except ImportError:
    _variant = None


def _tunable(name, default):
    """This variant's value for `name`, or the shipping default."""
    if _variant is None:
        return default
    return getattr(_variant, name, default)


# ─────────────────────────── THE DEFERRED DEFAULTS ──────────────────────────
# RULED (Sam, 2026-08-20): Glyph ships at true HIRES. Under VSYNC the panel
# charges nothing for it -- 87.52/s at 320x240 against 87.46/s at 160x120 --
# so every HIRES cost is compositor cost, and the compositor was measured.
RESOLUTION = _tunable("RESOLUTION", "hires")  # "hires" | "lores"

# ⏳ OWNER EYES-GATE, one line: which density the app OPENS on. THE 2026-08-21
# APPEARANCE REVIEW NARROWED THIS AND IT IS WORTH READING BEFORE FLIPPING EITHER
# LINE (`benchmark/results/reports/2026-08-21-glyph-density-flip.md`):
#
#   * "16x6" upsamples the 10x20 masks 2x into 20x40 cells -- and that upsample
#     is a BIT-EXACT pixel-double of what the panel already does to a LORES
#     pixel. 0 of 76,800 pixels differ from the 2x-scaled LORES panel on all
#     four techniques checked (`tests/test_app_smoke.py`
#     ::ResolutionEquivalenceTests). So at this density RESOLUTION above changes
#     NOTHING on glass, while costing 23.07 ms per cold tile against 5.06 ms and
#     4x the framebuffer traffic.
#   * "32x12" renders the dense deck at the bank's NATIVE cell size and is the
#     only configuration in this app where HIRES buys real detail. It was NOT
#     ship-grade on 2026-08-20 (wave's warm p99 34.291 ms against the 32.719 ms
#     authored period), but the 2026-08-21 device session measured it at
#     30.4 fps with the changed-cell memo on. **Timing no longer constrains the
#     choice; it is pure appearance.**
#
# The owner's first A/B was run against a BROKEN dense frame (a shared tile
# cache served 20x40 tiles on a 10x20 pitch; fixed in `glyph_render`), so his
# "can't tell the difference / better as lores" predates a working comparison
# and the gate is open, not answered. Side-by-side images live in the vault at
# `exports/glyph-hires-look/`; regenerate with
# `glyph/host/render_density_frames.py`.
DENSITY = _tunable("DENSITY", "16x6")  # "16x6" | "32x12"

# ISOLATION, and it is the whole reason the comparison tiles exist. False is the
# shipping behaviour: A/C walks ONE FLAT list of (technique, density) entries, so
# one C press is an A/B of the same animation at both grids -- deliberately,
# because `docs/badge-button-rules.md` I5 leaves this app no key to take and
# §9.5(b) pre-refuses a chord for it BY NAME.
#
# True drops every entry at another density from the list, so A/C walks 18
# techniques at THIS density and nothing else. That is not a second way to
# express the same feature: an A/B where the thing being compared can change
# underneath the wearer is a worse A/B than two tiles he chooses between, which
# is the owner's own read on 2026-08-22. It takes no key and adds no gesture --
# the list is simply shorter, exactly as it is on a `classic-only` install.
LOCK_DENSITY = _tunable("LOCK_DENSITY", False)

# THE ONE-LINE HUD, and OFF is a real configuration rather than a debug flag.
# On the shipping tile the strip earns its row: it names the density, which a
# grid that can change without saying so needs (see DENSITY above). On an
# isolated tile the density cannot change, so the strip would be a constant
# label plus telemetry over an animation the owner is trying to LOOK at -- and
# the owner asked for no frame-rate labels and no on-screen telemetry on the
# comparison tiles. The serial `GLYPH_STATS`/`GLYPH_MEM` lines are unaffected:
# they cost nothing on glass and are the only way to read a soak afterwards.
#
# OFF also gives back the band. Nothing else draws there, so with the HUD off
# the animation owns all 240 (or 120) rows, and `_draw_hud` is never called --
# `_present`'s return value stops gating anything.
HUD = _tunable("HUD", True)

# WHO IS SPEAKING, for a serial log with four near-identical tiles in it. The
# player cannot derive this: `__name__` is the PACKAGE's ("glyph"), not the
# tile's, because a tile imports this package rather than being it. So the
# variant says, and the shipping default is the app's own name.
TILE = _tunable("TILE", "glyph")

DEFAULT_ASSET = "radar"

# Cold `tile_bytes` is pure Python per output pixel, so a 20x40 HIRES tile costs
# 23.07 ms against 5.06 ms at 10x20 and a cold deck hitches through its first
# pass -- 21 cold dropped authored slots for wave against 2 at LORES. The repin
# said to pre-bake the tiles or warm them behind the loading screen; this warms
# the OPENING entry only. Not the whole deck: signal-ripple needs 93 distinct
# tiles where radar needs 13, so pre-warming every entry would trade a boot
# hitch for a two-second stall on every A/C press.
PREWARM_BOOT_TILES = True

# ⏳ DEVICE-UNPROVEN, off on purpose. `image.batch()` measured 1.28x on a
# command list rebuilt per frame, which is what a diff-draw does, but nothing
# else in the repository calls it and it has never run inside a glyph frame.
# Flip to True and re-run glyph_hires_probe.py to find out; the target falls
# back on its own if the runtime lacks the method.
USE_BATCH = False

# The wake sting is the shipping asset at double speed -- the same recorded
# stream, not a second capture (`glyph_stream` §"The engine clock contract").
# ⏳ The DURATION is the owner's: a wake classifier decides how long a button
# wake is worth, and 1-2 s is the brief's range, not a measurement.
STING_SCALE_MILLI = 2000
STING_DEFAULT_MS = 1500
STING_MIN_MS = 250
STING_MAX_MS = 4000

# HOW A CALLER ACTUALLY REACHES THE STING, and the honest limitation.
# `play_sting()` is a module-level function, but the module body ENDS in
# `run(update)`, which does not return -- so nothing outside this app can call
# it after boot. `badgeware.launch()` is `chdir` -> `path.insert` ->
# `__import__`, with no handle back into the imported module. That leaves
# exactly two real seams, and this is the first:
#
#   1. THIS CONSTANT. Non-zero plays a sting during the module body, before
#      `run()`, so a boot can be a sting instead of a cold cut to the viewer.
#      A supervisor that owns boot sets it by writing this line (the same
#      one-line-variant pattern `identity`/`badgecard` use for RESOLUTION), or
#      an operator sets it to preview the feel.
#   2. A supervisor that VENDORS the player modules and drives them itself,
#      which is what `supervisor/badge/supervisor/wake.py` would need:
#      `intro_ms` today returns the full intro or ZERO with no middle, and
#      `woken_by_button()` already exists and is already unused by the intro
#      policy, so the classifier has the information and no third branch.
#
# Default 0: opening the viewer from the launcher is not a wake, and a sting on
# every manual open is a delay, not a flourish.
#
# ⚠ SETTING THIS NON-ZERO BUYS AN INPUT-DEAD WINDOW OF `STING_ON_OPEN_MS +
# ARM_MS`, up to 4,090 ms at STING_MAX_MS. That is not the sting's cost being
# hidden -- it is worth stating before anyone opens this gate:
#   * `play_sting` BLOCKS and presents its own frames, and its loop calls only
#     `display.update()`. It never calls `badge.poll()`, so the pressed-set is
#     never refreshed and a press during the sting is not merely ignored, it is
#     never observed at all.
#   * the sting runs BEFORE `_armed_at` is set (see the tail of this module), so
#     ARM_MS's 90 ms comes AFTER the sting rather than overlapping it.
# Both orderings are deliberate and neither is the bug: the sting must own a
# known framebuffer, and the wake press must not step an entry underneath it.
# The undisclosed part was the DURATION.
#
# TODO (whenever the sting gate actually opens, and not before -- shipping value
# is 0, so nothing is unresponsive today): either poll inside the sting loop and
# swallow the presses, or cap the on-open sting well under STING_MAX_MS so the
# worst case is a window a wearer reads as "it is waking up" rather than as a
# dead badge. Pinned by `test_app_smoke.py::StingWindowTests`.
STING_ON_OPEN_MS = 0

# Commands are dead for this long after the app appears. Snake's constant and
# Snake's reason (`snake/badge/snake/__init__.py` ARM_MS): `badge.pressed()` is
# a membership test over a set refreshed at the END of the loop body, so the
# press that launched the app is still live on the app's first frame. THIS
# REPLACES A DRAIN LOOP THAT DID NOTHING -- see the note above `_commands_live`.
ARM_MS = 90

# ─────────── THE MEMORY VALVE, 2026-08-22, owner-reproduced on glass ─────────
# The crash this exists for, captured over serial while the owner flipped
# densities with C:
#
#   badgeware/__init__.py:52 __call__ -> badgelink network_runtime.py:1990
#   managed_update -> glyph/__init__.py update -> _step_entry -> _load_entry
#   -> glyph_stream.py:136 load
#   MemoryError: memory allocation failed, allocating 66816 bytes
#
# ⚠ 66,816 IS NOT AN ASSET SIZE AND LOOKING FOR ONE IS A DEAD END. No `.gpa` in
# the tree is that long. It is the size `read()` had grown its buffer to when
# the heap ran out, which is reproducible: on the pinned MicroPython unix port,
# squeezing the heap and reading `assets2x/radar.gpa` (73,792 B) reports
# `allocating 73728 bytes` at 73,664 B free, `allocating 69376 bytes` at 69,440
# free and `allocating 63232 bytes` at 63,104 free. THE NUMBER IN THE TRACEBACK
# IS ROUGHLY THE FREE HEAP, not the file. So the badge had ~66.8 KB free and a
# dense stream wanted ~73.9 KB CONTIGUOUS: about 7 KB short.
#
# Three things land in the same keypress, which is why one constant is not
# enough on its own (see `_read_stream`, `_stay_put`, and `glyph_render`'s
# MAX_TILE_BYTES):
#   1. the incoming stream's 49-74 KB single block,
#   2. the outgoing stream's identical block, still held while it loaded,
#   3. the tile caches, which nothing bounded and nothing could give back.
#
# HEADROOM: the read's own bytes plus this much, or the inactive geometry's
# tiles are dropped BEFORE the read rather than after it fails. 32 KB covers the
# renderer's `_previous` (768 B at 32x12) plus ~40 cold dense tiles at 800 B --
# radar's 13 and wave's 41. It deliberately does NOT cover signal-ripple's 93:
# the valve's job is to protect the ONE BIG BLOCK, and a cold tile that cannot
# be built is a repaired frame (`_present`), not a modal. Applied to the crash:
# the valve fires at 106,688 B and frees radar's 13 coarse tiles (41,600 B),
# turning 66.8 KB free into ~108 KB for a 73.9 KB read.
STREAM_HEADROOM_BYTES = 32768

# How long a degrade note holds the HUD strip. Long enough to read at a glance,
# short enough that it cannot be mistaken for the app's steady state.
MEMORY_NOTE_MS = 2000
# ────────────────────────────────────────────────────────────────────────────


badge.mode((HIRES if RESOLUTION == "hires" else LORES) | VSYNC)
# THE MODE IS SET BEFORE ANYTHING IS DRAWN OR MEASURED, and that ordering is
# load-bearing: `badge.mode` REBINDS `builtins.screen` to a new surface, so a
# held reference taken earlier (BlitTarget's screen, `memoryview(screen)`) goes
# stale and a HUD sized from the old `screen.width` would draw 160 px of chrome
# onto a 320 px panel.

import loading  # noqa: E402
# FOUR STAGES, AND GLYPH IS THE APP WHERE SUBDIVISION IS THE WHOLE STORY.  Its
# load is three raw reads -- a mask bank, a 10,240-byte colour LUT and an
# 11-73 KB recorded stream -- and every one of them was a single native `read()`
# this app sat inside.  All three now go through `load.chunked()`, which reads
# them in eight slices with a presented frame between each, so the bar moves
# through the largest blocking stretch in the app rather than over it.  Nothing
# here is deferred and nothing is left indivisible: there is no PNG decode and
# no `font.load` in this app at all.
_load = loading.begin(4)

import backlight  # noqa: E402
import glyph_render  # noqa: E402
_load.tick("-- glyph_render")
import glyph_rich_lights  # noqa: E402
import glyph_stream  # noqa: E402
_load.tick("-- glyph_stream")
import glyph_viewer  # noqa: E402
import light_calibration_2x  # noqa: E402
import wave_lights  # noqa: E402
_load.step("-- 7 modules imported")


# The canonical technique order. MEMBERSHIP is discovered from disk below,
# because which assets ship is a build decision (`apps-roster.json`
# §production.asset_profiles prunes `.gpa` files to shrink the payload); ORDER
# is fixed here so a pruned install and a full one present the same techniques
# in the same sequence.
ASSET_ORDER = (
    "radar", "wave", "signal-ripple", "arrow-field", "ring-buffer",
    "brackets", "tracks", "signal-histogram", "binary-island",
    "arrow-cleanse", "alphabet", "memory-compactor", "numbers", "column",
    "marquee", "terminal-marquee", "packet-router", "fluid-field",
    # `elephant` (2026-08-26) is DENSE-ONLY: it was sampled straight into the
    # 32x12 grid from the website's Muybridge plate and has no 16x6 sibling, so
    # `_installed()` finds it in `assets2x` and not in `assets`. It is last
    # because it arrived last -- the order is a browse sequence, not a ranking.
    "elephant",
    # THE FIVE `logo-*` DECKS (2026-08-26) ARE DENSE-ONLY AND OFF THE PACK, and
    # the second half of that is deliberate rather than incidental. They are
    # the Select 26 brand lockup, authored at 32x12 from the site's own
    # `components/brand/` code (`glyph/host/logo-lockup/`), and they are in the
    # GLYPH APP ONLY: they are absent from `identity/host/build_skin_assets.py`
    # 's `ASSET_ORDER`, so they never reach `glyphskins.gpk` and
    # `badgecard/host/generate_catalogue.py` -- which globs the packed `.gpd`
    # directory -- cannot see them. That is the owner's instruction ("add the
    # logo glyphs to glyphs but not to badgecard", 2026-08-26) and it needs no
    # exclusion mechanism because the two lists were already separate.
    #
    # It is also the only affordable arrangement: packing all five would add 22
    # keys to the browse keyframe union, which stood at 326 of a 327-key cap
    # after `elephant` (measured by `glyph/host/logo-lockup/measure_decks.py`).
    #
    # They are adjacent because a wearer comparing brand treatments wants them
    # one thumb apart, which is the same argument the density interleave makes.
    "logo-sizzle", "logo-trail", "logo-offset", "logo-left", "logo-stack",
)

# THE TWO DECKS, in the order a comparison wants them: the measured-safe
# geometry first. `cells` is the recorded grid; the CELL SIZE is never stated
# here because the renderer derives it from `screen.width // columns`, which is
# what lets one line of `RESOLUTION` retarget both decks.
DECKS = (
    ("16x6", "assets", 16, 6),
    ("32x12", "assets2x", 32, 12),
)

# WHICH MASK BANK EACH CASE WANTS, and the rule is shorter than the table:
# the classic 10x20 bank serves every geometry except a 5x10 cell. At HIRES,
# 320x240 over 32x12 is exactly 10x20 -- the classic cell -- so the dense deck
# runs `tile_bytes`'s identity path off the bank the other deck already ships
# and needs NO second bank (measured 2026-08-20: warm blit 43 µs, identical to
# LORES). Only LORES 32x12 lands on a 5x10 cell, and that wants the natively
# authored 5x10 records, because point-sampling a 10x20 mask down to 5x10 would
# throw away the antialiasing those records were built to carry.
CLASSIC_BANK = ("glyph-masks.pfb", 10, 20)
DENSE_5X10_BANK = ("glyph-masks-2x.pfb", 5, 10)

ASSET_DIR = APP_ROOT + "/assets"
LUT_PATH = ASSET_DIR + "/glyph-lut.bin"

PREFERRED_TIER = "blit"
INK_PERCENT = 100
LIGHT_CAP = 1.0
LIGHT_STATES = 40
LIGHT_DUTY_BUDGET = 1.0  # full-range review viewer; no rolling dimmer
LIGHT_INTERVAL_MS = 50
LIGHT_ATTACK_MS = 50
LIGHT_RELEASE_MS = 300


display.backlight(backlight.fraction(backlight.FULL))
badge.caselights(0)


def _installed(directory):
    """Which of ASSET_ORDER's techniques are on disk, in ASSET_ORDER order.

    A build may ship a subset, so the viewer DISCOVERS its deck rather than
    trusting a list a pruned install would contradict. A missing directory is a
    deck that was excluded from the payload, not an error.
    """
    try:
        import os
        present = set(os.listdir(APP_ROOT + "/" + directory))
    except (ImportError, OSError):
        return ()
    return tuple(name for name in ASSET_ORDER if (name + ".gpa") in present)


def _build_entries():
    """The flat A/C list: (technique, deck row) technique-major, density-minor.

    Adjacency is the feature. Stepping from an entry to its neighbour changes
    the density and holds the technique, which is exactly the comparison the
    2026-08-20 open gate asks for and cannot be done with a key this app has.
    """
    # One listdir per deck: this runs during the module body, where every
    # millisecond is a millisecond the loading screen has to cover.
    decks = []
    for row in DECKS:
        # LOCK_DENSITY prunes the LIST, not the buttons. An isolated tile ends
        # up in exactly the state a single-deck install is already in and every
        # path below it -- the HUD dropping the density token, `_opening_entry`'s
        # degradation ladder, the wrap in `_step_entry` -- is the one that was
        # already tested for a `classic-only` payload.
        if LOCK_DENSITY and row[0] != DENSITY:
            continue
        members = _installed(row[1])
        if members:
            decks.append((row, members))
    entries = []
    for technique in ASSET_ORDER:
        for row, members in decks:
            if technique in members:
                entries.append((technique, row))
    return tuple(entries), tuple(row[0] for row, _ in decks)


ENTRIES, DENSITIES = _build_entries()
if not ENTRIES:
    raise ValueError("no glyph deck is installed under " + APP_ROOT)


def _opening_entry():
    """The index DENSITY and DEFAULT_ASSET name, degrading in a stated order.

    An install that pruned the requested pair must still open on something, and
    silently opening on a different technique than the logs claim is worse than
    saying so.
    """
    for wanted in ((DEFAULT_ASSET, DENSITY), (DEFAULT_ASSET, None),
                   (None, DENSITY)):
        for index in range(len(ENTRIES)):
            technique, row = ENTRIES[index]
            if wanted[0] in (None, technique) and wanted[1] in (None, row[0]):
                if wanted != (DEFAULT_ASSET, DENSITY):
                    print(
                        "GLYPH_OPEN_NOTE %s@%s not installed; opening %s@%s"
                        % (DEFAULT_ASSET, DENSITY, technique, row[0])
                    )
                return index
    return 0


_load.step("-- %d entries, %d deck(s)" % (len(ENTRIES), len(DENSITIES)))

SCREEN_W = getattr(screen, "width", 160)
SCREEN_H = getattr(screen, "height", 120)


def _bank_choice(columns):
    """The mask bank this (resolution, density) pair wants. See CLASSIC_BANK."""
    if SCREEN_W // columns < CLASSIC_BANK[1]:
        return DENSE_5X10_BANK
    return CLASSIC_BANK


with open(LUT_PATH, "rb") as lut_file:
    RGBA_LUT = _load.chunked(lut_file, 10240, pieces=8)
_load.step("-- 10240 B colour table")

# Banks are read once and kept: stepping A/C can change which bank is in use,
# and re-reading 20,400 bytes on a keypress would stall the keypress.
_banks = {}


def _mask_bank(columns, directory, chunked=None):
    """The bank for this geometry, read once and cached.

    `chunked` is the loading screen's seam, and the 20,400-byte classic bank is
    the single largest blocking read in the app: it used to be one native
    `read()` the app sat inside with the launcher's leftover frame on the panel.
    Runtime A/C switches pass nothing and keep the one fast read, because by
    then there is an animation on screen to interrupt.
    """
    name, mask_w, mask_h = _bank_choice(columns)
    entry = _banks.get(name)
    if entry is None:
        # The bank lives beside the deck that authored it: the 5x10 records ship
        # with the dense deck, the 10x20 records with the classic one.
        for candidate in (ASSET_DIR, APP_ROOT + "/" + directory):
            try:
                with open(candidate + "/" + name, "rb") as bank_file:
                    if chunked is None:
                        entry = (bank_file.read(), mask_w, mask_h)
                    else:
                        bank_file.seek(0, 2)
                        size = bank_file.tell()
                        bank_file.seek(0)
                        entry = (
                            chunked(bank_file, size, pieces=8), mask_w, mask_h
                        )
                break
            except OSError:
                continue
        if entry is None:
            raise ValueError("mask bank %s is not installed" % name)
        _banks[name] = entry
    return entry


# Mini HUD: one single-line opaque strip. Opaque is required because the app
# owns a persistent diff-drawn framebuffer; translucent self-overdraw would
# converge to black. Button behavior remains live without bottom labels.
HUD_INK = color.rgb(225, 252, 215)
HUD_PANEL = color.rgb(0, 0, 0)
screen.font = font.sins
HUD_BAND_H = int(screen.measure_text("A")[1]) + 2


def _make_target():
    """Choose the measured hardware tier, with a loud compatible fallback."""
    if PREFERRED_TIER == "blit":
        try:
            probe = image(1, 1)
            memoryview(probe)[:4] = b"\x00\x00\x00\xff"
            if USE_BATCH and glyph_render.BatchBlitTarget.supported(screen):
                return "batch", glyph_render.BatchBlitTarget(screen, image, vec2)
            if USE_BATCH:
                print("GLYPH_TIER_NOTE screen.batch absent; using per-cell blit")
            return "blit", glyph_render.BlitTarget(screen, image, vec2)
        except (TypeError, ValueError) as error:
            print("GLYPH_TIER_NOTE blit upload unavailable: %r" % error)
    try:
        raw = memoryview(screen)
        if len(raw) >= SCREEN_W * SCREEN_H * 4:
            return "raw", glyph_render.RawTarget(raw, SCREEN_W)
        print("GLYPH_TIER_NOTE screen buffer too small: %d" % len(raw))
    except (TypeError, ValueError) as error:
        print("GLYPH_TIER_NOTE no screen buffer protocol: %r" % error)
    return "blit", glyph_render.BlitTarget(screen, image, vec2)


TIER, TARGET = _make_target()
print("GLYPH_TIER=%s" % TIER)

_entry_index = _opening_entry()
_stream = None
_renderer = None
_mask_for_lights = None
_mask_bytes_for_lights = 200
_last_frame = -1
_phase = "loop"  # compatibility token for existing probes; no viewer boot gate
_hud_dirty = True
# The degrade note: one string and a deadline, drawn in the HUD's own strip.
# `None` is the normal case and costs the HUD one identity test per frame.
_note_text = None
_note_until = 0
# Two counters, because "did it recover?" and "did it crash?" are different
# questions and a probe reading stdout cannot tell a degraded walk from a dead
# one. `_mem_reliefs` counts caches given back; `_mem_degrades` counts keypresses
# that could not be honoured. Both zero is the healthy badge.
_mem_reliefs = 0
_mem_degrades = 0
_lights_enabled = True
_light_sync = None
_light_kind = None
_armed_at = None
_channel_for_zone = wave_lights.channel_map_from_review()
_channel_source = "review" if _channel_for_zone else "fallback"
if _channel_for_zone is None:
    _channel_for_zone = wave_lights.DEFAULT_CHANNEL_FOR_ZONE
_now = time.ticks_ms()
_playhead = glyph_viewer.SpeedClock(_now, time.ticks_diff)
_metrics = glyph_viewer.ViewerMetrics(_now, time.ticks_diff)
_asset_started = _now


def _entry():
    return ENTRIES[_entry_index]


def _density():
    return _entry()[1][0]


def _grid():
    row = _entry()[1]
    return row[2], row[3]


print(
    "GLYPH_OPEN res=%s density=%s grid=%dx%d cell=%dx%d entries=%d decks=%s"
    % (
        RESOLUTION,
        _density(),
        _grid()[0],
        _grid()[1],
        SCREEN_W // _grid()[0],
        SCREEN_H // _grid()[1],
        len(ENTRIES),
        ",".join(DENSITIES),
    )
)
# A SECOND LINE RATHER THAN THREE MORE FIELDS ON THE FIRST. `GLYPH_OPEN` is
# matched by substring in `playground/e2e/glyph-viewers.spec.ts` and quoted in
# four documents; the variant fields belong to a tile and only a tile has them.
print("GLYPH_TILE name=%s lock_density=%d hud=%d variant=%d"
      % (TILE, 1 if LOCK_DENSITY else 0, 1 if HUD else 0,
         0 if _variant is None else 1))


def _slot_us():
    if _playhead.scale_milli == 0:
        return 0
    return max(
        1,
        _stream.period_wall_ms
        * 1_000_000
        // _stream.frame_count
        // _playhead.scale_milli,
    )


def _fit_hud_line(name, tail):
    """Keep metrics visible; truncate only a long technique name."""
    value = name
    while len(value) > 1 and screen.measure_text(value + tail)[0] > SCREEN_W - 4:
        value = value[:-1]
    return value + tail


def _free_heap():
    """Free heap in bytes, or None on a runtime that cannot say.

    `gc.mem_free` is MicroPython's; CPython's `gc` has no such function, and the
    host test suite runs the real module. Resolved per call rather than bound
    once so a test can swap the module in and out around a boot.
    """
    reader = getattr(gc, "mem_free", None)
    if reader is None:
        return None
    try:
        return reader()
    except Exception:
        return None


def _asset_bytes(path):
    """One `.gpa`'s size on disk, or 0 when it cannot be asked.

    The pressure valve needs the size of the block it is about to ask for, and
    the file is the only honest source: a constant would have to be the whole
    catalogue's worst case (549 KB under the `full` profile) and would fire on
    every press.
    """
    try:
        import os
        return os.stat(path)[6]
    except (ImportError, OSError, IndexError, TypeError):
        return 0


def _post_note(text):
    """Put one line in the HUD strip for MEMORY_NOTE_MS. Never a traceback."""
    global _note_text, _note_until, _hud_dirty
    _note_text = text
    _note_until = time.ticks_add(time.ticks_ms(), MEMORY_NOTE_MS)
    _hud_dirty = True


def _cell_for(row):
    """The cell size the renderer WILL derive for this deck row.

    The same arithmetic as `GlyphRenderer.__init__`, and it has to be the same:
    the point of computing it early is to name the cache the incoming renderer
    is about to select, before there is a renderer to ask.
    """
    return SCREEN_W // row[2], SCREEN_H // row[3]


def _drop_tiles_except(keep, reason):
    """Give back every tile cache except `keep`'s geometry.

    THE CHEAP LEVER. Tiles are pure cache, so this is always safe. `keep` is
    the geometry whose tiles are about to be worth something -- the INCOMING
    entry's on a load, the live one mid-animation -- and getting that argument
    right is what makes the lever free anything at all on the first flip. See
    `glyph_render.drop_geometries_except`.
    """
    global _mem_reliefs
    drop = getattr(TARGET, "drop_geometries_except", None)
    if drop is None:
        return 0
    caches, tiles = drop(keep)
    gc.collect()
    if tiles:
        _mem_reliefs += 1
        print("GLYPH_MEM_DROP why=%s keep=%dx%d caches=%d tiles=%d free=%s"
              % (reason, keep[0], keep[1], caches, tiles, _free_heap()))
    return tiles


def _draw_note():
    """The degrade note, in the HUD's strip. DRAWN EVEN WITH `HUD = False`.

    A NOTE OWNS THE WHOLE STRIP WHILE IT LIVES. There is one line of chrome in
    this app, so a note that tried to share it with five metrics would be
    truncated away on the 160 px panel -- and a wearer who just watched a
    keypress not happen needs the reason, not the frame rate.

    AND IT IS THE ONE THING THAT IGNORES `HUD`. On a comparison tile the owner
    asked for no labels and no on-screen telemetry, and this is neither: it is a
    2 s error message, shown instead of the traceback modal that used to be the
    alternative. A tile that silently declined a keypress would be the worse of
    the two failures. `_expire_note` gives the band straight back.
    """
    screen.font = font.sins
    screen.pen = HUD_PANEL
    screen.rectangle(0, 0, SCREEN_W, HUD_BAND_H)
    screen.pen = HUD_INK
    screen.text(_fit_hud_line(_note_text, ""), 2, 1)


def _expire_note():
    global _note_text, _last_frame
    _note_text = None
    if not HUD:
        # NOTHING ELSE DRAWS CHROME ON THIS TILE, so nothing would paint over
        # the strip the note borrowed -- the diff-draw skips every cell that
        # "has not changed", and those cells did not. Force one full repaint and
        # let the animation take the band back.
        _renderer.reset()
        _last_frame = -1


def _draw_hud():
    screen.font = font.sins
    screen.pen = HUD_PANEL
    screen.rectangle(0, 0, SCREEN_W, HUD_BAND_H)
    fps = glyph_viewer.format_x10(_metrics.fps_x10) + "F"
    loop = glyph_viewer.format_x10(_metrics.loop_fps_x10) + "L"
    slot = (
        "-%"
        if _metrics.slot_pct < 0
        else "%d%%" % min(999, _metrics.slot_pct)
    )
    lights = "ON" if _lights_enabled else "OFF"
    # THE DENSITY IS IN THE STRIP, and only when there is more than one deck to
    # be in. A grid that can change without saying so is unreviewable -- the
    # open gate is precisely that nobody has compared the two geometries by eye,
    # which needs the wearer to know which one is on screen. On a single-deck
    # install the token would be a constant, and a constant in a 160 px strip
    # costs a technique name for nothing.
    tail = " %s %s %s %s %s" % (
        fps,
        loop,
        slot,
        lights,
        glyph_viewer.format_speed_milli(_playhead.scale_milli),
    )
    if len(DENSITIES) > 1:
        tail += " " + _density()
    line = _fit_hud_line(_entry()[0].upper(), tail)
    screen.pen = HUD_INK
    screen.text(line, 2, 1)


def _detach_lights():
    global _light_sync, _light_kind
    if _light_sync is not None:
        try:
            _light_sync.close()
        except Exception as error:
            print("GLYPH_LIGHTS_NOTE close failed: %r" % error)
            badge.caselights(0)
    _light_sync = None
    _light_kind = None


def _attach_lights(now):
    """Build the light choreography for the live stream, or go dark.

    MemoryError IS CAUGHT HERE for the same reason `_drive_lights` catches
    everything: a light sync allocates per-technique buffers, this runs at the
    tail of every entry load, and the rear lights are the one part of this app
    whose absence a wearer can live with. `_lights_enabled` goes False so the
    HUD says OFF and B turns them back on -- the state stays honest rather than
    silently retrying every keypress.
    """
    global _lights_enabled, _hud_dirty
    try:
        _attach_lights_now(now)
    except MemoryError as error:
        print("GLYPH_MEM_LIGHTS disabled after %r free=%s"
              % (error, _free_heap()))
        _detach_lights()
        badge.caselights(0)
        _lights_enabled = False
        _hud_dirty = True
        gc.collect()


def _attach_lights_now(now):
    global _light_sync, _light_kind
    if not _lights_enabled:
        return
    lifecycle = wave_lights.lifecycle_for(
        _stream.technique, _stream.columns, _stream.rows
    )
    if lifecycle is not None:
        _light_sync = wave_lights.WaveLightChoreography(
            badge.caselights,
            _stream.frame_count,
            lifecycle[0],
            lifecycle[1],
            channel_for_zone=_channel_for_zone,
            max_level=LIGHT_CAP,
        )
        _light_kind = "wave"
    else:
        # The dense deck carries its own measured per-technique scales; the
        # classic deck's mapper keeps the module's own hardware-approved
        # defaults, which is what the 18-technique light validation ran against.
        if _density() == "32x12":
            luma_scale, motion_scale, motion_weight = (
                light_calibration_2x.calibration_for(_stream.technique)
            )
        else:
            luma_scale = motion_scale = motion_weight = None
        _light_sync = glyph_rich_lights.RichGlyphLightSync(
            badge.caselights,
            _mask_for_lights,
            RGBA_LUT,
            _stream.technique,
            _stream.columns,
            _stream.rows,
            channel_for_zone=_channel_for_zone,
            mode="motion",
            max_level=LIGHT_CAP,
            duty_budget=LIGHT_DUTY_BUDGET,
            interval_ms=LIGHT_INTERVAL_MS,
            states=LIGHT_STATES,
            attack_ms=LIGHT_ATTACK_MS,
            release_ms=LIGHT_RELEASE_MS,
            curve="linear",
            luma_scale=luma_scale,
            motion_scale=motion_scale,
            motion_weight=motion_weight,
            frame_count=_stream.frame_count,
            mask_bytes=_mask_bytes_for_lights,
            ticks_diff=time.ticks_diff,
            ticks_add=time.ticks_add,
        )
        _light_kind = "motion"
    print(
        "GLYPH_LIGHTS enabled=1 mode=%s cap=1.00 fill=%d channels=%s source=%s"
        % (
            _light_kind,
            INK_PERCENT,
            ",".join(str(channel) for channel in _channel_for_zone),
            _channel_source,
        )
    )
    if _last_frame >= 0:
        _drive_lights(_last_frame, now)


def _drive_lights(frame, now):
    global _light_sync, _light_kind, _lights_enabled, _hud_dirty
    sync = _light_sync
    if sync is None:
        return
    try:
        if _light_kind == "wave":
            sync.update(frame)
        else:
            sync.update(frame, _stream.frame_view(frame), now)
    except Exception as error:
        print("GLYPH_LIGHTS_NOTE disabled after error: %r" % error)
        _lights_enabled = False
        _hud_dirty = True
        _detach_lights()


def _print_stats(label, now):
    if _renderer is None:
        return
    stats = _renderer.stats
    print(
        "GLYPH_STATS phase=%s elapsed_ms=%d frames=%d cells_drawn=%d "
        "inherit_remapped=%d speed_milli=%d lights=%d density=%s "
        "dirty_hits=%d dirty_walks=%d"
        % (
            label,
            time.ticks_diff(now, _asset_started),
            stats["frames"],
            stats["cells_drawn"],
            stats["inherit_remapped"],
            _playhead.scale_milli,
            1 if _lights_enabled else 0,
            _density(),
            stats["dirty_hits"],
            stats["dirty_walks"],
        )
    )


def _prewarm(load=None):
    """Build the opening entry's tiles before the animation starts."""
    if not PREWARM_BOOT_TILES:
        return 0
    keys = set()
    for index in range(_stream.frame_count):
        keys |= _renderer.keys_in(_stream.frame_view(index))
    if load is None:
        return _renderer.prewarm(keys)
    # ONE PRESENTED FRAME PER TILE. A 20x40 tile is 23.07 ms of pure Python on
    # hardware, and 13 of them for radar is a third of a second: far too long a
    # gap for a spinner to sit still through if it were one blocking call.
    built = 0
    for key in keys:
        built += _renderer.prewarm((key,))
        load.tick()
    return built


def _read_stream(path, chunked, keep):
    """Load one `.gpa`, with a valve in front of the read and a retry behind it.

    THE READ IS THE ONE BIG BLOCK IN THIS APP: 49-74 KB of CONTIGUOUS heap for a
    dense stream, in a single `read()`. Everything here is about that block.

    In front, the PRESSURE VALVE (owner's option 3): if the free heap does not
    clear the file's own size plus STREAM_HEADROOM_BYTES, the inactive
    geometry's tiles go BEFORE the read rather than after it fails. Both
    geometries stay warm whenever memory is comfortable, which is the whole
    point of the A/B -- the valve is a floor, not a policy change.

    Behind, ONE RETRY (owner's option 1). `gc.collect()` first, and it is not
    cosmetic: a `read()` that raised part-way has already grown a buffer of tens
    of KB and that buffer is unreachable garbage the moment the exception
    unwinds. Reclaiming it is often the whole difference on a 7 KB shortfall.
    Then the inactive tiles, then exactly one more attempt -- not a loop, because
    a second failure means the shortfall is not cache-shaped and `_stay_put` has
    a better answer than trying harder.
    """
    needed = _asset_bytes(path)
    free = _free_heap()
    if free is not None and needed and free < needed + STREAM_HEADROOM_BYTES:
        print("GLYPH_MEM_TIGHT need=%d free=%d path=%s"
              % (needed + STREAM_HEADROOM_BYTES, free, path))
        _drop_tiles_except(keep, "valve")
    try:
        return glyph_stream.load(path, chunked)
    except MemoryError as error:
        print("GLYPH_MEM_RETRY bytes=%d free=%s err=%r"
              % (needed, _free_heap(), error))
        gc.collect()
        _drop_tiles_except(keep, "retry")
        return glyph_stream.load(path, chunked)


def _load_entry(now, chunked=None, prewarm_load=None):
    global _stream, _renderer, _last_frame, _asset_started, _hud_dirty
    global _mask_for_lights, _mask_bytes_for_lights
    _detach_lights()
    name, row = _entry()
    density, directory = row[0], row[1]
    # FREE THEN LOAD, NOT LOAD THEN SWAP (owner's option 2), and the ordering is
    # the fix as much as the retry is. This used to build the incoming stream
    # and renderer while `_stream`/`_renderer` still named the outgoing ones, so
    # the peak held TWO 49-74 KB stream buffers plus two diff-memos (up to
    # 32 KB each) plus two `_previous` grids -- on the one keypress that also
    # wants a fresh 74 KB contiguous block. Dropping the names first, with a
    # collect, means the incoming read is asked for against a heap that has
    # already given the outgoing entry back.
    #
    # The cost of being wrong here is bounded and paid for: if the load fails,
    # the outgoing entry is gone too, and `_stay_put` re-reads it -- one flash
    # read of a stream that was resident a moment ago, against a heap that has
    # since had every tile cache emptied into it.
    _stream = None
    _renderer = None
    gc.collect()
    bank, mask_w, mask_h = _mask_bank(row[2], directory, chunked)
    stream = _read_stream(
        APP_ROOT + "/" + directory + "/" + name + ".gpa",
        chunked,
        _cell_for(row),
    )
    _mask_for_lights = bank
    _mask_bytes_for_lights = mask_w * mask_h
    _stream = stream
    _renderer = glyph_render.GlyphRenderer(
        bank,
        RGBA_LUT,
        _stream.columns,
        _stream.rows,
        SCREEN_W,
        SCREEN_H,
        TARGET,
        mask_width=mask_w,
        mask_height=mask_h,
    )
    _last_frame = -1
    _asset_started = now
    _playhead.reset(now)
    _metrics.reset(now)
    print(
        "GLYPH_PLAY asset=%s density=%s frames=%d period_wall_ms=%d loop=%d "
        "cells=%d bank=%dx%d"
        % (
            name,
            density,
            _stream.frame_count,
            _stream.period_wall_ms,
            _stream.loop_class,
            _stream.cell_count,
            mask_w,
            mask_h,
        )
    )
    # PRE-WARMING IS PURE OPTIMISATION, so it is the first thing to give up. The
    # animation builds a tile the first time it needs one either way; losing the
    # warm-up costs a visible first-pass hitch (23.07 ms per cold 20x40 tile on
    # hardware) and dying costs the wearer the badge.
    try:
        warmed = _prewarm(prewarm_load)
    except MemoryError as error:
        warmed = 0
        gc.collect()
        print("GLYPH_MEM_PREWARM truncated %r free=%s" % (error, _free_heap()))
    if warmed:
        print("GLYPH_PREWARM asset=%s density=%s tiles=%d"
              % (name, density, warmed))
    # ONE LINE PER ENTRY LOAD, so retained growth is answerable from a serial
    # log or a browser console without a live probe into the module. Once per
    # keypress, never per frame, and `tile_bytes_held` is a multiply per
    # geometry rather than a walk -- so it is affordable on the badge and it is
    # what `playground/e2e/glyph-soak.spec.ts` reads instead of guessing.
    held = getattr(TARGET, "tile_bytes_held", None)
    print("GLYPH_MEM held=%s tiles=%d geoms=%d overflows=%s reliefs=%d "
          "degrades=%d free=%s"
          % (held() if held else -1,
             getattr(TARGET, "total_tiles", lambda: -1)(),
             len(getattr(TARGET, "geometries", lambda: ())()),
             getattr(TARGET, "overflows", -1),
             _mem_reliefs, _mem_degrades, _free_heap()))
    _attach_lights(now)
    _hud_dirty = True


def _present(now):
    """Advance and draw one frame. Returns True when the panel changed."""
    global _last_frame
    frame = _stream.frame_at(_playhead.elapsed(now), 1000)
    if frame == _last_frame:
        return False
    started = time.ticks_us()
    # ``frame=`` is what arms the renderer's changed-cell memo: playback is a
    # fixed loop, so after one pass each transition replays from a recorded
    # offset list instead of re-walking the whole grid.
    try:
        _renderer.draw(_stream.frame_view(frame), frame=frame)
    except MemoryError as error:
        # THE SMALL END OF THE SAME PRESSURE. A cold tile is 800 B at the dense
        # cell and 3,200 B at the coarse one, so this is nowhere near the
        # stream read -- but under a squeezed heap it is reachable, and it is on
        # the frame path, where a raise is a traceback modal and a reset.
        #
        # `reset()` because a draw that raised part-way left some cells painted
        # and `_previous` partly updated: the next frame must repaint the grid
        # rather than diff against a panel nobody described. `_last_frame` is
        # deliberately NOT advanced, so the clock simply lands the next frame
        # again. Each failure gives tiles back, so this converges instead of
        # spinning.
        _renderer.reset()
        gc.collect()
        # Mid-animation, so the live geometry is the one to protect: these are
        # the tiles the very next frame needs.
        _drop_tiles_except((_renderer.cell_w, _renderer.cell_h), "frame")
        print("GLYPH_MEM_FRAME frame=%d err=%r free=%s"
              % (frame, error, _free_heap()))
        return False
    if TIER == "batch":
        TARGET.flush()
    _last_frame = frame
    _drive_lights(frame, now)
    _metrics.note_frame(time.ticks_diff(time.ticks_us(), started))
    return True


_render = _present  # retained name; existing probes reference `_render`


def _stay_put(index, now, error):
    """The incoming entry would not load: put the outgoing one back on screen.

    THE MANDATE IS FIX-OVER-CRASH, so this is the floor: a keypress that cannot
    be honoured becomes a keypress that did nothing plus one line of HUD, never
    a traceback modal and a reset.

    It re-reads the outgoing entry because `_load_entry` freed it first (see the
    ordering note there). That read is the safest one this app ever makes: it
    asks for exactly the bytes that were resident one keypress ago, and it asks
    AFTER two collects, after the inactive geometry went, and after every
    remaining tile goes here -- so the heap is strictly larger than it was when
    those same bytes last fitted.

    Its tile cache went with the rest, so the reload re-warms it: 13 tiles for
    radar, 0.3 s on hardware at 23.07 ms a coarse tile. That is the price of the
    lever, and `_load_entry`'s prewarm guard is what stops it becoming a second
    failure -- under pressure the warm-up truncates and the frames rebuild
    lazily instead.

    If even that raises, the app genuinely cannot hold one stream and one grid
    and there is nothing left to give back. That case is left to raise rather
    than swallowed into a `_stream is None` state, which would fail on the very
    next frame with a stranger traceback than the honest one.
    """
    global _entry_index, _mem_degrades
    _mem_degrades += 1
    failed, failed_row = ENTRIES[_entry_index]
    print("GLYPH_MEM_FAIL entry=%s@%s err=%r free=%s"
          % (failed, failed_row[0], error, _free_heap()))
    _entry_index = index
    drop = getattr(TARGET, "drop_all_tiles", None)
    if drop is not None:
        print("GLYPH_MEM_DROP why=stay_put caches=all tiles=%d" % drop())
    gc.collect()
    _load_entry(now)
    name, row = _entry()
    _post_note("LOW MEM: KEPT %s %s" % (name.upper(), row[0]))
    print("GLYPH_MEM_KEPT entry=%s@%s free=%s"
          % (name, row[0], _free_heap()))


def _step_entry(step, now):
    global _entry_index
    _print_stats("loop", now)
    previous = _density()
    previous_index = _entry_index
    _entry_index = (_entry_index + step) % len(ENTRIES)
    if _density() != previous:
        print("GLYPH_DENSITY %s -> %s grid=%dx%d cell=%dx%d"
              % (previous, _density(), _grid()[0], _grid()[1],
                 SCREEN_W // _grid()[0], SCREEN_H // _grid()[1]))
    try:
        _load_entry(now)
    except MemoryError as error:
        # THE OWNER-REPRODUCED CRASH LANDED EXACTLY HERE (`_step_entry` ->
        # `_load_entry` -> `glyph_stream.load`). `_read_stream` has already
        # collected, dropped the inactive geometry and retried once by the time
        # this runs, so reaching it means the shortfall is not the incoming
        # entry's to fix.
        _stay_put(previous_index, now, error)


def _toggle_lights(now):
    global _lights_enabled, _hud_dirty
    if _lights_enabled:
        _lights_enabled = False
        _detach_lights()
    else:
        _lights_enabled = True
        _attach_lights(now)
    _hud_dirty = True
    print("GLYPH_LIGHTS enabled=%d" % (1 if _lights_enabled else 0))


def _change_speed(direction, now):
    global _hud_dirty
    if _playhead.step(direction, now):
        _metrics.reset(now)
        _hud_dirty = True
        print("GLYPH_SPEED scale_milli=%d" % _playhead.scale_milli)


def _commands_live(now):
    """False for ARM_MS after the app appears, so the launch press cannot act.

    THIS REPLACED A DRAIN THAT DRAINED NOTHING. The app used to read
    `badge.pressed()` once per button at startup under the comment "drain the
    launch edge" -- but `badge.pressed()` is a membership test that MUTATES
    NOTHING (firmware `badge.py`: `return button in _input.pressed`; the
    playground's compat layer is the same shape), so those were five discarded
    booleans and the launch press was still live on the app's first frame. The
    set is refreshed by `badge.poll()` at the END of the loop body, not by
    reading it. A time gate does not depend on that semantics at all, which is
    why Snake uses one and why `docs/badge-button-rules.md` names it the right
    pattern rather than the read.
    """
    return _armed_at is not None and time.ticks_diff(now, _armed_at) >= ARM_MS


def update():
    global _hud_dirty
    now = time.ticks_ms()
    _metrics.note_update()
    if _commands_live(now):
        if badge.pressed(BUTTON_A):
            _step_entry(-1, now)
        elif badge.pressed(BUTTON_C):
            _step_entry(1, now)
        elif badge.pressed(BUTTON_B):
            _toggle_lights(now)
        elif badge.pressed(BUTTON_UP):
            _change_speed(1, now)
        elif badge.pressed(BUTTON_DOWN):
            _change_speed(-1, now)

    drawn = _present(now)
    if _metrics.update(now, _slot_us()):
        _hud_dirty = True
    # An expired note has to be painted OVER, and on a paused viewer nothing
    # else would ask for that: `_present` returns False at speed 0 and the
    # metrics snapshot is only once a second.
    if _note_text is not None and time.ticks_diff(_note_until, now) <= 0:
        _expire_note()
        _hud_dirty = True
    if drawn or _hud_dirty:
        # A live note beats the metrics, and beats `HUD = False` as well: see
        # `_draw_note`. With no note and no HUD nothing draws chrome at all and
        # the animation owns every row.
        if _note_text is not None:
            _draw_note()
        elif HUD:
            _draw_hud()
        _hud_dirty = False


def play_sting(duration_ms=STING_DEFAULT_MS):
    """Play the current entry at 2x for `duration_ms`, leaving state untouched.

    THE WAKE SEAM, and it blocks on purpose: it presents its own frames because
    during a boot the managed loop has not started yet. The animation is the
    same `.gpa` the viewer is already holding, at `STING_SCALE_MILLI` -- a
    sting was never a second capture. `STING_ON_OPEN_MS` documents who can
    reach this and why it is not simply "the supervisor calls it".

    Returns the number of frames presented. The playhead, the metrics and the
    lights are restored, so a sting followed by the ordinary viewer is
    indistinguishable from the viewer alone.
    """
    if duration_ms < STING_MIN_MS or duration_ms > STING_MAX_MS:
        raise ValueError(
            "sting duration %d ms is outside %d..%d"
            % (duration_ms, STING_MIN_MS, STING_MAX_MS)
        )
    global _last_frame
    started = time.ticks_ms()
    saved_frame = _last_frame
    frames = 0
    elapsed = 0
    print(
        "GLYPH_STING asset=%s density=%s ms=%d scale_milli=%d"
        % (_stream.technique, _density(), duration_ms, STING_SCALE_MILLI)
    )
    while True:
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, started)
        if elapsed >= duration_ms:
            break
        frame = _stream.frame_at(elapsed, STING_SCALE_MILLI)
        if frame != _last_frame:
            _renderer.draw(_stream.frame_view(frame), frame=frame)
            if TIER == "batch":
                TARGET.flush()
            _last_frame = frame
            _drive_lights(frame, now)
            frames += 1
        display.update()
    print("GLYPH_STING_DONE frames=%d elapsed_ms=%d" % (frames, elapsed))
    # The sting left the panel mid-loop and the viewer's clock has to start from
    # a known phase, so re-anchor rather than letting the first animated frame
    # look like a jump.
    _last_frame = saved_frame
    _playhead.reset(time.ticks_ms())
    _metrics.reset(time.ticks_ms())
    return frames


_load_entry(time.ticks_ms(), chunked=_load.chunked, prewarm_load=_load)
_load.step("-- %s.gpa + %dx%d bank" % (
    _entry()[0], _renderer.mask_width, _renderer.mask_height))
_load.end()

# The managed loop must not clear between diff-drawn frames. Restore the stock
# policy on exit so the launcher and next app never inherit this ownership.
#
# THE CLEAR HAPPENS AFTER `_load.end()`, and the order is load-bearing: it used
# to sit above the asset load, and with the asset read now chunked into eight
# presented slices that would have wiped the loading screen's window out from
# under its own remaining frames.
_AUTO_CLEAR = color.rgb(0, 0, 0)
screen.pen = _AUTO_CLEAR
screen.clear()
badge.default_clear = None
# The clear wiped the framebuffer the diff-draw tracks, so the next frame must
# repaint every cell rather than diff against pixels that are no longer there.
_renderer.reset()
_last_frame = -1

# A boot that is a WAKE plays the sting before the viewer takes over. This runs
# after the clear and the renderer reset, so the sting owns a known framebuffer,
# and before the arm window opens, so the press that woke the badge cannot step
# an entry underneath it.
if STING_ON_OPEN_MS:
    play_sting(STING_ON_OPEN_MS)

# The app is on screen NOW, so the dead-key window starts here rather than on
# the first update: measuring it from the first update would make the window
# depend on how long the loop took to come round, which is the opposite of what
# a fixed 90 ms is for.
_armed_at = time.ticks_ms()


def on_exit():
    _print_stats("exit", time.ticks_ms())
    _detach_lights()
    badge.caselights(0)
    badge.default_clear = _AUTO_CLEAR


run(update)
