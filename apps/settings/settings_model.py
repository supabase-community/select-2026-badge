"""Pure view-model for the general-purpose Settings tile (OWNER-DECISIONS #2).

The owner ruled (2026-08-17, form SETTLED in the 2026-08-19 addendum) that the
permanent extra launcher tile is a **general-purpose Settings app** — hosting,
at the time, the Pair entry, plus a **network status** view — connected /
stopped-because-revoked-or-expired / unreachable — carrying an on-screen "reboot
to retry" instruction, because a badge stopped on 403 holds until the next boot
(OWNER-DECISIONS #14; ``polltransport._enter_revoked``). The Pair entry was
deleted on 2026-08-28 (see below); the general-purpose tile it justified is what
survives, and the addendum's own reasoning is why -- other settings-shaped needs
were already planned, and six of them are now rows here.

WHAT THIS MODULE IS. A drawing-agnostic, I/O-free state machine: the row list,
the selection, the screen routing and the transport-state -> wearer-copy
mapping. Everything here runs under CPython, so the whole tile's behaviour is
fixture-testable and the device layer (``settings_view``) is only pixels.

**THE PAIR ENTRY IS DELETED (owner instruction, 2026-08-28).** In the owner's
words: *"can you completely remove the phone linked thing, because that's going
to be just removed from the system anyway as part of the new update."* With it
went the ``PAIR`` screen, the ``Phone`` row, this module's whole
``badgelink.pairview`` consumer layer (the title/line/label maps, the
``LABEL_EVENTS`` key -> ``pairstate`` event table, the undriven-action
fallbacks) and the ``softkey_events`` field those two halves talked through.
``pairview`` and ``pairstate`` still ship in ``/system/lib`` with their own
tests; nothing in this tile reads them.

It was also BROKEN when it was deleted, which is why the row went first rather
than last: ``settings/__init__.py`` never passed ``driver=``, so every press of
the first row of the menu resolved straight to ``pair_start_failed`` and the
wearer's first impression of the tile was "Could not reach the server."

WHY EVERY BADGELINK DEPENDENCY IS INJECTED AND NOTHING IS IMPORTED. BadgeLink's
shared modules install to ``/system/lib`` (OWNER-DECISIONS #1) and reach an app
only through the one ``sys.path.append`` line ``/system/main.py`` carries. A
badge whose ``/system/lib`` has not been refreshed in the same session as this
tile therefore has the tile and not the library — and a bare ``import store``
at module scope on that badge raises INSIDE ``launch()``, which resets the badge
(``docs/deploy.md``: "an import that raises inside ``launch()`` resets the badge
— every badge, not one"). So the app guards its one presence probe, hands this
model a ``library`` boolean, and a missing library degrades to honest copy on
the three screens that describe networking instead of to a reset loop.
``launcher/menu/ui.py`` guards ``import loading`` for exactly the same reason.

WHERE THE WORDS LIVE, AND WHY NOT HERE. Every wearer-facing string is in
``settings_copy`` (owner ruling, 2026-08-21: the old labels were protocol words,
not human words). This module still owns the DECISION of which string a state
gets; it does not own the string.

BUTTON CONVENTIONS (``docs/badge-button-rules.md``, guidelines not laws):
B is the primary action on every screen (B1/B2); UP and DOWN move the selection
by one and wrap (B3); A is the labelled way back and **commits nothing** (I2).

**TWO SCREENS DECLARE A DEVIATION.** The second is CLOCK (owner request,
2026-08-28): B switches ROWS on a value field and activates on a button, because
the screen is a layout with two buttons in it -- see `clock_view`, which also
records why A becoming a direction there did not cost §I2's five-A test. On BRIGHTNESS
(owner ruling, 2026-08-24) A and C are the two ENDS of an ordered ladder and B
carries the way back, which is §9.2(b) of the button rules rather than an
exception to them — and it is the same bar the wearer met while the row lived in
``setup``. :func:`bright_view` states what bounds it, and
``settings/README.md`` § "Brightness" records it. (There is no deviation TABLE in
that README -- `setup` and `identity` keep registers, this tile does not --
so the section is the record, and this pointer is exact on purpose: a reference to
a table that does not exist reads as coverage nobody wrote.)
"""


import backlight
import settings_copy


SCHEMA = 1

# Screens this model routes between. There is no PAIR screen since 2026-08-28;
# see the docstring for the owner instruction that deleted it.
MENU = "menu"
NETWORK = "network"
#: The P6 doorbell's own screen (P6-L3, 2026-08-21). Its own row rather than a
#: third softkey on the Network screen: two switches on one screen make a bare
#: ON/OFF label ambiguous about WHICH switch it moves, and this one has enough
#: to explain (turned off by you / kept failing / turned off by the event) that
#: it needs the body band the Network screen is already using.
PUSH = "push"
#: The sleep note's own screen (owner design, 2026-08-23). Not a confirmation --
#: see `ROWS` below for why it is not one -- but a screen all the same, because
#: the panel is about to go dark and the wearer is owed one second of copy
#: saying what happened and how to undo it.
SLEEP = "sleep"
#: The brightness ladder's screen (owner ruling, 2026-08-24). A SCREEN rather
#: than an in-place edit on the menu row, and that is forced rather than chosen:
#: the ladder needs two keys, and on the menu UP and DOWN already move the
#: selection while B opens. It arrives here whole from `setup`, where it
#: lived for a day -- same rungs, same store, same one-press-per-rung
#: motion -- so the only thing this app had to decide was the bar.
BRIGHT = "bright"
#: The score-erase question and its result (owner feature, 2026-08-27). THE ONLY
#: DESTRUCTIVE SCREEN THIS TILE HAS, so it is the only one that follows B7's
#: confirmation shape rather than acting on the row it was opened from. One screen
#: constant covers the question and the answer: `setup` reuses `CONFIRM` for
#: the same reason -- it is one question with one subject, and a second screen id
#: for "the same screen, afterwards" would need its own route for no behaviour.
SCORES = "scores"
#: The operator's screen (2026-08-27). THE ONLY SCREEN IN THIS TILE THAT IS NOT
#: FOR THE WEARER, and it exists because on 2026-08-27 the badge KNEW the answer
#: three separate times and had no way to say it -- an hour of guessing each
#: time, over values `pushlink` had already computed and published to a serial
#: port with nothing attached to it. `settings_copy`'s diagnostics block names
#: the three incidents; the design rule they produced is that this screen
#: SURFACES what the runtime already has and adds no counter, no state and no
#: machinery of its own. The one thing it does own is the frame sweep, and that
#: is here for the same reason: nothing else on this badge could show a wearer's
#: eye the difference between a slow frame and a stopped one.
DIAG = "diag"
#: The repair screen (2026-08-28). THE PARACHUTE FOR A BLOCKED NTP, and the
#: state it exists for is the one `diag_view`'s clock line was added to make
#: visible: no plausible wall clock means `clock_boot.resync` RAISES rather than
#: failing soft, so verified TLS cannot validate a certificate, so the badge has
#: NO TRANSPORT AT ALL -- and a conference network that blocks UDP/123 is the
#: ordinary way to get there for a whole fleet at once. At the venue there is no
#: USB: the badges are on battery and handed out, so the only repair channel is
#: this panel and the five buttons under it.
#:
#: IT SAT AGAINST THE 2026-08-24 CLOCK DOCTRINE (*"we either get a real time from
#: a server or don't assume we know time"*, which deleted `schedule`'s dial) AND
#: THE OWNER OVERRULED THAT ON 2026-08-28, because the first clause assumes the
#: badge can ASK: with no plausible clock there is no TLS session to carry a
#: server's time, so "from a server" is unreachable in exactly the case it was
#: written for. `schedule/README.md` § "The 2026-08-28 overrule" is the amendment,
#: recorded beside the original ruling rather than replacing it.
#:
#: ⚠ **THE DOCTRINE'S ACTUAL CONCERN SURVIVES THE OVERRULE AND IS STILL LIVE.**
#: The harm it named was exact -- "a dial does not produce a time; it produces a
#: CLAIM by whoever is holding the badge", which `schedule` then dressed in the
#: same green NOW row a synced badge gets. A clock set here is that same claim,
#: and `schedule` still cannot tell the difference: its `CLOCK_TRUSTED` test is a
#: year floor plus the event window, both of which a hand-set clock passes. It is
#: not closable from here -- every app switch is `machine.reset()` and nothing
#: about verification is persisted -- and the follow-up (a `/state` "hand-set"
#: marker) is deliberately NOT part of this screen. Do not read the overrule as
#: having disposed of it.
#:
#: WHAT HOLDS THE LINE MEANWHILE: this screen never claims a sync.
#: `DeviceBackend._clock_verified` stays False, so Diagnostics reads
#: `Clock yes  sync no` after a hand-set -- the operator's screen keeps the
#: distinction even though `schedule`'s cannot -- and the result copy says a
#: server will replace it.
CLOCK = "clock"

# Row identifiers. The tile is general-purpose on purpose: the owner's reasoning
# for one Settings tile over a tile per need was that other settings-shaped needs
# are already planned (battery visibility among them), so adding one is a row
# here and not a launcher negotiation.
ROW_NETWORK = "network"
ROW_PUSH = "push"
ROW_SLEEP = "sleep"
ROW_BRIGHT = "bright"
ROW_SCORES = "scores"
ROW_DIAG = "diag"
ROW_CLOCK = "clock"

ROW_LABELS = {
    ROW_NETWORK: settings_copy.ROW_NETWORK_LABEL,
    ROW_PUSH: settings_copy.ROW_PUSH_LABEL,
    ROW_SLEEP: settings_copy.ROW_SLEEP_LABEL,
    ROW_BRIGHT: settings_copy.ROW_BRIGHT_LABEL,
    ROW_SCORES: settings_copy.ROW_SCORES_LABEL,
    ROW_DIAG: settings_copy.ROW_DIAG_LABEL,
    ROW_CLOCK: settings_copy.ROW_CLOCK_LABEL,
}
ROW_SCREENS = {
    ROW_NETWORK: NETWORK,
    ROW_PUSH: PUSH,
    ROW_SLEEP: SLEEP,
    ROW_BRIGHT: BRIGHT,
    ROW_SCORES: SCORES,
    ROW_DIAG: DIAG,
    ROW_CLOCK: CLOCK,
}

#: HOW MANY PAGES THE TWO DIAGNOSTIC SCREENS HAVE. **FIXED, AND THAT IS THE
#: LOAD-BEARING DECISION.**
#:
#: A count derived from "how much data this badge happens to have" would need a
#: second pure function agreeing with the builder, which is drift -- and worse,
#: it would MOVE UNDER AN OPERATOR. At the venue the sentence that works is
#: "press DOWN twice and read me the third line", and a page count that changes
#: when a badge gains a session destroys that instruction. A page with nothing
#: behind it still draws, and says so IN WORDS, which is this tile's existing
#: doctrine (`DIAG_NO_PUSH`, `_flag`'s three answers): the absence of a
#: measurement is never zeroes.
#:
#: THE OWNER'S RULING IS WHAT MADE FOUR PAGES LEGAL AT ALL (2026-08-28):
#: *"Scrolling is absolutely fine. The more information, the better."* Before
#: it, both screens were rationed to `settings_view.MAX_BODY_LINES` bands and
#: the values below simply had nowhere to go.
#:
#: **THE TWO COUNTS ARE INDEPENDENT AND DIAGNOSTICS IS FIVE SINCE 2026-08-29.**
#: The fifth is the score drain -- `scores_pending` and `scores_stalled`, the
#: two fields `network_runtime._pump_scores` calls "the pull-based form of the
#: same answer" and which no view read. Making them a PAGE rather than two lines
#: squeezed onto an existing one is the fixed-count doctrine working as intended:
#: a page is authored, once, and then it is where it is for ever, so "turn to the
#: last page and read me both lines" keeps meaning the same thing at a venue.
NETWORK_PAGES = 4
DIAG_PAGES = 5
#: The table BOTH halves of paging read: `Settings._move` turns the page and
#: `settings/__init__.py` decides which screens read UP/DOWN as bare edges.
#: `test_settings_seam` asserts the seam's table and the builders' `pages` keys
#: name the same screens, which is the only drift neither lane can see alone.
PAGES = {NETWORK: NETWORK_PAGES, DIAG: DIAG_PAGES}

#: THE FILES "ERASE SCORES" TAKES, BESIDES THE UNDELIVERED SPOOL. One per game,
#: written by `shared/score_sink.py` and read as the wearer's high score.
#:
#: THIS TILE CARRIES ITS OWN COPY OF THE LIST AND DOES NOT IMPORT ONE, which is
#: the same decision `setup` made about `setup_state` and for a stronger
#: reason: `scorebox.GAME_STATE_PATHS` says the same five paths, but it lives in
#: `/system/lib`, which production requires but installs separately. A wearer
#: erasing high scores that have nothing to do with networking must not lose that
#: local action if the shared library is missing or damaged.
#: `settings/tests/test_settings_scores.py` pins this list
#: against `scorebox`'s and against each game's own `STATE_PATH`, so the
#: duplication cannot drift silently -- and a silent drift here means a wipe that
#: misses a game while the modal says it took everything.
#:
#: FIVE, EVEN THOUGH THE PRODUCTION ROSTER SHIPS FEWER. Erasing a file that was
#: never written costs nothing, a dev badge has all five, and a badge that later
#: gains a game must not keep a high score the wearer already erased.
GAME_SCORE_PATHS = ("/state/snake.json", "/state/pong.json",
                    "/state/breakout.json", "/state/flappy.json",
                    "/state/pacman.json")
#: Menu order. **NETWORK IS THE HEAD OF THE MENU SINCE 2026-08-28**, and it is
#: there because the row above it was deleted rather than because it won an
#: argument: Pair was first from the tile's first day ("the entry point decision
#: #2 exists to ship") until the owner removed the feature.
#:
#: SLEEP IS LAST, AND IT IS THE FIRST NON-NETWORK ROW THIS TILE HAS EVER HAD.
#: The owner's idle design (2026-08-23) makes it the ONLY route to off -- there
#: is no auto-sleep, ever -- and this file's own comment above already predicted
#: the growth ("other settings-shaped needs are already planned ... adding one is
#: a row here and not a launcher negotiation").
#:
#: WHY LAST, and why it is NOT behind a confirmation. B7 sorts irreversible
#: actions last and puts a confirmation in front of them. Sleep is not
#: irreversible -- one press of any face button ends it -- so B7's letter does
#: not cover it; what it IS is startling, because the panel goes black. The
#: mitigation is the one-second NOTE rather than a question: a wearer who
#: pressed by accident reads what happened and how to undo it, which a
#: yes/no screen would not have told them. Sorting last still applies, because
#: B3's lists wrap and the first UP from the top of the menu lands here -- so
#: the note is also what protects a blind UP-then-B.
#:
#: BRIGHTNESS SITS DIRECTLY ABOVE SLEEP (owner ruling, 2026-08-24: *"Take
#: brightness out of setup. That should only exist in settings."*), and the
#: position is the one thing about the move this tile had to decide.
#:
#: It goes BELOW the network rows because it is the first row here that is about
#: the badge in the wearer's hand rather than about the server, and Sleep is the
#: other one: the menu reads as the connected things, then the two panel things.
#:
#: It does NOT take the last slot, and the temptation was real. `setup`'s
#: menu put this row last on exactly the argument above -- the first blind UP
#: from the top lands on the last row, and B7 wants that to be a harmless one; a
#: ladder is reversible in one press and destroys nothing, while Sleep blanks
#: the panel. Taking the slot would still have been wrong: Sleep's last place is
#: a recorded owner design decision whose mitigation is already built and
#: already tested, and the note protects a blind UP-then-B whether or not a
#: ladder exists. Trading a documented protection for an undocumented one is not
#: an improvement.
#:
#: SCORES SITS IN THE MIDDLE, and its seat is chosen against the two ends rather
#: than for a category. B3's lists wrap, so the two seats a blind press can reach
#: are the LAST row (the first UP from the top) and the SECOND (the first DOWN).
#: Sleep's last place is a recorded owner decision with a built mitigation, and
#: Brightness is pinned directly above it by its own; the destructive row
#: therefore takes neither end and is two deliberate presses from anywhere.
#:
#: `setup` argues the opposite case and both are right: a properly gated
#: destructive row makes a BETTER wrap target than an ungated mildly-costly one,
#: which is why RESET BADGE sits last there. The difference is what the seat is
#: being traded against. There the alternative was SAVE TO HOME, which writes a
#: 76,816-byte film on one press with no question; here the alternatives are a
#: reversible ladder and a documented note, so there is nothing to improve by
#: moving either of them and no reason to take a wrap seat at all.
#:
#: DIAGNOSTICS SITS WITH THE NETWORK ROWS AND IS CONDITIONAL ON NOTHING, and the
#: two halves of that sentence have different reasons.
#:
#: THE SEAT is chosen against the same two wrap-reachable seats the paragraph
#: above weighs: the LAST row (the first UP from the top) and the SECOND (the
#: first DOWN). It takes neither. Sleep's last place and Brightness's place
#: directly above it are both recorded decisions with built mitigations, and
#: Scores is deliberately away from both ends; this row goes after the network
#: rows because that is what most of it describes, and before Scores because the
#: destructive row's distance from a blind press is the thing being protected.
#:
#: UNCONDITIONAL, unlike Updates, and that is not an oversight. The Updates row
#: is conditional because a row describing a transport this badge does not carry
#: is a row that lies. This screen's OTHER half -- the frame sweep and the
#: latched worst frame -- is about the panel, and every badge has a panel. So the
#: argument is Brightness's rather than Updates': the row means something on an
#: unprovisioned badge, and the push half degrades to one honest line
#: (`settings_copy.DIAG_NO_PUSH`) exactly as the Network and Phone rows do. A
#: badge with a missing or damaged `/system/lib` still needs to be able to answer
#: "is this thing dropping frames".
#:
#: CLOCK SITS DIRECTLY AFTER DIAGNOSTICS, and the adjacency is the reason rather
#: than a category: they are the two rows an operator uses TOGETHER. Diagnostics
#: is where `Clock no  ntp_rejected: b` says the wall clock is why this badge has
#: no network, and the very next row is where it gets fixed. A wearer who is
#: never sent there by the screen above it has no reason to open this one.
#:
#: It takes NEITHER wrap-reachable seat (the LAST row, which is the first UP from
#: the top, and the SECOND, which is the first DOWN) for the reason the rows
#: around it already state -- and it is harmless in one press anyway: opening it
#: writes nothing, and A leaves committing nothing.
#:
#: UNCONDITIONAL, like Brightness and unlike Updates. The bounds it enforces are
#: this module's own (see `CLOCK_FLOOR_EPOCH`) and the write is `badgeware`'s, so
#: the row means exactly the same thing on a badge whose required `/system/lib`
#: is missing or damaged. A row that vanished with a networking library would be
#: missing from the badge whose clock nothing else can correct.
#: ⚠ **DELETING PAIR COST DIAGNOSTICS ITS NON-WRAP SEAT, AND THAT IS A PRICED
#: TRADE RATHER THAN AN OVERSIGHT.** Three rows above claim "neither
#: wrap-reachable seat" -- the LAST row (the first UP from the top) and the
#: SECOND (the first DOWN). With six rows that claim is over-determined and
#: cannot hold for all three: Sleep owns the last by a recorded owner decision,
#: Brightness is pinned directly above it, Clock must sit directly after
#: Diagnostics, and the only arrangement that clears seat 1 for all three puts
#: SCORES -- the one destructive row -- at the top, where a single B opens it.
#:
#: SO DIAGNOSTICS TAKES SEAT 1 AND SCORES KEEPS ITS DISTANCE, because the harm
#: being protected against is not symmetrical. Scores is the only row that
#: destroys anything and it is two deliberate presses from anywhere; Diagnostics
#: is a READ-ONLY instrument that writes nothing on open. Its one real cost is
#: that `settings/__init__.py` grants BadgeLink placement while it is up, so a
#: blind DOWN-then-B can overwrite the doorbell latch a wearer walked in with --
#: and that grant is itself a deliberate 2026-08-27 reversal, made because the
#: one screen built to watch a connection happen was the one screen that
#: forbade it. A blind press there does the thing the screen was re-scoped to
#: allow.
ROWS = (ROW_NETWORK, ROW_DIAG, ROW_CLOCK, ROW_SCORES, ROW_BRIGHT,
        ROW_SLEEP)
#: The Updates row is CONDITIONAL: it appears only when the boot pump actually
#: has a doorbell to control. A row that describes a transport this badge does
#: not carry is a row that lies, and the tile already refuses to invent state.
#: Brightness is conditional on nothing: every badge has a panel, so it is the
#: second row after Sleep that means the same thing on an unprovisioned badge.
#: With the Updates row present there are seven seats and every claim above
#: holds again: Updates takes seat 1 and Diagnostics moves down to 2.
ROWS_WITH_PUSH = (ROW_NETWORK, ROW_PUSH, ROW_DIAG, ROW_CLOCK,
                  ROW_SCORES, ROW_BRIGHT, ROW_SLEEP)

#: HOW LONG THE NOTE STAYS UP before `badge.sleep()` is called.
#:
#: ONE SECOND, and it is a READING time rather than a cancel window: nothing can
#: stop the sleep once the row is pressed, so the number only has to be long
#: enough for two short lines to be seen. It is deliberately NOT a confirmation
#: delay -- a window a mashing thumb could cross by accident would be worse than
#: no window at all, and a window it could cancel would need a labelled key,
#: which is the yes/no screen this design rejected.
#:
#: Nobody has felt it. If the owner reads it as too quick, this is the constant.
SLEEP_NOTE_MS = 1000


# -- network status ---------------------------------------------------------
#
# The wearer-facing statuses. The addendum names four; ``polltransport`` on
# origin/main exposes six states, and every one of them is rendered rather than
# folded into a neighbour, because a screen that calls a local stop "unreachable"
# is telling the wearer to check the Wi-Fi for a thing the Wi-Fi cannot fix.
NET_CONNECTED = "connected"
NET_CONNECTING = "connecting"
NET_UNREACHABLE = "unreachable"
#: The 403 verdict: revoked OR expired, terminal until the next boot.
NET_STOPPED = "stopped"
#: ``PollLoop.stop()`` — a local, restartable stop, not a server verdict.
NET_OFF = "off"
#: No transport at all (no BadgeLink library, or no session in this boot), or a
#: transport state string this model does not know. Never guessed at.
NET_UNKNOWN = "unknown"

#: ``polltransport`` state literal -> wearer-facing status. The keys are asserted
#: against the real module's constants by the app<->shared seam test, so a
#: transport that gains or renames a state fails the fast lane instead of
#: silently rendering "unknown" on a badge.
TRANSPORT_STATUS = {
    "connected": NET_CONNECTED,
    "connecting": NET_CONNECTING,
    "disconnected": NET_UNREACHABLE,
    "backoff": NET_UNREACHABLE,
    "stopped": NET_OFF,
    "revoked": NET_STOPPED,
}

#: Short menu-row values: the live state at a glance, in ``settings_copy``'s
#: words. Keyed by the wearer-facing status, not by the transport literal, so
#: two literals that mean one thing to a person share one word.
_STATUS_WORD = settings_copy.STATUS_WORDS


def transport_status(transport_state):
    """Map a ``polltransport`` state literal to a wearer-facing status.

    ``None`` (no transport) and any unrecognised literal both resolve to
    :data:`NET_UNKNOWN`; the raw literal is preserved by :func:`network_view` so
    the screen can print what it actually saw instead of inventing a state.
    """
    if transport_state is None:
        return NET_UNKNOWN
    if not isinstance(transport_state, str):
        raise ValueError("transport state must be text or None")
    return TRANSPORT_STATUS.get(transport_state, NET_UNKNOWN)


#: `ResilientWiFi.state` -> the stage word the RADIO alone can produce. The
#: three that need no other evidence; `online` needs the link record beside it
#: to say whether the badge got any further, so it is resolved in
#: :func:`network_stage` rather than listed here.
_WIFI_STAGE_WORDS = {
    "off": settings_copy.NET_STAGE_OFF,
    "connecting": settings_copy.NET_STAGE_ASSOCIATING,
    "backoff": settings_copy.NET_STAGE_WAITING,
}

#: The prefix `NetworkService.last_error` carries when `credentials.load` refused
#: a value in `/secrets.py`. Spelled here rather than imported for the reason
#: every other mirrored literal in this tile is: the model stays pure and
#: CPython-testable on a machine with no `/system/lib`, and
#: `test_settings_seam.py` is the drift detector that makes it safe.
CREDENTIAL_ERROR_PREFIX = "CredentialError"


def _literal(value):
    """A runtime word, folded and bounded, or ``?``. See :func:`diag_text`."""
    text = diag_text(value) if isinstance(value, str) else None
    return text if text else settings_copy.DIAG_MISSING


def _positive(value):
    """A measured, non-zero, non-``bool`` count of milliseconds."""
    return (isinstance(value, int) and not isinstance(value, bool)
            and value > 0)


def network_stage(wifi, link, network_enabled=None):
    """WHERE THE CONNECTION STOPPED, in one word from a closed set.

    FIRST MATCH WINS, and the order is the order the badge actually walks: a
    credential is read before a radio is started, a radio associates before a
    name is resolved, and a name is resolved before a socket is opened. So the
    earliest thing that is wrong is the thing named.

    ⚠ `credential` IS CHECKED ABOVE THE RADIO BECAUSE THAT IS WHERE IT HAPPENS.
    `DeviceBackend.__init__` calls `credentials.load(secrets)`, so a malformed
    BadgeLink value raises out of the factory, `_backend` stays None, the radio
    is NEVER STARTED and `_retry_at` is set -- which makes the service report
    BACKOFF, which folds onto "Can't reach the server". Today the exact sentence
    naming the field sits in `NetworkService.last_error` and is read by nobody;
    page 4 prints it and this word is the signpost.

    ⚠ `connected` IS CHECKED ABOVE THE PHASE SPLIT, WHICH IS A DELIBERATE
    DEPARTURE FROM THE FIRST DRAFT OF THIS DESIGN. `open_phases` is the LAST
    open's split, and on a healthy badge the last open SUCCEEDED -- so its
    latest non-zero phase is a response phase and a connected badge would have
    read `Stage: reply`. The phases say where an open STOPPED, which is only a
    question worth answering while it is not connected.

    THERE IS NO `handshake` WORD HERE. The WebSocket join is the doorbell's, and
    Diagnostics already reports it as `Join {}  sock {}  uid {}`; inventing one
    would be jargon for a stage this screen cannot observe.
    """
    service_error = link.get("service_error") if isinstance(link, dict) else None
    if (isinstance(service_error, str)
            and service_error.startswith(CREDENTIAL_ERROR_PREFIX)):
        return settings_copy.NET_STAGE_CREDENTIAL
    radio = wifi.get("radio") if isinstance(wifi, dict) else None
    if network_enabled is False or radio == "off":
        return settings_copy.NET_STAGE_OFF
    word = _WIFI_STAGE_WORDS.get(radio)
    if word is not None:
        return word
    transport = link.get("transport") if isinstance(link, dict) else None
    if radio == "online" and transport is None:
        # ASSOCIATED AND NOTHING FURTHER EXISTS YET: no `PollLoop`, so no socket
        # has been attempted. Distinct from a loop that is failing to open one.
        return settings_copy.NET_STAGE_ON_WIFI
    if transport == "connected":
        return settings_copy.NET_STAGE_CONNECTED
    if isinstance(link, dict):
        # THE LATER PHASE WINS, because the open walks dns THEN connect: a
        # non-zero `connect_ms` means the name resolved and the socket is where
        # it stopped. This pair is the whole numeric separation of "DNS is dead"
        # from "TLS is dead" that nothing on the badge could make before.
        if _positive(link.get("connect_ms")):
            return settings_copy.NET_STAGE_TLS
        if _positive(link.get("dns_ms")):
            return settings_copy.NET_STAGE_DNS
    return settings_copy.DIAG_MISSING


def wifi_reason_line(wifi):
    """WHY, in this app's own words, or ``None`` when there is nothing to say.

    The vocabulary is `ResilientWiFi`'s and it is CLOSED -- five healthy words
    and six that arrive through `_fail` -- so the table is total for every build
    this app was written against, and a word from a newer `/system/lib` is drawn
    RAW rather than smoothed over ("no invented states" cuts both ways).

    ⚠ **A `status_<n>` REASON DRAWS AS `Wi-Fi said status_-3` AND NOTHING
    MORE.** `benchmark/results/reports/2026-08-13-v3.0.1-network-authenticated.md`
    recorded a spurious `-3` on CORRECT credentials and ruled a negative CYW43
    status "a retry signal and diagnostic fact, not a safe basis for a permanent
    user-facing" claim. This badge never prints "wrong password".

    SUPPRESSED ON AN ONLINE RADIO. `The Wi-Fi dropped` above a badge that is
    currently associated is noise, and `On Wi-Fi` under `Connected to the
    server` is a band spent repeating the line above it.
    """
    if not isinstance(wifi, dict):
        return None
    reason = wifi.get("reason")
    if not isinstance(reason, str) or not reason:
        return None
    if wifi.get("radio") == "online":
        return None
    line = settings_copy.NET_WIFI_REASON_LINES.get(reason)
    if line is not None:
        return line
    bounded = diag_text(reason)
    if reason.startswith("status_"):
        return settings_copy.NET_LINE_WIFI_STATUS.format(bounded)
    return settings_copy.NET_LINE_WIFI_REASON.format(bounded)


def _ssid_line(lines, wifi):
    """The network name the radio was told to look for, or NOTHING AT ALL.

    **THE OWNER APPROVED THIS ON 2026-08-29** -- *"the SSID name would be
    awesome"* -- reversing the decision `settings_copy`'s SSID block carried
    until that day. It is the only value on the badge that separates "this badge
    was provisioned for the WRONG network" from "the right network is out of
    range": both of those badges read `Stage: associating`, `No answer from the
    Wi-Fi` and `Tries 40  fails 40`, and at a venue with no cable there is
    nothing else to tell them apart with.

    **THE PASSWORD IS NOT HERE AND CANNOT BE.** This reads one key off the radio
    record; `wifi_diagnostics` has never published a credential and this app has
    no path to `/secrets.py` at all.

    ⚠ **NO BAND AT ALL WHEN THERE IS NO NAME, AND THAT IS THE WHOLE DEGRADE.**
    `resilient_wifi.snapshot()` does not publish `ssid` today and
    `network_runtime.WIFI_DIAGNOSTIC_KEYS` has no entry for it -- both are files
    this lane does not own -- so on every badge that exists right now this
    function appends nothing and page 1 is byte-identical to what it drew
    before. A `Network ?` band would be the `_flag` mistake in copy: a
    measurement nobody took, drawn on the one screen that has to be trusted.
    The moment the runtime publishes the key the line appears with no edit here.

    NOT `_literal`, WHICH WOULD CLIP AT `DIAG_TEXT_CHARS`. The SSID has its own
    bound for the reason `diag_uid` has its own: this is a value somebody
    compares character by character against a name printed on a sign, so the
    band's arithmetic rather than a shared 15 decides how much of it survives.
    """
    if not isinstance(wifi, dict):
        return lines
    ssid = wifi.get("ssid")
    if not isinstance(ssid, str) or not ssid:
        return lines
    text = settings_copy.ascii_fold(ssid)[:settings_copy.NET_SSID_CHARS]
    if text:
        lines.append(settings_copy.NET_LINE_SSID.format(text))
    return lines


def _network_answer(lines, status, transport_state, network_enabled, wifi,
                    link):
    """PAGE 1: what, where it stopped, why, and how hard it tried.

    THE PAGE THAT NEEDS NO SCROLLING. Everything below it is evidence for this
    page; an operator who reads only this one has the answer in four lines.
    """
    if network_enabled is False:
        # **THE WEARER'S OWN CHOICE, AND IT OVERRIDES EVERYTHING.** It is the
        # first branch here for the same reason it is the first branch in the
        # status mapping: a badge whose wearer switched the radio off must never
        # read `Not on Wi-Fi yet`, and no stage claim may sit under it. Pages
        # 2-4 still draw their raw records, because an operator still needs to
        # see what the radio was doing when it was switched off -- but no page
        # contradicts this one.
        lines.append(settings_copy.NET_LINE_OFF)
        return lines
    # `None` MEANS "NO MEASUREMENT", NOT "OFFLINE", and the distinction is the
    # whole of the split below. A badge whose `/system/lib` predates
    # `wifi_diagnostics` keeps the two-way copy it had, because the new
    # sentences are claims about a bit this badge cannot read.
    online = bool(wifi.get("online")) if isinstance(wifi, dict) else None
    if status == NET_CONNECTED:
        lines.append(settings_copy.NET_LINE_CONNECTED)
    elif status == NET_CONNECTING:
        # THE FIRST OF THE TWO MERGES, SPLIT. `NetworkService.state` answers
        # CONNECTING whenever its backend is None, so a badge that has never
        # touched its radio used to claim a server connection was in progress.
        lines.append(settings_copy.NET_LINE_JOINING if online is False
                     else settings_copy.NET_LINE_CONNECTING)
    elif status == NET_UNREACHABLE:
        # THE SECOND. `TRANSPORT_STATUS` folds BOTH `disconnected` and `backoff`
        # onto one line, so "Can't reach the server" could not distinguish
        # no-Wi-Fi from no-Supabase. Now it does, and page 3 has the numbers.
        lines.append(settings_copy.NET_LINE_NO_WIFI if online is False
                     else settings_copy.NET_LINE_UNREACHABLE)
    elif status == NET_STOPPED:
        lines.append(settings_copy.NET_LINE_STOPPED)
        lines.append(settings_copy.NET_LINE_STOPPED_WHY)
    elif status == NET_OFF:
        # `PollLoop.stop()` -- a local, restartable stop reported by the
        # TRANSPORT, which is not the wearer's preference handled above.
        lines.append(settings_copy.NET_LINE_OFF)
    elif transport_state is None:
        # NO TRANSPORT AT ALL, which is the ordinary case: this tile never opens
        # a socket, so a boot with no supervisor session has nothing to report.
        # It used to fall through to the branch below and print `State: None` at
        # a wearer — a literal `None` on a panel, which is neither a state nor
        # English.
        lines.append(settings_copy.NET_LINE_NO_SESSION)
    else:
        # A state this build has never heard of. Print it rather than smooth it
        # over: "no invented states" cuts both ways.
        lines.append(settings_copy.NET_LINE_STATE.format(transport_state))
    if wifi is None:
        # THE ACCESSOR IS ABSENT, so there is no stage, no reason and no counts
        # to draw. Said in words rather than as three rows of `?`, which is the
        # `DIAG_NO_PUSH` doctrine: "this badge cannot tell you" is a fact about
        # the runtime, and a row of `?` reads as a fact about the radio.
        lines.append(settings_copy.NET_NO_RADIO)
        return lines
    _ssid_line(lines, wifi)
    lines.append(settings_copy.NET_LINE_STAGE.format(
        network_stage(wifi, link, network_enabled)))
    why = wifi_reason_line(wifi)
    if why is not None:
        lines.append(why)
    # `Tries 0  fails 0` ON A BADGE THAT NEVER STARTED IS THE HONEST READING and
    # it is the single fastest separation on this screen: never-tried is a
    # credential or a switch, forty-tried is an AP that is not answering.
    lines.append(settings_copy.NET_LINE_TRIES.format(
        _number(wifi.get("attempts")), _number(wifi.get("failures"))))
    return lines


def _network_radio(lines, wifi):
    """PAGE 2: the radio, raw, for correlating the panel against serial."""
    if wifi is None:
        lines.append(settings_copy.NET_NO_RADIO)
        return lines
    lines.append(settings_copy.NET_LINE_RADIO.format(_literal(wifi.get("radio"))))
    # A BARE LABEL AND A BARE VALUE, WHICH IS WHAT BUYS THE FIVE EXTRA
    # CHARACTERS. On a band with no prefix the whole 308 px is the word's, so
    # `diag_chunks` applies `DIAG_CHUNK_CHARS` and `radio_activate_error`
    # survives whole where the prefixed clip drew `radio_activate_`.
    lines.append(settings_copy.NET_LABEL_WHY)
    reason = diag_chunks(wifi.get("reason"), 1)
    lines.append(reason[0] if reason else settings_copy.DIAG_MISSING)
    lines.append(settings_copy.NET_LINE_HELD.format(
        _number(wifi.get("connected_s"))))
    lines.append(settings_copy.NET_LINE_REGION.format(
        _literal(wifi.get("region"))))
    lines.append(settings_copy.NET_LINE_TRIES.format(
        _number(wifi.get("attempts")), _number(wifi.get("failures"))))
    return lines


def _network_path(lines, link):
    """PAGE 3: the path to the server, in numbers."""
    if link is None:
        lines.append(settings_copy.NET_NO_LINK)
        return lines
    lines.append(settings_copy.NET_LINE_LINK_STATE.format(
        _literal(link.get("transport"))))
    resolver = link.get("resolver")
    if isinstance(resolver, str) and resolver:
        lines.append(settings_copy.NET_LINE_RESOLVER.format(diag_text(resolver)))
    elif link.get("lookups") is None:
        # NEVER ASKED. There is no resolver record at all -- no backend, or a
        # runtime older than the accessor -- so this is the absence of a
        # measurement and not the grey zone below it.
        lines.append(settings_copy.NET_LINE_RESOLVER.format(
            settings_copy.DIAG_MISSING))
    else:
        # ASKED, AND THE NETWORK OFFERED NOTHING. `resolver_address`'s
        # documented grey zone: no DHCP option 6 and an unusable gateway. This
        # is the sentence that turns "the badge just sits there" into a fact --
        # the whole `bounded_dns` module exists because `getaddrinfo` blocks
        # 13.1-14.0 s with no route.
        lines.append(settings_copy.NET_DNS_NONE)
    lines.append(settings_copy.NET_LINE_DNS_COUNTS.format(
        _number(link.get("lookups")), _number(link.get("lookup_failures"))))
    lines.append(settings_copy.NET_LINE_OPENS.format(
        _number(link.get("opens")), _number(link.get("open_failures"))))
    lines.append(settings_copy.NET_LINE_OUTCOME.format(
        _literal(link.get("outcome"))))
    lines.append(settings_copy.NET_LINE_SPLIT.format(
        _number(link.get("dns_ms")), _number(link.get("connect_ms"))))
    lines.append(settings_copy.NET_LINE_STALL.format(
        _number(link.get("stall_ms"))))
    return lines


def _network_errors(lines, link):
    """PAGE 4: the two error sentences, whole.

    **THIS IS THE PAGE THE WHOLE SCREEN WAS BUILT FOR.**
    `NetworkService.last_error` holds the exact `CredentialError` sentence a
    malformed BadgeLink value raises inside the factory's containment handler,
    and until now it was read by NO VIEW at all -- so a badge that could name the
    field in `/secrets.py` that was wrong said "Can't reach the server" instead.

    TWO BLOCKS AND NEVER ONE. The service error is a fault in what this badge
    was PROVISIONED with; the link error is a fault in what the network did.
    Different repairs, different people, and a merged line sends an operator to
    the wrong one.
    """
    if link is None:
        lines.append(settings_copy.NET_NO_LINK)
        return lines
    _chunk_band(lines, settings_copy.NET_LABEL_ERROR, link.get("service_error"),
                3, settings_copy.NET_NO_ERROR)
    _chunk_band(lines, settings_copy.NET_LABEL_LINK_ERROR,
                link.get("link_error"), 3, settings_copy.NET_NO_ERROR)
    return lines


def network_view(transport_state, library=True,
                 network_enabled=None, network_controllable=False,
                 page=0, wifi=None, link=None):
    """The network screen, per the OWNER-DECISIONS #2 addendum -- four pages.

    ``reboot`` is the flag the addendum's "reboot to retry" instruction hangs
    off, and it is true for exactly one status: :data:`NET_STOPPED`, the 403
    verdict. ``polltransport`` refuses ``request_reconnect`` once revoked
    ("stop until the next boot"), so a RETRY softkey there would be a label that
    does nothing — the copy is the honest affordance.

    **IT BECAME FOUR PAGES ON 2026-08-29 AND THE REASON IS AN INCIDENT.** A
    badge would not join Wi-Fi; it was on a cable, with root access, full source
    and a maintainer reading its serial output, and it was STILL impossible to
    tell a wrong password from an out-of-range AP from a radio fault. Every
    value that would have answered it was already computed and had NO READER.
    On 2026-10-02 there is no cable and no maintainer, so this screen is the
    only diagnostic channel that will exist. `settings_copy`'s network block
    carries the incident and the closed vocabularies.

    ``wifi`` and ``link`` ARE PASSED IN RATHER THAN READ, and which of them
    arrives is the CALLER's page-scoping decision -- see :meth:`Settings.view`.
    Both default to ``None``, which is also what a badge whose `/system/lib`
    predates the accessors produces, so every existing caller, fixture and test
    keeps working unchanged and lands on the "cannot tell you" copy.

    ``page`` IS CLAMPED TOTALLY rather than validated, because this runs on a
    draw path where a raise is `fatal_error` -> `machine.reset()`.

    **THE ACCOUNT LINE IS GONE SINCE 2026-08-28.** This screen carried
    ``Linked to sam`` / ``No account linked`` under the status, read out of the
    durable pair record. The Phone row was deleted on the owner's instruction and
    with it the only thing that could WRITE that record, so the line would have
    said "No account linked" on every badge for ever -- a true sentence about a
    feature the wearer has no way to reach, which is worse than silence. Nothing
    about the transport half changed.
    """
    page = _page_index(page, NETWORK_PAGES)
    status = transport_status(transport_state)
    # A controller is the authority for a deliberate local OFF.  This matters
    # during boot before a transport object exists: OFF is a user choice, not
    # the ambiguous "no session" state.
    if network_enabled is False:
        status = NET_OFF
    lines = []
    if not library:
        # An honest label for the one thing this tile cannot fake: the shared
        # library is not on this badge, so there is no state to report -- ON
        # EVERY PAGE. A row of `?` here would be four pages of a badge
        # pretending to measure something it has no module for.
        lines.append(settings_copy.NET_NOT_INSTALLED)
    elif page == 0:
        _network_answer(lines, status, transport_state, network_enabled, wifi,
                        link)
    elif page == 1:
        _network_radio(lines, wifi)
    elif page == 2:
        _network_path(lines, link)
    else:
        _network_errors(lines, link)

    if library and page == 0 and status == NET_STOPPED:
        # LAST ON ITS PAGE, so `_draw_body`'s reserve-a-band rule keeps it and
        # `settings_view._line_pen` still paints it WARN. It is the one line on
        # this screen that is an ACTION rather than a description.
        lines.append(settings_copy.NET_LINE_REBOOT)
    lines = [settings_copy.ascii_fold(line) for line in lines]

    middle = ""
    if library and network_controllable:
        # A 403 may not be bypassed by reconnect, but the physical holder must
        # still be able to turn the radio OFF.  Once off, turning it on records
        # the next-boot intent; the revoked session itself stays terminal.
        if status != NET_STOPPED or network_enabled is True:
            middle = (settings_copy.STOP if network_enabled
                      else settings_copy.START)
    return {
        "screen": NETWORK,
        # THE ORDINAL IS IN THE TITLE, not in a body band: the title band
        # already exists and costs nothing, and a PHOTOGRAPH of a badge in a
        # hall has to say which page it is -- that photo is the only bug report
        # this event will produce.
        "title": settings_copy.PAGE_TITLE.format(
            settings_copy.ROW_NETWORK_LABEL, page + 1, NETWORK_PAGES),
        "status": status,
        "transport_state": transport_state,
        "reboot": status == NET_STOPPED,
        "page": page,
        "pages": NETWORK_PAGES,
        "lines": lines,
        # The physical holder owns this policy. It changes only the radio
        # preference/session, and since 2026-08-28 there is no pairing record on
        # this badge for it to have been able to touch.
        "softkeys": (settings_copy.BACK, middle, ""),
    }


# -- the updates (push) screen ----------------------------------------------
#
# ``pushlink``'s six live modes plus one for "no controller / a literal this
# build has never heard of". Keyed on the same literals the transport reports, so
# the seam test can assert them against the real module rather than trusting a
# comment.
PUSH_ON = "push"
PUSH_TRYING = "trying"
PUSH_NORMAL = "polling"
PUSH_DEMOTED = "demoted"
PUSH_BLOCKED = "blocked"
PUSH_NETWORK_OFF = "network_off"
PUSH_UNKNOWN = "unknown"

PUSH_MODES = (PUSH_ON, PUSH_TRYING, PUSH_NORMAL, PUSH_DEMOTED, PUSH_BLOCKED,
              PUSH_NETWORK_OFF)

#: live mode -> the line that explains it, where there is room to explain.
_PUSH_LINES = {
    PUSH_ON: settings_copy.PUSH_LINE_ON,
    PUSH_TRYING: settings_copy.PUSH_LINE_TRYING,
    PUSH_NORMAL: settings_copy.PUSH_LINE_NORMAL,
    PUSH_DEMOTED: settings_copy.PUSH_LINE_DEMOTED,
    PUSH_BLOCKED: settings_copy.PUSH_LINE_BLOCKED,
    PUSH_NETWORK_OFF: settings_copy.PUSH_LINE_OFF,
}


def push_mode(mode):
    """Normalise a reported mode; an unknown literal is never smoothed over."""
    if mode is None:
        return PUSH_UNKNOWN
    if not isinstance(mode, str):
        raise ValueError("push mode must be text or None")
    return mode if mode in PUSH_MODES else PUSH_UNKNOWN


# -- WHY the doorbell is not carrying ----------------------------------------
#
# `network_runtime.PUSH_CAUSES`, spelled here rather than imported, exactly as
# the six transport states and the six push modes above are: this module stays
# pure and CPython-testable on a machine with no `/system/lib`, and
# `test_settings_seam.py` is the drift detector that makes the copy safe --
# `test_every_push_cause_the_runtime_can_name_has_wearer_copy` asserts these are
# the runtime's set, so a renamed or added cause fails the fast lane.
CAUSE_NOT_STARTED = "not started"
CAUSE_PLACEMENT = "in an app"
CAUSE_ESTABLISHING = "connecting"
CAUSE_NO_SIGNAL = "no signal"
CAUSE_REFUSED = "refused"
CAUSE_SERVER_BUSY = "server busy"
CAUSE_RETRY_LATER = "retry later"
CAUSE_WAITING = "waiting"

PUSH_CAUSES = (CAUSE_NOT_STARTED, CAUSE_PLACEMENT, CAUSE_ESTABLISHING,
               CAUSE_NO_SIGNAL, CAUSE_REFUSED, CAUSE_SERVER_BUSY,
               CAUSE_RETRY_LATER, CAUSE_WAITING)


def push_cause(cause):
    """Normalise a reported cause to a literal this build has copy for, or None.

    AN UNKNOWN WORD IS DROPPED, AND THIS IS THE ONE PLACE THIS APP DOES NOT
    PRINT A LITERAL IT HAS NEVER HEARD OF. `NET_LINE_STATE` and
    `PUSH_LINE_STATE` print theirs raw on purpose ("no invented states" cuts both
    ways), and two things make this different:

    * `/system/lib` and this app are installed by SEPARATE steps
      (OWNER-DECISIONS #1), so a badge can carry a newer `network_runtime` than
      this table knows -- and a word from it is a string no lane has ever priced
      against the 308 px band or checked against the pre-baked glyph set. The
      loud degrade for that belongs in the SUITE, where the exhaustiveness test
      fails on a ninth cause, not on a wearer's panel.
    * this line is SECONDARY. Dropping it loses nothing the mode line above did
      not already say, whereas `NET_LINE_STATE` is the only line on its screen
      and dropping it would leave a blank one.

    Total, and never raises: every caller is on a draw path where a raise is
    `machine.reset()`.
    """
    if not isinstance(cause, str):
        return None
    return cause if cause in PUSH_CAUSES else None


def push_view(mode, library=True, controllable=False, enabled=None, cause=None,
              previous=None):
    """The Updates screen: what is happening, WHY, and the one question to answer.

    ``mode`` is READ BACK from the transport every time this is built — the
    owner's Card PW rule, and the reason there is no "pending" state here. The
    wearer's own preference (``enabled``) is a separate fact and is not allowed
    to describe the connection: a badge whose holder said YES but whose venue
    blocked push reads "The event turned this off for now", not "Instant".

    ``cause`` IS THE SECOND LINE AND IT IS WHY THIS SCREEN CHANGED. `trying` is
    one word for eight states, four permanent for the boot, so "Looking for a
    fast connection" was true of a healthy handshake AND of a badge that had
    stopped trying for the rest of the boot. The cause names which
    (`settings_copy.PUSH_CAUSE_LINES` has the vocabulary and the evidence). It is
    rendered for EVERY cause rather than for a chosen subset, so "no second line"
    keeps exactly one meaning: there is nothing to explain, because push is live
    or somebody turned it off, and the mode line already said so.

    ``previous`` IS THE SAME QUESTION ABOUT THE PAST, and it exists because this
    screen destroys its own most valuable answer: opening it calls
    `set_active(True)`, which grants the placement `cause` would have reported.
    See `Settings.push_cause_previous` and `settings_copy`'s past-line block.

    ORDER: what, then why, then why BEFORE, then the question. The question is
    last because `settings_view._draw_body` reserves a band for every line still
    to come, so the last line is the one guaranteed not to be squeezed out — and
    here the last line is the one the softkeys answer. The past line sits under
    the live one because a reader scans downward from now into then; reversed, the
    first thing on the screen would be a fact about a moment that has passed.
    """
    normalised = push_mode(mode)
    # NOT on a library-less badge: "The server refused this badge" under
    # "BadgeLink is not installed" would be two answers to one question, and such
    # a badge has no transport to have produced a cause anyway.
    named = push_cause(cause) if library else None
    # LATCH PRESENCE IS THE ANSWER TO "IS THERE ANYTHING TO EXPLAIN", AND THIS
    # LINE MUST NOT RE-DERIVE IT FROM THE LIVE CAUSE. It did until 2026-08-26
    # (`named is not None`), and that gate was wrong twice over.
    #
    # IT COLLAPSED TWO DIFFERENT NONES. `push_cause()` answers None both when
    # everything is fine and when the wearer killed the transport, and the runtime
    # already distinguishes them where it matters: a live join CLEARS the latch,
    # a switch-off KEEPS it, and since the switch-press capture the runtime
    # deliberately TAKES one at the moment networking goes off -- that press is
    # the last instant the answer exists, because `poll()` returns above
    # `_note_push_cause` once networking is off. That asymmetry is the runtime's
    # reviewed decision, so reading the latch and trusting it is the whole
    # contract; second-guessing it here threw the asymmetry away.
    #
    # AND IT MADE A LANDED FEATURE DEAD CODE. Composed with that capture, the gate
    # left the switch-captured value with ZERO READERS ON ANY PATH: networking off
    # means no live cause, so the gate suppressed the line, and pressing ON clears
    # the latch. In freeze-bound firmware.
    #
    # THE `push` CASE THE GATE ALSO CLAIMED TO GUARD IS UNREACHABLE ANYWAY: a
    # latch beside a working doorbell dies within a frame of the join
    # (`_note_push_cause`'s shift-before-clear), so the runtime has already made
    # it impossible.
    #
    # `!= named` STAYS, because a latch equal to the live cause explains nothing
    # twice: `Waiting for a good moment` / `Earlier: it was between tries` is one
    # fact wearing two sentences, which is the eight-states-one-word defect
    # inverted. With `named` None the comparison holds trivially, which is exactly
    # the switch-off screen this rule has to let through.
    #
    # NORMALISED THROUGH `push_cause` UNCONDITIONALLY, never compared raw: this
    # value crosses the same `/system/lib`-may-be-newer seam the live one does, so
    # an unrecognised word is DROPPED here exactly as it is there and no unpriced
    # string can reach the pre-baked glyph set one layer up. The `library` gate is
    # the live line's, for the same reason: a badge with no BadgeLink has no
    # transport to have produced a cause, past or present.
    was = push_cause(previous) if library else None
    if was == named:
        was = None
    lines = []
    if not library:
        lines.append(settings_copy.NET_NOT_INSTALLED)
    elif normalised == PUSH_UNKNOWN:
        lines.append(settings_copy.PUSH_LINE_STATE.format(mode))
    else:
        lines.append(_PUSH_LINES[normalised])
    if named is not None:
        lines.append(settings_copy.PUSH_CAUSE_LINES[named])
    if was is not None:
        lines.append(settings_copy.PUSH_WAS_LINES[was])
    middle = ""
    right = ""
    if library and controllable:
        # THE Q&A PATTERN (owner ruling, 2026-08-21): one plain question, and
        # B/C answer it. YES/NO rather than a state-dependent TURN ON/TURN OFF —
        # which is the label pair that overran the 68 px softkey box — and the
        # answers are idempotent, so a wearer who presses YES twice has not
        # toggled themselves off.
        lines.append(settings_copy.PUSH_QUESTION)
        middle = settings_copy.YES
        right = settings_copy.NO
    lines = [settings_copy.ascii_fold(line) for line in lines]
    return {
        "screen": PUSH,
        "title": settings_copy.PUSH_TITLE,
        "mode": normalised,
        "push_mode": mode,
        "push_enabled": enabled,
        # The NORMALISED cause, or None -- the raw one is deliberately NOT
        # published, because nothing may forward an unpriced word toward a
        # renderer, a log line or a browser assertion.
        "push_cause": named,
        # The normalised LATCHED cause, on the same terms, and None whenever the
        # line is not drawn -- so a browser assertion or a probe reading this
        # field sees exactly what the panel shows rather than what was available
        # to show. The raw latch is not published either, for the same reason.
        "push_cause_before": was,
        "reboot": False,
        "lines": lines,
        "softkeys": (settings_copy.BACK, middle, right),
    }


# -- the diagnostics screen --------------------------------------------------


def _flag(record, key):
    """A published bool as a word, or ``?`` when this build did not publish it.

    THREE ANSWERS AND NOT TWO. A missing key is a real case -- `/system/lib` and
    this app are installed by SEPARATE steps (OWNER-DECISIONS #1), and
    `PushLink.snapshot()` has a conditional block of its own -- so a field the
    badge never published must not read as `no`. That would be a measurement,
    and there is none.
    """
    value = record.get(key)
    if not isinstance(value, bool):
        return settings_copy.DIAG_MISSING
    return settings_copy.DIAG_YES if value else settings_copy.DIAG_NO


def _number(value, ceiling=None):
    """A counter as text, capped, or ``?``.

    CAPPED AND NEVER CLIPPED. Clipping 12345 to `1234` is a wrong number a
    reader would believe; `9999+` is a true statement about a value too wide for
    a 308 px band. The ceiling is reachable in the field rather than
    theoretical: an 800-badge fleet show is 799 suppressions on every badge, so
    `doorbells_filtered` passes four figures after about a dozen shows.

    `isinstance(value, bool)` IS EXCLUDED FIRST because `bool` is a subclass of
    `int` in both runtimes, and a `True` rendered as `1` in a counter column is
    the kind of wrong that reads as right.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return settings_copy.DIAG_MISSING
    if ceiling is None:
        ceiling = settings_copy.DIAG_COUNT_MAX
    if value > ceiling:
        return "{}+".format(ceiling)
    return str(value)


def _count(record, key, ceiling=None):
    """One counter out of the published record. See :func:`_number`."""
    return _number(record.get(key), ceiling)


def diag_text(value):
    """A runtime-supplied string, folded and bounded, ready to draw.

    THE TWO HAZARDS ARE DIFFERENT AND BOTH ARE REAL. The FOLD closes the
    alphabet: this app draws from a pre-baked 95-glyph set and `last_error` is
    `pushlink._error_text`'s "ClassName: message" built from an arbitrary
    exception, so an unrenderable code point becomes a visible `?` rather than
    nothing at all. The BOUND closes the width: the same string can be 160
    characters, and this screen has exactly eight bands for eight lines, so a
    line allowed to wrap takes a band from a line below it.

    `settings_copy.DIAG_TEXT_CHARS` is the bound and it is derived from the band
    -- see it. Total, and never raises: every caller is on a draw path where a
    raise is `machine.reset()`.
    """
    if value is None:
        return None
    text = settings_copy.ascii_fold(value)
    return text[:settings_copy.DIAG_TEXT_CHARS]


def diag_chunks(value, count):
    """A runtime string as up to ``count`` bare lines of ``DIAG_CHUNK_CHARS``.

    **THE ONE PLACE THIS APP SPENDS MORE THAN ONE BAND ON A RUNTIME STRING, AND
    PAGING IS WHAT MADE IT AFFORDABLE.** `DIAG_TEXT_CHARS`' 15-character clip is
    right for a PREFIXED line and wrong here: it turned
    `CredentialError: BADGELINK_HOST must be a bare hostname` into
    `CredentialError` and `OSError: [Errno 6] Device not configured` into
    `OSError: [Errn` -- losing, in both cases, the half that names the repair.
    Three chunks carry 60 characters and both survive.

    A HARD CHOP, NOT A WORD BREAK, and that is not laziness. The drawn character
    count must not depend on where a space happens to fall: `test_settings_fit`
    prices `W * DIAG_CHUNK_CHARS` whichever it is, and a chopper is TOTAL where
    a breaker has cases. `CredentialError: BAD` / `GELINK_HOST must b` reads
    fine mid-word and names the exact field.

    FOLDED FIRST, for `diag_text`'s reason: this app draws from a pre-baked
    95-glyph set and these strings are built from arbitrary exceptions, so an
    unrenderable code point becomes a visible `?` rather than nothing at all.

    Total, and never raises: every caller is on a draw path where a raise is
    `fatal_error` -> `machine.reset()`, every frame, for ever.
    """
    if value is None:
        return ()
    text = settings_copy.ascii_fold(value)
    if not text:
        return ()
    out = []
    step = settings_copy.DIAG_CHUNK_CHARS
    for index in range(count):
        piece = text[index * step:(index + 1) * step]
        if not piece:
            break
        out.append(piece)
    return tuple(out)


def diag_uid(value):
    """The hardware badge id, folded, and clipped at its OWN length.

    NOT :func:`diag_text`. That bound is 15 and a `machine.unique_id().hex()` is
    16, so it drops the last nibble -- of the one value on this badge somebody
    reads down a phone to match a row in a database. A clipped badge id is worse
    than no line at all. `settings_copy.DIAG_UID_CHARS` carries the arithmetic
    that says 16 fits the band with room to spare.
    """
    if not isinstance(value, str) or not value:
        return settings_copy.DIAG_MISSING
    text = settings_copy.ascii_fold(value)[:settings_copy.DIAG_UID_CHARS]
    return text if text else settings_copy.DIAG_MISSING


def _page_index(page, total):
    """A caller's page, clamped TOTALLY onto a page this build can draw.

    EVERY BUILDER CLAMPS RATHER THAN VALIDATES, because both run on a draw path
    where a raise is `fatal_error` -> `machine.reset()`. A `-1`, a `"3"`, a
    `True` and a `99` all land on a drawable page instead of resetting a badge
    whose only repair channel is the screen being drawn.

    `isinstance(page, bool)` IS EXCLUDED FIRST for `_number`'s reason: `bool` is
    a subclass of `int` in both runtimes, so `True` would otherwise resolve to
    page 2 rather than to the answer page.
    """
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        page = 0
    return page % total


def _chunk_band(lines, label, value, count, missing):
    """A bare label, then ``value`` across up to ``count`` bare bands.

    ONE SHAPE FOR ALL FOUR CHUNKED BLOCKS -- both network errors, the push error
    and the firmware build -- so the "absent" answer cannot drift between them.

    **THE LABEL IS ALWAYS DRAWN, INCLUDING WHEN THE VALUE IS ABSENT**, and that
    is a deliberate departure from the first draft of this design, which
    replaced the whole block with one bare sentence. The Network error page
    carries TWO of these blocks, so that draft put two byte-identical
    `No error recorded` lines one under the other with nothing to say which
    error each was about. The label costs one band on a page with three to
    spare; an unreadable page costs the venue an answer.
    """
    lines.append(label)
    pieces = diag_chunks(value, count)
    if pieces:
        for piece in pieces:
            lines.append(piece)
    else:
        lines.append(missing)
    return lines


def clock_line(clock):
    """The clock readout, or ``None`` when the runtime published no record.

    A FORMATTER AND NOT A MACHINE, exactly like every other line on this screen:
    `plausible`, `synced` and `reason` are all
    `network_runtime.NetworkService.clock_diagnostics()`'s, which is itself a
    projection of `NetworkService._epoch()`'s existing gate and
    `DeviceBackend`'s existing latches. Nothing here reads a clock, evaluates an
    epoch or decides what is plausible -- doing any of that in the view would put
    a SECOND plausibility rule on the badge, and the whole value of the line is
    that it reports the one the TLS path actually uses.

    THE SECOND SLOT PREFERS THE REASON, and that is not a fallback order -- it is
    the more specific answer. `clock_boot.resync` says `reason: "synced"` on
    success and a skip reason otherwise, so a reason in that slot already means
    the sync did not land, and spending the slot on `sync no` beside it would
    cost 4 characters of `DIAG_TEXT_CHARS` to repeat something.
    """
    if not isinstance(clock, dict) or not clock:
        return None
    reason = diag_text(clock.get("reason"))
    synced = clock.get("synced")
    if not isinstance(synced, bool):
        tail = settings_copy.DIAG_CLOCK_UNKNOWN
    elif synced:
        # A LANDED SYNC OUTRANKS ITS OWN REASON. The reason is the literal
        # `synced` here, which is a protocol word where the screen wants a
        # verdict -- and `synced` is a BOOT latch while `reason` is the LAST
        # outcome, so a badge that synced and later skipped still reads
        # `sync yes`. That is the honest reading: the clock has been checked
        # against a server, whatever the most recent attempt did.
        tail = settings_copy.DIAG_CLOCK_SYNCED
    else:
        tail = reason if reason else settings_copy.DIAG_CLOCK_NO_SYNC
    return settings_copy.DIAG_LINE_CLOCK.format(_flag(clock, "plausible"), tail)


#: HOW LONG THE SWEEP TAKES TO CROSS THE PANEL ONCE.
#:
#: THE ELEMENT IS THE INSTRUMENT, NOT DECORATION. A number that has STOPPED
#: updating and a number updating SLOWLY look identical at a glance -- that is
#: how a 701 ms network stall sat unnoticed under a meter reporting `worst=58
#: ms` -- so the screen carries something whose speed is a constant of WALL TIME
#: rather than of frames. The comet advances by elapsed milliseconds, so a
#: healthy badge shows smooth motion, a badge at half rate shows the same speed
#: in visibly coarser steps, and a stalled badge shows the comet standing still
#: and then JUMPING. None of those three is mistakable for another.
#:
#: 1500 ms, and the number is bounded at both ends by what an eye can read. At
#: the measured 23 ms Settings frame the comet moves about 5 px per frame, which
#: reads as motion rather than as a flicker; a 700 ms stall moves it about
#: 144 px, which is nearly half the panel and unmissable. Much faster and a
#: healthy frame becomes a jump too; much slower and a dropped frame stops being
#: visible at all.
#:
#: **IT ALSO HAS TO STAY DIVISIBLE BY `settings_view._SWEEP_DIVISIONS`.** The
#: track carries graduations so a jump can be MEASURED and not merely noticed,
#: and at six divisions 1500 ms is six whole quarter-seconds. A period that made
#: a division 187.5 ms would still draw correctly and would be countable by
#: nobody. The view owns the geometry; this is the constraint it depends on.
SWEEP_PERIOD_MS = 1500


class FrameHealth:
    """Entry-to-entry frame timing: a latched worst, and a constant-rate phase.

    **IT TIMES ENTRY TO ENTRY, NOT THE WORK IN BETWEEN, AND THAT IS THE WHOLE
    POINT.** `benchmark/badge/stutter_meter.py` timed its own `update()` and
    said so in its first eight lines: the networking runs in `service.poll()`,
    which `managed_update` calls AFTER the app's callback returns, so every
    network stall was outside every number on its screen. It reported
    `worst=58 ms` in the same capture whose telemetry showed a 701 ms network
    frame. Measuring the gap between two ENTRIES puts the poll, the present and
    everything else the frame actually costs inside the number.

    **AND IT MUST NOT BECOME THE THING IT MEASURES.** Three rules, each with a
    measured failure behind it:

    * NO ALLOCATION. :meth:`tick` is integer arithmetic on preallocated
      attributes and builds nothing -- no tuple, no dict, no string. The
      readout string is composed by :func:`diag_view` from `worst_ms`, and
      `worst_ms` changes only when a frame is the worst so far, which is rare
      by construction.
    * NO `print`, ANYWHERE ON THIS PATH. A `print` into a USB CDC that no host
      is draining stalls the frame: the blocked-CDC arm measured 192 gaps in
      485 s with a modal stalled frame of 1,018 ms and a worst of 3,032 ms,
      against ZERO gaps on the same desk with the cable plugged in
      (`benchmark/results/raw/2026-08-27-usb-cdc-print-blocking/`). That the
      cost is per-CALL is INFERRED there and not measured; the gap is measured.
    * NO FLASH WRITE ON A PER-EVENT PATH. A probe that flushed one LittleFS
      write per logged line turned 600 frames / 2 gaps in 27 s into 1,200
      frames / 1,199 gaps in 183 s -- the frame rate fell about 7x and the gap
      count rose about 100x, self-amplifying, because every logged gap caused
      the next one
      (`benchmark/results/raw/2026-08-27-untethered-walk/`). This class holds
      RAM only and there is nowhere for it to write.

    IT TICKS ON EVERY SCREEN, NOT ONLY ITS OWN, and that is deliberate: the
    stalls worth catching happen while the wearer is on Network or Updates,
    where the runtime is allowed to establish. A meter that only counted while
    somebody was looking at it would miss exactly the frame they came to
    explain.
    """

    def __init__(self, period_ms=SWEEP_PERIOD_MS):
        #: The worst entry-to-entry gap seen since the last reset, in ms.
        self.worst_ms = 0
        #: Where the sweep is in its cycle, in ms. Never a pixel: this module
        #: owns no geometry and `settings_view` owns no decisions.
        self.phase_ms = 0
        #: Entries counted. THE FIRST ONE IS NOT A FRAME -- the gap in front of
        #: it runs back to module construction, which is a different quantity
        #: and a large one -- so `tick` records it and refuses to latch it.
        self.frames = 0
        #: PUBLIC, because `diag_view` publishes it and `settings_view` divides
        #: by it. A private name here would be a private read there, which is
        #: the shape a reviewer cannot tell from a leak.
        self.period_ms = period_ms if period_ms > 0 else SWEEP_PERIOD_MS

    def tick(self, elapsed_ms):
        """One frame entry. Allocation-free; returns nothing that allocates.

        `elapsed_ms` is `settings/__init__.py`'s own `time.ticks_diff(now,
        _last_ms)` taken at the TOP of `update()`, which is already the
        entry-to-entry quantity -- the seam computes it for the sleep note, so
        this reads a number that was going to exist anyway rather than starting
        a second clock.
        """
        if (isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, int)
                or elapsed_ms < 0):
            # A hostile or absent delta may not poison a latch that has no other
            # way to be corrected. Not reachable from the seam, which passes
            # `ticks_diff`; reachable from a fixture, and from a runtime whose
            # tick counter wrapped -- `ticks_diff` is SIGNED and negative across
            # a wrap, and a negative worst frame is not a thing.
            #
            # `bool` IS EXCLUDED FIRST because it is a subclass of `int` in both
            # runtimes: without this line a `True` becomes the latched worst
            # frame and the panel reads `Worst frame True ms`.
            return None
        self.phase_ms += elapsed_ms
        if self.phase_ms >= self.period_ms:
            # `%` rather than a subtract loop: one operation whatever the size
            # of the stall, so the frame AFTER a 3,032 ms gap is not itself slow.
            self.phase_ms = self.phase_ms % self.period_ms
        self.frames += 1
        if self.frames > 1 and elapsed_ms > self.worst_ms:
            self.worst_ms = elapsed_ms
        return None

    def reset(self):
        """Drop the latch and start the measurement again.

        THE SWEEP PHASE IS DELIBERATELY NOT RESET. The bar is a clock, not a
        result: restarting it would make the one element on the screen that is
        supposed to be continuous jump for a reason unrelated to frame health.
        `frames` goes back to zero for the same reason it starts there -- the
        gap across the press is a real frame, but the NEXT one is the first of
        the new measurement and its predecessor belongs to the old one.
        """
        self.worst_ms = 0
        self.frames = 0
        return None

    @property
    def measured(self):
        """True once two entries have been seen, so a worst frame exists."""
        return self.frames > 1


#: `network_runtime.FAULT_SUB_IS_A_BADGE`, spelled here rather than imported,
#: exactly as the six transport states and the eight push causes above are: this
#: module stays pure and CPython-testable on a machine with no `/system/lib`,
#: and `test_settings_seam.py` is the drift detector that makes the copy safe.
FAULT_SHARED_SUB = "shared_sub_is_this_badge"


def _clock_implausible(clock):
    """The clock verdict published as FALSE -- which is not the same as absent.

    `is False` AND NOT `not`, and the difference is a whole class of wrong
    warning. A `/system/lib` that publishes a half-record has no `plausible` key
    at all, and `record.get` answers None for it; warning on that would be
    `_flag`'s exact mistake -- a field the badge never published reading as a
    fault, which is a measurement nobody took.
    """
    return isinstance(clock, dict) and clock.get("plausible") is False


def _diag_health(lines, warn, diagnostics, clock, worst_ms, measured):
    """PAGE 1: is this badge working.

    **THE CLOCK LINE IS ON PAGE 1 AND IS NEVER AGAIN DROPPABLE.** Before paging,
    it and `Last error` both wanted the eighth band and the error kept it -- so
    the fleet-brick state had no line at all on the badge it bricks. A venue
    that blocks UDP/123 means no plausible clock, so `clock_boot.resync` RAISES
    rather than failing soft, so `_build_loop` never finishes, so there is no
    `PollLoop` and no doorbell -- and `No push details on this badge`, the
    sentence an IDLE badge draws, was the only thing this screen could say about
    it. Paging dissolved that contention outright: the error moved to page 3
    with four bands of its own.

    IT IS ALSO THE ONE LINE HERE THAT EARNS WARNING INK. See `warn_lines` in
    :func:`diag_view` for the rule: a line is WARN when, and only when, it names
    a state the badge cannot leave without help.
    """
    record = (diagnostics if isinstance(diagnostics, dict) and diagnostics
              else None)
    if record is not None:
        mode = diag_text(record.get("mode"))
        lines.append(settings_copy.DIAG_LINE_MODE.format(
            mode if mode else settings_copy.DIAG_MISSING))
    clock_text = clock_line(clock)
    if _clock_implausible(clock):
        # BY INDEX, BECAUSE THIS LINE'S TEXT IS A RUNTIME LITERAL. No copy
        # constant can identify `Clock no  ntp_rejected: b`, and a prefix sniff
        # on a draw path would silently re-ink any future line that matched it.
        warn.append(len(lines))
    lines.append(clock_text if clock_text is not None
                 else settings_copy.DIAG_NO_CLOCK)
    if record is not None:
        lines.append(settings_copy.DIAG_LINE_LINK.format(
            _flag(record, "joined"), _flag(record, "socket_open"),
            _flag(record, "targeted")))
    _diag_frame(lines, worst_ms, measured)
    return lines


def _diag_frame(lines, worst_ms, measured):
    """The latched worst frame. LAST ON ITS PAGE, and on EVERY badge.

    Last because the moving rail underneath belongs to it -- the latch says a
    stall happened and the comet says how big THIS one was -- and because
    `_draw_body` reserves a band for every line still to come, so the last line
    is the one guaranteed not to be squeezed out.

    IT IS THE ONE READING THAT SURVIVES `NET_NOT_INSTALLED`, which is the whole
    argument for the Diagnostics row being unconditional: every badge has a
    panel, whatever is or is not in `/system/lib`.
    """
    if measured:
        lines.append(settings_copy.DIAG_LINE_WORST.format(_number(worst_ms)))
    else:
        lines.append(settings_copy.DIAG_LINE_WORST_NONE)
    return lines


def _diag_doorbell(lines, diagnostics):
    """PAGE 2: the doorbell's numbers. NOT ONE CHARACTER OF THIS CHANGED.

    It moved as a unit from the single-page screen, and the three 2026-08-27
    incidents that forced each line are in `settings_copy`'s diagnostics block.
    `DIAG_NO_PUSH` lives HERE and on no other page, which is the single largest
    correctness win of the split -- see :func:`_diag_health`.
    """
    if not isinstance(diagnostics, dict) or not diagnostics:
        lines.append(settings_copy.DIAG_NO_PUSH)
        return lines
    record = diagnostics
    source = record.get("policy_source")
    line = settings_copy.DIAG_POLICY_LINES.get(source)
    if line is None:
        # A source literal this build has never heard of, printed rather than
        # smoothed over -- and bounded, because it crosses the same
        # newer-`/system/lib` seam every other runtime string here does.
        bounded = diag_text(source)
        line = settings_copy.DIAG_POLICY_STATE.format(
            bounded if bounded else settings_copy.DIAG_MISSING)
    lines.append(line)
    lines.append(settings_copy.DIAG_LINE_SESSIONS.format(
        _count(record, "sessions_joined"),
        _count(record, "sessions_failed"),
        _count(record, "failed_sessions", settings_copy.DIAG_SMALL_MAX),
        _count(record, "demote_after", settings_copy.DIAG_SMALL_MAX)))
    lines.append(settings_copy.DIAG_LINE_BELLS.format(
        _count(record, "doorbells"), _count(record, "doorbells_filtered"),
        # LAYER 2's COUNTER, ON LAYER 3's LINE, because it answers the same
        # question one step further out: `Bells`/`other` count broadcasts
        # that REACHED the doorbell, and this counts opcode-2 frames the
        # decoder refused, which reach nothing. A live `0x04` UserBroadcast
        # was captured on the wire on 2026-08-28 while the badge read
        # `Bells 0  other 0`, so the two are no longer enough on their own.
        # Lifted out of the nested layer-2 record by
        # `network_runtime.PUSH_DIAGNOSTIC_CLIENT_KEYS`; absent -- and so
        # `?` -- on a badge that has never opened a socket.
        _count(record, "binary_frames_ignored")))
    lines.append(settings_copy.DIAG_LINE_FLAGS.format(
        _flag(record, "demoted"), _flag(record, "push_revoked")))
    return lines


def _diag_error(lines, diagnostics, cause, previous):
    """PAGE 3: the last error, with the room it never had.

    `OSError: [Errno 6] Device not configured` is forty characters. The retired
    `DIAG_LINE_ERROR` drew `Last error: OSError: [Errn` and the errno -- the
    half that identifies it -- was gone. Here it survives across two chunks.

    THE TWO CAUSE LINES BELONG ON AN OPERATOR'S SCREEN TOO, and the second one
    especially: `push_cause_previous` is the accessor that exists BECAUSE
    READING DESTROYS THE ANSWER. `settings/__init__.py` calls `set_active(True)`
    while this tile is open, which GRANTS the placement `push_cause()` would
    have reported -- the mechanism that hid the 2026-08-26 doorbell root cause
    for a whole session.

    EACH CAUSE LINE IS DRAWN ONLY WHEN THERE IS ONE. A latch that expires
    between two frames costs no layout shift; the block below simply moves up a
    band, exactly as it does on the Updates screen.
    """
    bounded = diag_text(cause)
    if bounded:
        lines.append(settings_copy.DIAG_LINE_CAUSE.format(bounded))
    bounded = diag_text(previous)
    if bounded:
        lines.append(settings_copy.DIAG_LINE_WAS.format(bounded))
    error = (diagnostics.get("last_error")
             if isinstance(diagnostics, dict) else None)
    _chunk_band(lines, settings_copy.DIAG_LABEL_ERROR, error, 3,
                settings_copy.DIAG_NO_ERROR)
    return lines


def _diag_identity(lines, warn, identity):
    """PAGE 4: this badge.

    Every value here is posted to the server on EVERY heartbeat and none of them
    could be read off the badge in the hand -- the wrong way round for the one
    day when the server is what nobody can reach.

    ⚠ `Badge {}` CARRIES THE HARDWARE UID AND NOT THE JWT SUBJECT. On the
    shared-token fleet every badge ships a byte-identical `/secrets.py`, so the
    subject is the same value on all ~200 and names the FLEET; `Token {}` is
    what makes it useful anyway, because `fleet` / `per_badge` answers the S0.8
    rollout question nothing on the wire could. Neither is secret: a JWT `sub`
    is a public claim and nothing is authorised by knowing it.

    THE LAST LINE IS A PROMISE FINALLY KEPT. `provisioning_fault`'s own
    docstring says the badge "says why on serial and in Settings"; the Settings
    half was never written, and this is the one state in which the badge refuses
    to network for the life of the firmware -- `DeviceBackend.poll` returns
    DISCONNECTED above every path that opens or arms a socket. It is WARN ink
    because nothing but re-provisioning moves it.
    """
    if not isinstance(identity, dict):
        lines.append(settings_copy.DIAG_NO_ID)
        return lines
    lines.append(settings_copy.DIAG_LINE_BADGE.format(
        diag_uid(identity.get("uid"))))
    lines.append(settings_copy.DIAG_LINE_TOKEN.format(
        _literal(identity.get("token"))))
    lines.append(settings_copy.DIAG_LINE_BOOT.format(
        _literal(identity.get("boot"))))
    _chunk_band(lines, settings_copy.DIAG_LABEL_BUILD, identity.get("build"), 2,
                settings_copy.DIAG_MISSING)
    fault = identity.get("fault")
    if isinstance(fault, str) and fault:
        if fault == FAULT_SHARED_SUB:
            text = settings_copy.DIAG_FAULT_SHARED_SUB
        else:
            # A FAULT WORD FROM A `/system/lib` NEWER THAN THIS APP, drawn RAW
            # rather than dropped. The whole point of this line is that a badge
            # which will never network says so; a fault this build cannot name
            # is still a fault, and silence is the defect being closed.
            pieces = diag_chunks(fault, 1)
            text = pieces[0] if pieces else settings_copy.DIAG_MISSING
        warn.append(len(lines))
        lines.append(text)
    return lines


def scores_drain_line(scores):
    """WHY THE SPOOL IS NOT MOVING, in one sentence, or the healthy reading.

    A FORMATTER AND NOT A MACHINE, which is this screen's rule. It decides
    nothing about the drain: `scores_stalled` is `_pump_scores`' own latched
    word and `scores_pending` is `scorebox.pending`'s own count, and this
    chooses a sentence for the pair. Deriving "is it stalled" here would put a
    SECOND stall rule on the badge that could disagree with the one that
    actually gates the post.

    ⚠ **`None` IS "NOT STALLED" AND IS NOT ABSENCE.** `_pump_scores` clears
    `_score_stall` the moment a frame gets past every guard, so `None` beside a
    pending count is a drain that IS running -- which is a different sentence
    from a drain with nothing to do. Reading it as "no measurement" would draw
    `?` at the operator whose actual question is "is it moving".

    A WORD FROM A NEWER `/system/lib` IS DRAWN RAW rather than smoothed over,
    for `wifi_reason_line`'s reason: "no invented states" cuts both ways, and a
    stall this build cannot name is still a stall.
    """
    reason = scores.get("scores_stalled")
    if isinstance(reason, str) and reason:
        line = settings_copy.DIAG_SCORES_STALL_LINES.get(reason)
        if line is not None:
            return line
        bounded = diag_text(reason)
        return settings_copy.DIAG_SCORES_STATE.format(
            bounded if bounded else settings_copy.DIAG_MISSING)
    pending = scores.get("scores_pending")
    if isinstance(pending, int) and not isinstance(pending, bool) and pending > 0:
        return settings_copy.DIAG_SCORES_SENDING
    # NOTHING PENDING, OR NO COUNT AT ALL. The second case reads as idle rather
    # than as `?` on purpose: an unstalled drain with an unpublished count is a
    # badge whose runtime is older than `scores_pending`, and "nothing waiting"
    # is what such a badge's drain is in fact doing between posts.
    return settings_copy.DIAG_SCORES_IDLE


def _diag_scores(lines, scores):
    """PAGE 5: is the wearer's score going anywhere.

    **THE DEFECT IS THE RUNTIME'S OWN, RECORDED IN ITS OWN WORDS.**
    `_pump_scores`: *"five real scores sat on the owner's badge for a whole boot
    while the heartbeat and the settings read kept working, and nothing anywhere
    said the drain had stopped."* Every guard in that method returned None in
    silence, because it runs on every rendered frame.

    `_score_stalled` closed the SERIAL half on 2026-08-29 by latching the word
    so it prints once per transition -- and the runtime says what that leaves
    open: *"an operator who attaches serial afterwards sees nothing at all;
    these two are the pull-based form of the same answer."* On 2026-10-02 nobody
    attaches serial, so the transition print reaches no one and the latch is the
    only copy of the answer there is. This page is the reader it never had.

    TWO LINES AND NOT MORE, AND THE SHORT PAGE IS THE POINT. The count and the
    reason are the whole question; padding it with the counters the other pages
    already carry would make an operator read four lines to find two.
    """
    if not isinstance(scores, dict) or not scores:
        # THE ACCESSOR IS ABSENT -- no network controller, or a `/system/lib`
        # older than it -- said in words rather than as two rows of `?`, which
        # is `DIAG_NO_PUSH`'s doctrine: "this badge cannot tell you" is a fact
        # about the runtime and a `?` reads as a fact about the drain.
        lines.append(settings_copy.DIAG_NO_SCORES)
        return lines
    lines.append(settings_copy.DIAG_LINE_SCORES_WAITING.format(
        _number(scores.get("scores_pending"))))
    lines.append(scores_drain_line(scores))
    return lines


def diag_view(diagnostics, library=True, worst_ms=None, measured=False,
              sweep_ms=0, sweep_period_ms=SWEEP_PERIOD_MS, clock=None,
              page=0, cause=None, previous=None, identity=None, scores=None):
    """The operator's screen: what push is doing, the clock, and the frames.

    THE DESIGN RULE, and it is the reason this function is a formatter and not a
    machine: SURFACE WHAT THE RUNTIME ALREADY COMPUTES. Every push value here
    comes out of `PushLink.snapshot()` by way of
    `network_runtime.NetworkService.push_diagnostics()`; nothing on this path
    counts, derives or stores anything. The three 2026-08-27 incidents that
    forced the screen are in `settings_copy`'s diagnostics block, one per line
    of this body.

    IT DEGRADES IN TWO STEPS AND THEY MEAN DIFFERENT THINGS. No `/system/lib`
    says so with the tile's existing `NET_NOT_INSTALLED`, on every page -- that
    is no longer the common badge (`apps-roster.json` carries `ship: true` on
    the owner's 2026-08-28 ruling, reversing the 2026-08-24 one this docstring
    used to cite) but it is still a real one, and it is what a badge flashed
    with apps and no library draws. A library that is present but has no
    doorbell -- no push factory, or a runtime older than the accessor -- says
    `DIAG_NO_PUSH`, because "this badge cannot tell you" is a different fact
    from "BadgeLink is not installed" and both are different from a row of
    zeroes, which would be a measurement nobody took.

    THE FRAME LINES SURVIVE BOTH, because they are about the panel and every
    badge has one. That asymmetry is the whole reason the row is unconditional.

    **`DIAG_NO_PUSH` IS ON PAGE 2 AND ON NO OTHER PAGE, WHICH IS THE SINGLE
    LARGEST CORRECTNESS WIN OF THE SPLIT.** A badge with no plausible clock
    cannot finish `_build_loop`, so it never gets a doorbell -- so before
    paging, "no push details" was the ONLY thing this whole screen could say
    about a bricked fleet, and it was the same sentence an idle badge drew.
    Pages 1, 3 and 4 now keep drawing: the clock verdict, the two cause lines
    and the identity block need no push record at all.

    THE CLOCK LINE DOES NOT SURVIVE `NET_NOT_INSTALLED`, and that is the half a
    frame-line argument would get wrong: every badge has a panel, so the sweep
    is measurable with no library at all, whereas "plausible" is
    `clock_boot.evaluate_ntp`'s verdict and `clock_boot` lives in
    `/system/lib`. This app could read `time.time()` on any badge, but the raw
    epoch is not the fact anybody needs, and deciding plausibility HERE would be
    a second gate that could disagree with the one the TLS path applies. So:
    absent with no library, present without a doorbell, and never invented.

    ORDER, ACROSS FIVE PAGES SINCE 2026-08-29: is this badge working, what the
    doorbell heard, what broke, who this badge is, and whether the wearer's
    scores are going anywhere. The frame readout is LAST
    on page 1 because it is the one the moving bar underneath it belongs to, and
    because `settings_view._draw_body` reserves a band for every line still to
    come -- so the last line is the one guaranteed not to be squeezed out.

    **THE BAND BUDGET IS NO LONGER SPENT, AND THAT PARAGRAPH HAS BEEN REPLACED
    RATHER THAN LEFT STANDING.** This docstring used to record that the clock
    line and `Last error` both wanted the eighth band and that the error kept
    it -- with `clock_band`, and a `clock_band = False` inside the error branch,
    to enforce it. All three are DELETED. The owner's 2026-08-28 ruling
    (*"Scrolling is absolutely fine. The more information, the better."*) made
    paging legal, the error moved to page 3 with four bands of its own, and the
    clock line -- the FLEET-BRICK line -- is on page 1 and can no longer lose a
    band to anything. A rule that is no longer true is worse than no rule.

    **THE SWEEP IS ON EVERY PAGE.** `sweep` and `sweep_period` are published by
    all four, so `_draw_page` reserves the rail band and passes the same floor
    on every one. The comet is the one element whose whole job is to be visible
    while something ELSE is being read; a page that dropped it would be the
    2026-08-27 defect again -- a number that has stopped and a number updating
    slowly look identical. `FrameHealth.tick` already runs on every screen, so
    nothing about the measurement changes.

    ``page``, ``cause``, ``previous``, ``identity`` and ``scores`` all default
    to the values a caller that has never heard of paging produces, so every
    existing fixture and test builds page 1 unchanged.

    **PAGE 5 IS THE SCORE DRAIN, AND IT CLOSES THE LAST "COMPUTED AND NEVER
    READ" PAIR IN THIS AREA.** `scores_pending` and `scores_stalled` are what
    `network_runtime._pump_scores` calls "the pull-based form" of a serial line
    that is only ever printed on a TRANSITION -- so an operator who was not
    tethered at the moment the drain stopped had no way to learn it had. See
    :func:`_diag_scores`.
    """
    page = _page_index(page, DIAG_PAGES)
    lines = []
    #: WHICH LINES ARE WARNINGS, AS INDICES. See the `warn_lines` key below.
    warn = []
    if not library:
        # NO `/system/lib`, on every page. Not a row of `?`: `?` is the absence
        # of a MEASUREMENT, and this is the absence of a module.
        lines.append(settings_copy.NET_NOT_INSTALLED)
        # **AND THE FRAME READOUT SURVIVES IT, ON PAGE 1, WHICH IS THE WHOLE
        # ARGUMENT FOR AN UNCONDITIONAL ROW.** The sweep is about the PANEL and
        # every badge has one, so a badge with no networking library still has
        # to be able to answer "is this thing dropping frames". Page 1 is where
        # it lives on every other badge too, so an operator is not told to turn
        # to a different page depending on what is installed.
        if page == 0:
            _diag_frame(lines, worst_ms, measured)
    elif page == 0:
        _diag_health(lines, warn, diagnostics, clock, worst_ms, measured)
    elif page == 1:
        _diag_doorbell(lines, diagnostics)
    elif page == 2:
        _diag_error(lines, diagnostics, cause, previous)
    elif page == 3:
        _diag_identity(lines, warn, identity)
    else:
        _diag_scores(lines, scores)
    lines = [settings_copy.ascii_fold(line) for line in lines]
    return {
        "screen": DIAG,
        "title": settings_copy.PAGE_TITLE.format(
            settings_copy.DIAG_TITLE, page + 1, DIAG_PAGES),
        "reboot": False,
        "page": page,
        "pages": DIAG_PAGES,
        "lines": lines,
        # **A LINE IS WARN WHEN, AND ONLY WHEN, IT NAMES A STATE THE BADGE
        # CANNOT LEAVE WITHOUT HELP.** Warning ink that appears on every unhappy
        # screen stops meaning anything, and this badge is unhappy in a dozen
        # ordinary, recoverable ways. Two lines qualify here -- an implausible
        # clock (no `PollLoop` is ever built, so the badge will never connect
        # and nobody would guess why) and the provisioning fault (`poll` returns
        # DISCONNECTED above every path that opens a socket, for the life of the
        # firmware). Every counter, every stage and every error chunk stays DIM.
        #
        # A TUPLE OF SMALL INTEGERS, NEVER A SEVERITY WORD OR A PER-LINE DICT.
        # This model is rebuilt every frame by construction (the sweep phase
        # moves), so a second vocabulary on the draw path would allocate ~37
        # times a second on the one screen whose job is to cost nothing. This
        # allocates one tuple, exactly as `accent_lines` already does, and it is
        # usually empty.
        "warn_lines": tuple(warn),
        # THE PHASE, NOT A PIXEL. `settings_view` maps it onto the rail, so the
        # geometry stays where every other geometry decision in this tile is and
        # this module stays drawable on any canvas.
        "sweep": sweep_ms,
        "sweep_period": sweep_period_ms,
        # B DRAWS NOTHING AND DOES NOTHING. Everything on this screen is a
        # reading; the only command is the one that restarts the reading, and it
        # goes on C rather than on the key a thumb has been opening rows with.
        "softkeys": (settings_copy.BACK, "", settings_copy.DIAG_RESET),
    }


def bright_view(percent):
    """The ladder, as this app's page: a title, one line and a three-key bar.

    THE BAR IS `identity`'s D2 SHAPE AND IT IS A DECLARED DEVIATION HERE.
    A is one rung DOWN, C is one rung UP, and B carries the way back -- so A is
    NOT the labelled retreat on this one screen, which is the only place in this
    tile that is true. `docs/badge-button-rules.md` §9.2(b) is the rule being
    followed rather than broken: brightness is an ordered ladder, I1 puts the
    low end on A and the high end on C, and B2 explicitly allows B to carry the
    way out when A is a direction. The alternative -- keeping A as BACK and
    putting the two directions on B and C -- would have made the SAME wearer
    press different keys for the same control they met in `setup` the day
    before, to buy back a retreat that B already provides.

    WHAT BOUNDS THE DEVIATION, and each half is a test rather than a promise:
    the ladder CLAMPS, so a blind run of A stops at the lowest OFFERED level and
    can never turn the panel off (which is the trap the floor exists to close);
    and every change reverses with one press of the opposite key.

    EVERY LABEL NAMES THE VALUE THE PRESS WILL PRODUCE rather than a direction.
    The wearer reads the outcome before pressing, which a direction arrow could
    not offer -- and a key at the end of its ladder can do nothing, so it draws
    NOTHING and its event is empty. An empty slot is already this app's word for
    an inert key, and I5 forbids a label over a key that cannot act.
    """
    percent = backlight.clamp(percent)
    down = backlight.step(percent, -1)
    up = backlight.step(percent, 1)
    return {
        "screen": BRIGHT,
        "title": settings_copy.BRIGHT_TITLE,
        "brightness": percent,
        "reboot": False,
        "lines": [settings_copy.ascii_fold(settings_copy.bright_line(percent))],
        "softkeys": ("" if down == percent else backlight.name(down),
                     settings_copy.BACK,
                     "" if up == percent else backlight.name(up)),
    }


def scores_view(result=None):
    """The one destructive question in this tile, and afterwards its answer.

    B7'S SHAPE, AND EVERY PART OF THE BAR IS THE RULE RATHER THAN A CHOICE:
    ``KEEP`` on A commits nothing, the verb is on C, and **B DRAWS NOTHING AND
    DOES NOTHING**. B is the primary action on every other screen in this app, so
    a thumb that has been opening rows with it all afternoon must not be able to
    erase a wearer's scores with a press it started before it read the question.
    An empty slot is already this app's word for an inert key (I5).

    THE QUESTION NAMES ITS WHOLE SCOPE, BOTH WAYS. Four lines: what goes (every
    game's high score, and the scores still waiting to be sent), what this cannot
    reach (a score already on the leaderboard -- that row is in a database and
    only SQL can remove it), and what survives (the badge and the wifi). The
    scope is the ruling: the wearer is PRESENT, which is exactly what makes taking
    both kinds of score data defensible here and not from a fleet command.

    ``result`` IS THE SCREEN AFTERWARDS, and the failure arm is why it exists at
    all. A rewrite can fail on a full volume, and a wearer who walked away
    believing their scores were gone would be wrong in the one direction nothing
    later can correct. ``None`` is the question, ``True`` erased everything it
    tried, ``False`` did not -- partly counts as ``False``, because "some of your
    scores are still here" is the only honest reading of a partial wipe.
    """
    if result is None:
        return {
            "screen": SCORES,
            "title": settings_copy.SCORES_TITLE,
            "reboot": False,
            "lines": [settings_copy.ascii_fold(line) for line in (
                settings_copy.SCORES_LINE_CLEARS,
                settings_copy.SCORES_LINE_SPOOL,
                settings_copy.SCORES_LINE_SENT,
                settings_copy.SCORES_LINE_KEEPS)],
            "softkeys": (settings_copy.KEEP, "", settings_copy.ERASE),
        }
    return {
        "screen": SCORES,
        "title": (settings_copy.SCORES_DONE_TITLE if result
                  else settings_copy.SCORES_FAILED_TITLE),
        "reboot": False,
        "lines": [settings_copy.ascii_fold(
            settings_copy.SCORES_DONE_LINE if result
            else settings_copy.SCORES_FAILED_LINE)],
        # NO VERB LEFT ON C. The question has been answered, and a second ERASE
        # over a result the wearer has just read is a press with no question
        # above it.
        "softkeys": (settings_copy.BACK, "", ""),
    }


def sleep_view():
    """The one-second note, and the last thing on the panel before it goes dark.

    NO SOFTKEYS AT ALL, which is the same mechanical trick D1 uses on the worn
    badge: with every label empty there is no command for a waking press to
    fire, and here nothing can be pressed anyway. An empty slot is already this
    app's word for an inert key.

    `reboot: False` -- the field is the Pair screen's "restart to try again"
    flag, and this screen's own restart line is copy rather than a state.
    """
    return {
        "screen": SLEEP,
        "title": settings_copy.SLEEP_TITLE,
        "reboot": False,
        "lines": [settings_copy.ascii_fold(settings_copy.SLEEP_LINE_WAKE),
                  settings_copy.ascii_fold(settings_copy.SLEEP_LINE_RESTART)],
        "softkeys": ("", "", ""),
    }


# -- setting the clock by hand ----------------------------------------------
#
# **THE BOUNDS ARE `clock_boot`'S AND THIS MODULE KEEPS ITS OWN COPY OF THEM.**
# The precedent and the argument are `GAME_SCORE_PATHS`': that constant duplicates
# `scorebox.GAME_STATE_PATHS` because a wearer erasing their own high scores must
# not need a networking library to do it, and `settings/tests` pins the copy
# against the original so it cannot drift silently.
#
# The same holds here, harder. `clock_boot` lives in `/system/lib`, which
# production requires but installs separately, and the model is I/O-free by
# contract and imports nothing from there -- a bare import at module scope on a
# badge with a missing or damaged library raises inside `launch()`, which resets
# the badge, for ever. A screen
# that could not refuse a fat-fingered 2019 without a networking library would be
# the exact failure this screen exists to prevent: TLS would still fail, and the
# screen built to repair the badge would have quietly made it LOOK repaired.
#
# **THE DUPLICATION IS PINNED BY AGREEMENT AND NOT BY EQUALITY.**
# `test_settings_clock` asserts each constant equals `clock_boot`'s AND sweeps
# `clock_verdict` against the real `clock_boot.evaluate_ntp` across every
# boundary, so "a second gate that could disagree with the one the TLS path
# applies" -- the objection `diag_view` refuses to accept for the READOUT -- is
# closed by measurement here rather than by a promise.

#: `clock_boot.BUILD_FLOOR_EPOCH`: 2026-08-08T00:00:00Z, the pinned firmware's
#: build date. Below it a certificate window cannot be checked, and it is also
#: what rejects the PCF85063A's flat-battery default (the chip powers up in 2021).
CLOCK_FLOOR_EPOCH = 1786147200
#: `clock_boot.MAX_PLAUSIBLE_EPOCH`: 2099-12-31T23:59:59Z.
CLOCK_MAX_EPOCH = 4102444799
#: `clock_boot.NTP_ERA_ROLLOVER_EPOCH`: 2036-02-07T06:28:16Z, 2**32 seconds after
#: the NTP epoch. A clock inside the band around it is treated as NO CLOCK by
#: `clock_boot.resync`, so a wearer allowed to hand-set into it would be told
#: "clock set" while TLS went on failing -- the one outcome this screen may never
#: produce. Refused here for that reason and no other; hand entry cannot reach it
#: by the mechanism the band was built for (an era-1 mapping of a near-zero
#: seconds field), only by somebody typing it.
CLOCK_ERA_EPOCH = 2085978496
#: `clock_boot.NTP_ERA_GUARD_S`: seven days either side.
CLOCK_ERA_GUARD_S = 7 * 24 * 60 * 60

#: `clock_boot.evaluate_ntp`'s own reason literals, so the two gates speak one
#: vocabulary and `settings_copy.CLOCK_REJECT_LINES` is keyed on the runtime's
#: words rather than on words invented here.
CLOCK_PLAUSIBLE = "plausible"
CLOCK_BEFORE_FLOOR = "before_build_floor"
CLOCK_AFTER_CEILING = "implausible_future"
CLOCK_ERA_BAND = "ntp_era_rollover"

#: The editable fields. **THESE FIVE NUMBERS ARE TUPLE INDICES, NOT AN ORDER.**
#: Every function below indexes `(year, month, day, hour, minute)` with them, so
#: they cannot be renumbered to express a cursor order -- which is exactly what
#: the 2026-08-28 redesign needed and exactly why it did not touch them. The
#: order the cursor walks is `CLOCK_TRACKS`.
#:
#: NO SECONDS FIELD, AND THAT IS THE METHOD'S OWN PRECISION rather than a saving.
#: A wearer reads a phone and presses a key; the entry cannot deliver seconds, so
#: a seconds field would be a fifth of the presses for a digit nobody measured.
#: `clock_boot.resync` replaces the whole value to the second the moment a server
#: is reachable, which is the only thing that ever could.
CLOCK_YEAR = 0
CLOCK_MONTH = 1
CLOCK_DAY = 2
CLOCK_HOUR = 3
CLOCK_MINUTE = 4
CLOCK_FIELDS = (CLOCK_YEAR, CLOCK_MONTH, CLOCK_DAY, CLOCK_HOUR, CLOCK_MINUTE)

# -- the cursor: two rows of fields and two buttons on the panel --------------
#
# **THE TERMINAL REDESIGN, OWNER REQUEST 2026-08-28.** The first draft of this
# screen walked all five fields on one wrapping C key and NAMED the selected one
# in a sentence ("Up and down change the hour"). The owner called it *"a good
# first draft"* and asked for something else, in his words:
#
#     "what I actually want is more like terminal UI style ... when I go into my
#     BIOS settings, I think it's clearly highlighted on hour ... so it's very
#     obvious that if I go up or down, I'm changing the hour."
#
# and, on where the cursor starts: *"they really won't be updating the year, so
# that shouldn't be the default thing that is selected."*
#
# So the panel is a LAYOUT rather than a list, and the cursor moves through it:
#
#     HH:MM PDT      [ Save ]  [ Cancel ]
#     YYYY-MM-DD
#
# * **A and C are LEFT and RIGHT** through the stops of the current row, and both
#   rows continue rightward onto Save and then Cancel. From the opening position
#   that is right -> MM, right -> Save: **two presses to reach the button**,
#   which is the point of putting the time first.
# * **UP and DOWN change the highlighted value** (unchanged; §I1's own worked
#   example is a time dial, and this is the only key pair with a repeat curve).
# * **B SWITCHES ROWS** on a value field and **ACTIVATES** on a button.
#
# SAVE AND CANCEL ARE STOPS ON BOTH TRACKS RATHER THAN A THIRD ROW. They are the
# only two things on this screen that are not a value, so a wearer walking right
# off the end of either row arrives at them the way they arrive at anything else,
# and the highlight tells them which one they are on before B does anything.
#
# THE STOP IDS CONTINUE THE FIELD NUMBERING and are deliberately NOT valid tuple
# indices into the five fields: `clock_step` falls through on them and
# `_clock_step` refuses to call it, so a scroll key on a button is inert by two
# independent mechanisms rather than by one.
CLOCK_SAVE = 5
CLOCK_CANCEL = 6
#: The two stops that are buttons rather than values. `in` on a two-tuple, which
#: is what MicroPython makes cheapest and what every reader below uses.
CLOCK_ACTIONS = (CLOCK_SAVE, CLOCK_CANCEL)

CLOCK_ROW_TIME = 0
CLOCK_ROW_DATE = 1
#: What A and C walk, per row. **THE TIME ROW IS FIRST BECAUSE THE CURSOR OPENS
#: ON IT**, on the owner's reasoning above: the date on a badge being hand-set at
#: the event is already right, and the common repair is nudging an hour.
#:
#: FIVE STOPS IS THE LONGEST TRACK AND THAT IS BOUNDED BY §I2's FIVE-A TEST, not
#: by taste. A at the leftmost stop leaves (see `_clock_key`), so the deepest
#: stop on the date row -- Cancel -- is exactly five A presses from the menu.
#: A sixth stop on either track would fail the test the button rules state.
CLOCK_TRACKS = (
    (CLOCK_HOUR, CLOCK_MINUTE, CLOCK_SAVE, CLOCK_CANCEL),
    (CLOCK_YEAR, CLOCK_MONTH, CLOCK_DAY, CLOCK_SAVE, CLOCK_CANCEL),
)

_CLOCK_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _days_from_civil(year, month, day):
    """Days from 1970-01-01 for a proleptic Gregorian date. Pure integers.

    Hinnant's days-from-civil, which is exact for every year this screen can
    reach and needs no `time` module -- deliberately, because `time.mktime`'s
    epoch is NOT 1970 on every MicroPython port (a 2000-based epoch is exactly
    the mechanism `badgelink/badge/ft_b_clock_probe.py` reads rather than
    assumes), while `clock_boot`'s bounds are Unix seconds. Doing the arithmetic
    here means the comparison cannot be wrong by 30 years on one port.
    """
    if month <= 2:
        year -= 1
    era = year // 400
    year_of_era = year - era * 400
    shifted = month + (-3 if month > 2 else 9)
    day_of_year = (153 * shifted + 2) // 5 + day - 1
    day_of_era = (year_of_era * 365 + year_of_era // 4 - year_of_era // 100
                  + day_of_year)
    return era * 146097 + day_of_era - 719468


def _civil_from_days(days):
    """The inverse of :func:`_days_from_civil`: ``(year, month, day)``."""
    days += 719468
    era = days // 146097
    day_of_era = days - era * 146097
    year_of_era = (day_of_era - day_of_era // 1460 + day_of_era // 36524
                   - day_of_era // 146096) // 365
    year = year_of_era + era * 400
    day_of_year = day_of_era - (365 * year_of_era + year_of_era // 4
                                - year_of_era // 100)
    shifted = (5 * day_of_year + 2) // 153
    day = day_of_year - (153 * shifted + 2) // 5 + 1
    month = shifted + (3 if shifted < 10 else -9)
    if month <= 2:
        year += 1
    return year, month, day


def clock_days_in_month(year, month):
    """How many days that month really has. The leap rule, not an approximation.

    A wearer who scrolls to 31 and then back to February must not be able to
    commit a date that does not exist, and `_days_from_civil` would silently
    normalise one into 2 March -- a value the screen never showed.
    """
    if month == 2 and year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
        return 29
    return _CLOCK_MONTH_DAYS[month - 1]


def clock_weekday(year, month, day):
    """Monday=0 .. Sunday=6, which is the ONE numbering both writes take.

    `machine.RTC().datetime` takes Monday=0, and `badgeware/rtc.py:26` puts
    `time.localtime()[6]` -- the same numbering -- into the PCF's weekday
    register, which `rtc.py:30` reads back straight through. 1970-01-01 was a
    Thursday, so day 0 is 3.
    """
    return (_days_from_civil(year, month, day) + 3) % 7


def clock_epoch(fields):
    """Unix seconds for ``(year, month, day, hour, minute)``. Seconds are zero."""
    year, month, day, hour, minute = fields
    return (_days_from_civil(year, month, day) * 86400 + hour * 3600
            + minute * 60)


def clock_verdict(epoch):
    """`clock_boot.evaluate_ntp`'s answer for `epoch`, restated in this module.

    RESTATED RATHER THAN CALLED, because `clock_boot` is in `/system/lib` and
    this module imports nothing from there -- see the block above for why the
    duplication is the right trade and how it is pinned. The ORDER of the three
    refusals is `evaluate_ntp`'s too, so a value that fails two of them gets the
    same word from both gates.
    """
    if epoch < CLOCK_FLOOR_EPOCH:
        return CLOCK_BEFORE_FLOOR
    if epoch > CLOCK_MAX_EPOCH:
        return CLOCK_AFTER_CEILING
    distance = epoch - CLOCK_ERA_EPOCH
    if distance < 0:
        distance = -distance
    if distance <= CLOCK_ERA_GUARD_S:
        return CLOCK_ERA_BAND
    return CLOCK_PLAUSIBLE


def _fields_from_epoch(epoch):
    """Unix seconds -> ``(year, month, day, hour, minute)``. The inverse of
    :func:`clock_epoch`, minus the seconds this screen does not carry.

    Its two callers both need a CONSTANT derived from a bound rather than
    written out, so an edit to the bound moves the derived value with it instead
    of leaving a literal that agrees with nothing.
    """
    return (_civil_from_days(epoch // 86400)
            + ((epoch % 86400) // 3600, (epoch % 3600) // 60))


# -- the event's timezone, and the ONE offset the whole screen turns on --------
#
# **THE EDITOR'S FIELDS ARE EVENT-LOCAL SINCE 2026-08-28, AND UTC IS A READ-OUT.**
# Owner request, in the owner's words: *"having the UTC time visible is kinda
# cool but maybe it should be smaller, like more of a sanity check for anyone
# looking at it ... the user interface, user experience should be PST time, the
# local time zone. The UI should just say PST and that would be the main focus of
# what they're updating."*
#
# The fields were UTC until that day and the panel carried a line reading `Use
# UTC, not your local time`. That line is gone: a wearer reads a phone showing
# local time and should be able to type what it says.
#
# ⚠ **THE LABEL IS PDT AND THE OFFSET IS -420, NOT "PST" AND -480.** The owner
# says "PST" the way most people do; 2026-10-02 is inside daylight time, and
# `schedule/badge/schedule/schedule.json` records the event as `"timezone":
# "PDT"` with `"utc_offset_min": -420`. `schedule` renders every clock through
# THAT field and prints THAT label, so a Clock screen saying PST would put this
# badge's two screens an hour apart on the same instant. `EventSeedTests` pins
# the offset AND the label against the shipped agenda, so a future reader
# "correcting" either one gets a red test instead of a fleet an hour out.
#
# ⚠ **A FIXED OFFSET IS DELIBERATE, AND IT IS ONLY RIGHT FOR THE EVENT DAY.**
# Owner ruling, same day: *"you can hard code anything that you want for that
# date ... It doesn't have to be generic enough to last all year round with
# daylight savings and everything. Just that single day would need to be
# accurate."* So there is no DST engine here and there must not be one. The
# consequence, stated rather than engineered around: a wearer who sets this clock
# outside Pacific daylight time -- before 2026-03-08 or after 2026-11-01 -- gets a
# conversion one hour out for that date, and the UTC the badge stores is wrong by
# an hour. That is the accepted trade for a badge that exists for one day. It is
# also SAFE in the way that matters: the hour lands well inside the plausibility
# band, so a badge set in the wrong season still gets a clock verified TLS
# accepts, which is what this screen exists for.
#
# **THE OFFSET IS LOAD-BEARING NOW, WHERE IT USED TO BE A DEFAULT.** Until today
# it only picked the number the editor OPENED on. It is now applied to every
# value the wearer commits (`_clock_key` converts before it validates or writes),
# so a wrong offset is a wrong clock on every badge rather than a wrong starting
# point on some. That is exactly why the pin below is by AGREEMENT with the real
# agenda rather than by an `assertEqual` against a literal.
#
# SOURCED AS A CONSTANT AND NOT READ FROM THE AGENDA, which is a deliberate
# refusal rather than an oversight. This module is I/O-free by contract and
# imports nothing (see the file docstring); reaching `schedule`'s JSON would mean
# the Settings tile depending on another app's install path, its schema and its
# day-of `/schedule.json` override -- a cross-app failure mode on the one screen
# that has to work when everything else is broken. The duplication is pinned the
# way `clock_boot`'s bounds above are pinned, by AGREEMENT rather than by
# equality: `EventSeedTests` reads the shipped agenda on the host and fails if
# `utc_offset_min`, `timezone`, `start_date` or `day_start` ever stops matching
# these constants, so a rescheduled or relocated event is one red test.
#
# **WHAT THE EVENT INSTANT IS FOR, AND ITS SCOPE, which did not change with the
# frame.** It is the editor's FALLBACK SEED (owner request, same day): the number
# the five fields open on when the badge's own clock is garbage or unreadable.
# The badge does not adopt it, store it, report it or assert it anywhere, and one
# press of A leaves without writing it (`EventSeedTests` proves that). A
# plausible clock still seeds from itself.
#
# WHY IT BEATS THE BUILD FLOOR, which is what opened here until that day. Both
# are accepted dates, so both satisfy "every press moves toward a value that
# works". The event date is simply CLOSER TO THE TRUE TIME than anything else
# this module can name without a network -- a badge whose clock is the PCF's 2021
# is being hand-set by somebody standing at the event, so the wearer arrives
# within minutes of correct instead of within two months. It is also,
# deliberately, the easter egg: that date was the event -- and with local-facing
# fields the panel shows it as 09:00, which is what the agenda calls it.
#: `event.start_date` in `schedule/badge/schedule/schedule.json`.
CLOCK_EVENT_DATE = (2026, 10, 2)
#: `event.day_start` -- the hour the doors open, in EVENT-LOCAL time.
CLOCK_EVENT_LOCAL_HM = (9, 0)
#: `event.utc_offset_min`: minutes to ADD to a UTC clock to get event-local. PDT,
#: because 2 October is inside daylight time. NOT -480; see the block above.
CLOCK_EVENT_UTC_OFFSET_MIN = -420


def clock_local_to_utc(fields):
    """Event-local ``(y, m, d, H, M)`` -> the same instant in UTC.

    **THE DIRECTION MATTERS AND GETTING IT BACKWARDS IS A SEVEN-HOUR ERROR.**
    `CLOCK_EVENT_UTC_OFFSET_MIN` is minutes to ADD to a UTC clock to reach
    event-local (the agenda's own sense), so the inverse SUBTRACTS it. Applied
    the wrong way the accepted window would move fourteen hours, every commit
    would store a clock seven hours out, and nothing on the badge would say so --
    `clock_boot.evaluate_ntp` would still call the value plausible.
    `test_settings_clock` pins the direction against both bounds for that reason.

    Via the epoch rather than by adding to the hour field, because a -420 offset
    rolls the DATE for every event-local time from 17:00 -- and at a month or
    year boundary it rolls those too. `_fields_from_epoch` owns that arithmetic
    already and `_civil_from_days` is exact for every year the ladder can reach.
    """
    return _fields_from_epoch(
        clock_epoch(fields) - CLOCK_EVENT_UTC_OFFSET_MIN * 60)


def clock_utc_to_local(fields):
    """UTC ``(y, m, d, H, M)`` -> the same instant in event-local time.

    The inverse of :func:`clock_local_to_utc`, and the seam the badge's own clock
    crosses on the way IN: `ClockSet.read` answers UTC because that is what the
    badge stores, and the editor shows event-local because that is what the
    wearer reads off a phone.
    """
    return _fields_from_epoch(
        clock_epoch(fields) + CLOCK_EVENT_UTC_OFFSET_MIN * 60)


#: 2026-10-02 09:00 PDT: the doors opening, in the frame the editor EDITS.
#: Written as the agenda writes it, so the seed the wearer sees is literally the
#: agenda's own `start_date` and `day_start` -- which is the owner's easter egg
#: and, since the fields went local, something the panel can now show verbatim.
CLOCK_EVENT_LOCAL_FIELDS = CLOCK_EVENT_DATE + CLOCK_EVENT_LOCAL_HM
#: The same instant in the frame the badge STORES: 16:00 UTC. Derived rather than
#: written, so a wrong offset moves it visibly instead of agreeing with nothing.
CLOCK_EVENT_UTC_FIELDS = clock_local_to_utc(CLOCK_EVENT_LOCAL_FIELDS)

#: The earliest instant this screen will accept, as UTC fields. Composed from the
#: floor rather than written out, so moving the floor moves everything below.
CLOCK_FLOOR_FIELDS = _fields_from_epoch(CLOCK_FLOOR_EPOCH)
#: THE SAME TWO BOUNDS IN THE FRAME THE WEARER TYPES IN, which is the frame the
#: refusal sentences and the year ladder have to speak. At -420 the floor is
#: 2026-08-07 17:00 event-local, so a panel that said "Nothing before 2026-08-08"
#: would be refusing a date it does in fact accept -- the exact off-by-an-offset
#: this file's conversion comments exist to stop.
CLOCK_FLOOR_LOCAL_FIELDS = clock_utc_to_local(CLOCK_FLOOR_FIELDS)
CLOCK_CEILING_LOCAL_FIELDS = clock_utc_to_local(
    _fields_from_epoch(CLOCK_MAX_EPOCH))
#: The year ladder's ends. DERIVED FROM THE LOCAL BOUNDS, because the ladder
#: walks the local year field: the offset happens not to move either endpoint's
#: year, and deriving from local is what makes "the ladder cannot walk to a year
#: the SET press would refuse" a fact rather than a coincidence.
CLOCK_MIN_YEAR = CLOCK_FLOOR_LOCAL_FIELDS[0]
CLOCK_MAX_YEAR = CLOCK_CEILING_LOCAL_FIELDS[0]


def clock_time_line(fields, actions=True):
    """The first row: ``HH:MM PDT`` and, on the editor, the two buttons.

    Returns ``(text, spans)`` where ``spans`` maps a cursor stop to the
    ``(start, end)`` CHARACTER offsets of the thing it selects.

    **THE SPANS ARE ACCUMULATED WHILE THE STRING IS BUILT, never written down.**
    The view turns them into a highlight rectangle by measuring
    ``text[:start]`` and ``text[start:end]``, so an offset that disagrees with
    the composition by one character puts a green block half over a colon. Every
    piece here is a fixed-width format or a copy constant; deriving the offsets
    from the pieces is what makes a copy edit move the block with the text
    instead of leaving it behind.

    ASCII BY CONSTRUCTION, WHICH THE OFFSETS DEPEND ON. ``settings_copy.ascii_fold``
    is length-preserving for printable ASCII and is NOT for anything else (U+2026
    becomes three characters), so a non-ASCII edit to any constant here would
    silently shift every span after it. `test_settings_clock` asserts the folded
    line equals the composed one.

    ``actions=False`` is the note after a commit, which shows the wearer the time
    they set with no button beside it: the question has been answered and a
    button over a screen with nothing to decide is §I5's dead key.
    """
    text = "{:02d}:{:02d}".format(fields[CLOCK_HOUR], fields[CLOCK_MINUTE])
    # HH and MM are the first two and fourth-and-fifth characters of a
    # `{:02d}:{:02d}`, which is fixed width for every value the ladder can reach.
    spans = {CLOCK_HOUR: (0, 2), CLOCK_MINUTE: (3, 5)}
    text += settings_copy.CLOCK_LOCAL_SUFFIX
    if not actions:
        return text, spans
    text += settings_copy.CLOCK_CHIP_GAP
    start = len(text)
    text += settings_copy.CLOCK_SAVE_CHIP
    spans[CLOCK_SAVE] = (start, len(text))
    text += settings_copy.CLOCK_CHIP_SPACE
    start = len(text)
    text += settings_copy.CLOCK_CANCEL_CHIP
    spans[CLOCK_CANCEL] = (start, len(text))
    return text, spans


def clock_date_line(fields):
    """The second row: ``YYYY-MM-DD``, and the spans of its three fields.

    ISO ORDER, WHICH IS THE ONE ORDER NOBODY MISREADS. `08/09` is two different
    days on two sides of an ocean and this badge is handed to a room of people
    from both. It is also what puts this line digit-over-digit with the UTC
    read-out below it, which is the whole of that read-out's job: at -420 every
    event-local time from 17:00 rolls UTC into the next day, and the roll is
    visible as one column changing.
    """
    text = "{:04d}-{:02d}-{:02d}".format(fields[CLOCK_YEAR], fields[CLOCK_MONTH],
                                         fields[CLOCK_DAY])
    return text, {CLOCK_YEAR: (0, 4), CLOCK_MONTH: (5, 7), CLOCK_DAY: (8, 10)}


def clock_stamp(fields):
    """``2026-08-28  14:35``. Fixed width, so the line cannot move under a press.

    THE UTC READ-OUT'S SHAPE, AND SINCE 2026-08-28 ONLY ITS SHAPE. The editor's
    own local value is drawn as two rows (`clock_time_line` over
    `clock_date_line`) because the wearer edits them separately; the badge's
    stored frame is one line under both, because nobody edits it. Keeping this
    one-line form for the read-out is what lines its DATE up with the date row
    above it, column for column, at `_draw_body`'s fixed margin.
    """
    return "{:04d}-{:02d}-{:02d}  {:02d}:{:02d}".format(*fields)


#: WHY A COMMIT WAS REFUSED, in the wearer's words. Keyed on `evaluate_ntp`'s own
#: literals plus `clock_set.FAILED`, and COMPOSED HERE rather than spelled in
#: `settings_copy` because the two boundary sentences name an INSTANT derived
#: from `CLOCK_FLOOR_EPOCH` -- moving the floor has to move the sentence with it,
#: and `settings_copy` cannot import this module (this module imports it).
#: `settings_copy` still owns every word; this owns which state gets which.
#:
#: **THE BOUNDS ARE STATED IN THE FRAME THE WEARER IS TYPING IN, AND TO THE
#: MINUTE -- both of which changed on 2026-08-28.** They are UTC epochs and the
#: panel is now event-local, so naming the UTC date would refuse a wearer for a
#: value the gate accepts. And at -420 neither bound lands on local midnight, so
#: the DATE ALONE IS NOT ENOUGH EITHER: the floor is 2026-08-07 17:00 local, and
#: "Nothing before 2026-08-07" would be refusing 2026-08-07 18:00, which is
#: accepted. A date was exact while the fields were UTC and the bound was
#: midnight; it is exact in no other frame.
#:
#: `clock_stamp`'S SHAPE ON PURPOSE, so the refusal and the line being edited are
#: the same fixed width in the same order and the comparison is character against
#: character rather than remembered.
CLOCK_REJECT_LINES = {
    CLOCK_BEFORE_FLOOR: settings_copy.CLOCK_TOO_EARLY.format(
        clock_stamp(CLOCK_FLOOR_LOCAL_FIELDS)),
    CLOCK_AFTER_CEILING: settings_copy.CLOCK_TOO_LATE.format(
        clock_stamp(CLOCK_CEILING_LOCAL_FIELDS)),
    CLOCK_ERA_BAND: settings_copy.CLOCK_BAD_DATE,
    settings_copy.CLOCK_RESULT_FAILED: settings_copy.CLOCK_NOT_WRITTEN,
}


def clock_seed(reading):
    """The EVENT-LOCAL fields the editor opens on: the badge's clock, or the event.

    **THE READING IS UTC AND THE ANSWER IS EVENT-LOCAL, and the conversion is the
    LAST step rather than the first.** `ClockSet.read` answers the badge's own
    clock, which is UTC by contract, and `clock_verdict` is `evaluate_ntp`'s rule
    on a UTC epoch -- so the reading is validated in the frame it arrived in and
    converted only once it is known to be a clock. Converting first would leave
    the gate judging a local instant against UTC bounds, which is the same
    seven-hour error `clock_local_to_utc` warns about, pointed the other way.

    A PLAUSIBLE READING IS KEPT so a wearer whose badge is only wrong by an hour
    moves one field, not five -- and so that tweaking a good clock cannot wreck
    it. **AN IMPLAUSIBLE ONE IS DISCARDED FOR THE EVENT rather than shown**, and
    that is the whole case this screen is for: the value it would otherwise seed
    from is the PCF85063A's garbage, and starting a wearer at 2021 makes them
    scroll through five years of a value the screen is going to refuse anyway.

    THE FALLBACK IS THE EVENT INSTANT AND NOT THE BUILD FLOOR (owner request,
    2026-08-28; see the block above `CLOCK_EVENT_DATE` for the whole reasoning
    and for why the offset is the agenda's -420). Both are accepted dates, so
    both leave every press moving toward a value that works; the event is the one
    that is CLOSE, because the badge being hand-set is a badge at the event. With
    local-facing fields it now opens reading `2026-10-02  09:00 PDT` -- the
    agenda's own words for the doors opening, which is the point of the egg.
    Nothing is written, stored or claimed by seeding it.

    Total: a stand-in, a short tuple or a non-integer field all land on the
    event, because none of them is a clock this badge can be trusted to hold.
    """
    if not isinstance(reading, (tuple, list)) or len(reading) < 5:
        return list(CLOCK_EVENT_LOCAL_FIELDS)
    fields = []
    for index in range(5):
        value = reading[index]
        if isinstance(value, bool) or not isinstance(value, int):
            return list(CLOCK_EVENT_LOCAL_FIELDS)
        fields.append(value)
    if (fields[1] < 1 or fields[1] > 12 or fields[2] < 1
            or fields[2] > clock_days_in_month(fields[0], fields[1])
            or fields[3] < 0 or fields[3] > 23
            or fields[4] < 0 or fields[4] > 59):
        return list(CLOCK_EVENT_LOCAL_FIELDS)
    if clock_verdict(clock_epoch(fields)) != CLOCK_PLAUSIBLE:
        return list(CLOCK_EVENT_LOCAL_FIELDS)
    return list(clock_utc_to_local(fields))


def clock_step(fields, index, delta):
    """One press of UP or DOWN on the selected field. Returns the new fields.

    EVERY FIELD WRAPS (B3), including the year, so nothing is more than a hold
    away in either direction and the UP-then-DOWN test passes on every field.
    The year wraps within [`CLOCK_MIN_YEAR`, `CLOCK_MAX_YEAR`], which is derived
    from the same two bounds `clock_verdict` enforces -- so the ladder cannot
    walk to a year the SET press would then refuse.

    **THE DAY IS CLAMPED AFTER A YEAR OR MONTH MOVE, NOT VALIDATED AT COMMIT.**
    A wearer on 31 January who steps to February must see 28 immediately; leaving
    31 on screen and refusing it three presses later would blame them for a date
    the screen offered. `_days_from_civil` would otherwise normalise 31 February
    into 3 March, which is a value the panel never displayed.

    **AND THE CLAMP IS WHY B3'S UP-THEN-DOWN TEST DOES NOT HOLD ON THE DAY, which
    is a declared exception rather than a defect.** B3 is a guideline about a list
    SELECTION, where items are independent; the day here DEPENDS on the two fields
    above it, which is the value-field case I1 was rewritten to allow. Stepping
    31 December back to November shows 30 and stepping forward again leaves 30.
    The alternative -- a shadow "desired day" restored when the month allows -- is
    INVISIBLE STATE (the panel would show 30 while the model held 31) and it makes
    the day GROW while the wearer is moving the month, from a value they cannot
    see. The rule kept instead is the one a wearer can follow: **a day only ever
    shrinks, in full view.** `NEXT` walks year, month, day, so in the natural
    order the day is set after the month it has to fit in and the clamp costs
    nothing. `test_settings_clock` pins both halves.
    """
    fields = list(fields)
    if index == CLOCK_YEAR:
        span = CLOCK_MAX_YEAR - CLOCK_MIN_YEAR + 1
        fields[CLOCK_YEAR] = CLOCK_MIN_YEAR + (
            (fields[CLOCK_YEAR] - CLOCK_MIN_YEAR + delta) % span)
    elif index == CLOCK_MONTH:
        fields[CLOCK_MONTH] = 1 + ((fields[CLOCK_MONTH] - 1 + delta) % 12)
    elif index == CLOCK_DAY:
        last = clock_days_in_month(fields[CLOCK_YEAR], fields[CLOCK_MONTH])
        fields[CLOCK_DAY] = 1 + ((fields[CLOCK_DAY] - 1 + delta) % last)
        return fields
    elif index == CLOCK_HOUR:
        fields[CLOCK_HOUR] = (fields[CLOCK_HOUR] + delta) % 24
        return fields
    elif index == CLOCK_MINUTE:
        fields[CLOCK_MINUTE] = (fields[CLOCK_MINUTE] + delta) % 60
        return fields
    else:
        return fields
    last = clock_days_in_month(fields[CLOCK_YEAR], fields[CLOCK_MONTH])
    if fields[CLOCK_DAY] > last:
        fields[CLOCK_DAY] = last
    return fields


def clock_view(fields, stop=CLOCK_HOUR, row=CLOCK_ROW_TIME, result=None):
    """The hand-set clock: an editor, or the note that follows a commit.

    **THE KEY MAP, REDESIGNED 2026-08-28 ON THE OWNER'S REQUEST, AND EVERY PART
    OF IT IS A RULE RATHER THAN A CHOICE.** The panel is a layout now -- a time
    row with two buttons beside it over a date row -- and the block above
    `CLOCK_TRACKS` carries the owner's words and the shape they asked for.

    * **A and C are LEFT and RIGHT** through the stops of the current row (§I1:
      "A means left, C means right -- whenever a screen needs those directions at
      all", and this one now does). The track continues rightward onto Save and
      then Cancel, so from the opening position Save is two presses away.
    * **UP and DOWN change the highlighted value**, unchanged. §I1 was rewritten
      to allow exactly this -- "it would have flagged a perfectly ordinary time
      dial, where up and down on an hour field are exactly what anyone expects"
      -- and it is the only key pair with a repeat curve (§B4), which matters
      because a year is up to 73 presses away. It is safe here where it was not
      on BRIGHTNESS: a step writes an integer in RAM, not flash.
    * **B SWITCHES ROWS on a value field and ACTIVATES on a button.** This is a
      DECLARED DEVIATION from §B2's "B is the primary action", and it is this
      tile's second (BRIGHTNESS declares the other). The primary action IS still
      reached with B -- it is just reached with the cursor on the thing it acts
      on, which is what makes a two-button row possible at all. The bar says
      which of the three B means at every moment, so §I5 is satisfied rather
      than traded away.

    **HOW THE WEARER LEAVES WITHOUT SAVING, AND WHY IT IS BOTH DOORS.**

    * **Cancel is on the track**, drawn on the panel from the first frame, so the
      way out is visible rather than remembered. It is the labelled route §I2
      asks for, and it commits nothing.
    * **AND A AT THE LEFTMOST STOP OF A ROW STILL LEAVES.** That is not a
      convenience: §I2's test is "press A five times without reading the screen;
      PASS: you are at the app root and nothing was committed", and with A
      re-tasked as a direction the only way to keep passing it is to let the
      walk fall out of its own left end. The deepest stop on the longer track is
      exactly five A presses from the menu, which is what bounds `CLOCK_TRACKS`
      at five.

    **THE TRAP THAT WOULD HAVE BEEN, AND WHAT STOPS IT.** A key that is "left"
    four times and "leave, losing the edit" the fifth is a key that changes
    meaning under a thumb. The bar is the answer (§I5): A reads `LEFT` on every
    stop but the leftmost and `BACK` there, so the press that exits is the press
    the wearer can SEE is an exit. Nothing else on this screen can leave without
    a labelled B, and nothing at all can leave having written a clock.

    **THE WRAP THAT WAS CONSIDERED AND REJECTED.** Making the track cyclic --
    A at the leftmost landing on Cancel -- is the other way to keep A alive, and
    it is tempting because it makes an accidental over-shoot cost nothing and
    puts "back" two presses away on a chip that says so. It fails §I2's five-A
    test outright: five blind A presses would walk a circle. A guideline this
    repository states as a 30-second test is not worth trading for a hazard it
    already covers with a label.

    **THE HIGHLIGHT IS THE CURSOR, AND IT COULD NOT BE A SECOND POINT SIZE.**
    `settings_view._text` draws every body line at `Chrome.font_size`; the app
    resolves ONE size since the Phone row went, `settings/tests/settings_metrics.py`
    models what it measures and the harness RAISES on an unmodelled size, and the
    body's cap is 17.7 arcmin at 400 mm against this project's chosen 15.0 floor
    -- under 3 arcmin before the copy is below a bar the tile enforces everywhere
    else. So the hierarchy is ink, position and a rectangle: `accent_lines` puts
    the two edited rows in PHOSPHOR over the DIM read-out, and `highlight` names
    a CHARACTER SPAN on one of them that `_draw_body` paints as reverse video --
    a solid PHOSPHOR block with the digits cut out of it in the panel's own
    background. That is a terminal cursor, it is the same treatment whether the
    stop is two digits or a bracketed button, and it costs no point size.

    ``highlight`` IS A ``(line, start, end)`` TUPLE AND NOT PIXELS. The model
    owns which characters are selected; the view owns what that is worth in
    millimetres. It is absent on the note, where nothing is selected.

    **THE LOCAL VALUE IS THE SUBJECT AND UTC IS A READ-OUT UNDER IT.** Owner
    request, same day: *"the user interface, user experience should be PST time,
    the local time zone. The UI should just say PST and that would be the main
    focus of what they're updating"*, with UTC kept visible but *"more of a
    sanity check for anyone looking at it"*. Three decisions carry that:

    * ``fields`` ARE EVENT-LOCAL. They are what UP/DOWN move, what the wearer
      reads off a phone, and what Save commits (after `clock_local_to_utc`).
    * THE UTC LINE IS DERIVED ON EVERY BUILD OF THIS MODEL, never stored, so it
      cannot lag the value it is a check on.
    * IT IS LAST AND IT IS THE ONLY LINE NOT IN PHOSPHOR. The date row above it
      is `clock_date_line`'s and this is `clock_stamp`'s, both starting at
      `_draw_body`'s fixed margin, so their DATES land digit over digit -- and
      an event-local time past 17:00 rolls the read-out into tomorrow in a
      column the eye can find. The time halves do not line up, which is the
      price of splitting the wearer's value across two rows; the roll is the
      half of the check that a wearer cannot do in their head.

    ``result`` IS WHAT HAPPENED TO THE LAST PRESS OF SAVE: ``None`` while
    editing, `clock_set.SET`/`VOLATILE` for a commit that landed (its own note,
    with the editor gone), and a REFUSAL literal otherwise -- which keeps the
    wearer ON the editor with the value they typed and one line saying what is
    wrong with it, so the fix is a press away rather than a re-entry.
    """
    if result in (settings_copy.CLOCK_RESULT_SET,
                  settings_copy.CLOCK_RESULT_VOLATILE):
        # ONE COMPOSITION FOR BOTH SCREENS, so the note cannot drift from the
        # editor. A wearer who just committed 09:00 PDT on 2026-10-02 is shown
        # those same two rows back, in the same ink and the same order, with the
        # same UTC read-out under them -- minus the two buttons, because the
        # question has been answered.
        time_text, _ = clock_time_line(fields, actions=False)
        date_text, _ = clock_date_line(fields)
        lines = [time_text, date_text,
                 clock_stamp(clock_local_to_utc(fields))
                 + settings_copy.CLOCK_UTC_SUFFIX]
        if result == settings_copy.CLOCK_RESULT_SET:
            lines.append(settings_copy.CLOCK_DONE_KEPT)
        else:
            # THE HALF-WRITE, NAMED. The system clock took it and the external
            # chip did not, so it is the clock for this session and gone with the
            # battery. Telling the wearer "saved" here is the one direction
            # nothing later corrects -- they would set it once and lose it.
            lines.append(settings_copy.CLOCK_DONE_VOLATILE)
        lines.append(settings_copy.CLOCK_DONE_REPLACED)
        return {
            "screen": CLOCK,
            "title": (settings_copy.CLOCK_DONE_TITLE
                      if result == settings_copy.CLOCK_RESULT_SET
                      else settings_copy.CLOCK_VOLATILE_TITLE),
            "reboot": False,
            "fields": tuple(fields),
            "stop": stop,
            "row": row,
            "lines": [settings_copy.ascii_fold(line) for line in lines],
            "accent_lines": (0, 1),
            # NO CURSOR AND NO VERB LEFT. Nothing is selected, so there is
            # nothing to highlight; and a second SAVE over a note the wearer is
            # reading is a press with nothing to decide.
            "softkeys": (settings_copy.BACK, "", ""),
        }
    # BOUNDED BEFORE IT INDEXES. `_clock_key` keeps both of these in range, so
    # this is unreachable from a press -- but this function is public, both
    # values are published in the model, and an IndexError or a KeyError on a
    # draw path is `fatal_error` -> `machine.reset()`, every frame, for ever.
    # `bool` IS EXCLUDED FIRST, as it is in `_number`, because it is a subclass
    # of `int` in both runtimes -- a `True` would otherwise pass for MINUTE.
    if (isinstance(row, bool) or not isinstance(row, int)
            or row < 0 or row >= len(CLOCK_TRACKS)):
        row = CLOCK_ROW_TIME
    track = CLOCK_TRACKS[row]
    # `isinstance(int)` BEFORE THE MEMBERSHIP TEST, and the order is the bug it
    # was written from: `1.0 in (0, 1, 2, 5, 6)` is TRUE in both runtimes, so a
    # float stop passed the `in` check and then reached
    # `CLOCK_FIELD_NAMES[stop]` as a tuple index -- a TypeError on a draw path,
    # which is `fatal_error` -> `machine.reset()`, every frame, for ever.
    if (isinstance(stop, bool) or not isinstance(stop, int)
            or stop not in track):
        stop = track[0]
    time_text, time_spans = clock_time_line(fields)
    date_text, date_spans = clock_date_line(fields)
    lines = [time_text, date_text,
             clock_stamp(clock_local_to_utc(fields))
             + settings_copy.CLOCK_UTC_SUFFIX]
    # WHICH LINE THE STOP LIVES ON, resolved from the span tables rather than
    # from `row`: Save and Cancel are stops on BOTH tracks and are drawn once,
    # on the time line, so the cursor's row and the highlight's line are
    # genuinely different questions.
    if stop in time_spans:
        span = (0,) + time_spans[stop]
    else:
        span = (1,) + date_spans[stop]
    if stop not in CLOCK_ACTIONS:
        # ONLY ON A VALUE FIELD. On a button there is nothing for UP and DOWN to
        # change and the bar's own B label is the instruction; a permanent line
        # that is sometimes false is a line that stops being read.
        lines.append(settings_copy.CLOCK_FIELD_LINE.format(
            settings_copy.CLOCK_FIELD_NAMES[stop]))
    if result is not None:
        lines.append(CLOCK_REJECT_LINES.get(
            result, settings_copy.CLOCK_REJECT_UNKNOWN))
    # A IS THE LABELLED WAY BACK AT THE LEFT END OF A ROW AND A DIRECTION
    # EVERYWHERE ELSE, and the bar is the only thing that can say which (§I5).
    # C loses its label on the last stop for the reason BRIGHTNESS's ladder ends
    # lose theirs: a label over a key that cannot act teaches the wearer it does.
    position = track.index(stop)
    left = (settings_copy.BACK if position == 0
            else settings_copy.CLOCK_LEFT)
    right = ("" if position == len(track) - 1
             else settings_copy.CLOCK_RIGHT)
    if stop == CLOCK_SAVE:
        middle = settings_copy.CLOCK_SAVE
    elif stop == CLOCK_CANCEL:
        middle = settings_copy.CLOCK_CANCEL
    elif row == CLOCK_ROW_TIME:
        middle = settings_copy.CLOCK_ROW_DATE_LABEL
    else:
        middle = settings_copy.CLOCK_ROW_TIME_LABEL
    return {
        "screen": CLOCK,
        "title": settings_copy.CLOCK_TITLE,
        "reboot": False,
        # PUBLISHED so a probe and the seam's log can read what the panel shows
        # without re-deriving it from the strings. EVENT-LOCAL: these are the
        # digits on the panel, not the ones written.
        "fields": tuple(fields),
        "stop": stop,
        "row": row,
        "lines": [settings_copy.ascii_fold(line) for line in lines],
        # BOTH EDITED ROWS ARE THE SUBJECT, as INDICES rather than strings the
        # view sniffs for. `_line_pen` keys on exact copy constants, which cannot
        # identify a line whose text is five integers wide, and an index keeps
        # the view free of any knowledge of what this screen is about. Read with
        # `.get`, so every other screen in the tile is untouched.
        "accent_lines": (0, 1),
        # THE CURSOR, as (line, start, end) CHARACTER offsets. See the docstring:
        # the model owns which characters are selected and the view owns what
        # that is worth in pixels.
        "highlight": span,
        "softkeys": (left, middle, right),
    }


class Settings:
    """The whole tile as a pure machine: the rows, the routing and the screens.

    ``library`` is whether the BadgeLink ``/system/lib`` payload is installed on
    this badge. **A PLAIN BOOLEAN SINCE 2026-08-28, WHERE IT USED TO BE A PAIR OF
    INJECTED MODULES.** The tile took ``pairview`` and ``pairstate`` because the
    Phone row rendered their view-models, and ``library`` was read off them as a
    side effect (``self._pairview is not None``). With the row deleted this
    module consumes no shared module's API at all, so the fact it still needs --
    "is BadgeLink here?", which the Network, Updates and Diagnostics screens each
    have to state honestly -- arrives as the fact itself. ``settings/__init__.py``
    answers it with a guarded presence probe.
    """

    def __init__(self, library=False,
                 transport=None, network_control=None,
                 push_control=None, brightness=None, score_control=None,
                 clock_control=None):
        self._library = bool(library)
        self._transport = transport
        self._network_control = network_control
        self._push_control = push_control
        #: The one thing in this tile that can DELETE something, injected like
        #: every other capability so this module stays I/O-free and so the seam
        #: -- not the model -- decides what a wipe is allowed to reach. `None` is
        #: a tile that cannot erase, and the Scores row still exists on such a
        #: badge: the row is about the wearer's own files, not about a library,
        #: and a row that vanished when `/system/lib` was absent would teach the
        #: wearer that their high scores are a networking feature.
        self._score_control = score_control
        #: None while the question is up; True/False once it has been answered.
        #: Not a timer (a mashing thumb could cross a window) and not a toast
        #: (this tile has no toast machinery): the screen the wearer pressed on
        #: becomes the screen that reports what happened.
        self._scores_result = None
        #: THE SECOND THING IN THIS TILE THAT CAN CHANGE THE BADGE OUTSIDE ITS
        #: OWN FILES, injected like every other capability so this module stays
        #: I/O-free and so the SEAM -- not the model -- owns which clocks a write
        #: may reach. `None` is a tile that can offer the screen and not commit
        #: it, which is what a fixture and the browser lane are; the row still
        #: exists there, because the row is about the badge in the wearer's hand.
        self._clock_control = clock_control
        #: The five editable fields while the screen is open, and `None` when it
        #: is not. SEEDED ON THE WAY IN and dropped on the way out, so a wearer
        #: who leaves and comes back gets the badge's CURRENT clock rather than
        #: an abandoned edit (button rule B6: navigation never persists).
        self._clock_fields = None
        #: WHERE THE CURSOR IS, as (row, stop). Two values rather than one,
        #: because Save and Cancel are stops on BOTH tracks: the row is what A
        #: and C walk and what B toggles, and it is what the wearer returns to
        #: when they step left off a button. A single flat index could not say
        #: which row a press of A from Save should go back to.
        #:
        #: **THE TIME ROW AND THE HOUR ARE THE OPENING POSITION** (owner,
        #: 2026-08-28: *"they really won't be updating the year, so that
        #: shouldn't be the default thing that is selected"*). `_open_clock`
        #: re-seeds both on every entry.
        self._clock_row = CLOCK_ROW_TIME
        self._clock_stop = CLOCK_HOUR
        #: What happened to the last press of SET: `None` while editing, a
        #: refusal literal that keeps the wearer on the editor, or one of
        #: `clock_set`'s landed results, which replaces the editor with its note.
        self._clock_result = None
        #: WHICH PAGE OF A PAGED SCREEN IS UP, 0-based.
        #:
        #: RESET ON THE WAY IN (see :meth:`press`), for the same reason
        #: `_scores_result` and `_clock_fields` are: an operator who left on
        #: page 4 and came back must meet the ANSWER, not somebody else's page.
        #: The venue instruction that has to keep working is "press DOWN twice
        #: and read me the third line", and that sentence assumes a known start.
        self._page = 0
        self.screen = MENU
        self.index = 0
        self.rows = ROWS_WITH_PUSH if push_control is not None else ROWS
        #: THE WEARER'S PANEL LEVEL, SEEDED FROM THE FILE AND HELD HERE.
        #:
        #: A plain value rather than a controller object, which is the opposite
        #: of how `network_control` and `push_control` work, and the difference
        #: is where the authority sits. Those two DESCRIBE a live transport, so
        #: the model must read them back on every build or it would be reporting
        #: a state assumed from the last press. This one is the wearer's own
        #: choice and nothing else can change it while the tile is open: no
        #: server, no timer, and no other app -- because leaving an app is
        #: `machine.reset()`, so no other app is running.
        #:
        #: `None` is a seam that did not read the store (every fixture that is
        #: not about brightness), and it resolves to the factory level rather
        #: than to an end of the ladder, for the same reason `backlight.clamp`
        #: does: a badge whose file was hand-edited gets the level a new badge
        #: has, not the dimmest one.
        self.brightness = backlight.clamp(
            backlight.DEFAULT if brightness is None else brightness)
        #: Milliseconds left on the sleep note, or None when it is not up.
        #: `tick` counts it down and emits the one action that ends the session.
        self._sleep_ms = None
        #: THE FRAME METER, CONSTRUCTED HERE AND NEVER PER FRAME. It is not
        #: injected like every other capability in this constructor, and the
        #: difference is that it has no seam: it holds three integers, touches
        #: no hardware and reads no clock of its own -- the seam hands it the
        #: `ticks_diff` it was already computing. An injected meter would be a
        #: capability a fixture could forget to supply, on the one screen whose
        #: job is to work when nothing else does.
        self.frames = FrameHealth()

    def idle_busy(self):
        """True while the one-frame seam must finish an irreversible action."""

        # The clock and score commits are synchronous inside the pressed frame,
        # whose edge already refreshes inactivity.  The sleep note is the only
        # transient that spans frames, so it alone needs a busy latch here.
        return self._sleep_ms is not None

    def idle_draft(self):
        """True only while hand-set clock fields are still scratch state."""

        return (
            self.screen == CLOCK
            and self._clock_result not in (
                settings_copy.CLOCK_RESULT_SET,
                settings_copy.CLOCK_RESULT_VOLATILE,
            )
        )

    # -- state the view reads ------------------------------------------------

    @property
    def library(self):
        """True when the BadgeLink shared library was found on this badge.

        A PROPERTY OVER A STORED BOOLEAN, kept rather than flattened to an
        attribute, because it is read on a draw path by four screens and every
        one of them reads it by this name. Nothing in the tile can change it: the
        payload is either installed or it is not, and leaving an app is
        `machine.reset()`.
        """
        return self._library

    def transport_state(self):
        """The transport's own queryable state literal, or ``None``.

        ``polltransport`` exposes ``state`` on both ``PollLoop`` and its
        ``PollTransport`` adapter, so either object works here and neither is
        imported.
        """
        if self._transport is None:
            return None
        return getattr(self._transport, "state", None)

    def network_enabled(self):
        if self._network_control is None:
            return None
        value = getattr(self._network_control, "enabled", None)
        return value if isinstance(value, bool) else None

    def push_enabled(self):
        """The wearer's durable answer, or ``None`` with no controller."""
        if self._push_control is None:
            return None
        value = getattr(self._push_control, "enabled", None)
        return value if isinstance(value, bool) else None

    def push_mode(self):
        """The transport's OWN answer about what push is doing right now.

        Read through on every build, never cached: a cached mode is the "assumed
        from the last press" failure the owner's Card PW rule forbids.
        """
        if self._push_control is None:
            return None
        reader = getattr(self._push_control, "mode", None)
        if not callable(reader):
            return None
        value = reader()
        return value if isinstance(value, str) else None

    def _push_word(self, name):
        """Call a one-word `_PushControl` diagnostic, or answer ``None``.

        THREE FAIL-SOFT LAYERS, AND EACH ONE IS A REAL BADGE.

        1. `getattr`, because `/system/lib` and this app are installed by
           SEPARATE steps (OWNER-DECISIONS #1): a badge carrying a
           `network_runtime` from before 2026-08-26 has a `_PushControl` with no
           `cause` and one from before this stitch has no `previous_cause`, and a
           bare `self._push_control.cause()` there is an AttributeError inside
           `update()` -> `fatal_error` -> `machine.reset()`, every frame, for
           ever. Missing accessor means the screen shows exactly what it showed
           before the accessor existed and no extra line.
        2. `try/except`, because these readers are not field reads the way `mode`
           is. `NetworkService.push_cause` walks the live link, consults the
           placement predicate and does a LAZY `import pushlink` to classify a
           refusal -- a `/system/lib` missing that module raises ImportError from
           inside the call -- and `push_cause_previous` reads a monotonic clock to
           age the latch. A diagnostic may not be the thing that crashes the badge
           it is diagnosing.
        3. the type check, so a controller that returns a number or an object
           degrades to no line rather than to a formatted repr.

        ONE HELPER FOR BOTH READERS ON PURPOSE. Two copies of a four-layer guard
        is two places for a layer to be dropped, and the layer that gets dropped
        is the one whose absence is invisible until a badge resets in a loop.
        """
        if self._push_control is None:
            return None
        reader = getattr(self._push_control, name, None)
        if not callable(reader):
            return None
        try:
            value = reader()
        except Exception:  # noqa: BLE001 - see layer 2 above
            return None
        return value if isinstance(value, str) else None

    def push_cause(self):
        """WHY push is not carrying, as one word, or ``None``.

        Guarded by :meth:`_push_word`, which carries the reasoning. Read through
        on every build for the same Card PW reason `push_mode` is: this answer
        changes when the wearer WALKS somewhere.
        """
        return self._push_word("cause")

    def push_cause_previous(self):
        """The cause in force BEFORE this screen was opened, or ``None``.

        THE ACCESSOR THAT EXISTS BECAUSE READING DESTROYS THE ANSWER.
        `settings/__init__.py` calls `set_active(True)` while this tile is open,
        which GRANTS the OWNER RULING #22 placement that `push_cause()` would
        have reported -- so `CAUSE_PLACEMENT` is structurally unreachable from
        :meth:`push_cause` here, and that is the exact mechanism that hid the
        2026-08-26 doorbell root cause for a whole session. The runtime latches
        the cause it replaces so this panel can answer the question an operator
        actually has.

        ``None`` IS AN ORDINARY ANSWER, NOT AN EDGE CASE, and it became a common
        one when the latch got an age: it expires after
        `network_runtime.PUSH_CAUSE_LATCH_MS` and an expired latch is DROPPED
        rather than annotated, so this returns None on any badge whose doorbell
        has been quiet for longer than that window. `push_view` renders nothing
        for None, which is why no reserved-but-empty row appears and why a latch
        that expires between two frames costs no layout shift: the line is absent
        in both, or present in one and absent in the next with the question
        moving up one pitch exactly as it does when the LIVE cause clears.

        Guarded by :meth:`_push_word` for the same three reasons `push_cause` is.
        """
        return self._push_word("previous_cause")

    def push_diagnostics(self):
        """The runtime's own push counters, as a dict, or ``None``.

        SAME THREE FAIL-SOFT LAYERS AS :meth:`_push_word`, AND EVERY ONE OF THEM
        IS A REAL BADGE -- `getattr` because `/system/lib` and this app are
        installed by SEPARATE steps and a badge carrying a `network_runtime`
        from before 2026-08-27 has a `_PushControl` with no `diagnostics`;
        `try/except` because the forward reaches `PushLink.snapshot()`, which
        walks the policy and the client and is not a field read; a type check
        because a controller answering a list would otherwise reach `.get()`.
        An AttributeError inside `update()` is `fatal_error` ->
        `machine.reset()`, every frame, for ever.

        NOT SHARED WITH :meth:`_push_word` even though the shape is identical,
        because the two disagree on the last layer: that one demands `str` and
        this one demands `dict`, and a helper taking the type as an argument
        would be a guard whose strictness is a caller's decision. That is the
        layer whose absence is invisible until a badge resets in a loop.

        READ ONCE PER VIEW BUILD, AND ONLY ON ITS OWN SCREEN.
        `NetworkService.push_diagnostics` builds two dicts per call, so
        :meth:`view` calls this from the `DIAG` branch and nowhere else -- the
        menu row deliberately carries no value for exactly this reason.
        """
        if self._push_control is None:
            return None
        reader = getattr(self._push_control, "diagnostics", None)
        if not callable(reader):
            return None
        try:
            value = reader()
        except Exception:  # noqa: BLE001 - a reset is the alternative
            return None
        return value if isinstance(value, dict) else None

    def clock_diagnostics(self):
        """The runtime's own wall-clock verdict, as a dict, or ``None``.

        **OFF THE NETWORK CONTROL AND NOT OFF `push_control`, WHICH IS THE ONE
        DECISION IN THIS METHOD.** The state worth reporting is a badge whose
        clock is not plausible: `clock_boot.resync` raises rather than failing
        soft (verified TLS cannot check a certificate date without a clock),
        `DeviceBackend._build_loop` never finishes, no `PollLoop` exists and no
        doorbell is ever built -- so `push_control()` is exactly what a badge in
        that state does NOT have, and an accessor hung there would be
        unreachable in every case it was added for. The tile is handed the
        service itself as `network_control`, so this reads through that.

        SAME THREE FAIL-SOFT LAYERS AS :meth:`push_diagnostics`, and each one is
        a real badge: `getattr` because `/system/lib` and this app are installed
        by SEPARATE steps and a runtime from before this method has no such
        accessor; `try/except` because the forward reads a clock and walks the
        backend rather than reading a field; a type check because a controller
        answering a list would reach `.get()`. An AttributeError inside
        `update()` is `fatal_error` -> `machine.reset()`, every frame, for ever
        -- on the screen whose whole job is to work when nothing else does.

        READ ONCE PER VIEW BUILD, AND ONLY ON ITS OWN SCREEN, for
        `push_diagnostics`' reason: it builds a dict and reads the wall clock,
        and the menu is rebuilt every frame of every session.
        """
        if self._network_control is None:
            return None
        reader = getattr(self._network_control, "clock_diagnostics", None)
        if not callable(reader):
            return None
        try:
            value = reader()
        except Exception:  # noqa: BLE001 - a reset is the alternative
            return None
        return value if isinstance(value, dict) else None

    def wifi_diagnostics(self):
        """`ResilientWiFi`'s own record, as a dict, or ``None``.

        THE VALUES EXISTED ALL ALONG AND THE PATH TO A READER DID NOT.
        `snapshot()` has returned {state, reason, attempts, failures,
        connected_ms} every frame since the module was written, and its only
        consumers were two EDGE-GATED serial emitters -- so a badge that never
        associates emitted nothing at all, which is exactly the badge somebody
        needs to explain. See :meth:`_service_record` for the three fail-soft
        layers and why they are not shared with `_push_word`.
        """
        return self._service_record("wifi_diagnostics")

    def link_diagnostics(self):
        """The path to the server, as a dict, or ``None``.

        **THIS IS WHERE `NetworkService.last_error` FINALLY REACHES A READER.**
        A malformed BadgeLink value raises `CredentialError` inside
        `DeviceBackend.__init__`, the factory's containment handler puts the
        exact sentence in that field, and until now NO VIEW read it -- so a
        badge that could name the wrong field in `/secrets.py` drew "Can't
        reach the server" instead.
        """
        return self._service_record("link_diagnostics")

    def identity(self):
        """Who this badge is, as a dict, or ``None``.

        READ ON DIAGNOSTICS PAGE 4 AND NOWHERE ELSE, which is what makes it
        affordable: the forward reaches `os.uname()` and a cached
        `os.urandom(16)`, and :meth:`view` is rebuilt every frame.
        """
        return self._service_record("identity")

    def score_diagnostics(self):
        """The score drain's two fields, as a dict, or ``None``.

        **IT READS `snapshot()` AND NOT A PAGE-SCOPED ACCESSOR, AND THAT IS A
        DECLARED COMPROMISE RATHER THAN AN OVERSIGHT.** Every other reading on
        this screen comes through a projection built for it --
        `push_diagnostics`, `clock_diagnostics`, `wifi_diagnostics`,
        `link_diagnostics`, `identity` -- each one a dict of the handful of
        fields its page draws. The right sixth member of that family is a
        `NetworkService.score_diagnostics()` publishing `scores_pending`,
        `scores_stalled` and `scores_enabled`, and it belongs in
        `badgelink/badge/badgelink/network_runtime.py`, WHICH THIS LANE DOES NOT
        OWN. `snapshot()` is the accessor that exists today and already carries
        both fields, so the page is real on a badge now instead of waiting on
        another lane's file. **If that accessor is ever added, this method is
        the one line that changes and nothing above it moves.**

        THE COST IS BOUNDED AND IT WAS CHECKED RATHER THAN ASSUMED.
        `snapshot()` builds one dict of about twenty field reads plus the
        doorbell's own snapshot -- the same order as `push_diagnostics`, which
        pages 1-3 already pay per frame. Its one file touch is
        `scorebox.pending`, and `scorebox.slots`' own docstring prices that at
        "ONE open and ONE decode of a few hundred bytes, which is inside the
        budget `test_cx10_boot_json_cost.FirstFrameTests` enforces (one open,
        one decode per boot frame)" -- and it happens ONCE PER BOOT, because the
        module caches the slots in RAM afterwards.

        READ ON PAGE 5 AND NOWHERE ELSE, which is what makes even that
        affordable: :meth:`view` is rebuilt every frame on every screen.

        Same three fail-soft layers as :meth:`_service_record`, through it.
        """
        return self._service_record("snapshot")

    def _service_record(self, name):
        """One dict off the network control, or ``None``.

        OFF `_network_control` AND NOT OFF `_push_control`, for
        :meth:`clock_diagnostics`' stated reason: a badge with no plausible
        clock or no radio has NO DOORBELL, so an accessor hung there would be
        unreachable in every case it exists for.

        THREE FAIL-SOFT LAYERS AND EACH ONE IS A REAL BADGE.

        1. `getattr`, because `/system/lib` and this app are installed by
           SEPARATE steps (OWNER-DECISIONS #1) and a runtime older than the
           accessor has no such method; a bare call is an AttributeError inside
           `update()` -> `fatal_error` -> `machine.reset()`, every frame, for
           ever, on the one screen whose job is to work when nothing else does.
        2. `try/except`, because these forwards walk a backend and touch native
           calls (`ifconfig`, `uname`). A diagnostic may not be the thing that
           crashes the badge it is diagnosing.
        3. the type check, because a stand-in answering a list would reach
           `.get()`.

        NOT SHARED WITH `_push_word`, which demands `str` where this demands
        `dict` -- a helper taking the type as an argument would be a guard whose
        strictness is a caller's decision, and that is the layer whose absence
        is invisible until a badge resets in a loop.

        **`None` MEANS "THIS BADGE CANNOT TELL YOU", and the builders draw a
        sentence saying exactly that -- never zeroes, never `no`.**
        """
        if self._network_control is None:
            return None
        reader = getattr(self._network_control, name, None)
        if not callable(reader):
            return None
        try:
            value = reader()
        except Exception:  # noqa: BLE001 - a reset is the alternative
            return None
        return value if isinstance(value, dict) else None

    def row(self, index=None):
        return self.rows[self.index if index is None else index]

    def row_value(self, row):
        """The right-hand word on a menu row: the live state, at a glance."""
        if row == ROW_NETWORK:
            if self.network_enabled() is False:
                return _STATUS_WORD[NET_OFF]
            return _STATUS_WORD[transport_status(self.transport_state())]
        if row == ROW_PUSH:
            if not self.library:
                return settings_copy.VALUE_UNAVAILABLE
            return settings_copy.PUSH_WORDS[push_mode(self.push_mode())]
        if row == ROW_BRIGHT:
            # THE WORD, NOT THE NUMBER. `HIGH` is what the wearer chose and `80`
            # is how the panel is driven; a row that reported the second would
            # be asking somebody to learn a scale to read a status line.
            return backlight.name(self.brightness)
        # DIAGNOSTICS CARRIES NO VALUE, AND THAT IS A COST DECISION AS WELL AS A
        # COPY ONE. The obvious glance value is the latched worst frame, and it
        # would be wrong twice: the menu model is rebuilt every frame, so a value
        # that moves makes the ROOT screen redraw and rebuilds a `ui.ListView`
        # row plate (an image allocation) each time it changes -- on the screen
        # whose whole job is to cost nothing. And the push half would need
        # `push_diagnostics()`, which builds two dicts per call, on every frame
        # of the menu rather than on the screen that asked for it. The row is a
        # door, like Sleep and Scores.
        return ""

    def menu_view(self):
        rows = []
        for row in self.rows:
            rows.append({
                "id": row,
                "label": ROW_LABELS[row],
                "value": self.row_value(row),
            })
        return {
            "screen": MENU,
            "title": "Settings",
            "index": self.index,
            "rows": rows,
            # A is inert at the app root: HOME is the accepted route to the
            # launcher (button rules 9.4, owner ruling 2026-08-16) and printing
            # a label for it is forbidden by the same section.
            "softkeys": ("", settings_copy.OPEN, ""),
        }

    def menu_label(self, index):
        """One composed row string, for ``ui.ListView``'s ``label_for``."""
        row = self.rows[index]
        return "{}  {}".format(ROW_LABELS[row], self.row_value(row))

    def view(self):
        """The current screen, whichever it is."""
        if self.screen == MENU:
            return self.menu_view()
        if self.screen == NETWORK:
            page = self._page % NETWORK_PAGES
            # **PAGE-SCOPED READS, AND THEY ARE NOT AN OPTIMISATION.** This
            # method is rebuilt EVERY FRAME by the seam, so what a page reads is
            # what that page costs ~37 times a second. Scoping is the reason
            # `resolver_snapshot`'s `wlan.ifconfig()` is affordable on this
            # screen at all: page 2 never pays it.
            #
            # ⚠ PAGE 1 READS BOTH, AND THAT IS A DELIBERATE DEPARTURE FROM THE
            # "pages 1-2 read the radio alone" rule. Its stage line is the whole
            # path in one word, and two of that word's answers live on the LINK
            # record: `credential` comes from `NetworkService.last_error` (which
            # is filled in ABOVE the backend check, so it is free in exactly the
            # fault case -- there is no backend to walk), and `DNS`/`TLS` come
            # from the phase split. A page 1 that could not say `Stage: TLS` on
            # a badge whose venue blocks 443 would not be "the answer, no
            # scrolling required", which is the only reason page 1 exists.
            return network_view(
                self.transport_state(),
                library=self.library,
                network_enabled=self.network_enabled(),
                network_controllable=self._network_control is not None,
                page=page,
                wifi=self.wifi_diagnostics() if page < 2 else None,
                link=(self.link_diagnostics()
                      if page == 0 or page >= 2 else None),
            )
        if self.screen == PUSH:
            return push_view(
                self.push_mode(),
                library=self.library,
                controllable=self._push_control is not None,
                enabled=self.push_enabled(),
                cause=self.push_cause(),
                previous=self.push_cause_previous(),
            )
        if self.screen == DIAG:
            page = self._page % DIAG_PAGES
            # PAGE-SCOPED, for the Network screen's reason above and with the
            # same per-frame arithmetic. `push_diagnostics` builds two dicts per
            # call and page 4 needs none of them; `identity` reaches
            # `os.uname()` and is what page 4 alone pays for.
            return diag_view(
                self.push_diagnostics() if page < 3 else None,
                library=self.library,
                worst_ms=self.frames.worst_ms,
                measured=self.frames.measured,
                sweep_ms=self.frames.phase_ms,
                sweep_period_ms=self.frames.period_ms,
                clock=self.clock_diagnostics() if page == 0 else None,
                page=page,
                cause=self.push_cause() if page == 2 else None,
                previous=self.push_cause_previous() if page == 2 else None,
                identity=self.identity() if page == 3 else None,
                # PAGE 5 ALONE, and it is the most expensive read on this
                # screen: `snapshot()` is the whole service record rather than a
                # projection, because the projection that should exist lives in
                # a file this lane does not own. See
                # :meth:`Settings.score_diagnostics`.
                scores=self.score_diagnostics() if page == 4 else None,
            )
        if self.screen == SLEEP:
            return sleep_view()
        if self.screen == BRIGHT:
            return bright_view(self.brightness)
        if self.screen == SCORES:
            return scores_view(self._scores_result)
        if self.screen == CLOCK:
            return clock_view(self._clock_fields
                              if self._clock_fields is not None
                              else CLOCK_EVENT_LOCAL_FIELDS,
                              self._clock_stop, self._clock_row,
                              self._clock_result)
        # THE MENU IS THE FALL-THROUGH, and it is a real one rather than a
        # tidy default: `screen` is only ever set from `ROW_SCREENS` or back to
        # `MENU`, so this is unreachable -- but `view()` runs on the draw path,
        # where returning `None` is an AttributeError inside `update()`, which
        # is `fatal_error` -> `machine.reset()`, every frame, for ever. It used
        # to fall through to the pair screen for the same reason.
        return self.menu_view()

    # -- input ---------------------------------------------------------------

    def press(self, key):
        """One key edge. Returns the actions the seam must perform.

        THE LIST IS THE SEAM'S WORK ORDER AND NOTHING ELSE. It used to also
        carry the pair flow's server legs, which is why it exists at all; today
        every entry is something only the hardware layer can do -- a backlight
        write, a clock write, a network switch, a score wipe. Empty is the
        ordinary answer.
        """
        if key == "UP":
            return self._move(-1)
        if key == "DOWN":
            return self._move(1)
        if self.screen == SLEEP:
            # EVERY KEY IS INERT while the note is up, and the bar says so by
            # drawing nothing. There is no cancel (see `SLEEP_NOTE_MS`), so a
            # key that did anything here would be an unlabelled command on the
            # one screen where the wearer cannot see the result of it.
            return []
        if self.screen == MENU:
            if key == "B":
                self.screen = ROW_SCREENS[self.row()]
                if self.screen == SLEEP:
                    self._sleep_ms = SLEEP_NOTE_MS
                if self.screen == SCORES:
                    # OPENING A QUESTION, NOT ANSWERING ONE, and the state is
                    # cleared on the way IN rather than on the way out: a wearer
                    # who erased, read the result and came back must meet the
                    # question again, not somebody else's answer to it.
                    self._scores_result = None
                if self.screen == CLOCK:
                    # SEEDED ON THE WAY IN, FROM THE BADGE'S OWN CLOCK, for the
                    # same reason: a wearer who set the clock, read the note and
                    # came back must see what the badge NOW holds, not the fields
                    # they left behind. It is also the only moment the reading is
                    # worth paying for -- `row_value` deliberately never asks,
                    # because the root screen is rebuilt every frame.
                    self._open_clock()
                if self.screen in PAGES:
                    # OPENED ON THE ANSWER PAGE, EVERY TIME. Same rule as
                    # `_scores_result` and `_clock_fields` above: an operator
                    # who left on page 4 and came back must meet the answer, not
                    # somebody else's page -- and "press DOWN twice and read me
                    # the third line" is only an instruction if page 1 is where
                    # everyone starts.
                    self._page = 0
            return []
        if self.screen == BRIGHT:
            # BEFORE THE GENERIC `A` BRANCH BELOW, WHICH IS THE WHOLE POINT OF
            # PUTTING IT HERE. A is a DIRECTION on this screen (see
            # `bright_view` for the rule and the deviation it declares), so
            # falling through to "A returns to the menu" would leave the wearer
            # with a ladder they can only climb.
            return self._bright_key(key)
        if self.screen == CLOCK:
            # AND HERE SINCE 2026-08-28, FOR THE SAME REASON AND ON THE OWNER'S
            # REQUEST. A is LEFT on the clock editor now, so it cannot fall
            # through to the generic branch either -- but unlike BRIGHTNESS this
            # screen keeps §I2's five-A test, because A at the LEFT END of a row
            # leaves and the bar says `BACK` there. `_clock_key` owns that.
            return self._clock_key(key)
        if key == "A":
            # Labelled, and commits nothing (I2). On the erase question it is the
            # KEEP the bar promises, which is the same behaviour under a
            # different word rather than a second branch.
            self.screen = MENU
            return []
        if self.screen == DIAG:
            # C RESTARTS THE MEASUREMENT AND NOTHING ELSE ACTS. Reached AFTER
            # the generic A branch, because A means what it means everywhere
            # else. The key exists because the stutter meter's method needs a
            # floor you can zero: hold a steady animation, trigger ONE suspect
            # operation by hand, read what it cost. A latch you cannot drop
            # answers that question exactly once per boot.
            #
            # NO ACTION IS RETURNED. Everything this press changes lives in RAM
            # in this object, so there is nothing for the seam to perform -- and
            # the seam prints per action, which is a `print` a wearer's press
            # would put on the frame path this screen exists to measure.
            if key == "C":
                self.frames.reset()
            return []
        if self.screen == SCORES:
            # B IS INERT HERE (B7), and only C acts. Reached AFTER the generic A
            # branch because A means exactly what it means everywhere else -- and
            # the answered screen has no verb at all, so a second C cannot erase
            # again over a result the wearer is reading.
            if key != "C" or self._scores_result is not None:
                return []
            if self._score_control is None:
                # NOT A CRASH AND NOT A LIE. A tile with no wipe capability
                # cannot have erased anything, so it says so on the same screen
                # the wearer is already looking at.
                self._scores_result = False
                return []
            self._scores_result = bool(self._score_control.wipe())
            return [{"type": "scores_erased", "ok": self._scores_result}]
        if self.screen == NETWORK:
            if key == "B" and self._network_control is not None and self.library:
                before = self.network_enabled()
                if before is None:
                    return []
                after = bool(self._network_control.set_enabled(not before))
                return [{"type": "network_set", "enabled": after}]
            return []
        if self.screen == PUSH:
            if self._push_control is None or not self.library:
                return []
            # YES and NO, not a toggle: the answer is the value, so pressing the
            # same key twice cannot walk the preference somewhere the wearer did
            # not ask for. The reported value comes back from the controller.
            if key == "B":
                wanted = True
            elif key == "C":
                wanted = False
            else:
                return []
            after = bool(self._push_control.set_enabled(wanted))
            return [{"type": "push_set", "enabled": after}]
        return []

    def _move(self, delta):
        if self.screen == SLEEP:
            return []
        if self.screen == MENU:
            # By one, and wrapping, per B3.
            self.index = (self.index + delta) % len(self.rows)
        elif self.screen == CLOCK:
            # THE VALUE IS ON THE AXIS WITH THE REPEAT CURVE, which is the one
            # place in this tile that is true. `clock_view` has the rule (I1 was
            # rewritten to allow exactly a time field here) and the reason it is
            # safe where BRIGHTNESS's ladder was not: a step writes nothing but
            # an integer in RAM, so a lean on the key cannot become a burst of
            # 185 ms flash stalls. Returns no action for the same reason -- there
            # is nothing for the seam to perform until SET.
            self._clock_step(delta)
        elif self.screen in PAGES:
            # WRAPPING, BY ONE, PER B3 -- the same motion the root menu already
            # has, so a wearer who has scrolled that list has already been
            # taught this one. A mashing thumb always arrives back at page 1,
            # which is the page that answers the question.
            #
            # AFTER THE `CLOCK` BRANCH ON PURPOSE. That screen's UP/DOWN are a
            # VALUE, not a page, and testing it first is what keeps the editor
            # untouched by paging.
            #
            # Returns no action: nothing here is for the seam. The seam PRINTS
            # per action, and a print on a page turn is the 1,018 ms stalled
            # frame this screen exists to explain -- the transition print is
            # keyed on the page instead, once per turn, in `settings/__init__`.
            self._page = (self._page + delta) % PAGES[self.screen]
        # UP AND DOWN ARE INERT ON THE BRIGHTNESS SCREEN and that falls out of
        # this shape rather than needing a branch: there is no list there to
        # move. It is worth stating because the OTHER obvious wiring -- the
        # ladder on UP/DOWN, which is where a scroll key's meaning would suggest
        # putting it -- is the one arrangement that could not work: UP and DOWN
        # are the only keys in this app that auto-repeat (`ui.Axis`, button rule
        # B4), and auto-repeat on a value that WRITES FLASH turns a lean on a
        # key into a burst of 185 ms stalls.
        return []

    def _bright_key(self, key):
        """One rung, or the way back. Returns the action the seam performs.

        ONE PRESS PER RUNG, CLAMPED, NEVER CYCLING. `backlight.step` is the
        motion and its docstring carries the argument: brightness used to cycle
        on one key, so coming back one level from FULL cost four presses and the
        wearer had to remember the order.

        AN END-OF-LADDER PRESS DOES NOTHING AT ALL -- no action, so no panel
        write and no flash write. Its key draws no label, so this is reachable
        only from a hand-edited file, and a write with no change is a stall the
        wearer paid for nothing.

        THE MODEL MOVES FIRST AND THE SEAM PERFORMS SECOND, which is how the
        panel gets ahead of the file (button rule B6: update the screen first,
        write later). The seam's ordering is pinned in
        `settings/tests/test_settings_brightness.py`, because it is the half of
        the feel that this pure module cannot enforce.
        """
        if key == "B":
            # A and C have already applied everything, so there is nothing to
            # commit and nothing to undo: B is a labelled way back and no more.
            # It lands on the MENU with the selection untouched, so a wearer
            # stepping the ladder twice does not have to find the row again.
            self.screen = MENU
            return []
        if key == "A":
            direction = -1
        elif key == "C":
            direction = 1
        else:
            return []
        level = backlight.step(self.brightness, direction)
        if level == self.brightness:
            return []
        self.brightness = level
        return [{"type": "brightness_set", "level": level}]

    def _open_clock(self):
        """Seed the editor from the badge's own clock. Never raises.

        THE SAME THREE FAIL-SOFT LAYERS AS EVERY OTHER CONTROLLER READ IN THIS
        FILE, and each is a real badge: `getattr` because a seam built before
        this screen has no `read`; `try/except` because the forward touches a
        clock rather than a field; and `clock_seed` is total, so a stand-in
        answering nonsense lands on the EVENT instant instead of on a screen.
        An exception inside `update()` is `fatal_error` -> `machine.reset()`.
        """
        reading = None
        if self._clock_control is not None:
            reader = getattr(self._clock_control, "read", None)
            if callable(reader):
                try:
                    reading = reader()
                except Exception:  # noqa: BLE001 - a reset is the alternative
                    reading = None
        self._clock_fields = clock_seed(reading)
        # THE HOUR, ON THE TIME ROW. See `_clock_row` for the owner's reasoning:
        # a badge being hand-set is a badge at the event, so its date is already
        # right and the repair is a nudge to an hour.
        self._clock_row = CLOCK_ROW_TIME
        self._clock_stop = CLOCK_HOUR
        self._clock_result = None

    def _clock_step(self, delta):
        """One press of UP or DOWN, and it also clears a stale refusal.

        THE WARNING GOES THE MOMENT THE VALUE MOVES. A line saying "too early"
        over a date the wearer has since corrected is a true statement about a
        value that is no longer on screen, which is the shape of thing a reader
        acts on wrongly. Cleared on the STEP rather than on the next SAVE, so the
        screen never disagrees with itself between two presses.

        **INERT ON SAVE AND CANCEL**, and refused HERE rather than relied on
        downstream. `clock_step` falls through on a stop that is not a field, so
        calling it would be harmless -- but it would also clear the refusal line
        for a press that changed nothing, which is the one visible difference and
        the wrong one.
        """
        if self._clock_fields is None:
            self._open_clock()
        if self._clock_result in (settings_copy.CLOCK_RESULT_SET,
                                  settings_copy.CLOCK_RESULT_VOLATILE):
            # The note is up and the editor is gone; nothing is being edited, so
            # a scroll key has no field to move. Inert rather than silently
            # editing a value the wearer cannot see.
            return
        if self._clock_stop in CLOCK_ACTIONS:
            return
        self._clock_fields = clock_step(self._clock_fields, self._clock_stop,
                                        delta)
        self._clock_result = None

    def _clock_key(self, key):
        """A/C move the cursor, B acts, and nothing else acts. Returns actions.

        **B WITH THE CURSOR ON SAVE IS THE ONLY THING IN THIS SCREEN THAT WRITES
        ANYTHING**, which is what lets UP/DOWN carry the value at all -- and it
        is the fix §I2 records for this screen's ancestor: `schedule`'s dial was
        entered with B and could only be LEFT with B, and B wrote the RTC, so the
        only way out of the mode was to overwrite the clock the app depended on.
        Here there are two ways out and neither writes.

        **THIS METHOD IS REACHED BEFORE `press`'s GENERIC A BRANCH SINCE
        2026-08-28, which is the whole point of moving it there.** A is a
        DIRECTION on this screen now (see `clock_view` for the owner's request
        and the rule behind each key), so falling through to "A returns to the
        menu" would leave the wearer a track they can only walk rightward. The
        BRIGHTNESS screen is placed the same way for the same reason.

        **AND A AT THE LEFT END STILL LEAVES**, which is what keeps §I2's five-A
        test passing with A re-tasked: the walk falls out of its own left end
        rather than wrapping, and the bar says `BACK` there instead of `LEFT` so
        the exiting press is one the wearer can see coming. `clock_view`'s
        docstring records the cyclic alternative and why it was refused.

        THE GATE RUNS BEFORE THE SEAM IS TOUCHED. `clock_verdict` is
        `clock_boot.evaluate_ntp`'s rule, so a value TLS would refuse never
        reaches either clock -- a hand-set 2019 accepted locally would leave the
        wearer looking at "Clock set" while every handshake went on failing,
        which is the screen having quietly made a broken badge LOOK repaired.

        **AND THE CONVERSION RUNS BEFORE THE GATE.** The fields are event-local
        since 2026-08-28 and `evaluate_ntp` judges a UTC epoch, so local -> UTC
        happens ONCE, at the top, and everything after it -- the verdict, the two
        clock writes, the weekday and the epoch handed to the seam -- reads the
        SAME converted tuple. Ordering it the other way would slide the accepted
        window seven hours and hand `machine.RTC()` a local time labelled UTC,
        with nothing on the badge to say so: the value would still be plausible,
        still be written, and still be wrong. `test_settings_clock` pins the
        order at both bounds rather than trusting this comment.
        """
        if self._clock_fields is None:
            self._open_clock()
        if self._clock_result in (settings_copy.CLOCK_RESULT_SET,
                                  settings_copy.CLOCK_RESULT_VOLATILE):
            # The note has no verb (its bar is BACK and two empty slots), so a
            # thumb that kept pressing cannot set the clock a second time.
            return []
        track = CLOCK_TRACKS[self._clock_row]
        position = track.index(self._clock_stop)
        if key == "A":
            if position == 0:
                # THE LEFT END IS THE WAY OUT (§I2), and it commits nothing: the
                # fields are integers in RAM and `_open_clock` re-seeds from the
                # badge's own clock on the way back in.
                self.screen = MENU
                return []
            self._clock_stop = track[position - 1]
            # THE REFUSAL STANDS THROUGH A CURSOR MOVE, here and on C: moving the
            # highlight does not change the value the warning is about, and a
            # warning that vanished when the wearer looked elsewhere would be a
            # warning they never got to read.
            return []
        if key == "C":
            if position < len(track) - 1:
                self._clock_stop = track[position + 1]
            # AND THE TRACK DOES NOT WRAP. Cancel is the last stop; a C there
            # draws no label (§I5) and does nothing, exactly as an end-of-ladder
            # press does on BRIGHTNESS.
            return []
        if key != "B":
            return []
        if self._clock_stop not in CLOCK_ACTIONS:
            # B ON A VALUE FIELD SWITCHES ROWS, and lands on the FIRST stop of
            # the row it arrives at rather than on the nearest one. Predictable
            # beats clever: a remembered per-row position is invisible state, and
            # the leftmost is where `BACK` appears on the bar, so a wearer who
            # switched rows by accident is one labelled press from leaving.
            self._clock_row = (CLOCK_ROW_DATE
                               if self._clock_row == CLOCK_ROW_TIME
                               else CLOCK_ROW_TIME)
            self._clock_stop = CLOCK_TRACKS[self._clock_row][0]
            return []
        if self._clock_stop == CLOCK_CANCEL:
            # THE LABELLED WAY OUT, and it is the same behaviour A has at the
            # left end under a different word -- deliberately, because a wearer
            # who has walked RIGHT to leave should not have to walk back.
            self.screen = MENU
            return []
        # THE ONE CONVERSION, AND EVERYTHING BELOW READS ITS RESULT. See the
        # docstring: the panel is event-local, both clocks and the gate are UTC.
        utc = clock_local_to_utc(self._clock_fields)
        epoch = clock_epoch(utc)
        verdict = clock_verdict(epoch)
        if verdict != CLOCK_PLAUSIBLE:
            # REFUSED ON THE EDITOR, with the typed value still on screen, so the
            # repair is one press away. `clock_view` draws the reason.
            self._clock_result = verdict
            return [{"type": "clock_rejected", "reason": verdict}]
        writer = getattr(self._clock_control, "write", None)
        if not callable(writer):
            # NOT A CRASH AND NOT A LIE. A tile with no clock seam -- a fixture,
            # the browser's drop-in path, or an app installed beside a helper
            # from before this screen -- cannot have written anything, so it says
            # so on the screen the wearer is already looking at. The same shape
            # the Scores row uses for a missing wipe, and `getattr` covers the
            # `None` control too: `getattr(None, "write", None)` is None.
            self._clock_result = settings_copy.CLOCK_RESULT_FAILED
            return [{"type": "clock_rejected",
                     "reason": settings_copy.CLOCK_RESULT_FAILED}]
        try:
            # UTC, NOT THE PANEL'S FIELDS. The badge's clock contract is UTC end
            # to end -- `clock_boot.resync` sets it from `gmtime` and `schedule`
            # converts back out of `event.utc_offset_min` -- so writing the local
            # digits here would apply the offset a SECOND time on the schedule
            # screen, which is the bug the deleted `Use UTC` line used to ask the
            # wearer to avoid by hand.
            result = writer(utc[CLOCK_YEAR], utc[CLOCK_MONTH], utc[CLOCK_DAY],
                            # ONE NUMBER FEEDS BOTH WRITES, Monday=0: computed
                            # here because the model owns the arithmetic and the
                            # seam owns only the two calls. FROM THE UTC DATE,
                            # which is the date going into the same tuple -- at
                            # -420 every event-local time from 17:00 is the next
                            # UTC day, and a weekday off by one is a PCF register
                            # disagreeing with the y/m/d beside it.
                            clock_weekday(utc[CLOCK_YEAR], utc[CLOCK_MONTH],
                                          utc[CLOCK_DAY]),
                            utc[CLOCK_HOUR], utc[CLOCK_MINUTE])
        except Exception:  # noqa: BLE001 - a reset is the alternative
            result = settings_copy.CLOCK_RESULT_FAILED
        if result not in (settings_copy.CLOCK_RESULT_SET,
                          settings_copy.CLOCK_RESULT_VOLATILE):
            # ANYTHING THIS BUILD DOES NOT RECOGNISE IS A FAILURE, not a note. A
            # seam from a different version answering a word this model has no
            # screen for must not leave the wearer reading "Clock set".
            result = settings_copy.CLOCK_RESULT_FAILED
        self._clock_result = result
        # THE EPOCH IS THE UTC ONE. `__init__` prints it as `SETTINGS_CLOCK
        # result=... epoch=...`, and it exists so a later certificate failure can
        # be correlated against the instant the badge was actually set to -- an
        # epoch seven hours off the stored clock would make that log a lie.
        return [{"type": "clock_set", "result": result, "epoch": epoch}]

    # -- the outside world ---------------------------------------------------

    def tick(self, elapsed_ms):
        """Advance the sleep note and feed the frame meter. Returns actions.

        IT ADVANCED A PAIR CLAIM TOO UNTIL 2026-08-28, which is why the note is
        counted first and short-circuits: a badge one frame from dormancy had no
        reason to advance a claim it would never finish. The short-circuit stays
        because it is still the correct shape -- nothing after it needs doing on
        a session that is about to end -- and because the frame meter above it
        must be fed on the dormancy frame like any other.

        ONE-SHOT: `_sleep_ms` becomes None as the action is emitted, so a seam
        whose sleep call somehow returns does not sleep again every frame.

        THE FRAME METER IS FED FIRST, ABOVE EVERY SHORT-CIRCUIT BELOW, and the
        placement is the measurement. `elapsed_ms` is the seam's own
        `ticks_diff` taken at the top of `update()`, so it is the ENTRY-TO-ENTRY
        gap -- the quantity `benchmark/badge/stutter_meter.py` could not see,
        because it timed its own `update()` while the networking ran in
        `service.poll()` afterwards and reported `worst=58 ms` during a 701 ms
        stall. Fed on EVERY screen, not only its own: the stalls worth catching
        happen on Network and Updates, where the runtime is allowed to
        establish, and a meter that counted only while somebody watched it would
        miss the frame they came to explain. `FrameHealth.tick` allocates
        nothing and prints nothing, which is what makes this free enough to sit
        on the frame path of every screen in the tile.
        """
        self.frames.tick(elapsed_ms)
        if self._sleep_ms is not None:
            self._sleep_ms -= elapsed_ms
            if self._sleep_ms > 0:
                return []
            self._sleep_ms = None
            return [{"type": "sleep"}]
        return []

    def sleep_failed(self):
        """The sleep did not take. Put the wearer back on the menu.

        REACHABLE IN EXACTLY TWO PLACES and neither is a wearer's fault: a
        `badge.sleep()` that raises something other than the browser's reset, and
        a runtime where the call simply returns. On hardware it does not return
        at all, so this is dead code there -- but without it `screen == SLEEP`
        with the countdown already spent is a screen with no exit but HOME, on
        the one screen whose whole bar is deliberately empty.

        IT IS NOT A CANCEL. Nothing can stop a sleep that was asked for; this
        only runs after the attempt, which is why the note has no key that could
        reach it and why `press` stays inert on that screen.
        """
        self._sleep_ms = None
        self.screen = MENU
