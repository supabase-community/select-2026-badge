"""Parametric caselight primitives, driven one frame at a time.

WHAT THIS IS NOT is the design. It is not an animation and it never sleeps: a
blocking light show inside ``/system/main.py``'s frame pump would stall the
launcher and every app for its whole duration, and the PW rule is that
networking may degrade and may never take down the badge. So a program is a pure
function of ELAPSED MILLISECONDS, the frame pump asks it for one level per frame,
and the badge stays interactive throughout.

FOUR PRIMITIVES AND NO SCRIPTS, which is the constraint's shape too
(``badge_commands_set_lights_payload_check``): ``flash``, ``breathe``, ``strobe``
and ``off``, with a bounded ``period_ms`` (100..60000) and ``count`` (1..64).
Every one of them TERMINATES, and that is a fleet property rather than tidiness:
``set_lights`` is a fleet-scope command, so a primitive that could run forever is
800 badges nobody can turn off without another command reaching every one of
them.

THE STEADY FRAME ALLOCATES NOTHING. Every level a program can return is an
element of the module-level :data:`LEVELS` tuple, chosen by integer arithmetic, so
a frame produces no float and no tuple. :meth:`Program.step` also returns ``None``
whenever the level has not changed, which is the same duplicate-suppression every
app in this repository already applies to ``badge.caselights`` -- a direct write
is 252.5 us median (100-write device measurement, ``snake/README.md``) against an
~11.4 ms VSYNC quantum, so it is affordable per frame and still not free.

THE FIRMWARE APPLIES ITS OWN 2.2 GAMMA (``badge.caselights`` is
``duty_u16(int(level ** 2.2 * 65535))``), so the request axis is already
perceptual and a linear ramp here IS the even fade. ``glyph/badge/glyph/
wave_lights.py`` records the same rule and warns that correcting twice is wrong.

TIME IS THE CALLER'S PROBLEM, deliberately. This module takes ``elapsed_ms`` and
imports nothing, so ``time.ticks_ms`` wrap-around is handled in exactly one place
(``network_runtime``'s ``_ticks_diff``) rather than two, and the whole module is
testable by passing integers.
"""


FLASH = "flash"
BREATHE = "breathe"
STROBE = "strobe"
OFF = "off"

# The constraint's four, in its own order.
PATTERNS = (FLASH, BREATHE, STROBE, OFF)

# `badge_commands_set_lights_payload_check`'s bounds, character for character.
PERIOD_MIN_MS = 100
PERIOD_MAX_MS = 60000
COUNT_MIN = 1
COUNT_MAX = 64

# What an absent optional key means. The constraint allows both to be omitted, so
# the badge has to have an answer; these are it. One second and three cycles is a
# noticeable, obviously-deliberate blink that is over in three seconds -- the
# right default for a command whose most likely use is "which badge is Sam's".
DEFAULT_PERIOD_MS = 1000
DEFAULT_COUNT = 3

# How long the bright part of a `strobe` lasts, regardless of period. A strobe is
# a SHORT pulse with a long gap; scaling the pulse with the period would make a
# 60 s strobe a 30 s floodlight.
STROBE_ON_MS = 40

# The quantization of `breathe`, and the reason the steady frame allocates
# nothing: every level is an element of this tuple. Sixteen steps at the
# firmware's 2.2 gamma is finer than the eye resolves on four white LEDs behind a
# case, and it collapses a 1000 ms ramp from ~44 writes at 44 FPS to at most 32.
LEVEL_STEPS = 16
LEVELS = (
    0.0, 0.0625, 0.125, 0.1875, 0.25, 0.3125, 0.375, 0.4375,
    0.5, 0.5625, 0.625, 0.6875, 0.75, 0.8125, 0.875, 0.9375, 1.0,
)

DARK = LEVELS[0]
BRIGHT = LEVELS[LEVEL_STEPS]


def valid_period(value):
    """The constraint's ``period_ms`` verdict.

    ``jsonb_typeof = 'number'``, ``~ '^[0-9]{1,7}$'`` on the text form, and
    ``between 100 and 60000``. The regex is what rejects a sign and a decimal
    point, so an ``int`` is the exact mirror.

    A float is accepted when it is exactly integral, and that is DELIBERATELY
    LOOSER than the constraint in one direction only: JSON ``1e3`` decodes to
    ``1000.0`` in Python and renders as ``1000`` in jsonb, so it passes the CHECK
    and must not be refused here. ``1000.5`` fails both. Being loose where the
    constraint is tight is harmless -- the row cannot exist -- while being tight
    where the constraint is loose leaves a queued command that can never succeed.
    """

    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return PERIOD_MIN_MS <= value <= PERIOD_MAX_MS
    if isinstance(value, float):
        if value != value or value * 0 != 0:      # NaN, +/-inf, without math
            return False
        if value != int(value):
            return False
        return PERIOD_MIN_MS <= int(value) <= PERIOD_MAX_MS
    return False


def valid_count(value):
    """The constraint's ``count`` verdict: the same shape, 1..64."""

    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return COUNT_MIN <= value <= COUNT_MAX
    if isinstance(value, float):
        if value != value or value * 0 != 0:
            return False
        if value != int(value):
            return False
        return COUNT_MIN <= int(value) <= COUNT_MAX
    return False


def parse(payload):
    """One ``set_lights`` payload -> ``(pattern, period_ms, count)``, or raise.

    Mirrors ``badge_commands_set_lights_payload_check`` clause for clause,
    including the two the FT-S container run proved were needed:

    * ``payload ? 'pattern'`` FIRST. Without it ``jsonb_typeof(payload ->
      'pattern')`` is SQL NULL, a CHECK PASSES on NULL, and ``{}`` and
      ``{"count": 3}`` were both accepted until a real Postgres said so.
    * ``off`` is an EXACT OBJECT (``payload = jsonb_build_object('pattern',
      'off')``), so ``{"pattern": "off", "count": 3}`` is a rejection rather than
      a count nobody uses.
    """

    if not isinstance(payload, dict):
        raise ValueError("set_lights payload must be an object")
    if "pattern" not in payload:
        raise ValueError("set_lights payload requires a pattern")
    pattern = payload["pattern"]
    if not isinstance(pattern, str) or pattern not in PATTERNS:
        raise ValueError("set_lights pattern must be one of the four primitives")
    keys = set(payload.keys())
    if pattern == OFF:
        if keys != set(("pattern",)):
            raise ValueError("set_lights off takes no parameters")
        return (OFF, PERIOD_MIN_MS, COUNT_MIN)
    if not keys <= set(("pattern", "period_ms", "count")):
        raise ValueError("set_lights payload carries an unknown key")
    period = payload.get("period_ms", DEFAULT_PERIOD_MS)
    if "period_ms" in payload and not valid_period(period):
        raise ValueError("set_lights period_ms must be 100..60000")
    count = payload.get("count", DEFAULT_COUNT)
    if "count" in payload and not valid_count(count):
        raise ValueError("set_lights count must be 1..64")
    return (pattern, int(period), int(count))


class Program:
    """One running primitive.  Ask it for a level once per frame.

    ``step(elapsed_ms)`` returns a level to write, or ``None`` when the level has
    not changed since the last write. ``done`` is ``True`` once the program has
    emitted its final dark frame; a finished program answers ``None`` forever, so
    a caller that forgets to drop it costs nothing.
    """

    def __init__(self, pattern, period_ms=DEFAULT_PERIOD_MS, count=DEFAULT_COUNT):
        if pattern not in PATTERNS:
            raise ValueError("unknown caselight pattern: {}".format(pattern))
        self.pattern = pattern
        self.period_ms = int(period_ms)
        self.count = int(count)
        # `off` is a single dark frame, not a cycle.
        self.total_ms = 0 if pattern == OFF else self.period_ms * self.count
        self.done = False
        self.writes = 0
        self._last = None

    def _level_at(self, elapsed_ms):
        pattern = self.pattern
        if pattern == OFF:
            return DARK
        phase = elapsed_ms % self.period_ms
        if pattern == FLASH:
            # Half on, half off. `>>` rather than `//` because the period is an
            # int and this runs every frame.
            return BRIGHT if phase < (self.period_ms >> 1) else DARK
        if pattern == STROBE:
            return BRIGHT if phase < STROBE_ON_MS else DARK
        # BREATHE: a linear triangle in REQUEST space, which is the even fade
        # because the firmware applies the 2.2 gamma itself. Integer arithmetic
        # into the LEVELS table, so no float is created.
        half = self.period_ms >> 1
        if half < 1:
            return BRIGHT
        if phase < half:
            index = (phase * LEVEL_STEPS) // half
        else:
            index = ((self.period_ms - phase) * LEVEL_STEPS) // half
        if index < 0:
            index = 0
        elif index > LEVEL_STEPS:
            index = LEVEL_STEPS
        return LEVELS[index]

    def step(self, elapsed_ms):
        """The level for this frame, or ``None`` for "nothing to write"."""

        if self.done:
            return None
        if elapsed_ms < 0:
            # A clock that went backwards (ticks wrap handled by the caller, but
            # a fixture or a resynced RTC can still do this): treat it as frame
            # zero rather than indexing off the front of the ramp.
            elapsed_ms = 0
        if elapsed_ms >= self.total_ms:
            self.done = True
            if self._last == DARK:
                # Already dark: terminating costs no write at all.
                return None
            self._last = DARK
            self.writes += 1
            return DARK
        level = self._level_at(elapsed_ms)
        if level == self._last:
            return None
        self._last = level
        self.writes += 1
        return level


def program_for(payload):
    """``parse`` then :class:`Program`, which is what the applier calls."""

    pattern, period_ms, count = parse(payload)
    return Program(pattern, period_ms, count)
