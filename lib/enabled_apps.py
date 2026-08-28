"""The enabled-apps gate: the badge half of ``public.badges.enabled_apps``.

``data_api.read_own_badge`` has selected ``enabled_apps`` since the profile read
was written and NOTHING has ever consumed it (BADGE_FREEZE_ADDENDUM §D calls the
seam inert). This module is the consumer, and it is deliberately only HALF of the
feature: it WRITES a note to ``/state``; the LAUNCHER reads that note and drops
the gated names out of its grid scan (``launcher/menu/ui.py``, §THE ENABLED-APPS
GATE).

WHY A FILE AND NOT AN IMPORT, which is the whole shape of this module. The
launcher cannot import anything from ``/system/lib``: that payload and the
launcher are installed by two different steps, and a module-scope import of a
file a half-refreshed lib does not carry raises inside ``launch()``, which is
``fatal_error`` -> modal -> ``machine.reset()`` -> boot -> the same failing
import. That is the USB-recovery loop, on THE ONE APP WHOSE FAILURE NEEDS USB TO
RECOVER. So the two sides share a FILE, exactly as ``setup_state`` and
``setup`` do, and the launcher's reader is an independent copy that imports
nothing. ``launcher/tests/test_app_gating.py`` runs both copies over one table
and fails on any drift.

FAIL-SOFT IS THE OWNER'S HARD REQUIREMENT AND IT HAS ONE DIRECTION: a missing,
empty, corrupt or unparseable payload means ALL APPS ENABLED, never an empty
launcher. A badge that cannot read the setting is a fully working badge. Every
branch below that cannot produce a trustworthy list therefore ends at "no gate"
-- and "no gate" is the ABSENCE of the file, so the launcher's cheapest path
(one failed ``open``) is also the safe one.

THE PAYLOAD IS AN ALLOW-LIST, because the column is (``enabled_apps text[]``,
``badgelink.sql:24``). An installed app the list does not name is gated out. An
app the list names that this badge does not carry is simply never matched, which
is why a stale or fleet-wide list cannot crash a badge -- see :func:`gate`.

MicroPython surface only: ``json`` and ``os``, no ``re``, no f-strings, no
``typing``. The write is temp -> flush -> os.sync -> rename, the device-wide save
discipline -- the only sequence that survives power loss on LittleFS.

THIS MODULE IMPORTS NO SIBLING (BADGE_FREEZE_ADDENDUM §E): a ``/system/lib``
module that imports a neighbour at module scope takes the BOOT down rather than
one feature when the lib is half-refreshed. That is why :func:`_valid_slug` is
spelled here instead of imported from ``openapp_note``, which owns the identical
class; ``badgelink/tests/test_enabled_apps.py`` pins the two against each other.
"""

import json
import os


SCHEMA = 1

#: Written by this module, read by ``launcher/menu/ui.py``. The name carries the
#: ``badgelink-`` prefix every other note this lane writes to ``/state`` carries,
#: so an operator listing the directory can tell which subsystem owns a file.
DEFAULT_PATH = "/state/badgelink-enabled-apps.json"

# The constraint's slug class bound (`^[a-z][a-z0-9_-]{0,63}$`), the same one
# `openapp_note.MAX_SLUG` carries and for the same reason: nothing may be
# recorded that could not have arrived in a payload.
MAX_SLUG = 64

# THE LIST BOUND, and it is a REFUSAL rather than a truncation (see `normalise`).
# `enabled_apps` is an unbounded `text[]` server-side; the badge ships 8 apps
# (`apps-roster.json` production.apps) and the largest roster any badge has
# carried is 11 (`device`). 32 is roughly 3x the largest real payload, so a list
# past it did not come from a console configuring THIS fleet.
MAX_APPS = 32

# THE PRE-DECODE BOUND. A full 32-slug payload is 32 * (64 + 3) bytes of quoted,
# comma-separated names plus the schema envelope -- about 2.2 KB -- so 4 KB is
# comfortably twice the largest legitimate file and still a single small read.
# Past the cap the reader answers "no gate" WITHOUT decoding, which is the point:
# the launcher must never spend an unbounded parse on the home-screen path.
MAX_BYTES = 4096

KEY_SCHEMA = "schema"
KEY_APPS = "apps"

# What `record_from_badge_row` did, so a caller can log or ack it.
UNCHANGED = "unchanged"
CLEARED = "cleared"
RECORDED = "recorded"

# The column name in the `read_own_badge` select list (`data_api.py`). Spelled
# once here so the seam is a constant rather than a literal in two lanes' files.
ROW_KEY = "enabled_apps"


def _valid_slug(value):
    """Exactly ``openapp_note.valid_slug``'s class: ``^[a-z][a-z0-9_-]{0,63}$``.

    Duplicated rather than imported -- see the module docstring's sibling-import
    rule -- and pinned against the original by
    ``badgelink/tests/test_enabled_apps.py``.
    """

    if not isinstance(value, str):
        return False
    if len(value) < 1 or len(value) > MAX_SLUG:
        return False
    if not ("a" <= value[0] <= "z"):
        return False
    for character in value:
        if not (("a" <= character <= "z") or ("0" <= character <= "9")
                or character == "-" or character == "_"):
            return False
    return True


def normalise(value):
    """The server's ``enabled_apps`` -> a tuple of usable slugs. Never raises.

    ``()`` means "nothing usable here", which every caller reads as NO GATE.
    That single answer covers the four fail-soft cases the owner named -- a
    ``null``, an empty array, a value that is not an array at all, and an array
    whose every entry is junk -- so no caller has to enumerate them.

    A MIXED array keeps its good entries and drops the rest: a console that
    ships one typo among eight real names must gate the seven it got right, not
    unlock the badge. The dropped entry is indistinguishable on the badge from a
    name for an app this badge does not carry, and both are ignored the same way.

    OVER `MAX_APPS` IS A REFUSAL, NOT A TRUNCATION. Keeping the first 32 of a
    longer list would gate every app past the cut on the strength of a payload
    this badge has already decided it does not understand; dropping the whole
    thing lands on the fail-soft side, where every other unparseable case lands.
    """

    if not isinstance(value, (list, tuple)):
        return ()
    if len(value) > MAX_APPS:
        return ()
    kept = []
    for name in value:
        if _valid_slug(name) and name not in kept:
            kept.append(name)
    return tuple(kept)


# THE NAMES A BACKEND PAYLOAD CAN NEVER REMOVE. Each is here because gating it
# would take away a way BACK rather than a feature, which is the owner's line:
# "never gate an app in a way that leaves the wearer with no way back".
#
# * `menu` is the launcher itself, and the owner named it explicitly. The pinned
#   scan already skips it when it builds tiles (`path != "menu"`), so keeping it
#   in the list changes nothing a wearer sees -- it makes gating the home screen
#   STRUCTURALLY impossible instead of incidentally impossible.
# * `nametag` is the name badge, and it is the one app reachable WITHOUT the grid:
#   the 1.5 s hold on any of five keys and the idle ladder both launch
#   `/system/apps/nametag` directly (`launcher/menu/ui.py` POSTER_APP). A payload
#   that removed its tile would leave a hardware gesture opening an app the grid
#   says is not there, which is the exact wearer confusion the disappear-vs-inert
#   ruling turns on.
# * `settings` is "a permanent 5th launcher tile" by owner ruling (2026-08-17,
#   badgelink/OWNER-DECISIONS #2) and it is the badge's ONLY local control
#   surface: brightness, sleep, and the network-status view whose whole job is to
#   tell a wearer that networking has stopped and to reboot. Gating it with a
#   payload that ARRIVED OVER THAT NETWORK is the one failure this feature can
#   cause and cannot undo.
#
# If the owner wants a smaller set, this tuple is the whole knob.
PROTECTED = ("menu", "nametag", "settings")


def gate(ordered, allowed, protected=None, tile=None):
    """The grid names that survive the gate, in the order they arrived.

    THIS IS THE CANONICAL ALGORITHM and the launcher carries a byte-different,
    behaviour-identical copy because it cannot import this file (module
    docstring). ``launcher/tests/test_app_gating.py`` runs both over one table.

    THREE RULES, each of them a fail-soft direction:

    1. **No allow-list is no gate.** ``()``/``None`` returns everything.
    2. **An allow-list that matches NO INSTALLED TILE is discarded.** It
       describes some other badge -- a fleet-wide list for a different lineup, or
       a list of typos -- and honouring it would leave the wearer a launcher
       holding only :data:`PROTECTED`. Fail-soft says all-enabled instead. This
       is also what makes "a payload disabling everything" safe from the other
       direction: ``[]`` normalises to ``()`` and rule 1 catches it, and
       ``["typo"]`` gets here and rule 2 catches it.
    3. **:data:`PROTECTED` names survive any list.** See its comment.

    ``tile`` ANSWERS "COULD THIS NAME BECOME A TILE", and it exists because rule
    2 counted NAMES until 2026-08-26. The launcher's scan throws two classes of
    name away -- ``menu``, which it skips by name, and any directory with no
    ``__init__.py``/``.mpy``, which is what an interrupted Deploy leaves -- so
    ``["menu"]`` against a half-copied tree matched, kept only names the scan
    rejects, and left an EMPTY GRID. That is not a blank screen: the pinned
    base's ``Apps.active`` is ``self.apps[self.active_index]`` and the first
    frame reads it, so it is an ``IndexError`` inside ``launch()`` -> reset ->
    boot -> the same note -> the same raise.

    ``None`` means "assume every name can become a tile", which is the only
    thing a caller with no filesystem can honestly say and is what keeps this
    function pure; the LAUNCHER always passes a real predicate
    (``launcher/menu/ui.py`` ``_gate_tile``).

    What this guarantees is that the GATE cannot reduce the grid to zero tiles.
    It does not promise a non-empty grid: a badge with nothing installed has an
    empty one, and no payload is involved in that.
    """

    ordered = list(ordered)
    if not allowed:
        return ordered
    if protected is None:
        protected = PROTECTED
    matched = False
    for name in ordered:
        if name in allowed and (tile is None or tile(name)):
            matched = True
            break
    if not matched:
        return ordered
    kept = []
    for name in ordered:
        if name in allowed or name in protected:
            kept.append(name)
    return kept


# ---------------------------------------------------------------------------
# The note: write, clear, read
# ---------------------------------------------------------------------------

def record(apps, path=None, open_fn=None, sync_fn=None, rename_fn=None):
    """Persist the allow-list. Atomic; raises on a filesystem failure.

    Raising is the honest answer for the caller to turn into a failed ack or a
    logged event: a gate that could not be written is a gate that is not in
    effect, and the launcher will keep the previous one.
    """

    apps = normalise(apps)
    if not apps:
        raise ValueError("enabled_apps: no usable slugs to record")
    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    record_dict = {KEY_SCHEMA: SCHEMA, KEY_APPS: list(apps)}
    temporary = path + ".tmp"
    with open_fn(temporary, "w") as output:
        output.write(json.dumps(record_dict))
        flush = getattr(output, "flush", None)
        if flush is not None:
            flush()
    sync = sync_fn if sync_fn is not None else getattr(os, "sync", None)
    if sync is not None:
        sync()
    (rename_fn or os.rename)(temporary, path)
    return apps


def clear(path=None, remove_fn=None, open_fn=None):
    """Remove the note, which IS the all-enabled state. Never raises.

    Absent already counts as cleared, and a delete that fails leaves the previous
    gate in place -- which is a stale gate rather than a broken badge, and the
    only direction available on a read-only or full filesystem.

    The ``.tmp`` is removed too: an interrupted :func:`record` can strand one,
    and nothing ever reads it. Only the PRIMARY's fate is reported.
    """

    path = path or DEFAULT_PATH
    if remove_fn is None:
        remove_fn = getattr(os, "remove", None)
    if remove_fn is None:
        return False
    removed = True
    for target in (path, path + ".tmp"):
        try:
            remove_fn(target)
        except OSError:
            # Already absent is the state we wanted; anything else (read-only,
            # EBUSY) is not, so ask the filesystem rather than the errno.
            if target == path:
                removed = not _present(path, open_fn)
        except Exception:                                    # noqa: BLE001
            if target == path:
                removed = False
    return removed


def _present(path, open_fn=None):
    """Whether the note is still there, THROUGH THE CALLER'S FILESYSTEM.

    ``open_fn`` and not the builtin, because ``openapp_note._present`` shipped
    the builtin once and it inverted that module's central rule for every
    non-device caller: with an injected filesystem a FAILED delete read as a
    successful one.
    """

    open_fn = open_fn or open
    try:
        with open_fn(path, "r"):
            return True
    except OSError:
        return False
    except Exception:                                        # noqa: BLE001
        return True


def read(path=None, open_fn=None):
    """The recorded allow-list, or ``()``. TOTAL: never raises, always legible.

    The launcher owns the copy that actually runs on the home screen; this one is
    the canonical parse the pin test compares it against, and the one the badge's
    own diagnostics read.
    """

    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    try:
        with open_fn(path, "r") as source:
            raw = source.read(MAX_BYTES + 1)
    except Exception:                                        # noqa: BLE001
        return ()
    return parse(raw)


def parse(raw):
    """Bytes/str on disk -> a tuple of slugs. TOTAL.

    Split out of :func:`read` so the pin test can feed both copies the same
    STRING and compare, without either side needing a filesystem.

    The one extra byte :func:`read` asks for is what proves the file was over
    :data:`MAX_BYTES` without allocating the rest of it.
    """

    try:
        if raw is None:
            return ()
        if len(raw) > MAX_BYTES:
            return ()
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get(KEY_SCHEMA) != SCHEMA:
            return ()
        return normalise(value.get(KEY_APPS))
    except Exception:                                        # noqa: BLE001
        return ()


# ---------------------------------------------------------------------------
# The seam the networking lane calls
# ---------------------------------------------------------------------------

def record_from_badge_row(row, path=None, **io):
    """Apply one ``read_own_badge`` result. Returns what it did. Never raises.

    ONE CALL, so the networking lane's side of this feature is a single lazy
    import and a single line wherever the profile read lands. The decision table
    is here rather than at the call site because it is the fail-soft contract:

    * the row is not a dict, or carries no ``enabled_apps`` key -> ``UNCHANGED``.
      **Absence of information is not permission to rewrite the wearer's grid.**
      The select list is a firmware constant, so the key is missing only when the
      read failed or the SERVER dropped the column, and neither is the console
      saying anything about this badge.
    * the value carries nothing usable (``null``, ``[]``, not an array, all junk,
      over :data:`MAX_APPS`) -> ``CLEARED``. This is the owner's fail-soft rule
      landing on disk: the file goes away and the launcher's cheapest path is the
      all-enabled one. The launcher ALSO refuses an empty list it finds in a file
      an older or newer badge wrote; two independent guards, both tested.
    * otherwise -> ``RECORDED``, and a write that fails is reported as
      ``UNCHANGED`` rather than raised, because a failed note must not fail the
      poll/profile cycle that carried it.
    """

    try:
        if not isinstance(row, dict) or ROW_KEY not in row:
            return UNCHANGED
        apps = normalise(row.get(ROW_KEY))
        if not apps:
            clear(path=path, remove_fn=io.get("remove_fn"),
                  open_fn=io.get("open_fn"))
            return CLEARED
        record(apps, path=path,
               open_fn=io.get("open_fn"), sync_fn=io.get("sync_fn"),
               rename_fn=io.get("rename_fn"))
        return RECORDED
    except Exception:                                        # noqa: BLE001
        return UNCHANGED
