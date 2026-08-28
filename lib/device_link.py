"""On-device link: drive PostgREST over the frozen AsyncFetch keep-alive socket.

This is the glue between :mod:`polltransport`'s ``open/begin/pump/close`` contract
and Badgeware v3.0.1's frozen ``fetch.AsyncFetch`` + the verified-TLS shim. Its
non-I/O logic — request shaping (via :mod:`postgrest`), response adjudication,
error→``LinkError`` mapping, the handshake-only-at-``open`` discipline, and shim
install/restore bookkeeping — is fixture-tested here with an injected fake worker.

DEVICE-VERIFIED (Card E, Badgeware v3.0.1):

* the exact frozen ``AsyncFetch.fetch(...)`` keyword surface for a POST with a
  body and headers (the P4 pre-gates only exercised a GET). ``_start_request``
  isolates that one call so a device session can correct it in one place.
* the ~720 ms first-request handshake actually lands inside ``open`` (the tolerant
  CONNECTING moment) and every post-first ``pump`` stays ≤34 ms (B2 probe 1).

Design note — why ``open`` does a full first poll and stashes it. The frozen
client defers the TLS handshake to the first write, so there is no handshake-only
call: the socket is warmed by a real request. That first request MUST be the poll
(it re-fetches desired state on every (re)connect), and its result MUST NOT be
discarded — the poll RPC increments ``delivery_attempts`` against the 5-attempt
redelivery cap, so a thrown-away warm-up poll would burn a delivery attempt for
every queued command. So ``open`` runs the poll to completion, stashes the parsed
result, and the transport's first ``begin("poll")`` serves the stash.
"""

import time

from postgrest import (
    AccessRevoked,
    AuthRejected,
    PostgrestError,
    ack_request,
    parse_ack_row,
    parse_policy_row,
    parse_poll_rows,
    parse_response,
    policy_request,
    poll_request,
    rpc_request,
    table_request,
)
from polltransport import (
    COLD_OPEN_BUDGET_MS,
    OPEN_BUDGET_MS,
    PENDING,
    LinkError,
    LinkRevoked,
    LinkStalled,
)


DEFAULT_POLL_LIMIT = 16
# A single request must not spin the frame loop forever. On hardware a warm
# request completes in a handful of updates; this bounds a silently-stalled one
# into a missed-ack instead of an infinite pump.
MAX_PUMP_UPDATES = 400
# ``open`` drives a non-blocking socket in a tight tolerant-moment loop rather
# than once per rendered frame. Give the network time to progress between
# updates and let AsyncFetch's own inactivity timeout remain authoritative --
# `polltransport.OPEN_BUDGET_MS`, or `COLD_OPEN_BUDGET_MS` for the first open of
# a link, passed as whole seconds by `network_runtime`'s `worker_factory`.
#
# 30,000 STEPS AT A 1 ms COOPERATIVE SLEEP IS ~30 s, AND IT IS DELIBERATELY NOT
# BEING LOWERED WITH THE BUDGET (2026-08-24). It was 3x the old 10 s ceiling and
# is 6x the new 5 s one, which makes it MORE deferential to the firmware
# deadline, not less -- and that is the whole point of this guard: it exists only
# so a firmware that somehow never times out cannot spin a frame forever. A
# proportional cut would turn a backstop into a second, competing deadline with
# no measurement behind it.
#
# **WHICH OF THE TWO BINDS FIRST IS NO LONGER UNVERIFIED, and the answer is the
# firmware's deadline by about an order of magnitude.** The NB connect spec's
# adversarial review left this as a named open risk ("`MAX_OPEN_PUMP_UPDATES =
# 30000` vs Lane G's 5,000 ms cap -- which binds first on the blackhole path today
# is unverified"), and the measurement to close it already existed: the 2026-08-25
# freeze capture recorded **`updates=584-5,887`**, with the 5,887 belonging to the
# open that ran to the OLD 10,009 ms ceiling. That is ~1.7 ms of wall time per
# update -- the 1 ms sleep plus the update's own work -- so:
#
#   * a 5,000 ms capped open spends roughly **2,900 updates**, and
#   * this budget is reached at roughly **51 s** of wall time.
#
# So the ceiling fires first with ~10x of headroom, this guard stays the backstop
# it was written to be, and a `LinkError: open request exceeded the pump budget`
# still means what it has always meant: the firmware's own deadline did not fire,
# which is a firmware question and not a tuning one.
#
# AND IT STILL BINDS SECOND UNDER LANE J's COLD-BOOT ALLOWANCE: a 9,000 ms first
# open spends roughly 5,300 updates against this 30,000, so the ~51 s backstop is
# still ~5.7x the largest ceiling any open can be given. Not lowered, not raised.
# This remains a WORK sanity cap in the parked path. It no longer approximates
# wall time there: a would-block worker is called once next frame, so 30,000
# means 30,000 actual generator advances and not 30 seconds of 1 ms sleeps.
MAX_OPEN_PUMP_UPDATES = 30000

# The old 30,000-step spin backstop bound at roughly 51 seconds on the measured
# firmware (5,887 updates in 10,009 ms). P1-a preserves that independent
# liveness ceiling as WALL time, while the worker's own 5/9-second value remains
# an inactivity/no-progress deadline. A progressing peer therefore keeps its
# inactivity semantics but cannot park an owner forever.
OPEN_WALL_DEADLINE_MS = 51000

# A clock with coarse ticks, or a malformed worker that yields without touching
# I/O or consuming measurable time, must not turn the soft millisecond budget
# into an unbounded Python loop. This is per outer call and independent of the
# 30,000-update whole-attempt sanity cap.
MAX_OPEN_READY_STEPS = 64

# WHERE AN OPEN'S MILLISECONDS WENT, and why the buckets are the FIRMWARE's own
# labels rather than names we invented.
#
# ``PollLoop`` reports ONE number for a handshake (``open_ms``), and on
# 2026-08-23 that lump could not discriminate three live hypotheses for a
# multi-second launcher freeze: a blocking name resolution, a TCP connect to a
# peer that is not answering, and the TLS handshake itself. It cannot, because
# the whole open is one blocking call from the transport's point of view.
#
# ``fetch.AsyncFetch`` already labels every step it is in — ``self._phase`` is
# set to ``"dns"``/``"connect"`` in ``_connect``, ``"send"`` in
# ``_send_request``, ``"headers"`` in ``_read_headers`` and ``"body"`` in
# ``_run`` (pinned ``bw-1.28.0-3``, ``modules/common/fetch.py``). ``update()``
# advances the generator by exactly one ``next()``, so bracketing that one call
# and reading the label AFTER it charges the step to the phase it just ran. That
# is measurement with no interpretation: the buckets are the firmware's.
#
# THREE THINGS THE SPLIT SETTLES THAT THE LUMP CANNOT:
#
# * ``connect_ms`` carries the socket, the non-blocking ``connect`` (which
#   returns ``EINPROGRESS`` immediately, ``fetch.py:226-231``) and the whole
#   verified-TLS setup — a fresh ``SSLContext`` plus one
#   ``load_verify_locations`` per pinned root, i.e. two DER reads and two x509
#   parses off LittleFS on EVERY open (``verified_tls.VerifiedTLSShim``).
# * ``send_ms`` carries the TLS HANDSHAKE, because the firmware defers it to the
#   first write (``do_handshake_on_connect=False``, ``fetch.py:236``) and the
#   handshake was device-measured at 735.362 ms inside ONE ``update()``
#   (`VAL-031-BLT`). A handshake is therefore not splittable at this seam.
# * ``sleep_ms`` is OURS, not the network's: ``_run_blocking`` spins
#   ``update()`` with a 1 ms cooperative sleep between steps, so an open that
#   takes 400 steps has spent ~400 ms inside our own sleeps. Nothing before this
#   could tell that apart from radio time.
#
# All of it is inside ``open()``, which is the tolerant CONNECTING moment that is
# already the expensive path. ``begin``/``pump`` — every rendered frame of a
# healthy session — are not touched, so the steady frame is provably unchanged.
_OPEN_PHASE_KEYS = ("dns", "connect", "send", "headers", "body", "other")

# WHAT PROVES THE PEER IS STILL THERE, and it is a SHORT list on purpose.
#
# Only two of the firmware's phases can be reached because bytes came BACK:
# ``headers`` is set inside ``_read_headers`` and ``body`` inside ``_run``, so
# either one means a response is arriving. Every update spent in one of them
# re-arms the no-progress clock, which is also why a large body cannot be
# mistaken for a stall.
#
# ``connect``->``send`` IS DELIBERATELY NOT PROGRESS. The frozen client's
# ``connect`` is non-blocking and returns EINPROGRESS immediately
# (``fetch.py:226-231``), so the phase advances with nobody at the other end --
# every device open reports ``connect_ms`` around 8 ms, including the freeze
# capture's run 2, which then sat in ``send`` until the 10 s ceiling fired. A
# rule that counted that transition would have measured 10,001 ms of stall
# against a 10,000 ms ceiling: one millisecond of margin, decided by jitter.
_OPEN_PROGRESS_PHASES = ("headers", "body")

# Internal only: unlike ``PENDING``, this says the terminal response has been
# parsed and ownership can be published after the outer call is fully priced.
_OPEN_FINISHED = object()

# THE DEADLINE THE NO-PROGRESS CLASS IS DECLARED AT (NB-i), and it is the
# transport's own open budget rather than a fourth number that agrees with it
# today. IMPORTED, not re-spelled: this module already imports `polltransport`,
# so there is no new partial-install hazard, and the two MUST be one value
# because this deadline is a MIRROR of the ceiling the frozen
# ``AsyncFetch(timeout=5)`` actually enforces. We do not end the open -- the
# firmware does -- we only name the ending.
#
# WHY THE MIRROR CANNOT MISS BY A MILLISECOND: the stall clock is armed BEFORE
# ``_start_request`` and the firmware arms its own deadline inside ``fetch()``,
# one statement later, so our no-progress span is always at least the firmware's
# inactivity window. A ceiling failure therefore cannot read 4,999 against a
# 5,000 bar. (`test_device_link.TypedNoProgressTests` asserts that ordering in
# the source, because it is the whole reason no fudge factor is needed.)
OPEN_NO_PROGRESS_MS = OPEN_BUDGET_MS

# AND THE SAME MIRROR FOR THE FIRST OPEN OF A LINK (Lane J, 2026-08-24). The
# cold-boot allowance gives open #1 a bigger inactivity ceiling because the 5,000
# was measured truncating HEALTHY cold boots -- 5 of 7, with a 4,119 ms open
# succeeding beside them (`polltransport.COLD_OPEN_BUDGET_MS` carries the
# derivation). **A SECOND CEILING NEEDS A SECOND MIRROR, or the class would be
# declared at a deadline the firmware did not enforce**, and the failure mode is
# the bad direction: an open the firmware was still willing to wait 9 s for,
# killed at 6 s by something else, would be typed a black hole and buy the
# 16-32 s band.
#
# WHICH ONE APPLIES IS NOT DECIDED HERE, and that is the point. This module reads
# the ceiling off the WORKER the factory built (`_worker_no_progress_ms`), so ONE
# decision -- the factory's, which is the thing that spells `timeout=` -- drives
# both the firmware's deadline and the name this module gives to reaching it. A
# counter in this module beside a counter in the factory would be two decisions
# that agree today. A worker built by anything that predates the allowance
# carries no budget and gets `OPEN_NO_PROGRESS_MS`, which is exactly the old
# behaviour.
COLD_OPEN_NO_PROGRESS_MS = COLD_OPEN_BUDGET_MS

#: WHERE THE FACTORY WRITES THE CEILING IT APPLIED, in milliseconds. Same
#: mechanism as `worker._addr_info`: the frozen `AsyncFetch` has no accessor for
#: its own `timeout`, and asking for one would be a firmware change.
WORKER_BUDGET_ATTR = "_open_budget_ms"


def _worker_no_progress_ms(worker):
    """The deadline the no-progress class is declared at, for THIS worker.

    The ceiling the frozen ``AsyncFetch`` was constructed with, as the factory
    recorded it, or :data:`OPEN_NO_PROGRESS_MS` when there is nothing to read.
    Never raises and never returns zero: a broken or absent value degrades to the
    warm budget, which is the deadline every open had before Lane J.
    """

    try:
        value = int(getattr(worker, WORKER_BUDGET_ATTR, 0) or 0)
    except Exception:
        value = 0
    return value if value > 0 else OPEN_NO_PROGRESS_MS


def _open_phases():
    """A fresh, fixed-shape accounting record for one ``open()``.

    Fixed shape on purpose: the phase label comes from the firmware, and a dict
    keyed by whatever a module attribute happens to hold is an unbounded
    allocation on a 520 KB heap. An unrecognised label is charged to ``other``.
    """

    record = {
        "shim_ms": 0,
        "build_ms": 0,
        "start_ms": 0,
        "worker_ms": 0,
        "sleep_ms": 0,
        "finish_ms": 0,
        "total_ms": 0,
        # P1-a makes the open span several rendered frames, so one old lump can
        # no longer answer both "how long until connected" and "what held a
        # frame". These reconcile at every terminal outcome; `sleep_ms` stays
        # the legacy driver's literal sleeps and is always zero on the parked
        # path.
        "open_span_ms": 0,
        "open_busy_ms": 0,
        "open_wait_ms": 0,
        "open_steps": 0,
        # Batching makes the largest atomic worker call insufficient as a frame
        # oracle: fifty 2 ms updates are a 100 ms frame while
        # `open_step_max_ms` remains 2. This is the largest whole `open_step`
        # call; the old atomic field keeps its established denomination.
        "open_frame_max_ms": 0,
        # THE ONE NUMBER A WEARER CAN PERCEIVE (NB-i). Every other figure here
        # is a SUM, and a sum is not a feeling: the 2026-08-25 freeze capture's
        # worst open was 8,746 ms of which 5,156 ms was our own 1 ms sleeps, so
        # the frame was held for 8.7 seconds while no single call inside it ran
        # for longer than about two. This is the largest single BLOCKING call
        # charged to one frame, which is exactly the quantity the NB spec's
        # phase 1(a) has to move -- a parked open keeps the same `worker_ms` and
        # brings this down, and without it that win is invisible.
        "open_step_max_ms": 0,
        # HOW LONG THIS OPEN WENT WITHOUT HEARING THE PEER, at its terminal
        # outcome (NB-i). It is the EVIDENCE for `outcome`: a `LinkStalled` open
        # is one whose stall reached `OPEN_NO_PROGRESS_MS`, and printing the
        # number is what lets a reader check the classification rather than
        # trust it. Near zero on a healthy open, because the response phases
        # re-arm it.
        "open_stall_ms": 0,
        # AND THE DEADLINE IT WAS CHECKED AGAINST (Lane J). There are TWO now --
        # `COLD_OPEN_NO_PROGRESS_MS` for the first open of a link and
        # `OPEN_NO_PROGRESS_MS` after it -- so `open_stall_ms` alone stopped being
        # enough to check a classification: 6,000 is over one bar and under the
        # other. This is the bar that applied, read off the worker rather than
        # inferred, and it is also how a serial reader tells a COLD open from a
        # warm one without counting lines. PURELY REPORTED: the decision uses a
        # local, and `test_device_link.test_no_decision_reads_a_phase_number`
        # fails on a comparison against this name.
        "open_deadline_ms": 0,
        "updates": 0,
        "outcome": None,
    }
    for name in _OPEN_PHASE_KEYS:
        record[name + "_ms"] = 0
    return record


def _suppress_http_status_exception(_worker):
    """Let DeviceLink adjudicate HTTP status (especially the binding 401 rule)."""

    return True


def _ticks_ms():
    """The wrap-safe millisecond tick, or a CPython stand-in for the host lane.

    Same shape as ``network_runtime._ticks_ms``: MicroPython's monotonic
    ``ticks_ms``/``ticks_diff`` pair on the badge, ``time.monotonic`` under the
    fixture runner. No new module and no new firmware attribute.
    """

    function = getattr(time, "ticks_ms", None)
    return function() if function is not None else int(time.monotonic() * 1000)


def _ticks_diff(left, right):
    function = getattr(time, "ticks_diff", None)
    return function(left, right) if function is not None else left - right


def _span_ms(entered):
    span = _ticks_diff(_ticks_ms(), entered)
    return 0 if span < 0 else span


def _open_cooperate():
    sleep_ms = getattr(time, "sleep_ms", None)
    if sleep_ms is not None:
        sleep_ms(1)
    else:  # CPython fixture lane
        time.sleep(0.001)


class _ShimInstaller:
    """Install/restore the verified-TLS shim on the frozen ``fetch`` module.

    Wraps :func:`badgelink.verified_tls.install`/``restore`` so ``DeviceLink``
    can be constructed in a test without a real ``fetch``/``ssl`` module.
    """

    def __init__(self, fetch_module, tls_module, ca_paths, verified_tls):
        self._fetch = fetch_module
        self._tls = tls_module
        self._ca_paths = ca_paths
        self._verified_tls = verified_tls
        self._previous = None
        self._installed = False

    def enable_open_tracking(self):
        """Enable the socket readiness proxy in the immutable ON artifact."""

        # A class-default lookup keeps OFF's instance dictionary and install
        # call byte-for-byte shaped as before. Only the build-time ON path ever
        # materialises this key.
        self._track_open_io = True
        return True

    def install(self):
        if self._installed:
            return
        if getattr(self, "_track_open_io", False):
            self._previous = self._verified_tls.install(
                self._fetch, self._tls, self._ca_paths, track_io=True
            )
        else:
            self._previous = self._verified_tls.install(
                self._fetch, self._tls, self._ca_paths
            )
        self._installed = True

    def restore(self):
        if not self._installed:
            return
        self._verified_tls.restore(self._fetch, self._previous)
        self._installed = False


class DeviceLink:
    def __init__(
        self,
        credentials,
        worker_factory,
        shim,
        addr_info=None,
        poll_limit=DEFAULT_POLL_LIMIT,
        event_sink=None,
        addresses=None,
        self_badge_id=None,
    ):
        if credentials is None or worker_factory is None or shim is None:
            raise ValueError("credentials, worker_factory and shim are required")
        self._credentials = credentials
        #: THIS BADGE'S PHYSICAL ID, and it is NOT ``credentials.badge_id``.
        #: Under gang-clone provisioning the credential's ``sub`` is one shared
        #: fleet subject on all ~800 badges, so the ``_self`` poll/ack RPCs take
        #: the hardware ``machine.unique_id().hex()`` as an explicit
        #: ``p_badge_id`` and the fairness bucket keys on the same value.
        #: Injected rather than read here because this module imports no
        #: Badgeware; ``network_runtime.DeviceBackend`` computes it once per boot
        #: (`network_runtime.hardware_uid`) and hands the one value to this link,
        #: the doorbell and the score drain alike.
        #:
        #: ``None`` DEGRADES TO THE WHOAMI POLL AND ACK -- it does NOT refuse.
        #: It refused until 2026-08-26, and that took the correctness floor down
        #: for a purely defensive case: the primed poll runs inside :meth:`open`,
        #: so a refusal failed the OPEN, and with the socket went the schedule
        #: sync, the `badge_state` heartbeat, the score drain and the steering
        #: read -- none of which need a badge id at all. See
        #: `postgrest.poll_request` for the full reasoning; the diagnosability
        #: the refusal was buying is bought by one emitted line instead.
        self.self_badge_id = self_badge_id
        self._worker_factory = worker_factory
        self._shim = shim
        self._addr_info = addr_info
        #: THE SESSION'S SHARED ADDRESS CACHE, or ``None`` (CX-3). PURELY
        #: CARRIED -- nothing in this module reads it, and `_connect_worker` still
        #: uses the ``addr_info`` it was constructed with.
        #:
        #: It is here because this is the object the DOORBELL can reach. The push
        #: factory is handed one thing, the live `polltransport.PollLoop`
        #: (`network_runtime.device_push_factory`), and its signature is fixed by
        #: the generated `/system/main.py` block, so it cannot grow an argument
        #: without a badge reinstall. `poll_loop.link.addresses` is the seam.
        #: `network_runtime.DeviceBackend` owns the object and invalidates it on
        #: the ``wifi_lost`` edge; a link built without one carries ``None`` and
        #: the doorbell falls back to connecting by name.
        self.addresses = addresses
        self._poll_limit = int(poll_limit)
        self._event_sink = event_sink
        self._worker = None
        self._inflight_kind = None
        # AsyncFetch's terminal update can itself consume most of a rendered
        # frame. Keep response parsing/adjudication (and the caller's response
        # sinks) for the following frame instead of stacking both costs in the
        # terminal-update frame.
        self._response_ready = False
        self._pump_count = 0
        self._primed_poll = None  # stashed first-poll result from open()
        #: WHERE THE LAST ``open()``'s MILLISECONDS WENT. See `_OPEN_PHASE_KEYS`.
        #: Replaced (never mutated in place) once per open, so a probe reading it
        #: between opens sees one whole record; ``None`` before the first open.
        #: PURELY REPORTED — nothing in this module or the transport reads a
        #: number from it to make a decision, and an AST guard keeps it that way.
        self.open_phases = None

    # -- link contract -----------------------------------------------------

    def open(self, now):
        """Handshake + first poll, blocking, at the tolerant CONNECTING moment."""
        phases = _open_phases()
        started = _ticks_ms()
        entered = started
        self._shim.install()
        phases["shim_ms"] = _span_ms(entered)
        try:
            entered = _ticks_ms()
            self._worker = self._connect_worker()
            phases["build_ms"] = _span_ms(entered)
            # THE DEADLINE THIS OPEN'S CLASS WILL BE DECLARED AT, taken ONCE from
            # the worker the factory just built (Lane J). Held in a LOCAL and
            # passed down: the record below is published, and no decision in this
            # package is built from a published attribution field.
            no_progress_ms = _worker_no_progress_ms(self._worker)
            phases["open_deadline_ms"] = no_progress_ms
            # Warm the socket by running the first poll to completion. The
            # handshake cost lives here, behind the connecting screen.
            self._primed_poll = self._run_blocking(
                self._poll_request(), parse_poll_rows,
                phases=phases, no_progress_ms=no_progress_ms,
            )
        except LinkError as exc:
            # THE FAILED OPEN IS THE ONE WORTH ATTRIBUTING, so the record is
            # published before the raise rather than lost with the frame. The
            # exception is unchanged and re-raised untouched: this is
            # measurement, and `PollLoop` still owns every decision.
            self._finalize_phases(
                phases, started, exc.__class__.__name__, parked=False
            )
            self._publish_phases(phases)
            self._teardown_worker()
            self._shim.restore()
            raise
        self._finalize_phases(phases, started, "opened", parked=False)
        self._publish_phases(phases)
        self._emit("opened", primed=len(self._primed_poll))

    def open_step(self, now, budget_ms, generation=None):
        """Advance a first poll until a real socket wait or busy budget.

        The frozen ``AsyncFetch.update`` collapses every generator yield into
        one status, so phase names cannot distinguish progress from EAGAIN. The
        immutable ON build installs ``verified_tls``'s socket proxy: only a
        proxied read/write returning ``None`` (or write returning zero) is a
        genuine wait. Generator budget yields touch no socket and may continue
        inside this call until ``budget_ms`` is spent.

        ``budget_ms`` is soft: it is checked before another atomic update and
        cannot pre-empt the measured 820-903 ms certificate verification call.
        A terminal worker update is never stacked with response parsing; like
        :meth:`pump`, the parse happens on the next rendered frame.
        """

        if not isinstance(budget_ms, int) or isinstance(budget_ms, bool):
            raise ValueError("open-step budget must be a positive integer")
        if budget_ms <= 0:
            raise ValueError("open-step budget must be a positive integer")
        entered = _ticks_ms()
        self._parked_step_entered = entered
        try:
            result = self._advance_open_step(now, budget_ms, generation)
        except LinkError as exc:
            phases = getattr(self, "_parked_phases", None)
            if phases is not None:
                self._charge_parked_step(phases, entered)
                self._finish_parked_open(exc.__class__.__name__)
            raise
        except BaseException as exc:
            # A parser bug remains its original class, but it no longer owns a
            # socket until NetworkService gets around to containing it. This is
            # also the cancellation/KeyboardInterrupt cleanup hole that the
            # port's detached raw-socket behavior made load-bearing.
            phases = getattr(self, "_parked_phases", None)
            if phases is not None:
                self._charge_parked_step(phases, entered)
                self._finish_parked_open(exc.__class__.__name__)
            raise
        phases = getattr(self, "_parked_phases", None)
        if phases is not None:
            self._charge_parked_step(phases, entered)
        if result is _OPEN_FINISHED:
            self._finish_parked_open("opened")
            return None
        return PENDING

    def abort_open(self, generation=None, reason="aborted"):
        """Invalidate and close one parked open without scoring a failure."""

        active = getattr(self, "_parked_generation", None)
        if active is None or (generation is not None and generation != active):
            return False
        # Publish before teardown so even a worker reset that swallows an error
        # cannot erase which attempt owned the socket. The bounded outcome word
        # deliberately excludes the administrative reason from failure classes.
        self._finish_parked_open("aborted")
        self._emit("open_aborted", reason=reason)
        return True

    def _advance_open_step(self, now, budget_ms, generation):
        active = getattr(self, "_parked_generation", None)
        last = getattr(self, "_parked_last_generation", -1)
        if generation is None:
            generation = last + 1 if active is None else active
        if active is None:
            # A continuation from an invalidated attempt is a strict no-op. The
            # PollLoop that owns a current attempt always advances generation,
            # so only a stale callback can reach this branch.
            if generation <= last:
                return PENDING
            self._begin_parked_open(now, generation)
            active = generation
        elif generation != active:
            return PENDING

        phases = self._parked_phases
        if self._parked_response_ready:
            self._primed_poll = self._finish_parked_response()
            return _OPEN_FINISHED

        entered_updates = self._parked_updates
        while True:
            wall_span = _span_ms(self._parked_started)
            if wall_span >= OPEN_WALL_DEADLINE_MS:
                raise LinkError("open request exceeded the wall deadline")
            stall = _span_ms(self._parked_progress_at)
            if stall >= self._parked_no_progress_ms:
                phases["open_stall_ms"] = stall
                raise LinkStalled("open request made no progress")
            if self._parked_updates >= MAX_OPEN_PUMP_UPDATES:
                raise self._open_failure(
                    "open request exceeded the work budget",
                    self._parked_progress_at,
                    phases,
                    no_progress_ms=self._parked_no_progress_ms,
                )
            if self._parked_updates - entered_updates >= MAX_OPEN_READY_STEPS:
                return PENDING

            self._reset_worker_io()
            update_entered = _ticks_ms()
            try:
                status = self._worker.update()
            except Exception as exc:
                self._parked_updates += 1
                phases["updates"] = self._parked_updates
                phases["open_steps"] = self._parked_updates
                self._charge(
                    phases,
                    getattr(self._worker, "_phase", None),
                    _span_ms(update_entered),
                )
                raise self._open_failure(
                    "open update failed: {}".format(exc.__class__.__name__),
                    self._parked_progress_at,
                    phases,
                    cause=exc,
                    no_progress_ms=self._parked_no_progress_ms,
                )
            self._parked_updates += 1
            phases["updates"] = self._parked_updates
            phases["open_steps"] = self._parked_updates
            label = getattr(self._worker, "_phase", None)
            self._charge(phases, label, _span_ms(update_entered))
            io_state = self._worker_io_state()
            if io_state == "progress":
                self._parked_progress_at = _ticks_ms()
            if self._worker_done(status):
                self._parked_response_ready = True
                phases["open_stall_ms"] = _span_ms(self._parked_progress_at)
                return PENDING
            if io_state == "wait":
                return PENDING
            # ``none`` is a source-proven generator budget yield (headers and
            # chunked parsing have these too), not evidence the peer is ready or
            # absent. Continue only under the outer busy/work caps.
            if _span_ms(self._parked_step_entered) >= budget_ms:
                return PENDING

    def _begin_parked_open(self, now, generation):
        phases = _open_phases()
        self._parked_generation = generation
        self._parked_last_generation = generation
        self._parked_phases = phases
        self._parked_started = _ticks_ms()
        self._parked_progress_at = self._parked_started
        self._parked_updates = 0
        self._parked_response_ready = False
        self._parked_step_entered = self._parked_started
        self._shim.install()
        phases["shim_ms"] = _span_ms(self._parked_started)
        entered = _ticks_ms()
        self._worker = self._connect_worker()
        phases["build_ms"] = _span_ms(entered)
        self._parked_no_progress_ms = _worker_no_progress_ms(self._worker)
        phases["open_deadline_ms"] = self._parked_no_progress_ms
        entered = _ticks_ms()
        self._start_request(self._worker, self._poll_request())
        phases["start_ms"] = _span_ms(entered)

    def _finish_parked_response(self):
        entered = _ticks_ms()
        phases = self._parked_phases
        try:
            decoded = parse_response(self._worker.http_status, self._worker.body)
        except AuthRejected:
            self._emit("token_rejected")
            raise LinkError("token rejected (401)")
        except AccessRevoked:
            self._emit("access_revoked")
            raise LinkRevoked("badge access revoked (403)")
        except PostgrestError as exc:
            raise LinkError("bad open response: {}".format(exc))
        finally:
            phases["finish_ms"] = _span_ms(entered)
        # Keep the current raw-parser escape taxonomy: `parse_poll_rows` is one
        # line outside the adjudication try in the blocking path too.
        return parse_poll_rows(decoded)

    def _reset_worker_io(self):
        sock = self._worker_socket()
        if sock is None:
            return
        reset = getattr(sock, "reset_io", None)
        state = getattr(sock, "io_state", None)
        if not callable(reset) or not callable(state):
            raise LinkError("parked open missing tracked TLS socket")
        reset()

    def _worker_io_state(self):
        sock = self._worker_socket()
        if sock is None:
            # Frozen fetch publishes `_sock` before its first generator yield.
            # A nonterminal update without one therefore means the ON artifact
            # did not install the coupled proxy, not that the network is idle.
            raise LinkError("parked open did not publish a tracked TLS socket")
        state = getattr(sock, "io_state", None)
        if not callable(state):
            raise LinkError("parked open missing tracked TLS socket")
        value = state()
        if value not in ("none", "wait", "progress"):
            raise LinkError("parked open returned an invalid I/O state")
        return value

    def _worker_socket(self):
        sock = getattr(self._worker, "_sock", None)
        if sock is None:
            # Host fixtures predate the pinned firmware's `_sock` spelling.
            sock = getattr(self._worker, "_socket", None)
        return sock

    def _charge_parked_step(self, phases, entered):
        span = _span_ms(entered)
        phases["open_busy_ms"] += span
        phases["open_frame_max_ms"] = max(
            phases["open_frame_max_ms"], span
        )

    def _finish_parked_open(self, outcome):
        phases = getattr(self, "_parked_phases", None)
        if phases is None:
            return False
        started = self._parked_started
        primed = self._primed_poll if outcome == "opened" else None
        # Invalidate before publishing or closing. Worker reset may make a
        # callback ready, and no continuation from this generation may observe
        # an active owner once terminal cleanup has begun.
        self._parked_generation = None
        self._parked_phases = None
        self._parked_response_ready = False
        self._finalize_phases(phases, started, outcome, parked=True)
        self._publish_phases(phases)
        if outcome != "opened":
            try:
                self._teardown_worker()
                self._primed_poll = None
            finally:
                # Cancellation is a BaseException on this stack. Restoration is
                # ownership cleanup and may never depend on Exception taxonomy.
                self._shim.restore()
        if outcome == "opened":
            self._emit("opened", primed=len(primed))
        return True

    def _finalize_phases(self, phases, started, outcome, parked):
        span = _span_ms(started)
        phases["total_ms"] = span
        phases["open_span_ms"] = span
        if not parked:
            # The legacy call owns one whole frame. Its explicit sleeps are the
            # only time not inside local establishment work.
            phases["open_busy_ms"] = max(0, span - phases["sleep_ms"])
            phases["open_steps"] = phases["updates"]
        phases["open_wait_ms"] = max(0, span - phases["open_busy_ms"])
        phases["outcome"] = outcome

    def _publish_phases(self, phases):
        """Record and emit one open's phase split. Never raises into the frame."""

        self.open_phases = phases
        self._emit("open_phases", **phases)

    def begin(self, kind, payload, now):
        if self._worker is None:
            raise LinkError("begin without an open socket")
        if self._inflight_kind is not None:
            raise LinkError("a request is already in flight")
        if kind == "poll" and self._primed_poll is not None:
            # Serve the stashed first-poll result rather than a fresh round trip.
            self._inflight_kind = "primed"
            self._response_ready = False
            return
        request = self._request_for(kind, payload)
        self._start_request(self._worker, request)
        self._inflight_kind = kind
        self._response_ready = False
        self._pump_count = 0

    def pump(self, now):
        kind = self._inflight_kind
        if kind is None:
            raise LinkError("pump without an in-flight request")
        if kind == "primed":
            self._inflight_kind = None
            result = self._primed_poll
            self._primed_poll = None
            return {"commands": result}
        if self._response_ready:
            # Clear first so a 401/403 or malformed body cannot strand the link
            # in a permanently-busy state. No worker update belongs to this
            # phase: MAX_PUMP_UPDATES is a budget of network-worker updates,
            # not rendered frames spent finishing a response.
            self._inflight_kind = None
            self._response_ready = False
            return self._finish(kind)
        self._pump_count += 1
        if self._pump_count > MAX_PUMP_UPDATES:
            self._inflight_kind = None
            self._response_ready = False
            raise LinkError("request exceeded the pump budget")
        try:
            status = self._worker.update()
        except Exception as exc:
            self._inflight_kind = None
            self._response_ready = False
            raise LinkError("update failed: {}".format(exc.__class__.__name__))
        if not self._worker_done(status):
            return PENDING
        self._response_ready = True
        return PENDING

    def close(self):
        self.abort_open(reason="close")
        self._teardown_worker()
        self._primed_poll = None
        self._inflight_kind = None
        self._response_ready = False
        self._shim.restore()

    def blocking_rpc(self, function, params=None):
        """Run a non-cadence RPC at an explicitly tolerant UI moment.

        Pair start/confirm/bind are wearer-driven transitions, not normal poll
        frames. They reuse the already-open verified socket but may block until
        the whole response arrives; callers must render the transition screen
        first. Poll and ack remain exclusively on the per-frame ``begin/pump``
        path.

        A 403 here raises :class:`LinkRevoked` to the CALLER and changes no
        transport state and no pair state: the loop enters ``REVOKED`` only from
        its own open/poll/ack path. A denied pairing RPC is the pairing flow's
        error to render, not a reason to declare the badge unpaired.
        """

        if self._worker is None:
            raise LinkError("blocking_rpc without an open socket")
        request = rpc_request(self._credentials, function, params,
                              self_badge_id=self.self_badge_id)
        return self._run_blocking(request, lambda decoded: decoded)

    # -- internals ---------------------------------------------------------

    def _connect_worker(self):
        """Build this session's worker. THE ONLY name-resolution moment.

        Everything that can touch DNS lives here, inside ``open()`` — the
        tolerant ``CONNECTING`` moment the UI renders behind a connecting screen
        — because a blocking ``getaddrinfo`` on a name that no longer resolves
        (an archived or deleted project) would otherwise stall a rendered frame.
        ``begin``/``pump``/``close`` reuse the worker and never resolve anything;
        ``credentials.connect_host()`` is just a cached string.

        A failed resolution is an ordinary connect failure, so map it into
        ``LinkError``: raw ``OSError``/``EAI_NONAME`` escaping ``open()`` would
        miss ``PollLoop``'s handler and hit the supervisor as a task crash
        instead of the intended jittered backoff.
        """

        try:
            return self._worker_factory(
                self._credentials.connect_host(), self._addr_info
            )
        except LinkError:
            raise
        except Exception as exc:
            raise LinkError("connect setup failed: {}".format(exc.__class__.__name__))

    def _poll_request(self):
        """The self-addressed poll, with the builder's refusal mapped to LinkError.

        ONE MAPPING FOR THE WHOLE FAMILY, and it is new with the ``_self`` RPCs.
        `poll_request` now refuses a missing or malformed ``p_badge_id``, and a
        raw `PostgrestError` escaping `open()` would reach `NetworkService.poll`'s
        containment as an unclassified fault -- a radio-generation bump and a
        backend rebuild for what is one bad request. Mapped here it travels the
        proven `LinkError` route the table and rpc errand kinds already use: one
        failed poll, the existing backoff ladder, nothing else disturbed.
        """

        try:
            return poll_request(self._credentials, self._poll_limit,
                                self_badge_id=self.self_badge_id)
        except PostgrestError as exc:
            raise LinkError("bad poll request: {}".format(exc))

    def _request_for(self, kind, payload):
        if kind == "poll":
            return self._poll_request()
        if kind == "policy":
            return policy_request(self._credentials,
                                  self_badge_id=self.self_badge_id)
        if kind == "ack":
            try:
                return ack_request(
                    self._credentials,
                    payload.get("id"),
                    payload.get("status"),
                    payload.get("result"),
                    self_badge_id=self.self_badge_id,
                )
            except PostgrestError as exc:
                raise LinkError("bad ack request: {}".format(exc))
        # THE TWO ERRAND KINDS (Card FT-B). Everything above is a fixed request
        # this module builds from the credentials alone; these two are built from
        # the caller's payload, which is why they are the only kinds whose
        # arguments can be wrong. Every failure mode is a `PostgrestError` from
        # the builder, mapped to `LinkError` below, so a malformed errand is one
        # failed errand and never a broken socket.
        if kind == "table":
            if not isinstance(payload, dict):
                raise LinkError("table errand payload must be an object")
            try:
                return table_request(
                    self._credentials,
                    payload.get("table"),
                    payload.get("method", "POST"),
                    payload.get("row"),
                    payload.get("prefer"),
                    payload.get("query"),
                    self_badge_id=self.self_badge_id,
                )
            except PostgrestError as exc:
                raise LinkError("bad table errand: {}".format(exc))
        if kind == "rpc":
            if not isinstance(payload, dict):
                raise LinkError("rpc errand payload must be an object")
            try:
                return rpc_request(self._credentials, payload.get("function"),
                                   payload.get("params"),
                                   payload.get("method", "POST"),
                                   self_badge_id=self.self_badge_id)
            except PostgrestError as exc:
                raise LinkError("bad rpc errand: {}".format(exc))
        raise LinkError("unknown request kind: {}".format(kind))

    def _finish(self, kind):
        try:
            decoded = parse_response(self._worker.http_status, self._worker.body)
        except AuthRejected as exc:
            # A 401 is a real verdict, not a blip: the token is bad. Surface it
            # as a distinct event, then raise LinkError so the transport tears
            # down and stays in fail-closed backoff (degraded-offline) rather
            # than hammering a doomed handshake every frame.
            self._emit("token_rejected")
            raise LinkError("token rejected (401)")
        except AccessRevoked as exc:
            # A 403 is the other verdict: this badge is revoked / the grant is
            # denied. LinkRevoked makes the transport stop for the session
            # instead of reconnect-polling a server that already said no.
            self._emit("access_revoked")
            raise LinkRevoked("badge access revoked (403)")
        except PostgrestError as exc:
            raise LinkError("bad response: {}".format(exc))
        if kind == "poll":
            return {"commands": parse_poll_rows(decoded)}
        if kind == "policy":
            return {"policy": parse_policy_row(decoded)}
        if kind == "table" or kind == "rpc":
            # UNPARSED, deliberately. An errand's requester knows what it asked
            # for and this module does not; adding a parser per errand would put
            # every future feature's response shape into the transport. `None` is
            # a legitimate answer (a `return=minimal` 204 has no body).
            return {"data": decoded}
        return {"ack": parse_ack_row(decoded)}

    def _charge(self, phases, label, span):
        """Charge one bracketed ``update()`` to the phase the firmware named."""

        if phases is None:
            return
        name = label if label in _OPEN_PHASE_KEYS else "other"
        phases[name + "_ms"] += span
        phases["worker_ms"] += span
        # AND THE MAXIMUM, beside the sums: ONE `update()` is one blocking call
        # (the generator advances by exactly one `next()`), so the largest span
        # charged here is the worst single hold this open put on the frame. The
        # cooperative sleep is deliberately NOT a candidate -- it is charged in
        # `_run_blocking` as `sleep_ms`, it is ours rather than a call we are
        # waiting on, and folding it in would hide the thing this number is for.
        phases["open_step_max_ms"] = max(phases["open_step_max_ms"], span)

    def _open_failure(self, message, progress_at, phases, cause=None,
                      no_progress_ms=None):
        """The open's failure, TYPED when it is the no-progress kind (NB-i).

        Returns a :class:`LinkStalled` when nothing proved the peer was there for
        ``no_progress_ms`` AND the failure is socket-level (an ``OSError`` out of
        the worker) or our own giving-up; a plain :class:`LinkError` otherwise.
        Both conditions and the device evidence for each are in
        `polltransport.LinkStalled`'s docstring, which is where a reader chasing
        the CX-5 jump will arrive.

        ``no_progress_ms`` is the ceiling the FIRMWARE was given for this open --
        `COLD_OPEN_NO_PROGRESS_MS` on the first open of a link,
        :data:`OPEN_NO_PROGRESS_MS` after it (Lane J) -- and defaults to the warm
        one so a caller that predates the allowance is unchanged.

        The stall is recorded on the phase record on the way past, so a reader
        can check the classification instead of trusting it. THE COMPARISON USES
        A LOCAL: no decision in this package is built from a published
        attribution field, and an AST guard keeps it that way.
        """

        if no_progress_ms is None:
            no_progress_ms = OPEN_NO_PROGRESS_MS
        stall = _span_ms(progress_at)
        if phases is not None:
            phases["open_stall_ms"] = stall
        if stall >= no_progress_ms and (cause is None
                                        or isinstance(cause, OSError)):
            return LinkStalled(message)
        return LinkError(message)

    def _run_blocking(self, request, parser, phases=None, no_progress_ms=None):
        """Drive one request to completion synchronously (open only).

        ``phases`` is an optional accounting record (see :func:`_open_phases`).
        When present each ``update()`` is bracketed and charged to the phase
        ``fetch.AsyncFetch`` reports being in AFTER the step — the label is set
        inside the generator section that step just ran, so reading it after is
        what attributes the step rather than the one before it. The cooperative
        sleep between steps is charged separately, because it is OURS.

        It also tracks WHEN THE PEER WAS LAST HEARD (`_OPEN_PROGRESS_PHASES`),
        which is what types a failure as the black-hole class rather than the
        refused one. See :meth:`_open_failure`.

        ``no_progress_ms`` is the deadline that class is declared at, and
        ``None`` means "ask the worker" -- which is what `blocking_rpc` gets,
        since it runs on the socket `open` already built.
        """
        if no_progress_ms is None:
            no_progress_ms = _worker_no_progress_ms(self._worker)
        entered = _ticks_ms()
        # ARMED BEFORE THE REQUEST, one statement ahead of the firmware arming
        # its own inactivity deadline inside `fetch()`. That ordering is what
        # makes our no-progress span at least the firmware's window, so a ceiling
        # failure cannot read one millisecond under the bar.
        progress_at = entered
        self._start_request(self._worker, request)
        if phases is not None:
            phases["start_ms"] = _span_ms(entered)
        updates = 0
        while True:
            updates += 1
            if updates > MAX_OPEN_PUMP_UPDATES:
                # OURS, not the firmware's: 30,000 updates with no terminal state
                # means the firmware's own ceiling did not fire, which is a
                # firmware question. `cause=None` says "we gave up", and if
                # nothing progressed in all that time it is the no-progress class
                # by definition rather than a refusal.
                raise self._open_failure(
                    "open request exceeded the pump budget", progress_at, phases,
                    no_progress_ms=no_progress_ms)
            entered = _ticks_ms()
            try:
                status = self._worker.update()
            except Exception as exc:
                if phases is not None:
                    phases["updates"] = updates
                    self._charge(phases, getattr(self._worker, "_phase", None),
                                 _span_ms(entered))
                raise self._open_failure(
                    "open update failed: {}".format(exc.__class__.__name__),
                    progress_at, phases, cause=exc,
                    no_progress_ms=no_progress_ms)
            label = getattr(self._worker, "_phase", None)
            if phases is not None:
                self._charge(phases, label, _span_ms(entered))
            if label in _OPEN_PROGRESS_PHASES:
                # A RESPONSE PHASE, so bytes came back: the peer is there and the
                # no-progress clock starts again from here.
                progress_at = _ticks_ms()
            if self._worker_done(status):
                break
            entered = _ticks_ms()
            _open_cooperate()
            if phases is not None:
                phases["sleep_ms"] += _span_ms(entered)
        if phases is not None:
            phases["updates"] = updates
            phases["open_stall_ms"] = _span_ms(progress_at)
        entered = _ticks_ms()
        try:
            decoded = parse_response(self._worker.http_status, self._worker.body)
        except AuthRejected:
            self._emit("token_rejected")
            raise LinkError("token rejected (401)")
        except AccessRevoked:
            self._emit("access_revoked")
            raise LinkRevoked("badge access revoked (403)")
        except PostgrestError as exc:
            raise LinkError("bad open response: {}".format(exc))
        finally:
            if phases is not None:
                phases["finish_ms"] = _span_ms(entered)
        return parser(decoded)

    def _start_request(self, worker, request):
        # DEVICE-VERIFY: the exact frozen AsyncFetch request keyword surface.
        # Body-carrying POST/PATCH is hardware-green; Card FT-B's schedule GET
        # verifies that this runtime also accepts `data=None`.
        on_error = getattr(worker, "on_error", None)
        if callable(on_error):
            # Stock AsyncFetch otherwise raises HTTPException before this link
            # can apply the binding rule that only a 401 is auth rejection.
            on_error(_suppress_http_status_exception)
        worker.fetch(
            request["path"],
            method=request["method"],
            # Frozen Badgeware v3.0.1 names the request-body parameter ``data``
            # (not ``body``). This exact surface was verified on Card E.
            data=request["body"],
            headers=request["headers"],
            blocking=False,
        )

    def _worker_done(self, status):
        active = self._worker
        return status == active.DONE or (
            getattr(active, "ERROR", None) is not None
            and status == active.ERROR
        )

    def _teardown_worker(self):
        worker = self._worker
        self._worker = None
        self._inflight_kind = None
        self._response_ready = False
        self._pump_count = 0
        if worker is None:
            return
        try:
            worker.reset()
        except BaseException:
            pass

    def _emit(self, event, **fields):
        if self._event_sink is None:
            return
        record = {"link": "badgelink_device", "event": event}
        record.update(fields)
        self._event_sink(record)
