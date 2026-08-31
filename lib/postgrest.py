"""PostgREST RPC request shaping and response adjudication for the badge.

Pure and I/O-free: a request is a dict the link adapter hands to AsyncFetch; a
response is a ``(status, body_bytes)`` pair this module adjudicates. The badge
talks ONLY to PostgREST (Data API + the P1 SECURITY DEFINER RPCs) — no Storage,
no Realtime in P4 (ADR-006) — with ``Authorization: Bearer <jwt>`` and the
mandatory ``apikey`` header.

Adjudication rule (binding, receipts-verified — build brief / ADR-006): on
PostgREST **only HTTP 401 counts as rejected**. 200 is success; a forged token on
a missing object 404s (that is "authenticated, nothing there"), so 404 is NOT a
rejection. This module raises :class:`AuthRejected` only on 401. A 403 is the
separate authorization verdict — grant denied / badge revoked — and raises
:class:`AccessRevoked`, which the transport treats as stop-for-this-boot rather
than as something to retry (owner ruling 2026-08-19).

The RPC names, the ``/rest/v1/rpc/`` path form, the param keys, the header
construction and that adjudication rule are the SHARED contract in
``rpc_contract`` (card R1), which the async host module ``data_api.py`` reads
too. Everything else here — the request-dict envelope, the byte cap, the strict
argument validation and the row normalisation — is this lane's own shape.
``rpc_contract`` must be present in ``/system/lib`` beside this module.
"""

import json

import rpc_contract


# This lane's own cap, deliberately NOT shared: it is 8192 here (request AND
# response) against data_api's 4096 response cap, and a shared constant would
# hide that divergence instead of settling it (R1 memo D7).
MAX_BODY_BYTES = 8192

# The rest is the shared contract (rpc_contract.py), re-exported under the names
# device_link and the tests already import. The async host module data_api.py
# reads the same values, which is what keeps the two lanes on one wire shape.
REST_RPC_PREFIX = rpc_contract.RPC_PREFIX
MAX_COMMANDS = rpc_contract.MAX_COMMANDS
POLL_RPC = rpc_contract.RPC_POLL
ACK_RPC = rpc_contract.RPC_ACK
POLICY_RPC = rpc_contract.RPC_TRANSPORT_POLICY
ACK_APPLIED = rpc_contract.ACK_APPLIED
ACK_FAILED = rpc_contract.ACK_FAILED

# The SELF-ADDRESSED pair this lane routes to under the shared fleet token. The
# whoami-keyed names above are retained (the server keeps both functions live and
# a badge on its own per-badge token resolves them correctly), but nothing on the
# shared-token path may reach them: `whoami()` is one subject for ~800 badges, so
# the old poll returns the shared queue and finds none of THIS badge's commands.
POLL_SELF_RPC = rpc_contract.RPC_POLL_SELF
ACK_SELF_RPC = rpc_contract.RPC_ACK_SELF

class PostgrestError(Exception):
    """A non-auth transport-level failure (bad status, unparseable body)."""


class AuthRejected(PostgrestError):
    """HTTP 401 — the token was rejected. The only status that means rejected."""


class AccessRevoked(PostgrestError):
    """HTTP 403 — a live grant was denied, or this badge was revoked.

    Owner ruling 2026-08-19: on the device lane a 403 is a VERDICT, not a blip.
    It used to collapse into a plain retryable :class:`PostgrestError`, so a
    revoked badge reconnect-polled forever (the R1 contract memo called this out
    as the known device-side gap). It is a subclass of ``PostgrestError`` so a
    caller that only knows the old taxonomy still fails closed; a caller that
    wants the verdict catches this first and stops for the session.
    """


#: THE SELF-REPORTED ID'S SHAPE, validated HERE and not only by the server. This
#: lane validates its arguments strictly on purpose (bounded poll limit, ack
#: status vocabulary, dict result), and the reason applies with more force to
#: this one: the server answers a malformed `p_badge_id` with a 22023, which
#: arrives as one retryable transport fault and looks exactly like a flaky venue.
#: Refusing locally puts the fault in the frame that built it.
BADGE_ID_CHARS = "0123456789abcdef"
BADGE_ID_LEN = 16


def _self_badge_id(value):
    """The self-reported physical id, or raise. Lowercase 16-hex, exactly."""

    if not isinstance(value, str) or len(value) != BADGE_ID_LEN:
        raise PostgrestError("self badge id must be 16 characters")
    for character in value:
        if character not in BADGE_ID_CHARS:
            raise PostgrestError("self badge id must be lowercase hex")
    return value


def _json_bytes(value):
    try:
        return json.dumps(value).encode("utf-8")
    except (TypeError, ValueError):
        raise PostgrestError("request params are not JSON-serializable")


def rpc_request(credentials, function, params=None, method="POST",
                self_badge_id=None, device_token=None):
    """Describe a POST, or a query-argument GET, to an RPC endpoint.

    Returns a dict the link adapter feeds to AsyncFetch. ``connect_host`` is the
    cached IP when available (DNS off-frame); ``server_hostname`` stays the real
    hostname so SNI and certificate verification are never keyed on an IP.

    PostgREST puts GET arguments in the query string. They pass through the same
    deliberately narrow, no-escaping alphabet as table filters below: the only
    non-empty GET argument in shipping firmware is Schedule's canonical UUID.
    Refusing anything outside that alphabet is safer than carrying a partial URL
    encoder on a frozen MicroPython image.

    ``self_badge_id`` rides as ``x-badge-id`` on EVERY request this builds, which
    is why it is here rather than on the two RPCs that need it semantically: it
    is the rate-limit bucket key, and a request that omits it is limited on the
    one bucket the whole fleet shares. Unvalidated and optional on purpose --
    `rpc_contract.rpc_headers` drops anything unusable and the fallback is
    degraded, not broken.
    """
    # Badgeware v3.0.1's MicroPython ``str`` has no ``isalnum``. Keep the
    # accepted RPC surface deliberately ASCII-only and implement the check with
    # primitives shared by CPython and the device runtime.
    if (
        not isinstance(function, str)
        or not function
        or any(
            not (
                "a" <= character <= "z"
                or "A" <= character <= "Z"
                or "0" <= character <= "9"
                or character == "_"
            )
            for character in function
        )
    ):
        raise PostgrestError("rpc function name must be alphanumeric/underscore")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise PostgrestError("rpc params must be an object")
    if method not in ("GET", "POST"):
        raise PostgrestError("rpc method must be GET or POST")
    body = None if method == "GET" else _json_bytes(params)
    if body is not None and len(body) > MAX_BODY_BYTES:
        raise PostgrestError("rpc request body exceeds byte cap")
    path = rpc_contract.rpc_path(function)
    if method == "GET" and params:
        parts = []
        for key, value in params.items():
            parts.append(
                _safe_query_part(key, "key") + "="
                + _safe_query_part(str(value), "value")
            )
        path = path + "?" + "&".join(parts)
    return {
        "method": method,
        "connect_host": credentials.connect_host(),
        "server_hostname": credentials.host,
        "path": path,
        "url": "https://{}{}".format(credentials.host, path),
        "headers": rpc_contract.rpc_headers(
            credentials.jwt, credentials.apikey,
            content_type=(body is not None), badge_id=self_badge_id,
            device_token=device_token,
        ),
        "body": body,
    }


# The characters a query value may carry. PostgREST filters are built from
# these (`select=id,title`, `order=starts_at.asc`, `limit=200`,
# `starts_at=gte.2026-08-22T00:00:00Z`) and nothing here is ever percent-encoded,
# so anything outside the set is REFUSED rather than escaped: an encoder is a
# thing that can be wrong, and a rejection cannot be.
_QUERY_SAFE = ("abcdefghijklmnopqrstuvwxyz"
               "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
               "0123456789"
               "-._~,:*()")


def _safe_query_part(value, what):
    if not isinstance(value, str) or not value:
        raise PostgrestError("table query {} must be a non-empty string".format(what))
    for character in value:
        if character not in _QUERY_SAFE:
            raise PostgrestError(
                "table query {} carries an unencodable character".format(what))
    return value


def table_request(credentials, table, method="POST", row=None, prefer=None,
                  query=None, self_badge_id=None, device_token=None):
    """Describe a request to an ordinary PostgREST TABLE endpoint.

    The device lane was RPC-only until Card FT-B: ``rpc_request`` rejects a ``/``
    in its function name on purpose, so a table path cannot be smuggled through
    it. Three FT-B features need one -- ``report_state``'s ``badge_state`` write,
    the scorebox's ``scores`` insert and the schedule fetch -- and all three are
    covered by grants the schema already carries, so the alternative was a
    SECURITY DEFINER RPC per verb and an owner Supabase push per verb. That is
    the redesign the "vocabulary grows by migration plus applier" rule exists to
    avoid.

    ``query`` is a tuple of ``(key, value)`` pairs, each validated against a
    conservative safe set and joined with ``&``. Nothing is percent-encoded and
    nothing is escaped; an unencodable character is an error.
    """

    if not isinstance(table, str) or not table:
        raise PostgrestError("table name must be a non-empty string")
    for character in table:
        if not (("a" <= character <= "z") or ("0" <= character <= "9")
                or character == "_"):
            raise PostgrestError("table name must be lowercase/underscore")
    if method not in ("GET", "POST", "PATCH"):
        raise PostgrestError("table method must be GET, POST or PATCH")
    path = rpc_contract.table_path(table)
    if query:
        if not isinstance(query, (tuple, list)):
            raise PostgrestError("table query must be a tuple of pairs")
        parts = []
        for pair in query:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise PostgrestError("table query pairs must be (key, value)")
            key = _safe_query_part(pair[0], "key")
            value = _safe_query_part(str(pair[1]), "value")
            parts.append(key + "=" + value)
        path = path + "?" + "&".join(parts)
    body = None
    if method == "POST":
        if not isinstance(row, (dict, list)):
            raise PostgrestError("table POST requires an object or array body")
        body = _json_bytes(row)
    elif method == "PATCH":
        if not isinstance(row, dict):
            raise PostgrestError("table PATCH requires an object body")
        body = _json_bytes(row)
    if body is not None:
        if len(body) > MAX_BODY_BYTES:
            raise PostgrestError("table request body exceeds byte cap")
    elif method == "GET" and row is not None:
        raise PostgrestError("table GET takes no body")
    headers = rpc_contract.rpc_headers(
        credentials.jwt, credentials.apikey, content_type=(body is not None),
        badge_id=self_badge_id, device_token=device_token)
    if prefer is not None:
        if not isinstance(prefer, str) or not prefer:
            raise PostgrestError("table prefer must be a non-empty string")
        headers["Prefer"] = prefer
    return {
        "method": method,
        "connect_host": credentials.connect_host(),
        "server_hostname": credentials.host,
        "path": path,
        "url": "https://{}{}".format(credentials.host, path),
        "headers": headers,
        "body": body,
    }


def poll_request(credentials, limit=rpc_contract.DEFAULT_POLL_LIMIT,
                 self_badge_id=None):
    """Describe the self-addressed command poll.

    ``self_badge_id=None`` FALLS BACK TO THE WHOAMI POLL. **It used to raise, and
    that was a floor-severity mistake in the fail-soft direction that matters
    most.** The reasoning for raising was diagnosability: under the shared subject
    the whoami poll returns the fleet row's queue, which holds no per-badge
    command, so the badge would poll successfully forever and receive nothing --
    indistinguishable from a quiet event.

    That trade was wrong twice over. The primed poll runs INSIDE
    ``DeviceLink.open``, so a refusal fails the OPEN -- the socket never comes up,
    and with it go the schedule sync, the ``badge_state`` heartbeat, the score
    drain and the steering read, none of which need a badge id at all. Polling is
    the correctness floor and a missing hardware id is not a reason to take the
    floor down. And the diagnosability argument is answerable with a line rather
    than with an outage: `network_runtime` emits one when the uid read fails.

    So: no id means the historical whoami poll, which delivers nothing new on the
    shared subject and delivers correctly on a per-badge token. A MALFORMED id
    still raises -- that is a wiring mistake, not a degradation, and it fails in
    the frame that made it.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_COMMANDS:
        raise PostgrestError("poll limit must be 1..{}".format(MAX_COMMANDS))
    if self_badge_id is None:
        return rpc_request(credentials, POLL_RPC, rpc_contract.poll_params(limit))
    badge_id = _self_badge_id(self_badge_id)
    return rpc_request(credentials, POLL_SELF_RPC,
                       rpc_contract.poll_self_params(limit, badge_id),
                       self_badge_id=badge_id)


def policy_request(credentials, self_badge_id=None):
    """Describe the FLEET transport-policy read. No arguments, deliberately.

    The one whoami-keyed read that stays correct under a shared subject: it is
    fleet-scoped by design, so ``p_badge_id`` must NOT be added. It still carries
    ``x-badge-id``, because that header is about which rate bucket the request
    lands in and not about what the request asks for.
    """
    return rpc_request(credentials, POLICY_RPC,
                       rpc_contract.transport_policy_params(),
                       self_badge_id=self_badge_id)


def ack_request(credentials, command_id, status, result=None,
                self_badge_id=None):
    """Describe the self-addressed ack.

    ``self_badge_id=None`` falls back to the whoami ack for :func:`poll_request`'s
    reason, and it is CONSISTENT rather than merely lenient: a badge that polled
    the whoami queue must ack on the same queue, or the ack matches no row, the
    command stays ``delivered``, the next poll hands it back and the doorbell
    re-rings. A silent ack failure is a redelivery loop, not a lost message, so
    the two halves have to agree about which family they are in.
    """
    if not isinstance(command_id, str) or not command_id:
        raise PostgrestError("ack command_id must be a non-empty string")
    if status not in (ACK_APPLIED, ACK_FAILED):
        raise PostgrestError("ack status must be 'applied' or 'failed'")
    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise PostgrestError("ack result must be an object")
    if self_badge_id is None:
        return rpc_request(credentials, ACK_RPC,
                           rpc_contract.ack_params(command_id, status, result))
    badge_id = _self_badge_id(self_badge_id)
    return rpc_request(
        credentials,
        ACK_SELF_RPC,
        rpc_contract.ack_self_params(command_id, status, result, badge_id),
        self_badge_id=badge_id,
    )


def _decode_body(body):
    # Frozen AsyncFetch exposes its bounded response buffer as a zero-copy
    # ``memoryview``. Convert only at the parser boundary so JSON decoding has
    # the same input on CPython and MicroPython.
    if isinstance(body, (bytes, bytearray, memoryview)):
        if len(body) > MAX_BODY_BYTES:
            raise PostgrestError("response body exceeds byte cap")
        try:
            body = bytes(body).decode("utf-8")
        except UnicodeError:
            raise PostgrestError("response body is not UTF-8")
    elif not isinstance(body, str):
        raise PostgrestError("response body must be bytes or str")
    elif len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise PostgrestError("response body exceeds byte cap")
    return body


def parse_response(status, body):
    """Adjudicate a PostgREST response into decoded JSON, or raise.

    401 -> :class:`AuthRejected`. 403 -> :class:`AccessRevoked` (revoked/stop,
    owner ruling 2026-08-19). Any other non-2xx -> a plain
    :class:`PostgrestError` (retryable transport fault, not a verdict).
    """
    if not isinstance(status, int) or isinstance(status, bool):
        raise PostgrestError("status must be an integer")
    if rpc_contract.is_rejected(status):
        raise AuthRejected("PostgREST rejected the token (401)")
    # The shared contract adjudicates 403; only that one class is read here so
    # the wider success window below stays this lane's own (R1 memo D1) rather
    # than being laundered into classify_status's exact {200, 201, 204}.
    if rpc_contract.classify_status(status) == rpc_contract.FORBIDDEN:
        raise AccessRevoked("PostgREST denied the grant (403)")
    # The accepted success window stays wider here than data_api's exact
    # {200, 201, 204}; unifying it is a separate ruling (R1 memo D1).
    if not 200 <= status < 300:
        raise PostgrestError("PostgREST returned HTTP {}".format(status))
    text = _decode_body(body).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        raise PostgrestError("PostgREST body is not JSON")


def _bounded_str(value, maximum):
    if not isinstance(value, str):
        return None
    return value if len(value) <= maximum else value[:maximum]


def parse_poll_rows(decoded):
    """Normalise legacy ``badgelink_badge_poll`` rows for historical probes.

    The rebuild dropped this RPC and production calls no longer reach here. The
    parser remains only because dated transport probes use its old row shape as
    an oracle; it must not be read as a shipping queue or scheduling surface.
    """
    if decoded is None:
        return []
    if not isinstance(decoded, list):
        raise PostgrestError("poll response must be a JSON array")
    if len(decoded) > MAX_COMMANDS:
        raise PostgrestError("poll returned more rows than the limit allows")
    commands = []
    for row in decoded:
        if not isinstance(row, dict):
            continue
        command_id = _bounded_str(row.get("command_id"), 64)
        command_type = _bounded_str(row.get("command_type"), 64)
        if not command_id or not command_type:
            continue
        commands.append(
            {
                "id": command_id,
                "type": command_type,
                "payload": row.get("payload"),
                "execute_at": row.get("execute_at"),
                "attempts": row.get("delivery_attempts"),
            }
        )
    return commands


def parse_policy_row(decoded):
    """Normalise the fleet-settings row into steering fields.

    FAILS OPEN, deliberately and in one place: anything this cannot read
    confidently is dropped, and a dropped field leaves the client on its own
    default. The reasoning is in ``pushlink.PushPolicy.set_remote`` — a kill
    switch that fails closed makes the switch load-bearing, and a truncated
    body (a class Card E measured on real relay faults) would then disable push
    on badges nobody touched.

    W8 keeps physical acts out of this repeating row. Radio, backlight and sleep
    arrive through fleet broadcasts; parsing a legacy copy here would silently
    restore the very repeated-state behavior the split removed.

    ITS PRODUCER CHANGED AND ITS SHAPE DID NOT (rebuild, 2026-08-29). This read
    an RPC's row until today and now reads ``GET /rest/v1/fleet_settings?limit=1``,
    which is a JSON ARRAY of one object -- a case the list branch below already
    handled, because the RPC returned ``returns table``. ``policy_version`` and
    ``source`` have no column in the new table and simply never arrive; they are
    still read because nothing is gained by refusing a field a future row might
    carry, and ``pushlink`` still consumes the version when it is there.
    """
    row = decoded
    if isinstance(row, list):
        if not row:
            return {}
        row = row[0]
    if not isinstance(row, dict):
        return {}
    out = {}
    # THE BOOLEAN LEVERS. `isinstance(x, bool)` and nothing else: a `0`, a `""` or
    # a `"false"` is a MALFORMED field, not a false one, and the difference is
    # whether a typo in one console field can take the fleet's radios down.
    # `scores_enabled` joined them on 2026-08-29 and takes the same treatment for
    # the same reason: a malformed value must leave the drain on its own default,
    # which is ON. A firmware that read `0`/`"false"` as false would let one typo
    # in one console field silently stop every badge in the hall from posting.
    for key in ("push_enabled", "scores_enabled"):
        value = row.get(key)
        if isinstance(value, bool):
            out[key] = value
    version = row.get("policy_version")
    if isinstance(version, int) and not isinstance(version, bool):
        out["policy_version"] = version
    cadence = row.get("next_cadence_ms")
    if isinstance(cadence, int) and not isinstance(cadence, bool):
        out["next_cadence_ms"] = cadence
    elif "next_cadence_ms" in row and cadence is None:
        # NULL IS AN EXPLICIT OPERATOR ANSWER, not a truncated field. Admin uses
        # it for "return to the badge default"; dropping it left a cadence the
        # badge learned earlier in force until the next app-reset.
        out["next_cadence_ms"] = None
    source = _bounded_str(row.get("source"), 32)
    if source:
        out["source"] = source
    return out


def parse_ack_row(decoded):
    """Return ``(command_id, status)`` from an ack RPC result, or raise."""
    rows = decoded
    if isinstance(rows, list):
        if not rows:
            raise PostgrestError("ack returned no row")
        rows = rows[0]
    if not isinstance(rows, dict):
        raise PostgrestError("ack row must be an object")
    command_id = _bounded_str(rows.get("command_id"), 64)
    status = rows.get("status")
    if not command_id or status not in (ACK_APPLIED, ACK_FAILED):
        raise PostgrestError("ack row is malformed")
    return command_id, status
