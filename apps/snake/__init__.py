"""Project-owned Snake layers built after the preserved Pimoroni faithful port."""

import gc
import os
import random
import sys
import time


APP_ROOT = "/system/apps/snake"
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)
os.chdir(APP_ROOT)

# THE MODE MOVES ABOVE THE IMPORTS, and it has to.  `badge.mode` rebinds
# `builtins.screen`, so it must run before anything paints -- and the loading
# screen paints before this app's first import.  `Badge.mode()` returns early
# when the mode is unchanged, so out of the launcher (already LORES) this costs
# a comparison.
badge.mode(LORES | VSYNC)

import loading  # noqa: E402
# SNAKE'S LOAD IS GENUINELY SMALL, and the ceremony is sized to match: four
# modules, two short JSON reads and one view construction.  There is no PNG
# decode, no `font.load` and no asset pack anywhere in it -- nothing here is
# indivisible-and-slow, so there is nothing to defer and nothing to chunk.
# What the screen buys on this app is the FIRST FRAME: without it the launcher's
# last picture stays on the panel for the whole import.
# NAMED `_load` HERE AND `load` EVERYWHERE ELSE: this app imports
# `snake_store.load` a few lines below, and a loading handle a later
# import silently rebinds is a defect nothing would catch until the
# first `step()`.
_load = loading.begin(4)

import backlight  # noqa: E402
from snake_model import (
    DOWN,
    LEVEL_MS,
    UP,
    beats_record,
    bonus_peak,
    new_game,
    next_animation_frame,
    next_step_clock,
    queue_direction,
    queue_steer_left,
    queue_steer_right,
    step,
)
_load.tick("-- snake_model")
from snake_profile import load_accent  # noqa: E402
from snake_store import load, update_high_score  # noqa: E402
_load.tick("-- snake_store")
from snake_view import SnakeView  # noqa: E402


INTRO = "intro"
PLAYING = "playing"
PAUSED = "paused"
FINISHED = "finished"
# The nine levels, as movement intervals.  The INDEX into this table is the
# level minus one, and the level is also the price of every row the run scores
# and the size of the bonus window, which is why the table itself now lives in
# `snake_model` and this is a re-export: level 9 is eight times faster than
# level 1 and pays nine times as much, so a cautious run cannot reach a bold
# one's number.
SPEEDS_MS = LEVEL_MS
FOOD_FRAME_MS = 110
# How long a screen dead-keys its COMMANDS after it appears.
#
# `badge.pressed` is a set refreshed at the END of the loop body, so a button
# held during the frame that changes phase is delivered to the screen that has
# only just appeared, one frame later.  Reproduced twice on the canonical bytes:
# the last steering `A` of a run quit a live game one frame after the pause card
# appeared, and an `A` landing on the death frame threw the player to the intro
# with the post-mortem on screen for exactly one frame.
#
# One frame would close only the case a driver script can hit.  A thumb already
# travelling towards A when the snake dies lands tens of milliseconds later, and
# it should not be read as an answer to a question the player has not read yet.
# 90 ms is 3-4 frames at this app's measured 43.8 fps, sits under the ~250 ms
# floor for a deliberate reply to a screen that just appeared, and leaves the
# repository's own tightest lane (11 idle frames between the death frame and the
# `B` of the m3 reconnect test) a wide margin.  It is deliberately not a number
# derived from the playground's frame timing, which is not device timing.
ARM_MS = 90


def random_below(limit):
    return random.randint(0, limit - 1)


_load.step("-- 5 modules imported")
display.backlight(backlight.fraction(backlight.NORMAL))
badge.caselights(0)
accent, accent_source = load_accent()
_load.step("-- accent from /state/profile.json")
view = SnakeView(screen, image, color, font, vec2, accent)
_load.step("-- view built")
high_score, high_level, load_status = load()
_load.step("-- 1 row from /state/snake.json")
phase = INTRO
game = None
# The default STAKE is level 4, and it is zero-based here, so 3.  The owner
# chose 4 on 2026-08-19 after playing all five games; it is a judgement about
# how the game should feel out of the intro, not a value derived from anything
# in this file.  Do not "tidy" it back towards the middle of the ladder.
level_index = 3
last_step = time.ticks_ms()
food_frame = 0
food_clock = last_step
best = False
# The bloat count this app has already reported.  A critter that expires is a
# model event with no return value of its own -- one `step` can both feed the
# snake and lose a critter -- so the app notices the counter moving instead of
# asking for a second event channel.
bloat_seen = 0
light_kind = None
light_until = last_step
frame = 0
confirm_quit = False
# Did the last commit attempt fail?  The RECORD is never damaged by a failed
# write -- the sink renames into place or does nothing, so the old file
# survives intact -- but the player is owed the truth on the post-mortem, so
# the flag outlives the frame that set it.
save_failed = False
# True only while a commit is actually in flight.  `on_exit` runs inside the
# HOME interrupt and can therefore land in the middle of the main loop's own
# write, on the same temp path; it stands down rather than interleave with it.
saving = False
# Live from the first frame: no screen inside this app has changed yet, the
# launcher already consumed its own press, and an app whose whole claim is
# "instant to start" must not dead-key the first thing the player does.
armed_at = last_step

print(
    "SNAKE_OPEN high={} level={} status={} accent={} heap_free={}".format(
        high_score, high_level, load_status, accent_source, gc.mem_free()
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
    destructive, it is corrected by the next press, and steering that arrives
    late is the one thing this game may not do.
    """
    return time.ticks_diff(now, armed_at) >= 0


def start_game(now):
    global phase, game, last_step, light_kind, food_frame, food_clock, best, confirm_quit
    global bloat_seen
    # The level is read ONCE, here, and lives in the game state from then on.
    # A wager the player could edit after seeing the board would not be one.
    game = new_game(view.COLS, view.ROWS, random_below, level_index + 1)
    phase = PLAYING
    last_step = now
    food_frame = 0
    food_clock = last_step
    light_kind = None
    best = False
    confirm_quit = False
    bloat_seen = 0
    arm_input(last_step)
    badge.caselights(0)


def advance_food(now):
    """Step the food's heartbeat on its own deadline, never on frame count."""
    global food_frame, food_clock
    food_frame, food_clock = next_animation_frame(
        food_frame,
        view.FOOD_FRAMES,
        now,
        food_clock,
        FOOD_FRAME_MS,
        time.ticks_diff,
        time.ticks_add,
    )


def set_light(kind, now, duration_ms):
    global light_kind, light_until
    light_kind = kind
    light_until = time.ticks_add(now, duration_ms)


def bank_run(reason):
    """Commit the live run's score, and never let the flash cost the game.

    `ScoreSink.write` raises whatever the filesystem raises, and that is the
    right choice THERE: "a badge that cannot write its record must not silently
    believe it did."  It is the wrong choice HERE.  An `OSError` on this line
    leaves `update()`, and the firmware catches it in `_run.__call__`, draws
    `fatal_error()` and calls `machine.reset()` -- so a full volume, a missing
    `/state` or a flash write error would turn EVERY DEATH INTO A REBOOT, on
    the one screen whose entire job is to show the player what they scored.

    The record is the thing that can be lost here.  The game is not.  So the
    failure is caught, named on the serial log and remembered in `save_failed`,
    and the run carries on.

    `OSError` is the whole surface, not a hedge: `mkdir` is already guarded
    inside the sink, `_publish` swallows everything a forwarder raises, and the
    remaining calls -- `open`, `flush`, `os.sync`, `os.rename` -- raise nothing
    else.  Catching wider would hide a real defect in the model instead.
    """
    global high_score, high_level, save_failed, saving
    saving = True
    try:
        high_score, high_level, changed = update_high_score(
            game["score"], game["level"], high_score, high_level
        )
        save_failed = False
        return changed
    except OSError as error:
        save_failed = True
        print(
            "SNAKE_SAVE_ERROR reason={} score={} level={} err={}".format(
                reason, game["score"], game["level"], repr(error)
            )
        )
        return False
    finally:
        saving = False


def finish_game(event, now):
    global phase
    phase = FINISHED
    arm_input(now)
    # Fire the lights BEFORE the atomic save. There is no audio on this badge,
    # so four case lights are the only instantaneous feedback channel, and a
    # direct write is 252 us median against a save that is 7-130 ms median and
    # 185 ms at the tail. The screen can lag; the flash cannot.
    badge.caselights(0.7 if event == "won" else 0.85)
    changed = bank_run("finish")
    set_light("win" if event == "won" else "death", now, 1400)
    print(
        "SNAKE_FINISH event={} score={} level={} high={} high_level={} saved={}"
        " failed={}".format(
            event, game["score"], game["level"], high_score, high_level,
            changed, save_failed
        )
    )


def handle_intro(now):
    global level_index
    if not commands_live(now):
        return
    if badge.pressed(BUTTON_A):
        level_index = max(0, level_index - 1)
    elif badge.pressed(BUTTON_C):
        level_index = min(len(SPEEDS_MS) - 1, level_index + 1)
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
    print("SNAKE_PAUSE score={} high={}".format(game["score"], high_score))


def resume_game(now):
    """Resume with fresh clocks.

    Without this reset ``next_step_clock`` snaps a stale deadline to ``now`` and
    fires one immediate move on the resume frame — a free, unrequested move at
    the exact moment the player is re-orienting.  This is correctness, not
    polish, and it is why there is no countdown: the board was frozen and
    visible under the card the whole time.
    """
    global phase, last_step, food_clock, confirm_quit
    phase = PLAYING
    last_step = now
    food_clock = now
    confirm_quit = False
    arm_input(now)


def quit_game(now):
    """Leave a live run by a labelled door, banking what it earned.

    A labelled way out must not cost the player anything, so the run's score is
    committed on the way out.  The write happens with play stopped, which is the
    same position as the save on death.
    """
    global phase, light_kind, confirm_quit
    changed = bank_run("quit")
    phase = INTRO
    light_kind = None
    confirm_quit = False
    arm_input(now)
    badge.caselights(0)
    print(
        "SNAKE_QUIT score={} level={} high={} high_level={} saved={}"
        " failed={}".format(
            game["score"], game["level"], high_score, high_level, changed,
            save_failed
        )
    )


def handle_paused(now):
    """B resumes on one press; A asks before it ends the run.

    A is the destructive key here and it is also the key that turns the snake
    left one screen earlier, so a player who taps it out of muscle memory must
    not lose the run.  The first A latches a question and changes the card;
    the second answers it.  The latch is a state, not a timer: it stays until
    the player resolves it, and B clears it by resuming.
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
            print("SNAKE_QUIT_ASK score={}".format(game["score"]))


def handle_game(now):
    global last_step, best, bloat_seen
    if commands_live(now) and badge.pressed(BUTTON_B):
        # Before the direction reads and before the movement clock, so the
        # pausing frame never also steps: the frozen board is exactly the board
        # that was on screen when the thumb landed.
        pause_game(now)
        return
    advance_food(now)
    # A IS LEFT AND C IS RIGHT WHILE THE SNAKE TRAVELS VERTICALLY; going
    # across, they are the snake's own left and right.  The table and the whole
    # reasoning live in `snake_model.STEER_LEFT`/`STEER_RIGHT`; what matters
    # here is that both keys are DIRECTIONS, never commands, and that UP and
    # DOWN are untouched and still point where they are drawn.
    if badge.pressed(BUTTON_UP):
        queue_direction(game, UP)
    elif badge.pressed(BUTTON_DOWN):
        queue_direction(game, DOWN)
    elif badge.pressed(BUTTON_A):
        queue_steer_left(game)
    elif badge.pressed(BUTTON_C):
        queue_steer_right(game)

    next_clock = next_step_clock(
        now,
        last_step,
        # Indexed by the RUN's level, not by the intro's current selection, so
        # a game already in flight keeps the pace it was wagered at.
        SPEEDS_MS[game["level"] - 1],
        time.ticks_diff,
        time.ticks_add,
    )
    if next_clock is not None:
        event = step(game, random_below)
        last_step = next_clock
        if event == "ate":
            set_light("eat", now, 150)
            # Beating a stored zero is not an achievement, so the celebration
            # is gated on there being a record to beat.  Once latched it stays
            # for the rest of the run: a mode, continuously indicated, not a
            # hint on a timer.
            if not best and beats_record(game["score"], high_score):
                best = True
                set_light("best", now, 520)
                print("SNAKE_BEST score={} beat={}".format(game["score"], high_score))
        elif event == "vacuum":
            # Longer and brighter than the eat blip: a critter reached late is
            # worth a few rows and one reached early is worth a dozen, and the
            # lights are the only channel that can say "that was the big one"
            # while the player's eyes are on the head.
            set_light("vacuum", now, 300)
            print(
                "SNAKE_BONUS kind={} score={} level={} bloat={}".format(
                    game["bonus_tag"],
                    game["score"],
                    game["level"],
                    game["bloat"],
                )
            )
        elif event in ("dead", "won"):
            finish_game(event, now)
        if game["bloat"] > bloat_seen:
            # A critter timed out. Nothing was lost that the player had, so
            # there is no light for it -- but the next one is worth more, and
            # that is the one thing about this feature worth logging.
            print(
                "SNAKE_BLOAT missed={} next_peak={}".format(
                    game["bloat"], bonus_peak(game["level"], game["bloat"])
                )
            )
        bloat_seen = game["bloat"]


def update_lights(now):
    if light_kind is None or time.ticks_diff(light_until, now) < 0:
        badge.caselights(0)
        return
    if light_kind == "eat":
        badge.caselights(0.55)
    elif light_kind == "best":
        # A double blink, distinct from the flat eat blip it replaces.
        badge.caselights(0.05 if (time.ticks_diff(now, light_until) // 130) & 1 else 0.7)
    elif light_kind == "vacuum":
        # Two lit, two dark, swapping: a shape neither the eat blip (flat) nor
        # the record blink (all four together) can be confused with.
        swap = (time.ticks_diff(now, light_until) // 80) & 1
        badge.caselights(*((0.05, 0.8) * 2 if swap else (0.8, 0.05) * 2))
    elif light_kind == "win":
        active = (time.ticks_diff(now, light_until) // 90) & 3
        badge.caselights(*(0.7 if index == active else 0.03 for index in range(4)))
    else:
        # Parity chosen so the strobe's FIRST phase is lit: the direct write in
        # finish_game already has the lights on, and an immediately dark phase
        # would cut that flash short instead of continuing it.
        pulse = (time.ticks_diff(now, light_until) // 100) & 1
        badge.caselights(0 if pulse else 0.8)


def handle_finished(now):
    global phase
    if not commands_live(now):
        # The post-mortem is the whole point of this screen. A key that was
        # already moving when the snake died must not delete it unread.
        return
    if badge.pressed(BUTTON_B):
        start_game(now)
    elif badge.pressed(BUTTON_A):
        # The app root is a compliant destination, and reaching it needs no
        # reboot; the score was already banked by finish_game, so nothing is
        # written on this path.
        phase = INTRO
        arm_input(now)


def render():
    # THE PHOSPHOR PASS IS APPLIED HERE AND ONLY OVER THE BOARD.  It is one
    # whole-frame native filter (9.340 ms at LORES, measured on device), and it
    # has to run after the WHOLE frame including the status strip -- a filter
    # over the game but not over its own HUD looks like a defect.  `paused()`
    # draws through `play()`, so this is one call per frame, never two.
    #
    # The intro and the post-mortem are deliberately unfiltered: phosphor is a
    # monochrome tint and those two screens carry this app's only colour-coded
    # signals -- the red the death screen says "this is what killed you" in, and
    # the yellow that means a record or a raised stake.  `snake_view.PHOSPHOR`
    # carries the whole argument and is also the one-line way to turn it off.
    if phase == INTRO:
        view.intro(level_index + 1, high_score, high_level, accent_source)
    elif phase == PLAYING:
        view.play(game, high_score, food_frame, best=best)
        view.phosphor_pass()
    elif phase == PAUSED:
        view.paused(game, high_score, food_frame, best, confirm_quit)
        view.phosphor_pass()
    else:
        view.finished(game, high_score, food_frame, best, save_failed)


def update():
    global frame
    now = time.ticks_ms()
    # Input is dispatched once, on the phase this frame started in, and the
    # render then follows whatever phase that left behind.  A handler must
    # never run against a phase another handler just entered, or the frame
    # that pauses would also resume.  This closes the SAME-frame case only;
    # the NEXT-frame case — a button held while the phase changed, whose edge
    # the end-of-loop poll delivers to the new screen — is closed by ARM_MS.
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


def on_exit():
    """Bank a live run on the way out, and never be the reason HOME fails.

    THERE IS AN EXIT CALLBACK AND THIS IS IT.  `launch()` in the firmware
    registers HOME as an interrupt whose handler calls this function and then
    `reset()`, and calls it again on a normal return.  Snake never returns from
    `run(update)`, so in practice this is the interrupt path and nothing else.
    Before it existed, HOME during a live run threw the run away: every other
    door out of a game banks its score -- death does it in `finish_game`, the
    labelled exit does it in `quit_game` -- and the biggest, most obvious key
    on the badge was the one that did not.  A record run ended by the key the
    wearer reaches for by reflex was simply gone.

    IT RUNS INSIDE THE INTERRUPT, WHICH SETS EVERY RULE BELOW.

    It must not raise.  An exception escaping here never reaches `reset()`, so
    HOME stops working and the wearer is trapped in the game with no way back
    to the launcher and no explanation.  That is far worse than the lost score
    this function exists to save, so the whole body sits inside a total
    `except` and the failure path does nothing at all.

    It must not interleave.  The main loop writes through the same temp path,
    and an interrupt landing mid-write could leave a half-written temp file for
    the `rename` to publish -- turning a torn write into a CORRUPT record,
    which is the one outcome the atomic save exists to prevent.  So a commit
    already in flight wins and this stands down; that write is banking the same
    run anyway.

    It is a backstop and not a guarantee.  The crash path resets without ever
    calling it, and when it does run it is microseconds ahead of a queued
    `machine.reset()`, so a save at the 185 ms tail is racing that reset.  This
    is why the other two doors still commit for themselves.
    """
    try:
        badge.caselights(0)
        if saving:
            # The main loop is mid-commit on this very run. Its `rename` is the
            # authoritative one; a second writer here could only corrupt it.
            print("SNAKE_EXIT skipped=write-in-flight")
            return
        if game is None or phase not in (PLAYING, PAUSED):
            # INTRO has no run to bank, and FINISHED already banked one.
            print("SNAKE_EXIT phase={} banked=nothing".format(phase))
            return
        changed = bank_run("exit")
        print(
            "SNAKE_EXIT score={} level={} high={} saved={} failed={}".format(
                game["score"], game["level"], high_score, changed, save_failed
            )
        )
    except Exception as error:  # noqa: BLE001 - HOME must work regardless
        try:
            print("SNAKE_EXIT_ERROR err={}".format(repr(error)))
        except Exception:  # noqa: BLE001 - nothing left worth trying
            pass


_load.end()
run(update)
