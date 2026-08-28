"""The one-shot open-app note: a launch target that survives a reset.

WHY A DURABLE NOTE AT ALL. ``docs/tufty-architecture.md`` settles the badge's
control flow and it is not negotiable from here:

    app_to_launch = launch("/system/apps/menu")   # the menu returns a path
    if app_to_launch is not None:
        launch(app_to_launch)                      # SAME instance -- no reset
    reset()                                        # only now

**One boot buys one menu visit plus one app.** So a badge with an app open cannot
reach the launcher again in this boot at all -- the app's exit IS a reset. An
``open_app`` command that arrives while an app is open therefore has exactly two
honest options: lose it, or write it down. This module is writing it down.

THE DELETE IS THE PRECONDITION, NOT THE CLEANUP, and it is the whole safety
argument. ``launch()`` is ``os.chdir`` -> ``sys.path.insert`` ->
``__import__(path)``, and an exception inside it becomes a firmware modal that
RESETS the badge. A note that survived the launch it caused would give a badge
this loop:

    boot -> read note -> launch target -> target raises -> reset -> boot -> ...

which is a brick, not a bug. So :func:`consume` deletes the note FIRST and
returns the target ONLY if the delete succeeded. A read-only or full filesystem
therefore yields no target and no loop, and a corrupt note is removed rather than
re-read forever. Every other guard here (the roster check at apply time, the slug
class in the constraint) is a filter in front of that rule, never a replacement
for it.

MicroPython surface only: ``json`` and ``os``, no ``re``. The write is
temp -> flush -> os.sync -> rename, the device-wide save discipline.
"""

import json
import os


SCHEMA = 1
DEFAULT_PATH = "/state/badgelink-open-app.json"

# `/system/apps/<slug>`, which is what `launch()` takes and what the launcher's
# own grid is built from. One place spells it.
APPS_ROOT = "/system/apps"

# THE LAUNCHER IS NOT AN OPENABLE TARGET. `open_app {"app": "menu"}` looks
# harmless and is a footgun: returning the menu's own path from the menu's run
# makes `/system/main.py` launch a SECOND menu, and the app the wearer then picks
# is dropped on the floor because main.py dispatches only once. From inside an
# app, "go to the menu" is what HOME already does. So the verb refuses it.
MENU_SLUG = "menu"

# The constraint's slug class bound (`^[a-z][a-z0-9_-]{0,63}$`), so a note can
# never carry something longer than the payload that produced it.
MAX_SLUG = 64

# THE PRE-DECODE BOUND (CX-10 sub-claim 4). The note is
# ``{"schema": 1, "app": "<64 max>", "force": false}`` -- under 100 bytes -- so
# 1 KB is ten times the only file that belongs here. Past the cap `_read` answers
# ``None``, which `consume` already treats as "no note", and the delete-first rule
# still removes the file: an oversize note is discarded rather than honoured, and
# nothing about that ordering changes.
MAX_BYTES = 1024


def valid_slug(value):
    """Exactly ``badge_commands_open_app_payload_check``'s slug class.

    ``^[a-z][a-z0-9_-]{0,63}$`` -- ``scores.game``'s class, which is the
    NARROWER of the two in the schema, chosen so every value that can be queued
    can also be reported back in ``badge_state.active_app`` unchanged.
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


def app_path(slug):
    """``/system/apps/<slug>`` -- the argument ``launch()`` takes."""

    return APPS_ROOT + "/" + slug


def installed_apps(root=APPS_ROOT, listdir=None):
    """What is ACTUALLY on this badge, as a tuple of slugs.  Never raises.

    The device truth rather than ``apps-roster.json``: the roster says what the
    deploy wizard intends to install and an install deletes nothing, so a badge
    mid-migration disagrees with it in both directions.

    A FAILED LISTING IS AN EMPTY ROSTER, which makes every slug unknown and every
    ``open_app`` a failed ack. That direction is deliberate: an import that raises
    inside ``launch()`` resets the badge, so "I could not verify this slug" must
    never become "I will try it and see".
    """

    if listdir is None:
        listdir = getattr(os, "listdir", None)
    if listdir is None:
        return ()
    try:
        names = listdir(root)
    except OSError:
        return ()
    except Exception:
        return ()
    found = []
    for name in names:
        if valid_slug(name):
            found.append(name)
    found.sort()
    return tuple(found)


def current_app(getcwd=None):
    """The slug ``launch()`` chdir'd into, or ``None`` outside an app.

    ``launch()`` is ``os.chdir`` -> ``sys.path.insert`` -> ``__import__``, so the
    working directory IS the running app's directory -- for the menu too
    (``launcher/tests/test_build_menu.py`` pins ``os.chdir("/system/apps/menu")``
    in the generated menu). The apps that chdir for themselves
    (``schedule``, ``pet``, ``snake``, ``glyph2x``) all chdir to their OWN root,
    so the answer does not move.

    Read rather than tracked because there is nothing to track: this module runs
    inside ``/system/main.py``'s frame pump, which cannot see ``launch()``
    returning. ``sys.path[0]`` was the other candidate and is WRONG for the menu
    -- ``launcher/menu/ui.py`` records that the menu's own ``__init__`` inserts
    ``"/"`` after its directory, so ``sys.path[0]`` is ``"/"`` there.
    """

    if getcwd is None:
        getcwd = getattr(os, "getcwd", None)
    if getcwd is None:
        return None
    try:
        cwd = getcwd()
    except Exception:
        return None
    if not isinstance(cwd, str):
        return None
    prefix = APPS_ROOT + "/"
    if not cwd.startswith(prefix):
        return None
    slug = cwd[len(prefix):]
    if "/" in slug:
        slug = slug.split("/", 1)[0]
    return slug if valid_slug(slug) else None


def at_menu(getcwd=None):
    """Whether the LAUNCHER's frame loop is the one being pumped right now."""

    return current_app(getcwd) == MENU_SLUG


def write(slug, force=False, path=None, open_fn=None, sync_fn=None,
          rename_fn=None):
    """Persist the one-shot note.  Atomic; raises on a filesystem failure.

    The caller turns a raise into a ``failed`` ack, which is the honest answer:
    a note that could not be written is an open that will not happen.
    """

    if not valid_slug(slug):
        raise ValueError("open_app slug is not in the payload class")
    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    record = {"schema": SCHEMA, "app": slug, "force": bool(force)}
    temporary = path + ".tmp"
    with open_fn(temporary, "w") as output:
        output.write(json.dumps(record))
        flush = getattr(output, "flush", None)
        if flush is not None:
            flush()
    sync = sync_fn if sync_fn is not None else getattr(os, "sync", None)
    if sync is not None:
        sync()
    (rename_fn or os.rename)(temporary, path)
    return record


def _read(path, open_fn):
    try:
        with open_fn(path, "r") as source:
            raw = source.read(MAX_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_BYTES:
        # BOUNDED BEFORE THE DECODE (:data:`MAX_BYTES`). The one extra byte is
        # what proves the file was over the cap without allocating the rest.
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        return None
    slug = value.get("app")
    if not valid_slug(slug) or slug == MENU_SLUG:
        return None
    return {"app": slug, "force": value.get("force") is True}


def _remove(path, remove_fn, open_fn=None):
    """True when the note is provably gone.  Absent already counts."""

    if remove_fn is None:
        remove_fn = getattr(os, "remove", None)
    if remove_fn is None:
        return False
    try:
        remove_fn(path)
    except OSError:
        # Already absent is success; anything else (read-only, EBUSY) is not, and
        # the caller must then refuse the target rather than risk the loop.
        return not _present(path, open_fn)
    except Exception:
        return False
    return True


def _present(path, open_fn=None):
    """Whether the note is still there, THROUGH THE CALLER'S FILESYSTEM.

    Using the builtin `open` here instead of `open_fn` was a real inversion of
    this module's central rule: with an injected filesystem a FAILED delete read
    as a successful one, so `consume` returned the target -- the exact loop the
    delete-first rule exists to prevent, for every non-device caller.
    """

    open_fn = open_fn or open
    try:
        with open_fn(path, "r"):
            return True
    except OSError:
        return False
    except Exception:
        return True


def consume(path=None, open_fn=None, remove_fn=None):
    """The note, ONCE, or ``None``.  Deletes before it returns anything.

    Returns ``{"app": slug, "force": bool}`` or ``None``. See the module
    docstring: the delete is the precondition. A note that cannot be deleted is
    not honoured, because the alternative is a reset loop on a badge nobody can
    reach.
    """

    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    target = _read(path, open_fn)
    removed = _remove(path, remove_fn, open_fn)
    # A leftover ".tmp" from an interrupted write is dead weight; a failure to
    # remove it is not interesting because it is never read.
    try:
        _remove(path + ".tmp", remove_fn, open_fn)
    except Exception:
        pass
    if not removed:
        return None
    return target
