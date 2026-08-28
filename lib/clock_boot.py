"""BadgeLink v2 time bootstrap: NTP -> plausibility gate -> PCF85063A.

Verified TLS needs a plausible wall clock to validate certificate dates (the JWT
``exp`` is checked against the SERVER's clock, not this one — build brief). The P4
pre-gate 2 proved the mechanical recipe on hardware: ``ntptime.settime()`` sets
the RP2350 clock, ``badgeware.rtc.localtime_to_rtc()`` copies it to the external
PCF85063A, and the firmware restores the external chip on the next boot. This
module productizes that recipe with the two policy gates the probe used ad hoc:

* a **build-time floor** — refuse any epoch before the firmware build date. This
  rejects the flat-battery default (the chip powers up in 2021) and a spoof that
  rolls the clock *backward* toward an expired certificate window.
* a **plausibility ceiling** — refuse an implausibly-far-future epoch.

NTP is unauthenticated (pre-gate 2 §"Negative"): these gates reject grossly stale
or future values but cannot authenticate an attacker-chosen time *inside* the
window. That residual is documented, not closed here.

The pure decision (:func:`evaluate_ntp`) and the orchestration
(:func:`bootstrap`) both run under CPython with injected fakes; only the real
``ntptime``/``rtc`` modules are device-bound.
"""


# 2026-08-08T00:00:00Z — the pinned firmware's build date (bw-1.28.0-3), the same
# floor the P4 pre-gate used. Override at the call site once a newer build ships.
BUILD_FLOOR_EPOCH = 1786147200
# 2099-12-31T23:59:59Z — nothing this fleet does is plausible past it.
MAX_PLAUSIBLE_EPOCH = 4102444799

#: THE NTP ERA-0 ROLLOVER INSTANT, in Unix seconds: 2036-02-07T06:28:16Z, which
#: is 2**32 seconds after the NTP epoch of 1900-01-01 (4294967296 - 2208988800).
NTP_ERA_ROLLOVER_EPOCH = 2085978496

#: HOW WIDE A BAND AROUND THAT INSTANT IS REFUSED. Seven days.
#:
#: ⚠ **THIS EXISTS BECAUSE NTP DID NOT FAIL -- IT SUCCEEDED WITH GARBAGE, and
#: that is the failure mode "fail soft when NTP fails" cannot see.** On a cold
#: boot the dev badge's `ntptime` mapped a zero/near-zero seconds field onto NTP
#: **era 1** and set the clock to 2036-02-07, a shift of about +9.46 years. Every
#: subsequent TLS handshake then failed with "certificate not yet valid", so the
#: badge had no transport at all for the rest of the boot -- and the plausibility
#: gate above waved it through, because 2036 sits comfortably inside
#: [build floor, 2099].
#:
#: A BAND RATHER THAN A TIGHTER CEILING, deliberately. Lowering
#: `MAX_PLAUSIBLE_EPOCH` to something that rejects 2036 would put a hard cliff in
#: the fleet's future: a badge booted past the new ceiling would refuse every NTP
#: reply, keep no clock, fail TLS and have no network -- trading a rare garbage
#: value for a guaranteed one. The rollover instant is a SPECIFIC arithmetic
#: artifact, so refusing a week around it costs this fleet nothing real (a badge
#: retries a second later and gets a true time) and leaves no cliff.
#:
#: IT ALSO UN-TRAPS A BADGE THAT ALREADY ADOPTED THE POISON, which is why the
#: guard lives in :func:`evaluate_ntp` and not only at the point of acceptance: a
#: clock already reading 2036 is now NOT "usable", so :func:`resync` treats it as
#: no clock at all and lets a good reply replace it -- instead of the shift bound
#: below refusing the correction as an implausible 9-year jump.
NTP_ERA_GUARD_S = 7 * 24 * 60 * 60

#: THE LARGEST JUMP A BADGE THAT ALREADY HAS A TRUSTED CLOCK WILL ADOPT. 30 days.
#:
#: The second half of the same lesson: a plausibility WINDOW cannot catch a value
#: that is wrong by years but inside it. This badge's master clock is the RP2350
#: powman always-on timer, and its real error is measured in SECONDS (Card FT-B
#: measured `execute_at` firing 4.918 s late), so 30 days is roughly five orders
#: of magnitude of headroom over any correction the product legitimately needs --
#: while still refusing the +9.46 years the era artifact produced.
#:
#: APPLIED ONLY WHEN THE EXISTING CLOCK IS ITSELF TRUSTED. With no plausible
#: clock there is nothing to measure a jump against, and refusing on that basis
#: would leave a flat-battery badge (the PCF powers up in 2021) permanently unable
#: to be corrected.
MAX_PLAUSIBLE_SHIFT_S = 30 * 24 * 60 * 60


class ClockError(Exception):
    """The bootstrap could not establish a trusted clock. Stay offline-first."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def evaluate_ntp(candidate_epoch, build_floor_epoch=BUILD_FLOOR_EPOCH,
                 max_epoch=MAX_PLAUSIBLE_EPOCH,
                 era_guard_s=NTP_ERA_GUARD_S):
    """Decide whether an NTP epoch is plausible enough to trust for TLS dates.

    Returns a decision dict ``{accepted, epoch_utc, reason}``. ``accepted`` is
    ``True`` only when ``build_floor_epoch <= candidate <= max_epoch`` AND the
    candidate is not inside the NTP era-rollover band -- see
    :data:`NTP_ERA_GUARD_S` for the boot this last clause exists because of.
    """
    if not isinstance(candidate_epoch, int) or isinstance(candidate_epoch, bool):
        raise ValueError("candidate epoch must be an integer")
    if not isinstance(build_floor_epoch, int) or isinstance(build_floor_epoch, bool):
        raise ValueError("build floor must be an integer")
    if build_floor_epoch > max_epoch:
        raise ValueError("build floor cannot exceed the plausibility ceiling")
    if candidate_epoch < build_floor_epoch:
        return {"accepted": False, "epoch_utc": candidate_epoch, "reason": "before_build_floor"}
    if candidate_epoch > max_epoch:
        return {"accepted": False, "epoch_utc": candidate_epoch, "reason": "implausible_future"}
    if era_guard_s > 0:
        distance = candidate_epoch - NTP_ERA_ROLLOVER_EPOCH
        if distance < 0:
            distance = -distance
        if distance <= era_guard_s:
            return {"accepted": False, "epoch_utc": candidate_epoch,
                    "reason": "ntp_era_rollover"}
    return {"accepted": True, "epoch_utc": candidate_epoch, "reason": "plausible"}


def bootstrap(
    ntptime_module,
    rtc,
    read_epoch,
    build_floor_epoch=BUILD_FLOOR_EPOCH,
    max_epoch=MAX_PLAUSIBLE_EPOCH,
):
    """Run the NTP -> gate -> external-RTC recipe. Raise :class:`ClockError` on reject.

    * ``ntptime_module`` — exposes ``settime()`` (sets the system clock from NTP).
    * ``rtc`` — the Badgeware external-RTC object; ``localtime_to_rtc()`` copies
      the (now NTP-set) system time onto the PCF85063A.
    * ``read_epoch`` — callable returning the current system epoch as an int
      (``lambda: int(time.time())`` on device); read AFTER ``settime``.

    The external chip is written ONLY when the epoch passes both gates, so a
    rejected (stale/spoofed) NTP result never poisons the battery-backed clock.
    Returns the accepted decision dict.
    """
    try:
        ntptime_module.settime()
    except Exception as exc:
        raise ClockError("ntp_settime_failed: {}".format(exc.__class__.__name__))
    try:
        epoch = int(read_epoch())
    except Exception as exc:
        raise ClockError("clock_read_failed: {}".format(exc.__class__.__name__))
    decision = evaluate_ntp(epoch, build_floor_epoch, max_epoch)
    if not decision["accepted"]:
        raise ClockError("ntp_rejected: {}".format(decision["reason"]))
    try:
        rtc.localtime_to_rtc()
    except Exception as exc:
        raise ClockError("external_rtc_write_failed: {}".format(exc.__class__.__name__))
    return decision


def resync(
    ntptime_module,
    rtc,
    read_epoch,
    build_floor_epoch=BUILD_FLOOR_EPOCH,
    max_epoch=MAX_PLAUSIBLE_EPOCH,
    max_shift_s=MAX_PLAUSIBLE_SHIFT_S,
    clock_verified=True,
):
    """Correct the clock, whether or not the badge already believes it is right.

    THIS EXISTS BECAUSE A PLAUSIBILITY GATE IS NOT A CORRECTNESS GATE, and Card
    FT-B measured the difference. :func:`bootstrap` used to be reached only when
    ``evaluate_ntp`` REFUSED the clock the badge already had -- a window from
    2026-08-08 to 2099-12-31. Inside that window nothing ever asked NTP again, so
    a badge whose clock was set once and was WRONG stayed wrong for the whole
    conference. On the reference badge two ``execute_at`` commands fired
    4.918 s and 4.934 s late against the server's own timestamp, and the second
    was after a physical RESET.

    THE RESET IS THE PART THAT NAMES THE MECHANISM. On RP2350 ``time.time()`` IS
    the powman always-on timer, read straight out of hardware
    (``ports/rp2/mphalport.c:186-189``); it keeps counting across a reset while
    power is present, and the firmware's boot sync only ever copies
    ``localtime`` -> PCF85063A (``badgeware/rtc.py:15-19``, the ``elif`` that
    reads the PCF back is skipped whenever the system year is already >= 2025).
    So the always-on timer is the master, no boot corrects it, and this function
    is the only thing in the product that can.

    FAIL-SOFT, AND THE ASYMMETRY IS THE WHOLE DESIGN. A badge with no server must
    still boot and run, and a venue that blocks UDP/123 must not cost the fleet
    its transport:

    * the badge already has a plausible clock -> a failed sync is REPORTED and
      the old clock is kept. Returns ``synced: False``.
    * the badge has no plausible clock -> raise :class:`ClockError`, exactly as
      before, because verified TLS cannot validate a certificate without one.

    ``clock_verified`` says whether the clock this call is measuring against was
    itself established by a successful sync IN THIS BOOT. It gates the shift bound
    only. Pass ``False`` for the first resync after a cold boot, where the clock
    can only have come from the battery-backed PCF and has been verified by
    nothing; the default is ``True`` so an existing caller keeps today's behaviour.

    READ BEFORE WRITE, which :func:`bootstrap` alone cannot do. ``settime()``
    writes ``machine.RTC`` and only THEN can anything be gated, so a garbage
    reply lands on the master clock before it can be refused -- and the next boot
    copies it to the PCF. When the module offers the frozen ``ntptime``'s
    read-only ``time()``, the candidate is gated FIRST and a refused reply never
    touches a clock at all. Two UDP round trips per connect is the price, and a
    connect is a per-boot event, not a per-frame one.

    RESIDUAL, recorded rather than closed: two replies one round trip apart can
    disagree, so ``settime()`` may still write a value the pre-gate never saw.
    :func:`bootstrap`'s own post-write gate catches it and refuses the PCF, but
    the system clock is already written. Closing that needs a clock WRITE seam
    this module deliberately does not own (it touches no RTC hardware); it is the
    same unauthenticated-NTP residual this module's docstring already states.

    Returns ``{"epoch", "synced", "shift", "reason"}``. ``shift`` is the seconds
    the clock MOVED (positive means it was running slow), reported so a fleet's
    drift is observable instead of inferred -- never subtracted as a constant.
    """

    try:
        before = int(read_epoch())
    except Exception as exc:
        raise ClockError("clock_read_failed: {}".format(exc.__class__.__name__))
    usable = evaluate_ntp(before, build_floor_epoch, max_epoch)["accepted"]

    def refuse(reason):
        if not usable:
            raise ClockError(reason)
        return {"epoch": before, "synced": False, "shift": 0, "reason": reason}

    reader = getattr(ntptime_module, "time", None)
    if callable(reader):
        try:
            candidate = int(reader())
        except Exception as exc:
            return refuse("ntp_unreachable: {}".format(exc.__class__.__name__))
        decision = evaluate_ntp(candidate, build_floor_epoch, max_epoch)
        if not decision["accepted"]:
            return refuse("ntp_rejected: {}".format(decision["reason"]))
        if usable and clock_verified and max_shift_s > 0:
            # THE SHIFT BOUND (:data:`MAX_PLAUSIBLE_SHIFT_S`). A window cannot
            # catch a value that is wrong by years but inside it, and this badge
            # HAD one: 2036-02-07 accepted, every TLS handshake refused after it.
            # Only checked against a clock that is itself trusted -- with nothing
            # plausible to compare to, a jump is the correction rather than the
            # fault.
            #
            # ⚠ PLAUSIBLE IS NOT VERIFIED, AND ``clock_verified`` IS THAT
            # DISTINCTION. `usable` only says the clock sits inside
            # [build floor, ceiling] and outside the era band. A clock RESTORED
            # FROM THE PCF has never been checked against anything: on RP2350 the
            # powman timer is the master and resets when power is removed, so the
            # firmware's boot sync reads the external chip back (the `elif` that
            # only runs while the system year is < 2025) and whatever the PCF held
            # becomes "the clock the badge already has". Bounding a correction
            # against THAT is bounding it against an unverified value -- and
            # because `refuse` is fail-soft for a usable clock, the refusal KEEPS
            # the unverified value and declines the true one. A badge that came
            # back from hardware shipping mode with a stale or garbage PCF would
            # then hold a wrong clock for the whole conference, failing every TLS
            # handshake, with nothing able to correct it.
            #
            # So the bound applies only once THIS BOOT has actually landed a
            # sync. Before that, a jump is the correction, exactly as it already
            # is when no plausible clock exists at all -- the same rule, drawn one
            # notch tighter. After it, the bound is unchanged and still refuses
            # the +9.46 years the era artifact produced.
            jump = candidate - before
            if jump < 0:
                jump = -jump
            if jump > max_shift_s:
                return refuse("ntp_rejected: implausible_shift")

    try:
        bootstrap(ntptime_module, rtc, read_epoch, build_floor_epoch, max_epoch)
    except ClockError as exc:
        return refuse(exc.reason)

    try:
        after = int(read_epoch())
    except Exception as exc:
        raise ClockError("clock_read_failed: {}".format(exc.__class__.__name__))
    return {"epoch": after, "synced": True, "shift": after - before,
            "reason": "synced"}
