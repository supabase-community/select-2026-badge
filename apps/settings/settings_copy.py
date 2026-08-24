"""Every word this tile shows a wearer, in one file, in the wearer's language.

WHY A SEPARATE MODULE. The owner's ruling of 2026-08-21, after seeing the
Confirm screen on the physical badge: **the labels were protocol words, not
human words.** "Confirm code" with ACCEPT / DECLINE under it answers a question
the screen never clearly asks. So the tile now follows one pattern wherever the
wearer makes a choice — the screen asks ONE plain question and the buttons
ANSWER it (B = ``YES``, C = ``NO``) — and every title says what the wearer is
doing rather than which protocol step they are on.

Copy is the owner's voice, so it is collected here rather than scattered through
two modules: one file to read, one file to override, and
``settings/README.md``'s before/after table is generated from the same decisions.
The fit tests price every string in this file against the band it is drawn in
(``settings/tests/test_settings_fit.py``), so replacing any of them is safe: a
too-long replacement fails the fast lane instead of reaching a badge.

WHAT THIS MODULE IS NOT. It is not a fork of ``badgelink.pairview``. Card E's
view-models are canvas-agnostic and shared, and this tile CONSUMES them: the
maps below are a CONSUMER-SIDE presentation layer keyed on the exact strings
pairview publishes, applied in ``settings_model.pair_view``. pairview keeps its
own words for its own tests and for any other consumer, the pairstate event
names and screen ids are untouched, and
``settings/tests/test_settings_seam.py`` fails if pairview ever publishes a
title, line or softkey label this file has no answer for. That is the whole
guard: a silent pass-through of protocol copy is the failure worth catching.

THE ASCII FOLD IS NOT COSMETIC — IT IS THE ONE THING THAT MAKES THE COPY
VISIBLE AT ALL. ``MonaSans-Medium`` draws NO ellipsis, en dash, em dash, curly
quote, bullet or arrow: every one of them measures ZERO WIDTH
(``docs/engineering-findings.md`` § "Fonts and softkey geometry"). pairview
ships ``Starting…`` and ``Finishing pairing…`` with a real U+2026, so at HIRES
those screens would silently lose their punctuation, and ``image.ELLIPSES`` as
an overflow marker would draw nothing at all. Everything the model emits is
therefore folded to printable ASCII first, and anything left unrenderable
becomes a visible ``?`` — loud degrade for the unrenderable, silent correctness
for the merely typographic, which is the rule Schedule's ``sanitize_title``
already set.
"""


#: The vector face this app's chrome resolves through ``ui.CHROME_FACE``. Named
#: here only so the fit tests and the generator agree with the app about which
#: face the numbers describe.
VECTOR_FACE = "MonaSans-Medium"

#: The ROM face to fall back to when the ``.af`` outlines are missing from
#: ``/system``. NOT ``shared/ui.py``'s HIRES default: ``bacteria`` is picked for
#: sizing DISPLAY type and loses this app's layout before it gains any height —
#: DECLINE measures 90 px in it against a 68 px softkey box, and one line of
#: body copy 357 px against 308 px of content width. ``smart`` is the shortest
#: ROM face still taller than ``sins`` and is what Schedule chose for the same
#: job ("pick the HIRES bitmap fallback by the job, not from one recipe... never
#: fall back BOLDER").
BITMAP_FALLBACK = "smart"


# -- the ASCII fold ---------------------------------------------------------

#: Web punctuation that the shipping faces measure at ZERO width, and the ASCII
#: it becomes. Ordered pairs rather than a dict so the multi-character
#: replacements are deterministic on every MicroPython build.
PUNCTUATION_FOLD = (
    ("…", "..."),   # HORIZONTAL ELLIPSIS - pairview ships two of these
    ("—", "-"),     # EM DASH
    ("–", "-"),     # EN DASH
    ("‘", "'"),     # LEFT SINGLE QUOTATION MARK
    ("’", "'"),     # RIGHT SINGLE QUOTATION MARK
    ("“", '"'),     # LEFT DOUBLE QUOTATION MARK
    ("”", '"'),     # RIGHT DOUBLE QUOTATION MARK
    ("•", "-"),     # BULLET - its ink is a 2x2 dot, below the arcmin floor
    ("→", "->"),    # RIGHTWARDS ARROW
    # ESCAPED, NOT TYPED. Both of these are invisible characters, and an
    # invisible entry in a source table is a line a maintainer cannot see.
    ("\u00a0", " "),
    ("\u00ad", ""),
)

#: What an unrenderable code point becomes. Visible on purpose: a dropped glyph
#: is a defect nobody can see, and this tile draws server-supplied text (the
#: owner hint) that no lane can enumerate.
REPLACEMENT = "?"


def ascii_fold(text):
    """``text`` reduced to printable ASCII, folding what folds cleanly.

    Total by construction, which is what lets the fast lane price ANY string
    from a 95-entry advance table: after this, every character is in
    ``chr(32)..chr(126)``.
    """
    if not isinstance(text, str):
        text = str(text)
    for source, target in PUNCTUATION_FOLD:
        if source in text:
            text = text.replace(source, target)
    out = None
    for index in range(len(text)):
        character = text[index]
        code = ord(character)
        if 32 <= code <= 126:
            if out is not None:
                out.append(character)
            continue
        if out is None:
            out = []
            for earlier in range(index):
                out.append(text[earlier])
        # A newline or a tab in a one-line band is a layout accident, not a
        # character the wearer typed; everything else is genuinely unrenderable.
        out.append(" " if code < 32 else REPLACEMENT)
    return text if out is None else "".join(out)


# -- the pair flow, in the wearer's words ------------------------------------
#
# Keyed on exactly what `badgelink.pairview` publishes. The seam test walks
# every reachable pairstate phase and fails if a published title, line or
# softkey label is missing from these tables, so protocol copy cannot reach a
# panel by default.

#: pairview title -> what the wearer is DOING on that screen.
PAIR_TITLES = {
    "Pair this badge": "Link your phone",
    "Starting…": "Getting a code",
    "Scan to pair": "Scan with your phone",
    # The owner's own example of the defect: a title naming the protocol step
    # over a question the screen never asked.
    "Confirm code": "Check your phone",
    "Almost there": "Almost there",
    "Paired": "Badge linked",
    "Unpaired": "Link removed",
}

#: pairview body line -> the same fact in plain words. Unchanged entries are
#: listed rather than omitted, so the seam test's "every published line has an
#: answer" check stays total and a deliberate keep is visible as a decision.
PAIR_LINES = {
    "Press B to show a QR code.": "Press B to show a QR code.",
    "Contacting the server.": "Contacting the server.",
    # VERBATIM, and named as such by the owner: this is the question the
    # Confirm screen exists to ask, and at HIRES it finally fits on one line.
    "Does your phone show this code?": "Does your phone show this code?",
    "Finishing pairing…": "Finishing up.",
    "This badge is linked.": "This badge is linked.",
    "This badge was revoked.": "This badge was unlinked.",
    "The code expired. Try again.": "The code expired. Try again.",
    "Confirmation timed out. Try again.": "Timed out. Try again.",
    "Pairing cancelled.": "Cancelled.",
    # Reads back the button the wearer actually pressed, now that C says NO.
    "Pairing declined.": "You chose No.",
    "Could not reach the server.": "Could not reach the server.",
    "Could not finish pairing.": "Could not finish linking.",
    "Unlinked from your account.": "Unlinked from your account.",
    "Something went wrong. Try again.": "Something went wrong. Try again.",
}

#: pairview lines this tile deliberately passes through because they are
#: composed at runtime rather than written down. Matched by PREFIX, and the
#: seam test requires a published line to be in ``PAIR_LINES`` or to start with
#: one of these — an unmatched line is a copy decision nobody made.
PAIR_LINE_PASSTHROUGH = (
    # "Linked to sam." / "Linked to your account." - already the wearer's
    # words, and the tail is the server's own hint, which no table can hold.
    "Linked to ",
)

#: pairview softkey label -> the word printed over the physical button.
#:
#: The Q&A pattern: the Confirm screen asks one question and B/C answer it, so
#: ACCEPT/DECLINE become YES/NO. That is the owner's instruction and it also
#: retires the defect that produced it — DECLINE is the widest label this app
#: can draw (65.1 px of a 68 px box, 95.7% full), and NO is 23.5 px.
#: ``LABEL_EVENTS`` still keys on the pairview label, so the wiring is
#: untouched and this table is presentation only.
BUTTON_WORDS = {
    # The idle screen's line is "Press B to show a QR code."; the button says
    # the same verb rather than naming the protocol.
    "PAIR": "SHOW",
    "CANCEL": "CANCEL",
    "ACCEPT": "YES",
    "DECLINE": "NO",
    "RETRY": "RETRY",
}

#: This app's own labels. A is the labelled way back on every screen but the
#: root, where HOME is the accepted route to the launcher and
#: ``docs/badge-button-rules.md`` §10 forbids printing a label for it.
BACK = "BACK"
OPEN = "OPEN"

#: The Network screen's B action, and the SECOND copy defect the owner read off
#: the panel: it used to say ``TURN ON`` / ``TURN OFF``, which measure 69.06 px
#: and 75.84 px against a 68 px key box, so the badge drew ``TURN...``. The
#: pinned metrics had priced both strings all along — the walked fit corpus
#: never asked for them, because it built the Network view without a controller
#: (``settings/tests/test_settings_fit.py`` now walks every controller variant).
#: ``START`` / ``STOP`` are the words Card PW's own release brief uses for this
#: control ("the Settings Network screen gains Start/Stop actions"), they are
#: imperative verbs like every other label in this bar (BACK, OPEN, SHOW,
#: CANCEL, RETRY) rather than a switch position that could be read as a state
#: report, and they fit with room to spare: 49.27 px and 40.64 px of the 68 px
#: box, against ``CANCEL``'s 62.69 px, which stays this app's widest label.
START = "START"
STOP = "STOP"


# -- the menu ----------------------------------------------------------------

#: Row labels. "Phone" rather than "Pair": pairing is what the protocol does,
#: linking your phone is what the wearer does, and every screen behind this row
#: now says "link" and "phone". OWNER-DECISIONS #2 names the FEATURE "Pair";
#: this is the label over it and the README's copy table is where to override
#: it.
ROW_PAIR_LABEL = "Phone"
ROW_NETWORK_LABEL = "Network"
#: "Updates" rather than "Push": push is what the protocol does, and what the
#: wearer cares about is how fast a change from their phone shows up. The row
#: only exists on a badge whose boot pump actually has a doorbell to control.
ROW_PUSH_LABEL = "Updates"
#: The only route to OFF (owner design, 2026-08-23; see
#: `docs/design/idle-and-off.md`). "Sleep" and not "Off" or "Power off",
#: because that is what the badge does -- `badge.sleep()` is dormancy that any
#: face button ends -- and a label that promised "off" would promise a state
#: this hardware has no switch for.
ROW_SLEEP_LABEL = "Sleep"

#: Right-hand row values for the phone row: the live state, at a glance.
PAIR_VALUE_UNAVAILABLE = "Unavailable"
PAIR_VALUE_REVOKED = "Link removed"
PAIR_VALUE_LINKED = "Linked"
PAIR_VALUE_UNLINKED = "Not linked"


# -- the sleep note ----------------------------------------------------------
#
# ONE SECOND OF COPY BEFORE THE PANEL GOES DARK, and every word of it is
# load-bearing because there is nothing on screen afterwards to correct it.
#
# THE FIRST LINE COULD NOT SAY "any button". Measured on device 2026-08-21
# (`benchmark/results/reports/2026-08-21-device-session.md` §6): `badge.sleep()`
# with no argument arms A/B/C/UP/DOWN as wake sources and **HOME IS NOT A WAKE
# SOURCE AT ALL** -- the RESET recovery read 241. So "any button wakes it" is
# false for exactly the button a wearer reaches for when a badge looks stuck,
# and the note names the exception rather than the five.
#
# THE SECOND LINE IS NOT DECORATION EITHER. `docs/design/constraints.md:115`:
# waking from `badge.sleep()` is a FULL REBOOT of `main.py`; nothing survives
# in RAM. So the wearer does not come back to this screen, they come back to the
# launcher, and a note that did not say so would make a working wake look like a
# crash. (No intro plays: `supervisor/badge/supervisor/wake.py` classifies wakes
# 0-4 as button wakes and `INTRO_REASONS` is RESET and UNKNOWN only.)
SLEEP_TITLE = "Sleeping"
SLEEP_LINE_WAKE = "Any button but HOME wakes it"
SLEEP_LINE_RESTART = "The badge restarts when it wakes"


# -- the network screen ------------------------------------------------------
#
# Six transport states, six sets of words. The MAPPING is unchanged (it is
# `polltransport`'s own six literals and the seam test pins it); only the words
# are new. Nothing here claims a connection state the transport does not
# report: "Offline" is said when the transport says it cannot reach the server,
# "Turned off" only for a local stop, and a state literal this build has never
# heard of is still PRINTED rather than smoothed over.

#: Short row values, one or two words, for the glance.
STATUS_WORDS = {
    "connected": "Online",
    "connecting": "Connecting",
    "unreachable": "Offline",
    "stopped": "Access ended",
    "off": "Turned off",
    # Covers both "no session in this boot" and "a literal this build has never
    # heard of". Neither is a connection claim.
    "unknown": "Not ready",
}

#: The full lines on the network screen itself, where there is room to explain.
NET_NOT_INSTALLED = "BadgeLink is not installed"
NET_LINE_CONNECTED = "Connected to the server"
NET_LINE_CONNECTING = "Connecting to the server"
NET_LINE_UNREACHABLE = "Can't reach the server"
NET_LINE_STOPPED = "Access ended"
NET_LINE_STOPPED_WHY = "It was revoked or it expired"
NET_LINE_OFF = "The network is turned off"
#: No transport object at all: there is no session in this boot. True, and not
#: a claim about the radio or the server.
NET_LINE_NO_SESSION = "Not connected"
#: A literal this build does not know. Deliberately raw: "no invented states"
#: cuts both ways, and a wearer reading this is reading it to a maintainer.
NET_LINE_STATE = "State: {}"

NET_LINE_LINKED = "Linked to {}"
NET_LINE_LINKED_ANON = "your account"
NET_LINE_UNLINKED = "No account linked"

#: The one line that is an ACTION rather than a description, and the only
#: status that earns it: ``polltransport`` refuses ``request_reconnect`` once
#: revoked, so a RETRY softkey there would be a label over a key that cannot
#: act (OWNER-DECISIONS #14). Was "Reboot to retry", which is three words of
#: telegraph for a sentence the wearer has to act on.
NET_LINE_REBOOT = "Restart the badge to try again"


# -- the updates screen (P6-L3, 2026-08-21) ----------------------------------
#
# The wearer-facing name for the Realtime doorbell. "Push" is the protocol word
# and "Realtime" is the product it runs on; what a person notices is whether a
# change made on their phone shows up now or in a few seconds, so that is what
# the screen is about. THREE MODES SHARE ONE WORD on the row ("Normal") because
# they are one thing to a person — updates arrive at the ordinary speed — and
# the screen behind the row is where the difference between "you turned it off",
# "it kept failing here" and "the event turned it off" is spelled out. That is
# the same rule the network row already follows for its six transport literals.

#: ``pushlink`` live mode -> the row's right-hand word. Keys are asserted
#: against the real module's constants by ``test_settings_seam.py``.
PUSH_WORDS = {
    "push": "Instant",
    "trying": "Connecting",
    "polling": "Normal",
    "demoted": "Normal",
    "blocked": "Normal",
    "network_off": "Turned off",
    # No controller, or a mode literal this build has never heard of. Neither is
    # a claim about the connection.
    "unknown": "Not ready",
}

PUSH_TITLE = "Instant updates"
#: The ONE question the screen asks, so B/C can answer it (the owner's Q&A
#: pattern: B = YES, C = NO, and the labels are already priced).
PUSH_QUESTION = "Use instant updates?"
PUSH_LINE_ON = "Changes arrive right away"
PUSH_LINE_TRYING = "Looking for a fast connection"
PUSH_LINE_NORMAL = "Changes arrive in a few seconds"
#: The automatic demotion, in the wearer's terms. Answering YES is the explicit
#: re-enable that clears it, which is why the question stays on the screen.
PUSH_LINE_DEMOTED = "The fast connection kept failing"
#: The venue kill-switch. "For now" is exact: the flag is the server's and can
#: be lifted without touching the badge.
PUSH_LINE_BLOCKED = "The event turned this off for now"
PUSH_LINE_OFF = "The network is turned off"
#: A mode literal this build does not know. Raw, for the same reason
#: NET_LINE_STATE is raw.
PUSH_LINE_STATE = "Updates: {}"


# -- what the view draws that no view-model supplies -------------------------

#: The no-encoder path: honest, legible and typeable, and never a fake QR — a
#: rendered placeholder a phone cannot scan is the one failure a bystander
#: reads as working.
NO_ENCODER = "This badge cannot draw a QR code."
NO_ENCODER_OPEN = "Open this link on your phone:"

#: A payload past the measured 152-character ECC-medium boundary. A real
#: product fault, so it is named rather than drawn as an empty square.
PAYLOAD_TOO_LONG = "That link is too long to show."

#: The typeable fallback beside the claim QR. An instruction, not a noun: the
#: wearer types these eight characters into the page the QR would have opened.
MANUAL_PROMPT = "Or type"


def every_string():
    """Every string this tile can draw, for the fit tests and the generator.

    Composed rather than listed: the tables above are the source, so a copy
    change cannot land without its own fit check. The worst cases are included
    on purpose — a 64-character owner hint (``pairstate.MAX_OWNER_HINT``) is
    what the server is allowed to send, not what a fixture usually sends.
    """
    out = set()
    out.update(PAIR_TITLES.values())
    out.update(PAIR_LINES.values())
    out.update(BUTTON_WORDS.values())
    out.add(BACK)
    out.add(OPEN)
    out.add(START)
    out.add(STOP)
    out.add(ROW_PAIR_LABEL)
    out.add(ROW_NETWORK_LABEL)
    out.add(ROW_PUSH_LABEL)
    out.add(ROW_SLEEP_LABEL)
    out.add(SLEEP_TITLE)
    out.add(SLEEP_LINE_WAKE)
    out.add(SLEEP_LINE_RESTART)
    out.update(STATUS_WORDS.values())
    out.update(PUSH_WORDS.values())
    out.update((
        PAIR_VALUE_UNAVAILABLE, PAIR_VALUE_REVOKED, PAIR_VALUE_LINKED,
        PAIR_VALUE_UNLINKED, NET_NOT_INSTALLED, NET_LINE_CONNECTED,
        NET_LINE_CONNECTING, NET_LINE_UNREACHABLE, NET_LINE_STOPPED,
        NET_LINE_STOPPED_WHY, NET_LINE_OFF, NET_LINE_NO_SESSION,
        NET_LINE_UNLINKED, NET_LINE_REBOOT, NO_ENCODER, NO_ENCODER_OPEN,
        PAYLOAD_TOO_LONG, MANUAL_PROMPT,
        PUSH_TITLE, PUSH_QUESTION, PUSH_LINE_ON, PUSH_LINE_TRYING,
        PUSH_LINE_NORMAL, PUSH_LINE_DEMOTED, PUSH_LINE_BLOCKED, PUSH_LINE_OFF,
    ))
    # Composed rows, exactly as `Settings.menu_label` composes them.
    for value in (PAIR_VALUE_UNAVAILABLE, PAIR_VALUE_REVOKED,
                  PAIR_VALUE_LINKED, PAIR_VALUE_UNLINKED):
        out.add("{}  {}".format(ROW_PAIR_LABEL, value))
    for value in STATUS_WORDS.values():
        out.add("{}  {}".format(ROW_NETWORK_LABEL, value))
    for value in PUSH_WORDS.values():
        out.add("{}  {}".format(ROW_PUSH_LABEL, value))
    # The two runtime-composed families, at a normal value and at the worst
    # value the shared modules permit.
    for hint in ("sam", NET_LINE_LINKED_ANON, "W" * 64,
                 "a.very.long.address@an.extremely.long.example.domain.test"):
        out.add(NET_LINE_LINKED.format(hint))
        out.add("Linked to {}.".format(hint))
    for literal in ("disconnected", "backoff", "connecting", "connected",
                    "stopped", "revoked", "None"):
        out.add(NET_LINE_STATE.format(literal))
    for literal in ("push", "trying", "polling", "demoted", "blocked",
                    "network_off", "unavailable", "None"):
        out.add(PUSH_LINE_STATE.format(literal))
    # The claim URL, its typeable fragment and the countdown extremes.
    out.add("https://badge-badgelink.pages.dev/p#ABCD2345")
    out.add("ABCD2345")
    out.add("0:00")
    out.add("9:59")
    return out


#: Six-character match codes for the display-face ruler. ``pairstate``'s match
#: alphabet is ``A-Z0-9``, so the widest possible code is the widest glyph six
#: times; the fixture code is here too because three lanes print it.
MATCH_CODE_PROBES = ("K7QW2M", "WWWWWW", "MMMMMM", "000000", "IIIIII")
