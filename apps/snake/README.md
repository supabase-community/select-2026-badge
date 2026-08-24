# snake -- Snake on an 8 px grid where the food is the Supabase mark; nine levels trade pace for payout

A complete Snake game on a 20x13 board, grown from a licensed Pimoroni tutorial
checkpoint. Eating the animated mark grows one cell and scores the level number, so the
level is both speed (300 ms down to 25 ms per step) and price multiplier. Every fifth row
a database-themed bonus critter joins for 20 ticks: it pays, it decays, and it does not
grow the snake. Self-collision ends in a fake `psql` error block naming the killing cell.

**Controls.** Intro: A/C change level, B starts. Playing: A and C turn, UP/DOWN steer
absolutely, B pauses. Paused: B resumes, A asks then quits (two presses, banking the run).
Death screen: B restarts, A returns to the intro. HOME resets to the launcher. A and C are
a hand-written table rather than a rotation: absolute while the snake travels vertically,
snake-relative while it travels horizontally.

**Non-obvious.** LORES 160x120, set before the imports. It is the only app running a
whole-screen native `screen.phosphor()` filter, and only on the play and pause frames --
the intro and the post-mortem are deliberately unfiltered. High score goes to
`/state/snake.json` through the shared `score_sink`, and it is the only game declaring an
extra field (`high_level`) without a schema bump, so old and new builds read each other's
files. It is one of two apps here with a real `on_exit`, so a live run's score is banked
from inside the HOME interrupt. `PROVENANCE.md` beside this file records the upstream: the
"A tiny snake game" example from Pimoroni's own badgeware-docs, MIT, plus the CC0 mark
geometry the food sheet is drawn from.
