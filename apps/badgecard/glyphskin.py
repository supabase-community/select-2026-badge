"""GPD1 glyph skins: recorded glyph-engine animations as badge backgrounds.

Pure Python, ZERO imports, no Badgeware globals.  Identical under CPython (the
fast lane) and MicroPython (the badge).  Everything the runtime supplies -- the
image constructor, the vec2 constructor, the destination surface -- is INJECTED,
which is the only reason this file can be unit-tested without a device.

WHY THIS EXISTS INSTEAD OF IMPORTING THE GLYPH APP'S PLAYER.  `glyph2x_lab`
reaches `/system/apps/glyph` through `sys.path.insert` (`glyph2x_lab/badge/
glyph2x_lab/__init__.py:25`), so it refuses to start unless a DIFFERENT app
happens to be installed.  `identity` may not inherit that: its HOME key can
launch anything in any order and its background is the wearer's own badge.  So
the deck is re-encoded into a format this module can play alone, and this module
imports nothing at all -- `test_glyphskin.py` asserts the import list is empty
and imports it under `python3 -I` with only its own directory on `sys.path`.

Re-encoding also removes work the badge should never have been doing.  The glyph
app's player scans all 384 cells of every frame in Python looking for what
changed (2.790 ms median on device, every frame, whatever the content).  A
recorded stream's diff is a STATIC PROPERTY OF THE ASSET, so the host already
knows the answer; GPD1 stores it.  It is also smaller: the largest 2x `.gpa` is
549 KB held whole in RAM, the largest `.gpd` is 41 KB.

TOTALITY IS THE CONTRACT, for the same reason it is in `shared/wallpaper.py`.
This animation plays BEHIND THE WEARER'S NAME.  A traceback out of a draw call
is not a cosmetic bug, it is a badge that shows nothing at a conference.  So
every reader here -- `parse_header`, `decode`, `load`, `open_pack`,
`SkinPack.read`, `painter`, `skin`, `SkinPainter.advance` -- returns None, False
or zero rather than raising, and `test_glyphskin.py` names each failure mode as
its own gate: absent file, bad magic, wrong header length, truncated payload,
table/payload length mismatch, unsorted table, zero frames, absurd dimensions,
a grid that does not match its cell count, a glyph id past the mask bank, a cell
index past the grid, and a surface too small to hold the grid.

Only the WRITERS raise: `SkinPainter.__init__` refuses geometry it cannot paint,
because handing it a 3-pixel surface is a programming error and not a corrupt
file.  `painter()` is the total factory in front of it, exactly as
`wallpaper.decode` fronts `Wallpaper.__init__`.

THE PAINT MODEL is the retained-surface pattern measured on hardware
(`benchmark/results/reports/2026-08-14-v3.0.1-glyph-backgrounds.md`): the
animation is diff-painted into ONE offscreen RGBA image which the app blits
whole before drawing its foreground.  The app therefore pays no extra
full-screen work, because a badge already blits a background image every frame.

GPD1 LAYOUT (little-endian), fixed 64-byte header:

     0   4  magic b"GPD1"          | 20  24  technique id, ASCII, zero padded
     4   2  header length (64)     | 44   4  offset of the record-offset table
     6   1  grid columns           | 48   4  offset of the delta payload
     7   1  grid rows              | 52   2  peak BODY record length, entries
     8   2  frame count N          | 54   2  mean body entries x 100
    10   2  cell count (cols*rows) | 56   2  loop-closing record length
    12   4  loop period, ENGINE us | 58   6  reserved (zero)
    16   2  engine speed x 1000    |
    18   1  loop class 0/1/2       |
    19   1  flags: bit0 inverse    |

Then (N + 2) x u32 record offsets, then the payload.  Record r spans
[table[r], table[r+1]) and holds 4-byte entries: u16 cell index, u8 glyph id,
u8 style.  Record 0 is a full keyframe.  Record r in 1..N-1 turns frame r-1 into
frame r.  Record N turns frame N-1 back into frame 0, so the loop closes without
a special case and without the player ever comparing two frames.

Fields 52/54/56 exist so a budget can be SIZED FROM THE HEADER, with no scan of
the payload at load time.  `budget_for()` is the whole use.

GPK1 LAYOUT -- one pack file instead of twenty-two loose ones:

     0   4  magic b"GPK1"          | 16  ..  count x 32-byte directory entries
     4   2  header length (16)     |          0  24  member name, zero padded
     6   2  member count           |         24   4  offset within the payload
     8   4  directory offset (16)  |         28   4  member length
    12   4  payload offset         |

Flash cost on this device is FILE COUNT, not bytes: roughly 4 KB of FAT cluster
overhead per file (`docs/badge-app-quickstart.md` s7).  The deck is 18 streams,
two mask banks and three treatment LUTs -- twenty-three files and about 92 KB of
pure overhead against 385 KB of content, to serve an app that plays exactly ONE
stream at a time.  Packing them costs a 736-byte directory and one extra `open`
per load, and gives the overhead back.  RAM is unchanged, because `read()` seeks
to the member and reads only it: peak resident cost is one stream (2-41 KB) plus
the one mask bank the cell needs, never the pack.

RESOLUTION IS A PARAMETER OF THIS MODULE AND NOTHING ELSE.  It contains no
screen size at all -- a test walks the AST and fails on any numeric literal that
is one.  The cell comes from the surface, the mask bank comes from the cell, and
a grid that will not fit is refused by `SkinPainter`, which is the only party
that has seen the surface.  That is what lets one player serve a LORES 160x120
build and a HIRES 320x240 one from the same bytes and the same call.
"""

MAGIC = b"GPD1"
HEADER_BYTES = 64
ENTRY_BYTES = 4
TABLE_OFFSET = HEADER_BYTES

PACK_MAGIC = b"GPK1"
PACK_HEADER_BYTES = 16
PACK_ENTRY_BYTES = 32
PACK_NAME_BYTES = 24

# The app directory is the process cwd on the device, which is why `pet` and
# `namebadge` name their sheets relatively.  The absolute form is the fallback
# for anything that runs from elsewhere (a probe over `mpremote`, a host tool).
PACK_PATH = "assets/glyphskins.gpk"
PACK_FALLBACK = "/system/apps/identity/assets/glyphskins.gpk"

GPD_SUFFIX = ".gpd"
# The catalogue spells these `glyph.radar`; the pack spells them `radar.gpd`.
# One place knows both, so nothing else has to.
ID_PREFIX = "glyph."

# RESOLUTION IS A PARAMETER, NOT A CONSTANT.  Nothing here knows about 160x120:
# the cell size is `surface.width // stream.columns`, so the same stream fills a
# LORES 160x120 canvas at 5x10 cells and a HIRES 320x240 one at 10x20.
#
# Which mask bank to sample is then decided BY THAT CELL, and it matters more
# than it looks.  The 5x10 bank is the exact 2x2 block mean of the 10x20 bank
# (verified: worst per-pixel delta 1, which is rounding), so scaling it back up
# by nearest neighbour cannot recover what the mean destroyed -- 16.1% of pixels
# come out wrong, mean absolute coverage error 16.3/255, and on screen the
# letterforms go from crisp to blobby.  At HIRES the 10x20 bank is the AUTHORED
# geometry for a 10x20 cell and costs no resampling at all.
#
# Ordered highest density first: take the finest authored bank the cell can hold
# and nearest-neighbour up from there only if it must.
MASK_GEOMETRY = ((10, 20), (5, 10))
MASK_MEMBERS = {(10, 20): "masks-10x20.pfb", (5, 10): "masks-5x10.pfb"}
MASK_WIDTH = 5
MASK_HEIGHT = 10

LUT_BYTES = 10240
# THE THREE SHIPPED PALETTES, AND THIS MODULE IS WHERE THE VOCABULARY LIVES.
# `identity_catalogue` used to propose one of these words per entry; it no
# longer carries the column, because every glyph entry named `VIVID` and nothing
# was choosing.  The names stay here because a caller still has to say which
# table it wants, and a bare `"vivid"` at three call sites is three chances to
# misspell one into the silent fallback below.
#
# `VIVID` is the byte-exact full production Glyph palette and is what a poster
# or a card bake wants: the owner rejected the ghosted deck on glass on
# 2026-08-16 as barely visible.  `MUTED` and `GHOST` keep their baked holdbacks
# and are reachable through `identity`'s wearer-facing FINISH row, which is the
# one place a human still picks between them.  Transforming a holdback into the
# LUT is free per frame; painting a scrim over the finished background is not.
VIVID = "vivid"
MUTED = "muted"
GHOST = "ghost"
LUT_MEMBERS = {
    VIVID: "lut-vivid.bin",
    MUTED: "lut-muted.bin",
    GHOST: "lut-ghost.bin",
}
# An unknown treatment gets the defensive darkest table: the app cannot infer
# what a future word means.
DEFAULT_TREATMENT = GHOST

# WHETHER A GRID IS ABSURD IS A QUESTION ABOUT THE SURFACE, NOT ABOUT THIS
# MODULE.  An earlier draft rejected any grid finer than 160x120 in the header,
# which quietly made the codec LORES-only: the same stream is perfectly
# paintable on a 320x240 HIRES canvas.  The header therefore checks only that a
# grid exists and matches its own cell count -- both dimensions are single
# bytes, so 255x255 is the format's own ceiling -- and `SkinPainter` refuses the
# grid it cannot fit, because it is the only party that has seen the surface.
# 256 KB is the wallpaper codec's ceiling and the same reasoning applies: a
# member length larger than this is a corrupt directory, and attempting the
# allocation to find out is how a bad file becomes a MemoryError on stage.
MAX_MEMBER_BYTES = 262144

LOOP_EXACT = 0
LOOP_STRUCTURAL = 1
LOOP_NONE = 2

INVERSE_FLAG = 0x80
COLOR_MASK = 0x0F

# A skin may not stall the badge.  When playback has fallen this many authored
# frames behind, the per-frame budget DOUBLES until it has caught up -- and it
# is never lifted further, so the worst frame this module can ever cost stays
# bounded at 2 x budget cells whatever the clock does.  Smoothing one big
# loop-seam record over several frames is by itself enough to reach the limit on
# a 30.56 fps asset at a 29.24 fps app rate (fluid-field does exactly that),
# which is precisely the case where a "drain everything" escape hatch turned
# into a 127-cell frame in the design prototype.
LAG_LIMIT = 8
LAG_MULTIPLIER = 2

# budget = min(96, max(48, 2 * mean_body_entries)), read straight off the
# header.  The floor guarantees a drain rate of at least 2x the asset's
# sustained cell rate, so playback can never fall permanently behind; the
# ceiling caps one frame at 96 cells = 7.68 ms at the measured 0.080 ms warm
# incremental cell.
MIN_BUDGET = 48
MAX_BUDGET = 96

# The tile cache is what makes a warm cell cost a blit instead of a composite,
# and it is the one thing here that grows.  A cap in BYTES rather than in tiles
# scales with the canvas by itself: 1,310 tiles at a LORES 5x10 cell (200 B
# each), 327 at a HIRES 10x20 one (800 B each).
#
# A SINGLE skin never comes near it -- the busiest asset in the deck uses 117
# distinct keys, so 23 KB at LORES and 94 KB at HIRES.  The ceiling is sized for
# a BROWSE instead, where the wearer scrubs the catalogue through one retargeted
# painter and the cache accumulates across techniques: the whole eighteen-entry
# deck is 323 distinct keys, which fits at both resolutions and is what makes
# scrubbing back up the list free.  256 KB is about 3% of the ~8.2 MB free with
# an app loaded, and it is 323 small allocations rather than one big one, so it
# is nowhere near the 384 KB single-block wall the stress pass found.
#
# Overflow clears the WHOLE cache rather than evicting one entry: no LRU
# bookkeeping in the paint path, the cost is bounded and rare, and the next
# frames simply repay the cold cells they actually need.
MAX_TILE_BYTES = 262144

# A painter that has raised this many times stops trying.  Transient failures
# (one MemoryError while a tile is materialised) heal on the next frame; a
# surface that raises every time would otherwise cost a full budget of failed
# blits forever, which is the stall this module exists to prevent.
ERROR_LIMIT = 3

# Everything a total function must swallow.  MicroPython raises the same names.
# `LookupError` rather than `IndexError` because subscripting a dict-shaped
# object with a slice raises KeyError; `ArithmeticError` covers OverflowError;
# `MemoryError` is here because a tile allocation is not guaranteed and failing
# to allocate one must degrade to a still background, not to a dead app.
_SAFE = (OSError, ValueError, TypeError, LookupError, AttributeError,
         ArithmeticError, MemoryError)


def _u16(data, offset):
    return data[offset] | (data[offset + 1] << 8)


def _u32(data, offset):
    return (data[offset] | (data[offset + 1] << 8)
            | (data[offset + 2] << 16) | (data[offset + 3] << 24))


def technique_of(entry_id):
    """`"glyph.radar"` -> `"radar"`; anything else is returned unchanged."""
    try:
        if entry_id.startswith(ID_PREFIX):
            return entry_id[len(ID_PREFIX):]
        return entry_id
    except _SAFE:
        return ""


def mask_geometry_for(cell_w, cell_h):
    """The mask geometry to sample a `cell_w` x `cell_h` cell with.

    LORES 160x120 gives a 32x12 stream 5x10 cells and picks the 5x10 bank;
    HIRES 320x240 gives it 10x20 cells and picks the 10x20 bank, which is that
    cell's authored geometry and needs no resampling at all.
    """
    for geometry in MASK_GEOMETRY:
        if cell_w >= geometry[0] and cell_h >= geometry[1]:
            return geometry
    return MASK_GEOMETRY[-1]


def cell_size(stream, surface):
    """The cell this stream gets on this surface, or None.  Never raises."""
    try:
        cell = (surface.width // stream.columns, surface.height // stream.rows)
    except _SAFE:
        return None
    return cell if cell[0] > 0 and cell[1] > 0 else None


# ---------------------------------------------------------------------------
# GPD1: header, stream, decode
# ---------------------------------------------------------------------------

def _describe(data):
    if len(data) < HEADER_BYTES:
        return None
    if bytes(data[0:4]) != MAGIC:
        return None
    if _u16(data, 4) != HEADER_BYTES:
        return None
    columns = data[6]
    rows = data[7]
    frames = _u16(data, 8)
    cells = _u16(data, 10)
    period = _u32(data, 12)
    speed = _u16(data, 16)
    if columns < 1 or rows < 1:
        return None
    if cells != columns * rows:
        return None
    if frames < 1:
        return None
    if period < 1 or speed < 1:
        return None
    table = _u32(data, 44)
    payload = _u32(data, 48)
    if table != TABLE_OFFSET:
        return None
    span = ENTRY_BYTES * (frames + 2)
    if payload != table + span:
        return None
    # The technique id is a LABEL: it names the artwork in a log line and picks
    # nothing.  Undecodable bytes therefore degrade to "" rather than sinking
    # the whole header, which is the same rule `wallpaper.parse_header` applies
    # to an unrecognised `source`.
    try:
        technique = bytes(data[20:44]).rstrip(b"\x00").decode()
    except _SAFE:
        technique = ""
    return {
        "columns": columns,
        "rows": rows,
        "frames": frames,
        "cells": cells,
        "period_engine_us": period,
        "speed_milli": speed,
        "loop_class": data[18],
        "flags": data[19],
        "technique": technique,
        "peak_entries": _u16(data, 52),
        "mean_entries_x100": _u16(data, 54),
        "wrap_entries": _u16(data, 56),
        # Derived, because every caller needs them and would otherwise
        # re-derive them from three fields each.
        "table_offset": table,
        "table_bytes": span,
        "payload_offset": payload,
        "period_wall_ms": period // speed,
    }


def parse_header(head):
    """Describe a GPD1 header as a dict, or return None.  Never raises.

    Reads only the first 64 bytes, so a header-only read is enough.  `None`, a
    short buffer, a `str`, an int, a list holding 300 and a header claiming 200
    columns are all just None.
    """
    if head is None:
        return None
    try:
        return _describe(head)
    except _SAFE:
        return None


class SkinStream:
    """One parsed GPD1 asset (2-41 KB across the whole deck).

    Constructed only by `decode`, which has already validated the header, the
    offset table and the total length -- so nothing here re-checks and nothing
    here raises.
    """

    def __init__(self, view, header):
        self._view = view
        self.header = header
        self.columns = header["columns"]
        self.rows = header["rows"]
        self.frame_count = header["frames"]
        self.cell_count = header["cells"]
        self.period_engine_us = header["period_engine_us"]
        self.speed_milli = header["speed_milli"]
        self.loop_class = header["loop_class"]
        self.flags = header["flags"]
        self.technique = header["technique"]
        self.peak_entries = header["peak_entries"]
        self.mean_entries_x100 = header["mean_entries_x100"]
        self.wrap_entries = header["wrap_entries"]
        self.period_wall_ms = header["period_wall_ms"]
        self._table = header["table_offset"]
        self._payload = header["payload_offset"]

    @property
    def mean_entries(self):
        return self.mean_entries_x100 / 100.0

    @property
    def record_count(self):
        """Records, not frames: N bodies plus the loop-closing one."""
        return self.frame_count + 1

    def record(self, index):
        """Delta record `index`.  `index == frame_count` closes the loop.

        Out of range folds to record 0 rather than raising: a player that has
        lost track of where it is should repaint the keyframe, not stop.
        """
        if index < 0 or index > self.frame_count:
            index = 0
        base = self._table + index * ENTRY_BYTES
        start = _u32(self._view, base)
        stop = _u32(self._view, base + ENTRY_BYTES)
        return self._view[self._payload + start:self._payload + stop]

    def frame_at(self, elapsed_ms, time_scale_milli=1000):
        """The authored frame this wall clock selects.  Never raises.

        The mapping is STATELESS and integer-only, which is what makes playback
        deterministic and self-correcting: the same elapsed time always gives
        the same frame, a dropped frame is skipped rather than accumulated, and
        two badges started together stay in step.  There is no RNG anywhere in
        the playback path.
        """
        try:
            elapsed = int(elapsed_ms)
        except _SAFE:
            return 0
        if elapsed < 0:
            elapsed = 0
        try:
            scale = int(time_scale_milli)
        except _SAFE:
            scale = 1000
        if scale < 1:
            scale = 1000
        engine_us = elapsed * self.speed_milli * scale // 1000
        return (engine_us * self.frame_count
                // self.period_engine_us) % self.frame_count

    def keys(self):
        """Every distinct (glyph, style) the stream ever paints.

        One pass over the payload -- 900 to 10,200 entries depending on the
        asset -- so this is a LOAD-TIME cost paid to hand `warm()` a complete
        list.  Never raises; a short trailing fragment is ignored.
        """
        found = []
        seen = {}
        try:
            for index in range(self.frame_count + 1):
                record = self.record(index)
                for offset in range(0, len(record) - ENTRY_BYTES + 1,
                                    ENTRY_BYTES):
                    key = (record[offset + 2], record[offset + 3])
                    if key not in seen:
                        seen[key] = True
                        found.append(key)
        except _SAFE:
            pass
        return tuple(found)


def decode(data):
    """Decode GPD1 bytes into a `SkinStream`, or return None.  Never raises.

    The offset table is validated in full -- monotonic, 4-byte aligned, first
    entry zero, last entry exactly the payload length.  The design prototype
    checked only the last entry, which left three ways to walk off the end of a
    corrupt file: a descending pair produces a negative-length slice, an
    unaligned entry makes the last record read one byte past its end, and a
    non-zero first entry silently drops the head of the keyframe.
    """
    header = parse_header(data)
    if header is None:
        return None
    try:
        view = memoryview(data)
        payload = header["payload_offset"]
        if len(view) < payload:
            return None
        table = header["table_offset"]
        previous = 0
        for index in range(header["frames"] + 2):
            value = _u32(view, table + index * ENTRY_BYTES)
            if value % ENTRY_BYTES:
                return None
            if index == 0:
                if value:
                    return None
            elif value < previous:
                return None
            previous = value
        if len(view) != payload + previous:
            return None
        return SkinStream(view, header)
    except _SAFE:
        return None


def load(path):
    """Decode a standalone `.gpd` file, or return None.  Never raises."""
    source = None
    try:
        source = open(path, "rb")
        return decode(source.read())
    except _SAFE:
        return None
    finally:
        if source is not None:
            try:
                source.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# GPK1: the one-file asset pack
# ---------------------------------------------------------------------------

class SkinPack:
    """A pack's DIRECTORY, held open by path rather than by handle.

    The directory is ~600 bytes; the payload is 384 KB and is never resident.
    `read()` re-opens, seeks to the member and reads exactly its length, so the
    peak cost of playing a skin is one stream, and switching skins does not
    accumulate.
    """

    def __init__(self, path, entries, payload_offset):
        self.path = path
        self.entries = entries          # ((name, offset, length), ...)
        self._payload = payload_offset

    def names(self):
        return tuple(entry[0] for entry in self.entries)

    def techniques(self):
        """Playable technique ids, in pack order."""
        cut = len(GPD_SUFFIX)
        return tuple(entry[0][:-cut] for entry in self.entries
                     if entry[0].endswith(GPD_SUFFIX))

    def _find(self, name):
        for entry in self.entries:
            if entry[0] == name:
                return entry
        return None

    def size(self, name):
        """The member's declared length, or -1 if the pack has no such member."""
        entry = self._find(name)
        return entry[2] if entry is not None else -1

    def read(self, name):
        """One member's bytes, or None.  Never raises.  `None` name is None.

        A short read is the truncation gate: the directory promised bytes the
        file does not have, so the file is not the pack it claims to be.
        """
        entry = self._find(name)
        if entry is None:
            return None
        if entry[2] < 1 or entry[2] > MAX_MEMBER_BYTES:
            return None
        source = None
        try:
            source = open(self.path, "rb")
            source.seek(self._payload + entry[1])
            buffer = source.read(entry[2])
            if buffer is None or len(buffer) != entry[2]:
                return None
            return buffer
        except _SAFE:
            return None
        finally:
            if source is not None:
                try:
                    source.close()
                except OSError:
                    pass

    def stream(self, technique):
        """A `SkinStream` for `"radar"` or `"glyph.radar"`, or None."""
        return decode(self.read(technique_of(technique) + GPD_SUFFIX)
                      or b"")

    def masks(self, cell_w=MASK_WIDTH, cell_h=MASK_HEIGHT):
        """The mask bank for a cell this size, or None.

        Only the chosen bank is read, so a LORES app holds 5,100 bytes of masks
        and a HIRES one 20,400 -- never both.
        """
        return self.read(MASK_MEMBERS.get(mask_geometry_for(cell_w, cell_h)))

    def lut(self, treatment=DEFAULT_TREATMENT):
        """A treatment table, falling back to the darkest one we ship.

        An unknown treatment is not an error: `identity_catalogue` may grow a
        fourth word before this pack is rebuilt, and the safe answer to "I do
        not know how bright you meant" is the dimmest table, not no background.
        """
        member = LUT_MEMBERS.get(treatment)
        if member is None:
            member = LUT_MEMBERS[DEFAULT_TREATMENT]
        return self.read(member)


def _open_pack(path):
    source = None
    try:
        source = open(path, "rb")
        head = source.read(PACK_HEADER_BYTES)
        if head is None or len(head) < PACK_HEADER_BYTES:
            return None
        if bytes(head[0:4]) != PACK_MAGIC:
            return None
        if _u16(head, 4) != PACK_HEADER_BYTES:
            return None
        count = _u16(head, 6)
        directory = _u32(head, 8)
        payload = _u32(head, 12)
        if count < 1 or directory != PACK_HEADER_BYTES:
            return None
        if payload != directory + count * PACK_ENTRY_BYTES:
            return None
        raw = source.read(count * PACK_ENTRY_BYTES)
        if raw is None or len(raw) != count * PACK_ENTRY_BYTES:
            return None
        entries = []
        for index in range(count):
            base = index * PACK_ENTRY_BYTES
            label = bytes(raw[base:base + PACK_NAME_BYTES]).rstrip(b"\x00")
            if not label:
                return None
            entries.append((label.decode(),
                            _u32(raw, base + PACK_NAME_BYTES),
                            _u32(raw, base + PACK_NAME_BYTES + 4)))
        return SkinPack(path, tuple(entries), payload)
    except _SAFE:
        return None
    finally:
        if source is not None:
            try:
                source.close()
            except OSError:
                pass


def open_pack(path=None):
    """Open the asset pack, or return None.  Never raises.

    With no argument it tries the app-relative path and then the installed
    absolute one, so the same call works from the app, from a host test and
    from an `mpremote` probe.
    """
    if path is not None:
        return _open_pack(path)
    for candidate in (PACK_PATH, PACK_FALLBACK):
        pack = _open_pack(candidate)
        if pack is not None:
            return pack
    return None


# ---------------------------------------------------------------------------
# playback
# ---------------------------------------------------------------------------

def budget_for(stream):
    """Cells this asset may repaint per frame, sized from its own header.

    No payload scan: fields 52/54/56 exist for exactly this.  Never raises;
    anything that is not a stream gets the floor.
    """
    try:
        return min(MAX_BUDGET, max(MIN_BUDGET,
                                   2 * stream.mean_entries_x100 // 100))
    except _SAFE:
        return MIN_BUDGET


class SkinPainter:
    """Paints a GPD1 stream into a retained RGBA surface, under a cell budget.

    `surface` is the app's own background image.  The app keeps blitting it
    exactly as it does for a static skin, so an animated glyph skin adds no
    blit and no clear to the app's frame -- only the deltas.

    This constructor RAISES on geometry it cannot paint.  Use `painter()` for
    the total version; the asymmetry is deliberate and is the same one
    `shared/wallpaper.py` draws between `encode` and `decode`.
    """

    def __init__(self, stream, mask_bank, rgba_lut, surface, image_ctor,
                 vec2_ctor, mask_width=MASK_WIDTH, mask_height=MASK_HEIGHT,
                 budget=None):
        if mask_width < 1 or mask_height < 1:
            raise ValueError("mask geometry must be positive")
        self.mask_width = mask_width
        self.mask_height = mask_height
        self.mask_bytes = mask_width * mask_height
        if len(mask_bank) < self.mask_bytes:
            raise ValueError("mask bank holds no records")
        if len(mask_bank) % self.mask_bytes:
            raise ValueError("mask bank is not a whole number of records")
        if len(rgba_lut) < LUT_BYTES:
            raise ValueError("RGBA LUT is too small")
        self.stream = stream
        self.surface = surface
        self._image = image_ctor
        self._vec2 = vec2_ctor
        self._bank = mask_bank
        self._bank_count = len(mask_bank) // self.mask_bytes
        self._lut = rgba_lut
        width = surface.width
        height = surface.height
        self.cell_w = width // stream.columns
        self.cell_h = height // stream.rows
        if self.cell_w < 1 or self.cell_h < 1:
            raise ValueError("surface is smaller than the cell grid")
        self.origin_x = (width - self.cell_w * stream.columns) // 2
        self.origin_y = (height - self.cell_h * stream.rows) // 2
        self.tile_bytes_each = self.cell_w * self.cell_h * 4
        self.tile_limit = max(1, MAX_TILE_BYTES // self.tile_bytes_each)
        self._budget = budget
        self.budget = budget_for(stream) if budget is None else budget
        self._tiles = {}
        self.failed = False
        self.errors = 0
        self.stats = {"painted": 0, "records": 0, "skipped": 0, "errors": 0,
                      "cold": 0, "flushes": 0, "retargets": 0}
        self.reset()

    def retarget(self, stream):
        """Point this painter at another stream, KEEPING the warm tile cache.

        This is the browse path.  A wearer scrubbing the catalogue starts,
        switches and abandons a deck every few frames, and building a fresh
        painter per step throws away every tile and re-composites the ones the
        next technique shares -- which is most of them, because the deck draws
        from one 102-glyph bank and one palette.

        Returns False and changes nothing if the new stream needs a different
        cell geometry, because every cached tile would then be the wrong size;
        the caller builds a new painter for that case.  All eighteen shipped
        streams are 32x12, so it is the same geometry every time.
        """
        if stream is None:
            return False
        try:
            if (stream.columns != self.stream.columns
                    or stream.rows != self.stream.rows):
                return False
            self.stream = stream
            self.budget = (budget_for(stream) if self._budget is None
                           else self._budget)
            self.failed = False
            self.errors = 0
            self.stats["retargets"] += 1
            self.reset()
            return True
        except _SAFE:
            return False

    # -- tile cache ---------------------------------------------------------
    def tile_bytes(self, glyph, style):
        """One (glyph, style) cell as RGBA, LUT-coloured.

        Masks are authored at the bank's own cell size and sampled with integer
        nearest-neighbour, which is the identity when the cell matches the bank
        (5x10 masks in a 5x10 cell at 160x120).  A glyph id past the end of the
        bank paints as the EMPTY cell rather than raising -- one corrupt entry
        must not take the background down, and the corruption is counted in
        `stats["skipped"]` where a test can see it.
        """
        if glyph >= self._bank_count or glyph < 0:
            self.stats["skipped"] += 1
            glyph = 0
        nibble = style & COLOR_MASK
        palette = (nibble - 1) % 5 if nibble else 0
        lut_base = ((5 if style & INVERSE_FLAG else 0) + palette) * 256
        lut = self._lut
        bank = self._bank
        mask_base = glyph * self.mask_bytes
        mask_width = self.mask_width
        mask_height = self.mask_height
        cell_w = self.cell_w
        cell_h = self.cell_h
        tile = bytearray(cell_w * cell_h * 4)
        write = 0
        for local_y in range(cell_h):
            row = mask_base + (local_y * mask_height // cell_h) * mask_width
            for local_x in range(cell_w):
                offset = (lut_base + bank[row + (local_x * mask_width
                                                 // cell_w)]) * 4
                tile[write:write + 4] = lut[offset:offset + 4]
                write += 4
        return bytes(tile)

    def _tile(self, key):
        if len(self._tiles) >= self.tile_limit:
            self._tiles.clear()
            self.stats["flushes"] += 1
        self.stats["cold"] += 1
        surface = self._image(self.cell_w, self.cell_h)
        try:
            buffer = memoryview(surface)
        except TypeError:
            # Python < 3.12 cannot implement the buffer protocol in a pure
            # Python Badgeware fake.  Hardware never takes this path.
            buffer = memoryview(surface.buffer)
        buffer[:self.cell_w * self.cell_h * 4] = self.tile_bytes(key & 0xFF,
                                                                 key >> 8)
        self._tiles[key] = surface
        return surface

    def warm(self, pairs=None):
        """Materialise tiles ahead of time so no frame pays for a cold cell.

        `pairs` defaults to `stream.keys()`, which is every cell the asset ever
        paints: 12 to 300 tiles depending on the technique.  Never raises; a
        tile that will not allocate is simply left cold and made on demand.
        """
        if pairs is None:
            pairs = self.stream.keys()
        for glyph, style in pairs:
            key = (glyph & 0xFF) | ((style & 0xFF) << 8)
            if key not in self._tiles:
                try:
                    self._tile(key)
                except _SAFE:
                    break
        return len(self._tiles)

    @property
    def tile_count(self):
        return len(self._tiles)

    # -- playback -----------------------------------------------------------
    def reset(self):
        """Rewind to the keyframe; the next advance repaints the whole grid."""
        self._have = -1              # last authored frame fully painted
        self._record = 0             # record currently being applied
        self._offset = 0             # byte offset inside that record
        self._length = self._entries_in(self.stream.record(0))
        self._want = 0

    def _entries_in(self, record):
        """Usable byte length of a record: whole 4-byte entries only.

        `decode` already refuses an unaligned offset table, so this can only
        matter for a `SkinStream` assembled some other way -- but the cost is
        one modulo per record change and the alternative is reading three bytes
        past the end of a memoryview.
        """
        length = len(record)
        return length - (length % ENTRY_BYTES)

    def advance(self, elapsed_ms, time_scale_milli=1000):
        """Paint toward the frame the clock asks for.  Returns cells painted.

        TWO INVARIANTS, both of them tested directly:

        * BOUNDED WORK.  The return value never exceeds `2 * budget`, however
          far behind the clock has left us.  The inner loop is clamped to the
          remaining budget before it runs, so it cannot overshoot even by one
          cell, and `LAG_MULTIPLIER` is the only relaxation there is.
        * CONVERGENCE.  Against a held clock, repeated calls reach
          `caught_up` for ANY budget >= 1.  Every call either paints at least
          one cell or completes at least one record, so there is no state in
          which the painter is behind and does nothing.

        Never raises.  A surface or an allocation that fails is counted; after
        `ERROR_LIMIT` failures the painter gives up and returns 0 forever,
        because a budget's worth of raising blits every frame is the stall this
        module exists to prevent.
        """
        if self.failed:
            return 0
        stream = self.stream
        self._want = stream.frame_at(elapsed_ms, time_scale_milli)
        count = stream.frame_count
        budget = self.budget
        if not budget:
            budget = 0x7FFFFFFF
        elif (self._want - self._have) % count >= LAG_LIMIT:
            budget *= LAG_MULTIPLIER
        painted = 0
        try:
            surface = self.surface
            point = self._vec2
            tiles = self._tiles
            columns = stream.columns
            cells = stream.cell_count
            cell_w = self.cell_w
            cell_h = self.cell_h
            origin_x = self.origin_x
            origin_y = self.origin_y
            while painted < budget:
                if self._offset >= self._length:
                    self._have = 0 if self._record == count else self._record
                    if self._have == self._want:
                        break
                    self._record = (self._have + 1
                                    if self._have + 1 < count else count)
                    self._offset = 0
                    self._length = self._entries_in(
                        stream.record(self._record))
                    self.stats["records"] += 1
                    continue
                record = stream.record(self._record)
                offset = self._offset
                stop = self._length
                room = (budget - painted) * ENTRY_BYTES
                if offset + room < stop:
                    stop = offset + room
                while offset < stop:
                    index = record[offset] | (record[offset + 1] << 8)
                    if index < cells:
                        key = record[offset + 2] | (record[offset + 3] << 8)
                        tile = tiles.get(key)
                        if tile is None:
                            tile = self._tile(key)
                        surface.blit(
                            tile,
                            point(origin_x + (index % columns) * cell_w,
                                  origin_y + (index // columns) * cell_h))
                    else:
                        # A cell index past the grid is a corrupt entry.  Skip
                        # it, charge it to the budget, keep the loop bounded.
                        self.stats["skipped"] += 1
                    offset += ENTRY_BYTES
                    painted += 1
                self._offset = offset
        except _SAFE:
            self.errors += 1
            self.stats["errors"] += 1
            if self.errors >= ERROR_LIMIT:
                self.failed = True
        self.stats["painted"] += painted
        return painted

    @property
    def caught_up(self):
        return self._have == self._want and self._offset >= self._length

    @property
    def frame(self):
        """The authored frame the last `advance` was aiming at."""
        return self._want

    @property
    def lag(self):
        """Authored frames between what is painted and what the clock wants.

        The number `LAG_LIMIT` is compared against, exposed because it is the
        only honest way to test that falling behind is BOUNDED rather than
        monotonic -- a background that drifts further behind every frame still
        draws, and nothing else would notice.
        """
        return (self._want - self._have) % self.stream.frame_count


def painter(stream, mask_bank, rgba_lut, surface, image_ctor, vec2_ctor,
            mask_width=MASK_WIDTH, mask_height=MASK_HEIGHT, budget=None):
    """`SkinPainter`, or None.  Never raises.  The app-facing constructor."""
    if stream is None or mask_bank is None or rgba_lut is None:
        return None
    try:
        return SkinPainter(stream, mask_bank, rgba_lut, surface, image_ctor,
                           vec2_ctor, mask_width, mask_height, budget)
    except _SAFE:
        return None


def skin(pack, entry_id, surface, image_ctor, vec2_ctor,
         treatment=DEFAULT_TREATMENT, budget=None):
    """Pack + catalogue id -> a ready painter, or None.  Never raises.

    The one call an app needs, at either resolution:

        artist = glyphskin.skin(pack, state["background"], background,
                                image, vec2, treatment)
        if artist is not None:
            artist.advance(badge.ticks - started)

    The mask bank is chosen from the surface, so a HIRES build gets the native
    10x20 masks and a LORES one the 5x10 masks with no argument and no variant
    flag; the caller never states a resolution.

    `None` means "no animated background", which every caller must already be
    able to draw, because the wearer may simply have chosen a still one.
    """
    if pack is None:
        return None
    try:
        stream = pack.stream(entry_id)
        if stream is None:
            return None
        cell = cell_size(stream, surface)
        if cell is None:
            return None
        geometry = mask_geometry_for(cell[0], cell[1])
        return painter(stream, pack.masks(cell[0], cell[1]),
                       pack.lut(treatment), surface, image_ctor, vec2_ctor,
                       mask_width=geometry[0], mask_height=geometry[1],
                       budget=budget)
    except _SAFE:
        return None
