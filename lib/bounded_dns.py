"""An A-record lookup a rendered frame can afford, because it is a UDP socket.

THE FREEZE THIS EXISTS TO END, measured on the dev badge 2026-08-26/27 while
the owner walked out of range: `socket.getaddrinfo` blocks **13,121-14,017 ms**
when packets cannot reach the resolver, inside a rendered frame, repeatedly.
MicroPython's asyncio cannot interrupt it -- lwIP's `poll_sockets()` is a
C-level spin that never re-enters the Python VM -- so the wearer sees an 8-10
second dead badge each time.

**IT CANNOT BE FIXED UPSTREAM OR BY CONFIGURATION, and each of these was
checked rather than assumed:**

* micropython#18797 is CLOSED as completed. Its fix (PR #18805) keeps the lwIP
  timer running so the DNS timeout can COMPLETE; it adds no timeout to
  `getaddrinfo`. **The 13-14 s IS the fixed behaviour** -- the old one hung
  forever -- and Badgeware builds from `bw-1.28.0-3`, which contains it.
* PR #18801 (fail fast when no netif has LINK_UP) is OPEN and was deliberately
  rejected as a default: maintainers want a flapping link to still get retries.
* `socket.setdefaulttimeout` does not exist on this port (verified, `hasattr`
  is False).
* `_thread` is compiled out (`MICROPY_PY_THREAD (0)`), so core 1 is
  unreachable from Python and there is no thread to park the block on.

**AND THE OBVIOUS GUARD IS RULED OUT BY THE FIELD, which is the finding that
forced a real DNS client rather than a three-line check.** The owner walked
well out of range and `wlan.isconnected()` NEVER went False; it reported True
the whole time. "Skip the resolve when there is no route" cannot be written,
because the badge does not know. The freeze happens in the GREY ZONE:
associated, believing it is online, packets not flowing.

WHAT WORKS, PROVEN ON THE SAME HARDWARE: socket operations DO honour
`settimeout`; only `getaddrinfo` ignores it. So the query is built here and
sent over a UDP socket we own. Measured, dev badge, same session:

    real resolver, 1000 ms budget       39 ms   answered (76.76.21.21, correct)
    SILENT resolver, 1000 ms budget   1001 ms   ETIMEDOUT
    SILENT resolver,  300 ms budget    301 ms   ETIMEDOUT
    no route at all                   0-1 ms    EHOSTUNREACH
    getaddrinfo, no route            13,121-14,017 ms

The timeout holds to the millisecond. The silent case was simulated against
192.0.2.1 (RFC 5737 TEST-NET-1) -- routable-looking and guaranteed silent,
which is the closest analogue to the grey zone that is available on a bench.

**WIRED INTO THE SHIPPING NETWORK PATH.** `network_runtime.DeviceBackend`
constructs `BoundedResolver` over its WLAN handle and gives its `getaddrinfo`
method to the shared address cache. `install_system_lib.SHARED_MODULES` installs
this module with that runtime. There is deliberately no fallback to
`socket.getaddrinfo`: a bounded `OSError` enters the ordinary unreachable and
backoff path, while a fallback would restore the 13-14 second freeze precisely
when packets stop flowing.

DEPENDENCIES ARE `socket`, `struct`, `time` and `os`, and the last two are not
decoration: `time` is what makes the TOTAL budget a bound rather than a
per-recv hope (see :func:`query_a`), and `os.urandom` is the only entropy the
transaction id has. Everything else is arithmetic on bytes so the module runs
unchanged under CPython in `badgelink/tests/test_bounded_dns.py`.
"""

import os
import socket
import struct
import time


#: The DHCP-provided resolver is asked on 53/udp like any other stub resolver.
DNS_PORT = 53

#: RFC 1035's UDP answer ceiling. A larger buffer would only ever hold a
#: response this module refuses to parse anyway (see the TC handling in
#: :func:`parse_response`), and the badge pays for every allocation in a frame.
MAX_UDP_PAYLOAD = 512

#: **1000 ms, AND THE NUMBER IS THE MEASUREMENT, not a round figure.** Against
#: `getaddrinfo`'s 13,121-14,017 ms this is a 13-14x cut: the wearer's 8-10 s
#: dead badge becomes a sub-second hitch, and the freeze stops being the thing
#: they notice.
#:
#: WHY NOT TIGHTER. 300 ms was measured working (301 ms actual), so the floor is
#: not a mechanism limit -- it is a HAPPY-PATH limit. An answered lookup on this
#: badge costs 39 ms here and 30-88 ms in the NS-2 device runs, so a 300 ms
#: total split across two attempts leaves 150 ms per try: under 2x the worst
#: measured healthy answer. A venue resolver behind a busy AP or a split-horizon
#: forwarder would blow that, and the failure would be INVISIBLE -- a working
#: network reported as unresolvable. That is the wrong direction to be wrong in;
#: 500 ms per attempt is ~6x the worst measured healthy answer.
#:
#: WHY NOT LOOSER. 1000 ms is already ~37 dropped frames at the device's
#: measured 27 ms mean. Every further second buys nothing on a link that is
#: silent and costs the wearer directly.
DEFAULT_TIMEOUT_MS = 1000

#: **TWO ATTEMPTS INSIDE THE BUDGET, NOT ONE LONG WAIT, and the grey zone is the
#: argument.** The field case is not a silent resolver, it is a LOSSY one:
#: associated, `isconnected()` True, packets intermittently not flowing. A
#: single 1000 ms wait is defeated by one dropped datagram; two 500 ms
#: transmissions recover from it for the same worst case, and UDP retransmission
#: is what a stub resolver is supposed to do -- there is no lower layer that
#: will do it for us.
#:
#: THE RETRY IS FREE ON THE HAPPY PATH. The first attempt answers in 39 ms and
#: returns, so a healthy badge never sends the second datagram.
DEFAULT_ATTEMPTS = 2

_HEADER_LEN = 12
_HEADER = ">HHHHHH"

#: RD only. We are talking to a recursive resolver (DHCP option 6 or the
#: gateway forwarder), never to an authoritative server, so recursion desired
#: is the whole flag set a stub needs.
_FLAGS_RD = 0x0100
_FLAG_QR = 0x8000
_FLAG_TC = 0x0200
_RCODE_MASK = 0x000F

_TYPE_A = 1
_CLASS_IN = 1

#: A record's RDATA is exactly four bytes. A type-1 record claiming any other
#: length is not an IPv4 address, whatever it says it is.
_A_RDLENGTH = 4

#: RFC 1035 hard limits. Both are enforced when BUILDING, because a name that
#: violates either cannot be encoded at all: a label over 63 sets the two top
#: bits of its own length byte, which is the compression-pointer marker, so an
#: over-long label would be read back by every resolver on earth as a pointer.
_MAX_LABEL = 63
_MAX_NAME = 255

_UNSPECIFIED = "0.0.0.0"

#: "This answer section cannot be read", which is NOT the same answer as "this
#: name has no address" and must not collapse into it. A broken datagram is
#: ignored so the query keeps waiting inside its budget; a clean answer section
#: with no A record is a definitive negative and raises. Both look like `None`
#: from `_find_a_record` without a sentinel to tell them apart, and conflating
#: them would let one corrupt packet end a lookup that a retransmit would have
#: answered.
_MALFORMED = object()


def _ticks_ms():
    function = getattr(time, "ticks_ms", None)
    return function() if function is not None else int(time.monotonic() * 1000)


def _ticks_diff(left, right):
    function = getattr(time, "ticks_diff", None)
    return function(left, right) if function is not None else left - right


def _ascii_lower(raw):
    """Lowercase A-Z in a byte string, without `bytes.lower()`.

    DNS names are case-insensitive on the wire, so a resolver is free to echo
    the question in a different case and a case-sensitive comparison would
    reject its perfectly good answer. `bytes.lower()` is not guaranteed on every
    MicroPython build and this comparison must not be the thing that breaks on
    the badge, so the four lines are written out.
    """

    out = bytearray(raw)
    for index in range(len(out)):
        value = out[index]
        if 65 <= value <= 90:
            out[index] = value + 32
    return bytes(out)


def _transaction_id(entropy=None, ticks_ms=None):
    """Sixteen bits of query identity, from the best source the port offers.

    THE PROTOTYPE USED A CONSTANT (0x1234) and that is the one thing from it
    that must not ship. The transaction id is the only anti-off-path entropy
    DNS gives a stub, and with a constant it also fails a much more ordinary
    case: a late reply to the PREVIOUS query is indistinguishable from the
    answer to this one, which on a lossy link is not hypothetical.

    The ticks fallback is hashed rather than truncated because consecutive
    queries are milliseconds apart, so the raw low bits of two `ticks_ms()`
    readings are nearly identical; the multiplier is Knuth's 32-bit constant and
    it exists only to spread them.
    """

    source = entropy if entropy is not None else getattr(os, "urandom", None)
    if source is not None:
        try:
            raw = source(2)
            if raw is not None and len(raw) >= 2:
                return ((raw[0] << 8) | raw[1]) & 0xFFFF
        except Exception:
            pass
    clock = ticks_ms or _ticks_ms
    return (clock() * 2654435761) & 0xFFFF


def build_question(host):
    """The QNAME + QTYPE + QCLASS bytes for an IN A question.

    Returned separately from the header because the ANSWER is verified against
    these exact bytes (:func:`parse_response`), which is a stronger off-path
    check than the 16-bit id alone and costs one comparison.

    Raises ``ValueError``; callers that must match the ``getaddrinfo`` contract
    translate it (see :func:`query_a`).
    """

    if not isinstance(host, str) or not host:
        raise ValueError("host must be a non-empty string")
    # One trailing dot is a legal FQDN spelling and must not become an empty
    # final label, which would encode as a second terminator.
    name = host[:-1] if host.endswith(".") else host
    if not name:
        raise ValueError("host must not be the root")
    out = bytearray()
    for label in name.split("."):
        if not label:
            raise ValueError("host has an empty label")
        try:
            raw = label.encode("ascii")
        except Exception:
            # An internationalised name needs IDNA/punycode, which this badge
            # has no encoder for. Refusing is honest; sending the UTF-8 bytes
            # would produce a question no resolver answers.
            raise ValueError("host is not ASCII")
        if len(raw) > _MAX_LABEL:
            raise ValueError("host label is longer than 63 bytes")
        out.append(len(raw))
        out += raw
    out.append(0)
    if len(out) > _MAX_NAME:
        raise ValueError("host is longer than 255 bytes encoded")
    out += struct.pack(">HH", _TYPE_A, _CLASS_IN)
    return bytes(out)


def build_query(host, transaction_id):
    """The complete question datagram. Pinned byte-exact by the test suite.

    THE WIRE FORMAT IS THE THING A FUTURE EDIT MUST NOT CHANGE SILENTLY, which
    is why `test_bounded_dns` asserts these bytes literally rather than
    round-tripping them through this module's own parser: a parser and a builder
    that agree with each other can still both be wrong.
    """

    ident = int(transaction_id) & 0xFFFF
    header = struct.pack(_HEADER, ident, _FLAGS_RD, 1, 0, 0, 0)
    return header + build_question(host)


def _skip_name(payload, offset):
    """Offset just past the name at ``offset``, or ``None`` if it does not fit.

    THE POINTER IS NOT FOLLOWED, deliberately. Every name this parser meets is
    one it SKIPS -- the question is verified by byte comparison and the answer's
    owner name is irrelevant once the type and class match -- so following a
    compression pointer buys nothing and is exactly where a crafted packet buys
    a loop or a quadratic walk. A pointer ends the name; that is all we need.
    """

    length = len(payload)
    consumed = 0
    while True:
        if offset >= length:
            return None
        marker = payload[offset]
        if marker == 0:
            return offset + 1
        if marker >= 0xC0:
            if offset + 1 >= length:
                return None
            return offset + 2
        if marker > _MAX_LABEL:
            # 0x40 and 0x80 are reserved label types (RFC 6891 retired the one
            # that used them). Nothing on a badge network emits them, and
            # guessing a length from a reserved marker walks off the packet.
            return None
        offset += 1 + marker
        consumed += 1 + marker
        if consumed > _MAX_NAME:
            return None


def _skip_questions(payload, count):
    offset = _HEADER_LEN
    for _ in range(count):
        offset = _skip_name(payload, offset)
        if offset is None or offset + 4 > len(payload):
            return None
        offset += 4
    return offset


def _question_echoed(payload, question):
    end = _HEADER_LEN + len(question)
    if end > len(payload):
        return False
    return _ascii_lower(payload[_HEADER_LEN:end]) == _ascii_lower(question)


def _find_a_record(payload, offset, ancount):
    """An address, ``None`` for a clean walk with no A record, or `_MALFORMED`.

    THE CNAME WALK IS THE REASON THIS IS A LOOP. `supabase.co` and every hosted
    project name answer through a CNAME chain, so the A record is routinely NOT
    the first record: a parser that reads answer[0] and trusts it returns four
    bytes of a hostname. Records that are not IN A are stepped over by their own
    RDLENGTH, which is also the only bound on the walk.
    """

    length = len(payload)
    for _ in range(ancount):
        offset = _skip_name(payload, offset)
        if offset is None or offset + 10 > length:
            return _MALFORMED
        rtype, rclass, _ttl, rdlength = struct.unpack_from(">HHIH", payload,
                                                           offset)
        offset += 10
        if offset + rdlength > length:
            # A record that claims more RDATA than the datagram holds is the
            # index-out-of-range case; stop rather than clamp, because a
            # truncated record's contents cannot be trusted either.
            return _MALFORMED
        if (rtype == _TYPE_A and rclass == _CLASS_IN
                and rdlength == _A_RDLENGTH):
            raw = payload[offset:offset + _A_RDLENGTH]
            return "%d.%d.%d.%d" % (raw[0], raw[1], raw[2], raw[3])
        offset += rdlength
    return None


def parse_response(payload, transaction_id, question=None):
    """An address, ``None`` for "ignore this packet", or ``OSError``.

    THE THREE-WAY RETURN IS WHAT LETS THE READ LOOP STAY BOUNDED AND STILL BE
    CORRECT. ``None`` means the datagram is not an answer to our question --
    off-path, stale, malformed, truncated -- so :func:`query_a` keeps waiting
    inside the budget it already has. ``OSError`` means the resolver ANSWERED
    and the answer is a negative one (NXDOMAIN, SERVFAIL, REFUSED, or NODATA),
    which is definitive: retransmitting spends the wearer's budget to be told
    the same thing, and `getaddrinfo` raises for exactly these cases too.

    NOTHING HERE MAY RAISE `IndexError`. Every read is bounds-checked against
    ``len(payload)`` first, because the packets this sees come off the network
    and the caller is a rendered frame.
    """

    if payload is None or len(payload) < _HEADER_LEN:
        return None
    ident, flags, qdcount, ancount, _ns, _ar = struct.unpack_from(
        _HEADER, payload, 0)
    if ident != (int(transaction_id) & 0xFFFF):
        # AN OFF-PATH ANSWER IS REJECTED, NOT TRUSTED. Dropping it rather than
        # failing the query is deliberate: a spoofer who can flood us must not
        # also be able to end our wait early.
        return None
    if not flags & _FLAG_QR:
        # Our own query, reflected. Some captive portals and every loopback
        # misconfiguration produce one, and it parses as a header with zero
        # answers, so it must be named rather than fall through.
        return None
    if qdcount != 1:
        # We asked exactly one question. Any other count means the answer
        # section does not begin where we are about to look.
        return None
    if question is not None:
        if not _question_echoed(payload, question):
            return None
        offset = _HEADER_LEN + len(question)
    else:
        offset = _skip_questions(payload, qdcount)
        if offset is None:
            return None
    rcode = flags & _RCODE_MASK
    if rcode != 0:
        raise OSError("dns rcode %d" % rcode)
    address = _find_a_record(payload, offset, ancount)
    if address is _MALFORMED:
        return None
    if address is not None:
        return address
    if flags & _FLAG_TC:
        # A truncated datagram is MISSING data, not an assertion that no
        # address exists, so it must not become the definitive negative below.
        return None
    raise OSError("dns answer carried no A record")


def _from_server(source, server):
    """Whether a datagram's source is the server we asked.

    CHECKED ONLY WHEN THE SHAPE IS RECOGNISABLE. MicroPython's `recvfrom`
    address form is port-specific and has not been read off this board, so an
    unfamiliar shape must never be the reason a healthy answer is dropped. The
    transaction id and the echoed question are the checks that always run; this
    one is a cheap extra when the port hands us a `(host, port)` tuple.
    """

    if isinstance(source, (tuple, list)) and source:
        value = source[0]
        if isinstance(value, str) and value:
            return value == server
    return True


def query_a(host, server, timeout_ms=DEFAULT_TIMEOUT_MS,
            attempts=DEFAULT_ATTEMPTS, socket_module=None,
            transaction_id=None, ticks_ms=None, ticks_diff=None,
            entropy=None):
    """Resolve ``host`` to one IPv4 address within ``timeout_ms``, or raise.

    THE BUDGET IS MEASURED FROM ONE START AND IS THE OUTER BOUND ON EVERYTHING,
    which is why this needs a clock at all. A per-`recvfrom` timeout alone is
    not a bound: an off-path flood would hand us a fresh packet just before each
    deadline and restart the wait forever. Every `settimeout` below is
    `remaining`, so the wall time of this call cannot exceed ``timeout_ms`` no
    matter what arrives.

    ONE SOCKET SERVES EVERY ATTEMPT, AND THE TRANSACTION ID IS REUSED ACROSS
    THEM. Both halves are needed for the same reason: on a lossy link the first
    datagram's answer often arrives DURING the second attempt, and it is a valid
    answer. A fresh socket would have a fresh source port and the stack would
    discard it; a fresh id would make this parser discard it.

    A `sendto` failure is raised immediately and is never retransmitted: it is
    the local stack refusing (EHOSTUNREACH measured at 0-1 ms with no route),
    which is a definitive, instant answer and precisely the case `getaddrinfo`
    turns into 13-14 s.

    Raises ``OSError`` on every failure path, because that is what
    ``getaddrinfo`` raises and what `SessionAddresses.resolve`,
    `DeviceBackend._build_loop` and `device_link._connect_worker` already
    handle. A refused hostname is translated for the same reason -- a caller
    should not have to catch two exception types to ask one question.
    """

    if not server:
        raise OSError("dns: no resolver address")
    module = socket_module if socket_module is not None else socket
    clock = ticks_ms or _ticks_ms
    difference = ticks_diff or _ticks_diff
    budget = int(timeout_ms)
    if budget <= 0:
        raise OSError("dns: timeout_ms must be positive")
    tries = int(attempts)
    if tries < 1:
        tries = 1
    try:
        question = build_question(host)
    except ValueError as exc:
        raise OSError("dns: %s" % exc)
    ident = (_transaction_id(entropy, clock) if transaction_id is None
             else int(transaction_id)) & 0xFFFF
    packet = struct.pack(_HEADER, ident, _FLAGS_RD, 1, 0, 0, 0) + question
    # A budget smaller than the attempt count floors to a zero-length slice,
    # which would put every attempt but the last on the wire with NO WAIT
    # BEHIND IT -- datagrams sent only to be abandoned on the same tick. The
    # floor of one keeps each send paired with a recv.
    #
    # It is not what protects `settimeout` from a zero: `wait <= 0` below is,
    # and it has to be, because `wait` is the remaining budget rather than the
    # slice. An earlier version of this comment claimed otherwise and a
    # mutation run caught it -- removing the floor changed the datagram count
    # and never produced a non-blocking socket.
    slice_ms = max(1, budget // tries)
    start = clock()
    sock = module.socket(module.AF_INET, module.SOCK_DGRAM)
    try:
        for attempt in range(tries):
            # The LAST attempt owns whatever is left, so a budget that does not
            # divide evenly is spent rather than rounded away.
            attempt_end = (budget if attempt == tries - 1
                           else slice_ms * (attempt + 1))
            wait = attempt_end - difference(clock(), start)
            if wait <= 0:
                break
            # ARMED BEFORE THE SEND, which is the order the device numbers were
            # taken in: the hardware prototype called `settimeout` and then
            # `sendto`, and the 0-1 ms EHOSTUNREACH figure describes that shape.
            # A UDP `sendto` is not supposed to block, but "not supposed to" is
            # not a measurement and this is not the place to find out.
            sock.settimeout(wait / 1000)
            sock.sendto(packet, (server, DNS_PORT))
            while True:
                try:
                    payload, source = sock.recvfrom(MAX_UDP_PAYLOAD)
                except OSError:
                    break
                if _from_server(source, server):
                    address = parse_response(payload, ident, question)
                    if address is not None:
                        return address
                # EVERY rejection re-arms with what is LEFT, never with a fresh
                # slice, and both rejection reasons go through this one line on
                # purpose. An earlier version skipped it on the wrong-SOURCE
                # branch, which left the socket carrying a deadline armed
                # before the flood started: a stream of wrong-source datagrams
                # would then have run the call past its own budget, which is
                # the single property the module exists to guarantee.
                wait = attempt_end - difference(clock(), start)
                if wait <= 0:
                    break
                sock.settimeout(wait / 1000)
    finally:
        # The badge's lwIP socket pool is small and a leaked UDP socket is never
        # reclaimed inside a boot, so this close covers the answered path, the
        # timeout path and the `sendto` refusal alike.
        sock.close()
    raise OSError("dns: no answer from %s within %d ms" % (server, budget))



#: A step that has not finished yet. Deliberately the same sentinel name the poll
#: transport uses for the same idea, so a reader meets one vocabulary.
PENDING = "pending"


class SteppedQuery:
    """One A-record lookup advanced ONE non-blocking receive per rendered frame.

    WHY THIS EXISTS, AND IT IS THE WHOLE POINT OF THE MODULE'S SECOND HALF.
    `query_a` bounds the resolver at :data:`DEFAULT_TIMEOUT_MS`, which stopped
    `getaddrinfo`'s measured 13,121-14,017 ms freeze. But a bound is not the same
    as not blocking: 1,000 ms is still ~37 dropped frames at the device's
    measured 27 ms mean, and on this hardware a blocking call IS a stopped
    screen -- `_thread` is compiled out and asyncio cannot preempt a C call.

    THE REASON THIS IS OURS TO FIX RATHER THAN THE FIRMWARE'S: we build the
    query, we own the socket, we choose the transaction id and we hold the
    budget clock. Nothing here needs to block. `setblocking(False)` plus one
    `recvfrom` attempt per frame turns the same 1,000 ms budget into ~0 ms of
    frame time spread over at most ~37 frames.

    EVERY HARDENING PROPERTY OF THE BLOCKING PATH IS PRESERVED because the same
    two helpers do the work: :func:`build_query` writes the wire bytes and
    :func:`parse_response` validates them. That parser survived 18 hostile
    packets -- compression-pointer loops, truncation, overstated counts,
    off-path answers, mismatched ids -- with zero hangs and zero crashes, so it
    is reused rather than re-derived. The transaction id is still matched and the
    source address is still checked.

    ONE SOCKET AND ONE TRANSACTION ID ACROSS RETRIES, for the reason `query_a`
    states: on a lossy link the first datagram's answer often arrives during the
    second attempt and it is a VALID answer. A fresh port or a fresh id would
    throw it away.

    USAGE, one call per frame::

        q = SteppedQuery(host, server)
        # then, once per rendered frame:
        out = q.step()
        if out is PENDING:
            ...              # draw the frame; nothing was blocked
        else:
            address = out    # or an OSError was raised
    """

    def __init__(self, host, server, timeout_ms=DEFAULT_TIMEOUT_MS,
                 attempts=DEFAULT_ATTEMPTS, socket_module=None,
                 transaction_id=None, ticks_ms=None, ticks_diff=None,
                 entropy=None):
        self._host = host
        self._server = server
        self._timeout_ms = int(timeout_ms)
        self._attempts = max(1, int(attempts))
        self._socket = socket_module if socket_module is not None else socket
        self._ticks_ms = ticks_ms or _ticks_ms
        self._ticks_diff = ticks_diff or _ticks_diff
        self._transaction_id = (
            transaction_id if transaction_id is not None
            else _transaction_id(entropy))
        self._question = build_question(host)
        self._sock = None
        self._started = None
        self._sent = 0
        self._last_send = None
        self._done = False
        #: Frames spent, exported for tests and for a caller that wants to say
        #: something honest on screen while it waits.
        self.steps = 0

    # -- lifecycle ---------------------------------------------------------

    def _open(self):
        sock = self._socket.socket(self._socket.AF_INET, self._socket.SOCK_DGRAM)
        sock.setblocking(False)
        self._sock = sock
        self._started = self._ticks_ms()

    def close(self):
        """Idempotent. Safe to call from a caller's own teardown path."""
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except Exception:  # noqa: BLE001 - a closed socket is the goal
                pass

    def _elapsed(self):
        return self._ticks_diff(self._ticks_ms(), self._started)

    def _fail(self, message):
        self.close()
        self._done = True
        raise OSError(message)

    # -- the one call a frame makes ----------------------------------------

    def step(self):
        """Advance the lookup by at most one send and one receive attempt.

        Returns :data:`PENDING` while more frames are needed, or the address
        string. Raises ``OSError`` on failure, matching what ``getaddrinfo``
        raises and what every existing caller already handles.
        """
        if self._done:
            raise OSError("dns: step() after completion")
        self.steps += 1
        if self._sock is None:
            self._open()

        elapsed = self._elapsed()
        if elapsed >= self._timeout_ms:
            self._fail("dns: no answer from %s within %d ms" % (
                self._server, self._timeout_ms))

        # RETRANSMIT ON A SCHEDULE, NOT EVERY FRAME. One datagram per attempt
        # window; spraying one per frame would be a flood the moment a resolver
        # went quiet, and 800 badges doing that at a venue is a herd problem.
        window = self._timeout_ms // self._attempts or self._timeout_ms
        if self._sent == 0 or (
                self._sent < self._attempts
                and self._ticks_diff(self._ticks_ms(), self._last_send) >= window):
            try:
                self._sock.sendto(
                    build_query(self._host, self._transaction_id),
                    (self._server, DNS_PORT))
            except OSError as exc:
                # The local stack refusing is a definitive, instant answer -- it
                # is EHOSTUNREACH at 0-1 ms with no route, and it is exactly the
                # case getaddrinfo turns into 13-14 s. Never retransmit it.
                self._fail("dns: send to %s failed: %s" % (self._server, exc))
            self._sent += 1
            self._last_send = self._ticks_ms()

        try:
            payload, source = self._sock.recvfrom(MAX_UDP_PAYLOAD)
        except OSError:
            # EAGAIN on a non-blocking socket: nothing has arrived. This is the
            # ordinary case and it is what makes the frame free.
            return PENDING

        if not _from_server(source, self._server):
            return PENDING          # off-path datagram; keep waiting

        address = parse_response(payload, self._transaction_id, self._question)
        if address is None:
            return PENDING          # malformed or not ours; the budget still bounds us
        self.close()
        self._done = True
        return address

def _is_ipv4_literal(value):
    """Strict dotted quad only.

    The short forms `inet_aton` accepts (`10.1`, `0x0a000001`) are refused
    because the only producer of these strings is a badge provisioned with
    `BADGELINK_IP`, which writes a dotted quad; supporting the rest would mean
    re-implementing `inet_aton` for no caller.
    """

    if not isinstance(value, str):
        return False
    parts = value.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part or len(part) > 3:
            return False
        for character in part:
            if character < "0" or character > "9":
                return False
        if int(part) > 255:
            return False
    return True


def resolver_address(wlan):
    """The NETWORK's own resolver: DHCP option 6, else the default gateway.

    **NEVER A PUBLIC RESOLVER, and not as a fallback either.** A venue that
    answers its own names out of a split-horizon zone is a real deployment
    shape, and 1.1.1.1 would resolve those names to nothing -- so a hardcoded
    public server converts a working badge into a broken one at exactly the
    event this module exists for. It would also not help the case that motivated
    the module: in the grey zone the DHCP resolver is unreachable because
    PACKETS ARE NOT FLOWING, and a public resolver sits on the far side of the
    same dead link.

    THE GATEWAY IS THE FALLBACK because an AP that hands out no option 6 is
    almost always its own forwarder, and it is still the network's server, which
    is the property that matters. Observed on the dev badge: `ifconfig()`
    returned a four-entry ``(address, netmask, gateway, resolver)`` whose DHCP
    resolver at index 3 was the ISP's own public server and NOT the gateway at
    index 2 -- which is why index 3 is tried first and index 2 only after it.

    Returns ``None`` when neither is usable, which is a real state (a static
    configuration with no DNS, or a port whose `ifconfig` is shorter than four
    entries). What to do about it is the CALLER's decision and deliberately not
    taken here: falling back to `socket.getaddrinfo` would reinstate the 13-14 s
    freeze, and that trade belongs to the lane that owns the frame.
    """

    try:
        config = wlan.ifconfig()
    except Exception:
        # A radio that is down or a stub without `ifconfig` is "no resolver",
        # not a crash in a rendered frame.
        return None
    if not isinstance(config, (tuple, list)):
        return None
    for index in (3, 2):
        if len(config) <= index:
            continue
        candidate = config[index]
        if _is_ipv4_literal(candidate) and candidate != _UNSPECIFIED:
            return candidate
    return None


class BoundedResolver:
    """`socket.getaddrinfo`'s job, with a deadline, over a socket we own.

    :meth:`getaddrinfo` is signature-compatible with `socket.getaddrinfo` as
    this repository calls it, so it can be injected wherever that function is
    today -- `SessionAddresses` takes the callable as its first constructor
    argument and asks only that it be callable.

    THE COUNTERS EXIST FOR THE SAME REASON `SessionAddresses.snapshot` DOES: the
    thing a badge in a venue cannot tell you afterwards is how often it paid,
    and a credential-free trio of integers is the cheapest way to be able to
    answer that from a serial log.
    """

    def __init__(self, wlan, socket_module=None,
                 timeout_ms=DEFAULT_TIMEOUT_MS, attempts=DEFAULT_ATTEMPTS,
                 ticks_ms=None, ticks_diff=None, entropy=None):
        self._wlan = wlan
        self._socket = socket_module if socket_module is not None else socket
        self._timeout_ms = int(timeout_ms)
        self._attempts = int(attempts)
        self._ticks_ms = ticks_ms
        self._ticks_diff = ticks_diff
        self._entropy = entropy
        self.queries = 0
        self.answers = 0
        self.failures = 0

    @property
    def timeout_ms(self):
        return self._timeout_ms

    def server(self):
        return resolver_address(self._wlan)

    def resolve(self, host):
        """One address string for ``host``. Raises ``OSError``."""

        if _is_ipv4_literal(host):
            # A badge provisioned with `BADGELINK_IP` reaches every resolve
            # path with a dotted quad in hand (`credentials.connect_host()` is
            # `ip or host`). Asking a resolver to look up a LAN address
            # literal is a guaranteed NXDOMAIN and a wasted budget in a
            # rendered frame.
            return host
        server = self.server()
        if not server:
            raise OSError("dns: no resolver address")
        self.queries += 1
        try:
            address = query_a(
                host,
                server,
                timeout_ms=self._timeout_ms,
                attempts=self._attempts,
                socket_module=self._socket,
                ticks_ms=self._ticks_ms,
                ticks_diff=self._ticks_diff,
                entropy=self._entropy,
            )
        except Exception:
            self.failures += 1
            raise
        self.answers += 1
        return address

    def getaddrinfo(self, host, port, family=0, kind=0):
        """One addrinfo row, shaped like the one the callers already unpack.

        `(family, type, proto, canonname, sockaddr)` with an empty canonname and
        a `(address, port)` sockaddr, which is the shape pinned by
        `badgelink/tests/test_network_runtime.py:1616` and read by
        `SessionAddresses._address_from_info` (`info[-1][0]`, checked to be a
        non-empty string) and by every probe that assigns `worker._addr_info`.

        A LIST OF ONE, because `SessionAddresses.resolve` takes `[0]` and
        nothing in this repository looks at a second row. IPv6 is not returned
        at all: the fleet's transport is IPv4 and an AAAA question would be a
        second round trip inside the same frame budget.
        """

        address = self.resolve(host)
        stream = getattr(self._socket, "SOCK_STREAM", 1)
        inet = getattr(self._socket, "AF_INET", 2)
        return [(inet, kind or stream, 0, "", (address, int(port)))]

    def snapshot(self):
        return {"queries": self.queries, "answers": self.answers,
                "failures": self.failures, "timeout_ms": self._timeout_ms,
                "attempts": self._attempts}
