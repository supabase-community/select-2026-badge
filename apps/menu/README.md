# menu -- the boot host: the app grid, the hold shortcut, the loading screen and the idle ladder

The badge's home screen and its boot owner. `/system/main.py` launches this directory, and whatever path it returns is the app that opens. App discovery, grid navigation and the launch contract are the pinned Badgeware implementation; the visual layer, the commit gesture, the loading screen, the idle clock and the filter shuffle are project-owned. It persists nothing itself, but reads two of `badgecard`'s outputs: `/state/wallpaper.pgw` for the background and `/state/badgecard.json` for the wearer's brightness.

**Controls.** A/C move the cursor left and right within the current row of three only. UP/DOWN move a whole row. B launches the highlighted app **on release, not on the press edge** -- it has to be, because the press edge is what the hold gesture needs. Holding any of A/B/C/UP/DOWN for 1500 ms opens `poster` from anywhere on the grid: nothing is drawn for the first 250 ms (without that dead zone every navigation press would flash a bar), then a 3 px bar grows centre-out and the four rear case lights ramp with it. A poll gap over 250 ms resets the gesture fail-closed. HOME resets, which boots straight back here.

**Non-obvious.** The grid runs at the firmware's own default, LORES 160x120 -- the only unit here that is not HIRES. The one place a mode is named is the first-wake ceremony: `first_wake.py` calls `badge.mode` at 3 sites (read the entry mode, take the panel to `RIPPLE_MODE`, give the entry mode back from a `finally`), and it is the documented exception to the rule in `ARCHITECTURE.md` section 4. Leaving the launcher is not a reset, only a returned path, so its last frame sits on the panel while the app imports; going home *is* a reset, which is why the panel goes black on the way back and why this is the one screen that needs a loading screen. It is also the one app whose failure needs a USB cable to recover, since a raise here resets into the same failing code -- so `loading` and `first_wake` are guarded imports and the commit path is wrapped end to end (they are two of the guarded import sites `AGENTS.md` enumerates in full, not the only two). The grid order comes from `order.txt` beside the launcher: listed apps in roster order, then everything else alphabetically, and a badge with no `order.txt` is a valid stock install that boots alphabetical.

## This directory is incomplete on purpose

The launcher is not written from scratch. It is **Pimoroni's own menu app, patched** -- and their four files are not in this export or in this project's repository, because the pinned Badgeware release publishes no licence grant for its source. What ships here is only what this project wrote.

The build resolves the base out of a Badgeware release clone and refuses to proceed unless these four files hash exactly:

| stock file | pinned SHA-256 |
|---|---|
| `__init__.py` | `cc7fa620daec9f1a3afa32eb1e6bec98577287f5722f51f342d1563e5cffabb2` |
| `app.py` | `c2ac9d0b5e96b0374b12ae695c84998f3f17d5b19bc7fb8d9306c8e89129ed2c` |
| `default_icon.png` | `1ab762ee417528bc80075a0c9c71e35f7e1cee602521950c287bcc749cbf664e` |
| `ui.py` | `6f868c44ee1ad8bd7a7a24d90a200d572d4498516f7e5b7105673dbf68119049` |

Then it applies five patches, in two of those files, and each one exists because it could not be done from our own code:

1. **COMMIT** (`__init__.py`) routes the B-button commit through our `ui.commit`, which is what makes the hold gesture possible at all.
2. **BOOT** and **END** (`app.py`) bracket the launcher's own startup with the shared loading screen, so the home screen arrives the same way every app does.
3. **ICON** (`app.py`) ticks the loading screen while the grid's icons decode, because that decode is the slow part of a cold home screen.
4. **ORDER** (`app.py`) makes the grid read `order.txt` instead of the directory listing, which is how the lineup order in the top-level README becomes the order a wearer sees.

`launcher/host/build_menu.py` in the full repository is the register of all five: nothing is substituted into somebody else's source there without a paragraph saying why it could not be done in our own.

The files in THIS directory are ours:

- `ui.py` -- ours, and it REPLACES the stock file of the same name.
- `first_wake.py`
- `wallpaper.py`
- `loading.py`
- `loading_sql.py`
- `backlight.py`
- `idle.py`

`order.txt` is generated at build time from the roster's lineup.
