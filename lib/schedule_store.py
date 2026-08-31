"""The badge's schedule cache, and the sanitization contract for whoever draws it.

WHERE SANITIZATION LIVES, AND WHY -- the decision Card FT-B was asked to make.

Card FT-S recorded the trap: ``schedule_events.title`` and ``location`` are
DELIBERATELY not charset-constrained, unlike ``badges.display_name`` and the
``set_name`` payload. A schedule is typed into a web page by an organizer and the
measured nonzero-ink set excludes characters ordinary talk titles carry -- em
dashes, curly quotes, anything outside Latin-1 -- so rejecting a real title would
be the worse failure. The consequence is that an unsanitized title draws BLANK
GLYPHS, silently, with no exception to catch.

THE THREE CANDIDATE HOMES, and why the writer wins:

* THE RENDERER ALONE (what FT-S sketched). Lossless and face-aware, and it puts
  the responsibility on the one place that can forget. The failure mode of
  forgetting is a wearer looking at an empty box -- no traceback, no test failure,
  no log line. A rule enforced by everyone who ever writes a view is not
  enforced.
* THE WRITER ALONE. Cannot forget, runs once per schedule change instead of once
  per frame, and one function is testable against the real ink set. But it is
  LOSSY: the organizer's actual text is gone, so a firmware with a wider glyph
  set could never recover it without a resync, and the substitution choice is
  made by a module that knows nothing about the face or the panel.
* **BOTH, SPLIT BY RESPONSIBILITY -- and this is what ships.** The writer
  sanitizes and stores the RESULT as ``title``, so every present and future view
  is safe by default and none of them has to remember. When sanitizing changed
  something, the VERBATIM text is kept beside it as ``title_raw``, so nothing is
  actually lost and a future face-aware renderer can re-derive. Plain ASCII rows
  -- the overwhelming majority -- carry no ``title_raw`` at all, so the cost is
  paid only by the rows that need it.

**THE CONTRACT, WRITTEN DOWN, for the parked schedule app's rebuild (which is NOT
this card's scope):**

1. ``title``, ``location``, ``speaker`` and ``description`` in
   ``/state/schedule.json`` are DRAWABLE: every character in them is in
   :data:`SAFE_CHARS`, the measured nonzero-ink intersection of the ROM faces, so
   none of them can come out as a blank box.

   ⚠ **DRAWABLE IS NOT THE SAME AS SAFE TO HAND THE RECT FORM OF**
   ``screen.text``, **and this rule said "draw them directly" until 2026-08-26.**
   That API parses ``[renderer:args]`` and an unknown renderer raises INSIDE
   ``update()`` -- a traceback modal every frame, on every badge holding the
   cache. ``[`` has ink, so it is in :data:`SAFE_CHARS` and :func:`sanitize`
   passes it through untouched; a backend row reading
   ``speaker = '[sprite:x] Ada'`` reproduces the crash a title carried on
   2026-08-20. **A view drawing through the rect form runs
   :func:`escape_markup` first** -- one call, total, allocation-free on a plain
   row. The x/y form parses nothing and needs it not.
2. ``title_raw``/``location_raw`` are present only when they differ, and they are
   NOT drawable. A view that reads one owns its own substitution and must run it
   through :func:`sanitize` (then rule 1's :func:`escape_markup`) or its own
   face-aware equivalent.
3. A view that builds a string for the panel from any other source calls
   :func:`sanitize`, and :func:`escape_markup` too if it is drawing through the
   rect form. Both are total, neither raises, and :func:`sanitize` is bounded.
4. ``starts_at``/``ends_at`` are the server's ISO strings, unmodified, and are
   never drawn without formatting -- they are for ordering and for "on now".
5. ``track`` already has a charset CHECK in the schema
   (``^[a-z][a-z0-9_-]{0,31}$``) and needs no sanitizing. It is the one schedule
   field that inherits ``set_name``'s kind of guarantee.
6. **``synced_at`` IS ADDITIVE, AND ITS ABSENCE IS A REAL ANSWER** (added
   2026-08-24 for the schedule app's freshness line, which asked for it). It is
   epoch SECONDS at the moment :func:`save` persisted a successful sync, taken
   from the badge's CORRECTED clock -- the caller's NTP-gated reader, not
   ``time.time()`` raw -- and it is the only field here that describes the FETCH
   rather than the schedule. **It is written by :func:`save` and REQUIRED BY NO
   READER.** :func:`load`, :func:`cached_version` and :func:`stored_row` all
   tolerate its absence, because two entirely ordinary badges have no such field:
   one whose cache was written before this existed, and one that synced while its
   clock was not trustworthy (the writer omits the key rather than putting a 2021
   stamp on disk -- there is no ``null`` form). So a reader must render
   "unknown", never "very old", when it is missing, and **"absence means a
   pre-CX cache" is the LIKELIEST reason but not the only one.**

   It is a RECORD field, beside ``schema``/``version``/``rows`` -- never a row
   field, and :func:`stored_row` refuses a row that carries one, which is the
   check that keeps a per-row stamp from being added by accident. The cost is
   about 28 bytes ONCE PER FILE rather than per row, which is the only reason it
   is affordable at all: :data:`MAX_BYTES` now has 5,313 B of slack over the
   worst legal record and 64 copies of anything would eat it.

   **The READING half is the schedule lane's, not this module's.** :func:`load`
   deliberately does not surface it yet: their app owns the freshness verdict and
   its thresholds (`schedule/badge/schedule/schedule_model.py`, the
   ``BADGELINK_STATE_PATH`` block), and that block still says badgelink writes no
   such field. Landing a writer and a reader from two lanes in one commit is how
   a contract gets two owners.

7. 🔧 **AN ASK FROM THE SCHEDULE LANE, 2026-08-24, NOT A RULE THIS MODULE HAS
   ACCEPTED: whatever writes their agenda should carry the EVENT'S UTC OFFSET.**
   Recorded here because rule 6 is where their last request landed and this is the
   next one; the decision is badgelink's.

   *Why it exists.* A paired badge's clock reads UTC — ``ntptime.settime()`` sets
   it from ``gmtime`` and the firmware boot sync copies it verbatim, measured in
   VAL-041-BLR — while every time in a schedule-app agenda is EVENT-LOCAL. Since
   2026-08-24 their schema carries ``event.utc_offset_min`` and their app converts
   with it, and **an agenda that lacks it makes the badge claim no time at all**
   (their ``CLOCK_NO_OFFSET`` state: the plain list, no NOW marker). With their
   offline dial deleted, a synced fleet is the only route to a NOW marker, so the
   frame is not optional to them.

   *Nothing is broken today.* This module's rows are consumed by them as a
   FRESHNESS SIGNAL only — their schema is 2 and matched exactly, ours is 1, so
   feeding one to the other is a guaranteed rejection. The ask bites the day
   anything here writes THEIR schema (their "Phase 2 fetch").

   *What is wanted, precisely.* A **record** field beside
   ``schema``/``version``/``rows``, in the shape their validator already takes
   (whole minutes to ADD to UTC, a multiple of 15 inside ``-720..840``; ``PST`` is
   ``-480``). **Not a row field**, and not inferable from ``starts_at``: an ISO
   offset on a row describes that session's instant, while what they need is the
   EVENT's offset, which also has to interpret their event-local ``day_start`` and
   ``day_end``. It is one number per schedule, so it costs about 24 bytes once per
   file and leaves :data:`MAX_BYTES` alone.

8. **``speaker`` AND ``description`` ARE THE 2026-08-26 FREEZE-ADD, AND THEY ARE
   OPTIONAL IN EXACTLY THE WAY ``location`` IS** (BADGE_FREEZE_ADDENDUM §C, owner
   ruling; the badge-apps lane owns the change, this file is the seam). Both are
   sanitized to :data:`SAFE_CHARS` and bounded by :data:`MAX_SPEAKER` /
   :data:`MAX_DESCRIPTION`, both are ABSENT rather than empty when the backend has
   nothing, and neither keeps a ``_raw`` companion -- the byte argument is at
   :data:`MAX_BYTES` and it is the reason, not an oversight. **A ROW WITHOUT THEM
   IS AN ORDINARY ROW**: a cache written before today, a nulled column, a schedule
   nobody has annotated. A reader draws the line it has and omits the line it does
   not; it must never draw an empty one.

   FIELDS FREEZE, CONTENT DOES NOT. The projection is gang-cloned onto ~800
   badges, so this is the last chance to ask for a column; the backend may fill,
   empty or reword either field any day after. The corollary is a HARD BACKEND
   DEPENDENCY, spelled out at :data:`SELECT`: PostgREST 400s a ``select=`` naming
   a column that does not exist, so ``schedule_events`` must carry both before any
   badge can sync a schedule at all.

WHY THE FETCH IS PAGED. ``postgrest.MAX_BODY_BYTES`` is 8192 for REQUEST AND
RESPONSE on the device lane, and ``_decode_body`` raises past it. A worst-case row
here is ~686 bytes (a 120-character title, an 80-character location, a
120-character speaker, a 160-character description, two ISO stamps and a track),
so a single response can hold about 11 of them and a
conference schedule is longer than that. The sync therefore walks pages of
:data:`PAGE_ROWS` with ``limit``/``offset`` and swaps the whole file at the end,
which is also why the file is written once rather than appended to: a half-fetched
schedule must never be a schedule the badge shows.

MicroPython surface: ``json`` at module scope and ``os`` inside the writer, so
the parsing and sanitizing half of this module is importable anywhere -- including
a host tool or a test -- without a filesystem. The write is the same
temp -> flush -> os.sync -> rename discipline every other store here uses.
"""

import json


SCHEMA = 1
DEFAULT_PATH = "/state/schedule.json"

# HOW MANY EVENTS THE BADGE CACHES. Sixty-four, and the bound is the panel rather
# than the volume: a wearer scrolls a schedule to find what is on now and what is
# next, and 64 sessions is a full day of a four-track conference. At ~200 bytes a
# row that is ~13 KB, and at four pages it is four errands on a schedule that
# changes a handful of times a day.
MAX_ROWS = 64

# ROWS PER FETCH, against the 8192-byte response cap. A worst-case row is ~686
# bytes (120-char title + 80-char location + 120-char speaker + 160-char
# description + two ISO stamps + a track + JSON overhead), so 10 is ~6.9 KB
# worst case and typically under 2 KB. Deliberately not 11 -- the arithmetic
# ceiling -- because a cap that is exactly reached is a cap that fails on the
# first title somebody pads with spaces.
#
# **IT WAS 16 UNTIL 2026-08-26 AND THE FREEZE-ADD IS WHY.** Adding `speaker` and
# `description` to `SELECT` took the worst row from ~350 to ~686 bytes, so a
# 16-row page is 10,976 bytes -- past `postgrest.MAX_BODY_BYTES`, where
# `_decode_body` RAISES and the whole fetch is abandoned. The price is round
# trips on a CHANGED schedule only (MAX_ROWS/PAGE_ROWS = 7 pages instead of 4);
# the cadence check is one small version string either way.
PAGE_ROWS = 10

# THE PRE-DECODE BOUND (CX-10 sub-claim 4). A full MAX_ROWS record is ~15 KB in
# practice and **60,223 B** in its worst legal shape (64 rows each carrying a
# 120-character title, a 120-character `title_raw`, an 80-character location, its
# own `_raw`, a 120-character speaker, a 160-character description, two ISO
# stamps and a track, plus a 64-character `version` and a `synced_at`), so
# 65,536 is **1.09x** the worst thing `save` can write and the slack is
# **5,313 B** -- 8.1%, or about 83 bytes a row.
#
# **BOTH FIGURES ARE MEASURED, AND THE MEASUREMENT METHOD IS PART OF THE NUMBER**
# (corrected 2026-08-26; the widening shipped saying "~44 KB ... ~1.45x"). That
# pair described a BARE WIRE ROW -- 64 x ~687 B, no `_raw` at all -- while the
# sentence around it enumerated the `_raw` companions, so it was four times the
# real margin and not comparable with the pre-widening figure it claimed to
# replace. The pre-widening number was taken the SAME (with-`_raw`) way and was
# right: 40,127 B, 1.63x. So the honest narrowing is **1.63x -> 1.09x**, and
# `badgelink/tests/test_ft_b_schedule.py` now derives all three figures and
# fails if this comment stops matching them.
#
# **WHAT IS LEFT WILL NOT HOLD ONE MORE COLUMN, which is the thing a reader has
# to take away.** 5,313 B sounds like room and is not, because it divides by 64:
#   * restoring `speaker_raw` (120 chars) is +8,896 B -> 3,583 B OVER the cap;
#   * restoring `description_raw` (160 chars) is +11,712 B -> 6,399 B over;
#   * ONE new 80-character column is +5,888 B -> 575 B over;
#   * a 40-character column is +3,328 B and is the last thing that fits.
# So the next freeze-add to this projection is a cap change, a bound cut, or
# nothing -- it is not a judgement call, and it is why `speaker` and
# `description` carry no `_raw` companion (see `row`): with all four the worst
# legal record is 80,831 B.
#
# RAISING THE CAP IS THE OTHER WAY OUT AND IT IS WORSE: this number is duplicated
# in the schedule app as `schedule_model.BADGELINK_MAX_BYTES` and pinned by a
# cross-lane test, and it is a heap allocation on a badge whose entire boot-JSON
# budget exists to keep that allocation small.
#
# THE COST OF THE CAP BEING WRONG IS NOT SYMMETRIC, and only one direction is
# cheap. Past the cap BOTH readers answer "no cache", which for a CORRUPT or
# truncated file is the recovery it already gets: the next version check
# disagrees, one refetch, done. For a file `save` ITSELF wrote too large it is a
# PERMANENT refetch loop -- fetch, write, refuse, disagree, fetch -- because
# nothing about the input changes. That asymmetry is why the shape above is
# measured rather than estimated. It is also why the cap is sized for the worst
# LEGAL record and not for a pathological all-escapes file: a `title_raw` of 120
# em dashes encodes to 6 bytes a character and no cap the badge can allocate
# survives 64 of those rows.
MAX_BYTES = 65536

# The columns the badge asks for, and the two it does not. `id` is omitted
# because nothing badge-side keys on it; `created_by`/`created_at`/`updated_at`
# are omitted because they are the version function's business, not the panel's.
#
# ⚠ **THIS LIST IS FROZEN AT PROVISIONING AND THE COLUMNS BEHIND IT MUST EXIST**
# (BADGE_FREEZE_ADDENDUM §C, 2026-08-26; owner ruling, badge-apps lane). ~800
# badges are gang-cloned from one image, so a column that is not asked for here
# can never be asked for later -- which is why `speaker` and `description` are in
# the projection before the backend has content for them. THE ORDERING GOES THE
# OTHER WAY THOUGH: PostgREST answers `select=` naming an absent column with a
# 400, `_on_schedule_page` sees `ok=False` and abandons the fetch, so until
# `schedule_events` HAS both columns the badge keeps its cached schedule and
# quietly re-tries on the next 15-minute cadence. That degrade is bounded and it
# self-heals the moment the migration lands -- nothing persists, nothing breaks
# -- but it means the two columns are a backend GATE, not a nice-to-have. The
# ADD-column note for the Supabase lane is in `schedule/README.md`.
#
# `*` was the other way to be forward-compatible and it was refused: it drags
# `id`/`created_by`/`created_at`/`updated_at` (~150 bytes a row against an 8192
# response cap) and it freezes NOTHING, which is the opposite of what a frozen
# firmware wants from a projection.
SELECT = "title,starts_at,ends_at,location,track,speaker,description"
ORDER = "starts_at.asc"

# The column bounds, from `schedule_events`.
MAX_TITLE = 120
MAX_LOCATION = 80
MAX_TRACK = 32
MAX_STAMP = 40

# THE TWO 2026-08-26 BOUNDS, and each is a wire budget rather than a taste call.
#
# `MAX_SPEAKER` mirrors `MAX_TITLE` because the column is SINGULAR text while a
# real session has more than one name on it: the shipped agenda's keynote row is
# "Paul Copplestone, CEO, Supabase; Ant Wilson, CTO, Supabase" at 58 characters,
# so 120 holds two fully credited people and 80 would cut the second one's job
# title off.
#
# `MAX_DESCRIPTION` is 160 and the panel is not what sets it -- the schedule app
# draws ONE wrapped line and ellipsizes the rest, and that line holds about 30
# characters: `schedule/results/browser/metrics.json` measures the 1.5x HIRES
# content column at 214 px with the time range `09:00 - 10:00` at 84 px, i.e.
# ~6.5 px per character in MonaSans at 18 pt. 160 is what survives the arithmetic:
# it is the largest bound that still lets `PAGE_ROWS` rows plus one spare fit
# inside `postgrest.MAX_BODY_BYTES` at a page size worth fetching, and a bigger
# one buys characters no face on this badge can show today while costing a round
# trip on every schedule change. A longer blurb is truncated, never refused.
MAX_SPEAKER = 120
MAX_DESCRIPTION = 160

# THE MEASURED NONZERO-INK INTERSECTION of the ROM faces -- the same set
# `setup_state.NAME_CHARS` carries and the same one the `set_name` CHECK
# enforces. SPELLED HERE rather than imported, which is the pattern
# `network_runtime` already uses for `pushlink`'s literals and for the same
# reason: this module must not take a dependency on another /system/lib file it
# does not otherwise need. `badgelink/tests/test_ft_b_schedule.py` pins the two
# strings equal, so a drift fails a test instead of a panel.
SAFE_CHARS = (
    " !\"#$%&'()*+,-./0123456789:;<=>?@"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
    "abcdefghijklmnopqrstuvwxyz{|}~"
    "¡¢£©«®°·»¿"
    "ÀÁÂÃÄÅÆÇÈÉ"
    "ÊËÌÍÎÏÐÑÒÓ"
    "ÔÕÖØÙÚÛÜÝÞ"
    "ßàáâãäåæçè"
    "éêëìíîïðñò"
    "óôõöøùúûüý"
    "þ"
)

_SAFE = frozenset(SAFE_CHARS)

# WHAT AN UNRENDERABLE CHARACTER BECOMES. Every entry is a character an organizer
# actually types and a substitution that reads correctly rather than a box: the
# typographic dashes and quotes a word processor inserts silently, the ellipsis,
# the non-breaking space, and the arrows and bullets a schedule uses for
# structure. EVERY KEY IS ONE CHARACTER -- the lookup is per character, so a
# two-character key can never match and a draft carried two of them.
# Anything NOT in this table and not in SAFE_CHARS becomes a single
# `?`, which is honest -- it says "a character was here" rather than pretending
# the title was shorter.
SUBSTITUTIONS = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
    "‘": "'", "’": "'", "‚": ",", "‛": "'",
    "“": "\"", "”": "\"", "„": "\"", "‟": "\"",
    "′": "'", "″": "\"",
    "…": "...",
    " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", "　": " ",
    "​": "", "‌": "", "‍": "", "﻿": "",
    "•": "-", "‣": "-", "▪": "-", "●": "-",
    "→": "->", "←": "<-", "⇒": "=>",
    "×": "x", "÷": "/", "⁄": "/",
    "™": "(TM)", "℗": "(P)",
    "\t": " ", "\r": " ", "\n": " ",
    "œ": "oe", "Œ": "OE", "Š": "S", "š": "s",
    "Ž": "Z", "ž": "z", "Ÿ": "Y", "ƒ": "f",
    "€": "EUR",
}

# What a character with no substitution becomes. A single visible mark, because a
# silent deletion turns "Ask Me About Kubernetes" into something that reads as if
# the organizer typed it that way.
REPLACEMENT = "?"


class ScheduleError(Exception):
    """The cache could not be written. The caller degrades; it does not crash."""


def already_safe(text, limit=MAX_TITLE):
    """Whether :func:`sanitize` would return this exact string unchanged.

    ONE PASS, NO ALLOCATION, and it is why the same row can be normalised on
    fetch and verified on save and load without paying for the work twice. The
    three things `sanitize` does are each checked rather than performed: every
    character drawable, no run of two spaces to collapse, and no leading or
    trailing space to strip -- plus the length bound.
    """

    if not isinstance(text, str) or not text or len(text) > limit:
        return False
    first = None
    previous = None
    for character in text:
        if character not in _SAFE:
            return False
        if character == " " and previous == " ":
            return False
        if first is None:
            first = character
        previous = character
    return first != " " and previous != " "


def sanitize(text, limit=MAX_TITLE):
    """Any text -> text every ROM face can draw.  TOTAL: never raises.

    Three passes, in order: substitute what has a sensible equivalent, replace
    what does not, then bound the length. Bounding LAST so a substitution that
    grows the string (an ellipsis becomes three dots) cannot push it over.

    A non-string is an empty string, not an error: this is called from a draw
    path, and a view that has to check for None before it can paint is a view
    with a branch nobody exercises.

    THE FAST PATH IS THE COMMON PATH, and it exists because F21's frame gate
    measured what the slow one costs when it runs twice. Plain rows -- the
    overwhelming majority -- come back as the CALLER'S OWN object: no list, no
    join, no repeated `replace`, no `strip`, no slice and no allocation at all.
    A row that needs substituting still pays the full three passes below.
    """

    if not isinstance(text, str):
        return ""
    if already_safe(text, limit):
        return text
    out = []
    for character in text:
        if character in _SAFE:
            out.append(character)
            continue
        replacement = SUBSTITUTIONS.get(character)
        if replacement is None:
            replacement = REPLACEMENT
        out.append(replacement)
    result = "".join(out)
    # Collapse the runs a substitution can create -- "A   B" becoming
    # "A   B" reads as a typo rather than as a space.
    while "  " in result:
        result = result.replace("  ", " ")
    result = result.strip()
    if len(result) > limit:
        result = result[:limit].rstrip()
    return result


# THE PLATFORM'S MARKUP ESCAPE, and it is a SECOND contract that `SAFE_CHARS`
# says nothing about. The rect form of `screen.text` parses `[renderer:args]`,
# and an unknown renderer raises inside `update()` -- a traceback modal on every
# frame, on every badge holding that cache. `[` has nonzero ink in every ROM
# face, so `SAFE_CHARS` contains it and `sanitize` passes it straight through:
# the ink set is about BLANK GLYPHS and this is about the FIRMWARE READING the
# string. A title of `[sprite:x]` did exactly that on 2026-08-20.
#
# SPELLED HERE rather than imported from `schedule/badge/schedule/schedule_model.py`,
# which owns the identical table: a /system/lib module must not depend on an
# app's source tree. `badgelink/tests/test_ft_b_schedule.py` pins the two equal
# and compares the two functions' output, so the pin is what stops them drifting.
MARKUP_ESCAPE = {"[": "[["}


def escape_markup(text):
    """Text -> text the rect form of ``screen.text`` will not try to PARSE.

    SEPARATE FROM :func:`sanitize` ON PURPOSE, and the split is the contract:
    `sanitize` is what the WRITER owns (what can be drawn at all, decided once
    per schedule change and stored), and this is what the DRAWER owns (how one
    particular text API reads the result). Two reasons it is not folded into the
    writer, both of which were weighed:

    * **It would change the stored bytes of a frozen projection.** ~800 badges
      are gang-cloned from one image; the cache shape is the thing that cannot be
      revised afterwards, and `[[` on disk is a different file from `[`.
    * **It would double-escape.** The schedule app runs its own
      `sanitize_title` over anything it draws, so an already-escaped `[[` becomes
      `[[[[` and the wearer sees the artifact instead of the crash. A view using
      the x/y form of `screen.text` -- which parses nothing -- would see `[[` for
      no reason at all.

    TOTAL: a non-string is ``""``, matching :func:`sanitize`, because this is
    called from a draw path and a view that must check for None before it can
    paint is a view with a branch nobody exercises.
    """

    if not isinstance(text, str):
        return ""
    # The common answer is "nothing to do", and the scan is one pass over a
    # string a view already has: no allocation on a plain row.
    for character in MARKUP_ESCAPE:
        if character in text:
            break
    else:
        return text
    out = []
    for character in text:
        out.append(MARKUP_ESCAPE.get(character, character))
    return "".join(out)


def is_safe(text):
    """Whether every character is drawable.  What a view may assert."""

    if not isinstance(text, str):
        return False
    for character in text:
        if character not in _SAFE:
            return False
    return True


def _stamp(value):
    if not isinstance(value, str) or not value or len(value) > MAX_STAMP:
        return None
    return value


def _track(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_TRACK:
        return None
    # `schedule_events.track` HAS a charset CHECK, so this is a mirror rather
    # than a sanitizer -- the one schedule field that inherits set_name's kind of
    # guarantee.
    if not ("a" <= value[0] <= "z"):
        return None
    for character in value:
        if not (("a" <= character <= "z") or ("0" <= character <= "9")
                or character == "-" or character == "_"):
            return None
    return value


def synced_at_value(value):
    """An epoch-seconds sync stamp, or ``None`` meaning "write no field".

    REFUSED RATHER THAN REPAIRED, and never written as ``null``: the whole
    contract is that ABSENCE is the "we cannot say" answer, so a second spelling
    of the same thing would give every reader two cases for one fact.

    THE TRUST DECISION IS NOT MADE HERE. Whether the clock is believable is the
    caller's question -- `network_runtime._epoch` puts it through
    ``clock_boot.evaluate_ntp``'s build-floor/ceiling gate, the same gate the
    transport uses before opening a socket -- and duplicating that ceiling in this
    module would make it a second source of truth that drifts. What is checked
    here is only the SHAPE: a positive plain integer of seconds. ``bool`` is
    excluded explicitly because ``True`` is an ``int`` in Python and
    ``"synced_at": true`` would be the one value that passes every later check.
    """

    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value


def row(value):
    """One fetched row -> the stored shape, or ``None`` to drop it.

    A row with no title or no valid window is DROPPED rather than repaired: a
    schedule entry the badge cannot place in time is not an entry, and drawing a
    blank line in a list is worse than a shorter list.
    """

    if not isinstance(value, dict):
        return None
    title = sanitize(value.get("title"), MAX_TITLE)
    if not title:
        return None
    starts = _stamp(value.get("starts_at"))
    ends = _stamp(value.get("ends_at"))
    if starts is None or ends is None:
        return None
    stored = {"title": title, "starts_at": starts, "ends_at": ends}
    # THE VERBATIM TEXT, kept only when sanitizing changed it. Most titles are
    # plain ASCII and carry nothing extra, so the lossless option costs bytes
    # only on the rows that need it.
    #
    # AN EXISTING `_raw` IS CARRIED, NOT RE-DERIVED, and that is not tidiness:
    # this function normalises a FETCHED row and also re-validates a STORED one on
    # load, and a stored row's `title` is already the safe form -- so re-deriving
    # would compare the safe text with itself, find no difference, and silently
    # drop the organizer's actual words on the first reload.
    raw_title = value.get("title_raw")
    if not isinstance(raw_title, str) or not raw_title.strip():
        raw_title = value.get("title")
    if isinstance(raw_title, str):
        trimmed = raw_title.strip()
        if trimmed and trimmed != title:
            stored["title_raw"] = trimmed[:MAX_TITLE]
    location = value.get("location")
    if isinstance(location, str) and location.strip():
        safe = sanitize(location, MAX_LOCATION)
        if safe:
            stored["location"] = safe
            raw_location = value.get("location_raw")
            if not isinstance(raw_location, str) or not raw_location.strip():
                raw_location = location
            trimmed = raw_location.strip()
            if trimmed != safe:
                stored["location_raw"] = trimmed[:MAX_LOCATION]
    track = _track(value.get("track"))
    if track is not None:
        stored["track"] = track
    # THE TWO FREEZE-ADDED FIELDS, AND THEY KEEP NO VERBATIM COPY. `title` and
    # `location` do, because a future face-aware renderer could re-derive the
    # organizer's exact words from `_raw`; four such companions instead of two
    # put the worst legal record at 80,831 B against `MAX_BYTES` 65,536, which
    # is a file this function's caller can write and `load` must then refuse.
    # See MAX_BYTES for the full argument. The lossy substitution is therefore
    # final for these two, which is the trade the byte budget forced.
    #
    # BOTH ARE OPTIONAL IN EVERY DIRECTION: nullable columns, empty on the
    # seeded schedule, and a row that has neither must store exactly what it
    # stored before the widening -- the schedule app draws its speaker and
    # description lines only when the keys are there.
    for key, limit in (("speaker", MAX_SPEAKER), ("description", MAX_DESCRIPTION)):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            safe = sanitize(text, limit)
            if safe:
                stored[key] = safe
    return stored


def rows_from(decoded):
    """A PostgREST array response -> stored rows, bounded and sanitized."""

    if not isinstance(decoded, (list, tuple)):
        return []
    out = []
    for value in decoded:
        if len(out) >= MAX_ROWS:
            break
        entry = row(value)
        if entry is not None:
            out.append(entry)
    return out


# The keys a stored row may carry, and nothing else. Spelled once so
# :func:`stored_row` can refuse a row that smuggled an extra field into the file
# rather than silently writing it.
#
# `synced_at` IS DELIBERATELY NOT HERE. It describes the FETCH, so it belongs to
# the record beside `schema`/`version`/`rows` and there is exactly one of it per
# file; a per-row copy would be 64 identical stamps and 64 chances to disagree.
# A row carrying one is therefore refused by the loop below, which is the check
# that catches the well-meaning version of that mistake.
#
# `speaker` and `description` joined the tuple on 2026-08-26 and their `_raw`
# spellings deliberately did NOT: a stored row carrying `speaker_raw` is refused
# here, which is the check that catches somebody re-adding the verbatim copies
# MAX_BYTES rules out.
_STORED_KEYS = ("title", "title_raw", "starts_at", "ends_at", "location",
                "location_raw", "track", "speaker", "description")


def stored_row(value):
    """The SAME object back when it is already a stored row, else ``None``.

    THE POINT IS THAT VERIFYING IS NOT REBUILDING. ``save`` and ``load`` both
    used to run every row through :func:`row`, which re-sanitizes every string
    and allocates a fresh dict -- so the sync path, which had just built those
    rows with :func:`row`, paid for all of it a second time inside the ONE frame
    that received the last page. F21's frame gate is what made that visible:
    the host harness measured 64 extra normalisations and 61,136 bytes in that
    single frame for a full four-track conference day.

    Nothing is trusted. Every field is checked against the same bound
    :func:`row` would apply; a row that fails ANY check is answered ``None`` and
    the caller falls back to :func:`row`, so a foreign or hand-edited file is
    normalised exactly as before.
    """

    if not isinstance(value, dict):
        return None
    for key in value:
        if key not in _STORED_KEYS:
            return None
    if not already_safe(value.get("title"), MAX_TITLE):
        return None
    if _stamp(value.get("starts_at")) is None:
        return None
    if _stamp(value.get("ends_at")) is None:
        return None
    location = value.get("location")
    if location is not None and not already_safe(location, MAX_LOCATION):
        return None
    track = value.get("track")
    if track is not None and _track(track) is None:
        return None
    # The freeze-added pair, verified against the SAME bounds `row` applies.
    # Absent is ordinary -- every cache written before 2026-08-26 and every row
    # whose backend columns are null -- so only a present-but-wrong value sends
    # the row back through `row()`.
    for key, limit in (("speaker", MAX_SPEAKER), ("description", MAX_DESCRIPTION)):
        text = value.get(key)
        if text is not None and not already_safe(text, limit):
            return None
    for key in ("title_raw", "location_raw"):
        raw = value.get(key)
        if raw is None:
            continue
        limit = MAX_TITLE if key == "title_raw" else MAX_LOCATION
        if not isinstance(raw, str) or not raw or len(raw) > limit:
            return None
        if raw != raw.strip():
            return None
    # A `_raw` that no longer differs from its safe form is the one shape
    # `row()` would have dropped, so it is not a stored row.
    if value.get("title_raw") == value.get("title"):
        return None
    if location is not None and value.get("location_raw") == location:
        return None
    if value.get("location_raw") is not None and location is None:
        return None
    return value


def normalised_row(value):
    """A stored row, verified if it already is one and rebuilt if it is not."""

    kept = stored_row(value)
    return kept if kept is not None else row(value)


def version_from(decoded):
    """The ``version`` field of ``badgelink_schedule_version()``, or ``None``.

    The function ``returns table (version text, event_count integer, changed_at
    timestamptz)``, so PostgREST hands back a one-element array. ONLY ``version``
    is read, and only for EQUALITY -- that is the whole contract, and it is why
    the version being DERIVED from the rows (a count and a microsecond stamp)
    rather than a stored counter matters: it cannot drift from what a fetch would
    return.
    """

    if isinstance(decoded, (list, tuple)):
        decoded = decoded[0] if decoded else None
    if not isinstance(decoded, dict):
        return None
    version = decoded.get("version")
    if not isinstance(version, str) or not version or len(version) > 64:
        return None
    return version


def default_state():
    return {"schema": SCHEMA, "version": None, "rows": []}


def _decode(path, open_fn):
    """The file's decoded object, or ``None``.  BOUNDED, and never raises.

    ``read(MAX_BYTES + 1)`` rather than ``json.load(source)``: the extra byte is
    how an over-cap file is refused without allocating the rest of it, which is
    the whole of CX-10's sub-claim 4. Shared by both readers so there is one
    place the cap is applied and one place it can be wrong.
    """

    try:
        with open_fn(path, "r") as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        return json.loads(raw)
    except (OSError, ValueError, TypeError):
        return None


def load(path=None, open_fn=None):
    """The cached schedule, or defaults.  Fail-soft; never raises.

    A corrupt cache reads as "no schedule and no version", which makes the next
    version check disagree and refetch. That is the correct recovery and it costs
    one round trip.

    IT REBUILDS THE THREE KEYS IT NEEDS AND CARRIES NO OTHERS, which is what
    makes an added record field additive by construction: a file written by an
    older or a NEWER writer reads identically here, and `synced_at`'s presence or
    absence changes nothing on this path (contract rule 6). Surfacing that field
    is the schedule app's own half and is not this function's job yet.
    """

    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    raw = _decode(path, open_fn)
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return default_state()
    version = raw.get("version")
    if version is not None and (not isinstance(version, str) or len(version) > 64):
        version = None
    entries = raw.get("rows")
    rows = []
    if isinstance(entries, list):
        for value in entries[:MAX_ROWS]:
            entry = normalised_row(value)
            if entry is not None:
                rows.append(entry)
    return {"schema": SCHEMA, "version": version, "rows": rows}


def cached_version(path=None, open_fn=None):
    """The version ON DISK, or ``None``.  Fail-soft; never raises.

    THE VERSION CHECK MAY NOT READ THE ROWS. ``_on_schedule_version`` used to
    call :func:`load` to fetch one string for one equality comparison, which on a
    badge holding a full day's schedule re-validated 64 rows inside the frame
    that received the response. The rows are not part of the question, so they
    are not part of the answer, and the caller keeps this string in RAM
    afterwards -- which is what ``network_runtime`` does, so the cheap path
    touches no filesystem at all.

    **THIS STILL DECODES THE WHOLE FILE, AND CX-10 LEFT IT THAT WAY ON PURPOSE.**
    It normalises no row, so it is one decode rather than 65 -- but the ~13 KB
    JSON parse is real and it is the last whole-file read a boot pays. Killing it
    permanently needs a header-first schema (a version the reader can find
    without parsing the rows), which changes the on-disk format and is
    NEEDS-SOAK in the CX register §3. The bound below is what this commit can
    honestly claim: the allocation is capped BEFORE it happens.
    """

    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    raw = _decode(path, open_fn)
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None
    version = raw.get("version")
    if not isinstance(version, str) or not version or len(version) > 64:
        return None
    return version


def save(version, rows, path=None, open_fn=None, sync_fn=None, rename_fn=None,
         synced_at=None):
    """Atomically replace the cache.  THE VERSION AND THE ROWS MOVE TOGETHER.

    One file and one rename, deliberately: a version stored separately from the
    rows it describes is a second source of truth, and every way the two can
    disagree ends with a badge that never refetches -- the same argument Card
    FT-S used to make the server-side version DERIVED instead of a counter.

    A ROW THAT IS ALREADY STORED SHAPE IS VERIFIED, NOT REBUILT
    (:func:`stored_row`). The refusal is unchanged: anything that fails a check
    is normalised through :func:`row`, and a row that cannot be stored at all
    still raises.

    ``synced_at`` IS WHEN THIS SUCCEEDED, in epoch seconds from the caller's
    corrected clock (contract rule 6). **It rides the same one rename as the
    version and the rows** for the same reason they do: a sync time that could
    disagree with the content it describes would be worse than no sync time.
    Omitted from the record entirely when it is not a usable stamp -- see
    :func:`synced_at_value` -- and no reader requires it, so an old file and a
    clockless badge are both ordinary.
    """

    import os

    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    if version is not None and not isinstance(version, str):
        raise ScheduleError("schedule version must be a string or None")
    kept = []
    for value in rows[:MAX_ROWS]:
        entry = normalised_row(value)
        if entry is None:
            raise ScheduleError("schedule row is not storable")
        kept.append(entry)
    record = {"schema": SCHEMA, "version": version, "rows": kept}
    stamp = synced_at_value(synced_at)
    if stamp is not None:
        record["synced_at"] = stamp
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


def page_query(offset):
    """The PostgREST query for one page.  Bounded by the response byte cap."""

    return (("select", SELECT), ("order", ORDER), ("limit", PAGE_ROWS),
            ("offset", offset))
