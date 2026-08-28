"""Per-entry top-anchored name Y overrides, by frozen id.  GENERATED.

    python3 setup/host/generate_name_positions.py
    python3 setup/host/generate_name_positions.py --check

Do not hand-edit.  The owner input is `setup/host/name_positions.json`.
Its order and typeface fields are validation context only; this table changes
neither the catalogue order nor any face.

Only ruled entries appear here.  A catalogue id absent from `POSITIONS` keeps
`FALLBACK_Y`, silently and deliberately, so new or explicitly unruled artwork
does not acquire an invented placement.
"""

# The shipped global before per-entry placement, retained for every id the
# owner did not override and for an id this build has never heard of.
FALLBACK_Y = 0.08

# (catalogue entry id, top edge as a fraction of canvas height)
POSITIONS = (
    ('glyph.ring-buffer', 0.3625),
    ('glyph.wave', 0.2625),
    ('glyph.memory-compactor', 0.2625),
    ('glyph.brackets', 0.2625),
    ('glyph.alphabet', 0.2625),
    ('glyph.arrow-field', 0.3166666667),
    ('glyph.column', 0.2625),
    ('glyph.fluid-field', 0.2625),
    ('glyph.signal-ripple', 0.2625),
    ('glyph.packet-router', 0.2625),
    ('skin.supabase', 0.0416666667),
    ('skin.resend', 0.25),
    ('skin.bolt', 0.2916666667),
    ('skin.grafana', 0.3958333333),
    ('skin.doppler', 0.2875),
    ('skin.pg-sleep', 0.175),
    ('skin.paintbox', 0.1833333333),
    ('skin.breath', 0.2625),
    ('skin.scrim', 0.2625),
    ('skin.dot-dash', 0.2625),
    ('skin.dot-matrix-wave', 0.2625),
    ('skin.threshold', 0.2625),
    ('skin.acrylic', 0.2625),
    ('skin.convex-lens', 0.2625),
    ('skin.prismatic', 0.2625),
    ('skin.black-line', 0.2625),
    ('skin.dot-sphere', 0.2625),
    ('skin.dot-ring', 0.3166666667),
)

COUNT = len(POSITIONS)


def y_of(entry_id):
    """Top-anchored name Y for `entry_id`; unknown and unruled ids are safe."""
    for index in range(len(POSITIONS)):
        if POSITIONS[index][0] == entry_id:
            return POSITIONS[index][1]
    return FALLBACK_Y
