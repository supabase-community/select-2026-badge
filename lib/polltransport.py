"""BadgeLink v2 managed polling transport (P4).

This is the connection-lifetime half of the P4 directive expressed as a pure,
fixture-testable state machine. It performs no I/O itself and imports no
Badgeware globals: all blocking work (the verified-TLS handshake, the keep-alive
socket, request/response bytes) lives behind an injected ``link`` object, and all
time behind an injected ``clock``. That is the same injection-seam discipline the
M0 client uses, and it is what lets the whole contract below run under CPython.

TRANSPORT CONTRACT (build brief P4 / docs/badgelink-transport-decision.md §1, §3):

* The connection is **assumed ABSENT by default.** A ``PollLoop`` starts
  ``DISCONNECTED`` and only ever treats a live socket as a transient optimization.
* Its presence is **continuously re-verified via missed-ack liveness**, never via
  ``wlan.isconnected()`` — every request outcome is the liveness signal. A request
  that raises ``LinkError`` (silent death, half-open socket, timeout) tears the
  connection down and drops to backoff. The poll cadence doubles as the ≤25 s
  application keepalive that probes a quiet socket.
* **Per-request TLS handshakes are banned by measurement** (735 ms frame stall,
  P4 pre-gate 1; no session resumption on this mbedTLS build, B2 probe 2). One
  ``link.open()`` handshake happens only at a *tolerant moment* — session start or
  an explicit reconnect the UI can render behind a "connecting" screen. Every
  in-cadence exchange reuses the one kept-alive socket (B2 probe 1: post-first
  frame p99 33-34 ms).
* **A single open may own one rendered frame for at most
  :data:`OPEN_BUDGET_MS`** -- 5,000 ms since the owner's 2026-08-24 ruling
  ("10 seconds is too extreme"), and 10,000 before it. That constant's comment
  carries the derivation from measured healthy, slow-tail and refusal opens, and
  the risk it accepts. **EXCEPT THE FIRST OPEN OF A LINK, which gets
  :data:`COLD_OPEN_BUDGET_MS` (9,000 ms, Lane J)** -- because the 5,000 was
  measured truncating HEALTHY cold boots, 5 of 7, with one open at 4,119 ms
  succeeding beside them. Same derivation shape, different distribution.
* **Reconnect uses jittered backoff** (800 badges after an AP blip are a
  thundering herd). No fixed retry interval. **One open that made NO PROGRESS
  until its deadline skips the dense start of the ramp** (CX-5): a fast failure
  walks 0.5, 1, 2, 4 s because a blip must heal in seconds and those attempts are
  cheap, while a peer that never answered at all has already cost a rendered
  frame the whole budget and jumps straight to the 16-32 s band. Refusals and
  403s are untouched. **THE TRIGGER IS A TYPE, NOT A WALL SPAN, since NB-i:**
  the link raises :class:`LinkStalled` when the failure is the
  inactivity-ceiling kind and this loop reads the class. See
  :class:`LinkStalled` and :data:`UNREACHABLE_OPEN_MS`.
* **No server is a steady state, not a failure** (owner requirement
  2026-08-19). The badge must run indefinitely with the project unreachable,
  archived or deleted, at bounded radio cost, and recover on its own when it
  returns. Sustained failure therefore escalates the backoff to a **5 minute
  ceiling** and knocks there forever rather than giving up for the session —
  12-24 opens an hour, and a healthy connection resets the level to zero. See
  :data:`BACKOFF_MAX_MS`.
* **A 403 stops the session** (owner ruling 2026-08-19). The server answering
  "this badge is revoked / this grant is denied" is a verdict, not a blip: the
  loop enters :data:`REVOKED`, closes the socket and performs no further open or
  poll while it lives. The flag is RAM-only, so a reboot re-checks. Pair state is
  untouched — revoked is not unpaired.
* A rebooted or reconnected badge **RE-FETCHES desired state** (the badge_state
  version) and never assumes a command it sent earlier was delivered. That is the
  ``_need_full_resync`` flag: the first poll after every ``open()`` asks for full
  desired state, and delivery is reconciled from authoritative rows, not memory.

* **An ERRAND may never become the correctness channel** (``queue_errand``,
  added by Card FT-B). The badge_state update, the score drain and the schedule
  fetch all ride the one kept-alive socket as bounded, RAM-only, single-attempt
  side requests behind every pending ack and every due poll. Two properties are
  load-bearing: an errand never pulls the cadence forward, so it cannot make a
  badge chattier than its steering says; and **a 403 on an errand is not a
  revocation** — the poll and ack RPCs are whoami-scoped so a 403 there means
  this badge is denied, while an errand is a per-resource write, and letting a
  game's score insert stop the poll loop would take the transport down for a
  permission the transport does not need.
* **The P6 doorbell may shorten a poll and nothing else** (``pull_forward``,
  added by P6-L3). A Realtime broadcast on the badge's private topic pulls the
  next poll to *now* while CONNECTED and is otherwise ignored — never a
  reconnect, never an ack, never a payload this module reads. Push is therefore
  removable at any moment (by the wearer, by the server policy, by the demotion
  rule, or by the socket dying) without changing one delivery outcome.

Cadence is 30 s idle / 3-5 s active, server-steerable within clamps. "Active"
means a BadgeLink view is foreground, an ack is pending, or a command arrived
recently; the caller flips it with ``set_active``.

LINK CONTRACT (what an injected ``link`` must provide). A request is driven
**non-blocking, across frames**, because on hardware one keep-alive request spans
several ``AsyncFetch.update()`` calls at ≤34 ms each (B2 probe 1) — a single
blocking request would produce a 76-112 ms frame and fail the 50 ms gate. So the
loop never asks the link to "do a whole request"; it pumps one bounded step per
tick:

* ``open(now)`` — establish the persistent verified-TLS keep-alive connection.
  This is the ONE blocking handshake (~720 ms), called only from a tolerant
  moment (``CONNECTING``) the UI renders behind a connecting screen. Raises
  :class:`LinkError` on failure.
* ``begin(kind, payload, now)`` — start one request over the kept-alive socket.
  ``kind`` is ``"poll"``, ``"ack"``, or one of Card FT-B's two ERRAND kinds
  (``"table"``/``"rpc"``). There was a ``"policy"`` kind until 2026-08-29; the
  fleet settings are a ``"table"`` errand now, issued on a cadence
  `NetworkService` owns. Non-blocking. Raises :class:`LinkError`
  if the socket is already dead.
* ``pump(now)`` — advance the in-flight request by one bounded step. Returns
  :data:`PENDING` while still in flight, or the decoded response (any value) when
  done. Raises :class:`LinkError` on I/O failure (a missed-ack liveness signal).
* ``close()`` — tear the socket down; idempotent and must never raise usefully.

WHAT EVERY STEP COST, AND WHY IT IS TWO TICKS. A deployed badge showed rhythmic
freezes in one session, ``network_runtime.managed_update`` wraps every deployed
app frame, and Card FT-B's F21 gate could only answer "was that frame the socket
or the draw" with a distribution. So each link step is bracketed by two
``clock.ms()`` reads around work that already happens, and the loop reports FOUR
numbers per exchange plus the open **separately** — a warm poll measured ≤34 ms
on hardware (B2 probe 1) against a ~735 ms handshake, and one number covering
both says nothing about either. Nothing is emitted on a frame that did no link
work, which is what keeps the steady frame free: see
:meth:`PollLoop._note_link_step` and :meth:`PollLoop._report_exchange`.
"""


class _Pending:
    __slots__ = ()

    def __repr__(self):
        return "PENDING"


#: Sentinel returned by ``link.pump`` while a request is still in flight.
PENDING = _Pending()

# Ready Python work is batched so the 5,887-update hardware case does not turn
# into minutes at one call per rendered frame. Five milliseconds is a SOFT
# admission budget: it is small against the ~23 ms ordinary frame, but it cannot
# pre-empt the measured 820-903 ms certificate-verification call already inside
# one firmware update.
OPEN_STEP_BUSY_BUDGET_MS = 5


DISCONNECTED = "disconnected"
CONNECTING = "connecting"
CONNECTED = "connected"
BACKOFF = "backoff"
STOPPED = "stopped"
#: Terminal FOR THIS BOOT: the server answered 403 (owner ruling 2026-08-19).
#: No further open and no further poll happen while this object lives, and the
#: flag is RAM-ONLY so a reboot re-checks with the server. A Settings screen
#: renders it as "connection stopped — reboot to retry"; query it with
#: ``state == REVOKED`` or :meth:`PollLoop.is_revoked`.
REVOKED = "revoked"

#: WHICH EMITTER A `revoked` LINE CAME FROM (2026-08-24). A revocation is
#: DESIGNED to be reached independently by each transport, so more than one
#: `event=revoked` per boot is correct and an arm that reads "no second
#: `revoked`" literally fails a working badge. This field is what makes the lines
#: tell each other apart; the rule is one `revoked` per SOURCE, and a repeat of
#: the SAME source is the real failure. The other two words are
#: `pushlink.SOURCE_PUSH` and `network_runtime.SOURCE_SERVICE`, spelled in their
#: own modules for the reason every other literal here is, and pinned distinct by
#: `badgelink/tests/test_revoked_sources.py`.
SOURCE_POLL = "poll"

#: THE SLOW RE-PROBE AFTER A 403, and it is what stops the correctness FLOOR from
#: being terminal for a boot. 15-30 minutes, jittered per badge -- the same
#: interval and the same reasoning as `pushlink.REDEMOTE_RETRY_MIN_MS`, and the
#: numbers are deliberately equal so an operator reading two transports sees one
#: cadence.
#:
#: ⚠ **WHY THE FLOOR MAY NOT BE TERMINAL WHEN THE DOORBELL MAY.** The 403 ruling
#: ("stop, never retry harder, terminal for the boot") was written when one badge
#: held one token: a 403 then meant THIS badge is denied, and retrying could not
#: help. Under the shared fleet token a 403 means the FLEET's grant is denied --
#: so a transient server-side mistake during a migration, a mis-applied revoke, a
#: half-deployed policy, revokes ~800 badges at once and every one of them goes
#: dark until somebody physically reboots it. That is not a verdict about a badge;
#: it is an outage, and an outage the badge can survive by asking again later.
#:
#: THE ASYMMETRY WITH PUSH IS DELIBERATE. `pushlink`'s revocation stays terminal
#: because it follows a SUCCESSFUL join -- the socket opened, the server read the
#: grant row and said no -- and because losing push costs one convenience while
#: polling carries the event. Losing the poll IS the badge going dark, so the
#: floor gets the recovery even though the doorbell does not.
#:
#: ONE PROBE PER INTERVAL, so the herd cost of a fleet-wide mistake is 800 badges
#: making one request each per ~20 minutes -- 0.67/second against the ~27/second
#: the idle cadence already costs. Cheap enough that being wrong about the outage
#: costs nothing, which is the whole reason it is safe to keep asking.
REVOKED_REPROBE_MIN_MS = 15 * 60 * 1000
REVOKED_REPROBE_MAX_MS = 30 * 60 * 1000

# Cadence clamps (ms). The server may steer next-poll timing inside this band; a
# badge that received an out-of-band value clamps it rather than trusting it.
ACTIVE_CADENCE_MS = 3000
ACTIVE_CADENCE_MIN_MS = 3000
ACTIVE_CADENCE_MAX_MS = 5000
IDLE_CADENCE_MS = 30000
IDLE_CADENCE_MAX_MS = 60000

# THE STEERING CADENCE USED TO LIVE HERE (`POLICY_REFRESH_MS`, 300000) AND IT
# DOES NOT ANY MORE (rebuild, 2026-08-29). The venue kill-switch is a row in
# `fleet_settings` that `NetworkService._pump_fleet_settings` reads as an ordinary
# ERRAND, on `network_runtime.SETTINGS_REFRESH_MS`, so this loop no longer has a
# request kind of its own for it -- and with the kind went the due time, the phase
# `NetworkService` used to arm through `arm_policy`, and the mirror it read back
# through `policy_due`. That pair was CX-8's finding and then CX-8's correction:
# two objects holding one cadence disagree the first time a read FAILS.
#
# WHAT STAYS HERE IS THE ONLY PART THAT WAS EVER THIS OBJECT'S: `policy`,
# `suggested_cadence_ms` and `_policy_sink` -- the fields a steering answer sets
# and the exchange rate it steers, which is decided where the exchanges are.

# HOW MANY SIDE REQUESTS MAY WAIT (Card FT-B's errand channel). Four, and the
# number is an argument rather than a guess: the concurrent requesters are
# `report_state` (coalesced to ONE by key), the scorebox drain (one row at a
# time) and the schedule sync (a version read, then at most one fetch). Four
# covers every one of them being in flight at once with a slot spare, and it
# bounds the worst case an errand can add to another queued errand's wait to four
# exchanges. A refusal is better than a deeper queue: the only requester that
# needs a retry has a durable spool.
MAX_ERRANDS = 4

# THE MINIMUM GAP BETWEEN TWO ERRANDS (ms). An errand does not wait for the poll
# cadence -- a badge coming back online with a full 64-entry score spool would
# take 32 minutes to drain it at 30 s -- so the bound is a floor between requests
# instead. ONE SECOND, and the number is the herd rather than a preference: 800
# badges draining a full spool as fast as the socket allows is ~51,000 requests,
# and one second apart it is ~800/second, which is exactly the peak the ring
# jitter already accepts. A full spool then takes ~64 s to drain, which is
# invisible to a wearer and cheap for the server.
ERRAND_MIN_GAP_MS = 1000

# Jittered exponential backoff (ms) between reconnect attempts.
BACKOFF_BASE_MS = 1000
# THE SLOW CEILING for a server that is simply not there. Owner requirement
# 2026-08-19: archiving or deleting the Supabase project must never degrade the
# badge, so the no-server steady state has to be indefinite, cheap and
# self-healing. Persistent unreachability therefore does NOT give up for the
# session (an AP blip must recover with nobody doing anything); the schedule
# DECAYS instead — 0.5, 1, 2, 4, 8, 16, 32, 64, 128 s, then a jittered
# 150-300 s knock forever. Escalation costs ~4-9 minutes, so a blip still heals
# in seconds, while a dead project costs 12-24 opens/hour instead of the 60-120
# the old 60 s ceiling allowed: about 24 s of radio per hour at the measured
# ~1 s handshake (P4 pre-gate 1; B2 probe 2 proved no session resumption), which
# the transport memo's power note calls a rounding error. Five minutes is
# deliberately not longer — recovery must feel like the badge came back during
# the event, and 800 badges jittered across a 150 s window are not a herd.
BACKOFF_MAX_MS = 300000
# The level at which the DEFAULT base reaches the DEFAULT ceiling
# (1000 << 9 = 512000 >= 300000). The level clamp a loop actually uses is
# derived from its own base/ceiling by :func:`_backoff_level_for`, so lowering
# ``backoff_base_ms`` cannot quietly cap the delay below the requested ceiling.
BACKOFF_MAX_LEVEL = 9
# Hard iteration bound for that derivation; nothing sane needs 2**30 doublings.
_BACKOFF_LEVEL_LIMIT = 30

# THE IN-FRAME OPEN BUDGET, and it is an owner ruling with an arithmetic behind
# it. 2026-08-24, the owner's words: **"10 seconds is too extreme."**
# (`OWNER-DECISIONS #21`.)
#
# WHAT THIS NUMBER IS, STATED THE ONLY WAY IT IS TRUE (corrected 2026-08-24).
# `link.open()` is a fully blocking spin loop inside ONE rendered frame, and the
# only thing that ends it when the peer never answers is the frozen
# `fetch.AsyncFetch`'s own INACTIVITY CEILING -- passed as `timeout=` in whole
# SECONDS by `network_runtime`'s `worker_factory`. It was 10,000 ms; it is now
# 5,000.
#
# **IT BOUNDS THE GAP BETWEEN SIGNS OF LIFE, NOT THE OPEN.** This comment said
# "so this constant IS the worst single-frame freeze one connect attempt can cost
# a wearer", and four documents said it after this one -- while the risk block
# below, in this same comment, admitted that a firmware that re-arms on progress
# defeats it. Both cannot be the statement. **The inactivity reading is the one
# that is true**: an open whose peer TRICKLES -- one header line every 900 ms --
# resets the deadline on every `headers`/`body` step and can hold the frame for as
# long as it likes. Modelled end to end, through a real `DeviceLink` inside a real
# `PollLoop`, in `test_open_budget.TrickleTests`: 7.2 s of frame, correctly NOT
# classified `LinkStalled`, correctly not jumping, and correctly counted.
#
# **THE TWO HONEST INSTRUMENTS ARE NB-i's, and neither is this number.** The
# `open_step_max_ms` figure `device_link` publishes is the worst SINGLE blocking
# call -- what a wearer can actually feel, and the number that survives the NB
# spec's P1-a where the open parks between steps -- and :class:`LinkStalled` is
# the class the ramp acts on. A total is neither. Quote those, not this, when the
# claim is about a frame.
#
# (Named rather than dereferenced on purpose: `test_device_link` guards that this
# module has not learned about the phase record AT ALL, by text, and that guard
# cannot tell a reference from a read. It is right to stay strict -- every
# decision here is the transport's and none of them is a phase number.)
#
# What this number DOES bound, exactly: the longest an open can go with NO sign of
# the peer before the firmware ends it. For the case it was chosen for -- a
# blackholed open, nobody answering at all -- that and the frame cost are the same
# number, which is why the arithmetic below is still the right arithmetic.
#
# WHY EXACTLY FIVE SECONDS, from this repository's own hardware and nothing else:
#
# * **A healthy open is 720-1,330 ms** (P4 pre-gates' R4+R1 accept at 1,201 ms;
#   the P4 fault matrix's three clean recoveries at 1,077 / 1,297 / 1,329 ms;
#   the TLS handshake itself 683.558-734.456 ms inside ONE `update()`,
#   `VAL-031-BLS`/`VAL-031-BLT`), and **953-1,757 ms on glass** in the
#   2026-08-24 device sessions (`open_ms` 953, 1,082, 1,210, 1,757).
# * **The WSS join leg is 2,581-2,696 ms end to end** (P6-L3's two connect
#   frames, DNS + TCP + TLS + upgrade + first exchange in one frame).
# * **The WORST MEASURED SUCCESSFUL OPEN IS 3,217 ms** -- B2 probe 2's fourth
#   forced full connect, whose handshake max was still 720.206 ms, so the extra
#   ~2 s was network TAIL and is retained as tail evidence precisely because it
#   is the slowest thing that ever worked.
# * **The worst measured FAST FAILURE is 3,261 ms** -- a wrong-host rejection on
#   2026-08-24 (`ValueError`), beside a refusal at 2,835 ms the same day. The
#   ordinary band is 31-564 ms (refusals 31/32/34/125/309, wrong-host 174/211/221,
#   an R1-only chain reject at 564, fault-proxy drop 136, deleted-name resolver
#   failures 30-88).
# * ⚠ **AND ONE MEASURED SUCCESSFUL OPEN IS ABOVE THIS BUDGET: 8,746 ms**, run 1
#   of the 2026-08-25 freeze capture, of which **5,156 ms was our own in-frame
#   cooperative sleep** rather than the network. It is excluded from the
#   derivation below DELIBERATELY and with an argument, not by oversight -- see the
#   risk block after the arithmetic, which is where it decides something.
#
# So the binding constraint among opens whose cost is NETWORK cost is
# **3,261 ms**, the worst open of any class that was neither the ceiling nor
# dominated by our own sleeps. And the knob is whole seconds: `AsyncFetch(timeout=)` is an
# integer-second argument on frozen firmware and nothing in this repository has
# verified that it accepts a float. Therefore:
#
#     4 s = 1.23x  the worst measured open -- REJECTED, one slow TLS reject
#                  crosses it and the two classes stop separating at all
#     5 s = 1.53x  the worst fast failure, 1.55x the worst success  <- CHOSEN
#     6 s = 1.84x  20% more worst-case freeze for 0.3x more margin, against a
#                  ruling that called ten seconds extreme
#
# **ONE CAP, NOT ONE PER PATH, and the reason is which path binds.** The WSS
# legs' worst measured whole-connect frame (2,696 ms) is SMALLER than the poll's
# worst success (3,217 ms), and `pushlink`'s `connect_timeout_ms`/`io_timeout_ms`
# each bound a SUB-leg of that frame -- so 5,000 ms gives the doorbell 1.85x on
# the whole frame and more on any single leg. The poll open is the binding path;
# a per-path split would be two numbers where one is provably enough.
#
# ⚠ **THE RISK, AND IT IS NOT HYPOTHETICAL: ONE MEASURED SUCCESSFUL OPEN IS
# ABOVE THIS BUDGET.** The 2026-08-25 freeze capture, three runs on hardware, has
# run 1's open **SUCCEEDING at 8,746 ms** (and run 2's failing at 10,009 ms, the
# old ceiling, with a 999 ms retry after it). So the honest statement is not "a
# badge on marginal RF might need more than five seconds" -- it is **"a badge has
# been observed needing 8.7 seconds and getting there"**, and this budget would
# have interrupted that open.
#
# **WHETHER IT ACTUALLY WOULD HAVE IS AN OPEN QUESTION, and it is the firmware's
# to answer.** ``timeout=`` is documented here and everywhere else as an
# INACTIVITY ceiling. If the firmware re-arms it whenever bytes move, run 1 never
# had a five-second gap and survives this budget untouched; if it is really a
# wall-clock bound on the whole request, run 1 becomes a `LinkError` at ~5,007 ms.
# `fetch.py` is frozen firmware and is not in this repository, so nothing here
# establishes which -- and run 2's 10,009 ms failure is consistent with BOTH.
# **The device arm is where this gets settled** (arm 12's healthy control), and
# until it does, treat a capped `open_failed` on a HEALTHY network as new evidence
# rather than as noise.
#
# ⚠ **AND NOTE WHICH WAY THE DOCUMENTATION MUST LEAN WHILE IT IS OPEN.** The
# INACTIVITY reading is the one the docs are written against, because it is the
# documented one and because it is the weaker claim: it says this number does not
# bound an open at all, only the gap. Writing the wall-clock reading down would
# promise a 5 s worst frame that the firmware may not deliver, and that is the
# direction a wearer feels. `TrickleTests` is the case, and arm 12 is what could
# still turn this into the stronger claim.
#
# **WHY THE BUDGET IS STILL THE RIGHT ANSWER TO THAT OPEN, rather than a bigger
# ceiling being it.** Of run 1's 8,746 ms, **5,156 ms was `sleep_ms` -- OUR OWN
# 1 ms cooperative sleeps inside `device_link._run_blocking`**, not the network
# (`updates` reached 5,887). That is finding 2 of the same report: *"the open path
# SLEEPS while holding the frame hostage ... up to half the connect block is
# literally waiting, in-frame."* A ceiling large enough to contain that open is a
# ceiling that makes a self-inflicted 8.7-second frame INVISIBLE. This budget
# makes it loud. The repair is the NB spec's phase 1(a) -- release the frame during
# the open's sleeps -- and it is now the thing that removes this risk rather than
# the ceiling being it.
#
# The retry side is bounded as it always was: the jittered backoff bounds the
# RATE, the CX-5 jump below bounds the DENSITY, and run 2 measured the retry after
# a ceiling failure at **999 ms**. What is NOT measured is the wearer-facing
# comparison -- one 8.7 s frame against a 5 s frame plus a ~1 s frame 16-32 s
# later -- and it must not be asserted until it is.
OPEN_BUDGET_MS = 5000

# THE COLD-BOOT ALLOWANCE: THE FIRST OPEN OF A LINK GETS A BIGGER BUDGET, AND IT
# EXISTS BECAUSE THE 5,000 ABOVE WAS MEASURED BITING HEALTHY BOOTS (Lane J,
# 2026-08-24, from the 2026-08-25 day-3 device session's §7a).
#
# WHAT WAS MEASURED, and it is seven cold boots rather than one experiment --
# every probe that pointed at the real project that night produced one:
#
# * **5 of 7 cold boots burned the WHOLE budget on their FIRST open** and were
#   punished for it: `open_ms` 5,016 / 5,017 / 5,018 / 5,018 / 5,019, each with
#   `backoff_jumped level=5` and `delay_ms` **19,888-31,311**, and each followed
#   by a retry that opened in **969-1,058 ms**.
# * **The two control boots opened cold in 1,092 and 1,489 ms**, same badge, same
#   AP, minutes apart, so the network was not broken.
# * ⭐ **AND ONE OPEN TOOK 4,119 ms AND SUCCEEDED** -- 881 ms under the cap. So the
#   healthy open-duration distribution on this badge runs CONTINUOUSLY up to the
#   ceiling: **the cap was truncating a live distribution, not rejecting
#   pathological cases**, which is the observable the register left open and the
#   single most informative line of that session.
# * **The discriminator is the SEND leg, not connect.** On all five failures
#   `send_ms` was 1,337-1,416 ms with `sleep_ms` ~2,750; on the two successes
#   `send_ms` was 706-742 ms; `connect_ms` was 8 ms every single time. The 4,119 ms
#   SUCCESS reports `send_ms=1337` -- the same slow-send regime as the five
#   failures -- so those five were TRUNCATED members of a regime that completes,
#   not a different kind of event. `send_ms` is where the deferred TLS handshake
#   lands (`device_link._OPEN_PHASE_KEYS`), and a cold boot pays it on a radio
#   that has just associated.
#
# WHY NINE SECONDS, and this derivation is a FLOOR and a CEILING nearly meeting
# rather than a margin:
#
# * **The FLOOR is 8,746 ms** -- the 2026-08-25 freeze capture's run 1, a cold open
#   that SUCCEEDED. It is the worst cold open this repository has ever seen
#   COMPLETE, it is in `test_open_budget.OPENS_ABOVE_THE_BUDGET` as a pinned
#   counterexample to the 5,000, and §7a's near-miss is what promotes it from
#   "outlier" to "the tail". A budget below it fails an open that worked.
# * **The CEILING is the owner's ruling.** #21 is *"10 seconds is too extreme"*,
#   so 10,000 is not a number this repository may choose, for open #1 or any
#   other.
# * **The knob is whole seconds** -- `AsyncFetch(timeout=)` is an integer-second
#   argument on frozen firmware and nothing here has verified a float -- so
#   between a floor of 8,747 and a ceiling below 10,000 there is exactly ONE
#   candidate.
#
# ⚠ **SO THE MARGIN IS 1.03x AND THAT IS NOT A COMFORT, IT IS THE STATEMENT.** The
# next cold open above 8,746 ms will be truncated by this budget too. What would
# move it is a cold-boot distribution measured WITH this allowance in place (arm
# 12's re-run), not an argument -- and if that distribution has a tail above 9 s
# the answer is the NB spec's phase 1(a), which releases the frame during the
# open, rather than a bigger ceiling. A ceiling large enough to contain a
# self-inflicted 9-second frame is a ceiling that makes it invisible.
#
# WHAT IT COSTS, both parts, because the second one is a REGRESSION against #21's
# own headline and must not be discovered on a badge:
#
# 1. **A healthy cold boot's worst frame goes from ~5.0 s to ~9.0 s, once**, behind
#    the Connecting screen the paint order guarantees. Against that: the badge
#    stops paying 5 s AND THEN LOOKING DEAD FOR 20-31 s, which is the cost §7a
#    actually names (*"The cost is not the 5 s: it is the 20-31 s the jump then
#    imposes before a retry that takes ~1 s"*).
# 2. ⚠ **A BLACKHOLED boot's first minute goes from ~10 s of blocked frames to
#    ~19 s**, and it is this allowance PLUS Lane J's boot forgiveness together:
#    open 1 costs ~9.0 s and is forgiven, so it walks the dense ramp and open 2
#    follows immediately at ~5.0 s, and only THEN does the jump put open 3
#    16-32 s out -- three opens in the first minute where #21 counted two.
#    Still under a third of the ~60 s the pre-CX-5 ramp cost, and every one of
#    those frames is at BOOT behind a Connecting screen; but #21's "~10 s in the
#    first minute" is now the WARM figure, and this is the cold one.
#
# ONE OPEN, NOT A WINDOW, and the seam is the LINK rather than a clock. The
# `network_runtime` worker factory counts its own invocations -- it is called once
# per open, from `device_link._connect_worker` -- so open #1 of a link gets this
# and every later open gets `OPEN_BUDGET_MS`. A link is built once per boot on the
# path that matters; a REBUILD (a networking off/on toggle, or a retry after
# `_build_loop` raised) gets the allowance again, which is correct for the same
# reason the boot does -- the association under it is fresh and DHCP, ARP and the
# first route settle after `isconnected()` goes true.
#
# THE DEADLINE THE BLACK-HOLE CLASS IS DECLARED AT FOLLOWS THE BUDGET THAT
# APPLIED, per open. `device_link` reads the ceiling off the WORKER the factory
# built (`COLD_OPEN_NO_PROGRESS_MS` / `OPEN_NO_PROGRESS_MS`), so the mirror cannot
# drift from the thing it mirrors -- see `LinkStalled` and
# `test_open_budget.ColdBootAllowanceTests`.
#
# WHAT THIS DOES NOT TOUCH: the doorbell. `pushlink`'s `connect_timeout_ms` /
# `io_timeout_ms` stay at `OPEN_BUDGET_MS` for every join. The same session
# measured the join leg bimodal at 2,192-5,053 ms with the slow cluster sitting
# exactly on that 5,000 (§7c), which is the same shape on a second transport.
#
# THE BIMODALITY IS NOW EXPLAINED AND THE 5,000 STAYS (2026-08-26, six interleaved
# hardware arms). A slow cluster sitting exactly ON a deadline is the signature of a
# leg hitting that deadline, not of a network -- and the Upgrade-starvation fix
# collapsed that leg from a stuck 14,651 ms to a few hundred. **The slow cluster WAS
# the starvation**, so the premise above -- "nothing has measured a WSS join that
# would have completed above 5 s" -- is answered: nothing would have, and the ones
# that appeared to were being truncated by the ceiling they sat on.
#
# ⚠ WHAT THOSE ARMS DO **NOT** MEASURE IS THE QUANTITY THIS NUMBER GATES, and the
# figures must not be read as a margin against it. They are per-leg durations
# summing to a worst 1,726 ms; `OPEN_BUDGET_MS` is an **INACTIVITY** ceiling, which
# bounds the longest an open may go with NO SIGN OF THE PEER and not the open's
# duration (the Lane I correction, register §"THIS HEADLINE SAID"). Dividing a sum of
# durations into 5,000 yields a headroom ratio for something that was never gated: a
# TRICKLING peer re-arms the deadline on every byte and holds the frame as long as it
# likes -- 7.2 s end to end in `test_open_budget.TrickleTests`.
#
# SO THE RESIDUAL IS AN INSTRUMENT, NOT A NUMBER. This transport publishes
# `open_step_max_ms`, the worst SINGLE blocking call, which is the honest NB-i
# figure; the doorbell publishes no equivalent, so nothing measures what its
# `io_timeout_ms` actually bounds. Deliberately not built at freeze -- it is a
# diagnostic, polling is the floor, push ships default-off, and all six arms joined.
# Details and the unmeasured `phx_reply` wait are in
# `docs/badgelink-cx-issue-register.md`; they are deliberately NOT enumerated here,
# because this file is not allowed to learn the doorbell's leg names (see
# `test_device_link.OpenAttributionTests`, which enforces exactly that and which
# this comment tripped on its first draft).
COLD_OPEN_BUDGET_MS = 9000

# WHAT MAKES AN OPEN "UNREACHABLE" RATHER THAN "REFUSED" (CX-5), AND SINCE NB-i
# IT IS A TYPE RATHER THAN THIS NUMBER.
#
# **THIS CONSTANT IS NO LONGER A THRESHOLD ANYTHING COMPARES A SPAN AGAINST.** It
# is the DEADLINE the no-progress class is declared at -- the same 5,000 ms the
# frozen `AsyncFetch` enforces as its inactivity ceiling, mirrored by
# `device_link.OPEN_NO_PROGRESS_MS`, which is what raises
# :class:`LinkStalled`. It is still the modelled COST of one such open, which is
# what `p5_device_session_probe._unreachable_open_bound` reads it off the loop
# for. It remains `OPEN_BUDGET_MS` because a mirror of a ceiling has to be that
# ceiling.
#
# WHY THE WALL SPAN HAD TO GO, and it is not a tidiness argument. The old
# predicate was `if span >= self.unreachable_open_ms` over a bracket around the
# whole blocking `link.open()`, and it was CORRECT only because that open is one
# blocking frame: the span and the in-frame cost were the same number. The NB
# spec's phase 1(a) parks that open across frames, and from that moment the span
# also contains healthy readiness waits and other apps' rendered frames -- so a
# perfectly healthy parked open would classify as a black hole and land its next
# attempt 16-32 s out. Both adversarial reviewers found this independently, and
# Lane G had already re-derived the coupling once (*"a capped open fails AT the
# cap, so a 10 s trigger could never fire again"*). The third break was
# scheduled; this is it being paid off instead.
#
# ⚠ **WHAT THE OLD PREDICATE COST, and what the typed one does not.** At a 10 s
# ceiling a refusal was two orders of magnitude cheaper than a black hole and
# there was no ambiguity in the middle; at 5 s the worst measured fast failure
# (3,261 ms, a wrong-host reject) sat **1.53x** below the bar, so a slower one on
# bad RF could cross it and buy the 16-32 s band. **THE TWO CLASSES NO LONGER
# SHARE A MEASURE, so that gap stops being a risk**: a rejection is the peer
# ANSWERING, and no wall span can make it the no-progress kind. See
# :class:`LinkStalled` for the two conditions and the device evidence behind
# each.
#
# THE TYPE IS STILL THE ONLY THING THAT MAY SELECT THE FAST-FASTER RAMP. A
# refusal, a ``LinkRevoked``/403, a certificate rejection and every other fast
# failure keep the ordinary ramp untouched: 403 semantics are an owner ruling,
# and "the server answered" is never "the server is gone".
UNREACHABLE_OPEN_MS = OPEN_BUDGET_MS

# THE SAME THING FOR THE FIRST OPEN OF A LINK (Lane J). It is the deadline the
# no-progress class is declared at when the cold-boot allowance applied, mirrored
# by `device_link.COLD_OPEN_NO_PROGRESS_MS`, and the modelled COST of that one
# open -- which is what `p5_device_session_probe._unreachable_open_bound` charges
# to open #1 and nothing else. Like its warm twin it is not a threshold anything
# compares a span against; the class is a TYPE.
COLD_UNREACHABLE_OPEN_MS = COLD_OPEN_BUDGET_MS

# WHERE ONE UNREACHABLE OPEN JUMPS THE RAMP TO (CX-5). Level 5 against the
# default base is a 32,000 ms span, and `_backoff_delay_ms`'s existing full
# jitter makes that a **16-32 s band** -- which is the whole change: the ramp used
# to walk 1 -> 2 -> 4 -> 8 s from every boot, so the first minute of any
# connectivity trouble stacked repeated full-budget blocking opens, and every app
# switch restarted that minute. A whole budget of frame time is already the
# evidence the ramp was climbing towards; there is nothing left to learn from
# paying it four more times to find out.
#
# **THIS LEVEL DID NOT MOVE WITH THE CAP, DELIBERATELY.** Halving the budget
# halves what each attempt COSTS; it does not make a badge that burned the whole
# budget any more likely to succeed on the next try, which is the only thing the
# level is about. And because `_enter_backoff` arms the delay from the ATTEMPT's
# start, the attempt SCHEDULE is unchanged by the cap as well: the same two opens
# in the first minute of a black hole, each now costing five seconds of frame
# instead of ten. What changed is the gap a reader sees between a printed failure
# and the next `connecting` -- see `badgelink/README.md` §2c, which carries the
# worked arithmetic for both caps.
#
# WHAT IS DELIBERATELY UNCHANGED: the 300,000 ms ceiling (the no-server steady
# state is an owner requirement), the full jitter (800 badges), the reset to zero
# on a healthy connection, and the fact that escalation never becomes "give up".
UNREACHABLE_BACKOFF_LEVEL = 5

# HOW MANY CONSECUTIVE STALLED OPENS A LINK EDGE MAY FORGIVE (Lane I, 2026-08-24).
#
# **THE ONE-SHOT WAS RE-ARMABLE FOREVER AND THAT WAS A DEFECT** (`d4622382`,
# found by an adversarial review of Lane H's own fixes). `request_reconnect` is
# what both radio edges and the loop BUILD call (the build since Lane J, which is
# what a BOOT has instead of an edge), so a FLAPPING access point mints one
# forgiveness per
# recovery -- and a badge whose radio keeps re-associating against a genuine black
# hole was forgiven on every recovery, indefinitely. Measured in
# `test_cx_roam.FirstOpenForgivenessTests`: ten edges, **ten forgiven opens and
# zero jumps**. CX-5's whole escalation was retired by the radio rather than by
# any decision anybody wrote down, which is the same class of silent retirement
# the CX-5 threshold re-derivation was about.
#
# SO THE BOUND IS ON CONSECUTIVE FORGIVENESS, NOT ON EDGES. A forgiveness that is
# not followed by a SUCCESSFUL open arms a counter, and the next forgiven stall
# takes the jump instead -- across edge epochs, because the epoch is exactly what
# a flap manufactures. Any successful open resets it, so the settling story is
# available again the next time the badge genuinely re-associates: a wearer who
# walks out of range twice in an evening is forgiven both returns.
#
# **WHY ONE AND NOT TWO.** The DHCP renewal, the ARP for the gateway and the first
# route through a venue AP are properties of a SINGLE attempt; if the attempt
# after them also hears nothing, the badge has evidence about the PEER. Two would
# double the worst case (two full budgets of frame per flap) to buy a settling
# window nothing has measured as needing two attempts. Raise it only with a
# measurement.
FORGIVEN_STALLS_MAX = 1


class LinkError(Exception):
    """Any I/O failure from the injected link: connect, request, or teardown.

    The state machine treats every ``LinkError`` as a liveness signal — the
    connection is gone — and never inspects driver connection state directly.
    """


class LinkRevoked(LinkError):
    """The server denied this badge (HTTP 403), not an I/O fault.

    A subclass so a link may keep raising one exception type and any older
    handler still tears the connection down; the loop checks for this class
    first and stops for the session instead of re-arming backoff. Raised by
    ``device_link`` when ``postgrest`` adjudicates a 403 on open, poll or ack.
    """


class LinkStalled(LinkError):
    """An open that made NO PROGRESS until its deadline: the black-hole class.

    **THE TYPED OUTCOME CX-5 CLASSIFIES ON, since NB-i.** A subclass, so every
    handler that predates it still tears the connection down and still treats it
    as an ordinary liveness signal; the only thing that reads the class is
    :meth:`PollLoop._attempt_open`, and what it does with it is withhold the
    dense start of the backoff ramp (:func:`PollLoop._jump_unreachable`).

    ``device_link`` raises it when BOTH of these hold, and both are properties
    of the FAILURE rather than of the clock:

    1. **Nothing proved the peer was there for the deadline THAT OPEN was given**
       -- :data:`device_link.OPEN_NO_PROGRESS_MS`, or
       :data:`device_link.COLD_OPEN_NO_PROGRESS_MS` for the first open of a link
       (Lane J's cold-boot allowance). The deadline is read off the WORKER the
       factory built, so it is always the ceiling the frozen ``AsyncFetch``
       actually enforced rather than a constant that agrees with it today.
       Progress means a phase the
       frozen ``AsyncFetch`` can only reach once bytes came BACK -- ``headers``
       or ``body``. Deliberately not ``connect``->``send``: the non-blocking
       connect returns EINPROGRESS immediately and the phase advances with
       nobody answering, which is why every device open reports ``connect_ms``
       around 8 ms including the ones that then blackholed.
    2. **The failure is socket-level** -- an ``OSError`` out of the worker -- or
       our own no-progress giving-up. Every ceiling failure this repository has
       recorded is ``open update failed: OSError``: sixteen of sixteen on NS-1,
       twice again on 2026-08-24, and the 2026-08-25 freeze capture's run 2. A
       chain or hostname rejection is a ``ValueError``, and that means the peer
       ANSWERED.

    A missed-ack teardown, a refusal, a rejection, a 401, a 403 and a radio
    abort are all outside it, by class rather than by threshold.
    """


def _backoff_level_for(base_ms, max_ms):
    """The first doubling level whose span reaches ``max_ms``.

    Derived per loop instead of fixed so the level clamp and the millisecond
    ceiling always agree: with the defaults this is :data:`BACKOFF_MAX_LEVEL`,
    and a caller that passes a smaller base gets the extra levels it needs to
    actually reach the ceiling rather than a silently lower one.
    """

    level = 0
    span = base_ms
    while span < max_ms and level < _BACKOFF_LEVEL_LIMIT:
        span *= 2
        level += 1
    return level


def _default_rand01():
    import os

    raw = os.urandom(2)
    return (raw[0] << 8 | raw[1]) / 65536.0


class _MonotonicClock:
    def __init__(self):
        import time

        self._time = time

    def ms(self):
        return self._time.ticks_ms()

    def add(self, value, delta):
        return self._time.ticks_add(value, delta)

    def diff(self, left, right):
        return self._time.ticks_diff(left, right)


class PollLoop:
    """The pure connection-lifetime state machine. No I/O, no Badgeware imports."""

    # Class defaults keep the immutable OFF artifact free of parked-only keys.
    # `enable_parked_open` materialises them exactly once in the ON build.
    _parked_open_enabled = False
    _establishment_allowed = True
    open_steps = 0

    def __init__(
        self,
        link,
        clock=None,
        rand01=None,
        command_sink=None,
        event_sink=None,
        active_cadence_ms=ACTIVE_CADENCE_MS,
        idle_cadence_ms=IDLE_CADENCE_MS,
        backoff_base_ms=BACKOFF_BASE_MS,
        backoff_max_ms=BACKOFF_MAX_MS,
        liveness_misses=1,
        policy_sink=None,
    ):
        if link is None:
            raise ValueError("a link is required")
        if not (0 < active_cadence_ms <= idle_cadence_ms):
            raise ValueError("cadence must satisfy 0 < active <= idle")
        if not (0 < backoff_base_ms <= backoff_max_ms):
            raise ValueError("backoff must satisfy 0 < base <= max")
        if not isinstance(liveness_misses, int) or liveness_misses < 1:
            raise ValueError("liveness_misses must be a positive integer")
        self.link = link
        self.clock = clock or _MonotonicClock()
        self._rand01 = rand01 or _default_rand01
        self._command_sink = command_sink
        self._event_sink = event_sink
        self._policy_sink = policy_sink
        self.active_cadence_ms = int(active_cadence_ms)
        self.idle_cadence_ms = int(idle_cadence_ms)
        self.backoff_base_ms = int(backoff_base_ms)
        self.backoff_max_ms = int(backoff_max_ms)
        self.backoff_max_level = _backoff_level_for(
            self.backoff_base_ms, self.backoff_max_ms
        )
        self.liveness_misses = int(liveness_misses)
        #: CX-5's two knobs, instance attributes rather than constructor keywords
        #: because the numbers are DEVICE MEASUREMENTS and a caller with a
        #: different opinion about them is a caller with a different transport.
        #: Readable and overridable for a test; nothing configures them.
        #:
        #: ⚠ **`unreachable_open_ms` IS NOT READ BY THIS MODULE ANY MORE (NB-i).**
        #: It named the wall-span threshold `_attempt_open` compared against, and
        #: that comparison is gone: the link types the failure and this loop
        #: reads the class (:class:`LinkStalled`). What the number still IS is
        #: the deadline that class is declared at and the modelled COST of one
        #: such open, which is what reads it off a loop
        #: (`p5_device_session_probe._unreachable_open_bound`). Raising it here no
        #: longer retires the jump, and there is a test that says so.
        self.unreachable_open_ms = UNREACHABLE_OPEN_MS
        #: THE SAME NUMBER FOR THE FIRST OPEN OF A LINK (Lane J). Read off the
        #: loop by `p5_device_session_probe._unreachable_open_bound`, which
        #: charges it to open #1 and `unreachable_open_ms` to every later one --
        #: the cold-boot allowance is a property of the transport, so a bound
        #: derived from the loop has to see it. Not read by this module either.
        self.cold_unreachable_open_ms = COLD_UNREACHABLE_OPEN_MS
        self.unreachable_backoff_level = UNREACHABLE_BACKOFF_LEVEL

        self.state = DISCONNECTED
        self.active = False
        #: THE TEST KNOB (see :meth:`force_active_cadence`). RAM-only, off, and
        #: deliberately NOT a constructor keyword: a keyword is a thing a
        #: preference file could set, and this must die at the next RESET.
        self.cadence_forced_active = False
        # RAM-only revocation verdict: never persisted, so a reboot re-checks.
        self.revoked = False
        self.revoked_reason = None
        #: THE SLOW POST-403 RE-PROBE'S STATE (§8.1), all RAM-only for the same
        #: reason the verdict is: nothing about a revocation may survive the
        #: England boot, and a reboot is the documented hard reset of the whole
        #: story. `_revoked_announced` is what keeps "one `revoked` line per
        #: source per boot" true once a refused probe can re-enter the terminal.
        self._revoked_reprobe_at = None
        self._revoked_announced = False
        self.revoked_reprobes = 0
        self.revoked_reprobes_armed = 0
        self._next_due = self.clock.ms()
        self._backoff_level = 0
        self._consecutive_misses = 0
        self._need_full_resync = True
        self._connect_wanted = False
        self.desired_version = 0
        #: Card FT-B's side channel: bounded, RAM-only, one attempt each. Never
        #: persisted -- the only requester that needs durability has its own
        #: spool, and an errand replayed after a reboot would post a snapshot
        #: describing a badge that no longer exists.
        self._errands = []
        #: When the next errand may START. See ERRAND_MIN_GAP_MS.
        self._errand_gap_until = None
        self._inflight = None
        self._last_exchange_ms = None
        #: The last STEERING fields the server sent, whichever exchange carried
        #: them. Never persisted: a policy is the server's live opinion, and a
        #: badge that cached one across a reboot would keep enforcing a kill
        #: switch nobody can reach any more.
        self.policy = {}
        self.suggested_cadence_ms = None

        # Observability counters (all credential-free).
        self.opens = 0
        self.open_failures = 0
        #: EVERY OPEN THIS LOOP HAS ENTERED, whatever came out of it (Lane I).
        #:
        #: **THIS IS WHAT `DeviceBackend.connect_attempts` READS, and the reason
        #: it is not `opens + open_failures` is a fixed defect.** That sum moves
        #: only inside `_attempt_open`'s three classified branches -- `LinkRevoked`,
        #: `LinkError`, success -- so an open that raised anything else moved
        #: nothing at all, and `NetworkService` concluded the frame had paid no
        #: connect and let the doorbell establish a ~2.3 s WSS session in it. The
        #: real escape is a `PostgrestError` out of `parse_poll_rows`, which runs
        #: one line below `device_link._run_blocking`'s adjudication `try` and is
        #: therefore not a `LinkError`.
        #:
        #: Counted on ENTRY, beside the `connecting` line, because that is when
        #: the attempt becomes a fact: whether the frame paid for a handshake is
        #: not a question about an exception taxonomy. **One `connecting` per
        #: count, always** -- which is what makes the number readable on serial.
        #: An `open_attempts` above `opens + open_failures` is itself a finding:
        #: some open raised a class this transport does not classify.
        self.open_attempts = 0
        #: How many times a FULL-BUDGET open skipped the dense ramp (CX-5).
        #: Non-zero means "this badge met something that ate the whole in-frame
        #: budget, not a cheap refusal", which is the one distinction
        #: `open_failures` cannot make. ⚠ Read it as "full budget" and not as
        #: "black hole": at :data:`OPEN_BUDGET_MS` = 5,000 the worst measured
        #: fast failure sits only 1.53x below the bar, so a very slow refusal can
        #: legitimately land here. See :data:`UNREACHABLE_OPEN_MS`.
        self.unreachable_jumps = 0
        #: How many full-budget opens were FORGIVEN the jump because a link edge
        #: had just happened (Lane H). Its pair: `unreachable_jumps` counts the
        #: black holes this badge acted on and this counts the settling windows it
        #: chose not to act on, so the two together are the whole story of the
        #: predicate. ⚠ A boot with a flapping AP used to show only THIS rising,
        #: which was the defect and not the signature: since Lane I the flap shows
        #: one forgiven open and then `unreachable_jumps` climbing, so a rising
        #: pair is a radio AND a peer while a rising `unreachable_forgiven` on its
        #: own is a badge that keeps recovering.
        self.unreachable_forgiven = 0
        #: THE ONE-SHOT, armed by `request_reconnect` -- which is what BOTH radio
        #: edges call -- and consumed by the next open, whatever it does. See
        #: `_jump_unreachable`.
        self._forgive_unreachable_open = False
        #: HOW MANY STALLED OPENS HAVE BEEN FORGIVEN SINCE THE LAST SUCCESSFUL
        #: ONE (Lane I). Armed by a consumed forgiveness and cleared by a
        #: successful open, so :data:`FORGIVEN_STALLS_MAX` bounds the CONSECUTIVE
        #: run rather than the number of link edges -- which is what stops a
        #: flapping AP forgiving a genuine black hole forever. See
        #: :data:`FORGIVEN_STALLS_MAX` for the measurement that made it a defect.
        self._forgiven_stalls = 0
        self.polls = 0
        self.poll_failures = 0
        self.reconnects = 0
        self.commands_in = 0
        #: PERMANENTLY 0 SINCE THE REBUILD, and kept because `network_runtime`
        #: still reads it (`_backend_acks_sent`) as the delivery proof for the
        #: power verbs. It can never advance now that `queue_ack` drops, which is
        #: exactly why `_pump_power_action` acts on the `needed == 0` branch
        #: instead of waiting for it.
        self.acks_sent = 0
        #: Acks handed to `queue_ack` and discarded. The one number that tells an
        #: operator a verb still expects an acknowledgement nothing will send.
        self.acks_dropped = 0
        #: `policies` AND `policy_failures` WENT WITH THE REQUEST KIND (rebuild,
        #: 2026-08-29). The steering read is an errand now, so it is counted by
        #: `errands_done`/`errands_failed` along with every other one, and the
        #: `exchange kind=table` line names it on the wire log.
        self.errands_done = 0
        self.errands_failed = 0
        #: EVERY REQUEST THAT REACHED A TERMINAL OUTCOME IN A FRAME, whatever
        #: kind. One integer, because the question a frame gate asks is not "how
        #: many polls" but "did the socket finish something in THIS frame" -- and
        #: `ft_b_device_probe.frame_gate` needs to tell a frame the badge's own
        #: Python made expensive from a frame the socket did (Card FT-B, F21).
        self.exchanges = 0
        self.doorbells = 0
        self.doorbells_ignored = 0
        self.last_error = None
        self.last_backoff_ms = None

        # -- what each step cost (all milliseconds, all wrap-safe through
        # `clock.diff`, all reported and never acted on). THE OPEN IS KEPT APART
        # FROM EVERY EXCHANGE on purpose: ~735 ms of handshake averaged into a
        # ≤34 ms warm poll is a number that describes neither.
        #: The last ``link.open`` handshake, and the worst one this session.
        self.open_ms = None
        self.open_peak_ms = 0
        #: In-frame link time summed across every exchange this session, and the
        #: worst SINGLE exchange's total. `exchange_busy_ms` divided by
        #: `exchanges` is the mean cost of a request to the frame loop.
        self.exchange_busy_ms = 0
        self.exchange_worst_busy_ms = 0
        #: The worst SINGLE in-frame link step, opens excluded. This is the one
        #: number a 50 ms frame gate cares about: a pump that costs 60 ms is a
        #: dropped frame however cheap the exchange around it was.
        self.link_peak_ms = 0
        # Per-exchange accumulators, reset at every `begin`.
        self._exchange_started_ms = None
        self._exchange_busy_ms = 0
        self._exchange_peak_ms = 0
        self._exchange_steps = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self, now=None):
        """Request the session-start connect. Session start is a tolerant moment."""
        if self.state == STOPPED or self.revoked:
            return self.state
        self._connect_wanted = True
        self._need_full_resync = True
        self._next_due = self.clock.ms() if now is None else now
        return self.state

    def enable_parked_open(self):
        """Select NB-0's multi-frame open before this loop can start one."""

        if self.open_attempts:
            raise LinkError("parked open must be enabled before the first attempt")
        self._parked_open_enabled = True
        self._open_step_budget_ms = OPEN_STEP_BUSY_BUDGET_MS
        self._open_generation = 0
        self._active_open_generation = None
        self._open_forgive = False
        self.open_steps = 0
        return True

    def set_establishment_allowed(self, allowed):
        """The PERSISTENT establishment gate (placement / arbiter deny).

        ⚠ **DENYING WHILE AN OPEN IS IN-FLIGHT ABORTS IT; it does not merely
        withhold the next continuation.** :meth:`poll`'s ``CONNECTING`` branch
        is the only thing that ever advances or LEAVES ``CONNECTING``, so a
        gate-only deny would strand the loop in ``CONNECTING`` forever -- the
        permanently-offline-with-a-green-frame-gate trap NB-0's review named
        (spec 5.2, reviewer 1). The deny therefore drives the same abort
        primitive a radio edge uses (:meth:`_safe_close` -> ``link.abort_open``)
        as a NON-failure and returns the loop to a schedulable ``DISCONNECTED``
        state, so a later re-allow reconnects. Radio and connected-session work
        are untouched either way. Inert until :meth:`enable_parked_open`, so the
        cold-OFF path never reaches the abort.
        """

        if not self._parked_open_enabled:
            return bool(allowed)
        allowed = bool(allowed)
        if not allowed and self.state == CONNECTING:
            self._abort_parked_open("establishment_denied")
        self._establishment_allowed = allowed
        return allowed

    def _abort_parked_open(self, reason):
        """Abort an in-flight parked open as a NON-failure, staying schedulable.

        :meth:`_safe_close` invalidates the generation before cleanup and drives
        ``link.abort_open``, so the socket/PCB/heap return to baseline and no
        stale continuation can publish through this loop. Failure/demotion/
        backoff/forgiveness are deliberately NOT touched: an administrative deny
        is not a connect failure (spec 5.3(a)(4)/(d)/(e)), and due/backoff are
        preserved so a re-allow is immediately schedulable (owner ruling #22).
        ``_connect_wanted`` stays set, so the next allowed, due frame opens
        again. The abort's own ``open_aborted`` record carries the reason.
        """
        self._safe_close(reason)
        self.state = DISCONNECTED
        self._connect_wanted = True

    def stop(self):
        """Tear the socket down and refuse further connects until restarted."""
        self._safe_close("stop")
        self.state = STOPPED
        self._connect_wanted = False
        self._drop_errands()
        return self.state

    def restart(self):
        """TaskSlot restart hook: drop any socket and re-arm a fresh connect.

        The network task raising is itself a liveness signal — do not assume the
        socket is usable. Re-arm at backoff so a crash-looping task cannot busy
        the frame with handshakes.
        """
        self._safe_close("task_restart")
        self._consecutive_misses = 0
        self._drop_errands()
        if self.state != STOPPED and not self.revoked:
            self._enter_backoff(self.clock.ms(), reason="task_restart")
            self._connect_wanted = True
        return self.state

    def request_reconnect(self, now=None):
        """Owner-initiated reconnect (a tolerant moment): connect on the next poll.

        A revoked session refuses even this: the ruling is "stop until the next
        boot", so the Settings copy is "reboot to retry" rather than a button
        that silently resumes polling a server that already said no.

        **AND IT ARMS THE UNREACHABLE-JUMP FORGIVENESS** (Lane H). This is the
        method BOTH of `DeviceBackend.poll`'s radio edges call, so it is the one
        place that knows "the link under this socket just changed" -- see
        `_jump_unreachable` for what the one-shot buys and what BOUNDS it. Armed
        above the revoked/stopped guard would be wrong and it is not: a terminal
        loop opens nothing, so a flag set there could only sit there.

        ⚠ **AND `DeviceBackend.poll` ALSO CALLS IT ON THE LOOP BUILD** (Lane J,
        2026-08-24), which is what a BOOT has instead of an edge. It used to call
        this only under `if self._loop is not None`, one line above the build, so
        the boot's first open was never forgiven -- the one edge that produces the
        settling case, measured burning the whole budget on 5 of 7 cold boots.
        Nothing here changed for that fix; the CALLER moved below the build.

        ⚠ **ARMING IS NOT GRANTING, and that distinction is Lane I's fix.** This
        method is called on every radio edge, so a flapping AP arms the one-shot
        over and over; the grant is bounded separately by
        :data:`FORGIVEN_STALLS_MAX` at the point of consumption. Nothing here
        resets that bound -- only a successful open does.
        """
        if self.state == STOPPED or self.revoked:
            return self.state
        self._safe_close("reconnect")
        # ⚠ **THE LEVEL IS NOT ZEROED HERE ANY MORE (2026-08-26), AND THE RULE WAS
        # ALREADY WRITTEN ONE COUNTER OVER.** The forgiveness bound below resets only
        # on a successful open, under a Lane I comment that says why in as many
        # words: "Not in `request_reconnect`: an edge is what a flapping AP produces
        # by the dozen, and resetting there is the defect `FORGIVEN_STALLS_MAX`
        # names." That argument applies identically to the backoff level, and this
        # line was the one place it had not been applied -- so `_forgiven_stalls`
        # obeyed the rule while its sibling two lines away broke it.
        #
        # WHAT THE OWNER SAW: freezes "multiple times". `DeviceBackend` calls this on
        # every `wifi_lost` edge, so N flaps minted N ladders starting from the base,
        # and each fresh cascade was free to hit a `getaddrinfo` that blocks
        # 13.1-14.0 s on a dead route and cannot be bounded (no socket timeout on
        # this port). Nothing ever became more reluctant.
        #
        # PROMPTNESS AND FORGIVENESS ARE DIFFERENT THINGS, and zeroing the level
        # conflated them. `_next_due` below still fires this attempt IMMEDIATELY,
        # which is what a wearer who walked back into coverage needs; the ladder is
        # what stops a flapping link buying a full-price cascade per flap. A
        # successful open then clears the level at its own site, so a genuinely
        # recovered link sheds the ladder on the evidence rather than on the edge.
        self._forgive_unreachable_open = True
        self._connect_wanted = True
        self._need_full_resync = True
        self._next_due = self.clock.ms() if now is None else now
        # Leaving CONNECTING untouched strands a parked open forever: poll's
        # CONNECTING branch owns continuations, and the worker was just closed.
        self.state = DISCONNECTED
        self._emit("reconnect_requested")
        return self.state

    def set_active(self, active):
        """Flip active/idle cadence. Shortens the next due if we just went active."""
        active = bool(active)
        if active and not self.active:
            # Pull the next poll forward so a foregrounded view feels responsive,
            # but never earlier than now.
            self._next_due = self.clock.ms()
        self.active = active
        return self.active

    def force_active_cadence(self, on=True):
        """TEST KNOB: hold the ACTIVE cadence so a measurement has one period.

        **THIS EXISTS TO MAKE AN INTERACTIVE MEASUREMENT DETERMINISTIC AND IT IS
        A FIELD HAZARD.** An idle badge polls every 30 s, which means a wearer
        watching for the rhythmic freeze a deployed badge showed once would wait
        minutes between samples; forced ACTIVE it is one exchange every 3 s, and
        the UI impact is a rhythm an eye can see. Left on, the same knob is
        rhythmic stalls plus ten times the radio duty cycle for a wearer who
        never asked for either.

        So the containment is the API, not a warning:

        * **RAM-ONLY on this object.** Nothing is written, there is no
          preference, no command type and no Settings row — ``badgelink/tests/
          test_ft_b_poll_cost.py`` walks the AST of every ``/system/lib`` module
          and every Settings file and fails if one of them can reach this. It
          dies at the next physical RESET, and it dies earlier than that if
          networking is toggled OFF, because the flag lives on the ``PollLoop``
          the socket belongs to.
        * **NOT a constructor keyword**, for the same reason: a keyword is a
          path a config file could take.
        * **It overrides the CADENCE DECISION and nothing else.** Backoff,
          revocation, the missed-ack liveness rule, the errand gap and the
          doorbell's refusals are untouched — a 403 still stops the session with
          the knob engaged, which is the one property here that is a security
          property rather than a UX one.
        * **It cannot make the badge chattier than the transport already
          permits.** The forced value is ``active_cadence_ms``, which IS
          :data:`ACTIVE_CADENCE_MIN_MS`, the floor the server's own steering is
          clamped to. Steering is ignored while engaged (a period a server may
          stretch to 5 s is not a measurement window) but still RECORDED, so
          releasing the knob resumes it.

        Engaging pulls a poll that is scheduled FURTHER OUT than the forced
        cadence in to it, and only while CONNECTED — otherwise a knob thrown
        during backoff would shorten a reconnect, which is exactly what the
        jittered schedule exists to stop for a herd of 800 badges.

        Returns the resulting flag.
        """
        self.cadence_forced_active = bool(on)
        if self.cadence_forced_active and self.state == CONNECTED:
            target = self.clock.add(self.clock.ms(), self.active_cadence_ms)
            if self.clock.diff(self._next_due, target) > 0:
                self._next_due = target
        self._emit(
            "cadence_forced" if self.cadence_forced_active
            else "cadence_released",
            cadence_ms=self.cadence_ms(),
        )
        return self.cadence_forced_active

    def pull_forward(self, now=None, reason="doorbell", delay_ms=0):
        """A DOORBELL: bring the next poll forward. Carries nothing, proves nothing.

        This seam now serves only the private-topic compatibility branch. Fleet
        broadcasts carry and apply their action on the shared topic instead. A
        private-topic ring still means only "go look", so dropping or duplicating
        one costs dev-fixture latency and no production action.

        Three refusals are the load-bearing part:

        * **Only while CONNECTED.** In ``BACKOFF`` the next event is an
          ``open()`` handshake, and letting a server-sent frame pull *that*
          forward would hand a herd of 800 badges a way to defeat the jittered
          reconnect schedule the backoff exists to spread. A doorbell may
          shorten a poll; it may never shorten a reconnect.
        * **Never earlier than now.** ``_next_due`` moves to ``now`` (or to
          ``now + delay_ms``), so a doorbell cannot make a poll retroactively
          overdue or stack up work.
        * **Never LATER than it already was.** ``delay_ms`` is Card FT-B's herd
          jitter, and a "pull forward" that pushed a poll out would be a way for
          a server-sent frame to make a badge quieter than its own cadence. If
          the jittered target is past the poll already scheduled, the doorbell
          does nothing and says so.
        * **No side effects.** It does not flip ``active`` (the foreground view
          is that authority), does not reset the backoff level, does not clear
          the resync obligation, does not queue an ack and does not read the
          broadcast payload — layer 3 never passes one.

        Returns True when the next poll actually moved.
        """
        if self.state != CONNECTED:
            self.doorbells_ignored += 1
            return False
        now = self.clock.ms() if now is None else now
        self.doorbells += 1
        if self.clock.diff(self._next_due, now) <= 0:
            # Already due (or overdue): the poll the doorbell is asking for is
            # the one the next tick was going to run anyway.
            return False
        if delay_ms:
            target = self.clock.add(now, int(delay_ms))
            if self.clock.diff(self._next_due, target) <= 0:
                # The jittered moment is no sooner than the poll already
                # scheduled, so there is nothing to pull forward.
                return False
        else:
            target = now
        self._next_due = target
        self._emit("doorbell", reason=reason)
        return True

    def queue_ack(self, ack):
        """Accept an ack and DROP IT. There is no ack RPC any more.

        *** RETAINED AS A SEAM, NOT AS A FEATURE, AND IT ANSWERS 0 ON PURPOSE. ***
        `badgelink_badge_ack_command_self` is dropped by the rebuild
        (`migrations/20260829060000_badge_rebuild_v2.sql` §6a). Nothing routine
        reaches here now -- the broadcast lane posts a receipt instead and never
        acks. The compatibility command callback and its ledger re-ack branch
        still call this seam in host probes; deleting it would turn stale probe
        input into an `AttributeError` inside a frame, while sending would put a
        request to a function that no longer exists onto the wire. So it accepts
        and discards without reviving the removed queue.

        THE RETURN VALUE IS THE INTERESTING PART. `0` is the retained
        compatibility machinery's "cannot prove" answer, so an old callback
        cannot pretend an ack left. Production power actions use the independent
        fleet-receipt gate and never call this seam.

        ⚠ WHAT THAT COSTS IS REAL AND IS NOT FIXED HERE: an operator can no
        longer distinguish a badge that slept on command from one that died. The
        receipt POST is fire-and-forget with jitter, which is not the same
        guarantee. Flagged for the owner rather than papered over.
        """
        if ack is None:
            raise ValueError("ack payload must not be None")
        self.acks_dropped += 1
        return 0

    # -- the per-tick pump -------------------------------------------------

    def poll(self, now=None, allow_establishment=True):
        """One cooperative step. Called every supervisor network tick.

        ``allow_establishment`` is the NB-0 arbiter's PER-FRAME gate, and it is
        deliberately NOT :attr:`_establishment_allowed`. This one only DEFERS an
        open start/continuation for the frame the owner passes ``False`` -- a
        correctness chore already spent it (spec 5.3(b)) -- and the next frame
        with ``True`` continues the SAME parked attempt. It never aborts, never
        scores, never leaves a schedulable state. ``_establishment_allowed`` is
        the PERSISTENT gate (placement / arbiter deny) whose ``False`` aborts an
        in-flight open; see :meth:`set_establishment_allowed`. OFF never passes
        ``False`` (its backend calls ``poll(now)``), so the default keeps the
        cold-OFF path byte-for-byte unchanged.
        """
        now = self.clock.ms() if now is None else now
        if self.state == STOPPED:
            # STOPPED is terminal and stays terminal: it is a LOCAL decision (a
            # Settings press, a service teardown), so there is nothing to
            # re-probe -- asking the server again would answer a question nobody
            # asked.
            return self.state
        if self.state == REVOKED:
            # REVOKED IS NO LONGER TERMINAL FOR THE BOOT (§8.1). See
            # REVOKED_REPROBE_MIN_MS: under the shared fleet token a 403 revokes
            # ~800 badges at once, so a transient server mistake would take the
            # whole hall dark until each badge was physically rebooted. Until the
            # armed tick this is the same immediate return it always was -- no
            # open, no poll, no radio.
            if not self._revoked_reprobe_due(now):
                return self.state
            self._begin_revoked_reprobe(now)
        if self.state in (DISCONNECTED, BACKOFF):
            # `_errands_due` JOINED THIS GATE WITH THE REBUILD. It used to be
            # `_due` alone, which was complete when the poll was the reason to
            # have a socket: anything else worth sending was queued behind a poll
            # that was already coming. Errands are now the ONLY traffic, so a
            # score finishing, a receipt arming or the first heartbeat could
            # otherwise sit on a closed socket for a whole cadence with the
            # transport believing it had nothing to do.
            if (self._connect_wanted
                    and (self._due(now) or self._errands_due(now))
                    and self._establishment_allowed and allow_establishment):
                if self._parked_open_enabled:
                    self._begin_parked_open(now)
                else:
                    self._attempt_open(now)
            return self.state
        if self.state == CONNECTING:
            if (self._parked_open_enabled and self._establishment_allowed
                    and allow_establishment):
                self._continue_parked_open(now)
            return self.state
        if self.state == CONNECTED:
            self._service_connected(now)
        return self.state

    # -- internals ---------------------------------------------------------

    def _due(self, now):
        return self.clock.diff(now, self._next_due) >= 0

    def cadence_ms(self):
        if self.cadence_forced_active:
            # The TEST KNOB, and note what it does NOT do: `self.active` is
            # untouched, because the app foreground is that authority and
            # `NetworkService.poll` re-asserts it on every single frame -- a knob
            # implemented as `set_active(True)` would be erased one frame later.
            return self.active_cadence_ms
        return self.active_cadence_ms if self.active else self.idle_cadence_ms

    def _schedule_next(self, now, cadence_ms):
        self._next_due = self.clock.add(now, int(cadence_ms))

    def _attempt_open(self, now):
        self.state = CONNECTING
        # COUNTED HERE, WITH THE ANNOUNCEMENT AND BEFORE THE CALL (Lane I). Every
        # exit below is an outcome of an attempt that has already happened, and
        # one of those exits is "the exception was not ours" -- which returns
        # through no branch at all. See `open_attempts`.
        self.open_attempts += 1
        self._emit("connecting", backoff_level=self._backoff_level)
        # TWO TICKS AROUND THE ONE BLOCKING CALL IN THIS MODULE. Measured apart
        # from every exchange: this is the ~735 ms handshake the whole
        # keep-alive design exists to pay only at a tolerant moment, and folding
        # it into the per-request numbers would hide both.
        entered = self.clock.ms()
        # READ-AND-CLEAR, so the forgiveness cannot outlive this ONE open (Lane
        # H). Taken here rather than inside `_jump_unreachable` because every
        # branch below returns: a refusal, a 403 and a success all consume it, and
        # a flag cleared in only one of four exits is a flag that leaks. What the
        # flag ARMS is one open; what it GRANTS is bounded by
        # `FORGIVEN_STALLS_MAX` -- see `_jump_unreachable` (Lane I).
        forgive = self._forgive_unreachable_open
        self._forgive_unreachable_open = False
        try:
            self.link.open(now)
        except LinkRevoked as exc:
            # 403 at the handshake moment: a verdict, so stop rather than retry.
            self._note_open(entered)
            self.open_failures += 1
            self.last_error = _error_text(exc)
            self._enter_revoked(now, reason="open_forbidden")
            return
        except LinkError as exc:
            self._note_open(entered)
            self.open_failures += 1
            self.last_error = _error_text(exc)
            # CX-5, and note WHERE it sits: after the `LinkRevoked` clause above,
            # so a 403 can never reach it, and before `_enter_backoff`, because
            # that method reads the level to compute this delay and increments it
            # afterwards. Raising the level here is therefore what makes THIS
            # entry the 16-32 s band rather than the next one.
            #
            # **THE TEST IS THE FAILURE'S CLASS, NOT ITS WALL SPAN (NB-i).** This
            # read `if span >= self.unreachable_open_ms` until 2026-08-24, which
            # was the same number in two hands -- correct only while the open is
            # one blocking frame, and the NB spec's phase 1(a) parks it across
            # frames. `LinkStalled` says "nothing answered until the deadline",
            # which is what the ramp actually wants to know, and it means what it
            # says whether the open held one frame or a hundred.
            if isinstance(exc, LinkStalled):
                self._jump_unreachable(forgiven=forgive)
            self._enter_backoff(now, reason="open_failed")
            self._emit("open_failed", error=self.last_error,
                       open_ms=self.open_ms)
            return
        self._note_open(entered)
        self.opens += 1
        if self._backoff_level:
            self.reconnects += 1
        self.state = CONNECTED
        self._backoff_level = 0
        # AND THE FORGIVENESS BOUND RESETS HERE, beside the level, because a
        # successful open is the only evidence that the path works (Lane I). Not
        # in `request_reconnect`: an edge is what a flapping AP produces by the
        # dozen, and resetting there is the defect `FORGIVEN_STALLS_MAX` names.
        self._forgiven_stalls = 0
        self._consecutive_misses = 0
        self._need_full_resync = True
        # Poll immediately after a successful (re)connect to re-fetch desired
        # state. NO STEERING READ IS ARMED HERE and there is no longer one to arm:
        # the settings cadence belongs to `NetworkService._pump_fleet_settings`,
        # which phases itself per badge. This line used to be `self._policy_due =
        # now` unconditionally, so every reconnect -- every AP blip, every
        # missed-ack teardown, every `restart()` -- re-paid a request whose whole
        # design is a 5-minute cadence (CX-8).
        self._next_due = now
        self._emit("connected", resync=True, open_ms=self.open_ms)

    def _begin_parked_open(self, now):
        """Admit one open attempt and immediately spend its first bounded step."""

        self.state = CONNECTING
        self.open_attempts += 1
        self._open_generation += 1
        self._active_open_generation = self._open_generation
        self._emit("connecting", backoff_level=self._backoff_level)
        # An edge buys one ATTEMPT, not one frame. Capture and consume the
        # forgiveness exactly where the attempt becomes real; a chore-denied
        # due frame reaches none of this and mints/consumes nothing.
        self._open_forgive = self._forgive_unreachable_open
        self._forgive_unreachable_open = False
        self.open_ms = 0
        self._continue_parked_open(now)

    def _continue_parked_open(self, now):
        """Advance one generation and publish only its fresh terminal outcome."""

        generation = self._active_open_generation
        if generation is None:
            # This should be unreachable, but returning to a schedulable state
            # is safer than reproducing the permanently-green/offline trap.
            self.state = DISCONNECTED
            return self.state
        entered = self.clock.ms()
        self.open_steps += 1
        try:
            outcome = self.link.open_step(
                now, self._open_step_budget_ms, generation
            )
        except LinkRevoked as exc:
            self._note_parked_open_step(entered)
            terminal = self.clock.ms()
            self._active_open_generation = None
            self.open_failures += 1
            self.last_error = _error_text(exc)
            self._enter_revoked(terminal, reason="open_forbidden")
            return self.state
        except LinkError as exc:
            self._note_parked_open_step(entered)
            terminal = self.clock.ms()
            self._active_open_generation = None
            self.open_failures += 1
            self.last_error = _error_text(exc)
            if isinstance(exc, LinkStalled):
                self._jump_unreachable(forgiven=self._open_forgive)
            self._enter_backoff(terminal, reason="open_failed")
            self._emit("open_failed", error=self.last_error,
                       open_ms=self.open_ms)
            return self.state
        self._note_parked_open_step(entered)
        if outcome is PENDING:
            return self.state
        # Recheck the generation at the publication seam. Today `open_step` is
        # synchronous, but this is the contract that makes a later callback or
        # completion-vs-radio-edge race incapable of handing off a stale poll.
        if generation != self._active_open_generation:
            return self.state
        terminal = self.clock.ms()
        self._active_open_generation = None
        self.opens += 1
        if self._backoff_level:
            self.reconnects += 1
        self.state = CONNECTED
        self._backoff_level = 0
        self._forgiven_stalls = 0
        self._consecutive_misses = 0
        self._need_full_resync = True
        self._next_due = terminal
        self._emit("connected", resync=True, open_ms=self.open_ms)
        return self.state

    def _note_parked_open_step(self, entered):
        """Price the whole outer call: the denomination one frame can feel."""

        span = self.clock.diff(self.clock.ms(), entered)
        if span < 0:
            span = 0
        if self.open_ms is None or span > self.open_ms:
            self.open_ms = span
        if span > self.open_peak_ms:
            self.open_peak_ms = span
        return span

    def _service_connected(self, now):
        # Pump an in-flight request every tick; otherwise start one when due.
        # Exactly one bounded link operation per tick keeps every frame cheap.
        if self._inflight is not None:
            self._pump_inflight(now)
        elif self._due(now) or self._errands_due(now):
            self._begin_next(now)

    def set_suggested_cadence(self, cadence_ms):
        """The exchange cadence the SERVER suggests, from the fleet settings.

        THE CLAMP IS WHY THIS IS A SETTER AND NOT AN ASSIGNMENT: `_resolved_cadence`
        bounds whatever arrives into the ACTIVE or IDLE band, so nothing an
        operator (or a mistyped row) can send makes a badge ask faster than its own
        floor or slower than its own ceiling. Explicit ``None`` clears the prior
        suggestion because it is Admin's well-formed "badge default" value;
        every other non-integer stays ignored, since unreadable input is not an
        instruction to forget a readable value.

        Reached from `NetworkService._apply_settings` through
        `DeviceBackend.set_suggested_cadence`; it is the one steering field that
        stays this object's, because the interval between exchanges belongs where
        the exchanges are.
        """
        if cadence_ms is None:
            self.suggested_cadence_ms = None
            return None
        if isinstance(cadence_ms, bool) or not isinstance(cadence_ms, int):
            return self.suggested_cadence_ms
        self.suggested_cadence_ms = cadence_ms
        return self.suggested_cadence_ms

    def _begin_next(self, now):
        # *** THE LADDER IS ONE RUNG NOW: ERRANDS. *** It was ack, then poll, then
        # errand, and the two rungs above disappeared on 2026-08-29 with the RPCs
        # behind them -- `migrations/20260829060000_badge_rebuild_v2.sql` §6a drops
        # `badgelink_badge_poll_self` and `badgelink_badge_ack_command_self`.
        #
        # This is what "THE 3-5s CLAIM PATCH IS DELETED" actually means in code.
        # Moments now arrive on the doorbell and are acted on directly, so there
        # is no queue to drain and nothing to acknowledge; every remaining reason
        # to touch the network -- the ~60 s registration, the ~5 min settings
        # read, the score drain, the schedule sync, a broadcast receipt -- was
        # already an errand. Keeping a poll rung pointed at a dropped RPC would
        # not have failed loudly: PostgREST answers PGRST202, `parse_response`
        # calls that retryable, and ~1,000 badges would have retried a function that
        # does not exist every three seconds for a whole day.
        #
        # THE CADENCE DID NOT DIE WITH THE POLL, IT CHANGED JOBS. `_next_due` used
        # to say "ask the server for work"; it now says "wake and see whether this
        # badge has any of its own". The else-branch below re-arms it, which is
        # load-bearing in a way the old ladder never needed: `_due` gates the OPEN
        # (see `poll`), so a `_next_due` left permanently hot would call this
        # method on every rendered frame forever.
        if self._errands_due(now):
            kind, payload = self._errands[0][0], self._errands[0][1]
            self._errand_gap_until = self.clock.add(now, ERRAND_MIN_GAP_MS)
        else:
            # Nothing of our own to send this wake. Re-arm and come back; the
            # socket stays open, which is what makes the next errand cheap.
            self._schedule_next(now, self.cadence_ms())
            return
        # The exchange's clock starts at the FRAME tick, not at `clock.ms()`:
        # `span_ms` is meant to be comparable with the caller's own frame
        # accounting, and a request spans several frames on hardware.
        self._exchange_started_ms = now
        self._exchange_busy_ms = 0
        self._exchange_peak_ms = 0
        self._exchange_steps = 0
        entered = self.clock.ms()
        try:
            self.link.begin(kind, payload, now)
        except LinkError as exc:
            self._note_link_step(entered)
            self._fail_exchange(now, exc, kind)
            return
        self._note_link_step(entered)
        self._inflight = kind

    def _pump_inflight(self, now):
        kind = self._inflight
        entered = self.clock.ms()
        try:
            outcome = self.link.pump(now)
        except LinkError as exc:
            self._note_link_step(entered)
            self._inflight = None
            self._fail_exchange(now, exc, kind)
            return
        self._note_link_step(entered)
        if outcome is PENDING:
            return
        self._inflight = None
        self.exchanges += 1
        self._report_exchange(now, kind, True)
        self._consecutive_misses = 0
        self._last_exchange_ms = now
        if kind == "table" or kind == "rpc":
            self.errands_done += 1
            data = outcome.get("data") if isinstance(outcome, dict) else None
            self._finish_errand(True, data)
        else:
            # UNREACHABLE, AND LOUD RATHER THAN SILENT. `_begin_next` can only
            # start an errand now that the poll and ack rungs are gone, so a kind
            # arriving here means someone added a rung without adding its
            # completion. Counting it as a generic success would make that
            # invisible; a raise into the caller's own containment names it.
            raise LinkError("unknown in-flight kind: {}".format(kind))

    def _note_open(self, entered):
        """One handshake's cost. Never averaged into an exchange."""
        span = self.clock.diff(self.clock.ms(), entered)
        if span < 0:
            span = 0
        self.open_ms = span
        if span > self.open_peak_ms:
            self.open_peak_ms = span
        return span

    def _note_link_step(self, entered):
        """ONE BOUNDED LINK STEP, PRICED. Two ticks, four integer updates.

        Deliberately allocation-free and deliberately silent: the record is
        emitted once per EXCHANGE, not once per step, so a request that spans
        five frames costs five integer additions and one dict. A frame that
        starts no request and pumps nothing reaches none of this.
        """
        span = self.clock.diff(self.clock.ms(), entered)
        if span < 0:
            span = 0
        self._exchange_steps += 1
        self._exchange_busy_ms += span
        if span > self._exchange_peak_ms:
            self._exchange_peak_ms = span
        if span > self.link_peak_ms:
            self.link_peak_ms = span

    def _report_exchange(self, now, kind, ok):
        """FOUR NUMBERS, BECAUSE THEY ARE FOUR DIFFERENT QUESTIONS.

        ``busy_ms`` is what the frames actually paid inside the link, which is
        the frame-cost number and the one comparable with the device-recorded
        ≤34 ms warm request. ``peak_ms`` is the worst single in-frame step, which
        is the only one a 50 ms frame gate can fail on. ``span_ms`` is begin to
        completion in frame ticks — the wearer's latency, necessarily larger,
        because a keep-alive request spans several ``AsyncFetch.update()`` calls.
        ``steps`` says how many frames carried it.
        """
        started = self._exchange_started_ms
        span = 0 if started is None else self.clock.diff(now, started)
        if span < 0:
            span = 0
        self._exchange_started_ms = None
        self.exchange_busy_ms += self._exchange_busy_ms
        if self._exchange_busy_ms > self.exchange_worst_busy_ms:
            self.exchange_worst_busy_ms = self._exchange_busy_ms
        self._emit("exchange", kind=kind, ok=ok,
                   busy_ms=self._exchange_busy_ms,
                   peak_ms=self._exchange_peak_ms,
                   span_ms=span, steps=self._exchange_steps)

    def _fail_exchange(self, now, exc, kind):
        self.exchanges += 1
        self._report_exchange(now, kind, False)
        if kind == "poll":
            self.poll_failures += 1
        self.last_error = _error_text(exc)
        if kind == "table" or kind == "rpc":
            # A 403 ON AN ERRAND IS NOT A REVOCATION, and telling the two apart
            # is the whole reason errands have their own failure path.
            #
            # `badgelink_badge_poll` and the ack RPC are whoami-scoped: a 403
            # there means THIS BADGE is denied, so the session is over. An errand
            # is a PER-RESOURCE write -- `grants.allowed('scores', 'write')` is
            # not provisioned by `badgelink_pair_bind` today, so the very first
            # score insert on a real badge would 403 -- and letting that stop the
            # poll loop would mean a game posting a score took the badge's whole
            # transport down for the boot. So: notify, count, carry on.
            #
            # A non-403 LinkError still registers a miss, because a socket that
            # died under an errand is exactly as dead as one that died under a
            # poll and the liveness machinery must see it.
            self.errands_failed += 1
            self._finish_errand(False, None)
            if not isinstance(exc, LinkRevoked):
                self._register_miss(now)
            return
        if isinstance(exc, LinkRevoked):
            # Not a missed ack: the server answered, and the answer was "no".
            # Skip the liveness/backoff machinery entirely and stop the session.
            self._enter_revoked(now, reason="{}_forbidden".format(kind))
            return
        self._register_miss(now)

    # -- the errand channel (Card FT-B) ------------------------------------
    #
    # ONE SIDE CHANNEL, NOT ONE PER FEATURE. `report_state`'s badge_state update,
    # the scorebox's drain and the schedule sync all need a request on the
    # already-open socket, and the alternative was three request kinds, three
    # parsers and three places to get the priority wrong. So the transport gains
    # exactly one bounded queue and every feature is a caller.
    #
    # AN ERRAND IS ATTEMPTED ONCE. Its sink is told (False, None) on failure and
    # the errand is dropped, because the only requester that actually needs a
    # retry has a DURABLE spool of its own (`scorebox`) and a retry policy in the
    # transport would be a second, worse copy of it.

    def queue_errand(self, kind, payload, sink=None, key=None):
        """Queue one side request. Returns True when it was accepted.

        ``key`` COALESCES: a second errand with the same key replaces the first
        rather than queueing behind it. `report_state` uses it, because writing a
        stale snapshot and then a fresh one is strictly worse than writing only
        the fresh one.

        Bounded at :data:`MAX_ERRANDS`. A full queue is a refusal, not a drop of
        somebody else's work, so the caller learns it has to try later.
        """

        if kind not in ("table", "rpc"):
            raise ValueError("errand kind must be 'table' or 'rpc'")
        if not isinstance(payload, dict):
            raise ValueError("errand payload must be an object")
        if key is not None:
            # INDEX 0 IS SKIPPED WHILE IT IS ON THE WIRE, and that is a bug fix
            # rather than caution. `_begin_next` starts `self._errands[0]` and
            # LEAVES it in the list until `_finish_errand` pops it, so replacing
            # index 0 mid-flight would hand the in-flight response to the NEW
            # errand's sink and never send the new request at all -- an ack of
            # `applied` for a row that was dropped.
            first = 1 if (self._inflight in ("table", "rpc")
                          and self._errands) else 0
            for index in range(first, len(self._errands)):
                if self._errands[index][3] == key:
                    self._errands[index] = (kind, payload, sink, key)
                    return True
        if len(self._errands) >= MAX_ERRANDS:
            return False
        self._errands.append((kind, payload, sink, key))
        # NOT URGENT, AND RATE-LIMITED. `queue_ack` pulls the next exchange to
        # `now` because a wearer just did something; an errand does not touch the
        # cadence at all.
        #
        # But it does not WAIT for the cadence either, and an earlier version of
        # this comment claimed it did. It cannot: a badge coming back online with
        # 64 spooled scores would take 32 minutes to drain them at a 30 s idle
        # cadence. So errands run promptly and are bounded instead --
        # `ERRAND_MIN_GAP_MS` apart, one at a time. THE NUMBER IS THE HERD, the
        # same argument as the ring jitter: 800 badges draining a full spool as
        # fast as the socket allows is ~51,000 requests, and one second apart it
        # is ~800/second, which is the peak the ring jitter already accepts.
        return True

    def _errands_due(self, now):
        if not self._errands:
            return False
        if self._errand_gap_until is None:
            return True
        return self.clock.diff(now, self._errand_gap_until) >= 0

    def _drop_errands(self):
        """Tell every waiting requester the socket is gone.  Never raises."""

        pending = self._errands
        self._errands = []
        for _kind, _payload, sink, _key in pending:
            if sink is None:
                continue
            try:
                sink(False, None)
            except Exception as exc:
                self.last_error = _error_text(exc)

    def _finish_errand(self, ok, data):
        if not self._errands:
            return
        _kind, _payload, sink, _key = self._errands.pop(0)
        if sink is None:
            return
        try:
            sink(ok, data)
        except Exception as exc:
            # A requester's callback may not break the transport that ran it.
            self.last_error = _error_text(exc)

    def _process_response(self, response, now=None):
        if not isinstance(response, dict):
            self._need_full_resync = False
            return
        version = response.get("desired_version")
        if isinstance(version, int) and not isinstance(version, bool):
            if version >= self.desired_version:
                self.desired_version = version
        commands = response.get("commands")
        if isinstance(commands, (list, tuple)):
            for command in commands:
                self.commands_in += 1
                if self._command_sink is not None:
                    self._command_sink(command)
            if commands:
                self.set_active(True)
        # THE SAME STEERING CHANNEL. Read here as well as from the dedicated
        # policy RPC, so a server that later folds `push_enabled` into the poll
        # response needs no client change at all.
        self._process_steering(response, now)
        # Desired state has now been (re)read; clear the resync obligation.
        self._need_full_resync = False

    def _process_steering(self, fields, now=None):
        """Apply the server's steering fields, whichever exchange carried them.

        Nothing here interprets the policy: the fields are handed to the
        ``policy_sink`` as they arrived, and the FAIL DIRECTION for an absent or
        malformed value belongs to the consumer that knows what the field means
        (``pushlink.PushPolicy.set_remote``). This module's only job is to not
        invent one.

        ``now`` is the FRAME TICK when a caller has one, and ``None`` falls back
        to ``clock.ms()`` -- the parameter is optional because one test drives
        `_process_response` directly and because the value it feeds is a 5-minute
        cadence, where the two differ by one exchange's worth of milliseconds.
        """
        if not isinstance(fields, dict):
            return False
        if now is None:
            now = self.clock.ms()
        seen = False
        for key in ("push_enabled", "policy_version", "source"):
            if key in fields:
                self.policy[key] = fields[key]
                seen = True
        cadence = fields.get("next_cadence_ms")
        if isinstance(cadence, int) and not isinstance(cadence, bool):
            self.suggested_cadence_ms = cadence
        if not seen:
            return False
        # STEERING ARRIVED, SO THE INTERVAL IS SERVED, WHICHEVER EXCHANGE CARRIED
        # IT (CX-8, 2026-08-23). This advance used to live on `NetworkService`
        # instead, which meant the SERVICE believed a poll-borne policy retired
        # the dedicated read while this loop went on issuing it -- two objects with
        # two opinions about one cadence, and the disagreement is what CX-8's
        # correction closed. The loop is the single owner now and the service
        # mirrors it, so the promise `_process_response` makes when it calls this
        # for a POLL response ("a server that folds `push_enabled` into the poll
        # response needs no client change at all") is finally true of the requests
        # as well as of the fields. Inert against today's server, which sends no
        # steering keys on a poll.
        #
        # NO DUE TIME IS ADVANCED HERE ANY MORE (rebuild, 2026-08-29). This used
        # to move the loop's own steering cadence from the ANSWER as well as from
        # the ISSUE; the cadence belongs to `NetworkService._pump_fleet_settings`
        # now, and there is nothing here to keep in step with it.
        self._emit("policy", version=self.policy.get("policy_version"))
        if self._policy_sink is not None:
            self._policy_sink(dict(self.policy))
        return True

    def _resolved_cadence(self, response):
        if self.cadence_forced_active:
            # A FIXED PERIOD IS THE WHOLE POINT. `_process_response` has already
            # recorded the server's suggestion in `suggested_cadence_ms`, so
            # releasing the knob resumes steering with nothing lost -- and the
            # forced value is the ACTIVE floor, so this cannot poll faster than
            # the band steering is clamped to anyway.
            return self.active_cadence_ms
        suggested = None
        if isinstance(response, dict):
            suggested = response.get("next_cadence_ms")
        if not isinstance(suggested, int) or isinstance(suggested, bool):
            # A cadence the steering channel supplied on some earlier exchange
            # still steers; it is the same channel, clamped the same way.
            suggested = self.suggested_cadence_ms
        if not isinstance(suggested, int) or isinstance(suggested, bool):
            return self.cadence_ms()
        if self.active:
            return _clamp(suggested, ACTIVE_CADENCE_MIN_MS, ACTIVE_CADENCE_MAX_MS)
        return _clamp(suggested, self.active_cadence_ms, IDLE_CADENCE_MAX_MS)

    def _register_miss(self, now):
        self._consecutive_misses += 1
        self._emit("missed_ack", misses=self._consecutive_misses, error=self.last_error)
        if self._consecutive_misses >= self.liveness_misses:
            self._safe_close("missed_ack")
            self._enter_backoff(now, reason="missed_ack")
            self._connect_wanted = True
        else:
            # Keep the socket, retry the exchange one cadence later.
            self._schedule_next(now, self.cadence_ms())

    def _enter_revoked(self, now, reason):
        """Stop for the rest of this boot after a 403 (owner ruling 2026-08-19).

        Deliberately RAM-ONLY. Nothing is written to ``/badgelink_state.json``
        and **pair state is not touched**: revoked is not unpaired (v2 has no
        badge-side unpair), and a grant restored on the server must come back on
        the next boot without the wearer re-pairing. That is also why this is
        terminal only for the session — a power cycle re-checks, which is the
        cheapest correct retry for a badge with no server-push channel.
        """
        self._safe_close("revoked")
        self._connect_wanted = False
        self.revoked = True
        self.revoked_reason = reason
        self.state = REVOKED
        # ARM THE SLOW RE-PROBE (§8.1). Armed on the FIRST revocation and re-armed
        # on every refused probe after it, so the loop lives for the boot instead
        # of ending it. Wrap-safe via the clock's own `add`, because a 15-30 minute
        # interval is long enough to cross a `ticks_ms` wrap and a raw sum would
        # then fire immediately or never.
        span = REVOKED_REPROBE_MAX_MS - REVOKED_REPROBE_MIN_MS
        try:
            fraction = self._rand01()
        except Exception:
            fraction = 0.5
        if fraction < 0:
            fraction = 0.0
        elif fraction >= 1:
            fraction = 0.999
        delay = REVOKED_REPROBE_MIN_MS + int(fraction * span)
        self._revoked_reprobe_at = self.clock.add(now, delay)
        self.revoked_reprobes_armed += 1
        # Every waiting requester is told, so nothing holds a callback for a
        # socket that will not exist again this boot.
        self._drop_errands()
        # `source=poll` NAMES THE EMITTER, and the field exists because a
        # revocation legitimately prints MORE THAN ONE `event=revoked` line: this
        # transport reaches its terminal on its own 403, the doorbell reaches its
        # own independently, and `NetworkService` prints the boot-wide stop it
        # adopts from whichever got there first. All three are true facts about
        # different objects, so the fix is to make them distinguishable rather
        # than to suppress two of them -- see `network_runtime._PRINTED_FIELDS`.
        #
        # ONE `revoked` PER SOURCE PER BOOT, STILL, and the slow re-probe is what
        # made that need saying. A refused probe re-enters this method, and a
        # second `revoked` line from the same source is precisely the failure the
        # one-per-source rule exists to catch -- so a re-entry emits its own event
        # instead, which also says something the first line cannot: that the badge
        # is still asking.
        if self._revoked_announced:
            self._emit("revoked_reprobe_refused", reason=reason,
                       error=self.last_error, attempts=self.revoked_reprobes)
            return
        self._revoked_announced = True
        self._emit("revoked", reason=reason, error=self.last_error,
                   source=SOURCE_POLL)

    def is_revoked(self):
        """Queryable stop verdict for a Settings screen. RAM-only, so
        ``False`` again after a reboot."""
        return self.revoked

    def _revoked_reprobe_due(self, now):
        """Has the slow post-403 re-probe come due? Wrap-safe."""

        if self._revoked_reprobe_at is None:
            return False
        return self.clock.diff(now, self._revoked_reprobe_at) >= 0

    def revoked_reprobe_due(self, now=None):
        """The same question, for the SERVICE above this loop (§8.1).

        `NetworkService` latches its own boot-wide stop when it adopts a
        revocation and returns from `poll` above the backend from then on -- so
        this loop would never be pumped again and its own re-probe could never
        fire. The service asks this instead, and lets the frame through when the
        answer is yes. Two objects, one clock.
        """

        now = self.clock.ms() if now is None else now
        return self._revoked_reprobe_due(now)

    def _begin_revoked_reprobe(self, now):
        """Leave the terminal for exactly one attempt.

        The state is cleared rather than overridden, because unlike the doorbell's
        demotion there is no third party to keep informed: a Settings screen reads
        `state`, and a badge that is genuinely trying again should not read
        "stopped". If the attempt is refused, `_enter_revoked` puts it straight
        back and re-arms -- and emits `revoked_reprobe_refused` rather than a
        second `revoked`, so the one-per-source rule still holds.
        """

        self.revoked = False
        self.state = BACKOFF
        self._connect_wanted = True
        self._revoked_reprobe_at = None
        self.revoked_reprobes += 1
        self._next_due = now
        self._emit("revoked_reprobe", attempts=self.revoked_reprobes)

    def _jump_unreachable(self, forgiven=False):
        """One open that never heard the peer buys the 16-32 s band (CX-5).

        **UNLESS A LINK EDGE JUST HAPPENED, in which case the FIRST such open is
        forgiven** (Lane H). A re-association is not instantaneous below the
        radio's own ONLINE: on CYW43 `isconnected()` means an address has been
        assigned, and the DHCP renewal, the ARP for the gateway and the first
        route through a venue AP all settle AFTER that. An open started inside
        that window can burn the whole budget and then work perfectly on the very
        next attempt -- so it produces the same signature as a black hole and
        means the opposite thing.

        WORTH ONE OPEN PER SUCCESSFUL OPEN, which is the honest bound and is NOT
        the same claim as "one open per edge" (Lane I corrected that). The
        settling window is a property of a single attempt; if the next stalled
        open also hears nothing, the badge has evidence about the PEER and the
        jump is right -- **however many radio edges happened in between.** So a
        genuine black hole discovered right after a re-association is escalated
        one attempt later than it used to be, once, and the trade is that a badge
        walking back into range does not wait 16-32 s to poll after a lease that
        took a moment to arrive.

        ⚠ **"ONE PER EDGE" WAS THE DEFECT AND IT SHIPPED FOR A FEW HOURS.** The
        one-shot is armed by `request_reconnect`, which every radio edge and
        (since Lane J) every loop BUILD calls, so
        a flapping AP minted a fresh forgiveness on every recovery and this method
        never jumped at all: ten edges against a black hole measured ten forgiven
        opens and ZERO jumps. The bound is now on CONSECUTIVE forgiveness --
        :data:`FORGIVEN_STALLS_MAX`, reset by a successful open -- so the flap
        case costs exactly one forgiven open and then behaves like a loop that
        never saw an edge.

        A FORGIVEN OPEN IS STILL A FAILED OPEN. `open_failures` rises, the
        session still enters backoff, and it still walks the dense start of the
        ramp; the only thing withheld is the LEVEL JUMP. And it is announced --
        `backoff_forgiven` with the same `level`/`open_ms` fields
        `backoff_jumped` carries -- because a silently-not-taken action is the
        exact defect the CX-5 threshold re-derivation was about.

        The flag is consumed by `_attempt_open` for every outcome, so a refusal
        or a success between the edge and a later black hole cancels it: both
        prove the path answered. Only a SUCCESS clears the consecutive bound,
        though, and the asymmetry is deliberate -- a refusal proves a peer is
        there to refuse, while a stall proves nothing, and it is stalls the bound
        counts.

        THE RAMP IS NOT REPLACED, it is SKIPPED for one CLASS of failure -- and
        since NB-i that is literally a class. A fast failure -- a refusal, a TLS
        reject, a name that does not resolve -- still walks 0.5, 1, 2, 4 s,
        because a blip has to heal in seconds and those attempts are cheap. An
        open that reached its deadline having never heard the peer is neither
        cheap nor informative: it already cost a rendered frame the whole
        :data:`OPEN_BUDGET_MS`, and the next three attempts would cost three more
        to reach a delay this one reaches now.

        **THE SELECTOR IS :class:`LinkStalled`, NOT A COMPARISON.** It was
        `span >= self.unreachable_open_ms` -- one number in two hands, correct
        only while the open owned one whole frame -- and a bar left above the cap
        when the cap came down would have retired this method silently, which is
        the defect Lane G's re-derivation caught. A type cannot drift out of
        range, and it survives an open that parks across frames.

        Never lowers the level, so an escalation already past this point keeps
        climbing to the ceiling, and clamped to ``backoff_max_level`` so a caller
        with a small ceiling cannot be pushed past it.
        """
        target = min(self.unreachable_backoff_level, self.backoff_max_level)
        if forgiven and self._forgiven_stalls < FORGIVEN_STALLS_MAX:
            # ABOVE the "already past this level" check on purpose: a link edge
            # resets the level to 0, so that check could never have fired here,
            # and putting the forgiveness first is what makes the emitted line
            # unconditional. The counter and the line are the whole observable.
            #
            # AND BOUNDED BY THE CONSECUTIVE RUN, not by the arming (Lane I): the
            # `and` is the whole fix. A flap re-arms the one-shot on every
            # recovery, so an arming test alone forgave a black hole forever --
            # see :data:`FORGIVEN_STALLS_MAX`. When the bound is spent the branch
            # falls through and this open takes the ordinary jump, which is
            # exactly the no-edge behaviour and is announced as `backoff_jumped`
            # rather than as anything new.
            self._forgiven_stalls += 1
            self.unreachable_forgiven += 1
            self._emit("backoff_forgiven", level=self._backoff_level,
                       open_ms=self.open_ms)
            return False
        if self._backoff_level >= target:
            return False
        self._backoff_level = target
        self.unreachable_jumps += 1
        self._emit("backoff_jumped", level=target, open_ms=self.open_ms)
        return True

    def _enter_backoff(self, now, reason):
        self.state = BACKOFF
        delay = self._backoff_delay_ms()
        self._backoff_level = min(self._backoff_level + 1, self.backoff_max_level)
        self.last_backoff_ms = delay
        self._schedule_next(now, delay)
        self._emit("backoff", reason=reason, delay_ms=delay, level=self._backoff_level)

    def _backoff_delay_ms(self):
        # Sustained failure ESCALATES to the slow ceiling and stays there; it
        # never becomes "give up", so the badge recovers by itself whenever the
        # server comes back (see BACKOFF_MAX_MS).
        span = self.backoff_base_ms * (
            1 << min(self._backoff_level, self.backoff_max_level)
        )
        span = min(span, self.backoff_max_ms)
        # Full-jitter over [span/2, span): half fixed floor, half random.
        half = span // 2
        return int(half + self._rand01() * half)

    def _safe_close(self, reason="closed"):
        self._inflight = None
        generation = getattr(self, "_active_open_generation", None)
        if self._parked_open_enabled and generation is not None:
            # Invalidate locally before cleanup so a callback made ready by
            # reset cannot publish through this loop even if close pumps it.
            self._active_open_generation = None
            abort = getattr(self.link, "abort_open", None)
            if callable(abort):
                try:
                    abort(generation, reason)
                except BaseException:
                    pass
                return
        try:
            self.link.close()
        except Exception:
            # Teardown must never raise into the frame loop.
            pass

    def _emit(self, event, **fields):
        if self._event_sink is None:
            return
        record = {"transport": "badgelink_poll", "event": event, "state": self.state}
        record.update(fields)
        self._event_sink(record)

    def snapshot(self):
        return {
            "state": self.state,
            "active": self.active,
            "revoked": self.revoked,
            "revoked_reason": self.revoked_reason,
            #: HOW MANY TIMES THE FLOOR HAS ASKED AGAIN SINCE A 403 (§8.1). A
            #: climbing count with `revoked` still True is a badge that is being
            #: refused rather than one that gave up, and those two states read
            #: identically without it.
            "revoked_reprobes": self.revoked_reprobes,
            "desired_version": self.desired_version,
            "inflight": self._inflight,
            "acks_dropped": self.acks_dropped,
            "pending_errands": len(self._errands),
            "backoff_level": self._backoff_level,
            "backoff_max_level": self.backoff_max_level,
            "last_backoff_ms": self.last_backoff_ms,
            "consecutive_misses": self._consecutive_misses,
            "need_full_resync": self._need_full_resync,
            "opens": self.opens,
            "open_failures": self.open_failures,
            "open_attempts": self.open_attempts,
            "open_steps": self.open_steps,
            "unreachable_jumps": self.unreachable_jumps,
            "unreachable_forgiven": self.unreachable_forgiven,
            "polls": self.polls,
            "poll_failures": self.poll_failures,
            "reconnects": self.reconnects,
            "commands_in": self.commands_in,
            "acks_sent": self.acks_sent,
            "policy": dict(self.policy),
            "suggested_cadence_ms": self.suggested_cadence_ms,
            "doorbells": self.doorbells,
            "doorbells_ignored": self.doorbells_ignored,
            "last_error": self.last_error,
            # The poll-cost surface, so a probe reads the same numbers a serial
            # reader sees. `cadence_forced` is here so an operator (and a later
            # investigator reading a probe dump) can tell a measured badge from
            # a normal one -- a forced 3 s cadence changes what every other
            # number in this snapshot means.
            "cadence_forced": self.cadence_forced_active,
            "open_ms": self.open_ms,
            "open_peak_ms": self.open_peak_ms,
            "exchange_busy_ms": self.exchange_busy_ms,
            "exchange_worst_busy_ms": self.exchange_worst_busy_ms,
            "link_peak_ms": self.link_peak_ms,
            "exchanges": self.exchanges,
        }


def _clamp(value, low, high):
    return max(low, min(high, value))


def _error_text(exc):
    return "{}: {}".format(exc.__class__.__name__, exc)


class PollTransport:
    """Supervisor ``TaskSlot`` adapter around :class:`PollLoop`.

    Implements the same seam as ``supervisor.transport.DisabledTransport``
    (``poll(engine, now)``, ``restart()``, ``request_reconnect(engine)``,
    ``state``) so it drops straight into ``SupervisorRuntime``'s ``network`` slot.
    It wires received commands into ``engine.enqueue`` and loop events into
    ``engine.emit``; it holds no credential and no clock of its own.
    """

    def __init__(self, link, clock=None, rand01=None, **loop_kwargs):
        self._engine = None
        self.loop = PollLoop(
            link,
            clock=clock,
            rand01=rand01,
            command_sink=self._on_command,
            event_sink=self._on_event,
            **loop_kwargs
        )

    @property
    def state(self):
        return self.loop.state

    def is_revoked(self):
        """``True`` once a 403 stopped this session (Settings screen surface)."""
        return self.loop.is_revoked()

    def snapshot(self):
        """The loop's credential-free snapshot, for a status/Settings screen."""
        return self.loop.snapshot()

    def start(self, now=None):
        return self.loop.start(now)

    def set_active(self, active):
        return self.loop.set_active(active)

    def queue_ack(self, ack):
        return self.loop.queue_ack(ack)

    def queue_errand(self, kind, payload, sink=None, key=None):
        """Forward one side request. See :meth:`PollLoop.queue_errand`."""
        return self.loop.queue_errand(kind, payload, sink, key)

    def pull_forward(self, now=None, reason="doorbell", delay_ms=0):
        """Forward the P6 doorbell to the loop. See :meth:`PollLoop.pull_forward`."""
        return self.loop.pull_forward(now, reason, delay_ms)

    def force_active_cadence(self, on=True):
        """Forward the TEST KNOB. See :meth:`PollLoop.force_active_cadence`."""
        return self.loop.force_active_cadence(on)

    def poll(self, engine, now):
        self._engine = engine
        self.loop.poll(now)

    def restart(self):
        self.loop.restart()

    def request_reconnect(self, engine):
        self._engine = engine
        self.loop.request_reconnect()
        return {"transport": "badgelink_poll", "state": self.loop.state}

    def _on_command(self, command):
        if self._engine is None:
            return
        self._engine.enqueue(command, source="badgelink")

    def _on_event(self, record):
        if self._engine is None:
            return
        self._engine.emit(
            "badgelink_transport",
            phase=record.get("event"),
            transport_state=record.get("state"),
        )
