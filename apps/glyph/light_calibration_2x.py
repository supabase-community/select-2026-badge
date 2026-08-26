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
    # RE-DERIVED 2026-08-26 from (13, 2) when the fill was capped at four
    # rings: a third fewer lit cells drops the displayed-luma p95 and the
    # one-frame delta p95 with it.
    #
    # ⚠ NOT the lights an unconfigured badge shows, though it is that badge's
    # DEFAULT_BACKGROUND since 2026-08-26: `badgecard` and `poster` both call
    # `badge.caselights(0)` at their entry seam, so a worn badge is DARK behind
    # whatever it wears. These scales reach a panel from the `glyph` viewer tile
    # alone -- not the boot ripple, whose decks are `RIPPLE_SEQUENCE`.
    "ring-buffer": (10, 1, 0.45),
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
    "elephant": (14, 2, 0.45),
    # THE FIVE `logo-*` DECKS, 2026-08-26, DERIVED NOT TYPED. They are the
    # Select 26 brand lockup at 32x12 and they are QUIET assets -- 8 to 43 lit
    # cells of 384 against `arrow-field`'s edge-to-edge fill -- so their
    # displayed-luma p95 lands an order of magnitude below the bright decks.
    # `logo-sizzle` carries the largest motion term (4) because its storyboard
    # blanks the panel twice a lap; `logo-stack` the smallest because 16 cells
    # sit still for two thirds of it.
    'logo-sizzle': (14, 4, 0.45),
    'logo-trail': (27, 3, 0.45),
    'logo-offset': (15, 1, 0.45),
    'logo-left': (12, 2, 0.45),
    'logo-stack': (8, 1, 0.45),
}


def calibration_for(technique):
    return TECHNIQUE_CALIBRATION_2X.get(technique, DEFAULT)
