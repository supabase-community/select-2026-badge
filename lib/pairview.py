"""Pure view-models for the BadgeLink Pair and Confirm screens.

Card E ships two screens over the transport-agnostic
:mod:`badgelink.pairstate` machine: the **Pair** screen (dynamic QR + countdown)
and the **Confirm** screen (6-char match code, B accepts). This module turns a
``pairstate`` snapshot into a drawing-agnostic view-model — the claim URL, the
countdown text, the QR layout math, the title/lines and the softkey labels — so
all of it is fixture-testable. The actual pixels (the frozen ``qrcode`` module,
``screen`` draws) are a thin device layer that consumes this model; they are the
only device-verify part.

There is **no badge-side unpair in v2** (locked-once-claimed): no phase here
offers an unpair action, and the ``UNPAIR_*`` pairstate phases are never reached.
"""

import pairstate


# Canonical claim host for the experiment (build brief D1 / OWNER-DECISIONS #4).
# A custom domain is deferred; pass ``base_url`` to override.
CLAIM_BASE_URL = "https://badge-badgelink.pages.dev"
CLAIM_PATH = "/p#"
QR_BORDER_MODULES = 4
QR_MAX_SCALE = 4


def claim_url(code, base_url=CLAIM_BASE_URL):
    """Build the QR/claim URL: ``<base>/p#<CODE>`` (code in the URL FRAGMENT).

    The fragment keeps the single-use code off the wire to the server on the
    initial GET (brief pairing flow); it is validated against the pairstate
    base32 alphabet so a malformed code never reaches the QR.
    """
    if not isinstance(code, str) or len(code) != 8:
        raise ValueError("claim code must be eight characters")
    if any(ch not in pairstate.PAIR_CODE_CHARS for ch in code):
        raise ValueError("claim code has non-base32 characters")
    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        raise ValueError("claim base URL must be https")
    return base_url.rstrip("/") + CLAIM_PATH + code


#: PHASE-2's CLAIM PATH, beside P1's ``/p#``. A separate path because the two
#: ceremonies are different: ``/p#`` carries an 8-character base32 pair code and
#: ``/d#`` carries a 32-hex device code plus the physical badge id.
DEVICE_CLAIM_PATH = "/d#"

#: The separator between the two halves of the device-claim fragment. A dot
#: because it is unreserved in a URL fragment and appears in neither field's own
#: alphabet, so the split is unambiguous without escaping.
DEVICE_CLAIM_SEPARATOR = "."

#: The server mints ``encode(gen_random_bytes(16),'hex')``, so 32 lowercase hex.
DEVICE_CODE_LENGTH = 32
#: ``machine.unique_id().hex()``.
DEVICE_BADGE_ID_LENGTH = 16


def device_claim_url(device_code, badge_id, base_url=CLAIM_BASE_URL):
    """The Phase-2 claim QR: ``<base>/d#<device_code>.<badge_id>``.

    **WHAT IS AND IS NOT IN THIS QR, because it is the whole security argument.**
    The ``device_code`` is a semi-public DELIVERY-CHANNEL id, not a secret of the
    same class as the PKCE verifier: whoever scans this can VOUCH -- an
    authenticated, attributable act by a human willing to bind the badge to their
    own account -- and still cannot retrieve the token, because retrieval also
    requires the verifier, which never leaves the badge. That is what closes the
    shoulder-surf-the-QR attack. The badge id rides along because the vouch has to
    know which badge it is claiming, and it is self-reported and untrusted anyway
    (the server proves possession with PKCE, not with this).

    THE FRAGMENT, like P1's, keeps both halves off the wire on the initial GET:
    a fragment is never sent to the server, so the code reaches the web app's
    JavaScript and nothing else.

    ⚠ **THE URL SHAPE IS A DRAFT AND IT IS FROZEN WITH THE WEB LANE, NOT HERE.**
    Phase 2's server and web halves are held; this is the badge-side seam, which
    must exist in the frozen firmware because it can never be added later. If the
    web lane wants a different path or separator, this is one constant each and
    the pinned test moves with it -- but it must move on BOTH sides in one change,
    which is exactly what pinning it buys.
    """

    if not isinstance(device_code, str) or len(device_code) != DEVICE_CODE_LENGTH:
        raise ValueError("device code must be 32 characters")
    for character in device_code:
        if character not in "0123456789abcdef":
            raise ValueError("device code must be lowercase hex")
    if (not isinstance(badge_id, str)
            or len(badge_id) != DEVICE_BADGE_ID_LENGTH):
        raise ValueError("badge id must be 16 characters")
    for character in badge_id:
        if character not in "0123456789abcdef":
            raise ValueError("badge id must be lowercase hex")
    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        raise ValueError("claim base URL must be https")
    return (base_url.rstrip("/") + DEVICE_CLAIM_PATH + device_code
            + DEVICE_CLAIM_SEPARATOR + badge_id)


def format_countdown(remaining_ms):
    """Format milliseconds remaining as ``M:SS`` (clamped to ``0:00``..``9:59``)."""
    if not isinstance(remaining_ms, int) or isinstance(remaining_ms, bool):
        raise ValueError("remaining_ms must be an integer")
    seconds = max(0, remaining_ms) // 1000
    if seconds > 599:
        seconds = 599
    return "{}:{:02d}".format(seconds // 60, seconds % 60)


def qr_layout(module_count, canvas_px, border_modules=QR_BORDER_MODULES, max_scale=QR_MAX_SCALE):
    """Compute integer QR scale + centered offset for a square canvas.

    Mirrors the qrcode probe's sizing: the largest 1..max_scale that fits the
    modules plus a quiet-zone border inside ``canvas_px``.
    """
    if not isinstance(module_count, int) or module_count <= 0:
        raise ValueError("module_count must be positive")
    if not isinstance(canvas_px, int) or canvas_px <= 0:
        raise ValueError("canvas_px must be positive")
    total_modules = module_count + border_modules * 2
    scale = max(1, min(max_scale, canvas_px // total_modules))
    extent = total_modules * scale
    offset = max(0, (canvas_px - extent) // 2)
    return {
        "scale": scale,
        "extent": extent,
        "offset": offset,
        "border_modules": border_modules,
    }


# Screen identifiers the app renders.
IDLE = "idle"
STARTING = "starting"
PAIR = "pair"
CONFIRM = "confirm"
ACKING = "acking"
PAIRED = "paired"
ERROR = "error"


def _base_model(screen, title, lines, softkeys):
    return {"screen": screen, "title": title, "lines": lines, "softkeys": softkeys}


def view_model(state, base_url=CLAIM_BASE_URL):
    """Map a :func:`badgelink.pairstate` snapshot to a drawing-agnostic model.

    Softkey labels name the pairstate event the app should emit on that press:
    e.g. ``{"B": "PAIR"}`` -> emit ``pair_pressed``. The app owns the wiring; this
    only says what to show.
    """
    if not isinstance(state, dict):
        raise ValueError("pair state must be a dict")
    phase = state.get("phase")
    error = state.get("last_error") or ""

    if state.get("revoked"):
        return _base_model(ERROR, "Unpaired", ["This badge was revoked."], {"B": "PAIR"})

    if phase == pairstate.UNPAIRED:
        if error:
            return _base_model(IDLE, "Pair this badge", [_friendly(error)], {"B": "PAIR"})
        return _base_model(IDLE, "Pair this badge", ["Press B to show a QR code."], {"B": "PAIR"})

    if phase == pairstate.STARTING:
        return _base_model(STARTING, "Starting…", ["Contacting the server."], {})

    if phase == pairstate.CODE:
        model = _base_model(
            PAIR,
            "Scan to pair",
            [],
            {"B": "CANCEL"},
        )
        code = state.get("code", "")
        model["qr_payload"] = claim_url(code, base_url)
        # The QR fragment is deliberately also printed on the panel. It is the
        # manual fallback when a phone camera cannot acquire the code, and it
        # lets the owner distinguish camera/angle trouble from an expired or
        # malformed claim without exposing the six-character confirmation code.
        model["manual_code"] = code
        model["countdown"] = format_countdown(state.get("remaining_ms", 0))
        return model

    if phase == pairstate.CONFIRM:
        model = _base_model(
            CONFIRM,
            "Confirm code",
            ["Does your phone show this code?"],
            {"B": "ACCEPT", "C": "DECLINE"},
        )
        model["match_code"] = state.get("match_code", "")
        model["countdown"] = format_countdown(state.get("remaining_ms", 0))
        return model

    if phase == pairstate.ACKING:
        lines = ["Finishing pairing…"]
        softkeys = {}
        if error:
            lines = [_friendly(error)]
            softkeys = {"B": "RETRY"}
        return _base_model(ACKING, "Almost there", lines, softkeys)

    if phase == pairstate.PAIRED:
        owner = state.get("owner_hint") or "your account"
        # No badge-side unpair in v2: no unpair softkey is offered.
        return _base_model(PAIRED, "Paired", ["Linked to {}.".format(owner)], {})

    # UNPAIR_* phases are unreachable in v2; render a safe paired-ish fallback.
    return _base_model(PAIRED, "Paired", ["This badge is linked."], {})


_FRIENDLY = {
    "pair_expired": "The code expired. Try again.",
    "confirm_expired": "Confirmation timed out. Try again.",
    "pair_cancelled": "Pairing cancelled.",
    "pair_declined": "Pairing declined.",
    "pair_start_failed": "Could not reach the server.",
    "pair_ack_failed": "Could not finish pairing.",
    "revoked": "This badge was revoked.",
    "remote_unpaired": "Unlinked from your account.",
}


def _friendly(error):
    return _FRIENDLY.get(error, "Something went wrong. Try again.")
