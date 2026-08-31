# Building and installing

Source to bytecode to badge, with nothing missing. Two commands and a file copy.

Everything here assumes you are inside this export directory.

**Current production contract.** The visible launcher tiles are exactly `setup`, `nametag`, `schedule`, `snake`, `flappy`, `settings`, in that order. Those six plus hidden `menu` and no-entry-point `glyph` are the complete eight `/system/apps` roots. `glyph` is a pruned support payload used only by the launcher's first-wake ceremony; Setup and Nametag carry their own glyph packs. BadgeLink is not an app root: its complete networking, broadcast, schedule and score runtime ships under `/system/lib`. In the source repository, the `device` roster is for development review and is never a final or golden install target; this export's `apps-roster.json` is the flattened production contract.

---

## 0. The firmware on the badge, before anything else

**Check the firmware first and flash it if it is wrong.** This tree's bytecode is built for Badgeware **v3.0.2**; on an older image the apps do not start. Firmware first, apps second, always: section 0.2 has a flavour of image that erases every app on the badge, so doing it in the other order throws the install away.

### 0.1 How to check, honestly

**There is no Badgeware version string readable on the badge, as far as we can find.** Your CI writes `board/version.py` at build time (`ci/micropython.sh`, `ci_genversion`), it is not committed, and `board/manifest.py` freezes `../modules/python/` and `../modules/common/` and not `board/`, so it does not reach the image. No stock app reports a version either. **If we have missed a way, tell us and this section becomes one line.**

What you CAN read is the MicroPython build underneath it, over serial. This is the one step in the whole document that needs `mpremote` (`pip install mpremote`), and it is needed for nothing else:

```sh
mpremote exec "import os, sys; print(os.uname()); print(sys.implementation._mpy)"
```

Two things come back and each answers a different question:

- **`os.uname()`** names the MicroPython branch and the build date. On our v3.0.1 reference badge it read `release='1.29.0-preview'`, `version='bw-1.28.0-3, on 2026-08-08 (GNU 13.3.1 MinSizeRel)'`, `machine='Pimoroni Tufty 2350 with RP2350'`. The build date is the closest thing to an identifying stamp on the device; it does not name a `v3.0.x` tag.
- **`sys.implementation._mpy`** is the number that actually decides whether this build's bytecode imports. On a **v3.0.2** badge it reads **7942**. Anything else and the apps will not start, whatever the uname says.

**If you cannot establish what is on a badge, flash it.** That is cheaper than inferring, and it is the only answer we would trust on an unknown unit.

### 0.2 How to flash, and the flavour that erases the badge

Your README's "Updating/Reflashing Firmware" is the procedure: hold **BOOT** on the far left, briefly tap **RESET** to its right, and a disk named **`RP2350`** appears. Drag the `.uf2` onto it. The disk vanishing mid-copy is the flash succeeding and the badge rebooting.

**⚠️ TWO FLAVOURS, AND ONLY ONE OF THEM IS SAFE AFTER AN INSTALL.**

| image | what it does | when to use it |
|---|---|---|
| `tufty-vX.X.X-micropython-with-filesystem.uf2` | replaces the firmware **and resets every app to stock** | a fresh or unknown badge, **before** installing this tree |
| `tufty-vX.X.X-micropython.uf2` | replaces the firmware only; installed apps survive | everything else, including re-flashing a badge that already carries this build |

**The order rule, in one line: firmware first, apps second.** Flashing the `-with-filesystem` image after installing this tree erases the install, and the badge boots the stock lineup with no error to tell you why.

Images are on the releases page: <https://github.com/pimoroni/tufty2350/releases/latest>. After any flash, reinstall the apps (section 4) so the bytecode provably matches the firmware.

### 0.3 What a version mismatch looks like

A `.mpy` whose format version disagrees with the firmware raises `ValueError: incompatible .mpy file` at import. An import that raises inside `badgeware.launch()` is a traceback modal and a reset, so the symptom is a badge that reboots into the launcher every time you open one of these apps rather than an app that fails quietly. Section 1.1 is the build-side gate that stops us shipping bytecode in the wrong format in the first place.

**One caveat that is ours to state, not yours to answer:** `v3.0.2` names the public release asset, and section 1.2 explains why that is weaker than it looks. Two images tagged `v3.0.2` need not be byte-identical, and the exact UF2 the ~1,000 units will be flashed with is an open request rather than something we are withholding.

---

## 1. What you need

| | |
|---|---|
| **Python 3** | 3.8 or newer. The build script is stdlib-only and shells out to nothing but the compiler in the next row: no venv, no pip, no `diff`, so it runs on a stock Windows Python. |
| **`mpy-cross`** | Built from the MicroPython clone in §1.2. `make -C <micropython>/mpy-cross` |
| **A Badgeware release clone** | Two build inputs come out of it and neither is in this package: the four stock launcher files (§3) and the two stock `.af` faces (§2.3). |
| **The firmware** | Badgeware **v3.0.2** for the Tufty 2350, from <https://github.com/pimoroni/tufty2350>. Use the firmware-ONLY image so `/system` survives a flash. |
| **A badge** | Or a mounted volume that looks like one. |

### 1.1 The mpy format pin, which is the one that can hurt you

Badgeware v3.0.2 loads **mpy v6.x**; the build reads what your `mpy-cross` actually emits and refuses if the major version disagrees, because a format mismatch raises `ValueError: incompatible .mpy file` at import, and an import that raises inside `badgeware.launch()` is a modal and a reset on every unit.

Our compiler reports `mpy-cross emitting mpy v6.3`, and the firmware it was built beside declares `MPY_VERSION 6` / `MPY_SUB_VERSION 3` (`py/persistentcode.h`). On a badge, `sys.implementation._mpy` reads **7942**.

The build does **not** compare the sub-version (v6.**3** against v6.**2**), deliberately: the loader only checks it when the arch byte is non-zero, i.e. for native or viper code, and nothing in this product emits either. Comparing it would reject builds that work.

### 1.2 The pins, and one of them is honestly an open question

These are the exact identifiers this source was built and measured against. The exporter parses every one of them out of the file in our repository that owns it and refuses to emit this page if it stops naming them, so this table cannot drift from the tree it describes.

| what | pin |
|---|---|
| Badgeware release tag | `v3.0.2` |
| Badgeware release commit | `c4abbcd32fef7aa12985635d68daed967b04f594` |
| Public UF2 | `tufty-v3.0.2-micropython.uf2` |
| Public UF2 SHA-256 | `9fffbd7126904dadc0578c698b8bc07fd9f741baebe164efa1ef94ae5c21c85e` |
| MicroPython repo | `https://github.com/pimoroni/micropython.git` |
| MicroPython branch | `bw-1.28.0-3` |
| MicroPython commit (this is what builds `mpy-cross`) | `b29530abbd0550c8ab6963024aef36f3cd6cd278` |
| picovector commit | `a3959e5de8f261af43dad4b3c2668372897d522f` |
| mpy format emitted | `v6.3` |

```sh
git clone https://github.com/pimoroni/micropython.git ../micropython
git -C ../micropython checkout b29530abbd0550c8ab6963024aef36f3cd6cd278
make -C ../micropython/mpy-cross
```

**⚠️ THE ONE PIN WE CANNOT GIVE YOU IS THE ONE YOU OWN.** `v3.0.2` names the PUBLIC RELEASE asset and that is deliberately weaker than it looks: your CI builds picovector from a floating `main`, so two images tagged v3.0.2 need not be byte-identical. **We do not know the exact UF2 the ~1,000 units will be flashed with, and asking for it is an open request rather than something we are withholding.** Until it is answered, "this tree targets v3.0.2" means the public tag, and a first-article check against a production-flashed unit is the only thing that closes the gap. If you can name the image, we will pin to it and this table gains a row.

---

## 2. Compile

```sh
# `mpy-cross` is NOT found through PATH. Name it explicitly, or export MPY_CROSS.
MPY=<micropython>/mpy-cross/build/mpy-cross

python3 tools/build.py --list                        # what would be compiled
python3 tools/build.py --mpy-cross "$MPY" \
    --stock-menu  <badgeware>/firmware/apps/menu \
    --stock-fonts <badgeware>/firmware/assets/fonts  # the whole tree
python3 tools/build.py --mpy-cross "$MPY" --skip-menu --no-stock-fonts
python3 tools/build.py --check --mpy-cross "$MPY" \
    --stock-menu <badgeware>/firmware/apps/menu \
    --stock-fonts <badgeware>/firmware/assets/fonts  # prove it reproducible
```

**`--mpy-cross` is the flag a first-time reader stops without, so it is in every line above.** The script does not search `PATH` and has no default: it checks the explicit flag, then the `MPY_CROSS` environment variable, and if neither resolves it stops and prints the `make` line from §1.2. That is deliberate -- a fallback path would let one machine build with a compiler nobody named while every other machine gets the error.

Output lands in `build/system/`, shaped exactly like the badge's `/system`.

**`--check` does NOT populate `build/system`.** It compiles the whole tree twice into temporary directories, hashes both, and asserts byte-identical output, then deletes them. So it is two commands rather than one: a normal build creates the install tree, and a separate `--check` proves the build reproducible. Run it before any install you intend to verify, because an install proves itself by SHA-256 equality and bytecode breaks that claim unless the build is reproducible. The comparison is a pure-Python hash walk, so no `diff` executable is needed.

### 2.1 What compiles: the production roster, not the directory listing

`tools/build.py` reads the flattened `apps-roster.json` at the export root. It compiles the six names in `apps` in grid order, assembles the hidden `launcher`, and applies each `payload_only` keep list without adding an entry point. The exporter derives those keys from the source repository's `production.apps`, hidden menu and `production.payload_only`; the development `device` list never enters this file. **A directory under `apps/` that the production contract does not carry is a refusal, not an app.** That matters more than it sounds: without it, a lab tile or a half-finished experiment copied into the tree would compile into a shipping app with an icon on a wearer's grid, silently, roughly 1,000 times. `--allow-unrostered` overrides it and prints what it took.

### 2.2 Two things the build refuses to do

Both because the failure is silent on a badge and expensive at roughly 1,000 units:

- ship a `.py` beside its own `.mpy`. MicroPython stats the source *first*, so a badge holding both runs the source: no speed-up, possibly stale code, and no error anywhere. `main.py` is the one allowed exception (the frozen boot imports it by path, and it is under a kilobyte, so there is nothing to win and a format to get wrong);
- exceed the 12 MB FAT allocation `/system` is packed into. Over budget is not a slow install, it is an install that cannot happen.

### 2.3 The two stock fonts are an INPUT, and you already have them

A finished badge carries three `.af` outline faces. This package contains one: `MonaSans-Medium.af`, our own OFL rebuild, with its licence beside it. The other two are yours, byte-exact assets from the release, and the pinned release publishes no licence grant for them, so they are in neither this export nor the repository it came from.

In a **v3.0.2** release clone they are at:

```
<badgeware>/firmware/assets/fonts/DynaPuff-Medium.af
<badgeware>/firmware/assets/fonts/IndieFlower-Regular.af
```

`--stock-fonts <dir>` verifies both against these SHA-256s **before** copying them, so a release that moved underneath us is a refusal rather than a silent substitution:

| face | bytes | SHA-256 |
|---|---:|---|
| `DynaPuff-Medium.af` | 9,688 | `e15bd8b9709b6196da4b4fa74a94ca3f23a24d9b9fd8d8776d733136cd74649b` |
| `IndieFlower-Regular.af` | 9,756 | `a917728b392046f7bcd90575652613884af7bd3e9c435b7ca8b93cb07fae935c` |

**There is no fetch and no resolver, on purpose.** A build that reaches the network is not one we would ask you to trust, and you are the party that already has the release on disk. `--stock-fonts` is the whole mechanism, and this section is where it is specified; `assets/fonts/README.md` points here rather than restating it.

Without `--stock-fonts` the build **stops**. `--no-stock-fonts` overrides that and prints a warning: this tree replaces `/system` wholesale, so a missing stock face is a REMOVAL from a stock badge rather than an omission from a package, and 19,444 bytes of a 12 MB volume is not a budget argument.

### 2.4 What the build writes that is not in this package: `secrets.py`

The build emits `build/system/secrets.py`: eight provisioning slots, **every value empty**. Badgeware's frozen `secrets` helper reads `/secrets.py` first and falls back to `/system/secrets.py`, so this is what an unprovisioned badge reads, and an empty string is a better answer than an `ImportError`.

**The shipped BadgeLink runtime reads these slots, but this build never populates them.** `apps-roster.json` records `system_lib.ship: true`, so `network_runtime` and its complete flat/package/CA payload are compiled into `/system/lib`; an unprovisioned unit still fails closed because every value in the generated template is empty. The eight are: the venue network name and its password, a two-letter Wi-Fi regulatory domain, an IANA timezone, a per-badge ES256 identity token, the project's publishable API key, the realtime host that drives SNI and TLS verification, and an optional pre-resolved IPv4.

Two rules on it, and both are now ENFORCED rather than promised:

- **it is never populated by anything in this package, ever.** The per-unit file is provisioned separately and must be a SUPERSET of these keys. Nothing in this export or the repository it came from writes a credential value anywhere;
- there is no `secrets.py` in the source export itself, deliberately, and the exporter's own secrets gate refuses one by name. A file of empty slots is a build product, not source.

**A `secrets.py` at the export root is a refusal, populated or not, and this paragraph is here because the code did not always agree with the two rules above it.** Until 2026-08-26 the build COPIED a root `secrets.py` into the staged tree and wrote its own template only when none was there, so a credential an operator happened to leave beside `apps/` shipped as `/system/secrets.py` to every badge installed from that build, silently. Three things changed and each covers a different way in:

- `tools/build.py` stops in preflight, before it compiles anything or replaces a good `build/system`, if that file exists. It is checked by existence and **never opened**, so the refusal cannot read or log what it is protecting. Move the file outside this tree (do not delete it if it holds anything real) and rebuild;
- the empty template is written **unconditionally**, so nothing can win the race by being on disk first;
- the staged template is re-parsed before it is hashed into `manifest.json` and any non-empty value stops the build. That refusal names the **keys**, never the values: a build log gets pasted around more than the file ever would.

Real credentials never travel through a build. They go to `/secrets.py` on the badge's 1 MB writable root over ordinary MicroPython serial:

```sh
mpremote connect PORT fs cp <your-file> :/secrets.py.tmp
mpremote connect PORT exec "import os; os.rename('/secrets.py.tmp', '/secrets.py')"
```

Temporary file plus rename, then read it back to confirm without printing it. `/secrets.py` wins over `/system/secrets.py`, so this overrides the empty template without touching the common image.

### 2.5 Developing by drag and drop, and why this package precompiles

**Plain `.py` works, and it is your own documented flow.** The `tufty2350` README's "Installing Apps" section is four steps: double-tap RESET, a disk named `Tufty2350` appears, copy an app directory into `apps`, unmount. Source runs directly. For development, a one-off tweak or reading a traceback against the line you edited, that is the fastest loop there is, and nothing in this package takes it away: every module here is the source, and dropping an app directory onto a badge is a valid way to run it.

**This package ships bytecode anyway, for three reasons, all measured on this tree.**

| | source form | bytecode form |
|---|---:|---:|
| the modules | 2,937,792 B | 503,629 B (17%) |
| plus assets and the two files that stay source | +980,312 B | +980,312 B |
| **staged `/system`** | **3,918,104 B** | **1,483,941 B** |
| of the 12 MB FAT allocation | 31% | 12% |

1. **Headroom.** Source form fits today. It fits with 8.3 MB in hand against 0.9 MB, and the assets are the part that grows, so the compile is what keeps the artwork budget rather than the code budget the binding constraint.
2. **First-open latency, which is the one a wearer feels.** Every app exit is a full reset (`ARCHITECTURE.md` section 2), so *every* open is a cold open. The badge parses and compiles each `.py` it imports as one uninterruptible native call per module: nothing of ours can paint the panel while that runs, which is why a heavy app freezes its own loading animation. The largest module in this tree is `apps/setup/skins.py` at 326,156 B of source, which compiles to a 102,017 B `.mpy` that **still costs 630-765 ms to import cold on device** (a measured band across several runs, not a point estimate). Shipping the source would add the parse to that, on every open, forever.
3. **A stray `.py` beside its own `.mpy` silently wins.** MicroPython stats the source first, so a badge holding both runs the source: no speed-up, possibly stale code, no error anywhere. That is the failure mode a mixed drag-and-drop-plus-build workflow produces, and it is exactly what `--verify-mount` reports as a stray.

So: develop by drag and drop, ship the build. If you drop a source app onto a badge that carries this build, clear that app's directory first and run `--verify-mount` before you conclude anything about performance.

**Your documentation, for anything this package does not cover:** the Help section of the `tufty2350` README, the Badgeware API docs at <https://badgewa.re/docs>, and the firmware images at <https://github.com/pimoroni/tufty2350/releases/latest>.

---

**One honest caveat about reproducibility.** `mpy-cross` embeds the source name it is handed as the traceback filename, so bytecode built from this export carries `apps/setup/card_app.py` where bytecode built from the full repository carries `setup/badge/setup/card_app.py`. Both are reproducible; they are not byte-identical to each other. If you want to compare an artifact against one of ours, compare a build of *this* tree against a build of *this* tree.

---

## 3. The launcher's stock base

`apps/menu/` is **deliberately incomplete**. The launcher is your menu app, patched, and four of its files are not in this export or in the repository it came from, because the pinned release publishes no licence grant for its source:

```
__init__.py    app.py    default_icon.png    ui.py
```

`ui.py` is the exception in the other direction: ours **replaces** yours, and it is already here.

Point the build at your own copy:

```sh
python3 tools/build.py --stock-menu <badgeware>/firmware/apps/menu
```

It verifies all four files against pinned SHA-256s **before** substituting anything, then applies the patches in `apps/menu/PATCHES.json` -- an anchor-and-replacement register, machine-appliable and readable, with a `why` on every entry. A drifted base is a refusal, not a patch that quietly matched half of something. `apps/menu/README.md` is the prose version of the same five patches.

---

## 4. Install: Disk Mode

The wearer-facing path. It is a file copy onto a USB volume.

**This is the same procedure the README's quick start runs, in the same order and with the same commands.** There is one install path for this package, and it is this one. What the README leaves out and this section adds is why each step is shaped the way it is.

1. **Double-tap RESET** on the back of the badge, toward the right. A disk mounts. **Read its name off the mount before you paste anything**, because we have two sources and they disagree: your README's "Installing Apps" says the disk is named `Tufty2350`, and the pinned v3.0.2 board configuration sets `PIMORONI_FATFS_LABEL "TUFTY"` (`board/mpconfigboard.cmake`), which is also what our own device notes recorded. We have written `Tufty2350` live below and left `TUFTY` one comment away. **If one of those is stale, it is worth knowing which.** A wrong `MOUNT` is refused by name: step 3 asks the kernel whether the path is a mount point before it deletes anything, so an unmounted badge, a leftover directory or a typo stops the install instead of costing you two directories. (From a live REPL the equivalent is `import powman; powman.reset_into_msc()`. The BOOTSEL disk from BOOT+RESET is a different volume, `RP2350`, and it belongs to section 0.2.)

   ```sh
   MOUNT=/media/$USER/Tufty2350   # Linux, or /run/media/$USER/Tufty2350
   #MOUNT=/Volumes/Tufty2350      # macOS
   #MOUNT=/media/$USER/TUFTY      # Linux, the label the pinned board config sets
   #MOUNT=/Volumes/TUFTY          # macOS, same
   ```

2. **Mind the path translation.** Badgeware's logical `/system/apps` and `/system/assets` appear at the mounted volume's **top level**:

   ```
   /system/apps/setup       ->   $MOUNT/apps/setup
   /system/main.py          ->   $MOUNT/main.py
   /system/assets/fonts     ->   $MOUNT/assets/fonts
   /system/lib              ->   $MOUNT/lib
   ```

   Creating `$MOUNT/system/...` makes an unused duplicate tree, can fill the 12 MB volume, and leaves the running app unchanged.

3. **Clear, copy and verify. One command, and it is the only destructive step in this package.**

   ```sh
   python3 tools/build.py --install "$MOUNT"
   ```

   **Everything it can refuse, it refuses before it deletes anything.** In order: the build exists; the build matches its own manifest; the build was made from this source tree as it stands right now; the build is not a `--skip-menu`/`--no-stock-fonts` one; the build was made for the pinned firmware; `$MOUNT` is a real mounted volume the size of a badge and is not this source tree. A refusal costs you nothing, and the message says whether to fix the build or the mount.

   **This was four shell lines until it was one, and each of the four had a way to end badly.** The block began with a bare recursive delete of the badge's two root directories, with nothing in front of it. (Described rather than reproduced: written out it is still a line somebody can paste, and this package now refuses to print it.) A build that refuses leaves the previous `build/system` exactly where it was, by design, so a compile error was followed by the delete, by a copy of the **previous** build, and by a verification against that previous build's own manifest, which passes and proves only that the wrong bytes copied cleanly. On a fresh checkout with no build at all, the delete still ran, the copy failed, the verification failed, and the eject was attempted anyway. And nothing checked `$MOUNT`: any directory holding `apps/` and `assets/` was enough, which includes this export's own root.

   **Clearing first is still what it does, because this tree replaces `/system` wholesale rather than merging into it.** A badge arrives with a stock `/system`, and a copy over the top leaves the stock lineup in place: measured on a volume seeded from a release clone, 188 files the build did not emit, 54 stray `.py` shadowing their own bytecode, and 16 stale app directories, every one of them a live tile pointing at code that is not there. Clearing the roots is also what makes a `.py` to `.mpy` switch safe when it is interrupted.

   **It copies manifest-named files rather than `build/system/.` wholesale.** The obvious one-liner also copies `build/system/manifest.json` onto the volume, where it is a file the build did not emit and the verification fails. The current build manages five top-level paths, not just `apps/`: `apps/`, `assets/`, `lib/`, `main.py`, and `secrets.py`. The three directories are cleared before copying; the two files are overwritten. Leaving `main.py` behind boots the stock launcher from stock source, while leaving `lib/` behind can run stale networking code. `--verify-mount` catches both.

   **It copies in Python rather than shelling out to `cp -R`, and that is the AppleDouble fix.** On macOS `cp -R` carries extended attributes, FAT cannot hold them, and the kernel writes them beside the file as a `._*` sidecar: one of those under `apps/` is a file the badge tries to IMPORT. `COPYFILE_DISABLE=1` is the documented suppression, this section documented it, and neither copy command in the old procedure set it. A data-only copy has no metadata to spill, so there is nothing left to disable. If you do copy by hand for any reason, `COPYFILE_DISABLE=1` and `dot_clean -m` on the volume still apply, and the sidecar check below is still there to catch you.

   **It is not atomic on the volume and does not pretend to be.** FAT on a USB volume has no rename-into-place, so between the clear and the end of the copy the badge holds a partial `/system`. That is survivable: the badge is in Disk Mode and is not running the tree. Run the command again. What is not survivable is ejecting a partial install, which is why the verification is inside this command and the eject in step 4 is chained to its exit code.

4. **The verification is the last thing it does, and it is the install's only proof.**

   It compares every file on the volume against `build/system/manifest.json` by size and SHA-256 and reports seven findings: missing files, wrong bytes, files on the volume the build did not emit, stray `.py` that would shadow their own bytecode, AppleDouble/OS sidecars, stale app directories under `apps/`, and unexpected top-level directories. Any one of them fails the install non-zero. It never deletes: what to remove is printed, and removing a file the build does not own stays your call.

   ```sh
   python3 tools/build.py --verify-mount "$MOUNT"
   ```

   That is the same check on its own, read-only, for when you want to ask the question again without reinstalling. Either way it replaces a hand checklist of the same seven things, and at roughly 1,000 units the checklist is the failure mode, not the check.

   For the current production build, a pass includes an exact app-root check: `menu`, `setup`, `nametag`, `schedule`, `snake`, `flappy`, `settings`, `glyph`; only the six rostered tiles are discoverable as wearer-facing tiles (`menu` is the hidden boot host and `glyph` has no entry point). It also requires the complete `/system/lib` payload. A review-only root such as `breakout`, `pacman`, `pong`, or `pet` is therefore an extra and fails.

   One finding is worth knowing about before you see it: a stale app directory is a live tile pointing at code that no longer exists, which in one real case was 3.82 MB of it.

5. **Eject cleanly, and chain it.** The quick start writes `python3 tools/build.py --install "$MOUNT" && umount "$MOUNT"` for a reason: a `&&` makes the eject unreachable unless the install verified, and unlike `set -e` it is not a line an editor can quietly drop. Not ejecting cleanly has corrupted the filesystem before. The badge reboots into the launcher; open one updated app and confirm it starts. An install is not a test: a deploy with no app opened is an install claim, not a behaviour claim.

---

## 5. Flashing firmware

**The procedure is section 0.2 and it is stated once.** BOOT + RESET, an `RP2350` disk, one `.uf2` copy, and the two flavours matter: `-with-filesystem` resets every app to stock and the plain `-micropython.uf2` does not.

Three things that belong here rather than there:

- **A bad flash cannot brick the badge.** The ROM bootloader is immutable, so BOOT + RESET and flash again.
- **The disk vanishing mid-copy is the flash succeeding** and the badge rebooting, not a failure.
- **Reinstall the apps after any flash** (section 4) so the bytecode provably matches the firmware. That is the whole reason the version gate in section 1.1 exists.

---

## 6. Two boot-path gotchas

**A hard reset cannot show you `/system/main.py`'s own first line over serial.** USB re-enumeration takes roughly 1.3 seconds, so anything printed before that is gone. If you are checking the boot path, hard reset and then attach -- and note that an ordinary `mpremote exec` auto-soft-resets into the raw REPL and **skips `/system/main.py` entirely**. Use `mpremote resume exec`.

**A file named `hardware_test.txt` at the volume root is a boot hijack.** The firmware's frozen main opens it and imports the factory hardware test *before* it imports `/system/main.py`. Nothing in this export ships that file; if one appears on a badge, that badge does not boot into this software.
