"""Glyph vocabulary and palette shared by the converter, player, and tests.

Glyph IDs 0..84 are adopted verbatim from the select-badge sparkle-player
branch (badge-platform/device/sparkle-app/player_pixel_font.py at commit
f1da312) so that our packed-cell glyph IDs stay byte-compatible with its
85-record mask bank (DepartureMonoSuperbase-Player.pfb). IDs 85..101 are
this feature's extension for the full technique sweep (the text overlay's
ascii charset ramps plus the letters of the player's default words); their
masks are appended to assets/glyph-masks.pfb from the same committed
Departure Mono pixel atlas by host/extend_mask_bank.py, leaving the first
85 records byte-identical to the pinned original.
ID zero is the empty cell and owns an all-zero mask record.

The palette is the verified Select playground player palette
(select-main lib/glyph-engine/presets.ts rows) in the same index order the
sparkle-player compositor contract uses: color index 0..4, packed color
nibble = index + 1 (0 is reserved for strand-inherit, which recorded
streams never use).
"""

MASK_BYTES = 200

PLAYER_GLYPHS = (
    None,
    "▁", "▂", "▃", "▄", "▅", "▆", "▇",
    "·", "─", "═",
    "‹", "(", "[", "{", "›", ")", "]", "}",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "A", "B", "C", "D", "E", "F", "G", "\ue000",
    ":", "|", "I", "┄", "┈", "╫", "▓", "▒",
    "█", "◆", "×", "+", "/", "│", "x",
    "↑", "↗", "→", "↘", "↓", "↙",
    "←", "↖",
    "~", "≈", "?", "!", "≠", "R", "L", "T", "Y", " ",
    "┐", "┘", "└", "┌", "●", "■",
    "▣", "•", "▔", "┴", "━", "├",
    "┤", "▸", "◂",
    # IDs 85+: full-sweep extension (host/extend_mask_bank.py appends the
    # matching masks; order here is load-bearing and mirrored there).
    ".", ";", "-", "=", "*", "#", "%", "@",
    "<", ">", "\\", "⌘",
    "H", "P", "S", "U", "V",
)

GLYPH_TO_ID = {glyph: index for index, glyph in enumerate(PLAYER_GLYPHS)}
MASK_COUNT = len(PLAYER_GLYPHS)
BANK_BYTES = MASK_COUNT * MASK_BYTES

# Playground player palette over black. Index order matches the
# sparkle-player compositor contract; packed nibble = index + 1.
PALETTE_RGB = (
    (62, 207, 142),    # 0 #3ecf8e
    (0, 189, 88),      # 1 #00bd58
    (149, 230, 184),   # 2 #95e6b8
    (225, 252, 215),   # 3 #e1fcd7
    (255, 255, 255),   # 4 #ffffff
)
BACKGROUND_RGB = (0, 0, 0)

INVERSE_FLAG = 0x80
COLOR_MASK = 0x0F


def glyph_id(glyph):
    """Return the stable uint8 mask ID for a glyph, or 255 if unknown."""
    return GLYPH_TO_ID.get(glyph, 255)
