"""Small atomic exactly-once ledger for commands applied by the boot pump.

The server normally prevents redelivery after an ack.  The local ledger closes
the harder window: an effect landed, then HOME/RESET happened before its ack.
The remembered ack is queued again after reboot and the physical effect is not
repeated.  Thirty-two entries cover two full 16-command poll batches.
"""

import json
import os


SCHEMA = 1
LIMIT = 32
DEFAULT_PATH = "/state/badgelink-command-ledger.json"
_MAX_ID = 64
_MAX_RESULT_TEXT = 512

# THE PRE-DECODE BOUND (CX-10 sub-claim 4). LIMIT entries, each a 64-character id
# plus a status plus a result whose text fields are capped at _MAX_RESULT_TEXT,
# is ~22 KB, so 64 KB is ~3x the largest thing `save` can write. Past the cap the
# load answers `default_state()` -- the same answer a corrupt ledger already gets,
# and the same cost: at worst one replayed physical effect, which is CX-7's
# documented residual and not a new failure mode.
MAX_BYTES = 65536


def default_state():
    return {"schema": SCHEMA, "entries": []}


def _entry(value):
    if not isinstance(value, dict):
        raise ValueError("ledger entry must be an object")
    command_id = value.get("id")
    status = value.get("status")
    result = value.get("result")
    if not isinstance(command_id, str) or not command_id or len(command_id) > _MAX_ID:
        raise ValueError("ledger command id is invalid")
    if status not in ("applied", "failed"):
        raise ValueError("ledger status is invalid")
    if not isinstance(result, dict):
        raise ValueError("ledger result must be an object")
    if len(json.dumps(result)) > _MAX_RESULT_TEXT:
        raise ValueError("ledger result is too large")
    return {"id": command_id, "status": status, "result": result}


def normalise(value):
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("ledger schema is invalid")
    entries = value.get("entries")
    if not isinstance(entries, list) or len(entries) > LIMIT:
        raise ValueError("ledger entries are invalid")
    seen = set()
    result = []
    for raw in entries:
        item = _entry(raw)
        if item["id"] in seen:
            raise ValueError("ledger command ids must be unique")
        seen.add(item["id"])
        result.append(item)
    return {"schema": SCHEMA, "entries": result}


def load(path=DEFAULT_PATH, open_fn=open):
    """The stored ledger, or defaults.  BOUNDED before the decode; never raises."""

    try:
        with open_fn(path, "r") as source:
            text = source.read(MAX_BYTES + 1)
        if len(text) > MAX_BYTES:
            return default_state()
        return normalise(json.loads(text))
    except (OSError, ValueError, TypeError):
        return default_state()


def find(state, command_id):
    for entry in state.get("entries", ()):
        if entry.get("id") == command_id:
            return entry
    return None


def remember(state, ack):
    record = normalise(state)
    item = _entry(ack)
    entries = [entry for entry in record["entries"] if entry["id"] != item["id"]]
    entries.append(item)
    record["entries"] = entries[-LIMIT:]
    return record


def save(state, path=DEFAULT_PATH, open_fn=open, sync_fn=None,
         rename_fn=None, mkdir_fn=None):
    record = normalise(state)
    directory = path.rsplit("/", 1)[0] if "/" in path else None
    if directory:
        try:
            (mkdir_fn or os.mkdir)(directory)
        except OSError:
            pass
    temporary = path + ".tmp"
    with open_fn(temporary, "w") as output:
        json.dump(record, output)
        flush = getattr(output, "flush", None)
        if flush is not None:
            flush()
    sync = sync_fn if sync_fn is not None else getattr(os, "sync", None)
    if sync is not None:
        sync()
    (rename_fn or os.rename)(temporary, path)
    return record
