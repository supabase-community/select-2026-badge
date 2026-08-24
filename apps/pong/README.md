# pong -- Pong themed on database replication: the ball is a WAL segment, the AI bat is the replica

A one-player paddle game against a machine-played opponent. The left bat is the primary
(yours), the right is the replica; each return is one segment synced, and a segment the
replica fails to apply forces a resync that pays five and re-serves. Letting a segment past
your own bat ends the run as a `FATAL` block with detail and hint rows. The level sets the
segment's speed and nothing else.

**Controls.** Intro: A/C change level, B connects. Playing: UP/DOWN move your bat, read at
`badge.held()` level rather than on edges so the bat is a position and not a command; A and
C are inert. Paused: B resumes, A asks then quits. Finished: B reconnects, A returns to the
menu. HOME resets to the launcher.

**Non-obvious.** LORES 160x120. The court is 160x104, the panel minus a 16 px status strip,
and the model never knows the strip exists -- which is what makes it host-testable. The
model is entirely integer fixed point at 1/16-pixel units, because floats on the RP2350 are
software and a float model would force every geometry test to carry a tolerance. There is
no `on_exit` hook, so HOME during a live run discards that run's score: only death and the
labelled quit bank it. The intro opens on level 5 where every other game opens on 4, which
is a feel judgement made with the badge in hand rather than a derived number.
