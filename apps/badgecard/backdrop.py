"""BDR1 backdrop cache: the worn badge's artwork, rasterised once and kept.

THIS FILE IS THE CANONICAL COPY.  EDIT IT HERE AND NOWHERE ELSE.

    python3 scripts/sync_ui.py            # refresh every vendored copy
    python3 scripts/sync_ui.py --check    # fail if any has drifted

WHY IT EXISTS.  The owner's 2026-08-21 verdict on the worn badge: *"badge feels
instant but the artwork takes an extra half a second which is not ideal."*  That
half second is `shared/poster.Poster.background` -- one `skins.render` into a
full-screen buffer, 63.752 ms median and 247.900 ms max at HIRES, and up to
864 ms for the worst arm ever measured.  It is paid at STAGE 2 of the staged
arrival, on the frame the wearer is watching, every single time the badge is
opened -- to produce THE SAME PIXELS every time, because a procedural skin is a
pure function of its index and the surface geometry.

So the pixels are persisted.  Stage 2 becomes a file read and a blit, and the
render happens once per skin change rather than once per open.

WHAT IS CACHED, AND WHAT IS DELIBERATELY NOT.  Only PROCEDURAL skins.  A GLYPH
entry is painted by a live `glyphskin.SkinPainter` that owns the surface and
diff-paints its animation INTO it -- a cached first frame would be overwritten
by the painter's own keyframe and would have bought nothing.  Glyph entries keep
the live path; `Poster.background` is where that split is made.

THE CACHE IS A CACHE, NOT STATE, AND THAT IS THE WHOLE RISK MODEL.  Every
failure -- missing file, short file, wrong magic, wrong geometry, wrong stamp,
unreadable volume, a torn write from a power loss mid-save -- returns None or
False, and the caller renders live exactly as it does today.  So this feature
cannot make the badge worse than it was; it can only fail to make it faster.
That is also why there is NO `.tmp` and NO `.bak` here, unlike
`shared/wallpaper.py`:

  * a rename-based atomic write needs the new file to fit BESIDE the old one,
    and at HIRES that is 614 KB of a 1 MB LittleFS volume for a file nobody
    would miss if it vanished;
  * a `.bak` is a second 307 KB copy of pixels that can be regenerated in one
    `skins.render`.

`save` therefore REMOVES the old file first (so the volume only ever holds one
copy, and the space check only has to clear one), then writes the header, then
the pixels.  A write interrupted anywhere leaves a file that is SHORT, and a
short file fails the read gate below -- which is the same truncation gate
`wallpaper.load` already relies on.

THE SPACE CHECK HAS TO BE TOLD WHICH FILE IT IS REPLACING, and until 2026-08-22
it was not.  `statvfs` counts the old cache as used, so "one copy plus slack"
silently meant "two copies plus slack" on every badge that had ever cached
anything -- which is to say the first skin a wearer cached was the only skin
they could ever cache.  `space_for` now takes a `path` and credits its bytes;
that docstring has the device evidence and the reason nothing is removed first.

FILE FORMAT -- BDR1, 64-byte little-endian header, then raw pixels:

     0  4  b"BDR1"                    | 10  4  stamp    fnv1a32 of everything
     4  1  version = 1                |                 that decides the pixels
     5  1  flags  bit0 = PALE, the    | 14  2  id_len   1..48
              ink polarity sampled    | 16 48  id       the catalogue entry id,
              when it was rendered    |                 UTF-8, zero padded
     6  2  width   1..1024            | 64 ..  width * height * 4 bytes,
     8  2  height  1..1024            |        RGBA8888, top-left origin

THE ID IS STORED WHOLE rather than hashed, because the failure mode of a hash
collision here is the wearer's badge showing SOMEBODY ELSE'S ARTWORK, and 48
bytes buys that away completely (`card_model._ident` already caps an id at 48).
The `stamp` covers the things an id cannot: the renderer's own version, the
catalogue's shape, and the artwork module's file size.

FLAGS CARRIES THE INK POLARITY, and that is not an optimisation for its own
sake: `Poster._sample_ink` is 189 `get()` calls, each boxing a `color` object,
and its whole answer is one bit -- is the name band dark enough for white type.
Storing the bit beside the pixels it was measured from keeps a cache hit free of
the one piece of work that would otherwise still run per open.
"""

import os


MAGIC = b"BDR1"
VERSION = 1
HEADER_BYTES = 64

# One module owns the path.  `/state` is the writable LittleFS volume; no deploy
# path touches it, which is exactly why a cache may live there and survive a
# firmware update -- and exactly why `stamp` has to be able to invalidate it.
PATH = "/state/backdrop.bdr"

# Where the id lives in the header, and how long it may be.  48 is
# `card_model._ident`'s own cap, so an id this table cannot hold is an id the
# schema would already have truncated.
ID_OFFSET = 16
MAX_ID = 48

# Big enough for 320x240 and for anything the panel could plausibly become; a
# geometry outside this is evidence the bytes are not a backdrop.
MAX_DIM = 1024

# bit0: the artwork's name band measured PALE, so the poster's type is black on
# white rather than white on black.  `Poster._sample_ink` owns the threshold.
FLAG_PALE = 0x01

# On top of the file itself, and it is `card_bake.DISK_SLACK`'s number for
# `card_bake`'s reason: a volume filled to the last block cannot write
# `badgecard.json` either, and losing the badge to save a cache is the wrong
# trade twice over.
DISK_SLACK = 65536
UNKNOWN_FREE = -1

# Everything a total function must swallow.  `shared/wallpaper.py`'s tuple, for
# the same reasons -- including `MemoryError`, because a runtime that cannot
# allocate a 64-byte header read must degrade to "no cache" rather than to a
# badge that will not open.
_SAFE = (OSError, ValueError, TypeError, LookupError, AttributeError,
         ArithmeticError, MemoryError)


def fnv1a32(data):
    """FNV-1a/32 over `data`.

    THE 32-BIT DIGEST, UNFOLDED, unlike `wallpaper.fnv1a16`.  That one folds to
    16 bits because it is written into a two-byte header field; this one has
    four bytes to spend and spends them: a collision here means a badge drawing
    artwork from a build it is no longer running, and 1-in-4-billion is worth
    two extra bytes.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    digest = 0x811C9DC5
    for byte in data:
        digest = ((digest ^ byte) * 0x01000193) & 0xFFFFFFFF
    return digest


def stamp(*parts):
    """Hash everything that decides the cached pixels.  Ints, strs and bytes.

    FLOATS ARE REFUSED, and `wallpaper.recipe_id` records why: `repr(0.1)` is
    not guaranteed to agree between CPython and MicroPython, so a stamp built
    from one would differ between the host lane and the device -- which presents
    as "the cache never hits on hardware while every host test passes".
    """
    fields = []
    for part in parts:
        if isinstance(part, (bytes, bytearray)):
            fields.append(bytes(part).decode("utf-8"))
        elif isinstance(part, str) or isinstance(part, int):
            fields.append(str(part))
        else:
            raise TypeError("stamp part is not a str, bytes or int: %r"
                            % (part,))
    return fnv1a32("\x1f".join(fields))


def _u16(buf, offset):
    return buf[offset] | (buf[offset + 1] << 8)


def _u32(buf, offset):
    return (buf[offset] | (buf[offset + 1] << 8) | (buf[offset + 2] << 16)
            | (buf[offset + 3] << 24))


def _describe(head):
    view = bytes(head[:HEADER_BYTES])
    if len(view) < HEADER_BYTES:
        return None
    if view[0:4] != MAGIC:
        return None
    if view[4] != VERSION:
        return None
    width = _u16(view, 6)
    height = _u16(view, 8)
    length = _u16(view, 14)
    if not 1 <= width <= MAX_DIM:
        return None
    if not 1 <= height <= MAX_DIM:
        return None
    if not 1 <= length <= MAX_ID:
        return None
    try:
        entry = bytes(view[ID_OFFSET:ID_OFFSET + length]).decode("utf-8")
    except _SAFE:
        return None
    payload = width * height * 4
    return {
        "version": view[4],
        "flags": view[5],
        "pale": bool(view[5] & FLAG_PALE),
        "width": width,
        "height": height,
        "stamp": _u32(view, 10),
        "id": entry,
        "payload_bytes": payload,
        "total_bytes": HEADER_BYTES + payload,
    }


def parse_header(head):
    """Describe a BDR1 header as a dict, or return None.  Never raises.

    Total for `wallpaper.parse_header`'s reason and one of its own: this runs on
    the badge app's LAUNCH PATH, and an exception there is `fatal_error` -- a
    modal that blocks until a keypress and then resets the badge.  A cache is
    not worth a reset.
    """
    if head is None:
        return None
    try:
        return _describe(head)
    except _SAFE:
        return None


def encode_header(entry_id, width, height, mark, pale=False):
    """The 64 bytes that frame a backdrop.  RAISES ValueError on bad input.

    The same asymmetry `wallpaper.encode` documents: a reader that raises breaks
    the badge, while a writer that quietly clamps produces a header that lies
    about its own pixels.
    """
    if not isinstance(entry_id, str) or not entry_id:
        raise ValueError("entry id must be a non-empty str")
    raw = entry_id.encode("utf-8")
    if len(raw) > MAX_ID:
        raise ValueError("entry id is %d bytes, over %d" % (len(raw), MAX_ID))
    if not isinstance(width, int) or not isinstance(height, int):
        raise ValueError("width and height must be ints")
    if not 1 <= width <= MAX_DIM or not 1 <= height <= MAX_DIM:
        raise ValueError("geometry %rx%r is outside 1..%d"
                         % (width, height, MAX_DIM))
    if not isinstance(mark, int) or not 0 <= mark <= 0xFFFFFFFF:
        raise ValueError("stamp %r does not fit four bytes" % (mark,))
    out = bytearray(HEADER_BYTES)
    out[0:4] = MAGIC
    out[4] = VERSION
    out[5] = FLAG_PALE if pale else 0
    out[6] = width & 0xFF
    out[7] = (width >> 8) & 0xFF
    out[8] = height & 0xFF
    out[9] = (height >> 8) & 0xFF
    out[10] = mark & 0xFF
    out[11] = (mark >> 8) & 0xFF
    out[12] = (mark >> 16) & 0xFF
    out[13] = (mark >> 24) & 0xFF
    out[14] = len(raw) & 0xFF
    out[15] = (len(raw) >> 8) & 0xFF
    out[ID_OFFSET:ID_OFFSET + len(raw)] = raw
    return bytes(out)


def matches(header, entry_id, width, height, mark):
    """Is this header a picture of exactly what the caller is about to draw?

    FOUR THINGS, AND ALL FOUR ARE LOAD-BEARING.  The id catches a badge whose
    skin changed.  The geometry catches the resolution flip and a thumbnail
    written by a contact sheet.  The stamp catches everything else -- a bumped
    renderer version, an inserted catalogue row that shifted every index, a
    rebuilt artwork module -- and it is the field that makes this cache safe to
    ship, because the alternative is a badge that keeps drawing last month's
    artwork for ever.
    """
    if header is None:
        return False
    return (header["id"] == entry_id and header["width"] == width
            and header["height"] == height and header["stamp"] == mark)


def peek(path=PATH):
    """The cached backdrop's header, or None.  Never raises, reads 64 bytes.

    The cheap half of the question: an app can ask "is the cache already the
    picture my state describes?" for one `open` and 64 bytes, without reading
    307,200 of them and without rendering anything to compare against.
    """
    source = None
    try:
        source = open(path, "rb")
        return parse_header(source.read(HEADER_BYTES))
    except _SAFE:
        return None
    finally:
        if source is not None:
            try:
                source.close()
            except OSError:
                pass


def load_into(buffer, entry_id, width, height, mark, path=PATH):
    """Fill `buffer` with the cached pixels, or return None.  Never raises.

    `buffer` is the SURFACE'S OWN BYTES -- `Poster.backdrop` is constructed as
    `image(w, h, buffer)` and Badgeware keeps a raw pointer to them, so a
    `readinto` here IS the blit source being repainted.  Nothing is copied,
    nothing is allocated, and the surface the poster already blits every frame
    is the surface that got filled.

    Returns the header on success, so the caller also gets the ink polarity.

    THE LENGTH IS CHECKED BEFORE A SINGLE BYTE IS COPIED, with `os.stat`.  That
    ordering is the point: a truncated file caught by a short `readinto` would
    already have overwritten part of the surface, and the caller would be
    rendering over a half-read picture.  `wallpaper.decode` says exactly this --
    the exact-size question "belongs to the app, which has `total_bytes` from
    `parse_header` and one `os.stat` away from a definitive answer" -- and here
    the app IS this function.  The short-read gate below stays anyway, for a
    volume that changes under us between the stat and the read.
    """
    source = None
    try:
        source = open(path, "rb")
        header = parse_header(source.read(HEADER_BYTES))
        if not matches(header, entry_id, width, height, mark):
            return None
        payload = header["payload_bytes"]
        if len(buffer) != payload:
            return None
        if os.stat(path)[6] != header["total_bytes"]:
            return None
        if source.readinto(buffer) != payload:
            return None
        return header
    except _SAFE:
        return None
    finally:
        if source is not None:
            try:
                source.close()
            except OSError:
                pass


def module_bytes(root, name="skins"):
    """The artwork module's size on the volume, or 0 when it cannot be told.

    THE AUTOMATIC HALF OF THE STAMP.  `BACKDROP_CACHE_VERSION` is the lever a
    human pulls; this is the net under it, because the change nobody remembers
    to bump a constant for is an edit to a skin -- and every path that lands one
    on a badge (`scripts/skin.py sync`, `build_mpy.py`, a Disk Mode copy) moves
    this number.

    `.mpy` FIRST, because that is what the device runs: MicroPython stats `.py`
    first when IMPORTING, but a deployed app carries only the bytecode, and the
    playground and the test lanes carry only the source.  Trying both in this
    order means the same app fingerprints itself consistently wherever it runs,
    and a badge whose editor and poster carry DIFFERENT builds of the artwork
    stamps differently and simply re-renders -- which is the correct outcome and
    is free.

    A relative `root` is fine: the seams pass the install directory they derived
    from `__name__`, and on the device that is an absolute path already.
    """
    for suffix in (".mpy", ".py"):
        try:
            return int(os.stat(root + "/" + name + suffix)[6])
        except _SAFE:
            continue
    return 0


def free_bytes(root="/"):
    """Free bytes on the writable volume, or `UNKNOWN_FREE`.  Never raises.

    `card_bake.free_bytes`, restated rather than imported: this module is
    vendored into three apps and may not depend on any of them.  Unknown means
    DO NOT REFUSE -- a runtime without `statvfs` is one this check cannot speak
    about, and `badge.disk_free()` is deliberately not used because it answers
    14 MB in the browser for a volume the device ships at 1 MB.
    """
    try:
        stat = os.statvfs(root)
        return int(stat[0]) * int(stat[3])
    except (OSError, AttributeError, TypeError, IndexError, ValueError):
        return UNKNOWN_FREE


def space_for(payload, root="/", path=None):
    """`(ok, needed, free)` for a cache of `payload` pixel bytes.

    `ok` is False only when we KNOW it will not fit.  The old file is removed
    before the new one is written, so `needed` is ONE copy plus slack rather
    than two -- which is the difference between 372 KB and 679 KB on a 1 MB
    volume that also holds a 76,816-byte wallpaper film.

    `path` IS THE FILE THIS WRITE IS ABOUT TO REPLACE, AND ITS BYTES ARE
    CREDITED TO `free`.  Until 2026-08-22 they were not, and that made the
    paragraph above a comment rather than a behaviour: `statvfs` still counts
    the old cache as USED, so a volume already holding one 307,264-byte cache
    was asked to clear a second one and refused every rewrite.  DEVICE-PROVEN
    on the reference badge (`bw-1.28.0-3`, 2026-08-22): a `/state` with
    483,328 B free and no cache wrote one; with that cache present, 172,032 B
    free refused **5 attempts out of 5** with `Writer.error == "space"`, at
    every chunk size from 16384 down to 1024
    (`benchmark/results/raw/2026-08-22-overnight/05b-chunk-sweep.log`).

    THE WEARER'S SYMPTOM WAS THE BAD ONE, worse than the sweep's
    inconvenience.  `matches()` refuses a cache written for another entry id,
    so a badge whose first-ever cached skin is still on the volume can never
    cache a second: the first skin hits and EVERY OTHER SKIN FALLS BACK TO A
    LIVE RENDER FOR EVER.  That is `cache_stamp`'s own "everything works,
    nothing is faster" -- the same silent class as the 2026-08-21 stamp bug,
    which is exactly why this one is a stat and not a comment.

    THE CREDIT IS OPT-IN, `path=None` credits nothing, because a caller that
    names no file has not said which one it is about to remove, and defaulting
    to `PATH` would credit a file that some other write is not replacing.
    `Writer` always names its own.  `free` is therefore the figure the decision
    was MADE on, credit included, so `ok == (free >= needed)` stays readable by
    a caller that logs both.

    NOTHING IS REMOVED HERE, and the stat is the whole mechanism.  That is what
    keeps `Writer._begin`'s promise -- a refusal must not destroy the cache it
    was protecting -- literally true rather than merely intended.
    """
    needed = HEADER_BYTES + payload + DISK_SLACK
    free = free_bytes(root)
    if free == UNKNOWN_FREE:
        return (True, needed, free)
    if path is not None:
        try:
            free += int(os.stat(path)[6])
        except _SAFE:
            # No file there, a directory, an unreadable volume: fall back to
            # the `statvfs` figure alone, which is the pre-2026-08-22
            # comparison and errs towards refusing.  A total function on the
            # launch path may not raise for a missing file that is the NORMAL
            # case -- the first cache a badge ever writes has nothing to credit.
            pass
    return (free >= needed, needed, free)


def remove(path=PATH):
    """Delete the cache.  True if a file went away.  Never raises."""
    try:
        os.remove(path)
        return True
    except _SAFE:
        return False


# HOW MUCH OF THE PICTURE ONE `step()` WRITES.  ONE LITTLEFS BLOCK: the writable
# volume allocates in 4 KB blocks (`docs/tufty-architecture.md`), so a chunk that
# is a whole multiple of one never makes the filesystem read-modify-write a block
# it is about to overwrite anyway.
#
# MEASURED ON SILICON, 2026-08-22, AND THIS CONSTANT MOVED BECAUSE OF IT.  It was
# 16384 (four blocks) with a comment admitting nobody had timed it.  Badge
# The reference badge (`bw-1.28.0-3`), HIRES, a 307,264-byte cache, one
# `Writer.step()` timed per row; "body" excludes the header step and the closing
# step (`benchmark/results/raw/2026-08-22-overnight/05c-chunk-sweep.log`):
#
#   chunk    body median   worst step   steps > 22.86 ms frame   calls    wall
#   16384      225.1 ms      278.4 ms         19 of 20             20    4.36 s
#    8192      113.7 ms      160.5 ms         38 of 39             39    4.35 s
#    4096       56.1 ms      101.3 ms         75 of 76             76    4.31 s
#    2048       48.5 ms       59.3 ms         76 of 151           151    4.39 s
#    1024        3.3 ms       58.9 ms         76 of 301           301    4.41 s
#
# THE COST IS PER 4,096-BYTE BLOCK FLUSH, NOT PER BYTE, and that one fact decides
# the number.  307,200 / 4,096 is EXACTLY 75 -- this comment said 76 until
# 2026-08-23, which was a wrong figure standing in for a right one.  The plateau
# IS 76, and it is 75 payload blocks PLUS THE HEADER'S: a 64-byte header write
# dirties a block of its own, so a full save is 76 block flushes however the
# payload is chunked.  76 steps exceed one frame at 2048 AND at 1024: the count
# of expensive steps stops falling the moment the chunk drops below one block.
# At 1024, three steps in four cost ~3.3 ms and the fourth costs ~57 ms.
# `backdrop_cache_probe` emits `blocks_at_shipping_chunk` (75) beside
# `steps_over_frame` (76) so the two numbers can never be conflated again.  So halving the chunk halves the step from 16384 down to
# 4096 and then hits a FLOOR of ~52-59 ms, about two and a half frames.
# **`CHUNK_BYTES` CANNOT BRING A STEP INSIDE ONE FRAME.  THE DIAL DOES NOT
# REACH** -- which kills the remedy `docs/design/backdrop-cache.md` §6(2)
# prescribed, and that section now says so.
#
# 4096 STRICTLY DOMINATES the 16384 it replaces, on every measured axis: the
# lowest total wall of all five rows (4.31 s), a worst step 2.75x smaller
# (278.4 -> 101.3 ms) and a median 4.0x smaller (225.1 -> 56.1 ms).  It is also
# the paragraph above taken to its conclusion -- if the reason to be a whole
# multiple of a block is that the flush is per block, the right multiple is ONE.
#
# 1024 IS NOT THIS FILE'S CHOICE TO MAKE.  It buys the best worst case (58.9 ms)
# and a 3.3 ms median, and it costs 301 stepped frames against 76 -- roughly
# 9.5 s of editor dwell against 4.3 s -- so it trades the wearer's time for
# smoothness.  That is an OWNER decision, it is recorded as one in
# `docs/design/backdrop-cache.md` §6(2), and it must not be landed here.
CHUNK_BYTES = 4096


class Writer:
    """One cache write, STEPPED, so no single frame pays for 300 KB of flash.

    WHY THIS IS NOT ONE `f.write()`.  `docs/badge-button-rules.md` I4: "no
    blocking operation may run while a key is being serviced or real-time
    content is on screen", costed there at up to eight dropped frames for a
    184.90 ms state save against a ~22.8 ms frame.  A HIRES backdrop is
    sixty-four times the bytes of the largest save that table measured, and as
    of 2026-08-22 the silicon number is known: **4.31 s of wall clock**, about
    188 frames' worth, whatever the chunk size (the total barely moves across
    5 chunk sizes -- see `CHUNK_BYTES`).  So the write is broken into chunks the
    caller steps at a rate IT chooses, which is the same shape
    `card_bake.BakeJob` uses for the same reason.  What the chunk buys is the
    size of the WORST step, not the total: it cannot get one inside a frame.

    THE OLD FILE IS REMOVED BEFORE THE FIRST BYTE, a deliberate trade.  The
    cost: a badge interrupted mid-write has no cache and re-renders once,
    exactly as it did before this module existed.  The payoffs are two, and both
    matter on a 1 MB volume -- it never holds two copies of a 307 KB picture, so
    `space_for` only has to clear one (and is handed `self.path` so it CREDITS
    the copy that is about to go, without which the second cache a badge writes
    is refused for ever); and an interrupted write can only ever leave a SHORT
    file, which `load_into` refuses on its `os.stat` gate.

    Nothing here raises.  `ok` is False until the last chunk lands.
    """

    def __init__(self, buffer, entry_id, width, height, mark, pale=False,
                 path=PATH, root="/", chunk=CHUNK_BYTES):
        self.buffer = buffer
        self.path = path
        self.root = root
        self.chunk = chunk if chunk > 0 else CHUNK_BYTES
        self.total = width * height * 4
        self.offset = 0
        self.finished = False
        self.ok = False
        self.error = ""
        self._target = None
        self._head = None
        try:
            self._head = encode_header(entry_id, width, height, mark, pale)
            if len(buffer) != self.total:
                self._fail("buffer")
        except _SAFE as problem:
            self._fail(repr(problem))

    @property
    def progress(self):
        return self.offset / float(self.total) if self.total else 1.0

    @property
    def steps(self):
        """How many `step()` calls a whole write takes, header included."""
        return 1 + (self.total + self.chunk - 1) // self.chunk

    def step(self):
        """Write the header, or one chunk, or close.  Never raises.

        Returns True while there is more to do, so a frame loop reads as
        `if writer.step(): return`.
        """
        if self.finished:
            return False
        try:
            if self._target is None:
                return self._begin()
            return self._chunk()
        except _SAFE as problem:
            self._fail(repr(problem))
            return False

    def _begin(self):
        # `self.path` IS PASSED, and that is the whole of the 2026-08-22 fix:
        # `statvfs` still counts the file on the next line as used, so without
        # crediting it a volume that already holds a cache is asked to clear
        # two copies and refuses every rewrite.  The order below is unchanged
        # and must stay unchanged -- the stat is a READ.
        ok, _needed, _free = space_for(self.total, self.root, self.path)
        if not ok:
            # A REFUSAL MUST NOT BE THE THING THAT DESTROYS THE CACHE IT WAS
            # PROTECTING: nothing has been removed yet at this point.
            self._fail("space")
            return False
        remove(self.path)
        self._target = open(self.path, "wb")
        self._target.write(self._head)
        return True

    def _chunk(self):
        end = self.offset + self.chunk
        if end > self.total:
            end = self.total
        written = self._target.write(memoryview(self.buffer)[self.offset:end])
        if written != end - self.offset:
            self._fail("short")
            return False
        self.offset = end
        if self.offset < self.total:
            return True
        # CLOSED HERE AND NOT IN A `finally`, because a close is a FLUSH and a
        # flush is where a full volume finally reports itself.  A close that
        # raised after `ok` was set would leave this object claiming success
        # about a file that is short.
        self._target.close()
        self._target = None
        self.finished = True
        self.ok = True
        return False

    def abandon(self):
        """Stop, and take the half-written file with us.  Never raises.

        Called when the app is leaving with a write in flight.  What is left
        behind would be refused by `load_into` anyway -- it is short -- but 300
        KB of rubbish nothing will ever read is 300 KB a badge cannot use to
        save a wearer's state.
        """
        if self.finished and self.ok:
            return False
        self._fail("abandoned")
        return True

    def _fail(self, reason):
        self.error = reason
        self.finished = True
        self.ok = False
        if self._target is not None:
            try:
                self._target.close()
            except OSError:
                pass
            self._target = None
            remove(self.path)


def save(buffer, entry_id, width, height, mark, pale=False, path=PATH,
         root="/", chunk=CHUNK_BYTES):
    """`Writer`, driven to completion.  True on success.  Never raises.

    The blocking form, for a caller that has nowhere to spread the cost -- a
    host tool, a test, or a probe measuring what the whole write costs.  A frame
    loop uses `Writer` instead, and the two share every byte of the format
    because one is the other in a loop.
    """
    writer = Writer(buffer, entry_id, width, height, mark, pale, path, root,
                    chunk)
    while writer.step():
        pass
    return writer.ok
