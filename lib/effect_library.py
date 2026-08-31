"""THE NUMBERED EFFECT LIBRARY: `play_effect` looks an id up in here.

WHAT THE BROADCAST IS FOR.  One console press has to make ~1,000 badges do the same
visible thing at the same instant ("play effect #7 for 5 seconds").  The payload
that crosses the wire is therefore deliberately tiny -- `{"kind", "id",
"duration_s"}` per sequence item and nothing else -- because ALL the animation
data lives here, in frozen firmware. The backend never ships a frame.

⚠ NAME COLLISION, AND IT IS NOT THE SAME WORD.  `shared/effects.py` is the
wearer's CARD FILTER set (a whole-surface native filter over the finished
setup).  This module is the fleet-triggered LIGHT SHOW library.  Neither
imports the other and neither should; they share only the English word.

WHAT AN EFFECT DRIVES, AND WHY IT IS NOT PIXELS.  Two output channels, both of
which the network runtime already owns and neither of which is the framebuffer:

  * the four rear case LEDs, via `badge.caselights` (`kind: "lights"`);
  * those PLUS the panel backlight, via `display.backlight` (`kind: "glyph"`).

THE PANEL IS NOT DRAWN ON, AND THAT IS A DECISION WITH TWO MEASURED REASONS, not
a shortcut.  `badgelink`'s `managed_update` is the only cross-app per-frame seam
on this badge (`docs/engineering-findings.md` §"There is no global per-frame seam
on this badge"), and the managed loop is `badge.clear() -> update() ->
display.update() -> badge.poll()`, so an overlay drawn from `NetworkService.poll`
WOULD reach the same present.  It must not, because:

  1. THE OVERLAY WOULD SCAR THE WORN BADGE.  An app that diff-draws sets
     `badge.default_clear = None` and repaints only changed cells -- `nametag`,
     `setup` and `glyph` all do.  `nametag` is the badge's resting state, so a
     fleet effect would leave its pixels on screen until the wearer pressed
     something.  A show that damages the product for everyone who looked away is
     worse than no show.
  2. THE DECK DOES NOT FIT IN A RUNNING APP'S HEAP.  A `.gpa` cell stream is a
     49-74 KB CONTIGUOUS read plus a 20,400 B mask bank and a 10,240 B LUT, and
     the owner reproduced `MemoryError: memory allocation failed, allocating
     66816 bytes` on glass doing exactly that with the badge otherwise idle
     (`glyph/badge/glyph/__init__.py` §THE MEMORY VALVE).  A MemoryError raised
     inside `run(update)` hard-resets the badge -- every badge, at once.  The
     first-wake ceremony can afford a deck only because it runs in the launcher's
     module body with an empty heap, and it still costs ~7.0-9.2 s of blocked
     wall time (`launcher/menu/first_wake.py` §THE SEQUENCE).

So the glyph DECKS are reused here as a temporal vocabulary rather than as
bytes: a `kind: "glyph"` effect is named after the shipped technique whose rhythm
it plays (`glyph/badge/glyph/assets/`, and the same five names
`glyph_lights.TECHNIQUE_ENERGY_SCALE` calibrated), and it costs no asset read at
all.  Nothing in this module opens a file, so a badge whose art did not install
plays every effect exactly as a badge whose art did.  Rendering a real deck to
the panel is a separate, app-side opt-in seam and is recorded as such in
`docs/design/effect-library.md`; it is deliberately NOT in the frozen firmware.

WHAT A FRAME COSTS.  At most one `badge.caselights` write and at most one
`display.backlight` write, both suppressed unless the level MOVED.  A caselight
write is 252.5 us median on device (100-write measurement, `snake/README.md`)
against an ~11.43 ms VSYNC quantum.  ⚠ THE COMPARISON THAT MATTERS is the
first-wake ceremony's 7.5-7.8 ms per frame: that cost is the QUANTISATION SCAN of
a rendered glyph frame, not the PWM write, and it made the ceremony +24 % dearer
(`launcher/menu/first_wake.py` §THE CASE LIGHTS).  A table-driven effect has no
frame to scan, which is why this player is affordable in every app's frame pump
and that one is not.  Nobody may "simplify" this into a per-frame scan of
anything.

THE STEADY FRAME ALLOCATES NOTHING, same rule and same reason as
`caselight_program`: every level is an element of a pre-built table chosen by
integer arithmetic, `step()` answers False when nothing moved, and the per-segment
`Program` objects are built ONCE when the effect starts (at most
`MAX_SEGMENTS` of them for a whole show) rather than per frame.

MEASURED, on the pinned MicroPython unix port, all 22 effects shipped before the
2026-08-30 light-set expansion
(`badgelink/host/effect_frame_cost.py`, which exits non-zero if this stops being
true): **0 bytes of heap per frame over 2,000 frames at an 11 ms step**, on every
arm.  One-off costs: **608-1,408 B** to construct a player (1-5 segments) and
**4,672 B once per boot** for the shared caselight->panel table, which includes
the lazy `caselight_program` import itself.  Write density ranges from 1 frame in
2,000 (`on`, `off`) to 1,084 (`signal-histogram`, the busiest rhythm in the set).
⚠ These are HOST numbers and describe the SHAPE, not the badge: block
granularity differs on the RP2350 and the real per-frame cost is the PWM and
panel writes, which this probe does not perform.

RERUN 2026-08-30, after the four spatial lights rows, on the pinned
badgeware-playground MicroPython WebAssembly runtime: **all 36 arms still
allocate 0 B per frame and terminate**; construction is 672-4,752 B (the high
end is `night-finale`'s 20 prebuilt four-tuples), the shared table is 10,336 B
in that runtime, and write density remains 1-1,084 frames in 2,000. Those
numbers replace no device claim; they prove the same bounded shape on the
runtime available for this change.

DURATION IS AUTHORITATIVE AND THE CYCLE LOOPS UNDER IT.  Each entry declares a
CYCLE; the player repeats it until `duration_s` expires and then restores.  That
is what makes one id usable for both a 3 s wink and a 60 s ambient wash.

TIME IS THE CALLER'S PROBLEM, deliberately -- `caselight_program`'s rule, kept:
this module takes `elapsed_ms` and imports nothing at module scope, so
`time.ticks_ms` wrap-around is handled in exactly one place (`network_runtime`'s
`_ticks_diff`) and the whole library is testable by passing integers.

/system/lib RULE: no sibling import at module scope.  `caselight_program` is
resolved lazily on the first `player_for` and then held, so a half-refreshed lib
costs one failed ack rather than the boot.
"""


# ---------------------------------------------------------------------------
# the wire contract
# ---------------------------------------------------------------------------

KIND_GLYPH = "glyph"
KIND_LIGHTS = "lights"

#: The two `kind` values `play_effect` accepts.  Anything else is a failed ack.
KINDS = (KIND_GLYPH, KIND_LIGHTS)

#: Exactly the keys `play_effect` carries.  A payload with a fourth key is
#: REFUSED rather than ignored: the backend and the badge freeze together, so an
#: unknown key means one side is running code the other has not seen, and
#: silently dropping it would hide that until it mattered in front of a room.
PAYLOAD_KEYS = ("kind", "id", "duration_s")

# HOW LONG AN EFFECT MAY RUN, and both ends are arguments rather than taste.
#
# ONE SECOND MINIMUM, because a shorter fleet effect is dominated by broadcast
# fan-out and rendered-frame timing: it becomes a flicker on some badges and a
# missed moment on others.
#
# FIVE MINUTES MAXIMUM, because a fleet effect nobody can stop is ~1,000 badges
# nobody can stop.  It is the same argument `caselight_program` makes for its
# four primitives all terminating, ten times longer than the longest use anybody
# has described ("play effect #7 for 5 seconds"), and short enough that a
# mistyped duration is an embarrassment rather than an evacuation.
DURATION_MIN_S = 1
DURATION_MAX_S = 300

# ⚠ THE SERVER-SIDE `valid_effect_sequence` CHECK MUST MIRROR THIS CLAUSE FOR
# CLAUSE. The rule
# `caselight_program.valid_period` learned the hard way applies again: being
# LOOSE where the constraint is tight is harmless because the row cannot exist,
# while being TIGHT where the constraint is loose leaves a queued command that can
# never succeed and a queue that looks healthy.


# ---------------------------------------------------------------------------
# the segment vocabulary
# ---------------------------------------------------------------------------
#
# The four cycling primitives are `caselight_program`'s, by NAME and by level
# function -- this module does not re-implement a single ramp.  Two more exist
# here and nowhere else:
#
#   GAP  dark for its whole length
#   LIT  full brightness for its whole length
#
# WHY THEY COULD NOT GO IN `caselight_program`: that module mirrors
# `fleet_actions_set_lights_payload_check` clause for clause, and the constraint
# has four patterns.  Adding a fifth there would drift the module from the SQL it
# exists to mirror.  WHY THEY ARE NEEDED HERE: a `set_lights` show is a fixed
# number of cycles, so it never had to fill an arbitrary span; an effect's length
# comes from `duration_s`, so a rhythm needs a rest ("two quick blinks, then
# nothing for 600 ms") and a wash needs a hold.

FLASH = "flash"
BREATHE = "breathe"
STROBE = "strobe"
OFF = "off"
GAP = "gap"
LIT = "lit"

#: The four this module borrows, in `caselight_program.PATTERNS` order, plus the
#: two scalar patterns it owns.  A test pins the first four against that module
#: so a rename there fails here instead of silently producing a dark badge.
SEGMENT_PATTERNS = (FLASH, BREATHE, STROBE, OFF, GAP, LIT)

# FOUR-CHANNEL PHRASES. The wire still carries only a numbered effect: these
# names are firmware-local segment types whose bit masks select logical case
# channels CL0..CL3.  Fixed masks keep a room in sync; using `random` here would
# make ~1,000 badges look like noise instead of one show.
PINWHEEL = "pinwheel-4"
CROSSFIRE = "crossfire-4"
SPARKSTORM = "sparkstorm-4"
NIGHT_FINALE = "night-finale-4"
SPATIAL_PATTERNS = (PINWHEEL, CROSSFIRE, SPARKSTORM, NIGHT_FINALE)

# Every phrase contains one all-on frame so it still reads at the edge of the
# room. Physical clockwise order remains a device-eye question; these masks pin
# logical CL0..CL3 only (`docs/hardware-map.md`).
_SPATIAL_MASKS = {
    PINWHEEL: (0x1, 0x2, 0x4, 0x8, 0xF, 0x0),
    CROSSFIRE: (0x5, 0x0, 0xA, 0x0, 0x5, 0xA, 0xF, 0x0),
    SPARKSTORM: (0x1, 0x8, 0x2, 0x4, 0x9, 0x2, 0xC,
                 0x1, 0x6, 0x8, 0x3, 0xF, 0x0),
    NIGHT_FINALE: (0x1, 0x2, 0x4, 0x8, 0x5, 0xA, 0x3, 0xC, 0x6, 0x9,
                   0xF, 0x0, 0x9, 0x6, 0xC, 0x3, 0xA, 0x5, 0xF, 0x0),
}

# HOW MANY SEGMENTS ONE CYCLE MAY HAVE.  Eight, and the number bounds the only
# per-effect allocation there is: `player_for` builds one small `Program` per
# CYCLING segment, once.  Eight is twice the longest rhythm in the shipped set
# (`arrow-field`, four segments) and it keeps the whole construction under a
# single frame's chore budget.
MAX_SEGMENTS = 8

# THE PANEL'S FLOOR, AND IT IS BORROWED WITH ITS ARGUMENT INTACT.  0.1 is
# `fleet_actions_set_backlight_payload_check`'s floor, repeated at
# `network_runtime._apply_set_backlight`, and the reason it is not zero is the
# reason it is not zero here: "a dark panel is indistinguishable from a dead
# badge to its wearer, and this is a fleet-scope command."  A real "screen off"
# would be a different verb.
#
# It is a CROSS-REFERENCE, not a second authority -- `shared/backlight.py` makes
# the same disclaimer about the same number, and for the same reason: the CHECK
# constraint owns it.  Nothing here may widen it.
PANEL_FLOOR = 0.1


# ---------------------------------------------------------------------------
# the library
# ---------------------------------------------------------------------------
#
# ⚠ THE ID IS THE INDEX.  `LIGHTS_EFFECTS[3]` IS effect `{"kind": "lights", "id":
# 3}`.  That is the whole id scheme, and it is why `resolve()` is a bounds check
# rather than a table walk: ids are dense, unique and stable by construction, and
# `test_effect_library.StructureTests` fails if that ever stops being true.
#
# ⚠ APPEND ONLY. The console and saved show recipes name an effect by NUMBER;
# reordering this tuple silently repoints both. To retire an effect, replace its
# row with a quiet one and say so in the comment; never delete or move one.
#
# Each row is `(name, cycle, panel_cycle)`:
#   name         the stable slug the ack and the console show.  Unique across
#                BOTH tables, so a log line reads without its kind.
#   cycle        the caselight rhythm: a tuple of (pattern, period_ms, count).
#   panel_cycle  the backlight rhythm, or None to leave the panel alone.
#
# `period_ms` and `count` are `caselight_program`'s own bounds (100..60000 and
# 1..64) for the four borrowed patterns; GAP and LIT take the same fields and use
# them only for length.

_NAME = 0
_CYCLE = 1
_PANEL = 2

# THE `lights` SET -- the four rear LEDs only, no panel. The first eight are the
# frozen launch set; ids 8-17 add longer temporal phrases; ids 18-21 use the
# existing four-argument `badge.caselights(CL0, CL1, CL2, CL3)` form. Every
# appended phrase has a full-bright frame, a distinct cycle tuple and no more
# than MAX_SEGMENTS, so the extra choice does not weaken the existing brightness,
# identity or allocation contracts.
LIGHTS_EFFECTS = (
    # 0 -- DARK, for the whole duration.  The escape hatch: whatever a badge is
    #      doing, id 0 makes the fleet quiet, and it is id 0 so an operator under
    #      pressure does not have to look it up.
    ("off", ((GAP, 1000, 1),), None),
    # 1 -- a slow, unmistakable on/off.  `caselight_program`'s own default period
    #      and the shape its docstring calls "an obviously-deliberate blink".
    ("blink", ((FLASH, 1000, 1),), None),
    # 2 -- a calm two-second swell.  BREATHE is a linear triangle in REQUEST
    #      space and that IS the even fade, because the firmware applies its own
    #      2.2 gamma (`badge.caselights` is `duty_u16(int(level ** 2.2 *
    #      65535))`).  Correcting twice is the documented mistake
    #      (`glyph/badge/glyph/wave_lights.py`).
    ("pulse", ((BREATHE, 2000, 1),), None),
    # 3 -- attention.  STROBE's bright phase is a fixed 40 ms regardless of
    #      period (`caselight_program.STROBE_ON_MS`), so a long strobe stays a
    #      pulse instead of becoming a floodlight.
    ("strobe", ((STROBE, 250, 1),), None),
    # 4 -- two quick beats and a rest.  The rest is why GAP exists.
    ("heartbeat", ((FLASH, 200, 2), (GAP, 600, 1)), None),
    # 5 -- three fast ticks then a pause.  Reads as urgency without the distress
    #      connotation of a real SOS, which is the wrong register for a
    #      conference floor.
    ("alert", ((STROBE, 120, 3), (GAP, 600, 1)), None),
    # 6 -- ambient.  Four seconds is slower than anyone reads as a signal, which
    #      is the point: a room of these looks like weather, not like an alarm.
    ("beacon", ((BREATHE, 4000, 1),), None),
    # 7 -- steady on.  The other reason LIT exists: "light the room" is a real
    #      request and no cycling primitive expresses it.
    ("on", ((LIT, 1000, 1),), None),
    # 8 -- a deliberate knock: two readable flashes followed by enough silence
    #      that it cannot be mistaken for the continuous launch-set blink.
    ("double-tap", ((FLASH, 240, 2), (GAP, 920, 1)), None),
    # 9 -- three rounded swells rather than cuts. The 800 ms period reaches the
    #      shared BRIGHT table entry on every pulse, even at the default 5 s.
    ("soft-triple", ((BREATHE, 800, 3), (GAP, 800, 1)), None),
    # 10 -- two short beams one second apart and then a long dark sweep. The
    #       asymmetry is what separates it from heartbeat across a room.
    ("lighthouse",
     ((LIT, 200, 1), (GAP, 800, 1), (LIT, 200, 1), (GAP, 2800, 1)), None),
    # 11 -- a hard flare, a small separation, then one broad halo. This uses
    #       existing bounded primitives rather than adding a one-off fade mode.
    ("flare",
     ((LIT, 300, 1), (GAP, 300, 1), (BREATHE, 2400, 1), (GAP, 1000, 1)), None),
    # 12 -- three flashes whose cadence accelerates into a full-bright hold.
    #       Segment periods carry the timing; no counter is added to the player.
    ("countdown",
     ((FLASH, 1200, 1), (FLASH, 800, 1), (FLASH, 400, 1),
      (LIT, 800, 1), (GAP, 1200, 1)), None),
    # 13 -- the same acceleration with silence between claps, using the full
    #       eight-segment cap but not increasing the player's allocation bound.
    ("slow-clap",
     ((FLASH, 1600, 1), (GAP, 400, 1), (FLASH, 1200, 1), (GAP, 400, 1),
      (FLASH, 800, 1), (GAP, 400, 1), (FLASH, 400, 1), (GAP, 1600, 1)), None),
    # 14 -- eight bounded ticks resolve into a steady full-bright finish. The
    #       finite count keeps a repeated default-duration show self-restoring.
    ("drumroll", ((STROBE, 180, 8), (LIT, 700, 1), (GAP, 1200, 1)), None),
    # 15 -- two short swells followed by one broad swell. All are the same
    #       allocation-free triangle; only their musical phrase is new.
    ("rolling-wave",
     ((BREATHE, 1200, 2), (BREATHE, 2400, 1), (GAP, 600, 1)), None),
    # 16 -- broad flashes, a brief rest, tight sparks, then a bright finish. It
    #       is intentionally celebratory without inventing random per-badge time.
    ("celebration",
     ((FLASH, 300, 4), (GAP, 200, 1), (STROBE, 120, 4),
      (LIT, 700, 1), (GAP, 1000, 1)), None),
    # 17 -- two sparse pinpricks and one wider wink. Deterministic spacing keeps
    #       every badge on the same phrase when this is used inside a sequence.
    ("constellation",
     ((STROBE, 700, 2), (GAP, 300, 1), (FLASH, 1100, 1),
      (GAP, 1700, 1)), None),
    # 18 -- one logical lamp advances per beat, then all four resolve together.
    #       The physical diffuser order is deliberately not claimed here.
    ("pinwheel", ((PINWHEEL, 720, 1),), None),
    # 19 -- opposing logical pairs trade places before a full-room hit.
    ("crossfire", ((CROSSFIRE, 800, 1),), None),
    # 20 -- a deterministic irregular mask sequence: lively across a fleet,
    #       but identical on every badge and every replay.
    ("sparkstorm", ((SPARKSTORM, 1040, 1),), None),
    # 21 -- the broadest logical-channel phrase and the fastest approved pace,
    #       ending each lap with an all-on hit and a clean dark separation.
    ("night-finale", ((NIGHT_FINALE, 1200, 1),), None),
)

# THE `glyph` SET -- caselights AND the panel backlight, named after the shipped
# deck technique whose rhythm each one plays.  EVERY NAME HERE IS A FILE IN THE
# GLYPH APP'S `assets/` OR `assets2x/`, pinned by
# `test_effect_library.MissingAssetTests`.  Nothing here READS those files -- see
# the module docstring -- so the pin is about the vocabulary staying honest, not
# about a dependency.
#
# WHY THE LAST SIX MAY SHARE A RESTRAINED RHYTHM.  The original eight predate
# Nametag's pixel show and had to be distinguishable on four LEDs plus one
# backlight alone.  Ids 8-13 command real temporary decks, so the picture now
# supplies the identity.  Making the lamps compete with a Select 26 lockup would
# turn a logo show into a strobe show; one slow same-period breathe on both
# channels keeps the artwork load-bearing while avoiding a static rear lamp.
# The five lockups stay in the glyph app's own order and `elephant` stays last,
# exactly as the owner approved on 2026-08-28.
GLYPH_EFFECTS = (
    # 0 -- radar: one slow sweep round the case, the panel swelling with it.
    #      In phase on purpose: the deck's sweep is one moving front, not two.
    ("radar", ((BREATHE, 3000, 1),), ((BREATHE, 3000, 1),)),
    # 1 -- wave: the LEDs roll at 1.2 s under a panel swell at twice that, so the
    #      two never line up and the badge reads as a rolling surface rather than
    #      as one pulsing lamp.
    ("wave", ((BREATHE, 1200, 1),), ((BREATHE, 2400, 1),)),
    # 2 -- signal-ripple: three tight ticks then quiet, under a single slow panel
    #      swell across the whole 1.35 s cycle.  This is the first-wake
    #      ceremony's opening deck, so it is the one a wearer has already seen.
    ("signal-ripple", ((FLASH, 150, 3), (GAP, 900, 1)), ((BREATHE, 1350, 1),)),
    # 3 -- ring-buffer: FOUR rings, which is the deck's own count since the
    #      2026-08-26 rebuild stopped its fill at four.  Keeping the number
    #      matched is the whole reason this row is named after that deck.
    ("ring-buffer", ((FLASH, 250, 4), (GAP, 1000, 1)), ((BREATHE, 2000, 1),)),
    # 4 -- packet-router: five fast packets over a panel held steady.  The one
    #      entry whose panel does not move, so a fleet of them looks like traffic
    #      on a lit board.
    ("packet-router", ((STROBE, 200, 5), (GAP, 500, 1)), ((LIT, 1500, 1),)),
    # 5 -- terminal-marquee: four even ticks and an equal rest, a cursor's
    #      cadence.  The ceremony's second act.
    ("terminal-marquee", ((FLASH, 300, 4), (GAP, 300, 1)), ((BREATHE, 2400, 1),)),
    # 6 -- signal-histogram: four quick swells then a rest, bars filling and
    #      clearing.
    ("signal-histogram", ((BREATHE, 600, 4), (GAP, 400, 1)), ((BREATHE, 2800, 1),)),
    # 7 -- arrow-field: a two-speed rhythm (slow pair, fast pair, rest), the
    #      busiest signature in the set and the one that reads from across a
    #      room.
    ("arrow-field",
     ((FLASH, 400, 2), (GAP, 200, 1), (FLASH, 200, 2), (GAP, 600, 1)),
     ((BREATHE, 1400, 1),)),
    # 8 -- logo-sizzle: one restrained, same-period breathe on both channels.
    #      Its own 2.38 s storyboard already blanks twice per lap, so a flash or
    #      independent cadence would compete with the lockup instead of framing it.
    ("logo-sizzle", ((BREATHE, 2400, 1),), ((BREATHE, 2400, 1),)),
    # 9 -- logo-trail: one four-second swell on both channels.  This is the
    #      widest and busiest lockup field; moving the lamps any faster would
    #      turn its deliberate punctuation trail back into visual noise.
    ("logo-trail", ((BREATHE, 4000, 1),), ((BREATHE, 4000, 1),)),
    # 10 -- logo-offset: matching 3.6 s breathes support two sparse rows without
    #       adding a second cadence to the only lockup with `26` on the top line.
    ("logo-offset", ((BREATHE, 3600, 1),), ((BREATHE, 3600, 1),)),
    # 11 -- logo-left: matching slow breathes on both channels.  The
    #       arrangement differs from `logo-stack` only by a 60 px year shift, so
    #       its lamps deliberately do not invent a louder distinction.
    ("logo-left", ((BREATHE, 4000, 1),), ((BREATHE, 4000, 1),)),
    # 12 -- logo-stack: the same restrained light bed as `logo-left`.  The logo
    #       placement is the comparison the viewer should see; changing the
    #       rhythm would answer a different and less useful question.
    ("logo-stack", ((BREATHE, 4000, 1),), ((BREATHE, 4000, 1),)),
    # 13 -- elephant: a slightly livelier case breathe under the slow 2.4 s
    #       panel swell.  The moving Muybridge study can carry that extra lift
    #       without the FLASH/STROBE cuts forbidden beneath a brand lockup.
    ("elephant", ((BREATHE, 1800, 1),), ((BREATHE, 2400, 1),)),
)

_TABLES = {KIND_LIGHTS: LIGHTS_EFFECTS, KIND_GLYPH: GLYPH_EFFECTS}


# ---------------------------------------------------------------------------
# lazy sibling resolution
# ---------------------------------------------------------------------------

_lights_mod = None
_panel_map = None


def _lights():
    """`caselight_program`, resolved once and held.

    LAZY BECAUSE OF THE /system/lib RULE: a module-scope sibling import makes a
    half-refreshed lib take the BOOT down rather than one command.  HELD because
    `player_for` must not pay a `__import__` and its allocations on every
    command, and because `_panel_levels` derives from its table.
    """
    global _lights_mod
    if _lights_mod is None:
        import caselight_program

        _lights_mod = caselight_program
    return _lights_mod


def _panel_levels():
    """caselight level -> panel level, built once and held.

    A dict rather than arithmetic because the alternative is a float multiply
    (and therefore an allocation) on every frame the panel moves.  Seventeen
    entries, keyed by `caselight_program.LEVELS`, so the panel is quantised
    exactly as coarsely as the LEDs are and the two channels can never disagree
    about what "half" means.

    The range is PANEL_FLOOR..1.0 rather than 0..1: see PANEL_FLOOR.
    """
    global _panel_map
    if _panel_map is None:
        span = 1.0 - PANEL_FLOOR
        _panel_map = dict(
            (level, PANEL_FLOOR + level * span) for level in _lights().LEVELS)
    return _panel_map


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------

def resolve(kind, effect_id):
    """The entry for `(kind, id)`, or None.

    NONE RATHER THAN A RAISE, because both callers want to say something
    different about the miss: `player_for` fails the ack with the id in the
    message, while `describe`/`catalogue` are read-only and answer nothing.

    A bounds check is the whole lookup because the id IS the index -- see the
    table comment.  `bool` is rejected before the bounds check: `True` is an int
    in Python and would otherwise silently resolve to effect 1.
    """
    table = _TABLES.get(kind)
    if table is None:
        return None
    if isinstance(effect_id, bool) or not isinstance(effect_id, int):
        return None
    if effect_id < 0 or effect_id >= len(table):
        return None
    return table[effect_id]


def describe(kind, effect_id):
    """One effect as a plain dict, or None.  For acks, logs and the console."""
    entry = resolve(kind, effect_id)
    if entry is None:
        return None
    return {"kind": kind, "id": effect_id, "name": entry[_NAME],
            "cycle_ms": cycle_ms(entry[_CYCLE]),
            "panel": entry[_PANEL] is not None}


def catalogue():
    """Every effect in the library, in id order within kind.

    THIS IS WHAT THE BACKEND'S PICKER SHOULD BE BUILT FROM, and it is why the
    names are here rather than only in the console: the firmware freezes and the
    backend does not, so the badge has to be able to state what it actually
    carries.  A host script can dump it to JSON for the admin UI without anyone
    re-typing a list that would then drift.
    """
    rows = []
    for kind in KINDS:
        for effect_id in range(len(_TABLES[kind])):
            rows.append(describe(kind, effect_id))
    return tuple(rows)


def cycle_ms(cycle):
    """How long one pass through a cycle takes.

    Every segment contributes `period_ms * count`, INCLUDING `off` -- which is
    the one place this module deliberately reads a segment differently from
    `caselight_program`, where `off` is a single dark frame with `total_ms == 0`.
    Here a segment's length is what makes the cycle loop, so a zero-length
    segment would be an infinite loop rather than a quick blink.  Use GAP for a
    rest; `off` inside a cycle means the same thing and is accepted so a future
    row can spell it either way.
    """
    total = 0
    for segment in cycle:
        total += int(segment[1]) * int(segment[2])
    return total


# ---------------------------------------------------------------------------
# payload validation
# ---------------------------------------------------------------------------

def parse(payload):
    """One `play_effect` payload -> `(kind, id, duration_ms)`, or raise.

    EVERY REJECTION IS A FAILED ACK AND NEVER A RENDER.  The command arrives from
    a fleet fan-out, so the badge's only safe answers are "played it" and "could
    not"; guessing at a payload it does not understand is how one console typo
    becomes ~1,000 badges doing something nobody chose.

    The clause order mirrors what a CHECK constraint would do, and the FIRST
    clause is the one `caselight_program.parse` learned from a real Postgres:
    test for the KEY before reading it, because a missing key makes
    `jsonb_typeof(...)` SQL NULL and a CHECK PASSES on NULL.
    """
    if not isinstance(payload, dict):
        raise ValueError("play_effect payload must be an object")
    keys = tuple(sorted(payload.keys()))
    if keys != tuple(sorted(PAYLOAD_KEYS)):
        raise ValueError(
            "play_effect payload requires exactly {}".format(
                ", ".join(PAYLOAD_KEYS)))
    kind = payload["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("play_effect kind must be one of {}".format(
            ", ".join(KINDS)))
    effect_id = payload["id"]
    if resolve(kind, effect_id) is None:
        # ONE MESSAGE FOR "not an int" AND "no such id", on purpose: both are
        # "this badge does not have that effect", which is exactly what an
        # operator needs to read off a failed ack when half a fleet is running
        # firmware that predates a new row.
        raise ValueError(
            "this badge has no {} effect {!r}".format(kind, effect_id))
    duration = payload["duration_s"]
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValueError("play_effect duration_s must be a number")
    if duration != duration or duration * 0 != 0:      # NaN, +/-inf, no math
        raise ValueError("play_effect duration_s must be finite")
    if duration < DURATION_MIN_S or duration > DURATION_MAX_S:
        raise ValueError("play_effect duration_s must be {}..{}".format(
            DURATION_MIN_S, DURATION_MAX_S))
    return (kind, effect_id, int(duration * 1000))


# ---------------------------------------------------------------------------
# the player
# ---------------------------------------------------------------------------

class EffectPlayer:
    """One running effect.  Ask it for a frame once per rendered frame.

    THE FRAME PROTOCOL, and it is shaped to allocate nothing in the steady case:

        if player.step(elapsed_ms):
            if player.case_level is not None:
                caselights(player.case_level)
            if player.panel_level is not None:
                backlight(player.panel_level)
        if player.done:
            player = None

    `step` returns False on every frame where neither channel moved, which is
    most of them -- True and False are singletons, so a quiet frame allocates
    nothing at all.  `case_level`, optional `case_levels`, and `panel_level` are
    elements of pre-built tables, never freshly computed floats or tuples.

    IT IS A DIFFERENT SHAPE FROM `caselight_program.Program` ON PURPOSE.  That
    class returns a level because it drives ONE channel; this one drives two, and
    returning a tuple per frame would allocate a tuple per frame.  The two live
    in separate slots in `network_runtime` for the same reason -- a shared slot
    would put a type switch in the frame pump.
    """

    def __init__(self, kind, effect_id, entry, duration_ms, panel_base=None):
        lights = _lights()
        self.kind = kind
        self.effect_id = effect_id
        self.name = entry[_NAME]
        self.duration_ms = int(duration_ms)
        self.panel_base = panel_base
        self.done = False
        self.writes = 0
        self.case_level = None
        self.case_levels = None
        self.panel_level = None
        self._case_last = None
        self._panel_last = None
        # ONE `Program` PER CYCLING SEGMENT, BUILT ONCE.  `Program.__init__` is
        # cheap but not free, and a 60 s effect over a 1.35 s cycle would
        # otherwise construct ~44 of them per channel.  GAP and LIT get a None
        # slot: their level is a constant, so there is nothing to build.
        self._case = self._compile(lights, entry[_CYCLE])
        self._case_ms = cycle_ms(entry[_CYCLE])
        panel_cycle = entry[_PANEL]
        # THE PANEL IS SKIPPED ENTIRELY WITHOUT A BASE TO GO BACK TO, and that is
        # a fail-soft rule rather than an optimisation: this player cannot READ
        # the panel (there is no getter on `display.backlight`), so a badge whose
        # runtime could not say what the wearer chose would be left at a
        # brightness the wearer never picked, for the rest of the boot.  Playing
        # the LED half and leaving the panel alone is the honest degradation.
        if panel_cycle is None or panel_base is None:
            self._panel = None
            self._panel_ms = 0
        else:
            self._panel = self._compile(lights, panel_cycle)
            self._panel_ms = cycle_ms(panel_cycle)
        self.panel_active = self._panel is not None
        self._dark = lights.DARK
        self._bright = lights.BRIGHT
        self._panel_for = _panel_levels()

    @staticmethod
    def _compile(lights, cycle):
        """Compile programs or four-channel frames once when a show starts.

        The borrowed patterns become real `caselight_program.Program` objects and
        this player calls their `_level_at`.  ⚠ THAT IS A DELIBERATE REACH INTO A
        PRIVATE NAME, and the alternative is worse: `Program.step` carries its
        own termination and duplicate-suppression state, which is exactly what
        this player owns instead (it loops a cycle under a duration, which a
        `Program` has no concept of).  Re-implementing the ramps here would be a
        second copy of the 2.2-gamma reasoning, and `wave_lights.py` already
        records what happens when that number gets applied twice.
        """
        compiled = []
        for pattern, period_ms, count in cycle:
            length = int(period_ms) * int(count)
            if pattern in SPATIAL_PATTERNS:
                dark = lights.DARK
                bright = lights.BRIGHT
                frames = tuple(
                    tuple(bright if mask & (1 << channel) else dark
                          for channel in range(4))
                    for mask in _SPATIAL_MASKS[pattern])
                compiled.append((frames, length, pattern, int(period_ms)))
            elif pattern in (GAP, LIT):
                compiled.append((None, length, pattern, int(period_ms)))
            else:
                compiled.append(
                    (lights.Program(pattern, period_ms, count), length, pattern,
                     int(period_ms)))
        return tuple(compiled)

    def _level_at(self, compiled, cycle_length, phase):
        """The caselight level for `phase` ms into one pass of a cycle."""
        for program, length, pattern, period_ms in compiled:
            if phase < length:
                if pattern == GAP:
                    return self._dark
                if pattern == LIT:
                    return self._bright
                if pattern in SPATIAL_PATTERNS:
                    # `program` is the immutable frame tuple built in `_compile`;
                    # indexing it keeps the steady frame allocation-free.
                    within = phase % period_ms
                    return program[(within * len(program)) // period_ms]
                return program._level_at(phase)
            phase -= length
        # Only reachable if `cycle_length` and the segments disagree, which
        # `StructureTests` forbids.  Answer DARK rather than raising: a fleet
        # effect must not be the thing that takes a badge down.
        return self._dark

    def step(self, elapsed_ms):
        """Advance to `elapsed_ms` since this badge started the effect.

        Returns True when a case output or `panel_level` holds something to write.
        """
        self.case_level = None
        self.case_levels = None
        self.panel_level = None
        if self.done:
            return False
        if elapsed_ms < 0:
            # A clock that went backwards.  `caselight_program.Program.step`
            # takes the same guard for the same reason: a fixture or a resynced
            # RTC can do this even though `_ticks_diff` handles the wrap.
            elapsed_ms = 0
        if elapsed_ms >= self.duration_ms:
            return self._finish()
        moved = False
        level = self._level_at(self._case, self._case_ms,
                               elapsed_ms % self._case_ms)
        if level != self._case_last:
            self._case_last = level
            if isinstance(level, tuple):
                self.case_levels = level
            else:
                self.case_level = level
            moved = True
        if self._panel is not None:
            panel = self._panel_for[
                self._level_at(self._panel, self._panel_ms,
                               elapsed_ms % self._panel_ms)]
            if panel != self._panel_last:
                self._panel_last = panel
                self.panel_level = panel
                moved = True
        if moved:
            self.writes += 1
        return moved

    def _finish(self):
        """The restore frame: LEDs dark, panel back to the wearer's level.

        ALWAYS EMITTED, EVEN IF IT COSTS TWO WRITES.  `caselight_program` can
        skip its terminal dark frame when the level is already dark; this player
        cannot take that shortcut on the panel, because leaving ~1,000 badges at a
        brightness a show chose is a visible, persistent fault that survives
        until each wearer notices and fixes it by hand.
        """
        self.done = True
        # `interrupt()` can follow a moved `step()` before the caller clears its
        # staged outputs. A restore frame must contain only restore values;
        # otherwise the runtime prefers stale four-channel light data over the
        # scalar DARK staged below and immediately replays the interrupted frame.
        self.case_level = None
        self.case_levels = None
        self.panel_level = None
        moved = False
        if self._case_last != self._dark:
            self._case_last = self._dark
            self.case_level = self._dark
            moved = True
        if self._panel is not None and self._panel_last != self.panel_base:
            self._panel_last = self.panel_base
            self.panel_level = self.panel_base
            moved = True
        if moved:
            self.writes += 1
        return moved

    def interrupt(self):
        """End NOW and stage the restore frame.  Returns True if there is one.

        THE ANSWER TO "an effect is not a modal".  An effect never blocks a
        frame, never consumes a press and never owns the screen, so a wearer is
        never TRAPPED by one -- but a wearer or a newer command can still want
        the channels back, and then the show has to hand them over CLEAN rather
        than merely stop.  Calling this before applying the newer intent means
        the restore frame lands first and the new verb overwrites whatever it
        owns, so the order of the two is not something either side has to think
        about.

        Idempotent: a second call finds `done` already set and nothing staged.
        """
        if self.done:
            self.case_level = None
            self.case_levels = None
            self.panel_level = None
            return False
        return self._finish()


def player_for(payload, panel_base=None):
    """`parse` then :class:`EffectPlayer`, which is what the applier calls."""
    kind, effect_id, duration_ms = parse(payload)
    return EffectPlayer(kind, effect_id, _TABLES[kind][effect_id], duration_ms,
                        panel_base=panel_base)
