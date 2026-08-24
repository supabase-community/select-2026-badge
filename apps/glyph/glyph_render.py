"""Mask-bank + RGBA-LUT cell compositor with diff-draw.

Pure Python, no hardware imports. Rendering technique adopted from the
select-badge sparkle-player branch's compositor contract
(bank_mask_compositor_contract.py): one antialiased coverage mask per
glyph (200 bytes at the classic 10x20 cell), one 10,240-byte RGBA lookup
table factoring color and inverse out of the mask set. This module renders
packed cells into any RGBA byte buffer (the screen's own buffer, or
per-tile image surfaces that the app blits) and only touches cells whose
packed record changed.

Mask geometry is parametric since the glyph2x feature: a renderer may be
constructed with a bank authored at another cell size (the 2x-density deck
uses 5x10 masks). The defaults are the classic 10x20 records, and default
behavior is byte-identical to the frozen sparkle-player oracle (pinned by
glyph/tests). The LUT is coverage-indexed and carries no cell geometry, so
one LUT serves every mask size.

Style byte (packed record byte 1): bit7 = inverse, low nibble = palette
color index + 1. Recorded streams always carry an explicit color; nibble 0
(strand-inherit) is remapped to color 0 and counted in ``stats`` so a
malformed asset is visible rather than fatal mid-animation.

THE DIFF WALK IS THE 32x12 COST, AND IT IS MEMOIZED RATHER THAN REWRITTEN.
``draw`` used to iterate every cell of the grid on every frame regardless of
how few changed, which is 96 interpreted iterations at 16x6 and 384 at 32x12.
The 2026-08-20 v3.0.2 repin measured that as the reason HIRES 32x12 is not
ship-grade: warm compositor median 5.914 ms with only 26 cells actually
blitted, roughly 4.8 ms of it the Python loop
(``benchmark/results/reports/2026-08-20-v3.0.2-repin.md`` §5).

A recorded stream is a FIXED loop, so which cells differ between two of its
frames is a property of the asset, not of the run. Pass ``frame=`` and the
renderer remembers, per frame index, the byte offsets that changed and the
frame they changed FROM; a later arrival at the same transition walks only
those offsets. Nothing is precomputed at load: each list is built as the
by-product of the one full walk that transition needs anyway, so a cold first
loop costs exactly what today costs and every loop after it is cheaper.

The guard is what makes it safe: an entry is used only when ``_previous``
still holds the exact frame the entry was derived from, so a skipped frame,
a speed change, a ``reset()`` or a forced repaint falls back to the full
walk instead of trusting a stale list. Callers that pass no ``frame`` keep
byte-identical behavior to the frozen oracle.

A TILE CACHE BELONGS TO A CELL GEOMETRY, AND FORGETTING THAT SHIPPED A BUG.
A target's cache is keyed by ``(glyph_id, style)`` -- everything
``tile_bytes`` reads EXCEPT the cell size it renders AT. One target
outliving one renderer is the design (``glyph``'s viewer builds a renderer
per A/C entry and shares one module-level target, so stepping the catalogue
keeps its tiles warm), so on 2026-08-21 a HIRES C-press from the 16x6 deck
to the 32x12 deck handed every 20x40 surface to a renderer drawing on a
10x20 pitch: each glyph painted at 4x area over its right and lower
neighbours, and the diff-draw never cleaned the overdraw up because those
cells had not "changed". The owner saw it and called the dense entries
"really messed up"; the suite was green, because the goldens pin one
geometry at a time and ``playground/e2e/glyph-viewers.spec.ts`` asserted the
console lines of that exact flip without looking at a pixel.

So a target holds ONE CACHE PER CELL GEOMETRY and ``use_geometry`` picks the
live one. The renderer calls it in its constructor and once per
``draw``/``prewarm`` -- not per cell, because 384 cells a frame is no place
for a bounds check, and not at construction alone, because "the app
remembers to do it in the right order" is the invariant that just failed.
Both geometries stay warm: rebuilding on every press would cost 2.15 s for
signal-ripple's 93 tiles at 23.07 ms each, and the flip is meant to be an
A/B one thumb movement wide. ``_tiles`` still names the LIVE geometry's
dict, so probes reading ``len(target._tiles)`` keep reporting the cache in
use; ``total_tiles()`` is the across-geometry number for a memory question.

...AND THAT MEMORY QUESTION CAME DUE ON 2026-08-22, ON THE OWNER'S BADGE.
"Both geometries stay warm" was the right call for the 2.15 s and the wrong
one for the heap, because nothing bounded it and nothing could drop it. The
owner flipped densities in the viewer and got a traceback modal:
``MemoryError: memory allocation failed, allocating 66816 bytes`` from a
dense ``.gpa`` read (``glyph_stream.load``). A dense stream is 49-74 KB and
wants that much CONTIGUOUS, and the caches this file keeps had eaten the
headroom: 18 techniques accumulate across a catalogue walk, each key costing
3,200 B at the coarse 20x40 cell and 800 B at the dense 10x20 one.

So the caches are now BOUNDED and DROPPABLE, and both halves matter:

* ``MAX_TILE_BYTES`` caps the total. Overflow drops the INACTIVE geometry
  first (costing the next flip its re-warm, the price already accepted
  above) and only then clears wholesale, so the entry on screen keeps its
  tiles in the common case. Checked once per COLD tile build, never in the
  draw path. The pattern and the wholesale-clear-over-LRU reasoning are
  ``badgecard/badge/badgecard/glyphskin.py``'s ``MAX_TILE_BYTES``.
* ``drop_geometries_except()`` / ``drop_other_geometries()`` /
  ``drop_all_tiles()`` are the levers the app pulls when an allocation has
  already failed or is about to. Tiles are pure cache: giving them back is
  always safe and always cheaper than a reset. WHICH cache to keep is the
  whole subtlety and it is written up on ``drop_geometries_except``. See the
  app's ``_read_stream``, ``_present`` and ``_stay_put``.
"""

from array import array

import glyph_vocab

MASK_BYTES = glyph_vocab.MASK_BYTES
MASK_WIDTH = 10
MASK_HEIGHT = 20
LUT_BYTES = 10240
INVERSE_FLAG = glyph_vocab.INVERSE_FLAG
COLOR_MASK = glyph_vocab.COLOR_MASK

# Changed-cell lists are held as ``array('H')``: measured on the pinned
# MicroPython 1.29 unix port, that is both 1.58x faster to iterate than a list
# of the same ints AND 3.25x smaller (32,800 B against 106,560 B for 192 lists
# of 50). 'H' caps a cell index at 65,535 offsets, i.e. 32,767 cells, which is
# 85x the densest grid we record.
DIRTY_TYPECODE = "H"
# A ceiling on memoization, in cells, so a long asset cannot grow the cache
# without bound. 16,384 cells is 32 KB of payload and clears the whole 2x deck's
# worst case (arrow-field, 9,579 changed cells across its 192 frames).
DIRTY_BUDGET_CELLS = 16384

# A CEILING ON THE TILE CACHES, in bytes across every geometry, because until
# 2026-08-22 there was none and the owner's badge raised MemoryError reading a
# dense stream (module docstring, last section).
#
# The arithmetic the number has to satisfy, in both directions:
#   * BIG ENOUGH not to thrash the both-warm A/B. The worst single entry is
#     signal-ripple at 93 distinct keys; held at BOTH geometries that is
#     93 * 3,200 + 93 * 800 = 372,000 B, and a cap under that would clear the
#     cache on the very keypress the feature exists for.
#   * SMALL ENOUGH to bound a catalogue walk. 18 techniques is a few hundred
#     distinct keys, so an unbounded coarse cache alone heads past 1 MB while
#     a dense stream needs 74 KB CONTIGUOUS. Fragmentation, not the total, is
#     what killed the read.
# 512 KB clears the first by 141 KB and caps the second at ~40% of where it
# was heading. It is a bound, not a measurement of a device limit: no probe has
# measured the badge's free heap with the badgelink runtime resident, and
# `docs/engineering-findings.md` records that as the open gate.
MAX_TILE_BYTES = 524288


class GlyphRenderer:
    """Diff-draws packed cell grids as RGBA tiles.

    The caller supplies a ``target`` with one method:
        draw_cell(cell_x_px, cell_y_px, key, renderer)
    where ``key`` is the (glyph_id, style) pair; the target obtains pixel
    bytes via ``renderer.tile_bytes(key)`` and owns its own tile cache, so
    a raw-buffer target caches bytes while a blit target caches surfaces.
    """

    def __init__(
        self,
        mask_bank,
        rgba_lut,
        columns,
        rows,
        screen_w,
        screen_h,
        target,
        mask_width=MASK_WIDTH,
        mask_height=MASK_HEIGHT,
    ):
        if mask_width < 1 or mask_height < 1:
            raise ValueError("mask geometry must be positive")
        self.mask_width = mask_width
        self.mask_height = mask_height
        self.mask_bytes = mask_width * mask_height
        if len(mask_bank) % self.mask_bytes:
            raise ValueError("mask bank length is not a whole number of records")
        if len(rgba_lut) < LUT_BYTES:
            raise ValueError("RGBA LUT is too small")
        self._bank = mask_bank
        self._bank_count = len(mask_bank) // self.mask_bytes
        self._lut = rgba_lut
        self.columns = columns
        self.rows = rows
        self.cell_count = columns * rows
        # Resolution-relative layout: integer cell size, centred remainder.
        self.cell_w = screen_w // columns
        self.cell_h = screen_h // rows
        if self.cell_w < 1 or self.cell_h < 1:
            raise ValueError("screen is smaller than the cell grid")
        self.origin_x = (screen_w - self.cell_w * columns) // 2
        self.origin_y = (screen_h - self.cell_h * rows) // 2
        self._target = target
        # 0xFF is not a valid packed record for either byte, so the first
        # draw after construction or reset() repaints every cell.
        self._previous = bytearray(b"\xff" * (self.cell_count * 2))
        # frame index -> (frame it was derived FROM, array('H') of byte offsets)
        self._dirty = {}
        # Which frame index ``_previous`` currently holds. -1 = not a frame.
        self._dirty_frame = -1
        self._dirty_cells = 0
        self.dirty_enabled = True
        self.stats = {
            "frames": 0,
            "cells_drawn": 0,
            "inherit_remapped": 0,
            "dirty_hits": 0,
            "dirty_walks": 0,
        }
        # Resolved once: a target predating this contract (an app's own custom
        # target, or the vendored copy under identity/host/skinprobe) simply
        # has no geometry to select and must keep working unchanged.
        self._target_geometry = getattr(target, "use_geometry", None)
        self._sync_target()

    def _sync_target(self):
        """Point the target's tile cache at THIS renderer's cell geometry.

        Called from the constructor and from the top of ``draw``/``prewarm``:
        once per frame, never per cell. See the module docstring for why both.
        """
        if self._target_geometry is not None:
            self._target_geometry(self.cell_w, self.cell_h)

    def reset(self):
        """Force the next draw to repaint the full grid."""
        for index in range(len(self._previous)):
            self._previous[index] = 0xFF
        # The cache stays: it describes the asset, not this run. But nothing in
        # it may be trusted now, because ``_previous`` no longer holds a frame.
        self._dirty_frame = -1

    def draw(self, packed, force=False, frame=None):
        """Draw one packed frame; returns the number of cells repainted.

        ``frame`` is the stream's frame index. Supplying it enables the
        changed-cell memo described in the module docstring; omitting it keeps
        the original full-grid walk exactly.
        """
        if len(packed) < self.cell_count * 2:
            raise ValueError("packed frame is smaller than the grid")
        self._sync_target()
        memoizing = (
            not force
            and frame is not None
            and self.dirty_enabled
            # A walk from "no known frame" would memoize the whole grid, which
            # costs the most to store and saves the least. Skip it.
            and self._dirty_frame >= 0
        )
        if memoizing:
            entry = self._dirty.get(frame)
            if entry is not None and entry[0] == self._dirty_frame:
                drawn = self._draw_offsets(packed, entry[1])
                self._dirty_frame = frame
                self.stats["frames"] += 1
                self.stats["cells_drawn"] += drawn
                self.stats["dirty_hits"] += 1
                return drawn

        previous = self._previous
        changed = [] if memoizing else None
        drawn = 0
        cell_w = self.cell_w
        cell_h = self.cell_h
        columns = self.columns
        target = self._target
        for index in range(self.cell_count):
            offset = index * 2
            glyph = packed[offset]
            style = packed[offset + 1]
            if (
                not force
                and previous[offset] == glyph
                and previous[offset + 1] == style
            ):
                continue
            if glyph >= self._bank_count:
                raise ValueError("glyph id %d outside the mask bank" % glyph)
            cell_x = self.origin_x + (index % columns) * cell_w
            cell_y = self.origin_y + (index // columns) * cell_h
            target.draw_cell(cell_x, cell_y, (glyph, style), self)
            previous[offset] = glyph
            previous[offset + 1] = style
            if changed is not None:
                changed.append(offset)
            drawn += 1
        if changed is not None:
            self._remember(frame, changed)
        # A forced repaint leaves ``_previous`` holding this frame just as a
        # diffed one does, so the memo may still key off it next time.
        if frame is None:
            self._dirty_frame = -1
        else:
            self._dirty_frame = frame
        self.stats["frames"] += 1
        self.stats["cells_drawn"] += drawn
        self.stats["dirty_walks"] += 1
        return drawn

    def _remember(self, frame, changed):
        """Store one transition's changed offsets, inside the cell budget."""
        previous_entry = self._dirty.get(frame)
        replaced = len(previous_entry[1]) if previous_entry is not None else 0
        if self._dirty_cells - replaced + len(changed) > DIRTY_BUDGET_CELLS:
            return
        self._dirty[frame] = (self._dirty_frame, array(DIRTY_TYPECODE, changed))
        self._dirty_cells += len(changed) - replaced

    def _draw_offsets(self, packed, offsets):
        """Repaint exactly the cells a remembered transition changes."""
        previous = self._previous
        columns = self.columns
        cell_w = self.cell_w
        cell_h = self.cell_h
        origin_x = self.origin_x
        origin_y = self.origin_y
        bank_count = self._bank_count
        target = self._target
        drawn = 0
        for offset in offsets:
            glyph = packed[offset]
            style = packed[offset + 1]
            if glyph >= bank_count:
                raise ValueError("glyph id %d outside the mask bank" % glyph)
            index = offset >> 1
            target.draw_cell(
                origin_x + (index % columns) * cell_w,
                origin_y + (index // columns) * cell_h,
                (glyph, style),
                self,
            )
            previous[offset] = glyph
            previous[offset + 1] = style
            drawn += 1
        return drawn

    def tile_bytes(self, key):
        """Render one (glyph_id, style) cell to RGBA bytes, LUT-colored.

        Masks are authored at the bank's own cell size (10x20 classic,
        5x10 for the 2x-density deck); other cell sizes sample the mask
        with integer nearest-neighbour, which is the identity when the
        cell matches the bank geometry.
        """
        glyph, style = key
        nibble = style & COLOR_MASK
        if nibble:
            color = (nibble - 1) % 5
        else:
            color = 0
            if glyph:
                # A lit glyph without an explicit color is a malformed
                # recorded stream; empty background cells legitimately
                # carry style 0 and are not counted.
                self.stats["inherit_remapped"] += 1
        table = (5 if style & INVERSE_FLAG else 0) + color
        lut = self._lut
        lut_base = table * 256
        bank = self._bank
        mask_base = glyph * self.mask_bytes
        mask_width = self.mask_width
        mask_height = self.mask_height
        cell_w = self.cell_w
        cell_h = self.cell_h
        tile = bytearray(cell_w * cell_h * 4)
        write = 0
        for local_y in range(cell_h):
            mask_row = mask_base + (local_y * mask_height // cell_h) * mask_width
            for local_x in range(cell_w):
                coverage = bank[mask_row + (local_x * mask_width // cell_w)]
                lut_offset = (lut_base + coverage) * 4
                tile[write : write + 4] = lut[lut_offset : lut_offset + 4]
                write += 4
        return bytes(tile)


    def keys_in(self, packed):
        """Every distinct (glyph, style) cell key in one packed frame.

        The seam a caller uses to populate the tile cache BEFORE animating.
        Cold ``tile_bytes`` is pure Python per output pixel, so at HIRES a
        20x40 tile costs 23.07 ms against 5.06 ms at 10x20 (v3.0.2 repin) and
        a cold deck hitches visibly for its first pass. Collecting keys is a
        read-only walk: it draws nothing and mutates no diff state.
        """
        found = set()
        for index in range(self.cell_count):
            offset = index * 2
            found.add((packed[offset], packed[offset + 1]))
        return found

    def prewarm(self, keys):
        """Render the given cell keys into the target's cache, drawing nothing.

        Returns the number of tiles actually built, so a caller can report the
        cost it moved off the animation and into its loading screen.
        """
        target = self._target
        if not hasattr(target, "prewarm"):
            return 0
        self._sync_target()
        built = 0
        for key in keys:
            if key[0] >= self._bank_count:
                raise ValueError("glyph id %d outside the mask bank" % key[0])
            if target.prewarm(key, self):
                built += 1
        return built


class _GeometryCaches:
    """One tile cache per cell geometry; ``_tiles`` is the live one.

    Mixed into both targets. A tile is pixels rendered AT a cell size, so a
    cache that spans two cell sizes serves the wrong bytes -- see the module
    docstring for the flip that proved it.
    """

    def _init_caches(self, max_tile_bytes=MAX_TILE_BYTES):
        self._caches = {}
        self._geometry = None
        self._tiles = {}
        self.max_tile_bytes = max_tile_bytes
        # Bumped every time the ceiling had to give something back. A soak that
        # walks the catalogue expects a few; a soak that flips one pair expects
        # zero, which is what makes the both-warm claim checkable.
        self.overflows = 0

    def use_geometry(self, cell_w, cell_h):
        """Select the cache for this cell size, creating it on first use."""
        geometry = (cell_w, cell_h)
        if geometry == self._geometry:
            return self._tiles
        tiles = self._caches.get(geometry)
        if tiles is None:
            tiles = {}
            self._caches[geometry] = tiles
        self._geometry = geometry
        self._tiles = tiles
        return tiles

    def total_tiles(self):
        """Tiles held across every geometry: the memory question's answer."""
        return sum(len(tiles) for tiles in self._caches.values())

    def tile_bytes_held(self):
        """Bytes of tile cache across every geometry.

        Derived from the geometry rather than measured per object, so it is the
        same number for a ``RawTarget``'s ``bytes`` and a ``BlitTarget``'s
        surfaces -- and so it costs one multiply per geometry rather than a walk
        over every tile.
        """
        return sum(
            len(tiles) * geometry[0] * geometry[1] * 4
            for geometry, tiles in self._caches.items()
        )

    def geometries(self):
        """The cell sizes this target is holding tiles for, smallest first."""
        return tuple(sorted(self._caches))

    def drop_geometries_except(self, keep):
        """Free every cache except ``keep``'s. Returns (caches, tiles).

        ``keep`` is the cell size whose tiles are worth something NEXT, and it
        need not be the live one -- or exist at all, which is the case that
        matters. An app about to load a dense entry has not built its dense
        renderer yet, so the live cache is still the COARSE one it is leaving:
        on exactly the first coarse-to-dense flip, "keep the live geometry"
        protects the 41,600 B nobody is about to draw and frees nothing, which
        is no relief at all on the press that raised MemoryError. Naming the
        INCOMING geometry frees the right 41,600 B.

        ``_tiles`` is re-pointed when the live cache was among the casualties,
        so the invariant that it names the live geometry's dict survives; the
        next ``use_geometry`` re-creates it.
        """
        caches = 0
        tiles = 0
        for geometry in list(self._caches):
            if geometry == keep:
                continue
            tiles += len(self._caches.pop(geometry))
            caches += 1
        if self._geometry is not None and self._geometry not in self._caches:
            self._geometry = None
            self._tiles = {}
        return caches, tiles

    def drop_other_geometries(self):
        """Free every cache except the LIVE one. Returns (caches, tiles).

        The no-regret lever for a caller that is MID-ANIMATION: what it gives
        back is the geometry the wearer is not looking at. The bill is the NEXT
        flip's re-warm, which is the 2.15 s the module docstring accepts.
        """
        return self.drop_geometries_except(self._geometry)

    def drop_all_tiles(self):
        """Free every cache INCLUDING the live one. Returns tiles dropped.

        The last lever, for when an allocation has already failed and the
        inactive geometry was not enough. ``_tiles`` keeps naming the live
        geometry's dict -- the invariant every probe reads -- it is simply
        empty, so the next frames rebuild lazily the cells they actually need.
        """
        dropped = self.total_tiles()
        self._caches = {}
        self._tiles = {}
        if self._geometry is not None:
            self._caches[self._geometry] = self._tiles
        return dropped

    def _admit(self, renderer):
        """Make room for one more tile, dropping the cheapest thing first.

        Called once per COLD tile build, never from the draw path: a warm cell
        is a dict hit and a blit, and 384 cells a frame is no place for a sum.
        """
        if self.max_tile_bytes <= 0:
            return
        tile = renderer.cell_w * renderer.cell_h * 4
        if self.tile_bytes_held() + tile <= self.max_tile_bytes:
            return
        self.overflows += 1
        self.drop_other_geometries()
        if self.tile_bytes_held() + tile <= self.max_tile_bytes:
            return
        self.drop_all_tiles()


class RawTarget(_GeometryCaches):
    """Slice-copies tiles straight into an RGBA screen buffer.

    ``raw`` is any writable buffer of screen_w * screen_h * 4 bytes
    (memoryview(screen) on hardware, a bytearray under CPython tests).
    """

    def __init__(self, raw, screen_w):
        self._raw = raw
        self._stride = screen_w * 4
        self._init_caches()

    def prewarm(self, key, renderer):
        """Build one tile ahead of time. True when it was not already cached."""
        if key in self._tiles:
            return False
        self._admit(renderer)
        self._tiles[key] = renderer.tile_bytes(key)
        return True

    def draw_cell(self, cell_x, cell_y, key, renderer):
        tile = self._tiles.get(key)
        if tile is None:
            self._admit(renderer)
            tile = renderer.tile_bytes(key)
            self._tiles[key] = tile
        raw = self._raw
        stride = self._stride
        row_bytes = renderer.cell_w * 4
        left = cell_x * 4
        read = 0
        for local_y in range(renderer.cell_h):
            offset = (cell_y + local_y) * stride + left
            raw[offset : offset + row_bytes] = tile[read : read + row_bytes]
            read += row_bytes


class BlitTarget(_GeometryCaches):
    """Renders tiles once into image surfaces and blits them per cell.

    Uses only measured v3.0.1 facilities: ``image(w, h)`` surfaces support
    the buffer protocol (bulk memoryview assignment) and ``screen.blit``
    costs 0.233 ms median for a small sprite.
    """

    def __init__(self, screen, image_ctor, vec2_ctor):
        self._screen = screen
        self._image = image_ctor
        self._vec2 = vec2_ctor
        self._init_caches()

    def _build(self, key, renderer):
        # Before the surface, not after: the ceiling exists to stop an
        # allocation failing, so it has to run in front of the allocation.
        self._admit(renderer)
        surface = self._image(renderer.cell_w, renderer.cell_h)
        try:
            buffer = memoryview(surface)
        except TypeError:
            # Python <3.12 cannot implement the buffer protocol in a
            # pure-Python Badgeware fake. Hardware never takes this path;
            # ``.buffer`` keeps the renderer testable on older host Python.
            buffer = memoryview(surface.buffer)
        buffer[: renderer.cell_w * renderer.cell_h * 4] = renderer.tile_bytes(key)
        self._tiles[key] = surface
        return surface

    def prewarm(self, key, renderer):
        """Build one surface ahead of time. True when it was not already cached."""
        if key in self._tiles:
            return False
        self._build(key, renderer)
        return True

    def draw_cell(self, cell_x, cell_y, key, renderer):
        surface = self._tiles.get(key)
        if surface is None:
            surface = self._build(key, renderer)
        self._screen.blit(surface, self._vec2(cell_x, cell_y))


class BatchBlitTarget(BlitTarget):
    """A BlitTarget that submits one frame's cells as a single ``batch()`` call.

    ``image.batch(commands)`` takes a list of ``(method_name, *params)`` tuples
    and runs them in one C dispatch loop. Measured 2026-08-21 on v3.0.2: 1.82x
    faster than the same 72-draw-call frame issued call by call with a cached
    list, and **1.28x with the list rebuilt every frame**
    (`benchmark/results/reports/2026-08-20-v3.0.2-filter-matrix.md` §3). A
    diff-draw rebuilds every frame by definition, so 1.28x is the honest number
    to expect here.

    ⚠ NOT ENABLED BY DEFAULT AND NOT DEVICE-MEASURED IN THIS APP. Nothing else
    in the repository calls ``batch()``; the API's existence and its microbench
    are proven, its behavior inside a diff-drawn glyph frame is not. ``supported``
    probes for the method so a runtime without it degrades to the plain target
    instead of raising inside ``launch()``, which resets the badge.
    """

    def __init__(self, screen, image_ctor, vec2_ctor):
        BlitTarget.__init__(self, screen, image_ctor, vec2_ctor)
        self._commands = []

    @staticmethod
    def supported(screen):
        return callable(getattr(screen, "batch", None))

    def draw_cell(self, cell_x, cell_y, key, renderer):
        surface = self._tiles.get(key)
        if surface is None:
            surface = self._build(key, renderer)
        self._commands.append(("blit", surface, cell_x, cell_y))

    def flush(self):
        """Submit the accumulated frame. Returns the command count issued."""
        commands = self._commands
        if not commands:
            return 0
        count = len(commands)
        self._screen.batch(commands)
        # A new list, not clear(): batch() holds the argument for the duration
        # of the call and reusing the object across frames is not a documented
        # guarantee anywhere we have measured.
        self._commands = []
        return count


def make_rgba_lut(palette=glyph_vocab.PALETTE_RGB, alpha_num=100, alpha_den=100):
    """Build the 10,240-byte RGBA LUT: (inverse*5+color)*256+coverage -> RGBA.

    Layout adopted from the sparkle-player compositor contract. That
    branch modelled painted ink at source alphas 88/100 and 96/100; our
    captured playground-player frames measure FULL-strength palette ink
    (pixel histograms of the captured canvases show the exact palette
    values), so recorded-stream assets use alpha 100/100. Exact rational
    rounding, no floats.
    """
    if len(palette) != 5:
        raise ValueError("palette must contain five colors")
    if not 1 <= alpha_num <= alpha_den:
        raise ValueError("alpha must be a fraction in (0, 1]")
    denominator = alpha_den * 255
    output = bytearray(LUT_BYTES)
    for inverse in range(2):
        for color in range(5):
            source = palette[color]
            ground = tuple(
                (channel * alpha_num + alpha_den // 2) // alpha_den
                for channel in source
            )
            for coverage in range(256):
                offset = ((inverse * 5 + color) * 256 + coverage) * 4
                for channel_index in range(3):
                    if inverse:
                        value = (
                            ground[channel_index]
                            * (denominator - alpha_num * coverage)
                            + denominator // 2
                        ) // denominator
                    else:
                        value = (
                            source[channel_index] * alpha_num * coverage
                            + denominator // 2
                        ) // denominator
                    output[offset + channel_index] = value
                output[offset + 3] = 255
    return output
