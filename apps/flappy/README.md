# flappy -- tap-to-fly where you are a client connection and the pipes are a pooler's slots

Written from the genre's public description rather than ported. You are a client
connection; gravity is the idle timer reclaiming a connection that stopped talking, and
each tap is a keepalive. Clearing a pipe pair serves a query; touching a pipe, the floor or
the ceiling is the pool refusing you, and the death screen names the query that killed you.
The nine loads narrow the gap from 46 px down to 30 px.

**Controls.** This is the deliberate inversion: **A is pause and B is the flap.** Intro:
A/C change load, B connects. Playing: B or UP flaps, A pauses. Paused: B resumes, A quits
-- and because A also opened the pause card, the quit is a two-press confirm so a habitual
double-tap of A cannot end your own run. DOWN is unused on every screen; there is nothing
to steer downwards. HOME resets to the launcher.

**Non-obvious.** LORES 160x120, world 160x104 matching snake's and pong's playfield so all
three sit in the same place on the panel. The flap impulse is applied to the model
immediately rather than latched for the next tick, which is the whole latency decision. The
Supabase mark ships at 12 px rather than the visually better 16 px purely for collision
honesty: the model hitbox is 8 px at every size, so a 16 px mark would put up to 5 px of ink
inside a lethal collar while the game correctly says nothing happened. `PROVENANCE.md` beside
this file records that this is not a port, that no upstream implementation was read, and where
the one sourced pixel came from.
