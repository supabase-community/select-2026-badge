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

THE ORDER IS NOT NEGOTIABLE: DISK FIRST, AND DISK WINS.  `write()` completes
the atomic local save -- including the `rename` that makes it durable -- before
anything else is offered the record.  A network sink is best-effort and
downstream by construction, so no failure, absence, timeout or bug in one can
lose, delay or corrupt the local record.  See `forward_to()` for the seam and
for why it is not called before the rename.

NOTHING HERE IS A SCHEMA BUMP, AND THAT IS LOAD-BEARING.  `read()` accepts any
dict at the sink's own schema and IGNORES keys it does not know, so a badge
running an older build reads a file written by a newer one and keeps its
record.  Bumping a schema, or adding a key to the written record, invalidates
every existing file and silently wipes the owner's high score -- the exact
failure the atomic save exists to prevent.  This module therefore writes
`schema`, `high_score` and the sink's declared extras, in that order, and
NOTHING ELSE.  There is no key for the network seam; there is nothing for it to
persist.

MICROPYTHON.  No f-strings, no `pathlib`, no comprehension where a loop is
cheaper to compile, and `os.sync` behind a `getattr` because some builds do not
have it.
"""

import json
import os


# THE SECOND SINK, AND IT DOES NOT EXIST YET.
#
# UNUSED TODAY.  Nothing in this repository calls `forward_to()`, nothing
# imports `badgelink`, and no game knows this list is here.  It is carried
# anyway because the owner has already named the next destination and because
# the seam is the part that is expensive to add later: retrofitting a
# publication point into five games means five edits to the one function that
# must not be got wrong twice.  One edit here, in one file, is the cost of
# adding it now.
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
        """Return `(high_score, extras, status)`.

        `extras` is a tuple parallel to `self.extras`; `status` is `loaded`,
        `missing` or `corrupt`.

        TOLERANT BY CONSTRUCTION, AND IT DELETES NOTHING.  A missing file is a
        badge that has never been played; a corrupt one is a badge whose write
        was interrupted.  Both read as zero and both leave the file exactly as
        found, so a later build that understands it can still recover it.
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
            return high_score, tuple(found), "loaded"
        except OSError:
            return 0, self._floor(), "missing"
        except (ValueError, TypeError, OverflowError):
            return 0, self._floor(), "corrupt"

    def _floor(self):
        """The extras of a record that could not be read: each field's low."""
        blank = []
        for field in self.extras:
            blank.append(field[1])
        return tuple(blank)

    # -- writing -------------------------------------------------------------
    def write(self, high_score, extras=(), path=None):
        """Commit a record so a power cut cannot leave a half-written file.

        Temp + flush + sync + rename.  `os.rename` over an existing name is
        atomic on the badge's FAT volume, so the record on disk is either the
        old one or the new one and never a truncated JSON fragment.  `os.sync`
        is absent on some builds, hence the `getattr`.

        Returns `(high_score, extras)` as stored.  Raises whatever the
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

        # Key order is the order these games have always written: schema,
        # high_score, then the extras.  `json.dump` follows insertion order in
        # both CPython and MicroPython, so this keeps the file byte-identical
        # to what is on the owner's badge today.
        record = {"schema": self.schema, "high_score": high_score}
        for index in range(len(self.extras)):
            record[self.extras[index][0]] = stored[index]

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
        return high_score, tuple(stored)

    # -- the rule ------------------------------------------------------------
    def commit(self, score, current, extras=(), current_extras=(), path=None):
        """Persist a run only when it beats the record.

        Returns `(high_score, extras, changed)`.  A run that does not beat the
        record writes NOTHING AT ALL -- flash wear is real and a losing run has
        no reason to touch the file, or to reach a forwarder.

        THE EXTRAS TRAVEL WITH THE SCORE AND ARE NEVER WRITTEN ALONE.  A run
        that failed to beat the record must not relabel the record it failed to
        beat: Snake's stored level is the price the standing score was earned
        at, so a losing level-9 run must leave a level-4 record reading 4.
        """
        score = max(0, int(score))
        current = max(0, int(current))
        if score <= current:
            # The standing extras are floored but NOT capped, matching the
            # five games' shipped behaviour on this path: nothing was read
            # from disk here, so there is no stored value to clamp -- only a
            # caller-supplied one to keep non-negative.
            kept = []
            for index in range(len(self.extras)):
                low = self.extras[index][1]
                given = current_extras[index] if index < len(current_extras) else low
                kept.append(max(low, int(given)))
            return current, tuple(kept), False
        high_score, stored = self.write(score, extras, path)
        return high_score, stored, True
