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
here it always returns to the Settings menu WITHOUT emitting a pairstate event,
so a pair flow already in the air keeps running and the wearer can leave a live
QR to read the network row and come back to it. The flow's own cancel/decline
labels stay where pairview put them, on B and C.
"""


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

# Row identifiers. The tile is general-purpose on purpose: the owner's reasoning
# for one Settings tile over a tile per need was that other settings-shaped needs
# are already planned (battery visibility among them), so adding one is a row
# here and not a launcher negotiation.
ROW_PAIR = "pair"
ROW_NETWORK = "network"
ROW_PUSH = "push"
ROW_SLEEP = "sleep"

ROW_LABELS = {
    ROW_PAIR: settings_copy.ROW_PAIR_LABEL,
    ROW_NETWORK: settings_copy.ROW_NETWORK_LABEL,
    ROW_PUSH: settings_copy.ROW_PUSH_LABEL,
    ROW_SLEEP: settings_copy.ROW_SLEEP_LABEL,
}
ROW_SCREENS = {
    ROW_PAIR: PAIR,
    ROW_NETWORK: NETWORK,
    ROW_PUSH: PUSH,
    ROW_SLEEP: SLEEP,
}
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
ROWS = (ROW_PAIR, ROW_NETWORK, ROW_SLEEP)
#: The Updates row is CONDITIONAL: it appears only when the boot pump actually
#: has a doorbell to control. A row that describes a transport this badge does
#: not carry is a row that lies, and the tile already refuses to invent state.
ROWS_WITH_PUSH = (ROW_PAIR, ROW_NETWORK, ROW_PUSH, ROW_SLEEP)

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


def push_view(mode, library=True, controllable=False, enabled=None):
    """The Updates screen: what is happening, and the one question to answer.

    ``mode`` is READ BACK from the transport every time this is built — the
    owner's Card PW rule, and the reason there is no "pending" state here. The
    wearer's own preference (``enabled``) is a separate fact and is not allowed
    to describe the connection: a badge whose holder said YES but whose venue
    blocked push reads "The event turned this off for now", not "Instant".
    """
    normalised = push_mode(mode)
    lines = []
    if not library:
        lines.append(settings_copy.NET_NOT_INSTALLED)
    elif normalised == PUSH_UNKNOWN:
        lines.append(settings_copy.PUSH_LINE_STATE.format(mode))
    else:
        lines.append(_PUSH_LINES[normalised])
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
        "reboot": False,
        "lines": lines,
        "softkeys": (settings_copy.BACK, middle, right),
        "softkey_events": events,
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
                 push_control=None):
        if (pairview is None) != (pairstate is None):
            raise ValueError("pairview and pairstate must be supplied together")
        self._pairview = pairview
        self._pairstate = pairstate
        self._driver = driver
        self._base_url = base_url
        self._transport = transport
        self._network_control = network_control
        self._push_control = push_control
        self.screen = MENU
        self.index = 0
        self.rows = ROWS_WITH_PUSH if push_control is not None else ROWS
        #: Milliseconds left on the sleep note, or None when it is not up.
        #: `tick` counts it down and emits the one action that ends the session.
        self._sleep_ms = None
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
            )
        if self.screen == SLEEP:
            return sleep_view()
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
            return []
        if key == "A":
            # Labelled, commits nothing, and never touches the pair flow.
            self.screen = MENU
            return []
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
        return []

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
        """
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
