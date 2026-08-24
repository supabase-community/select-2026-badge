"""The wearer's brightness: one ladder, one unit conversion, one idle stop.

THIS FILE IS THE CANONICAL COPY.  EDIT IT HERE AND NOWHERE ELSE.

    python3 scripts/sync_ui.py            # refresh every vendored copy
    python3 scripts/sync_ui.py --check    # fail if any has drifted

WHY IT EXISTS.  `docs/design/idle-and-off.md` §3.4 counted the state of the tree
on 2026-08-23: **59 non-comment `display.backlight(...)` call sites, 51 of them a
bare literal, and ZERO cross-file imports of any brightness constant.**  Every
named constant was module-local, there was no `constants.py` anywhere, and the
closest thing to a canonical range lived in Postgres
(`badgelink/supabase/schemas/badgelink.sql:243-248`) rather than in importable
Python.  The idle-dim feature needs a number that two apps and the launcher all
agree on, so it created the home the design record asked for.

WHAT IS MIGRATED, AND WHAT IS NOT.  The idle feature first moved its four seams
here.  The follow-up migration moved twelve more app seams: the shared 85 %
normal level used by the supervisor, Pet, Schedule, all five games, Name Badge
and Profile, plus Glyph's 100 % review level.  SETTINGS WAS ON THAT LIST AND
CAME OFF IT ON 2026-08-24, when the owner moved the brightness row there: an app
that HOSTS the ladder cannot open at a level the ladder did not choose, so it
reads the store like the launcher, `poster` and `badgecard` do.  Measurement probes,
off-roster labs, teardown zeroes, the playground compatibility layer and the
two state-driven identity surfaces remain deliberately unchanged.  Their values
are experimental conditions, blackouts or wearer data rather than app policy.

THE UNIT.  A PERCENT, 0-100, integer.  Chosen because it is what the two things
that PERSIST a brightness already store -- `poster/badge/poster/badge_state.py`
and the archived `identity/badge/identity/identity_model.py` both carry
`brightness: 80` -- so picking the fraction instead would have meant migrating a
saved file format to save a division.  `fraction()` converts at the edge, and the
panel is the only edge there is.

    percent   what the wearer chose and what the store holds      20..100
    fraction  what `display.backlight()` takes                    0.2..1.0

THERE IS A THIRD UNIT AND THIS MODULE DELIBERATELY DOES NOT OWN IT.  BadgeLink's
fleet `set_backlight` command is a 0.1..1 float with a hard floor CONSTRAINED IN
SQL (`badgelink.sql:243-248`, repeated by
`badgelink/badge/badgelink/network_runtime.py:1315-1318`).  Copying that floor
here would make two editable copies of a number whose authority is a CHECK
constraint; `FLEET_FLOOR` below is a cross-reference for a reader, and nothing
in this module reads it.  Its ARGUMENT, though, is load-bearing for the idle dim
and is quoted in the constant's comment.
"""


# The wearer's ladder.  Lifted verbatim from
# `identity/badge/identity/identity_model.py:86-93` -- values, names and the
# reasoning -- because that app is archived and this was the last live copy of a
# product judgement nobody wants to make twice:
#
#   The brightness floor is the LOWEST OFFERED LEVEL, which is the whole
#   argument for it: a value the wearer cannot reach from the UI is a trap, and
#   a value that turns the panel off is a trap you cannot read your way out of.
#   These are product judgements, not measurements; nothing here was timed.
LEVELS = (20, 40, 60, 80, 100)
NAMES = ("DIM", "LOW", "MID", "HIGH", "FULL")
MIN = LEVELS[0]
MAX = LEVELS[-1]

# What a badge nobody has configured runs at.  The same 80 that
# `badge_state.DEFAULT_BRIGHTNESS` and `identity_model.DEFAULT_BRIGHTNESS` both
# already carried -- the design record flagged that pair as "two copies of one
# number, already a drift hazard", and this is the entry that ends it.
DEFAULT = 80

# The steady panel level inherited by the apps that predate the wearer's ladder.
# It is deliberately NOT `DEFAULT`: 0.85 was their established output, while
# `DEFAULT` is the 80 % value persisted for a wearer.  Naming both preserves the
# visible behaviour and makes their different authority explicit.
#
# FOUR APPS DO NOT USE IT, and the number of them is the thing to watch: the
# launcher, `poster`, `badgecard` and (since 2026-08-24) `settings` all open at
# the level stored in `/state/badgecard.json`.  Every app still on this constant
# overrides the wearer's choice for as long as it is open.
NORMAL = 85

# Glyph is a review viewer and deliberately drives the panel at the ladder's
# ceiling.  Derived from the ladder rather than restating 100.
FULL = MAX

# WHAT THE IDLE DIM DIMS TO, and it is the ladder's own floor rather than a new
# number.  Three arguments landed on 20:
#
#   * it is a stop the wearer can also choose by hand, so nothing the idle timer
#     does is a state the UI cannot express;
#   * `benchmark/badge/battery_kit.py:21` already measures `DIM_BRIGHTNESS =
#     0.20`, so the battery arm that quantifies this feature measures the
#     shipped value rather than a neighbour of it;
#   * the ladder's floor exists precisely because a lower one is unreadable, and
#     an idle dim that reads as DEAD has failed at its one job.  That is
#     BadgeLink's 0.1-floor argument -- "a dark panel is indistinguishable from
#     a dead badge to its wearer" -- applied to a screen nobody is touching.
#
# NOTHING HAS JUDGED IT ON GLASS.  `docs/design/idle-and-off.md` §4.1 offers 40
# (`LOW`) as the retreat and says the choice is a look-at-it decision; it is one
# constant and one line to move.
IDLE_PERCENT = LEVELS[0]

# BadgeLink's fleet floor, for a reader who arrives here from that code.  NOT
# read by anything in this module -- see the docstring.
FLEET_FLOOR = 0.1


def clamp(percent):
    """Any number into the offered range, AS AN INT.  Never raises.

    Total because every caller is a panel write or a stored preference, and both
    would rather show a legible screen than propagate a bad value.  A non-number
    -- including the `True` that is an `int` in Python -- resolves to `DEFAULT`
    rather than to an end of the ladder: a wearer whose file was hand-edited to
    a string gets the factory brightness, not the dimmest one.

    ALWAYS AN INT, AND THAT IS A CORRECTION RATHER THAN A CHOICE (2026-08-23).
    This returned whatever it was given while a value was in range, so a stored
    `80.0` came back as `80.0` -- and `card_model.repair` then produced a state
    its own `invariants()` REJECTED, because that check requires an `int`.  A
    total repair whose output fails its own postcondition is the one shape this
    schema exists to make unrepresentable.
    A truncating `int()` is the right conversion for the same reason the ladder
    is integers at all: the percent IS the stored unit, `fraction()` divides by
    100.0 at the panel, and half a percent of backlight is not a thing a wearer
    can see or a UI can express.  It also makes the tree's three readers of a
    stored brightness -- `badge_state.coerce`, `card_model.repair` and the
    launcher's own -- agree on the type as well as the range, which was the
    other half of the same defect: a store holding `55.5` would otherwise have
    given the launcher 55 and the poster the factory 80, and the wearer would
    have watched the panel JUMP across the 45-second handoff.
    """
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        return DEFAULT
    # NaN and the infinities, with the test `badge_state._frac` already uses and
    # the only one that works without `math` on this build.
    if percent != percent or percent * 0 != 0:
        return DEFAULT
    if percent < MIN:
        return MIN
    if percent > MAX:
        return MAX
    return int(percent)


def fraction(percent):
    """The 0.0-1.0 value `display.backlight()` takes, clamped first.

    IT CANNOT RETURN 0, and that is the point rather than an oversight: the
    floor is `MIN`, so nothing that routes a wearer-facing brightness through
    this function can black the panel out.  A genuine blackout is a different
    act with a different reason -- the battery probes' teardown zeroes are the
    only ones in the tree -- and it calls `display.backlight(0)` directly.
    """
    return clamp(percent) / 100.0


def name(percent):
    """The level WORD for any brightness, including one between the rungs.

    `identity_model.brightness_name`, unchanged: it walks the ladder rather than
    indexing it, so a value from a newer build or a hand edit still names the
    rung it is at or above instead of raising.
    """
    best = 0
    for index in range(len(LEVELS)):
        if percent >= LEVELS[index]:
            best = index
    return NAMES[best]


def step(percent, direction):
    """The next offered level in `direction`.  CLAMPED, never wrapping.

    `identity_model.step_brightness`, unchanged, and THE CLAMP IS THE WHOLE OF
    that app's D2 ruling: brightness used to CYCLE on one key, so coming back
    one level from FULL cost four presses and the wearer had to remember the
    order.  As a ladder on two keys it costs one press in either direction --
    and clamping is what makes that literally true, because a wrapping ladder
    puts the far end of the range under the key that is supposed to reverse the
    last change.

    At either end the answer is the value itself, which is how a bar knows to
    draw nothing there: a key that cannot change anything must not be labelled
    as though it could (I5).

    Strictly-above / strictly-below rather than index arithmetic, so a value
    that arrived from a newer build, an import or a hand edit still steps
    somewhere sensible instead of jumping to an end.
    """
    if direction < 0:
        best = LEVELS[0]
        for level in LEVELS:
            if level < percent:
                best = level
        return best
    for level in LEVELS:
        if level > percent:
            return level
    return LEVELS[-1]
