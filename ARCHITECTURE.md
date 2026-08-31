# Architecture

How the badge software is put together, why it is shaped this way, and where the shape is load-bearing. Read `README.md` first for the lineup; this is the page for someone who is going to have an opinion about the code.

> **Current production boundary.** Exactly six tiles ship: `setup`, `nametag`,
> `schedule`, `snake`, `flappy`, `settings`. Hidden `menu` and no-entry-point
> `glyph` complete the eight `/system/apps` roots; Glyph exists only for the
> launcher's first-wake ceremony and is not a Nametag dependency. The complete
> BadgeLink runtime ships under `/system/lib`. References below to a dark export,
> Badgecard/Poster as tiles, a full Glyph viewer, or Pet describe the earlier
> review package from which this architecture record was cut, not the final
> install contract.

---

## 1. Boot, end to end

Nothing of ours runs first. The chain is:

```
power / RESET
  -> frozen main.py in the firmware image
       reads hardware_test.txt if present  (a boot hijack; we never ship that file)
  -> import badgeware              constructs the ST7789; the panel is black here
  -> /system/main.py               ours, in this export
       - Pimoroni's hash-pinned main, patched twice (see README)
       - the guarded BadgeLink block, dark in this export
       - its stock comments are yours and we left them: one of them still
         mentions auto-launching a rasteriser test app, which this build
         does not do. The hash pin is what proves we started from your
         file, so we did not edit around it.
  -> launch("/system/apps/menu")   the launcher IS the boot host
  -> the launcher's module body
       - first_wake.play()         the ceremony, on RESET only
       - loading.begin()           unless the ceremony already drew
       - the app grid
  -> commit() returns a path       and main.py launches that app
```

Two consequences fall straight out of this and both matter more than they look.

**The launcher's module body holds the earliest project-owned instruction on the badge.** Everything before it belongs to the firmware: threads are compiled out, there is no hook, and no Python of ours can run. So anything that must happen "first" happens there, and there is no earlier place to move it to.

**Launcher to app is not a reset; app to launcher is.** Leaving the launcher only returns a path, in the same interpreter, so the launcher's last frame sits on the panel while the next app imports. Going home is `machine.reset()`, which re-runs `import badgeware` and reconstructs the panel, which is why the screen goes black on the way home and why the launcher is the one screen that genuinely needs a loading screen.

---

## 2. App lifecycle, and why every exit is a reset

An app is a directory under `/system/apps/`. The firmware's `launch()` imports it, calls `update()` in a loop, and hands back whatever `update()` returns. There are exactly three ways out and all three end at the same instruction:

1. **HOME.** `launch()` registers a falling-edge IRQ on the HOME pin *before it imports the app*, so HOME works from any app state -- including an app's own error screen. The IRQ calls the app's `on_exit` first, then resets. A pending write is therefore not lost, and leaving is distinguishable from crashing.
2. **A normal return.** `update()` returning non-`None` ends the loop, `launch()` returns, and `/system/main.py` falls through to a bare `reset()`.
3. **A crash.** An escaping exception reaches the firmware's `fatal_error`, which flips the panel to HIRES, draws a traceback modal, blocks for a keypress and resets.

**Exit-is-reset is a design choice we would defend, not an accident.** It means no app has to unwind its own state, the launcher is always entered on a known-good heap, and there is exactly one recovery path for every failure. What it costs is that nothing survives in RAM between apps, so every piece of persistence in this product is a file on flash and the only open question is *when* it is written. Two answers ship, and the difference is the premise of the flash-wear question in section 8:

- **Synchronously, at the press that made the change.** Every commit in the badge editor, every rung of the Settings brightness ladder, every game score that beats the stored one. Nothing is deferred, so nothing is owed to an exit or a timer.
- **Debounced, in the one app whose state changes faster than a press.** `pet` writes through `ui.Saver`: a change marks the state dirty, the write lands once the state has been quiet for `SAVE_DEBOUNCE_MS = 400`, and `SAVE_MAX_DEFER_MS = 1000` caps how long a dirty state may wait however busy it is. `on_exit` flushes, so HOME costs at most one pending write and never loses one.

No app in this export constructs a `Saver`: `pet` was the only one and its tile was retired on 2026-08-28. Everything here is the first bullet.

It also produces one non-obvious behaviour worth knowing before you read the launcher: on the RP2350, `machine.reset()` is served **through the watchdog**, so every return to the launcher reads wake reason 242. That is how "no animation between apps" is enforced by silicon rather than by a flag someone has to remember to clear.

The third consequence is that a raise in the **launcher** is a loop: reset, boot, run the same failing code, reset. That app needs a USB cable to recover, which is why the launcher guards `import loading` and `import first_wake` -- a soft dependency that is missing there must degrade, never raise -- and why its commit path is wrapped end to end and returns `None` on any exception.

The launcher is not the only place that guards an import, and section 3 is the reason: `sys.path` holds exactly one entry, so everything optional is imported inside a `try`. That was true when `/system/lib` was absent from this export and it stays true now that `lib/` ships it: whether the library is built is one roster key, a badge can be flashed either way, and an app that assumed it was there would be an app that resets on the badges built without it. **The guarded surface is 58 import sites across 25 files**, every one of them enumerated in `AGENTS.md` -- `main.py`'s BadgeLink block, Settings' `qrcode` and its four `/system/lib` peers (`pairstate`, `pairview`, `store`, and `scorebox` guarded separately from the coupled three so the Scores row still works with no library at all), glyph's optional 2x deck, the staged loading screen's `os` and `loading_sql` in each app that vendors it, the score sink's `scorebox` in each game that records a run, the launcher's two `json` reads of `/state` (the wearer's brightness and the enabled-apps gate, both total and both defaulting rather than raising), and the launcher's two above.

---

## 3. The shared layer, and the copies

MicroPython puts exactly **one** path on `sys.path`: the running app's own directory. An app *can* import from a sibling app's directory, but then it refuses to start unless that sibling happens to be installed -- a bad trade on a badge whose HOME key can launch anything in any order.

So shared code is **copied**, not imported. `scripts/sync_ui.py` in the full repository owns one table of canonical sources and their consumers, refreshes every copy, and has a `--check` mode that hashes each copy against its source and exits non-zero on drift. Maintainers run the repository's production lane by hand, and that lane invokes `--check`; there is no tracked CI configuration or hook setup. This export runs its own equivalent over the shipping subset and refuses to build on a mismatch. `shared/README.md` is the map.

What is in the layer:

| module | what it owns |
|---|---|
| `ui.py` | chrome, list views, the softkey bar, the one auto-repeat curve, the outline-face memo |
| `poster.py` | the worn-badge renderer: staged arrival, the name plate, the backdrop cache |
| `backdrop.py` | the artwork cache format on `/state` |
| `wallpaper.py` | the baked launcher film format |
| `effects.py` | the whole-surface filters, and the rule that they are applied once per paint |
| `idle.py` | the inactivity clock, and only the clock -- it never decides what counts as input |
| `backlight.py` | every brightness number in the product, in one file, importing nothing |
| `loading.py`, `loading_sql.py` | the staged loading screen |
| `game_palette.py`, `score_sink.py` | the games' shared palette and high-score sink |
| `kb_shell.py` | the keyboard controller the name editor drives |

**`game_palette.py` and `score_sink.py` were authored for five games and two of them ship here** (snake and flappy). Their comments, and a line in `apps/flappy/README.md`, still name pong, breakout and pacman: those apps exist in the repository this export was cut from and were left out of the lineup, so a reader who goes looking for them in this tree will not find them. Nothing in the shipped code imports them.

Two of these deserve a note. `backlight.py` imports nothing at all and `idle.py` imports only `time`, deliberately: both are vendored into the launcher, and the launcher is the app whose failure needs a cable, so a module it carries must have nothing to fail on. And `idle.py` refuses to define input -- the launcher's definition is "any of A/B/C/UP/DOWN at held level" because its own gestures are a press edge, a release and a held level, so an edge-only definition would dim the panel under a resting thumb.

---

## 4. HIRES and LORES, and where the decision lives

Two panel modes: **HIRES 320x240 1:1** and **LORES 160x120** (pixel-doubled).

- **Identity surfaces are HIRES.** A name, a QR code and a sticker are read, not played, and 160 columns runs out of room for real vector type.
- **Games are LORES.** A game frame has a budget, and the panel cost is where it goes. The whole-surface `phosphor` filter snake runs is 9.34 ms at LORES against 35.23 ms at HIRES, and every game frame budget we hold was measured at 160x120.
- **The launcher is LORES**, at the firmware's own default. Its grid, its baked wallpaper film and its loading screen are all authored for 160x120.

**The mode is chosen exactly once per app, in its entry seam, and nothing downstream names a mode.** `ui.Chrome` reads `screen.width`, the glyph skin reads the cell geometry, the mark sheet reads `chrome.scale`. Two AST-walking tests in the full repository (`badgecard`'s and `poster`'s; only `poster`'s ships in this export) fail if a second `badge.mode` call appears anywhere in those packages. That constraint is what makes the resolution a one-line decision instead of a sweep.

**The launcher is the one exception, and it is a ceremony rather than a mode.** `apps/menu/first_wake.py` calls `badge.mode` at 3 sites and no other file in the launcher calls it at all: `_enter_mode` reads the entry mode and then takes the panel to `RIPPLE_MODE` (`"hires"`) for the first-wake animation, and `_leave_mode` gives the entry mode back from a `finally`, before the launcher paints. The grid is never drawn at HIRES. A `badge.mode` that is missing or refuses leaves the panel at 160x120 and plays the LORES arm, which is why both call sites are wrapped. No AST test covers this one, because a test that allowed the ceremony would allow the thing it exists to forbid.

---

## 5. Memory discipline

The badge has a fixed heap, no swap, and a garbage collector whose pauses land in the middle of frames. Three habits follow, and they are the reason most of the code that looks over-engineered is over-engineered:

1. **Allocate once, rewrite in place.** Frame buffers, plate buffers and run tables are allocated in `__init__` or at module scope and mutated per frame. The comments at those sites carry the measured saving.
2. **Retain, don't rebuild.** Vector shapes, loaded outline faces and rendered plates are held in module-level or instance-level caches keyed on the thing that would change them. The alternative is not slower; it is a different product. One catalogue skin went from 252 ms per frame to 11.88 ms on device purely by keeping its nineteen shapes rather than rebuilding their point lists every frame. Those lists held 867 vectors when that measurement was taken; a later tolerance change cut the same skin to 615 points for a 0.01% fidelity difference, so counting the shipped source will not reproduce the 867.
3. **Never hold two big things at once.** Stage ordering in the worn-badge renderer exists partly for this: the name is on the panel before the 307,200 B backdrop buffer and the 953 KB mark sheet are touched.

**The related constraint is compile time, not run time.** The badge parses and compiles every `.py` it imports as **one uninterruptible native call per module** -- nothing of ours can paint while that runs, which is exactly why a heavy app freezes a loading animation. Shipping `.mpy` removes the compile entirely. See `BUILDING.md`; the source in this export is what a human edits, and bytecode is a build artifact.

---

## 6. The idle ladder, and the first-wake ceremony

**Idle is a ladder, not a sleep.** Twenty seconds without input dims the panel to 20% (the floor of the wearer's own 20/40/60/80/100 ladder -- an idle dim that reads as *dead* has failed at its one job). Ten seconds later the launcher opens the badge: it returns `/system/apps/poster`, the same route the 1.5-second hold takes, so this is an existing shortcut reached by a new trigger and not a new destination.

**There is no third rung and no auto-sleep.** The automatic path always ends at the badge, never at a dark panel. That is a measured decision: worst run-to-flat on this hardware is 8 h 28 m and best is 11 h 14 m, so the badge survives its conference day without ever sleeping itself, and an auto-sleep would spend the product's whole reason for existing to buy an hour nobody needs. Sleep exists, but only as a row in Settings that a person chooses.

**The press that un-dims the panel is consumed.** The panel is already restored by the time the clock reports the wake, and both callers throw the press away: the launcher marks every currently-down key stale (so neither the hold nor B's release-launch can fire) and the badge editor returns from `update()` before its controller is called. It is a one-shot consume with no invented millisecond figure in it. If a walk test says a wearer resents the extra press, deleting four lines is the whole retreat.

**`poster` has no idle clock at all** -- not a clock with a rung removed. It is the state the ladder exists to reach, so it holds the wearer's brightness for as long as it is open.

**The ceremony runs on RESET only**, gated on `badge.wake_reason()` against `(0xF1, 0xFF)`: a deliberate RESET tap or a cold attach play it, and 242 (which is every app exit, per section 2) plays nothing after one register read. A wearer sees two recorded glyph animations back to back, 248 frames, with the four rear case lights following frame by frame. It **vendors no asset** -- the decks, the mask bank and the LUT are read out of `/system/apps/glyph` as a soft dependency, so a badge without that app boots unchanged with no ceremony, and a heap check turns a short heap into a skipped ceremony rather than a modal.

---

## 7. Why the ugly spots are ugly

There are perhaps a dozen places in this source where an experienced reader's first instinct will be to clean something up. They are all measured, and each one now carries a comment stating the constraint and the number. The pattern to recognise:

- **A preallocated buffer held on an attribute** rather than built where it is used. The worn badge's name plate is the clearest: retained, it runs at 20.11 FPS with zero rebuilds; rebuilt per frame it runs at 15.43 FPS with 180 rebuilds in 180 frames. That is 22.097 ms off the median frame for 58,240 B of retained buffer, measured on device.
- **A module-level dict that looks like a leak.** `ui._load_vector` memoises the loaded outline face because `font.load` caches nothing on the native side: four calls for one name returned four distinct 73,728 B objects at 111.3 ms each, and 111.3 of a `Chrome()`'s 112.1 ms was that one call. On device, memoising it collapsed the worn badge's whole build step (`Chrome()`, the app, and its plan) from 116.3 ms on every open to 116.5 ms once and a 3.8 ms median after.
- **A cache validity stamp** instead of just re-rendering. The backdrop cache is a 21x difference on a cold open: 915.5 ms to render against 43.4 ms to read.
- **A per-frame budget expressed in panel quanta.** The panel's own update quantum is 11.43 ms at both resolutions, so a frame that must hold three quanta has a body ceiling, and the launcher's filter shuffle is cut against it rather than against a round number.
- **A filter applied at present time, once**, at the end of a composition rather than inside a draw loop. Applying it twice would compound it, and on the worn badge it is 8.246 ms of draw for a whole-surface effect where the p99 frame did not move at all.
- **A consumed button press** that appears to be a dropped input.

None of those numbers are host estimates. Where a host model and the device disagreed, the device won and the host figure was retired -- one of them was two orders of magnitude out, and we would rather tell you that than have you find it.

---

## 8. Where we would value your eyes

Honestly, and in the order we would ask:

1. **Per-app frame budgets.** We hold LORES game budgets measured at 160x120 and HIRES identity budgets measured at 320x240, and we cut features against the 11.43 ms quantum. We do not have a good model of what VSYNC pacing does to a frame that lands just over a quantum boundary, and we have one filter that visibly flickers between two and three quanta. If there is a right way to think about that on this panel, we would like to be told.
2. **Flash wear, in both of the shapes section 2 describes.** Most of our persistence is synchronous: every commit in the badge editor is a write, and the Settings tile's brightness ladder writes on every rung change. We chose that over deferred saves because a badge that loses a wearer's name is worse than a badge that wears its flash. **`pet` is the exception and it is the case we understand least** -- it writes through a debounced saver (400 ms of quiet, or 1000 ms since the state first went dirty, whichever comes first, plus a flush on exit), so its write pattern is bursty where the others are one write per deliberate press. We have no wear model for either, and roughly 800 units are about to be handled for two days. If the FAT/LittleFS layout or the flash part makes either shape a real risk at that volume, that changes a decision -- and if the debounced one is the risk, we would rather hear that before we extend it to another app.
3. **Anything Tufty-specific we got wrong.** We have measured a lot from the outside: `font.load` costing 111 ms and caching nothing, `powman` verbs being software-invokable, the panel quantum being identical at both resolutions, `sys.path` holding exactly one entry, `machine.reset()` arriving as a watchdog. Every one of those is inference from a probe rather than knowledge of the firmware, and any of them being wrong invalidates something downstream.
4. **The pinned image.** We build against the public **v3.0.2** tag, and we know that is weaker than it looks: picovector is built from a floating `main`, so two images tagged v3.0.2 need not be byte-identical. Our mpy format gate compares what `mpy-cross` emits against the pinned firmware source, but the exact UF2 the fleet will be flashed with is still an open question for us. If you can name it, we will pin to it.
5. **The launcher patches.** We apply 5 patches across 2 of your files (`__init__.py` and `app.py`), replace your `ui.py` wholesale, and copy `default_icon.png` untouched; `apps/menu/PATCHES.json` carries every anchor, its replacement and a `why`, and `apps/menu/README.md` is the prose version. If any of those five patches would be better as an upstream hook, we would far rather carry the hook than the patch.
6. **Whether the code reads.** This export exists partly to ask that. Where a comment explains a measurement, we would rather it were shorter and clearer; where it explains a workaround for firmware behaviour, we would rather not need it.

**The last one is about networking, which is not in this tree.** `NETWORKING.md` explains why the fleet ships with the radio off and carries every measurement quoted below; the runtime itself lives in the repository this export was cut from. We are asking anyway, because it is the answer we would most like to have and because most of it is only answerable by you.

7. **The networking ask, and it is the one we care most about.** Everything on this badge runs on one thread, so the UI and the network take strict turns: when a network step holds its turn too long, the animation stops. Steady state is fine now, at a worst residual gap of 69 ms over ~90 s in all three measured runs. Three moments still hold the frame. The TLS handshake is one indivisible call of 820-903 ms, and a control run with chain verification disabled attributes roughly 480 ms of it to verifying the certificate chain. The WebSocket's opening exchange is the remaining ~1.4 s of the block, most of it waiting on replies. And the first clock sync lands in a preparation step that costs 1,668 ms cold, most of it two unbounded name lookups inside the firmware's own `ntptime`. We have measured all of it and we are re-architecting the connection into budgeted per-frame steps, but the indivisible TLS call is the floor that work cannot get under. **Our question is the open one: how do you think about this class of problem on this hardware?** Things we wondered while measuring, offered as prompts rather than requests: the RP2350 has a hardware SHA-256 block, and we do not know whether your mbedTLS build reaches it; `MICROPY_PY_THREAD` is 0 in this firmware, and we do not know whether a `_thread`-enabled build is viable here or off for a reason we should know before designing around it; every app exit is `machine.reset()`, so a wearer pays the whole join again on every switch, and we do not know whether any firmware path could let radio or link state survive that. Separately, and it is the one thing on this whole list we cannot measure ourselves: you shipped the GitHub Universe 2025 badge on this platform, and roughly 800 of ours are about to be in one room. What did venue Wi-Fi actually do with hundreds of badges associating at once, and what dead-on-arrival rate should we plan for? Mostly, though: here is the problem and here are our numbers, and we would rather hear how you would approach it than have you answer any single question above.
