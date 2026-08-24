"""VACUUM.SQL — a brick breaker about reclaiming a bloated table.

The only file in this app that touches Badgeware.  Everything it decides is
either a phase change, an input reading or a light; the physics live in
`breakout_model` and the pixels in `breakout_view`, and neither imports
anything from the badge.
"""

import gc
import os
import random
import sys
import time


APP_ROOT = "/system/apps/breakout"
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)
os.chdir(APP_ROOT)

# THE MODE MOVES ABOVE THE IMPORTS, and it has to.  `badge.mode` rebinds
# `builtins.screen`, so it must run before anything paints.  `Badge.mode()`
# returns early when the mode is unchanged, so out of the launcher (already
# LORES) this costs a comparison.
badge.mode(LORES | VSYNC)

import loading  # noqa: E402
# THIS GAME'S LOAD IS SMALL, and the ceremony is sized to match: three modules,
# one view construction and one short JSON read.  There is no PNG decode, no
# `font.load` and no asset pack anywhere in it -- nothing here is
# indivisible-and-slow, so there is nothing to defer and nothing to chunk.
# What the screen buys is the FIRST FRAME: without it the launcher's last
# picture stays on the panel for the whole import.
#
# THREE STAGES AND NOT SNAKE'S FOUR.  Snake declares four because it also reads
# an accent from `/state/profile.json`; this game has no second file, and a
# fourth stage here would be a `step()` with no work behind it -- exactly the
# decorative count `stages=` exists to catch.  The two `tick()`s subdivide the
# import block so a frame fits between its halves; they deliberately do not
# count stages.
#
# NAMED `_load` AND NOT `load`: this app imports `breakout_store.load` a few
# lines below, and a loading handle a later import silently rebinds is a defect
# nothing would catch until the first `step()`.
_load = loading.begin(3)

import backlight  # noqa: E402
from breakout_model import (  # noqa: E402
    STEP_MS,
    MAX_LEVEL,
    MIN_LEVEL,
    beats_record,
    new_game,
    next_step_clock,
    step,
)
_load.tick("-- breakout_model")
from breakout_store import load, update_high_score  # noqa: E402
_load.tick("-- breakout_store")
from breakout_view import BreakoutView  # noqa: E402
_load.step("-- 4 modules imported")


INTRO = "intro"
PLAYING = "playing"
PAUSED = "paused"
FINISHED = "finished"

# How long a screen dead-keys its COMMANDS after it appears.
#
# `badge.pressed` is a set refreshed at the END of the loop body, so a button
# held during the frame that changes phase is delivered to the screen that has
# only just appeared, one frame later.  Snake reproduced that twice on the
# canonical bytes: the last steering `A` of a run quit a live game one frame
# after the pause card appeared, and an `A` landing on the death frame threw
# the player to the intro with the post-mortem on screen for exactly one frame.
#
# THIS GAME IS THE WORST CASE FOR IT.  A is the scan's left during a run and
# the quit key on the card that B raises, so the most likely key to be physically
# down when the pause card appears is the one key on that card that ends the run.
#
# 90 ms is 3-4 frames at Snake's measured 43.8 fps, sits under the ~250 ms floor
# for a deliberate reply to a screen that just appeared, and is copied rather
# than re-derived because it is measured platform truth.
ARM_MS = 90


def random_below(limit):
    return random.randint(0, limit - 1)


display.backlight(backlight.fraction(backlight.NORMAL))
badge.caselights(0)
view = BreakoutView(screen, image, color, font, vec2)
_load.step("-- view built")
high_score, load_status = load()
_load.step("-- 1 row from /state/breakout.json")
phase = INTRO
game = None
# The default LEVEL is 4, and it is zero-based here, so 3.  The owner chose 4
# on 2026-08-19 after playing all five games; it is a judgement about how the
# game should feel out of the intro, not a value derived from anything in this
# file.  Do not "tidy" it back towards the middle of the ladder.
level_index = 3
last_step = time.ticks_ms()
best = False
light_kind = None
light_until = last_step
frame = 0
confirm_quit = False
# Live from the first frame: no screen inside this app has changed yet, the
# launcher already consumed its own press, and an app whose whole claim is
# "instant to start" must not dead-key the first thing the player does.
armed_at = last_step

print(
    "BREAKOUT_OPEN high={} status={} step_ms={} heap_free={}".format(
        high_score, load_status, STEP_MS, gc.mem_free()
    )
)


def arm_input(now):
    """Dead-key commands for ``ARM_MS`` because the screen just changed.

    Called by every phase transition.  A press that was already in flight when
    the screen changed belongs to the screen the player was looking at, not to
    the one that replaced it.
    """
    global armed_at
    armed_at = time.ticks_add(now, ARM_MS)


def commands_live(now):
    """Whether a command may fire on this frame.

    Only commands are gated.  A direction is never gated: it is never
    destructive, it is corrected by the next press, and a scan that stops
    answering for 90 ms after a resume is the one thing this game may not do.
    """
    return time.ticks_diff(now, armed_at) >= 0


def scan_move():
    """The held direction, as -1, 0 or +1.

    HELD, not pressed.  The scan is a position rather than a command, so it
    tracks a key that is DOWN rather than a key that has just gone down; an
    edge-driven scan would need the player to tap once per 25 ms tick.

    A IS LEFT AND C IS RIGHT, spatially truthful on a screen whose only
    directions these are — A sits at logical x 28 and C at x 127, so the keys
    are where the movement is.  UP and DOWN are inert during a run: this game
    has no vertical axis the player controls, and the button rules leave keys a
    screen does not need free rather than requiring a filler binding.
    """
    if badge.held(BUTTON_A):
        return -1
    if badge.held(BUTTON_C):
        return 1
    return 0


def start_game(now):
    global phase, game, last_step, light_kind, best, confirm_quit
    # The level is read ONCE, here, and lives in the game state from then on.
    game = new_game(level_index + 1, random_below)
    phase = PLAYING
    last_step = now
    light_kind = None
    best = False
    confirm_quit = False
    arm_input(last_step)
    badge.caselights(0)


def set_light(kind, now, duration_ms):
    global light_kind, light_until
    light_kind = kind
    light_until = time.ticks_add(now, duration_ms)


def finish_game(now, won):
    global phase, high_score
    phase = FINISHED
    arm_input(now)
    # Fire the lights BEFORE the atomic save.  There is no audio on this badge,
    # so four case lights are the only instantaneous feedback channel, and a
    # direct write is 252 us median against a save that is 7-130 ms median and
    # 185 ms at the tail.  The screen can lag; the flash cannot.
    badge.caselights(0.85)
    high_score, changed = update_high_score(game["score"], high_score)
    set_light("compacted" if won else "aborted", now, 1800 if won else 1400)
    print(
        "BREAKOUT_FINISH event={} score={} level={} high={} saved={}".format(
            "compacted" if won else "aborted",
            game["score"],
            game["level"],
            high_score,
            changed,
        )
    )


def handle_intro(now):
    global level_index
    if not commands_live(now):
        return
    if badge.pressed(BUTTON_A):
        level_index = max(0, level_index - 1)
    elif badge.pressed(BUTTON_C):
        level_index = min(MAX_LEVEL - MIN_LEVEL, level_index + 1)
    elif badge.pressed(BUTTON_B):
        start_game(now)


def pause_game(now):
    """Freeze the run where it stands and turn the badge dark."""
    global phase, light_kind, confirm_quit
    phase = PAUSED
    light_kind = None
    confirm_quit = False
    arm_input(now)
    badge.caselights(0)
    print(
        "BREAKOUT_PAUSE score={} passes={} high={}".format(
            game["score"], game["passes"], high_score
        )
    )


def resume_game(now):
    """Resume with a fresh clock.

    Without this reset ``next_step_clock`` snaps a stale deadline to ``now`` and
    fires one immediate move on the resume frame — a free, unrequested step at
    the exact moment the player is re-orienting.  This is correctness, not
    polish, and it is why there is no countdown: the court was frozen and
    visible under the card the whole time.
    """
    global phase, last_step, confirm_quit
    phase = PLAYING
    last_step = now
    confirm_quit = False
    arm_input(now)


def quit_game(now):
    """Leave a live run by a labelled door, banking what it earned.

    A labelled way out must not cost the player anything, so the run's score is
    committed on the way out.  The write happens with play stopped, which is the
    same position as the save on an aborted run.
    """
    global phase, high_score, light_kind, confirm_quit
    high_score, changed = update_high_score(game["score"], high_score)
    phase = INTRO
    light_kind = None
    confirm_quit = False
    arm_input(now)
    badge.caselights(0)
    print(
        "BREAKOUT_QUIT score={} level={} high={} saved={}".format(
            game["score"], game["level"], high_score, changed
        )
    )


def handle_paused(now):
    """B resumes on one press; A asks before it ends the run.

    The first A latches a question and changes the card; the second answers it.
    The latch is a state, not a timer: it stays until the player resolves it,
    and B clears it by resuming.
    """
    global confirm_quit
    if not commands_live(now):
        return
    if badge.pressed(BUTTON_B):
        resume_game(now)
    elif badge.pressed(BUTTON_A):
        if confirm_quit:
            quit_game(now)
        else:
            confirm_quit = True
            print("BREAKOUT_QUIT_ASK score={}".format(game["score"]))


def handle_game(now):
    global last_step, best
    if commands_live(now) and badge.pressed(BUTTON_B):
        # Before the direction read and before the movement clock, so the
        # pausing frame never also steps: the frozen court is exactly the court
        # that was on screen when the thumb landed.
        pause_game(now)
        return

    next_clock = next_step_clock(
        now, last_step, STEP_MS, time.ticks_diff, time.ticks_add
    )
    if next_clock is None:
        return
    # The held direction is sampled on the frame the step actually runs, so the
    # scan advances exactly once per tick however fast the panel renders.
    event = step(game, random_below, scan_move())
    last_step = next_clock
    if event == "reclaim":
        set_light("reclaim", now, 120)
        # Beating a stored zero is not an achievement, so the celebration is
        # gated on there being a record to beat.  Once latched it stays for the
        # rest of the run: a mode, continuously indicated, not a hint on a
        # timer.
        if not best and beats_record(game["score"], high_score):
            best = True
            set_light("best", now, 520)
            print("BREAKOUT_BEST score={} beat={}".format(game["score"], high_score))
    elif event == "lost":
        # Longer and structurally different from the reclaim blip: losing a
        # pass is the only thing in a run that cannot be undone, and the lights
        # are the only channel that can say so while the player's eyes are on
        # the worker.
        set_light("lost", now, 320)
        print(
            "BREAKOUT_LOST passes={} score={}".format(
                game["passes"], game["score"]
            )
        )
    elif event == "compacted":
        finish_game(now, True)
    elif event == "aborted":
        finish_game(now, False)


def update_lights(now):
    if light_kind is None or time.ticks_diff(light_until, now) < 0:
        badge.caselights(0)
        return
    if light_kind == "reclaim":
        badge.caselights(0.55)
    elif light_kind == "best":
        # A double blink, distinct from the flat reclaim blip it replaces.
        badge.caselights(0.05 if (time.ticks_diff(now, light_until) // 130) & 1 else 0.7)
    elif light_kind == "lost":
        # Two lit, two dark, swapping: a shape neither the reclaim blip (flat)
        # nor the record blink (all four together) can be confused with.
        swap = (time.ticks_diff(now, light_until) // 80) & 1
        badge.caselights(*((0.05, 0.8) * 2 if swap else (0.8, 0.05) * 2))
    elif light_kind == "compacted":
        # A sweep across the four lights: the table shrinking, once, slowly.
        # It is the only pattern in the app that is not symmetric, because it
        # is the only outcome the player will see once in a session if at all.
        position = (time.ticks_diff(now, light_until) // 150) & 3
        badge.caselights(*[0.85 if index == position else 0.05 for index in range(4)])
    else:
        # Parity chosen so the strobe's FIRST phase is lit: the direct write in
        # finish_game already has the lights on, and an immediately dark phase
        # would cut that flash short instead of continuing it.
        pulse = (time.ticks_diff(now, light_until) // 100) & 1
        badge.caselights(0 if pulse else 0.8)


def handle_finished(now):
    global phase
    if not commands_live(now):
        # The result is the whole point of this screen.  A key that was already
        # moving when the run ended must not delete it unread.
        return
    if badge.pressed(BUTTON_B):
        start_game(now)
    elif badge.pressed(BUTTON_A):
        # The app root is a compliant destination and reaching it needs no
        # reboot; the score was already banked by finish_game, so nothing is
        # written on this path.
        phase = INTRO
        arm_input(now)


def render():
    if phase == INTRO:
        view.intro(level_index + 1, high_score)
    elif phase == PLAYING:
        view.play(game, high_score, best=best)
    elif phase == PAUSED:
        view.paused(game, high_score, best, confirm_quit)
    else:
        view.finished(game, high_score, best)


def update():
    global frame
    now = time.ticks_ms()
    # Input is dispatched once, on the phase this frame started in, and the
    # render then follows whatever phase that left behind.  A handler must
    # never run against a phase another handler just entered, or the frame that
    # pauses would also resume.  This closes the SAME-frame case only; the
    # NEXT-frame case — a button held while the phase changed, whose edge the
    # end-of-loop poll delivers to the new screen — is closed by ARM_MS.
    entry = phase
    if entry == INTRO:
        handle_intro(now)
    elif entry == PLAYING:
        handle_game(now)
    elif entry == PAUSED:
        handle_paused(now)
    else:
        handle_finished(now)
    render()
    update_lights(now)
    frame += 1


_load.end()
run(update)
