# Supabase Select 2026 badge software -- source export

This is the software that would ship to the ~800 SELECT badges today, as SOURCE, assembled by `scripts/export-source.py` from commit `353e1bfb6fd4` (worktree clean). It targets Badgeware **v3.0.2** on the **Pimoroni Tufty 2350**.

## Status

**This is a RELEASE CANDIDATE for Supabase Select 2026** (conference day: October 2, 2026, roughly 800 badges). Read it as software we intend to ship, and hold it to that standard. Three things a reviewer should know before forming an opinion:

- **Networking is intentionally disabled for launch.** The badge is offline-first and fully functional without it. `NETWORKING.md` is the whole story: what keeps the radio off, why, and what enabling it takes.
- **The exact fleet UF2 is an open ask.** We build against the public **v3.0.2** release; the exact image the fleet will be flashed with is still an open question (`BUILDING.md` has the pins and the caveat).
- **A first-article acceptance run is pending.** No unit flashed by the production process has been walked through the acceptance procedure yet; until one has, treat install-level claims as verified on dev hardware only.

## Quick start

From this export's root to a running badge, copy and paste. You need Python 3.8 or newer (stdlib only: no venv, no pip), a C toolchain for `make`, and a badge.

**Step 0, before any of this: check the badge's firmware.** This tree is built against Badgeware **v3.0.2** and its bytecode will not import on an older image. Flash first and install second, and use the plain `...-micropython.uf2` rather than the `-with-filesystem` one unless you want the badge reset to stock apps. **`BUILDING.md` section 0** has the check, the two flavours and what a mismatch looks like.

```sh
# 1. The Badgeware release clone: the stock launcher files and two fonts come from it.
#    BESIDE this tree, not inside it: the two clones are ~294 MB and every file
#    in here is hashed in MANIFEST.json.
git clone --branch v3.0.2 https://github.com/pimoroni/tufty2350 ../badgeware
BADGEWARE=$(cd ../badgeware && pwd)

# 2. mpy-cross, compiled once, from a SECOND clone: MicroPython, not the release.
git clone https://github.com/pimoroni/micropython.git ../micropython
git -C ../micropython checkout b29530abbd0550c8ab6963024aef36f3cd6cd278
make -C ../micropython/mpy-cross
MPY=$(cd ../micropython/mpy-cross/build && pwd)/mpy-cross

# 3. Compile the whole tree into build/system.
python3 tools/build.py --mpy-cross "$MPY" \
    --stock-menu  "$BADGEWARE/firmware/apps/menu" \
    --stock-fonts "$BADGEWARE/firmware/assets/fonts"

# 4. Disk Mode: double-tap the rear RESET button. Your own README names the disk
#    "Tufty2350"; we have also observed TUFTY, so read the name off the mount.
MOUNT=/media/$USER/Tufty2350      # Linux, or /run/media/$USER/Tufty2350
#MOUNT=/Volumes/Tufty2350         # macOS
#MOUNT=/media/$USER/TUFTY         # Linux, observed short name
#MOUNT=/Volumes/TUFTY             # macOS, observed short name

# 5. Clear the install roots first: copying over the top leaves stock apps and strays.
rm -r "$MOUNT/apps" "$MOUNT/assets"

# 6. Copy by root: manifest.json is the build's own proof file and must not install.
cp -R build/system/apps build/system/assets \
      build/system/main.py build/system/secrets.py "$MOUNT/"

# 7. The install's only proof: every file on the volume hashed against the build.
python3 tools/build.py --verify-mount "$MOUNT"

# 8. Eject cleanly, then open one app: an install is not a test.
umount "$MOUNT"                # Linux
#diskutil eject "$MOUNT"       # macOS: use this line instead
```

Step 2 is a different clone from step 1 and you need both: `mpy-cross` is built from MicroPython at the pinned commit, and the four stock launcher files and two stock `.af` faces come out of the Badgeware release. Every input above is either in this package or in one of those two clones.

**`BUILDING.md` section 4 is this same install, with the reasoning.** It is not a second procedure and there is no other one; if the two ever read differently, the exporter's `doc-claims-verified` gate has failed.

### Why this ships as bytecode, when Badgeware runs plain `.py`

It does, and that is the right development loop: your own README's "Installing Apps" is four steps, one of them "copy your app directory into apps", and source runs directly. Nothing here takes that away. Every module in this tree is the source, and dropping one onto a badge is a valid way to run it.

We precompile the thing we hand you for three measured reasons:

1. **Headroom.** The modules here are 3,532,949 B as source and 805,913 B as bytecode, 23%. With assets, the installed tree is 6,322,611 B, 50% of the 12 MB volume; as source it would be 9,049,647 B, 72%. Both fit today. The assets are what grows, so the compile is what keeps the artwork budget rather than the code budget the binding constraint.
2. **First-open latency, which is the one a wearer feels.** MicroPython compiles each `.py` at import, as one uninterruptible native call per module, and every app exit resets the badge, so every open is a cold open. The largest module here is 666,336 B of source; even precompiled to a 228,847 B `.mpy`, its cold import measures 630-765 ms on device. Shipping source adds the parse to that, on every open.
3. **Fleet integrity.** 800 badges get a byte-identical, hash-verified install, and a stray `.py` beside its own `.mpy` silently wins: no speed-up, possibly stale code, no error. That is the failure `tools/build.py --verify-mount` exists to catch.

`BUILDING.md` section 2.5 is the full treatment, including how to mix the two safely.

Full detail, pins, and troubleshooting: **`BUILDING.md`**. It carries the pins with their one open caveat, `--check` (build twice, prove byte-identical output), a build without the release clone (`--skip-menu`, `--no-stock-fonts`), firmware flashing, and the refusals the build will not budge on.

It is not a repository dump and it is not a release. It is the boot file, the launcher, 8 apps, the shared layer they all vendor, the assets they read, and the toolchain that compiles and installs them: **202 files, 9,524,292 bytes**.

Those two numbers are the PAYLOAD: everything in this tree except this README and `MANIFEST.json`, the two files that cannot quote a total including themselves without changing it. `MANIFEST.json` lists 203 rows (the payload plus this README) and does not hash itself; its `totals.payload` repeats the two numbers above, and the exporter's `readme-matches-manifest` gate reads this paragraph back and fails the build if any of the three disagrees.

## Start here

| | |
|---|---|
| **`ARCHITECTURE.md`** | how it is put together and why, including where we would value your eyes |
| **`BUILDING.md`** | source to bytecode to badge: two commands and a file copy |
| **`NETWORKING.md`** | why the fleet ships with networking off, and what enabling it takes |
| `AGENTS.md` | orientation and hard constraints for an AI agent reviewing or modifying this tree |
| `apps/<app>/README.md` | one short page per app: what it does, its controls, the non-obvious bits |
| `shared/README.md` | why every app carries its own copy of the shared layer |
| `MANIFEST.json` | every file, its SHA-256, the tree hash, and the gate results |

**We are asking you to review this, not only to run it.** The last section of `ARCHITECTURE.md` names the specific things we think we may have wrong.

## The lineup

The order is the launcher's grid order and it comes from `apps-roster.json`, **which is in this export** -- the same file this exporter and the bytecode exporter read, so the two artifacts cannot describe different badges. `tools/build.py` reads it too and REFUSES any directory under `apps/` the roster does not name, so a stray lab directory cannot become a shipping app by being copied in. The copy here carries the contract (the lineup, the descriptions, the asset profiles, the `/system/lib` decision, one compacted line per excluded app); the decision history behind each entry stays in the repository.

| app | installs at | what it is |
|---|---|---|
| `badgecard` | `/system/apps/badgecard` | the badge editor and the worn badge itself: name, skin, stickers, effect |
| `poster` | `/system/apps/poster` | the worn badge as a read-only full-screen poster, opened in 14 modules instead of 27 |
| `schedule` | `/system/apps/schedule` | the offline conference agenda: two stage tabs, fourteen sessions, no network |
| `snake` | `/system/apps/snake` | Snake on an 8 px grid where the food is the Supabase mark; nine levels trade pace for payout |
| `flappy` | `/system/apps/flappy` | tap-to-fly where you are a client connection and the pipes are a pooler's slots |
| `pet` | `/system/apps/pet` | virtual-pet care sim where the creature is your database project |
| `glyph` | `/system/apps/glyph` | a player for 36 recorded cell-stream animations, with the rear case lights in sync |
| `settings` | `/system/apps/settings` | pairing, the network switch, optional updates, screen brightness, and the badge's only route to off |
| `menu` | `/system/apps/menu` | the boot host: the app grid, the hold shortcut, the loading screen and the idle ladder |

Each app directory carries its own short `README.md`: what it does, its controls, and anything a reader would not guess.

## The architecture, in ten sentences

1. The launcher owns the home screen: it is the boot host, it draws the app grid, and it is the only thing that runs when nothing else does.
2. Every app is a directory under `/system/apps/`, and the badge puts exactly one path on `sys.path` -- that app's own directory -- so an app is a closed world with no shared import path.
3. That is why `shared/` exists here but not on the badge: `scripts/sync_ui.py` copies each canonical module into every app that needs it, and a `--check` mode proves the copies are byte-identical rather than trusting anyone to remember.
4. Every app exit is a `machine.reset`, so an app never has to unwind its own state, and the launcher is always entered on a known-good heap.
5. `shared/` is the common layer: `ui` (chrome, lists, softkeys, the repeat curve), `effects` (the present-time filters), `idle` (the inactivity clock), `backlight` (the one home of every brightness number), plus `poster`, `backdrop`, `wallpaper` and `loading`.
6. The identity surfaces run HIRES, 320x240 at 1:1, because a name and a QR code are read rather than played; the games run LORES, 160x120, because a game frame has a budget and the panel cost is where it goes.
7. The panel is chosen exactly once per app, in its entry seam, and nothing downstream names a mode: `ui.Chrome` reads `screen.width`, the glyph skin reads the cell geometry, the mark sheet reads `chrome.scale`.
8. A first-wake ceremony runs on RESET only, so the badge introduces itself once when it is switched on and never interrupts a wearer who is using it.
9. Idle is a ladder rather than a sleep: the panel dims after a period without input and the badge opens itself after a longer one, and the press that un-dims the screen is consumed so a wearer's wake-up tap cannot also press a button.
10. Nothing in this tree talks to a network.

`ARCHITECTURE.md` is that page at length: the boot chain, the app lifecycle, the shared layer, the resolution split, memory discipline, and why the code that looks over-engineered is over-engineered.

## Building it

The Quick start at the top of this page is the whole path in one block. Two things it does not spell out:

- **`--mpy-cross` is not optional in practice.** The script does not search `PATH`. It checks the flag, then the `MPY_CROSS` environment variable, then one cached default path, and if none of the three resolves it stops with the `make` line you need.
- **`--check` does not populate `build/system`.** It compiles the tree twice into temporary directories, hashes both and asserts they are byte-identical, then deletes them. So proving the build reproducible and producing the tree you install are two separate commands.

`BUILDING.md` is the whole procedure: the exact pins (release tag and commit, UF2 filename and SHA-256, the MicroPython branch/commit that builds `mpy-cross`, the picovector commit, the mpy format, and the two stock font hashes), the refusals the build will not budge on, the Disk Mode install and the byte-verify. Three inputs are yours rather than ours, because the pinned release publishes no licence grant for them: four files of the stock launcher (`apps/menu/README.md` names them with their pinned hashes, `apps/menu/PATCHES.json` is the machine-appliable patch register) and the two stock `.af` faces (`assets/fonts/README.md`). All three come out of a **v3.0.2** release clone and all three are hash-gated.

## How this tree maps onto the badge

Disk Mode mounts logical `/system` at the volume root, so the mapping is direct and there is nothing to interpret:

```
<export>/main.py              ->  /system/main.py
<export>/apps/<app>/          ->  /system/apps/<app>/
<export>/apps/menu/           ->  /system/apps/menu/   (the launcher)
<export>/assets/fonts/        ->  /system/assets/fonts/
```

What in this tree is **export-only** and does not install:

- every `README.md` (including this one), `AGENTS.md`, `NETWORKING.md`, `ARCHITECTURE.md`, `BUILDING.md`;
- `MANIFEST.json`, `apps-roster.json` and `apps/menu/PATCHES.json`;
- `.gitignore` and `CONTRIBUTING.md` -- furniture for the published source repository this tree is mirrored into;
- `shared/` -- the canonical copies, explained in `shared/README.md`;
- `tools/build.py` -- the compiler front end;
- `apps/poster/tests/` -- one host suite, shipped as a worked example.

`apps/snake/PROVENANCE.md` and `apps/flappy/PROVENANCE.md` -- the attribution records for the two apps derived from somebody else's work -- **do** install, and that is deliberate: a licence notice that stays behind on the build host is not a licence notice. They are in `build/system` and on a verified volume.

What installs is bytecode, not source: the badge parses and compiles every `.py` it imports as one uninterruptible native call per module, so nothing of ours can paint the panel while that runs. `tools/build.py` here does the compile; `scripts/export-handover.py` in the full repository does the same thing for the release pipeline and emits a SHA-256 manifest with it.

### `main.py` is the badge's, patched twice

`main.py` here is byte-for-byte what a finished badge boots. It starts as Pimoroni's own hash-pinned main and takes two patches:

1. the Poster hold handoff -- the factory main drains held buttons before launching an app, which makes an app selected AT a long-press threshold visibly wait for key-up; `poster` is the one app selected that way and the one app whose update consumes press edges only, so it is the single named exception and every other app keeps the factory drain;
2. the BadgeLink block -- a `sys.path.append("/system/lib")` and a `try/except` that installs a network runtime.

Everything else in that file is yours, including a comment above the `launch()` call about temporarily auto-launching the `world` app for rasteriser testing. It is stock, it is inherited, and it does not describe this tree. We left it rather than take a third patch on a file we are trying to patch less.

**The BadgeLink block is in this export on purpose, and it is dead code here.** `/system/lib` is not part of this tree, so the guarded import fails, the handler prints `BADGELINK_NETWORK boot=offline error=ImportError` and the badge boots clean into the launcher. Stripping the block would have made the export disagree with the badge about its own boot file, which is a worse thing for a reader than a guarded import they can see.

## The shared layer, and why every app has its own copy of it

The badge puts exactly one directory on `sys.path`: the app's own. An app *can* import from another app's directory, but then it refuses to start unless that other app happens to be installed -- a bad trade on a badge whose HOME key can launch anything in any order. So the copies are forced, and what is not forced is keeping them in sync by hand: `scripts/sync_ui.py` owns one table of canonical sources and their consumers, and `--check` hashes every copy on every CI run.

`shared/` in this export holds the 12 canonical modules the shipping lineup vendors. `shared/README.md` is the whole map, including the 9 modules whose canonical copy is not a `shared/` file.

## What a wearer experiences

- **Switch on.** The badge resets, `main.py` runs, the launcher draws the home screen, and the first-wake ceremony plays -- once, on RESET only.
- **Pick something.** The grid scrolls with UP/DOWN; B opens the highlighted app. Holding B for about a second and a half opens `poster` from anywhere on the grid, which is the wearer's "show my badge" gesture.
- **Leave.** HOME leaves any app. Because every exit is a hard reset, the home screen is always entered clean.
- **Do nothing.** The panel dims after a short period without input, and after a longer one the badge opens itself to its identity surface, which is the state it should be in while it hangs on a lanyard. The press that wakes the panel back up is consumed: a wearer tapping to see the screen does not also press a button in whatever app is open.
- **Run out of battery.** Nothing is lost that was saved; every app that persists anything writes to the badge's own `/state` volume.

## What is deliberately NOT here

- **The network runtime.** BadgeLink -- the `/system/lib` payload, its transport, its pairing and its realtime client -- is not in this tree. It is written and it works; it is dark until it earns its way in, and the software above is built so that its absence costs exactly the features that need it and nothing else. The one visible seam is the Settings tile's pairing view, which guards its three imports and says so when they are missing.
- **The research repository.** Benchmarks, device probes, measurement reports, design records, the skin lab, the glyph labs, the keyboard bench and every `evidence/` directory stay behind. The numbers quoted in the comments in this source come from those reports; the reports themselves are a much larger body of work than the software.
- **Host tooling.** Every `*/host/` tree: the catalogue generators, the asset bakers, the `mpy-cross` build, the browser playground and the deploy scripts.
- **The test suites**, with one exception. The shipping apps carry 107 host test modules totalling roughly 55,000 lines -- a codebase larger than the software it tests, and not the thing to read first. `apps/poster/tests/` ships as the worked example: it is the smallest suite in the repository, and it pins the two invariants this README claims out loud (the staged arrival, and the panel resolution being decided in exactly one place). **It runs from this tree, and the exporter proves it:** the `included-tests-run` gate executes `python3 -m unittest discover -s apps/poster/tests -v` from the export root on every build and refuses on any error or failure. A few of its cases pin the app against trees this export omits -- the archived editor it replaced, and `scripts/sync_ui.py` -- and those SKIP from here, with the reason printed. The gate counts the skips so an all-skip suite could not pass as green.
- **Two of the three fonts, which YOU already have.** `DynaPuff-Medium.af` and `IndieFlower-Regular.af` are Pimoroni's own, shipped in the Badgeware **v3.0.2** release, and the pinned release publishes no licence grant, so they are in neither this export nor the repository. **They still ship on the badge** -- this tree replaces `/system` wholesale, so dropping either is a removal rather than an omission. You supply them from your own release clone:

  ```sh
  python3 tools/build.py --stock-fonts <badgeware>/firmware/assets/fonts ...
  ```

  The build verifies both against pinned SHA-256s before copying them and refuses the build without them unless you pass `--no-stock-fonts` and accept a `/system` that regresses a stock badge. `BUILDING.md` §2 has the hashes and `assets/fonts/README.md` has the whole story. `assets/fonts/` here holds the one face this project owns: MonaSans-Medium.af, an OFL rebuild of github:github/mona-sans 2.0.8.
- **The stock launcher base.** Four files of Pimoroni's own menu app are patched rather than replaced; `apps/menu/README.md` names them, their pinned hashes and the five patches.
- **Apps that were built and are not shipping.** `MANIFEST.json` records 24 excluded app directories, each with the reason `apps-roster.json` gives for it -- archived predecessors, dev labs, comparison tiles and instruments. The roster's own list carries 26 reasons: the extra 2 are for directories the app registry no longer names. They are in the repository, not in this export.
- **Secrets, of any kind.** There is no `secrets.py` in this tree, no network credential, no private address and no `/state` content, and the exporter fails loudly rather than emitting one -- see its `gate_secrets`.

## Verifying this export

One command, and it runs from this package with no compiler, no clones and no network:

```sh
python3 tools/build.py --verify-manifest
```

It hashes every file here against `MANIFEST.json` and recomputes the `tree_hash`, reporting missing files, wrong bytes and files the manifest does not name. It skips `build/`, `__pycache__/` and `.git/` when it walks the tree. The first two are what the build and the shipped test suite write, and are in `.gitignore` for the same reason; `.git/` is this repository's own metadata, present in every clone and never a manifest row, so a FRESH `git clone` of this repository verifies clean. (git cannot ignore its own metadata directory, which is why `.git/` is skipped in the walk rather than named in `.gitignore`.)

**The `tree_hash` formula, so you do not have to take our word for it.** SHA-256 over the concatenation of `<path>\0<sha256>\n` for every row in `MANIFEST.json`, rows sorted by path:

```sh
python3 -c "import hashlib,json;r=sorted(json.load(open('MANIFEST.json'))['files'],key=lambda x:x['path']);print(hashlib.sha256(''.join('%s\0%s\n'%(f['path'],f['sha256']) for f in r).encode()).hexdigest())"
```

Both prove this tree is self-consistent; neither proves it is ours. The canonical commit is in `MANIFEST.json`'s `provenance` and in this document's header, and the exporter that assembled the tree lives in that repository, not in this one. The export is deterministic by construction -- sorted walks, `copyfile` so no host metadata rides along, and no wall-clock timestamp in any generated file -- so two runs from one commit produce the same `tree_hash`, which the exporter's own `--check` asserts in the full repository.

21 gates run on every build and there is no warning tier, because a warning in a build log is how something ships. Their results are in `MANIFEST.json`. The one that matters most is the first: no credential, no private address, no `/state` content, no `secrets.py`. The one most likely to catch a real mistake is `imports-resolve`, which proves every import in every app either lands inside that app's own directory, is a firmware module, or sits inside a `try/except ImportError` -- because the badge puts exactly one path on `sys.path` and this export drops `/system/lib` on purpose. The ones that exist because an outside engineer read an earlier cut of this package and found them missing are `included-tests-run` (execute the shipped suite from the artifact), `readme-matches-manifest` (this document's counts against the manifest's), `building-md-pins` (every pin in `BUILDING.md` against the file in our repository that owns it), `roster-ships-and-matches`, `provenance-records-present` and `no-device-identifiers`. Two more came from a second reading of the package after those landed: `hold-contract-consistent`, which reads the launcher's `HOLD_MS` out of this export and refuses any sentence anywhere in it that names a different hold duration (a stale one survived a fix because the string was split across two source lines), and `internal-exhaust-census`, which counts the internal residue still in this source -- validation-row identifiers, quoted decisions, paths into reports you do not have -- in every text file and in the manifest. Its per-file counts go to a maintainer report kept outside this package, because that ledger is our cleanup homework, not yours. It is REPORT-ONLY except for the class that already refused (a bench badge's serial number), because what to remove and what to keep is a judgement rather than a rule.
