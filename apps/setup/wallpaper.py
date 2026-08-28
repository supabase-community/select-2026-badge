"""PGW1 wallpaper film: the codec that lets a badge be the device background.

THIS FILE IS THE CANONICAL COPY.  EDIT IT HERE AND NOWHERE ELSE.

Vendoring is FORCED on this device: each app installs to its own directory and
only that directory goes on `sys.path`, so there is no /system/lib and
`pg_runtime` inserts exactly one path.  What is not forced is keeping the copies
in sync by hand:

    python3 scripts/sync_ui.py            # refresh every vendored copy
    python3 scripts/sync_ui.py --check    # fail if any has drifted

The copies are byte-identical to this file, which is why they carry this notice
too: if you are reading it in an app directory, your edit belongs in
`shared/wallpaper.py` and will be overwritten here.

WHAT THIS IS FOR.  The home screen is just an app (`/system/apps/menu`) and its
`draw_background()` lives in a `ui.py` we already replace wholesale
(`launcher/host/build_menu.py`).  So the wearer's badge can become the device
wallpaper — but only if the launcher's dependency on the badge app is EXACTLY
ZERO.  The launcher is the one app whose failure needs a USB cable to recover,
so it may not import the badge app, may not know the badge's schema, and may not
run the badge's renderer.  The whole contract is one self-describing file:

    the badge app BAKES a short film of RGBA frames  ->  one bounded file
    the launcher OPENS that file and blits frame k   ->  no imports, no schema

Every failure mode here therefore returns None or False rather than raising.  A
traceback inside `draw_background()` is not a cosmetic bug; it is a badge that
cannot reach its own menu.  `parse_header` is total for the same reason, and its
totality is what the corruption tests actually pin.

FILE FORMAT — PGW1, 16-byte little-endian header, then raw frames:

     0  4  b"PGW1"                    | 11  1  source     0 unknown 1 skin
     4  1  version = 1                |                   2 glyph 3 imported
     5  1  flags   bit0 = legibility  | 12  2  period_ms  33..4000
              treatment already baked | 14  2  recipe_id  fnv1a16 of the bake
     6  2  width   1..160             |                   recipe
     8  2  height  1..120             | 16 ..  frames * width * height * 4,
    10  1  frames  1..24              |        RGBA8888, top-left origin

`source` and `recipe_id` occupy what the design prototype
(`identity/host/proto/wallpaper.py`) left as reserved zero bytes, so a film
written by the prototype still parses here and means exactly what it says:
source "unknown", recipe 0.  No version bump was needed or taken.

`recipe_id` is the point of the header.  It stamps the inputs that decided the
pixels, so the app can answer "is the installed film the one my state
describes?" from a SIXTEEN BYTE read instead of re-baking a film to compare it.
Re-baking costs a rendered surface, RAM for the frames and a flash write; a
`peek()` costs one `open`.

UNKNOWN VALUES ARE KEPT, NOT REJECTED.  An unrecognised `source`, an unknown
`flags` bit and any `recipe_id` all parse fine.  This is the same rule the
identity schema follows for unknown catalogue ids: a film written by a newer
build must still render after a downgrade rather than blanking the home screen,
because none of those three fields decides a single pixel of the blit.  The
fields that DO decide the blit — magic, version, geometry, frame count — are
checked to the byte.
"""

import os


MAGIC = b"PGW1"
VERSION = 1
HEADER_BYTES = 16

# One module owns the path.  The launcher opens this literal; nothing negotiates
# it, because a negotiated path needs a shared schema and that is the dependency
# this whole design exists to avoid.
PATH = "/state/wallpaper.pgw"

# `write` installs through `PATH + TMP_SUFFIX`.  NAMED rather than inlined
# because a second module needs it: `card_bake`'s free-space check clears a
# leftover temp before it measures the volume, and two copies of `".tmp"` is one
# rename away from a check that measures a file the writer no longer uses.
TMP_SUFFIX = ".tmp"

# The badge panel at LORES.  A film may be smaller (the launcher stretches it to
# the screen rect) but never larger: an oversize frame is a decode that allocates
# more than it can blit.
MAX_WIDTH = 160
MAX_HEIGHT = 120

# 24 is the frame-count ceiling in the header, but it is rarely the binding one.
# MAX_BYTES is 25% of the 1 MB writable LittleFS volume and is also about the RAM
# a decoded film may hold, so at full 160x120 (76,800 bytes a frame) only THREE
# frames fit; 24 frames needs a 40x30 film.  Both limits are checked because they
# fail differently: too many frames is a bad header, too many bytes is a bad bake.
MAX_FRAMES = 24
MAX_BYTES = 262144

# 33 ms is one frame at 30 fps — faster than the panel can show and faster than
# the launcher's own loop, so a smaller number can only mean a corrupt header.
# 4 s is the slowest thing that still reads as a moving wallpaper rather than as
# a stuck one.  Both are rejections, not clamps: a period outside this range is
# evidence the bytes are not a film, and a wrong wallpaper is worse than none.
MIN_PERIOD_MS = 33
MAX_PERIOD_MS = 4000
DEFAULT_PERIOD_MS = 100

# bit0: the bake already applied its legibility treatment (scrim, dim, mute), so
# the launcher must NOT apply a second one on top.  Two scrims read as a fault.
FLAG_LEGIBLE = 0x01

SOURCE_UNKNOWN = 0
SOURCE_SKIN = 1
SOURCE_GLYPH = 2
SOURCE_IMPORTED = 3
# Diagnostics only.  Never index this with a raw header byte without a bounds
# check: the whole point of the forward-compatibility rule above is that a
# future build may write a source number this table has never heard of.
SOURCE_NAMES = ("unknown", "skin", "glyph", "imported")

MAX_RECIPE_ID = 0xFFFF

# Everything a total function must swallow.  MicroPython raises the same names.
#
# `LookupError` rather than `IndexError`: subscripting a dict-shaped object with
# a slice raises KeyError, not TypeError, and a test that passed `{}` walked
# straight through an IndexError-only guard and out of `parse_header`.  The base
# class covers both shapes.  `ArithmeticError` covers OverflowError the same way.
# `MemoryError` is here because a 256 KB allocation on a badge with 8.2 MB free
# is not guaranteed, and failing to allocate a wallpaper must degrade to no
# wallpaper rather than to a dead launcher.
_SAFE = (OSError, ValueError, TypeError, LookupError, AttributeError,
         ArithmeticError, MemoryError)


def fnv1a16(data):
    """FNV-1a/32 over `data`, xor-folded to 16 bits.

    Xor-folding rather than a 16-bit prime because FNV is only defined for 32,
    64, ... bit widths; folding is the author's own prescription for a shorter
    hash and it keeps every input byte in play.

    THIS IS A PERSISTED VALUE.  It is written into installed films and compared
    against a number the app stored in `/state/identity.json`, so changing the
    algorithm silently invalidates every film on every badge in the field.  If
    it ever must change, change the format version with it.  `test_wallpaper_
    codec` pins golden vectors for exactly this reason.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    digest = 0x811C9DC5
    for byte in data:
        digest = ((digest ^ byte) * 0x01000193) & 0xFFFFFFFF
    return ((digest >> 16) ^ (digest & 0xFFFF)) & 0xFFFF


def recipe_id(*parts):
    """Stamp the inputs that decide the pixels: `recipe_id("glyph.radar", 3)`.

    Parts are joined with a unit separator so ("ab", "c") and ("a", "bc") do not
    collide, which a plain concatenation would allow.

    FLOATS ARE REFUSED, deliberately and loudly.  `repr(0.1)` is not guaranteed
    to agree between CPython and MicroPython, and a stamp that differs between
    the host lane and the device is worse than no stamp at all: it makes the app
    re-bake on every boot on hardware while every host test passes.  Quantise
    first — identity already stores coordinates as 4-place fractions, so
    `int(round(x * 10000))` is the intended spelling.
    """
    fields = []
    for part in parts:
        if isinstance(part, (bytes, bytearray)):
            fields.append(bytes(part).decode("utf-8"))
        elif isinstance(part, str) or isinstance(part, int):
            # bool is an int subclass and str(True) == "True", which is stable.
            fields.append(str(part))
        else:
            raise TypeError("recipe part is not a str, bytes or int: %r"
                            % (part,))
    return fnv1a16("\x1f".join(fields))


def _u16(buf, offset):
    return buf[offset] | (buf[offset + 1] << 8)


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
    count = view[10]
    period = _u16(view, 12)
    if not 1 <= width <= MAX_WIDTH:
        return None
    if not 1 <= height <= MAX_HEIGHT:
        return None
    if not 1 <= count <= MAX_FRAMES:
        return None
    if not MIN_PERIOD_MS <= period <= MAX_PERIOD_MS:
        return None
    stride = width * height * 4
    payload = stride * count
    if payload > MAX_BYTES:
        return None
    return {
        "version": view[4],
        "flags": view[5],
        "width": width,
        "height": height,
        "frames": count,
        "source": view[11],
        "period_ms": period,
        "recipe_id": _u16(view, 14),
        # Derived, because every caller needs them and every caller would
        # otherwise re-derive them: `stride` sizes one frame's buffer and
        # `total_bytes` is the exact file size a matching film must have.
        "stride": stride,
        "payload_bytes": payload,
        "total_bytes": HEADER_BYTES + payload,
    }


def parse_header(head):
    """Describe a PGW1 header as a dict, or return None.  Never raises.

    Accepts anything indexable as bytes and at least `HEADER_BYTES` long,
    including a whole film — only the first 16 bytes are read.  `None`, a short
    buffer, a `str`, an int, a list holding 300 and a header claiming a 161-pixel
    width are all just None.

    Totality is the contract.  The prototype this grew from was NOT total: it
    reached `bytes(head[0:4])` on a `str` and raised TypeError, which in the
    launcher is a home screen that cannot draw.
    """
    if head is None:
        return None
    try:
        return _describe(head)
    except _SAFE:
        return None


class Wallpaper:
    """A decoded film: `count` ready-to-blit frames and the header that framed
    them.  Constructed only by `decode`/`load`, both of which have already
    validated the header, so nothing here re-checks it."""

    def __init__(self, frames, header):
        self.frames = frames
        self.count = len(frames)
        self.width = header["width"]
        self.height = header["height"]
        self.period_ms = header["period_ms"]
        self.flags = header["flags"]
        self.source = header["source"]
        self.recipe_id = header["recipe_id"]
        # Hoisted out of the flags word because the launcher asks this question
        # once a frame and a named boolean is cheaper to read than a mask.
        self.legible = bool(header["flags"] & FLAG_LEGIBLE)
        self.header = header

    def frame(self, index):
        """Frame `index`, wrapped.  Never raises and never returns None."""
        if self.count == 1:
            return self.frames[0]
        try:
            return self.frames[int(index) % self.count]
        except _SAFE:
            return self.frames[0]

    def frame_at(self, ticks_ms):
        """The frame this millisecond clock selects.

        `badge.ticks` is a raw unsigned 32-bit millisecond counter that wraps
        after ~49.7 days (docs/engineering-findings.md).  Wrapping costs one
        short or long frame every seven weeks, which is not worth a modulo
        arithmetic scheme to avoid.  Python's `%` is non-negative for a positive
        divisor, so even a negative clock lands on a real index.
        """
        if self.count == 1:
            return self.frames[0]
        try:
            return self.frames[(int(ticks_ms) // self.period_ms) % self.count]
        except _SAFE:
            return self.frames[0]

    def blit(self, target, dest, index=0):
        """Blit frame `index` onto `target` at `dest`.  Returns True if drawn.

        `target` is the injected surface (`screen`) and `dest` whatever that
        surface's `blit` accepts — a `vec2` for a 1:1 film, a `rect` to stretch a
        smaller one to the panel.  Neither is constructed here: this module has
        no Badgeware globals, which is what lets it be tested under bare CPython.

        A failed blit is swallowed on purpose.  The caller is `draw_background()`
        and there is no recovery from a raising home screen except a USB cable.
        """
        try:
            target.blit(self.frame(index), dest)
            return True
        except _SAFE:
            return False

    def blit_at(self, target, dest, ticks_ms):
        """`blit`, selecting the frame from a millisecond clock."""
        try:
            target.blit(self.frame_at(ticks_ms), dest)
            return True
        except _SAFE:
            return False


def decode(data, image_ctor):
    """Decode a whole film held in memory, or return None.  Never raises.

    `image_ctor` is INJECTED — on the device it is Badgeware's `image(w, h, buf)`
    and in tests it is a plain class that keeps the bytes.  That injection is the
    reason this module imports nothing from the runtime and runs under
    `python3 -I`.

    Trailing bytes after the declared payload are IGNORED rather than treated as
    corruption: they cannot affect a single blitted pixel, and the exact-size
    check that does matter belongs to the app, which has `total_bytes` from
    `parse_header` and one `os.stat` away from a definitive answer.  Being
    strict here would only turn a cosmetically odd file into a blank home
    screen, which is the trade this module exists to refuse.
    """
    header = parse_header(data)
    if header is None:
        return None
    try:
        view = memoryview(data)
        if len(view) < header["total_bytes"]:
            return None
        stride = header["stride"]
        frames = []
        offset = HEADER_BYTES
        for _ in range(header["frames"]):
            frames.append(image_ctor(header["width"], header["height"],
                                     bytearray(view[offset:offset + stride])))
            offset += stride
        return Wallpaper(frames, header)
    except _SAFE:
        return None


def load(image_ctor, path=PATH):
    """Load the installed film, or return None.  Never raises.

    The constructor comes first so the launcher's hook is the one-liner
    `wallpaper.load(image)`; `decode` takes its bytes first because that reads
    better for everything else.

    Frames are read one at a time into their own buffer rather than slurping the
    file, so peak RAM is the film plus ONE frame instead of twice the film.
    """
    source = None
    try:
        source = open(path, "rb")
        header = parse_header(source.read(HEADER_BYTES))
        if header is None:
            return None
        stride = header["stride"]
        frames = []
        for _ in range(header["frames"]):
            buffer = bytearray(stride)
            # A short read is the truncation gate: the header promised bytes the
            # file does not have, so the file is not the film it claims to be.
            if source.readinto(buffer) != stride:
                return None
            frames.append(image_ctor(header["width"], header["height"], buffer))
        return Wallpaper(frames, header)
    except _SAFE:
        return None
    finally:
        if source is not None:
            try:
                source.close()
            except OSError:
                pass


def peek(path=PATH):
    """The installed film's header, or None.  Never raises, reads 16 bytes.

    This is the cheap half of the recipe stamp: comparing `peek()["recipe_id"]`
    against `state["home"]["recipe"]` tells the app whether the installed film is
    the one its state describes, without decoding or re-baking anything.
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


def encode(frames, width, height, period_ms=DEFAULT_PERIOD_MS, flags=0,
           source=SOURCE_UNKNOWN, recipe_id=0):
    """Encode RGBA8888 frame buffers into one PGW1 film and return `bytes`.

    Unlike everything above, this RAISES ValueError on bad input, and the
    asymmetry is the design: a reader that raises breaks the launcher, while a
    writer that quietly clamps produces a film whose header lies about its own
    pixels.  The one guarantee that matters is the join between them — anything
    `encode` accepts, `parse_header` accepts, and `test_wallpaper_codec` pins it.

    `recipe_id` is refused rather than truncated when it exceeds 16 bits for the
    same reason: `identity_model.RECIPE_MAX` is (1 << 30) - 1, so a caller that
    forwards a stored recipe straight from state can hand us a number this field
    cannot hold, and a silently truncated stamp compares unequal for ever.
    """
    try:
        frames = list(frames)
    except _SAFE:
        # ValueError, not the TypeError this would raise on its own: the whole
        # writer reports one exception type, so a baker wraps one `except`.
        raise ValueError("frames is not a sequence of buffers")
    if not isinstance(width, int) or not isinstance(height, int):
        raise ValueError("width and height must be ints")
    if not 1 <= width <= MAX_WIDTH:
        raise ValueError("width %r is outside 1..%d" % (width, MAX_WIDTH))
    if not 1 <= height <= MAX_HEIGHT:
        raise ValueError("height %r is outside 1..%d" % (height, MAX_HEIGHT))
    if not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError("frame count %d is outside 1..%d"
                         % (len(frames), MAX_FRAMES))
    if not isinstance(period_ms, int):
        raise ValueError("period_ms must be an int")
    if not MIN_PERIOD_MS <= period_ms <= MAX_PERIOD_MS:
        raise ValueError("period_ms %r is outside %d..%d"
                         % (period_ms, MIN_PERIOD_MS, MAX_PERIOD_MS))
    if not isinstance(flags, int) or not 0 <= flags <= 0xFF:
        raise ValueError("flags %r does not fit one byte" % (flags,))
    if not isinstance(source, int) or not 0 <= source <= 0xFF:
        raise ValueError("source %r does not fit one byte" % (source,))
    if not isinstance(recipe_id, int) or not 0 <= recipe_id <= MAX_RECIPE_ID:
        raise ValueError("recipe_id %r does not fit two bytes" % (recipe_id,))

    stride = width * height * 4
    total = stride * len(frames)
    if total > MAX_BYTES:
        raise ValueError("film is %d bytes, over the %d byte budget"
                         % (total, MAX_BYTES))

    out = bytearray(HEADER_BYTES + total)
    out[0:4] = MAGIC
    out[4] = VERSION
    out[5] = flags
    out[6] = width & 0xFF
    out[7] = (width >> 8) & 0xFF
    out[8] = height & 0xFF
    out[9] = (height >> 8) & 0xFF
    out[10] = len(frames)
    out[11] = source
    out[12] = period_ms & 0xFF
    out[13] = (period_ms >> 8) & 0xFF
    out[14] = recipe_id & 0xFF
    out[15] = (recipe_id >> 8) & 0xFF

    offset = HEADER_BYTES
    for index, frame in enumerate(frames):
        try:
            length = len(frame)
        except _SAFE:
            raise ValueError("frame %d is not a buffer" % index)
        if length != stride:
            raise ValueError("frame %d is %d bytes, expected %d"
                             % (index, length, stride))
        try:
            out[offset:offset + stride] = bytes(frame)
        except _SAFE:
            raise ValueError("frame %d is not RGBA bytes" % index)
        offset += stride
    return bytes(out)


def _ensure_parent(path):
    # `"wallpaper.pgw".rsplit("/", 1)[0]` is `"wallpaper.pgw"`, so a bare
    # filename without this guard makes a DIRECTORY named after the file and
    # then fails to write it.  Every device path is absolute, which is exactly
    # why the case is easy to leave in and hard to notice.
    if "/" not in path:
        return
    parent = path.rsplit("/", 1)[0]
    if not parent:
        return
    try:
        os.mkdir(parent)
    except OSError:
        pass


def write(data, path=PATH):
    """Install a film atomically: temp -> flush -> sync -> rename.

    The rename is the atom, which is the only sequence that survives power loss
    on LittleFS (`identity_store` writes state the same way).  It matters more
    here than for state: a torn film is read by the LAUNCHER, and half a
    wallpaper on the home screen is the failure that needs USB to fix.

    The bytes are CHECKED before they are installed, exactly and not loosely.
    This is the only chokepoint in front of a file the launcher will open, and
    the launcher cannot report a complaint — it just falls back to its own
    background and the wearer sees no badge and no reason.  So a film that
    `parse_header` would refuse, or one whose payload is not exactly the length
    its header claims, never reaches the disk.

    ValueError for bytes that are not a film; OSError propagates from the write.
    A failed bake must be visible to the app that asked for it, and the
    previously installed film is untouched either way.
    """
    header = parse_header(data)
    if header is None:
        raise ValueError("refusing to install bytes that are not a PGW1 film")
    if len(data) != header["total_bytes"]:
        raise ValueError("film is %d bytes, its header describes %d"
                         % (len(data), header["total_bytes"]))
    _ensure_parent(path)
    temporary = path + TMP_SUFFIX
    try:
        with open(temporary, "wb") as output:
            output.write(data)
            output.flush()
        sync = getattr(os, "sync", None)
        if sync is not None:
            sync()
        os.rename(temporary, path)
    except OSError:
        # A FAILED WRITE MAY NOT LEAVE ITS TEMP BEHIND, and on a 1 MB volume
        # that is not tidiness.  `with` closes the file but nothing unlinks it,
        # so an ENOSPC used to strand up to 76,816 bytes under a name nothing
        # ever looks at again -- and the next save then failed its own free-space
        # check for a reason nothing on the panel could explain.  The failure
        # still propagates; only the wreckage is cleared.
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


def remove(path=PATH):
    """Uninstall the film.  True if it is gone, False if it could not be.

    Turning the wallpaper off has to delete the file, not just clear a flag in
    the app's state: the launcher never reads that state, so a film left behind
    keeps drawing a badge the wearer switched off.
    """
    try:
        os.remove(path)
        return True
    except OSError:
        try:
            os.stat(path)
        except OSError:
            # Already absent, which is the state the caller asked for.
            return True
        return False
