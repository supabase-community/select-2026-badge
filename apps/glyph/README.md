# glyph -- a player for 36 recorded cell-stream animations, with the rear case lights in sync

> **Current production note.** The Glyph viewer does not ship as a tile. The
> production exporter prunes this source into a no-entry-point support root at
> `/system/apps/glyph` containing only what the launcher's first-wake ceremony
> needs. Nametag and Setup carry their own glyph art packs and do not import this
> root. See [`glyph-assets-on-the-badge.md`](../../glyph-assets-on-the-badge.md).

The description below documents the full development/review viewer from which that payload is pruned; it is not the final badge lineup.

Plays packed binary `.gpa` streams through an antialiased mask-bank and RGBA-LUT compositor with per-cell diff drawing, in pure Python: no native code and no `.mpy` dependency of its own. It discovers which decks are actually installed rather than trusting a list, so a pruned asset profile still boots. A HUD names the technique, the density and the measured frame cost.

**Controls.** A/C step to the previous or next entry in one flat list. B toggles the rear case-light animation. UP/DOWN make playback faster or slower. HOME exits, printing stats, detaching the lights and restoring `badge.default_clear`. All five keys are dead for the first 90 ms so the launch press cannot step an entry underneath the wearer.

**Non-obvious.** The deck layout is the design: 18 techniques times 2 densities (`assets/` at 16x6, `assets2x/` at 32x12) laid out technique-major, so one C press is an A/B comparison of the same animation at both grids. Density is an *entry*, not a key binding, because UP/DOWN are screen directions everywhere and B is always the primary action, so there was no key left to take. Cell size is never stated anywhere: the renderer derives it from `screen.width // columns`, which is what lets one constant retarget both decks. It is by far the largest thing on the volume -- around 4.6 MB, roughly 73% of the whole install -- and all of it is assets.
