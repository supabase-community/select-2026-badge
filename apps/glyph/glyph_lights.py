"""Optional four-zone case-light synchronizer for recorded Glyph streams.

The light pattern is derived from the packed frame that the compositor is
already presenting.  Each logical zone follows the rendered ink energy in one
screen quadrant (top-left, bottom-left, top-right, bottom-right), rather than
running an unrelated decorative animation.  The caller supplies the physical
channel mapping because Tufty's public sources name the outputs CL0..CL3 but do
not document which rear diffuser position each output drives.

The hot-path policy is deliberately bounded:

* scan the 16x6 packed grid only when the asset frame changes;
* update at no more than 20 Hz by default;
* quantize output and suppress duplicate ``badge.caselights`` calls;
* cap brightness and use a short release tail to avoid harsh flashes.

This module has no hardware imports.  Apps pass ``badge.caselights`` and the
MicroPython tick helpers, while host tests use ordinary callables.
"""


ZONE_TOP_LEFT = 0
ZONE_BOTTOM_LEFT = 1
ZONE_TOP_RIGHT = 2
ZONE_BOTTOM_RIGHT = 3
ZONE_COUNT = 4

# Raw mean-mask energy per 8x3 logical quadrant that maps to full output.  The
# values are measured from the committed badge-native assets.  Unknown future
# techniques use a conservative generic scale.
TECHNIQUE_ENERGY_SCALE = {
    "radar": 3600,
    "wave": 3600,
    "signal-ripple": 1450,
    "arrow-field": 5800,
    "ring-buffer": 850,
}
DEFAULT_ENERGY_SCALE = 4096


def glyph_energies(mask_bank, mask_bytes=200):
    """Return the mean coverage byte for every glyph mask."""
    if mask_bytes < 1 or len(mask_bank) % mask_bytes:
        raise ValueError("mask bank length is not a whole number of records")
    output = []
    for start in range(0, len(mask_bank), mask_bytes):
        output.append(sum(mask_bank[start : start + mask_bytes]) // mask_bytes)
    return tuple(output)


def quadrant_energy(packed, columns, rows, energies):
    """Measure rendered mask energy in TL, BL, TR, BR logical quadrants."""
    cell_count = columns * rows
    if columns < 2 or rows < 2:
        raise ValueError("light sync needs a grid of at least 2x2 cells")
    if len(packed) < cell_count * 2:
        raise ValueError("packed frame is smaller than the grid")
    split_x = columns // 2
    split_y = rows // 2
    zones = [0, 0, 0, 0]
    for index in range(cell_count):
        offset = index * 2
        glyph = packed[offset]
        style = packed[offset + 1]
        if glyph == 0 and style == 0:
            continue
        if glyph >= len(energies):
            raise ValueError("glyph id %d outside the mask bank" % glyph)
        energy = energies[glyph]
        if style & 0x80:
            energy = 255 - energy
        x = index % columns
        y = index // columns
        zone = (2 if x >= split_x else 0) + (1 if y >= split_y else 0)
        zones[zone] += energy
    return tuple(zones)


class GlyphLightSync:
    """Rate-limited, change-only case-light projection of one Glyph stream."""

    def __init__(
        self,
        writer,
        mask_bank,
        technique,
        columns,
        rows,
        channel_for_zone=(0, 1, 2, 3),
        max_level=0.24,
        interval_ms=50,
        quantization_steps=12,
        frame_count=None,
        ticks_diff=None,
        ticks_add=None,
        mask_bytes=200,
        energy_scale_multiplier=1,
    ):
        if sorted(channel_for_zone) != [0, 1, 2, 3]:
            raise ValueError("channel_for_zone must be a permutation of 0..3")
        if max_level < 0 or max_level > 1:
            raise ValueError("max_level must be in 0..1")
        if interval_ms < 1:
            raise ValueError("interval_ms must be positive")
        if quantization_steps < 1:
            raise ValueError("quantization_steps must be positive")
        if columns < 2 or rows < 2:
            raise ValueError("light sync needs a grid of at least 2x2 cells")
        if frame_count is not None and frame_count < 1:
            raise ValueError("frame_count must be positive")
        if energy_scale_multiplier < 1:
            raise ValueError("energy_scale_multiplier must be positive")
        self.writer = writer
        self.technique = technique
        self.columns = columns
        self.rows = rows
        self.channel_for_zone = tuple(channel_for_zone)
        self.max_level = max_level
        self.interval_ms = interval_ms
        self.quantization_steps = quantization_steps
        self._ticks_diff = ticks_diff or (lambda left, right: left - right)
        self._ticks_add = ticks_add or (lambda value, delta: value + delta)
        self._energies = glyph_energies(mask_bank, mask_bytes)
        self._energy_scale = TECHNIQUE_ENERGY_SCALE.get(
            technique, DEFAULT_ENERGY_SCALE
        ) * energy_scale_multiplier
        self._level_table = tuple(
            max_level * step / quantization_steps
            for step in range(quantization_steps + 1)
        )
        self._target = [0, 0, 0, 0]
        self._smoothed = [0, 0, 0, 0]
        # Four normalized bytes plus one validity byte per authored frame:
        # 480 B for radar and at most 960 B for this deck. Looping backgrounds
        # then scan each packed frame once rather than every revolution.
        self._frame_targets = (
            bytearray(frame_count * ZONE_COUNT) if frame_count is not None else None
        )
        self._frame_valid = bytearray(frame_count) if frame_count is not None else None
        self._last_levels = (0.0, 0.0, 0.0, 0.0)
        self._last_frame = -1
        self._next_update = None
        self.frame_scans = 0
        self.frame_cache_hits = 0
        self.write_calls = 0
        self.duplicate_writes_avoided = 0

    @property
    def levels(self):
        """Last four values written, in CL0..CL3 API order."""
        return self._last_levels

    def _scan(self, frame_index, packed):
        if (
            self._frame_valid is not None
            and 0 <= frame_index < len(self._frame_valid)
            and self._frame_valid[frame_index]
        ):
            start = frame_index * ZONE_COUNT
            for zone in range(ZONE_COUNT):
                self._target[zone] = self._frame_targets[start + zone]
            self.frame_cache_hits += 1
            return
        zones = quadrant_energy(
            packed, self.columns, self.rows, self._energies
        )
        scale = self._energy_scale
        for zone in range(ZONE_COUNT):
            self._target[zone] = min(255, zones[zone] * 255 // scale)
        if self._frame_valid is not None and 0 <= frame_index < len(self._frame_valid):
            start = frame_index * ZONE_COUNT
            for zone in range(ZONE_COUNT):
                self._frame_targets[start + zone] = self._target[zone]
            self._frame_valid[frame_index] = 1
        self.frame_scans += 1

    def update(self, frame_index, packed, now_ms):
        """Consume the presented asset frame; return True on a PWM write."""
        if frame_index != self._last_frame:
            self._scan(frame_index, packed)
            self._last_frame = frame_index

        if (
            self._next_update is not None
            and self._ticks_diff(now_ms, self._next_update) < 0
        ):
            return False
        self._next_update = self._ticks_add(now_ms, self.interval_ms)

        # Faster attack, slower release: the quadrant catches a sweep promptly
        # but fades over several light updates instead of snapping off.
        for zone in range(ZONE_COUNT):
            current = self._smoothed[zone]
            target = self._target[zone]
            if target >= current:
                current = (current + target + 1) // 2
            else:
                current = (current * 3 + target + 2) // 4
            self._smoothed[zone] = current

        zone_buckets = [
            (value * self.quantization_steps + 127) // 255
            for value in self._smoothed
        ]
        channels = [0.0, 0.0, 0.0, 0.0]
        for zone, channel in enumerate(self.channel_for_zone):
            channels[channel] = self._level_table[zone_buckets[zone]]
        levels = tuple(channels)
        if levels == self._last_levels:
            self.duplicate_writes_avoided += 1
            return False
        self.writer(*levels)
        self._last_levels = levels
        self.write_calls += 1
        return True

    def close(self):
        """Restore all lights off.  Safe to call from a ``finally`` block."""
        self.writer(0, 0, 0, 0)
        self._last_levels = (0.0, 0.0, 0.0, 0.0)
        self.write_calls += 1
