# `shared/` -- the canonical copies

**Nothing on the badge imports this directory.** It is not installed, and it is not on any `sys.path`. It is here so that a reader who finds 7 byte-identical copies of `backlight.py` under `apps/` can tell which one a human edits.

MicroPython puts exactly one path on `sys.path` -- the running app's own directory -- so a shared module has to be COPIED into every app that uses it. `scripts/sync_ui.py` in the full repository owns one table of canonical sources and their consumers, refreshes the copies, and has a `--check` mode that hashes every copy against its source and exits non-zero on drift. Maintainers run the repository's production lane by hand, and that lane invokes `--check`; there is no tracked CI configuration or hook setup.

This export additionally proves it for the shipping subset: its `gate_vendored_copies_identical` hashes every copy below against the canonical file, so if this table is wrong the export does not build.

## The map

| module | canonical copy | shipped into |
|---|---|---|
| `backdrop.py` | `shared/backdrop.py` | `nametag`, `setup` |
| `backlight.py` | `shared/backlight.py` | `flappy`, `menu`, `nametag`, `schedule`, `settings`, `setup`, `snake` |
| `card_name_positions.py` | `apps/setup/card_name_positions.py` | `nametag` |
| `effects.py` | `shared/effects.py` | `nametag`, `setup` |
| `game_palette.py` | `shared/game_palette.py` | `flappy`, `snake` |
| `glyphskin.py` | *not here* | `nametag`, `setup` |
| `glyphskins.gpk` | *not here* | `nametag`, `setup` |
| `identity_catalogue.py` | `apps/setup/identity_catalogue.py` | `nametag` |
| `identity_faces.py` | *not here* | `nametag`, `setup` |
| `identity_keyboard.py` | *not here* | `setup` |
| `identity_marks.py` | *not here* | `nametag`, `setup` |
| `idle.py` | `shared/idle.py` | `menu`, `setup` |
| `kb_shell.py` | `shared/kb_shell.py` | `setup` |
| `kbqwerty_board.py` | *not here* | `setup` |
| `loading.py` | `shared/loading.py` | `flappy`, `menu`, `schedule`, `setup`, `snake` |
| `loading_sql.py` | `shared/loading_sql.py` | `flappy`, `menu`, `schedule`, `setup`, `snake` |
| `nametag.py` | `shared/nametag.py` | `nametag`, `setup` |
| `score_sink.py` | `shared/score_sink.py` | `flappy`, `snake` |
| `skins.py` | *not here* | `nametag`, `setup` |
| `stickers-36-p8.png` | *not here* | `nametag`, `setup` |
| `ui.py` | `shared/ui.py` | `nametag`, `settings`, `setup` |
| `wallpaper.py` | `shared/wallpaper.py` | `menu`, `setup` |

## The modules whose canonical copy lives in an app

Not every shared module's home is `shared/`. Some grew inside the app that first needed them and stayed there, and moving one is a real job rather than a rename -- the paths are hardcoded in host tooling. Where that is the case the table above points at the app directory that owns the file, and the other copies of it are generated from there:

- `card_name_positions.py` is owned by `apps/setup/card_name_positions.py`.
- `identity_catalogue.py` is owned by `apps/setup/identity_catalogue.py`.

## The modules whose canonical copy is not in this export

These are owned by app trees that no longer ship -- archived predecessors of the apps that do. The shipping copies in this export are byte-identical to them (the gate above proves it), so nothing is missing: the file you are reading IS the source. The canonical path is named only so that a reader of the full repository knows which copy a human edits.

- `glyphskin.py` -- canonical at `identity/badge/identity/glyphskin.py` in the full repository, shipped into `nametag`, `setup`.
- `glyphskins.gpk` -- canonical at `identity/badge/identity/assets/glyphskins.gpk` in the full repository, shipped into `nametag`, `setup`.
- `identity_faces.py` -- canonical at `identity/badge/identity/identity_faces.py` in the full repository, shipped into `nametag`, `setup`.
- `identity_keyboard.py` -- canonical at `identity/badge/identity/identity_keyboard.py` in the full repository, shipped into `setup`.
- `identity_marks.py` -- canonical at `identity/badge/identity/identity_marks.py` in the full repository, shipped into `nametag`, `setup`.
- `kbqwerty_board.py` -- canonical at `kbqwerty/badge/kbqwerty/kbqwerty_board.py` in the full repository, shipped into `setup`.
- `skins.py` -- canonical at `namebadge/badge/namebadge/skins.py` in the full repository, shipped into `nametag`, `setup`.
- `stickers-36-p8.png` -- canonical at `namebadge/badge/namebadge/assets/stickers-36-p8.png` in the full repository, shipped into `nametag`, `setup`.

## What is in this directory

- `backdrop.py`
- `backlight.py`
- `effects.py`
- `game_palette.py`
- `idle.py`
- `kb_shell.py`
- `loading.py`
- `loading_sql.py`
- `nametag.py`
- `score_sink.py`
- `ui.py`
- `wallpaper.py`
