# nametag -- the worn badge as a read-only full-screen poster, opened in 14 modules instead of 27

Draws exactly the picture `badgecard` shows at rest, through the same byte-identical `shared/poster.Poster` renderer, and nothing else. It reads `/state/badgecard.json` and writes nothing. This is where the launcher's 1.5-second hold and its 30-second idle handoff both land, so it is the badge's resting face.

**Controls.** Any button (A, B, C, UP, DOWN) exits to the launcher. HOME exits too, via the firmware interrupt. There is no navigation and nothing to edit.

**Non-obvious.** HIRES 320x240; `tests/test_poster_app.py` fails on a second `badge.mode` call anywhere in the package. **It has no idle clock at all** -- not a clock with a rung removed. It is the state the idle ladder exists to reach, so it holds the wearer's brightness for as long as it is open. A still badge costs one VSYNC wait per frame: `badge.default_clear` is set to `None`, so with motion off the app skips every frame after the first and the panel keeps its own pixels. Stage 2 reads the artwork out of `/state/backdrop.bdr` when the editor cached it, skipping both the render and the 666 KB `skins` import.
