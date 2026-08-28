"""Pure view-model for the general-purpose Settings tile (OWNER-DECISIONS #2).

The owner ruled (2026-08-17, form SETTLED in the 2026-08-19 addendum) that the
permanent extra launcher tile is a **general-purpose Settings app** hosting the
**Pair** entry, plus a **network status** view — connected / paired /
stopped-because-revoked-or-expired / unreachable — carrying an on-screen "reboot
to retry" instruction, because a badge stopped on 403 holds until the next boot
(OWNER-DECISIONS #14; ``polltransport._enter_revoked``).

WHAT THIS MODULE IS. A drawing-agnostic, I/O-free state machine: the row list,
the selection, the screen routing, the key -> pairstate event wiring and the
transport-state -> wearer-copy mapping. Everything here runs under CPython, so
the whole tile's behaviour is fixture-testable and the device layer
(``settings_view``) is only pixels.

WHAT IT DELIBERATELY IS NOT. It does not reimplement the Pair or Confirm
screens. Card E landed those as ``badgelink.pairview`` view-models over the
``badgelink.pairstate`` machine (dynamic QR + countdown; 6-char match code, B
accepts; **no badge-side unpair exists in v2**), they are transport-agnostic and
tested, and this module CONSUMES them. Nothing here duplicates a pairview line
and nothing here offers an unpair.

WHY EVERY BADGELINK DEPENDENCY IS INJECTED AND NOTHING IS IMPORTED. BadgeLink's
shared modules install to ``/system/lib`` (OWNER-DECISIONS #1) and reach an app
only through the one ``sys.path.append`` line ``/system/main.py`` carries. A
badge whose ``/system/lib`` has not been refreshed in the same session as this
tile therefore has the tile and not the library — and a bare ``import pairview``
at module scope on that badge raises INSIDE ``launch()``, which resets the badge
(``docs/deploy.md``: "an import that raises inside ``launch()`` resets the badge
— every badge, not one"). So the app guards the import once, hands whatever it
found to this model, and a missing library degrades to one honest row instead of
a reset loop. ``launcher/menu/ui.py`` guards ``import loading`` for exactly the
same reason.

WHERE THE WORDS LIVE, AND WHY NOT HERE. Every wearer-facing string is in
``settings_copy`` (owner ruling, 2026-08-21: the old labels were protocol words,
not human words). This module still owns the DECISION of which string a state
gets; it does not own the string. Two consequences worth stating because both
are load-bearing:

* ``pairview``'s own copy is mapped through ``settings_copy``'s consumer-side
  tables in :meth:`Settings.pair_view` rather than edited in ``pairview`` — the
  shared view-models keep their words for their own tests and any other
  consumer, and the seam test fails if pairview ever publishes a title, line or
  label this app has no answer for.
* the softkey tuple a screen publishes is now the WEARER'S words (``YES`` /
  ``NO``), so the key -> event wiring reads ``softkey_events`` instead. Wiring
  on the printed label would have made every copy change a behaviour change.

BUTTON CONVENTIONS (``docs/badge-button-rules.md``, guidelines not laws):
B is the primary action on every screen (B1/B2); UP and DOWN move the selection
by one and wrap (B3); A is the labelled way back and **commits nothing** (I2) —
it returns to the Settings menu WITHOUT emitting a pairstate event, so a pair
flow already in the air keeps running and the wearer can leave a live QR to read
the network row and come back to it. The flow's own cancel/decline labels stay
where pairview put them, on B and C.

**ONE SCREEN DECLARES A DEVIATION, and it is this tile's first.** On BRIGHTNESS
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

# Screens this model routes between. The Pair screen's INNER screen id comes
# from pairview (PAIR / CONFIRM / PAIRED / ...); this is only the outer route.
MENU = "menu"
PAIR = "pair"
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

# Row identifiers. The tile is general-purpose on purpose: the owner's reasoning
# for one Settings tile over a tile per need was that other settings-shaped needs
# are already planned (battery visibility among them), so adding one is a row
# here and not a launcher negotiation.
ROW_PAIR = "pair"
ROW_NETWORK = "network"
ROW_PUSH = "push"
ROW_SLEEP = "sleep"
ROW_BRIGHT = "bright"
ROW_SCORES = "scores"
ROW_DIAG = "diag"

ROW_LABELS = {
    ROW_PAIR: settings_copy.ROW_PAIR_LABEL,
    ROW_NETWORK: settings_copy.ROW_NETWORK_LABEL,
    ROW_PUSH: settings_copy.ROW_PUSH_LABEL,
    ROW_SLEEP: settings_copy.ROW_SLEEP_LABEL,
    ROW_BRIGHT: settings_copy.ROW_BRIGHT_LABEL,
    ROW_SCORES: settings_copy.ROW_SCORES_LABEL,
    ROW_DIAG: settings_copy.ROW_DIAG_LABEL,
}
ROW_SCREENS = {
    ROW_PAIR: PAIR,
    ROW_NETWORK: NETWORK,
    ROW_PUSH: PUSH,
    ROW_SLEEP: SLEEP,
    ROW_BRIGHT: BRIGHT,
    ROW_SCORES: SCORES,
    ROW_DIAG: DIAG,
}

#: THE FILES "ERASE SCORES" TAKES, BESIDES THE UNDELIVERED SPOOL. One per game,
#: written by `shared/score_sink.py` and read as the wearer's high score.
#:
#: THIS TILE CARRIES ITS OWN COPY OF THE LIST AND DOES NOT IMPORT ONE, which is
#: the same decision `setup` made about `setup_state` and for a stronger
#: reason: `scorebox.GAME_STATE_PATHS` says the same five paths, but it lives in
#: `/system/lib`, which the production payload DOES NOT SHIP
#: (`apps-roster.json`: `production.system_lib.ship` is false). A wearer erasing
#: high scores that have nothing to do with networking must not need a networking
#: library to do it. `settings/tests/test_settings_scores.py` pins this list
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
#: Menu order. Pair first: it is the entry point decision #2 exists to ship.
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
#: badge that ships with no `/system/lib` at all -- which is the badge that SHIPS
#: (`apps-roster.json`: `production.system_lib.ship` is false) -- still needs to
#: be able to answer "is this thing dropping frames".
ROWS = (ROW_PAIR, ROW_NETWORK, ROW_DIAG, ROW_SCORES, ROW_BRIGHT, ROW_SLEEP)
#: The Updates row is CONDITIONAL: it appears only when the boot pump actually
#: has a doorbell to control. A row that describes a transport this badge does
#: not carry is a row that lies, and the tile already refuses to invent state.
#: Brightness is conditional on nothing: every badge has a panel, so it is the
#: second row after Sleep that means the same thing on an unprovisioned badge.
ROWS_WITH_PUSH = (ROW_PAIR, ROW_NETWORK, ROW_PUSH, ROW_DIAG, ROW_SCORES,
                  ROW_BRIGHT, ROW_SLEEP)

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


def network_view(transport_state, paired=False, owner_hint="", library=True,
                 network_enabled=None, network_controllable=False):
    """The network-status screen, per the OWNER-DECISIONS #2 addendum.

    ``reboot`` is the flag the addendum's "reboot to retry" instruction hangs
    off, and it is true for exactly one status: :data:`NET_STOPPED`, the 403
    verdict. ``polltransport`` refuses ``request_reconnect`` once revoked
    ("stop until the next boot"), so a RETRY softkey there would be a label that
    does nothing — the copy is the honest affordance.
    """
    status = transport_status(transport_state)
    # A controller is the authority for a deliberate local OFF.  This matters
    # during boot before a transport object exists: OFF is a user choice, not
    # the ambiguous "no session" state.
    if network_enabled is False:
        status = NET_OFF
    lines = []
    if not library:
        # An honest label for the one thing this tile cannot fake: the shared
        # library is not on this badge, so there is no state to report.
        lines.append(settings_copy.NET_NOT_INSTALLED)
    elif status == NET_CONNECTED:
        lines.append(settings_copy.NET_LINE_CONNECTED)
    elif status == NET_CONNECTING:
        lines.append(settings_copy.NET_LINE_CONNECTING)
    elif status == NET_UNREACHABLE:
        lines.append(settings_copy.NET_LINE_UNREACHABLE)
    elif status == NET_STOPPED:
        lines.append(settings_copy.NET_LINE_STOPPED)
        lines.append(settings_copy.NET_LINE_STOPPED_WHY)
    elif status == NET_OFF:
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

    if library:
        lines.append(
            settings_copy.NET_LINE_LINKED.format(
                owner_hint or settings_copy.NET_LINE_LINKED_ANON)
            if paired else settings_copy.NET_LINE_UNLINKED)
    if status == NET_STOPPED:
        lines.append(settings_copy.NET_LINE_REBOOT)
    lines = [settings_copy.ascii_fold(line) for line in lines]

    middle = ""
    event = ""
    if library and network_controllable:
        # A 403 may not be bypassed by reconnect, but the physical holder must
        # still be able to turn the radio OFF.  Once off, turning it on records
        # the next-boot intent; the revoked session itself stays terminal.
        if status != NET_STOPPED or network_enabled is True:
            middle = (settings_copy.STOP if network_enabled
                      else settings_copy.START)
            event = "network_toggle"
    return {
        "screen": NETWORK,
        "title": settings_copy.ROW_NETWORK_LABEL,
        "status": status,
        "transport_state": transport_state,
        "paired": bool(paired),
        "reboot": status == NET_STOPPED,
        "lines": lines,
        # The physical holder owns this policy.  It changes only the radio
        # preference/session and never edits the paired record.
        "softkeys": (settings_copy.BACK, middle, ""),
        "softkey_events": ("", event, ""),
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
    events = ("", "", "")
    if library and controllable:
        # THE Q&A PATTERN (owner ruling, 2026-08-21): one plain question, and
        # B/C answer it. YES/NO rather than a state-dependent TURN ON/TURN OFF —
        # which is the label pair that overran the 68 px softkey box — and the
        # answers are idempotent, so a wearer who presses YES twice has not
        # toggled themselves off.
        lines.append(settings_copy.PUSH_QUESTION)
        middle = settings_copy.BUTTON_WORDS["ACCEPT"]
        right = settings_copy.BUTTON_WORDS["DECLINE"]
        events = ("", "push_on", "push_off")
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
        "softkey_events": events,
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
        entry-to-entry quantity -- the seam computes it for the pair countdown
        and the sleep note, so this reads a number that was going to exist
        anyway rather than starting a second clock.
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


def diag_view(diagnostics, library=True, worst_ms=None, measured=False,
              sweep_ms=0, sweep_period_ms=SWEEP_PERIOD_MS):
    """The operator's screen: what push is doing, and how the frames are running.

    THE DESIGN RULE, and it is the reason this function is a formatter and not a
    machine: SURFACE WHAT THE RUNTIME ALREADY COMPUTES. Every push value here
    comes out of `PushLink.snapshot()` by way of
    `network_runtime.NetworkService.push_diagnostics()`; nothing on this path
    counts, derives or stores anything. The three 2026-08-27 incidents that
    forced the screen are in `settings_copy`'s diagnostics block, one per line
    of this body.

    IT DEGRADES IN TWO STEPS AND THEY MEAN DIFFERENT THINGS. No `/system/lib` is
    the SHIPPING badge (`apps-roster.json`: `production.system_lib.ship` is
    false) and says so with the tile's existing `NET_NOT_INSTALLED`. A library
    that is present but has no doorbell -- no push factory, or a runtime older
    than the accessor -- says `DIAG_NO_PUSH`, because "this badge cannot tell
    you" is a different fact from "BadgeLink is not installed" and both are
    different from a row of zeroes, which would be a measurement nobody took.

    THE FRAME LINES SURVIVE BOTH, because they are about the panel and every
    badge has one. That asymmetry is the whole reason the row is unconditional.

    ORDER: what push is, why it is that, how it got there, what it heard, what
    broke, and then the frame. The frame line is LAST because it is the one the
    moving bar underneath it belongs to, and because `settings_view._draw_body`
    reserves a band for every line still to come -- so the last line is the one
    guaranteed not to be squeezed out.
    """
    lines = []
    if not library:
        lines.append(settings_copy.NET_NOT_INSTALLED)
    elif not isinstance(diagnostics, dict) or not diagnostics:
        lines.append(settings_copy.DIAG_NO_PUSH)
    else:
        record = diagnostics
        mode = diag_text(record.get("mode"))
        lines.append(settings_copy.DIAG_LINE_MODE.format(
            mode if mode else settings_copy.DIAG_MISSING))
        source = record.get("policy_source")
        line = settings_copy.DIAG_POLICY_LINES.get(source)
        if line is None:
            # A source literal this build has never heard of, printed rather
            # than smoothed over -- and bounded, because it crosses the same
            # newer-`/system/lib` seam every other runtime string here does.
            bounded = diag_text(source)
            line = settings_copy.DIAG_POLICY_STATE.format(
                bounded if bounded else settings_copy.DIAG_MISSING)
        lines.append(line)
        lines.append(settings_copy.DIAG_LINE_LINK.format(
            _flag(record, "joined"), _flag(record, "socket_open"),
            _flag(record, "targeted")))
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
        error = diag_text(record.get("last_error"))
        if error:
            # ONLY WHEN THERE IS ONE. An empty error line is a band spent saying
            # nothing on a screen that has exactly eight of them.
            lines.append(settings_copy.DIAG_LINE_ERROR.format(error))
    if measured:
        lines.append(settings_copy.DIAG_LINE_WORST.format(_number(worst_ms)))
    else:
        lines.append(settings_copy.DIAG_LINE_WORST_NONE)
    lines = [settings_copy.ascii_fold(line) for line in lines]
    return {
        "screen": DIAG,
        "title": settings_copy.DIAG_TITLE,
        "reboot": False,
        "lines": lines,
        # THE PHASE, NOT A PIXEL. `settings_view` maps it onto the rail, so the
        # geometry stays where every other geometry decision in this tile is and
        # this module stays drawable on any canvas.
        "sweep": sweep_ms,
        "sweep_period": sweep_period_ms,
        # B DRAWS NOTHING AND DOES NOTHING. Everything on this screen is a
        # reading; the only command is the one that restarts the reading, and it
        # goes on C rather than on the key a thumb has been opening rows with.
        "softkeys": (settings_copy.BACK, "", settings_copy.DIAG_RESET),
        "softkey_events": ("", "", "frames_reset"),
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
        "softkey_events": ("" if down == percent else "brightness_down",
                           "",
                           "" if up == percent else "brightness_up"),
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
            "softkey_events": ("", "", "scores_erase"),
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
        "softkey_events": ("", "", ""),
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
        "softkey_events": ("", "", ""),
    }


# -- the pair entry ---------------------------------------------------------
#
# Key -> pairstate event. pairview publishes the label a key should carry
# ({"B": "ACCEPT", "C": "DECLINE"}); this is the other half of that contract,
# turning the label back into the event pairstate accepts. Keeping it a table
# means the app wires nothing by hand and the mapping is asserted in one test.
LABEL_EVENTS = {
    "PAIR": "pair_pressed",
    "CANCEL": "back",
    "ACCEPT": "accept",
    "DECLINE": "decline",
    "RETRY": "retry",
}

def _button_word(label):
    """pairview's protocol label -> the word printed over the button.

    An unmapped label falls through UNCHANGED rather than becoming blank: a key
    that can act must carry a word, and the seam test is what stops an unmapped
    label from being the normal case.
    """
    if not label:
        return ""
    return settings_copy.ascii_fold(
        settings_copy.BUTTON_WORDS.get(label, label))


def _pair_line(line):
    """pairview's body line -> the same fact in plain words."""
    return settings_copy.ascii_fold(settings_copy.PAIR_LINES.get(line, line))


#: What to feed back when a pairstate action has no driver to perform it. With
#: no BadgeLink session there is no server, so "start failed" is the TRUE
#: outcome, not a placeholder: pairview renders it "Could not reach the server."
#: A screen that sat on "Starting..." for ever would be the dishonest option.
_UNDRIVEN_FAILURES = {
    "pair_start": {"type": "pair_start_failed", "error": "pair_start_failed"},
    "pair_ack": {"type": "ack_failed", "error": "pair_ack_failed"},
    # pair_cancel and pair_decline need no server for the local screen to be
    # correct; the claim simply expires server-side.
}


class Settings:
    """The whole tile as a pure machine: rows, routing, and the pair wiring.

    ``pairview`` and ``pairstate`` are the real ``/system/lib`` modules when the
    library is installed and ``None`` when it is not. ``driver``, when given,
    performs pairstate actions (the server legs) and is the seam Card P5's demo
    path fills; with no driver every action that needs a server resolves to its
    honest failure event.
    """

    def __init__(self, pairview=None, pairstate=None, driver=None, base_url=None,
                 pair_state=None, transport=None, network_control=None,
                 push_control=None, brightness=None, score_control=None):
        if (pairview is None) != (pairstate is None):
            raise ValueError("pairview and pairstate must be supplied together")
        self._pairview = pairview
        self._pairstate = pairstate
        self._driver = driver
        self._base_url = base_url
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
        self.pair = None
        if pairstate is not None:
            self.pair = pair_state if pair_state is not None else pairstate.new_state()

    # -- state the view reads ------------------------------------------------

    @property
    def library(self):
        """True when the BadgeLink shared modules were found on this badge."""
        return self._pairview is not None

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
                return settings_copy.PAIR_VALUE_UNAVAILABLE
            return settings_copy.PUSH_WORDS[push_mode(self.push_mode())]
        if row == ROW_PAIR:
            if not self.library:
                return settings_copy.PAIR_VALUE_UNAVAILABLE
            if self.pair.get("revoked"):
                return settings_copy.PAIR_VALUE_REVOKED
            return (settings_copy.PAIR_VALUE_LINKED if self.pair.get("paired")
                    else settings_copy.PAIR_VALUE_UNLINKED)
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
            "softkey_events": ("", "", ""),
        }

    def menu_label(self, index):
        """One composed row string, for ``ui.ListView``'s ``label_for``."""
        row = self.rows[index]
        return "{}  {}".format(ROW_LABELS[row], self.row_value(row))

    def pair_view(self):
        """The pairview model for the current pair state, plus this app's bar.

        Two consumer-side decisions, both about not drawing a dead key:

        * A carries BACK on every pair screen. It returns to the menu and emits
          nothing, so a live claim survives the trip (I2's "commits nothing").
        * a REVOKED badge is offered no B. pairview returns ``{"B": "PAIR"}``
          for it, but ``pairstate._apply_event`` returns early on every event
          once ``revoked`` is set, so that key cannot do anything — and a label
          over an inert key teaches the wearer it works. The reboot line from
          the #2 addendum replaces it.
        """
        if not self.library:
            return {
                "screen": PAIR,
                "title": settings_copy.ROW_PAIR_LABEL,
                "lines": [settings_copy.NET_NOT_INSTALLED],
                "softkeys": (settings_copy.BACK, "", ""),
                "softkey_events": ("", "", ""),
                "reboot": False,
            }
        if self._base_url is None:
            model = self._pairview.view_model(self.pair)
        else:
            model = self._pairview.view_model(self.pair, self._base_url)
        keys = model.get("softkeys") or {}
        reboot = False
        if self.pair.get("revoked"):
            keys = {}
            reboot = True
        model = dict(model)
        # THE PRINTED WORD AND THE WIRED EVENT ARE NOW TWO DIFFERENT THINGS.
        # `softkeys` is what the wearer reads; `softkey_events` keeps pairview's
        # own label so `LABEL_EVENTS` still resolves it. Wiring on the printed
        # word would have made "ACCEPT -> YES" a behaviour change.
        model["softkey_events"] = ("", keys.get("B", ""), keys.get("C", ""))
        model["softkeys"] = (
            settings_copy.BACK,
            _button_word(keys.get("B", "")),
            _button_word(keys.get("C", "")),
        )
        model["title"] = settings_copy.ascii_fold(
            settings_copy.PAIR_TITLES.get(model.get("title", ""),
                                          model.get("title", "")))
        lines = [_pair_line(line) for line in (model.get("lines") or ())]
        model["reboot"] = reboot
        if reboot:
            lines.append(settings_copy.NET_LINE_REBOOT)
        model["lines"] = lines
        # The QR payload and the typeable code come from pairview untouched, and
        # both are ASCII by construction (an https base plus a validated base32
        # code). Folded anyway, so that EVERY string this model hands the view
        # is drawable by the same 95-glyph advance table the fit tests price
        # against — one rule, no exceptions to remember.
        for field in ("qr_payload", "manual_code", "match_code", "countdown"):
            if model.get(field):
                model[field] = settings_copy.ascii_fold(model[field])
        return model

    def view(self):
        """The current screen, whichever it is."""
        if self.screen == MENU:
            return self.menu_view()
        if self.screen == NETWORK:
            return network_view(
                self.transport_state(),
                paired=bool(self.library and self.pair.get("paired")),
                owner_hint=self.pair.get("owner_hint", "") if self.library else "",
                library=self.library,
                network_enabled=self.network_enabled(),
                network_controllable=self._network_control is not None,
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
            return diag_view(
                self.push_diagnostics(),
                library=self.library,
                worst_ms=self.frames.worst_ms,
                measured=self.frames.measured,
                sweep_ms=self.frames.phase_ms,
                sweep_period_ms=self.frames.period_ms,
            )
        if self.screen == SLEEP:
            return sleep_view()
        if self.screen == BRIGHT:
            return bright_view(self.brightness)
        if self.screen == SCORES:
            return scores_view(self._scores_result)
        return self.pair_view()

    # -- input ---------------------------------------------------------------

    def press(self, key):
        """One key edge. Returns the pairstate actions the app must perform.

        The list is normally empty; it is non-empty only when a driver is
        present and a pair action needs the server (an undriven action has
        already been resolved to its honest failure event before this returns).
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
            return []
        if self.screen == BRIGHT:
            # BEFORE THE GENERIC `A` BRANCH BELOW, WHICH IS THE WHOLE POINT OF
            # PUTTING IT HERE. A is a DIRECTION on this screen (see
            # `bright_view` for the rule and the deviation it declares), so
            # falling through to "A returns to the menu" would leave the wearer
            # with a ladder they can only climb.
            return self._bright_key(key)
        if key == "A":
            # Labelled, commits nothing, and never touches the pair flow. On the
            # erase question it is the KEEP the bar promises, which is the same
            # behaviour under a different word rather than a second branch.
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
        if not self.library:
            return []
        return self._pair_key(key)

    def _move(self, delta):
        if self.screen == SLEEP:
            return []
        if self.screen == MENU:
            # By one, and wrapping, per B3.
            self.index = (self.index + delta) % len(self.rows)
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

    def _pair_key(self, key):
        if key == "B":
            slot = 1
        elif key == "C":
            slot = 2
        else:
            return []
        # pairview's OWN label, not the word on the panel: `softkeys` carries
        # the wearer's copy and `LABEL_EVENTS` is keyed on the protocol.
        label = self.pair_view()["softkey_events"][slot]
        event = LABEL_EVENTS.get(label)
        if event is None:
            # No label on that key, or a label pairview added that this build
            # has no event for. Inert beats guessed.
            return []
        return self.feed([{"type": event}])

    # -- the outside world ---------------------------------------------------

    def tick(self, elapsed_ms):
        """Advance the note and the pair countdown. Returns actions.

        THE SLEEP NOTE IS COUNTED FIRST AND SHORT-CIRCUITS, because a badge one
        frame from dormancy has no reason to advance a pair claim it will never
        finish -- and because `_advance` returns pairstate actions the seam would
        then try to perform on a session that is about to end.

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
        if not self.library:
            return []
        return self._advance(elapsed_ms, ())

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

    def feed(self, events):
        """Apply observed pair events (``pair_started``, ``claim_received``,
        ``ack_succeeded``, ``revoked``, ``remote_unpaired``, ...)."""
        if not self.library:
            return []
        return self._advance(0, events)

    def _advance(self, elapsed_ms, events):
        self.pair, actions = self._pairstate.advance(self.pair, elapsed_ms, events)
        return self._perform(actions)

    def _perform(self, actions):
        if self._driver is not None:
            return list(actions)
        pending = []
        for action in actions:
            fallback = _UNDRIVEN_FAILURES.get(action.get("type"))
            if fallback is not None:
                pending.append(fallback)
        # Resolved here rather than returned, so the app never has to know that
        # "no driver" is a case: it gets a settled screen either way.
        for event in pending:
            self.pair, _ = self._pairstate.advance(self.pair, 0, [event])
        return []
