"""SCORE SINK -- where a game's record goes when a run ends.

FIVE GAMES WROTE THIS FILE FIVE TIMES.  Snake, REPLICA.SQL, VACUUM.SQL,
POOLER.SQL and CURSOR.SQL each carried a `<game>_store.py` holding the same
temp + flush + sync + rename dance and the same deliberately tolerant reader,
differing only in a path, a schema constant and -- in Snake's case -- one extra
field.  Four of the five were byte-identical in three of their functions.  That
is a drift hazard on the one code path that can destroy the owner's high score,
so the dance lives here once and each game keeps only its own configuration.

WHY "SINK" AND NOT "FILE", which is the whole reason this is shaped as it is.
The owner's stated plan (2026-08-19): scores save to disk today, but
"eventually we may have network connection... completing the game may make a
network request to save the game score on a network which would be cool and
might be useful to have shared code for that".  A module named for the disk
would have to be reopened and renamed to grow that; a module named for the
DESTINATION already has the right shape, with exactly one destination
implemented.

THAT SECOND DESTINATION ARRIVED ON 2026-08-27 and it is `spool()`, NOT the
`forward_to()` seam this file built for it.  The seam publishes from `write()`,
which `commit()` reaches only when the run BEAT THE RECORD, so a forwarder sees
personal bests and nothing else -- and the owner's ruling is EVERY completed run,
with no filtering on the badge.  `spool()` is therefore called from each game's
own game-over, and `forward_to` stays for a genuinely best-only destination.

THE ORDER IS NOT NEGOTIABLE: DISK FIRST, AND DISK WINS.  `write()` completes
the atomic local save -- including the `rename` that makes it durable -- before
anything else is offered the record.  A network sink is best-effort and
downstream by construction, so no failure, absence, timeout or bug in one can
lose, delay or corrupt the local record.  See `forward_to()` for the seam and
for why it is not called before the rename.

NOTHING HERE IS A SCHEMA BUMP, AND THAT IS LOAD-BEARING.  `read()` accepts any
dict at the sink's own schema and IGNORES keys it does not know, so a badge
running an older build reads a file written by a newer one and keeps its
record.  Bumping a schema, or removing a key, invalidates every existing file
and silently wipes the owner's high score -- the exact failure the atomic save
exists to prevent.  This module therefore writes `schema`, `high_score`, the
sink's declared extras and `plays`, in that order, and NOTHING ELSE.  There is
no key for the network seam; there is nothing for it to persist.

`plays` IS THE ONE KEY THIS RULE HAS EVER ADMITTED, and it was admitted exactly
BECAUSE of the rule (2026-08-29).  A score is now unique in the database as
`(badge_id, game, play_number, score)`, so every game needs a durable count of
its own completed runs -- and adding it as a new key at SCHEMA 1 means an older
build reads a file this one wrote and keeps its high score, while this build
reads an older file and counts `plays` as 0, which is the correct "never played
under a counting build" answer.  Bumping the schema instead would have wiped
every badge's record on the day the counter shipped.

AND IT REVERSED ONE RULE, WHICH IS THE ONE THING TO KNOW BEFORE READING
`commit()`.  "A run that does not beat the record writes NOTHING AT ALL" was a
flash-wear saving, and it is gone: the counter changes on EVERY completed run
and has to be durable, so a losing run writes the standing record back with the
new count.  The companion rule survives untouched -- a losing run still writes
the STANDING extras and never its own.

MICROPYTHON.  No f-strings, no `pathlib`, no comprehension where a loop is
cheaper to compile, and `os.sync` behind a `getattr` because some builds do not
have it.
"""

import json
import os


# THE OFFLINE SCORE SPOOL, GUARDED, AND THE GUARD IS THE WHOLE REASON THIS IMPORT
# IS HERE RATHER THAN IN FIVE APPS.
#
# `scorebox` lives in `/system/lib`, which the production roster now requires.
# The guard still matters because apps and the shared library are installed by
# separate steps and a damaged or half-refreshed badge can have one without the
# other. An `ImportError` raised inside `launch()` is a traceback modal and
# `machine.reset()`, so an unguarded import would make every game UNOPENABLE
# rather than merely unscored.
#
# `except Exception`, not `except ImportError`, for `system/main.py`'s reason: a
# half-refreshed `/system/lib` can fail an import in more ways than one, and none
# of them is worth a reset.  `settings` carries the same shape one level down.
#
# MODULE SCOPE, NOT LAZY, and that is a frame-cost decision.  The first import of
# a `.mpy` is a real load; taken lazily it would land on the death frame, which
# already pays the 7-130 ms atomic save.  Taken here it lands during the app's
# own loading screen, where nothing is on the clock.
try:
    import scorebox
except Exception:  # noqa: BLE001 - a missing library may not cost the game
    scorebox = None


# THE PLAY COUNTER'S BOUNDS, RESTATED RATHER THAN IMPORTED.  They mirror
# `scorebox.MIN_PLAY` / `scorebox.MAX_PLAY`, which mirror
# `scores_play_number_check`, and they are spelled here because the import above
# is GUARDED: `scorebox` is `None` on a badge with no `/system/lib`, and a game's
# high-score file must still be readable and writable there.  A pin test holds
# the two pairs together.
#
# CLAMPED ON BOTH READ AND WRITE, for `MAX_SCORE`'s reason: a corrupted counter
# is refused HERE, for free, rather than by a database CHECK the wearer's score
# then has to survive.  AT THE CAP THE COUNTER STOPS RATHER THAN WRAPPING -- every
# further run reuses play 1000000, and an identical (game, play, score) tuple
# dedupes, so the failure mode is "no new rows for this game" and not "rows
# attributed to play 3".  A wearer would have to finish a million 1-3 minute
# rounds to reach it.
MIN_PLAYS = 0
MAX_PLAYS = 1000000

#: The record's key for it.  Written LAST, after `high_score` and the extras, so
#: a badge's existing file gains a key at the end rather than changing shape.
PLAYS_KEY = "plays"


def _clamp_plays(value):
    return max(MIN_PLAYS, min(MAX_PLAYS, int(value)))


# THE SECOND SINK, AND IT IS NOT THIS SEAM.  READ THIS BEFORE USING `forward_to`.
#
# UNUSED TODAY, and it was UNUSABLE for the destination it was built for.
# `_publish` is reached only from `write()`, and `write()` used to be reached
# from `commit()` only when the run BEAT THE RECORD -- so a forwarder registered
# here saw personal bests and nothing else.  The owner's scoring ruling
# (2026-08-27) is EVERY-RUN with no client-side filtering, because
# personal-best-on-the-badge is judgment and all judgment is SQL, hot-patchable.
# Publishing the leaderboard through this seam would therefore have implemented,
# silently, the exact filtering the ruling forbids.
#
# ⚠ THAT IS NO LONGER WHAT A FORWARDER SEES, and a future user of this seam has
# to know it: since the play counter landed (2026-08-29) `commit()` ALWAYS
# writes, so a forwarder now sees every completed run, with a LOSING run carrying
# the STANDING record's score rather than the run's own.  The seam is still not
# the leaderboard's path -- `spool()` is -- and it is still best-only in intent,
# so a "new record" destination must read `changed` from `commit()` rather than
# infer it from being called.
#
# So the every-run path is `spool()` below, called from each game's own
# game-over, and this list is left in place because a genuine best-only
# destination (a "new record" announcement, say) would still want it.
_FORWARDERS = []
#
# A FORWARDER MUST RETURN IMMEDIATELY.  It is called from `write()`, which is
# reached from a game's `finish_game()`, which is reached from `update()` --
# inside the frame loop.  Snake measured its own atomic save at 7-130 ms median
# with a 185 ms tail (`docs/engineering-findings.md`), and that is already the
# most expensive thing a frame can do on purpose.  A forwarder that transmits
# synchronously would add a network round trip on top of it and drop frames on
# the death animation.  So the contract is: ENQUEUE AND RETURN.  Whoever adds
# networking transmits from their own loop, their own `on_exit`, or their own
# socket's write-ready callback -- never from here.
#
# This module cannot enforce that, and pretending otherwise would be worse than
# saying it plainly: it can only guarantee what is on its own side of the call.
# It calls each forwarder exactly ONCE per committed record, never retries,
# never sleeps, never waits for a result, and swallows every exception a
# forwarder raises.  Retry, queueing, batching and back-off belong to the
# forwarder, which is the only thing that will know what the transport costs.
_FORWARDERS = []


def forward_to(callback):
    """Register a best-effort second destination for committed records.

    `callback(name, record)` is called after -- and only after -- a successful
    local save, where `name` is the sink's short game name ("snake", "pong")
    and `record` is the dict just written to disk.  The dict is freshly built
    per write and is not read again afterwards, so the callback may keep it.

    Returns the callback, so it can be used as a decorator.

    NOT CALLED ANYWHERE TODAY.  See the note above `_FORWARDERS` for the
    contract a caller has to keep and for why the seam exists before its
    first user.
    """
    if callback not in _FORWARDERS:
        _FORWARDERS.append(callback)
    return callback


def spool(name, score, play, elapsed_ms=0, end=None):
    """Offer one COMPLETED RUN to the offline score spool.  NEVER RAISES.

    The every-run submission path (owner ruling, 2026-08-27): every completed
    game submits, with NO client-side filtering, because personal-best-on-the-
    badge would be judgment and all judgment is SQL and hot-patchable.  What the
    leaderboard DISPLAYS is a server-side view decision and can change mid-event.

    CALLED WHEREVER THE GAME ALREADY BANKS THE RUN TO FLASH, and that rule is the
    whole of the placement argument: if the app already considers a run finished
    enough to write it to `/state`, it is finished enough to send.  It adds no new
    door and no new judgment -- deciding a quit run "does not count" would be
    exactly the client-side filtering the ruling forbids.

    `end` IS THE DOOR THE RUN LEFT BY -- the game's own banking `reason`, one of
    "finish", "quit" or "exit" -- and it exists because the sentence that used to
    end the paragraph above was WRONG.  It read "the server can tell a walk-away
    from a death from the score and the duration", and 2026-08-29 disproved it: a
    real drained row read `snake score 0 duration_ms 584` against the same badge's
    `snake 24 @ 17216ms`, and 584 ms is inside snake's genuine instant-death range
    at the default level.  Score and duration cannot separate those two runs; only
    the door can.  So the badge LABELS and still sends -- suppressing the row here
    would be the client-side judgment the ruling forbids, and a genuine zero is a
    real thing a player does.  `scorebox` carries it in `metadata` as `end`, where
    SQL can act on it and be changed mid-event.

    AFTER the local save, never before.  `write()`'s ordering rule ("DISK FIRST,
    AND DISK WINS") is not negotiable, and it applies harder here than to the
    forwarder seam: the spool is one `open`/`write`/`sync`, so on a full volume it
    is one more thing that can fail on the frame the atomic save is already
    failing on.

    THE FRAME COST, STATED: an append plus an `os.sync` on top of a save measured
    at 7-130 ms median with a 185 ms tail (`docs/engineering-findings.md`).  It
    lands on the death/quit frame, which is already the most expensive frame these
    games draw on purpose, and there is nowhere cheaper to put it -- the game owns
    the only copy of the score, and the pump that drains the spool runs frames
    later, in another module, with no way to ask.

    `elapsed_ms` IS WALL TIME FROM THE RUN STARTING, PAUSES INCLUDED, and 0 means
    NOT KNOWN.  A run whose measured wall time falls outside the `scores` column's
    own bound (a game left paused overnight, then quit) reports 0 rather than
    losing the score to `record`'s refusal or asserting a clamped figure nothing
    measured.  Nothing here invents a duration from model ticks: a step counter
    times the SIMULATION, not the player, and a fabricated duration would be worse
    than a missing one because no server-side check can falsify it.

    `play` IS HOW MANY TIMES THIS GAME HAS NOW BEEN FINISHED, and it is a
    REQUIRED POSITIONAL argument on purpose -- the one place in this file where a
    stale caller is meant to be loud.  `score_sink` is VENDORED into all five
    games by `scripts/sync_ui.py`, so it always ships in the same install unit as
    the game that calls it; a call site that has not been updated is therefore a
    build-time mistake, and a `TypeError` a test catches is better than a silently
    mis-typed duration landing in the play field.  `scorebox` is the opposite case
    and takes it as a keyword: see below.

    It is the number the run was set at -- the counter incremented FIRST, then
    saved, then passed here -- and it makes the row unique in the database as
    `(badge_id, game, play_number, score)`, which is what replaced the random
    idempotency key.  Re-posting the identical tuple is a 200 and no new row.

    Returns `record`'s own answer unchanged: True when a slot was written, False
    when a better or equal score for this game is already waiting (normal, and
    nothing is written), None when nothing was spooled -- a badge with no
    `/system/lib`, a refused row, or a filesystem that would not take it.
    """
    if scorebox is None:
        return None
    try:
        if elapsed_ms < 0 or elapsed_ms > scorebox.MAX_DURATION_MS:
            elapsed_ms = 0
        # EVERY ARGUMENT BY KEYWORD, AND THAT IS THE VERSION-SKEW RULE.  The app
        # and `/system/lib` are refreshed by SEPARATE install steps, so the two
        # signatures cannot be assumed to move together and this call has to
        # survive being one version ahead of the module it reaches.  A positional
        # `play` would land in `record`'s `path` on an older lib and write the
        # badge's scores to a file named after an integer; a keyword lands in
        # `**io`, where an older `record` ignores it and spools the old shape.
        # Against a NEWER lib a missing `play` is a refusal rather than a
        # mis-typed field, which is the other half of the same rule.
        return scorebox.record(name, score, duration_ms=elapsed_ms,
                               play=play, end=end)
    except Exception:  # noqa: BLE001 - see below
        # DEFENCE IN DEPTH, and it is deliberate rather than superstitious.
        # `record` documents and tests "it NEVER RAISES" -- but the badge runs
        # whatever `.mpy` its `/system/lib` happens to hold, which is refreshed by
        # a separate install step from the app, and an exception escaping here
        # reaches the firmware's `fatal_error()` and `machine.reset()`.  So the
        # cost of being wrong is EVERY DEATH BECOMING A REBOOT, on the one screen
        # whose job is to show the player their score, and the cost of the guard
        # is two lines.  Same trade `_publish` takes above it, for the same
        # reason: a sink may not break a finished game.
        return None


def forget(callback):
    """Drop a forwarder.  Present so a test can register one and clean up."""
    try:
        _FORWARDERS.remove(callback)
    except ValueError:
        pass


def _publish(name, record):
    """Offer a committed record to every forwarder.  Never raises, ever.

    The local save is already durable when this runs, so there is nothing here
    worth reporting to the player and nothing worth failing a save over.  A
    forwarder that raises is simply skipped for this record; a forwarder that
    is slow has broken its own contract and this module has no way to undo
    that.
    """
    for index in range(len(_FORWARDERS)):
        try:
            _FORWARDERS[index](name, record)
        except Exception:  # noqa: BLE001 - a sink cannot break a saved score
            pass


class ScoreSink:
    """One game's record: where it lives, what shape it is, how it is written.

    `name` is the short game name, used only to label a record offered to a
    forwarder.  `path` and `schema` are the persisted contract and must never
    change for a game that has shipped.  `label` appears in the `ValueError`
    raised internally on a rejected file; it is never shown to a player and
    exists so a serial log names the game.

    `extras` declares OPTIONAL COMPANION FIELDS as `(name, low, high)` tuples,
    which is how Snake's `high_level` is carried without inventing a level for
    the four games that have no wager.  An extra is an integer clamped into
    `[low, high]` on both read and write, defaults to `low` when the key is
    absent, and is written AFTER `high_score` so the record's key order is the
    order the game has always written.
    """

    def __init__(self, name, path, schema, label, extras=()):
        self.name = name
        self.path = path
        self.schema = schema
        self.label = label
        self.extras = tuple(extras)

    # -- reading -------------------------------------------------------------
    def read(self, path=None):
        """Return `(high_score, extras, plays, status)`.

        `extras` is a tuple parallel to `self.extras`; `plays` is how many runs
        of this game have been finished; `status` is `loaded`, `missing` or
        `corrupt`.

        `plays` IS INSERTED BEFORE `status` AND NOT APPENDED AFTER IT, so
        `status` stays last in a tuple every caller unpacks positionally.  A new
        field at the end would have read as a status on any call site that was
        not updated; a new field in the middle is a loud unpack error.

        AN ABSENT `plays` IS 0, which is the correct "never played under a
        counting build" answer: every badge in the field has a file without the
        key, and those wearers' high scores are the thing that must survive.

        TOLERANT BY CONSTRUCTION, AND IT DELETES NOTHING.  A missing file is a
        badge that has never been played; a corrupt one is a badge whose write
        was interrupted.  Both read as zero and both leave the file exactly as
        found, so a later build that understands it can still recover it.  A
        `plays` value that is not a number makes the file corrupt exactly as a
        non-numeric extra already does -- one rule for every field, rather than a
        second, gentler rule for the newest one.
        """
        if path is None:
            path = self.path
        try:
            with open(path, "r") as source:
                value = json.load(source)
            if not isinstance(value, dict) or value.get("schema") != self.schema:
                raise ValueError("invalid %s state" % self.label)
            high_score = max(0, int(value.get("high_score", 0)))
            found = []
            for field in self.extras:
                key, low, high = field
                found.append(max(low, min(high, int(value.get(key, low)))))
            plays = _clamp_plays(value.get(PLAYS_KEY, MIN_PLAYS))
            return high_score, tuple(found), plays, "loaded"
        except OSError:
            return 0, self._floor(), MIN_PLAYS, "missing"
        except (ValueError, TypeError, OverflowError):
            return 0, self._floor(), MIN_PLAYS, "corrupt"

    def _floor(self):
        """The extras of a record that could not be read: each field's low."""
        blank = []
        for field in self.extras:
            blank.append(field[1])
        return tuple(blank)

    # -- writing -------------------------------------------------------------
    def write(self, high_score, extras, plays, path=None):
        """Commit a record so a power cut cannot leave a half-written file.

        Temp + flush + sync + rename.  `os.rename` over an existing name is
        atomic on the badge's FAT volume, so the record on disk is either the
        old one or the new one and never a truncated JSON fragment.  `os.sync`
        is absent on some builds, hence the `getattr`.

        `plays` IS A REQUIRED THIRD POSITIONAL, AND `extras` LOST ITS DEFAULT
        WITH IT.  That deliberately breaks `pong_store.save(high_score, (), path)`
        LOUDLY: with a default, a caller that had not been updated would pass its
        `path` where `plays` belongs, or silently write a zero over a counter the
        wearer had earned, and a zeroed counter re-mints play numbers the
        database already holds.  A `TypeError` at build time is the cheap
        version of that mistake.  This module is vendored per game, so every call
        site ships with it.

        Returns `(high_score, extras, plays)` as stored.  Raises whatever the
        filesystem raises: a badge that cannot write its record must not
        silently believe it did, and that has been the behaviour of all five
        games since they shipped.

        THE FORWARDERS ARE OFFERED THE RECORD LAST, after the rename has made
        the local save durable.  Ordering it the other way -- publish, then
        write -- would let a network hiccup delay or prevent the save that is
        actually authoritative.
        """
        if path is None:
            path = self.path
        high_score = max(0, int(high_score))
        stored = []
        for index in range(len(self.extras)):
            key, low, high = self.extras[index]
            given = extras[index] if index < len(extras) else low
            stored.append(max(low, min(high, int(given))))
        plays = _clamp_plays(plays)

        # Key order is the order these games have always written: schema,
        # high_score, then the extras -- and `plays` is APPENDED after them, so a
        # badge's existing file gains a key at the end rather than changing
        # shape.  `json.dump` follows insertion order in both CPython and
        # MicroPython, so a file written before the counter existed and one
        # written after it differ by exactly one trailing key.
        record = {"schema": self.schema, "high_score": high_score}
        for index in range(len(self.extras)):
            record[self.extras[index][0]] = stored[index]
        record[PLAYS_KEY] = plays

        parent = path.rsplit("/", 1)[0]
        try:
            os.mkdir(parent)
        except OSError:
            pass
        temporary = path + ".tmp"
        with open(temporary, "w") as output:
            json.dump(record, output)
            output.flush()
        sync = getattr(os, "sync", None)
        if sync is not None:
            sync()
        os.rename(temporary, path)
        _publish(self.name, record)
        return high_score, tuple(stored), plays

    # -- the rule ------------------------------------------------------------
    def commit(self, score, current, plays, extras=(), current_extras=(),
               path=None):
        """Persist the run: the record when it beats one, the count always.

        Returns `(high_score, extras, changed)`.

        *** IT NOW ALWAYS WRITES, AND THAT REVERSES A SHIPPED RULE. *** "A run
        that does not beat the record writes NOTHING AT ALL" was a flash-wear
        saving and it cannot survive the play counter: the count changes on every
        completed run, the score it prices is unique in the database as
        `(badge_id, game, play_number, score)`, and a counter that is only
        durable on a winning run would re-mint play numbers the database already
        holds -- silently, because `on conflict do nothing` answers 200.

        THE COST, STATED: a losing run now pays one atomic save (7-130 ms median,
        185 ms tail) where it used to pay nothing.  A completed run pays at most
        two -- this one always, and the slot file only when the score actually
        replaces one -- so the worst death frame roughly doubles to ~370 ms.  It
        lands on the frame that already pays the most on purpose.

        THE EXTRAS TRAVEL WITH THE SCORE AND ARE NEVER WRITTEN ALONE, and THAT
        rule is untouched.  A run that failed to beat the record must not relabel
        the record it failed to beat: Snake's stored level is the price the
        standing score was earned at, so a losing level-9 run must leave a
        level-4 record reading 4.  The losing arm therefore writes `current` and
        `current_extras`, which is the standing record read back out with a new
        count.
        """
        score = max(0, int(score))
        current = max(0, int(current))
        if score <= current:
            # The standing extras are floored here, matching the five games'
            # shipped behaviour on this path: nothing was read from disk, so
            # there is no stored value to clamp -- only a caller-supplied one to
            # keep non-negative.  `write` then applies the declared ceiling as it
            # does to any other value it stores, which is new only because this
            # arm did not reach `write` before.
            kept = []
            for index in range(len(self.extras)):
                low = self.extras[index][1]
                given = current_extras[index] if index < len(current_extras) else low
                kept.append(max(low, int(given)))
            high_score, stored, _plays = self.write(current, kept, plays, path)
            return high_score, stored, False
        high_score, stored, _plays = self.write(score, extras, plays, path)
        return high_score, stored, True
