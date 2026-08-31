"""BadgeLink P6 layer 3: the doorbell, and deliberately nothing else.

Layers 1 and 2 are DONE and are consumed, never forked: layer 1 is the bounded
WebSocket client in ``network/vendor/aiohttp``, layer 2 is the portable Phoenix
client in ``badgelink/badge/realtime``. This module is the thin, ours-only third
layer that hangs layer 2 off the product's polling pump.

WHAT A DOORBELL IS ALLOWED TO DO (docs/badgelink-transport-decision.md §0). One
thing: pull the next POLL forward. A broadcast on ``realtime:badge:<id>`` means
"go look", carries no data this module reads, acknowledges nothing, and cannot
change a delivery outcome. Correctness stays where P1 put it — durable
``badge_commands`` rows, an idempotency key, and the ack RPC — so every way push
can end (the wearer turns it off, the venue policy disables it, the demotion rule
fires, the socket dies, the AP goes away) degrades to exactly the polling
behaviour Card E already proved on hardware. That is not a fallback path bolted
on afterwards; it is the only path, and push merely shortens the wait.

WHY ``connect()`` HAS TWO COLD STRATEGIES. The OFF artifact keeps the ORIGINAL
blocking oracle: a named tolerant moment awaits the whole connect. The NB-0 ON
artifact -- which is what ships since the 2026-08-28 ruling -- uses that moment
only to START one explicitly owned task; later ordinary frame
pumps resume it at network-WANT boundaries. Device probes measured the one
certificate/crypto call that cannot yield at 820--903 ms, but the ~1.4 s Upgrade
read is waiting that can be spread across frames. ``step(tolerant=False)``
therefore never starts a socket, although under ON it can advance or reap the
single attempt a prior admission already owns.

THE INTRO, AND ANY OTHER GATE THAT STOPS SERVICING US (card obligation 7). The
supervisor's ``run(intro_update, duration=)`` gate quiesces engine tasks, and the
Card PW stock-``run`` pump has its own quiet windows (the one-frame deferral after
Settings turns the network on, and any app that blocks). A socket nobody services
for longer than the Realtime heartbeat ceiling is not a live socket, whatever the
driver says: the far end has already stopped hearing from us. So this module
tracks the gap since its last serviced step and, past
:data:`STARVATION_CEILING_MS`, closes and reconnects on jittered backoff instead
of assuming. The intro is explicitly NOT a tolerant moment; intro-end is.

DEFAULT ON, AUTOMATIC DEMOTION (owner scope addition, 2026-08-21). Push is
attempted whenever the network preference is ON. After
:data:`DEMOTE_AFTER_SESSIONS` consecutive WS sessions that never reached a JOIN,
the badge demotes to polling-only and STAYS there until a reboot or an explicit
re-enable from Settings, because a badge that cannot get a doorbell up in three
tries is on a network that will not give it one, and 800 badges retrying forever
is the herd the whole design is shaped around avoiding. A session that joined and
later dropped is NOT a failure for this counter: that is a healthy socket losing
its network, which polling already handles and which reconnect already spreads.

WHAT THIS MODULE MUST NOT DO, and does not. It imports no Badgeware, holds no
credential (a token arrives through ``token_provider``, a callable), logs no URL,
apikey, token or payload, and allocates nothing in the steady frame beyond what
layer 2's own single-frame read does. ``hashlib``/``ssl``/``fetch`` do not appear
here at all: the verified-TLS SSLContext is built by the caller and injected as
part of ``ws_connect``, so there is exactly one trust path on the badge and this
file cannot fork it.
"""

import asyncio


try:  # MicroPython
    from time import ticks_add as _ticks_add
    from time import ticks_diff as _ticks_diff
    from time import ticks_ms as _ticks_ms
except ImportError:  # CPython, for the host test lane
    from time import monotonic as _monotonic

    def _ticks_ms():
        return int(_monotonic() * 1000)

    def _ticks_add(value, delta):
        return value + delta

    def _ticks_diff(later, earlier):
        return later - earlier


# -- the live mode a Settings screen reads back ------------------------------
#
# Read from the transport, never from the last button press (Card PW's binding
# rule). Every literal below is a fact about this boot, not an intention.

#: The network preference is OFF, so there is no session at all to push over.
MODE_NETWORK_OFF = "network_off"
#: Push is turned off locally: the wearer chose polling-only from Settings.
MODE_POLLING = "polling"
#: Push is wanted and the socket is not carrying a joined channel yet.
MODE_TRYING = "trying"
#: A channel is JOINED: the doorbell is live.
MODE_PUSH = "push"
#: DEMOTE_AFTER_SESSIONS consecutive sessions failed to join. Sticky for this
#: boot unless Settings re-enables it explicitly.
MODE_DEMOTED = "demoted"
#: The server's transport policy disabled push for this badge or the fleet.
MODE_BLOCKED = "blocked"

MODES = (
    MODE_NETWORK_OFF,
    MODE_POLLING,
    MODE_TRYING,
    MODE_PUSH,
    MODE_DEMOTED,
    MODE_BLOCKED,
)


# Layer 2's event kinds, spelled here rather than imported. ``realtime`` is a
# PACKAGE under ``/system/lib`` while this module installs flat beside
# ``polltransport``, and a module-scope import of a package that a half-refreshed
# ``/system/lib`` might not carry raises inside ``launch()`` — which resets the
# badge (docs/deploy.md). ``badgelink/tests/test_pushlink.py`` asserts every
# literal below against the real ``realtime.client`` constant, so a renamed kind
# fails the fast lane instead of silently never ringing a doorbell.
#: LAYER 2's OWN JOIN-TIMEOUT REASON, spelled here for the reason every `KIND_*`
#: literal above is: `realtime` is a PACKAGE under `/system/lib` and this module
#: installs flat beside it, so a module-scope import of it is a boot the badge
#: may not survive. `badgelink/tests/test_pushlink.py` asserts this against the
#: real string in `realtime/client.py`, so a rename fails the fast lane instead
#: of silently un-counting the state below.
JOIN_TIMEOUT_REASON = "join timed out"

#: HOW MANY UNANSWERED JOINS ON ONE SOCKET BEFORE IT IS DROPPED.
#:
#: ⚠ **THE §3a TRAP, ON THE ROUTE NOBODY WAS WATCHING.** A join the server never
#: ANSWERS is not a refusal: layer 2 fires `channel_error reason="join timed out"`
#: after its own 10 s deadline and reschedules a rejoin on a 1 s -> 30 s backoff.
#: That is right for a blip and wrong forever -- the socket stays open, `joined`
#: stays False, `failed_sessions` never moves, and the badge reads "Connecting"
#: for as long as the venue stays silent while sending a fresh `phx_join` every
#: ≤30 s. Across the fleet that is ~800 x 1/30 s = **~27 joins a second,
#: permanently, with no recovery signal and a panel that lies.**
#:
#: THREE, and dropping the socket is now SAFE IN A WAY IT WAS NOT BEFORE. The
#: close feeds the ordinary never-joined accounting, so three such sockets demote
#: -- and since 2026-08-26 a demotion is not terminal: the slow bounded re-arm
#: tries again every 15-30 minutes. So the fleet cost falls from ~27/s to
#: ~0.67/s and the badge still recovers by itself. Before that re-arm existed,
#: demoting here would have traded a permanent load for a permanent silence,
#: which is why the endless rejoin was the better of the two.
#:
#: A SESSION THAT ALREADY JOINED IS NOT PUNISHED FOR IT. `_close_session` only
#: charges the demotion counter for a session that never joined, so a healthy
#: socket whose REJOIN times out is closed and reconnected -- a fresh TLS and a
#: fresh join instead of an endless rejoin on a stale one -- without moving the
#: counter at all.
JOIN_TIMEOUT_LIMIT = 3

KIND_BROADCAST = "broadcast"
KIND_JOINED = "joined"
KIND_DISCONNECTED = "disconnected"
KIND_JOIN_ERROR = "join_error"
KIND_CHANNEL_ERROR = "channel_error"


# -- the ring filter (CX-9) --------------------------------------------------
#
# THE ONE BROADCAST THE SERVER SENDS TODAY, and the two facts that make filtering
# it safe. `grants.broadcast_command_status` fires `after insert or update of
# status on public.badge_commands` and drops an update that leaves the status
# alone, so one command's `queued -> delivered -> applied` is THREE broadcasts on
# `'badge:' || new.badge_id` -- the badge's OWN private topic, which is the topic
# this module joins. The badge therefore receives the broadcast its own ack
# caused, and before this filter it treated all three as "go look".
#
# ONLY `queued` IS NEWS. `delivered` is set by this badge's own poll and
# `applied`/`failed` by its own ack, so both arrive after the exchange that
# produced them; `cancelled` is an owner action on a row the badge is not going to
# be given. None of the four is a reason to pull a poll forward.
#
# EVERY LITERAL BELOW IS THE PRODUCER'S. The event name and the payload keys come
# from the `jsonb_build_object` in `badgelink/supabase/schemas/badgelink.sql`
# (~:708-730) and the statuses from `badge_commands.status`'s own CHECK
# (`status in ('queued', 'delivered', 'applied', 'failed', 'cancelled')`);
# `badgelink/tests/test_cx9_status_rings.py` asserts both against the schema file
# so a server-side rename fails a test instead of silently suppressing a ring.
BROADCAST_COMMAND_STATUS = "command_status"

#: The status that means "there is something to fetch". The ONLY one.
STATUS_QUEUED = "queued"

#: The statuses a ring may be suppressed for, spelled out rather than derived as
#: "not queued". THE DIRECTION MATTERS: an unknown FUTURE status must RING, and
#: `not queued` would silence it. Suppression is the dangerous half of this fix --
#: a ring the badge did not need costs one poll, a ring it needed and did not get
#: costs a command that waits out the 30 s idle cadence -- so anything this list
#: does not name falls through to ringing.
STATUS_QUIET = ("delivered", "applied", "failed", "cancelled")

#: THE PRODUCER'S WHOLE PAYLOAD, and a quiet arrival has to match ALL of it.
#:
#: The five keys and their order are the `jsonb_build_object` in
#: `badgelink/supabase/schemas/badgelink.sql` (~:721-727), and the types are the
#: columns it reads: `command_id` is `badge_commands.id`, a uuid, so a JSON
#: string; `badge_id` is `text` and it is THIS badge's on every message worth
#: quieting, because the badge's own poll and its own ack are what caused them;
#: `delivery_attempts` is an integer; `at` is `coalesce(applied_at, delivered_at,
#: created_at)`, a timestamp, so a JSON string.
#:
#: WHY THE WHOLE SHAPE AND NOT JUST THE STATUS. Checking the event name, that the
#: payload is a mapping and that `status` is a non-empty string is what this
#: filter did until 2026-08-23, and it silenced `{"status": "applied"}` -- three
#: fields short, from no badge in particular. Suppression is the direction that
#: breaks a wearer's badge, so the recognised shape is the narrow one: anything
#: this build cannot positively identify as the producer's own echo RINGS, and
#: the cost of that mistake is one poll.
BROADCAST_PAYLOAD_KEYS = ("command_id", "badge_id", "status",
                          "delivery_attempts", "at")

#: Phoenix's wire namespace plus the server's own sub-topic, spelled ONCE. See
#: :func:`badge_topic` and its inverse :func:`topic_badge_id`.
TOPIC_PREFIX = "realtime:badge:"

#: THE FLEET NAMESPACE, and it is the topic the shared-token firmware actually
#: joins. `grants.can_access_channel` authorizes `^event:[A-Za-z0-9][A-Za-z0-9
#: ._:-]{0,127}$` for READ to any identity holding `realtime/read`
#: (`badgelink/supabase/schemas/badgelink.sql:642-653`), which the shared floor
#: subject has. Under the shared JWT all 800 badges carry the SAME `sub`, so
#: `badge:<sub>` collapses onto one private topic that names no badge in
#: particular -- joining it would be a channel and a handshake spent on nothing.
EVENT_TOPIC_PREFIX = "realtime:event:"

#: The one fleet event this firmware joins. FROZEN with the server publisher:
#: `grants.broadcast_doorbell_ring` sends event `doorbell` on topic
#: `event:doorbell` from an AFTER INSERT trigger on `badge_commands` gated
#: `when (new.status = 'queued')`
#: (`badgelink/supabase/migrations/20260826050815_badgelink_doorbell_ring.sql`).
#: A separate trigger and not an extension of `broadcast_command_status`, which
#: also fires on the delivered/applied transitions this badge's own poll and ack
#: cause -- extending it would re-ring the whole fleet for one command.
EVENT_DOORBELL_NAME = "doorbell"

#: THE FLEET PAYLOAD KEY THAT ADDRESSES THE HINT. The legacy per-row publisher
#: names one physical badge; the fleet_actions publisher names either one
#: physical badge or the explicit ``all`` sentinel below. It is ADDRESSING, never
#: authority: RLS on `realtime.messages` already decided who may hear this.
FLEET_TARGET_KEY = "badge_id"

#: RESERVED TARGET, not a wildcard convention. A hardware id is exactly 16
#: lowercase hex characters, so this word cannot collide with one; every near
#: miss (``*``, null, uppercase, whitespace) stays silent.
RELIABLE_ALL_TARGET = "all"

#: -- THE BROADCAST ENVELOPE (2026-08-29) ------------------------------------
#:
#: WHAT EACH KEY IS FOR:
#:
#:   ``id``           the same value as ``action_id`` -- see below
#:   ``badge_id``     16 lowercase hex, or the ``all`` sentinel. ADDRESSING.
#:   ``action_id``    the `fleet_actions` row id, canonical UUID text. It is
#:                    also `fleet_receipts.action_id`, which is how a badge's
#:                    write-back names what it answered without the server
#:                    having to correlate anything.
#:   ``action_type``  the verb. A non-empty string here and NOTHING MORE; the
#:                    vocabulary belongs to `network_runtime._apply`, which is
#:                    the one place it is already spelled.
#:   ``payload``      the verb's arguments, an object or array. Opaque here;
#:                    ``play_effect`` is always an array of effect objects and
#:                    the runtime owns that verb-specific rule.
#:   ``at``           when the action was published. Non-empty text.
#:
#: ⚠ **THE DOORBELL IS A COURIER NOW, AND THIS TUPLE IS THE WHOLE CONTRACT.**
#: Until today a broadcast was read for ONE BIT -- "is this news?" -- and the
#: durable `badge_commands` row was the courier. That queue is deleted (the
#: rebuild commit `928d53f7`: moments are broadcast, states are polled), so
#: there is nothing behind a ring to recover it and the payload has to carry the
#: moment itself. The cost of that is exactly what this key set defends against:
#: a payload this badge cannot positively identify is no longer one wasted
#: request, it is a light show nobody chose.
#:
#: **`id` IS IN THE SET BECAUSE THE SERVER PUTS IT THERE WHETHER WE WANT IT OR
#: NOT.** `realtime.send` injects an `id` key into any payload lacking one, and
#: that is precisely how the per-command doorbell broke: it emitted
#: ``{at, badge_id, command_id, kind}``, arrived as
#: ``{at, badge_id, command_id, id, kind}``, missed this exact-key filter, and
#: was dropped -- 595 of 598 broadcasts, silently, fleet-wide
#: (`docs/design/badge-schema-rebuild-2026-08-28.md` §3). The publisher must
#: therefore set ``id`` ITSELF, to the action id, so the injection is a no-op.
#: The ``id == action_id`` clause in `_reliable_doorbell_payload` is what makes
#: forgetting that loud instead of silent.
#:
#: **THE WORD `kind` IS GONE FROM THE ENVELOPE AND ITS ABSENCE IS DELIBERATE.**
#: It carried the constant string ``"command"``, which said nothing a doorbell
#: payload on this topic did not already say, and it COLLIDED head-on with
#: `effect_library`'s own ``kind`` (``"glyph"``/``"lights"``) which now travels
#: INSIDE ``payload``. Two meanings of one word in one payload is how a
#: validator gets written against the wrong one.
#:
#: **THE BADGE AND THE PUBLISHER MUST LAND TOGETHER.** An exact key set the
#: server does not emit is total, silent, fleet-wide loss that looks like a quiet
#: event -- that is the 595/598 bug -- and relaxing the exactness to hedge just
#: trades silence for ~1,000 badges rendering a guess. Neither is acceptable, so
#: this tuple is pinned by `badgelink/tests/test_fleet_doorbell.py` on this side
#: and must be pinned against the trigger on the other.
RELIABLE_DOORBELL_KEYS = ("id", "badge_id", "action_id", "action_type",
                          "payload", "at")

#: Spelled separately because three lanes read them: this validator, the receipt
#: `network_runtime` posts, and the console that joins the two.
ACTION_ID_KEY = "action_id"
ACTION_TYPE_KEY = "action_type"
ACTION_PAYLOAD_KEY = "payload"

#: THE VERB'S LENGTH BOUND. 32, against a longest live verb of fourteen
#: characters (``set_caselights``, ``set_networking``), so it refuses nothing
#: this fleet can say and is not a limit anyone will meet.
#:
#: IT IS HERE BECAUSE THIS STRING TRAVELS FURTHER THAN THE VALIDATOR. It reaches
#: `network_runtime._apply`'s dispatch and it reaches the event sink, which on a
#: tethered badge is a serial console an operator is reading the event by --
#: server-supplied text with no length of its own is the one thing on that line
#: that could push everything else off it. Bounding it HERE rather than at either
#: consumer is the same argument the rest of this function makes: a shape the
#: badge cannot positively identify should stop at the boundary, once.
MAX_ACTION_TYPE = 32

#: Canonical Postgres UUID text and physical-id alphabets. Spelled locally so a
#: half-refreshed flat `/system/lib` never has to import a sibling merely to
#: validate a broadcast on the rendered-frame path.
LOWER_HEX = "0123456789abcdef"
UUID_TEXT_LEN = 36
UUID_HYPHENS = (8, 13, 18, 23)


# -- tolerant moments --------------------------------------------------------
#
# Named so an event log says WHICH tolerant moment paid for a handshake, and so
# a caller cannot pass "now is fine" without saying why.

MOMENT_SESSION_START = "session_start"
MOMENT_VIEW_TRANSITION = "view_transition"
MOMENT_CONNECTING_SCREEN = "connecting_screen"
MOMENT_INTRO_COMPLETE = "intro_complete"
#: A SCHEDULED RECONNECT whose jittered backoff has run out, taken in whatever
#: frame is next. This is a deliberate, bounded departure from the strict reading
#: of "never inside a normal frame", and the reason is that the strict reading
#: does not survive contact with a badge left on the launcher: the four moments
#: above are all things a WEARER causes, and a badge sitting in the menu causes
#: none of them, so a first connect that failed would never be retried and push
#: would simply never come up. What bounds it: the jittered ``BackoffPolicy``
#: bounds the RATE, ``DEMOTE_AFTER_SESSIONS`` bounds the COUNT per boot at three,
#: and the card's own frame gate counts handshake frames rather than excluding
#: them ("handshake/reconnect moments included and bounded"). The moment is named
#: separately so a serial log says which kind of moment paid for a stall.
MOMENT_RECONNECT_DUE = "reconnect_due"
TOLERANT_MOMENTS = (
    MOMENT_SESSION_START,
    MOMENT_VIEW_TRANSITION,
    MOMENT_CONNECTING_SCREEN,
    MOMENT_INTRO_COMPLETE,
    MOMENT_RECONNECT_DUE,
)


#: Consecutive never-joined WS sessions before the badge gives up on push for
#: this boot. THREE, chosen for the herd and not for one badge: the jittered
#: schedule spends roughly 1 s + 2 s + 4 s of *base* delay getting here, so a
#: transient venue fault still gets three real chances inside about ten seconds,
#: while a systematic one (no WSS egress, a saturated Realtime shard, a captive
#: portal) stops costing 800 badges a handshake apiece within the first minute
#: of the event. Two would demote a badge that hit one bad AP association; four
#: buys a fourth attempt whose prior probability of success, given three
#: failures on the same network, is not worth 800 TLS handshakes.
DEMOTE_AFTER_SESSIONS = 3

#: A socket nobody has serviced for this long is treated as gone rather than
#: live. 25,000 ms is the Realtime heartbeat CEILING (layer 2 refuses a larger
#: interval), so a gap this size means the far end may already have dropped us —
#: card obligation 7(c), and it is the reason an intro longer than the ceiling
#: reconnects instead of assuming.
STARVATION_CEILING_MS = 25000

#: How often the badge forces a fresh socket and private-channel join. Realtime
#: calculates private-channel authorization when the channel is joined; the real
#: D9 run proved that re-pushing the same valid long-lived ``access_token`` on
#: an already joined channel does NOT make the hosted service re-read a revoked
#: grant. This cadence — not the poll cadence — is therefore the badge's own
#: contribution to the revocation bound: at worst one interval passes between a
#: grant being revoked and this badge presenting a fresh join.
#:
#: **ONE HOUR, BY OWNER RULING 2026-08-24, and the words were:** *"can we change
#: this to like once per hour or something? secure enough, no major network
#: refactor. less freezes."* It was ten minutes from 2026-08-22 until then.
#: Recorded in full as `OWNER-DECISIONS #20`; the MECHANISM did not change and
#: must not (fresh join on cadence, refused join = terminal revoked for the boot,
#: jitter mandatory) — only this interval and its jitter did.
#:
#: **WHAT THE INTERVAL COSTS A WEARER, which is what the ruling bought.** The
#: only tolerant moment a badge sitting on the launcher ever reaches is
#: ``MOMENT_RECONNECT_DUE``, i.e. an ORDINARY rendered frame, so every cadence
#: close is paid for by one frame that carries a full TLS connect and a fresh
#: ``phx_join``: **945 ms, measured** (`ft_b_frame_cost.mjs --arm
#: reconnect-cadence`, after CX-3 took the lookup out of it). At ten minutes that
#: is ~6 such frames an hour, for the life of every boot; at one hour it is one.
#:
#: **WHAT THE INTERVAL COSTS IN SECURITY, stated as a bound and not as a
#: reassurance.** The push-side revocation bound becomes **~60-72 minutes plus
#: the latency of the next tolerant moment** — see :data:`REJOIN_JITTER_MS` for
#: the range and `docs/badgelink-identity-and-security-model.md` §5/§9 for the
#: doc-level restatement. Three hardware-measured facts are what make that
#: acceptable rather than merely cheaper, and none of them is an inference:
#:
#: * **The ACTION kill is the poll transport's 403, and it is instant.** Grant
#:   revocation takes effect on the badge's next Data API statement (P1, hosted);
#:   `PollLoop` then enters :data:`polltransport.REVOKED`, closes the socket and
#:   performs no further open or poll for the boot (owner ruling 2026-08-19). A
#:   revoked badge therefore stops fetching commands, stops acking and stops
#:   reporting state within one poll — ≤30 s idle, 3-5 s active — whatever this
#:   cadence says.
#: * **What the surviving socket can still deliver is the badge's OWN status
#:   metadata.** The only topic this client joins is ``badge:<its own 16-hex
#:   uid>``; `grants.can_access_channel` refuses any other, and RLS on
#:   ``realtime.messages`` is what refuses it. The payload is
#:   `grants.broadcast_command_status`'s five fields — ``command_id``,
#:   ``badge_id``, ``status``, ``delivery_attempts``, ``at`` — about commands
#:   addressed to this badge. That is low-sensitivity metadata a revoked badge
#:   receives about itself, and this client never PUBLISHES: it sends
#:   ``phx_join``, heartbeats, pings and ``access_token`` frames and nothing
#:   else.
#: * **A doorbell that rings a revoked badge used to buy the server a 403, not
#:   an action.** `pull_forward` only moved the next poll earlier, and that poll
#:   was the statement revocation was already immediate on. D9 measured the
#:   shape on glass: post-refusal HTTP delivery with no broadcast, and the
#:   restored Broadcast and durable ack afterwards.
#:
#:   ⚠ **THAT IS NO LONGER TRUE, AND THE RULING SURVIVES ANYWAY.** Since
#:   2026-08-29 a broadcast carries the action itself, so a badge whose HTTP
#:   grant was revoked but whose WS session is still open WILL play the effect --
#:   locally, with no request for the server to refuse. What that costs is
#:   bounded by what it is: a light show on a badge in the room, for as long as
#:   one socket outlives one revocation. Under the owner's settled threat model
#:   (`AGENTS.md`, 2026-08-28: ~1,000 badges, one shared token, attribution
#:   self-reported, "it could be a random ID for all we care") that is not a
#:   boundary worth a mechanism. The RECEIPT is still refused, so the console
#:   still sees the badge stop answering.
#:
#: **AND THE ADVERSARIAL BOUND DOES NOT MOVE AT ALL, which is the honest reason
#: this is a cheap ruling.** Realtime's authorization cache is per-connection, so
#: the cadence bounds only a COMPLIANT client's socket. A hostile client holding
#: an extracted token simply never rejoins, so its window was already unbounded
#: before this change and is unbounded after it; the remedies for that case are
#: the Data API 403 (immediate) and key rotation (§7 / OWNER-DECISIONS #7, #17),
#: never this number. Lengthening it extends how long a revoked but HONEST badge
#: keeps hearing its own echoes, and nothing else.
TOKEN_REFRESH_MS = 3600000

#: THE CADENCE JITTER, and the reason the boot jitter is not enough on its own.
#:
#: The boot jitter spreads the FIRST connect of each boot over 20 s, and this
#: cadence's phase is that connect — so without a second draw, 800 badges spend
#: the whole boot reconnecting inside the same 20 s window, once every ten
#: minutes, forever. That is ~40 TLS handshakes and ~40 `phx_join`s per second in
#: a repeating burst, against a per-tenant join rate limit that answers
#: `ClientJoinRateLimitReached: Too many joins per second` and then DISCONNECTS
#: the socket it refused (`realtime_channel.ex:184-187`). The boot jitter was
#: priced as a one-time event; turning it into a standing rhythm is a different
#: claim, and it does not decorrelate on its own: each cycle adds exactly one
#: interval, so the phase survives the whole boot with only handshake-duration
#: variance to spread it.
#:
#: So the interval is redrawn EVERY session from ``[TOKEN_REFRESH_MS,
#: TOKEN_REFRESH_MS + REJOIN_JITTER_MS)``, per badge, like the ring jitter and
#: unlike the boot jitter.
#:
#: **TWELVE MINUTES, SCALED PROPORTIONALLY WITH THE HOURLY INTERVAL (2026-08-24,
#: OWNER-DECISIONS #20).** It was two minutes against a ten-minute interval, and
#: the scaling is deliberately the plain ratio — 2/10 = 12/60 — because every
#: property this constant is chosen for is a RATIO and a proportional scale is
#: the only change that preserves all of them at once:
#:
#: * **The phase walk still dominates the boot formation, by more than before.**
#:   Two minutes was 6x the 20 s window the boot jitter leaves behind; twelve
#:   minutes is **36x** it. That is the property that lets the phase random-walk
#:   apart instead of holding formation, and scaling the interval without scaling
#:   the jitter would have shrunk it to 6x of a formation that now recurs six
#:   times less often — the wrong direction for the only thing this constant does.
#: * **It stays a quarter of the interval**, so the honest worst-case revocation
#:   bound is not dominated by the spread: 720,000 ≤ 3,600,000 // 4, exactly as
#:   120,000 ≤ 600,000 // 4. `test_the_window_is_wide_enough_to_break_the_boot_formation`
#:   pins both halves.
#: * **The standing fleet rate falls with the interval and the spread widens with
#:   it.** 800 badges over a 720 s window is ~1.11 joins/second average against
#:   ~6.67/s over the old 120 s window, and over a conference day the fleet
#:   converges on ~0.22 joins/second (800 badges / 3,600 s) against the old ~1.3,
#:   rather than the ~40/s burst an unjittered cadence produces against a
#:   per-tenant join rate limit that answers `ClientJoinRateLimitReached: Too many
#:   joins per second` and then DISCONNECTS the socket it refused. The busiest
#:   one-second bucket over 800 badges is measured, not asserted, by
#:   `test_pushlink.FleetCadenceSpreadTests`, which follows
#:   `test_cx8_boot_cadence.FleetSpreadTests`' patterns and keeps the unjittered
#:   cadence as its oracle.
#:
#: The cost is that the revocation bound is a RANGE, not a single number: worst
#: case ``TOKEN_REFRESH_MS + REJOIN_JITTER_MS`` — **72 minutes** — plus the
#: latency of the next tolerant moment. That is the honest bound, and it is the
#: one the docs quote.
REJOIN_JITTER_MS = 720000

#: THE SLOW RE-ARM AFTER A NEVER-JOINED DEMOTION. 15-30 minutes, jittered per
#: badge, and it is what makes "never give up until reboot" true rather than
#: aspirational.
#:
#: THE RULE IT IMPLEMENTS: *"a badge parked on a nametag reconnects after hours."*
#: `DEMOTE_AFTER_SESSIONS` bounds the FAST attempts at three, and until now that
#: was also the end of push for the boot -- `demoted` is RAM-only, so the only
#: escapes were a reboot or a Settings press. That is wrong for the case it was
#: built for: three failures inside the first ten seconds of a boot say the
#: badge's network is bad NOW, not that it will be bad in an hour, and the
#: wearer who carries it into a working room gets nothing.
#:
#: WHY IT IS SLOW RATHER THAN BACKED OFF. The herd is the whole reason a
#: demotion exists. 800 badges probing once per ~20 minutes is **0.67
#: handshakes/second fleet-wide** -- against the ~27 requests/second the 30 s
#: idle poll already costs, it is noise. The same fleet on a 30-second retry
#: would be 27/second of pure TLS on a venue that has already refused it three
#: times. So the interval is picked for the WORST case (a systematic outage, all
#: 800 probing forever) rather than the best one, and the cost of that choice is
#: paid by a single badge waiting up to half an hour -- against polling, which
#: is already carrying the event.
#:
#: PER-BADGE JITTERED, redrawn on every arm, for the reason the ring jitter is:
#: a fixed interval puts the same 800 badges back in the same order at the same
#: spacing forever, and a demotion is a CORRELATED event (one venue refuses the
#: whole hall at once).
REDEMOTE_RETRY_MIN_MS = 15 * 60 * 1000
REDEMOTE_RETRY_MAX_MS = 30 * 60 * 1000

#: THE SAME RE-ARM FOR AN UNANSWERED VENUE, AND IT IS MUCH SHORTER. 3-5 minutes.
#:
#: **TWO DEMOTIONS WITH DIFFERENT BASE RATES MUST NOT SHARE ONE TIMER**, which is
#: the whole reason this constant exists. The 15-30 minute window above was chosen
#: for a never-joined AUTHORIZATION REFUSAL -- a server saying no, which stays no
#: until somebody changes something server-side, so waiting out a long interval
#: costs nothing. A join the venue never ANSWERS is a different fact with a
#: different half-life: silence clears in seconds when an AP finishes booting,
#: rebalancing or being reconfigured.
#:
#: THE CASE THAT DECIDES THE NUMBER is the event's opening window -- an AP being
#: configured or saturated at exactly the hour ~800 badges cold-boot into it, and
#: exactly when somebody is watching a console for green joins. Routing silence
#: into the long window would cost every badge up to half an hour of no doorbell
#: for a 30-second blip.
#:
#: AND THE HERD ARGUMENT STILL WINS OVERWHELMINGLY AT THIS INTERVAL: 800 badges at
#: one attempt per 3-5 minutes is ~3-4 joins/second against the ~27/second an
#: unbounded rejoin produces -- a 7-9x reduction rather than 40x, for a recovery
#: measured in minutes instead of half an hour. Erring SHORT is deliberate: the
#: fleet cost of a 3-minute re-arm is affordable and the product cost of a
#: 30-minute one during the opening hour is not.
UNANSWERED_RETRY_MIN_MS = 3 * 60 * 1000
UNANSWERED_RETRY_MAX_MS = 5 * 60 * 1000

#: WHY THIS BADGE IS DEMOTED, as a bounded word. Kept in the state even though the
#: two causes could share a timer, because undistinguishable causes behind one
#: number is exactly how the 5,000 ms open budget ended up with a justification
#: that measured a different code path -- and because it is what lets the
#: intervals above be retuned later without re-deriving which demotion happened.
DEMOTE_CAUSE_REFUSED = "refused"
DEMOTE_CAUSE_UNANSWERED = "unanswered"
DEMOTE_CAUSE_UNREACHABLE = "unreachable"

#: The close reason `step()` uses for a bounded run of unanswered joins, and the
#: key that selects the short re-arm above.
CLOSE_JOIN_UNANSWERED = "join_unanswered"
#: The close reason for a never-joined authorization refusal.
CLOSE_JOIN_REFUSED = "join_refused"

#: THE SERVER'S ERROR CODE FOR A REFUSED PRIVATE JOIN, and the only part of a
#: refusal reason this module is willing to act on.
#:
#: Realtime answers a join it will not authorize with
#: ``{:error, %{reason: "Unauthorized: You do not have permissions to read from
#: this Channel topic: badge:<16 hex>"}}``. The prefix is not prose: `join/3`'s
#: else-branch calls ``log_error(socket, "Unauthorized", msg)``
#: (``realtime_channel.ex:174-175`` at pin ``833cf36c``) and
#: ``realtime_channel/logging.ex:21-25`` renders that as ``"#{code}: #{msg}"``,
#: so the CODE is the machine-readable field and the sentence after it is
#: human-facing detail that may be reworded upstream at any time.
#:
#: Matching the code and not the sentence is what keeps this from being either
#: brittle or over-broad. The refusals that are NOT this — `ChannelRateLimitReached`,
#: `ClientJoinRateLimitReached`, `Realtime was unable to connect to the project
#: database`, a join timeout — are transient server conditions, and treating one
#: of them as a revocation would stop a healthy badge's doorbell for a whole boot
#: over a database blip. They keep layer 2's ordinary jittered channel rejoin.
REVOCATION_REASON_CODE = "Unauthorized"

#: WHICH EMITTER A `revoked` LINE CAME FROM (2026-08-24), the doorbell's word.
#: TWO TRANSPORTS REACH A TERMINAL INDEPENDENTLY and that is the design, not a
#: duplicate: this object hears a refused rejoin on its own socket, the poll
#: transport hears a 403 on its own exchange, and neither waits for the other. So
#: a boot can legitimately print more than one `event=revoked`, and `source=` is
#: how a reader tells whose it is. `polltransport.SOURCE_POLL` carries the whole
#: note; the rule is one per SOURCE, and a repeated source is the failure.
SOURCE_PUSH = "push"

#: How long before a JWT's ``exp`` the client forces reauthorization rather than
#: riding a token it knows is about to die. Five minutes, comfortably more than
#: one refresh interval's worth of clock error.
TOKEN_EXPIRY_MARGIN_MS = 300000

#: How long before a grant row's ``expires_at`` the client forces
#: reauthorization. Card item 4b makes this mandatory *where a real expiry is
#: present*: long-lived grants are the norm since OWNER-DECISIONS #14, and a
#: grant with no expiry simply never triggers this.
GRANT_EXPIRY_MARGIN_MS = 60000

#: THE BOOT-TIME JITTER DECISION (review item 6). Every HOME press is a
#: ``machine.reset()``, so the reconnect schedule does not survive it — nothing
#: about the exponential backoff a badge earned before the reset carries over,
#: and it must not: the backoff describes a session that no longer exists.
#: What DOES carry over is the correlation. A hall-wide event — a talk ending, an
#: announcement, a keynote letting out — presses HOME on hundreds of badges
#: inside a few seconds, and every one of them then boots, associates and wants a
#: WebSocket at the same instant with a freshly-zeroed backoff that cannot spread
#: anything. So the FIRST connect of every boot waits a full-jitter delay drawn
#: from ``[0, BOOT_JITTER_MS)``, redrawn on each boot because it is RAM-only.
#:
#: TWENTY SECONDS, and the number is the herd: 800 badges spread over 20 s is
#: ~40 joins/second instead of 800 at once, and it costs the doorbell at most
#: 20 s on a boot where polling is already the authority and where the badge was
#: unreachable for a measured 4-8 s anyway (transport memo §1). Association
#: itself contributes 3.2-4.8 s of natural spread; this adds the part association
#: cannot, which is the TLS handshake and the Phoenix join.
BOOT_JITTER_MS = 20000

#: THE RING JITTER (Card FT-B item 3): how long a doorbell-driven poll waits.
#:
#: THE CARD ASKED FOR THIS ON "FLEET-SCOPED" RINGS AND THE BADGE CANNOT SEE THE
#: SCOPE. That is worth stating plainly rather than papering over, because the
#: conclusion is the opposite of the obvious one.
#:
#: A fleet command is not one broadcast to many badges. ``badge_commands`` rows
#: are addressed to ONE ``badge_id`` each, and ``grants.broadcast_command_status``
#: publishes to ``'badge:' || new.badge_id`` -- so an 800-badge light show is 800
#: rows in one statement and 800 broadcasts, each on its OWN private topic. Every
#: badge sees exactly one ring, on the only topic it subscribes to, carrying no
#: scope field. **There is no signal to classify.** A per-badge ring from an
#: operator pressing "find this badge" is byte-identical to one of 800.
#:
#: So the jitter applies to EVERY doorbell ring, and the trade is priced rather
#: than assumed:
#:
#: * WITHOUT it, 800 badges poll inside the broadcast fan-out window -- call it
#:   50-200 ms -- which is 4,000-16,000 requests/second against the ~27/second
#:   the 30 s idle cadence already costs.
#: * WITH it, they spread over a 1 s window: ~800/second peak, a 5-20x
#:   reduction, for ONE second.
#: * THE COST IS PAID BY THE SINGLE-BADGE CASE, and it is small: the doorbell's
#:   whole value is turning a ≤30 s wait into a short one, and 1-2 s is still
#:   15-30x better than the cadence. `execute_at` is what synchronizes a visible
#:   moment; the ring only decides when the badge goes to LOOK, and nobody is
#:   watching that.
#:
#: ⚠ **THE PARAGRAPH ABOVE DESCRIBES THE PER-BADGE-TOKEN WORLD AND IT IS HISTORY
#: SINCE 2026-08-26.** It is kept because the arithmetic is still the argument for
#: the numbers; what changed is which half of the trade the badge is on. The
#: server now DOES publish one shared broadcast to `event:doorbell` (one row, one
#: publish, 800 subscribers) instead of 800 private ones, so:
#:
#: * THE SCOPE IS NOW LEGIBLE, but not from the topic -- every badge sees every
#:   fleet ring on the same topic. It is legible from the PAYLOAD's `badge_id`,
#:   which names one physical badge or the explicit ``all`` sentinel, and
#:   :meth:`PushLink._fleet_action_for_me` validates the complete producer shape.
#:   So the filter, not the jitter, is what keeps a targeted ring cheap: the
#:   other badges suppress it before anything is acted on.
#: * THE JITTER STILL APPLIES TO EVERY RING THIS LINK DELIVERS, and it has to.
#:   The filter bounds the badges that ring for ONE command; it does nothing for
#:   an owner queueing a row per badge in one statement, which is 800 rings that
#:   each pass their own badge's filter inside the fan-out window. That is the
#:   original herd, unchanged, and this jitter is still the only thing that
#:   spreads it -- see :meth:`PushLink.ring_scope`, which classifies the fleet
#:   primary as fleet EVEN FOR AN UNTOPICED FRAME so the 0 ms shortcut below can
#:   never be reached on a shared channel.
#: * ``fleet_topic`` (the second-channel seam) is therefore NOT the shape that
#:   shipped. The fleet topic is the PRIMARY `topic` and there is no second
#:   channel, because `badge:<shared sub>` names the fleet rather than a badge
#:   and joining it would spend a handshake on a topic nothing addresses. The
#:   seam stays supported for a caller that wants both.
RING_JITTER_MIN_MS = 1000
RING_JITTER_MAX_MS = 2000

#: HOW MANY ALREADY-ARRIVED FRAMES ONE RENDERED FRAME MAY DRAIN.
#:
#: FOUR, and the number is the shared topic's fan-in against the frame budget.
#: Layer 2 takes at most one frame per ``service()`` call and this module used to
#: call it once per rendered frame -- ample on a private topic whose only
#: publisher was this badge, and a ~21 second backlog on a shared topic where an
#: 800-badge fleet show publishes ~800 broadcasts that every badge receives (the
#: measured device frame is ~27 ms, so ~37 frames a second).
#:
#: **WHAT ACTUALLY BREAKS IS THE HEARTBEAT, not a server-side slow-consumer
#: close, and the distinction changes the severity in both directions.** Layer 2
#: pings every 20,000 ms and drops the socket if the reply misses a 10,000 ms
#: deadline (`realtime/client.py`'s `heartbeat_ms`/`heartbeat_timeout_ms`). It
#: already knows a starved pump can reach that deadline with the reply sitting
#: behind another frame, so `_drain_for_heartbeat_reply` empties up to
#: `HEARTBEAT_DRAIN_ROUNDS` (8) frames before believing the timeout -- but eight
#: is not hundreds, so a fleet-sized backlog drops a HEALTHY socket as
#: "heartbeat reply timed out".
#:
#: AND THAT DROP DOES NOT DEMOTE, which is worth stating because the obvious
#: fear is wrong: `_close_session` only charges the demotion counter for a
#: session that NEVER joined, so a joined-then-dropped socket is a reconnect,
#: not a strike (see :meth:`PushPolicy.note_session_failed`). So the real cost is
#: bounded -- ~20 s of ring latency, 799 wasted decodes and about one reconnect
#: per badge per fleet batch. CP3's shipping producer now sends one room-wide
#: `fleet_actions` frame, so that old per-badge burst is historical; the bound
#: remains defensive for batched or future shared-topic traffic.
#:
#: FOUR rather than "until empty": a drained frame costs a JSON decode of a body
#: `max_frame_size` caps at 2 KB, so four is a handful of milliseconds against
#: the ~27 ms frame -- the same order as `polltransport.OPEN_STEP_BUSY_BUDGET_MS`
#: -- while an unbounded drain would hand one burst the whole frame and stutter
#: the UI the doorbell exists to keep smooth. It cuts the ~21 s backlog to ~5 s.
FLEET_DRAIN_MAX = 4


#: The layer-1 transport options layer 3 pins for Realtime (review item 10).
#: Each value is a decision, not a default:
#:
#: * ``idle_timeout_ms=None`` — silence between frames is NORMAL on a
#:   subscription. An idle deadline here is what made an earlier client tear
#:   down its own healthy socket; liveness is the ping timer plus the Phoenix
#:   heartbeat, both missed-ack based.
#: * ``io_timeout_ms`` — a stall *inside* a frame is a broken peer, and this is
#:   the deadline that catches it. Kept distinct from the idle deadline on
#:   purpose; the stalled-peer test drives exactly this split.
#: * **BOTH DEADLINES ARE 5,000 ms SINCE THE OWNER'S 2026-08-24 RULING** ("10
#:   seconds is too extreme", `OWNER-DECISIONS #21`); both were 10,000. It is the
#:   same in-frame budget the poll transport caps its blocking open with —
#:   `polltransport.OPEN_BUDGET_MS`, whose comment carries the whole derivation —
#:   spelled here rather than imported, because a `/system/lib` module importing
#:   a sibling is a partial-install hazard, and pinned equal across all three
#:   sites by `badgelink/tests/test_open_budget.py`.
#:
#:   **ONE NUMBER COVERS BOTH PATHS AND THE POLL OPEN IS THE ONE THAT BINDS.**
#:   P6-L3 measured the whole WSS connect frame — DNS, TCP, TLS, upgrade and the
#:   first exchange together — at **2,581-2,696 ms**, which is *less* than the
#:   worst measured successful poll open (3,217 ms). These two deadlines each
#:   bound a SUB-leg of that frame, so 5,000 ms is 1.85x the whole thing and more
#:   than that on any single leg. A per-path split would be two numbers where one
#:   is provably enough. **Independently re-measured 2026-08-25**: the freeze
#:   capture put the `reconnect_due` join leg at **2,252-2,436 ms across three
#:   runs** -- remarkably stable, and 2.05x inside this budget. That report also
#:   names the join leg as the ONE remaining user-felt freeze, which this budget
#:   does not fix: capping a leg that reliably costs 2.3 s at 5 s changes nothing
#:   a wearer feels. The fix is the NB spec's non-blocking join states.
#:
#:   ⚠ **TWO HONEST LIMITS.** (a) `connect_timeout_ms` wraps `_handshake` in
#:   `_wait_for`, and `_wait_for` cannot interrupt a blocking C call — on
#:   MicroPython the name lookup and the TLS handshake happen INSIDE
#:   `asyncio.open_connection` (`aiohttp_ws.py`'s own note, and
#:   `network/tests/test_bounded_websocket.py`). So this deadline bounds the
#:   interruptible remainder, and lowering it does less on the doorbell's path
#:   than the poll's `timeout=` does on its own. (b) `io_timeout_ms` also bounds
#:   in-session frame-body reads, so a mid-frame stall is now called a broken peer
#:   after 5 s rather than 10. A doorbell frame is capped at 2 KB below, so a
#:   five-second stall after a header has already arrived is a broken peer with
#:   very little room for another reading.
#:
#:   The VENDORED defaults in `network/vendor/aiohttp/aiohttp_ws.py` stay at
#:   10,000 on purpose: this dict passes both explicitly on every production
#:   session, and a vendored library's defaults are upstream's business.
#: * ``ping_interval_ms=20000`` — under the ≤25 s ceiling, and nothing else on
#:   this device sends a WebSocket ping.
#: * the frame/message caps — a doorbell carries no data, so anything past 2 KB
#:   in one frame is not a doorbell. The cap is enforced before the payload is
#:   buffered, which is the point of having one at all. (This line said "on a
#:   520 KB heap" until 2026-08-26. The heap is ~8 MB -- five measured
#:   `SNAKE_OPEN` reads of 8,005,696-8,011,328 B free -- so the cap is about
#:   CONTIGUITY and a bounded per-frame cost, not about the free total; see
#:   `docs/engineering-findings.md` on the stale phrase.)
TRANSPORT_CONFIG = {
    "connect_timeout_ms": 5000,
    "io_timeout_ms": 5000,
    "idle_timeout_ms": None,
    "ping_interval_ms": 20000,
    "max_frame_size": 2048,
    "max_message_size": 4096,
}


def _default_rand01():
    """A fraction in [0, 1). ``os.urandom`` is the one source both runtimes have."""

    import os

    raw = os.urandom(2)
    return (raw[0] << 8 | raw[1]) / 65536.0


def transport_config(**overrides):
    """A fresh copy of :data:`TRANSPORT_CONFIG`, with any overrides applied.

    Returns a new dict every call so a caller cannot mutate the pinned defaults
    for everybody else, and rejects an unknown key rather than silently dropping
    a misspelled option into a session that then behaves nothing like the tested
    one.
    """

    for key in overrides:
        if key not in TRANSPORT_CONFIG:
            raise ValueError("unknown transport option: {}".format(key))
    config = dict(TRANSPORT_CONFIG)
    config.update(overrides)
    return config


def _nonempty_text(value):
    """A JSON string with something in it.  The trigger sends no empty ones."""

    return isinstance(value, str) and len(value) > 0


def _exact_payload_keys(payload, expected):
    """No missing and no future keys, without allocating a set per ring."""

    if not isinstance(payload, dict) or len(payload) != len(expected):
        return False
    for key in expected:
        if key not in payload:
            return False
    return True


def _canonical_uuid_text(value):
    """Postgres UUID JSON form: lowercase hex with four fixed hyphens."""

    if not isinstance(value, str) or len(value) != UUID_TEXT_LEN:
        return False
    for index in range(UUID_TEXT_LEN):
        character = value[index]
        if index in UUID_HYPHENS:
            if character != "-":
                return False
        elif character not in LOWER_HEX:
            return False
    return True


def _physical_badge_id(value):
    """Exactly the lowercase 16-hex shape `machine.unique_id().hex()` emits."""

    if not isinstance(value, str) or len(value) != 16:
        return False
    for character in value:
        if character not in LOWER_HEX:
            return False
    return True


def _reliable_doorbell_payload(payload):
    """The validated action inside one broadcast, or ``None``.

    **IT RETURNS THE ACTION AND NOT A BOOLEAN, AND THAT IS THE REBUILD.** While
    the doorbell was a hint, this answered "is this news?" and the durable
    `badge_commands` row carried the content. There is no row now, so the only
    copy of the moment is the one in this payload and it has to travel out of
    here -- see :data:`RELIABLE_DOORBELL_KEYS`.

    ``(action_id, action_type, payload)`` on success. A TUPLE rather than a dict
    because this runs on the rendered-frame path and a tuple of three references
    that already exist is the cheapest thing that can leave a validator; the
    caller unpacks it once.

    **THE ENVELOPE IS VALIDATED HERE, THE ACTION IS NOT.** ``action_type`` must
    be a non-empty string and ``payload`` must be a JSON object or array --
    enough to prove this is an action-shaped thing and not a future message --
    and nothing beyond that. W9 requires the array arm for ``play_effect``;
    `_apply` rejects arrays for verbs that still require objects. The verb
    vocabulary belongs to the appliers and effect item arguments belong to
    `effect_library.parse`, whose clause order is
    load-bearing (test for the KEY before reading it) and which already fails
    loudly. Duplicating either here would be a second boundary to keep in step,
    which is the mistake `_apply_play_effect`'s own comment names.

    Every clause is a refusal and every refusal is silence rather than a guess:
    on a shared topic a validator that hedges is ~1,000 badges rendering something
    nobody chose.
    """

    if not _exact_payload_keys(payload, RELIABLE_DOORBELL_KEYS):
        return None
    target = payload[FLEET_TARGET_KEY]
    if target != RELIABLE_ALL_TARGET and not _physical_badge_id(target):
        return None
    action_id = payload[ACTION_ID_KEY]
    if not _canonical_uuid_text(action_id):
        return None
    # `realtime.send` injects `id` when the publisher omits it, so this equality
    # is what proves the publisher wrote the whole envelope on purpose.
    if payload["id"] != action_id:
        return None
    if not _nonempty_text(payload["at"]):
        return None
    action_type = payload[ACTION_TYPE_KEY]
    if not _nonempty_text(action_type) or len(action_type) > MAX_ACTION_TYPE:
        return None
    action_payload = payload[ACTION_PAYLOAD_KEY]
    if not isinstance(action_payload, (dict, list)):
        return None
    return (action_id, action_type, action_payload)


def is_revocation_reason(reason):
    """Is this refusal the server saying NO, rather than NOT NOW?

    See :data:`REVOCATION_REASON_CODE`. Deliberately a prefix test on the error
    code and nothing else: no substring search, so an unrelated reason that
    happens to contain the word cannot stop a badge's doorbell for a boot.
    """

    if not isinstance(reason, str):
        return False
    return reason.startswith(REVOCATION_REASON_CODE + ":")


def badge_topic(badge_id):
    """The private Phoenix topic for one badge: ``realtime:badge:<16 hex>``.

    The ``realtime:`` prefix is Phoenix's wire namespace; the server's
    ``grants.can_access_channel`` matches the bare ``badge:<16 hex>`` tail, so
    the two halves have to agree exactly and this function is the only place
    either is spelled.
    """

    if not isinstance(badge_id, str) or len(badge_id) != 16:
        raise ValueError("badge id must be 16 characters")
    for character in badge_id:
        if character not in "0123456789abcdef":
            raise ValueError("badge id must be lowercase hex")
    return TOPIC_PREFIX + badge_id


def topic_badge_id(topic):
    """The badge id inside a joined topic, or ``None``.  Never raises.

    THE INVERSE OF :func:`badge_topic`, and it is here rather than in the caller
    for that function's own reason: the topic is spelled in one place. It is how
    layer 3 knows WHOSE acks it is looking at without being handed a second copy
    of the badge id -- the ring filter has to compare a broadcast's ``badge_id``
    to this badge's, and the topic it joined already carries it.

    ``None`` for anything that is not the private per-badge shape (a fleet topic,
    a test double, a name from a future server), which is the fail-open answer:
    a ``None`` matches no payload, so every broadcast rings.
    """

    if not isinstance(topic, str) or not topic.startswith(TOPIC_PREFIX):
        return None
    badge_id = topic[len(TOPIC_PREFIX):]
    if len(badge_id) != 16:
        return None
    for character in badge_id:
        if character not in "0123456789abcdef":
            return None
    return badge_id


#: The name characters `grants.can_access_channel`'s `event:` branch accepts
#: after the first, spelled as a set because Badgeware v3.0.1's MicroPython `str`
#: has no `isalnum` and this module may not import `re` (see the module
#: docstring: it imports nothing but `asyncio`).
_EVENT_NAME_CHARS = ("abcdefghijklmnopqrstuvwxyz"
                     "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                     "0123456789._:-")


def event_topic(name):
    """The fleet Phoenix topic for one event: ``realtime:event:<name>``.

    The mirror of :func:`badge_topic` for the OTHER half of the server's topic
    convention, and it exists for the same reason that one does: the server
    matches the bare ``event:<name>`` tail and Phoenix wants the ``realtime:``
    namespace in front of it, so the two halves have to agree exactly and this
    is the only place either is spelled.

    VALIDATED AGAINST THE SERVER'S OWN REGEX rather than trusted, because the
    failure it prevents is silent: a topic the policy's
    ``^event:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`` does not match
    (`badgelink/supabase/schemas/badgelink.sql:642`) is not refused with a
    useful reason, it simply never carries a broadcast, and a doorbell that
    never rings looks exactly like a doorbell nobody pressed. Raising here puts
    the mistake in the frame that made it.
    """

    if not isinstance(name, str) or not name:
        raise ValueError("event name must be a non-empty string")
    if len(name) > 128:
        raise ValueError("event name must be at most 128 characters")
    first = name[0]
    if not (("a" <= first <= "z") or ("A" <= first <= "Z")
            or ("0" <= first <= "9")):
        raise ValueError("event name must start alphanumeric")
    for character in name[1:]:
        if character not in _EVENT_NAME_CHARS:
            raise ValueError("event name carries an unauthorized character")
    return EVENT_TOPIC_PREFIX + name


class PushPolicy:
    """Whether push may be attempted at all: wearer, server and demotion.

    Three independent authorities, and every one of them can only ever say NO:

    * the WEARER, through Settings (``enabled``) and through the network
      preference itself, which is a separate switch this class is told about;
    * the SERVER, through the poll response's steering channel
      (``remote_disabled`` — the venue herd kill-switch);
    * the BADGE ITSELF, through the demotion counter.

    Nothing here can turn push ON against one of the others, which is what makes
    the fail-safe direction below coherent: there is no combination of remote
    state that produces more radio work than the wearer already allowed.
    """

    def __init__(self, enabled=True, demote_after=DEMOTE_AFTER_SESSIONS):
        if not isinstance(demote_after, int) or demote_after < 1:
            raise ValueError("demote_after must be a positive integer")
        self.enabled = bool(enabled)
        self.demote_after = demote_after
        self.demoted = False
        self.failed_sessions = 0
        #: A FOURTH authority, and it also only ever says NO: the server refused
        #: this badge's join on authorization grounds after the badge had already
        #: proved the path works. Kept separate from ``demoted`` because the two
        #: are different facts about different failures — see
        #: :meth:`note_revoked`.
        self.revoked = False
        self.revocations = 0
        self.remote_disabled = False
        self.policy_version = None
        #: Where the current remote answer came from: ``"default"`` until a
        #: steering field has been seen, then ``"server"`` or ``"malformed"``.
        self.policy_source = "default"
        self.demotions = 0

    # -- the wearer ---------------------------------------------------------

    def set_enabled(self, enabled):
        """Settings turning push on or off. Turning it ON clears a demotion.

        The explicit re-enable is the documented escape from a sticky demotion
        (the other one is a reboot, because ``demoted`` is RAM-only on purpose:
        a badge carried into a working network the next morning must not still
        be punished for last night's venue).
        """

        enabled = bool(enabled)
        if enabled:
            self.demoted = False
            self.failed_sessions = 0
            # A revocation is cleared here too, and it costs exactly one refused
            # join to re-establish: the wearer pressed YES, the badge asks once,
            # the server says no again and it goes straight back. Same escape as
            # the demotion, same bound, and it keeps the wearer's switch from
            # being the one control that a server state can override.
            self.revoked = False
        self.enabled = enabled
        return self.enabled

    # -- the badge ----------------------------------------------------------

    def note_session_failed(self):
        """One WS session ended WITHOUT ever joining a channel.

        Returns True when this failure is the one that demoted the badge.
        """

        self.failed_sessions += 1
        if self.demoted or self.failed_sessions < self.demote_after:
            return False
        self.demoted = True
        self.demotions += 1
        return True

    def note_session_joined(self):
        """A channel joined: the push path demonstrably works on this network.

        Resets the counter, and only the counter — a demotion already recorded
        stays recorded, because it is what stopped the attempts that would have
        produced this join. Clearing it here would let one lucky join re-arm an
        unbounded retry loop.

        THAT RATIONALE STILL HOLDS FOR THIS METHOD and is why the clear did NOT
        move into it (2026-08-26). This method is called on EVERY join, including
        the ordinary reconnects of a healthy socket, so folding a demotion clear
        in here would silently repurpose a narrow "reset the counter" role. The
        clear is a separate, deliberate call from the one caller that knows the
        join came from the SLOW bounded probe — see :meth:`clear_demotion` and
        `PushLink._on_event`'s KIND_JOINED branch.
        """

        self.failed_sessions = 0

    def clear_demotion(self):
        """A bounded slow probe joined, so the demotion's claim is falsified.

        SAFE ONLY BECAUSE OF WHAT PRODUCED THE JOIN. A demotion says "this badge
        cannot get a doorbell up on this network", and it is always the
        never-joined kind -- :meth:`note_session_failed` only counts sessions that
        never joined. A join is therefore direct evidence against the only thing
        it ever claimed. What made clearing it unsafe before
        `REDEMOTE_RETRY_MIN_MS` existed was the RATE of the retry that could
        produce one: an unbounded fast loop plus a clear-on-join is a loop with no
        bound at all. One jittered attempt per 15-30 minutes is not that loop.

        Returns True when this call changed anything, so a caller can emit once.
        """

        if not self.demoted:
            return False
        self.demoted = False
        self.failed_sessions = 0
        return True

    def note_revoked(self):
        """The server refused an authorization this badge had already been given.

        A SEPARATE STATE FROM DEMOTION, and the separation is the point.
        ``demoted`` counts sockets that NEVER joined: an unreachable shard, no
        WSS egress, a captive portal — conditions about the network, which a
        different network fixes, and which is why three tries is the budget.
        ``revoked`` is the opposite fact: the path works, the socket opened, the
        server read the grant row and said no. Retrying that cannot succeed, so
        it gets no attempt budget at all — one refusal is the whole evidence —
        and it must never consume ``failed_sessions``, or a revoked badge would
        arrive at "demoted" by a route that says nothing true about its network.

        This mirrors the poll's 403 exactly (`rpc_contract`, owner ruling
        2026-08-19): 403 means stop, never retry harder, terminal for the boot.
        The two transports reach it independently — the poll from its own HTTP
        verdict, this from its own join refusal — because neither may be the
        reason the other stops.

        Returns True when this is the refusal that revoked the badge.
        """

        if self.revoked:
            return False
        self.revoked = True
        self.revocations += 1
        return True

    # -- the server ---------------------------------------------------------

    def set_remote(self, steering):
        """Apply the poll response's transport-policy fields.

        FAIL DIRECTION (chosen and justified, card item 9): **absent or
        malformed means push stays ALLOWED.** Push is disabled only by an
        explicit, well-formed ``push_enabled: false``.

        The instinct is to fail closed, and it is wrong here, because "closed"
        for a KILL SWITCH is the direction that makes the switch itself
        load-bearing. Every server the badge talks to today — the deployed P1
        schema included — returns no policy field at all, so failing closed
        would mean push never works until a migration lands, and a truncated or
        garbled poll body (a class Card E measured on real relay faults) would
        silently disable push on badges the operator never touched. Both are
        outages caused by the safety mechanism.

        Failing open is safe *because push is not load-bearing*: the worst case
        is the badge holds one WebSocket it was already allowed to hold, and the
        wearer's own switch plus the demotion rule still bound it. The venue
        kill-switch is for a room that is working badly, not for a security
        boundary — the security boundary is `realtime.messages` RLS, which
        refuses the join regardless of what any client believes about policy.
        Note the asymmetry that makes this cheap: a malformed policy cannot
        *enable* anything the wearer disabled.
        """

        if not isinstance(steering, dict):
            self.policy_source = "default"
            return self.remote_disabled
        if "push_enabled" not in steering:
            self.policy_source = "default"
            return self.remote_disabled
        value = steering.get("push_enabled")
        if not isinstance(value, bool):
            # A non-boolean is a malformed policy, not a false one.
            self.policy_source = "malformed"
            self.remote_disabled = False
            return self.remote_disabled
        self.policy_source = "server"
        self.remote_disabled = not value
        version = steering.get("policy_version")
        if isinstance(version, int) and not isinstance(version, bool):
            self.policy_version = version
        return self.remote_disabled

    # -- the answer ---------------------------------------------------------

    def push_allowed(self, network_enabled):
        return bool(
            network_enabled
            and self.enabled
            and not self.demoted
            and not self.revoked
            and not self.remote_disabled
        )

    def mode(self, network_enabled, joined):
        """The live mode, in the order a wearer would want to be told.

        Order matters: a demoted badge whose venue ALSO disabled push should read
        as blocked, because that is the thing an operator can undo.
        """

        if not network_enabled:
            return MODE_NETWORK_OFF
        if not self.enabled:
            return MODE_POLLING
        if self.remote_disabled:
            return MODE_BLOCKED
        if self.demoted or self.revoked:
            # NO NEW MODE LITERAL, and that is a decision rather than laziness.
            # A mode is what a WEARER is told, and `settings_copy.PUSH_WORDS`
            # already answers "Normal" for both `demoted` and `blocked` — the
            # true and only useful thing to say here, since the wearer cannot act
            # on the difference. Adding a sixth literal would also mean a new
            # copy string and a new entry in the pre-baked glyph set, which is
            # real flash for a word nobody can use. The CAUSE stays fully legible
            # where a probe or a serial log reads it: `push_revoked`,
            # `revocations` and `last_error` in the snapshot, plus the `revoked`
            # event.
            return MODE_DEMOTED
        return MODE_PUSH if joined else MODE_TRYING

    def snapshot(self):
        return {
            "enabled": self.enabled,
            "demoted": self.demoted,
            "demote_after": self.demote_after,
            "failed_sessions": self.failed_sessions,
            "demotions": self.demotions,
            # Named `push_revoked` rather than `revoked`: `network_runtime`'s own
            # snapshot already carries a `revoked` key for the POLL's terminal
            # 403 state, and the two are independent facts that a device
            # transcript must be able to hold at once.
            "push_revoked": self.revoked,
            "revocations": self.revocations,
            "remote_disabled": self.remote_disabled,
            "policy_version": self.policy_version,
            "policy_source": self.policy_source,
        }


class PushLink:
    """Layer 2 under the product's polling pump, as a doorbell.

    ``poll_loop`` is the transport this link reads ``state`` from: a
    ``polltransport.PollLoop`` or its ``PollTransport`` adapter. It used to be
    "the object the doorbell rings" and it is not any more -- a validated
    broadcast goes to :meth:`set_action_sink`, not to ``pull_forward``, because
    there is no queue left for a pulled-forward poll to collect. The argument
    stays required so the transport's ``state`` is still reachable and so the
    construction seam does not move in the same change as the behaviour.

    ``client_factory()`` builds a configured layer-2
    ``RealtimeClient`` with its transports already injected — this module never
    constructs an SSLContext, never reads a CA file and never sees a token except
    through ``token_provider``.

    ``token_provider()`` returns ``(jwt, claims)``; claims may be ``None``. It is
    called immediately before every socket open rather than cached, so the fresh
    join after a cadence close carries a credential refreshed on flash without a
    reboot.
    """

    # NB-0'S HELD-STRATEGY DEFAULTS LIVE ON THE CLASS so the cold OFF artifact
    # does not allocate per-instance slots for a strategy it cannot enter. Every
    # value is immutable. The first ON admission materialises the complete owner
    # on the instance before creating its task; all later writes are instance
    # writes too. This is the lazy-construction half of the dark-launch contract.
    _held_strategy = False
    #: OWNER RULING #22 placement (WSS side). ``False`` while the badge is in a
    #: non-opted-in app: it defers the CADENCE reauthorization reopen (a healthy
    #: minute-60 close with no re-open allowed would strand a mid-app command).
    #: A true token/grant expiry ignores it and still fails closed. RAM-only and
    #: class-defaulted ``True`` so OFF and un-gated callers keep the old cadence.
    _establishment_allowed = True
    _establishing = False
    _establish_task = None
    _establish_attempt = 0
    _establish_generation = 0
    _establish_moment = None
    _establish_radio_generation = None
    _establish_started_ms = None
    _establish_terminal_ms = None
    _establish_error_class = None
    _establish_error_text = None
    _establish_aborting = False
    _establish_abort_reason = None
    _establish_abort_retry = False
    _establish_trace_closed = False
    #: THE ARMED TICK for the next slow demotion probe (``ticks_ms`` domain), or
    #: ``None`` for "not armed". CLASS DEFAULTS so the cold OFF artifact
    #: allocates no per-instance slot for a strategy it cannot enter, and so
    #: every boot starts clean -- these are RAM-only on purpose. A reboot is the
    #: documented hard escape and nothing about a demotion may survive one; see
    #: the England-boot rule that no connectivity artifact reaches flash.
    _demote_retry_at_ms = None
    #: Unanswered joins on the CURRENT socket. Reset on a join and on every
    #: close, because the question is "is this socket getting anywhere", not
    #: "has this boot ever timed out".
    _join_timeouts = 0
    #: DID THIS SOCKET EVER JOIN? Distinct from `joined`, which is the CURRENT
    #: channel state and goes False the moment a `channel_error` arrives -- so at
    #: the point a deferred close runs, `joined` can no longer answer "did this
    #: session ever get a doorbell up". The demotion counter's documented meaning
    #: is "consecutive sessions that never reached a JOIN", and this is the only
    #: field that can still say so after the error that caused the close.
    _session_joined = False
    #: WHY this badge is demoted, or ``None``. Chooses the re-arm interval and
    #: appears in the snapshot; see :data:`DEMOTE_CAUSE_REFUSED`.
    demote_cause = None
    #: A never-joined authorization refusal waiting for ``step()`` to close it.
    #: `_on_event` is SYNCHRONOUS and the socket is released only by async
    #: `_ensure_closed`, so the intent is recorded here and acted on one frame
    #: later -- the same deferral `_note_revoked` already uses.
    _refused_close_pending = False
    #: WHO TO TELL THAT THE ENDPOINT ITSELF LOOKS UNREACHABLE, or ``None``.
    #: Set by the product through :meth:`set_unreachable_sink`; see
    #: `_note_failed_session` for the failure this closes. Class-defaulted for
    #: the same reason as the held-strategy slots above: an artifact whose
    #: product never wires it allocates no per-instance slot for it.
    _unreachable_sink = None
    #: WHO ACTS ON A VALIDATED BROADCAST, or ``None``. Set by the product through
    #: :meth:`set_action_sink`. Class-defaulted like the sink above, and for one
    #: extra reason: a fixture that never wires it still exercises the whole
    #: validator, which is where the interesting behaviour is.
    _action_sink = None
    #: Validated actions this link handed to the product, and validated actions
    #: it had nowhere to hand. THE SECOND NUMBER IS THE DIAGNOSTIC: it is nonzero
    #: only when the badge understood a broadcast and then lost it -- no sink
    #: wired, or a sink that raised -- which is invisible from the wearer's side,
    #: because the show simply does not play.
    actions_delivered = 0
    actions_dropped = 0

    def __init__(
        self,
        poll_loop,
        client_factory,
        topic,
        token_provider,
        policy=None,
        clock=None,
        event_sink=None,
        token_refresh_ms=TOKEN_REFRESH_MS,
        rejoin_jitter_ms=REJOIN_JITTER_MS,
        token_expiry_margin_ms=TOKEN_EXPIRY_MARGIN_MS,
        grant_expiry_margin_ms=GRANT_EXPIRY_MARGIN_MS,
        starvation_ms=STARVATION_CEILING_MS,
        grant_expires_at=None,
        epoch_clock=None,
        boot_jitter_ms=BOOT_JITTER_MS,
        rand01=None,
        fleet_topic=None,
        ring_jitter_min_ms=RING_JITTER_MIN_MS,
        ring_jitter_max_ms=RING_JITTER_MAX_MS,
        open_trace=None,
        target_uid=None,
    ):
        if poll_loop is None:
            raise ValueError("a poll loop is required")
        if not callable(client_factory):
            raise ValueError("client_factory must be callable")
        if not callable(token_provider):
            raise ValueError("token_provider must be callable")
        if int(starvation_ms) < 1:
            raise ValueError("starvation ceiling must be positive")
        if int(boot_jitter_ms) < 0:
            raise ValueError("boot jitter cannot be negative")
        if int(ring_jitter_min_ms) < 0 or int(ring_jitter_max_ms) < 0:
            raise ValueError("ring jitter cannot be negative")
        if int(ring_jitter_max_ms) < int(ring_jitter_min_ms):
            raise ValueError("ring jitter max must not be below min")
        self.poll_loop = poll_loop
        self.topic = topic
        #: THIS BADGE's id, read back out of the topic it joins (CX-9). Drawn
        #: once per boot because the topic cannot change under a PushLink, and
        #: it is what lets the ring filter tell the badge's OWN status echo from
        #: another badge's. ``None`` when the topic is not the private per-badge
        #: shape, which makes every broadcast ring.
        #:
        #: ⚠ UNDER THE SHARED TOKEN THIS IS THE FLEET'S SUBJECT, NOT THIS BADGE.
        #: `badge_topic(creds.badge_id)` used to name one physical badge because
        #: provisioning minted `sub = machine.unique_id().hex()`; a byte-identical
        #: `secrets.py` breaks that equality for all 800. It stays for the private
        #: per-badge shape (a dev badge on its own token, the fixtures) and it is
        #: ``None`` on the fleet topic -- which is exactly why the fleet path uses
        #: :attr:`target_uid` and never this.
        self.badge_id = topic_badge_id(topic)
        #: THE PHYSICAL BADGE, injected rather than derived (§0.5's linchpin).
        #: 16 lowercase hex from `machine.unique_id()`, computed ONCE per boot by
        #: `network_runtime.device_push_factory` and handed in, because this
        #: module holds no credential and imports no Badgeware -- see the module
        #: docstring. ``None`` in every fixture that does not supply one, and
        #: `_fleet_target_is_me` reads that as "cannot prove, do not ring".
        self.target_uid = target_uid
        #: IS THE PRIMARY CHANNEL THE SHARED FLEET TOPIC? Derived from the topic
        #: itself so a caller cannot get it wrong, and it is load-bearing twice:
        #: it makes `ring_scope` classify the primary as `"fleet"` (so
        #: RING_JITTER applies -- see :meth:`ring_scope`) and it selects the
        #: positive-UID ring filter over the private topic's echo filter.
        self._fleet_primary = (
            isinstance(topic, str) and topic.startswith(EVENT_TOPIC_PREFIX)
        )
        self.policy = policy if policy is not None else PushPolicy()
        self._client_factory = client_factory
        self._token_provider = token_provider
        self._clock = clock or _ticks_ms
        self._epoch_clock = epoch_clock
        self._event_sink = event_sink
        #: WHO IS TIMING THE ESTABLISHMENT, or ``None`` (NB-i). Called with ONE
        #: outcome word when the owner COMMITS a reaped result or abort, plus the
        #: child's actual terminal tick so frame-barrier wait is not charged to
        #: join-send. That edge is the only thing this module can contribute:
        #: the legs are measured inside the WS client (a vendored ``trace=``
        #: dict) and the record is closed and emitted by whoever supplied both,
        #: which is `network_runtime.device_push_factory` -- the one scope
        #: holding a trace, the session and `event_sink` at the same time.
        #:
        #: Duck-typed and optional, so a fixture, a probe or a badge whose
        #: factory predates the seam simply never traces. PURELY REPORTED: no
        #: branch in this module reads a number from it, and `_note_open_trace`
        #: swallows, because an instrument may not cost a badge its socket.
        self._open_trace = open_trace
        self.token_refresh_ms = int(token_refresh_ms)
        self.rejoin_jitter_ms = int(rejoin_jitter_ms)
        self.token_expiry_margin_ms = int(token_expiry_margin_ms)
        self.grant_expiry_margin_ms = int(grant_expiry_margin_ms)
        self.starvation_ms = int(starvation_ms)
        self.boot_jitter_ms = int(boot_jitter_ms)
        #: A shared fleet channel, if a server ever publishes to one. None today,
        #: which is why every ring is jittered -- see RING_JITTER_MIN_MS.
        self.fleet_topic = fleet_topic
        self.ring_jitter_min_ms = int(ring_jitter_min_ms)
        self.ring_jitter_max_ms = int(ring_jitter_max_ms)
        self._rand01 = rand01 or _default_rand01
        # Drawn ONCE per object, which is once per boot, which is the point.
        self.boot_delay_ms = (
            int(self._rand01() * self.boot_jitter_ms)
            if self.boot_jitter_ms else 0
        )
        self._boot_ready_at_ms = None
        self.grant_expires_at = grant_expires_at
        self.client = None
        self.joined = False
        self._quiesced = False
        self._last_step_ms = None
        self._token_due_ms = None
        self._session_open = False
        self._last_claims = None
        self._token_exp = None
        # Credential-free counters, all of them report material.
        self.sessions = 0
        self.sessions_joined = 0
        self.sessions_failed = 0
        self.doorbells = 0
        self.doorbells_rung = 0
        #: Broadcasts this badge declined to ring for (CX-9). `doorbells` counts
        #: arrivals the badge ACCEPTED, so a filtered one is not one of them --
        #: that is what makes `doorbells` mean "rings that were worth having"
        #: rather than "messages that arrived", and it is why the two counters are
        #: reported side by side: their SUM is what the WSS link delivered, and
        #: the fleet cost is the sum.
        self.doorbells_filtered = 0
        self.token_pushes = 0
        self.reauthorizations = 0
        self.starvation_drops = 0
        self.connect_failures = 0
        self.contained_errors = 0
        self.last_error = None
        self.last_moment = None

    # -- what a Settings screen reads -------------------------------------

    def mode(self, network_enabled=True):
        """The LIVE mode, derived from the transport, never from a button."""

        return self.policy.mode(network_enabled, self.joined)

    def wants_connect(self, now=None, network_enabled=True):
        """Would a tolerant moment RIGHT NOW actually open a socket?

        The caller uses this to decide whether to SPEND a tolerant moment. A
        moment spent while the boot jitter or the reconnect backoff is still
        running is a moment wasted — and on a badge sitting on the launcher there
        may not be another one for a long time, so the caller keeps it pending
        instead.
        """

        now = self._clock() if now is None else now
        if self._session_open or self._establishing or self._quiesced:
            return False
        # `_establishment_open` so NetworkService SPENDS a tolerant moment when a
        # demotion probe is due -- and keeps retaining it when one is not, which
        # is the whole point of asking before spending. A badge on the launcher
        # may not see another tolerant moment for a long time.
        if not self._establishment_open(now, network_enabled):
            return False
        if self._boot_ready_at_ms is not None and _ticks_diff(
            now, self._boot_ready_at_ms
        ) < 0:
            return False
        client = self.client
        if client is None:
            return True
        delay = client.reconnect_delay_ms(now)
        return delay is None or delay <= 0

    def snapshot(self):
        record = {
            "mode": self.mode(),
            "boot_delay_ms": self.boot_delay_ms,
            "joined": self.joined,
            "socket_open": self._session_open,
            "quiesced": self._quiesced,
            "sessions": self.sessions,
            "sessions_joined": self.sessions_joined,
            "sessions_failed": self.sessions_failed,
            "doorbells": self.doorbells,
            "doorbells_rung": self.doorbells_rung,
            "doorbells_filtered": self.doorbells_filtered,
            #: THE TWO NUMBERS THAT SEPARATE "NOBODY PUBLISHED" FROM "THE BADGE
            #: HEARD IT AND NOTHING HAPPENED", which are the same silence on
            #: serial and are now the difference between a working show and a
            #: dead one. `actions_dropped` above zero means the envelope
            #: validated and the product still did not act: no sink wired, or a
            #: sink that raised. Read it before suspecting the publisher.
            "actions_delivered": self.actions_delivered,
            "actions_dropped": self.actions_dropped,
            #: WHETHER THE RING FILTER CAN ANSWER YES AT ALL, as a bool and not
            #: the id. A `PushLink` on the fleet primary with no `target_uid`
            #: rings for nothing and looks identical on serial to one whose
            #: venue never publishes -- `doorbells_filtered` climbing with
            #: `targeted` False is the difference, and it is the first thing to
            #: read when T2 delivers zero rows.
            "fleet_primary": self._fleet_primary,
            "targeted": self.target_uid is not None,
            #: WHICH demotion this is, so the two intervals can be retuned later
            #: without re-deriving which one happened from surrounding lines.
            "demote_cause": self.demote_cause,
            "token_pushes": self.token_pushes,
            "reauthorizations": self.reauthorizations,
            "starvation_drops": self.starvation_drops,
            "connect_failures": self.connect_failures,
            "contained_errors": self.contained_errors,
            "last_error": self.last_error,
            "last_moment": self.last_moment,
        }
        # The flag gates accounting too. OFF never enters this strategy, so its
        # shipping snapshot keeps the old schema and pays for no held-only keys.
        if self._held_strategy:
            record.update({
                "establishing": self._establishing,
                "establishment_attempt": (
                    self._establish_attempt if self._establishing else None
                ),
                "establishment_moment": self._establish_moment,
            })
        record.update(self.policy.snapshot())
        if self.client is not None:
            record["client"] = self.client.snapshot()
        return record

    # -- gates the caller declares ----------------------------------------

    def quiesce(self, reason="intro"):
        """A gate has stopped servicing us (the intro, or any equivalent).

        This does not close an established socket — a ten-second intro on a
        badge that just booted has usually not opened one yet, and tearing down a
        healthy socket for a gate that lasts one frame would be worse than the
        gate. A PARTIAL held establishment is different: nobody may advance it
        inside the gate, so it is cancelled and driven to cleanup as a nonfailure.
        The method records that nothing is being serviced, refuses new opens and
        lets :meth:`resume` decide from the measured gap whether an established
        session can still be believed.
        """

        self._quiesced = True
        # Synchronous on purpose.  On the pinned scheduler a ready held task may
        # be ahead of the cleanup coroutine that PushService is about to pump.
        # Cancelling here prevents it from taking one more TLS/write step first;
        # PushService then drives the task to done before returning.
        self._request_establishment_abort(reason, retry=False)
        self._emit("quiesced", reason=reason)
        return True

    def resume(self, now=None):
        """The gate lifted. Intro-end is a tolerant moment; this arms it.

        Deliberately synchronous and I/O-free: the caller's next ``step(...,
        tolerant=True)`` does the work, so a resume cannot itself stall the frame
        that ended the intro.
        """

        self._quiesced = False
        now = self._clock() if now is None else now
        self._emit("resumed", starved_ms=self._starved_for(now))
        return True

    def set_establishment_allowed(self, allowed):
        """OWNER RULING #22: whether a NEW establishment may start right now.

        Placement's WSS gate. It affects only the CADENCE reauthorization in
        :meth:`_maybe_reauthorize`; a true expiry is never gated. Synchronous
        and I/O-free -- the caller's next pumped ``step`` reads the flag."""

        self._establishment_allowed = bool(allowed)
        return self._establishment_allowed

    def set_unreachable_sink(self, sink):
        """Who to notify when this badge demotes because nothing answered.

        THE FACT TRAVELS OUT, THE REMEDY DOES NOT COME IN. This module cannot
        import Badgeware, holds no credential, and knows nothing about DNS, TLS
        or the poll transport's internals -- ``poll_loop`` is contractually just
        ``pull_forward`` plus ``state``. So the only thing said here is "the
        endpoint I was pointed at did not answer, three sessions running"; what
        that is worth is entirely the product's call. `network_runtime` wires it
        to the shared address cache, which is the one thing that can be wrong in
        a way this module can never observe.

        Synchronous, I/O-free and contained at the call site; ``None`` unwires."""

        self._unreachable_sink = sink if callable(sink) else None
        return self._unreachable_sink is not None

    def set_action_sink(self, sink):
        """Who ACTS on a validated broadcast.  ``None`` unwires.

        THE ACTION TRAVELS OUT, THE VOCABULARY DOES NOT COME IN. This module
        imports nothing but ``asyncio`` (see the module docstring) and
        `effect_library` is a sibling in the same flat `/system/lib`, so it must
        not resolve, interpret or apply a verb -- the same rule that put
        ``target_uid`` in the constructor rather than a `machine` import here.
        What leaves is exactly what the envelope proved:
        ``(action_id, action_type, payload, receipt_delay_ms)``, four positional
        arguments.

        THE DELAY IS PASSED RATHER THAN APPLIED because this module cannot queue
        anything -- it has no transport and no clock the product shares -- and
        because the product is the only side that knows a RECEIPT is the thing
        being delayed. See ``_on_event``.

        Synchronous, I/O-free and contained at the call site. Set ONCE per
        service by `network_runtime._service_push`, beside the unreachable sink
        and for the same reason: it is a bound method of an object that outlives
        every doorbell.
        """

        self._action_sink = sink if callable(sink) else None
        return self._action_sink is not None

    def _deliver_action(self, action, receipt_delay_ms):
        """Hand one validated action to the product.  Never raises.

        Contained exactly like `_note_unreachable`, and the containment is NOT
        symmetric with it: this one runs on the delivery path of the only
        mechanism the badge still has for a remote moment, inside `_on_event`,
        which layer 2 calls from a drain loop inside a rendered frame. A product
        sink that throws must cost this badge one action and one counter, never
        the socket every later action arrives on.

        Answers whether the product took it, which is what `_on_event` reports as
        a rung doorbell -- so ``doorbells_rung`` keeps meaning "rings that
        reached something" rather than "rings that arrived".
        """

        sink = self._action_sink
        if sink is None:
            # A validated action with nowhere to go. Counted, not emitted: a link
            # whose product never wired the seam would say this on every
            # broadcast of the event, and the counter already says it once.
            self.actions_dropped += 1
            return False
        try:
            taken = sink(action[0], action[1], action[2], receipt_delay_ms)
        except Exception as exc:
            self.contained_errors += 1
            self.actions_dropped += 1
            self.last_error = _error_text(exc)
            return False
        if not taken:
            self.actions_dropped += 1
            return False
        self.actions_delivered += 1
        return True

    # -- the per-frame pump ------------------------------------------------

    async def step(self, now=None, tolerant=False, network_enabled=True):
        """One cooperative step. Returns the number of doorbells rung.

        ``tolerant=False`` (the normal frame) NEVER starts a socket, whatever is
        overdue: it services what exists, runs layer 2's timers, advances an ON
        attempt that was admitted earlier, and rings the doorbell.
        ``tolerant=True`` is the OFF artifact's blocking admission path and is
        only correct where the caller has already accepted a stall. The ON
        artifact calls :meth:`admit_establishment` instead and this method only
        resumes/reaps its held task.

        Every exception is contained: push failing must never be able to take
        down a badge, and this pump runs inside the launcher's frame loop.
        """

        now = self._clock() if now is None else now
        rung = 0
        if self._boot_ready_at_ms is None:
            # The first pumped frame is when this boot's clock starts, not when
            # the object was constructed: `install()` runs before the launcher's
            # first frame and the difference is not ours to guess at.
            self._boot_ready_at_ms = _ticks_add(now, self.boot_delay_ms)
        try:
            if not self._establishment_open(now, network_enabled):
                # Not a push-path failure: the wearer, the venue or the demotion
                # rule said no, and none of those may feed the demotion counter.
                #
                # `_establishment_open` RATHER THAN `push_allowed` (§5.3), so a
                # due or in-flight demotion probe is not torn down as
                # `not_allowed` on the very frame it was admitted. While the
                # probe establishes, its armed tick is in the past, so the gate
                # keeps answering yes until the probe resolves and re-arms.
                await self._ensure_closed(
                    "not_allowed", count_failure=False,
                    polite=not self._held_strategy,
                )
                self._last_step_ms = now
                return 0
            if self._establishing:
                # Reap only a DONE task. Awaiting a parked task here would turn
                # the ordinary frame back into run-until-connect-completes.
                if self._establish_aborting:
                    await self._abort_establishment()
                    self._last_step_ms = self._clock()
                    return 0
                terminal = await self._reap_establishment()
                self._last_step_ms = self._clock()
                if terminal or self._establishing:
                    return 0
            if self._starved(now):
                # Card obligation 7(c): a socket nobody serviced across a gap
                # longer than the heartbeat ceiling is not a socket we may
                # assume. Drop it and let backoff schedule the next attempt.
                # Our own gate starved it, so it is not the network's failure.
                self.starvation_drops += 1
                self._emit("starved", gap_ms=self._starved_for(now))
                await self._ensure_closed(
                    "starved", count_failure=False,
                    polite=not self._held_strategy,
                )
            self._last_step_ms = now
            if self._session_open:
                rung = await self._service(now)
                if self._refused_close_pending:
                    # HALF A's DEFERRED CLOSE, ahead of the reauthorization
                    # check because a socket we have decided to drop must not
                    # first be handed a fresh token. `count_failure=True` is what
                    # makes the never-joined refusal advance the demotion
                    # counter; `retry=False` keeps re-establishment under our own
                    # slow gate (Half B) rather than layer 2's auto-reconnect.
                    #
                    # TWO ROUTES REACH IT and the reason says which: an
                    # authorization REFUSAL, or `JOIN_TIMEOUT_LIMIT` joins the
                    # server never answered. They need the same close for
                    # opposite-looking evidence -- one is a "no", the other a
                    # silence -- and an operator must be able to tell them apart
                    # in the log.
                    reason = (CLOSE_JOIN_UNANSWERED
                              if self._join_timeouts >= JOIN_TIMEOUT_LIMIT
                              else CLOSE_JOIN_REFUSED)
                    self._refused_close_pending = False
                    # A SESSION THAT ALREADY JOINED IS NOT CHARGED FOR THIS. The
                    # counter means "consecutive sessions that never reached a
                    # JOIN", and `joined` cannot answer that here -- the
                    # `channel_error` which caused this close already cleared it.
                    # `_session_joined` is the field that still can.
                    await self._ensure_closed(
                        reason, count_failure=not self._session_joined,
                        polite=not self._held_strategy, retry=False,
                    )
                else:
                    await self._maybe_reauthorize(now)
            elif tolerant and not self._quiesced:
                await self._maybe_connect(now)
        except Exception as exc:  # containment is the whole contract
            self.contained_errors += 1
            self.last_error = _error_text(exc)
            self._emit("contained", error=self.last_error)
            try:
                await self._ensure_closed(
                    "contained", polite=not self._held_strategy)
            except Exception:
                self._forget_session()
        return rung

    def ring_scope(self, topic):
        """``"badge"`` or ``"fleet"`` for one ring's topic.

        ``"fleet"`` for a topic that is not this badge's private one, which is
        the shape a shared fleet channel would have. ``"badge"`` otherwise --
        including for a ring with no topic at all, because a frame layer 2
        delivered without one is this badge's channel by construction.

        ⚠ **AND THAT LAST SENTENCE IS FALSE ONCE THE PRIMARY TOPIC IS THE FLEET'S,
        which is why the first branch below exists.** Under the shared-token shape
        this link holds ONE channel and it is `event:doorbell`, shared with 799
        other badges; there is no private channel left for an untopiced frame to
        have come from. Answering ``"badge"`` for it would hand `ring_delay_ms` a
        badge-scoped ring, and with a `fleet_topic` registered that returns 0 ms
        -- so one broadcast would put 800 polls inside the fan-out window, which
        is the exact herd this jitter exists to stop. The fleet primary therefore
        classifies EVERY ring it delivers as fleet, topic or no topic.
        """

        if self._fleet_primary:
            return "fleet"
        if topic is None:
            return "badge"
        if self.fleet_topic is not None and topic == self.fleet_topic:
            return "fleet"
        if topic == self.topic:
            return "badge"
        return "fleet"

    def ring_delay_ms(self, topic=None):
        """How long this ring's poll waits.  Drawn PER RING, never cached.

        Per ring rather than per boot, unlike ``boot_delay_ms``: the boot jitter
        spreads badges that booted together and stays fixed because the boot is
        the event; a ring is a NEW correlated event each time, and a fixed offset
        would put the same 800 badges back in the same order at the same spacing
        on every ring.

        Zero when the jitter is configured off, and zero for a ring the caller
        has declared badge-scoped by giving this object a ``fleet_topic`` -- see
        :data:`RING_JITTER_MIN_MS` for why the default is to jitter everything.

        ON THE FLEET PRIMARY NOTHING IS EVER ZERO, and that is the point: every
        ring on `event:doorbell` is one of up to 800 arrivals of the same
        broadcast, so :meth:`ring_scope` answers ``"fleet"`` unconditionally and
        the badge-scoped shortcut below is unreachable there.
        """

        span = self.ring_jitter_max_ms - self.ring_jitter_min_ms
        if self.ring_jitter_max_ms <= 0:
            return 0
        if self.fleet_topic is not None and self.ring_scope(topic) == "badge":
            # A server that publishes fleet rings on a shared topic has made the
            # scope legible, so a per-badge ring can go back to being instant.
            return 0
        try:
            fraction = self._rand01()
        except Exception:
            fraction = 0.5
        if fraction < 0:
            fraction = 0.0
        elif fraction >= 1:
            fraction = 0.999
        return self.ring_jitter_min_ms + int(fraction * span)

    async def note_tolerant_moment(self, moment, now=None, network_enabled=True):
        """Convenience for a caller that has just reached a named tolerant moment."""

        if moment not in TOLERANT_MOMENTS:
            raise ValueError("unknown tolerant moment: {}".format(moment))
        self.last_moment = moment
        if moment == MOMENT_INTRO_COMPLETE:
            self.resume(now)
        return await self.step(now, tolerant=True, network_enabled=network_enabled)

    async def admit_establishment(
        self,
        moment,
        now=None,
        network_enabled=True,
        radio_generation=None,
    ):
        """Admit one WSS establishment without awaiting it to completion.

        The moment is consumed only when this returns ``True``.  A live owner,
        boot jitter or reconnect backoff returns ``False`` so NetworkService can
        retain the moment.  A credential preflight failure returns ``True``:
        the moment did reach the attempt boundary and the existing typed
        ``token_unusable`` accounting is its terminal result.

        The task is deliberately detached from this short admission coroutine,
        but never unowned: ordinary frame pumps advance it, ``step`` reaps it,
        and every administrative exit cancels and awaits it before releasing the
        PushService.  That is the same held-task mechanism Realtime already uses
        for its receive path on the shipping MicroPython scheduler.
        """

        if moment not in TOLERANT_MOMENTS:
            raise ValueError("unknown tolerant moment: {}".format(moment))
        self._held_strategy = True
        now = self._clock() if now is None else now
        if self._boot_ready_at_ms is None:
            self._boot_ready_at_ms = _ticks_add(now, self.boot_delay_ms)
        if moment == MOMENT_INTRO_COMPLETE:
            self.resume(now)
        accepted = await self._start_establishment(
            now,
            network_enabled=network_enabled,
            moment=moment,
            radio_generation=radio_generation,
        )
        self._last_step_ms = self._clock()
        if accepted:
            self.last_moment = moment
        return accepted

    async def stop(self, reason="stopped", polite=True, retry=False):
        """Close the socket and forget the session. Idempotent.

        ``polite=False`` skips the WebSocket close handshake -- see
        :meth:`_ensure_closed`. The blocking artifact uses courtesy writes;
        NB-0's held strategy cannot spend their two 5 s deadlines in an
        administrative frame, and a radio `wifi_lost` edge already knows the
        peer is unreachable. Either way this is not a failed session:
        ``count_failure=False`` is not a parameter here and must not become one,
        because every reason a caller has to call `stop` is the badge's own
        decision.
        """

        await self._ensure_closed(
            reason,
            count_failure=False,
            polite=polite,
            retry=retry,
        )
        return True

    # -- internals ---------------------------------------------------------

    def _starved_for(self, now):
        if self._last_step_ms is None:
            return 0
        return max(0, _ticks_diff(now, self._last_step_ms))

    def _starved(self, now):
        return (
            self._session_open
            and self._last_step_ms is not None
            and self._starved_for(now) >= self.starvation_ms
        )

    async def _service(self, now):
        """Drain what has already arrived, bounded, and ring for what is ours.

        Layer 2's ``service()`` handles at most one frame per call. The shipping
        producer now emits one room-wide ``fleet_actions`` frame, so the old
        per-badge command burst is gone; this bounded loop remains because a
        delayed socket or a future producer can still batch frames ahead of the
        heartbeat reply. It cannot become a blocking drain: each call is the
        same non-blocking step, and the loop stops as soon as no frame is ready.
        Four ≤2 KB decodes bound the work inside one rendered frame.
        """

        rung = 0
        for _ in range(FLEET_DRAIN_MAX):
            events = await self.client.service()
            if not events:
                # Nothing was in hand. On an idle socket this is the first
                # iteration and the loop costs one non-blocking call.
                break
            for event in events:
                rung += self._on_event(event, now)
            if not self._session_open:
                # A frame ended the session (a drop, a refusal). Layer 2 has no
                # socket to read from and `_on_event` has already recorded it.
                break
        return rung

    def _on_event(self, event, now):
        kind = event.kind
        if kind == KIND_BROADCAST:
            # THE DOORBELL IS THE COURIER NOW, AND THIS IS THE SEAM. D9 said "a
            # broadcast pulls the next poll forward and does nothing else", and
            # that was correct for exactly as long as a durable `badge_commands`
            # row was the thing being pulled forward TO. The queue is deleted, so
            # the only copy of the moment is the one in this payload: it is
            # validated whole (`_reliable_doorbell_payload`) and handed OUT
            # through `_action_sink`. Do not restore the one-bit reading without
            # restoring the queue behind it -- with no queue, "ring and go look"
            # rings and finds nothing, forever.
            #
            # WHAT DID NOT CHANGE, and must not: the validation is exactly as
            # strict, the positive target match still decides whether this badge
            # is addressed at all, and nothing this module cannot positively
            # identify reaches the product. The strictness got MORE load-bearing,
            # not less -- see `_fleet_action_for_me`.
            #
            # AND THIS MODULE STILL DOES NOT ACT. It imports nothing but asyncio,
            # holds no credential and has never heard of `effect_library`; the
            # action travels out the way `target_uid` travelled in. Layer 3 owns
            # the vocabulary, the frame budget and the receipt.
            #
            # THE TOPIC is read as before, for routing and the jitter; it is
            # already trusted, because layer 2 refuses a frame for a channel it
            # did not join.
            if self.ring_scope(getattr(event, "topic", None)) == "fleet":
                action = self._fleet_action_for_me(event)
                if action is None:
                    self.doorbells_filtered += 1
                    # ONE LINE PER BOOT, AND THE COUNTER CARRIES THE REST. The
                    # current producer targets the whole fleet, so suppression
                    # should be rare, but a malformed or future targeted burst
                    # must not flood the serial console. The first line proves
                    # the filter is running; the snapshot carries the quantity.
                    if self.doorbells_filtered == 1:
                        self._emit("ring_filtered", scope="fleet",
                                   filtered=self.doorbells_filtered)
                    return 0
                self.doorbells += 1
                # THE JITTER IS THE RECEIPT'S NOW, NOT THE ACTION'S, and that
                # swap is the point. It used to delay the POLL, which was fine
                # when the poll WAS the delivery. Delaying the ACTION would start
                # one synchronised light show at ~1,000 different random moments
                # across a five-second window -- destroying the fleet synchrony
                # the show exists for. So the action fires immediately and the
                # WRITE-BACK carries the spread instead: ~1,000 receipts into
                # `fleet_receipts` inside one fan-out window is the stampede
                # worth stopping, and nobody is watching that one happen.
                delay = self.ring_delay_ms(getattr(event, "topic", None))
                if self._deliver_action(action, delay):
                    self.doorbells_rung += 1
                    return 1
                return 0
            # -- THE PRIVATE TOPIC, BELOW, IS UNCHANGED AND THAT IS DELIBERATE --
            #
            # It is already unreachable in production: `device_push_factory`
            # passes `event_topic(EVENT_DOORBELL_NAME)` as the primary topic, so
            # `_fleet_primary` is True and `ring_scope` answers "fleet"
            # unconditionally. Only a dev badge on its own per-badge token and
            # the CX-9 fixtures come through here.
            #
            # SO IT KEEPS THE OLD MEANING OF A RING, pull_forward included. Two
            # reasons, and the second is the real one. It is the ECHO filter for
            # a per-command status stream that carries no action to act on, so
            # there is nothing here for the new path to deliver -- and it belongs
            # to the same deletion that removes `_is_own_ack`, `STATUS_QUIET`,
            # `BROADCAST_PAYLOAD_KEYS` and `badge_topic`, which is a separate cut
            # of ~200 lines of dead branch. Half-rewriting it here would leave
            # that cut harder to make and its tests (`test_cx9_status_rings`)
            # asserting a third thing that was never true of either design.
            if self._is_own_ack(event):
                self.doorbells_filtered += 1
                self._emit("ring_filtered",
                           status=self._broadcast_status(event),
                           filtered=self.doorbells_filtered)
                return 0
            self.doorbells += 1
            delay = self.ring_delay_ms(getattr(event, "topic", None))
            if self.poll_loop.pull_forward(now, reason="realtime",
                                           delay_ms=delay):
                self.doorbells_rung += 1
                return 1
            return 0
        if kind == KIND_JOINED:
            self.joined = True
            # A recovered session must not continue narrating the failure from
            # the session before it. The first physical P6 soak ended joined
            # while snapshot.last_error still named its pre-grant 403.
            self.last_error = None
            self.sessions_joined += 1
            self._join_timeouts = 0
            self._session_joined = True
            self.policy.note_session_joined()
            if self.policy.demoted:
                # A PROBE JOINED, so clear the demotion -- and this REVERSES the
                # never-clear rule `note_session_joined` was written with. That
                # rule's reasoning was "clearing it here would let one lucky join
                # re-arm an unbounded retry loop", and it was right about the loop
                # it could see: before §5.3 the only thing that could produce this
                # join was a fast retry. Now the retry that produced it is the
                # SLOW one -- one jittered attempt per 15-30 minutes, bounded by
                # `REDEMOTE_RETRY_MIN_MS` -- so a join here means the path
                # demonstrably works on this network, which is the only thing
                # demotion ever claimed was false. No reboot required.
                self.policy.clear_demotion()
                self._demote_retry_at_ms = None
                cleared = self.demote_cause
                self.demote_cause = None
                self._emit("demote_cleared", reason=cleared)
            self._emit("joined")
            return 0
        if kind == KIND_DISCONNECTED:
            self.last_error = event.reason
            self._close_session("dropped")
            return 0
        if kind in (KIND_JOIN_ERROR, KIND_CHANNEL_ERROR):
            self.joined = False
            self.last_error = event.reason
            self._emit(kind, reason=event.reason)
            if event.reason == JOIN_TIMEOUT_REASON:
                # AN UNANSWERED JOIN, WHICH IS NEITHER A REFUSAL NOR A BLIP AFTER
                # THE THIRD ONE. See JOIN_TIMEOUT_LIMIT: layer 2 will rejoin this
                # same socket forever, so without a bound the badge sends a
                # `phx_join` every ≤30 s for the rest of the boot and never
                # demotes. Deferred to `step()` like every other close, because
                # this method is synchronous (F1).
                self._join_timeouts += 1
                if self._join_timeouts >= JOIN_TIMEOUT_LIMIT:
                    self._refused_close_pending = True
            if kind == KIND_JOIN_ERROR:
                # HALF A OF THE RETRY STATE MACHINE (§5.2). `_note_revoked`
                # DECLINES a refusal on a socket that never joined -- correctly,
                # because that is the demotion path's case and not a revocation
                # -- and until 2026-08-26 declining meant NOTHING HAPPENED. The
                # socket stayed open, layer 2 rejoined the errored channel on its
                # own backoff (1 s -> 30 s cap), and the badge sent a refused
                # `phx_join` every 15-30 s plus a fresh TLS handshake every
                # cadence, for the rest of the boot, while `mode()` read
                # "Connecting" forever. `failed_sessions` never moved either,
                # because the cadence closes with `count_failure=False`, so the
                # demotion that would have made the state legible never came.
                #
                # NOW: record the intent and let `step()` close it. The close
                # counts a failure, so three refusals reach MODE_DEMOTED like any
                # other never-joined failure -- but the socket is OFF THE WIRE
                # between tries instead of standing in a refused-join storm.
                #
                # ONLY AN AUTHORIZATION REFUSAL. A rate limit or a transient
                # database fault is layer 2's to retry and it clears itself; only
                # a persistent refusal is the herd load, and it is what T5
                # simulates.
                if not self._note_revoked(event.reason):
                    if (is_revocation_reason(event.reason)
                            and not self.policy.revoked):
                        self._refused_close_pending = True
                # THE OTHER HALF OF THE REAUTHORIZATION CADENCE. Crossing an
                # authorization boundary is only useful if the badge acts on the
                # answer, and "refused" is an answer. Without this the cadence
                # turns a revoked badge into a permanent load: layer 2 rejoins
                # the errored channel on its own jittered backoff (1 s -> 30 s
                # cap), so the badge would send a refused `phx_join` every
                # 15-30 s AND pay a fresh TLS handshake every cadence, for the
                # rest of the boot, while `mode()` read "Connecting" forever. It
                # would never demote either: the cadence closes with
                # ``count_failure=False``, exactly as it should, so
                # ``failed_sessions`` never moves.
        return 0

    def _broadcast_status(self, event):
        """The ``status`` a ``command_status`` broadcast carries, or ``None``.

        ``None`` for every shape that is not one: a different event, a payload
        that is not a mapping, a missing or non-string status. FAIL-OPEN is the
        caller's rule and this function's job is only to answer honestly.
        """

        if getattr(event, "event", None) != BROADCAST_COMMAND_STATUS:
            return None
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return None
        status = payload.get("status")
        if not isinstance(status, str) or not status:
            return None
        return status

    def _own_ack_status(self, event):
        """The status of a broadcast that is PROVABLY this badge's own echo.

        ``None`` unless the payload is the producer's WHOLE shape
        (:data:`BROADCAST_PAYLOAD_KEYS`): all five keys, no sixth, each of the
        trigger's types, and a ``badge_id`` equal to this badge's own. Every
        departure answers ``None``, which rings.

        THE FIVE-FIELD CHECK IS THE FIX AND THE `badge_id` IS ITS POINT. Until
        2026-08-23 this decision was event-name + mapping + non-empty status, so
        ``{"status": "applied"}`` -- a payload no producer sends, about no badge
        in particular -- was silenced. The statuses in :data:`STATUS_QUIET` are
        quiet for one reason only: THIS badge's own poll and its own ack are what
        caused them. A payload that cannot show that is not covered by the
        argument.

        THE TOPIC IS DELIBERATELY NOT PART OF THE DECISION. Layer 2 refuses a
        frame for a channel it did not join, so the topic is already trusted --
        and the payload's ``badge_id`` is the stronger claim anyway, because a
        shared fleet channel would carry the same topic for every badge.
        """

        status = self._broadcast_status(event)
        if status is None:
            return None
        mine = self.badge_id
        if mine is None:
            return None
        payload = getattr(event, "payload", None)
        if len(payload) != len(BROADCAST_PAYLOAD_KEYS):
            return None
        for key in BROADCAST_PAYLOAD_KEYS:
            if key not in payload:
                return None
        if payload["badge_id"] != mine:
            return None
        if not _nonempty_text(payload["command_id"]):
            return None
        if not _nonempty_text(payload["at"]):
            return None
        attempts = payload["delivery_attempts"]
        if isinstance(attempts, bool) or not isinstance(attempts, int):
            return None
        if attempts < 0:
            return None
        return status

    def _is_own_ack(self, event):
        """Whether this broadcast is one the badge has nothing to fetch for.

        TRUE for exactly one shape and FALSE for everything else, which is the
        whole safety argument (CX-9). The producer's OWN five-field
        ``command_status`` about THIS badge, naming a status in
        :data:`STATUS_QUIET`, is a transition the badge's own exchange caused --
        or an owner cancelling a row it will never be handed -- so pulling a poll
        forward for it buys a request that finds nothing. An unknown event, an
        unreadable payload, a payload that is not the producer's whole shape
        (:func:`_own_ack_status`), another badge's status, an unknown FUTURE
        status and ``queued`` itself all answer False and RING.

        WHY NOT `status != "queued"`: it is one character shorter and it silences
        every status this fleet has not been taught yet. The asymmetry of the two
        mistakes decides it -- a needless ring costs one poll, a missing ring
        costs a command sitting for up to the 30 s idle cadence in front of a
        wearer who was promised an instant light show.
        """

        status = self._own_ack_status(event)
        return status is not None and status in STATUS_QUIET

    def _fleet_target_is_me(self, event):
        """Does this fleet broadcast positively name THIS badge or ``all``?

        THE BOOLEAN QUESTION, kept because the diagnostics and the negative
        tests ask it and because one implementation should answer both forms.
        The live path calls :meth:`_fleet_action_for_me` and uses what comes
        back.
        """

        return self._fleet_action_for_me(event) is not None

    def _fleet_action_for_me(self, event):
        """The action this fleet broadcast carries FOR THIS BADGE, or ``None``.

        THE ONE PREDICATE THE SHARED CHANNEL IS SAFE UNDER, and its direction is
        the opposite of :meth:`_is_own_ack`'s. Every one of ~1,000 badges receives
        every publish on `event:doorbell`, so the fail-OPEN rule that is right on
        a private topic ("anything I cannot identify as my own echo is news") is
        the herd catastrophe here. The positive match is the whole safety
        argument: this badge's own hardware id, or the reserved ``all`` sentinel,
        on an exact envelope whose top-level ``id`` equals its ``action_id``.
        Missing, null, wildcard, malformed and future shapes are silence.

        ⚠ **THE ASYMMETRY THAT CHOSE THIS DIRECTION HAS CHANGED SIDES, AND THE
        DIRECTION STILL HOLDS.** The old argument was "fail-safe because polling
        is the floor": a missed ring cost this badge one idle cadence against a
        durable row the next poll collected anyway, so silence was nearly free.
        **That sentence is now false.** There is no durable row and no poll
        behind it, so a dropped ring is a CORRECTNESS loss -- this badge simply
        misses the show, and the console reports it silent. The direction is
        unchanged anyway, because the other mistake got worse at the same time
        and by more: a ring accepted without proof it was addressed is no longer
        one wasted request, it is ~1,000 badges rendering something nobody chose,
        and unlike a missed show it cannot be undone by the next broadcast.

        **AND THE LEGACY FALL-THROUGH IS CLOSED.** A payload carrying only
        ``badge_id`` used to ring unconditionally, for receiver compatibility
        with the deployed per-row publisher: tightening it would have stranded a
        valid old producer that durable polling could recover from anyway. Both
        halves of that reasoning are gone. There is no old producer left to
        strand -- the queue it published from is deleted -- and there is no
        durable recovery behind it. What the fall-through would admit NOW is an
        envelope with no action in it at all, which is either a message from
        something this firmware does not understand or a truncated one, and
        neither is a thing to act on. It answers ``None``.
        """

        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return None
        if getattr(event, "event", None) != EVENT_DOORBELL_NAME:
            # The topic admitted the frame; the event name says which publisher
            # on it spoke. A future event sharing the topic is not this contract.
            return None
        target = payload.get(FLEET_TARGET_KEY)
        if target == RELIABLE_ALL_TARGET:
            # `all` is self-authenticating only as a SHAPE, not as authority:
            # the channel's RLS already admitted the producer, and the exact
            # envelope keeps a typo or future message from becoming a herd.
            return _reliable_doorbell_payload(payload)
        if self.target_uid is None or target != self.target_uid:
            # No injected hardware id means this object cannot prove a targeted
            # ring is its own. The explicit `all` shape above needs no such
            # proof, which is why it is tested first.
            return None
        return _reliable_doorbell_payload(payload)

    def _note_revoked(self, reason):
        """A refused join from a server that had already let this badge in.

        TWO GUARDS, and each rules out a different false positive:

        * the reason must carry the server's ``Unauthorized`` error code, so a
          rate limit or a database outage stays transient
          (:func:`is_revocation_reason`);
        * this boot must have JOINED at least once, so a badge that has never
          got a doorbell up takes the demotion path it was designed for. A first
          join refused at a venue whose policy is not deployed yet is a
          never-joined session, not a revocation.

        The socket is not closed here. The next ``step`` sees
        ``push_allowed() == False`` and takes the existing, proven
        ``not_allowed`` close — one frame later, which is well inside layer 2's
        minimum rejoin delay, so no further join reaches the wire. Doing it here
        would mean an ``await`` inside the event walk for no gain.
        """

        if self.policy.revoked or not is_revocation_reason(reason):
            return False
        if self.sessions_joined < 1:
            return False
        if not self.policy.note_revoked():
            return False
        # `source=push` NAMES THE EMITTER. `policy.note_revoked()` above is what
        # makes this at most ONE line per boot from THIS object; the field is for
        # the other two, which are the poll transport's own terminal and the
        # service's boot-wide stop. Independent by design: neither transport waits
        # for the other to notice a revocation, so a reader has to be able to say
        # WHICH one is talking. See `polltransport.SOURCE_POLL`.
        self._emit("revoked", reason=reason, revocations=self.policy.revocations,
                   source=SOURCE_PUSH)
        return True

    async def _maybe_connect(self, now):
        # Independent of wants_connect(): direct callers and a retained tolerant
        # moment must not be able to re-enter a parked owner.
        if self._establishing:
            return False
        if self._boot_ready_at_ms is not None and _ticks_diff(
            now, self._boot_ready_at_ms
        ) < 0:
            # The boot herd. Nothing is built yet either, so a badge that never
            # reaches the delay has spent no heap on a client it cannot use.
            return False
        client = self.client
        if client is None:
            client = self._build_client()
        delay = client.reconnect_delay_ms(now)
        if delay is not None and delay > 0:
            return False
        # Read the credential HERE, not at construction: every reconnect is a
        # reauthorization, so the join must carry whatever the provider holds
        # now. On a closed socket `set_access_token` only records the value, so
        # this is the whole mechanism behind "force reauthorization by rejoining".
        try:
            token = self._current_token()
            if token is None:
                raise ValueError("no access token available")
            boundary = self._forced_reason(now)
            if boundary is not None:
                # The credential the provider just handed over is already past a
                # boundary. Opening a socket to have it torn down is worse than
                # not opening one, and after DEMOTE_AFTER_SESSIONS tries the
                # badge stops asking — polling keeps running and is the thing
                # that will receive the server's actual verdict.
                raise ValueError("credential past its {} boundary".format(boundary))
            await client.set_access_token(token)
        except Exception as exc:
            # Fail CLOSED: no plausible token, no socket. Polling is unaffected
            # and will get its own 401/403 verdict from PostgREST if the
            # credential is genuinely bad.
            self.last_error = _error_text(exc)
            self._note_failed_session("token_unusable")
            return False
        self.sessions += 1
        self.joined = False
        # TWO TICKS AROUND THE ESTABLISHMENT ITSELF (NB-i). `push_moment ms=` in
        # `network_runtime` prices the whole tolerant moment; this prices
        # `client.connect()` alone -- socket, TLS, Upgrade and the bounded
        # `phx_join` SENDS -- so the difference between the two numbers is the
        # moment's non-establishment work, and knowing it is the point. The join
        # REPLY is not in here: `RealtimeClient.connect` sends and returns, and
        # `service()` reaps the reply on a later frame.
        entered = self._clock()
        try:
            await client.connect()
        except Exception as exc:
            # A session that never opened is a failed session for the demotion
            # counter: from the doorbell's point of view "the handshake failed"
            # and "the join failed" are the same outcome.
            self._note_open_trace(exc.__class__.__name__, self._clock())
            self.connect_failures += 1
            self.last_error = _error_text(exc)
            self._note_failed_session("connect_failed")
            return False
        span = _ticks_diff(self._clock(), entered)
        if span < 0:
            span = 0
        self._note_open_trace("join_sent", self._clock())
        self._session_open = True
        self._token_due_ms = _ticks_add(now, self._next_cadence_ms())
        self._emit("connected", ms=span)
        return True

    async def _start_establishment(
        self,
        now,
        network_enabled=True,
        moment=None,
        radio_generation=None,
    ):
        """Latch one owner and create its held connect task.

        Everything through credential validation remains in the admission frame:
        it is bounded local work and determines whether an attempt exists at all.
        Only ``client.connect`` is parked.  The latch is installed before
        ``create_task`` so no callback, diagnostic or second moment can observe a
        connectable owner between those two operations.
        """

        if self._session_open or self._establishing or self._quiesced:
            return False
        # The third and last `_establishment_open` site (§5.3): without it the
        # probe would be admitted by the arbiter and then refused here, which is
        # a moment spent for nothing.
        if not self._establishment_open(now, network_enabled):
            return False
        if self._boot_ready_at_ms is not None and _ticks_diff(
            now, self._boot_ready_at_ms
        ) < 0:
            return False
        client = self.client
        if client is None:
            client = self._build_client()
        delay = client.reconnect_delay_ms(now)
        if delay is not None and delay > 0:
            return False
        try:
            token = self._current_token()
            if token is None:
                raise ValueError("no access token available")
            boundary = self._forced_reason(now)
            if boundary is not None:
                raise ValueError(
                    "credential past its {} boundary".format(boundary)
                )
            await client.set_access_token(token)
        except Exception as exc:
            # This is a terminal attempted admission, not arbiter deferral.  It
            # keeps the old fail-closed/demotion semantics and consumes the
            # moment so a bad credential cannot be retried every rendered frame.
            self.last_error = _error_text(exc)
            self._note_failed_session("token_unusable")
            return True

        self.sessions += 1
        self.joined = False
        self._establish_attempt += 1
        self._establish_generation += 1
        generation = self._establish_generation
        self._establishing = True
        self._establish_moment = moment
        self._establish_radio_generation = radio_generation
        self._establish_started_ms = self._clock()
        self._establish_terminal_ms = None
        self._establish_error_class = None
        self._establish_error_text = None
        self._establish_aborting = False
        self._establish_abort_reason = None
        self._establish_abort_retry = False
        self._establish_trace_closed = False
        # Keep the not-yet-scheduled coroutine as an explicit owner. A heap
        # failure inside `create_task` cannot strand a socket (connect has not
        # run), but leaving this generator to GC keeps its frame alive at the
        # exact low-memory edge that refused the task allocation.
        runner = self._run_establishment(generation, client)
        try:
            self._establish_task = asyncio.create_task(runner)
        except Exception as exc:
            closer = getattr(runner, "close", None)
            if callable(closer):
                try:
                    closer()
                except BaseException:
                    pass
            # A scheduler/heap failure happened after the attempt counter moved,
            # so it is one natural failed attempt.  There is no detached task to
            # reap and no socket owner yet, but all latch fields still clear at
            # this same terminal edge.
            terminal = self._clock()
            try:
                abort = getattr(client, "abort_connect", None)
                if callable(abort):
                    await abort(retry=True)
                rebase = getattr(client, "rebase_reconnect", None)
                if callable(rebase):
                    rebase(terminal)
            except BaseException as cleanup_exc:
                # Scheduler/heap failure must still fail soft. Cleanup is a
                # separate contained diagnostic, never a second failed session.
                self.contained_errors += 1
                self.last_error = _error_text(cleanup_exc)
                self._emit("close_failed", error=self.last_error)
            self._trace_establishment(exc.__class__.__name__, terminal)
            self._clear_establishment()
            self.connect_failures += 1
            self.last_error = _error_text(exc)
            self._note_failed_session("connect_failed")
        return True

    async def _run_establishment(self, generation, client):
        """The detached task body.  It never lets an exception detach with it."""

        error_class = None
        error_text = None
        try:
            await client.connect()
        except BaseException as exc:
            # MicroPython CancelledError derives from BaseException.  Storing it
            # keeps the task itself successful, so its exception handler cannot
            # report a crash one frame before the owner gets to reap it.
            error_class = exc.__class__.__name__
            error_text = _error_text(exc)
        terminal = self._clock()
        if (
            not self._establishing
            or generation != self._establish_generation
            or self._establish_aborting
        ):
            return False
        self._establish_terminal_ms = terminal
        self._establish_error_class = error_class
        self._establish_error_text = error_text
        # The result stays TENTATIVE until the owning root coroutine reaps it.
        # A radio/admin edge observed before that site must be able to classify
        # the attempt as aborted rather than publish a stale socket or a network
        # failure caused by the radio edge itself.
        return error_class is None

    async def _reap_establishment(self):
        """Publish one done task, or return False without waiting for network."""

        task = self._establish_task
        if not self._establishing or task is None or not task.done():
            return False
        await_error_class = None
        await_error_text = None
        try:
            await task
        except BaseException as exc:
            # Cancellation before the coroutine's first instruction never enters
            # `_run_establishment`'s try.  Administrative cancellation is handled
            # below; an otherwise unexplained one is a natural terminal failure.
            await_error_class = exc.__class__.__name__
            await_error_text = _error_text(exc)
        if self._establish_aborting:
            await self._abort_establishment()
            return True
        error_class = self._establish_error_class or await_error_class
        error_text = self._establish_error_text or await_error_text
        terminal = self._establish_terminal_ms
        if terminal is None:
            terminal = self._clock()
        entered = self._establish_started_ms
        span = 0 if entered is None else _ticks_diff(terminal, entered)
        if span < 0:
            span = 0
        # Both retry and cadence are armed at the ownership commit, never at the
        # child terminal tick. Frame arbitration can deliberately delay this
        # site; a stale base would make retry immediately due or cadence early.
        reap_now = self._clock()
        if error_class is not None:
            # A failed connect can still own an upgraded response, receive task
            # or raw/TLS transport.  Realtime's abort is idempotent and only
            # schedules a retry when its own failure path has not already done
            # so, which makes this the single deterministic cleanup site.
            client = self.client
            try:
                abort = getattr(client, "abort_connect", None)
                if callable(abort):
                    await abort(retry=True)
                else:
                    abrupt = getattr(client, "close_transport", None)
                    if callable(abrupt):
                        await abrupt()
                rebase = getattr(client, "rebase_reconnect", None)
                if callable(rebase):
                    rebase(reap_now)
            except BaseException as exc:
                self.contained_errors += 1
                self.last_error = _error_text(exc)
                self._emit("close_failed", error=self.last_error)
            self._trace_establishment(error_class, terminal)
            self._clear_establishment()
            self.connect_failures += 1
            self.last_error = error_text or error_class
            self._note_failed_session("connect_failed")
            return True
        if _ticks_diff(reap_now, terminal) >= self.starvation_ms:
            # The task completed while the shared frame arbiter withheld its
            # owner.  Its heartbeat/timers have already gone unserviced for a
            # whole starvation ceiling, so it is not a healthy socket to hand
            # off.  This is our scheduling edge, not a push failure.
            self._request_establishment_abort(
                "starved_before_handoff", retry=True)
            await self._abort_establishment()
            return True
        self._trace_establishment("join_sent", terminal)
        # HANDOFF: every held field clears before the open session is published.
        # There is no yield in this sequence, so an observed radio edge cannot
        # interleave a stale task between ownership and `_session_open`.
        self._clear_establishment()
        self._session_open = True
        # Cadence belongs to HANDOFF, not to the child task's earlier terminal
        # tick. A frame barrier may delay reap; arming from that stale tick would
        # make the same delay recur as an early hourly reconnect.
        self._token_due_ms = _ticks_add(reap_now, self._next_cadence_ms())
        self._emit("connected", ms=span)
        return True

    def _request_establishment_abort(self, reason, retry=False):
        """Synchronously invalidate and cancel before another loop turn starts."""

        if not self._establishing:
            return False
        if not self._establish_aborting:
            self._establish_aborting = True
            self._establish_abort_reason = reason
            self._establish_abort_retry = bool(retry)
            # The running task captured the previous generation.  Any completion
            # after this line is stale even if cancel races with an already-ready
            # socket callback.
            self._establish_generation += 1
        elif retry:
            self._establish_abort_retry = True
        task = self._establish_task
        if task is not None and not task.done():
            try:
                task.cancel()
            except BaseException:
                pass
        return True

    async def _abort_establishment(self, reason=None, retry=None):
        """Drive cancellation and transport cleanup to completion, then forget."""

        if not self._establishing:
            return False
        if reason is not None:
            self._request_establishment_abort(
                reason,
                retry=False if retry is None else retry,
            )
        reason = self._establish_abort_reason or reason or "aborted"
        retry = self._establish_abort_retry if retry is None else bool(retry)
        task = self._establish_task
        if task is not None:
            if not task.done():
                try:
                    task.cancel()
                except BaseException:
                    pass
            try:
                await task
            except BaseException:
                pass
        client = self.client
        try:
            abort = getattr(client, "abort_connect", None)
            if callable(abort):
                await abort(retry=retry)
            else:
                abrupt = getattr(client, "close_transport", None)
                if callable(abrupt):
                    await abrupt()
        except BaseException as exc:
            # Cleanup failure is contained but never reclassified as a failed
            # push session: the administrative/radio edge remains the cause.
            self.contained_errors += 1
            self.last_error = _error_text(exc)
            self._emit("close_failed", error=self.last_error)
        if retry:
            # A natural failure may have drawn its retry before an observed
            # radio/admin abort won ownership. Preserve that draw but move its
            # base to this cleanup commit; otherwise a gate-delayed abort can
            # publish an already-overdue retry and reopen on the next frame.
            rebase = getattr(client, "rebase_reconnect", None)
            if callable(rebase):
                try:
                    rebase(self._clock())
                except BaseException as exc:
                    self.contained_errors += 1
                    self.last_error = _error_text(exc)
                    self._emit("close_failed", error=self.last_error)
        terminal = self._establish_terminal_ms
        if terminal is None:
            terminal = self._clock()
        self._trace_establishment("aborted", terminal)
        self._clear_establishment()
        self._forget_session()
        self._emit("establishment_aborted", reason=reason)
        return True

    def _trace_establishment(self, outcome, terminal_ms=None):
        if self._establish_trace_closed:
            return False
        self._establish_trace_closed = True
        self._note_open_trace(outcome, terminal_ms)
        return True

    def _clear_establishment(self):
        self._establishing = False
        self._establish_task = None
        self._establish_moment = None
        self._establish_radio_generation = None
        self._establish_started_ms = None
        self._establish_terminal_ms = None
        self._establish_error_class = None
        self._establish_error_text = None
        self._establish_aborting = False
        self._establish_abort_reason = None
        self._establish_abort_retry = False
        self._establish_trace_closed = False

    def _note_open_trace(self, outcome, terminal_ms=None):
        """Tell the establishment's tracer how this one ended. Never raises.

        One word, and it is either ``"join_sent"`` or the failing exception's
        CLASS name -- the same bounded vocabulary `device_link._open_phases`
        publishes as its ``outcome``, and the same reason: a class name is a
        literal the runtime spells, never a server's text.
        """

        sink = self._open_trace
        if sink is None:
            return
        try:
            sink(outcome, terminal_ms)
        except Exception:
            # Diagnostics, contained. `_service_push` would swallow this too,
            # but a broken instrument must not reach the failed-session counter
            # by way of an exception the caller reads as a failed connect.
            pass

    def _build_client(self):
        client = self._client_factory()
        client.channel(self.topic)
        if self.fleet_topic is not None:
            # A SECOND SUBSCRIPTION, and the RLS objection it used to carry is
            # GONE: this comment said a shared fleet topic "would be REFUSED by
            # RLS today" because `can_access_channel` only matched the
            # `badge:<16 hex>` tail. It has an `event:<name>` READ branch, and it
            # authorizes any identity holding `realtime/read`
            # (`badgelink/supabase/schemas/badgelink.sql:642-653`) -- which the
            # shared floor subject has, and which is how the doorbell works at
            # all. What is true is that PRODUCTION DOES NOT USE THIS SEAM: the
            # fleet topic is the PRIMARY `topic`, one channel and one handshake,
            # because `badge:<shared sub>` names the fleet rather than a badge
            # and nothing addresses it. Registered only when a caller supplies
            # one, so a two-channel fixture still works.
            client.channel(self.fleet_topic)
        self.client = client
        return client

    def _next_cadence_ms(self):
        """This session's reauthorization interval, redrawn per session.

        Called once per socket open, not per frame — the draw is the same
        ``_rand01`` the ring jitter uses and it costs two bytes of ``urandom``.
        See :data:`REJOIN_JITTER_MS` for why one draw per BOOT is not enough:
        the cadence's phase is the boot connect, so a fixed interval keeps 800
        badges reconnecting in formation forever.
        """

        if self.rejoin_jitter_ms <= 0:
            return self.token_refresh_ms
        try:
            fraction = self._rand01()
        except Exception:
            # A broken entropy source must not stop the cadence; the midpoint
            # still crosses the boundary, it just spreads nothing.
            fraction = 0.5
        if fraction < 0:
            fraction = 0.0
        elif fraction >= 1:
            fraction = 0.999
        return self.token_refresh_ms + int(fraction * self.rejoin_jitter_ms)

    async def _maybe_reauthorize(self, now):
        """Item 4a/4b: force a fresh authorization on cadence or a boundary.

        A live hosted D9 run revoked ``realtime/read``, then watched an identical
        ``access_token`` frame succeed while the old private channel kept
        receiving broadcasts for the full thirteen-minute observation. Token
        refresh updates the JWT associated with a joined channel; it is not a
        promise that Realtime re-runs that channel's RLS decision. The smallest
        fail-closed path is therefore the one already used at expiry boundaries:
        close the whole socket without charging demotion, then let the named
        tolerant-moment path pay for a fresh TLS connection and ``phx_join``.

        Same-socket leave/rejoin would avoid the measured ~735 ms TLS cost, but
        this client's current dispatcher topic-routes broadcast/error/close
        frames without filtering their old ``join_ref``. A full reconnect gives
        every frame and ref a new transport lifetime without adding a stale-frame
        state machine to a security correction.
        """

        if not self._session_open:
            return False
        forced = self._forced_reason(now)
        if forced is None:
            if self._token_due_ms is None or _ticks_diff(now, self._token_due_ms) < 0:
                return False
            if not self._establishment_allowed:
                # OWNER RULING #22: the cadence reopen is a NEW establishment, so
                # it defers out of a non-opted-in app -- closing this healthy WSS
                # now, when no re-open is allowed, would strand a mid-app command
                # on a link that was fine (spec §4.5). The due time is left in
                # place, so the moment the badge is back at the launcher / an app
                # opts in, the very next frame refreshes. A TRUE token/grant
                # expiry took the `forced is not None` branch above and is
                # unaffected: security boundaries never defer.
                return False
            forced = "cadence"
        # A cadence or boundary: disconnect, and let the tolerant-moment path
        # reconnect with whatever the provider hands over next. Our own decision
        # to rejoin is not a network failure and must never feed demotion.
        self.reauthorizations += 1
        self._emit("reauthorization_forced", reason=forced)
        await self._ensure_closed(
            "reauthorization",
            count_failure=False,
            polite=not self._held_strategy,
        )
        return True

    def _forced_reason(self, now):
        """A boundary the socket may not be ridden past, or None.

        Allocation-free by construction: it compares two cached integers against
        the epoch clock and calls nothing. That matters because this runs on
        every frame of an open session, and the steady frame must not allocate.
        A badge with no trusted epoch clock returns None rather than inventing a
        boundary from an untrusted RTC — the server is the authority on expiry,
        and polling still gets its 401/403 verdict either way.
        """

        epoch = self._epoch_now()
        if epoch is None:
            return None
        exp = self._token_exp
        if exp is not None and (exp - epoch) * 1000 <= self.token_expiry_margin_ms:
            return "token_expiry"
        expires_at = self.grant_expires_at
        if isinstance(expires_at, int) and not isinstance(expires_at, bool):
            if (expires_at - epoch) * 1000 <= self.grant_expiry_margin_ms:
                return "grant_expiry"
        return None

    def _current_token(self):
        """Ask the provider for the credential, and cache the one claim we use.

        Accepts a bare token or a ``(token, claims)`` pair so a caller can hand
        over ``credentials.Credentials`` claims without this module importing or
        decoding anything. The token itself is returned and never stored.
        """

        provided = self._token_provider()
        if isinstance(provided, tuple):
            token = provided[0]
            claims = provided[1] if len(provided) > 1 else None
        else:
            token, claims = provided, None
        self._last_claims = claims
        exp = claims.get("exp") if isinstance(claims, dict) else None
        self._token_exp = (
            exp if isinstance(exp, int) and not isinstance(exp, bool) else None
        )
        return token

    def _epoch_now(self):
        if self._epoch_clock is None:
            return None
        try:
            value = self._epoch_clock()
        except Exception:
            return None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def _note_failed_session(self, reason):
        self.sessions_failed += 1
        demoted = self.policy.note_session_failed()
        self._emit(
            "session_failed",
            reason=reason,
            failed_sessions=self.policy.failed_sessions,
            # WHICH SIDE OF THE THRESHOLD, on the line itself. "2 of 3" and
            # "3 of 3" are the whole difference between a panel that reads
            # "Connecting" forever and one that reads "Normal", and an operator
            # reading a capture could not tell them apart from the old line.
            sessions_joined=self.sessions_joined,
            demote_after=self.policy.demote_after,
            # THE REASON THE SESSION FAILED, not just the CATEGORY it failed in.
            # `reason` above is this module's own word (`connect_failed`,
            # `join_refused`, `join_unanswered`, `token_unusable`) and it says
            # WHICH branch fired; `error` is what the layer below actually said,
            # and without it a 403, a 429 and a malformed 200 all reach the log as
            # the single word `ValueError`. At the venue nobody is attaching a
            # probe to read the wire the information was already on.
            #
            # BOUNDED AT ITS SOURCE AND NOT HERE, and the two sources have two
            # different caps: a layer-2 failure reason is truncated to 120 by
            # `RealtimeEvent.__init__` (`MAX_REASON_CHARACTERS`) and an exception
            # to 160 by `_error_text`. This module deliberately adds no third cap
            # -- one applied here would be a bound unfindable from the value's own
            # type, and the printer caps the LINE regardless.
            #
            # It never reaches a glyph renderer either: `push_cause` reads this
            # string for ONE BIT and returns a baked word.
            error=self.last_error,
        )
        if demoted:
            self._emit("demoted", failed_sessions=self.policy.failed_sessions)
        if self.policy.demoted:
            # HALF B (§5.3). Armed on the DEMOTING failure and re-armed on every
            # later probe that failed -- and it has to be this branch rather than
            # the `demoted` flag above, because `note_session_failed` returns
            # True only once. That flag is the EDGE; this is the STATE, and the
            # state is what keeps the slow loop alive.
            #
            # THE CAUSE CHOOSES THE INTERVAL. A refusal and a silence are
            # different facts with different half-lives; see
            # UNANSWERED_RETRY_MIN_MS.
            if reason == CLOSE_JOIN_UNANSWERED:
                self.demote_cause = DEMOTE_CAUSE_UNANSWERED
            elif reason == CLOSE_JOIN_REFUSED:
                self.demote_cause = DEMOTE_CAUSE_REFUSED
            else:
                self.demote_cause = DEMOTE_CAUSE_UNREACHABLE
                # THE ONE DEMOTION THAT CAN BE CAUSED BY A CACHED ANSWER, so it
                # is the one that has to be able to un-cache it. A refusal and a
                # silence are both a SERVER that was reached; UNREACHABLE means
                # the socket never got there, and the badge's own resolved-once
                # address is a candidate for why.
                #
                # THE FAILURE THIS CLOSES, precisely. `SessionAddresses` holds
                # one IP per host for the whole WLAN session and only the radio
                # clears it (`wifi_lost`, `radio_stopped`). Nothing cleared it on
                # repeated FAILURE -- so if that answer went bad while the badge
                # stayed associated (a DNS failover, a venue re-homing the
                # endpoint), three sessions failed, `_arm_demote_retry` below
                # routed UNREACHABLE into the LONG window, and 15-30 minutes
                # later the badge re-probed THE SAME BAD ADDRESS. It re-armed,
                # re-probed, re-failed: the doorbell was dead for the rest of the
                # boot and no loop in the system could learn otherwise.
                #
                # ON THIS PATH ONLY, and that is the whole cost argument. The
                # next attempt now pays a blocking resolve -- `bounded_dns` caps
                # it at 1,000 ms, against the 13.1-14.0 s an unbounded
                # `getaddrinfo` costs with no route -- which is precisely the
                # cost NB_CONNECT exists to keep off the HAPPY path. It is
                # bought here once per 15-30 minute probe by a badge that
                # currently has no doorbell at all.
                self._note_unreachable()
            self._arm_demote_retry(self._clock())

    def _note_unreachable(self):
        """Tell the product the endpoint did not answer. Never raises.

        Contained like `_emit`: this runs inside the demotion bookkeeping of a
        session that has ALREADY failed, and a product sink that throws must not
        turn a recorded failure into an exception the caller never expected.
        """

        sink = self._unreachable_sink
        if sink is None:
            return False
        try:
            sink(self.demote_cause)
        except Exception as exc:
            self.contained_errors += 1
            self.last_error = _error_text(exc)
            return False
        return True

    def _arm_demote_retry(self, now):
        """Draw the next slow probe's tick. Wrap-safe, and redrawn every time.

        `_ticks_add` rather than ``now + delay`` because ``ticks_ms`` WRAPS, and
        a 15-30 minute sleep is long enough to cross the wrap on a badge that has
        been on for a while -- a raw addition would then compare wrong and either
        fire immediately or never fire at all. The draw is per arm for the reason
        the ring jitter's is per ring: a demotion is a correlated event, so a
        fixed offset would put the same 800 badges back in formation.

        THE WINDOW COMES FROM :attr:`demote_cause`: an unanswered venue gets the
        short one, because silence clears on its own and a refusal does not.
        """

        if self.demote_cause == DEMOTE_CAUSE_UNANSWERED:
            floor = UNANSWERED_RETRY_MIN_MS
            ceiling = UNANSWERED_RETRY_MAX_MS
        else:
            floor = REDEMOTE_RETRY_MIN_MS
            ceiling = REDEMOTE_RETRY_MAX_MS
        span = ceiling - floor
        try:
            fraction = self._rand01()
        except Exception:
            # A broken entropy source must not stop the retry; the midpoint
            # still crosses the interval, it just spreads nothing.
            fraction = 0.5
        if fraction < 0:
            fraction = 0.0
        elif fraction >= 1:
            fraction = 0.999
        delay = floor + int(fraction * span)
        self._demote_retry_at_ms = _ticks_add(now, delay)
        self._emit("demote_retry_armed", delay_ms=delay,
                   reason=self.demote_cause)

    def _demote_probe_due(self, now):
        """The ONE override to a demoted ``push_allowed() == False``.

        Demotion is ALWAYS the never-joined kind -- `note_session_failed` only
        advances the counter for a session that never joined -- so it is a
        statement about a network and not a verdict about this badge, and it is
        not terminal for the boot. This permits exactly one jittered
        re-establishment probe once the armed tick has elapsed.
        """

        if not self.policy.demoted or self._demote_retry_at_ms is None:
            return False
        return _ticks_diff(now, self._demote_retry_at_ms) >= 0

    def _establishment_open(self, now, network_enabled):
        """May an establishment exist right now? A PARALLEL gate, not a clear.

        `policy.demoted` is deliberately NOT cleared to let a probe through:
        `mode()` must keep reading MODE_DEMOTED, the snapshot must keep saying
        why, and every OTHER authority still means no. Network off, wearer off,
        the venue's remote kill and REVOKED are all checked here and none of them
        is overridable -- only the never-joined demotion is, and only on its own
        slow clock.
        """

        if self.policy.push_allowed(network_enabled):
            return True
        if not (network_enabled and self.policy.enabled
                and not self.policy.revoked
                and not self.policy.remote_disabled):
            return False
        return self._demote_probe_due(now)

    def _close_session(self, reason, count_failure=True):
        """Layer 2 already released the socket; record what the session was worth.

        A session that JOINED and then dropped is not a failure for the demotion
        counter: that is a working push path losing its network, which polling
        already covers and jittered reconnect already spreads. Only a session
        that never got a doorbell up counts against push.
        """

        joined = self.joined or self._session_joined
        self._session_open = False
        self.joined = False
        self._session_joined = False
        self._join_timeouts = 0
        self._token_due_ms = None
        if count_failure and not joined:
            self._note_failed_session(reason)
        else:
            self._emit("session_ended", reason=reason)

    def _forget_session(self):
        self._session_open = False
        self.joined = False
        self._session_joined = False
        self._join_timeouts = 0
        self._token_due_ms = None

    async def _ensure_closed(
        self,
        reason,
        count_failure=True,
        polite=True,
        retry=False,
    ):
        """Release the socket, and record what the session was worth.

        ``polite=True`` is the ordinary close: layer 2 leaves every joined
        channel and layer 1 sends a WebSocket CLOSE frame before the transport
        goes. That is a courtesy to the server and it costs WRITES -- one
        `phx_leave` per joined channel plus the CLOSE -- each of which drains
        under `io_timeout_ms` (5,000 ms since owner ruling #21). Against a peer
        that answers, that is microseconds; against a peer that does not, it is
        the deadline, twice, in a rendered frame.

        ``polite=False`` therefore exists for paths whose frame may not afford
        courtesy writes: the radio's `wifi_lost` edge (peer unreachable), and
        held-strategy cadence/administrative releases (the whole point of NB-0
        is that merely waiting cannot hold a rendered frame). It goes straight
        to `close_transport`, which cancels the receive task and closes the
        writer. **Nothing about the SESSION accounting changes** -- the same
        `_close_session` runs in the same `finally`, so the demotion rule, the
        counters and the emitted `session_ended` are byte-identical.

        Duck-typed at the client, so a layer 2 without `close_transport` (a
        scripted stand-in, an older vendored client) closes politely instead of
        not at all.
        """

        if self._establishing:
            await self._abort_establishment(reason, retry=retry)
        if self.client is None or not self._session_open:
            self._forget_session()
            return False
        try:
            if polite:
                await self.client.close()
            else:
                abrupt = getattr(self.client, "close_transport", None)
                if callable(abrupt):
                    await abrupt()
                else:
                    await self.client.close()
        except Exception as exc:
            # A polite close is a courtesy to the server, never a precondition
            # for this badge letting go. Swallowed here rather than in step()'s
            # containment so a Settings button that stops push cannot raise into
            # the app either (a raise inside launch() resets the badge).
            self.contained_errors += 1
            self.last_error = _error_text(exc)
            self._emit("close_failed", error=self.last_error)
        finally:
            # THE `finally` REVIEW ITEM 5 NAMES: a cancellation between the
            # CLOSE frame and the teardown must still leave this module with no
            # session, or the next tolerant moment believes it holds a socket
            # nobody owns.
            self._close_session(reason, count_failure=count_failure)
        return True

    def _emit(self, event, **fields):
        if self._event_sink is None:
            return
        record = {"transport": "badgelink_push", "event": event, "mode": self.mode()}
        record.update(fields)
        self._event_sink(record)


def _error_text(exc):
    return "{}: {}".format(exc.__class__.__name__, str(exc))[:160]


class FramePump:
    """Give asyncio exactly one explicit scheduler turn per rendered frame.

    The badge has no background event loop: the launcher owns the frame loop and
    ``run(update)`` calls back once per frame. So asyncio is pumped, not run —
    one ``run_until_complete`` of a coroutine that yields once, which lets every
    already-ready task take a step and returns. NB-0 has one deliberately
    long-lived establishment task, but it is HELD by ``PushLink`` and advances
    only through these visible calls; there is still no background event loop.
    A ready task can enter a non-preemptible firmware call, so the device-measured
    maximum atomic call remains a separate frame gate.

    Two pins worth stating because both cost a session to learn:

    * ``asyncio.sleep_ms`` may NOT be passed to ``run_until_complete`` directly
      at the pinned MicroPython version — it TypeErrors. The coroutine must be
      an ``async def`` that awaits it.
    * an asyncio task that raises bypasses TaskSlot containment entirely, so the
      loop gets an exception handler that routes crashes into the same event
      sink as everything else instead of the default print-and-continue.
    """

    def __init__(self, loop=None, event_sink=None):
        self._loop = loop
        self._event_sink = event_sink
        self.crashes = 0
        self.last_error = None
        if loop is not None:
            self._install_handler(loop)

    def loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            self._install_handler(self._loop)
        return self._loop

    def _install_handler(self, loop):
        setter = getattr(loop, "set_exception_handler", None)
        if setter is None:
            return
        setter(self._handle)

    def _handle(self, _loop, context):
        self.crashes += 1
        error = context.get("exception") if isinstance(context, dict) else None
        self.last_error = (
            _error_text(error) if error is not None else "asyncio task crashed"
        )
        if self._event_sink is not None:
            self._event_sink(
                {
                    "transport": "badgelink_push",
                    "event": "task_crashed",
                    "error": self.last_error,
                }
            )

    def run(self, coroutine):
        """Drive one coroutine to completion on this loop, then return."""

        return self.loop().run_until_complete(coroutine)


class PushService:
    """The synchronous face of :class:`PushLink` for a once-per-frame pump.

    The Card PW product pump is plain synchronous code called from the stock
    launcher's ``run(update)`` seam, and layer 2 is asyncio. This is the whole
    adapter: one ``run_until_complete`` per frame, no background loop, and every
    call the product needs spelled out so the product never touches a coroutine.
    Under NB-0 the adapter also owns one explicitly latched task across calls.
    """

    def __init__(self, link, pump=None, event_sink=None):
        self.link = link
        self.pump = pump if pump is not None else FramePump(event_sink=event_sink)

    def poll(self, now=None, tolerant=False, network_enabled=True):
        if not network_enabled and self.link._establishing:
            # Pre-cancel BEFORE run_until_complete: the held task may already be
            # ahead of this frame's root coroutine in MicroPython's global queue.
            self.link._request_establishment_abort("network_off", retry=False)
        return self.pump.run(self.link.step(now, tolerant, network_enabled))

    def tolerant_moment(self, moment, now=None, network_enabled=True):
        if not network_enabled and self.link._establishing:
            self.link._request_establishment_abort("network_off", retry=False)
        return self.pump.run(
            self.link.note_tolerant_moment(moment, now, network_enabled)
        )

    def admit_establishment(
        self,
        moment,
        now=None,
        network_enabled=True,
        radio_generation=None,
    ):
        """Consume one admission turn; the connect itself remains held."""

        return self.pump.run(
            self.link.admit_establishment(
                moment,
                now,
                network_enabled,
                radio_generation,
            )
        )

    def stop(self, reason="stopped"):
        self.link._request_establishment_abort(reason, retry=False)
        return self.pump.run(
            self.link.stop(reason, polite=not self.link._held_strategy)
        )

    def drop(self, reason="dropped"):
        """`stop`, with the close HANDSHAKE skipped. For an unreachable peer.

        A separate method rather than a `polite=` keyword on `stop`, and the
        reason is the product seam: `stop`'s signature is what every fixture,
        probe and generated `/system/main.py` block already calls, and a new
        keyword there is a partial-install hazard for no gain. The service reaches
        this by `getattr`, so a badge whose `network_runtime.mpy` is newer than
        its `pushlink.mpy` falls back to the polite `stop` -- it lets go either
        way, which is the property that matters.
        """

        self.link._request_establishment_abort(reason, retry=True)
        return self.pump.run(
            self.link.stop(reason, polite=False, retry=True)
        )

    def quiesce(self, reason="intro"):
        result = self.link.quiesce(reason)
        if self.link._establishing:
            self.pump.run(self.link._abort_establishment(reason, retry=False))
        return result

    def resume(self, now=None):
        return self.link.resume(now)

    def abort_establishment(self, reason="deferred"):
        """Abort a PARKED (not-yet-session) establishment as a non-failure.

        OWNER RULING #22 placement uses this when the badge enters a
        non-opted-in app while a WSS join is still in-flight. It is the same
        two-step primitive `quiesce`/`apply_steering` already use -- a
        synchronous pre-cancel so a ready held task cannot take one more TLS
        step ahead of the cleanup coroutine, then drive that coroutine to done
        -- but WITHOUT touching `_quiesced`, so it is not the intro gate and
        `resume` does not own its re-arm. ``retry=False``: no jittered retry is
        drawn; the re-arm is the next tolerant moment minted at the launcher /
        on opt-in. Guarded by `_establishing`, so a warm session -- which is
        never `establishing` -- is left completely alone (warm travel).
        """

        if not self.link._establishing:
            return False
        self.link._request_establishment_abort(reason, retry=False)
        self.pump.run(self.link._abort_establishment(reason, retry=False))
        return True

    def set_establishment_allowed(self, allowed):
        """Whether a NEW establishment may start (OWNER RULING #22, WSS side).

        The service sets this each pumped frame. It gates only the CADENCE
        (hourly) reauthorization reopen inside `PushLink._maybe_reauthorize`: a
        non-opted-in app must not close a healthy WSS at minute 60 with no
        re-open allowed. A TRUE token/grant expiry is unaffected and still fails
        closed -- that is a security boundary, not a cadence. RAM-only, like
        `network_enabled`; the admission moments themselves are already gated at
        the service before ever reaching admit_establishment.
        """

        return self.link.set_establishment_allowed(allowed)

    def set_unreachable_sink(self, sink):
        """Wire the demote-for-unreachable notification (see `PushLink`).

        Set ONCE per service by `network_runtime._service_push`, not per frame:
        the sink is a bound method of an object that outlives every doorbell,
        and re-binding it every frame would allocate one on the badge for a
        value that cannot change.
        """

        return self.link.set_unreachable_sink(sink)

    def set_action_sink(self, sink):
        """Wire the validated-broadcast handler (see `PushLink`).

        Set ONCE per service by `network_runtime._service_push`, beside the
        unreachable sink and for the same reason.
        """

        return self.link.set_action_sink(sink)

    @property
    def enabled(self):
        return self.link.policy.enabled

    def set_enabled(self, enabled):
        """Settings turning push on or off. Turning OFF closes the socket now."""

        result = self.link.policy.set_enabled(enabled)
        if not result:
            self.stop("push_disabled")
        return result

    def apply_steering(self, response):
        """Hand the poll response's steering fields to the policy."""

        result = self.link.policy.set_remote(response)
        if self.link._establishing and not self.link.policy.push_allowed(True):
            self.link._request_establishment_abort("push_blocked", retry=False)
            self.pump.run(
                self.link._abort_establishment("push_blocked", retry=False)
            )
        return result

    def wants_tolerant_moment(self, now=None, network_enabled=True):
        return self.link.wants_connect(now, network_enabled)

    @property
    def establishing(self):
        return self.link._establishing

    @property
    def establishment_radio_generation(self):
        """Association epoch owned by the parked attempt, if there is one."""

        return self.link._establish_radio_generation

    def mode(self, network_enabled=True):
        return self.link.mode(network_enabled)

    def snapshot(self):
        record = self.link.snapshot()
        record["task_crashes"] = self.pump.crashes
        return record
