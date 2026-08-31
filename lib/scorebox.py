"""An offline score spool a game opts into in two lines.

    import scorebox
    scorebox.record("snake", score, duration_ms, play=plays)

That is the whole API a game needs, and both properties of it are deliberate:
**it never raises** (a game may not crash because a filesystem was full) and
**it never blocks** (one bounded write and the network is somebody else's
problem). ``network_runtime`` drains the slots through the transport's errand
channel whenever a socket happens to exist.

ONE SLOT PER GAME, HIGHEST SCORE WINS (owner design, 2026-08-29; ADR-007). Each
game holds at most ONE pending score. A better score REPLACES the standing one,
an equal or lower one is ignored and nothing is written, and a successful upload
clears that game's slot. With five games there can never be more than five
pending scores, so the bound on undelivered data is STRUCTURAL rather than
enforced -- which is what deleted ``MAX_ENTRIES``, the FIFO compaction path and
the incremental scan state machine that existed to keep a 64-entry cold read
inside a rendered frame.

**NOTHING IS EVER DISCARDED.** The owner's ruling, verbatim: *"it doesn't have to
be pounding the database... If it fails it can try again in a way that is smart.
It doesn't have to be instant but we won't lose the scores completely."* A failed
upload leaves the slot exactly where it is, forever. ``MAX_ATTEMPTS`` -- three
refusals and the wearer's score was DELETED -- is gone with everything else that
dropped a score on failure. Exactly two things empty a slot: a better score
replacing it, and a successful upload (:func:`retire`).

THE CONSEQUENCE THE OWNER ACCEPTED EXPLICITLY: with network after every game you
see every score; with no network all day you see one peak per game. Losing the
LOW scores is the correct thing to lose.

UNIQUENESS IS A PER-GAME PLAY COUNTER, NOT A RANDOM KEY. Each game keeps a
durable integer in its own ``/state/<game>.json`` counting completed runs, a
score carries the number it was set at, and the database key is
``(badge_id, game, play_number, score)``. Re-posting the identical tuple hits
``on conflict do nothing`` and returns success, so a lost response costs one
duplicate REQUEST and creates no duplicate ROW -- which is the only guarantee the
random ``idempotency_key`` was ever providing. ``new_key`` and ``valid_key`` are
gone; :func:`valid_play` took their place.

THE MINIMAL ANTI-CHEAT RULING BINDS EVERY LINE HERE, quoted from Card FT-S:
**the badge sends score / duration / idempotency-key ONLY; ALL judgment is SQL,
hot-patchable; per-game floors are measured by playground bots later;
flag-don't-block; human prize check.** (The key in that sentence is now the play
number; the ruling it states is untouched.) So there is no plausibility test, no
floor, no rate limit on scoring and no "is this even possible" check in this
module, and adding one later would be moving judgment client-side. What IS here
is delivery: one slot per game, a high-water rule, and a retire-once rule with a
supersede check.

THERE IS NO ``duration`` COLUMN, and that is the one shape surprise. The client
grant is ``(badge_id, game, play_number, score, metadata)`` -- Card FT-S
deliberately added no floors table and no duration column -- so the duration
rides in ``metadata`` as ``{"duration_ms": N}``. SQL reads it with
``metadata ->> 'duration_ms'``, so it stays hot-patchable exactly as the ruling
requires, and promoting it to a column later is a migration nothing here has to
know about.

THE WEARER'S NAME RIDES THERE TOO, AND IT IS THE SAME SHAPE SURPRISE RATHER THAN
A SECOND ONE. Owner request, 2026-08-28: a leaderboard row should be attributable
to a person -- "just a way so that it's easier to identify which person has
whatever name they put in the name badge should be associated with their game
scores", and "it's not supposed to be any sort of identifier other than this
score is associated with this name that was entered in a badge. That is all." So
**the ruling above is untouched: a name is an ATTRIBUTE, not a judgment, and it
adds NO COLUMN.**

THE DOOR THE RUN LEFT BY RIDES THERE TOO, and so does ``age_ms``, so ``metadata``
is ``{"duration_ms": N, "name": "...", "end": "finish", "age_ms": N}`` -- four
keys in the same bag, and for the fourth time no column and no migration.

THE PHANTOM ZERO-SCORE INCIDENT IS WHY ``end`` EXISTS. ``snake`` is the only one
of the five games with an ``on_exit``, so it is the only one that banks a run on
the HOME path, and its guard rejects only INTRO and FINISHED -- a run started half
a second ago is PLAYING, so it passes. One press of B on a post-mortem starts a
fresh run at score 0 with a restamped clock; HOME a moment later spooled it. A
real drained row read ``snake score 0 duration_ms 584`` on the same badge as
``snake 24 @ 17216ms``.

**THE BADGE STILL SENDS THE ROW**, and that is the ruling rather than an
oversight: suppressing it here would be exactly the client-side judgment Card
FT-S forbids, and a zero is a real thing a player does -- the owner genuinely
died at 0 on flappy. So the badge adds EVIDENCE instead of a verdict. ``end`` is
the door: ``finish`` (death or win), ``quit`` (the labelled exit) or ``exit``
(HOME out of a live run). ``metadata ->> 'end' = 'exit' and score = 0`` then
excludes the phantom in SQL, hot-patchable at the venue instead of a reflash of
~1,000 badges.

A DURATION THRESHOLD WAS INVESTIGATED AND REJECTED, and it must not come back as
a "simpler" fix. 584 ms sits INSIDE snake's genuine instant-death range: it wraps
at the walls, so the only death is self-collision -- three turns, about 480 ms at
level 4 and near 100 ms at level 9. And the five games do not measure duration
comparably in the first place: snake reads its clock AFTER the atomic save while
the other four use the frame's own ``now``, so snake's figures run 7-185 ms high
against theirs. A floor drawn anywhere in that band cuts real runs.

``age_ms`` IS A WITHIN-BOOT MEASUREMENT AND THE BADGE NEVER FAKES ONE. The badge
sets its clock by NTP at boot, NTP needs network, and the scores that sit longest
undelivered are exactly the ones recorded WITHOUT network -- so a wall-clock
stamp taken offline is the one thing that must not be trusted. Each slot carries
the monotonic ``time.ticks_ms()`` reading it was written at plus this boot's
:func:`boot_id`, and :func:`_age_ms` returns a number ONLY when the slot was
recorded in THIS boot. Otherwise the key is absent and the server falls back to
``recorded_at`` -- arrival -- which is today's behaviour, so the change degrades
to the status quo rather than to a lie. See :func:`_age_ms` for why a naive
cross-boot ``ticks_diff`` would place scores IN THE FUTURE.

THE NAME IS READ AT ``record`` TIME AND NOT AT ``row`` TIME, and that is CX-10's
frame budget deciding it rather than taste. ``row`` runs on a rendered frame and
NO frame of the boot may open a second file or decode a second document
(``test_cx10_boot_json_cost.FirstFrameTests``); a read there would have been the
defect CX-10 removed, put back. ``record`` runs on the game's death/quit frame,
which already pays an atomic ``/state/<game>.json`` save measured at 7-130 ms
with a 185 ms tail, and it reads the card state ONCE PER BOOT. Play time is also
the more honest moment: the score carries the name its player was actually
wearing.

THE FILE IS ONE JSON OBJECT AND EVERY WRITE IS temp -> flush -> sync -> rename.
The append this module used to do was justified by a file that grew without
bound; the file is now at most five short slots (~620 bytes realistic, ~4.2 KB
for a hostile one at ``MAX_SLOTS``), so a whole-document rewrite is trivial and
it buys atomicity: what is on flash is a whole valid document or the previous
one, never a torn tail. That deletes the entire class of defects ``_can_append``
existed to catch.

MicroPython surface: ``json``, ``os`` and ``time``. ``time`` is a frozen built-in
on every port, so it cannot be the half-refreshed-lib case the games'
``try: import scorebox`` guard exists for.
"""

import json
import os
import time


SCHEMA = 2
DEFAULT_PATH = "/state/badgelink-scores.json"

# THE GAMES' PERSISTED PERSONAL BESTS, WHICH ARE NOT THE SPOOL. There are two
# kinds of score data on this badge and conflating them is how a wipe lies: this
# module's file holds UNDELIVERED SUBMISSIONS, and each game separately keeps its
# own high score -- and, since 2026-08-29, its own PLAY COUNTER -- through
# `shared/score_sink.py`.
#
# The spec that ordered the wipe said no game kept a local high score. It was
# wrong, and the reason generalises: the grep behind it was scoped to the DEPLOY
# path (`apps/`) while the games are top-level repository trees. All five write
# `/state/<game>.json`, and the OSError-guard rollout exists precisely because
# those game-over writes happen.
#
# ERASING THESE NOW RESETS THE PLAY COUNTERS TOO, and that is the owner's design
# rather than a side effect: the SCORE is in the database's primary key, so a
# wearer who erases and replays to the same play index with a DIFFERENT score
# still creates a row. Only an identical (game, play, score) is deduped.
#
# THE LIST LIVES HERE because `wipe_scores`' `scope: "all"` has to reach these
# files and `network_runtime` already imports this module -- one list, so a fleet
# wipe cannot silently miss a game.
#
# NOTHING ELSE IMPORTS IT, and that is deliberate rather than untidy. Each game
# owns its own `STATE_PATH`, and `settings` carries its own copy, so a wearer can
# still erase local high scores when the required `/system/lib` install is
# missing or damaged. Host tests pin all three lists against each other, which
# is the shape `setup_state` already uses for the app that must not import it.
GAME_STATE_PATHS = ("/state/snake.json", "/state/pong.json",
                    "/state/breakout.json", "/state/flappy.json",
                    "/state/pacman.json")


# THE PRE-DECODE BOUND, and it is a bound on the ALLOCATION rather than on the
# result (CX-10 sub-claim 4). Every loader in BadgeLink read its whole file and
# applied its bound afterwards, so a corrupt or hostile `/state` file was a heap
# allocation before it was a refusal.
#
# 64 KB is now enormous headroom rather than a tight fit, and the arithmetic is
# `MAX_SLOTS`': a legal document is ~4.2 KB at its very worst, 15x under this cap.
# Past the cap the document is NOT truncated and NOT partially adopted -- a file
# that big is not one this module wrote, so nothing in it is trusted. It is left
# on flash (the next `record` replaces it) rather than deleted.
MAX_BYTES = 65536

# HOW MANY SLOTS A DOCUMENT MAY HOLD, and it is NOT a limit on normal play: five
# games ship, so the real ceiling is five and it is structural. This number
# exists to bound a HOSTILE OR FOREIGN `/state` file, which is the only way more
# than five keys can appear -- `record` refuses a sixteenth NEW game rather than
# growing the file a rendered frame has to decode.
#
# THIS IS WHAT REPLACED `MAX_ENTRIES = 64`. That number bounded a QUEUE, and the
# queue is gone: there is no head, so there is nothing to compact and nothing to
# evict. Sixteen at ~260 bytes for the worst LEGAL slot is ~4.2 KB.
MAX_SLOTS = 16

# `scores.game ~ '^[a-z][a-z0-9_-]{0,63}$'`.
MAX_GAME = 64

# `scores.score` and its CHECK, mirrored:
#
#     constraint scores_score_check check (score between 0 and 1000000000)
#
# so a game handing over a corrupted counter is refused HERE, for free, rather
# than by a 400 nobody reads. One billion is far above anything the five shipped
# games can produce, so this narrows nothing a real player will ever reach.
#
# MIRRORING IT EXACTLY IS WHAT MAKES "RETRY FOREVER" SAFE. Nothing deletes a
# refused slot any more, so a slot the database would always reject would be
# re-offered for the rest of the event. It cannot be the badge's fault: every
# bound this module checks is the column's own bound, so a well-formed slot is
# one the server has no shape reason to refuse.
MAX_SCORE = 1000000000

# `scores.play_number` and its CHECK, mirrored:
#
#     constraint scores_play_number_check check (play_number between 0 and 1000000)
#
# ZERO IS LEGAL AND MEANS "recorded before play numbers existed" -- the 2026-08
# database backfill's value, and the value `_adopt_legacy` gives a spool line
# imported from the old JSON-lines file. The badge's own counter starts at 0 and
# the first completed run is play 1, so the badge never MINTS 0; the reader
# accepts it because the database does.
MIN_PLAY = 0
MAX_PLAY = 1000000

# `metadata` is `jsonb ... octet_length <= 4096`, and this module puts exactly
# FOUR keys in it -- the duration, the wearer's name (2026-08-28), the door the
# run left by (2026-08-29) and the age (2026-08-29). The whole object serializes
# to under 180 bytes, so the ceiling is never in play. The duration cap is a
# sanity bound, not a judgment: 24 hours.
MAX_DURATION_MS = 24 * 60 * 60 * 1000

# THE CEILING ON A CLAIMED AGE, and the number is chosen against `ticks_diff`'s
# validity window rather than against how long an event lasts. MicroPython's tick
# wraps at 2**30 ms and `ticks_diff` resolves into +/-2**29 ms (~6.2 days), so a
# difference larger than that is ALIASED rather than large. 24 hours is 4x inside
# that window, which means an absurd age is refused as unmeasurable instead of
# being reported as a plausible small number. The server clamps it again in SQL,
# because `metadata` is a badge-written blob and all judgment is SQL's.
MAX_AGE_MS = 24 * 60 * 60 * 1000

# WHERE THE WEARER'S NAME LIVES. `setup` -- the app the launcher's hold opens --
# stores the name the wearer typed on the badge itself, and these are its
# literals. **THIS IS NOT `badges.display_name`**: that column is the ADMIN path,
# written remotely by the `set_name` command. This is the wearer's own card.
#
# RESTATED, NOT IMPORTED, and the reason is the one `install_system_lib` gives
# for this file in particular: `scorebox` is "the only /system/lib module an app
# is meant to reach for", so a badge whose lib predates a refresh must fail the
# game's `import scorebox` and nothing else. A module-scope `import setup_state`
# (which already mirrors this same file for the `set_name` applier) would make
# `scorebox` fail whenever THAT module was the one a half-refreshed lib was
# missing. `setup_state`, `settings.brightness_store` and `nametag.badge_state`
# all restate this file's literals for the same reason; what keeps them honest is
# a pin test against the real `card_store`/`card_model`, not a comment --
# `badgelink/tests/test_setup_state.py::ScoreboxNamePinTests`, which lives beside
# the rest of setup's pins because that is where the real modules are imported.
NAME_STATE_PATH = "/state/badgecard.json"   # card_store.STATE_PATH
NAME_BADGES = "badges"                      # card_model.new_state()'s list
NAME_ACTIVE = "active"                      # card_model.new_state()'s index
NAME_KEY = "name"                           # card_model.BADGE_KEYS[0]

# `card_model.NAME_MAX`, AND THE ONLY TRUNCATION RULE THIS MODULE APPLIES. Twelve
# is what `setup` already stores (`setup_state.set_name` writes `name[:12]` and
# reports `truncated`) and what `nametag` draws, so the string is short by
# construction and a second, different cap here would be a rule nothing else on
# the badge agrees with. It is re-applied on read and again in `row` for one
# reason only: `/state` is a file a stranger can write, and 12 characters is at
# most 72 bytes of escaped JSON, so no name reachable through here can push a row
# near `metadata`'s 4096-byte ceiling.
MAX_NAME = 12

# THE DOOR THE RUN LEFT BY. `finish` is a death or a win, `quit` is the game's
# own labelled exit, `exit` is HOME out of a live run -- the three `reason`
# strings the games already pass to their own banking call, carried through
# unchanged rather than re-spelled here. The module docstring has the incident.
#
# THE GAME SUPPLIES IT AND THIS MODULE DOES NOT CHECK IT AGAINST A VOCABULARY,
# which is the same line `wearer_name` holds: a label is an ATTRIBUTE of a score,
# not part of its validity, so an unknown or absent one may cost the row its
# EVIDENCE and never the score itself. Refusing a line for a strange label would
# be the client-side judgment the ruling forbids, applied to the very key that
# exists so judgment can stay in SQL.
END_KEY = "end"

# THE ONLY RULE APPLIED TO IT: a length cap, for `MAX_NAME`'s reason and no
# other. The spool is a `/state` file a stranger can write and `row` builds a
# `metadata` object with a 4096-byte ceiling, so the label has to be bounded even
# though nothing the five games write is longer than `finish`. Sixteen leaves
# room for a door a sixth game might add without anyone reopening this file.
MAX_END = 16

# THE SLOT'S OWN KEYS, named as constants because THREE readers spell them: this
# module, the drain in `network_runtime`, and a device probe reading `/state` by
# hand. `play` in the SLOT becomes `play_number` in the ROW -- the slot speaks the
# badge's vocabulary and the row speaks the database's, the same split
# `duration_ms` already has (a slot key AND a metadata key of the same name).
PLAY_KEY = "play"
AT_KEY = "at_ms"
BOOT_KEY = "boot"

# ...and the metadata key the pair above produces. Absent means UNKNOWN, never
# zero: `metadata ->> 'age_ms'` has to be able to tell "no measurement" from
# "measured as zero", which is the same absent-not-blank doctrine `name` and
# `end` already follow.
AGE_KEY = "age_ms"

# THE PRE-DECODE BOUND ON THE CARD STATE -- the same rule `MAX_BYTES` states for
# the spool, and stated again because it is the rule CX-10 found every other
# BadgeLink loader breaking: bound the ALLOCATION, not the result.
#
# 4 KB, and the arithmetic is `setup`'s own. One badge is a 12-character name, a
# 48-character background id, a face, an effect and at most
# `card_model.MAX_STICKERS` (24) marks of ~80 bytes each -- ~2.1 KB -- and this is
# double that. A LONGER FILE READS AS NO NAME, which is the right way to fail: it
# costs attribution, never a score, and a game's heap is the tightest on this
# badge.
NAME_STATE_BYTES = 4096

# KEPT AND REPURPOSED. This table was `new_key`'s; `boot_id` renders the same
# eight bytes of `os.urandom` into the same 16 hex characters, and the reason the
# random source survived the key's deletion is that a BOOT needs a handle even
# though a SCORE no longer does.
_HEX = "0123456789abcdef"

#: THE SLOTS THIS BOOT KNOWS ABOUT: ``{game: slot}``, or ``None`` for "not read
#: yet". A game and the transport share one interpreter and one ``sys.modules``
#: entry, so a score recorded inside ``launch()`` is visible to the pump without
#: either side knowing about the other, and the pump's per-frame question costs a
#: dict length instead of a filesystem read.
#:
#: THE CACHE IT REPLACED HAD A DEFECT WORTH REMEMBERING, because it is why the
#: whole scan state machine went. ``_pending`` and ``_head`` were two globals
#: kept in step by six writers, and ``_scan_step``'s failure arms set
#: ``_pending = count`` while leaving ``_head`` at ``None`` -- so ONE transient
#: read error part way through a cold scan (a busy volume, a card pulled and
#: pushed back) latched "the spool holds zero scores" for the REST OF THE BOOT.
#: The drain's free guard was ``scan_complete() and cached_head() is None``, no
#: later read ever contradicted it, and nothing called :func:`reset_cache`. A
#: badge with five real scores on flash would sit there with every gate open and
#: send nothing. One dict cannot disagree with itself.
_slots = None

#: ROUND-ROBIN POSITION FOR :func:`take_slot`, and it is what replaced
#: ``MAX_ATTEMPTS``. The old spool had a HEAD, so an entry the server kept
#: refusing blocked every later score -- which is why three refusals DELETED a
#: wearer's score. The slots are unordered peers, so a refused one occupies only
#: its own game's place and this cursor walks past it to the next game on the
#: very next frame. Nothing has to be discarded to keep the others moving.
_cursor = 0

#: THIS BOOT'S IDENTITY, minted once by :func:`boot_id`. ``None`` means "not
#: minted yet"; ``""`` means "minted, and this port could not produce one", which
#: is FALSY AND NEVER COMPARES EQUAL FOR AGE PURPOSES -- see :func:`_age_ms`.
#:
#: :func:`reset_cache` MUST NOT CLEAR IT. That function is called by the
#: wipe-failure path and by tests, and re-minting here would silently strip
#: ``age_ms`` from every slot already on the badge. A test that wants a simulated
#: reboot sets ``scorebox._boot = None`` itself.
_boot = None

#: THE WEARER'S NAME AS OF THIS BOOT. ``None`` means "not read yet"; ``""`` means
#: "read, and there is none" -- which is `card_model.DEFAULT_NAME`, so the two
#: falsy answers a caller cares about collapse into one truth test.
#:
#: ONE READ PER BOOT IS THE WHOLE COST, and it is enough because **leaving an app
#: is `machine.reset()`**. Nothing survives in RAM between the `setup` screen
#: where a wearer types their name and the game that records a score, so a boot
#: that has read this file cannot be holding an answer the wearer has since
#: changed. The one window it does not see is a REMOTE `set_name` landing mid
#: boot, and the staleness there points the right way anyway: a score being
#: spooled was played under the name the file held when play started.
_name = None


def _ticks_ms():
    """The monotonic clock, on the badge and under CPython host tests.

    COPIED FROM `network_runtime` RATHER THAN IMPORTED, for the reason the name
    literals above are restated: a module-scope import of another `/system/lib`
    module would make `import scorebox` fail whenever THAT module was the one a
    half-refreshed lib was missing, and the games' guarded import exists to make
    a missing scorebox cost the scores and nothing else.
    """

    function = getattr(time, "ticks_ms", None)
    return function() if function is not None else int(time.monotonic() * 1000)


def _ticks_diff(left, right):
    """``left - right`` in tick space. WRAP-AWARE, which is the whole point.

    MicroPython's tick wraps at 2**30 ms; `ticks_diff` resolves the difference
    into +/-2**29 and a bare subtraction does not. CPython has neither function,
    so the fallback is the subtraction its `monotonic` makes correct.
    """

    function = getattr(time, "ticks_diff", None)
    return function(left, right) if function is not None else left - right


def valid_game(value):
    """``scores.game``'s class: ``^[a-z][a-z0-9_-]{0,63}$``."""

    if not isinstance(value, str) or not value or len(value) > MAX_GAME:
        return False
    if not ("a" <= value[0] <= "z"):
        return False
    for character in value:
        if not (("a" <= character <= "z") or ("0" <= character <= "9")
                or character == "-" or character == "_"):
            return False
    return True


def valid_score(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return 0 <= value <= MAX_SCORE


def valid_duration(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return 0 <= value <= MAX_DURATION_MS


def valid_play(value):
    """``scores.play_number``'s bounds, and ONE rule for both sides of the file.

    The badge's minting and the reader agree deliberately: 0 is LEGAL and means
    "recorded before play numbers existed" (a legacy slot, and the database
    backfill), while the badge's own counter mints 1 upward, so the two can never
    collide. `True` is rejected before `int` because `True` IS an `int` in
    Python and a boolean play number would be stored as 1.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return MIN_PLAY <= value <= MAX_PLAY


def boot_id():
    """This boot's id: 16 lowercase hex characters, or ``""``.  NEVER RAISES.

    MINTED ONCE PER BOOT, and it exists for exactly one job: to tell a slot
    recorded in THIS boot from one that survived a reset, so :func:`_age_ms`
    knows whether its two tick readings are even in the same clock domain.

    ``""`` IS THE FAILURE ANSWER AND IT IS A TRAP IF READ CARELESSLY. A port with
    no `os.urandom` mints nothing, and `"" == ""` would then match on every boot
    and hand `_age_ms` exactly the cross-boot garbage it exists to refuse. Every
    reader must test the id for truth BEFORE comparing it.
    """

    global _boot
    if _boot is not None:
        return _boot
    # PESSIMISTIC FIRST, for `wearer_name`'s reason: every early return below is
    # a failure arm and setting this before the read means none of them can
    # forget to.
    _boot = ""
    urandom = getattr(os, "urandom", None)
    if urandom is None:
        return _boot
    try:
        raw = urandom(8)
    except Exception:
        return _boot
    out = []
    for index in range(8):
        byte = raw[index]
        out.append(_HEX[(byte >> 4) & 0x0F])
        out.append(_HEX[byte & 0x0F])
    _boot = "".join(out)
    return _boot


def wearer_name(path=None, open_fn=None):
    """The name the WEARER typed into their own badge, or ``""``. NEVER RAISES.

    THE GUARD IS THE POINT, not the read. This is reached from :func:`record`,
    which a game calls on its death frame and which "never raises" -- so a
    missing, unreadable, over-long, hostile or simply foreign card state must
    cost the wearer their NAME on that row and never their SCORE. Every failure
    arm therefore lands on ``""``, which :func:`record` reads as "send no key".

    IT IS ALSO WHY THE ANSWER IS CACHED EVEN WHEN IT IS EMPTY: a badge whose
    `/state` has no card file would otherwise pay a failed ``open`` on every
    round of every game for the rest of the boot.

    THE CACHE IS KEYED ON NOTHING, exactly as :data:`_slots` is. A caller that
    needs a different ``path`` answered must :func:`reset_cache` first; on the
    badge there is only ever one card state and one boot.

    ``open_fn`` IS THE CARD STATE'S HOOK AND NOT THE SPOOL'S. ``record``'s
    injected ``open_fn`` deliberately does not reach here: a test that fakes a
    full volume for the spool is not also claiming the wearer has no name, and
    `test_cx10_boot_json_cost` counts the spool's opens through that hook.
    """

    global _name
    if _name is not None:
        return _name
    # PESSIMISTIC FIRST. Every early return below is a failure arm, and setting
    # this before the read means none of them can forget to.
    _name = ""
    try:
        with (open_fn or open)(path or NAME_STATE_PATH, "r") as source:
            text = source.read(NAME_STATE_BYTES + 1)
        if len(text) > NAME_STATE_BYTES:
            # OVER THE CAP: refused rather than decoded. See `NAME_STATE_BYTES`.
            return _name
        state = json.loads(text)
        if not isinstance(state, dict):
            return _name
        badges = state.get(NAME_BADGES)
        if isinstance(badges, list) and badges:
            index = state.get(NAME_ACTIVE)
            # `True` IS an `int` in Python, so an `active` of `True` would select
            # badge 1 rather than being rejected. `card_model.active` and
            # `nametag.badge_state.select` both spell it this way; this is the
            # third reader of the same file and it agrees with them by
            # construction, not by luck.
            if not isinstance(index, int) or isinstance(index, bool):
                index = 0
            if index < 0 or index >= len(badges):
                index = 0
            badge = badges[index]
        else:
            # `identity`'s FLAT shape, which a badge nobody has migrated still
            # carries and which `nametag.badge_state.select` still falls back to.
            # Agreeing with the reader that DRAWS the name is the whole point of
            # attributing a score to it.
            badge = state
        if not isinstance(badge, dict):
            return _name
        found = badge.get(NAME_KEY)
        if isinstance(found, str):
            _name = found[:MAX_NAME]
    except Exception:
        # A MISSING /state, an unreadable volume, bytes that are not JSON, or a
        # file written by something that is not `setup` at all. None of them is
        # a reason to lose a score.
        return _name
    return _name


def _slot(name, value):
    """One on-disk slot, validated, or ``None``.

    THE KEY AND THE INNER ``game`` MUST AGREE. `valid_game` accepts the name
    "schema", which is why the slots live in a nested object rather than at the
    top level -- and a slot filed under the wrong key would be posted as one game
    and cleared as another, so a disagreement drops it.

    FOUR REFUSALS AND FOUR REPAIRS, and the split is this module's standing rule:
    a slot is dropped only for something the DATABASE would reject (the game, the
    score, the play number, the duration), never for an ATTRIBUTE. A non-integer
    ``at_ms`` becomes 0 and a non-string ``boot`` becomes ``""``, which costs the
    row its ``age_ms`` and never its score; the name and the door are re-bounded
    rather than refused. An attribute may cost a row its evidence and may never
    cost a wearer their score.
    """

    if not isinstance(value, dict):
        return None
    game = value.get("game")
    if game != name or not valid_game(game):
        return None
    score = value.get("score")
    play = value.get(PLAY_KEY)
    duration = value.get("duration_ms")
    if not valid_score(score) or not valid_play(play):
        return None
    if not valid_duration(duration):
        return None
    at = value.get(AT_KEY)
    boot = value.get(BOOT_KEY)
    if isinstance(at, bool) or not isinstance(at, int):
        # AN UNREADABLE TICK CLEARS THE BOOT ID WITH IT, because the two are ONE
        # measurement: a slot whose tick could not be read has no age, and
        # keeping a matching boot id beside a repaired 0 would let `_age_ms`
        # report the whole time since boot as the score's age. Repairing costs
        # the row its `age_ms` and never its score, which is the rule; inventing
        # an age would be the lie the whole `age_ms` design exists to refuse.
        at = 0
        boot = ""
    if not isinstance(boot, str):
        boot = ""
    # KEY ORDER IS THE WRITE ORDER, so a document read and written back is
    # byte-identical. Both CPython and MicroPython `json.dumps` follow insertion
    # order, which is what makes `_rewrite` deterministic.
    slot = {"game": game, "score": score, PLAY_KEY: play,
            "duration_ms": duration, AT_KEY: at, BOOT_KEY: boot}
    # RE-TRUNCATED because this reader's input is a `/state` file a stranger can
    # write, and `MAX_NAME` is the one cap this module applies. Absent is not
    # blank: a slot written on a badge whose wearer never typed a name carries no
    # key at all, and SQL can tell that apart from an empty string.
    found = value.get(NAME_KEY)
    if isinstance(found, str) and found:
        slot[NAME_KEY] = found[:MAX_NAME]
    found = value.get(END_KEY)
    if isinstance(found, str) and found:
        slot[END_KEY] = found[:MAX_END]
    return slot


def _adopt_legacy(text):
    """Import the OLD JSON-lines spool once, rather than destroying it.

    THE PATH DID NOT CHANGE, so the first boot after this update finds a
    JSON-lines file where a JSON object is expected -- on a badge that may be
    holding real undelivered scores from the day before. Discarding them would
    break the owner's rule that nothing is ever discarded, at the exact moment
    the wearer is least able to notice.

    THE HIGH-WATER RULE IS APPLIED ONCE, HERE: the highest score per game
    survives, which is the same rule `record` applies from now on. ``play`` is 0
    -- "recorded before play numbers existed", the same thing the database
    backfill means by it -- and ``at_ms`` is 0 with ``boot`` ``""``, so NO
    ``age_ms`` is ever claimed for an adopted slot. Its age is genuinely unknown
    and the module does not invent one.

    The old random ``key`` is READ AND DROPPED: the natural key replaced it, and
    a lost response now costs a duplicate request rather than a duplicate row.
    This runs at most once per badge, because the next `_rewrite` leaves the new
    format behind.
    """

    found = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            # A torn last line, or a line from a build with a different shape.
            # Dropped individually so one bad score cannot cost the rest.
            continue
        if not isinstance(value, dict):
            continue
        game = value.get("game")
        score = value.get("score")
        duration = value.get("duration_ms")
        if not valid_game(game) or not valid_score(score):
            continue
        if not valid_duration(duration):
            continue
        standing = found.get(game)
        if standing is not None:
            if score <= standing["score"]:
                continue
        elif len(found) >= MAX_SLOTS:
            # A hostile legacy file cannot buy more slots than a hostile new one.
            continue
        slot = {"game": game, "score": score, PLAY_KEY: 0,
                "duration_ms": duration, AT_KEY: 0, BOOT_KEY: ""}
        carried = value.get(NAME_KEY)
        if isinstance(carried, str) and carried:
            slot[NAME_KEY] = carried[:MAX_NAME]
        carried = value.get(END_KEY)
        if isinstance(carried, str) and carried:
            slot[END_KEY] = carried[:MAX_END]
        found[game] = slot
    return found


def _read_document(path, open_fn):
    """The whole file as ``{game: slot}``.  ONE open, ONE decode.  Never raises.

    ``read(MAX_BYTES + 1)`` rather than ``read()``: the extra byte is how the
    caller learns the file was over the cap without allocating the rest of it.

    AN OVER-CAP FILE KEEPS NOTHING, which is a deliberate difference from the
    old reader's "truncate to the last complete line". That behaviour existed
    because FIFO put the head in the prefix; there is no head now, a document
    that big is not one this module wrote, and adopting half a foreign file's
    keys would be worse than adopting none of them.

    ANYTHING THAT IS NOT A SCHEMA-2 DOCUMENT FALLS THROUGH TO
    :func:`_adopt_legacy` rather than to an empty dict, because the file this
    module is replacing lives at the same path.
    """

    try:
        with open_fn(path, "r") as source:
            text = source.read(MAX_BYTES + 1)
    except Exception:
        # A MISSING spool is an empty one and a write is how it gets created. An
        # unreadable one reads as empty too, and the next `record` REPLACES it --
        # which is the one behaviour the whole-document rewrite buys that the
        # append never could: there is no torn tail to step over.
        return {}
    if len(text) > MAX_BYTES:
        return {}
    text = text.strip()
    if not text:
        return {}
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        return _adopt_legacy(text)
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return _adopt_legacy(text)
    raw = raw.get("slots")
    if not isinstance(raw, dict):
        return _adopt_legacy(text)
    found = {}
    # SORTED, so a hostile file with seventeen keys is truncated deterministically
    # rather than by dict iteration luck -- the same file must read the same way
    # on every boot or a slot would appear and disappear.
    for name in sorted(raw):
        if len(found) >= MAX_SLOTS:
            break
        slot = _slot(name, raw[name])
        if slot is not None:
            found[name] = slot
    return found


def slots(path=None, open_fn=None):
    """Every pending slot, ``{game: slot}``.  Never raises.

    THE AUTHORITATIVE WHOLE-FILE READ, and it is now the ONLY read: the game path
    (`record` on a fresh boot), the drain's first frame, the device probes and
    the tests all want the file's own answer in one call.

    IT IS ALSO WHAT DELETED THE INCREMENTAL SCAN. That machine existed because a
    64-entry spool was 64 per-line decodes and no rendered frame could afford
    them; a five-slot document is ONE open and ONE decode of a few hundred bytes,
    which is inside the budget `test_cx10_boot_json_cost.FirstFrameTests`
    enforces (one open, one decode per boot frame).
    """

    global _slots, _cursor
    _slots = _read_document(path or DEFAULT_PATH, open_fn or open)
    # THE CURSOR RESTARTS WITH THE DICT IT INDEXES. It is a position in
    # `sorted(_slots)`, so carrying it across a re-read would point at a
    # different game.
    _cursor = 0
    return _slots


def _rewrite(mapping, path, open_fn=None, sync_fn=None, rename_fn=None):
    """THE ONLY WRITER: temp -> flush -> sync -> rename.

    EVERY WRITE IS THIS DANCE NOW, where the module used to append and reserve
    the dance for retire and compaction. The append was justified by a file that
    grew to 64 entries -- a whole-file rewrite per score would have made every
    round pay for every round before it -- and the file is now five short slots,
    so the trade reverses: ~620 bytes is nothing, and atomicity is everything.
    What is on flash is a whole valid document or the previous one, so the torn
    tail, the unreachable append past `MAX_BYTES` and the newline-free prefix are
    not damage this module can produce any more.

    SORTED, so the file is byte-deterministic for a given set of slots: two
    badges with the same scores write the same bytes, and a diff of `/state`
    across a session shows only what changed.
    """

    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    temporary = path + ".tmp"
    # `slots` IS A NESTED OBJECT AND THAT IS LOAD-BEARING: `valid_game` accepts
    # the name "schema", so slots keyed at the top level would let a game called
    # `schema` collide with the version key.
    document = {"schema": SCHEMA, "slots": {}}
    for name in sorted(mapping):
        document["slots"][name] = mapping[name]
    with open_fn(temporary, "w") as output:
        output.write(json.dumps(document))
        flush = getattr(output, "flush", None)
        if flush is not None:
            flush()
    sync = sync_fn if sync_fn is not None else getattr(os, "sync", None)
    if sync is not None:
        sync()
    (rename_fn or os.rename)(temporary, path)
    return mapping


def _ensure_parent(path, mkdir_fn=None):
    if "/" not in path:
        return
    parent = path.rsplit("/", 1)[0]
    if not parent:
        return
    maker = mkdir_fn if mkdir_fn is not None else getattr(os, "mkdir", None)
    if maker is None:
        return
    try:
        maker(parent)
    except OSError:
        pass
    except Exception:
        pass


def record(game, score, duration_ms=0, play=None, path=None, end=None, **io):
    """Offer one finished run to this game's slot.  NEVER RAISES.

    THE GAME-FACING CALL. Returns:

    * ``True``  -- a slot was written (a new game, or a better score),
    * ``False`` -- a better or equal score already stands. NORMAL, and nothing
      was written: a losing run costs no flash at all,
    * ``None``  -- refused. An invalid argument, a missing or invalid ``play``,
      `MAX_SLOTS` reached for a NEW game, or a filesystem that would not take it.

    STRICTLY GREATER REPLACES; EQUAL IS IGNORED, and that asymmetry is load
    bearing rather than a taste. Snake's HOME re-entrancy window can submit the
    same live run twice (`bank_run` inside a `finally`, re-entered by the HOME
    interrupt); the second submission carries the SAME score at a HIGHER play
    number, and `<=` drops it before anything reaches the wire. Under the old
    random key that same window produced two leaderboard rows for one run.

    ``play`` IS A KEYWORD AFTER ``duration_ms`` AND A MISSING ONE IS A REFUSAL,
    which is the version-skew rule this signature is shaped by. `/system/lib` and
    the apps ship in SEPARATE install steps (`production.system_lib.ship` is
    false), so a badge may hold any pairing. An OLD app calling
    ``record(name, score, elapsed)`` against this lib passes no ``play``, and a
    refusal is the only honest answer -- accepting it would write 17216 into the
    play field. Positional slot 3 is still ``duration_ms`` and must stay there.

    NO JUDGMENT HAPPENS HERE beyond the column bounds the database would reject
    anyway (the minimal-anti-cheat ruling): there is no floor, no plausibility
    test and no rate limit, because all of that is SQL's and hot-patchable.

    IT STAMPS THE WEARER'S NAME, ONCE PER BOOT and never at the cost of a score,
    and it stamps the monotonic tick and this boot's id so `row` can compute an
    honest ``age_ms``. ``end`` is the door the run left by, EVIDENCE rather than
    a verdict; only the caller can know it.

    IT BUILDS A NEW DICT AND NEVER MUTATES A SLOT IN PLACE. The drain holds a
    reference to the slot it posted for the whole round trip, and that reference
    has to stay a snapshot of what it actually sent -- see :func:`retire`.
    """

    global _slots
    try:
        if not valid_game(game) or not valid_score(score):
            return None
        if not valid_duration(duration_ms) or not valid_play(play):
            return None
        # POPPED, NOT READ. `_rewrite` takes only the three write hooks, so
        # leaving `mkdir_fn` in `io` made the rewrite path raise TypeError -- and
        # the blanket `except` below turned that into a silent "score lost" for
        # every caller that injected one.
        mkdir_fn = io.pop("mkdir_fn", None)
        # POPPED FOR THE SAME REASON, and they are the CARD STATE's hooks rather
        # than the spool's: `_rewrite` takes neither, and `wearer_name` must not
        # inherit a fake `open_fn` that exists to simulate a full spool volume.
        name_path = io.pop("name_path", None)
        name_open_fn = io.pop("name_open_fn", None)
        # ACCEPTED AND IGNORED. `new_key` is gone, but an un-updated caller that
        # still injects a random source must get a refusal or a spooled score --
        # never a TypeError, which inside `launch()` is a badge reset.
        io.pop("urandom", None)
        path = path or DEFAULT_PATH
        open_fn = io.get("open_fn") or open
        if _slots is None:
            # THE ONE COLD READ of the boot, and it lands here rather than on a
            # rendered frame on purpose: this is the game's death frame, which
            # already pays the atomic `/state/<game>.json` save.
            slots(path, open_fn)
        standing = _slots.get(game)
        if standing is not None and score <= standing["score"]:
            return False
        if standing is None and len(_slots) >= MAX_SLOTS:
            return None
        entry = {"game": game, "score": score, PLAY_KEY: play,
                 "duration_ms": duration_ms, AT_KEY: _ticks_ms(),
                 BOOT_KEY: boot_id()}
        found = wearer_name(name_path, name_open_fn)
        if found:
            entry[NAME_KEY] = found
        # THE DOOR, WRITTEN ONLY WHEN THE CALLER NAMED ONE. Absent and blank stay
        # different facts all the way to SQL, so an older game's call spools the
        # same slot it always did rather than one claiming an empty door.
        if isinstance(end, str) and end:
            entry[END_KEY] = end[:MAX_END]
        merged = dict(_slots)
        merged[game] = entry
        _ensure_parent(path, mkdir_fn)
        _rewrite(merged, path, **io)
        # AFTER THE RENAME, NEVER BEFORE. `_rewrite` renames last, so a failure
        # part way through leaves the previous document on flash -- and RAM has to
        # keep describing that document rather than the one that did not land.
        _slots = merged
        return True
    except Exception:
        # THE GAME NEVER LEARNS. A full volume, a read-only mount, a missing
        # /state: none of them may become a traceback inside launch(), which is a
        # modal that resets the badge.
        return None


def pending(path=None, open_fn=None):
    """How many slots are waiting, 0..``MAX_SLOTS``.  One read per boot.

    SEMANTIC CHANGE, SAME NAME AND SAME CALLERS: this counts SLOTS -- at most one
    per game -- where it used to count submissions. A wearer who played snake ten
    times offline had a `pending` of 10 and now has a `pending` of 1, which is
    the truth about how many rows are waiting to be sent. The `wipe_scores` ack's
    `discarded` count reads the same way (0..5 rather than 0..64), and the
    operator guide says so.
    """

    global _slots
    if _slots is None:
        slots(path, open_fn)
    return len(_slots)


def scan_complete():
    """Whether the slots have been read this boot.  FREE: no filesystem, no
    allocation.

    The per-frame question, and the reason a frame can ask it every frame: a
    badge whose games have not been played answers "nothing to do" for an
    identity compare, so the drain never claims the frame's chore budget for it.
    """

    return _slots is not None


def cached_pending():
    """How many slots are in RAM: ``0`` when nothing has been read.  FREE.

    REPLACES `cached_head`, which returned the head ENTRY. There is no head, and
    the drain's free guard only ever needed the yes/no -- `cached_pending() == 0`
    is the same question `cached_head() is None` was asking, minus the second
    global that could disagree with the first.
    """

    return 0 if _slots is None else len(_slots)


def take_slot(path=None, open_fn=None):
    """The slot to post NEXT, or ``None``.  ROUND-ROBIN over the games.

    One whole-file read on its first call of the boot, pure RAM afterwards.

    THE ROTATION IS WHAT REPLACED `MAX_ATTEMPTS`. The old spool was a FIFO, so an
    entry the server kept refusing blocked every later score -- and the fix was to
    DELETE it after three refusals. There is no head here: a permanently refused
    snake slot delays only snake, and pong, breakout, flappy and pacman drain past
    it on the very next frame. Nothing has to be thrown away to keep the queue
    moving, because there is no queue.

    THE RETURNED DICT IS THE CALLER'S SNAPSHOT for the whole round trip.
    :func:`record` never mutates a slot in place, so a better score arriving
    mid-flight builds a NEW dict and leaves this one describing exactly what was
    posted -- which is what makes :func:`retire`'s supersede check meaningful.
    """

    global _cursor
    if _slots is None:
        slots(path, open_fn)
    if not _slots:
        return None
    names = sorted(_slots)
    index = _cursor % len(names)
    _cursor = index + 1
    return _slots[names[index]]


def retire(game, play, score, path=None, **io):
    """Clear one game's slot AFTER A SUCCESSFUL POST -- and only if it still
    stands.

    THE SUPERSEDE CHECK IS THE HEART OF THE DRAIN, and the race it closes is
    real: an identical one was fixed in the drain's own latch on 2026-08-29
    (`40cec1ff`), where a stale response would have retired a score that was
    never posted. A round trip takes frames, and a player can finish another
    round inside it.

    Three races, all resolved by comparing BOTH the play number and the score:

    * The player BEATS the score mid-flight -> the slot was replaced -> the
      (play, score) differ -> LEAVE IT. The delivered score is in the database and
      the better one is still pending. Nothing lost, nothing duplicated.
    * The player scores LOWER mid-flight -> `record` wrote nothing -> the slot is
      unchanged -> it is cleared. The low score is gone, which is the owner's
      explicit ruling: losing the LOW scores is the correct thing to lose.
    * The response is lost and the drain re-offers -> the identical tuple hits
      `on conflict do nothing` -> success -> cleared. One duplicate REQUEST, zero
      duplicate rows.

    EQUALITY, NEVER `>=`. "Erase scores" deletes `/state/<game>.json` and resets
    that game's counter, so a replacement slot's play number can be LOWER than the
    one in flight. An ordering comparison would clear a slot it has no business
    clearing.

    THERE IS ONLY ONE REASON TO CALL THIS NOW. It used to be called for a
    delivered score AND for an exhausted one; `MAX_ATTEMPTS` is gone, so delivery
    is the only thing that empties a slot from outside.

    Raises whatever the filesystem raises -- the caller guards, as it always has.
    """

    global _slots, _cursor
    path = path or DEFAULT_PATH
    open_fn = io.get("open_fn") or open
    # THE FILE, NOT RAM. This is the rare path and it already reads the whole
    # (tiny) document, so it is also the one place the cache can be re-derived
    # for free rather than guessed at -- and the whole point of the check is to
    # ask what is ON FLASH now, not what RAM believed when the post went out.
    found = _read_document(path, open_fn)
    slot = found.get(game)
    if slot is None or slot[PLAY_KEY] != play or slot["score"] != score:
        _slots = found
        _cursor = 0
        return False
    del found[game]
    _rewrite(found, path, **io)
    _slots = found
    _cursor = 0
    return True


def clear(path=None, **io):
    """Empty every slot.  For a device session and for tests, not for a game.

    Writes `{"schema": 2, "slots": {}}` -- a real, valid, EMPTY document, so a
    badge that has been cleared reads as cleared rather than as a badge whose
    spool is missing. Raises on failure; :func:`wipe` is the guarded door.
    """

    global _slots, _cursor
    _rewrite({}, path, **io)
    _slots = {}
    _cursor = 0
    return True


def wipe(path=None, **io):
    """Discard every UNDELIVERED score.  NEVER RAISES.  Returns whether it went.

    THE WEARER'S DOOR AND THE FLEET'S DOOR, and both of them are why this is not
    just :func:`clear`. One caller is a Settings action running inside
    ``launch()``, where an escaping ``OSError`` reaches the firmware's
    ``fatal_error()`` and ``machine.reset()`` -- so a full volume would turn
    "wipe my scores" into a reboot, on the exact screen that promised the wearer
    a safe way to do it. The other is the ``wipe_scores`` command applier, where
    a raise would cost the ack the fleet is waiting on.

    IT DOES NOT UN-SEND ANYTHING, and no copy above it may imply otherwise: rows
    already posted are the backend's, deletable in SQL and by nothing here.

    ON FAILURE IT FORGETS RATHER THAN CLAIMS EMPTY, which is the one subtle part.
    ``_rewrite`` renames last, so a failure leaves the previous document -- and
    the previous scores -- intact. Caching an empty dict there would strand them:
    the frame pump reads a known-zero `cached_pending` and stops draining, and no
    later read ever contradicts it. :func:`reset_cache` says "unknown" instead,
    and the next reader re-derives the truth from the file.
    """

    try:
        clear(path, **io)
        return True
    except Exception:
        reset_cache()
        return False


def wipe_bests(paths=None, remove_fn=None, stat_fn=None):
    """Delete the games' persisted personal bests.  NEVER RAISES.

    Returns ``(removed, failed)``. A file that was never written counts as
    NEITHER: a badge whose wearer never played Pong has nothing to erase there,
    and reporting that as a failure would make a completely successful wipe look
    partial on every badge. **That case is decided by whether the file is still
    there, not by an errno** -- see the comment in the loop for the port that
    proved why.

    IT NOW ERASES THE PLAY COUNTERS TOO, because they live in the same files.
    That is the owner's deliberate design and not a side effect: the SCORE is
    part of the database's primary key, so replaying to the same play index with
    a different score still creates a row. Only an identical (game, play, score)
    is deduped, and that residual loss is ruled acceptable.

    DELETION RATHER THAN A ZERO RECORD, and the reader is why: `score_sink.read`
    treats a missing file as ``missing`` and answers zero, so an absent file IS
    the never-played state. Writing ``{"high_score": 0}`` instead would leave a
    record claiming a run happened and scored nothing.

    THIS IS THE POWER THE FLEET COMMAND GATES. `scope: "spool"` never comes here;
    only `scope: "all"` does, and whether that is ever queued is an owner-level
    server-side decision on purpose (ruling, 2026-08-27) -- remote erasure of a
    wearer's personal bests must never arrive as a side effect of clearing a
    delivery backlog.
    """

    remove = remove_fn if remove_fn is not None else getattr(os, "remove", None)
    stat = stat_fn if stat_fn is not None else getattr(os, "stat", None)
    removed = 0
    failed = 0
    for path in (paths if paths is not None else GAME_STATE_PATHS):
        if remove is None:
            failed += 1
            continue
        try:
            remove(path)
            removed += 1
        except Exception:
            # NOT AN ERRNO COMPARISON, and that is a correction rather than a
            # style: this counted `args[0] == 2` as "already gone" until the
            # browser lane ran the same code and raised **44** for a missing file
            # (WASI's numbering, not POSIX's), so every never-played game counted
            # as a failure. The observable state answers the question on every
            # port, and it is also exactly what the caller is claiming.
            if stat is None:
                failed += 1
                continue
            try:
                stat(path)
            except Exception:
                # Gone, or unreachable in a way that is indistinguishable from
                # gone. Either way there is nothing left here to erase.
                continue
            failed += 1
    return removed, failed


def reset_cache():
    """Forget the cached slots, the cursor and the cached name. Tests and a fresh
    boot.

    Never a game: on hardware the cache is only ever wrong across a reset, and a
    reset is what clears it.

    IT MUST NOT CLEAR :data:`_boot`, and that is a rule rather than an omission.
    The wipe-failure path calls this, and re-minting the boot id there would
    silently strip ``age_ms`` from every slot already on flash -- every one of
    them would look like a slot from a previous boot. A test that wants a
    simulated reboot sets ``scorebox._boot = None`` itself, which is honest
    about what it is faking.
    """

    global _slots, _cursor, _name
    _slots = None
    _cursor = 0
    _name = None


def _age_ms(slot, now):
    """How long ago this slot was recorded, or ``None`` when that is unknowable.

    THE ONE AN IMPLEMENTATION GETS WRONG. `time.ticks_ms()` restarts at every
    power cycle, and on this badge LEAVING AN APP IS `machine.reset()` -- so "a
    reboot" is not a rare event, it is what happens every time the wearer presses
    HOME. Across two boots the subtraction is not a duration at all: the tick
    wraps at 2**30 and `ticks_diff` resolves into +/-2**29 ms, so it returns an
    arbitrary value within +/-6.2 days and IT CAN BE NEGATIVE. The server computes
    `now() - age_ms`, so a negative one would place the score IN THE FUTURE.

    So the measurement is only ever WITHIN A BOOT, and every one of these has to
    hold or the key is omitted entirely:

    * this port could mint a boot id at all (`boot_id()` is truthy),
    * the slot was written in THIS boot (`boot` matches),
    * the slot carries a real integer tick,
    * and the difference is between 0 and `MAX_AGE_MS`.

    THE EMPTY BOOT ID IS THE TRAP, and the truth test above it is the guard: a
    port with no `os.urandom` mints `""` on every boot, and `"" == ""` would match
    across reboots and hand back exactly the garbage this function refuses.

    A slot that survived a reset therefore posts with NO `age_ms`, and the server
    falls back to `recorded_at` -- arrival -- which is what it already does today.
    The feature degrades to the status quo instead of to a lie.
    """

    boot = boot_id()
    if not boot:
        return None
    if slot.get(BOOT_KEY) != boot:
        return None
    at = slot.get(AT_KEY)
    if isinstance(at, bool) or not isinstance(at, int):
        return None
    age = _ticks_diff(now, at)
    if age < 0 or age > MAX_AGE_MS:
        return None
    return age


def row(badge_id, slot, now=None):
    """One slot as the ``scores`` row the badge is allowed to insert.

    EXACTLY the five client-writable columns and nothing else. The wearer's name,
    the door the run left by and the age are KEYS INSIDE ``metadata`` rather than
    columns six, seven and eight -- which is the whole reason none of the three
    cost a migration and all three can be acted on with a `where` clause. The
    insert-time clock column is deliberately absent: it is server-authored, which
    is what stops a badge backdating a score to win a tiebreak.

    ``play_number`` IN THE ROW, ``play`` IN THE SLOT. The row speaks the
    database's vocabulary and the slot speaks the badge's; it is the same split
    ``duration_ms`` already has.

    NO FILE IS TOUCHED HERE, and that is a requirement rather than an
    observation: this runs on a rendered frame, and
    `test_cx10_boot_json_cost.FirstFrameTests` holds every boot frame to one
    ``open`` and one decode. The name arrives already inside the slot, put there
    by :func:`record` on the game's own death frame.

    ``now`` DEFAULTS TO THE LIVE TICK and is a parameter only so a test can pin
    an age; nothing on the badge passes it.
    """

    if now is None:
        now = _ticks_ms()
    metadata = {"duration_ms": slot["duration_ms"]}
    # ABSENT AND BLANK ARE DIFFERENT FACTS and the backend can tell them apart in
    # SQL, so an unnamed badge sends NO key rather than an empty string. Bounded
    # again here because a hand-built slot never went through `_slot`, and
    # `MAX_NAME` is the same 12 `setup` already stores -- not a second rule.
    found = slot.get(NAME_KEY)
    if isinstance(found, str) and found:
        metadata[NAME_KEY] = found[:MAX_NAME]
    found = slot.get(END_KEY)
    if isinstance(found, str) and found:
        metadata[END_KEY] = found[:MAX_END]
    # ABSENT MEANS UNKNOWN, NEVER ZERO AND NEVER A GUESS -- the same doctrine, on
    # the one key where the difference is a score placed in the wrong hour rather
    # than a missing label. See `_age_ms`.
    age = _age_ms(slot, now)
    if age is not None:
        metadata[AGE_KEY] = age
    return {
        "badge_id": badge_id,
        "game": slot["game"],
        "score": slot["score"],
        "play_number": slot[PLAY_KEY],
        # No duration column, no name column, no `end` column and no age column
        # exists, and none is wanted. SQL reads `metadata ->> 'duration_ms'`,
        # `->> 'name'`, `->> 'end'` and `->> 'age_ms'`, so the ruling's "all
        # judgment is SQL, hot-patchable" still holds: a duration, a door and an
        # age are EVIDENCE and a name is an ATTRIBUTE, and none of the four is a
        # judgment the badge made. Whether an `end = 'exit'` row at score 0
        # belongs on the board, and what `recorded_at - age_ms` means, are both
        # decided in a view that can be changed between sessions of a one-day
        # event.
        "metadata": metadata,
    }
