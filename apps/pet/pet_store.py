"""Atomic Pet persistence: load, repair, migrate, save, milestone backup.

Only `json` and `os` are imported, so the whole module runs in the CPython fast
lane against a temporary directory.

The write sequence is temp -> flush -> sync -> rename, which is the only
sequence that survives power loss on LittleFS: the rename is the atom, so a kill
at any earlier point leaves the previous good file untouched.
"""

import json
import os

import pet_model as model
from pet_tuning import RESTORE_S, STAGE_AGE_S


# One module owns the path.  Every entry point takes `path=None` and resolves it
# HERE at call time rather than as a default argument, because a default binds at
# definition time: an override would then be silently ignored, which is exactly
# the class of path-drift bug that has bitten this platform before.
STATE_PATH = "/state/pet.json"
BACKUP_SUFFIX = ".bak"
BAD_SUFFIX = ".bad"
V1_SUFFIX = ".v1"
# The ERASE keepsake, and a DIFFERENT slot from the torn-write backup on purpose.
# `.bak` is refreshed by every milestone, so a backup written there survives
# exactly one further button press - which made the confirmation screen's promise
# ("A BACKUP IS KEPT") a lie by the time anyone could act on it.  Nothing but
# `save(..., previous=True)` ever writes `.prev`, and no automatic recovery path
# reads it: discarding a creature is deliberate, so restoring one must be too.
PREV_SUFFIX = ".prev"


def ensure_parent(path=None):
    path = path or STATE_PATH
    parent = path.rsplit("/", 1)[0]
    if not parent:
        return
    try:
        os.mkdir(parent)
    except OSError:
        pass


def _read(path):
    with open(path, "r") as source:
        return source.read()


def _write_atomic(path, text):
    ensure_parent(path)
    temporary = path + ".tmp"
    with open(temporary, "w") as output:
        output.write(text)
        output.flush()
    sync = getattr(os, "sync", None)
    if sync is not None:
        sync()
    os.rename(temporary, path)


def _copy(path, text):
    try:
        _write_atomic(path, text)
    except OSError:
        pass


def load(now_s=0, path=None):
    """Returns (state, status).

    status is one of loaded / migrated / corrupt / missing / backup.  A parse
    failure copies the offending bytes to `<path>.bad` first, so a field failure
    becomes a diagnosable artefact rather than a shrug, and then falls through to
    the milestone backup before giving up and starting a fresh pet.
    """
    path = path or STATE_PATH
    raw = None
    try:
        raw = _read(path)
    except OSError:
        raw = None

    if raw is not None:
        state, status = _parse(raw, now_s, path)
        if state is not None:
            return state, status

    try:
        backup = _read(path + BACKUP_SUFFIX)
    except OSError:
        backup = None
    if backup is not None:
        state, _status = _parse(backup, now_s, path, keep_bad=False)
        if state is not None:
            return state, "backup"

    if raw is None:
        return model.new_state(model.MAX, now_s), "missing"
    return model.new_state(model.MAX, now_s), "corrupt"


def _parse(raw, now_s, path, keep_bad=True):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        if keep_bad:
            _copy(path + BAD_SUFFIX, raw[:512])
        return None, "corrupt"
    if not isinstance(value, dict):
        if keep_bad:
            _copy(path + BAD_SUFFIX, raw[:512])
        return None, "corrupt"
    schema = value.get("schema")
    if schema == 1:
        # Keep the untouched v1 bytes once: migration is a one-way door on a real
        # save, and the backup slot will already be v2 by the time anyone notices.
        _copy(path + V1_SUFFIX, raw)
        return migrate_v1(value, now_s), "migrated"
    if schema != model.SCHEMA:
        # Readable but from a version we do not know.  Repair coerces it into
        # something representable rather than throwing the pet away.
        return model.repair(value, now_s), "migrated"
    return model.repair(value, now_s), "loaded"


def migrate_v1(value, now_s):
    """Schema 1 was {schema, health, last_seen, state, restore_started, total_feeds}.

    Health carries across as tenths.  DATA and MOOD are seeded FROM health rather
    than from full, so a v1 pet that was struggling does not arrive suspiciously
    well fed, and a healthy one does not arrive starving and immediately fire two
    stressors on its first open.  Stage is seeded at DEV rather than EGG: an owner
    who has been playing the mock must not be demoted to an egg by an update.
    """
    state = model.new_state(model.MAX, now_s, fast=0)
    health = model._int(_number_tenths(value.get("health")), model.MAX)
    state["health"] = model._clamp(health, 0, model.MAX)
    state["data"] = state["health"]
    state["mood"] = state["health"]
    state["last_seen"] = model._int(value.get("last_seen"), now_s)
    state["total_feeds"] = model._clamp(model._int(value.get("total_feeds"), 0), 0, 999999999)
    name = value.get("state")
    state["state"] = name if name in model.VALID_STATES else model.ALIVE
    state["stage"] = 2
    state["age_s"] = STAGE_AGE_S[2]
    if state["state"] == model.RESTORING:
        started = model._int(value.get("restore_started"), 0)
        now = model._int(now_s, 0)
        elapsed = now - started
        if started <= 0 or elapsed < 0 or elapsed > RESTORE_S:
            # Any doubt about the clock buys a full fresh wait, never zero.
            state["restore_left_s"] = RESTORE_S
        else:
            state["restore_left_s"] = RESTORE_S - elapsed
    return model._settle(state)


def _number_tenths(value):
    """v1 stored health as a float 0..100; v2 stores tenths 0..1000."""
    try:
        return int(round(float(value) * 10))
    except (TypeError, ValueError, OverflowError):
        return None


def save(state, path=None, milestone=False, previous=False):
    """Write the state atomically.  Milestones additionally refresh the backup.

    `previous=True` writes ONLY the `.prev` keepsake slot and never touches the
    primary or the backup: the creature being handed to it is the one that is
    about to be replaced, so writing it to the primary would just be a flash
    write that the next line overwrites.
    """
    path = path or STATE_PATH
    text = json.dumps(state)
    if previous:
        _copy(path + PREV_SUFFIX, text)
        return state
    _write_atomic(path, text)
    if milestone:
        _copy(path + BACKUP_SUFFIX, text)
    return state
