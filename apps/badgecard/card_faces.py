"""One ROM face per background, frozen by string id.  GENERATED.

    python3 badgecard/host/generate_faces.py            # rewrite this file
    python3 badgecard/host/generate_faces.py --check    # fail if it drifted

Do not hand-edit.  `badgecard/tests/test_card_faces.py` re-runs the generator
and diffs its output against these bytes.

THE OWNER'S RULING, 2026-08-17: the skin dictates the face and the wearer cannot
change it.  That is option A of the three in
`docs/design/authoring-a-skin/consuming-a-skin.md`.  There is no typeface screen
in this app and there is no persisted override; `card_model.repair` recomputes
the badge's `face` from its `background` on every load, so a hand-edited state
file cannot separate them either.

WHY A TABLE RATHER THAN A LOOKUP.  `skins.font_name(i)` takes a POSITION in a
tuple, and this app persists frozen string ids precisely so that appending
artwork cannot rewrite a saved badge.  Resolving one through the other at
runtime would reintroduce the hazard at the only point that matters.  The join
is done host-side, once, against both sources, and checked.

`widest` is the measured widest glyph of that face at scale 1, copied from
`skins.FONT_WIDEST` so the runtime can size a name without importing the
666,336 bytes of `skins` to ask.
"""

# What the 18 glyph decks draw a name in.  A deck is a pixel-font atlas, not a
# ROM typeface, so the catalogue proposes no face for one and the owner chose a
# single default for all eighteen.
GLYPH_FACE = 'badgewaremax'

# (entry id, ROM face, widest glyph in px at scale 1)
FACES = (
    ('skin.build-furnace', 'futile', 19),
    ('skin.container-sea', 'bacteria', 13),
    ('skin.interlock', 'ignore', 17),
    ('skin.oxide', 'curse', 10),
    ('skin.supabase', 'badgewaremax', 13),
    ('skin.terminal', 'smart', 9),
    ('skin.trace-map', 'absolute', 12),
    ('skin.amber', 'yesterday', 10),
    ('skin.bbs-ansi-art', 'badgeware', 11),
    ('skin.bluescreen', 'bacteria', 13),
    ('skin.c64-ready', 'badgewaremax', 13),
    ('skin.crt', 'curse', 10),
    ('skin.dmg-boot', 'smart', 9),
    ('skin.floppy-1-44m', 'absolute', 12),
    ('skin.oscilloscope', 'outflank', 13),
    ('skin.plasma', 'more', 20),
    ('skin.vector', 'ignore', 17),
    ('skin.vhs-tracking', 'unfair', 12),
    ('skin.aurora', 'manticore', 11),
    ('skin.firefly-wood', 'salty', 11),
    ('skin.last-train', 'yesterday', 10),
    ('skin.late-shift', 'vest', 14),
    ('skin.outer-rim', 'ignore', 17),
    ('skin.red-mesa', 'more', 20),
    ('skin.ridgeline', 'manticore', 11),
    ('skin.starfield', 'troll', 15),
    ('skin.storm-cape', 'curse', 10),
    ('skin.sunken-light', 'bacteria', 13),
    ('skin.arcs', 'ziplock', 15),
    ('skin.bauhaus', 'futile', 19),
    ('skin.diagonal', 'unfair', 12),
    ('skin.dot-shock', 'ziplock', 15),
    ('skin.eclipse', 'more', 20),
    ('skin.floor', 'bacteria', 13),
    ('skin.grid-break', 'absolute', 12),
    ('skin.iso-stack', 'compass', 11),
    ('skin.memphis-blvd', 'ziplock', 15),
    ('skin.op-ripple', 'outflank', 13),
    ('skin.red-wedge', 'futile', 19),
    ('skin.riso', 'salty', 11),
    ('skin.square-tunnel', 'ignore', 17),
    ('skin.vanish-point', 'compass', 11),
    ('skin.code-rain', 'smart', 9),
    ('skin.datamosh', 'curse', 10),
    ('skin.glitch', 'troll', 15),
    ('skin.hex-field', 'ignore', 17),
    ('skin.rain', 'salty', 11),
    ('skin.synthwave', 'more', 20),
    ('skin.blinky', 'badgewaremax', 13),
    ('skin.claw-machine', 'ziplock', 15),
    ('skin.face', 'more', 20),
    ('skin.lava-lamp', 'bacteria', 13),
    ('skin.mixtape', 'salty', 11),
    ('skin.not-loading', 'smart', 9),
    ('skin.party-mode', 'futile', 19),
    ('skin.pet-rock', 'badgewaremax', 13),
    ('skin.stickerbomb', 'unfair', 12),
    ('skin.test-card', 'bacteria', 13),
    ('skin.aero-ribbon', 'futile', 19),
    ('skin.aqua-gel', 'more', 20),
    ('skin.dew-glass', 'holotype', 10),
    ('skin.palm-gloss', 'compass', 11),
    ('skin.reef-tank', 'bacteria', 13),
    ('skin.frosted-stack', 'compass', 11),
    ('skin.louvre', 'smart', 9),
    ('skin.meniscus', 'bacteria', 13),
    ('skin.prism-ring', 'ignore', 17),
    ('skin.shear', 'futile', 19),
    ('skin.bliss-hill', 'yesterday', 10),
    ('skin.card-cascade', 'manticore', 11),
    ('skin.minefield', 'smart', 9),
    ('skin.paintbox', 'bacteria', 13),
    ('skin.3d-pipes', 'troll', 15),
    ('skin.cryostat', 'manticore', 11),
    ('skin.dyson-swarm', 'futile', 19),
    ('skin.ion-drive', 'ignore', 17),
    ('skin.terraform', 'ziplock', 15),
    ('skin.visor', 'compass', 11),
    ('skin.vercel', 'absolute', 12),
    ('skin.stripe', 'bacteria', 13),
    ('skin.resend', 'smart', 9),
    ('skin.bolt', 'badgewaremax', 13),
    ('skin.grafana', 'bacteria', 13),
    ('skin.doppler', 'badgewaremax', 13),
    ('skin.posthog', 'ziplock', 15),
    ('skin.anthropic', 'badgewaremax', 13),
    ('skin.pg-sleep', 'smart', 9),
    ('skin.supabase-select', 'badgewaremax', 13),
    ('glyph.alphabet', 'badgewaremax', 13),
    ('glyph.arrow-cleanse', 'badgewaremax', 13),
    ('glyph.arrow-field', 'badgewaremax', 13),
    ('glyph.binary-island', 'badgewaremax', 13),
    ('glyph.brackets', 'badgewaremax', 13),
    ('glyph.column', 'badgewaremax', 13),
    ('glyph.fluid-field', 'badgewaremax', 13),
    ('glyph.marquee', 'badgewaremax', 13),
    ('glyph.memory-compactor', 'badgewaremax', 13),
    ('glyph.numbers', 'badgewaremax', 13),
    ('glyph.packet-router', 'badgewaremax', 13),
    ('glyph.radar', 'badgewaremax', 13),
    ('glyph.ring-buffer', 'badgewaremax', 13),
    ('glyph.signal-histogram', 'badgewaremax', 13),
    ('glyph.signal-ripple', 'badgewaremax', 13),
    ('glyph.terminal-marquee', 'badgewaremax', 13),
    ('glyph.tracks', 'badgewaremax', 13),
    ('glyph.wave', 'badgewaremax', 13),
)

COUNT = len(FACES)

# The face a background this build has never heard of draws in.  The same
# default the glyph decks take: an unknown id keeps its string in state so
# reinstalling the asset restores the badge, and in the meantime it has to draw
# in SOMETHING.
FALLBACK_FACE = GLYPH_FACE
FALLBACK_WIDEST = 13


def _row(entry_id):
    for index in range(len(FACES)):
        if FACES[index][0] == entry_id:
            return FACES[index]
    return None


def face_of(entry_id):
    """The ROM face this background's name is drawn in.  Never raises."""
    row = _row(entry_id)
    return row[1] if row is not None else FALLBACK_FACE


def widest_of(entry_id):
    """The widest glyph of that face, px at scale 1.  Never raises."""
    row = _row(entry_id)
    return row[2] if row is not None else FALLBACK_WIDEST


def cap_for(entry_id, width, scale=1, ceiling=0):
    """How many characters this background's face fits across `width`.

    `skins.max_nickname`'s arithmetic, against the frozen table instead of an
    index, plus the product ceiling that function's docstring explicitly leaves
    to the caller: "The caller decides whether to apply a further product-wide
    ceiling."

    THE CEILING IS NOT OPTIONAL HERE and it is not a style choice.  `poster`
    truncates a name at `badge_state.NAME_MAX` before drawing it, and `poster`
    is what the launcher's 1.5-second hold opens.  An editor that let a wearer
    type more than that would show them a name their own home screen then cut
    short.  `card_model.NAME_MAX` is the number and it passes it in.

    `width` and `scale` are arguments rather than globals so a LORES panel, a
    HIRES panel and a host test each get their own honest answer.
    """
    fits = (width - 2 * scale) // (widest_of(entry_id) * scale)
    if fits < 1:
        fits = 1
    if ceiling and fits > ceiling:
        return ceiling
    return fits
