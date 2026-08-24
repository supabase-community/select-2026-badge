"""Pure reconstructive care simulation for the database Pet.

THE LAW OF THIS FILE: it never reads a clock, never calls random, never imports
Badgeware and never touches a file.  Its only time entry point is

    advance(state, elapsed_s) -> (state, report)

a pure function of (state, elapsed seconds).  `pet_clock` decides what
`elapsed_s` is, `pet_store` serialises, `pet_app` sequences frames and
`pet_view` draws.  That split is what lets the whole simulation be tested under
CPython with no device and no browser.

WHY RECONSTRUCTIVE.  The 1990s handheld care toys were event driven: the toy
beeped and you answered within minutes.  This badge has no audio, no background
ticking and no notifications, so an event can never be delivered - it can only be
RECONSTRUCTED when the app is next opened.  Every mechanic here is therefore
expressible as f(state, elapsed).  Sleep is fatigue derived rather than nightly,
sickness is a deterministic pressure integral rather than a dice roll, and
"what happened while I was away" becomes the app's signature moment.

WHY INTEGERS.  Stats are integer tenths (0..1000) and time is integer seconds.
RP2350 MicroPython floats are single precision and CPython's are double; the
browser playground reproduces the device width on purpose.  Integers make all
three lanes agree exactly, so the fast lane is a real oracle for the device.

WHY A FIXED STEP.  `advance` accumulates elapsed seconds into `sim_carry` and
runs `carry // SIM_STEP_S` whole steps, keeping the remainder.  Any partition of
the same total elapsed time therefore produces the identical step sequence, so

    advance(s, a); advance(s, b)  ==  advance(s, a + b)

exactly, for every field.  That property is asserted in the test suite and is the
backbone of the whole design.
"""

from pet_tuning import *  # noqa: F401,F403  - dials only, deliberately wildcard


SCHEMA = 2

ALIVE = "alive"
PAUSED = "paused"
RESTORING = "restoring"
VALID_STATES = (ALIVE, PAUSED, RESTORING)

# The fixed care ring.  Order never changes, so muscle memory survives a
# three-day wear; unavailable entries are drawn dimmed rather than removed.
FEED = "feed"
PLAY = "play"
CLEAN = "clean"
HEAL = "heal"
REST = "rest"
SCOLD = "scold"
RING = (FEED, PLAY, CLEAN, HEAL, REST, SCOLD)

# Everything `apply` accepts.  Tests and the fuzzer enumerate this rather than
# naming actions literally, so a new action cannot be added without a ruling for
# every state.
RESTORE = "restore"
HATCH = "hatch"
PLAY_WIN = "play_win"
PLAY_LOSS = "play_loss"
ACTIONS = (FEED, CLEAN, HEAL, REST, SCOLD, PLAY_WIN, PLAY_LOSS, RESTORE, HATCH)

# Needs that decay and are displayed as meters.
NEEDS = ("data", "mood", "fatigue", "discipline")

STAGE_NAMES = ("EGG", "SEED", "DEV", "BRANCH", "STAGING", "ADULT")
FORM_NAMES = ("HA PROD", "PROD", "LEGACY")

# Thirteen faces the SIMULATION can ask for, in the order `mood_name` tests
# them.  Every one of these distinctions was already modelled and thrown away by
# a face set that could only say happy / neutral / sad / sick.
MOODS = ("paused", "wink", "asleep", "verysick", "sick", "angry", "grossed",
         "dying", "ecstatic", "hungry", "happy", "neutral", "sad")

# Event log codes.  Stored as ints so the save stays small and the strings can
# be reworded without migrating anything.
LOG_HATCHED = 1
LOG_STAGE = 2
LOG_SICK = 3
LOG_CURED = 4
LOG_SLEPT = 5
LOG_WOKE = 6
LOG_MISBEHAVED = 7
LOG_SCOLDED = 8
LOG_PAUSED = 9
LOG_RESTORED = 10
LOG_OVERFED = 11
LOG_MISTAKE = 12
LOG_CLEANED = 13
LOG_PLAYED = 14
LOG_AUTOVACUUM = 15
LOG_MAX = 8

LOG_TEXT = {
    LOG_HATCHED: "PROJECT CREATED",
    LOG_STAGE: "EVOLVED",
    LOG_SICK: "GOT SICK",
    LOG_CURED: "ROLLED BACK",
    LOG_SLEPT: "SCALED TO ZERO",
    LOG_WOKE: "WOKE UP",
    LOG_MISBEHAVED: "UNRESTRICTED",
    LOG_SCOLDED: "RLS ENABLED",
    LOG_PAUSED: "PROJECT PAUSED",
    LOG_RESTORED: "RESTORED",
    LOG_OVERFED: "DEAD TUPLES",
    LOG_MISTAKE: "INCIDENT",
    LOG_CLEANED: "VACUUMED",
    LOG_PLAYED: "QUERY PLANNED",
    LOG_AUTOVACUUM: "AUTOVACUUM",
}


# --------------------------------------------------------------------------
# repair: total, never raises
# --------------------------------------------------------------------------

def _int(value, fallback):
    """Parse an integer without an intermediate float.

    MicroPython's float is single precision on RP2350, so routing a current epoch
    timestamp through float discards roughly minute-sized chunks.  A previous
    build failed an exact five-minute restore on hardware for exactly this
    reason; every timestamp and counter stays an integer end to end.
    """
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def _stat(value, fallback):
    return _clamp(_int(value, fallback), 0, MAX)


def _counter(value):
    return _clamp(_int(value, 0), 0, 999999999)


def mode_of(state):
    """0 = real time, 1 = fast.  A property of the creature, chosen at birth."""
    return 1 if _int(state.get("fast"), FAST_DEFAULT) else 0


def speed_of(state):
    return SPEED_BY_MODE[mode_of(state)]


def restore_s(state):
    return RESTORE_S_BY_MODE[mode_of(state)]


def feed_window_s(state):
    return FEED_WINDOW_S_BY_MODE[mode_of(state)]


def wake_grace_s(state):
    return WAKE_GRACE_S_BY_MODE[mode_of(state)]


def news_min_away_s(state):
    return NEWS_MIN_AWAY_BY_MODE[mode_of(state)]


def catchup_s(state):
    return CATCHUP_S_BY_MODE[mode_of(state)]


def new_state(health=MAX, last_seen=0, fast=FAST_DEFAULT):
    """A fresh egg.  `last_seen` is whatever the caller's clock reads, or 0."""
    return {
        "schema": SCHEMA,
        "state": ALIVE,
        "fast": 1 if fast else 0,
        # meters, tenths
        "health": _stat(health, MAX),
        "data": MAX,
        "mood": MAX,
        "fatigue": 0,
        "discipline": DISCIPLINE_START_T,
        # integration carries, so any partition of elapsed time is exact
        "health_c": 0,
        "data_c": 0,
        "mood_c": 0,
        "fatigue_c": 0,
        "discipline_c": 0,
        "waste_c": 0,
        "sick_c": 0,
        "worsen_c": 0,
        "misbehave_c": 0,
        "sim_carry": 0,
        # discrete conditions
        "waste": 0,
        "waste_p": 0,
        "autovac_s": 0,
        "sick": 0,
        "sick_p": 0,
        "worsen_p": 0,
        "asleep": 0,
        "scheduled": 0,
        "sleep_s": 0,
        "misbehaving": 0,
        "misbehave_p": 0,
        # growth
        "stage": 0,
        "form": 0,
        "age_s": 0,
        # countdowns, exact seconds, decremented outside the quantised step loop
        "restore_left_s": 0,
        "feed_left_s": 0,
        "feed_streak": 0,
        "play_cd_s": 0,
        # care mistakes: rearming grace timers, seconds
        "mistakes": 0,
        "m_data_s": 0,
        "m_mood_s": 0,
        "m_waste_s": 0,
        "m_sick_s": 0,
        "m_mis_s": 0,
        # lifetime counters and log
        "pauses": 0,
        "total_feeds": 0,
        "total_plays": 0,
        "total_cleans": 0,
        "total_heals": 0,
        "log": [],
        "last_seen": _int(last_seen, 0),
    }


def repair(value, last_seen=0):
    """Coerce anything at all into a representable state.  Never raises.

    Deliberately total: `pet_store` needs to tell "unreadable bytes" apart from
    "readable but wrong shape", and the fuzzer needs a function it can throw
    nulls, strings and NaN-ish values at without a try/except around every call.
    """
    result = new_state(MAX, last_seen)
    if not isinstance(value, dict):
        return result
    # FIRST: the speed decides three of the clamps below.
    # A SAVE THAT PREDATES THE CLOCK CHOICE IS A REAL-TIME CREATURE.  A fresh
    # badge starts fast (new_state), but silently multiplying an existing
    # three-day pet by FAST_SPEED would pause it minutes after an update.
    result["fast"] = 1 if _int(value.get("fast"), 0) else 0

    for key in ("health", "data", "mood", "fatigue", "discipline",
                "waste_p", "sick_p", "worsen_p", "misbehave_p"):
        if key in value:
            result[key] = _stat(value.get(key), result[key])
    for key in ("health_c", "data_c", "mood_c", "fatigue_c", "discipline_c",
                "waste_c", "sick_c", "worsen_c", "misbehave_c"):
        result[key] = _clamp(_int(value.get(key), 0), 0, 3599)
    result["sim_carry"] = _clamp(_int(value.get("sim_carry"), 0), 0, SIM_STEP_S - 1)

    result["waste"] = _clamp(_int(value.get("waste"), 0), 0, WASTE_MAX)
    # SECONDS, not per-mille, so it is bounded by its own dial rather than by
    # the 0..MAX group above.
    result["autovac_s"] = _clamp(_int(value.get("autovac_s"), 0),
                                 0, AUTOVACUUM_AFTER_S)
    result["sick"] = _clamp(_int(value.get("sick"), 0), 0, 2)
    result["asleep"] = 1 if _int(value.get("asleep"), 0) else 0
    result["scheduled"] = 1 if _int(value.get("scheduled"), 0) else 0
    result["sleep_s"] = _clamp(_int(value.get("sleep_s"), 0), 0, 4 * 86400)
    result["misbehaving"] = 1 if _int(value.get("misbehaving"), 0) else 0

    result["stage"] = _clamp(_int(value.get("stage"), 0), 0, STAGE_COUNT - 1)
    result["form"] = _clamp(_int(value.get("form"), 0), 0, len(FORM_NAMES) - 1)
    result["age_s"] = _counter(value.get("age_s"))

    result["restore_left_s"] = _clamp(_int(value.get("restore_left_s"), 0), 0,
                                      restore_s(result))
    result["feed_left_s"] = _clamp(_int(value.get("feed_left_s"), 0), 0,
                                   feed_window_s(result))
    result["feed_streak"] = _clamp(_int(value.get("feed_streak"), 0), 0, 32)
    result["play_cd_s"] = _clamp(_int(value.get("play_cd_s"), 0), 0, PLAY_COOLDOWN_S)

    result["mistakes"] = _clamp(_int(value.get("mistakes"), 0), 0, MISTAKE_MAX)
    for key in ("m_data_s", "m_mood_s", "m_waste_s", "m_sick_s", "m_mis_s"):
        result[key] = _clamp(_int(value.get(key), 0), 0, 4 * 86400)

    for key in ("pauses", "total_feeds", "total_plays", "total_cleans", "total_heals"):
        result[key] = _counter(value.get(key))

    result["log"] = _repair_log(value.get("log"))
    result["last_seen"] = _int(value.get("last_seen"), result["last_seen"])

    name = value.get("state")
    result["state"] = name if name in VALID_STATES else ALIVE
    return _settle(result)


def _repair_log(value):
    log = []
    if isinstance(value, (list, tuple)):
        for entry in value:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            code = _int(entry[0], 0)
            if code not in LOG_TEXT:
                continue
            log.append([code, _counter(entry[1])])
    return log[-LOG_MAX:]


def _settle(state):
    """Enforce the cross-field invariants after any mutation."""
    if state["state"] == PAUSED:
        state["health"] = 0
        state["restore_left_s"] = 0
        state["asleep"] = 0
        state["misbehaving"] = 0
    elif state["state"] == RESTORING:
        state["health"] = 0
        state["asleep"] = 0
        state["misbehaving"] = 0
        if state["restore_left_s"] <= 0:
            state["restore_left_s"] = restore_s(state)
    else:
        state["restore_left_s"] = 0
        if state["health"] <= 0:
            state["health"] = 0
            state["state"] = PAUSED
            state["asleep"] = 0
            state["misbehaving"] = 0
    if state["stage"] == 0:
        # An egg is inert: it has no needs and cannot misbehave.
        state["asleep"] = 0
        state["misbehaving"] = 0
    if not state["asleep"]:
        # The sleep clock only exists inside a sleep, so an awake creature can
        # never carry a stale one into its next nap.
        state["sleep_s"] = 0
    if state["feed_left_s"] <= 0:
        state["feed_streak"] = 0
    return state


def invariants(state):
    """Raise on any violation.  Called after every step in tests, never on device."""
    if state["state"] not in VALID_STATES:
        raise AssertionError("bad state name %r" % (state["state"],))
    for key in ("health", "data", "mood", "fatigue", "discipline",
                "waste_p", "sick_p", "worsen_p", "misbehave_p"):
        value = state[key]
        if not isinstance(value, int) or isinstance(value, bool):
            raise AssertionError("%s is not an int: %r" % (key, value))
        if not 0 <= value <= MAX:
            raise AssertionError("%s out of range: %r" % (key, value))
    if not 0 <= state["autovac_s"] <= AUTOVACUUM_AFTER_S:
        raise AssertionError("autovac_s out of range: %r" % (state["autovac_s"],))
    if not 0 <= state["waste"] <= WASTE_MAX:
        raise AssertionError("waste out of range")
    if not 0 <= state["sick"] <= 2:
        raise AssertionError("sick out of range")
    if not 0 <= state["stage"] < STAGE_COUNT:
        raise AssertionError("stage out of range")
    if not 0 <= state["sim_carry"] < SIM_STEP_S:
        raise AssertionError("sim_carry out of range")
    if state["state"] != RESTORING and state["restore_left_s"] != 0:
        raise AssertionError("restore countdown outside restoring")
    if not state["asleep"] and state["sleep_s"] != 0:
        raise AssertionError("sleep clock running while awake")
    if state["state"] != ALIVE and state["health"] != 0:
        raise AssertionError("health must be zero unless alive")
    if state["state"] == ALIVE and state["health"] <= 0:
        raise AssertionError("alive with no health")
    if len(state["log"]) > LOG_MAX:
        raise AssertionError("log too long")
    return True


# --------------------------------------------------------------------------
# derived reads
# --------------------------------------------------------------------------

def _deficit(value):
    """0 at or above COMFORT, rising linearly to 1000 permille at empty."""
    if value >= COMFORT_T:
        return 0
    return (COMFORT_T - value) * 1000 // COMFORT_T


def strain(state):
    """Total care pressure, 0..1000 permille.  The weights sum to exactly 1000."""
    if state["stage"] == 0:
        return 0
    waste_term = state["waste"] * 1000 // WASTE_MAX
    if waste_term > 1000:
        waste_term = 1000
    total = (
        W_DATA * _deficit(state["data"])
        + W_MOOD * _deficit(state["mood"])
        + W_WASTE * waste_term
        + W_SICK * (1000 if state["sick"] else 0)
    )
    return _clamp(total // 1000, 0, 1000)


def health_rate_t(state):
    """Health change in tenths per hour right now: the screen's most useful number.

    A status app whose headline number is an integral is opaque unless the
    derivative is on screen too.  Printing "-21/H" beside the bar turns "why is
    it dying" into a fact readable at arm's length in two seconds.
    """
    if state["state"] != ALIVE or state["stage"] == 0:
        return 0
    pressure = strain(state)
    if state["asleep"]:
        regen = REGEN_T * (REGEN_SCHEDULED_MULT if state["scheduled"] else REGEN_UNPLANNED_MULT) // 1000
        decay = DECAY_T * SLEEP_DECAY_MULT // 1000
    else:
        regen = REGEN_T
        decay = DECAY_T
    return (regen * (1000 - pressure) - decay * pressure) // 1000


def mood_name(state):
    """The face, from state the model already keeps.

    THIS IS A READ, NOT A MECHANIC: a pure function of the fields above, so it
    costs nothing to store and cannot affect additivity.  The previous set
    collapsed distinctions the simulation was already making - a second dose of
    sickness looked like the first, a full waste bin showed on the floor but not
    on the face, a starving creature with good health read "happy", and a pet at
    5% health looked exactly like one at 34%.  Each branch below is a state the
    player can act on, in the order that decides which one wins.
    """
    if state["state"] != ALIVE:
        return "paused"
    if state["stage"] == 0:
        return "wink"
    if state["asleep"]:
        return "asleep"
    if state["sick"] >= 2:
        return "verysick"
    if state["sick"]:
        return "sick"
    if state["misbehaving"]:
        return "angry"
    if state["waste"] >= WASTE_MAX:
        return "grossed"
    if state["health"] <= LOW_HEALTH_T // 2:
        return "dying"
    if state["health"] > 900 and state["mood"] > 900:
        return "ecstatic"
    if state["data"] < 300:
        return "hungry"
    if state["health"] > 650 and state["mood"] > 500:
        return "happy"
    if state["health"] > LOW_HEALTH_T:
        return "neutral"
    return "sad"


def stage_name(state):
    if state["stage"] >= STAGE_COUNT - 1:
        return FORM_NAMES[state["form"]]
    return STAGE_NAMES[state["stage"]]


def care_grade(state):
    """A, B or C.  The thresholds are the adult-form thresholds exactly, so the
    player can see which grown-up form is coming before it arrives."""
    if state["mistakes"] <= ADULT_HA_MAX_MISTAKES:
        return "A"
    if state["mistakes"] <= ADULT_PROD_MAX_MISTAKES:
        return "B"
    return "C"


def db_size_mb(state):
    """A cosmetic readout only.  Weight existed in the originals to make
    overfeeding and exercise matter; here waste and bloat already do that, so
    size is a joke on the STATS screen rather than a mechanic."""
    return 8 + state["total_feeds"] * 3 + state["age_s"] * 3 // 7200


def available(state, action):
    """Can this ring entry be committed right now, and if not, why not."""
    if state["state"] != ALIVE:
        return False, "PAUSED"
    if state["stage"] == 0:
        return False, "EGG"
    if action in (FEED, PLAY, SCOLD) and state["asleep"]:
        return False, "SLEEPING"
    if action == FEED and state["data"] >= MAX:
        # THE DEFECT THIS CLOSES.  Without it, a brand-new creature - which
        # hatches at DATA 1000 - has FEED available, so `suggest` parks on it,
        # the ring never dims it and key B reads FEED.  Eight presses of the
        # app's own recommendation made a healthy newborn sick.  Measured: the
        # button-masher's death moved from 190 s to 280 s with this one line.
        #
        # Postgres has no "table full" condition; an INSERT that collides with
        # what is already there raises 23505, `duplicate key value violates
        # unique constraint`.  That is both what the model means and what the
        # audience has actually seen at 2am.
        return False, "DUPLICATE KEY"
    if action == HEAL and not state["sick"]:
        return False, "NOT SICK"
    if action == SCOLD and not state["misbehaving"]:
        return False, "BEHAVING"
    if action == REST and not state["asleep"] and state["fatigue"] < REST_MIN_FATIGUE_T:
        return False, "NOT TIRED"
    if action == PLAY and state["play_cd_s"] > 0:
        return False, "WAIT"
    return True, ""


def ring_label(state, action):
    """The word above key B.  It must name what the press will actually do.

    REST is a three-way toggle, so it needs three words: an unplanned outage is
    BOOKed into a maintenance window, a booked sleep is WAKEn, and an awake and
    tired creature is put to REST.  The old label said REST for two of those.
    """
    if action == REST and state["asleep"]:
        return "WAKE" if state["scheduled"] else "BOOK"
    if action == SCOLD:
        # The sprite is already a policy shield and the toast already says RLS
        # ENABLED - only the word was still parenting vocabulary in a database
        # costume.  18 px against the 34 px budget, the narrowest label here.
        return "RLS"
    return action.upper()


def suggest(state):
    """Index into RING of the action this visit most needs.

    Parking the cursor here on SCREEN ENTRY is what keeps the decided ten-second
    visit: open, press B, leave.  It is a pure function, so "does the app pick
    the right thing" is a unit test rather than a play session.

    THE CONTROLLER ALSO RE-PARKS AFTER EVERY COMMIT.  This docstring used to say
    it parked on entry only and never moved again; that ruling was reversed
    because a booth visitor presses B and nothing else, so a fixed cursor made
    them commit one verb forever.  What keeps the standard intact is that key B
    is INERT for REACT_MS after a commit, so the label can never change while
    the key can act - see `pet_app._commit_ring`.

    NOTE the asleep ruling.  An unplanned outage wants BOOK, which is purely
    beneficial.  A creature already sleeping in a booked window needs NOTHING,
    and parking there would make WAKE - which costs a care mistake - the default
    press of the visit.  So a scheduled sleep scores REST below everything.
    """
    if state["state"] != ALIVE or state["stage"] == 0:
        return 0
    if state["asleep"]:
        rest_weight = -1 if state["scheduled"] else 400
    else:
        rest_weight = (state["fatigue"] - REST_MIN_FATIGUE_T) // 2
    best = 0
    score = -1
    weights = (
        (FEED, (MAX - state["data"]) * 4 // 10),
        (CLEAN, state["waste"] * 300),
        (HEAL, state["sick"] * 500),
        (REST, rest_weight),
        (SCOLD, 450 if state["misbehaving"] else -1),
        # The floor matters: with every need met, every other weight is 0 or
        # negative and ties resolve to whatever comes FIRST in this tuple, which
        # parked a perfectly happy creature on CLEAN with nothing to clean.
        # PLAY is the only entry that is always available, never harmful, and
        # the only actual game in the app, so it wins an otherwise empty visit.
        (PLAY, max(1, (MAX - state["mood"]) // 10)),
    )
    for action, value in weights:
        ok, _why = available(state, action)
        if not ok:
            continue
        if value > score:
            score = value
            best = RING.index(action)
    return best


def log_lines(state):
    """The event log as (relative-age-seconds, text) pairs, newest first.

    Relative times only.  An untrusted clock makes an absolute timestamp
    meaningless, and relative times read better at 160x120 anyway.
    """
    lines = []
    for code, age in reversed(state["log"]):
        lines.append((max(0, state["age_s"] - age), LOG_TEXT.get(code, "?")))
    return lines


def span(seconds):
    """A relative duration.  An untrusted clock makes an absolute one a lie, and
    relative times read better at 160x120 anyway."""
    seconds = _int(seconds, 0)
    if seconds < 0:
        seconds = 0
    if seconds < 3600:
        return "{}M".format(seconds // 60)
    if seconds < 86400:
        return "{}H {:02d}M".format(seconds // 3600, (seconds % 3600) // 60)
    return "{}D {:02d}H".format(seconds // 86400, (seconds % 86400) // 3600)


def stats_rows(state):
    """The STATS screen as (name, value) pairs.

    It lives in the pure model so the controller's scroll range and the view's
    row list are the same list, and so the whole screen is unit-testable with no
    rendering.

    CLOCK is on this list because it is a one-press decision, taken on a screen
    the player sees for a few seconds, that then governs the creature for its
    whole life.  Nothing after the egg named it: UPTIME reads in SIMULATED hours
    on both clocks, so a badge that landed on REAL simply looked inert, and the
    only route back was to guess that something was wrong and erase.  A property
    a player cannot change must at least be one they can read.
    """
    return (
        ("FORM", stage_name(state)),
        ("CLOCK", "{} {}X".format("FAST" if mode_of(state) else "REAL",
                                  speed_of(state))),
        ("CARE GRADE", care_grade(state)),
        # DISCIPLINE gates a refusal the owner WILL meet - an undisciplined
        # creature turns down every second bite - and it appeared on no screen
        # at all, so the refusal read as the app malfunctioning.  A meter that
        # climbs when you win the PLANNER also gives the minigame a visible
        # purpose, which it did not have.
        ("DISCIPLINE", "{}%".format(state["discipline"] // 10)),
        ("UPTIME", span(state["age_s"])),
        ("DB SIZE", "{} MB".format(db_size_mb(state))),
        ("DATA", "{}%".format(state["data"] // 10)),
        ("MOOD", "{}%".format(state["mood"] // 10)),
        ("REST", "{}%".format(100 - state["fatigue"] // 10)),
        ("INSERTS", str(state["total_feeds"])),
        ("VACUUMS", str(state["total_cleans"])),
        ("ROLLBACKS", str(state["total_heals"])),
        ("PLANS RUN", str(state["total_plays"])),
        ("PAUSES", str(state["pauses"])),
        ("MISTAKES", str(state["mistakes"])),
    )


def _log(state, code):
    state["log"].append([code, state["age_s"]])
    if len(state["log"]) > LOG_MAX:
        del state["log"][0:len(state["log"]) - LOG_MAX]


# --------------------------------------------------------------------------
# the report returned by advance
# --------------------------------------------------------------------------

def new_report():
    return {
        "away_s": 0,
        "steps": 0,
        "stage_up": 0,
        "got_sick": 0,
        "cured": 0,
        "misbehaved": 0,
        "slept": 0,
        "woke": 0,
        "paused": 0,
        "restored": 0,
        "mistakes": 0,
        "waste": 0, "autovacuum": 0,
        "data_empty": 0,
        "events": [],
    }


def report_has_news(report):
    return bool(
        report["stage_up"] or report["got_sick"] or report["misbehaved"]
        or report["paused"] or report["restored"] or report["mistakes"]
        or report["waste"] or report["data_empty"]
    )


# --------------------------------------------------------------------------
# the single time entry point
# --------------------------------------------------------------------------

def _accrue(state, carry_key, rate_t_per_hour, seconds):
    """Integrate one meter exactly.

    Floor division with a carry in [0, 3600) is exact for both signs and matches
    between CPython and MicroPython, so no rounding drifts between lanes.
    """
    total = rate_t_per_hour * seconds + state[carry_key]
    delta = total // 3600
    state[carry_key] = total - delta * 3600
    return delta


def advance(state, elapsed_s):
    """Apply `elapsed_s` seconds of simulated time.  Pure; no clock, no RNG."""
    report = new_report()
    elapsed_s = _int(elapsed_s, 0)
    if elapsed_s < 0:
        elapsed_s = 0
    report["away_s"] = elapsed_s
    if elapsed_s == 0:
        return state, report

    # Countdowns run on exact seconds, deliberately outside the quantised step
    # loop, so a five-minute restore completes at five minutes and not at the
    # next step boundary.
    state["feed_left_s"] = max(0, state["feed_left_s"] - elapsed_s)
    if state["feed_left_s"] == 0:
        state["feed_streak"] = 0
    state["play_cd_s"] = max(0, state["play_cd_s"] - elapsed_s)

    if state["state"] == RESTORING:
        used = min(elapsed_s, state["restore_left_s"])
        state["restore_left_s"] -= used
        elapsed_s -= used
        if state["restore_left_s"] <= 0:
            _finish_restore(state)
            report["restored"] = 1
            report["events"].append("restored")

    if state["state"] != ALIVE:
        return state, report

    total = state["sim_carry"] + elapsed_s
    steps = total // SIM_STEP_S
    state["sim_carry"] = total - steps * SIM_STEP_S
    if steps > MAX_SIM_STEPS:
        steps = MAX_SIM_STEPS
        report["events"].append("step_guard")
    report["steps"] = steps

    for _ in range(steps):
        _step(state, report)
        if state["state"] != ALIVE:
            break
    return state, report


def _finish_restore(state):
    state["state"] = ALIVE
    state["health"] = RESTORED_HEALTH_T
    state["data"] = RESTORED_DATA_T
    state["mood"] = RESTORED_MOOD_T
    state["fatigue"] = 0
    state["waste"] = 0
    state["waste_p"] = 0
    state["sick"] = 0
    state["sick_p"] = 0
    state["worsen_p"] = 0
    state["asleep"] = 0
    state["scheduled"] = 0
    state["sleep_s"] = 0
    state["misbehaving"] = 0
    state["misbehave_p"] = 0
    state["restore_left_s"] = 0
    state["health_c"] = 0
    state["sim_carry"] = 0
    if state["stage"] == 0:
        state["stage"] = 1
    _log(state, LOG_RESTORED)


def _step(state, report):
    """One SIM_STEP_S of simulated time.  The only place the rules are applied."""
    seconds = SIM_STEP_S

    if state["stage"] == 0:
        if mode_of(state):
            # A FAST egg is fully inert: it waits for INIT.  Auto-hatching after
            # 300 simulated seconds would fire 2.5 real seconds after an ERASE,
            # taking the clock choice off screen before anyone could read it -
            # and a badge resting on "PRESS INIT" is a better invitation than a
            # creature that hatched itself and starved unattended.
            return
        # The egg only ages; nothing decays, nothing can go wrong.
        state["age_s"] += seconds
        _grow(state, report)
        return

    # --- sleep and fatigue -------------------------------------------------
    if state["asleep"]:
        state["sleep_s"] += seconds
        state["fatigue"] += _accrue(state, "fatigue_c",
                                    -FATIGUE_DRAIN_T_PER_HOUR, seconds)
        if state["fatigue"] <= 0:
            state["fatigue"] = 0
            state["asleep"] = 0
            state["scheduled"] = 0
            state["sleep_s"] = 0
            report["woke"] += 1
            _log(state, LOG_WOKE)
    else:
        state["fatigue"] += _accrue(state, "fatigue_c",
                                    FATIGUE_T_PER_HOUR, seconds)
        if state["fatigue"] >= MAX:
            state["fatigue"] = MAX
            state["asleep"] = 1
            state["scheduled"] = 0      # an unplanned outage: survives, does not heal
            state["sleep_s"] = 0
            report["slept"] += 1
            _log(state, LOG_SLEPT)
    need_mult = SLEEP_NEED_MULT if state["asleep"] else 1000

    # --- needs -------------------------------------------------------------
    state["data"] = _clamp(
        state["data"] + _accrue(state, "data_c",
                                -(DATA_DECAY_T * need_mult // 1000), seconds), 0, MAX)
    state["mood"] = _clamp(
        state["mood"] + _accrue(state, "mood_c",
                                -(MOOD_DECAY_T * need_mult // 1000), seconds), 0, MAX)
    state["discipline"] = _clamp(
        state["discipline"] + _accrue(state, "discipline_c",
                                      -DISCIPLINE_DECAY_T, seconds), 0, MAX)

    # --- waste -------------------------------------------------------------
    if not state["asleep"]:
        rate = WASTE_P_PER_HOUR
        if state["misbehaving"]:
            rate *= MISBEHAVE_WASTE_MULT
        state["waste_p"] += _accrue(state, "waste_c", rate, seconds)
        while state["waste_p"] >= MAX and state["waste"] < WASTE_MAX:
            state["waste_p"] -= MAX
            state["waste"] += 1
            report["waste"] += 1
        if state["waste"] >= WASTE_MAX:
            state["waste_p"] = _clamp(state["waste_p"], 0, MAX)
            # AUTOVACUUM.  The floor has been full for a while, so a worker
            # arrives on its own - and gets it down to AUTOVACUUM_FLOOR, not to
            # zero.  Deterministic, so it cannot break the no-RNG-in-the-time-
            # path law: the same elapsed seconds always produce the same floor.
            state["autovac_s"] += seconds
            if state["autovac_s"] >= AUTOVACUUM_AFTER_S:
                state["autovac_s"] = 0
                state["waste"] = AUTOVACUUM_FLOOR
                state["waste_p"] = 0
                report["autovacuum"] += 1
                _log(state, LOG_AUTOVACUUM)
        else:
            state["autovac_s"] = 0

    # --- sickness ----------------------------------------------------------
    pressure = SICK_WASTE_P_PER_HOUR * state["waste"] - SICK_RELIEF_P_PER_HOUR
    if state["health"] < SICK_LOW_HEALTH_T:
        pressure += SICK_LOWHEALTH_P_PER_HOUR
    state["sick_p"] = _clamp(
        state["sick_p"] + _accrue(state, "sick_c", pressure, seconds), 0, MAX)
    if state["sick"] == 0 and state["sick_p"] >= MAX:
        state["sick"] = 1
        state["sick_p"] = 0
        state["worsen_p"] = 0
        report["got_sick"] += 1
        report["events"].append("sick")
        _log(state, LOG_SICK)
    elif state["sick"] == 1:
        state["worsen_p"] = _clamp(
            state["worsen_p"] + _accrue(state, "worsen_c",
                                        MAX // SICK_WORSEN_HOURS, seconds), 0, MAX)
        if state["worsen_p"] >= MAX:
            state["sick"] = 2
            state["worsen_p"] = 0

    # --- misbehaviour ------------------------------------------------------
    if not state["misbehaving"] and not state["asleep"]:
        arming = (state["mood"] < MISBEHAVE_MOOD_BELOW_T
                  and state["discipline"] < MISBEHAVE_DISC_BELOW_T)
        rate = MISBEHAVE_P_PER_HOUR if arming else -MISBEHAVE_P_PER_HOUR
        state["misbehave_p"] = _clamp(
            state["misbehave_p"] + _accrue(state, "misbehave_c",
                                           rate, seconds), 0, MAX)
        if state["misbehave_p"] >= MAX:
            state["misbehaving"] = 1
            state["misbehave_p"] = 0
            report["misbehaved"] += 1
            report["events"].append("misbehaving")
            _log(state, LOG_MISBEHAVED)

    # --- health ------------------------------------------------------------
    state["health"] = _clamp(
        state["health"] + _accrue(state, "health_c",
                                  health_rate_t(state), seconds), 0, MAX)

    # --- care mistakes -----------------------------------------------------
    _mistakes(state, report, seconds)

    # --- growth ------------------------------------------------------------
    state["age_s"] += seconds
    _grow(state, report)

    # --- the pause ---------------------------------------------------------
    if state["health"] <= 0:
        state["health"] = 0
        state["state"] = PAUSED
        state["asleep"] = 0
        state["sleep_s"] = 0
        state["misbehaving"] = 0
        # A paused project accumulates nothing, so the partial step is dropped.
        # Without this, advance(3d) and 7 x advance(3d/7) leave different
        # sim_carry values and the additivity law stops holding at the pause.
        state["sim_carry"] = 0
        state["pauses"] += 1
        state["mistakes"] = _clamp(state["mistakes"] + MISTAKE_PAUSE, 0, MISTAKE_MAX)
        report["paused"] = 1
        report["mistakes"] += MISTAKE_PAUSE
        report["events"].append("paused")
        _log(state, LOG_PAUSED)


def _mistake_timer(state, report, key, condition, threshold, seconds):
    if not condition:
        state[key] = 0
        return
    state[key] += seconds
    while state[key] >= threshold:
        state[key] -= threshold
        state["mistakes"] = _clamp(state["mistakes"] + 1, 0, MISTAKE_MAX)
        report["mistakes"] += 1
        _log(state, LOG_MISTAKE)


def _mistakes(state, report, seconds):
    if state["data"] <= 0:
        report["data_empty"] = 1
    _mistake_timer(state, report, "m_data_s", state["data"] <= 0,
                   MISTAKE_NEED_ZERO_S, seconds)
    _mistake_timer(state, report, "m_mood_s", state["mood"] <= 0,
                   MISTAKE_NEED_ZERO_S, seconds)
    _mistake_timer(state, report, "m_waste_s", state["waste"] >= WASTE_MAX,
                   MISTAKE_WASTE_FULL_S, seconds)
    _mistake_timer(state, report, "m_sick_s", state["sick"] > 0,
                   MISTAKE_SICK_S, seconds)
    _mistake_timer(state, report, "m_mis_s", state["misbehaving"] != 0,
                   MISTAKE_MISBEHAVE_S, seconds)


def _grow(state, report):
    target = state["stage"]
    for index in range(STAGE_COUNT):
        if state["age_s"] >= STAGE_AGE_S[index]:
            target = index
    if target <= state["stage"]:
        return
    state["stage"] = target
    if target == STAGE_COUNT - 1:
        if state["mistakes"] <= ADULT_HA_MAX_MISTAKES:
            state["form"] = 0
        elif state["mistakes"] <= ADULT_PROD_MAX_MISTAKES:
            state["form"] = 1
        else:
            state["form"] = 2
    report["stage_up"] = target
    report["events"].append("stage")
    _log(state, LOG_STAGE)


# --------------------------------------------------------------------------
# the single command entry point
# --------------------------------------------------------------------------

def apply(state, action):
    """Commit one action.  Returns (state, outcome).

    `outcome` is {"event", "applied", "rejected", "text"}: `applied` is in tenths,
    `rejected` is a short reason or "", and `text` is the toast to show.
    """
    if action == RESTORE:
        return _do_restore(state)
    if action == HATCH:
        return _do_hatch(state)

    ok, why = available(state, _ring_of(action))
    if not ok:
        return state, _out("", 0, why.lower().replace(" ", "_"), why)

    if action == FEED:
        return _do_feed(state)
    if action == CLEAN:
        return _do_clean(state)
    if action == HEAL:
        return _do_heal(state)
    if action == REST:
        return _do_rest(state)
    if action == SCOLD:
        return _do_scold(state)
    if action == PLAY_WIN:
        return _do_play(state, True)
    if action == PLAY_LOSS:
        return _do_play(state, False)
    return state, _out("", 0, "unknown", "")


def _ring_of(action):
    if action in (PLAY_WIN, PLAY_LOSS):
        return PLAY
    return action


def _out(event, applied=0, rejected="", text=""):
    return {"event": event, "applied": applied, "rejected": rejected, "text": text}


def _do_feed(state):
    if state["feed_left_s"] <= 0:
        state["feed_streak"] = 0
    streak = state["feed_streak"]

    # An undisciplined creature refuses every second bite - unless refusing could
    # actually endanger it, which the two safety valves rule out.  Losing is
    # meant to be shareable, not punishing.
    if (state["discipline"] < REFUSE_DISCIPLINE_BELOW_T
            and streak % REFUSE_EVERY_N == 1
            and state["health"] >= REFUSE_SAFETY_HEALTH_T
            and state["data"] >= REFUSE_SAFETY_DATA_T):
        # A refused bite still CONSUMED the bite: the streak advances and the
        # window re-arms, which is what makes this "every second press" rather
        # than a deadlock.  The lockout fix below deliberately does NOT apply
        # here - see the comment on the 429 return for which refusal is which.
        state["feed_left_s"] = feed_window_s(state)
        state["feed_streak"] = min(32, streak + 1)
        return state, _out("refused", 0, "", "40001 RETRY")

    offered = FEED_VALUE_T >> streak if streak < 16 else 0
    if offered <= 0:
        # The window has halved to nothing.  This is BACKOFF, not fullness - the
        # bar is typically around 91% when it fires, so the old "TABLE FULL" was
        # contradicted by the DATA row one key-press away on STATS.  Supabase's
        # gateway returns 429 for exactly this, and exponential halving IS
        # exponential backoff.
        #
        # AND CRUCIALLY: this return does NOT re-arm the window.  The assignment
        # used to sit at the top of the function, above every refusal, so each
        # rejected press restarted its own lockout and burned another streak
        # step.  The remedy was to stop pressing for 3 s (fast) or 45 s (real),
        # and the natural human response - press it again - was exactly what
        # prevented it.  That is the "I could not continue and did not know why"
        # the owner hit.  The 403 above is a different mechanic and still arms,
        # because a refused bite is still a bite.
        return state, _out("full", 0, "", "429 TOO MANY")

    state["feed_left_s"] = feed_window_s(state)
    state["feed_streak"] = min(32, streak + 1)
    applied = min(MAX - state["data"], offered)
    state["data"] += applied
    state["mood"] = _clamp(state["mood"] + FEED_MOOD_T, 0, MAX)
    state["total_feeds"] += 1
    if applied <= 0 and offered > 0:
        state["sick_p"] = _clamp(state["sick_p"] + OVERFEED_SICK_P, 0, MAX)
        state["waste_p"] += OVERFEED_WASTE_P
        _spill_waste(state)
        _log(state, LOG_OVERFED)
        # Not a metaphor: 23505 aborts the statement, and the tuple written
        # before the abort stays on the heap as a dead tuple until vacuum
        # removes it.  The model already did exactly this; it just never said
        # so.  Reachable only by overriding the DUPLICATE KEY gate with the
        # cursor, which is a deliberate act rather than the app's suggestion.
        return state, _out("overfed", 0, "", "DUPLICATE KEY +1 TUPLE")
    state["waste_p"] += FEED_WASTE_P
    _spill_waste(state)
    return state, _out("fed", applied, "", "INSERT 0 1")


def _spill_waste(state):
    while state["waste_p"] >= MAX and state["waste"] < WASTE_MAX:
        state["waste_p"] -= MAX
        state["waste"] += 1
    if state["waste"] >= WASTE_MAX:
        state["waste_p"] = _clamp(state["waste_p"], 0, MAX)


def _do_clean(state):
    removed = state["waste"]
    state["waste"] = 0
    state["waste_p"] = 0
    state["total_cleans"] += 1
    if removed:
        _log(state, LOG_CLEANED)
    return state, _out("cleaned", removed, "", ("VACUUM FULL -%d" % removed) if removed else "0 DEAD ROWS")


def _do_heal(state):
    state["sick"] -= 1
    state["total_heals"] += 1
    if state["sick"] <= 0:
        state["sick"] = 0
        state["sick_p"] = 0
        state["worsen_p"] = 0
        state["health"] = _clamp(state["health"] + HEAL_HEALTH_T, 0, MAX)
        _log(state, LOG_CURED)
        return state, _out("cured", HEAL_HEALTH_T, "", "ROLLBACK OK")
    return state, _out("dosed", 0, "", "ONE DOSE LEFT")


def _do_rest(state):
    if state["asleep"]:
        if not state["scheduled"]:
            # Retro-schedule an unplanned outage: the pet starts healing properly.
            state["scheduled"] = 1
            return state, _out("scheduled", 0, "", "WINDOW BOOKED")
        slept_s = state["sleep_s"]
        state["asleep"] = 0
        state["scheduled"] = 0
        state["sleep_s"] = 0
        # Waking a creature that has barely closed its eyes is an UNDO of the
        # press before it, not neglect.  Only a wake that cuts a real sleep
        # short costs a care mistake, so a mistap on the ring is recoverable and
        # a mashed B cannot drive the mistake counter to its cap.
        if slept_s >= wake_grace_s(state) and state["fatigue"] > WAKE_PENALTY_FATIGUE_T:
            state["mood"] = _clamp(state["mood"] - WAKE_MOOD_COST_T, 0, MAX)
            state["mistakes"] = _clamp(state["mistakes"] + 1, 0, MISTAKE_MAX)
            _log(state, LOG_MISTAKE)
            _log(state, LOG_WOKE)
            return state, _out("woke", 0, "", "WOKEN EARLY")
        _log(state, LOG_WOKE)
        return state, _out("woke", 0, "", "GOOD MORNING")
    state["asleep"] = 1
    state["scheduled"] = 1
    state["sleep_s"] = 0
    state["fatigue_c"] = 0
    _log(state, LOG_SLEPT)
    return state, _out("slept", 0, "", "SCALED TO ZERO")


def _do_scold(state):
    state["misbehaving"] = 0
    state["misbehave_p"] = 0
    state["discipline"] = _clamp(state["discipline"] + SCOLD_VALUE_T, 0, MAX)
    state["mood"] = _clamp(state["mood"] - SCOLD_MOOD_COST_T, 0, MAX)
    _log(state, LOG_SCOLDED)
    return state, _out("scolded", SCOLD_VALUE_T, "", "RLS ENABLED")


def _do_play(state, won):
    state["total_plays"] += 1
    state["play_cd_s"] = PLAY_COOLDOWN_S
    gain = PLAY_MOOD_WIN_T if won else PLAY_MOOD_LOSS_T
    state["mood"] = _clamp(state["mood"] + gain, 0, MAX)
    if won:
        state["health"] = _clamp(state["health"] + PLAY_HEALTH_WIN_T, 0, MAX)
        state["discipline"] = _clamp(state["discipline"] + PLAY_DISCIPLINE_T, 0, MAX)
    _log(state, LOG_PLAYED)
    return state, _out("played", gain, "", "SEQ SCAN AVOIDED" if won else "NICE TRY")


def _do_restore(state):
    if state["state"] != PAUSED:
        return state, _out("", 0, "not_paused", "")
    state["state"] = RESTORING
    state["restore_left_s"] = restore_s(state)
    state["sim_carry"] = 0
    return state, _out("restoring", 0, "", "RESTORE QUEUED")


def _do_hatch(state):
    if state["stage"] != 0 or state["state"] != ALIVE:
        return state, _out("", 0, "not_egg", "")
    state["stage"] = 1
    if state["age_s"] < STAGE_AGE_S[1]:
        state["age_s"] = STAGE_AGE_S[1]
    _log(state, LOG_HATCHED)
    return state, _out("hatched", 0, "", "PROJECT CREATED")


# --------------------------------------------------------------------------
# screens: the softkey contract lives in the pure model so the 34 px budget is
# a fast-lane unit test rather than a device surprise
# --------------------------------------------------------------------------

POSTER = "poster"
NEWS = "news"
CARE = "care"
STATS = "stats"
LOG = "log"
CONFIRM = "confirm"
GAME = "game"
PAUSED_VIEW = "paused"
RESTORING_VIEW = "restoring"
VIEWS = (POSTER, NEWS, CARE, STATS, LOG, CONFIRM, GAME, PAUSED_VIEW, RESTORING_VIEW)


def view_for(state):
    """The screen the app must be on for this state, ignoring navigation."""
    if state["state"] == PAUSED:
        return PAUSED_VIEW
    if state["state"] == RESTORING:
        return RESTORING_VIEW
    return CARE


def softkeys(state, view, index=0):
    """Exactly three labels; "" means the key draws nothing and is inert (R6).

    A retreats, B commits, C advances (R7) on every screen without exception.

    THE ONE PLACE THAT LOOKS LIKE AN EXCEPTION IS DELIBERATE.  NEW sits on B of
    STATS and the advance key of LOG is empty, because C is the natural
    exploratory press and R19 puts the destructive verb on C of the confirmation
    screen.  With NEW on C, four presses of one key walked from the root to an
    erased creature and the confirmation contributed no decision at all - R20's
    stated failure case on the other axis.  Keeping the entry on B breaks the run
    of identical presses without moving the destructive verb off C, so R19 stays
    literally satisfied.  `test_pet_ui_contract` asserts both halves.

    WHY THE ENTRY MOVED UP A SCREEN.  A badge handed to a stranger has to be
    resettable by the NEXT stranger, and NEW used to live on LOG - two screens
    deep, on a readout nobody has a reason to open, four presses from the root.
    It is now C, B, C from EVERY root, alive or paused, which is why PAUSED also
    advances to STATS.  Only the screen changed; D21's rule did not.
    """
    if view == POSTER:
        return ("", "", "")
    if view == NEWS:
        return ("", "OK", "")
    if view == CARE:
        if state["stage"] == 0:
            # The one screen where the clock is chosen: C names the OTHER speed.
            return ("BACK", "INIT", "REAL" if mode_of(state) else "FAST")
        return ("BACK", ring_label(state, RING[index % len(RING)]), "STATS")
    if view == STATS:
        return ("BACK", "NEW", "LOG")
    if view == LOG:
        return ("BACK", "", "")
    if view == CONFIRM:
        return ("KEEP", "", "ERASE")
    if view == GAME:
        return ("QUIT", "PICK", "")
    if view == PAUSED_VIEW:
        return ("", "START", "STATS")
    if view == RESTORING_VIEW:
        return ("", "", "STATS")
    return ("", "", "")
