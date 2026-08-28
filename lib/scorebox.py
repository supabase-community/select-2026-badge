"""An offline score spool a game opts into in two lines.

    import scorebox
    scorebox.record("snake", score, duration_ms)

That is the whole API a game needs, and both properties of it are deliberate:
**it never raises** (a game may not crash because a filesystem was full) and
**it never blocks** (the append is one line and the network is somebody else's
problem). ``network_runtime`` drains the spool through the transport's errand
channel whenever a socket happens to exist.

THE MINIMAL ANTI-CHEAT RULING BINDS EVERY LINE HERE, quoted from Card FT-S:
**the badge sends score / duration / idempotency-key ONLY; ALL judgment is SQL,
hot-patchable; per-game floors are measured by playground bots later;
flag-don't-block; human prize check.** So there is no plausibility test, no floor,
no rate limit on scoring and no "is this even possible" check in this module, and
adding one later would be moving judgment client-side. What IS here is delivery:
a bounded buffer, an idempotency key and a retire-once rule.

THERE IS NO ``duration`` COLUMN, and that is the one shape surprise. ``scores``
is ``(badge_id, game, score, idempotency_key, metadata)`` on the client grant --
Card FT-S deliberately added no floors table and no duration column -- so the
duration rides in ``metadata`` as ``{"duration_ms": N}``. SQL reads it with
``metadata ->> 'duration_ms'``, so it stays hot-patchable exactly as the ruling
requires, and promoting it to a column later is a migration nothing here has to
know about.

THE SPOOL IS JSON LINES AND THE APPEND IS ONE ``write``. A whole-file rewrite per
score would make a game finishing a round pay for every round before it; a
torn append can only damage the LAST line, and the reader drops a line it cannot
parse. That is the entire durability argument, and it is why this file is not the
temp/rename shape the rest of BadgeLink uses -- the rewrite shape is still used
for the two operations that are rare: retiring a delivered score and compacting a
full spool.

MicroPython surface only: ``json`` and ``os``.
"""

import json
import os


SCHEMA = 1
DEFAULT_PATH = "/state/badgelink-scores.json"

# THE GAMES' PERSISTED PERSONAL BESTS, WHICH ARE NOT THE SPOOL. There are two
# kinds of score data on this badge and conflating them is how a wipe lies: this
# module's file holds UNDELIVERED SUBMISSIONS, and each game separately keeps its
# own high score through `shared/score_sink.py`.
#
# The spec that ordered the wipe said no game kept a local high score. It was
# wrong, and the reason generalises: the grep behind it was scoped to the DEPLOY
# path (`apps/`) while the games are top-level repository trees. All five write
# `/state/<game>.json`, and the OSError-guard rollout exists precisely because
# those game-over writes happen.
#
# THE LIST LIVES HERE because `wipe_scores`' `scope: "all"` has to reach these
# files and `network_runtime` already imports this module -- one list, so a fleet
# wipe cannot silently miss a game.
#
# NOTHING ELSE IMPORTS IT, and that is deliberate rather than untidy. Each game
# owns its own `STATE_PATH`, and `settings` carries its own copy, because
# `/system/lib` DOES NOT SHIP on the production payload
# (`apps-roster.json`: `production.system_lib.ship` is false) -- so a wearer
# erasing their own high scores must not need a networking library to do it. Host
# tests pin all three lists against each other, which is the shape
# `setup_state` already uses for the app that must not import it.
GAME_STATE_PATHS = ("/state/snake.json", "/state/pong.json",
                    "/state/breakout.json", "/state/flappy.json",
                    "/state/pacman.json")


# HOW MANY UNDELIVERED SCORES THE BADGE KEEPS. Sixty-four, and the number is
# three arguments rather than a round figure:
#
# * TIME. A game round on this badge is 1-3 minutes (snake, pong, breakout,
#   flappy, pacman all sit in that band), so 64 undelivered scores is one to
#   three HOURS of continuous play with no network at all. A badge in that state
#   is not one the venue Wi-Fi is about to fix.
# * SPACE. An entry serializes to ~90-120 bytes, so the full spool is ~6-8 KB
#   against a 1 MB volume shared with five saved badges and a wallpaper film.
# * COST. Retiring a delivered score rewrites the file, so the cap is also the
#   worst-case size of that rewrite. 64 keeps it under one LittleFS block group.
MAX_ENTRIES = 64

# How many times one entry is offered before it is DISCARDED. Three, and this is
# the rule that makes the head of the spool unblockable.
#
# The drain cannot see an HTTP status -- the errand channel reports (ok, data) --
# so it cannot tell a 409 duplicate from a 403 missing grant from a 400 bad row.
# It does not need to: an entry the server has refused three times is not going to
# be accepted, and an entry that could block the head forever would silently stop
# every LATER score from ever being delivered. The counter is per BOOT and in RAM
# on purpose: persisting it would add a file write per failure, and a reboot
# retrying three more times is not a hot loop.
MAX_ATTEMPTS = 3

# THE PRE-DECODE BOUND, and it is a bound on the ALLOCATION rather than on the
# result (CX-10 sub-claim 4). Every loader in BadgeLink read its whole file and
# applied its bound afterwards, so a corrupt or hostile `/state` file was a heap
# allocation before it was a refusal -- and this module was the one that did not
# bound on READ at all, because `MAX_ENTRIES` is enforced by `record`.
#
# 64 KB, and the arithmetic is: MAX_ENTRIES entries at MAX_LINE_BYTES each is
# 32,832 B, so a legal spool has 2x headroom. Past the cap the read STOPS at the
# last complete line inside it rather than refusing the file, which keeps the
# entry the drain needs: FIFO means the head is always in the prefix.
#
# TRUNCATION IS NOT SELF-HEALING ON ITS OWN, and saying it was hid a real hole
# for one lane. The heal is the COMPACTION in `record`, which only ran when
# `_pending >= MAX_ENTRIES` -- and an over-cap file whose prefix holds no
# complete record counts ZERO entries, so nothing compacted, the append landed
# past this cap where neither reader goes, and the score was reachable only
# through the RAM `_head` that the next reset throws away. See
# :func:`_can_append`: an append now has to be REACHABLE, or the file is
# compacted first.
MAX_BYTES = 65536

# ONE RECORD'S CEILING, for the frame-safe scan below. A `record` line is
# ~90-120 bytes and its worst legal case is ~270 (a 64-character game, a 128
# character key, a bigint score), so 512 is roughly double the worst thing this
# module can write.
MAX_LINE_BYTES = 512

# `scores.game ~ '^[a-z][a-z0-9_-]{0,63}$'`, and `scores.idempotency_key`'s
# `char_length between 8 and 128` plus `~ '^[A-Za-z0-9._:-]+$'`.
MAX_GAME = 64
MIN_KEY = 8
MAX_KEY = 128
KEY_CHARS = ("abcdefghijklmnopqrstuvwxyz"
             "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
             "0123456789._:-")

# `scores.score bigint not null check (score >= 0)`. The upper bound is bigint's,
# stated so a game handing over a corrupted counter is refused here rather than
# by a 400 nobody reads.
MAX_SCORE = 9223372036854775807

# `metadata` is `jsonb ... octet_length <= 4096`, and this module puts exactly one
# key in it. The duration cap is a sanity bound, not a judgment: 24 hours.
MAX_DURATION_MS = 24 * 60 * 60 * 1000

_HEX = "0123456789abcdef"

#: Cached count of undelivered scores. ``None`` means "not read yet".
#: THE CACHE IS WHY THE FRAME PUMP CAN ASK EVERY FRAME. A game and the transport
#: share one interpreter and one ``sys.modules`` entry, so a score recorded inside
#: ``launch()`` is visible to the pump without either side knowing about the
#: other, and the pump's per-frame question costs an integer compare instead of a
#: filesystem read.
_pending = None

#: The OLDEST undelivered entry, retained beside the count (CX-10). The drain
#: asked :func:`head` for it on every drain frame and paid a whole-file read for
#: the answer; FIFO means the head only moves when the spool empties, when it is
#: retired, or when a compaction drops it, so it is RAM state with three writers
#: and not a thing to re-read. ``None`` with a known ``_pending`` means the spool
#: is empty; ``None`` with ``_pending is None`` means nothing is known yet.
_head = None

#: The in-progress cold scan: ``[byte_offset, records_counted]``, or ``None``.
#: See :func:`drain_head`.
_scan = None

#: THE APPEND'S PRECONDITION: the spool's size in bytes when this module last
#: knew the file ENDED WHERE A RECORD ENDS -- ``-1`` when it provably does not
#: (a torn tail, an over-long line, or anything past :data:`MAX_BYTES`), and
#: ``None`` when nothing has read it yet.
#:
#: IT IS DERIVED, NEVER MEASURED, and that is what makes the check free. Every
#: read that learns the file's length also learns where it ends, so a game
#: finishing a round pays no ``stat`` and no extra ``open`` for the answer --
#: which matters, because the append being ONE ``open`` is the trade this whole
#: module is built on. The invariant a future writer must keep: **whatever sets
#: ``_pending`` sets this too** (`test_cx10_boot_json_cost.SpoolRepairTests`
#: asserts it for all six writers). During the append itself it is ``-1``, so a
#: write that fails half way leaves a REPAIR pending rather than a lie.
_appendable = None


def valid_game(value):
    """``scores.game``'s class: ``^[a-z][a-z0-9_-]{0,63}$``."""

    if not isinstance(value, str) or not value or len(value) > MAX_GAME:
        return False
    if not ("a" <= value[0] <= "z"):
        return False
    for character in value:
        if not (("a" <= character <= "z") or ("0" <= character <= "9")
                or character == "-" or character == "_"):
            return False
    return True


def valid_key(value):
    """``scores.idempotency_key``'s class and length bounds."""

    if not isinstance(value, str):
        return False
    if len(value) < MIN_KEY or len(value) > MAX_KEY:
        return False
    for character in value:
        if character not in KEY_CHARS:
            return False
    return True


def valid_score(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return 0 <= value <= MAX_SCORE


def valid_duration(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return 0 <= value <= MAX_DURATION_MS


def new_key(urandom=None):
    """An idempotency key: ``sb.`` plus 16 hex characters.

    RANDOM RATHER THAN DERIVED, and the difference matters. A key derived from
    the game and the score would collide for two identical rounds -- entirely
    normal in a game with a low ceiling -- and the unique constraint
    ``(badge_id, game, idempotency_key)`` would silently drop the second one. A
    counter would collide across reboots. 64 random bits collide at a rate this
    fleet will never observe.
    """

    if urandom is None:
        urandom = getattr(os, "urandom", None)
    if urandom is None:
        return None
    try:
        raw = urandom(8)
    except Exception:
        return None
    out = ["s", "b", "."]
    for index in range(8):
        byte = raw[index]
        out.append(_HEX[(byte >> 4) & 0x0F])
        out.append(_HEX[byte & 0x0F])
    return "".join(out)


def _entry(value):
    """One spool line, validated, or ``None``."""

    if not isinstance(value, dict):
        return None
    game = value.get("game")
    score = value.get("score")
    duration = value.get("duration_ms")
    key = value.get("key")
    if not valid_game(game) or not valid_score(score):
        return None
    if not valid_duration(duration) or not valid_key(key):
        return None
    return {"game": game, "score": score, "duration_ms": duration, "key": key}


def _read_lines(path, open_fn):
    """Every valid entry in the file, oldest first, from a BOUNDED read.

    ``read(MAX_BYTES + 1)`` rather than ``read()``: the extra byte is how the
    caller learns the file was over the cap without allocating the rest of it.
    An over-cap file is TRUNCATED to its last complete line rather than refused,
    for the reason :data:`MAX_BYTES` gives.

    IT ALSO ANSWERS THE APPEND QUESTION, because it is already holding the only
    two facts that decide it: how long the file is, and whether it ends where a
    record ends. See :data:`_appendable`.
    """

    global _appendable
    try:
        with open_fn(path, "r") as source:
            text = source.read(MAX_BYTES + 1)
    except OSError:
        # A MISSING spool is an empty one and an append is how it gets created;
        # an unreadable one cannot be appended to either, and `record`'s blanket
        # refusal is what covers that.
        _appendable = 0
        return []
    if len(text) > MAX_BYTES:
        # DROP THE PARTIAL TAIL. A cut in the middle of a line would fail to
        # decode anyway; cutting at the last newline says so deliberately.
        # NOTHING MAY BE APPENDED to a file this long, whatever the prefix holds:
        # the appended line would sit past the cap both readers stop at.
        _appendable = -1
        text = text[:MAX_BYTES]
        cut = text.rfind("\n")
        text = text[:cut] if cut >= 0 else ""
    elif text and not text.endswith("\n"):
        # A TORN TAIL. An append would join onto the fragment and the two would
        # decode as neither.
        _appendable = -1
    else:
        _appendable = len(text)
    entries = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            # A TORN LAST LINE, which is the only damage an interrupted append
            # can do, or a line from a build with a different shape. Dropped
            # individually so one bad score cannot cost the rest.
            continue
        entry = _entry(value)
        if entry is not None:
            entries.append(entry)
    return entries


def load(path=None, open_fn=None):
    """Every undelivered score, oldest first.  Never raises.

    THE AUTHORITATIVE WHOLE-FILE READ, and it is deliberately still here: the
    game path (``record`` on a fresh boot), the device probes and the tests all
    want the file's own answer in one call. What must not use it is a RENDERED
    FRAME -- see :func:`drain_head`.
    """

    global _pending, _head, _scan
    entries = _read_lines(path or DEFAULT_PATH, open_fn or open)
    _pending = len(entries)
    _head = entries[0] if entries else None
    # A whole-file read is a better answer than a scan in progress, and leaving
    # the scan armed would let it overwrite this count with a partial one.
    _scan = None
    return entries


def _rewrite(entries, path, open_fn=None, sync_fn=None, rename_fn=None):
    """The RARE path: temp -> flush -> sync -> rename, for retire and compact.

    THE WHOLE-FILE WRITER OWNS THE APPEND STATE, and it owns it for free: every
    line it writes is newline terminated, so the file it leaves ends exactly
    where a record ends and its length is the sum of what it wrote. Recorded
    AFTER the rename, so a failure part way through leaves the previous file --
    and the previous answer -- untouched.
    """

    global _appendable
    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    temporary = path + ".tmp"
    written = 0
    with open_fn(temporary, "w") as output:
        for entry in entries:
            line = json.dumps(entry)
            output.write(line)
            output.write("\n")
            written += len(line) + 1
        flush = getattr(output, "flush", None)
        if flush is not None:
            flush()
    sync = sync_fn if sync_fn is not None else getattr(os, "sync", None)
    if sync is not None:
        sync()
    (rename_fn or os.rename)(temporary, path)
    _appendable = written
    return entries


def _can_append(needed):
    """Whether one more line of ``needed`` bytes would still be REACHABLE.

    Two conditions and the second is the one `7effa98e` missed: the file has to
    end where a record ends, AND the new line has to fit inside
    :data:`MAX_BYTES`, because both readers stop there. An unknown state is not a
    licence to append.

    THE ARITHMETIC SAYS THIS NEVER FIRES FOR A FILE THIS MODULE WROTE: a legal
    spool is at most ``MAX_ENTRIES * MAX_LINE_BYTES`` = 32,832 bytes, half the
    cap, and a spool at ``MAX_ENTRIES`` compacts on the count anyway. What it
    fires for is a foreign or damaged file, which is exactly the case that lost
    scores in silence.
    """

    return (_appendable is not None and _appendable >= 0
            and _appendable + needed <= MAX_BYTES)


def record(game, score, duration_ms=0, path=None, key=None, **io):
    """Spool one score.  THE GAME-FACING CALL, and it NEVER RAISES.

    Returns the idempotency key on success and ``None`` on refusal, so a game
    that wants to know can look and a game that does not can ignore it. A game
    must not crash because a volume was full or a score was out of range.

    NO JUDGMENT HAPPENS HERE beyond the column bounds the database would reject
    anyway (the minimal-anti-cheat ruling): there is no floor, no plausibility
    test and no rate limit, because all of that is SQL's and hot-patchable.

    AND THE SCORE MUST BE THERE AFTER THE NEXT RESET, which is the property the
    append alone does not give: see :func:`_can_append`. A file this module
    cannot append to REACHABLY is compacted first, in the same rewrite that
    already existed for a full spool.
    """

    global _pending, _head, _appendable
    try:
        if not valid_game(game) or not valid_score(score):
            return None
        if not valid_duration(duration_ms):
            return None
        if key is None:
            key = new_key(io.pop("urandom", None))
        else:
            io.pop("urandom", None)
        if not valid_key(key):
            return None
        # POPPED, NOT READ. `_rewrite` takes only the three write hooks, so
        # leaving `mkdir_fn` in `io` made the compact path raise TypeError -- and
        # the blanket `except` below turned that into a silent "score lost" for
        # every caller that injected one.
        mkdir_fn = io.pop("mkdir_fn", None)
        path = path or DEFAULT_PATH
        open_fn = io.get("open_fn") or open
        entry = {"game": game, "score": score, "duration_ms": duration_ms,
                 "key": key}
        payload = json.dumps(entry) + "\n"
        if _pending is None:
            load(path, open_fn)
        if _pending >= MAX_ENTRIES or not _can_append(len(payload)):
            # COMPACT, dropping the OLDEST. A spool this full means the badge has
            # been offline for hours; the newest scores are the ones whose wearer
            # is still at the event. THE TRADE, STATED: a high score older than
            # MAX_ENTRIES rounds can be lost. FIFO is chosen because ANY
            # score-aware eviction would be judgment, and judgment is SQL's.
            #
            # OR REPAIR, through the same rewrite and for a different reason: the
            # file cannot take a reachable append (`_can_append`). One rule
            # rather than two -- a torn tail could also be healed by inserting a
            # newline in the same `open`, but that leaves the corruption in the
            # file for every later scan to step over, and this path removes it.
            # It costs one rewrite ONCE per damage event, because what it leaves
            # behind is appendable. A prefix with no complete record in it
            # compacts to EMPTY and the new score is the only line.
            entries = _read_lines(path, open_fn)
            keep = entries[-(MAX_ENTRIES - 1):] if MAX_ENTRIES > 1 else []
            keep.append(entry)
            _rewrite(keep, path, **io)
            _pending = len(keep)
            # THE HEAD MOVED, because FIFO compaction dropped the oldest entries.
            _head = keep[0] if keep else None
            return key
        # THE APPEND. One `write` of one line, flushed and synced -- not the
        # temp/rename dance, because a whole-file rewrite per score would make
        # every round pay for every round before it.
        _ensure_parent(path, mkdir_fn)
        size = _appendable
        # PESSIMISTIC ACROSS THE WRITE, and it costs nothing: an ENOSPC part way
        # through a line leaves a torn tail behind, so until this append lands
        # whole the file is not one that may be appended to again.
        _appendable = -1
        with open_fn(path, "a") as output:
            output.write(payload)
            flush = getattr(output, "flush", None)
            if flush is not None:
                flush()
        sync = io.get("sync_fn")
        if sync is None:
            sync = getattr(os, "sync", None)
        if sync is not None:
            sync()
        _appendable = size + len(payload)
        # THE HEAD MOVES ONLY WHEN THE SPOOL WAS EMPTY. An append lands at the
        # TAIL, so FIFO leaves the oldest entry exactly where it was.
        if not _pending:
            _head = entry
        _pending += 1
        return key
    except Exception:
        # THE GAME NEVER LEARNS. A full volume, a read-only mount, a missing
        # /state: none of them may become a traceback inside launch(), which is a
        # modal that resets the badge.
        return None


def _ensure_parent(path, mkdir_fn=None):
    if "/" not in path:
        return
    parent = path.rsplit("/", 1)[0]
    if not parent:
        return
    maker = mkdir_fn if mkdir_fn is not None else getattr(os, "mkdir", None)
    if maker is None:
        return
    try:
        maker(parent)
    except OSError:
        pass
    except Exception:
        pass


def pending(path=None, open_fn=None):
    """How many scores are waiting.  One filesystem read per boot, then RAM.

    NOT FOR A RENDERED FRAME on a boot that has not read the spool yet: the
    ``_pending is None`` branch is a whole-file load, which is what CX-10 found
    outside the frame budget. A frame asks :func:`scan_complete` and
    :func:`drain_head`; a Settings screen, a snapshot or a probe asks this.
    """

    global _pending
    if _pending is None:
        load(path, open_fn)
    return _pending


def head(path=None, open_fn=None):
    """The oldest undelivered score, or ``None``.  Reads the file.

    The authoritative answer, like :func:`load` and for the same callers. The
    frame pump uses :func:`drain_head`.
    """

    global _pending, _head, _scan
    entries = _read_lines(path or DEFAULT_PATH, open_fn or open)
    _pending = len(entries)
    _head = entries[0] if entries else None
    _scan = None
    return _head


def scan_complete():
    """Whether the spool depth is known.  FREE: no filesystem, no allocation.

    The per-frame question, and the reason a frame can ask it every frame: an
    empty spool that has already been scanned answers "nothing to do" for an
    integer compare, so the drain never claims the frame's chore budget for a
    badge whose games have not been played.
    """

    return _pending is not None


def cached_head():
    """The oldest entry if it is already in RAM, else ``None``.  FREE."""

    return _head


def drain_head(path=None, open_fn=None):
    """The oldest score FOR A FRAME: RAM, or ONE bounded record read (CX-10).

    THE COLD LOAD WAS THE DEFECT, not the drain. ``pending()`` and ``head()``
    each read the whole spool, and on the first serviced frame of a boot both ran
    -- 64 per-line JSON decodes and 12,544 bytes, twice, in ONE rendered frame,
    with the first of the two happening eighteen lines BEFORE the frame's chore
    budget was claimed. This is the same information gathered ONE RECORD AT A
    TIME, so the worst frame decodes a single ~100-byte line.

    Two answers rather than one, and the first is what makes it usable
    immediately: **the head is the FIRST line**, so step one already has it and
    the drain does not wait for the count. The scan keeps stepping until the
    count is known too, because ``record`` and ``snapshot`` both ask for the
    count and neither of them should be the one to pay for a whole-file read.

    THE OPEN COUNT RISES AND THAT IS THE TRADE, stated plainly: a 64-entry spool
    is scanned in 64 frames with one ``open``/``seek``/``read`` each, where it
    used to be one open. The FRAME is the budget CX-10 is about, and 64 frames is
    ~1.7 s at the launcher's cadence. A held file handle would have saved the
    opens and was rejected: it would have to survive a game's own ``record``
    append in the same interpreter and be closed on every abandonment path,
    while a byte offset is state that cannot leak.
    """

    if _pending is None:
        _scan_step(path, open_fn)
    return _head


def _scan_step(path, open_fn):
    """Read, decode and account for ONE bounded record.  Never raises.

    BINARY MODE ON PURPOSE. The scan carries a byte offset across frames, and in
    text mode a ``seek`` offset is an opaque cookie rather than a position -- so
    ``offset + len(chunk)`` is only a byte count when the file is read as bytes.
    ``open(path, "rb")`` plus ``seek``/``tell`` is device-proven in this
    repository (``glyphskin``, ``nametag.backdrop``, ``glyph_stream``).
    """

    global _pending, _head, _scan, _appendable
    path = path or DEFAULT_PATH
    open_fn = open_fn or open
    if _scan is None:
        _scan = [0, 0]
    offset, count = _scan
    try:
        with open_fn(path, "rb") as source:
            if offset:
                source.seek(offset)
            chunk = source.read(MAX_LINE_BYTES + 1)
    except Exception:
        # NO FILE, an unreadable one, or a volume that went away mid-scan. The
        # spool exists precisely because a badge is sometimes broken; what is
        # counted so far is the answer, and it is the same fail-soft rule
        # `_read_lines` applies to an OSError.
        _pending = count
        _scan = None
        _appendable = 0 if not offset else -1
        return "done"
    if not chunk:
        # CLEAN END OF FILE: the last thing read was a newline, so the file ends
        # where a record ends and `offset` is its length. This is the branch a
        # boot that only ever DRAINS takes, which is why the scan answers the
        # append question too rather than leaving it to a later whole-file read.
        _pending = count
        _scan = None
        _appendable = offset
        return "done"
    at = chunk.find(b"\n")
    if at < 0:
        if len(chunk) > MAX_LINE_BYTES:
            # AN OVER-LONG RECORD ENDS THE SCAN. Skipping it would need an
            # unbounded read to find where it ends, which is the allocation this
            # whole cap exists to refuse -- and `record` cannot write one, so the
            # file is foreign or damaged from here on. Everything before it is
            # kept, which is stricter than `_read_lines`' per-line drop and is
            # the deliberate difference between the two readers.
            _pending = count
            _scan = None
            _appendable = -1
            return "done"
        line = chunk
        offset += len(chunk)
        final = True
    else:
        line = chunk[:at]
        offset += at + 1
        final = False
    entry = None
    if line.strip():
        try:
            entry = _entry(json.loads(line.decode()))
        except Exception:
            # A TORN LAST LINE or a foreign one, dropped individually exactly as
            # `_read_lines` drops it.
            entry = None
    if entry is not None:
        count += 1
        if _head is None:
            _head = entry
    if final or offset > MAX_BYTES:
        # A TAIL WITH NO NEWLINE, or a complete line that ended past the cap.
        # Both mean an append would be unreachable, and both are what
        # `_can_append` exists to catch.
        _pending = count
        _scan = None
        _appendable = -1
        return "done"
    _scan = [offset, count]
    return "scanning"


def retire(key, path=None, **io):
    """Drop one delivered (or exhausted) score.  Returns True when it was there.

    Called after a successful post AND after :data:`MAX_ATTEMPTS` refusals, which
    is the same operation: this entry is no longer the badge's problem.
    """

    global _pending, _head, _scan
    path = path or DEFAULT_PATH
    open_fn = io.get("open_fn") or open
    entries = _read_lines(path, open_fn)
    keep = [entry for entry in entries if entry["key"] != key]
    # THE RARE PATH already reads the whole file, so it is also the one place the
    # RAM pair can be re-derived for free rather than guessed at.
    _scan = None
    if len(keep) == len(entries):
        _pending = len(entries)
        _head = entries[0] if entries else None
        return False
    _rewrite(keep, path, **io)
    _pending = len(keep)
    _head = keep[0] if keep else None
    return True


def clear(path=None, **io):
    """Empty the spool.  For a device session and for tests, not for a game."""

    global _pending, _head, _scan
    _rewrite([], path, **io)
    _pending = 0
    _head = None
    _scan = None
    return True


def wipe(path=None, **io):
    """Discard every UNDELIVERED score.  NEVER RAISES.  Returns whether it went.

    THE WEARER'S DOOR AND THE FLEET'S DOOR, and both of them are why this is not
    just :func:`clear`. One caller is a Settings action running inside
    ``launch()``, where an escaping ``OSError`` reaches the firmware's
    ``fatal_error()`` and ``machine.reset()`` -- so a full volume would turn
    "wipe my scores" into a reboot, on the exact screen that promised the wearer
    a safe way to do it. The other is the ``wipe_scores`` command applier, where
    a raise would cost the ack the fleet is waiting on. ``clear`` keeps its
    raising contract for a device session and for tests, which is the only place
    a failed rewrite should be loud.

    IT DOES NOT UN-SEND ANYTHING, and no copy above it may imply otherwise: rows
    already posted are the backend's, deletable in SQL and by nothing here.

    ON FAILURE IT FORGETS RATHER THAN CLAIMS EMPTY, which is the one subtle part.
    ``_rewrite`` renames last, so a failure leaves the previous file -- and the
    previous scores -- intact. Setting ``_pending = 0`` there would strand them
    forever: the frame pump reads a known-zero depth and stops draining, and no
    later read ever contradicts it, so real scores would sit undelivered until a
    reset. :func:`reset_cache` says "unknown" instead, and the next reader
    re-derives the truth from the file.
    """

    try:
        clear(path, **io)
        return True
    except Exception:
        reset_cache()
        return False


def wipe_bests(paths=None, remove_fn=None, stat_fn=None):
    """Delete the games' persisted personal bests.  NEVER RAISES.

    Returns ``(removed, failed)``. A file that was never written counts as
    NEITHER: a badge whose wearer never played Pong has nothing to erase there,
    and reporting that as a failure would make a completely successful wipe look
    partial on every badge. **That case is decided by whether the file is still
    there, not by an errno** -- see the comment in the loop for the port that
    proved why.

    DELETION RATHER THAN A ZERO RECORD, and the reader is why: `score_sink.read`
    treats a missing file as ``missing`` and answers zero, so an absent file IS
    the never-played state. Writing ``{"high_score": 0}`` instead would leave a
    record claiming a run happened and scored nothing.

    THIS IS THE POWER THE FLEET COMMAND GATES. `scope: "spool"` never comes here;
    only `scope: "all"` does, and whether that is ever queued is an owner-level
    server-side decision on purpose (ruling, 2026-08-27) -- remote erasure of a
    wearer's personal bests must never arrive as a side effect of clearing a
    delivery backlog.
    """

    remove = remove_fn if remove_fn is not None else getattr(os, "remove", None)
    stat = stat_fn if stat_fn is not None else getattr(os, "stat", None)
    removed = 0
    failed = 0
    for path in (paths if paths is not None else GAME_STATE_PATHS):
        if remove is None:
            failed += 1
            continue
        try:
            remove(path)
            removed += 1
        except Exception:
            # NOT AN ERRNO COMPARISON, and that is a correction rather than a
            # style: this counted `args[0] == 2` as "already gone" until the
            # browser lane ran the same code and raised **44** for a missing file
            # (WASI's numbering, not POSIX's), so every never-played game counted
            # as a failure. The observable state answers the question on every
            # port, and it is also exactly what the caller is claiming.
            if stat is None:
                failed += 1
                continue
            try:
                stat(path)
            except Exception:
                # Gone, or unreachable in a way that is indistinguishable from
                # gone. Either way there is nothing left here to erase.
                continue
            failed += 1
    return removed, failed


def reset_cache():
    """Forget the cached count. Tests and a fresh boot; never a game."""

    global _pending, _head, _scan, _appendable
    _pending = None
    _head = None
    _scan = None
    _appendable = None


def row(badge_id, entry):
    """One spool entry as the ``scores`` row the badge is allowed to insert.

    EXACTLY the five client-writable columns and nothing else. The insert-time
    clock column is deliberately absent -- it is server-authored, which is what
    stops a badge backdating a score to win a tiebreak against a later, higher
    entry.
    """

    return {
        "badge_id": badge_id,
        "game": entry["game"],
        "score": entry["score"],
        "idempotency_key": entry["key"],
        # No duration COLUMN exists. SQL reads `metadata ->> 'duration_ms'`, so
        # the ruling's "all judgment is SQL, hot-patchable" still holds.
        "metadata": {"duration_ms": entry["duration_ms"]},
    }
