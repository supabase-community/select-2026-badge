# pacman -- maze chase where you are a cursor doing a table scan and four named failures hunt you

A maze game on a fixed 20x13 grid with three lives. The player is a cursor walking a heap;
every dot is a row read, and clearing the maze completes the scan. A power pellet grants
superuser for 48 ticks, during which the four chasers -- deadlock, timeout, rollback and
OOM -- flee and can be eaten. Being caught reports a deadlock and names the culprit in its
own board colour.

**Controls.** Intro: A/C change level, B connects. Playing: A and C move left and right,
UP/DOWN move up and down, all four absolute and spatially truthful, explicitly unlike
snake's relative A/C, because this game has a real two-dimensional axis. No direction is
ever a command, which is why there is no softkey bar. B pauses; paused, A asks then quits.
HOME resets to the launcher.

**Non-obvious.** LORES 160x120. The step is 130 ms, much slower than the 25 ms tick of
pong, breakout and flappy, and a separate 110 ms animation clock drives the pellet blink
and the superuser expiry warning together rather than adding a third clock. Direction
presses are never gated by the 90 ms dead-key window that covers commands: a cursor deaf
for 90 ms while four chasers keep moving is the one thing this game may not do. The model
reads no clock at all -- every duration is counted in ticks -- so a frozen board is
genuinely frozen. There is no `on_exit` hook, so HOME mid-run loses that run's score.
