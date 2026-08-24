# Why this badge ships with networking off

The badge is OFFLINE-FIRST. Every shipping app works with no network, no account and no pairing, and the fleet launches that way on purpose. This page is the honest version of why: what keeps the radio off, what the offline product does about network-shaped features, and what turning networking on looks like when it is ready.

## Two independent layers keep it off

**1. The network runtime is not installed.** Networking lives in a separate library that installs to `/system/lib`; it is not part of this package, and the roster in this package says so (`apps-roster.json`, `system_lib.ship: false`). `main.py` keeps its guarded import either way: it appends `/system/lib` to `sys.path` and imports the runtime inside a `try` whose handler catches the failure, prints `BADGELINK_NETWORK boot=offline error=ImportError`, and boots straight on into the launcher. You can read that guard in this tree's own `main.py`. It is verified mechanically, twice: this package's `imports-resolve` gate proves every import in every app is local, firmware or guarded (`settings` is the only app that touches `/system/lib` modules, and it guards all three), and the exporter that builds the flashable artifact reads the BUILT boot file and refuses the build if that guard is ever narrowed or hoisted.

**2. The radio preference fails closed.** Even on a badge that has the library installed, the radio runs only if whoever is holding the badge turned it on from Settings. The preference is a small record on the badge's writable volume; a missing, corrupt, over-sized or wrong-schema record all read as OFF, and the write is atomic (temp file, flush, sync, rename) so a power cut cannot turn a half-written record into an enabled radio. The fleet default is OFF.

## Why it is off for launch

The connect path works, and it is not yet up to product standard: it blocks the UI. The badge is a single-threaded MicroPython machine that runs one cooperative network step inside each rendered frame, and building a connection is a sequence of blocking calls. Measured on hardware, three runs: connection establishment blocked one rendered frame for 2,252-2,436 ms. The breakdown is known exactly. The TLS handshake totals roughly 1.0-1.1 s, and 820-903 ms of that is ONE atomic CPU-bound call that does not yield, measured by two independent instruments. A control run with chain verification disabled attributes roughly 480 ms of that call to certificate-chain verification and roughly 343 ms to the rest of the crypto (that control is a bench instrument with no production path: the fleet runs `CERT_REQUIRED` against two pinned roots). The remaining ~1.4 s of the block is protocol work and waiting, which CAN be split into small budgeted steps that each fit inside an ordinary frame.

That split is the re-architecture in progress: a non-blocking connect that takes bounded steps across frames, behind a build-time flag in the runtime library (default off; only the build tooling can flip it, and no file, preference or command on the badge can reach it). Until that path passes its on-device soak gates and is accepted, the blocking path is the only connect path, and a product that visibly freezes for two seconds is not one we ship. So the product ships offline.

## What the offline product does about network-shaped features

Nothing in this tree pretends to be online, and nothing asks the wearer to fix being offline.

- **The schedule** is a baked agenda that needs no connection. Its header carries a small provenance mark instead of a freshness claim: distinct shapes for no link state, content verified current, content known superseded, linked-but-never-verified, and a hand-loaded day-of copy. An offline badge is never told it is out of date, because offline is this product's normal state and an alarm that is always on is not read.
- **The clock is trusted or it is silent.** The only thing that ever sets the badge's clock is the network runtime's server time sync. When nothing trustworthy has set it, the schedule shows the plain agenda and says nothing about time at all: no current-session marker, no countdown, no prompt to set anything. There is deliberately no manual time dial, because a hand-set clock is a claim, not a time.
- **Settings** reports the network state honestly. With the runtime absent, its network view says it is not ready. It does not nag, and no app asks the wearer to configure networking.

## What turning it on looks like

One roster key plus the holder's own switch, and no file in this tree changes:

1. `system_lib.ship: true` in the roster puts the runtime library back into the flashable artifact. `main.py` already carries the guarded import and `settings` already guards its runtime imports, so the same source boots both ways.
2. The holder turns the radio preference on from Settings (or fleet provisioning does): the fail-closed switch above.

The non-blocking connect flag is a separate, third decision inside the runtime library itself, and it stays off until its soak gates pass.

## What we would ask you about all this

One question, and it is item 7 of `ARCHITECTURE.md` section 8, where the rest of our asks live. The short version: everything runs on one thread, the UI and the network take strict turns, and three moments still hold the frame long enough to stop the animation. We have measured all of them and we are re-architecting around them, but the atomic call above is a floor we cannot get under. Rather than ask you to answer a list, we would rather show you the problem and the numbers and hear how you would approach it. Asked once, in one place, so nothing is asked twice with different figures.
