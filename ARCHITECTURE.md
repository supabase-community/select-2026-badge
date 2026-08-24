# Architecture

How the badge software is put together, why it is shaped this way, and where the
shape is load-bearing. Read `README.md` first for the lineup; this is the page
for someone who is going to have an opinion about the code.

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
  -> launch("/system/apps/menu")   the launcher IS the boot host
  -> the launcher's module body
       - first_wake.play()         the ceremony, on RESET only
       - loading.begin()           unless the ceremony already drew
       - the app grid
  -> commit() returns a path       and main.py launches that app
```

Two consequences fall straight out of this and both matter more than they look.

**The launcher's module body holds the earliest project-owned instruction on the
badge.** Everything before it belongs to the firmware: threads are compiled out,
there is no hook, and no Python of ours can run. So anything that must happen
"first" happens there, and there is no earlier place to move it to.

**Launcher to app is not a reset; app to launcher is.** Leaving the launcher only
returns a path, in the same interpreter, so the launcher's last frame sits on the
panel while the next app imports. Going home is `machine.reset()`, which re-runs
`import badgeware` and reconstructs the panel, which is why the screen goes black
on the way home and why the launcher is the one screen that genuinely needs a
loading screen.

---

## 2. App lifecycle, and why every exit is a reset

An app is a directory under `/system/apps/`. The firmware's `launch()` imports
it, calls `update()` in a loop, and hands back whatever `update()` returns. There
are exactly three ways out and all three end at the same instruction:

1. **HOME.** `launch()` registers a falling-edge IRQ on the HOME pin *before it
   imports the app*, so HOME works from any app state -- including an app's own
   error screen. The IRQ calls the app's `on_exit` first, then resets. A pending
   write is therefore not lost, and leaving is distinguishable from crashing.
2. **A normal return.** `update()` returning non-`None` ends the loop, `launch()`
   returns, and `/system/main.py` falls through to a bare `reset()`.
3. **A crash.** An escaping exception reaches the firmware's `fatal_error`, which
   flips the panel to HIRES, draws a traceback modal, blocks for a keypress and
   resets.

**Exit-is-reset is a design choice we would defend, not an accident.** It means
no app has to unwind its own state, the launcher is always entered on a
known-good heap, and there is exactly one recovery path for every failure. What
it costs is that nothing survives in RAM between apps, which is why every piece
of persistence in this product is a file written synchronously at the press that
made it -- not at exit, and not on a timer.

It also produces one non-obvious behaviour worth knowing before you read the
launcher: on the RP2350, `machine.reset()` is served **through the watchdog**, so
every return to the launcher reads wake reason 242. That is how "no animation
between apps" is enforced by silicon rather than by a flag someone has to
remember to clear.

The third consequence is that a raise in the **launcher** is a loop: reset, boot,
run the same failing code, reset. That app needs a USB cable to recover, and it
is why `import loading` and `import first_wake` are the only guarded imports in
the product and why its commit path is wrapped end to end and returns `None` on
any exception.

---

## 3. The shared layer, and the copies

MicroPython puts exactly **one** path on `sys.path`: the running app's own
directory. An app *can* import from a sibling app's directory, but then it
refuses to start unless that sibling happens to be installed -- a bad trade on a
badge whose HOME key can launch anything in any order.

So shared code is **copied**, not imported. `scripts/sync_ui.py` in the full
repository owns one table of canonical sources and their consumers, refreshes
every copy, and has a `--check` mode that hashes each copy against its source and
exits non-zero on drift. CI runs `--check` on every commit; this export runs its
own equivalent over the shipping subset and refuses to build on a mismatch.
`shared/README.md` is the map.

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
| `game_palette.py`, `score_sink.py` | the five games' shared palette and high-score sink |
| `kb_shell.py` | the keyboard controller the name editor drives |

Two of these deserve a note. `backlight.py` imports nothing at all and `idle.py`
imports only `time`, deliberately: both are vendored into the launcher, and the
launcher is the app whose failure needs a cable, so a module it carries must have
nothing to fail on. And `idle.py` refuses to define input -- the launcher's
definition is "any of A/B/C/UP/DOWN at held level" because its own gestures are a
press edge, a release and a held level, so an edge-only definition would dim the
panel under a resting thumb.

---

## 4. HIRES and LORES, and where the decision lives

Two panel modes: **HIRES 320x240 1:1** and **LORES 160x120** (pixel-doubled).

- **Identity surfaces are HIRES.** A name, a QR code and a sticker are read, not
  played, and 160 columns runs out of room for real vector type.
- **Games are LORES.** A game frame has a budget, and the panel cost is where it
  goes. The whole-surface `phosphor` filter snake runs is 9.34 ms at LORES
  against 35.23 ms at HIRES, and every game frame budget we hold was measured at
  160x120.
- **The launcher is LORES**, because it never calls `badge.mode` at all and runs
  at the firmware's own default.

**The mode is chosen exactly once per app, in its entry seam, and nothing
downstream names a mode.** `ui.Chrome` reads `screen.width`, the glyph skin reads
the cell geometry, the mark sheet reads `chrome.scale`. Two AST-walking tests
(`apps/badgecard`'s and `apps/poster`'s) fail if a second `badge.mode` call
appears anywhere in those packages. That constraint is what makes the resolution
a one-line decision instead of a sweep.

---

## 5. Memory discipline

The badge has a fixed heap, no swap, and a garbage collector whose pauses land in
the middle of frames. Three habits follow, and they are the reason most of the
code that looks over-engineered is over-engineered:

1. **Allocate once, rewrite in place.** Frame buffers, plate buffers and run
   tables are allocated in `__init__` or at module scope and mutated per frame.
   The comments at those sites carry the measured saving.
2. **Retain, don't rebuild.** Vector shapes, loaded outline faces and rendered
   plates are held in module-level or instance-level caches keyed on the thing
   that would change them. The alternative is not slower; it is a different
   product. One catalogue skin went from 252 ms per frame to 11.88 ms on device
   purely by keeping its 19 shapes rather than rebuilding 867 vectors each frame.
3. **Never hold two big things at once.** Stage ordering in the worn-badge
   renderer exists partly for this: the name is on the panel before the 307,200 B
   backdrop buffer and the 953 KB mark sheet are touched.

**The related constraint is compile time, not run time.** The badge parses and
compiles every `.py` it imports as **one uninterruptible native call per
module** -- nothing of ours can paint while that runs, which is exactly why a
heavy app freezes a loading animation. Shipping `.mpy` removes the compile
entirely. See `BUILDING.md`; the source in this export is what a human edits, and
bytecode is a build artifact.

---

## 6. The idle ladder, and the first-wake ceremony

**Idle is a ladder, not a sleep.** Twenty seconds without input dims the panel to
20% (the floor of the wearer's own 20/40/60/80/100 ladder -- an idle dim that
reads as *dead* has failed at its one job). Ten seconds later the launcher opens
the badge: it returns `/system/apps/poster`, the same route the 1.5-second hold
takes, so this is an existing shortcut reached by a new trigger and not a new
destination.

**There is no third rung and no auto-sleep.** The automatic path always ends at
the badge, never at a dark panel. That is a measured decision: worst run-to-flat
on this hardware is 8 h 28 m and best is 11 h 14 m, so the badge survives its
conference day without ever sleeping itself, and an auto-sleep would spend the
product's whole reason for existing to buy an hour nobody needs. Sleep exists,
but only as a row in Settings that a person chooses.

**The press that un-dims the panel is consumed.** The panel is already restored
by the time the clock reports the wake, and both callers throw the press away:
the launcher marks every currently-down key stale (so neither the hold nor B's
release-launch can fire) and the badge editor returns from `update()` before its
controller is called. It is a one-shot consume with no invented millisecond
figure in it. If a walk test says a wearer resents the extra press, deleting four
lines is the whole retreat.

**`poster` has no idle clock at all** -- not a clock with a rung removed. It is
the state the ladder exists to reach, so it holds the wearer's brightness for as
long as it is open.

**The ceremony runs on RESET only**, gated on `badge.wake_reason()` against
`(0xF1, 0xFF)`: a deliberate RESET tap or a cold attach play it, and 242 (which
is every app exit, per section 2) plays nothing after one register read. A wearer
sees two recorded glyph animations back to back, 248 frames, with the four rear
case lights following frame by frame. It **vendors no asset** -- the decks, the
mask bank and the LUT are read out of `/system/apps/glyph` as a soft dependency,
so a badge without that app boots unchanged with no ceremony, and a heap check
turns a short heap into a skipped ceremony rather than a modal.

---

## 7. Why the ugly spots are ugly

There are perhaps a dozen places in this source where an experienced reader's
first instinct will be to clean something up. They are all measured, and each one
now carries a comment stating the constraint and the number. The pattern to
recognise:

- **A preallocated buffer held on an attribute** rather than built where it is
  used. The worn badge's name plate is the clearest: retained, it runs at
  20.11 FPS with zero rebuilds; rebuilt per frame it runs at 15.43 FPS with 180
  rebuilds in 180 frames. That is 22.097 ms off the median frame for 58,240 B of
  retained buffer, measured on device.
- **A module-level dict that looks like a leak.** `ui._load_vector` memoises the
  loaded outline face because `font.load` caches nothing on the native side: four
  calls for one name returned four distinct 73,728 B objects at 111.3 ms each. On
  device, the memo collapsed the chrome build from 116.3 ms to a 3.8 ms median.
- **A cache validity stamp** instead of just re-rendering. The backdrop cache is
  a 21x difference on a cold open: 915.5 ms to render against 43.4 ms to read.
- **A per-frame budget expressed in panel quanta.** The panel's own update
  quantum is 11.43 ms at both resolutions, so a frame that must hold three quanta
  has a body ceiling, and the launcher's filter shuffle is cut against it rather
  than against a round number.
- **A filter applied at present time, once**, at the end of a composition rather
  than inside a draw loop. Applying it twice would compound it, and on the worn
  badge it is 8.246 ms of draw for a whole-surface effect where the p99 frame did
  not move at all.
- **A consumed button press** that appears to be a dropped input.

None of those numbers are host estimates. Where a host model and the device
disagreed, the device won and the host figure was retired -- one of them was two
orders of magnitude out, and we would rather tell you that than have you find it.

---

## 8. Where we would value your eyes

Honestly, and in the order we would ask:

1. **Per-app frame budgets.** We hold LORES game budgets measured at 160x120 and
   HIRES identity budgets measured at 320x240, and we cut features against the
   11.43 ms quantum. We do not have a good model of what VSYNC pacing does to
   a frame that lands just over a quantum boundary, and we have one filter that
   visibly flickers between two and three quanta. If there is a right way to
   think about that on this panel, we would like to be told.
2. **Flash wear.** Every commit in the badge editor is a synchronous write, and
   the Settings tile's brightness ladder writes on every rung change. We chose that over deferred saves
   because a badge that loses a wearer's name is worse than a badge that wears
   its flash, but we have no wear model at all and roughly 800 units are about to
   be handled for two days. If the FAT/LittleFS layout or the flash part makes
   this a real risk at that volume, that changes a decision.
3. **Anything Tufty-specific we got wrong.** We have measured a lot from the
   outside: `font.load` costing 111 ms and caching nothing, `powman` verbs being
   software-invokable, the panel quantum being identical at both resolutions,
   `sys.path` holding exactly one entry, `machine.reset()` arriving as a
   watchdog. Every one of those is inference from a probe rather than knowledge
   of the firmware, and any of them being wrong invalidates something downstream.
4. **The pinned image.** We build against the public **v3.0.2** tag, and we know
   that is weaker than it looks: picovector is built from a floating `main`, so
   two images tagged v3.0.2 need not be byte-identical. Our mpy format gate
   compares what `mpy-cross` emits against the pinned firmware source, but the
   exact UF2 the fleet will be flashed with is still an open question for us. If
   you can name it, we will pin to it.
5. **The launcher patches.** We substitute into four files of yours (see
   `apps/menu/README.md`). If any of those five patches would be better as an
   upstream hook, we would far rather carry the hook than the patch.
6. **Whether the code reads.** This export exists partly to ask that. Where a
   comment explains a measurement, we would rather it were shorter and clearer;
   where it explains a workaround for firmware behaviour, we would rather not
   need it.
