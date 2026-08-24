"""Shared controls and low-overhead HUD metrics for the two Glyph viewers.

Pure Python with injected tick helpers.  The product entries own drawing and
buttons; this module keeps their speed/playhead and metric semantics identical.
"""


SPEED_LEVELS_MILLI = (
    0, 250, 500, 750, 1000, 1250, 1500, 2000, 3000, 4000, 5000
)
DEFAULT_SPEED_MILLI = 1000
SNAPSHOT_MS = 1000


def format_x10(value):
    """One decimal without allocating a float on the badge."""
    if value < 0:
        return "-"
    return "%d.%d" % (value // 10, value % 10)


def format_speed_milli(value):
    """Compact playback multiplier for the 160 px HUD."""
    if value < 0:
        raise ValueError("speed must not be negative")
    whole = value // 1000
    remainder = value % 1000
    if remainder == 0:
        return "%dX" % whole
    if remainder % 100 == 0:
        fraction = "%d" % (remainder // 100)
    else:
        fraction = "%02d" % (remainder // 10)
    prefix = "%d" % whole if whole else ""
    return "%s.%sX" % (prefix, fraction)


class SpeedClock:
    """Clock-derived playhead whose phase survives speed changes."""

    def __init__(self, now_ms, ticks_diff=None, levels=SPEED_LEVELS_MILLI):
        if not levels or DEFAULT_SPEED_MILLI not in levels:
            raise ValueError("speed ladder must contain the 1x default")
        if any(level < 0 for level in levels):
            raise ValueError("speed levels must not be negative")
        if tuple(levels) != tuple(sorted(set(levels))):
            raise ValueError("speed levels must be strictly increasing")
        self._diff = ticks_diff or (lambda left, right: left - right)
        self.levels = tuple(levels)
        self.index = self.levels.index(DEFAULT_SPEED_MILLI)
        self._anchor_ms = now_ms
        self._scaled_before_anchor = 0

    @property
    def scale_milli(self):
        return self.levels[self.index]

    def elapsed(self, now_ms):
        wall_ms = max(0, self._diff(now_ms, self._anchor_ms))
        return self._scaled_before_anchor + wall_ms * self.scale_milli // 1000

    def reset(self, now_ms):
        self._anchor_ms = now_ms
        self._scaled_before_anchor = 0

    def step(self, direction, now_ms):
        """Clamp one ladder step and preserve the current animation phase."""
        if direction not in (-1, 1):
            raise ValueError("speed direction must be -1 or 1")
        old_index = self.index
        new_index = max(0, min(len(self.levels) - 1, old_index + direction))
        if new_index == old_index:
            return False
        current = self.elapsed(now_ms)
        self._scaled_before_anchor = current
        self._anchor_ms = now_ms
        self.index = new_index
        return True


class ViewerMetrics:
    """Animation FPS, managed-loop FPS and changed-frame slot use."""

    def __init__(self, now_ms, ticks_diff=None, window=64):
        if window < 2:
            raise ValueError("metrics window must hold at least two frames")
        self._diff = ticks_diff or (lambda left, right: left - right)
        self._frames_since = 0
        self._updates_since = 0
        self._work_total_since = 0
        self._work_frames_since = 0
        self._snapshot_at = now_ms
        self.fps_x10 = -1
        self.loop_fps_x10 = -1
        self.slot_pct = -1

    def reset(self, now_ms):
        self._frames_since = 0
        self._updates_since = 0
        self._work_total_since = 0
        self._work_frames_since = 0
        self._snapshot_at = now_ms
        self.fps_x10 = -1
        self.loop_fps_x10 = -1
        self.slot_pct = -1

    def note_update(self):
        """Count one managed update callback, including unchanged frames."""
        self._updates_since += 1

    def note_frame(self, work_us):
        work_us = max(0, work_us)
        self._frames_since += 1
        self._work_total_since += work_us
        self._work_frames_since += 1

    def update(self, now_ms, slot_us):
        """Refresh once per second; return True when HUD values changed."""
        elapsed = self._diff(now_ms, self._snapshot_at)
        if elapsed < SNAPSHOT_MS:
            return False
        self.fps_x10 = self._frames_since * 10000 // max(1, elapsed)
        self.loop_fps_x10 = self._updates_since * 10000 // max(1, elapsed)
        if self._work_frames_since and slot_us > 0:
            mean_work = self._work_total_since // self._work_frames_since
            self.slot_pct = mean_work * 100 // slot_us
        else:
            # Pause has no target slot and no changed-frame work. Reporting 0
            # is actionable; retaining an old animation sample is not.
            self.slot_pct = 0
        self._frames_since = 0
        self._updates_since = 0
        self._work_total_since = 0
        self._work_frames_since = 0
        self._snapshot_at = now_ms
        return True
