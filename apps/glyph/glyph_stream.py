"""GPA1 packed cell-stream assets: header parsing and clock-derived frames.

Pure Python, no hardware imports; runs identically under CPython (tests)
and MicroPython (badge). One asset = one captured glyph-engine technique.

Binary layout (little-endian), fixed 64-byte header then frame data:

    offset size  field
    0      4     magic  b"GPA1"
    4      2     header length (64)
    6      1     grid columns (16)
    7      1     grid rows, visible only (6)
    8      2     frame count
    10     2     frame bytes (= columns * rows * 2)
    12     4     loop period in ENGINE microseconds
    16     2     engine speed * 1000 (500 = the playground player's 0.5)
    18     1     loop class: 0 exact, 1 structural, 2 none
    19     1     flags: bit0 = stream contains inverse cells
    20     24    technique id, ASCII, zero padded
    44     20    reserved (zero)
    64     ...   frame_count * frame_bytes packed cells

Packed cell record (2 bytes, sparkle-player packed-grid compatible):
    byte 0: glyph id into glyph_vocab.PLAYER_GLYPHS (0 = empty cell)
    byte 1: bit7 inverse; low nibble = palette color index + 1
            (nibble 0 = inherit strand color; recorded streams never emit it,
            every cell carries its captured explicit color)

The engine clock contract: the web engine advances `engine_ms = wall_ms *
speed`. A stream captured over one loop period P engine-ms at N frames is
played back by mapping elapsed wall time onto the loop:

    engine_us = elapsed_ms * speed_milli * time_scale_milli // 1000
    frame     = (engine_us * frame_count // period_engine_us) % frame_count

time_scale_milli 1000 plays at authentic site speed; 2000 plays double
speed (the wake-sting variant). The mapping is stateless: dropped frames
self-correct and two badges started together stay in sync.
"""

MAGIC = b"GPA1"
HEADER_BYTES = 64

LOOP_EXACT = 0
LOOP_STRUCTURAL = 1
LOOP_NONE = 2


def _u16(data, offset):
    return data[offset] | (data[offset + 1] << 8)


def _u32(data, offset):
    return (
        data[offset]
        | (data[offset + 1] << 8)
        | (data[offset + 2] << 16)
        | (data[offset + 3] << 24)
    )


class GlyphStream:
    """One parsed GPA1 asset held fully in RAM (the deck is 3-74 KB each)."""

    def __init__(self, data):
        if len(data) < HEADER_BYTES:
            raise ValueError("GPA asset is shorter than its header")
        if bytes(data[0:4]) != MAGIC:
            raise ValueError("GPA magic mismatch")
        header_len = _u16(data, 4)
        if header_len != HEADER_BYTES:
            raise ValueError("GPA header length %d unsupported" % header_len)
        self.columns = data[6]
        self.rows = data[7]
        self.frame_count = _u16(data, 8)
        self.frame_bytes = _u16(data, 10)
        self.period_engine_us = _u32(data, 12)
        self.speed_milli = _u16(data, 16)
        self.loop_class = data[18]
        self.flags = data[19]
        raw_id = bytes(data[20:44])
        self.technique = raw_id.rstrip(b"\x00").decode()
        if self.columns < 1 or self.rows < 1:
            raise ValueError("GPA grid is empty")
        if self.frame_bytes != self.columns * self.rows * 2:
            raise ValueError("GPA frame size does not match its grid")
        if self.frame_count < 1:
            raise ValueError("GPA has no frames")
        if self.period_engine_us < 1:
            raise ValueError("GPA period must be positive")
        if self.speed_milli < 1:
            raise ValueError("GPA speed must be positive")
        expected = HEADER_BYTES + self.frame_count * self.frame_bytes
        if len(data) != expected:
            raise ValueError(
                "GPA payload is %d bytes, expected %d" % (len(data), expected)
            )
        self._data = data

    @property
    def cell_count(self):
        return self.columns * self.rows

    @property
    def period_wall_ms(self):
        """One loop in wall milliseconds at authentic (1x) playback."""
        return self.period_engine_us // self.speed_milli

    def frame_view(self, index):
        """A zero-copy memoryview of one frame's packed cells."""
        if index < 0 or index >= self.frame_count:
            raise IndexError("frame %d out of range" % index)
        start = HEADER_BYTES + index * self.frame_bytes
        return memoryview(self._data)[start : start + self.frame_bytes]

    def frame_at(self, elapsed_ms, time_scale_milli=1000):
        """Clock-derived frame index for elapsed wall milliseconds."""
        if elapsed_ms < 0:
            elapsed_ms = 0
        engine_us = elapsed_ms * self.speed_milli * time_scale_milli // 1000
        return (engine_us * self.frame_count // self.period_engine_us) % self.frame_count


def load(path, chunked=None):
    """Read a GPA asset from disk into RAM.

    `chunked` is the loading screen's seam.  A `.gpa` is 2-73 KB and reading it
    is ONE native call the app blocks inside; `shared/loading.py` supplies a
    `chunked(handle, nbytes, pieces)` that reads it in eight slices with a
    presented frame between each, which is the only way a progress bar can move
    through this on a build with threads compiled out.  Default None, so the
    runtime asset switches (A / C) keep the single fast read they have today.
    """
    with open(path, "rb") as source:
        if chunked is None:
            return GlyphStream(source.read())
        source.seek(0, 2)
        size = source.tell()
        source.seek(0)
        return GlyphStream(chunked(source, size, pieces=8))
