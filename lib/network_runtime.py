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
_PULSE_MS = 3000
# How often a frame may read the wall clock while something is scheduled. ONE
# SECOND: a moment 800 badges share to the second needs no finer resolution, and
# `time.time()` every frame would be a syscall per frame for nothing.
_SCHEDULE_TICK_MS = 1000

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

# `polltransport.POLICY_REFRESH_MS` and its boot-phase floor, spelled here for the
# same reason `CONNECTED` is: this module installs to `/system/lib` and runs from
# `/system/main.py` before any app, so a module-scope import of a sibling a
# half-refreshed lib might not carry would take the boot down. The service owns
# the PHASE of the steering read (`arm_policy`) because it outlives every loop it
# builds; the loop owns the interval. Pinned against the real constants by
# `badgelink/tests/test_network_runtime.py`.
POLICY_REFRESH_MS = 300000
POLICY_FIRST_MIN_MS = 60000

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

    AN ABSENT OR EMPTY PAYLOAD IS THE DEFAULT SCOPE. `badge_commands.payload` is
    nullable and a hand-queued row is routinely `{}`, so requiring the key would
    fail the most ordinary way to send this command, for a reason nobody could
    read off the ack. Naming the scope explicitly is still the documented shape.
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
    some badge's `machine.unique_id()`, that badge's `badge_state` row, its
    command queue and the floor's would be the same row: revoking the fleet grant
    would revoke that badge's own tier, and its `_self` writes would collide with
    the floor identity the claim RPCs are required to refuse.

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
                 open_app_path=None, listdir=None, getcwd=None,
                 backlight=None, badge_api=None, schedule_path=None,
                 epoch_clock=None, score_path=None,
                 schedule_cache_path=None, reset=None, rand01=None,
                 ticks_ms=None):
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
        # itself minutes later to a wearer who had forgotten it. `open_app` is
        # durable for the opposite reason -- it is an instruction, not a moment.
        self._lights = None
        self._lights_started = 0
        # The running FLEET EFFECT, in its own slot for the reason
        # `effect_library.EffectPlayer` gives: it drives two channels and answers
        # a bool, where a `Program` drives one and answers a level, so sharing the
        # slot above would put a type switch in the frame pump. RAM-only for the
        # same reason as the lights program -- a show is a moment.
        self._effect = None
        self._effect_started = 0
        self._backlight = backlight
        # The `badge` object, for the battery gauge `report_state` samples. The
        # caselights callable stays a separate argument because Card PW's
        # fixtures inject it directly and nothing may break that.
        self._badge_api = badge_api
        self._boot_session_id = None
        self._schedule_path = schedule_path
        self._epoch_clock = epoch_clock
        # DURABLE, unlike the light program: a moment somebody planned has to
        # survive the reset that a HOME press causes on the way to it.
        self._schedule = self._load_schedule(schedule_path)
        self._schedule_checked = None
        self._score_path = score_path
        self._scorebox = None
        self._score_inflight = None
        # THE FAILURE COUNT IS ONE PAIR, NOT A MAP, and that is a leak fix rather
        # than a simplification. Only the HEAD of the spool is ever drained, so a
        # map is never larger than one entry in the healthy case -- but a key
        # could linger in it forever: the head fails twice, the spool fills, and
        # `record`'s FIFO compaction drops that very entry, leaving nothing to pop
        # its counter. One pair cannot leak, because a head change resets it.
        #
        # Per BOOT and in RAM either way: see scorebox.MAX_ATTEMPTS for why
        # persisting it would buy a file write per failure and nothing else.
        self._score_attempt_key = None
        self._score_attempts = 0
        # A DELIVERED SCORE IS RETIRED ON A LATER FRAME. The sink that hears
        # "posted" only remembers the key; the whole-file read and the atomic
        # swap that retiring costs are this service's one expensive sub-task for
        # some later frame. See `_pump_scores`.
        self._score_retire = None
        self._score_retire_posted = False
        self._schedule_cache_path = schedule_cache_path
        self._schedule_box = None
        self._schedule_inflight = False
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
        self._event_sink = event_sink
        # ONE READ FOR BOTH SWITCHES (CX-10 sub-claim 1). This used to be
        # `load()` then `load_push()`, and each of those calls `load_record`, so
        # the preference file was opened and DECODED TWICE before the launcher's
        # first frame -- two of the constructor's three decodes for one 45-byte
        # record. The two flags still default the opposite ways (OFF for the
        # radio, ON for push: see `network_preference`'s module note) and
        # `enabled_from`/`push_from` keep that asymmetry where it belongs.
        preference = network_preference.load_record(preference_path)
        self._enabled = network_preference.enabled_from(preference)
        # DEFAULT ON, with automatic demotion (owner scope addition 2026-08-21).
        self._push_enabled = network_preference.push_from(preference)
        self._push_control = None
        self._policy = None
        #: WHEN THE STEERING READ IS NEXT DUE, owned HERE and not on the loop
        #: (CX-8). This object outlives every backend and every `PollLoop` it
        #: builds, so a wearer toggling networking off and on -- or a backend
        #: rebuilt after a fault -- cannot restart a 5-minute interval that was
        #: served thirty seconds ago. `None` means "not phased yet"; the first
        #: backend build draws the phase and arms the loop through
        #: `DeviceBackend.set_policy_due`. RAM-only, like the loop's own copy: a
        #: cadence is not a thing to carry across a reset (nothing durable could
        #: tell a boot the interval was served, which is exactly CX-8's finding).
        self._policy_due = None
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
        self._pulse_until = None
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
        # BEFORE THE FLAG FLIPS, because the flip is what makes the cause
        # unknowable: `push_cause` reads `_enabled` first and answers None from
        # here on, and `poll` stops reaching `_note_push_cause` entirely. This is
        # the last instant the answer exists. See `_latch_cause_at_switch`.
        if not enabled:
            self._latch_cause_at_switch()
        else:
            self._clear_cause_latch()
        self._enabled = enabled
        self._emit("preference", enabled=enabled)
        if not enabled:
            self._retry_at = None
            self._failures = 0
            self._stop_backend()   # closes the doorbell's socket with it
            self._caselights(0)
            self._pulse_until = None
            # A RUNNING SHOW STOPS WITH THE RADIO. `_pump_effect` runs before the
            # `_enabled` check in `poll`, so a light program left set here would
            # keep driving the LEDs after the wearer switched networking off --
            # the one effect in this module that outlives its own cause.
            self._lights = None
            # AND A DELIVERED SCORE IS RETIRED BEFORE THE RADIO GOES, because its
            # retire is a DEFERRED sub-task and `poll` returns before the drain
            # once networking is off. Left pending, the row would be reposted on
            # the next boot -- harmless (the RPC is idempotent) and still wrong.
            # Not a frame: this is a wearer or probe action, and it is the same
            # moment that already writes the preference file.
            self._chore_spent = False
            self._retire_score()
        elif not self._revoked:
            # The Settings frame showing CONNECTING must reach the panel before
            # any DNS/TLS work begins.  The wrapper consumes this one deferral.
            self._defer_once = True
        return self._enabled

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
                # THE STEERING READ'S PHASE, ARMED BEFORE THE FIRST OPEN (CX-8).
                # Duck-typed exactly like the sink above, so a backend shape that
                # predates the seam keeps the old session-start behaviour. Armed
                # here rather than in `__init__` because a badge whose networking
                # is OFF should not be holding a cadence phase at all.
                self._arm_policy_phase(now)
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
            # MIRROR THE LOOP'S STEERING DUE (CX-8, corrected 2026-08-23). The
            # loop advanced it if it issued a request or heard steering in the
            # call above, and this object is the only one that survives the loop
            # being rebuilt -- so it carries the answer and never invents one.
            self._mirror_policy_due()
            # PollLoop marks itself active when a command arrives.  The app
            # foreground is the lasting authority; pending acks remain urgent
            # because queue_ack already pulled their deadline to "now".
            self._backend.set_active(self._active)
            self._failures = 0
            if getattr(self._backend, "state", None) == REVOKED:
                self._revoked = True
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
            "scheduled": len(self._schedule.get("held", ())),
            "scores_pending": self._score_pending(),
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
                # OWNER RULING #22: the hourly reauthorization is itself a NEW
                # establishment (it closes the healthy WSS and reopens), so it
                # defers out of a non-opted-in app too -- a minute-60 close with
                # no re-open allowed would strand a mid-app command on a link
                # that was healthy right up to the close. A TRUE token/grant
                # expiry still fails CLOSED: that is a security boundary the
                # push side owns and placement must not veto. Duck-typed setter,
                # consumed inside the pumped session step; a push seam that
                # predates it is simply never deferred.
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
            result = self._dispatch(command)
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
        self._backend.queue_ack(ack)
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

    def _load_schedule(self, path):
        """Held commands, or an empty hold.  Contained, like every other lazy
        /system/lib import in this module: a boot may not fail over a moment.

        Runs from ``__init__`` BEFORE ``last_error`` exists, so the failure is
        deliberately silent rather than recorded: setting the attribute here
        would only have it overwritten with ``None`` two lines later, which is a
        worse lie than saying nothing.

        THE MODULE IS KEPT, because `_pump_scheduled_commands` runs once per
        rendered frame and an `import` in its body is a `__import__` call and its
        allocations on every one of them. Same rule as `_score_box` and
        `_schedule_store`: resolve the lazy import once, then hold it.
        """
        self._held_box = None
        try:
            import command_schedule

            self._held_box = command_schedule
            return command_schedule.load(path)
        except Exception:
            return {"held": []}

    def _dispatch(self, command):
        """`execute_at` first, then the applier (Card FT-B item 2).

        THE SPLIT IS HERE rather than inside `_apply` so that every verb gets the
        same scheduling semantics for free -- which is the whole growth rule: a
        new command is one CHECK plus one applier, and it inherits `execute_at`
        without knowing the word.
        """
        import command_schedule

        when, verdict = command_schedule.due_at(command, self._epoch())
        if verdict == "now":
            return self._apply(command)
        if verdict == "unreadable":
            raise ValueError("execute_at is not a timestamp this badge can read")
        if verdict == "no_clock":
            # REFUSED, not applied early. A scheduled moment the badge cannot
            # time is a moment it would get wrong, and the operator can see the
            # failed ack and re-queue it once the badge has a clock.
            raise ValueError("this badge has no trusted clock to schedule against")
        if verdict == "far":
            raise ValueError(
                "execute_at is more than {} hours away".format(
                    command_schedule.MAX_HORIZON_S // 3600))
        # A FUTURE MOMENT. Validate the payload NOW by asking the applier to
        # check it, so a malformed scheduled command fails visibly at the moment
        # it is queued rather than silently minutes later in front of a room.
        self._precheck(command)
        command_id = command.get("id")
        state = command_schedule.hold(
            self._schedule, command_id, command.get("type"),
            command.get("payload") or {}, when)
        command_schedule.save(state, self._schedule_path)
        self._schedule = state
        self._emit("command_scheduled", command=command.get("type"))
        # `applied` because the ack vocabulary has no "accepted, not yet applied"
        # status (the CHECK accepts exactly applied/failed), so the honest signal
        # is in the RESULT. FT-W reads `applies`.
        return {"effect": "scheduled", "applies": "scheduled",
                "execute_at": command.get("execute_at"), "at_epoch": when,
                "held": len(state["held"])}

    def _precheck(self, command):
        """Reject a payload the applier could never accept, without applying it.

        Cheap and deliberately incomplete: it re-runs the pure validators the
        appliers use and does nothing that touches hardware or the filesystem. A
        verb with no pure validator is accepted here and adjudicated when it
        fires -- which is the same answer an unscheduled command gets, just
        later.
        """
        command_type = command.get("type")
        payload = command.get("payload")
        if command_type == "set_lights":
            import caselight_program

            caselight_program.parse(payload)
            return True
        if command_type == "set_name":
            import setup_state

            if (not isinstance(payload, dict)
                    or tuple(payload.keys()) != ("name",)
                    or not setup_state.valid_name(payload["name"])):
                raise ValueError("set_name payload requires exactly one name key")
            return True
        if command_type == "set_skin":
            import setup_state

            if (not isinstance(payload, dict)
                    or tuple(payload.keys()) != ("skin",)
                    or setup_state.resolve_skin(payload["skin"]) is None):
                raise ValueError("set_skin payload requires exactly one skin key")
            return True
        if command_type == "report_state":
            if not isinstance(payload, dict) or payload:
                raise ValueError("report_state takes no arguments")
            return True
        if command_type == "wipe_scores":
            # PURE, so a scheduled wipe with an unreadable scope fails at QUEUE
            # time rather than hours later at fire time, where the only record of
            # it is a serial line nobody is watching.
            _wipe_scope(payload)
            return True
        return True

    def _epoch(self):
        """The NTP-synced wall clock, or ``None`` when it is not trustworthy.

        `clock_boot`'s build-floor/ceiling gate is the same one the transport
        already uses before opening a socket, reused here so a badge that never
        reached NTP HOLDS a scheduled command instead of firing it in 2021.
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
            # and refusing every scheduled command would be worse than trusting
            # the same value the TLS handshake already trusts.
            pass
        return candidate

    def _pump_scheduled_commands(self, now):
        """Fire whatever is due.  Called once per frame; usually one `if`.

        ALLOCATES NOTHING IN THE STEADY CASE: `next_due` is `held[0]` and the
        common answer is `None`. The wall clock is read only when something is
        actually waiting, and then no more often than once a second -- a moment
        the fleet shares to the second does not need millisecond resolution, and
        `time.time()` every frame would be a syscall per frame for nothing.

        AND IT RESOLVES NO IMPORT. This body used to open the held-command module
        itself, which is a `__import__` call plus its allocations on every
        rendered frame; `_load_schedule` holds the module now (Card FT-B, F21).
        `test_ft_b_frame_budget` greps this body for the statement, and prose
        naming it would fire that guard -- the same way FT-S's column guard fired
        on a comment, which is a feature and not a false positive.
        """
        box = self._held_box
        if box is None:
            return None
        entry = box.next_due(self._schedule)
        if entry is None:
            return None
        if self._schedule_checked is not None and _ticks_diff(
                now, self._schedule_checked) < _SCHEDULE_TICK_MS:
            return None
        self._schedule_checked = now
        epoch = self._epoch()
        if epoch is None:
            return None
        verdict = box.fire_verdict(entry["at"], epoch)
        if verdict == "wait":
            return None
        # The rest of this path drops/saves durable schedule state and may apply
        # a physical or filesystem effect. It runs before backend polling, so no
        # response sink can raise the usual barrier for it; raise that same
        # one-frame exclusion here before any work or error. Otherwise a held
        # WSS task can stack its 820-903 ms TLS flight onto this save/effect.
        self._response_continuation = True
        # DROPPED FROM THE FILE BEFORE THE EFFECT, and for the same reason the
        # open-app note is: an effect that raises must not be retried on the next
        # frame forever. The ledger already carries the ack.
        self._schedule = box.drop(self._schedule, entry["id"])
        try:
            box.save(self._schedule, self._schedule_path)
        except Exception as exc:
            # THE ENTRY IS STILL ON DISK, so firing now would fire AGAIN after the
            # next reset -- and this path calls `_apply` directly, so the command
            # ledger cannot deduplicate it. Not firing is the safe direction: the
            # RAM drop means this boot does nothing, and the next boot fires it
            # once or discards it as stale.
            self.last_error = _error_text(exc)
            self._emit("command_hold_stuck", command=entry["type"])
            return "deferred"
        if verdict == "stale":
            # The moment passed while the badge was off. Firing a synchronized
            # light show minutes late is worse than not firing it.
            self._emit("command_stale", command=entry["type"])
            return "stale"
        try:
            # THE LATENESS IS MEASURED HERE BECAUSE THIS IS THE ONLY PLACE THAT
            # KNOWS IT. `fire_verdict` has already ruled this inside
            # `MAX_LATE_S`, so the subtraction is bounded by 120 s and cannot be
            # negative (a `when > now_epoch` row returned "wait" above). Wall
            # clock, not ticks: the fleet's shared instant is an epoch second and
            # `ticks_ms` has no meaning across two badges.
            self._apply({"id": entry["id"], "type": entry["type"],
                         "payload": entry["payload"]},
                        skew_ms=int((epoch - entry["at"]) * 1000))
            self._emit("command_fired", command=entry["type"])
            return "fired"
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("command_fire_failed", command=entry["type"],
                       error=self.last_error)
            return "failed"

    def _apply(self, command, skew_ms=0):
        """One command -> one physical effect, or a raise the caller turns into a
        failed ack.

        ``skew_ms`` IS HOW LATE THIS COMMAND IS, and only the SCHEDULED path can
        pass a nonzero one. It exists for `play_effect`: a fleet show has to end
        together even when one badge fired 90 seconds behind the others, so the
        lateness starts that badge that far INTO the effect rather than running a
        full-length show alone. Every other applier ignores it, which is why it is
        a defaulted keyword rather than a required argument -- the immediate path
        (`_on_command`) has no lateness to report and should not have to say so.
        """

        command_type = command.get("type")
        payload = command.get("payload")
        if command_type == "find_badge":
            self._lights = None       # a running show yields to "where is it?"
            # AND SO DOES A FLEET EFFECT, for the stronger version of the same
            # reason: "where is my badge" is a person in a room looking for a
            # thing, and a light show is decoration. `interrupt` restores the
            # panel to its base level on the way out, so the effect cannot leave
            # the backlight parked where its last frame happened to put it.
            self._preempt_effect()
            self._caselights(1.0)
            self._pulse_until = _ticks_add(self._now, _PULSE_MS)
            return {"effect": "caselight_pulse"}
        if command_type == "set_caselights":
            if not isinstance(payload, dict) or not isinstance(payload.get("on"), bool):
                raise ValueError("set_caselights payload requires boolean on")
            self._lights = None       # an explicit on/off outranks a program
            self._preempt_effect()   # and outranks a fleet show
            self._pulse_until = None
            self._caselights(1.0 if payload["on"] else 0)
            return {"effect": "caselights", "on": payload["on"]}
        if command_type == "set_lights":
            return self._apply_set_lights(payload)
        if command_type == "set_backlight":
            return self._apply_set_backlight(payload)
        if command_type == "report_state":
            return self._apply_report_state(payload)
        if command_type == "set_name":
            return self._apply_set_name(payload)
        if command_type == "set_skin":
            return self._apply_set_skin(payload)
        if command_type == "open_app":
            return self._apply_open_app(payload)
        if command_type == "wipe_scores":
            return self._apply_wipe_scores(payload)
        if command_type == "play_effect":
            return self._apply_play_effect(payload, skew_ms=skew_ms)
        raise ValueError("unsupported command type: {}".format(command_type))

    # -- the setup appliers (Card FT-B item 1) -------------------------
    #
    # NEXT-OPEN SEMANTICS, which is the owner's 2026-08-22 ruling and not a
    # limitation of this seam: the write lands now and setup reads it the
    # next time it opens. A LIVE refresh of a running card is a flagged hook in
    # `setup_state`, OFF behind the battery gate, with the measured cost of
    # an unrequested mid-session repaint recorded at the flag.
    #
    # THE PAYLOAD VALIDATION MIRRORS THE DB CHECK EXACTLY, because the constraint
    # is the boundary and the applier is the courtesy: a badge that rejected a
    # payload the constraint accepted would leave a queued row that can never
    # succeed, and the queue would look healthy.
    #
    # NO FLEET SKIN (the ruling). Nothing is enforced here, and that is honest
    # rather than lax: every `badge_commands` row is addressed to ONE badge_id, so
    # a badge cannot tell a fleet push from a per-badge one and has nothing to
    # refuse. The rule lives where the fan-out would be written -- the console.

    def _card_state(self):
        """Import the state contract LAZILY, per the module docstring's rule.

        `setup_state` installs to /system/lib beside this file, so a
        module-scope import would make a half-refreshed lib take the BOOT down
        rather than one command. A missing module is a failed ack.
        """
        import setup_state

        return setup_state

    def _apply_set_name(self, payload):
        # `payload = jsonb_build_object('name', payload -> 'name')` in the CHECK
        # is an EXACTLY-ONE-KEY test, so an extra key is a rejection here too.
        if not isinstance(payload, dict) or tuple(payload.keys()) != ("name",):
            raise ValueError("set_name payload requires exactly one name key")
        contract = self._card_state()
        result = contract.set_name(payload["name"], self._card_state_path)
        contract.live_refresh(path=self._card_refresh_path)
        record = {"effect": "card_name", "stored": result["stored"],
                  "applies": "next_open"}
        if result["truncated"]:
            # The 64-character constraint bound and setup's 12-character cap
            # are both real; saying so is better than a silent difference.
            record["truncated"] = True
        return record

    def _apply_set_skin(self, payload):
        # NO PAYLOAD CHECK EXISTS for set_skin (Card FT-S extended the vocabulary
        # and left this verb's payload to the generic object rules), so this is
        # the whole boundary rather than a mirror of one.
        if not isinstance(payload, dict) or tuple(payload.keys()) != ("skin",):
            raise ValueError("set_skin payload requires exactly one skin key")
        contract = self._card_state()
        result = contract.set_skin(payload["skin"], self._card_state_path)
        contract.live_refresh(path=self._card_refresh_path)
        return {"effect": "card_skin", "stored": result["stored"],
                "applies": "next_open"}

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
        # A light show and find_badge's 3 s pulse are the same four LEDs, so the
        # newer intent wins outright rather than the two fighting per frame.
        self._pulse_until = None
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

    def _apply_play_effect(self, payload, skew_ms=0):
        """§A's fleet-show primitive: one console press, 800 badges, one instant.

        **THE LIBRARY LANDED WITHOUT THIS APPLIER AND NOTHING NOTICED FOR A DAY.**
        `effect_library` is complete, tested and frozen -- its own `player_for`
        docstring says "which is what the applier calls" and describes how
        `_on_command` turns its raise into a failed ack -- but no dispatch entry
        existed, so `_apply` fell through to `unsupported command type` and a
        frozen fleet would have FAIL-ACKED every `play_effect` the backend ever
        queued. The gap read as done because a design doc described it and a
        hand-built test service exercised it; the seam between the two lanes is
        where it fell through. Nothing here is new behaviour -- it is the missing
        hop between a landed library and a landed queue.

        ALL VALIDATION IS THE LIBRARY'S, deliberately. `parse` mirrors the CHECK
        constraint clause for clause, including the "test for the KEY before
        reading it" rule a real Postgres taught `caselight_program`; duplicating
        any of it here would be a second boundary to keep in step, and the one
        thing worse than a payload the badge refuses is one the badge and the
        database disagree about.

        A RAISE IS THE FAIL-ACK, which is the ladder's existing contract and the
        only safe answer to a fleet fan-out: an unknown kind or an id this
        firmware does not carry means "half the fleet is on older firmware", and
        an operator needs to read that off a failed ack rather than watch some
        badges guess.

        THE PANEL BASE IS READ, NOT ASSUMED. A `kind: "glyph"` effect drives the
        backlight and must hand it back where the wearer left it, so the player is
        given the current level rather than a constant -- otherwise a show ends by
        resetting every badge in the room to full brightness.
        """

        # IMPORTED IN THE METHOD, exactly as `_apply_set_lights` imports
        # `caselight_program`: this module installs to `/system/lib` and runs from
        # `/system/main.py` before any app, and a module-scope import of a sibling
        # a half-refreshed lib might not carry would take the boot down.
        import effect_library

        # PARSED BEFORE THE OLD SHOW IS TOUCHED. `player_for` raises on a bad
        # payload, and a raise here is a failed ack -- so a malformed command must
        # not have already stopped a good effect that was running.
        player = effect_library.player_for(
            payload, skew_ms=skew_ms, panel_base=self._panel_base)
        # ONE SHOW AT A TIME, AND THE OLD ONE IS RETIRED PROPERLY. `interrupt`
        # restores both channels; dropping the reference would leave the panel and
        # the case lights wherever the previous effect's last frame put them.
        self._preempt_effect()
        self._pulse_until = None   # a show outranks find_badge's 3 s pulse
        self._lights = None        # and outranks a caselight program
        self._effect = player
        self._effect_started = self._now
        # ONE WRITE NOW, the same courtesy `_apply_set_lights` pays: an operator
        # pressing the button sees the first frame rather than waiting for the next
        # rendered frame. `step(0)` is the frame at the SKEWED phase, because
        # `player_for` already seated the player that far into the effect.
        if player.step(0):
            self._write_effect_levels(player)
        if player.done:
            # A show whose skew consumed all but the last instant. `player_for`
            # refuses a skew at or past the duration, so this is the narrow band
            # just inside it; parking it would leave the pump stepping a finished
            # player every frame.
            self._effect = None
        # THE ACK SHAPE IS THE HARNESS'S, not this file's invention: the
        # library's contract tests already model these five fields, and a console
        # reading a different set from a real badge than from the harness would
        # make the harness worthless as a contract.
        return {"effect": "play_effect", "kind": player.kind,
                "id": player.effect_id, "duration_ms": player.duration_ms,
                "skew_ms": player.skew_ms, "panel": player.panel_active}

    def _preempt_effect(self):
        """Stop a running fleet effect and put both channels back. Total.

        Called from the frame pump's neighbours and from two appliers, so it may
        not raise: `_apply` is reached from `_pump_scheduled_commands`, which runs
        before backend polling on the frame path.
        """

        player = self._effect
        if player is None:
            return False
        self._effect = None
        try:
            if player.interrupt():
                self._write_effect_levels(player)
        except Exception as exc:
            self.last_error = _error_text(exc)
            self._emit("effect_contained", error=self.last_error)
        return True

    def _write_effect_levels(self, player):
        """Push whichever of the two channels moved. Nothing else."""

        if player.case_level is not None:
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
        # `payload = jsonb_build_object('level', payload -> 'level')` -- exactly
        # one key -- plus the 0.1..1 range. The constraint's regex is a CAST
        # GUARD (its own comment says so), so the RANGE is what is mirrored here;
        # a badge that additionally demanded three decimal places would reject a
        # payload the database accepted.
        if not isinstance(payload, dict) or tuple(payload.keys()) != ("level",):
            raise ValueError("set_backlight payload requires exactly one level key")
        level = payload["level"]
        if isinstance(level, bool) or not isinstance(level, (int, float)):
            raise ValueError("set_backlight level must be a number")
        if level != level or level * 0 != 0:
            raise ValueError("set_backlight level must be finite")
        # THE 0.1 FLOOR IS THE CONSTRAINT'S AND IT IS NOT AN ACCIDENT: a dark
        # panel is indistinguishable from a dead badge to its wearer, and this is
        # a fleet-scope command. A real "screen off" would be a different verb.
        if level < 0.1 or level > 1:
            raise ValueError("set_backlight level must be 0.1..1")
        setter = self._backlight
        if setter is None:
            # No panel handle (a host fixture, or a boot where `display` was not
            # injected): a failed ack, never a pretended one.
            raise ValueError("this badge exposes no backlight control")
        setter(float(level))
        # REMEMBERED AS THE PANEL BASE, so a glyph effect hands the backlight back
        # where it was rather than to a constant. A show that ended by setting
        # every badge in the room to full brightness would be worse than one that
        # never played.
        self._panel_base = float(level)
        return {"effect": "backlight", "level": float(level)}

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

    def state_report(self):
        """The ``badge_state`` row this badge would post right now.

        Public because it is the whole payload of ``report_state`` and because a
        device session needs to be able to print it without queueing anything.
        Every field except ``badge_id`` is optional and an unreadable one is
        OMITTED rather than guessed: a null column reads as "not reported", and a
        fabricated one reads as a measurement.
        """
        badge_id = None
        reader = getattr(self._backend, "badge_id", None)
        if callable(reader):
            try:
                badge_id = reader()
            except Exception:
                badge_id = None
        if not isinstance(badge_id, str) or not badge_id:
            raise ValueError("this badge has no credential to report against")
        record = {"badge_id": badge_id}
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

    def post_state_report(self, reason="command"):
        """Build a snapshot and queue it. Raises when it could not be queued."""
        import rpc_contract

        record = self.state_report()
        field_count = len(record)
        badge_id = record.pop("badge_id")
        queued = self._queue_errand(
            "table",
            {"table": rpc_contract.TABLE_BADGE_STATE, "method": "PATCH",
             "row": record, "prefer": rpc_contract.PREFER_MINIMAL,
             "query": (("badge_id", "eq." + badge_id),)},
            self._on_state_posted,
            # COALESCED. Two reports in one exchange window would post a stale
            # snapshot and then a fresh one; only the fresh one is worth sending.
            key="badge_state",
        )
        if not queued:
            raise ValueError("the badge could not queue a state report")
        self._emit("state_report_queued", reason=reason)
        return {"effect": "state_report", "queued": True,
                "fields": field_count, "reason": reason}

    def _on_state_posted(self, ok, _data):
        self._emit("state_report_posted" if ok else "state_report_failed")

    # -- the score drain (Card FT-B item 3) ---------------------------------
    #
    # THE GAME NEVER WAITS AND NEVER KNOWS. A game calls
    # `scorebox.record(game, score, duration_ms)` and returns to its own frame
    # loop; this is the half that notices a socket exists and posts one row.
    #
    # ONE IN FLIGHT, OLDEST FIRST, and the per-frame question is an integer
    # compare: `scorebox.scan_complete()`/`cached_head()` read the count and the
    # head out of the module both sides share, so a spool that is empty costs
    # nothing at all. Filling that pair the FIRST time is the cold load, and it
    # happens ONE bounded record per frame (`scorebox.drain_head`, CX-10).
    #
    # THE HEAD CANNOT BLOCK. An entry is retired after a success AND after
    # `scorebox.MAX_ATTEMPTS` refusals, because the errand channel reports
    # (ok, data) with no HTTP status -- it cannot tell a transient failure from
    # the 403 a badge without a `scores/write` grant gets -- and an entry that
    # retried forever would silently stop every later score from ever landing.

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

    # -- the two cadence phases (CX-8) -------------------------------------
    #
    # NEITHER OF THESE IS A LATENCY DECISION. Both intervals were priced for the
    # herd (`SCHEDULE_REFRESH_MS`, `polltransport.POLICY_REFRESH_MS`) and both were
    # honoured perfectly WITHIN a boot; what was wrong was only the FIRST fire, and
    # every app exit on this platform is a `machine.reset()`, so "the first fire"
    # is what a wearer switching apps pays over and over. Phasing the first fire
    # moves every later one with it and costs nothing else.

    def _arm_policy_phase(self, now):
        """Give the loop this badge's steering-read phase. Never raises."""
        arm = getattr(self._backend, "set_policy_due", None)
        if not callable(arm):
            return None
        if self._policy_due is None:
            delay = self._jittered_delay_ms(POLICY_FIRST_MIN_MS,
                                            POLICY_REFRESH_MS)
            self._policy_due = _ticks_add(now, delay)
            self._emit("policy_phased", due_ms=delay)
        try:
            return arm(self._policy_due)
        except Exception as exc:
            self.last_error = _error_text(exc)
            return None

    def _mirror_policy_due(self):
        """Copy the loop's steering due into this object. Never raises.

        **THIS IS THE CORRECTION TO CX-8's OWN FIX, 2026-08-23.** Ownership of
        the steering PHASE moved here because this object outlives every loop it
        builds -- but the loop advances the due time when the request is ISSUED
        while this object advanced it only in `_on_policy`, when steering
        ARRIVED. One case makes those two disagree, and a wearer creates it on
        purpose: a policy read that FAILED. The loop moved its copy five minutes
        out (correctly -- see `polltransport._begin_next`) and this copy stayed in
        the past, so the next backend rebuild -- a networking off/on toggle, or a
        fault the service recovers from with a new backend -- handed that stale
        past-due straight back down through `arm_policy` and OVERWROTE the loop's
        good value. The new session then issued poll-then-immediate-policy, which
        is the CX-8 boot burst reappearing behind a Settings toggle.

        So the loop owns every advance and this is a MIRROR. The read is one
        duck-typed call per polled frame -- an attribute read and no allocation --
        and it is duck-typed for the same reason `set_policy_due` is: a backend or
        fixture shape that predates the seam keeps the behaviour it had.
        """
        reader = getattr(self._backend, "policy_due", None)
        if not callable(reader):
            return None
        try:
            due = reader()
        except Exception as exc:
            self.last_error = _error_text(exc)
            return None
        if due is not None:
            self._policy_due = due
        return due

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

    def _pump_scores(self):
        """Offer the oldest spooled score, if there is one and a socket exists.

        RETIRING COMES FIRST, and it is a whole frame's budget: the delivered
        entry's key is remembered by the sink and the file work happens here, one
        frame later, so the frame that received the acknowledgement carries the
        response decode and nothing else.

        THE ORDER OF THE THREE GUARDS BELOW IS CX-10'S FIX and it is the whole
        of it. This method used to ask ``box.pending()`` FIRST -- eighteen lines
        above `_claim_chore()` and above the socket check -- so a badge with no
        socket at all paid the cold whole-file spool load in its first serviced
        frame, and a frame that had already spent its budget elsewhere paid it
        anyway. Now: eligibility (which costs nothing), then the RAM question,
        then the budget, then the only file touch there is.
        """
        if self._score_retire is not None:
            return self._retire_score()
        if self._score_inflight is not None:
            return None
        # ELIGIBILITY BEFORE STORAGE. Not an error and not worth a log line: the
        # spool exists precisely because the badge is sometimes offline, and an
        # offline badge must not read it to discover that it cannot post it.
        backend = self._backend
        if backend is None or getattr(backend, "state", None) != CONNECTED:
            return None
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
            return None
        box = self._score_box()
        if box is None:
            return None
        try:
            # THE FREE QUESTION, and it is the steady frame's whole cost: a spool
            # the module has already scanned and found empty is an integer
            # compare, and it does not claim the budget the schedule sync wants.
            if box.scan_complete() and box.cached_head() is None:
                return None
        except Exception as exc:
            self.last_error = _error_text(exc)
            return None
        # THE BUDGET IS CLAIMED BEFORE ANY FILE WORK. `drain_head` is either a
        # RAM read or ONE bounded record of the cold scan; either way it is this
        # frame's one expensive sub-task and a frame that has spent its budget
        # elsewhere does not reach it.
        if not self._claim_chore():
            return None
        try:
            entry = box.drain_head(self._score_path)
        except Exception as exc:
            self.last_error = _error_text(exc)
            return None
        if entry is None:
            # The cold scan has not reached a usable record yet, or the spool is
            # empty. Either way the next frame asks again.
            return None
        import rpc_contract

        # Keep ``scorebox.row`` as the one mapping from a durable spool entry to
        # the database vocabulary. The RPC route (never a direct table insert) is
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
        row = box.row(badge_id, entry)
        params = rpc_contract.score_submit_self_params(
            badge_id, row["game"], row["score"], row["idempotency_key"],
            row["metadata"])
        self._score_inflight = entry["key"]
        queued = self._queue_errand(
            "rpc",
            {"function": rpc_contract.RPC_SCORE_SUBMIT_SELF, "params": params},
            self._on_score_posted,
        )
        if not queued:
            self._score_inflight = None
        return queued

    def _on_score_posted(self, ok, _data):
        """The sink, and it CAPTURES rather than works.

        The frame that receives an errand response has already paid for the
        response: `device_link._finish` decoded it. Retiring the entry is a
        whole-file read plus an atomic swap, so it is remembered here and
        performed by `_retire_score` on a later frame.
        """
        self._response_continuation = True
        key = self._score_inflight
        self._score_inflight = None
        box = self._score_box()
        if box is None or key is None:
            return
        if ok:
            self._score_retire = key
            self._score_retire_posted = True
            return
        self._count_score_attempt(key, box)

    def _retire_score(self):
        """Drop one retired entry.  This frame's one expensive sub-task.

        Serves both reasons an entry stops being the badge's problem -- delivered
        and exhausted -- because they are the same operation, which is what
        `scorebox.retire`'s own docstring says.
        """
        if not self._claim_chore():
            return None
        key = self._score_retire
        posted = self._score_retire_posted
        self._score_retire = None
        box = self._score_box()
        if box is None or key is None:
            return None
        try:
            box.retire(key, self._score_path)
        except Exception as exc:
            # THE ROW LANDED AND THE SPOOL STILL HOLDS IT, so the next drain
            # offers the same entry again. The RPC's idempotency key makes
            # the repost harmless on the server, but nothing would stop it:
            # the attempt counter only advanced on FAILURE, so a read-only
            # volume turned "the head cannot block" into a row reposted once
            # per errand gap for the rest of the boot. A successful post whose
            # retire failed therefore counts as an attempt too.
            #
            # AN EXHAUSTED ENTRY IS NOT COUNTED AGAIN. Its counter was already
            # cleared and its `score_discarded` already emitted, so the entry
            # simply stays and the next drain starts its three attempts over --
            # bounded churn on a volume that is already broken.
            self.last_error = _error_text(exc)
            if not posted:
                return False
            self._emit("score_retire_failed", error=self.last_error)
            self._count_score_attempt(key, box)
            return False
        self._forget_score_attempts(key)
        if posted:
            self._emit("score_posted")
        return True

    def _count_score_attempt(self, key, box):
        """One more strike against the spool head, and retire it at the cap."""
        if self._score_attempt_key != key:
            # A DIFFERENT HEAD, so the previous one's count is history. This is
            # also what makes the counter leak-proof: nothing survives a change
            # of head, including an entry FIFO compaction removed.
            self._score_attempt_key = key
            self._score_attempts = 0
        self._score_attempts += 1
        if self._score_attempts < box.MAX_ATTEMPTS:
            self._emit("score_retry")
            return
        # EXHAUSTED. Retired so the head cannot block every later score -- and
        # retired through the SAME deferred slot a delivered entry uses, because
        # the verdict is what belongs in this frame and the file work is not.
        # The event still fires here: `score_discarded` describes the decision,
        # and F19's denied leg counts decisions.
        self._forget_score_attempts(key)
        self._score_retire = key
        self._score_retire_posted = False
        self._emit("score_discarded")

    def _forget_score_attempts(self, key):
        if self._score_attempt_key == key:
            self._score_attempt_key = None
            self._score_attempts = 0

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
        finds the key gone and `scorebox.retire` returns False without raising,
        and a stale `_score_attempt_key` cannot outlive a change of head (see
        `_count_score_attempt`). What DOES have to be reset is the module-level
        cache, and `scorebox.wipe` owns that.

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
            # COUNTS RATHER THAN A VERDICT, and the honest signal is in the
            # RESULT for the reason `_dispatch` already states about "scheduled":
            # the ack vocabulary has two words and neither of them is "partly".
            # A game that was never played is neither removed nor failed, which
            # is normal -- three of the five are off the production roster.
            result["bests_removed"] = removed
            result["bests_failed"] = failed
        self._emit("scores_wiped", scope=scope, discarded=discarded)
        return result

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
        """Queue the app-open snapshot RPC once the shared socket is ready."""

        if (not self._schedule_v2_requested or self._schedule_v2_done
                or self._schedule_v2_inflight):
            return None
        backend = self._backend
        if backend is None or getattr(backend, "state", None) != CONNECTED:
            return None
        import rpc_contract

        params = rpc_contract.schedule_current_v2_params(
            self._schedule_v2_have)
        queued = self._queue_errand(
            "rpc",
            {"function": rpc_contract.RPC_SCHEDULE_CURRENT_V2,
             "params": params, "method": "GET"},
            self._on_schedule_v2,
            key="schedule_v2_open",
        )
        if queued:
            self._schedule_v2_inflight = True
            self._emit("schedule_v2_queued")
        return queued

    def _on_schedule_v2(self, ok, data):
        """Stage one decoded response into the app; never parse or write here."""

        self._response_continuation = True
        self._schedule_v2_inflight = False
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
        if self._schedule_inflight:
            return None
        backend = self._backend
        if backend is None or getattr(backend, "state", None) != CONNECTED:
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

        self._schedule_inflight = True
        queued = self._queue_errand(
            "rpc",
            {"function": rpc_contract.RPC_SCHEDULE_VERSION,
             "params": {}, "method": "GET"},
            self._on_schedule_version,
            key="schedule_version",
        )
        if not queued:
            self._schedule_inflight = False
        return queued

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

    def _on_schedule_version(self, ok, data):
        """The sink, and it touches NO file: the cached version is in RAM."""
        self._response_continuation = True
        self._schedule_inflight = False
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

        self._schedule_inflight = True
        queued = self._queue_errand(
            "table",
            {"table": rpc_contract.TABLE_SCHEDULE_EVENTS, "method": "GET",
             "query": box.page_query(self._schedule_offset)},
            self._on_schedule_page,
        )
        if not queued:
            self._schedule_inflight = False
        return queued

    def _on_schedule_page(self, ok, data):
        """The sink, and it CAPTURES the page rather than normalising it.

        Everything expensive about a page -- the per-character sanitize, the
        `_raw` decision, the bound on every field -- happens in
        `_schedule_parse_step`, `SCHEDULE_PARSE_ROWS` rows at a time.
        """
        self._response_continuation = True
        self._schedule_inflight = False
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
        self._pump_scheduled_commands(now)
        if self._pulse_until is not None and _ticks_diff(now, self._pulse_until) >= 0:
            self._pulse_until = None
            self._caselights(0)
        program = self._lights
        if program is not None:
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
        if player is not None:
            # `step` is False on every frame where neither channel moved, which is
            # most of them, and True/False are singletons -- so a quiet frame of a
            # 300-second show allocates nothing.
            if player.step(_ticks_diff(now, self._effect_started)):
                self._write_effect_levels(player)
            if player.done:
                self._effect = None

    def _emit(self, event, **fields):
        if self._event_sink is None:
            return
        record = {"service": "badgelink_network", "event": event,
                  "state": self.state}
        record.update(fields)
        self._event_sink(record)

    def _on_policy(self, steering):
        """The server's transport policy, on its way to the doorbell.

        Held even when there is no push object yet, so a policy that arrived
        before the first WS session still applies to it. Contained: a malformed
        policy is a thing to ignore, never a thing to crash a poll cycle over.
        """
        self._policy = steering if isinstance(steering, dict) else None
        # THE DUE TIME IS NOT TOUCHED HERE ANY MORE (CX-8, corrected 2026-08-23).
        # This line used to be `self._policy_due = _ticks_add(self._now,
        # POLICY_REFRESH_MS)`, which made this object the second owner of one
        # cadence: it advanced on ARRIVAL while the loop advanced on ISSUE, so a
        # FAILED read left the two disagreeing and a rebuild handed the stale copy
        # back down. `polltransport._process_steering` now performs this same
        # advance on the loop -- which is where "whichever exchange carried it"
        # belongs, since the loop is what reads the poll response -- and
        # `_mirror_policy_due` brings it back here. See that method.
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
        #: The service-owned steering phase, held until a loop exists to take it.
        self._policy_due = None
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

    def set_policy_due(self, due_ms):
        """When the service says the next steering read is due (CX-8).

        Same shape as `set_policy_sink` and for the same reason: the service does
        not reach into the loop, and a backend with no loop yet remembers the
        value so the loop built on the first successful association carries it.
        """
        self._policy_due = due_ms
        if self._loop is not None:
            self._loop.arm_policy(due_ms)
        return due_ms

    def policy_due(self):
        """What the LIVE loop says the next steering read is due at, or ``None``.

        The read-back half of `set_policy_due` (CX-8, corrected 2026-08-23). The
        loop advances its own due time when it ISSUES a request and again when
        steering ARRIVES; the service used to advance a separate copy only on
        arrival, so a FAILED read left the two disagreeing and the next rebuild
        handed the stale past-due back down here. Answering from the loop when
        there is one -- and from the remembered value when there is not, which is
        the window between a rebuild and the first successful association --
        makes the service's copy a mirror instead of a second opinion.
        """
        if self._loop is not None:
            return self._loop.policy_due()
        return self._policy_due

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
        # command queue and `badge_state` row would be the floor's, and revoking
        # the fleet grant would revoke its own tier -- so it does not try. It
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
            outcome = self._clock_boot.resync(
                self._ntptime,
                self._rtc,
                read_epoch=lambda: int(time.time()),
                clock_verified=self._clock_verified,
            )
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
        if self._policy_due is not None:
            # CX-8: the service phased this cadence before the radio was up, so
            # the loop takes the phase rather than arming `now` at its first open.
            self._loop.arm_policy(self._policy_due)
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
                   "sessions_joined") + _CONNECT_ATTRIBUTION_FIELDS

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
#: The evidence README overstates this in two directions -- it says "every badge
#: in the field runs it", but `apps-roster.json` ships `production.system_lib`
#: `ship: false`, so the handover payload carries no `/system/lib` at all, and it
#: omits the DTR precondition above.
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
            schedule_path=None, score_path=None, schedule_cache_path=None):
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
            # Badgeware's launcher returns the selected app path from its
            # update callback. ``run`` preserves that value in ``.result`` and
            # /system/main.py launches it. Dropping the return here makes a
            # selected tile merely flash while the launcher keeps running.
            result = update()
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
