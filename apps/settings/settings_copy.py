"""Every word this tile shows a wearer, in one file, in the wearer's language.

WHY A SEPARATE MODULE. The owner's ruling of 2026-08-21, after seeing the
Confirm screen on the physical badge: **the labels were protocol words, not
human words.** So the tile follows one pattern wherever the wearer makes a
choice — the screen asks ONE plain question and the buttons ANSWER it — and
every title says what the wearer is doing rather than which protocol step they
are on.

Copy is the owner's voice, so it is collected here rather than scattered through
two modules: one file to read, one file to override, and
``settings/README.md``'s before/after table is generated from the same decisions.
The fit tests price every string in this file against the band it is drawn in
(``settings/tests/test_settings_fit.py``), so replacing any of them is safe: a
too-long replacement fails the fast lane instead of reaching a badge.

**THE PAIR FLOW'S COPY IS GONE (owner instruction, 2026-08-28: "can you
completely remove the phone linked thing, because that's going to be just
removed from the system anyway as part of the new update").** This module used
to carry a CONSUMER-SIDE presentation layer keyed on the exact strings
``badgelink.pairview`` publishes — ``PAIR_TITLES``, ``PAIR_LINES``,
``BUTTON_WORDS`` and the passthrough prefixes — because the Phone row rendered
that shared view-model. With the row deleted nothing here consumes pairview,
and the shared module keeps its own words for its own tests and any other
consumer. It is still installed under ``/system/lib``; this tile simply no
longer reads it.

THE ASCII FOLD IS NOT COSMETIC — IT IS THE ONE THING THAT MAKES THE COPY
VISIBLE AT ALL. ``MonaSans-Medium`` draws NO ellipsis, en dash, em dash, curly
quote, bullet or arrow: every one of them measures ZERO WIDTH
(``docs/engineering-findings.md`` § "Fonts and softkey geometry"), and
``image.ELLIPSES`` as an overflow marker would draw nothing at all. **The fold
survives the pair removal even though pairview's two U+2026 strings were its
loudest customers**, because the tile still draws text it did not author: a
runtime literal on the Network, Updates and Diagnostics screens comes from
`/system/lib` and may be any build's. Everything the model emits is therefore
folded to printable ASCII first, and anything left unrenderable becomes a
visible ``?`` — loud degrade for the unrenderable, silent correctness for the
merely typographic, which is the rule Schedule's ``sanitize_title`` already set.
"""


import backlight


#: The vector face this app's chrome resolves through ``ui.CHROME_FACE``. Named
#: here only so the fit tests and the generator agree with the app about which
#: face the numbers describe.
VECTOR_FACE = "MonaSans-Medium"

#: The ROM face to fall back to when the ``.af`` outlines are missing from
#: ``/system``. NOT ``shared/ui.py``'s HIRES default: ``bacteria`` is picked for
#: sizing DISPLAY type and loses this app's layout before it gains any height —
#: DECLINE (the widest label this app carried until the Phone row was deleted on
#: 2026-08-28, and the measurement that made this choice) measures 90 px in it
#: against a 68 px softkey box, and one line of
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


#: This app's own labels. A is the labelled way back on every screen but the
#: root, where HOME is the accepted route to the launcher and
#: ``docs/badge-button-rules.md`` §10 forbids printing a label for it.
BACK = "BACK"
OPEN = "OPEN"

#: The Q&A answers, on B and C wherever a screen asks one plain question. Owner
#: ruling, 2026-08-21, after reading `ACCEPT` / `DECLINE` off the panel: the
#: screen asks and the buttons ANSWER, rather than naming the protocol step.
#:
#: THEY LIVED IN `BUTTON_WORDS` UNTIL 2026-08-28, keyed on the pairview labels
#: they translated. That table went with the Phone row, and the Updates screen is
#: the reader left -- it asks "Use instant updates?" -- so the two words are
#: spelled here directly instead of being looked up through a protocol
#: vocabulary this tile no longer speaks.
#:
#: The owner's second reason for two short words, which `test_settings_fit`
#: pins: a three-character answer cannot crowd the panel boundary the way a
#: seven-character verb does (`DECLINE` was 65.1 px of a 68 px box; `NO` is 23.5).
YES = "YES"
NO = "NO"

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
#: box. (The comparison was against ``CANCEL``'s 62.69 px while the pair flow
#: owned that label; the Clock editor's own CANCEL is the widest one now.)
START = "START"
STOP = "STOP"


# -- the menu ----------------------------------------------------------------

#: Row labels.
#:
#: **THERE IS NO `ROW_PAIR_LABEL` ANY MORE.** "Phone" was the first row of this
#: menu from the tile's first day until 2026-08-28, when the owner deleted the
#: feature outright: *"can you completely remove the phone linked thing, because
#: that's going to be just removed from the system anyway as part of the new
#: update."* Network is the head of the menu now.
ROW_NETWORK_LABEL = "Network"
#: "Updates" rather than "Push": push is what the protocol does, and what the
#: wearer cares about is how fast a change from their phone shows up. The row
#: only exists on a badge whose boot pump actually has a doorbell to control.
ROW_PUSH_LABEL = "Updates"
#: The panel's own row (owner ruling, 2026-08-24: *"Take brightness out of
#: setup. That should only exist in settings."*). "Brightness" and not
#: "Screen" or "Backlight": it is the word the wearer would use, the word the
#: ladder's own names describe, and the word `setup`'s row carried for the
#: day it lived there -- a wearer who learned it there meets it again.
ROW_BRIGHT_LABEL = "Brightness"
#: The only route to OFF (owner design, 2026-08-23; see
#: `docs/design/idle-and-off.md`). "Sleep" and not "Off" or "Power off",
#: because that is what the badge does -- `badge.sleep()` is dormancy that any
#: face button ends -- and a label that promised "off" would promise a state
#: this hardware has no switch for.
ROW_SLEEP_LABEL = "Sleep"

#: The right-hand row word for a row whose answer needs `/system/lib` on a badge
#: that has none -- which is the badge that SHIPS with networking uninstalled.
#:
#: RENAMED FROM `PAIR_VALUE_UNAVAILABLE` ON 2026-08-28. It was named for the
#: Phone row, which is deleted; the Updates row is the one reader left, and a
#: constant still carrying the name of a removed feature is the kind of thing a
#: later reader mis-files. Its three siblings -- `Link removed`, `Linked` and
#: `Not linked` -- went with the row, because nothing else in this tile has a
#: link to report.
VALUE_UNAVAILABLE = "Unavailable"


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


# -- erasing the scores ------------------------------------------------------
#
# THE ONLY DESTRUCTIVE ACTION IN THIS TILE, so it is the only place here that
# follows B7's confirmation shape: KEEP on A, B EMPTY AND INERT, the verb on C.
# The precedent is `setup`'s RESET BADGE, and this copy owes it two rules.
#
# THE MODAL NAMES WHAT IT TAKES *AND* WHAT IT KEEPS. `setup`'s confirmation
# ends on "SCORES AND WIFI ARE KEPT" because a wearer standing at a conference
# deciding whether to press C is exactly the person who needs to know what
# survives. This screen is the other side of that sentence -- the one press on
# this badge that DOES take the scores -- so it has to be equally exact about the
# boundary, and `setup`'s promise stays true: resetting a card still keeps
# the scores, and this row still keeps the card.
#
# AND IT MUST NOT OVERCLAIM. Erasing is local and nothing more. A score already
# sent to the leaderboard is a row in a database this badge cannot reach; the
# owner can delete those in SQL, the badge cannot, and copy that implied
# otherwise would be a promise the wearer could disprove by looking at the board.
# `SCORES_LINE_SENT` is that limit, in the wearer's words.
#
# "EVERY GAME" RATHER THAN "ALL FIVE", and the number is the trap: the production
# roster ships a SUBSET of the five games, so a badge in a wearer's hand may have
# three of them and a count would be visibly wrong. `scorebox.GAME_STATE_PATHS`
# names five paths on purpose (a dev badge has all of them, and erasing a file
# that is not there costs nothing), but the copy must not.
ROW_SCORES_LABEL = "Scores"
SCORES_TITLE = "Erase scores"
SCORES_LINE_CLEARS = "Erases every game's high score"
SCORES_LINE_SPOOL = "and any score not sent yet"
SCORES_LINE_SENT = "Scores already sent stay sent"
SCORES_LINE_KEEPS = "Your badge and wifi are kept"
#: A on the question, and the word is `setup`'s: a wearer who met this
#: decision there meets the same answer here.
KEEP = "KEEP"
#: C on the question. "ERASE" and not "WIPE": it is the verb the title uses, and
#: a bar whose word differs from the question's is a bar the wearer has to
#: translate.
ERASE = "ERASE"
#: THE RESULT SCREEN, because a destructive press with no feedback is a press the
#: wearer has to guess about -- and the failure case is the one that matters. A
#: rewrite can fail on a full volume, and a wearer who walked away believing
#: their scores were gone would be wrong in the one direction that cannot be
#: corrected later.
SCORES_DONE_TITLE = "Scores erased"
SCORES_DONE_LINE = "Every game starts from nothing"
SCORES_FAILED_TITLE = "Not all erased"
SCORES_FAILED_LINE = "The badge could not write. Try again"


# -- the brightness ladder ---------------------------------------------------
#
# THE RUNG NAMES ARE `shared/backlight.py`'s AND THIS FILE DOES NOT RESTATE
# THEM. DIM / LOW / MID / FULL are a product judgement that was made once, in
# `identity`, and lifted into the shared ladder when that app was archived
# precisely so nobody makes it twice. A sentence-case second vocabulary here
# ("Dim", "Medium", "Brightest") would be two names for one rung, which is the
# drift the shared module exists to prevent -- and the wearer would meet both,
# because the ladder's names are what the SOFTKEYS have to say: this bar is
# uppercase everywhere (BACK, OPEN, SHOW, YES, NO, START, STOP) and a key that
# names the value it will produce has to name it in the bar's own case.
#
# THE SCREEN STATES THE CURRENT LEVEL IN WORDS, because the bar cannot. Each key
# names the value ONE press away and nothing beyond it, so a wearer at HIGH sees
# `MID` and `FULL` and has no way to read where they are -- and at either end of
# the ladder one of those keys is blank, which makes the guess worse rather than
# better.
BRIGHT_TITLE = "Brightness"
BRIGHT_LINE = "The screen is set to {}"


def bright_line(percent):
    """The one body line, for a level that may be BETWEEN two rungs.

    `backlight.name` walks the ladder rather than indexing it, so a hand-edited
    55 reads as the rung it is nearest rather than raising -- which is the same
    total-read discipline every other reader of this file applies.
    """
    return BRIGHT_LINE.format(backlight.name(percent))


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

#: The one line that is an ACTION rather than a description, and the only
#: status that earns it: ``polltransport`` refuses ``request_reconnect`` once
#: revoked, so a RETRY softkey there would be a label over a key that cannot
#: act (OWNER-DECISIONS #14). Was "Reboot to retry", which is three words of
#: telegraph for a sentence the wearer has to act on.
NET_LINE_REBOOT = "Restart the badge to try again"

#: THE TWO SPLIT LINES, AND THEY CLOSE THE OLDEST DEFECT ON THIS SCREEN.
#: `NetworkService.state` answers CONNECTING whenever its backend is None -- a
#: cold badge, a boot before the first radio start, a `CredentialError` out of
#: the factory -- so a badge that has NEVER TOUCHED ITS RADIO printed
#: "Connecting to the server", which is a claim about a TCP session that cannot
#: exist yet. `wifi_diagnostics()["online"]` is what separates them, and it is
#: `ResilientWiFi`'s own `_was_online` rather than a second opinion.
#:
#: NEITHER SENTENCE ASSERTS ANYTHING BEYOND THAT BIT. "Not on Wi-Fi yet" says
#: the radio has not reported an assigned address; it does NOT say the password
#: is wrong, the AP is absent or the radio is broken, because the badge cannot
#: tell those apart and page 2 is where the raw evidence is.
NET_LINE_JOINING = "Joining Wi-Fi"
NET_LINE_NO_WIFI = "Not on Wi-Fi yet"


# -- the network screen's four pages (2026-08-29) -----------------------------
#
# **WHY THIS BLOCK EXISTS, AND IT IS NOT HYPOTHETICAL.** On 2026-08-27 the
# owner's badge would not join Wi-Fi. It was on a USB cable, with root access,
# full source and a maintainer reading its serial output, and it was STILL
# impossible to tell a wrong password from an out-of-range AP from a radio
# fault. The badge printed
# `BADGELINK_NETWORK installed=1 enabled=1 state=connecting` once and then went
# silent into backoff. On 2026-10-02 ~200 badges go to a one-day conference:
# no cable, no serial, no re-provisioning and no maintainer, so THE BADGE'S OWN
# SCREEN IS THE ONLY DIAGNOSTIC CHANNEL THAT WILL EXIST.
#
# EVERY VALUE THESE LINES DRAW WAS ALREADY BEING COMPUTED AND HAD NO READER.
# `ResilientWiFi.snapshot()` has published {state, reason, attempts, failures,
# connected_ms} every frame all along and its only consumers were two
# edge-gated serial emitters -- so a badge that NEVER associates emitted
# nothing at all. `DeviceLink.open_phases` split every connect into dns /
# connect+TLS / headers / body with an outcome word. `BoundedResolver` knew the
# DHCP resolver's address and its query counts. `NetworkService.last_error`
# held the exact `CredentialError` sentence. None of it could reach a pixel.
#
# THE SCREEN IS FOUR PAGES BECAUSE THE OWNER RULED IT COULD BE (2026-08-28):
# *"Scrolling is absolutely fine. The more information, the better."* Before
# that ruling this was a one-screen, eight-band budget and the information had
# nowhere to go.
#
# ⚠ **THE ONE RULE THAT GOVERNS ALL OF IT: DO NOT TRANSLATE A RAW STATUS CODE
# INTO A VERDICT.** `benchmark/results/reports/2026-08-13-v3.0.1-network-authenticated.md`
# recorded a spurious CYW43 `-3` on CORRECT credentials and ruled that a
# negative status is "a retry signal and diagnostic fact, not a safe basis for
# a permanent user-facing" claim. So `status_-3` draws as `Wi-Fi said status_-3`
# and the badge NEVER prints "wrong password".

#: A PAGED SCREEN'S TITLE. The ordinal is in the TITLE and not in a body band
#: because the title band already exists and costs nothing, and because a
#: PHOTOGRAPH of a badge in a hall has to say which page it is -- that photo is
#: the only bug report this event will produce. Composed by the model:
#: `Network  1/4`, `Diagnostics  4/4`.
PAGE_TITLE = "{}  {}/{}"

#: WHERE THE CONNECTION STOPPED, in one word from a closed set this app owns.
#: The words are deliberately not the runtime's: `associating` is the wearer's
#: half of `resilient_wifi.CONNECTING`, and the RAW literal is on page 2 beside
#: it. `Stage: DNS` and `Stage: TLS` are the two that no badge could say before,
#: and the pair is the whole reason `bounded_dns` and `device_link` publish a
#: split at all.
NET_LINE_STAGE = "Stage: {}"
#: A malformed BadgeLink value in `/secrets.py`. **CHECKED BEFORE THE RADIO
#: BECAUSE THAT IS WHERE IT HAPPENS:** `credentials.load` raises inside
#: `DeviceBackend.__init__`, so the backend is never built, the radio is never
#: started and `_retry_at` is set -- which makes the service report BACKOFF,
#: which folds onto "Can't reach the server". Page 4 prints the sentence; this
#: word is the signpost to it.
NET_STAGE_CREDENTIAL = "credential"
NET_STAGE_OFF = "off"
NET_STAGE_ASSOCIATING = "associating"
NET_STAGE_WAITING = "waiting"
NET_STAGE_ON_WIFI = "on Wi-Fi"
NET_STAGE_CONNECTED = "connected"
NET_STAGE_DNS = "DNS"
#: TCP AND TLS TOGETHER, because that is how this client measures it: the
#: handshake is not splittable at the `connect_ms` seam (VAL-031-BLT), and
#: inventing a third number the badge does not have would be worse than one
#: honest word.
NET_STAGE_TLS = "TLS"
#: THE CLOSED SET, for `every_string()`. `DIAG_MISSING` is priced separately
#: rather than listed here, because it is defined further down this file and a
#: forward reference in a module-level tuple is an import error on the badge.
NET_STAGE_WORDS = (
    NET_STAGE_CREDENTIAL, NET_STAGE_OFF, NET_STAGE_ASSOCIATING,
    NET_STAGE_WAITING, NET_STAGE_ON_WIFI, NET_STAGE_CONNECTED,
    NET_STAGE_DNS, NET_STAGE_TLS,
)

#: `ResilientWiFi.reason` -> a plain sentence. THE VOCABULARY IS CLOSED and it
#: is the module's own: `idle`, `joining`, `connected`, `forgiven` and `stopped`
#: are the healthy words, and the six failure words all arrive through `_fail`.
#: A reason this table does not know is still DRAWN, raw, by
#: `NET_LINE_WIFI_REASON` -- "no invented states" cuts both ways.
#:
#: NONE OF THESE IS A VERDICT ABOUT THE PASSWORD OR THE AP. `The radio refused
#: the join` is `connect_exception`, which is the driver call raising; it is not
#: "wrong password", and the badge has no way to know which it was.
NET_WIFI_REASON_LINES = {
    "idle": "The radio has not started",
    "joining": "Looking for the Wi-Fi",
    "connected": "On Wi-Fi",
    "forgiven": "On Wi-Fi and steady",
    "stopped": "The radio was switched off",
    "timeout": "No answer from the Wi-Fi",
    "connection_lost": "The Wi-Fi dropped",
    "radio_activate_error": "The radio would not switch on",
    "connect_exception": "The radio refused the join",
    "isconnected_exception": "The radio stopped answering",
}
#: A `status_<n>` reason. ⚠ **THE RAW WORD, NEVER A VERDICT** -- see the block
#: above and the 2026-08-13 report it cites. `status_-3` is nine characters and
#: survives `DIAG_TEXT_CHARS` whole, and so does any two-digit code.
NET_LINE_WIFI_STATUS = "Wi-Fi said {}"
#: A reason word from a `/system/lib` newer than this app. Raw, for
#: `NET_LINE_STATE`'s reason.
NET_LINE_WIFI_REASON = "Wi-Fi: {}"

#: HOW HARD THE RADIO TRIED. `Tries 0  fails 0` on a badge that never started is
#: the honest reading and it immediately separates "never tried" from "tried
#: forty times" -- which is the difference between a credential fault and an AP
#: out of range, and nothing on this badge could show it before.
NET_LINE_TRIES = "Tries {}  fails {}"

#: PAGE 2, THE RADIO RAW. `Radio {}` carries `resilient_wifi`'s own literal --
#: `off` / `connecting` / `online` / `backoff` -- so a reader can correlate the
#: panel against the module's source and against a serial capture.
NET_LINE_RADIO = "Radio {}"
#: A BARE LABEL over the raw reason word. The label is its own band so the value
#: below it gets the WHOLE 308 px content width, which is what buys
#: `DIAG_CHUNK_CHARS` instead of `DIAG_TEXT_CHARS` for the one string on this
#: screen that is a closed-vocabulary identifier rather than a sentence.
NET_LABEL_WHY = "Why"
#: How long the current association has held. `0 s` the instant it lands, `?`
#: when the radio has never been up: a badge that keeps dropping at 40 s reads
#: differently from one that has been up for an hour, and the pair of them is
#: the difference between a flaky AP and a badge nobody has to touch.
NET_LINE_HELD = "Wi-Fi held {} s"
#: THE REGULATORY DOMAIN THE RADIO WAS STARTED IN. It comes out of `secrets.py`
#: and it is NOT credential material: it is the two-letter domain `start`
#: already validates and hands to `network.country()`. It is on the screen
#: because a badge provisioned `GB` and flown to San Francisco cannot see the
#: venue's channels, and nothing else on this badge can say so.
#:
#: ⚠ FLAGGED FOR THE OWNER. This is the one value here that is read out of the
#: provisioning file. Strike this line if that is not wanted; see the SSID note
#: at the end of this block for the value that was NOT put on the screen.
NET_LINE_REGION = "Region {}"

#: PAGE 3, THE PATH TO THE SERVER. `Link {}` carries the RAW `polltransport`
#: literal -- the value `settings_model.TRANSPORT_STATUS` folds, where both
#: `disconnected` and `backoff` become one "Can't reach the server" line. That
#: fold is why page 1 alone cannot separate no-Wi-Fi from no-Supabase.
NET_LINE_LINK_STATE = "Link {}"
#: The address `bounded_dns` would ask. THE WHOLE MODULE EXISTS BECAUSE
#: `getaddrinfo` blocks 13.1-14.0 s with no route, and this line is what turns
#: "the badge just sits there" into a fact a reader can act on.
NET_LINE_RESOLVER = "DNS via {}"
#: DHCP offered no option 6 and the gateway is unusable -- `resolver_address`'s
#: documented grey zone, named. NOT drawn when the resolver was never asked at
#: all; that reads `?`, because the absence of a measurement is not a finding.
NET_DNS_NONE = "No DNS server offered"
NET_LINE_DNS_COUNTS = "Lookups {}  failed {}"
NET_LINE_OPENS = "Opens {}  failed {}"
#: `open_phases["outcome"]`: `opened`, or the exception class the open ended in
#: (`LinkStalled` / `LinkError` / `LinkRevoked`). A class name is a protocol
#: word on a screen whose audience is an operator -- the same declared exception
#: the Diagnostics block makes -- and it is what a serial capture will say too.
NET_LINE_OUTCOME = "Open {}"
#: **THE LINE THAT SEPARATES "DNS IS DEAD" FROM "TLS IS DEAD" NUMERICALLY.**
#: Nothing on the badge could answer that question before, and it is the
#: question a venue's captive portal or blocked 443 actually poses.
NET_LINE_SPLIT = "dns {} ms  tls {} ms"
#: How long the last open went without hearing the peer. It is the EVIDENCE for
#: the outcome word above: a `LinkStalled` open is one whose silence reached the
#: no-progress deadline, and printing the number lets a reader check the
#: classification rather than trust it.
NET_LINE_STALL = "Silent for {} ms"

#: PAGE 4, THE TWO ERRORS, AND THEY ARE NEVER MERGED. `Last error` is
#: `NetworkService.last_error` -- the field that holds the `CredentialError`
#: sentence today and was read by NO VIEW; `Link error` is `PollLoop.last_error`.
#: They are different repairs by different people: the first is a fault in what
#: this badge was PROVISIONED with, the second a fault in what the network did,
#: and one merged "last error" line would send an operator to the wrong one.
NET_LABEL_ERROR = "Last error"
NET_LABEL_LINK_ERROR = "Link error"
#: Under either label when there is nothing to report. Said out loud rather than
#: left blank, for `DIAG_NO_PUSH`'s reason: a blank band reads as a line that
#: failed to draw, on the screen that has to be trusted when nothing else works.
NET_NO_ERROR = "No error recorded"

#: THE THREE "THIS BADGE CANNOT TELL YOU" SENTENCES, modelled word-for-word on
#: `DIAG_NO_PUSH` and `DIAG_NO_CLOCK`. They are drawn when the ACCESSOR is
#: absent -- a `/system/lib` older than this app, or a tile built with no
#: network controller at all -- and NEVER when a value merely came back empty.
#: A row of zeroes would be a measurement nobody took.
NET_NO_RADIO = "No radio details on this badge"
NET_NO_LINK = "No link details on this badge"

# -- THE SSID IS ON THIS SCREEN. THE OWNER SAID YES, 2026-08-29 --------------
#
# This block said the opposite until today, and the reversal is an OWNER RULING
# rather than a re-reading of the old one: *"the SSID name would be awesome."*
# The product question the old note deferred -- ~200 badges in a public hall,
# each with a screen anyone can wake, each showing the venue's network name --
# has been answered. **THE PASSWORD IS STILL NOWHERE NEAR THIS FILE** and
# nothing below reads `secrets.WIFI_PASSWORD`; the name is not the credential.
#
# WHAT IT BUYS, and it is the reason it was worth asking twice: it is the ONLY
# thing that separates "this badge was provisioned for the WRONG network" from
# "the right network is out of range". Both of those badges read `Stage:
# associating`, `No answer from the Wi-Fi` and `Tries 40  fails 40`, and until
# this line nothing on the badge could tell them apart -- which at a venue with
# no cable is the difference between a five-second answer and no answer at all.
#
# ⚠ **THE VALUE CANNOT REACH THIS APP YET, AND THAT IS A DIFFERENT LANE'S
# FILE.** `resilient_wifi.snapshot()` publishes {state, reason, attempts,
# failures, connected_ms} and no name, `network_runtime.WIFI_DIAGNOSTIC_KEYS`
# has no `ssid` entry, and `badgelink/tests/test_network_diagnostics.py::
# test_THE_SSID_HAS_NO_KEY_IN_THIS_RECORD` asserts BOTH of those -- it even
# feeds `ssid` into a fake backend and asserts the record drops it. So the
# runtime half is three files this lane does not own.
#
# WHAT IS WRITTEN HERE IS THE WHOLE SETTINGS HALF, AND IT IS NOT A DEAD
# CONSTANT. `settings_model._network_answer` draws the line the moment the
# radio record carries a non-empty `ssid`, and draws NOTHING when it does not --
# which is this tile's existing rule for `wifi_reason_line` and for both
# `push_cause` lines, and is why a badge whose `/system/lib` predates the key
# gets no `Network ?` band claiming a measurement nobody took. The corpus
# prices it, the model tests drive it, and the day the runtime publishes the
# key it lights up with no further edit. The runtime patch is three lines:
# `"ssid": self._ssid` in `resilient_wifi.snapshot()`, `"ssid"` in
# `WIFI_DIAGNOSTIC_KEYS`, and `record["ssid"] = _text(snapshot.get("ssid"))`
# in `NetworkService.wifi_diagnostics()` -- plus reversing that badgelink test.

#: THE NETWORK NAME THE RADIO WAS TOLD TO LOOK FOR. **NEVER THE PASSWORD**, and
#: never a claim that the AP was found: this is what `start()` was handed, so on
#: the wrong-network badge it is exactly the wrong name and that IS the finding.
#:
#: ONE BAND, ON PAGE 1, AND THE BUDGET IS WHY. Page 1's worst case is already
#: seven of `settings_view.MAX_BODY_LINES`' eight bands (a revoked transport
#: draws two status lines, a stage, a reason, the tries and the restart
#: instruction), so the bare-label-plus-two-chunks shape the errors use -- three
#: bands, 40 characters -- does not fit and neither does it on page 2, which is
#: six bands of its own. A prefixed single band is what there is room for.
NET_LINE_SSID = "Network {}"
#: ITS OWN BOUND, DERIVED, exactly as `DIAG_UID_CHARS` is and for the same kind
#: of reason: this is a value somebody COMPARES CHARACTER BY CHARACTER against a
#: name printed on a sign, so every character bought is worth buying. `Network `
#: is 62.69 px in `MonaSans-Medium` at 17 pt and `W` is 14.742 px, so 16 W lands
#: at 298.6 px of the 308 px content width and 17 W at 313.3 -- ONE CHARACTER
#: over. Sixteen is arithmetic, not taste, and `test_settings_fit` re-derives it.
#:
#: ⚠ A 32-BYTE SSID STILL LOSES ITS TAIL, and that is disclosed rather than
#: fixed. The alternative is three bands this page does not have. Sixteen
#: characters is enough to tell `SupabaseLaunchWeek` from `venue-guest`, which
#: is the discrimination the line exists for.
NET_SSID_CHARS = 16


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


# -- WHY the doorbell is not carrying: the second Updates line ---------------
#
# THE DEFECT THIS CLOSES COST THE OWNER DAYS AND A HARDWARE SESSION MOST OF A
# MORNING. "Updates  Connecting" is `pushlink` mode `trying`, and `trying` is ONE
# WORD FOR EIGHT DISTINCT STATES -- four of them permanent for the boot, and one
# in which the doorbell object was never built at all
# (`NetworkService.push_mode()` answers `PUSH_MODE_TRYING` whenever `self._push`
# is None and both preferences are on). The owner had one symptom and no cause.
# `docs/handoff/networking-endstate-2026-08-26/DOORBELL_ROOTCAUSE_FINDINGS.md`
# §6 D1 is the finding; §6 "the seam, defined precisely" is the interface, and
# this table is the half it says is ours.
#
# A WEARER CANNOT ACT ON MOST OF THE DIFFERENCE, which is why
# `network_runtime.push_cause()` is a SECOND line and not a new row word: the
# glance stays "Connecting", and the screen behind it is where the difference is
# spelled out. That is the rule the network row already follows for its six
# transport literals and the Updates row already follows for its three "Normal"
# modes.
#
# EVERY WORD BELOW IS OURS, CHOSEN FROM A CLOSED SET, AND NEVER THE SERVER'S.
# `push_cause()` reads the server's refusal string for ONE BIT (is this an
# authorization refusal?) and discards the text, because a string minted by a
# system that knows nothing about which glyphs this badge carries renders as
# tofu. The same rule governs this table: the KEYS are `network_runtime`'s eight
# literals and the VALUES are copy priced against the band by
# `test_settings_fit.py`, so there is no path by which unbaked text reaches the
# renderer.
#
# THE MAP IS TOTAL AND ASSERTED TOTAL. `test_settings_seam.py`'s
# `test_every_push_cause_the_runtime_can_name_has_wearer_copy` fails the fast
# lane if the runtime grows a ninth cause, because on this canvas an unmapped
# word is not a cosmetic gap -- the glyph set is pre-baked, so it is missing
# glyphs on a wearer's screen.
#
# ONE CAUSE IS MASKED BY THE ACT OF READING IT, and that is worth knowing before
# trusting this line as a diagnostic. `_placement_allows_establishment()` is True
# for an app that called `set_active(True)`, and `settings/__init__.py` calls
# exactly that while the Updates screen is open -- so opening the screen GRANTS
# the placement the cause would have reported. `in an app` is therefore
# effectively unreachable HERE (only an app-exit frame can produce it), and the
# state that actually hid the 2026-08-26 root cause is read off serial's
# `event=push_withheld reason=in an app`, not off this panel. The copy is still
# required, still priced and still rendered: the map may not have a hole in it.
PUSH_CAUSE_NOT_STARTED = "It has not started yet"
#: The one line a wearer can ACT on. HOME leaves the app, and leaving an app is
#: `machine.reset()` into the launcher, where placement always allows an
#: establishment (spec §4.5). Naming HOME in body copy is this app's existing
#: idiom (`SLEEP_LINE_WAKE`); what `docs/badge-button-rules.md` §10 forbids is a
#: HOME LABEL in the softkey bar, which this is not.
PUSH_CAUSE_PLACEMENT = "Press HOME to connect"
#: An attempt is in flight RIGHT NOW, which is the one state the wearer should
#: simply wait out. Said explicitly rather than left as a blank second line,
#: because "no line" has to keep meaning "there is nothing to explain".
PUSH_CAUSE_ESTABLISHING = "Connecting right now"
#: "Wi-Fi" rather than "the network": the row above already owns the word
#: network, and a conference attendee reads a missing radio faster than a
#: missing network.
PUSH_CAUSE_NO_SIGNAL = "No Wi-Fi signal"
#: An authorization refusal, and the one cause an operator has to be able to
#: read off the panel. "The server" is this app's existing word for it
#: (`NET_LINE_CONNECTED`, `NET_LINE_UNREACHABLE`); "this badge" is what makes it
#: a refusal of the holder rather than an outage.
PUSH_CAUSE_REFUSED = "The server refused this badge"
#: NOT an authorization refusal -- a rate limit or a shard fault, which layer 2
#: retries on its own backoff and which clears itself. The second clause is the
#: whole value of the line: it says do nothing.
PUSH_CAUSE_SERVER_BUSY = "The server is busy, trying again"
#: Demoted, with the slow bounded re-arm armed. "Later" and not "shortly",
#: because the re-arm is deliberately slow and a promise of soon would be one
#: the transport has not made.
PUSH_CAUSE_RETRY_LATER = "It will try again later"
#: Wanted, allowed, nothing wrong: between attempts (boot jitter, a reconnect
#: backoff, waiting for a tolerant moment). "A good moment" is the internal
#: "tolerant moment" without the jargon, and it is honestly vague because the
#: wait genuinely has several causes and none of them is actionable.
PUSH_CAUSE_WAITING = "Waiting for a good moment"

#: ``network_runtime.PUSH_CAUSES`` literal -> the second line. Keyed on bare
#: strings for the same reason ``PUSH_WORDS`` is: the model spells the literals
#: as constants and the seam test asserts them against the real module, so this
#: file stays importable on a host with no ``/system/lib``.
PUSH_CAUSE_LINES = {
    "not started": PUSH_CAUSE_NOT_STARTED,
    "in an app": PUSH_CAUSE_PLACEMENT,
    "connecting": PUSH_CAUSE_ESTABLISHING,
    "no signal": PUSH_CAUSE_NO_SIGNAL,
    "refused": PUSH_CAUSE_REFUSED,
    "server busy": PUSH_CAUSE_SERVER_BUSY,
    "retry later": PUSH_CAUSE_RETRY_LATER,
    "waiting": PUSH_CAUSE_WAITING,
}


# -- WHY it was not carrying BEFORE this screen was opened -------------------
#
# THE OBSERVER EFFECT, AND IT IS THE MECHANISM THAT HID THE 2026-08-26 ROOT
# CAUSE FOR A WHOLE SESSION. `settings/__init__.py` calls `set_active(True)`
# while this tile is open, and OWNER RULING #22 placement is exactly what that
# grants -- so opening the Updates screen GRANTS THE PLACEMENT THE SCREEN CAME
# TO REPORT. `push_cause()` therefore cannot return `in an app` to a reader on
# this panel: not because the state never happened, but because looking ended
# it. The block above notes that; this block is the fix.
#
# `network_runtime` latches the cause it replaces and exposes it as
# `previous_cause()`, so the panel can answer the question an operator actually
# has -- "why did it fail BEFORE I came to look" -- with a value that survives
# the act of asking.
#
# EVERY STRING BELOW IS PAST TENSE AND CARRIES `PUSH_WAS_MARK`, AND THAT IS AN
# ENFORCED INVARIANT RATHER THAN A HOUSE STYLE. A past fact rendered as present
# is precisely the failure the runtime's own clear-on-join branch exists to
# prevent, and re-introducing it one layer up in the UI would defeat that branch
# entirely. `network_runtime.PUSH_CAUSE_LATCH_MS`'s comment names the risk
# exactly -- "a display that has to say 'this is historical' is one edit away
# from not saying it" -- so the marker is asserted by
# `test_settings_seam.py::test_every_past_push_cause_is_marked_as_past` instead
# of trusted. An edit that drops it fails the fast lane.
#
# THE MAP IS FLAT ON PURPOSE: ONE STRING PER CAUSE, NO FRESHNESS QUALIFIER.
# There is deliberately no "a moment ago" / "hours ago" tier and no relative-time
# token, because THE RUNTIME OWNS FRESHNESS, not this copy: the latch expires
# after `network_runtime.PUSH_CAUSE_LATCH_MS` and an expired latch READS AS
# ABSENT (`previous_cause()` returns None and drops the value). So a rendered
# past line is always inside that window by construction, and a staleness
# qualifier would be copy restating a guarantee the answer already carries.
# Do not add one (coordinator ruling, 2026-08-26; `settings/README.md`
# § "The past cause line").
#
# THESE ARE NOT THE LIVE LINES WITH A PREFIX, AND THE BAND IS WHY. Prefixing
# `PUSH_CAUSE_LINES` reaches 263.50 px of the 308 px content width for
# `server busy` (85.6%), which clears the band but blows the 75% margin
# `test_settings_fit.py` requires of a cause line -- on the one screen whose
# whole audience is already confused. Rewritten short, the worst past line is
# 189.79 px (61.6%), NARROWER than the widest live line in BOTH FACES (215.55 px
# vector, 189.00 px bitmap), so the extra row costs the screen no width at all.
# THE BITMAP FACE IS NOT A FORMALITY HERE: it is 2 px tighter than the vector one
# on this table's worst string and it is what rejected the first `retry later`
# draft, which the vector face passed with 23 px to spare. Every number is pinned
# in `test_every_past_cause_line_fits_the_band_in_both_faces` and
# `test_the_past_line_never_makes_the_screen_tighter_than_it_was`.
#
# ONE IS A STATEMENT WHERE THE LIVE LINE IS AN INSTRUCTION, and that is not a
# style choice either: live `in an app` says "Press HOME to connect" because
# HOME is the fix. In the past tense that instruction is WRONG -- the wearer is
# standing in Settings, placement is already granted, and pressing HOME would
# act on a condition that has gone. So the past form reports and never directs.
#: The shared past marker, spelled once so the seam test can assert every value
#: carries it. "Earlier" and not "Before", which invites "before what?".
PUSH_WAS_MARK = "Earlier: "
#: No doorbell object existed yet. Nothing had been attempted.
PUSH_WAS_NOT_STARTED = "Earlier: it had not started"
#: THE ONE THIS WHOLE BLOCK EXISTS FOR. A statement, never "Press HOME" -- see
#: the instruction/statement note above. "Held it back" rather than "blocked",
#: because `PUSH_LINE_BLOCKED` already owns "block" on this screen for the
#: venue's kill switch and two meanings for one word here would be a real
#: ambiguity, not a pedantic one.
PUSH_WAS_PLACEMENT = "Earlier: an app held it back"
#: An establishment was in flight.
PUSH_WAS_ESTABLISHING = "Earlier: it was connecting"
#: The radio was not associated. "Wi-Fi" for the same reason the live line uses
#: it: the row above owns the word network.
PUSH_WAS_NO_SIGNAL = "Earlier: there was no Wi-Fi"
#: An authorization refusal. "It" is the join rather than the badge, which keeps
#: the line short without claiming the refusal has been lifted.
PUSH_WAS_REFUSED = "Earlier: the server refused it"
#: A rate limit or a shard fault, not an authorization refusal. The live line's
#: "trying again" clause is dropped on purpose: it is advice about NOW, and this
#: line is about then.
PUSH_WAS_SERVER_BUSY = "Earlier: the server was busy"
#: Demoted, with the slow bounded re-arm armed. The live line's own past tense,
#: word for word: "It will try again later" -> would. It is also the SHORTEST
#: string here, and that was forced rather than chosen -- the first draft, "it
#: was set to try later", measured 191.00 px in the BITMAP FALLBACK against the
#: 189.00 px widest live line there, so it would have become the widest thing on
#: this screen on a badge whose `/system` was rebuilt without the `.af` outlines.
#: The vector face said 192.71 against 215.55 and hid that completely
#: (`test_the_past_line_never_makes_the_screen_tighter_than_it_was` caught it).
PUSH_WAS_RETRY_LATER = "Earlier: it would try later"
#: Wanted, allowed, nothing wrong: between attempts. Distinct from
#: `PUSH_WAS_ESTABLISHING`, which is an attempt actually in flight.
PUSH_WAS_WAITING = "Earlier: it was between tries"

#: ``network_runtime.PUSH_CAUSES`` literal -> the PAST line, keyed exactly as
#: ``PUSH_CAUSE_LINES`` is and asserted set-equal to it and to the runtime's own
#: tuple in both directions. A ninth cause fails the fast lane here as well as
#: there, because the past line is drawn from the same pre-baked glyph set.
PUSH_WAS_LINES = {
    "not started": PUSH_WAS_NOT_STARTED,
    "in an app": PUSH_WAS_PLACEMENT,
    "connecting": PUSH_WAS_ESTABLISHING,
    "no signal": PUSH_WAS_NO_SIGNAL,
    "refused": PUSH_WAS_REFUSED,
    "server busy": PUSH_WAS_SERVER_BUSY,
    "retry later": PUSH_WAS_RETRY_LATER,
    "waiting": PUSH_WAS_WAITING,
}


# -- the diagnostics screen --------------------------------------------------
#
# THE ONE SCREEN IN THIS TILE WHOSE AUDIENCE IS NOT THE WEARER, and that is a
# declared exception to this file's founding rule rather than a lapse from it.
# Everywhere else the owner's 2026-08-21 ruling holds: protocol words are not
# human words. Here the reader is whoever is holding the badge trying to explain
# it -- at a bench, or at the event with 800 of them -- and the values they need
# are the runtime's OWN, the ones `network_runtime` prints on serial and
# `PushLink.snapshot()` publishes. Translating `policy_source = default` into a
# friendly sentence would break the correlation that is the entire point, and
# the wearer already has the Updates screen, which says the same facts in their
# language. The one place this screen DOES translate is `policy_source` itself,
# and the reason is below: the raw word is actively misleading.
#
# WHAT IT COST TO NOT HAVE THIS, three times on 2026-08-27, an hour each:
#
# 1. The Updates screen read `PUSH_LINE_BLOCKED` -- "The event turned this off
#    for now" -- and nobody could tell a venue that had really said no from a
#    badge that had not been told yet. The steering read is deliberately phased
#    60-240 s after boot so 800 badges do not stampede, and every app exit is
#    `machine.reset()`, so "not told yet" is the NORMAL state for the first
#    minutes after every app switch. `DIAG_POLICY_LINES` is the fix and it is
#    THE MOST VALUABLE LINE ON THIS SCREEN.
# 2. The Updates screen read `PUSH_LINE_DEMOTED` -- "The fast connection kept
#    failing" -- with `DEMOTE_AFTER_SESSIONS` at 3 and no way to see how far
#    along that count the badge was. `DIAG_LINE_SESSIONS` draws 2/3 against 3/3,
#    which the runtime's own comment names as the whole difference.
# 3. Command latency measured bimodal: 0.40/0.44/0.55 s against 1.34-2.38 s over
#    12 `set_caselights` inserts -- a doorbell ring against the 3 s
#    `ACTIVE_CADENCE_MS` poll floor underneath it. `event:doorbell` is a SHARED
#    topic and its filter is fail-safe by design (it rings only on a positive
#    hardware-UID match), so a UID comparison that never matches is
#    indistinguishable from a venue that never publishes. `DIAG_LINE_BELLS` and
#    `DIAG_LINE_FLAGS` separate them, and note the counters are DISJOINT:
#    `doorbells` counts only broadcasts that passed the filter, so the signature
#    of a filter that never matches is `other` climbing while `Bells` stays 0.
# 4. And on 2026-08-28 a live `0x04` UserBroadcast was captured ON THE WIRE by
#    `realtime_join_probe.py --listen`, which runs the badge's own shipping
#    `RealtimeClient` -- so the server-side fan-out is proven and the badge still
#    read `Bells 0  other 0`. Neither counter can explain that: both count
#    broadcasts that reached layer 3, and an opcode-2 frame the decoder refuses
#    is counted and SKIPPED by `_handle_binary` without producing one.
#    `DIAG_LINE_BELLS`'s third field is that counter, and it is the difference
#    between a decoder bug and a vendored WebSocket that delivers no binary
#    frames at all.
#
# EVERY VALUE IS STILL FOLDED AND BOUNDED BEFORE IT IS DRAWN. The words are the
# runtime's; the GLYPHS are still this app's pre-baked 95, and the band is still
# 308 px. `last_error` is `_error_text`'s 160-character "ClassName: message" and
# a mode literal can come from a `/system/lib` newer than this app, so both go
# through `ascii_fold` and `DIAG_TEXT_CHARS`; the counters go through
# `DIAG_COUNT_MAX`. See those constants.

#: HOW MUCH OF A RUNTIME-SUPPLIED STRING THIS SCREEN WILL DRAW.
#:
#: THE BOUND IS TYPOGRAPHY, WHICH IS WHY IT LIVES IN THE COPY MODULE AND NOT IN
#: THE MODEL. `settings_model` applies it; this file owns the number, because it
#: is the number `test_settings_fit.py` prices -- one constant, one worst case,
#: one place to change if the band ever changes.
#:
#: FIFTEEN, AND IT IS DERIVED RATHER THAN CHOSEN. `W` is the widest glyph in
#: `MonaSans-Medium` at 17 pt (14.742 px) and the content width is 308 px, so
#: the two lines that carry a runtime string are priced at their worst: `Push
#: mode: ` + 15 W is 306.9 px and `Last error: ` + 15 W is 295.4 px. Sixteen
#: busts the first of those, and this screen has exactly eight bands for eight
#: lines -- a line that wraps to two takes a band from a line below it.
#:
#: IT IS ENOUGH FOR THE THING IT IS FOR. The `session_failed` vocabulary fits
#: whole: `join_unanswered` is 15, `connect_failed` and `token_unusable` 14,
#: `join_refused` 12. A longer `OSError: [Errno ...]` loses its tail and keeps
#: the class, which is the half that identifies it.
DIAG_TEXT_CHARS = 15

#: HOW MUCH OF A RUNTIME STRING A **BARE** BAND WILL DRAW, under a label of its
#: own. A SECOND BOUND RATHER THAN A WIDER ONE, and the two are not
#: interchangeable: `DIAG_TEXT_CHARS` is right for a PREFIXED line and stays
#: exactly as it is (`Push mode: ` + 15 W is 306.9 px of 308, and 16 busts it).
#: A bare band has no prefix, so the whole 308 px is the value's and the bound
#: is the widest glyph in the face instead of a prefix's leftovers: `W` is
#: 14.742 px, 20 W is 294.84 px and 21 W is 309.6 -- ONE CHARACTER over. The
#: number is arithmetic, not taste.
#:
#: WHAT IT BUYS, AND IT IS THE WHOLE REASON PAGING WAS WORTH BUILDING. Under the
#: 15-character clip, `CredentialError: BADGELINK_HOST must be a bare hostname`
#: drew as `CredentialError` and `OSError: [Errno 6] Device not configured` drew
#: as `OSError: [Errn`. `settings_model.diag_chunks` spends three bands on
#: 60 characters and both survive, naming the exact field and the exact errno.
#:
#: ⚠ ONE DISCLOSED LOSS. `isconnected_exception` is 21 characters and draws as
#: `isconnected_exceptio`. It is the only word in the closed Wi-Fi vocabulary
#: over 20 and it stays unambiguous against every other word in that set. DO NOT
#: "fix" it by raising the bound to 21:
#: `test_every_body_string_fits_the_content_width_on_one_line` goes red,
#: correctly. Under the old 15-character clip it drew as `isconnected_exc` and
#: `radio_activate_error` as `radio_activate_`.
DIAG_CHUNK_CHARS = 20

#: THE HARDWARE BADGE ID'S OWN BOUND, and it is the VALUE's length rather than a
#: band's. `machine.unique_id().hex()` is 16 lowercase hex characters and every
#: one of them identifies the badge -- this is the value somebody reads down a
#: phone to match a row in a database -- so a clip that dropped the last nibble
#: would be worse than drawing no line at all, and `DIAG_TEXT_CHARS`' 15 does
#: exactly that. It fits with room: `Badge ` + 16 W is 285.0 px of the 308 px
#: band (18 W is what busts it), so nothing had to be traded for it.
DIAG_UID_CHARS = 16

#: THE LARGEST COUNTER VALUE DRAWN AS ITSELF; past it the line reads `9999+`.
#:
#: A CAP AND NOT A CLIP. Clipping 12345 to `1234` is a WRONG NUMBER a reader
#: would believe; `9999+` is a true statement about a value too wide for the
#: band. It is reachable in the field rather than theoretical: an 800-badge
#: fleet show is 799 suppressions on every badge, so `doorbells_filtered` passes
#: four figures after about a dozen shows.
DIAG_COUNT_MAX = 9999
#: The same idea for the demotion pair, which is bounded by construction --
#: `failed_sessions` cannot exceed `DEMOTE_AFTER_SESSIONS`, which is 3 -- so
#: this is a backstop against a hand-edited or newer runtime rather than a
#: budget. It is tighter because its line already carries two four-figure
#: counters: `Joins 9999+  fails 9999+  demote 99+/99+` is 293.8 px of 308.
DIAG_SMALL_MAX = 99
#: The worst values the bounds above permit, for `every_string()`. Composed from
#: the constants, never spelled out, so a change to a bound reprices itself
#: instead of quietly leaving the corpus behind.
_WIDEST = "W" * DIAG_TEXT_CHARS
#: The bare-band worst case. ITS OWN ENTRY, because the two bounds are different
#: numbers: pricing a chunked line at `_WIDEST` would leave five characters of
#: the real worst case unmeasured on every error line this tile draws.
_WIDEST_CHUNK = "W" * DIAG_CHUNK_CHARS
_WIDEST_UID = "W" * DIAG_UID_CHARS
#: The SSID band's own worst case. ITS OWN ENTRY for `_WIDEST_CHUNK`'s reason:
#: `NET_SSID_CHARS` is a third bound and pricing it at `_WIDEST` would leave one
#: character of the real worst case unmeasured -- the one character that bound
#: exists to buy.
_WIDEST_SSID = "W" * NET_SSID_CHARS
_WIDEST_COUNT = "{}+".format(DIAG_COUNT_MAX)
_WIDEST_SMALL = "{}+".format(DIAG_SMALL_MAX)

ROW_DIAG_LABEL = "Diagnostics"
DIAG_TITLE = "Diagnostics"
#: C on this screen: drop the latched worst frame and start again. The verb is
#: the stutter meter's whole method -- hold a steady animation, trigger ONE
#: suspect operation by hand, read what it cost -- which needs a floor you can
#: zero between attempts. NOT "CLEAR": nothing is erased, a measurement is
#: restarted. 48.1 px of the 68 px softkey box, against `CANCEL`'s 62.69 px.
DIAG_RESET = "RESET"

#: No doorbell object on this badge: no push factory in `/system/main.py`, or a
#: `/system/lib` older than `push_control().diagnostics()`. NOT ZEROES -- a
#: zeroed counter is a measurement, and this is the absence of one.
DIAG_NO_PUSH = "No push details on this badge"
#: One field this build did not publish, where a number or a yes/no would go.
#: The line still draws, because the fields beside it are still true.
DIAG_MISSING = "?"
DIAG_YES = "yes"
DIAG_NO = "no"

#: `PushLink.mode()`. Its own line, and that is forced rather than chosen: the
#: line below carries three yes/no fields, and a worst-case mode literal beside
#: them measured 386.7 px against a 308 px band.
DIAG_LINE_MODE = "Push mode: {}"
#: `joined` (the channel is joined), `socket_open` (a socket exists) and
#: `targeted` (the ring filter CAN answer yes at all). The first two disagree
#: during a handshake, which is the window an operator is trying to see into;
#: `uid no` beside a climbing `other` on the line below is a badge that will
#: never ring, and `PushLink.snapshot`'s own comment names it the first thing to
#: read when the fleet delivers zero rows.
DIAG_LINE_LINK = "Join {}  sock {}  uid {}"
#: `sessions_joined` / `sessions_failed`, then the DEMOTION progress:
#: `failed_sessions` of `demote_after`. The last pair is the 2-of-3 against
#: 3-of-3 distinction; the first pair is whether this badge has ever joined at
#: all, which separates "it worked and stopped" from "it never worked".
DIAG_LINE_SESSIONS = "Joins {}  fails {}  demote {}/{}"
#: `doorbells` (broadcasts that PASSED the filter), `doorbells_filtered`
#: (broadcasts suppressed as somebody else's) and `binary_frames_ignored` (the
#: layer-2 counter, lifted by `network_runtime.PUSH_DIAGNOSTIC_CLIENT_KEYS`).
#: The first two are disjoint, not subset -- see the block above. "other" rather
#: than "filtered": the filter's question is whose bell it was.
#:
#: THE THIRD FIELD COSTS NO BAND AND ANSWERS THE 2026-08-28 QUESTION. A live
#: `0x04` `UserBroadcast` was captured ON THE WIRE that night by
#: `badgelink/host/realtime_join_probe.py --listen` -- 274 bytes, opcode 2,
#: topic `realtime:event:doorbell`, no `replayed` key -- so the server-side
#: fan-out is PROVEN and the host probe that saw it runs the badge's own
#: shipping `RealtimeClient`. The badge still read `Bells 0  other 0`, which
#: those two numbers alone cannot explain: they count broadcasts that reached
#: layer 3, and `_handle_binary` counts-and-SKIPS a frame the decoder refuses
#: without ever producing one. So `skip` climbing means opcode-2 frames DO
#: arrive and `phoenix.decode_binary` refuses them; `skip 0` beside two zeroes
#: means the vendored `aiohttp_ws` never handed a binary frame upward. That is
#: the whole remaining split, and it is one number.
#:
#: "skip" IS `_handle_binary`'S OWN WORD ("counted and SKIPPED rather than
#: dropped") and it is chosen over "raw" because a bare noun reads as a total: a
#: reader glancing at `raw 0` beside two other counts would take it for
#: "0 frames", which is the opposite of what a 0 here means. It is a THIRD field
#: rather than a ninth line because the screen has exactly eight bands and
#: `settings_view._draw_body` silently drops a line it has no whole band for --
#: which on this screen is the worst-frame readout. At its worst value the line
#: is 260.05 px of the 308 px band in the vector face (220.00 in the bitmap
#: fallback), against 175.45 px for the two-field version it replaces; a FOURTH
#: count would be 338.14 px and bust it. `test_settings_fit` prices it.
DIAG_LINE_BELLS = "Bells {}  other {}  skip {}"
#: `demoted` and `push_revoked`. Named `push_revoked` in the snapshot because
#: `network_runtime`'s own record already carries a `revoked` for the POLL's
#: terminal 403, and a transcript has to be able to hold both at once; on this
#: screen there is only one subject, so it is drawn as `revoked`.
DIAG_LINE_FLAGS = "Demoted {}  revoked {}"
#: `PushLink.last_error`, AS A BARE LABEL OVER ITS OWN BANDS.
#:
#: **`DIAG_LINE_ERROR = "Last error: {}"` IS RETIRED AND THIS REPLACED IT ON
#: 2026-08-29.** That line carried the value inline at `DIAG_TEXT_CHARS`, so
#: `OSError: [Errno 6] Device not configured` -- forty characters -- drew as
#: `Last error: OSError: [Errn` and the errno, the one half that identifies it,
#: was gone. Paging is what made the fix affordable: the error moved to its own
#: page with bands to spare, so the label gets one and
#: `settings_model.diag_chunks` spends up to three more at `DIAG_CHUNK_CHARS`.
#: The whole sentence now survives. It is `_error_text`'s "ClassName: message"
#: on most paths and layer 2's own `event.reason` on a refused or dropped join,
#: which is where `connect_failed` / `join_refused` / `join_unanswered` /
#: `token_unusable` land.
DIAG_LABEL_ERROR = "Last error"
#: Under the label when there is nothing to report. It replaces the chunks, not
#: the label: two identical bare sentences on one page cannot be told apart, and
#: the label is what says WHICH error is absent.
DIAG_NO_ERROR = "No error recorded"

#: THE TWO CAUSE LINES, PROMOTED TO THE OPERATOR'S SCREEN (2026-08-29). Both
#: values exist today and have exactly ONE reader between them, the Updates
#: screen -- which is the wearer's screen, in the wearer's words. An operator
#: holding somebody else's badge needs the same two facts, and
#: `push_cause_previous` in particular is the accessor that exists BECAUSE
#: READING DESTROYS THE ANSWER: `settings/__init__.py` calls `set_active(True)`
#: while this tile is open, which GRANTS the placement `push_cause()` would have
#: reported, and that mechanism hid the 2026-08-26 doorbell root cause for a
#: whole session.
#:
#: RAW CAUSE LITERALS, NOT THE WEARER SENTENCES. This screen's declared
#: exception applies: the words are the runtime's own, so a panel reading and a
#: serial capture say the same thing and can be correlated.
DIAG_LINE_CAUSE = "Cause {}"
DIAG_LINE_WAS = "Earlier {}"

#: PAGE 4, THIS BADGE. Every one of these is posted to the server on EVERY
#: heartbeat and none of them could be read off the badge in the hand -- which
#: is the wrong way round for the one day when the server is what nobody can
#: reach.
#:
#: ⚠ `Badge {}` CARRIES THE HARDWARE UID, NOT THE JWT SUBJECT. On the
#: shared-token fleet every badge ships a byte-identical `/secrets.py`, so the
#: subject is the same 16-hex value on all ~200 and names the FLEET rather than
#: a badge. Neither value is secret: `network_runtime` states in as many words
#: that a JWT `sub` is a public claim and that nothing is authorised by knowing
#: it.
DIAG_LINE_BADGE = "Badge {}"
#: `fleet` / `per_badge` / `?`. THE S0.8 ROLLOUT QUESTION -- "has this badge been
#: re-provisioned yet?" -- which nothing on the wire could answer, because the
#: rollout deliberately runs new firmware on OLD per-badge tokens as its safety
#: step and a fleet half-way through was indistinguishable from one that had not
#: started.
DIAG_LINE_TOKEN = "Token {}"
#: The first 8 hex of the boot session. Two serial rows or two server rows
#: sharing it came from one uninterrupted run, which is how an operator tells a
#: badge that has been resetting from one that has not.
DIAG_LINE_BOOT = "Boot {}"
#: `os.uname().version`, over its own bands for `DIAG_LABEL_ERROR`'s reason: a
#: build string is long, and a build string with its tail cut off cannot be
#: matched against the payload somebody installed.
DIAG_LABEL_BUILD = "Build"
#: **THE SETTINGS HALF OF A PROMISE MADE IN A DOCSTRING AND NEVER KEPT.**
#: `network_runtime.provisioning_fault` says the badge "says why on serial and
#: in Settings"; only the serial half was ever written. This is the one state in
#: which the badge refuses to network FOR THE LIFE OF THE FIRMWARE -- `poll`
#: returns DISCONNECTED above every path that opens or arms a socket -- and
#: until now it said nothing about it on any screen. It is drawn in WARN ink for
#: exactly that reason: nothing but re-provisioning moves it.
DIAG_FAULT_SHARED_SUB = "This badge is the fleet's id"
#: The runtime cannot answer the identity question at all: no network controller
#: on this badge, or one older than `NetworkService.identity`. The mirror of
#: `DIAG_NO_PUSH` and `DIAG_NO_CLOCK`, and deliberately not the same sentence --
#: telling an operator the wrong one is missing sends them to the wrong step.
DIAG_NO_ID = "No badge details on this badge"

#: `PushPolicy.policy_source` -> what it means, and THIS IS THE LINE THE SCREEN
#: WAS BUILT FOR. It is also the ONE field here that is translated rather than
#: passed through, because the raw word is actively misleading: `default` is not
#: a setting and not a refusal, it means no well-formed `push_enabled` has been
#: seen -- the state of every badge for the first 60-240 s of every boot.
#:
#: "Not sent yet" rather than "not checked yet", because the badge does not
#: check: the policy rides the poll response (`PushService.apply_steering` is
#: called only from `NetworkService._on_policy`), so "checked" would describe a
#: request this badge never makes.
DIAG_POLICY_LINES = {
    "default": "Policy: not sent yet",
    "server": "Policy: from the server",
    # A `push_enabled` that is not a boolean. It fails OPEN by design
    # (`PushPolicy.set_remote`: failing closed makes the kill switch itself
    # load-bearing), so this is a note about the DATA, not an outage.
    "malformed": "Policy: unreadable",
}
#: A source literal this build has never heard of. Raw, for the same reason
#: `NET_LINE_STATE` is raw: "no invented states" cuts both ways.
DIAG_POLICY_STATE = "Policy: {}"

#: The latched worst ENTRY-TO-ENTRY frame, in milliseconds. LATCHED, because a
#: stall the wearer blinked through has to still be on the screen when they look
#: down; RESET is what drops it.
DIAG_LINE_WORST = "Worst frame {} ms"
#: Before two frames have been entered. THE FIRST SAMPLE IS NOT A FRAME: it
#: would measure module construction to first entry, which is a different
#: quantity and a large one.
DIAG_LINE_WORST_NONE = "Worst frame not measured yet"

# -- WHY THE SCORES ARE NOT GOING UP: diagnostics page 5 (2026-08-29) ---------
#
# **THE INCIDENT IS RECORDED IN THE RUNTIME'S OWN COMMENT AND IT IS EXACTLY THIS
# SCREEN'S SHAPE.** `network_runtime._pump_scores`: *"five real scores sat on
# the owner's badge for a whole boot while the heartbeat and the settings read
# kept working, and nothing anywhere said the drain had stopped."* Every guard
# in that method used to `return None` in silence, because it runs on EVERY
# RENDERED FRAME and a per-frame print is unaffordable.
#
# `_score_stalled` fixed the SERIAL half on 2026-08-29 by latching the word, so
# it prints once per transition. **THAT LEAVES THE PULL HALF UNBUILT, AND THE
# RUNTIME SAYS SO IN SO MANY WORDS:** *"`score_stalled` is emitted on the
# TRANSITION, so an operator who attaches serial afterwards sees nothing at
# all; these two are the pull-based form of the same answer."* The two are
# `snapshot()["scores_pending"]` and `snapshot()["scores_stalled"]`, and until
# this page NOTHING READ EITHER. On 2026-10-02 nobody attaches serial at all,
# so the transition print reaches no one and the latch is the only copy of the
# answer there is.
#
# ⚠ **NOT ONE OF THESE SENTENCES IS A VERDICT ABOUT THE SERVER OR THE
# LEADERBOARD.** They restate the drain's own closed word in the wearer's
# language and nothing more, which is `NET_WIFI_REASON_LINES`' rule applied to
# a second closed vocabulary. A word from a `/system/lib` newer than this app is
# drawn RAW by `DIAG_SCORES_STATE` -- "no invented states" cuts both ways here
# too.

#: How many game slots are waiting to be posted. SLOTS AND NOT SUBMISSIONS:
#: `scorebox.pending` counts at most one per game since the 2026-08-26 rewrite,
#: so a wearer who played snake ten times offline reads `1`, which is the truth
#: about how many rows are waiting. Bounded by `DIAG_COUNT_MAX` like every other
#: counter in this tile, though `scorebox.MAX_SLOTS` is 16 and it cannot get
#: near it.
DIAG_LINE_SCORES_WAITING = "Scores waiting {}"
#: PAST EVERY GUARD: `_score_stall` is `None` and there is something to send, so
#: the drain is claiming its chore budget a record at a time. NOT "sent" --
#: nothing here waits for the acknowledgement, and a wearer told their score was
#: sent when the post is still in flight has been told the one thing that later
#: turns out wrong.
DIAG_SCORES_SENDING = "Sending them now"
#: `_score_stall is None` AND nothing pending. The healthy idle badge, said out
#: loud rather than left blank for `DIAG_NO_PUSH`'s reason: a blank band reads
#: as a line that failed to draw.
DIAG_SCORES_IDLE = "Nothing waiting to be sent"
#: `NetworkService.snapshot()` could not be asked at all -- no network
#: controller on this badge, or a `/system/lib` older than the accessor. The
#: mirror of `DIAG_NO_PUSH`, `DIAG_NO_CLOCK` and `DIAG_NO_ID`, and deliberately
#: its own sentence: telling an operator the wrong thing is missing sends them
#: to the wrong step.
DIAG_NO_SCORES = "No score details on this badge"

#: `_pump_scores`' SEVEN REFUSALS -> a sentence. **THE VOCABULARY IS CLOSED AND
#: IT IS THE RUNTIME'S**, keyed on the literals `_score_stalled` is called with,
#: and `settings/tests/test_settings_seam.py` is the drift detector that keeps
#: this table and that method the same seven words.
#:
#: THE ORDER BELOW IS `_pump_scores`' OWN GUARD ORDER, so a reader following the
#: source finds them in the sequence the badge actually walks: the in-flight
#: latch, then eligibility, then the operator's lever, then identity, then
#: storage.
DIAG_SCORES_STALL_LINES = {
    # The post went out and no answer came back yet. ORDINARY between frames --
    # this is the one word here that a healthy badge shows -- which is why it
    # says "waiting" and not anything that reads as a fault.
    "inflight": "Waiting for the server",
    # No socket. The commonest word by far, and the one that sends a reader to
    # the Network screen rather than to the scores.
    "offline": "Not connected yet",
    # `fleet_settings.scores_enabled`, the operator's leaderboard lever. "For
    # now" is exact and it is `PUSH_LINE_BLOCKED`'s word for the same shape of
    # fact: the flag is the server's, the spool is durable, and every round the
    # wearer plays is still being kept.
    "fleet_disabled": "The event turned scores off for now",
    # `hardware_uid()` answered None. A badge that cannot name itself must not
    # write a row that says it is somebody else, so the score STAYS -- which is
    # the half of this the sentence has to carry.
    "no_badge_id": "This badge cannot name itself",
    # The `scorebox` import failed. `scorebox_unavailable` already carries the
    # import error itself, once per boot; this is the consequence in the
    # drain's own terms.
    "no_scorebox": "The score store is missing",
    # Scanned, and there is genuinely nothing. Distinct from `DIAG_SCORES_IDLE`
    # only in provenance -- this is the drain's word, that one is this page's
    # reading of a `None` stall -- and they are deliberately the SAME sentence,
    # because they are the same fact to a person.
    "spool_empty": "Nothing waiting to be sent",
    # The read raised. `NetworkService.last_error` holds the exception sentence
    # and the Network screen's page 4 prints it whole, which is where this word
    # sends a reader.
    "spool_unreadable": "The badge could not read them",
}
#: A stall word from a `/system/lib` newer than this app. Drawn RAW rather than
#: smoothed over, for `NET_LINE_STATE`'s reason.
DIAG_SCORES_STATE = "Scores: {}"

# -- the clock line ----------------------------------------------------------
#
# **THE STATE THIS LINE EXISTS FOR IS A FLEET-WIDE BRICK THAT LOOKS EXACTLY LIKE
# AN IDLE BADGE.** Verified TLS needs a plausible wall clock to check a
# certificate date. On RP2350 the powman always-on timer is the master and it
# resets when power is removed, so a badge back from hardware shipping mode
# wakes holding whatever the battery-backed PCF85063A kept -- a value the owner
# has been told to ASSUME IS GARBAGE. With no plausible clock,
# `clock_boot.resync` raises instead of failing soft (there is nothing to fall
# back to), `DeviceBackend._build_loop` never finishes, no `PollLoop` exists, no
# doorbell is ever built -- and `push_diagnostics()` answers None, so this
# screen drew `DIAG_NO_PUSH`: **the same sentence a badge that has simply not
# tried yet draws.** A venue that blocks UDP/123 makes that every badge in the
# hall, and at the venue there is NO USB: battery, handed out, and this panel is
# the only diagnostic channel there is.
#
# TWO FIELDS AND NOT THREE, AND THE BAND IS WHY. `Clock ` + the widest flag +
# two spaces leaves 233 px of the 308 px band, which is 15 `W` at 14.742 px --
# exactly `DIAG_TEXT_CHARS`, so the reason reuses the bound this screen already
# applies to every runtime string instead of inventing a second one. A third
# field (`Clock yes  sync no  ` + 15 W) is 356.7 px and busts it, and the cost of
# squeezing it in would be an 11-character reason, where `ntp_rejected:
# before_build_floor` and `ntp_rejected: implausible_shift` both collapse to
# `ntp_rejecte` and the gate that refused is gone.
#
# SO THE SECOND SLOT IS THE MORE SPECIFIC OF THE TWO ANSWERS: the skip reason
# when there is one, and the sync verdict when there is not. That is exact
# rather than a compromise -- `clock_boot.resync` returns `reason: "synced"` on
# success and a skip reason otherwise, so a reason in that slot ALREADY means
# the sync did not land.
DIAG_LINE_CLOCK = "Clock {}  {}"
#: A sync landed this boot: the clock has been checked against a server, so it
#: is verified and not merely plausible. `clock_boot.resync`'s own `reason` here
#: is the literal `synced`, which is a protocol word for the one field on this
#: screen whose reading is "nothing to explain" -- so it is the one clock value
#: that is translated, exactly as `policy_source` is and for the same reason.
DIAG_CLOCK_SYNCED = "sync yes"
#: No sync has landed and the runtime published no reason: nothing has tried
#: yet. The ordinary state of a badge with the radio off, which is a state a
#: wearer can be in for a whole conference.
DIAG_CLOCK_NO_SYNC = "sync no"
#: The `synced` key itself absent -- a `/system/lib` that publishes a clock
#: record this build does not fully know. `?` and never `no`, for the same
#: reason `_flag` has three answers: a zero is a measurement nobody took.
DIAG_CLOCK_UNKNOWN = "sync ?"
#: The runtime cannot answer the clock question at all: no network controller on
#: this badge, or one older than `NetworkService.clock_diagnostics`. The mirror
#: of `DIAG_NO_PUSH`, and NOT the same sentence -- a badge can have a doorbell
#: and no clock accessor, or the reverse, and telling an operator the wrong one
#: is missing sends them to the wrong install step.
DIAG_NO_CLOCK = "No clock details on this badge"


# -- setting the clock by hand -----------------------------------------------
#
# THE ONE REPAIR SCREEN IN THIS TILE, and the only one whose copy has to work for
# a wearer standing in a hall with no laptop, no USB and a badge that cannot
# reach the network at all. Verified TLS needs a plausible wall clock; a venue
# that blocks UDP/123 leaves the badge unable to get one from a server, and
# `settings_model.CLOCK` carries the owner ruling this sits against and why it is
# built anyway.
#
# **IT IS THE SECOND DECLARED EXCEPTION TO THE COPY RULING**, and a much smaller
# one than Diagnostics': every sentence here is the wearer's, except the two
# FRAME LABELS -- **PDT** and **UTC** -- which are unavoidable and which are the
# whole shape of this screen since the owner's 2026-08-28 words:
#
#     "having the UTC time visible is kinda cool but maybe it should be smaller,
#     like more of a sanity check for anyone looking at it ... the user
#     interface, user experience should be PST time, the local time zone. The UI
#     should just say PST and that would be the main focus of what they're
#     updating."
#
# So the WEARER'S frame is event-local and the badge's frame is UTC, and both are
# on the panel with the wearer's on top. Neither label can be dropped:
#
# * the badge's clock contract is UTC end to end -- `clock_boot.resync` sets it
#   from `gmtime` and the PCF holds that verbatim (VAL-041-BLR measured a sync
#   moving a badge's local 22:05 to 04:06, the Mountain offset of the machine
#   running the probe) -- so the value that is WRITTEN is a UTC one and the
#   read-out that proves it has to say so;
# * and `schedule` renders every clock through `event.utc_offset_min` and prints
#   `PDT` beside it, so a Clock screen labelling the same instant anything else
#   would be one badge disagreeing with itself on two screens.
#
# ⚠ **THE LABEL IS `PDT` AND NOT `PST`.** The owner says "PST" colloquially, the
# way most people do; 2026-10-02 is inside daylight time, and
# `schedule/badge/schedule/schedule.json` records `"timezone": "PDT"` with
# `"utc_offset_min": -420`. `CLOCK_LOCAL_SUFFIX` below is pinned against that
# field by `test_settings_clock.EventSeedTests`, so "fixing" it to PST is a red
# test rather than a badge whose two screens are an hour apart.

ROW_CLOCK_LABEL = "Clock"
CLOCK_TITLE = "Set the clock"
#: **THE HINT, WHICH IS NO LONGER THE CURSOR.** This line named the selected
#: field because the panel had no way to mark one: `settings_view` drew each body
#: line as ONE point-form string in ONE ink. Since 2026-08-28 the highlight IS
#: the cursor -- a reverse-video block on the field itself -- and this line is
#: kept as what a marker cannot do, which is teach the control: it says which
#: KEYS move the value, on a screen where four of the five buttons now do
#: something.
#:
#: DRAWN ONLY ON A VALUE FIELD. On Save or Cancel there is no value to change and
#: the bar's own B label is already the instruction, so the line is absent rather
#: than reworded -- the same "only when there is one" discipline the refusal line
#: and the diagnostics error line follow.
CLOCK_FIELD_LINE = "Up and down change the {}"
CLOCK_FIELD_NAMES = ("year", "month", "day", "hour", "minute")
#: Appended to the stamp the wearer is EDITING, on the editor and on the note
#: after a commit. It is the whole answer to "which time am I typing?", and it
#: replaced the sentence `Use UTC, not your local time`, which stopped being true
#: the moment the fields became event-local (owner request, 2026-08-28).
#:
#: A LABEL RATHER THAN A SENTENCE, because it has to sit on the value it
#: describes. The frame is a property of those digits, not an instruction beside
#: them, and putting it on the line means the panel never has to spend a band
#: saying which of two stamps is which.
#:
#: ⚠ `PDT`, NOT `PST` -- see the block above. Pinned against the shipped agenda's
#: `event.timezone` by `test_settings_clock.EventSeedTests`.
CLOCK_LOCAL_SUFFIX = " PDT"
# -- the editor's bar, and the two buttons that are ON the panel --------------
#
# **THE 2026-08-28 REDESIGN'S COPY.** `SET` on B and `NEXT` on C are retired.
# `NEXT` was honest for a five-field walk with no horizontal axis; the screen now
# HAS one -- two rows of fields with two buttons to their right -- and the owner
# asked for a terminal/BIOS interaction over it, so the keys name directions.
#
# **A SAYS `LEFT` OR `BACK` AND THE BAR IS WHERE THE DIFFERENCE LIVES (§I5: a
# live key's meaning is on screen the whole time).** A moves the highlight left,
# except at the leftmost stop of a row, where it leaves the screen committing
# nothing (§I2's five-A test). Without the changing label that would be a key
# that silently changes meaning under the wearer's thumb; with it, the wearer at
# the leftmost field can SEE that the next press is the way out.
#
# `LEFT` AND `RIGHT` ARE NOT VERBS, WHICH THE REST OF THIS BAR IS. That is a
# deliberate exception rather than an oversight: the layout is spatial now, and
# what a wearer needs from these two keys is which way the green block moves. An
# arrow glyph would have said it in less ink and is what a terminal would use;
# words are chosen because this bar is uppercase words everywhere else and a lone
# 8.9 px `<` beside `CANCEL` reads as debris rather than as a control.
CLOCK_LEFT = "LEFT"
CLOCK_RIGHT = "RIGHT"
#: B on a value field: the OTHER row. Two labels rather than one toggle word,
#: because a bare `ROW` would not say which one the press goes to -- and the
#: wearer can already see both rows, so naming the destination is free.
CLOCK_ROW_DATE_LABEL = "DATE"
CLOCK_ROW_TIME_LABEL = "TIME"
#: B on the two buttons. `SAVE` is the verb the chip beside it carries, so the
#: bar needs no translation; `CANCEL` at 62.69 px of the 68 px box is once again
#: this app's widest label, the seat `DECLINE` and the pair flow's own `CANCEL`
#: held until the Phone row was deleted earlier the same day.
CLOCK_SAVE = "SAVE"
CLOCK_CANCEL = "CANCEL"

#: The two buttons AS THEY ARE DRAWN ON THE PANEL, in the body, beside the time.
#:
#: **BRACKETS, AND THEY ARE SAFE HERE FOR A MEASURED REASON.** `settings_view`
#: draws every body line in POINT form, which parses no markup at all, and
#: `docs/engineering-findings.md` § "What a `[` in wearer text ACTUALLY does"
#: measured the rest: a lone `[` and an unknown name like `[ Save ]` render as
#: written in BOTH forms, and only a KNOWN renderer name reached with unusable
#: parameters (`[sprite:x]`, `[pen:1]`) raises. `measure_text` parses nothing
#: either, so the width priced by the fit lane is the width drawn. **They must
#: never be put in a SOFTKEY label**, which is the one rect-form draw left in the
#: app.
#:
#: WHY DRAW THEM AT ALL, when the highlight already shows which stop the cursor
#: is on: unhighlighted, two bare words floating beside a timestamp read as copy.
#: Bracketed they read as buttons before anything is selected, which is what
#: tells a wearer the row continues rightward at all.
#:
#: Title case rather than the bar's uppercase, because they are BODY text drawn
#: at the body size in the body's own voice -- and because that is how the owner
#: drew them.
CLOCK_SAVE_CHIP = "[ Save ]"
CLOCK_CANCEL_CHIP = "[ Cancel ]"
#: The gap between the local stamp and the first button, and between the two
#: buttons. SPACES RATHER THAN A COLUMN THE VIEW COMPUTES, so the whole line is
#: one string the fit lane can price and one string the highlight can index into.
#: The time block is fixed width (`{:02d}:{:02d}` plus a fixed suffix), so the
#: buttons never move under a press.
CLOCK_CHIP_GAP = "      "
CLOCK_CHIP_SPACE = "  "

#: `clock_set`'s three results, spelled here for the reason every other mirrored
#: literal in this tile is: the model routes on them, and a screen may only draw
#: strings this build knows about. `settings/tests/test_settings_clock.py` pins
#: them against the real module.
CLOCK_RESULT_SET = "set"
CLOCK_RESULT_VOLATILE = "volatile"
CLOCK_RESULT_FAILED = "failed"

#: Appended to the SECONDARY stamp -- the badge's own frame, on both the editor
#: and the note. It used to be the note's only frame label, on the note's only
#: stamp; since 2026-08-28 there are two stamps on both screens and the label is
#: what tells them apart.
#:
#: THE TWO STAMPS ARE THE SAME FIXED WIDTH ON PURPOSE (`clock_stamp`), so drawn
#: at the same margin one under the other their digits line up column for column
#: and the conversion is checkable at a glance -- which is the entire job the
#: owner gave this line ("more of a sanity check for anyone looking at it").
#: That is also why it carries the DATE and not just the time: at -420 every
#: event-local hour from 17:00 rolls UTC into the next day, and a bare `00:00
#: UTC` under `2026-10-02  17:00 PDT` would look like a badge set to the wrong
#: day rather than a correct conversion.
CLOCK_UTC_SUFFIX = " UTC"
CLOCK_DONE_TITLE = "Clock set"
#: THE PROMISE THE PCF WRITE BUYS, and the whole reason both clocks are written:
#: the RP2350 always-on timer resets when power is removed, so a system-only
#: write means every wearer sets the clock twice.
CLOCK_DONE_KEPT = "The badge keeps this without power"
#: The half-write. The system clock took it, the external chip did not, so it is
#: true for this session and gone with the battery. Saying "kept" here would be
#: wrong in the one direction nothing later corrects.
CLOCK_VOLATILE_TITLE = "Set for now"
CLOCK_DONE_VOLATILE = "It is lost if the battery goes flat"
#: SAID ON BOTH NOTES, because it is the honest limit of a hand-set clock and the
#: owner's 2026-08-24 doctrine in the wearer's words: this is a claim, and the
#: badge prefers a server's answer the moment it can get one.
CLOCK_DONE_REPLACED = "A server replaces it when it can"

#: `clock_boot.evaluate_ntp`'s refusal literals -> what a wearer can act on,
#: keyed on the RUNTIME's words exactly as `DIAG_POLICY_LINES` is. The floor date
#: is composed by the model from `CLOCK_FLOOR_EPOCH` rather than written out
#: here, so moving the floor moves the sentence with it.
CLOCK_TOO_EARLY = "Too early. Nothing before {}"
CLOCK_TOO_LATE = "Too late. Nothing after {}"
#: The NTP era-rollover band. A wearer cannot reach it by the mechanism it exists
#: for, only by typing a date in one week of 2036 -- and `clock_boot.resync`
#: treats a clock in there as NO clock, so accepting it would tell them the badge
#: was fixed while every handshake went on failing.
CLOCK_BAD_DATE = "The badge cannot use that date"
#: The write itself refused. Retryable in place: the wearer stays on the editor
#: with the value they typed and B is still SET.
CLOCK_NOT_WRITTEN = "The badge could not set the clock"
#: A refusal literal from a `clock_boot` this build has never heard of. Named
#: rather than drawn blank, for `NET_LINE_STATE`'s reason.
CLOCK_REJECT_UNKNOWN = "That date cannot be used"


# -- what the view draws that no view-model supplies -------------------------
#
# EMPTY SINCE 2026-08-28, AND WORTH A LINE RATHER THAN A DELETED HEADING. Four
# strings lived here -- the two no-encoder lines, the too-long-payload fault and
# the `Or type` caption -- and all four belonged to the claim QR, which went with
# the Phone row. `settings_view` now draws nothing it was not handed in a model.


def every_string():
    """Every string this tile can draw, for the fit tests and the generator.

    Composed rather than listed: the tables above are the source, so a copy
    change cannot land without its own fit check. The worst cases are included
    on purpose -- a runtime literal from a `/system/lib` newer than this build is
    clipped by `settings_model.diag_text` and priced HERE at that clip, not at
    the example value a fixture happens to show.
    """
    out = set()
    out.add(BACK)
    out.add(OPEN)
    out.add(START)
    out.add(STOP)
    out.add(ROW_NETWORK_LABEL)
    out.add(ROW_PUSH_LABEL)
    out.add(ROW_SLEEP_LABEL)
    out.add(ROW_BRIGHT_LABEL)
    out.add(ROW_SCORES_LABEL)
    out.add(SLEEP_TITLE)
    out.add(SLEEP_LINE_WAKE)
    out.add(SLEEP_LINE_RESTART)
    out.add(KEEP)
    out.add(ERASE)
    out.add(SCORES_TITLE)
    out.add(SCORES_LINE_CLEARS)
    out.add(SCORES_LINE_SPOOL)
    out.add(SCORES_LINE_SENT)
    out.add(SCORES_LINE_KEEPS)
    out.add(SCORES_DONE_TITLE)
    out.add(SCORES_DONE_LINE)
    out.add(SCORES_FAILED_TITLE)
    out.add(SCORES_FAILED_LINE)
    out.add(BRIGHT_TITLE)
    # EVERY RUNG, in all three places a rung name is drawn: the body line, the
    # composed menu row and the two softkeys. The ladder is five names, so this
    # is the whole space rather than a sample of it.
    out.update(backlight.NAMES)
    for name in backlight.NAMES:
        out.add(BRIGHT_LINE.format(name))
        out.add("{}  {}".format(ROW_BRIGHT_LABEL, name))
    out.update(STATUS_WORDS.values())
    out.update(PUSH_WORDS.values())
    # EVERY CAUSE, from the table rather than a list, so a ninth one is priced
    # against the band by the same lane that refuses to let it be unmapped.
    out.update(PUSH_CAUSE_LINES.values())
    # AND EVERY PAST FORM, on the same terms. These are drawn only on a badge
    # whose doorbell was failing BEFORE the wearer walked to this screen, which
    # is the rarest copy in the app and therefore the copy most likely to reach a
    # panel unpriced -- the exact shape of the `TURN...` and `ECLIN` defects.
    out.update(PUSH_WAS_LINES.values())
    out.update((
        VALUE_UNAVAILABLE, NET_NOT_INSTALLED, NET_LINE_CONNECTED,
        NET_LINE_CONNECTING, NET_LINE_UNREACHABLE, NET_LINE_STOPPED,
        NET_LINE_STOPPED_WHY, NET_LINE_OFF, NET_LINE_NO_SESSION,
        NET_LINE_REBOOT, NET_LINE_JOINING, NET_LINE_NO_WIFI,
        PUSH_TITLE, PUSH_QUESTION, PUSH_LINE_ON, PUSH_LINE_TRYING,
        PUSH_LINE_NORMAL, PUSH_LINE_DEMOTED, PUSH_LINE_BLOCKED, PUSH_LINE_OFF,
    ))
    # THE FOUR-PAGE NETWORK SCREEN AND THE FOUR-PAGE DIAGNOSTICS SCREEN, priced
    # from the tables rather than listed, so a copy change cannot land without
    # its own fit check. EVERY runtime slot is filled with the WIDEST value its
    # own clip permits, never with an example: `_WIDEST` for a prefixed line,
    # `_WIDEST_CHUNK` for a bare one, and the two are different numbers.
    out.update((
        NET_NO_RADIO, NET_NO_LINK, NET_DNS_NONE, NET_NO_ERROR,
        NET_LABEL_WHY, NET_LABEL_ERROR, NET_LABEL_LINK_ERROR,
        DIAG_NO_ERROR, DIAG_NO_ID, DIAG_LABEL_ERROR, DIAG_LABEL_BUILD,
        DIAG_FAULT_SHARED_SUB,
    ))
    # EVERY WI-FI REASON SENTENCE. The map is closed and the model falls back to
    # a RAW line for anything outside it, so both halves are priced.
    out.update(NET_WIFI_REASON_LINES.values())
    for stage in NET_STAGE_WORDS + (DIAG_MISSING,):
        out.add(NET_LINE_STAGE.format(stage))
    # A NEGATIVE CYW43 STATUS AT BOTH SIGNS AND AT THE CLIP. `status_-3` is the
    # spurious one the 2026-08-13 report recorded on CORRECT credentials, and it
    # is on this screen as a raw word for exactly that reason.
    for value in ("status_-3", "status_-2", _WIDEST):
        out.add(NET_LINE_WIFI_STATUS.format(value))
    for value in ("connection_lost", _WIDEST):
        out.add(NET_LINE_WIFI_REASON.format(value))
    for literal in ("off", "connecting", "online", "backoff", DIAG_MISSING,
                    _WIDEST):
        out.add(NET_LINE_RADIO.format(literal))
    for literal in ("connected", "connecting", "disconnected", "backoff",
                    "stopped", "revoked", DIAG_MISSING, _WIDEST):
        out.add(NET_LINE_LINK_STATE.format(literal))
    for value in ("opened", "LinkStalled", "LinkError", "LinkRevoked",
                  DIAG_MISSING, _WIDEST):
        out.add(NET_LINE_OUTCOME.format(value))
    # TEST-NET-2 exercises a normal dotted address without embedding a private
    # operator-network literal in the bytecode shipped to every badge.
    for address in ("198.51.100.1", "255.255.255.255", DIAG_MISSING):
        out.add(NET_LINE_RESOLVER.format(address))
    for count in ("0", "3", _WIDEST_COUNT, DIAG_MISSING):
        out.add(NET_LINE_TRIES.format(count, count))
        out.add(NET_LINE_DNS_COUNTS.format(count, count))
        out.add(NET_LINE_OPENS.format(count, count))
        out.add(NET_LINE_SPLIT.format(count, count))
        out.add(NET_LINE_HELD.format(count))
        out.add(NET_LINE_STALL.format(count))
    for region in ("US", "GB", DIAG_MISSING, _WIDEST):
        out.add(NET_LINE_REGION.format(region))
    # THE VENUE'S NETWORK NAME, AT ITS OWN BOUND AND NOT AT `_WIDEST`. This is
    # the one prefixed line in the tile with a bound of its own -- 16 rather
    # than 15 -- so pricing it from `_WIDEST` would leave the widest string it
    # can actually draw unmeasured by exactly the character that bound was
    # bought for. `DIAG_MISSING` is deliberately NOT here: the model draws no
    # band at all when there is no name, so `Network ?` is not a string this
    # app can produce.
    for ssid in ("badge-venue", "SupabaseLaunchWeek", _WIDEST_SSID):
        out.add(NET_LINE_SSID.format(ssid))
    for value in ("fleet", "per_badge", DIAG_MISSING, _WIDEST):
        out.add(DIAG_LINE_TOKEN.format(value))
    for value in ("0123456789abcdef", _WIDEST_UID, DIAG_MISSING):
        out.add(DIAG_LINE_BADGE.format(value))
    for value in ("0123abcd", DIAG_MISSING):
        out.add(DIAG_LINE_BOOT.format(value))
    for cause in tuple(PUSH_CAUSE_LINES) + (DIAG_MISSING, _WIDEST):
        out.add(DIAG_LINE_CAUSE.format(cause))
        out.add(DIAG_LINE_WAS.format(cause))
    # THE BARE CHUNK, ONCE. Every chunked line on both screens -- the Wi-Fi
    # reason, both network errors, the push error and the firmware build -- is
    # the same worst case, because `diag_chunks` cuts every one of them to the
    # same width with the same hard chop.
    out.add(_WIDEST_CHUNK)
    # THE PAGED TITLES, AT EVERY ORDINAL BOTH SCREENS CAN PRODUCE. A photograph
    # of a badge in a hall is the only bug report this event will produce, and
    # the ordinal is what makes it readable -- so it is priced like any other
    # drawn string rather than assumed to be short.
    # DIAGNOSTICS IS FIVE SINCE THE SCORE-DRAIN PAGE LANDED (2026-08-29) and
    # Network is still four. The counts are spelled here rather than imported,
    # because `settings_model` imports THIS module and the reverse would be a
    # cycle -- and `test_settings_fit` walks `settings_model.DIAG_PAGES` and
    # `NETWORK_PAGES` against the titles the models actually publish, so a count
    # that drifts out of this loop fails there rather than reaching a panel.
    for label, pages in ((ROW_NETWORK_LABEL, 4), (DIAG_TITLE, 5)):
        for index in range(pages):
            out.add(PAGE_TITLE.format(label, index + 1, pages))
    # Composed rows, exactly as `Settings.menu_label` composes them.
    for value in STATUS_WORDS.values():
        out.add("{}  {}".format(ROW_NETWORK_LABEL, value))
    for value in PUSH_WORDS.values():
        out.add("{}  {}".format(ROW_PUSH_LABEL, value))
    # The runtime-composed families, at a normal value and at the worst value
    # the shared modules permit. THE OWNER-HINT FAMILY IS GONE: `Linked to sam.`
    # and its 64-character worst case were the pair store's, and no screen in
    # this tile reports an account any more.
    for literal in ("disconnected", "backoff", "connecting", "connected",
                    "stopped", "revoked", "None"):
        out.add(NET_LINE_STATE.format(literal))
    for literal in ("push", "trying", "polling", "demoted", "blocked",
                    "network_off", "unavailable", "None"):
        out.add(PUSH_LINE_STATE.format(literal))
    # THE DIAGNOSTICS SCREEN, AT ITS WORST VALUES AND NOT ITS EXAMPLE ONES.
    # Every field on it is composed at runtime from a counter or a runtime
    # literal, so an example row prices nothing: the strings that can actually
    # reach a panel are the ones where every slot is as wide as this app will
    # let it get. `_WIDEST` is a clipped worst case rather than an arbitrary
    # long string, because `settings_model` is what does the clipping and the
    # two numbers have to be the same number (`test_settings_fit` asserts it).
    out.add(ROW_DIAG_LABEL)
    out.add(DIAG_TITLE)
    out.add(DIAG_RESET)
    out.add(DIAG_NO_PUSH)
    out.add(DIAG_LINE_WORST_NONE)
    out.update(DIAG_POLICY_LINES.values())
    for value in ("default", "server", "malformed", _WIDEST):
        out.add(DIAG_POLICY_STATE.format(value))
    for mode in ("push", "trying", "polling", "demoted", "blocked",
                 "network_off", _WIDEST):
        out.add(DIAG_LINE_MODE.format(mode))
    for flag in (DIAG_YES, DIAG_NO, DIAG_MISSING):
        out.add(DIAG_LINE_LINK.format(flag, flag, flag))
        out.add(DIAG_LINE_FLAGS.format(flag, flag))
    # THE TWO BOUNDS ARE DIFFERENT AND THE CORPUS HAS TO KEEP THEM APART. The
    # first two slots of the sessions line are cumulative counters
    # (`DIAG_COUNT_MAX`); the demotion pair after them is bounded by
    # `DEMOTE_AFTER_SESSIONS` and gets the tighter `DIAG_SMALL_MAX`. Pricing all
    # four at the wide bound would reject a layout the app cannot produce, and
    # pricing all four at the tight one would leave the real worst case unpriced.
    for count in ("0", "3", _WIDEST_COUNT, DIAG_MISSING):
        for small in ("0", "3", _WIDEST_SMALL, DIAG_MISSING):
            out.add(DIAG_LINE_SESSIONS.format(count, count, small, small))
        out.add(DIAG_LINE_BELLS.format(count, count, count))
        out.add(DIAG_LINE_WORST.format(count))
    # THE CLOCK LINE, at the widest value of BOTH slots. The reason slot carries
    # a runtime literal clipped by `settings_model.diag_text`, so `_WIDEST` is
    # the string that can actually reach the panel -- and it is the binding case
    # on this line by a long way (296.0 px of 308 in the vector face, against
    # 152.7 for `Clock yes  sync yes`).
    out.add(DIAG_NO_CLOCK)
    for flag in (DIAG_YES, DIAG_NO, DIAG_MISSING):
        for tail in (DIAG_CLOCK_SYNCED, DIAG_CLOCK_NO_SYNC, DIAG_CLOCK_UNKNOWN,
                     _WIDEST):
            out.add(DIAG_LINE_CLOCK.format(flag, tail))
    # THE SCORE-DRAIN PAGE. Every sentence of the closed stall vocabulary is
    # priced from the TABLE rather than from a list, so an eighth refusal word
    # added to `_pump_scores` is measured against the band by the same lane that
    # refuses to let it be unmapped -- the rule `PUSH_CAUSE_LINES` already sets.
    out.add(DIAG_NO_SCORES)
    out.add(DIAG_SCORES_SENDING)
    out.add(DIAG_SCORES_IDLE)
    out.update(DIAG_SCORES_STALL_LINES.values())
    for value in ("offline", "spool_unreadable", DIAG_MISSING, _WIDEST):
        out.add(DIAG_SCORES_STATE.format(value))
    for count in ("0", "3", _WIDEST_COUNT, DIAG_MISSING):
        out.add(DIAG_LINE_SCORES_WAITING.format(count))
    # THE CLOCK SCREEN. Its stamps are fixed-width by construction, so their
    # extreme is the widest digits rather than a long string -- and the two
    # boundary sentences are composed by `settings_model` out of
    # `CLOCK_FLOOR_EPOCH`, so they are priced HERE at the widest instant that
    # arithmetic can produce rather than at today's floor.
    out.add(ROW_CLOCK_LABEL)
    out.add(CLOCK_TITLE)
    # THE EDITOR'S FIVE BAR WORDS (2026-08-28). All five are drawn on the same
    # screen at different moments, so all five are priced -- `CANCEL` is the
    # widest label the whole app can print, at 62.69 px of the 68 px box.
    out.add(CLOCK_LEFT)
    out.add(CLOCK_RIGHT)
    out.add(CLOCK_SAVE)
    out.add(CLOCK_CANCEL)
    out.add(CLOCK_ROW_DATE_LABEL)
    out.add(CLOCK_ROW_TIME_LABEL)
    out.add(CLOCK_DONE_TITLE)
    out.add(CLOCK_VOLATILE_TITLE)
    out.add(CLOCK_DONE_KEPT)
    out.add(CLOCK_DONE_VOLATILE)
    out.add(CLOCK_DONE_REPLACED)
    out.add(CLOCK_BAD_DATE)
    out.add(CLOCK_NOT_WRITTEN)
    out.add(CLOCK_REJECT_UNKNOWN)
    out.add("{}  {}".format(ROW_CLOCK_LABEL, ""))
    for name in CLOCK_FIELD_NAMES:
        out.add(CLOCK_FIELD_LINE.format(name))
    # BOTH SUFFIXES ON EVERY EXTREME STAMP SINCE 2026-08-28. The editor draws two
    # stamps now -- the edited event-local one and the UTC read-out under it --
    # so the LABELLED forms are what reaches the panel and the bare stamp alone
    # would leave that unmeasured. They are comfortable (163.1 px of 308 at the
    # widest digits); the binding line on this screen is the refusal below.
    for stamp in ("2026-08-08  00:00", "8888-88-88  88:88",
                  "0000-00-00  00:00"):
        out.add(stamp)
        out.add(stamp + CLOCK_UTC_SUFFIX)
    # **THE EDITOR'S OWN TWO ROWS SINCE THE 2026-08-28 REDESIGN.** The wearer's
    # value is no longer one stamp: it is `HH:MM PDT` with two BUTTONS beside it
    # over a bare `YYYY-MM-DD`, and the button row is the widest thing this
    # screen draws that is not the refusal sentence. Priced at the widest digits
    # the format can produce rather than at a plausible time, because the fields
    # are handed in by a seam and the stamp is a `{:02d}`. The note after a
    # commit drops the two buttons, so its shorter form is priced too.
    for hm in ("00:00", "88:88", "23:59"):
        out.add(hm + CLOCK_LOCAL_SUFFIX)
        out.add(hm + CLOCK_LOCAL_SUFFIX + CLOCK_CHIP_GAP + CLOCK_SAVE_CHIP
                + CLOCK_CHIP_SPACE + CLOCK_CANCEL_CHIP)
    for date in ("2026-10-02", "8888-88-88", "0000-00-00"):
        out.add(date)
    # ⚠ THE BOUNDARY SENTENCES CARRY A WHOLE STAMP SINCE 2026-08-28, not a date:
    # the bounds are UTC epochs, the panel is event-local, and at -420 neither
    # bound lands on local midnight -- so `settings_model` names the instant.
    #
    # THEY ARE NOW THE BINDING LINE ON THIS SCREEN AND THE FIT IS TIGHT. Today's
    # floor sentence measures 304.0 px of the 308 px content width in the vector
    # face, and the widest digits this arithmetic can produce measure 307.7 --
    # ONE CHARACTER of slack, confirmed by adding one and watching
    # `test_settings_fit.CopyFitTests` go red. So this loop is not optional
    # pricing: any further word here, or a floor date with wider digits, wraps.
    for stamp in ("2026-08-07  17:00", "2099-12-31  16:59",
                  "8888-88-88  88:88"):
        out.add(CLOCK_TOO_EARLY.format(stamp))
        out.add(CLOCK_TOO_LATE.format(stamp))
    return out
