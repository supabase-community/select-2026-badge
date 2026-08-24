# `shared/` -- the canonical copies

**Nothing on the badge imports this directory.** It is not installed, and
it is not on any `sys.path`. It is here so that a reader who finds 9
byte-identical copies of `backlight.py` under `apps/` can tell which one a human
edits.

MicroPython puts exactly one path on `sys.path` -- the running app's own
directory -- so a shared module has to be COPIED into every app that uses
it. `scripts/sync_ui.py` in the full repository owns one table of
canonical sources and their consumers, refreshes the copies, and has a
`--check` mode that hashes every copy against its source and exits
non-zero on drift. CI runs `--check` on every commit.

This export additionally proves it for the shipping subset: its
`gate_vendored_copies_identical` hashes every copy below against the
canonical file, so if this table is wrong the export does not build.

## The map

| module | canonical copy | shipped into |
|---|---|---|
| `backdrop.py` | `shared/backdrop.py` | `badgecard`, `poster` |
| `backlight.py` | `shared/backlight.py` | `badgecard`, `flappy`, `glyph`, `menu`, `pet`, `poster`, `schedule`, `settings`, `snake` |
| `effects.py` | `shared/effects.py` | `badgecard`, `poster` |
| `game_palette.py` | `shared/game_palette.py` | `flappy`, `snake` |
| `glyphskin.py` | *not here* | `badgecard`, `poster` |
| `glyphskins.gpk` | *not here* | `badgecard`, `poster` |
| `identity_catalogue.py` | `apps/badgecard/identity_catalogue.py` | `poster` |
| `identity_faces.py` | *not here* | `badgecard`, `poster` |
| `identity_keyboard.py` | *not here* | `badgecard` |
| `identity_marks.py` | *not here* | `badgecard`, `poster` |
| `idle.py` | `shared/idle.py` | `badgecard`, `menu` |
| `kb_shell.py` | `shared/kb_shell.py` | `badgecard` |
| `kbqwerty_board.py` | *not here* | `badgecard` |
| `loading.py` | `shared/loading.py` | `badgecard`, `flappy`, `glyph`, `menu`, `pet`, `schedule`, `snake` |
| `loading_sql.py` | `shared/loading_sql.py` | `badgecard`, `flappy`, `glyph`, `menu`, `pet`, `schedule`, `snake` |
| `poster.py` | `shared/poster.py` | `badgecard`, `poster` |
| `score_sink.py` | `shared/score_sink.py` | `flappy`, `snake` |
| `skins.py` | *not here* | `badgecard`, `poster` |
| `stickers-36-p8.png` | *not here* | `badgecard`, `poster` |
| `ui.py` | `shared/ui.py` | `badgecard`, `pet`, `poster`, `settings` |
| `wallpaper.py` | `shared/wallpaper.py` | `badgecard`, `menu` |

## The modules whose canonical copy lives in an app

Not every shared module's home is `shared/`. Some grew inside the app
that first needed them and stayed there, and moving one is a real job
rather than a rename -- the paths are hardcoded in host tooling. Where
that is the case the table above points at the app directory that owns
the file, and the other copies of it are generated from there:

- `identity_catalogue.py` is owned by `apps/badgecard/identity_catalogue.py`.

## The modules whose canonical copy is not in this export

These are owned by app trees that no longer ship -- archived
predecessors of the apps that do. The shipping copies in this export
are byte-identical to them (the gate above proves it), so nothing is
missing: the file you are reading IS the source. The canonical path is
named only so that a reader of the full repository knows which copy a
human edits.

- `glyphskin.py` -- canonical at `identity/badge/identity/glyphskin.py` in the full repository, shipped into `badgecard`, `poster`.
- `glyphskins.gpk` -- canonical at `identity/badge/identity/assets/glyphskins.gpk` in the full repository, shipped into `badgecard`, `poster`.
- `identity_faces.py` -- canonical at `identity/badge/identity/identity_faces.py` in the full repository, shipped into `badgecard`, `poster`.
- `identity_keyboard.py` -- canonical at `identity/badge/identity/identity_keyboard.py` in the full repository, shipped into `badgecard`.
- `identity_marks.py` -- canonical at `identity/badge/identity/identity_marks.py` in the full repository, shipped into `badgecard`, `poster`.
- `kbqwerty_board.py` -- canonical at `kbqwerty/badge/kbqwerty/kbqwerty_board.py` in the full repository, shipped into `badgecard`.
- `skins.py` -- canonical at `namebadge/badge/namebadge/skins.py` in the full repository, shipped into `badgecard`, `poster`.
- `stickers-36-p8.png` -- canonical at `namebadge/badge/namebadge/assets/stickers-36-p8.png` in the full repository, shipped into `badgecard`, `poster`.

## What is in this directory

- `backdrop.py`
- `backlight.py`
- `effects.py`
- `game_palette.py`
- `idle.py`
- `kb_shell.py`
- `loading.py`
- `loading_sql.py`
- `poster.py`
- `score_sink.py`
- `ui.py`
- `wallpaper.py`

