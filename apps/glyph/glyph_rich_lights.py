"""Full-range all-technique Glyph-to-case-light product mapper.

Promoted from the hardware-timed Glyph Lab mapper after the owner selected
full-range motion lights for the two simple deck viewers. The older
``glyph_lights.GlyphLightSync`` remains available as the conservative control.
This richer mapper differs in five measurable ways:

* it follows the luminance of the pixels actually displayed (palette, mask and
  inverse state), not mask coverage alone;
* a motion mode adds a calibrated accent from frame-to-frame luminance change;
* 32/40/48 buckets are uniform in perceived API-input space, before Badgeware
  applies its documented ``input ** 2.2`` PWM gamma;
* attack/release and per-technique luma/motion scales are explicit;
* a rolling budget limits mean *post-gamma PWM duty* across all four lights.

There are no hardware imports. The product app passes ``badge.caselights`` and
tick helpers; host tests replay the production assets with ordinary callables.
"""


ZONE_COUNT = 4
GAMMA = 2.2

CURVES = ("linear", "lift", "contrast")
MODES = ("luma", "motion")
CHOREOGRAPHIES = (None, "wave_vertical")

# Host-derived defaults are intentionally conservative until the complete
# asset replay writes a per-technique table.  The values are normalized bytes:
# luma_scale is the displayed quadrant luminance that maps to full target;
# motion_scale is the absolute one-frame delta that maps to full accent.
DEFAULT_LUMA_SCALE = 64
DEFAULT_MOTION_SCALE = 32
DEFAULT_MOTION_WEIGHT = 0.45

# Generated from the committed 16x6 streams by
# ``glyph_lab/host/analyze_rich_lights.py``. Each tuple is displayed-luma p95,
# absolute frame-delta p95, motion weight. Unknown/future assets use defaults.
TECHNIQUE_CALIBRATION = {
    "radar": (83, 19, 0.45),
    "wave": (116, 4, 0.45),
    "signal-ripple": (27, 8, 0.45),
    "arrow-field": (184, 23, 0.45),
    "ring-buffer": (19, 7, 0.45),
    "brackets": (12, 1, 0.45),
    "tracks": (7, 1, 0.45),
    "signal-histogram": (98, 4, 0.45),
    "binary-island": (121, 5, 0.45),
    "arrow-cleanse": (176, 15, 0.45),
    "alphabet": (190, 6, 0.45),
    "memory-compactor": (86, 8, 0.45),
    "numbers": (223, 4, 0.45),
    "column": (19, 1, 0.45),
    "marquee": (57, 16, 0.45),
    "terminal-marquee": (75, 2, 0.45),
    "packet-router": (20, 10, 0.45),
    "fluid-field": (83, 2, 0.45),
}


def calibration_for(technique):
    """Return (luma_scale, motion_scale, motion_weight)."""
    return TECHNIQUE_CALIBRATION.get(
        technique,
        (DEFAULT_LUMA_SCALE, DEFAULT_MOTION_SCALE, DEFAULT_MOTION_WEIGHT),
    )


def glyph_coverages(mask_bank, mask_bytes=200):
    """Mean 0..255 coverage for every glyph record."""
    if mask_bytes < 1 or len(mask_bank) % mask_bytes:
        raise ValueError("mask bank length is not a whole number of records")
    values = bytearray(len(mask_bank) // mask_bytes)
    glyph = 0
    for start in range(0, len(mask_bank), mask_bytes):
        values[glyph] = sum(mask_bank[start : start + mask_bytes]) // mask_bytes
        glyph += 1
    return values


def palette_luminances(rgba_lut):
    """Return five Rec.709-ish luminance bytes from the compositor LUT."""
    if len(rgba_lut) < 10 * 256 * 4:
        raise ValueError("RGBA LUT is too small")
    values = bytearray(5)
    for color in range(5):
        offset = (color * 256 + 255) * 4
        red, green, blue = rgba_lut[offset : offset + 3]
        values[color] = (54 * red + 183 * green + 19 * blue + 128) // 256
    return values


def quadrant_luminance(packed, columns, rows, coverages, palette_luma):
    """Mean displayed-pixel luminance in logical TL, BL, TR, BR order."""
    cell_count = columns * rows
    if columns < 2 or rows < 2:
        raise ValueError("light sync needs a grid of at least 2x2 cells")
    if len(packed) < cell_count * 2:
        raise ValueError("packed frame is smaller than the grid")
    split_x = columns // 2
    split_y = rows // 2
    totals = [0, 0, 0, 0]
    counts = [0, 0, 0, 0]
    for index in range(cell_count):
        offset = index * 2
        glyph = packed[offset]
        style = packed[offset + 1]
        if glyph >= len(coverages):
            raise ValueError("glyph id %d outside the mask bank" % glyph)
        nibble = style & 0x0F
        color = (nibble - 1) % 5 if nibble else 0
        coverage = coverages[glyph]
        if style & 0x80:
            coverage = 255 - coverage
        value = (coverage * palette_luma[color] + 127) // 255
        x = index % columns
        y = index // columns
        zone = (2 if x >= split_x else 0) + (1 if y >= split_y else 0)
        totals[zone] += value
        counts[zone] += 1
    return tuple(
        (totals[zone] + counts[zone] // 2) // counts[zone]
        for zone in range(ZONE_COUNT)
    )


def _curve_table(name):
    if name not in CURVES:
        raise ValueError("unknown light curve %r" % name)
    values = bytearray(256)
    for value in range(256):
        if name == "linear":
            curved = value
        elif name == "lift":
            curved = int((value * 255) ** 0.5 + 0.5)
        else:
            # Integer smoothstep: darker low end, stronger high-end separation.
            curved = (
                value * value * (3 * 255 - 2 * value) + (255 * 255 // 2)
            ) // (255 * 255)
        values[value] = max(0, min(255, curved))
    return values


def perceptual_bucket_table(max_level, states):
    """API levels uniformly spaced after accounting for Badgeware gamma.

    Badgeware converts the requested perceptual level to PWM duty with
    ``level ** 2.2``.  Linear spacing here is therefore linear in perceived
    brightness; the companion duty table is deliberately nonlinear.
    """
    if not 0 <= max_level <= 1:
        raise ValueError("max_level must be in 0..1")
    if states < 2:
        raise ValueError("states must include off and at least one lit state")
    return tuple(max_level * index / (states - 1) for index in range(states))


def wave_vertical_targets(frame_count, phase_frames=0):
    """Return one even full-range top/bottom crossfade per authored loop.

    Zone order is TL, BL, TR, BR.  A linear triangle gives exact endpoints and
    a constant visual handoff rate; the earlier smoothstep moved 50% faster at
    mid-fade and felt rushed despite matching the measured edge phase.
    ``phase_frames`` rotates the authored curve so its extrema can follow the
    visible wave at the outer screen edge rather than an arbitrary capture
    boundary. The table is built once when a wave synchronizer is attached;
    the per-frame path remains four byte reads.
    """
    if frame_count < 2:
        raise ValueError("wave choreography needs at least two frames")
    if not isinstance(phase_frames, int):
        raise ValueError("wave choreography phase must be an integer")
    phase_frames %= frame_count
    values = bytearray(frame_count * ZONE_COUNT)
    for frame in range(frame_count):
        phase = ((frame + phase_frames) % frame_count) * 510 // frame_count
        top = 255 - phase if phase <= 255 else phase - 255
        bottom = 255 - top
        start = frame * ZONE_COUNT
        values[start : start + ZONE_COUNT] = bytes((top, bottom, top, bottom))
    return values


class RollingDutyBudget:
    """Bounds mean post-gamma duty across four channels and a fixed window."""

    def __init__(self, max_average, samples):
        if not 0 < max_average <= 1:
            raise ValueError("max_average must be in (0, 1]")
        if samples < 1:
            raise ValueError("budget samples must be positive")
        self.max_average = max_average
        self.samples = samples
        self._history = [0.0] * samples
        self._count = 0
        self._next = 0
        self._sum = 0.0
        self.peak_rolling_average = 0.0
        self.limited_updates = 0

    @property
    def rolling_average(self):
        return self._sum / self._count if self._count else 0.0

    def constrain(self, bucket_indices, duty_table):
        """Return budget-safe indices while staying on perceptual buckets."""
        indices = list(bucket_indices)
        outgoing = self._history[self._next] if self._count == self.samples else 0.0
        prior_sum = self._sum - outgoing
        next_count = min(self.samples, self._count + 1)
        allowed_sample = max(0.0, self.max_average * next_count - prior_sum)

        def sample_duty():
            return sum(duty_table[index] for index in indices) / ZONE_COUNT

        duty = sample_duty()
        if duty > allowed_sample + 1e-12:
            self.limited_updates += 1
            if duty > 0 and allowed_sample > 0:
                ratio = allowed_sample / duty
                for channel in range(ZONE_COUNT):
                    indices[channel] = int(indices[channel] * ratio)
            else:
                indices = [0, 0, 0, 0]
            duty = sample_duty()
            # Integer bucket rounding can still leave a small excess. Lower
            # the most expensive channel until the invariant is exact.
            while duty > allowed_sample + 1e-12 and any(indices):
                channel = max(range(ZONE_COUNT), key=lambda item: indices[item])
                indices[channel] -= 1
                duty = sample_duty()

        self._history[self._next] = duty
        self._next = (self._next + 1) % self.samples
        if self._count < self.samples:
            self._count += 1
        self._sum = prior_sum + duty
        average = self.rolling_average
        if average > self.peak_rolling_average:
            self.peak_rolling_average = average
        return tuple(indices)


class RichGlyphLightSync:
    """Displayed-luminance synchronizer with optional motion accent."""

    def __init__(
        self,
        writer,
        mask_bank,
        rgba_lut,
        technique,
        columns,
        rows,
        channel_for_zone=(0, 1, 2, 3),
        mode="luma",
        max_level=1.0,
        duty_budget=0.35,
        budget_window_ms=2000,
        interval_ms=50,
        states=40,
        attack_ms=50,
        release_ms=300,
        curve="linear",
        luma_scale=None,
        motion_scale=None,
        motion_weight=None,
        frame_count=None,
        mask_bytes=200,
        choreography=None,
        choreography_phase_frames=0,
        ticks_diff=None,
        ticks_add=None,
    ):
        if sorted(channel_for_zone) != [0, 1, 2, 3]:
            raise ValueError("channel_for_zone must be a permutation of 0..3")
        if mode not in MODES:
            raise ValueError("mode must be luma or motion")
        if choreography not in CHOREOGRAPHIES:
            raise ValueError("unknown light choreography %r" % choreography)
        if interval_ms < 1:
            raise ValueError("interval_ms must be positive")
        if attack_ms < 0 or release_ms < 0:
            raise ValueError("attack/release must not be negative")
        calibrated_luma, calibrated_motion, calibrated_weight = calibration_for(
            technique
        )
        if luma_scale is None:
            luma_scale = calibrated_luma
        if motion_scale is None:
            motion_scale = calibrated_motion
        if motion_weight is None:
            motion_weight = calibrated_weight
        if luma_scale < 1 or motion_scale < 1:
            raise ValueError("calibration scales must be positive")
        if motion_weight < 0:
            raise ValueError("motion_weight must not be negative")
        if frame_count is not None and frame_count < 1:
            raise ValueError("frame_count must be positive")
        if choreography is not None and frame_count is None:
            raise ValueError("light choreography needs frame_count")
        if not isinstance(choreography_phase_frames, int):
            raise ValueError("light choreography phase must be an integer")
        self.writer = writer
        self.technique = technique
        self.columns = columns
        self.rows = rows
        self.channel_for_zone = tuple(channel_for_zone)
        self.mode = mode
        self.max_level = max_level
        self.interval_ms = interval_ms
        self.states = states
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.curve = curve
        self.luma_scale = luma_scale
        self.motion_scale = motion_scale
        self.motion_weight = motion_weight
        self.choreography = choreography
        self.choreography_phase_frames = choreography_phase_frames
        self._ticks_diff = ticks_diff or (lambda left, right: left - right)
        self._ticks_add = ticks_add or (lambda value, delta: value + delta)
        self._coverages = glyph_coverages(mask_bank, mask_bytes)
        self._palette_luma = palette_luminances(rgba_lut)
        self._curve = _curve_table(curve)
        self._levels = perceptual_bucket_table(max_level, states)
        self._duties = tuple(level ** GAMMA for level in self._levels)
        samples = max(1, budget_window_ms // interval_ms)
        self._budget = RollingDutyBudget(duty_budget, samples)
        self._frame_luma = (
            bytearray(frame_count * ZONE_COUNT) if frame_count is not None else None
        )
        self._frame_valid = bytearray(frame_count) if frame_count is not None else None
        self._choreography = (
            wave_vertical_targets(frame_count, choreography_phase_frames)
            if choreography == "wave_vertical"
            else None
        )
        self._luma = [0, 0, 0, 0]
        self._previous_luma = [0, 0, 0, 0]
        self._smoothed = [0, 0, 0, 0]
        self._last_frame = -1
        self._next_update = None
        self._last_levels = (0.0, 0.0, 0.0, 0.0)
        self.frame_scans = 0
        self.frame_cache_hits = 0
        self.write_calls = 0
        self.duplicate_writes_avoided = 0
        self.motion_accent_updates = 0
        self.choreography_frames = 0
        self.peak_input = 0.0

    @property
    def levels(self):
        return self._last_levels

    @property
    def rolling_duty(self):
        return self._budget.rolling_average

    @property
    def peak_rolling_duty(self):
        return self._budget.peak_rolling_average

    @property
    def budget_limited_updates(self):
        return self._budget.limited_updates

    def _scan(self, frame_index, packed):
        for zone in range(ZONE_COUNT):
            self._previous_luma[zone] = self._luma[zone]
        if self._choreography is not None:
            start = frame_index * ZONE_COUNT
            for zone in range(ZONE_COUNT):
                self._luma[zone] = self._choreography[start + zone]
            self.choreography_frames += 1
            return
        if (
            self._frame_valid is not None
            and 0 <= frame_index < len(self._frame_valid)
            and self._frame_valid[frame_index]
        ):
            start = frame_index * ZONE_COUNT
            for zone in range(ZONE_COUNT):
                self._luma[zone] = self._frame_luma[start + zone]
            self.frame_cache_hits += 1
            return
        values = quadrant_luminance(
            packed, self.columns, self.rows, self._coverages, self._palette_luma
        )
        for zone in range(ZONE_COUNT):
            self._luma[zone] = values[zone]
        if self._frame_valid is not None and 0 <= frame_index < len(self._frame_valid):
            start = frame_index * ZONE_COUNT
            for zone in range(ZONE_COUNT):
                self._frame_luma[start + zone] = values[zone]
            self._frame_valid[frame_index] = 1
        self.frame_scans += 1

    def _target(self, zone):
        if self._choreography is not None:
            return self._luma[zone]
        base = min(255, self._luma[zone] * 255 // self.luma_scale)
        if self.mode == "motion":
            delta = abs(self._luma[zone] - self._previous_luma[zone])
            accent = min(255, delta * 255 // self.motion_scale)
            if accent:
                self.motion_accent_updates += 1
            base = min(255, int(base + accent * self.motion_weight + 0.5))
        return self._curve[base]

    def _smooth(self, current, target):
        duration = self.attack_ms if target >= current else self.release_ms
        if duration <= self.interval_ms:
            return target
        delta = target - current
        step = abs(delta) * self.interval_ms // duration
        if step < 1 and delta:
            step = 1
        return current + step if delta > 0 else current - step

    def update(self, frame_index, packed, now_ms):
        """Consume the displayed frame; return True only on a PWM write."""
        frame_changed = frame_index != self._last_frame
        if frame_changed:
            self._scan(frame_index, packed)
            self._last_frame = frame_index
        if (
            not (self._choreography is not None and frame_changed)
            and self._next_update is not None
            and self._ticks_diff(now_ms, self._next_update) < 0
        ):
            return False
        self._next_update = self._ticks_add(now_ms, self.interval_ms)

        indices = [0, 0, 0, 0]
        for zone in range(ZONE_COUNT):
            target = self._target(zone)
            # The authored-loop choreography is already a complete fade. Applying
            # a second attack/release filter would shift it off the displayed
            # wave and prevent either pair from reaching the requested 100%.
            value = target if self._choreography is not None else self._smooth(
                self._smoothed[zone], target
            )
            self._smoothed[zone] = value
            indices[zone] = (value * (self.states - 1) + 127) // 255
        indices = self._budget.constrain(indices, self._duties)

        channels = [0.0, 0.0, 0.0, 0.0]
        for zone, channel in enumerate(self.channel_for_zone):
            channels[channel] = self._levels[indices[zone]]
        levels = tuple(channels)
        peak = max(levels)
        if peak > self.peak_input:
            self.peak_input = peak
        if levels == self._last_levels:
            self.duplicate_writes_avoided += 1
            return False
        self.writer(*levels)
        self._last_levels = levels
        self.write_calls += 1
        return True

    def close(self):
        self.writer(0, 0, 0, 0)
        self._last_levels = (0.0, 0.0, 0.0, 0.0)
        self.write_calls += 1
