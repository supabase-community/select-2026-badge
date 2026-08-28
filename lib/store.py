"""Atomic durable store for BadgeLink's badge-side state (``/badgelink_state.json``).

Only the small, must-survive-reboot facts live here: the paired flag and owner
hint (from :func:`badgelink.pairstate.durable_state`), plus the two idempotency
high-waters the transport reconciles from — ``last_applied_command_id`` (so a
redelivered command is not re-applied) and ``desired_version``. Short-lived pair
and match codes are NEVER persisted; a reboot re-fetches desired state (transport
contract).

The write is atomic (temp + flush + ``os.sync`` + ``os.rename``), matching the
device-wide save discipline (docs/badge-button-rules B6; supervisor runtime).
Loading is fail-soft: a missing or corrupt file yields defaults so a bad write
can never brick the badge — it degrades to unpaired, and re-pairing restores it.
"""

import json
import os


SCHEMA = 1
DEFAULT_PATH = "/badgelink_state.json"
_MAX_HINT = 64
_MAX_COMMAND_ID = 64


class StoreError(Exception):
    pass


def default_state():
    return {
        "schema": SCHEMA,
        "paired": False,
        "owner_hint": "",
        "last_applied_command_id": "",
        "desired_version": 0,
    }


def _str(value, name, maximum):
    if not isinstance(value, str) or len(value) > maximum:
        raise StoreError("{} must be a string within {} chars".format(name, maximum))
    return value


def normalise(state):
    """Validate + coerce a state dict into the exact stored shape, or raise."""
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise StoreError("state schema is invalid")
    paired = state.get("paired", False)
    if not isinstance(paired, bool):
        raise StoreError("paired must be boolean")
    version = state.get("desired_version", 0)
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise StoreError("desired_version must be a non-negative integer")
    return {
        "schema": SCHEMA,
        "paired": paired,
        # An unpaired badge carries no owner hint.
        "owner_hint": _str(state.get("owner_hint", ""), "owner_hint", _MAX_HINT) if paired else "",
        "last_applied_command_id": _str(
            state.get("last_applied_command_id", ""),
            "last_applied_command_id",
            _MAX_COMMAND_ID,
        ),
        "desired_version": version,
    }


def load(path=DEFAULT_PATH, open_fn=open):
    """Return the stored state, or defaults if the file is missing or corrupt."""
    try:
        with open_fn(path, "r") as source:
            raw = json.load(source)
    except OSError:
        return default_state()
    except ValueError:
        # Corrupt JSON: fail soft to defaults rather than crash the boot.
        return default_state()
    try:
        return normalise(raw)
    except StoreError:
        return default_state()


def save(path, state, open_fn=open, sync_fn=None, rename_fn=None):
    """Atomically persist ``state``. Never leaves a partial file at ``path``."""
    record = normalise(state)
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
