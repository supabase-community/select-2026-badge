"""Pure schedule schema, clock and navigation rules shared by device and host tests."""

import json
import os


SCHEMA = 2

# Schema 2 adds `kind` and `speakers` to a session. Its three kinds are the
# three visual treatments the published agenda actually uses, recorded in the
# data rather than re-derived from an empty speaker list — "Doors Open &
# Breakfast" and "Lunch" both have no speakers and are drawn differently.
KIND_TALK = "talk"           # speakers, or TO BE ANNOUNCED when the list is empty
KIND_LOGISTICS = "logistics"  # normal row, no speaker line at all
KIND_BREAK = "break"         # muted and hatched, no speaker line
KINDS = (KIND_TALK, KIND_LOGISTICS, KIND_BREAK)

# ASCII remains the truncation marker so the bitmap fallback draws the same
# three visible stops as the rebuilt vector face.
ELLIPSIS = "..."

# The repository MonaSans-Medium rebuild carries every punctuation glyph its
# pinned v2.0.08 source exposes, plus the five arrows and minus sign a web
# agenda uses. `schedule/host/render.mjs` renders every character below through
# the real picovector runtime and refuses zero advance or zero ink.
DRAWABLE_PUNCTUATION = "–—‘’‚“”„•…‰‹›⁄←↑→↓↔−"

# Honest residue only: every key here is absent from the rebuilt vector face.
# Fold it to a visible equivalent before the range check rather than letting it
# disappear or degrading ordinary typography to `?`.
PUNCTUATION_FOLD = {
    "‐": "-", "‑": "-", "‒": "-", "―": "-",
    "‛": "'", "′": "'",
    "‟": '"', "″": '"',
    " ": " ", " ": " ", " ": " ",
    "­": "",
}

# Not a font fallback. Rect-form `screen.text` parses `[renderer:args]`, and an
# unknown renderer raises inside the frame loop. The platform escape is `[[`.
MARKUP_ESCAPE = {"[": "[["}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def parse_time(value):
    _require(isinstance(value, str), "time must be HH:MM text")
    parts = value.split(":")
    _require(len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) == 2, "time must be HH:MM")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        raise ValueError("time must contain digits")
    _require(0 <= hour <= 23 and 0 <= minute <= 59, "time outside day")
    return hour * 60 + minute


def format_time(minutes):
    minutes = int(minutes) % (24 * 60)
    return "{:02d}:{:02d}".format(minutes // 60, minutes % 60)


def _leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def parse_date(value):
    _require(isinstance(value, str), "date must be YYYY-MM-DD text")
    parts = value.split("-")
    _require(len(parts) == 3 and len(parts[0]) == 4 and len(parts[1]) == 2 and len(parts[2]) == 2, "date must be YYYY-MM-DD")
    try:
        year, month, day = (int(part) for part in parts)
    except ValueError:
        raise ValueError("date must contain digits")
    _require(2000 <= year <= 2199 and 1 <= month <= 12, "date outside supported range")
    days = (31, 29 if _leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    _require(1 <= day <= days[month - 1], "invalid day for month")
    return year, month, day


# ── THE EVENT'S UTC OFFSET: THE ONE PIECE OF TIMEZONE ARITHMETIC THIS APP DOES ─
#
# WHY IT EXISTS, AND IT IS A MEASUREMENT RATHER THAN AN ARGUMENT. Every time in
# an agenda file is EVENT-LOCAL (`day_start`, every session `HH:MM`, the date
# window, `generated_at`) and a SYNCED BADGE'S CLOCK READS UTC. The chain, read
# out of the code rather than assumed: `badgelink.clock_boot.resync` calls
# `ntptime.settime()`, which sets `machine.RTC` from `gmtime` (UTC), and
# `badgeware.rtc.localtime_to_rtc()` copies that verbatim onto the PCF85063A this
# app reads. VAL-041-BLR is the hardware receipt: on the reference badge
# one sync moved the badge's own local wall `2026-08-16 22:05:05` to
# `2026-08-17 04:06:26` -- six hours forward, the Mountain offset of the machine
# running the probe -- and the external chip read back the UTC value.
#
# So without this field a paired badge tests a 09:00-18:00 event window against a
# UTC clock: eight hours out for PST, which rolls it onto "the wrong day" from
# 16:00 local and prints UTC under a `PST` label.
#
# IT IS DATA, NEVER A LITERAL, for the same reason the `timezone` LABEL is: the
# venue's offset is a fact somebody confirms, not something this app can know. It
# rides in the baked file, in a `/schedule.json` day-of override, and (when a
# fetch ever writes this schema) in whatever the server sends.
#
# SIGN CONVENTION, stated once because getting it backwards is silent: it is the
# minutes to ADD to a UTC reading to get event-local time. PST is `-480`.
#
# THREE BOUNDS, each catching a different mistake:
#
# * `-720 .. 840` -- the real range of civil offsets, UTC-12 to UTC+14. Outside
#   it, the value is not a timezone.
# * A MULTIPLE OF 15 MINUTES. Every civil offset in modern use is one, and this
#   is the bound that catches the mistake somebody will ACTUALLY make: writing
#   `-8` (hours) where the field wants `-480` (minutes). `-8` is inside the range
#   and would shift the agenda by eight MINUTES -- enough to put the NOW marker
#   on the wrong row either side of a boundary, and small enough that nobody
#   would suspect the data.
# * An `int` with `bool` excluded EXPLICITLY, because `True` is an `int` in both
#   Pythons, so `"utc_offset_min": true` would otherwise become one minute. Same
#   trap `synced_at_seconds` documents, same explicit check.
#
# A BAD VALUE IS A REJECTION, NOT A REPAIR, and the asymmetry that makes that
# safe is already built: a day-of override that fails validation falls back to
# the known-good baked agenda plus a visible notice, and only a BAKED file this
# wrong reaches the error screen -- which is a build defect the pre-freeze gate
# catches. Clamping would hand somebody a confidently wrong NOW marker, which is
# the exact defect this field exists to remove.
UTC_OFFSET_MIN = -720   # UTC-12
UTC_OFFSET_MAX = 840    # UTC+14
UTC_OFFSET_STEP = 15


def parse_utc_offset(value):
    """The event's UTC offset in minutes, validated. Raises `ValueError`."""
    _require(isinstance(value, int) and not isinstance(value, bool),
             "event utc_offset_min must be a whole number of minutes")
    _require(UTC_OFFSET_MIN <= value <= UTC_OFFSET_MAX,
             "event utc_offset_min outside the UTC-12..UTC+14 range")
    _require(value % UTC_OFFSET_STEP == 0,
             "event utc_offset_min must be a multiple of 15 minutes, not hours")
    return value


# NO WEEKDAY HELPER LIVES HERE ANY MORE, and its absence is the doctrine.
#
# `weekday_iso` and `weekday_badgeware` existed for ONE caller: the dial's
# commit, which wrote both of the badge's clocks and had to put the right
# number in the PCF85063A's weekday register. **The dial is deleted (owner
# ruling, 2026-08-25: "we either get a real time from a server or don't assume
# we know time"), so this app writes no clock and reads no weekday.**
#
# The firmware knowledge those functions carried is NOT lost and must not be
# re-derived here: the two clocks, their incompatible tuple orders, the
# Monday=0 convention the boot sync propagates, the stock clock app's two
# disagreeing writes, and the `powman.c` 2025-05-01 re-seed are all recorded in
# `docs/engineering-findings.md` (the two-clocks section), which is where the
# next thing that writes a badge clock should read them. Today that is
# `badgelink`'s boot sync, not this app.


def sanitize_title(value):
    """Fold web punctuation to ASCII, escape markup, then make the rest visibly lossy.

    Three failure modes, not one. A code point outside the face contract becomes
    a visible `?`, which is the loud degrade Phase 2 needs. Punctuation the
    rebuilt vector face owns passes through unchanged; genuinely absent near
    equivalents are folded visibly. And `[` used to pass into the rect form of
    `screen.text`, which is where the firmware parses glyph markup: a title of
    `[sprite:x]` was a KeyError inside `update()`, i.e. a modal that resets the
    badge on every frame. All three are handled by the fold running first and
    the range check running second; see PUNCTUATION_FOLD and MARKUP_ESCAPE.
    """
    text = str(value)
    safe = []
    for character in text:
        escaped = MARKUP_ESCAPE.get(character)
        if escaped is not None:
            safe.append(escaped)
            continue
        replacement = PUNCTUATION_FOLD.get(character)
        if replacement is not None:
            safe.append(replacement)
            continue
        codepoint = ord(character)
        if character in "\t\r\n":
            safe.append(" ")
        elif (32 <= codepoint <= 126 or 160 <= codepoint <= 255
              or character in DRAWABLE_PUNCTUATION):
            safe.append(character)
        else:
            safe.append("?")
    return "".join(safe)


def normalize(data):
    _require(isinstance(data, dict), "schedule root must be an object")
    _require(data.get("schema") == SCHEMA, "unsupported schedule schema")
    event = data.get("event")
    _require(isinstance(event, dict), "event must be an object")
    event_id = event.get("id")
    event_name = event.get("name")
    _require(isinstance(event_id, str) and event_id, "event id required")
    _require(isinstance(event_name, str) and event_name, "event name required")
    start_date = parse_date(event.get("start_date"))
    end_date = parse_date(event.get("end_date", event.get("start_date")))
    _require(start_date <= end_date, "event date window reversed")
    day_start = parse_time(event.get("day_start", "00:00"))
    day_end = parse_time(event.get("day_end", "23:59"))
    _require(day_start < day_end, "event day window reversed")

    # FOUR OPTIONAL `event` FIELDS. Optional is the load-bearing word: the
    # schema version is matched EXACTLY, so making any of these required would
    # reject every agenda file already on a badge, and this app's whole
    # day-of story is a file somebody drops on the root by hand. Absent means
    # "this file does not say", which the freshness line renders honestly.
    #
    # `utc_offset_min` (added 2026-08-25) is the fourth and it is the one whose
    # ABSENCE COSTS SOMETHING: without it the app has no frame to read a synced
    # badge's UTC clock in, so it claims no time at all. That is a deliberate
    # refusal rather than a degradation by accident -- documented at
    # `clock_state` -- and it still cannot be required, because every agenda file
    # written before today omits it and a required field would turn each of those
    # badges into an error screen. A silent NOW marker beats a wrong one.
    generated_at = event.get("generated_at")
    if generated_at is not None:
        generated_at = parse_stamp(generated_at)
    # The badgelink `version` string this agenda was built from, when it was
    # built from one. Compared for EQUALITY against `/state/schedule.json`'s
    # version and never parsed, so its shape stays badgelink's business.
    source_version = event.get("source_version")
    if source_version is not None:
        _require(isinstance(source_version, str) and 0 < len(source_version) <= 64,
                 "source version must be a short string")
    # The header used to print `PST` as a literal, which is a lie on any event
    # that is not in the Pacific. It is data now; a file that does not say gets
    # no label rather than an invented one.
    timezone = event.get("timezone", "")
    _require(isinstance(timezone, str) and len(timezone) <= 5,
             "event timezone must be a short label")
    # THE LABEL'S ARITHMETIC HALF, and the two are ONE FACT that must move
    # together. The label is what the header prints; this is what converts a
    # synced badge's UTC clock into the frame every other time in this file is
    # written in. A file that does not say gets NO CLOCK AT ALL rather than an
    # assumed UTC==local -- see `clock_state`'s `CLOCK_NO_OFFSET`.
    utc_offset_min = event.get("utc_offset_min")
    if utc_offset_min is not None:
        utc_offset_min = parse_utc_offset(utc_offset_min)

    raw_stages = data.get("stages")
    _require(isinstance(raw_stages, list) and raw_stages, "at least one stage required")
    stages = []
    stage_by_id = {}
    for index, raw in enumerate(raw_stages):
        _require(isinstance(raw, dict), "stage must be an object")
        stage_id = raw.get("id")
        name = raw.get("name")
        short = raw.get("short", name)
        color_value = raw.get("color", [255, 255, 255])
        _require(isinstance(stage_id, str) and stage_id and stage_id not in stage_by_id, "stage id must be unique")
        _require(isinstance(name, str) and name, "stage name required")
        _require(isinstance(short, str) and 1 <= len(short) <= 8, "stage short label must be 1-8 characters")
        _require(isinstance(color_value, list) and len(color_value) == 3, "stage color must be RGB")
        color_value = tuple(int(channel) for channel in color_value)
        _require(all(0 <= channel <= 255 for channel in color_value), "stage color outside RGB")
        stage = {
            "id": stage_id,
            "name": sanitize_title(name),
            "short": sanitize_title(short),
            "color": color_value,
            "index": index,
        }
        stages.append(stage)
        stage_by_id[stage_id] = stage

    raw_sessions = data.get("sessions")
    _require(isinstance(raw_sessions, list) and raw_sessions, "at least one session required")
    sessions = []
    session_ids = set()
    for raw in raw_sessions:
        _require(isinstance(raw, dict), "session must be an object")
        session_id = raw.get("id")
        title = raw.get("title")
        stage_id = raw.get("stage_id")
        kind = raw.get("kind", KIND_TALK)
        raw_speakers = raw.get("speakers", [])
        _require(isinstance(session_id, str) and session_id and session_id not in session_ids, "session id must be unique")
        _require(isinstance(title, str) and title.strip(), "session title required")
        _require(stage_id in stage_by_id, "session references unknown stage")
        _require(kind in KINDS, "session kind must be one of {}".format(KINDS))
        _require(isinstance(raw_speakers, list), "session speakers must be a list")
        speakers = []
        for speaker in raw_speakers:
            _require(isinstance(speaker, str) and speaker.strip(), "speaker name required")
            speakers.append(sanitize_title(speaker.strip()))
        # A break or a logistics row draws no speaker line, so carrying names on
        # one would silently drop them rather than render them somewhere.
        _require(kind == KIND_TALK or not speakers, "only a talk may list speakers")
        start = parse_time(raw.get("start"))
        end = parse_time(raw.get("end"))
        _require(start < end, "session end must follow start")
        _require(day_start <= start and end <= day_end, "session outside event day")
        session_ids.add(session_id)
        sessions.append(
            {
                "id": session_id,
                "title": sanitize_title(title.strip()),
                "stage_id": stage_id,
                "kind": kind,
                "speakers": speakers,
                "start": start,
                "end": end,
                "stage_index": stage_by_id[stage_id]["index"],
            }
        )
    sessions.sort(key=lambda item: (item["start"], item["stage_index"], item["id"]))
    return {
        "schema": SCHEMA,
        "event": {
            "id": event_id,
            "name": sanitize_title(event_name),
            "start_date": start_date,
            "end_date": end_date,
            "day_start": day_start,
            "day_end": day_end,
            "generated_at": generated_at,
            "source_version": source_version,
            "timezone": sanitize_title(timezone),
            "utc_offset_min": utc_offset_min,
        },
        "stages": stages,
        "stage_by_id": stage_by_id,
        "sessions": sessions,
        "stage_sessions": sessions_by_stage(stages, sessions),
    }


def sessions_by_stage(stages, sessions):
    """One chronological list per stage, in the stages' own declared order.

    The badge shows one stage at a time — the agenda page's own tabs — so every
    view and clock rule operates on one of these lists, never on the merged one.
    A stage with nothing on it still gets an entry: an empty tab is a fact about
    the day, not an error.
    """
    grouped = [[] for _ in stages]
    for session in sessions:
        grouped[session["stage_index"]].append(session)
    return grouped


def load(path):
    with open(path, "r") as source:
        return normalize(json.load(source))


# EVERY WAY A DATA DEFECT CAN COME OUT OF `load`, and the reason the tuple is
# exactly these four rather than a bare `except`.
#
# `OSError`   the file is missing, truncated or unreadable.
# `ValueError` the designed channel: `json.load`'s parse errors and every one of
#             `normalize`'s ~30 `_require` rejections. `JSONDecodeError` is a
#             `ValueError` subclass on both CPython and MicroPython.
# `TypeError` a JSON value of the wrong Python type reaching arithmetic or
#             iteration before an `isinstance` check catches it -- e.g. a dict
#             where a stage colour's channel list belongs.
# `MemoryError` a file large enough that parsing it exhausts the heap. Rare, and
#             the one member of this tuple that is about SIZE rather than shape.
#
# `test_normalize_only_ever_raises_a_guarded_error` fuzzes the fixture and
# asserts no other class escapes, so the tuple is measured rather than guessed.
# A bare `except Exception` is deliberately NOT used: a `KeyError` or
# `AttributeError` out of here would be a bug in THIS file, and hiding our own
# bugs behind the fleet's data guard is how a defect ships quietly.
LOAD_ERRORS = (OSError, ValueError, TypeError, MemoryError)


def describe_error(error):
    """A one-line, allocation-cheap description safe to draw on a panel.

    Formatting an exception can itself fail when the failure was `MemoryError`,
    so the fallback is the class name alone and the last resort is a constant.
    """
    try:
        return "{}: {}".format(type(error).__name__, error)
    except Exception:  # noqa: BLE001
        try:
            return type(error).__name__
        except Exception:  # noqa: BLE001
            return "unreadable"


def load_guarded(path):
    """`(schedule, None)`, or `(None, description)` -- never raises on bad data.

    THE BOUNDARY, and the only reason it exists. `normalize` is deliberately
    strict and stays that way: rejecting a malformed agenda loudly is right. But
    the app's call to `load` sits at MODULE SCOPE, and `badgeware.launch()`
    catches an import-time exception into `fatal_error` -> a traceback modal ->
    any button -> `machine.reset()` -> the launcher, which re-runs the same
    failing import. One bad byte in `schedule.json` was therefore a modal-reset
    loop on every badge carrying it, fleet-wide, with no way back into the app
    and nothing on the panel naming the problem.

    Strictness belongs in the validator; survivability belongs at the boundary.
    """
    try:
        return load(path), None
    except LOAD_ERRORS as error:
        return None, describe_error(error)


# THE DAY-OF OVERRIDE.  `/` is the writable LittleFS root; `/system` is the FAT
# partition the app is baked into.  A file dropped at `/schedule.json` therefore
# replaces the agenda WITHOUT reflashing or rebuilding bytecode -- which is the
# only realistic way to fix a wrong room, a swapped speaker or a shifted start
# time on the morning of the event, when the alternative is a USB cable and a
# Disk Mode pass per badge.
OVERRIDE_PATH = "/schedule.json"
BAKED_NAME = "schedule.json"


def _exists(path):
    """`os.stat` rather than a trial `open`, so ABSENCE is not a rejection.

    The distinction is the whole design: no override present is the NORMAL state
    and must be silent, while an override that is present and unusable is a
    content mistake somebody needs to be told about.
    """
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def load_with_override(override=OVERRIDE_PATH, baked=BAKED_NAME):
    """`(schedule, source, notice, error)` -- writable root first, baked second.

    Precedence is override-then-baked so the day-of file wins, and both go
    through `load_guarded`, so neither can raise at import.

    A CORRUPT OVERRIDE FALLS BACK TO THE BAKED COPY, not to the error screen, and
    that asymmetry is deliberate. The baked agenda is known-good: it passed the
    pre-freeze gate before it shipped. Somebody fat-fingering a JSON edit at
    07:50 on the day must not be able to turn eight hundred working badges into
    eight hundred error screens -- they should get the agenda that was already
    there, plus a line on the panel saying their file was rejected. Silence would
    be worse than either: the badge would look like it had taken the edit.

    The error screen is reached only when the BAKED copy is also unusable, which
    is a build defect rather than a content one, and `notice` still travels there
    so both problems are named at once.
    """
    notice = None
    if _exists(override):
        value, error = load_guarded(override)
        if value is not None:
            return value, override, None, None
        # Sanitized HERE, once, because this string is built out of an exception
        # message and is then DRAWN: `OSError: [Errno 2] ...` carries a bracket
        # straight into the markup parser otherwise.
        notice = sanitize_title("{} rejected: {}".format(override, error))
    value, error = load_guarded(baked)
    if value is None:
        return None, None, notice, error
    return value, baked, notice, None


TBA = "TO BE ANNOUNCED"


def format_range(session):
    return "{} - {}".format(format_time(session["start"]), format_time(session["end"]))


def speaker_lines(session):
    """The lines drawn under a title: the names, the placeholder, or nothing.

    The agenda page draws the placeholder in the speakers slot of a talk whose
    line-up is not announced, and draws no slot at all on a break or a
    logistics row. Both are data, so both are decided here rather than in the
    renderer.
    """
    if session["kind"] != KIND_TALK:
        return ()
    if session["speakers"]:
        return tuple(session["speakers"])
    return (TBA,)


# ── THE FRAME SEAM: ONE CONVERSION, AT THE POINT THE CLOCK IS READ ───────────
#
# EVERYTHING DOWNSTREAM OF HERE IS EVENT-LOCAL. The badge hands us a UTC reading
# (see `parse_utc_offset` for the measured chain); the NOW layer, the window test
# and every displayed time are event-local. So the conversion happens ONCE, here,
# and no other function in this app applies an offset.
#
# ⚠ THE ONE EXCEPTION, AND IT IS NOT AN OVERSIGHT: `sync_age_minutes` must be fed
# the RAW reading, never a converted one. It subtracts badgelink's `synced_at`
# from a later reading of THE SAME CLOCK, so the frame cancels; adding an offset
# to one side of that subtraction would BREAK a calculation that is currently
# correct. Its docstring carries the whole argument. Two stamps, two frames, and
# the app names both.
#
# WHAT THIS CANNOT DETECT, stated plainly rather than pretended away: a badge
# whose clock is NOT UTC. Applying the offset assumes the reading came from
# badgelink's NTP sync, and nothing in a date tuple says where it came from. The
# assumption is defensible because the offline dial was deleted on 2026-08-25, so
# the only clock writer left in the product IS that sync -- but a badge whose
# clock was set by hand, by an older lib, or by a stock app is out-of-product
# state and this app will read it eight hours wrong without being able to say so.
# The 2026 floor and the event-window test are the only nets, and they only catch
# a reading that lands outside the event.


def civil_from_days(days):
    """Days since 1970-01-01 -> `(year, month, day)`. Hinnant's inverse.

    THE EXACT INVERSE of `days_from_civil`, and it exists because an offset can
    move the DATE and not only the clock: an evening session in the Pacific is
    the next day in UTC, so a badge reading `2026-08-15 01:00` must be told it is
    `2026-08-14 17:00` and therefore INSIDE a single-day event window. Rolling
    the day by hand ("if hours < 0 then yesterday") needs a calendar anyway, and
    a calendar written twice is a calendar that disagrees with itself.

    Floor division throughout, which is what the algorithm requires and what
    Python and MicroPython both give for `//` on ints. Hinnant's C++ carries a
    `z < 0` adjustment only because C++ truncates; adding it here would be wrong.
    Checked against CPython's own calendar across a century by the suite.
    """
    days = int(days) + 719468
    era = days // 146097
    day_of_era = days - era * 146097                     # [0, 146096]
    year_of_era = ((day_of_era - day_of_era // 1460 + day_of_era // 36524
                    - day_of_era // 146096) // 365)      # [0, 399]
    year = year_of_era + era * 400
    day_of_year = day_of_era - (365 * year_of_era + year_of_era // 4
                                - year_of_era // 100)    # [0, 365]
    month_prime = (5 * day_of_year + 2) // 153            # [0, 11]
    day = day_of_year - (153 * month_prime + 2) // 5 + 1  # [1, 31]
    month = month_prime + (3 if month_prime < 10 else -9)
    return (year + (1 if month <= 2 else 0), month, day)


def shift_stamp(stamp, minutes):
    """`(y, m, d, H, M)` moved by `minutes`, rolling the date. None on garbage.

    Whole minutes through the day number, so a shift across midnight, a month
    end, a year end or a leap day is the same arithmetic as any other shift.
    Never raises: every caller is on the once-a-second clock path.
    """
    if stamp is None:
        return None
    try:
        total = (days_from_civil(stamp[0], stamp[1], stamp[2]) * 1440
                 + int(stamp[3]) * 60 + int(stamp[4]) + int(minutes))
    except (IndexError, TypeError, ValueError):
        return None
    days, within = divmod(total, 1440)   # floors, so a negative shift rolls back
    year, month, day = civil_from_days(days)
    return (year, month, day, within // 60, within % 60)


def event_local_stamp(datetime_value, utc_offset_min):
    """A badge clock reading -> the EVENT-LOCAL `(y, m, d, H, M)`, or None.

    None means "this app has no event-local reading", and it has exactly two
    causes, both of which the caller must treat as "claim nothing":

    * the agenda carries no `utc_offset_min`, so there is no frame to read the
      clock in. **NOT the same as an offset of zero** — a missing offset must
      never be read as UTC==local, which is the whole defect this seam closes;
    * the reading itself is unusable (`stamp_from_datetime` refuses it), which is
      the dead-backup-cell hour-of-99 case.

    `utc_offset_min` is the minutes to ADD to get event-local time; PST is -480.
    """
    if utc_offset_min is None:
        return None
    return shift_stamp(stamp_from_datetime(datetime_value), utc_offset_min)


# FOUR CLOCK STATES, AND SINCE 2026-08-25 ONLY TWO PRESENTATIONS.
#
# THE MACHINERY IS UNCHANGED AND STAYS. The floor, the window test and the
# time-field validation are all correct, and `clock_state` still answers three
# values: they are what the serial marker reports, what the tests assert, and
# what a future network-synced clock will be judged by.
#
# WHAT CHANGED IS THE SCREEN. The owner's ruling is "we either get a real time
# from a server or don't assume we know time", so the three states collapse into
# two treatments:
#
#   CLOCK_TRUSTED  -> the full NOW layer: strip, phases, rails, auto-land, and
#                     `11:50 PST` in the header corner.
#   anything else  -> the plain schedule. No time on screen, no day named, no
#                     placeholder, no instruction, no key to press. SILENCE, not
#                     apology.
#
# CLOCK_OFF_DAY used to print the day it believed (`SUN 16 AUG`) as a diagnosis,
# and CLOCK_UNSET used to print `--:--` with `B SET TIME` beside it. Both are
# gone. Naming the day an unsynced RTC believes IS the assumption the ruling
# forbids, and the diagnosis it bought now lives on the serial marker, where the
# person who can act on it is standing.
#
# THE FOURTH STATE ARRIVED 2026-08-25 WITH THE OFFSET FIELD, and it is a
# DATA fault rather than a clock fault. `unset` means this badge's clock is
# detectably garbage; `no_offset` means the clock may be perfect and the AGENDA
# does not say what frame to read it in. Both draw the plain agenda -- the panel
# still has two presentations -- but they need different people to fix them, and
# the one an operator can act on is the one that must be nameable on serial. A
# fleet-wide `state=no_offset` is one line of JSON; a per-badge `state=unset` is a
# flat cell.
CLOCK_TRUSTED = "trusted"      # sane year, inside the window: NOW may be claimed
CLOCK_UNSET = "unset"          # detectably garbage: claim nothing, say nothing
CLOCK_OFF_DAY = "off_day"      # a clock we believe, on a day the event is not on
CLOCK_NO_OFFSET = "no_offset"  # no `utc_offset_min` in the data: no frame to read

CLOCK_STATES = (CLOCK_TRUSTED, CLOCK_UNSET, CLOCK_OFF_DAY, CLOCK_NO_OFFSET)

# THE YEAR FLOOR, and 2025 was too low to catch the case that actually happens.
#
# Three garbage values are recorded in `docs/engineering-findings.md`, and only
# one of them was below the old floor:
#
#   2000  the PCF85063A's own power-on default after a flat battery (:5145)
#   2021  the RP2350 system clock's default after the same flat battery (:5145)
#   2025-05-01  what `powman.c:121,208` RE-SEEDS the always-on timer to on the
#         way into every sleep, which `badgeware/rtc.py:15-16` then copies over
#         the PCF at the next boot because its own gate is `>= 2025`
#
# The third is the common one — every factory unit has been slept — and a floor
# of 2025 ADMITTED it, so a slept badge could present 2025-05-01 as a clock this
# app believed. It failed the window check and reached the same degrade by
# accident, which is why it was never visible; a two-day event in May 2025 would
# have made it a wrong NOW marker.
#
# 2026 is not a guess and not local to this app: `badgelink`'s own gate is
# `clock_boot.BUILD_FLOOR_EPOCH = 1786147200` (2026-08-08, the pinned firmware's
# build date), and a value below the firmware's own build date cannot be a real
# reading. This is the same rule expressed in years, because a date tuple is
# what the badge's two clocks hand us.
#
# IT IS TESTED AGAINST THE EVENT-LOCAL YEAR, not the raw reading, because
# everything downstream of the frame seam is event-local and a floor applied in
# one frame and a window in another is the class of bug this whole change exists
# to remove. The two frames differ by at most 14 hours, and none of the three
# recorded garbage values is within 14 hours of a year boundary, so no real
# verdict moves either way.
TRUSTED_YEAR = 2026


def clock_state(datetime_value, event):
    """`(one of the four `CLOCK_*` values, the event-local stamp)`. Never raises.

    ⚠ **PASS THE RAW BADGE READING, NOT A CONVERTED ONE.** This function does the
    UTC -> event-local conversion ITSELF, out of the event's own
    `utc_offset_min`, so handing it a stamp that has already been shifted applies
    the offset twice. It reads the offset from `event` rather than taking it as an
    argument precisely so that the conversion cannot be forgotten at a call site
    — the same reasoning `ClockArgumentTests` records about `set_clock`'s state
    argument, and the same failure shape: nothing would raise, every screen would
    render, and the badge would be confidently eight hours wrong.

    **IT RETURNS THE STAMP IT CONVERTED, and that second return is what makes the
    ONE SEAM claim true rather than aspirational.** It used to return the verdict
    alone, so `_refresh_clock` called `event_local_stamp` a second time with the
    same reading and the same offset to get the stamp it needed for the minute,
    the phases, freshness and the view: one conversion FUNCTION, but two
    conversion INVOCATIONS per second, and a documented guarantee that the app
    "cannot double-shift" resting on the two call sites agreeing forever. An
    adversarial review (2026-08-25, `dist/sol-reviews/schedule-waves-review.md`
    wave 3) named that gap. Handing the stamp back closes it structurally: there
    is now exactly ONE conversion invocation in the app, `FrameWiringTests`
    asserts that by AST, and the second shift costs nothing because it no longer
    happens.

    THE STAMP IS RETURNED EVEN WHEN THE VERDICT REJECTS IT, and that is
    deliberate rather than sloppy. A 2021 reading is a perfectly well-formed
    event-local stamp that fails the year floor: the view is still handed it (the
    NOW layer is gated on `trusted`, not on the stamp being absent) and only
    detectably GARBLED readings and a missing offset yield `None`. That is exactly
    what the two `event_local_stamp` calls used to produce, so no caller sees a
    changed value.

    `CLOCK_NO_OFFSET` comes FIRST and outranks every other verdict, because
    without a frame there is nothing to judge. A 2021 clock and a perfect one are
    equally unreadable, and the actionable fault is the agenda file, which is the
    same on all 800 badges.

    The TIME fields are validated too, not only the date fields, and that is a
    defect fix rather than tidiness: `clock_is_trusted` checked the date while
    `clock_minutes` checked the time, so a caller that combined them naively kept
    `trusted` True while the minute was `None` — and the `None` reached the view
    and killed the app on its first frame. That is the dead-backup-cell symptom,
    where a PCF85063A comes up reporting an hour of 99. `event_local_stamp`
    refuses both halves at once now, so they cannot disagree.
    """
    if event.get("utc_offset_min") is None:
        return CLOCK_NO_OFFSET, None
    local = event_local_stamp(datetime_value, event.get("utc_offset_min"))
    if local is None:
        return CLOCK_UNSET, None
    year, month, day = local[0], local[1], local[2]
    if year < TRUSTED_YEAR or year > 2199:
        return CLOCK_UNSET, local
    current = (year, month, day)
    if event["start_date"] <= current <= event["end_date"]:
        return CLOCK_TRUSTED, local
    return CLOCK_OFF_DAY, local


def clock_is_trusted(datetime_value, event):
    """The one question the NOW layer asks. Kept as the predicate.

    `clock_state` is the richer answer; this is the half of it that gates a NOW
    claim. Its callers were the dial (twice) and the NOW layer; the dial is gone,
    so `schedule/badge/probe.py`'s clock-trust row is the remaining one and it is
    a measurement rather than a screen. Kept rather than inlined because the
    predicate is the whole doctrine in one name.

    Takes the RAW badge reading, exactly like `clock_state`, and an event with no
    `utc_offset_min` therefore answers False for every reading — which is the
    point of the field.

    `[0]` because `clock_state` hands back the stamp it converted as well as the
    verdict; a predicate has no use for the stamp.
    """
    return clock_state(datetime_value, event)[0] == CLOCK_TRUSTED


def clock_minutes(datetime_value):
    """Minutes past midnight out of any tuple with an hour at [3] and minute [4].

    IT DOES NOT KNOW WHICH FRAME IT IS IN, and the caller has to. The app feeds
    it the EVENT-LOCAL stamp from `event_local_stamp`, because the minute this
    returns is what the NOW layer compares against `HH:MM` session times and what
    the header prints under the `PST` label. Both a badge clock tuple
    (7 or 8 elements) and a 5-element stamp work: only [3] and [4] are read.
    """
    try:
        hour = int(datetime_value[3])
        minute = int(datetime_value[4])
    except (IndexError, TypeError, ValueError):
        return None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return hour * 60 + minute


def current_indices(sessions, now_minutes):
    if now_minutes is None:
        return ()
    return tuple(
        index for index, session in enumerate(sessions)
        if session["start"] <= now_minutes < session["end"]
    )


def next_index(sessions, now_minutes):
    if now_minutes is None:
        return None
    for index, session in enumerate(sessions):
        if session["start"] > now_minutes:
            return index
    return None


def initial_index(sessions, now_minutes):
    if not sessions:
        return 0
    current = current_indices(sessions, now_minutes)
    if current:
        return current[0]
    upcoming = next_index(sessions, now_minutes)
    return len(sessions) - 1 if upcoming is None else upcoming


# ── THE NOW LAYER ────────────────────────────────────────────────────────────
#
# Four phases rather than a highlight and nothing else. "What is on now" is only
# half of what a wearer standing in a hallway wants; the other half is which
# rows they have already missed, which is the cheapest thing on the screen to
# get right and the one this app never drew.
PHASE_PAST = "past"      # ended: de-emphasised, still readable, never hidden
PHASE_NOW = "now"        # start <= now < end
PHASE_NEXT = "next"      # the first row that has not started yet
PHASE_LATER = "later"    # after that
PHASES = (PHASE_PAST, PHASE_NOW, PHASE_NEXT, PHASE_LATER)


def session_phases(sessions, now_minutes):
    """One phase per session, or `()` when there is no minute to compare against.

    COMPUTED ON THE CLOCK REFRESH, NOT IN A FRAME. It is once-a-second integer
    work over one stage, and returning a tuple the view keeps means `draw` does
    a tuple index per visible block instead of re-deciding the day. Empty rather
    than all-`PHASE_LATER` when the clock is untrusted, so a caller cannot
    accidentally render a de-emphasis it has no clock to justify.
    """
    if now_minutes is None:
        return ()
    upcoming = next_index(sessions, now_minutes)
    phases = []
    for index, session in enumerate(sessions):
        if session["start"] <= now_minutes < session["end"]:
            phases.append(PHASE_NOW)
        elif session["end"] <= now_minutes:
            phases.append(PHASE_PAST)
        elif index == upcoming:
            phases.append(PHASE_NEXT)
        else:
            phases.append(PHASE_LATER)
    return tuple(phases)


# What the one-line strip is honestly able to say. `DONE` and `EMPTY` used to be
# the same sentence, and that was a lie one of them told: at 19:00 on the event
# day a finished Main Stage read "NOTHING SCHEDULED ON THIS STAGE", which is what
# an EMPTY stage says. A day that is over and a stage that was never on are
# different facts, and the clock is trusted in both cases, so the app knows.
STRIP_NOW = "now"
STRIP_NEXT = "next"
STRIP_DONE = "done"
STRIP_EMPTY = "empty"


def strip_state(sessions, now_minutes):
    """`(kind, index)` for the NOW strip: what to say, and about which row.

    `index` is None for the two states that name no row. Deciding this here
    rather than inside the draw is what makes the day-boundary cases testable
    without a screen: before the first row, between two, after the last, and on
    a stage with nothing on it at all.
    """
    if not sessions:
        return STRIP_EMPTY, None
    if now_minutes is None:
        return STRIP_EMPTY, None
    current = current_indices(sessions, now_minutes)
    if current:
        return STRIP_NOW, current[0]
    upcoming = next_index(sessions, now_minutes)
    if upcoming is not None:
        return STRIP_NEXT, upcoming
    return STRIP_DONE, len(sessions) - 1


def format_gap(minutes):
    """A short relative duration: `45 MIN`, `2 H`, `1 H 20`.

    Uppercase and ASCII because it is drawn beside `NEXT` in the same face as
    everything else, and abbreviated because the strip shares one line with a
    session title. Negative or zero reads as `NOW`, so a caller cannot print
    "IN 0 MIN" on the minute a session starts.
    """
    minutes = int(minutes)
    if minutes <= 0:
        return "NOW"
    if minutes < 60:
        return "{} MIN".format(minutes)
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return "{} H".format(hours)
    return "{} H {:02d}".format(hours, rest)


# NO CALENDAR NAMES, AND NOTHING FORMATS A DATE FOR THE PANEL ANY MORE.
#
# Two functions lived here and both were killed by the 2026-08-25 rulings.
# `format_day` (`FRI 14 AUG`) printed the day an UNTRUSTED clock believed, which
# is exactly the assumption the clock ruling forbids. `format_date_short`
# (`14 AUG`) dated the agenda file inside `OFFLINE COPY 14 AUG`, and the
# freshness ruling replaced every one of those sentences with a glyph.
#
# So the only relative reading this app still formats is `format_gap`, which the
# NOW strip spends on a TRUSTED clock. `MONTHS` and `WEEKDAYS` are gone with
# their callers; a future feature that needs them should measure the widest
# member again rather than trust a template (see the ellipsized clock corner in
# `host/evidence/2026-08-24-ux/README.md`).


def days_from_civil(year, month, day):
    """Days since 1970-01-01, by integer arithmetic with no epoch opinion.

    Hinnant's days-from-civil, nine lines, and the reason it is here rather
    than `time.mktime`: MicroPython's bare-metal ports count seconds from 2000
    while CPython counts from 1970, so `mktime` would surface as a thirty-year
    error on hardware and nowhere else (`docs/engineering-findings.md`, the
    transcribed-calendar finding, where the same choice was made for the same
    reason). Nothing in this app needs an absolute epoch; it needs DIFFERENCES,
    and a difference of day numbers has no epoch in it at all.
    """
    year = int(year)
    month = int(month)
    year -= 1 if month <= 2 else 0
    era = (year if year >= 0 else year - 399) // 400
    year_of_era = year - era * 400
    day_of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + int(day) - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146097 + day_of_era - 719468


def stamp_from_datetime(datetime_value):
    """`(y, m, d, hour, minute)` out of a badge clock tuple, or None.

    Both of the badge's clocks put the date in elements 0-2 and the hour and
    minute in 3-4 (the PCF's tuple diverges only at element 5), so one reader
    serves either. Returns None rather than raising, because every caller is on
    a frame path.
    """
    try:
        year, month, day = (int(datetime_value[index]) for index in range(3))
        hour = int(datetime_value[3])
        minute = int(datetime_value[4])
    except (IndexError, TypeError, ValueError):
        return None
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return (year, month, day, hour, minute)


def minutes_between(earlier, later):
    """`later - earlier` in whole minutes, for two `(y, m, d, H, M)` stamps."""
    if earlier is None or later is None:
        return None
    days = days_from_civil(later[0], later[1], later[2]) - days_from_civil(
        earlier[0], earlier[1], earlier[2]
    )
    return days * 1440 + (later[3] * 60 + later[4]) - (earlier[3] * 60 + earlier[4])


def parse_stamp(value):
    """`YYYY-MM-DD HH:MM` -> `(y, m, d, H, M)`, reusing the strict parsers.

    ONE new field, NO new parsing rules. `parse_date` and `parse_time` are
    already strict and already fuzzed by the suite, so the optional stamp the
    schema gains below cannot introduce a rejection path nothing has tested.
    """
    _require(isinstance(value, str), "stamp must be 'YYYY-MM-DD HH:MM' text")
    parts = value.split(" ")
    _require(len(parts) == 2, "stamp must be 'YYYY-MM-DD HH:MM' text")
    year, month, day = parse_date(parts[0])
    minutes = parse_time(parts[1])
    return (year, month, day, minutes // 60, minutes % 60)


# ── FRESHNESS: WHAT THE BADGE CAN HONESTLY SAY ABOUT ITS OWN AGENDA ──────────
#
# THIS APP MAKES NO NETWORK CALL AND NEVER WILL. What it does is read state a
# service on the same badge already maintains, plus two optional stamps carried
# inside the agenda file itself, and say only what those support.
#
# WHAT BADGELINK ACTUALLY WRITES, read out of `badgelink/badge/badgelink/
# schedule_store.py:68-69,506-543` rather than assumed:
#
#     /state/schedule.json   {"schema": 1, "version": <str|null>, "rows": [...],
#                             "synced_at": <int epoch seconds, OPTIONAL>}
#
# written temp -> flush -> os.sync -> os.rename, so a reader never sees a torn
# file. `version` is `"<event_count>:<micros>"` from the server's own
# `badgelink_schedule_version()` RPC, where micros is
# `max(schedule_events.updated_at)` in Unix epoch microseconds.
#
# THREE THINGS THAT WOULD BE EASY TO ASSUME. THE FIRST ONE CHANGED:
#
# 1. **IT CARRIES A SYNC TIME NOW, AND ITS ABSENCE IS A REAL ANSWER.** This item
#    used to read "It is not a sync time. There is no `synced_at`, `fetched_at`
#    or `checked_at` field anywhere in that record, and nothing in badgelink
#    writes one" -- and it ended by asking for exactly one field. **badgelink's
#    Lane F added it on 2026-08-24** (`schedule_store` contract rule 6):
#    `synced_at`, epoch SECONDS, taken from the badge's own NTP-gated corrected
#    clock at the moment a sync succeeded, written by their `save` and REQUIRED
#    BY NO READER.
#
#    Two entirely ordinary badges have no such field -- one whose cache predates
#    it, and one that synced while its clock was untrustworthy (their writer
#    omits the key rather than stamping a 2021 date; there is no `null` form) --
#    so **a reader must render absence as "unknown", never as "very old"**, and
#    the fleet will carry both libs at once. `read_link_state` reads it and
#    `freshness` falls all the way back to the pre-Lane-F behaviour without it.
#
#    What it buys is NOT the version comparison, which it cannot answer: it is
#    the STALENESS threshold, which stood the content's build age in for "how
#    long since this badge could have learned about something newer". See
#    `freshness`.
# 2. **Their rows are not this app's content.** Their schema is 1 and carries
#    `{title, starts_at, ends_at, location, track}` ISO rows with no stage, no
#    speaker list and no `HH:MM`; this app's schema is 2 and is matched exactly.
#    Feeding one to the other is a guaranteed rejection, so their cache is
#    consumed HERE AS A FRESHNESS SIGNAL ONLY, never as an agenda.
# 3. **So a version alone cannot date what is on screen.** Which is why the
#    comparison below is version-to-version and not timestamp-to-timestamp: the
#    agenda file may record the badgelink `version` it was built from, and two
#    version strings compare exactly, with no timezone and no epoch in it. A
#    server edit time in UTC against an event-local build time would have been
#    wrong by the event's UTC offset — eight hours for PST, enough to invent an
#    OUT OF DATE verdict inside a single day.
#
# The file's mtime was the other candidate and is deliberately NOT used: LittleFS
# mtime support on this port is unmeasured, a badge writes it with whatever clock
# it had (which is untrusted in exactly the case that matters), and it is
# badgelink's file, so its rewrite policy on an unchanged poll is theirs to
# change. Two explicit fields inside the agenda beat one filesystem attribute
# nobody has measured.
BADGELINK_STATE_PATH = "/state/schedule.json"
# Duplicated, not imported, and pinned by `BadgelinkContractTests`. A
# module-scope import of a `/system/lib` file a half-refreshed badge might not
# carry raises inside `launch()`, which resets the badge — the same defect class
# this app's guarded loader exists to prevent. The precedent is
# `badgelink/badge/badgelink/badgecard_state.py`, which duplicates `badgecard`'s
# literals and pins them with a test for exactly this reason.
BADGELINK_STATE_SCHEMA = 1
# Their own cap (`schedule_store.MAX_BYTES`), read the same way they read it:
# one byte past the limit, so an oversize file is refused rather than parsed.
BADGELINK_MAX_BYTES = 65536

# Four verdicts. The first two are FACTS about matching version strings; the
# third is a JUDGEMENT with a threshold; the fourth is the absence of evidence.
FRESH_SYNCED = "synced"          # our content is what the server last published
FRESH_SUPERSEDED = "superseded"  # the server has published something else
FRESH_STALE = "stale"            # a linked badge, old content, never verified
FRESH_OFFLINE = "offline"        # no link state at all: nothing to compare to

# HOW OLD IS TOO OLD, and why an offline badge is never told it is stale.
#
# The baked agenda is built days before the event and that is CORRECT — it is the
# known-good copy that passed the pre-freeze gate. An offline fleet is this
# feature's whole premise, so "MAY BE OUT OF DATE" on every badge every day
# would be a false alarm on the normal case, and an alarm that is always on is
# not read. The judgement therefore requires BOTH halves: the badge has link
# state (so it could have been updated) and the content it is showing was never
# verified against it. Twelve hours means a linked badge showing yesterday
# evening's build on the morning of the event says so, and one showing a file
# loaded at breakfast does not.
STALE_MINUTES = 720


def read_link_state(path=BADGELINK_STATE_PATH, open_fn=None):
    """`(version, synced_at)` out of badgelink's record. Never raises.

    ONE OPEN FOR BOTH FIELDS. This was `read_link_version` until badgelink's
    Lane F added `synced_at` (2026-08-24); reading the file twice would let a
    version and a sync time come from two different writes of a file another
    lane rewrites atomically, which is the one thing their single-rename
    discipline exists to prevent.

    READ-ONLY, and this app must never write or delete that file: badgelink
    keeps an in-RAM copy of the same value, so removing the file at runtime does
    not invalidate their cache and would leave their next check answering
    `schedule_current` against content that is gone
    (`benchmark/results/reports/2026-08-22-badgelink-ft-b-appliers.md`).

    Mirrors their own strict schema equality, so a future badgelink bump reads
    as "no state" here instead of being misparsed.

    `synced_at` IS EPOCH SECONDS AND ITS ABSENCE IS A REAL ANSWER, which is
    their contract rule 6 and not an implementation detail. Two entirely
    ordinary badges have no such field: one whose cache predates the field, and
    one that synced while its clock was not trustworthy — their writer omits the
    key rather than putting a 2021 stamp on disk, and there is no `null` form.
    **So absence must render as "unknown" here, never as "very old".** The shape
    check below duplicates `schedule_store.synced_at_value` — positive plain
    integer, `bool` excluded explicitly because `True` is an `int` and
    `"synced_at": true` is the one value that would pass every later check — and
    `BadgelinkContractTests` pins it against their source.
    """
    opener = open_fn or open
    try:
        with opener(path, "r") as source:
            raw = source.read(BADGELINK_MAX_BYTES + 1)
        if raw is None or len(raw) > BADGELINK_MAX_BYTES:
            return None, None
        record = json.loads(raw)
        if not isinstance(record, dict):
            return None, None
        if record.get("schema") != BADGELINK_STATE_SCHEMA:
            return None, None
        version = record.get("version")
        version = version if isinstance(version, str) and version else None
        return version, synced_at_seconds(record.get("synced_at"))
    except LOAD_ERRORS:
        return None, None


def synced_at_seconds(value):
    """Their `synced_at` as usable epoch seconds, or None meaning "unknown".

    A DUPLICATE OF THEIR OWN SHAPE CHECK, refusing rather than repairing, for
    the reason the whole `BADGELINK_*` block above exists: importing
    `schedule_store` at module scope would be a `/system/lib` import inside
    `launch()` on a badge that might not carry it, which resets the badge.

    `isinstance(value, bool)` first is not defensive tidiness. `True` is an
    `int` in Python and in MicroPython, so `"synced_at": true` would otherwise
    become the epoch second 1 — a sync in January 1970, which every threshold
    below would read as "very old" rather than as "unusable".
    """
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    return value if value > 0 else None


def epoch_from_stamp(stamp):
    """`(y, m, d, H, M)` -> seconds since 1970 IN THE STAMP'S OWN FRAME.

    NO TIMEZONE IN IT, and that is the whole reason this is safe to compare
    against badgelink's `synced_at`. Read
    `docs/engineering-findings.md`'s transcribed-calendar finding and
    `days_from_civil` above for why the arithmetic is hand-rolled rather than
    `time.mktime` (MicroPython's bare-metal ports count from 2000, CPython from
    1970 — a thirty-year error that appears on hardware and nowhere else).
    """
    if stamp is None:
        return None
    try:
        return (days_from_civil(stamp[0], stamp[1], stamp[2]) * 86400
                + int(stamp[3]) * 3600 + int(stamp[4]) * 60)
    except (IndexError, TypeError, ValueError):
        return None


def sync_age_minutes(synced_at, now_stamp):
    """Minutes since badgelink last synced, or None. **Frame-free by design.**

    THE UTC QUESTION, WHICH IS THE ONLY REASON THIS IS NOT A ONE-LINER, and the
    reason it is safe where `generated_at` against a server time would not be.

    `synced_at` is epoch seconds taken from the BADGE'S OWN corrected clock
    (`network_runtime._epoch`, `clock_boot.evaluate_ntp`-gated) at the moment the
    sync succeeded. `now_stamp` is a later reading of THAT SAME CLOCK. So this is
    a difference between two readings of one clock, and **whatever frame that
    clock is in cancels** — exactly the argument `days_from_civil` makes about
    day numbers. No offset is needed and none may be applied.

    Contrast the trap the freshness design already avoids: a SERVER's UTC edit
    time against an event-local build stamp is two clocks, and it would be wrong
    by the event's offset — eight hours for PST, enough to invent a verdict
    inside a single day. That is why the version comparison is version-to-version
    and why this one is same-clock-to-same-clock.

    ⚠ **SO THIS IS THE ONE PLACE THAT MUST NOT BE HANDED THE EVENT-LOCAL STAMP,
    AND THAT IS NOW A LIVE HAZARD RATHER THAN A NOTE.** The frame question this
    docstring used to leave open was answered on 2026-08-25: the agenda carries
    `event.utc_offset_min` and the app converts the UTC clock to event-local at
    one seam, so an event-local stamp is now sitting right there in
    `_refresh_clock` next to the raw one. Feeding it to this function would put
    the offset on ONE side of the subtraction and make a correct calculation
    wrong by eight hours. The app passes the RAW stamp here and the LOCAL stamp
    to `freshness`, and a source-level test pins which one goes where.
    """
    if synced_at is None:
        return None
    now_seconds = epoch_from_stamp(now_stamp)
    if now_seconds is None:
        return None
    age = (now_seconds - synced_at) // 60
    # A sync in the future is not an age. Same rule as a clock behind the build
    # stamp: treat it as unknown rather than negative, because the clock is the
    # suspect part and "unknown" is a state this app already renders honestly.
    return None if age < 0 else age


def freshness(event, link_version, now_stamp=None, link_synced_at=None):
    """`(verdict, age_minutes)` for the agenda currently on screen.

    `age_minutes` is the age of the content's own build stamp and is None
    whenever either half is missing — an agenda with no `generated_at`, or a
    clock this app does not believe. The two version verdicts do NOT need a
    clock: comparing what we were built from against what the server last
    published is string equality, so a badge with a dead RTC can still be told
    its agenda has been superseded.

    ⚠ **`now_stamp` MUST BE THE EVENT-LOCAL STAMP**, because `generated_at` is
    event-local and this compares the two. It is the opposite requirement to
    `sync_age_minutes`, which must have the raw one; the two functions sit next to
    each other and take stamps in different frames on purpose. A badge with no
    `utc_offset_min` has no event-local stamp at all, so it arrives here as None
    and the content age becomes "unknown" — which is HONEST rather than degraded:
    dating an event-local build stamp against an unknown-frame clock could be up
    to 14 hours out, and `STALE_MINUTES` is 12 hours, so the frame alone could
    flip the verdict. The two version FACTS survive it, which is the important
    half.

    ── `synced_at` LANDED 2026-08-24 AND IT GATES NOTHING HERE ──

    badgelink's Lane F added `synced_at` to `/state/schedule.json` — the field
    this lane asked for. `read_link_state` reads it, `sync_age_minutes` dates it
    and the app puts it on the serial marker. **It deliberately decides no
    verdict on this screen, and the reason is in badgelink's own contract rather
    than in a preference.**

    **IT DATES THE LAST STORED CHANGE, NOT THE LAST CHECK.** Their cheap path is
    an early return: `network_runtime._schedule_version_response` compares one
    string and, when the version is unchanged, emits `schedule_current` and
    touches no filesystem at all — which is that sync's whole performance claim.
    `save` is reached only when the schedule actually CHANGED, so the stamp only
    moves then. Their register says it in one line: *"A freshness line built on it
    says 'content as of', not 'checked'."*

    **SO IT CANNOT CARRY A STALENESS THRESHOLD, AND BUILDING ONE ON IT WOULD BE
    EXACTLY THE ALARM THIS FEATURE FORBIDS.** A badge that polls every thirty
    seconds and finds no change all day keeps a day-old stamp. At an event whose
    agenda is frozen — which is every event, after the pre-freeze gate — EVERY
    badge's schedule stops changing, so every badge would cross a 12-hour
    threshold and light amber while being perfectly current. `STALE_MINUTES`'s own
    comment already rules on that class of error: *an alarm that is always on is
    not read.* **The first draft of this function DID gate on it**, and their
    register's one line is what caught it before it shipped.

    **WHAT IT HONESTLY IS: A ONE-DIRECTIONAL LOWER BOUND on the last successful
    sync.** Recent means the badge demonstrably talked to the server recently.
    Old means UNKNOWN — it may have polled a minute ago and had nothing to do. A
    fact that can only reassure, never accuse; and there is no verdict here whose
    confidence it can raise, because the two version verdicts are already facts
    and the unverifiable branch stays unverifiable however live the link is.

    **THE CROSS-LANE ASK THIS LEAVES OPEN, stated the way the first one was:**
    what this app wanted was a LAST-CHECK time. One stamp written on the cheap
    path too, or a separate `checked_at` beside `synced_at`, would turn the
    staleness judgement into a fact. It is their file and their performance claim
    to weigh — and a reader in this lane must never infer "checked" from "stored".

    So the rules below are exactly the pre-2026-08-24 ones. `link_synced_at` is
    accepted, dated and reported without being believed for more than it says.
    """
    built = event.get("generated_at")
    source_version = event.get("source_version")
    age = minutes_between(built, now_stamp) if (built and now_stamp) else None
    if age is not None and age < 0:
        # A clock behind the build stamp is not an age. Treat it as unknown
        # rather than printing a negative one; the clock is the suspect part.
        age = None
    if link_version and source_version:
        if link_version == source_version:
            return FRESH_SYNCED, age
        return FRESH_SUPERSEDED, age
    if link_version:
        # A linked badge showing content that was not built from the link. Old
        # or undatable content is worth a warning; recent content is not.
        if age is None or age > STALE_MINUTES:
            return FRESH_STALE, age
        return FRESH_OFFLINE, age
    return FRESH_OFFLINE, age


# ── THE FRESHNESS MARK, WHICH REPLACED FOUR SENTENCES ────────────────────────
#
# OWNER RULING, 2026-08-25: the text banners were too loud. "Not super obvious,
# but easy to tell someone what it means if it matters." So the header carries a
# small glyph instead of a phrase, and `UPDATED 30 MIN AGO` / `OUT OF DATE` /
# `MAY BE OUT OF DATE` / `OFFLINE COPY 14 AUG` / `DAY-OF COPY 14 AUG` are all
# deleted. There are no words on the panel about freshness at all.
#
# WHY FIVE MARKS AND NOT FOUR. The ruling sketched "fresh / stale-or-unknown /
# offline-copy / day-of-override", which folds SUPERSEDED into STALE. They are
# kept apart because they are different KINDS of statement and the code has
# always argued so: SUPERSEDED is two version strings that differ, a FACT that
# needs no clock and the one freshness fact that matters most; STALE is a
# JUDGEMENT against a 12-hour threshold. Collapsing them would have thrown away
# the certain one to save a row of a README table. `freshness` still answers four
# verdicts; the split into five marks happens here, because whether the file was
# hand-dropped is a fact about the SOURCE rather than about the version.
#
# GEOMETRY IS IN `schedule_view._draw_fresh_mark` and the meanings are tabulated
# once, for staff, in `schedule/README.md`. Two shapes here were redrawn after
# the 8x contact sheet: SUPERSEDED was two stacked bars, which read as an EQUALS
# sign (the opposite of what it means), and it was inset by a unit, which the
# rasteriser turned into a lump with no apex at 6 px.
#
# SHAPE CARRIES THE MEANING AND COLOUR ONLY REINFORCES IT. Every pair below is
# distinguishable with the colour removed, because a lit panel at 400 mm is not
# where anybody should be resolving green against amber.
MARK_SYNCED = "mark_synced"          # a solid blob: this IS what the server published
MARK_SUPERSEDED = "mark_superseded"  # an UP TRIANGLE: there is a newer agenda than this one
MARK_STALE = "mark_stale"            # a HOLLOW RING: linked, but this cannot be vouched for
MARK_OFFLINE = "mark_offline"        # a DASH: no link at all, so nothing to check against
MARK_DAY_OF = "mark_day_of"          # a PLUS: somebody added a file to this badge by hand

MARKS = (MARK_SYNCED, MARK_SUPERSEDED, MARK_STALE, MARK_OFFLINE, MARK_DAY_OF)


def freshness_mark(verdict, from_override=False):
    """Which glyph the header corner draws. Always exactly one, never nothing.

    A BLANK CORNER WAS THE OTHER CANDIDATE for the offline case, on the grounds
    that an offline fleet is this feature's premise so the normal state should
    cost nothing. It was rejected: a mark that is sometimes absent cannot be
    explained to a member of staff ("if you see nothing, that means…" is the
    sentence nobody finishes), and the offline dash is already the quietest thing
    on the screen. One glyph, always, in the same place.
    """
    if verdict == FRESH_SYNCED:
        return MARK_SYNCED
    if verdict == FRESH_SUPERSEDED:
        return MARK_SUPERSEDED
    if verdict == FRESH_STALE:
        return MARK_STALE
    return MARK_DAY_OF if from_override else MARK_OFFLINE
