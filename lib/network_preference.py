"""Atomic physical-holder preference for BadgeLink network access.

Pairing answers *whose* badge this is.  This file answers the separate local
question *may this badge use its radio for BadgeLink?*  Anyone holding the
badge may change it from Settings, and neither value edits or removes the
durable pair state in ``/badgelink_state.json``.

ABSENT IS NOT UNUSABLE, AND ONLY ABSENT DEFAULTS ON (owner ruling, 2026-08-28).
A record that is CORRUPT, truncated, over :data:`MAX_BYTES`, wrong-schema, not a
dict, or present-but-unreadable still fails closed to OFF, exactly as it always
has.  A file that has NEVER EXISTED answers :data:`ABSENT` and the radio comes up
ON.  The write still follows the device-wide temp -> flush -> sync -> rename rule
so a power cut cannot turn an incomplete record into an enabled radio.

WHY THE VIRGIN BADGE HAD TO CHANGE.  The switch lives under ``/state``, which is
the WEARER's partition, and ``scripts/export-handover.py`` refuses to ship
anything from there (``"%d leak(s) found; NOTHING SHIPS"``) because one badge's
``/state`` copied onto ~1,000 would leak that person's name, scores and
card.  So the golden image is FORBIDDEN to carry this file, every freshly flashed
badge booted with no record, and no record meant OFF -- ~1,000 badges arriving with
their radios dark unless a human remembered to press Settings > Network on a
master badge before the image was cut (silently fatal if forgotten) or touched
all ~1,000 after flashing.  The default is the only place this can be fixed.

THE ACCEPTED CONSEQUENCE, WEIGHED AND CHOSEN -- DO NOT "FIX" IT BACK.  Wiping
``/state`` also produces absent, so a wipe now RE-ENABLES networking rather than
leaving it off.  The owner has weighed that against ~1,000 badges arriving dark and
chosen this.  It is a known, accepted trade-off, not an oversight; a wearer who
wants the radio off after a wipe presses Settings > Network once, and that
deliberate ``enabled: false`` record then wins for ever (it is present and valid,
so it is neither absent nor unusable).

HOW A HALF-WRITTEN FILE IS STILL UNUSABLE, which is the property this module was
built around and the one the new default must not weaken.  :func:`save` NEVER
opens ``path`` for writing -- it writes ``path + ".tmp"``, flushes, syncs, and
atomically renames onto ``path``.  So the directory ENTRY for ``path`` is only
ever created or replaced by a rename of an already-synced complete record, and a
power cut leaves ``path`` either untouched (the previous complete record, or no
entry at all on a badge that has never saved) or fully replaced.  This module
cannot produce a torn ``path``.  And structurally it could not be mistaken for
absence even if something else produced one: **absence is a property of the
directory entry, not of the bytes.**  A half-written file HAS a directory entry,
so its ``open`` SUCCEEDS and its failure necessarily lands in the read, the
decode or the schema check -- every one of which answers ``None`` -> OFF.  The
ON default is reachable ONLY when ``open`` itself fails, which requires there to
be no entry to open.  Truncation, garbage, a torn tail and an over-cap file all
stay OFF by construction, not by a check that could be forgotten.

NOT BY AN ERRNO, AND THAT IS MEASURED (2026-08-28).  The obvious spelling of
"the file is not there" is ``exc.errno == errno.ENOENT``, and it is WRONG on a
port this repository actually runs.  In the pinned Badgeware runtime
(``playground/public/runtime``, MicroPython ``b29530ab`` -- the same firmware
commit the badge mirrors) ``errno.ENOENT`` is **2** while ``open`` on a missing
file raises **44**, so that comparison is FALSE for a genuinely missing file and
would have shipped ~1,000 dark badges anyway.  Hard-coding 2 is the same bug this
repository has already corrected twice (``settings/badge/settings/score_wipe.py``
and ``scorebox.wipe_bests``, both burned by the same 44).  So this module never
compares an errno.  It splits on WHICH STEP FAILED instead, which is portable:
``open`` raising means there was nothing to open; anything failing AFTER a
successful ``open`` means the file is there and is not usable.

THE SECOND SWITCH, AND WHY IT FAILS THE OTHER WAY (P6-L3, 2026-08-21).  The same
record also carries the PUSH preference: whether this badge may use the Realtime
doorbell on top of polling.  Two deliberate asymmetries:

* it lives in the SAME file and the SAME atomic write, because two files would
  mean two writes and a window where a power cut leaves the pair disagreeing;
* it defaults **ON** where the radio switch defaults OFF FOR AN UNUSABLE RECORD
  (since 2026-08-28 the radio also defaults ON for an ABSENT one, so on a virgin
  badge the two now agree; the asymmetry below is unchanged and still decides
  every corrupt, over-cap and old record), and the schema number is NOT bumped
  for it.  Absent means ON because push cannot start a radio the
  wearer did not already turn on — ``enabled`` gates it — so the fail-open here
  cannot produce unasked-for radio work, while a fail-closed would silently
  disable the feature on every badge whose ``/state`` was wiped or whose record
  predates this field.  Bumping the schema would have been worse still: every
  existing schema-1 record would have failed closed and TURNED THE RADIO OFF on
  a badge whose holder had turned it on.
"""

import json
import os


SCHEMA = 1
DEFAULT_PATH = "/state/badgelink-network.json"
#: Absent or malformed ``push`` means ON. See the module note.
PUSH_DEFAULT = True

#: THE PRE-DECODE BOUND (CX-10 sub-claim 4). The record this module writes is
#: ``{"schema": 1, "enabled": true, "push": true}`` -- 45 bytes -- so 4 KB is
#: ninety times the only file that belongs here. Past the cap the load answers
#: ``None``, which is the same fail-closed answer a corrupt record already gets:
#: OFF for the radio, ON for push, and one Settings press to correct.
MAX_BYTES = 4096


class _Absent:
    """The type of :data:`ABSENT`.

    A one-instance class rather than ``object()`` so a traceback, a REPL or a
    failing assertion NAMES the sentinel instead of printing an anonymous
    address -- this value crosses a module boundary into `network_runtime`, and
    "what is this object" must not need a grep to answer.
    """

    def __repr__(self):
        return "network_preference.ABSENT"


#: THE FILE HAS NEVER EXISTED -- a virgin badge, or a wiped ``/state``.
#:
#: DISTINCT FROM ``None`` ON PURPOSE, and the choice of shape is what keeps this
#: change small.  ``None`` keeps its exact old meaning ("present, and not
#: usable"), so ``enabled_from(None)``, ``push_from(None)`` and the ``None`` an
#: over-cap or corrupt record still returns all behave exactly as they did; the
#: only new behaviour is reachable only through this new value.  The alternatives
#: were a second return value or a separate absence query, and both would have
#: had to change every ``load_record`` call site -- including the single boot
#: read `network_runtime.__init__` is pinned on (CX-10 sub-claim 1).  With a
#: sentinel that call site does not change at all: it already hands whatever it
#: got straight to :func:`enabled_from` and :func:`push_from`, which are the two
#: places that know what a record MEANS.
#:
#: Truthy, unlike ``None``.  No caller tests a record for truthiness today (the
#: only two readers, the derivers below, both use ``is None``), and a reader who
#: adds one must decide which of the two no-record states they meant.
ABSENT = _Absent()


def _directory(path):
    if "/" not in path:
        return None
    head = path.rsplit("/", 1)[0]
    return head or None


def load_record(path=DEFAULT_PATH, open_fn=open):
    """The stored record, :data:`ABSENT`, or ``None``.

    Three answers, not two:

    * a ``dict`` -- a present, in-cap, schema-matching record;
    * :data:`ABSENT` -- there was nothing to open.  The radio defaults ON;
    * ``None`` -- the file is THERE and is not usable (unreadable, over
      :data:`MAX_BYTES`, undecodable, not a dict, wrong schema).  OFF, as always.

    ONE CALL ANSWERS BOTH SWITCHES, and that is why it is the entry point
    `network_runtime` uses: `load` and `load_push` each call this, so a
    constructor that asked both questions opened and DECODED the same file twice
    before the launcher's first frame (CX-10 sub-claim 1).  The absence
    distinction is drawn from THAT SAME SINGLE READ and adds no ``stat``, no
    ``listdir`` and no second ``open`` -- the information was always there, in
    which step raised, and was being thrown away by one shared ``except``.

    BOUNDED BEFORE THE DECODE (:data:`MAX_BYTES`): ``read(MAX_BYTES + 1)`` and
    the extra byte is how an over-cap file is refused without allocating it.
    """

    try:
        handle = open_fn(path, "r")
    except OSError:
        # NOTHING TO OPEN -> no directory entry -> this badge has never been
        # told.  THE ONLY BRANCH THAT DEFAULTS THE RADIO ON, and it is reachable
        # only here: every failure downstream of a successful open belongs to a
        # file that EXISTS, so a torn, truncated or corrupt record cannot arrive
        # in this branch (module note, "HOW A HALF-WRITTEN FILE IS STILL
        # UNUSABLE").  Deliberately NOT gated on ``errno == ENOENT``: the pinned
        # runtime raises 44 here while its own ``errno.ENOENT`` is 2, so that
        # gate would be false for a genuinely missing file and would ship dark
        # badges -- the same errno trap ``score_wipe`` and ``scorebox`` already
        # paid for.
        return ABSENT
    except (ValueError, TypeError):
        # A non-OSError refusal from an injected filesystem.  Unclassifiable, so
        # it keeps the fail-closed answer it has always had.
        return None
    try:
        with handle as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        record = json.loads(raw)
    except (OSError, ValueError, TypeError):
        # PAST THE OPEN, so the file is there.  An I/O error reading it is a
        # present-but-unreadable record, which is unusable and not absent.
        return None
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return None
    return record


def enabled_from(record):
    """A loaded record -> the radio switch.  UNUSABLE means OFF, ABSENT means ON.

    Split out of :func:`load` so a caller that already holds the record can
    derive both switches from it. The two default the opposite ways ON PURPOSE
    for an unusable record (see the module note), so neither may be inferred
    from the other.

    ``ABSENT`` IS CHECKED FIRST AND SEPARATELY.  Order matters only for
    readability here -- the two sentinels are distinct objects -- but keeping
    the ON case above the OFF case is what makes it visible that exactly one
    input produces ON without a stored ``enabled``.
    """

    if record is ABSENT:
        # A badge nobody has ever told.  The golden image cannot carry this file
        # (it lives under ``/state``, which never ships), so this is what ~200
        # freshly flashed badges see on their first boot.  Module note, "WHY THE
        # VIRGIN BADGE HAD TO CHANGE".
        return True
    if record is None:
        return False
    value = record.get("enabled")
    return value if isinstance(value, bool) else False


def push_from(record):
    """A loaded record -> the push switch. Absent or invalid means ON.

    UNCHANGED BY THE 2026-08-28 RULING, for every input it has ever had and for
    the new one.  ``ABSENT`` was previously delivered here as ``None`` and
    answered ``PUSH_DEFAULT``; it is now delivered as ``ABSENT`` and answers
    ``PUSH_DEFAULT``.  The push default was argued separately (module note) and
    is not this change's to move.
    """

    if record is None or record is ABSENT:
        return PUSH_DEFAULT
    value = record.get("push")
    return value if isinstance(value, bool) else PUSH_DEFAULT


def load(path=DEFAULT_PATH, open_fn=open):
    """Return the stored boolean; ABSENT means ON, unusable means OFF."""

    return enabled_from(load_record(path, open_fn))


def load_push(path=DEFAULT_PATH, open_fn=open):
    """Whether push is allowed on this badge; absent or invalid means ON."""

    return push_from(load_record(path, open_fn))


def save_push(push, path=DEFAULT_PATH, open_fn=open, sync_fn=None,
              rename_fn=None, mkdir_fn=None):
    """Atomically store the PUSH preference, preserving the radio switch.

    ON A VIRGIN BADGE THIS WRITES THE DEFAULT DOWN, and that is correct rather
    than a side effect to remove: :func:`load` reports the badge's EFFECTIVE
    radio state, which for an absent record is now ON, so the first push write
    persists the ON the badge was already running with.  Persisting anything
    else would change the radio as a side effect of touching the doorbell, which
    is the exact asymmetry :func:`save`'s ``push=None`` exists to prevent in the
    other direction.
    """

    if not isinstance(push, bool):
        raise ValueError("push preference must be boolean")
    return save(load(path, open_fn), path, open_fn, sync_fn, rename_fn,
                mkdir_fn, push=push)


def save(enabled, path=DEFAULT_PATH, open_fn=open, sync_fn=None,
         rename_fn=None, mkdir_fn=None, push=None):
    """Atomically store ``enabled`` and return the exact stored value.

    ``push=None`` PRESERVES whatever push preference is already on disk, so the
    Network screen's Start/Stop cannot silently re-enable a doorbell the wearer
    turned off (or vice versa) as a side effect of touching the radio.
    """

    if not isinstance(enabled, bool):
        raise ValueError("network preference must be boolean")
    if push is None:
        push = load_push(path, open_fn)
    elif not isinstance(push, bool):
        raise ValueError("push preference must be boolean")
    directory = _directory(path)
    if directory:
        make = mkdir_fn or os.mkdir
        try:
            make(directory)
        except OSError:
            pass
    temporary = path + ".tmp"
    with open_fn(temporary, "w") as output:
        json.dump({"schema": SCHEMA, "enabled": enabled, "push": push}, output)
        flush = getattr(output, "flush", None)
        if flush is not None:
            flush()
    sync = sync_fn if sync_fn is not None else getattr(os, "sync", None)
    if sync is not None:
        sync()
    (rename_fn or os.rename)(temporary, path)
    return enabled
