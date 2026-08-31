"""The shared BadgeLink PostgREST RPC contract (card R1).

Single source of truth for the things ``data_api.py`` (the async whole-request
host shape, proven by the Card C hosted campaign) and ``postgrest.py`` (the
per-frame device shape, proven by the Card E device run) must always agree on:
the RPC names, the ``/rest/v1/rpc/<name>`` path form, the param key names, the
auth header construction, and the status adjudication rule. Both files authored
these independently and each was validated on the wire, so every value here is
a FROZEN wire literal, not a preference: changing one silently forks a proven
lane. ``badgelink/tests/test_rpc_contract.py`` pins each literal for that
reason.

TWO FAMILIES SINCE 2026-08-26, and the split is the shared fleet token. The
original RPCs derive the badge from ``grants.whoami()``, i.e. from the JWT
``sub``; the ``_self`` family takes the physical ``machine.unique_id().hex()`` as
an explicit ``p_badge_id``. Both are live and both are frozen: gang-clone
provisioning means every badge ships the SAME ``sub``, so the whoami-keyed
functions COLLAPSE the fleet onto one identity rather than failing, and a badge
still holding its own per-badge token resolves them correctly. **Nothing on the
shared-token path may resolve to a whoami-derived RPC** -- that is not a style
rule, it is the difference between a poll that returns this badge's commands and
one that returns none.

Adjudication (receipts-verified, binding for every BadgeLink auth path):
**only HTTP 401 means the token was REJECTED.** 200/204 succeed. 404 means
"authenticated, nothing there" -- a forged token on a missing target 404s -- and
is never a rejection. 403 is authorization (a live grant denied, or the badge
revoked), which the badge treats as "revoked / stop", never "retry harder" --
on BOTH lanes since the owner ruling of 2026-08-19.

Deliberate, documented consumer divergences this module does NOT launder (they
each need their own owner ruling; R1 is a behavior-preserving extraction):

* Success set. ``classify_status`` -- and therefore ``data_api`` -- treats
  exactly {200, 201, 204} as OK and anything else below 500 as MALFORMED.
  ``postgrest.parse_response`` accepts the whole ``200 <= status < 300`` window.
  A 202/206 is success on-device and retry-after-backoff on the host lane.
* 404/429 consequence. The host lane has the fine-grained classes below and
  branches on each; the device lane still collapses 404/408/429/5xx into one
  retryable ``PostgrestError`` and lets its backoff sort them out.

  **403 no longer diverges (owner ruling 2026-08-19, and it was the fix this
  module was shaped for).** The device lane used to collapse every non-2xx that
  was not 401 into a retryable error, so a revoked badge reconnect-polled
  forever; ``postgrest.parse_response`` now reads ``classify_status`` for exactly
  the ``FORBIDDEN`` verdict and raises ``AccessRevoked``, which ``device_link``
  maps to ``polltransport.LinkRevoked`` and the loop turns into its terminal
  ``REVOKED`` state for the rest of the boot. Both lanes therefore mean the same
  thing by 403: stop, do not retry harder. The success-window divergence below is
  untouched, because ``parse_response`` reads only the ``FORBIDDEN`` answer out
  of ``classify_status`` and keeps its own ``2xx`` test.
* Byte caps. ``data_api.MAX_RESPONSE_BYTES`` is 4096 (response only) and
  ``postgrest.MAX_BODY_BYTES`` is 8192 (request and response). The caps stay
  with their consumers on purpose: moving two different numbers into a "shared"
  module would hide the divergence rather than settle it.
* Argument validation. ``postgrest`` validates strictly (bounded int poll limit,
  ack status in the vocabulary, dict result) and ``data_api`` coerces
  permissively. Nothing here validates: the builders below are total functions
  that cannot raise, so neither consumer's exception taxonomy is disturbed.

This module ships to ``/system/lib`` beside ``postgrest.mpy``, so it imports
NOTHING -- no ``json``, no ``typing``, no ``enum`` -- and uses only constructs
the frozen Badgeware v3.0.1 MicroPython runtime and the pinned mpy-cross both
accept. JSON serialization stays in the consumers.
"""


REST_PREFIX = "/rest/v1"
RPC_PREFIX = "/rest/v1/rpc/"

# RPC names. Frozen by the deployed P1 schema (SECURITY DEFINER functions).
RPC_PAIR_START = "badgelink_pair_start"
RPC_PAIR_CONFIRM = "badgelink_pair_confirm"
RPC_PAIR_BIND = "badgelink_pair_bind"
RPC_POLL = "badgelink_badge_poll"
RPC_ACK = "badgelink_badge_ack_command"

# -- the SELF-ADDRESSED family (the shared fleet token, 2026-08-26) -----------
#
# THE COLLAPSE THESE CLOSE, and it is worth stating before the names. Every RPC
# above derives the badge from ``grants.whoami()``, which reads the JWT ``sub``.
# That was this badge's own 16-hex id while provisioning minted one token per
# badge. Gang-clone provisioning ships a byte-identical ``/secrets.py``, so
# ``whoami()`` returns the SAME shared subject for all ~800 badges: the RPCs
# above do not fail, they COLLAPSE. A rung badge polls the shared subject's queue
# and finds zero rows, because commands are inserted per PHYSICAL badge id; every
# score folds onto one leaderboard row.
#
# So the new path passes the physical id EXPLICITLY as ``p_badge_id`` --
# ``machine.unique_id().hex()``, which is the only per-badge value a
# gang-cloned image has. The id is SELF-REPORTED and the server treats it as an
# addressing key, never as an authorization: the gate is the live floor grant on
# the shared subject (``commands/poll``, ``commands/ack``, ``scores/write``),
# joined against ``badges.revoked_at``, so revoking that one row is the fleet
# kill switch. Spoofability is accepted and bounded -- at worst another badge's
# command queue or a score for a fabricated id, never a read of ``scores``,
# ``devices`` or another schema.
#
# FROZEN BY NAME AND ARGUMENT KEY, cross-lane, and pinned in
# ``badgelink/tests/test_rpc_contract.py`` because a rename on either side is
# SILENT in the worst way: PostgREST answers PGRST202 for a function it cannot
# find and the badge reads that as one failed request, so a fleet whose delivery
# path is dead looks exactly like a quiet event. The deployed signatures are
# ``badgelink/supabase/migrations/20260826051213_badgelink_command_self.sql``.
RPC_POLL_SELF = "badgelink_badge_poll_self"
RPC_ACK_SELF = "badgelink_badge_ack_command_self"
# ADDITIVE, and deliberately a SECOND RPC rather than a change to RPC_POLL
# (P6-L3, 2026-08-21). The steering channel the badge reads is the poll
# response's own dict -- ``next_cadence_ms`` today, ``push_enabled`` now -- and
# extending that CHANNEL does not require changing the poll WIRE. It must not:
# ``badgelink_badge_poll`` is a ``returns table`` function proven on two
# independent lanes (Card C hosted, Card E device), a new OUT column would force
# a DROP/CREATE and a new row shape on both, and the module docstring above is a
# standing instruction that changing one silently forks the other. So the fleet
# transport policy arrives on its own slow-cadence call and flows into the SAME
# steering fields, which also means a future server that folds those fields into
# the poll response needs no client change at all.
RPC_TRANSPORT_POLICY = "badgelink_badge_transport_policy"

# Card FT-S's derived schedule version, read on a slow cadence by Card FT-B's
# schedule sync. `returns table (version text, event_count integer, changed_at
# timestamptz)` and the badge compares ONE field, `version`, for equality: the
# whole point of the function is that a badge which has not changed pays one
# small round trip instead of fetching rows.
RPC_SCHEDULE_VERSION = "badgelink_schedule_version"

# The Schedule app's one-open whole-snapshot read. Unlike the historical
# version+table projection above, this RPC returns the exact schema-2 artifact
# the app validates and caches, and it is requested only when the wearer opens
# Schedule. The optional UUID lets an unchanged open return identity alone;
# changed content remains one atomic replacement rather than a patch stream.
RPC_SCHEDULE_CURRENT_V2 = "badgelink_schedule_current_v2"

# ``RPC_SCORE_SUBMIT`` AND ``score_submit_params`` ARE DELETED (2026-08-29), and
# the deletion is the migration's rather than a tidy-up. They were kept as a
# frozen historical literal expressly "because the server keeps the function
# live" -- and ``20260829170000_scores_play_number`` DROPS it, because its body
# inserts into ``idempotency_key``, a column that no longer exists. A plpgsql
# body is not validated until it is called, so leaving the literal here would
# have turned a stale caller into a runtime error instead of a 404. Nothing
# called it: the fleet-token ``whoami()`` derivation attributed the whole hall to
# one row, which is why ``_self`` exists.

#: The self-addressed score write. Takes ``p_badge_id`` FIRST, auto-provisions a
#: ``badges`` row so the FK holds for an unseeded physical id, and bypasses RLS
#: as ``postgres`` -- which is the point: a direct ``scores`` insert with a
#: client-side ``ON CONFLICT`` would force a ``scores`` SELECT grant onto the
#: badge and leak the human-only leaderboard read. **Every badge writes scores,
#: claimed or not** (owner ruling); the leaderboard READ stays human-only.
RPC_SCORE_SUBMIT_SELF = "badgelink_badge_submit_score_self"

# -- fairness and verified-tier headers (wire literals) ----------------------
#
# LOWERCASE, because PostgREST exposes request headers to SQL through
# ``current_setting('request.headers')`` with lowercased keys, and
# ``grants.check_request`` reads them by exactly these names.
#
#: THE PER-BADGE RATE BUCKET, and it is release-blocking rather than a nicety.
#: The server limiter keys its modifying-request bucket on ``role:sub``, so under
#: one shared subject all ~800 badges share ONE bucket -- and poll, ack, score
#: and heartbeat are all POSTs, so an SF-morning mass cold boot is a fleet-wide
#: 429 storm against a limit sized for one badge. The server re-keys the bucket
#: on this self-reported header for the shared subject only, gated on
#: ``^[0-9a-f]{16}$``. FAIL-OVER, NEVER FAIL-CLOSED: omitting it falls back to
#: the shared-subject bucket, which is degraded and still functional. A spoof
#: only reshuffles which bucket the spoofer's own requests land in.
#:
#: **PostgREST ONLY, NEVER REALTIME.** The doorbell holds no credential beyond
#: ``token_provider`` and its authorization is ``can_access_channel``; a header
#: on a Phoenix frame would be a second identity channel on a path that has no
#: use for one.
HEADER_BADGE_ID = "x-badge-id"

#: THE VERIFIED TIER'S CREDENTIAL, and it is the ONLY non-spoofable per-badge
#: signal the system has. An opaque random bearer the server mints when a human
#: vouches for a scanned QR -- not a JWT, no signing key, no expiry and no refresh
#: path (owner ruling 1), so revocation is the whole lifecycle.
#:
#: **POSTGREST WRITES ONLY. NEVER REALTIME, NEVER A FLOOR READ.** Realtime
#: authorization is `grants.can_access_channel`, which reads the JWT claims and
#: knows nothing about this header -- and the doorbell must keep working for an
#: UNCLAIMED badge, so making it depend on a credential most badges do not have
#: would break the tier boundary in the expensive direction. Absent or corrupt
#: means the floor path, which every badge always has.
#:
#: READ THE TWO HEADERS TOGETHER TO SEE THE TIERS: `x-badge-id` is a FAIRNESS
#: dimension a spoof can only use to reshuffle its own rate bucket, and this is
#: an AUTHORIZATION credential a spoof cannot forge. Confusing them is the one
#: mistake that would matter.
HEADER_DEVICE_TOKEN = "x-device-token"

# DIRECT-TABLE paths. Badge state and schedule events remain ordinary PostgREST
# endpoints because that is what their schema grants. ``TABLE_SCORES`` remains
# as a shared table literal, but the badge drain does not use it: PostgREST's
# client-side ON CONFLICT forced SELECT privileges onto a write-only surface, so
# score conflict resolution moved behind ``RPC_SCORE_SUBMIT_SELF``. The lane is
# kept working by the grants and ``scores_badge_read_self`` so firmware can move
# to it without another migration -- and since the primary key IS the natural key
# ``(badge_id, game, play_number, score)``, PostgREST would infer the conflict
# target from it with no ``on_conflict`` parameter.
#
# `data_api.py` spelled `REST_PREFIX + "/badge_state"` inline before Card FT-B
# needed the same string on the device lane. It is here now for the reason every
# other literal in this module is: two files authored the same wire shape once
# already, and the drift is silent.
TABLE_BADGE_STATE = "badge_state"
TABLE_SCORES = "scores"
TABLE_SCHEDULE_EVENTS = "schedule_events"

#: THE HEARTBEAT AND THE SELF-REGISTRATION, WHICH ARE ONE REQUEST (rebuild,
#: 2026-08-29). `badges` and `badge_state` were 1:1 on the same key, so splitting
#: them made "who is alive?" a join and made a badge's first contact two writes.
#: A ~60 s ``POST /rest/v1/badges`` with ``PREFER_MERGE_MINIMAL`` both creates the
#: row and refreshes it -- the owner's "they try to pull, and we create a row for
#: them" -- which is why the old ``PATCH ?badge_id=eq.`` shape had to go: PATCH on
#: a row that does not exist is a 204 affecting zero rows, which
#: ``parse_response`` reads as SUCCESS, so a badge the server had never seen would
#: heartbeat into nothing for the whole event and look identical to a healthy one.
#:
#: ⚠ THE ROW'S KEY IS ``id`` AND IT IS ``network_runtime.hardware_uid()``, NEVER
#: the credential subject. All ~1,000 badges carry one JWT, so `sub` names the FLEET;
#: that single confusion is why the old ``badge_state`` table holds ONE row for
#: every badge in the building. See `NetworkService.state_report`.
TABLE_BADGES = "badges"

#: THE OPERATOR'S 2 pm LEVERS, read on a ~5 minute cadence, and the REST half of
#: the rebuild's "MOMENTS are broadcast, STATES are polled" split. It replaces
#: ``RPC_TRANSPORT_POLICY``: one ordinary singleton table with an RLS read policy
#: instead of a SECURITY DEFINER function, because a table a console can UPDATE is
#: a lever an operator can actually pull at the venue.
#:
#: IT IS ALSO THE CATCH-UP MECHANISM. A badge that missed a broadcast (or was
#: asleep, or off) learns the CURRENT state here, which is why every field it
#: carries has to be a STATE rather than an event: re-applying the same values
#: every five minutes must change nothing. See `NetworkService._apply_settings`.
TABLE_FLEET_SETTINGS = "fleet_settings"

#: THE COLUMN LIST, PINNED, AND ``select=*`` IS REFUSED ON PURPOSE. `postgrest`
#: caps a RESPONSE at ``MAX_BODY_BYTES`` (8192) on this lane, and a ``*`` that
#: grows a column one afternoon is a parse failure on ~1,000 badges the same
#: afternoon -- the failure mode being an operator lever that silently stops
#: working. Every name here is also a key `postgrest.parse_policy_row` knows.
#:
#: Every character must survive `postgrest._safe_query_part` unencoded (``,`` and
#: ``_`` are in its safe set); nothing on this lane is percent-encoded.
#:
#: `scores_enabled` JOINED IT ON 2026-08-29, AND IT WAS THE ONLY COLUMN IN THE
#: TABLE THE FIRMWARE NEVER ASKED FOR. It has existed in the schema and in the
#: admin console since the rebuild, and `host/verify_rebuild_wire.py` has always
#: read it -- but the string appeared nowhere in the badge, so the operator's
#: switch moved a boolean in Postgres and changed nothing on any badge. See
#: `network_runtime._apply_settings_scores`.
#:
#: W8 KEEPS ROUTINE BUSINESS STEERING AND NOTHING PHYSICAL. Sleep, networking
#: and backlight are one-shot broadcasts; asking for their old columns here
#: would turn a moment back into a value re-applied about 96 times per event day.
#: This is a required subset, not a frozen exact count: a future routine control
#: may join it once firmware has an observable consumer.
FLEET_SETTINGS_COLUMNS = ("next_cadence_ms", "push_enabled", "scores_enabled")
FLEET_SETTINGS_SELECT = ",".join(FLEET_SETTINGS_COLUMNS)

#: ONE ROW, FOREVER: the table is a singleton (`id boolean primary key default
#: true`), and ``limit=1`` says so on the wire rather than trusting it. The reply
#: is a JSON ARRAY of one object, which `parse_policy_row` already unwraps.
FLEET_SETTINGS_QUERY = (("select", FLEET_SETTINGS_SELECT), ("limit", "1"))

#: WHAT THE BADGE POSTS AFTER IT ACCEPTS A BROADCAST. For immediate effects that
#: also means acted; deferred sleep and radio-off are only ARMED at this point,
#: because sleeping cannot post after its radio closes. Hardware observation is
#: the execution proof. Shape: `{action_id, badge_id, at, result}`.
#:
#: IT REPLACES AN ACK AND IT IS NOT ONE. An ack answered a durable row the server
#: was holding open; a receipt answers nothing and is owed to nobody. Rows exist
#: only for badges that genuinely received and accepted the action, rather than
#: for every badge an operator hoped was connected.
#:
#: THEREFORE FAILING TO POST ONE IS NOT A FAILURE OF THE ACTION. The show played;
#: nobody found out. `network_runtime._on_receipt_posted` counts it and stops,
#: and no retry ladder hangs off it: a receipt that arrives after the moment it
#: describes is worth less than the request it costs, and ~1,000 badges retrying
#: one is the stampede the jitter exists to prevent, rebuilt.
TABLE_FLEET_RECEIPTS = "fleet_receipts"

# PostgREST's `Prefer` values, which are part of the wire shape rather than a
# preference. `resolution=merge-duplicates` is what makes a repeat badge_state
# post an idempotent UPDATE instead of a duplicate-key error; `return=minimal`
# keeps the response empty, which matters on a lane with an 8192-byte cap.
PREFER_MERGE_MINIMAL = "resolution=merge-duplicates,return=minimal"
PREFER_MINIMAL = "return=minimal"
# LIVE AGAIN, for ``fleet_receipts``. This was the historical direct-score shape
# and it sat here as a frozen literal with no consumer; the receipt insert is a
# real one. `resolution=ignore-duplicates` is what makes a receipt idempotent
# under its `(action_id, badge_id)` key: a badge that somehow posts twice for one
# action gets a no-op rather than a 409, which matters because `parse_response`
# maps 409 into the generic retryable bucket and a retryable receipt is exactly
# the fleet-wide retry storm the jitter exists to prevent.
PREFER_IGNORE_MINIMAL = "resolution=ignore-duplicates,return=minimal"

# Ack status vocabulary the badge_commands CHECK constraint accepts.
ACK_APPLIED = "applied"
ACK_FAILED = "failed"

# Server-side row cap the poll RPC is willing to hand back in one call.
MAX_COMMANDS = 32
DEFAULT_POLL_LIMIT = 16

# Response classes the host poll loop branches on.
OK = "ok"
NOT_FOUND = "not_found"        # authenticated, no target row -- NOT a rejection
UNAUTHENTICATED = "unauthenticated"   # 401 only; token invalid/expired
FORBIDDEN = "forbidden"        # 403; live grant denied / badge revoked
RATE_LIMITED = "rate_limited"  # 429; back off
MALFORMED = "malformed"        # truncated/tampered/oversize/unparseable body
TRANSIENT = "transient"        # 408/5xx/unknown; retry with backoff

# Status is authoritative for the auth verdict; 404 is deliberately NOT a
# rejection (adjudication rule above).
_STATUS_CLASS = {
    200: OK,
    201: OK,
    204: OK,
    401: UNAUTHENTICATED,
    403: FORBIDDEN,
    404: NOT_FOUND,
    408: TRANSIENT,
    429: RATE_LIMITED,
}


def rpc_path(name):
    """The origin-form path for one RPC, e.g. ``/rest/v1/rpc/<name>``."""

    return RPC_PREFIX + name


def table_path(table):
    """The origin-form path for one table, e.g. ``/rest/v1/badge_state``."""

    return REST_PREFIX + "/" + table


def rpc_headers(jwt, apikey, content_type=False, badge_id=None,
                device_token=None):
    """The authenticated PostgREST header set.

    ``apikey`` is the publishable key PostgREST requires on every request and
    ``jwt`` is the badge's bearer token. ``content_type`` is a request-shape
    flag, not a contract difference: the device module is POST-only and always
    sends a JSON body, while the host module also issues GETs and adds
    ``Content-Type`` only when there is a body. Returns a fresh dict the caller
    may mutate. No caller may log the result.

    ``badge_id`` IS THE FAIRNESS DIMENSION, not a credential -- see
    :data:`HEADER_BADGE_ID`. It is attached HERE, in the one function both the
    host lane and the device lane build their headers with, rather than at each
    call site: the header has to ride EVERY modifying PostgREST request or the
    shared-subject bucket is what limits that request, and "every" is a property
    a single funnel can hold and eleven call sites cannot. Absent, empty or
    not-a-string is simply omitted, because a malformed value would be refused by
    the server's own shape gate and the fallback (the shared bucket) is the same
    either way.
    """

    headers = {
        "apikey": apikey,
        "Authorization": "Bearer " + jwt,
        "Accept": "application/json",
    }
    if content_type:
        headers["Content-Type"] = "application/json"
    if isinstance(badge_id, str) and badge_id:
        headers[HEADER_BADGE_ID] = badge_id
    if isinstance(device_token, str) and device_token:
        # ADDITIVE, NEVER A REPLACEMENT. The shared JWT stays in `Authorization`
        # and the role stays `authenticated`; this rides alongside it, and RLS
        # resolves a badge id FROM it rather than from the token's subject. A
        # caller with no device token sends a byte-identical floor request.
        headers[HEADER_DEVICE_TOKEN] = device_token
    return headers


def poll_params(limit):
    """Argument object for ``badgelink_badge_poll``. Does not validate ``limit``.

    HISTORICAL on the shared-token path: this function's identity comes from
    ``whoami()``, which is the fleet's subject now. See :func:`poll_self_params`.
    """

    return {"p_limit": limit}


def ack_params(command_id, status, result):
    """Argument object for ``badgelink_badge_ack_command``. Does not validate.

    HISTORICAL on the shared-token path -- see :func:`ack_self_params`. Kept
    because the server keeps the function, and a badge on its own per-badge token
    still resolves it to its own rows.
    """

    return {"p_command_id": command_id, "p_status": status, "p_result": result}


def poll_self_params(limit, badge_id):
    """Argument object for ``badgelink_badge_poll_self``. Does not validate.

    ``p_badge_id`` is the PHYSICAL badge (``machine.unique_id().hex()``) and it
    is the queue key, not the authorization: the server gates on the shared
    subject's live ``commands/poll`` grant and validates only the id's SHAPE.
    Keys are frozen cross-lane; ``badgelink/tests/test_rpc_contract.py`` pins the
    exact set.
    """

    return {"p_badge_id": badge_id, "p_limit": limit}


def ack_self_params(command_id, status, result, badge_id):
    """Argument object for ``badgelink_badge_ack_command_self``. No validation.

    THE ACK IS WHY ``commands/ack`` IS A FLOOR GRANT. Without it a delivered
    command cannot be acked, so it stays ``delivered``, the next poll hands it
    back, and the doorbell re-rings -- a redelivery loop rather than a quiet
    failure. ``badge_id`` is last so the argument order of the historical
    :func:`ack_params` reads unchanged at the call sites that keep it.
    """

    return {"p_badge_id": badge_id, "p_command_id": command_id,
            "p_status": status, "p_result": result}


def score_submit_self_params(badge_id, game, score, play_number, metadata):
    """Argument object for ``badgelink_badge_submit_score_self``. No validation.

    ``p_badge_id`` is SELF-REPORTED and spoofable, which is an accepted trade for
    the fun tier: the authenticated function gates on the shared subject's live
    ``scores/write`` grant, auto-provisions the ``badges`` row so the FK holds,
    and bypasses RLS as ``postgres`` -- so it does NOT derive identity from
    ``whoami()`` and the badge still gains no ``scores`` SELECT.

    ``p_play_number`` REPLACED ``p_idempotency_key`` on 2026-08-29 and the
    parameter was RENAMED rather than added, which is why the migration drops and
    recreates the function instead of ``create or replace`` -- replace refuses to
    rename an input parameter. Retry safety is now the NATURAL key: the primary
    key is ``(badge_id, game, play_number, score)``, the insert is
    ``on conflict ... do nothing``, so re-posting the identical tuple returns
    success and creates no second row. That is the only guarantee the random
    handle ever provided.

    ``p_metadata`` IS SENT even though the server declares a default for it. The
    signature declares the argument, the ``scorebox`` plumbing already carries
    the value, and a body key the server does not declare is a PGRST202 -- so the
    safe direction is to match the declared signature exactly rather than to rely
    on a default.
    """

    return {
        "p_badge_id": badge_id,
        "p_game": game,
        "p_score": score,
        "p_play_number": play_number,
        "p_metadata": metadata,
    }


def schedule_current_v2_params(have_artifact_id=None):
    """Arguments for the public conditional whole-snapshot Schedule read.

    No cached artifact means the SQL default (``uuid default null``) is used by
    omitting the parameter. Validation stays in the Schedule model, which owns
    the UUID and outer/inner identity contract; this import-free wire module
    only fixes the exact parameter spelling shared with PostgREST.
    """

    if have_artifact_id is None:
        return {}
    return {"p_have_artifact_id": have_artifact_id}


# -- Phase-2 device-grant claim (OAuth device-authorization-grant shape) ------
#
# DISTINCT RPCs, NEVER EDITS TO THE P1 `pair_*` FAMILY, and the reason is the same
# one the `_self` family has: the shared floor gives every badge the SAME 16-hex
# subject, so `whoami()` resolves but COLLAPSES all badges onto one identity.
# These pass the physical UID explicitly as `p_badge_id` and prove possession with
# PKCE instead of deriving anything from the token.
#
# ⚠ **DRAFT-FROZEN, NOT DEPLOYED.** Phase 2 is held server-side; these names come
# from the reconciled wire contract (v2) and the badge-side hooks freeze now
# because the firmware is gang-cloned and cannot be changed afterwards. Nothing in
# this build CALLS them yet.
RPC_DEVICE_CLAIM_START = "badgelink_device_claim_start"
RPC_DEVICE_CLAIM_RETRIEVE = "badgelink_device_claim_retrieve"
# `badgelink_device_claim_vouch` is deliberately NOT here: it is called by the WEB
# app on an authenticated human's session, gated on `grants.user_id() IS NOT NULL`,
# which a 16-hex fleet subject can never satisfy. The badge never calls it, so it
# gets no firmware constant to be tempted by.


def device_claim_start_params(badge_id, code_challenge):
    """Args for ``badgelink_device_claim_start``. Does not validate.

    ``p_code_challenge`` is the S256 challenge -- lowercase hex of the verifier's
    SHA-256, which is the shape the deployed function's ``^[0-9a-f]{64}$`` check
    wants. The VERIFIER never appears in any argument object here; that is the
    whole PKCE guarantee, and it is why a photographed QR cannot retrieve a token.
    """

    return {"p_badge_id": badge_id, "p_code_challenge": code_challenge}


def device_claim_retrieve_params(device_code, code_verifier, badge_id):
    """Args for ``badgelink_device_claim_retrieve``. Does not validate.

    THE ONE PLACE THE VERIFIER CROSSES THE WIRE, and it crosses to the server that
    already holds its challenge -- over verified TLS, on the floor JWT, with no
    device token yet, because this call is what mints one.
    """

    return {"p_device_code": device_code,
            "p_code_verifier": code_verifier,
            "p_badge_id": badge_id}


def transport_policy_params():
    """Argument object for ``badgelink_badge_transport_policy``: none.

    THE ONE WHOAMI-KEYED READ THAT IS STILL CORRECT UNDER THE SHARED TOKEN, and
    it is correct for the reason the others are wrong: this read is FLEET-SCOPED
    on purpose. It answers "may push run, and at what cadence" for the venue, so
    a subject that names the whole fleet is exactly the right key -- collapsing
    800 badges onto one steering row is the FEATURE (an operator slows or
    silences the hall with one row). It is also read-only and fails open, so
    there is nothing here for a spoofed id to steer even if one were accepted.
    **Do not add ``p_badge_id``.**
    """

    return {}


def classify_status(status):
    """Map an HTTP status onto one response class.

    Unmapped statuses below 500 are MALFORMED (the response is not something
    this contract describes) and 500+ is TRANSIENT (retry after a backoff).
    """

    cls = _STATUS_CLASS.get(status)
    if cls is None:
        cls = TRANSIENT if status >= 500 else MALFORMED
    return cls


def is_rejected(status):
    """True only for 401 -- the single authentication-rejection oracle."""

    return status == 401
