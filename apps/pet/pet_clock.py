"""Wall-clock policy for the Pet.  Pure: decides elapsed time, never simulates.

Badges power on with wrong clocks, so this module exists to answer exactly one
question - "how many seconds of simulation does this app open owe?" - and to
answer it defensively.  `pet_model.advance` then applies that number and knows
nothing about epochs at all.

THIS MODULE ALSO OWNS SPEED.  Fast mode is implemented HERE and nowhere else: a
creature's `fast` flag selects an INTEGER multiplier (`model.speed_of`) and both
entry points return REAL seconds multiplied by it.  Nothing in `pet_model`
changes, so every rate, threshold and product promise still holds verbatim in
SIMULATED time - fast mode is the same game with a shorter second, not a second
balance to tune.  Additivity survives because the multiplier is an integer:
sum(a_i * S) == S * sum(a_i) exactly, for any partition.

UNITS TRAP, and it is the new version of the ordering trap below: what these
functions RETURN is SIMULATED seconds, while `last_seen` is a WALL-CLOCK epoch
advanced by REAL seconds.  The two are equal only at 1x.  A future caller that
treats `open_delta`'s first value as real time will be silently FAST_SPEED times
wrong.

ORDERING TRAP, stated once so nobody has to rediscover it: `last_seen` is owned
HERE and nowhere else.  `advance` never touches it.  Every forward case now
rebases to `now_s` (identical to adding the real gap at 1x, and the only correct
answer at any other speed); the two cases that return None - a clock set
backwards, and a clamped baseline - return zero elapsed and deliberately keep
the later baseline, so a clock set backwards can neither kill nor supercharge
the creature.
"""

from pet_tuning import MIN_VALID_EPOCH, BACKWARD_REBASE_S

import pet_model as model


def clock_valid(now_s):
    """Only a display hint ("CLOCK NOT SET"), never a gate on play.

    The decided rule is that decay depends on DELTAS, so a running-but-wrong
    clock must play normally.  The previous build refused to decay at all below
    this epoch, which left a badge whose RTC reads 2021 frozen and unplayable -
    and, worse, unable to ever un-pause.
    """
    return model._int(now_s, 0) >= MIN_VALID_EPOCH


def open_delta(state, now_s):
    """Six explicit cases.  Returns (SIMULATED elapsed_s, events, rebase_or_None).

    The cap is the ruling on THE RECONSTRUCTION TRAP.  At FAST_SPEED, six real
    minutes with the app closed would be ten simulated hours, so an uncapped
    reconstruction would land every reopen on a paused pet and kill the care
    loop instead of speeding it up.  A fast creature therefore reconstructs at
    most FAST_CATCHUP_S simulated seconds from a CLOSED app - enough to come
    back hungry, messy and one stage older, never enough to come back grey
    unless it was already dying.  `session_tick` is uncapped, so a pause still
    fires while somebody is holding the badge, which is where it belongs.  Real
    mode keeps its 7-day clamp exactly.
    """
    now_s = model._int(now_s, 0)
    last_seen = model._int(state.get("last_seen"), 0)
    events = []
    speed = model.speed_of(state)
    cap = model.catchup_s(state)

    if not clock_valid(now_s):
        # The RTC has never been set.  Play anyway, from this baseline onward:
        # deltas against a wrong-but-ticking clock are still real elapsed time.
        events.append("clock_invalid")
        if last_seen <= 0 or last_seen > now_s:
            return 0, events, now_s
        gap = closed_elapsed(gap_of(now_s, last_seen), speed, cap, events)
        return gap, events, now_s

    if last_seen < MIN_VALID_EPOCH:
        # A save made while the clock was unset. Adopt the good clock, no decay.
        events.append("clock_rebased")
        return 0, events, now_s

    if now_s < last_seen:
        if last_seen - now_s > BACKWARD_REBASE_S:
            # Two days in the future is not a user setting the clock back; it is
            # a dead RTC that came up high.  Without this the pet freezes forever.
            events.append("clock_rebased")
            return 0, events, now_s
        # Clamp negative elapsed and KEEP the later baseline, so a clock set
        # backwards can neither kill nor supercharge the creature.
        events.append("clock_backward")
        return 0, events, None

    return closed_elapsed(gap_of(now_s, last_seen), speed, cap, events), events, now_s


def gap_of(now_s, last_seen):
    gap = now_s - last_seen
    return gap if gap > 0 else 0


def closed_elapsed(gap, speed, cap, events):
    """SIMULATED seconds owed for time the app was CLOSED.

    A CLOSED APP IS UNATTENDED BY DEFINITION, so it reconstructs at REAL TIME,
    exactly as an open-but-untouched app already does.  `speed` is accepted and
    ignored, so the call site still reads as the place speed would apply.

    THE BUG THIS FIXES.  This used to charge `gap * speed`.  With the cap that
    meant EVERY closed gap over 180 real seconds reconstructed to exactly
    FAST_CATCHUP_S - measured: 181 s, 1 h, 8 h, 3 days and 21 days all returned
    21600 s.  Simulated lifetime therefore scaled with the NUMBER OF OPENS
    rather than with elapsed time: four opens a day aged a creature 24 simulated
    hours, twelve opens aged it 72.  So checking on your pet more often made it
    older and worse, and pressing HOME instead of wearing the badge scored
    better - the app punished both of the ways it is meant to be used, which is
    how two independent playtests reached opposite-sounding headlines from this
    one line.

    The ceiling stays, and must: neglect pauses at roughly 11-12 simulated
    hours, so an uncapped closed clock would pause every fast badge overnight.
    """
    if gap > cap:
        # Bounds the step loop.  Seven days of neglect pauses many times over,
        # so a three-week gap and a seven-day gap reach the identical outcome.
        events.append("gap_clamped")
        return cap
    return gap


def open_session(state, now_s):
    """The one call an app makes on open.  Returns (state, events, report)."""
    elapsed, events, rebase = open_delta(state, now_s)
    state, report = model.advance(state, elapsed)
    if rebase is not None:
        state["last_seen"] = rebase
    # Order is the console contract the browser and device lanes assert against:
    # clock verdict first, then "decayed" whenever any time was applied at all,
    # then whatever the simulation reported, then the Ant warning.
    if elapsed > 0:
        events.append("decayed")
    events = events + report["events"]
    if state["state"] == model.ALIVE and state["health"] <= model.LOW_HEALTH_T:
        events.append("low")
    return state, events, report


def session_tick(state, seconds, speed=None):
    """Advance an open session by whole seconds measured from `time.ticks_ms`.

    Wall time is read exactly once per session, at open.  Everything after that
    comes from the monotonic tick counter, so a dead RTC still produces a
    creature that visibly ages while you watch it and the playground's virtual
    clock reproduces the device exactly.
    """
    seconds = model._int(seconds, 0)
    if seconds <= 0:
        return state, model.new_report()
    # `speed` is the ATTENTION CLOCK, and it is passed in rather than read here
    # on purpose.  The multiplier has to be chosen by whoever knows when the
    # last key was pressed - the controller - while this module keeps owning
    # `last_seen`.  Defaulting to the creature's own speed keeps every direct
    # caller, including the additivity tests, behaving exactly as before.
    if speed is None:
        speed = model.speed_of(state)
    speed = model._int(speed, 1)
    if speed < 1:
        speed = 1
    state, report = model.advance(state, seconds * speed)
    state["last_seen"] = model._int(state.get("last_seen"), 0) + seconds
    return state, report
