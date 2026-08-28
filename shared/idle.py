"""Time since the wearer last touched the badge.  One clock, one set of rungs.

THIS FILE IS THE CANONICAL COPY.  EDIT IT HERE AND NOWHERE ELSE.

    python3 scripts/sync_ui.py            # refresh every vendored copy
    python3 scripts/sync_ui.py --check    # fail if any has drifted

THE OWNER'S DESIGN (`docs/design/idle-and-off.md` §1), and this module is the
whole of its clock.  **THE TWO NUMBERS WERE RETUNED ON 2026-08-24, owner
verbatim: *"should dim after 20 seconds of being inactive on the home screen and
then switch to the nametag after another 10 seconds"*.**  They were 30 s and 45 s
for one day.

    20 s of no input   the screen DIMS.  The dim IS the idle signal; nothing
                       else announces it.
    30 s of no input   the badge opens the NAMETAG.  The default resting state
                       of this product is being a badge.
    ever               NOTHING.  There is no third rung.  The automatic path
                       always returns to the badge, never to a dark panel.

THE RUNGS BELOW ARE THE HOME SCREEN'S, and that is a scope the ruling states in
its own first clause -- "on the home screen".  They are this module's DEFAULTS
because the launcher is the surface the ruling is about and it takes them without
an argument.  `setup` deliberately does not: see `CARD_DIM_MS`.

WHY THERE IS NO SLEEP RUNG, stated here because this is the file somebody would
add one to.  Sleeping is a thing a person chooses (the Settings row), and the
measured battery rows make the case rather than the taste: the worst run-to-flat
workload on this hardware is 8 h 28-30 m (`VAL-054-WIFI`) and the best is
11 h 14-16 m (`VAL-050`), so the product survives the conference day it was
built for without ever sleeping itself.  An auto-sleep would spend the badge's
whole reason for existing -- being readable on a lanyard -- to buy an hour
nobody needs.

WHY AN ABSOLUTE CLOCK AND NOT ACCUMULATED DELTAS.  `launcher/menu/ui.py`'s hold
gesture accumulates `badge.ticks_delta` and RESETS on a poll gap over 250 ms,
fail-closed, because a 2026-08-16 hardware trace reproduced a 29 ms tap being
classified as a completed hold through an absolute-counter path.  That is the
right rule for proving a key stayed DOWN and the wrong one for proving nobody
touched anything: an idle timer wants the OPPOSITE default, because a stalled
frame loop is evidence of exactly what it is looking for.  Failing closed here
would mean a slow app never idles.

    So this class reads an absolute millisecond clock and fails OPEN by
    construction -- a 900 ms frame credits 900 ms of idleness, no rule required.
    `docs/design/idle-and-off.md` §3.5 names this as a decision a builder must
    make consciously; this is it, made the other way from the hold's, on
    purpose, and the two live in different files so neither inherits the other's
    reason.

MILLISECONDS, NEVER FRAMES, which the hold clock got right and this copies: the
launcher's frame rate moves with what it is drawing (43.72 FPS against 33.87
measured, film against theme), so a counted idle timer would be a 20-second
timer on one skin and a 30-second timer on another.

WHAT COUNTS AS INPUT is the CALLER'S question and this module refuses to guess
it.  `touch(now)` is the only way the clock is reset, and every caller passes
its own definition -- the launcher's is any of five keys down, `setup`'s is
`badge.held()`.  A module that read `badge.held()` itself could not be
stepped off the device at all, which is the same argument
`identity_keyboard` and `card_app` both record for taking their input as an
argument.

WHO WIRES THIS, AND THE ONE APP THAT DELIBERATELY DOES NOT.  The launcher and
`setup`, and that is the whole list.  **`nametag` wired this module between
2026-08-23 and 2026-08-24 and no longer does** -- owner ruling: *"The nametag app
currently dims after a timeout.  Nametag should never dim"*.  It is the resting
state this ladder exists to REACH, so a dim there is the ladder undoing its own
destination; it holds the wearer's chosen brightness for as long as it is open.
`nametag/badge/nametag/idle.py` was deleted with the seam, so this file is
vendored into two apps rather than three.

`busy` IS PART OF THE DESIGN AND NOT AN AFTERTHOUGHT (§4.3).  A running game is
not idle in any sense a wearer would recognise even when no button has been
pressed for twenty seconds -- Snake moves on its own -- so an idle timer that
dims a running game is a bug.  `poll(now, busy=True)` says "I am doing
something", and it holds the clock exactly as an input would.  No game wires
this module today; the seam exists so that the app which needs it does not have
to invent one.
"""

import time


# THE OWNER'S TWO NUMBERS FOR THE HOME SCREEN, retuned 2026-08-24 from 30000 and
# 45000.  The ruling is phrased as a dim plus a further wait -- "20 seconds ...
# then ... after another 10 seconds" -- and both are stored ABSOLUTE, measured
# from the same last touch, because that is what the clock compares against.  The
# 10 s is therefore POSTER_MS - DIM_MS and not a second timer, which is why there
# is no third constant here and no state that could disagree about when the dim
# happened.
DIM_MS = 20000
POSTER_MS = 30000

# `setup`'S DIM IS DELIBERATELY STILL 30 s, AND THE ASYMMETRY IS UNRULED.
# The 2026-08-24 ruling scoped itself to the home screen and said nothing about
# the editor, so the editor keeps the number it shipped with rather than
# inheriting a retune it was not part of.  There is a case for either answer -- a
# wearer part-way through typing a name is doing something slower than browsing a
# grid, which argues for the longer wait; one panel behaving two ways is a thing
# a wearer could notice, which argues against -- and it is the owner's call, not
# a builder's.  It is a named constant rather than a literal in `setup` so
# the divergence is visible from the file that owns the numbers.
# `docs/design/idle-and-off.md` §5.1 carries it as an open question.
CARD_DIM_MS = 30000

# What `poll` returns.  Empty string for "nothing changed this frame", which is
# every frame but three in a session and is why the falsy value is the common
# one.
NOTHING = ""
#: Cross the dim line: the caller dims the panel.
DIM = "dim"
#: Input arrived while dimmed: the caller restores the wearer's brightness.
WAKE = "wake"
#: Cross the nametag line: the caller opens the badge.  ONCE per idle spell.
NAMETAG = "nametag"


class Idle:
    """One badge's idle clock.  Pure: no `badge`, no `display`, no globals.

    `poster_ms=None` disables the second rung, which is what `setup` passes:
    only the LAUNCHER can open an app, so a second rung inside the editor could
    only mean exiting it and discarding whatever the wearer was part-way
    through.  It is expressed as an absent rung rather than as a special case in
    a caller.

    `nametag` passed this too until 2026-08-24, for a different reason that no
    longer applies -- it does not build a clock at all now (see the module
    docstring), so `setup` is the only caller of this argument.
    """

    def __init__(self, now=0, dim_ms=DIM_MS, poster_ms=POSTER_MS):
        self.dim_ms = dim_ms
        self.poster_ms = poster_ms
        self.since = now
        self.dimmed = False
        #: True once the nametag rung has fired for this idle spell, so the
        #: caller cannot be handed the same transition twice while it waits for
        #: an app chain-load that takes several frames.
        self.opened = False

    # -- input ---------------------------------------------------------------

    def touch(self, now):
        """The wearer did something.  Restart the clock.

        Returns `WAKE` when this call ENDED a dim and `NOTHING` otherwise, so a
        caller that only ever calls `touch` still learns it owes the panel a
        restore.  Idempotent: a second `touch` in the same dim-free frame
        returns `NOTHING`.
        """
        self.since = now
        self.opened = False
        if not self.dimmed:
            return NOTHING
        self.dimmed = False
        return WAKE

    # -- the frame -----------------------------------------------------------

    def elapsed(self, now):
        """Milliseconds since the last touch.  Signed-ring safe, never negative.

        `time.ticks_diff` over MicroPython's 30-bit ring, the same call
        `ui.Saver` makes.  A negative answer means the caller's clock moved
        backwards -- a wrapped counter read out of order, or a host test being
        careless -- and the honest reading of "less time than none" is none.
        """
        span = time.ticks_diff(now, self.since)
        return span if span > 0 else 0

    def poll(self, now, busy=False):
        """Call once a frame.  Returns `NOTHING`, `DIM`, `WAKE` or `NAMETAG`.

        `busy` holds the clock without being an input: see the module docstring.

        AT MOST ONE SIGNAL PER FRAME, and `DIM` is never skipped on the way to
        `NAMETAG`.  A frame long enough to cross both lines at once reports the
        dim first and the nametag on the frame after, because the dim is the
        thing the WEARER is owed -- if a stalled frame swallowed it, a badge
        would jump from full brightness straight to a different app with no
        signal in between, which is precisely the announcement the owner's
        design says the dim IS.
        """
        if busy:
            return self.touch(now)
        span = self.elapsed(now)
        if not self.dimmed:
            if span >= self.dim_ms:
                self.dimmed = True
                return DIM
            return NOTHING
        if self.opened or self.poster_ms is None:
            return NOTHING
        if span >= self.poster_ms:
            self.opened = True
            return NAMETAG
        return NOTHING


class Panel:
    """The clock above, plus the brightness it dims and restores.

    THE WHOLE APP-SIDE SEAM, in one object, because the alternative measured
    badly: `nametag/badge/nametag/__init__.py` and
    `setup/badge/setup/__init__.py` are both held under an entry-file cap
    (`test_nametag_app.EntryFootprintTests`, `test_card_purity.EntryFootprintTests`)
    and were at 15,319 and 16,290 bytes against 16,384 when this was written --
    1,065 and 94 bytes of headroom. A per-app copy of "write the panel only when
    the level moves, dim on DIM, restore on WAKE" would not have fitten in
    either. So it lives here once and each seam spends four lines.

    THAT ARITHMETIC IS NOW HISTORY FOR ONE OF THE TWO: `nametag` has no seam at
    all since the 2026-08-24 never-dims ruling, and both caps are 18 KB. The
    argument still holds for the launcher and `setup`, and it is kept
    because it is why this class exists rather than three copies of eight lines.

    BOTH IMPURE THINGS ARE INJECTED, and that is what keeps this file free of
    Badgeware:

        apply(percent)   writes the panel.  Every caller's is
                         `display.backlight(backlight.fraction(percent))`.
        clock()          milliseconds.  Every caller's is `time.ticks_ms`.

    A module that reached for `display` and `time.ticks_ms` itself could not be
    unit-tested at all -- the same argument `card_app` and `identity_keyboard`
    both record for taking their input as an argument -- and the launcher, which
    vendors this file, must not acquire an import it can fail to start on.

    `dim_percent` IS PASSED IN rather than read from `shared/backlight.py`,
    which every caller also vendors. One reason: this module imports nothing but
    `time`, and the home screen is the one app whose failure needs USB to
    recover, so the cheapest guarantee that it cannot fail on import is that
    there is nothing to import. Callers pass `backlight.IDLE_PERCENT`, so the
    number still has exactly one home.
    """

    def __init__(self, apply, clock, percent, dim_percent,
                 dim_ms=DIM_MS, poster_ms=POSTER_MS):
        self._apply = apply
        self._clock = clock
        #: The wearer's own level. `set_brightness` moves it while dimmed too.
        self.percent = percent
        self.dim_percent = dim_percent
        self.clock = Idle(clock(), dim_ms, poster_ms)
        #: What was last written, so an idle app makes no device call at all --
        #: `display.backlight` is hardware for a value that moves once a minute
        #: at most, which is why `nametag` applies its own outside any frame loop
        #: at all. None means "nothing has been written yet", which is NOT the
        #: same as 0 and is why this is not initialised to a level.
        self._lit = None

    # -- the panel -----------------------------------------------------------

    def write(self, percent):
        """Put `percent` on the panel, and only when it actually moves.

        `_lit` is set AFTER the call, so a write that RAISED is not remembered
        as done and the next caller asking for the same level tries again.

        BE HONEST ABOUT WHICH CALLER THAT HELPS. Both app seams pass an `apply`
        that swallows its own failure -- a backlight must never reach
        `fatal_error`, which is a modal and a reset -- so for them nothing
        raises, `_lit` is set, and a failed write is NOT retried; what they get
        instead is a printed `stage=backlight` line. The ordering bites only for
        the launcher, whose `_apply_backlight` is unguarded because `commit()`
        already wraps head to toe. It is kept for both because the cost is the
        line order and the alternative is a class whose bookkeeping is wrong for
        any future caller that does let an error through.
        """
        if percent != self._lit:
            self._apply(percent)
            self._lit = percent

    def restore(self):
        """The wearer's own level on the panel, and NOT dimmed any more.

        Every seam calls this exactly once, at its entry, where `dimmed` is
        already False -- so the clock write below is a no-op in the shipping
        path.  It is here because it is the only thing that stops this method
        WEDGING the pair if anyone ever calls it mid-session: writing the full
        level while `clock.dimmed` stayed True left an object that could never
        dim again (`poll` goes straight to the nametag rung) and whose
        `set_brightness` was silently swallowed by its own guard.

        The clock is NOT reset, because nobody touched the badge.  So a
        mid-session `restore()` un-dims and the timer immediately re-earns the
        dim on the next frame, which is a visible flicker and a correct one --
        the alternative was a badge that never dimmed again.
        """
        self.clock.dimmed = False
        self.write(self.percent)

    def set_brightness(self, percent):
        """The wearer changed their preference. Show it immediately.

        LIVE, EVEN WHILE DIMMED -- and "while dimmed" cannot actually happen
        from a Settings row, because reaching one is input and input un-dims.
        The guard is here anyway: a brightness that arrived from somewhere with
        no press behind it (a fleet command, a restored file) must not brighten
        a panel the idle timer deliberately dimmed, or the dim would silently
        undo itself.
        """
        self.percent = percent
        if not self.clock.dimmed:
            self.write(percent)

    # -- the frame -----------------------------------------------------------

    def frame(self, touched, busy=False):
        """One frame. Returns `NOTHING`, `DIM`, `WAKE` or `NAMETAG`.

        The panel is ALREADY WRITTEN by the time this returns, for both `DIM`
        and `WAKE`. A caller acts on two of the four answers:

            WAKE     the press did nothing but restore the brightness, so
                     CONSUME it (D1: "the first press wakes ... and does
                     nothing else").
            NAMETAG   open the badge. Only the launcher can; `setup`, the one
                     other caller, passes `poster_ms=None` and never sees this.
        """
        now = self._clock()
        signal = self.clock.touch(now) if touched else self.clock.poll(now, busy)
        if signal == DIM:
            self.write(self.dim_percent)
        elif signal == WAKE:
            self.write(self.percent)
        return signal
