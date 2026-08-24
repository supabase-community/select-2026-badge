"""Retained Glyph surface for use underneath independently drawn UI.

The boot player can diff-draw directly into the display because it owns every
pixel.  A launcher or game cannot: moving UI would leave stale pixels whenever
the recorded Glyph cell underneath did not change.  ``GlyphBackdrop`` keeps the
diff-drawn animation in one offscreen RGBA image, then restores that complete
image before the app draws its foreground.

The class is pure Python and receives Badgeware's injected graphics objects.
It intentionally does not call ``display.update`` or poll input; the host app
retains its normal frame and input policy.
"""

import glyph_render


def make_ambient_lut(rgba_lut, tint=(62, 207, 142), strength=40):
    """Return a low-contrast monochrome LUT for UI backgrounds.

    Tile generation uses the transformed table directly, so dimming costs
    nothing per frame and avoids painting a full-screen translucent rectangle.
    ``strength`` is a percentage of the chosen tint's peak intensity.
    """
    if len(rgba_lut) < glyph_render.LUT_BYTES:
        raise ValueError("RGBA LUT is too small")
    if len(tint) != 3 or any(channel < 0 or channel > 255 for channel in tint):
        raise ValueError("tint must contain three byte values")
    if strength < 0 or strength > 100:
        raise ValueError("strength must be in 0..100")
    output = bytearray(glyph_render.LUT_BYTES)
    denominator = 255 * 100
    channel_tables = []
    for channel in tint:
        table = bytearray(256)
        for peak in range(256):
            table[peak] = channel * peak * strength // denominator
        channel_tables.append(table)
    for offset in range(0, glyph_render.LUT_BYTES, 4):
        peak = max(rgba_lut[offset], rgba_lut[offset + 1], rgba_lut[offset + 2])
        output[offset] = channel_tables[0][peak]
        output[offset + 1] = channel_tables[1][peak]
        output[offset + 2] = channel_tables[2][peak]
        output[offset + 3] = rgba_lut[offset + 3]
    return output


class GlyphBackdrop:
    """Clock-driven retained surface for one loaded ``GlyphStream``."""

    def __init__(
        self,
        stream,
        mask_bank,
        rgba_lut,
        image_ctor,
        vec2_ctor,
        width=160,
        height=120,
    ):
        self.stream = stream
        self.surface = image_ctor(width, height)
        self._vec2 = vec2_ctor
        self._target = glyph_render.BlitTarget(self.surface, image_ctor, vec2_ctor)
        self.renderer = glyph_render.GlyphRenderer(
            mask_bank,
            rgba_lut,
            stream.columns,
            stream.rows,
            width,
            height,
            self._target,
        )
        self.last_frame = -1

    @property
    def tile_cache_entries(self):
        return len(self._target._tiles)

    def update(self, elapsed_ms, time_scale_milli=1000, force=False):
        """Advance from a caller-owned clock; return repainted cell count.

        Recorded playback remains wall-clock derived, so an overloaded app
        drops obsolete animation frames instead of slowing its game/UI clock.
        """
        frame = self.stream.frame_at(elapsed_ms, time_scale_milli)
        if not force and frame == self.last_frame:
            return 0
        # ``frame=`` enables the renderer's changed-cell memo. The backdrop is
        # the case it helps most often: a host app repaints it every update
        # forever, so every transition in the loop is walked once and then
        # replayed from the cache for the rest of the session.
        drawn = self.renderer.draw(
            self.stream.frame_view(frame), force=force, frame=frame
        )
        self.last_frame = frame
        return drawn

    def draw_to(self, screen):
        """Restore the complete retained backdrop before foreground drawing."""
        screen.blit(self.surface, self._vec2(0, 0))

    def reset(self):
        """Force a complete surface refresh on the next ``update``."""
        self.renderer.reset()
        self.last_frame = -1
