"""FIRST WAKE -- the opening sequence the badge plays on a RESET, and only then.

OWNER DESIGN (2026-08-23): *"we need a first-wake animation, which happens on
RESET: the badge plays SIGNAL-RIPPLE at LORES 2x density, ONCE, start to finish.
If you hit HOME you go home -- NO animation between apps or on home (the loading
animation already covers that). The animation might change but let's see what
this looks like."*

THEN HE SAW IT ON GLASS (2026-08-24): *"looks awesome -- what would be the
implications of making it hires?"*, having separately ruled that 2xHI glyphs
*"look way better than 2x lo"*.  So the panel is now a one-word constant,
`RIPPLE_MODE`, and it ships at `"hires"`.  Its own section below carries what
changes, what it costs and what it does not cost.

AND THEN HE ASKED FOR A SECOND ACT (2026-08-24): keep signal-ripple as the first
animation, then go STRAIGHT into terminal-marquee -- both 32x12 at HIRES, both
`held=1`, the ruled-final pacing.  So this module plays an ORDERED TUPLE now
(`RIPPLE_SEQUENCE`), not one deck, and the same request carried a second half:
**on this first-wake path ONLY, the generic loading screen must not appear -- the
sequence ends on home directly.** That half is not implemented here; it lives in
`launcher/menu/ui.py`, which is `loading.begin()`'s caller, and §THE LOADING
SCREEN below says why it cannot live anywhere else.

WHAT A SEQUENCE COSTS THAT ONE DECK DID NOT.  Three things, and each has a
section: the union tile cache (§THE SHARED TARGET), the free-then-load ordering
between decks (§ONE DECK AT A TIME), and the wall time -- **~7.0 s on glass at
the shipped settings, which is AT the owner's stated limit and not under it**
(§THE SEQUENCE).

AND THEN THE CASE LIGHTS (owner ruling, 2026-08-24): the four rear PWM channels
follow the animation frame by frame and are handed back DARK.  §THE CASE LIGHTS
below is the whole of it, including the thing nobody expected -- **the mapping is
7.5-7.8 ms per frame, not free**, because the viewer's per-frame-index scan memo
can never pay off in a one-shot pass.  It is not the PWM write: it is
QUANTISATION -- 7.5 ms of scan on a frame already spending 2-3 quanta buys a
whole extra 11.4 ms tick, so the model puts the sequence **+1,577 ms (+24%)**
dearer, i.e. **~9.0-9.2 s on glass** against a MEASURED 7.39-7.46 s without them.
**That is 2.0-2.2 s over the ~7 s the owner said he would judge against -- and
the lights are not the whole reason, because the lights-free sequence measures
over it too** (§THE SEQUENCE).  `LIGHT_EVERY = 2` is the one-word lever (~8.1-8.2
s, and the same number of writes) and
`python3 launcher/host/ripple_cost.py --light-every N` prices every arm.

WHAT THIS REPLACES.  The supervisor's `_draw_intro` -- six primitives behind a
10,000 ms unskippable gate (`supervisor/badge/supervisor/runtime.py:461`).  That
intro never shipped: the supervisor is boot-ownership decision D3 and it is
PARKED (`apps-roster.json` `production.excluded`, `supervisor/README.md`), so
the badge in the owner's hand has no first-wake ceremony at all.  The launcher
is the boot owner, so the ceremony belongs here.

WHERE THIS RUNS, AND WHY IT IS THE ONLY PLACE IT CAN.  The shipped chain is
frozen `main.py` -> `import badgeware` (which constructs the ST7789, which is
why the panel is black) -> `/system/main.py` -> `launch("/system/apps/menu")` ->
the menu's module body -> `import ui`.  Everything before that first statement
of `ui.py` belongs to the firmware: no Python of ours runs there and there is no
hook.  So `ui.py`'s module body is the earliest project-owned instruction on the
badge, and this module is called from the top of it -- ahead of
`loading.begin()`, which owns frame 0 of every OTHER boot.

THE POLICY IS THE WAKE REGISTER, AND IT IS THE OWNER'S RULE EXACTLY.  Leaving an
app is `machine.reset()`, which the RP2350 serves through the watchdog, so every
HOME exit reads `WAKE_WATCHDOG` 242 and gets NO ripple -- which is the "if you
hit HOME you go home" half, enforced by the silicon rather than by a flag we
have to remember to clear.  A deliberate RESET tap reads 241 and a cold attach
reads 255, and those two are the ceremony.  The table and its device provenance
are `supervisor/badge/supervisor/wake.py`; `INTRO_REASONS` below is that
module's tuple, and `launcher/tests/test_first_wake.py` fails if the two ever
disagree.

WHY THE CONSTANTS ARE COPIED RATHER THAN IMPORTED.  `scripts/sync_ui.py` says it
best: each app installs to its own directory and only that directory reaches
`sys.path`, so importing across apps makes one app refuse to start when another
is missing.  The supervisor is not installed at all, so importing its classifier
here would be a dependency on a parked app.  Three integers and a `wake_reason`
read are cheaper than that, and the test is the guard.

WHY THE PLAYER IS INSIDE `play()` AND NOT AT MODULE SCOPE.  `glyph_render` is
30 KB of source.  A HOME exit must not pay for it, and MicroPython does not
compile what it does not import -- the same reason `shared/loading.py` keeps its
painter in `loading_sql.py`.  So this module's own body is constants, and every
import that costs anything happens after the gate has already said yes.

NOTHING HERE MAY RAISE.  `launch()` turns an exception into a modal that
`machine.reset()`s, and on the LAUNCHER that reset boots straight back into the
same failing code: the USB-recovery loop `launcher/menu/ui.py` guards its
`import loading` against.  So `play()` catches everything, returns a reason
string, and a badge whose glyph app is missing boots exactly as it does today.

THE LOADING SCREEN, AND WHY ITS SUPPRESSION IS NOT IN THIS FILE.  The owner kept
the generic loading screen everywhere else on purpose -- *"that generic loading
screen that appears between every screen -- I love it, we got to keep that
there"* -- and asked for it gone on this one path only.  `shared/loading.py` is
one of the SEVEN FILES FROZEN BY SHA-256 in `kb/tests/test_kb_sameness.py`
(`ControlTests` pins every byte `kbgrid` installs, and `loading.py` is one of
them), so the suppression may not be a flag inside it.  It is also not
implementable here: `loading.begin()` paints its window and PRESENTS inside
`_Loader.__init__`, so by the time anything this module returns could be read,
frame 0 is already on the panel.  The only seam left is the CALL, and that is
`ui.py`'s -- which is where it lives: `ui.py` reads this module's return value
and simply does not call `begin()` when the sequence painted.  `play()`'s
contract exists for that reader, which is why it returns a FRAME COUNT and not a
boolean.
"""

import gc
import sys
import time


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------

# `modules/c/powman/bindings.c:18-30` @ `c4abbcd` (Badgeware v3.0.2), measured
# on the reference badge on 2026-08-20. NEVER `badge.woken_by_reset()`:
# it compares the register to 255, which is WAKE_UNKNOWN and not WAKE_RESET, so
# it is False on the deliberate reset it names and True on a cold attach.
# `supervisor/badge/supervisor/wake.py` exists partly so nothing reaches for it.
WAKE_RESET = 0xF1
WAKE_WATCHDOG = 0xF2
WAKE_UNKNOWN = 0xFF

#: The whole policy, in one tuple. Mirrors `wake.INTRO_REASONS`, pinned by test.
INTRO_REASONS = (WAKE_RESET, WAKE_UNKNOWN)


# ---------------------------------------------------------------------------
# The animation
# ---------------------------------------------------------------------------

# THE DECKS LIVE IN THE GLYPH APP AND ARE READ FROM THERE, NOT VENDORED.  The
# dense `signal-ripple.gpa` is 98,368 B, `terminal-marquee.gpa` 92,224 B, the
# 5x10 mask bank 5,100 B, the classic bank 20,400 B and the LUT 10,240 B:
# vendoring them would be **more than twice** a 98,385-byte launcher payload on a
# 1 MB volume to buy a decoration, and the second deck doubled that argument
# rather than weakening it.  `glyph` is on all three `apps-roster` lists including
# `production`, and `shared/glyph_tile.py` already established reading one app's
# payload from another rather than copying 4.7 MB of it.
#
# THE TRADE IS EXPLICIT: no glyph app, no ceremony, and the launcher boots
# unchanged.  That is a SOFT dependency, unlike the tiles' hard one, because the
# launcher is the app whose failure needs a cable.  It is also PER STREAM: a badge
# whose asset profile carries signal-ripple but not terminal-marquee plays the
# first act and stops, which is a shorter ceremony and not a failure.
# `test_first_wake.py::AssetTests` asserts every path below is a file that
# EXISTS in the repository -- the sticker lesson from `AGENTS.md`, where a total
# fallback turned a deleted asset into a picture instead of an error.
GLYPH_ROOT = "/system/apps/glyph"

#: THE SEQUENCE, IN ORDER. One pass of each, back to back, no gap, no loop.
#
# OWNER DESIGN 2026-08-24: signal-ripple stays first, terminal-marquee follows
# it, and the badge goes straight to home from the end of the second.
#
# THE ORDER IS NOT ARBITRARY AND THE JOIN IS WHY. signal-ripple ENDS almost
# empty -- 23 of 384 cells lit on frame 127, a small cluster of dim digits
# centre-panel -- and terminal-marquee BEGINS almost full: 333 of 384, a whole
# terminal with an inverse status band across the middle. So the cut runs
# near-black -> full, which reads as the signal dying out and the terminal waking
# up. Reversed, the same two frames would slam a full terminal into a near-empty
# panel, which is the same information in the order that reads as a dropout.
#
# NO DARK FRAME IS INSERTED, and that was a decision rather than an omission.
# `launcher/host/ripple_cost.py --join` measures the cut and says it: at 6% lit,
# **signal-ripple's own last frame IS the dark frame**, so inserting one would
# spend a VSYNC quantum to add black the deck already gives. If a third stream
# ever joins this tuple, run `--join` again before trusting that -- the verdict
# is a property of the two decks that meet, not of the feature.
#
# A STREAM'S GRID IS ALLOWED TO DIFFER from its neighbours' and the player
# handles it (a new cell geometry re-reads the bank and gets its own tile cache,
# which is `_GeometryCaches`' whole job) -- but both of these are 32x12, so the
# shipped sequence never exercises that path.
RIPPLE_SEQUENCE = ("signal-ripple", "terminal-marquee")

# 5x10 records for a cell finer than the classic 10x20, 10x20 otherwise. Same
# rule as `glyph/badge/glyph/__init__.py:431` `_bank_choice`, restated rather
# than imported because the module that holds it runs an app at import time.
#
# BOTH BANKS HOLD THE SAME 102 RECORDS of the same 102 glyphs, which is what
# makes `RIPPLE_MODE` a one-word change rather than a re-authoring: 20,400 B at
# 200 B a record and 5,100 B at 50 B, so every id either deck names resolves in
# either bank. (`glyph_render` RAISES on an id past the bank, so this is a
# correctness property and not a nicety.)
#
# ⚠ AND THE SEQUENCE SPENT ALMOST ALL OF THAT MARGIN. This comment said "the
# dense deck's highest glyph id is 51" and that was signal-ripple's alone.
# **terminal-marquee reaches id 101, and the banks hold records 0..101** -- so
# the sequence uses the LAST RECORD IN THE BANK and there is exactly one id of
# slack left, not fifty. Anything that trims either `.pfb` now raises inside
# `launch()` on the launcher, which is the failure that needs a cable.
# `HeadroomTests.test_every_glyph_the_sequence_names_exists_in_the_classic_bank`
# is the guard, and it walks the union rather than one deck.
CLASSIC_BANK = ("assets/glyph-masks.pfb", 10, 20)
DENSE_5X10_BANK = ("assets2x/glyph-masks-2x.pfb", 5, 10)
LUT_NAME = "assets/glyph-lut.bin"
LUT_BYTES = 10240

#: WHICH PANEL THE RIPPLE PLAYS ON. "hires" or "lores", and it is the owner's A/B.
#
# SHIPS "hires" (2026-08-24), because he asked for it after seeing the LORES one
# and because he has already ruled the dense deck reads better at HIRES than at
# LORES on the glyph viewer. "lores" is EXACTLY the shipped behaviour of
# 2026-08-23 -- not merely equivalent: that arm makes NO `badge.mode` call at
# all, so flipping this word back cannot leave a mode call behind as a souvenir.
#
# WHAT ACTUALLY CHANGES, and it is one thing: the CELL. 32x12 over 160x120 is a
# 5x10 cell, the only configuration in the repository that reaches the natively
# authored 5x10 mask records; 32x12 over 320x240 is a 10x20 cell, which is the
# CLASSIC bank at its own authored size. Same deck, same 128 frames, same grid,
# same 98,368-byte read. `bank_for` picks the bank off the PANEL and never off
# this constant, which is the safety property that makes the whole variant total:
# a badge whose `badge.mode` refuses stays at 160x120 and plays the LORES ripple
# correctly rather than drawing 10x20 masks into 5x10 cells.
#
# WHAT IT COSTS. Not the present: [DEVICE] the v3.0.2 repin measured the VSYNC
# floor at 11.426 ms at 320x240 against 11.433 at 160x120 -- 87.52 updates/s
# against 87.46 -- so four times the pixels are FREE at the panel and every HIRES
# cost is compositor cost. Anybody quoting 14-17 ms for a HIRES present is
# quoting nothing. What it costs is:
#   * the tile cache, 21,000 B -> 84,000 B (105 keys at 200 B against 800 B,
#     device-confirmed per-tile sizes), which is why the heap headroom below is
#     mode-dependent;
#   * ~+500 ms on the pass, of which ~400 ms is 105 COLD TILE builds at 5.06 ms
#     each instead of ~1.27 -- and 48 of those land on frame 0, so the opening
#     frame is a ~300 ms hitch against ~114 ms at LORES. That hitch is the one
#     thing to watch for on glass that the LORES pass does not have.
#   * nothing else: the diff walk is 384 interpreted iterations at either panel
#     ("resolution pays where the CELL COUNT rises, never where the cell merely
#     grows" -- `docs/design/glyph-knowledge.md`), and a 4x-area blit costs ~2x.
# `launcher/host/ripple_cost.py` is that arithmetic, frame by frame, fitted to
# the one device reading this feature has. Read its docstring before quoting a
# duration: the DELTA between the panels is the trustworthy half.
RIPPLE_MODE = "hires"

#: Panel presents each stream frame is held for. THE SPEED KNOB.
#
# WHAT IT COSTS IN WALL TIME, and this is a READING now, not arithmetic.
# [DEVICE] the reference badge, 2026-08-24: `FIRSTWAKE_DONE frames=128
# presents=256 ms=4581 note=ok` at LORES with `held=2`. **4,581 ms, where every
# document promised 2,926.** The old prediction counted presents and ignored the
# renderer; per frame the truth is 35.79 ms = 3.13 quanta, not the 2 that
# `held=2` implies, because `glyph_render.draw` runs BEFORE the presents rather
# than inside their VSYNC waits. The corrected model is
# `frames * (ceil(draw / quantum) + held - 1) * quantum`.
#
# So the knob is dearer at every setting than this comment used to say, and
# `launcher/host/ripple_cost.py` prices all eight combinations off the real deck:
#
#             held=1     held=2     held=3     held=4
#   LORES     3,121      4,585*     6,048      7,511      ms  (*the reading)
#   HIRES     3,622      5,085      6,547      8,010      ms
#
# [HOST] except the starred one. **The HIRES pass at held=1 is ~1.0 s SHORTER
# than the LORES pass the owner has already seen at held=2**, which is the answer
# if he judges 4.58 s long: the honest direction for this constant is DOWN, and
# at HIRES it buys the better-looking cell for less of his time.
#
# WHY A PRESENT COUNT AND NOT A CLOCK, since the knob's unit is the question a
# reader asks first. It is the same decision `shared/loading.py` argues at length
# for its spinner: a clock-driven target REPEATS a frame when presents are dense
# and LURCHES when they are sparse, and both read as stutter. Here it is also the
# only design the browser lane can host at all --
# `playground/src/worker/virtual-clock.ts` advances virtual time by 1 us per
# clock READ, so a `while elapsed < 52` wait costs 52,000 reads per frame and
# 6.7 M for a pass. A present count costs none.
#
# AUTHORED FIDELITY, for the record: signal-ripple's authored slot is 52.5 ms
# (128 frames over a 6,720 ms wall period), so the shipped pass runs at 1.47x
# authored speed at LORES and 1.32x at HIRES. Nothing in the deck cares -- the
# player walks frames, not clocks -- but a 1x pass is 6.7 s and no setting of
# this constant reaches it.
#
# RULED (Sam, 2026-08-24): held=1 ships. Device readings, same session, forced
# via play(reason=241): HIRES held=2 = 5,221 ms; HIRES held=1 = 3,785 ms --
# crisper AND ~0.8 s shorter than the LORES pass he judged. The A/B moved two
# variables on purpose: the owner had already seen both slow arms.
#
# ⚠⚠ THE SEQUENCE PUT THIS CONSTANT AT ITS FLOOR AND SPENT THE MARGIN. See
# §THE SEQUENCE below: two decks at held=1 is ~7.0 s on glass, which is AT the
# limit the owner named and not under it. There is no room left in this knob --
# 1 is the floor, and `held=0` is clamped to 1 by `play()`. If he judges the
# sequence long, the next levers are (a) drop terminal-marquee back out, (b)
# trim a deck's frame count host-side, (c) `SKIPPABLE = True` so a face key
# ends it. None of the three is a one-word change to THIS constant, which is
# what changed on 2026-08-24 and is the reason it is flagged here.
PRESENTS_PER_FRAME = 1

#: HOW LONG THE WHOLE SEQUENCE TAKES. Read this before quoting a duration.
#
# ONE PASS OF EACH DECK, AT THE SHIPPED SETTINGS (HIRES, held=1), from
# `launcher/host/ripple_cost.py` walking both real files:
#
#                      frames   [HOST] ms   frame 0
#   signal-ripple        128       3,622     297 ms  (48 cold tiles)
#   terminal-marquee     120       3,074     263 ms  (41 cold tiles, 21 warm
#                                                     already from act one)
#   ------------------------------------------------
#   the sequence         248       6,696
#
# **AND ON GLASS IT IS 7.39-7.46 s -- MEASURED, AND OVER THE LIMIT RATHER THAN AT
# IT.** [DEVICE] the reference badge, 2026-08-24, three observations (two natural
# resets and one forced `play(reason=241)`, all `acts=2 note=ok`, all
# `presents == frames == 248`), from the day-session report §3:
#
#   act 1 signal-ripple     3,760 / 3,772 / 3,771 ms   (stable to 12 ms)
#   act 2 terminal-marquee  3,541 / 3,469 / 3,460 ms   (81 ms; act 2 cold first)
#   total                   7,457 / 7,397 / 7,387 ms
#
# So **the model runs 10.3-11.4% UNDER** (6,696 against 7,387-7,457) and the
# sequence is **387-457 ms OVER the owner's ~7 s all by itself.** This comment
# said "~6,997 ms ... ON it with 3 ms of modelled margin" until 2026-08-24; that
# figure was an extrapolation from a SINGLE-ACT reading (signal-ripple alone,
# 3,785 measured against 3,622 modelled, x1.045) and the numbers above are the
# reading of the actual arm. Do not quote 6,997 again.
#
# ⚠⚠⚠ AND ALL OF THAT IS THE LIGHTS-FREE SEQUENCE. Since the 2026-08-24 case
# lights ruling the shipped pass also pays 7.5-7.8 ms per frame of light mapping:
# +1,577 ms of modelled time, i.e. **~9.0-9.2 s on glass**, 2.0-2.2 s over the
# limit. §THE CASE LIGHTS holds the derivation, the per-arm table and the
# one-word lever; the 3,622/3,074 figures here stay because they are what
# `test_ripple_cost.py` re-derives and what the lights-off model still says.
#
# AT LORES the same sequence is 5,945 ms [HOST] (3,121 + 2,824), so the panel
# choice costs +750 ms across the pair -- which is the trustworthy half of the
# model, since every term it gets wrong is a term both panels pay.
#
# AUTHORED FIDELITY, for the record: signal-ripple's slot is 52.5 ms and
# terminal-marquee's is 80.0 ms (120 frames over 9,600 ms), so at held=1 the
# sequence runs at 1.86x and 3.12x authored speed. terminal-marquee is the one
# being hurried, and it is being hurried three times over -- worth knowing if the
# marquee reads as too fast to follow on glass, because the fix there is NOT this
# constant (which would slow both) but a per-stream hold, which does not exist.
#
# THE FIGURES ABOVE ARE PINNED BY TEST, not left to rot in a comment:
# `launcher/tests/test_ripple_cost.py` re-runs the model and fails if any of
# them moves. This repository has shipped four wrong figures in one document
# before; a comment nobody re-derives is how.

#: Does a face button end the pass early? SHIPS FALSE, and it is a ruling.
#
# The owner said "ONCE, start to finish", so unskippable is what his words
# describe and what ships.  It is not the old defect either: the 10,000 ms gate
# §9.3 of `docs/badge-button-rules.md` calls the one deliberate invariant breach
# is replaced by ~2.9 s, and `badge.poll()` runs on every present below, so the
# input layer stays live even while presses do nothing (I4, and the lesson of
# the sting's undisclosed 4,090 ms input-dead window).  Flip this to True and a
# press on any of the five face keys ends the pass; nothing else changes.
SKIPPABLE = False

#: Free heap a dense stream read needs before it is attempted, over the file.
#
# 98,368 B WANTED CONTIGUOUS IS THE BIGGEST RISK IN THIS FEATURE.  On 2026-08-22
# the owner's badge raised `MemoryError: memory allocation failed, allocating
# 66816 bytes` reading a 73,792 B dense stream in the glyph app
# (`docs/design/glyph-knowledge.md` §4.2): the number in the traceback was the
# FREE HEAP, and fragmentation rather than the total was what killed the read.
# This read happens at the emptiest moment the launcher ever has -- a fresh
# interpreter, before `import wallpaper` and before `Apps()` -- which is the
# best case available, and the guard below makes a short heap a skipped ripple
# instead of a modal.  `STREAM_HEADROOM_BYTES` is glyph's own name and value.
#
# WHAT THE HEADROOM IS ACTUALLY FOR, since the stream's own size is checked
# separately: the PEAK is the stream plus everything the pass allocates on top of
# it.  **RE-DERIVED FOR THE SEQUENCE, 2026-08-24, and both numbers moved: the
# tile cache is now the UNION of the two decks' keys, because one target spans
# both of them.**
#
#              bank   +  LUT   +  union tiles + memo   =  peak -> the next 8 KB
#   LORES      5,100    10,240      32,000     32,768     80,108 ->  81,920
#   HIRES     20,400    10,240     128,000     32,768    191,408 -> 196,608
#
# * TILES: `cell_w * cell_h * 4` per distinct key, 200 B at a 5x10 cell and 800 B
#   at 10x20 -- both confirmed against the device's own `GLYPH_MEM held=` figures
#   (2,600 B and 10,400 B for radar's 13 tiles). **THE UNION IS 160 KEYS**:
#   signal-ripple names 105 and terminal-marquee 76, they share 21, and one
#   `BlitTarget` outliving both renderers is what makes the shared 21 free
#   (§THE SHARED TARGET in `play()`). 105 was the figure until the second deck
#   joined; before that it was 93, which was a third deck's count entirely.
# * MEMO: `glyph_render` keeps a changed-cell memo, `DIRTY_BUDGET_CELLS` (16,384)
#   cells at 2 bytes = 32,768 B, and this counts it ONCE rather than per stream --
#   correct, because a renderer is built per stream and the previous one's memo is
#   released before the next allocates (§ONE DECK AT A TIME). Both decks fill it:
#   7,111 changed cells over signal-ripple's 128 frames and 6,780 over
#   terminal-marquee's 120, so the budget caps each rather than the deck. A
#   ONE-SHOT can never read that memo back (it only pays off on a second visit to
#   a frame index), so it is 32 KB and some time spent for nothing. Passing
#   `frame=None` to `draw` would reclaim both; it is deliberately NOT done here,
#   because it would change the arm the device readings describe.
# * BANK: the classic bank is 20,400 B against the dense 5,100. Read ONCE for the
#   whole sequence now, not once per deck, because it is a property of the panel.
# * NOT COUNTED, AND THIS IS THE ORDERING THAT MAKES IT SAFE: the second stream's
#   92,224 B. The decks are never both resident -- §ONE DECK AT A TIME frees each
#   before loading the next -- so the buffer term is `max(98,368, 92,224)` and the
#   `need` the guard adds this headroom to is the LARGEST deck, not the sum.
#   A design that held both would want 190,592 B of it instead.
#
# `glyph_render.MAX_TILE_BYTES` caps the cache at 512 KB, still over twice the
# HIRES union, so it cannot bound this -- the check below is the only thing that
# does.  [HOST] arithmetic; no device has measured the peak.  What a device HAS
# measured (2026-08-24) is that it is nowhere near firing: free heap after
# `gc.collect()` was 8,215,840 B, with `bytearray(98368)` and `bytearray(131136)`
# both allocated directly to prove it against fragmentation rather than inferring
# it.  The guard stays because it costs one comparison and turns a modal into a
# skipped ceremony; it should stop being called this feature's biggest risk.
STREAM_HEADROOM_BYTES = 81920
STREAM_HEADROOM_BYTES_HIRES = 196608


# ---------------------------------------------------------------------------
# The case lights
# ---------------------------------------------------------------------------

#: Do the four rear case lights follow the animation? SHIPS TRUE. IT IS A RULING.
#
# OWNER RULING (Sam, 2026-08-24): the opening sequence drives the CASELIGHTS in
# sync with the animation -- the case glows and pulses with the ripple, flickers
# with the terminal, and hands the lights back DARK to the launcher.
#
# NOTHING HERE IS A NEW LIGHT DESIGN. The mapping is the glyph app's own, read
# from the glyph app's own modules through the same soft dependency that already
# gets the decks: `glyph_rich_lights.RichGlyphLightSync` in `mode="motion"`, the
# `light_calibration_2x` per-technique scales (both decks are the DENSE 32x12
# deck, which is the arm that table exists for), and `wave_lights`' physical
# zone->channel map including the badge's own `/glyph-review.json` calibration if
# the owner has run the identification card. `glyph/badge/glyph/__init__.py`
# `_attach_lights_now` is the source; `LightsTests` pins every one of those
# choices against it so a drift on either side lands red.
#
# WHICH KIND EACH ACT GETS, since the viewer picks per technique: the viewer's
# rule is `wave_lights.lifecycle_for(...) is not None` -> the wave choreography,
# everything else -> the rich motion mapper. `lifecycle_for` returns non-None for
# the `wave` technique ALONE, so **both shipped acts are `motion`** --
# signal-ripple at luma/motion/weight (23, 8, 0.45) and terminal-marquee at
# (47, 1, 0.45). A stream that wanted the wave choreography goes DARK for its act
# with `kind=wave` rather than being driven by the wrong mapper; this player does
# not carry that branch, and `LightsTests` asserts neither shipped act needs it.
#
# `False` IS A TRUE REVERT, in the same sense `RIPPLE_MODE = "lores"` is: this arm
# makes NO `badge.caselights` call at ALL, so flipping the word back cannot leave
# a PWM write behind as a souvenir. It also costs nothing to read -- one test per
# frame -- which is why the knob is a constant and not a build flag.
LIGHTS = True

#: Feed the sync every Nth stream frame. THE COST KNOB, and it is a real one.
#
# ⚠ THE SCAN IS NOT FREE AND THE PWM WRITE IS NOT THE COST. A `badge.caselights`
# call is four `duty_u16` writes; what costs is `quadrant_luminance`, which walks
# all 384 packed cells in interpreted Python doing ~18 operations each against
# the renderer's own diff walk's ~6. Measured [HOST] as a RATIO against that walk
# -- one process, real decks, the anchor re-timed beside every arm, best-of-N --
# because the device has a figure for the walk (2.790 ms per 384-cell grid) and
# none for this. A whole `RichGlyphLightSync.update` is **2.70x** the walk on
# signal-ripple and **2.80x** on terminal-marquee, so the scaled cost is
# **~7.5 and ~7.8 ms per frame**: two thirds of a VSYNC quantum, on a sequence
# whose frames already sit at 2-3 quanta. It is the single most expensive thing
# this feature added and the duration model carries it as its own term.
# `python3 launcher/host/ripple_cost.py --measure-lights` re-derives it and
# reports the drift; the ratios are two significant figures on purpose (the
# observed band is 2.50-3.00, and the spread tracks how busy the host is) and
# `LIGHT_RATIO`'s comment says why -- including that the VERDICT is insensitive
# to the whole band: ~8.9-9.3 s at any ratio the probe has ever reported.
#
# WHY A LOOPING VIEWER NEVER NOTICED. `RichGlyphLightSync` memoises the scan per
# FRAME INDEX (`_frame_valid`), so the glyph viewer pays 384 cells once per frame
# of the deck and then reads four bytes on every revolution afterwards. **A
# ONE-SHOT PASS NEVER TAKES A SECOND LAP**, so every frame is a cold scan. The
# same asymmetry the changed-cell memo has (see §STREAM_HEADROOM_BYTES), for the
# same reason, in a module nobody suspected of it.
# `test_ripple_cost.LightsCostTests.test_the_scan_is_paid_on_every_frame_of_a_one_shot_pass`
# is that fact as an assertion: `frame_scans` equals the frame count and
# `frame_cache_hits` is zero, across both decks.
#
# WHAT `LIGHT_EVERY = 2` WOULD BUY, measured the same way: **4.05 and 4.19 ms per
# frame**, roughly half, for essentially the same NUMBER of writes (61 against 62
# on signal-ripple, 59 against 58 on terminal-marquee) -- because the sync
# already rate-limits itself to `LIGHT_INTERVAL_MS`, so feeding it faster than
# 20 Hz pays for scans it then discards. The VALUES differ though (8 of 62 level
# tuples in common), because the motion accent becomes a two-frame delta and the
# attack/release lands on different steps. **That is a perceptual change and no
# eye has judged it**, so 1 ships -- the arm that is byte-for-byte the viewer's
# own -- and this constant is the lever if the owner judges the sequence long.
# `every=3` is ~2.6/2.8 ms and `every=4` ~2.05/2.10, but both drop the write
# count visibly (42 and 31 against 62), so they are not nearly-free the way 2 is.
#
# ⚠⚠ WHAT EACH ARM DOES TO THE WALL TIME, and it is why this constant is the
# first thing to reach for. `launcher/host/ripple_cost.py --light-every N`,
# HIRES held=1, corrected against the one [DEVICE] reading:
#
#   lights OFF     7.39-7.46 s   [DEVICE], the pre-ruling build. ALREADY OVER.
#   every=1        ~9.0-9.2 s    +1,577 ms modelled (+24%)   <- SHIPS
#   every=2        ~8.1-8.2 s    +708 ms   (+11%)
#   every=3        ~7.8-7.9 s    +400 ms   (+6%)
#
# The lights-off row is a MEASUREMENT; the other three are that measurement plus
# the model's lights term, bracketed two ways because the device's 691-761 ms of
# unmodelled cost is either a per-frame residual (which the term would scale) or
# a fixed overhead (which it would not), and no reading exists with the lights
# on. `--light-every N` prints both brackets.
#
# **EVERY ARM IS OVER THE OWNER'S ~7 s, AND SO IS THE ARM WITH NO LIGHTS IN IT
# AT ALL** -- so the lights are not the only thing that would have to give if he
# holds that line, and saying "turn the knob" would misdescribe the decision.
# The ruling that put the lights in did not speak to duration, so the shipped arm
# is the FAITHFUL one and the number goes to him rather than being quietly traded
# away: `FIRSTWAKE_SEG` and `FIRSTWAKE_LIGHTS` print the real per-act figures on
# the next reset, and THAT reading, not this arithmetic, is what he should judge.
LIGHT_EVERY = 1

#: The viewer's own light settings, verbatim from `glyph/badge/glyph/__init__.py`
#: lines 343-348. Copied rather than imported for the reason the whole module
#: copies things: importing the glyph APP entry runs an app at import time.
#: `LightsTests.test_the_settings_are_the_viewers_own` reads them back out of
#: that file's source and fails on a drift.
LIGHT_CAP = 1.0
LIGHT_STATES = 40
LIGHT_DUTY_BUDGET = 1.0  # full-range; no rolling dimmer, as the viewer ships
LIGHT_INTERVAL_MS = 50
LIGHT_ATTACK_MS = 50
LIGHT_RELEASE_MS = 300


def wants_ripple(reason):
    """True when this boot plays the ripple. PURE, and the whole policy.

    Anything unrecognised is a RESUME, not a ceremony: a value this code has
    never heard of is likelier a future reboot cause than a wearer asking for
    the animation, and replaying it on every trip home is the failure being
    designed out. Mirrors `wake.wants_intro`.
    """
    return reason in INTRO_REASONS


def read_reason(source=None):
    """Read the wake register once. TOTAL: an unreadable register is UNKNOWN.

    `source` defaults to the Badgeware `badge` builtin and is a parameter so the
    host lane can drive every row of the table without a device. An unreadable
    register genuinely IS "this boot cannot be identified", which is 255 -- and
    255 plays the ripple, so the failure mode is a ceremony rather than a badge
    that never shows one.
    """
    try:
        if source is None:
            source = badge  # noqa: F821 -- the Badgeware builtin
        return int(source.wake_reason())
    except Exception:  # noqa: BLE001 -- see the module docstring
        return WAKE_UNKNOWN


def bank_for(cell_w, cell_h):
    """Which mask bank a cell this size wants. PURE. See `_bank_choice`.

    Reads the PANEL, never `RIPPLE_MODE`. That is what makes the HIRES variant
    total: if `badge.mode` is missing or refuses, the panel is still 160x120, the
    cell is still 5x10, and the pass plays the LORES ripple correctly instead of
    drawing 10x20 masks into 5x10 cells.
    """
    if cell_w < CLASSIC_BANK[1] or cell_h < CLASSIC_BANK[2]:
        return DENSE_5X10_BANK
    return CLASSIC_BANK


def headroom_for(mode=None):
    """Free heap the pass wants OVER the stream file, for a panel. PURE.

    Mode-dependent because the tile cache is, and it is four times the bytes at
    HIRES: 105 keys at 800 B rather than 200. See the derivation above.
    """
    if (RIPPLE_MODE if mode is None else mode) == "hires":
        return STREAM_HEADROOM_BYTES_HIRES
    return STREAM_HEADROOM_BYTES


def _wanted_mode():
    """The panel flags this variant wants, or None to leave the panel alone.

    None on the `"lores"` arm is the point: that arm makes NO `badge.mode` call,
    so flipping `RIPPLE_MODE` back restores the byte-for-byte behaviour of the
    build the owner has already judged, rather than something equivalent to it.
    """
    if RIPPLE_MODE != "hires":
        return None
    try:
        return HIRES | VSYNC  # noqa: F821 -- the Badgeware builtins
    except NameError:  # pragma: no cover -- a host without Badgeware's flags
        return None


def _enter_mode():
    """Take the panel to `RIPPLE_MODE`. Returns the mode to give back, or None.

    READS THE ENTRY MODE RATHER THAN ASSUMING IT.  `badgeware/__init__.py`'s last
    statement is `badge.mode(LORES | VSYNC)`, so that is what the launcher runs
    at and what a hardcoded restore would put back -- but reading it means a
    future launcher that chooses its own panel is restored to ITS choice and not
    to a constant somebody forgot to update here.  The fallback exists because
    `badge.mode()` returns `_current_mode`, which is None until something sets
    it; on a badge that is never, and on a host stub it might be.
    """
    want = _wanted_mode()
    if want is None:
        return None
    try:
        entry = badge.mode()  # noqa: F821
    except Exception:  # noqa: BLE001 -- no `mode` at all is a LORES ripple
        return None
    if not isinstance(entry, int):
        try:
            entry = LORES | VSYNC  # noqa: F821
        except NameError:  # pragma: no cover
            return None
    if entry == want:
        return None
    try:
        badge.mode(want)  # noqa: F821
    except Exception:  # noqa: BLE001
        # A HALF-APPLIED mode is still worth restoring: `badge.mode` sets
        # `_current_mode` before it touches the panel, so a raise inside it can
        # leave the panel and the bookkeeping disagreeing.
        pass
    return entry


def _leave_mode(entry):
    """Give the panel back before the launcher paints. NEVER RAISES.

    THE ONE THING IN THIS MODULE THAT MUST NOT BE SKIPPED.  Everything else here
    fails into "no ripple"; this one fails into a launcher drawing 160x120
    coordinates onto a 320x240 panel -- a quarter-size home screen in the corner,
    on the app whose failure needs a cable.  So it runs from the `finally`, on
    every path including `MemoryError`, and it runs BEFORE `_clear()` so the
    black the launcher inherits is black at the launcher's own geometry.
    """
    if entry is None:
        return
    try:
        badge.mode(entry)  # noqa: F821
    except Exception:  # noqa: BLE001
        pass


def _lights_off():
    """All four case lights DARK. NEVER RAISES. THE HANDOFF GUARANTEE.

    THIS IS THE ONE LIGHT CALL THAT MUST NOT BE SKIPPED, and the reason is in
    `launcher/menu/ui.py`, not here. The launcher owns its own lights policy and
    that policy is CHANGE-ONLY: `ui._lit` starts at `0.0` and `ui._caselights`
    writes `badge.caselights` only when the level MOVES. So a sequence that
    handed over with the case lit would leave it lit -- the launcher believes the
    lights are off, so it never writes a zero, and nothing turns them out until
    the wearer starts a hold gesture. A `FIRSTWAKE_SKIP` badge with stranded
    LEDs is the same defect by a shorter road.

    So this runs from `play()`'s `finally`, on every path -- the ordinary end, a
    skip for heap, a missing deck, a raise, a `MemoryError` -- and it is the
    reason no arm needs its own darkening call. `LightsTests` drives every one.

    `badge.caselights(0)` is the single-argument arity, which the pinned
    `badgeware/badge.py:198-205` expands to all four channels. `LIGHTS = False`
    makes this a no-op so that arm is byte-for-byte the pre-lights launcher.
    """
    if not LIGHTS:
        return
    try:
        badge.caselights(0)  # noqa: F821 -- the Badgeware builtin
    except Exception:  # noqa: BLE001
        pass


def _attach_lights(rich, calibration, waves, technique, columns, rows,
                   frame_count, bank, lut, mask_bytes):
    """The act's light sync, or None. NEVER RAISES. The viewer's own choices.

    Returns `(sync, kind, source, channels)`. `sync is None` means this act runs
    dark, and `kind` says why: `off` (the constant), `wave` (a stream this player
    cannot drive correctly), `nomodule` (a badge whose glyph app has decks but no
    light modules), `error` (anything else).

    MEMORYERROR IS CAUGHT HERE FOR THE VIEWER'S OWN REASON, stated in
    `glyph`'s `_attach_lights`: a sync allocates per-technique buffers and the
    rear lights are the one part of the ceremony whose absence nobody can miss.
    The buffers are small -- `frame_count * 5` bytes plus a 256-byte curve table
    and 102 coverage bytes, so ~900 B for the longer deck -- which is why they
    are NOT in `STREAM_HEADROOM_BYTES`' derivation: they round to nothing beside
    a 128,000-byte tile cache. Caught anyway, because the moment this runs is the
    moment after a 98,368-byte contiguous read.
    """
    if not LIGHTS:
        return None, "off", None, None
    if rich is None or calibration is None or waves is None:
        return None, "nomodule", None, None
    try:
        # THE VIEWER PICKS PER TECHNIQUE AND THIS IS ITS TEST, verbatim.
        # `lifecycle_for` is non-None for `wave` alone, so no shipped act takes
        # this branch -- but a third stream might, and driving a wave deck with
        # the motion mapper would be a picture rather than an error, which is
        # `AGENTS.md`'s sticker lesson. Dark is the honest answer.
        if waves.lifecycle_for(technique, columns, rows) is not None:
            return None, "wave", None, None
        channels = waves.channel_map_from_review()
        source = "review" if channels else "fallback"
        if channels is None:
            channels = waves.DEFAULT_CHANNEL_FOR_ZONE
        luma_scale, motion_scale, motion_weight = calibration.calibration_for(
            technique)
        sync = rich.RichGlyphLightSync(
            badge.caselights,  # noqa: F821
            bank,
            lut,
            technique,
            columns,
            rows,
            channel_for_zone=channels,
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
            frame_count=frame_count,
            mask_bytes=mask_bytes,
            # THE REAL TICK HELPERS, NOT THE SYNC'S DEFAULTS. Left unset it
            # falls back to `left - right`, which is wrong across
            # MicroPython's 30-bit tick wrap -- the rate limiter would stop
            # writing for a whole wrap period. A boot animation is unlikely to
            # straddle one, but the failure is silent and the fix is two
            # keyword arguments.
            ticks_diff=_ticks_diff,
            ticks_add=_ticks_add,
        )
        return sync, "motion", source, channels
    except Exception as error:  # noqa: BLE001 -- see the module docstring
        print("FIRSTWAKE_LIGHTS_NOTE dark: %r" % (error,))
        _lights_off()
        return None, "error", None, None


def _detach_lights(sync, position, count, technique, kind, source, channels):
    """Report the act's lights and give them back DARK. NEVER RAISES.

    ONE LINE PER ACT, ALWAYS, EVEN A DARK ONE -- because "the lights did nothing"
    and "the lights were never asked to" are different faults and a panel cannot
    tell them apart. `writes=` is the whole oracle for "the case actually
    pulsed": it is the count of `badge.caselights` calls the mapper made, so a
    zero on a lit-looking act means the sync was built and then never fed.
    `dup=` is what the change-only filter suppressed and `scans=` is the cost
    term -- one cold 384-cell scan per fed frame, which is what §LIGHT_EVERY is
    about.

    CLOSING BETWEEN ACTS IS DELIBERATE AND IT IS FREE ON GLASS. `close()` writes
    `(0, 0, 0, 0)`, and signal-ripple's last frame is 23 of 384 cells lit -- the
    same fact that decided against inserting a dark frame at the cut -- so the
    smoothed level is already near its floor when the act ends. What closing buys
    is the memory ordering: the sync and its per-frame tables are dropped before
    the next `glyph_stream.load` wants up to 98,368 B contiguous, which is
    §ONE DECK AT A TIME applied to the lights.
    """
    if sync is None:
        print("FIRSTWAKE_LIGHTS seq=%d/%d asset=%s kind=%s"
              % (position, count, technique, kind))
        return
    try:
        print("FIRSTWAKE_LIGHTS seq=%d/%d asset=%s kind=%s channels=%s "
              "source=%s every=%d writes=%d dup=%d scans=%d peak=%.2f"
              % (position, count, technique, kind,
                 ",".join(str(channel) for channel in channels), source,
                 LIGHT_EVERY, sync.write_calls, sync.duplicate_writes_avoided,
                 sync.frame_scans, sync.peak_input))
    except Exception:  # noqa: BLE001
        pass
    try:
        sync.close()
    except Exception:  # noqa: BLE001
        _lights_off()


def _read(path, size=None):
    """Whole-file read. Raises OSError when the glyph app is not installed."""
    with open(path, "rb") as handle:
        return handle.read() if size is None else handle.read(size)


def _face_pressed():
    """True when any of the five face keys went down since the last poll."""
    try:
        for key in (BUTTON_A, BUTTON_B, BUTTON_C,  # noqa: F821 -- builtins
                    BUTTON_UP, BUTTON_DOWN):      # noqa: F821
            if badge.pressed(key):  # noqa: F821
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def play(reason=None, root=None, presents_per_frame=None, sequence=None):
    """Play the opening sequence if this boot earned it. NEVER RAISES.

    Returns `(frames, note)`: the stream frames presented ACROSS THE WHOLE
    SEQUENCE, and a short reason token for the marker line. `(0, "resume")` is
    the common case and the point of the feature -- a HOME exit pays one register
    read and one `print`.

    THE FRAME COUNT IS A CONTRACT, NOT A STATISTIC, and `launcher/menu/ui.py` is
    the reader: `frames > 0` means the sequence PAINTED, which is the only
    condition under which the loading screen is suppressed. Every failure path
    below returns the frames it managed before failing, so a badge that played
    act one and then lost act two still suppresses -- it has something on the
    panel -- while a badge that skipped for heap or has no glyph app returns 0
    and gets the ordinary loading screen. That is why this is not a boolean.

    `reason`, `root` and `sequence` are injected by the tests; production passes
    none of them.
    """
    frames = 0
    note = "ok"
    if reason is None:
        reason = read_reason()
    if not wants_ripple(reason):
        # ONE LINE ON THE COMMON PATH, and it is the instrument for the whole
        # feature: a trip home that printed `ripple=0` proves the register was
        # read and the ceremony was declined, which is not observable from a
        # panel that simply went to the loading screen.
        print("FIRSTWAKE wake=%d ripple=0" % reason)
        return 0, "resume"

    root = GLYPH_ROOT if root is None else root
    held = presents_per_frame
    if held is None:
        held = PRESENTS_PER_FRAME
    if held < 1:
        held = 1
    names = RIPPLE_SEQUENCE if sequence is None else tuple(sequence)

    saved_path = None
    saved_surface = None
    saved_mode = None
    stream = None
    renderer = None
    target = None
    lights = None
    try:
        # THE BORROW CONTRACT, and it is not hygiene: `shared/loading.py`
        # records an hour-long bug where a loader set the pen and the app that
        # followed measured its own text in the wrong face. This runs in front
        # of a module body that is about to do exactly that.
        try:
            saved_surface = (screen.pen, screen.font)  # noqa: F821
        except Exception:  # noqa: BLE001
            saved_surface = None

        # INSIDE the try and restored in the finally, never at module scope.
        # `benchmark/badge/density_flip_smoke.py:155` records why: a
        # module-level insert plus import runs before the entry state can be
        # captured, so a raise leaves another app's directory on `sys.path` for
        # whatever runs next -- and in the launcher, what runs next is the whole
        # badge.
        saved_path = list(sys.path)
        if root not in sys.path:
            sys.path.insert(0, root)

        import glyph_render
        import glyph_stream

        # THE LIGHT MODULES, AND THEIR OWN `try` IS THE POINT. They are three
        # more files in the same app directory, so they ride the SAME soft
        # dependency as the decks -- but a badge that has `glyph_render` and not
        # `glyph_rich_lights` must play the ceremony DARK, not skip it. Folding
        # them into the import above would report the most decorative failure
        # this feature has as `reason=noasset` and take the whole animation with
        # it. None of the three imports the glyph APP entry, and none of them
        # imports hardware: `glyph_rich_lights` and `light_calibration_2x` have
        # no imports at all and `wave_lights` takes `json` and `math`, both
        # frozen. That is what makes this the same pattern and not a new one.
        rich = None
        calibration = None
        waves = None
        if LIGHTS:
            try:
                import glyph_rich_lights
                import light_calibration_2x
                import wave_lights
                rich = glyph_rich_lights
                calibration = light_calibration_2x
                waves = wave_lights
            except Exception as error:  # noqa: BLE001
                # ALL THREE OR NONE. A partial set would leave `_attach_lights`
                # reaching into a None, and the whole point of the arm is that
                # it degrades to a dark ceremony rather than to a traceback.
                rich = None
                calibration = None
                waves = None
                print("FIRSTWAKE_LIGHTS_NOTE dark: no light modules %r"
                      % (error,))

        # THE HEAP GATE RUNS BEFORE THE PANEL DOES, deliberately: it needs only
        # the files' sizes and this variant's own headroom, so a badge that skips
        # for heap has not touched the mode and cannot be left mid-switch.
        #
        # `need` IS THE BIGGEST DECK, NOT THE SUM, and that is a claim about the
        # loop below rather than an optimism: §ONE DECK AT A TIME frees each
        # stream before loading the next, so the two 90-KB buffers are never both
        # resident. A missing file measures 0 and is simply not counted -- the
        # OSError that follows is the honest report of it.
        gc.collect()
        paths = ["%s/assets2x/%s.gpa" % (root, name) for name in names]
        need = 0
        for path in paths:
            size = _stream_size(path)
            if size > need:
                need = size
        free = _free_heap()
        headroom = headroom_for()
        if free is not None and need and free < need + headroom:
            print("FIRSTWAKE_SKIP reason=heap free=%d need=%d"
                  % (free, need + headroom))
            return 0, "heap"

        # THE PANEL, and everything after this line reads it fresh. `badge.mode`
        # REPLACES the `screen` object rather than resizing it
        # (`docs/engineering-findings.md`: held references go stale, which is why
        # glyph_lab rebuilds its targets after every mode change), so the width,
        # the height and the `BlitTarget` below are all taken AFTER the switch.
        saved_mode = _enter_mode()
        width = int(getattr(screen, "width", 0))    # noqa: F821
        height = int(getattr(screen, "height", 0))  # noqa: F821

        # THE SHARED TARGET, BUILT ONCE FOR THE WHOLE SEQUENCE. This is the only
        # object that deliberately outlives a stream, and it is where the union
        # tile cache lives.
        #
        # WHY ONE TARGET AND A RENDERER PER STREAM, rather than either extreme.
        # `glyph_render`'s docstring rules it: *"One target outliving one renderer
        # is the design -- `glyph`'s viewer builds a renderer per A/C entry and
        # shares one module-level target, so stepping the catalogue keeps its
        # tiles warm."* Applied here that means the 21 keys the two decks share
        # are built once instead of twice (a measured 21 of 181 -> 160 builds,
        # ~106 ms saved at HIRES), while each stream still gets a renderer whose
        # `_previous` starts at 0xFF and whose changed-cell memo starts empty.
        #
        # AND THE MEMO IS WHY THE RENDERER MUST NOT BE SHARED. `draw(frame=index)`
        # memoises changed offsets PER FRAME INDEX, and two streams both index
        # from 0 -- so one renderer across both would file terminal-marquee's
        # frame 5 under signal-ripple's. The guard would catch it (an entry is
        # only trusted while `_previous` still holds the frame it was derived
        # from) but relying on a guard to save a design is how the 2026-08-21
        # cross-geometry tile bug shipped. A new renderer cannot collide.
        #
        # THE THIRD THING IT BUYS IS THE FRAME BOUNDARY THE JOIN WANTS: a fresh
        # `_previous` of 0xFF means the incoming stream's frame 0 repaints ALL 384
        # cells, so the cut is one whole clean frame and never a diff against the
        # outgoing deck's last picture.
        target = glyph_render.BlitTarget(screen, image, vec2)  # noqa: F821

        bank_spec = None
        bank = None
        lut = None
        started = _ticks_ms()
        for position, name in enumerate(names):
            stream = glyph_stream.load(paths[position])
            cell_w = width // stream.columns if stream.columns else 0
            cell_h = height // stream.rows if stream.rows else 0
            if cell_w < 1 or cell_h < 1:
                # RETURNS RATHER THAN BREAKING, so no `FIRSTWAKE_DONE` claims a
                # pass that never ran. The `finally` below still gives the panel
                # and the pen back -- that is what it is for -- and `frames` is
                # whatever earlier acts managed, which on the first act is 0 and
                # is exactly the pre-sequence behaviour.
                print("FIRSTWAKE_SKIP reason=panel w=%d h=%d" % (width, height))
                return frames, "panel"

            # THE BANK IS A PROPERTY OF THE CELL, SO IT IS READ ONCE PER
            # GEOMETRY and not once per deck: both shipped decks are 32x12, so
            # this reads 20,400 B once for the sequence instead of twice. The
            # re-read arm exists because a future third stream on a different
            # grid would need it, and `_GeometryCaches` already gives that stream
            # its own tile cache -- so the two halves of a grid change are
            # handled in the two places that own them.
            want = bank_for(cell_w, cell_h)
            if want != bank_spec:
                bank_spec = want
                bank = _read("%s/%s" % (root, want[0]))
                lut = _read("%s/%s" % (root, LUT_NAME), LUT_BYTES)
            mask_w, mask_h = bank_spec[1], bank_spec[2]

            renderer = glyph_render.GlyphRenderer(
                bank, lut, stream.columns, stream.rows, width, height,
                target, mask_width=mask_w, mask_height=mask_h,
            )
            # THE LIGHTS, PER ACT, FOR THE SAME REASON THE RENDERER IS PER ACT:
            # the sync's per-frame luma table is keyed by frame INDEX and both
            # decks index from 0, so one sync across both would answer act two's
            # frame 5 with act one's brightness. It also carries the technique's
            # own calibration, which is the whole reason the viewer builds one
            # per entry. Built AFTER the renderer so a light failure cannot cost
            # the animation, and after the bank read because it needs the bank.
            lights, light_kind, light_source, light_channels = _attach_lights(
                rich, calibration, waves, stream.technique,
                stream.columns, stream.rows, stream.frame_count,
                bank, lut, mask_w * mask_h,
            )
            # ONE LINE PER ACT, and `asset=` is what distinguishes them. `mode=`
            # and `panel=` are the instrument for the HIRES variant: `cell=` and
            # `bank=` already say which records were used, but only the panel
            # says whether the mode switch actually took -- a badge whose
            # `badge.mode` refused prints `mode=hires panel=160x120`, which is
            # the one failure that looks identical to success in every other
            # field. `seq=` is the sequence's own addition: with two decks on the
            # serial log, the position is the thing a reader needs and cannot
            # infer, because a deck that failed to load prints nothing at all.
            print(
                "FIRSTWAKE wake=%d mode=%s panel=%dx%d seq=%d/%d asset=%s "
                "grid=%dx%d cell=%dx%d bank=%dx%d frames=%d held=%d" % (
                    reason, RIPPLE_MODE, width, height,
                    position + 1, len(names),
                    stream.technique, stream.columns, stream.rows,
                    cell_w, cell_h, mask_w, mask_h, stream.frame_count, held)
            )

            # ONE PASS, IN ORDER, START TO FINISH. `frame_at` is deliberately not
            # used: it maps a clock onto the loop MODULO the frame count, which
            # is what a looping viewer wants and the opposite of a single pass.
            act_started = _ticks_ms()
            act_frames = 0
            for index in range(stream.frame_count):
                # ONE `frame_view` FOR BOTH READERS. The renderer and the light
                # sync want the same packed frame, and the viewer calls
                # `frame_view` twice for it; hoisting the memoryview slice here
                # is the one place this player is CHEAPER than the app it borrows
                # from, and it is free.
                packed = stream.frame_view(index)
                renderer.draw(packed, frame=index)
                if lights is not None and index % LIGHT_EVERY == 0:
                    # THE CASE FOLLOWS THE PANEL, IN THE SAME FRAME. Driven
                    # after the draw and BEFORE the presents, so the PWM write
                    # and the picture it came from land together rather than a
                    # frame apart.
                    #
                    # TOTAL, LIKE EVERYTHING ELSE HERE: a light mapper that
                    # raises mid-pass costs the case its glow and nothing more.
                    # `_lights_off` is called on the spot rather than left to the
                    # `finally` so the LEDs do not hold a stale level for the
                    # remaining frames.
                    try:
                        lights.update(index, packed, _ticks_ms())
                    except Exception as error:  # noqa: BLE001
                        print("FIRSTWAKE_LIGHTS_NOTE dark after %r" % (error,))
                        lights = None
                        light_kind = "error"
                        _lights_off()
                frames += 1
                act_frames += 1
                for _ in range(held):
                    # I4: the input layer stays live through a blocking animation
                    # even though nothing acts on a press. The sting's 4,090 ms
                    # window happened because its loop presented without polling,
                    # so a press there was never OBSERVED, not merely ignored.
                    badge.poll()      # noqa: F821
                    display.update()  # noqa: F821
                if SKIPPABLE and _face_pressed():
                    note = "skipped"
                    break
            # PER-ACT WALL TIME, and it is the one number this feature has been
            # arguing about from a model. `FIRSTWAKE_DONE` gives the total, which
            # cannot say which deck spent it; `launcher/host/ripple_cost.py`
            # predicts 3,622 and 3,074 ms at HIRES held=1 and has never been
            # checked per act against a device. This line is that check.
            print("FIRSTWAKE_SEG seq=%d/%d asset=%s frames=%d ms=%d"
                  % (position + 1, len(names), stream.technique, act_frames,
                     _ticks_diff(_ticks_ms(), act_started)))
            # THE ACT'S LIGHTS, REPORTED AND THEN DARK. Runs on the skipped path
            # too -- the `break` below is after it on purpose, because a press
            # that ends the ceremony must not end it with the case still lit.
            _detach_lights(lights, position + 1, len(names), stream.technique,
                           light_kind, light_source, light_channels)
            lights = None
            if note == "skipped":
                break

            # ONE DECK AT A TIME: FREE, THEN LOAD. The next `glyph_stream.load`
            # wants up to 98,368 B CONTIGUOUS, and on 2026-08-22 the owner's
            # badge raised `MemoryError` on a 73,792 B dense read with ~66.8 KB
            # free -- fragmentation, not the total (`glyph-knowledge.md` §4.2).
            # So the outgoing stream and its renderer are dropped and collected
            # BEFORE the next name is touched, which is `glyph`'s own discipline
            # and the reason the heap gate above adds its headroom to the LARGEST
            # deck rather than to the sum. The target survives on purpose.
            renderer = None
            stream = None
            gc.collect()
        elapsed = _ticks_diff(_ticks_ms(), started)
        print("FIRSTWAKE_DONE frames=%d presents=%d ms=%d note=%s acts=%d"
              % (frames, frames * held, elapsed, note, len(names)))
    except MemoryError:
        print("FIRSTWAKE_SKIP reason=mem frames=%d" % frames)
        note = "mem"
    except ImportError as error:
        # THE SAME DIAGNOSIS AS A MISSING FILE, and it needs its own arm because
        # `ImportError` is not an `OSError` in either interpreter. A badge with no
        # glyph app installed fails at `import glyph_render`, one statement
        # BEFORE any path is opened, so without this the operator reads
        # `reason=error` for the most ordinary situation there is.
        print("FIRSTWAKE_SKIP reason=noasset error=%r" % (error,))
        note = "noasset"
    except OSError as error:
        # The glyph app is not installed, or its deck was left off this badge by
        # an asset profile. Not an error: a launcher with no ripple.
        print("FIRSTWAKE_SKIP reason=noasset error=%r" % (error,))
        note = "noasset"
    except Exception as error:  # noqa: BLE001 -- see the module docstring
        print("FIRSTWAKE_SKIP reason=error error=%r" % (error,))
        note = "error"
    finally:
        # DROP EVERYTHING. This is a one-shot: the streams, the renderers and the
        # target's union tile cache are dead the instant the sequence ends, and
        # the module body behind us is about to want 22.5 KB for the film codec
        # and then a film. `glyph`'s own discipline is FREE THEN LOAD, and this
        # is the free.
        #
        # THE TARGET IS THE ONE THAT MATTERS NOW. It holds 128,000 B of union
        # tiles at HIRES -- more than the 98,368-byte deck that used to be the
        # biggest thing in this function -- and it is the only object here that
        # deliberately outlived a stream, so it is the only one a reader might
        # expect to survive. It must not: the launcher's next allocation is the
        # film codec's.
        # THE LIGHTS GO OUT UNCONDITIONALLY, AND THIS IS THE HANDOFF GUARANTEE.
        # Every arm above reaches this line -- the ordinary end, `reason=heap`,
        # `reason=panel`, `reason=mem`, `reason=noasset`, `reason=error`, a
        # `SKIPPABLE` press -- because they all `return` or fall out of the `try`,
        # so no arm needs a darkening call of its own and none can be forgotten.
        # `_lights_off`'s own docstring says why it must not be skipped: the
        # launcher's lights policy is CHANGE-ONLY and believes the case is dark,
        # so a lit handoff strands the LEDs until the wearer starts a hold.
        #
        # IT IS A SECOND ZERO ON THE HAPPY PATH, which is deliberate. The act's
        # `close()` already wrote `(0, 0, 0, 0)`; this writes it again. Two PWM
        # calls at the end of a ~7 s ceremony against a guarantee that cannot be
        # reasoned about per arm is a trade worth making once.
        renderer = None
        stream = None
        target = None
        lights = None
        _lights_off()
        for name in ("glyph_render", "glyph_stream", "glyph_vocab",
                     "glyph_rich_lights", "light_calibration_2x",
                     "wave_lights"):
            sys.modules.pop(name, None)
        if saved_path is not None:
            sys.path[:] = saved_path
        # THE PANEL GOES BACK BEFORE THE BLACK DOES, and the order is the whole
        # of the handoff: `_leave_mode` replaces `screen` with the launcher's own
        # geometry, and `_clear()` then blacks THAT surface. Clearing first would
        # black a surface the mode change is about to throw away, and the
        # launcher's first paint would land on whatever the new buffer holds.
        _leave_mode(saved_mode)
        _clear()
        if saved_surface is not None:
            try:
                screen.pen, screen.font = saved_surface  # noqa: F821
            except Exception:  # noqa: BLE001
                pass
        gc.collect()
    return frames, note


def _clear():
    """Black, with NO present. The loading screen's frame 0 is the next paint.

    Presenting here would cost a whole VSYNC quantum to show a black panel the
    loading screen replaces immediately. Clearing without presenting means the
    editor window paints onto a known surface instead of over ripple remnants.

    ⚠ AT HIRES THIS LEAVES ONE UNMEASURABLE WINDOW, and it is worth knowing
    where the only candidate glitch in this feature lives. The panel is still
    lit with the ripple's last 320x240 frame when `_leave_mode` changes the
    driver's geometry underneath it, and it stays lit until the loading screen
    presents ~11-60 ms later. Nothing here can model what the ST7789 does with
    already-latched content across that change; no host or browser lane sees it
    (the playground's `fullres` zeroes its buffer, which hardware may or may not
    do). If a flick or a smear ever gets reported between the ripple and the home
    screen, THIS is the seam, and the fix is one `display.update()` below at a
    cost of one quantum.
    """
    try:
        screen.pen = color.rgb(0, 0, 0)  # noqa: F821
        screen.clear()                   # noqa: F821
    except Exception:  # noqa: BLE001
        pass


def _stream_size(path):
    """Bytes on disk, or 0 when it cannot be asked. Never raises."""
    try:
        import os
        return int(os.stat(path)[6])
    except Exception:  # noqa: BLE001
        return 0


def _free_heap():
    """`gc.mem_free()`, or None on a host that has no such thing."""
    try:
        return int(gc.mem_free())
    except Exception:  # noqa: BLE001
        return None


def _ticks_ms():
    """MicroPython's 30-bit tick counter, with a host stand-in."""
    try:
        return time.ticks_ms()
    except AttributeError:  # pragma: no cover -- CPython only
        return int(time.time() * 1000)


def _ticks_diff(later, earlier):
    try:
        return time.ticks_diff(later, earlier)
    except AttributeError:  # pragma: no cover -- CPython only
        return later - earlier


def _ticks_add(value, delta):
    """Wrap-safe tick addition, with a host stand-in.

    Handed to the light sync so its rate limiter is correct across
    MicroPython's 30-bit tick wrap. Its own default is `value + delta`, which
    would stop the lights updating for a whole wrap period.
    """
    try:
        return time.ticks_add(value, delta)
    except AttributeError:  # pragma: no cover -- CPython only
        return value + delta
