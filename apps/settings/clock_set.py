"""The Settings tile's ONE clock writer, and its whole extent.

A SEPARATE MODULE FOR THE SAME REASON `score_wipe` AND `brightness_store` ARE
ONE: the model is drawing-agnostic and I/O-free by contract, the app's
`__init__` cannot be imported by a test (it needs the firmware's injected
globals), and a path that writes a clock the whole product's TLS depends on is
the last thing in this tile that should be exercisable only on a device.
`settings/tests/test_settings_clock.py` drives this file directly.

**BOTH CLOCKS, SYSTEM FIRST, AND THE ORDER IS THE CRASH BEHAVIOUR RATHER THAN
STYLE.** The badge has two:

| Clock | Reached by | Tuple order |
|---|---|---|
| RP2350 always-on timer | `time.localtime()`, `machine.RTC()` | `(y, m, d, weekday, H, M, S, subseconds)` |
| External PCF85063A | the injected `rtc` builtin | written by `localtime_to_rtc()` |

The firmware's boot sync copies **localtime -> PCF** (`badgeware/rtc.py:15-19`),
never the reverse while the system year is already >= 2025. So:

* a write that touches only the SYSTEM clock is lost the moment power is
  removed, because the always-on timer is powered by the battery this badge is
  about to be unplugged from -- and the wearer sets the clock twice;
* a write that touches only the PCF is silently reverted on the next boot of any
  badge that has ever slept, because that boot copies localtime over it;
* and if an exception lands BETWEEN the two, system-first leaves a correct
  localtime that the next boot copies into the PCF, so the badge heals itself.
  The other order leaves a good PCF beside a bad localtime and the next boot
  clobbers the good value with the bad one.

`benchmark/SCHEDULE-CLOCK-GATE.md` is the record of that mechanism being proved
on the reference badge (VAL-052-DC, 2026-08-22, N=2) for the app that used
to own this path, and its own closing note asks a future clock-writing feature
to reuse the reasoning. This is that feature.

THE RESULT HAS THREE VALUES AND NOT TWO, because the middle one is a promise the
wearer can otherwise be told wrongly: a system write that succeeds beside a PCF
write that fails IS the clock for this session and IS lost with the battery.
Saying "saved" there would be the one direction nothing later corrects.

MICROPYTHON. `time` only, no f-strings, and `machine` is imported lazily inside
the write so this module stays importable on the host.
"""

import time


#: Both writes landed: the badge holds this time across a power loss.
SET = "set"
#: The system clock took it and the external chip did not. True for this
#: session, gone with the battery -- and the wearer is told exactly that.
VOLATILE = "volatile"
#: Nothing took it.
FAILED = "failed"


class ClockSet:
    """Read the badge's wall clock, and write a wearer's hand-set time to both.

    NEVER RAISES. It is called from inside `launch()`, where an escaping
    exception reaches the firmware's `fatal_error()` and `machine.reset()` -- so
    a badge whose external chip is unreachable would turn "set my clock" into a
    reboot on the exact screen offering the wearer a way to repair it.

    EVERY COLLABORATOR IS INJECTED, and `rtc` in particular cannot be anything
    else: it is a Badgeware-injected builtin, not an importable module, so a
    module-scope `import` of it would fail on the host and a bare name would
    fail at test time. `None` means "this badge has no external chip reachable
    from here", which downgrades a write to :data:`VOLATILE` rather than failing
    it -- the system clock is still the one TLS reads this session.
    """

    def __init__(self, rtc=None, machine_module=None, localtime=None):
        self._rtc = rtc
        self._machine = machine_module
        self._localtime = localtime if localtime is not None else time.localtime

    def _machine_module(self):
        """`machine`, imported on the press rather than at module scope.

        A module-scope import would make this file unimportable under CPython,
        which is where every test of it runs. The cost is one `__import__` on a
        once-per-press path, and the app's own guarded-import discipline is the
        precedent: a raise here is caught by `write` below.
        """
        if self._machine is not None:
            return self._machine
        import machine

        return machine

    def read(self):
        """The badge's current wall clock as ``(y, m, d, H, M)``, or ``None``.

        THE SYSTEM CLOCK, NOT THE EXTERNAL CHIP, and that is the reading the
        screen has to seed from: on RP2350 `time.time()` IS the powman always-on
        timer and it is what `clock_boot.evaluate_ntp` gates and what verified
        TLS validates a certificate against. The PCF is only ever read at boot.

        Never raises: a clock that cannot be read seeds the editor from the
        build floor instead, which is a worse starting point and not a crash.
        """
        try:
            value = self._localtime()
        except Exception:  # noqa: BLE001 - a reset is the alternative
            return None
        try:
            return (int(value[0]), int(value[1]), int(value[2]),
                    int(value[3]), int(value[4]))
        except Exception:  # noqa: BLE001 - a stand-in with a short tuple
            return None

    def write(self, year, month, day, weekday, hour, minute):
        """Set both clocks. Returns :data:`SET`, :data:`VOLATILE` or
        :data:`FAILED`.

        SECONDS ARE ZERO, AND THAT IS THE METHOD'S OWN PRECISION. A wearer reads
        a phone and presses a key; the entry cannot deliver seconds, so claiming
        them would be a digit nobody measured. `clock_boot.resync` replaces the
        whole value the moment a server is reachable, to the second.

        THE WEEKDAY IS THE CALLER'S, computed in `settings_model` from the same
        date, because ONE number feeds this write: `machine.RTC().datetime`
        takes Monday=0 and `rtc.py:26` puts `time.localtime()[6]` -- the same
        numbering -- into the PCF's weekday register, which `rtc.py:30` reads
        back straight through.
        """
        try:
            self._machine_module().RTC().datetime(
                (year, month, day, weekday, hour, minute, 0, 0))
        except Exception as error:  # noqa: BLE001 - a reset is the alternative
            print("SETTINGS_CLOCK failed=system err={}".format(
                error.__class__.__name__))
            # NOTHING ELSE IS ATTEMPTED. Writing the PCF over a system clock that
            # refused the value is the exact order this module's docstring calls
            # the harmful one: the next boot would copy the bad localtime over
            # the good chip.
            return FAILED
        if self._rtc is None:
            return VOLATILE
        try:
            self._rtc.localtime_to_rtc()
        except Exception as error:  # noqa: BLE001
            print("SETTINGS_CLOCK failed=external err={}".format(
                error.__class__.__name__))
            return VOLATILE
        return SET
