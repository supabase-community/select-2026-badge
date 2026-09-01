"""Fail-soft boot pump behind Settings' user-controlled network switch.

``install()`` is called from ``/system/main.py`` after ``/system/lib`` is on
``sys.path``.  It parks one service on ``builtins`` and wraps Badgeware's
``run(update, ...)`` seam, so the service receives one cooperative step per
frame under the stock menu and unmodified apps.  HOME still resets the MCU;
the durable queue and preference make the next boot reconnect and catch up.

No connection starts unless the local preference is ON.  Switching OFF closes
the keep-alive socket, powers down station Wi-Fi and leaves pairing untouched.
Every exception is contained as an offline/backoff state: networking may
degrade, but it may not take down an otherwise useful badge.

THE P6 DOORBELL IS OPTIONAL HERE.  With no ``push_factory`` this is exactly the
polling baseline Card PW shipped.  With one, the same per-frame step also gives
``pushlink.PushService`` one turn, and three properties are load-bearing:

* an ordinary frame can never open a WebSocket.  ``_service_push`` passes
  ``tolerant=False`` unless a caller has declared a tolerant moment, so the
  735 ms handshake cannot land in a frame nobody chose to spend.
* a doorbell fault can never fail a poll cycle, and a poll fault can never stop
  a live socket being serviced: the push step sits OUTSIDE the polling
  try/except and contains itself.
* **the intro does not strand heartbeats at this seam, and that is a property of
  the seam rather than a promise.**  ``managed_run`` wraps EVERY ``run(...)``,
  including a supervisor intro's ``run(intro_update, duration=)``, so the pump
  keeps stepping through an intro and layer 2's timers keep running.  What the
  intro must not do is open a socket, which is why it is not a tolerant moment;
  ``quiesce()``/``resume()`` exist for a gate that stops calling us altogether,
  and layer 3's starvation ceiling catches the case where one did.
"""

import builtins
import gc
import time

import command_ledger
import network_preference


OFF = "stopped"
CONNECTING = "connecting"
DISCONNECTED = "disconnected"
BACKOFF = "backoff"
REVOKED = "revoked"
# `polltransport.CONNECTED`, spelled here for the same reason every other
# mirrored literal in this module is, and PINNED by
# `badgelink/tests/test_network_runtime.py`. Two of Card FT-B's pumps ask "is
# there a socket right now" and the answer was a bare string in both.
CONNECTED = "connected"

# RETIRED SCHEMA-1 PROJECTION CONSTANTS. Production `poll()` no longer reads any
# of them or calls `_pump_schedule_sync`: Schedule v2 makes one conditional
# whole-snapshot request from the app-open seam. They remain temporarily because
# the pre-v2 device/frame probes import these exact names to interpret historical
# receipts; removing that 20-file probe surface is separate from re-enabling it.
# `test_schedule_v2_refresh` AST-pins the production call graph against drift.
#
# HOW OFTEN THE BADGE ASKED WHETHER THE SCHEDULE MOVED. Fifteen minutes, and the
# number is priced the same way POLICY_REFRESH_MS is: 800 badges reading one
# small version string every 15 minutes is ~0.9 requests/second against the ~27
# the 30 s idle poll already costs, so it is a ~3% surcharge on the transport. A
# schedule is edited a handful of times a day by one organizer, and the PRICE,
# STATED PLAINLY: an edit takes up to 15 minutes plus one poll to reach the last
# badge. If that ever matters, a fleet doorbell ring already pulls the poll
# forward -- it just does not pull this check forward, because a schedule is not
# a moment.
SCHEDULE_REFRESH_MS = 900000

# WHERE IN ITS OWN INTERVAL A BOOT'S FIRST SCHEDULE-VERSION CHECK LANDS (CX-8).
# `_schedule_due` used to start `None` and `_pump_schedule_sync` read `None` as
# "due now", so a 15-minute cadence was served at t=0 on EVERY boot -- and every
# app exit on this platform is a `machine.reset()`, so ten app switches in ten
# minutes cost ten 15-minute requests. Measured: 1 poll + 2 extra requests inside
# the first 3,024 ms of every boot (`badgelink/tests/test_cx8_boot_cadence.py`),
# which for a correlated 800-badge reset is ~1,600 requests behind the
# association burst.
#
# THE FLOOR IS DETERMINISTIC AND THAT IS THE POINT. A pure jitter over the whole
# interval leaves 1 badge in 300 still paying the boot burst, which is a worse fix
# than a fix; one minute is comfortably past the boot pile-up and the Wi-Fi
# settle, and 800 badges spread over the remaining 14 minutes are ~1 request a
# second. THE PRICE, STATED PLAINLY: a badge that already holds the current
# schedule learns about an edit up to 15 minutes and one minute later than it used
# to, which is inside the 15-minute promise the interval already made.
SCHEDULE_FIRST_MIN_MS = 60000

# THE COLD CASE, AND IT IS THE OPPOSITE REQUEST. A badge holding NO schedule at
# all has nothing to show a wearer who opens the schedule view, so it may not wait
# fourteen minutes; it wants one promptly and the fleet still may not ask in the
# same second. So the cold first check is a DETERMINISTIC per-badge stagger across
# one minute (`NetworkService._badge_stagger_ms`), not a jitter: the same badge
# lands in the same slot on every boot, so a hall of 800 badges rebooting together
# reproduces the same even spread instead of re-rolling into a fresh clump.
SCHEDULE_COLD_STAGGER_MS = 60000

# HOW OFTEN THE BADGE RE-READS THE FLEET'S SETTINGS, and its boot-phase floor.
#
# THIS SERVICE NOW OWNS BOTH THE PHASE AND THE INTERVAL, which is the rebuild's
# one real simplification here rather than a move. Until 2026-08-29 the steering
# read was a `polltransport` request KIND with its own due time, and this object
# armed the PHASE (`arm_policy`) while the loop owned the INTERVAL -- two objects
# holding one cadence, which is exactly the disagreement CX-8 was opened for and
# then had to be corrected for a second time on 2026-08-23. The settings read is
# an ordinary errand now, so there is one due time, in one object, advanced in one
# place (`_pump_fleet_settings`), and `_mirror_policy_due` is gone with the split
# it existed to paper over.
#
# THE INTERVAL IS THE HERD, NOT A LATENCY PREFERENCE: ~1,000 badges reading one row
# every five minutes is ~3.3 requests a second, and the operator's lever is worth
# at most five minutes of lag. The FLOOR is CX-8's fix and it is not a
# jitter alone: every app exit on this platform is a `machine.reset()`, so "the
# first fire" is what a wearer switching apps pays over and over, and a pure
# jitter over five minutes still leaves one badge in a hundred firing inside the
# boot burst. Spelled here rather than imported for the same reason `CONNECTED`
# is: this module installs to `/system/lib` and runs from `/system/main.py` before
# any app, so a module-scope import of a sibling a half-refreshed lib might not
# carry would take the boot down.
SETTINGS_REFRESH_MS = 300000
SETTINGS_FIRST_MIN_MS = 60000

# HOW OFTEN THE BADGE SAYS IT IS ALIVE (`POST /rest/v1/badges`), with the same
# two-part shape and for the same two reasons.
#
# SIXTY SECONDS IS THE OPERATOR'S QUESTION, NOT THE BADGE'S. "Which badges are on
# the floor right now?" is answered by `badges.last_seen_at`, and an answer that
# is up to a minute stale is one nobody at the venue can tell from live. Faster
# buys nothing and costs the herd: ~1,000 badges is ~16.7 requests a second at
# this interval and twice that at thirty seconds.
#
# THE FLOOR IS SHORTER THAN THE SETTINGS ONE, DELIBERATELY. The heartbeat is also
# the SELF-REGISTRATION -- a badge the server has never seen has no row until this
# request lands -- so a badge that boots must appear promptly or an operator
# watching a provisioning run cannot tell "not registered yet" from "broken". Ten
# seconds is long enough for the socket to be up on a normal boot and short enough
# that a human waiting on the console does not start debugging.
HEARTBEAT_MS = 60000
HEARTBEAT_FIRST_MIN_MS = 10000

# WHAT A REFUSED ERRAND WAITS BEFORE ASKING AGAIN. A full errand queue
# (`polltransport.MAX_ERRANDS`) is a REFUSAL, not a rejection -- the request was
# never made -- so the pump must try again; but re-offering on the very next
# rendered frame would spin a bounded queue at frame rate for as long as the score
# drain is busy. Five seconds is short against both cadences above and long
# against a frame.
ERRAND_RETRY_MS = 5000

# HOW LONG ONE SCORE POST MAY HOLD THE DRAIN'S LATCH WITH NO ANSWER.
#
# THE BACKSTOP, NOT THE FIX. `NetworkService._release_score_latch` takes the
# latch back the moment the transport is not CONNECTED, which is the mechanism
# that actually failed in the field; this bounds the case nobody has thought of
# -- a response lost while the socket never once reports anything but connected.
# Belt and braces, and the braces are the socket.
#
# SIXTY SECONDS IS TWO ORDERS OF MAGNITUDE OUTSIDE AN HONEST ROUND TRIP on this
# lane and there is no tuning in it. An errand is attempted ONCE
# (`polltransport`'s errand channel), a connect is bounded by `OPEN_BUDGET_MS`
# (5,000), and the deepest an errand can be queued is `MAX_ERRANDS` (4) at
# `ERRAND_MIN_GAP_MS` (1,000) apart -- so a post that is still unanswered after a
# minute is not slow, it is gone. Firing early costs one duplicate REQUEST that
# the row's natural key `(badge_id, game, play_number, score)` absorbs server-side
# with `on conflict do nothing`, and no duplicate row at all; firing late costs
# the wearer their score for the rest of the boot, which is the bug this exists
# for. It is also
# the heartbeat's own interval, so an operator watching serial sees at most one
# of these between two beats.
SCORE_INFLIGHT_MAX_MS = 60000

# HOW LONG ONE SCHEDULE REQUEST MAY HOLD ITS LATCH WITH NO ANSWER.
#
# THE SAME DEFECT AND THE SAME BACKSTOP AS `SCORE_INFLIGHT_MAX_MS`, one lane
# over. `_schedule_v2_inflight` and `_schedule_inflight` were both set before
# their errand was handed over and cleared in exactly two places -- the queue
# refusing it, and the response sink -- so one response that never came back
# stopped that consumer for the rest of the boot. The socket check in
# `_release_schedule_latch` is the mechanism that matters; this bounds the case
# nobody has thought of, a response lost while the transport never once reports
# anything other than CONNECTED.
#
# THE NUMBER IS THE SCORE LANE'S, DELIBERATELY, and it is a SEPARATE NAME rather
# than a reuse so the two can move apart if a measurement ever asks them to.
# Both ride one errand channel with one set of bounds -- `OPEN_BUDGET_MS`
# (5,000), `MAX_ERRANDS` (4) at `ERRAND_MIN_GAP_MS` (1,000) apart -- so the
# argument for sixty seconds is word for word the one above it, and a schedule
# GET that is still unanswered after a minute is gone rather than slow.
#
# FIRING EARLY COSTS ONE REPEATED READ AND NOTHING ELSE, which is what makes the
# blunt release safe here too: every request on this lane is a GET
# (`RPC_SCHEDULE_CURRENT_V2`, `RPC_SCHEDULE_VERSION`, the paged
# `schedule_events` read), so asking twice writes nothing anywhere and the
# second answer simply replaces the first. Firing late costs the wearer the
# agenda they opened the app to read.
SCHEDULE_INFLIGHT_MAX_MS = 60000

# -- the broadcast lane's four bounds ----------------------------------------
#
# HOW MANY VALIDATED ACTIONS MAY WAIT FOR A FRAME. FOUR, and the number is the
# WS drain rather than a guess: `pushlink.FLEET_DRAIN_MAX` services four frames
# per rendered frame, so four is exactly the most one frame can hand over, and a
# fifth arriving in the same frame is a publisher doing something this design
# did not anticipate. Overflow drops the NEWEST and counts it, which is the
# opposite of the usual choice and is deliberate: the ones already queued are
# older, so they are closer to the moment they describe, and a light show that
# arrives late is worse than one that never arrives.
BROADCAST_ACTION_MAX = 4

# W18 keeps app switching as INTERNAL plumbing for one wearer-visible verb.
# Naming the target here keeps the protocol payload from becoming an app slug
# again: every valid ``show_notice`` opens Nametag and nothing else.
NOTICE_APP_SLUG = "nametag"

# HOW MANY ACTION IDS THE EXACTLY-ONCE GUARD REMEMBERS. Eight, i.e. two full
# drains, and it is a LIST rather than a set because MicroPython's set costs more
# than a linear scan of eight strings and because the eviction order has to be
# insertion order. The window only has to outlive DUPLICATE ARRIVAL of one
# publish -- measured in frames, not minutes -- so eight is generous. It is not a
# replay defence and cannot be one: a badge that reboots mid-event has an empty
# list, and re-playing one show after a reset is the same residual `_on_command`
# documented and accepted.
ACTION_MEMORY = 8

# HOW MANY RECEIPTS MAY WAIT OUT THEIR JITTER AT ONCE. Four, matching the action
# queue, because a receipt exists per applied action and the errand channel's own
# `MAX_ERRANDS` is four -- a deeper queue here would only push the refusal one
# layer down. Overflow drops the newest and counts it. THAT IS ALLOWED TO HAPPEN:
# a dropped receipt is a missing row in an audit table, not a missing show.
RECEIPT_MAX_PENDING = 4

# THE RECEIPT STAMPEDE WINDOW. One broadcast reaches ~1,000 badges inside one
# fan-out window and every one of them wants to POST a row about it; unspread,
# that is the entire fleet writing in the same second, which is the same herd
# arithmetic the ring jitter was drawn for. Five seconds costs ordinary shows
# nothing. Sleep and radio-off deliberately wait for their own attempt before
# destroying the channel, so this jitter is also their bounded observability
# delay; see :data:`POWER_ACTION_RECEIPT_MS`.
#
# THE DRAW ITSELF IS `pushlink.ring_delay_ms`'s, made per ring and passed in.
# Re-drawing it here would be a second opinion about one number, which is CX-8's
# lesson exactly; this constant is the CLAMP the service falls back to when the
# link hands over a delay it cannot use.
RECEIPT_JITTER_MAX_MS = 5000

# HOW MANY FRAMES A DUE RECEIPT MAY SPEND TRYING TO GET INTO THE ERRAND QUEUE,
# and the re-arm between them. The errand channel holds four slots
# (`polltransport.MAX_ERRANDS`) and the heartbeat, the settings read and the
# score drain all want them, so a full queue right after a fleet show is
# foreseeable rather than exotic -- but the retry is bounded HARD, because an
# unbounded one is the fleet-wide write storm again with extra steps. Three
# tries a second apart, then the row is dropped and counted.
RECEIPT_QUEUE_TRIES = 3
RECEIPT_RETRY_MS = 1000

#: THE LONGEST A BROADCAST POWER ACTION WAITS FOR ITS RECEIPT ATTEMPT.
#:
#: This is NOT an acknowledgement and expiry does NOT cancel the action. The
#: receipt is the console's only proof that a badge accepted/armed sleep or
#: radio-off, but either action destroys the channel that must post it. Waiting
#: for the attempt's terminal callback makes a healthy receipt land first; 30 s
#: covers the 5 s fleet jitter, four one-second-spaced errand slots and a bounded
#: failed exchange. A dead link still acts at expiry, because an audit outage may
#: cost observability but may not veto an accepted one-shot fleet instruction.
POWER_ACTION_RECEIPT_MS = 30000

# THE TWO WORDS A RECEIPT'S `result` MAY CARRY, and they are a CROSS-LANE
# CONTRACT rather than a local choice. `badgelink/web/src/lib/fleet-broadcast.ts`
# reads this column as badge-authored text and treats it as an acknowledgement
# unless it is one of the refusal words it knows -- "failed", "error",
# "refused", "unsupported" -- so RECEIPT_FAILED must stay inside that set or a
# badge reporting a refusal is counted by the console as a success. RECEIPT_OK
# is deliberately NOT in that set and is shown verbatim.
#
# A STRING AND NOT THE APPLIER'S RESULT DICT. The applier answers a rich object
# (`{"effect": "play_effect", "kind": ..., "id": ...}`) and it is tempting to
# post it, but the console's column is text and every reader of it -- the
# responder table, the failure tally, the sort -- is written against a word. One
# word per badge per action is also the right size for a table an operator scans
# during a show.
RECEIPT_OK = "applied"
RECEIPT_FAILED = "failed"

# HOW MANY FETCHED SCHEDULE ROWS ONE FRAME NORMALISES, and this number exists
# because Card FT-B's F21 gate failed on it. The sink used to sanitize a WHOLE
# page (`schedule_store.PAGE_ROWS`, sixteen rows) and, on the last page, write
# the cache too -- so one frame carried a JSON decode, sixteen per-character
# normalisations, a whole-record encode and an atomic flash swap.
# `badgelink/host/ft_b_frame_cost.mjs` measured that frame at 82 expensive units
# and 61,136 allocated bytes against a full four-track conference day, in a run
# whose every other frame did none.
#
# FOUR, and the bound is the frame rather than the schedule: at HIRES a 30-second
# gate window holds only ~1,114 frames, so the eleven worst frames ARE the p99
# and a rare frame is not an affordable frame. Four rows is ~1.4 KB of title and
# location text, and a 64-row day therefore spreads over sixteen parse frames
# plus four page requests -- about half a second of wall time on a sync that
# happens when an organizer edits the schedule, against a frame nobody can miss.
SCHEDULE_PARSE_ROWS = 4

# CARD NB'S ONLY STRATEGY SWITCH, AND **ON IS THE SHIPPING CONFIGURATION** --
# OWNER RULING 2026-08-28, on device readings, reversing the OFF default this
# constant carried until then. `scripts/build_mpy.py --nb-connect off` rewrites
# this ONE literal in a staged build input to produce the other artifact; source
# is never edited and no preference, command, file or runtime setter can reach
# it. The service snapshots the value when it is constructed; child constructors
# receive that snapshot rather than rereading this module.
#
# WHAT THE RULING BOUGHT, and it is a frame, not a millisecond count. OFF drives
# the poll open through `device_link._run_blocking`, which owns one RENDERED
# frame for up to `polltransport.OPEN_BUDGET_MS` = 5,000 -- and out of range it
# spends the whole ceiling. Measured twice by two independent methods on the
# reference badge: **5,163 ms** worst frame walking to the edge of the Wi-Fi,
# **5,166 ms** with the badge inside a microwave oven used as a Faraday cage.
# They agree to 3 ms and both are the constant plus ~165 ms of frame, so the roam
# freeze IS that ceiling, spent whole, in one frame. ON selects
# `device_link.open_step`, which advances an open a bounded amount and RETURNS
# THE FRAME: the same rig measured **126 ms** out of range and **526 ms**
# reconnecting, and games are stutter-free. Full record, including what was ruled
# out so nobody re-runs it:
# `docs/handoff/networking-endstate-2026-08-26/NB-CONNECT-DECISION.md`.
#
# ⚠ **ON DOES NOT MAKE DNS NON-BLOCKING, AND THE OBVIOUS READING OF THAT IS A
# TRAP.** Said here because this constant is where a reader meets the flag, and
# the flag's name invites exactly the wrong inference. It is now the SHIPPING
# flag, so the wrong inference is more expensive than it used to be.
#
# What ON does is remove the doorbell's NEED to resolve, by reusing an address the
# BOOT already resolved. It does not make `getaddrinfo` interruptible -- nothing
# can, and these numbers are why avoidance is the only lever there will ever be.
# Measured on device: with no route, `getaddrinfo` blocks **13.1-14.0 s** across
# four runs and **cannot be bounded** (no socket timeout on this port, and no
# Python wrapper reaches the C call). With a route, even an NXDOMAIN answers in
# 30 ms. For contrast the association FAILURE path is exonerated: `wlan.connect`
# against an absent SSID returns in **11 ms**. Read them as the STANDING REASON
# the doorbell must keep reusing the boot's answer rather than as an argument
# about which artifact ships -- OFF pays the same unbounded resolve, it just pays
# it somewhere a wearer is even less able to explain.
#
# ⚰ THE STALE-ADDRESS OBJECTION IS RETIRED, and it is recorded rather than
# deleted because it stood here for four days and a reader will reconstruct it.
# It argued that ON is worse at a NEW VENUE, because a reused boot address is a
# possibly-STALE address and a wrong IP is not a fast failure but a connect that
# goes nowhere plus a 15-30 minute `DEMOTE_CAUSE_UNREACHABLE` re-arm. Two facts
# in this file kill it:
#
#   * `SessionAddresses` IS INVALIDATED ON THE `wifi_lost` EDGE
#     (`_addresses.invalidate("wifi_lost")`, CX-3). Reaching a different venue
#     requires a new association, and a new association requires losing the old
#     one, so the cache is ALWAYS cleared before a different venue's first
#     resolve. The premise -- a boot address surviving into a venue that did not
#     issue it -- cannot occur.
#   * The poll link's own `_addr_info` is created once per boot and reused across
#     reconnects, which is UNCHANGED BEHAVIOUR present on OFF too (see
#     `SessionAddresses`' docstring). Whatever residual staleness it carries is
#     not a cost of ON and flipping this constant does not change it.
NB_CONNECT_ENABLED = True

# HOW MANY DOORBELL PUMPS SHARE ONE SERIAL LINE. The push pump is the only thing
# this module times on EVERY frame -- `_service_push` gives asyncio one
# `run_until_complete` per frame whether or not anything is ready -- so a line
# per frame would be 37 lines a second and the measurement would cost more than
# the thing measured. 128, and the number is the poll cadence rather than a round
# figure: at the device's measured 27 ms mean frame that is ~3.5 s, so one push
# roll-up lands per ACTIVE poll and a reader can see the two rhythms against each
# other in one serial log. The peak inside the window is kept, so a single
# expensive pump is never averaged away.
PUSH_PUMP_ROLLUP = 128

# HOW MANY TIMES A BOOT RE-TRIES A LEDGER WRITE THAT FAILED, and why it gives up
# (CX-7). The durable ledger closes one window: an effect landed, then a reset
# happened before its ack. A full or read-only LittleFS cannot be argued with, so
# the write is contained rather than raised -- but the window it protects is real,
# so the badge tries again from a chore-budgeted frame instead of forgetting.
#
# FOUR TRIES, jittered nowhere and doubling from LEDGER_PERSIST_BASE_MS: 5, 10, 20
# and 40 seconds, which spans the ~75 s a wearer plausibly spends in one app.
# Then it stops, SILENTLY, because a badge whose flash is full will fail all four
# and a retry ladder that never ends is a flash write every 40 s for the life of a
# boot. `ledger_save_failures` in the snapshot is what tells the story afterwards.
#
# EACH RUNG IS MEASURED FROM THE FAILED WRITE, not from the top of the frame the
# write failed in. That distinction is worth a line here because it was wrong on
# the device until 2026-08-24 and the symptom looked like a broken ladder rather
# than a broken edge: see `_note_ledger_unsaved`.
LEDGER_PERSIST_TRIES = 4
LEDGER_PERSIST_BASE_MS = 5000
_SERVICE = None

# One trust path for both PostgREST and Realtime. DeviceBackend feeds these
# roots through the frozen fetch shim; ``device_push_factory`` below feeds the
# same ordered pair into one WebSocket SSLContext per push service.
# WE1 IS FIRST, AND ITS POSITION IS THE WHOLE POINT. The live chain is
# leaf -> WE1 -> GTS R4 and EVERY link is ECDSA, which this chip verifies about
# 1.8x slower than RSA (measured: 372-393 ms vs 201-226 ms for the same
# handshake). Trusting the INTERMEDIATE directly removes one ECDSA signature
# verification from every connection.
#
# MEASURED ON THE DEV BADGE, 2026-08-27, verified against the real project host:
#   both roots only ........ 821-846 ms
#   WE1 pinned ............. 530-581 ms
#   WE1 + both roots ....... 540-582 ms   <- this configuration
# so the roots cost NOTHING to keep and mbedTLS takes the short path when WE1
# matches. THEY STAY DELIBERATELY: an intermediate rotates far more often than a
# root, and if Supabase reissues under a different one the roots still verify --
# just at the old speed. Shipping WE1 INSTEAD OF the roots would trade ~270 ms
# for a fleet-wide outage the day the intermediate changes.
#
# WE1 notAfter 2029-02-20; the chain's R4 notAfter 2028-01-28. Both clear the
# 2026-10-02 event with years to spare.
DEVICE_CA_PATHS = (
    "/system/lib/ca/gts-we1.der",
    "/system/lib/ca/gts-root-r4.der",
    "/system/lib/ca/gts-root-r1.der",
)
REALTIME_SOCKET_PATH = "/realtime/v1/websocket"

# THE IN-FRAME OPEN BUDGET, IN WHOLE SECONDS, WHICH IS THE UNIT THE FROZEN
# FIRMWARE TAKES. `fetch.AsyncFetch(timeout=)` is an integer-second argument and
# nothing in this repository has verified that it accepts a float, which is also
# why both budgets are whole seconds rather than 3.5 or 8.7.
#
# TWO NUMBERS SINCE LANE J (2026-08-24), and the second one is why they are NAMED
# here rather than spelled inline at the call site: `worker_factory` now chooses
# between them, and a conditional inside a keyword argument is a thing
# `badgelink/tests/test_open_budget.py`'s census cannot read. The census asserts
# both against `polltransport`'s milliseconds and asserts that the call site
# references exactly these two names.
#
# * `OPEN_BUDGET_S` is the owner's ruling #21 (*"10 seconds is too extreme"*).
# * `COLD_OPEN_BUDGET_S` is the FIRST open of a link, because 5 s was measured
#   truncating HEALTHY cold boots -- 5 of 7, with an open at 4,119 ms succeeding
#   beside them. The floor is the 8,746 ms cold open that SUCCEEDED, the ceiling
#   is the ruling, and whole seconds leave exactly one candidate between them.
#
# The derivation for both, the evidence and the costs are in
# `polltransport.OPEN_BUDGET_MS` and `polltransport.COLD_OPEN_BUDGET_MS`. The
# literals are spelled in this module rather than imported for the same reason
# every other cross-module literal here is: a `/system/lib` module importing a
# sibling is a partial-install hazard this repository has been bitten by.
OPEN_BUDGET_S = 5
COLD_OPEN_BUDGET_S = 9

# ``pushlink``'s tolerant-moment names, spelled here rather than imported.  This
# module installs to ``/system/lib`` and runs from ``/system/main.py`` before any
# app, so a module-scope import of a file a half-refreshed ``/system/lib`` might
# not carry would take the boot down.  Push is OPTIONAL at this seam: with no
# ``push_factory`` the polling baseline behaves exactly as Card PW shipped it.
# ``badgelink/tests/test_network_runtime.py`` pins both literals against the real
# ``pushlink`` constants.
MOMENT_SESSION_START = "session_start"
MOMENT_VIEW_TRANSITION = "view_transition"
MOMENT_INTRO_COMPLETE = "intro_complete"
MOMENT_RECONNECT_DUE = "reconnect_due"

# WHICH EMITTER A `revoked` LINE CAME FROM, and this module's own word for it
# (2026-08-24). THREE OBJECTS EMIT `event=revoked` AND ALL THREE ARE CORRECT: the
# poll transport on its own 403 (`polltransport.SOURCE_POLL`), the doorbell on its
# own refused rejoin (`pushlink.SOURCE_PUSH`), and this service when it adopts a
# backend's terminal and stops for the boot. Two transports reach a terminal
# INDEPENDENTLY by design -- neither is allowed to be the reason the other stops
# -- so more than one line per revocation is the intended behaviour, and the 2026
# -08-24 device session showed two of them 20 ms apart in one frame with nothing
# on the line to tell them apart. Hence a field rather than a suppression:
# **exactly one `revoked` per SOURCE, and a repeated source is the failure.**
# Spelled here rather than imported, like `pushlink`'s literals above and for the
# same boot-safety reason; `badgelink/tests/test_revoked_sources.py` pins all
# three distinct and pins that every `revoked` emitter carries one.
SOURCE_SERVICE = "service"

# ``pushlink``'s mode literals, for the pre-session answers this module has to
# give Settings before any push object exists. Pinned by the same seam test.
PUSH_MODE_NETWORK_OFF = "network_off"
PUSH_MODE_POLLING = "polling"
PUSH_MODE_TRYING = "trying"

# -- WHY IT IS NOT CONNECTED, as a closed vocabulary ------------------------
#
# **ONE WORD COVERED AT LEAST EIGHT STATES, AND FOUR OF THEM WERE PERMANENT.**
# `push_mode()` answers `trying` for every one of: no doorbell object was ever
# built, one was built and placement is withholding every moment, an
# establishment is genuinely in flight, a join was refused, the radio is not
# associated, and a demoted badge is waiting out its slow re-arm. A wearer cannot
# act on the difference -- which is why `mode()` deliberately has no new literal
# -- but an OPERATOR reading a serial capture must, and a 2026-08-26 hardware
# session lost most of a morning to exactly that: 449 consecutive seconds of
# silence that could have been any of the eight.
#
# EVERY WORD IS A FIXED LITERAL THIS PACKAGE SPELLS, and that is a hard
# requirement rather than a style: this vocabulary reaches a Settings line, and a
# screen may only draw strings the pre-baked glyph set contains. The server's
# refusal string in particular is NEVER forwarded -- it arrives from a system
# that knows nothing about which glyphs this badge carries, so rendering it is
# tofu. The refusal is read for ONE BIT (is this an authorization refusal?) and
# discarded; the verbatim text stays in the snapshot and on serial, where
# numbers and short enums are all that is printed anyway.
#: No doorbell object exists in this boot. Not a claim about the radio or the
#: server -- nothing has been attempted yet.
CAUSE_NOT_STARTED = "not started"
#: A doorbell exists and OWNER RULING #22 placement is withholding every moment:
#: the badge is inside an app that did not opt in. This is the one that hid the
#: 2026-08-26 root cause, because the launcher idles into `nametag` at 30 s.
CAUSE_PLACEMENT = "in an app"
#: An establishment is in flight right now.
CAUSE_ESTABLISHING = "connecting"
#: The radio is not associated, so there is nothing to establish over.
CAUSE_NO_SIGNAL = "no signal"
#: The server refused the join on authorization grounds.
CAUSE_REFUSED = "refused"
#: A join error that is NOT an authorization refusal -- a rate limit, a shard
#: fault. Layer 2 retries these on its own backoff and they clear themselves.
CAUSE_SERVER_BUSY = "server busy"
#: Demoted, with the slow bounded re-arm armed. The badge WILL try again; saying
#: "connecting" here is what made a recoverable state look permanent.
CAUSE_RETRY_LATER = "retry later"
#: Wanted, allowed, nothing wrong -- between attempts (boot jitter, a reconnect
#: backoff, waiting for a tolerant moment).
CAUSE_WAITING = "waiting"

#: HOW LONG A LATCHED CAUSE STAYS TRUE ENOUGH TO SHOW, in milliseconds.
#:
#: SIXTY MINUTES, a coordinator ruling (REVIEW-LOG r22) that replaced an earlier
#: five. **THE DECIDING ARGUMENT IS THAT THIS FIRMWARE IS FROZEN, so the question
#: is not "which number is right" but "which permanent mistake is cheaper".** Too
#: short reintroduces the exact defect this whole feature was built to close --
#: the panel reporting NOTHING about a state the wearer is asking about -- for
#: every read past the bound. Too long costs one line that is true, marked as
#: past, and contradicts nothing beside it. With no update path, the recoverable
#: error is the only defensible one.
#:
#: WHAT MAKES A LONG WINDOW HONEST is that the stamp is EVENT-ANCHORED. Both
#: branches that fill this latch do so at the moment the question becomes askable
#: -- `_latch_cause_at_switch` at the wearer's press, and the observer branch at
#: the screen-open that grants the placement -- so the age read here is "how long
#: since you did the thing you are now asking about". And on the off branches
#: nothing CAN change the answer while the wearer waits, because the radio or the
#: doorbell is off: this is the last known state of a frozen system, and a frozen
#: system's last known state does not rot.
#:
#: TWO SUPERSEDED JUSTIFICATIONS, recorded because a later reader who checks
#: either will find it false and may "fix" the number on that basis -- and a
#: justification that is wrong for the current design is worse than none:
#:
#: * **"The question decays"** (the original five-minute case). It did not survive
#:   `_latch_cause_at_switch`; see the frozen-system point above.
#: * **"The app lifecycle already bounds it, so the number barely matters."** True
#:   and worth knowing -- every trip home is `machine.reset()`, so this RAM-only
#:   latch cannot outlive one app session at ANY bound, and the timer only ever
#:   adjudicates dwell on a single screen. But it is an argument for indifference,
#:   not for tightness, and under indifference the asymmetry above decides.
#:
#: THE BOUND IS ON THE ANSWER, NOT ON THE COPY BESIDE IT, and that part is
#: independent of the number. An expired latch is ABSENT rather than annotated: the
#: apps lane builds one past-copy map with no age variants, which is what keeps
#: their 308 px width budget, and a display that has to say "this is historical" is
#: one edit away from not saying it.
PUSH_CAUSE_LATCH_MS = 3600000

#: THE CLOSED SET, in the order :meth:`NetworkService.push_cause` tries them.
#: Exported so the Settings lane can build its line against a vocabulary it can
#: enumerate rather than a string it has to trust.
PUSH_CAUSES = (
    CAUSE_NOT_STARTED,
    CAUSE_PLACEMENT,
    CAUSE_ESTABLISHING,
    CAUSE_NO_SIGNAL,
    CAUSE_REFUSED,
    CAUSE_SERVER_BUSY,
    CAUSE_RETRY_LATER,
    CAUSE_WAITING,
)

#: THE NARROWED PUSH SNAPSHOT A PANEL MAY READ, in the order a reader wants it.
#:
#: EVERY KEY HERE IS ALREADY COMPUTED by `pushlink` and was already published
#: into `PushLink.snapshot()` / `PushPolicy.snapshot()`. Nothing in this file
#: counts, derives or stores anything new for it: the whole defect being closed
#: is that these values reached a SERIAL PORT NOTHING WAS ATTACHED TO and never a
#: screen. Three incidents on 2026-08-27, each an hour of guessing, and each one a
#: value that existed the whole time:
#:
#: * `policy_source` -- Settings said "The event turned this off for now"
#:   (`MODE_BLOCKED`) and nobody could tell a venue that really said no from a
#:   badge that had not been told yet. It is `"default"` until a well-formed
#:   `push_enabled` is seen and `"server"`/`"malformed"` after, and the phased
#:   60-240 s first read (`POLICY_FIRST_MIN_MS`) means "not told yet" is the
#:   NORMAL state for the first minutes of every boot -- and every app switch is
#:   a boot. THE SINGLE MOST VALUABLE FIELD IN THIS TUPLE.
#: * `sessions_joined` / `sessions_failed` / `failed_sessions` / `demote_after`
#:   -- `MODE_DEMOTED` reads "The fast connection kept failing" after
#:   `DEMOTE_AFTER_SESSIONS` failures with no way to see how far along that count
#:   a badge is. 2 of 3 and 3 of 3 are the whole difference.
#: * `doorbells` / `doorbells_filtered` / `targeted` -- command latency measured
#:   bimodal (0.40-0.55 s against 1.34-2.38 s over 12 `set_caselights` inserts):
#:   the fast group is a ring, the slow group is the 3 s `ACTIVE_CADENCE_MS`
#:   poll floor underneath it. `event:doorbell` is SHARED, so the ring filter is
#:   fail-safe and rings only on a positive hardware-UID match -- a comparison
#:   that never matches is indistinguishable from a venue that never publishes.
#:   THE TWO COUNTERS ARE DISJOINT, which is what makes the shape readable:
#:   `doorbells` counts only broadcasts that PASSED the filter, so a filter that
#:   never matches is `doorbells_filtered` climbing while `doorbells` stays 0,
#:   and a silent venue is both of them at 0. `PushLink.snapshot`'s own comment
#:   names `targeted` as the first thing to read when zero rows arrive.
#:
#: NARROWED RATHER THAN FORWARDED WHOLE, for two reasons that are not tidiness.
#: The full record carries a nested `client` dict and ~25 keys, and a panel that
#: iterates whatever it is handed will one day iterate a key nobody priced
#: against the 308 px band or against the pre-baked glyph set. And a narrowing
#: spelled HERE is a list a reviewer can read against the incidents above,
#: whereas one spelled in the app is a second place to forget a field.
#:
#: TWO KEYS HERE ARE NOT DRAWN BY THE SETTINGS PANEL TODAY, AND THAT IS NOT AN
#: OVERSIGHT: this is the SEAM, and the panel is one consumer of it with eight
#: bands to spend. Both answer a question the drawn fields cannot, so a probe or
#: a later screen reading this projection gets them without a second edit here.
#: * `doorbells_rung` is the ring that actually pulled a poll forward.
#:   `doorbells` counts the bell being ACCEPTED and `doorbells_rung` only
#:   increments when `poll_loop.pull_forward` agrees, so a gap between them is a
#:   doorbell that reached the badge and changed nothing -- a different failure
#:   from a filter that rejected it.
#: * `remote_disabled` is the venue's answer itself, beside `policy_source`'s
#:   account of where the answer came from. It is NOT recoverable from `mode`:
#:   `mode` resolves in wearer-priority order, so a badge with the radio off
#:   reads `network_off` whether or not the venue has also said no.
#:
#: A key that stops being reachable from any reader, here or in a probe, should
#: be deleted rather than left as decoration.
PUSH_DIAGNOSTIC_KEYS = (
    "mode",
    "joined",
    "socket_open",
    "policy_source",
    "remote_disabled",
    "sessions_joined",
    "sessions_failed",
    "failed_sessions",
    "demote_after",
    "demoted",
    "push_revoked",
    "doorbells",
    "doorbells_rung",
    "doorbells_filtered",
    "targeted",
    "last_error",
)

#: THE SAME NARROWING, ONE LEVEL DOWN: keys lifted out of the LAYER-2 record at
#: `PushLink.snapshot()["client"]`.
#:
#: A SECOND TUPLE RATHER THAN A SECOND RULE INSIDE THE LOOP. `PushLink` merges
#: `PushPolicy.snapshot()` into itself but nests `RealtimeClient.snapshot()`
#: whole under `client`, and that nesting is deliberate and tested -- the full
#: layer-2 record is ~14 keys nobody priced against the 308 px band. So a
#: layer-2 counter a panel needs has to be named HERE, one at a time, and lifted
#: to the top level. Naming them is the review surface: a reader can see exactly
#: which layer-2 fields crossed into the app and why.
#:
#: * `binary_frames_ignored` -- WHICH SIDE OF THE SOCKET THE DOORBELL DIES ON,
#:   and the only counter that can say. On 2026-08-28 a live `0x04`
#:   `UserBroadcast` was captured ON THE WIRE by `realtime_join_probe.py
#:   --listen` (274 bytes, opcode 2, topic `realtime:event:doorbell`, no
#:   `replayed` key -- §H20 of the 2026-08-26 doorbell root-cause handoff), so
#:   trigger -> `realtime.send()` -> WAL -> tenant fan-out -> subscriber is
#:   PROVEN. The host probe runs the SHIPPING `RealtimeClient` and the SHIPPING
#:   join payload; the badge runs the same code and reports zero doorbells. The
#:   one material difference left is the socket underneath -- host stdlib
#:   RFC 6455 against the badge's vendored `aiohttp_ws` -- and this counter
#:   splits it: NON-ZERO means opcode-2 frames REACH the badge and
#:   `phoenix.decode_binary` refuses them (a decoder bug, and the session
#:   survives, because `_handle_binary` counts and SKIPS rather than dropping);
#:   ZERO beside zero doorbells means the vendored WebSocket layer never handed
#:   a binary frame upward at all. `docs/handoff/...
#:   /DOORBELL_ROOTCAUSE_FINDINGS.md` §D4 already listed it among the values
#:   that reach no screen.
PUSH_DIAGNOSTIC_CLIENT_KEYS = (
    "binary_frames_ignored",
)

#: THE WALL-CLOCK FACTS A PANEL MAY READ. Same projection discipline as
#: :data:`PUSH_DIAGNOSTIC_KEYS` -- every value here is one this module ALREADY
#: computes, and the defect being closed is that none of them reached a screen.
#:
#: **THE FAILURE THIS EXISTS FOR IS A FLEET-WIDE BRICK THAT LOOKS LIKE AN IDLE
#: BADGE.** On RP2350 the powman always-on timer is the master clock and it
#: RESETS when power is removed (`clock_boot.resync`'s docstring has the
#: mechanism and `ports/rp2/mphalport.c:186-189` the source), so a badge coming
#: back from hardware shipping mode wakes holding whatever the battery-backed
#: PCF85063A kept -- a value nothing has checked. With no plausible clock,
#: verified TLS cannot validate a certificate date, `clock_boot.resync` RAISES
#: rather than failing soft, and `DeviceBackend._build_loop` never finishes. No
#: loop means no `poll_loop()`, which means `_service_push` never builds a
#: doorbell, which means :meth:`push_diagnostics` answers `None` and the panel
#: reads "No push details on this badge" -- **the same screen a badge that has
#: simply not tried yet draws.** A venue that blocks UDP/123 (common) turns that
#: into every badge in the hall, and the operator holding one has no USB, no
#: serial and no way to tell the two apart.
#:
#: * `plausible` -- does this badge have a clock verified TLS can work from at
#:   all? `NetworkService._epoch()`'s existing `clock_boot.evaluate_ntp` gate,
#:   which is the SAME gate the transport applies before opening a socket, so
#:   the panel and the socket cannot disagree. **This is the brick bit.**
#: * `synced` -- has an NTP sync actually LANDED this boot? Already latched as
#:   `DeviceBackend._clock_verified`, because `clock_boot.resync`'s shift bound
#:   is armed by it. It is the difference between a clock that is merely
#:   plausible (PCF-restored, or hand-set on the Clock screen) and one that has
#:   been checked against a server.
#: * `reason` -- `clock_boot.resync`'s own last word, verbatim. `_build_loop`
#:   already emits it as `clock_resync_skipped(reason=)`, onto serial.
#:
#: NARROWED AND FLAT, for `PUSH_DIAGNOSTIC_KEYS`' reasons: a reviewer can read
#: this list against the failure above, and a panel keeps one shape to read.
CLOCK_DIAGNOSTIC_KEYS = (
    "plausible",
    "synced",
    "reason",
)

#: THE RADIO'S OWN FACTS A PANEL MAY READ, from :meth:`NetworkService.wifi_diagnostics`.
#: Same projection discipline as :data:`CLOCK_DIAGNOSTIC_KEYS`: every value here
#: is one `ResilientWiFi` already computes on every frame, and the defect being
#: closed is that not one of them reached a screen.
#:
#: **THE FAILURE THIS EXISTS FOR IS A BADGE THAT NEVER ASSOCIATES AND SAYS
#: NOTHING AT ALL.** `ResilientWiFi.snapshot()`'s only consumers were two
#: EDGE-GATED serial emitters, so a radio that never reached ONLINE never
#: produced an edge and therefore never printed a line -- while
#: :meth:`NetworkService.state` answered CONNECTING (it does that whenever
#: `_backend is None`) and the panel drew "Connecting to the server" over a
#: radio that had not found an access point. On 2026-10-02 there is no cable and
#: nothing attached to the serial port, so the panel is the only channel there
#: is.
#:
#: * `radio` -- the RAW `off`/`connecting`/`online`/`backoff` literal.
#: * `reason` -- the closed failure vocabulary, RAW and never translated into a
#:   verdict. A negative CYW43 status is a retry signal, not proof of a wrong
#:   password (`benchmark/results/reports/2026-08-13-v3.0.1-network-authenticated.md`
#:   records a spurious `-3` on CORRECT credentials).
#: * `attempts` / `failures` -- how hard it tried. Zero and zero on a badge that
#:   never started is the honest reading, and it is the only thing that
#:   separates "never tried" from "tried forty times".
#: * `online` -- `DeviceBackend._was_online`, the same flag the radio gate reads,
#:   so the sentence on the panel and the connect decision cannot disagree.
#: * `connected_s` -- how long the CURRENT association has held, in seconds.
#: * `region` -- the two-letter regulatory domain the radio was started in.
#:
#: **THERE IS NO SSID KEY AND THAT IS STRUCTURAL.** The owner's instruction
#: names the network name a secret; putting it on ~1,000 screens in a public hall
#: is a product decision, not an engineering one. Omitting the key outright is
#: what makes it unable to reach a view at all, rather than a rule a future
#: caller could forget.
WIFI_DIAGNOSTIC_KEYS = (
    "radio",
    "reason",
    "attempts",
    "failures",
    "online",
    "connected_s",
    "region",
)

#: THE PATH TO THE SERVER, from :meth:`NetworkService.link_diagnostics`. Same
#: discipline again, and the same defect: `DeviceLink.open_phases` has split
#: every connect into dns / connect+TLS / handshake / headers / body WITH AN
#: OUTCOME WORD since Lane J, `BoundedResolver` has counted its queries and
#: known the DHCP resolver's address all along, and `PollLoop` has counted its
#: opens -- and no view read any of it.
#:
#: * `transport` -- the RAW `polltransport` literal, before the fold that turns
#:   both `disconnected` and `backoff` into one "Can't reach the server" line.
#: * `opens` / `open_failures` -- the loop's own counters.
#: * `outcome` -- `opened`, or the exception class name the open ended in.
#: * `dns_ms` / `connect_ms` -- **the split that separates "DNS is dead" from
#:   "TLS is dead" numerically**, which is the question nothing on the badge
#:   could answer.
#: * `stall_ms` -- how long the last open went without hearing the peer.
#: * `resolver` -- the address `bounded_dns` would ask, or `None`, which is the
#:   documented grey zone: DHCP offered no option 6 and the gateway is unusable.
#: * `lookups` / `lookup_failures` -- the resolver's counters.
#: * `service_error` and `link_error` -- **TWO KEYS AND NEVER MERGED.** The first
#:   is :attr:`NetworkService.last_error`, which holds the `CredentialError`
#:   sentence a malformed BadgeLink value raises inside the factory containment
#:   handler and which is read by no view today; the second is
#:   `PollLoop.last_error`. They are different repairs by different people.
LINK_DIAGNOSTIC_KEYS = (
    "transport",
    "opens",
    "open_failures",
    "outcome",
    "dns_ms",
    "connect_ms",
    "stall_ms",
    "resolver",
    "lookups",
    "lookup_failures",
    "service_error",
    "link_error",
)

#: WHO THIS BADGE IS, from :meth:`NetworkService.identity`. Every one of these is
#: posted to the server on every heartbeat and NONE of them can be read off the
#: badge in the hand -- which is the wrong way round for the one day when the
#: server is what nobody can reach.
#:
#: * `uid` -- :func:`hardware_uid`, the PHYSICAL badge id. Not the JWT `sub`: on
#:   the shared-token fleet every badge ships a byte-identical `/secrets.py`, so
#:   `sub` is the same value on all ~1,000 and names the fleet rather than a badge.
#: * `token` -- :func:`credential_tier`, which answers the S0.8 rollout question
#:   ("has this badge been re-provisioned yet?") that nothing on the wire could.
#: * `boot` -- the first 8 hex of `_boot_session()`: two rows sharing it came
#:   from one uninterrupted run.
#: * `build` -- `os.uname().version`.
#: * `fault` -- `DeviceBackend.provisioning_fault`, whose own docstring promises
#:   the badge "says why on serial and in Settings" and whose Settings half was
#:   never written.
#:
#: NEITHER `uid` NOR `token` IS SECRET, and the argument is already in this file:
#: a JWT `sub` is a public claim and nothing is authorised by knowing it (see
#: :data:`SHARED_SUB`).
IDENTITY_KEYS = (
    "uid",
    "token",
    "boot",
    "build",
    "fault",
)


def _ticks_ms():
    function = getattr(time, "ticks_ms", None)
    return function() if function is not None else int(time.monotonic() * 1000)


def _ticks_add(value, delta):
    function = getattr(time, "ticks_add", None)
    return function(value, delta) if function is not None else value + delta


def _ticks_diff(left, right):
    function = getattr(time, "ticks_diff", None)
    return function(left, right) if function is not None else left - right


def _error_text(exc):
    return "{}: {}".format(exc.__class__.__name__, str(exc))[:160]


# -- THE DIAGNOSTIC PROJECTION HELPERS -----------------------------------------
#
# Four one-liners rather than the same four guards repeated at thirty call
# sites, and the reason is not tidiness. Every one of them is a layer whose
# ABSENCE is invisible until a badge resets in a loop at the venue: the accessors
# below are read by `settings_model` on a DRAW path, where an exception reaches
# `fatal_error` and `machine.reset()`s the badge -- every badge, every frame, for
# ever. Spelling the rule once is what makes "did this call site guard?" a
# question nobody has to ask.


def _text(value):
    """A non-empty ``str``, or ``None`` meaning "cannot tell you".

    THE TWO WAYS A RUNTIME STRING RUINS A 308 px BAND, closed together: a
    stand-in answering a formatted repr, and a field answering ``""``. The
    second is the nastier one -- an empty string draws as a blank line that
    looks like a measurement that came back zero, when nothing was measured at
    all. The builders draw the absence in words instead.
    """

    return value if isinstance(value, str) and value else None


def _whole(value):
    """A non-negative, non-``bool`` ``int``, or ``None``.  See :func:`_text`.

    ``bool`` IS EXCLUDED FIRST because it is a subclass of ``int`` in both
    runtimes, so a flag forwarded where a counter was expected would sail
    through an `isinstance(value, int)` check and draw as `Tries 1  fails 0` --
    a count nobody took, which is the one thing these projections may never
    produce.
    """

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _call(target, name):
    """One no-argument read off a duck-typed object, or ``None``.

    THREE FAIL-SOFT LAYERS AND EACH ONE IS A REAL BADGE.

    1. `getattr`, because `/system/lib` and the apps that read it are installed
       by SEPARATE steps, so a runtime older than an accessor genuinely has no
       such method and a bare call is an AttributeError on the draw path.
    2. `callable`, because a stand-in may carry the name as data -- the
       fixtures, the kill-test and the browser lane all pass their own objects
       through the backend factory.
    3. `try`, because these reads walk a backend and touch native calls
       (`ifconfig`, `uname`). A diagnostic may not be the thing that crashes the
       badge it is diagnosing.
    """

    reader = getattr(target, name, None)
    if not callable(reader):
        return None
    try:
        return reader()
    except Exception:  # noqa: BLE001 - a reset is the alternative
        return None


def _call_dict(target, name):
    """:func:`_call`, narrowed to a ``dict``.

    The type check is the same layer for the same reason `push_diagnostics`
    carries one: a stand-in answering a list would otherwise reach `.get()` and
    raise on a draw path. NOT FOLDED INTO `_call`, because `identity` genuinely
    wants a string back from `badge_id` -- a helper that took the expected type
    as an argument would make strictness a caller's decision, which is exactly
    the layer whose absence is invisible.
    """

    record = _call(target, name)
    return record if isinstance(record, dict) else None


# THE `wipe_scores` SCOPES, FROZEN (owner ruling, 2026-08-27). Two of them, and
# the second is the whole reason this verb carries a payload at all:
#
# * "spool" -- the UNDELIVERED submissions in `scorebox`. The DEFAULT, and the
#   only scope anyone has a reason to queue: the feature exists to stop a
#   reconnect backlog draining into the leaderboard.
# * "all" -- that, plus the wearer's own persisted high scores
#   (`/state/<game>.json`, `scorebox.GAME_STATE_PATHS`).
#
# FREEZE THE CAPABILITY, GATE THE POWER. The firmware is gang-cloned onto ~800
# badges with no update path, so a scope left out here can never be added later --
# but remote erasure of a wearer's personal bests must never arrive as a SIDE
# EFFECT of clearing a delivery backlog. Both scopes therefore exist in the frozen
# dispatch, and WHETHER "all" IS EVER QUEUED is a server-side, owner-level policy
# decision that stays editable and auditable forever.
#
# AN UNKNOWN SCOPE FAIL-ACKS RATHER THAN FALLING BACK, and that is the
# load-bearing half. A frozen firmware that quietly ignored a scope it did not
# understand would under-execute a future wider command and ack "applied" for work
# it did not do -- and nobody would find out until the scores were still there.
WIPE_SCOPE_SPOOL = "spool"
WIPE_SCOPE_ALL = "all"
WIPE_SCOPES = (WIPE_SCOPE_SPOOL, WIPE_SCOPE_ALL)


def _wipe_scope(payload):
    """The scope a ``wipe_scores`` payload asks for.  Raises on anything else.

    AN ABSENT OR EMPTY PAYLOAD IS THE DEFAULT SCOPE. Requiring the key would
    reject the smallest valid broadcast for a reason nobody could read off its
    receipt. Naming the scope explicitly is still the documented shape.
    """

    if payload is None:
        return WIPE_SCOPE_SPOOL
    if not isinstance(payload, dict):
        raise ValueError("wipe_scores payload must be an object")
    if not payload:
        return WIPE_SCOPE_SPOOL
    if tuple(payload.keys()) != ("scope",):
        raise ValueError("wipe_scores takes exactly one scope key")
    scope = payload["scope"]
    # `isinstance(True, int)` is why the type is checked before the membership:
    # a bare `in` would let a stray `True` past on a tuple of strings only by
    # luck, and this module's other appliers reject bools explicitly for the
    # same reason.
    if not isinstance(scope, str) or scope not in WIPE_SCOPES:
        raise ValueError("wipe_scores scope must be one of {}".format(
            ", ".join(WIPE_SCOPES)))
    return scope


# -- the battery levers (fleet battery management, 2026-08-28) ---------------
#
# THE MEASURED PROBLEM. A badge lasts ~7 h 36 m under conference-like load
# (owner-reported, 2026-08-28), and a conference day is longer than that. These
# two verbs are the admin-side levers for the difference, and they are ranked by
# what they actually save: `sleep` turns EVERYTHING off, `set_networking` turns
# the radio off. Only the first is a step change; the second shaves a component.
#
# A THIRD VERB WAS CUT BEFORE IT SHIPPED, and the reason is a rule rather than a
# detail (owner ruling, 2026-08-28). `set_push` would have closed the WebSocket
# doorbell for ~1% of a day's battery: the doorbell's traffic is ~77 B/s measured
# and the cost of a radio is STANDING CURRENT, which polling keeps powered
# anyway. It also duplicated a control that already exists and is fully
# reversible -- `badge_transport_policy.push_enabled`, RAM-only on the badge and
# failing open. Every verb here is pinned across firmware `_apply` and the
# broadcast schema, so a 1% verb is not worth the surface. Use the policy row
# instead.
#
# THE OWNER'S FRAME, verbatim (2026-08-28): *"we're not breaking the device or
# anything. A user can easily hit reset, but we're just creating the experience
# we want for the users. If they want to go against that, fine."* Every bound
# below exists to keep that true -- RESET must always be a real escape, and no
# admin mistake may cost more than one talk.

#: THE LONGEST REMOTE SLEEP, IN MINUTES, and the number is a CEILING on the
#: damage a malformed or hostile row can do rather than a product feature.
#:
#: 60 because the use case is "sleep the fleet for a talk that does not need
#: badges" and a conference talk is 20-60 minutes; a keynote block is the outlier
#: and it can be sent as two commands. The cost of guessing high is what makes
#: this a ceiling: `sleep(n)` arms the ALARM ALONE (device-measured 2026-08-21,
#: report §6), so for the whole duration the five face buttons are dead and RESET
#: is the only escape. A `minutes` of 1440 typo'd into a console would put ~800
#: badges down for a day, and every wearer who did not think to press RESET would
#: read it as a dead badge. One talk is a mistake somebody laughs about.
SLEEP_MAX_MINUTES = 60

#: HOW LONG THE PRE-SLEEP NOTE STAYS ON THE PANEL, and it is a READING time.
#:
#: LONGER THAN SETTINGS' OWN 1000 ms (`settings_model.SLEEP_NOTE_MS`) ON PURPOSE.
#: That note follows a button the wearer just pressed, so they are already
#: looking at the screen; this one interrupts somebody who asked for nothing, so
#: the first part of the second is spent noticing that the screen changed at all.
#: Nothing can cancel it either way -- see `_pump_power_action`, which repaints
#: rather than reads keys.
SLEEP_NOTE_MS = 1500

#: HOW LONG A DEFERRED POWER ACTION WAITS FOR ITS ACK BEFORE GIVING UP.
#:
#: An ack is URGENT on the wire (`PollLoop.queue_ack` pulls the next exchange to
#: now), so the healthy case is one exchange -- well under a second. 30 s buys a
#: couple of failed exchanges and a reconnect without holding a pending sleep
#: into the talk it was meant to cover. ON EXPIRY THE ACTION IS ABANDONED, NEVER
#: PERFORMED: see `_pump_power_action` for why that direction is the only safe
#: one.
POWER_ACTION_ACK_MS = 30000

#: The pre-sleep note's words. THE COPY RULES ARE `settings_copy`'s AND THEY ARE
#: LOAD-BEARING FOR THE SAME REASON: there is nothing on screen afterwards to
#: correct a lie, and this time the wearer did not ask for the screen.
#:
#: THE TWO FORMS SAY DIFFERENT THINGS ABOUT WAKING BECAUSE THE HARDWARE DOES.
#: Measured on device 2026-08-21 (`benchmark/results/reports/2026-08-21-device-
#: session.md` §6): `sleep()` reaches `powman.sleep()` and arms A/B/C/UP/DOWN;
#: `sleep(n)` reaches `goto_dormant_for` and arms **the alarm alone** -- the five
#: buttons are ignored until it expires. HOME is not a wake source either way.
#: So the timed note may not offer a button, and the indefinite note must name
#: HOME as the exception rather than promise "any button".
SLEEP_TITLE = "SLEEPING"
SLEEP_LINE_WAKE = "A B C UP DOWN WAKE"
SLEEP_LINE_HOME = "HOME DOES NOT WAKE"
SLEEP_LINE_BUTTONS = "BUTTONS DO NOT WAKE"
SLEEP_LINE_RESET = "RESET WAKES SOONER"
SLEEP_LINE_RESTART = "RESTARTS ON WAKE"


def sleep_note_lines(seconds):
    """The lines to draw before dormancy, for a duration in seconds.

    PURE, so the copy is testable without a panel -- which is the only way the
    wake claim above can be gated, because the claim is a sentence rather than a
    pixel.

    A DURATION, NEVER A WALL-CLOCK WAKE TIME, and the owner's "back at 2:30" was
    considered and rejected on evidence. Two facts decide it. (1) A duration is
    monotonic: `badge.sleep(n)` runs off the POWMAN always-on timer, measured to
    keep counting through dormancy and not be re-seeded, so it is immune to a
    wrong or hand-set clock. (2) The badge has no local time to render one with:
    a paired badge's clock reads UTC (`ntptime.settime()` sets it from `gmtime`;
    VAL-041-BLR) and nothing in this library carries the event's UTC offset --
    `schedule_store` rule 7 records that gap as still open. "Back at 2:30" drawn
    seven hours out is worse than no time at all, because a wearer can disprove
    it and will then distrust the rest of the note.
    """

    if seconds is None:
        return (SLEEP_TITLE, SLEEP_LINE_WAKE, SLEEP_LINE_HOME,
                SLEEP_LINE_RESTART)
    minutes = seconds // 60
    return (SLEEP_TITLE,
            "WAKES IN {} MIN".format(minutes),
            SLEEP_LINE_BUTTONS,
            SLEEP_LINE_RESET)


def _networking_intent(payload):
    """``(on, persist)`` for a ``set_networking`` payload, or a raise.

    PURE, so every delivery path applies the same strict payload rules. Same
    reason `_wipe_scope` is a function.
    """

    if not isinstance(payload, dict):
        raise ValueError("set_networking payload must be an object")
    keys = set(payload.keys())
    if "on" not in keys or not keys <= set(("on", "persist")):
        raise ValueError("set_networking payload requires on and at most persist")
    on = payload["on"]
    if not isinstance(on, bool):
        raise ValueError("set_networking on must be a boolean")
    persist = payload.get("persist", False)
    if not isinstance(persist, bool):
        raise ValueError("set_networking persist must be a boolean")
    return on, persist


def _backlight_intent(payload):
    """``(level, persist)`` for one fleet backlight moment, or a raise.

    Transient control may reach the fleet command's 10 percent safety floor.
    Persistence has a 20 percent floor because Settings' durable wearer ladder
    cannot represent anything lower; accepting 10 percent there would make the
    panel jump on the next reset while a successful receipt claimed otherwise.
    """

    if not isinstance(payload, dict):
        raise ValueError("set_backlight payload must be an object")
    keys = set(payload.keys())
    if "level" not in keys or not keys <= set(("level", "persist")):
        raise ValueError("set_backlight payload requires level and at most persist")
    level = payload["level"]
    if isinstance(level, bool) or not isinstance(level, (int, float)):
        raise ValueError("set_backlight level must be a number")
    if level != level or level * 0 != 0:
        raise ValueError("set_backlight level must be finite")
    persist = payload.get("persist", False)
    if not isinstance(persist, bool):
        raise ValueError("set_backlight persist must be a boolean")
    floor = 0.2 if persist else 0.1
    if level < floor or level > 1:
        if persist:
            raise ValueError("persistent set_backlight level must be 0.2..1")
        raise ValueError("set_backlight level must be 0.1..1")
    return level, persist


def _sleep_seconds(payload):
    """Dormancy in SECONDS for a ``sleep`` payload, or ``None`` for indefinite.

    ZERO, NEGATIVE, FRACTIONAL AND OVER-BOUND ARE ALL REFUSED RATHER THAN
    COERCED, and the reasons differ. An ABSENT ``minutes`` is not an error --
    ``{}`` is the indefinite broadcast form. A ``minutes`` of 0 or less
    is a MALFORMED row: coercing it to the indefinite form would silently turn a
    typo into a different command than the operator sent, and this module's rule
    (see the ``wipe_scores`` scopes) is that frozen firmware fail-acks what it
    does not understand rather than guessing, because nobody finds out about a
    guess. A float is refused because ``goto_dormant_for`` takes whole seconds
    and 2.5 minutes is a row nobody meant. The ceiling is
    :data:`SLEEP_MAX_MINUTES` and its reasoning is at the constant.
    """

    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("sleep payload must be an object")
    keys = tuple(payload.keys())
    if not keys:
        return None
    if keys != ("minutes",):
        raise ValueError("sleep takes at most one minutes key")
    minutes = payload["minutes"]
    # `isinstance(True, int)` again: a bare int check reads `True` as one minute.
    if isinstance(minutes, bool) or not isinstance(minutes, int):
        raise ValueError("sleep minutes must be a whole number")
    if minutes < 1:
        raise ValueError("sleep minutes must be at least 1")
    if minutes > SLEEP_MAX_MINUTES:
        raise ValueError(
            "sleep minutes must be at most {}".format(SLEEP_MAX_MINUTES))
    return minutes * 60


def _draw_sleep_note(lines):
    """Paint the note over whatever app owns the frame.  Never raises.

    BARE NAMES, NOT `getattr(builtins, ...)`, and this is the trap
    `install_system_lib` and `docs/engineering-findings.md` both record: the
    pinned runtime's injected globals participate in normal name resolution but
    are NOT visible through the `builtins` module object, so `getattr` here would
    answer `None` on a badge where the panel exists. A missing name raises
    `NameError`, which is why every one of them is inside the try.
    Host tests install module-global recorders for these three names. Hardware
    still falls through to Badgeware's injected globals, so the geometry can be
    gated without changing the device lookup rule.
    ⚠ AND IT IS THE ONE PLACE THIS MODULE DRAWS AT ALL. `install()` is handed
    `display_api` for `set_backlight` and nothing else, so a screen handle would
    have meant a new argument in the generated `/system/main.py` block -- which
    is a REINSTALL, and a badge that is never reinstalled would silently lose the
    note. Reading the injected name costs no boot-block change and degrades to
    "no note, still sleeps".
    ⚠ POINT FORM ONLY. `screen.text(s, x, y, scale)` never parses `[...]` glyph markup;
    the rect form does, and an unknown renderer name raises inside `update()`,
    which is the traceback modal and a reset (`settings_view` rule 1). These
    strings are constants today, and point form means they can never become the
    crash class even if a future one carries a name.

    A FAILURE HERE MAY NOT COST THE SLEEP. The caller has already decided to go
    dormant and has already told the server so; a panel that would not paint is a
    worse note, not a worse decision.
    """

    try:
        width = screen.width                     # noqa: F821 - injected builtin
        height = screen.height                   # noqa: F821
        # Badgeware's two production panels are 160x120 and 320x240. Keeping
        # one LORES geometry and scaling it makes this interrupt readable over
        # either an identity app or a game without switching the app's mode.
        unit = 2 if width >= 240 else 1
        background = color.rgb(5, 18, 16)        # noqa: F821
        phosphor = color.rgb(62, 207, 142)        # noqa: F821
        white = color.rgb(255, 255, 255)          # noqa: F821
        warning = color.rgb(255, 176, 72)         # noqa: F821

        screen.pen = background                  # noqa: F821
        screen.clear()                           # noqa: F821

        # The rail and crescent make this read as an intentional power-state
        # card, not a crash message, using only ROM primitives immediately
        # before dormancy (no font.load, asset read or retained buffer).
        screen.pen = phosphor                    # noqa: F821
        screen.rectangle(12 * unit, 12 * unit,   # noqa: F821
                         3 * unit, height - 24 * unit)
        screen.circle(137 * unit, 22 * unit, 10 * unit)  # noqa: F821
        screen.pen = background                  # noqa: F821
        screen.circle(141 * unit, 18 * unit, 10 * unit)  # noqa: F821

        screen.font = font.badgewaremax           # noqa: F821
        screen.pen = phosphor                    # noqa: F821
        screen.text(lines[0], 23 * unit, 15 * unit, unit)  # noqa: F821

        screen.font = font.sins                  # noqa: F821
        for index in range(1, len(lines)):
            # Amber is reserved for the last thing the wearer must remember:
            # the escape/restart consequence once the panel goes dark.
            screen.pen = warning if index == len(lines) - 1 else white  # noqa: F821
            screen.text(lines[index], 23 * unit,             # noqa: F821
                        (55 + (index - 1) * 17) * unit, unit)
        return True
    except Exception:  # noqa: BLE001 - see the docstring: no note beats no sleep
        return False


def _default_rand01():
    """One float in [0, 1) from the hardware RNG, two bytes at a time.

    The same shape `polltransport._default_rand01` uses, and imported lazily for
    the same reason every other import in this module is. Drawn a handful of times
    per BOOT (the cadence phases below), never per frame.
    """
    import os

    raw = os.urandom(2)
    return (raw[0] << 8 | raw[1]) / 65536.0


def _device_reset():
    """Reset lazily so the host fixtures never need a fake ``machine`` module."""
    import machine

    machine.reset()


# The RP2350 accepts at most 16,777 ms. Keep a little below that boundary so
# firmware rounding cannot reject the value. A 16,000 ms watchdog was measured
# on the production badge on 2026-08-31: neither a full 60 s dormant sleep nor
# indefinite button-wake sleep caused a watchdog reset, and both woke normally.
WATCHDOG_TIMEOUT_MS = 16000


def _start_runtime_watchdog(factory=None):
    """Arm the one hard bound around native calls, or keep running without it.

    Python deadlines cannot interrupt a native socket call once the firmware is
    inside it. Marginal RF reproduced that exact failure: the panel and buttons
    froze and USB vanished while WebSocket establishment never returned. The
    hardware watchdog is recovery, not transport policy; ordinary failures
    still use the existing retry/backoff path.

    A missing watchdog must not turn an otherwise usable offline badge into a
    boot loop. Host fixtures also have no ``machine`` module, so lookup is lazy
    and failure leaves the existing runtime intact.
    """
    try:
        if factory is None:
            import machine

            factory = machine.WDT
        watchdog = factory(timeout=WATCHDOG_TIMEOUT_MS)
    except Exception as error:  # noqa: BLE001 - fail open keeps the badge usable
        print("BADGELINK_WATCHDOG armed=0 error={}".format(
            error.__class__.__name__))
        return None
    print("BADGELINK_WATCHDOG armed=1 timeout_ms={}".format(
        WATCHDOG_TIMEOUT_MS))
    return watchdog


#: THIS BADGE'S PHYSICAL IDENTITY, CACHED FOR THE BOOT. ``None`` until the first
#: :func:`hardware_uid` call and on any host/fixture without ``machine``.
_HARDWARE_UID = None


#: THE ONE PROVISIONING FAULT THE FIRMWARE CAN DETECT BY ITSELF, spelled as a
#: bounded word rather than a message: it reaches a Settings line, and a screen may
#: only draw strings the glyph set was baked with.
FAULT_SUB_IS_A_BADGE = "shared_sub_is_this_badge"

#: THE FLEET'S SUBJECT, PINNED, and the whole reason :func:`provisioning_fault` can
#: tell its two inputs apart.
#:
#: **WITHOUT THIS CONSTANT THE CHECK WAS A TAUTOLOGY AND IT REFUSED TO NETWORK ON
#: EVERY DEV BADGE.** It compared the LOADED credential's subject against
#: `machine.unique_id().hex()` — and on a per-badge mint those are equal BY
#: CONSTRUCTION, because that mint sets `sub = machine.unique_id().hex()` (§0.5's
#: own linchpin says so). So the predicate could not distinguish the collision it
#: was written for from the normal state of every badge not yet re-provisioned, and
#: it faulted all of them. Found on hardware: six interleaved arms, `attempts=0` in
#: all six, `reason=shared_sub_is_this_badge` at 3.08 s of every boot.
#:
#: IT IS NOT A SECRET. A JWT `sub` is a public claim, it is already in the token
#: this firmware ships, and nothing is authorised by knowing it — the signature is
#: what authorises. What it buys is the ability to answer "is the credential I am
#: holding the FLEET's, or my own?", which no other value on the badge can answer.
#:
#: FAILS OPEN BY DESIGN. If the owner mints with a different subject, this constant
#: stops matching and the check simply never fires — which is the right direction
#: for a guard whose entire purpose is catching a ~4x10^-17 coincidence. A guard
#: that fails CLOSED on an unrecognised subject is what produced the outage above.
SHARED_SUB = "b60582ec3e2974a1"

#: WHICH CREDENTIAL THIS BADGE IS CARRYING, as bounded words for the serial line.
#: Worth emitting because the §0.8 rollout deliberately runs new firmware on OLD
#: per-badge tokens as its safety step, and until now nothing on the wire said which
#: of the two a badge had — so a fleet half-way through provisioning was
#: indistinguishable from one that had not started.
CREDENTIAL_TIER_FLEET = "fleet"
CREDENTIAL_TIER_PER_BADGE = "per_badge"


def credential_tier(subject):
    """Is this the fleet's shared subject, this badge's own, or neither?

    ``None`` when it cannot be told — no subject, or no hardware id (a host
    fixture). Total: this is read on the launch path.
    """

    if not isinstance(subject, str) or not subject:
        return None
    if subject == SHARED_SUB:
        return CREDENTIAL_TIER_FLEET
    uid = hardware_uid()
    if uid is not None and subject == uid:
        return CREDENTIAL_TIER_PER_BADGE
    return None


def provisioning_fault():
    """Is the FLEET's subject also this badge's own hardware id? Almost never.

    **TAKES NO ARGUMENT, AND THAT IS THE FIX RATHER THAN AN ECONOMY.** It used to
    take the loaded credential's subject and return a fault when
    ``subject == uid`` -- which is a TAUTOLOGY on a per-badge mint, because that
    mint sets ``sub = machine.unique_id().hex()`` (§0.5's own linchpin). So every
    un-reprovisioned badge faulted and refused to network: six hardware arms,
    ``attempts=0`` in all six, `reason=shared_sub_is_this_badge` at 3.08 s of every
    boot. Removing the parameter is what makes that mistake unavailable to the next
    reader, which a comment could not.

    THE COLLISION THIS RULES OUT, and why it is checked at all when the odds are
    ~4x10^-17. Gang-clone provisioning drops the 800-UID disjointness manifest --
    there is no UID scan and there never will be -- so the firmware's own boot
    check is the ONLY thing standing between a one-in-a-quintillion draw and a
    fleet whose kill switch is wired to a physical badge. If `SHARED_SUB` were
    some badge's `machine.unique_id()`, that badge's `badge_state` row and the
    floor identity would collide: revoking the fleet grant would revoke that
    badge's own tier, and its `_self` writes would collide with the identity the
    claim RPCs are required to refuse.

    NEVER BRICKS, NEVER SILENT -- the two halves of the ruling. It returns a WORD
    rather than raising, because this runs on the launch path where an exception
    is a `machine.reset()`; the caller emits it and refuses to network, so the
    badge stays a working offline nametag and says why on serial and in Settings.
    That is also the honest response: a badge in this state cannot safely use the
    floor, and offline-first means it does not have to.

    ``None`` when there is nothing to compare -- no credential, or no hardware id
    on a host fixture. An unprovable check may not manufacture a fault.

    **THE HAZARD IS A PROPERTY OF THE UID, NOT OF THE CARRIED CREDENTIAL**, which
    is why the comparison is `uid == SHARED_SUB` and nothing else. A narrower
    version -- fault only while ALSO holding the fleet token -- was drafted and
    rejected: `p_badge_id` and `x-badge-id` are read from `hardware_uid()` on EVERY
    `_self` call whatever token is in `secrets.py`, so a badge whose UID equals the
    fleet subject collides with the floor identity under any credential. The Phase-2
    claim RPCs would refuse it (`p_badge_id != SHARED_SUB`), its scores and commands
    would land on the floor's rows, and revoking the fleet grant would revoke its
    own tier. Faulting on the UID alone is both simpler and the case §2 actually
    names.

    THE ODDS ARGUMENT APPLIES TO THIS COMPARISON AND NOT THE OLD ONE. ~4x10^-17 is
    the chance of the shared subject matching a UID. It was never the chance of a
    badge holding a token minted from its own UID, which is 1 -- and conflating the
    two is what let a 1-in-a-quintillion guard fire on every badge in the building.
    """

    uid = hardware_uid()
    if uid is None:
        # Nothing to compare: a host fixture, or a `machine` that would not answer.
        # An unprovable check may not manufacture a fault.
        return None
    return FAULT_SUB_IS_A_BADGE if uid == SHARED_SUB else None


def hardware_uid():
    """The 16-lowercase-hex physical badge id, or ``None`` off-device.

    **THE LINCHPIN OF THE SHARED-TOKEN FLEET.** All 800 badges ship a
    byte-identical ``/secrets.py``, so ``credentials.load(secrets).badge_id`` --
    the JWT ``sub`` -- is the SAME 16-hex value on every one of them and names
    the fleet rather than a badge. ``machine.unique_id()`` is 8 bytes of RP2350
    flash id, so this is the only per-badge identity the firmware has, and every
    consumer that used to lean on ``sub`` as "who am I" now reads this instead:
    the fleet doorbell's positive ring filter, the `_self` poll/ack/score RPCs'
    ``p_badge_id``, the ``x-badge-id`` fairness bucket, and the schedule sync's
    deterministic anti-herd stagger. `DeviceBackend.badge_id` deliberately does
    NOT -- ``badge_state``'s RLS is ``badge_id = grants.whoami()``, so that write
    has to keep naming the subject or it is denied.

    COMPUTED ONCE PER BOOT, and the cache is the contract rather than an
    optimisation: four independent consumers must agree, and a per-call read
    would put a `machine` import and a hex encode on the frame that polls.

    ``bytes.hex()`` IS NOT ASSUMED. `hashlib.sha256` on `bw-1.28.0-3` exposes
    `digest()` and NOT `hexdigest()` (see `_badge_stagger_ms`), and the device
    printed `AttributeError` while `mpremote` returned 0 -- so an attribute this
    module has not verified on hardware gets a fallback rather than a guess.
    `binascii.hexlify` is the one both runtimes have.

    RETURNS ``None`` RATHER THAN RAISING, ALWAYS. This is reached from the push
    factory, the link build and the score drain, all of which run inside a
    rendered frame under `launch()`, where an unhandled exception is a
    `machine.reset()`. Every consumer treats ``None`` as "cannot prove my
    identity" and degrades: the ring filter stays silent, the `x-badge-id`
    header is omitted (the shared-sub bucket, degraded but working) and the
    stagger falls back to a random draw.
    """

    global _HARDWARE_UID
    if _HARDWARE_UID is not None:
        return _HARDWARE_UID
    try:
        import machine

        raw = machine.unique_id()
        hexer = getattr(raw, "hex", None)
        if callable(hexer):
            value = hexer()
        else:
            import binascii

            value = binascii.hexlify(raw).decode()
    except Exception:
        return None
    if not isinstance(value, str):
        return None
    # LOWERCASE IS THE WIRE FORM, and it is not cosmetic: the server validates
    # every self-reported id against `^[0-9a-f]{16}$` (the `_self` RPCs, the
    # `x-badge-id` limiter bucket and `can_access_channel`'s topic tails all
    # spell it), so an upper-case digit is a 22023 rather than a mismatch.
    value = value.lower()
    # EXACTLY SIXTEEN, VALIDATED RATHER THAN COUNTED ON. RP2350's unique id is 8
    # bytes so this holds, but the server's regex is anchored at sixteen and a
    # board that answered otherwise would turn every poll, ack and score into a
    # 22023 instead of degrading. Refusing here keeps the badge on the honest
    # fallbacks it already has for "no id".
    if len(value) != 16:
        return None
    for character in value:
        if character not in "0123456789abcdef":
            return None
    _HARDWARE_UID = value
    return value


class SessionAddresses:
    """ONE resolved address per host, for as long as the WLAN session lasts (CX-3).

    THE ASYMMETRY THIS CLOSES. The poll transport resolves the project host ONCE
    per boot -- `DeviceBackend._build_loop` calls ``getaddrinfo`` and injects the
    answer into the worker as ``_addr_info``, so `DeviceLink.begin`/`pump`/`close`
    never touch DNS again. The doorbell had no equivalent: layer 1 connects
    through ``asyncio.open_connection(uri.hostname, uri.port, ssl=)``
    (`network/vendor/aiohttp/aiohttp_ws.py`) and MicroPython resolves the name
    INSIDE that call, blocking, on EVERY attempt -- up to three attempts per boot
    before the demotion rule silences push, plus one on every reauthorization
    reconnect, each in an ORDINARY launcher frame. ``connect_timeout_ms`` cannot
    bound any of it: `_wait_for` cannot interrupt a blocking C call.

    So the two transports share one cache, and the shape they share is
    **IP-PLUS-SNI**, which is device-proven: `p6_device_kill_probe` connects with
    ``asyncio.open_connection(address, port, ssl=ctx, server_hostname=hostname)``
    on real hardware, and the board capability probe records
    ``server_hostname_kwarg=accepted``. Verification stays on the NAME -- the
    address is only where the socket goes. `postgrest` has priced the same shape
    since Card E ("cached IP when available (DNS off-frame); ``server_hostname``
    stays the real host").

    PER HOST, not per session-with-one-host, because nothing guarantees the WSS
    endpoint and the REST endpoint are the same name in every deployment shape.
    Today they are (both ``<ref>.supabase.co``), and this class does not care.

    INVALIDATED ON WLAN LOSS. A new association can mean a new DHCP lease, a new
    resolver and a different venue's split-horizon answer, so the ``wifi_lost``
    edge -- which already exists and already asks the loop to reconnect -- clears
    the cache. The poll link keeps the ``_addr_info`` it was built with, which is
    unchanged behaviour: it is created once per boot and reused across reconnects.

    AND ON A DOORBELL DEMOTED FOR *UNREACHABLE*, which is the edge the radio's two
    cannot see: an answer that goes bad while the badge stays ASSOCIATED produces
    no `wifi_lost` at all. See `DeviceBackend.note_push_unreachable` -- and note
    that it, not this class, is the seam, because the ON strategy's readiness bit
    has to move with the cache or held WSS can never be admitted again.

    Bounded at :data:`MAX_HOSTS` because it is a per-boot cache with two known
    callers and no eviction policy worth writing; a third host is a deployment
    change, not a leak.
    """

    #: Two known callers, one host each today, and one spare.
    MAX_HOSTS = 4

    def __init__(self, getaddrinfo, sock_stream=0, event_sink=None):
        if not callable(getaddrinfo):
            raise ValueError("a getaddrinfo is required")
        self._getaddrinfo = getaddrinfo
        self._sock_stream = sock_stream
        self._event_sink = event_sink
        self._entries = {}
        #: Credential-free and endpoint-free counters. `lookups` is the number of
        #: BLOCKING resolutions this boot actually performed, which is the number
        #: CX-3 exists to hold down; `hits` is what the share bought.
        self.lookups = 0
        self.hits = 0
        self.invalidations = 0

    def resolve(self, host, port=443):
        """The addrinfo tuple for ``host``, resolving at most once per session.

        Raises whatever ``getaddrinfo`` raises. A caller that must not fail asks
        :meth:`address` instead.
        """
        key = (host, int(port))
        found = self._entries.get(key)
        if found is not None:
            self.hits += 1
            return found
        info = self._getaddrinfo(host, int(port), 0, self._sock_stream)[0]
        self.lookups += 1
        if len(self._entries) < self.MAX_HOSTS:
            self._entries[key] = info
        return info

    def remember(self, host, port, info):
        """Record an address a caller resolved for itself. Never raises."""
        if info is None:
            return None
        if len(self._entries) >= self.MAX_HOSTS:
            return None
        self._entries[(host, int(port))] = info
        return info

    def cached_address(self, host, port=443):
        """A cached bare address, or ``None``.  Performs NO name lookup."""

        info = self._entries.get((host, int(port)))
        if info is None:
            return None
        self.hits += 1
        return self._address_from_info(info)

    def has_cached_address(self, host, port=443):
        """Whether a usable numeric address is cached, without a lookup/hit."""

        # Readiness is a safety gate, not a cache use. Counting it as a hit would
        # make the CX-3 metric grow when no socket consumed an address, while
        # checking only key presence would admit a malformed addrinfo row and
        # send the held task into the vendored client's blocking name lookup.
        info = self._entries.get((host, int(port)))
        return info is not None and self._address_from_info(info) is not None

    def address_strict(self, host, port=443):
        """Like :meth:`address` but RAISES when a resolve was tried and failed.

        WHY BOTH EXIST. ``address`` returns ``None`` on any failure, and ``None``
        means "connect by name" at the next layer. That was harmless when the
        only resolver WAS the by-name path. It is not harmless now: since
        2026-08-27 the resolve goes through `bounded_dns`, so a timeout costs its
        budget AND THEN hands the caller a value meaning "spend 13,121-14,017 ms
        in one rendered frame" (measured, no route). The two costs add; the
        escalation is strictly worse than either.

        THE DISTINCTION THIS DRAWS is between "no address is cached and none was
        attempted" -- where by-name is a legitimate affordance the probes rely on
        -- and "we asked a bounded resolver and it refused". Only the second
        raises. A caller that cannot afford an unbounded call uses this one.
        """
        cached = self.cached_address(host, port)
        if cached is not None:
            return cached
        info = self.resolve(host, port)          # deliberately not caught
        value = self._address_from_info(info)
        if value is None:
            raise OSError("resolver returned an unusable addrinfo for %s" % host)
        return value

    def address(self, host, port=443):
        """The bare address string for ``host``, or ``None``. NEVER raises.

        ``None`` means "connect by name", which is exactly the behaviour the
        doorbell had before this class existed -- so a resolver failure, an
        unexpected addrinfo shape or a missing cache degrades to the old cost and
        never to a dropped connection.
        """
        cached = self.cached_address(host, port)
        if cached is not None:
            return cached
        try:
            info = self.resolve(host, port)
        except Exception:
            return None
        return self._address_from_info(info)

    @staticmethod
    def _address_from_info(info):
        try:
            sockaddr = info[-1]
        except Exception:
            return None
        # THE SHAPE IS CHECKED, not assumed. A `getaddrinfo` row is
        # `(family, type, proto, canonname, sockaddr)` and only the last element
        # is the address tuple -- and a string indexes without complaining, so an
        # unchecked `info[-1][0]` would happily hand a doorbell one CHARACTER of a
        # hostname to connect to.
        if not isinstance(sockaddr, (tuple, list)) or not sockaddr:
            return None
        value = sockaddr[0]
        return value if isinstance(value, str) and value else None

    def invalidate(self, reason="wifi_lost"):
        """Forget every address. Called on a WLAN or push edge; never raises."""
        if not self._entries:
            return 0
        count = len(self._entries)
        self._entries = {}
        self.invalidations += 1
        sink = self._event_sink
        if sink is not None:
            try:
                sink({"event": "addresses_invalidated", "reason": reason,
                      "hosts": count})
            except Exception:
                pass
        return count

    def snapshot(self):
        return {"hosts": len(self._entries), "lookups": self.lookups,
                "hits": self.hits, "invalidations": self.invalidations}


class _PushControl:
    """The Settings-facing face of the push preference.

    One property, one setter, and the read-through answers a panel asks for:
    `mode`, `cause`, `previous_cause` and `diagnostics`. The STATE IS ALWAYS
    READ THROUGH, never cached here: the owner's Card PW rule is that a control
    reads its state back from the transport rather than assuming the last press
    worked, and a cache in this object would be exactly that assumption with an
    extra step.

    EVERY ACCESSOR HERE WAS ADDED BECAUSE A COMPUTED VALUE HAD NO READER, and
    the surface has therefore grown in one direction only: `cause` (the eight
    states behind one `trying`), `previous_cause` (the one the act of looking
    destroys) and now `diagnostics` (the counters that only ever reached
    serial). It is still narrow -- nothing here lets a tile drive the transport
    -- but "the same tiny surface as the network control" stopped being true at
    `cause`, so do not restore that claim by deleting an accessor.
    """

    def __init__(self, service):
        self._service = service

    @property
    def enabled(self):
        return self._service.push_enabled

    def set_enabled(self, enabled):
        return self._service.set_push_enabled(enabled)

    def mode(self):
        return self._service.push_mode()

    def cause(self):
        """WHY the mode is what it is, as one word from :data:`PUSH_CAUSES`.

        THIS FACE IS THE ONLY THING SETTINGS HOLDS, which is why the accessor has
        to exist here and not only on the service: the tile is handed
        ``push_control()``, so a `push_cause` reachable only from
        ``NetworkService`` is a derivation with no consumer. Forwarding rather
        than re-deriving keeps ONE definition of the vocabulary
        (:meth:`NetworkService.push_cause`), and the read-through discipline is
        the same as ``mode`` above for the same Card PW reason.

        RAISES WHATEVER THE SERVICE RAISES, deliberately: this is a plain
        forward, and a swallow here would hide an instrument fault from the one
        caller able to report it. The Settings side guards the call, because an
        exception on its draw path is `machine.reset()`.
        """
        return self._service.push_cause()

    def previous_cause(self):
        """The cause that was in force BEFORE the current one, or ``None``.

        THE ONE ACCESSOR SETTINGS ACTUALLY NEEDS FOR PLACEMENT, and the reason is
        an irony rather than an oversight: the Settings screen calls
        ``set_active(True)`` while it is open, so by the time this tile is drawn
        the placement grant it would have reported has already been given.
        :meth:`cause` therefore CANNOT return `CAUSE_PLACEMENT` to a reader on
        this screen -- not because the state never happened, but because looking
        ended it. See :meth:`NetworkService.push_cause_previous`.

        **IT EXPIRES**, after :data:`PUSH_CAUSE_LATCH_MS`, so a tile may render
        this value with no age qualifier beside it. That is deliberate: the bound
        lives on the ANSWER rather than on the surrounding copy, because copy is
        the thing that drifts. A screen that has to say "this is historical" is one
        edit away from not saying it.

        A plain forward, raising like :meth:`cause`, for the same reason.
        """

        return self._service.push_cause_previous()

    def diagnostics(self):
        """The narrowed push snapshot for a panel, or ``None``.

        THE SEAM IS THIS OBJECT, WHICH IS WHY THE ACCESSOR HAS TO BE HERE.
        `settings/__init__.py` is handed `push_control()` and nothing else -- the
        `NetworkService` arrives separately as the NETWORK control -- so a
        `push_diagnostics` reachable only from the service is a projection with
        no consumer, which is the exact shape :meth:`cause` was added to fix.

        NOT A PER-FRAME READ. :meth:`NetworkService.push_diagnostics` builds two
        dicts per call, so this belongs on a screen a wearer opens rather than in
        a frame loop; the tile reads it once per view build on one screen.

        A plain forward, raising like :meth:`cause` and :meth:`previous_cause`,
        and for the same reason: a swallow here would hide an instrument fault
        from the one caller able to report it. The service side is already total
        for the cases that are NOT faults (no doorbell, a stand-in with no
        snapshot), and the Settings side guards the call because an exception on
        its draw path is `machine.reset()`.
        """

        return self._service.push_diagnostics()


class NetworkService:
    """Preference, command effects and a lazily-created device backend."""

    # Cold OFF never materialises these NB-0-only fields on the instance. ON
    # writes them before use; the class values are immutable zero/False.
    _radio_generation = 0
    _push_nb_contract_validated = False
    # TRANSIENT EFFECT SLOTS ARE CLASS-SAFE because device probes construct a
    # skeletal service through `__new__`. A stop/error path must still be total
    # on that object; AttributeError while trying to contain another failure
    # would turn a recoverable transport teardown into a reset.
    _effect = None
    _effect_queue = None
    _live_candidate = None
    _live_pending = None
    # Skeletal probes share the same frame writer; unknown means try the real
    # four-argument form once before deciding a host shim is scalar-only.
    _caselights_variadic = None
    # A DURABLE FIRE INSTALLS THROUGH THE REAL APPLIER, which already performs
    # the operator-visible first write. The steady pump follows in the same
    # rendered poll, so it needs the installed object's identity to avoid a
    # second step at the same instant. Class defaults keep skeletal probe
    # services total; the pump consumes each marker on its first call.
    _lights_stepped_frame = None
    _effect_stepped_frame = None
    #: THE PANEL LEVEL A GLYPH EFFECT RETURNS THE BACKLIGHT TO, or ``None`` for
    #: "nobody has told us one, so do not touch the panel". A CLASS DEFAULT for
    #: the same reason `DeviceBackend.provisioning_fault` is one: probes and
    #: fixtures build these objects without running `__init__`, and this is read
    #: from an applier reachable on the frame path, where an AttributeError is a
    #: `machine.reset()`.
    #:
    #: A RECORD OF WHAT WAS SET, NEVER A READING -- the badge cannot ask the panel
    #: its level. Two writers: a fleet `set_backlight`, and
    #: :meth:`note_panel_level` for the wearer's own brightness row. The NAME is
    #: `docs/design/effect-library.md` §4's, not this file's invention, because
    #: the library's contract harness and that doc both refer to it.
    _panel_base = None
    #: OWNER RULING #22 placement (NB-0). Establishment -- a NEW poll open or
    #: WSS join -- is allowed only when the launcher's frame loop is foreground,
    #: or an app opted in via :meth:`set_active`. ``_at_launcher`` is resolved
    #: ONCE per ``run()`` call in ``managed_run`` (a run() call is one app for
    #: its whole life; an app switch is a new boot, see openapp_note). Class
    #: default ``True`` so a service nobody told the context to -- a probe, a
    #: fixture, a boot before ``enter_run_context`` -- keeps the launcher's
    #: always-connect liveness (fail-open, spec §4.5 amended invariant). Cold
    #: OFF never reads either: every reader is behind ``_nb_connect_enabled``.
    _at_launcher = True
    #: The current frame is an APP-EXIT frame: ``managed_update`` saw a non-None
    #: app result, one frame before the hard reset an app exit performs. Reset
    #: every ``poll``. A parked establishment may not advance or SEND into a
    #: reset (spec §5.3(e) exit-frame item). The launcher's own non-None result
    #: is a same-boot handoff, not a reset, and is excluded in the helper below.
    _exit_frame = False
    #: One-shot latch for the fail-open unknown-context diagnostic (#22). The
    #: whole in-app freeze-avoidance rests on an UNENFORCED convention -- every
    #: app keeps its cwd under ``/system/apps/<slug>`` so ``current_app`` can tell
    #: launcher from app. Resolving ``None`` fails OPEN (a rare in-app hitch beats
    #: a dead badge), which silently re-opens the freeze; on device every
    #: ``run()`` is under ``/system/apps``, so a None context that KNOWS its cwd
    #: is a real app that chdir'd out of its root. Emit once so a serial reader
    #: sees it; the AST guard is the actual enforcement. Class default so cold OFF
    #: never materialises it.
    _unknown_context_warned = False

    def __init__(self, backend_factory, preference_path=network_preference.DEFAULT_PATH,
                 ledger_path=command_ledger.DEFAULT_PATH, caselights=None,
                 event_sink=None, push_factory=None,
                 card_state_path=None, card_refresh_path=None,
                 open_app_path=None, notice_path=None, listdir=None, getcwd=None,
                 backlight=None, badge_api=None, schedule_path=None,
                 epoch_clock=None, score_path=None,
                 schedule_cache_path=None, reset=None, rand01=None,
                 ticks_ms=None, sleep_note=None):
        if not callable(backend_factory):
            raise ValueError("backend_factory must be callable")
        if push_factory is not None and not callable(push_factory):
            raise ValueError("push_factory must be callable")
        self._backend_factory = backend_factory
        # None means "the contract's own default", resolved at CALL time inside
        # `setup_state`. Passing the literal here would put setup's path
        # in a second place, which is the drift this card exists to prevent.
        self._card_state_path = card_state_path
        self._card_refresh_path = card_refresh_path
        self._open_app_path = open_app_path
        self._notice_path = notice_path
        # Injected so the fixtures can be a real filesystem-free roster and a
        # real "which app is open" answer. None means the device's own os.
        self._listdir = listdir
        self._getcwd = getcwd
        self._open_target = None
        self._open_force = False
        self._reset = reset or _device_reset
        # THE CADENCE PHASES' ONLY RANDOM SOURCE (CX-8). Injectable so a fixture
        # can make a phase deterministic; drawn a handful of times per boot and
        # never per frame.
        self._rand01 = rand01 or _default_rand01
        # The running light program, or None. Held in RAM ONLY, deliberately: a
        # light show is a MOMENT, and a moment that survived a reset would replay
        # itself minutes later to a wearer who had forgotten it. The internal
        # notice->Nametag handoff is durable only long enough to cross its forced
        # reset; the notice itself is consumed once and never becomes campaign
        # state.
        self._lights = None
        self._lights_started = 0
        self._lights_stepped_frame = None
        # The running FLEET EFFECT, in its own slot for the reason
        # `effect_library.EffectPlayer` gives: it drives two channels and answers
        # a bool, where a `Program` drives one and answers a level, so sharing the
        # slot above would put a type switch in the frame pump. RAM-only for the
        # same reason as the lights program -- a show is a moment.
        self._effect = None
        # THE REST OF THE RECEIVED ARRAY, pre-built before frame zero. Keeping
        # it on the badge is what lets a flaky connection lose the socket after
        # delivery without stranding half a show; validating every player first
        # also prevents a malformed later cue from starting a partial show.
        self._effect_queue = None
        self._effect_started = 0
        self._effect_stepped_frame = None
        # RESERVED NOW SO EVERY STOP EDGE HAS ONE TOTAL CLEANUP PATH BEFORE
        # Live lands. The socket callback will eventually capture an unvalidated
        # candidate and the frame pump will hold one validated cue; neither may
        # survive OFF, revocation or a backend rebuild while an older Reliable
        # effect is correctly restored. Keeping the two RAM-only slots beside the
        # player makes that lifecycle true before transport code can depend on it.
        self._live_candidate = None
        self._live_pending = None
        # -- THE BROADCAST LANE (2026-08-29) --------------------------------
        #
        # VALIDATED ACTIONS WAITING FOR A FRAME. `pushlink` calls the sink from
        # inside layer 2's drain loop, which is inside a RENDERED FRAME and which
        # drains up to `FLEET_DRAIN_MAX` WS frames per call -- so applying in the
        # sink would put four appliers on one frame and hand CX-10's one-chore
        # budget to whichever arrived first. The sink therefore only ENQUEUES;
        # `_pump_broadcast_actions` applies exactly one per frame, under the
        # chore budget, like every other expensive thing this class does.
        #
        # RAM-ONLY AND BOUNDED, and both are one argument: a moment queued for
        # longer than a few frames is a light show that already looks wrong, so
        # there is nothing here worth surviving a reset and nothing worth a deep
        # queue. See :data:`BROADCAST_ACTION_MAX`.
        self._actions = []
        # ACTION IDS ALREADY ACCEPTED THIS BOOT, newest last, capped at
        # :data:`ACTION_MEMORY`. THE EXACTLY-ONCE GUARD, and it replaces
        # `command_ledger`'s -- which was durable because an unacked command was
        # REDELIVERED across boots. A broadcast is never redelivered, so there is
        # nothing for a durable ledger to protect against and a flash write per
        # show would be pure cost. What DOES happen is duplicate ARRIVAL: one
        # publish can be drained more than once inside one frame, and without
        # this a single fleet show plays twice on one badge and once on its
        # neighbour.
        self._action_ids = []
        # RECEIPTS WAITING OUT THEIR JITTER: `[due_tick, action_id, result,
        # tries]`, oldest first. The delay is held HERE rather than in the
        # transport because `polltransport.queue_errand` has no notion of one and
        # must not grow one for this: an errand queue that can hold work back is
        # a queue that can starve the heartbeat.
        self._receipts = []
        # Report material for a lane whose entire failure mode is silence.
        self.actions_applied = 0
        self.actions_failed = 0
        self.actions_dropped = 0
        #: DUPLICATE ARRIVALS CORRECTLY SUPPRESSED -- a HEALTH number, not an
        #: error one. A shared fleet topic delivers the same publish more than
        #: once by construction, so a nonzero value here is the de-duplication
        #: working. It is a counter rather than a line because the ordinary case
        #: runs up to four times per RENDERED frame; see `_on_broadcast_action`.
        self.actions_duplicate = 0
        #: One serial line per boot for the whole broadcast lane, then silence.
        self._action_anomaly_noted = False
        self.receipts_queued = 0
        self.receipts_dropped = 0
        self._backlight = backlight
        # The `badge` object, for the battery gauge `report_state` samples. The
        # caselights callable stays a separate argument because Card PW's
        # fixtures inject it directly and nothing may break that.
        self._badge_api = badge_api
        #: THE DEFERRED POWER ACTION, or None.  RAM-only and one at a time; see
        #: `_arm_power_action` for why it may never be durable.
        self._power = None
        #: The note painter, injectable so the host suite can gate the ORDER and
        #: the COPY without a panel.  See `_draw_sleep_note`.
        self._sleep_note = sleep_note or _draw_sleep_note
        self._boot_session_id = None
        self._epoch_clock = epoch_clock
        # `schedule_path` remains an accepted no-op argument for old host probes.
        # The command table and its future-fire contract were deleted in the
        # rebuild, so reading that file would revive offline catch-up that the
        # owner explicitly cut. Production never passes this compatibility seam.
        _ = schedule_path
        self._score_path = score_path
        self._scorebox = None
        self._score_inflight = None
        #: WHEN THAT LATCH WAS ARMED, so it cannot outlive the errand it names.
        #: The latch is set BEFORE the request is handed over and was cleared by
        #: the response sink alone, so one lost response stopped the drain for
        #: the whole boot; :data:`SCORE_INFLIGHT_MAX_MS` and the socket check in
        #: `_release_score_latch` are the two ways it comes back.
        self._score_inflight_at = None
        #: WHY THE DRAIN IS NOT DRAINING, latched so the answer is printed on the
        #: TRANSITION rather than on every rendered frame. ``None`` means "not
        #: stalled", and every other value is one word from `_pump_scores`'s own
        #: closed set. See `_score_stalled`.
        self._score_stall = None
        #: THE OPERATOR'S LEADERBOARD LEVER (`fleet_settings.scores_enabled`).
        #: DEFAULTS TO TRUE AND FAILS OPEN for the reason `parse_policy_row`
        #: argues at length: a badge that has not managed to read the row, or
        #: read one this firmware could not parse, must behave like a badge at an
        #: event with the lever ON. It gates the DRAIN only -- `scorebox.record`
        #: never consults it -- so an operator's switch can delay a wearer's
        #: score but can never lose it. See `_apply_settings_scores`.
        self._scores_enabled = True
        #: WHETHER THE SERVER IS CURRENTLY REFUSING POSTS, latched so the line is
        #: printed on the transition rather than once per refused round trip. It
        #: is a BOOLEAN and not a count: nothing is discarded at any number, so
        #: there is nothing for a counter to decide. It replaced
        #: `_score_attempt_key`/`_score_attempts`, which existed only to reach
        #: `scorebox.MAX_ATTEMPTS` and DELETE a wearer's score.
        #: See `_on_score_posted`.
        self._score_refused = False
        # A DELIVERED SCORE IS RETIRED ON A LATER FRAME. The sink that hears
        # "posted" only remembers the `(game, play_number, score)` triple; the
        # whole-file read and the atomic swap that retiring costs are this
        # service's one expensive sub-task for some later frame. See
        # `_pump_scores`.
        self._score_retire = None
        #: THE WEARER'S NAME AS OF THIS BOOT, reported UP on every heartbeat
        #: (owner ruling 2026-08-28: the badge owns its name; nobody owns its
        #: skin). ``False`` means "not read yet" and ``""`` means "read, and there
        #: is none" -- the two are different because a frame that could not claim
        #: the budget must WAIT rather than report an unattributed one.
        #: See `_wearer_name`.
        self._wearer_name_cached = False
        self._schedule_cache_path = schedule_cache_path
        self._schedule_box = None
        self._schedule_inflight = False
        #: WHEN THAT LATCH WAS ARMED, so it cannot outlive the errand it names.
        #: Same defect, same shape and same fix as `_score_inflight_at`; see
        #: :data:`SCHEDULE_INFLIGHT_MAX_MS` and `_release_schedule_latch`.
        self._schedule_inflight_at = None
        #: WHICH REQUEST THE LATCH IS ABOUT, bumped by every release. Once a
        #: latch can be taken back, two version checks or two page reads can be
        #: outstanding at once, and a sink that assumed it was the only one would
        #: let an abandoned page append its rows a SECOND time or abandon a fetch
        #: it does not belong to. Each sink carries the generation it was queued
        #: under and drops a response that does not match. See `_on_schedule_page`.
        self._schedule_gen = 0
        self._schedule_due = None
        self._schedule_version = None
        # THE CACHED VERSION LIVES IN RAM once it has been read, because the
        # cheap path's whole claim is that an unchanged schedule touches no
        # filesystem. `False` means "not read from disk yet"; `None` is a real
        # answer meaning "this badge holds no schedule".
        self._schedule_cached = False
        # None means "not fetching"; a list means a paged fetch is in progress.
        self._schedule_pages = None
        self._schedule_offset = 0
        # The page a sink handed over, still un-normalised, and how far through
        # it `_schedule_parse_step` has got. `SCHEDULE_PARSE_ROWS` rows a frame.
        self._schedule_raw = None
        self._schedule_raw_at = 0
        self._schedule_received = 0
        self._schedule_commit = False
        # Schedule v2 is an APP-OPEN REQUEST, not a service cadence.  The app
        # parks one sink here before association and this service queues one GET
        # when its existing socket is ready.  ``done`` is boot-local because an
        # app exit resets the badge; no timer or Realtime path can re-arm it.
        self._schedule_v2_requested = False
        self._schedule_v2_inflight = False
        #: WHEN THE SNAPSHOT'S LATCH WAS ARMED. The app parks ONE sink and
        #: `_on_schedule_v2` sets ``done`` whatever the answer, so a latch that
        #: outlives its errand costs the wearer the whole refresh for that app
        #: open with nothing on screen to say so. See `_release_schedule_latch`.
        self._schedule_v2_inflight_at = None
        #: WHICH SNAPSHOT REQUEST THE LATCH IS ABOUT, bumped by every release.
        #: A released request can still answer -- `_safe_close` leaves the errand
        #: in `polltransport`'s queue -- and the one thing that response must not
        #: be allowed to do is retire the app's single parked sink on behalf of a
        #: request the service has already re-offered. See `_on_schedule_v2`.
        self._schedule_v2_gen = 0
        self._schedule_v2_done = False
        self._schedule_v2_have = None
        self._schedule_v2_sink = None
        # A RESPONSE SINK MAY RUN INSIDE ``backend.poll``. The score and
        # schedule continuations below deliberately defer their file/parse work,
        # but merely putting that work after the sink is not enough when this
        # very method calls the pumps again later in the SAME rendered frame.
        # A sink raises this one-frame barrier; the next call clears it before
        # polling, so the captured continuation becomes eligible only after the
        # response frame has reached the panel.
        self._response_continuation = False
        # ONE EXPENSIVE SUB-TASK PER FRAME, and this is the whole budget: every
        # sub-task that reads a file, swaps one or normalises a batch of rows
        # claims it first and the rest wait for the next frame.
        self._chore_spent = False
        #: How many expensive sub-tasks this service has run. Read by
        #: `ft_b_device_probe.frame_gate` so a frame over the gate can be
        #: attributed to badge code or to the socket underneath it.
        self.chores = 0
        # SNAPSHOT THE BUILD-TIME SELECTION ONCE. NB-0's child constructors will
        # take this value, never the module again, so one boot cannot construct
        # an OFF poll path and an ON push path under a host that mutates globals.
        self._nb_connect_enabled = NB_CONNECT_ENABLED
        self._push_factory = push_factory
        self._push = None
        self._pending_moment = None
        self._quiesced = False
        self._quiesce_reason = None
        #: WHETHER THE RADIO HAS BEEN SEEN UP, so the doorbell's gate can find the
        #: `wifi_lost` EDGE from outside `DeviceBackend.poll` (Lane H). `False`
        #: to start deliberately: a badge that has never associated has no socket
        #: to release, so the first frames are not an edge, they are a badge that
        #: is still associating -- and nothing may be attempted into that either.
        self._radio_seen_online = False
        if self._nb_connect_enabled:
            #: MONOTONIC ASSOCIATION EPOCH FOR PARKED OWNERS. Every observed
            #: edge changes it; a held WSS attempt captures the current value
            #: and must still match before any later event-loop turn can hand
            #: the socket off. Cold OFF retains only the immutable class zero.
            self._radio_generation = 0
            self._push_nb_contract_validated = False
        #: DID THE POLL TRANSPORT CONNECT IN THIS FRAME? (Lane H.) Set once per
        #: `poll`, read by `_service_push` at the end of the same frame, so the
        #: two transports cannot put two connects in one rendered frame.
        self._connect_frame = False
        # WHAT THE DOORBELL PUMP COSTS A FRAME. Six integers, rolled up every
        # PUSH_PUMP_ROLLUP pumps; the first three reset per window, the last
        # three are the session totals a snapshot and a probe read.
        self._push_pumps = 0
        self._push_busy_ms = 0
        self._push_peak_ms = 0
        self._push_pumps_total = 0
        self._push_busy_total_ms = 0
        self._push_peak_session_ms = 0
        self._preference_path = preference_path
        self._ledger_path = ledger_path
        self._caselights = caselights or (lambda _level: None)
        # Badgeware accepts either one shared brightness or four logical case
        # channels.  Host shims written before spatial shows often accept only
        # one; latch that discovery so a compatibility TypeError is paid once,
        # not on every light frame.
        self._caselights_variadic = None
        self._event_sink = event_sink
        # ONE READ FOR BOTH SWITCHES (CX-10 sub-claim 1). This used to be
        # `load()` then `load_push()`, and each of those calls `load_record`, so
        # the preference file was opened and DECODED TWICE before the launcher's
        # first frame -- two of the constructor's three decodes for one 45-byte
        # record. An ABSENT production record defaults both radio and push ON;
        # only a PRESENT-BUT-UNUSABLE record splits radio OFF from push ON. The
        # distinction lives in `enabled_from`/`push_from`, not at this seam.
        preference = network_preference.load_record(preference_path)
        self._enabled = network_preference.enabled_from(preference)
        # DEFAULT ON, with automatic demotion (owner scope addition 2026-08-21).
        self._push_enabled = network_preference.push_from(preference)
        self._push_control = None
        self._policy = None
        #: WHEN THE FLEET-SETTINGS READ AND THE HEARTBEAT ARE NEXT DUE. Both are
        #: owned HERE and in exactly one place, which is CX-8's lesson learned
        #: twice: the steering read used to keep a due time on the `PollLoop` and
        #: a mirror of it here, and the two disagreed the moment a read FAILED.
        #:
        #: `None` MEANS "NOT PHASED YET" AND IS RE-ARMED ON EVERY DISCONNECT, so a
        #: badge that spent ten minutes off the air comes back owing ONE of each
        #: rather than ten -- and pays the per-badge phase again, which is what
        #: keeps ~1,000 badges reconnecting after an AP blip from arriving together.
        #: RAM-only: a cadence is not a thing to carry across a reset, since
        #: nothing durable could tell a boot the interval had been served.
        self._settings_due = None
        self._heartbeat_due = None
        #: THE LAST VALUE THIS BADGE ACTED ON, PER LEVER -- the whole of the
        #: idempotence rule in `_apply_settings`. The settings read is a CATCH-UP
        #: mechanism, so it re-delivers the same answer every five minutes for the
        #: length of the event; without this, that is ~96 backlight writes and ~96
        #: sleeps per badge per day. RAM-only, deliberately: a durable copy would
        #: survive the reboot that waking IS.
        self._settings_applied = {}
        self._backend = None
        self._defer_once = self._enabled
        self._revoked = False
        #: Has this service already printed its boot-wide `revoked`? The latch
        #: above is cleared for every slow re-probe (§8.1), so it can no
        #: longer double as "have we said this".
        self._revoked_announced = False
        #: The last cause `_note_push_cause` printed, so the line follows the
        #: EDGE rather than the level. ``False`` rather than ``None`` because
        #: ``None`` is a real cause value ("nothing to explain") and the first
        #: frame must be able to print it.
        self._push_cause_seen = False
        #: The cause before the current one, so the observer problem in
        #: :meth:`push_cause_previous` has an answer. RAM-only.
        self._push_cause_before = None
        #: WHEN that latch was taken, so it can EXPIRE. See
        #: :data:`PUSH_CAUSE_LATCH_MS` for why an unaged latch is a liability and
        #: :meth:`push_cause_previous` for why the expiry lives on the READ.
        self._push_cause_before_at = None
        self._active = False
        self._ledger = command_ledger.load(ledger_path)
        #: THE RAM LEDGER HOLDS AN ACK THE FLASH DOES NOT (CX-7). `remember` is a
        #: pure function and `save` is the only call that can fail, so this flag
        #: is the whole difference between "exactly-once across a reset" and
        #: "exactly-once within this boot".
        self._ledger_dirty = False
        #: How many durable ledger writes this boot lost. Reported in
        #: `snapshot()`; it is the only durable trace of a failed swap, because
        #: the diagnostic below is emitted at most ONCE.
        self.ledger_save_failures = 0
        self._ledger_retries = 0
        self._ledger_retry_at = None
        self._ledger_diagnosed = False
        self._retry_at = None
        self._failures = 0
        self.last_error = None
        # Command callbacks run inside ``backend.poll(now)``. Keep their
        # deadlines in that same clock domain: a fresh `_ticks_ms()` happens to
        # match on hardware but disagrees with the deterministic kill-test clock.
        self._now = _ticks_ms()
        #: THE MILLISECOND TICK, AS A SEAM (2026-08-24). The comment above is the
        #: reason `self._now` exists and it is still right about the DOMAIN -- but
        #: it was read as "never take a fresh tick", and one deadline genuinely
        #: needs one. `self._now` is the tick at the TOP of `poll`, and a command
        #: callback can run many seconds later inside the same call: the 2026-08-24
        #: device session's command rode a frame that had also paid an 8,852 ms
        #: blocking open, so `self._now + 5000` was already in the PAST and the
        #: ledger ladder's first rung fired 169 ms later instead of ~5 s
        #: (`benchmark/results/reports/2026-08-24-lane-c-install.md` §4a).
        #:
        #: A SEAM RATHER THAN A BARE `_ticks_ms()`, which is what answers the
        #: objection above: on hardware this IS `time.ticks_ms` and `poll()` is
        #: called with no argument, so the two agree exactly; a deterministic test
        #: hands in the same virtual clock it drives `poll` with, so they agree
        #: there too. Every arithmetic on it goes through `_ticks_add`/
        #: `_ticks_diff`, so it is wrap-safe on the device's 30-bit tick.
        self._ticks_ms = ticks_ms or _ticks_ms

    # THE GENERIC OUTBOUND PIPE (`telemetry.py`) WAS DELETED ON 2026-08-29, and
    # the reason is worth one paragraph because the feature was a good idea.
    #
    # It existed so the badge's outbound vocabulary would stop being frozen: a
    # row was `{kind, payload}`, so the next thing anyone wanted a badge to
    # report was SQL rather than a firmware change on a gang-cloned image. What
    # killed it is that its RLS was `badge_id = grants.whoami()` -- the JWT
    # subject -- which under one shared fleet token names the FLEET and not a
    # badge, so every row it ever sent was misattributed. The rebuild drops
    # `public.telemetry` outright, and a pump aimed at a dropped table is not a
    # dead feature, it is a live one that burns an errand slot every frame and
    # answers PGRST205 for ever.
    #
    # ITS ONE PRODUCER WAS `_report_boot` (a wake-reason row from the
    # constructor) and its one genuinely valuable piece was the wearer-name
    # reader, which is HARVESTED rather than deleted: see `_wearer_name` below,
    # now feeding `POST /rest/v1/badges` instead of a diagnostic row.

    @property
    def enabled(self):
        return self._enabled

    @property
    def state(self):
        if not self._enabled:
            return OFF
        if self._revoked:
            return REVOKED
        if self._retry_at is not None:
            return BACKOFF
        if self._backend is None:
            return CONNECTING
        return getattr(self._backend, "state", DISCONNECTED)

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        try:
            network_preference.save(enabled, self._preference_path)
        except Exception as exc:
            # A full/read-only LittleFS must not turn a Settings button into an
            # app reset. The old state remains authoritative and the marker is
            # credential-free.
            self.last_error = _error_text(exc)
            self._emit("preference_failed", error=self.last_error)
            return self._enabled
        if enabled == self._enabled:
            return self._enabled
        if not enabled:
            # THE DURABLE HALF IS THE `save` ABOVE; everything the radio itself
            # has to be told is `_go_offline`, which the TRANSIENT
            # `set_networking` lever reuses without the save.
            self._go_offline("preference")
        else:
            self._clear_cause_latch()
            self._enabled = enabled
            self._emit("preference", enabled=enabled)
            if not self._revoked:
                # The Settings frame showing CONNECTING must reach the panel
                # before any DNS/TLS work begins.  The wrapper consumes this one
                # deferral.
                self._defer_once = True
        return self._enabled

    def _go_offline(self, event):
        """Radio DOWN NOW, with no opinion about flash.  The teardown half.

        EXTRACTED FROM `set_enabled` IN 2026-08-28 AND BYTE-FOR-BYTE THE SAME
        SEQUENCE, because the fleet-battery lever needs a networking-off that is
        NOT written to `/state`. `set_enabled` always persists -- boot reads the
        preference back through `network_preference.load_record` -- and the owner
        asked for temporary and permanent to be different commands, with
        temporary the default. Temporary can only mean "never written in the
        first place": a badge with its radio down is not polling, so a
        re-enable command can never arrive, and scheduling one for later would be
        a promise this transport cannot keep.

        ``event`` NAMES THE CAUSE ON THE WIRE-LOG, and the two words mean
        different things to an operator reading serial: ``preference`` is the
        durable wearer/admin switch, ``network_suspended`` is the transient one
        that ends at the next reset. They are deliberately not the same word.

        THE ORDER IS UNCHANGED AND EACH STEP KEEPS ITS ORIGINAL REASON.
        """

        if not self._enabled:
            # Already down. Every step below is idempotent, but re-emitting the
            # event would tell an operator the radio went off twice.
            return False
        # BEFORE THE FLAG FLIPS, because the flip is what makes the cause
        # unknowable: `push_cause` reads `_enabled` first and answers None from
        # here on, and `poll` stops reaching `_note_push_cause` entirely. This is
        # the last instant the answer exists. See `_latch_cause_at_switch`.
        self._latch_cause_at_switch()
        self._enabled = False
        self._emit(event, enabled=False)
        self._retry_at = None
        self._failures = 0
        # RESTORE BEFORE FINAL DARK. A glyph can finish with lit case LEDs;
        # if OFF darkened first and interrupt restored second, switching the
        # radio off could turn those LEDs back on. Backend stop repeats this
        # total helper harmlessly because it is also a standalone stop edge.
        self._clear_remote_effects()
        self._stop_backend()   # closes the doorbell's socket with it
        # A RUNNING SHOW STOPS WITH THE RADIO. `_pump_effect` runs before the
        # `_enabled` check in `poll`, so a light program left set here would
        # keep driving the LEDs after the wearer switched networking off --
        # the one effect in this module that outlives its own cause.
        self._lights = None
        self._caselights(0)
        # AND A DELIVERED SCORE IS RETIRED BEFORE THE RADIO GOES, because its
        # retire is a DEFERRED sub-task and `poll` returns before the drain
        # once networking is off. Left pending, the row would be reposted on
        # the next boot -- harmless (the RPC is idempotent) and still wrong.
        # Not a frame: this is a wearer or probe action, and it is the same
        # moment that already writes the preference file.
        self._chore_spent = False
        self._retire_score()
        return True

    @property
    def push(self):
        """The push service, or ``None`` while polling is the only transport."""
        return self._push

    @property
    def push_enabled(self):
        """The durable wearer preference, not whatever the socket is doing."""
        return self._push_enabled

    def push_mode(self):
        """The LIVE push mode, read back from the transport (the PW rule).

        Before a session exists there is nothing to read back, so the answer is
        derived from the two preferences and says "trying" rather than "on" —
        the one thing this may never do is claim a doorbell the badge has not
        got.
        """
        if self._push is not None:
            return self._push.mode(self._enabled)
        if not self._enabled:
            return PUSH_MODE_NETWORK_OFF
        if not self._push_enabled:
            return PUSH_MODE_POLLING
        return PUSH_MODE_TRYING

    def push_cause(self):
        """WHY push is not carrying, as one word from :data:`PUSH_CAUSES`.

        ``None`` when there is nothing to explain -- push is live, or the wearer
        or the venue turned it off, and in both of those cases `push_mode()`
        already says the whole truth.

        **THIS ``None`` IS OVERLOADED AND IT COST A FEATURE ITS ONLY READER.** It
        means BOTH "nothing is wrong" (joined) and "you switched it off", and those
        two want opposite treatment from a panel: the first should suppress a past
        line, the second is exactly when a past line is the only thing there is to
        read. A consumer that gated its past line on `cause() is not None` was
        therefore dead on every off screen -- the value `_latch_cause_at_switch`
        takes at the press had zero readers on any path, and both lanes were green.
        **The "is there something to explain" signal is not this method's return
        value; it is :meth:`push_cause_previous`'s own presence**, which already
        encodes the distinction because a join CLEARS the latch and a switch KEEPS
        it. Read that, and do not re-derive it from here.

        THE ORDER IS MOST-SPECIFIC-FIRST and each rung is a state a reader could
        otherwise not distinguish. Read from the transport, never from a
        preference: the Card PW binding rule applies to the cause exactly as it
        applies to the mode.
        """

        if not self._enabled:
            return None
        if not self._push_enabled:
            return None
        push = self._push
        if push is None:
            # NOTHING WAS EVER BUILT. Distinguishing the two reasons is the point:
            # placement withholding every moment inside a non-opted-in app is a
            # recoverable state a wearer fixes by walking to the launcher, and it
            # is what hid a real bug for a whole session.
            if not self._placement_allows_establishment():
                return CAUSE_PLACEMENT
            return CAUSE_NOT_STARTED
        link = getattr(push, "link", None)
        if link is None:
            return CAUSE_NOT_STARTED
        policy = getattr(link, "policy", None)
        if policy is not None:
            if getattr(policy, "revoked", False):
                return CAUSE_REFUSED
            if getattr(policy, "remote_disabled", False):
                # The venue's own kill switch. `push_mode()` already reads
                # `blocked`, so there is nothing left for a cause to add.
                return None
            if getattr(link, "joined", False):
                return None
            if getattr(policy, "demoted", False):
                return CAUSE_RETRY_LATER
        if getattr(link, "_establishing", False):
            return CAUSE_ESTABLISHING
        if not self._placement_allows_establishment():
            return CAUSE_PLACEMENT
        if not self._radio_seen_online:
            return CAUSE_NO_SIGNAL
        error = getattr(link, "last_error", None)
        if isinstance(error, str) and error:
            # ONE BIT OUT OF THE SERVER'S STRING AND NOTHING ELSE. The prefix
            # test is the same one `_note_revoked` uses; the text itself may not
            # reach a screen, because it carries glyphs this build was never
            # baked with.
            try:
                import pushlink

                refused = pushlink.is_revocation_reason(error)
            except Exception:
                refused = False
            return CAUSE_REFUSED if refused else CAUSE_SERVER_BUSY
        return CAUSE_WAITING

    def push_cause_previous(self):
        """The cause BEFORE the current one, or ``None``.

        **THE OBSERVER PROBLEM, AND IT IS NOT A CURIOSITY -- IT HID THE 2026-08-26
        ROOT CAUSE FOR A WHOLE SESSION.** `CAUSE_PLACEMENT` is the state a wearer
        most needs explained, and it is the one the panel can never show: the
        Settings screen that would display it calls `set_active(True)` while it is
        open, so OPENING THE SCREEN GRANTS THE PLACEMENT the screen would have
        reported. Every diagnostic on this badge shares that shape to some degree
        -- looking costs a frame, a moment, or in this case the very condition
        being asked about.

        THE PATH IS A NAVIGATION INSIDE SETTINGS, NOT A JOURNEY BETWEEN APPS, and
        the distinction is the difference between a reachable feature and a
        justification that crosses a `machine.reset()`. `settings/__init__.py` calls
        `set_active` with `screen in (NETWORK, PAIR, PUSH)`, so the Settings ROOT
        screen withholds by placement exactly like any non-opted-in app; stepping
        from there to Updates is what grants the placement and fills this latch, all
        inside one boot. The obvious-sounding story -- a wearer in the nametag app
        who walks to Settings -- CANNOT happen: every trip home is
        `machine.reset()`, so that journey ends the boot and this value with it.

        So the runtime latches the previous cause and the UI reads THAT. "Why is
        push not carrying" is answerable from the panel; "why did it fail BEFORE I
        came to look" is the question an operator actually has, and it needs a
        value that survives the act of asking.

        CLEARED THE MOMENT PUSH IS LIVE, because a latched reason beside a working
        doorbell is worse than no reason: it is a true fact about the past
        presented where a reader will take it for the present. RAM-only, like
        every other connectivity fact -- nothing about a failure may reach flash
        (the England-boot rule).

        **AND IT EXPIRES** after :data:`PUSH_CAUSE_LATCH_MS`, which is the same
        argument applied to age instead of to state: a latch with no age is a true
        fact about the past with no indication of HOW FAR past.

        THE EXPIRY IS ON THE READ AND IT HAS TO BE. The obvious home for it is
        `_note_push_cause`, which runs every frame -- but `poll()` RETURNS ABOVE
        that call when networking is off, and the radio-off branch is precisely
        the one that keeps a latch indefinitely. An expiry in the emitter would
        therefore be dead code in the only case that needs it. Expiring here also
        means the bound holds for a caller that never polls at all, which is what
        a Settings screen on a disabled badge is.
        """

        if self._push_cause_before is None:
            return None
        taken = self._push_cause_before_at
        if taken is not None and _ticks_diff(
                self._ticks_ms(), taken) >= PUSH_CAUSE_LATCH_MS:
            # DROPPED, not merely hidden. Keeping the value while refusing to
            # return it would leave a stale cause reachable from a snapshot or a
            # future reader that forgets to age it.
            self._push_cause_before = None
            self._push_cause_before_at = None
            return None
        return self._push_cause_before

    def push_diagnostics(self):
        """The narrowed push snapshot for a panel, or ``None``.

        THE VALUES ALREADY EXISTED; THE PATH TO A READER DID NOT. See
        :data:`PUSH_DIAGNOSTIC_KEYS` for the three 2026-08-27 incidents that
        each cost an hour because a computed value only ever reached a serial
        port with nothing attached to it. This method adds no counter, no state
        and no accounting -- it is a projection of `PushLink.snapshot()`, which
        already merges `PushPolicy.snapshot()` into itself.

        ``None`` IS AN ORDINARY ANSWER AND MEANS "THIS BADGE CANNOT TELL YOU",
        never "everything is fine". A badge whose `/system/main.py` installed the
        polling baseline with no push factory has no doorbell to describe, and a
        boot that has not built one yet has nothing to snapshot. The caller draws
        an honest "no details" line for it; it may not draw zeroes, because a
        zeroed counter is a measurement and this is the absence of one.

        DUCK-TYPED AND TOTAL, because the object under it is not always the
        product's. `pushlink.PushService` is what ships, but the fixtures, the
        kill-test and the browser lane all pass their own stand-ins through
        `_push_factory`, and one of them predating `snapshot()` must degrade to
        `None` rather than raise: the only consumer is a Settings draw path,
        where an exception reaches `fatal_error` and `machine.reset()`s the
        badge -- every badge, every frame, for ever. The `isinstance` check is
        the same layer for the same reason: a stand-in returning a list would
        otherwise reach `record[key]` as an index.

        A FRESH DICT PER CALL, WHICH IS WHY THIS IS NOT ON A PER-FRAME PATH.
        `PushLink.snapshot()` builds a record of its own, so a caller polling
        this every frame would allocate twice a frame for values that change on
        the timescale of a session. It is built for a screen a wearer OPENS.

        THE FLAT RESULT IS PART OF THE CONTRACT. Layer-2 keys named in
        :data:`PUSH_DIAGNOSTIC_CLIENT_KEYS` are LIFTED out of the nested
        `client` record to the top level rather than forwarded as a sub-dict,
        so the panel keeps one shape to read and the ~14 unpriced layer-2
        strings stay off it. A layer-2 name and a `PushLink` name would collide
        here; none do today, and the lift is deliberately LAST so a future
        collision resolves in layer 2's favour -- the layer-2 counter is the
        more specific fact, and it is the one a caller asking for it wants.
        """

        push = self._push
        if push is None:
            return None
        reader = getattr(push, "snapshot", None)
        if not callable(reader):
            return None
        try:
            record = reader()
        except Exception:  # noqa: BLE001 - a reset is the alternative
            return None
        if not isinstance(record, dict):
            return None
        out = {}
        for key in PUSH_DIAGNOSTIC_KEYS:
            # ABSENT KEYS ARE OMITTED, NOT DEFAULTED. `PushLink.snapshot`'s
            # held-strategy block is already conditional, so "this build does
            # not publish that" is a real case, and a `0` invented here would be
            # a count the reader would believe.
            if key in record:
                out[key] = record[key]
        # THE LAYER-2 LIFT, and it is guarded the same way the record above is.
        # `PushLink.snapshot()` writes `client` ONLY once a client exists -- it
        # is built lazily on the first connect ATTEMPT -- so a badge that has
        # never tried to open a socket omits these keys entirely and the panel
        # draws `?`. That is the honest answer: a `0` there would say "a socket
        # existed and saw no binary frames", which is a measurement nobody took
        # and the exact wrong reading for the split this counter is for.
        client = record.get("client")
        if isinstance(client, dict):
            for key in PUSH_DIAGNOSTIC_CLIENT_KEYS:
                if key in client:
                    out[key] = client[key]
        return out

    def clock_diagnostics(self):
        """The wall-clock facts for a panel, as :data:`CLOCK_DIAGNOSTIC_KEYS`.

        THE VALUES ALREADY EXISTED; THE PATH TO A READER DID NOT -- the same
        sentence :meth:`push_diagnostics` was written under, for a worse defect.
        See :data:`CLOCK_DIAGNOSTIC_KEYS` for the brick this answers: a badge
        with no plausible clock cannot finish `_build_loop`, so it never gets a
        doorbell, so the Diagnostics screen draws the SAME "no push details" a
        badge that has not tried yet draws. That is the one state at the venue
        an operator cannot fix without knowing about, and the badge's own panel
        is the only channel there is (no USB, battery, handed out).

        **IT HANGS OFF THE NETWORK CONTROL AND NOT OFF `_PushControl`, AND THAT
        IS THE WHOLE POINT.** `push_control()` returns `None` on a badge whose
        `/system/main.py` installed the polling baseline -- and the failure being
        reported is precisely "there is no doorbell", so a clock accessor
        reachable only through the doorbell's face would be unreadable in every
        case it exists for. Settings is handed this service as its NETWORK
        control, so this method is directly reachable there.

        NEVER `None`, WHICH IS THE OPPOSITE OF :meth:`push_diagnostics`, and the
        asymmetry is real rather than an inconsistency: a doorbell may genuinely
        not exist, but a clock always does -- `_epoch()` reads one and gates it
        whether or not a radio, a backend or a loop was ever built. "This badge
        cannot tell you" is therefore a statement about the ACCESSOR being
        absent (a `/system/lib` older than this method), which the caller's own
        `getattr` guard already answers; it is not a state this can be in.

        A FRESH DICT PER CALL, so like `push_diagnostics` this belongs on a
        screen a wearer opens and not on a frame path.

        TOTAL, because the only consumer is a Settings draw path where a raise
        is `fatal_error` -> `machine.reset()`, every frame, for ever. The backend
        read is duck-typed for the same reason every other backend read here is:
        fixtures, probes and the kill-test all pass their own stand-ins.
        """

        # `_epoch()` IS THE GATE THE TRANSPORT ITSELF USES, reused rather than
        # re-derived, so the panel cannot say "plausible" about a clock the TLS
        # path is about to refuse. It answers None both for an implausible clock
        # and for a clock it could not read at all -- the second is a
        # `time.time()` that raised, which on this hardware is the powman timer
        # being unreadable, and reporting that as "no usable clock" is true.
        record = {"plausible": self._epoch() is not None,
                  "synced": False, "reason": None}
        backend = self._backend
        reader = getattr(backend, "clock_snapshot", None)
        if not callable(reader):
            # NO BACKEND YET (cold OFF, or before the first radio start) or one
            # that predates the latch. The clock question is still answered --
            # `plausible` above needs nothing but the clock -- and the two sync
            # fields keep their honest defaults: nothing has synced, and there is
            # no reason on record because nothing has tried.
            return record
        try:
            snapshot = reader()
        except Exception:  # noqa: BLE001 - a reset is the alternative
            return record
        if not isinstance(snapshot, dict):
            return record
        record["synced"] = bool(snapshot.get("synced"))
        reason = snapshot.get("reason")
        # A STRING OR NOTHING. `clock_boot`'s reasons are its own literals and a
        # `_error_text` line; anything else is a stand-in, and a formatted repr
        # on a 308 px band is the `TURN...` defect in a different coat.
        record["reason"] = reason if isinstance(reason, str) and reason else None
        return record

    def wifi_diagnostics(self):
        """The radio's own facts, as :data:`WIFI_DIAGNOSTIC_KEYS`.

        THE VALUES ALREADY EXISTED; THE PATH TO A READER DID NOT -- the third
        time this module has been written under that sentence, and this is the
        layer the other two sat on top of. See :data:`WIFI_DIAGNOSTIC_KEYS` for
        the incident: a badge that would not join Wi-Fi, on a cable, with root
        access and a maintainer reading its serial output, and it was STILL
        impossible to tell a wrong password from an out-of-range AP from a radio
        fault. It printed one line and went silent into backoff.

        NEVER ``None``, for :meth:`clock_diagnostics`' reason: a doorbell may
        genuinely not exist, but a radio always does. "This badge cannot tell
        you" is a statement about the ACCESSOR being absent -- an older
        `/system/lib` -- which the caller's own `getattr` already answers.

        **`online` DEFAULTS TO ``False``, WHICH IS THE OPPOSITE OF EVERY OTHER
        RADIO READ IN THIS MODULE.** See :meth:`_radio_online_for_display`; the
        asymmetry is the whole point rather than an oversight.

        `connected_ms` IS A `ticks_ms` STAMP AND NEVER A DURATION -- it is
        assigned `now` on the transition to ONLINE and cleared by `_fail`. The
        conversion happens HERE and not in `resilient_wifi` because this object
        owns the frame's clock (`self._now`, taken at the top of `poll`) and the
        pure view model that draws the line owns no clock at all.

        PAGE-SCOPED AND CHEAP ON PURPOSE. One dict plus six field reads and NO
        native call, because the Settings seam rebuilds its view every frame and
        the two Network pages that read this are the pages an operator leaves up
        while a badge retries.
        """

        record = {"radio": None, "reason": None, "attempts": None,
                  "failures": None, "online": False, "connected_s": None,
                  "region": None}
        backend = self._backend
        if backend is None:
            # NO BACKEND: cold OFF, or a boot before the first radio start, or a
            # `CredentialError` out of the factory. **THIS IS EXACTLY THE STATE
            # `state` REPORTS AS CONNECTING** (it does that whenever `_backend`
            # is None), and being able to tell it apart is the whole reason this
            # accessor exists: `online` stays False, so the panel says the radio
            # has not joined instead of claiming a server connection is in
            # progress.
            return record
        snapshot = _call_dict(backend, "wifi_snapshot")
        if snapshot is not None:
            record["radio"] = _text(snapshot.get("state"))
            # RAW, AND NEVER TRANSLATED INTO A VERDICT. `status_-3` reaches the
            # screen as `status_-3`. A negative CYW43 status was recorded
            # SPURIOUSLY on correct credentials
            # (`benchmark/results/reports/2026-08-13-v3.0.1-network-authenticated.md`),
            # and that report rules it "a retry signal and diagnostic fact, not
            # a safe basis for a permanent user-facing" claim.
            record["reason"] = _text(snapshot.get("reason"))
            for key in ("attempts", "failures"):
                record[key] = _whole(snapshot.get(key))
            held = snapshot.get("connected_ms")
            if isinstance(held, int) and not isinstance(held, bool):
                span = _ticks_diff(self._now, held)
                # A NEGATIVE SPAN IS FLOORED AT ZERO RATHER THAN DROPPED: the
                # stamp is taken inside `backend.poll` and `self._now` is the
                # tick from the TOP of the same frame, so an association that
                # landed this frame legitimately reads a few ticks in the
                # future. "0 s" is true; `?` would say the badge cannot tell.
                record["connected_s"] = span // 1000 if span > 0 else 0
        record["online"] = self._radio_online_for_display()
        record["region"] = _text(_call(backend, "wifi_region"))
        return record

    def link_diagnostics(self):
        """The path to the server, as :data:`LINK_DIAGNOSTIC_KEYS`.

        NEVER ``None``, for :meth:`wifi_diagnostics`' reason, and `service_error`
        is filled in ABOVE the backend check on purpose: the fault this key
        exists for is the one where there IS no backend. A malformed BadgeLink
        value raises `CredentialError` out of `credentials.load` inside
        `DeviceBackend.__init__`, the factory's containment handler puts the
        exact sentence in :attr:`last_error`, `_backend` stays None and
        `_retry_at` is set -- so `state` answers BACKOFF, the panel folds that
        onto "Can't reach the server", and the sentence naming the actual field
        sits in memory with no reader. Returning early before copying it would
        reproduce that defect inside its own fix.

        **NOT `PollLoop.snapshot()` AND NOT `NetworkService.snapshot()`.** The
        first builds ~35 keys; the second reaches the FILESYSTEM through
        `_score_pending` and `_cached_schedule_version`. Neither belongs on a
        path that runs once per rendered frame. `link_counts` reads the six
        individual attributes instead.

        PAGE-SCOPED: this is the cost of Network pages 3-4 and of no other
        frame, which is what makes the resolver's `ifconfig()` affordable at
        all.
        """

        record = {"transport": None, "opens": None, "open_failures": None,
                  "outcome": None, "dns_ms": None, "connect_ms": None,
                  "stall_ms": None, "resolver": None, "lookups": None,
                  "lookup_failures": None, "service_error": None,
                  "link_error": None}
        # TWO ERROR KEYS, TWO LINES, NEVER MERGED. `service_error` is a fault in
        # what this badge was PROVISIONED with; `link_error` is a fault in what
        # the network did. They are different repairs by different people, and a
        # single "last error" line would send an operator to the wrong one.
        record["service_error"] = _text(self.last_error)
        backend = self._backend
        if backend is None:
            return record
        counts = _call_dict(backend, "link_counts")
        if counts is not None:
            # THE RAW TRANSPORT LITERAL, before the fold that maps both
            # `disconnected` and `backoff` onto one unreachable line. That fold
            # is why "Can't reach the server" cannot today distinguish no-Wi-Fi
            # from no-Supabase.
            record["transport"] = _text(counts.get("state"))
            record["opens"] = _whole(counts.get("opens"))
            record["open_failures"] = _whole(counts.get("open_failures"))
            record["link_error"] = _text(counts.get("last_error"))
            phases = counts.get("phases")
            if isinstance(phases, dict):
                record["outcome"] = _text(phases.get("outcome"))
                # THE ONE SPLIT THAT SEPARATES A DEAD RESOLVER FROM A DEAD TLS
                # PEER NUMERICALLY. `connect_ms` is TCP+TLS together on this
                # client; the handshake is not splittable at that seam
                # (`VAL-031-BLT`), so no third number is invented here.
                record["dns_ms"] = _whole(phases.get("dns_ms"))
                record["connect_ms"] = _whole(phases.get("connect_ms"))
                record["stall_ms"] = _whole(phases.get("open_stall_ms"))
        dns = _call_dict(backend, "resolver_snapshot")
        if dns is not None:
            # `None` HERE IS THE GREY ZONE NAMED, not a missing reading: DHCP
            # offered no option 6 and the gateway is unusable, which is the
            # exact condition `bounded_dns` was written for and the one that
            # used to present as a badge sitting there for 13-14 s per lookup.
            record["resolver"] = _text(dns.get("server"))
            record["lookups"] = _whole(dns.get("queries"))
            record["lookup_failures"] = _whole(dns.get("failures"))
        return record

    def identity(self):
        """Who this badge is, as :data:`IDENTITY_KEYS`.

        NEVER ``None``: `uid`, `boot` and `build` need no backend, no radio and
        no loop, so the badge that can answer least still answers these. Every
        one of them is posted to the server on every heartbeat and none of them
        could be read off the badge in the hand -- the wrong way round for the
        one day when the server is what nobody can reach.

        ⚠ `uid` IS `hardware_uid()` AND NOT THE CREDENTIAL'S SUBJECT. On the
        shared-token fleet every badge ships a byte-identical `/secrets.py`, so
        the subject is the same 16-hex value on all ~1,000 and names the FLEET.
        `token` is what makes the subject useful anyway -- `fleet` or
        `per_badge` answers the S0.8 rollout question that nothing on the wire
        could answer before.

        `_boot_session()` GENERATES ONCE AND CACHES, so calling it here is
        idempotent and costs one `os.urandom(16)` on the first draw of Diag
        page 4 at worst; the heartbeat generates it anyway.

        PAGE-SCOPED: Diagnostics page 4 alone calls this, which is what makes
        `_firmware_version`'s `os.uname()` affordable.
        """

        record = {"uid": None, "token": None, "boot": None, "build": None,
                  "fault": None}
        record["uid"] = _text(hardware_uid())
        backend = self._backend
        if backend is not None:
            # THE SUBJECT IS FETCHED AND IMMEDIATELY REDUCED TO A TIER WORD. It
            # is not secret -- see :data:`SHARED_SUB` -- but it is a
            # server-shaped string, and no server-shaped string may reach a line
            # a screen draws from a pre-baked 95-glyph set.
            record["token"] = _text(credential_tier(_call(backend, "badge_id")))
            # NOT THROUGH `_call`: this is a plain ATTRIBUTE with a class
            # default of None, so a probe-built instance answers "no fault"
            # rather than raising, and there is no method to be older than.
            record["fault"] = _text(getattr(backend, "provisioning_fault", None))
        boot = _text(self._boot_session())
        record["boot"] = boot[:8] if boot is not None else None
        record["build"] = _text(self._firmware_version())
        return record

    def _note_push_cause(self):
        """Emit the cause ON CHANGE, and never more than that.

        THE MEASURED GAP THIS CLOSES IS 449 CONSECUTIVE SECONDS OF SILENCE. Every
        withholding gate on the establishment path was a silent `return`, so a
        badge that had stopped trying looked exactly like a badge with nothing to
        do. A line per frame would be the opposite mistake -- 37 lines a second
        drowning the log an operator is reading it in -- so the rule is the one
        the rest of this module uses for state: print the EDGE, not the level.
        """

        # CONTAINED HERE RATHER THAN AT THE CALL SITE. `poll`'s own handler would
        # catch it, but it would then set `last_error` and emit `contained` --
        # making a broken INSTRUMENT read as a transport fault, which is the one
        # thing a diagnostic must never do.
        try:
            cause = self.push_cause()
        except Exception:
            return None
        changed = cause != self._push_cause_seen
        if changed and self._push_cause_seen:
            # THE ONE BEING REPLACED becomes the answer to "what was it before I
            # came to look" -- see `push_cause_previous`. `_push_cause_seen`
            # starts as False and can legitimately be None, and neither is a
            # cause worth latching, so the truthiness test is doing real work
            # here rather than saving a character.
            self._push_cause_before = self._push_cause_seen
            self._push_cause_before_at = self._ticks_ms()
        # SHIFT FIRST, THEN CLEAR, and the order is load-bearing: written the
        # other way round the join that clears the latch immediately re-latches
        # the `waiting` it just cleared, because a join is itself a CHANGE from
        # some cause to None.
        if cause is None and self._push_joined():
            # THE QUESTION IS ANSWERED. Drop the latch rather than leave a true
            # fact about the past sitting where a reader will take it for the
            # present.
            self._push_cause_before = None
            self._push_cause_before_at = None
        if not changed:
            return cause
        self._push_cause_seen = cause
        if cause is not None:
            self._emit("push_withheld", reason=cause)
        return cause

    def _latch_cause_at_switch(self):
        """Latch the LIVE cause because the wearer is about to destroy it.

        **THE BRANCH THIS FIXES REPORTED NOTHING AT ALL, which is not what two
        reviews assumed.** Both flagged that a badge which saw `refused` and then
        had its radio switched off would keep SAYING `refused` for the rest of the
        day. It would not -- it said nothing. `poll()` returns above
        `_note_push_cause` once networking is off, so the shift from `refused` to
        `None` never ran and the latch kept whatever preceded `refused`, or more
        usually nothing. The live cause was sitting in `_push_cause_seen`, which no
        accessor reads.

        So the fix is not only an age bound on a stale value; it is TAKING the
        value in the first place. This runs at the switch, which is the last moment
        the cause is still knowable, and it is what makes "why was it down before I
        disabled it" answerable at all.

        Total, and called from a Settings press: a raise here would turn a button
        into a `machine.reset()`.
        """

        try:
            cause = self.push_cause()
        except Exception:
            return None
        if cause is None:
            return None
        self._push_cause_before = cause
        self._push_cause_before_at = self._ticks_ms()
        return cause

    def _clear_cause_latch(self):
        """Drop the latch, because the live cause can speak again.

        Called when a switch goes back ON: the wearer has restored the thing whose
        absence the latch was explaining, so keeping it would put a fact about the
        previous state beside a live reading of the current one -- the same mistake
        `_note_push_cause` avoids on a join.
        """

        self._push_cause_before = None
        self._push_cause_before_at = None

    def _push_joined(self):
        """Is the doorbell actually carrying right now? Total, never raises."""

        push = self._push
        link = getattr(push, "link", None) if push is not None else None
        return bool(getattr(link, "joined", False))

    def set_push_enabled(self, enabled):
        """Turn the doorbell on or off durably, and act on it now.

        Turning it ON is also the documented escape from an automatic demotion:
        the wearer is explicitly asking for another try, which is exactly the
        signal the sticky demotion was waiting for.
        """
        enabled = bool(enabled)
        try:
            network_preference.save_push(enabled, self._preference_path)
        except Exception as exc:
            # Same rule as the radio switch: a full or read-only LittleFS must
            # not turn a Settings button into an app reset, and the old value
            # stays authoritative.
            self.last_error = _error_text(exc)
            self._emit("push_preference_failed", error=self.last_error)
            return self._push_enabled
        # Same seam as the radio switch, one line above the flip for the same
        # reason: `push_cause` reads `_push_enabled` and answers None once it is
        # False, so the cause has to be taken while it is still True.
        if not enabled:
            self._latch_cause_at_switch()
        else:
            self._clear_cause_latch()
        self._push_enabled = enabled
        self._emit("push_preference", enabled=enabled)
        if self._push is not None:
            self._push.set_enabled(enabled)
            if enabled:
                # Reconnect at the next frame, which is a tolerant moment by
                # construction: the wearer is looking at the screen they just
                # pressed and the panel has already repainted.
                self.request_tolerant_moment(MOMENT_SESSION_START)
        return self._push_enabled

    def push_control(self):
        """A Settings-shaped control, or ``None`` when this badge has no push.

        Deliberately a narrow, read-through surface (``enabled`` /
        ``set_enabled`` / ``mode`` / ``cause`` / ``previous_cause`` /
        ``diagnostics``) so ``settings_model`` needs no knowledge of either
        transport. It started out matching the network control exactly; the
        three read-only answers since are values the runtime already computed
        and had no path to a reader for -- see :class:`_PushControl`.
        """
        if self._push_factory is None:
            return None
        if self._push_control is None:
            self._push_control = _PushControl(self)
        return self._push_control

    def set_active(self, active):
        active = bool(active)
        if active and not self._active:
            # A BadgeLink view coming foreground is a view transition, which the
            # transport decision names as a tolerant moment: the wearer is
            # already watching a screen change, so a handshake can hide there.
            self.request_tolerant_moment(MOMENT_VIEW_TRANSITION)
        self._active = active
        backend = self._backend
        if backend is not None:
            backend.set_active(self._active)
        return self._active

    def request_schedule_refresh(self, have_artifact_id, sink):
        """Latch exactly one conditional Schedule GET for this app open.

        This call intentionally succeeds before a backend or socket exists. The
        Schedule app can therefore make one request at open and keep drawing its
        local copy while ordinary association proceeds; `_pump_schedule_v2`
        queues it later on the existing errand channel. A second call cannot
        create polling by accident.
        """

        if self._schedule_v2_requested or self._schedule_v2_done:
            return False
        if not callable(sink):
            return False
        if have_artifact_id is not None and not isinstance(have_artifact_id, str):
            return False
        self._schedule_v2_requested = True
        self._schedule_v2_have = have_artifact_id
        self._schedule_v2_sink = sink
        self._emit("schedule_v2_requested", cached=have_artifact_id is not None)
        return True

    def enter_run_context(self):
        """Resolve the OWNER RULING #22 placement context ONCE per ``run()``.

        ``managed_run`` wraps every ``run(...)`` and calls this at the top of
        each. A ``run()`` call is ONE app for its whole life -- an app switch is
        a new boot and a new ``run()`` (docs/tufty-architecture.md: an app exit
        IS ``machine.reset()``) -- so the launcher-vs-app answer is stable for
        the call and is read exactly here, not per rendered frame (handoff §5.3).

        The signal is ``openapp_note.current_app``, the PROVEN app identity: the
        cwd ``launch()`` chdir'd into (do NOT infer it from ``sys.path[0]`` --
        the menu inserts ``"/"`` there). Placement denies ONLY inside a KNOWN
        app that is not the launcher; ``current_app`` is the menu's slug at the
        launcher and a real slug in an app, and it is ``None`` outside
        ``/system/apps`` -- early boot, a probe, a host test -- which fails OPEN.
        Stranding an unknown or launcher context is worse than one extra
        establishment, and the launcher always connects (spec §4.5 amended
        invariant). On the device every ``run()`` call is either the menu or an
        app, both under ``/system/apps``, so ``None`` is never a real run there.
        Cold OFF does no cwd/app-context work at all: the always-connect legacy.
        A missing note module or a raising ``getcwd`` also fails open.
        """
        if not self._nb_connect_enabled:
            return None
        # PLACEMENT OPT-IN IS STRICTLY PER-RUN-CONTEXT (OWNER RULING #22). A
        # launcher-and-app pair share ONE boot (docs/tufty-architecture.md: the
        # menu returns a path and launch()es it in the same instance, no reset),
        # so a `set_active(True)` the launcher raised for a BadgeLink Settings
        # screen would otherwise still be True when the app's `run()` begins --
        # silently opting the app in and re-opening the freeze this policy
        # closes. An app opts in from INSIDE its own run (`set_active` fires in
        # its update loop, always AFTER this), so clearing here loses nothing an
        # app asked for and closes the same-boot handoff leak. OFF returned above
        # and never touches `_active`.
        self._active = False
        note = self._open_app_note_safe()
        if note is None:
            self._at_launcher = True
            return self._at_launcher
        try:
            app = note.current_app(self._getcwd)
        except Exception:
            app = None
        # Launcher-equivalent (allow) unless we KNOW we are in a non-menu app.
        self._at_launcher = app is None or app == note.MENU_SLUG
        if app is None:
            # FAIL-OPEN STAYS (dead-badge is worse than an in-app hitch), but a
            # None context that resolved a REAL cwd is a shipping app that
            # chdir'd out of its own root -- the convention this policy leans on,
            # broken. Emit a one-shot tripwire; the AST guard is the enforcement.
            self._warn_unknown_run_context()
        return self._at_launcher

    def _warn_unknown_run_context(self):
        """One-shot fail-open diagnostic for a resolved-but-unknown run context.

        Only fires when we actually KNOW the cwd (a real absolute path) and it is
        NOT under ``/system/apps`` -- which on device means an app chdir'd out of
        its own root, defeating placement silently. A host test or early boot
        gives no usable cwd and stays quiet, so this does not pollute suites that
        never inject one. Never raises: a diagnostic may not be the reason a boot
        has no network. Bounded like ``error`` -- a cwd is a device path this
        package did not format, so it is capped rather than put unbounded on the
        wire; ``reason`` is already a printed/forwarded field, so no census entry
        moves.
        """
        if self._unknown_context_warned:
            return
        getcwd = self._getcwd
        if getcwd is None:
            # `os` is imported locally throughout this module (MicroPython keeps
            # the import cheap and the top-level namespace small); mirror that.
            import os
            getcwd = getattr(os, "getcwd", None)
        if not callable(getcwd):
            return
        try:
            cwd = getcwd()
        except Exception:
            return
        if not isinstance(cwd, str) or not cwd:
            return
        self._unknown_context_warned = True
        self._emit("placement_unknown_context",
                   reason=cwd[:_PRINTED_ERROR_CHARS])

    def _force_open_reset_pending(self):
        """Whether ``launch_result`` will hard-reset the badge THIS frame (#22).

        A force ``open_app`` command applied during ``backend.poll`` sets
        ``_open_target``/``_open_force``; on an idle frame in a non-menu app,
        ``launch_result`` then calls ``_reset()`` the instant ``poll`` returns
        (``launch_result``: the force branch). That reset is an app exit in all
        but name, so `poll` treats the frame as an EXIT FRAME for the doorbell --
        no parked WSS may SEND into it (spec §5.3(e)). At the launcher the same
        target is consumed as a launch, not a reset, so this is scoped to
        not-at-menu, matching `launch_result`'s own condition. Never raises.
        """
        if self._open_target is None or not self._open_force:
            return False
        note = self._open_app_note_safe()
        if note is None:
            return False
        try:
            return not note.at_menu(self._getcwd)
        except Exception:
            return False

    def _placement_allows_establishment(self):
        """Whether a NEW establishment may START now (OWNER RULING #22).

        ``True`` at the launcher, or in an app that opted in via
        ``set_active(True)`` (the settings app's precedent). ``False`` in any
        other app: a new poll open and a new WSS join both defer until the
        badge is back at the launcher or an app opts in. This gates only the
        START of an establishment -- a warm, already-ESTABLISHED session is
        untouched and travels into the app (spec §4.5 warm travel); it is the
        loop's CONNECTED branch and the doorbell's session pump that carry it,
        not this predicate.

        An APP-EXIT frame is always deny: ``managed_update`` runs this frame's
        ``poll`` one step before the app's non-None result resets the badge, and
        a parked open may neither advance nor SEND into that reset (spec §5.3(e),
        the exit-frame open item). The launcher's OWN non-None result is a
        same-boot handoff -- the socket travels, there is no reset -- so the
        exit deny is scoped to ``not self._at_launcher``.
        """
        if self._exit_frame and not self._at_launcher:
            return False
        return self._at_launcher or self._active

    def request_tolerant_moment(self, moment):
        """Declare that the NEXT pumped frame may afford a WS handshake.

        The frame loop cannot discover this for itself: only the caller knows a
        connecting screen is up or a view is changing. Session start is the one
        this module raises on its own.
        """
        self._pending_moment = moment
        return moment

    def quiesce(self, reason="intro"):
        """A gate has stopped servicing the transport (the supervisor's intro).

        Push only: the polling loop's own missed-ack liveness already treats a
        gap as a dead socket, and it opens nothing that a frame has to pay for
        outside its ``CONNECTING`` state.
        """
        self._quiesced = True
        self._quiesce_reason = reason
        if self._push is not None:
            self._push.quiesce(reason)
        self._emit("quiesced", reason=reason)
        return True

    def resume(self, now=None):
        """The gate lifted. Intro-end IS a tolerant moment (card item 7b)."""
        self._quiesced = False
        self._quiesce_reason = None
        if self._push is not None:
            self._push.resume(now)
        self.request_tolerant_moment(MOMENT_INTRO_COMPLETE)
        self._emit("resumed")
        return True

    def poll(self, now=None, exit_frame=False):
        now = _ticks_ms() if now is None else now
        self._now = now
        if self._nb_connect_enabled:
            # OWNER RULING #22 exit-frame: recorded per frame, read by the
            # placement predicate and by `_service_push`. OFF never sets or
            # reads it -- the class default False stands and the whole policy is
            # inert. `managed_update` passes True on the app's non-None result.
            self._exit_frame = bool(exit_frame)
        # A barrier left by an earlier call has served its purpose: this is now
        # a later rendered poll. A sink invoked by ``backend.poll`` below raises
        # it again and prevents both continuation pumps in THIS call.
        self._response_continuation = False
        # ONE EXPENSIVE SUB-TASK PER FRAME (Card FT-B, F21). Reset here rather
        # than tracked per pump, because the budget belongs to the FRAME: the
        # score drain and the schedule sync are two features and one frame, and
        # a badge that lets them both spend it has a p99 nobody can predict.
        self._chore_spent = False
        # ONE TRANSPORT CONNECT PER FRAME, and the flag is reset with the chore
        # budget for the same reason: it is a property of the FRAME, not of a
        # transport. A frame that returns early below has performed no connect,
        # which is what `False` says.
        self._connect_frame = False
        # THE ARRIVED MOMENT COMES FIRST, above every early return below: a broadcast is
        # the ONLY delivery path the badge has left, so a pump placed behind the
        # `_enabled`/`_revoked`/backoff returns would make a fleet light show
        # depend on the state of an HTTP transport it no longer travels over.
        # The action is already in RAM; applying it needs no socket at all.
        #
        # AHEAD OF `_pump_effect`, which is what lets a freshly installed player
        # take its frame-zero write here and be SKIPPED by the steady pump below
        # using the installed-object marker below. There is no durable action
        # hold now: offline badges deliberately miss broadcast moments.
        self._pump_broadcast_actions(now)
        # STEADY ANIMATION IS NOT A CHORE. These three bounded slots must advance
        # even when the broadcast above, or the ledger below, spent the frame's
        # flash/network budget. A broadcast applier already emitted its explicit
        # frame-zero write, so the installed-object marker skips only that
        # same-poll duplicate; the predecessor cannot write one last stale frame.
        self._pump_effect(now)
        # THE DURABLE ACK'S RETRY RUNS IN EVERY STATE, ABOVE EVERY EARLY RETURN
        # (CX-7, corrected 2026-08-23). It used to sit ~80 lines below, behind the
        # `_enabled`/`_revoked` return, and that made the whole 5/10/20/40 s ladder
        # unreachable in the two states that need it most: a wearer who switches
        # networking off after the badge misbehaved, and a badge whose grant was
        # revoked -- which is STOPPED for the rest of the boot, so the ack it
        # already performed can never reach the server this boot and the durable
        # record is the only thing standing between that effect and a replay. The
        # ladder ran out against a return statement, `_ledger_dirty` stayed True,
        # and the next reset reopened the exact CX-7 window the ladder closes.
        #
        # IT IS LOCAL FLASH WORK AND IT IS NOT NETWORK WORK. That is why it is
        # correct here: `_defer_once` exists to keep DNS/TLS off the frame that
        # paints CONNECTING and `_retry_at` exists to keep an open off a
        # backed-off frame, so neither of them is a reason to skip a write to
        # `/state`. `set_enabled(False)` already makes the same argument for the
        # score retire twenty lines below itself, in the same words.
        #
        # THE BOUNDS ARE THE SAME BOUNDS: four tries PER BOOT (not per state),
        # each behind its own doubling backoff, and each spending this frame's one
        # chore. Ordered ahead of the score drain and the schedule sync exactly as
        # before -- correctness ahead of both optimisations, the rule `_begin_next`
        # applies on the wire. What it no longer sits behind is the
        # `_response_continuation` barrier, and that barrier's own comment names
        # the two OPTIMISATIONS it protects a response frame from; a barrier
        # raised by a sink cannot be read before the sink runs anyway.
        try:
            self._pump_ledger_persist(now)
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("ledger_contained", error=self.last_error)
        # THE DEFERRED POWER ACTION, ABOVE EVERY EARLY RETURN AND OUTSIDE EVERY
        # TRY, for three separate reasons and each one is load-bearing:
        #
        # * ABOVE `_enabled`, because the transient networking-off sets that flag
        #   False as its own effect, and a pump below the check would be
        #   unreachable from the frame after it fired -- and because the ABANDON
        #   path must still run on a badge whose radio the wearer just switched
        #   off, or the latch would outlive its own deadline for the boot.
        # * ABOVE `_defer_once` and `_retry_at`, so a badge in backoff still
        #   reaches its deadline and abandons rather than holding a pending sleep
        #   for the rest of the session.
        # * OUTSIDE THE TRY, because the browser's `MachineResetRequested` is how
        #   a modelled sleep ends the session and `poll`'s handler would swallow
        #   it into `contained` -- turning a working sleep into a transport
        #   fault. `_pump_power_action` contains everything else itself.
        #
        # It costs one `is None` on every ordinary frame.
        self._pump_power_action(now)
        if not self._enabled:
            return self.state
        if self._revoked and not self._revoked_reprobe_due(now):
            # THE BOOT-WIDE STOP IS NOW A SLOW HOLD, NOT A TERMINAL (§8.1). It
            # returned unconditionally here until 2026-08-26, which under the
            # shared fleet token means one transient server mistake takes ~800
            # badges dark until each is physically rebooted -- a 403 no longer
            # says "this badge is denied", it says "the fleet's grant is denied".
            # Every frame before the armed tick is the same immediate return it
            # always was.
            return self.state
        if self._defer_once:
            self._defer_once = False
            return self.state
        if self._retry_at is not None:
            if _ticks_diff(now, self._retry_at) < 0:
                return self.state
            self._retry_at = None
        # ONE TRANSPORT CONNECT PER FRAME (Lane H). Sampled BEFORE the backend
        # section and compared after it, so the answer covers the whole block --
        # a `_build_loop` that resolves and syncs the clock, the open that
        # follows it in the SAME frame because `start`/`request_reconnect` set
        # the next due to `now`, and an open that raised. See
        # `_connect_frame`'s own comment at `_service_push` for what it buys.
        #
        # ⚠ **ON SAMPLES ESTABLISHMENT STEPS, NOT ATTEMPTS (NB-0 arbiter).** Once
        # P1-a parks the poll open across frames, `connect_attempts` moves only
        # on the attempt-start frame, so every later parked continuation would
        # read as "no connect this frame" and could share it with the ~2.3 s WSS
        # join. `establishment_steps` moves on preparation AND on every
        # `open_step`, so a parked open is a connect frame on EVERY frame it
        # advances. OFF keeps the attempt sample byte-for-byte.
        attempts_before = self._frame_connect_sample()
        try:
            if self._backend is None:
                self._backend = self._backend_factory(
                    self._on_command, self._on_backend_event)
                if self._nb_connect_enabled:
                    # The backend contains both cold strategies but OFF must not
                    # allocate or pump the held-only address owner. Enable it
                    # before start/build so the first authenticated poll open is
                    # already able to publish the numeric WSS address.
                    enabler = getattr(
                        self._backend, "enable_held_connect", None)
                    if callable(enabler):
                        enabler()
                # Duck-typed and optional, so the two-argument factory shape
                # Card PW shipped keeps working unchanged: a backend that has no
                # steering channel simply never offers one.
                setter = getattr(self._backend, "set_policy_sink", None)
                if callable(setter):
                    setter(self._on_policy)
                # NOTHING ARMS A CADENCE PHASE HERE ANY MORE (rebuild,
                # 2026-08-29). The steering read's phase was pushed DOWN into the
                # loop from this line until today, which is what made two objects
                # own one cadence; `_pump_fleet_settings` and `_pump_heartbeat`
                # phase themselves on the first frame they see a socket, which is
                # also the frame a badge whose networking is OFF never reaches.
                self._backend.start(now)
                self._backend.set_active(self._active)
            if self._nb_connect_enabled:
                # OWNER RULING #22 PLACEMENT, POLL SIDE. The PERSISTENT gate:
                # when the foreground is a non-opted-in app (or this is the
                # exit frame), a new poll open must not start, and an in-flight
                # one is ABORTED as a non-failure. That abort/re-arm lives in
                # `PollLoop.set_establishment_allowed`, which the backend drives
                # from this flag inside its own `poll`; it is distinct from the
                # per-frame chore gate below, which only DEFERS. Driven before
                # the frame gate and before `backend.poll` so a deny edge aborts
                # a parked open before it can advance. Duck-typed like the frame
                # gate: a fixture backend that predates the seam is never gated.
                placement = self._placement_allows_establishment()
                placement_gate = getattr(
                    self._backend, "set_placement_establishment_allowed", None)
                if callable(placement_gate):
                    placement_gate(placement)
                # PASS THE PER-FRAME ARBITER GATE INTO THE BACKEND (spec 5.3(b)),
                # BOTH DIRECTIONS. A correctness chore that already ran this
                # frame -- the durable-ledger persist or the physical-effect pump
                # above -- set `_chore_spent`, and a 35-45 ms atomic save plus a
                # parked open step fails the whole-frame bar while both private
                # budgets pass. THE EXIT FRAME denies it too (harmless-drop, not
                # abort): a parked open may not advance into a reset (spec
                # §5.3(e)), and the reset itself is the cleanup. Deny defers
                # preparation/open one frame; Wi-Fi still ticks and radio abort
                # edges still run inside `poll`. Duck-typed so a fixture backend
                # that predates the seam is simply never gated. OFF calls `poll`
                # with no gate at all.
                gate = getattr(
                    self._backend, "set_frame_establishment_allowed", None)
                if callable(gate):
                    exit_frame = self._exit_frame and not self._at_launcher
                    gate(not self._chore_spent and not exit_frame)
            self._backend.poll(now)
            # PollLoop marks itself active when a command arrives.  The app
            # foreground is the lasting authority; pending acks remain urgent
            # because queue_ack already pulled their deadline to "now".
            self._backend.set_active(self._active)
            self._failures = 0
            if getattr(self._backend, "state", None) == REVOKED:
                self._revoked = True
                # AUTHORITY LOSS ENDS THE REMOTE MOMENT NOW. The frame pump sits
                # above the revoked early return, so merely latching the state
                # would let a 300-second player keep writing for five minutes.
                # Restore before releasing transport state; this helper also
                # clears any cue captured just before the refusal arrived.
                self._clear_remote_effects()
                # `source=service` NAMES THIS EMITTER, and it is the reason the
                # field exists (2026-08-24). This line and the loop's own
                # `revoked` land in the SAME FRAME, 20 ms apart on the device, and
                # both are true: the transport stopped, and then the whole service
                # stopped for the boot -- which is the fact that also releases the
                # doorbell below. Until this field existed the two were
                # indistinguishable on serial and arm 6's "no second `revoked`"
                # failed a WORKING build.
                # ONE LINE PER BOOT FROM THIS EMITTER, even though the latch is
                # now cleared and re-set on every refused re-probe (§8.1). A
                # second `revoked` with `source=service` is exactly the failure
                # the one-per-source rule exists to catch; the loop's own
                # `revoked_reprobe_refused` is what says the badge is still
                # asking, and it does not need repeating here.
                if not self._revoked_announced:
                    self._revoked_announced = True
                    self._emit("revoked", source=SOURCE_SERVICE)
                # AND LET GO OF THE DOORBELL'S SOCKET, because from the next
                # frame on this method returns above `_service_push` and would
                # never touch it again. An abandoned WebSocket is not a stopped
                # one: nothing runs layer 1's ping timer or layer 2's heartbeat,
                # so the far end drops us on its own ~25 s ceiling while the TLS
                # socket and its buffers stay allocated for the rest of the boot
                # on a 520 KB heap -- and `pushlink`'s own starvation ceiling
                # cannot catch it either, because `step` is what would notice and
                # `step` is no longer called. Stopping here is also the honest
                # reading of decision #14: a 403 means stop until reboot, and
                # "stop" has to include the transport the wearer can see.
                #
                # This is the POLL's verdict acting on the poll's evidence. Push
                # reaches its own terminal state independently, from a refused
                # join (`pushlink.PushPolicy.note_revoked`); neither is allowed
                # to be the reason the other stops, and either arriving first is
                # correct.
                self._stop_push("revoked")
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("contained", error=self.last_error)
            backend = self._backend
            if backend is not None:
                try:
                    backend.failed(now, exc)
                except Exception:
                    self._stop_backend()
            else:
                self._failures += 1
                delay = min(300000, 1000 * (1 << min(self._failures - 1, 9)))
                self._retry_at = _ticks_add(now, delay)
        # DID THE POLL TRANSPORT CONNECT IN THIS FRAME? Read here, outside the
        # try, so an open that RAISED still counts -- a frame that spent the whole
        # budget in a blocked resolver is exactly the frame that must not also pay
        # a handshake. A backend that was rebuilt or torn down inside the block
        # answers differently from before it and therefore reads as "yes", which
        # is the conservative answer and the right one: a rebuild is a
        # `_build_loop`.
        self._connect_frame = (
            self._frame_connect_sample() != attempts_before)
        # The score drain rides the same cadence and the same socket. Outside the
        # try/except above for the same reason push is: a spooled score may never
        # be the reason a poll cycle is treated as failed.
        #
        # A backend response is different from an idle transport step. Its sink
        # has already paid the response decode in this frame, so it raises the
        # continuation barrier and neither score retirement nor schedule
        # parse/write/page continuation may pile onto it. Push remains below and
        # is still serviced: this barrier budgets response FOLLOW-UP, not the
        # independent doorbell.
        if not self._response_continuation and not (
                self._nb_connect_enabled and self._connect_frame):
            # ON: A POLL OPEN STEP THAT ADVANCED THIS FRAME SUPPRESSES THE SCORE
            # DRAIN AND THE SCHEDULE SYNC TOO (spec 5.1). Both are expensive
            # continuations, and stacking either onto the frame a parked open
            # just advanced re-creates the whole-frame overrun the private
            # per-transport budgets each pass. OFF keeps the response-only
            # barrier exactly: `_connect_frame` gates the doorbell there, not
            # these, because an OFF blocking open is already the whole frame.
            #
            # THE LEDGER PERSIST USED TO BE THE FIRST CALL IN THIS BLOCK and it is
            # now at the top of `poll` instead, above every early return -- see the
            # comment there. It kept its precedence over both of these (it claims
            # the chore first, so a frame that writes the ledger does not also
            # retire a score or sync the schedule); what it shed is a barrier that
            # made it unreachable while networking was off.
            # THE RECEIPT GOES FIRST OF THE THREE, AND IT COSTS THEM NOTHING.
            # It claims NO chore (a dict and a queue hand-off -- no file, no
            # parse, no crypto), so unlike the two below it cannot take the
            # frame's expensive slot away from them; going first only means the
            # oldest due write-back gets the errand slot before a score does.
            # That ordering is deliberate: a score is durable on flash and drains
            # whenever it likes, while a receipt is RAM-only and describes a
            # moment that has already happened, so the score can wait and the
            # receipt cannot.
            #
            # UNDER THE SAME BARRIER AS THE OTHER TWO, unlike the APPLIER at the
            # top of `poll`. Applying is local work that must never wait on a
            # transport; POSTING is a request, and a request stacked onto the
            # frame a parked open just advanced is the whole-frame overrun this
            # barrier exists to prevent. Being late here costs a row in an audit
            # table a few frames of latency and nothing else.
            try:
                self._pump_receipts(now)
            except Exception as exc:
                self.last_error = _error_text(exc)
                self._emit("receipt_contained", error=self.last_error)
            try:
                self._pump_scores()
            except Exception as exc:
                self.last_error = _error_text(exc)
                self._emit("score_contained", error=self.last_error)
            try:
                self._pump_schedule_v2()
            except Exception as exc:
                self.last_error = _error_text(exc)
                self._emit("schedule_v2_contained", error=self.last_error)
            # THE TWO PERIODIC REST ERRANDS, AFTER BOTH OF THE ABOVE AND FOR THE
            # REASON THE ORDER ABOVE ALREADY GIVES. A score is a wearer's
            # achievement and a schedule is what they came to read; the heartbeat
            # and the settings read are what an OPERATOR wants, on cadences of a
            # minute and five minutes, so a frame either of the first two claimed
            # costs them nothing they can measure. Both are inside the
            # continuation barrier for the same reason everything here is: a frame
            # that just decoded a response, or just advanced a parked open, has
            # already spent itself.
            #
            # THE HEARTBEAT FIRST, because it fires five times as often and
            # because it is also the SELF-REGISTRATION -- a badge with no row on
            # the server is a badge an operator cannot see at all, which is worse
            # than a lever that is five minutes stale. Contained separately from
            # each other so neither can be the reason the other is skipped.
            try:
                self._pump_heartbeat(now)
            except Exception as exc:
                self.last_error = _error_text(exc)
                self._emit("heartbeat_contained", error=self.last_error)
            try:
                self._pump_fleet_settings(now)
            except Exception as exc:
                self.last_error = _error_text(exc)
                self._emit("settings_contained", error=self.last_error)
        if self._nb_connect_enabled and self._force_open_reset_pending():
            # A force `open_app` applied in `backend.poll` above will `_reset()`
            # in `launch_result` the instant this poll returns (spec §5.3(e)).
            # Promote the frame to an exit frame BEFORE the doorbell runs so a
            # parked WSS is aborted and no moment is minted -- nothing may SEND
            # into that reset. The poll side needs no promotion here: a loop
            # delivering this command is CONNECTED, not advancing a parked open,
            # so its placement/frame gates (set above `backend.poll`) had nothing
            # to abort. `launch_result` runs one step later and cannot gate the
            # doorbell there; this is the only seam that can.
            self._exit_frame = True
        # OUTSIDE the polling try/except on purpose. Push is an optimisation, so
        # a doorbell fault may never be the reason a poll cycle is treated as
        # failed, and a poll fault may never be the reason a live WebSocket stops
        # being serviced. `_service_push` contains everything itself.
        self._service_push(now)
        # AFTER the doorbell's turn, so the cause describes the state this frame
        # actually left behind rather than the one it started in. It contains
        # itself -- see `_note_push_cause`.
        self._note_push_cause()
        return self.state

    def stop(self):
        self.set_enabled(False)
        return self.state

    def force_active_cadence(self, on=True):
        """THE OPERATOR ENTRY POINT for the poll-cost test knob.

        Reachable from a REPL or a device probe as
        ``badgelink_network.force_active_cadence(True)`` and from nowhere else --
        no command type, no preference, no Settings row, no boot hook. See
        :meth:`polltransport.PollLoop.force_active_cadence` for what it does and
        why it is contained the way it is; the guards are in
        ``badgelink/tests/test_ft_b_poll_cost.py``.

        Returns the resulting flag, or ``None`` when there is no live loop to
        set it on -- a badge that is OFF, offline, or has not completed its first
        handshake yet. ``None`` is deliberately distinguishable from ``False``:
        "not measuring" and "could not be asked" are different answers to an
        operator who is about to read a serial log.
        """
        backend = self._backend
        setter = None if backend is None else getattr(
            backend, "force_active_cadence", None)
        if not callable(setter):
            # Duck-typed, like `set_policy_sink`: a backend shape that predates
            # the knob keeps working and simply has none.
            return None
        return setter(on)

    def snapshot(self):
        record = {
            "enabled": self._enabled,
            "state": self.state,
            "revoked": self._revoked,
            "push_enabled": self._push_enabled,
            "push_mode": self.push_mode(),
            "last_error": self.last_error,
            "ledger_entries": len(self._ledger.get("entries", ())),
            # CX-7's story, and the only durable one: the diagnostic is emitted
            # at most once per boot, so these two are what a Settings screen or a
            # probe reads to learn that `/state` is unwritable.
            "ledger_dirty": self._ledger_dirty,
            "ledger_save_failures": self.ledger_save_failures,
            "scores_pending": self._score_pending(),
            # WHY THAT NUMBER IS NOT FALLING, for a reader who was not tethered
            # at the moment it stopped. `score_stalled` is emitted on the
            # TRANSITION, so an operator who attaches serial afterwards sees
            # nothing at all; these two are the pull-based form of the same
            # answer and cost a RAM read each.
            "scores_enabled": self._scores_enabled,
            "scores_stalled": self._score_stall,
            # THE BROADCAST LANE'S QUANTITIES. `actions_duplicate` is the
            # one an operator reads as HEALTHY: it means the shared topic
            # delivered a publish twice and this badge played it once.
            "actions_applied": self.actions_applied,
            "actions_failed": self.actions_failed,
            "actions_dropped": self.actions_dropped,
            "actions_duplicate": self.actions_duplicate,
            "schedule_version": self._cached_schedule_version(),
            # The doorbell pump's session cost, for a probe. The exchange and
            # handshake numbers live on the PollLoop's own snapshot, because that
            # is the object that owns the socket.
            "push_pumps": self._push_pumps_total,
            "push_busy_ms": self._push_busy_total_ms,
            "push_peak_ms": self._push_peak_session_ms,
        }
        if self._push is not None:
            record["push"] = self._push.snapshot()
        return record

    def _cached_schedule_version(self):
        """The version this badge holds.  THE ONE SOURCE, and the only reader.

        `_schedule_version` is the version an in-progress fetch is FOR, so it is
        None on a boot that has not synced yet and stays set after an abandoned
        fetch -- reporting either would say the badge has a schedule it does not.

        `_schedule_cached` is the on-disk answer once it has been read; `False`
        means nothing has read it yet, and then this does -- WITHOUT the row
        normalisation `load()` performs, because a snapshot wants one string.
        The RAM copy is written by exactly two things: this priming read, and the
        commit in `_schedule_parse_step` that moves it with the file.

        BOTH CALLERS COME HERE (CX-10), and the honest reason is CONSOLIDATION
        rather than a saved read: `snapshot()` and `_pump_schedule_sync` each
        called `box.cached_version` for themselves, and each was guarded by its
        own `is False` check, so whichever ran first was already the only one
        that paid. What two call sites bought was two ways to diverge, and one of
        them HAD diverged -- this one used to leave `_schedule_cached` at `False`
        after a raise where the frame's copy recorded `None`. The frame's caller
        claims the chore budget BEFORE calling this, because the read is the
        expensive thing and the budget belongs to the frame.
        """
        if self._schedule_cached is not False:
            return self._schedule_cached
        box = self._schedule_store()
        if box is None:
            return None
        try:
            self._schedule_cached = box.cached_version(self._schedule_cache_path)
        except Exception as exc:
            self.last_error = _error_text(exc)
            # A READ THAT FAILED IS "NO SCHEDULE", RECORDED. Leaving `False` here
            # would make the next frame try again, and a volume that raises once
            # raises every time -- which is a per-frame file open for the rest of
            # the boot.
            self._schedule_cached = None
        return self._schedule_cached

    def _score_pending(self):
        """The spool depth, for a snapshot.  Never raises."""
        box = self._score_box()
        if box is None:
            return 0
        try:
            return box.pending(self._score_path)
        except Exception:
            return 0

    def _service_push(self, now):
        """Give the doorbell its one turn per frame. Never raises.

        Creation is deferred until the polling loop exists, because the doorbell
        has nothing to ring before then and because it must be the SAME loop:
        a doorbell wired to a loop that has since been rebuilt would pull a poll
        forward on an object nobody is pumping.
        """
        # THE RADIO'S EDGE, READ FROM OUTSIDE THE RADIO'S OWN GATE (Lane H). This
        # method runs on EVERY frame, deliberately outside the polling
        # try/except, which is why the poll transport's own "nothing below here
        # opens a socket unless the radio says ONLINE" never covered the
        # doorbell. It is read here rather than plumbed through
        # `_on_backend_event` because that path is DIAGNOSTICS -- its sink
        # swallows, by contract, so that a broken sink cannot cost a connect --
        # and a socket release must not depend on an event being printable.
        online = self._radio_online()
        if self._nb_connect_enabled and online != self._radio_seen_online:
            self._radio_generation += 1
        lost_edge = False
        if self._radio_seen_online and not online:
            self._release_push_socket("wifi_lost")
            lost_edge = True
        self._radio_seen_online = online
        if self._push_factory is None:
            return None
        if self._revoked:
            # The 403 frame calls `_stop_push` and then falls through to here,
            # so without this the doorbell would be rebuilt in the same frame it
            # was told to stop -- and then never pumped again, because `poll`
            # returns above this call from the next frame on. A PushService
            # nobody steps holds no socket, but it does hold heap and it makes
            # `push_mode()` read "Connecting" for the rest of a boot in which
            # push is over. Decision #14 again: stop means stop.
            return None
        if self._push is None:
            reader = getattr(self._backend, "poll_loop", None)
            loop = reader() if callable(reader) else None
            if loop is None:
                return None
            try:
                self._push = self._push_factory(
                    loop, self._on_backend_event, self._push_enabled)
            except Exception as exc:
                # A doorbell that cannot even be built must cost the badge one
                # log line, not a boot. Never retried: the failure is structural
                # (a missing module, a bad credential shape), not transient.
                self._push_factory = None
                self.last_error = _error_text(exc)
                self._emit("push_unavailable", error=self.last_error)
                return None
            if self._push is None:
                self._push_factory = None
                return None
            # ONCE PER DOORBELL, HERE, because this is the only frame that has a
            # brand-new PushService. Re-binding a bound method every frame would
            # allocate one on the badge for a value that cannot change, and the
            # sink has to be in place before the FIRST session can fail.
            # Duck-typed: a badge whose `pushlink.mpy` predates the seam keeps
            # the old behaviour rather than losing its doorbell to a TypeError,
            # which is the partial-install lesson `ws_connect`'s `trace=` guard
            # paid for on a bench.
            wire_unreachable = getattr(
                self._push, "set_unreachable_sink", None)
            if callable(wire_unreachable):
                try:
                    wire_unreachable(self._note_push_unreachable)
                except Exception as exc:
                    self.last_error = _error_text(exc)
                    self._emit("push_contained", error=self.last_error)
            # THE ACTION SINK, WIRED IN THE SAME FRAME AND FOR STRONGER REASONS
            # THAN THE ONE ABOVE. The doorbell is the badge's ONLY path for a
            # remote moment now, so a service whose sink is never wired is a
            # badge that validates every broadcast correctly and then does
            # nothing with any of them -- silent, and identical on serial to a
            # venue nobody published to. It must be in place before the first
            # session can deliver, which is why it is here rather than per frame.
            #
            # Duck-typed for the partial-install lesson `ws_connect`'s `trace=`
            # guard paid for on a bench: a badge whose `pushlink.mpy` predates
            # this seam keeps its doorbell instead of losing it to a TypeError.
            # ⚠ That badge cannot play a fleet effect at all -- `actions_dropped`
            # on the OTHER side of the seam is the only symptom, so read the
            # snapshot rather than the serial line that is not there.
            wire_action = getattr(self._push, "set_action_sink", None)
            if callable(wire_action):
                try:
                    wire_action(self._on_broadcast_action)
                except Exception as exc:
                    self.last_error = _error_text(exc)
                    self._emit("push_contained", error=self.last_error)
            if self._nb_connect_enabled:
                self._push_nb_contract_validated = False
            if self._policy is not None:
                # A policy that arrived before this session applies to it.
                self._on_policy(self._policy)
            if self._quiesced:
                self._push.quiesce(self._quiesce_reason or "gate")
            elif self._pending_moment is None:
                self._pending_moment = MOMENT_SESSION_START
        if self._nb_connect_enabled and not self._push_nb_contract_validated:
            admit = getattr(self._push, "admit_establishment", None)
            if (
                not callable(admit)
                or not hasattr(self._push, "establishing")
                or not hasattr(
                    self._push, "establishment_radio_generation")
            ):
                # A cold ON artifact may never fall back to the blocking method:
                # that would print the right configuration marker while keeping
                # the measured 2.4-second frame.  Refuse push loudly; polling is
                # still the correctness transport.
                self.last_error = "Card NB push missing admit_establishment"
                self._emit("push_unavailable", error=self.last_error)
                self._push = None
                self._push_factory = None
                return None
            # Validate once per concrete PushService. Repeating getattr on the
            # method every rendered frame allocates a bound method on the badge.
            self._push_nb_contract_validated = True
        if lost_edge and self._nb_connect_enabled:
            # drop() synchronously cancels and drives a parked owner.  Do not
            # enter the same cached event loop again on the association-loss
            # frame or a stale ready callback can run after cleanup.
            return None
        if self._nb_connect_enabled and self._push_establishing():
            captured = self._push_establishment_radio_generation()
            if captured != self._radio_generation:
                # The association changed after admission.  Abort before the
                # cached loop gets a turn: once FramePump runs, a ready child can
                # complete the Upgrade and publish a socket from the old route.
                self._release_push_socket("wifi_changed")
                return None
        if (
            self._nb_connect_enabled
            and self._push_establishing()
            and not self._placement_allows_establishment()
        ):
            # OWNER RULING #22, WSS side. The badge entered a non-opted-in app
            # (or this is the exit frame) with a WSS establishment still PARKED
            # -- admitted but not yet a session. Abort the partial owner as a
            # NON-failure and re-arm: the next moment minted at the launcher /
            # on opt-in reconnects, and no demotion/backoff is charged (spec
            # §5.3(a)(4)). Aborting ONLY while `_push_establishing()` is exactly
            # what makes warm travel safe -- an ESTABLISHED session is never
            # `establishing`, so this can never tear one down. Synchronous and
            # before the cached loop gets a turn, like the `wifi_changed` abort.
            self._push_abort_parked_establishment("placement_deferred")
            return None
        if (
            self._nb_connect_enabled
            and self._push_establishing()
            and (
                self._connect_frame
                or self._chore_spent
                or self._response_continuation
            )
        ):
            # With a held task the ordinary `poll` call is itself an
            # establishment step: FramePump advances every ready task on its
            # cached loop before the root coroutine can inspect a guard.  The
            # only real frame budget is therefore to skip the whole pump.
            return None
        moment = self._pending_moment
        if self._quiesced:
            # A gate is holding: keep the moment PENDING rather than spending it
            # inside a window that cannot afford a handshake. Card item 7a.
            moment = None
        elif not online:
            # THE RADIO IS THE SAME KIND OF GATE, and it takes the same answer:
            # the moment stays PENDING. A tolerant moment spent with no radio is
            # a `client.connect()` that blocks for its own deadline and then
            # raises, which `_maybe_connect` correctly scores as a FAILED
            # SESSION -- and three of those is `DEMOTE_AFTER_SESSIONS`, so a walk
            # out of range used to cost a wearer their doorbell for the rest of
            # the boot. `PushPolicy.note_session_failed`'s own docstring says
            # that counter must only ever hear about push, and this is the line
            # that makes it true of the radio.
            #
            # `_wants_moment` is SHORT-CIRCUITED rather than consulted-and-
            # ignored. Asking is cheap, but the answer cannot be acted on, and a
            # gate that asks anyway is a gate the next reader tries to satisfy
            # from the push side.
            moment = None
        elif (
            self._nb_connect_enabled
            and not self._placement_allows_establishment()
        ):
            # OWNER RULING #22: a non-opted-in app (or the exit frame) mints no
            # new establishment moment -- the ~2.3 s WSS join defers to the
            # launcher / an opt-in. A warm session keeps polling below (warm
            # travel); the parked-attempt abort above already cleared any
            # partial owner. This is a placement deferral, NOT a failure: it
            # touches no due/backoff/forgiveness/demotion counter (§5.3(a)(4)).
            moment = None
        elif (
            self._nb_connect_enabled
            and (self._chore_spent or self._response_continuation)
        ):
            # Admission itself drives the newly-created task once before its
            # run_until_complete root returns. Therefore the correctness chore
            # and response-continuation barriers apply before the FIRST held
            # step just as they apply to every later held step above. Retain the
            # pending moment for the next clean frame.
            moment = None
        elif self._connect_frame:
            # ONE TRANSPORT CONNECT PER FRAME (Lane H). The poll transport opened
            # -- or tried to -- inside `backend.poll` earlier in THIS frame, so
            # the doorbell waits for the next one.
            #
            # THE FRAME THIS EXISTS FOR IS THE RETURN FROM A ROAM.
            # `DeviceBackend.poll`'s `wifi_online` edge calls
            # `PollLoop.request_reconnect`, which sets the next due to `now`, so
            # the SAME frame performs the open; and the doorbell's socket is gone
            # (released on the `wifi_lost` edge), so `_wants_moment` says yes in
            # that same frame. Measured device costs: a healthy re-open is
            # 953-1,757 ms and the WSS join leg is 2,252-2,436 ms
            # ("remarkably stable in all three runs" -- the 2026-08-25 freeze
            # capture, whose finding 1 is that the join leg IS the freeze the
            # owner felt). Their sum is a frame nobody should have to render.
            # Waiting one frame costs the doorbell 27 ms.
            #
            # It also covers the BOOT pile-up frame, which is the same shape:
            # `start` arms the open for the frame that built the loop, so the
            # 1,209 ms/seven-step frame used to be handed MOMENT_SESSION_START as
            # well. The moment stays PENDING; nothing is lost.
            #
            # SCOPED TO CONNECTS, and deliberately not to responses. An ordinary
            # ~11 ms exchange response sharing a frame with a doorbell attempt is
            # what `--arm wss`'s `transports_never_share_a_frame` verdict reads,
            # and that verdict stays ungated: the two costs are three orders of
            # magnitude apart, and a rule that made a doorbell wait for every
            # poll RESPONSE would starve it on the 3 s active cadence.
            moment = None
        elif not self._wants_moment(now):
            # The boot jitter or the reconnect backoff has not run out, so a
            # tolerant moment spent now would open nothing — and on a badge
            # sitting on the launcher there may be no next one for a long time.
            moment = None
        elif self._nb_connect_enabled and not self._push_address_is_ready():
            # Ask only when a closed/due push link would actually consume an
            # admission. A roam invalidates the shared resolver answer; the
            # poll link may retry its retained address and, after a
            # TLS-authenticated success, re-share it. Until then an ON WSS start
            # would fall through to MicroPython getaddrinfo inside a held task,
            # an untimeoutable C call in an ordinary frame. Retain the moment.
            moment = None
        else:
            if moment is None:
                # A SCHEDULED RECONNECT. Every wearer-caused moment has already
                # been spent, so this is the launcher paying for a retry whose
                # jittered backoff has run out. See MOMENT_RECONNECT_DUE for what
                # bounds it and why the alternative is worse.
                moment = MOMENT_RECONNECT_DUE
            if not self._nb_connect_enabled:
                self._pending_moment = None
        # TWO TICKS AROUND THE ONE THING THIS MODULE DOES EVERY FRAME. The pump
        # is `run_until_complete` of a coroutine that yields once, and F21 could
        # not say how much of its 52 ms p99 belonged to it. Now it can: the
        # ordinary pump rolls up (PUSH_PUMP_ROLLUP), and a TOLERANT MOMENT --
        # which is the 735 ms WebSocket handshake -- gets a line of its own,
        # because averaging a handshake into a per-frame pump would hide both.
        entered = _ticks_ms()
        spent_moment = None
        try:
            if moment is not None:
                if self._nb_connect_enabled:
                    accepted = self._push.admit_establishment(
                        moment,
                        now,
                        self._enabled,
                        self._radio_generation,
                    )
                    if accepted:
                        self._pending_moment = None
                        spent_moment = moment
                    self._note_push_step(entered, spent_moment)
                    return accepted
                # OFF's blocking call can raise.  Its frame is still the named
                # tolerant moment, so denominate it before entering rather than
                # misreporting the exception as an ordinary push-pump sample.
                spent_moment = moment
                result = self._push.tolerant_moment(moment, now, self._enabled)
                self._note_push_step(entered, moment)
                return result
            if self._nb_connect_enabled:
                # Production keeps a healthy WSS. This gate remains for the
                # explicit diagnostic reconnect seam; a TRUE token/grant expiry
                # still fails CLOSED and placement must not veto it.
                reauth_gate = getattr(
                    self._push, "set_establishment_allowed", None)
                if callable(reauth_gate):
                    reauth_gate(self._placement_allows_establishment())
            result = self._push.poll(now, False, self._enabled)
            self._note_push_step(entered, None)
            return result
        except Exception as exc:
            self._note_push_step(entered, spent_moment)
            self.last_error = _error_text(exc)
            self._emit("push_contained", error=self.last_error)
            return None

    def _push_abort_parked_establishment(self, reason):
        """Abort a PARKED WSS establishment as a non-failure. Never raises.

        For OWNER RULING #22 placement: a warm session is never `establishing`,
        so the PushService's own guard makes this a no-op on one -- warm travel
        is safe by construction. Distinct from `_release_push_socket`, which is
        the `wifi_lost` HARD drop and closes a healthy session too. Duck-typed:
        a push seam that predates `abort_establishment` simply cannot be asked,
        which is the pre-NB-0 behaviour (there was no parked attempt to abort).
        """
        push = self._push
        if push is None:
            return False
        aborter = getattr(push, "abort_establishment", None)
        if not callable(aborter):
            return False
        try:
            return bool(aborter(reason))
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("push_contained", error=self.last_error)
            return False

    def _push_establishing(self):
        """Whether the ON doorbell owns a parked attempt. Never raises."""

        push = self._push
        if push is None:
            return False
        try:
            value = getattr(push, "establishing", False)
            return bool(value() if callable(value) else value)
        except Exception:
            return False

    def _push_establishment_radio_generation(self):
        """Association epoch captured by the ON attempt, or ``None``."""

        push = self._push
        if push is None:
            return None
        try:
            value = getattr(push, "establishment_radio_generation", None)
            return value() if callable(value) else value
        except Exception:
            return None

    def _push_address_is_ready(self):
        """Whether ON establishment can avoid blocking DNS. Never raises."""

        backend = self._backend
        asker = getattr(backend, "push_address_ready", None)
        if not callable(asker):
            # Old fixtures and non-device backends keep their historical shape.
            # The production DeviceBackend always answers this in the same
            # coupled bytecode unit as NetworkService.
            return True
        try:
            return bool(asker())
        except Exception:
            # A broken product gate must fail closed: retrying later is cheaper
            # than entering an unbounded resolver from a rendered frame.
            return False

    def _note_push_step(self, entered, moment):
        """One doorbell turn, priced. Never raises, never allocates per frame.

        A tolerant moment emits immediately (there are a handful per boot). The
        ordinary pump only touches integers until the window closes, so 127 of
        every 128 frames allocate nothing here at all.
        """
        span = _ticks_diff(_ticks_ms(), entered)
        if span < 0:
            span = 0
        if moment is not None:
            self._emit("push_moment", moment=moment, ms=span)
            return
        self._push_pumps += 1
        self._push_pumps_total += 1
        self._push_busy_ms += span
        self._push_busy_total_ms += span
        if span > self._push_peak_ms:
            self._push_peak_ms = span
        if span > self._push_peak_session_ms:
            self._push_peak_session_ms = span
        if self._push_pumps >= PUSH_PUMP_ROLLUP:
            self._emit("push_pump", pumps=self._push_pumps,
                       busy_ms=self._push_busy_ms, peak_ms=self._push_peak_ms)
            self._push_pumps = 0
            self._push_busy_ms = 0
            self._push_peak_ms = 0

    def _wants_moment(self, now):
        """Whether the push service could use a tolerant moment right now.

        Duck-typed: a service that does not answer is assumed to want it, which
        keeps the old behaviour for anything that predates this seam.
        """
        asker = getattr(self._push, "wants_tolerant_moment", None)
        if not callable(asker):
            return True
        try:
            return bool(asker(now, self._enabled))
        except Exception:
            return True

    def _radio_online(self):
        """Is the radio ONLINE?  ``True`` when nothing here can say.

        Duck-typed exactly like `set_policy_sink` and `force_active_cadence`: a
        backend shape that predates this seam -- the two-argument factory Card PW
        shipped, every fixture built against it -- answers nothing and gets the
        old behaviour, which is "assume the radio is up". That default is the
        conservative one for a FAKE and the wrong one for a badge, which is why
        `DeviceBackend` answers.

        ONLINE means what `DeviceBackend.poll` means by it: `ResilientWiFi.tick`
        returned `ONLINE`, and on CYW43 `isconnected()` is true only once an
        address has been assigned. So this is not "associated", it is "routable
        as far as the radio can tell".
        """
        asker = getattr(self._backend, "wifi_online", None)
        if not callable(asker):
            return True
        try:
            return bool(asker())
        except Exception:
            # A backend that raises when asked about its own radio is a backend
            # in trouble, and the containment rule everywhere else in this module
            # applies: diagnostics may never decide a connect. Assume up, which
            # is the pre-Lane-H behaviour.
            return True

    def _radio_online_for_display(self):
        """Is the radio ONLINE?  ``False`` when nothing here can say.

        ⚠ **THE DEFAULT IS THE EXACT OPPOSITE OF :meth:`_radio_online`'S, AND
        THE ASYMMETRY IS THE POINT RATHER THAN AN INCONSISTENCY.** That method
        fails OPEN because it GATES A CONNECT, where a wrong deny is a badge
        that never networks at all. This one feeds a SENTENCE, and a wrong
        "online" is the precise lie the Network screen exists to end: a badge
        that has never touched its radio drawing "Connecting to the server"
        while it hunts for an access point it will never find. A gate and a
        diagnostic want opposite defaults, so they are two methods rather than
        one with a flag -- a flag is a thing a future caller passes wrongly.

        Identical in every other respect: duck-typed for the fixtures and the
        browser lane, contained because a raise on a draw path is
        `machine.reset()`, and reading the same `_was_online` the
        `wifi_lost`/`wifi_online` edges are emitted from, so the panel and the
        edge can never disagree.
        """

        asker = getattr(self._backend, "wifi_online", None)
        if not callable(asker):
            return False
        try:
            return bool(asker())
        except Exception:  # noqa: BLE001 - a reset is the alternative
            return False

    def _backend_connect_attempts(self):
        """How many opens the poll transport has ATTEMPTED, or ``None``.

        Attempts rather than successes, because a failed open costs the frame the
        same thing: a blackholed one is the whole `OPEN_BUDGET_MS`, and a blocked
        resolver was measured at 16,119 ms in ONE frame. A counter rather than a
        state transition for the same reason -- an open that ended in BACKOFF
        never reached CONNECTED and still spent the budget.

        Duck-typed like `wifi_online`: a backend that cannot count answers
        ``None``, both samples are ``None``, they compare equal, and nothing is
        withheld. That is the pre-Lane-H behaviour exactly.
        """
        asker = getattr(self._backend, "connect_attempts", None)
        if not callable(asker):
            return None
        try:
            return asker()
        except Exception:
            return None

    def _frame_connect_sample(self):
        """The per-frame connect token sampled either side of `backend.poll`.

        ON reads `establishment_steps` -- which moves on loop preparation AND on
        every parked `open_step`, so a multi-frame open reads as a connect frame
        on EVERY frame it advances, not only the attempt-start frame
        `connect_attempts` names (the hole that let a poll continuation share a
        frame with the WSS join). OFF reads `connect_attempts` unchanged.
        """
        if self._nb_connect_enabled:
            return self._backend_establishment_steps()
        return self._backend_connect_attempts()

    def _backend_establishment_steps(self):
        """`DeviceBackend.establishment_steps`, or the attempt fallback.

        Duck-typed like `_backend_connect_attempts`: a backend that predates the
        seam (old fixtures, the two-argument factory) falls back to
        `connect_attempts`, so the sample still moves once per open rather than
        never. A backend that raises fails to the same fallback.
        """
        asker = getattr(self._backend, "establishment_steps", None)
        if not callable(asker):
            return self._backend_connect_attempts()
        try:
            return asker()
        except Exception:
            return self._backend_connect_attempts()

    def _note_push_unreachable(self, cause="unreachable"):
        """The doorbell says nothing answered; the backend forgets its addresses.

        THIS SERVICE IS THE ONLY OBJECT THAT SEES BOTH HALVES, which is the whole
        reason the seam is here. `pushlink` knows WHY the doorbell demoted and
        must not learn what DNS is; `DeviceBackend` owns the shared address cache
        and the ON readiness bit and cannot see a push demotion; and
        `device_push_factory`'s three-argument signature is frozen by the
        generated `/system/main.py` block, so the backend cannot be handed to it.
        The service holds `self._push` and `self._backend` and joins them.

        NOT THROUGH `_on_backend_event`, for the reason Lane H already wrote at
        the top of `_service_push`: that sink SWALLOWS by contract, so a broken
        or absent printer would silently disable this. A cache correction is not
        diagnostics.

        Duck-typed and contained, like every other backend reach here: a fixture
        backend, or a badge whose `network_runtime` is newer than the module that
        built its backend, simply keeps the old behaviour. Never raises --
        `_service_push` promises that and this can be reached from inside it.
        """

        backend = self._backend
        forgetter = getattr(backend, "note_push_unreachable", None)
        if not callable(forgetter):
            return None
        try:
            return forgetter(cause)
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("push_contained", error=self.last_error)
            return None

    def _release_push_socket(self, reason):
        """Let go of the doorbell's socket, ABRUPTLY, and charge nobody for it.

        THREE THINGS ARE DELIBERATE HERE and each one was the shorter call's
        mistake:

        * **`drop`, not `stop`.** Both close the socket without charging the
          demotion counter (`PushLink.stop` passes ``count_failure=False``), but
          `drop` skips the POLITE close -- no `phx_leave` per joined channel and
          no WebSocket CLOSE frame. Each of those is a write whose `drain()`
          carries `io_timeout_ms`, so being courteous to an access point that is
          out of range is a theoretical 10 s of frame time (5,000 ms twice) at
          the exact moment the badge has established the peer is unreachable.
          Duck-typed, so a doorbell that predates the seam still lets go through
          the polite path -- letting go matters more than how.
        * **NOT `_stop_push`.** That sets `self._push` to `None`, so the next
          tolerant moment builds a fresh `PushLink` with a fresh `PushPolicy` --
          which resets `failed_sessions`, `demoted` AND `revoked`. A revoked
          badge that walked out of range would come back ringing. The socket is
          what the radio invalidated; the doorbell is not.
        * **The socket is released rather than abandoned.** Nothing runs layer
          1's ping timer or layer 2's heartbeat for a socket the far end still
          believes in, so an abandoned one survives to ITS ceiling (20-30 s) with
          the TLS buffers allocated on a 520 KB heap. This is the same argument
          the 403 path makes twenty lines above `_stop_push("revoked")`.
        """
        push = self._push
        if push is None:
            return None
        dropper = getattr(push, "drop", None)
        closer = dropper if callable(dropper) else getattr(push, "stop", None)
        if not callable(closer):
            return None
        try:
            return closer(reason)
        except Exception as exc:
            # Releasing a socket must never be the thing that costs a frame its
            # app. Same containment as `_stop_push`.
            self.last_error = _error_text(exc)
            self._emit("push_contained", error=self.last_error)
            return None

    def _stop_push(self, reason):
        push = self._push
        if push is None:
            return
        try:
            push.stop(reason)
        except Exception as exc:
            self.last_error = _error_text(exc)
        self._push = None
        if self._nb_connect_enabled:
            self._push_nb_contract_validated = False
        self._pending_moment = None

    def _stop_backend(self):
        # A backend rebuild invalidates every transient remote intent even when
        # the caller did not come through Settings. Total cleanup restores the
        # two physical channels before sockets and their callbacks disappear.
        self._clear_remote_effects()
        # AND THE SCORE DRAIN'S LATCH GOES WITH THE SINK IT NAMES. `_pump_scores`
        # releases it whenever the transport is not CONNECTED, which covers every
        # ordinary outage -- but a stop followed by a rebuild can put a FRESH
        # backend in place inside one frame, and a drain that only ever asks
        # `state == CONNECTED` would never see the gap. The sink is a callback on
        # a queue that is about to be garbage: it can no longer fire at all, so
        # the entry stays spooled and the next connect re-offers it. Nothing is
        # retired here for the same reason nothing is counted: the row's fate is
        # unknown, and the natural key `(badge_id, game, play_number, score)`
        # makes asking again free (`on conflict do nothing`).
        self._score_inflight = None
        self._score_inflight_at = None
        # AND SO DO THE TWO SCHEDULE LATCHES, for word for word the reason above.
        # A rebuilt loop takes its errand queue and every parked sink to the
        # collector with it, so these responses cannot arrive however long the
        # pumps wait -- and the rebuild can install a fresh CONNECTED backend
        # inside the SAME frame, which is precisely the gap a pump that only ever
        # asked `state == CONNECTED` would never see. Nothing is consumed on the
        # way out: no attempt is counted, no `done` is set and the app's parked
        # sink is left where it is, so the next connect simply asks again.
        if self._schedule_v2_inflight:
            self._release_schedule_v2("backend_stopped")
        if self._schedule_inflight:
            self._release_schedule_sync("backend_stopped")
        # The doorbell is wired to THIS loop; a new backend gets a new one.
        self._stop_push("backend_stopped")
        backend = self._backend
        self._backend = None
        if backend is not None:
            try:
                backend.stop()
            except Exception as exc:
                self.last_error = _error_text(exc)
        gc.collect()

    # -- the broadcast lane (2026-08-29) -----------------------------------
    #
    # MOMENTS ARE BROADCAST, STATES ARE POLLED, AND THERE IS NO COMMAND QUEUE.
    # `pushlink` validates an envelope on the shared `event:doorbell` topic and
    # hands the action here; this is where the badge ACTS on it, and then says
    # so. Three methods and each owns exactly one of the three things that used
    # to be tangled together in `_on_command`:
    #
    #   `_on_broadcast_action`   accept-or-refuse, on the WS drain's frame
    #   `_pump_broadcast_actions` apply exactly one, under the chore budget
    #   `_pump_receipts`          post the write-back, after its jitter
    #
    # THE SPLIT IS THE FRAME, and it is not tidiness. `pushlink` calls the sink
    # from inside layer 2's drain loop, which drains up to four WS frames per
    # RENDERED frame, so a sink that applied would put up to four appliers --
    # each of which may light both channels and one of which may launch an app --
    # on a single frame, and the first of them would take CX-10's one chore and
    # leave the rest unbudgeted. The sink therefore does nothing expensive at
    # all: a membership test, a bounds check, an append.
    #
    # AND THE RECEIPT IS SPLIT OFF FOR THE OPPOSITE REASON. It must not be able
    # to affect whether the show played, so it cannot share a failure path with
    # the applier: the action is applied and counted first, the receipt is armed
    # afterwards, and every way the receipt can fail (a full errand queue, no
    # backend, a refused POST) is swallowed and counted here.

    def _on_broadcast_action(self, action_id, action_type, payload,
                             receipt_delay_ms):
        """Take one validated broadcast action, or refuse it.  Never raises.

        THE SINK `pushlink.set_action_sink` CALLS, and its whole contract is
        "cheap and total". It runs inside a rendered frame, inside layer 2's
        drain loop, in a module that has already contained it once -- so the
        containment here is the second of two, not the first, and it exists
        because the counters below have to be right even when something above
        them is not.

        RETURNS TRUE WHEN THE BADGE OWNS THIS ACTION -- including when it owns it
        because it has ALREADY seen it. A duplicate is not a loss and must not be
        counted as one: `pushlink.actions_dropped` is the diagnostic for "the
        badge understood a broadcast and nothing happened", and folding correct
        de-duplication into it would make the one number that finds a dead
        light-show lane read nonzero on a healthy badge.
        """

        try:
            if not isinstance(action_id, str) or not action_id:
                return False
            if action_id in self._action_ids:
                # DUPLICATE ARRIVAL, WHICH IS ORDINARY. One publish can be
                # drained more than once inside one frame; without this the show
                # plays twice on this badge and once on its neighbour, which is
                # the failure `command_ledger`'s RAM half used to prevent for the
                # poll. See `ACTION_MEMORY` for why the RAM half is all that is
                # needed now.
                #
                # *** COUNTED, NOT EMITTED, AND THIS ONE IS MEASURED. *** It
                # emitted until 2026-08-29 and that was a real per-frame cost on
                # the RENDERED path: layer 2 drains up to `FLEET_DRAIN_MAX` (4)
                # frames per rendered frame, `_emit` allocates a dict and
                # `_print_event` formats a string, and a probe over identical
                # frame counts measured an idle frame at ~55 B of net heap
                # against ~1,028 B when four duplicates arrived -- 19x, sustained,
                # on the frame that paints the UI, on a runtime where the GC pause
                # IS the freeze. The event NAME also still printed, and a blocked
                # `print` on this hardware is ~1,000 ms, so the ordinary case was
                # also the fastest way in the firmware to burn the serial mute
                # budget and blind a tethered operator mid-show.
                #
                # THE RULE IS THE ONE THE OVERFLOW BRANCH BELOW ALREADY QUOTES
                # and `pushlink`'s no-sink branch already follows: the event name
                # is the line, the snapshot is the quantity. `_note_first_action_
                # anomaly` keeps ONE line per boot for diagnosis, which is the
                # `link_unaddressed` shape -- enough to find it, bounded enough
                # to be free.
                self.actions_duplicate += 1
                self._note_first_action_anomaly("action_duplicate", action_type)
                return True
            if len(self._actions) >= BROADCAST_ACTION_MAX:
                # THE NEWEST IS THE ONE DROPPED. Everything already queued is
                # closer to the moment it describes, and a moment applied late is
                # worse than a moment not applied -- the same ruling that makes
                # catch-up a BUG for moments and free for states.
                self.actions_dropped += 1
                # THE EVENT NAME IS THE LINE, THE SNAPSHOT IS THE QUANTITY --
                # the rule `doorbells_filtered` already follows. A `queued=`
                # field here would be a new printed field for a number
                # `actions_dropped` already carries. Same one-shot treatment as
                # the duplicate above: a publisher storming a full queue would
                # otherwise repeat this line on every rendered frame.
                self._note_first_action_anomaly("action_overflow", action_type)
                return False
            self._action_ids.append(action_id)
            if len(self._action_ids) > ACTION_MEMORY:
                del self._action_ids[0]
            self._actions.append((action_id, action_type, payload,
                                  receipt_delay_ms))
            return True
        except Exception as exc:
            # A sink that raises into layer 2 would cost this badge the socket
            # every later action arrives on.
            self.last_error = _error_text(exc)
            self._emit("action_contained", error=self.last_error)
            return False

    def _note_first_action_anomaly(self, event, action_type):
        """Emit ONE broadcast-lane anomaly line per boot, then never again.

        THE SHAPE IS `link_unaddressed`'s, and the reason is the same: the fact
        that it happened AT ALL is worth a serial line, and the number of times
        it happened is worth a counter, and confusing the two puts an allocation
        and a `print` on a rendered frame in the ordinary case.

        One line for the whole lane rather than one per event name, because both
        callers mean the same thing to an operator -- "broadcasts are arriving
        that this badge did not turn into a show" -- and the counters
        (`actions_duplicate`, `actions_dropped`) say which and how many. Total:
        a failure to say so may not cost the action that provoked it.
        """

        if self._action_anomaly_noted:
            return
        self._action_anomaly_noted = True
        try:
            self._emit(event, verb=action_type)
        except Exception as exc:
            self.last_error = _error_text(exc)

    def _pump_broadcast_actions(self, now):
        """Apply at most ONE queued broadcast action.  Never raises.

        ONE PER FRAME AND IT SPENDS THE CHORE, which is what makes this safe to
        call from the frame path at all: `_apply` reaches appliers that light
        both channels, write `/state`, and in `open_app`'s case launch an app.

        IT DISPATCHES THROUGH `_apply` UNCHANGED, and that is the acceptance
        requirement rather than a convenience. The frozen `effect_library` runs
        exactly as it does today because the code that reaches it is exactly the
        code that reached it before -- same ladder, same appliers, same payload
        contract, same raise-is-a-failure rule. Only the DELIVERY changed.

        THERE IS NO LATE-JOIN PHASE. A broadcast arrives when it arrives, within
        one fan-out window of every other connected badge; offline badges miss
        it. Reintroducing phase correction here would also reintroduce the
        scheduling/catch-up model the owner deleted.

        AN UNKNOWN VERB IS A RAISE FROM `_apply`'s terminal clause, which lands
        in the same place a bad payload does: counted, emitted, receipted as
        failed, and never rendered. That is the "logged and dropped" rule, and it
        is one branch rather than two on purpose -- a firmware that half-knows a
        verb is the thing that renders something nobody chose.
        """

        if not self._actions:
            return False
        if not self._claim_chore():
            return False
        action_id, action_type, payload, receipt_delay_ms = self._actions.pop(0)
        # THIS FRAME DID CORRECTNESS WORK. `_service_push` runs later in the same
        # `poll` and reads this barrier before admitting a WSS establishment, so
        # a TLS/Upgrade step cannot stack onto the frame that just lit the panel.
        # The same reason `_on_command` raised it, at the same point in the frame.
        self._response_continuation = True
        # REAL APPLIERS WRITE FRAME ZERO IMMEDIATELY, and `_pump_effect` runs
        # after this in the same `poll`. Remember only a NEWLY installed object so
        # the steady pump does not step it a second time in this rendered frame;
        # this marker is the only same-frame arbitration the broadcast needs.
        lights_before = self._lights
        effect_before = self._effect
        power_before = self._power
        try:
            # THE APPLIER'S RICH RESULT IS DISCARDED, and that is a real loss
            # worth naming: `_apply_play_effect` answers a whole-show diagnostic
            # result, while the receipt column is text (see RECEIPT_OK), so it
            # cannot carry it. What replaced it is better for the question an
            # operator actually asks during a show -- "who played it?" -- and the
            # detail is still on serial in `action_applied`.
            self._apply({"type": action_type, "payload": payload})
        except Exception as exc:
            self.actions_failed += 1
            self.last_error = _error_text(exc)
            self._emit("action_failed", verb=action_type,
                       error=self.last_error)
            # THE WORD, NOT THE EXCEPTION TEXT. The console's column is text and
            # its refusal vocabulary is a fixed set; an error string would be
            # counted as a SUCCESS there ("an unrecognised string is shown
            # verbatim and counted as an answer"). The detail is already on
            # serial, in the `action_failed` event above, where an operator
            # debugging one badge can read it.
            result = RECEIPT_FAILED
        else:
            self.actions_applied += 1
            self._emit("action_applied", verb=action_type)
            result = RECEIPT_OK
        if self._lights is not None and self._lights is not lights_before:
            self._lights_stepped_frame = self._lights
        if self._effect is not None and self._effect is not effect_before:
            self._effect_stepped_frame = self._effect
        # ARMED AFTER THE APPLIER, OUTSIDE ITS TRY, AND TOTAL. Ordinary shows
        # have already played and cannot be vetoed. A power applier has only
        # armed its latch; its own terminal receipt attempt delays teardown but
        # never decides whether teardown ultimately happens.
        receipt_armed = self._arm_receipt(
            now, action_id, result, receipt_delay_ms)
        if result == RECEIPT_OK and self._power is not power_before:
            # Sleep/radio-off destroy the very channel this row needs. Bind only
            # the power latch created by THIS action; a later ordinary broadcast
            # must never claim an older pending latch's receipt by accident.
            self._bind_power_receipt(now, action_id, receipt_armed)
        return True

    def _arm_receipt(self, now, action_id, result, receipt_delay_ms):
        """Hold one receipt for its jitter. Never raises or vetoes an action.

        THE DELAY COMES FROM THE LINK, NOT FROM HERE. `pushlink.ring_delay_ms`
        draws it PER RING inside the 0-5 s window and hands it over; re-drawing
        it in this file would be two objects with two opinions about one number,
        which is CX-8 exactly. :data:`RECEIPT_JITTER_MAX_MS` is only the clamp
        for a link that hands over something unusable.
        """

        try:
            delay = int(receipt_delay_ms)
        except Exception:
            delay = RECEIPT_JITTER_MAX_MS
        if delay < 0 or delay > RECEIPT_JITTER_MAX_MS:
            delay = RECEIPT_JITTER_MAX_MS
        if len(self._receipts) >= RECEIPT_MAX_PENDING:
            # A MISSING ROW IN AN AUDIT TABLE, NOT A MISSING SHOW. Counted and
            # dropped, deliberately without a spool: a receipt that outlives the
            # moment it describes is worth less than the flash write it would
            # cost, and ~1,000 badges retrying one is the stampede this whole lane
            # is jittered to avoid, rebuilt at a slower cadence.
            self.receipts_dropped += 1
            return False
        # INSERTED IN DUE ORDER, NOT APPEND ORDER, because `_pump_receipts` reads
        # only the head and the two orders are NOT the same here: the delay is
        # drawn fresh per ring, so an action applied later with a 0 ms draw is due
        # before one applied earlier with a 5,000 ms draw. Appending would let the
        # first block the second for the whole of its jitter -- harmless in size
        # (the window is five seconds) but it would make "oldest first" a comment
        # that is not true, which is the kind of small lie that later gets built
        # on. `_ticks_diff` rather than `<` because `ticks_ms` WRAPS.
        due = _ticks_add(now, delay)
        entry = [due, action_id, result, 0]
        for index in range(len(self._receipts)):
            if _ticks_diff(due, self._receipts[index][0]) < 0:
                self._receipts.insert(index, entry)
                return True
        self._receipts.append(entry)
        return True

    def _bind_power_receipt(self, now, action_id, receipt_armed):
        """Make a newly armed broadcast power action wait for its own receipt.

        The applier cannot bind this itself because the broadcast envelope owns
        ``action_id`` and the pure `_apply` ladder deliberately does not. A
        failed/overflowed receipt is already terminal and therefore does not
        delay the action; a held receipt gets one hard deadline and no replay.
        """

        power = self._power
        if power is None or power.get("needed") != 0:
            return False
        if power.get("receipt_action_id") is not None:
            return False
        power["receipt_action_id"] = action_id
        power["receipt_done"] = not bool(receipt_armed)
        power["receipt_status"] = "unavailable" if not receipt_armed else None
        power["receipt_deadline"] = _ticks_add(
            now, POWER_ACTION_RECEIPT_MS)
        return True

    def _finish_power_receipt(self, action_id, status):
        """Release only the power latch whose receipt reached a terminal state."""

        power = self._power
        if power is None or power.get("receipt_action_id") != action_id:
            return False
        power["receipt_done"] = True
        power["receipt_status"] = status
        return True

    def _receipt_sink(self, action_id):
        """One keyed callback, because the errand sink receives no request id.

        At most four receipts exist, so this tiny closure is cheaper and safer
        than a parallel FIFO that assumes transport callbacks can never be
        reordered while reconnecting. Superseded power latches simply ignore a
        late callback whose action id no longer matches.
        """

        def posted(ok, data):
            self._finish_power_receipt(
                action_id, "posted" if ok else "failed")
            return self._on_receipt_posted(ok, data)

        return posted

    def _pump_receipts(self, now):
        """Queue whatever receipt has waited out its jitter.  Never raises.

        ONE PER FRAME AND NO CHORE CLAIMED. Building this row is a dict and a
        `_queue_errand` hand-off -- no file, no parse, no crypto -- so taking the
        frame's one expensive slot for it would starve the score drain and the
        schedule sync for work that costs neither of them anything. It is the
        same argument `_pump_effect` makes for its own bounded slots.

        A REFUSED QUEUE IS RE-ARMED A FEW TIMES AND THEN DROPPED. The errand
        channel holds four slots and the heartbeat, the settings read and the
        score drain all want them, so a full queue right after a fleet show is
        foreseeable rather than exotic -- but the retry is bounded hard, because
        an unbounded one is the fleet-wide write storm again with extra steps.
        """

        if not self._receipts:
            return False
        entry = self._receipts[0]
        if _ticks_diff(now, entry[0]) < 0:
            return False
        badge_id = hardware_uid()
        if badge_id is None:
            # NO IDENTITY, NO RECEIPT. `x-badge-id` is the RLS identity and the
            # row's own `badge_id` column is the same value; a receipt that
            # cannot name its badge is a row nobody can read anything from.
            # `link_unaddressed` has already said this once per boot.
            del self._receipts[0]
            self.receipts_dropped += 1
            self._finish_power_receipt(entry[1], "unaddressed")
            return False
        import rpc_contract

        # NO `at`. THE SERVER STAMPS IT, and the reason is that the badge cannot
        # honestly beat it: `_epoch()` is None on any badge that never reached
        # NTP, so the column needs a `default now()` for those badges REGARDLESS
        # -- and once the default has to exist, a second clock that disagrees
        # with it by the receipt's own jitter buys an audit row nobody reads
        # live a few seconds of precision, at the price of a hand-rolled ISO-8601
        # formatter on a runtime whose `time.gmtime` epoch is not the Unix one.
        # That trade is the wrong way round for a one-day event. ⚠ The
        # `fleet_receipts` DDL must therefore carry `at timestamptz not null
        # default now()`.
        queued = self._queue_errand(
            "table",
            {"table": rpc_contract.TABLE_FLEET_RECEIPTS, "method": "POST",
             "row": {"action_id": entry[1], "badge_id": badge_id,
                     "result": entry[2]},
             # IDEMPOTENT UNDER `(action_id, badge_id)`. A 409 would land in
             # `parse_response`'s generic retryable bucket, and a retryable
             # receipt is the storm again.
             "prefer": rpc_contract.PREFER_IGNORE_MINIMAL},
            self._receipt_sink(entry[1]),
            # NOT COALESCED. `badge_state` coalesces because a stale snapshot
            # superseded by a fresh one is worth nothing; two receipts describe
            # two different actions and neither replaces the other.
        )
        if queued:
            del self._receipts[0]
            self.receipts_queued += 1
            return True
        entry[3] += 1
        if entry[3] >= RECEIPT_QUEUE_TRIES:
            del self._receipts[0]
            self.receipts_dropped += 1
            self._emit("receipt_dropped")
            self._finish_power_receipt(entry[1], "queue_refused")
            return False
        entry[0] = _ticks_add(now, RECEIPT_RETRY_MS)
        return False

    def _on_receipt_posted(self, ok, _data):
        """The write-back landed, or it did not.  Either way the show played.

        NO RETRY LADDER HANGS OFF THIS, and that is the design rather than an
        omission. The errand channel reports `(ok, data)` with no HTTP status, so
        this cannot tell a transient failure from a refusal -- and a receipt
        retried until it lands is ~1,000 badges retrying one row, which is the herd
        the jitter above exists to break up. One counter, one line, done.
        """

        if ok:
            return
        self.receipts_dropped += 1
        self._emit("receipt_failed")

    def _on_command(self, command):
        """One command: effect, then RAM ledger, then flash, then the ack.

        THE ORDER IS THE CORRECTNESS ARGUMENT and it has four steps, not three.

        1. **The effect**, inside its own handler, so a bad payload becomes a
           ``failed`` ack rather than a dead transport.
        2. **The RAM ledger** (`command_ledger.remember`, a PURE function). This
           is what makes a redelivery on the SAME boot a re-ack: `_on_command`
           takes the ``prior`` branch above and the physical action does not
           repeat.
        3. **The durable ledger**, INSIDE ITS OWN TRY (CX-7). Until 2026-08-23
           `save()` sat bare between the effect and the ack, so a full or
           read-only LittleFS turned one command into an ``OSError`` that walked
           out through `polltransport._process_response`'s unguarded sink call
           into `NetworkService.poll`'s handler: the effect had fired, the ack was
           never queued, EVERY LATER COMMAND IN THE SAME RESPONSE was skipped
           along with that response's steering fields, ``_need_full_resync`` was
           left set, and the transport paid a full reconnect. The write is now
           swallowed and counted (`ledger_save_failures`, `_ledger_dirty`, ONE
           bounded diagnostic) and `_pump_ledger_persist` retries it from a
           chore-budgeted frame.
        4. **The ack**, which now always happens.

        **THE RESIDUAL IS DESIGN, NOT AN OVERSIGHT.** If the badge resets after
        the effect but before the server hears the ack, AND the durable write did
        not land, the next boot has nothing to read and repeats the effect ONCE;
        the server's five-attempt cap bounds it from there. Storage cannot close
        that window -- closing it is exactly the write that just failed -- so the
        honest fix is a bounded retry plus a counter, and the replay stays.
        """
        command_id = command.get("id") if isinstance(command, dict) else None
        if not isinstance(command_id, str) or not command_id:
            return
        # This callback runs INSIDE the poll response frame. Effect dispatch,
        # durable ledger save and ack construction all happen before it returns;
        # mark that frame before any of them so a held or newly-admitted WSS task
        # cannot stack its next TLS/Upgrade step onto the correctness work.
        self._response_continuation = True
        prior = command_ledger.find(self._ledger, command_id)
        if prior is not None:
            self._backend.queue_ack(dict(prior))
            self._emit("command_reacked", command=command.get("type"))
            return
        try:
            # The durable command table is gone. Keeping this compatibility
            # callback total is cheap, but it applies immediately: no hold,
            # catch-up, or future-fire path may be reconstructed behind it.
            result = self._apply(command)
            status = "applied"
        except Exception as exc:
            status = "failed"
            result = {"error": _error_text(exc)}
        ack = {"id": command_id, "status": status, "result": result}
        # Persist BEFORE the ack and after the effect: reset in this window
        # re-acks instead of repeating the physical action.
        self._ledger = command_ledger.remember(self._ledger, ack)
        try:
            command_ledger.save(self._ledger, self._ledger_path)
        except Exception as exc:
            self._note_ledger_unsaved(exc)
        else:
            self._ledger_dirty = False
        # STEP 4'S RETURN VALUE IS NOW LOAD-BEARING, and only for the deferred
        # power actions (`sleep`, `set_networking` off). `queue_ack` answers the
        # DEPTH of the pending-ack FIFO including this one, which is the only
        # number that turns `PollLoop.acks_sent` into a proof that THIS ack
        # reached the server -- see `_note_power_ack`. Every other command
        # ignores it exactly as before.
        self._note_power_ack(self._backend.queue_ack(ack))
        self._emit("command_" + status, command=command.get("type"))

    def _note_ledger_unsaved(self, exc):
        """Count a lost durable ledger write and arm the persist-later retry.

        ONE DIAGNOSTIC PER BOOT, deliberately. A badge whose ``/state`` cannot be
        written fails every single command's write, and an event per failure would
        be a serial line per command for a fault the first line already described.
        `ledger_save_failures` in `snapshot()` carries the count.

        THE RUNG IS ARMED FROM THE CURRENT TICK, NOT FROM THE FRAME'S
        (corrected 2026-08-24). This ran from ``self._now`` -- the tick taken at
        the top of ``poll`` -- and a command callback runs inside
        ``backend.poll(now)``, which on a cold boot is the call that also paid the
        open. The 2026-08-24 device session measured the consequence: the frame
        carrying the command had spent 8,852 ms, so ``self._now + 5000`` was
        3.8 s in the PAST and the first rung fired on the NEXT FRAME -- the write
        landed 169 ms after the failure, where the ladder says ~5 s. Nothing was
        unsafe (four tries per boot, one chore per frame, one atomic swap each),
        but a ladder whose first rung is skippable is not the ladder the
        constants describe, and an operator timing the arm's "wait ~40 s" against
        a stopwatch reads a working badge as a broken one.

        The rungs themselves are UNCHANGED: 5, 10, 20 and 40 seconds, doubling
        from `LEDGER_PERSIST_BASE_MS`, bounded by `LEDGER_PERSIST_TRIES` per
        BOOT. Only the edge each one is measured from moved.
        """
        self._ledger_dirty = True
        self.ledger_save_failures += 1
        self.last_error = _error_text(exc)
        self._ledger_retry_at = _ticks_add(
            self._ticks_ms(),
            LEDGER_PERSIST_BASE_MS << min(self._ledger_retries,
                                          LEDGER_PERSIST_TRIES - 1))
        if not self._ledger_diagnosed:
            self._ledger_diagnosed = True
            self._emit("ledger_save_failed", error=self.last_error,
                       failures=self.ledger_save_failures)

    def _pump_ledger_persist(self, now):
        """Retry a lost durable ledger write from a chore-budgeted frame.

        Three bounds, and each one is the reason a naive retry would be worse
        than no retry at all:

        * **It never blocks command processing.** This runs from `poll`, after
          the transport step, and `_on_command` no longer waits on the
          filesystem at all.
        * **It never writes flash every frame.** One atomic swap costs the
          frame's whole chore budget, and the retry has its OWN backoff
          (LEDGER_PERSIST_BASE_MS, doubling) on top of that.
        * **It gives up quietly** after LEDGER_PERSIST_TRIES tries per boot. A
          volume that refused four times is full or read-only, not busy.
        """
        if not self._ledger_dirty:
            return None
        if self._ledger_retries >= LEDGER_PERSIST_TRIES:
            return None
        if self._ledger_retry_at is not None and _ticks_diff(
                now, self._ledger_retry_at) < 0:
            return None
        if not self._claim_chore():
            return None
        self._ledger_retries += 1
        try:
            command_ledger.save(self._ledger, self._ledger_path)
        except Exception as exc:
            self._note_ledger_unsaved(exc)
            return False
        self._ledger_dirty = False
        self._ledger_retry_at = None
        return True

    def _epoch(self):
        """The NTP-synced wall clock, or ``None`` when it is not trustworthy.

        `clock_boot`'s build-floor/ceiling gate is the same one the transport
        uses before opening a socket. Heartbeats, receipts and schedule-cache
        freshness must omit a time they cannot defend instead of stamping 2021.
        """
        reader = self._epoch_clock
        try:
            if reader is not None:
                candidate = int(reader())
            else:
                candidate = int(time.time())
        except Exception:
            return None
        try:
            import clock_boot

            if not clock_boot.evaluate_ntp(candidate)["accepted"]:
                return None
        except Exception:
            # No `clock_boot` on this /system/lib: the raw clock is all there is,
            # so keep the same value the TLS handshake already trusts.
            pass
        return candidate

    def _apply(self, command):
        """One broadcast -> one physical effect, or a raise the caller contains."""

        command_type = command.get("type")
        payload = command.get("payload")
        if command_type == "set_backlight":
            return self._apply_set_backlight(payload)
        if command_type == "report_state":
            return self._apply_report_state(payload)
        if command_type == "show_notice":
            return self._apply_show_notice(payload)
        if command_type == "play_effect":
            return self._apply_play_effect(payload)
        if command_type == "set_networking":
            return self._apply_set_networking(payload)
        if command_type == "sleep":
            return self._apply_sleep(payload)
        raise ValueError("unsupported command type: {}".format(command_type))

    # `set_name` AND `set_skin` WERE DELETED HERE ON 2026-08-29 (owner ruling).
    #
    # They were the two verbs that wrote the WEARER'S OWN CARD from the server,
    # and the ruling that removed them is one sentence: the badge owns its name,
    # nobody owns its skin. The direction is now the other way -- the badge
    # REPORTS `wearer_name` up on every heartbeat (`state_report`, sourced from
    # `scorebox.wearer_name`) instead of being told a `display_name` down.
    #
    # THEY WERE ALSO UNBROADCASTABLE IN PRINCIPLE, which is the structural half
    # of the same ruling and the reason they could not simply have been left
    # alone: a moment goes to EVERY connected badge, so a broadcast `set_name`
    # renames ~1,000 attendees at once. There is no targeting in the envelope and
    # deliberately so. `public.fleet_actions`' `kind` CHECK omits both.
    #
    # `_card_state()` went with them -- they were its only callers. `setup_state`
    # itself is untouched and still owns the wearer's own local edit path;
    # `self._card_state_path` survives because `_wearer_name` reads it.

    # -- open_app (Card FT-B item 1) ----------------------------------------
    #
    # THREE OUTCOMES, and which one you get depends on what the badge is doing,
    # not on the command:
    #
    #   at the LAUNCHER  -> INSTANT. The frame pump returns the app path as the
    #                       launcher's own update result, `run(...).result`
    #                       carries it and /system/main.py launches it. Same
    #                       boot, so a live socket survives into the app.
    #   in an APP        -> WAITS FOR THE LAUNCHER. One boot buys one menu visit
    #                       plus one app (docs/tufty-architecture.md), so there
    #                       is no launcher to return to in this boot. The note is
    #                       durable; the wearer's next HOME press resets the
    #                       badge and the note fires on the way through the menu.
    #   in an APP, force -> the same note, plus the badge LEAVES the app now: the
    #                       pump returns the target from the app's own update,
    #                       run exits, launch returns, main.py resets, and the
    #                       note fires at the next boot.
    #
    # THE ROSTER CHECK IS AT APPLY TIME AND AGAINST THE DEVICE, and an unknown
    # slug is a `failed` ack rather than a launch attempt. `launch()` is
    # os.chdir -> sys.path.insert -> __import__, and an exception inside it is a
    # firmware modal that RESETS the badge -- so a slug shape is a filter, never
    # a permission. The note's own delete-before-honour rule (openapp_note) is
    # what makes even a slug that passes both checks and then fails to import
    # cost one reset instead of a loop.

    def _open_app_note(self):
        """Imported lazily for the same reason as the state contract."""
        import openapp_note

        return openapp_note

    def _apply_open_app(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("open_app payload must be an object")
        keys = set(payload.keys())
        # `payload ? 'app' and payload - 'app' - 'force' = '{}'` in the CHECK:
        # `app` is required and `force` is the only other key allowed.
        if "app" not in keys or not keys <= set(("app", "force")):
            raise ValueError("open_app payload requires app and at most force")
        force = payload.get("force", False)
        if not isinstance(force, bool):
            raise ValueError("open_app force must be a boolean")
        note = self._open_app_note()
        slug = payload["app"]
        if not note.valid_slug(slug):
            raise ValueError("open_app slug is not in the payload class")
        if slug == note.MENU_SLUG:
            raise ValueError("open_app cannot target the launcher")
        installed = note.installed_apps(listdir=self._listdir)
        if slug not in installed:
            # NEVER a launch attempt. The ack names the slug so the console can
            # tell a typo from a badge that is missing the app.
            raise ValueError("open_app slug is not installed: {}".format(slug))
        # Written BEFORE the ack and before any frame acts on it, so a reset in
        # the window loses the ack (the server redelivers, the ledger re-acks)
        # and never the intent.
        note.write(slug, force, self._open_app_path)
        self._open_target = slug
        self._open_force = force
        if note.at_menu(self._getcwd):
            return {"effect": "open_app", "app": slug, "applies": "immediate"}
        if force:
            return {"effect": "open_app", "app": slug, "applies": "on_reset",
                    "force": True}
        return {"effect": "open_app", "app": slug, "applies": "next_launcher"}

    def _notice_note(self):
        """Lazy so an older /system/lib loses only the new verb, not boot."""

        import notice_note

        return notice_note

    def _apply_show_notice(self, payload):
        """Persist one notice, then force the fixed Nametag target."""

        notice = self._notice_note()
        # Validation happens before the temp write, and rename exposes only a
        # complete record.  This write precedes the forced reset so Nametag can
        # never launch from this action without the message it is meant to show.
        record = notice.write(payload, self._notice_path)
        try:
            opened = self._apply_open_app(
                {"app": NOTICE_APP_SLUG, "force": True})
        except Exception:
            # A notice without its force target would appear on some unrelated
            # later Nametag visit.  Roll it back best-effort and preserve the
            # original failure for the receipt.
            try:
                notice.discard(self._notice_path)
            except Exception:
                pass
            raise
        return {"effect": "show_notice", "app": NOTICE_APP_SLUG,
                "duration_s": record["duration_s"],
                "applies": opened["applies"]}

    def launch_result(self, bounded=False):
        """What the frame pump should return in place of ``None``.

        Called once per pumped frame from ``managed_run``'s wrapper, and it
        allocates nothing and touches no filesystem in the steady case: the
        target is an in-RAM slug and the common answer is the first ``if``.

        ``bounded`` is true inside ``run(update, duration=)`` -- a supervisor
        intro or any other time-boxed, non-interactive phase. A force-exit is
        refused there: that loop's caller is waiting for its own return value and
        handing it an app path would be answering a question nobody asked.
        """
        slug = self._open_target
        if slug is None:
            return None
        note = self._open_app_note_safe()
        if note is None:
            self._open_target = None
            return None
        if bounded:
            # A TIME-BOXED `run(update, duration=)` is waiting for its OWN return
            # value -- a supervisor intro, or any other bounded non-interactive
            # phase. Handing it an app path answers a question nobody asked, and
            # an earlier version of this guard only applied it to the FORCE path:
            # a launcher that runs an intro before its main loop would have had
            # its adopted note consumed and thrown away.
            return None
        at_menu = note.at_menu(self._getcwd)
        if not at_menu:
            if not self._open_force:
                return None
            # An arbitrary app owns this `run()` call and may discard its return
            # value (setup does). Preserve the one-shot note and RESET into
            # /system/main.py instead; the successor service consumes the note
            # before the launcher's first frame. Clear only the RAM intent first
            # so an injected reset that returns cannot make every frame reset.
            self._open_target = None
            self._open_force = False
            self._emit("open_app_force", app=slug)
            self._reset()
            return None
        # CONSUMED BEFORE THE LAUNCH, both here and at boot. The note has already
        # done its job for this boot; leaving it would open the app twice.
        self._open_target = None
        self._open_force = False
        try:
            note.consume(self._open_app_path)
        except Exception as exc:
            self.last_error = _error_text(exc)
        path = note.app_path(slug)
        self._emit("open_app_launch", app=slug)
        return path

    def _open_app_note_safe(self):
        try:
            return self._open_app_note()
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("open_app_unavailable", error=self.last_error)
            return None

    def adopt_open_note(self):
        """Consume a note left by an earlier boot.  Called once, from install().

        Boot-time consumption is what makes the note one-shot ACROSS a reset: the
        file is gone before the launcher's first frame, so a target that fails to
        import costs exactly one reset.
        """
        note = self._open_app_note_safe()
        if note is None:
            return None
        try:
            pending = note.consume(self._open_app_path)
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("open_app_unavailable", error=self.last_error)
            return None
        if pending is None:
            return None
        self._open_target = pending["app"]
        # The force already happened -- it is why this boot exists. What is left
        # is an ordinary launcher-return, so the flag is not carried forward.
        self._open_force = False
        self._emit("open_app_adopted", app=pending["app"])
        return pending["app"]

    # -- set_lights / set_backlight (Card FT-B item 1) ----------------------

    def _apply_set_lights(self, payload):
        import caselight_program

        program = caselight_program.program_for(payload)
        # A VALID newer one-channel intent retires a two-channel effect first.
        # `program_for` stays above this edge so malformed replacement input
        # cannot cancel the good effect already in the wearer's hands.
        self._preempt_effect()
        self._lights = program
        self._lights_started = self._now
        # ONE WRITE NOW, so an operator pressing the button sees the first frame
        # of the effect rather than waiting for the next network tick.
        level = program.step(0)
        if level is not None:
            self._caselights(level)
        if program.done:
            # `off` is one dark frame and nothing else, so it is finished before
            # the frame pump ever sees it. Leaving it parked would make the next
            # frame step a program that answers None forever -- harmless, and
            # still a reference the pump has to look at every frame.
            self._lights = None
        return {"effect": "caselights_program", "pattern": program.pattern,
                "period_ms": program.period_ms, "count": program.count,
                "duration_ms": program.total_ms}

    def _apply_play_effect(self, payload):
        """Play one non-empty array locally, in order, after one delivery.

        THE ARRAY IS THE RELIABILITY BOUNDARY. The whole show arrives in one
        broadcast and every cue is constructed before frame zero, so losing the
        socket later cannot strand half the sequence and a malformed later cue
        cannot start a partial one. There is deliberately no object shortcut:
        one cue is a one-element array and follows this exact path.

        ALL ITEM VALIDATION IS THE LIBRARY'S. Duplicating kind/id/duration rules
        here would let the badge and the database disagree at the worst seam.
        """

        # IMPORTED IN THE METHOD, exactly as `_apply_set_lights` imports
        # `caselight_program`: this module installs to `/system/lib` and runs from
        # `/system/main.py` before any app, and a module-scope import of a sibling
        # a half-refreshed lib might not carry would take the boot down.
        import effect_library

        if not isinstance(payload, list) or not payload:
            raise ValueError("play_effect payload must be a non-empty array")
        # BUILD THE WHOLE SEQUENCE BEFORE PREEMPTION. Each player is small and
        # the action row already has a bounded JSON payload; postponing builds
        # would let cue one play before cue two's invalid id was discovered.
        players = []
        total_ms = 0
        panel = False
        for item in payload:
            player = effect_library.player_for(
                item, panel_base=self._panel_base)
            players.append(player)
            total_ms += player.duration_ms
            if player.panel_active:
                panel = True
        # ONE SHOW AT A TIME, AND THE OLD ONE IS RETIRED PROPERLY. `interrupt`
        # restores both channels; dropping the reference would leave the panel and
        # the case lights wherever the previous effect's last frame put them.
        self._preempt_effect()
        self._lights = None
        self._effect_queue = players[1:] or None
        player = players[0]
        # THE FRAME TICK CAN BE 8,852 MS OLD by the time a command sink runs
        # inside a blocking open. Sample only at the install edge so a five-second
        # effect cannot be born already finished (2026-08-24 device evidence).
        self._start_effect_player(player, self._ticks_ms())
        return {"effect": "play_effect", "count": len(players),
                "duration_ms": total_ms, "panel": panel}

    def _start_effect_player(self, player, started):
        """Install one already-validated cue and write frame zero."""

        self._effect = player
        self._effect_started = started
        # Writing now avoids a one-frame dark gap both at broadcast arrival and
        # at cue boundaries; the previous cue's restore is overwritten only on
        # the channels this next cue owns.
        if player.step(0):
            self._write_effect_levels(player)

    def _preempt_effect(self):
        """Stop a running fleet effect and put both channels back. Total.

        Called from the frame pump's neighbours and from appliers, so it may not
        raise into Badgeware's frame path.
        """

        pending = self._effect_queue
        self._effect_queue = None
        player = self._effect
        if player is None:
            return bool(pending)
        self._effect = None
        try:
            if player.interrupt():
                self._write_effect_levels(player)
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("effect_contained", error=self.last_error)
        return True

    def _clear_remote_effects(self):
        """Drop not-yet-applied Live state and restore a running effect. Total.

        OFF, revocation and backend teardown are three spellings of the same
        authority loss. One helper keeps a future cue mailbox from being added to
        only two of them and leaving a stale cue able to apply after the third.
        """

        self._live_candidate = None
        self._live_pending = None
        return self._preempt_effect()

    def _write_effect_levels(self, player):
        """Push whichever of the two channels moved. Nothing else."""

        levels = player.case_levels
        if levels is not None:
            if self._caselights_variadic is False:
                self._caselights(max(levels))
            else:
                try:
                    self._caselights(*levels)
                    self._caselights_variadic = True
                except TypeError:
                    # Old one-argument test/dev shims must degrade visibly, not
                    # reset the managed frame pump. Production Badgeware takes
                    # four args; the latch avoids repeated exception allocation.
                    self._caselights_variadic = False
                    self._caselights(max(levels))
        elif player.case_level is not None:
            self._caselights(player.case_level)
        if player.panel_level is not None:
            setter = self._backlight
            if setter is not None:
                setter(player.panel_level)

    def note_panel_level(self, level):
        """The wearer just chose a panel level. Total; never raises into update().

        **THE HALF OF A CROSS-LANE SEAM THAT LIVES HERE**, specified verbatim in
        `docs/design/effect-library.md` §4 including this method's name. Settings
        writes `display.backlight(...)` directly and, without this, never tells
        `NetworkService` anything -- so `_panel_base` could only be moved by a
        FLEET `set_backlight`, and a running glyph effect would (a) overwrite the
        wearer's brightness presses up to ~24 times a second, making the row look
        broken, and (b) restore a STALE level when it finished. The contract
        harness measured exactly that: a restore to 0.5 against a live wearer
        level of 1.0.

        THE OTHER HALF IS THE APPS LANE'S and is not done: one guarded call
        (`getattr(_network, "note_panel_level", None)`) beside the existing
        `display.backlight(...)` in `settings/badge/settings/__init__.py`. Guarded
        because an older `/system/lib` has no such method and an AttributeError
        inside `update()` is a `machine.reset()` -- the same guard `push_control`
        already uses. Until that lands this method is correct and unreached, which
        is strictly better than the reverse.

        PREEMPTS THE SHOW, because §4's rule is that the newer intent wins: a
        wearer reaching for the brightness button is a person acting on the badge
        in their hand, and a fleet effect is decoration.
        """

        try:
            level = float(level)
        except Exception:
            # A level this method cannot make a float of is not a level. Refusing
            # silently is right: this is called from a draw path.
            return False
        self._preempt_effect()
        self._panel_base = level
        # THE EXPLICIT WRITE IS THE WHOLE FIX, AND THE DESIGN DOC'S SNIPPET IS
        # MISSING IT. §4 gives two lines -- record the base, then preempt -- and
        # neither of them puts the wearer's level on the panel. The running player
        # captured its own `panel_base` at `player_for` time, so `interrupt()`
        # restores THAT one; measured, a press of 0.4 during a show started at base
        # 1.0 leaves the panel at 1.0.
        #
        # AND THE ORDER OF THE TWO LINES ABOVE IS NOT WHAT SAVES IT. Recording
        # before preempting versus after produces the IDENTICAL write sequence
        # (`0.38125, 1.0` either way), because the level `interrupt()` writes comes
        # from the player and not from this object. Written this way round only
        # because it reads in causal order; the fix is the line below. Measured
        # both ways rather than assumed, after the first draft of this comment
        # claimed the ordering was the fix.
        #
        # IT ALSO MAKES THE CALL ORDER WITH SETTINGS IRRELEVANT. Settings writes
        # `display.backlight(...)` itself and the order against this call is not
        # guaranteed; if Settings wrote first, the preempt above just overwrote it.
        # Idempotent with that write, and skipped on a badge with no panel handle.
        setter = self._backlight
        if setter is not None:
            try:
                setter(level)
            except Exception:
                # A panel that refused is not a reason to raise into `update()`.
                pass
        return True

    def _apply_set_backlight(self, payload):
        level, persist = _backlight_intent(payload)
        setter = self._backlight
        if setter is None:
            # No panel handle (a host fixture, or a boot where `display` was not
            # injected): a failed ack, never a pretended one.
            raise ValueError("this badge exposes no backlight control")
        level = float(level)
        stored = None
        if persist:
            # THE FLASH WRITE PRECEDES EVERY VISIBLE EDGE. A corrupt/full state
            # partition is knowable here; moving the panel first would post a
            # failed receipt after showing a level that reset cannot retain.
            # setup_state mirrors Settings' one root key without importing an
            # app tree into this boot-path library.
            import setup_state

            # RP2350 IS SINGLE-PRECISION: ordinary exact-percent payloads land
            # just below their integer after scaling (`0.53 * 100` is about
            # 52.999996), so a naked truncation persists 52 while the console
            # sent 53. The epsilon is one order above that measured float error
            # and five orders below a percent; genuine sub-percent values still
            # truncate (`0.205` remains 20), which is the shared-store rule.
            percent = int(level * 100 + 0.00001)
            result = setup_state.set_brightness(
                percent, path=self._card_state_path)
            stored = result["stored"]
            # Settings stores integer percent. Apply that canonical value now,
            # so 0.205 cannot become 0.20 only after the next reset.
            level = stored / 100.0
        # HANDLE AND VALUE VALIDATION BOTH PRECEDE THIS EDGE. A malformed or
        # unavailable newer control must not cancel a valid two-channel show;
        # once valid, the explicit panel intent wins and the player restores
        # before that newer level is written.
        self._preempt_effect()
        setter(level)
        # REMEMBERED AS THE PANEL BASE, so a glyph effect hands the backlight back
        # where it was rather than to a constant. A show that ended by setting
        # every badge in the room to full brightness would be worse than one that
        # never played.
        self._panel_base = level
        return {"effect": "backlight", "level": level, "persist": persist,
                "stored": stored}

    # -- report_state (Card FT-B item 1) ------------------------------------
    #
    # THE REPLY IS A `badge_state` WRITE, NOT THE ACK ROW. The constraint's own
    # comment says so ("anything in this object would be a field nobody reads"),
    # and there was no device-side badge_state writer at all before this card:
    # `data_api.heartbeat` is the host lane and is not in the /system/lib
    # manifest. So this applier BUILDS a snapshot and queues it as an errand on
    # the already-open socket.
    #
    # `applied` MEANS "BUILT AND QUEUED", not "landed". `_on_command` is
    # synchronous and the errand needs an exchange or two, so waiting would leave
    # the command un-acked across a poll. A queue that refused (four errands
    # already waiting) is a FAILED ack, because then nothing was queued at all.
    #
    # `last_seen_at` IS IN THE CLIENT GRANT AND IS DELIBERATELY NOT SENT. The
    # column defaults to `statement_timestamp()`, and the same argument Card FT-S
    # used to take the `scores` insert-time column out of its grant applies to any
    # clock a badge could get wrong: the server's is the only one worth trusting.
    # (Naming that column here would trip FT-S's own guard, which searches this
    # tree for the literal string -- a deliberately prose-sensitive check.)

    def _boot_session(self):
        """A per-boot id matching ``^[0-9a-f]{32}$``.  Generated once, never stored.

        Per BOOT rather than per session, because that is what it is for: two
        rows with the same boot_session came from one uninterrupted run, and a
        HOME press must produce a different one.
        """
        if self._boot_session_id is not None:
            return self._boot_session_id
        try:
            import os

            raw = os.urandom(16)
        except Exception:
            return None
        digits = "0123456789abcdef"
        out = []
        for index in range(16):
            byte = raw[index]
            out.append(digits[(byte >> 4) & 0x0F])
            out.append(digits[byte & 0x0F])
        self._boot_session_id = "".join(out)
        return self._boot_session_id

    def _battery_fields(self, record):
        """Battery percent and charge state, each independently optional.

        THE READING IS NOISY BY CONSTRUCTION and this does not smooth it. The
        firmware derives the percentage through
        ``123 - 123 / (1 + (v/3.2) ** 80) ** 0.165`` -- an exponent of 80 is a
        very steep sigmoid, so a millivolt of ADC noise near the knee moves the
        answer by several points, and ``battery_voltage()`` averages only ten
        samples. The launcher smooths it for DISPLAY (a minimum interval plus a
        hysteresis margin, `launcher/menu/ui.py`) because a flickering bar is a
        defect. A telemetry sample is a sample: smoothing it here would hide a
        real drop, so the noise is recorded rather than filtered.
        """
        badge_api = self._badge_api
        reader = getattr(badge_api, "battery_level", None)
        if callable(reader):
            try:
                level = int(reader())
            except Exception:
                level = None
            if level is not None:
                if level < 0:
                    level = 0
                elif level > 100:
                    level = 100
                record["battery_percent"] = level
        usb = getattr(badge_api, "usb_connected", None)
        charging = getattr(badge_api, "is_charging", None)
        if callable(usb):
            try:
                plugged = bool(usb())
                # `is_charging` already returns False when VBUS is absent, so
                # "plugged and not charging" is the honest reading of CHARGE_STAT
                # going high: the pack is full.
                if not plugged:
                    record["battery_state"] = "discharging"
                elif callable(charging) and bool(charging()):
                    record["battery_state"] = "charging"
                else:
                    record["battery_state"] = "charged"
            except Exception:
                record["battery_state"] = "unknown"
        return record

    def _firmware_version(self):
        try:
            import os

            uname = getattr(os, "uname", None)
            if not callable(uname):
                return None
            info = uname()
            text = getattr(info, "version", None)
            if not isinstance(text, str) or not text:
                return None
            # `firmware_version text check (char_length(...) <= 64)`.
            return text[:64]
        except Exception:
            return None

    def state_report(self, chore_held=False):
        """The ``badges`` row this badge would post right now.

        Public because a device session needs to be able to print it without
        queueing anything. Every field except ``id`` is optional and an unreadable
        one is OMITTED rather than guessed: a null column reads as "not reported",
        and a fabricated one reads as a measurement.

        ``chore_held`` is passed through to `_wearer_name` and means "the caller
        already took this frame's chore for this work". It defaults False so the
        on-demand callers (a device session, the `report_state` verb) are
        unchanged; only `_pump_heartbeat` passes True.

        ⚠ ``id`` IS ``hardware_uid()`` AND NOT THE CREDENTIAL'S SUBJECT, AND THAT
        ONE LINE IS THE WHOLE REASON THIS METHOD CHANGED (rebuild, 2026-08-29).
        It read `DeviceBackend.badge_id()` -- the JWT `sub` -- until today, which
        was correct while `badge_state`'s RLS was `badge_id = grants.whoami()` and
        catastrophic the moment provisioning went gang-clone: all ~1,000 badges ship
        a byte-identical `/secrets.py`, so every one of them reported the SAME id
        and the table holds ONE row for the entire fleet. The new `badges` table
        keys on the physical id and RLS keys on the `x-badge-id` header
        (`rpc_contract.rpc_headers`), which carries that same value, so the two
        accessors that deliberately DISAGREED now deliberately AGREE. Nothing on
        this path may key on the sub again.
        `_pump_scores` already read the uid for exactly this reason; the two are
        now the same choice made twice rather than a split.

        RAISING WHEN THERE IS NO UID IS THE HONEST ANSWER and the caller has to
        expect it. `hardware_uid()` returns None off-device and on a board whose
        `machine.unique_id()` does not answer sixteen hex characters, and a
        heartbeat with no id is not a degraded heartbeat -- it is a row that would
        either be refused by the CHECK or, worse, land unattributed. The pump
        swallows it; the `link_unaddressed` event emitted once per link build is
        the symptom to look for, and it is now far more serious than the one line
        per boot it was priced as -- with `x-badge-id` as the RLS identity, a badge
        with no uid does not merely miss commands, it cannot WRITE.
        """
        badge_id = hardware_uid()
        if not isinstance(badge_id, str) or not badge_id:
            raise ValueError("this badge cannot prove its physical identity")
        record = {"id": badge_id}
        # THE BADGE REPORTS ITS NAME **UP** (owner ruling, 2026-08-28). It used to
        # be told a `display_name` DOWN, which meant the console was authoritative
        # about a string the wearer typed into their own badge. `scorebox`'s reader
        # is the source because it is the same one that attributes a SCORE, so a
        # leaderboard row and a heartbeat can never disagree about who this is.
        #
        # `None` MEANS "NOT READ YET", NOT "NO NAME": the read is a `/state` open
        # and it claims the frame's chore, so a frame that spent its budget
        # elsewhere simply omits the key and the next heartbeat carries it. `""`
        # (read, and there is none) is omitted too -- the column is nullable and an
        # empty string would be a name nobody typed.
        name = self._wearer_name(chore_held=chore_held)
        if isinstance(name, str) and name:
            record["wearer_name"] = name
        session = self._boot_session()
        if session is not None:
            record["boot_session"] = session
        self._battery_fields(record)
        firmware = self._firmware_version()
        if firmware is not None:
            record["firmware_version"] = firmware
        try:
            note = self._open_app_note()
            active = note.current_app(self._getcwd)
        except Exception:
            active = None
        if active is not None:
            record["active_app"] = active
        # CREDENTIAL-FREE AND ENDPOINT-FREE, like every other event this module
        # emits. A host, a token or an apikey in here would be a secret in a
        # table the whole event's admin can read.
        record["network_state"] = {
            "transport": self.state,
            "push": self.push_mode(),
            "push_enabled": self._push_enabled,
        }
        return record

    def _apply_report_state(self, payload):
        # `report_state` carries no arguments: `payload = '{}'::jsonb`.
        if not isinstance(payload, dict) or payload:
            raise ValueError("report_state takes no arguments")
        return self.post_state_report(reason="command")

    def post_state_report(self, reason="command", chore_held=False):
        """Build a snapshot and queue it. Raises when it could not be queued.

        ONE REQUEST IS BOTH THE HEARTBEAT AND THE REGISTRATION, and the `Prefer`
        header is the whole of that. `resolution=merge-duplicates` makes a POST of
        a row that already exists an UPDATE, so a badge the server has never seen
        CREATES its own row on first contact and every later beat refreshes it.

        ⚠ IT WAS A `PATCH ?badge_id=eq.<id>` UNTIL 2026-08-29 AND THAT SHAPE
        COULD NOT SELF-REGISTER. PATCH against a row that does not exist is a 204
        affecting zero rows, which `postgrest.parse_response` correctly reads as
        SUCCESS -- so an unregistered badge heartbeats into nothing, forever,
        while every event it emits says the post landed. There is no symptom to
        find, which is why the method is a POST now and why the filter is gone:
        the id is a COLUMN in the body rather than a query on the URL.

        RAISES rather than returning False, because both callers want that: the
        `report_state` verb turns it into a failed ack (claiming `applied` for a
        row that was never queued would be a lie), and the periodic pump treats it
        as "try again on the next frame".
        """
        import rpc_contract

        record = self.state_report(chore_held=chore_held)
        queued = self._queue_errand(
            "table",
            {"table": rpc_contract.TABLE_BADGES, "method": "POST",
             "row": record, "prefer": rpc_contract.PREFER_MERGE_MINIMAL},
            self._on_state_posted,
            # COALESCED, AND IT MATTERS MORE NOW THAN IT DID. Two reports in one
            # exchange window would post a stale snapshot and then a fresh one;
            # only the fresh one is worth sending. With a ~60 s beat AND an
            # on-demand path sharing this key, the coalesce is what stops an
            # operator hammering `report_state` from filling the errand queue and
            # starving the score drain.
            key="badge_state",
        )
        if not queued:
            raise ValueError("the badge could not queue a state report")
        self._emit("state_report_queued", reason=reason)
        return {"effect": "state_report", "queued": True,
                "fields": len(record), "reason": reason}

    def _on_state_posted(self, ok, _data):
        self._emit("state_report_posted" if ok else "state_report_failed")

    def _pump_heartbeat(self, now):
        """Post this badge's liveness row about once a minute.  Never raises.

        THE CADENCE IS ADVANCED ON THE ISSUE, NOT ON THE ANSWER, which is CX-8's
        rule and the reason this pump owns one due time and nothing else does. A
        beat that fails is a beat skipped, never a beat retried immediately: the
        errand's own failure path already tells the operator, and a badge whose
        socket is unhappy is exactly the badge that must not add requests to it.
        The one exception is a REFUSAL -- a full errand queue means the request was
        never made at all, so that re-arms at `ERRAND_RETRY_MS` instead.

        *** THIS PUMP CLAIMS THE FRAME'S CHORE, AND THE COMMENT THAT SAID IT DID
        NOT WAS WRONG ABOUT ITS OWN MOST EXPENSIVE FIELD. *** It read: "the only
        expensive thing on the path is the wearer-name read ... everything else
        in the snapshot is a RAM read or a cwd parse the frame already performs".
        `state_report` calls `_battery_fields`, which calls
        `badge_api.battery_level()`, which the firmware derives from
        `battery_voltage()` -- an ADC read that averages ten samples, as
        `_battery_fields`' own docstring says two screens down. It also calls
        `os.uname()` via `_firmware_version`. Neither is a RAM read.

        The cost is small and bounded (once per ~60 s), so this was never a
        freeze; it is corrected because in this repo the comment IS the register,
        and a comment that tells the next reader a chore-free heartbeat is free
        is exactly how the eleventh field gets added to `state_report` on a false
        premise. CX-10's budget exists to make a frame's worst case predictable,
        and a frame that does a gauge read plus a `_pump_scores` drain plus a
        schedule sync is not predictable just because each piece is small.

        THE BEAT IS THE RIGHT THING TO DEFER when the chore is already spent: it
        has ~60 s of slack, which is more than any other claimant on this ladder,
        so losing the race costs one frame and never a beat.
        """
        backend = self._backend
        if backend is None or getattr(backend, "state", None) != CONNECTED:
            # NO SOCKET, AND THE DUE TIME IS LEFT EXACTLY WHERE IT WAS. Clearing
            # it here would re-phase on every reconnect, which is CX-8's original
            # defect wearing the other hat: an AP that blips more often than the
            # phase is long would mean a badge that never beats at all. A badge
            # that spent ten minutes offline comes back ONE beat overdue, not ten,
            # because the advance below is absolute rather than cumulative.
            return None
        if self._heartbeat_due is None:
            # FIRST BEAT OF THIS SESSION, PHASED. See `HEARTBEAT_FIRST_MIN_MS`:
            # prompt enough that a provisioning run sees the badge appear, spread
            # enough that ~1,000 badges booting into one room do not register in the
            # same second.
            self._heartbeat_due = _ticks_add(
                now, self._jittered_delay_ms(HEARTBEAT_FIRST_MIN_MS,
                                             HEARTBEAT_MS))
            return None
        if _ticks_diff(now, self._heartbeat_due) < 0:
            return None
        if not self._claim_chore():
            # THE DUE TIME IS NOT MOVED. This frame was spent on something else;
            # the beat is still owed and the next frame offers it again. Re-arming
            # here would let a busy stretch silently postpone registration.
            return None
        try:
            self.post_state_report(reason="heartbeat", chore_held=True)
        except Exception as exc:
            # A snapshot this badge cannot build (no `hardware_uid`) or an errand
            # channel that refused it. Both are "ask again", and neither may take
            # down a poll cycle -- the wearer is holding a badge, not a server.
            self.last_error = _error_text(exc)
            self._heartbeat_due = _ticks_add(now, ERRAND_RETRY_MS)
            return False
        self._heartbeat_due = _ticks_add(now, HEARTBEAT_MS)
        return True

    # -- the score drain (Card FT-B item 3) ---------------------------------
    #
    # THE GAME NEVER WAITS AND NEVER KNOWS. A game calls
    # `scorebox.record(game, score, duration_ms)` and returns to its own frame
    # loop; this is the half that notices a socket exists and posts one row.
    #
    # ONE IN FLIGHT, ROUND-ROBIN OVER THE GAMES, and the per-frame question is an
    # integer compare: `scorebox.scan_complete()`/`cached_pending()` read the
    # slot count out of the module both sides share, so a spool that is empty
    # costs nothing at all. Filling it the FIRST time is the cold load, and it is
    # now ONE bounded open and ONE decode of a document holding at most one slot
    # per game (`scorebox.take_slot`, CX-10).
    #
    # NOTHING IS EVER DISCARDED (owner ruling, 2026-08-29; ADR-007). `MAX_ATTEMPTS`
    # -- three refusals and the wearer's score was DELETED -- is gone, and with it
    # every path in this file that dropped a score on failure. It existed because
    # the spool was a FIFO whose head could block every later score; there is no
    # head any more, so a permanently refused snake slot delays snake and nothing
    # else, and the other four drain past it on the very next frame. The guarantee
    # a counter used to buy by throwing a score away is now free, and structural.
    #
    # EXACTLY ONE THING EMPTIES A SLOT FROM OUTSIDE: `scorebox.retire`, after a
    # response said the row landed -- and only if the slot has not been superseded
    # in the meantime. See `_retire_score` for why that return value is checked.

    def _score_box(self):
        if self._scorebox is False:
            return None
        if self._scorebox is None:
            try:
                import scorebox

                self._scorebox = scorebox
            except Exception as exc:
                self._scorebox = False
                self.last_error = _error_text(exc)
                self._emit("scorebox_unavailable", error=self.last_error)
                return None
        return self._scorebox

    def exchanges(self):
        """How many transport requests have finished, or 0.  Duck-typed.

        The other half of the frame-gate discriminator: `chores` counts what this
        module's own Python made a frame expensive for, and this counts what the
        socket did in it. A backend that predates the accessor answers 0, so a
        probe reads a number rather than handling an absence.
        """
        reader = getattr(self._backend, "exchanges", None)
        if not callable(reader):
            return 0
        try:
            return int(reader())
        except Exception:
            return 0

    # -- the fleet settings read (rebuild, 2026-08-29) ----------------------
    #
    # STATES ARE POLLED. This is the other half of "MOMENTS are broadcast": the
    # doorbell carries a thing that HAPPENS and this carries what IS. A badge that
    # missed a ring -- asleep, off, out of range, or one of the 595 in 598 the
    # exact-key filter silently dropped before the server was fixed -- learns the
    # current state here and nowhere else, which is why the payload may only ever
    # carry values that are safe to re-apply. See `_apply_settings`.
    #
    # IT REPLACES `RPC_TRANSPORT_POLICY` AND ITS WHOLE CADENCE APPARATUS. The
    # steering read used to be a `polltransport` request KIND with a due time the
    # loop owned and a phase this object owned -- two objects, one cadence, which
    # is the CX-8 defect and then the CX-8 correction. It is an ordinary errand
    # now: one due time, in this object, advanced where the request is issued.
    #
    # THE PHASE IS STILL CX-8'S AND THE ARGUMENT IS UNCHANGED. The interval was
    # never the problem; the FIRST fire was, because every app exit on this
    # platform is a `machine.reset()` and a wearer switching apps pays it over and
    # over. A floor plus a jitter is deterministic where a pure jitter is not: a
    # jitter alone still leaves one badge in a hundred inside the boot burst, and
    # one in a hundred is eight badges in a hall of 800 still doing the wrong
    # thing.

    def _pump_fleet_settings(self, now):
        """Re-read the fleet's settings on a slow cadence.  Never raises.

        ADVANCED ON THE ISSUE, exactly like the heartbeat and for CX-8's reason: a
        read that FAILS must not leave the due time in the past, or a badge whose
        socket is unhappy re-issues on every tick that has nothing better to do.
        One skipped cycle is five minutes of a lever being stale; a re-issue storm
        is the herd.

        FAIL-OPEN SURVIVES THE MOVE, and it is the whole reason this may be
        skipped safely: a settings read that never happens is a `_apply_settings`
        that is never called, and every consumer -- `pushlink.PushPolicy` most of
        all -- leaves the badge on its own default when it has heard nothing. A
        kill switch that fails CLOSED makes the switch itself load-bearing.
        """
        backend = self._backend
        if backend is None or getattr(backend, "state", None) != CONNECTED:
            # LEFT WHERE IT WAS, for the reason `_pump_heartbeat` spells out: the
            # phase is drawn ONCE, by whoever owns it, and a reconnect may not
            # re-draw it. It is also why a badge that comes back after an outage
            # reads the settings promptly -- which is the catch-up this read is
            # for, and exactly one request rather than one per missed interval.
            return None
        if self._settings_due is None:
            delay = self._jittered_delay_ms(SETTINGS_FIRST_MIN_MS,
                                            SETTINGS_REFRESH_MS)
            self._settings_due = _ticks_add(now, delay)
            self._emit("settings_phased", due_ms=delay)
            return None
        if _ticks_diff(now, self._settings_due) < 0:
            return None
        import rpc_contract

        queued = self._queue_errand(
            "table",
            {"table": rpc_contract.TABLE_FLEET_SETTINGS, "method": "GET",
             "query": rpc_contract.FLEET_SETTINGS_QUERY},
            self._on_fleet_settings,
            # COALESCED for the same reason the heartbeat is: two settings reads
            # in one window would answer the same question twice, and the second
            # answer is the only one that matters.
            key="fleet_settings",
        )
        if not queued:
            self._settings_due = _ticks_add(now, ERRAND_RETRY_MS)
            return False
        self._settings_due = _ticks_add(now, SETTINGS_REFRESH_MS)
        return True

    def _on_fleet_settings(self, ok, data):
        """Decode one settings response and apply it.  Never raises.

        THE PARSE IS `postgrest.parse_policy_row` AND IT NEEDED NO NEW SHAPE: it
        already unwrapped a one-element LIST (the RPC returned `returns table`,
        this returns `?limit=1`), and it already drops every field it cannot read
        confidently. What it gained is three more keys, which is additive.
        """
        self._response_continuation = True
        if not ok:
            self._emit("settings_failed")
            return None
        try:
            import postgrest

            fields = postgrest.parse_policy_row(data)
        except Exception as exc:
            # A body that is not the shape this badge understands. Dropped whole
            # rather than half-applied: `parse_policy_row` fails open field by
            # field, and anything that gets past it is a malformed RESPONSE.
            self.last_error = _error_text(exc)
            self._emit("settings_contained", error=self.last_error)
            return None
        return self._apply_settings(fields)

    def _apply_settings(self, fields):
        """Apply the fleet's current state.  IDEMPOTENT.  Never raises.

        W8 KEEPS ROUTINE BUSINESS STEERING HERE: push, score draining and the
        suggested cadence. Physical acts are broadcasts instead. A table read
        repeats about 96 times over an eight-hour day; re-reading radio, panel or
        sleep state would overrule a wearer or repeat an act they already undid.

        AN ABSENT FIELD IS NOT A FALSE ONE. `parse_policy_row` drops what it
        cannot read, so a truncated body arrives here as an empty dict and every
        lever keeps the value it had. That is the same fail-open direction
        `PushPolicy.set_remote` argues for at length. Unknown future business
        fields are inert until this firmware learns an applier for them.
        """
        if not isinstance(fields, dict):
            return None
        applied = []
        # PUSH FIRST, because it is the only lever with a consumer that wants the
        # WHOLE steering dict rather than one value, and because it is the one
        # that was already wired: `_on_policy` holds the policy even when no push
        # object exists yet and forwards it when one appears.
        if "push_enabled" in fields:
            self._settings_lever("push_enabled", self._apply_settings_push,
                                 fields, applied)
        # THE CADENCE IS THE LOOP'S, NOT THIS OBJECT'S, so it is handed down
        # rather than held here -- the one piece of steering that still lives in
        # `polltransport`, where the exchange it paces is decided. Clamped there,
        # into the band the transport is willing to run at, so nothing the server
        # can send makes a badge ask faster than its own floor. NOT edge-guarded:
        # the setter is a plain assignment on the loop and a loop REBUILD is what
        # would otherwise silently drop the operator's value.
        cadence = fields.get("next_cadence_ms")
        if ("next_cadence_ms" in fields
                and (cadence is None
                     or (isinstance(cadence, int)
                         and not isinstance(cadence, bool)))):
            if self._set_suggested_cadence(cadence):
                applied.append("next_cadence_ms")
        # RECORDING IS NEVER GATED. This edge changes only whether the durable
        # score spool drains, so the operator can delay but not lose a round.
        if self._settings_edge("scores_enabled", fields):
            self._settings_lever("scores_enabled", self._apply_settings_scores,
                                 fields["scores_enabled"], applied)
        # Legacy wifi/backlight/sleep keys are deliberately unclaimed. W5-W7
        # deliver those once through `_pump_broadcast_actions`; restoring one
        # here would turn a moment back into repeated physical state.
        self._emit("settings_applied", applied=len(applied))
        return applied

    def _settings_lever(self, name, applier, value, applied):
        """Pull one lever, alone.  Never raises.

        ONE CONTAINMENT PER LEVER, NOT ONE FOR THE SET, and the difference is the
        whole reason this helper exists rather than a single `try` around the
        ladder: current push/scores appliers are total, but a future retained
        business control may validate or call a fallible seam. Its failure must
        not stop an independent score or delivery policy below it from applying.

        ⚠ CONTAINED AT ALL. This runs inside `backend.poll`, which runs inside a
        rendered frame under `launch()`, where an unhandled exception reaches
        `fatal_error` and resets the badge. A malformed lever is a thing to
        ignore; it may never be the reason a wearer's badge reboots.

        A LEVER THAT RAISED IS STILL RECORDED AS APPLIED by `_settings_edge`,
        deliberately: the value did not change, so re-trying it every five minutes
        for the rest of the event would be ~96 identical failures per badge.
        """
        try:
            result = applier(value)
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("settings_lever_failed", lever=name,
                       error=self.last_error)
            return False
        if result is False:
            # A retained control may have nothing to change. That is neither a
            # failure nor an application, so it stays out of the applied count.
            return False
        applied.append(name)
        return True

    def _settings_edge(self, key, fields):
        """Whether ``key`` carries a value this badge has not acted on yet.

        THE ABSENT CASE IS NOT AN EDGE and the unchanged case is not either. The
        remembered value is written HERE rather than in each applier so that no
        applier can forget to -- a lever that acts without recording is a lever
        that acts on every read for the rest of the event.
        """
        if key not in fields:
            return False
        value = fields[key]
        if key in self._settings_applied and self._settings_applied[key] == value:
            return False
        self._settings_applied[key] = value
        return True

    def _set_suggested_cadence(self, cadence):
        """Hand the loop the server's suggested exchange cadence.  Duck-typed."""
        setter = getattr(self._backend, "set_suggested_cadence", None)
        if not callable(setter):
            return False
        try:
            setter(cadence)
        except Exception as exc:
            self.last_error = _error_text(exc)
            return False
        return True

    def _apply_settings_push(self, fields):
        """The doorbell's kill switch, handed to the consumer that owns it.

        NOT EDGE-GUARDED, AND THAT IS THE ONE EXCEPTION TO THE RULE ABOVE.
        `_on_policy` is an assignment plus a forward into `PushPolicy.set_remote`,
        which sets a flag; re-applying the same value cannot flicker anything, and
        the doorbell is REBUILT on every reconnect, so an edge guard would mean a
        badge that reconnected after the last settings read spent up to five
        minutes with the operator's kill switch un-applied.
        """
        self._on_policy(fields)
        return True

    def _apply_settings_scores(self, enabled):
        """The fleet leaderboard lever.  ``False`` stops the DRAIN and nothing else.

        ⚠ **RECORDING IS NEVER GATED, AND THAT ASYMMETRY IS THE WHOLE DESIGN.**
        `scorebox.record` does not read this flag and must not learn to: a wearer
        whose round vanished because an operator flipped a switch has lost
        something the badge cannot get back, while a wearer whose round is merely
        UPLOADED LATE has lost nothing at all. The spool is durable on flash and
        survives the `machine.reset()` that every app exit is, so switching the
        lever back on drains the backlog with no further help.

        ⚠⚠ **AND THIS IS NOT MERELY POLITE -- WITHOUT IT THE LEVER DESTROYS
        SCORES.** `badgelink.gate_scores()` is a BEFORE INSERT trigger that
        returns NULL when the lever is off, so the row is discarded and
        PostgREST still answers 201. The badge reads that as success,
        `_retire_score` deletes the entry from the spool, and it is gone for good.
        The server chose the silent discard on purpose -- a 403 used to burn
        `scorebox.MAX_ATTEMPTS` and delete the spool too. ⚠ THAT SECOND HALF IS
        NOW HISTORY AND THE FIRST IS NOT: a refusal costs a slot nothing since
        2026-08-29, but a SILENT SUCCESS is still indistinguishable from a real
        one and still retires the slot. The only way the lever is safe is for the
        badge not to post at all, which is this.

        ⚠ **THE RESIDUAL WINDOW IS REAL AND IS NOT CLOSED HERE.** The badge
        learns the lever off the ~5 minute `fleet_settings` read
        (`SETTINGS_REFRESH_MS`), so scores posted between the operator's flip and
        this badge's next read still meet the trigger and are still destroyed.
        Shortening the cadence is the herd cost that interval exists to price;
        the real fix is a server that says "dropped" distinguishably, and that is
        a schema change rather than a firmware one.

        ⚠ **AND IT IS NOT A PRIVACY CONTROL.** Rows already delivered are the
        backend's; this stops future sends and claims nothing else, exactly as
        `_apply_wipe_scores` states for the wipe. If the operator's intent is
        "these scores must not exist", the leaderboard's own cutoff is the tool.

        BOTH DIRECTIONS ARE A REAL APPLICATION. There is no wearer-side switch
        for score draining, so the fleet's value is the only opinion there is.

        NO EVENT OF ITS OWN, deliberately. `_settings_lever` counts it into
        `settings_applied`, and the line an operator actually needs is the
        CONSEQUENCE -- `score_stalled reason=fleet_disabled`, which the drain
        emits on its own next frame and which is on the printer's whitelist. A
        second line here would say the same thing one frame earlier in a field
        (`enabled=`) that `_PRINTED_FIELDS` does not carry.
        """
        self._scores_enabled = bool(enabled)
        return True

    # `_apply_settings_sleep` WAS DELETED HERE ON 2026-08-29 (owner ruling), and
    # this stub of a comment is the record so nobody writes it back.
    #
    # It was the fleet's indefinite-sleep lever: `fleet_settings.sleep_mode`
    # true -> arm an indefinite `sleep` power action. Its own docstring argued
    # that re-sleeping on every read was "the lever working, not a loop ... it is
    # awake for at least a minute every cycle". THE OWNER READ THAT AS THE BUG.
    # Verbatim: *"I don't think that should be a setting in the Fleet settings...
    # If I just wanted to set them all to sleep right now... I'll just send a
    # broadcast message to send them all to sleep once."* A wearer pressing a
    # button to reclaim their own badge, and getting a minute, is not a lever
    # working.
    #
    # WHAT REPLACED IT IS THE `sleep` BROADCAST, `_apply_sleep`, which fires ONCE
    # and holds nothing. The two are not a pair and there is no third state: a
    # badge that was disconnected at fan-out simply stays awake, accepted in the
    # same ruling (*"I'm not worried if they're not connected"*).
    #
    # `fleet_sleep_armed` WENT WITH IT and is not emitted by anything now. The
    # broadcast lane's line is `action_applied verb=sleep`, followed by
    # `sleeping seconds=...` from `_sleep_now`.

    def _jittered_delay_ms(self, floor_ms, interval_ms):
        """A per-badge delay in ``[floor_ms, interval_ms)``.

        The floor is what makes the fix DETERMINISTIC rather than probabilistic: a
        pure jitter over a 5-minute interval still leaves one badge in a hundred
        firing inside the boot burst, and one badge in a hundred is a hall of 800
        with eight of them still doing the wrong thing.
        """
        span = interval_ms - floor_ms
        if span <= 0:
            return floor_ms
        try:
            fraction = float(self._rand01())
        except Exception:
            fraction = 0.5
        if not 0.0 <= fraction < 1.0:
            fraction = 0.5
        return floor_ms + int(fraction * span)

    def _badge_stagger_ms(self, span_ms):
        """A stable slot inside ``span_ms`` for THIS badge, from its own id.

        Deterministic on purpose, and the reason is the correlated reset: 800
        badges rebooting together re-roll a random jitter into a fresh clump every
        time, while a hash of the badge id reproduces the same even spread. Falls
        back to the random draw when there is no id to hash -- a fixture, or a
        backend that has not loaded its credential yet.

        **THE DERIVATION IS SHA-256, AND SWITCHING TO IT IS THE WHOLE FIX.** This
        was a 16-bit poly-31 hash over the id's characters until 2026-08-23, which
        spreads arbitrary strings perfectly well and spreads THESE ids hardly at
        all. A badge id is ``machine.unique_id().hex()`` -- sixteen hex digits
        (`credentials.py`: ``sub=<16-hex badge id>``) -- and a batch of boards
        bought together carries flash unique ids from one production run, so a
        real fleet's ids are CONSECUTIVE. Poly-31 is linear in every character,
        so a consecutive run only ever moves its low-order terms: 800 sequential
        UIDs landed in a **3.3 s window with 321 requests in the busiest second**
        (288 anchored at zero) against the 13.3/s this stagger exists to produce.
        Both numbers are measured in
        `badgelink/tests/test_cx8_boot_cadence.py::FleetSpreadTests`, which keeps
        the old derivation as its ORACLE so a character-linear hash cannot come
        back quietly.

        TWO DIGEST BYTES, and the arithmetic below is untouched: 65,536 slots
        against 800 badges is ~5 expected collisions, and a collision costs two
        badges the same millisecond slot, which is nothing. ``digest()`` and never
        ``hexdigest()`` -- THIS FIRMWARE HAS NO ``hexdigest``. `hashlib.sha256` on
        ``bw-1.28.0-3`` exposes ``digest()`` only
        (`docs/engineering-findings.md`), and a device preflight that assumed
        otherwise printed ``AttributeError`` while `mpremote` still returned 0.
        Imported lazily like every other import in this module, and reached once
        per BOOT rather than per frame.

        CONTAINED, into the fallback that already existed. A build with no usable
        ``hashlib`` must not leave `_pump_schedule_sync` unable to arm a due time
        -- that is a badge whose schedule never refreshes at all -- so it degrades
        to the random draw, which is exactly what a badge with no id gets.

        ⚠ **AND IT HASHES THE HARDWARE UID, NOT `backend.badge_id()`, SINCE
        2026-08-26 -- THE SHARED-TOKEN FIX, AND IT IS THE WORST CASE OF THE WHOLE
        LINCHPIN CLASS.** This method read the credential's `badge_id` (the JWT
        `sub`), which was this badge's own UID only because provisioning minted
        it that way. Under the byte-identical `secrets.py` all 800 badges hash the
        SAME string, get the SAME two digest bytes and land in the SAME
        millisecond slot -- so the mechanism whose entire purpose is a
        DETERMINISTIC even spread silently becomes perfect synchronisation, and
        it fails in the direction that hides: the code runs, the arithmetic is
        right, the comment above still reads true, and nothing is wrong until 800
        badges are in a room. The cold branch is also the one that fires on the
        San Francisco event morning, because a gang-cloned badge has no
        `/state/schedule.json` at all, so the mass cold boot would put 800
        schedule-version requests in one millisecond. `hardware_uid()` is the
        per-badge value that survives the shared image; the sequential-UID
        argument above is about `machine.unique_id()` and applies to it
        unchanged.
        """
        badge_id = hardware_uid()
        if badge_id is None:
            # NO HARDWARE ID IS THE FIXTURE/HOST CASE, and it degrades to the
            # random draw rather than to the credential: the credential is
            # fleet-constant now, so falling back to it would reintroduce
            # exactly the synchronisation this reads the UID to avoid.
            return self._jittered_delay_ms(0, span_ms)
        try:
            import hashlib

            digest = hashlib.sha256(badge_id.encode("utf-8")).digest()
            total = digest[0] << 8 | digest[1]
        except Exception as exc:
            self.last_error = _error_text(exc)
            return self._jittered_delay_ms(0, span_ms)
        return span_ms * total // 0x10000

    def _revoked_reprobe_due(self, now):
        """Ask the backend whether the floor's slow re-probe has come due.

        AND CLEAR THE LATCH WHEN IT HAS, in one place, because the latch is what
        gates three separate things: this early return, `state` reading REVOKED,
        and `_service_push` refusing to rebuild the doorbell. Clearing it here
        means a recovered floor brings the doorbell back with it -- which is the
        honest outcome, since the doorbell was stopped by the poll's verdict and
        not by one of its own.
        """

        backend = self._backend
        if backend is None:
            return False
        reader = getattr(backend, "revoked_reprobe_due", None)
        if not callable(reader):
            return False
        try:
            due = bool(reader(now))
        except Exception:
            return False
        if due:
            self._revoked = False
            self._emit("revoked_reprobe", source=SOURCE_SERVICE)
        return due

    def _claim_chore(self):
        """Take this frame's one expensive sub-task, or answer False."""
        if self._chore_spent:
            return False
        self._chore_spent = True
        self.chores += 1
        return True

    def _release_chore(self):
        """Hand the frame's budget back after a claim that bought nothing.

        FOR THE RAISE, NEVER FOR A REFUSAL. A pump that claims the budget and
        then raises has taken the frame's one expensive slot away from every pump
        behind it while doing none of the expensive work -- and if the raise
        happens on EVERY frame, the pumps behind it never run at all for the whole
        boot. That is not hypothetical: on 2026-08-29 the score drain called an
        API `scorebox` had deleted, claimed the chore, raised, was contained, and
        `_pump_heartbeat` -- which runs later on the same ladder and needs a chore
        of its own -- never issued a single beat. A badge that never beats is a
        badge no operator can see.

        `chores` COMES BACK DOWN WITH IT, because that counter is the frame
        gate's evidence of what this module made a frame expensive for
        (`test_ft_b_frame_budget`). A claim that was handed back did not.
        """
        if not self._chore_spent:
            return False
        self._chore_spent = False
        self.chores -= 1
        return True

    def _pump_scores(self):
        """Offer one spooled score, if there is one and a socket exists.

        RETIRING COMES FIRST, and it is a whole frame's budget: the delivered
        slot's identity is remembered by the sink and the file work happens here,
        one frame later, so the frame that received the acknowledgement carries
        the response decode and nothing else.

        THE ORDER OF THE GUARDS BELOW IS CX-10'S FIX and it is the whole
        of it. This method used to ask ``box.pending()`` FIRST -- eighteen lines
        above `_claim_chore()` and above the socket check -- so a badge with no
        socket at all paid the cold whole-file spool load in its first serviced
        frame, and a frame that had already spent its budget elsewhere paid it
        anyway. Now: eligibility (which costs nothing), then the RAM question,
        then the budget, then the only file touch there is.

        **EVERY REFUSAL BELOW SAYS SO, ONCE (2026-08-29).** Each of these guards
        used to `return None` in silence -- no line, no event, no `last_error` --
        and the drain runs on EVERY RENDERED FRAME, so silence was the only
        affordable choice while the message was unlatched. `_score_stalled`
        latches it, so the cost is one line per TRANSITION and the owner can read
        why the spool is not moving instead of inferring it. The bug that forced
        this: five real scores sat on the owner's badge for a whole boot while
        the heartbeat and the settings read kept working, and nothing anywhere
        said the drain had stopped.
        """
        if self._score_retire is not None:
            return self._retire_score()
        # THE SOCKET QUESTION IS ASKED ABOVE THE LATCH, not below it, and that
        # ordering IS the fix. `_score_inflight` USED TO BE released by the
        # response sink and by nothing else, so a response that never arrived --
        # a loop rebuilt under the errand, a socket lost on one of the paths that
        # does not reach `polltransport._drop_errands` -- wedged the drain for
        # the whole remainder of the boot. Reading `backend.state` first costs an
        # attribute lookup and lets the latch be released on the evidence.
        # `_release_score_latch` carries the argument in full.
        backend = self._backend
        connected = (backend is not None
                     and getattr(backend, "state", None) == CONNECTED)
        if self._score_inflight is not None:
            released = self._release_score_latch(connected)
            if released is None:
                return self._score_stalled("inflight")
        # ELIGIBILITY BEFORE STORAGE. The spool exists precisely because the
        # badge is sometimes offline, and an offline badge must not read it to
        # discover that it cannot post it.
        if not connected:
            return self._score_stalled("offline")
        # THE OPERATOR'S LEADERBOARD LEVER, AND IT GATES THE DRAIN ONLY.
        # `scorebox.record` is never consulted about this flag, so a badge whose
        # scores are switched off at 2 pm still SPOOLS every round the wearer
        # plays and posts the lot when the switch comes back. Losing a wearer's
        # score because an operator flipped a switch would be far worse than
        # uploading it late, and the spool is durable across the reboot that
        # every app exit is. See `_apply_settings_scores`.
        if not self._scores_enabled:
            return self._score_stalled("fleet_disabled")
        # THE HARDWARE UID, NOT `backend.badge_id()` -- and this is the §0.5
        # implementation trap, stated where the mistake would be made.
        # `DeviceBackend.badge_id` returns the credential's `sub` and MUST keep
        # doing so, because `badge_state`'s RLS is `badge_id = grants.whoami()`
        # and that row has to name the subject to be accepted at all. The
        # LEADERBOARD is the opposite case: it wants the physical badge, and
        # under the shared fleet token the subject would attribute every score in
        # the hall to one row. The two reads sat on the same accessor until
        # 2026-08-26; the split is deliberate and is what the `_self` RPC exists
        # for.
        badge_id = hardware_uid()
        if badge_id is None:
            # No provable identity: the score stays SPOOLED rather than being
            # attributed to the fleet. The drain is durable and idempotent, so
            # nothing is lost -- and a badge that cannot name itself must not
            # write a row that says it is somebody else.
            return self._score_stalled("no_badge_id")
        box = self._score_box()
        if box is None:
            # `_score_box` emits `scorebox_unavailable` with the import error,
            # once per boot, so the CAUSE is already on the log. This says the
            # consequence in the drain's own vocabulary, which is what a reader
            # asking "why is the spool not moving" greps for.
            return self._score_stalled("no_scorebox")
        try:
            # THE FREE QUESTION, and it is the steady frame's whole cost: a spool
            # the module has already read and found empty is an integer compare,
            # and it does not claim the budget the schedule sync wants.
            # `cached_pending() == 0` is the same question the deleted
            # `cached_head() is None` was asking, minus the second global that
            # could disagree with the first (see `scorebox.cached_pending`).
            if box.scan_complete() and box.cached_pending() == 0:
                return self._score_stalled("spool_empty")
        except Exception as exc:
            self.last_error = _error_text(exc)
            return self._score_stalled("spool_unreadable")
        # PAST EVERY GUARD, SO THE LATCH RE-ARMS. Cleared HERE and not at the
        # bottom because the three refusals below it -- a spent chore, a cold read
        # that found nothing, a `take_slot` that raised -- are ordinary
        # frame-to-frame states rather than a drain that has stopped, and latching
        # a message on them would print on every wearer's badge for no reason.
        self._score_stall = None
        # THE BUDGET IS CLAIMED BEFORE ANY FILE WORK. `take_slot` is either a RAM
        # read or the boot's ONE bounded whole-document load; either way it is
        # this frame's one expensive sub-task and a frame that has spent its
        # budget elsewhere does not reach it.
        if not self._claim_chore():
            return None
        try:
            slot = box.take_slot(self._score_path)
        except Exception as exc:
            # THE CHORE GOES BACK, AND THAT IS THE ORDERING FIX (2026-08-29).
            # This claim is taken BEFORE the call that can raise, and
            # `_pump_heartbeat` runs later on the same ladder needing a chore of
            # its own -- so a drain that raised every frame took the frame's one
            # expensive slot every frame and the heartbeat was NEVER issued. A
            # badge in that state never registers with the fleet, which is a
            # badge an operator cannot see at all. Observed for real: the drain
            # called an API `scorebox` had deleted, so the raise was every frame
            # of the boot. Handing the budget back costs a frame nothing -- this
            # path did no file work worth charging for -- and it makes the
            # starvation impossible rather than unlikely.
            self._release_chore()
            self.last_error = _error_text(exc)
            return None
        if slot is None:
            # The cold read found an empty spool. The next frame's free guard
            # answers `spool_empty` from RAM and this costs nothing again.
            return None
        import rpc_contract

        # Keep ``scorebox.row`` as the one mapping from a durable slot to the
        # database vocabulary. The RPC route (never a direct table insert) is
        # what keeps the badge write-only: PostgREST's client-side ON CONFLICT
        # machinery would force SELECT privileges onto ``scores`` and leak the
        # human-only leaderboard read.
        #
        # THE BADGE ID IS NOW SENT, AND THAT IS THE CHANGE. It was deliberately
        # absent while the server could derive it from ``grants.whoami()``, which
        # was strictly better -- no client-supplied id could cross the wire. Under
        # one shared fleet token that derivation names the FLEET, so the stronger
        # design put the whole hall on one leaderboard row. `_self` takes the
        # physical id explicitly: self-reported, spoofable, and accepted for the
        # fun tier. This write is on the FLOOR -- never gated behind a claim,
        # never carrying `x-device-token`.
        #
        # `play_number` REPLACED `idempotency_key` ON THE WIRE (2026-08-29). The
        # database key is `(badge_id, game, play_number, score)` and the insert is
        # `on conflict do nothing`, so a re-post of the identical tuple returns
        # success and creates no second row -- which is the only guarantee the
        # random handle ever provided. There is no `p_idempotency_key` parameter
        # left to send one to.
        row = box.row(badge_id, slot)
        params = rpc_contract.score_submit_self_params(
            badge_id, row["game"], row["score"], row["play_number"],
            row["metadata"])
        # THE IDENTITY IS THE TUPLE `retire` CHECKS, not a handle. It is read out
        # of `row` rather than out of `slot` so that what the sink remembers and
        # what went on the wire cannot drift: this triple IS the row's natural
        # key. `take_slot` hands back a snapshot -- `record` builds a new dict
        # rather than mutating one -- so a better score arriving mid-flight leaves
        # this describing exactly what was posted, which is what makes `retire`'s
        # supersede check meaningful.
        key = (row["game"], row["play_number"], row["score"])
        self._score_inflight = key
        # THE DEADLINE IS ARMED FROM A FRESH TICK, not from `self._now`, and the
        # seam's own docstring is the reason: this runs after `backend.poll`, in
        # a frame that may have paid a multi-second open, so the frame's opening
        # tick can be seconds in the past by the time the errand is handed over.
        self._score_inflight_at = self._ticks_ms()

        # THE SINK CARRIES ITS OWN KEY AND NEVER READS THE LATCH, which is what
        # makes releasing the latch early SAFE. Before the release existed only
        # one post could be outstanding, so "the latch" and "the slot this
        # response is about" were the same thing by construction; they are not
        # any more. A response abandoned on a lost socket can still arrive after
        # the drain has re-offered -- and the round robin means the slot it
        # re-offered is very likely a DIFFERENT GAME, so a sink reading the latch
        # would retire a slot that was never posted. That is the one way this fix
        # could lose a score, and this closure is why it cannot.
        # It costs one function object per POST, on a path already building three
        # dicts and bounded by `polltransport.ERRAND_MIN_GAP_MS`; it is not a
        # per-frame allocation.
        def posted(ok, _data, key=key):
            self._on_score_posted(key, ok)

        queued = self._queue_errand(
            "rpc",
            {"function": rpc_contract.RPC_SCORE_SUBMIT_SELF, "params": params},
            posted,
        )
        if not queued:
            self._score_inflight = None
            self._score_inflight_at = None
        return queued

    def _release_score_latch(self, connected):
        """Take a lost score post back, or answer ``None`` to keep waiting.

        **THE PRIMARY HALF OF THE 2026-08-29 WEDGE FIX, and the important one is
        the socket.** `_score_inflight` was set before the errand was sent and
        cleared in exactly two places -- the queue refusing it, and the response
        sink -- so a response that never came back stopped the drain for the
        REST OF THE BOOT, silently, while the heartbeat and the settings read
        kept working on the same socket. Five real scores sat on the owner's
        badge that way. `polltransport._drop_errands` does notify sinks, but only
        `stop()` and `restart()` reach it: `_abort_parked_open` closes the socket
        and goes DISCONNECTED without it, and a loop REBUILT under a queued
        errand takes the sink to the collector with it.

        **RE-OFFERING IS FREE AND THAT IS WHY THIS IS ALLOWED TO BE BLUNT.** The
        slot is still on flash -- nothing is retired until a response says so --
        and the row's natural key `(badge_id, game, play_number, score)` is what
        the server dedupes on (`on conflict do nothing`). The worst case of
        releasing too eagerly is one duplicate REQUEST and zero duplicate rows;
        the worst case of releasing too late is the wedge above.

        **NOTHING IS COUNTED AND NOTHING CAN BE DISCARDED.** The obvious
        implementation -- call the sink with ``(False, None)`` like
        `_drop_errands` does -- used to run `_count_score_attempt` against
        `scorebox.MAX_ATTEMPTS` of 3, so a wearer walking in and out of range
        three times would have their score DELETED. That counter is gone
        (2026-08-29): a failed post leaves the slot exactly where it is, for ever,
        so this method has nothing left it could spend.

        THE DEADLINE IS THE BACKSTOP, NOT THE FIX. It exists for the path nobody
        has thought of: a response lost while the transport never once reports
        anything other than CONNECTED. See :data:`SCORE_INFLIGHT_MAX_MS`.
        """
        if not connected:
            self._score_inflight = None
            self._score_inflight_at = None
            self._emit("score_latch_released", reason="offline")
            return "offline"
        started = self._score_inflight_at
        if started is None:
            # Armed by something that predates the deadline (a probe, a fixture
            # writing the latch directly). Adopt this tick so the backstop is
            # armed from here rather than never.
            self._score_inflight_at = self._ticks_ms()
            return None
        if _ticks_diff(self._ticks_ms(), started) < SCORE_INFLIGHT_MAX_MS:
            return None
        self._score_inflight = None
        self._score_inflight_at = None
        self._emit("score_latch_released", reason="deadline")
        return "deadline"

    def _score_stalled(self, reason):
        """Say WHY the drain is not draining, ONCE per transition.  Never raises.

        LATCHED, BECAUSE THE CALLER IS EVERY RENDERED FRAME. An unconditional
        line here would be one `print` per frame -- flooding the log the operator
        is trying to read, and paying `_SINK_SLOW_MS`'s ~1,000 ms per blocked
        write on a badge whose USB host has gone away. Latching costs one string
        compare on the steady frame and prints on the EDGE, which is the only
        place the information is.

        THE WORD IS FROM A CLOSED SET THIS PACKAGE SPELLS, never server text, so
        it is safe on `reason` -- the same rule `_PRINTED_FIELDS` states for every
        other word on that whitelist.
        """
        if self._score_stall != reason:
            self._score_stall = reason
            self._emit("score_stalled", reason=reason)
        return None

    def _on_score_posted(self, key, ok):
        """The sink, and it CAPTURES rather than works.

        The frame that receives an errand response has already paid for the
        response: `device_link._finish` decoded it. Retiring the slot is a
        whole-file read plus an atomic swap, so it is remembered here and
        performed by `_retire_score` on a later frame.

        ``key`` IS THE POST'S OWN ``(game, play_number, score)`` AND ARRIVES FROM
        THE CLOSURE, not from `_score_inflight`. `_pump_scores` says why in full;
        the short form is that the latch is no longer proof of which slot a
        response is about.

        A RESPONSE THAT LOST ITS RACE IS DROPPED WHOLE. If the latch is already
        clear, or names a different slot, this response belongs to a post the
        drain has taken back: the slot it names is either already retired or
        already re-offered, and acting again could only retire something twice.
        Dropping is safe in both directions because the spool is the truth and it
        is durable.

        **A REFUSAL COSTS THE WEARER NOTHING AT ALL.** There is no counter left
        to strike and no cap to reach: the slot stays exactly where it is and the
        round robin offers the other four games in the meantime. There is no
        backlog to drain -- five games, five slots -- so there is nothing to
        hurry for either. See the section note above for why `MAX_ATTEMPTS` went.
        """
        self._response_continuation = True
        if self._score_inflight != key:
            return
        self._score_inflight = None
        self._score_inflight_at = None
        box = self._score_box()
        if box is None or key is None:
            return
        if ok:
            self._score_refused = False
            self._score_retire = key
            return
        # ONE LINE PER OUTAGE, NOT ONE PER REFUSAL. A slot the server keeps
        # refusing -- the realistic case is a fleet whose `scores/write` grant is
        # missing, which refuses all five -- comes back round once per errand gap
        # for the whole boot, so an unconditional line here is the per-frame flood
        # `_score_stalled` exists to avoid. Latched instead, and re-armed by the
        # next success, so the SECOND outage is reported too.
        if not self._score_refused:
            self._score_refused = True
            # NO `game=`. The event NAME is the printed signal; a game slug is a
            # string this package did not format, and `_PRINTED_FIELDS` carries
            # only words it spells -- so the field would reach no serial console
            # and would owe the emitted-field census a written excuse for that.
            self._emit("score_refused")

    def _retire_score(self):
        """Clear one DELIVERED slot.  This frame's one expensive sub-task.

        DELIVERY IS THE ONLY REASON THIS RUNS NOW. It used to serve a delivered
        slot and an EXHAUSTED one, because retiring was the same operation either
        way; `MAX_ATTEMPTS` is gone, so nothing is exhausted and nothing is
        thrown away.

        ⚠ **`scorebox.retire` ANSWERS False AND THAT ANSWER IS LOAD-BEARING.** A
        round trip takes frames and a player can finish another round inside one,
        so the slot on flash may no longer be the slot that was posted. `retire`
        compares BOTH the play number and the score against the FILE and refuses
        to clear a slot that has been superseded -- which is the guard against
        the race `40cec1ff` was written for, where a stale OK would have retired
        a score that was never posted. A drain that ignored the return value
        would put the better score's fate back in the hands of the response's
        timing; honouring it means the delivered row is in the database, the
        better one is still pending, and nothing is duplicated or lost.
        """
        if not self._claim_chore():
            return None
        key = self._score_retire
        self._score_retire = None
        box = self._score_box()
        if box is None or key is None:
            return None
        game, play, score = key
        try:
            cleared = box.retire(game, play, score, self._score_path)
        except Exception as exc:
            # THE ROW LANDED AND THE SPOOL STILL HOLDS IT, so the next rotation
            # offers the same slot again. The natural key makes the repost a
            # server-side no-op (`on conflict do nothing`), so a read-only volume
            # costs one duplicate REQUEST per rotation and never a duplicate row
            # -- and never a deleted score, which is what the attempt counter that
            # used to be struck here would eventually have done.
            self.last_error = _error_text(exc)
            self._emit("score_retire_failed", error=self.last_error)
            return False
        if not cleared:
            # SUPERSEDED WHILE IN FLIGHT. The posted row is in the database and
            # the slot now holds a BETTER score, still pending. Saying
            # `score_posted` here would be true about the row and misleading
            # about the spool, which is the thing an operator is reading this log
            # to understand.
            self._emit("score_superseded")
            return False
        self._emit("score_posted")
        return True

    # -- the wearer's name ---------------------------------------------------

    def _wearer_name(self, chore_held=False):
        """The wearer's typed name, or ``None`` to WAIT.  Never raises.

        ``chore_held`` says THE CALLER ALREADY TOOK THIS FRAME'S CHORE and this
        read is the work it took it for. It exists because `_pump_heartbeat` now
        claims the budget for the whole beat, and without it the two claims would
        collide EVERY time: the beat would take the chore, this read would be
        refused it, and the name would be omitted from the row on every beat for
        the whole boot -- a field silently always null, which is indistinguishable
        from a wearer who never typed one.

        ``""`` MEANS "READ, AND THERE IS NONE"; ``None`` means "not yet, ask
        again next frame". The two are different because the caller must not
        report an unattributed name merely because the budget was spent
        elsewhere.

        ITS CONSUMER IS THE HEARTBEAT NOW (rebuild, 2026-08-29). This was
        `_telemetry_wearer_name` and it stamped a diagnostic row; the badge
        reports `wearer_name` UP on `POST /rest/v1/badges` instead of being told a
        `display_name` DOWN, so this is the reader that feeds it.
        `scorebox.wearer_name` is the source because it is the same reader that
        attributes a SCORE -- a leaderboard row and a heartbeat can never disagree
        about who this badge is.

        THIS IS THE ONLY FILE TOUCH ON THE PATH, IT HAPPENS ONCE PER BOOT, AND IT
        CLAIMS THE FRAME'S CHORE BEFORE IT HAPPENS. `wearer_name` opens
        `/state/badgecard.json` and decodes it -- one open, one decode, the exact
        CX-10 frame allowance -- and caches the answer for the rest of the boot,
        so every later heartbeat carries a RAM string. It is reached after
        `_pump_scores` in the poll block, so a frame the score drain already
        claimed simply defers it by one; nothing is lost, because the next beat is
        sixty seconds away.

        WHY NOT IN THE CONSTRUCTOR: because
        `test_cx10_boot_json_cost.ConstructorTests` pins the constructor's opens
        as an exact SET, and this may not be the thing that adds a boot-path file
        read. The name is a property of the WEARER rather than of any one report,
        so reading it lazily loses nothing.
        """
        if self._wearer_name_cached is not False:
            return self._wearer_name_cached
        box = self._score_box()
        if box is None:
            # No `/system/lib` scorebox means no reader for setup's card state.
            # Recorded as "there is no name" rather than retried: the module is
            # not going to appear later in this boot.
            self._wearer_name_cached = ""
            return self._wearer_name_cached
        if not (chore_held or self._claim_chore()):
            return None
        try:
            found = box.wearer_name(self._card_state_path)
        except Exception as exc:
            # `wearer_name` is total, so this is a `/system/lib` whose scorebox
            # predates it. Contained and never retried, for the same reason.
            self.last_error = _error_text(exc)
            self._emit("wearer_name_contained", error=self.last_error)
            self._wearer_name_cached = ""
            return self._wearer_name_cached
        self._wearer_name_cached = found if isinstance(found, str) else ""
        return self._wearer_name_cached

    def _apply_wipe_scores(self, payload):
        """Discard this badge's UNSENT scores; on ``all``, its high scores too.

        WHAT IT CANNOT DO, WRITTEN HERE BECAUSE AN ACK IS READ AS A CLAIM: it
        does not un-send anything. A wipe reaching a reconnecting badge arrives on
        the SAME socket the drain is already using, so rows may be delivered
        before it applies, and delivered rows are the backend's -- a view cutoff
        or a `delete`, no firmware. This command stops FUTURE sends. It is not
        sufficient on its own and nothing in the ack claims it is.

        THE DRAIN'S RAM STATE IS DELIBERATELY LEFT ALONE. `_score_inflight` names
        an RPC that is already on the wire and cannot be recalled; clearing it
        would only let a second drain start beside it. The retire that follows
        finds the slot gone and `scorebox.retire` returns False without raising,
        which `_retire_score` already treats as "leave it alone". What DOES have
        to be reset is the module-level cache, and `scorebox.wipe` owns that.

        ⚠ THAT PARAGRAPH IS SCOPED TO A LIVE SOCKET AND `_release_score_latch`
        DOES NOT CONTRADICT IT (2026-08-29). The reason not to clear here is that
        the response IS still coming; the reason to clear there is that it is
        not. Read together they are one rule -- release the latch exactly when
        the errand can no longer answer -- and the second drain that argument
        warns about is now a case the sink itself survives, because it carries
        its own key rather than reading the latch.

        VERSION-SKEW GUARDED. An older `/system/lib` has a `scorebox` with neither
        call, and an `AttributeError` here would ack "failed" with a message that
        reads like a bug rather than like a stale install.
        """

        scope = _wipe_scope(payload)
        box = self._score_box()
        if box is None:
            # No scorebox means no spool -- but acking "applied" would hide a
            # half-refreshed library behind a success, and this is the one
            # channel that could tell the operator.
            raise ValueError("wipe_scores needs scorebox and this badge has none")
        wipe = getattr(box, "wipe", None)
        if wipe is None:
            raise ValueError("this badge's scorebox predates wipe_scores")
        # BEFORE THE WIPE, or the answer is always zero. One bounded whole-file
        # read, once, on the frame a command arrives -- which is the caller class
        # `pending` documents (a screen, a snapshot, a probe) and not the per-frame
        # drain path CX-10 took it out of.
        discarded = box.pending(self._score_path)
        if not wipe(self._score_path):
            # `wipe` never raises and reports instead, so this is where a failed
            # rewrite becomes a fail-ack: the spool is still full, and an
            # "applied" would tell the operator their backlog is gone.
            raise ValueError("wipe_scores could not rewrite the spool")
        result = {"effect": "wipe_scores", "scope": scope,
                  "discarded": discarded}
        if scope == WIPE_SCOPE_ALL:
            wipe_bests = getattr(box, "wipe_bests", None)
            if wipe_bests is None:
                raise ValueError("this badge's scorebox predates wipe_scores")
            removed, failed = wipe_bests()
            # COUNTS RATHER THAN A VERDICT, because the receipt vocabulary has
            # two words and neither of them is "partly".
            # A game that was never played is neither removed nor failed, which
            # is normal -- three of the five are off the production roster.
            result["bests_removed"] = removed
            result["bests_failed"] = failed
        self._emit("scores_wiped", scope=scope, discarded=discarded)
        return result

    # -- the battery levers (fleet battery management, 2026-08-28) ----------
    #
    # TWO VERBS, ONE MECHANISM, AND THE MECHANISM IS THE HARD PART. BOTH of
    # them (`sleep`, and `set_networking` with `on: false`) DESTROY THE CHANNEL
    # THEY ARRIVED ON. Neither acts inline: the applier validates and arms
    # `self._power`, `_pump_broadcast_actions` binds the keyed receipt after the
    # applier returns, and `_pump_power_action` acts from a later frame only after
    # that receipt attempt finishes or its bounded deadline expires. Otherwise
    # sleep could prevent its own audit row from ever leaving the badge.
    #
    # RAM-ONLY IS LOAD-BEARING. A `/state` file saying "sleep when you next boot"
    # survives the reboot that waking IS and could put a badge straight back to
    # sleep forever. Missing a moment after a reset is safer than creating a
    # fleet that needs the RESET pin to recover.

    def _arm_power_action(self, action, needs_ack=True):
        """Latch one deferred power action.  RAM-only, one at a time.

        ``needs_ack=False`` IS THE PRODUCTION FORM. `_pump_broadcast_actions`
        binds the resulting receipt after this applier returns, and
        `_pump_power_action` lets the POST finish (success or failure) before
        destroying its channel, with a hard timeout that still acts. The True
        default exists only for the retained compatibility callback and is not
        reachable from the broadcast lane.

        NEVER DURABLE, for the reboot-loop reason above. A broadcast is never
        redelivered, so nothing here needs to outlive the boot.

        THE SECOND ONE WINS. Two broadcasts arriving a few frames apart are an
        operator changing their mind, and the newer moment is the newer intent.
        Each still receives its accepted receipt attempt; only the newer moment
        owns the physical latch. The result says `applies: "after_receipt"`
        rather than pretending the hardware action is already done.
        """

        self._power = {
            "action": action["action"],
            "seconds": action.get("seconds"),
            "persist": action.get("persist", False),
            # A persistent radio-off is accepted only after its atomic write
            # succeeds. Carry the proof so the deferred frame tears down the
            # radio without repeating a fallible write after the receipt.
            "preference_saved": action.get("preference_saved", False),
            "preference_before": action.get("preference_before"),
            # The broadcast envelope binds these after `_apply` returns, because
            # the applier deliberately does not know an action id.
            "receipt_action_id": None,
            "receipt_done": False,
            "receipt_status": None,
            "receipt_deadline": None,
            # `acks_sent` BEFORE this command's own ack is queued. `_on_command`
            # queues it a few statements later, in the same synchronous call, so
            # no exchange can complete in between and this baseline is exact.
            "sent_at_arm": self._backend_acks_sent(),
            # `None` MEANS "NOT PROVEN YET" AND `0` MEANS "NOTHING TO PROVE".
            # `_note_power_ack` fills the first in from `queue_ack`'s FIFO depth;
            # the second is what a caller with no ack in the first place arms
            # with, and it is a distinct value rather than a second flag so that
            # `_pump_power_action` reads one field. See `needs_ack` above.
            "needed": None if needs_ack else 0,
            "deadline": _ticks_add(self._ticks_ms(), POWER_ACTION_ACK_MS),
            "note_until": None,
        }
        return self._power

    def _note_power_ack(self, depth):
        """Record the FIFO depth `queue_ack` reported for the armed action.

        THE ONE NUMBER THAT MAKES DELIVERY PROVABLE. `PollLoop` pops an ack only
        when its exchange SUCCEEDS (`_pump_inflight`; a `LinkError` leaves it at
        the head) and increments `acks_sent` on the same line, and the queue is
        FIFO -- so once `acks_sent` has advanced by the depth this ack was queued
        at, this ack is one of the ones that went.

        A DEPTH THAT IS NOT A POSITIVE INT MEANS "CANNOT PROVE", AND CANNOT PROVE
        MEANS NEVER ACT. `DeviceBackend.queue_ack` answers 0 when no `PollLoop`
        exists yet, and a fixture backend answers None; either way the ack was
        not handed to a transport that counts, so `needed` stays None and
        `_pump_power_action` abandons at its deadline rather than sleeping a badge
        whose server still believes the command failed.
        """

        power = self._power
        if power is None or power["needed"] is not None:
            return None
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
            return None
        if not isinstance(power["sent_at_arm"], int):
            return None
        power["needed"] = depth
        return depth

    def _backend_acks_sent(self):
        """`PollLoop.acks_sent`, or None when this badge cannot answer.

        Duck-typed and contained exactly like `_backend_establishment_steps`: a
        fixture backend, a boot with no loop yet, or a `/system/lib` older than
        the seam all answer None -- which the caller reads as "cannot prove", the
        direction that never sleeps.
        """

        backend = self._backend
        reader = getattr(backend, "poll_loop", None)
        if not callable(reader):
            return None
        try:
            loop = reader()
        except Exception:  # noqa: BLE001 - a diagnostic may not cost a frame
            return None
        sent = getattr(loop, "acks_sent", None)
        if isinstance(sent, bool) or not isinstance(sent, int):
            return None
        return sent

    def _pump_power_action(self, now):
        """Perform a deferred power action after its delivery proof/attempt.

        RUNS AT THE TOP OF A FRAME, OUTSIDE `poll`'s try, AND THAT PLACEMENT IS
        DELIBERATE. Sleeping or tearing the backend down inside the action sink
        would destroy the transport while it is still draining the Realtime
        frame. A later frame owns nothing.

        THREE STAGES, and the note is why there are three rather than two:

        1. **Finish observability.** A broadcast waits for its keyed receipt
           attempt, then acts whether that POST succeeded, failed or hit its
           hard timeout. The old callback's ack branch remains compatibility
           containment only; production never arms it.
        2. **Show the note**, repainted on every frame for `SLEEP_NOTE_MS`. It
           has to be repainted: this runs AFTER the foreground app's own
           `update()` (see `managed_run.managed_update`), so the app clears and
           redraws the panel every frame and a single paint would survive about
           one frame. Repainting lands on top of whatever is there and the
           framework presents it, in the launcher and in any app alike.
        3. **Act**, which for `sleep` does not return.

        ⚠ THE RECEIPT DEADLINE ACTS. A broadcast is never redelivered, so a
        missing audit response may not veto the moment; its deadline emits
        `power_receipt_timeout` and releases the latch. The compatibility ack
        branch still abandons because it cannot prove delivery.

        ⚠ NEVER RAISES, except for the browser's reset (see `_run_power_action`).
        `poll` is called from every app's frame pump, and an exception out of
        here reaches `fatal_error`, which draws a modal and resets the badge --
        a crash for a command the wearer did not ask for.
        """

        power = self._power
        if power is None:
            return None
        try:
            if power["note_until"] is not None:
                # Repaint first, act second: the last frame that draws is the
                # frame that sleeps, and the panel keeps the note it was showing
                # because nothing presents after a call that does not return.
                self._paint_sleep_note(power)
                if _ticks_diff(now, power["note_until"]) < 0:
                    return "note"
                return self._run_power_action(power)
            proven = False
            needed = power["needed"]
            if needed == 0:
                # NO ACK TO PROVE. A LIVE BROADCAST IS BOUND TO ITS RECEIPT by
                # `_pump_broadcast_actions`; direct applier fixtures remain
                # unbound and keep the original later-frame behavior.
                receipt_id = power.get("receipt_action_id")
                if receipt_id is not None and not power.get("receipt_done"):
                    deadline = power.get("receipt_deadline")
                    if deadline is None or _ticks_diff(now, deadline) < 0:
                        return "receipt"
                    power["receipt_done"] = True
                    power["receipt_status"] = "timeout"
                    self._emit("power_receipt_timeout",
                               action=power["action"])
                proven = True
            elif needed is not None:
                sent = self._backend_acks_sent()
                if isinstance(sent, int) and not isinstance(sent, bool):
                    proven = (sent - power["sent_at_arm"]) >= needed
            if not proven:
                if _ticks_diff(now, power["deadline"]) < 0:
                    return "waiting"
                self._power = None
                self._emit("power_action_abandoned",
                           action=power["action"], reason="ack_undelivered")
                return "abandoned"
            if power["action"] != "sleep":
                return self._run_power_action(power)
            power["note_until"] = _ticks_add(now, SLEEP_NOTE_MS)
            self._paint_sleep_note(power)
            return "note"
        except Exception as exc:  # noqa: BLE001 - see the docstring
            if type(exc).__name__ == "MachineResetRequested":
                # THE BROWSER'S REBOOT IS NOT A FAILURE. `settings/__init__._sleep`
                # found this first: the playground models `powman.sleep()` as an
                # event plus `machine.reset()`, which raises this type, and
                # `pg_runtime.step_frame` catches that exact type to end the
                # session. Matched BY NAME rather than imported, because
                # `machine.MachineResetRequested` does not exist in the firmware
                # and importing it would put a browser conditional in shipping
                # code. Unreachable on hardware: `powman.sleep()` never returns.
                raise
            self._power = None
            self.last_error = _error_text(exc)
            self._emit("power_action_failed",
                       action=power["action"], error=self.last_error)
            return "failed"

    def _paint_sleep_note(self, power):
        """One note frame.  Contained, because a panel may not cost a sleep."""

        try:
            self._sleep_note(sleep_note_lines(power["seconds"]))
        except Exception:  # noqa: BLE001 - see `_draw_sleep_note`
            pass

    def _run_power_action(self, power):
        """Do the thing.  The latch is cleared FIRST, always.

        CLEARED BEFORE THE ACT so no failure path can leave it armed: a `sleep`
        that returned (a fixture, the browser) would otherwise sleep again on
        every frame for ever, which is `settings_model`'s own ONE-SHOT rule for
        the same call.
        """

        self._power = None
        if power["action"] == "networking_off":
            if power["persist"]:
                # THE FLASH WRITE ALREADY SUCCEEDED IN THE APPLIER, before the
                # accepted receipt. Repeating it here reintroduced a false-
                # success path: `set_enabled` contains write failures because a
                # Settings press must not reset the app, then this deferred lane
                # emitted success anyway. The remaining edge is pure teardown.
                #
                # ⚠ THERE IS NO REMOTE ESCAPE. Broadcast moments are not held
                # for offline badges, and the owner explicitly cut scheduling.
                # Reintroducing a local delayed-on file would recreate the stale
                # catch-up model the rebuild removed.
                #
                # SO `persist: true` IS ONE-WAY, AND THE ONLY UNDO IS A HUMAN
                # HOLDING THE BADGE: Settings > Network, on the device, in the
                # wearer's hand. THE OWNER ACCEPTED THAT KNOWINGLY, verbatim:
                # *"we know what the implications are, so we would only do that
                # if we really wanted to or needed to."* It is the end-of-day
                # fleet shutdown and nothing else.
                if not power.get("preference_saved"):
                    raise ValueError("persistent networking action was not saved")
                self._go_offline("preference")
            else:
                self._go_offline("network_suspended")
            # ONE GREPPABLE LINE FOR BOTH FORMS, carrying the flag that is the
            # whole difference between them. The two teardown events above are
            # deliberately different words for an operator watching serial live;
            # this is the one an incident review searches for afterwards, and a
            # review that had to know which word to grep would find neither.
            self._emit("networking_off", persist=power["persist"])
            return "networking_off"
        return self._sleep_now(power["seconds"])

    def _sleep_now(self, seconds):
        """Take the badge dormant.  THE ORDER IS THE WHOLE OF THE SAFETY.

        Lifted from `settings/badge/settings/__init__._sleep`, whose docstring is
        the specification, with the one deliberate difference noted below.

        * **The service's own `on_exit` first.** Waking is a FULL REBOOT of
          `main.py` (`docs/design/constraints.md:115`) and nothing survives RAM,
          so anything that has to be put back has to be put back here or not at
          all. What this object owns is the two physical channels a remote effect
          can have taken over, which is exactly `_clear_remote_effects`.
        * **Then the network DOWN**, because a socket left open across dormancy
          is a socket the server keeps waiting on. ⚠ THIS IS STRONGER THAN THE
          SETTINGS ROUTINE, WHICH CALLS `set_active(False)`: that only relaxes
          the poll CADENCE and leaves the TLS socket open. `_stop_backend` closes
          it, and the doorbell's with it. The preference file is untouched, so
          the badge comes back networked -- which is required, or a slept fleet
          would also be a disconnected one.
        * **Then the log**, so a tethered operator sees the intent even though
          the next call does not return.
        * **Then sleep.**

        THE ARGUMENT IS SECONDS AND THE TWO FORMS ARE DIFFERENT HARDWARE.
        Measured on device 2026-08-21 (report §6): `sleep()` reaches
        `powman.sleep()` and arms A/B/C/UP/DOWN; `sleep(n)` reaches
        `goto_dormant_for(n)` and arms THE ALARM ALONE. HOME is not a wake source
        either way. So the timed form is a badge whose five face buttons are dead
        until the alarm expires, and RESET is the only escape -- which is
        `SLEEP_MAX_MINUTES`' whole job.

        ⚠ **THE TIMED FORM HAS NO BADGE-SIDE TWIN AND THE OWNER IS OWED THAT
        SENTENCE.** His standing rule is that every admin control has a
        badge-side equivalent a wearer can undo it with. Settings offers only the
        INDEFINITE form, and a timed sleep ignores the button a wearer would
        press, so the wearer's normal wake gesture does nothing. RESET is the
        twin. That is accepted -- it is what "sleep the fleet for a talk, RESET
        is the opt-out" means -- but it is an exception to the rule, not an
        instance of it.
        """

        api = self._badge_api
        sleeper = getattr(api, "sleep", None)
        if not callable(sleeper):
            # Defensive backstop for a hardware API that changed after the
            # applier's preflight. Normal absence fails before acceptance.
            self._emit("sleep_unavailable")
            return "unavailable"
        self._clear_remote_effects()
        self._stop_backend()
        self._emit("sleeping", seconds=seconds)
        if seconds is None:
            sleeper()
        else:
            sleeper(seconds)
        # ONLY REACHED IF THE CALL RETURNED, which on hardware it never does.
        # The badge carries on; `poll` rebuilds the backend on the next frame
        # because the preference was never written.
        self._emit("sleep_failed")
        return "sleep_failed"

    def _apply_set_networking(self, payload):
        """Radio off (or on), temporarily by default and durably on request.

        THE PAYLOAD IS WHERE THE DANGER IS LEGIBLE, and that is the owner's
        requirement rather than a style choice (2026-08-28): *"it should be very
        obvious when we're doing the destructive one, because Wi-Fi off as a
        permanent instruction means we're not getting this back unless someone
        manually goes into the badge and enables it again."* So:

            {"on": false}                  temporary -- back at the next reset
            {"on": false, "persist": true} permanent -- wearer-only undo

        DEFAULT TEMPORARY, PERSISTENCE SPELLED IN THE ROW. The flag lives in the
        payload rather than in a console mode so that the `fleet_actions` row
        itself carries the intent, and the audit trail can be read years later
        without knowing what UI somebody was looking at.

        TEMPORARY IS FREE ON THIS HARDWARE. Every app exit is a `machine.reset()`
        (`docs/tufty-architecture.md`), so a transient off ends the moment the
        wearer opens anything -- which is the semantic the owner asked for, at no
        cost in state.

        WHAT IT SAVES IS REAL, AND THE CHAIN IS CITED SO NOBODY RE-DERIVES IT:
        both forms reach `_go_offline` -> `_stop_backend` ->
        `DeviceBackend.stop()` -> `_wifi.stop(power_down=True)` ->
        `wlan.active(False)` (`network/badge/resilient_wifi.py:350-351`). The
        radio is POWERED DOWN, not merely disassociated or idle.

        DEFERRED, NOT IMMEDIATE, for the reason this whole section exists: the
        effect has to be taken from a later frame, not from inside the transport
        call stack it is about to tear down. `on: true` is applied inline
        instead, because bringing the radio UP destroys nothing.

        ⚠ `on: true` IS ALMOST ALWAYS UNDELIVERABLE. A broadcast has no durable
        hold, and the owner ruled out scheduling. The badge
        that needs an `on` is by definition the badge that cannot hear it, so
        `on: true` is only ever useful to CANCEL an off that has not fired yet
        (below) -- it is not a recovery path, and "queue the off and the on
        together" is not a thing an operator can do.

        THEREFORE `persist: true` IS ONE-WAY, WEARER-ONLY UNDO, AND ACCEPTED.
        See `_run_power_action`'s flash-write branch for the owner's words.
        """

        on, persist = _networking_intent(payload)
        if on:
            # AND IT CANCELS AN OFF THAT HAS NOT FIRED YET. Two rows in one poll
            # response is an operator changing their mind inside three seconds,
            # and letting an armed off run after an explicit on would take the
            # radio down moments after being told to bring it up -- with no way
            # left to say so again. A pending SLEEP is deliberately NOT cancelled:
            # it is a different intent, and this verb says nothing about it.
            pending = self._power
            cancelled = (pending is not None
                         and pending["action"] == "networking_off")
            if persist:
                # Like the off form, a durable claim is accepted only after the
                # atomic preference write succeeds. This is usually delivered
                # only while the badge is already online, but the row must still
                # describe what was actually stored.
                network_preference.save(True, self._preference_path)
            elif cancelled and pending.get("preference_saved"):
                # The superseded off already performed its preflight write.
                # Restore the value it replaced before cancelling the latch, so
                # last-write-wins is true after reset as well as in this frame.
                network_preference.save(
                    bool(pending.get("preference_before")),
                    self._preference_path)
            if cancelled:
                self._power = None
            if not self._enabled:
                # Transient ON must not write the wearer's preference. A badge
                # already offline cannot normally receive it; this path exists
                # for a same-response cancellation and deterministic fixtures.
                self._clear_cause_latch()
                self._enabled = True
                self._defer_once = True
                self._emit("networking_resumed", enabled=True)
            return {"effect": "networking", "on": True, "persist": persist,
                    "applies": "immediate", "cancelled_pending_off": cancelled}
        preference_saved = False
        preference_before = None
        if persist:
            # KNOWABLE BEFORE ACCEPTANCE. A full/read-only state partition must
            # produce `action_failed`, not an accepted receipt followed by a
            # radio that stayed up. The deferred frame only tears down transport.
            preference_before = network_preference.load(self._preference_path)
            network_preference.save(False, self._preference_path)
            preference_saved = True
        # ``needs_ack=False``, FOR WORD FOR WORD THE REASON `_apply_sleep` GIVES
        # ELEVEN LINES BELOW, AND IT WAS LEFT LIVE ON THIS VERB WHEN SLEEP WAS
        # FIXED (2026-08-29). Reproduced before the fix: the radio stayed up, the
        # badge waited out `POWER_ACTION_ACK_MS`, emitted `power_action_abandoned
        # reason=ack_undelivered`, while the applier had already claimed
        # `applied` --
        # a console button that could look successful and do nothing.
        #
        # WHY THE GUARD IS SAFE TO DROP, which is the half worth writing down.
        # Stage 1 of `_pump_power_action` existed to hold back a REDELIVERY LOOP,
        # and the loop was a property of the COMMAND QUEUE rather than of power:
        # `powman.sleep()` never returns, so a `badge_commands` row that acted
        # before its ack was answered stayed unacked, the server redelivered it on
        # its five-attempt cap, and the badge woke into the same row. A BROADCAST
        # IS NEVER REDELIVERED -- `public.fleet_actions` fans a moment out ONCE to
        # whoever is listening, the server holds no open row waiting to be
        # answered, and `fleet_receipts` is owed to nobody -- so there is no
        # second delivery for a recovered badge to be handed. This verb is the
        # milder of the two anyway: the badge keeps running as a name tag and
        # nothing here fails to return.
        #
        # AND THE PROOF WAS ALREADY UNOBTAINABLE, so `needs_ack=True` could only
        # ever abandon. `_on_command` was the sole caller of `_note_power_ack`,
        # `queue_ack` now drops what it is handed, and `PollLoop.acks_sent` is
        # documented "PERMANENTLY 0 SINCE THE REBUILD" -- nothing has advanced it
        # since. `needed` therefore stayed `None` for ever, which
        # `_pump_power_action` correctly reads as "cannot prove" and correctly
        # resolves by abandoning. The pump is right; the arming was wrong.
        self._arm_power_action({"action": "networking_off", "persist": persist,
                                "preference_saved": preference_saved,
                                "preference_before": preference_before},
                               needs_ack=False)
        # `persist` IS ECHOED BACK so the console can show what actually
        # happened rather than what somebody meant to send, and so a row read
        # back months later still says which of the two commands it was.
        return {"effect": "networking", "on": False, "persist": persist,
                "applies": "after_receipt",
                "undo": "settings" if persist else "reset"}

    def _apply_sleep(self, payload):
        """Take this badge dormant, from a later frame.

        THE KILLER LEVER, and the only one that is a step change: it turns
        EVERYTHING off, where `set_networking` only shaves a component. The use
        case is a talk that does not need badges -- the fleet sleeps for its
        duration and wakes itself at the end, and anyone who disagrees taps
        RESET and keeps using their badge at their own battery cost.

            {}                -> indefinite; A/B/C/UP/DOWN wake it (not HOME)
            {"minutes": 30}   -> timed; the ALARM alone, RESET is the only escape

        THE PAYLOAD RULES ARE `_sleep_seconds`', so every delivery path shares
        one strict validator. A broadcast fires when it arrives; there is no
        queue-time or future-fire path.

        MID-APP IS FINE, AND IT IS THE ONE PLACE THIS VERB IS SIMPLER THAN
        `open_app`. That verb needs a durable note because one boot buys one menu
        visit plus one app, so an in-app open has no launcher to return to. Sleep
        needs no launcher: waking is a full reboot into `/system/main.py`, so the
        wearer lands on the LAUNCHER whatever they were in, and the note says so.
        What it costs is the running app's unsaved RAM -- which is exactly what a
        HOME press already costs on this hardware, every time, since every app
        exit is a `machine.reset()`. Two consequences worth knowing rather than
        fixing: a game in progress is lost the same way HOME loses it, and a
        badge inside a non-opted-in app may not have an establishment window at
        all under OWNER RULING #22, so it simply never receives the command and
        stays awake.
        """

        seconds = _sleep_seconds(payload)
        # A missing hardware API is knowable before acceptance. The old shape
        # armed cleanly, claimed `applied`, and only later emitted
        # `sleep_unavailable`; accepted evidence for a badge that cannot sleep
        # is false evidence.
        if not callable(getattr(self._badge_api, "sleep", None)):
            raise ValueError("this badge exposes no sleep control")
        # ``needs_ack=False``, OR THIS VERB ARMS AND NEVER FIRES. THIS WAS A LIVE
        # DEFECT, fixed 2026-08-29, and the failure was silent in the worst
        # direction: the applier returned cleanly, `_pump_broadcast_actions`
        # counted it applied and armed an `applied` receipt, and the badge then sat
        # for `POWER_ACTION_ACK_MS` and emitted `power_action_abandoned
        # reason=ack_undelivered` without ever sleeping. A console button that
        # reports success to a room and does nothing.
        #
        # WHAT THE ACK WAS FOR, so nobody reads this as dropping a safeguard.
        # Stage 1 of `_pump_power_action` refused to act until `PollLoop.
        # acks_sent` proved the badge's ack had left, and the hazard it was
        # holding back was a REDELIVERY LOOP: `powman.sleep()` does not return,
        # so a `badge_commands` row that slept before its ack was answered stayed
        # unacked, the server redelivered it on its five-attempt cap, the badge
        # woke through a full reboot with nothing in RAM, polled, was handed the
        # same row and slept again -- a fleet nobody can use without finding the
        # RESET pin.
        #
        # A BROADCAST CANNOT PRODUCE THAT LOOP, and that is why the requirement
        # is gone rather than merely inconvenient. A moment is fanned out ONCE to
        # whoever is connected (`public.fleet_actions`); the server holds no open
        # row waiting to be answered, `fleet_receipts` is not an ack owed to a
        # durable command, and
        # `_pump_broadcast_actions`' own comment states the shape -- a broadcast
        # has no durable hold. So there is nothing left for a
        # woken badge to be handed a second time; waking is just awake.
        #
        # AND THE PROOF WAS ALREADY UNOBTAINABLE. The ack lane died with the
        # command queue: `_on_command` was the only caller of `_note_power_ack`,
        # `queue_ack` now drops what it is handed, and `PollLoop.acks_sent` is
        # documented "PERMANENTLY 0 SINCE THE REBUILD". `needed` therefore stayed
        # `None` for ever, which `_pump_power_action` correctly reads as "cannot
        # prove" and correctly resolves by abandoning. The pump is right; the
        # arming was wrong. The broadcast envelope now adds a separate bounded
        # receipt-before-power gate: it preserves operator observability without
        # recreating the deleted ack or allowing a receipt failure to veto sleep.
        self._arm_power_action({"action": "sleep", "seconds": seconds},
                               needs_ack=False)
        # `applies: after_receipt` RATHER THAN `applied`, because the honest
        # answer is accepted/armed: the keyed receipt attempt must finish, then
        # the note is shown, then hardware acts. `_pump_broadcast_actions`
        # discards this rich dict (the receipt column is text), but keeping the
        # field honest prevents a direct diagnostic from reviving the dead ack
        # model in its interpretation.
        # `wake` names the ONLY escape for the timed form, so an operator reading
        # the row later can see what they committed a room to.
        return {"effect": "sleep", "seconds": seconds,
                "applies": "after_receipt",
                "wake": "buttons" if seconds is None else "alarm_or_reset"}

    # -- schedule sync (Card FT-B item 4) -----------------------------------
    #
    # CHEAP WHEN NOTHING CHANGED, which is the whole point of Card FT-S's derived
    # version. On cadence the badge calls `badgelink_schedule_version()` and
    # compares ONE string for equality; a badge whose schedule has not moved pays
    # one small round trip and touches no filesystem. Only a disagreement starts
    # a fetch.
    #
    # THE FETCH IS PAGED because `postgrest.MAX_BODY_BYTES` is 8192 for request
    # AND response and a conference schedule is bigger than that. Pages of
    # `schedule_store.PAGE_ROWS` accumulate in RAM and the file is written ONCE,
    # so a half-fetched schedule is never a schedule the badge shows.
    #
    # THE VERSION IS CAPTURED BEFORE THE FIRST PAGE and stored with the rows. If
    # the schedule is edited mid-fetch the stored version is the OLD one, which
    # disagrees with the next check and refetches -- one wasted fetch, never a
    # cache that believes it is current when it is not.
    #
    # AND THE WHOLE SYNC IS SPREAD ACROSS FRAMES, which Card FT-B's F21 gate
    # forced. Three costs used to land in the ONE frame a response arrives on:
    # the page's JSON decode (unavoidable -- the transport just did it), a
    # per-character normalisation of every row in that page, and, on the last
    # page, a whole-record JSON encode plus the atomic flash swap. Now the sink
    # stores the raw page and returns; `_schedule_parse_step` normalises
    # `SCHEDULE_PARSE_ROWS` rows per frame and the cache write is a frame of its
    # own. The cheap path got cheaper the same way: the cached version is held in
    # RAM, so an unchanged schedule reads no file at all instead of re-validating
    # every stored row to compare one string.

    def _pump_schedule_v2(self):
        """Queue the app-open snapshot RPC once the shared socket is ready.

        THE SOCKET QUESTION IS ASKED ABOVE THE LATCH, not below it, and that
        ordering IS the 2026-08-29 wedge fix -- the same one 40cec1ff applied to
        the score drain, in the lane that matters most to a wearer. This method
        used to read `_schedule_v2_inflight` in the very first condition, so a
        latch that had outlived its errand made the socket question UNREACHABLE:
        `_on_schedule_v2` was the only thing that ever cleared it, and one
        response that never came back cost the Schedule app its entire refresh
        for that app open. There is no cadence behind this request to paper over
        it -- `request_schedule_refresh` latches exactly ONE -- so what the
        wearer got was the offline copy, silently, with nothing on screen or on
        serial to say the badge had stopped asking.
        """

        if not self._schedule_v2_requested or self._schedule_v2_done:
            return None
        backend = self._backend
        connected = (backend is not None
                     and getattr(backend, "state", None) == CONNECTED)
        if self._schedule_v2_inflight:
            verdict = self._release_schedule_latch(
                self._schedule_v2_inflight_at, connected)
            if verdict == "adopt":
                self._schedule_v2_inflight_at = self._ticks_ms()
                return None
            if verdict is None:
                return None
            self._release_schedule_v2(verdict)
        if not connected:
            return None
        import rpc_contract

        params = rpc_contract.schedule_current_v2_params(
            self._schedule_v2_have)
        generation = self._schedule_v2_gen

        # THE SINK CARRIES THE GENERATION IT WAS QUEUED UNDER and never reads the
        # latch, which is what makes releasing the latch early SAFE. Before the
        # release existed only one snapshot could be outstanding, so "the latch"
        # and "the request this response is about" were the same thing by
        # construction; they are not any more. `polltransport._safe_close` leaves
        # a queued errand in its list, so an abandoned request can still answer
        # AFTER the service has re-offered -- and this sink sets `done` and
        # consumes the app's one parked callback, so a stale `(False, None)`
        # would retire the refresh the badge is at that moment succeeding at.
        # One function object per REQUEST, on a path bounded by
        # `request_schedule_refresh` to one per app open; it is not a per-frame
        # allocation.
        def received(ok, data, generation=generation):
            self._on_schedule_v2(generation, ok, data)

        queued = self._queue_errand(
            "rpc",
            {"function": rpc_contract.RPC_SCHEDULE_CURRENT_V2,
             "params": params, "method": "GET"},
            received,
            key="schedule_v2_open",
        )
        if queued:
            self._schedule_v2_inflight = True
            # ARMED FROM A FRESH TICK, not from a frame tick this method is not
            # even given: `poll` runs this after `backend.poll`, in a frame that
            # may have paid a multi-second open. `self._ticks_ms` is the existing
            # seam (`__init__`'s `ticks_ms` argument), not a new clock.
            self._schedule_v2_inflight_at = self._ticks_ms()
            self._emit("schedule_v2_queued")
        return queued

    def _release_schedule_v2(self, reason):
        """Take the app-open snapshot's latch back so the next connect re-asks.

        NOTHING IS CONSUMED HERE, AND THAT IS THE WHOLE CARE IN IT. `done` stays
        False and `_schedule_v2_sink` stays parked, because the bounded thing on
        this lane is the REQUEST ITSELF: `request_schedule_refresh` grants one
        per app open and refuses a second, so a release that let `_on_schedule_v2`
        run would spend the wearer's only refresh on a socket outage. That was
        this lane's version of the score drain's `MAX_ATTEMPTS` -- which is itself
        deleted now, leaving this the only bounded consumable left -- and it is
        the reason the transport-level fix was rejected: see the module note on
        `_release_schedule_latch`.

        RE-ASKING IS FREE. The request is a GET with a `p_have_artifact_id` the
        badge already holds, so a duplicate costs one conditional read that
        writes nothing anywhere; the coalescing key means a queued-but-unsent
        errand is REPLACED rather than duplicated, and the generation bump means
        an abandoned one that answers late is dropped.
        """
        self._schedule_v2_inflight = False
        self._schedule_v2_inflight_at = None
        self._schedule_v2_gen += 1
        # ON THE TRANSITION, NEVER PER FRAME. `_pump_schedule_v2` runs on every
        # rendered frame and the latch is clear the moment this returns, so this
        # line costs one print per RELEASE -- the edge, which is the only place
        # the information is. The steady wedged frame printed nothing at all
        # before this fix and still prints nothing after it.
        self._emit("schedule_v2_latch_released", reason=reason)
        return reason

    def _release_schedule_latch(self, started, connected):
        """Has an in-flight schedule request's latch outlived the errand it names?

        Answers ``None`` to keep waiting, ``"adopt"`` when the caller must arm a
        deadline this latch never got, and otherwise the RELEASE REASON. It
        DECIDES ONLY: the two schedule latches own different state and this
        judgement is the whole of what they share.

        **THE SOCKET IS THE MECHANISM AND THE DEADLINE IS THE BACKSTOP**, exactly
        as `_release_score_latch` argues for the drain. `polltransport` clears a
        latch's response on precisely three paths -- `stop()`, `restart()` and
        `_enter_revoked`'s 403, all via `_drop_errands` -- while
        `_abort_parked_open` (an OWNER RULING #22 placement deny, driven every
        frame) and `request_reconnect` (every radio edge, and the boot's loop
        build) close the socket without notifying anybody, and a REBUILT loop
        takes its whole queue to the collector.

        ⚠ **AND THE FIX FOR THAT DOES NOT BELONG IN THE TRANSPORT, which was
        evaluated first and rejected on the evidence (2026-08-29).** Making those
        two paths call `_drop_errands` would hand `(False, None)` to every sink
        in the system on paths that today deliver nothing, and three of them act
        on a false response in a way the badge cannot take back:

        * `_on_schedule_v2` sets ``_schedule_v2_done`` and drops the app's parked
          sink WHATEVER the answer, and `request_schedule_refresh` refuses to
          re-arm once ``done`` -- so a placement deny during CONNECTING would
          retire the Schedule app's only refresh for the whole boot. It would
          make the very bug this method exists to fix strictly worse.
        * `_on_score_posted` used to run `_count_score_attempt` against
          `scorebox.MAX_ATTEMPTS` of 3, so three radio flaps would DISCARD a
          wearer's score, and 40cec1ff's key guard did not close it: a transport
          drop fires while the latch still names the same slot. ⚠ THAT COUNTER IS
          DELETED (2026-08-29) and this bullet is now the WEAKEST of the three --
          a false `(False, None)` costs one latched `score_refused` line and
          nothing else. The other two still stand on their own.
        * `_on_receipt_posted` counts `receipts_dropped` and the entry is already
          gone from `_receipts`, so the audit row is lost for good -- where today
          `_safe_close` leaves the errand queued and the next open sends it.

        That last point is the general one: those two paths do NOT drop the
        errand queue today, they only clear `_inflight`, so a transport "fix"
        would CANCEL requests that currently succeed on the next open. Per
        consumer is the safe shape, and it is the shape the score drain already
        took.
        """
        if not connected:
            return "offline"
        if started is None:
            # Armed by something that predates the deadline (a probe, or a
            # fixture writing the latch directly). Adopt this tick, so the
            # backstop is armed from here rather than never.
            return "adopt"
        if _ticks_diff(self._ticks_ms(), started) < SCHEDULE_INFLIGHT_MAX_MS:
            return None
        return "deadline"

    def _on_schedule_v2(self, generation, ok, data):
        """Stage one decoded response into the app; never parse or write here.

        ``generation`` IS THE REQUEST'S OWN AND ARRIVES FROM THE CLOSURE, not
        from the latch. A RESPONSE THAT LOST ITS RACE IS DROPPED WHOLE: the
        service has already taken that request back and re-offered it, so acting
        on this one could only spend the app's single parked sink on an answer
        the badge no longer believes -- and on the `(False, None)` case, retire
        the refresh permanently. `_pump_schedule_v2` says why in full.
        """

        self._response_continuation = True
        if generation != self._schedule_v2_gen:
            self._emit("schedule_v2_stale_dropped")
            return
        self._schedule_v2_inflight = False
        self._schedule_v2_inflight_at = None
        self._schedule_v2_done = True
        sink = self._schedule_v2_sink
        self._schedule_v2_sink = None
        self._emit("schedule_v2_received" if ok else "schedule_v2_failed")
        if sink is None:
            return
        try:
            sink(ok, data)
        except Exception as exc:
            # An app callback is an optimisation layered over the offline copy;
            # it may not take down the service or the agenda already on screen.
            self.last_error = _error_text(exc)
            self._emit("schedule_v2_sink_contained", error=self.last_error)

    def _schedule_store(self):
        if self._schedule_box is False:
            return None
        if self._schedule_box is None:
            try:
                import schedule_store

                self._schedule_box = schedule_store
            except Exception as exc:
                self._schedule_box = False
                self.last_error = _error_text(exc)
                self._emit("schedule_unavailable", error=self.last_error)
                return None
        return self._schedule_box

    def _pump_schedule_sync(self, now):
        """RETIRED schema-1 probe path; production ``poll`` never calls this.

        One step of the version check / paged fetch / parse. Never raises.

        The parse step comes FIRST and needs no socket, so a fetch that is still
        in flight does not stall the rows already in hand.
        """
        box = self._schedule_store()
        if box is None:
            return None
        step = self._schedule_parse_step(box)
        if step is not None:
            return step
        if self._schedule_cached is False:
            # THE ONE READ, ONCE PER BOOT, and it is this frame's sub-task rather
            # than the version sink's: `cached_version` decodes the file but
            # normalises no row, and after this the comparison is a RAM string.
            # Ahead of the socket checks on purpose -- it is a filesystem answer
            # and an offline badge should have it before the radio comes back.
            if not self._claim_chore():
                return None
            # THROUGH THE ONE ACCESSOR, not a second call to the store (CX-10).
            # `snapshot()` primes the same field, and the RAM copy the F21 work
            # introduced is the single source for the version on this object --
            # so the read lives in exactly one place and the two paths cannot
            # record a failure differently, which they did.
            self._cached_schedule_version()
            return "cached"
        # THE SOCKET QUESTION IS ASKED ABOVE THE LATCH, for the reason
        # `_pump_schedule_v2` states at length: `_schedule_inflight` used to be
        # read here FIRST, so a latch that had outlived its errand made the
        # socket question unreachable and one lost response stopped this sync --
        # cadence check and paged fetch alike -- for the rest of the boot.
        backend = self._backend
        connected = (backend is not None
                     and getattr(backend, "state", None) == CONNECTED)
        if self._schedule_inflight:
            verdict = self._release_schedule_latch(
                self._schedule_inflight_at, connected)
            if verdict == "adopt":
                self._schedule_inflight_at = self._ticks_ms()
                return None
            if verdict is None:
                return None
            self._release_schedule_sync(verdict)
        if not connected:
            return None
        if self._schedule_pages is not None:
            return self._request_schedule_page()
        if self._schedule_due is None:
            # THE FIRST CHECK IS PHASED, NOT IMMEDIATE (CX-8). `None` used to mean
            # "due now", which served a 15-minute cadence at t=0 on every single
            # boot. Armed at the first moment the check could actually have run --
            # so a badge that takes five minutes to associate phases from THERE
            # rather than owing a request the whole time it was offline.
            delay = self._schedule_first_delay_ms()
            self._schedule_due = _ticks_add(now, delay)
            self._emit("schedule_phased", due_ms=delay,
                       cached=self._schedule_cached is not None)
            return None
        if _ticks_diff(now, self._schedule_due) < 0:
            return None
        # RECORD THE ATTEMPT BEFORE THE RPC, so a reset during a failing errand
        # cannot recreate the herd the phase just spread.
        self._schedule_due = _ticks_add(now, SCHEDULE_REFRESH_MS)
        import rpc_contract

        generation = self._schedule_gen

        def answered(ok, data, generation=generation):
            self._on_schedule_version(generation, ok, data)

        self._schedule_inflight = True
        self._schedule_inflight_at = self._ticks_ms()
        queued = self._queue_errand(
            "rpc",
            {"function": rpc_contract.RPC_SCHEDULE_VERSION,
             "params": {}, "method": "GET"},
            answered,
            key="schedule_version",
        )
        if not queued:
            self._schedule_inflight = False
            self._schedule_inflight_at = None
        return queued

    def _release_schedule_sync(self, reason):
        """Take the schema-1 sync's latch back so the next frame can ask again.

        NO ATTEMPT AND NO CADENCE IS CONSUMED. `_schedule_due` was advanced by
        `SCHEDULE_REFRESH_MS` before the request went out -- deliberately, so a
        reset during a failing errand cannot recreate the herd the CX-8 phase
        just spread -- and a release does NOT pull it forward for the same
        reason. What that costs is a version check landing at its next 15-minute
        tick rather than immediately; what it buys is that a released badge
        cannot turn a flapping AP into a fleet-wide burst. A paged FETCH does
        resume at once, because `_schedule_pages` is checked above the cadence
        and `_schedule_offset` still names the page that was never answered.

        NOTHING IS DISCARDED EITHER: the pages already parsed stay in
        `_schedule_pages`, the version is not stored until the last page is
        written, and `_abandon_schedule_fetch` is reached only by a response that
        genuinely failed. The bump is what keeps that true -- see
        `_on_schedule_page`.
        """
        self._schedule_inflight = False
        self._schedule_inflight_at = None
        self._schedule_gen += 1
        self._emit("schedule_latch_released", reason=reason)
        return reason

    def _schedule_first_delay_ms(self):
        """How long this boot waits before its FIRST schedule-version check.

        Two answers, because a badge with no schedule and a badge holding the
        current one want opposite things:

        * **No schedule at all** (`_schedule_cached is None`): a deterministic
          per-badge stagger across `SCHEDULE_COLD_STAGGER_MS`, so a wearer who
          opens the schedule view has something inside a minute and 800 badges
          still do not ask in the same second.
        * **A cache** (the common case, and the one the cheap version check exists
          for): full jitter inside the normal interval above a one-minute floor.
          Nothing is waiting on it -- the badge already has a schedule to draw.
        """
        if self._schedule_cached is None:
            return self._badge_stagger_ms(SCHEDULE_COLD_STAGGER_MS)
        return self._jittered_delay_ms(SCHEDULE_FIRST_MIN_MS,
                                       SCHEDULE_REFRESH_MS)

    def _on_schedule_version(self, generation, ok, data):
        """The sink, and it touches NO file: the cached version is in RAM.

        ``generation`` IS THE REQUEST'S OWN. A check the sync has already taken
        back is dropped whole: it would otherwise be free to start a fetch on the
        strength of a version the badge asked about two outages ago, wiping a
        fetch already in progress.
        """
        self._response_continuation = True
        if generation != self._schedule_gen:
            self._emit("schedule_stale_dropped")
            return
        self._schedule_inflight = False
        self._schedule_inflight_at = None
        box = self._schedule_store()
        if box is None or not ok:
            return
        version = box.version_from(data)
        if version is None:
            self._emit("schedule_version_unreadable")
            return
        if self._schedule_cached == version:
            # THE CHEAP PATH: one small round trip and nothing else at all. It
            # used to call `load()` here, which re-read and re-validated every
            # stored row to compare one string -- inside the response frame.
            self._emit("schedule_current")
            return
        self._emit("schedule_changed")
        self._schedule_version = version
        self._schedule_pages = []
        self._schedule_offset = 0

    def _request_schedule_page(self):
        box = self._schedule_store()
        if box is None:
            self._abandon_schedule_fetch()
            return None
        import rpc_contract

        generation = self._schedule_gen

        def paged(ok, data, generation=generation):
            self._on_schedule_page(generation, ok, data)

        self._schedule_inflight = True
        self._schedule_inflight_at = self._ticks_ms()
        queued = self._queue_errand(
            "table",
            {"table": rpc_contract.TABLE_SCHEDULE_EVENTS, "method": "GET",
             "query": box.page_query(self._schedule_offset)},
            paged,
        )
        if not queued:
            self._schedule_inflight = False
            self._schedule_inflight_at = None
        return queued

    def _on_schedule_page(self, generation, ok, data):
        """The sink, and it CAPTURES the page rather than normalising it.

        Everything expensive about a page -- the per-character sanitize, the
        `_raw` decision, the bound on every field -- happens in
        `_schedule_parse_step`, `SCHEDULE_PARSE_ROWS` rows at a time.

        ``generation`` IS THE REQUEST'S OWN, AND THIS IS THE SINK THE RELEASE
        WOULD HAVE BROKEN. Once a latch can be taken back, the same offset can be
        re-requested while the abandoned read is still capable of answering --
        and the two failure modes are both silent corruption of what the wearer
        reads. An abandoned page that answers OK would stage its rows a SECOND
        time, duplicating a whole page of the agenda; an abandoned page that
        answers FAILED would call `_abandon_schedule_fetch` on the fetch that
        replaced it, throwing away every page already parsed. So a response that
        does not name the request in hand is dropped before either can happen.
        """
        self._response_continuation = True
        if generation != self._schedule_gen:
            self._emit("schedule_stale_dropped")
            return
        self._schedule_inflight = False
        self._schedule_inflight_at = None
        box = self._schedule_store()
        if box is None or self._schedule_pages is None:
            # No fetch is in progress, so this is a late or duplicated sink call.
            # Answering it with an AttributeError inside the transport's own
            # `_finish_errand` would be a worse outcome than ignoring it.
            self._abandon_schedule_fetch()
            return
        if not ok:
            # ABANDON THE WHOLE FETCH rather than write a partial schedule. The
            # version is not stored, so the next check disagrees and starts over.
            self._abandon_schedule_fetch()
            self._emit("schedule_fetch_failed")
            return
        # THE DECODED LENGTH DECIDES, NOT THE ACCEPTED COUNT. `row` DROPS a row
        # with no window or an empty title, so comparing accepted-vs-page-size
        # made one unrenderable event in a full page look like a short page --
        # declaring the fetch complete and silently truncating the whole schedule
        # from that point on. Recorded here because the count is taken here and
        # spent frames later.
        self._schedule_received = len(data) if isinstance(
            data, (list, tuple)) else 0
        self._schedule_raw = data if self._schedule_received else ()
        self._schedule_raw_at = 0

    def _abandon_schedule_fetch(self):
        """Forget a fetch in every one of its four pieces of state."""
        self._schedule_pages = None
        self._schedule_offset = 0
        self._schedule_raw = None
        self._schedule_raw_at = 0
        self._schedule_received = 0
        self._schedule_commit = False

    def _schedule_parse_step(self, box):
        """Normalise one batch, or write the cache.  NEVER BOTH, never neither.

        Returns ``None`` when there is nothing to do, so the caller knows the
        frame's budget is still unspent.
        """
        raw = self._schedule_raw
        if raw is not None:
            if not self._claim_chore():
                return "waiting"
            rows = self._schedule_pages
            at = self._schedule_raw_at
            end = at + SCHEDULE_PARSE_ROWS
            if end > len(raw):
                end = len(raw)
            while at < end:
                if len(rows) >= box.MAX_ROWS:
                    at = len(raw)
                    break
                entry = box.row(raw[at])
                if entry is not None:
                    rows.append(entry)
                at += 1
            self._schedule_raw_at = at
            if at < len(raw):
                return "parsing"
            received = self._schedule_received
            self._schedule_raw = None
            self._schedule_raw_at = 0
            self._schedule_received = 0
            if received < box.PAGE_ROWS or len(rows) >= box.MAX_ROWS:
                self._schedule_commit = True
            else:
                self._schedule_offset += box.PAGE_ROWS
            return "parsed"
        if not self._schedule_commit:
            return None
        if not self._claim_chore():
            return "waiting"
        self._schedule_commit = False
        collected = self._schedule_pages[:box.MAX_ROWS]
        version = self._schedule_version
        self._schedule_pages = None
        self._schedule_offset = 0
        try:
            # `synced_at` IS TAKEN HERE AND NOWHERE ELSE, because here is where
            # the sync actually SUCCEEDS -- the last page is parsed and the file
            # is about to be swapped. `_epoch()` is the CORRECTED clock: it is
            # `clock_boot.evaluate_ntp`-gated and answers None on a badge whose
            # wall clock is not trustworthy, and `schedule_store` then writes no
            # field at all rather than stamping a 2021 date on this fetch. The
            # schedule app renders freshness from it and must read absence as
            # "unknown", never as "old" (that module's contract rule 6).
            box.save(version, collected, self._schedule_cache_path,
                     synced_at=self._epoch())
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("schedule_write_failed", error=self.last_error)
            return "write_failed"
        # THE RAM COPY MOVES WITH THE FILE, so no later check re-reads it.
        self._schedule_cached = version
        self._emit("schedule_synced")
        return "synced"

    def _queue_errand(self, kind, payload, sink=None, key=None):
        """Hand one side request to the backend.  Duck-typed and never raises.

        Duck-typed for the same reason ``set_policy_sink`` is: a backend that
        predates the errand channel simply has none, and the caller gets False.
        """
        backend = self._backend
        sender = getattr(backend, "queue_errand", None)
        if not callable(sender):
            return False
        try:
            return bool(sender(kind, payload, sink, key))
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("errand_contained", error=self.last_error)
            return False

    def _pump_effect(self, now):
        # ONLY BOUNDED STEADY SLOTS LIVE HERE. None of these calls may claim the
        # frame's expensive chore or a ledger/cache write would freeze a
        # 300-second show on every retry frame.
        program = self._lights
        stepped_program = self._lights_stepped_frame
        self._lights_stepped_frame = None
        if program is not None and program is not stepped_program:
            # ONE PROGRAM, ONE CALL, NO ALLOCATION. `step` answers None on a
            # frame whose level has not changed, which is the same duplicate
            # suppression every app applies to badge.caselights.
            level = program.step(_ticks_diff(now, self._lights_started))
            if level is not None:
                self._caselights(level)
            if program.done:
                self._lights = None
        # THE FLEET EFFECT, IN ITS OWN SLOT AND NOT SHARING THE ONE ABOVE. The
        # library's own note says why: a `Program` returns a level because it
        # drives one channel, an `EffectPlayer` drives two and answers a bool, so
        # a shared slot would put a type switch in a frame pump that runs on every
        # rendered frame of every app.
        player = self._effect
        stepped_player = self._effect_stepped_frame
        self._effect_stepped_frame = None
        if player is not None and player is not stepped_player:
            # `step` is False on every frame where neither channel moved, which is
            # most of them, and True/False are singletons -- so a quiet frame of a
            # 300-second show allocates nothing.
            if player.step(_ticks_diff(now, self._effect_started)):
                self._write_effect_levels(player)
            if player.done:
                self._effect = None
                queued = self._effect_queue
                if queued:
                    # CONTINUE FROM RAM, NOT THE NETWORK. This is the property
                    # W9 buys: after the one array arrives, every later boundary
                    # is local and a dropped socket cannot truncate the show.
                    following = queued.pop(0)
                    self._effect_queue = queued or None
                    self._start_effect_player(following, now)
                else:
                    self._effect_queue = None

    def _emit(self, event, **fields):
        if self._event_sink is None:
            return
        record = {"service": "badgelink_network", "event": event,
                  "state": self.state}
        record.update(fields)
        self._event_sink(record)

    def _on_policy(self, steering):
        """The push half of the fleet settings, on its way to the doorbell.

        Held even when there is no push object yet, so a setting that arrived
        before the first WS session still applies to it (`_service_push` replays
        `self._policy` when it builds one). Contained: a malformed policy is a
        thing to ignore, never a thing to crash a poll cycle over.

        ITS PRODUCER CHANGED, ITS CONSUMER DID NOT (rebuild, 2026-08-29). This was
        fed by the transport-policy RPC's own response; it is fed by
        `_apply_settings` now, off the five-minute `fleet_settings` GET. The dict
        shape is unchanged, `PushPolicy.set_remote` reads the same
        `push_enabled` key with the same fail-open rule, and the extra keys the
        settings row carries are simply not read here.

        NO DUE TIME IS TOUCHED HERE, which used to need a paragraph of CX-8
        history to explain and now needs none: there is one cadence, it lives in
        `_pump_fleet_settings`, and it advances where the request is issued.
        """
        self._policy = steering if isinstance(steering, dict) else None
        if self._push is None:
            return None
        try:
            return self._push.apply_steering(self._policy)
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("policy_contained", error=self.last_error)
            return None

    def _on_backend_event(self, record):
        if not isinstance(record, dict):
            self._emit("backend_event")
            return
        fields = {}
        # THE LIST IS `_FORWARDED_FIELDS` AND ITS HISTORY IS WRITTEN THERE, beside
        # the printer's whitelist it has to agree with. It was an inline tuple
        # expression until 2026-08-24 -- which allocated a fresh concatenation of
        # two tuples on EVERY backend event, in a frame path, for a list that
        # never changes -- and having it in one place is also what lets a test
        # assert the two whitelists agree.
        for key in _FORWARDED_FIELDS:
            if key in record:
                fields[key] = record[key]
        self._emit(record.get("event", "backend_event"), **fields)


class DeviceBackend:
    """Real CYW43 + verified-TLS PollLoop backend, created only when ON."""

    #: THE §2 BOOT ASSERT'S VERDICT, or ``None``. A CLASS DEFAULT so an instance
    #: built by a probe or a fixture through ``__new__`` -- which several do, to
    #: exercise `poll` without a radio -- reads "no fault" instead of raising
    #: AttributeError on the launch path, where a raise is a `machine.reset()`.
    #: `__init__` replaces it with the real answer. See :func:`provisioning_fault`.
    provisioning_fault = None

    #: THE NTP HOST'S ORIGINAL NAME, remembered before `_bound_ntp_host` overwrites
    #: `ntptime.host` with an address. Without this the second resync of a boot would
    #: read back the IP the first one wrote, treat it as the name, and keep using a
    #: STALE address for the rest of the boot -- the same trap `NB_CONNECT_ENABLED`
    #: carries a warning about. Class default so a probe built through `__new__` reads it.
    _ntp_host = None

    # NB-0-only association ownership stays lazy so the OFF artifact
    # pays neither instance heap nor a per-frame restoration call. NetworkService
    # materialises these immutable defaults once, before the first radio start,
    # only in a cold ON build.
    _held_connect_enabled = False
    _poll_addr_info = None
    _push_address_ready = True
    #: NB-0 arbiter counters, ON-only. A monotonic count of establishment WORK
    #: a frame could feel: loop preparation (the NTP/DNS/PM build frame) plus
    #: the RETIRED loops' `open_step` totals, added to the LIVE loop's below.
    #: See :meth:`establishment_steps`. Class default keeps OFF instance-inert.
    _establishment_steps = 0
    #: The PER-FRAME arbiter gate (spec 5.3(b)), set by NetworkService before
    #: each ON ``poll`` and consumed inside it. ``False`` DEFERS preparation and
    #: any open continuation one frame; it never aborts. Distinct from the loop's
    #: persistent :meth:`polltransport.PollLoop.set_establishment_allowed`.
    _frame_establishment_allowed = True
    #: The PERSISTENT placement gate (OWNER RULING #22), set by NetworkService
    #: from `_placement_allows_establishment` before each ON ``poll`` and NOT
    #: reset per frame. ``False`` refuses a loop BUILD (its NTP/DNS prep is
    #: establishment work) and drives the loop's own persistent
    #: :meth:`polltransport.PollLoop.set_establishment_allowed`, whose deny
    #: ABORTS an in-flight open as a non-failure and blocks a new one. Class
    #: default ``True`` keeps OFF and un-gated fixtures at the always-connect
    #: launcher behaviour.
    _placement_establishment_allowed = True

    #: Has a sync actually LANDED this boot? Gates `clock_boot.resync`'s shift
    #: bound. False until proven otherwise, because a cold boot's clock can only
    #: have come from the battery-backed PCF -- plausible, and verified by
    #: nothing. See `clock_boot.resync`'s `clock_verified`.
    #:
    #: A CLASS attribute rather than an `__init__` one, deliberately and for the
    #: same reason `_establishment_steps` is: `__init__` imports `network`,
    #: `ntptime` and `secrets`, so every host test builds this object through
    #: `__new__` and an `__init__` default would be invisible to all of them.
    _clock_verified = False

    #: `clock_boot.resync`'s LAST WORD, or ``None`` before anything has tried.
    #:
    #: LATCHED BECAUSE IT HAD NOWHERE ELSE TO GO. `_build_loop` already emits it
    #: as `clock_resync_skipped(reason=)` -- onto a serial port that, at the
    #: venue, has nothing attached to it: the badges are on battery and handed
    #: out, and the panel is the only channel. This is one string assignment on a
    #: per-connect path (never per frame), which is the whole cost of making
    #: `dns_unreachable` distinguishable from `ntp_rejected: before_build_floor`
    #: on the screen. `NetworkService.clock_diagnostics` is the reader.
    #:
    #: A CLASS attribute for `_clock_verified`'s reason, and NOT reset between
    #: builds: it is the last outcome of the boot, and a field cleared on entry
    #: to `_build_loop` would read `None` for exactly as long as the frame that
    #: is failing.
    _clock_reason = None

    def __init__(self, command_sink, event_sink, rtc_device=None):
        import fetch
        import network
        import ntptime
        import secrets
        import socket
        import ssl

        import bounded_dns
        import clock_boot
        import credentials
        import device_link
        import polltransport
        import postgrest
        import radio_policy
        import resilient_wifi
        import store
        import verified_tls

        self._fetch = fetch
        self._network = network
        self._ntptime = ntptime
        self._secrets = secrets
        self._socket = socket
        self._ssl = ssl
        self._clock_boot = clock_boot
        self._credentials_module = credentials
        self._device_link = device_link
        self._polltransport = polltransport
        self._postgrest = postgrest
        self._radio_policy = radio_policy
        self._wifi_module = resilient_wifi
        self._store = store
        self._verified_tls = verified_tls
        self._command_sink = command_sink
        self._event_sink = event_sink
        self._policy_sink = None
        #: The server's suggested cadence, held until a loop exists to take it.
        self._suggested_cadence_ms = None
        #: CX-3's shared address cache. Owned here because this is the object
        #: that owns the radio and therefore the WLAN session the cache is scoped
        #: to; reached by the doorbell through `poll_loop().link.addresses`.
        #: THE RADIO HANDLE, MOVED ABOVE THE ADDRESS CACHE (2026-08-27) because
        #: the cache's resolver now needs it: `bounded_dns` reads the DHCP-provided
        #: server out of `wlan.ifconfig()` on every lookup, so the WLAN object has
        #: to exist before the resolver that asks it.
        self._wlan = network.WLAN(network.STA_IF)
        #: **THE BOUNDED RESOLVER, AND IT REPLACES `socket.getaddrinfo` OUTRIGHT
        #: RATHER THAN FALLING BACK TO IT.** `getaddrinfo` on this port blocks
        #: 13.1-14.0 s with no route and CANNOT be bounded -- no socket timeout
        #: reaches it and no Python wrapper wraps the C call -- so it is not a
        #: safety net, it is the defect. `bounded_dns` owns its own UDP socket and
        #: answers or gives up inside 1,000 ms.
        #:
        #: WHAT HAPPENS WITH NO RESOLVER AT ALL is deliberately a FAILURE and the
        #: module left that call to this lane in as many words ("falling back to
        #: `socket.getaddrinfo` would reinstate the 13-14 s freeze, and that trade
        #: belongs to the lane that owns the frame"). Taken: a badge whose DHCP
        #: offered no option 6 and whose gateway is unusable is not a badge that
        #: was about to reach Supabase, and the honest outcome is a bounded
        #: `OSError` into the transport's ordinary unreachable path -- backoff, a
        #: readable serial line, a working nametag -- rather than an eight-second
        #: dead badge in the wearer's hand. A fallback here would mean the freeze
        #: survives in exactly the conditions the module was built for.
        self._resolver = bounded_dns.BoundedResolver(self._wlan)
        self._addresses = SessionAddresses(
            self._resolver.getaddrinfo,
            sock_stream=getattr(socket, "SOCK_STREAM", 0),
            event_sink=self._emit_backend_record,
        )
        self._rtc = rtc_device
        self._wifi = resilient_wifi.ResilientWiFi(wlan=self._wlan)
        self._original_country = network.country()
        self._original_pm = None
        self._creds = credentials.load(secrets)
        #: THE §2 BOOT ASSERT, run HERE because this is the one place that holds
        #: the credential and can reach the hardware id in the same breath. See
        #: :func:`provisioning_fault`.
        subject = getattr(self._creds, "badge_id", None)
        self.provisioning_fault = provisioning_fault()
        if self.provisioning_fault is not None:
            self._emit_backend("provisioning_error",
                               reason=self.provisioning_fault)
        # WHICH CREDENTIAL, ONCE PER BOOT, and it is not decoration. The §0.8
        # rollout deliberately runs NEW firmware on OLD per-badge tokens as its
        # safety step, so during provisioning the fleet is a mix -- and until this
        # line existed nothing on the wire distinguished a badge that had been
        # re-provisioned from one that had not. It is also the line that would have
        # made the tautology above obvious on the first boot: `tier=per_badge`
        # beside `reason=shared_sub_is_this_badge` is a visible contradiction.
        # A BOUNDED WORD from a closed set, never the subject itself: the subject
        # is not secret but it is not glyph-safe either, and no server-shaped
        # string may reach a line a screen might draw.
        self._emit_backend("credential_tier",
                           reason=credential_tier(subject) or "unknown")
        self._loop = None
        self._active = False
        self._was_online = False
        self._retry_at = None
        self._failures = 0
        self.last_error = None

    @property
    def state(self):
        if self._loop is not None and self._loop.state == self._polltransport.REVOKED:
            return REVOKED
        wifi_state = self._wifi.state
        if wifi_state == self._wifi_module.ONLINE:
            return self._loop.state if self._loop is not None else CONNECTING
        if wifi_state == self._wifi_module.CONNECTING:
            return CONNECTING
        if wifi_state == self._wifi_module.BACKOFF or self._retry_at is not None:
            return BACKOFF
        return DISCONNECTED

    def start(self, now):
        ssid = getattr(self._secrets, "WIFI_SSID", "")
        password = getattr(self._secrets, "WIFI_PASSWORD", "")
        region = getattr(self._secrets, "REGION", "")
        self._wifi_module.validate_credentials(ssid, password)
        if not isinstance(region, str) or len(region) != 2:
            raise ValueError("REGION must be a two-letter regulatory domain")
        self._network.country(region.upper())
        self._wifi.start(ssid, password, now=now)

    def set_policy_sink(self, sink):
        """Where the server's steering fields go. Must be set before the loop.

        The service calls this right after construction, so the ``PollLoop``
        built on the first successful open already carries it.
        """
        self._policy_sink = sink
        if self._loop is not None:
            self._loop._policy_sink = sink
        return sink

    def set_suggested_cadence(self, cadence_ms):
        """The server's suggested exchange cadence, on its way to the loop.

        THE ONE PIECE OF STEERING THAT IS STILL THE LOOP'S. Everything else the
        fleet settings carry is applied by `NetworkService`, but the interval
        between exchanges is decided where the exchanges are, and the loop clamps
        whatever arrives into the band it is willing to run at -- so nothing the
        server can send makes a badge ask faster than its own floor.

        Same shape as `set_policy_sink` and for the same reason: the service does
        not reach into the loop, and a backend with no loop yet REMEMBERS the
        value so the loop built on the first successful association carries it.

        ⚠ THIS REPLACED `set_policy_due`/`policy_due` (rebuild, 2026-08-29). Those
        two existed only because the steering READ was a loop request kind with a
        due time on both objects; the settings read is an errand on one cadence in
        one object now, so there is nothing left to mirror.
        """
        self._suggested_cadence_ms = cadence_ms
        if self._loop is not None:
            self._loop.set_suggested_cadence(cadence_ms)
        return cadence_ms

    def push_address_ready(self):
        """Whether held WSS can connect without entering name resolution."""

        if not bool(self._push_address_ready):
            return False
        # The boolean names cache readiness in this association: initial build
        # sets it after current-session resolution; a roam sets it only after
        # the retained poll address completes an authenticated reopen. The cache
        # is still the resource WSS actually consumes, so check both. A stale bit
        # plus `connect_host=None` would make the vendor enter untimeoutable
        # getaddrinfo in a rendered frame. WSS verifies the hostname with its own
        # TLS handshake; this gate is about DNS boundedness, not borrowed trust.
        return self._addresses.has_cached_address(self._creds.host, 443)

    def enable_held_connect(self):
        """Materialise NB-0's association owner before any socket can start."""

        self._held_connect_enabled = True
        self._poll_addr_info = None
        self._push_address_ready = False
        return True

    def poll_loop(self):
        """The live ``PollLoop``, or ``None`` before the first successful open.

        The doorbell seam: layer 3 needs exactly this object and nothing else
        from the device backend, which is why it is one accessor rather than a
        reference handed out at construction.
        """
        return self._loop

    def clock_snapshot(self):
        """What this boot's clock syncs did: ``{"synced", "reason"}``.

        THE PLAUSIBILITY HALF IS NOT HERE ON PURPOSE. This object exists only
        once the radio has been asked for, and a badge whose loop never built --
        the brick :data:`CLOCK_DIAGNOSTIC_KEYS` describes -- may have no backend
        at all. So the answer that must never depend on one lives in
        :meth:`NetworkService.clock_diagnostics`, and this contributes only the
        two facts that are genuinely this object's: whether a sync LANDED (the
        latch `clock_boot.resync`'s shift bound is already armed by) and what
        `resync` last said. Two field reads; nothing is derived or counted.
        """
        return {"synced": self._clock_verified, "reason": self._clock_reason}

    def set_active(self, active):
        self._active = bool(active)
        if self._loop is not None:
            self._loop.set_active(self._active)

    def queue_ack(self, ack):
        if self._loop is not None:
            return self._loop.queue_ack(ack)
        return 0

    def queue_errand(self, kind, payload, sink=None, key=None):
        """Card FT-B's side channel, forwarded to the loop that owns the socket.

        The same shape as ``queue_ack``: the service does not reach into the
        loop, and a backend with no socket yet answers False rather than raising.
        """
        if self._loop is not None:
            return self._loop.queue_errand(kind, payload, sink, key)
        return False

    def exchanges(self):
        """How many requests this session has finished. See ``PollLoop``."""
        loop = self._loop
        return loop.exchanges if loop is not None else 0

    def force_active_cadence(self, on=True):
        """Forward the poll-cost TEST KNOB to the loop that owns the socket.

        The same shape as ``queue_errand``: the service does not reach into the
        loop, and a backend with no socket yet answers ``None`` rather than
        pretending it set something. THE FLAG DIES WITH THIS LOOP -- a networking
        OFF/ON toggle builds a new one, which is one more thing that cannot leave
        a knob on in the field.
        """
        loop = self._loop
        if loop is None:
            return None
        return loop.force_active_cadence(on)

    def wifi_online(self):
        """Did the radio report ONLINE on the last polled frame? (Lane H.)

        THE ONE ACCESSOR THAT LETS THE RADIO'S GATE COVER THE DOORBELL. Every
        socket this class opens is already behind that gate -- `poll` returns
        above `_build_loop` and above `_loop.poll` unless `ResilientWiFi.tick`
        said ONLINE -- but `NetworkService._service_push` runs OUTSIDE this
        object, on every frame, because a doorbell fault may never be the reason
        a poll cycle is treated as failed. So the service has to be able to ASK,
        and `_was_online` is the answer it needs: the same flag the `wifi_lost` /
        `wifi_online` edges are emitted from, so the two can never disagree.

        Read rather than re-derived on purpose. Calling `self._wifi.tick(now)`
        again here would be a SECOND native `wlan.isconnected()` in the same
        frame (CX-11 is the claim that one per frame is already unbounded), and
        it could answer differently from the value the frame's own edge decision
        was made on.

        Duck-typed at the caller, so a backend that predates this is assumed
        online and keeps the pre-Lane-H behaviour exactly.
        """
        return self._was_online

    def wifi_snapshot(self):
        """`ResilientWiFi`'s own record, forwarded unchanged.

        Five field reads into a fresh dict -- `{state, reason, attempts,
        failures, connected_ms}` -- which is what makes it affordable on the
        draw path the Network screen's first two pages run on. NOTHING IS
        DERIVED OR RE-READ HERE, and specifically nothing calls
        `ResilientWiFi.tick`: that would be a SECOND native `wlan.isconnected()`
        in a frame that has already paid one, and it could answer differently
        from the value the frame's own edge decision was made on. Same rule as
        :meth:`wifi_online`, for the same reason.

        `connected_ms` STAYS A STAMP. Converting it to a held duration needs the
        frame's clock, and this object does not own one;
        `NetworkService.wifi_diagnostics` does it.

        **THE SSID IS NOT IN THIS RECORD AND HAS NO KEY.** `ResilientWiFi` holds
        it, and the owner's instruction names the network name a secret -- ~200
        screens anyone can wake in a public hall is a product decision, not an
        engineering one. Omitting the key outright is what makes it structurally
        unable to reach a view, rather than a rule a future caller could forget.
        """

        return self._wifi.snapshot()

    def wifi_region(self):
        """The regulatory domain this radio was started in, or ``None``.

        NOT A SECRET AND NOT CREDENTIAL MATERIAL: it is the two-letter domain
        :meth:`start` already validates and hands to `network.country()`. It is
        worth a band because a badge provisioned `GB` and flown to San Francisco
        cannot see the venue's channels at all, and nothing else on this badge
        can say so -- the radio simply never associates and every other line
        reads exactly like an out-of-range access point.

        READ OFF `secrets` RATHER THAN OFF `network.country()`, which is a
        native call and this runs on a draw path. The validated constant is also
        the more useful answer: it is what was ASKED for, so a mismatch with the
        hall is visible without a second reading to compare against.
        """

        region = getattr(self._secrets, "REGION", "")
        return region.upper() if isinstance(region, str) and len(region) == 2 else None

    def resolver_snapshot(self):
        """The bounded resolver's counters PLUS the address it would ask.

        `BoundedResolver.server()` reads `wlan.ifconfig()`, which is a NATIVE
        CALL, and that is precisely why this is its own accessor rather than
        three more keys on :meth:`wifi_snapshot`: only Network page 3 asks, so
        the cost is paid by the page that needs it and by no other frame.

        `resolver_address` already contains its own failure -- a radio that is
        down or a port whose `ifconfig` is short answers ``None`` -- so the grey
        zone this exists to NAME arrives as `server: None` rather than as a
        raise. That state is the whole reason `bounded_dns` replaced
        `socket.getaddrinfo`: DHCP offered no option 6, the gateway is unusable,
        and the badge that used to sit there for 13.1-14.0 s per lookup with
        nothing on any screen now has one line saying so.

        The address is written onto the resolver's OWN fresh record, never into
        a cached one, so a reader can never catch a half-written dict.
        """

        record = self._resolver.snapshot()
        record["server"] = self._resolver.server()
        return record

    def link_counts(self):
        """Six field reads off the live ``PollLoop``, or ``None``.

        **DELIBERATELY NOT `PollLoop.snapshot()`.** That builds ~35 keys, and
        this is read once per rendered frame for as long as an operator holds
        Network page 3 or 4 up -- which is exactly the badge somebody is staring
        at because it is retrying. The rule the whole diagnostic design turns
        on is: on a draw path, read the individual attributes and never a
        snapshot.

        ``None`` MEANS THERE IS NO LOOP, which is a state and not an error: a
        badge that never associated, or one whose clock is implausible so
        `_build_loop` raises before it finishes. The panel draws that in words.
        It may not draw zeroes -- a zeroed counter is a measurement, and this is
        the absence of one.

        `open_phases` is forwarded BY REFERENCE and never copied. `DeviceLink`
        REPLACES that record once per open rather than mutating it in place
        (`device_link.py`'s `_publish_phases`), so a reader between opens always
        sees one whole consistent record and a copy here would only be heap.
        """

        loop = self._loop
        if loop is None:
            return None
        link = getattr(loop, "link", None)
        return {
            "state": loop.state,
            "opens": loop.opens,
            "open_failures": loop.open_failures,
            # ⚠ `open_attempts` IS NOT `opens + open_failures` AND THE GAP IS
            # ITSELF A FINDING: the two halves move only inside `_attempt_open`'s
            # three classified branches, so an open that raised an unclassified
            # exception moved neither. Counted on ENTRY, so the answer does not
            # depend on an exception taxonomy.
            "open_attempts": loop.open_attempts,
            "last_error": loop.last_error,
            "revoked_reason": loop.revoked_reason,
            "phases": getattr(link, "open_phases", None),
        }

    def connect_attempts(self):
        """Opens this backend's loop has ATTEMPTED, successful or not (Lane H).

        The number `NetworkService` samples either side of `backend.poll` to
        learn whether THIS frame already paid a transport connect. Attempts, not
        successes: a blackholed open spends the whole `OPEN_BUDGET_MS` and ends
        in BACKOFF, and that frame is exactly the one that must not also pay a
        735 ms WebSocket handshake.

        `0` before a loop exists rather than `None`, so the frame that BUILDS one
        and opens inside it reads as a change (0 -> 1). `_build_loop`'s own
        blocking legs -- two NTP round trips with their own unbounded lookups and
        the project's `getaddrinfo` -- are inside that same frame, which is the
        1,209 ms pile-up, so this covers it without a second seam.

        ⚠ **THIS READ `loop.opens + loop.open_failures` UNTIL LANE I, AND THAT
        SUM COULD FAIL TO MOVE FOR AN OPEN THAT HAPPENED.** Both halves are
        incremented only inside `_attempt_open`'s three CLASSIFIED branches
        (`LinkRevoked`, `LinkError`, success), so an open that raised anything
        else -- a raw `PostgrestError` out of `parse_poll_rows`, which runs one
        line outside `device_link`'s adjudication `try` and is therefore not a
        `LinkError` -- moved neither, this method answered "no connect happened",
        and the doorbell established a ~2.3 s WSS session in the frame that had
        just paid a whole open. `PollLoop.open_attempts` is counted on ENTRY, so
        the answer no longer depends on an exception taxonomy. The old sum stays
        on the snapshot beside it, and a gap between them is a source bug worth
        reading.
        """
        loop = self._loop
        if loop is None:
            return 0
        return loop.open_attempts

    def establishment_steps(self):
        """The ON per-frame ESTABLISHMENT-STEP token (NB-0 arbiter).

        `connect_attempts` moves once, at attempt admission -- so once P1-a
        parks the poll open across frames, every LATER continuation frame is
        invisible to it and the doorbell can establish a ~2.3 s WSS join in the
        same frame a parked poll open is advancing. This counter moves on loop
        PREPARATION (`_build_loop`, the NTP/DNS/PM frame) and on EVERY
        `PollLoop.open_step` continuation (mirrored by the loop's own
        `open_steps`), so `NetworkService` -- which samples it either side of
        `backend.poll` -- sees a parked open on every frame it advances. An
        ordinary CONNECTED exchange never enters `_continue_parked_open`, so it
        does not move this and does not make the frame a connect frame, which is
        why the ~11 ms exchange still shares a frame with a doorbell PUMP.

        Monotonic across loop rebuilds: a rebuilt loop restarts `open_steps` at
        0, so a retiring loop's steps are banked into `_establishment_steps`
        before it is dropped (see :meth:`stop`).
        """
        loop = self._loop
        live = loop.open_steps if loop is not None else 0
        return self._establishment_steps + live

    def set_frame_establishment_allowed(self, allowed):
        """The per-frame arbiter gate, set before each ON ``poll`` (spec 5.3(b)).

        DEFERS this frame's loop preparation and open continuation when a
        correctness chore already spent the frame; Wi-Fi still ticks and radio
        abort edges still run. It never aborts an in-flight open -- that is the
        loop's persistent
        :meth:`polltransport.PollLoop.set_establishment_allowed`. Consumed (and
        reset to allowed) inside ``poll``, so a frame nobody gates runs normally.
        """
        self._frame_establishment_allowed = bool(allowed)
        return self._frame_establishment_allowed

    def set_placement_establishment_allowed(self, allowed):
        """The PERSISTENT placement gate, set before each ON ``poll`` (#22).

        Unlike the per-frame gate this is NOT reset inside ``poll``: placement
        is a lasting property of where the badge is (launcher vs a non-opted-in
        app), so it holds across frames until NetworkService changes it. It
        refuses a loop BUILD while denied -- the build's NTP/DNS/PM frame is
        establishment work that must not run in an app -- and it is forwarded to
        the live loop's own persistent gate, whose deny aborts an in-flight open
        as a non-failure and blocks a new one. A warm CONNECTED session is
        untouched by either (warm travel). Inert in OFF: nothing calls it.
        """
        self._placement_establishment_allowed = bool(allowed)
        return self._placement_establishment_allowed

    def revoked_reprobe_due(self, now):
        """Has the loop's slow post-403 re-probe come due? (§8.1)

        A PASS-THROUGH, and it exists because the service above latches its own
        boot-wide stop: once `NetworkService._revoked` is set, `poll` returns
        before it ever reaches this backend, so the loop would never be pumped
        again and its own armed tick could never fire. The service asks THIS, and
        lets the frame through when the answer is yes. Two objects, one clock, and
        the loop remains the only thing that decides what a probe does.
        """

        loop = self._loop
        if loop is None:
            return False
        reader = getattr(loop, "revoked_reprobe_due", None)
        if not callable(reader):
            return False
        try:
            return bool(reader(now))
        except Exception:
            return False

    def badge_id(self):
        """This badge's own id, from its credential.

        Needed because `badge_state`'s RLS is `badge_id = grants.whoami()`: the
        row has to name the badge, and the badge is the only thing that knows
        which one it is before the request is authenticated.
        """
        return getattr(self._creds, "badge_id", None)

    def poll(self, now):
        # THE §2 BOOT ASSERT'S OTHER HALF: OFFLINE MODE. A badge whose own
        # hardware id IS the fleet's subject cannot safely use the floor -- its
        # `badge_state` identity would be the floor's, and revoking the fleet
        # grant would revoke its own tier -- so it does not try. It
        # remains a fully working offline nametag, which is what offline-first
        # buys: refusing the radio costs the wearer nothing they can see, and the
        # one line already emitted at construction is what QA reads. Checked
        # first because every other path below either opens a socket or arms one.
        if self.provisioning_fault is not None:
            return DISCONNECTED
        # CONSUME the per-frame arbiter gate first (spec 5.3(b)). ``True`` unless
        # NetworkService set it False before this ON poll because a correctness
        # chore already spent the frame; reset so a frame nobody gates is allowed.
        allow_establishment = self._frame_establishment_allowed
        self._frame_establishment_allowed = True
        if self._retry_at is not None:
            if _ticks_diff(now, self._retry_at) < 0:
                return self.state
            self._retry_at = None
            if self._wifi.state == self._wifi_module.OFF:
                self.start(now)
        wifi_state = self._wifi.tick(now)
        online = wifi_state == self._wifi_module.ONLINE
        # THE RADIO'S OWN EDGES, NAMED, because "the badge felt laggy" has two
        # families of cause and this is the line that separates them. Nothing
        # below this method opens a socket unless the radio says ONLINE (and on
        # CYW43 `isconnected()` means an address was assigned, not merely
        # associated), so a session of `open_failed` lines with no `wifi_lost`
        # between them is a SERVER-side or path-side story, while a run of
        # `wifi_lost`/`wifi_online` pairs is the radio. `attempts`/`failures` are
        # `ResilientWiFi`'s own counters, so a flapping AP is a rising number
        # rather than an impression. Emitted on the EDGE, so a steady session
        # prints nothing at all.
        if not online:
            if self._was_online:
                snapshot = self._wifi.snapshot()
                self._emit_backend("wifi_lost", reason=snapshot.get("reason"),
                                   attempts=snapshot.get("attempts"),
                                   failures=snapshot.get("failures"))
                # CX-3: the SHARE dies with the association. A new one can mean a
                # new lease, a new resolver and a different venue's split-horizon
                # answer. The poll link keeps the `_addr_info` it was BUILT with
                # and reuses it for its authenticated reconnect; only after that
                # success is the same address re-shared with WSS. Thus the held
                # WSS task never performs blocking DNS in an ordinary frame.
                self._addresses.invalidate("wifi_lost")
                if self._held_connect_enabled:
                    self._push_address_ready = False
                if self._loop is not None:
                    self._loop.request_reconnect(now)
            self._was_online = False
            return self.state
        # ⚠ **THE ARMING IS BELOW THE BUILD, AND IT USED TO BE ABOVE IT** (Lane J,
        # 2026-08-24). `request_reconnect` is what arms the jump forgiveness
        # (`polltransport._jump_unreachable`), and it was called here under
        # `if self._loop is not None` -- with the loop built on the NEXT line. So
        # on the boot's first `wifi_online` the arming was skipped and the loop
        # that came into existence one statement later started with
        # `_forgive_unreachable_open = False`: **the boot's first stalled open was
        # never forgiven, which is exactly the DHCP/ARP-settling case the
        # forgiveness exists for.** The 2026-08-25 day-3 session measured both
        # halves with the predictions written first (§7b: `EDGE0_boot
        # predicted=not_armed jumped=1 forgiven=0`, `EDGE1_reassoc
        # predicted=armed jumps=0`) -- and §7a of the same report burned the whole
        # budget on the first open of **5 of 7 cold boots** on a HEALTHY network,
        # so the edge that was missed is the edge that produces the case.
        #
        # A LOOP THAT HAS JUST BEEN BUILT IS ON THE SAME FOOTING AS ONE THAT HAS
        # JUST SEEN AN EDGE, so the seam is the BUILD and not only the edge. That
        # also covers the case an edge-only fix would still miss: `_build_loop`
        # can RAISE (a failed resolve, an NTP failure) after `_was_online` is
        # already True, and the retry a few frames later has no edge left to arm
        # it while its first open pays the same settling window.
        #
        # WHAT IS NOT CHANGED: `PollLoop.start` still does not arm anything
        # (`test_cx_roam.FirstOpenForgivenessTests.test_start_does_not_arm_the_forgiveness`)
        # -- a bare loop started by a probe is not a radio edge, and the radio is
        # what this method knows about. And the GRANT is still bounded by
        # `polltransport.FORGIVEN_STALLS_MAX`, reset only by a successful open, so
        # the boot gets ONE settling open and a genuine black hole is escalated on
        # its second exactly as Lane I left it.
        online_edge = not self._was_online
        if online_edge:
            snapshot = self._wifi.snapshot()
            self._emit_backend("wifi_online", reason=snapshot.get("reason"),
                               attempts=snapshot.get("attempts"),
                               failures=snapshot.get("failures"))
        self._was_online = True
        built = False
        if self._loop is None:
            if self._held_connect_enabled and (
                    not allow_establishment
                    or not self._placement_establishment_allowed):
                # ON: loop preparation is establishment work (NTP/DNS/PM in this
                # one frame). A chore-spent frame may not start it -- and neither
                # may a non-opted-in app (OWNER RULING #22): building the loop
                # pays the ~1.2 s prep even if the first open is then gated, so
                # the placement deny must reach the BUILD, not only the open.
                # Wi-Fi has already ticked and its edges have run; defer a frame.
                # A re-allow at the launcher / on opt-in builds immediately.
                return self.state
            self._build_loop(now)
            online_edge = True
            built = True
        if online_edge:
            self._loop.request_reconnect(now)
        if self._held_connect_enabled and built:
            # ON: the build frame paid preparation; that IS its establishment
            # step (counted in `_build_loop`), and the first `open_step` belongs
            # to the NEXT frame so a ~1.2 s prepare and a ~850 ms first handshake
            # never stack. The arbiter still sees this frame as a connect frame,
            # because `establishment_steps()` moved on the prepare. OFF never
            # reaches this and stays exactly synchronous.
            return self.state
        if self._held_connect_enabled:
            # OWNER RULING #22 placement, forwarded to the loop's PERSISTENT
            # gate before it polls. Denying while an open is in-flight aborts it
            # as a non-failure (re-armed, due/backoff preserved) and blocks a new
            # one; a warm CONNECTED session is left polling. Driven every frame
            # so the deny EDGE (app entry) is what aborts, and re-allow (launcher
            # / opt-in) is immediately schedulable. `request_reconnect` above may
            # have re-armed a reconnect on a radio edge; this gate then defers it
            # under placement rather than opening into the app.
            self._loop.set_establishment_allowed(
                self._placement_establishment_allowed)
            self._loop.poll(now, allow_establishment=allow_establishment)
            self._restore_push_address_after_poll()
            return self.state
        self._loop.poll(now)
        return self.state

    def _restore_push_address_after_poll(self):
        """Re-share the poll address only after a successful authenticated open."""

        if getattr(self, "_push_address_ready", True):
            return False
        loop = self._loop
        if loop is None or getattr(loop, "state", None) != CONNECTED:
            return False
        info = getattr(self, "_poll_addr_info", None)
        if info is None:
            return False
        remembered = self._addresses.remember(self._creds.host, 443, info)
        if remembered is None:
            return False
        self._push_address_ready = True
        return True

    def note_push_unreachable(self, cause="unreachable"):
        """The doorbell demoted for UNREACHABLE: forget the session's addresses.

        WHY THE BACKEND OWNS THIS AND NOT THE FACTORY. `device_push_factory` can
        already reach `SessionAddresses` (through `poll_loop.link.addresses`), so
        a bare `invalidate()` there looks like the smaller change -- and in ON it
        is a PERMANENT STALL. Held WSS never resolves; it is admitted only while
        `push_address_ready()` is true, and that reads TWO things: the cache, and
        the `_push_address_ready` bit that `_restore_push_address_after_poll`
        needs to be False before it will re-share the poll's address. Clearing
        the cache alone leaves the bit True, so the gate refuses every moment and
        the only repair path refuses to run. The two fields have one owner and
        this is it.

        WHAT THE TWO STRATEGIES THEN DO, and neither of them resolves off-radio:

        * OFF re-resolves on its next attempt, through `address_strict` ->
          `bounded_dns` (<=1,000 ms, never the unbounded 13.1-14.0 s call), and
          that attempt is already gated on `online` by `_service_push`.
        * ON resolves nothing, ever. It waits for
          `_restore_push_address_after_poll` to re-share the address the POLL
          link has just carried through an authenticated TLS reopen -- so the
          doorbell resumes behind a proven-live answer instead of an unexamined
          cached one. That repair costs a frame or two against a 15-30 minute
          re-arm, so ON is not slowed by this.

        Same reasoning as `_bound_ntp_host` either way: a lookup is only ever
        entered where there is already evidence of a route.

        `cause` is `pushlink`'s own bounded word and is accepted but not echoed:
        the emitted reason is a LITERAL from this module's closed set, so no
        push-side string can ever reach a line a screen might draw.
        """

        count = self._addresses.invalidate("push_unreachable")
        if self._held_connect_enabled:
            # UNCONDITIONAL, not `if count`. An already-empty cache with the bit
            # still True is exactly the stall described above, and a backend that
            # only repaired the case it caused would leave the other one standing.
            self._push_address_ready = False
        return count

    def failed(self, now, exc):
        self.last_error = _error_text(exc)
        if self._loop is not None:
            self._loop.restart()
            return
        self._failures += 1
        delay = min(300000, 1000 * (1 << min(self._failures - 1, 9)))
        self._retry_at = _ticks_add(now, delay)

    def stop(self):
        if self._loop is not None:
            if self._held_connect_enabled:
                # Bank the retiring loop's open steps so `establishment_steps`
                # stays MONOTONIC across a rebuild: the next loop restarts its
                # own `open_steps` at 0. (spec 5.1: monotonic across rebuilds.)
                self._establishment_steps += getattr(
                    self._loop, "open_steps", 0)
            self._loop.stop()
            self._loop = None
        if self._original_pm is not None and self._wlan.active():
            try:
                self._radio_policy.restore_power_management(
                    self._wlan, self._original_pm)
            except Exception:
                pass
        self._wifi.stop(power_down=True, clear_credentials=True)
        # The radio is going down, so the WLAN session the addresses were scoped
        # to is over. Same rule as the `wifi_lost` edge (CX-3).
        self._addresses.invalidate("radio_stopped")
        if self._held_connect_enabled:
            self._push_address_ready = False
        self._network.country(self._original_country)
        gc.collect()

    def _emit_backend(self, event, **fields):
        """One event out of the backend, contained.

        The backend has no `_emit` of its own; the service's `_on_backend_event`
        is what `event_sink` holds. A sink that raises must not cost a connect,
        which is why this swallows: the event is diagnostics, the socket is not.
        """
        sink = self._event_sink
        if sink is None:
            return
        record = {"event": event}
        record.update(fields)
        try:
            sink(record)
        except Exception:
            pass

    def _emit_backend_record(self, record):
        """The same containment, for a collaborator that builds its own record.

        `SessionAddresses` is constructed before `_event_sink` is read anywhere,
        and it does not know this class's keyword shape, so it hands over a dict.
        """
        sink = self._event_sink
        if sink is None:
            return
        try:
            sink(record)
        except Exception:
            pass

    def _bound_ntp_host(self):
        """May the NTP resync run without risking an unbounded lookup?

        **THE BOUNDED RESOLVE IS USED AS A PROBE, AND THAT IS WHAT MAKES THIS SAFE
        WITHOUT DEPENDING ON A WRITABLE MODULE.** The pinned `ntptime` resolves its
        own host inside `time()` and `settime()` -- twice per boot -- with
        `settimeout(1)` applied AFTER the lookup, so that timeout bounds the UDP recv
        and bounds the name lookup not at all. Two unbounded lookups, and with no
        route each is 13.1-14.0 s.

        The obvious fix is to overwrite `ntptime.host` with an address so it never
        looks anything up. That is done below, but it is an OPTIMISATION and not the
        guarantee -- C-level modules on this firmware are read-only and an attribute
        write to one raises a misleading `AttributeError` naming an attribute that
        exists and reads fine. So the correctness argument rests on something that
        cannot fail instead:

        * if the bounded resolve SUCCEEDS, the network resolves, and `ntptime`'s own
          lookups will cost the 30 ms a routed NXDOMAIN costs -- safe whether or not
          the write took;
        * if it FAILS, there is no route, which is precisely and only when those
          lookups burn fourteen seconds each -- so the sync is skipped.

        Either way no frame waits on an unbounded resolver, and the read-only
        question is reduced to "did we save two fast round trips".

        RESOLVED FROM THE REMEMBERED NAME, never from `ntptime.host` as found, because
        after the first call that attribute holds an address. Reading it back as the
        name is how a stale address survives a venue change.

        ``True`` when the caller may proceed. Total: this runs on the loop-build
        frame, where a raise is a `machine.reset()`.
        """

        ntptime_module = self._ntptime
        if self._ntp_host is None:
            candidate = getattr(ntptime_module, "host", None)
            if not isinstance(candidate, str) or not candidate:
                # A stub, a fixture, or an `ntptime` that names no host: nothing to
                # bind and nothing to protect, so do not invent a refusal.
                return True
            self._ntp_host = candidate
        try:
            address = self._resolver.resolve(self._ntp_host)
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit_backend("ntp_unresolved", error=self.last_error)
            return False
        try:
            ntptime_module.host = address
        except Exception:
            # READ-ONLY MODULE, and it costs only the two fast round trips the
            # write would have saved. Not an error and not worth a line: the
            # branch above already proved the lookups are cheap right now.
            pass
        return True

    def _build_loop(self, now):
        # THE CLOCK IS RE-SYNCED ON EVERY CONNECT. This used to run NTP only when
        # `evaluate_ntp` REFUSED the clock the badge already had -- a window from
        # 2026-08-08 to 2099 -- so a badge whose clock was set once and was WRONG
        # never asked again. Card FT-B's F14/F15 fired 4.918 s and 4.934 s late
        # against the server's own timestamp on the reference badge, and the
        # second was after a physical RESET: `time.time()` on RP2350 IS the
        # powman always-on timer, it keeps counting across a reset while power is
        # present, and the firmware's boot sync only copies localtime -> PCF, so
        # nothing else in the stack can correct it. `clock_boot.resync` carries
        # the whole rationale and the fail-soft asymmetry -- a venue that blocks
        # UDP/123 keeps its transport, a badge with no plausible clock still
        # refuses, because verified TLS cannot check a certificate without one.
        #
        # WHAT THIS ONE FRAME BLOCKS ON, PRICED, because until 2026-08-23 nothing
        # measured it and it is the least examined expensive frame BadgeLink has.
        # Building a loop performs, IN ONE RENDERED FRAME and before a single
        # socket is opened:
        #
        #   * ``clock_boot.resync`` -> ``ntptime.time()`` then
        #     ``ntptime.settime()`` -> ``time()`` again. TWO UDP round trips is
        #     the price its own docstring names; what nothing priced is that the
        #     pinned ``ntptime`` resolves ITS OWN host each time
        #     (``socket.getaddrinfo("pool.ntp.org", 123)``,
        #     micropython-lib ``ntptime.py``) and that ``settimeout(1)`` is set
        #     AFTER the resolve, so the 1 s timeout bounds the UDP recv and
        #     bounds the name lookup NOT AT ALL. Two lookups, unbounded.
        #   * ``getaddrinfo`` for the project host below. A third lookup, also
        #     unbounded: MicroPython's ``socket.getaddrinfo`` takes no timeout
        #     argument at any version, so the resolver's own retry ladder is the
        #     only bound and a frame waits for all of it.
        #
        # So ``ntp_ms`` and ``resolve_ms`` are reported separately, and the badge
        # says which of them cost the frame instead of leaving a reader to infer
        # it from a single figure. NOTHING HERE CHANGES A DECISION -- no timeout
        # is imposed, no call is skipped, no order is altered; the numbers are
        # published and that is all. Deciding what to do about them needs device
        # evidence this instrumentation exists to collect.
        if self._held_connect_enabled:
            # ON: preparation is an establishment step of its own (spec 5.1).
            # Counted BEFORE the work, so a resolve/NTP that RAISES still marks
            # this frame a connect frame for the arbiter -- the frame that spent
            # the whole budget in a blocked resolver is exactly the one the
            # doorbell must not also try to establish on.
            self._establishment_steps += 1
        prepare_started = _ticks_ms()
        entered = prepare_started
        if self._bound_ntp_host():
            try:
                outcome = self._clock_boot.resync(
                    self._ntptime,
                    self._rtc,
                    read_epoch=lambda: int(time.time()),
                    clock_verified=self._clock_verified,
                )
            except Exception as exc:
                # THE ONE PATH THAT PRODUCES NO OUTCOME DICT, AND IT IS THE
                # BRICK. `resync` raises only when the badge has NO plausible
                # clock and the sync did not land -- verified TLS cannot check a
                # certificate without one, so there is nothing to fail soft to.
                # The raise propagates unchanged (`poll` retries on a later
                # frame); latching first is what stops the reason dying with the
                # frame, because this is the state where NOTHING downstream ever
                # exists to describe it: no loop, no doorbell, no snapshot.
                #
                # `.reason` IS `ClockError`'S OWN FIELD and it is the whole
                # value here (`ntp_rejected: before_build_floor` is a different
                # instruction to an operator than `ntp_unreachable: OSError`).
                # Anything else that escapes gets the module's usual
                # "ClassName: message", so an unexpected fault is still legible.
                self._clock_reason = getattr(exc, "reason", None) or _error_text(exc)
                raise
        else:
            # NO ROUTE TO A RESOLVER, so the pinned `ntptime`'s own two unbounded
            # lookups are exactly the 13-14 s freeze this guard exists to avoid.
            # Skipping is the cheap, correct answer HERE and only here: the badge
            # keeps whatever clock it had, `evaluate_ntp` still gates plausibility,
            # and the next loop build tries again. See `_bound_ntp_host`.
            outcome = {"synced": False, "epoch": int(time.time()), "shift": 0,
                       "reason": "dns_unreachable"}
        ntp_ms = _ticks_diff(_ticks_ms(), entered)
        current = outcome["epoch"]
        # THE SAME WORD THE EVENT CARRIES, kept where a screen can reach it.
        # Both branches below print it and neither retains it, which is why a
        # badge that skipped the sync could say nothing about why.
        self._clock_reason = outcome["reason"]
        if outcome["synced"]:
            # THE LATCH IS SET ONLY BY A LANDED SYNC, never by a plausible read.
            # From here the shift bound applies as it always did; before here a
            # PCF-restored clock must not be allowed to refuse its own correction.
            self._clock_verified = True
            self._emit_backend("clock_resynced", shift_s=outcome["shift"],
                               ntp_ms=ntp_ms)
        else:
            self._emit_backend("clock_resync_skipped", reason=outcome["reason"],
                               ntp_ms=ntp_ms)
        self._credentials_module.assert_event_window(self._creds.claims, current)
        entered = _ticks_ms()
        if self._original_pm is None:
            self._original_pm, _ = self._radio_policy.disable_power_save(
                self._wlan, self._network.WLAN)
        pm_ms = _ticks_diff(_ticks_ms(), entered)
        entered = _ticks_ms()
        try:
            # THROUGH THE SHARED CACHE (CX-3), not around it. The blocking call is
            # the same one, `resolve_ms` still prices it, and a cache HIT here is
            # only possible when a previous loop in this WLAN session already paid
            # it -- which is the case a networking off/on toggle used to re-pay.
            # What the cache is really for is the WSS path, which had no cache at
            # all; this call is what puts the entry in it.
            addr_info = self._addresses.resolve(
                self._creds.connect_host(), 443)
            # AND FILE IT UNDER THE HOSTNAME AS WELL, which the harness caught
            # and nothing else would have. `connect_host()` is `ip or host`, so a
            # badge provisioned with `BADGELINK_IP` resolves the IP -- and the
            # doorbell asks for the HOST, because its URL is built from
            # `creds.host` and SNI must stay on the name. Without this line the
            # two transports would key the same endpoint two ways and push would
            # have gone on doing its own lookup, which is exactly the pre-set
            # `BADGELINK_IP` is there to avoid.
            self._addresses.remember(self._creds.host, 443, addr_info)
            if self._held_connect_enabled:
                # Initial readiness follows current-association resolution, not
                # a successful poll open: WSS performs its own hostname-verified
                # TLS and must not inherit poll liveness. After a roam the old
                # row is different -- `_restore_push_address_after_poll` waits
                # for an authenticated poll reopen before re-sharing it.
                self._poll_addr_info = addr_info
                self._push_address_ready = True
        except Exception:
            # A FAILED RESOLUTION IS THE EXPENSIVE ONE, so it must not be the
            # unreported one. The exception is re-raised untouched -- the service
            # still contains it and still applies its own retry ramp -- but the
            # frame it cost is now on the wire.
            self._emit_backend("link_prepared", ntp_ms=ntp_ms, pm_ms=pm_ms,
                               resolve_ms=_ticks_diff(_ticks_ms(), entered),
                               prepare_ms=_ticks_diff(_ticks_ms(),
                                                      prepare_started),
                               reason="resolve_failed")
            raise
        resolve_ms = _ticks_diff(_ticks_ms(), entered)

        # HOW MANY OPENS THIS LINK HAS ASKED FOR. A one-element list because the
        # closure below has to WRITE it and this module targets MicroPython.
        #
        # THE FACTORY IS CALLED EXACTLY ONCE PER OPEN, from
        # `device_link._connect_worker` inside `DeviceLink.open`, which is why the
        # count lives here and nowhere else: it makes "which open of this link is
        # this" a fact rather than an inference, and it puts the cold/warm choice
        # in the ONE place that also spells `timeout=`. A counter in `device_link`
        # beside this one would be two decisions that agree today.
        opens_asked = [0]

        def worker_factory(_connect_host, provided_addr):
            # THE IN-FRAME OPEN BUDGET, IN WHOLE SECONDS, and this is where it is
            # actually applied: `open()` is a blocking spin loop in ONE rendered
            # frame and the frozen `AsyncFetch`'s inactivity ceiling is the only
            # thing that ends it against a peer that never answers.
            #
            # **FIVE since the owner's 2026-08-24 ruling ("10 seconds is too
            # extreme", OWNER-DECISIONS #21); ten before it -- AND NINE FOR THE
            # FIRST OPEN OF THIS LINK since Lane J**, because the 5,000 was
            # measured truncating HEALTHY cold boots: 5 of 7, each then punished
            # with a 20-31 s jump, with one open at 4,119 ms SUCCEEDING beside
            # them. The derivations, the evidence and the costs of both are in
            # `polltransport.OPEN_BUDGET_MS` and
            # `polltransport.COLD_OPEN_BUDGET_MS`; `OPEN_BUDGET_S` /
            # `COLD_OPEN_BUDGET_S` at the top of this module are the seconds and
            # the reason they are named.
            opens_asked[0] += 1
            budget_s = (COLD_OPEN_BUDGET_S if opens_asked[0] == 1
                        else OPEN_BUDGET_S)
            worker = self._fetch.AsyncFetch(
                self._creds.host,
                443,
                use_tls=True,
                max_bytes=self._postgrest.MAX_BODY_BYTES,
                timeout=budget_s,
            )
            worker._addr_info = provided_addr
            # AND THE MIRROR TRAVELS WITH THE WORKER. `device_link` declares the
            # `LinkStalled` class at the ceiling the firmware was actually given,
            # and the frozen `AsyncFetch` has no accessor for its own `timeout`,
            # so the factory records what it chose. Same mechanism as
            # `_addr_info` one line above; read by
            # `device_link._worker_no_progress_ms`, which falls back to the warm
            # budget when there is nothing to read.
            setattr(worker, self._device_link.WORKER_BUDGET_ATTR,
                    budget_s * 1000)
            return worker

        # ONE READ, AND THE LOCAL IS WHY: the value goes into the link AND
        # decides whether the diagnostic line below fires, and a second call
        # could not disagree (it is cached) but a reader should not have to know
        # that to trust the pair.
        self_uid = hardware_uid()
        shim = self._device_link._ShimInstaller(
            self._fetch,
            self._ssl,
            DEVICE_CA_PATHS,
            self._verified_tls,
        )
        if self._held_connect_enabled:
            # ON: install the socket-readiness proxy so `open_step` can tell a
            # genuine network wait from a generator budget yield. Before the
            # first `install()` (deferred to the first open); a no-op in OFF,
            # which never reaches this line.
            shim.enable_open_tracking()
        link = self._device_link.DeviceLink(
            self._creds,
            worker_factory=worker_factory,
            shim=shim,
            addr_info=addr_info,
            # THE LINK'S OWN EVENTS HAD NO SINK AT ALL until 2026-08-23, so
            # `opened`, `token_rejected`, `access_revoked` and now the open's
            # phase split were emitted into `None` on every real badge and were
            # readable only by a probe that built its own DeviceLink. That is the
            # same defect the poll-cost section recorded for `shift_s` -- a
            # forwarded field with no printer is a field nobody watching a badge
            # can read -- and the fix is the same one line.
            event_sink=self._event_sink,
            # CX-3: the session's shared address cache, CARRIED so the doorbell
            # can reach it through the one object it is handed (`poll_loop.link`)
            # without this backend's construction seam appearing in
            # `device_push_factory`'s signature -- which is fixed by the generated
            # `/system/main.py` block and cannot grow an argument without a
            # reinstall. Nothing in `device_link` reads it.
            addresses=self._addresses,
            # THE PHYSICAL BADGE, for the `_self` poll/ack `p_badge_id` and the
            # `x-badge-id` fairness bucket. The SAME per-boot value the doorbell's
            # ring filter and the score drain read -- one uid, four consumers --
            # because two reads that disagreed would mean a badge that rings for
            # commands it then cannot poll for.
            self_badge_id=self_uid,
        )
        if self_uid is None:
            # THE LINE THAT PAYS FOR THE FAIL-SOFT. A badge whose hardware uid
            # read failed polls the whoami queue instead of its own, which on the
            # shared fleet subject delivers nothing -- a working socket, a
            # working schedule, and no commands, forever. That is the right
            # degradation and the WRONG thing to leave silent, because it is
            # indistinguishable from an event nobody queued anything for. One
            # line per link build, not per poll.
            self._emit_backend("link_unaddressed")
        self._emit_backend("link_prepared", ntp_ms=ntp_ms, pm_ms=pm_ms,
                           resolve_ms=resolve_ms,
                           prepare_ms=_ticks_diff(_ticks_ms(), prepare_started),
                           reason=outcome["reason"])
        self._loop = self._polltransport.PollLoop(
            link,
            command_sink=self._command_sink,
            event_sink=self._event_sink,
            # The server's steering fields, forwarded verbatim; the service
            # decides what they mean and only when there is a doorbell to steer.
            policy_sink=self._policy_sink,
        )
        if self._held_connect_enabled:
            # ON: select the multi-frame parked open before the first attempt,
            # so the poll open PARKS across frames instead of spinning
            # `time.sleep_ms(1)` inside one. Must precede `start()`, which arms
            # the first attempt; `enable_parked_open` refuses a loop that has
            # already opened. A no-op path in OFF: this line is never reached.
            self._loop.enable_parked_open()
        if self._suggested_cadence_ms is not None:
            # A CADENCE THE SERVER SUGGESTED BEFORE THIS LOOP EXISTED. The fleet
            # settings are read once every five minutes and a loop is rebuilt on
            # every fault and every networking toggle, so without this the badge
            # would fall back to its own default cadence for up to five minutes
            # after each rebuild -- and an operator who slowed the fleet down
            # would watch it speed itself back up.
            self._loop.set_suggested_cadence(self._suggested_cadence_ms)
        durable = self._store.load()
        self._loop.desired_version = durable.get("desired_version", 0)
        self._loop.set_active(self._active)
        self._loop.start(now)


def _wss_host_from(url, fallback):
    """The hostname in a ``wss://host/path`` URL, or ``fallback``.

    Parsed rather than assumed because the WSS host and the REST host are not
    guaranteed to be the same name in every deployment shape -- today they are
    (both ``<ref>.supabase.co``), and per-host caching means nothing downstream
    has to care if that stops being true. Never raises: an unexpected URL shape
    falls back to the credential's host, which is the value the URL was built
    from.
    """
    if not isinstance(url, str):
        return fallback
    at = url.find("://")
    if at < 0:
        return fallback
    rest = url[at + 3:]
    for stop in ("/", "?", "#"):
        cut = rest.find(stop)
        if cut >= 0:
            rest = rest[:cut]
    if "@" in rest:
        rest = rest.rsplit("@", 1)[1]
    if ":" in rest:
        rest = rest.rsplit(":", 1)[0]
    return rest or fallback


def _wss_connect_host(addresses, url, fallback, cached_only=False):
    """The address to open the doorbell's socket to, or ``None`` for by-name."""
    host = _wss_host_from(url, fallback)
    if cached_only:
        # A held task runs in an ordinary rendered frame, where getaddrinfo is an
        # untimeoutable C call. OFF retains the historical resolve-and-cache miss
        # below; only ON is admitted after the poll path has filled this cache.
        # Failing locally is intentional: `None` is not a harmless absence at
        # the next layer, it explicitly means "resolve the hostname now".
        cached = None if addresses is None else getattr(
            addresses, "cached_address", None)
        value = cached(host, 443) if callable(cached) else None
        if not isinstance(value, str) or not value:
            raise OSError("held WSS cached address unavailable")
        return value
    if addresses is None:
        # `None` MEANS "resolve the hostname at the next layer", and on MicroPython
        # that layer resolves INSIDE `open_connection` -- a C call no timeout reaches,
        # 13.1-14.0 s with no route. So it is worth saying exactly who reaches this
        # branch, because it looks like an unbounded freeze and is not one.
        #
        # **FIXTURES AND PROBES, plus a backend that predates the seam** -- the shape
        # `test_no_cache_at_all_still_connects_by_name` pins. In production
        # `addresses` is `poll_loop.link.addresses` and every current `device_link`
        # carries one, so the resolve goes through `addresses.address` below, which
        # since 2026-08-27 is `bounded_dns` and cannot exceed 1,000 ms.
        #
        # A REFUSAL HERE WAS DRAFTED AND REVERTED. It reads well -- "never return a
        # value that means unbounded" -- and it breaks six probe tests plus the
        # by-name affordance those probes are built on, to protect a configuration
        # (partial install of `device_link.mpy`) that has its own detection and in
        # which the doorbell is the least of the badge's problems. Bounding the
        # PRODUCTION path was the whole job; bounding the fixture path costs the
        # fixtures and buys nothing.
        return None
    # STRICT ON PURPOSE. This value is consumed in an ordinary rendered frame,
    # so a `None` here does not degrade gracefully -- it escalates a bounded
    # 1,000 ms resolver timeout into an untimeoutable 13-14 s C call, and the
    # wearer pays both. Raising instead lets the establishment be retried on the
    # ladder, which is what every other transient failure on this path already
    # does. The `addresses is None` branch above is untouched: that one is the
    # fixture affordance and by-name is correct there.
    return addresses.address_strict(host, 443)


# WHERE ONE DOORBELL ESTABLISHMENT'S MILLISECONDS WENT (NB-i), and why the
# record is built HERE rather than in `pushlink` or in the WS client.
#
# The badge reported the whole thing as ONE number -- `push_moment ms=2413` --
# and the 2026-08-25 freeze capture measured that lump at 2,252-2,436 ms inside a
# single rendered frame, three runs for three, which is the freeze the owner
# felt. One number cannot say which leg to convert, and the four legs are not
# comparable costs:
#
# * ``tcp_ms`` is the whole ``asyncio.open_connection``, and on MicroPython the
#   NAME RESOLUTION HAPPENS INSIDE IT -- which is exactly why `connect_host`
#   exists, and why a cold lookup is in this bucket by construction.
# * ``ws_tls_ms`` is ONE WRITE that carries the ENTIRE deferred TLS handshake
#   plus the Upgrade flush, because the pinned ``open_connection`` wraps with
#   ``do_handshake_on_connect=False``. The 820-903 ms certificate-verify flight
#   the TLS-split probe measured on hardware lands here and nowhere else.
# * ``upgrade_ms`` is the status line and header reads, each bounded by
#   ``io_timeout_ms``.
# * ``join_send_ms`` runs from ``ws_connect``'s RETURN to ``client.connect()``'s
#   return: the receive-task creation and the bounded ``phx_join`` SENDS.
#   **THE JOIN REPLY IS STRUCTURALLY OUTSIDE IT.** `RealtimeClient.connect`
#   awaits `_join`, which SENDS; the acknowledgement, its timeout, the channel
#   backoff and demotion are the ordinary per-frame `service()` path, reaping a
#   parked receive task. A reader who budgets a reply in this number is reading
#   a leg that never lands in it.
#
# THIS SCOPE IS THE ONLY ONE THAT SEES ALL FOUR. The first three are measured
# inside the vendored WS client through its ``trace=`` dict; the fourth needs
# both the moment `ws_connect` returned (only this closure sees it) and the
# moment `client.connect()` returned (only `PushLink` sees it, and it says so
# through the `open_trace` hook). `event_sink` is already in scope here too.
#
# FIXED SHAPE, mirroring `device_link._open_phases`: every key present from the
# start, so a handshake cancelled mid-leg by `connect_timeout_ms` still prints a
# FULL row -- with `phase` naming the leg it died in -- and the emitted-field
# census sees a stable field set. PURELY REPORTED: nothing reads a number back
# out of it, and no decision anywhere is built from one.
def _ws_open_phases():
    """A fresh, fixed-shape accounting record for ONE WSS establishment."""

    return {
        "transport": "badgelink_push",
        "event": "ws_open_phases",
        "tcp_ms": 0,
        "ws_tls_ms": 0,
        "upgrade_ms": 0,
        "join_send_ms": 0,
        "phase": None,
        "outcome": None,
    }


def device_push_factory(
    poll_loop,
    event_sink,
    enabled,
    realtime_client,
    backoff_reset,
):
    """Build the production Realtime doorbell over the live polling loop.

    The layer-2 class and reset literal arrive from ``/system/main.py``. That
    preserves the enforced package boundary: BadgeLink cannot import
    ``realtime`` directly, and layer 2 cannot import badge code. Imports remain
    lazy so a stale/partial payload degrades to ``push_unavailable`` without
    taking polling down. One verified context and one session are reused across
    every reconnect owned by this PushLink.

    IT ALSO SHARES THE POLL TRANSPORT'S RESOLVED ADDRESS (CX-3). ``poll_loop`` is
    the only thing this factory is handed -- its signature is fixed by the
    generated ``/system/main.py`` block -- so the cache is read off the loop's own
    link, which `DeviceBackend` put there. OFF retains the historical by-name
    fallback for an absent cache. A held ON attempt fails locally instead:
    passing ``None`` onward means "call getaddrinfo", which is precisely the
    untimeoutable rendered-frame wait this phase removes.
    """

    import secrets
    import ssl

    import aiohttp
    import credentials
    import pushlink
    import verified_tls
    from ws_backoff import BackoffPolicy

    if not callable(realtime_client):
        raise ValueError("Realtime client must be callable")

    addresses = getattr(getattr(poll_loop, "link", None), "addresses", None)
    creds = credentials.load(secrets)
    tls = verified_tls.VerifiedTLSShim(ssl, DEVICE_CA_PATHS)
    context = tls.SSLContext(tls.PROTOCOL_TLS_CLIENT)
    session = aiohttp.ClientSession(**pushlink.transport_config())

    def token_provider():
        current = credentials.load(secrets)
        return current.jwt, current.claims

    # THE ESTABLISHMENT IN FLIGHT, and one slot is enough: the badge is
    # single-threaded, there is one PushLink, and `_maybe_connect` awaits one
    # `client.connect()` to completion before another can start. `record` is
    # `None` between establishments, which is what makes an outcome with no
    # establishment behind it (an unusable token, a client that raised before it
    # reached the closure) emit nothing at all. See `_ws_open_phases`.
    establishment = {"record": None, "handoff_ms": None, "trace": True}

    def note_establishment(outcome, terminal_ms=None):
        """Commit one outcome without charging time spent parked after it."""

        record = establishment["record"]
        handoff = establishment["handoff_ms"]
        establishment["record"] = None
        establishment["handoff_ms"] = None
        if record is None:
            return None
        if handoff is not None:
            terminal = _ticks_ms() if terminal_ms is None else terminal_ms
            span = _ticks_diff(terminal, handoff)
            record["join_send_ms"] = 0 if span < 0 else span
        record["outcome"] = outcome
        event_sink(record)
        return record

    def client_factory():
        async def ws_connect(url):
            # NO LOOKUP HERE. ON admits only with a current-association numeric
            # address from DeviceBackend's poll cache; after a roam that retained
            # address is not restored until the poll TLS reopen succeeds. WSS
            # still verifies the hostname itself -- the share removes DNS work,
            # it does not borrow the poll connection's trust decision.
            # Absence or a malformed cache fails before `session.ws_connect`;
            # its `connect_host=None` convention means "resolve now", not "wait
            # for an address later".
            #
            # `trace=` is the establishment record (NB-i): the WS client writes
            # its three handshake legs and its current phase into it, and the
            # handoff tick below is what lets `note_establishment` measure the
            # join-send leg. A raise leaves the record in place with `phase`
            # naming the leg it died in and no handoff, so the partial row is
            # still emitted when `PushLink` reports the outcome.
            #
            # ⚠ **AND THE KWARG IS GUARDED, because it is NOT ADDITIVE the way
            # `connect_host=` was.** Found on a bench, not in a test (the
            # 2026-08-25 day-3 session's §14): the vendored client before this
            # instrument has no `trace` parameter and no `**kwargs`, so on a
            # badge whose `network_runtime` outruns its vendored `aiohttp` --
            # a partial install, or a stale `.py` SHADOW at the LittleFS root,
            # which beats a `.mpy` under `/system/lib` and which no installer can
            # see -- EVERY establishment raised `TypeError`, three of those is
            # `DEMOTE_AFTER_SESSIONS`, and the doorbell was dead for the boot.
            # An instrument may not cost a badge its socket.
            #
            # ASKED ONCE PER BOOT and then never again, so the fallback cannot
            # become a second attempt per establishment. A `TypeError` from
            # DEEPER inside a supporting client would also land here and turn the
            # instrument off for the boot after one extra attempt -- the right
            # direction, and the `ws_trace_unsupported` line says which.
            if establishment["trace"]:
                record = _ws_open_phases()
                establishment["record"] = record
                establishment["handoff_ms"] = None
                # Allocate the record BEFORE the cache read. That read is
                # required to be nonblocking, but if a partial-install fallback
                # ever violates the contract, the cost/failure remains visible.
                record["phase"] = "address"
                connect_host = _wss_connect_host(
                    addresses, url, creds.host,
                    cached_only=link._held_strategy)
                try:
                    response = await session.ws_connect(
                        url, ssl=context, connect_host=connect_host,
                        trace=record)
                except TypeError:
                    establishment["trace"] = False
                    # NO all-zero row: four zeros would read as a 0 ms
                    # handshake. The record is dropped and one line says the
                    # instrument is off.
                    establishment["record"] = None
                    event_sink({"transport": "badgelink_push",
                                "event": "ws_trace_unsupported"})
                    response = await session.ws_connect(
                        url, ssl=context, connect_host=connect_host)
            else:
                connect_host = _wss_connect_host(
                    addresses, url, creds.host,
                    cached_only=link._held_strategy)
                response = await session.ws_connect(
                    url, ssl=context, connect_host=connect_host)
            establishment["handoff_ms"] = _ticks_ms()
            return response

        return realtime_client(
            "wss://{}{}".format(creds.host, REALTIME_SOCKET_PATH),
            creds.apikey,
            ws_connect,
            backoff_factory=lambda: BackoffPolicy(1000, 30000),
            backoff_reset=backoff_reset,
        )

    # THE FLEET TOPIC IS THE PRIMARY CHANNEL, and `badge_topic(creds.badge_id)`
    # is gone from this call for the reason the whole shared-token migration
    # exists: `creds.badge_id` is the JWT `sub`, every badge ships the same one,
    # so `badge:<sub>` is ONE private topic 800 badges would collapse onto and
    # that the server addresses no command to. The server keeps publishing it
    # for the web Control page and for any badge still on a per-badge token; new
    # firmware simply stops subscribing. One channel, one handshake.
    #
    # AND THE HARDWARE UID IS READ HERE, ONCE, because `pushlink` may not: its
    # contract is that it imports no Badgeware and holds no credential, so the
    # only place that can turn `machine.unique_id()` into a ring filter is this
    # factory. `None` (a host fixture, a board without `machine`) leaves the
    # filter unable to prove a match, which is silence rather than a herd.
    target_uid = hardware_uid()
    link = pushlink.PushLink(
        poll_loop,
        client_factory,
        pushlink.event_topic(pushlink.EVENT_DOORBELL_NAME),
        token_provider,
        policy=pushlink.PushPolicy(enabled=enabled),
        event_sink=event_sink,
        epoch_clock=lambda: int(time.time()),
        open_trace=note_establishment,
        target_uid=target_uid,
    )
    if target_uid is None:
        # ONE LINE, ONCE PER BOOT, because the alternative is invisible: a badge
        # whose UID read failed joins the fleet topic, filters every ring and
        # looks exactly like a badge nobody has queued a command for.
        event_sink({"transport": "badgelink_push", "event": "push_untargeted"})
    return pushlink.PushService(link, event_sink=event_sink)


# WHAT A SERIAL READER GETS TO SEE, in a fixed order. Every one of these is a
# number or a short enum -- no URL, no apikey, no token, no payload, no wearer
# text -- which is why the list is a whitelist rather than "print the record".
#
# THIS LIST IS THE HALF THAT WAS MISSING. `_on_backend_event` has forwarded
# `shift_s` since 11200e09 so "a probe and a serial reader can both see it", but
# the production serial printer only ever rendered `event=` and `state=`, so on a
# normally booted badge the clock shift was invisible: only a probe that
# installed its OWN sink could read it. A forwarded field with no printer is a
# field nobody watching a badge can read.
# WHERE A CONNECT'S MILLISECONDS WENT. One tuple, used by BOTH whitelists (the
# probe-facing forwarder and the serial printer), because a number that reaches
# one and not the other is exactly the defect the poll-cost section recorded.
#
# Two events carry these. `link_prepared` prices the frame that builds a loop --
# `ntp_ms` is `clock_boot.resync`'s two UDP round trips INCLUDING the two
# unbounded `pool.ntp.org` lookups the pinned `ntptime` performs inside them,
# `resolve_ms` is the project host's own unbounded `getaddrinfo`, `pm_ms` is the
# power-save disable, `prepare_ms` is the lot. `open_phases` prices one handshake
# in the firmware's OWN phase labels (`device_link._OPEN_PHASE_KEYS`):
# `connect_ms` is socket + non-blocking connect + the verified-TLS context and
# its two CA parses, `send_ms` is the deferred TLS HANDSHAKE plus the request
# write, `headers_ms`/`body_ms` are the response, and `sleep_ms` is our own
# cooperative sleep between steps rather than anything the radio did.
# `open_step_max_ms` is the largest single blocking firmware `update()`. P1-a
# adds `open_frame_max_ms` because batching several ready updates means an atomic
# maximum alone is no longer a frame oracle. `open_span_ms` is admission through
# terminal outcome, `open_busy_ms` is time inside outer calls, `open_wait_ms` is
# the remainder, and `open_steps` counts actual worker updates. The four always
# reconcile and keep literal `sleep_ms` zero on the parked path.
# `open_stall_ms` is how long that open went without hearing the PEER, and it is
# the evidence behind `outcome`: a `LinkStalled` open is one whose stall reached
# the deadline, and printing the number is what lets a reader check the CX-5
# classification rather than trust it.
#
# EVERY ONE IS AN INTEGER OR A SHORT ENUM. No URL, no apikey, no token, no
# payload, no wearer text -- the same rule the rest of the whitelist follows.
# A THIRD EVENT JOINED THEM ON 2026-08-24: `ws_open_phases` prices ONE DOORBELL
# ESTABLISHMENT in the four legs `_ws_open_phases` documents -- `tcp_ms` (the
# whole `open_connection`, name resolution included), `ws_tls_ms` (one write
# carrying the entire deferred TLS handshake, which is where the device's
# 820-903 ms certificate-verify flight lands), `upgrade_ms` (the two bounded
# header reads) and `join_send_ms` (the `phx_join` SENDS, never the reply). It is
# the split the badge did not have: the whole establishment was one
# `push_moment ms=2413` line for a 2,252-2,436 ms rendered frame. `phase` is the
# leg a cancelled handshake died in and `outcome` is its terminal word, both
# short enums this package spells -- never server text.
#
# A FOURTH FIELD JOINED THE OPEN'S SPLIT ON 2026-08-24 (Lane J): `open_deadline_ms`,
# the inactivity ceiling THAT open was given. There are two of them now -- 9,000 ms
# for the first open of a link and 5,000 after it (the cold-boot allowance in
# `polltransport.COLD_OPEN_BUDGET_MS`) -- so `open_stall_ms` on its own stopped
# being enough to check a classification, because 6,000 is over one bar and under
# the other. It is also how a serial reader tells a COLD open from a warm one
# without counting `connecting` lines, which is the whole content of the arm-12
# re-run.
_CONNECT_ATTRIBUTION_FIELDS = (
    "ntp_ms", "resolve_ms", "pm_ms", "prepare_ms",
    "total_ms", "shim_ms", "build_ms", "start_ms", "worker_ms", "sleep_ms",
    "finish_ms", "updates", "outcome", "open_step_max_ms", "open_stall_ms",
    "open_deadline_ms", "open_span_ms", "open_busy_ms", "open_wait_ms",
    "open_steps", "open_frame_max_ms",
    "dns_ms", "connect_ms", "send_ms", "headers_ms", "body_ms", "other_ms",
    "tcp_ms", "ws_tls_ms", "upgrade_ms", "join_send_ms", "phase",
)

#: HOW MUCH OF AN ERROR TEXT REACHES THE SERIAL LINE. Bounded because `error` is
#: the ONE printed field that carries an exception's own words rather than a
#: number this module formatted, and an unbounded one would be a record dump with
#: extra steps. 120 characters comfortably holds every message the audit in
#: `badgelink/tests/test_ft_b_poll_cost.py::PrintedErrorTests` enumerates.
_PRINTED_ERROR_CHARS = 120

# WHY `error` IS ON THIS LIST, and it is the third time this exact defect has
# been found. `PollLoop._attempt_open` has emitted `error=` on `open_failed`
# since the transport was written, and neither whitelist carried it -- so a badge
# printing `event=open_failed open_ms=505` said WHAT it cost and never WHY, while
# the sentence that discriminates the causes was already being forwarded. That
# sentence is the whole diagnosis: `connect setup failed: OSError` is a name
# resolution, `open update failed: OSError` is the socket, `bad open response:
# PostgREST returned HTTP 5xx` is a server that answered and refused, and
# `open request exceeded the pump budget` is neither. `shift_s` was in this state
# until `f8222dbd`; the open's phase split was in it until 2026-08-23.
#
# IT IS SAFE TO PRINT, AND THAT IS AUDITED RATHER THAN ASSUMED. Every producer
# that can reach this field formats a FIXED string plus, at most, an HTTP status
# code, a setting NAME or an exception CLASS name -- never a value, never a body,
# never a URL, never a token (`postgrest`, `device_link`, `credentials`,
# `polltransport`). The test named above enumerates them and fails on a new
# producer that interpolates anything else.
#
# `due_ms` and `cached` JOINED IT FOR CX-8's TWO PHASE EVENTS. Each boot prints at
# most one `policy_phased` and one `schedule_phased` line, and the number on them
# is the whole observable difference between a fleet that phases its cadences and
# one that does not -- a device session reading a wall of `event=exchange` lines
# cannot otherwise tell "the request did not happen yet" from "the request is
# gone". Both are integers/booleans this module formatted.
#
# SIX FIELDS JOINED IT ON 2026-08-24, AND THAT WAS THE FOURTH RECURRENCE OF ONE
# DEFECT -- which is why the recurrence is now a TEST rather than a habit
# (`test_ft_b_poll_cost.EmittedFieldCensusTests`, and read it before adding an
# emitted field). The 2026-08-24 device session ran four CX arms whose written
# checks quote fields the badge could not print, and a check quoting a field that
# cannot appear reads as a failed arm:
#
# * `delay_ms` + `level` -- arm 5 (CX-5) is *"`backoff_jumped level=5`"* and
#   *"`backoff delay_ms=` in the 16,000-32,000 ms band"*. Both bands had to be
#   recovered from attempt-start timestamps instead, and the arithmetic that
#   recovery needs is the reason `docs/engineering-findings.md` now carries a
#   section on which EDGE a backoff delay is armed from.
# * `hosts` -- arm 7 (CX-3) is *"`addresses_invalidated reason=wifi_lost
#   hosts=`"*. It is a COUNT, `len(self._entries)` at `SessionAddresses.invalidate`
#   (never a hostname, never an address: see the audit in
#   `PrintedHostCountTests`), so it says HOW MANY cached addresses a WLAN edge
#   threw away and names none of them. Endpoint-free, like everything else here.
# * `misses` -- not named by an arm; found by the census above, in exactly the
#   `shift_s` state (forwarded for a probe, invisible on serial). `missed_ack` is
#   the line before every liveness teardown and the count is the whole content.
# * `status` + `filtered` -- arm 10 (CX-9) is *"read `event=ring_filtered status=
#   filtered=` -- TWO of them per command"* and *"their absence ... means the
#   filter is not running"*, so the unprinted pair would have booked a false
#   FAILURE for a fix that works. `status` is the one field here that arrives from
#   the server, and it is a short enum rather than free text BY CONTROL FLOW:
#   `PushLink._handle` emits `ring_filtered` only inside its `_is_own_ack` branch,
#   which is true only when the status is one of `pushlink.STATUS_QUIET`'s four
#   words. That is asserted, not assumed (`PrintedRingStatusTests`).
#
# THE TWO WHITELISTS MUST AGREE, and until 2026-08-24 nothing checked it: every
# field that reaches the service through `_on_backend_event` passes TWO filters,
# so a field on one list and not the other is invisible for the same reason a
# field on neither is. `_FORWARDED_FIELDS` is therefore a SUBSET of this tuple by
# assertion.
# `source` JOINED IT ON 2026-08-24 FOR THE REVOCATION LINES, and it is the one
# field here that exists to make a DUPLICATE readable rather than to add a
# measurement. Three objects emit `event=revoked` and all three are right (see
# `SOURCE_SERVICE` at the top of this module): two transports reach a terminal
# independently by design, and the service prints the boot-wide stop it adopts.
# Unprinted, the device session's two lines were 20 ms apart and identical apart
# from `reason=`, so arm 6's "no second `revoked`" failed a WORKING build. It is
# one of three literals THIS PACKAGE spells, so it is in the same category as
# `kind` and `moment` rather than `app` or `version`: never server text.
# `demote_after` JOINED IT ON 2026-08-26 WITH `sessions_joined`, and the pair is
# the verdict's own "2 of 3 vs 3 of 3" item. A `session_failed` line carrying
# only `failed_sessions` cannot say which side of the threshold the badge is on,
# and that threshold is the entire difference between a panel that reads
# "Connecting" forever and one that reads "Normal" -- the state an operator can
# act on. Both are integers this package owns.
# `scope` JOINED IT ON 2026-08-26 FOR THE FLEET RING FILTER, and it is the field
# that says WHICH filter suppressed a ring. The two are opposites -- the private
# topic's suppresses this badge's own provable echo, the fleet topic's suppresses
# every ring that does not positively name this hardware -- so a bare
# `ring_filtered filtered=N` on a shared channel cannot be told from the same
# line on a private one, and those two lines mean opposite things about whether
# the badge is working. Two words, both spelled in THIS package
# (`pushlink.ring_scope`), never server text.
# `discarded` JOINED IT ON 2026-08-27 WITH `wipe_scores`, and it is the only
# record that a wipe took anything: the ack goes to the backend, so a badge on a
# bench or a serial log has nothing else to read. `scope` was already here for the
# ring filter and carries the wipe's scope word for free -- the same two-word
# vocabulary rule applies, both spelled in THIS package. The number is an integer
# this package counted (`scorebox.pending`), never server text.
_PRINTED_FIELDS = ("kind", "ok", "busy_ms", "peak_ms", "span_ms", "steps",
                   "open_ms", "cadence_ms", "delay_ms", "level", "misses",
                   "hosts", "status", "filtered", "pumps", "moment", "ms",
                   "shift_s", "reason", "error", "due_ms", "cached",
                   "attempts", "failures", "source",
                   "scope", "demote_after", "discarded",
                   "sessions_joined",
                   # THE BATTERY LEVERS (2026-08-28), and all three are the ONLY
                   # record that survives the thing they describe. `action` and
                   # `seconds` are the last line a tethered operator gets before
                   # the badge stops printing entirely -- a dormant badge has no
                   # serial port, and waking is a full reboot, so an
                   # unprinted `sleeping` would make a deliberate fleet sleep and
                   # a fleet crash look identical on a log. `persist` is the
                   # difference between an off a reset undoes and one only a
                   # wearer can, which is the single most important thing to be
                   # able to read back after the fact.
                   "action", "seconds", "persist",
                   # THE FLEET SETTINGS (2026-08-29), and the same argument the
                   # battery levers make. `applied` is the only evidence that a
                   # five-minute read DID anything -- a `settings_applied` line
                   # with no number cannot tell an operator whose 2pm lever is not
                   # working whether the badge is reading the row and ignoring it
                   # or not reading it at all. `lever` names WHICH one refused,
                   # which matters because they are contained one at a time so
                   # that a mistyped brightness cannot disable the radio switch
                   # below it; without the word, `settings_lever_failed error=...`
                   # says something is wrong and not what. Both are integers or
                   # words THIS package spells (`_apply_settings`'s own ladder),
                   # never server text.
                   "applied", "lever",
                   ) + _CONNECT_ATTRIBUTION_FIELDS

#: WHAT REACHES THE SERVICE FROM EVERYTHING BEHIND IT. `_on_backend_event`
#: filters by key, so a field absent from this tuple is a field no probe and no
#: serial reader can see -- the poll loop, the doorbell, the device link, the
#: radio's edges and `SessionAddresses` ALL arrive through that one method.
#:
#: `shift_s` joined it for the connect-time clock resync: the seconds the wall
#: clock MOVED is the number a drifting fleet is diagnosed by. The poll-cost
#: fields joined it the same way -- `kind`/`ok`/`busy_ms`/`peak_ms`/`span_ms`/
#: `steps` are one `exchange`, `open_ms` is the handshake kept apart from it, and
#: `cadence_ms` says whether the test knob is holding the 3 s period, which
#: changes what every other number in the log means. The connect-attribution
#: fields joined it on 2026-08-23 for the reason both whitelists exist: `open_ms`
#: is one lump covering a name resolution, a TCP connect, a TLS handshake and our
#: own cooperative sleeps, and three separate explanations of a multi-second
#: launcher freeze all predict the same lump (see `_CONNECT_ATTRIBUTION_FIELDS`).
#: `hosts`, `status` and `filtered` joined it on 2026-08-24 with the printer:
#: they were dropped HERE first, one filter earlier than the defect that was
#: being fixed.
#: `source` joined it WITH the printer on 2026-08-24: two of the three `revoked`
#: emitters are behind this filter (the poll transport's and the doorbell's) and
#: only the service's is direct, so a `source` on the printer's list alone would
#: have left exactly the two lines that needed telling apart still identical.
#: `ms` JOINED IT ON 2026-08-24 FOR THE DOORBELL'S OWN ESTABLISHMENT COST. It
#: was on the printer's list alone and that was enough while its only producer
#: was `NetworkService._note_push_step`, which prints DIRECTLY; `PushLink`'s
#: `connected ms=` is behind this filter, so without this line the inner
#: bracket around `client.connect()` would have been invisible for exactly the
#: reason `hosts` was.
#: `scope` joined it WITH the printer on 2026-08-26: `ring_filtered` is
#: `PushLink`'s, so it arrives through this filter, and a `scope` on the
#: printer's list alone would leave the fleet filter exactly as unreadable as
#: `hosts` was.
_FORWARDED_FIELDS = (
    "reason", "delay_ms", "level", "misses", "hosts", "status", "filtered",
    "shift_s", "kind", "ok", "busy_ms", "peak_ms", "span_ms", "steps",
    "open_ms", "cadence_ms", "error", "attempts", "failures", "source", "ms",
    "scope", "demote_after", "sessions_joined",
) + _CONNECT_ATTRIBUTION_FIELDS


#: WHEN A `print` IS EVIDENCE THE PORT IS DEAD RATHER THAN SLOW. 250 ms, chosen
#: to sit in the empty middle of a bimodal distribution rather than to be a
#: percentile of anything:
#:
#: * a HEALTHY write is a memcpy into a 256 B TinyUSB FIFO -- microseconds;
#: * a BLOCKED one is pinned to the firmware's own constant.
#:   `MICROPY_HW_USB_CDC_TX_TIMEOUT` is 500 (`ports/rp2/mphalport.h:36`) and
#:   `mp_usbd_cdc_tx_strn` (`shared/tinyusb/mp_usbd_cdc.c:102-147`) spins
#:   `mp_event_wait_ms(1)` until 500 ms have passed with no byte accepted, then
#:   breaks. **`print(line)` makes TWO `mp_hal_stdout_tx_strn` calls** -- the
#:   string, then the newline -- and each gets its own fresh `last_write`, so ONE
#:   blocked `print` costs ~1,000 ms.
#:
#: The measured gap quanta agree to the millisecond and have no free parameter:
#: 1,017-1,030 / 2,013-2,027 / 3,032 ms across two independent arms is one, two
#: and three blocked prints (`benchmark/results/raw/2026-08-27-usb-cdc-print-blocking/`).
#: 250 ms is therefore ~2x above any healthy write including a GC pause landing
#: inside one, and 2x below the smallest possible blocked one.
_SINK_SLOW_MS = 250

#: HOW MANY CONSECUTIVE SLOW WRITES BEFORE THE SINK GOES QUIET. Two, because one
#: is not a pattern and the cost of being wrong is only lost telemetry -- there
#: is no state, no queue and no wearer-visible behaviour behind this printer.
#: Two also bounds the damage: the trip costs three blocked writes once (the two
#: that count, plus the notice below, which is itself a `print` into the same
#: dead port), so ~3 s at boot against ~1 s per event for the rest of the boot.
_SINK_SLOW_LIMIT = 2

#: THE SCOPE THIS FIX DOES NOT CLAIM, and it belongs beside the constants because
#: a reader who trusts the wrong half will mis-triage the next freeze report.
#:
#: The block requires a host to have ASSERTED DTR AND THEN GONE AWAY -- a serial
#: session opened, then the cable pulled. The firmware says why: `tud_cdc_write`
#: is limited to `tud_cdc_write_available()` **only when `tud_cdc_connected()`**,
#: i.e. only while DTR is up; with DTR down the same loop writes the whole string
#: into an overwriting FIFO and returns immediately. Closing the port first
#: measured ~2 gaps/min against ~24. **So a badge that has NEVER been tethered
#: may not block at all.**
#:
#: This is a HARDENING FIX AGAINST A MEASURED FAILURE MODE, NOT A PROVEN
#: EXPLANATION OF THE OWNER'S FIELD SYMPTOM. The effect is measured; no arm has
#: yet timed a single `print` directly, which is the probe that would settle it.
#: The evidence README overstates the DTR half: production now ships this module
#: under `/system/lib`, but the field claim still needs the connected-versus-
#: disconnected distinction above. A badge that has never raised DTR may never
#: enter the measured slow-write path.
_sink_slow_writes = 0
_sink_muted = False


def _print_event(record):
    # Fields are deliberately credential-free and endpoint-free.
    #
    # THE SELF-DISABLING SINK. This is the DEFAULT event sink -- `install()`
    # hardcodes it and takes no override -- and `_emit` fires hardest on connect,
    # retry and backoff, exactly the paths a wearer walking in and out of range
    # hits. See `_SINK_SLOW_MS` above for the 500 ms / two-writes arithmetic and
    # for what this fix does NOT claim.
    global _sink_slow_writes, _sink_muted
    if _sink_muted:
        # Muted BEFORE the line is built, so a quiet sink costs one global read
        # and not a formatted string nobody will ever see.
        return
    line = "BADGELINK_NETWORK event={} state={}".format(
        record.get("event", "-"), record.get("state", "-"))
    for name in _PRINTED_FIELDS:
        if name in record:
            value = record[name]
            if name == "error" and isinstance(value, str):
                value = value[:_PRINTED_ERROR_CHARS]
            line += " {}={}".format(name, value)
    started = _ticks_ms()
    print(line)
    # The whole healthy-path cost of this feature: two clock reads and an integer
    # subtraction. `_ticks_diff` returns a small int, so nothing here allocates.
    elapsed = _ticks_diff(_ticks_ms(), started)
    if elapsed < _SINK_SLOW_MS:
        _sink_slow_writes = 0
        return
    _sink_slow_writes += 1
    if _sink_slow_writes < _SINK_SLOW_LIMIT:
        return
    _sink_muted = True
    # ONE LAST LINE, and it is the last thing this sink ever prints. A tethered
    # operator who reattaches sees the transition and a reason rather than a
    # mystery silence; `ms=` is the evidence, because ~1,000 ms is the timeout
    # signature and 300 ms would be a slow terminal. The mute is PER BOOT and is
    # not re-armed by a fast write: re-arming would require probe prints, which
    # are the ~1,000 ms stalls this exists to remove, and the FIFO drains
    # partially on every timeout break, so a fast probe is not evidence the host
    # is back. HOME resets the MCU and an app switch is a new boot, so a bench
    # badge recovers telemetry with one reset.
    print("BADGELINK_NETWORK event=serial_muted state={} reason=usb_cdc_blocked"
          " ms={}".format(record.get("state", "-"), elapsed))


def install(backend_factory=None, preference_path=network_preference.DEFAULT_PATH,
            ledger_path=command_ledger.DEFAULT_PATH, run_function=None,
            badge_api=None, rtc_device=None, push_factory=None,
            card_state_path=None, open_app_path=None, display_api=None,
            schedule_path=None, score_path=None, schedule_cache_path=None,
            watchdog_factory=None):
    """Install once and return the singleton exposed to Settings."""

    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    if run_function is None:
        run_function = getattr(builtins, "run", None)
    if badge_api is None:
        badge_api = getattr(builtins, "badge", None)
    if not callable(run_function):
        raise ValueError("Badgeware run function is required")
    if backend_factory is None:
        def backend_factory(command_sink, event_sink):
            return DeviceBackend(command_sink, event_sink, rtc_device)
    caselights = getattr(badge_api, "caselights", None)
    # `display.backlight(level)` is the panel brightness call, verified against
    # the pinned firmware: `st7789_bindings.c` maps Python `backlight` onto
    # `set_backlight`, and `st7789_bindings.cpp` reads it as a FLOAT and
    # multiplies by 255 -- so 0..1 is the contract and an int 255 truncates to
    # nearly-off. There is no `badge.backlight`.
    #
    # `display_api` MUST BE PASSED, not read off `builtins`: MicroPython-injected
    # builtins participate in normal name resolution but `getattr(builtins,
    # "display", None)` bypasses the override dictionary in the pinned runtime
    # (recorded in docs/engineering-findings.md, found the same way for
    # `screen`). A badge whose main.py block predates this argument gets
    # `set_backlight` -> failed ack and everything else unchanged, which is why
    # the whole feature degrades to one verb rather than to a boot failure.
    backlight = getattr(display_api, "backlight", None)
    if not callable(backlight):
        backlight = None
    service = NetworkService(
        backend_factory,
        preference_path=preference_path,
        ledger_path=ledger_path,
        caselights=caselights,
        event_sink=_print_event,
        push_factory=push_factory,
        card_state_path=card_state_path,
        open_app_path=open_app_path,
        backlight=backlight,
        badge_api=badge_api,
        schedule_path=schedule_path,
        score_path=score_path,
        schedule_cache_path=schedule_cache_path,
    )
    # Arm on the first rendered frame, not during early boot. The first-wake
    # ceremony runs in the launcher's module body before `run()` and legitimately
    # takes about nine seconds; starting a 16-second watchdog before it would
    # leave an unnecessary narrow margin for app discovery. Index 0 distinguishes
    # "not attempted" from a supported fail-open result of None.
    watchdog_slot = [False, None]
    original_run = run_function

    def managed_run(update, *args, **kwargs):
        wrapper_bounded = "duration" in kwargs
        # OWNER RULING #22 placement: resolve the launcher-vs-app run context
        # ONCE here, not per rendered frame. This wraps every `run(...)`, and a
        # `run()` call is one app for its whole life (an app switch is a new
        # boot). Cold OFF's `enter_run_context` is a no-op, so the launcher's
        # legacy always-connect behaviour is byte-for-byte unchanged.
        service.enter_run_context()

        def managed_update():
            if not watchdog_slot[0]:
                watchdog_slot[0] = True
                watchdog_slot[1] = _start_runtime_watchdog(watchdog_factory)
            watchdog = watchdog_slot[1]
            # Feed from the frame pump, never an interrupt: the confirmed fault
            # stops rendered frames but may leave interrupts alive. The second
            # feed below gives networking its own full recovery window.
            if watchdog is not None:
                watchdog.feed()
            # Badgeware's launcher returns the selected app path from its
            # update callback. ``run`` preserves that value in ``.result`` and
            # /system/main.py launches it. Dropping the return here makes a
            # selected tile merely flash while the launcher keeps running.
            result = update()
            if watchdog is not None:
                watchdog.feed()
            # OWNER RULING #22 exit-frame: a non-None app result is the final
            # frame before the hard reset an app exit performs, so a parked
            # establishment may not advance or SEND into it (spec §5.3(e)). The
            # placement predicate scopes this to `not at_launcher`, so the
            # launcher's own selection -- a same-boot handoff, no reset -- is not
            # treated as an exit. OFF ignores the argument entirely.
            service.poll(exit_frame=result is not None)
            if result is None:
                # THE WEARER ALWAYS WINS. A non-None result is the launcher's own
                # selection (or an app deciding to exit) and is never overridden;
                # only an idle frame can carry an `open_app` target. Card FT-B
                # item 1's "menu-instant via the launcher-return mechanism" is
                # exactly this line.
                result = service.launch_result(wrapper_bounded)
            return result

        # A TIME-BOXED ``run`` IS A GATE, and the seam can see it without being
        # told: ``run(intro_update, duration=intro_ms)`` is how the firmware and
        # the supervisor both express "this loop is a bounded, non-interactive
        # phase". Nothing bounded can afford the 735 ms WS handshake, so push is
        # quiesced for its whole length and intro-end becomes the tolerant
        # moment (card item 7a/7b) with no cooperation required from
        # /system/main.py. The transport keeps being SERVICED throughout — this
        # gate stops connects, not heartbeats.
        bounded = wrapper_bounded
        if not bounded:
            return original_run(managed_update, *args, **kwargs)
        service.quiesce("bounded_run")
        try:
            return original_run(managed_update, *args, **kwargs)
        finally:
            service.resume()

    builtins.badgelink_network = service
    builtins.run = managed_run
    _SERVICE = service
    # BEFORE the launcher's first frame and before anything is launched, so a
    # target that fails to import costs one reset rather than a loop. Contained:
    # a note is a convenience and may never be the reason a boot has no network.
    try:
        service.adopt_open_note()
    except Exception as error:
        print("BADGELINK_NETWORK open_note=skipped error={}".format(
            error.__class__.__name__))
    print("BADGELINK_NETWORK installed=1 enabled={} state={}".format(
        1 if service.enabled else 0, service.state))
    return service
