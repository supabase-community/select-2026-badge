"""Deterministic rich-light scales for the committed 32x12 Glyph deck.

Values are displayed quadrant-luminance p95 and one-frame delta p95 from
``glyph2x_lab/host/analyze_rich_lights_2x.py``. Promoted into the product viewer
so its all-technique lights remain calibrated without the lab app installed.
"""


DEFAULT = (64, 32, 0.45)

TECHNIQUE_CALIBRATION_2X = {
    "radar": (77, 13, 0.45),
    "wave": (111, 2, 0.45),
    "signal-ripple": (23, 8, 0.45),
    "arrow-field": (189, 17, 0.45),
    "ring-buffer": (13, 2, 0.45),
    "brackets": (11, 1, 0.45),
    "tracks": (3, 1, 0.45),
    "signal-histogram": (131, 2, 0.45),
    "binary-island": (108, 2, 0.45),
    "arrow-cleanse": (174, 4, 0.45),
    "alphabet": (208, 1, 0.45),
    "memory-compactor": (40, 3, 0.45),
    "numbers": (210, 1, 0.45),
    "column": (19, 1, 0.45),
    "marquee": (65, 7, 0.45),
    "terminal-marquee": (47, 1, 0.45),
    "packet-router": (12, 4, 0.45),
    "fluid-field": (74, 1, 0.45),
}


def calibration_for(technique):
    return TECHNIQUE_CALIBRATION_2X.get(technique, DEFAULT)
