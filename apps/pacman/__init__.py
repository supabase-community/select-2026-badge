"""CURSOR.SQL — a maze game about a cursor doing a table scan.

The only file in this app that touches Badgeware.  Everything it decides is
either a phase change, an input reading or a light; the game lives in
`pacman_model` and the pixels in `pacman_view`, and neither imports anything
from the badge.
"""

import gc
import os
import random
import sys
import time


APP_ROOT = "/system/apps/pacman"
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
# NAMED `_load` AND NOT `load`: this app imports `pacman_store.load` a few
# lines below, and a loading handle a later import silently rebinds is a defect
# nothing would catch until the first `step()`.
_load = loading.begin(3)

import backlight  # noqa: E402
from pacman_model import (  # noqa: E402
    DOWN,
    FLEE,
    GHOST_NAMES,
    LEFT,
    MAX_LEVEL,
    MIN_LEVEL,
    RIGHT,
    STEP_MS,
    SUPER_WARN_TICKS,
    UP,
    beats_record,
    new_game,
    next_step_clock,
    queue_direction,
    step,
)
_load.tick("-- pacman_model")
from pacman_store import load, update_high_score  # noqa: E402
_load.tick("-- pacman_store")
from pacman_view import PacmanView  # noqa: E402
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
# 90 ms is 3-4 frames at Snake's measured 43.8 fps, sits under the ~250 ms floor
# for a deliberate reply to a screen that just appeared, and is copied rather
# than re-derived because it is measured platform truth.
ARM_MS = 90

# The one animation clock in the app.  It drives the cursor's bite, the
# pellets' blink and the SUPERUSER expiry warning together, because three
# clocks would be three things to keep in step and a player reads them as one
# heartbeat regardless.  110 ms is close enough to the 130 ms movement tick to
# look like the same creature moving and far enough off it not to beat against
# it.
ANIM_MS = 110


def random_below(limit):
    return random.randint(0, limit - 1)


display.backlight(backlight.fraction(backlight.NORMAL))
badge.caselights(0)
view = PacmanView(screen, image, color, font, vec2)
_load.step("-- view built")
high_score, load_status = load()
_load.step("-- 1 row from /state/pacman.json")
phase = INTRO
game = None
level_index = 2
last_step = time.ticks_ms()
anim = 0
anim_clock = last_step
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
    "PACMAN_OPEN high={} status={} step_ms={} heap_free={}".format(
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

    Only commands are gated.  A DIRECTION IS NEVER GATED: it is never
    destructive, it is corrected by the next press, and a cursor that stops
    answering for 90 ms while four chasers keep moving is the one thing this
    game may not do.
    """
    return time.ticks_diff(now, armed_at) >= 0


def advance_anim(now):
    """Step the one animation counter on its own deadline, never on frames.

    Shares `next_step_clock`'s semantics deliberately: at most one step per
    rendered frame, and a long hitch is discarded rather than replayed as a
    burst.
    """
    global anim, anim_clock
    due = next_step_clock(
        now, anim_clock, ANIM_MS, time.ticks_diff, time.ticks_add
    )
    if due is not None:
        anim = (anim + 1) & 3
        anim_clock = due


def set_light(kind, now, duration_ms):
    global light_kind, light_until
    light_kind = kind
    light_until = time.ticks_add(now, duration_ms)


def start_game(now):
    global phase, game, last_step, anim, anim_clock, light_kind, best
    global confirm_quit
    # The level is read ONCE, here, and lives in the game state from then on.
    # A wager the player could edit after seeing the maze would not be one.
    game = new_game(level_index + 1, random_below)
    phase = PLAYING
    last_step = now
    anim = 0
    anim_clock = now
    light_kind = None
    best = False
    confirm_quit = False
    arm_input(last_step)
    badge.caselights(0)


def finish_game(event, now):
    global phase, high_score
    phase = FINISHED
    arm_input(now)
    # Fire the lights BEFORE the atomic save.  There is no audio on this badge,
    # so four case lights are the only instantaneous feedback channel, and a
    # direct write is 252 us median against a save that is 7-130 ms median and
    # 185 ms at the tail.  The screen can lag; the flash cannot.
    badge.caselights(0.7 if event == "cleared" else 0.85)
    high_score, changed = update_high_score(game["score"], high_score)
    set_light("cleared" if event == "cleared" else "caught", now, 1400)
    print(
        "PACMAN_FINISH event={} score={} level={} rows_left={} by={} "
        "high={} saved={}".format(
            event,
            game["score"],
            game["level"],
            game["dots"],
            GHOST_NAMES[game["caught_by"]] if game["caught_by"] >= 0 else "-",
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
        "PACMAN_PAUSE score={} lives={} rows_left={} high={}".format(
            game["score"], game["lives"], game["dots"], high_score
        )
    )


def resume_game(now):
    """Resume with fresh clocks.

    Without this reset ``next_step_clock`` snaps a stale deadline to ``now``
    and fires one immediate move on the resume frame — a free, unrequested step
    at the exact moment the player is re-orienting, and in this game a free
    step can walk the cursor into a chaser.  This is correctness, not polish,
    and it is why there is no countdown: the maze was frozen and visible under
    the card the whole time.
    """
    global phase, last_step, anim_clock, confirm_quit
    phase = PLAYING
    last_step = now
    anim_clock = now
    confirm_quit = False
    arm_input(now)


def quit_game(now):
    """Leave a live run by a labelled door, banking what it earned.

    A labelled way out must not cost the player anything, so the run's score is
    committed on the way out.  The write happens with play stopped, which is
    the same position as the save on a cancelled query.
    """
    global phase, high_score, light_kind, confirm_quit
    high_score, changed = update_high_score(game["score"], high_score)
    phase = INTRO
    light_kind = None
    confirm_quit = False
    arm_input(now)
    badge.caselights(0)
    print(
        "PACMAN_QUIT score={} level={} high={} saved={}".format(
            game["score"], game["level"], high_score, changed
        )
    )


def handle_paused(now):
    """B resumes on one press; A asks before it ends the run.

    A is the destructive key here and it is ALSO the key that walks the cursor
    left one screen earlier, so a player who taps it out of muscle memory must
    not lose the run.  The first A latches a question and changes the card; the
    second answers it.  The latch is a state, not a timer: it stays until the
    player resolves it, and B clears it by resuming.
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
            print("PACMAN_QUIT_ASK score={}".format(game["score"]))


def handle_game(now):
    global last_step, best
    if commands_live(now) and badge.pressed(BUTTON_B):
        # Before the direction reads and before the movement clock, so the
        # pausing frame never also steps: the frozen maze is exactly the maze
        # that was on screen when the thumb landed.
        pause_game(now)
        return
    advance_anim(now)
    # ALL FOUR KEYS ARE ABSOLUTE DIRECTIONS.  UP is up, DOWN is down, A is the
    # screen's left and C is the screen's right, on every heading and every
    # frame.  Snake's A and C are relative turns because a snake travelling
    # horizontally has nothing to be absolute about; this game has a real 2-D
    # axis, so all four keys are spatially truthful and stay that way.  None of
    # them is ever a command, which is why there is no softkey bar.
    if badge.pressed(BUTTON_UP):
        queue_direction(game, UP)
    elif badge.pressed(BUTTON_DOWN):
        queue_direction(game, DOWN)
    elif badge.pressed(BUTTON_A):
        queue_direction(game, LEFT)
    elif badge.pressed(BUTTON_C):
        queue_direction(game, RIGHT)

    next_clock = next_step_clock(
        now, last_step, STEP_MS, time.ticks_diff, time.ticks_add
    )
    if next_clock is None:
        return
    event = step(game, random_below)
    last_step = next_clock
    if event == "cleared":
        finish_game(event, now)
        return
    if event == "caught":
        if game["status"] == "dead":
            finish_game(event, now)
            return
        # A life lost with lives left is not a phase change: the model freezes
        # the board for a beat and the player reads the reset positions under
        # a strobe.  The badge says so in the only instantaneous channel it
        # has.
        set_light("caught", now, 600)
        print(
            "PACMAN_CAUGHT by={} lives={} score={}".format(
                GHOST_NAMES[game["caught_by"]], game["lives"], game["score"]
            )
        )
        return
    if event == "ghost":
        print(
            "PACMAN_GHOST paid={} combo={} score={}".format(
                game["last_ghost"], game["combo"], game["score"]
            )
        )
    if event in ("dot", "pellet", "ghost"):
        # Beating a stored zero is not an achievement, so the celebration is
        # gated on there being a record to beat.  Once latched it stays for the
        # rest of the run: a mode, continuously indicated, not a hint on a
        # timer.
        if not best and beats_record(game["score"], high_score):
            best = True
            set_light("best", now, 520)
            print("PACMAN_BEST score={} beat={}".format(game["score"], high_score))


def update_lights(now):
    """Four case lights, four ways a query dies.

    There is no audio on this badge, so the lights are the whole of the
    non-visual channel, and this game has exactly as many of them as it has
    chasers.  Under SUPERUSER each light IS its ghost: lit while that one is
    still out there and catchable, dark the instant it is consumed.  A player
    with their eyes on the maze can count what is left on their own case, and a
    bystander can see that something has changed.

    Everything else is an event on a timer, and an event outranks the state
    display for as long as it lasts.
    """
    global light_kind
    if light_kind is not None and time.ticks_diff(light_until, now) < 0:
        light_kind = None
    if light_kind == "caught":
        # Parity chosen so the strobe's FIRST phase is lit: `finish_game`
        # already has the lights on, and an immediately dark phase would cut
        # that flash short instead of continuing it.
        pulse = (time.ticks_diff(now, light_until) // 100) & 1
        badge.caselights(0 if pulse else 0.85)
        return
    if light_kind == "cleared":
        active = (time.ticks_diff(now, light_until) // 90) & 3
        badge.caselights(*(0.7 if index == active else 0.03 for index in range(4)))
        return
    if light_kind == "best":
        # A double blink on all four, distinct from both the per-ghost display
        # and the death strobe.
        badge.caselights(0.05 if (time.ticks_diff(now, light_until) // 130) & 1 else 0.7)
        return
    if phase == PLAYING and game is not None and game["super"]:
        lit = 0.7
        if game["super"] <= SUPER_WARN_TICKS and (now // 120) & 1:
            # The window is closing.  The same warning the fleeing ghosts show
            # on the panel, on the channel a player who is not looking down
            # still has.
            lit = 0.1
        badge.caselights(
            *(lit if ghost["state"] == FLEE else 0.03 for ghost in game["ghosts"])
        )
        return
    badge.caselights(0)


def handle_finished(now):
    global phase
    if not commands_live(now):
        # The result is the whole point of this screen.  A key that was already
        # moving when the query was cancelled must not delete it unread.
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
        view.play(game, high_score, anim, best=best)
    elif phase == PAUSED:
        view.paused(game, high_score, anim, best, confirm_quit)
    else:
        view.finished(game, high_score, anim, best)


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
