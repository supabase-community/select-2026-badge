# breakout -- brick breaker where the bricks are table bloat, the ball is the vacuum worker

Bricks are dead tuples holding heap pages, the ball is the vacuum worker, and the paddle is
the scan position in the heap. Clearing the heap compacts the table; exhausting the three
passes ends the run as a lock-not-available failure. Top rows pay more because a real
VACUUM can only return space by truncating free pages off the *end* of the heap, so the
value ladder is a database fact rather than a difficulty curve.

**Controls.** Intro: A/C change level, B connects. Playing: A and C move the scan left and
right, held rather than tapped; B pauses. Paused: B resumes, A asks then quits. Finished:
B reconnects, A returns to the menu. UP and DOWN are unused on every screen -- the game
has no vertical axis the player controls, and an unused key stays silent rather than being
reassigned. HOME resets to the launcher.

**Non-obvious.** LORES 160x120, court 160x104 under the same 16 px strip pong uses.
Horizontal movement lives on A/C rather than UP/DOWN, the opposite of pong, because the
keys are placed to match the axis on screen. The fixed-point integer model is borrowed
wholesale from `pong_model`. There is no `on_exit` hook, so HOME mid-run loses that run's
score; the high score is `/state/breakout.json` through the shared sink.
