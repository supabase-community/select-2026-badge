"""The wearer's brightness, in the ONE file every reader already shares.

THE STORE IS `/state/badgecard.json`'s ROOT `brightness` KEY, AND A SECOND ONE
MUST NEVER BE CREATED.  Four things read that key today -- the launcher
(`launcher/menu/ui.BRIGHTNESS_PATH`), `poster` (`badge_state.DEVICE_KEYS`),
`badgecard`'s own `panel.restore()`, and this tile -- and a wearer who set the
level here has to find it applied on all four.  There is no other way for that
to happen: **leaving an app is `machine.reset()`** (`supervisor/system/
stock-v3.0.1-main.py` takes one path out of `launch()` and resets when it
returns), so nothing at all survives in RAM between two apps, and the file is
the whole handover.  A settings-owned second file would give the launcher one
answer and the badge another, which is the exact drift `docs/design/
idle-and-off.md` §5.4 records as defect 2: a stored `55.5` gave the launcher 55
and the poster 80, and it read on the panel as a brightness JUMP.

WHY THIS IS A WRITER AND NOT AN IMPORT OF `card_store`.  `badgecard` OWNS the
format -- `card_model.SCHEMA`, `card_store.STATE_PATH` and the total
`card_model.repair` are canonical -- and this module is a writer that AGREES
with them.  Importing the real thing would put 23 KB of another app's code plus
a 106-row face table into this tile, for one integer;
`badgelink/badge/badgelink/badgecard_state.py` made the same call for the same
reason and its docstring has the full argument.  What keeps the two honest is a
test, not a comment: `settings/tests/test_settings_brightness.py` imports the
real `card_store`/`card_model` and pins every literal below against them.

MINIMAL KNOWLEDGE, MAXIMAL CARRY.  :func:`write` parses the file, changes ONE
root key and writes every other byte back verbatim.  It does not repair,
normalise, migrate or drop anything it does not recognise, because
`card_model.repair` is total and idempotent and runs at open.  A badge
configured by a NEWER `badgecard` keeps its new fields through a brightness
change.

IT REFUSES RATHER THAN OVERWRITE, and that is the one non-obvious rule.
`card_store.load` falls back to `<path>.bak` when the primary is corrupt or
missing.  A writer that answered a corrupt primary by writing a fresh little
file would make `badgecard` load THAT and never consult the backup -- so a
brightness press would silently destroy up to five saved badges.  A corrupt
primary is therefore refused, a missing primary is refused when a backup exists,
and only "no primary and no backup" (a badge whose badgecard has never been
opened) gets a fresh file.

THE `.bak` MILESTONE IS NEVER REFRESHED.  It is `badgecard`'s slot for a wearer
COMMIT of a BADGE (button rule B6), and copying our file over it would put the
one thing we cannot verify -- five badges we merely carried -- into the slot that
exists to recover them.

MicroPython surface only: `json` and `os`.  The write is temp -> flush ->
os.sync -> rename, which is `card_store._write_atomic`'s sequence and the only
one that survives power loss on LittleFS: the rename is the atom.
"""

import json
import os

import backlight


# `badgecard`'s literals.  Pinned against the real modules by
# `settings/tests/test_settings_brightness.py`; do not change one here to make a
# test pass, change `badgecard` and let the pin tell you.
STATE_PATH = "/state/badgecard.json"      # card_store.STATE_PATH
BACKUP_SUFFIX = ".bak"                    # card_store.BACKUP_SUFFIX
KEY = "brightness"                        # card_model.new_state()'s root key


def _exists(path, open_fn):
    try:
        handle = open_fn(path, "r")
    except OSError:
        return False
    handle.close()
    return True


def read(path=None, open_fn=None):
    """The wearer's level, clamped onto the ladder.  TOTAL: never raises.

    A missing file, a directory, unparseable bytes, a JSON array, a level of
    `"80"` or of `True` -- every one of them is `backlight.DEFAULT`.  The
    alternative is an exception on the boot path of an app, and an import-time
    or launch-time raise reaches `fatal_error`, which resets the badge.  This is
    `launcher/menu/ui._read_brightness` in another app, deliberately the same
    shape: the two are the only readers that have to survive a hostile file with
    no screen to report on.
    """
    path = path or STATE_PATH
    open_fn = open_fn or open
    try:
        with open_fn(path, "r") as source:
            value = json.loads(source.read())
        if isinstance(value, dict):
            return backlight.clamp(value.get(KEY, backlight.DEFAULT))
    except Exception:                                        # noqa: BLE001
        pass
    return backlight.DEFAULT


def write(percent, path=None, open_fn=None, sync_fn=None, rename_fn=None):
    """Store one level.  Returns the level written, or None when it refused.

    NOT TOTAL IN THE SAME WAY `read` IS, and the asymmetry is the point: a read
    that fails can substitute the factory level and be nearly right, while a
    write that fails must not invent a file.  The two refusals are the corrupt
    and the missing-with-a-backup primary, both of which mean the wearer's
    badges are sitting in `.bak` one careless write from gone.

    An `OSError` from the write itself propagates to the caller, which is the
    seam, which prints it and carries on: the panel has already moved, so a
    failed write costs the wearer persistence and not the level they are
    looking at.
    """
    path = path or STATE_PATH
    open_fn = open_fn or open
    level = backlight.clamp(percent)
    try:
        with open_fn(path, "r") as source:
            raw = source.read()
    except OSError:
        if _exists(path + BACKUP_SUFFIX, open_fn):
            return None
        # A badge whose `badgecard` has never been opened. ONE KEY IS ENOUGH:
        # `card_model.repair` is total, so it completes this into a whole state
        # at open -- schema, one default badge and the home record included --
        # and a writer that guessed those fields here would be a second
        # definition of a format it does not own.
        raw = None
    if raw is None:
        state = {}
    else:
        try:
            state = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(state, dict):
            return None
    state[KEY] = level
    text = json.dumps(state)
    temporary = path + ".tmp"
    with open_fn(temporary, "w") as output:
        output.write(text)
        flush = getattr(output, "flush", None)
        if flush is not None:
            flush()
    sync = sync_fn if sync_fn is not None else getattr(os, "sync", None)
    if sync is not None:
        sync()
    (rename_fn or os.rename)(temporary, path)
    return level
