"""``execute_at``: hold a command durably and fire it on the NTP-synced clock.

WHY THE BADGE HOLDS IT AND ACKS IMMEDIATELY, which is the one decision here that
looks wrong and is not. ``badgelink_badge_poll`` DOES NOT FILTER ON
``execute_at``. It hands back every ``queued`` or ``delivered`` row for this
badge, increments ``delivery_attempts`` on each pass, and at
``delivery_attempts >= 5`` it FAILS the row with
``{"error": "delivery_attempts_exhausted"}``. So a badge that withheld its ack
until the moment arrived would watch the server kill the command first: five
polls is 2.5 minutes at the 30 s idle cadence and 15-25 seconds while active,
against an ``execute_at`` that exists precisely to be minutes away.

So the badge:

1. VALIDATES THE PAYLOAD NOW, so a malformed scheduled command fails visibly at
   the moment it is queued rather than silently five minutes later;
2. persists it here;
3. acks ``applied`` with ``result.applies == "scheduled"`` and the resolved
   ``execute_at``.

THE ACK VOCABULARY HAS NO "ACCEPTED, NOT YET APPLIED" STATUS. The CHECK accepts
``applied`` and ``failed`` and nothing else, so the honest signal lives in the
RESULT rather than the status, and the console must read ``result.applies``. That
is recorded as a schema OBSERVATION, not a defect: adding a ``scheduled`` status
is a future migration and Card FT-B may not touch the schema.

WALL CLOCK, NOT TICKS. ``execute_at`` is a timestamptz and the point of the
ring+``execute_at`` hybrid is that 800 badges act at ONE instant, so the
comparison has to be against the NTP-synced epoch. Two consequences:

* the epoch is parsed here with pure integer arithmetic (Hinnant's
  days-from-civil), so nothing depends on which epoch the port's ``time.mktime``
  uses -- a real trap on MicroPython, where bare-metal ports count from 2000;
* a badge whose clock is NOT plausible must not fire early. ``clock_boot``'s
  build-floor/ceiling gate is reused for exactly that, so a badge that never
  reached NTP holds the command until it does instead of firing it in 2021.

MicroPython surface only: ``json`` and ``os``. The write is
temp -> flush -> os.sync -> rename.
"""

import json
import os


SCHEMA = 1
DEFAULT_PATH = "/state/badgelink-scheduled.json"

# HOW MANY COMMANDS MAY WAIT. Eight, and the number is an argument: a
# synchronized moment is ONE command per badge (the console fans a light show out
# as one row each), so the realistic queue depth is 1-2 and eight is four times
# the worst case anybody has described. It also bounds the file: eight entries of
# a ~4 KB payload cap is ~32 KB against a 1 MB volume, and the whole file is
# rewritten on every change, so a larger cap would be a larger write on every
# schedule. A full queue REFUSES, which becomes a failed ack the console can see;
# silently dropping the oldest would lose a moment somebody had planned.
MAX_HELD = 8

# How far ahead the badge is willing to hold something. THIRTY-SIX HOURS, which
# covers "tomorrow morning's keynote" set up the night before and refuses a
# typo'd year. It is also a fail-soft bound on the file: a command scheduled for
# 2099 would otherwise sit in the queue forever, occupying one of the eight slots
# nothing can reclaim.
MAX_HORIZON_S = 36 * 60 * 60

# How stale a held command may be when its moment finally arrives. A badge that
# was off during the moment boots afterwards and finds a command whose time has
# passed; firing a light show ten minutes late is worse than not firing it, so
# anything older than this is DISCARDED and reported. Two minutes: long enough to
# survive a reset and a reconnect, short enough that nobody sees a stale effect.
MAX_LATE_S = 120

# THE PRE-DECODE BOUND (CX-10 sub-claim 4). MAX_HELD's own comment already prices
# the file: eight entries against a ~4 KB payload cap is ~32 KB, so 64 KB is 2x
# the largest thing `save` can write. Past the cap the load answers
# `default_state()`, which is exactly what a corrupt file already answers, and
# the docstring below says what that costs: at most one light show that never
# happens.
MAX_BYTES = 65536

_DIGITS = "0123456789"


class ScheduleError(Exception):
    """The command could not be held. The applier turns this into a failed ack."""


def _int(text):
    if not text:
        return None
    value = 0
    for character in text:
        if character not in _DIGITS:
            return None
        value = value * 10 + (ord(character) - 48)
    return value


def _days_from_civil(year, month, day):
    """Days since 1970-01-01 for a proleptic Gregorian date.  Pure integers.

    Hinnant's algorithm, transcribed. Chosen over ``time.mktime`` because this
    module has to agree with a PostgreSQL timestamptz on any port, and
    MicroPython's bare-metal ports count seconds from 2000 while CPython counts
    from 1970 -- a difference that would show up as a command firing 30 years
    early, on hardware, once.
    """

    if month <= 2:
        year -= 1
    era = (year if year >= 0 else year - 399) // 400
    year_of_era = year - era * 400
    shifted = month + (-3 if month > 2 else 9)
    day_of_year = (153 * shifted + 2) // 5 + day - 1
    day_of_era = (year_of_era * 365 + year_of_era // 4 - year_of_era // 100
                  + day_of_year)
    return era * 146097 + day_of_era - 719468


def parse_timestamp(text):
    """One PostgREST timestamptz -> a UNIX epoch integer, or ``None``.

    Accepts what PostgREST actually renders and nothing else:
    ``2026-08-22T18:30:00+00:00``, ``...Z``, ``...+05:30``, ``...-07:00``, with
    or without fractional seconds, and with a space instead of ``T``. FRACTIONAL
    SECONDS ARE TRUNCATED rather than rounded: the badge cannot act inside a
    frame anyway, and truncating can only fire late.

    Returns ``None`` -- never a guess and never a raise -- for anything else. A
    caller that cannot read the time refuses the command, which is the only safe
    direction: a misparsed timestamp is a command that fires at the wrong moment
    in front of 800 people.
    """

    if not isinstance(text, str) or len(text) < 19 or len(text) > 40:
        return None
    if text[4] != "-" or text[7] != "-":
        return None
    if text[10] != "T" and text[10] != " ":
        return None
    if text[13] != ":" or text[16] != ":":
        return None
    year = _int(text[0:4])
    month = _int(text[5:7])
    day = _int(text[8:10])
    hour = _int(text[11:13])
    minute = _int(text[14:16])
    second = _int(text[17:19])
    if None in (year, month, day, hour, minute, second):
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    # A leap second renders as :60 and is not a date this fleet has to honour;
    # clamping is kinder than refusing the whole command.
    if hour > 23 or minute > 59 or second > 60:
        return None
    if second == 60:
        second = 59
    rest = text[19:]
    if rest.startswith("."):
        index = 1
        while index < len(rest) and rest[index] in _DIGITS:
            index += 1
        rest = rest[index:]
    offset = 0
    if rest in ("", "Z", "z"):
        pass
    elif rest[0] == "+" or rest[0] == "-":
        body = rest[1:]
        if len(body) == 5 and body[2] == ":":
            body = body[0:2] + body[3:5]
        elif len(body) == 2:
            body = body + "00"
        if len(body) != 4:
            return None
        offset_hours = _int(body[0:2])
        offset_minutes = _int(body[2:4])
        if offset_hours is None or offset_minutes is None:
            return None
        if offset_hours > 23 or offset_minutes > 59:
            return None
        offset = offset_hours * 3600 + offset_minutes * 60
        if rest[0] == "-":
            offset = -offset
    else:
        return None
    days = _days_from_civil(year, month, day)
    return days * 86400 + hour * 3600 + minute * 60 + second - offset


def due_at(command, now_epoch):
    """When this command should fire: ``(epoch, verdict)``.

    ``verdict`` is one of:

    * ``"now"``   -- no ``execute_at``, or it is in the past/at now. Apply.
    * ``"hold"``  -- a future moment inside the horizon. Persist and fire later.
    * ``"unreadable"`` -- present and not a timestamp this module can parse.
    * ``"far"``   -- further out than :data:`MAX_HORIZON_S`.
    * ``"no_clock"`` -- an ``execute_at`` is present and ``now_epoch`` is
      ``None`` (the wall clock failed ``clock_boot``'s plausibility gate). An
      EXPLICIT verdict rather than a comparison against ``None``, which raises
      TypeError on CPython and compares silently on some ports -- and "the badge
      does not know what time it is" is a real answer a caller has to render.
      A command with NO ``execute_at`` still says ``"now"``: it never needed a
      clock.

    THERE IS NO ``"stale"`` HERE, and a draft docstring listed one. A
    freshly-arrived command with a past ``execute_at`` is ``"now"`` -- the
    operator meant "as soon as you can" and the console is showing them a queued
    row. Staleness is only a question for an ALREADY-HELD command whose moment
    passed while the badge was off, which is :func:`fire_verdict`'s.
    """

    raw = command.get("execute_at") if isinstance(command, dict) else None
    if raw is None:
        return (now_epoch, "now")
    if now_epoch is None:
        return (None, "no_clock")
    when = parse_timestamp(raw)
    if when is None:
        return (None, "unreadable")
    if when <= now_epoch:
        return (when, "now")
    if when - now_epoch > MAX_HORIZON_S:
        return (when, "far")
    return (when, "hold")


def fire_verdict(when, now_epoch):
    """For an already-held command: ``"wait"``, ``"fire"`` or ``"stale"``.

    No clock means WAIT, never fire: a badge that has not reached NTP must hold
    a moment rather than guess at it.
    """

    if now_epoch is None:
        return "wait"
    if when > now_epoch:
        return "wait"
    if now_epoch - when > MAX_LATE_S:
        return "stale"
    return "fire"


# ---------------------------------------------------------------------------
# the file
# ---------------------------------------------------------------------------

def default_state():
    return {"schema": SCHEMA, "held": []}


def _entry(value):
    if not isinstance(value, dict):
        return None
    command_id = value.get("id")
    command_type = value.get("type")
    payload = value.get("payload")
    when = value.get("at")
    if not isinstance(command_id, str) or not command_id or len(command_id) > 64:
        return None
    if not isinstance(command_type, str) or not command_type or len(command_type) > 32:
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(when, int) or isinstance(when, bool):
        return None
    return {"id": command_id, "type": command_type, "payload": payload,
            "at": when}


def load(path=None, open_fn=None):
    """The held commands, or defaults.  Fail-soft: a corrupt file holds nothing.

    A scheduled moment is not worth a boot. Dropping the file's contents costs
    at most one light show that never happens; raising here would cost the badge.

    BOUNDED BEFORE THE DECODE (:data:`MAX_BYTES`), so an oversize file is a
    refusal rather than a heap allocation followed by a refusal.
    """

    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    try:
        with open_fn(path, "r") as source:
            text = source.read(MAX_BYTES + 1)
        if len(text) > MAX_BYTES:
            return default_state()
        raw = json.loads(text)
    except (OSError, ValueError, TypeError):
        return default_state()
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return default_state()
    entries = raw.get("held")
    if not isinstance(entries, list):
        return default_state()
    held = []
    for value in entries[:MAX_HELD]:
        entry = _entry(value)
        if entry is not None:
            held.append(entry)
    return {"schema": SCHEMA, "held": held}


def save(state, path=None, open_fn=None, sync_fn=None, rename_fn=None):
    """Atomically persist.  temp -> flush -> sync -> rename."""

    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    held = []
    for value in state.get("held", ())[:MAX_HELD]:
        entry = _entry(value)
        if entry is None:
            raise ScheduleError("held command entry is malformed")
        held.append(entry)
    record = {"schema": SCHEMA, "held": held}
    temporary = path + ".tmp"
    with open_fn(temporary, "w") as output:
        json.dump(record, output)
        flush = getattr(output, "flush", None)
        if flush is not None:
            flush()
    sync = sync_fn if sync_fn is not None else getattr(os, "sync", None)
    if sync is not None:
        sync()
    (rename_fn or os.rename)(temporary, path)
    return record


def hold(state, command_id, command_type, payload, when):
    """Add one entry, ordered by when it fires.  Raises when the queue is full.

    Re-holding the SAME command id replaces its entry rather than duplicating it:
    a redelivered command must not become two effects, and the ledger's re-ack
    path already covers the ordinary case.
    """

    entry = _entry({"id": command_id, "type": command_type, "payload": payload,
                    "at": when})
    if entry is None:
        raise ScheduleError("scheduled command is malformed")
    held = []
    for existing in state.get("held", ()):
        if existing.get("id") != command_id:
            held.append(existing)
    if len(held) >= MAX_HELD:
        raise ScheduleError("the badge is already holding {} commands".format(
            MAX_HELD))
    held.append(entry)
    # Sorted so the pump only ever has to look at held[0]. `sorted` with a key is
    # available on the frozen build; an insertion sort would be the fallback and
    # is not needed for eight entries.
    held.sort(key=lambda item: item["at"])
    return {"schema": SCHEMA, "held": held}


def next_due(state):
    """The earliest held entry, or ``None``.  Allocates nothing."""

    held = state.get("held")
    if not held:
        return None
    return held[0]


def drop(state, command_id):
    """Remove one entry by id."""

    held = [entry for entry in state.get("held", ())
            if entry.get("id") != command_id]
    return {"schema": SCHEMA, "held": held}
