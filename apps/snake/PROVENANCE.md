# `snake` provenance

`SNAKE.SQL` began as a faithful port of a documented Pimoroni example and grew
from there. This page is the attribution record the app's `README.md` points at.
The full record, including the design history the port went through, is
`snake/PROVENANCE.md` in the project's repository.

## The ported code

| | |
|---|---|
| Repository | <https://github.com/pimoroni/badgeware-docs> |
| Path | `guides/buttons.md`, section "A tiny snake game", lines 136-180 |
| Commit | `1911532c75cbfd54facbe5c792921fbe9dcce016` |
| Licence | MIT, copyright 2025 Pimoroni Ltd |

The code portion of the first checkpoint was byte-identical to the documented
example. The MIT example is intentionally tiny: fixed length, edge wrapping, no
food, no self-collision, no score and no game-over. Everything after that
checkpoint is project-written, uses the generic Snake rules and the documented
button mapping, and copies no other implementation.

Two facts worth carrying because they are about YOUR firmware rather than about
us:

- the example relies on the launcher already being in LORES 160x120, which it
  is. The shipping app does not rely on that: it calls
  `badge.mode(LORES | VSYNC)` itself, above its imports, because `badge.mode`
  rebinds `builtins.screen` and the loading screen paints before the app's first
  import. `Badge.mode()` returns early when the mode is unchanged, so out of a
  LORES launcher this costs one comparison;
- the example's direct `badge.ticks - last_step` expression is unsafe at the
  32-bit wrap. That was preserved for the faithful checkpoint and replaced with
  `time.ticks_diff()` in the shipping game.

## Sourced artwork: the food mark

`assets/food-p8.png` is generated host-side and its geometry is **not** original
project art. The mark geometry comes from **Simple Icons**
(<https://simpleicons.org>), whose icon files are released **CC0-1.0**.

**CC0 covers the icon files, not the brands.** The trademarks remain the property
of their respective owners. Simple Icons removes marks at a company's request,
and the generator treats a missing slug as the answer rather than sourcing the
mark elsewhere. If these badges are handed to the public, the trademark question
is the owner's to answer.

This is the canonical statement of that position for this project;
`apps/flappy/PROVENANCE.md` points here rather than restating it.

## Everything else

The 24x24 launcher icon and every other pixel the app draws are original project
art. The generator that writes the food sheet is host tooling and is not in this
export.
