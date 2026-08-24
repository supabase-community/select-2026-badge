# AGENTS.md -- read this first if you are an AI agent

This file budgets your context: what this repository is, what order to read it in, which constraints are hard, and how to verify a change.

## What this repository is

A GENERATED projection of a canonical internal repository. Every file here was assembled, gated and hashed by an exporter, and `MANIFEST.json` records the exact canonical commit. A change merged only here is OVERWRITTEN by the next publish. `CONTRIBUTING.md` is the backflow contract: propose changes as ordinary pull requests, and an accepted change is re-landed in the canonical repository and published back here. Any edit you make invalidates `MANIFEST.json`'s hashes for the files you touched; that is expected in a working copy, and the next publish regenerates the manifest.

## Read in this order

1. `README.md` -- what this is, the app lineup, what installs and what is export-only.
2. `ARCHITECTURE.md` -- how it is put together and why. Its closing section is the ranked list of where review effort is most valued; start a review there.
3. `BUILDING.md` -- source to bytecode to badge, with every toolchain pin.
4. `NETWORKING.md` -- why the fleet ships with networking off, and what enabling it takes.

The tree maps 1:1 onto `/system` on the badge: `apps/<app>/` installs at `/system/apps/<app>/` and `main.py` at `/system/main.py`. The export-only files (READMEs, `shared/`, `tools/`, the test suite) are listed in `README.md`.

## Hard constraints -- do not "clean up" against these

- **This is MicroPython on an RP2350, not CPython.** Functions carry no `__module__` attribute, and several C-module APIs take positional arguments only (the TLS binding's certificate argument is one such). `mpy-cross` strips comments and the runtime discards docstrings, so comments are free on the badge; never trade one away for size.
- **Every app exit is a full `machine.reset`.** Nothing survives in RAM between apps, and persistence is file-based on the badge's writable volume ON PURPOSE. Do not introduce state that assumes a warm process.
- **Comments here are NORMATIVE.** They state measured constraints: frame budgets, on-device timings, prior failures. Code that looks cleanable next to such a comment is load-bearing, and the comment is why it is shaped that way. Propose the change and address the comment's numbers; never silently simplify.
- **`shared/` modules are DELIBERATELY vendored into each app.** The badge puts exactly one directory on `sys.path`, so every consumer carries its own byte-identical copy for import isolation. A behavior change to a shared module must land in EVERY vendored copy or the copies silently diverge: `MANIFEST.json`'s `vendored_modules` table records every copy, and the exporter's `vendored-copies-identical` gate refuses drift.
- **HIRES apps are the identity surfaces; LORES apps are the games.** 320x240 for things that are read, 160x120 for things that are played. The split is a product ruling backed by measurement (the games' frame budgets were measured at 160x120 and do not survive conversion), not an accident. Do not convert an app in either direction.
- **Secrets are provisioning, not source.** A finished badge is provisioned with a separate secrets file; the build output carries an EMPTY template of it, and this tree deliberately carries none (the exporter refuses one by name). Never commit a populated credential value anywhere in this tree.

## Build and verify

```sh
python3 tools/build.py --verify-manifest               # are these the published bytes
python3 tools/build.py --list                          # what would compile
python3 tools/build.py --mpy-cross <path> ...          # compile; pins in BUILDING.md
python3 tools/build.py --check --mpy-cross <path> ...  # prove it reproducible
python3 tools/build.py --verify-mount <MOUNT>          # prove an install
```

`tools/build.py` reads `apps-roster.json` and refuses any directory under `apps/` the roster does not name. The firmware, compiler and font pins are in `BUILDING.md`, and the build refuses on all of them. There is no default `mpy-cross` path: pass `--mpy-cross` or set `MPY_CROSS`, so every machine resolves the same compiler or none.

Run the included test suite from this tree:

```sh
python3 -m unittest discover -s apps/poster/tests -v
```

It passes from this layout; a few cases skip with a printed reason because they pin against trees this export deliberately omits. The suite is the worked example of how everything else is verified; the full suites live in the canonical repository.

**Running it writes `__pycache__/` directories, and they are not in `MANIFEST.json`.** That is CPython caching bytecode beside the source, not drift: they are in `.gitignore`, `tools/build.py` skips them when it compiles, and `--verify-manifest` skips them when it hashes. `git clean -xfd` removes them if you want the tree back to the published file list exactly.

## The guarded imports, in full

**38 import sites across 18 files** are wrapped in a `try` that catches `ImportError`, and this list is generated from an AST walk of the tree you are holding rather than maintained by hand. `ARCHITECTURE.md` section 2 quotes these two numbers and the exporter's `doc-claims-verified` gate refuses a build where they disagree.

A guarded import is how this tree survives its own omissions: the badge puts exactly one directory on `sys.path`, `/system/lib` is not in this export, and the launcher is the app whose failure needs a USB cable. An import moved OUT of one of these guards is a reset at launch, not a tidy-up.

| file | line | imports |
|---|---:|---|
| `apps/badgecard/loading.py` | 147 | `os` |
| `apps/badgecard/loading.py` | 306 | `loading_sql` |
| `apps/badgecard/poster.py` | 89 | `backdrop` |
| `apps/flappy/loading.py` | 147 | `os` |
| `apps/flappy/loading.py` | 306 | `loading_sql` |
| `apps/glyph/__init__.py` | 82 | `glyph_variant` |
| `apps/glyph/__init__.py` | 363 | `os` |
| `apps/glyph/__init__.py` | 628 | `os` |
| `apps/glyph/loading.py` | 147 | `os` |
| `apps/glyph/loading.py` | 306 | `loading_sql` |
| `apps/menu/first_wake.py` | 867 | `glyph_render` |
| `apps/menu/first_wake.py` | 868 | `glyph_stream` |
| `apps/menu/first_wake.py` | 885 | `glyph_rich_lights` |
| `apps/menu/first_wake.py` | 886 | `light_calibration_2x` |
| `apps/menu/first_wake.py` | 887 | `wave_lights` |
| `apps/menu/first_wake.py` | 1199 | `os` |
| `apps/menu/loading.py` | 147 | `os` |
| `apps/menu/loading.py` | 306 | `loading_sql` |
| `apps/menu/ui.py` | 81 | `first_wake` |
| `apps/menu/ui.py` | 171 | `loading` |
| `apps/menu/ui.py` | 514 | `json` |
| `apps/pet/loading.py` | 147 | `os` |
| `apps/pet/loading.py` | 306 | `loading_sql` |
| `apps/poster/poster.py` | 89 | `backdrop` |
| `apps/schedule/loading.py` | 147 | `os` |
| `apps/schedule/loading.py` | 306 | `loading_sql` |
| `apps/settings/__init__.py` | 87 | `pairstate` |
| `apps/settings/__init__.py` | 88 | `pairview` |
| `apps/settings/__init__.py` | 89 | `store` |
| `apps/settings/settings_view.py` | 95 | `qrcode` |
| `apps/snake/loading.py` | 147 | `os` |
| `apps/snake/loading.py` | 306 | `loading_sql` |
| `apps/snake/snake_profile.py` | 27 | `__import__(<dynamic>)` |
| `main.py` | 5 | `network_runtime` |
| `main.py` | 11 | `from realtime.client import BACKOFF_RESET_ON_FIRST_JOIN, RealtimeClient` |
| `shared/loading.py` | 147 | `os` |
| `shared/loading.py` | 306 | `loading_sql` |
| `shared/poster.py` | 89 | `backdrop` |
