"""POOLER.SQL — a tap-to-fly game about getting a query through the pool.

The only file in this app that touches Badgeware.  Everything it decides is
either a phase change, an input reading or a light; the flight lives in
`flappy_model` and the pixels in `flappy_view`, and neither imports anything
from the badge.
"""

import gc
import os
import random
import sys
import time


APP_ROOT = "/system/apps/flappy"
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
# NAMED `_load` AND NOT `load`: this app imports `flappy_store.load` a few
# lines below, and a loading handle a later import silently rebinds is a defect
# nothing would catch until the first `step()`.
_load = loading.begin(3)

import backlight  # noqa: E402
from flappy_model import (  # noqa: E402
    STEP_MS,
    MAX_LEVEL,
    MIN_LEVEL,
    beats_record,
    flap,
    new_game,
    next_step_clock,
    step,
)
_load.tick("-- flappy_model")
from score_sink import spool  # noqa: E402
from flappy_store import load, update_high_score  # noqa: E402
_load.tick("-- flappy_store")
from flappy_view import FlappyView  # noqa: E402
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
# 90 ms is 3-4 frames at Snake's measured 43.8 fps, sits under the ~250 ms
# floor for a deliberate reply to a screen that just appeared, and is copied
# rather than re-derived because it is measured platform truth.
#
# IT GATES THE KEEPALIVE TOO, and that is the one decision in this file a
# reviewer should argue with, so the reasoning is in `handle_game` and in
# `flappy/README.md` rather than buried here.
ARM_MS = 90


def random_below(limit):
    return random.randint(0, limit - 1)


display.backlight(backlight.fraction(backlight.NORMAL))
badge.caselights(0)
view = FlappyView(screen, image, color, font, vec2)
_load.step("-- view built, 1 mark sheet decoded")
high_score, load_status = load()
_load.step("-- 1 row from /state/flappy.json")
phase = INTRO
game = None
# The default LEVEL is 4, and it is zero-based here, so 3.  The owner chose 4
# on 2026-08-19 after playing all five games; it is a judgement about how the
# game should feel out of the intro, not a value derived from anything in this
# file.  Do not "tidy" it back towards the middle of the ladder.
level_index = 3
last_step = time.ticks_ms()
# WHEN THE LIVE RUN STARTED, for the duration the leaderboard is sent.  Wall
# time, measured, and it is the only honest source: no model state in this game
# times the PLAYER.  The step clock times the SIMULATION, so a tick count scaled
# by the level's interval would be an in-game figure dressed up as a measurement
# -- and a fabricated duration is worse than a missing one, because nothing
# server-side can falsify it.
#
# A RESUME DOES NOT RESTART IT.  `start_game` is the only writer: the run the
# wearer played is the one that began there, and a pause is INSIDE it.  Re-arming
# this on resume would let a paused run report a duration shorter than the play
# it contains, which is the one direction a floor check must not be fooled in.
run_started = last_step
best = False
# Did the last commit attempt fail?  The RECORD is never damaged by a failed
# write -- the sink renames into place or does nothing, so the old file
# survives intact -- but the post-mortem paints `best` in the record colour,
# and `best` latched against the number that was ON DISK.  Without this flag
# the card claims a bank that is not there, so it outlives the frame that set
# it and reaches the view.
save_failed = False
light_kind = None
light_until = last_step
frame = 0
confirm_quit = False
# Live from the first frame: no screen inside this app has changed yet, the
# launcher already consumed its own press, and an app whose whole claim is
# "instant to start" must not dead-key the first thing the player does.
armed_at = last_step

print(
    "FLAPPY_OPEN high={} status={} step_ms={} heap_free={}".format(
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

    EVERY key in this app is a command — there are no directions on any screen,
    because there is nothing to steer.  UP is not used as a direction here; it
    is a second face for the one action the game has, so it is gated exactly
    like B rather than being waved through as a direction the way Pong's
    paddle keys are.
    """
    return time.ticks_diff(now, armed_at) >= 0


def start_game(now):
    global phase, game, last_step, light_kind, best, confirm_quit, run_started
    # The load is read ONCE, here, and lives in the game state from then on.
    game = new_game(level_index + 1, random_below)
    phase = PLAYING
    last_step = now
    run_started = now
    light_kind = None
    best = False
    confirm_quit = False
    arm_input(last_step)
    badge.caselights(0)


def set_light(kind, now, duration_ms):
    global light_kind, light_until
    light_kind = kind
    light_until = time.ticks_add(now, duration_ms)


def finish_game(now):
    global phase, high_score, save_failed
    phase = FINISHED
    arm_input(now)
    # Fire the lights BEFORE the atomic save.  There is no audio on this badge,
    # so four case lights are the only instantaneous feedback channel, and a
    # direct write is 252 us median against a save that is 7-130 ms median and
    # 185 ms at the tail.  The screen can lag; the flash cannot.
    badge.caselights(0.85)
    # A death must never reset the badge.  `ScoreSink.write` raises whatever
    # the filesystem raises -- the right choice THERE -- but an `OSError`
    # escaping `update()` reaches the firmware's `fatal_error()` and
    # `machine.reset()`, so a full volume (ENOSPC) would turn every dropped
    # connection into a REBOOT on the one screen whose whole job is to show
    # the score.  Guard shape from snake's `bank_run` (the pattern origin).
    # `OSError` is the whole write surface, not a hedge: `mkdir` is already
    # guarded inside the sink, `_publish` swallows whatever a forwarder
    # raises, and open/flush/os.sync/os.rename raise nothing else, so catching
    # wider would hide a real defect in the model.
    try:
        high_score, changed = update_high_score(game["score"], high_score)
        # Cleared on every success, not only set on failure: the card this
        # feeds renders one frame later and must describe THIS commit, not a
        # stale one from an earlier run in the same session.
        save_failed = False
    except OSError as error:
        save_failed = True
        changed = False
        print(
            "FLAPPY_SAVE_ERROR reason=finish score={} level={} err={}".format(
                game["score"], game["level"], repr(error)
            )
        )
    # EVERY COMPLETED RUN SUBMITS (owner ruling, 2026-08-27): one line, no
    # client-side filtering, because personal-best-on-the-badge would be
    # judgment and all judgment is SQL and hot-patchable.  AFTER the local save,
    # for `score_sink`'s non-negotiable reason -- disk first, disk wins -- and it
    # runs whether or not that save landed: a losing run writes nothing at all
    # and still counts, and a full volume that cost the record must not also cost
    # the leaderboard row.  `spool` never raises and does nothing at all on a
    # badge with no `/system/lib`.
    # GUARDED AT THE CALL SITE ANYWAY (owner ruling, 2026-08-27), and it is a
    # ruling rather than superstition: an unguarded persistence write on
    # game-over turned every death into a badge RESET once already, which is
    # where the save guard above comes from.  `spool` swallows a raising store
    # itself, so what only THIS `try` can catch is the ARGUMENT EVALUATION and a
    # `spool` from a build that broke its own contract -- both a reset if they
    # escape.  The print is what stops the guard from hiding a real defect: the
    # serial log names the class, and a silent `pass` here would not.
    try:
        spool("flappy", game["score"],
              time.ticks_diff(now, run_started))
    except Exception as error:  # noqa: BLE001 - a reset is the alternative
        print("FLAPPY_SPOOL_ERROR score={} err={}".format(
            game["score"], repr(error)))
    set_light("refused", now, 1400)
    print(
        "FLAPPY_FINISH score={} level={} cause={} high={} saved={}".format(
            game["score"], game["level"], game["cause"], high_score, changed
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
    print("FLAPPY_PAUSE score={} high={}".format(game["score"], high_score))


def resume_game(now):
    """Resume with a fresh clock.

    Without this reset ``next_step_clock`` snaps a stale deadline to ``now``
    and fires one immediate move on the resume frame — a free, unrequested
    step at the exact moment the player is re-orienting, and in this game that
    step is a fall.  This is correctness, not polish, and it is why there is no
    countdown: the world was frozen and visible under the card the whole time.
    """
    global phase, last_step, confirm_quit
    phase = PLAYING
    last_step = now
    confirm_quit = False
    arm_input(now)


def quit_game(now):
    """Leave a live run by a labelled door, banking what it earned.

    A labelled way out must not cost the player anything, so the run's score is
    committed on the way out.  The write happens with play stopped, which is
    the same position as the save on a refused connection.
    """
    global phase, high_score, light_kind, confirm_quit, save_failed
    try:
        high_score, changed = update_high_score(game["score"], high_score)
        save_failed = False
    except OSError as error:
        # Same guard as finish_game's, same WHY: an escaping OSError reaches
        # machine.reset(), so a full volume would turn the labelled door into
        # a REBOOT.  The record is what can be lost here; the way out is not.
        save_failed = True
        changed = False
        print(
            "FLAPPY_SAVE_ERROR reason=quit score={} level={} err={}".format(
                game["score"], game["level"], repr(error)
            )
        )
    # THE LABELLED DOOR SUBMITS TOO, and that is the ruling rather than a
    # preference: deciding that a walked-away run "does not count" is judgment,
    # and judgment is SQL's, where it can be changed mid-event.  This app already
    # treats a quit as a completed run -- it banks it to flash three lines up --
    # so the spool follows the door the record already went through.
    # GUARDED AT THE CALL SITE ANYWAY (owner ruling, 2026-08-27), and it is a
    # ruling rather than superstition: an unguarded persistence write on
    # game-over turned every death into a badge RESET once already, which is
    # where the save guard above comes from.  `spool` swallows a raising store
    # itself, so what only THIS `try` can catch is the ARGUMENT EVALUATION and a
    # `spool` from a build that broke its own contract -- both a reset if they
    # escape.  The print is what stops the guard from hiding a real defect: the
    # serial log names the class, and a silent `pass` here would not.
    try:
        spool("flappy", game["score"],
              time.ticks_diff(now, run_started))
    except Exception as error:  # noqa: BLE001 - a reset is the alternative
        print("FLAPPY_SPOOL_ERROR score={} err={}".format(
            game["score"], repr(error)))
    phase = INTRO
    light_kind = None
    confirm_quit = False
    arm_input(now)
    badge.caselights(0)
    print(
        "FLAPPY_QUIT score={} level={} high={} saved={}".format(
            game["score"], game["level"], high_score, changed
        )
    )


def handle_paused(now):
    """B resumes on one press; A asks before it ends the run.

    A IS THE KEY THAT OPENED THIS CARD, which is why the question exists at
    all: a player tapping A twice out of habit would otherwise pause and then
    immediately end his own run.  The first A latches the question and changes
    the card; the second answers it.  The latch is a state, not a timer: it
    stays until the player resolves it, and B clears it by resuming.
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
            print("FLAPPY_QUIT_ASK score={}".format(game["score"]))


def handle_game(now):
    global last_step, best
    if commands_live(now) and badge.pressed(BUTTON_A):
        # Before the keepalive and before the movement clock, so the pausing
        # frame never also flaps or steps: the frozen world is exactly the
        # world that was on screen when the thumb landed.
        pause_game(now)
        return

    # THE KEEPALIVE IS SAMPLED HERE, ABOVE THE MOVEMENT CLOCK, AND THAT IS THE
    # WHOLE LATENCY DECISION.  The impulse is applied to the model at once
    # rather than latched for the next tick, so on a frame where a step is also
    # due the client is already rising in the frame the press was seen.  Read
    # after the clock instead and every tap would wait a full interval before
    # anything moved.
    #
    # Worst case from thumb to pixel is therefore one poll frame (the pressed
    # set is refreshed at the end of the loop body: ~23 ms on the badge's
    # measured 43.8 fps) plus at most one 25 ms step, so 48 ms; best case is
    # the poll frame alone.  Both sit under the ~100 ms at which a tap stops
    # feeling connected to the thing it moved.
    #
    # It is an EDGE and never a hold: holding B is one keepalive, not lift.
    # The model's impulse SETS the velocity, so two taps inside one step
    # collapse to one climb rather than stacking into a jump the ladder was
    # never designed around.
    if commands_live(now) and (
        badge.pressed(BUTTON_B) or badge.pressed(BUTTON_UP)
    ):
        flap(game)

    next_clock = next_step_clock(
        now, last_step, STEP_MS, time.ticks_diff, time.ticks_add
    )
    if next_clock is None:
        return
    event = step(game, random_below)
    last_step = next_clock
    if event == "served":
        set_light("served", now, 120)
        # Beating a stored zero is not an achievement, so the celebration is
        # gated on there being a record to beat.  Once latched it stays for the
        # rest of the run: a mode, continuously indicated, not a hint on a
        # timer.
        if not best and beats_record(game["score"], high_score):
            best = True
            set_light("best", now, 520)
            print("FLAPPY_BEST score={} beat={}".format(game["score"], high_score))
    elif event == "dead":
        finish_game(now)


def update_lights(now):
    if light_kind is None or time.ticks_diff(light_until, now) < 0:
        badge.caselights(0)
        return
    if light_kind == "served":
        # A flat blip, once per query.  THE KEEPALIVE ITSELF IS NOT LIT: a tap
        # happens several times a second and a light on every one is a strobe,
        # not feedback.  The screen already answers a tap, instantly, by moving
        # the thing the player is looking at.
        badge.caselights(0.55)
    elif light_kind == "best":
        # A double blink, distinct from the flat served blip it replaces.
        badge.caselights(0.05 if (time.ticks_diff(now, light_until) // 130) & 1 else 0.7)
    else:
        # Parity chosen so the strobe's FIRST phase is lit: the direct write in
        # finish_game already has the lights on, and an immediately dark phase
        # would cut that flash short instead of continuing it.
        pulse = (time.ticks_diff(now, light_until) // 100) & 1
        badge.caselights(0 if pulse else 0.8)


def handle_finished(now):
    global phase
    if not commands_live(now):
        # The result is the whole point of this screen, and B is pressed
        # constantly in this game.  A keepalive that was already in flight when
        # the pool refused the client must not delete the result unread.
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
        view.finished(game, high_score, best, save_failed)


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
