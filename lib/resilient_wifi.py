"""Nonfatal cooperative Wi-Fi association for Badgeware v3.

The native WLAN call can hard-hang on invalid inputs, so validation must happen before
the driver call. This module never draws a fatal screen or resets the machine.
"""

import time

try:
    import network as _network
except ImportError:
    _network = None


OFF = "off"
CONNECTING = "connecting"
ONLINE = "online"
BACKOFF = "backoff"


#: THE SMALLEST DELAY A JITTERED BACKOFF MAY RETURN, and it is deliberately
#: tiny because the real floor is DERIVED: every draw is at least `rung // 2`,
#: i.e. half the caller's own base, so the only thing left to rule out is the
#: degenerate configuration where integer division reaches zero -- and a
#: zero-delay backoff is the busy-wait this class exists to prevent.
#:
#: TWO WRONG FLOORS WERE TRIED FIRST and both are worth recording, because each
#: looked right. A floor at `backoff_base_ms` returns the base for EVERY draw on
#: the first rung, which re-synchronises the fleet exactly where it hurts most --
#: the fix wearing the defect's clothes. An absolute 100 ms silently overrode any
#: caller's base below 200 ms, and those bounds are a published contract this
#: class must honour, not suggestions.
BACKOFF_FLOOR_MS = 1

#: HOW LONG A LINK MUST HOLD BEFORE SUCCESS FORGIVES THE LADDER.
#:
#: **DERIVED, NOT CHOSEN: it is the instance's own ``backoff_max_ms``.** The rule is
#: that a link must stay up at least as long as the worst penalty it would otherwise
#: have paid -- once it has been connected longer than the biggest backoff on the
#: ladder, the ladder has nothing left to say about it. Nothing to keep in step with
#: a second number, and it moves automatically if the ceiling ever does.
#:
#: WHY A THRESHOLD AT ALL, when `_fail`'s counter is the evidence and a completed
#: association is evidence against it. Because **an association is cheap and a
#: flapping AP completes them all day.** Forgiving on the FIRST connected tick meant
#: every flap reset the ladder to the base, so N flaps bought N full-price connect
#: cascades -- and on a dead route each cascade is free to hit a `getaddrinfo` that
#: blocks 13.1-14.0 s and cannot be bounded. That is the owner's "freezes multiple
#: times", and nothing in this class ever became more reluctant.
#:
#: THE HERD ARGUMENT THAT PUT THE RESET HERE IN THE FIRST PLACE IS PRESERVED, which
#: is why this is a threshold and not a deletion: 800 badges must not accumulate
#: permanent reluctance from one bad morning. A badge that genuinely recovers holds
#: the link for a minute and sheds the whole ladder; a badge whose AP drops every
#: twenty seconds never earns that and stays polite. The two cases are told apart by
#: SUSTAINED success, which is the only signal that distinguishes them.
FORGIVE_AFTER_CONNECTED_MS = None   # -> `backoff_max_ms`, see `_forgive_after_ms`

#: THE FLOOR OF THE PER-ATTEMPT TIMEOUT JITTER, as a percentage of `timeout_ms`.
#: 60 means an attempt gives up somewhere in [0.6, 1.0] x the configured timeout.
#: Chosen against a MEASURED number rather than a feeling: association on this
#: hardware completes in 3.2-4.8 s, so 60% of the shipped 45 s is still ~6x the
#: time a succeeding attempt needs and cannot abandon one. What it buys is an
#: 18-second spread on the moment a synchronised fleet admits failure, which no
#: amount of backoff jitter can produce because the backoff rungs (1-60 s) are
#: applied AFTER that moment.
TIMEOUT_JITTER_FLOOR = 60


def _default_rand01():
    """A fraction in [0, 1). ``os.urandom`` is the one source both runtimes have.

    The same shape `polltransport._default_rand01` and
    `pushlink._default_rand01` use, spelled here rather than imported: this
    module installs to `/system/lib` and a module-scope import of a sibling a
    half-refreshed lib might not carry raises inside `launch()`, which resets the
    badge.
    """

    import os

    raw = os.urandom(2)
    return (raw[0] << 8 | raw[1]) / 65536.0


def _ticks_ms():
    return time.ticks_ms()


def _ticks_add(value, delta):
    return time.ticks_add(value, delta)


def _ticks_diff(left, right):
    return time.ticks_diff(left, right)


def _byte_length(value, label):
    if not isinstance(value, (str, bytes)):
        raise ValueError("{} must be text or bytes".format(label))
    return len(value.encode("utf-8") if isinstance(value, str) else value)


def validate_credentials(ssid, password):
    ssid_bytes = _byte_length(ssid, "SSID")
    if ssid_bytes < 1 or ssid_bytes > 32:
        raise ValueError("SSID must be 1-32 UTF-8 bytes")
    password_bytes = _byte_length(password, "Wi-Fi password")
    if password_bytes > 64:
        raise ValueError("Wi-Fi password must be at most 64 UTF-8 bytes")


class ResilientWiFi:
    def __init__(
        self,
        wlan=None,
        timeout_ms=45000,
        backoff_base_ms=1000,
        backoff_max_ms=60000,
        ticks_ms=None,
        ticks_add=None,
        ticks_diff=None,
        rand01=None,
    ):
        if wlan is None:
            if _network is None:
                raise RuntimeError("network module unavailable")
            wlan = _network.WLAN(_network.STA_IF)
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        if backoff_base_ms <= 0 or backoff_max_ms < backoff_base_ms:
            raise ValueError("invalid backoff bounds")
        self.wlan = wlan
        self.timeout_ms = int(timeout_ms)
        self.backoff_base_ms = int(backoff_base_ms)
        self.backoff_max_ms = int(backoff_max_ms)
        self._ticks_ms = ticks_ms or _ticks_ms
        self._ticks_add = ticks_add or _ticks_add
        self._ticks_diff = ticks_diff or _ticks_diff
        #: THE ONLY RANDOM SOURCE IN LAYER 1, injectable so a fleet simulation
        #: can drive independent badges and a fixture can be deterministic. Drawn
        #: once per failed attempt, never per frame.
        self._rand01 = rand01 or _default_rand01
        self.state = OFF
        self.reason = "idle"
        self.failures = 0
        self.attempts = 0
        self.connected_ms = None
        self._ssid = None
        self._password = None
        self._deadline = None

    def _now(self, now):
        return self._ticks_ms() if now is None else now

    def _forgive_after_ms(self):
        """How long connected before the ladder is forgiven. See the constant."""

        if FORGIVE_AFTER_CONNECTED_MS is not None:
            return int(FORGIVE_AFTER_CONNECTED_MS)
        return self.backoff_max_ms

    def _due(self, now):
        return self._deadline is not None and self._ticks_diff(now, self._deadline) >= 0

    def _backoff_ms(self):
        """This attempt's delay: the ladder's rung, JITTERED.

        ⚠ **THERE WAS NO JITTER HERE UNTIL 2026-08-26, AND THIS IS THE LAYER
        UNDERNEATH EVERY OTHER RETRY.** The return value was a pure function of
        one integer, so every badge in a hall produced a byte-identical attempt
        sequence and differed only by which rendered frame it noticed the outage
        in -- a ~27 ms spread. Driven against this class,
        `benchmark/host/wifi-herd-politeness.py` put **800 of 800 badges inside
        the same one-second window**, in both arms.

        WHY IT MATTERS MORE THAN IT LOOKS. Layers 2 and 3 (`polltransport`,
        `pushlink`) jitter everywhere and say so in their docstrings -- but
        association is UPSTREAM of both, so nothing above this line can
        compensate for a lockstep here. The end-state addendum names BOOT_JITTER,
        cadence jitter and the per-badge rate bucket as what absorbs the ~800-badge
        San Francisco morning; every one of those is layer 2 or 3, and the AP
        meets the herd before any of them applies. The England-to-SF path sharpens
        it: a badge that missed deep sleep has been failing to associate for the
        whole flight, so its ladder is pinned at the ceiling -- and so is every
        other badge's, identically, at the moment the venue SSID appears.

        UNIFORM OVER THE RUNG'S UPPER HALF -- [rung/2, rung) -- and each of the
        three candidate shapes was measured against this gate rather than argued
        about:

        * FULL JITTER, [0, rung): halves the mean interval, so it DOUBLES how
          often a badge calls the driver. It took the England-boot arm from one
          attempt per 53 s to one per 22 s per badge, and §7.1 asks for the
          opposite ("keep radio retries gentle and infrequent so the England boot
          doesn't stutter", because `wlan.connect` is a known BLOCKING call).
        * EQUAL JITTER, [rung/2, 3*rung/2): keeps the mean, but OVERSHOOTS
          `backoff_max_ms` -- it produced an 85,206 ms rung against a documented
          60,000 ms ceiling, which is a contract this class publishes and a
          caller may configure.
        * THIS ONE: never exceeds the rung, so `backoff_max_ms` still means what
          it says; keeps 75% of the ladder's designed cadence; and spreads the
          fleet across half a rung, which at the 60 s ceiling is a 30-second
          window and ~27 associations a second instead of 800 in one instant.

        Clamping full or equal jitter at the ceiling was rejected for the reason
        the jitter exists: every draw above the cap piles onto the cap, which
        rebuilds a synchroniser exactly where the fleet spends most of an outage.
        """

        shift = min(max(0, self.failures - 1), 10)
        rung = min(self.backoff_max_ms, self.backoff_base_ms * (1 << shift))
        try:
            fraction = self._rand01()
        except Exception:
            # A broken entropy source must not stop the radio from retrying; the
            # midpoint still advances the ladder, it just spreads nothing.
            fraction = 0.5
        if fraction < 0:
            fraction = 0.0
        elif fraction >= 1:
            fraction = 0.999
        # The floor is `BACKOFF_FLOOR_MS` and its whole job is "never zero" --
        # see that constant for the two larger floors that were tried and were
        # both wrong.
        half = rung // 2
        delay = half + int(fraction * (rung - half))
        return delay if delay > BACKOFF_FLOOR_MS else BACKOFF_FLOOR_MS

    def _attempt_timeout_ms(self):
        """How long THIS attempt waits before calling itself failed. Jittered.

        **THE SECOND SYNCHRONISER, and the backoff jitter cannot reach it.** A
        fleet that starts associating together and is answered by nothing fails
        together -- not because of the ladder, but because every badge gives up at
        exactly `timeout_ms`. Measured against the shipped class: the first retry
        after a synchronised 45 s timeout put 800 of 800 badges in one second,
        with a fully jittered ladder underneath it, because a 1,000 ms rung
        cannot spread a 45,000 ms period.

        JITTERED DOWNWARD ONLY, and that is what makes it safe: a real
        association on this hardware completes in a measured 3.2-4.8 s, so even
        the shortest draw here (60% of 45 s = 27 s) is five to eight times the
        time a succeeding attempt needs. Nothing that was going to succeed is
        abandoned; only the wait before admitting a failure is de-correlated.
        """

        span = self.timeout_ms - (self.timeout_ms * TIMEOUT_JITTER_FLOOR) // 100
        if span <= 0:
            return self.timeout_ms
        try:
            fraction = self._rand01()
        except Exception:
            fraction = 0.5
        if fraction < 0:
            fraction = 0.0
        elif fraction >= 1:
            fraction = 0.999
        return self.timeout_ms - int(fraction * span)

    def _contain(self, operation, *args):
        try:
            operation(*args)
            return True
        except Exception:
            return False

    def start(self, ssid, password="", now=None):
        validate_credentials(ssid, password)
        self._ssid = ssid
        self._password = password
        self.failures = 0
        return self._begin(self._now(now))

    def _begin(self, now):
        self.attempts += 1
        self.connected_ms = None
        if not self._contain(self.wlan.active, True):
            return self._fail("radio_activate_error", now)
        try:
            self.wlan.connect(self._ssid, self._password)
        except Exception:
            return self._fail("connect_exception", now)
        self.state = CONNECTING
        self.reason = "joining"
        self._deadline = self._ticks_add(now, self._attempt_timeout_ms())
        return self.state

    def _fail(self, reason, now):
        self._contain(self.wlan.disconnect)
        self.failures += 1
        self.state = BACKOFF
        self.reason = reason
        self.connected_ms = None
        self._deadline = self._ticks_add(now, self._backoff_ms())
        return self.state

    def tick(self, now=None):
        now = self._now(now)
        if self.state == OFF:
            return self.state
        if self.state == BACKOFF:
            return self._begin(now) if self._due(now) else self.state

        try:
            connected = bool(self.wlan.isconnected())
        except Exception:
            return self._fail("isconnected_exception", now)

        if connected:
            if self.state != ONLINE:
                self.state = ONLINE
                self.reason = "connected"
                self.connected_ms = now
                self._deadline = None
            elif self.failures and self.connected_ms is not None and (
                    self._ticks_diff(now, self.connected_ms)
                    >= self._forgive_after_ms()):
                # SUSTAINED success, not the first tick of it. See
                # :data:`FORGIVE_AFTER_CONNECTED_MS`. `connected_ms` is already
                # stamped on the transition above and already cleared by `_fail`,
                # so a flap resets the clock without a second field to keep in
                # step -- and wrap-safety comes from the same `_ticks_diff` seam
                # every other deadline here uses.
                self.failures = 0
                self.reason = "forgiven"
            return self.state

        if self.state == ONLINE:
            return self._fail("connection_lost", now)

        try:
            status = self.wlan.status()
        except Exception:
            status = None
        if isinstance(status, int) and status < 0:
            return self._fail("status_{}".format(status), now)
        if self._due(now):
            return self._fail("timeout", now)
        return self.state

    def request_reconnect(self, now=None):
        if self._ssid is None:
            return self.state
        self._contain(self.wlan.disconnect)
        return self._begin(self._now(now))

    def stop(self, power_down=True, clear_credentials=False):
        self._contain(self.wlan.disconnect)
        if power_down:
            self._contain(self.wlan.active, False)
        self.state = OFF
        self.reason = "stopped"
        self.connected_ms = None
        self._deadline = None
        if clear_credentials:
            self._ssid = None
            self._password = None
        return self.state

    def snapshot(self):
        return {
            "state": self.state,
            "reason": self.reason,
            "attempts": self.attempts,
            "failures": self.failures,
            "connected_ms": self.connected_ms,
        }
