"""Atomic persistence for the badge store: read, load, save, the backup.

Only `json`, `os` and the pure model are imported, so the whole module runs in
the CPython fast lane against a temporary directory.

THE WRITE SEQUENCE IS temp -> flush -> sync -> rename, which is the only
sequence that survives power loss on LittleFS: the rename is the atom, so a kill
at any earlier point leaves the previous good file untouched.

THIS IS `identity_store` WITH THE KEEPSAKE TAKEN OUT, and the subtraction is
deliberate rather than lazy.  `identity` has one badge, so ERASE is unrecoverable
and needs a write-once `.prev` slot to undo from.  This app's argument used to be
"it has five"; since 2026-08-24 it has ONE TOO, and the subtraction survived the
loss of its first reason because the second one was always the load-bearing half:
the destructive press is confirmed on its own screen (B7), with B inert, and THE
CONFIRMATION IS THE PROTECTION.  A keepsake no screen can reach would be a fourth
file, a fourth failure mode and a fourth thing to reason about, in exchange for
an undo nobody can perform -- and it would now be actively wrong, because a
wearer who resets their card is asking for it to be gone.  What is kept is the
part that has actually caught real corruption: the milestone `.bak` and the
`.bad` diagnostic copy.

ONE MODULE OWNS THE PATH, and every entry point resolves `path=None` HERE at
call time rather than as a default argument -- a default binds at DEFINITION
time, so an override would be silently ignored, which is exactly the path-drift
bug `namebadge/tests/app_harness.py:335` had to work around with
`model.save.__defaults__`.
"""

import json
import os

import card_model as model


STATE_PATH = "/state/badgecard.json"
BACKUP_SUFFIX = ".bak"
BAD_SUFFIX = ".bad"

# How much of an unparseable file is kept for diagnosis.  Enough to see the
# shape and the truncation point; small enough that a runaway writer cannot fill
# the 1 MB volume with its own wreckage.
BAD_BYTES = 512


def ensure_parent(path=None):
    path = path or STATE_PATH
    # A BARE FILENAME HAS NO PARENT.  `"f.json".rsplit("/", 1)[0]` is `"f.json"`
    # itself, so the naive form would `mkdir` a directory named after the file
    # and every write to it would then fail with EISDIR.  Device paths are
    # absolute so nothing shipped reaches it, but a host test using a relative
    # path would, and the failure would look like a corrupt save.
    if "/" not in path:
        return
    parent = path.rsplit("/", 1)[0]
    if not parent:
        return
    try:
        os.mkdir(parent)
    except OSError:
        pass


def _read_text(path):
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
    """A best-effort write to a SIDECAR slot.

    Swallowing OSError is right here and wrong for the primary: failing to keep
    a diagnostic copy must not fail the operation that was actually asked for,
    while failing to write the badge itself must be visible to the caller.
    """
    try:
        _write_atomic(path, text)
    except OSError:
        pass


def read(path=None):
    """Load one file and RAISE on anything wrong.  The honest reader.

    THE BUG THIS SHAPE EXISTS TO PREVENT, recorded in `identity_store` and
    inherited: `profile.undo_reset` restored its backup by calling the FORGIVING
    loader, which swallows every failure and returns factory defaults.  With no
    backup on disk it read defaults, wrote them over the wearer's real badge,
    failed the subsequent remove, caught that, and returned None -- and the
    caller reads None as "nothing to undo" and prints NO UNDO.  The badge was
    already gone, and the return value lied about the one thing it existed to
    report.

    So: exactly one function falls back, it is `load`, and it is only ever
    called on the boot path.

    Raises OSError when the file is not there and ValueError when its bytes are
    not a JSON object.  A file that IS a JSON object always returns a state,
    because `repair` is total.
    """
    path = path or STATE_PATH
    value = json.loads(_read_text(path))
    if not isinstance(value, dict):
        # A JSON array or a bare number parses fine and is still not a store.
        raise ValueError("not a JSON object: %s" % path)
    return model.repair(value)


def _parse(raw, path, keep_bad=True):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        if keep_bad:
            _copy(path + BAD_SUFFIX, raw[:BAD_BYTES])
        return None, "corrupt"
    if not isinstance(value, dict):
        if keep_bad:
            _copy(path + BAD_SUFFIX, raw[:BAD_BYTES])
        return None, "corrupt"
    if value.get("schema") != model.SCHEMA:
        # Readable, and from a version we do not know -- older, newer, or hand
        # written.  `repair` coerces it into something representable and carries
        # the keys it did not recognise, so a badge configured on a newer build
        # loses the FEATURES on a downgrade and not the DATA.  Rejecting it
        # would hand the wearer a factory badge for having run an update.
        return model.repair(value), "migrated"
    return model.repair(value), "loaded"


def load(path=None):
    """Returns `(state, status)`.  THE ONLY FORGIVING ENTRY POINT.

    `status` is one of loaded / migrated / corrupt / missing / backup.  A parse
    failure copies the offending bytes to `<path>.bad` FIRST, so a field failure
    becomes a diagnosable artefact rather than a shrug, then falls through to
    the milestone backup before giving up and starting a fresh store.

    A badge with a corrupt save must still show a badge, which is why this
    swallows.  That is a BOOT-PATH judgement and it does not generalise.
    """
    path = path or STATE_PATH
    try:
        raw = _read_text(path)
    except OSError:
        raw = None

    if raw is not None:
        state, status = _parse(raw, path)
        if state is not None:
            return state, status

    try:
        backup = _read_text(path + BACKUP_SUFFIX)
    except OSError:
        backup = None
    if backup is not None:
        state, _status = _parse(backup, path, keep_bad=False)
        if state is not None:
            return state, "backup"

    if raw is None:
        return model.new_state(), "missing"
    return model.new_state(), "corrupt"


def save(state, path=None, milestone=False):
    """Write the state atomically.  Milestones additionally refresh the backup.

    What counts as a milestone is the caller's business, but the rule that makes
    `.bak` worth having is that a milestone is a COMMIT and never a navigation
    step (B6): three hundred scroll presses must not become three hundred backup
    writes on a shared 1 MB volume.
    """
    path = path or STATE_PATH
    text = json.dumps(state)
    _write_atomic(path, text)
    if milestone:
        _copy(path + BACKUP_SUFFIX, text)
    return state
