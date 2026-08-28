"""Atomic physical-holder preference for BadgeLink network access.

Pairing answers *whose* badge this is.  This file answers the separate local
question *may this badge use its radio for BadgeLink?*  Anyone holding the
badge may change it from Settings, and neither value edits or removes the
durable pair state in ``/badgelink_state.json``.

Missing, corrupt and old records fail closed to OFF.  The write follows the
device-wide temp -> flush -> sync -> rename rule so a power cut cannot turn an
incomplete record into an enabled radio.

THE SECOND SWITCH, AND WHY IT FAILS THE OTHER WAY (P6-L3, 2026-08-21).  The same
record also carries the PUSH preference: whether this badge may use the Realtime
doorbell on top of polling.  Two deliberate asymmetries:

* it lives in the SAME file and the SAME atomic write, because two files would
  mean two writes and a window where a power cut leaves the pair disagreeing;
* it defaults **ON** where the radio switch defaults OFF, and the schema number
  is NOT bumped for it.  Absent means ON because push cannot start a radio the
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


def _directory(path):
    if "/" not in path:
        return None
    head = path.rsplit("/", 1)[0]
    return head or None


def load_record(path=DEFAULT_PATH, open_fn=open):
    """The stored record, or ``None`` when there is nothing usable to read.

    ONE CALL ANSWERS BOTH SWITCHES, and that is why it is the entry point
    `network_runtime` uses: `load` and `load_push` each call this, so a
    constructor that asked both questions opened and DECODED the same file twice
    before the launcher's first frame (CX-10 sub-claim 1).

    BOUNDED BEFORE THE DECODE (:data:`MAX_BYTES`): ``read(MAX_BYTES + 1)`` and
    the extra byte is how an over-cap file is refused without allocating it.
    """

    try:
        with open_fn(path, "r") as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        record = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return None
    return record


def enabled_from(record):
    """A loaded record -> the radio switch. Absent or invalid means OFF.

    Split out of :func:`load` so a caller that already holds the record can
    derive both switches from it. The two default the opposite ways ON PURPOSE
    (see the module note), so neither may be inferred from the other.
    """

    if record is None:
        return False
    value = record.get("enabled")
    return value if isinstance(value, bool) else False


def push_from(record):
    """A loaded record -> the push switch. Absent or invalid means ON."""

    if record is None:
        return PUSH_DEFAULT
    value = record.get("push")
    return value if isinstance(value, bool) else PUSH_DEFAULT


def load(path=DEFAULT_PATH, open_fn=open):
    """Return the stored boolean; absent or invalid means OFF."""

    return enabled_from(load_record(path, open_fn))


def load_push(path=DEFAULT_PATH, open_fn=open):
    """Whether push is allowed on this badge; absent or invalid means ON."""

    return push_from(load_record(path, open_fn))


def save_push(push, path=DEFAULT_PATH, open_fn=open, sync_fn=None,
              rename_fn=None, mkdir_fn=None):
    """Atomically store the PUSH preference, preserving the radio switch."""

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
