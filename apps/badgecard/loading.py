"""LOADING -- the screen every app puts up before it has anything to show.

THE SQL EDITOR, AND ONE THING THAT MOVES.  Supabase's editor mid-query: a dark
window, a statement on its current-line highlight in the editor's own syntax
colours, a divider, and a results bar reading `Running...` beside a turning
arc.  The window is painted ONCE and never again; the arc is three primitives
and is the only thing repainted.  `loading_sql.py` draws all of it.

WHY EVERYTHING ELSE IS STILL, and this is the design rather than a shortcut.
The panel can only be repainted between statements of the app's module body,
and those gaps are wildly uneven -- a cheap import returns in microseconds, an
image decode blocks for hundreds of milliseconds.  Anything redrawing much per
frame stutters whenever the app is busy.  Three primitives fit in almost any
gap, so the arc keeps moving where a fuller screen could not.

AND THE ARC TURNS PER PRESENT, NOT PER MILLISECOND.  Its predecessor asked the
wall clock which frame should be showing and painted toward it, which REPEATS a
frame when presents are dense and LURCHES when they are sparse -- both read as
stutter.  One step per repaint can do neither.  The speed then varies with how
fast the app is loading, which is honest and which the eye forgives.

WHY AN APP HAS TO DRAW ITS OWN LOADING SCREEN.  `badgeware.launch()` is
`os.chdir` -> `sys.path.insert` -> `__import__(path)`, and the firmware's own
comment on that line is "App may block here".  The launcher's frame loop has
already returned by then and threads are compiled out, so the ONLY moment
anything can reach the panel is between two statements of the app's own module
body.  That is what `step()` and `tick()` are for.

WHAT REPLACED WHAT, so nobody restores the wrong thing.  A psql terminal and a
radar sweep were A/B'd by coin flip; the owner took the radar on 2026-08-17,
then asked for it alone with no chrome, then on 2026-08-18 asked for this: the
editor back, but with a spinner that cannot stutter.  All of it is in git.

TWO SCREEN KINDS, AND ONE OF THEM IS AN ABSENCE.  `sql` is the screen.  `none`
means nothing was drawn and the app simply started -- there is no lesser screen
to fall back to, because the owner asked never to see the bare bar again.
`reason=` on the marker and in the log says which of the three failures it was.

NOTHING HERE MAY RAISE.  An exception inside `launch()` becomes a modal that
RESETS the badge, so every public method is wrapped and the painter latches
itself dead after one failure rather than raising once per frame.
"""

import sys
import time


# RESOLVED ONCE, at import, rather than probed per frame.  MicroPython's tick
# counters are 30-bit and wrap every ~18 minutes, which `ticks_diff` handles and
# plain subtraction does not; CPython has neither name, so the fast lane gets a
# monotonic-enough stand-in and the badge gets the real thing.
try:
    _ticks_us = time.ticks_us
    _ticks_diff = time.ticks_diff
except AttributeError:  # pragma: no cover - CPython only
    def _ticks_us():
        return int(time.time() * 1000000)

    def _ticks_diff(later, earlier):
        return later - earlier


# THE DECK.  One of these is chosen per open and typed into the editor.
#
# KEPT SHORT ON PURPOSE.  `loading_sql.wrap` measures rather than counts, so
# the limit is 152 pixels rather than a column count -- but a statement that
# needs four rows pushes the highlight down over the divider, and a wearer sees
# this for well under a second. One or two rows reads as a real editor; five
# reads as a wall of text.
#
# They are also all HARMLESS AND PLAUSIBLE. Nothing here is executed anywhere,
# but a loading screen that flashes `drop table attendees;` at eight hundred
# people is a joke that lands exactly once.
STATEMENTS = (
    "select pg_sleep(Infinity);",
    "select count(*) from badges where status = 'awake';",
    "select * from attendees where badge_id = current_setting('badge.id');",
    "select now() - pg_postmaster_start_time() as uptime;",
    "vacuum analyze conversations;",
    "listen proximity;",
    "notify badges, 'hello';",
    "select version();",
    "select avg(battery) from badges;",
    "refresh materialized view leaderboard;",
    "select name from friends order by met_at desc limit 5;",
    "select * from stickers where unlocked;",
    "update badges set mood = 'ready';",
    "select pg_size_pretty(pg_database_size('badge'));",
    "insert into handshakes (a, b) values (1, 2);",
    "select coalesce(nickname, name) from attendees;",
    "grant select on friends to everyone;",
    "select * from pg_stat_activity where state = 'active';",
    "reindex table conversations;",
    "checkpoint;",
    "explain analyze select 1;",
    "select set_config('badge.mode', 'party', false);",
    "begin; select 1; commit;",
    "select count(*) from friends where met_today;",
)

# HOW FAST THE ARC TURNS, in ring steps per present rather than per
# millisecond, and that IS the fix for the stutter the radar had.
#
# The radar asked the wall clock which frame should be showing and painted
# toward it. Presents are uneven -- a cheap import returns in microseconds, an
# image decode blocks for hundreds of milliseconds -- so a clock-driven target
# REPEATS a frame when presents are dense and LURCHES when they are sparse.
# Advancing per present cannot do either: every repaint moves the arc exactly
# one step. The wall-clock rate then varies with how fast the app is loading,
# which is honest, and which the eye forgives where it does not forgive a
# freeze.
_SPIN_STEP = 1

LOG_PATH = "/state/loading.log"
# 32 KB of log at ~60 bytes a line is about 540 opens, which is far more than
# anyone needs to answer "did every app get a screen" and 3% of the 1 MB
# volume.  One rotation is kept.
LOG_MAX = 32768


def _app_name():
    """The app's own directory name, DERIVED and never a literal.

    `badgeware.launch()` and the playground's `pg_runtime.launch_app` both do
    `sys.path.insert(0, path)` against the install directory before importing
    the app, so `sys.path[0]` IS that directory.  A literal here would be the
    same defect identity's build records: a wrong path made one app import its
    NEIGHBOUR's modules.
    """
    try:
        root = sys.path[0]
        if root:
            return root.rsplit("/", 1)[-1]
    except Exception:  # noqa: BLE001
        pass
    return "app"


def _log(line):
    """Append one line to `/state/loading.log`, rotating at 32 KB.

    Total: a full volume, a read-only mount or a missing `/state` drops the
    line.  The `print` marker has already gone out, so nothing is lost that a
    serial session could not recover.
    """
    try:
        import os
        try:
            if os.stat(LOG_PATH)[6] >= LOG_MAX:
                try:
                    os.remove(LOG_PATH + ".1")
                except OSError:
                    pass
                os.rename(LOG_PATH, LOG_PATH + ".1")
        except OSError:
            pass
        with open(LOG_PATH, "a") as handle:
            handle.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def pick(app, ticks):
    """Which statement this open shows.  Pure, and the tested seam.

    NOT `random`.  Importing it costs a module parse in front of every app to
    choose one of two dozen strings, and MicroPython's is seeded from the same
    near-constant tick counter anyway.

    MIXED WITH THE APP NAME, which matters more than it looks.  `ticks_us` is
    measured from interpreter start, so it reads nearly the same on every cold
    boot -- six boots 137 ms apart once picked the same screen, and that is
    recorded in `docs/engineering-findings.md`.  The name DECORRELATES the
    choice from the clock.

    DECORRELATION IS NOT EXCLUSION, and the first draft of this docstring said
    it was.  Two apps opened back to back land on different statements about
    23 times in 24 -- measured at 3,851 of 4,000 name pairs, which is exactly
    the independent baseline for a deck this size.  The claim worth making is
    that the choice does not FOLLOW the clock; promising no repeat would be a
    guarantee this cannot keep.

    The playground pins its clock deterministically, so the browser lane always
    gets the same statement for a given app.  That is a FEATURE there -- the
    e2e specs assert on the text -- and it is why this is a pure function of
    its arguments rather than reaching for a clock itself.
    """
    value = ticks & 0x3FFFFFFF
    for ch in app or "":
        value = (value * 31 + ord(ch)) & 0x3FFFFFFF
    # one avalanche step, because a counter's low bits barely move between
    # boots and `% len()` would read them straight
    value ^= (value >> 15)
    value = (value * 0x27220A95) & 0x3FFFFFFF
    value ^= (value >> 13)
    return STATEMENTS[value % len(STATEMENTS)]


class _Null:
    """The handle `begin()` returns when it could not even build a `_Loader`.

    Every method is the identity, so an app annotated for the loading screen
    runs unchanged.  It shares `screen_kind = "none"` with a `_Loader` whose
    window could not be painted, and that sameness is the point: both mean NO
    SCREEN.  The difference is that this one never got far enough to write a
    log line, so `reason="off"` only ever appears on the `print` marker.
    """

    screen_kind = "none"
    reason = "off"
    ticks = 0
    done = 0
    total = 0

    def step(self, note=""):
        return None

    def tick(self, note=None):
        return None

    def end(self):
        return None

    def chunked(self, handle, nbytes, pieces=8):
        try:
            return handle.read(nbytes)
        except Exception:  # noqa: BLE001
            return b""


class _Loader:
    """The live loading screen: the player, the counters, and the log.

    There is one painter and it draws one thing.  `_paint_window` lays down the
    window once via `_paint_window`; `_present` turns the arc by one step.  If the
    window could not be painted, this object still counts stages and still
    writes the log, and paints nothing at all.
    """

    def __init__(self, stages, app):
        self.total = stages if stages and stages > 0 else 1
        self.done = 0
        self.ticks = 0
        self.app = app or _app_name()
        self.reason = "-"
        self.started = _ticks_us()
        self.statement = pick(self.app, self.started)
        self._geometry = None
        self._step = 0

        # THE ONE LATCH, AND IT STARTS CLOSED.  `_dead` means "this loader will
        # not paint again", which covers both reasons for that: the window
        # never painted, or the painter raised once and retired.  `_present`
        # reads nothing else, so there is no state in which it can be reached
        # with `self._geometry` unset.
        self._dead = True
        # `self.screen_kind`, not `self.screen`: bare `screen` inside these
        # methods is the injected framebuffer builtin and the two must not read
        # like the same thing.
        self.screen_kind = "none"
        self._paint_window()
        print("LOADING screen=%s app=%s stages=%d reason=%s"
              % (self.screen_kind, self.app, self.total, self.reason))

    # -- choosing the statement ----------------------------------------------
    # -- the surface ---------------------------------------------------------
    def _borrow(self):
        """Remember the pen and face the app was using.  Never raises.

        THE LOADING SCREEN BORROWS THE SURFACE, IT DOES NOT OWN IT, and this is
        not hygiene -- it is a bug that shipped for an hour and a pixel oracle
        caught.  `tick()` is called from INSIDE the app's own work: `schedule`
        passes it to `build_layout_cache`, which measures fourteen blocks with
        `screen.measure_text` against `screen.font`.  Setting the loader's face
        between two of those measurements silently measured the rest of the
        agenda in the wrong font, and the text ran off the panel.
        """
        try:
            return screen.pen, screen.font
        except Exception:  # noqa: BLE001
            return None

    def _restore(self, saved):
        if saved is None:
            return
        try:
            screen.pen, screen.font = saved
        except Exception:  # noqa: BLE001
            pass

    # -- the frames ---------------------------------------------------------
    def _paint_window(self):
        """The editor, once.  Everything after this repaints only the arc.

        A failure here is not a fallback to something simpler -- there is
        nothing simpler left, and the owner asked never to see the bar this
        replaced. It means `screen_kind` stays `none`, the app starts with a
        blank panel, and `reason=` on the marker says which of the three ways
        it went wrong. That is the entire failure surface now: with no pack to
        install there is no `noasset`, no `badpack` and no unprovisioned badge.
        """
        saved = None
        try:
            saved = self._borrow()
            try:
                import loading_sql
            except Exception:  # noqa: BLE001
                self.reason = "nopainter"
                return
            self._geometry = loading_sql.paint(
                screen, color.rgb, font, self.statement)
            display.update()
            self.screen_kind = "sql"
            self._dead = False
        except MemoryError:
            self.reason = "mem"
        except Exception:  # noqa: BLE001 - see the module docstring
            self.reason = "paint"
        finally:
            # A `finally`, NOT a call on each path, and the difference is a bug
            # that shipped here for an hour. `loading_sql.paint` sets both the
            # pen and the face before it can raise, so an open that failed
            # partway used to hand the app back a surface still measuring in
            # `winds` -- which is exactly the wrong-face defect the borrow
            # contract exists to prevent, arriving through the error path
            # instead of the happy one. Restoring here covers every exit.
            if saved is not None:
                self._restore(saved)
    def _present(self):
        """One turn of the arc, and NOTHING else is painted.

        Three primitives and a present. Nothing clears the framebuffer during a
        load -- the managed frame loop has not started -- so the window painted
        at frame zero simply stays there and the arc is redrawn over itself.

        `_borrow`/`_restore` IS needed here, unlike the radar's blit-only
        present: the spinner sets a pen. Forgetting that is the bug `schedule`
        shipped for an hour, and `test_loading.py` asserts the property through
        both `step` and `tick`.
        """
        if self._dead:
            return
        import loading_sql
        saved = self._borrow()
        self._step += _SPIN_STEP
        loading_sql.spinner(screen, color.rgb, self._geometry, self._step)
        display.update()
        self._restore(saved)
    # -- the app-facing API -------------------------------------------------
    def step(self, note=""):
        """One completed unit of REAL work.  Counted, and presents a frame.

        `note` is accepted and ignored; see the module docstring for why the
        parameter cannot simply be removed.
        """
        try:
            if self.done < self.total:
                self.done += 1
            self._present()
        except Exception as error:  # noqa: BLE001 - see the module docstring
            self._retire(error)

    def tick(self, note=None):
        """Motion from inside one unit of work.  Does NOT count a stage.

        Every caller is a piece of work that has been deliberately subdivided
        so a frame fits between its halves.  If an app has nothing to subdivide
        it simply never calls this.  `note` is accepted and ignored.
        """
        try:
            self.ticks += 1
            self._present()
        except Exception as error:  # noqa: BLE001
            self._retire(error)

    def _retire(self, error):
        """Stop drawing, leave the last good frame up, and say so once.

        Latched rather than retried: a painter that raised once will raise
        every present, and a traceback per frame in front of a loading app is
        the crash this feature exists to prevent.

        THERE IS NOTHING TO RELEASE, which is new. Its predecessor held a
        pack's file handle and a tile bank and had to close both here or leak
        them into the app still importing behind it. This screen owns no
        handle, no asset and no buffer -- it is primitives on the app's own
        surface -- so retiring is only the latch.

        SILENT WHEN THERE WAS NOTHING TO RETIRE. On an open whose window never
        painted, `_dead` is already set from `__init__` and `LOADING_FAIL`
        would be reporting the failure of a screen that was never up;
        `reason=` has already said what happened.
        """
        if not self._dead:
            print("LOADING_FAIL app=%s error=%r" % (self.app, error))
        self._dead = True
        self._geometry = None

    def chunked(self, handle, nbytes, pieces=8):
        """`handle.read(nbytes)`, in `pieces` slices with a frame between each.

        The move that recurs.  A 10,240-byte LUT read is one native call that
        cannot be animated through; eight 1,280-byte reads with a present
        between them can be.  The codec never learns: `SkinPainter.__init__`
        takes byte objects, so this is a drop-in for the `read` that fed it.
        """
        try:
            if pieces < 1:
                pieces = 1
            slice_bytes = (nbytes + pieces - 1) // pieces
            out = bytearray(nbytes)
            got = 0
            while got < nbytes:
                want = nbytes - got
                if want > slice_bytes:
                    want = slice_bytes
                blob = handle.read(want)
                if not blob:
                    break
                out[got:got + len(blob)] = blob
                got += len(blob)
                # No progress string: nothing on the panel would show it, and
                # this formatted one per chunk of every read in every app.
                self.tick()
            return bytes(out[:got])
        except Exception:  # noqa: BLE001
            try:
                return handle.read(nbytes)
            except Exception:  # noqa: BLE001
                return b""

    def end(self):
        """Tear down, print the measured duration, append one line to the log.

        IT COSTS NO FRAME, EVER.  The bar used to present once more when the
        app had declared more stages than it ran, because a bar frozen at 3/4
        under a finished app is a lie.  Nothing on the panel counts stages now,
        so that frame would be ~11.4 ms of VSYNC latency for one more radar
        picture the app's own first paint immediately replaces.  `done` is
        still completed for the log line, which is where the count lives.
        """
        try:
            micros = _ticks_diff(_ticks_us(), self.started)
        except Exception:  # noqa: BLE001
            micros = 0
        try:
            if self.done < self.total:
                self.done = self.total
        except Exception as error:  # noqa: BLE001
            self._retire(error)
        self._geometry = None
        self._dead = True
        print("LOADING_DONE screen=%s app=%s stages=%d/%d ticks=%d"
              % (self.screen_kind, self.app, self.done, self.total,
                 self.ticks))
        # MEASURED, NOT DECORATED: the same value that lands in the log, and it
        # is the only instrument for what the radar costs -- every open pays
        # for it now, and an open that drew nothing pays only for the failed
        # `open` that told it so.
        print("Time: %d.%03d ms" % (micros // 1000, micros % 1000))
        _log("LOADING screen=%s app=%s ms=%d stages=%d/%d ticks=%d reason=%s"
             % (self.screen_kind, self.app, micros // 1000, self.done,
                self.total, self.ticks, self.reason))


def begin(stages, app=None):
    """Put a loading screen up NOW and return a handle.  Never raises.

    `stages` is how many `step()` calls the app will make.  Nothing on the
    panel shows it any more -- it is the denominator of the `stages=` column in
    `/state/loading.log`, which is how an app that promises four stages and
    runs two gets caught.  `app` overrides the name derived from the install
    path, which only the launcher, a test or a host tool ever needs.

    A failure here returns a handle whose every method does nothing, so the app
    that follows is unchanged.
    """
    try:
        return _Loader(stages, app)
    except Exception as error:  # noqa: BLE001 - see the module docstring
        print("LOADING screen=none error=%r" % (error,))
        return _Null()
