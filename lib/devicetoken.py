"""Phase-2 verified tier, badge side: the PKCE verifier and the token store.

**WHY THIS SHIPS IN THE FROZEN FIRMWARE WITH NO SERVER TO TALK TO.** The Phase-2
claim ceremony is HELD server-side, but its badge-side hooks cannot be added
later: the firmware is gang-cloned onto ~800 badges from one golden image and
there is no per-unit step and no update path afterwards. Backend and web stay
editable forever; this file does not. So the hooks freeze now and the ceremony
chases them.

WHAT THE VERIFIED TIER IS, in one paragraph, because everything here follows from
it. The floor is a SHARED authenticated JWT: identical on every badge, so its
``sub`` identifies the FLEET and carries no per-badge information at all. Every
per-badge signal on the floor is therefore self-reported and untrusted -- the
``p_badge_id`` argument, the ``x-badge-id`` header. The verified tier adds the one
non-spoofable per-badge credential: an opaque random bearer minted by the server
when a human vouches for a scanned QR, stored here, and sent as ``x-device-token``
on PostgREST writes. ``whoami()`` means "a badge, some badge"; the device token
means "this badge".

FOUR PROPERTIES THIS MODULE OWES THE REST OF THE SYSTEM, each of them a decision:

* **THE VERIFIER NEVER TOUCHES FLASH.** PKCE's whole security argument is that the
  QR carries the ``device_code`` (semi-public, it is a delivery-channel id) while
  the verifier stays on the device that generated it. A shoulder-surfer who
  photographs the QR can vouch -- an attributable act by an authenticated human --
  and still cannot retrieve the token. Persisting the verifier would hand that
  guarantee to anyone who later reads ``/state``.
* **THE TOKEN STORE IS TOTAL.** Missing, corrupt, oversize, wrong schema, a
  half-written temp file: every one answers ``None`` and the badge stays on the
  floor. A verified tier that could raise would make a claimed badge LESS reliable
  than an unclaimed one, which inverts the whole point.
* **THE WRITE IS ATOMIC, temp -> flush -> sync -> rename**, the same recipe
  ``openapp_note`` uses, because the token arrives exactly once. The server's
  retrieve is idempotent within a grace window, so a crash before the rename is
  recoverable -- but only if a crash can never leave a half-token that reads as
  whole. The rename IS the commit.
* **THE TOKEN IS NEVER LOGGED.** Not in an event, not in a snapshot, not in an
  error string. It is a bearer credential with an INDEFINITE lifetime and no
  refresh path (owner ruling 1): revocation is the only lifecycle lever, so a
  token in a log is a token that stays useful to whoever reads the log.

This module imports nothing but ``json`` and ``os`` and holds no network code, so
it is testable under CPython and cannot take a boot down by being present.
"""

import json
import os


SCHEMA = 1

#: WHERE THE TOKEN LIVES. Under ``/state`` and NOT in ``secrets.py``: the golden
#: image's ``secrets.py`` is byte-identical across the fleet and is not writable
#: at runtime, while this is per-badge and arrives after provisioning.
DEFAULT_PATH = "/state/badgelink-device-token.json"

#: THE PRE-DECODE BOUND. The record is ``{"schema": 1, "token": "<64 hex>"}`` --
#: about 90 bytes -- so 1 KB is ten times the only file that belongs here. Past
#: the cap the read answers ``None``, which is the same answer a corrupt record
#: gets: stay on the floor.
MAX_BYTES = 1024

#: The server mints ``encode(gen_random_bytes(32), 'hex')``, so the token is
#: exactly 64 lowercase hex characters. Validated on the way IN as well as out --
#: a value this module cannot recognise is not one it will send as a credential.
TOKEN_CHARS = "0123456789abcdef"
TOKEN_LENGTH = 64

#: PKCE S256 only. The verifier is 32 random bytes rendered as 64 lowercase hex,
#: which is inside RFC 7636's 43-128 character range and uses only unreserved
#: characters, so it needs no escaping on the wire.
VERIFIER_LENGTH = 64


def _hexlify(raw):
    """``bytes`` -> lowercase hex, without assuming ``bytes.hex`` exists.

    Frozen Badgeware exposes ``digest()`` on ``hashlib.sha256`` and NOT
    ``hexdigest()``, and a device once printed ``AttributeError`` while
    ``mpremote`` returned 0 -- so an attribute this module has not verified on
    hardware gets a fallback rather than a guess.
    """

    hexer = getattr(raw, "hex", None)
    if callable(hexer):
        return hexer()
    import binascii

    return binascii.hexlify(raw).decode()


def new_verifier(entropy=None):
    """A fresh PKCE code verifier. **RAM ONLY -- never write this anywhere.**

    Regenerated per claim attempt rather than kept: a verifier is only useful
    between one ``claim_start`` and its ``retrieve``, and one that outlived a
    claim would be a stored secret with no expiry.
    """

    source = entropy or os.urandom
    return _hexlify(source(VERIFIER_LENGTH // 2))


def challenge_for(verifier, sha256=None):
    """The S256 challenge for a verifier: lowercase hex of its SHA-256.

    HEX RATHER THAN BASE64URL, and it is the server's choice not a shortcut: the
    deployed ``claim_start`` validates ``p_code_challenge ~ '^[0-9a-f]{64}$'``
    and compares against ``encode(digest(verifier,'sha256'),'hex')``. Matching
    that exactly is the whole job. ``digest()`` and never ``hexdigest()`` -- this
    firmware has no ``hexdigest``.
    """

    if not isinstance(verifier, str) or not verifier:
        raise ValueError("a PKCE verifier is required")
    if sha256 is None:
        import hashlib

        sha256 = hashlib.sha256
    return _hexlify(sha256(verifier.encode("utf-8")).digest())


def valid_token(token):
    """Is this the shape the server mints? 64 lowercase hex, exactly."""

    if not isinstance(token, str) or len(token) != TOKEN_LENGTH:
        return False
    for character in token:
        if character not in TOKEN_CHARS:
            return False
    return True


def load(path=DEFAULT_PATH, open_fn=open, remove_fn=None):
    """The stored device token, or ``None``. **Never raises.**

    ``None`` for every unusable shape -- no file, an unreadable one, over the
    cap, unparseable, a wrong schema, a token that is not the minted shape -- and
    the caller's response to all of them is identical: stay on the floor. That
    uniformity is the point. A verified tier whose failure mode is an exception
    would make a claimed badge less reliable than an unclaimed one.

    IT ALSO CLEANS UP A STRANDED ``.tmp``. A crash between the write and the
    rename leaves one behind, and the next claim's write would happily overwrite
    it -- but a file that is never removed is a file somebody eventually reads,
    and this one contains a bearer credential.
    """

    temporary = path + ".tmp"
    remove = remove_fn if remove_fn is not None else getattr(os, "remove", None)
    if remove is not None:
        try:
            remove(temporary)
        except Exception:
            # Absent (the normal case) or unremovable. Neither is this
            # function's problem and neither may stop it answering.
            pass
    try:
        with open_fn(path, "r") as source:
            raw = source.read(MAX_BYTES + 1)
    except Exception:
        return None
    # BOUNDED BEFORE THE DECODE. The one extra byte proves the file was over the
    # cap without allocating the rest of it.
    if len(raw) > MAX_BYTES:
        return None
    try:
        record = json.loads(raw)
    except Exception:
        return None
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return None
    token = record.get("token")
    return token if valid_token(token) else None


def save(token, path=DEFAULT_PATH, open_fn=open, sync_fn=None, rename_fn=None):
    """Persist the token atomically. Raises on a filesystem failure.

    RAISES, UNLIKE :func:`load`, and the asymmetry is deliberate. A read that
    fails has an honest fallback -- the floor -- but a write that fails silently
    would leave the badge believing it is claimed while nothing on flash says so,
    and the next boot would drop to the floor with no record of why. The caller
    turns the raise into a retry or a failed claim; the server's retrieve is
    idempotent within its grace window, so retrying is safe.

    THE RENAME IS THE COMMIT. temp -> flush -> sync -> rename, so a power cut
    cannot produce a half-written record that reads as whole -- which for a
    64-character token is otherwise entirely possible.
    """

    if not valid_token(token):
        raise ValueError("device token must be 64 lowercase hex characters")
    record = {"schema": SCHEMA, "token": token}
    temporary = path + ".tmp"
    with open_fn(temporary, "w") as output:
        output.write(json.dumps(record))
        flush = getattr(output, "flush", None)
        if flush is not None:
            flush()
    sync = sync_fn if sync_fn is not None else getattr(os, "sync", None)
    if sync is not None:
        sync()
    (rename_fn or os.rename)(temporary, path)
    return True


def clear(path=DEFAULT_PATH, remove_fn=None):
    """Forget the token. Total, like :func:`load`.

    The badge-side half of revocation and of a re-claim. It does NOT need to
    succeed to be correct: a token the server has revoked is inert whether or not
    this file still holds it, so a read-only filesystem cannot strand the badge
    in a claimed state that means anything.
    """

    remove = remove_fn if remove_fn is not None else getattr(os, "remove", None)
    if remove is None:
        return False
    for target in (path, path + ".tmp"):
        try:
            remove(target)
        except Exception:
            pass
    return True
