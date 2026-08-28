"""Load and sanity-check the badge's BadgeLink credentials from ``/secrets.py``.

The owner provisions ``/secrets.py`` (OWNER-DECISIONS #7 / the identity model
doc): this module NEVER embeds a token, key, host or IP — it only reads the
values the provisioning step wrote and validates their shape. A malformed or
missing credential fails closed to offline; BadgeLink degrading never takes the
badge down.

⚠ **``sub`` IS NOT "THIS BADGE" ANY MORE, AND THIS FILE IS WHY THE MISTAKE WAS
EASY TO MAKE.** It said "provisions ``/secrets.py`` **per badge**" and
"``sub=<16-hex badge id>``", and it is the definition site every other module
derived its per-badge reasoning from — `network_runtime._badge_stagger_ms` cited
this docstring by name while hashing the value to spread a fleet.

Gang-clone provisioning (2026-08-26) ships ONE byte-identical ``/secrets.py`` on
all ~800 badges, so ``sub`` is a single random 16-hex value that identifies the
FLEET. The per-badge identity is ``machine.unique_id().hex()``, read exactly once
per boot by `network_runtime.hardware_uid`, and it is what the fleet doorbell's
ring filter, the ``_self`` RPCs' ``p_badge_id`` and the ``x-badge-id`` fairness
bucket all use. :attr:`Credentials.badge_id` still returns ``sub`` and MUST — the
``badge_state`` heartbeat's RLS is ``badge_id = grants.whoami()``, so that one
write has to keep naming the subject — but it is the fleet's name, not a badge's.
**Nothing here changes for the floor:** the shape this module validates is
identical, which is the whole reason the shared token needed no code change here.

Expected ``/secrets.py`` fields (all strings):

* ``BADGELINK_JWT``   — the ES256 JWT (fleet-shared; see the note above).
  Identity-only claims: ``role=authenticated``, ``aud=authenticated``,
  ``sub=<16-hex subject>``,
  long-lived integer ``exp``, and (by rule) NO ``nbf`` (badge clocks are untrusted;
  ADR-004/005/006 and OWNER-DECISIONS #14). The badge cannot verify the signature — that is the server's
  job — but it CAN decode the payload to refuse an obviously-wrong token before
  spending a handshake.
* ``BADGELINK_APIKEY`` — the project's publishable (anon) key, sent as the
  mandatory ``apikey`` header alongside the Bearer token.
* ``BADGELINK_HOST``  — ``<ref>.supabase.co`` (drives SNI + TLS verification).
* ``BADGELINK_IP``    — optional pre-resolved IPv4 for connect-by-IP (keeps DNS
  off-frame; ``server_hostname`` still drives SNI/verification). Absent = resolve
  once off-frame at session start.
"""

import binascii
import json


BADGE_ROLE = "authenticated"
BADGE_AUD = "authenticated"
_MAX_FIELD_BYTES = 4096
_HOST_MAX = 253


class CredentialError(Exception):
    """A missing or malformed BadgeLink credential. Fail closed to offline."""


def _require_str(source, name, maximum=_MAX_FIELD_BYTES):
    value = getattr(source, name, None)
    if not isinstance(value, str) or not value:
        raise CredentialError("{} must be a non-empty string in /secrets.py".format(name))
    if len(value) > maximum:
        raise CredentialError("{} is implausibly long".format(name))
    return value


def _optional_str(source, name, maximum=_MAX_FIELD_BYTES):
    value = getattr(source, name, None)
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > maximum:
        raise CredentialError("{} must be a short string or absent".format(name))
    return value


def _validate_host(host):
    if len(host) > _HOST_MAX or " " in host or "/" in host or ":" in host:
        raise CredentialError("BADGELINK_HOST must be a bare hostname")
    if "." not in host:
        raise CredentialError("BADGELINK_HOST must be a fully-qualified hostname")
    return host


def _validate_ipv4(ip):
    parts = ip.split(".")
    if len(parts) != 4:
        raise CredentialError("BADGELINK_IP must be dotted-quad IPv4")
    for part in parts:
        if not part.isdigit() or not 0 <= int(part) <= 255:
            raise CredentialError("BADGELINK_IP octet out of range")
    return ip


def _b64url_decode(segment):
    if isinstance(segment, str):
        segment = segment.encode("ascii")
    # JWT uses URL-safe base64 without padding.
    segment = segment.replace(b"-", b"+").replace(b"_", b"/")
    pad = (-len(segment)) % 4
    segment = segment + (b"=" * pad)
    try:
        return binascii.a2b_base64(segment)
    except (ValueError, TypeError):
        raise CredentialError("JWT segment is not valid base64url")


def decode_claims(jwt):
    """Decode (NOT verify) a compact JWT's payload claims into a dict.

    Signature verification is the server's job; this only reads claims so the
    badge can pre-flight expiry/role/aud plausibility before it connects.
    """
    if not isinstance(jwt, str):
        raise CredentialError("JWT must be a string")
    segments = jwt.split(".")
    if len(segments) != 3 or not all(segments):
        raise CredentialError("JWT must have three non-empty segments")
    try:
        payload = json.loads(_b64url_decode(segments[1]).decode("utf-8"))
    except (ValueError, UnicodeError):
        raise CredentialError("JWT payload is not JSON")
    if not isinstance(payload, dict):
        raise CredentialError("JWT payload must be an object")
    return payload


def assert_token_shape(claims):
    """Refuse a token whose identity claims are not the ADR-005/006 badge shape."""
    if claims.get("role") != BADGE_ROLE:
        raise CredentialError("badge token role must be 'authenticated'")
    if claims.get("aud") != BADGE_AUD:
        raise CredentialError("badge token aud must be 'authenticated'")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise CredentialError("badge token sub (badge id) is missing")
    if "nbf" in claims:
        # Untrusted badge clocks + nbf is a known footgun (ADR-004): a badge a
        # little behind UTC would reject its own valid token. The mint must omit
        # it; refuse a token that carries one rather than silently locking out.
        raise CredentialError("badge token must not carry nbf")
    exp = claims.get("exp")
    if not isinstance(exp, int) or isinstance(exp, bool):
        raise CredentialError("badge token exp must be an integer epoch")
    return claims


def assert_event_window(claims, now_epoch, event_end_epoch=None):
    """Pre-flight expiry, plus an optional operator-supplied upper bound.

    ``exp`` is checked against the *server's* clock at request time, so this is a
    best-effort local plausibility gate, not the authority. It catches a badge
    holding a token that has already expired (skip the handshake, stay offline).
    ``event_end_epoch`` remains as a compatibility hook for bounded campaigns;
    production credentials follow decision #14's long-lived posture.
    """
    exp = claims.get("exp")
    if not isinstance(exp, int) or isinstance(exp, bool):
        raise CredentialError("badge token exp must be an integer epoch")
    if isinstance(now_epoch, int) and not isinstance(now_epoch, bool):
        if exp <= now_epoch:
            raise CredentialError("badge token has expired")
    if event_end_epoch is not None and exp > event_end_epoch:
        raise CredentialError("badge token exp is past the event window")
    return True


class Credentials:
    def __init__(self, jwt, apikey, host, ip=None):
        self.jwt = jwt
        self.apikey = apikey
        self.host = host
        self.ip = ip
        self.claims = assert_token_shape(decode_claims(jwt))

    @property
    def badge_id(self):
        """The JWT's ``sub``. **THE FLEET'S SUBJECT, NOT THIS BADGE** — see the
        module note. Kept under this name because the ``badge_state`` heartbeat
        must write it (its RLS is ``badge_id = grants.whoami()``) and because a
        badge still holding a per-badge token resolves it to itself. For "which
        physical badge am I", every consumer reads
        `network_runtime.hardware_uid` instead."""

        return self.claims["sub"]

    def connect_host(self):
        """Where to open the TCP socket: cached IP if present, else the hostname.

        ``server_hostname`` (SNI + verification) is always the hostname, never
        the IP — see :func:`~badgelink.postgrest.rpc_request`.
        """
        return self.ip or self.host


def load(secrets_module):
    """Build a validated :class:`Credentials` from a ``secrets``-like module."""
    jwt = _require_str(secrets_module, "BADGELINK_JWT")
    apikey = _require_str(secrets_module, "BADGELINK_APIKEY")
    host = _validate_host(_require_str(secrets_module, "BADGELINK_HOST", _HOST_MAX))
    ip = _optional_str(secrets_module, "BADGELINK_IP", 15)
    if ip is not None:
        ip = _validate_ipv4(ip)
    return Credentials(jwt=jwt, apikey=apikey, host=host, ip=ip)
