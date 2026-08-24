"""Wave-only rear-light choreography locked to the wave spawn lifecycle.

Owner brief (Sam, 2026-08-16): the wave technique is a radial sine; a wave
rises from zero to full height at the dead center of the line, splits, and
travels outward while the center falls back to zero as the next wave
spawns.  While the wave asset plays, the TOP and BOTTOM light pairs crossfade
twice as fast as the captured wave lifecycle: each swap takes half a lifecycle
and the full light period is one lifecycle.  This is the owner-requested visual
revision after reviewing the spawn-locked one-swap-per-lifecycle build on
hardware.  The authored-frame lock still holds at any playback speed and at
both densities; the wave animation itself is unchanged.

Lifecycle receipts (derive with ``glyph/host/derive_wave_lifecycle.py``):

* Engine source (select-main frames/faces/basic.ts, waveFace): amplitude =
  (sin(distance*9 - timeMs*0.006 + phase) + 1) / 2, so the dead center is a
  pure sinusoid at 0.006 rad/engine-ms.  One lifecycle = 2*pi/0.006 =
  1047.19755 engine-ms.  Both committed wave captures are 64 frames over a
  loop-exact 1047.198 engine-ms period: 64.0000 frames per lifecycle, one
  lifecycle per loop.
* Empirical (both assets): the smallest circular shift mapping the center
  cell's glyph-level series onto itself is 64 frames, and the whole frame
  sequence agrees; a half-loop shift mismatches 58/64 frames, ruling out
  two spawns per loop.  The dead-center spawn (amplitude minimum) sits at
  authored frame 16.000 in both captures (phase fit 0.00000 rad, zero
  quantization error, corroborated by the observed minimum-level runs).

Design rules, each load-bearing:

* Keyed to the AUTHORED FRAME INDEX, never wall time: the envelope phase is
  a pure function of how many authored frames the player has presented, so
  cadence multipliers (the 2x wake sting, lab rate overrides) cannot
  stretch or shear the fade.  Loop parity is tracked by accumulating
  forward frame deltas modulo the asset frame count, which also survives
  clock resets and skipped frames.
* Perceptually even fade: ``badge.caselights`` applies its own 2.2 gamma to
  the requested level, so the request axis is already perceptual; a LINEAR
  triangle in request space is the even fade, and double gamma correction
  would be wrong.  The same even-rate linear triangle was physically
  approved by the owner for the lab's wave experiment
  (glyph_lab/README.md, 2026-08-15).
* One write at most per authored frame change, duplicate-suppressed: the
  authored cadence (30.6/s at 1x, 61/s in the 2x sting) is the rate limit.
  A wall-clock throttle is deliberately absent: the lab measured that the
  generic 50 ms sampler skipped envelope targets and enlarged brightness
  jumps on wave (glyph_lab/README.md).
* The brightness cap defaults to the owner-selected full product range (1.0).
  The first wired build accidentally inherited ``GlyphLightSync``'s old 0.24
  control ceiling and was visibly rejected on hardware; the wave choreography
  must retain its exact dark endpoints while allowing each pair to reach the
  Badgeware API's full 1.0 input at its spawn handoff.
* The light envelope advances at 2x the authored wave phase.  A 64-frame wave
  therefore swaps pairs in 32 frames and returns in 64.  This is deliberately
  a wave-only product choice; the other 17 techniques are untouched.
* The physical channel order consumes the review card's persisted mapping
  (``/glyph-review.json``, ``cl_mapping.channel_for_zone``) when present.
  The documented fallback is the 2026-08-14 full-brightness rear sweep:
  screen zones (TL, BL, TR, BR) map to API channels (1, 2, 0, 3)
  (glyph_lab/README.md).

No hardware imports: apps pass ``badge.caselights``; host tests pass plain
callables.
"""

import json
import math

WAVE_TECHNIQUE = "wave"
ZONE_COUNT = 4

# Angular frequency of waveFace's temporal sine, radians per engine-ms.
WAVE_OMEGA = 0.006

# (columns, visible rows) -> (frames_per_lifecycle, spawn_offset_frames).
# Values are host-derived from engine math AND the committed captures by
# glyph/host/derive_wave_lifecycle.py (module docstring holds the receipts);
# test_wave_lights.py re-derives both routes so a recapture cannot drift
# this table silently.  No on-device analysis happens.
LIFECYCLE_TABLE = {
    (16, 6): (64, 16),
    (32, 12): (64, 16),
}

# Fallback physical map, screen zones (TL, BL, TR, BR) -> CL channels.
# Receipt: 2026-08-14 full-brightness rear sweep (glyph_lab/README.md):
# rear view CL0 top-left, CL1 top-right, CL2 bottom-right, CL3 bottom-left.
DEFAULT_CHANNEL_FOR_ZONE = (1, 2, 0, 3)

# Owner-selected product ceiling. Keep the older GlyphLightSync control at 0.24;
# wave is a separate choreography whose physical review requires full endpoints.
DEFAULT_MAX_LEVEL = 1.0

# Owner-selected wave-light tempo: two pair swaps per authored wave lifecycle.
LIGHT_PHASE_MULTIPLIER = 2

REVIEW_STATE_PATH = "/glyph-review.json"


def lifecycle_for(technique, columns, rows):
    """(frames_per_lifecycle, spawn_offset) for a wave stream, else None."""
    if technique != WAVE_TECHNIQUE:
        return None
    return LIFECYCLE_TABLE.get((columns, rows))


def expected_frames_per_lifecycle(frame_count, period_engine_us):
    """Route-A engine math for receipts and drift tests."""
    lifecycle_engine_us = 2 * math.pi / WAVE_OMEGA * 1000.0
    return frame_count * lifecycle_engine_us / period_engine_us


def channel_map_from_review(path=REVIEW_STATE_PATH):
    """channel_for_zone persisted by the review card, or None.

    Loud failure is wrong here: a missing or unreadable review state simply
    means the owner has not run the identification card on this badge, so
    the caller falls back to the documented measured default.
    """
    try:
        with open(path) as source:
            state = json.load(source)
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    mapping = state.get("cl_mapping")
    if not isinstance(mapping, dict):
        return None
    channels = mapping.get("channel_for_zone")
    if not isinstance(channels, list) or sorted(channels) != [0, 1, 2, 3]:
        return None
    return tuple(channels)


def envelope_pair(slot, frames_per_lifecycle):
    """(top, bottom) request bytes for one slot of the base triangle.

    A linear triangle in request space with round-half-up endpoints: slot 0
    is exactly (0, 255), slot ``frames_per_lifecycle`` is exactly (255, 0),
    and the two ramps are time mirrors. The product choreography samples this
    base triangle at ``LIGHT_PHASE_MULTIPLIER`` times authored-wave phase.
    """
    period = 2 * frames_per_lifecycle
    slot %= period
    if slot > frames_per_lifecycle:
        slot = period - slot
    top = (510 * slot + frames_per_lifecycle) // period
    return top, 255 - top


class WaveLightChoreography:
    """Frame-locked top/bottom crossfade for one playing wave stream."""

    def __init__(
        self,
        writer,
        frame_count,
        frames_per_lifecycle,
        spawn_offset_frames,
        channel_for_zone=DEFAULT_CHANNEL_FOR_ZONE,
        max_level=DEFAULT_MAX_LEVEL,
    ):
        if frame_count < 1:
            raise ValueError("frame_count must be positive")
        if frames_per_lifecycle < 1:
            raise ValueError("frames_per_lifecycle must be positive")
        if frame_count % frames_per_lifecycle:
            # Spawn alignment needs the loop to hold whole lifecycles;
            # both committed assets hold exactly one.
            raise ValueError("frame_count must be a multiple of the lifecycle")
        if not 0 <= spawn_offset_frames < frames_per_lifecycle:
            raise ValueError("spawn offset must sit inside one lifecycle")
        if sorted(channel_for_zone) != [0, 1, 2, 3]:
            raise ValueError("channel_for_zone must be a permutation of 0..3")
        if not 0 <= max_level <= 1:
            raise ValueError("max_level must be in 0..1")
        self.writer = writer
        self.frame_count = frame_count
        self.frames_per_lifecycle = frames_per_lifecycle
        self.spawn_offset_frames = spawn_offset_frames
        self.channel_for_zone = tuple(channel_for_zone)
        self.max_level = max_level
        period = (2 * frames_per_lifecycle) // LIGHT_PHASE_MULTIPLIER
        self._period = period
        # Authored-frame cache: four request bytes per unrolled slot, with
        # the physical channel order baked in, so the per-frame hot path is
        # four byte reads and four multiplies (256 B for the 64-frame deck at
        # the owner-selected 2x light phase).
        table = bytearray(period * ZONE_COUNT)
        for slot in range(period):
            top, bottom = envelope_pair(
                LIGHT_PHASE_MULTIPLIER * (slot - spawn_offset_frames),
                frames_per_lifecycle,
            )
            zone_bytes = (top, bottom, top, bottom)  # TL, BL, TR, BR
            base = slot * ZONE_COUNT
            for zone in range(ZONE_COUNT):
                table[base + self.channel_for_zone[zone]] = zone_bytes[zone]
        self._table = bytes(table)
        self._scale = max_level / 255.0
        self._unrolled = -1
        self._last_frame = -1
        self._last_levels = None
        self.write_calls = 0
        self.duplicate_writes_avoided = 0

    @property
    def levels(self):
        """Last four values written, in CL0..CL3 API order."""
        return self._last_levels or (0.0, 0.0, 0.0, 0.0)

    def update(self, frame_index):
        """Consume the presented authored frame; return True on a PWM write."""
        if not 0 <= frame_index < self.frame_count:
            raise ValueError("frame %d outside the asset" % frame_index)
        if frame_index == self._last_frame:
            return False
        if self._last_frame < 0:
            self._unrolled = frame_index % self._period
        else:
            delta = (frame_index - self._last_frame) % self.frame_count
            self._unrolled = (self._unrolled + delta) % self._period
        self._last_frame = frame_index
        base = self._unrolled * ZONE_COUNT
        scale = self._scale
        table = self._table
        levels = (
            table[base] * scale,
            table[base + 1] * scale,
            table[base + 2] * scale,
            table[base + 3] * scale,
        )
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
