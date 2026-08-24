# `flappy` provenance

`POOLER.SQL` is original project code. It is not a port: no upstream Flappy Bird implementation was read, copied or adapted, and the game rules in `flappy_model.py` were written from the genre's public description (gravity, a tap that adds upward velocity, a scrolling gap to fly through). Nothing in this app is under a third-party code licence.

One pixel of it is sourced, and this page exists for that one. The full record is `flappy/PROVENANCE.md` in the project's repository.

## Sourced artwork: the client mark

`assets/client-p8.png` is the Supabase mark, and it is the thing the player is: a client holding a pooled connection open.

| | |
|---|---|
| SHA-256 | `73b59abf7c2b41f28dff0761e323ba0f80a812dea5fa1b2a231e421036cb38af` |
| Bytes | 290 |
| Geometry | 96x24 indexed-P8: 8 animation frames x 2 ink rows, cell 12x12 |
| Immediate source | the project's own 36 px sticker sheet, row 0 columns 0-7 |
| Mark geometry | **Simple Icons** (<https://simpleicons.org>), slug `supabase`, pinned at version `16.28.0` |
| Licence | **CC0-1.0**: the icon *files* are CC0, the *trademarks* are not |

**`apps/snake/PROVENANCE.md` is the canonical licence statement** and this is a pointer to it. The trademark position, the "CC0 covers the icon files, not the brands" distinction, and the note that public distribution is the owner's call are written down once, there, and are not restated here in a form that could drift away from it.

### The chain is one link longer than Snake's, and it costs fidelity

Snake's generator rasterises straight from the SVG. This one resamples the already-rasterised 36 px cell down to the app's 12 px cell, so it inherits that sheet's quantisation. Measured: this route's 36 to 12 mask differs from Snake's 12 px mask by 10 of 144 pixels (7%), all on the mark's thin top and bottom tips, which this route keeps slightly more of (62 lit against 52). The shape is the same bolt.

### Why the mark is drawn larger than the hitbox

The model's collision box is `M.CLIENT = 8` px and stays there at every mark size, because the reachability fuzz was written against that hitbox. So the mark is a drawing that overhangs it, deliberately:

| cell | overhang per side | widest ink outside the hitbox | share of the level-9 margin |
|---:|---:|---:|---:|
| 12 px (ships) | 2 px | 3 px of a 10 px mark | 9% |
| 16 px | 4 px | 5 px of a 14 px mark | 18% |

`LEVEL_GAP[8]` is 30 px, so a level-9 gap leaves an 8 px client 22 px of legal travel. 12 px ships because at 16 px up to 5 px of the mark's width would sit inside a lethal collar while the game correctly says nothing has happened, and a picture that contradicts its mechanic is worse than a plainer one.

## Everything else

The 24x24 launcher icon is generated host-side. The room, the pipes, the racks, the cable and the rails are project-written rectangles. The SQLSTATE strings on the death screen are Postgres's own error codes, which are facts rather than artwork. The palette's three green steps are the project's own brand hexes, taken from `shared/game_palette.py`.
