# Cleanup census -- what the internal-exhaust classes still cost

**This is a MEASUREMENT, and it is report-only.** It exists because the
second outside review of this package found that the export's cleanup
claim was proved on two roster narratives and nowhere else, so a gate
reported green while the shipping source still read like an internal
engineering ledger. `scripts/export-source.py`'s `internal-exhaust-census` gate
now counts every class below in every exported text file and in
`MANIFEST.json`, and refuses the build only for the class that already
refused it (`device-identifiers`).

Nothing here is a defect on its own. Most of the engineering rationale in
this source is the most valuable thing in it, and a mechanical scrub
would take the reasoning out with the residue. What to remove, what to
reword into local language and what to keep is a judgement call; these
are the numbers to make it with.

## By class

| class | occurrences | files | fatal | what it counts |
|---|---:|---:|:---:|---|
| `device-identifiers` | 0 | 0 | **yes** | a bench badge's 16-hex serial number |
| `val-identifiers` | 14 | 11 | no | `VAL-*` rows in a validation table the reader does not have |
| `owner-quotations` | 217 | 60 | no | a quoted block with an owner attribution beside it |
| `verbatim-ruling-blocks` | 48 | 27 | no | the `*"..."*` verbatim-ruling form, a subset of the line above |
| `benchmark-report-paths` | 23 | 16 | no | a path into `benchmark/results/` |
| `repository-doc-paths` | 203 | 85 | no | a path into `docs/` other than this export's own prose |
| `other-internal-paths` | 201 | 77 | no | a path into another tree this export omits (`*/host/`, `research/`, ...) |

`172` text subjects were scanned: every exported file with a text
extension, plus `MANIFEST.json` as it is about to be written. The
manifest scan cannot include this gate's own row or the row that will
describe this file, which is self-reference rather than a gap.

`owner-quotations` counts a quoted block of twelve characters or more,
containing at least one space, with `owner` or `Sam` within 160
characters before it or 60 after. Plain quoted strings are NOT counted:
this tree holds thousands of double-quoted Python literals and counting
those produces a number nobody can act on, and a quoted token with no
space in it is a JSON key, a path or a hash rather than speech.
`verbatim-ruling-blocks` is the `*"..."*` subset, which is the shape a
mechanical pass could target.

For reference, the launcher's hold contract is `HOLD_MS = 1500 ms` and the
`hold-contract-consistent` gate refuses any exported sentence that names
a different hold duration. That one IS fatal, because a wrong number in
prose is a defect rather than a matter of taste.

## By file

Sorted by total occurrences, then by path. A file absent from this table
carries none of the classes above.

| file | `device-identifiers` | `val-identifiers` | `owner-quotations` | `verbatim-ruling-blocks` | `benchmark-report-paths` | `repository-doc-paths` | `other-internal-paths` | total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `apps/menu/ui.py` | 0 | 0 | 14 | 9 | 4 | 3 | 11 | 41 |
| `apps/settings/settings_copy.py` | 0 | 0 | 25 | 0 | 1 | 4 | 3 | 33 |
| `apps/menu/first_wake.py` | 0 | 0 | 5 | 5 | 0 | 4 | 13 | 27 |
| `apps/poster/tests/test_badge_state.py` | 0 | 0 | 25 | 0 | 0 | 1 | 0 | 26 |
| `apps/settings/settings_model.py` | 0 | 0 | 14 | 0 | 0 | 2 | 0 | 16 |
| `apps/schedule/schedule_view.py` | 0 | 1 | 5 | 0 | 0 | 7 | 2 | 15 |
| `apps/badgecard/card_view.py` | 0 | 0 | 8 | 2 | 0 | 1 | 3 | 14 |
| `apps/badgecard/card_model.py` | 0 | 0 | 3 | 4 | 0 | 4 | 2 | 13 |
| `apps/pacman/pacman_view.py` | 0 | 0 | 4 | 2 | 0 | 5 | 2 | 13 |
| `apps/badgecard/kbqwerty_board.py` | 0 | 0 | 2 | 0 | 0 | 1 | 9 | 12 |
| `apps/breakout/breakout_view.py` | 0 | 0 | 0 | 0 | 0 | 11 | 1 | 12 |
| `apps/flappy/flappy_view.py` | 0 | 0 | 2 | 2 | 0 | 5 | 3 | 12 |
| `apps/pong/pong_view.py` | 0 | 0 | 2 | 0 | 0 | 10 | 0 | 12 |
| `apps/poster/tests/test_poster_app.py` | 0 | 0 | 7 | 1 | 0 | 0 | 4 | 12 |
| `apps/schedule/schedule_model.py` | 0 | 1 | 3 | 1 | 1 | 4 | 2 | 12 |
| `apps/badgecard/idle.py` | 0 | 2 | 4 | 2 | 0 | 3 | 0 | 11 |
| `apps/menu/idle.py` | 0 | 2 | 4 | 2 | 0 | 3 | 0 | 11 |
| `apps/poster/__init__.py` | 0 | 0 | 2 | 1 | 0 | 3 | 5 | 11 |
| `shared/idle.py` | 0 | 2 | 4 | 2 | 0 | 3 | 0 | 11 |
| `MANIFEST.json (as it will be written)` | 0 | 0 | 2 | 0 | 0 | 0 | 8 | 10 |
| `apps/badgecard/poster.py` | 0 | 0 | 1 | 0 | 0 | 3 | 6 | 10 |
| `apps/poster/poster.py` | 0 | 0 | 1 | 0 | 0 | 3 | 6 | 10 |
| `apps/snake/snake_view.py` | 0 | 0 | 0 | 1 | 1 | 8 | 0 | 10 |
| `shared/poster.py` | 0 | 0 | 1 | 0 | 0 | 3 | 6 | 10 |
| `apps-roster.json` | 0 | 0 | 9 | 0 | 0 | 0 | 0 | 9 |
| `apps/badgecard/backdrop.py` | 0 | 0 | 2 | 1 | 2 | 4 | 0 | 9 |
| `apps/glyph/__init__.py` | 0 | 0 | 2 | 0 | 1 | 3 | 3 | 9 |
| `apps/poster/backdrop.py` | 0 | 0 | 2 | 1 | 2 | 4 | 0 | 9 |
| `apps/settings/settings_view.py` | 0 | 0 | 2 | 0 | 1 | 3 | 3 | 9 |
| `shared/backdrop.py` | 0 | 0 | 2 | 1 | 2 | 4 | 0 | 9 |
| `apps/glyph/glyph_render.py` | 0 | 0 | 3 | 0 | 2 | 1 | 2 | 8 |
| `apps/badgecard/effects.py` | 0 | 0 | 1 | 1 | 1 | 0 | 4 | 7 |
| `apps/badgecard/skins.py` | 0 | 0 | 4 | 0 | 0 | 1 | 2 | 7 |
| `apps/badgecard/ui.py` | 0 | 1 | 0 | 0 | 0 | 3 | 3 | 7 |
| `apps/pet/ui.py` | 0 | 1 | 0 | 0 | 0 | 3 | 3 | 7 |
| `apps/poster/effects.py` | 0 | 0 | 1 | 1 | 1 | 0 | 4 | 7 |
| `apps/poster/skins.py` | 0 | 0 | 4 | 0 | 0 | 1 | 2 | 7 |
| `apps/poster/ui.py` | 0 | 1 | 0 | 0 | 0 | 3 | 3 | 7 |
| `apps/settings/ui.py` | 0 | 1 | 0 | 0 | 0 | 3 | 3 | 7 |
| `shared/effects.py` | 0 | 0 | 1 | 1 | 1 | 0 | 4 | 7 |
| `shared/ui.py` | 0 | 1 | 0 | 0 | 0 | 3 | 3 | 7 |
| `apps/badgecard/card_app.py` | 0 | 0 | 3 | 0 | 0 | 1 | 2 | 6 |
| `apps/breakout/game_palette.py` | 0 | 0 | 1 | 1 | 0 | 2 | 2 | 6 |
| `apps/flappy/game_palette.py` | 0 | 0 | 1 | 1 | 0 | 2 | 2 | 6 |
| `apps/pacman/game_palette.py` | 0 | 0 | 1 | 1 | 0 | 2 | 2 | 6 |
| `apps/pong/game_palette.py` | 0 | 0 | 1 | 1 | 0 | 2 | 2 | 6 |
| `apps/snake/game_palette.py` | 0 | 0 | 1 | 1 | 0 | 2 | 2 | 6 |
| `shared/game_palette.py` | 0 | 0 | 1 | 1 | 0 | 2 | 2 | 6 |
| `apps/badgecard/__init__.py` | 0 | 0 | 0 | 0 | 0 | 3 | 2 | 5 |
| `apps/badgecard/card_bake.py` | 0 | 0 | 4 | 0 | 1 | 0 | 0 | 5 |
| `apps/badgecard/kb_shell.py` | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 5 |
| `apps/schedule/__init__.py` | 0 | 1 | 1 | 0 | 0 | 3 | 0 | 5 |
| `apps/settings/__init__.py` | 0 | 0 | 0 | 0 | 0 | 4 | 1 | 5 |
| `shared/kb_shell.py` | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 5 |
| `apps/badgecard/card_faces.py` | 0 | 0 | 0 | 0 | 0 | 1 | 3 | 4 |
| `apps/badgecard/identity_keyboard.py` | 0 | 0 | 2 | 0 | 0 | 0 | 2 | 4 |
| `apps/breakout/score_sink.py` | 0 | 0 | 3 | 0 | 0 | 1 | 0 | 4 |
| `apps/flappy/flappy_scene.py` | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 4 |
| `apps/flappy/score_sink.py` | 0 | 0 | 3 | 0 | 0 | 1 | 0 | 4 |
| `apps/glyph/wave_lights.py` | 0 | 0 | 2 | 0 | 0 | 0 | 2 | 4 |
| `apps/pacman/score_sink.py` | 0 | 0 | 3 | 0 | 0 | 1 | 0 | 4 |
| `apps/pong/score_sink.py` | 0 | 0 | 3 | 0 | 0 | 1 | 0 | 4 |
| `apps/snake/score_sink.py` | 0 | 0 | 3 | 0 | 0 | 1 | 0 | 4 |
| `shared/score_sink.py` | 0 | 0 | 3 | 0 | 0 | 1 | 0 | 4 |
| `apps/badgecard/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `apps/badgecard/card_board.py` | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 3 |
| `apps/badgecard/card_cache.py` | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 3 |
| `apps/badgecard/identity_marks.py` | 0 | 0 | 1 | 0 | 0 | 0 | 2 | 3 |
| `apps/badgecard/wallpaper.py` | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 3 |
| `apps/breakout/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `apps/flappy/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `apps/glyph/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `apps/menu/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `apps/menu/wallpaper.py` | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 3 |
| `apps/pacman/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `apps/pet/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `apps/pong/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `apps/poster/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `apps/poster/identity_marks.py` | 0 | 0 | 1 | 0 | 0 | 0 | 2 | 3 |
| `apps/schedule/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `apps/settings/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `apps/snake/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `shared/backlight.py` | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 3 |
| `shared/wallpaper.py` | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 3 |
| `apps/badgecard/glyphskin.py` | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 2 |
| `apps/badgecard/identity_catalogue.py` | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 2 |
| `apps/breakout/breakout_model.py` | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 2 |
| `apps/pet/pet_atlas.py` | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 2 |
| `apps/poster/badge_state.py` | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 2 |
| `apps/poster/glyphskin.py` | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 2 |
| `apps/poster/identity_catalogue.py` | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 2 |
| `apps/badgecard/card_store.py` | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| `apps/badgecard/identity_faces.py` | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| `apps/badgecard/loading.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `apps/breakout/loading.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `apps/flappy/loading.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `apps/glyph/glyph_rich_lights.py` | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| `apps/glyph/light_calibration_2x.py` | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| `apps/glyph/loading.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `apps/menu/README.md` | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| `apps/menu/loading.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `apps/pacman/loading.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `apps/pet/loading.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `apps/pet/pet_model.py` | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| `apps/pet/pet_store.py` | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| `apps/pong/loading.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `apps/pong/pong_model.py` | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| `apps/poster/identity_faces.py` | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| `apps/poster/tests/poster_harness.py` | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| `apps/schedule/config.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `apps/schedule/loading.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `apps/snake/loading.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `main.py` | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| `shared/loading.py` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `tools/build.py` | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |

