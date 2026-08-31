"""BADGE-5 offline schedule app for Tufty Badgeware v3.0.2."""

import gc
import os
import sys
import time


APP_ROOT = "/system/apps/schedule"
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)
os.chdir(APP_ROOT)

import badgeware

import config


MODE = (HIRES if config.USE_HIRES else LORES) | VSYNC
CLOCK_REFRESH_MS = 1000


# THE MODE BEFORE THE FIRST PAINT.  `config` is imported above it because the
# mode depends on it; nothing else is, because the loading screen goes up next.
badge.mode(MODE)

import loading  # noqa: E402
# FOUR STAGES, AND THIS APP CARRIES THE REPOSITORY'S ONE GENUINELY UNAVOIDABLE
# CALL.  `ScheduleView._select_face` does `font.load("MonaSans-Medium")` -- a
# ~66 KB read into a fresh ~74 KB object, one native call, no chunked form.  It
# cannot be subdivided and it cannot be DEFERRED here, because unlike a mark
# sheet or a wallpaper it is not an extra: this app's first interactive frame is
# the agenda and the agenda is typeset in that face, so there is nothing to
# show before it exists.  A frame is presented and captioned immediately before
# it and the caselights come up, so the pause is explained and indicated on a
# channel the panel cannot provide -- but nothing MOVES during that one call,
# and `schedule/README.md` records it as the one open case rather than hiding
# it.  Everything either side of it is subdivided: the imports one at a time,
# and the fourteen-session layout measurement one session at a time.
_load = loading.begin(4)

# `machine` IS NO LONGER IMPORTED HERE, and that absence is the 2026-08-24 clock
# ruling.  It was pulled in for one caller -- the dial's commit, which wrote
# `machine.RTC().datetime(...)` and then the external PCF -- and this app writes
# no clock now.  The comment it replaces explained that a builtin module costs
# nothing to import below `_load`; that is still true, and there is simply
# nothing left that needs it.
import backlight  # noqa: E402
import idle  # noqa: E402
from schedule_model import (  # noqa: E402
    CLOCK_TRUSTED,
    CLOCK_UNSET,
    CACHE_PATH,
    OVERRIDE_PATH,
    clock_minutes,
    clock_state,
    current_indices,
    display_freshness_mark,
    freshness,
    initial_index,
    load_with_cache,
    next_index,
    read_link_state,
    session_phases,
    stamp_from_datetime,
    sync_age_minutes,
)
_load.tick("-- schedule_model")
from schedule_view import ScheduleView  # noqa: E402
from schedule_refresh import ScheduleRefresh  # noqa: E402
_load.step("-- 5 modules imported")

display.backlight(backlight.fraction(backlight.NORMAL))
badge.caselights(0)
_return_idle = idle.ReturnToNametag(time.ticks_ms)
_next_app = None


def _unavailable(detail, notice=None, idle_step=None):
    """The screen for a badge whose agenda cannot be read, and it never returns.

    WHY THIS EXISTS AT ALL.  `normalize` is deliberately strict, this call is at
    MODULE SCOPE, and `badgeware.launch()` turns an import-time exception into
    `fatal_error` -> a traceback modal -> any button -> `machine.reset()` -> the
    launcher, which re-runs the same failing import.  One bad byte in
    `schedule.json` was a MODAL-RESET LOOP on every badge carrying it, with no
    way into the app and nothing on the panel naming the problem.  The strict
    validator is right; it just cannot be the last thing between the data and
    the fleet.

    NOTHING IN HERE MAY RAISE, for exactly the reason above: a traceback out of
    the error screen is the loop it exists to prevent.  So the whole draw is
    wrapped, the fallback is a bare cleared panel, and the marker goes to serial
    first -- before any drawing -- so a badge that cannot paint at all is still
    diagnosable over USB.

    HOME COSTS NOTHING AND IS ALREADY WIRED.  `launch()` registers it as a
    falling-edge IRQ on `machine.Pin.board.BUTTON_HOME` BEFORE it imports the app
    (`modules/common/badgeware/__init__.py:80-85`), so it works from any app
    state including this one.  All this screen has to do is keep a managed frame
    loop alive rather than raise, and say so on the panel.

    `font.sins` and point-form text on purpose: `sins` is ROM and cannot be
    missing, where the vector face is on the FAT partition and `ScheduleView`
    (which selects it) needs a valid schedule to construct.  Point form also does
    not parse `[...]` markup, so a defect message containing a bracket cannot
    become a second crash inside the screen reporting the first one.
    """
    print("SCHEDULE_UNAVAILABLE detail={} notice={}".format(detail, notice))
    try:
        _load.end()
    except Exception:  # noqa: BLE001
        pass

    ink = color.rgb(238, 244, 255)
    muted = color.rgb(145, 157, 180)
    paper = color.rgb(7, 10, 18)
    wide = int(screen.width) > 160
    pad = 4 if wide else 2
    # (text, scale, pen), MEASURED AND TRIMMED ONCE.  Not per frame: the detail
    # is a validator message of unknown length, LORES is 160 px wide, and
    # trimming it by measured advance inside the draw would put one
    # `measure_text` per character per frame into a screen whose whole job is to
    # be undramatic.  Same rule as the agenda's own layout cache.
    rows = []
    try:
        screen.font = font.sins
        limit = int(screen.width) - pad * 2
        # Both problems get named at once when both exist: reaching this screen
        # means the BAKED agenda is unusable, and a rejected day-of override on
        # top of that is a second, separate thing somebody has to fix.
        for index, line in enumerate((
            "SCHEDULE UNAVAILABLE",
            "The agenda file could not be read.",
            "{}".format(detail),
        ) + (("{}".format(notice),) if notice else ()) + (
            "HOME returns to the launcher.",
        )):
            scale = (2 if wide else 1) if index == 0 else 1
            text = line
            while text and int(screen.measure_text(text)[0] + 0.5) * scale > limit:
                text = text[:-1]
            rows.append((text, scale, ink if index == 0 else muted))
    except Exception as error:  # noqa: BLE001
        print("SCHEDULE_UNAVAILABLE_MEASURE_FAIL error={!r}".format(error))
        rows = []

    def _paint():
        screen.font = font.sins
        screen.pen = paper
        screen.clear()
        y = pad * 2
        for text, scale, pen in rows:
            screen.pen = pen
            screen.text(text, pad, y, scale)
            y += (12 * scale) + pad

    # NOT NAMED `update`, deliberately.  Three tests read this app's key
    # bindings straight out of the source, slicing from the dial handler to the
    # frame callback, so a second callback of that name ABOVE the dial would
    # silently empty their slice -- and an empty slice PASSES a `assertNotIn`.
    # Those helpers now slice on top-level definition boundaries and assert the
    # block is non-empty, which is what caught this comment's own first draft.
    def _frame():
        # This module-scope modal cannot return through `launch`; the exact
        # sentinel is caught by the generated main while every other
        # SystemExit remains an error/reset path.
        if idle_step is not None and idle_step():
            raise SystemExit("/system/apps/nametag")
        try:
            _paint()
        except Exception as error:  # noqa: BLE001
            # A second failure: stop trying to say anything and just hold a
            # frame.  Raising here would BE the modal loop.
            print("SCHEDULE_UNAVAILABLE_DRAW_FAIL error={!r}".format(error))
            try:
                screen.pen = paper
                screen.clear()
            except Exception:  # noqa: BLE001
                pass

    # `run` blocks until its callback returns non-None, and `_frame` never does,
    # so the module body below is unreachable.  The `while` makes that a
    # guarantee rather than a reading of `Loop.__call__`.
    while True:
        run(_frame)


# THE WRITABLE ROOT WINS, and it is checked first on purpose.  `/` is LittleFS
# and writable; `/system` is the FAT partition this app is baked into.  A file
# dropped at `/schedule.json` therefore replaces the agenda with no reflash and
# no bytecode rebuild -- the only realistic way to fix a wrong room or a shifted
# start time on the morning of the event, where the alternative is a USB cable
# and a Disk Mode pass per badge.  Both paths go through the same guarded loader,
# so neither can raise here; a corrupt override degrades to the baked copy with a
# band on the panel rather than to the error screen.  `load_with_cache` inserts
# the last-good downloaded snapshot between that override and the baked floor.
(schedule, _schedule_source, _schedule_notice, _schedule_error,
 _cached_schedule, _cache_error) = load_with_cache()
if schedule is None:
    gc.collect()
    _unavailable(
        _schedule_error,
        _schedule_notice,
        lambda: _return_idle.frame(bool(badge.held())),
    )
if _schedule_notice:
    print("SCHEDULE_OVERRIDE {}".format(_schedule_notice))
if _cache_error:
    print("SCHEDULE_CACHE rejected={}".format(_cache_error))
_from_override = _schedule_source == OVERRIDE_PATH
# A cache UUID proves where the file came from, not when it was last checked.
# This bit is RAM-only and becomes true only after this open's conditional GET
# succeeds; persisting it would let a reboot claim a verification it did not do.
_display_verified = False
# READ ONCE, AT OPEN, AND READ ONLY.  `badgelink`'s `/state/schedule.json` is
# THEIR file and THEIR schema; this app takes TWO fields out of it -- the version
# string and, since their Lane F landed it on 2026-08-24, the optional
# `synced_at` epoch -- and never writes, deletes or imports anything of theirs.
#
# ONE CALL FOR BOTH, deliberately: they rewrite that file with a single atomic
# rename, so two reads could pair a version from one write with a sync time from
# the next, which is the exact disagreement their rename discipline exists to
# prevent.  Once rather than per frame because a file seam's semantics are
# next-open, not live (there is no object either side can hold), and neither
# value can change while this app owns the screen.  The reasoning for all of it,
# and what their record does and does not contain, is in
# `schedule_model.read_link_state` and `schedule/README.md`.
_link_version, _link_synced_at = read_link_state()
_load.step("-- {} sessions loaded".format(len(schedule["sessions"])))
_load.tick("NOTICE:  MonaSans 74 KB")
# The caselights carry the one pause nothing on the panel can carry.
badge.caselights(0.35)
view = ScheduleView(
    screen, color, font, image, rect, schedule, config.UI_SCALE, _schedule_notice,
    config.SOFTKEYS,
)
badge.caselights(0)
_load.step("-- face resolved, 18 pt")
view.build_layout_cache(on_session=_load.tick)
_load.step("-- {} blocks measured".format(len(schedule["sessions"])))


def _new_view(value):
    """Build an offscreen view with the exact shipping renderer configuration."""

    # An invalid manual override stays authoritative until the file is fixed or
    # removed.  A network swap changes the fallback underneath it, not the
    # reason the warning band is on screen, so the replacement inherits notice.
    return ScheduleView(
        screen, color, font, image, rect, value, config.UI_SCALE,
        _schedule_notice,
        config.SOFTKEYS,
        # `font.load` returns a distinct retained ~73,792 B object and costs
        # ~111 ms (VAL-020-CH). A live refresh uses the same panel and scale, so
        # the old immutable face is the correct state to share with its
        # offscreen replacement while both views coexist.
        (view.face, view.vector, view.font_size),
    )


_refresh = ScheduleRefresh(
    schedule, view, _schedule_source, _cached_schedule, _new_view,
)
last_clock_refresh = time.ticks_add(time.ticks_ms(), -CLOCK_REFRESH_MS)
last_clock_report = None
# Each tab is positioned on the clock once, the first time it is shown with a
# trusted clock. Doing it every refresh would drag the reader's scroll position
# back to "now" while they were reading somewhere else.
positioned = set()


def _refresh_clock(force=False):
    global last_clock_refresh, last_clock_report
    now_ticks = time.ticks_ms()
    if not force and time.ticks_diff(now_ticks, last_clock_refresh) < CLOCK_REFRESH_MS:
        return
    last_clock_refresh = now_ticks
    # THE RAW READING IS UTC ON A SYNCED BADGE, and this is the only line in the
    # app that touches it directly.  `badgelink.clock_boot.resync` runs
    # `ntptime.settime()` (which sets the clock from `gmtime`) and copies it
    # verbatim to the PCF85063A through `badgeware.rtc.localtime_to_rtc()`;
    # VAL-041-BLR measured the result on hardware.  Every time in the agenda is
    # EVENT-LOCAL, so the two frames are converted at ONE seam, immediately below.
    current_datetime = rtc.datetime()
    # ONE FUNCTION DECIDES, and it used to be two that could disagree: the date
    # half and the time half were checked separately, so `trusted` could stay
    # True while the minute was None - and the None reached the view and killed
    # the app on its first frame, which is the dead-backup-cell symptom (a
    # PCF85063A coming up reporting an hour of 99).  `clock_state` validates
    # both halves, converts the frame itself out of the event's own
    # `utc_offset_min`, and answers one of FOUR states -- the fourth being
    # `no_offset`, an agenda that does not say what frame its times are in.
    #
    # IT TAKES THE RAW READING, NOT `local` BELOW.  It applies the offset
    # internally, so passing the converted stamp would apply it twice.
    #
    # AND IT HANDS THE CONVERTED STAMP BACK, which is what makes `schedule/
    # README.md`'s ONE SEAM claim structurally true instead of a promise about
    # two call sites agreeing.  This line used to be followed by a SECOND
    # `event_local_stamp(current_datetime, ...["utc_offset_min"])` -- the same
    # reading, the same offset, the same answer, computed twice a second -- and
    # an adversarial review named the gap: one conversion function, two
    # conversion invocations, so "cannot double-shift" was true of the code and
    # not of the app's shape.  There is ONE invocation now and
    # `FrameWiringTests` holds it there by AST.
    state, local = clock_state(current_datetime, schedule["event"])
    trusted = state == CLOCK_TRUSTED
    # ── TWO STAMPS, TWO FRAMES, AND MIXING THEM UP IS AN EIGHT-HOUR DEFECT ────
    #
    # `local`  the event-local reading, converted ONCE, inside `clock_state`
    #          above.  Everything that compares against agenda CONTENT uses it:
    #          the minute the NOW layer tests against `HH:MM` session times, the
    #          header's `11:50 PST`, and `freshness`, whose other operand is the
    #          event-local `generated_at`.  None when the agenda carries no
    #          offset (no frame) or the reading is garbage.
    # `raw`    the badge's own reading, unconverted.  ONLY `sync_age_minutes`
    #          takes it, because that subtracts badgelink's `synced_at` from a
    #          later reading of THE SAME CLOCK: whatever frame the clock is in
    #          cancels, and adding an offset to one side would break a
    #          calculation that is already right.  See its docstring.
    raw = stamp_from_datetime(current_datetime)
    minutes = clock_minutes(local) if trusted else None
    # Now/Next/phases are per stage, because one stage is what the screen shows.
    sessions = view.visible()
    current = current_indices(sessions, minutes)
    upcoming = next_index(sessions, minutes)
    view.set_clock(state, minutes, current, upcoming,
                   session_phases(sessions, minutes), local)
    # FRESHNESS DOES NOT NEED THE EVENT WINDOW, only a believable clock: the age
    # of the agenda file is a wall-clock question, so a badge reading a real date
    # three days before the event can still judge how old its copy is.  The AGE
    # no longer reaches the panel -- the 2026-08-24 ruling replaced every
    # freshness sentence with a glyph. It still decides the legacy FRESH_STALE
    # value in the serial marker's change key, but the schema-2 panel mark below
    # is source plus this-open verification and does not consume this verdict.
    # A BELIEVABLE CLOCK IS ENOUGH, AND `CLOCK_OFF_DAY` COUNTS AS ONE. The event
    # window gates NOW claims; dating a file and dating a sync are wall-clock
    # questions, so a badge reading a real date three days before the event can
    # still do both. Only detectable garbage (`CLOCK_UNSET`) withholds the stamp.
    # `CLOCK_NO_OFFSET` needs no gate here: `local` is already None in that case,
    # because there is no frame in which to date anything.
    verdict, age = freshness(
        schedule["event"], _link_version, None if state == CLOCK_UNSET else local,
        _link_synced_at,
    )
    # Legacy schema-1 version metadata remains useful on serial, but the v2 UI
    # is source-only after reboot: manual/day-of, cache/unverified, baked/offline.
    view.set_freshness(display_freshness_mark(
        _schedule_source, _display_verified))
    if trusted and view.stage not in positioned:
        positioned.add(view.stage)
        view.select(initial_index(sessions, minutes))
    # THE STATE IS IN THE KEY, not just `trusted`, and leaving it out hid a real
    # transition: a badge going from a believable off-event date to a
    # flat-battery 2021 keeps `trusted` False, `minutes` None and the same
    # freshness verdict, so the line never reprinted and the console said the
    # clock had not changed. Found by a browser scenario that set 2021 and
    # waited for a marker that could never come.
    report = (state, minutes, view.stage, verdict)
    if report != last_clock_report:
        last_clock_report = report
        print(
            "SCHEDULE_CLOCK trusted={} minute={} stage={} current={} next={}"
            # THE DIAGNOSIS THAT USED TO BE ON THE PANEL LIVES HERE NOW.  Two
            # readings left the screen on 2026-08-24 and both were diagnostic:
            # the day an off-day clock believed, and the age behind
            # `UPDATED 30 MIN AGO`.  `state=` and `age=` are them, on the channel
            # where the person who can act on them is standing.  A wearer cannot
            # fix either one; an operator with a cable can.
            # `offset=` IS THE DIAGNOSIS FOR THE FOURTH STATE.  A badge printing
            # `state=no_offset offset=None` is telling an operator that the
            # AGENDA FILE is missing `utc_offset_min` -- fleet-wide, one line of
            # JSON to fix -- rather than that this unit's clock is flat.  The
            # value is printed as well as the state because a WRONG offset is
            # undetectable by the badge and readable by a person.
            " state={} fresh={} mark={} age={} sync={} offset={}".format(
                int(trusted), minutes, view.stage, current, upcoming, state, verdict,
                view.freshness, age, sync_age_minutes(_link_synced_at, raw),
                schedule["event"]["utc_offset_min"],
            )
        )


def _switch_stage(delta):
    view.cycle_stage(delta)
    _refresh_clock(True)
    print(
        "SCHEDULE_STAGE index={} id={} sessions={}".format(
            view.stage, schedule["stages"][view.stage]["id"], len(view.visible())
        )
    )


# THE OFFLINE TIME DIAL IS DELETED.  OWNER RULING, 2026-08-24:
#
#     "we either get a real time from a server or don't assume we know time"
#
# WHAT WAS HERE.  `_open_dial` seeded an hour and minute from the RTC (or from
# the baked `day_start`) and put a second screen up; `_handle_dial` walked it
# with C and UP/DOWN and committed it on B, writing BOTH of the badge's clocks
# -- `machine.RTC()` first, then the external PCF85063A, with a Monday=0 weekday
# for the boot sync to propagate.  Roughly 90 lines, all of it correct for what
# it was, and it is gone: `_handle_dial`, `_open_dial`, `adjust_dial`,
# `weekday_badgeware`, `view.draw_dial`, `import machine`, the `B SET TIME`
# header affordance and the `TIME` softkey label.
#
# WHY THE CODE BEING CORRECT DID NOT SAVE IT.  A dial does not produce a time;
# it produces a CLAIM by whoever is holding the badge.  A wearer who dialled
# 10:35 got the full NOW layer -- a green live row, `ENDS IN 10 MIN`, an
# auto-landed cursor -- with nothing behind it but their own guess, and the badge
# presented that identically to a badge whose clock came off the network.  The
# app could not tell them apart and neither could the wearer.  So the trust floor
# now means exactly one thing: a real sync, either happening now or still carried
# in the RTC from a previous one.  Everything below it shows the agenda and says
# nothing about time.
#
# WHAT REPLACED IT ON THE PANEL: nothing.  That is the point -- see
# `schedule_view._clock_reading`.  Silence, not apology, and no key to press.
#
# WHAT DID *NOT* GO WITH IT.  The trust-state machinery is untouched and still
# tested: the 2026 floor (`powman.c` re-seeds 2025-05-01 into the always-on timer
# on every sleep, so a 2025 floor admits the value every factory unit produces),
# the event-window test, and the time-field validation that closed the
# hour-of-99 dead-backup-cell crash.  The two-clock firmware knowledge the commit
# was built on is recorded in `docs/engineering-findings.md`, not deleted with the
# code that used it, and `badgelink`'s boot sync is the thing that writes badge
# clocks now.


# -- the BadgeLink placement opt-in ----------------------------------------
#
# OWNER RULING #22 establishes the MECHANISM and names no apps; the ROSTER is the
# owner's work order, `docs/handoff/networking-endstate-2026-08-26/
# FINAL_PROMPT_badge.md` §7.1 -- settings and home already covered, poster and
# schedule the two to add. Kept apart so nobody reads a roster into #22.
#
# THIS APP IS THE ONE THAT MOST NEEDS THE NETWORK. Its v2 request is earned once
# at app open and parks until the existing backend reaches CONNECTED, while
# `network_runtime._placement_allows_establishment` is `at_launcher or active`.
# Without `set_active(True)` the very app waiting for that GET would withhold
# every establishment moment. The GET itself is non-blocking and rides the
# existing errand channel; this opt-in lets that one open request make progress.
#
# THE ROSTER IS ALSO A CAPACITY CONTROL AND NOBODY PRICED THAT HALF. See the long
# note beside `poster`'s opt-in for the argument; the short form is that the
# poster is join-allowed and is where an untouched badge spends its day, every
# app exit is a `machine.reset()` landing the wearer at the join-allowed
# launcher, and so no ordinary wearer state withholds. `BOOT_JITTER_MS`'s twenty
# seconds spaces a herd, not a rate, and nothing is reused across a reset -- so
# every join is cold and each app added here multiplies fleet join rate by that
# app's share of wearer time. The server-side join cost is an open measurement
# (NETWORKING_LANE_STATE.md §6). Do not extend the roster without it.
#
# A firmware-injected builtin read as a BARE NAME: MicroPython's `builtins`
# attribute lookup bypasses its own override dictionary, so
# `builtins.badgelink_network = ...` is visible only to ordinary name lookup.
try:
    _network = badgelink_network
except NameError:
    _network = None


def _network_active(active):
    """Tell BadgeLink this app is a tolerant place to establish, or stop.

    GUARDED BECAUSE AN AttributeError HERE RESETS THE BADGE (docs/deploy.md: a
    raise on the launch path is a `machine.reset()`), and a badge whose
    `/system/lib` predates `set_active` would raise exactly that. A missing seam
    means the agenda simply keeps showing its cached copy, which is this app's
    whole offline story anyway.
    """

    if _network is None:
        return
    setter = getattr(_network, "set_active", None)
    if not callable(setter):
        return
    try:
        setter(bool(active))
    except Exception as error:  # noqa: BLE001
        print("SCHEDULE_NETWORK stage=set_active error={!r}".format(error))


def on_exit():
    """Release the opt-in. A backstop, and worth having anyway.

    `enter_run_context` clears `_active` at the top of every `run()`, so the
    next app cannot inherit this one's opt-in. What this covers is the same-run
    window: an app that opted in and returned without releasing leaves a WSS
    establishment admissible for the rest of the call.
    """

    _network_active(False)
    return _next_app


def _advance_schedule_refresh():
    """Advance one bounded phase and apply a ready view before this frame draws."""

    global schedule, view, _schedule_source, _from_override
    global _display_verified, positioned, last_clock_report
    result = _refresh.advance()
    if result is None:
        return
    kind = result.get("kind")
    if kind == "failed":
        print("SCHEDULE_REFRESH failed={}".format(result.get("error")))
        return
    if kind == "cached":
        # The wearer still sees `/schedule.json`; this marker is the only claim
        # made until removing that override reveals the downloaded file.
        print("SCHEDULE_REFRESH cached={} override=1".format(
            result.get("artifact_id")))
        return
    if kind == "verified":
        if not _from_override and _schedule_source == CACHE_PATH:
            _display_verified = True
            _refresh_clock(True)
        print("SCHEDULE_REFRESH current={} displayed={}".format(
            result.get("artifact_id"), int(_display_verified)))
        return
    if kind != "swap":
        return

    previous = view
    old_positioned_ids = set()
    for stage_index in positioned:
        if 0 <= stage_index < len(previous.stages):
            old_positioned_ids.add(previous.stages[stage_index]["id"])
    schedule = result["schedule"]
    view = result["view"]
    _schedule_source = result["source"]
    _from_override = False
    _display_verified = True
    positioned = set(
        index for index, stage in enumerate(view.stages)
        if stage["id"] in old_positioned_ids
    )
    # Navigation was adopted by semantic IDs. Marking the visible stage as
    # positioned keeps the immediately following trusted clock refresh from
    # undoing that preservation with its first-open auto-land.
    positioned.add(view.stage)
    last_clock_report = None
    _refresh_clock(True)
    print("SCHEDULE_REFRESH swapped={} sessions={} stage={}".format(
        result.get("artifact_id"), len(schedule["sessions"]),
        schedule["stages"][view.stage]["id"],
    ))


def update():
    global _next_app
    if _return_idle.frame(bool(badge.held())):
        _next_app = idle.NAMETAG_APP
        return "idle"
    # IDEMPOTENT AND PER FRAME. `set_active` raises MOMENT_VIEW_TRANSITION on
    # the False->True edge only, so after the first frame this is an attribute
    # lookup and a bool compare -- and doing it per frame is what survives a
    # `set_active(False)` raised from anywhere else while the agenda is still up.
    _network_active(True)
    # ADVANCE BEFORE REQUEST. A real transport answers on a later frame, but a
    # compatibility service or future warm in-memory service may invoke its
    # callback synchronously. Advancing first guarantees that callback only
    # stages bytes in this frame; validation cannot begin until the next one.
    _advance_schedule_refresh()
    # The controller is constructed once per app import/open. Calling its latch
    # here survives a socket that is not ready on frame one without turning the
    # frame callback into a cadence: only the first call reaches the service.
    if _network is not None:
        _refresh.request_once(_network)
    # FOUR LIVE KEYS, DOWN FROM FIVE, AND B IS DELIBERATELY UNBOUND.  UP/DOWN
    # move the focused thing up and down the screen; A and C are the leftward and
    # rightward direction, and what sits left and right here is the stage tabs
    # the agenda page itself puts there.  A day is 8 rows, so paging is what that
    # costs.
    #
    # B IS NOT REPURPOSED, and that was a deliberate call rather than an
    # oversight.  `docs/design/schedule.md` says one screen and no session-detail
    # view; the row already draws every field the data has; and an app whose
    # whole job is to be readable while somebody holds it up has no use for a
    # free key it would have to teach.  `docs/badge-button-rules.md` §9.2's
    # key-budget question is now moot for this app rather than answered.
    if badge.pressed(BUTTON_UP):
        view.move(-1)
    elif badge.pressed(BUTTON_DOWN):
        view.move(1)
    elif badge.pressed(BUTTON_A):
        _switch_stage(-1)
    elif badge.pressed(BUTTON_C):
        _switch_stage(1)

    _refresh_clock()
    view.draw()


_refresh_clock(True)
gc.collect()
print(
    "SCHEDULE_OPEN mode={} scale={} face={} pt={} stages={} sessions={} cache={}"
    " softkeys={} link={} sync={} source={} built={} offset={} heap_free={}".format(
        "HIRES" if config.USE_HIRES else "LORES",
        config.UI_SCALE,
        "vector" if view.vector else "bitmap",
        view.font_size,
        len(schedule["stages"]),
        len(schedule["sessions"]),
        len(view.layout_cache),
        int(config.SOFTKEYS),
        # WHETHER THIS BADGE HAS BADGELINK STATE AT ALL, which is the difference
        # between the offline mark being a fact and being a guess.  The version
        # string itself is not printed: it is another lane's opaque value and a
        # marker line is not the place to leak it.
        int(_link_version is not None),
        # WHETHER THEIR RECORD CARRIES A SYNC TIME, which is the difference
        # between the staleness threshold being a FACT about when this badge last
        # checked and a PROXY built on the agenda's own build age.  Absence is
        # ordinary and means "unknown", never "very old" -- a pre-Lane-F cache
        # and a badge that synced with an untrustworthy clock both read 0 here.
        int(_link_synced_at is not None),
        # WHICH FILE THE WEARER IS ACTUALLY READING.  Without this, "we pushed
        # the fix to the badges" is unverifiable after the fact.
        _schedule_source,
        # WHEN THE AGENDA ON SCREEN WAS BUILT, which used to be readable on the
        # panel as `OFFLINE COPY 14 AUG` until the 2026-08-24 freshness ruling
        # replaced the sentence with a glyph.  The glyph says WHICH KIND of copy
        # it is; the date is the follow-up question, and this is where it is
        # answered now.  `None` on an agenda that carries no `generated_at`.
        schedule["event"].get("generated_at"),
        # THE FRAME THIS BADGE IS READING ITS CLOCK IN, in minutes east of UTC.
        # `None` means the agenda does not say, which means NO NOW LAYER on this
        # badge no matter how good its clock is -- so it belongs on the line
        # somebody reads when they ask why the marker is missing.  A synced badge
        # reads UTC (`ntptime.settime()` + a verbatim boot-sync copy) and every
        # agenda time is event-local, so this number is the whole bridge.
        schedule["event"]["utc_offset_min"],
        gc.mem_free(),
    )
)
_load.end()
run(update)
