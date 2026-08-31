# How this badge uses the network

The badge is OFFLINE-FIRST and this package ships the network runtime. Both are true at once, and the order matters: every shipping app works with no network, no account and no pairing. On a fresh badge the radio and instant updates start ON. Networking is additive here. Nothing in this tree waits for it, asks the wearer to fix it, or degrades without it.

## Fresh starts on; damaged preference fails closed

The runtime being installed is not proof of a connection. Production leaves the small local preference record absent, which means radio and push ON. A valid stored preference wins. A corrupt, over-sized, unreadable or wrong-schema record reads the radio as OFF, and the write is atomic (temp file, flush, sync, rename) so a power cut cannot turn a half-written record into an enabled radio. Push remains ON unless a valid stored preference or retained fleet policy disables it.

`main.py` appends `/system/lib` to `sys.path` and imports the runtime inside a `try` whose handler prints `BADGELINK_NETWORK boot=offline` and boots straight on into the launcher, so the same source boots both ways and a badge whose library is missing or damaged is a working offline badge rather than a brick. Settings guards its library controls and degrades to its "Not ready" view if they are unavailable.

## What it cost, and what changed

This is the part worth reading before trusting networking on this single-threaded badge.

The badge is a single-threaded MicroPython machine that runs one cooperative network step inside each rendered frame, so a blocking call is a stopped screen, not a slow one. Building a connection used to be a sequence of blocking calls: measured on hardware over three runs, connection establishment blocked ONE rendered frame for 2,252 to 2,436 ms. Out of range it was worse, because the badge spent its whole 5,000 ms open budget inside a single frame, measured at 5,163 ms and 5,166 ms by two independent instruments.

The fix is a non-blocking connect that takes bounded steps across frames. The same out-of-range case measures 126 ms stepped. It is controlled by a build-time flag inside the runtime library, so only the build tooling can flip it: no file, preference or command on the badge can reach it. It is ON in this package.

What has NOT been eliminated is one atomic CPU-bound call in the TLS handshake, roughly 820 to 903 ms, measured by two independent instruments. It does not yield, so it is one long frame at connect time. A bench control with chain verification disabled attributes roughly 480 ms of it to certificate-chain verification and roughly 343 ms to the rest of the crypto; that control has no production path, because the fleet runs `CERT_REQUIRED` against pinned roots and will keep doing so. Connecting is therefore still visible. Staying connected is not.

## What the network is for

Nothing in this list is required for the badge to be a badge.

- **Schedule freshness.** The agenda is baked into the package and needs no connection. Its header carries a small provenance mark rather than a freshness claim: distinct shapes for no link state, content verified current, content known superseded, linked-but-never-verified, and a hand-loaded day-of copy. A connected badge can move that mark. An offline badge is never told it is out of date, because offline is a normal state here and an alarm that is always on is not read.
- **The clock.** The only thing that ever sets the badge's clock is the runtime's server time sync. When nothing trustworthy has set it, the schedule shows the plain agenda and says nothing about time at all: no current-session marker, no countdown, no prompt to set anything. There is deliberately no manual time dial, because a hand-set clock is a claim, not a time.
- **Pairing and fleet effects.** Settings carries the pairing and network status screens. They report state honestly and they do not nag.

## Turning it off

One roster key, and no file in this tree changes:

1. `system_lib.ship: false` in `apps-roster.json` leaves the runtime library out of the flashable artifact. `main.py` already carries the guarded import and `settings` already guards its runtime imports, so the same source boots both ways.
2. Below that, the holder's own switch is still the thing that decides, and it still fails closed.
