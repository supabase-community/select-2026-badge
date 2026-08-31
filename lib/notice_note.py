"""One temporary fleet notice, handed from BadgeLink to Nametag.

The record is separate from ``openapp_note`` because the two files have
different consumers: the launcher consumes the app target during boot, while
Nametag consumes the text only after it owns the panel.  Both use the same
delete-before-honour rule.  If a notice cannot be deleted, displaying it would
turn every later Nametag visit into a replay, so :func:`consume` returns
``None`` instead.

Only printable ASCII is accepted.  The badge's ROM face silently omits glyphs
outside that measured repertoire; accepting arbitrary Unicode would therefore
acknowledge messages that some badges cannot display.
"""

import json
import os


SCHEMA = 1
DEFAULT_PATH = "/state/badgelink-notice.json"
MIN_DURATION_S = 5
MAX_DURATION_S = 60
MAX_TEXT = 64

# The largest valid record is under 130 bytes.  Reading one extra byte against
# a 512-byte ceiling rejects damaged or unrelated files before JSON allocates
# from an unbounded input on the badge's small heap.
MAX_BYTES = 512


def parse(payload):
    """Return the canonical notice or raise ``ValueError``.

    Surrounding ordinary spaces are normalized away.  Tabs/newlines are
    rejected before trimming because the wire contract is printable ASCII,
    not merely "text that becomes printable after cleanup".
    """

    if not isinstance(payload, dict):
        raise ValueError("show_notice payload must be an object")
    keys = set(payload.keys())
    if keys != set(("text", "duration_s")):
        raise ValueError("show_notice requires exactly text and duration_s")
    text = payload.get("text")
    if not isinstance(text, str):
        raise ValueError("show_notice text must be a string")
    for character in text:
        codepoint = ord(character)
        if codepoint < 0x20 or codepoint > 0x7E:
            raise ValueError("show_notice text must be printable ASCII")
    text = text.strip()
    if not text or len(text) > MAX_TEXT:
        raise ValueError("show_notice text must contain 1..64 characters")
    duration_s = payload.get("duration_s")
    # JSON booleans decode as bool, and bool is an int subclass on both CPython
    # and MicroPython.  Without the explicit exclusion, true becomes a one-
    # second notice even though the minimum is five.
    if (not isinstance(duration_s, int) or isinstance(duration_s, bool)
            or duration_s < MIN_DURATION_S or duration_s > MAX_DURATION_S):
        raise ValueError("show_notice duration_s must be an integer from 5 to 60")
    return {"text": text, "duration_s": duration_s}


def write(payload, path=None, open_fn=None, sync_fn=None, rename_fn=None):
    """Validate and atomically replace the pending notice."""

    notice = parse(payload)
    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    record = {
        "schema": SCHEMA,
        "text": notice["text"],
        "duration_s": notice["duration_s"],
    }
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
    return notice


def _read(path, open_fn):
    try:
        with open_fn(path, "r") as source:
            raw = source.read(MAX_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_BYTES:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        return None
    if set(value.keys()) != set(("schema", "text", "duration_s")):
        return None
    try:
        return parse({"text": value["text"],
                      "duration_s": value["duration_s"]})
    except (ValueError, TypeError):
        return None


def _present(path, open_fn):
    try:
        with open_fn(path, "r"):
            return True
    except OSError:
        return False
    except Exception:
        return True


def _remove(path, remove_fn, open_fn):
    remove_fn = remove_fn or getattr(os, "remove", None)
    if remove_fn is None:
        return False
    try:
        remove_fn(path)
    except OSError:
        # An already-absent note is gone; a read-only/full filesystem is not.
        return not _present(path, open_fn)
    except Exception:
        return False
    return True


def discard(path=None, open_fn=None, remove_fn=None):
    """Best-effort removal used when forcing Nametag could not be armed."""

    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    removed = _remove(path, remove_fn, open_fn)
    try:
        _remove(path + ".tmp", remove_fn, open_fn)
    except Exception:
        pass
    return removed


def consume(path=None, open_fn=None, remove_fn=None):
    """Return one validated notice only after its file is provably gone."""

    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    notice = _read(path, open_fn)
    removed = discard(path, open_fn, remove_fn)
    if not removed:
        return None
    return notice
