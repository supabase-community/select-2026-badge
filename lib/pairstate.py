"""Pure BadgeLink pairing state machine.

`advance` performs no I/O and never mutates its arguments. The store layer persists
only `durable_state`; short-lived pair and match codes remain in memory.
"""


SCHEMA = 1
UNPAIRED = "unpaired"
STARTING = "starting"
CODE = "code"
CONFIRM = "confirm"
ACKING = "acking"
PAIRED = "paired"
UNPAIR_CONFIRM = "unpair_confirm"
UNPAIRING = "unpairing"

PHASES = {
    UNPAIRED,
    STARTING,
    CODE,
    CONFIRM,
    ACKING,
    PAIRED,
    UNPAIR_CONFIRM,
    UNPAIRING,
}

PAIR_CODE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
MATCH_CODE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MAX_OWNER_HINT = 64
MAX_ERROR = 96

EVENT_TYPES = {
    "pair_pressed",
    "pair_started",
    "pair_start_failed",
    "claim_received",
    "back",
    "decline",
    "accept",
    "ack_succeeded",
    "ack_failed",
    "retry",
    "open_unpair",
    "keep",
    "unpair",
    "unpair_succeeded",
    "unpair_failed",
    "remote_unpaired",
    "revoked",
}


def _text(value, name, maximum, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError("{} must be text".format(name))
    if (not allow_empty and not value) or len(value) > maximum:
        raise ValueError("{} length is invalid".format(name))
    return value


def _error(value):
    if value is None:
        return ""
    return _text(value, "error", MAX_ERROR, allow_empty=True)


def _pair_code(value):
    value = _text(value, "pair code", 8)
    if len(value) != 8 or any(item not in PAIR_CODE_CHARS for item in value):
        raise ValueError("pair code must be eight base32 characters")
    return value


def _match_code(value):
    value = _text(value, "match code", 6)
    if len(value) != 6 or any(item not in MATCH_CODE_CHARS for item in value):
        raise ValueError("match code must be six uppercase characters")
    return value


def _claim_id(value):
    return _text(value, "claim ID", 64)


def _remaining(value):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("expiry must be a positive integer of milliseconds")
    return value


def new_state(paired=False, owner_hint=""):
    if not isinstance(paired, bool):
        raise ValueError("paired must be boolean")
    owner_hint = _text(owner_hint, "owner hint", MAX_OWNER_HINT, allow_empty=True)
    return {
        "schema": SCHEMA,
        "phase": PAIRED if paired else UNPAIRED,
        "paired": paired,
        "owner_hint": owner_hint if paired else "",
        "code": "",
        "remaining_ms": 0,
        "claim_id": "",
        "match_code": "",
        "last_error": "",
        "revoked": False,
    }


def _copy_state(state):
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise ValueError("pair state schema is invalid")
    phase = state.get("phase")
    if phase not in PHASES:
        raise ValueError("pair state phase is invalid")
    paired = state.get("paired")
    if not isinstance(paired, bool):
        raise ValueError("pair state paired flag is invalid")
    remaining_ms = state.get("remaining_ms", 0)
    if not isinstance(remaining_ms, int) or isinstance(remaining_ms, bool) or remaining_ms < 0:
        raise ValueError("pair state countdown is invalid")
    revoked = state.get("revoked", False)
    if not isinstance(revoked, bool):
        raise ValueError("pair state revoked flag is invalid")
    return {
        "schema": SCHEMA,
        "phase": phase,
        "paired": paired,
        "owner_hint": _text(
            state.get("owner_hint", ""),
            "owner hint",
            MAX_OWNER_HINT,
            allow_empty=True,
        ),
        "code": _text(state.get("code", ""), "pair code", 8, allow_empty=True),
        "remaining_ms": remaining_ms,
        "claim_id": _text(state.get("claim_id", ""), "claim ID", 64, allow_empty=True),
        "match_code": _text(
            state.get("match_code", ""),
            "match code",
            6,
            allow_empty=True,
        ),
        "last_error": _error(state.get("last_error", "")),
        "revoked": revoked,
    }


def durable_state(state):
    state = _copy_state(state)
    return {
        "schema": SCHEMA,
        "paired": state["paired"],
        "owner_hint": state["owner_hint"] if state["paired"] else "",
    }


def restore_durable(record):
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise ValueError("durable pair state schema is invalid")
    paired = record.get("paired")
    if not isinstance(paired, bool):
        raise ValueError("durable pair flag is invalid")
    owner_hint = _text(
        record.get("owner_hint", ""),
        "owner hint",
        MAX_OWNER_HINT,
        allow_empty=True,
    )
    return new_state(paired=paired, owner_hint=owner_hint)


def _clear_flow(state, phase, paired=None):
    state["phase"] = phase
    if paired is not None:
        state["paired"] = paired
    state["code"] = ""
    state["remaining_ms"] = 0
    state["claim_id"] = ""
    state["match_code"] = ""
    return state


def _fresh_with_error(error=""):
    state = new_state()
    state["last_error"] = _error(error)
    return state


def _action(action_type, **fields):
    action = {"type": action_type}
    action.update(fields)
    return action


def _expire(state):
    if state["phase"] == CODE:
        return _fresh_with_error("pair_expired"), [_action("pair_cancel", reason="expired")]
    if state["phase"] == CONFIRM:
        claim_id = state["claim_id"]
        return _fresh_with_error("confirm_expired"), [
            _action("pair_decline", claim_id=claim_id, reason="expired")
        ]
    return state, []


def _event_type(event):
    if isinstance(event, str):
        event = {"type": event}
    if not isinstance(event, dict):
        raise ValueError("pair event must be text or an object")
    event_type = event.get("type")
    if event_type not in EVENT_TYPES:
        raise ValueError("unknown pair event")
    return event_type, event


def _apply_event(state, event_type, event):
    phase = state["phase"]
    actions = []

    if event_type == "revoked":
        state = _fresh_with_error("revoked")
        state["revoked"] = True
        return state, actions
    if event_type == "remote_unpaired" and state["paired"]:
        return _fresh_with_error("remote_unpaired"), actions
    if state["revoked"]:
        return state, actions

    if event_type == "pair_pressed" and phase == UNPAIRED:
        state = _clear_flow(state, STARTING, paired=False)
        state["last_error"] = ""
        actions.append(_action("pair_start"))
    elif event_type == "pair_started" and phase == STARTING:
        state["phase"] = CODE
        state["code"] = _pair_code(event.get("code"))
        state["remaining_ms"] = _remaining(event.get("expires_in_ms"))
        state["last_error"] = ""
    elif event_type == "pair_start_failed" and phase == STARTING:
        state = _fresh_with_error(event.get("error", "pair_start_failed"))
    elif event_type == "claim_received" and phase == CODE:
        state["phase"] = CONFIRM
        state["claim_id"] = _claim_id(event.get("claim_id"))
        state["match_code"] = _match_code(event.get("match_code"))
        state["remaining_ms"] = _remaining(event.get("expires_in_ms"))
        state["last_error"] = ""
    elif event_type == "back" and phase == STARTING:
        state = _fresh_with_error()
    elif event_type == "back" and phase == CODE:
        state = _fresh_with_error("pair_cancelled")
        actions.append(_action("pair_cancel", reason="owner_back"))
    elif event_type in ("back", "decline") and phase == CONFIRM:
        claim_id = state["claim_id"]
        state = _fresh_with_error("pair_declined")
        actions.append(_action("pair_decline", claim_id=claim_id, reason="owner_declined"))
    elif event_type == "accept" and phase == CONFIRM:
        claim_id = state["claim_id"]
        state = _clear_flow(state, ACKING, paired=False)
        state["claim_id"] = claim_id
        state["last_error"] = ""
        actions.append(_action("pair_ack", claim_id=claim_id))
    elif event_type == "ack_succeeded" and phase == ACKING:
        owner_hint = _text(
            event.get("owner_hint", ""),
            "owner hint",
            MAX_OWNER_HINT,
            allow_empty=True,
        )
        state = new_state(paired=True, owner_hint=owner_hint)
    elif event_type == "ack_failed" and phase == ACKING:
        state["last_error"] = _error(event.get("error", "pair_ack_failed"))
    elif event_type == "retry" and phase == ACKING:
        actions.append(_action("pair_ack", claim_id=state["claim_id"]))
    elif event_type == "open_unpair" and phase == PAIRED:
        state["phase"] = UNPAIR_CONFIRM
        state["last_error"] = ""
    elif event_type == "keep" and phase == UNPAIR_CONFIRM:
        state["phase"] = PAIRED
    elif event_type == "unpair" and phase == UNPAIR_CONFIRM:
        state["phase"] = UNPAIRING
        state["last_error"] = ""
        actions.append(_action("unpair"))
    elif event_type == "unpair_succeeded" and phase == UNPAIRING:
        state = new_state()
    elif event_type == "unpair_failed" and phase == UNPAIRING:
        state["last_error"] = _error(event.get("error", "unpair_failed"))
    elif event_type == "retry" and phase == UNPAIRING:
        actions.append(_action("unpair"))

    return state, actions


def advance(state, elapsed_ms, events):
    """Advance countdown, then apply observed events; return `(state, actions)`."""

    if not isinstance(elapsed_ms, int) or isinstance(elapsed_ms, bool) or elapsed_ms < 0:
        raise ValueError("elapsed_ms must be a non-negative integer")
    if not isinstance(events, (list, tuple)):
        raise ValueError("events must be a list or tuple")
    state = _copy_state(state)
    actions = []

    if state["phase"] in (CODE, CONFIRM) and elapsed_ms:
        state["remaining_ms"] = max(0, state["remaining_ms"] - elapsed_ms)
        if state["remaining_ms"] == 0:
            state, expiry_actions = _expire(state)
            actions.extend(expiry_actions)

    for event in events:
        event_type, event = _event_type(event)
        state, event_actions = _apply_event(state, event_type, event)
        actions.extend(event_actions)
    return state, actions
