"""The skin catalogue: one idea per entry, not one idea recoloured twenty times.

A skin is the full-screen artwork behind the nickname. The badge hangs facing
outward, so this is the most visible thing about it and it is pure personality —
the real name is on a printed card above the device. Ugly is allowed; generic
is not.

## The contract

    render(buf, index)      draw the static background. Called ONCE on select.
    animated(index)         does this skin move?
    animate(dst, t, index)  draw moving elements on top, EVERY frame, t in 0..1.
    font_name(index)        proposed ROM font metadata for the nickname.

The table proposes that the font become part of the skin: a face carries as much
of the era as the artwork does, and a chooser would be one more thing to drive
with five buttons. Every assignment is one of the 37 `.ppf` faces in /rom/fonts,
so the metadata depends on no optional file. The current production app does not
consume `font_name()` or `max_nickname()`; Chrome still owns the display face and
the editor still applies the product-wide 12-character cap. Keep that integration
status explicit until the variation is deliberately wired and tested.

Everything is **resolution-relative**: coordinates derive from buf.width and
buf.height, never from a literal 160 or 120. The same code therefore renders a
40x30 contact-sheet thumbnail, a 160x120 LORES badge and a 320x240 HIRES badge.

**AUTHOR AND PRICE AT HIRES 320x240.** badgecard ships HIRES 1:1, so that is the
size to judge and to cost.

**BUT 160x120 IS STILL SHIPPED, and it is not the badgecard variant that ships it.**
SAVE TO HOME bakes the chosen skin into the launcher's wallpaper film at 160x120
(`card_bake.py`), and the launcher plays it as the device background. So the 160x120
render must be WALLPAPER-GRADE: it draws, it is not blank, and no layer vanishes or
stroke collapses. What is no longer required, as of 2026-08-21, is that the two sizes
look the SAME -- `_stroke()` is a physical width and doubling it is correct.
`_unit()` is the idiom — one unit is a fortieth of the width, so a shape built
from units keeps its proportions everywhere.

## Cost

render() gets ~600 primitive calls; the previous catalogue measured 7.2-26.5 ms
on device against a 90 ms ceiling. A full-height gradient is one rectangle per
row, ~120 calls, and is cheap.

animate() runs every frame and gets ~40 calls -- ADVISORY AT HIRES since
2026-08-18, where a stroke-derived animator legitimately doubles (`OSCILLOSCOPE`
goes 28 -> 54) and the owner ruled that is fine. `validate-skin.mjs --strict`
still enforces 40 at LORES, which is the resolution authoring measures at. A
call count does not predict frame time -- cost tracks rasterised AREA -- so the
gate that matters is a device measurement, not this number. It is a few moving shapes, never
a redraw. The app also gates it to the worn and skin-browsing views: the glyph
hardware pass measured that ambient motion behind a sticker-dense editor reads
as "too busy".

The nickname sits in large outlined text around y = 28% of height, so these
avoid fussy high-frequency detail exactly there.

## Brand marks

By DEFAULT every composition here is original: colour stories and geometry as
homage, never a reproduced trademark, with the brand marks living in the sticker
set that has its own provenance record.

`SUPABASE` USED TO BE THE WORKED EXAMPLE OF THAT RULE -- an angular bolt cropped
huge, not a logo -- and on 2026-08-21 the owner replaced it with the Supabase
mascot drawn from the company's own sticker art, and added `SUPABASE SELECT` from
the event poster. It is his company and his mark, asked for by name. So the
default below still holds for every OTHER skin, but the two entries that carry
this mark are now deliberate reproductions rather than homages, and nobody should
"fix" them back into abstraction.

THE OWNER OVERRIDES THIS WHEN A BRAND IS THE POINT, and on 2026-08-18 he did.
Sponsors and partners get skins that are deliberately and completely branded,
made from the brands' own assets under permission recorded with the work. That
is a REQUIREMENT rather than a lapse: a sponsor skin that hedges itself back
into abstraction has failed the only brief it exists for, and the sponsor
notices. Do not "fix" one into a colour story.

Two rules keep the exception from spreading, and they are the whole of it:

* a branded skin is its OWN entry, made for that brand on purpose;
* brand marks do not leak into any skin that is not one of them. The default
  above still governs all 78 of these.
"""

import math


CYCLE_MS = 4000

# The group is an INTERNAL tag: a shorthand for talking about a set of
# artwork, and the jump key's stops. It is NOT persisted by any app --
# `card_model` and `identity_model` store the background id and nothing
# else -- so a group may be added or renamed without touching a saved
# badge. What it must stay is CONTIGUOUS: `identity_catalogue` emits in
# SKINS order and `test_entries_are_contiguous_within_their_group` holds
# browsing a group to "must not walk the whole table". Since SKINS is
# append-only, a new set of artwork takes a NEW group rather than
# joining an existing one it would be separated from.
GROUPS = ("BRAND", "RETRO", "SCENE", "GRAPHIC", "NEON", "PLAY",
          "AERO", "GLASS", "WIN9X", "FUTURE", "SPONSOR", "DEV", "EVENT")


def _unit(buf):
    return max(1, buf.width // 40)


def _stroke(buf):
    """Pixels per PHYSICAL stroke, so a hairline keeps its millimetres.

    `_unit()` handles composition: it is a fraction of the canvas, so a shape
    built from it occupies the same share of the screen everywhere. Stroke
    weight is the other kind of size and it does not follow the same rule. A
    literal `rectangle(0, y, w, 1)` is 2 panel pixels at LORES, where every
    logical pixel is doubled, and 1 at HIRES — half the millimetres.

    That was measured, not assumed. `namebadge/host/skin_resolution.mjs`
    renders every skin at both resolutions and compares them as the panel shows
    them: 47 of 58 hold their dominant texture period, and the ones that do not
    are exactly the ones drawing one-logical-pixel strokes. CRT's tube lost its
    scanlines entirely — the modulation is still in the framebuffer, at a
    3-panel-pixel period, which is 4.8 arcminutes at arm's length and reads as a
    flat wash.

    So: `_unit()` for composition, `_stroke()` for anything whose WIDTH is the
    point. It is 1 at LORES and at thumbnail size, 2 at HIRES, which is the
    same rule `ui.Chrome.scale` already uses for the softkey bar — and it means
    a HIRES-only change cannot move a LORES pixel.
    """
    return max(1, buf.width // 160)


def _thick_line(buf, x1, y1, x2, y2, weight):
    """A line `weight` pixels wide. `line()` has no width, so lay them side by
    side along whichever axis the line is shallower in."""
    if weight <= 1:
        buf.line(x1, y1, x2, y2)
        return
    steep = abs(y2 - y1) > abs(x2 - x1)
    for i in range(weight):
        if steep:
            buf.line(x1 + i, y1, x2 + i, y2)
        else:
            buf.line(x1, y1 + i, x2, y2 + i)


def _vertical(buf, low, high, y0=0, y1=None):
    """Cheap vertical gradient: one filled row at a time."""
    h = buf.height if y1 is None else y1
    span = max(1, h - y0 - 1)
    for y in range(y0, h):
        t = (y - y0) * 255 // span
        buf.pen = color.rgb(
            low[0] + (high[0] - low[0]) * t // 255,
            low[1] + (high[1] - low[1]) * t // 255,
            low[2] + (high[2] - low[2]) * t // 255,
        )
        buf.rectangle(0, y, buf.width, 1)


# ── BRAND: colour stories and geometry -- EXCEPT the owner's own mark, which
# ── `SUPABASE` reproduces on purpose (2026-08-21). See "Brand marks" above.


# SUPABASE -- the bolt mascot: shades on, thumb up, standing on its own stage.
#
# Drawn from the sticker sheet, HIRES-first: 320x240 1:1 is what badgecard ships.
#
# EVERY PROPORTION BELOW WAS MEASURED OFF THE SOURCE ART, not eyeballed. The
# sticker's alpha box is square (aspect 0.977), so the character is laid out in a
# SQUARE box and the tables are that box's own 0..1 coordinates -- which is also
# why it survives 40x30 and 160x120 unchanged. Guessing the box shape was the one
# mistake that made every part look detached: a 1.4 box stretches a round face
# into an egg and drags the gloves away from the body.
#
# Measured centroids the tables honour: tongue (0.523, 0.493) -- the mouth is
# almost dead centre; dark green (0.744, 0.425) -- the swept wing owns the right;
# light green (0.462, 0.373) -- crown plus face own the upper middle.
#
# THE COMPOSITION IS DECIDED BY THE NAME BAND. The wearer's name occupies 28% to
# 62% of the height (`shared/poster.py:99`), so the box is pitched low enough that
# the band crosses the crown and the shades -- both near-black -- and clears the
# mouth entirely. The field is one flat wash, darkest across the band, because an
# outlined name needs a quiet ground more than the picture needs a gradient.

# SUPABASE -- the bolt mascot, drawn from the owner's own vector source.
#
# EVERY CURVE HERE IS HIS, not my approximation of one. The geometry is
# `character.svg`'s nineteen filled paths, bezier-flattened and Douglas-Peucker
# simplified at a tolerance derived from one 320x240 pixel, then normalised to the
# art's own bounding box so the tables are 0..1 and the skin still renders at
# 160x120 and 40x30. The previous version was traced by eye off a PNG and the
# owner's verdict was that it looked awful; he was right, and this is the fix.
#
# WHY A POLYGON TABLE IS THE RIGHT SHAPE FOR THIS. `shape.custom` accepts 2,000
# vertices in ONE draw call and cost on this hardware tracks rasterised AREA, not
# vertex count -- so a faithful 87-point glove costs exactly what a crude 8-point
# guess cost. Fidelity is free here; the only price is bytes in this module.
#
# `body-outline` is the one path with two contours, i.e. a hole. It is stored as
# the outer contour followed by the inner one REVERSED, and drawn under
# `fill_rule = EVEN_ODD`, which is the only way to express a hole -- there is no
# multi-contour form of `shape.custom` (confirmed by trying it).
#
# THE ANIMATION IS THE OWNER'S CSS, TRANSLATED EXACTLY.
#
#     #arm-l-outline, #glove-l, #glove-l-finger1, #glove-l-finger2 {
#       transform-origin: 69px 113px;   /* == circle#pivot-arm-left */
#       animation: thumbs-up 1000ms cubic-bezier(.45,0,.55,1) infinite alternate;
#     }
#     @keyframes thumbs-up { 0% { rotate(-12deg) } 100% { rotate(8deg) } }
#
# 1,000 ms per leg is 2,000 ms per round trip, which is TWO round trips per the
# badge's fixed 4,000 ms loop. That integer is the whole reason the motion joins
# itself at the wrap; his first draft was 1,500 ms per leg, and 4000/3000 = 1.33
# would have snapped the arm back mid-swing every four seconds -- the defect that
# broke eight skins on 2026-08-18. The cubic-bezier is solved, not approximated.
#
# THE ARM IS BEHIND THE BODY, which is what makes `animate` more than one draw:
# repaint the swept patch of field, draw the four arm paths rotated, then redraw
# the two body paths whose bounding box the sweep intersects (`body-outline` and
# `face-dark-top`, computed rather than guessed). Seven calls a frame.
#
# The field is `brush.gradient` -- ONE call for the whole wash, C-speed and smooth,
# where the hand-rolled per-row version cost 18 rectangles and banded. It is kept
# dark because the wearer's name is drawn over 28%..62% of the height and an
# outlined name needs a quiet ground.

# SUPABASE -- the bolt mascot, drawn from the owner's own vector source.
#
# EVERY CURVE HERE IS HIS, not my approximation of one. The geometry is
# `character.svg`'s nineteen filled paths, bezier-flattened and Douglas-Peucker
# simplified at a tolerance derived from one 320x240 pixel, then normalised to the
# art's own bounding box so the tables are 0..1 and the skin still renders at
# 160x120 and 40x30. The previous version was traced by eye off a PNG and the
# owner's verdict was that it looked awful; he was right, and this is the fix.
#
# WHY A POLYGON TABLE IS THE RIGHT SHAPE FOR THIS. `shape.custom` accepts 2,000
# vertices in ONE draw call and cost on this hardware tracks rasterised AREA, not
# vertex count -- so a faithful 87-point glove costs exactly what a crude 8-point
# guess cost. Fidelity is free here; the only price is bytes in this module.
#
# `body-outline` is the one path with two contours, i.e. a hole. It is stored as
# the outer contour followed by the inner one REVERSED, and drawn under
# `fill_rule = EVEN_ODD`, which is the only way to express a hole -- there is no
# multi-contour form of `shape.custom` (confirmed by trying it).
#
# THE ANIMATION IS THE OWNER'S CSS, TRANSLATED EXACTLY.
#
#     #arm-l-outline, #glove-l, #glove-l-finger1, #glove-l-finger2 {
#       transform-origin: 69px 113px;   /* == circle#pivot-arm-left */
#       animation: thumbs-up 1000ms cubic-bezier(.45,0,.55,1) infinite alternate;
#     }
#     @keyframes thumbs-up { 0% { rotate(-12deg) } 100% { rotate(8deg) } }
#
# 1,000 ms per leg is 2,000 ms per round trip, which is TWO round trips per the
# badge's fixed 4,000 ms loop. That integer is the whole reason the motion joins
# itself at the wrap; his first draft was 1,500 ms per leg, and 4000/3000 = 1.33
# would have snapped the arm back mid-swing every four seconds -- the defect that
# broke eight skins on 2026-08-18. The cubic-bezier is solved, not approximated.
#
# THE ARM IS BEHIND THE BODY, which is what makes `animate` more than one draw:
# repaint the swept patch of field, draw the four arm paths rotated, then redraw
# the two body paths whose bounding box the sweep intersects (`body-outline` and
# `face-dark-top`, computed rather than guessed). Seven calls a frame.
#
# The field is `brush.gradient` -- ONE call for the whole wash, C-speed and smooth,
# where the hand-rolled per-row version cost 18 rectangles and banded. It is kept
# dark because the wearer's name is drawn over 28%..62% of the height and an
# outlined name needs a quiet ground.

# @skinlab {"type":"color","label":"Field top","group":"Field"}
SUPA_FIELD_TOP = (5, 16, 12)


# @skinlab {"type":"color","label":"Field bottom","group":"Field"}
SUPA_FIELD_BOTTOM = (13, 43, 30)


# @skinlab {"type":"number","label":"Art height","group":"Layout","min":0.40,"max":1.00,"step":0.01}
SUPA_FIT = 0.76


# @skinlab {"type":"number","label":"Feet at","group":"Layout","min":0.60,"max":1.00,"step":0.005}
SUPA_FOOT = 0.995


# @skinlab {"type":"number","label":"Swing start (deg)","group":"Motion","min":-40,"max":0,"step":0.5}
SUPA_SWING_LO = -12.0


# @skinlab {"type":"number","label":"Swing end (deg)","group":"Motion","min":0,"max":40,"step":0.5}
SUPA_SWING_HI = 8.0


# @skinlab {"type":"integer","label":"Round trips per loop","group":"Motion","min":1,"max":4,"step":1}
SUPA_SWEEPS = 2


SUPA_ART_X0, SUPA_ART_Y0, SUPA_ART_W, SUPA_ART_H = 0.0560, -0.0100, 229.1913, 216.4292


SUPA_ASPECT = 1.058967


SUPA_PIVOT = (0.30081, 0.52216)


SUPA_SWEPT = (-0.02309, 0.15618, 0.34008, 0.62278)


SUPA_ARM_IDS = ('arm-l-outline', 'glove-l', 'glove-l-finger1', 'glove-l-finger2')


SUPA_COVER_IDS = ('body-outline', 'face-dark-top')


SUPA_ORDER = ('arm-l-outline', 'glove-l', 'glove-l-finger1', 'glove-l-finger2', 'body-outline', 'glove-r', 'glove-r-cuff', 'shoe-r', 'shoe-l', 'shoe-l-sole', 'shoe-r-tongue', 'face-light', 'lens-r', 'lens-l', 'mouth', 'mouth-corner', 'tongue', 'face-dark', 'face-dark-top')


SUPA_HOLES = ('body-outline',)


SUPA_PATHS = {
    'arm-l-outline': ((9, 10, 10), ((0.1531,0.1749), (0.1387,0.1767), (0.1250,0.1834), (0.1028,0.2080), (0.0914,0.2418), (0.0934,0.2717), (0.0718,0.2702), (0.0453,0.2772), (0.0272,0.2890), (0.0144,0.3058), (0.0089,0.3267), (0.0110,0.3448), (0.0043,0.3558), (0.0000,0.3722), (0.0010,0.3891), (0.0073,0.4048), (0.0028,0.4219), (0.0044,0.4392), (0.0137,0.4603), (0.0334,0.4827), (0.0520,0.4958), (0.0792,0.5064), (0.0959,0.5220), (0.1265,0.5272), (0.1514,0.5665), (0.1805,0.5925), (0.2124,0.6051), (0.2323,0.6065), (0.2525,0.6034), (0.2927,0.5845), (0.3249,0.5564), (0.3379,0.5342), (0.3401,0.5222), (0.3382,0.5115), (0.3264,0.4914), (0.3058,0.4815), (0.2837,0.4853), (0.2507,0.5113), (0.2363,0.5178), (0.2225,0.5127), (0.2075,0.4923), (0.1981,0.4739), (0.2104,0.4546), (0.2155,0.4232), (0.2122,0.4030), (0.2108,0.4057), (0.2034,0.3888), (0.2056,0.3556), (0.1866,0.2830), (0.1931,0.2100), (0.1831,0.1888), (0.1695,0.1793), (0.1531,0.1749))),
    'glove-l': ((255, 255, 255), ((0.0277,0.4091), (0.0489,0.3968), (0.0739,0.3941), (0.0988,0.3998), (0.1199,0.4128), (0.1259,0.4236), (0.1256,0.4340), (0.1179,0.4456), (0.1050,0.4527), (0.0863,0.4525), (0.0477,0.4362), (0.0481,0.4422), (0.0537,0.4484), (0.0850,0.4647), (0.0985,0.4663), (0.1120,0.4631), (0.1241,0.4557), (0.1332,0.4451), (0.1381,0.4272), (0.1345,0.4120), (0.1426,0.4037), (0.1468,0.3884), (0.1452,0.3723), (0.1395,0.3588), (0.1488,0.3463), (0.1509,0.3294), (0.1397,0.3047), (0.1149,0.2857), (0.1120,0.2433), (0.1169,0.2227), (0.1274,0.2066), (0.1443,0.1977), (0.1638,0.1991), (0.1714,0.2066), (0.1744,0.2176), (0.1673,0.2792), (0.1834,0.3535), (0.1857,0.3771), (0.1788,0.4061), (0.1551,0.4347), (0.1597,0.4369), (0.1682,0.4320), (0.1900,0.4056), (0.1934,0.4224), (0.1877,0.4515), (0.1669,0.4827), (0.1476,0.4975), (0.1317,0.5039), (0.1156,0.5050), (0.1000,0.5000), (0.0951,0.4968), (0.1254,0.4864), (0.1342,0.4790), (0.1392,0.4692), (0.1247,0.4788), (0.1018,0.4844), (0.0773,0.4825), (0.0545,0.4739), (0.0363,0.4594), (0.0274,0.4451), (0.0241,0.4283), (0.0277,0.4092))),
    'glove-l-finger1': ((255, 255, 255), ((0.0906,0.3844), (0.0522,0.3838), (0.0248,0.3948), (0.0202,0.3728), (0.0252,0.3604), (0.0400,0.3490), (0.0606,0.3433), (0.0888,0.3440), (0.1087,0.3505), (0.1223,0.3598), (0.1319,0.3714), (0.1361,0.3848), (0.1341,0.3946), (0.1262,0.4028), (0.1096,0.3910), (0.0906,0.3844))),
    'glove-l-finger2': ((255, 255, 255), ((0.1295,0.3506), (0.1069,0.3372), (0.0815,0.3306), (0.0553,0.3314), (0.0306,0.3404), (0.0302,0.3196), (0.0398,0.3046), (0.0608,0.2937), (0.0856,0.2911), (0.1073,0.2959), (0.1243,0.3064), (0.1367,0.3229), (0.1385,0.3375), (0.1295,0.3506))),
    'body-outline': ((9, 10, 10), ((0.5613,0.0000), (0.5370,0.0054), (0.5157,0.0201), (0.3485,0.2260), (0.2966,0.2293), (0.2655,0.2369), (0.2621,0.2517), (0.2632,0.2731), (0.2753,0.2915), (0.2786,0.3149), (0.2294,0.3758), (0.2131,0.4045), (0.2092,0.4253), (0.2096,0.4497), (0.2138,0.4678), (0.2216,0.4831), (0.2401,0.5002), (0.2890,0.5231), (0.3170,0.5469), (0.3379,0.5730), (0.3573,0.6110), (0.3826,0.6505), (0.3371,0.7091), (0.3064,0.7554), (0.2916,0.7291), (0.2681,0.7044), (0.2419,0.6906), (0.2147,0.6866), (0.1880,0.6912), (0.1579,0.7074), (0.1343,0.7332), (0.1224,0.7592), (0.1185,0.7812), (0.1197,0.8048), (0.1267,0.8294), (0.1402,0.8547), (0.1695,0.8885), (0.2029,0.9139), (0.2378,0.9560), (0.2570,0.9705), (0.2780,0.9803), (0.2999,0.9834), (0.3165,0.9804), (0.3470,0.9658), (0.3641,0.9486), (0.3771,0.9154), (0.3814,0.8901), (0.3783,0.8888), (0.3787,0.8832), (0.3889,0.8718), (0.3957,0.8538), (0.3947,0.8298), (0.3830,0.8031), (0.4191,0.7475), (0.4573,0.7000), (0.5074,0.7116), (0.5545,0.7100), (0.5495,0.7436), (0.5548,0.7806), (0.5705,0.8146), (0.5917,0.8361), (0.5909,0.8481), (0.5650,0.8524), (0.5417,0.8650), (0.5328,0.8747), (0.5238,0.8920), (0.5175,0.9098), (0.5147,0.9334), (0.5190,0.9535), (0.5293,0.9699), (0.5446,0.9827), (0.5641,0.9920), (0.6116,1.0000), (0.6638,0.9940), (0.7128,0.9742), (0.7338,0.9591), (0.7511,0.9406), (0.7730,0.9035), (0.7823,0.8756), (0.7836,0.8528), (0.7789,0.8310), (0.7678,0.8115), (0.7497,0.7958), (0.7689,0.7859), (0.7882,0.7688), (0.8122,0.7659), (0.8369,0.7558), (0.8584,0.7399), (0.8705,0.7243), (0.9004,0.7093), (0.9186,0.6859), (0.9251,0.6617), (0.9552,0.6387), (0.9778,0.6134), (0.9897,0.5934), (0.9971,0.5730), (1.0000,0.5525), (0.9982,0.5324), (0.9843,0.5007), (0.9565,0.4727), (0.9141,0.4502), (0.9587,0.3911), (0.9786,0.3486), (0.9816,0.3294), (0.9799,0.3097), (0.9641,0.2755), (0.9408,0.2543), (0.9164,0.2447), (0.7462,0.2439), (0.7279,0.2339), (0.7033,0.2284), (0.6062,0.2245), (0.6040,0.0335), (0.5891,0.0094), (0.5761,0.0022), (0.5613,0.0000), (0.8650,0.5109), (0.8108,0.5834), (0.8372,0.5752), (0.8555,0.5736), (0.8733,0.5774), (0.8859,0.5852), (0.9090,0.5726), (0.9225,0.5593), (0.9266,0.5528), (0.9265,0.5450), (0.9176,0.5330), (0.8650,0.5109))),
    'glove-r': ((255, 255, 255), ((0.7711,0.6945), (0.7628,0.6938), (0.7491,0.6987), (0.7277,0.7145), (0.7117,0.7368), (0.7053,0.7621), (0.6940,0.7619), (0.6849,0.7566), (0.6786,0.7476), (0.6755,0.7326), (0.6839,0.7067), (0.7069,0.6787), (0.7445,0.6527), (0.7254,0.6556), (0.7021,0.6690), (0.6789,0.6943), (0.6668,0.7186), (0.6540,0.7029), (0.6545,0.6795), (0.6705,0.6505), (0.6991,0.6208), (0.7349,0.6017), (0.7747,0.5938), (0.8143,0.5994), (0.8430,0.6179), (0.8581,0.6395), (0.8656,0.6702), (0.8613,0.7008), (0.8457,0.7269), (0.8313,0.7385), (0.8131,0.7460), (0.7915,0.7484), (0.7906,0.7429), (0.7681,0.7630), (0.7454,0.7763), (0.7261,0.7772), (0.7196,0.7712), (0.7171,0.7615), (0.7250,0.7353), (0.7452,0.7114), (0.7710,0.6945))),
    'glove-r-cuff': ((255, 255, 255), ((0.8751,0.6996), (0.8769,0.6709), (0.8695,0.6379), (0.8520,0.6098), (0.8299,0.5926), (0.8475,0.5877), (0.8688,0.5920), (0.8864,0.6056), (0.8989,0.6255), (0.9048,0.6482), (0.9027,0.6707), (0.8910,0.6896), (0.8751,0.6996))),
    'shoe-r': ((255, 255, 255), ((0.6284,0.9784), (0.5902,0.9766), (0.5572,0.9631), (0.5451,0.9526), (0.5372,0.9399), (0.5344,0.9254), (0.5359,0.9147), (0.5438,0.8976), (0.5593,0.8793), (0.5842,0.8701), (0.6216,0.8736), (0.6727,0.8932), (0.6685,0.8858), (0.6539,0.8753), (0.6125,0.8577), (0.6121,0.8434), (0.6127,0.8385), (0.6278,0.8516), (0.6464,0.8557), (0.6607,0.8537), (0.6776,0.8452), (0.6871,0.8353), (0.6921,0.8230), (0.6915,0.8090), (0.6838,0.7937), (0.7084,0.8035), (0.7165,0.8137), (0.7201,0.8259), (0.7147,0.8528), (0.6947,0.8769), (0.7111,0.8704), (0.7234,0.8574), (0.7307,0.8403), (0.7305,0.8122), (0.7328,0.8122), (0.7425,0.8173), (0.7604,0.8384), (0.7643,0.8570), (0.7612,0.8767), (0.7426,0.9137), (0.7107,0.9485), (0.6746,0.9690), (0.6284,0.9784))),
    'shoe-l': ((255, 255, 255), ((0.3406,0.9417), (0.3380,0.9259), (0.3284,0.9074), (0.2853,0.8580), (0.2501,0.7998), (0.2251,0.7682), (0.2057,0.7521), (0.1894,0.7441), (0.1715,0.7408), (0.1519,0.7430), (0.1690,0.7245), (0.1930,0.7104), (0.2112,0.7071), (0.2347,0.7111), (0.2610,0.7275), (0.2813,0.7540), (0.2931,0.7877), (0.2938,0.8259), (0.3031,0.8077), (0.3252,0.8265), (0.3270,0.8247), (0.3217,0.8084), (0.3063,0.7956), (0.3060,0.7845), (0.3350,0.7910), (0.3615,0.8109), (0.3726,0.8286), (0.3747,0.8477), (0.3646,0.8663), (0.3568,0.8490), (0.3481,0.8412), (0.3557,0.8650), (0.3577,0.8974), (0.3513,0.9296), (0.3406,0.9417))),
    'shoe-l-sole': ((234, 239, 216), ((0.2185,0.9014), (0.1756,0.8652), (0.1581,0.8437), (0.1463,0.8231), (0.1397,0.8040), (0.1381,0.7820), (0.1437,0.7651), (0.1555,0.7549), (0.1678,0.7525), (0.1824,0.7552), (0.1990,0.7637), (0.2170,0.7786), (0.2360,0.8004), (0.2928,0.8867), (0.2539,0.8969), (0.2185,0.9014))),
    'shoe-r-tongue': ((234, 238, 216), ((0.3031,0.9611), (0.2839,0.9595), (0.2667,0.9516), (0.2479,0.9357), (0.2286,0.9130), (0.2656,0.9065), (0.3017,0.8954), (0.3217,0.9200), (0.3287,0.9382), (0.3268,0.9478), (0.3222,0.9533), (0.3031,0.9611))),
    'face-light': ((92, 180, 128), ((0.4762,0.2560), (0.4137,0.2380), (0.3711,0.2319), (0.5155,0.0521), (0.5480,0.0251), (0.5626,0.0211), (0.5714,0.0232), (0.5833,0.0359), (0.5849,0.0473), (0.5859,0.2333), (0.5451,0.2414), (0.4997,0.2554), (0.4762,0.2560))),
    'lens-r': ((234, 238, 214), ((0.6255,0.3557), (0.6070,0.3745), (0.6222,0.3176), (0.6390,0.2784), (0.6465,0.2725), (0.6570,0.2708), (0.6804,0.2784), (0.6483,0.3278), (0.6255,0.3557))),
    'lens-l': ((233, 238, 214), ((0.3748,0.3560), (0.3766,0.3168), (0.3881,0.2847), (0.4041,0.2704), (0.4254,0.2756), (0.4276,0.2812), (0.3747,0.3559))),
    'mouth': ((23, 22, 23), ((0.5992,0.5226), (0.5764,0.5504), (0.5444,0.5708), (0.5179,0.5764), (0.4858,0.5712), (0.4628,0.5579), (0.4437,0.5373), (0.4277,0.5023), (0.4228,0.4582), (0.3985,0.4469), (0.3922,0.4380), (0.3952,0.4328), (0.4009,0.4317), (0.4295,0.4448), (0.4575,0.4530), (0.4945,0.4590), (0.5324,0.4602), (0.5700,0.4560), (0.6000,0.4476), (0.6090,0.4422), (0.6005,0.4389), (0.6001,0.4356), (0.6016,0.4311), (0.6083,0.4290), (0.6314,0.4387), (0.6387,0.4503), (0.6405,0.4622), (0.6385,0.4665), (0.6332,0.4678), (0.6268,0.4580), (0.6155,0.4916), (0.5992,0.5226))),
    'mouth-corner': ((52, 168, 77), ((0.6000,0.4476), (0.5998,0.4368), (0.6112,0.4424), (0.6001,0.4476))),
    'tongue': ((232, 101, 41), ((0.4615,0.5392), (0.4749,0.5243), (0.4925,0.5165), (0.5149,0.5197), (0.5121,0.5362), (0.5233,0.5201), (0.5435,0.5084), (0.5669,0.5062), (0.5892,0.5138), (0.5788,0.5288), (0.5613,0.5455), (0.5407,0.5573), (0.5241,0.5623), (0.5074,0.5634), (0.4909,0.5603), (0.4754,0.5524), (0.4615,0.5392))),
    'face-dark': ((50, 169, 73), ((0.6000,0.6722), (0.5992,0.5226), (0.6162,0.4866), (0.6260,0.4573), (0.6301,0.4590), (0.6324,0.4656), (0.6372,0.4656), (0.6400,0.4607), (0.6348,0.4458), (0.6236,0.4345), (0.6121,0.4303), (0.6001,0.4318), (0.5990,0.4137), (0.6285,0.4147), (0.6543,0.4105), (0.6768,0.4006), (0.6954,0.3851), (0.7152,0.3524), (0.7250,0.3018), (0.7418,0.2802), (0.7428,0.2654), (0.9059,0.2655), (0.9206,0.2683), (0.9415,0.2815), (0.9560,0.3025), (0.9616,0.3277), (0.9579,0.3514), (0.9438,0.3773), (0.7887,0.5815), (0.7499,0.5847), (0.7183,0.5952), (0.6899,0.6131), (0.6635,0.6407), (0.6482,0.6656), (0.6415,0.6866), (0.6441,0.7113), (0.6536,0.7239), (0.6640,0.7309), (0.6649,0.7398), (0.6620,0.7526), (0.6461,0.7716), (0.6362,0.7769), (0.6219,0.7773), (0.6123,0.7724), (0.6038,0.7601), (0.6003,0.7368), (0.6000,0.6722))),
    'face-dark-top': ((91, 181, 128), ((0.6000,0.4129), (0.5998,0.4483), (0.5534,0.4594), (0.5184,0.4614), (0.4838,0.4590), (0.4413,0.4498), (0.4002,0.4329), (0.3935,0.4365), (0.4009,0.4473), (0.4236,0.4577), (0.4288,0.5020), (0.4447,0.5368), (0.4633,0.5571), (0.4858,0.5701), (0.5173,0.5752), (0.5437,0.5696), (0.5758,0.5496), (0.5992,0.5226), (0.6000,0.6723), (0.5712,0.6833), (0.5429,0.6891), (0.5154,0.6900), (0.4889,0.6864), (0.4638,0.6785), (0.4328,0.6618), (0.4117,0.6452), (0.3872,0.6181), (0.3672,0.5861), (0.3556,0.5593), (0.3451,0.5205), (0.3413,0.4894), (0.2680,0.4864), (0.2480,0.4787), (0.2335,0.4640), (0.2266,0.4350), (0.2309,0.4137), (0.2453,0.3885), (0.2886,0.3349), (0.3018,0.3681), (0.3268,0.3911), (0.3589,0.4035), (0.4003,0.4036), (0.4260,0.3943), (0.4473,0.3771), (0.4615,0.3549), (0.4748,0.3029), (0.4812,0.2946), (0.4911,0.2929), (0.5007,0.2997), (0.5178,0.3514), (0.5368,0.3798), (0.5681,0.4031), (0.6000,0.4130))),
}


def _supabase_ease(p):
    """cubic-bezier(.45, 0, .55, 1) at `p`, solved rather than approximated.

    Two Newton steps on x(s) = p then evaluate y(s). The curve is symmetric and
    well-behaved, so two steps are inside a thousandth -- and this runs once a
    frame, not once a point.
    """
    s = p
    for _ in range(2):
        u = 1.0 - s
        x = 3.0 * u * u * s * 0.45 + 3.0 * u * s * s * 0.55 + s * s * s
        dx = (3.0 * u * u * 0.45 + 6.0 * u * s * (0.55 - 0.45)
              + 3.0 * s * s * (1.0 - 0.55))
        if dx < 1e-6:
            break
        s -= (x - p) / dx
        s = 0.0 if s < 0.0 else (1.0 if s > 1.0 else s)
    u = 1.0 - s
    return 3.0 * u * s * s * 1.0 + s * s * s


def _supabase_box(buf):
    """The art's box: fit by height, centred, feet on SUPA_FOOT."""
    w, h = buf.width, buf.height
    bh = h * SUPA_FIT
    bw = bh * SUPA_ASPECT
    if bw > w * 0.98:
        bw = w * 0.98
        bh = bw / SUPA_ASPECT
    return ((w - bw) * 0.5, h * SUPA_FOOT - bh, bw, bh)


_SUPA_CACHE = {}


def _supabase_cache(buf):
    """The nineteen shapes and the field brush, built once per canvas size."""
    key = (buf.width, buf.height)
    held = _SUPA_CACHE.get("key")
    if held == key:
        return _SUPA_CACHE
    box = _supabase_box(buf)
    bx, by, bw, bh = box
    shapes = {}
    for ident in SUPA_ORDER:
        points = SUPA_PATHS[ident][1]
        shapes[ident] = shape.custom(
            [vec2(bx + px * bw, by + py * bh) for px, py in points])
    _SUPA_CACHE["key"] = key
    _SUPA_CACHE["box"] = box
    _SUPA_CACHE["shapes"] = shapes
    _SUPA_CACHE["field"] = brush.gradient(
        brush.LINEAR, 0.0, 0.0, 0.0, float(buf.height),
        [(0.0, color.rgb(*SUPA_FIELD_TOP)), (1.0, color.rgb(*SUPA_FIELD_BOTTOM))])
    _SUPA_CACHE["sweep"] = rect(
        int(bx + SUPA_SWEPT[0] * bw) - 2, int(by + SUPA_SWEPT[1] * bh) - 2,
        int((SUPA_SWEPT[2] - SUPA_SWEPT[0]) * bw) + 5,
        int((SUPA_SWEPT[3] - SUPA_SWEPT[1]) * bh) + 5)
    _SUPA_CACHE["full"] = rect(0, 0, buf.width, buf.height)
    return _SUPA_CACHE


def _supabase_paint(buf, held, ident):
    fill = SUPA_PATHS[ident][0]
    buf.pen = color.rgb(fill[0], fill[1], fill[2])
    buf.fill_rule = image.EVEN_ODD if ident in SUPA_HOLES else image.NON_ZERO
    buf.shape(held["shapes"][ident])


def _supabase_field(buf, held):
    buf.pen = held["field"]
    buf.rectangle(0, 0, buf.width, buf.height)


def _supabase_swing(t):
    """The owner's `alternate` swing, as an angle. Integer sweeps, so t=1 == t=0."""
    u = (t * SUPA_SWEEPS) % 1.0
    p = u * 2.0 if u < 0.5 else (1.0 - u) * 2.0
    return SUPA_SWING_LO + (SUPA_SWING_HI - SUPA_SWING_LO) * _supabase_ease(p)


def _supabase_arm_matrix(box, degrees):
    bx, by, bw, bh = box
    px, py = bx + SUPA_PIVOT[0] * bw, by + SUPA_PIVOT[1] * bh
    # THE SUPA_ORDER IS BACKWARDS FROM THE OBVIOUS ONE, and it was measured rather
    # than reasoned. `mat3` composes so that these calls read as "put the pivot
    # at the origin LAST": writing the textbook translate(-p), rotate,
    # translate(+p) rotated the arm about the wrong centre and landed it in the
    # wrong place -- 5.30% of pixels differing from the Chromium reference at the
    # same angle, against 2.60% for this order, which is the antialiasing floor.
    m = mat3()
    m.translate(px, py)
    m.rotate(float(degrees))
    m.translate(-px, -py)
    return m


def _supabase(buf):
    held = _supabase_cache(buf)
    _supabase_field(buf, held)
    matrix = _supabase_arm_matrix(held["box"], _supabase_swing(0.0))
    for ident in SUPA_ARM_IDS:
        held["shapes"][ident].transform = matrix
    for ident in SUPA_ORDER:
        _supabase_paint(buf, held, ident)
    # LEAVE THE SURFACE AS IT WAS FOUND.  This said `NON_ZERO` until 2026-08-21
    # and it cost the owner a badge whose menu text was unreadable: `fill_rule`
    # is STICKY PER SURFACE, `animate`'s `dst` IS the screen, and under NON_ZERO
    # an outline glyph whose counter winds the same way as its body FILLS -- B,
    # O, 8, Q, D, 0 and # in MonaSans-Medium.  EVEN_ODD is picovector's own
    # per-surface default, so this restores rather than imposes, and it changes
    # no pixel here: nothing is drawn after it in this call.
    buf.fill_rule = image.EVEN_ODD


def _supabase_anim(buf, t):
    """Clip to the arm's sweep, then redraw ONLY what lives inside it.

    Seven draws: the field, the four arm paths, and the two body paths whose
    bounding box the sweep intersects -- `body-outline` and `face-dark-top`,
    computed by the emitter rather than guessed. Everything else in the
    character is OUTSIDE the clip, so its absence here cannot show: the clip
    means those pixels keep whatever `render` left them.

    AN EARLIER VERSION OF THIS WAS WRONG AND THE REASON MATTERS. Redrawing just
    those two paths without a clip put `body-outline` -- the full-silhouette
    keyline -- back on top of the face, the shades and the mouth, because
    fourteen paths are drawn over it. Measured 14.25% of pixels wrong against
    the Chromium reference. The fix was never "redraw all nineteen"; it was the
    CLIP. With it, the minimal set is exactly correct, and it is verified at
    2.27% -- the antialiasing floor -- at every sampled phase.
    """
    held = _supabase_cache(buf)
    buf.clip = held["sweep"]
    _supabase_field(buf, held)
    matrix = _supabase_arm_matrix(held["box"], _supabase_swing(t))
    for ident in SUPA_ARM_IDS:
        held["shapes"][ident].transform = matrix
        _supabase_paint(buf, held, ident)
    for ident in SUPA_COVER_IDS:
        _supabase_paint(buf, held, ident)
    # BOTH LINES PUT THE SURFACE BACK, and only the clip did until 2026-08-21.
    # This is the animator, so `buf` IS the screen: whatever it stops on is what
    # the app's chrome type is drawn under.  See `_supabase` above.
    buf.fill_rule = image.EVEN_ODD
    buf.clip = held["full"]


# @skinlab {"type":"color","label":"Screen","group":"Palette"}
TERM_SCREEN = (2, 10, 4)

# @skinlab {"type":"color","label":"Bezel glow","group":"Palette"}
TERM_GLOW = (20, 90, 40)

# @skinlab {"type":"color","label":"Text","group":"Palette"}
TERM_TEXT = (70, 240, 120)

# @skinlab {"type":"color","label":"Cursor","group":"Palette"}
TERM_CURSOR = (120, 255, 160)

# @skinlab {"type":"color","label":"Sweep","group":"Palette"}
TERM_SWEEP_TINT = (160, 255, 190)

# @skinlab {"type":"number","label":"Glow size","group":"Layout","min":0.3,"max":0.9,"step":0.02}
TERM_GLOW_R = 0.62

# @skinlab {"type":"integer","label":"Line spacing","group":"Layout","min":0,"max":8,"step":1}
TERM_LINE_GAP = 1

# @skinlab {"type":"integer","label":"Scanline pitch","group":"Look","min":2,"max":8,"step":1}
TERM_SCANLINE = 2

# @skinlab {"type":"number","label":"Cursor blink","group":"Motion","min":0.3,"max":1,"step":0.05}
TERM_CURSOR_BLINK = 0.5

# @skinlab {"type":"boolean","label":"Sweep bar","group":"Motion"}
TERM_SWEEP_ON = True

# @skinlab {"type":"number","label":"Sweep speed","group":"Motion","min":0.5,"max":6,"step":0.5}
TERM_SWEEP_SPEED = 2.0

# @skinlab {"type":"integer","label":"Typed cells","group":"Motion","min":0,"max":14,"step":1}
TERM_TYPE_CELLS = 9

# @skinlab {"type":"number","label":"Type rate","group":"Motion","min":1,"max":6,"step":1}
TERM_TYPE_RATE = 2.0

# @skinlab {"type":"integer","label":"Live log rows","group":"Motion","min":0,"max":8,"step":1}
TERM_LOG_ROWS = 6

# @skinlab {"type":"number","label":"Log rate","group":"Motion","min":0.5,"max":8,"step":0.5}
TERM_LOG_RATE = 3.0

# @skinlab {"type":"integer","label":"Rolling scanlines","group":"Motion","min":0,"max":5,"step":1}
TERM_ROLL = 3

# Whole laps only: a fractional roll rate leaves a bar mid-screen at t = 1 and
# at the top at t = 0, which is a visible tear once every four seconds.
# @skinlab {"type":"number","label":"Roll speed","group":"Motion","min":1,"max":4,"step":1}
TERM_ROLL_SPEED = 1.0

# @skinlab {"type":"integer","label":"Status lamps","group":"Motion","min":0,"max":5,"step":1}
TERM_LAMPS = 3


def _terminal(buf):
    """A phosphor console mid-session, glow bleeding into the bezel."""
    w, h, u = buf.width, buf.height, _unit(buf)
    buf.pen = color.rgb(*TERM_SCREEN)
    buf.clear()
    buf.pen = color.rgb(TERM_GLOW[0], TERM_GLOW[1], TERM_GLOW[2], 70)
    buf.circle(w // 2, h // 2, int(h * TERM_GLOW_R))
    lengths = (17, 9, 23, 5, 14, 28, 11, 20, 7, 25, 13, 19)
    for row, y in enumerate(range(u, h - u, max(3, u + TERM_LINE_GAP))):
        if h * 0.24 < y < h * 0.48:
            continue
        buf.pen = color.rgb(TERM_TEXT[0], TERM_TEXT[1], TERM_TEXT[2],
                            210 if row % 3 else 130)
        buf.rectangle(u, y, min(w - u * 2, lengths[row % len(lengths)] * u // 2), max(1, u // 2))
    # The scanline is a physical measurement, not a logical one: two panel
    # pixels dark, two clear, at every resolution.
    s = _stroke(buf)
    for y in range(0, h, TERM_SCANLINE * s):
        buf.pen = color.rgb(0, 0, 0, 60)
        buf.rectangle(0, y, w, s)


def _terminal_anim(dst, t):
    """A console MID-SESSION, which means somebody is typing into it.

    The command types itself out along the prompt, the cursor walks with it,
    a log column updates on the right of the standing text, and the tube rolls.
    `render` still draws a complete screen on its own -- the editor views blit
    the background without ever calling this -- so nothing here is a mark the
    background is missing, only the part of the session that is happening now.

    Every typed cell is drawn every frame, ghosted when it has not been typed
    yet. A loop that skips calls would report a cheaper frame than the one the
    wearer actually pays for on the frame the line is full."""
    w, h, u = dst.width, dst.height, _unit(dst)
    s = _stroke(dst)

    # the command line: cells fill left to right, then the line is entered and
    # the next one starts. The reset is not a glitch, it is a carriage return.
    cell = max(2, u * 3 // 2)
    py = h - u * 3
    typed = int(((t * TERM_TYPE_RATE) % 1.0) * (TERM_TYPE_CELLS + 1))
    dst.pen = color.rgb(*TERM_TEXT)
    dst.rectangle(u, py, max(1, u // 2), u * 2)
    for i in range(TERM_TYPE_CELLS):
        lit = i < typed
        dst.pen = color.rgb(TERM_TEXT[0], TERM_TEXT[1], TERM_TEXT[2],
                            225 if lit else 22)
        dst.rectangle(u * 2 + i * cell, py + u // 2,
                      max(1, cell - max(1, u // 3)), max(1, u))
    if t % TERM_CURSOR_BLINK < 0.28:
        dst.pen = color.rgb(*TERM_CURSOR)
    else:
        dst.pen = color.rgb(TERM_CURSOR[0], TERM_CURSOR[1], TERM_CURSOR[2], 60)
    dst.rectangle(u * 2 + min(typed, TERM_TYPE_CELLS) * cell, py, cell, u * 2)

    # a log column updating beside the standing text, low enough to stay clear
    # of the name band
    for i in range(TERM_LOG_ROWS):
        ly = int(h * (0.635 + 0.047 * i))
        step = int(t * TERM_LOG_RATE + i * 0.41) % 3
        wide = max(2, u * (2 + ((i * 5 + step) % 5)))
        dst.pen = color.rgb(TERM_TEXT[0], TERM_TEXT[1], TERM_TEXT[2],
                            230 if step == (i % 3) else 110)
        dst.rectangle(int(w * 0.60), ly, wide, max(1, u // 2))

    # the tube rolls: dark bars drifting down the phosphor
    for i in range(TERM_ROLL):
        dst.pen = color.rgb(0, 0, 0, 80)
        dst.rectangle(0, int(h * ((t * TERM_ROLL_SPEED + i / max(1, TERM_ROLL)) % 1.0)),
                      w, max(1, s * 2))

    # status lamps along the top edge, above the name band
    for i in range(TERM_LAMPS):
        on = ((t * (2.0 + i) + i * 0.29) % 1.0) < 0.45
        dst.pen = color.rgb(TERM_CURSOR[0], TERM_CURSOR[1], TERM_CURSOR[2],
                            235 if on else 50)
        dst.rectangle(w - u * (3 + i * 2), int(h * 0.04), u, max(1, u // 2))

    if TERM_SWEEP_ON:
        dst.pen = color.rgb(TERM_SWEEP_TINT[0], TERM_SWEEP_TINT[1], TERM_SWEEP_TINT[2], 26)
        dst.rectangle(0, int(h * ((t * TERM_SWEEP_SPEED) % 1.0)), w, max(2, u))


# @skinlab {"type":"color","label":"Metal top","group":"Palette"}
OXIDE_METAL_TOP = (46, 26, 16)

# @skinlab {"type":"color","label":"Metal base","group":"Palette"}
OXIDE_METAL_BOTTOM = (18, 12, 10)

# @skinlab {"type":"color","label":"Rust","group":"Palette"}
OXIDE_RUST = (140, 62, 24)

# @skinlab {"type":"color","label":"Gear ring","group":"Palette"}
OXIDE_RING = (206, 102, 44)

# @skinlab {"type":"color","label":"Hub","group":"Palette"}
OXIDE_CORE = (30, 18, 14)

# @skinlab {"type":"integer","label":"Tooth spacing","group":"Shape","min":2,"max":8,"step":1}
OXIDE_TOOTH_GAP = 3

# @skinlab {"type":"integer","label":"Tooth height","group":"Shape","min":1,"max":9,"step":1}
OXIDE_TOOTH_HEIGHT = 3

# @skinlab {"type":"integer","label":"Gear studs","group":"Layout","min":5,"max":20,"step":1}
OXIDE_TEETH = 12

# @skinlab {"type":"number","label":"Ring height","group":"Layout","min":0.4,"max":0.68,"step":0.02}
OXIDE_RING_Y = 0.62

# @skinlab {"type":"number","label":"Ring radius","group":"Layout","min":0.16,"max":0.4,"step":0.02}
OXIDE_RING_R = 0.34

# @skinlab {"type":"integer","label":"Hub spokes","group":"Layout","min":3,"max":9,"step":1}
OXIDE_SPOKES = 5

# @skinlab {"type":"number","label":"Gear speed","group":"Motion","min":0.25,"max":3,"step":0.25}
OXIDE_SPIN = 1.0

# @skinlab {"type":"integer","label":"Ratchet steps","group":"Motion","min":3,"max":16,"step":1}
OXIDE_RATCHET = 6

# @skinlab {"type":"integer","label":"Rust motes","group":"Motion","min":0,"max":12,"step":1}
OXIDE_MOTES = 8

# @skinlab {"type":"number","label":"Mote drift","group":"Motion","min":0.25,"max":3,"step":0.25}
OXIDE_MOTE_SPEED = 1.0


def _oxide(buf):
    """Weathered metal: rust bleeding through a gear-toothed ring."""
    w, h, u = buf.width, buf.height, _unit(buf)
    _vertical(buf, OXIDE_METAL_TOP, OXIDE_METAL_BOTTOM)
    buf.pen = color.rgb(OXIDE_RUST[0], OXIDE_RUST[1], OXIDE_RUST[2], 90)
    for i in range(0, w, u * OXIDE_TOOTH_GAP):
        buf.triangle(i, h, i + u * 2, h,
                     i + u, h - u * (OXIDE_TOOTH_HEIGHT + (i // max(1, u)) % 5))
    cx, cy, r = w // 2, int(h * OXIDE_RING_Y), int(h * OXIDE_RING_R)
    for i in range(OXIDE_TEETH):
        a = 2 * math.pi * i / OXIDE_TEETH
        buf.pen = color.rgb(*OXIDE_RING)
        buf.circle(int(cx + math.cos(a) * r), int(cy + math.sin(a) * r), max(2, u))
    buf.pen = color.rgb(*OXIDE_RING)
    buf.circle(cx, cy, r - u)
    buf.pen = color.rgb(*OXIDE_CORE)
    buf.circle(cx, cy, r - u * 3)


def _oxide_anim(dst, t):
    """The gear TURNS. A gear-toothed ring that never moves is the joke, so the
    spokes sweep the dark hub, a bolt rides between each of them, the light
    ratchets stud to stud around the rim, and rust lifts off the hot base.

    Everything rotates by exactly one spoke pitch over the cycle, so t = 1
    puts spoke i where spoke i+1 stood at t = 0 and the loop is invisible.
    Nothing here repeats a mark `render` already drew: the hub is bare dark
    metal in the background and the ratchet glint sits ON an existing stud."""
    w, h, u = dst.width, dst.height, _unit(dst)
    cx, cy, r = w // 2, int(h * OXIDE_RING_Y), int(h * OXIDE_RING_R)
    turn = 2.0 * math.pi * ((t * OXIDE_SPIN) % 1.0) / OXIDE_SPOKES
    hub = max(2, r - u * 3)
    wid = max(1, u // 2)
    dst.pen = color.rgb(OXIDE_RING[0], OXIDE_RING[1], OXIDE_RING[2], 210)
    for i in range(OXIDE_SPOKES):
        a = turn + 2.0 * math.pi * i / OXIDE_SPOKES
        ca, sa = math.cos(a), math.sin(a)
        dst.triangle(int(cx - sa * wid), int(cy + ca * wid),
                     int(cx + sa * wid), int(cy - ca * wid),
                     int(cx + ca * hub), int(cy + sa * hub))
    # a bolt head between every pair of spokes, out on the plate
    bolt = (hub * 3) // 4
    dst.pen = color.rgb(OXIDE_METAL_TOP[0], OXIDE_METAL_TOP[1], OXIDE_METAL_TOP[2])
    for i in range(OXIDE_SPOKES):
        a = turn + 2.0 * math.pi * (i + 0.5) / OXIDE_SPOKES
        dst.circle(int(cx + math.cos(a) * bolt), int(cy + math.sin(a) * bolt), wid)
    dst.pen = color.rgb(*OXIDE_CORE)
    dst.circle(cx, cy, max(2, u))
    # the light ratchets round the rim, tooth by tooth
    k = int(t * OXIDE_RATCHET) % OXIDE_RATCHET
    for j in range(3):
        idx = (k * OXIDE_TEETH // OXIDE_RATCHET + j - 1) % OXIDE_TEETH
        a = 2.0 * math.pi * idx / OXIDE_TEETH
        dst.pen = color.rgb(255, 190, 120, 235 if j == 1 else 90)
        dst.circle(int(cx + math.cos(a) * r), int(cy + math.sin(a) * r), max(2, u))
    # rust lifting off the hot base, below the name band
    for i in range(OXIDE_MOTES):
        p = (t * OXIDE_MOTE_SPEED + i * 0.127) % 1.0
        mx = (i * 149) % w + int(u * math.sin((p + i * 0.31) * 4.0 * math.pi))
        my = h - int(p * h * 0.34)
        dst.pen = color.rgb(230, 138, 62, 200 - int(p * 190))
        dst.rectangle(mx, my, max(1, u // 2), max(1, u // 2))


# ── RETRO ──────────────────────────────────────────────────────────────────


# @skinlab {"type":"color","label":"Tube top","group":"Palette"}
CRT_TUBE_TOP = (8, 14, 10)

# @skinlab {"type":"color","label":"Tube bottom","group":"Palette"}
CRT_TUBE_BOTTOM = (16, 30, 20)

# @skinlab {"type":"color","label":"Phosphor glow","group":"Palette"}
CRT_GLOW = (90, 220, 140)

# @skinlab {"type":"color","label":"Hot spot","group":"Palette"}
CRT_HOTSPOT = (150, 255, 190)

# @skinlab {"type":"color","label":"Flyback beam","group":"Palette"}
CRT_BEAM = (200, 255, 220)

# @skinlab {"type":"integer","label":"Scanline depth","group":"Look","min":0,"max":255,"step":5}
CRT_SCANLINE_ALPHA = 90

# @skinlab {"type":"integer","label":"Corner darkness","group":"Look","min":0,"max":255,"step":5}
CRT_VIGNETTE_ALPHA = 200

# @skinlab {"type":"integer","label":"Scanline pitch","group":"Layout","min":2,"max":8,"step":1}
CRT_SCANLINE_PITCH = 3

# @skinlab {"type":"integer","label":"Corner falloff width","group":"Layout","min":1,"max":6,"step":1}
CRT_VIGNETTE_BANDS = 3

# @skinlab {"type":"number","label":"Tube radius","group":"Shape","min":0.25,"max":0.6,"step":0.01}
CRT_TUBE_RADIUS = 0.44

# @skinlab {"type":"number","label":"Hot spot size","group":"Shape","min":0.08,"max":0.42,"step":0.01}
CRT_HOTSPOT_SIZE = 0.26

# @skinlab {"type":"number","label":"Hot spot height","group":"Shape","min":0.15,"max":0.7,"step":0.01}
CRT_HOTSPOT_Y = 0.42

# @skinlab {"type":"number","label":"Flyback speed","group":"Motion","min":0.25,"max":4,"step":0.25}
CRT_SWEEP_SPEED = 1.0

# @skinlab {"type":"integer","label":"Blanking bands","group":"Layout","min":0,"max":8,"step":1}
CRT_BLANK_BANDS = 4

# @skinlab {"type":"integer","label":"Persistence bands","group":"Layout","min":1,"max":8,"step":1}
CRT_GLOW_BANDS = 5

# @skinlab {"type":"integer","label":"Seam brightness","group":"Look","min":0,"max":200,"step":5}
CRT_ROLL_ALPHA = 80

# @skinlab {"type":"integer","label":"Phosphor sparks","group":"Layout","min":0,"max":14,"step":1}
CRT_SPARKS = 8

# @skinlab {"type":"integer","label":"Spark brightness","group":"Look","min":0,"max":255,"step":5}
CRT_SPARK_ALPHA = 70

# @skinlab {"type":"integer","label":"Mains hum depth","group":"Look","min":0,"max":60,"step":2}
CRT_HUM_ALPHA = 14

# @skinlab {"type":"number","label":"Mains hum speed","group":"Motion","min":0.25,"max":4,"step":0.25}
CRT_HUM_SPEED = 2.0

# @skinlab {"type":"integer","label":"Warm-up breathe","group":"Look","min":0,"max":60,"step":2}
CRT_WARM_ALPHA = 12


def _crt(buf):
    """A tube warming up: curved vignette, scanlines, corner falloff."""
    w, h, u = buf.width, buf.height, _unit(buf)
    _vertical(buf, CRT_TUBE_TOP, CRT_TUBE_BOTTOM)
    buf.pen = color.rgb(CRT_GLOW[0], CRT_GLOW[1], CRT_GLOW[2], 40)
    buf.circle(w // 2, h // 2, int(w * CRT_TUBE_RADIUS))
    buf.pen = color.rgb(CRT_HOTSPOT[0], CRT_HOTSPOT[1], CRT_HOTSPOT[2], 26)
    buf.circle(w // 2, int(h * CRT_HOTSPOT_Y), int(w * CRT_HOTSPOT_SIZE))
    # Scanlines are the whole idea of a tube, so they are measured in panel
    # pixels. Left as a logical 3 they halved in millimetres at HIRES and the
    # tube read as a flat wash. CRT_SCANLINE_PITCH multiplies _stroke(); it
    # does not replace it.
    s = _stroke(buf)
    for y in range(0, h, CRT_SCANLINE_PITCH * s):
        buf.pen = color.rgb(0, 0, 0, CRT_SCANLINE_ALPHA)
        buf.rectangle(0, y, w, s)
    for i in range(u * CRT_VIGNETTE_BANDS):
        buf.pen = color.rgb(0, 0, 0, max(0, CRT_VIGNETTE_ALPHA - i * 60 // max(1, u)))
        buf.rectangle(0, i, w, 1)
        buf.rectangle(0, h - 1 - i, w, 1)
        buf.rectangle(i, 0, 1, h)
        buf.rectangle(w - 1 - i, 0, 1, h)


def _crt_anim(dst, t):
    """The vertical hold never quite locks.

    A tube that is not framed properly rolls: the frame seam climbs the glass
    with the blanking interval dark ahead of it and the phosphor decaying
    behind it, the mains hum beats a broad shadow through at its own rate, and
    the gun spits sparks along the live line. Bands are stacked _unit() rows
    rather than one tall rectangle so the decay is visible instead of flat.
    """
    w, h, u = dst.width, dst.height, _unit(dst)
    s = _stroke(dst)
    band = max(2, u)
    y = int(h * (1.0 - (t * CRT_SWEEP_SPEED) % 1.0))
    for i in range(CRT_BLANK_BANDS):
        dst.pen = color.rgb(0, 0, 0, max(0, 96 - i * 22))
        dst.rectangle(0, y - (i + 1) * band, w, band)
    fade = max(1, CRT_ROLL_ALPHA // CRT_GLOW_BANDS)
    for i in range(CRT_GLOW_BANDS):
        dst.pen = color.rgb(CRT_BEAM[0], CRT_BEAM[1], CRT_BEAM[2],
                            max(4, CRT_ROLL_ALPHA - i * fade))
        dst.rectangle(0, y + i * band, w, band)
    reach = max(1, band * CRT_GLOW_BANDS)
    for i in range(CRT_SPARKS):
        sx = (i * 53 + int(t * 89)) % max(1, w)
        dst.pen = color.rgb(CRT_HOTSPOT[0], CRT_HOTSPOT[1], CRT_HOTSPOT[2],
                            CRT_SPARK_ALPHA)
        dst.rectangle(sx, y + (i * 31) % reach, max(2, u // 2), s)
    dst.pen = color.rgb(CRT_GLOW[0], CRT_GLOW[1], CRT_GLOW[2], CRT_HUM_ALPHA)
    dst.rectangle(0, int(h * (1.0 - (t * CRT_HUM_SPEED) % 1.0)) - h // 4,
                  w, max(2, h // 4))
    warm = max(0, CRT_WARM_ALPHA + int(CRT_WARM_ALPHA * math.sin(t * 2 * math.pi)))
    dst.pen = color.rgb(CRT_GLOW[0], CRT_GLOW[1], CRT_GLOW[2], warm)
    dst.rectangle(0, 0, w, u * 2)
    dst.rectangle(0, h - u * 2, w, u * 2)


# @skinlab {"type":"color","label":"Screen","group":"Palette"}
AMBER_SCREEN = (14, 8, 2)

# @skinlab {"type":"color","label":"Phosphor text","group":"Palette"}
AMBER_TEXT = (255, 176, 40)

# @skinlab {"type":"integer","label":"Dim line brightness","group":"Look","min":0,"max":255,"step":5}
AMBER_DIM_ALPHA = 160

# @skinlab {"type":"integer","label":"Bright line brightness","group":"Look","min":0,"max":255,"step":5}
AMBER_BRIGHT_ALPHA = 220

# @skinlab {"type":"integer","label":"Edge bar glow","group":"Look","min":0,"max":255,"step":5}
AMBER_EDGE_ALPHA = 30

# @skinlab {"type":"integer","label":"Line spacing","group":"Layout","min":1,"max":4,"step":1}
AMBER_LINE_SPACING = 1

# @skinlab {"type":"number","label":"Clear band top","group":"Layout","min":0.05,"max":0.45,"step":0.01}
AMBER_GAP_TOP = 0.24

# @skinlab {"type":"number","label":"Clear band bottom","group":"Layout","min":0.25,"max":0.75,"step":0.01}
AMBER_GAP_BOTTOM = 0.48

# @skinlab {"type":"integer","label":"Refresh trail","group":"Layout","min":1,"max":14,"step":1}
AMBER_REFRESH_ROWS = 9

# @skinlab {"type":"number","label":"Refresh speed","group":"Motion","min":0.25,"max":4,"step":0.25}
AMBER_REFRESH_SPEED = 1.0

# @skinlab {"type":"integer","label":"Refresh brightness","group":"Look","min":0,"max":255,"step":5}
AMBER_GLOW_ALPHA = 165

# @skinlab {"type":"integer","label":"Beam wash","group":"Look","min":0,"max":80,"step":2}
AMBER_BEAM_ALPHA = 26

# @skinlab {"type":"integer","label":"Meter bars","group":"Layout","min":0,"max":10,"step":1}
AMBER_METERS = 8

# @skinlab {"type":"number","label":"Meter drift","group":"Motion","min":0.25,"max":4,"step":0.25}
AMBER_METER_SPEED = 1.0

# @skinlab {"type":"number","label":"Cursor blink","group":"Motion","min":0.05,"max":0.5,"step":0.05}
AMBER_CURSOR_BLINK = 0.25

# @skinlab {"type":"integer","label":"Phosphor flicker","group":"Look","min":0,"max":24,"step":1}
AMBER_FLICKER = 5


def _amber(buf):
    """Amber monochrome: a ledger nobody has read since 1983."""
    w, h, u = buf.width, buf.height, _unit(buf)
    buf.pen = color.rgb(*AMBER_SCREEN)
    buf.clear()
    widths = (26, 12, 30, 18, 8, 22, 34, 15)
    for row, y in enumerate(range(u * 2, h - u, max(3, u + 1) * AMBER_LINE_SPACING)):
        if h * AMBER_GAP_TOP < y < h * AMBER_GAP_BOTTOM:
            continue
        buf.pen = color.rgb(AMBER_TEXT[0], AMBER_TEXT[1], AMBER_TEXT[2],
                            AMBER_DIM_ALPHA if row % 2 else AMBER_BRIGHT_ALPHA)
        buf.rectangle(u * 2, y, min(w - u * 4, widths[row % len(widths)] * u // 2), max(1, u // 2))
    buf.pen = color.rgb(AMBER_TEXT[0], AMBER_TEXT[1], AMBER_TEXT[2], AMBER_EDGE_ALPHA)
    buf.rectangle(0, 0, w, u)
    buf.rectangle(0, h - u, w, u)


def _amber_a(dst, t):
    """The refresh beam crawling down a ledger nobody has read since 1983.

    A monochrome terminal at idle is not a still image: the beam relights one
    line at a time and the lines behind it decay, the block cursor waits at
    the prompt, the meters on the right keep reporting to nobody, and the
    whole tube breathes on the mains. The trail wraps rather than resetting,
    which is what a raster does, so t = 1 joins t = 0 with the head simply
    back at the top row.
    """
    w, h, u = dst.width, dst.height, _unit(dst)
    step = max(3, u + 1) * AMBER_LINE_SPACING
    top = u * 2
    rows = max(1, (h - u - top + step - 1) // step)
    widths = (26, 12, 30, 18, 8, 22, 34, 15)
    head = int(rows * ((t * AMBER_REFRESH_SPEED) % 1.0))
    drop = max(1, AMBER_GLOW_ALPHA // AMBER_REFRESH_ROWS)
    dst.pen = color.rgb(AMBER_TEXT[0], AMBER_TEXT[1], AMBER_TEXT[2], AMBER_BEAM_ALPHA)
    dst.rectangle(0, top + head * step - step, w, step * 2)
    for i in range(AMBER_REFRESH_ROWS):
        row = (head - i) % rows
        y = top + row * step
        if h * AMBER_GAP_TOP < y < h * AMBER_GAP_BOTTOM:
            continue
        dst.pen = color.rgb(255, 220, 150, max(0, AMBER_GLOW_ALPHA - i * drop))
        dst.rectangle(u * 2, y,
                      min(w - u * 4, widths[row % len(widths)] * u // 2),
                      max(1, u // 2))
    mx = w * 2 // 3
    span = max(2, w // 3 - u * 3)
    for i in range(AMBER_METERS):
        k = math.sin(t * AMBER_METER_SPEED * 2 * math.pi + i * 1.05)
        dst.pen = color.rgb(AMBER_TEXT[0], AMBER_TEXT[1], AMBER_TEXT[2], 210)
        dst.rectangle(mx, int(h * 0.66) + i * max(2, u),
                      max(1, int(span * (0.55 + 0.45 * k))), max(1, u // 2))
    cy = top + (rows - 1) * step
    if (t % AMBER_CURSOR_BLINK) * 2 < AMBER_CURSOR_BLINK:
        run = min(w - u * 4, widths[(rows - 1) % len(widths)] * u // 2)
        dst.pen = color.rgb(255, 232, 176, 240)
        dst.rectangle(u * 2 + run + max(1, u // 2), cy - max(1, u // 4),
                      max(2, u // 2), max(2, u))
    dst.pen = color.rgb(AMBER_TEXT[0], AMBER_TEXT[1], AMBER_TEXT[2],
                        max(0, AMBER_FLICKER
                            + int(AMBER_FLICKER * math.sin(t * 6 * math.pi))))
    dst.rectangle(0, 0, w, h)


# @skinlab {"type":"color","label":"Text","group":"Palette"}
BSOD_TEXT = (134, 122, 222)

# @skinlab {"type":"color","label":"Panel","group":"Palette"}
BSOD_PANEL = (72, 58, 170)

# @skinlab {"type":"integer","label":"Border width","group":"Layout","min":1,"max":3,"step":1}
BSOD_BORDER = 2

# @skinlab {"type":"number","label":"Message top","group":"Layout","min":0.3,"max":0.8,"step":0.01}
BSOD_TEXT_TOP = 0.52

# @skinlab {"type":"integer","label":"Line spacing","group":"Layout","min":1,"max":4,"step":1}
BSOD_LINE_SPACING = 1

# @skinlab {"type":"integer","label":"Shortest line","group":"Layout","min":2,"max":14,"step":1}
BSOD_LINE_MIN = 7

# @skinlab {"type":"integer","label":"Line length spread","group":"Layout","min":1,"max":24,"step":1}
BSOD_LINE_SPREAD = 17

# @skinlab {"type":"integer","label":"Heading width","group":"Layout","min":4,"max":28,"step":1}
BSOD_HEADING = 12

# @skinlab {"type":"color","label":"Dump fill","group":"Palette"}
BSOD_DUMP = (198, 190, 250)

# @skinlab {"type":"integer","label":"Dump blocks","group":"Layout","min":2,"max":24,"step":1}
BSOD_DUMP_BLOCKS = 14

# @skinlab {"type":"integer","label":"Address digits","group":"Layout","min":0,"max":12,"step":1}
BSOD_HEX_COLS = 6

# @skinlab {"type":"number","label":"Dump speed","group":"Motion","min":0.25,"max":4,"step":0.25}
BSOD_DUMP_SPEED = 1.0

# @skinlab {"type":"integer","label":"Address churn","group":"Motion","min":1,"max":48,"step":1}
BSOD_HEX_SPEED = 24

# @skinlab {"type":"number","label":"Cursor blink","group":"Motion","min":0.05,"max":0.5,"step":0.05}
BSOD_CURSOR_BLINK = 0.25


def _bluescreen(buf):
    """That blue, that border, that chunky confidence."""
    w, h, u = buf.width, buf.height, _unit(buf)
    buf.pen = color.rgb(*BSOD_TEXT)
    buf.clear()
    buf.pen = color.rgb(*BSOD_PANEL)
    buf.rectangle(u * BSOD_BORDER, u * BSOD_BORDER,
                  w - u * BSOD_BORDER * 2, h - u * BSOD_BORDER * 2)
    for row, y in enumerate(range(int(h * BSOD_TEXT_TOP), h - u * 3,
                                  max(3, u + 1) * BSOD_LINE_SPACING)):
        buf.pen = color.rgb(*BSOD_TEXT)
        buf.rectangle(u * 4, y, (BSOD_LINE_MIN + (row * 5) % BSOD_LINE_SPREAD) * u, max(1, u // 2))
    buf.pen = color.rgb(*BSOD_TEXT)
    buf.rectangle(u * 4, u * 4, u * BSOD_HEADING, max(1, u))


def _bluescreen_a(dst, t):
    """The dump is the only thing still running, and it is not going well.

    Everything else on a stop screen is frozen by definition -- that is the
    joke -- so the motion is confined to the two lines a halted kernel keeps
    writing: the address it is walking and the progress of the memory it is
    committing to a disk nobody will read. The last two message rows are
    repainted in panel blue first, because `animate` draws over the blitted
    background and cannot erase what `render` already put there.
    """
    w, h, u = dst.width, dst.height, _unit(dst)
    step = max(3, u + 1) * BSOD_LINE_SPACING
    top = int(h * BSOD_TEXT_TOP)
    n = max(2, (h - u * 3 - top + step - 1) // step)
    hex_y = top + (n - 2) * step
    bar_y = top + (n - 1) * step
    dst.pen = color.rgb(*BSOD_PANEL)
    dst.rectangle(u * 3, hex_y - max(1, u // 4), w - u * 6,
                  bar_y - hex_y + max(2, u) + max(1, u // 4))
    k = int(t * BSOD_HEX_SPEED)
    cell = max(2, (w - u * 8) // max(1, BSOD_HEX_COLS))
    for i in range(BSOD_HEX_COLS):
        run = 2 + (i * 37 + k * 11) % 5
        dst.pen = color.rgb(*BSOD_TEXT)
        dst.rectangle(u * 4 + i * cell, hex_y,
                      max(1, cell * run // 8), max(1, u // 2))
    span = w - u * 8
    slot = max(2, span // max(1, BSOD_DUMP_BLOCKS))
    filled = int(BSOD_DUMP_BLOCKS * ((t * BSOD_DUMP_SPEED) % 1.0)) + 1
    for i in range(BSOD_DUMP_BLOCKS):
        if i < filled:
            dst.pen = color.rgb(*BSOD_DUMP)
        else:
            dst.pen = color.rgb(BSOD_TEXT[0], BSOD_TEXT[1], BSOD_TEXT[2], 90)
        dst.rectangle(u * 4 + i * slot, bar_y,
                      max(1, slot - max(1, u // 3)), max(2, u))
    if (t % BSOD_CURSOR_BLINK) * 2 < BSOD_CURSOR_BLINK:
        dst.pen = color.rgb(*BSOD_DUMP)
        dst.rectangle(u * 4 + BSOD_DUMP_BLOCKS * slot + max(1, u // 2), bar_y,
                      max(2, u // 2), max(2, u))


# @skinlab {"type":"color","label":"Deep space","group":"Palette"}
STAR_SPACE = (4, 4, 14)

# @skinlab {"type":"color","label":"Starlight","group":"Palette"}
STAR_INK = (255, 255, 255)

# @skinlab {"type":"integer","label":"Star count","group":"Layout","min":0,"max":160,"step":5}
STAR_COUNT = 70

# @skinlab {"type":"color","label":"Planet rim","group":"Palette"}
STAR_RIM = (24, 18, 60)

# @skinlab {"type":"color","label":"Planet","group":"Palette"}
STAR_PLANET = (90, 60, 180)

# @skinlab {"type":"color","label":"Terminator glow","group":"Palette"}
STAR_GLOW = (180, 150, 255)

# @skinlab {"type":"number","label":"Rim reach","group":"Layout","min":0.40,"max":0.70,"step":0.01}
STAR_RIM_R = 0.58

# @skinlab {"type":"number","label":"Planet size","group":"Layout","min":0.40,"max":0.78,"step":0.01}
STAR_PLANET_R = 0.54

# @skinlab {"type":"integer","label":"Twinkles","group":"Motion","min":0,"max":30,"step":1}
STAR_TWINKLES = 20

# @skinlab {"type":"integer","label":"Twinkle speed","group":"Motion","min":1,"max":8,"step":1}
STAR_TWINKLE_SPEED = 3

# @skinlab {"type":"number","label":"Twinkle duty","group":"Motion","min":0.05,"max":0.9,"step":0.05}
STAR_TWINKLE_DUTY = 0.35

# @skinlab {"type":"integer","label":"Flaring stars","group":"Layout","min":0,"max":4,"step":1}
STAR_FLARES = 2

# @skinlab {"type":"integer","label":"Flare speed","group":"Motion","min":1,"max":4,"step":1}
STAR_FLARE_SPEED = 1

# @skinlab {"type":"integer","label":"Terminator breath","group":"Motion","min":1,"max":3,"step":1}
STAR_GLOW_PULSE = 1

# @skinlab {"type":"color","label":"Station hull","group":"Palette"}
STAR_STATION_INK = (188, 196, 220)

# @skinlab {"type":"boolean","label":"Passing station","group":"Motion"}
STAR_STATION = True

# @skinlab {"type":"integer","label":"Station speed","group":"Motion","min":1,"max":3,"step":1}
STAR_STATION_SPEED = 1

# @skinlab {"type":"boolean","label":"Meteor","group":"Motion"}
STAR_METEOR = True

# @skinlab {"type":"integer","label":"Meteor rate","group":"Motion","min":1,"max":6,"step":1}
STAR_METEOR_RATE = 1


def _starfield(buf):
    """A planet's edge, and a very long way down."""
    w, h, u = buf.width, buf.height, _unit(buf)
    buf.pen = color.rgb(*STAR_SPACE)
    buf.clear()
    for i in range(STAR_COUNT):
        buf.pen = color.rgb(STAR_INK[0], STAR_INK[1], STAR_INK[2], 90 + (i % 4) * 50)
        buf.rectangle((i * 37) % w, (i * 61) % h, 1, 1)
    buf.pen = color.rgb(*STAR_RIM)
    buf.circle(int(w * 0.24), int(h * 1.12), int(h * STAR_RIM_R))
    buf.pen = color.rgb(*STAR_PLANET)
    buf.circle(int(w * 0.24), int(h * 1.12), int(h * STAR_PLANET_R))
    buf.pen = color.rgb(STAR_GLOW[0], STAR_GLOW[1], STAR_GLOW[2], 120)
    buf.circle(int(w * 0.18), int(h * 1.02), int(h * 0.14))


def _starfield_anim(dst, t):
    """The whole field breathes: stars brighten and fade on the scatter the
    render already laid down, two of them flare, the terminator swells, and
    something crewed goes quietly past."""
    w, h, u = dst.width, dst.height, _unit(dst)
    s = _stroke(dst)
    ang = t * 6.283185
    px, py = int(w * 0.24), int(h * 1.12)
    pr = int(h * STAR_PLANET_R)
    for i in range(STAR_TWINKLES):
        x = (i * 137) % w
        y = (i * 89) % h
        dx, dy = x - px, y - py
        if dx * dx + dy * dy < pr * pr:
            continue                      # that one is behind the planet
        b = 0.5 + 0.5 * math.sin(ang * STAR_TWINKLE_SPEED + i * 2.399)
        dst.pen = color.rgb(STAR_INK[0], STAR_INK[1], STAR_INK[2], int(30 + 225 * b))
        dst.rectangle(x, y, s, s)
    for i in range(STAR_FLARES):
        p = (t * STAR_FLARE_SPEED + i * 0.5) % 1.0
        if p >= STAR_TWINKLE_DUTY:
            continue
        b = math.sin(p / STAR_TWINKLE_DUTY * 3.14159)
        x = int(w * (0.62 + i * 0.24))
        y = int(h * (0.18 + i * 0.30))
        arm = max(1, int(u * (0.5 + 1.8 * b)))
        dst.pen = color.rgb(STAR_GLOW[0], STAR_GLOW[1], STAR_GLOW[2], int(40 + 150 * b))
        dst.rectangle(x - arm, y, arm * 2, s)
        dst.rectangle(x, y - arm, s, arm * 2)
        dst.pen = color.rgb(255, 255, 255, int(90 + 165 * b))
        dst.rectangle(x, y, s * 2, s * 2)
    breath = 0.5 + 0.5 * math.sin(ang * STAR_GLOW_PULSE)
    dst.pen = color.rgb(STAR_GLOW[0], STAR_GLOW[1], STAR_GLOW[2], int(40 + 70 * breath))
    dst.circle(int(w * 0.18), int(h * 1.02), int(h * (0.12 + 0.03 * breath)))
    if STAR_STATION:
        q = (t * STAR_STATION_SPEED) % 1.0
        sx = -int(w * 0.10) + int(w * 1.20 * q)
        sy = int(h * 0.22 + math.sin(q * 6.283185) * h * 0.02)
        dst.pen = color.rgb(*STAR_STATION_INK)
        dst.rectangle(sx, sy, max(2, int(u * 1.6)), max(1, s * 2))
        dst.pen = color.rgb(70, 90, 150)
        dst.rectangle(sx - max(1, s * 2), sy - max(1, s), max(1, s * 2), max(2, int(u * 0.8)))
        dst.rectangle(sx + max(2, int(u * 1.6)), sy - max(1, s), max(1, s * 2),
                      max(2, int(u * 0.8)))
        dst.pen = color.rgb(255, 90, 80, 230 if (t * 5.0) % 1.0 < 0.3 else 40)
        dst.rectangle(sx + max(1, int(u * 0.7)), sy - max(1, s), s * 2, s * 2)
    if STAR_METEOR:
        p = (t * STAR_METEOR_RATE) % 1.0
        if p < 0.18:
            q = p / 0.18
            mx = int(w * (0.98 - 0.55 * q))
            my = int(h * (0.02 + 0.34 * q))
            dst.pen = color.rgb(255, 246, 220, int(220 - 170 * q))
            dst.line(mx, my, mx + int(w * 0.07), my - int(h * 0.05))
            dst.pen = color.rgb(255, 255, 255, 240)
            dst.rectangle(mx, my, s * 2, s * 2)


# ── GRAPHIC ────────────────────────────────────────────────────────────────


# @skinlab {"type":"color","label":"Paper","group":"Palette"}
BAUHAUS_PAPER = (236, 228, 210)

# @skinlab {"type":"color","label":"Disc","group":"Palette"}
BAUHAUS_DISC = (212, 58, 44)

# @skinlab {"type":"color","label":"Wedge","group":"Palette"}
BAUHAUS_WEDGE = (30, 56, 140)

# @skinlab {"type":"color","label":"Bar","group":"Palette"}
BAUHAUS_BAR = (240, 196, 40)

# @skinlab {"type":"color","label":"Rule","group":"Palette"}
BAUHAUS_RULE = (24, 22, 20)

# @skinlab {"type":"number","label":"Disc across","group":"Layout","min":0.25,"max":1,"step":0.02}
BAUHAUS_DISC_X = 0.74

# @skinlab {"type":"number","label":"Disc down","group":"Layout","min":0.05,"max":0.7,"step":0.02}
BAUHAUS_DISC_Y = 0.30

# @skinlab {"type":"number","label":"Disc size","group":"Shape","min":0.15,"max":0.65,"step":0.02}
BAUHAUS_DISC_R = 0.40

# @skinlab {"type":"number","label":"Wedge width","group":"Shape","min":0.2,"max":1,"step":0.02}
BAUHAUS_WEDGE_W = 0.52

# @skinlab {"type":"number","label":"Wedge peak","group":"Shape","min":0.05,"max":0.7,"step":0.02}
BAUHAUS_WEDGE_TOP = 0.30

# @skinlab {"type":"number","label":"Bar height","group":"Layout","min":0.35,"max":0.9,"step":0.02}
BAUHAUS_BAR_Y = 0.66

# @skinlab {"type":"integer","label":"Bar weight","group":"Shape","min":1,"max":8,"step":1}
BAUHAUS_BAR_W = 3

# @skinlab {"type":"number","label":"Rule height","group":"Layout","min":0.2,"max":0.95,"step":0.02}
BAUHAUS_RULE_Y = 0.60


def _bauhaus(buf):
    """Three colours, one crop, no apologies."""
    w, h, u = buf.width, buf.height, _unit(buf)
    buf.pen = color.rgb(*BAUHAUS_PAPER)
    buf.clear()
    buf.pen = color.rgb(*BAUHAUS_DISC)
    buf.circle(int(w * BAUHAUS_DISC_X), int(h * BAUHAUS_DISC_Y), int(h * BAUHAUS_DISC_R))
    buf.pen = color.rgb(*BAUHAUS_WEDGE)
    buf.triangle(0, h, int(w * BAUHAUS_WEDGE_W), h, 0, int(h * BAUHAUS_WEDGE_TOP))
    buf.pen = color.rgb(*BAUHAUS_BAR)
    buf.rectangle(int(w * 0.10), int(h * BAUHAUS_BAR_Y), w, u * BAUHAUS_BAR_W)
    buf.pen = color.rgb(*BAUHAUS_RULE)
    buf.rectangle(0, int(h * BAUHAUS_RULE_Y), w, max(1, u // 2))


# @skinlab {"type":"color","label":"Sky top","group":"Palette"}
FLOOR_SKY_TOP = (12, 12, 24)

# @skinlab {"type":"color","label":"Sky at horizon","group":"Palette"}
FLOOR_SKY_BOTTOM = (44, 30, 70)

# @skinlab {"type":"color","label":"Horizon line","group":"Palette"}
FLOOR_EDGE = (250, 240, 220)

# @skinlab {"type":"color","label":"Pale tile","group":"Palette"}
FLOOR_TILE_LIGHT = (230, 226, 240)

# @skinlab {"type":"color","label":"Shadow tile","group":"Palette"}
FLOOR_TILE_DARK = (90, 80, 130)

# @skinlab {"type":"number","label":"Horizon height","group":"Layout","min":0.25,"max":0.7,"step":0.02}
FLOOR_HORIZON = 0.46

# The 1.32 is geometric growth that integer truncation eats below band == 4, so
# the low end stays well above 1.0 and the high end stops before the floor
# collapses into three enormous rows.
# @skinlab {"type":"number","label":"Depth falloff","group":"Shape","min":1.15,"max":1.55,"step":0.01}
FLOOR_GROWTH = 1.32

# @skinlab {"type":"number","label":"Tile width","group":"Shape","min":1.4,"max":3,"step":0.1}
FLOOR_TILE_ASPECT = 2.2

# @skinlab {"type":"color","label":"Tile light","group":"Palette"}
FLOOR_LIGHT = (120, 240, 255)

# The floor is a dance floor: the tiles light in a band that rolls out of the
# horizon and past the wearer, which is forward motion drawn as many small
# marks. Scrolling the checker instead would mean repainting the whole lower
# half every frame -- a screen and a half of fill, against the 21 small
# rectangles this costs.
# @skinlab {"type":"integer","label":"Lit tiles per row","group":"Layout","min":0,"max":3,"step":1}
FLOOR_LIGHT_TILES = 3

# @skinlab {"type":"number","label":"Light speed","group":"Motion","min":0.25,"max":4,"step":0.25}
FLOOR_LIGHT_SPEED = 1.0

# How far the band lags one row behind the row in front of it. Small values
# flash the whole floor at once; large ones stretch the band past a full cycle.
# @skinlab {"type":"number","label":"Row lag","group":"Motion","min":0.03,"max":0.3,"step":0.01}
FLOOR_LIGHT_LEAN = 0.055

# @skinlab {"type":"number","label":"Light trail","group":"Motion","min":0.1,"max":1,"step":0.05}
FLOOR_LIGHT_DUTY = 0.40


def _floor(buf):
    """A checkerboard floor running to a hard horizon."""
    w, h, u = buf.width, buf.height, _unit(buf)
    _vertical(buf, FLOOR_SKY_TOP, FLOOR_SKY_BOTTOM, 0, max(1, int(h * FLOOR_HORIZON)))
    horizon = int(h * FLOOR_HORIZON)
    buf.pen = color.rgb(*FLOOR_EDGE)
    buf.rectangle(0, horizon, w, max(1, u // 2))
    row, y, band = 0, horizon, max(1, u // 2)
    while y < h:
        band = max(band + 1, int(band * FLOOR_GROWTH))
        for i in range(9):
            if (i + row) % 2:
                continue
            x0 = int(w * 0.5 + (i - 4.0) * (band * FLOOR_TILE_ASPECT))
            buf.pen = (color.rgb(*FLOOR_TILE_LIGHT) if row % 2
                       else color.rgb(*FLOOR_TILE_DARK))
            buf.rectangle(x0, y, int(band * FLOOR_TILE_ASPECT) + 1, band)
        y += band
        row += 1


def _floor_a(dst, t):
    """A band of lit tiles rolling out of the horizon and past the wearer.

    It walks the SAME band geometry `_floor` does, so a light always lands on a
    tile that is really there rather than on the black between them. Each row
    fires a fixed lag after the row behind it, so the band reads as one thing
    travelling forward instead of the floor blinking.
    """
    w, h, u = dst.width, dst.height, _unit(dst)
    tt = (t * FLOOR_LIGHT_SPEED) % 1.0
    row, y, band = 0, int(h * FLOOR_HORIZON), max(1, u // 2)
    while y < h:
        band = max(band + 1, int(band * FLOOR_GROWTH))
        q = (tt - row * FLOOR_LIGHT_LEAN) % 1.0
        if q < FLOOR_LIGHT_DUTY:
            level = int(235 * (1.0 - q / FLOOR_LIGHT_DUTY))
            if level > 10:
                tw = int(band * FLOOR_TILE_ASPECT) + 1
                dst.pen = color.rgb(FLOOR_LIGHT[0], FLOOR_LIGHT[1],
                                    FLOOR_LIGHT[2], level)
                for j in range(FLOOR_LIGHT_TILES):
                    # A tile only exists where (i + row) is even, so the slot
                    # takes the row's parity; 2, 4, 6 keeps the band on the
                    # three centre columns, which are the ones still on the
                    # panel once the near rows have spread.
                    i = (row % 2) + 2 * j + 2
                    dst.rectangle(int(w * 0.5 + (i - 4.0)
                                      * (band * FLOOR_TILE_ASPECT)),
                                  y, tw, band)
        y += band
        row += 1


# @skinlab {"type":"color","label":"Backdrop","group":"Palette"}
ARCS_BACKDROP = (16, 26, 32)

# @skinlab {"type":"color","label":"Deep arc","group":"Palette"}
ARCS_TINT_A = (0, 189, 88)

# @skinlab {"type":"color","label":"Mid arc","group":"Palette"}
ARCS_TINT_B = (62, 207, 142)

# @skinlab {"type":"color","label":"Pale arc","group":"Palette"}
ARCS_TINT_C = (149, 230, 184)

# @skinlab {"type":"color","label":"Lightest arc","group":"Palette"}
ARCS_TINT_D = (225, 252, 215)

# ARCS is the most expensive skin in the catalogue (247.9 ms at HIRES): every
# ring is two huge filled circles, so the top of this range is deliberately
# close to the default.
# @skinlab {"type":"integer","label":"Arc count","group":"Layout","min":3,"max":11,"step":1}
ARCS_RINGS = 9

# @skinlab {"type":"number","label":"Centre across","group":"Layout","min":-0.2,"max":0.5,"step":0.02}
ARCS_ORIGIN_X = 0.04

# @skinlab {"type":"number","label":"Centre down","group":"Layout","min":0.5,"max":1.2,"step":0.02}
ARCS_ORIGIN_Y = 0.86

# @skinlab {"type":"number","label":"Arc spacing","group":"Shape","min":0.1,"max":0.34,"step":0.01}
ARCS_SPACING = 0.20

# @skinlab {"type":"integer","label":"Arc weight","group":"Shape","min":1,"max":4,"step":1}
ARCS_WEIGHT = 1

# The rings are a signal leaving the bottom-left corner, so the motion is a
# charge running OUTWARD through them rather than anything sliding across the
# picture. Every mark is a small square on purpose: ARCS is the most
# expensive render in the catalogue (247.9 ms at HIRES) exactly because a
# filled circle centred here covers most of the panel, and an animator that
# added one would pay that bill on every frame instead of once per selection.
# Rays times pulses IS the per-frame call count, because every mark is drawn
# whether or not the crop keeps it, so the two maxima multiply out to 36 of
# the 40 an animator gets.
# @skinlab {"type":"integer","label":"Pulse rays","group":"Layout","min":0,"max":12,"step":1}
ARCS_PULSE_RAYS = 9

# @skinlab {"type":"integer","label":"Pulses in flight","group":"Motion","min":1,"max":3,"step":1}
ARCS_PULSE_WAVES = 3

# @skinlab {"type":"number","label":"Pulse speed","group":"Motion","min":0.25,"max":4,"step":0.25}
ARCS_PULSE_SPEED = 1.0

# A multiple of the ring weight, not of the stroke: a charge is a bright
# chunk OF an arc, so it has to be as thick as the arc it is riding.
# @skinlab {"type":"integer","label":"Pulse size","group":"Shape","min":1,"max":3,"step":1}
ARCS_PULSE_SIZE = 1


def _arcs(buf):
    """Concentric arcs cropped hard by the bottom-left corner."""
    w, h, u = buf.width, buf.height, _unit(buf)
    buf.pen = color.rgb(*ARCS_BACKDROP)
    buf.clear()
    tints = (ARCS_TINT_A, ARCS_TINT_B, ARCS_TINT_C, ARCS_TINT_D)
    for i in range(ARCS_RINGS, 0, -1):
        tint = tints[i % len(tints)]
        buf.pen = color.rgb(tint[0], tint[1], tint[2])
        buf.circle(int(w * ARCS_ORIGIN_X), int(h * ARCS_ORIGIN_Y),
                   int(h * ARCS_SPACING * i))
        buf.pen = color.rgb(*ARCS_BACKDROP)
        buf.circle(int(w * ARCS_ORIGIN_X), int(h * ARCS_ORIGIN_Y),
                   max(1, int(h * ARCS_SPACING * i) - max(2, u * ARCS_WEIGHT)))


def _arcs_a(dst, t):
    """Charges leaving the corner and running out through the rings.

    Three fronts are in flight at once, a third of a cycle apart, so the corner
    is never empty and the panel is never empty either. A front is brightest
    where it is born and dims as it spreads, which is the physics the picture
    already draws; by the time it has faded it is past the far corner, so the
    wrap at t = 1 happens off the panel.
    """
    w, h = dst.width, dst.height
    u = _unit(dst)
    cx, cy = int(w * ARCS_ORIGIN_X), int(h * ARCS_ORIGIN_Y)
    step = h * ARCS_SPACING
    sz = max(2, u * ARCS_PULSE_SIZE)
    tt = (t * ARCS_PULSE_SPEED) % 1.0
    rays = max(1, ARCS_PULSE_RAYS)
    far = math.sqrt((w - cx) * (w - cx) + cy * cy) + sz
    for j in range(ARCS_PULSE_WAVES):
        # Every ray of one wave shares a radius, so the charges line up into a
        # front CONCENTRIC with the rings instead of a scatter. Staggering them
        # per ray was tried first and read as dust.
        p = (tt + j * 1.0 / ARCS_PULSE_WAVES) % 1.0
        r = step * 0.7 + (far - step * 0.7) * p
        dst.pen = color.rgb(ARCS_TINT_D[0], ARCS_TINT_D[1], ARCS_TINT_D[2],
                            255 - int(120 * p))
        for k in range(rays):
            # The visible crop is the quadrant from straight up to straight
            # right; a front leaves the top edge before it leaves the right
            # one, so part of every front is off the panel. Those marks are
            # drawn and clipped rather than tested: a bounds test written in
            # pixels answers differently at the two resolutions once int() has
            # rounded, and the count has to be RAYS x PULSES at both.
            a = -1.5708 + 1.5708 * (k + 0.5) / rays
            dst.rectangle(int(cx + math.cos(a) * r) - sz // 2,
                          int(cy + math.sin(a) * r) - sz // 2, sz, sz)


# ── NEON ───────────────────────────────────────────────────────────────────


# @skinlab {"type":"color","label":"Sky top","group":"Palette"}
SYNTH_SKY_TOP = (18, 6, 46)

# @skinlab {"type":"color","label":"Sky at horizon","group":"Palette"}
SYNTH_SKY_HORIZON = (86, 16, 92)

# @skinlab {"type":"color","label":"Sun","group":"Palette"}
SYNTH_SUN = (255, 96, 140)

# @skinlab {"type":"color","label":"Sun core","group":"Palette"}
SYNTH_SUN_CORE = (255, 208, 96)

# @skinlab {"type":"color","label":"Ground","group":"Palette"}
SYNTH_GROUND = (10, 4, 24)

# @skinlab {"type":"color","label":"Horizon glow","group":"Palette"}
SYNTH_HORIZON_GLOW = (255, 60, 190)

# @skinlab {"type":"color","label":"Grid","group":"Palette"}
SYNTH_GRID = (200, 40, 200)

# @skinlab {"type":"color","label":"Sweep","group":"Palette"}
SYNTH_SWEEP = (255, 120, 240)

# @skinlab {"type":"number","label":"Horizon height","group":"Layout","min":0.4,"max":0.55,"step":0.01}
SYNTH_HORIZON = 0.52

# @skinlab {"type":"number","label":"Sun height","group":"Layout","min":0.36,"max":0.55,"step":0.01}
SYNTH_SUN_Y = 0.40

# @skinlab {"type":"number","label":"Sun size","group":"Shape","min":0.1,"max":0.4,"step":0.01}
SYNTH_SUN_R = 0.26

# @skinlab {"type":"integer","label":"Rays each side","group":"Layout","min":2,"max":9,"step":1}
SYNTH_GRID_SPAN = 6

# @skinlab {"type":"integer","label":"Ray spread","group":"Shape","min":3,"max":16,"step":1}
SYNTH_GRID_SPREAD = 9

# @skinlab {"type":"number","label":"Perspective growth","group":"Layout","min":1.05,"max":2.5,"step":0.05}
SYNTH_BAND_GROWTH = 1.4

# A COUNT of scrolls per loop, and it has to stay a whole number: the grid is
# drawn from `(i + frac) / rules`, so the set of rules at `frac = 1` is the set
# at `frac = 0` shifted one index -- the same picture -- only when a whole
# number of scrolls fits in the four-second cycle.
# @skinlab {"type":"integer","label":"Grid scrolls per loop","group":"Motion","min":1,"max":4,"step":1}
SYNTH_SWEEP_SPEED = 1

# @skinlab {"type":"integer","label":"Moving grid rules","group":"Layout","min":4,"max":16,"step":1}
SYNTH_RULES = 12

# @skinlab {"type":"integer","label":"Rising sun cuts","group":"Layout","min":0,"max":8,"step":1}
SYNTH_CUTS = 5

# @skinlab {"type":"integer","label":"Reflection bands","group":"Layout","min":0,"max":10,"step":1}
SYNTH_REFLECTS = 6


def _synthwave(buf):
    """Sun with horizontal cuts, grid running to the horizon."""
    w, h, u = buf.width, buf.height, _unit(buf)
    _vertical(buf, SYNTH_SKY_TOP, SYNTH_SKY_HORIZON, 0, max(1, int(h * SYNTH_HORIZON)))
    cx, cy, r = w // 2, int(h * SYNTH_SUN_Y), int(h * SYNTH_SUN_R)
    buf.pen = color.rgb(*SYNTH_SUN)
    buf.circle(cx, cy, r)
    buf.pen = color.rgb(*SYNTH_SUN_CORE)
    buf.circle(cx, cy - r // 3, max(1, r * 2 // 3))
    for i, y in enumerate(range(cy, cy + r + 1, max(2, u))):
        buf.pen = color.rgb(*SYNTH_SKY_TOP)
        buf.rectangle(cx - r, y, r * 2, max(1, (i * u) // 4 + max(1, u // 3)))
    horizon = int(h * SYNTH_HORIZON)
    buf.pen = color.rgb(*SYNTH_GROUND)
    buf.rectangle(0, horizon, w, h - horizon)
    buf.pen = color.rgb(SYNTH_HORIZON_GLOW[0], SYNTH_HORIZON_GLOW[1], SYNTH_HORIZON_GLOW[2], 200)
    buf.rectangle(0, horizon, w, max(1, u // 2))
    s = _stroke(buf)
    for i in range(-SYNTH_GRID_SPAN, SYNTH_GRID_SPAN + 1):
        buf.pen = color.rgb(SYNTH_GRID[0], SYNTH_GRID[1], SYNTH_GRID[2], 150)
        _thick_line(buf, cx + i * u, horizon, cx + i * u * SYNTH_GRID_SPREAD, h, s)
    y, band = horizon, max(1, u // 2)
    while y < h:
        buf.pen = color.rgb(SYNTH_GRID[0], SYNTH_GRID[1], SYNTH_GRID[2], 130)
        buf.rectangle(0, y, w, s)
        band = max(band + 1, int(band * SYNTH_BAND_GROWTH))
        y += band


def _synthwave_anim(dst, t):
    """The floor running at you, and the sun striping itself.

    The whole grid scrolls rather than one highlight sliding along it: each
    rule sits at `f = (i + frac) / rules` squared into perspective, so they
    crowd at the horizon and race apart underfoot, and the set repeats
    exactly when `frac` wraps.  The cuts across the sun rise and thin as they
    go, which is the one piece of a synthwave sun that is supposed to move.
    Runners chase the radial rays down the same depth curve, so the two
    halves of the floor share one motion instead of arguing.
    """
    w, h, u = dst.width, dst.height, _unit(dst)
    s = _stroke(dst)
    horizon = int(h * SYNTH_HORIZON)
    depth = max(1, h - horizon)
    frac = (t * SYNTH_SWEEP_SPEED) % 1.0
    cx = w // 2
    cy, r = int(h * SYNTH_SUN_Y), int(h * SYNTH_SUN_R)
    for i in range(SYNTH_CUTS):
        f = (i + frac) / SYNTH_CUTS
        cyy = cy - int(r * f)
        # Follow the sun's silhouette, or a rectangle of sky colour hangs off
        # its shoulders. `** 0.5` is the chord half-width and needs no import.
        hw = max(1, int(r * (1.0 - f * f) ** 0.5))
        dst.pen = color.rgb(SYNTH_SKY_TOP[0], SYNTH_SKY_TOP[1], SYNTH_SKY_TOP[2], 235)
        dst.rectangle(cx - hw, cyy, hw * 2, max(1, int(u * (1.15 - 0.95 * f))))
    dst.pen = color.rgb(SYNTH_HORIZON_GLOW[0], SYNTH_HORIZON_GLOW[1],
                        SYNTH_HORIZON_GLOW[2], 130 + int(90 * frac * (1.0 - frac) * 4))
    dst.rectangle(0, horizon - s, w, max(1, u // 2))
    for i in range(SYNTH_RULES):
        f = (i + frac) / SYNTH_RULES
        near = f * f
        dst.pen = color.rgb(SYNTH_SWEEP[0], SYNTH_SWEEP[1], SYNTH_SWEEP[2],
                            60 + int(160 * near))
        dst.rectangle(0, horizon + int(depth * near), w, s * 2)
    for i in range(SYNTH_REFLECTS):
        f = (i + frac) / SYNTH_REFLECTS
        near = f * f
        rw = max(1, int(r * (0.55 + 2.1 * near) * (0.72 if i % 2 else 1.0)))
        dst.pen = color.rgb(SYNTH_SUN[0], SYNTH_SUN[1], SYNTH_SUN[2],
                            int(120 * (1.0 - near)))
        dst.rectangle(cx - rw, horizon + int(depth * near), rw * 2,
                      max(1, int(u * (0.4 + near))))


# @skinlab {"type":"color","label":"Backdrop top","group":"Palette"}
GLITCH_BG_TOP = (10, 8, 20)

# @skinlab {"type":"color","label":"Backdrop bottom","group":"Palette"}
GLITCH_BG_BOTTOM = (26, 16, 40)

# @skinlab {"type":"color","label":"Hot band","group":"Palette"}
GLITCH_MAGENTA = (255, 40, 90)

# @skinlab {"type":"color","label":"Cold band","group":"Palette"}
GLITCH_CYAN = (40, 240, 255)

# @skinlab {"type":"color","label":"Flash bar","group":"Palette"}
GLITCH_FLASH = (255, 255, 255)

# @skinlab {"type":"integer","label":"Band variety","group":"Shape","min":1,"max":8,"step":1}
GLITCH_BAND_STEPS = 4

# @skinlab {"type":"integer","label":"Tear centre","group":"Shape","min":2,"max":15,"step":1}
GLITCH_SHIFT_BIAS = 8

# @skinlab {"type":"integer","label":"Band gap","group":"Layout","min":0,"max":6,"step":1}
GLITCH_GAP = 1

# @skinlab {"type":"integer","label":"Flash steps","group":"Motion","min":2,"max":16,"step":1}
GLITCH_JUMPS = 8

# @skinlab {"type":"integer","label":"Flash thickness","group":"Shape","min":1,"max":6,"step":1}
GLITCH_FLASH_HEIGHT = 2

# @skinlab {"type":"integer","label":"Flash strength","group":"Look","min":0,"max":255,"step":5}
GLITCH_FLASH_ALPHA = 60

# @skinlab {"type":"number","label":"Tear speed","group":"Motion","min":0.5,"max":8,"step":0.5}
GLITCH_TEAR_SPEED = 3

# @skinlab {"type":"integer","label":"Tear swing","group":"Motion","min":0,"max":12,"step":1}
GLITCH_TEAR_SWING = 3

# @skinlab {"type":"integer","label":"Slices tearing loose","group":"Layout","min":0,"max":10,"step":1}
GLITCH_TEARS = 7

# @skinlab {"type":"integer","label":"Dropout blocks","group":"Layout","min":0,"max":8,"step":1}
GLITCH_DROPOUTS = 4

# @skinlab {"type":"integer","label":"Tear rate","group":"Motion","min":2,"max":32,"step":1}
GLITCH_TEAR_RATE = 16


def _glitch(buf):
    """Bands that did not survive the copy."""
    w, h, u = buf.width, buf.height, _unit(buf)
    _vertical(buf, GLITCH_BG_TOP, GLITCH_BG_BOTTOM)
    offsets = (3, 11, 6, 17, 9, 2, 14, 7)
    y, i = 0, 0
    while y < h:
        band = u * (1 + offsets[i % len(offsets)] % GLITCH_BAND_STEPS)
        shift = (offsets[i % len(offsets)] - GLITCH_SHIFT_BIAS) * u
        buf.pen = color.rgb(GLITCH_MAGENTA[0], GLITCH_MAGENTA[1], GLITCH_MAGENTA[2], 190)
        buf.rectangle(shift, y, w, band)
        buf.pen = color.rgb(GLITCH_CYAN[0], GLITCH_CYAN[1], GLITCH_CYAN[2], 150)
        buf.rectangle(-shift, y + max(1, band // 3), w, max(1, band // 2))
        buf.pen = color.rgb(GLITCH_BG_TOP[0], GLITCH_BG_TOP[1], GLITCH_BG_TOP[2], 150)
        buf.rectangle(0, y + band - max(1, u // 2), w, max(1, u // 2))
        y += band + u * GLITCH_GAP
        i += 1


def _glitch_anim(dst, t):
    """The copy failing AGAIN, live: slices tearing loose, blocks dropping out.

    `k` is a stepped clock rather than `t` itself, so the picture HOLDS for a
    sixteenth of the loop and then jumps -- a corrupted decode does not ease.
    Every position is a hash of `(k, i)`, so it is deterministic, and `k` never
    reaches `GLITCH_TEAR_RATE` because `t < 1`, which is what makes the wrap
    join cleanly.  The slices are a third of the width, not the whole of it:
    a torn macroblock run, and far less filled area than a full-width bar.
    """
    w, h, u = dst.width, dst.height, _unit(dst)
    s = _stroke(dst)
    k = int(t * GLITCH_TEAR_RATE)
    swing = GLITCH_TEAR_SWING * 2 + 1
    for i in range(GLITCH_TEARS):
        j = (k * 7 + i * 13) % 19
        y = h * j // 19
        band = max(2, u * (1 + j % GLITCH_BAND_STEPS))
        bw = w // 3 + ((i * 5 + k) % 3) * w // 6
        x = ((k * 11 + i * 29) % 23) * w // 23 - w // 4
        sh = ((k * 13 + i * 7) % swing - GLITCH_TEAR_SWING) * u
        dst.pen = color.rgb(GLITCH_MAGENTA[0], GLITCH_MAGENTA[1], GLITCH_MAGENTA[2], 205)
        dst.rectangle(x + sh, y, bw, band)
        dst.pen = color.rgb(GLITCH_CYAN[0], GLITCH_CYAN[1], GLITCH_CYAN[2], 175)
        dst.rectangle(x - sh, y + band // 2, bw, max(1, band // 2))
        dst.pen = color.rgb(GLITCH_BG_TOP[0], GLITCH_BG_TOP[1], GLITCH_BG_TOP[2], 210)
        dst.rectangle(x, y + band, bw, s * 2)
    for i in range(GLITCH_DROPOUTS):
        dst.pen = color.rgb(GLITCH_BG_BOTTOM[0], GLITCH_BG_BOTTOM[1], GLITCH_BG_BOTTOM[2], 235)
        dst.rectangle(((k * 7 + i * 5) % 11) * w // 11, h * ((k * 3 + i * 17) % 13) // 13,
                      u * (2 + i % 3), u * (1 + i % 2))
    y = int(h * ((int(t * GLITCH_JUMPS) % GLITCH_JUMPS) / GLITCH_JUMPS))
    dst.pen = color.rgb(GLITCH_FLASH[0], GLITCH_FLASH[1], GLITCH_FLASH[2], GLITCH_FLASH_ALPHA)
    dst.rectangle(0, y, w, u * GLITCH_FLASH_HEIGHT)
    dst.pen = color.rgb(GLITCH_CYAN[0], GLITCH_CYAN[1], GLITCH_CYAN[2], 130)
    dst.rectangle(int(-u * GLITCH_TEAR_SWING + u * GLITCH_TEAR_SWING * 2 * ((t * GLITCH_TEAR_SPEED) % 1.0)),
                  y + u, w, max(1, u))


# @skinlab {"type":"color","label":"White bar","group":"Palette"}
TESTCARD_WHITE = (192, 192, 192)

# @skinlab {"type":"color","label":"Yellow bar","group":"Palette"}
TESTCARD_YELLOW = (192, 192, 0)

# @skinlab {"type":"color","label":"Cyan bar","group":"Palette"}
TESTCARD_CYAN = (0, 192, 192)

# @skinlab {"type":"color","label":"Green bar","group":"Palette"}
TESTCARD_GREEN = (0, 192, 0)

# @skinlab {"type":"color","label":"Magenta bar","group":"Palette"}
TESTCARD_MAGENTA = (192, 0, 192)

# @skinlab {"type":"color","label":"Red bar","group":"Palette"}
TESTCARD_RED = (192, 0, 0)

# @skinlab {"type":"color","label":"Blue bar","group":"Palette"}
TESTCARD_BLUE = (0, 0, 192)

# @skinlab {"type":"color","label":"Lower-row separator","group":"Palette"}
TESTCARD_BLACK = (16, 16, 16)

# @skinlab {"type":"integer","label":"Grey steps","group":"Layout","min":4,"max":9,"step":1}
TESTCARD_STEPS = 8

# @skinlab {"type":"integer","label":"Step brightness rise","group":"Look","min":12,"max":30,"step":1}
TESTCARD_STEP_RISE = 26

# @skinlab {"type":"color","label":"Roll bar","group":"Palette"}
TESTCARD_ROLL = (255, 255, 255)

# @skinlab {"type":"color","label":"Roll trail","group":"Palette"}
TESTCARD_ROLL_SHADOW = (0, 0, 0)

# The roll bar's speed is a COUNT of passes, not a rate, and it has to stay an
# integer: `(t * speed) % 1.0` only rejoins itself at `t = 1 -> 0` when a whole
# number of passes fits in the loop. At 1.3 the bar used to reappear a third of
# the way down the picture once every four seconds.
# @skinlab {"type":"integer","label":"Roll passes per loop","group":"Motion","min":1,"max":6,"step":1}
TESTCARD_ROLL_SPEED = 2

# @skinlab {"type":"integer","label":"Roll thickness","group":"Motion","min":1,"max":8,"step":1}
TESTCARD_ROLL_UNITS = 3

# @skinlab {"type":"integer","label":"Torn bands","group":"Layout","min":0,"max":4,"step":1}
TESTCARD_TEARS = 2

# @skinlab {"type":"integer","label":"Hold scans per loop","group":"Motion","min":1,"max":6,"step":1}
TESTCARD_TEAR_SPEED = 1

# @skinlab {"type":"integer","label":"Tear offset","group":"Motion","min":0,"max":12,"step":1}
TESTCARD_SHIFT = 5

# Five, and the ceiling is nine, because of a constraint that binds only here:
# `test_identity_browse` requires every animator to cost less than its OWN
# render, and TEST CARD has the second-cheapest render in the catalogue -- 22
# calls, because twenty-two enormous filled bars cover the screen. Twenty-two
# calls is not a cheap render (7.754 ms on device, against ARCS' 64.169 for
# nineteen), but it is a small NUMBER, and this animator has to stay under it.
# @skinlab {"type":"integer","label":"Noise speckles","group":"Layout","min":0,"max":9,"step":1}
TESTCARD_NOISE = 5

# @skinlab {"type":"integer","label":"Noise rate","group":"Motion","min":2,"max":40,"step":1}
TESTCARD_NOISE_RATE = 20


def _testcard(buf):
    """No signal. Colour bars, and the grey steps nobody looks at."""
    w, h, u = buf.width, buf.height, _unit(buf)
    bars = (TESTCARD_WHITE, TESTCARD_YELLOW, TESTCARD_CYAN, TESTCARD_GREEN,
            TESTCARD_MAGENTA, TESTCARD_RED, TESTCARD_BLUE)
    span = max(1, w // len(bars) + 1)
    for i, tint in enumerate(bars):
        buf.pen = color.rgb(tint[0], tint[1], tint[2])
        buf.rectangle(i * span, 0, span, int(h * 0.74))
    lower = (TESTCARD_BLUE, TESTCARD_BLACK, TESTCARD_MAGENTA, TESTCARD_BLACK,
             TESTCARD_CYAN, TESTCARD_BLACK, TESTCARD_WHITE)
    for i, tint in enumerate(lower):
        buf.pen = color.rgb(tint[0], tint[1], tint[2])
        buf.rectangle(i * span, int(h * 0.74), span, max(1, int(h * 0.12)))
    step = max(1, w // TESTCARD_STEPS)
    for i in range(TESTCARD_STEPS):
        level = 16 + i * TESTCARD_STEP_RISE
        buf.pen = color.rgb(level, level, level)
        buf.rectangle(i * step, int(h * 0.86), step + 1, h)


def _testcard_anim(dst, t):
    """No signal, and the set knows it: the hold slips, the picture fizzes.

    Three failures of a dead transmitter, and every one of them is a failure
    the bars exist to reveal.  A torn band redraws the SEVEN colour bars
    displaced sideways -- horizontal hold letting go, which is why it is the
    bars themselves and not a foreign stripe.  Speckles fizz on a stepped
    clock, kept in the top and bottom of the frame so the nickname band stays
    quiet.  The frame roll is last, over the top of both.
    """
    w, h, u = dst.width, dst.height, _unit(dst)
    s = _stroke(dst)
    bars = (TESTCARD_WHITE, TESTCARD_YELLOW, TESTCARD_CYAN, TESTCARD_GREEN,
            TESTCARD_MAGENTA, TESTCARD_RED, TESTCARD_BLUE)
    span = max(1, w // len(bars) + 1)
    for n in range(TESTCARD_TEARS):
        p = (t * TESTCARD_TEAR_SPEED + n * 0.5) % 1.0
        ty = int(h * p) - u
        off = int(u * TESTCARD_SHIFT * (1.0 - 2.0 * p)) * (1 if n % 2 else -1)
        for i in range(len(bars)):
            tint = bars[i]
            dst.pen = color.rgb(tint[0], tint[1], tint[2], 235)
            dst.rectangle(i * span + off, ty, span, max(2, u * 2))
    k = int(t * TESTCARD_NOISE_RATE)
    for i in range(TESTCARD_NOISE):
        lvl = 30 + ((i * 37 + k * 11) % 5) * 54
        x = (i * 53 + k * 29) % w
        zone = (i * 31 + k * 47) % 100
        if i % 2:
            ny = int(h * (0.63 + zone * 0.0036))
        else:
            ny = int(h * zone * 0.0022)
        dst.pen = color.rgb(lvl, lvl, lvl, 190)
        dst.rectangle(x, ny, s * 2, s * 2)
    y = int(h * ((t * TESTCARD_ROLL_SPEED) % 1.0))
    dst.pen = color.rgb(TESTCARD_ROLL[0], TESTCARD_ROLL[1], TESTCARD_ROLL[2], 40)
    dst.rectangle(0, y, w, u * TESTCARD_ROLL_UNITS)
    dst.pen = color.rgb(TESTCARD_ROLL_SHADOW[0], TESTCARD_ROLL_SHADOW[1],
                        TESTCARD_ROLL_SHADOW[2], 70)
    dst.rectangle(0, y + u * TESTCARD_ROLL_UNITS, w, max(1, u))


# @skinlab {"type":"color","label":"Skin, top","group":"Palette"}
FACE_SKIN_TOP = (255, 206, 70)

# @skinlab {"type":"color","label":"Skin, bottom","group":"Palette"}
FACE_SKIN_BOTTOM = (250, 160, 40)

# @skinlab {"type":"color","label":"Features","group":"Palette"}
FACE_INK = (40, 28, 10)

# @skinlab {"type":"color","label":"Blush","group":"Palette"}
FACE_BLUSH = (255, 120, 120)

# @skinlab {"type":"color","label":"Eyelid","group":"Palette"}
FACE_LID = (252, 186, 56)

# @skinlab {"type":"color","label":"Tongue","group":"Palette"}
FACE_TONGUE = (226, 84, 96)

# @skinlab {"type":"color","label":"Delight","group":"Palette"}
FACE_SPARK = (255, 250, 220)

# @skinlab {"type":"integer","label":"Eye size","group":"Shape","min":1,"max":4,"step":1}
FACE_EYE_UNITS = 2

# @skinlab {"type":"boolean","label":"Blink","group":"Motion"}
FACE_BLINK = True

# @skinlab {"type":"number","label":"Blink interval","group":"Motion","min":0.1,"max":1.0,"step":0.05}
FACE_BLINK_EVERY = 0.5

# @skinlab {"type":"number","label":"Blink length","group":"Motion","min":0.02,"max":0.3,"step":0.01}
FACE_BLINK_LENGTH = 0.06

# @skinlab {"type":"number","label":"Eye travel","group":"Motion","min":0,"max":1,"step":0.05}
FACE_LOOK = 0.55

# @skinlab {"type":"integer","label":"Looks per loop","group":"Motion","min":1,"max":4,"step":1}
FACE_LOOK_RATE = 1

# @skinlab {"type":"integer","label":"Grins per loop","group":"Motion","min":1,"max":6,"step":1}
FACE_GRIN_RATE = 2

# @skinlab {"type":"integer","label":"Delight sparks","group":"Layout","min":0,"max":4,"step":1}
FACE_SPARKS = 3


def _face(buf):
    """A large idiot, delighted to be here."""
    w, h, u = buf.width, buf.height, _unit(buf)
    _vertical(buf, FACE_SKIN_TOP, FACE_SKIN_BOTTOM)
    buf.pen = color.rgb(*FACE_INK)
    buf.circle(int(w * 0.32), int(h * 0.56), max(2, u * FACE_EYE_UNITS))
    buf.circle(int(w * 0.68), int(h * 0.56), max(2, u * FACE_EYE_UNITS))
    buf.rectangle(int(w * 0.30), int(h * 0.76), int(w * 0.40), max(2, u))
    buf.circle(int(w * 0.30), int(h * 0.78), max(1, u))
    buf.circle(int(w * 0.70), int(h * 0.78), max(1, u))
    buf.pen = color.rgb(FACE_BLUSH[0], FACE_BLUSH[1], FACE_BLUSH[2], 120)
    buf.circle(int(w * 0.16), int(h * 0.68), max(2, u * 2))
    buf.circle(int(w * 0.84), int(h * 0.68), max(2, u * 2))


def _face_tone(h, y):
    """The skin gradient's exact colour at row `y`.

    An animator that wants to MOVE a baked feature has to paint the skin back
    over it first, and a flat patch on a gradient is a visible plate. This is
    the same arithmetic `_vertical` used to lay the gradient down, so the
    patch is the pixel that was already there.
    """
    k = y * 255 // max(1, h - 1)
    return (FACE_SKIN_TOP[0] + (FACE_SKIN_BOTTOM[0] - FACE_SKIN_TOP[0]) * k // 255,
            FACE_SKIN_TOP[1] + (FACE_SKIN_BOTTOM[1] - FACE_SKIN_TOP[1]) * k // 255,
            FACE_SKIN_TOP[2] + (FACE_SKIN_BOTTOM[2] - FACE_SKIN_TOP[2]) * k // 255)


def _face_anim(dst, t):
    """The idiot, actually delighted: looking about, grinning, blinking.

    A face that only blinks is a photograph of a face. So the eyes track, the
    brows go up with the grin, the mouth widens far enough to show tongue and
    the cheeks warm with it -- one shared `joy` phase, so the features agree
    with each other instead of each running its own timer. Both are triangle
    waves off `t`, which need no `math` and rejoin exactly at the wrap. The
    sparks are kept above and below the nickname band; everything else here
    is slow and broad, which that band tolerates.
    """
    w, h, u = dst.width, dst.height, _unit(dst)
    ey = int(h * 0.56)
    er = max(2, u * FACE_EYE_UNITS)
    skin = _face_tone(h, ey)
    q = abs(2.0 * ((t * FACE_LOOK_RATE) % 1.0) - 1.0)
    look = max(-1.0, min(1.0, (q - 0.5) * 3.0))
    joy = abs(2.0 * ((t * FACE_GRIN_RATE) % 1.0) - 1.0)
    shut = FACE_BLINK and (t % FACE_BLINK_EVERY) < FACE_BLINK_LENGTH
    for s in (-1, 1):
        ex = int(w * (0.5 + s * 0.18))
        if shut:
            dst.pen = color.rgb(*FACE_LID)
        else:
            dst.pen = color.rgb(skin[0], skin[1], skin[2])
        dst.circle(ex, ey, er + max(1, u // 2))
        if shut:
            dst.pen = color.rgb(*FACE_INK)
            dst.rectangle(ex - er, ey, er * 2, max(2, u * 2 // 3))
        else:
            px = ex + int(er * FACE_LOOK * look)
            dst.pen = color.rgb(*FACE_INK)
            dst.circle(px, ey, er)
            dst.pen = color.rgb(255, 255, 255)
            dst.circle(px - er // 3, ey - er // 3, max(1, er // 3))
        dst.pen = color.rgb(*FACE_INK)
        dst.rectangle(ex - er, ey - er - max(2, u) - int(u * joy), er * 2, max(1, u // 2))
    my = int(h * 0.76)
    lip = _face_tone(h, my)
    dst.pen = color.rgb(lip[0], lip[1], lip[2])
    dst.rectangle(int(w * 0.26), my - max(1, u // 2), int(w * 0.48), u * 3)
    mw = int(w * 0.40 * (0.76 + 0.34 * joy))
    mx = w // 2 - mw // 2
    if joy > 0.72:
        dst.pen = color.rgb(*FACE_TONGUE)
        dst.circle(w // 2, my + max(2, u), max(2, int(u * 1.4)))
    dst.pen = color.rgb(*FACE_INK)
    dst.rectangle(mx, my, mw, max(2, u))
    dst.circle(mx, my + max(1, u) // 2 + max(1, u), max(1, u))
    dst.circle(mx + mw, my + max(1, u) // 2 + max(1, u), max(1, u))
    dst.pen = color.rgb(FACE_BLUSH[0], FACE_BLUSH[1], FACE_BLUSH[2], 55 + int(75 * joy))
    dst.circle(int(w * 0.16), int(h * 0.68), max(2, u * 2) + int(u * joy))
    dst.circle(int(w * 0.84), int(h * 0.68), max(2, u * 2) + int(u * joy))
    spots = ((0.11, 0.12), (0.89, 0.09), (0.50, 0.93), (0.22, 0.95))
    for i in range(FACE_SPARKS):
        p = (t * 3 + i * 0.34) % 1.0
        if p > 0.45:
            continue
        g = max(2, int(u * (1.6 - 2.4 * abs(p - 0.22))))
        sx, sy = int(w * spots[i][0]), int(h * spots[i][1])
        dst.pen = color.rgb(*FACE_SPARK)
        dst.rectangle(sx - g, sy - max(1, u // 3), g * 2, max(1, u * 2 // 3))
        dst.rectangle(sx - max(1, u // 3), sy - g, max(1, u * 2 // 3), g * 2)


# @skinlab {"type":"color","label":"Void","group":"Palette"}
VECTOR_VOID = (0, 0, 0)

# @skinlab {"type":"color","label":"Wireframe","group":"Palette"}
VECTOR_WIRE = (80, 255, 140)

# @skinlab {"type":"color","label":"Perspective rays","group":"Palette"}
VECTOR_RAYS = (40, 160, 90)

# @skinlab {"type":"color","label":"Spinning outline","group":"Palette"}
VECTOR_TRACE = (190, 255, 210)

# @skinlab {"type":"integer","label":"Spinning outline brightness","group":"Look","min":0,"max":255,"step":5}
VECTOR_TRACE_ALPHA = 200

# @skinlab {"type":"integer","label":"Shape sides","group":"Layout","min":3,"max":12,"step":1}
VECTOR_SIDES = 6

# @skinlab {"type":"integer","label":"Ray spacing","group":"Layout","min":1,"max":10,"step":1}
VECTOR_RAY_SPACING = 3

# @skinlab {"type":"number","label":"Shape radius","group":"Shape","min":0.1,"max":0.34,"step":0.01}
VECTOR_SIZE = 0.26

# @skinlab {"type":"number","label":"Shape height","group":"Shape","min":0.4,"max":0.78,"step":0.01}
VECTOR_CENTRE_Y = 0.66

# @skinlab {"type":"number","label":"Vanishing point","group":"Shape","min":0.05,"max":0.42,"step":0.01}
VECTOR_HORIZON = 0.30

# @skinlab {"type":"number","label":"Pulse depth","group":"Motion","min":0,"max":0.4,"step":0.01}
VECTOR_PULSE = 0.14

# The spin is in TURNS PER CYCLE, not radians per cycle. It used to be
# radians -- 0.6 of one -- so the hull rotated 34 degrees over four seconds
# and then snapped back to where it started, every four seconds, forever. A
# whole (or half) turn lands the polygon on itself, which is what `t` wrapping
# requires.
# @skinlab {"type":"number","label":"Hull spin (turns)","group":"Motion","min":-3,"max":3,"step":0.5}
VECTOR_SPIN = 1.0

# @skinlab {"type":"integer","label":"Core sides","group":"Layout","min":3,"max":8,"step":1}
VECTOR_INNER_SIDES = 3

# @skinlab {"type":"number","label":"Core spin (turns)","group":"Motion","min":-3,"max":3,"step":0.5}
VECTOR_INNER_SPIN = -1.0

# @skinlab {"type":"number","label":"Core size","group":"Shape","min":0.15,"max":0.8,"step":0.01}
VECTOR_CORE = 0.45

# @skinlab {"type":"integer","label":"Rock sides","group":"Layout","min":3,"max":7,"step":1}
VECTOR_ROCK_SIDES = 3

# @skinlab {"type":"number","label":"Rock drift","group":"Motion","min":0.25,"max":4,"step":0.25}
VECTOR_ROCK_SPEED = 1.0

# @skinlab {"type":"number","label":"Rock tumble (turns)","group":"Motion","min":-3,"max":3,"step":0.5}
VECTOR_ROCK_SPIN = 1.0

# @skinlab {"type":"number","label":"Rock height","group":"Layout","min":0.05,"max":0.3,"step":0.01}
VECTOR_ROCK_Y = 0.15

# @skinlab {"type":"number","label":"Shots per cycle","group":"Motion","min":0.25,"max":6,"step":0.25}
VECTOR_SHOT_SPEED = 2.0

# @skinlab {"type":"number","label":"Shot lean","group":"Shape","min":0,"max":1.2,"step":0.05}
VECTOR_SHOT_LEAN = 0.55


def _vector(buf):
    """Wireframe arcade: outlines only, phosphor green, hard black."""
    w, h, u = buf.width, buf.height, _unit(buf)
    buf.pen = color.rgb(*VECTOR_VOID)
    buf.clear()
    buf.pen = color.rgb(*VECTOR_WIRE)
    cx, cy = w // 2, int(h * VECTOR_CENTRE_Y)
    size = int(h * VECTOR_SIZE)
    points = []
    for i in range(VECTOR_SIDES):
        a = 2 * math.pi * i / VECTOR_SIDES
        points.append((int(cx + math.cos(a) * size), int(cy + math.sin(a) * size)))
    s = _stroke(buf)
    for i in range(VECTOR_SIDES):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % VECTOR_SIDES]
        _thick_line(buf, x1, y1, x2, y2, s)
        _thick_line(buf, cx, cy, x1, y1, s)
    buf.pen = color.rgb(*VECTOR_RAYS)
    for i in range(0, w, max(4, u * VECTOR_RAY_SPACING)):
        _thick_line(buf, i, h, cx, int(h * VECTOR_HORIZON), s)


def _vector_anim(dst, t):
    """A vector monitor with something actually happening on it.

    The tube is a beam rather than a raster: nothing is filled, everything is
    an outline, and the corners are the bright parts because the beam dwells
    there while it turns. So the hull spins with a bloom at every vertex, a
    core counter-rotates inside it, a rock tumbles across the sky above the
    vanishing point, and a shot leaves the horizon and comes at the wearer
    down the tunnel `render` already laid out.

    Every stroke goes through `_thick_line(..., _stroke(dst))`. Bare `line()`
    has no width and cost THIS skin the largest luminance loss in the whole
    catalogue at HIRES, so the honest price is that the segment count doubles
    there: 20 calls at LORES is 33 at HIRES, and that is the number the budget
    has to clear.
    """
    w, h, u = dst.width, dst.height, _unit(dst)
    s = _stroke(dst)
    cx, cy = w // 2, int(h * VECTOR_CENTRE_Y)
    size = int(h * VECTOR_SIZE * (0.9 + VECTOR_PULSE * math.sin(t * 2 * math.pi)))
    spin = t * VECTOR_SPIN * 2 * math.pi
    hull = []
    for i in range(VECTOR_SIDES):
        a = 2 * math.pi * i / VECTOR_SIDES + spin
        hull.append((int(cx + math.cos(a) * size), int(cy + math.sin(a) * size)))
    dst.pen = color.rgb(VECTOR_TRACE[0], VECTOR_TRACE[1], VECTOR_TRACE[2], VECTOR_TRACE_ALPHA)
    for i in range(VECTOR_SIDES):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % VECTOR_SIDES]
        _thick_line(dst, x1, y1, x2, y2, s)
    for x1, y1 in hull:
        dst.circle(x1, y1, max(1, s * 2))
    core = max(2, int(size * VECTOR_CORE))
    twist = t * VECTOR_INNER_SPIN * 2 * math.pi
    for i in range(VECTOR_INNER_SIDES):
        a = 2 * math.pi * i / VECTOR_INNER_SIDES + twist
        b = 2 * math.pi * (i + 1) / VECTOR_INNER_SIDES + twist
        _thick_line(dst, int(cx + math.cos(a) * core), int(cy + math.sin(a) * core),
                    int(cx + math.cos(b) * core), int(cy + math.sin(b) * core), s)
    rr = max(2, u * 2)
    rx = int(-rr * 2 + (w + rr * 4) * ((t * VECTOR_ROCK_SPEED) % 1.0))
    ry = int(h * VECTOR_ROCK_Y)
    tumble = t * VECTOR_ROCK_SPIN * 2 * math.pi
    dst.pen = color.rgb(*VECTOR_WIRE)
    for i in range(VECTOR_ROCK_SIDES):
        a = 2 * math.pi * i / VECTOR_ROCK_SIDES + tumble
        b = 2 * math.pi * (i + 1) / VECTOR_ROCK_SIDES + tumble
        _thick_line(dst, int(rx + math.cos(a) * rr), int(ry + math.sin(a) * rr),
                    int(rx + math.cos(b) * rr), int(ry + math.sin(b) * rr), s)
    k = (t * VECTOR_SHOT_SPEED) % 1.0
    lean = VECTOR_SHOT_LEAN if int(t * VECTOR_SHOT_SPEED) % 2 == 0 else -VECTOR_SHOT_LEAN
    sy = int(h * VECTOR_HORIZON)
    hx = cx + int(w * lean * k * k / 2)
    hy = sy + int((h - sy) * k * k)
    dst.pen = color.rgb(*VECTOR_TRACE)
    _thick_line(dst, cx, sy, hx, hy, s)
    # The head GROWS as it comes: a bare dot is lost among forty perspective
    # rays the same colour, and a thing getting bigger is the only depth cue a
    # wireframe has.
    dst.circle(hx, hy, max(1, s * 2 + int(u * k)))


# @skinlab {"type":"color","label":"Backdrop","group":"Palette"}
PLASMA_VOID = (20, 0, 40)

# @skinlab {"type":"color","label":"Blob one","group":"Palette"}
PLASMA_TINT_A = (255, 60, 160)

# @skinlab {"type":"color","label":"Blob two","group":"Palette"}
PLASMA_TINT_B = (80, 60, 255)

# @skinlab {"type":"color","label":"Blob three","group":"Palette"}
PLASMA_TINT_C = (60, 230, 255)

# @skinlab {"type":"color","label":"Blob four","group":"Palette"}
PLASMA_TINT_D = (255, 200, 60)

# @skinlab {"type":"color","label":"Highlight","group":"Palette"}
PLASMA_HIGHLIGHT = (255, 255, 255)

# @skinlab {"type":"integer","label":"Blob opacity","group":"Look","min":0,"max":120,"step":5}
PLASMA_BLOB_ALPHA = 60

# @skinlab {"type":"integer","label":"Highlight strength","group":"Look","min":0,"max":90,"step":2}
PLASMA_HIGHLIGHT_ALPHA = 34

# @skinlab {"type":"integer","label":"Blob count","group":"Layout","min":4,"max":40,"step":1}
PLASMA_BLOBS = 22

# @skinlab {"type":"number","label":"Blob size","group":"Shape","min":0.05,"max":0.5,"step":0.01}
PLASMA_BLOB_SIZE = 0.22

# @skinlab {"type":"number","label":"Horizontal spread","group":"Shape","min":0.05,"max":0.6,"step":0.01}
PLASMA_SPREAD_X = 0.36

# @skinlab {"type":"number","label":"Vertical spread","group":"Shape","min":0.05,"max":0.6,"step":0.01}
PLASMA_SPREAD_Y = 0.40

# @skinlab {"type":"number","label":"Highlight orbit","group":"Shape","min":0.05,"max":0.5,"step":0.01}
PLASMA_ORBIT = 0.30

# @skinlab {"type":"number","label":"Drift speed","group":"Motion","min":0.25,"max":4,"step":0.25}
PLASMA_DRIFT_SPEED = 1.0

# @skinlab {"type":"integer","label":"Moving cells","group":"Layout","min":0,"max":30,"step":1}
PLASMA_CELLS = 18

# @skinlab {"type":"number","label":"Cell size","group":"Shape","min":0.03,"max":0.18,"step":0.01}
PLASMA_CELL_SIZE = 0.07

# @skinlab {"type":"integer","label":"Cell opacity","group":"Look","min":0,"max":120,"step":2}
PLASMA_CELL_ALPHA = 46

# @skinlab {"type":"number","label":"Cell swim","group":"Motion","min":0,"max":0.5,"step":0.01}
PLASMA_WOBBLE = 0.30


def _plasma(buf):
    """Demoscene plasma, faked with overlapping translucent discs."""
    w, h, u = buf.width, buf.height, _unit(buf)
    buf.pen = color.rgb(*PLASMA_VOID)
    buf.clear()
    tints = (PLASMA_TINT_A, PLASMA_TINT_B, PLASMA_TINT_C, PLASMA_TINT_D)
    for i in range(PLASMA_BLOBS):
        a = i * 0.9
        x = int(w * 0.5 + math.cos(a) * w * PLASMA_SPREAD_X * math.sin(i * 0.4))
        y = int(h * 0.5 + math.sin(a * 1.3) * h * PLASMA_SPREAD_Y)
        tint = tints[i % len(tints)]
        buf.pen = color.rgb(tint[0], tint[1], tint[2], PLASMA_BLOB_ALPHA)
        buf.circle(x, y, int(h * PLASMA_BLOB_SIZE))


def _plasma_anim(dst, t):
    """The field boiling, not four highlights sliding across a painting.

    Real plasma is a sum of sine fields evaluated at every pixel and a badge
    cannot afford per-pixel Python, so the catalogue fakes it with overlapping
    translucent discs. `render` holds the low-frequency layer; this is the one
    that moves. Each cell sits on a hashed home -- primes 17 and 11 over
    different extents -- and swims around it, with radius and opacity riding
    their own harmonics, so no two cells are in step. Eighteen small discs
    cost about the same filled area as the four big ones they replace, which
    is the budget that actually binds.

    Every phase term is an INTEGER multiple of the cycle, so the field lands
    exactly where it started at t = 1. The old highlight used sin(a * 1.2) and
    did not: it snapped once every four seconds.
    """
    w, h = dst.width, dst.height
    ph = t * PLASMA_DRIFT_SPEED * 2 * math.pi
    tints = (PLASMA_TINT_A, PLASMA_TINT_B, PLASMA_TINT_C, PLASMA_TINT_D)
    base = max(2, int(h * PLASMA_CELL_SIZE))
    swim = PLASMA_WOBBLE * 0.5
    for i in range(PLASMA_CELLS):
        hx = ((i * 17) % 20) / 20.0
        hy = ((i * 11) % 16) / 16.0
        tint = tints[i % len(tints)]
        a = PLASMA_CELL_ALPHA + int(PLASMA_CELL_ALPHA * 0.5
                                    * math.sin(ph * 2 + i * 1.31))
        dst.pen = color.rgb(tint[0], tint[1], tint[2], max(0, min(255, a)))
        dst.circle(int(w * (0.06 + 0.88 * hx) + w * swim * math.cos(ph + i * 0.83)),
                   int(h * (0.06 + 0.88 * hy) + h * swim * math.sin(ph * 2 + i * 1.31)),
                   max(1, base + int(base * 0.4 * math.sin(ph * 3 + i * 2.11))))
    for i in range(4):
        a = ph + i * 1.5708
        dst.pen = color.rgb(PLASMA_HIGHLIGHT[0], PLASMA_HIGHLIGHT[1], PLASMA_HIGHLIGHT[2],
                            PLASMA_HIGHLIGHT_ALPHA)
        dst.circle(int(w * 0.5 + math.cos(a) * w * PLASMA_ORBIT),
                   int(h * 0.5 + math.sin(a * 2) * h * PLASMA_ORBIT),
                   max(2, int(h * 0.09)))


# @skinlab {"type":"color","label":"Sky top","group":"Palette"}
AURORA_SKY_TOP = (4, 6, 26)

# @skinlab {"type":"color","label":"Sky base","group":"Palette"}
AURORA_SKY_BOTTOM = (12, 4, 32)

# @skinlab {"type":"color","label":"Stars","group":"Palette"}
AURORA_STAR = (255, 255, 255)

# @skinlab {"type":"integer","label":"Star count","group":"Layout","min":0,"max":120,"step":5}
AURORA_STARS = 50

# @skinlab {"type":"color","label":"Curtain","group":"Palette"}
AURORA_CURTAIN = (60, 230, 150)

# @skinlab {"type":"integer","label":"Curtains","group":"Layout","min":2,"max":12,"step":1}
AURORA_CURTAINS = 7

# @skinlab {"type":"integer","label":"Folds per curtain","group":"Layout","min":1,"max":6,"step":1}
AURORA_FOLDS = 4

# @skinlab {"type":"integer","label":"Curtain glow","group":"Look","min":12,"max":120,"step":2}
AURORA_CURTAIN_ALPHA = 46

# @skinlab {"type":"color","label":"Ground","group":"Palette"}
AURORA_GROUND = (6, 10, 20)

# @skinlab {"type":"number","label":"Horizon","group":"Layout","min":0.62,"max":0.96,"step":0.01}
AURORA_HORIZON = 0.86

# @skinlab {"type":"color","label":"Shimmer","group":"Palette"}
AURORA_SWEEP = (160, 255, 200)

# @skinlab {"type":"integer","label":"Shimmer folds","group":"Layout","min":0,"max":22,"step":1}
AURORA_SWEEPS = 16

# Whole turns of the 4 s cycle. A fractional rate would put `sin` somewhere
# other than where it started when `t` wraps 1 -> 0, which is a visible snap.
# @skinlab {"type":"integer","label":"Fold drift","group":"Motion","min":1,"max":4,"step":1}
AURORA_SWEEP_SPEED = 1

# @skinlab {"type":"number","label":"Fold sway","group":"Motion","min":0.0,"max":0.3,"step":0.01}
AURORA_SWAY = 0.09

# @skinlab {"type":"integer","label":"Fold breath","group":"Motion","min":1,"max":6,"step":1}
AURORA_BREATH = 2

# @skinlab {"type":"integer","label":"Twinkling stars","group":"Layout","min":0,"max":18,"step":1}
AURORA_TWINKLES = 11

# @skinlab {"type":"integer","label":"Twinkle speed","group":"Motion","min":1,"max":8,"step":1}
AURORA_TWINKLE_SPEED = 3

# @skinlab {"type":"integer","label":"Snow glow bars","group":"Layout","min":0,"max":8,"step":1}
AURORA_GLOW_BARS = 4

# @skinlab {"type":"integer","label":"Snow glow pulse","group":"Motion","min":1,"max":4,"step":1}
AURORA_GLOW_SPEED = 1


def _aurora(buf):
    """Curtains over a cold sky."""
    w, h, u = buf.width, buf.height, _unit(buf)
    _vertical(buf, AURORA_SKY_TOP, AURORA_SKY_BOTTOM)
    for i in range(AURORA_STARS):
        buf.pen = color.rgb(AURORA_STAR[0], AURORA_STAR[1], AURORA_STAR[2],
                            90 + (i % 3) * 60)
        buf.rectangle((i * 71) % w, (i * 43) % max(1, int(h * 0.7)), 1, 1)
    for i in range(AURORA_CURTAINS):
        x = int(w * (0.05 + i * 0.15))
        for band in range(AURORA_FOLDS):
            tint = (AURORA_CURTAIN[0] + band * 30, AURORA_CURTAIN[1] - band * 20,
                    AURORA_CURTAIN[2] + band * 20)
            buf.pen = color.rgb(tint[0], tint[1], tint[2], AURORA_CURTAIN_ALPHA)
            buf.triangle(x + band * u, 0, x + u * 3 + band * u, 0,
                         x - u * 4 + band * u * 2, int(h * (0.62 + band * 0.08)))
    buf.pen = color.rgb(*AURORA_GROUND)
    buf.rectangle(0, int(h * AURORA_HORIZON), w, h)


def _aurora_anim(dst, t):
    """The whole curtain lives: every fold sways on its own beat, brightens
    and dies away, the stars behind it twinkle, and the snow catches it."""
    w, h, u = dst.width, dst.height, _unit(dst)
    s = _stroke(dst)
    ang = t * 6.283185
    for i in range(AURORA_SWEEPS):
        lit = math.sin(ang * AURORA_BREATH + i * 1.7)
        if lit <= -0.15:
            continue
        sway = math.sin(ang * AURORA_SWEEP_SPEED + i * 0.9)
        x = int(w * (0.02 + ((i * 97) % 100) * 0.0096) + sway * w * AURORA_SWAY)
        reach = 0.44 + ((i * 37) % 7) * 0.05
        top = u + ((i * 53) % 3) * (u // 2)
        dst.pen = color.rgb(AURORA_SWEEP[0], AURORA_SWEEP[1], AURORA_SWEEP[2],
                            int(24 + 66 * (lit + 0.15)))
        dst.triangle(x, 0, x + top, 0, x - u * 3 + int(sway * u * 5), int(h * reach))
    for i in range(AURORA_TWINKLES):
        b = math.sin(ang * AURORA_TWINKLE_SPEED + i * 2.1)
        if b < 0.0:
            continue
        dst.pen = color.rgb(255, 255, 255, int(50 + 200 * b))
        dst.rectangle((i * 149) % w, (i * 83) % max(1, int(h * 0.5)), s, s)
    gy = int(h * AURORA_HORIZON)
    for i in range(AURORA_GLOW_BARS):
        pulse = 0.5 + 0.5 * math.sin(ang * AURORA_GLOW_SPEED + i * 1.3)
        bx = int(w * (0.03 + i * 0.24) + math.sin(ang + i) * w * 0.02)
        dst.pen = color.rgb(AURORA_SWEEP[0], AURORA_SWEEP[1], AURORA_SWEEP[2],
                            int(34 + 66 * pulse))
        dst.rectangle(bx, gy + (i % 2) * max(1, u // 2),
                      int(w * (0.13 + 0.19 * pulse)), max(1, u // 2))


# @skinlab {"type":"color","label":"Paper","group":"Palette"}
RISO_PAPER = (244, 238, 222)

# @skinlab {"type":"color","label":"Pink ink","group":"Palette"}
RISO_PINK = (255, 80, 140)

# @skinlab {"type":"color","label":"Blue ink","group":"Palette"}
RISO_BLUE = (40, 120, 240)

# @skinlab {"type":"color","label":"Rule ink","group":"Palette"}
RISO_RULE = (20, 20, 24)

# The overprint IS the skin, so both ink densities are controls rather than
# compositing constants.
# @skinlab {"type":"integer","label":"Pink density","group":"Look","min":70,"max":255,"step":5}
RISO_PINK_DENSITY = 190

# @skinlab {"type":"integer","label":"Blue density","group":"Look","min":70,"max":255,"step":5}
RISO_BLUE_DENSITY = 170

# @skinlab {"type":"number","label":"Pink across","group":"Layout","min":0.1,"max":0.7,"step":0.02}
RISO_PINK_X = 0.38

# @skinlab {"type":"number","label":"Pink down","group":"Layout","min":0.2,"max":0.8,"step":0.02}
RISO_PINK_Y = 0.46

# @skinlab {"type":"number","label":"Pink size","group":"Shape","min":0.15,"max":0.6,"step":0.02}
RISO_PINK_R = 0.40

# @skinlab {"type":"number","label":"Blue across","group":"Layout","min":0.3,"max":0.9,"step":0.02}
RISO_BLUE_X = 0.60

# @skinlab {"type":"number","label":"Blue down","group":"Layout","min":0.2,"max":0.8,"step":0.02}
RISO_BLUE_Y = 0.58

# @skinlab {"type":"number","label":"Blue size","group":"Shape","min":0.15,"max":0.6,"step":0.02}
RISO_BLUE_R = 0.36

# @skinlab {"type":"number","label":"Long rule","group":"Layout","min":0.2,"max":0.9,"step":0.02}
RISO_RULE_LONG = 0.84

# @skinlab {"type":"number","label":"Short rule","group":"Layout","min":0.1,"max":0.9,"step":0.02}
RISO_RULE_SHORT = 0.46


def _riso(buf):
    """Two-colour overprint, slightly out of register."""
    w, h, u = buf.width, buf.height, _unit(buf)
    buf.pen = color.rgb(*RISO_PAPER)
    buf.clear()
    buf.pen = color.rgb(RISO_PINK[0], RISO_PINK[1], RISO_PINK[2], RISO_PINK_DENSITY)
    buf.circle(int(w * RISO_PINK_X), int(h * RISO_PINK_Y), int(h * RISO_PINK_R))
    buf.pen = color.rgb(RISO_BLUE[0], RISO_BLUE[1], RISO_BLUE[2], RISO_BLUE_DENSITY)
    buf.circle(int(w * RISO_BLUE_X), int(h * RISO_BLUE_Y), int(h * RISO_BLUE_R))
    buf.pen = color.rgb(*RISO_RULE)
    buf.rectangle(int(w * 0.08), int(h * 0.84), int(w * RISO_RULE_LONG),
                  max(1, u // 2))
    buf.rectangle(int(w * 0.08), int(h * 0.88), int(w * RISO_RULE_SHORT),
                  max(1, u // 2))


# @skinlab {"type":"color","label":"Ink","group":"Palette"}
DIAG_INK = (24, 26, 34)

# @skinlab {"type":"color","label":"First stripe","group":"Palette"}
DIAG_STRIPE_A = (255, 210, 60)

# @skinlab {"type":"color","label":"Second stripe","group":"Palette"}
DIAG_STRIPE_B = (255, 90, 110)

# @skinlab {"type":"color","label":"Third stripe","group":"Palette"}
DIAG_STRIPE_C = (60, 200, 220)

# @skinlab {"type":"color","label":"Disc","group":"Palette"}
DIAG_DISC = (244, 244, 248)

# @skinlab {"type":"integer","label":"Stripe width","group":"Shape","min":2,"max":10,"step":1}
DIAG_BAND = 4

# @skinlab {"type":"number","label":"Disc across","group":"Layout","min":0.2,"max":0.95,"step":0.02}
DIAG_DISC_X = 0.72

# @skinlab {"type":"number","label":"Disc down","group":"Layout","min":0.2,"max":0.95,"step":0.02}
DIAG_DISC_Y = 0.66

# @skinlab {"type":"number","label":"Disc size","group":"Shape","min":0.12,"max":0.42,"step":0.02}
DIAG_DISC_R = 0.26

# @skinlab {"type":"number","label":"Disc core","group":"Shape","min":0.04,"max":0.36,"step":0.02}
DIAG_CORE_R = 0.20

# Stripes on the bias are a barber pole, and a barber pole's whole trick is
# that the pattern travels while the object does not. Repainting the field
# every frame would cost a screen and a half of fill, so what travels is a
# specular sliver riding each stripe: the glints are spaced exactly as far
# apart as they move in one cycle, which is what makes t = 1 land on t = 0 with
# nothing to see. 2 is one stripe pitch: every stripe gets a glint and each
# one travels a whole stripe per cycle. Larger values thin the field out.
# @skinlab {"type":"integer","label":"Glint spacing","group":"Layout","min":2,"max":10,"step":1}
DIAG_GLINT_STEP = 2

# @skinlab {"type":"number","label":"Glint width","group":"Shape","min":0.1,"max":1,"step":0.02}
DIAG_GLINT_W = 0.22

# Opaque, and narrow. A translucent sliver was tried first: over the ink gaps
# it made grey bars, which is the flat-plate failure the colour chapter warns
# about, not a highlight.
# @skinlab {"type":"integer","label":"Glint strength","group":"Look","min":0,"max":255,"step":5}
DIAG_GLINT_ALPHA = 255

# @skinlab {"type":"number","label":"Glint speed","group":"Motion","min":0.25,"max":4,"step":0.25}
DIAG_GLINT_SPEED = 1.0


def _diagonal(buf):
    """Bold stripes on the bias, with one shape crashing through."""
    w, h, u = buf.width, buf.height, _unit(buf)
    buf.pen = color.rgb(*DIAG_INK)
    buf.clear()
    tints = (DIAG_STRIPE_A, DIAG_STRIPE_B, DIAG_STRIPE_C)
    band = max(3, u * DIAG_BAND)
    i = 0
    for x in range(-h, w + h, band * 2):
        tint = tints[i % len(tints)]
        buf.pen = color.rgb(tint[0], tint[1], tint[2])
        buf.triangle(x, 0, x + band, 0, x - h + band, h)
        buf.triangle(x + band, 0, x - h + band, h, x - h + band * 2, h)
        i += 1
    buf.pen = color.rgb(*DIAG_INK)
    buf.circle(int(w * DIAG_DISC_X), int(h * DIAG_DISC_Y), int(h * DIAG_DISC_R))
    buf.pen = color.rgb(*DIAG_DISC)
    buf.circle(int(w * DIAG_DISC_X), int(h * DIAG_DISC_Y), int(h * DIAG_CORE_R))


def _diagonal_a(dst, t):
    """Light running down the bias: the pattern moves, the poster does not."""
    w, h, u = dst.width, dst.height, _unit(dst)
    band = max(3, u * DIAG_BAND)
    gap = band * DIAG_GLINT_STEP
    g = max(1, int(band * DIAG_GLINT_W))
    slide = int(gap * ((t * DIAG_GLINT_SPEED) % 1.0))
    dst.pen = color.rgb(DIAG_DISC[0], DIAG_DISC[1], DIAG_DISC[2],
                        DIAG_GLINT_ALPHA)
    for x in range(-h - gap + slide, w + h, gap):
        # The sliver shears exactly as the stripe under it does, so it reads as
        # the stripe catching the light rather than as a bar crossing it.
        if x + g <= 0 or x - h + g >= w:
            continue
        dst.triangle(x, 0, x + g, 0, x - h + g, h)
        dst.triangle(x + g, 0, x - h + g, h, x - h + g * 2, h)


# @skinlab {"type":"color","label":"Night sky","group":"Palette"}
RAIN_NIGHT_TOP = (6, 8, 22)

# @skinlab {"type":"color","label":"Night street","group":"Palette"}
RAIN_NIGHT_BOTTOM = (30, 14, 46)

# @skinlab {"type":"color","label":"Hot pink sign","group":"Palette"}
RAIN_SIGN_HOT = (255, 60, 120)

# @skinlab {"type":"color","label":"Ice blue sign","group":"Palette"}
RAIN_SIGN_ICE = (60, 230, 255)

# @skinlab {"type":"color","label":"Amber sign","group":"Palette"}
RAIN_SIGN_AMBER = (255, 200, 60)

# @skinlab {"type":"color","label":"Violet sign","group":"Palette"}
RAIN_SIGN_VIOLET = (150, 90, 255)

# @skinlab {"type":"color","label":"Drizzle","group":"Palette"}
RAIN_DROP = (180, 220, 255)

# @skinlab {"type":"color","label":"Falling streak","group":"Palette"}
RAIN_STREAK = (200, 235, 255)

# @skinlab {"type":"integer","label":"Drizzle density","group":"Layout","min":0,"max":110,"step":1}
RAIN_DRIZZLE = 40

# @skinlab {"type":"integer","label":"Falling drops","group":"Layout","min":1,"max":24,"step":1}
RAIN_DROPS = 18

# @skinlab {"type":"integer","label":"Splashes","group":"Layout","min":0,"max":8,"step":1}
RAIN_SPLASHES = 4

# @skinlab {"type":"integer","label":"Puddle reflections","group":"Layout","min":0,"max":4,"step":1}
RAIN_PUDDLES = 3

# @skinlab {"type":"integer","label":"Flickering signs","group":"Layout","min":0,"max":4,"step":1}
RAIN_FLICKERS = 2

# @skinlab {"type":"integer","label":"Flicker rate","group":"Motion","min":2,"max":40,"step":1}
RAIN_FLICKER_RATE = 14

# Where the four signs hang, as fractions of the canvas. Shared by the render
# and the animator on purpose: the flicker and the puddle reflections have to
# land on the SIGNS, so one table is the only way they cannot drift apart.
RAIN_SIGNS = ((0.08, 0.20), (0.62, 0.14), (0.34, 0.34), (0.74, 0.44))

# @skinlab {"type":"integer","label":"Drop length","group":"Shape","min":1,"max":8,"step":1}
RAIN_DROP_LEN = 3

# @skinlab {"type":"integer","label":"Drop lean","group":"Shape","min":0,"max":6,"step":1}
RAIN_LEAN = 1

# A whole number of falls per loop, or the rain teleports at the wrap.
# @skinlab {"type":"integer","label":"Falls per loop","group":"Motion","min":1,"max":6,"step":1}
RAIN_FALL_SPEED = 2

# @skinlab {"type":"number","label":"Drop stagger","group":"Motion","min":0.02,"max":0.2,"step":0.01}
RAIN_STAGGER = 0.07


def _rain(buf):
    """Wet neon, somewhere with bad weather and good signage."""
    w, h, u = buf.width, buf.height, _unit(buf)
    _vertical(buf, RAIN_NIGHT_TOP, RAIN_NIGHT_BOTTOM)
    tints = (RAIN_SIGN_HOT, RAIN_SIGN_ICE, RAIN_SIGN_AMBER, RAIN_SIGN_VIOLET)
    for i in range(len(RAIN_SIGNS)):
        fx, fy = RAIN_SIGNS[i]
        tint = tints[i]
        buf.pen = color.rgb(tint[0], tint[1], tint[2], 70)
        buf.rectangle(int(w * fx) - u, int(h * fy) - u, u * 10, u * 5)
        buf.pen = color.rgb(tint[0], tint[1], tint[2])
        buf.rectangle(int(w * fx), int(h * fy), u * 8, u * 3)
        buf.pen = color.rgb(*RAIN_NIGHT_TOP)
        buf.rectangle(int(w * fx) + u, int(h * fy) + u, u * 6, max(1, u))
    buf.pen = color.rgb(RAIN_DROP[0], RAIN_DROP[1], RAIN_DROP[2], 60)
    for i in range(RAIN_DRIZZLE):
        x = (i * 47) % w
        y = (i * 31) % h
        buf.line(x, y, x - u * RAIN_LEAN, y + u * RAIN_DROP_LEN)


def _rain_anim(dst, t):
    """Rain that lands, on a street that answers it.

    Streaks are bare `line()` -- thinness is the effect and the catalogue
    keeps hairlines here deliberately -- so eighteen of them cost eighteen
    calls and almost no filled area.  What was missing was everything the
    rain hits: splashes opening on the wet road, the sign colours smeared
    across the puddles, and two of the four signs dropping out and striking
    again, which is the one thing neon reliably does at night.
    """
    w, h, u = dst.width, dst.height, _unit(dst)
    s = _stroke(dst)
    tints = (RAIN_SIGN_HOT, RAIN_SIGN_ICE, RAIN_SIGN_AMBER, RAIN_SIGN_VIOLET)
    k = int(t * RAIN_FLICKER_RATE)
    for i in range(RAIN_FLICKERS):
        fx, fy = RAIN_SIGNS[i]
        tint = tints[i]
        if (k * 7 + i * 5) % 9 > 2:
            dst.pen = color.rgb(tint[0], tint[1], tint[2], 90)
            dst.rectangle(int(w * fx) - u, int(h * fy) - u, u * 10, u * 5)
            dst.pen = color.rgb(tint[0], tint[1], tint[2])
        else:
            dst.pen = color.rgb(tint[0] // 4, tint[1] // 4, tint[2] // 4)
        dst.rectangle(int(w * fx), int(h * fy), u * 8, u * 3)
    for i in range(RAIN_PUDDLES):
        tint = tints[i]
        q = abs(2.0 * ((t * 2 + i * 0.3) % 1.0) - 1.0)
        dst.pen = color.rgb(tint[0], tint[1], tint[2], 105)
        dst.rectangle(int(w * RAIN_SIGNS[i][0]) + int(u * (q - 0.5) * 3),
                      int(h * (0.87 + i * 0.04)), u * 8, max(1, s * 2))
    for i in range(RAIN_DROPS):
        phase = (t * RAIN_FALL_SPEED + i * RAIN_STAGGER) % 1.0
        x = (i * 89) % w
        y = int(h * phase)
        dst.pen = color.rgb(RAIN_STREAK[0], RAIN_STREAK[1], RAIN_STREAK[2], 190)
        dst.line(x, y, x - u * RAIN_LEAN, y + u * RAIN_DROP_LEN)
    for i in range(RAIN_SPLASHES):
        p = (t * RAIN_FALL_SPEED + i * 0.23) % 1.0
        g = max(1, int(u * (0.4 + 2.4 * p)))
        dst.pen = color.rgb(RAIN_DROP[0], RAIN_DROP[1], RAIN_DROP[2], int(210 * (1.0 - p)))
        dst.rectangle((i * 137 + 21) % w - g, int(h * (0.90 + i * 0.025)), g * 2, max(1, s))


# @skinlab {"type":"color","label":"Backdrop","group":"Palette"}
HEX_BACKDROP = (6, 14, 24)

# @skinlab {"type":"color","label":"Pulse ring","group":"Palette"}
HEX_PULSE = (120, 255, 255)

# @skinlab {"type":"integer","label":"Cell warmth","group":"Palette","min":0,"max":255,"step":5}
HEX_CELL_RED = 0

# @skinlab {"type":"integer","label":"Cell blue floor","group":"Palette","min":0,"max":255,"step":5}
HEX_CELL_BLUE_FLOOR = 60

# @skinlab {"type":"integer","label":"Cell strength","group":"Look","min":60,"max":255,"step":5}
HEX_CELL_ALPHA = 170

# @skinlab {"type":"integer","label":"Cell size","group":"Layout","min":3,"max":8,"step":1}
HEX_STEP = 4

# The falloff coefficient below is a distance in PIXELS. Keep it an integer and
# keep the `// _stroke(buf) or 1` divisor: exposing a bare constant instead is
# the regression this comment exists to prevent.
# @skinlab {"type":"integer","label":"Glow falloff","group":"Look","min":1,"max":8,"step":1}
HEX_FALLOFF = 2

# @skinlab {"type":"integer","label":"Core brightness","group":"Look","min":120,"max":255,"step":5}
HEX_LEVEL_MAX = 220

# @skinlab {"type":"integer","label":"Edge brightness","group":"Look","min":0,"max":120,"step":5}
HEX_LEVEL_MIN = 30

# @skinlab {"type":"integer","label":"Live cells","group":"Layout","min":4,"max":18,"step":1}
HEX_FLARES = 12

# @skinlab {"type":"integer","label":"Charge waves per loop","group":"Motion","min":1,"max":5,"step":1}
HEX_WAVE_SPEED = 2

# @skinlab {"type":"number","label":"Wave spread","group":"Motion","min":0.2,"max":3,"step":0.1}
HEX_WAVE_SPREAD = 1.6

# @skinlab {"type":"integer","label":"Pulse strength","group":"Look","min":0,"max":255,"step":5}
HEX_PULSE_ALPHA = 165


def _hexfield(buf):
    """An energy field, tiled."""
    w, h, u = buf.width, buf.height, _unit(buf)
    buf.pen = color.rgb(*HEX_BACKDROP)
    buf.clear()
    step = max(5, u * HEX_STEP)
    # The falloff is a distance in PIXELS, so a literal coefficient makes the
    # glow twice as tight on a canvas with twice the pixels: measured, HIRES
    # came out 5.25/255 darker overall and the lit centre shrank to a quarter
    # of its area. Divide by the physical stroke so the falloff is a distance
    # in millimetres and LORES is untouched. HEX_FALLOFF is that coefficient;
    # the division must stay here, in the skin, where the buffer is known.
    fade = HEX_FALLOFF // _stroke(buf) or 1
    row = 0
    for y in range(-step, h + step, step):
        for x in range(-step, w + step, step * 2):
            cx = x + (step if row % 2 else 0)
            far = abs(cx - w // 2) + abs(y - h // 2)
            level = max(HEX_LEVEL_MIN, HEX_LEVEL_MAX - far * fade)
            buf.pen = color.rgb(HEX_CELL_RED, level, max(HEX_CELL_BLUE_FLOOR, level), HEX_CELL_ALPHA)
            buf.triangle(cx, y, cx + step // 2, y + step // 2, cx - step // 2, y + step // 2)
            buf.triangle(cx, y + step, cx + step // 2, y + step // 2, cx - step // 2, y + step // 2)
        row += 1


def _hexfield_anim(dst, t):
    """A charge firing outward through the lattice, cell by lit cell.

    The cells sit on the SAME lattice `_hexfield` tiles, so this reads as the
    field itself conducting rather than as marks laid over it: `step`, the
    row stagger and the half-diamond pair are all copied from the render.
    Each cell's phase is its distance from the centre, so the bright front
    travels outward; the sawtooth means a cell fires hard and decays, which
    is what a charge does and is also periodic across `t = 1 -> 0` at every
    integer `HEX_WAVE_SPEED`.
    """
    w, h, u = dst.width, dst.height, _unit(dst)
    step = max(5, u * HEX_STEP)
    cols = max(1, w // (step * 2) + 1)
    rows = max(1, h // step + 2)
    half = step // 2
    reach = float(w + h)
    for i in range(HEX_FLARES):
        row = (i * 7) % rows
        col = (i * 5) % cols
        cx = -step + col * step * 2 + (step if row % 2 else 0)
        cy = -step + row * step
        far = (abs(cx - w // 2) + abs(cy - h // 2)) / reach
        k = (t * HEX_WAVE_SPEED - far * HEX_WAVE_SPREAD) % 1.0
        level = int(HEX_PULSE_ALPHA * (1.0 - k * k))
        dst.pen = color.rgb(HEX_PULSE[0], HEX_PULSE[1], HEX_PULSE[2], level)
        dst.triangle(cx, cy, cx + half, cy + half, cx - half, cy + half)
        dst.triangle(cx, cy + step, cx + half, cy + half, cx - half, cy + half)


# @skinlab {"type":"color","label":"Sky","group":"Palette"}
FURNACE_SKY = (24, 5, 12)

# @skinlab {"type":"color","label":"Molten crest","group":"Palette"}
FURNACE_MOLTEN_CREST = (255, 220, 130)

# @skinlab {"type":"color","label":"Molten","group":"Palette"}
FURNACE_MOLTEN = (255, 140, 30)

# @skinlab {"type":"color","label":"Towers","group":"Palette"}
FURNACE_TOWER = (14, 7, 12)

# @skinlab {"type":"color","label":"Tower rim light","group":"Palette"}
FURNACE_TOWER_LIGHT = (255, 168, 58)

# @skinlab {"type":"color","label":"Progress fill","group":"Palette"}
FURNACE_FILL = (255, 150, 40)

# @skinlab {"type":"color","label":"Status lamp","group":"Palette"}
FURNACE_LED = (120, 255, 120)

# @skinlab {"type":"integer","label":"Sky band","group":"Layout","min":3,"max":24,"step":1}
FURNACE_HORIZON = 9

# @skinlab {"type":"integer","label":"Molten line","group":"Layout","min":52,"max":88,"step":1}
FURNACE_MOLTEN_Y = 74

# @skinlab {"type":"integer","label":"Glow rings","group":"Layout","min":1,"max":9,"step":1}
FURNACE_GLOW_RINGS = 6

# @skinlab {"type":"number","label":"Fill speed","group":"Motion","min":0.25,"max":4,"step":0.25}
FURNACE_FILL_SPEED = 1.0

# @skinlab {"type":"integer","label":"Embers","group":"Motion","min":0,"max":14,"step":1}
FURNACE_EMBERS = 10

# @skinlab {"type":"number","label":"Ember speed","group":"Motion","min":0.25,"max":4,"step":0.25}
FURNACE_EMBER_SPEED = 1.0

# @skinlab {"type":"number","label":"Lamp blink rate","group":"Motion","min":1,"max":12,"step":1}
FURNACE_LED_RATE = 6.0

# @skinlab {"type":"integer","label":"Molten crests","group":"Motion","min":0,"max":8,"step":1}
FURNACE_CRESTS = 4

# @skinlab {"type":"number","label":"Crest drift","group":"Motion","min":0.25,"max":3,"step":0.25}
FURNACE_CREST_SPEED = 1.0

# @skinlab {"type":"integer","label":"Torch sparks","group":"Motion","min":0,"max":6,"step":1}
FURNACE_SPARKS = 3

# @skinlab {"type":"integer","label":"Lit windows","group":"Motion","min":0,"max":6,"step":1}
FURNACE_WINDOWS = 3

# The tower skyline, shared by the background and the windows lit in it:
# (left in fortieths, width in fortieths, height in hundredths).  Hand-placed
# composition, not a knob.
FURNACE_BLOCKS = ((1, 7, 16), (9, 5, 27), (15, 6, 12), (22, 4, 31),
                  (27, 6, 18), (34, 5, 24))


def _g_build_furnace(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    for y in range(h):
        k = y * 255 // max(1, h - 1)
        kk = k * k // 255
        buf.pen = color.rgb(min(255, FURNACE_SKY[0] + kk * 231 // 255),
                            min(255, FURNACE_SKY[1] + kk * 148 // 255),
                            min(255, FURNACE_SKY[2] + kk * kk // 255 * 26 // 255))
        buf.rectangle(0, y, w, 1)
    buf.pen = color.rgb(255, 190, 70, 26)
    for i in range(FURNACE_GLOW_RINGS):
        buf.circle(w // 2, h * 108 // 100, max(3, min(w, h) * (10 - i) // 9))
    base = h * FURNACE_MOLTEN_Y // 100
    buf.pen = color.rgb(*FURNACE_MOLTEN_CREST)
    buf.rectangle(0, base, w, h - base)
    buf.pen = color.rgb(*FURNACE_MOLTEN)
    buf.rectangle(0, base + h * 5 // 100, w, h - base)
    for bl in FURNACE_BLOCKS:
        x = w * bl[0] // 40
        bw = w * bl[1] // 40 + 1
        bh = h * bl[2] // 100
        buf.pen = color.rgb(*FURNACE_TOWER)
        buf.rectangle(x, base - bh, bw, h - base + bh)
        buf.pen = color.rgb(FURNACE_TOWER_LIGHT[0], FURNACE_TOWER_LIGHT[1],
                            FURNACE_TOWER_LIGHT[2], 210)
        buf.rectangle(x, base - bh, bw, max(1, h // 80))
        buf.pen = color.rgb(255, 120, 30, 90)
        buf.rectangle(x, base - bh, max(1, u // 2), bh)
    buf.pen = color.rgb(0, 0, 0, 205)
    buf.rectangle(0, 0, w, h * FURNACE_HORIZON // 100)
    hz = h * FURNACE_HORIZON // 100
    sw = w // 5
    for i in range(6):
        x = i * sw - sw
        buf.pen = color.rgb(255, 176, 40, 190)
        buf.triangle(x, hz, x + sw // 2, hz, x + sw // 2 + hz, 0)
        buf.triangle(x, hz, x + hz, 0, x + sw // 2 + hz, 0)
    buf.pen = color.rgb(255, 200, 90, 120)
    buf.rectangle(0, hz, w, max(1, h // 120))
    pbx = w * 6 // 100
    pbw = w * 88 // 100
    pby = h * 86 // 100
    pbh = max(3, h // 14)
    buf.pen = color.rgb(0, 0, 0, 200)
    buf.rectangle(pbx - u, pby - u, pbw + u * 2, pbh + u * 2)
    buf.pen = color.rgb(52, 18, 12)
    buf.rectangle(pbx, pby, pbw, pbh)
    buf.pen = color.rgb(96, 40, 20)
    for i in range(1, 8):
        buf.rectangle(pbx + pbw * i // 8, pby, max(1, u // 2), pbh)
    buf.pen = color.rgb(255, 210, 120, 70)
    for i in range(7):
        buf.rectangle(w * (4 + i * 6) // 40, h * (20 + (i * 13) % 40) // 100,
                      max(1, u // 2), max(1, u // 2))
    buf.pen = color.rgb(0, 0, 0, 70)
    buf.rectangle(0, h * FURNACE_HORIZON // 100, u * 2, h)
    buf.rectangle(w - u * 2, h * FURNACE_HORIZON // 100, u * 2, h)


def _g_build_furnace_a(dst, t):
    """The plant is RUNNING, not just filling a bar.

    The pour crests slide along the molten line, the crucible glow breathes,
    embers lift off it, the towers throw sparks and their windows flicker, and
    the build bar fills with a hot leading edge. Everything busy lives BELOW
    the molten line at 0.74h or above the horizon at 0.09h -- the name band
    gets the slow glow and nothing else."""
    import math
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    base = h * FURNACE_MOLTEN_Y // 100

    # the pour: bright crests sliding along the molten line
    for i in range(FURNACE_CRESTS):
        laps = 1 + (i % 2)
        cp = (t * FURNACE_CREST_SPEED * laps + i * 0.23) % 1.0
        cx = int(cp * (w + u * 6)) - u * 6
        dst.pen = color.rgb(255, 240, 190, 190)
        dst.rectangle(cx, base + (i % 3) * max(1, u // 2), u * 4, max(1, u // 2))

    # the progress bar, with a hot head and a shimmer running the filled part
    pbx = w * 6 // 100
    pbw = w * 88 // 100
    pby = h * 86 // 100
    pbh = max(3, h // 14)
    fw = int(pbw * (0.06 + 0.94 * ((t * FURNACE_FILL_SPEED) % 1.0)))
    dst.pen = color.rgb(*FURNACE_FILL)
    dst.rectangle(pbx, pby, fw, pbh)
    dst.pen = color.rgb(255, 226, 130)
    dst.rectangle(pbx, pby, fw, max(1, pbh // 3))
    dst.pen = color.rgb(255, 248, 210, 150)
    dst.rectangle(pbx + int(fw * ((t * 3.0) % 1.0)), pby, max(1, u), pbh)
    dst.pen = color.rgb(255, 255, 220)
    dst.rectangle(pbx + fw - u, pby, u * 2, pbh)

    for i in range(FURNACE_EMBERS):
        p = (t * FURNACE_EMBER_SPEED * (1 + i % 3) + i * 0.17) % 1.0
        sx = w * (5 + i * 4) // 40 + int(math.sin(p * 6.2832 + i) * (w // 26))
        sy = int(h * 0.96 - p * h * 0.9)
        dst.pen = color.rgb(255, 210 - i * 12, 90, 200 - int(p * 150))
        dst.rectangle(sx, sy, max(1, u // 2), max(1, u))

    # sparks thrown off the tower tops, and windows lit behind them
    for i in range(FURNACE_SPARKS):
        bl = FURNACE_BLOCKS[(i * 2 + 1) % len(FURNACE_BLOCKS)]
        p = (t * 2.0 + i * 0.41) % 1.0
        tx = w * bl[0] // 40 + w * bl[1] // 80
        ty = base - h * bl[2] // 100
        dst.pen = color.rgb(255, 232, 170, 220 - int(p * 200))
        dst.rectangle(tx + int((p - 0.5) * u * 4), ty - int(p * h * 0.10),
                      max(1, u // 2), max(1, u))
    for i in range(FURNACE_WINDOWS):
        bl = FURNACE_BLOCKS[(i * 2) % len(FURNACE_BLOCKS)]
        on = ((t * (3.0 + i) + i * 0.29) % 1.0) < 0.55
        dst.pen = color.rgb(255, 196, 96, 235 if on else 60)
        dst.rectangle(w * bl[0] // 40 + max(1, u // 2),
                      base - h * bl[2] // 100 + u,
                      max(1, u), max(1, u))

    dst.pen = color.rgb(255, 170, 50, 40)
    dst.circle(w // 2, h * 108 // 100,
               max(3, int(min(w, h) * (0.85 + 0.12 * math.sin(t * 6.2832)))))
    if (t * FURNACE_LED_RATE) % 1.0 < 0.5:
        dst.pen = color.rgb(*FURNACE_LED)
    else:
        dst.pen = color.rgb(40, 90, 40)
    dst.rectangle(w - u * 4, h * 3 // 100, u * 2, u * 2)


# @skinlab {"type":"color","label":"Sky","group":"Palette"}
CONTAINER_SKY = (5, 16, 46)

# @skinlab {"type":"color","label":"Sea","group":"Palette"}
CONTAINER_SEA = (3, 18, 50)

# @skinlab {"type":"color","label":"Sea rays","group":"Palette"}
CONTAINER_RAY = (46, 150, 237)

# @skinlab {"type":"color","label":"Container face","group":"Palette"}
CONTAINER_BOX = (36, 150, 237)

# @skinlab {"type":"color","label":"Container top","group":"Palette"}
CONTAINER_BOX_TOP = (120, 205, 255)

# @skinlab {"type":"color","label":"Container side","group":"Palette"}
CONTAINER_BOX_SIDE = (20, 92, 162)

# @skinlab {"type":"color","label":"Container ribs","group":"Palette"}
CONTAINER_BOX_RIB = (12, 70, 130)

# @skinlab {"type":"color","label":"Deck lamp","group":"Palette"}
CONTAINER_LAMP = (255, 240, 180)

# @skinlab {"type":"integer","label":"Horizon","group":"Layout","min":32,"max":58,"step":1}
CONTAINER_HORIZON = 56

# @skinlab {"type":"integer","label":"Horizon glow","group":"Layout","min":0,"max":5,"step":1}
CONTAINER_SUN_RINGS = 3

# @skinlab {"type":"number","label":"Swell speed","group":"Motion","min":0.5,"max":6,"step":0.5}
CONTAINER_SWELL_SPEED = 2.0

# @skinlab {"type":"number","label":"Bob rate","group":"Motion","min":0.25,"max":4,"step":0.25}
CONTAINER_BOB_TURNS = 1.0

# @skinlab {"type":"number","label":"Lamp blink rate","group":"Motion","min":1,"max":8,"step":1}
CONTAINER_LAMP_RATE = 3.0

# @skinlab {"type":"boolean","label":"Drifting cloud","group":"Motion"}
CONTAINER_CLOUD_DRIFT = True

# @skinlab {"type":"integer","label":"Swell lines","group":"Motion","min":0,"max":8,"step":1}
CONTAINER_SWELLS = 5

# @skinlab {"type":"integer","label":"Deck lamps","group":"Motion","min":0,"max":5,"step":1}
CONTAINER_LAMPS = 3

# @skinlab {"type":"integer","label":"Sun glitter","group":"Motion","min":0,"max":8,"step":1}
CONTAINER_GLITTER = 4

# @skinlab {"type":"integer","label":"Wake foam","group":"Motion","min":0,"max":6,"step":1}
CONTAINER_FOAM = 3

# @skinlab {"type":"boolean","label":"Second crate","group":"Motion"}
CONTAINER_SECOND = True

# @skinlab {"type":"boolean","label":"Gull","group":"Motion"}
CONTAINER_GULL = True


def _g_container_sea(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    hz = h * CONTAINER_HORIZON // 100
    for y in range(hz):
        k = y * 255 // max(1, hz - 1)
        buf.pen = color.rgb(CONTAINER_SKY[0] + k * 31 // 255,
                            CONTAINER_SKY[1] + k * 132 // 255,
                            CONTAINER_SKY[2] + k * 191 // 255)
        buf.rectangle(0, y, w, 1)
    buf.pen = color.rgb(190, 235, 255, 40)
    for i in range(CONTAINER_SUN_RINGS):
        buf.circle(w // 2, hz, max(2, min(w, h) * (5 - i) // 12))
    buf.pen = color.rgb(255, 255, 255, 46)
    clouds = ((3, 8, 9), (7, 6, 5), (24, 11, 7), (29, 7, 4), (14, 5, 3))
    for cl in clouds:
        buf.rectangle(w * cl[0] // 40, h * cl[1] // 100, w * cl[2] // 40, max(1, h // 40))
    buf.pen = color.rgb(255, 255, 255, 26)
    buf.rectangle(w * 3 // 40, h * 6 // 100, w * 8 // 40, max(1, h // 40))
    buf.pen = color.rgb(*CONTAINER_SEA)
    buf.rectangle(0, hz, w, h - hz)
    buf.pen = color.rgb(150, 220, 255, 190)
    buf.rectangle(0, hz, w, max(1, h // 120))
    buf.pen = color.rgb(CONTAINER_RAY[0], CONTAINER_RAY[1], CONTAINER_RAY[2], 130)
    for i in range(-6, 7):
        buf.line(w // 2 + i * (w // 34), hz, w // 2 + i * (w * 4 // 11), h)
    for i in range(1, 9):
        buf.rectangle(0, hz + (h - hz) * i * i // 70, w, max(1, h // 120))
    boxes = ((4, 62, 6), (4, 82, 6), (30, 66, 5), (22, 60, 3))
    for bx in boxes:
        x = w * bx[0] // 40
        y = h * bx[1] // 100
        s = w * bx[2] // 40
        dd = max(1, s // 3)
        buf.pen = color.rgb(*CONTAINER_BOX_SIDE)
        buf.triangle(x + s, y, x + s + dd, y - dd, x + s + dd, y + s - dd)
        buf.triangle(x + s, y, x + s + dd, y + s - dd, x + s, y + s)
        buf.pen = color.rgb(*CONTAINER_BOX_TOP)
        buf.triangle(x, y, x + s, y, x + dd, y - dd)
        buf.triangle(x + s, y, x + s + dd, y - dd, x + dd, y - dd)
        buf.pen = color.rgb(*CONTAINER_BOX)
        buf.rectangle(x, y, s, s)
        buf.pen = color.rgb(*CONTAINER_BOX_RIB)
        buf.rectangle(x + s // 3, y, max(1, s // 12), s)
        buf.rectangle(x + s * 2 // 3, y, max(1, s // 12), s)
    buf.pen = color.rgb(0, 0, 0, 60)
    buf.rectangle(0, h - h // 8, w, h // 8)
    buf.pen = color.rgb(6, 30, 70, 90)
    buf.rectangle(0, 0, w, h * 4 // 100)


def _g_container_sea_a(dst, t):
    """A working sea, not one bobbing crate.

    A whole swell set runs at the water, two crates ride it out of phase, foam
    breaks off the near hull, the deck lamps blink, the sun glitters on the
    chop and a gull crosses the sky. The busy marks -- foam, glitter, lamps --
    all sit below 0.66h; what crosses the name band is the swell and the
    clouds, which is broad and slow by construction."""
    import math
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    hz = h * CONTAINER_HORIZON // 100

    # the swell set: lines running at the viewer, foreshortened by p * p
    for i in range(CONTAINER_SWELLS):
        p = (t * CONTAINER_SWELL_SPEED + i / max(1, CONTAINER_SWELLS)) % 1.0
        dst.pen = color.rgb(170, 230, 255, 40 + int(70 * p))
        dst.rectangle(0, hz + int((h - hz) * p * p), w, max(1, h // 90))

    # sun glitter on the chop, kept clear of the name band
    for i in range(CONTAINER_GLITTER):
        gp = (t * 4.0 + i * 0.31) % 1.0
        dst.pen = color.rgb(255, 250, 220, 40 + int(200 * math.sin(math.pi * gp)))
        dst.rectangle((i * 97) % w, h * (64 + (i * 5) % 8) // 100,
                      max(1, u), max(1, u // 3))

    s = w * 8 // 40
    dd = max(1, s // 3)
    x = w * 16 // 40
    bob = int(math.sin(t * CONTAINER_BOB_TURNS * 6.2832) * (h // 40))
    y = h * 70 // 100 + bob
    dst.pen = color.rgb(*CONTAINER_BOX_SIDE)
    dst.triangle(x + s, y, x + s + dd, y - dd, x + s + dd, y + s - dd)
    dst.triangle(x + s, y, x + s + dd, y + s - dd, x + s, y + s)
    dst.pen = color.rgb(140, 215, 255)
    dst.triangle(x, y, x + s, y, x + dd, y - dd)
    dst.triangle(x + s, y, x + s + dd, y - dd, x + dd, y - dd)
    dst.pen = color.rgb(*CONTAINER_BOX)
    dst.rectangle(x, y, s, s)
    dst.pen = color.rgb(*CONTAINER_BOX_RIB)
    dst.rectangle(x + s // 3, y, max(1, s // 12), s)
    dst.rectangle(x + s * 2 // 3, y, max(1, s // 12), s)

    # foam breaking off the near hull as it drops into the trough
    for i in range(CONTAINER_FOAM):
        fp = (t * 2.0 + i * 0.37) % 1.0
        dst.pen = color.rgb(240, 252, 255, 200 - int(fp * 180))
        dst.rectangle(x - u + i * (s // max(1, CONTAINER_FOAM)) + int(fp * u * 3),
                      y + s - int(fp * u), max(2, u), max(1, u // 2))

    # a second crate riding the same swell half a beat behind
    if CONTAINER_SECOND:
        s2 = w * 5 // 40
        d2 = max(1, s2 // 3)
        x2 = w * 26 // 40
        y2 = h * 80 // 100 - int(math.sin(t * CONTAINER_BOB_TURNS * 6.2832) * (h // 44))
        dst.pen = color.rgb(*CONTAINER_BOX_SIDE)
        dst.triangle(x2 + s2, y2, x2 + s2 + d2, y2 - d2, x2 + s2 + d2, y2 + s2 - d2)
        dst.pen = color.rgb(120, 205, 255)
        dst.triangle(x2, y2, x2 + s2, y2, x2 + d2, y2 - d2)
        dst.pen = color.rgb(*CONTAINER_BOX)
        dst.rectangle(x2, y2, s2, s2)
        dst.pen = color.rgb(*CONTAINER_BOX_RIB)
        dst.rectangle(x2 + s2 // 2, y2, max(1, s2 // 10), s2)

    # deck lamps blinking out of step with each other
    for i in range(CONTAINER_LAMPS):
        if ((t * (CONTAINER_LAMP_RATE + i) + i * 0.3) % 1.0) < 0.4:
            dst.pen = color.rgb(*CONTAINER_LAMP)
        else:
            dst.pen = color.rgb(*CONTAINER_BOX_RIB)
        dst.circle(x + dd + s * (i + 1) // (CONTAINER_LAMPS + 1), y - dd,
                   max(1, u // 2))

    if CONTAINER_GULL:
        gx = int(-u * 4 + (w + u * 8) * ((t + 0.3) % 1.0))
        gy = h * 14 // 100 + int(math.sin(t * 4.0 * math.pi) * (h // 50))
        flap = max(1, u // 2 + int(u * abs(math.sin(t * 8.0 * math.pi))))
        dst.pen = color.rgb(250, 252, 255, 220)
        dst.triangle(gx, gy, gx - u * 2, gy - flap, gx - u, gy + max(1, u // 3))
        dst.triangle(gx, gy, gx + u * 2, gy - flap, gx + u, gy + max(1, u // 3))

    if CONTAINER_CLOUD_DRIFT:
        # a whole lap per cycle, entering left as it leaves right; the old
        # `+ int(t * w // 6)` was an unbounded ramp and snapped back at t = 1
        cw = w * 8 // 40
        dst.pen = color.rgb(255, 255, 255, 34)
        dst.rectangle(int((t + 0.08) % 1.0 * (w + cw)) - cw, h * 6 // 100,
                      cw, max(1, h // 40))
        cw = w * 6 // 40
        dst.pen = color.rgb(255, 255, 255, 26)
        dst.rectangle(int((t + 0.61) % 1.0 * (w + cw)) - cw, h * 11 // 100,
                      cw, max(1, h // 44))


# @skinlab {"type":"color","label":"Ground","group":"Palette"}
INTERLOCK_INK = (14, 22, 36)

# @skinlab {"type":"color","label":"Blue plate","group":"Palette"}
INTERLOCK_BLUE = (48, 105, 152)

# @skinlab {"type":"color","label":"Blue shadow","group":"Palette"}
INTERLOCK_BLUE_SHADE = (28, 66, 102)

# @skinlab {"type":"color","label":"Yellow plate","group":"Palette"}
INTERLOCK_YELLOW = (255, 212, 59)

# @skinlab {"type":"color","label":"Yellow highlight","group":"Palette"}
INTERLOCK_YELLOW_LIGHT = (255, 240, 150)

# @skinlab {"type":"integer","label":"Columns","group":"Layout","min":14,"max":26,"step":1}
INTERLOCK_COLUMNS = 14

# @skinlab {"type":"integer","label":"Stair base","group":"Layout","min":62,"max":94,"step":1}
INTERLOCK_STAIR_BASE = 84

# @skinlab {"type":"integer","label":"Stair rise","group":"Layout","min":10,"max":66,"step":1}
INTERLOCK_STAIR_RISE = 50

# @skinlab {"type":"integer","label":"Tab height","group":"Shape","min":3,"max":26,"step":1}
INTERLOCK_TAB = 13

# @skinlab {"type":"integer","label":"Rivet size","group":"Shape","min":3,"max":15,"step":1}
INTERLOCK_RIVET = 9


def _g_interlock(buf):
    w, h = buf.width, buf.height
    buf.pen = color.rgb(*INTERLOCK_INK)
    buf.clear()
    n = INTERLOCK_COLUMNS
    gap = max(1, h // 36)
    sh = max(1, h // 30)
    for i in range(n):
        x = w * i // n
        xw = w * (i + 1) // n - x
        sy = h * INTERLOCK_STAIR_BASE // 100 - h * INTERLOCK_STAIR_RISE // 100 * i // (n - 1)
        buf.pen = color.rgb(*INTERLOCK_BLUE)
        buf.rectangle(x, 0, xw, sy)
        buf.pen = color.rgb(*INTERLOCK_BLUE_SHADE)
        buf.rectangle(x, sy - sh, xw, sh)
        buf.pen = color.rgb(*INTERLOCK_YELLOW)
        buf.rectangle(x, sy + gap, xw, h - sy - gap)
        buf.pen = color.rgb(*INTERLOCK_YELLOW_LIGHT)
        buf.rectangle(x, sy + gap, xw, sh)
    tabs = (2, 7, 11)
    for i in tabs:
        x = w * i // n
        xw = w * (i + 1) // n - x
        sy = h * INTERLOCK_STAIR_BASE // 100 - h * INTERLOCK_STAIR_RISE // 100 * i // (n - 1)
        ts = h * INTERLOCK_TAB // 100
        buf.pen = color.rgb(*INTERLOCK_YELLOW)
        buf.rectangle(x, sy - ts, xw, h - sy + ts)
        buf.pen = color.rgb(*INTERLOCK_YELLOW_LIGHT)
        buf.rectangle(x, sy - ts, xw, sh)
    tabs = (4, 9, 13)
    for i in tabs:
        x = w * i // n
        xw = w * (i + 1) // n - x
        sy = h * INTERLOCK_STAIR_BASE // 100 - h * INTERLOCK_STAIR_RISE // 100 * i // (n - 1)
        ts = h * INTERLOCK_TAB // 100
        buf.pen = color.rgb(*INTERLOCK_BLUE)
        buf.rectangle(x, 0, xw, sy + gap + ts)
        buf.pen = color.rgb(*INTERLOCK_BLUE_SHADE)
        buf.rectangle(x, sy + gap + ts - sh, xw, sh)
    buf.pen = color.rgb(INTERLOCK_INK[0], INTERLOCK_INK[1], INTERLOCK_INK[2], 150)
    for i in range(n):
        x = w * i // n
        xw = w * (i + 1) // n - x
        sy = h * INTERLOCK_STAIR_BASE // 100 - h * INTERLOCK_STAIR_RISE // 100 * i // (n - 1)
        buf.rectangle(x, sy + gap, xw, max(1, h // 60))
    buf.pen = color.rgb(0, 0, 0, 26)
    for i in range(4):
        buf.rectangle(0, h * (58 + i * 10) // 100, w, max(1, h // 40))
    buf.pen = color.rgb(255, 255, 255, 22)
    for i in range(4):
        buf.rectangle(0, h * (6 + i * 9) // 100, w, max(1, h // 60))
    ex = w * 24 // 100
    ey = h * 17 // 100
    er = max(2, min(w, h) * INTERLOCK_RIVET // 100)
    buf.pen = color.rgb(*INTERLOCK_YELLOW)
    buf.circle(ex, ey, er)
    buf.pen = color.rgb(*INTERLOCK_INK)
    buf.circle(ex + er // 3, ey, max(1, er * 2 // 5))
    ex = w * 78 // 100
    ey = h * 83 // 100
    buf.pen = color.rgb(*INTERLOCK_BLUE)
    buf.circle(ex, ey, er)
    buf.pen = color.rgb(*INTERLOCK_INK)
    buf.circle(ex - er // 3, ey, max(1, er * 2 // 5))
    buf.pen = color.rgb(0, 0, 0, 70)
    buf.rectangle(0, 0, w, h * 5 // 100)
    buf.rectangle(0, h - h * 5 // 100, w, h * 5 // 100)
    buf.pen = color.rgb(255, 255, 255, 26)
    buf.rectangle(0, h * 5 // 100, w, max(1, h // 120))


# @skinlab {"type":"color","label":"Border","group":"Palette"}
C64_BORDER = (108, 94, 181)

# @skinlab {"type":"color","label":"Screen","group":"Palette"}
C64_SCREEN = (53, 40, 121)

# @skinlab {"type":"color","label":"Text","group":"Palette"}
C64_TEXT = (134, 122, 202)

# @skinlab {"type":"color","label":"Loader bar one","group":"Palette"}
C64_BAR_A = (144, 172, 100)

# @skinlab {"type":"color","label":"Loader bar two","group":"Palette"}
C64_BAR_B = (184, 199, 111)

# @skinlab {"type":"color","label":"Loader bar three","group":"Palette"}
C64_BAR_C = (204, 118, 60)

# @skinlab {"type":"color","label":"Loader bar four","group":"Palette"}
C64_BAR_D = (154, 103, 89)

# @skinlab {"type":"color","label":"Loader bar five","group":"Palette"}
C64_BAR_E = (112, 164, 178)

# @skinlab {"type":"integer","label":"Scanline depth","group":"Look","min":0,"max":120,"step":2}
C64_SCANLINE_ALPHA = 22

# @skinlab {"type":"integer","label":"Side border","group":"Layout","min":0,"max":22,"step":1}
C64_BORDER_X = 8

# @skinlab {"type":"integer","label":"Top border","group":"Layout","min":0,"max":22,"step":1}
C64_BORDER_Y = 9

# @skinlab {"type":"integer","label":"Text columns","group":"Layout","min":35,"max":80,"step":1}
C64_COLS = 40

# @skinlab {"type":"integer","label":"Text rows","group":"Layout","min":18,"max":50,"step":1}
C64_ROWS = 25

# @skinlab {"type":"integer","label":"Loader speed","group":"Motion","min":1,"max":60,"step":1}
C64_LOAD_SPEED = 26

# @skinlab {"type":"integer","label":"Side raster rows","group":"Layout","min":0,"max":20,"step":1}
C64_RASTER_ROWS = 11

# @skinlab {"type":"integer","label":"Side raster offset","group":"Motion","min":0,"max":4,"step":1}
C64_RASTER_SKEW = 3

# @skinlab {"type":"number","label":"Cursor duty","group":"Motion","min":0.05,"max":0.9,"step":0.05}
C64_CURSOR_DUTY = 0.3


def _g_c64_ready(buf):
    w, h = buf.width, buf.height
    bx = max(1, w * C64_BORDER_X // 100)
    by = max(1, h * C64_BORDER_Y // 100)
    buf.pen = color.rgb(*C64_BORDER)
    buf.clear()
    buf.pen = color.rgb(*C64_SCREEN)
    buf.rectangle(bx, by, w - 2 * bx, h - 2 * by)
    iw = w - 2 * bx
    ih = h - 2 * by
    cw = max(1, iw // C64_COLS)
    ch = max(1, ih // C64_ROWS)
    bw = max(1, cw - 1)
    bh = max(1, ch * 3 // 4)
    rows = ((0, 4, 4), (0, 9, 9), (0, 19, 2), (0, 22, 5), (0, 28, 2), (0, 31, 4),
            (2, 1, 3), (2, 5, 3), (2, 9, 6), (2, 17, 5), (2, 23, 5), (2, 29, 5),
            (12, 1, 6),
            (14, 1, 4), (14, 6, 3), (14, 10, 1), (14, 12, 3),
            (16, 1, 6))
    buf.pen = color.rgb(*C64_TEXT)
    for r, c, n in rows:
        y = by + r * ch + ch // 5
        for i in range(n):
            buf.rectangle(bx + c * cw + i * cw, y, bw, bh)
    buf.pen = color.rgb(0, 0, 0, C64_SCANLINE_ALPHA)
    step = max(2, h // 60)
    for y in range(0, h, step):
        buf.rectangle(0, y, w, max(1, step // 2))
    cs = max(2, w // 14)
    cq = max(2, h // 12)
    buf.pen = color.rgb(0, 0, 0, 90)
    buf.triangle(0, 0, cs * 2, 0, 0, cq * 2)
    buf.triangle(w, 0, w - cs * 2, 0, w, cq * 2)
    buf.triangle(0, h, cs * 2, h, 0, h - cq * 2)
    buf.triangle(w, h, w - cs * 2, h, w, h - cq * 2)
    buf.pen = color.rgb(0, 0, 0, 170)
    buf.triangle(0, 0, cs, 0, 0, cq)
    buf.triangle(w, 0, w - cs, 0, w, cq)
    buf.triangle(0, h, cs, h, 0, h - cq)
    buf.triangle(w, h, w - cs, h, w, h - cq)


def _g_c64_ready_a(dst, t):
    """A tape loader owns the WHOLE border, not the top inch of it.

    The raster interrupt fires on every scanline the beam spends outside the
    text window, so the stripes run down both sides as well as across the top
    and bottom -- that band of colour racing round the frame is the entire
    reason anybody remembers loading from tape. The sides are offset from the
    top by C64_RASTER_SKEW so the pattern reads as one continuous sweep rather
    than four independent flashers.
    """
    w, h = dst.width, dst.height
    bx = max(1, w * C64_BORDER_X // 100)
    by = max(1, h * C64_BORDER_Y // 100)
    bars = (C64_BAR_A, C64_BAR_B, C64_BAR_C, C64_BAR_D, C64_BAR_E)
    k = int(t * C64_LOAD_SPEED)
    sh = max(1, by // 4) + 1
    for i in range(4):
        r, g, b = bars[(i + k) % 5]
        dst.pen = color.rgb(r, g, b)
        dst.rectangle(0, i * by // 4, w, sh)
        r, g, b = bars[(i + k + 2) % 5]
        dst.pen = color.rgb(r, g, b)
        dst.rectangle(0, h - by + i * by // 4, w, sh)
    inner = max(1, h - 2 * by)
    rh = inner // max(1, C64_RASTER_ROWS) + 1
    for i in range(C64_RASTER_ROWS):
        y = by + i * inner // max(1, C64_RASTER_ROWS)
        r, g, b = bars[(i + k + C64_RASTER_SKEW) % 5]
        dst.pen = color.rgb(r, g, b)
        dst.rectangle(0, y, bx, rh)
        r, g, b = bars[(i + k + C64_RASTER_SKEW + 2) % 5]
        dst.pen = color.rgb(r, g, b)
        dst.rectangle(w - bx, y, bx, rh)
    if t % 0.5 < C64_CURSOR_DUTY:
        iw = w - 2 * bx
        ih = h - 2 * by
        cw = max(1, iw // C64_COLS)
        ch = max(1, ih // C64_ROWS)
        dst.pen = color.rgb(*C64_TEXT)
        dst.rectangle(bx + cw, by + 16 * ch + ch // 6, cw, ch)


# @skinlab {"type":"color","label":"Screen","group":"Palette"}
DMG_LIGHTEST = (155, 188, 15)

# @skinlab {"type":"color","label":"Light shade","group":"Palette"}
DMG_LIGHT = (139, 172, 15)

# @skinlab {"type":"color","label":"Mid shade","group":"Palette"}
DMG_MID = (48, 98, 48)

# @skinlab {"type":"color","label":"Dark shade","group":"Palette"}
DMG_DARK = (15, 56, 15)

# @skinlab {"type":"integer","label":"Wash strength","group":"Look","min":0,"max":255,"step":2}
DMG_WASH_ALPHA = 28

# @skinlab {"type":"integer","label":"Grid strength","group":"Look","min":0,"max":255,"step":5}
DMG_GRID_ALPHA = 40

# @skinlab {"type":"integer","label":"Sweep brightness","group":"Look","min":0,"max":255,"step":5}
DMG_SWEEP_ALPHA = 30

# @skinlab {"type":"integer","label":"Wash bands","group":"Layout","min":1,"max":10,"step":1}
DMG_WASH_BANDS = 6

# @skinlab {"type":"integer","label":"Grid density","group":"Layout","min":8,"max":60,"step":1}
DMG_GRID_DENSITY = 30

# @skinlab {"type":"integer","label":"Logo height","group":"Layout","min":28,"max":78,"step":1}
DMG_LOGO_Y = 55

# @skinlab {"type":"integer","label":"Shade bar height","group":"Layout","min":10,"max":40,"step":1}
DMG_SHADE_BAR_Y = 12

# @skinlab {"type":"number","label":"Drop duration","group":"Motion","min":0.1,"max":0.48,"step":0.02}
DMG_DROP_END = 0.42

# @skinlab {"type":"number","label":"Sweep speed","group":"Motion","min":0.25,"max":6,"step":0.25}
DMG_SWEEP_SPEED = 2.0

# @skinlab {"type":"integer","label":"Refresh bands","group":"Layout","min":0,"max":10,"step":1}
DMG_LCD_BANDS = 6

# @skinlab {"type":"number","label":"Refresh speed","group":"Motion","min":0.25,"max":4,"step":0.25}
DMG_LCD_SPEED = 1.0

# @skinlab {"type":"integer","label":"Refresh strength","group":"Look","min":0,"max":120,"step":2}
DMG_LCD_ALPHA = 22

# @skinlab {"type":"number","label":"Contrast beat speed","group":"Motion","min":0.25,"max":4,"step":0.25}
DMG_GHOST_SPEED = 1.0

# @skinlab {"type":"integer","label":"Contrast beat depth","group":"Look","min":0,"max":80,"step":2}
DMG_GHOST_ALPHA = 14


def _g_dmg_boot(buf):
    w, h = buf.width, buf.height
    p = max(1, w // 40)
    buf.pen = color.rgb(*DMG_LIGHTEST)
    buf.clear()
    for i in range(DMG_WASH_BANDS):
        buf.pen = color.rgb(DMG_LIGHT[0], DMG_LIGHT[1], DMG_LIGHT[2], DMG_WASH_ALPHA)
        buf.rectangle(0, 0, w, h * (DMG_WASH_BANDS - i) // 11)
    gy = max(2, h // DMG_GRID_DENSITY)
    buf.pen = color.rgb(DMG_MID[0], DMG_MID[1], DMG_MID[2], DMG_GRID_ALPHA)
    for y in range(0, h, gy):
        buf.rectangle(0, y, w, max(1, gy // 3))
    fr = max(1, w // 26)
    buf.pen = color.rgb(*DMG_DARK)
    buf.rectangle(0, 0, w, fr)
    buf.rectangle(0, h - fr, w, fr)
    buf.rectangle(0, 0, fr, h)
    buf.rectangle(w - fr, 0, fr, h)
    buf.pen = color.rgb(DMG_MID[0], DMG_MID[1], DMG_MID[2], 120)
    buf.rectangle(fr, fr, w - 2 * fr, max(1, h // 60))
    ly = h * DMG_LOGO_Y // 100
    lx = (w - 27 * p) // 2
    buf.pen = color.rgb(*DMG_DARK)
    buf.rectangle(lx, ly + 3 * p, 9 * p, 3 * p)
    buf.rectangle(lx + 3 * p, ly, 3 * p, 9 * p)
    buf.pen = color.rgb(*DMG_MID)
    buf.rectangle(lx + 3 * p, ly + 3 * p, 3 * p, 3 * p)
    buf.pen = color.rgb(*DMG_DARK)
    buf.circle(lx + 23 * p, ly + 3 * p, max(1, p * 3 // 2))
    buf.circle(lx + 18 * p, ly + 6 * p, max(1, p * 3 // 2))
    buf.rectangle(lx + 12 * p, ly + 8 * p, 4 * p, max(1, p))
    buf.rectangle(lx + 17 * p, ly + 8 * p, 4 * p, max(1, p))
    shades = (DMG_LIGHTEST, DMG_LIGHT, DMG_MID, DMG_DARK)
    rw = 3 * p
    rx = (w - 4 * rw) // 2
    ry = h * DMG_SHADE_BAR_Y // 100
    buf.pen = color.rgb(*DMG_DARK)
    buf.rectangle(rx - p, ry - p, 4 * rw + 2 * p, 4 * p)
    for i in range(4):
        s = shades[i]
        buf.pen = color.rgb(s[0], s[1], s[2])
        buf.rectangle(rx + i * rw, ry, rw, 2 * p)
    buf.pen = color.rgb(DMG_DARK[0], DMG_DARK[1], DMG_DARK[2], 150)
    for i in range(9):
        buf.rectangle(w // 4 + i * 2 * p, h - fr - 2 * p, max(1, p * 3 // 2), max(1, p))


def _g_dmg_boot_a(dst, t):
    w, h = dst.width, dst.height
    p = max(1, w // 40)
    ly = h * DMG_LOGO_Y // 100
    lx = (w - 27 * p) // 2
    if t < DMG_DROP_END:
        y = int((ly + 10 * p) * t / DMG_DROP_END) - 10 * p
        dst.pen = color.rgb(*DMG_LIGHTEST)
        dst.rectangle(0, ly - p, w, 11 * p)
        gy = max(2, h // DMG_GRID_DENSITY)
        k = (ly - p + gy - 1) // gy
        dst.pen = color.rgb(DMG_MID[0], DMG_MID[1], DMG_MID[2], DMG_GRID_ALPHA)
        for i in range(11 * p // gy + 1):
            yy = (k + i) * gy
            if yy < ly + 10 * p:
                dst.rectangle(0, yy, w, max(1, gy // 3))
        dst.pen = color.rgb(*DMG_DARK)
        dst.rectangle(lx, y + 3 * p, 9 * p, 3 * p)
        dst.rectangle(lx + 3 * p, y, 3 * p, 9 * p)
        dst.pen = color.rgb(*DMG_MID)
        dst.rectangle(lx + 3 * p, y + 3 * p, 3 * p, 3 * p)
        dst.pen = color.rgb(*DMG_DARK)
        dst.circle(lx + 23 * p, y + 3 * p, max(1, p * 3 // 2))
        dst.circle(lx + 18 * p, y + 6 * p, max(1, p * 3 // 2))
        dst.rectangle(lx + 12 * p, y + 8 * p, 4 * p, max(1, p))
        dst.rectangle(lx + 17 * p, y + 8 * p, 4 * p, max(1, p))
        fr = max(1, w // 26)
        dst.pen = color.rgb(*DMG_DARK)
        dst.rectangle(0, ly - p, fr, 11 * p)
        dst.rectangle(w - fr, ly - p, fr, 11 * p)
        shades = (DMG_LIGHTEST, DMG_LIGHT, DMG_MID, DMG_DARK)
        rw = 3 * p
        rx = (w - 4 * rw) // 2
        ry = h * DMG_SHADE_BAR_Y // 100
        dst.pen = color.rgb(*DMG_DARK)
        dst.rectangle(rx - p, ry - p, 4 * rw + 2 * p, 4 * p)
        for i in range(4):
            s = shades[i]
            dst.pen = color.rgb(s[0], s[1], s[2])
            dst.rectangle(rx + i * rw, ry, rw, 2 * p)
    elif t < 0.5:
        dst.pen = color.rgb(DMG_DARK[0], DMG_DARK[1], DMG_DARK[2], int((0.5 - t) * 900))
        dst.rectangle(0, 0, w, h)
    sy = int(h * ((t * DMG_SWEEP_SPEED) % 1.0))
    dst.pen = color.rgb(DMG_LIGHTEST[0], DMG_LIGHTEST[1], DMG_LIGHTEST[2], DMG_SWEEP_ALPHA)
    dst.rectangle(0, sy, w, max(1, h // 22))
    # The panel never settles once the logo has landed. A DMG's refresh crawls
    # down the glass as a stack of ghost bands and the contrast wheel beats a
    # slower shadow under them, which is why a real one looks alive on a boot
    # screen that is, strictly, a static picture. Evenly phased bands mean the
    # stack wraps rather than restarting at t = 1.
    lb = max(2, h // 26)
    for i in range(DMG_LCD_BANDS):
        ly2 = int(h * ((t * DMG_LCD_SPEED + i * 1.0 / DMG_LCD_BANDS) % 1.0))
        dst.pen = color.rgb(DMG_MID[0], DMG_MID[1], DMG_MID[2],
                            max(0, DMG_LCD_ALPHA - i * 2))
        dst.rectangle(0, ly2, w, lb)
    dst.pen = color.rgb(DMG_DARK[0], DMG_DARK[1], DMG_DARK[2], DMG_GHOST_ALPHA)
    dst.rectangle(0, int(h * (1.0 - (t * DMG_GHOST_SPEED) % 1.0)) - h // 5,
                  w, max(2, h // 5))


# @skinlab {"type":"color","label":"Desk halo","group":"Palette"}
FLOPPY_HALO = (70, 78, 120)

# @skinlab {"type":"color","label":"Disk shell","group":"Palette"}
FLOPPY_SHELL = (30, 32, 40)

# @skinlab {"type":"color","label":"Metal shutter","group":"Palette"}
FLOPPY_SHUTTER = (174, 180, 192)

# @skinlab {"type":"color","label":"Paper label","group":"Palette"}
FLOPPY_LABEL = (236, 231, 214)

# @skinlab {"type":"color","label":"Label header","group":"Palette"}
FLOPPY_LABEL_BAND = (40, 92, 186)

# @skinlab {"type":"color","label":"Label rule","group":"Palette"}
FLOPPY_LABEL_RULE = (226, 60, 60)

# @skinlab {"type":"color","label":"Handwriting","group":"Palette"}
FLOPPY_INK = (120, 116, 108)

# @skinlab {"type":"color","label":"Disk below","group":"Palette"}
FLOPPY_BACK_LABEL = (60, 170, 90)

# @skinlab {"type":"color","label":"Disk in the middle","group":"Palette"}
FLOPPY_MID_LABEL = (214, 108, 36)

# @skinlab {"type":"integer","label":"Halo strength","group":"Look","min":0,"max":120,"step":2}
FLOPPY_HALO_ALPHA = 14

# @skinlab {"type":"integer","label":"Edge shading","group":"Look","min":0,"max":190,"step":5}
FLOPPY_EDGE_ALPHA = 120

# @skinlab {"type":"integer","label":"Halo rings","group":"Layout","min":0,"max":7,"step":1}
FLOPPY_HALO_RINGS = 4

# @skinlab {"type":"integer","label":"Disk height","group":"Layout","min":0,"max":16,"step":1}
FLOPPY_TOP = 9


def _g_floppy_1_44m(buf):
    w, h = buf.width, buf.height
    for i in range(18):
        v = 10 + i
        buf.pen = color.rgb(v, v + 3, v + 14)
        buf.rectangle(0, i * h // 18, w, h // 18 + 1)
    buf.pen = color.rgb(FLOPPY_HALO[0], FLOPPY_HALO[1], FLOPPY_HALO[2], FLOPPY_HALO_ALPHA)
    for i in range(FLOPPY_HALO_RINGS):
        buf.circle(w // 2, h * 42 // 100, max(3, min(w, h) * (7 - i) // 8))
    s = min(w * 62 // 100, h * 84 // 100)
    x0 = (w - s) // 2
    y0 = h * FLOPPY_TOP // 100
    o = max(1, s // 12)
    buf.pen = color.rgb(20, 22, 30)
    buf.rectangle(x0 - o * 2, y0 - o, s, s)
    buf.pen = color.rgb(34, 36, 46)
    buf.rectangle(x0 - o * 2, y0 - o, s, max(1, s // 40))
    buf.pen = color.rgb(*FLOPPY_BACK_LABEL)
    buf.rectangle(x0 - o * 2, y0 - o + s * 26 // 100, s, max(1, s // 12))
    buf.pen = color.rgb(24, 26, 34)
    buf.rectangle(x0 - o, y0 - o // 2, s, s)
    buf.pen = color.rgb(38, 40, 50)
    buf.rectangle(x0 - o, y0 - o // 2, s, max(1, s // 40))
    buf.pen = color.rgb(*FLOPPY_MID_LABEL)
    buf.rectangle(x0 - o, y0 - o // 2 + s * 26 // 100, s, max(1, s // 12))
    buf.pen = color.rgb(0, 0, 0, 90)
    buf.rectangle(x0 + max(1, s // 20), y0 + max(1, s // 20), s, s)
    buf.pen = color.rgb(*FLOPPY_SHELL)
    buf.rectangle(x0, y0, s, s)
    buf.pen = color.rgb(64, 68, 82)
    buf.rectangle(x0, y0, s, max(1, s // 36))
    buf.rectangle(x0, y0, max(1, s // 36), s)
    buf.pen = color.rgb(12, 12, 18)
    buf.rectangle(x0, y0 + s - max(1, s // 26), s, max(1, s // 26))
    buf.triangle(x0 + s, y0, x0 + s - s // 7, y0, x0 + s, y0 + s // 7)
    buf.pen = color.rgb(*FLOPPY_SHUTTER)
    buf.rectangle(x0 + s // 5, y0, s * 3 // 5, s * 17 // 100)
    buf.pen = color.rgb(214, 220, 232)
    buf.rectangle(x0 + s // 5, y0, s * 3 // 5, max(1, s // 40))
    buf.pen = color.rgb(120, 126, 138)
    buf.rectangle(x0 + s // 5, y0 + s * 17 // 100 - max(1, s // 30), s * 3 // 5, max(1, s // 30))
    buf.pen = color.rgb(22, 24, 30)
    buf.rectangle(x0 + s * 36 // 100, y0, s * 26 // 100, s * 14 // 100)
    buf.pen = color.rgb(*FLOPPY_LABEL)
    buf.rectangle(x0 + s * 7 // 100, y0 + s * 20 // 100, s * 86 // 100, s * 48 // 100)
    buf.pen = color.rgb(206, 200, 182)
    buf.rectangle(x0 + s * 7 // 100, y0 + s * 66 // 100, s * 86 // 100, max(1, s // 40))
    buf.pen = color.rgb(*FLOPPY_LABEL_BAND)
    buf.rectangle(x0 + s * 7 // 100, y0 + s * 20 // 100, s * 86 // 100, s * 6 // 100)
    buf.pen = color.rgb(*FLOPPY_LABEL_RULE)
    buf.rectangle(x0 + s * 7 // 100, y0 + s * 26 // 100, s * 86 // 100, max(1, s // 50))
    buf.pen = color.rgb(FLOPPY_INK[0], FLOPPY_INK[1], FLOPPY_INK[2], 200)
    for i in range(3):
        buf.rectangle(x0 + s * 14 // 100, y0 + s * (46 + i * 5) // 100,
                      s * (54 - i * 13) // 100, max(1, s // 60))
    buf.pen = color.rgb(60, 64, 76)
    buf.rectangle(x0 + s * 70 // 100, y0 + s * 74 // 100, s * 20 // 100, s * 5 // 100)
    buf.pen = color.rgb(14, 14, 20)
    buf.rectangle(x0 + s * 4 // 100, y0 + s * 82 // 100, s * 10 // 100, s * 10 // 100)
    buf.rectangle(x0 + s * 86 // 100, y0 + s * 82 // 100, s * 10 // 100, s * 10 // 100)
    buf.pen = color.rgb(60, 64, 76)
    buf.rectangle(x0 + s * 30 // 100, y0 + s * 86 // 100, s * 40 // 100, max(1, s // 40))
    buf.pen = color.rgb(0, 0, 0, FLOPPY_EDGE_ALPHA)
    for i in range(4):
        buf.rectangle(0, h - (i + 1) * max(1, h // 30), w, max(1, h // 30))
        buf.rectangle(0, i * max(1, h // 40), w, max(1, h // 40))


# @skinlab {"type":"color","label":"Screen","group":"Palette"}
OSC_SCREEN = (4, 14, 8)

# @skinlab {"type":"color","label":"Graticule","group":"Palette"}
OSC_GRATICULE = (28, 92, 48)

# @skinlab {"type":"color","label":"Centre axes","group":"Palette"}
OSC_AXIS = (44, 128, 66)

# @skinlab {"type":"color","label":"Ghost trace","group":"Palette"}
OSC_GHOST = (60, 190, 90)

# @skinlab {"type":"color","label":"Live trace","group":"Palette"}
OSC_TRACE = (150, 255, 175)

# @skinlab {"type":"color","label":"Trace head","group":"Palette"}
OSC_DOT = (220, 255, 230)

# @skinlab {"type":"color","label":"Trigger marker","group":"Palette"}
OSC_MARKER = (255, 180, 40)

# @skinlab {"type":"color","label":"Readout bars","group":"Palette"}
OSC_READOUT = (120, 255, 150)

# @skinlab {"type":"integer","label":"Graticule columns","group":"Layout","min":4,"max":20,"step":1}
OSC_GRID_X = 10

# @skinlab {"type":"integer","label":"Graticule rows","group":"Layout","min":3,"max":16,"step":1}
OSC_GRID_Y = 8

# @skinlab {"type":"integer","label":"Trace height","group":"Shape","min":25,"max":78,"step":1}
OSC_TRACE_Y = 60

# @skinlab {"type":"integer","label":"Trace amplitude","group":"Shape","min":2,"max":32,"step":1}
OSC_AMPLITUDE = 20

# @skinlab {"type":"number","label":"Trace speed","group":"Motion","min":0.25,"max":4,"step":0.25}
OSC_TRACE_SPEED = 1.0

# @skinlab {"type":"number","label":"Sweep speed","group":"Motion","min":0.25,"max":4,"step":0.25}
OSC_SWEEP_SPEED = 1.0


def _g_oscilloscope(buf):
    import math
    # A graticule is drawn in millimetres, not in logical pixels: at a literal
    # 1 px the whole grid halved in weight at HIRES and the instrument read as
    # a faint sketch of itself.
    s = _stroke(buf)
    w, h = buf.width, buf.height
    buf.pen = color.rgb(*OSC_SCREEN)
    buf.clear()
    buf.pen = color.rgb(20, 80, 40, 26)
    for i in range(5):
        buf.circle(w // 2, h * OSC_TRACE_Y // 100, max(3, min(w, h) * (8 - i) // 8))
    gx = max(2, w // OSC_GRID_X)
    gy = max(2, h // OSC_GRID_Y)
    buf.pen = color.rgb(OSC_GRATICULE[0], OSC_GRATICULE[1], OSC_GRATICULE[2], 190)
    for x in range(gx, w, gx):
        buf.rectangle(x, 0, s, h)
    for y in range(gy, h, gy):
        buf.rectangle(0, y, w, s)
    buf.pen = color.rgb(OSC_AXIS[0], OSC_AXIS[1], OSC_AXIS[2], 220)
    buf.rectangle(w // 2, 0, s, h)
    buf.rectangle(0, h // 2, w, s)
    tk = max(1, w // 80)
    for i in range(1, 20):
        buf.rectangle(i * w // 20, h // 2 - tk, s, tk * 2 + 1)
    for i in range(1, 16):
        buf.rectangle(w // 2 - tk, i * h // 16, tk * 2 + 1, s)
    cy = h * OSC_TRACE_Y // 100
    amp = h * OSC_AMPLITUDE // 100
    n = 26
    px, py = 0, cy
    buf.pen = color.rgb(OSC_GHOST[0], OSC_GHOST[1], OSC_GHOST[2], 120)
    for i in range(n + 1):
        x = i * w // n
        a = i * 6.2832 * 2.0 / n
        y = cy + int(amp * math.sin(a) * 0.72 + amp * 0.34 * math.sin(a * 3.0 + 1.0))
        if i:
            _thick_line(buf, px, py, x, y, s)
        px, py = x, y
    buf.pen = color.rgb(*OSC_MARKER)
    tw = max(2, w // 26)
    buf.triangle(w - tw, cy - amp // 2, w, cy - amp // 2 - tw // 2, w, cy - amp // 2 + tw // 2)
    buf.pen = color.rgb(OSC_READOUT[0], OSC_READOUT[1], OSC_READOUT[2], 160)
    buf.rectangle(0, h - max(1, h // 22), w // 4, max(1, h // 22))
    buf.rectangle(w // 3, h - max(1, h // 22), w // 8, max(1, h // 22))
    buf.pen = color.rgb(0, 0, 0, 70)
    ev = max(1, w // 22)
    eh = max(1, h // 18)
    for i in range(4):
        buf.rectangle(i * ev, 0, ev, h)
        buf.rectangle(w - (i + 1) * ev, 0, ev, h)
        buf.rectangle(0, i * eh, w, eh)
        buf.rectangle(0, h - (i + 1) * eh, w, eh)
    cs = max(2, w // 12)
    cq = max(2, h // 10)
    buf.pen = color.rgb(0, 0, 0, 140)
    buf.triangle(0, 0, cs * 2, 0, 0, cq * 2)
    buf.triangle(w, 0, w - cs * 2, 0, w, cq * 2)
    buf.triangle(0, h, cs * 2, h, 0, h - cq * 2)
    buf.triangle(w, h, w - cs * 2, h, w, h - cq * 2)
    buf.pen = color.rgb(0, 0, 0)
    buf.triangle(0, 0, cs, 0, 0, cq)
    buf.triangle(w, 0, w - cs, 0, w, cq)
    buf.triangle(0, h, cs, h, 0, h - cq)
    buf.triangle(w, h, w - cs, h, w, h - cq)


def _g_oscilloscope_a(dst, t):
    import math
    w, h = dst.width, dst.height
    cy = h * OSC_TRACE_Y // 100
    amp = h * OSC_AMPLITUDE // 100
    n = 26
    ph = t * OSC_TRACE_SPEED * 6.2832
    px, py = 0, cy
    dst.pen = color.rgb(*OSC_TRACE)
    for i in range(n + 1):
        x = i * w // n
        a = ph + i * 6.2832 * 2.0 / n
        y = cy + int(amp * math.sin(a) * 0.72 + amp * 0.34 * math.sin(a * 3.0 + ph * 2.0))
        if i:
            _thick_line(dst, px, py, x, y, _stroke(dst))
        px, py = x, y
    dst.pen = color.rgb(*OSC_DOT)
    dst.circle(px, py, max(1, w // 80))
    sx = int(w * ((t * OSC_SWEEP_SPEED) % 1.0))
    dst.pen = color.rgb(OSC_READOUT[0], OSC_READOUT[1], OSC_READOUT[2], 40)
    dst.rectangle(sx, 0, max(1, w // 90), h)


# @skinlab {"type":"color","label":"Backdrop","group":"Palette"}
BBS_BACKDROP = (0, 0, 0)

# @skinlab {"type":"color","label":"Bright cyan","group":"Palette"}
BBS_CYAN = (85, 255, 255)

# @skinlab {"type":"color","label":"Dark cyan","group":"Palette"}
BBS_TEAL = (0, 170, 170)

# @skinlab {"type":"color","label":"Bright blue","group":"Palette"}
BBS_BLUE = (85, 85, 255)

# @skinlab {"type":"color","label":"Dark blue","group":"Palette"}
BBS_NAVY = (0, 0, 170)

# @skinlab {"type":"color","label":"Grey text","group":"Palette"}
BBS_GREY = (170, 170, 170)

# @skinlab {"type":"color","label":"White text","group":"Palette"}
BBS_WHITE = (255, 255, 255)

# @skinlab {"type":"color","label":"Yellow","group":"Palette"}
BBS_YELLOW = (255, 255, 85)

# @skinlab {"type":"color","label":"Bright magenta","group":"Palette"}
BBS_MAGENTA = (255, 85, 255)

# @skinlab {"type":"color","label":"Dark magenta","group":"Palette"}
BBS_PURPLE = (170, 0, 170)

# @skinlab {"type":"integer","label":"Header block rows","group":"Layout","min":1,"max":4,"step":1}
BBS_HEADER_ROWS = 3

# @skinlab {"type":"integer","label":"Side rail top","group":"Layout","min":1,"max":8,"step":1}
BBS_RAIL_TOP = 4

# @skinlab {"type":"integer","label":"Side rail bottom","group":"Layout","min":5,"max":14,"step":1}
BBS_RAIL_BOTTOM = 13

# @skinlab {"type":"integer","label":"Art rows","group":"Layout","min":1,"max":5,"step":1}
BBS_ART_ROWS = 5

# @skinlab {"type":"integer","label":"Cycled header cells","group":"Layout","min":0,"max":20,"step":1}
BBS_CYCLE_COLS = 20

# @skinlab {"type":"integer","label":"Colour cycle speed","group":"Motion","min":1,"max":32,"step":1}
BBS_CYCLE_SPEED = 8

# @skinlab {"type":"integer","label":"Lightbar speed","group":"Motion","min":1,"max":20,"step":1}
BBS_LIGHTBAR_SPEED = 5

# @skinlab {"type":"integer","label":"Lightbar strength","group":"Look","min":0,"max":160,"step":2}
BBS_LIGHTBAR_ALPHA = 52

# @skinlab {"type":"number","label":"Blink period","group":"Motion","min":0.05,"max":1,"step":0.05}
BBS_BLINK_PERIOD = 0.25


def _g_bbs_ansi_art(buf):
    w, h = buf.width, buf.height
    cols = 20
    rows = 15
    cw = max(1, w // cols)
    rh = max(1, h // rows)
    buf.pen = color.rgb(*BBS_BACKDROP)
    buf.clear()
    ramp = (255, 235, 200, 160, 120, 82, 48)
    for r in range(BBS_HEADER_ROWS):
        y = r * h // rows
        yh = (r + 1) * h // rows - y
        for c in range(cols):
            lv = r * 2 + (c + r) % 2
            if lv > 6:
                continue
            x = c * w // cols
            xw = (c + 1) * w // cols - x
            if r == 0:
                buf.pen = color.rgb(BBS_CYAN[0], BBS_CYAN[1], BBS_CYAN[2], ramp[lv])
            elif (c * 7 + r) % 9 == 0:
                buf.pen = color.rgb(BBS_BLUE[0], BBS_BLUE[1], BBS_BLUE[2], ramp[lv])
            else:
                buf.pen = color.rgb(BBS_TEAL[0], BBS_TEAL[1], BBS_TEAL[2], ramp[lv])
            buf.rectangle(x, y, xw, yh)
    y = 3 * h // rows
    buf.pen = color.rgb(*BBS_GREY)
    buf.rectangle(0, y, w, max(1, rh // 2))
    buf.pen = color.rgb(*BBS_WHITE)
    buf.rectangle(0, y, 3 * cw, max(1, rh // 2))
    buf.rectangle(w - 5 * cw, y, 2 * cw, max(1, rh // 2))
    for r in range(BBS_RAIL_TOP, BBS_RAIL_BOTTOM):
        y = r * h // rows
        yh = (r + 1) * h // rows - y
        buf.pen = color.rgb(*BBS_NAVY) if r % 2 else color.rgb(*BBS_BLUE)
        buf.rectangle(0, y, cw, yh)
        buf.rectangle(w - cw, y, cw, yh)
    for i in range(BBS_ART_ROWS):
        r = 8 + i
        y = r * h // rows
        yh = (r + 1) * h // rows - y
        buf.pen = color.rgb(*BBS_YELLOW)
        buf.rectangle(2 * w // cols, y + yh // 5, cw, max(1, yh * 3 // 5))
        buf.pen = color.rgb(*BBS_MAGENTA)
        buf.rectangle(3 * w // cols, y + yh // 5, cw, max(1, yh * 3 // 5))
        buf.pen = color.rgb(BBS_PURPLE[0], BBS_PURPLE[1], BBS_PURPLE[2], 200)
        buf.rectangle((16 - i) * w // cols, y, (3 + i) * cw, yh)
        buf.pen = color.rgb(*BBS_MAGENTA)
        buf.rectangle((16 - i) * w // cols, y, max(1, cw // 2), yh)
        n = 5 + (i * 5 + 3) % 8
        for k in range(n):
            c = 5 + k
            if c > 14 - i:
                break
            x = c * w // cols
            xw = (c + 1) * w // cols - x
            if (k + i) % 3:
                buf.pen = color.rgb(*BBS_GREY)
            else:
                buf.pen = color.rgb(*BBS_CYAN)
            buf.rectangle(x, y + yh // 4, max(1, xw - max(1, xw // 3)), max(1, yh // 2))
    y = 13 * h // rows
    buf.pen = color.rgb(*BBS_BLUE)
    buf.rectangle(0, y + rh // 2, w, max(1, rh // 2))
    y = 14 * h // rows
    buf.pen = color.rgb(*BBS_NAVY)
    buf.rectangle(0, y, w, h - y)
    for c in (1, 2, 4, 5, 6, 9, 12, 13, 16, 17, 18):
        x = c * w // cols
        xw = (c + 1) * w // cols - x
        buf.pen = color.rgb(*BBS_WHITE) if c % 3 else color.rgb(*BBS_CYAN)
        buf.rectangle(x, y + rh // 4, max(1, xw - 1), max(1, rh // 2))


def _g_bbs_ansi_art_a(dst, t):
    """The three things an ANSI screen could actually do, all at once.

    An ANSI artist had no pixels and no frames -- only 16 colours, a block
    character and two attributes -- so a moving board meant colour cycling the
    logo by rewriting its attributes every refresh, the blink bit on whatever
    was NEW, a lightbar walking the menu, and the cursor waiting at the
    prompt. That is the whole vocabulary and this uses all of it.

    The header is repainted OPAQUE rather than with alpha: `render` laid those
    cells down as translucent cyan over black, and translucent cyan drawn
    again over the same cells only adds, so the band would brighten instead of
    cycling. Scaling the colour by the same ramp gives the identical result
    that `render` gets, and replaces rather than accumulates.
    """
    w, h = dst.width, dst.height
    cols = 20
    rows = 15
    cw = max(1, w // cols)
    rh = max(1, h // rows)
    ramp = (255, 235, 200, 160, 120, 82, 48)
    k = int(t * BBS_CYCLE_SPEED)
    yh = h // rows
    for c in range(BBS_CYCLE_COLS):
        x = c * w // cols
        lv = ramp[(c + k) % len(ramp)]
        dst.pen = color.rgb(BBS_CYAN[0] * lv // 255, BBS_CYAN[1] * lv // 255,
                            BBS_CYAN[2] * lv // 255)
        dst.rectangle(x, 0, (c + 1) * w // cols - x, yh)
    sel = 8 + int(t * BBS_LIGHTBAR_SPEED) % BBS_ART_ROWS
    y = sel * h // rows
    dst.pen = color.rgb(BBS_WHITE[0], BBS_WHITE[1], BBS_WHITE[2], BBS_LIGHTBAR_ALPHA)
    dst.rectangle(cw, y, w - 2 * cw, (sel + 1) * h // rows - y)
    dst.pen = color.rgb(*BBS_YELLOW)
    dst.rectangle(cw, y, max(1, cw // 2), (sel + 1) * h // rows - y)
    if (t % BBS_BLINK_PERIOD) * 2 < BBS_BLINK_PERIOD:
        dst.pen = color.rgb(*BBS_WHITE)
        dst.rectangle(19 * w // cols, 14 * h // rows + rh // 4,
                      max(1, cw - 1), max(1, rh // 2))
    else:
        dst.pen = color.rgb(*BBS_BACKDROP)
        for i in range(BBS_ART_ROWS):
            ry = (8 + i) * h // rows
            rhh = (9 + i) * h // rows - ry
            dst.rectangle(2 * w // cols, ry + rhh // 5, cw, max(1, rhh * 3 // 5))
            dst.rectangle(3 * w // cols, ry + rhh // 5, cw, max(1, rhh * 3 // 5))


# @skinlab {"type":"color","label":"Sky base","group":"Palette"}
VHS_SKY = (14, 12, 44)

# @skinlab {"type":"color","label":"Sun halo","group":"Palette"}
VHS_HALO = (255, 200, 230)

# @skinlab {"type":"color","label":"Sun","group":"Palette"}
VHS_SUN = (255, 245, 250)

# @skinlab {"type":"color","label":"Horizon haze","group":"Palette"}
VHS_HAZE = (240, 210, 235)

# @skinlab {"type":"color","label":"Chroma magenta","group":"Palette"}
VHS_MAGENTA = (255, 60, 200)

# @skinlab {"type":"color","label":"Chroma cyan","group":"Palette"}
VHS_CYAN = (60, 240, 255)

# @skinlab {"type":"color","label":"On-screen display","group":"Palette"}
VHS_OSD = (255, 255, 255)

# @skinlab {"type":"color","label":"Tracking band","group":"Palette"}
VHS_BAND = (120, 130, 160)

# @skinlab {"type":"color","label":"Dropout streaks","group":"Palette"}
VHS_STREAK = (230, 235, 255)

# @skinlab {"type":"integer","label":"Scanline depth","group":"Look","min":0,"max":130,"step":5}
VHS_SCANLINE_ALPHA = 70

# @skinlab {"type":"integer","label":"Horizon height","group":"Layout","min":30,"max":85,"step":1}
VHS_HORIZON = 62

# @skinlab {"type":"integer","label":"Sun position","group":"Layout","min":12,"max":88,"step":1}
VHS_SUN_X = 66

# @skinlab {"type":"number","label":"Tracking band speed","group":"Motion","min":0.25,"max":4,"step":0.25}
VHS_BAND_SPEED = 1.0

# @skinlab {"type":"boolean","label":"Frame flash","group":"Motion"}
VHS_FLASH = True

# @skinlab {"type":"integer","label":"Dropout streaks","group":"Layout","min":0,"max":14,"step":1}
VHS_STREAKS = 9

# @skinlab {"type":"integer","label":"Head-switch tear","group":"Layout","min":0,"max":10,"step":1}
VHS_HEAD_NOISE = 7

# @skinlab {"type":"integer","label":"Chroma bleed lines","group":"Layout","min":0,"max":8,"step":1}
VHS_CHROMA_LINES = 4

# @skinlab {"type":"number","label":"Chroma wander","group":"Motion","min":0,"max":0.2,"step":0.01}
VHS_CHROMA_SWING = 0.06

# @skinlab {"type":"boolean","label":"Second band","group":"Motion"}
VHS_SECOND_BAND = True

# @skinlab {"type":"integer","label":"Tape counter speed","group":"Motion","min":1,"max":32,"step":1}
VHS_COUNTER_SPEED = 8


def _g_vhs_tracking(buf):
    w, h = buf.width, buf.height
    hz = h * VHS_HORIZON // 100
    for i in range(20):
        y = i * hz // 20
        v = 10 + i * 2
        buf.pen = color.rgb(VHS_SKY[0] + v // 2, VHS_SKY[1] + v // 3, VHS_SKY[2] + v)
        buf.rectangle(0, y, w, hz // 20 + 1)
    sx = w * VHS_SUN_X // 100
    sy = hz - h * 12 // 100
    for i in range(4):
        buf.pen = color.rgb(VHS_HALO[0], VHS_HALO[1], VHS_HALO[2], 26)
        buf.circle(sx, sy, max(2, h * (13 - i * 2) // 100))
    buf.pen = color.rgb(VHS_SUN[0], VHS_SUN[1], VHS_SUN[2], 190)
    buf.circle(sx, sy, max(1, h * 5 // 100))
    buf.pen = color.rgb(255, 120, 210, 60)
    buf.rectangle(sx, sy - max(1, h // 60), w - sx, max(2, h // 26))
    buf.pen = color.rgb(VHS_HAZE[0], VHS_HAZE[1], VHS_HAZE[2], 70)
    buf.rectangle(0, hz - h // 9, w, h // 9)
    buf.pen = color.rgb(255, 240, 250, 120)
    buf.rectangle(0, hz - h // 22, w, h // 22)
    buf.pen = color.rgb(VHS_MAGENTA[0], VHS_MAGENTA[1], VHS_MAGENTA[2], 90)
    buf.rectangle(w // 8, hz - h // 12, w, max(1, h // 40))
    buf.pen = color.rgb(VHS_CYAN[0], VHS_CYAN[1], VHS_CYAN[2], 80)
    buf.rectangle(0, hz + max(1, h // 60), w * 9 // 10, max(1, h // 50))
    for i in range(10):
        y = hz + i * (h - hz) // 10
        v = 26 - i * 2
        buf.pen = color.rgb(v, v - 6, v + 14)
        buf.rectangle(0, y, w, (h - hz) // 10 + 1)
    buf.pen = color.rgb(180, 180, 200, 60)
    for i in range(9):
        k = (i * 53 + 17) % 97
        buf.rectangle(k * w // 97, hz + h * (6 + i * 3) // 100, w // 4 + k // 3, max(1, h // 70))
    buf.pen = color.rgb(0, 0, 0, VHS_SCANLINE_ALPHA)
    step = max(2, h // 60)
    for y in range(0, h, step):
        buf.rectangle(0, y, w, max(1, step // 2))
    buf.pen = color.rgb(230, 230, 240, 170)
    for i in range(7):
        k = (i * 41 + 7) % 89
        buf.rectangle(k * w // 89, h - max(2, h // 22) + (i % 3), w // 6, max(1, h // 90))
    buf.pen = color.rgb(0, 0, 0, 200)
    buf.rectangle(0, h - max(1, h // 40), w, max(1, h // 40))
    ox = max(2, w // 16)
    oy = max(2, h // 12)
    ts = max(3, w // 22)
    buf.pen = color.rgb(0, 0, 0, 140)
    buf.triangle(ox + 1, oy + 1, ox + 1, oy + ts + 1, ox + ts + 1, oy + ts // 2 + 1)
    buf.pen = color.rgb(*VHS_OSD)
    buf.triangle(ox, oy, ox, oy + ts, ox + ts, oy + ts // 2)
    buf.rectangle(ox + ts * 2, oy + ts // 3, ts, max(1, ts // 3))
    buf.rectangle(ox + ts * 7 // 2, oy + ts // 3, ts * 2, max(1, ts // 3))


def _g_vhs_tracking_a(dst, t):
    """A tape the tracking never quite finds.

    One mechanism -- a drum spinning against a stretched ribbon -- produces
    all of it, so all of it moves off the same phase: the noise band climbing
    the frame with dropouts inside it, a weaker second band half a cycle
    behind, chroma sliding out from under the luma at the horizon, the
    head-switch tear the deck never manages to hide at the bottom of the
    picture, and the counter on the on-screen display ticking over.

    Everything here is one thin rectangle. Twenty small marks are cheaper than
    two big ones, and a tape defect is small marks by nature.
    """
    w, h = dst.width, dst.height
    bh = max(2, h // 9)
    y = int(h * 1.3 * (1.0 - (t * VHS_BAND_SPEED) % 1.0)) - h // 8
    dst.pen = color.rgb(VHS_BAND[0], VHS_BAND[1], VHS_BAND[2], 70)
    dst.rectangle(0, y, w, bh)
    dst.pen = color.rgb(20, 16, 40, 160)
    dst.rectangle(0, y + bh // 3, w, max(1, bh // 4))
    for i in range(VHS_STREAKS):
        k = (i * 37 + int(t * 200)) % 101
        dst.pen = color.rgb(VHS_STREAK[0], VHS_STREAK[1], VHS_STREAK[2], 200)
        dst.rectangle(k * w // 101, y + i * bh // VHS_STREAKS,
                      w // 5 + k // 4, max(1, h // 80))
    dst.pen = color.rgb(VHS_MAGENTA[0], VHS_MAGENTA[1], VHS_MAGENTA[2], 60)
    dst.rectangle(w // 12, y - max(1, h // 60), w, max(1, h // 60))
    dst.pen = color.rgb(VHS_CYAN[0], VHS_CYAN[1], VHS_CYAN[2], 50)
    dst.rectangle(0, y + bh, w * 11 // 12, max(1, h // 60))
    if VHS_SECOND_BAND:
        y2 = int(h * 1.3 * (1.0 - (t * VHS_BAND_SPEED + 0.5) % 1.0)) - h // 8
        dst.pen = color.rgb(VHS_BAND[0], VHS_BAND[1], VHS_BAND[2], 34)
        dst.rectangle(0, y2, w, max(2, bh // 2))
        dst.pen = color.rgb(VHS_STREAK[0], VHS_STREAK[1], VHS_STREAK[2], 110)
        dst.rectangle(w // 3, y2 + bh // 4, w // 3, max(1, h // 90))
    hz = h * VHS_HORIZON // 100
    for i in range(VHS_CHROMA_LINES):
        tint = VHS_MAGENTA if i % 2 else VHS_CYAN
        dst.pen = color.rgb(tint[0], tint[1], tint[2], 70)
        dst.rectangle(int(w * VHS_CHROMA_SWING
                          * math.sin(t * 2 * math.pi + i * 1.6)),
                      hz - h // 12 + i * max(1, h // 34), w, max(1, h // 60))
    jy = h - max(2, h // 16)
    for i in range(VHS_HEAD_NOISE):
        k = (i * 53 + int(t * 300)) % 97
        dst.pen = color.rgb(210, 214, 232, max(40, 160 - i * 14))
        dst.rectangle(k * w // 97, jy + (i % 3) * max(1, h // 90),
                      w // 4 + k // 3, max(1, h // 90))
    ox = max(2, w // 16)
    oy = max(2, h // 12)
    ts = max(3, w // 22)
    n = int(t * VHS_COUNTER_SPEED)
    for i in range(3):
        dst.pen = color.rgb(VHS_OSD[0], VHS_OSD[1], VHS_OSD[2], 210)
        dst.rectangle(ox + ts * 6 + i * ts, oy + ts // 3,
                      max(1, ts * (2 + (i * 29 + n * 7) % 5) // 8),
                      max(1, ts // 3))
    if VHS_FLASH and int(t * 12) % 5 == 0:
        dst.pen = color.rgb(VHS_OSD[0], VHS_OSD[1], VHS_OSD[2], 22)
        dst.rectangle(0, 0, w, h)


# @skinlab {"type":"color","label":"Paper","group":"Palette"}
WEDGE_PAPER = (236, 229, 212)

# @skinlab {"type":"color","label":"Ink","group":"Palette"}
WEDGE_INK = (20, 18, 22)

# @skinlab {"type":"color","label":"Wedge","group":"Palette"}
WEDGE_RED = (214, 46, 30)

# @skinlab {"type":"color","label":"Wedge shadow","group":"Palette"}
WEDGE_SHADOW = (110, 16, 12)

# @skinlab {"type":"number","label":"Ground shade","group":"Layout","min":0.5,"max":0.95,"step":0.02}
WEDGE_GROUND = 0.72

# @skinlab {"type":"number","label":"Disc across","group":"Layout","min":0.4,"max":1,"step":0.02}
WEDGE_DISC_X = 0.80

# @skinlab {"type":"number","label":"Disc down","group":"Layout","min":0.1,"max":0.7,"step":0.02}
WEDGE_DISC_Y = 0.42

# @skinlab {"type":"number","label":"Disc size","group":"Shape","min":0.2,"max":0.7,"step":0.02}
WEDGE_DISC_R = 0.46

# @skinlab {"type":"number","label":"Disc core","group":"Shape","min":0.03,"max":0.24,"step":0.01}
WEDGE_CORE_R = 0.09

# Both the wedge and its offset shadow read this, so the two stay welded.
# @skinlab {"type":"number","label":"Wedge reach","group":"Shape","min":0.5,"max":1.1,"step":0.02}
WEDGE_TIP_X = 0.92

# The fifth square starts past the right edge at both resolutions, so four is
# the honest top of this range.
# @skinlab {"type":"integer","label":"Square count","group":"Layout","min":1,"max":4,"step":1}
WEDGE_SQUARES = 4

# @skinlab {"type":"integer","label":"Square size","group":"Shape","min":1,"max":4,"step":1}
WEDGE_SQUARE = 3

# @skinlab {"type":"number","label":"Header rule","group":"Layout","min":0.1,"max":0.6,"step":0.02}
WEDGE_RULE_W = 0.30


def _g_red_wedge(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    buf.pen = color.rgb(*WEDGE_PAPER)
    buf.clear()
    buf.pen = color.rgb(WEDGE_INK[0], WEDGE_INK[1], WEDGE_INK[2], 22)
    buf.rectangle(0, int(h * WEDGE_GROUND), w, h - int(h * WEDGE_GROUND))
    buf.pen = color.rgb(*WEDGE_INK)
    buf.circle(int(w * WEDGE_DISC_X), int(h * WEDGE_DISC_Y), int(h * WEDGE_DISC_R))
    buf.pen = color.rgb(*WEDGE_SHADOW)
    buf.triangle(-u * 2, int(h * 0.18) + u, -u * 2, int(h * 0.98) + u,
                 int(w * WEDGE_TIP_X) + u, int(h * 0.58) + u)
    buf.pen = color.rgb(*WEDGE_RED)
    buf.triangle(-u * 2, int(h * 0.16), -u * 2, int(h * 0.96),
                 int(w * WEDGE_TIP_X), int(h * 0.56))
    buf.pen = color.rgb(*WEDGE_PAPER)
    buf.circle(int(w * WEDGE_DISC_X), int(h * WEDGE_DISC_Y),
               max(2, int(h * WEDGE_CORE_R)))
    buf.pen = color.rgb(*WEDGE_INK)
    buf.rectangle(int(w * 0.40), int(h * 0.84), int(w * 0.60), max(1, u // 2))
    for i in range(WEDGE_SQUARES):
        buf.rectangle(int(w * 0.52) + i * u * 5, int(h * 0.89),
                      u * WEDGE_SQUARE, u * WEDGE_SQUARE)
    buf.pen = color.rgb(*WEDGE_RED)
    buf.rectangle(int(w * 0.06), int(h * 0.05), int(w * WEDGE_RULE_W), max(1, u))
    buf.rectangle(int(w * 0.06), int(h * 0.05) + u * 2, int(w * 0.16), max(1, u // 2))


# @skinlab {"type":"color","label":"Dark ring","group":"Palette"}
RIPPLE_DARK = (22, 22, 28)

# @skinlab {"type":"color","label":"Light ring","group":"Palette"}
RIPPLE_LIGHT = (240, 234, 220)

# @skinlab {"type":"color","label":"Centre dot","group":"Palette"}
RIPPLE_DOT = (255, 198, 26)

# @skinlab {"type":"number","label":"Centre across","group":"Layout","min":0.3,"max":1.1,"step":0.02}
RIPPLE_CX = 0.80

# @skinlab {"type":"number","label":"Centre down","group":"Layout","min":0.3,"max":1.1,"step":0.02}
RIPPLE_CY = 0.84

# The rings grow geometrically until they leave the panel, so this is the cost
# ceiling rather than the ring count; lowering it crops the pattern back.
# @skinlab {"type":"integer","label":"Ring limit","group":"Layout","min":8,"max":24,"step":1}
RIPPLE_MAX_RINGS = 24

# OP RIPPLE is the catalogue's most expensive animator (7.019 ms per LORES
# frame), and every one of these is a filled circle drawn every frame.
# @skinlab {"type":"integer","label":"Moving rings","group":"Motion","min":2,"max":12,"step":1}
RIPPLE_ANIM_RINGS = 10

# @skinlab {"type":"integer","label":"Centre size","group":"Shape","min":1,"max":4,"step":1}
RIPPLE_CORE = 1

# @skinlab {"type":"number","label":"Ripple speed","group":"Motion","min":0.25,"max":4,"step":0.25}
RIPPLE_SPEED = 1.0

# @skinlab {"type":"boolean","label":"Ripple moves","group":"Motion"}
RIPPLE_MOVES = True

# @skinlab {"type":"number","label":"Header rule","group":"Layout","min":0.1,"max":0.8,"step":0.02}
RIPPLE_BAR_W = 0.44

# @skinlab {"type":"number","label":"Header height","group":"Layout","min":0.02,"max":0.4,"step":0.02}
RIPPLE_BAR_Y = 0.06


def _g_op_ripple(buf):
    import math
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    cx, cy = int(w * RIPPLE_CX), int(h * RIPPLE_CY)
    edge = math.sqrt(cx * cx + cy * cy) + u * 2
    r0 = float(max(2, u * RIPPLE_CORE))
    n = 1
    r = r0
    while r < edge and n < RIPPLE_MAX_RINGS:
        r *= 1.34
        n += 1
    buf.pen = color.rgb(*RIPPLE_DARK) if n % 2 else color.rgb(*RIPPLE_LIGHT)
    buf.clear()
    for i in range(n - 1, -1, -1):
        buf.pen = color.rgb(*RIPPLE_DARK) if i % 2 else color.rgb(*RIPPLE_LIGHT)
        buf.circle(cx, cy, int(r))
        r /= 1.34
    buf.pen = color.rgb(*RIPPLE_DOT)
    buf.circle(cx, cy, max(1, int(r0)))
    buf.rectangle(0, int(h * RIPPLE_BAR_Y), int(w * RIPPLE_BAR_W), max(1, u))
    buf.pen = color.rgb(*RIPPLE_DARK)
    buf.rectangle(0, int(h * RIPPLE_BAR_Y) + u * 2, int(w * 0.26), max(1, u // 2))


def _g_op_ripple_a(dst, t):
    import math
    if not RIPPLE_MOVES:
        return
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    cx, cy = int(w * RIPPLE_CX), int(h * RIPPLE_CY)
    edge = math.sqrt(cx * cx + cy * cy) + u * 2
    r0 = float(max(2, u * RIPPLE_CORE))
    n = 1
    r = r0
    while r < edge and n < RIPPLE_MAX_RINGS:
        r *= 1.34
        n += 1
    n = min(RIPPLE_ANIM_RINGS, n - 2)
    # 0.7956 is 1.34 * 1.34 - 1: one ring's worth of growth per loop, which is
    # what makes the wrap seamless. Both numbers stay literal for that reason.
    r = r0 * (1.0 + 0.7956 * ((t * RIPPLE_SPEED) % 1.0))
    for _ in range(n - 1):
        r *= 1.34
    for i in range(n - 1, -1, -1):
        dst.pen = color.rgb(*RIPPLE_DARK) if i % 2 else color.rgb(*RIPPLE_LIGHT)
        dst.circle(cx, cy, int(r))
        r /= 1.34
    dst.pen = color.rgb(*RIPPLE_DOT)
    dst.circle(cx, cy, max(1, int(r0)))


# @skinlab {"type":"color","label":"Night","group":"Palette"}
ECLIPSE_NIGHT = (18, 22, 46)

# @skinlab {"type":"color","label":"Sun","group":"Palette"}
ECLIPSE_SUN = (255, 74, 34)

# @skinlab {"type":"color","label":"Ground","group":"Palette"}
ECLIPSE_GROUND = (240, 234, 220)

# @skinlab {"type":"color","label":"Corner mark","group":"Palette"}
ECLIPSE_MARK = (255, 198, 60)

# @skinlab {"type":"color","label":"Corona","group":"Palette"}
ECLIPSE_CORONA = (255, 236, 200)

# @skinlab {"type":"number","label":"Sun across","group":"Layout","min":0.2,"max":1,"step":0.02}
ECLIPSE_SUN_X = 0.70

# The moon crosses at a fixed height, so the sun stays inside the band it can
# still be eclipsed in.
# @skinlab {"type":"number","label":"Sun height","group":"Layout","min":0.2,"max":0.45,"step":0.01}
ECLIPSE_SUN_Y = 0.32

# @skinlab {"type":"number","label":"Sun size","group":"Shape","min":0.2,"max":0.9,"step":0.02}
ECLIPSE_SUN_R = 0.56

# @skinlab {"type":"number","label":"Horizon height","group":"Layout","min":0.4,"max":0.9,"step":0.02}
ECLIPSE_HORIZON = 0.68

# @skinlab {"type":"integer","label":"Tower count","group":"Layout","min":2,"max":8,"step":1}
ECLIPSE_TOWERS = 6

# @skinlab {"type":"number","label":"Tower width","group":"Shape","min":0.03,"max":0.18,"step":0.01}
ECLIPSE_TOWER_W = 0.09

# @skinlab {"type":"number","label":"Tower spacing","group":"Layout","min":0.06,"max":0.24,"step":0.01}
ECLIPSE_TOWER_GAP = 0.14

# @skinlab {"type":"number","label":"Moon size","group":"Shape","min":0.12,"max":0.6,"step":0.02}
ECLIPSE_MOON_R = 0.34

# The moon used to appear at 0.16w already half over the sun and leave at the
# right edge, so the loop jumped once every four seconds. Starting it a moon's
# width off the left edge and running it a moon's width past the right one
# costs nothing and makes t = 1 land on t = 0 with the moon off the panel.
# @skinlab {"type":"number","label":"Moon entry","group":"Motion","min":-0.8,"max":0.2,"step":0.02}
ECLIPSE_MOON_START = -0.30

# @skinlab {"type":"number","label":"Moon travel","group":"Motion","min":0.6,"max":1.8,"step":0.05}
ECLIPSE_MOON_TRAVEL = 1.60

# @skinlab {"type":"color","label":"Stars","group":"Palette"}
ECLIPSE_STAR = (214, 226, 255)

# Stars come out as the sun goes in. They live in the strip of night sky the
# sun does not cover, which is the left third of the panel at both
# resolutions, and they are the cheapest thing on the screen -- a stroke
# square each, against two filled discs the size of the panel.
# @skinlab {"type":"integer","label":"Stars","group":"Details","min":0,"max":16,"step":1}
ECLIPSE_STARS = 12

# @skinlab {"type":"integer","label":"Limb flares","group":"Details","min":0,"max":8,"step":1}
ECLIPSE_FLARES = 6

# Whole beats per cycle, so the flicker joins itself at the wrap.
# @skinlab {"type":"integer","label":"Flare beat","group":"Motion","min":1,"max":6,"step":1}
ECLIPSE_FLARE_BEAT = 3


def _g_eclipse(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    buf.pen = color.rgb(*ECLIPSE_NIGHT)
    buf.clear()
    buf.pen = color.rgb(*ECLIPSE_SUN)
    buf.circle(int(w * ECLIPSE_SUN_X), int(h * ECLIPSE_SUN_Y), int(h * ECLIPSE_SUN_R))
    buf.pen = color.rgb(*ECLIPSE_GROUND)
    buf.rectangle(0, int(h * ECLIPSE_HORIZON), w, h - int(h * ECLIPSE_HORIZON))
    buf.pen = color.rgb(*ECLIPSE_NIGHT)
    buf.rectangle(0, int(h * ECLIPSE_HORIZON), w, max(1, u // 2))
    for i in range(ECLIPSE_TOWERS):
        buf.pen = (color.rgb(*ECLIPSE_SUN) if i % 2
                   else color.rgb(*ECLIPSE_NIGHT))
        bw = int(w * ECLIPSE_TOWER_W)
        buf.rectangle(int(w * 0.08) + i * int(w * ECLIPSE_TOWER_GAP),
                      h - u * (2 + (i * 3) % 7), bw, h)
    buf.pen = color.rgb(*ECLIPSE_MARK)
    buf.rectangle(int(w * 0.04), int(h * 0.08), max(1, u), int(h * 0.34))


def _g_eclipse_a(dst, t):
    """The transit, and what the transit does to the rest of the sky."""
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    s = _stroke(dst)
    r = int(h * ECLIPSE_MOON_R)
    sun_r = h * ECLIPSE_SUN_R
    sx, sy = w * ECLIPSE_SUN_X, h * ECLIPSE_SUN_Y
    mx = int(w * (ECLIPSE_MOON_START + ECLIPSE_MOON_TRAVEL * t))
    my = int(h * 0.30)
    # The sun flares whether or not anything is crossing it, so the picture is
    # never completely still. The arc is the part of the limb the ground and
    # the right edge leave visible.
    beat = ECLIPSE_FLARE_BEAT * t
    for k in range(ECLIPSE_FLARES):
        a = 3.1416 * (0.78 + 0.42 * (k + 0.5) / max(1, ECLIPSE_FLARES))
        lick = 0.55 + 0.45 * math.sin(6.2832 * (beat + ((k * 13) % 7) / 7.0))
        # A flare is a feature of the sun, not a hairline, so it is sized off
        # the composition unit; at _stroke() it was one pixel and invisible.
        fz = max(2, int(u * (0.4 + 0.7 * lick)))
        dst.pen = color.rgb(ECLIPSE_MARK[0], ECLIPSE_MARK[1], ECLIPSE_MARK[2],
                            140 + int(115 * lick))
        dst.rectangle(int(sx + math.cos(a) * sun_r) - fz // 2,
                      int(sy + math.sin(a) * sun_r) - fz // 2, fz, fz)
    gap = math.sqrt((mx - sx) * (mx - sx) + (my - sy) * (my - sy))
    cover = 1.0 - gap / sun_r
    if cover > 0.02:
        # 29 and 53: separate primes, and neither is one off a multiple of its
        # own extent at either resolution, which is what stops the scatter
        # collapsing into a stripe.
        span_x = max(1, int(w * 0.27))
        span_y = max(1, int(h * 0.62))
        dst.pen = color.rgb(ECLIPSE_STAR[0], ECLIPSE_STAR[1], ECLIPSE_STAR[2],
                            int(235 * min(1.0, cover)))
        for k in range(ECLIPSE_STARS):
            dst.rectangle((k * 29) % span_x, (k * 53 + 5) % span_y, s, s)
    if cover > 0.15:
        # Only once the moon is INSIDE the sun's disc. The old gate was the
        # moon's x alone, which lit a halo while it was still out over open
        # sky with nothing behind it to glow.
        dst.pen = color.rgb(*ECLIPSE_CORONA)
        dst.circle(mx - max(1, u // 2), my - max(1, u // 2), r + max(1, u // 2))
    dst.pen = color.rgb(*ECLIPSE_NIGHT)
    dst.circle(mx, my, r)


# @skinlab {"type":"color","label":"Paper","group":"Palette"}
MEMPHIS_PAPER = (246, 240, 228)

# @skinlab {"type":"color","label":"Ink","group":"Palette"}
MEMPHIS_INK = (26, 24, 28)

# @skinlab {"type":"color","label":"Pink","group":"Palette"}
MEMPHIS_PINK = (240, 64, 122)

# @skinlab {"type":"color","label":"Teal","group":"Palette"}
MEMPHIS_TEAL = (46, 208, 178)

# @skinlab {"type":"color","label":"Yellow","group":"Palette"}
MEMPHIS_YELLOW = (255, 198, 58)

# @skinlab {"type":"integer","label":"Checker size","group":"Shape","min":1,"max":5,"step":1}
MEMPHIS_CHECK = 2

# @skinlab {"type":"number","label":"Checker top","group":"Layout","min":0.55,"max":0.95,"step":0.02}
MEMPHIS_CHECK_TOP = 0.80

# @skinlab {"type":"number","label":"Ribbon width","group":"Shape","min":0.05,"max":0.3,"step":0.01}
MEMPHIS_RIBBON = 0.15

# @skinlab {"type":"number","label":"Ribbon at left","group":"Layout","min":0.28,"max":0.7,"step":0.02}
MEMPHIS_RIBBON_LEFT = 0.46

# @skinlab {"type":"number","label":"Ribbon at right","group":"Layout","min":0.05,"max":0.5,"step":0.02}
MEMPHIS_RIBBON_RIGHT = 0.18

# @skinlab {"type":"number","label":"Disc size","group":"Shape","min":0.1,"max":0.4,"step":0.02}
MEMPHIS_DISC_R = 0.24

# @skinlab {"type":"integer","label":"Stair steps","group":"Layout","min":2,"max":6,"step":1}
MEMPHIS_STEPS = 4

# Four is what the teal panel holds: a fifth slat is drawn below its bottom
# edge, on the paper.
# @skinlab {"type":"integer","label":"Blind slats","group":"Layout","min":1,"max":4,"step":1}
MEMPHIS_SLATS = 4

# @skinlab {"type":"integer","label":"Confetti","group":"Details","min":0,"max":28,"step":1}
MEMPHIS_CONFETTI = 16

# The printed confetti is the skin's own vocabulary, so the motion is more of
# it: loose pieces drifting through, spinning as they go. They ride two lanes,
# above and below the name band, because a dozen small shapes crossing the
# nickname is exactly the high-frequency detail that band is kept clear of.
# @skinlab {"type":"integer","label":"Drifting pieces","group":"Layout","min":0,"max":24,"step":1}
MEMPHIS_FLOAT = 16

# @skinlab {"type":"number","label":"Drift speed","group":"Motion","min":0.25,"max":4,"step":0.25}
MEMPHIS_FLOAT_SPEED = 1.0

# Whole turns per cycle. An integer is the point: a half-turn would leave the
# spin mid-flip at the wrap.
# @skinlab {"type":"integer","label":"Spins per cycle","group":"Motion","min":1,"max":6,"step":1}
MEMPHIS_SPIN = 2

# @skinlab {"type":"number","label":"Bob height","group":"Motion","min":0,"max":3,"step":0.1}
MEMPHIS_BOB = 1.2


def _g_memphis_blvd(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    buf.pen = color.rgb(*MEMPHIS_PAPER)
    buf.clear()
    cell = max(2, u * MEMPHIS_CHECK)
    buf.pen = color.rgb(*MEMPHIS_INK)
    row = 0
    y = int(h * MEMPHIS_CHECK_TOP)
    while y < h:
        x = -cell if row % 2 else 0
        while x < w:
            buf.rectangle(x, y, cell, cell)
            x += cell * 2
        y += cell
        row += 1
    th = int(h * MEMPHIS_RIBBON)
    buf.pen = color.rgb(*MEMPHIS_PINK)
    buf.triangle(int(-w * 0.1), int(h * MEMPHIS_RIBBON_LEFT),
                 int(w * 1.1), int(h * MEMPHIS_RIBBON_RIGHT),
                 int(w * 1.1), int(h * MEMPHIS_RIBBON_RIGHT) + th)
    buf.triangle(int(-w * 0.1), int(h * MEMPHIS_RIBBON_LEFT),
                 int(-w * 0.1), int(h * MEMPHIS_RIBBON_LEFT) + th,
                 int(w * 1.1), int(h * MEMPHIS_RIBBON_RIGHT) + th)
    buf.pen = color.rgb(*MEMPHIS_INK)
    buf.rectangle(0, int(h * 0.50), w, max(1, u // 2))
    buf.pen = color.rgb(*MEMPHIS_TEAL)
    buf.circle(int(w * 0.10), int(h * 0.72), int(h * MEMPHIS_DISC_R))
    buf.pen = color.rgb(*MEMPHIS_INK)
    buf.circle(int(w * 0.10), int(h * 0.72), max(1, int(h * 0.07)))
    buf.pen = color.rgb(*MEMPHIS_YELLOW)
    for i in range(MEMPHIS_STEPS):
        buf.rectangle(int(w * 0.34) + i * u * 5, int(h * 0.72) - i * u * 4,
                      u * 5, u * 4)
    buf.pen = color.rgb(*MEMPHIS_INK)
    for i in range(MEMPHIS_STEPS):
        buf.rectangle(int(w * 0.34) + i * u * 5, int(h * 0.72) - i * u * 4,
                      u * 5, max(1, u // 2))
    buf.pen = color.rgb(*MEMPHIS_TEAL)
    buf.rectangle(int(w * 0.70), int(h * 0.54), int(w * 0.26), int(h * 0.20))
    buf.pen = color.rgb(*MEMPHIS_INK)
    for i in range(MEMPHIS_SLATS):
        buf.rectangle(int(w * 0.70), int(h * 0.56) + i * max(2, u + u // 2),
                      int(w * 0.26), max(1, u // 2))
    for i in range(MEMPHIS_CONFETTI):
        px = (i * 37 + 9) % 100
        py = (i * 43 + 5) % 15
        x = px * w // 100
        y = py * h // 100
        k = i % 4
        if k == 0:
            buf.pen = color.rgb(*MEMPHIS_PINK)
            buf.circle(x, y, max(1, u))
        elif k == 1:
            buf.pen = color.rgb(*MEMPHIS_INK)
            buf.rectangle(x, y, u * 3, max(1, u // 2))
        elif k == 2:
            buf.pen = color.rgb(*MEMPHIS_TEAL)
            buf.triangle(x, y + u * 2, x + u * 2, y - u, x + u * 4, y + u * 2)
        else:
            buf.pen = color.rgb(*MEMPHIS_YELLOW)
            buf.rectangle(x, y, u * 2, u * 2)


def _g_memphis_blvd_a(dst, t):
    """Loose confetti crossing the boulevard, spinning as it goes."""
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    tints = (MEMPHIS_PINK, MEMPHIS_TEAL, MEMPHIS_YELLOW, MEMPHIS_INK)
    tt = t * MEMPHIS_FLOAT_SPEED
    span = w + u * 8
    for k in range(MEMPHIS_FLOAT):
        # A different prime per field: 31 spaces the launches, 17 and 23 place
        # the lanes, so nothing lines up into a visible column.
        p = (tt + ((k * 31) % 97) / 97.0) % 1.0
        x = int(-u * 4 + span * p)
        lane = ((k * 17) % 11) / 100.0
        y = int(h * (0.02 + lane) if k % 2 else h * (0.64 + lane))
        y += int(u * MEMPHIS_BOB
                 * math.sin(6.2832 * (MEMPHIS_SPIN * t + ((k * 23) % 9) / 9.0)))
        tint = tints[k % 4]
        dst.pen = color.rgb(tint[0], tint[1], tint[2])
        if k % 4 == 0:
            dst.circle(x, y, max(1, u))
        elif k % 4 == 1:
            # The flip: the square narrows to an edge and opens out again,
            # which is a spin drawn with one rectangle.
            flip = abs(math.cos(3.1416 * (MEMPHIS_SPIN * t + k * 0.11)))
            dst.rectangle(x, y, max(1, int(u * 2 * flip)), u * 2)
        elif k % 4 == 2:
            dst.triangle(x, y + u * 2, x + u * 2, y - u, x + u * 4, y + u * 2)
        else:
            dst.rectangle(x, y, u * 3, max(1, u // 2))


# @skinlab {"type":"color","label":"Paper","group":"Palette"}
ISO_PAPER = (238, 232, 218)

# @skinlab {"type":"color","label":"Banner","group":"Palette"}
ISO_BANNER = (255, 198, 60)

# @skinlab {"type":"color","label":"Ink","group":"Palette"}
ISO_INK = (24, 22, 26)

# @skinlab {"type":"color","label":"Block top","group":"Palette"}
ISO_TOP = (255, 128, 70)

# @skinlab {"type":"color","label":"Block left","group":"Palette"}
ISO_LEFT = (214, 46, 30)

# @skinlab {"type":"color","label":"Block right","group":"Palette"}
ISO_RIGHT = (124, 20, 14)

# @skinlab {"type":"color","label":"Odd block top","group":"Palette"}
ISO_TOP_ALT = (96, 148, 240)

# @skinlab {"type":"color","label":"Odd block left","group":"Palette"}
ISO_LEFT_ALT = (40, 74, 184)

# @skinlab {"type":"color","label":"Odd block right","group":"Palette"}
ISO_RIGHT_ALT = (20, 38, 112)

# @skinlab {"type":"number","label":"Banner depth","group":"Layout","min":0.1,"max":0.45,"step":0.01}
ISO_BANNER_H = 0.22

# @skinlab {"type":"number","label":"Block width","group":"Shape","min":0.08,"max":0.24,"step":0.01}
ISO_BLOCK = 0.15

# @skinlab {"type":"number","label":"Storey height","group":"Shape","min":0.3,"max":1.2,"step":0.02}
ISO_STOREY = 0.72

# @skinlab {"type":"number","label":"Stack across","group":"Layout","min":0.2,"max":0.8,"step":0.02}
ISO_ORIGIN_X = 0.38

# @skinlab {"type":"number","label":"Stack down","group":"Layout","min":0.45,"max":0.9,"step":0.02}
ISO_ORIGIN_Y = 0.66


def _g_iso_stack(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    buf.pen = color.rgb(*ISO_PAPER)
    buf.clear()
    buf.pen = color.rgb(*ISO_BANNER)
    buf.rectangle(0, 0, w, int(h * ISO_BANNER_H))
    buf.pen = color.rgb(*ISO_INK)
    buf.rectangle(0, int(h * ISO_BANNER_H), w, max(1, u // 2))
    buf.rectangle(int(w * 0.74), int(h * 0.04), int(w * 0.14), int(h * 0.14))
    a = max(2, int(w * ISO_BLOCK))
    b = max(1, a // 2)
    d = max(2, int(a * ISO_STOREY))
    ox, oy = int(w * ISO_ORIGIN_X), int(h * ISO_ORIGIN_Y)
    cols = ((0, 0, 1), (1, 0, 2), (0, 1, 2), (2, 0, 1), (1, 1, 3),
            (0, 2, 1), (2, 1, 1), (1, 2, 2), (2, 2, 1))
    tops = (ISO_TOP, ISO_TOP_ALT)
    lefts = (ISO_LEFT, ISO_LEFT_ALT)
    rights = (ISO_RIGHT, ISO_RIGHT_ALT)
    buf.pen = color.rgb(ISO_INK[0], ISO_INK[1], ISO_INK[2], 30)
    buf.triangle(ox - a * 3, oy + b * 2, ox, oy + b * 5, ox + a * 3, oy + b * 2)
    buf.triangle(ox - a * 3, oy + b * 2, ox, oy - b, ox + a * 3, oy + b * 2)
    for c, r, lev in cols:
        sx = ox + (c - r) * a
        sy = oy + (c + r) * b - lev * d
        k = 1 if (c == 1 and r == 1) else 0
        buf.pen = color.rgb(rights[k][0], rights[k][1], rights[k][2])
        buf.triangle(sx + a, sy, sx, sy + b, sx, sy + b + lev * d)
        buf.triangle(sx + a, sy, sx + a, sy + lev * d, sx, sy + b + lev * d)
        buf.pen = color.rgb(lefts[k][0], lefts[k][1], lefts[k][2])
        buf.triangle(sx - a, sy, sx, sy + b, sx, sy + b + lev * d)
        buf.triangle(sx - a, sy, sx - a, sy + lev * d, sx, sy + b + lev * d)
        buf.pen = color.rgb(tops[k][0], tops[k][1], tops[k][2])
        buf.triangle(sx, sy - b, sx + a, sy, sx, sy + b)
        buf.triangle(sx, sy - b, sx - a, sy, sx, sy + b)


# @skinlab {"type":"color","label":"Paper","group":"Palette"}
DOT_PAPER = (240, 236, 226)

# @skinlab {"type":"color","label":"Dot ink","group":"Palette"}
DOT_INK = (22, 20, 26)

# @skinlab {"type":"color","label":"Accent","group":"Palette"}
DOT_ACCENT = (38, 74, 208)

# Every extra column is another row AND another column of filled circles, so
# the top of this range is where the render stays affordable.
# @skinlab {"type":"integer","label":"Dot columns","group":"Layout","min":6,"max":16,"step":1}
DOT_GRID = 12

# @skinlab {"type":"number","label":"Growth across","group":"Shape","min":0,"max":1.4,"step":0.05}
DOT_SPREAD_X = 0.55

# @skinlab {"type":"number","label":"Growth down","group":"Shape","min":0,"max":1.4,"step":0.05}
DOT_SPREAD_Y = 0.75

# @skinlab {"type":"number","label":"Dot size","group":"Shape","min":0.3,"max":1.1,"step":0.05}
DOT_SIZE = 0.80

# @skinlab {"type":"number","label":"Slash width","group":"Shape","min":0.06,"max":0.4,"step":0.02}
DOT_SLASH = 0.20

# @skinlab {"type":"number","label":"Slash at left","group":"Layout","min":0.3,"max":0.95,"step":0.02}
DOT_SLASH_LEFT = 0.60

# @skinlab {"type":"number","label":"Slash at right","group":"Layout","min":0.02,"max":0.6,"step":0.02}
DOT_SLASH_RIGHT = 0.16

# @skinlab {"type":"number","label":"Blue disc size","group":"Shape","min":0.05,"max":0.3,"step":0.01}
DOT_BADGE_R = 0.14

# @skinlab {"type":"number","label":"Sweep speed","group":"Motion","min":0.25,"max":4,"step":0.25}
DOT_SWEEP_SPEED = 1.0

# The name says shock, so what travels is a shock: a band of dots swollen past
# their printed size with the accent colour on its leading edge. Depth is how
# many diagonals deep the band is, and it is the whole cost -- one diagonal is
# eleven dots at either resolution.
# @skinlab {"type":"integer","label":"Wave depth","group":"Motion","min":1,"max":3,"step":1}
DOT_WAVE_DEPTH = 3

# @skinlab {"type":"number","label":"Wave swell","group":"Shape","min":0,"max":0.6,"step":0.05}
DOT_SWELL = 0.30


def _g_dot_shock(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    step = max(2, w // DOT_GRID)
    buf.pen = color.rgb(*DOT_PAPER)
    buf.clear()
    cols = w // step + 1
    rows = h // step + 1
    for j in range(rows + 1):
        for i in range(cols + 1):
            f = ((i * 1.0 / max(1, cols)) * DOT_SPREAD_X
                 + (j * 1.0 / max(1, rows)) * DOT_SPREAD_Y)
            rad = int(f * step * DOT_SIZE)
            if rad < 1:
                continue
            buf.pen = color.rgb(*DOT_INK)
            buf.circle(i * step + step // 2, j * step + step // 2, rad)
    slash = int(h * DOT_SLASH)
    buf.pen = color.rgb(*DOT_PAPER)
    buf.triangle(int(w * -0.1), int(h * DOT_SLASH_LEFT),
                 int(w * 1.1), int(h * DOT_SLASH_RIGHT),
                 int(w * 1.1), int(h * DOT_SLASH_RIGHT) + slash)
    buf.triangle(int(w * -0.1), int(h * DOT_SLASH_LEFT),
                 int(w * -0.1), int(h * DOT_SLASH_LEFT) + slash,
                 int(w * 1.1), int(h * DOT_SLASH_RIGHT) + slash)
    buf.pen = color.rgb(*DOT_ACCENT)
    buf.circle(int(w * 0.16), int(h * 0.22), int(h * DOT_BADGE_R))
    buf.pen = color.rgb(*DOT_INK)
    buf.rectangle(int(w * 0.05), int(h * 0.06), max(1, u // 2), int(h * 0.34))


def _g_dot_shock_a(dst, t):
    """A shock crossing the halftone: dots swell, the crest takes the accent.

    A dot can only be drawn over, never shrunk back, so the wave is made of
    dots larger than the printed ones underneath. It passes BEHIND the paper
    slash, which is the composition's one clean edge and the reason the skin
    is not just a field of dots.
    """
    w, h = dst.width, dst.height
    step = max(2, w // DOT_GRID)
    cols = w // step + 1
    rows = h // step + 1
    lead = int(((t * DOT_SWEEP_SPEED) % 1.0) * (cols + rows + 6)) - 3
    slash = h * DOT_SLASH
    left, right = h * DOT_SLASH_LEFT, h * DOT_SLASH_RIGHT
    for d in range(DOT_WAVE_DEPTH):
        swell = DOT_SWELL * step * (1.0 - d * 0.7 / DOT_WAVE_DEPTH)
        for j in range(rows + 1):
            i = lead - d - j
            if i < 0 or i > cols:
                continue
            x = i * step + step // 2
            y = j * step + step // 2
            f = ((i * 1.0 / max(1, cols)) * DOT_SPREAD_X
                 + (j * 1.0 / max(1, rows)) * DOT_SPREAD_Y)
            rad = int(f * step * DOT_SIZE + swell) + 1
            edge = left + (right - left) * (x + w * 0.1) / (w * 1.2)
            if edge - rad <= y <= edge + slash + rad:
                continue                  # the slash is printed over the top
            dst.pen = (color.rgb(*DOT_ACCENT) if d == 0
                       else color.rgb(*DOT_INK))
            dst.circle(x, y, rad)


# @skinlab {"type":"color","label":"Paper","group":"Palette"}
VANISH_PAPER = (238, 231, 214)

# @skinlab {"type":"color","label":"Dark ray","group":"Palette"}
VANISH_INK = (28, 26, 34)

# @skinlab {"type":"color","label":"Gold ray","group":"Palette"}
VANISH_GOLD = (226, 152, 30)

# @skinlab {"type":"color","label":"Accent","group":"Palette"}
VANISH_RED = (232, 60, 40)

# The rays run gold, dark, gap, so the pattern only closes on a multiple of
# three; the step keeps the slider on those.
# @skinlab {"type":"integer","label":"Ray count","group":"Layout","min":6,"max":30,"step":3}
VANISH_RAYS = 18

# @skinlab {"type":"number","label":"Ray twist","group":"Layout","min":0,"max":1,"step":0.05}
VANISH_TWIST = 0.16

# @skinlab {"type":"number","label":"Vanishing point across","group":"Layout","min":0,"max":0.6,"step":0.02}
VANISH_X = 0.16

# @skinlab {"type":"number","label":"Vanishing point down","group":"Layout","min":0.4,"max":1,"step":0.02}
VANISH_Y = 0.78

# @skinlab {"type":"number","label":"Ground line","group":"Layout","min":0.55,"max":0.95,"step":0.02}
VANISH_GROUND = 0.82

# @skinlab {"type":"number","label":"Hub size","group":"Shape","min":0.04,"max":0.25,"step":0.01}
VANISH_HUB = 0.11

# Kept under the hub it is punched out of: at 0.12 the paper core swallows the
# red ring entirely and the vanishing point stops reading as one.
# @skinlab {"type":"number","label":"Hub core","group":"Shape","min":0.02,"max":0.09,"step":0.005}
VANISH_HUB_CORE = 0.055

# @skinlab {"type":"number","label":"Blade width","group":"Motion","min":0.02,"max":0.3,"step":0.01}
VANISH_BLADE = 0.09

# @skinlab {"type":"number","label":"Sweep speed","group":"Motion","min":0.25,"max":4,"step":0.25}
VANISH_SPEED = 1.0

# @skinlab {"type":"integer","label":"Blades","group":"Motion","min":1,"max":4,"step":1}
VANISH_BLADES = 2

# The point of a vanishing point is that things come out of it. Sparks running
# outward along the rays grow as they travel, which is the perspective the
# rays already draw, and each one dies exactly where its own ray leaves the
# panel rather than at some shared radius most rays never reach.
# @skinlab {"type":"integer","label":"Sparks","group":"Layout","min":0,"max":24,"step":1}
VANISH_SPARKS = 20

# @skinlab {"type":"number","label":"Spark speed","group":"Motion","min":0.25,"max":4,"step":0.25}
VANISH_SPARK_SPEED = 1.0


def _g_vanish_point(buf):
    import math
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    vx, vy = int(w * VANISH_X), int(h * VANISH_Y)
    R = (w + h) * 2
    buf.pen = color.rgb(*VANISH_PAPER)
    buf.clear()
    for k in range(VANISH_RAYS):
        if k % 3 == 2:
            continue
        buf.pen = color.rgb(*VANISH_INK) if k % 3 else color.rgb(*VANISH_GOLD)
        a0 = 2.0 * math.pi * k / VANISH_RAYS + VANISH_TWIST
        a1 = 2.0 * math.pi * (k + 1) / VANISH_RAYS + VANISH_TWIST
        buf.triangle(vx, vy,
                     int(vx + math.cos(a0) * R), int(vy + math.sin(a0) * R),
                     int(vx + math.cos(a1) * R), int(vy + math.sin(a1) * R))
    buf.pen = color.rgb(*VANISH_PAPER)
    buf.rectangle(0, int(h * VANISH_GROUND), w, h - int(h * VANISH_GROUND))
    buf.pen = color.rgb(*VANISH_RED)
    buf.rectangle(0, int(h * VANISH_GROUND), w, max(1, u))
    buf.circle(vx, vy, int(h * VANISH_HUB))
    buf.pen = color.rgb(*VANISH_PAPER)
    buf.circle(vx, vy, int(h * VANISH_HUB_CORE))
    buf.pen = color.rgb(*VANISH_INK)
    buf.rectangle(int(w * 0.62), int(h * 0.88), int(w * 0.30), u * 2)


def _g_vanish_point_a(dst, t):
    import math
    w, h = dst.width, dst.height
    s = _stroke(dst)
    vx, vy = int(w * VANISH_X), int(h * VANISH_Y)
    R = (w + h) * 2
    a = 2.0 * math.pi * ((t * VANISH_SPEED) % 1.0)
    for k in range(VANISH_BLADES):
        ang = a + k * 2.0 * math.pi / VANISH_BLADES
        dst.pen = color.rgb(*VANISH_RED)
        dst.triangle(vx, vy,
                     int(vx + math.cos(ang - VANISH_BLADE) * R),
                     int(vy + math.sin(ang - VANISH_BLADE) * R),
                     int(vx + math.cos(ang + VANISH_BLADE) * R),
                     int(vy + math.sin(ang + VANISH_BLADE) * R))
    sparks = max(1, VANISH_SPARKS)
    # The vanishing point sits low and left, so only the rays leaving it
    # UPWARD have any panel to cross; the rest are under the ground line the
    # render already covers with paper. Sparks are put on that upper half
    # deliberately rather than scattered over all of them and then thrown away.
    upper = max(1, VANISH_RAYS - VANISH_RAYS // 2)
    tt = (t * VANISH_SPARK_SPEED) % 1.0
    for k in range(VANISH_SPARKS):
        # 5 picks the ray, 13 the launch: two primes, so the sparks neither
        # bunch on one ray nor leave the hub in a ring.
        m = VANISH_RAYS // 2 + (k * 5) % upper
        ang = 2.0 * math.pi * (m + 0.5) / VANISH_RAYS + VANISH_TWIST
        ca, sa = math.cos(ang), math.sin(ang)
        reach = -vy / sa if sa < -0.001 else (w + h) * 2.0
        if ca > 0.001:
            reach = min(reach, (w - vx) / ca)
        elif ca < -0.001:
            reach = min(reach, -vx / ca)
        p = (tt + ((k * 13) % sparks) / float(sparks)) % 1.0
        x = int(vx + ca * reach * p)
        y = int(vy + sa * reach * p)
        if x < 0 or x > w or y < 0 or y > h:
            continue
        # Nearer means bigger, the same lie the rays tell.
        sz = max(s, int(s * (1.0 + 3.0 * p)))
        dst.pen = color.rgb(*VANISH_RED)
        dst.rectangle(x - sz // 2, y - sz // 2, sz, sz)
    dst.pen = color.rgb(*VANISH_PAPER)
    dst.circle(vx, vy, int(h * VANISH_HUB_CORE))


# @skinlab {"type":"color","label":"Nearest frame","group":"Palette"}
TUNNEL_TINT_1 = (244, 240, 226)

# @skinlab {"type":"color","label":"Second frame","group":"Palette"}
TUNNEL_TINT_2 = (122, 226, 206)

# @skinlab {"type":"color","label":"Third frame","group":"Palette"}
TUNNEL_TINT_3 = (36, 168, 190)

# @skinlab {"type":"color","label":"Fourth frame","group":"Palette"}
TUNNEL_TINT_4 = (30, 92, 194)

# @skinlab {"type":"color","label":"Fifth frame","group":"Palette"}
TUNNEL_TINT_5 = (26, 42, 116)

# @skinlab {"type":"color","label":"Deepest frame","group":"Palette"}
TUNNEL_TINT_6 = (14, 16, 38)

# @skinlab {"type":"color","label":"Corner shade","group":"Palette"}
TUNNEL_SHADE = (8, 10, 26)

# @skinlab {"type":"color","label":"Rushing frame","group":"Palette"}
TUNNEL_GLOW = (255, 250, 236)

# @skinlab {"type":"integer","label":"Tunnel depth","group":"Layout","min":4,"max":16,"step":1}
TUNNEL_DEPTH = 10

# @skinlab {"type":"number","label":"Tunnel across","group":"Layout","min":0.2,"max":1,"step":0.02}
TUNNEL_VX = 0.70

# @skinlab {"type":"number","label":"Tunnel down","group":"Layout","min":0.2,"max":1,"step":0.02}
TUNNEL_VY = 0.66

# @skinlab {"type":"number","label":"Frame spread","group":"Shape","min":0.9,"max":1.8,"step":0.02}
TUNNEL_SPREAD = 1.24

# @skinlab {"type":"number","label":"Rush speed","group":"Motion","min":0.25,"max":4,"step":0.25}
TUNNEL_SPEED = 1.0

# One frame rushing out of the vanishing point read as a single object moving.
# A train of them, evenly spaced around the cycle, reads as the tunnel itself
# going past -- and it stays cheap because a frame is four thin rectangles,
# not a filled plate.
# @skinlab {"type":"integer","label":"Frames in flight","group":"Motion","min":1,"max":8,"step":1}
TUNNEL_RUSH = 6

# @skinlab {"type":"boolean","label":"Emitter pulses","group":"Motion"}
TUNNEL_CORE = True


def _g_square_tunnel(buf):
    import math
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    tx, ty = w * TUNNEL_VX, h * TUNNEL_VY
    tints = (TUNNEL_TINT_1, TUNNEL_TINT_2, TUNNEL_TINT_3,
             TUNNEL_TINT_4, TUNNEL_TINT_5, TUNNEL_TINT_6)
    buf.pen = color.rgb(*TUNNEL_TINT_6)
    buf.clear()
    for i in range(TUNNEL_DEPTH):
        f = 1.0 - i / TUNNEL_DEPTH
        k = f * math.sqrt(f)
        rw = w * TUNNEL_SPREAD * k
        rh = h * TUNNEL_SPREAD * k
        cx = tx + (w * 0.5 - tx) * k
        cy = ty + (h * 0.5 - ty) * k
        c = tints[i % len(tints)]
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(int(cx - rw / 2), int(cy - rh / 2), int(rw), int(rh))
    buf.pen = color.rgb(TUNNEL_SHADE[0], TUNNEL_SHADE[1], TUNNEL_SHADE[2], 90)
    buf.triangle(0, 0, w, 0, 0, h)
    buf.pen = color.rgb(*TUNNEL_TINT_1)
    buf.rectangle(0, int(h * 0.90), int(w * 0.34), max(1, u // 2))


def _g_square_tunnel_a(dst, t):
    """A train of frames leaving the vanishing point and passing the wearer.

    Each frame is one cycle of the same growth curve, offset by a fixed share
    of the loop, so the one that leaves the panel at t = 1 is replaced by the
    one born at t = 0 and the join is invisible. Frames brighten as they come,
    which is the only cue that says approaching rather than expanding.
    """
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    tx, ty = w * TUNNEL_VX, h * TUNNEL_VY
    tt = (t * TUNNEL_SPEED) % 1.0
    if TUNNEL_CORE:
        cz = max(1, u // 2)
        dst.pen = color.rgb(TUNNEL_GLOW[0], TUNNEL_GLOW[1], TUNNEL_GLOW[2],
                            110 + int(145 * (1.0 - (tt * TUNNEL_RUSH) % 1.0)))
        dst.rectangle(int(tx) - cz, int(ty) - cz, cz * 2, cz * 2)
    for j in range(TUNNEL_RUSH):
        p = (tt + j * 1.0 / TUNNEL_RUSH) % 1.0
        k = 0.10 + 0.92 * p * p
        rw = w * TUNNEL_SPREAD * k
        rh = h * TUNNEL_SPREAD * k
        cx = tx + (w * 0.5 - tx) * k
        cy = ty + (h * 0.5 - ty) * k
        x0, y0 = int(cx - rw / 2), int(cy - rh / 2)
        th = max(1, int(u * 0.6 + u * k))
        if x0 + th <= 0 and y0 + th <= 0 and x0 + rw - th >= w and y0 + rh - th >= h:
            continue                      # the frame has passed the panel
        dst.pen = color.rgb(TUNNEL_GLOW[0], TUNNEL_GLOW[1], TUNNEL_GLOW[2],
                            70 + int(185 * p))
        dst.rectangle(x0, y0, int(rw), th)
        dst.rectangle(x0, int(y0 + rh) - th, int(rw), th)
        dst.rectangle(x0, y0, th, int(rh))
        dst.rectangle(int(x0 + rw) - th, y0, th, int(rh))


# @skinlab {"type":"color","label":"Paper","group":"Palette"}
GRID_PAPER = (238, 233, 220)

# @skinlab {"type":"color","label":"Ink","group":"Palette"}
GRID_INK = (28, 26, 32)

# @skinlab {"type":"color","label":"Slash","group":"Palette"}
GRID_SLASH = (224, 48, 34)

# @skinlab {"type":"integer","label":"Grid columns","group":"Layout","min":3,"max":16,"step":1}
GRID_COLUMNS = 9

# @skinlab {"type":"integer","label":"Grid rows","group":"Layout","min":2,"max":12,"step":1}
GRID_ROWS = 7

# @skinlab {"type":"number","label":"Block top","group":"Layout","min":0.3,"max":0.85,"step":0.02}
GRID_BLOCK_Y = 0.56

# @skinlab {"type":"number","label":"Block width","group":"Shape","min":0.12,"max":0.6,"step":0.02}
GRID_BLOCK_W = 0.34

# Above ~0.13 the paper-coloured hole spills over the top edge of the block it
# is punched out of, which reads as a smudge rather than a hole.
# @skinlab {"type":"number","label":"Punched hole","group":"Shape","min":0.03,"max":0.13,"step":0.01}
GRID_HOLE_R = 0.08

# @skinlab {"type":"number","label":"Slash width","group":"Shape","min":0.05,"max":0.35,"step":0.01}
GRID_SLASH_TH = 0.17

# @skinlab {"type":"number","label":"Slash at left","group":"Layout","min":0.4,"max":1,"step":0.02}
GRID_SLASH_LEFT = 0.96

# @skinlab {"type":"number","label":"Slash at right","group":"Layout","min":0.02,"max":0.6,"step":0.02}
GRID_SLASH_RIGHT = 0.12

# @skinlab {"type":"integer","label":"Chip size","group":"Shape","min":1,"max":7,"step":1}
GRID_CHIP = 3


def _g_grid_break(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    lw = max(1, u // 3)
    buf.pen = color.rgb(*GRID_PAPER)
    buf.clear()
    buf.pen = color.rgb(GRID_INK[0], GRID_INK[1], GRID_INK[2], 130)
    for i in range(1, GRID_COLUMNS):
        buf.rectangle(i * w // GRID_COLUMNS, 0, lw, h)
    for j in range(1, GRID_ROWS):
        buf.rectangle(0, j * h // GRID_ROWS, w, lw)
    buf.pen = color.rgb(*GRID_INK)
    buf.rectangle(0, int(h * GRID_BLOCK_Y), int(w * GRID_BLOCK_W),
                  h - int(h * GRID_BLOCK_Y))
    buf.pen = color.rgb(*GRID_PAPER)
    buf.circle(int(w * 0.15), int(h * 0.65), int(h * GRID_HOLE_R))
    th = int(h * GRID_SLASH_TH)
    buf.pen = color.rgb(*GRID_SLASH)
    buf.triangle(int(-w * 0.2), int(h * GRID_SLASH_LEFT),
                 int(w * 1.2), int(h * GRID_SLASH_RIGHT),
                 int(w * 1.2), int(h * GRID_SLASH_RIGHT) + th)
    buf.triangle(int(-w * 0.2), int(h * GRID_SLASH_LEFT),
                 int(-w * 0.2), int(h * GRID_SLASH_LEFT) + th,
                 int(w * 1.2), int(h * GRID_SLASH_RIGHT) + th)
    buf.pen = color.rgb(*GRID_INK)
    buf.rectangle(w - int(w * 0.22), 0, int(w * 0.22), int(h * 0.16))
    buf.pen = color.rgb(*GRID_SLASH)
    buf.rectangle(int(w * 0.40), int(h * 0.86), u * GRID_CHIP, u * GRID_CHIP)


# @skinlab {"type":"number","label":"Waterline","group":"Layout","min":0.56,"max":0.74,"step":0.01}
RIDGE_LAKE = 0.62

# @skinlab {"type":"color","label":"Sun halo","group":"Palette"}
RIDGE_GLOW = (255, 110, 60)

# @skinlab {"type":"color","label":"Sun","group":"Palette"}
RIDGE_SUN = (255, 190, 84)

# @skinlab {"type":"color","label":"Sun core","group":"Palette"}
RIDGE_SUN_CORE = (255, 234, 158)

# @skinlab {"type":"number","label":"Sun size","group":"Layout","min":0.12,"max":0.40,"step":0.01}
RIDGE_SUN_R = 0.26

# @skinlab {"type":"color","label":"Near ripples","group":"Palette"}
RIDGE_RIPPLE = (38, 18, 44)

# @skinlab {"type":"color","label":"Sun path","group":"Palette"}
RIDGE_PATH = (255, 212, 146)

# @skinlab {"type":"integer","label":"Sun path bars","group":"Layout","min":1,"max":12,"step":1}
RIDGE_PATH_BARS = 7

# @skinlab {"type":"color","label":"Shoreline","group":"Palette"}
RIDGE_SHORE = (255, 226, 190)

# @skinlab {"type":"color","label":"Birds","group":"Palette"}
RIDGE_BIRD = (28, 14, 34)

# @skinlab {"type":"integer","label":"Birds","group":"Motion","min":0,"max":8,"step":1}
RIDGE_BIRDS = 5

# @skinlab {"type":"integer","label":"Bird speed","group":"Motion","min":1,"max":4,"step":1}
RIDGE_BIRD_SPEED = 1

# @skinlab {"type":"color","label":"Water glints","group":"Palette"}
RIDGE_GLINT = (255, 236, 210)

# Whole runs of the sun path per 4 s cycle. At 1.4 the glints used to restart
# two fifths of the way down the water when `t` wrapped.
# @skinlab {"type":"integer","label":"Glint speed","group":"Motion","min":1,"max":4,"step":1}
RIDGE_GLINT_SPEED = 2

# @skinlab {"type":"integer","label":"Sun path glints","group":"Layout","min":0,"max":14,"step":1}
RIDGE_PATH_GLINTS = 8

# @skinlab {"type":"integer","label":"Lake ripples","group":"Layout","min":0,"max":10,"step":1}
RIDGE_RIPPLES = 5

# @skinlab {"type":"integer","label":"Ripple drift","group":"Motion","min":1,"max":3,"step":1}
RIDGE_RIPPLE_SPEED = 1

# @skinlab {"type":"integer","label":"Haze bars on sun","group":"Layout","min":0,"max":6,"step":1}
RIDGE_SUN_BARS = 3

# @skinlab {"type":"integer","label":"Haze bar rise","group":"Motion","min":1,"max":3,"step":1}
RIDGE_SUN_BAR_SPEED = 1


def _g_ridgeline(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    lake = int(h * RIDGE_LAKE)
    step = max(1, h // 90)
    for y in range(0, lake, step):
        f = y / lake
        if f < 0.62:
            g = f / 0.62
            buf.pen = color.rgb(int(34 + 150 * g * g), int(18 + 52 * g * g), int(78 - 6 * g))
        else:
            g = (f - 0.62) / 0.38
            buf.pen = color.rgb(int(184 + 71 * g), int(70 + 104 * g), int(72 - 10 * g))
        buf.rectangle(0, y, w, step)
    cx, cy = w // 2, int(h * 0.40)
    r = int(h * RIDGE_SUN_R)
    buf.pen = color.rgb(RIDGE_GLOW[0], RIDGE_GLOW[1], RIDGE_GLOW[2], 60)
    buf.circle(cx, cy, int(r * 1.5))
    buf.pen = color.rgb(*RIDGE_SUN)
    buf.circle(cx, cy, r)
    buf.pen = color.rgb(*RIDGE_SUN_CORE)
    buf.circle(cx, cy, int(r * 0.62))
    by = cy - int(r * 0.8)
    i = 0
    while by < cy + r:
        th = max(1, (u * (i + 2)) // 5)
        f = min(1.0, by / lake)
        if f < 0.62:
            g = f / 0.62
            buf.pen = color.rgb(int(34 + 150 * g * g), int(18 + 52 * g * g), int(78 - 6 * g))
        else:
            g = (f - 0.62) / 0.38
            buf.pen = color.rgb(int(184 + 71 * g), int(70 + 104 * g), int(72 - 10 * g))
        buf.rectangle(cx - r - 1, by, r * 2 + 2, th)
        by += th + max(1, u // 2 + i)
        i += 1
    peaks = (13, 6, 17, 9, 21, 7, 15, 10, 19, 8)
    wide = (9, 6, 11, 7, 13, 8, 10, 6, 12, 7)
    layers = ((0.50, (146, 78, 116), 0, 1.0), (0.545, (98, 48, 90), 3, 0.86),
              (0.585, (58, 28, 62), 6, 0.72), (0.625, (24, 11, 32), 1, 0.58))
    for base_f, tint, seed, sc in layers:
        base = int(h * base_f)
        buf.pen = color.rgb(tint[0], tint[1], tint[2])
        buf.rectangle(0, base, w, lake - base + 1)
        x = -u * 6
        i = 0
        while x < w + u * 2:
            span = max(1, int(u * wide[(i + seed) % 10] * sc * 0.6))
            ph = max(1, int(peaks[(i * 3 + seed) % 10] * u * sc) // 2)
            buf.triangle(x, base + 1, x + span * 2, base + 1, x + span, base - ph)
            x += span + max(1, u // 2)
            i += 1
    for y in range(lake, h, step):
        f = (y - lake) / max(1, h - lake)
        buf.pen = color.rgb(int(158 - 124 * f), int(66 - 46 * f), int(74 - 20 * f))
        buf.rectangle(0, y, w, step)
    x = -u * 4
    i = 0
    buf.pen = color.rgb(RIDGE_RIPPLE[0], RIDGE_RIPPLE[1], RIDGE_RIPPLE[2], 150)
    while x < w + u * 2:
        span = max(1, int(u * wide[i % 10] * 0.5))
        ph = max(1, int(peaks[(i * 3) % 10] * u) // 4)
        buf.triangle(x, lake, x + span * 2, lake, x + span, lake + ph)
        x += span + max(1, u // 2)
        i += 1
    for i in range(RIDGE_PATH_BARS):
        yy = lake + int((h - lake) * (i + 1) / 8.0)
        ww = int(r * (0.55 + i * 0.16))
        gapw = int(u * (i % 3) * 0.8)
        buf.pen = color.rgb(RIDGE_PATH[0], RIDGE_PATH[1], RIDGE_PATH[2], 160 - i * 18)
        buf.rectangle(cx - ww // 2, yy, max(1, ww // 2 - gapw), max(1, u // 2))
        buf.rectangle(cx + gapw, yy, max(1, ww // 2 - gapw), max(1, u // 2))
    buf.pen = color.rgb(RIDGE_SHORE[0], RIDGE_SHORE[1], RIDGE_SHORE[2], 90)
    buf.rectangle(0, lake, w, max(1, u // 3))


def _g_ridgeline_a(dst, t):
    """The lake never sits still: the sun's path breaks up and runs at you,
    ripples cross the whole water, haze slides over the disc, birds work the
    ridge in a loose skein."""
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    ang = t * 6.283185
    lake = int(h * RIDGE_LAKE)
    cx, cy = w // 2, int(h * 0.40)
    r = int(h * RIDGE_SUN_R)
    for i in range(RIDGE_SUN_BARS):
        q = (t * RIDGE_SUN_BAR_SPEED + i / float(max(1, RIDGE_SUN_BARS))) % 1.0
        yy = cy + r - int(r * 2 * q)
        dy = (yy - cy) / float(max(1, r))
        span = int(r * math.sqrt(max(0.0, 1.0 - dy * dy)))
        dst.pen = color.rgb(255, 236, 200, 70)
        dst.rectangle(cx - span, yy, span * 2, max(1, u // 3))
    # The sun path: broken glints running toward the near shore, widening the
    # way a reflection does, brightest where they are born under the sun.
    n = max(1, RIDGE_PATH_GLINTS)
    for i in range(RIDGE_PATH_GLINTS):
        q = (t * RIDGE_GLINT_SPEED + ((i * 5) % n) / float(n)) % 1.0
        ww = int(r * (0.45 + 1.05 * q))
        sway = math.sin(ang * 2.0 + i * 1.7)
        dst.pen = color.rgb(RIDGE_GLINT[0], RIDGE_GLINT[1], RIDGE_GLINT[2],
                            int(50 + 130 * (1.0 - q)))
        dst.rectangle(cx - ww // 2 + int(sway * u * (1 + i % 3)),
                      lake + int((h - lake) * q),
                      max(2, int(ww * (0.34 + 0.22 * (i % 3)))), max(1, u // 3))
    for i in range(RIDGE_RIPPLES):
        q = (t * RIDGE_RIPPLE_SPEED + i / float(max(1, RIDGE_RIPPLES))) % 1.0
        dst.pen = color.rgb(RIDGE_RIPPLE[0], RIDGE_RIPPLE[1], RIDGE_RIPPLE[2], 110)
        dst.rectangle(int(w * (((i * 29) % 17) / 17.0)) - int(w * 0.1),
                      lake + int((h - lake) * (0.06 + 0.9 * q)),
                      int(w * (0.26 + 0.1 * (i % 3))), max(1, u // 3))
    dst.pen = color.rgb(*RIDGE_BIRD)
    for i in range(RIDGE_BIRDS):
        p = (t * RIDGE_BIRD_SPEED + ((i * 3) % 5) * 0.19) % 1.0
        x = int(w * 1.12 - w * 1.24 * p)
        y = int(h * (0.13 + 0.035 * i) + math.sin(p * 6.5 + i) * h * 0.03)
        s = max(1, u - i // 2)
        flap = 0 if math.sin(ang * 4.0 + i * 1.3) > 0 else max(1, s // 2)
        dst.line(x - s * 2, y + flap, x, y - s + flap)
        dst.line(x, y - s + flap, x + s * 2, y + flap)


# @skinlab {"type":"color","label":"Stars","group":"Palette"}
SHIFT_STAR = (220, 226, 255)

# @skinlab {"type":"color","label":"Moon","group":"Palette"}
SHIFT_MOON = (252, 244, 216)

# @skinlab {"type":"color","label":"High haze","group":"Palette"}
SHIFT_HAZE = (120, 70, 120)

# @skinlab {"type":"color","label":"Low smog","group":"Palette"}
SHIFT_SMOG = (180, 110, 130)

# @skinlab {"type":"color","label":"Far blocks","group":"Palette"}
SHIFT_BACK = (58, 44, 96)

# @skinlab {"type":"color","label":"Towers","group":"Palette"}
SHIFT_TOWER = (12, 10, 30)

# @skinlab {"type":"color","label":"Windows","group":"Palette"}
SHIFT_WINDOW = (255, 206, 120)

# @skinlab {"type":"integer","label":"Lit windows","group":"Layout","min":0,"max":11,"step":1}
SHIFT_LIT = 5

# @skinlab {"type":"color","label":"River","group":"Palette"}
SHIFT_RIVER = (10, 12, 34)

# @skinlab {"type":"color","label":"Mast beacon","group":"Palette"}
SHIFT_BEACON = (255, 60, 60)

# @skinlab {"type":"boolean","label":"Beacon blinks","group":"Motion"}
SHIFT_BEACON_ON = True

# @skinlab {"type":"integer","label":"Window blink","group":"Motion","min":1,"max":8,"step":1}
SHIFT_BLINK_SPEED = 3

# @skinlab {"type":"boolean","label":"Night flight","group":"Motion"}
SHIFT_PLANE = True

# One crossing per 4 s cycle. At 0.9 the aircraft used to reappear a tenth of
# the way in when `t` wrapped, which is the periodicity rule failing quietly.
# @skinlab {"type":"integer","label":"Flight speed","group":"Motion","min":1,"max":4,"step":1}
SHIFT_PLANE_SPEED = 1

# @skinlab {"type":"integer","label":"Blinking windows","group":"Layout","min":0,"max":30,"step":2}
SHIFT_BLINKERS = 18

# @skinlab {"type":"number","label":"Windows lit at once","group":"Motion","min":0.1,"max":0.9,"step":0.05}
SHIFT_BLINK_DUTY = 0.5

# @skinlab {"type":"integer","label":"River ripples","group":"Layout","min":0,"max":10,"step":1}
SHIFT_RIPPLES = 5

# @skinlab {"type":"integer","label":"Ripple drift","group":"Motion","min":1,"max":3,"step":1}
SHIFT_RIPPLE_SPEED = 1

# @skinlab {"type":"boolean","label":"River traffic","group":"Motion"}
SHIFT_BOAT = True

# @skinlab {"type":"color","label":"Boat lamp","group":"Palette"}
SHIFT_BOAT_LIGHT = (255, 214, 140)

# @skinlab {"type":"integer","label":"Boat speed","group":"Motion","min":1,"max":3,"step":1}
SHIFT_BOAT_SPEED = 1

# @skinlab {"type":"integer","label":"Smog drift","group":"Motion","min":1,"max":3,"step":1}
SHIFT_SMOG_DRIFT = 1


def _g_late_shift(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    sky = int(h * 0.66)
    step = max(1, h // 90)
    for y in range(0, sky, step):
        f = y / sky
        buf.pen = color.rgb(int(8 + 60 * f * f), int(10 + 26 * f * f), int(32 + 46 * f))
        buf.rectangle(0, y, w, step)
    stars = ((0.08, 0.10), (0.17, 0.05), (0.29, 0.13), (0.41, 0.07), (0.55, 0.11),
             (0.63, 0.04), (0.88, 0.09), (0.94, 0.17), (0.35, 0.20), (0.72, 0.22))
    for i, s in enumerate(stars):
        buf.pen = color.rgb(SHIFT_STAR[0], SHIFT_STAR[1], SHIFT_STAR[2], 110 + (i % 3) * 60)
        buf.rectangle(int(w * s[0]), int(h * s[1]), max(1, u // 3), max(1, u // 3))
    mx, my = int(w * 0.79), int(h * 0.15)
    for i in range(3):
        buf.pen = color.rgb(255, 236, 190, 20)
        buf.circle(mx, my, int(u * (5.2 - i * 0.9)))
    buf.pen = color.rgb(*SHIFT_MOON)
    buf.circle(mx, my, int(u * 2.2))
    buf.pen = color.rgb(70, 40, 90, 90)
    buf.circle(mx - u, my - u, int(u * 2.2))
    buf.pen = color.rgb(SHIFT_HAZE[0], SHIFT_HAZE[1], SHIFT_HAZE[2], 60)
    buf.rectangle(0, int(h * 0.50), w, int(h * 0.18))
    buf.pen = color.rgb(SHIFT_SMOG[0], SHIFT_SMOG[1], SHIFT_SMOG[2], 50)
    buf.rectangle(0, int(h * 0.58), w, int(h * 0.10))
    back = ((0.02, 0.40, 0.14), (0.13, 0.46, 0.10), (0.22, 0.36, 0.16), (0.36, 0.44, 0.12),
            (0.47, 0.38, 0.18), (0.62, 0.47, 0.11), (0.71, 0.34, 0.15), (0.85, 0.42, 0.17))
    buf.pen = color.rgb(*SHIFT_BACK)
    for b in back:
        top = int(h * (0.30 + b[1] * 0.28))
        buf.rectangle(int(w * b[0]), top, int(w * b[2]), h - top)
    ant = int(w * 0.24)
    buf.pen = color.rgb(*SHIFT_BACK)
    buf.rectangle(ant, int(h * 0.24), max(1, u // 2), int(h * 0.2))
    buf.pen = color.rgb(255, 200, 140, 34)
    for b in back:
        top = int(h * (0.30 + b[1] * 0.28))
        buf.rectangle(int(w * b[0]), top, int(w * b[2]), max(1, u // 2))
    towers = ((0.00, 0.46, 0.13, 3), (0.12, 0.58, 0.09, 2), (0.20, 0.50, 0.15, 4),
              (0.34, 0.62, 0.11, 2), (0.44, 0.44, 0.12, 4), (0.55, 0.56, 0.14, 3),
              (0.68, 0.48, 0.10, 3), (0.77, 0.60, 0.13, 3), (0.89, 0.52, 0.13, 3))
    lit = int(h * 0.86)
    for ti, tw in enumerate(towers):
        x0 = int(w * tw[0])
        top = int(h * tw[1])
        bw = int(w * tw[2])
        buf.pen = color.rgb(*SHIFT_TOWER)
        buf.rectangle(x0, top, bw, h - top)
        cols = tw[3]
        cw = max(1, bw // (cols * 2 + 1))
        rows = max(1, (lit - top) // max(2, u * 2))
        for ry in range(rows):
            wy = top + u + ry * max(2, u * 2)
            if wy > lit:
                break
            for cxi in range(cols):
                if (ti * 7 + ry * 5 + cxi * 3) % 11 < SHIFT_LIT:
                    a = 210 if (ti + ry + cxi) % 3 else 130
                    buf.pen = color.rgb(SHIFT_WINDOW[0], SHIFT_WINDOW[1], SHIFT_WINDOW[2], a)
                    buf.rectangle(x0 + cw + cxi * cw * 2, wy, cw, max(1, u))
    river = int(h * 0.86)
    buf.pen = color.rgb(*SHIFT_RIVER)
    buf.rectangle(0, river, w, h - river)
    buf.pen = color.rgb(255, 210, 140, 60)
    buf.rectangle(0, river, w, max(1, u // 3))
    for i in range(8):
        x = int(w * (0.03 + i * 0.125))
        buf.pen = color.rgb(255, 200, 120, 70)
        buf.rectangle(x, river, max(2, int(u * 1.4)), int((h - river) * (0.4 + 0.15 * (i % 4))))
    buf.pen = color.rgb(250, 244, 216, 100)
    buf.rectangle(mx - u, river, max(2, int(u * 2)), int((h - river) * 0.8))
    for i in range(6):
        yy = river + int((h - river) * (i + 1) / 7.0)
        buf.pen = color.rgb(8, 10, 28, 150)
        buf.rectangle(int(w * ((i * 0.31) % 1.0)) - int(w * 0.1), yy, int(w * 0.34), max(1, u // 3))


def _g_late_shift_a(dst, t):
    """A city still working: windows going on and off all over the skyline, the
    river breathing under it, a barge crossing, smog sliding, a late flight."""
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    ant = int(w * 0.24)
    river = int(h * 0.86)
    if SHIFT_BEACON_ON and t % 0.5 < 0.22:
        dst.pen = color.rgb(SHIFT_BEACON[0], SHIFT_BEACON[1], SHIFT_BEACON[2], 60)
        dst.circle(ant, int(h * 0.235), max(2, int(u * 1.6)))
        dst.pen = color.rgb(*SHIFT_BEACON)
        dst.rectangle(ant - max(1, u // 3), int(h * 0.23), max(1, u), max(1, u))
    # Windows switch in relay across the towers `render` drew. The offsets are a
    # full permutation of the cycle, so the count alight never spikes.
    towers = ((0.00, 0.46, 0.13), (0.12, 0.58, 0.09), (0.20, 0.50, 0.15),
              (0.34, 0.62, 0.11), (0.44, 0.44, 0.12), (0.55, 0.56, 0.14),
              (0.68, 0.48, 0.10), (0.77, 0.60, 0.13), (0.89, 0.52, 0.13))
    n = max(1, SHIFT_BLINKERS)
    for i in range(SHIFT_BLINKERS):
        if (t * SHIFT_BLINK_SPEED + ((i * 7) % n) / float(n)) % 1.0 >= SHIFT_BLINK_DUTY:
            continue
        tw = towers[(i * 4) % 9]
        top = int(h * tw[1])
        bw = int(w * tw[2])
        rows = max(1, (int(h * 0.84) - top) // max(2, u * 2))
        dst.pen = color.rgb(255, 220, 150, 220)
        dst.rectangle(int(w * tw[0]) + max(1, bw // 5)
                      + ((i * 3) % 3) * max(1, bw // 4),
                      top + u + ((i * 5) % rows) * max(2, u * 2),
                      max(1, u), max(1, u))
    for i in range(SHIFT_RIPPLES):
        q = (t * SHIFT_RIPPLE_SPEED + i / float(max(1, SHIFT_RIPPLES))) % 1.0
        dst.pen = color.rgb(255, 210, 140, 60 + (i % 3) * 20)
        dst.rectangle(-int(w * 0.3) + int(w * 1.3 * q),
                      river + int((h - river) * (0.10 + 0.16 * ((i * 3) % 5))),
                      int(w * 0.22), max(1, u // 3))
    glint = 0.5 + 0.5 * math.sin(t * 6.283185 * 2.0)
    dst.pen = color.rgb(250, 244, 216, int(50 + 90 * glint))
    dst.rectangle(int(w * 0.79) - u, river + int((h - river) * 0.2),
                  max(2, int(u * 2)), max(1, u // 3))
    if SHIFT_BOAT:
        bx = -int(w * 0.16) + int(w * 1.32 * ((t * SHIFT_BOAT_SPEED) % 1.0))
        by = river + int((h - river) * 0.34)
        dst.pen = color.rgb(6, 8, 20)
        dst.rectangle(bx, by, int(w * 0.09), max(1, u))
        dst.rectangle(bx + int(w * 0.02), by - max(1, u), max(2, int(u * 1.5)), max(1, u))
        dst.pen = color.rgb(*SHIFT_BOAT_LIGHT)
        dst.rectangle(bx + int(w * 0.075), by - max(1, u // 2),
                      max(1, u // 2), max(1, u // 2))
        dst.pen = color.rgb(SHIFT_BOAT_LIGHT[0], SHIFT_BOAT_LIGHT[1],
                            SHIFT_BOAT_LIGHT[2], 80)
        dst.rectangle(bx + int(w * 0.06), by + max(1, u), max(2, int(u * 1.2)),
                      max(1, int((h - river) * 0.45)))
    for i in range(2):
        q = (t * SHIFT_SMOG_DRIFT + i * 0.5) % 1.0
        dst.pen = color.rgb(SHIFT_SMOG[0], SHIFT_SMOG[1], SHIFT_SMOG[2], 26)
        dst.rectangle(-int(w * 0.5) + int(w * 1.5 * q), int(h * (0.52 + i * 0.07)),
                      int(w * 0.5), max(1, int(u * 1.5)))
    if SHIFT_PLANE:
        px = int(w * 1.05 - w * 1.15 * ((t * SHIFT_PLANE_SPEED) % 1.0))
        dst.pen = color.rgb(255, 255, 220, 200 if (t * 8) % 1.0 < 0.5 else 60)
        dst.rectangle(px, int(h * 0.09), max(1, u // 2), max(1, u // 2))
        dst.pen = color.rgb(255, 90, 70, 200 if (t * 8) % 1.0 < 0.25 else 40)
        dst.rectangle(px + max(1, u), int(h * 0.09) + max(1, u // 3),
                      max(1, u // 3), max(1, u // 3))


# @skinlab {"type":"color","label":"Light shafts","group":"Palette"}
SUNKEN_RAY = (200, 250, 245)

# @skinlab {"type":"integer","label":"Light shafts","group":"Layout","min":0,"max":12,"step":1}
SUNKEN_RAYS = 6

# @skinlab {"type":"color","label":"Surface","group":"Palette"}
SUNKEN_SURFACE = (150, 235, 230)

# @skinlab {"type":"color","label":"Wreck","group":"Palette"}
SUNKEN_HULL = (5, 34, 56)

# @skinlab {"type":"color","label":"Porthole","group":"Palette"}
SUNKEN_PORT = (210, 245, 245)

# @skinlab {"type":"color","label":"Fish","group":"Palette"}
SUNKEN_FISH = (250, 200, 90)

# @skinlab {"type":"color","label":"Seabed","group":"Palette"}
SUNKEN_BED = (3, 20, 40)

# @skinlab {"type":"color","label":"Weed","group":"Palette"}
SUNKEN_WEED = (10, 70, 60)

# @skinlab {"type":"integer","label":"Drifting motes","group":"Layout","min":0,"max":24,"step":1}
SUNKEN_MOTES = 10

# @skinlab {"type":"color","label":"Bubbles","group":"Palette"}
SUNKEN_BUBBLE = (210, 250, 250)

# @skinlab {"type":"integer","label":"Bubble count","group":"Motion","min":0,"max":16,"step":1}
SUNKEN_BUBBLES = 8

# Whole rises per 4 s cycle, so the column joins itself at the wrap.
# @skinlab {"type":"integer","label":"Bubble rise","group":"Motion","min":1,"max":4,"step":1}
SUNKEN_RISE_SPEED = 1

# @skinlab {"type":"color","label":"Swimming fish","group":"Palette"}
SUNKEN_SWIMMER = (255, 214, 110)

# @skinlab {"type":"integer","label":"Fish speed","group":"Motion","min":1,"max":4,"step":1}
SUNKEN_SWIM_SPEED = 1

# @skinlab {"type":"integer","label":"School size","group":"Layout","min":0,"max":12,"step":1}
SUNKEN_SCHOOL = 6

# @skinlab {"type":"integer","label":"School speed","group":"Motion","min":1,"max":3,"step":1}
SUNKEN_SCHOOL_SPEED = 1

# @skinlab {"type":"integer","label":"Swaying shafts","group":"Layout","min":0,"max":8,"step":1}
SUNKEN_SHAFT_SWAY_N = 4

# @skinlab {"type":"number","label":"Shaft sway","group":"Motion","min":0.0,"max":0.15,"step":0.01}
SUNKEN_SHAFT_SWAY = 0.05

# @skinlab {"type":"integer","label":"Seabed caustics","group":"Layout","min":0,"max":10,"step":1}
SUNKEN_CAUSTICS = 5

# @skinlab {"type":"integer","label":"Caustic drift","group":"Motion","min":1,"max":3,"step":1}
SUNKEN_CAUSTIC_SPEED = 1

# @skinlab {"type":"number","label":"Weed sway","group":"Motion","min":0.0,"max":0.15,"step":0.01}
SUNKEN_WEED_SWAY = 0.05


def _g_sunken_light(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    step = max(1, h // 90)
    for y in range(0, h, step):
        f = y / h
        buf.pen = color.rgb(int(30 - 28 * f), int(150 - 132 * f), int(158 - 116 * f))
        buf.rectangle(0, y, w, step)
    for i in range(SUNKEN_RAYS):
        x = int(w * (0.05 + i * 0.19))
        buf.pen = color.rgb(SUNKEN_RAY[0], SUNKEN_RAY[1], SUNKEN_RAY[2], 34)
        buf.triangle(x, 0, x + int(w * 0.07), 0, x - int(w * 0.12), int(h * 0.86))
        buf.pen = color.rgb(225, 255, 250, 26)
        buf.triangle(x + u, 0, x + int(w * 0.045), 0, x - int(w * 0.06), int(h * 0.7))
    buf.pen = color.rgb(SUNKEN_SURFACE[0], SUNKEN_SURFACE[1], SUNKEN_SURFACE[2], 120)
    buf.rectangle(0, 0, w, max(1, u // 2))
    for i in range(9):
        buf.pen = color.rgb(190, 250, 245, 90)
        buf.circle(int(w * (i + 0.5) / 9.0), 0, max(1, u))
    hx, hy = int(w * 0.36), int(h * 0.62)
    br = int(h * 0.115)
    buf.pen = color.rgb(*SUNKEN_HULL)
    buf.circle(hx, hy, br)
    buf.circle(hx - int(w * 0.11), hy, int(br * 0.86))
    buf.rectangle(hx - int(w * 0.11), hy - br, int(w * 0.11), br * 2)
    buf.triangle(hx - int(w * 0.16), hy - int(br * 0.6), hx - int(w * 0.16), hy + int(br * 0.6),
                 hx - int(w * 0.30), hy - int(br * 1.5))
    buf.triangle(hx - int(w * 0.16), hy - int(br * 0.6), hx - int(w * 0.16), hy + int(br * 0.6),
                 hx - int(w * 0.30), hy + int(br * 1.2))
    buf.triangle(hx - int(w * 0.02), hy + int(br * 0.5), hx + int(w * 0.05), hy + int(br * 0.5),
                 hx - int(w * 0.04), hy + int(br * 1.5))
    buf.pen = color.rgb(120, 200, 210, 110)
    buf.rectangle(hx - int(w * 0.13), hy - br, int(w * 0.16), max(1, u // 2))
    buf.pen = color.rgb(SUNKEN_PORT[0], SUNKEN_PORT[1], SUNKEN_PORT[2], 200)
    buf.rectangle(hx + int(br * 0.5), hy - int(br * 0.25), max(1, u // 2), max(1, u // 2))
    buf.pen = color.rgb(3, 24, 44)
    buf.rectangle(hx - int(w * 0.11), hy + int(br * 0.55), int(w * 0.12), max(1, u // 2))
    fish = ((0.62, 0.36), (0.70, 0.40), (0.66, 0.44), (0.76, 0.34), (0.80, 0.42), (0.72, 0.30))
    for f in fish:
        buf.pen = color.rgb(*SUNKEN_FISH)
        x, y = int(w * f[0]), int(h * f[1])
        buf.triangle(x, y, x - u * 2, y - u, x - u * 2, y + u)
    buf.pen = color.rgb(*SUNKEN_BED)
    buf.rectangle(0, int(h * 0.88), w, h)
    for i in range(6):
        buf.pen = color.rgb(*SUNKEN_BED)
        buf.circle(int(w * (0.05 + i * 0.19)), int(h * (0.90 + (i % 2) * 0.03)),
                   int(u * (2 + i % 3)))
    for i in range(5):
        x = int(w * (0.08 + i * 0.21))
        buf.pen = color.rgb(*SUNKEN_WEED)
        buf.triangle(x - u, h, x + u, h,
                     x + (u * 3 if i % 2 else -u * 3), int(h * (0.60 + 0.05 * (i % 3))))
    for i in range(SUNKEN_MOTES):
        buf.pen = color.rgb(220, 255, 250, 60)
        buf.rectangle(int(w * ((i * 0.173 + 0.05) % 1.0)), int(h * ((i * 0.271 + 0.1) % 0.85)),
                      max(1, u // 3), max(1, u // 3))


def _g_sunken_light_a(dst, t):
    """The whole site is alive: shafts swaying off the surface, a school
    working the open water past the wreck, weed leaning in the current,
    bubbles off the hull, caustics crawling over the seabed."""
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    turn = t * 6.283185
    for i in range(SUNKEN_SHAFT_SWAY_N):
        sway = math.sin(turn + i * 1.5) * w * SUNKEN_SHAFT_SWAY
        x = int(w * (0.09 + i * 0.24))
        dst.pen = color.rgb(SUNKEN_RAY[0], SUNKEN_RAY[1], SUNKEN_RAY[2], 24)
        dst.triangle(x, 0, x + int(w * 0.04), 0,
                     int(x - w * 0.09 + sway), int(h * 0.80))
    for i in range(3):
        x = int(w * (0.08 + i * 0.32))
        lean = math.sin(turn + i * 2.0) * w * SUNKEN_WEED_SWAY
        dst.pen = color.rgb(SUNKEN_WEED[0], SUNKEN_WEED[1], SUNKEN_WEED[2], 220)
        dst.triangle(x - u, h, x + u, h, int(x + lean), int(h * (0.58 + 0.05 * i)))
    for i in range(SUNKEN_CAUSTICS):
        q = (t * SUNKEN_CAUSTIC_SPEED + i / float(max(1, SUNKEN_CAUSTICS))) % 1.0
        dst.pen = color.rgb(190, 250, 245, 46)
        dst.rectangle(-int(w * 0.2) + int(w * 1.4 * q),
                      int(h * (0.89 + 0.03 * (i % 3))), int(w * 0.15), max(1, u // 3))
    for i in range(SUNKEN_SCHOOL):
        q = (t * SUNKEN_SCHOOL_SPEED + i * 0.04) % 1.0
        fx = int(w * 1.14 - w * 1.34 * q)
        fy = int(h * (0.30 + 0.035 * (i % 4)) + math.sin(turn * 2 + i) * h * 0.02)
        dst.pen = color.rgb(SUNKEN_FISH[0], SUNKEN_FISH[1], SUNKEN_FISH[2], 230)
        dst.triangle(fx, fy, fx + u * 2, fy - u, fx + u * 2, fy + u)
    for i in range(SUNKEN_BUBBLES):
        p = (t * SUNKEN_RISE_SPEED + i * 0.125) % 1.0
        dst.pen = color.rgb(SUNKEN_BUBBLE[0], SUNKEN_BUBBLE[1], SUNKEN_BUBBLE[2],
                            90 + (i % 3) * 50)
        dst.circle(int(w * (0.12 + i * 0.10) + math.sin(p * 6.283185 + i) * u * 2),
                   int(h * 1.02 - h * 1.06 * p), max(1, (u // 2) + (i % 3)))
    fx = int(w * 0.62 + math.sin(turn * SUNKEN_SWIM_SPEED) * w * 0.14)
    fy = int(h * 0.38 + math.cos(turn * SUNKEN_SWIM_SPEED) * h * 0.03)
    dst.pen = color.rgb(*SUNKEN_SWIMMER)
    dst.triangle(fx, fy, fx - u * 3, fy - u, fx - u * 3, fy + u)
    dst.rectangle(fx - u * 4, fy - int(u * (0.4 + 0.5 * math.sin(turn * 4))),
                  max(1, u), max(1, u))


# @skinlab {"type":"number","label":"Horizon","group":"Layout","min":0.64,"max":0.88,"step":0.01}
MESA_HORIZON = 0.74

# @skinlab {"type":"color","label":"Sun halo","group":"Palette"}
MESA_SUN_HALO = (255, 140, 60)

# @skinlab {"type":"color","label":"Sun rim","group":"Palette"}
MESA_SUN_RIM = (255, 186, 84)

# @skinlab {"type":"color","label":"Sun mid","group":"Palette"}
MESA_SUN_MID = (255, 212, 124)

# @skinlab {"type":"color","label":"Sun inner","group":"Palette"}
MESA_SUN_INNER = (255, 234, 168)

# @skinlab {"type":"color","label":"Sun core","group":"Palette"}
MESA_SUN_CORE = (255, 248, 214)

# @skinlab {"type":"number","label":"Sun size","group":"Layout","min":0.18,"max":0.58,"step":0.01}
MESA_SUN_R = 0.40

# @skinlab {"type":"color","label":"Cloud streaks","group":"Palette"}
MESA_CLOUD = (255, 170, 120)

# @skinlab {"type":"integer","label":"Cloud streaks","group":"Layout","min":0,"max":8,"step":1}
MESA_CLOUDS = 4

# @skinlab {"type":"color","label":"Far mesas","group":"Palette"}
MESA_FAR = (150, 66, 82)

# @skinlab {"type":"color","label":"Near mesas","group":"Palette"}
MESA_MID = (96, 36, 60)

# @skinlab {"type":"color","label":"Desert floor","group":"Palette"}
MESA_GROUND = (52, 18, 40)

# @skinlab {"type":"color","label":"Floor streaks","group":"Palette"}
MESA_STREAK = (74, 26, 52)

# @skinlab {"type":"color","label":"Cactus","group":"Palette"}
MESA_CACTUS = (22, 7, 22)

# @skinlab {"type":"color","label":"Vultures","group":"Palette"}
MESA_BIRD = (30, 10, 26)

# @skinlab {"type":"integer","label":"Vultures","group":"Layout","min":0,"max":6,"step":1}
MESA_BIRDS = 3

# Whole circuits of the 4 s cycle: a fractional rate leaves the bird somewhere
# other than where it started when `t` wraps 1 -> 0.
# @skinlab {"type":"integer","label":"Thermal speed","group":"Motion","min":1,"max":4,"step":1}
MESA_BIRD_SPEED = 1

# @skinlab {"type":"color","label":"Tumbleweed","group":"Palette"}
MESA_TUMBLE = (128, 74, 58)

# @skinlab {"type":"integer","label":"Tumbleweeds","group":"Layout","min":0,"max":4,"step":1}
MESA_TUMBLERS = 2

# @skinlab {"type":"integer","label":"Tumble speed","group":"Motion","min":1,"max":3,"step":1}
MESA_TUMBLE_SPEED = 1

# @skinlab {"type":"integer","label":"Heat shimmer","group":"Layout","min":0,"max":8,"step":1}
MESA_SHIMMER = 5

# @skinlab {"type":"integer","label":"Shimmer beat","group":"Motion","min":1,"max":4,"step":1}
MESA_SHIMMER_SPEED = 2

# @skinlab {"type":"integer","label":"Haze bars on sun","group":"Layout","min":0,"max":6,"step":1}
MESA_GLARE_BARS = 3

# @skinlab {"type":"integer","label":"Haze bar rise","group":"Motion","min":1,"max":3,"step":1}
MESA_GLARE_SPEED = 1

# @skinlab {"type":"integer","label":"Drifting cirrus","group":"Layout","min":0,"max":6,"step":1}
MESA_DRIFT_CLOUDS = 3


def _g_red_mesa(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    ground = int(h * MESA_HORIZON)
    step = max(1, h // 90)
    for y in range(0, ground, step):
        f = y / ground
        buf.pen = color.rgb(int(96 + 158 * f), int(28 + 130 * f * f), int(84 - 4 * f - 30 * f * f))
        buf.rectangle(0, y, w, step)
    cx, cy = int(w * 0.52), int(h * 0.56)
    r = int(h * MESA_SUN_R)
    buf.pen = color.rgb(MESA_SUN_HALO[0], MESA_SUN_HALO[1], MESA_SUN_HALO[2], 60)
    buf.circle(cx, cy, int(r * 1.25))
    buf.pen = color.rgb(*MESA_SUN_RIM)
    buf.circle(cx, cy, r)
    buf.pen = color.rgb(*MESA_SUN_MID)
    buf.circle(cx, cy, int(r * 0.78))
    buf.pen = color.rgb(*MESA_SUN_INNER)
    buf.circle(cx, cy, int(r * 0.54))
    buf.pen = color.rgb(*MESA_SUN_CORE)
    buf.circle(cx, cy, int(r * 0.28))
    for i in range(MESA_CLOUDS):
        yy = int(h * (0.16 + i * 0.045))
        buf.pen = color.rgb(MESA_CLOUD[0], MESA_CLOUD[1], MESA_CLOUD[2], 60)
        buf.rectangle(int(w * (0.05 + 0.1 * i)), yy, int(w * (0.34 - 0.05 * i)), max(1, u // 2))
    far = ((0.00, 0.44, 0.18, 0.10), (0.26, 0.50, 0.12, 0.06), (0.60, 0.42, 0.22, 0.12),
           (0.86, 0.48, 0.16, 0.08))
    buf.pen = color.rgb(*MESA_FAR)
    for m in far:
        x0 = int(w * m[0])
        top = int(h * m[1])
        bw = int(w * m[2])
        buf.rectangle(x0, top, bw, ground - top)
        buf.triangle(x0 - int(w * m[3]), ground, x0, ground, x0, top)
        buf.triangle(x0 + bw, ground, x0 + bw + int(w * m[3]), ground, x0 + bw, top)
    mid = ((0.06, 0.56, 0.20, 0.07), (0.44, 0.60, 0.16, 0.06), (0.74, 0.54, 0.24, 0.09))
    buf.pen = color.rgb(*MESA_MID)
    for m in mid:
        x0 = int(w * m[0])
        top = int(h * m[1])
        bw = int(w * m[2])
        buf.rectangle(x0, top, bw, ground - top)
        buf.triangle(x0 - int(w * m[3]), ground, x0, ground, x0, top)
        buf.triangle(x0 + bw, ground, x0 + bw + int(w * m[3]), ground, x0 + bw, top)
    buf.pen = color.rgb(*MESA_GROUND)
    buf.rectangle(0, ground, w, h - ground)
    buf.pen = color.rgb(*MESA_STREAK)
    for i in range(6):
        yy = ground + int((h - ground) * (i + 1) / 8.0)
        buf.rectangle(int(w * (0.02 + 0.14 * i)), yy, int(w * (0.30 - 0.03 * i)), max(1, u // 2))
    for cxx, sc, dy in ((0.14, 1.0, 0.06), (0.83, 0.78, 0.02), (0.34, 0.46, -0.02)):
        x = int(w * cxx)
        base = ground + int(h * dy)
        ch = int(h * 0.22 * sc)
        cwid = max(1, int(u * 1.7 * sc))
        buf.pen = color.rgb(*MESA_CACTUS)
        buf.rectangle(x, base - ch, cwid, ch)
        buf.rectangle(x - cwid * 2, base - int(ch * 0.86), cwid, int(ch * 0.42))
        buf.rectangle(x - cwid * 2, base - int(ch * 0.50), cwid * 2, max(1, cwid))
        buf.rectangle(x + cwid * 2, base - int(ch * 0.72), cwid, int(ch * 0.36))
        buf.rectangle(x + cwid, base - int(ch * 0.40), cwid * 2, max(1, cwid))
    buf.pen = color.rgb(24, 8, 24)
    buf.circle(int(w * 0.62), h - max(1, u), int(u * 2))
    buf.circle(int(w * 0.92), h - max(1, u // 2), int(u * 1.4))
    buf.circle(int(w * 0.05), h - max(1, u // 2), int(u * 1.2))


def _g_red_mesa_a(dst, t):
    """Desert evening, and none of it is actually still: haze crossing the
    disc, cirrus sliding, vultures on the last thermal, heat coming off the
    floor and a tumbleweed going wherever the wind is going."""
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    turn = t * 6.283185
    ground = int(h * MESA_HORIZON)
    cx, cy = int(w * 0.52), int(h * 0.56)
    r = int(h * MESA_SUN_R)
    for i in range(MESA_GLARE_BARS):
        q = (t * MESA_GLARE_SPEED + i / float(max(1, MESA_GLARE_BARS))) % 1.0
        yy = cy + r - int(r * 2 * q)
        if yy >= ground or yy < 0:
            continue
        dy = (yy - cy) / float(max(1, r))
        span = int(r * math.sqrt(max(0.0, 1.0 - dy * dy)))
        dst.pen = color.rgb(255, 232, 178, 64)
        dst.rectangle(cx - span, yy, span * 2, max(1, u // 3))
    for i in range(MESA_DRIFT_CLOUDS):
        q = (t + i / float(max(1, MESA_DRIFT_CLOUDS))) % 1.0
        dst.pen = color.rgb(MESA_CLOUD[0], MESA_CLOUD[1], MESA_CLOUD[2], 44)
        dst.rectangle(-int(w * 0.34) + int(w * 1.34 * q),
                      int(h * (0.13 + 0.05 * i)), int(w * 0.32), max(1, u // 2))
    dst.pen = color.rgb(*MESA_BIRD)
    for i in range(MESA_BIRDS):
        a = turn * MESA_BIRD_SPEED + i * 2.1
        bx = int(w * (0.28 + 0.19 * i) + math.cos(a) * w * 0.17)
        by = int(h * (0.13 + 0.04 * i) + math.sin(a) * h * 0.035)
        sz = max(1, u - (i % 2))
        flap = 0 if math.sin(turn * 3 + i) > 0 else max(1, sz // 2)
        dst.line(bx - sz * 2, by + flap, bx, by - sz + flap)
        dst.line(bx, by - sz + flap, bx + sz * 2, by + flap)
    for i in range(MESA_SHIMMER):
        sway = math.sin(turn * MESA_SHIMMER_SPEED + i * 1.4)
        dst.pen = color.rgb(255, 196, 138, 34)
        dst.rectangle(int(w * (0.01 + 0.07 * i) + sway * u * 3),
                      ground + int((h - ground) * (0.06 + 0.2 * i)),
                      int(w * (0.52 - 0.06 * i)), max(1, u // 3))
    for i in range(MESA_TUMBLERS):
        q = (t * MESA_TUMBLE_SPEED + i * 0.5) % 1.0
        tx = -int(w * 0.08) + int(w * 1.16 * q)
        rest = ground + int((h - ground) * (0.44 + 0.30 * i))
        rad = max(1, int(u * (1.5 - 0.5 * i)))
        ty = rest - int(abs(math.sin(q * 6.283185 * 4)) * u * 2)
        spin = turn * 4 + i
        dst.pen = color.rgb(24, 8, 24, 110)
        dst.rectangle(tx - rad, rest + rad, rad * 2, max(1, u // 3))
        dst.pen = color.rgb(*MESA_TUMBLE)
        dst.circle(tx, ty, rad)
        dst.rectangle(tx + int(math.cos(spin) * rad), ty + int(math.sin(spin) * rad),
                      max(1, u // 2), max(1, u // 2))
        dst.rectangle(tx - int(math.cos(spin) * rad), ty - int(math.sin(spin) * rad),
                      max(1, u // 2), max(1, u // 2))


# @skinlab {"type":"color","label":"Moon halo","group":"Palette"}
FIREFLY_MOON_HALO = (200, 240, 200)

# @skinlab {"type":"integer","label":"Moon glow","group":"Look","min":4,"max":60,"step":2}
FIREFLY_HALO_ALPHA = 16

# @skinlab {"type":"integer","label":"Halo rings","group":"Layout","min":1,"max":8,"step":1}
FIREFLY_HALO_RINGS = 4

# @skinlab {"type":"color","label":"Moon","group":"Palette"}
FIREFLY_MOON = (226, 244, 206)

# @skinlab {"type":"number","label":"Moon size","group":"Layout","min":0.06,"max":0.20,"step":0.01}
FIREFLY_MOON_R = 0.13

# @skinlab {"type":"color","label":"Stars","group":"Palette"}
FIREFLY_STAR = (220, 240, 230)

# @skinlab {"type":"color","label":"Mist","group":"Palette"}
FIREFLY_MIST = (150, 200, 190)

# @skinlab {"type":"integer","label":"Mist bands","group":"Layout","min":0,"max":8,"step":1}
FIREFLY_MIST_BANDS = 4

# @skinlab {"type":"color","label":"Near trees","group":"Palette"}
FIREFLY_TRUNK = (6, 14, 16)

# @skinlab {"type":"color","label":"Firefly halo","group":"Palette"}
FIREFLY_GLOW = (190, 255, 90)

# @skinlab {"type":"color","label":"Resting firefly","group":"Palette"}
FIREFLY_BODY = (226, 255, 150)

# @skinlab {"type":"color","label":"Flying firefly","group":"Palette"}
FIREFLY_SPARK = (232, 255, 160)

# Whole turns of the 4 s cycle. `t` wraps 1 -> 0, so a fractional rate
# restarts the motion part-way through and the loop visibly snaps.
# @skinlab {"type":"integer","label":"Drift speed","group":"Motion","min":1,"max":4,"step":1}
FIREFLY_DRIFT_SPEED = 1

# @skinlab {"type":"integer","label":"Flying fireflies","group":"Layout","min":0,"max":24,"step":2}
FIREFLY_FLIERS = 16

# @skinlab {"type":"number","label":"Blink duty","group":"Motion","min":0.1,"max":0.9,"step":0.05}
FIREFLY_BLINK_DUTY = 0.5

# @skinlab {"type":"integer","label":"Blink speed","group":"Motion","min":1,"max":6,"step":1}
FIREFLY_BLINK_SPEED = 2

# @skinlab {"type":"integer","label":"Close fireflies","group":"Layout","min":0,"max":4,"step":1}
FIREFLY_NEAR = 2

# @skinlab {"type":"integer","label":"Mist drift","group":"Motion","min":1,"max":3,"step":1}
FIREFLY_MIST_DRIFT = 1


def _g_firefly_wood(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    step = max(1, h // 90)
    for y in range(0, h, step):
        f = y / h
        buf.pen = color.rgb(int(14 + 26 * f), int(24 + 54 * f - 30 * f * f),
                            int(38 + 30 * f - 40 * f * f))
        buf.rectangle(0, y, w, step)
    mx, my = int(w * 0.70), int(h * 0.22)
    for i in range(FIREFLY_HALO_RINGS):
        buf.pen = color.rgb(FIREFLY_MOON_HALO[0], FIREFLY_MOON_HALO[1],
                            FIREFLY_MOON_HALO[2], FIREFLY_HALO_ALPHA)
        buf.circle(mx, my, int(h * (0.25 - i * 0.028)))
    buf.pen = color.rgb(*FIREFLY_MOON)
    buf.circle(mx, my, int(h * FIREFLY_MOON_R))
    buf.pen = color.rgb(20, 34, 44, 60)
    buf.circle(mx - int(u * 1.6), my - u, int(h * 0.12))
    stars = ((0.10, 0.08), (0.22, 0.16), (0.33, 0.06), (0.44, 0.12), (0.90, 0.10), (0.06, 0.22))
    for s in stars:
        buf.pen = color.rgb(FIREFLY_STAR[0], FIREFLY_STAR[1], FIREFLY_STAR[2], 150)
        buf.rectangle(int(w * s[0]), int(h * s[1]), max(1, u // 3), max(1, u // 3))
    for i in range(FIREFLY_MIST_BANDS):
        buf.pen = color.rgb(FIREFLY_MIST[0], FIREFLY_MIST[1], FIREFLY_MIST[2], 26)
        buf.rectangle(0, int(h * (0.52 + i * 0.055)), w, max(1, u))
    layers = ((0.62, (34, 64, 62), 5, 9, 0), (0.74, (20, 42, 44), 7, 13, 2),
              (0.90, (8, 20, 24), 10, 19, 5))
    for base_f, tint, span_u, tall, seed in layers:
        base = int(h * base_f)
        buf.pen = color.rgb(tint[0], tint[1], tint[2])
        buf.rectangle(0, base, w, h - base)
        span = u * span_u
        n = w // max(1, span) + 3
        for i in range(n):
            x = -span + i * span
            hh = (tall + ((i * 7 + seed) % 5) * 2) * u // 2
            buf.triangle(x - span, base + 1, x + span, base + 1, x, base - hh)
            buf.triangle(x - span * 3 // 4, base - hh // 3, x + span * 3 // 4, base - hh // 3,
                         x, base - int(hh * 1.25))
    buf.pen = color.rgb(*FIREFLY_TRUNK)
    buf.triangle(-u * 2, h, int(w * 0.22), h, int(w * 0.02), -u)
    buf.triangle(int(w * 0.86), h, w + u * 4, h, w + u, -u)
    buf.rectangle(int(w * 0.02), int(h * 0.30), max(1, u), h - int(h * 0.30))
    flies = ((0.14, 0.58), (0.31, 0.72), (0.50, 0.62), (0.63, 0.80), (0.85, 0.68),
             (0.40, 0.88), (0.72, 0.60), (0.22, 0.84))
    for i, f in enumerate(flies):
        x, y = int(w * f[0]), int(h * f[1])
        buf.pen = color.rgb(FIREFLY_GLOW[0], FIREFLY_GLOW[1], FIREFLY_GLOW[2], 34)
        buf.circle(x, y, max(1, int(u * (1.2 + (i % 3) * 0.4))))
        buf.pen = color.rgb(FIREFLY_BODY[0], FIREFLY_BODY[1], FIREFLY_BODY[2], 220)
        buf.rectangle(x, y, max(1, u // 2), max(1, u // 2))


def _g_firefly_wood_a(dst, t):
    """A wood full of them: a swarm blinking in relay through drifting mist,
    with two close enough to light the air around themselves."""
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    ang = t * 6.283185
    # Mist patches crossing the trunks. Each enters at the left before the one
    # ahead has left, so the band never empties and never jumps at the wrap.
    span = int(w * 0.55)
    for i in range(FIREFLY_MIST_BANDS):
        p = (t * FIREFLY_MIST_DRIFT + i / max(1, float(FIREFLY_MIST_BANDS))) % 1.0
        dst.pen = color.rgb(FIREFLY_MIST[0], FIREFLY_MIST[1], FIREFLY_MIST[2], 14)
        dst.rectangle(-span + int((w + span) * p), int(h * (0.52 + i * 0.06)),
                      span, max(2, u * 2))
    # The swarm. Offsets are a full permutation of the cycle, so exactly
    # `duty * count` of them are alight at any instant however long you watch.
    n = max(1, FIREFLY_FLIERS)
    for i in range(FIREFLY_FLIERS):
        p = (t * FIREFLY_BLINK_SPEED + ((i * 11) % n) / float(n)) % 1.0
        if p >= FIREFLY_BLINK_DUTY:
            continue
        b = math.sin(p / FIREFLY_BLINK_DUTY * 3.14159)
        drift = ang * FIREFLY_DRIFT_SPEED + i
        x = int(w * (((i * 73) % 97) / 97.0) + math.sin(drift) * w * 0.035)
        y = int(h * (0.40 + ((i * 29) % 53) / 53.0 * 0.52)
                + math.cos(drift * 2) * h * 0.03)
        a = int(40 + 200 * b)
        dst.pen = color.rgb(FIREFLY_GLOW[0], FIREFLY_GLOW[1], FIREFLY_GLOW[2], a // 4)
        dst.circle(x, y, max(1, int(u * 1.4)))
        dst.pen = color.rgb(FIREFLY_SPARK[0], FIREFLY_SPARK[1], FIREFLY_SPARK[2], a)
        dst.rectangle(x, y, max(1, u // 2), max(1, u // 2))
    for i in range(FIREFLY_NEAR):
        p = ang + i * 3.1
        b = 0.5 + 0.5 * math.sin(ang * 2 + i * 2.4)
        x = int(w * (0.24 + i * 0.46) + math.sin(p) * w * 0.09)
        y = int(h * (0.66 + i * 0.10) + math.cos(p * 2) * h * 0.05)
        dst.pen = color.rgb(FIREFLY_GLOW[0], FIREFLY_GLOW[1], FIREFLY_GLOW[2],
                            int(8 + 20 * b))
        dst.circle(x, y, max(2, int(u * 3.2)))
        dst.pen = color.rgb(FIREFLY_GLOW[0], FIREFLY_GLOW[1], FIREFLY_GLOW[2],
                            int(20 + 54 * b))
        dst.circle(x, y, max(1, int(u * 1.6)))
        dst.pen = color.rgb(FIREFLY_BODY[0], FIREFLY_BODY[1], FIREFLY_BODY[2],
                            int(120 + 135 * b))
        dst.rectangle(x, y, max(1, u), max(1, u // 2))


# @skinlab {"type":"color","label":"Deep space","group":"Palette"}
RIM_SPACE = (6, 5, 18)

# @skinlab {"type":"color","label":"Violet nebula","group":"Palette"}
RIM_NEBULA = (66, 28, 120)

# @skinlab {"type":"color","label":"Blue nebula","group":"Palette"}
RIM_NEBULA2 = (28, 62, 140)

# @skinlab {"type":"color","label":"Stars","group":"Palette"}
RIM_STAR = (226, 230, 255)

# @skinlab {"type":"integer","label":"Star count","group":"Layout","min":0,"max":110,"step":2}
RIM_STARS = 46

# @skinlab {"type":"color","label":"Planet","group":"Palette"}
RIM_PLANET = (228, 140, 96)

# @skinlab {"type":"number","label":"Planet size","group":"Layout","min":0.12,"max":0.36,"step":0.01}
RIM_PLANET_R = 0.27

# @skinlab {"type":"color","label":"Ring behind","group":"Palette"}
RIM_RING_BACK = (180, 150, 210)

# @skinlab {"type":"color","label":"Ring in front","group":"Palette"}
RIM_RING = (214, 186, 240)

# @skinlab {"type":"number","label":"Ring spread","group":"Layout","min":1.5,"max":3.2,"step":0.1}
RIM_RING_SPREAD = 2.3

# @skinlab {"type":"number","label":"Ring gap","group":"Layout","min":1.15,"max":2.4,"step":0.01}
RIM_RING_INNER = 1.42

# @skinlab {"type":"color","label":"Moon","group":"Palette"}
RIM_MOON = (120, 120, 150)

# @skinlab {"type":"integer","label":"Twinkle speed","group":"Motion","min":1,"max":10,"step":1}
RIM_TWINKLE_SPEED = 4

# @skinlab {"type":"boolean","label":"Shooting star","group":"Motion"}
RIM_COMET = True

# @skinlab {"type":"integer","label":"Twinkling stars","group":"Layout","min":0,"max":18,"step":1}
RIM_TWINKLES = 12

# @skinlab {"type":"color","label":"Ring ice","group":"Palette"}
RIM_SPARK = (255, 246, 232)

# @skinlab {"type":"integer","label":"Ring ice","group":"Layout","min":0,"max":16,"step":1}
RIM_SPARKS = 12

# Whole orbits per 4 s cycle: a fraction would teleport the ice at the wrap.
# @skinlab {"type":"integer","label":"Ring orbit","group":"Motion","min":1,"max":3,"step":1}
RIM_SPARK_SPEED = 1

# @skinlab {"type":"boolean","label":"Orbiting moonlet","group":"Motion"}
RIM_MOONLET = True

# @skinlab {"type":"integer","label":"Moonlet orbit","group":"Motion","min":1,"max":3,"step":1}
RIM_MOONLET_SPEED = 1

# @skinlab {"type":"color","label":"Freighter lights","group":"Palette"}
RIM_SHIP = (255, 170, 90)

# @skinlab {"type":"boolean","label":"Passing freighter","group":"Motion"}
RIM_FREIGHTER = True

# @skinlab {"type":"integer","label":"Freighter speed","group":"Motion","min":1,"max":3,"step":1}
RIM_FREIGHTER_SPEED = 1


def _g_outer_rim(buf):
    import math
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    buf.pen = color.rgb(*RIM_SPACE)
    buf.clear()
    neb = ((0.18, 0.26, 0.30), (0.26, 0.18, 0.22), (0.12, 0.16, 0.18), (0.30, 0.30, 0.14))
    for n in neb:
        buf.pen = color.rgb(RIM_NEBULA[0], RIM_NEBULA[1], RIM_NEBULA[2], 26)
        buf.circle(int(w * n[0]), int(h * n[1]), int(w * n[2]))
    neb2 = ((0.40, 0.10, 0.20), (0.32, 0.06, 0.14), (0.46, 0.16, 0.12))
    for n in neb2:
        buf.pen = color.rgb(RIM_NEBULA2[0], RIM_NEBULA2[1], RIM_NEBULA2[2], 24)
        buf.circle(int(w * n[0]), int(h * n[1]), int(w * n[2]))
    for i in range(RIM_STARS):
        x = int(w * (((i * 37) % 101) / 101.0))
        y = int(h * (((i * 61) % 97) / 97.0))
        b = 90 + (i % 4) * 55
        buf.pen = color.rgb(RIM_STAR[0], RIM_STAR[1], RIM_STAR[2], b)
        buf.rectangle(x, y, max(1, u // 3), max(1, u // 3))
    pcx, pcy = int(w * 0.60), int(h * 0.66)
    r = int(h * RIM_PLANET_R)
    ra, rb = r * RIM_RING_SPREAD, r * 0.66
    inner = RIM_RING_INNER
    ystep = max(1, int(rb / 9.0))
    yy = pcy - int(rb)
    while yy <= pcy + int(rb):
        dy = (yy - pcy) / rb
        if abs(dy) > 1.0:
            yy += ystep
            continue
        xo = ra * math.sqrt(max(0.0, 1.0 - dy * dy))
        di = (yy - pcy) / (rb / inner)
        xi = ra / inner * math.sqrt(max(0.0, 1.0 - di * di)) if abs(di) < 1.0 else 0.0
        seg = int(xo - xi)
        if seg > 0 and yy < pcy:
            buf.pen = color.rgb(RIM_RING_BACK[0], RIM_RING_BACK[1], RIM_RING_BACK[2], 150)
            buf.rectangle(int(pcx - xo), yy, seg, ystep)
            buf.rectangle(int(pcx + xi), yy, seg, ystep)
        yy += ystep
    buf.pen = color.rgb(52, 30, 78)
    buf.circle(pcx, pcy, r + max(1, u // 2))
    buf.pen = color.rgb(*RIM_PLANET)
    buf.circle(pcx, pcy, r)
    bands = ((0.62, (206, 106, 78)), (0.34, (242, 178, 126)), (0.06, (198, 92, 70)),
             (-0.22, (238, 164, 112)), (-0.5, (188, 84, 66)), (-0.76, (232, 152, 104)))
    for by, c in bands:
        span = int(r * math.sqrt(max(0.0, 1.0 - by * by)))
        yy = int(pcy - r * by)
        th = max(1, int(r * 0.14))
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(pcx - span, yy, span * 2, th)
    buf.pen = color.rgb(10, 6, 24, 130)
    buf.circle(pcx + int(r * 0.42), pcy + int(r * 0.30), int(r * 1.02))
    yy = pcy
    while yy <= pcy + int(rb):
        dy = (yy - pcy) / rb
        if abs(dy) > 1.0:
            break
        xo = ra * math.sqrt(max(0.0, 1.0 - dy * dy))
        di = (yy - pcy) / (rb / inner)
        xi = ra / inner * math.sqrt(max(0.0, 1.0 - di * di)) if abs(di) < 1.0 else 0.0
        seg = int(xo - xi)
        if seg > 0:
            buf.pen = color.rgb(RIM_RING[0], RIM_RING[1], RIM_RING[2], 170)
            buf.rectangle(int(pcx - xo), yy, seg, ystep)
            buf.rectangle(int(pcx + xi), yy, seg, ystep)
        yy += ystep
    buf.pen = color.rgb(*RIM_MOON)
    buf.circle(int(w * 0.16), int(h * 0.74), max(2, int(u * 2.2)))
    buf.pen = color.rgb(70, 70, 96)
    buf.circle(int(w * 0.16) - u, int(h * 0.74) - u // 2, max(1, int(u * 1.6)))


def _g_outer_rim_a(dst, t):
    """The system turns: ice in the ring runs round the planet and is eclipsed
    behind it, a moonlet keeps its own orbit, a freighter crosses the rim."""
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    s = _stroke(dst)
    ang = t * 6.283185
    pcx, pcy = int(w * 0.60), int(h * 0.66)
    r = int(h * RIM_PLANET_R)
    ra, rb = r * RIM_RING_SPREAD, r * 0.66
    for i in range(RIM_TWINKLES):
        b = math.sin(ang * RIM_TWINKLE_SPEED + i * 1.9)
        if b < 0.2:
            continue
        dst.pen = color.rgb(255, 255, 255, int(70 + 185 * b))
        dst.rectangle(int(w * (((i * 37) % 101) / 101.0)),
                      int(h * 0.02 + h * 0.30 * (((i * 29) % 89) / 89.0)), s * 2, s * 2)
    for i in range(RIM_SPARKS):
        a = (t * RIM_SPARK_SPEED + i / float(max(1, RIM_SPARKS))) * 6.283185
        dx = ra * math.cos(a)
        dy = rb * math.sin(a)
        if dy < 0 and dx * dx + dy * dy < r * r:
            continue                      # round the back, behind the planet
        front = 1.0 if dy > 0 else 0.55
        dst.pen = color.rgb(RIM_SPARK[0], RIM_SPARK[1], RIM_SPARK[2],
                            int((110 + 120 * (0.5 + 0.5 * math.sin(a * 3.0))) * front))
        dst.rectangle(int(pcx + dx), int(pcy + dy), max(1, s * 2), max(1, s))
    if RIM_MOONLET:
        a = (t * RIM_MOONLET_SPEED) * 6.283185
        mx = int(pcx + ra * 1.12 * math.cos(a))
        my = int(pcy + rb * 1.28 * math.sin(a))
        shade = 0.5 + 0.5 * math.cos(a)
        dst.pen = color.rgb(int(120 + 90 * shade), int(118 + 84 * shade),
                            int(140 + 80 * shade))
        dst.circle(mx, my, max(1, int(u * 0.9)))
        dst.pen = color.rgb(20, 14, 34, 170)
        dst.circle(mx + max(1, u // 2), my, max(1, int(u * 0.7)))
    if RIM_FREIGHTER:
        q = (t * RIM_FREIGHTER_SPEED) % 1.0
        fx = -int(w * 0.12) + int(w * 1.24 * q)
        fy = int(h * 0.30 + math.sin(q * 6.283185) * h * 0.015)
        dst.pen = color.rgb(60, 58, 78)
        dst.rectangle(fx, fy, max(2, int(u * 2.4)), max(1, s * 2))
        dst.pen = color.rgb(*RIM_SHIP)
        dst.rectangle(fx + max(2, int(u * 2.4)), fy, max(1, s * 2), max(1, s * 2))
        dst.pen = color.rgb(180, 220, 255, 200 if (t * 6.0) % 1.0 < 0.4 else 50)
        dst.rectangle(fx - max(1, s), fy - max(1, s), max(1, s * 2), max(1, s * 2))
    p = (t * 2.0) % 1.0
    if RIM_COMET and p < 0.3:
        q = p / 0.3
        x = int(w * (0.05 + 0.7 * q))
        y = int(h * (0.06 + 0.28 * q))
        dst.pen = color.rgb(255, 250, 220, int(230 - 150 * q))
        dst.line(x, y, x - int(w * 0.06), y - int(h * 0.05))
        dst.pen = color.rgb(255, 255, 255, 230)
        dst.rectangle(x, y, max(1, u // 2), max(1, u // 2))


# @skinlab {"type":"color","label":"Cloud crest","group":"Palette"}
STORM_CLOUD = (64, 68, 102)

# @skinlab {"type":"color","label":"Cloud belly","group":"Palette"}
STORM_CLOUD_DARK = (20, 22, 42)

# @skinlab {"type":"color","label":"Swell caps","group":"Palette"}
STORM_SWELL = (190, 220, 240)

# @skinlab {"type":"integer","label":"Swell rows","group":"Layout","min":0,"max":12,"step":1}
STORM_SWELLS = 9

# @skinlab {"type":"color","label":"Cliff","group":"Palette"}
STORM_CLIFF = (16, 16, 30)

# @skinlab {"type":"color","label":"Lighthouse","group":"Palette"}
STORM_TOWER = (226, 224, 216)

# @skinlab {"type":"color","label":"Tower stripes","group":"Palette"}
STORM_STRIPE = (198, 62, 58)

# @skinlab {"type":"color","label":"Ironwork","group":"Palette"}
STORM_IRON = (30, 30, 44)

# @skinlab {"type":"color","label":"Lamp","group":"Palette"}
STORM_LAMP = (255, 236, 150)

# @skinlab {"type":"color","label":"Beam","group":"Palette"}
STORM_BEAM = (255, 240, 170)

# Whole turns of the 4 s cycle. `t` wraps 1 -> 0, so a fractional rate
# restarts the motion part-way through and the loop visibly snaps.
# @skinlab {"type":"integer","label":"Beam sweep","group":"Motion","min":1,"max":6,"step":1}
STORM_BEAM_SPEED = 2

# @skinlab {"type":"boolean","label":"Lightning","group":"Motion"}
STORM_LIGHTNING = True

# @skinlab {"type":"integer","label":"Strike rate","group":"Motion","min":1,"max":8,"step":1}
STORM_STRIKE_RATE = 3

# @skinlab {"type":"color","label":"Lightning bolt","group":"Palette"}
STORM_BOLT = (230, 240, 255)

# @skinlab {"type":"color","label":"Rain","group":"Palette"}
STORM_RAIN_INK = (196, 216, 240)

# @skinlab {"type":"integer","label":"Raindrops","group":"Layout","min":0,"max":20,"step":1}
STORM_RAIN = 12

# @skinlab {"type":"integer","label":"Rain speed","group":"Motion","min":1,"max":6,"step":1}
STORM_RAIN_SPEED = 3

# @skinlab {"type":"number","label":"Wind tilt","group":"Motion","min":0.0,"max":0.4,"step":0.02}
STORM_RAIN_TILT = 0.16

# @skinlab {"type":"integer","label":"Working swell","group":"Layout","min":0,"max":10,"step":1}
STORM_CAPS = 6

# @skinlab {"type":"integer","label":"Swell beat","group":"Motion","min":1,"max":4,"step":1}
STORM_CAP_SPEED = 2

# @skinlab {"type":"integer","label":"Scudding cloud","group":"Layout","min":0,"max":6,"step":1}
STORM_SCUD = 3

# @skinlab {"type":"integer","label":"Scud speed","group":"Motion","min":1,"max":3,"step":1}
STORM_SCUD_SPEED = 1


def _g_storm_cape(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    sea = int(h * 0.56)
    step = max(1, h // 90)
    for y in range(0, sea, step):
        f = y / sea
        buf.pen = color.rgb(int(12 + 40 * f), int(16 + 44 * f), int(30 + 62 * f))
        buf.rectangle(0, y, w, step)
    clouds = ((0.10, 0.06, 0.20), (0.26, 0.10, 0.16), (0.44, 0.04, 0.22), (0.66, 0.09, 0.18),
              (0.86, 0.05, 0.20), (0.18, 0.16, 0.14), (0.56, 0.17, 0.16), (0.78, 0.19, 0.14))
    for c in clouds:
        buf.pen = color.rgb(STORM_CLOUD[0], STORM_CLOUD[1], STORM_CLOUD[2], 150)
        buf.circle(int(w * c[0]), int(h * c[1]), int(w * c[2] * 0.5))
    for c in clouds:
        buf.pen = color.rgb(STORM_CLOUD_DARK[0], STORM_CLOUD_DARK[1], STORM_CLOUD_DARK[2], 235)
        buf.circle(int(w * c[0]), int(h * c[1]) + max(1, u // 2), int(w * c[2] * 0.5))
    buf.pen = color.rgb(18, 20, 38)
    buf.rectangle(0, 0, w, int(h * 0.07))
    buf.pen = color.rgb(140, 160, 200, 60)
    buf.rectangle(0, sea - max(1, u // 2), w, max(1, u // 2))
    for y in range(sea, h, step):
        f = (y - sea) / max(1, h - sea)
        buf.pen = color.rgb(int(20 - 12 * f), int(34 - 18 * f), int(58 - 26 * f))
        buf.rectangle(0, y, w, step)
    for i in range(STORM_SWELLS):
        yy = sea + int((h - sea) * (i * i + 2) / 90.0)
        ln = max(1, u + i)
        buf.pen = color.rgb(STORM_SWELL[0], STORM_SWELL[1], STORM_SWELL[2], 70 + i * 12)
        for k in range(3):
            buf.rectangle(int(w * ((k * 0.34 + i * 0.17) % 1.0)), yy, ln * 2, max(1, u // 3))
    cx = int(w * 0.74)
    cliff = int(h * 0.66)
    buf.pen = color.rgb(*STORM_CLIFF)
    buf.rectangle(int(w * 0.56), cliff, w - int(w * 0.56), h - cliff)
    buf.triangle(int(w * 0.40), h, int(w * 0.56), h, int(w * 0.56), cliff)
    buf.triangle(int(w * 0.56), cliff, w, cliff, int(w * 0.86), int(h * 0.60))
    buf.pen = color.rgb(96, 120, 160, 130)
    buf.rectangle(int(w * 0.56), cliff, w - int(w * 0.56), max(1, u // 3))
    buf.pen = color.rgb(8, 8, 18)
    buf.triangle(int(w * 0.46), h, int(w * 0.70), h, int(w * 0.60), int(h * 0.78))
    buf.circle(int(w * 0.30), h + int(u * 2), int(u * 5))
    tw = max(2, int(u * 2.6))
    ty = int(h * 0.32)
    by = int(h * 0.70)
    buf.pen = color.rgb(*STORM_TOWER)
    buf.triangle(cx - tw, by, cx + tw, by, cx, ty - u * 4)
    buf.pen = color.rgb(*STORM_STRIPE)
    for i in range(3):
        yb = ty + int((by - ty) * (0.18 + i * 0.28))
        ww = int(tw * 2 * (0.42 + 0.2 * i))
        buf.rectangle(cx - ww // 2, yb, ww, max(1, int(u * 0.9)))
    buf.pen = color.rgb(*STORM_IRON)
    buf.rectangle(cx - max(1, int(tw * 0.8)), ty - u, max(2, int(tw * 1.6)), max(2, int(u * 1.2)))
    buf.pen = color.rgb(*STORM_LAMP)
    buf.rectangle(cx - max(1, int(tw * 0.55)), ty - u * 3, max(1, int(tw * 1.1)), max(2, u * 2))
    for i in range(5):
        buf.pen = color.rgb(255, 230, 140, 11)
        buf.circle(cx, ty - u * 2, int(u * (6.0 - i * 1.0)))
    buf.pen = color.rgb(*STORM_IRON)
    buf.triangle(cx - int(tw * 0.9), ty - u * 4, cx + int(tw * 0.9), ty - u * 4, cx, ty - u * 7)


def _g_storm_cape_a(dst, t):
    """It is weather, so it should be weather: rain driving in off the sea,
    cloud scudding over the cape, the swell working, the lamp turning, and
    lightning when it comes."""
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    s = _stroke(dst)
    turn = t * 6.283185
    cx = int(w * 0.74)
    ty = int(h * 0.32) - u * 2
    sea = int(h * 0.56)
    for i in range(STORM_SCUD):
        q = (t * STORM_SCUD_SPEED + i / float(max(1, STORM_SCUD))) % 1.0
        dst.pen = color.rgb(STORM_CLOUD_DARK[0], STORM_CLOUD_DARK[1],
                            STORM_CLOUD_DARK[2], 110)
        dst.circle(-int(w * 0.18) + int(w * 1.36 * q),
                   int(h * (0.035 + 0.045 * (i % 3))), int(w * 0.10))
    for i in range(STORM_CAPS):
        bob = math.sin(turn * STORM_CAP_SPEED + i * 1.9)
        row = ((i * 5) % 7) / 7.0
        dst.pen = color.rgb(STORM_SWELL[0], STORM_SWELL[1], STORM_SWELL[2],
                            int(50 + 110 * (0.5 + 0.5 * bob)))
        dst.rectangle(int(w * (((i * 23) % 13) / 13.0) + bob * u * 3),
                      sea + int((h - sea) * (0.10 + 0.78 * row)) + int(bob * u),
                      max(2, int(u * (3.0 + 1.4 * (i % 3)))), max(1, u // 3))
    p = (t * STORM_BEAM_SPEED) % 1.0
    swing = p * 2.0 - 1.0
    dx = swing * w * 1.2
    dst.pen = color.rgb(STORM_BEAM[0], STORM_BEAM[1], STORM_BEAM[2],
                        max(10, int(70 * (1.0 - abs(swing) * 0.6))))
    dst.triangle(cx, ty, int(cx + dx - w * 0.12), int(ty + h * 0.30),
                 int(cx + dx + w * 0.12), int(ty + h * 0.30))
    dst.pen = color.rgb(255, 250, 210, 200)
    dst.circle(cx, ty, max(1, u))
    f = (t * STORM_STRIKE_RATE) % 1.0
    if STORM_LIGHTNING and f < 0.05:
        dst.pen = color.rgb(200, 220, 255, 90 if f < 0.025 else 40)
        dst.rectangle(0, 0, w, int(h * 0.56))
        dst.pen = color.rgb(STORM_BOLT[0], STORM_BOLT[1], STORM_BOLT[2], 220)
        dst.line(int(w * 0.22), 0, int(w * 0.28), int(h * 0.20))
        dst.line(int(w * 0.28), int(h * 0.20), int(w * 0.20), int(h * 0.38))
        dst.line(int(w * 0.26), int(h * 0.14), int(w * 0.34), int(h * 0.26))
        dst.pen = color.rgb(STORM_BOLT[0], STORM_BOLT[1], STORM_BOLT[2], 120)
        dst.rectangle(int(w * 0.14), sea - max(1, u // 3), int(w * 0.16), max(1, u // 3))
    # Rain last, so it falls in front of everything including the beam. A bare
    # `line()` is the right call here: thinness IS the mark.
    n = max(1, STORM_RAIN)
    for i in range(STORM_RAIN):
        q = (t * STORM_RAIN_SPEED + ((i * 7) % n) / float(n)) % 1.0
        x = ((i * 53) % w) - int(w * STORM_RAIN_TILT * q)
        y = int(h * 1.06 * q) - int(h * 0.06)
        dst.pen = color.rgb(STORM_RAIN_INK[0], STORM_RAIN_INK[1], STORM_RAIN_INK[2],
                            90 + (i % 3) * 45)
        dst.line(x, y, x - max(1, u), y + max(2, int(u * 2.6)))
    dst.pen = color.rgb(STORM_RAIN_INK[0], STORM_RAIN_INK[1], STORM_RAIN_INK[2], 40)
    dst.rectangle(0, sea, w, s)


# @skinlab {"type":"color","label":"Tunnel void","group":"Palette"}
TRAIN_DARK = (10, 9, 14)

# @skinlab {"type":"integer","label":"Tunnel rings","group":"Layout","min":4,"max":18,"step":1}
TRAIN_RINGS = 13

# @skinlab {"type":"color","label":"Tunnel haze","group":"Palette"}
TRAIN_HAZE = (150, 128, 80)

# @skinlab {"type":"color","label":"Far lamp","group":"Palette"}
TRAIN_LAMP = (255, 236, 180)

# @skinlab {"type":"color","label":"Sleepers","group":"Palette"}
TRAIN_SLEEPER = (40, 34, 30)

# @skinlab {"type":"color","label":"Rails","group":"Palette"}
TRAIN_RAIL = (180, 166, 130)

# @skinlab {"type":"color","label":"Tunnel lights","group":"Palette"}
TRAIN_LIGHT = (255, 226, 150)

# @skinlab {"type":"color","label":"Platform","group":"Palette"}
TRAIN_PLATFORM = (20, 18, 24)

# @skinlab {"type":"color","label":"Platform edge","group":"Palette"}
TRAIN_EDGE = (150, 126, 46)

# @skinlab {"type":"number","label":"Platform line","group":"Layout","min":0.74,"max":0.97,"step":0.01}
TRAIN_PLATFORM_Y = 0.90

# @skinlab {"type":"color","label":"Approach glow","group":"Palette"}
TRAIN_GLOW = (255, 230, 160)

# @skinlab {"type":"color","label":"Headlights","group":"Palette"}
TRAIN_BEAM = (255, 246, 210)

# Whole turns of the 4 s cycle. `t` wraps 1 -> 0, so a fractional rate
# restarts the motion part-way through and the loop visibly snaps.
# @skinlab {"type":"integer","label":"Approach speed","group":"Motion","min":1,"max":4,"step":1}
TRAIN_APPROACH_SPEED = 1

# @skinlab {"type":"boolean","label":"Passing carriage","group":"Motion"}
TRAIN_STROBE = True

# @skinlab {"type":"integer","label":"Rushing ribs","group":"Layout","min":0,"max":6,"step":1}
TRAIN_RIBS = 4

# @skinlab {"type":"integer","label":"Rushing lamps","group":"Layout","min":0,"max":8,"step":1}
TRAIN_RUSH_LAMPS = 4

# @skinlab {"type":"integer","label":"Rail glints","group":"Layout","min":0,"max":6,"step":1}
TRAIN_GLINTS = 2

# Whole turns of the 4 s cycle, so a rib is back where it started at the wrap.
# @skinlab {"type":"integer","label":"Tunnel rush","group":"Motion","min":1,"max":4,"step":1}
TRAIN_RUSH_SPEED = 1


def _g_last_train(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    vx, vy = int(w * 0.48), int(h * 0.56)
    buf.pen = color.rgb(*TRAIN_DARK)
    buf.clear()
    n = TRAIN_RINGS
    for i in range(n):
        k = 1.0 - i / float(n)
        k = k * k
        rw = int(w * 0.62 * k) + int(w * 0.05)
        rh = int(h * 0.62 * k) + int(h * 0.05)
        g = i / float(n)
        buf.pen = color.rgb(int(26 + 150 * g * g), int(30 + 116 * g * g), int(40 + 44 * g))
        buf.rectangle(vx - rw, vy - rh, rw * 2, rh * 2)
        buf.pen = color.rgb(*TRAIN_DARK)
        rw2 = int(rw * 0.86)
        rh2 = int(rh * 0.86)
        buf.rectangle(vx - rw2, vy - rh2, rw2 * 2, rh2 * 2)
    buf.pen = color.rgb(TRAIN_HAZE[0], TRAIN_HAZE[1], TRAIN_HAZE[2], 60)
    buf.circle(vx, vy, int(h * 0.14))
    buf.pen = color.rgb(*TRAIN_LAMP)
    buf.circle(vx, vy, max(1, int(u * 0.8)))
    buf.pen = color.rgb(8, 7, 12)
    buf.triangle(0, h, int(w * 0.30), h, vx, vy)
    buf.triangle(w, h, int(w * 0.70), h, vx, vy)
    for i in range(9):
        k = (i + 1) / 10.0
        k = k * k
        yy = int(vy + (h - vy) * k)
        ww = int((w * 0.5) * k)
        buf.pen = color.rgb(*TRAIN_SLEEPER)
        buf.rectangle(vx - ww, yy, ww * 2, max(1, int(u * k * 2)))
    for s in (-1, 1):
        prev_x, prev_y = vx + s * max(1, u // 2), vy
        for i in range(7):
            k = (i + 1) / 7.0
            k = k * k
            yy = int(vy + (h - vy) * k)
            xx = int(vx + s * (u // 2 + (w * 0.34) * k))
            buf.pen = color.rgb(*TRAIN_RAIL)
            buf.line(prev_x, prev_y, xx, yy)
            buf.line(prev_x + s, prev_y, xx + s, yy)
            prev_x, prev_y = xx, yy
    lights = ((0.30, 0.32), (0.60, 0.66), (0.82, 0.88))
    for lk in lights:
        kk = lk[0] * lk[0]
        lw = int(w * 0.10 * (0.3 + kk))
        yy = int(vy - vy * (0.35 + 0.6 * kk))
        buf.pen = color.rgb(TRAIN_LIGHT[0], TRAIN_LIGHT[1], TRAIN_LIGHT[2], 200)
        buf.rectangle(vx - lw // 2, yy, lw, max(1, int(u * (0.4 + kk))))
        buf.pen = color.rgb(255, 210, 130, 40)
        buf.rectangle(vx - lw, yy - max(1, u // 2), lw * 2, max(2, int(u * (1.0 + kk))))
    buf.pen = color.rgb(*TRAIN_PLATFORM)
    buf.rectangle(0, int(h * TRAIN_PLATFORM_Y), w, h)
    buf.pen = color.rgb(*TRAIN_EDGE)
    buf.rectangle(0, int(h * TRAIN_PLATFORM_Y), w, max(1, u // 3))


def _g_last_train_a(dst, t):
    """The whole tunnel rushes past, not just the lamp: ribs and ceiling lights
    stream out of the vanishing point, the rails pick up the glare, and the
    headlamps swell out of the dark behind them."""
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    vx, vy = int(w * 0.48), int(h * 0.56)
    rush = t * TRAIN_RUSH_SPEED
    # Tunnel ribs: a whole section frame at a time, on the same squared
    # perspective ramp `render` builds its static rings from, so each one grows
    # out of the vanishing point and washes off the edges of the screen.
    n = max(1, TRAIN_RIBS)
    for i in range(TRAIN_RIBS):
        q = (rush + i / float(n)) % 1.0
        k = q * q
        rw = int(w * 0.62 * k) + int(w * 0.05)
        rh = int(h * 0.62 * k) + int(h * 0.05)
        th = max(1, int(u * (0.4 + k)))
        dst.pen = color.rgb(TRAIN_HAZE[0], TRAIN_HAZE[1], TRAIN_HAZE[2],
                            int(190 * (1.0 - k)))
        dst.rectangle(vx - rw, vy - rh, rw * 2, th)
        dst.rectangle(vx - rw, vy + rh - th, rw * 2, th)
        dst.rectangle(vx - rw, vy - rh, th, rh * 2)
        dst.rectangle(vx + rw - th, vy - rh, th, rh * 2)
    n = max(1, TRAIN_RUSH_LAMPS)
    for i in range(TRAIN_RUSH_LAMPS):
        q = (rush + i / float(n)) % 1.0
        k = q * q
        lw = int(w * 0.10 * (0.3 + k))
        dst.pen = color.rgb(TRAIN_LIGHT[0], TRAIN_LIGHT[1], TRAIN_LIGHT[2],
                            int(210 * (1.0 - k * k)))
        dst.rectangle(vx - lw // 2, int(vy - vy * (0.35 + 0.6 * k)), lw,
                      max(1, int(u * (0.3 + k))))
    for sg in (-1, 1):
        for i in range(TRAIN_GLINTS):
            q = (rush + i / float(max(1, TRAIN_GLINTS)) + 0.11) % 1.0
            k = q * q
            gx = int(vx + sg * (u // 2 + (w * 0.34) * k))
            dst.pen = color.rgb(TRAIN_BEAM[0], TRAIN_BEAM[1], TRAIN_BEAM[2],
                                int(60 + 190 * (1.0 - k)))
            dst.rectangle(gx - int(u * k), int(vy + (h - vy) * k),
                          max(1, int(u * (0.5 + k * 2.4))), max(1, int(u * (0.3 + k))))
    p = (t * TRAIN_APPROACH_SPEED) % 1.0
    k = p * p
    # The last sixth of the run washes the approach out instead of letting a
    # full-size pair of headlamps snap back to two pixels at the wrap.
    fade = 1.0 if p < 0.84 else (1.0 - p) / 0.16
    gr = int(u + h * 0.22 * k)
    dst.pen = color.rgb(TRAIN_GLOW[0], TRAIN_GLOW[1], TRAIN_GLOW[2],
                        int((30 + 90 * k) * fade))
    dst.circle(vx, vy, gr)
    dst.pen = color.rgb(TRAIN_BEAM[0], TRAIN_BEAM[1], TRAIN_BEAM[2], int(230 * fade))
    dst.circle(vx - int(gr * 0.35), vy, max(1, int(u * (0.5 + k * 1.6))))
    dst.circle(vx + int(gr * 0.35), vy, max(1, int(u * (0.5 + k * 1.6))))
    if TRAIN_STROBE and (t * 9.0) % 1.0 < 0.2:
        dst.pen = color.rgb(20, 16, 20, 200)
        dst.rectangle(vx - int(w * 0.05), int(vy - vy * 0.62), int(w * 0.10), max(1, u))
        dst.pen = color.rgb(TRAIN_LIGHT[0], TRAIN_LIGHT[1], TRAIN_LIGHT[2], 150)
        dst.rectangle(vx - int(w * 0.03), int(vy - vy * 0.60), int(w * 0.06),
                      max(1, u // 2))


# @skinlab {"type":"color","label":"Void","group":"Palette"}
MOSH_VOID = (9, 6, 20)

# @skinlab {"type":"color","label":"Magenta block","group":"Palette"}
MOSH_MAGENTA = (255, 32, 128)

# @skinlab {"type":"color","label":"Cyan block","group":"Palette"}
MOSH_CYAN = (0, 232, 255)

# @skinlab {"type":"color","label":"Lime block","group":"Palette"}
MOSH_LIME = (168, 255, 40)

# @skinlab {"type":"color","label":"Amber block","group":"Palette"}
MOSH_AMBER = (255, 190, 0)

# @skinlab {"type":"color","label":"Violet block","group":"Palette"}
MOSH_VIOLET = (150, 60, 255)

# @skinlab {"type":"color","label":"Still tear, cold","group":"Palette"}
MOSH_TEAR_CYAN = (0, 255, 255)

# @skinlab {"type":"color","label":"Still tear, hot","group":"Palette"}
MOSH_TEAR_PINK = (255, 0, 160)

# @skinlab {"type":"color","label":"Name panel shade","group":"Palette"}
MOSH_SCRIM = (8, 4, 18)

# @skinlab {"type":"color","label":"Name panel rules","group":"Palette"}
MOSH_RULE = (235, 245, 255)

# @skinlab {"type":"color","label":"Moving tear, cold","group":"Palette"}
MOSH_SHIFT_CYAN = (0, 240, 255)

# @skinlab {"type":"color","label":"Moving tear, hot","group":"Palette"}
MOSH_SHIFT_PINK = (255, 20, 140)

# @skinlab {"type":"integer","label":"Band height","group":"Shape","min":1,"max":6,"step":1}
MOSH_BLOCK_H = 2

# @skinlab {"type":"integer","label":"Dropout rate","group":"Shape","min":2,"max":12,"step":1}
MOSH_HOLE = 5

# @skinlab {"type":"integer","label":"Tear rate","group":"Motion","min":1,"max":24,"step":1}
MOSH_TEAR_RATE = 12

# @skinlab {"type":"integer","label":"Moving tears","group":"Layout","min":1,"max":8,"step":1}
MOSH_TEARS = 5

# @skinlab {"type":"integer","label":"Displaced blocks","group":"Layout","min":0,"max":14,"step":1}
MOSH_BLOCKS = 10

# @skinlab {"type":"integer","label":"Drag smears","group":"Layout","min":0,"max":6,"step":1}
MOSH_SMEARS = 4


def _g_datamosh(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    buf.pen = color.rgb(*MOSH_VOID)
    buf.clear()
    tints = (MOSH_MAGENTA, MOSH_CYAN, MOSH_LIME, MOSH_AMBER, MOSH_VIOLET)
    y, i = 0, 0
    while y < h:
        bh = max(2, u * (MOSH_BLOCK_H + (i * 7) % 5))
        base = tints[i % 5]
        x, j = -((i * 13 * u) % max(1, w // 2)), 0
        while x < w:
            bw = max(2, u * (2 + (i * 5 + j * 3) % 7))
            if (i * 3 + j * 7) % MOSH_HOLE == 0:
                x += bw
                j += 1
                continue
            s = 55 + ((i * 37 + j * 53) % 5) * 45
            buf.pen = color.rgb(base[0] * s // 255, base[1] * s // 255, base[2] * s // 255)
            buf.rectangle(x, y, bw, bh)
            x += bw
            j += 1
        buf.pen = color.rgb(MOSH_TEAR_CYAN[0], MOSH_TEAR_CYAN[1], MOSH_TEAR_CYAN[2], 70)
        buf.rectangle(-u * 2 + ((i * 11) % 5) * u, y + bh // 3, w, max(1, bh // 3))
        buf.pen = color.rgb(MOSH_TEAR_PINK[0], MOSH_TEAR_PINK[1], MOSH_TEAR_PINK[2], 70)
        buf.rectangle(u * 2 - ((i * 7) % 5) * u, y + bh // 2, w, max(1, bh // 4))
        y += bh
        i += 1
    buf.pen = color.rgb(MOSH_SCRIM[0], MOSH_SCRIM[1], MOSH_SCRIM[2], 105)
    buf.rectangle(0, int(h * 0.23), w, int(h * 0.25))
    buf.pen = color.rgb(MOSH_RULE[0], MOSH_RULE[1], MOSH_RULE[2], 200)
    buf.rectangle(0, int(h * 0.23), w, max(1, u // 4))
    buf.rectangle(0, int(h * 0.48), w, max(1, u // 4))


def _g_datamosh_a(dst, t):
    """A decode coming apart three ways at once.

    Tears are the row shifts it already had.  What makes it read as a MOSH
    rather than as two sliding bars is the other two: blocks pasted in from
    somewhere else in the frame -- the palette's own colours, at hashed
    positions, so they look like the picture's own macroblocks in the wrong
    place -- and drags, where one block's colour is held across a run of the
    row because the motion vector never got its residual.  Everything hangs
    off `k`, a stepped clock, so the frame HOLDS and then breaks again.
    """
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    tints = (MOSH_MAGENTA, MOSH_CYAN, MOSH_LIME, MOSH_AMBER, MOSH_VIOLET)
    k = int(t * MOSH_TEAR_RATE)
    for i in range(MOSH_TEARS):
        j = (k * 5 + i * 7) % 9
        y = int(h * j / 9.0)
        bh = max(2, u * (1 + j % 3))
        sh = ((k * 13 + i * 29) % 11 - 5) * u
        dst.pen = color.rgb(MOSH_SHIFT_CYAN[0], MOSH_SHIFT_CYAN[1], MOSH_SHIFT_CYAN[2], 205)
        dst.rectangle(sh, y, w, bh)
        dst.pen = color.rgb(MOSH_SHIFT_PINK[0], MOSH_SHIFT_PINK[1], MOSH_SHIFT_PINK[2], 205)
        dst.rectangle(-sh, y + bh, w, max(1, bh // 2))
    for i in range(MOSH_BLOCKS):
        c = tints[(k + i) % 5]
        s = 90 + ((k * 7 + i * 53) % 4) * 55
        dst.pen = color.rgb(c[0] * s // 255, c[1] * s // 255, c[2] * s // 255)
        dst.rectangle(((k * 11 + i * 29) % 23) * w // 23, ((k * 5 + i * 37) % 19) * h // 19,
                      u * (2 + (i * 3) % 5), u * (1 + i % 3))
    for i in range(MOSH_SMEARS):
        c = tints[(k * 3 + i * 2) % 5]
        y = ((k * 17 + i * 41) % 13) * h // 13
        x = ((k * 23 + i * 7) % 9) * w // 9
        dst.pen = color.rgb(c[0], c[1], c[2], 150)
        dst.rectangle(x, y, w // 3 + (i % 3) * u * 4, max(1, u // 2))
    if k % 4 == 0:
        dst.pen = color.rgb(240, 250, 255, 220)
        dst.rectangle(0, int(h * ((k * 0.17) % 1.0)), w, max(1, u // 2))


# @skinlab {"type":"color","label":"Void","group":"Palette"}
CODE_VOID = (1, 7, 5)

# @skinlab {"type":"color","label":"Screen halo","group":"Palette"}
CODE_HALO = (0, 80, 50)

# @skinlab {"type":"color","label":"Glyph green","group":"Palette"}
CODE_GREEN = (40, 255, 110)

# @skinlab {"type":"color","label":"Glyph blue","group":"Palette"}
CODE_BLUE = (40, 210, 255)

# @skinlab {"type":"color","label":"Glyph pink","group":"Palette"}
CODE_PINK = (255, 40, 170)

# @skinlab {"type":"color","label":"Leading glyph","group":"Palette"}
CODE_HEAD = (225, 255, 240)

# @skinlab {"type":"color","label":"Falling trail","group":"Palette"}
CODE_TRAIL = (70, 250, 150)

# @skinlab {"type":"color","label":"Trail tail","group":"Palette"}
CODE_TRAIL_DIM = (25, 165, 90)

# @skinlab {"type":"color","label":"Name panel shade","group":"Palette"}
CODE_SCRIM = (0, 14, 9)

# @skinlab {"type":"color","label":"Name panel rules","group":"Palette"}
CODE_RULE = (60, 255, 150)

# @skinlab {"type":"integer","label":"Glyph columns","group":"Layout","min":4,"max":24,"step":1}
CODE_COLUMNS = 12

# @skinlab {"type":"integer","label":"Glyph rows","group":"Layout","min":6,"max":32,"step":1}
CODE_ROWS = 16

# @skinlab {"type":"integer","label":"Falling streams","group":"Layout","min":1,"max":8,"step":1}
CODE_STREAMS = 8

# @skinlab {"type":"integer","label":"Trail glyphs","group":"Layout","min":1,"max":3,"step":1}
CODE_TRAIL_LEN = 3

# @skinlab {"type":"integer","label":"Flickering glyphs","group":"Layout","min":0,"max":4,"step":1}
CODE_FLICKERS = 2

# @skinlab {"type":"integer","label":"Flicker rate","group":"Motion","min":2,"max":40,"step":1}
CODE_FLICKER_RATE = 18

# Whole falls per loop. The per-stream variation below adds INTEGERS to this
# for the same reason: at 1.35 a stream is two thirds of the way down the
# screen when `t` wraps, and jumps to the top of it every four seconds.
# @skinlab {"type":"integer","label":"Falls per loop","group":"Motion","min":1,"max":4,"step":1}
CODE_FALL_SPEED = 1


def _g_code_rain(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    buf.pen = color.rgb(*CODE_VOID)
    buf.clear()
    for i in range(3):
        buf.pen = color.rgb(CODE_HALO[0], CODE_HALO[1], CODE_HALO[2], 30)
        buf.circle(w // 2, int(h * 0.46), int(h * (0.78 - i * 0.19)))
    cw = max(3, w // CODE_COLUMNS)
    gap = max(1, cw // 5)
    bw = cw - gap
    bh = max(2, h // CODE_ROWS)
    bhg = max(1, bh - max(1, bh // 4))
    for c in range(CODE_COLUMNS):
        x = c * cw + gap // 2
        seed = (c * 37 + 11) % 29
        head = (seed * 13) % (h + bh)
        run = 7 + seed % 8
        if c % 7 == 3:
            base = CODE_BLUE
        elif c % 11 == 5:
            base = CODE_PINK
        else:
            base = CODE_GREEN
        for k in range(run):
            y = (head - k * bh) % (h + bh)
            if y >= h:
                continue
            if (seed * 3 + k * 7) % 11 == 0:
                continue
            f = 235 - k * 200 // run
            buf.pen = color.rgb(base[0] * f // 255, base[1] * f // 255, base[2] * f // 255)
            buf.rectangle(x, y, bw, bhg)
        if head < h:
            buf.pen = color.rgb(*CODE_HEAD)
            buf.rectangle(x, head, bw, bhg)
    for y in range(0, h, max(2, u // 2)):
        buf.pen = color.rgb(0, 0, 0, 70)
        buf.rectangle(0, y, w, _stroke(buf))
    buf.pen = color.rgb(CODE_SCRIM[0], CODE_SCRIM[1], CODE_SCRIM[2], 140)
    buf.rectangle(0, int(h * 0.22), w, int(h * 0.26))
    buf.pen = color.rgb(CODE_RULE[0], CODE_RULE[1], CODE_RULE[2], 130)
    buf.rectangle(0, int(h * 0.22), w, max(1, u // 4))
    buf.rectangle(0, int(h * 0.48), w, max(1, u // 4))


def _g_code_rain_a(dst, t):
    """Eight streams falling, each with a tail that fades behind its head.

    Three cells was a head and a hint; four reads as a stream, and eight
    columns of it is enough that the screen never looks parked. The tail
    interpolates between the two trail colours rather than stepping through
    two fixed ones, so lengthening it stays coherent. The per-stream speeds
    are INTEGER multiples: a stream at 1.35 falls is halfway down the screen
    when `t` wraps and jumps to the top of it.
    """
    w, h = dst.width, dst.height
    cw = max(3, w // CODE_COLUMNS)
    gap = max(1, cw // 5)
    bw = cw - gap
    bh = max(2, h // CODE_ROWS)
    bhg = max(1, bh - max(1, bh // 4))
    for i in range(CODE_STREAMS):
        c = (i * 5 + 2) % CODE_COLUMNS
        sp = CODE_FALL_SPEED + (i * 7) % 3
        y = int(((t * sp + i * 0.37) % 1.0) * (h + 4 * bh)) - 2 * bh
        x = c * cw + gap // 2
        dst.pen = color.rgb(*CODE_HEAD)
        dst.rectangle(x, y, bw, bhg)
        for j in range(CODE_TRAIL_LEN):
            f = 200 - j * 150 // CODE_TRAIL_LEN
            dst.pen = color.rgb(CODE_TRAIL[0] + (CODE_TRAIL_DIM[0] - CODE_TRAIL[0]) * j // CODE_TRAIL_LEN,
                                CODE_TRAIL[1] + (CODE_TRAIL_DIM[1] - CODE_TRAIL[1]) * j // CODE_TRAIL_LEN,
                                CODE_TRAIL[2] + (CODE_TRAIL_DIM[2] - CODE_TRAIL[2]) * j // CODE_TRAIL_LEN,
                                f)
            dst.rectangle(x, y - (j + 1) * bh, bw, bhg)
    k = int(t * CODE_FLICKER_RATE)
    for i in range(CODE_FLICKERS):
        c = (k * 3 + i * 11) % CODE_COLUMNS
        dst.pen = color.rgb(CODE_HEAD[0], CODE_HEAD[1], CODE_HEAD[2], 210)
        dst.rectangle(c * cw + gap // 2, bh * ((k * 5 + i * 7) % CODE_ROWS), bw, bhg)


# @skinlab {"type":"color","label":"Board","group":"Palette"}
TRACE_BOARD = (3, 15, 24)

# @skinlab {"type":"color","label":"Graticule","group":"Palette"}
TRACE_GRATICULE = (0, 90, 110)

# @skinlab {"type":"color","label":"Bus","group":"Palette"}
TRACE_BUS = (0, 150, 175)

# @skinlab {"type":"color","label":"Trace","group":"Palette"}
TRACE_INK = (0, 190, 200)

# @skinlab {"type":"color","label":"Chip body","group":"Palette"}
TRACE_CHIP = (10, 14, 18)

# @skinlab {"type":"color","label":"Chip pins","group":"Palette"}
TRACE_GOLD = (220, 190, 80)

# @skinlab {"type":"color","label":"Vias","group":"Palette"}
TRACE_VIA = (255, 130, 220)

# @skinlab {"type":"integer","label":"Graticule columns","group":"Layout","min":3,"max":16,"step":1}
TRACE_GRID = 8

# @skinlab {"type":"integer","label":"Trace count","group":"Layout","min":2,"max":9,"step":1}
TRACE_LINES = 8

# @skinlab {"type":"integer","label":"Via count","group":"Layout","min":0,"max":16,"step":1}
TRACE_VIAS = 9

# @skinlab {"type":"integer","label":"Pin count","group":"Layout","min":2,"max":12,"step":1}
TRACE_PINS = 6

# @skinlab {"type":"number","label":"Chip width","group":"Shape","min":0.18,"max":0.4,"step":0.02}
TRACE_CHIP_W = 0.30

# @skinlab {"type":"number","label":"Packet speed","group":"Motion","min":0.25,"max":4,"step":0.25}
TRACE_PACKET_SPEED = 1.0

# @skinlab {"type":"boolean","label":"Blinking vias","group":"Motion"}
TRACE_BLINK = True

# @skinlab {"type":"integer","label":"Signal packets","group":"Motion","min":0,"max":8,"step":1}
TRACE_SIGNALS = 4

# @skinlab {"type":"integer","label":"Live vias","group":"Motion","min":0,"max":9,"step":1}
TRACE_LIVE_VIAS = 5

# @skinlab {"type":"number","label":"Via blink rate","group":"Motion","min":1,"max":8,"step":1}
TRACE_VIA_RATE = 3.0

# @skinlab {"type":"number","label":"Clock rate","group":"Motion","min":1,"max":8,"step":1}
TRACE_CLOCK_RATE = 4.0


def _g_trace_map(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    bus = (0.18, 0.42, 0.66, 0.88)
    tw = max(1, u // 3)
    step = max(1, h // 60)
    for y in range(0, h, step):
        f = y * 255 // max(1, h - 1)
        buf.pen = color.rgb(TRACE_BOARD[0] + 7 * f // 255,
                            TRACE_BOARD[1] + 12 * f // 255,
                            TRACE_BOARD[2] + 16 * f // 255)
        buf.rectangle(0, y, w, step)
    for i in range(1, TRACE_GRID):
        buf.pen = color.rgb(TRACE_GRATICULE[0], TRACE_GRATICULE[1], TRACE_GRATICULE[2], 70)
        buf.rectangle(i * w // TRACE_GRID, 0, 1, h)
    for i in range(4):
        y = int(h * bus[i])
        buf.pen = color.rgb(TRACE_BUS[0], TRACE_BUS[1], TRACE_BUS[2], 230)
        buf.rectangle(0, y, w, tw)
    for i in range(TRACE_LINES):
        y = int(h * (0.10 + i * 0.108))
        x0 = int(w * ((i * 17) % 5) / 11.0)
        x1 = x0 + int(w * (0.30 + ((i * 13) % 4) * 0.14))
        buf.pen = color.rgb(TRACE_INK[0], TRACE_INK[1], TRACE_INK[2], 200)
        buf.rectangle(x0, y, x1 - x0, tw)
        buf.line(x1, y, x1 + u * 2, y + u * 2)
        buf.rectangle(x1 + u * 2, y + u * 2, int(w * 0.18), tw)
        buf.rectangle(x0, y if i % 2 else y - u * 2, tw, u * 2)
    bx, by = int(w * 0.56), int(h * 0.50)
    bw, bh2 = int(w * TRACE_CHIP_W), int(h * 0.22)
    buf.pen = color.rgb(0, 200, 190, 120)
    buf.rectangle(bx - u, by - u, bw + u * 2, bh2 + u * 2)
    buf.pen = color.rgb(*TRACE_CHIP)
    buf.rectangle(bx, by, bw, bh2)
    buf.pen = color.rgb(0, 220, 210, 160)
    buf.rectangle(bx + u, by + u, bw - u * 2, bh2 - u * 2)
    buf.pen = color.rgb(*TRACE_CHIP)
    buf.rectangle(bx + u * 2, by + u * 2, bw - u * 4, bh2 - u * 4)
    for i in range(TRACE_PINS):
        buf.pen = color.rgb(*TRACE_GOLD)
        buf.rectangle(bx + u + i * (bw - u * 2) // TRACE_PINS, by - u * 2,
                      max(1, u // 2), u * 2)
        buf.rectangle(bx + u + i * (bw - u * 2) // TRACE_PINS, by + bh2,
                      max(1, u // 2), u * 2)
    for i in range(TRACE_VIAS):
        vx = int(w * (0.06 + ((i * 29) % 11) * 0.085))
        vy = int(h * bus[i % 4]) if i % 2 else int(h * (0.10 + (i % 5) * 0.19))
        buf.pen = color.rgb(255, 40, 180, 70)
        buf.circle(vx, vy, max(2, u))
        buf.pen = color.rgb(*TRACE_VIA)
        buf.circle(vx, vy, max(1, u // 2))


def _g_trace_map_a(dst, t):
    """The whole board is powered, not one bus of it.

    Packets run every bus AND the signal traces, the chip's pins clock in
    sequence, its core lights on the clock edge, and the vias it is talking to
    blink. Each packet does a WHOLE number of laps per cycle, so nothing
    teleports at the t = 1 -> 0 wrap; the previous version's 1.23 laps put a
    23%-of-screen jump in every bus once every four seconds."""
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    bus = (0.18, 0.42, 0.66, 0.88)
    for i in range(4):
        y = int(h * bus[i])
        laps = 1 + (i % 2)
        p = (t * TRACE_PACKET_SPEED * laps + i * 0.25) % 1.0
        x = int(w * p) if i % 2 == 0 else w - int(w * p)
        dst.pen = color.rgb(0, 255, 230, 50)
        dst.rectangle(x - u * 9, y - max(1, u // 3), u * 4, max(1, u))
        dst.pen = color.rgb(0, 255, 230, 110)
        dst.rectangle(x - u * 5, y - max(1, u // 3), u * 5, max(1, u))
        dst.pen = color.rgb(210, 255, 255)
        dst.rectangle(x, y - max(1, u // 3), u * 2, max(1, u))

    # the signal traces carry traffic too, each between the ends `render` drew
    tw = max(1, u // 3)
    for i in range(TRACE_SIGNALS):
        n = i * 2 + 1
        y = int(h * (0.10 + n * 0.108))
        x0 = int(w * ((n * 17) % 5) / 11.0)
        x1 = x0 + int(w * (0.30 + ((n * 13) % 4) * 0.14))
        laps = 1 + (i % 3)
        p = (t * TRACE_PACKET_SPEED * laps + i * 0.31) % 1.0
        dst.pen = color.rgb(190, 255, 255, 235)
        dst.rectangle(x0 + int((x1 - x0) * p), y - tw, max(2, u), tw * 3)

    # the chip clocks: pins light in sequence and the core answers
    bx, by = int(w * 0.56), int(h * 0.50)
    bw, bh2 = int(w * TRACE_CHIP_W), int(h * 0.22)
    edge = (t * TRACE_CLOCK_RATE) % 1.0
    k = int(t * TRACE_CLOCK_RATE * TRACE_PINS) % TRACE_PINS
    for j in range(3):
        pin = (k + j) % TRACE_PINS
        dst.pen = color.rgb(255, 245, 190, 240 if j == 0 else 110)
        dst.rectangle(bx + u + pin * (bw - u * 2) // TRACE_PINS,
                      by - u * 2 if j % 2 else by + bh2,
                      max(1, u // 2), u * 2)
    dst.pen = color.rgb(0, 255, 220, 30 + int(90 * (1.0 - edge)))
    dst.rectangle(bx + u * 2, by + u * 2, bw - u * 4, bh2 - u * 4)
    dst.pen = color.rgb(190, 255, 250, 40 + int(160 * (1.0 - edge)))
    dst.rectangle(bx + u, by + u, bw - u * 2, max(1, u // 2))

    # the vias it is talking to. Same scatter `render` placed them with, so a
    # blink lands ON a via instead of beside one.
    if TRACE_BLINK:
        for i in range(TRACE_LIVE_VIAS):
            vx = int(w * (0.06 + ((i * 29) % 11) * 0.085))
            vy = int(h * bus[i % 4]) if i % 2 else int(h * (0.10 + (i % 5) * 0.19))
            on = ((t * TRACE_VIA_RATE + i * 0.37) % 1.0) < 0.4
            dst.pen = color.rgb(255, 160, 230, 225 if on else 40)
            dst.circle(vx, vy, max(2, u))


# @skinlab {"type":"color","label":"Backdrop","group":"Palette"}
BLINKY_BACK = (58, 22, 88)

# @skinlab {"type":"color","label":"Confetti","group":"Palette"}
BLINKY_CONFETTI = (84, 36, 122)

# @skinlab {"type":"color","label":"Ears","group":"Palette"}
BLINKY_HORN = (255, 196, 60)

# @skinlab {"type":"color","label":"Body","group":"Palette"}
BLINKY_BODY = (126, 214, 74)

# @skinlab {"type":"color","label":"Body highlight","group":"Palette"}
BLINKY_BODY_LIGHT = (150, 232, 96)

# @skinlab {"type":"color","label":"Body shadow","group":"Palette"}
BLINKY_BODY_DARK = (22, 86, 38)

# @skinlab {"type":"color","label":"Body spots","group":"Palette"}
BLINKY_SPOT = (96, 178, 56)

# @skinlab {"type":"color","label":"Cheeks","group":"Palette"}
BLINKY_CHEEK = (240, 110, 150)

# @skinlab {"type":"color","label":"Eye white","group":"Palette"}
BLINKY_EYE = (255, 252, 236)

# @skinlab {"type":"color","label":"Pupil","group":"Palette"}
BLINKY_PUPIL = (24, 18, 30)

# @skinlab {"type":"color","label":"Tongue","group":"Palette"}
BLINKY_TONGUE = (196, 62, 96)

# @skinlab {"type":"number","label":"Eye travel","group":"Motion","min":0,"max":0.54,"step":0.02}
BLINKY_LOOK = 0.42

# @skinlab {"type":"number","label":"Blink length","group":"Motion","min":0.01,"max":0.12,"step":0.005}
BLINKY_BLINK_LENGTH = 0.035

# @skinlab {"type":"integer","label":"Confetti count","group":"Layout","min":0,"max":40,"step":1}
BLINKY_DOTS = 16

# @skinlab {"type":"integer","label":"Falling confetti","group":"Layout","min":0,"max":12,"step":1}
BLINKY_FLOATERS = 8

# @skinlab {"type":"integer","label":"Confetti falls per loop","group":"Motion","min":1,"max":4,"step":1}
BLINKY_FALL = 1

# @skinlab {"type":"integer","label":"Horn sparks","group":"Layout","min":0,"max":2,"step":1}
BLINKY_SPARKS = 2

# @skinlab {"type":"integer","label":"Cheek pulses per loop","group":"Motion","min":1,"max":8,"step":1}
BLINKY_PUFF = 3


def _g_blinky(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    buf.pen = color.rgb(*BLINKY_BACK)
    buf.clear()
    buf.pen = color.rgb(*BLINKY_CONFETTI)
    for i in range(BLINKY_DOTS):
        buf.circle(int(w * ((i * 7) % 11) / 10.0), int(h * ((i * 5) % 9) / 8.0), max(1, u))
    cx = w // 2
    cy = int(h * 0.60)
    r = int(h * 0.54)
    buf.pen = color.rgb(*BLINKY_HORN)
    buf.triangle(cx - r // 2, int(h * 0.22), cx - int(r * 0.86), int(h * 0.02), cx - int(r * 0.30), int(h * 0.14))
    buf.triangle(cx + r // 2, int(h * 0.22), cx + int(r * 0.86), int(h * 0.02), cx + int(r * 0.30), int(h * 0.14))
    buf.pen = color.rgb(28, 104, 46)
    buf.circle(cx - r, cy - u, int(r * 0.30))
    buf.circle(cx + r, cy - u, int(r * 0.30))
    buf.pen = color.rgb(232, 106, 140)
    buf.circle(cx - r, cy - u, int(r * 0.15))
    buf.circle(cx + r, cy - u, int(r * 0.15))
    buf.pen = color.rgb(*BLINKY_BODY_DARK)
    buf.circle(cx, cy + max(1, u), r)
    buf.pen = color.rgb(*BLINKY_BODY)
    buf.circle(cx, cy, r)
    buf.pen = color.rgb(*BLINKY_BODY_LIGHT)
    buf.circle(cx - int(r * 0.34), cy - int(r * 0.34), int(r * 0.52))
    buf.pen = color.rgb(*BLINKY_SPOT)
    for i in range(6):
        buf.circle(cx + int(r * (0.62 - 0.30 * (i % 3))) * (1 if i % 2 else -1),
                   cy + int(r * (0.30 + 0.18 * (i % 4))), max(1, int(u * 1.4)))
    buf.pen = color.rgb(BLINKY_CHEEK[0], BLINKY_CHEEK[1], BLINKY_CHEEK[2], 150)
    buf.circle(cx - int(r * 0.66), int(h * 0.50), int(r * 0.20))
    buf.circle(cx + int(r * 0.66), int(h * 0.50), int(r * 0.20))
    ew = int(h * 0.135)
    ey = int(h * 0.28)
    for s in (-1, 1):
        ex = cx + s * int(w * 0.145)
        buf.pen = color.rgb(16, 40, 20)
        buf.circle(ex, ey, ew + max(1, u // 2))
        buf.pen = color.rgb(*BLINKY_EYE)
        buf.circle(ex, ey, ew)
        buf.pen = color.rgb(*BLINKY_PUPIL)
        buf.circle(ex, ey + int(ew * 0.15), int(ew * 0.42))
        buf.pen = color.rgb(255, 255, 255)
        buf.circle(ex - int(ew * 0.30), ey - int(ew * 0.28), max(1, int(ew * 0.18)))
    buf.pen = color.rgb(40, 120, 50)
    buf.circle(cx - int(w * 0.045), int(h * 0.50), max(1, u))
    buf.circle(cx + int(w * 0.045), int(h * 0.50), max(1, u))
    my = int(h * 0.68)
    mr = int(h * 0.20)
    buf.pen = color.rgb(30, 14, 22)
    buf.circle(cx, my, mr)
    buf.pen = color.rgb(*BLINKY_TONGUE)
    buf.circle(cx, my + int(mr * 0.45), int(mr * 0.62))
    buf.pen = color.rgb(255, 250, 240)
    buf.rectangle(cx - mr, my - mr, mr * 2, max(2, int(mr * 0.34)))
    buf.pen = color.rgb(30, 14, 22)
    for i in range(3):
        buf.rectangle(cx - mr + int(mr * 0.5) * (i + 1), my - mr, max(1, u // 2), int(mr * 0.34))
    buf.pen = color.rgb(255, 250, 240)
    buf.triangle(cx + int(mr * 0.2), my + mr, cx + int(mr * 0.62), my + int(mr * 0.5),
                 cx + int(mr * 0.72), my + int(mr * 0.95))


def _g_blinky_a(dst, t):
    """Everything a delighted idiot monster does at once.

    The eyes were already tracking and blinking. What it did not have was a
    reason to be delighted, so the confetti its own background is made of
    now falls in front as well, the cheeks puff on a shared phase, the horns
    spark and the tongue wags rather than bobbing. The confetti passes over
    the face on purpose -- the monster fills the canvas, so there is no
    background left to fall through.
    """
    import math
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    cx = w // 2
    ew = int(h * 0.135)
    ey = int(h * 0.28)
    b = 0.0
    for c in (0.30, 0.58, 0.66):
        d = abs(t - c)
        if d < BLINKY_BLINK_LENGTH:
            b = max(b, 1.0 - d / BLINKY_BLINK_LENGTH)
    look = math.sin(t * 6.283) * BLINKY_LOOK
    for s in (-1, 1):
        ex = cx + s * int(w * 0.145)
        dst.pen = color.rgb(*BLINKY_EYE)
        dst.circle(ex, ey, ew)
        dst.pen = color.rgb(*BLINKY_PUPIL)
        dst.circle(ex + int(ew * look), ey + int(ew * 0.15), int(ew * 0.42))
        dst.pen = color.rgb(255, 255, 255)
        dst.circle(ex + int(ew * look) - int(ew * 0.3), ey - int(ew * 0.13), max(1, int(ew * 0.18)))
        if b > 0.02:
            lid = max(1, int(ew * 2 * b))
            dst.pen = color.rgb(*BLINKY_BODY)
            dst.rectangle(ex - ew, ey - ew, ew * 2, lid)
            dst.pen = color.rgb(60, 150, 50)
            dst.rectangle(ex - ew, ey - ew + lid, ew * 2, max(1, u // 2))
    mr = int(h * 0.20)
    dst.pen = color.rgb(*BLINKY_TONGUE)
    dst.circle(cx + int(math.sin(t * 6.283 * 2) * u), int(h * 0.68) + int(mr * 0.45)
               + int(math.sin(t * 6.283 * 4) * u), int(mr * 0.62))
    puff = abs(2.0 * ((t * BLINKY_PUFF) % 1.0) - 1.0)
    r = int(h * 0.54)
    dst.pen = color.rgb(BLINKY_CHEEK[0], BLINKY_CHEEK[1], BLINKY_CHEEK[2], 90 + int(90 * puff))
    dst.circle(cx - int(r * 0.66), int(h * 0.50), int(r * 0.20) + int(u * puff))
    dst.circle(cx + int(r * 0.66), int(h * 0.50), int(r * 0.20) + int(u * puff))
    for i in range(BLINKY_SPARKS):
        s = i * 2 - 1
        p = (t * 2 + i * 0.5) % 1.0
        if p > 0.4:
            continue
        g = max(2, int(u * (1.5 - 3.0 * abs(p - 0.2))))
        sx, sy = cx + s * int(r * 0.86), int(h * 0.02)
        dst.pen = color.rgb(255, 250, 220)
        dst.rectangle(sx - g, sy - max(1, u // 3), g * 2, max(1, u * 2 // 3))
    flakes = (BLINKY_HORN, BLINKY_CHEEK, BLINKY_EYE, BLINKY_BODY_LIGHT)
    for i in range(BLINKY_FLOATERS):
        c = flakes[i % 4]
        p = (t * (BLINKY_FALL + (i * 5) % 3) + i * 0.13) % 1.0
        x = (i * 71 + 9) % w + int(u * (abs(2.0 * ((t * 2 + i * 0.3) % 1.0) - 1.0) - 0.5) * 3)
        dst.pen = color.rgb(c[0], c[1], c[2], 225)
        dst.circle(x, int(p * (h + u * 4)) - u * 2, max(1, u * 3 // 4))


# @skinlab {"type":"color","label":"Backdrop","group":"Palette"}
TAPE_BACK = (16, 54, 88)

# @skinlab {"type":"color","label":"Backdrop streak","group":"Palette"}
TAPE_STREAK = (255, 240, 190)

# @skinlab {"type":"color","label":"Shell","group":"Palette"}
TAPE_SHELL = (32, 28, 36)

# @skinlab {"type":"color","label":"Label paper","group":"Palette"}
TAPE_LABEL = (248, 240, 216)

# @skinlab {"type":"color","label":"Label stripe, orange","group":"Palette"}
TAPE_LABEL_A = (234, 88, 36)

# @skinlab {"type":"color","label":"Label stripe, red","group":"Palette"}
TAPE_LABEL_B = (214, 40, 56)

# @skinlab {"type":"color","label":"Label bar, blue","group":"Palette"}
TAPE_LABEL_C = (48, 132, 176)

# @skinlab {"type":"color","label":"Window","group":"Palette"}
TAPE_WINDOW = (12, 10, 16)

# @skinlab {"type":"color","label":"Tape ribbon","group":"Palette"}
TAPE_RIBBON = (84, 52, 32)

# @skinlab {"type":"color","label":"Reel rim","group":"Palette"}
TAPE_REEL_RIM = (58, 36, 22)

# @skinlab {"type":"color","label":"Reel","group":"Palette"}
TAPE_REEL = (112, 72, 44)

# @skinlab {"type":"color","label":"Hub","group":"Palette"}
TAPE_HUB = (200, 198, 206)

# @skinlab {"type":"number","label":"Hub spin","group":"Motion","min":1,"max":8,"step":1}
TAPE_SPIN = 3.0

# @skinlab {"type":"integer","label":"Streak count","group":"Layout","min":0,"max":20,"step":1}
TAPE_STREAKS = 9

# @skinlab {"type":"integer","label":"Hub spokes","group":"Layout","min":2,"max":5,"step":1}
TAPE_SPOKES = 4

# @skinlab {"type":"boolean","label":"Splice mark","group":"Details"}
TAPE_SPLICE = True

# @skinlab {"type":"integer","label":"Play lamp blinks per loop","group":"Motion","min":1,"max":8,"step":1}
TAPE_BLINK = 4


def _g_mixtape(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    steps = 40
    for i in range(steps):
        buf.pen = color.rgb(TAPE_BACK[0] + i * 26 // steps, TAPE_BACK[1] + i * 44 // steps,
                            TAPE_BACK[2] + i * 26 // steps)
        buf.rectangle(0, h * i // steps, w, h // steps + 2)
    buf.pen = color.rgb(TAPE_STREAK[0], TAPE_STREAK[1], TAPE_STREAK[2], 46)
    for i in range(TAPE_STREAKS):
        buf.rectangle(int(w * i / TAPE_STREAKS) + u, 0, max(1, u // 2), h)
    x0, x1 = int(w * 0.04), int(w * 0.96)
    y0, y1 = int(h * 0.09), int(h * 0.93)
    buf.pen = color.rgb(8, 6, 12, 140)
    buf.rectangle(x0 + u, y0 + u, x1 - x0, y1 - y0)
    buf.pen = color.rgb(*TAPE_SHELL)
    buf.rectangle(x0, y0, x1 - x0, y1 - y0)
    buf.pen = color.rgb(66, 60, 74)
    buf.rectangle(x0, y0, x1 - x0, max(1, u // 2))
    buf.rectangle(x0, y0, max(1, u // 2), y1 - y0)
    lx0, lx1 = x0 + u, x1 - u
    ly0 = y0 + u
    lh = int(h * 0.36)
    buf.pen = color.rgb(*TAPE_LABEL)
    buf.rectangle(lx0, ly0, lx1 - lx0, lh)
    buf.pen = color.rgb(*TAPE_LABEL_A)
    buf.rectangle(lx0, ly0, lx1 - lx0, max(1, int(h * 0.048)))
    buf.pen = color.rgb(*TAPE_LABEL_B)
    buf.rectangle(lx0, ly0 + int(h * 0.048), lx1 - lx0, max(1, int(h * 0.028)))
    buf.pen = color.rgb(*TAPE_LABEL_C)
    buf.rectangle(lx0, ly0 + lh - max(2, u), lx1 - lx0, max(2, u))
    buf.pen = color.rgb(120, 112, 100, 110)
    buf.rectangle(lx0 + u * 2, ly0 + lh - max(3, int(u * 2.4)), (lx1 - lx0) - u * 4, max(1, u // 3))
    buf.pen = color.rgb(*TAPE_LABEL_B)
    buf.triangle(lx0 + int(u * 1.5), ly0 + int(h * 0.105), lx0 + int(u * 4.2), ly0 + int(h * 0.14),
                 lx0 + int(u * 1.5), ly0 + int(h * 0.175))
    wx0, wx1 = x0 + int(u * 2.5), x1 - int(u * 2.5)
    wy0, wy1 = int(h * 0.50), int(h * 0.81)
    buf.pen = color.rgb(*TAPE_WINDOW)
    buf.rectangle(wx0, wy0, wx1 - wx0, wy1 - wy0)
    buf.pen = color.rgb(74, 68, 84)
    buf.rectangle(wx0, wy0, wx1 - wx0, max(1, u // 2))
    hy = wy0 + int((wy1 - wy0) * 0.44)
    hub = max(2, int(h * 0.042))
    big = int(h * 0.125)
    buf.pen = color.rgb(*TAPE_RIBBON)
    buf.rectangle(wx0 + u, wy1 - max(2, int(u * 1.6)), wx1 - wx0 - u * 2, max(1, u))
    for s in (-1, 1):
        hx = w // 2 + s * int(w * 0.20)
        rr = big if s < 0 else int(big * 0.55)
        buf.pen = color.rgb(*TAPE_REEL_RIM)
        buf.circle(hx, hy, rr)
        buf.pen = color.rgb(*TAPE_REEL)
        buf.circle(hx, hy, max(1, rr - max(1, u // 2)))
        buf.pen = color.rgb(*TAPE_HUB)
        buf.circle(hx, hy, hub)
        buf.pen = color.rgb(*TAPE_WINDOW)
        buf.circle(hx, hy, max(1, hub // 2))
    buf.pen = color.rgb(10, 8, 14)
    for i in range(5):
        buf.rectangle(int(w * (0.20 + i * 0.15)), int(h * 0.855), max(2, u * 2), max(2, int(h * 0.045)))
    buf.pen = color.rgb(84, 78, 94)
    for sx in (x0 + int(u * 1.5), x1 - int(u * 2.5)):
        buf.circle(sx, y0 + u * 2, max(1, u // 2 + 1))
        buf.circle(sx, y1 - u * 2, max(1, u // 2 + 1))


def _g_mixtape_a(dst, t):
    """A tape actually playing: wound left to right, spokes turning with it.

    The reel radii swap over the loop, which is the one thing a cassette does
    that you can read from across a room. What was missing was the evidence
    that the tape between them is MOVING -- so a splice mark runs along the
    exposed ribbon at the hub speed, a bump on each wound reel carries the
    rotation the spokes only hint at, and the label's play lamp blinks.
    """
    import math
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    wx0, wx1 = int(w * 0.04) + int(u * 2.5), int(w * 0.96) - int(u * 2.5)
    wy0, wy1 = int(h * 0.50), int(h * 0.81)
    dst.pen = color.rgb(*TAPE_WINDOW)
    dst.rectangle(wx0, wy0, wx1 - wx0, wy1 - wy0)
    hy = wy0 + int((wy1 - wy0) * 0.44)
    hub = max(2, int(h * 0.042))
    big = int(h * 0.125)
    p = abs(t * 2.0 - 1.0)
    a = t * 6.283 * TAPE_SPIN
    dst.pen = color.rgb(*TAPE_RIBBON)
    dst.rectangle(wx0 + u, wy1 - max(2, int(u * 1.6)), wx1 - wx0 - u * 2, max(1, u))
    for s in (-1, 1):
        hx = w // 2 + s * int(w * 0.20)
        rr = hub + int((big - hub) * (p if s < 0 else 1.0 - p))
        dst.pen = color.rgb(*TAPE_REEL_RIM)
        dst.circle(hx, hy, rr)
        dst.pen = color.rgb(*TAPE_REEL)
        dst.circle(hx, hy, max(1, rr - max(1, u // 2)))
        dst.pen = color.rgb(TAPE_REEL[0] + 40, TAPE_REEL[1] + 30, TAPE_REEL[2] + 20)
        dst.circle(hx + int(math.cos(a) * (rr + hub) * 0.34),
                   hy + int(math.sin(a) * (rr + hub) * 0.34), max(1, rr // 4))
        dst.pen = color.rgb(*TAPE_HUB)
        dst.circle(hx, hy, hub)
        for i in range(TAPE_SPOKES):
            ang = a + i * 6.283 / TAPE_SPOKES
            dst.pen = color.rgb(*TAPE_WINDOW)
            dst.circle(hx + int(math.cos(ang) * hub * 0.60), hy + int(math.sin(ang) * hub * 0.60),
                       max(1, hub // 3))
    if TAPE_SPLICE:
        run = wx1 - wx0 - u * 2
        dst.pen = color.rgb(*TAPE_LABEL)
        dst.rectangle(wx0 + u + int(run * ((t * TAPE_SPIN) % 1.0)),
                      wy1 - max(2, int(u * 1.6)), max(1, u // 2), max(1, u))
    lx0 = int(w * 0.04) + u
    ly0 = int(h * 0.09) + u
    if (t * TAPE_BLINK) % 1.0 < 0.5:
        dst.pen = color.rgb(255, 96, 96)
    else:
        dst.pen = color.rgb(*TAPE_LABEL)
    dst.triangle(lx0 + int(u * 1.5), ly0 + int(h * 0.105), lx0 + int(u * 4.2), ly0 + int(h * 0.14),
                 lx0 + int(u * 1.5), ly0 + int(h * 0.175))
    dst.pen = color.rgb(255, 255, 255, 34)
    dst.rectangle(wx0, wy0 + int((wy1 - wy0) * ((t * 2.0) % 1.0)), wx1 - wx0, max(1, u))


# @skinlab {"type":"color","label":"Desktop","group":"Palette"}
LOADING_DESKTOP = (0, 116, 118)

# @skinlab {"type":"color","label":"Folder icon","group":"Palette"}
LOADING_FOLDER = (240, 210, 90)

# @skinlab {"type":"color","label":"Folder shadow","group":"Palette"}
LOADING_FOLDER_SHADE = (180, 150, 50)

# @skinlab {"type":"color","label":"Window face","group":"Palette"}
LOADING_FACE = (198, 198, 198)

# @skinlab {"type":"color","label":"Bevel shadow","group":"Palette"}
LOADING_BEZEL = (110, 110, 110)

# @skinlab {"type":"color","label":"Title bar","group":"Palette"}
LOADING_TITLEBAR = (0, 24, 132)

# @skinlab {"type":"color","label":"Hourglass","group":"Palette"}
LOADING_GLASS = (250, 250, 250)

# @skinlab {"type":"color","label":"Sand","group":"Palette"}
LOADING_SAND = (230, 170, 40)

# @skinlab {"type":"color","label":"Progress trough","group":"Palette"}
LOADING_TROUGH = (160, 160, 160)

# @skinlab {"type":"integer","label":"Progress segments","group":"Layout","min":4,"max":24,"step":1}
LOADING_SEGMENTS = 13

# @skinlab {"type":"number","label":"How far it gets","group":"Motion","min":0.1,"max":1.0,"step":0.01}
LOADING_FILL = 0.97

# @skinlab {"type":"integer","label":"Clicks per loop","group":"Motion","min":1,"max":6,"step":1}
LOADING_CLICKS = 2

# @skinlab {"type":"integer","label":"Title scrolls per loop","group":"Motion","min":1,"max":4,"step":1}
LOADING_TITLE_SCROLL = 1

# @skinlab {"type":"boolean","label":"Pointer","group":"Details"}
LOADING_POINTER = True


def _g_not_loading(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    steps = 40
    for i in range(steps):
        buf.pen = color.rgb(LOADING_DESKTOP[0], LOADING_DESKTOP[1] - i * 40 // steps,
                            LOADING_DESKTOP[2] - i * 40 // steps)
        buf.rectangle(0, h * i // steps, w, h // steps + 2)
    buf.pen = color.rgb(*LOADING_FOLDER)
    buf.rectangle(u, u, u * 3, int(u * 2.2))
    buf.rectangle(u, u * 2, u * 5, u * 3)
    buf.pen = color.rgb(*LOADING_FOLDER_SHADE)
    buf.rectangle(u, int(u * 4.2), u * 5, max(1, u // 2))
    x0, x1 = int(w * 0.07), int(w * 0.93)
    y0, y1 = int(h * 0.15), int(h * 0.82)
    buf.pen = color.rgb(0, 0, 0, 120)
    buf.rectangle(x0 + u, y0 + u, x1 - x0, y1 - y0)
    buf.pen = color.rgb(0, 0, 0)
    buf.rectangle(x0, y0, x1 - x0, y1 - y0)
    buf.pen = color.rgb(*LOADING_FACE)
    buf.rectangle(x0 + 1, y0 + 1, x1 - x0 - 2, y1 - y0 - 2)
    buf.pen = color.rgb(255, 255, 255)
    buf.rectangle(x0 + 1, y0 + 1, x1 - x0 - 2, max(1, u // 2))
    buf.rectangle(x0 + 1, y0 + 1, max(1, u // 2), y1 - y0 - 2)
    buf.pen = color.rgb(*LOADING_BEZEL)
    buf.rectangle(x0 + 1, y1 - 1 - max(1, u // 2), x1 - x0 - 2, max(1, u // 2))
    buf.rectangle(x1 - 1 - max(1, u // 2), y0 + 1, max(1, u // 2), y1 - y0 - 2)
    tb = int(h * 0.085)
    buf.pen = color.rgb(*LOADING_TITLEBAR)
    buf.rectangle(x0 + u, y0 + u, x1 - x0 - u * 2, tb)
    buf.pen = color.rgb(120, 160, 230, 160)
    for i in range(3):
        buf.rectangle(x0 + u * 2, y0 + u + int(tb * 0.28) + i * max(2, u), int(w * (0.20 - i * 0.05)),
                      max(1, u // 2))
    buf.pen = color.rgb(*LOADING_FACE)
    buf.rectangle(x1 - u * 4, y0 + u + max(1, u // 2), u * 3, tb - u)
    buf.pen = color.rgb(20, 20, 20)
    buf.line(x1 - u * 4 + u, y0 + u * 2, x1 - u * 2, y0 + tb)
    buf.line(x1 - u * 2, y0 + u * 2, x1 - u * 4 + u, y0 + tb)
    hx = int(w * 0.145)
    hy = int(h * 0.385)
    hs = int(h * 0.082)
    buf.pen = color.rgb(60, 60, 60)
    buf.rectangle(hx - hs, hy - hs - max(1, u // 2), hs * 2, max(1, u))
    buf.rectangle(hx - hs, hy + hs, hs * 2, max(1, u))
    buf.pen = color.rgb(*LOADING_GLASS)
    buf.triangle(hx - hs, hy - hs, hx + hs, hy - hs, hx, hy)
    buf.triangle(hx - hs, hy + hs, hx + hs, hy + hs, hx, hy)
    buf.pen = color.rgb(*LOADING_SAND)
    buf.triangle(hx - int(hs * 0.7), hy - int(hs * 0.5), hx + int(hs * 0.7), hy - int(hs * 0.5), hx, hy)
    px0, px1 = int(w * 0.13), int(w * 0.87)
    py = int(h * 0.58)
    ph = int(h * 0.10)
    buf.pen = color.rgb(*LOADING_BEZEL)
    buf.rectangle(px0, py, px1 - px0, ph)
    buf.pen = color.rgb(255, 255, 255)
    buf.rectangle(px0 + max(1, u // 2), py + max(1, u // 2), px1 - px0 - max(1, u // 2), ph)
    buf.pen = color.rgb(*LOADING_TROUGH)
    buf.rectangle(px0 + max(1, u // 2), py + max(1, u // 2), px1 - px0 - max(1, u), ph - max(1, u))
    for i in range(2):
        bx = int(w * (0.22 + i * 0.34))
        by = int(h * 0.71)
        bw2 = int(w * 0.22)
        bh2 = int(h * 0.085)
        buf.pen = color.rgb(0, 0, 0)
        buf.rectangle(bx, by, bw2, bh2)
        buf.pen = color.rgb(*LOADING_FACE)
        buf.rectangle(bx + 1, by + 1, bw2 - 2, max(1, bh2 - 2))
        buf.pen = color.rgb(255, 255, 255)
        buf.rectangle(bx + 1, by + 1, bw2 - 2, max(1, u // 2))
        buf.pen = color.rgb(*LOADING_BEZEL)
        buf.rectangle(bx + 1, by + bh2 - 1 - max(1, u // 2), bw2 - 2, max(1, u // 2))
        buf.pen = color.rgb(70, 70, 70)
        buf.rectangle(bx + int(bw2 * 0.22), by + int(bh2 * 0.42), int(bw2 * 0.56), max(1, u // 2))


def _g_not_loading_a(dst, t):
    """Ninety-seven percent, forever, while somebody keeps clicking OK.

    The bar and the hourglass were already the joke; the pointer is what
    makes it a scene. It walks between the two buttons, presses each one --
    the bevel inverts, which is the whole of a 1995 button press -- and the
    bar resets anyway. The title marquee scrolls behind it because the one
    part of this window that IS working is the decoration.
    """
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    x0, x1 = int(w * 0.07), int(w * 0.93)
    y0 = int(h * 0.15)
    tb = int(h * 0.085)
    dst.pen = color.rgb(*LOADING_TITLEBAR)
    dst.rectangle(x0 + u, y0 + u, x1 - x0 - u * 2, tb)
    run = x1 - x0 - u * 2
    slide = int(run * ((t * LOADING_TITLE_SCROLL) % 1.0))
    for i in range(3):
        dst.pen = color.rgb(120, 160, 230, 160)
        dst.rectangle(x0 + u * 2 + ((slide + i * u * 3) % run) - run // 3,
                      y0 + u + int(tb * 0.28) + i * max(2, u),
                      int(w * (0.20 - i * 0.05)), max(1, u // 2))
    px0, px1 = int(w * 0.13), int(w * 0.87)
    py = int(h * 0.58)
    ph = int(h * 0.10)
    ix = px0 + max(1, u // 2)
    iy = py + max(1, u // 2)
    iw = px1 - px0 - max(1, u)
    ih = ph - max(1, u)
    dst.pen = color.rgb(*LOADING_TROUGH)
    dst.rectangle(ix, iy, iw, ih)
    p = LOADING_FILL * (1.0 - (1.0 - t) * (1.0 - t))
    n = int(p * LOADING_SEGMENTS)
    seg = max(2, iw // LOADING_SEGMENTS)
    for i in range(n):
        dst.pen = color.rgb(*LOADING_TITLEBAR)
        dst.rectangle(ix + i * seg, iy, max(1, seg - max(1, u // 2)), ih)
    hx = int(w * 0.145)
    hy = int(h * 0.385)
    hs = int(h * 0.082)
    dst.pen = color.rgb(*LOADING_GLASS)
    dst.triangle(hx - hs, hy - hs, hx + hs, hy - hs, hx, hy)
    dst.pen = color.rgb(*LOADING_SAND)
    k = 1.0 - t
    dst.triangle(hx - int(hs * 0.72 * k), hy - int(hs * 0.52 * k),
                 hx + int(hs * 0.72 * k), hy - int(hs * 0.52 * k), hx, hy)
    dst.pen = color.rgb(*LOADING_SAND)
    dst.triangle(hx - int(hs * 0.8 * t), hy + hs, hx + int(hs * 0.8 * t), hy + hs, hx, hy + int(hs * 0.3))
    if not LOADING_POINTER:
        return
    q = abs(2.0 * ((t * LOADING_CLICKS) % 1.0) - 1.0)
    i = 1 if q > 0.5 else 0
    bx = int(w * (0.22 + i * 0.34))
    by = int(h * 0.71)
    bw2 = int(w * 0.22)
    bh2 = int(h * 0.085)
    if q > 0.88 or q < 0.12:
        dst.pen = color.rgb(*LOADING_FACE)
        dst.rectangle(bx + 1, by + 1, bw2 - 2, max(1, bh2 - 2))
        dst.pen = color.rgb(*LOADING_BEZEL)
        dst.rectangle(bx + 1, by + 1, bw2 - 2, max(1, u // 2))
        dst.pen = color.rgb(70, 70, 70)
        dst.rectangle(bx + int(bw2 * 0.24), by + int(bh2 * 0.46), int(bw2 * 0.56), max(1, u // 2))
    cxp = int(w * (0.30 + 0.34 * q))
    cyp = int(h * (0.715 + 0.045 * (1.0 - abs(q - 0.5) * 2.0)))
    dst.pen = color.rgb(20, 20, 20)
    dst.triangle(cxp, cyp, cxp, cyp + int(u * 3.4), cxp + int(u * 2.4), cyp + int(u * 2.4))
    dst.pen = color.rgb(255, 255, 255)
    dst.triangle(cxp + 1, cyp + 1, cxp + 1, cyp + int(u * 2.6), cxp + int(u * 1.7), cyp + int(u * 1.9))


# @skinlab {"type":"color","label":"Sky","group":"Palette"}
ROCK_SKY = (122, 182, 172)

# @skinlab {"type":"color","label":"Halo rings","group":"Palette"}
ROCK_HALO = (255, 250, 214)

# @skinlab {"type":"color","label":"Floor","group":"Palette"}
ROCK_FLOOR = (186, 102, 70)

# @skinlab {"type":"color","label":"Floorboards","group":"Palette"}
ROCK_FLOOR_LINE = (156, 78, 54)

# @skinlab {"type":"color","label":"Rock","group":"Palette"}
ROCK_BODY = (112, 110, 122)

# @skinlab {"type":"color","label":"Rock facet","group":"Palette"}
ROCK_FACET = (156, 154, 168)

# @skinlab {"type":"color","label":"Rock highlight","group":"Palette"}
ROCK_FACET_LIGHT = (196, 194, 210)

# @skinlab {"type":"color","label":"Rock shadow","group":"Palette"}
ROCK_FACET_DARK = (84, 82, 94)

# @skinlab {"type":"color","label":"Speckles","group":"Palette"}
ROCK_SPECKLE = (70, 68, 78)

# @skinlab {"type":"color","label":"Eye white","group":"Palette"}
ROCK_EYE = (255, 255, 255)

# @skinlab {"type":"color","label":"Pupil","group":"Palette"}
ROCK_PUPIL = (24, 20, 28)

# @skinlab {"type":"color","label":"Bow tie and lead","group":"Palette"}
ROCK_BOW = (212, 48, 64)

# Whole rolls per loop: `sin(t * 6.283 * roll)` only closes on itself at the
# wrap when `roll` is an integer.
# @skinlab {"type":"integer","label":"Eye rolls per loop","group":"Motion","min":1,"max":4,"step":1}
ROCK_ROLL = 2

# @skinlab {"type":"boolean","label":"Sparkle","group":"Details"}
ROCK_SPARKLE = True

# @skinlab {"type":"integer","label":"Sparkles","group":"Layout","min":1,"max":4,"step":1}
ROCK_SPARKLES = 3

# @skinlab {"type":"boolean","label":"Fly","group":"Details"}
ROCK_FLY = True

# @skinlab {"type":"integer","label":"Dust puffs","group":"Layout","min":0,"max":4,"step":1}
ROCK_DUST = 3

# @skinlab {"type":"integer","label":"Fly laps per loop","group":"Motion","min":1,"max":4,"step":1}
ROCK_FLY_LAPS = 1


def _g_pet_rock(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    steps = 40
    for i in range(steps):
        buf.pen = color.rgb(ROCK_SKY[0] + i * 76 // steps, ROCK_SKY[1] + i * 44 // steps,
                            ROCK_SKY[2] + i * 40 // steps)
        buf.rectangle(0, h * i // steps, w, h // steps + 2)
    cx = w // 2
    buf.pen = color.rgb(ROCK_HALO[0], ROCK_HALO[1], ROCK_HALO[2], 42)
    buf.circle(cx, int(h * 0.30), int(w * 0.46))
    buf.circle(cx, int(h * 0.30), int(w * 0.32))
    buf.circle(cx, int(h * 0.30), int(w * 0.19))
    fy = int(h * 0.72)
    buf.pen = color.rgb(*ROCK_FLOOR)
    buf.rectangle(0, fy, w, h - fy)
    buf.pen = color.rgb(222, 136, 94)
    buf.rectangle(0, fy, w, max(1, u // 2))
    buf.pen = color.rgb(*ROCK_FLOOR_LINE)
    for i in range(5):
        buf.rectangle(0, fy + int((h - fy) * (0.16 + i * 0.18)), w, max(1, u // 3))
    buf.pen = color.rgb(96, 46, 34, 140)
    buf.rectangle(cx - int(w * 0.24), int(h * 0.875), int(w * 0.48), int(h * 0.06))
    buf.circle(cx - int(w * 0.24), int(h * 0.905), max(1, int(h * 0.03)))
    buf.circle(cx + int(w * 0.24), int(h * 0.905), max(1, int(h * 0.03)))
    ry = int(h * 0.715)
    rr = int(h * 0.245)
    buf.pen = color.rgb(*ROCK_BODY)
    buf.circle(cx, ry, rr)
    buf.circle(cx - int(w * 0.115), ry + int(h * 0.045), int(rr * 0.74))
    buf.circle(cx + int(w * 0.115), ry + int(h * 0.035), int(rr * 0.70))
    buf.pen = color.rgb(*ROCK_FACET)
    buf.triangle(cx - int(w * 0.20), ry + int(h * 0.09), cx - int(w * 0.02), ry - int(h * 0.155),
                 cx + int(w * 0.17), ry + int(h * 0.08))
    buf.pen = color.rgb(*ROCK_FACET_LIGHT)
    buf.triangle(cx - int(w * 0.17), ry + int(h * 0.03), cx - int(w * 0.05), ry - int(h * 0.145),
                 cx - int(w * 0.00), ry + int(h * 0.02))
    buf.pen = color.rgb(*ROCK_FACET_DARK)
    buf.triangle(cx + int(w * 0.02), ry + int(h * 0.13), cx + int(w * 0.21), ry + int(h * 0.01),
                 cx + int(w * 0.19), ry + int(h * 0.13))
    buf.pen = color.rgb(*ROCK_FLOOR)
    buf.rectangle(0, int(h * 0.895), w, h - int(h * 0.895))
    buf.pen = color.rgb(*ROCK_SPECKLE)
    for i in range(6):
        buf.circle(cx + int(w * (0.14 - 0.07 * (i % 3))) * (1 if i % 2 else -1),
                   ry + int(h * (0.04 + 0.03 * (i % 3))), max(1, u // 2))
    ey = int(h * 0.665)
    er = max(2, int(h * 0.078))
    for s in (-1, 1):
        ex = cx + s * int(w * 0.065)
        buf.pen = color.rgb(22, 20, 26)
        buf.circle(ex, ey, er + max(1, u // 2))
        buf.pen = color.rgb(*ROCK_EYE)
        buf.circle(ex, ey, er)
        buf.pen = color.rgb(*ROCK_PUPIL)
        buf.circle(ex, ey + er // 2, max(1, int(er * 0.42)))
    bx, by = cx, int(h * 0.845)
    buf.pen = color.rgb(*ROCK_BOW)
    buf.triangle(bx - int(w * 0.10), by - int(h * 0.045), bx - int(w * 0.10), by + int(h * 0.045), bx, by)
    buf.triangle(bx + int(w * 0.10), by - int(h * 0.045), bx + int(w * 0.10), by + int(h * 0.045), bx, by)
    buf.pen = color.rgb(250, 196, 60)
    buf.circle(bx, by, max(1, int(u * 1.1)))
    buf.pen = color.rgb(*ROCK_BOW)
    buf.line(cx + int(w * 0.21), ry - int(h * 0.12), int(w * 0.76), int(h * 0.50))
    buf.line(int(w * 0.76), int(h * 0.50), int(w * 0.88), int(h * 0.47))
    buf.line(int(w * 0.88), int(h * 0.47), w, int(h * 0.41))


def _g_pet_rock_a(dst, t):
    """Everything around the rock moves. The rock does not. That is the joke.

    So the budget goes to the pet, not the stone: googly eyes rolling, the
    bow's bead catching the light, sparkles going off because somebody is
    very proud of it, dust puffing at its base where the lead is pulling,
    and a fly that has correctly identified this as a rock and keeps
    checking anyway. Deliberately no wobble, no bounce, no breathing.
    """
    import math
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    cx = w // 2
    ey = int(h * 0.665)
    er = max(2, int(h * 0.078))
    a = math.sin(t * 6.283 * ROCK_ROLL) * 1.1
    d = er * 0.48
    for s in (-1, 1):
        ex = cx + s * int(w * 0.065)
        dst.pen = color.rgb(*ROCK_EYE)
        dst.circle(ex, ey, er)
        dst.pen = color.rgb(*ROCK_PUPIL)
        dst.circle(ex + int(math.sin(a) * d), ey + int(math.cos(a) * d), max(1, int(er * 0.42)))
        dst.pen = color.rgb(190, 190, 200, 160)
        dst.circle(ex - int(er * 0.4), ey - int(er * 0.4), max(1, int(er * 0.22)))
    dst.pen = color.rgb(250, 196, 60)
    dst.circle(cx, int(h * 0.845), max(1, int(u * (1.0 + 0.5 * abs(math.sin(t * 6.283 * 2))))))
    if ROCK_SPARKLE:
        spots = ((0.30, 0.60), (0.70, 0.58), (0.50, 0.47), (0.22, 0.52))
        for i in range(ROCK_SPARKLES):
            p = (t * 2 + i * 0.33) % 1.0
            if p > 0.36:
                continue
            g = max(1, int(u * (1.4 - 3.4 * abs(p - 0.18))))
            sx, sy = int(w * spots[i][0]), int(h * spots[i][1])
            dst.pen = color.rgb(255, 250, 210)
            dst.line(sx - g, sy, sx + g, sy)
            dst.line(sx, sy - g, sx, sy + g)
    for i in range(ROCK_DUST):
        p = (t * 2 + i * 0.34) % 1.0
        dst.pen = color.rgb(222, 176, 140, int(150 * (1.0 - p)))
        dst.circle(cx + (i * 2 - 2) * int(w * 0.16) - int(w * 0.06 * p),
                   int(h * 0.935) - int(u * p), max(1, int(u * (0.5 + 1.6 * p))))
    if ROCK_FLY:
        fa = t * 6.283 * ROCK_FLY_LAPS
        fx = cx + int(w * 0.30 * math.sin(fa))
        fy = int(h * 0.56) + int(h * 0.11 * math.sin(fa * 2 + 1.0))
        dst.pen = color.rgb(220, 220, 230, 170)
        dst.rectangle(fx - u, fy - max(1, u // 3), u * 2, max(1, u // 2))
        dst.pen = color.rgb(28, 24, 30)
        dst.circle(fx, fy, max(1, u // 2))


# @skinlab {"type":"color","label":"Cabinet","group":"Palette"}
CLAW_CABINET = (198, 30, 52)

# @skinlab {"type":"color","label":"Cabinet trim","group":"Palette"}
CLAW_CABINET_TRIM = (160, 18, 40)

# @skinlab {"type":"color","label":"Marquee","group":"Palette"}
CLAW_MARQUEE = (250, 206, 60)

# @skinlab {"type":"color","label":"Cabinet interior","group":"Palette"}
CLAW_INTERIOR = (12, 14, 34)

# @skinlab {"type":"color","label":"Bulb, warm","group":"Palette"}
CLAW_BULB_A = (255, 252, 220)

# @skinlab {"type":"color","label":"Bulb, alternate","group":"Palette"}
CLAW_BULB_B = (255, 140, 60)

# @skinlab {"type":"color","label":"Prize, pink","group":"Palette"}
CLAW_PRIZE_PINK = (255, 120, 170)

# @skinlab {"type":"color","label":"Prize, sky","group":"Palette"}
CLAW_PRIZE_SKY = (120, 220, 255)

# @skinlab {"type":"color","label":"Prize, lemon","group":"Palette"}
CLAW_PRIZE_LEMON = (255, 216, 90)

# @skinlab {"type":"color","label":"Prize, mint","group":"Palette"}
CLAW_PRIZE_MINT = (150, 240, 160)

# @skinlab {"type":"color","label":"Prize, lilac","group":"Palette"}
CLAW_PRIZE_LILAC = (200, 150, 255)

# @skinlab {"type":"integer","label":"Marquee bulbs","group":"Layout","min":3,"max":12,"step":1}
CLAW_BULBS = 7

# @skinlab {"type":"integer","label":"Prizes in the tank","group":"Layout","min":4,"max":20,"step":1}
CLAW_PRIZES = 12

# @skinlab {"type":"number","label":"Claw travel","group":"Motion","min":0.05,"max":0.4,"step":0.01}
CLAW_SWING = 0.26

# @skinlab {"type":"number","label":"Claw drop","group":"Motion","min":0.1,"max":0.55,"step":0.02}
CLAW_DROP = 0.44

# @skinlab {"type":"integer","label":"Side rail bulbs","group":"Layout","min":0,"max":4,"step":1}
CLAW_SIDE_BULBS = 3

# @skinlab {"type":"integer","label":"Button pulses per loop","group":"Motion","min":1,"max":8,"step":1}
CLAW_BUTTON_PULSE = 4

# @skinlab {"type":"number","label":"Where it fumbles the prize","group":"Motion","min":0.05,"max":0.9,"step":0.01}
CLAW_RELEASE = 0.30


def _g_claw_machine(buf):
    import math
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    buf.pen = color.rgb(*CLAW_CABINET)
    buf.clear()
    buf.pen = color.rgb(*CLAW_CABINET_TRIM)
    buf.rectangle(0, int(h * 0.12), w, max(1, u // 2))
    buf.pen = color.rgb(*CLAW_MARQUEE)
    buf.rectangle(0, 0, w, int(h * 0.11))
    buf.pen = color.rgb(214, 154, 28)
    buf.rectangle(0, int(h * 0.095), w, max(1, u // 2))
    for i in range(CLAW_BULBS):
        buf.pen = color.rgb(*CLAW_BULB_A) if i % 2 == 0 else color.rgb(*CLAW_BULB_B)
        buf.circle(int(w * (i + 0.5) / CLAW_BULBS), int(h * 0.052), max(1, int(u * 1.1)))
    ix0, ix1 = int(w * 0.07), int(w * 0.93)
    iy0, iy1 = int(h * 0.15), int(h * 0.78)
    buf.pen = color.rgb(*CLAW_INTERIOR)
    buf.rectangle(ix0, iy0, ix1 - ix0, iy1 - iy0)
    cx = w // 2
    buf.pen = color.rgb(40, 52, 120, 110)
    for i in range(8):
        a0 = i * 0.785
        buf.triangle(cx, int(h * 0.46),
                     cx + int(math.cos(a0) * w), int(h * 0.46) + int(math.sin(a0) * w),
                     cx + int(math.cos(a0 + 0.39) * w), int(h * 0.46) + int(math.sin(a0 + 0.39) * w))
    buf.pen = color.rgb(*CLAW_CABINET)
    buf.rectangle(0, 0, ix0, h)
    buf.rectangle(ix1, 0, w - ix1, h)
    buf.rectangle(0, iy1, w, h - iy1)
    buf.pen = color.rgb(*CLAW_MARQUEE)
    buf.rectangle(0, 0, w, int(h * 0.11))
    buf.pen = color.rgb(214, 154, 28)
    buf.rectangle(0, int(h * 0.095), w, max(1, u // 2))
    for i in range(CLAW_BULBS):
        buf.pen = color.rgb(*CLAW_BULB_A) if i % 2 == 0 else color.rgb(*CLAW_BULB_B)
        buf.circle(int(w * (i + 0.5) / CLAW_BULBS), int(h * 0.052), max(1, int(u * 1.1)))
    pal = (CLAW_PRIZE_PINK, CLAW_PRIZE_SKY, CLAW_PRIZE_LEMON, CLAW_PRIZE_MINT, CLAW_PRIZE_LILAC)
    for i in range(CLAW_PRIZES):
        px = ix0 + int((ix1 - ix0) * (((i * 29 + 7) % 41) / 41.0))
        py = int(h * (0.585 + 0.105 * (((i * 17) % 5) / 4.0)))
        pr = max(2, int(h * (0.078 + 0.026 * ((i % 3) / 2.0))))
        c = pal[i % 5]
        buf.pen = color.rgb(c[0] * 2 // 3, c[1] * 2 // 3, c[2] * 2 // 3)
        buf.circle(px, py + max(1, u // 2), pr)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.circle(px, py, pr)
        if i % 3 == 0:
            buf.pen = color.rgb(30, 24, 40)
            buf.circle(px - pr // 2, py - pr // 4, max(1, pr // 5))
            buf.circle(px + pr // 2, py - pr // 4, max(1, pr // 5))
    buf.pen = color.rgb(255, 255, 255, 30)
    buf.triangle(ix0, iy1, ix0 + int(w * 0.30), iy0, ix0 + int(w * 0.46), iy0)
    buf.triangle(ix0, iy1, ix0 + int(w * 0.10), iy1, ix0 + int(w * 0.50), iy0)
    buf.pen = color.rgb(120, 128, 150)
    buf.rectangle(ix0, int(h * 0.175), ix1 - ix0, max(2, int(u * 0.9)))
    buf.pen = color.rgb(*CLAW_CABINET_TRIM)
    buf.rectangle(0, int(h * 0.79), w, max(1, u // 2))
    buf.pen = color.rgb(40, 40, 48)
    buf.rectangle(int(w * 0.06), int(h * 0.86), int(w * 0.22), int(h * 0.12))
    buf.pen = color.rgb(20, 20, 26)
    buf.rectangle(int(w * 0.08), int(h * 0.88), int(w * 0.18), int(h * 0.10))
    buf.pen = color.rgb(30, 30, 38)
    buf.rectangle(int(w * 0.46), int(h * 0.86), max(2, u), int(h * 0.10))
    buf.pen = color.rgb(230, 60, 90)
    buf.circle(int(w * 0.465), int(h * 0.86), max(2, int(u * 2.0)))
    buf.pen = color.rgb(60, 200, 120)
    buf.circle(int(w * 0.66), int(h * 0.90), max(2, int(u * 1.8)))
    buf.pen = color.rgb(*CLAW_MARQUEE)
    buf.circle(int(w * 0.82), int(h * 0.90), max(2, int(u * 1.8)))
    buf.pen = color.rgb(20, 20, 26)
    buf.rectangle(int(w * 0.90), int(h * 0.855), max(2, u), int(h * 0.05))


def _g_claw_machine_a(dst, t):
    """A whole cabinet running, and a claw that loses the prize every lap.

    The grab was here; the machine around it was dead. Now the marquee and
    the side rails chase, the coin buttons breathe, a reflection crosses the
    glass -- and on the way up the claw fumbles, which is the only honest
    outcome and costs one circle. The dropped prize falls from where the
    claw actually was at `CLAW_RELEASE`, not from wherever it is now.
    """
    import math
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    cx = int(w * 0.5 + math.cos(t * 6.283) * w * CLAW_SWING)
    ry = int(h * 0.175)
    dip = max(0.0, math.sin(t * 6.283))
    cy = ry + int(h * CLAW_DROP * dip * dip)
    dst.pen = color.rgb(180, 188, 210)
    dst.rectangle(cx - u * 2, ry - max(1, u // 2), u * 4, max(2, int(u * 1.6)))
    dst.pen = color.rgb(200, 200, 210)
    dst.line(cx, ry, cx, cy)
    op = int(u * 2 * (1.0 - dip))
    dst.pen = color.rgb(150, 158, 180)
    dst.triangle(cx - u * 2, cy, cx + u * 2, cy, cx, cy + u * 2)
    dst.pen = color.rgb(210, 216, 235)
    dst.triangle(cx - u, cy + u, cx - u * 3 - op, cy + u * 4, cx - u * 2 - op, cy + u)
    dst.triangle(cx + u, cy + u, cx + u * 3 + op, cy + u * 4, cx + u * 2 + op, cy + u)
    if dip > 0.86:
        dst.pen = color.rgb(*CLAW_PRIZE_PINK)
        dst.circle(cx, cy + u * 3, max(2, int(u * 1.6)))
    if CLAW_RELEASE < t < CLAW_RELEASE + 0.25:
        q = (t - CLAW_RELEASE) * 4.0
        rx = int(w * 0.5 + math.cos(CLAW_RELEASE * 6.283) * w * CLAW_SWING)
        dst.pen = color.rgb(*CLAW_PRIZE_LEMON)
        dst.circle(rx, ry + int(h * (CLAW_DROP * 0.5 + 0.30 * q * q)), max(2, int(u * 1.6)))
    for i in range(CLAW_BULBS):
        if (i + int(t * 8)) % 2 == 0:
            dst.pen = color.rgb(*CLAW_BULB_A)
        else:
            dst.pen = color.rgb(*CLAW_BULB_B)
        dst.circle(int(w * (i + 0.5) / CLAW_BULBS), int(h * 0.052), max(1, int(u * 1.1)))
    chase = int(t * 8)
    for i in range(CLAW_SIDE_BULBS):
        if (i + chase) % 3 == 0:
            dst.pen = color.rgb(*CLAW_BULB_A)
        else:
            dst.pen = color.rgb(*CLAW_BULB_B)
        by = int(h * (0.26 + i * 0.20))
        dst.circle(int(w * 0.035), by, max(1, u))
        dst.circle(int(w * 0.965), by, max(1, u))
    glow = abs(2.0 * ((t * CLAW_BUTTON_PULSE) % 1.0) - 1.0)
    dst.pen = color.rgb(255, 120, 150, 120 + int(120 * glow))
    dst.circle(int(w * 0.465), int(h * 0.86), max(2, int(u * (1.4 + 0.7 * glow))))
    dst.pen = color.rgb(120, 255, 180, 120 + int(120 * (1.0 - glow)))
    dst.circle(int(w * 0.66), int(h * 0.90), max(2, int(u * (1.2 + 0.7 * (1.0 - glow)))))
    dst.pen = color.rgb(CLAW_MARQUEE[0], CLAW_MARQUEE[1], CLAW_MARQUEE[2], 120 + int(120 * glow))
    dst.circle(int(w * 0.82), int(h * 0.90), max(2, int(u * (1.2 + 0.7 * glow))))
    sx = int(-w * 0.3 + w * 1.4 * ((t * 1 + 0.5) % 1.0))
    dst.pen = color.rgb(255, 255, 255, 26)
    dst.triangle(sx, int(h * 0.78), sx + int(w * 0.10), int(h * 0.15), sx + int(w * 0.22), int(h * 0.15))


# @skinlab {"type":"color","label":"Backdrop","group":"Palette"}
PARTY_BACK = (246, 72, 124)

# @skinlab {"type":"color","label":"Light rays","group":"Palette"}
PARTY_RAYS = (255, 138, 168)

# @skinlab {"type":"color","label":"Bunting, mint","group":"Palette"}
PARTY_BUNTING_A = (80, 220, 200)

# @skinlab {"type":"color","label":"Bunting, lemon","group":"Palette"}
PARTY_BUNTING_B = (255, 226, 90)

# @skinlab {"type":"color","label":"Bunting, violet","group":"Palette"}
PARTY_BUNTING_C = (140, 130, 255)

# @skinlab {"type":"color","label":"Bunting, cream","group":"Palette"}
PARTY_BUNTING_D = (255, 250, 244)

# @skinlab {"type":"color","label":"Balloon, red","group":"Palette"}
PARTY_BALLOON_A = (255, 92, 96)

# @skinlab {"type":"color","label":"Balloon, blue","group":"Palette"}
PARTY_BALLOON_B = (110, 200, 255)

# @skinlab {"type":"color","label":"Balloon, yellow","group":"Palette"}
PARTY_BALLOON_C = (255, 226, 90)

# @skinlab {"type":"color","label":"Cake","group":"Palette"}
PARTY_CAKE = (112, 58, 38)

# @skinlab {"type":"color","label":"Candle flame","group":"Palette"}
PARTY_FLAME = (255, 140, 30)

# @skinlab {"type":"integer","label":"Confetti on the floor","group":"Layout","min":0,"max":40,"step":1}
PARTY_CONFETTI = 20

# @skinlab {"type":"integer","label":"Falling confetti","group":"Layout","min":0,"max":20,"step":1}
PARTY_FALLING = 16

# A whole number of falls per loop. Confetti that teleports back to the
# ceiling every four seconds is the one thing a party does not do.
# @skinlab {"type":"integer","label":"Falls per loop","group":"Motion","min":1,"max":3,"step":1}
PARTY_FALL = 1

# @skinlab {"type":"integer","label":"Icing twinkles","group":"Layout","min":0,"max":7,"step":1}
PARTY_TWINKLES = 3

# @skinlab {"type":"integer","label":"Cake sparkles","group":"Layout","min":0,"max":6,"step":1}
PARTY_SPARKLES = 4

# @skinlab {"type":"number","label":"Candle flicker","group":"Motion","min":5,"max":60,"step":1}
PARTY_FLICKER = 25.0


def _g_party_mode(buf):
    import math
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    buf.pen = color.rgb(*PARTY_BACK)
    buf.clear()
    cx, cy = w // 2, int(h * 0.86)
    rr = int(w * 2.0)
    for i in range(16):
        if i % 2:
            continue
        a0 = 3.1416 + i * 0.19635
        a1 = a0 + 0.19635
        buf.pen = color.rgb(*PARTY_RAYS)
        buf.triangle(cx, cy, cx + int(math.cos(a0) * rr), cy + int(math.sin(a0) * rr),
                     cx + int(math.cos(a1) * rr), cy + int(math.sin(a1) * rr))
    buf.pen = color.rgb(46, 26, 62)
    buf.line(0, int(h * 0.085), int(w * 0.5), int(h * 0.145))
    buf.line(int(w * 0.5), int(h * 0.145), w, int(h * 0.065))
    flag = (PARTY_BUNTING_A, PARTY_BUNTING_B, PARTY_BUNTING_C, PARTY_BUNTING_D)
    for i in range(8):
        fx = int(w * (i + 0.5) / 8.0)
        fy = int(h * (0.085 + 0.058 * math.sin(3.1416 * i / 7.0)))
        c = flag[i % 4]
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.triangle(fx - int(w * 0.058), fy, fx + int(w * 0.058), fy, fx, fy + int(h * 0.115))
    bal = ((0.12, 0.36, 0.105, PARTY_BALLOON_A), (0.88, 0.30, 0.095, PARTY_BALLOON_B),
           (0.78, 0.52, 0.072, PARTY_BALLOON_C))
    for i in range(3):
        bx = int(w * bal[i][0])
        by = int(h * bal[i][1])
        br = int(h * bal[i][2])
        c = bal[i][3]
        buf.pen = color.rgb(40, 20, 50, 80)
        buf.line(bx, by + br, bx + (u * 2 if i % 2 else -u * 2), by + br + int(h * 0.18))
        buf.pen = color.rgb(c[0] * 3 // 5, c[1] * 3 // 5, c[2] * 3 // 5)
        buf.circle(bx, by, br)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.circle(bx - max(1, br // 6), by - max(1, br // 6), int(br * 0.86))
        buf.pen = color.rgb(255, 255, 255, 180)
        buf.circle(bx - br // 2, by - br // 2, max(1, br // 4))
        buf.pen = color.rgb(c[0] * 3 // 5, c[1] * 3 // 5, c[2] * 3 // 5)
        buf.triangle(bx - u, by + br, bx + u, by + br, bx, by + br + max(2, u))
    kx0, kx1 = int(w * 0.24), int(w * 0.76)
    ky = int(h * 0.66)
    buf.pen = color.rgb(250, 250, 252)
    buf.rectangle(int(w * 0.16), int(h * 0.905), int(w * 0.68), int(h * 0.05))
    buf.circle(int(w * 0.16), int(h * 0.93), max(1, int(h * 0.028)))
    buf.circle(int(w * 0.84), int(h * 0.93), max(1, int(h * 0.028)))
    buf.pen = color.rgb(*PARTY_CAKE)
    buf.rectangle(kx0, ky, kx1 - kx0, int(h * 0.25))
    buf.pen = color.rgb(146, 80, 50)
    buf.rectangle(kx0, ky + int(h * 0.09), kx1 - kx0, int(h * 0.035))
    buf.pen = color.rgb(255, 246, 236)
    buf.rectangle(kx0, ky - int(h * 0.045), kx1 - kx0, int(h * 0.06))
    for i in range(8):
        buf.circle(kx0 + (kx1 - kx0) * i // 7, ky + int(h * 0.016), max(2, int(u * 1.8)))
    buf.pen = color.rgb(255, 92, 150)
    for i in range(7):
        buf.circle(kx0 + int((kx1 - kx0) * (0.08 + i * 0.14)), ky - int(h * 0.035), max(1, int(u * 1.2)))
    cand = ((0.34, (90, 200, 255)), (0.5, (255, 232, 96)), (0.66, (150, 130, 255)))
    for i in range(3):
        c = cand[i][1]
        cxx = int(w * cand[i][0])
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(cxx - max(1, int(u * 0.7)), ky - int(h * 0.20), max(2, int(u * 1.4)), int(h * 0.17))
        buf.pen = color.rgb(255, 255, 255, 130)
        buf.rectangle(cxx - max(1, int(u * 0.7)), ky - int(h * 0.16), max(2, int(u * 1.4)), max(1, u // 2))
    conf = ((250, 250, 250), (80, 220, 200), (255, 226, 90), (140, 130, 255), (46, 26, 62))
    for i in range(PARTY_CONFETTI):
        a = (i * i * 31 + i * 17) % 101
        b = (i * i * 47 + i * 23) % 83
        x = int(w * a / 101.0)
        y = int(h * b / 83.0)
        c = conf[i % 5]
        buf.pen = color.rgb(c[0], c[1], c[2])
        if i % 3 == 0:
            buf.circle(x, y, max(1, u // 2))
        elif i % 3 == 1:
            buf.rectangle(x, y, max(1, u), max(2, int(u * 1.6)))
        else:
            buf.triangle(x, y, x + max(2, u), y, x, y + max(2, u))


def _g_party_mode_a(dst, t):
    """More party. The confetti falls thicker, the candles gutter, and the
    cake answers them: the icing dots twinkle on the flames' own clock and
    four sparkles fire off the frosting, kept below the nickname band where
    a fast twitch is nobody's problem."""
    import math
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    conf = ((250, 250, 250), (80, 220, 200), (255, 226, 90), (140, 130, 255), (255, 120, 90))
    kx0, kx1 = int(w * 0.24), int(w * 0.76)
    kyc = int(h * 0.66)
    for i in range(PARTY_TWINKLES):
        j = (i * 3 + 1) % 7
        g = abs(2.0 * ((t * 3 + i * 0.3) % 1.0) - 1.0)
        dst.pen = color.rgb(255, 92 + int(120 * g), 150 + int(80 * g))
        dst.circle(kx0 + int((kx1 - kx0) * (0.08 + j * 0.14)), kyc - int(h * 0.035),
                   max(1, int(u * (1.0 + 0.5 * g))))
    for i in range(PARTY_SPARKLES):
        p = (t * 2 + i * 0.25) % 1.0
        if p > 0.4:
            continue
        g = max(1, int(u * (1.5 - 3.2 * abs(p - 0.2))))
        sx = kx0 + (kx1 - kx0) * (i * 2 + 1) // (PARTY_SPARKLES * 2)
        sy = kyc + int(h * (0.10 + 0.09 * (i % 2)))
        dst.pen = color.rgb(255, 250, 230)
        dst.rectangle(sx - g, sy - max(1, u // 3), g * 2, max(1, u * 2 // 3))
        dst.rectangle(sx - max(1, u // 3), sy - g, max(1, u * 2 // 3), g * 2)
    for i in range(PARTY_FALLING):
        ph = ((i * 37) % 100) / 100.0
        sp = PARTY_FALL + (i * 13) % 2
        p = (t * sp + ph) % 1.0
        y = int(p * (h + u * 4)) - u * 2
        x = int(w * (((i * 29 + 11) % 97) / 97.0) + math.sin(p * 12.56 + ph * 6.0) * u * 2)
        c = conf[i % 5]
        dst.pen = color.rgb(c[0], c[1], c[2])
        sw = max(1, int(u * 1.7 * abs(math.sin(p * 18.8 + ph * 6.28))))
        dst.rectangle(x, y, sw, max(2, int(u * 1.5)))
    ky = int(h * 0.66)
    for i in range(3):
        cxx = int(w * (0.34 + i * 0.16))
        fy = ky - int(h * 0.21)
        fw = max(1, int(u * (1.0 + 0.45 * math.sin(t * PARTY_FLICKER + i * 2.1))))
        dst.pen = color.rgb(*PARTY_FLAME)
        dst.triangle(cxx - fw, fy, cxx + fw, fy, cxx, fy - int(u * 3))
        dst.pen = color.rgb(255, 240, 150)
        dst.triangle(cxx - max(1, fw // 2), fy, cxx + max(1, fw // 2), fy, cxx, fy - int(u * 1.6))


# @skinlab {"type":"color","label":"Wall","group":"Palette"}
LAVA_WALL = (14, 6, 34)

# @skinlab {"type":"color","label":"Room glow","group":"Palette"}
LAVA_GLOW = (255, 120, 60)

# @skinlab {"type":"color","label":"Glass edge","group":"Palette"}
LAVA_GLASS = (64, 20, 78)

# @skinlab {"type":"color","label":"Goo","group":"Palette"}
LAVA_GOO = (180, 30, 140)

# @skinlab {"type":"color","label":"Bulb glow","group":"Palette"}
LAVA_BULB = (255, 190, 90)

# @skinlab {"type":"color","label":"Molten pool","group":"Palette"}
LAVA_POOL = (255, 128, 40)

# @skinlab {"type":"color","label":"Brass cap","group":"Palette"}
LAVA_BRASS = (232, 194, 110)

# @skinlab {"type":"color","label":"Base","group":"Palette"}
LAVA_BASE = (180, 142, 72)

# @skinlab {"type":"color","label":"Rising blob","group":"Palette"}
LAVA_BLOB = (255, 100, 36)

# @skinlab {"type":"color","label":"Blob highlight","group":"Palette"}
LAVA_BLOB_LIGHT = (255, 200, 96)

# @skinlab {"type":"integer","label":"Glass bands","group":"Layout","min":12,"max":60,"step":1}
LAVA_ROWS = 42

# @skinlab {"type":"number","label":"Lamp bulge","group":"Shape","min":0.12,"max":0.2,"step":0.005}
LAVA_BULGE = 0.140

# @skinlab {"type":"integer","label":"Rising blobs","group":"Layout","min":1,"max":8,"step":1}
LAVA_BLOBS = 6

# @skinlab {"type":"integer","label":"Sinking blobs","group":"Layout","min":0,"max":5,"step":1}
LAVA_FALLERS = 3

# @skinlab {"type":"integer","label":"Bubbles","group":"Layout","min":0,"max":4,"step":1}
LAVA_BUBBLES = 2

# A whole number of rises per loop. The blobs vary by PHASE, not by speed:
# a lamp where one blob overtakes another at 1.9x reads as a fault, and a
# fractional speed also teleports every blob at `t = 1 -> 0`.
# @skinlab {"type":"integer","label":"Rises per loop","group":"Motion","min":1,"max":4,"step":1}
LAVA_RISE = 1


def _d1(buf):
    import math
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    steps = 40
    for i in range(steps):
        k = i * 255 // steps
        buf.pen = color.rgb(LAVA_WALL[0] + k * 44 // 255, LAVA_WALL[1] + k * 12 // 255,
                            LAVA_WALL[2] + k * 16 // 255)
        buf.rectangle(0, h * i // steps, w, h // steps + 2)
    cx = w // 2
    buf.pen = color.rgb(LAVA_GLOW[0], LAVA_GLOW[1], LAVA_GLOW[2], 20)
    buf.circle(cx, int(h * 0.58), int(w * 0.50))
    buf.circle(cx, int(h * 0.58), int(w * 0.36))
    buf.circle(cx, int(h * 0.66), int(w * 0.24))
    gy0, gy1 = int(h * 0.17), int(h * 0.80)
    rows = LAVA_ROWS
    rh = (gy1 - gy0) // rows + 2
    for i in range(rows):
        y = gy0 + (gy1 - gy0) * i // rows
        f = i / float(rows)
        hw = int(w * (0.050 + LAVA_BULGE * math.sin(f * 1.75 + 0.30)))
        buf.pen = color.rgb(*LAVA_GLASS)
        buf.rectangle(cx - hw, y, hw * 2, rh)
        buf.pen = color.rgb(LAVA_GOO[0] + int(f * 40), LAVA_GOO[1] + int(f * 30),
                            LAVA_GOO[2] - int(f * 60))
        buf.rectangle(cx - hw + u, y, hw * 2 - u * 2, rh)
    buf.pen = color.rgb(LAVA_BULB[0], LAVA_BULB[1], LAVA_BULB[2], 150)
    buf.rectangle(cx - int(w * 0.16), gy1 - int(h * 0.10), int(w * 0.32), int(h * 0.10))
    buf.pen = color.rgb(*LAVA_POOL)
    buf.circle(cx - int(w * 0.07), gy1 - int(h * 0.04), int(h * 0.07))
    buf.circle(cx + int(w * 0.075), gy1 - int(h * 0.035), int(h * 0.055))
    buf.circle(cx, gy1 - int(h * 0.012), int(h * 0.06))
    buf.pen = color.rgb(255, 226, 170, 120)
    buf.rectangle(cx - int(w * 0.11), gy0 + int(h * 0.10), max(1, u), int(h * 0.40))
    buf.pen = color.rgb(*LAVA_BRASS)
    buf.triangle(cx - int(w * 0.068), int(h * 0.175), cx + int(w * 0.068), int(h * 0.175),
                 cx, int(h * 0.035))
    buf.rectangle(cx - int(w * 0.032), int(h * 0.025), int(w * 0.064), int(h * 0.05))
    buf.circle(cx, int(h * 0.025), max(2, int(u * 1.3)))
    buf.triangle(cx - int(w * 0.115), int(h * 0.955), cx + int(w * 0.115), int(h * 0.955),
                 cx, int(h * 0.760))
    buf.pen = color.rgb(*LAVA_BASE)
    buf.rectangle(cx - int(w * 0.145), int(h * 0.945), int(w * 0.29), int(h * 0.055))
    buf.pen = color.rgb(255, 236, 170, 130)
    buf.line(cx - int(w * 0.06), int(h * 0.83), cx - int(w * 0.035), int(h * 0.93))


def _d1_a(dst, t):
    """The whole convection, not one lane of it.

    A lamp is a loop: wax rises up the warm middle, cools at the cap, and
    slides back down the glass. Only the rise was here, so the picture had a
    column of beads going one way forever. Now the sinking ones run down the
    far wall, the pool necks and breathes on the bulb's own pulse, and every
    blob is clamped inside `hw` -- the same bulge profile the render used to
    cut the glass -- so nothing walks through the wall.
    """
    import math
    w, h = dst.width, dst.height
    u = max(1, w // 40)
    cx = w // 2
    gy0, gy1 = int(h * 0.17), int(h * 0.80)
    span = max(1, gy1 - gy0)
    q = abs(2.0 * ((t * LAVA_RISE * 2) % 1.0) - 1.0)
    dst.pen = color.rgb(LAVA_BULB[0], LAVA_BULB[1], LAVA_BULB[2], 120 + int(80 * q))
    dst.rectangle(cx - int(w * 0.16), gy1 - int(h * 0.10), int(w * 0.32), int(h * 0.10))
    for i in range(LAVA_FALLERS):
        ph = ((i * 53) % 100) / 100.0
        p = (t * LAVA_RISE + ph) % 1.0
        y = gy0 + int(span * p)
        f = (y - gy0) / float(span)
        hw = int(w * (0.050 + LAVA_BULGE * math.sin(f * 1.75 + 0.30)))
        r = max(1, int(h * 0.030 * (min(1.0, 3.0 * min(p, 1.0 - p) + 0.10))))
        x = cx - int(math.sin(p * 6.283 + ph * 7) * max(0, hw - r - u))
        dst.pen = color.rgb(LAVA_BLOB[0] * 3 // 4, LAVA_BLOB[1] * 2 // 3, LAVA_BLOB[2] // 2)
        dst.circle(x, y, r)
    for i in range(LAVA_BLOBS):
        ph = ((i * 37) % 100) / 100.0
        p = (t * LAVA_RISE + ph) % 1.0
        y = gy1 - int(span * p)
        f = (y - gy0) / float(span)
        hw = int(w * (0.050 + LAVA_BULGE * math.sin(f * 1.75 + 0.30)))
        # A blob must not vanish at the cap and reappear at the pool: it
        # thins to a bead at both ends of its run, which is both what wax
        # does and what makes `t = 1 -> 0` join.
        r = max(1, int(h * (0.062 - 0.016 * (i % 3))
                       * min(1.0, 3.0 * min(p, 1.0 - p) + 0.10)))
        x = cx + int(math.sin(p * 6.283 + ph * 9) * max(0, hw - r - u))
        dst.pen = color.rgb(*LAVA_BLOB)
        dst.circle(x, y, r)
        dst.pen = color.rgb(*LAVA_BLOB_LIGHT)
        dst.circle(x - r // 3, y - r // 3, max(1, r // 3))
    for i in range(LAVA_BUBBLES):
        p = (t * LAVA_RISE * 3 + i * 0.4) % 1.0
        dst.pen = color.rgb(255, 220, 170, 150)
        dst.circle(cx + (i * 2 - 1) * int(w * 0.05), gy1 - int(span * p), max(1, u // 2))
    neck = int(h * 0.035 * q)
    dst.pen = color.rgb(*LAVA_POOL)
    dst.circle(cx - int(w * 0.07), gy1 - int(h * 0.04), int(h * (0.060 + 0.020 * q)))
    dst.circle(cx + int(w * 0.075), gy1 - int(h * 0.035), int(h * (0.050 + 0.015 * (1.0 - q))))
    dst.circle(cx, gy1 - int(h * 0.012) - neck, max(2, int(h * (0.045 + 0.020 * q))))
    dst.pen = color.rgb(*LAVA_BLOB_LIGHT)
    dst.circle(cx - int(w * 0.02), gy1 - int(h * 0.030) - neck, max(1, int(h * 0.015)))


# @skinlab {"type":"color","label":"Hot pink","group":"Palette"}
BOMB_PINK = (255, 62, 88)

# @skinlab {"type":"color","label":"Orange","group":"Palette"}
BOMB_ORANGE = (255, 150, 24)

# @skinlab {"type":"color","label":"Lemon","group":"Palette"}
BOMB_LEMON = (250, 226, 72)

# @skinlab {"type":"color","label":"Mint","group":"Palette"}
BOMB_MINT = (36, 200, 132)

# @skinlab {"type":"color","label":"Azure","group":"Palette"}
BOMB_AZURE = (40, 148, 255)

# @skinlab {"type":"color","label":"Violet","group":"Palette"}
BOMB_VIOLET = (160, 96, 255)

# @skinlab {"type":"color","label":"Bubblegum","group":"Palette"}
BOMB_BUBBLEGUM = (255, 96, 176)

# @skinlab {"type":"color","label":"Teal","group":"Palette"}
BOMB_TEAL = (14, 200, 200)

# @skinlab {"type":"color","label":"Backdrop and cutouts","group":"Palette"}
BOMB_INK = (20, 20, 26)

# @skinlab {"type":"color","label":"Sticker border","group":"Palette"}
BOMB_BORDER = (248, 248, 250)

# @skinlab {"type":"color","label":"Tape","group":"Palette"}
BOMB_TAPE = (246, 240, 224)

# @skinlab {"type":"color","label":"Tape stripe, warm","group":"Palette"}
BOMB_TAPE_WARM = (255, 72, 96)

# @skinlab {"type":"color","label":"Tape stripe, cool","group":"Palette"}
BOMB_TAPE_COOL = (58, 162, 255)

# @skinlab {"type":"number","label":"Sticker size","group":"Shape","min":0.045,"max":0.1,"step":0.005}
BOMB_SIZE = 0.072


# STICKERBOMB IS DELIBERATELY STILL, and this note is why it stays that way.
#
# It was reviewed for animation on 2026-08-18 with the rest of PLAY, under an
# instruction to default toward motion and spend the frame budget. Every other
# skin in the group took it. This one is a laptop lid: twenty-four vinyl
# stickers slapped over each other under a strip of gaffer tape. The subject is
# a surface that has been COVERED, and the only honest reading of motion on it
# is a highlight travelling over the vinyl -- which is exactly the generic
# sweep `poster.py` names as worse than nothing, "dragging a foreign highlight
# across somebody's composition to prove a checkbox works".
#
# The cost of animating it is also concrete rather than notional: a `None` in
# the fourth SKINS field is what makes `generate_catalogue.py` treat this entry
# as VIVID, and any animator at all flips it to MUTED -- saturation(-130) plus
# blur(1) when the badge bakes it as a home screen. Twenty-four hard-edged
# stickers are the worst thing in the catalogue to blur. So: still, on purpose.
def _d2(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    buf.pen = color.rgb(*BOMB_INK)
    buf.clear()
    buf.pen = color.rgb(36, 36, 44)
    for i in range(12):
        buf.rectangle(0, h * i // 12, w, max(1, u // 2))
    pal = (BOMB_PINK, BOMB_ORANGE, BOMB_LEMON, BOMB_MINT,
           BOMB_AZURE, BOMB_VIOLET, BOMB_BUBBLEGUM, BOMB_TEAL)
    edge = max(1, u // 2)
    for i in range(24):
        gx = i % 6
        gy = i // 6
        jx = ((i * i * 37 + i * 61) % 17) - 8
        jy = ((i * i * 53 + i * 29) % 15) - 7
        x = int(w * (gx + 0.5) / 6.0) + int(w * jx / 110.0)
        y = int(h * (gy + 0.5) / 4.0) + int(h * jy / 90.0)
        s = int(w * (BOMB_SIZE + 0.056 * (((i * 41 + 13) % 5) / 4.0)))
        col = pal[(i * 3) % 8]
        k = (i * 7 + i // 6) % 5
        buf.pen = color.rgb(*BOMB_BORDER)
        if k == 0:
            buf.circle(x, y, s + edge)
            buf.pen = color.rgb(col[0], col[1], col[2])
            buf.circle(x, y, s)
            buf.pen = color.rgb(*BOMB_INK)
            buf.circle(x, y, max(1, s // 3))
        elif k == 1:
            buf.rectangle(x - s - edge, y - s - edge, s * 2 + edge * 2, s * 2 + edge * 2)
            buf.pen = color.rgb(col[0], col[1], col[2])
            buf.rectangle(x - s, y - s, s * 2, s * 2)
            buf.pen = color.rgb(*BOMB_INK)
            buf.rectangle(x - s, y - max(1, s // 4), s * 2, max(1, s // 2))
        elif k == 2:
            buf.triangle(x - s - edge * 2, y + s + edge, x + s + edge * 2, y + s + edge, x, y - s - edge * 2)
            buf.pen = color.rgb(col[0], col[1], col[2])
            buf.triangle(x - s, y + s, x + s, y + s, x, y - s)
            buf.pen = color.rgb(*BOMB_INK)
            buf.circle(x, y + s // 3, max(1, s // 4))
        elif k == 3:
            buf.rectangle(x - s - edge, y - (s // 2) - edge, s * 2 + edge * 2, s + edge * 2)
            buf.circle(x - s, y, s // 2 + edge)
            buf.circle(x + s, y, s // 2 + edge)
            buf.pen = color.rgb(col[0], col[1], col[2])
            buf.rectangle(x - s, y - s // 2, s * 2, max(2, s))
            buf.circle(x - s, y, max(1, s // 2))
            buf.circle(x + s, y, max(1, s // 2))
        else:
            buf.circle(x, y, s + edge)
            buf.pen = color.rgb(col[0], col[1], col[2])
            buf.triangle(x - s, y - s // 2, x + s, y - s // 2, x, y + s)
            buf.triangle(x - s, y + s // 2, x + s, y + s // 2, x, y - s)
    ty0 = int(h * 0.27)
    th = int(h * 0.185)
    buf.pen = color.rgb(16, 14, 18)
    buf.rectangle(-u, ty0 - max(1, u), w + u * 2, th + u * 2)
    buf.pen = color.rgb(*BOMB_TAPE)
    buf.rectangle(-u, ty0, w + u * 2, th)
    buf.pen = color.rgb(16, 14, 18)
    for i in range(9):
        x = w * i // 8
        buf.triangle(x, ty0 - 1, x + w // 8, ty0 - 1, x + w // 16, ty0 + max(2, int(u * 1.4)))
        buf.triangle(x, ty0 + th + 1, x + w // 8, ty0 + th + 1, x + w // 16, ty0 + th - max(2, int(u * 1.4)))
    buf.pen = color.rgb(*BOMB_TAPE_WARM)
    buf.rectangle(-u, ty0 + max(2, int(u * 1.5)), w + u * 2, max(1, u // 3))
    buf.pen = color.rgb(*BOMB_TAPE_COOL)
    buf.rectangle(-u, ty0 + th - max(2, int(u * 1.8)), w + u * 2, max(1, u // 3))
    buf.pen = color.rgb(255, 168, 36)
    buf.circle(int(w * 0.09), ty0 - max(2, int(u * 1.6)), max(2, int(u * 2.6)))
    buf.pen = color.rgb(*BOMB_INK)
    buf.circle(int(w * 0.09), ty0 - max(2, int(u * 1.6)), max(1, u))
    buf.pen = color.rgb(64, 208, 146)
    buf.triangle(int(w * 0.88) - u * 4, ty0 + th + u * 4, int(w * 0.88) + u * 4, ty0 + th + u * 4,
                 int(w * 0.88), ty0 + th - u)


# ── AERO RIBBON ───────────────────────────────────────────
# AERO RIBBON - a wide band of light swooping across deep blue, cyan fading to lime, with a hard specular top edge and a glint running along it.

# @skinlab {"type":"color","label":"Field (top)","group":"Palette"}
RIBBON_SKY_TOP = (8, 40, 128)


# @skinlab {"type":"color","label":"Field (bottom)","group":"Palette"}
RIBBON_SKY_LOW = (18, 118, 204)


# @skinlab {"type":"color","label":"Ribbon (left)","group":"Palette"}
RIBBON_LEFT = (44, 214, 246)


# @skinlab {"type":"color","label":"Ribbon (right)","group":"Palette"}
RIBBON_RIGHT = (150, 236, 88)


# @skinlab {"type":"color","label":"Specular edge","group":"Palette"}
RIBBON_EDGE = (245, 255, 255)


# @skinlab {"type":"integer","label":"Segments","group":"Layout","min":16,"max":64,"step":4}
RIBBON_SEGMENTS = 44


# @skinlab {"type":"number","label":"Swoop","group":"Shape","min":0.02,"max":0.3,"step":0.01}
RIBBON_AMP = 0.15


# @skinlab {"type":"number","label":"Ribbon depth","group":"Shape","min":0.06,"max":0.34,"step":0.02}
RIBBON_THICK = 0.22


# @skinlab {"type":"number","label":"Ribbon centre","group":"Layout","min":0.3,"max":0.75,"step":0.01}
RIBBON_BASE = 0.54


# @skinlab {"type":"integer","label":"Bokeh lights","group":"Layout","min":0,"max":18,"step":1}
RIBBON_BOKEH = 11


# @skinlab {"type":"number","label":"Glint speed","group":"Motion","min":0.25,"max":3,"step":0.25}
RIBBON_GLINT_SPEED = 1.0


# @skinlab {"type":"boolean","label":"Second ribbon","group":"Details"}
RIBBON_TWIN = True


# @skinlab {"type":"integer","label":"Glint trail","group":"Motion","min":1,"max":10,"step":1}
RIBBON_GLINT_TRAIL = 6


# @skinlab {"type":"integer","label":"Twin glint trail","group":"Motion","min":0,"max":8,"step":1}
RIBBON_TWIN_TRAIL = 4


# @skinlab {"type":"integer","label":"Drifting lights","group":"Motion","min":0,"max":10,"step":1}
RIBBON_DRIFT = 6


# @skinlab {"type":"number","label":"Drift speed","group":"Motion","min":0.25,"max":3,"step":0.25}
RIBBON_DRIFT_SPEED = 1.0


# @skinlab {"type":"integer","label":"Edge sparkles","group":"Motion","min":0,"max":10,"step":1}
RIBBON_SPARKLE = 6


# @skinlab {"type":"integer","label":"Light streaks","group":"Motion","min":0,"max":4,"step":1}
RIBBON_STREAKS = 2


def _aero_ribbon_ribbon_mix(a, b, k):
    if k < 0.0:
        k = 0.0
    if k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _aero_ribbon_ribbon_y(f, h, base, amp, turn):
    """Centre of the band at horizontal fraction f. One whole sine over the
    canvas, so the left and right edges meet and a glint can wrap through."""
    return int(h * base + h * amp * math.sin(f * 2.0 * math.pi + turn))


def _aero_ribbon_ribbon_th(f, h, thick):
    """Thicker in the middle, tapering to the edges."""
    return max(2, int(h * thick * (0.42 + 0.58 * math.sin(f * math.pi))))


def _aero_ribbon(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, u // 4)   # the catalogue's stroke unit: 1 logical px at LORES, 2 at HIRES

    # the field, one filled row per line
    for y in range(h):
        c = _aero_ribbon_ribbon_mix(RIBBON_SKY_TOP, RIBBON_SKY_LOW, (y / max(1, h - 1)) ** 1.3)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(0, y, w, 1)

    # bokeh: small defocused lights, small enough that alpha still reads as
    # light. Radius 2 is the floor — circle() draws a plus below that.
    for i in range(RIBBON_BOKEH):
        buf.pen = color.rgb(206, 244, 255, 16 + (i * 37) % 22)
        buf.circle((i * 137) % w, (i * 89) % h, max(2, u + ((i * 11) % 3) * u // 2))

    step = max(1, w // RIBBON_SEGMENTS)

    # the faint twin, behind and below
    if RIBBON_TWIN:
        for x in range(0, w, step):
            f = x / max(1, w)
            cy = _aero_ribbon_ribbon_y(f, h, RIBBON_BASE + 0.16, RIBBON_AMP * 0.7, 2.4)
            th = max(2, _aero_ribbon_ribbon_th(f, h, RIBBON_THICK * 0.45))
            c = _aero_ribbon_ribbon_mix(RIBBON_RIGHT, RIBBON_LEFT, f)
            buf.pen = color.rgb(c[0], c[1], c[2], 120)
            buf.rectangle(x, cy - th // 2, step, th)
            buf.pen = color.rgb(RIBBON_EDGE[0], RIBBON_EDGE[1], RIBBON_EDGE[2], 150)
            buf.rectangle(x, cy - th // 2, step, max(1, s))

    # the hero ribbon: body, bright core, hard specular top edge
    for x in range(0, w, step):
        f = x / max(1, w)
        cy = _aero_ribbon_ribbon_y(f, h, RIBBON_BASE, RIBBON_AMP, 0.6)
        th = _aero_ribbon_ribbon_th(f, h, RIBBON_THICK)
        c = _aero_ribbon_ribbon_mix(RIBBON_LEFT, RIBBON_RIGHT, f)
        deep = _aero_ribbon_ribbon_mix(c, RIBBON_SKY_TOP, 0.34)
        buf.pen = color.rgb(deep[0], deep[1], deep[2])
        buf.rectangle(x, cy - th // 2, step, th)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(x, cy - th // 2, step, max(1, th * 2 // 5))
        core = _aero_ribbon_ribbon_mix(c, RIBBON_EDGE, 0.72)
        buf.pen = color.rgb(core[0], core[1], core[2])
        buf.rectangle(x, cy - th // 6, step, max(1, th // 5))
        buf.pen = color.rgb(*RIBBON_EDGE)
        buf.rectangle(x, cy - th // 2, step, max(1, s))


def _aero_ribbon_a(buf, t):
    """Everything the light touches moves.

    A glint runs the hero ribbon and a second one runs the twin the other way;
    sparkles fire along the specular edge; the bokeh field drifts up through
    the frame; and two soft light streaks lean across the whole picture. The
    ribbon itself is the one thing that stays put -- 44 segments redrawn every
    frame would be a repaint, not an animation.

    Every drifting light fades to nothing at both ends of its travel, so the
    field has no pop at the t = 1 -> 0 wrap even though each light is at a
    different point in its own lap."""
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, u // 4)   # the catalogue's stroke unit: 1 logical px at LORES, 2 at HIRES
    step = max(1, w // RIBBON_SEGMENTS)

    # soft light shafts leaning across the field, behind everything else.
    # WIDE and faint: at two units they came out as hard diagonal scratches,
    # which is the "foreign highlight dragged across the composition" the
    # poster note warns about.
    for i in range(RIBBON_STREAKS):
        sp = (t + i / max(1, RIBBON_STREAKS)) % 1.0
        wide = max(3, u * 6)
        sx = int(sp * (w + wide + h // 3)) - wide - h // 3
        buf.pen = color.rgb(214, 246, 255, 20)
        buf.triangle(sx, h, sx + wide, h, sx + h // 3, 0)
        buf.triangle(sx + wide, h, sx + h // 3, 0, sx + h // 3 + wide, 0)

    # the bokeh field drifts upward and wraps invisibly
    for i in range(RIBBON_DRIFT):
        p = (t * RIBBON_DRIFT_SPEED + i * 0.163) % 1.0
        buf.pen = color.rgb(220, 248, 255, int(58 * math.sin(math.pi * p)))
        buf.circle((i * 137) % w, int(h * (1.0 - p)),
                   max(2, u + ((i * 11) % 3) * u // 2))

    # a glint runs the length of the ribbon and wraps through the seam,
    # trailing dimmer copies behind it
    head = (t * RIBBON_GLINT_SPEED) % 1.0
    for k in range(RIBBON_GLINT_TRAIL):
        f = (head - k * 0.045) % 1.0
        x = int(f * w)
        cy = _aero_ribbon_ribbon_y(f, h, RIBBON_BASE, RIBBON_AMP, 0.6)
        th = _aero_ribbon_ribbon_th(f, h, RIBBON_THICK)
        buf.pen = color.rgb(250, 255, 255, 230 - k * 38)
        buf.rectangle(x, cy - th // 2, max(2, step), max(2, th * 2 // 5))

    # and one the other way down the twin, so the pair reads as two passes of
    # the same light rather than one lit band and one dead one
    if RIBBON_TWIN:
        for k in range(RIBBON_TWIN_TRAIL):
            f = (1.0 - head - k * 0.05) % 1.0
            cy = _aero_ribbon_ribbon_y(f, h, RIBBON_BASE + 0.16, RIBBON_AMP * 0.7, 2.4)
            th = max(2, _aero_ribbon_ribbon_th(f, h, RIBBON_THICK * 0.45))
            buf.pen = color.rgb(235, 252, 255, 170 - k * 36)
            buf.rectangle(int(f * w), cy - th // 2, max(2, step), max(2, th // 2))

    # sparkles firing along the hero ribbon's specular edge. Drawn every frame
    # and switched by brightness: a skipped call would understate the frame
    # where all of them are lit.
    for i in range(RIBBON_SPARKLE):
        f = ((i * 7) % 13) / 13.0
        cy = _aero_ribbon_ribbon_y(f, h, RIBBON_BASE, RIBBON_AMP, 0.6)
        th = _aero_ribbon_ribbon_th(f, h, RIBBON_THICK)
        lit = ((t * 3.0 + i * 0.29) % 1.0) < 0.22
        buf.pen = color.rgb(*RIBBON_EDGE) if lit else color.rgb(
            RIBBON_EDGE[0], RIBBON_EDGE[1], RIBBON_EDGE[2], 70)
        buf.rectangle(int(f * w), cy - th // 2 - s, max(1, s * 2), max(1, s * 2))

# ── AQUA GEL ───────────────────────────────────────────
# AQUA GEL - one fat glossy web-2.0 button floating on a sky gradient, a specular glint sliding across its shine.

# @skinlab {"type":"color","label":"Sky (top)","group":"Palette"}
GEL_SKY_TOP = (10, 70, 164)


# @skinlab {"type":"color","label":"Sky (bottom)","group":"Palette"}
GEL_SKY_BOTTOM = (182, 236, 253)


# @skinlab {"type":"color","label":"Button","group":"Palette"}
GEL_BODY = (12, 122, 206)


# @skinlab {"type":"color","label":"Shine","group":"Palette"}
GEL_GLOSS = (228, 250, 255)


# @skinlab {"type":"color","label":"Chrome bevel","group":"Palette"}
GEL_BEVEL = (240, 250, 255)


# @skinlab {"type":"color","label":"Dock lime","group":"Palette"}
GEL_DOCK_A = (126, 216, 62)


# @skinlab {"type":"color","label":"Dock amber","group":"Palette"}
GEL_DOCK_B = (255, 168, 40)


# @skinlab {"type":"number","label":"Button width","group":"Layout","min":0.4,"max":0.92,"step":0.02}
GEL_WIDTH = 0.76


# @skinlab {"type":"number","label":"Button height","group":"Layout","min":0.24,"max":0.66,"step":0.02}
GEL_HEIGHT = 0.57


# @skinlab {"type":"number","label":"Shine split","group":"Shape","min":0.2,"max":0.7,"step":0.02}
GEL_SPLIT = 0.32


# @skinlab {"type":"integer","label":"Dock lozenges","group":"Layout","min":0,"max":6,"step":1}
GEL_DOCK = 4


# @skinlab {"type":"integer","label":"Bokeh lights","group":"Layout","min":0,"max":16,"step":1}
GEL_BOKEH = 9


# @skinlab {"type":"number","label":"Glint speed","group":"Motion","min":0.25,"max":3,"step":0.25}
GEL_GLINT_SPEED = 1.0


# @skinlab {"type":"boolean","label":"Dock chase","group":"Motion"}
GEL_CHASE = True


# @skinlab {"type":"integer","label":"Glint slabs","group":"Motion","min":1,"max":5,"step":1}
GEL_GLINT_SLABS = 3


# @skinlab {"type":"integer","label":"Drifting lights","group":"Motion","min":0,"max":10,"step":1}
GEL_DRIFT = 5


# @skinlab {"type":"integer","label":"Bevel sparkles","group":"Motion","min":0,"max":8,"step":1}
GEL_SPARKS = 4


# @skinlab {"type":"integer","label":"Gel bubbles","group":"Motion","min":0,"max":6,"step":1}
GEL_BUBBLES = 3


# @skinlab {"type":"number","label":"Bubble speed","group":"Motion","min":1,"max":4,"step":1}
GEL_BUBBLE_SPEED = 1.0


def _aqua_gel_gel_mix(a, b, k):
    if k < 0.0:
        k = 0.0
    if k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _aqua_gel_gel_geom(w, h):
    """The button sits high enough that its shine/body terminator lands ABOVE
    0.28h. The wearer's name is then drawn over one broad flat gradient rather
    than across a hard light-to-dark edge, which is the one thing the polarity
    flip cannot rescue."""
    bw = int(w * GEL_WIDTH)
    bh = max(4, int(h * GEL_HEIGHT))
    return (w - bw) // 2, int(h * 0.09), bw, bh, max(2, bh // 4)


def _aqua_gel_gel_inset(i, n, r):
    """How far row `i` of an `n`-row rounded rect is pulled in at radius `r`."""
    if i < r:
        dy = r - i
    elif i >= n - r:
        dy = i - (n - r) + 1
    else:
        return 0
    q = r * r - dy * dy
    if q <= 0:
        return r
    return r - int(math.sqrt(q))


def _aqua_gel_gel_dot(buf, x, y, r):
    """A disc. circle() at radius 1 rasterises as a five-pixel plus, so the
    smallest dot is a square instead."""
    if r < 2:
        buf.rectangle(x, y, 1, 1)
    else:
        buf.circle(x, y, r)


def _aqua_gel_gel_dock_y(h):
    return int(h * 0.88)


def _aqua_gel_gel_dock_r(u):
    return max(1, int(u * 2.2))


def _aqua_gel(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, u // 4)   # the catalogue's stroke unit: 1 logical px at LORES, 2 at HIRES

    # sky: one filled row per line, squared so the deep blue holds the top
    for y in range(h):
        k = y / max(1, h - 1)
        c = _aqua_gel_gel_mix(GEL_SKY_TOP, GEL_SKY_BOTTOM, k * k)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(0, y, w, 1)

    # bokeh: small out-of-focus lights, kept small so the alpha stays honest
    for i in range(GEL_BOKEH):
        buf.pen = color.rgb(255, 255, 255, 34 + (i * 29) % 46)
        buf.circle((i * 137) % w, (i * 89) % h, max(2, u + ((i * 7) % 3) * u // 2))

    bx, by, bw, bh, r = _aqua_gel_gel_geom(w, h)

    # chrome bevel: the same rounded shape one stroke larger, drawn underneath
    buf.pen = color.rgb(*GEL_BEVEL)
    n = bh + 2 * s
    for i in range(n):
        dx = _aqua_gel_gel_inset(i, n, r + s)
        buf.rectangle(bx - s + dx, by - s + i, bw + 2 * s - 2 * dx, 1)

    # the gel: one row per line, so the round corners and the gradient are free.
    # White shine on top, a hard terminator, then saturated colour that climbs
    # back towards the light bouncing off whatever the button is sitting on.
    gloss_lo = _aqua_gel_gel_mix(GEL_GLOSS, GEL_BODY, 0.58)
    body_hi = _aqua_gel_gel_mix(GEL_BODY, (0, 0, 0), 0.28)
    body_lo = _aqua_gel_gel_mix(GEL_BODY, GEL_GLOSS, 0.66)
    for i in range(bh):
        f = i / max(1, bh - 1)
        if f < GEL_SPLIT:
            c = _aqua_gel_gel_mix(GEL_GLOSS, gloss_lo, (f / GEL_SPLIT) ** 0.8)
        else:
            g = (f - GEL_SPLIT) / max(0.05, 1.0 - GEL_SPLIT)
            c = _aqua_gel_gel_mix(body_hi, body_lo, g ** 2.4)
        dx = _aqua_gel_gel_inset(i, bh, r)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(bx + dx, by + i, bw - 2 * dx, 1)

    # two hard lines finish the gel, and nothing else: a specular hot spot
    # painted on top of a near-white shine only reads as a stray bubble.
    ti = int(bh * GEL_SPLIT)
    dxt = _aqua_gel_gel_inset(ti, bh, r)
    edge = _aqua_gel_gel_mix(GEL_BODY, (0, 0, 0), 0.48)
    buf.pen = color.rgb(edge[0], edge[1], edge[2])
    buf.rectangle(bx + dxt, by + ti, bw - 2 * dxt, max(1, s))
    bi = bh - max(1, s * 2)
    dxb = _aqua_gel_gel_inset(bi, bh, r)
    lip = _aqua_gel_gel_mix(GEL_BODY, GEL_GLOSS, 0.82)
    buf.pen = color.rgb(lip[0], lip[1], lip[2])
    buf.rectangle(bx + dxb, by + bi, bw - 2 * dxb, max(1, s))

    # a dock of little gel lozenges below the hero
    dy = _aqua_gel_gel_dock_y(h)
    dr = _aqua_gel_gel_dock_r(u)
    for i in range(GEL_DOCK):
        cx = int(w * (i + 0.5) / max(1, GEL_DOCK))
        c = GEL_DOCK_A if i % 2 == 0 else GEL_DOCK_B
        buf.pen = color.rgb(*GEL_BEVEL)
        buf.circle(cx, dy, dr + s)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.circle(cx, dy, dr)
        hi = _aqua_gel_gel_mix(c, (255, 255, 255), 0.62)
        buf.pen = color.rgb(hi[0], hi[1], hi[2])
        buf.circle(cx, dy - max(1, dr // 3), max(1, dr // 2))


def _aqua_gel_a(buf, t):
    """The button is a LIQUID, not a decal.

    A stack of glint slabs crosses the shine, bubbles rise inside the gel, the
    chrome bevel sparkles where the light catches it, the whole dock chases,
    and the sky behind drifts. The one hard-edged fast thing -- the sparkle
    row -- is pinned to the bevel at 0.09h, above the name band; the bubbles
    that do cross it are slow and small.

    Every mark is drawn on every frame with its brightness switched rather
    than being skipped, so the measured per-frame cost is the cost of the
    worst frame and not of a lucky one."""
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, u // 4)   # the catalogue's stroke unit: 1 logical px at LORES, 2 at HIRES
    bx, by, bw, bh, r = _aqua_gel_gel_geom(w, h)

    # the sky drifts up behind the button and fades out at both ends
    for i in range(GEL_DRIFT):
        p = (t + i * 0.19) % 1.0
        buf.pen = color.rgb(255, 255, 255, int(74 * math.sin(math.pi * p)))
        buf.circle((i * 137) % w, int(h * (1.0 - p)), max(2, u))

    # bubbles rising through the body of the gel, small and unhurried
    for i in range(GEL_BUBBLES):
        p = (t * GEL_BUBBLE_SPEED + i * 0.37) % 1.0
        by0 = by + bh - max(2, u)
        buf.pen = color.rgb(255, 255, 255, int(150 * math.sin(math.pi * p)))
        buf.circle(bx + r + (i * 53) % max(1, bw - 2 * r),
                   int(by0 - p * bh * 0.42), max(2, u // 2 + (i % 2)))

    # a leaning glint crossing the shine, three slabs deep; alpha folds to
    # zero at both ends so it fades out rather than popping when t wraps
    phase = (t * GEL_GLINT_SPEED) % 1.0
    a = int(190 * math.sin(math.pi * phase))
    gw = max(1, u * 2)
    lean = max(1, u * 2)
    run = max(1, bw - 2 * r - gw - lean)
    y0 = by + max(1, s)
    y1 = by + max(3, int(bh * GEL_SPLIT))
    for k in range(GEL_GLINT_SLABS):
        gx = bx + r + int(run * phase) - k * (gw + max(1, u // 2))
        buf.pen = color.rgb(255, 255, 255, max(0, a - k * 55))
        buf.triangle(gx, y1, gx + lean, y0, gx + lean + gw, y0)
        buf.triangle(gx, y1, gx + gw, y1, gx + lean + gw, y0)

    # sparkles walking the chrome bevel along the top of the button
    for i in range(GEL_SPARKS):
        lit = ((t * 2.0 + i * 0.23) % 1.0) < 0.3
        buf.pen = color.rgb(255, 255, 255, 240 if lit else 60)
        buf.rectangle(bx + r + (i * 71) % max(1, bw - 2 * r), by - s,
                      max(1, s * 2), max(1, s * 2))

    # the dock chases, every lozenge lit by how close the head is to it
    if GEL_CHASE and GEL_DOCK > 0:
        dy = _aqua_gel_gel_dock_y(h)
        dr = _aqua_gel_gel_dock_r(u)
        head = (t * GEL_DOCK) % GEL_DOCK
        for i in range(GEL_DOCK):
            near = abs(head - i - 0.5)
            if near > GEL_DOCK / 2.0:
                near = GEL_DOCK - near
            cx = int(w * (i + 0.5) / GEL_DOCK)
            buf.pen = color.rgb(255, 255, 255, max(0, 120 - int(near * 90)))
            buf.circle(cx, dy, dr + s * 2)
        k = int(head) % GEL_DOCK
        buf.pen = color.rgb(255, 255, 255, 235)
        _aqua_gel_gel_dot(buf, int(w * (k + 0.5) / GEL_DOCK),
                          dy - max(1, dr // 3), max(1, dr // 3))

# ── DEW GLASS ───────────────────────────────────────────
# DEW GLASS - a macro shot of water beading on a pane, each drop a little lens with a hard white highlight, over an out-of-focus sky-and-meadow blur.

# @skinlab {"type":"color","label":"Blur (top)","group":"Palette"}
DEW_TOP = (96, 206, 250)


# @skinlab {"type":"color","label":"Blur (bottom)","group":"Palette"}
DEW_BOTTOM = (74, 178, 62)


# @skinlab {"type":"color","label":"Drop rim","group":"Palette"}
DEW_RIM = (8, 52, 74)


# @skinlab {"type":"color","label":"Highlight","group":"Palette"}
DEW_SPEC = (255, 255, 255)


# @skinlab {"type":"integer","label":"Hero drops","group":"Layout","min":0,"max":12,"step":1}
DEW_HERO = 5


# @skinlab {"type":"integer","label":"Mid drops","group":"Layout","min":0,"max":24,"step":1}
DEW_MID = 9


# @skinlab {"type":"integer","label":"Fine beading","group":"Layout","min":0,"max":48,"step":1}
DEW_FINE = 26


# @skinlab {"type":"number","label":"Drop size","group":"Shape","min":0.5,"max":1.8,"step":0.05}
DEW_SIZE = 1.0


# @skinlab {"type":"integer","label":"Bokeh blobs","group":"Layout","min":0,"max":10,"step":1}
DEW_BOKEH = 5


# @skinlab {"type":"integer","label":"Runners","group":"Motion","min":0,"max":5,"step":1}
DEW_RUNS = 3


# Whole laps only. `0.75 * (1 + 0.3 * i)` put a jump of up to three quarters
# of the pane in every runner at the t = 1 -> 0 wrap.
# @skinlab {"type":"number","label":"Runner speed","group":"Motion","min":1,"max":4,"step":1}
DEW_RUN_SPEED = 1.0


# @skinlab {"type":"boolean","label":"Defocus the backdrop","group":"Look"}
DEW_BLUR = True


# @skinlab {"type":"integer","label":"Twinkling beads","group":"Motion","min":0,"max":16,"step":1}
DEW_TWINKLE = 8


# @skinlab {"type":"number","label":"Twinkle rate","group":"Motion","min":0.5,"max":6,"step":0.5}
DEW_TWINKLE_RATE = 2.0


# @skinlab {"type":"integer","label":"Shed droplets","group":"Motion","min":0,"max":6,"step":1}
DEW_SHED = 3


def _dew_glass_dew_mix(a, b, k):
    if k < 0.0:
        k = 0.0
    if k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _dew_glass_dew_back(y, h):
    """The backdrop colour a drop at row y is refracting."""
    return _dew_glass_dew_mix(DEW_TOP, DEW_BOTTOM, (y / max(1, h - 1)) ** 1.25)


def _dew_glass_dew_dot(buf, x, y, r):
    """A disc. circle() at radius 1 rasterises as a five-pixel plus, and a field
    of those reads as sparkles, not as water — so a small dot is a square."""
    if r < 2:
        buf.rectangle(x, y, 1, 1)
    else:
        buf.circle(x, y, r)


def _dew_glass_dew_drop(buf, x, y, r, h, s):
    """One bead. A drop on glass is mostly BRIGHTER than what is behind it —
    an earlier pass gave it a dark rim and a white core and every drop read as
    a rivet. So: a soft cast shadow, a body only a shade deeper than the
    backdrop, light pooling low and right, and one hard clipped highlight."""
    back = _dew_glass_dew_back(y, h)
    off = max(1, r // 3)
    buf.pen = color.rgb(DEW_RIM[0], DEW_RIM[1], DEW_RIM[2], 70)
    buf.circle(x + off, y + off, r)
    body = _dew_glass_dew_mix(back, DEW_RIM, 0.26)
    buf.pen = color.rgb(body[0], body[1], body[2])
    buf.circle(x, y, r)
    # the lit disc all but fills the bead, leaving the darker body as a thin
    # crescent up-left; drawn any smaller it reads as a soap bubble's outline
    lit = _dew_glass_dew_mix(back, (255, 255, 255), 0.52)
    buf.pen = color.rgb(lit[0], lit[1], lit[2])
    buf.circle(x + max(1, r // 5), y + max(1, r // 5), max(2, r - max(1, r // 5)))
    buf.pen = color.rgb(*DEW_SPEC)
    _dew_glass_dew_dot(buf, x - max(1, r // 3), y - max(1, r // 3), max(1, r // 3))


def _dew_glass_dew_bead(buf, x, y, r, h):
    """A small bead. Below two pixels it is one lit speck and nothing else —
    a body plus a highlight at that size is just a white pixel twice."""
    back = _dew_glass_dew_back(y, h)
    if r < 2:
        lit = _dew_glass_dew_mix(back, (255, 255, 255), 0.72)
        buf.pen = color.rgb(lit[0], lit[1], lit[2])
        buf.rectangle(x, y, max(1, r), max(1, r))
        return
    body = _dew_glass_dew_mix(back, (255, 255, 255), 0.34)
    buf.pen = color.rgb(body[0], body[1], body[2])
    buf.circle(x, y, r)
    buf.pen = color.rgb(*DEW_SPEC)
    buf.rectangle(x - r // 2, y - r // 2, max(1, r // 2), max(1, r // 2))


def _dew_glass_dew_runner_x(i, w):
    return int(w * (0.20 + 0.46 * ((i * 3) % 2))) + (i * 7) % max(1, w // 8)


def _dew_glass(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, u // 4)   # the catalogue's stroke unit: 1 logical px at LORES, 2 at HIRES

    # the backdrop: sky over meadow, one filled row per line
    for y in range(h):
        c = _dew_glass_dew_back(y, h)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(0, y, w, 1)

    # a few soft lights to give the defocus something to smear
    for i in range(DEW_BOKEH):
        y = (i * 89) % h
        c = _dew_glass_dew_mix(_dew_glass_dew_back(y, h), (255, 255, 255), 0.55)
        buf.pen = color.rgb(c[0], c[1], c[2], 140)
        buf.circle((i * 137) % w, y, max(2, int(h * 0.12)))

    if DEW_BLUR:
        buf.blur(1)

    # fine beading first, so the bigger drops sit on top of it
    for i in range(DEW_FINE):
        y = (i * 61) % h
        _dew_glass_dew_bead(buf, (i * 131) % w, y, max(1, int(u * 0.5 * DEW_SIZE)), h)

    for i in range(DEW_MID):
        y = int(h * (0.06 + 0.093 * ((i * 5) % 10))) + (i * 3) % max(1, u)
        x = int(w * (0.05 + 0.104 * ((i * 7) % 9))) + (i * 11) % max(1, u)
        _dew_glass_dew_bead(buf, x, y, max(2, int(h * 0.05 * DEW_SIZE)), h)

    # hero drops: big enough to stay legible in a picker cell
    hero_r = max(3, int(h * 0.13 * DEW_SIZE))
    for i in range(DEW_HERO):
        x = int(w * (0.13 + 0.185 * ((i * 3) % 5))) + ((i * 29) % max(1, u * 2))
        y = int(h * (0.13 + 0.155 * ((i * 2) % 5)))
        _dew_glass_dew_drop(buf, x, y, max(3, hero_r - (i % 2) * (hero_r // 4)), h, s)


def _dew_glass_a(buf, t):
    """Water on glass does not sit still; it BREAKS and runs.

    Three beads run the pane, each dragging a wet track and shedding smaller
    droplets in its wake, the beading twinkles as the light behind moves, and
    the hero drops flare. The runs are the only broad marks that cross the
    name band, and a bead running down a pane is exactly the slow travel that
    band tolerates.

    The twinkles land on the SAME `(i * 131) % w, (i * 61) % h` scatter the
    background beaded with, so a light comes up in a drop that is already
    there instead of appearing in bare glass."""
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, u // 4)   # the catalogue's stroke unit: 1 logical px at LORES, 2 at HIRES

    # the beading catches the light as the defocused backdrop shifts
    for j in range(DEW_TWINKLE):
        i = j * 3
        y = (i * 61) % h
        p = ((t * DEW_TWINKLE_RATE + j * 0.17) % 1.0)
        buf.pen = color.rgb(255, 255, 255, int(215 * math.sin(math.pi * p)))
        buf.rectangle((i * 131) % w, y, max(1, s * 2), max(1, s * 2))

    # a bead breaks and runs down the pane, dragging a wet track behind it
    r = max(3, int(h * 0.085 * DEW_SIZE))
    for i in range(DEW_RUNS):
        phase = (t * DEW_RUN_SPEED * (1 + i % 2) + i * 0.41) % 1.0
        x = _dew_glass_dew_runner_x(i, w)
        y = int(h * phase)
        track = _dew_glass_dew_mix(_dew_glass_dew_back(y, h), (255, 255, 255), 0.30)
        buf.pen = color.rgb(track[0], track[1], track[2], 170)
        buf.rectangle(x - max(1, s), max(0, y - int(h * 0.22)), max(1, s * 2), int(h * 0.22))
        _dew_glass_dew_drop(buf, x, y, r, h, s)

    # what the run leaves behind: smaller beads stranded on the wet track
    for j in range(DEW_SHED):
        i = j % max(1, DEW_RUNS)
        phase = (t * DEW_RUN_SPEED * (1 + i % 2) + i * 0.41) % 1.0
        x = _dew_glass_dew_runner_x(i, w)
        y = int(h * phase) - int(h * (0.06 + 0.05 * (j // max(1, DEW_RUNS))))
        if y < 0:
            y += h
        _dew_glass_dew_bead(buf, x + ((j * 7) % 3) - 1, y, max(2, r // 3), h)

    # three highlights catch the light and flare
    for i in range(3):
        p = 0.5 + 0.5 * math.sin((t * 2 + i * 0.37) * 2 * math.pi)
        x = int(w * (0.13 + 0.185 * ((i * 6) % 5)))
        y = int(h * (0.13 + 0.155 * ((i * 4) % 5)))
        buf.pen = color.rgb(255, 255, 255, 60 + int(190 * p))
        buf.circle(x - max(1, u), y - max(1, u), max(2, int(u * (0.5 + p))))

# ── PALM GLOSS ───────────────────────────────────────────
# PALM GLOSS - a macro tangle of waxy tropical leaves against a blown-out sky, wet sheen running down each blade, one frond swaying in front.

# @skinlab {"type":"color","label":"Sky (top)","group":"Palette"}
LEAF_SKY = (238, 252, 255)


# @skinlab {"type":"color","label":"Sky (low)","group":"Palette"}
LEAF_HAZE = (170, 230, 196)


# @skinlab {"type":"color","label":"Leaf (back)","group":"Palette"}
LEAF_DEEP = (10, 66, 44)


# @skinlab {"type":"color","label":"Leaf (mid)","group":"Palette"}
LEAF_MID = (22, 104, 50)


# @skinlab {"type":"color","label":"Leaf (front)","group":"Palette"}
LEAF_LIME = (72, 158, 52)


# @skinlab {"type":"color","label":"Wet sheen","group":"Palette"}
LEAF_RIM = (206, 250, 150)


# @skinlab {"type":"integer","label":"Leaves","group":"Layout","min":4,"max":14,"step":1}
LEAF_BLADES = 9


# @skinlab {"type":"number","label":"Leaf length","group":"Shape","min":0.5,"max":1.4,"step":0.05}
LEAF_LENGTH = 1.15


# @skinlab {"type":"number","label":"Leaf width","group":"Shape","min":0.1,"max":0.4,"step":0.02}
LEAF_WIDTH = 0.32


# @skinlab {"type":"number","label":"Leaf curve","group":"Shape","min":0.0,"max":0.5,"step":0.02}
LEAF_CURVE = 0.28


# @skinlab {"type":"number","label":"Fan spread","group":"Layout","min":0.2,"max":1.3,"step":0.05}
LEAF_FAN = 0.70


# @skinlab {"type":"integer","label":"Dappled light","group":"Layout","min":0,"max":12,"step":1}
LEAF_DAPPLE = 6


# @skinlab {"type":"number","label":"Sway","group":"Motion","min":0.0,"max":0.24,"step":0.01}
LEAF_SWAY = 0.13


# @skinlab {"type":"number","label":"Breeze speed","group":"Motion","min":0.25,"max":3,"step":0.25}
LEAF_BREEZE = 1.0


# @skinlab {"type":"boolean","label":"Second frond","group":"Motion"}
LEAF_SECOND = True


# @skinlab {"type":"integer","label":"Moving dapples","group":"Motion","min":0,"max":8,"step":1}
LEAF_DAPPLE_MOVE = 5


def _palm_gloss_palm_mix(a, b, k):
    if k < 0.0:
        k = 0.0
    if k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _palm_gloss_palm_stroke(buf, x1, y1, x2, y2, weight):
    """line() is always one pixel, so a midrib whose WIDTH carries the idea is
    laid side by side along whichever axis it is shallower in."""
    if weight <= 1:
        buf.line(x1, y1, x2, y2)
        return
    steep = abs(y2 - y1) > abs(x2 - x1)
    for i in range(weight):
        if steep:
            buf.line(x1 + i, y1, x2 + i, y2)
        else:
            buf.line(x1, y1 + i, x2, y2 + i)


def _palm_gloss_palm_spine(bx, by, ang, length, curve, seg):
    """Sample a gently bowed leaf axis. A straight lens reads as a spearhead;
    the bow is what makes it read as a leaf."""
    ca, sa = math.cos(ang), math.sin(ang)
    pts = []
    for k in range(seg + 1):
        f = k / seg
        d = length * f
        off = length * curve * f * f
        pts.append((bx + d * ca - sa * off, by + d * sa + ca * off))
    return pts


def _palm_gloss_palm_edges(pts, halfw, seg, lo, hi):
    """Two offset edges either side of the axis, tapering to nothing at both
    ends. The 1.35 exponent puts the widest point ABOVE centre and leaves a
    blunt base and a sharp tip - a leaf, and it also parks the fat part of
    every blade in the band the wearer's name occupies, which keeps that band
    one value instead of half sky and half leaf. `lo`/`hi` select a band of
    the half-width, so the same routine draws the whole blade or just the
    sheen stripe down its lit side."""
    left, right = [], []
    for i in range(seg + 1):
        x, y = pts[i]
        x0, y0 = pts[max(0, i - 1)]
        x1, y1 = pts[min(seg, i + 1)]
        dx, dy = x1 - x0, y1 - y0
        m = math.sqrt(dx * dx + dy * dy)
        if m < 0.001:
            m = 1.0
        px, py = -dy / m, dx / m
        hw = halfw * math.sin(math.pi * ((i / seg) ** 1.35))
        left.append((int(x + px * hw * hi), int(y + py * hw * hi)))
        right.append((int(x + px * hw * lo), int(y + py * hw * lo)))
    return left, right


def _palm_gloss_palm_strip(buf, left, right, seg):
    for i in range(seg):
        buf.triangle(left[i][0], left[i][1], right[i][0], right[i][1],
                     left[i + 1][0], left[i + 1][1])
        buf.triangle(right[i][0], right[i][1], right[i + 1][0], right[i + 1][1],
                     left[i + 1][0], left[i + 1][1])


def _palm_gloss_palm_leaf(buf, bx, by, ang, length, halfw, curve, body, s, seg, sheen, rib):
    pts = _palm_gloss_palm_spine(bx, by, ang, length, curve, seg)
    left, right = _palm_gloss_palm_edges(pts, halfw, seg, -1.0, 1.0)
    buf.pen = color.rgb(*body)
    _palm_gloss_palm_strip(buf, left, right, seg)

    if sheen:
        # the waxy highlight is a NARROWER copy of the leaf hugging its lit
        # edge, so it follows the silhouette instead of sitting on it as a patch
        a, b = _palm_gloss_palm_edges(pts, halfw, seg, 0.30, 0.72)
        tint = _palm_gloss_palm_mix(body, LEAF_RIM, 0.44)
        buf.pen = color.rgb(tint[0], tint[1], tint[2])
        _palm_gloss_palm_strip(buf, a, b, seg)

    if rib:
        tint = _palm_gloss_palm_mix(body, LEAF_RIM, 0.40)
        buf.pen = color.rgb(tint[0], tint[1], tint[2])
        for i in range(seg):
            _palm_gloss_palm_stroke(buf, int(pts[i][0]), int(pts[i][1]),
                         int(pts[i + 1][0]), int(pts[i + 1][1]), s)


def _palm_gloss_palm_place(i, count, w, h):
    """Base, angle, length and bow for leaf i. The bow alternates sign so the
    fan does not line up into a ridge of matching spikes."""
    f = (i + 0.5) / max(1, count)
    bx = int(w * (f * 1.5 - 0.25))
    by = int(h * (1.02 + ((i * 7) % 4) * 0.05))
    ang = -math.pi / 2 + LEAF_FAN * (f - 0.5) * 2.0 + (((i * 13) % 5) - 2) * 0.07
    length = h * LEAF_LENGTH * (0.80 + ((i * 11) % 5) * 0.08)
    curve = LEAF_CURVE * (1 if i % 2 else -1) * (0.6 + ((i * 5) % 3) * 0.2)
    return bx, by, ang, length, curve


def _palm_gloss(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, u // 4)   # the catalogue's stroke unit: 1 logical px at LORES, 2 at HIRES

    # blown-out sky behind the canopy, one filled row per line. Every leaf is
    # darker than every part of it, so the silhouettes survive a picker cell.
    for y in range(h):
        c = _palm_gloss_palm_mix(LEAF_SKY, LEAF_HAZE, (y / max(1, h - 1)) ** 0.85)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(0, y, w, 1)

    # sun coming through the gaps
    for i in range(LEAF_DAPPLE):
        buf.pen = color.rgb(255, 255, 240, 60 + (i * 31) % 60)
        buf.circle((i * 137) % w, (i * 71) % max(1, int(h * 0.5)),
                   max(2, u + ((i * 5) % 3) * u // 2))

    count = LEAF_BLADES
    back = max(1, count // 3)
    mid = max(1, count // 3)
    hazed = _palm_gloss_palm_mix(LEAF_DEEP, LEAF_HAZE, 0.18)
    for i in range(count):
        bx, by, ang, length, curve = _palm_gloss_palm_place(i, count, w, h)
        if i < back:
            body, seg, sheen, rib, scale = hazed, 4, False, False, 0.86
        elif i < back + mid:
            body, seg, sheen, rib, scale = LEAF_MID, 5, False, True, 0.95
        else:
            body, seg, sheen, rib, scale = LEAF_LIME, 5, True, True, 1.0
        _palm_gloss_palm_leaf(buf, bx, by, ang, length * scale,
                   length * scale * LEAF_WIDTH, curve, body, s, seg, sheen, rib)


def _palm_gloss_a(buf, t):
    """The breeze moves the CANOPY, not one blade of it.

    Two fronds lean in front of the still tangle, out of phase with each other
    so the frame flexes rather than sliding, and the dapples between them
    shift with the same swing. The pair is the whole budget this skin can
    afford: a leaf is a triangle strip, and the front frond alone is twenty of
    the forty calls at HIRES because its midrib is drawn at stroke width."""
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, u // 4)   # the catalogue's stroke unit: 1 logical px at LORES, 2 at HIRES

    # one frond in front of everything, leaning on the breeze. It lives only
    # here, so nothing is drawn twice and it is free to move.
    swing = LEAF_SWAY * math.sin(t * 2 * math.pi * LEAF_BREEZE)
    length = h * LEAF_LENGTH * 0.98
    lit = _palm_gloss_palm_mix(LEAF_LIME, LEAF_RIM, 0.14)
    _palm_gloss_palm_leaf(buf, int(-w * 0.10), int(h * 1.14), -math.pi / 2 + 0.70 + swing,
               length, length * LEAF_WIDTH * 1.15, LEAF_CURVE * 0.9,
               lit, s, 4, True, True)

    # a shorter blade off the other edge, swinging against it. No sheen and no
    # midrib: it is the counterweight, not a second hero.
    if LEAF_SECOND:
        back = _palm_gloss_palm_mix(LEAF_LIME, LEAF_DEEP, 0.30)
        short = h * LEAF_LENGTH * 0.62
        _palm_gloss_palm_leaf(buf, int(w * 1.08), int(h * 1.10),
                   -math.pi / 2 - 0.62 - swing * 0.8, short,
                   short * LEAF_WIDTH * 1.05, -LEAF_CURVE * 0.8,
                   back, s, 3, False, False)

    # dappled light shifting as the canopy moves
    for i in range(LEAF_DAPPLE_MOVE):
        p = 0.5 + 0.5 * math.sin((t * LEAF_BREEZE + i * 0.29) * 2 * math.pi)
        buf.pen = color.rgb(255, 255, 240, 40 + int(90 * p))
        buf.circle((i * 137) % w + int(u * swing * 8),
                   (i * 71) % max(1, int(h * 0.4)),
                   max(2, u // 2 + int(u * p)))

# ── REEF TANK ───────────────────────────────────────────
# REEF TANK - a sunlit tropical tank: a caustic net rippling under the surface, striped fish over pale sand, bubbles climbing the glass.

# @skinlab {"type":"color","label":"Water (surface)","group":"Palette"}
REEF_WATER_TOP = (152, 244, 252)


# @skinlab {"type":"color","label":"Water (deep)","group":"Palette"}
REEF_WATER_DEEP = (14, 118, 176)


# @skinlab {"type":"color","label":"Sand","group":"Palette"}
REEF_SAND = (244, 232, 186)


# @skinlab {"type":"color","label":"Fish A","group":"Palette"}
REEF_FISH_A = (255, 132, 32)


# @skinlab {"type":"color","label":"Fish B","group":"Palette"}
REEF_FISH_B = (255, 216, 56)


# @skinlab {"type":"color","label":"Weed","group":"Palette"}
REEF_WEED = (44, 172, 110)


# @skinlab {"type":"integer","label":"Caustic bands","group":"Layout","min":0,"max":6,"step":1}
REEF_CAUSTIC = 3


# @skinlab {"type":"integer","label":"Fish","group":"Layout","min":0,"max":8,"step":1}
REEF_FISH = 5


# @skinlab {"type":"number","label":"Fish size","group":"Shape","min":0.6,"max":1.8,"step":0.1}
REEF_FISH_SIZE = 1.0


# @skinlab {"type":"integer","label":"Weed fronds","group":"Layout","min":0,"max":10,"step":1}
REEF_FRONDS = 6


# @skinlab {"type":"integer","label":"Bubbles","group":"Motion","min":0,"max":16,"step":1}
REEF_BUBBLES = 10


# The lap count has to be a WHOLE number or the column of bubbles jumps once
# every four seconds when t wraps; 0.6 put a 60%-of-screen leap in it.
# @skinlab {"type":"number","label":"Bubble speed","group":"Motion","min":1,"max":4,"step":1}
REEF_BUBBLE_SPEED = 1.0


# @skinlab {"type":"integer","label":"Caustic ripples","group":"Motion","min":0,"max":12,"step":1}
REEF_RIPPLE = 8


# @skinlab {"type":"number","label":"Ripple speed","group":"Motion","min":1,"max":4,"step":1}
REEF_RIPPLE_SPEED = 1.0


# @skinlab {"type":"boolean","label":"Swimmer","group":"Motion"}
REEF_SWIMMER = True


def _reef_tank_reef_mix(a, b, k):
    if k < 0.0:
        k = 0.0
    if k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _reef_tank_reef_fish_shape(buf, x, y, r, body, fin, face):
    """One fish: tail, dorsal, round body, snout, a bold stripe and an eye."""
    buf.pen = color.rgb(fin[0], fin[1], fin[2])
    buf.triangle(x - face * r * 2, y - r, x - face * r * 2, y + r, x - face * (r // 2), y)
    buf.triangle(x, y - r, x - face * r, y - r * 2, x + face * (r // 2), y - r)
    buf.pen = color.rgb(body[0], body[1], body[2])
    buf.circle(x, y, r)
    buf.triangle(x, y - r, x, y + r, x + face * int(r * 1.7), y)
    buf.pen = color.rgb(255, 255, 255)
    buf.rectangle(x - max(1, r // 4), y - r, max(1, r // 2), r * 2)
    buf.pen = color.rgb(16, 34, 48)
    buf.rectangle(x + face * (r // 2), y - max(1, r // 3), max(1, r // 3), max(1, r // 3))


def _reef_tank(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, u // 4)   # the catalogue's stroke unit: 1 logical px at LORES, 2 at HIRES

    # the water column, one filled row per line
    for y in range(h):
        c = _reef_tank_reef_mix(REEF_WATER_TOP, REEF_WATER_DEEP, (y / max(1, h - 1)) ** 0.85)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(0, y, w, 1)

    # the surface, seen from below: a bright lid with scalloped ripples
    buf.pen = color.rgb(255, 255, 255, 190)
    buf.rectangle(0, 0, w, max(1, s * 2))
    step = max(1, w // 32)
    buf.pen = color.rgb(236, 255, 255, 150)
    for j in range(0, w, step * 2):
        buf.circle(j, 0, max(2, u))

    # the caustic net: fine bright ripples, kept high where the name is not
    for k in range(REEF_CAUSTIC):
        base = int(h * (0.07 + 0.055 * k))
        amp = h * 0.028
        buf.pen = color.rgb(228, 255, 255, 165 - k * 30)
        for j in range(0, w, step):
            a = (j / max(1, w)) * 2.0 * math.pi
            y = base + int(amp * math.sin(a * 3.0 + k * 1.9))
            buf.rectangle(j, y, step, max(1, s))

    # sand bed
    sand_y = int(h * 0.86)
    buf.pen = color.rgb(*REEF_SAND)
    buf.rectangle(0, sand_y, w, h - sand_y)
    shade = _reef_tank_reef_mix(REEF_SAND, REEF_WATER_DEEP, 0.35)
    buf.pen = color.rgb(shade[0], shade[1], shade[2])
    for i in range(7):
        buf.circle((i * 137) % w, sand_y + (i * 5) % max(1, h - sand_y), max(2, u))

    # weed fronds leaning off the bed
    for i in range(REEF_FRONDS):
        x = int(w * (0.05 + 0.16 * i)) % max(1, w)
        lean = u * 3 if i % 2 else -u * 3
        tip = int(h * (0.52 + 0.07 * (i % 3)))
        tint = _reef_tank_reef_mix(REEF_WEED, (255, 255, 255), 0.12 * (i % 3))
        buf.pen = color.rgb(tint[0], tint[1], tint[2])
        buf.triangle(x - u, h, x + u, h, x + lean, tip)

    # the fish, low in the tank so the name band stays open water
    r = max(2, int(h * 0.085 * REEF_FISH_SIZE))
    for i in range(REEF_FISH):
        if i == 0:
            fx, fy, fr, face = int(w * 0.34), int(h * 0.72), int(r * 1.55), 1
        else:
            fx = int(w * (0.14 + 0.21 * ((i * 3) % 4)))
            fy = int(h * (0.64 + 0.09 * (i % 3)))
            fr = max(2, r - (i % 2) * (r // 3))
            face = 1 if i % 2 else -1
        body = REEF_FISH_A if i % 2 == 0 else REEF_FISH_B
        fin = _reef_tank_reef_mix(body, (255, 255, 255), 0.45)
        _reef_tank_reef_fish_shape(buf, fx, fy, max(2, fr), body, fin, face)


def _reef_tank_a(buf, t):
    """The skin's own description says "a caustic net RIPPLING under the
    surface" and until now the net was painted on. It ripples here.

    Bright segments run along the same three scalloped bands `render` laid
    down, at the same amplitude and phase, so the light travels through the
    net instead of a second net sliding over the first. They sit between 0.07h
    and 0.20h, above the name band, which is where the caustics already were."""
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, u // 4)   # the catalogue's stroke unit: 1 logical px at LORES, 2 at HIRES
    step = max(1, w // 32)

    for i in range(REEF_RIPPLE):
        f = (i / max(1, REEF_RIPPLE) + t * REEF_RIPPLE_SPEED) % 1.0
        k = i % max(1, REEF_CAUSTIC)
        base = int(h * (0.07 + 0.055 * k))
        a = f * 2.0 * math.pi
        y = base + int(h * 0.028 * math.sin(a * 3.0 + k * 1.9))
        buf.pen = color.rgb(255, 255, 255, 90 + int(140 * abs(math.sin(a * 1.5))))
        buf.rectangle(int(f * w), y, step * 2, max(1, s * 2))

    # bubbles climb, wobbling; the wobble is a whole number of cycles per lap.
    # radius 2 is the floor: circle() draws a plus below that, and a screenful
    # of pluses reads as sparkle rather than as air
    for i in range(REEF_BUBBLES):
        phase = (t * REEF_BUBBLE_SPEED + i * 0.13) % 1.0
        r = max(2, u // 2 + (i % 3) * u // 3)
        x = (i * 137) % w + int(u * math.sin((phase + i * 0.19) * 4 * math.pi))
        y = int(h * (1.0 - phase))
        buf.pen = color.rgb(224, 255, 255, 150)
        buf.circle(x, y, r)
        buf.pen = color.rgb(255, 255, 255, 240)
        buf.rectangle(x - max(1, r // 2), y - max(1, r // 2), max(1, s), max(1, s))

    # one fish crosses the top of the tank, in and out of frame
    if REEF_SWIMMER:
        r = max(2, int(h * 0.07 * REEF_FISH_SIZE))
        x = int(-r * 4 + (w + r * 8) * t)
        y = int(h * 0.20 + u * math.sin(t * 4 * math.pi))
        fin = _reef_tank_reef_mix(REEF_FISH_B, (255, 255, 255), 0.45)
        _reef_tank_reef_fish_shape(buf, x, y, r, REEF_FISH_B, fin, 1)

# ── FROSTED STACK ───────────────────────────────────────────
# Three frosted cards fanned back into the dark over a magenta-and-cyan light.

# @skinlab {"type":"color","label":"Room","group":"Palette"}
STACK_ROOM = (9, 11, 24)


# @skinlab {"type":"color","label":"Light A","group":"Palette"}
STACK_LIGHT_A = (238, 54, 176)


# @skinlab {"type":"color","label":"Light B","group":"Palette"}
STACK_LIGHT_B = (36, 186, 255)


# @skinlab {"type":"color","label":"Glass tint","group":"Palette"}
STACK_GLASS = (206, 228, 255)


# @skinlab {"type":"color","label":"Specular","group":"Palette"}
STACK_SPECULAR = (255, 255, 255)


# @skinlab {"type":"color","label":"Keyline","group":"Palette"}
STACK_KEYLINE = (2, 3, 10)


# @skinlab {"type":"integer","label":"Panes","group":"Layout","min":1,"max":5,"step":1}
STACK_PANES = 3


# @skinlab {"type":"number","label":"Depth offset","group":"Layout","min":0.02,"max":0.16,"step":0.01}
STACK_DEPTH = 0.075


# @skinlab {"type":"number","label":"Corner radius","group":"Shape","min":0.0,"max":0.5,"step":0.02}
STACK_CORNER = 0.30


# @skinlab {"type":"integer","label":"Frost blur","group":"Look","min":0,"max":10,"step":1}
STACK_FROST = 6


# @skinlab {"type":"number","label":"Frosting","group":"Look","min":0.0,"max":0.8,"step":0.05}
STACK_MILK = 0.26


# @skinlab {"type":"number","label":"Refraction step","group":"Look","min":0.0,"max":0.20,"step":0.01}
STACK_REFRACT = 0.10


# @skinlab {"type":"integer","label":"Glint cycles","group":"Motion","min":1,"max":4,"step":1}
STACK_GLINT_SPEED = 1


# @skinlab {"type":"number","label":"Sheen strength","group":"Motion","min":0.0,"max":1.0,"step":0.05}
STACK_SHEEN = 0.55


# @skinlab {"type":"integer","label":"Dust motes","group":"Layout","min":0,"max":10,"step":1}
STACK_MOTES = 8


# @skinlab {"type":"integer","label":"Mote drift","group":"Motion","min":0,"max":3,"step":1}
STACK_MOTE_DRIFT = 1


# @skinlab {"type":"number","label":"Refraction drift","group":"Motion","min":0.0,"max":3.0,"step":0.25}
STACK_BAND_SPEED = 1.0


def _frosted_stack_u(buf):
    return max(1, buf.width // 40)


def _frosted_stack_s(buf):
    """The house stroke: a quarter of a unit, so 1 px at LORES and 2 at HIRES."""
    return max(1, _frosted_stack_u(buf) // 4)


def _frosted_stack_mix(a, b, k):
    if k < 0.0:
        k = 0.0
    if k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _frosted_stack_field(x, y, w, h):
    """The light behind the glass: room black plus two soft saturated blobs.

    An analytic stand-in for what blur() leaves on the canvas, so a pane can
    resample it from a displaced position and read as refraction.
    """
    reach = max(1.0, min(w, h) * 1.05)
    ax, ay = w * 0.24, h * 0.14
    bx, by = w * 0.78, h * 0.92
    da = math.sqrt((x - ax) * (x - ax) + (y - ay) * (y - ay))
    db = math.sqrt((x - bx) * (x - bx) + (y - by) * (y - by))
    ka = max(0.0, 1.0 - da / reach)
    kb = max(0.0, 1.0 - db / reach)
    ka = ka * ka * 1.2
    kb = kb * kb * 1.2
    return (int(STACK_ROOM[0] + (STACK_LIGHT_A[0] - STACK_ROOM[0]) * ka
                + (STACK_LIGHT_B[0] - STACK_ROOM[0]) * kb),
            int(STACK_ROOM[1] + (STACK_LIGHT_A[1] - STACK_ROOM[1]) * ka
                + (STACK_LIGHT_B[1] - STACK_ROOM[1]) * kb),
            int(STACK_ROOM[2] + (STACK_LIGHT_A[2] - STACK_ROOM[2]) * ka
                + (STACK_LIGHT_B[2] - STACK_ROOM[2]) * kb))


def _frosted_stack_pane(buf, k):
    """Pane k: 0 is the deepest card, STACK_PANES - 1 the front one."""
    w, h = buf.width, buf.height
    n = max(1, STACK_PANES)
    d = max(1, int(min(w, h) * STACK_DEPTH))
    pw = int(w * 0.66)
    ph = int(h * 0.42)
    back = n - 1 - k
    x = int(w * 0.06) + d * back * 2
    y = int(h * 0.28) - d * back
    r = max(1, int(min(pw, ph) * STACK_CORNER * 0.5))
    return x, y, pw, ph, r


def _frosted_stack(buf):
    w, h = buf.width, buf.height
    u, s = _frosted_stack_u(buf), _frosted_stack_s(buf)
    step = max(1, h // 96)
    n = max(1, STACK_PANES)
    shift = int(h * STACK_REFRACT)

    # The light source, drawn vividly and then frosted in one call. Everything
    # after the blur is crisp, which is the whole trick: soft light, hard edges.
    buf.pen = color.rgb(*STACK_ROOM)
    buf.clear()
    for y in range(0, h, step):
        buf.pen = color.rgb(*_frosted_stack_mix(STACK_ROOM, (20, 16, 48), y / max(1, h - 1)))
        buf.rectangle(0, y, w, step)
    buf.pen = color.rgb(*STACK_LIGHT_A)
    buf.circle(int(w * 0.24), int(h * 0.14), int(min(w, h) * 0.46))
    buf.pen = color.rgb(*STACK_LIGHT_B)
    buf.circle(int(w * 0.78), int(h * 0.92), int(min(w, h) * 0.48))
    buf.pen = color.rgb(*_frosted_stack_mix(STACK_LIGHT_A, STACK_LIGHT_B, 0.5))
    buf.circle(int(w * 0.54), int(h * 0.54), int(min(w, h) * 0.17))
    if STACK_FROST > 0:
        buf.blur(int(STACK_FROST))

    for k in range(n):
        x, y, pw, ph, r = _frosted_stack_pane(buf, k)
        front = k == n - 1

        # Shadow down and right, specular rim up and left. The rim is a full
        # rounded rect, but the pane's own body lands on top of it a moment
        # later and leaves exactly the two-pixel lip that reads as glass.
        # Two stroke pixels is a lip on a full-size card and a third of a
        # thumbnail's card, where three stacked rims turn the picture white.
        e = max(1, min(s * 2, pw // 14))
        buf.pen = color.rgb(*STACK_KEYLINE)
        buf.shape(shape.rounded_rectangle(x + e, y + e, pw, ph, r))
        buf.pen = color.rgb(*STACK_SPECULAR)
        buf.shape(shape.rounded_rectangle(x - e, y - e, pw, ph, r))

        # The body: the light resampled from `shift` rows lower and pulled
        # towards the glass tint, so the picture visibly steps at the edge.
        milk = STACK_MILK if front else STACK_MILK * 0.8
        mid = _frosted_stack_field(x + pw // 2, y + ph // 2 + shift, w, h)
        if not front:
            mid = _frosted_stack_mix(mid, STACK_KEYLINE, 0.10)
        buf.pen = color.rgb(*_frosted_stack_mix(mid, STACK_GLASS, milk))
        buf.shape(shape.rounded_rectangle(x, y, pw, ph, r))

        if front:
            for yy in range(y, y + ph, step):
                base = _frosted_stack_field(x + pw // 2, yy + shift, w, h)
                buf.pen = color.rgb(*_frosted_stack_mix(base, STACK_GLASS, milk))
                buf.rectangle(x + r, yy, pw - r * 2, step)

    # Inner bevel on the front card: light on the top lip, shade on the bottom.
    x, y, pw, ph, r = _frosted_stack_pane(buf, n - 1)
    buf.pen = color.rgb(STACK_SPECULAR[0], STACK_SPECULAR[1], STACK_SPECULAR[2], 150)
    buf.rectangle(x + r, y + s, pw - r * 2, s)
    buf.pen = color.rgb(STACK_KEYLINE[0], STACK_KEYLINE[1], STACK_KEYLINE[2], 170)
    buf.rectangle(x + r, y + ph - s * 2, pw - r * 2, s)


def _frosted_stack_a(buf, t):
    """The LIGHT moves, not the glass.

    render() froze one lamp position into the panes; the only honest way to
    keep the picture still glass and still alive is to move what the lamp is
    doing to the edges — the rim it catches, the band it drives down the face,
    the lip it lights on the way past. Every pane takes the sweep a beat later
    than the one in front, so the stack reads as three sheets in front of ONE
    source rather than three lamps blinking.
    """
    w, h = buf.width, buf.height
    u, s = _frosted_stack_u(buf), _frosted_stack_s(buf)
    n = max(1, STACK_PANES)
    p = 0.5 - 0.5 * math.cos(t * 2 * math.pi * STACK_GLINT_SPEED)
    lit = min(n, 3)               # the front three; the rest are behind them

    for k in range(lit):
        x, y, pw, ph, r = _frosted_stack_pane(buf, n - 1 - k)
        q = 0.5 - 0.5 * math.cos((t * STACK_GLINT_SPEED - k * 0.13) * 2 * math.pi)
        gw = max(2, int(pw * (0.22 - 0.04 * k)))
        gx = x + r + int((pw - r * 2 - gw) * q)
        buf.pen = color.rgb(STACK_SPECULAR[0], STACK_SPECULAR[1], STACK_SPECULAR[2],
                            240 - k * 70)
        buf.rectangle(gx, y - s * 2, gw, s * 2)

        # The left lip only lights while the source is over on that side, which
        # is what tells you the lamp is BEHIND the glass and not painted on it.
        buf.pen = color.rgb(STACK_SPECULAR[0], STACK_SPECULAR[1], STACK_SPECULAR[2],
                            max(0, int(30 + 170 * (1.0 - q)) - k * 20))
        buf.rectangle(x - s, y + r, s, ph - r * 2)

        # Two refraction bands crossing the face in opposite directions: one
        # band alone is a shape sliding, two shearing past each other is glass.
        inner = max(1, ph - r * 2 - u)
        d = (t * STACK_BAND_SPEED + k * 0.21) % 1.0
        buf.pen = color.rgb(STACK_GLASS[0], STACK_GLASS[1], STACK_GLASS[2], 72 - k * 20)
        buf.rectangle(x + r, y + r + int(inner * d), pw - r * 2, max(1, u // 2))
        buf.pen = color.rgb(STACK_GLASS[0], STACK_GLASS[1], STACK_GLASS[2], 46 - k * 12)
        buf.rectangle(x + r, y + r + inner - int(inner * d), pw - r * 2, max(1, s * 2))

    # The front card gets the hot half of the glint and a caustic on its foot.
    x, y, pw, ph, r = _frosted_stack_pane(buf, n - 1)
    gw = max(2, int(pw * 0.22))
    gx = x + r + int((pw - r * 2 - gw) * p)
    buf.pen = color.rgb(STACK_SPECULAR[0], STACK_SPECULAR[1], STACK_SPECULAR[2], 110)
    buf.rectangle(gx - gw // 3, y - s * 2, gw + gw // 2, s * 2)
    buf.pen = color.rgb(*STACK_SPECULAR)
    buf.rectangle(gx + gw // 3, y + s, gw // 3, s)
    buf.pen = color.rgb(255, 246, 232, int(70 + 120 * (0.5 + 0.5 * math.sin(t * 2 * math.pi))))
    buf.rectangle(gx - gw // 2, y + ph - s * 2, gw * 2, s)

    # Motes in the beam. Their travel is a whole number of bands per loop, so
    # every speck lands back on its own start row at t = 1 and nothing snaps.
    # They live above and below the name band, never inside it.
    for i in range(max(0, STACK_MOTES)):
        top = i % 2 == 0
        y0 = int(h * (0.02 if top else 0.64))
        span = max(2, int(h * 0.20 if top else h * 0.32))
        my = y0 + ((i * 97) % span + int(t * span * STACK_MOTE_DRIFT)) % span
        buf.pen = color.rgb(255, 255, 255, 60 + (i * 41) % 110)
        buf.rectangle((i * 173) % w, my, s, s)

    # A thin sheen leans across the whole deck behind the glint.
    if STACK_SHEEN > 0.0:
        a = int(46 * STACK_SHEEN)
        sx = int(w * (p * 1.3 - 0.15))
        lean = int(h * 0.35)
        buf.pen = color.rgb(STACK_SPECULAR[0], STACK_SPECULAR[1], STACK_SPECULAR[2], a)
        buf.triangle(sx, 0, sx + u * 3, 0, sx - lean, h)
        buf.triangle(sx + u * 3, 0, sx - lean, h, sx - lean + u * 3, h)

# ── LOUVRE ───────────────────────────────────────────
# Frosted glass slats standing over a vivid light that walks along behind them.

# @skinlab {"type":"color","label":"Room","group":"Palette"}
LOUVRE_ROOM = (7, 9, 18)


# @skinlab {"type":"color","label":"Light A","group":"Palette"}
LOUVRE_GLOW_A = (255, 52, 116)


# @skinlab {"type":"color","label":"Light B","group":"Palette"}
LOUVRE_GLOW_B = (255, 182, 40)


# @skinlab {"type":"color","label":"Light C","group":"Palette"}
LOUVRE_GLOW_C = (48, 142, 255)


# @skinlab {"type":"color","label":"Glass tint","group":"Palette"}
LOUVRE_GLASS = (208, 234, 255)


# @skinlab {"type":"color","label":"Keyline","group":"Palette"}
LOUVRE_KEY = (2, 3, 9)


# @skinlab {"type":"integer","label":"Slats","group":"Layout","min":3,"max":12,"step":1}
LOUVRE_SLATS = 6


# @skinlab {"type":"number","label":"Gap","group":"Layout","min":0.10,"max":0.55,"step":0.02}
LOUVRE_GAP = 0.32


# @skinlab {"type":"number","label":"Corner radius","group":"Shape","min":0.0,"max":0.6,"step":0.05}
LOUVRE_CORNER = 0.30


# @skinlab {"type":"integer","label":"Frost blur","group":"Look","min":0,"max":12,"step":1}
LOUVRE_FROST = 7


# @skinlab {"type":"number","label":"Frosting","group":"Look","min":0.0,"max":0.8,"step":0.05}
LOUVRE_MILK = 0.20


# @skinlab {"type":"number","label":"Refraction step","group":"Look","min":0.0,"max":0.5,"step":0.02}
LOUVRE_REFRACT = 0.20


# @skinlab {"type":"integer","label":"Sweep cycles","group":"Motion","min":1,"max":4,"step":1}
LOUVRE_SWEEP = 1


# @skinlab {"type":"integer","label":"Live slats","group":"Layout","min":2,"max":8,"step":1}
LOUVRE_LIVE = 8


# @skinlab {"type":"number","label":"Ripple speed","group":"Motion","min":0.0,"max":3.0,"step":0.25}
LOUVRE_RIPPLE = 1.0


# @skinlab {"type":"integer","label":"Dust motes","group":"Layout","min":0,"max":8,"step":1}
LOUVRE_MOTES = 6


# @skinlab {"type":"integer","label":"Mote drift","group":"Motion","min":0,"max":3,"step":1}
LOUVRE_MOTE_DRIFT = 1


def _louvre_u(buf):
    return max(1, buf.width // 40)


def _louvre_s(buf):
    """The house stroke: a quarter of a unit, so 1 px at LORES and 2 at HIRES."""
    return max(1, _louvre_u(buf) // 4)


def _louvre_mix(a, b, k):
    if k < 0.0:
        k = 0.0
    if k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


LOUVRE_LAMPS = ((0.14, 0.30, 0), (0.50, 0.86, 1), (0.90, 0.34, 2))


# @skinlab {"type":"integer","label":"Glass bands","group":"Layout","min":6,"max":32,"step":1}
LOUVRE_GLASS_BANDS = 16


def _louvre_lamp_tint(i):
    return (LOUVRE_GLOW_A, LOUVRE_GLOW_B, LOUVRE_GLOW_C)[i]


def _louvre_glow(x, y, w, h):
    """Three saturated lamps in the room; the analytic twin of the blur.

    A slat is painted opaquely from this rather than washed over the canvas,
    because a big low-alpha fill would just grey the picture out. It has to
    track what blur() actually leaves behind: wide reach, gentle falloff.
    """
    reach = max(1.0, min(w, h) * 1.45)
    acc = [0.0, 0.0, 0.0]
    total = 0.0
    peak = 0.0
    for fx, fy, i in LOUVRE_LAMPS:
        tint = _louvre_lamp_tint(i)
        dx = x - w * fx
        dy = y - h * fy
        k = max(0.0, 1.0 - math.sqrt(dx * dx + dy * dy) / reach)
        k = k * k
        if k > peak:
            peak = k
        total += k
        acc[0] += tint[0] * k
        acc[1] += tint[1] * k
        acc[2] += tint[2] * k
    if total <= 0.0:
        return LOUVRE_ROOM
    # Hue from whichever lamps are nearest, brightness from how near they are.
    # Summing the three instead would put every channel at 255 and paint white.
    lit = (acc[0] / total, acc[1] / total, acc[2] / total)
    return _louvre_mix(LOUVRE_ROOM, lit, min(1.0, peak * 2.8))


def _louvre_slat(buf, i):
    w, h = buf.width, buf.height
    u = _louvre_u(buf)
    n = max(1, LOUVRE_SLATS)
    pitch = w / n
    sw = max(2, int(pitch * (1.0 - LOUVRE_GAP)))
    x = int(i * pitch + (pitch - sw) * 0.5)
    y = u
    sh = h - u * 2
    r = max(1, int(sw * LOUVRE_CORNER))
    return x, y, sw, sh, r


def _louvre(buf):
    w, h = buf.width, buf.height
    u, s = _louvre_u(buf), _louvre_s(buf)

    # Vivid light, then one call of frost. Everything after this is crisp.
    buf.pen = color.rgb(*LOUVRE_ROOM)
    buf.clear()
    for fx, fy, i in LOUVRE_LAMPS:
        buf.pen = color.rgb(*_louvre_lamp_tint(i))
        buf.circle(int(w * fx), int(h * fy), int(min(w, h) * 0.52))
    buf.pen = color.rgb(*_louvre_mix(LOUVRE_GLOW_A, LOUVRE_GLOW_C, 0.5))
    buf.circle(int(w * 0.50), int(h * 0.42), int(min(w, h) * 0.26))
    if LOUVRE_FROST > 0:
        buf.blur(int(LOUVRE_FROST))

    shift = int(w * LOUVRE_REFRACT)
    for i in range(max(1, LOUVRE_SLATS)):
        x, y, sw, sh, r = _louvre_slat(buf, i)
        sx = x + sw // 2 + shift
        # Two stroke pixels is a lip on a wide slat and half the slat in a
        # thumbnail, where it turns the picture white. Cap it at a fifth.
        e = max(1, min(s * 2, sw // 5))

        buf.pen = color.rgb(*LOUVRE_KEY)
        buf.shape(shape.rounded_rectangle(x + e, y + e, sw, sh, r))
        buf.pen = color.rgb(242, 250, 255)
        buf.shape(shape.rounded_rectangle(x - e, y - e, sw, sh, r))

        # The slat's contents: the light resampled from a position sideways of
        # where this slat actually is, so the picture jogs at every gap. That
        # jog is the refraction, and it costs nothing but an offset. The two
        # rounded caps are their own shapes in their own local colour, or they
        # come out as a pair of mismatched nubs at the ends of the gradient.
        buf.pen = color.rgb(*_louvre_mix(_louvre_glow(sx, y + r, w, h), LOUVRE_GLASS, LOUVRE_MILK))
        buf.shape(shape.rounded_rectangle(x, y, sw, r * 2, r))
        buf.pen = color.rgb(*_louvre_mix(_louvre_glow(sx, y + sh - r, w, h), LOUVRE_GLASS, LOUVRE_MILK))
        buf.shape(shape.rounded_rectangle(x, y + sh - r * 2, sw, r * 2, r))
        inner = max(1, sh - r * 2)
        for k in range(LOUVRE_GLASS_BANDS):
            j = y + r + inner * k // LOUVRE_GLASS_BANDS
            hh = max(1, y + r + inner * (k + 1) // LOUVRE_GLASS_BANDS - j)
            buf.pen = color.rgb(*_louvre_mix(_louvre_glow(sx, j + hh // 2, w, h),
                                      LOUVRE_GLASS, LOUVRE_MILK))
            buf.rectangle(x, j, sw, hh)

        # One broad sheen catching the surface, staggered slat to slat so they
        # never line up into rows of type, and the inner lip down the left face.
        gy = y + int(sh * (0.14 + 0.13 * ((i * 5) % 4)))
        buf.pen = color.rgb(255, 255, 255, 58)
        buf.rectangle(x + r, gy, sw - r * 2, max(2, sh // 7))
        buf.pen = color.rgb(255, 255, 255, 90)
        buf.rectangle(x + s, y + r, s, sh - r * 2)


def _louvre_a(buf, t):
    """The lamp walks behind the blind and the whole blind answers.

    The slats cannot move — they are in the saved background — so what moves is
    everything the light does to them: the edge each one takes as the source
    passes, a sheen rippling down the faces one slat behind the last, and the
    two GAPS either side of the lamp, which are the only places the source is
    not behind frosted glass and are therefore the brightest marks on screen.
    """
    w, h = buf.width, buf.height
    u, s = _louvre_u(buf), _louvre_s(buf)
    n = max(1, LOUVRE_SLATS)
    live = min(n, max(2, LOUVRE_LIVE))

    lx = w * (0.5 - 0.46 * math.cos(t * 2 * math.pi * LOUVRE_SWEEP))
    reach = w * 0.34
    hot = -1
    best = reach
    for i in range(live):
        x, y, sw, sh, r = _louvre_slat(buf, i)
        d = abs(x + sw * 0.5 - lx)
        if d < best:
            best, hot = d, i
        e = max(1, min(s * 2, sw // 5))
        if d < reach:
            buf.pen = color.rgb(255, 255, 255, int(230 * (1.0 - d / reach)))
            buf.rectangle(x - e, y + r, e, sh - r * 2)
        inner = max(1, sh - r * 2 - u)
        q = (t * LOUVRE_RIPPLE + i * 0.17) % 1.0
        buf.pen = color.rgb(255, 255, 255,
                            28 + int(64 * max(0.0, 1.0 - d / max(1.0, reach))))
        buf.rectangle(x + s, y + r + int(inner * q), max(1, sw - s * 2),
                      max(2, sh // 16))

    # The light spilling through the two gaps flanking the lamp.
    pitch = w / n
    for g in (0, 1):
        gi = int(lx / pitch) - 1 + g * 2
        if gi < 0 or gi >= n:
            continue
        x, y, sw, sh, r = _louvre_slat(buf, gi)
        d = abs(x + sw * 0.5 - lx)
        buf.pen = color.rgb(255, 250, 236,
                            int(170 * max(0.0, 1.0 - d / max(1.0, pitch * 2.0))))
        buf.rectangle(x + sw, y + r, max(1, int(pitch - sw)), sh - r * 2)

    # One hard glint slides down the slat the light is behind, and a bloom
    # bleeds off its lit edge.
    if hot >= 0:
        x, y, sw, sh, r = _louvre_slat(buf, hot)
        gy = y + int(sh * (0.26 + 0.40 * (0.5 + 0.5 * math.sin(t * 2 * math.pi))))
        e = max(1, min(s * 2, sw // 5))
        buf.pen = color.rgb(255, 255, 255)
        buf.rectangle(x - e, gy, e, max(2, int(sh * 0.12)))
        buf.pen = color.rgb(255, 255, 255, 130)
        buf.rectangle(x + s, gy + u, s, max(2, int(sh * 0.07)))
        buf.pen = color.rgb(255, 246, 224, 90)
        buf.rectangle(x - e * 3, gy - u, e * 2, max(3, int(sh * 0.18)))

    # Motes in the beam, kept to the two bands the wearer's name never uses.
    # Their travel is a whole number of band heights per loop, so each speck is
    # back on its own start row at t = 1.
    for i in range(max(0, LOUVRE_MOTES)):
        top = i % 2 == 0
        y0 = int(h * (0.03 if top else 0.65))
        span = max(2, int(h * (0.18 if top else 0.30)))
        my = y0 + ((i * 89) % span + int(t * span * LOUVRE_MOTE_DRIFT)) % span
        buf.pen = color.rgb(255, 252, 238, 70 + (i * 47) % 120)
        buf.rectangle((i * 151) % w, my, s, s)

# ── MENISCUS ───────────────────────────────────────────
# A bead of liquid glass magnifying a banded field, rim-lit with a caustic under it.

# @skinlab {"type":"color","label":"Band (deep)","group":"Palette"}
MENIS_DEEP = (36, 40, 168)


# @skinlab {"type":"color","label":"Band (mid)","group":"Palette"}
MENIS_MID = (226, 34, 146)


# @skinlab {"type":"color","label":"Band (hot)","group":"Palette"}
MENIS_HOT = (255, 198, 66)


# @skinlab {"type":"color","label":"Glass tint","group":"Palette"}
MENIS_GLASS = (210, 240, 255)


# @skinlab {"type":"color","label":"Rim shadow","group":"Palette"}
MENIS_SHADOW = (10, 6, 34)


# @skinlab {"type":"integer","label":"Bands","group":"Layout","min":3,"max":14,"step":1}
MENIS_BANDS = 7


# @skinlab {"type":"integer","label":"Satellite drops","group":"Layout","min":0,"max":6,"step":1}
MENIS_DROPS = 3


# @skinlab {"type":"number","label":"Bead size","group":"Shape","min":0.20,"max":0.50,"step":0.01}
MENIS_SIZE = 0.42


# @skinlab {"type":"number","label":"Bead height","group":"Layout","min":0.35,"max":0.65,"step":0.01}
MENIS_CENTRE = 0.50


# @skinlab {"type":"number","label":"Magnification","group":"Look","min":1.0,"max":3.5,"step":0.1}
MENIS_MAG = 2.6


# @skinlab {"type":"number","label":"Rim squash","group":"Look","min":1.0,"max":2.6,"step":0.05}
MENIS_EDGE = 1.85


# @skinlab {"type":"integer","label":"Caustic","group":"Look","min":0,"max":255,"step":5}
MENIS_CAUSTIC = 165


# @skinlab {"type":"number","label":"Glint sweep","group":"Motion","min":0.0,"max":1.2,"step":0.05}
MENIS_SWEEP = 0.55


# @skinlab {"type":"integer","label":"Rim sparks","group":"Layout","min":0,"max":10,"step":1}
MENIS_SPARKS = 8


# @skinlab {"type":"integer","label":"Running drops","group":"Layout","min":0,"max":3,"step":1}
MENIS_RUNNERS = 2


# @skinlab {"type":"integer","label":"Run speed","group":"Motion","min":0,"max":3,"step":1}
MENIS_RUN = 1


def _meniscus_u(buf):
    return max(1, buf.width // 40)


def _meniscus_s(buf):
    """The house stroke: a quarter of a unit, so 1 px at LORES and 2 at HIRES."""
    return max(1, _meniscus_u(buf) // 4)


def _meniscus_mix(a, b, k):
    if k < 0.0:
        k = 0.0
    if k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _meniscus_ramp(tint):
    """The field behind the glass, quantised into thick bands so a displacement
    of a few pixels is actually visible — and computed once, as a list, because
    the lens resamples it a hundred times a render."""
    n = max(1, MENIS_BANDS)
    out = []
    for i in range(n):
        f = i / max(1, n - 1)
        if f < 0.5:
            base = _meniscus_mix(MENIS_DEEP, MENIS_MID, f * 2.0)
        else:
            base = _meniscus_mix(MENIS_MID, MENIS_HOT, (f - 0.5) * 2.0)
        out.append(_meniscus_mix(base, MENIS_GLASS, tint))
    return out


def _meniscus_at(table, y, h):
    i = int(y * len(table) / max(1, h))
    if i < 0:
        i = 0
    if i > len(table) - 1:
        i = len(table) - 1
    return table[i]


def _meniscus_bead(buf):
    w, h = buf.width, buf.height
    return w // 2, int(h * MENIS_CENTRE), max(3, int(min(w, h) * MENIS_SIZE))


def _meniscus_lens(buf, cx, cy, rad, table):
    """Fill a disc with the field resampled through a spherical map: the centre
    magnifies, the rim compresses and reaches past the disc's own edge."""
    h = buf.height
    step = max(1, h // 96)
    inner = 1.0 / max(0.05, MENIS_MAG)
    outer = MENIS_EDGE - inner
    for y in range(cy - rad, cy + rad + 1, step):
        dy = y - cy
        if dy > rad:
            dy = rad
        if dy < -rad:
            dy = -rad
        half = int(math.sqrt(max(0.0, rad * rad - dy * dy)))
        if half <= 0:
            continue
        n = dy / rad
        c = _meniscus_at(table, cy + dy * (inner + outer * n * n), h)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(cx - half, y, half * 2, step)


def _meniscus_satellite(w, h, i):
    """Where satellite i sits — render places them, animate lights them, and
    a highlight that disagrees with its own drop is worse than no highlight."""
    return (int(w * (0.10 + 0.80 * (((i * 137) % 97) / 97.0))),
            int(h * (0.08 + 0.84 * (((i * 89) % 83) / 83.0))),
            max(2, int(min(w, h) * (0.05 + 0.035 * (((i * 53) % 7) / 7.0)))))


def _meniscus_drop(buf, cx, cy, rad, table):
    """A bead: shadow crescent, specular crescent, then its lensed contents."""
    e = _meniscus_s(buf) * 2
    buf.pen = color.rgb(*MENIS_SHADOW)
    buf.circle(cx + e, cy + e, rad)
    buf.pen = color.rgb(*MENIS_GLASS)
    buf.circle(cx - e, cy - e, rad)
    _meniscus_lens(buf, cx, cy, rad, table)


def _meniscus(buf):
    w, h = buf.width, buf.height
    u, s = _meniscus_u(buf), _meniscus_s(buf)
    step = max(1, h // 96)

    # The field. Thick bands, each shaded a little towards its own foot, so the
    # picture has structure for the glass to bend without going fussy.
    buf.pen = color.rgb(*MENIS_DEEP)
    buf.clear()
    plain = _meniscus_ramp(0.0)
    shaded = []
    for c in plain:
        for k in range(6):
            shaded.append(_meniscus_mix(c, MENIS_SHADOW, 0.10 + 0.16 * (k / 6.0)))
    for y in range(0, h, step):
        c = _meniscus_at(shaded, y, h)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(0, y, w, step)

    # Satellites first, so the main bead sits in front of them.
    small = _meniscus_ramp(0.38)
    for i in range(MENIS_DROPS):
        dx, dy, dr = _meniscus_satellite(w, h, i)
        _meniscus_drop(buf, dx, dy, dr, small)

    cx, cy, rad = _meniscus_bead(buf)
    _meniscus_drop(buf, cx, cy, rad, _meniscus_ramp(0.12))

    # Light focused through the bead pools just inside its lower rim.
    if MENIS_CAUSTIC > 0:
        for i in range(3):
            fy = 0.52 + 0.15 * i
            yy = cy + int(rad * fy)
            half = int(math.sqrt(max(0.0, rad * rad - (yy - cy) * (yy - cy))) * 0.86)
            buf.pen = color.rgb(255, 244, 226, max(0, MENIS_CAUSTIC - i * 40))
            buf.rectangle(cx - half, yy, half * 2, s * 2)

    # The static half of the specular: a hard hot dot up and left of centre.
    buf.pen = color.rgb(*MENIS_GLASS)
    buf.circle(cx - int(rad * 0.44), cy - int(rad * 0.46), max(1, int(rad * 0.15)))


def _meniscus_a(buf, t):
    """ONE light source, and everything wet in the frame answers to it.

    The hot spot, the arc of rim under it, the spark running the whole
    circumference and the highlight on every satellite are all driven by the
    same angle `a`. That is the difference between a bead of liquid and a
    picture of a circle with a dot sliding on it.
    """
    w, h = buf.width, buf.height
    u, s = _meniscus_u(buf), _meniscus_s(buf)
    cx, cy, rad = _meniscus_bead(buf)

    # The hot spot slides around the upper-left rim and back.
    a = -2.36 + MENIS_SWEEP * math.sin(t * 2 * math.pi)
    lift = rad * (0.62 + 0.07 * math.cos(t * 2 * math.pi))
    hx = cx + int(lift * math.cos(a))
    hy = cy + int(lift * math.sin(a))
    buf.pen = color.rgb(255, 255, 255, 120)
    buf.circle(hx, hy, max(2, int(rad * 0.22)))
    buf.pen = color.rgb(255, 255, 255)
    buf.circle(hx, hy, max(1, int(rad * 0.11)))

    # A short bright arc of rim travels with it.
    for i in range(5):
        aa = a - 0.34 + i * 0.17
        rx = cx + int(rad * math.cos(aa))
        ry = cy + int(rad * math.sin(aa))
        buf.pen = color.rgb(255, 255, 255, 210 - abs(i - 2) * 55)
        buf.rectangle(rx - s, ry - s, s * 2, s * 2)

    # The whole circumference stays wet: sparks all the way round, with the
    # brightness running round them once a loop. Fixed angles, moving value —
    # cheaper and far more liquid than moving the marks themselves.
    spin = t * 2 * math.pi
    n = max(0, MENIS_SPARKS)
    for i in range(n):
        aa = i * 2 * math.pi / max(1, n)
        k = 0.5 + 0.5 * math.cos(aa - spin)
        rx = cx + int(rad * 0.93 * math.cos(aa))
        ry = cy + int(rad * 0.93 * math.sin(aa))
        buf.pen = color.rgb(255, 255, 255, int(25 + 190 * k * k * k))
        buf.rectangle(rx - s, ry - s, s * 2, s * 2)

    # The lens is showing a different slice of the ramp as the drop settles:
    # one pale band and one dark one crossing the bead out of step.
    for i in range(2):
        by = cy + int(rad * 0.55 * math.sin(spin + i * 2.1))
        half = int(math.sqrt(max(0.0, rad * rad - (by - cy) * (by - cy))) * 0.92)
        buf.pen = (color.rgb(255, 255, 255, 46) if i == 0
                   else color.rgb(MENIS_SHADOW[0], MENIS_SHADOW[1], MENIS_SHADOW[2], 60))
        buf.rectangle(cx - half, by, half * 2, max(1, s * 2))

    # Every satellite catches the same light on the same side.
    for i in range(min(MENIS_DROPS, 3)):
        dx, dy, dr = _meniscus_satellite(w, h, i)
        buf.pen = color.rgb(255, 255, 255, 230)
        buf.circle(dx + int(dr * 0.42 * math.cos(a)),
                   dy + int(dr * 0.42 * math.sin(a)), max(1, dr // 4))

    # Fresh drops run down the field. Their fall is a whole canvas per loop, so
    # each one is back on its own start row at t = 1.
    span = h + u * 4
    for i in range(max(0, MENIS_RUNNERS)):
        rx = int(w * (0.09 + 0.82 * (i % 2))) + (i // 2) * u * 3
        ry = -u * 2 + ((i * 61) % span + int(t * span * MENIS_RUN)) % span
        dr = max(2, int(u * (1.3 - 0.3 * i)))
        buf.pen = color.rgb(MENIS_GLASS[0], MENIS_GLASS[1], MENIS_GLASS[2], 200)
        buf.circle(rx, ry, dr)
        buf.pen = color.rgb(255, 255, 255, 235)
        buf.circle(rx - dr // 3, ry - dr // 3, max(1, dr // 3))

    # The caustic breathes as the light moves across the bead, and a second,
    # tighter pool tracks the hot spot's side.
    k = 0.5 + 0.5 * math.sin(t * 2 * math.pi)
    yy = cy + int(rad * 0.60)
    half = int(math.sqrt(max(0.0, rad * rad - (yy - cy) * (yy - cy))) * 0.7)
    buf.pen = color.rgb(255, 246, 220, int(60 + 130 * k))
    buf.rectangle(cx - half, yy, half * 2, s * 2)
    buf.pen = color.rgb(255, 250, 236, int(90 + 120 * (1.0 - k)))
    buf.rectangle(cx - half // 2 - int(half * 0.4 * math.cos(a)),
                  yy + s * 3, half, s * 2)

# ── PRISM RING ───────────────────────────────────────────
# A thick ring of glass whose edges split into colour, turning a glint round itself.

# @skinlab {"type":"color","label":"Void","group":"Palette"}
PRISM_VOID = (5, 4, 16)


# @skinlab {"type":"color","label":"Haze","group":"Palette"}
PRISM_HAZE = (46, 20, 92)


# @skinlab {"type":"color","label":"Ring glass","group":"Palette"}
PRISM_BODY = (120, 226, 238)


# @skinlab {"type":"color","label":"Outer fringe","group":"Palette"}
PRISM_FRINGE_OUT = (255, 96, 64)


# @skinlab {"type":"color","label":"Inner fringe","group":"Palette"}
PRISM_FRINGE_IN = (128, 78, 255)


# @skinlab {"type":"color","label":"Glint","group":"Palette"}
PRISM_GLINT = (255, 255, 255)


# @skinlab {"type":"number","label":"Ring radius","group":"Shape","min":0.24,"max":0.48,"step":0.01}
PRISM_RADIUS = 0.42


# @skinlab {"type":"number","label":"Ring thickness","group":"Shape","min":0.15,"max":0.60,"step":0.02}
PRISM_THICK = 0.34


# @skinlab {"type":"integer","label":"Fringe width","group":"Look","min":1,"max":5,"step":1}
PRISM_FRINGE_W = 2


# @skinlab {"type":"integer","label":"Body banding","group":"Look","min":0,"max":80,"step":5}
PRISM_BANDING = 45


# @skinlab {"type":"integer","label":"Glint tiles","group":"Motion","min":2,"max":10,"step":1}
PRISM_ARC = 6


# @skinlab {"type":"integer","label":"Turns per loop","group":"Motion","min":-2,"max":2,"step":1}
PRISM_SPIN = 1


# @skinlab {"type":"integer","label":"Dispersion sparks","group":"Layout","min":0,"max":6,"step":1}
PRISM_SPARKS = 6


# @skinlab {"type":"boolean","label":"Exit glint","group":"Motion"}
PRISM_EXIT = True


# @skinlab {"type":"integer","label":"Haze pulse","group":"Motion","min":0,"max":90,"step":5}
PRISM_HAZE_PULSE = 55


def _prism_ring_u(buf):
    return max(1, buf.width // 40)


def _prism_ring_s(buf):
    """The house stroke: a quarter of a unit, so 1 px at LORES and 2 at HIRES."""
    return max(1, _prism_ring_u(buf) // 4)


def _prism_ring_mix(a, b, k):
    if k < 0.0:
        k = 0.0
    if k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _prism_ring_back(y, h):
    """Void at the top and foot, saturated haze across the middle."""
    f = y / max(1, h - 1)
    k = 1.0 - abs(f - 0.5) * 2.0
    return _prism_ring_mix(PRISM_VOID, PRISM_HAZE, k * k)


def _prism_ring_geom(buf):
    w, h = buf.width, buf.height
    rout = max(4, int(min(w, h) * PRISM_RADIUS))
    rin = max(2, int(rout * (1.0 - PRISM_THICK)))
    return w // 2, h // 2, rout, rin


def _prism_ring_tile(buf, cx, cy, r_in, r_out, a0, a1):
    x0, y0 = int(cx + r_in * math.cos(a0)), int(cy + r_in * math.sin(a0))
    x1, y1 = int(cx + r_out * math.cos(a0)), int(cy + r_out * math.sin(a0))
    x2, y2 = int(cx + r_out * math.cos(a1)), int(cy + r_out * math.sin(a1))
    x3, y3 = int(cx + r_in * math.cos(a1)), int(cy + r_in * math.sin(a1))
    buf.triangle(x0, y0, x1, y1, x2, y2)
    buf.triangle(x0, y0, x2, y2, x3, y3)


def _prism_ring(buf):
    w, h = buf.width, buf.height
    u, s = _prism_ring_u(buf), _prism_ring_s(buf)
    step = max(1, h // 96)
    f = max(1, PRISM_FRINGE_W) * s
    cx, cy, rout, rin = _prism_ring_geom(buf)

    # The background ramp once, as a list: the bore restores from the same
    # table further down, and the body's tones come out of a second one.
    back = [_prism_ring_back(y, h) for y in range(0, h, step)]
    tones = []
    for i in range(33):
        k = i / 32.0
        tone = _prism_ring_mix(PRISM_BODY, (255, 255, 255), max(0.0, 0.50 - k * 1.1))
        tone = _prism_ring_mix(tone, (10, 16, 52), max(0.0, (k - 0.45) * 0.95))
        if k > 0.90:
            tone = _prism_ring_mix(tone, PRISM_BODY, (k - 0.90) * 5.0)
        tones.append(tone)

    for y in range(0, h, step):
        c = back[y // step]
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(0, y, w, step)

    # No blur here at all: the ring is glass because of what its edges do.
    # Shadow, then the warm side of the split, then the body.
    buf.pen = color.rgb(2, 2, 8)
    buf.circle(cx + f, cy + f, rout + f)
    buf.pen = color.rgb(*PRISM_FRINGE_OUT)
    buf.circle(cx, cy, rout + f * 2)
    buf.pen = color.rgb(*_prism_ring_mix(PRISM_FRINGE_OUT, PRISM_BODY, 0.55))
    buf.circle(cx, cy, rout + f)

    # The body, row by row rather than as one flat disc: a lit shoulder at the
    # top, a deep foot, and a thin bounce where light comes back off the base.
    for y in range(cy - rout, cy + rout + 1, step):
        dy = y - cy
        if dy > rout:
            dy = rout
        if dy < -rout:
            dy = -rout
        half = int(math.sqrt(max(0.0, rout * rout - dy * dy)))
        if half <= 0:
            continue
        tone = tones[int((dy + rout) * 32 / max(1, rout * 2))]
        buf.pen = color.rgb(tone[0], tone[1], tone[2])
        buf.rectangle(cx - half, y, half * 2, step)

    # Thin darker bands across the body: thickness read as a few strata rather
    # than one flat plate, which is what a chunk of glass actually looks like.
    if PRISM_BANDING > 0:
        for i in range(3):
            by = cy - rout + int(rout * 2 * (0.20 + 0.30 * i))
            dy = by - cy
            half = int(math.sqrt(max(0.0, rout * rout - dy * dy)))
            buf.pen = color.rgb(20, 40, 70, PRISM_BANDING)
            buf.rectangle(cx - half, by, half * 2, max(1, s * 2))

    # The cool side of the split lines the bore.
    buf.pen = color.rgb(*PRISM_FRINGE_IN)
    buf.circle(cx, cy, rin + f * 2)
    buf.pen = color.rgb(*_prism_ring_mix(PRISM_FRINGE_IN, PRISM_VOID, 0.45))
    buf.circle(cx, cy, rin + f)

    # Restore the background through the bore, row by row, so the gradient runs
    # on unbroken behind the name instead of being plugged with a flat disc.
    for y in range(cy - rin, cy + rin + 1, step):
        dy = y - cy
        if dy > rin:
            dy = rin
        if dy < -rin:
            dy = -rin
        half = int(math.sqrt(max(0.0, rin * rin - dy * dy)))
        if half <= 0:
            continue
        c = back[min(len(back) - 1, max(0, y // step))]
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(cx - half, y, half * 2, step)

    # A standing highlight where the ring's shoulder faces the light.
    buf.pen = color.rgb(255, 255, 255, 150)
    _prism_ring_tile(buf, cx, cy, rout - f * 3, rout - f, -2.55, -1.95)


def _prism_ring_a(buf, t):
    w, h = buf.width, buf.height
    s = _prism_ring_s(buf)
    f = max(1, PRISM_FRINGE_W) * s
    cx, cy, rout, rin = _prism_ring_geom(buf)
    n = max(2, PRISM_ARC)
    base = t * 2 * math.pi * PRISM_SPIN
    span = 0.16

    # The glint runs round the ring and its colour fringes trail it, one tile
    # further out and one further in, which is dispersion moving with the light.
    lip = rin + (rout - rin) * 5 // 9
    for i in range(n):
        a0 = base + i * span
        k = 1.0 - abs(i - (n - 1) * 0.5) / max(1.0, (n - 1) * 0.5)
        buf.pen = color.rgb(PRISM_GLINT[0], PRISM_GLINT[1], PRISM_GLINT[2],
                            int(50 + 205 * k))
        _prism_ring_tile(buf, cx, cy, lip, rout - f, a0, a0 + span * 1.04)

    a = base - span
    buf.pen = color.rgb(PRISM_FRINGE_OUT[0], PRISM_FRINGE_OUT[1], PRISM_FRINGE_OUT[2], 210)
    _prism_ring_tile(buf, cx, cy, rout - f, rout + f, a, a + span * 0.85)
    a = base + n * span
    buf.pen = color.rgb(PRISM_FRINGE_IN[0], PRISM_FRINGE_IN[1], PRISM_FRINGE_IN[2], 210)
    _prism_ring_tile(buf, cx, cy, rin, rin + f * 2, a, a + span * 0.85)

    # Light entering a torus leaves it again on the far side, dimmer and cooler.
    # Without it the ring reads as a disc with one lamp taped to it.
    if PRISM_EXIT:
        a = base + math.pi
        buf.pen = color.rgb(PRISM_BODY[0], PRISM_BODY[1], PRISM_BODY[2], 175)
        _prism_ring_tile(buf, cx, cy, rin + f * 2, lip, a, a + span * 1.6)

    # A dark stratum turning the other way. Two things moving at different
    # rates through one body is what makes a slab read as THICK.
    a = -base * 0.6
    buf.pen = color.rgb(16, 34, 74, 78)
    _prism_ring_tile(buf, cx, cy, rin + f, rout - f * 2, a, a + span * 3.4)

    # Dispersion sparks pinned round the rim: warm where the glint has just
    # been, cool where it is going, and only bright as it passes.
    m = max(0, PRISM_SPARKS)
    for i in range(m):
        aa = i * 2 * math.pi / max(1, m)
        k = 0.5 + 0.5 * math.cos(aa - base)
        k = k * k * k
        warm = math.sin(aa - base) > 0
        tint = PRISM_FRINGE_OUT if warm else PRISM_FRINGE_IN
        rr = rout - f if warm else rin + f
        buf.pen = color.rgb(tint[0], tint[1], tint[2], int(30 + 200 * k))
        buf.rectangle(cx + int(rr * math.cos(aa)) - s, cy + int(rr * math.sin(aa)) - s,
                      s * 2, s * 2)

    # The haze behind breathes with the glint, top and foot only, so the bore
    # the name sits in stays where it was.
    if PRISM_HAZE_PULSE > 0:
        b = int(PRISM_HAZE_PULSE * (0.5 + 0.5 * math.sin(base)))
        buf.pen = color.rgb(PRISM_HAZE[0], PRISM_HAZE[1], PRISM_HAZE[2], b)
        buf.rectangle(0, int(h * 0.06), w, max(1, int(h * 0.10)))
        buf.rectangle(0, int(h * 0.84), w, max(1, int(h * 0.10)))

# ── SHEAR ───────────────────────────────────────────
# A leaning sheet of glass laid over a banded field; everything under it steps.

# @skinlab {"type":"color","label":"Band (deep)","group":"Palette"}
SHEAR_DEEP = (22, 26, 96)


# @skinlab {"type":"color","label":"Band (mid)","group":"Palette"}
SHEAR_MID = (24, 220, 176)


# @skinlab {"type":"color","label":"Band (hot)","group":"Palette"}
SHEAR_HOT = (255, 236, 96)


# @skinlab {"type":"color","label":"Glass tint","group":"Palette"}
SHEAR_GLASS = (222, 244, 255)


# @skinlab {"type":"color","label":"Keyline","group":"Palette"}
SHEAR_KEY = (3, 4, 14)


# @skinlab {"type":"color","label":"Edge fringe","group":"Palette"}
SHEAR_FRINGE = (255, 88, 168)


# @skinlab {"type":"integer","label":"Bands","group":"Layout","min":3,"max":16,"step":1}
SHEAR_BANDS = 6


# @skinlab {"type":"number","label":"Sheet width","group":"Layout","min":0.20,"max":0.80,"step":0.02}
SHEAR_WIDTH = 0.46


# @skinlab {"type":"number","label":"Lean","group":"Shape","min":-1.2,"max":1.2,"step":0.05}
SHEAR_LEAN = 0.55


# @skinlab {"type":"number","label":"Refraction step","group":"Look","min":0.0,"max":0.20,"step":0.005}
SHEAR_STEP = 0.08


# @skinlab {"type":"number","label":"Glass paleness","group":"Look","min":0.0,"max":0.6,"step":0.02}
SHEAR_PALE = 0.20


# @skinlab {"type":"boolean","label":"Second sheet","group":"Layout"}
SHEAR_SECOND = True


# @skinlab {"type":"integer","label":"Glint cycles","group":"Motion","min":1,"max":4,"step":1}
SHEAR_GLINT = 1


# @skinlab {"type":"integer","label":"Edge sparks","group":"Layout","min":0,"max":8,"step":1}
SHEAR_SPARKS = 6


# @skinlab {"type":"integer","label":"Cast caustics","group":"Layout","min":0,"max":6,"step":1}
SHEAR_CAUSTICS = 4


# @skinlab {"type":"integer","label":"Field bars","group":"Layout","min":0,"max":4,"step":1}
SHEAR_FIELD = 3


def _shear_u(buf):
    return max(1, buf.width // 40)


def _shear_s(buf):
    """The house stroke: a quarter of a unit, so 1 px at LORES and 2 at HIRES."""
    return max(1, _shear_u(buf) // 4)


def _shear_mix(a, b, k):
    if k < 0.0:
        k = 0.0
    if k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _shear_ramp(tint):
    """Every band's colour once, as a list. Four row passes cross this canvas
    and the arithmetic below would otherwise run several hundred times."""
    n = max(1, SHEAR_BANDS)
    out = []
    for i in range(n):
        f = i / max(1, n - 1)
        if f < 0.5:
            base = _shear_mix(SHEAR_DEEP, SHEAR_MID, f * 2.0)
        else:
            base = _shear_mix(SHEAR_MID, SHEAR_HOT, (f - 0.5) * 2.0)
        # Alternate the value band to band. A smooth ramp displaced sideways
        # looks exactly like a smooth ramp; a rhythm displaced sideways jumps.
        if i % 2:
            base = _shear_mix(base, SHEAR_KEY, 0.24)
        else:
            base = _shear_mix(base, (255, 255, 255), 0.10)
        out.append(_shear_mix(base, SHEAR_GLASS, tint))
    return out


def _shear_at(table, y, h):
    i = int(y * len(table) / max(1, h))
    if i < 0:
        i = 0
    if i > len(table) - 1:
        i = len(table) - 1
    return table[i]


def _shear_sheet(buf, wide):
    """A leaning parallelogram: left edge x at row y, and its width."""
    w, h = buf.width, buf.height
    big = max(2, int(w * SHEAR_WIDTH))
    if wide:
        return big, SHEAR_LEAN, int(w * 0.04)
    # A second, slimmer sheet lying parallel and nearer the viewer, overlapping
    # the first by a fifth of its width: two sheets read as depth, and where
    # they cross the field is displaced twice. Two sheets crossing at an angle
    # would just read as a letter X.
    return max(2, int(big * 0.44)), SHEAR_LEAN, int(w * 0.04) + int(big * 0.80)


def _shear_left(buf, wide, y):
    sw, lean, foot = _shear_sheet(buf, wide)
    return int(foot + (buf.height - y) * lean)


def _shear_quad(buf, x_top, x_bot, thick, h):
    """A leaning stroke of `thick` pixels: two triangles, because line() is 1 px."""
    buf.triangle(x_top, 0, x_top + thick, 0, x_bot, h)
    buf.triangle(x_top + thick, 0, x_bot, h, x_bot + thick, h)


def _shear(buf):
    w, h = buf.width, buf.height
    u, s = _shear_u(buf), _shear_s(buf)
    # Three row passes cross this canvas, so halve them: the bands are far
    # taller than two rows and the leaning edges are covered by their strokes.
    step = max(1, h // 60)
    shift = max(1, int(h * SHEAR_STEP))
    field = _shear_ramp(0.0)
    pale = _shear_ramp(SHEAR_PALE)
    thin = _shear_ramp(SHEAR_PALE * 0.7)
    deep = _shear_ramp(min(1.0, SHEAR_PALE * 1.8))

    for y in range(0, h, step):
        c = _shear_at(field, y, h)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(0, y, w, step)

    # Under the wide sheet the field is resampled from `shift` rows lower and
    # paled: the same picture, displaced, which is what looking through a slab
    # of glass at an angle actually does to what is behind it.
    sw, lean, foot = _shear_sheet(buf, True)
    for y in range(0, h, step):
        c = _shear_at(pale, y + shift, h)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(int(foot + (h - y) * lean), y, sw, step)

    if SHEAR_SECOND:
        sw2, lean2, foot2 = _shear_sheet(buf, False)
        for y in range(0, h, step):
            x2 = int(foot2 + (h - y) * lean2)
            x1 = int(foot + (h - y) * lean)
            over = min(x2 + sw2, x1 + sw) - max(x2, x1)
            if over < sw2:
                c = _shear_at(thin, y - shift, h)
                buf.pen = color.rgb(c[0], c[1], c[2])
                buf.rectangle(x2, y, sw2, step)
            c = _shear_at(deep, y + shift * 2, h)
            buf.pen = color.rgb(c[0], c[1], c[2])
            if over >= sw2:
                buf.rectangle(x2, y, sw2, step)
            elif over > 0:
                buf.rectangle(max(x2, x1), y, over, step)

    # Crisp edges, drawn last. Specular up the leading edge with a warm fringe
    # just outside it; a hard keyline down the trailing one.
    e = s * 2
    tl = _shear_left(buf, True, 0)
    bl = _shear_left(buf, True, h)
    buf.pen = color.rgb(*SHEAR_FRINGE)
    _shear_quad(buf, tl - e * 2, bl - e * 2, e, h)
    buf.pen = color.rgb(255, 255, 255)
    _shear_quad(buf, tl, bl, e, h)
    buf.pen = color.rgb(*SHEAR_KEY)
    _shear_quad(buf, tl + sw - e, bl + sw - e, e, h)
    buf.pen = color.rgb(SHEAR_GLASS[0], SHEAR_GLASS[1], SHEAR_GLASS[2], 120)
    _shear_quad(buf, tl + sw - e * 3, bl + sw - e * 3, s, h)

    if SHEAR_SECOND:
        sw2, lean2, foot2 = _shear_sheet(buf, False)
        t2 = _shear_left(buf, False, 0)
        b2 = _shear_left(buf, False, h)
        buf.pen = color.rgb(240, 252, 255, 190)
        _shear_quad(buf, t2, b2, s, h)
        buf.pen = color.rgb(*_shear_mix(SHEAR_KEY, SHEAR_DEEP, 0.45))
        _shear_quad(buf, t2 + sw2 - s, b2 + sw2 - s, s, h)


def _shear_a(buf, t):
    w, h = buf.width, buf.height
    u, s = _shear_u(buf), _shear_s(buf)
    e = s * 2
    sw, lean, foot = _shear_sheet(buf, True)

    # A glint slides the whole length of the leading edge and off both ends, so
    # t = 1 joins t = 0 with the mark already out of frame.
    seg = max(4, int(h * 0.34))
    y0 = int(-seg + (t * SHEAR_GLINT % 1.0) * (h + seg * 2))
    y1 = y0 + seg
    xa = _shear_left(buf, True, y0)
    xb = _shear_left(buf, True, y1)
    buf.pen = color.rgb(255, 255, 255)
    buf.triangle(xa, y0, xa + e, y0, xb, y1)
    buf.triangle(xa + e, y0, xb, y1, xb + e, y1)
    buf.pen = color.rgb(SHEAR_FRINGE[0], SHEAR_FRINGE[1], SHEAR_FRINGE[2], 200)
    buf.triangle(xa - e * 2, y0, xa - e, y0, xb - e * 2, y1)
    buf.triangle(xa - e, y0, xb - e * 2, y1, xb - e, y1)

    # A soft bloom sits inside the glass beside it, thin enough to stay a glow.
    buf.pen = color.rgb(255, 255, 255, 40)
    buf.triangle(xa + e, y0, xa + u * 2, y0, xb + e, y1)
    buf.triangle(xa + u * 2, y0, xb + e, y1, xb + u * 2, y1)

    # The near sheet takes the same event half a loop later, and its trailing
    # keyline goes hard black as the light passes: the two sheets stop being
    # one shape the moment they stop agreeing about the light.
    if SHEAR_SECOND:
        sw2, lean2, foot2 = _shear_sheet(buf, False)
        seg2 = max(3, int(h * 0.26))
        y2 = int(-seg2 + ((t * SHEAR_GLINT + 0.5) % 1.0) * (h + seg2 * 2))
        y3 = y2 + seg2
        xc = _shear_left(buf, False, y2)
        xd = _shear_left(buf, False, y3)
        buf.pen = color.rgb(250, 254, 255, 225)
        buf.triangle(xc, y2, xc + s, y2, xd, y3)
        buf.triangle(xc + s, y2, xd, y3, xd + s, y3)
        buf.pen = color.rgb(SHEAR_KEY[0], SHEAR_KEY[1], SHEAR_KEY[2], 200)
        buf.triangle(xc + sw2 - s, y2, xc + sw2, y2, xd + sw2 - s, y3)
        buf.triangle(xc + sw2, y2, xd + sw2 - s, y3, xd + sw2, y3)

    # Sparks skittering down the leading edge ahead of the glint. Each phase is
    # `t * an integer + a constant`, so every spark is back where it started at
    # the wrap.
    for i in range(max(0, SHEAR_SPARKS)):
        q = (t * SHEAR_GLINT + i * 0.137) % 1.0
        yy = int(q * h)
        buf.pen = color.rgb(255, 255, 255, 90 + (i * 53) % 150)
        buf.rectangle(_shear_left(buf, True, yy) - s, yy, e, e)

    # What the sheet throws onto the field beyond it: short bright slivers
    # sliding down just clear of the trailing edge.
    for i in range(max(0, SHEAR_CAUSTICS)):
        q = (t + i / float(max(1, SHEAR_CAUSTICS))) % 1.0
        yy = int(q * h)
        buf.pen = color.rgb(255, 250, 224, 120)
        buf.rectangle(_shear_left(buf, True, yy) + sw + e, yy, u * 3, max(1, e))

    # And the bare field on the near side, taking the same source: a wide slow
    # bar, which is the one kind of movement the name band tolerates.
    #
    # Each bar is then drawn AGAIN inside the sheet, `shift` rows higher —
    # because that is exactly where the sheet resamples the field from
    # (`_shear`, the pale pass). So the bar visibly JOGS as it crosses the
    # glass. The displacement was the whole idea of this skin and until now it
    # was the one thing in it that never moved.
    shift = max(1, int(h * SHEAR_STEP))
    for i in range(max(0, SHEAR_FIELD)):
        q = (t + i / float(max(1, SHEAR_FIELD))) % 1.0
        yy = int(q * h)
        buf.pen = color.rgb(255, 255, 255, 52)
        buf.rectangle(0, yy, max(2, _shear_left(buf, True, yy) - e), max(1, e))
        jy = yy - shift
        buf.pen = color.rgb(255, 255, 255, 60)
        buf.rectangle(_shear_left(buf, True, jy), jy, sw, max(1, e))

# ── BLISS HILL ───────────────────────────────────────────
# BLISS HILL — a deep blue sky over one sunlit green hill, cumulus drifting.

# @skinlab {"type":"color","label":"Sky (zenith)","group":"Palette"}
BLISS_SKY_TOP = (36, 84, 172)


# @skinlab {"type":"color","label":"Sky (horizon)","group":"Palette"}
BLISS_SKY_LOW = (188, 219, 242)


# @skinlab {"type":"color","label":"Hill","group":"Palette"}
BLISS_HILL = (86, 152, 44)


# @skinlab {"type":"color","label":"Sunlit crest","group":"Palette"}
BLISS_HILL_SUN = (140, 196, 66)


# @skinlab {"type":"color","label":"Hill shadow","group":"Palette"}
BLISS_HILL_SHADE = (46, 96, 30)


# @skinlab {"type":"color","label":"Cloud","group":"Palette"}
BLISS_CLOUD = (252, 252, 252)


# @skinlab {"type":"color","label":"Cloud underside","group":"Palette"}
BLISS_CLOUD_SHADE = (176, 200, 226)


# @skinlab {"type":"number","label":"Horizon height","group":"Layout","min":0.60,"max":0.95,"step":0.01}
BLISS_HORIZON = 0.87


# @skinlab {"type":"number","label":"Crest rise","group":"Shape","min":0.05,"max":0.34,"step":0.01}
BLISS_RISE = 0.26


# @skinlab {"type":"number","label":"Crest position","group":"Shape","min":0.05,"max":0.60,"step":0.01}
BLISS_CREST = 0.20


# @skinlab {"type":"number","label":"Cloud size","group":"Shape","min":0.05,"max":0.18,"step":0.01}
BLISS_CLOUD_SIZE = 0.11


# @skinlab {"type":"integer","label":"Small clouds","group":"Layout","min":2,"max":5,"step":1}
BLISS_CLOUDS = 3


# @skinlab {"type":"integer","label":"Wind (lanes per loop)","group":"Motion","min":0,"max":3,"step":1}
BLISS_WIND = 1


# @skinlab {"type":"integer","label":"High wisps","group":"Layout","min":0,"max":4,"step":1}
BLISS_WISPS = 3


# @skinlab {"type":"integer","label":"Birds","group":"Layout","min":0,"max":3,"step":1}
BLISS_BIRDS = 2


# @skinlab {"type":"integer","label":"Grass gusts","group":"Layout","min":0,"max":5,"step":1}
BLISS_GUSTS = 4


# @skinlab {"type":"integer","label":"Gust speed","group":"Motion","min":0,"max":3,"step":1}
BLISS_GUST_SPEED = 1


def _bliss_hill_crest(fx):
    """Height of the hill above the horizon at fx, as 0..1 of the rise.

    Left of the crest it climbs in off the edge; right of it a half cosine
    sweeps all the way down to the horizon. That swoop is the whole picture.
    """
    if fx <= BLISS_CREST:
        return 0.86 + 0.14 * (fx / max(0.001, BLISS_CREST))
    return 0.5 + 0.5 * math.cos(math.pi * (fx - BLISS_CREST) / max(0.001, 1.0 - BLISS_CREST))


def _bliss_hill_cloud(buf, cx, cy, r):
    """One cumulus: a grey belly disc, then three white lobes over it."""
    buf.pen = color.rgb(*BLISS_CLOUD_SHADE)
    buf.circle(cx, cy + max(1, r // 3), int(r * 1.06))
    buf.pen = color.rgb(*BLISS_CLOUD)
    buf.circle(cx - r, cy, max(1, int(r * 0.70)))
    buf.circle(cx + r, cy, max(1, int(r * 0.62)))
    buf.circle(cx, cy - max(1, r // 3), max(1, r))


def _bliss_hill_band(buf, t, count, cy, r):
    """`count` identical clouds on one lane, so the drift wraps seamlessly.

    Each cloud sits a whole lane apart and the whole band slides an INTEGER
    number of lanes per loop, so at t = 1 cloud k stands exactly where cloud
    k + wind stood at t = 0 and nothing jumps.
    """
    w = buf.width
    span = w + 4 * r
    lane = max(1, span // count)
    total = lane * count
    shift = int(t * lane) * BLISS_WIND
    for k in range(count):
        cx = -2 * r + ((k * lane + shift) % total)
        _bliss_hill_cloud(buf, cx, cy, r)


def _bliss_hill(buf):
    w, h = buf.width, buf.height
    s = max(1, w // 160)
    hz = int(h * BLISS_HORIZON)
    amp = int(h * BLISS_RISE)

    # Sky: one filled row per physical stroke, deep blue down to a pale haze.
    for y in range(0, hz, s):
        k = y * 255 // max(1, hz - 1)
        buf.pen = color.rgb(
            BLISS_SKY_TOP[0] + (BLISS_SKY_LOW[0] - BLISS_SKY_TOP[0]) * k // 255,
            BLISS_SKY_TOP[1] + (BLISS_SKY_LOW[1] - BLISS_SKY_TOP[1]) * k // 255,
            BLISS_SKY_TOP[2] + (BLISS_SKY_LOW[2] - BLISS_SKY_TOP[2]) * k // 255,
        )
        buf.rectangle(0, y, w, s)

    # A hazier ridge behind the main hill, so the right half has some depth.
    buf.pen = color.rgb(
        (BLISS_HILL[0] + BLISS_SKY_LOW[0] * 2) // 3,
        (BLISS_HILL[1] + BLISS_SKY_LOW[1] * 2) // 3,
        (BLISS_HILL[2] + BLISS_SKY_LOW[2] * 2) // 3,
    )
    buf.triangle(int(w * 0.38), hz, w, hz - int(h * 0.08), w, hz)

    # The hill, one stroke-wide column at a time: body, then the sunlit crest.
    for x in range(0, w, s):
        fx = (x + s * 0.5) / w
        ty = int(hz - amp * _bliss_hill_crest(fx))
        buf.pen = color.rgb(*BLISS_HILL)
        buf.rectangle(x, ty, s, h - ty)
        buf.pen = color.rgb(*BLISS_HILL_SUN)
        buf.rectangle(x, ty, s, max(1, (h - ty) // 4))

    # Shadow in the foreground grass.
    buf.pen = color.rgb(*BLISS_HILL_SHADE)
    buf.rectangle(0, int(h * 0.92), w, h - int(h * 0.92))


def _bliss_hill_a(buf, t):
    """Four wind speeds and something alive in the grass.

    Cumulus alone slides like one sheet of wallpaper. What makes a sky read as
    weather is layers that disagree: fat clouds low and slow, small ones a
    little quicker, wisps twice as fast again, birds that beat, and gusts
    running the contour of the hill down where the name never goes.
    """
    w, h = buf.width, buf.height
    s = max(1, w // 160)
    u = max(1, w // 40)
    r = max(2, int(h * BLISS_CLOUD_SIZE))
    _bliss_hill_band(buf, t, 2, int(h * 0.10), r)
    _bliss_hill_band(buf, t, min(BLISS_CLOUDS, 3), int(h * 0.19), max(2, int(r * 0.55)))

    # Every drift below is an integer number of spans per loop, so at t = 1
    # each mark is standing exactly where it stood at t = 0.
    span = w + u * 8
    for i in range(max(0, BLISS_WISPS)):
        x = -u * 4 + ((i * 137) % span + int(t * span * 2)) % span
        buf.pen = color.rgb(255, 255, 255, 120 + (i * 37) % 100)
        buf.rectangle(x, int(h * (0.035 + 0.022 * (i % 2))), u * (3 + i % 3), max(1, s))

    for i in range(max(0, BLISS_BIRDS)):
        x = -u * 2 + ((i * 89) % span + int(t * span)) % span
        y = int(h * (0.13 + 0.05 * (i % 2)))
        up = (int(t * 8) + i) % 2
        buf.pen = color.rgb(40, 54, 78)
        buf.rectangle(x, y - up * s, max(2, u), s)
        buf.rectangle(x + max(2, u), y - (1 - up) * s, max(2, u), s)

    for i in range(max(0, BLISS_GUSTS)):
        x = -u * 3 + ((i * 61) % span + int(t * span * BLISS_GUST_SPEED)) % span
        fx = (x + u) / float(max(1, w))
        if fx < 0.0:
            fx = 0.0
        if fx > 1.0:
            fx = 1.0
        gy = int(h * BLISS_HORIZON - h * BLISS_RISE * _bliss_hill_crest(fx))
        buf.pen = color.rgb(180, 226, 100, 150)
        buf.rectangle(x, gy + u * 2 + (i % 3) * u, u * (2 + i % 2), max(1, s))

# ── CARD CASCADE ───────────────────────────────────────────
# CARD CASCADE — the win animation: cards bouncing off green baize, trailing.

# @skinlab {"type":"color","label":"Baize (top)","group":"Palette"}
CARD_BAIZE = (0, 134, 52)


# @skinlab {"type":"color","label":"Baize (bottom)","group":"Palette"}
CARD_BAIZE_DEEP = (0, 62, 20)


# @skinlab {"type":"color","label":"Card face","group":"Palette"}
CARD_FACE = (250, 250, 244)


# @skinlab {"type":"color","label":"Card edge","group":"Palette"}
CARD_EDGE = (24, 24, 24)


# @skinlab {"type":"color","label":"Red suit","group":"Palette"}
CARD_RED = (208, 24, 32)


# @skinlab {"type":"color","label":"Card back","group":"Palette"}
CARD_BACK = (28, 52, 168)


# @skinlab {"type":"color","label":"Card back pattern","group":"Palette"}
CARD_BACK_INK = (120, 150, 230)


# @skinlab {"type":"integer","label":"Slots on the shelf","group":"Layout","min":4,"max":8,"step":1}
CARD_SLOTS = 7


# @skinlab {"type":"integer","label":"Cards in the trail","group":"Layout","min":6,"max":26,"step":1}
CARD_TRAIL = 15


# @skinlab {"type":"integer","label":"Cards in flight","group":"Motion","min":1,"max":8,"step":1}
CARD_FLYERS = 5


# @skinlab {"type":"integer","label":"Bounces across","group":"Shape","min":2,"max":6,"step":1}
CARD_BOUNCES = 4


# @skinlab {"type":"number","label":"Bounce height","group":"Shape","min":0.08,"max":0.30,"step":0.01}
CARD_ARC = 0.25


# @skinlab {"type":"boolean","label":"Flight trail","group":"Motion"}
CARD_GHOST = True


# @skinlab {"type":"boolean","label":"Deal from stock","group":"Motion"}
CARD_DEAL = True


# @skinlab {"type":"integer","label":"Foundation sparks","group":"Layout","min":0,"max":6,"step":1}
CARD_SPARKS = 6


def _card_cascade_lip(buf):
    return max(1, buf.width // 160)


def _card_cascade_size(buf):
    return max(4, int(buf.width * 0.115)), max(6, int(buf.height * 0.20))


def _card_cascade_fall(u, w, h, cht, arc, bounces):
    """Where a card is, u of the way through its run across the table.

    A cosine started at its peak leaves the shelf already falling, and the
    amplitude decays as it crosses, so the arcs stay clear of the broad flat
    band of baize the wearer's name is drawn on.
    """
    x = int(w * (1.03 - u * 1.20))
    floor = h - cht - int(h * 0.02)
    amp = arc * h * (1.0 - u * 0.72)
    return x, int(floor - abs(math.cos(math.pi * bounces * u)) * amp)


def _card_cascade_card(buf, x, y, cwd, cht, red):
    lip = _card_cascade_lip(buf)
    buf.pen = color.rgb(*CARD_EDGE)
    buf.rectangle(x, y, cwd, cht)
    buf.pen = color.rgb(*CARD_FACE)
    buf.rectangle(x + lip, y + lip, cwd - lip * 2, cht - lip * 2)
    buf.pen = color.rgb(*CARD_RED) if red else color.rgb(30, 30, 30)
    buf.rectangle(x + cwd // 5, y + cht // 5, max(1, cwd // 3), max(1, cht // 4))


def _card_cascade_back(buf, x, y, cwd, cht):
    lip = _card_cascade_lip(buf)
    buf.pen = color.rgb(*CARD_EDGE)
    buf.rectangle(x, y, cwd, cht)
    buf.pen = color.rgb(*CARD_BACK)
    buf.rectangle(x + lip, y + lip, cwd - lip * 2, cht - lip * 2)
    buf.pen = color.rgb(*CARD_BACK_INK)
    buf.rectangle(x + cwd // 3, y + cht // 3, max(1, cwd // 3), max(1, cht // 3))


def _card_cascade(buf):
    w, h = buf.width, buf.height
    lip = _card_cascade_lip(buf)
    cwd, cht = _card_cascade_size(buf)

    # Baize, one filled row per physical stroke.
    for y in range(0, h, lip):
        k = y * 255 // max(1, h - 1)
        buf.pen = color.rgb(
            CARD_BAIZE[0] + (CARD_BAIZE_DEEP[0] - CARD_BAIZE[0]) * k // 255,
            CARD_BAIZE[1] + (CARD_BAIZE_DEEP[1] - CARD_BAIZE[1]) * k // 255,
            CARD_BAIZE[2] + (CARD_BAIZE_DEEP[2] - CARD_BAIZE[2]) * k // 255,
        )
        buf.rectangle(0, y, w, lip)

    # The shelf across the top: stock, waste, then the foundations.
    sy = int(h * 0.035)
    gap = max(1, (w - CARD_SLOTS * cwd) // (CARD_SLOTS + 1))
    for i in range(CARD_SLOTS):
        sx = gap + i * (cwd + gap)
        if i == 0:
            _card_cascade_back(buf, sx, sy, cwd, cht)
        elif i == 1:
            _card_cascade_card(buf, sx, sy, cwd, cht, True)
        elif i == CARD_SLOTS - 1:
            _card_cascade_card(buf, sx, sy, cwd, cht, False)
        else:
            buf.pen = color.rgb(*CARD_BAIZE_DEEP)
            buf.rectangle(sx, sy, cwd, cht)
            buf.pen = color.rgb(*CARD_BAIZE)
            buf.rectangle(sx + lip, sy + lip, cwd - lip * 2, cht - lip * 2)

    # The trail the cascade has already smeared across the table.
    for i in range(CARD_TRAIL):
        u = (i + 0.5) / CARD_TRAIL
        x, y = _card_cascade_fall(u, w, h, cht, CARD_ARC, CARD_BOUNCES)
        _card_cascade_card(buf, x, y, cwd, cht, (i * 7) % 3 == 0)


def _card_cascade_a(buf, t):
    """The win animation, playing rather than posing.

    Three things move and they are three different events: cards bouncing the
    table and TURNING OVER between bounces, the smear each one leaves, and the
    stock dealing a card onto the waste up on the shelf.
    """
    w, h = buf.width, buf.height
    lip = _card_cascade_lip(buf)
    cwd, cht = _card_cascade_size(buf)
    sy = int(h * 0.035)
    gap = max(1, (w - CARD_SLOTS * cwd) // (CARD_SLOTS + 1))
    n = min(max(1, CARD_FLYERS), 6)

    for i in range(n):
        q = (t + i / float(n)) % 1.0
        x, y = _card_cascade_fall(q, w, h, cht, CARD_ARC * 1.08, CARD_BOUNCES + 1)
        if CARD_GHOST:
            gq = (q - 0.055) % 1.0
            gx, gy = _card_cascade_fall(gq, w, h, cht, CARD_ARC * 1.08, CARD_BOUNCES + 1)
            buf.pen = color.rgb(CARD_FACE[0], CARD_FACE[1], CARD_FACE[2], 95)
            buf.rectangle(gx, gy, cwd, cht)
        # The turn is staggered per card. With the default five flyers on four
        # bounces every card's bounce lands on the same frame, and an unstaggered
        # flip turned the whole cascade over at once at the wrap.
        if (int(q * (CARD_BOUNCES + 1) + i * 0.41) + i) % 2:
            _card_cascade_back(buf, x, y, cwd, cht)
        else:
            _card_cascade_card(buf, x, y, cwd, cht, (i * 5) % 2 == 0)

    # Stock to waste, twice a loop: face down leaving, face up landing. At both
    # ends it comes to rest exactly on the card render() already put there, so
    # the deal closes on a pixel instead of on a jump.
    if CARD_DEAL:
        p = (t * 2) % 1.0
        dx = gap + int((cwd + gap) * p)
        dy = sy - int(cht * 0.22 * math.sin(math.pi * p))
        if p < 0.5:
            _card_cascade_back(buf, dx, dy, cwd, cht)
        else:
            _card_cascade_card(buf, dx, dy, cwd, cht, True)

    # The foundations twinkle, because that is what they were doing when the
    # cascade started.
    for i in range(max(0, CARD_SPARKS)):
        k = 0.5 + 0.5 * math.sin((t + i * 0.19) * 4 * math.pi)
        sx = gap + (CARD_SLOTS - 1 - (i % 3)) * (cwd + gap) + (i * 7) % max(1, cwd)
        buf.pen = color.rgb(255, 255, 224, int(18 + 220 * k * k * k))
        buf.rectangle(sx, sy + (i * 13) % max(1, cht), lip * 2, lip * 2)

# ── MINEFIELD ───────────────────────────────────────────
# MINEFIELD — a grey bevelled sweeper board, red LED counters and a smiley.

# @skinlab {"type":"color","label":"Button face","group":"Palette"}
MINE_FACE = (192, 192, 192)


# @skinlab {"type":"color","label":"Bevel shadow","group":"Palette"}
MINE_SHADOW = (128, 128, 128)


# @skinlab {"type":"color","label":"LED panel","group":"Palette"}
MINE_PANEL = (16, 16, 16)


# @skinlab {"type":"color","label":"LED digits","group":"Palette"}
MINE_LED = (236, 32, 32)


# @skinlab {"type":"color","label":"Smiley","group":"Palette"}
MINE_SMILEY = (248, 224, 48)


# @skinlab {"type":"color","label":"Flag","group":"Palette"}
MINE_FLAG = (216, 32, 32)


# @skinlab {"type":"color","label":"One","group":"Palette"}
MINE_ONE = (0, 0, 232)


# @skinlab {"type":"color","label":"Two","group":"Palette"}
MINE_TWO = (0, 124, 0)


# @skinlab {"type":"integer","label":"Columns","group":"Layout","min":5,"max":10,"step":1}
MINE_COLS = 7


# @skinlab {"type":"integer","label":"Flags planted","group":"Layout","min":0,"max":4,"step":1}
MINE_FLAGS = 3


# @skinlab {"type":"integer","label":"Cursor hops per loop","group":"Motion","min":2,"max":8,"step":1}
MINE_HOPS = 4


# @skinlab {"type":"boolean","label":"Mouse pointer","group":"Details"}
MINE_POINTER = True


# @skinlab {"type":"integer","label":"Cells opened per click","group":"Motion","min":0,"max":5,"step":1}
MINE_CASCADE = 4


# @skinlab {"type":"boolean","label":"Right-click cycle","group":"Motion"}
MINE_MARK = True


MINEFIELD_SEGS = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F)


MINEFIELD_BOARD = (
    (0, 2, 2), (1, 2, 3), (2, 2, 2), (3, 2, 4), (4, 2, 2),
    (0, 3, 3), (1, 3, 2), (2, 3, 4), (3, 3, 2), (4, 3, 5),
)


MINEFIELD_FLAGGED = ((5, 2), (6, 3), (6, 2), (5, 3))


MINEFIELD_HOPS = ((5, 2), (6, 2), (4, 3), (6, 3), (4, 2), (3, 3), (5, 3), (3, 2))


# Where a click spreads to. A blank cell opens its neighbours, and that spread
# is the only thing in Minesweeper that is genuinely an animation.
MINEFIELD_SPREAD = ((1, 0), (0, 1), (1, 1), (-1, 0), (0, -1))


# The cell the right button cycles on: blank, flag, question, blank. It has to
# be one render() left CLEAN, or the mark lands on top of a painted one.
MINEFIELD_MARK_CELL = (5, 3)


# @skinlab {"type":"integer","label":"Min text height","group":"Details","min":8,"max":24,"step":1}
MINEFIELD_GLYPH = 12


def _minefield_lip(buf):
    return max(1, buf.width // 160)


def _minefield_raised(buf, x, y, bw, bh, lip):
    buf.pen = color.rgb(*MINE_FACE)
    buf.rectangle(x, y, bw, bh)
    buf.pen = color.rgb(255, 255, 255)
    buf.rectangle(x, y, bw, lip)
    buf.rectangle(x, y, lip, bh)
    buf.pen = color.rgb(*MINE_SHADOW)
    buf.rectangle(x, y + bh - lip, bw, lip)
    buf.rectangle(x + bw - lip, y, lip, bh)


def _minefield_sunken(buf, x, y, bw, bh, lip):
    buf.pen = color.rgb(*MINE_SHADOW)
    buf.rectangle(x, y, bw, lip)
    buf.rectangle(x, y, lip, bh)
    buf.pen = color.rgb(255, 255, 255)
    buf.rectangle(x, y + bh - lip, bw, lip)
    buf.rectangle(x + bw - lip, y, lip, bh)


def _minefield_digit(buf, x, y, dw, dh, value):
    """One LED digit as up to seven filled bars — no font, so it scales."""
    mask = MINEFIELD_SEGS[value % 10]
    th = max(1, dh // 6)
    half = dh // 2
    buf.pen = color.rgb(*MINE_LED)
    if mask & 0x01:
        buf.rectangle(x, y, dw, th)
    if mask & 0x02:
        buf.rectangle(x + dw - th, y, th, half)
    if mask & 0x04:
        buf.rectangle(x + dw - th, y + half, th, dh - half)
    if mask & 0x08:
        buf.rectangle(x, y + dh - th, dw, th)
    if mask & 0x10:
        buf.rectangle(x, y + half, th, dh - half)
    if mask & 0x20:
        buf.rectangle(x, y, th, half)
    if mask & 0x40:
        buf.rectangle(x, y + half - th // 2, dw, th)


def _minefield_counter(buf, x, y, dw, dh, gap, value):
    buf.pen = color.rgb(*MINE_PANEL)
    buf.rectangle(x - gap, y - gap, (dw + gap) * 3 + gap, dh + gap * 2)
    for i in range(3):
        _minefield_digit(buf, x + i * (dw + gap), y, dw, dh, value // (100 // 10 ** i) % 10)


def _minefield_board_box(buf):
    """Field origin, cell size and row count — shared by render and animate."""
    w, h = buf.width, buf.height
    lip = _minefield_lip(buf)
    fx, fy = lip * 3, int(h * 0.235)
    fw, fh = w - lip * 6, h - lip * 3 - fy
    cs = max(2, (fw - lip * 2) // MINE_COLS)
    rows = max(1, (fh - lip * 2) // cs)
    return fx + lip, fy + lip, cs, rows, fx, fy, fw, fh


def _minefield_face(buf, cx, cy, r, startled, look=0):
    """The reset smiley: disc, two eyes, and a mouth that reacts to a click.

    `look` slides both pupils toward whatever the pointer is doing. It costs
    nothing — the eyes were already two rectangles — and it defaults to 0, so
    render() draws the byte-identical face it always did.
    """
    buf.pen = color.rgb(*MINE_SMILEY)
    buf.circle(cx, cy, r)
    e = max(1, r // 4)
    buf.pen = color.rgb(20, 20, 20)
    buf.rectangle(cx - r // 2 + look, cy - r // 3, e, e)
    buf.rectangle(cx + r // 2 - e + look, cy - r // 3, e, e)
    if startled:
        buf.rectangle(cx - e, cy + r // 5, e * 2, e * 2)
    else:
        buf.rectangle(cx - r // 2, cy + r // 3, r, e)
        buf.rectangle(cx - r // 2 - e, cy + r // 5, e, e)
        buf.rectangle(cx + r // 2, cy + r // 5, e, e)


def _minefield_pointer(buf, x, y, size):
    buf.pen = color.rgb(20, 20, 20)
    buf.triangle(x, y, x + size, y + size, x, y + int(size * 1.5))
    buf.pen = color.rgb(255, 255, 255)
    buf.triangle(x + size // 3, y + size // 3, x + size, y + int(size * 1.15),
                 x + size // 3, y + int(size * 1.35))


def _minefield(buf):
    w, h = buf.width, buf.height
    lip = _minefield_lip(buf)
    buf.pen = color.rgb(*MINE_FACE)
    buf.clear()
    buf.pen = color.rgb(255, 255, 255)
    buf.rectangle(0, 0, w, lip)
    buf.rectangle(0, 0, lip, h)

    # Status panel: mine counter, reset smiley, clock.
    sy, sh = lip * 3, int(h * 0.20) - lip * 3
    _minefield_sunken(buf, lip * 3, sy, w - lip * 6, sh, lip)
    dh = max(3, int(sh * 0.62))
    dw = max(2, dh // 2)
    gap = max(1, dw // 3)
    _minefield_counter(buf, lip * 5, sy + (sh - dh) // 2, dw, dh, gap, 10)
    _minefield_counter(buf, w - lip * 5 - (dw + gap) * 3, sy + (sh - dh) // 2, dw, dh, gap, 87)
    bs = int(sh * 0.86)
    _minefield_raised(buf, w // 2 - bs // 2, sy + (sh - bs) // 2, bs, bs, lip)
    _minefield_face(buf, w // 2, sy + sh // 2, max(2, bs // 2 - lip), False)

    # The board.
    gx, gy, cs, rows, fx, fy, fw, fh = _minefield_board_box(buf)
    _minefield_sunken(buf, fx, fy, fw, fh, lip)
    buf.pen = color.rgb(*MINE_SHADOW)
    buf.rectangle(gx, gy, cs * MINE_COLS, cs * rows)
    bw = max(1, cs // 7)
    opened = {}
    for col, row, kind in MINEFIELD_BOARD:
        if col < MINE_COLS and row < rows:
            opened[row * 16 + col] = kind
    flags = {}
    for i in range(min(MINE_FLAGS, len(MINEFIELD_FLAGGED))):
        col, row = MINEFIELD_FLAGGED[i]
        flags[(row % max(1, rows)) * 16 + (col % MINE_COLS)] = True
    for row in range(rows):
        for col in range(MINE_COLS):
            x, y = gx + col * cs, gy + row * cs
            kind = opened.get(row * 16 + col, 0)
            buf.pen = color.rgb(*MINE_FACE)
            buf.rectangle(x, y, cs - bw, cs - bw)
            if kind:
                _minefield_mark(buf, x, y, cs - bw, kind)
                continue
            buf.pen = color.rgb(255, 255, 255)
            buf.rectangle(x, y, cs - bw, bw)
            buf.rectangle(x, y, bw, cs - bw)
            if flags.get(row * 16 + col):
                _minefield_flag(buf, x, y, cs - bw)


def _minefield_mark(buf, x, y, cs, kind):
    """A number, a mine, or nothing, inside an opened cell."""
    if kind == 5:
        buf.pen = color.rgb(20, 20, 20)
        buf.circle(x + cs // 2, y + cs // 2, max(1, cs // 3))
        buf.pen = color.rgb(255, 255, 255)
        buf.rectangle(x + cs // 3, y + cs // 3, max(1, cs // 8), max(1, cs // 8))
        return
    if kind < 3:
        return
    tint = MINE_ONE if kind == 3 else MINE_TWO
    buf.pen = color.rgb(*tint)
    if cs < MINEFIELD_GLYPH:
        # A glyph is a fixed pixel size, so once a cell is shorter than one
        # the number becomes the coloured pip it reads as across a room.
        buf.rectangle(x + cs // 3, y + cs // 3, max(1, cs // 3), max(1, cs // 3))
        return
    buf.font = font.sins
    label = "1" if kind == 3 else "2"
    scale = max(1, cs // (MINEFIELD_GLYPH + 4))
    tw, th = buf.measure_text(label)
    buf.text(label, x + (cs - int(tw) * scale) // 2, y + (cs - int(th) * scale) // 2, scale)


def _minefield_flag(buf, x, y, cs):
    buf.pen = color.rgb(*MINE_FLAG)
    buf.triangle(x + cs // 2, y + cs // 5, x + cs // 2, y + cs // 2,
                 x + cs // 5, y + cs // 3)
    buf.pen = color.rgb(20, 20, 20)
    buf.rectangle(x + cs // 2, y + cs // 5, max(1, cs // 8), cs * 3 // 5)


def _minefield_a(buf, t):
    """Somebody is PLAYING this board.

    The cursor glides to the next cell instead of teleporting onto it, the
    click opens a spreading patch of cells the way a blank one cascades, the
    right button cycles one cell blank -> flag -> question -> blank across the
    loop, and the smiley watches the pointer. Everything is keyed off `step`
    and `local`, both of which are exactly zero again at t = 1.
    """
    w, h = buf.width, buf.height
    lip = _minefield_lip(buf)
    gx, gy, cs, rows, fx, fy, fw, fh = _minefield_board_box(buf)
    bw = max(1, cs // 7)

    hops = max(1, MINE_HOPS)
    step = int(t * hops) % hops
    local = (t * hops) % 1.0
    col, row = MINEFIELD_HOPS[step % len(MINEFIELD_HOPS)]
    col, row = col % MINE_COLS, row % rows
    # The cursor only ever visits the first MINE_HOPS entries, so the cell it
    # is arriving FROM has to wrap on MINE_HOPS and not on the table's length.
    # Wrapping on the table sent it back from hop 3 to hop 7 at t = 1 and the
    # pointer teleported once a loop.
    was = MINEFIELD_HOPS[((step - 1) % hops) % len(MINEFIELD_HOPS)]
    pcol, prow = was[0] % MINE_COLS, was[1] % rows
    x, y = gx + col * cs, gy + row * cs
    pressed = local > 0.45

    # Smoothstep, so the cursor arrives rather than stopping dead.
    glide = local / 0.38 if local < 0.38 else 1.0
    glide = glide * glide * (3.0 - 2.0 * glide)
    px = gx + int((pcol + (col - pcol) * glide) * cs)
    py = gy + int((prow + (row - prow) * glide) * cs)

    if pressed:
        buf.pen = color.rgb(*MINE_SHADOW)
        buf.rectangle(x, y, cs - bw, cs - bw)
        buf.pen = color.rgb(*MINE_FACE)
        buf.rectangle(x + bw, y + bw, cs - bw * 2, cs - bw * 2)

    # What the click opened: neighbours going flat, one after another.
    spread = 0
    if local > 0.55:
        spread = int((local - 0.55) * 12)
        if spread > MINE_CASCADE:
            spread = MINE_CASCADE
    for k in range(spread):
        dcol, drow = MINEFIELD_SPREAD[k % len(MINEFIELD_SPREAD)]
        ccol, crow = col + dcol, row + drow
        if ccol < 0 or ccol >= MINE_COLS or crow < 0 or crow >= rows:
            continue
        ox, oy = gx + ccol * cs, gy + crow * cs
        buf.pen = color.rgb(*MINE_SHADOW)
        buf.rectangle(ox, oy, cs - bw, cs - bw)
        buf.pen = color.rgb(*MINE_FACE)
        buf.rectangle(ox + bw, oy + bw, cs - bw * 2, cs - bw * 2)
        if k == 1:
            buf.pen = color.rgb(*MINE_ONE)
            buf.rectangle(ox + cs // 3, oy + cs // 3, max(1, cs // 3), max(1, cs // 3))

    # The right button cycles one clean cell: blank, flag, question, blank.
    # Three equal thirds of the loop, so t = 1 lands back on blank.
    if MINE_MARK:
        mcol = MINEFIELD_MARK_CELL[0] % MINE_COLS
        mrow = MINEFIELD_MARK_CELL[1] % rows
        mx, my = gx + mcol * cs, gy + mrow * cs
        if t < 1.0 / 3.0:
            pass
        elif t < 2.0 / 3.0:
            _minefield_flag(buf, mx, my, cs - bw)
        else:
            buf.pen = color.rgb(20, 20, 20)
            buf.rectangle(mx + cs // 3, my + cs // 5, max(1, cs // 3), max(1, cs // 8))
            buf.rectangle(mx + cs // 2, my + cs // 2, max(1, cs // 8), max(1, cs // 5))

    sy, sh = lip * 3, int(h * 0.20) - lip * 3
    bs = int(sh * 0.86)
    look = 1 if px > w // 2 else -1
    _minefield_face(buf, w // 2, sy + sh // 2, max(2, bs // 2 - lip), pressed,
                    look * max(1, lip))

    dh = max(3, int(sh * 0.62))
    dw = max(2, dh // 2)
    gap = max(1, dw // 3)
    cx = w - lip * 5 - (dw + gap)
    buf.pen = color.rgb(*MINE_PANEL)
    buf.rectangle(cx, sy + (sh - dh) // 2, dw, dh)
    _minefield_digit(buf, cx, sy + (sh - dh) // 2, dw, dh, 7 + step)

    if MINE_POINTER:
        _minefield_pointer(buf, px + cs // 3, py + cs // 3, max(2, cs // 2))

# ── PAINTBOX ───────────────────────────────────────────
# PAINTBOX — a grey paint program: navy title bar, tool column, colour strip.

# @skinlab {"type":"color","label":"Title bar (left)","group":"Palette"}
PAINT_TITLE_A = (0, 0, 128)


# @skinlab {"type":"color","label":"Title bar (right)","group":"Palette"}
PAINT_TITLE_B = (16, 132, 208)


# @skinlab {"type":"color","label":"Window face","group":"Palette"}
PAINT_FACE = (192, 192, 192)


# @skinlab {"type":"color","label":"Bevel shadow","group":"Palette"}
PAINT_SHADOW = (128, 128, 128)


# @skinlab {"type":"color","label":"Canvas","group":"Palette"}
PAINT_CANVAS = (255, 255, 255)


# @skinlab {"type":"color","label":"Airbrush ink","group":"Palette"}
PAINT_INK = (216, 32, 32)


# @skinlab {"type":"color","label":"Second ink","group":"Palette"}
PAINT_INK2 = (0, 96, 200)


# @skinlab {"type":"integer","label":"Tool buttons","group":"Layout","min":6,"max":16,"step":2}
PAINT_TOOLS = 12


# @skinlab {"type":"integer","label":"Colours per row","group":"Layout","min":7,"max":14,"step":1}
PAINT_SWATCHES = 14


# @skinlab {"type":"integer","label":"Airbrush puffs","group":"Motion","min":4,"max":20,"step":1}
PAINT_SPRAY = 13


# @skinlab {"type":"integer","label":"Strokes per loop","group":"Motion","min":1,"max":3,"step":1}
PAINT_STROKES = 1


# @skinlab {"type":"integer","label":"Overspray","group":"Layout","min":0,"max":6,"step":1}
PAINT_MIST = 4


# @skinlab {"type":"text","label":"Title","group":"Details"}
PAINT_CAPTION = "UNTITLED"


PAINTBOX_STRIP = (
    (0, 0, 0), (128, 128, 128), (128, 0, 0), (255, 0, 0), (128, 128, 0),
    (255, 255, 0), (0, 128, 0), (0, 255, 0), (0, 128, 128), (0, 255, 255),
    (0, 0, 128), (0, 0, 255), (128, 0, 128), (255, 0, 255),
    (255, 255, 255), (192, 192, 192), (128, 128, 64), (255, 255, 128),
    (0, 64, 64), (0, 255, 128), (0, 128, 255), (128, 255, 255),
    (0, 64, 128), (128, 128, 255), (64, 0, 128), (255, 0, 128),
    (128, 64, 0), (255, 128, 64),
)


# @skinlab {"type":"integer","label":"Min text height","group":"Details","min":8,"max":24,"step":1}
PAINTBOX_GLYPH = 12


def _paintbox_lip(buf):
    return max(1, buf.width // 160)


def _paintbox_raised(buf, x, y, bw, bh, lip):
    buf.pen = color.rgb(*PAINT_FACE)
    buf.rectangle(x, y, bw, bh)
    buf.pen = color.rgb(255, 255, 255)
    buf.rectangle(x, y, bw, lip)
    buf.rectangle(x, y, lip, bh)
    buf.pen = color.rgb(*PAINT_SHADOW)
    buf.rectangle(x, y + bh - lip, bw, lip)
    buf.rectangle(x + bw - lip, y, lip, bh)


def _paintbox_sunken(buf, x, y, bw, bh, lip):
    buf.pen = color.rgb(*PAINT_SHADOW)
    buf.rectangle(x, y, bw, lip)
    buf.rectangle(x, y, lip, bh)
    buf.pen = color.rgb(255, 255, 255)
    buf.rectangle(x, y + bh - lip, bw, lip)
    buf.rectangle(x + bw - lip, y, lip, bh)


def _paintbox_chrome_text(buf, label, x, y, tint):
    """Chrome lettering, at panel resolutions only.

    A ROM glyph is a fixed pixel height — `sins` is _GLYPH tall whatever the
    canvas is — so a menu word on the panel would be a third of a thumbnail.
    Draw it only where a line of it stays under an eighth of the picture;
    below that the caller's bars carry the same information.
    """
    if buf.height < PAINTBOX_GLYPH * 8:
        return False
    buf.font = font.sins
    buf.pen = color.rgb(*tint)
    buf.text(label, x, y, max(1, buf.width // 160))
    return True


def _paintbox_pointer(buf, x, y, size):
    """The arrow, in the house style: black body, white fill inside it."""
    buf.pen = color.rgb(20, 20, 20)
    buf.triangle(x, y, x + size, y + size, x, y + int(size * 1.5))
    buf.pen = color.rgb(255, 255, 255)
    buf.triangle(x + size // 3, y + size // 3, x + size, y + int(size * 1.15),
                 x + size // 3, y + int(size * 1.35))


def _paintbox_brush_path(k, n, w, h):
    """A closed figure of eight in the lower canvas — it joins at both ends."""
    a = 2.0 * math.pi * k / n
    return (int(w * 0.70 + w * 0.15 * math.sin(a)),
            int(h * 0.685 + h * 0.045 * math.sin(a * 2.0)))


def _paintbox(buf):
    w, h = buf.width, buf.height
    lip = _paintbox_lip(buf)
    tb = int(h * 0.105)
    mb = int(h * 0.075)
    pw = int(w * 0.17)

    buf.pen = color.rgb(*PAINT_FACE)
    buf.clear()

    # Title bar: a left-to-right ramp in bands, navy into sky.
    bands = 18
    for i in range(bands):
        k = i * 255 // (bands - 1)
        buf.pen = color.rgb(
            PAINT_TITLE_A[0] + (PAINT_TITLE_B[0] - PAINT_TITLE_A[0]) * k // 255,
            PAINT_TITLE_A[1] + (PAINT_TITLE_B[1] - PAINT_TITLE_A[1]) * k // 255,
            PAINT_TITLE_A[2] + (PAINT_TITLE_B[2] - PAINT_TITLE_A[2]) * k // 255,
        )
        buf.rectangle(w * i // bands, 0, w // bands + 1, tb)
    if not _paintbox_chrome_text(buf, PAINT_CAPTION, lip * 2, (tb - PAINTBOX_GLYPH * lip) // 2, (255, 255, 255)):
        buf.pen = color.rgb(255, 255, 255)
        buf.rectangle(lip * 2, tb // 3, w // 5, max(1, tb // 3))

    # The three window buttons, hard against the right edge.
    bs = max(2, tb - lip * 2)
    for i in range(3):
        bx = w - lip - (3 - i) * (bs + lip)
        buf.pen = color.rgb(*PAINT_FACE)
        buf.rectangle(bx, lip, bs, bs)
        buf.pen = color.rgb(20, 20, 20)
        buf.rectangle(bx + bs // 4, lip + bs // 2 - max(1, bs // 8), bs // 2, max(1, bs // 5))

    # Menu bar.
    buf.pen = color.rgb(*PAINT_SHADOW)
    buf.rectangle(0, tb + mb - lip, w, lip)
    if not _paintbox_chrome_text(buf, "FILE  EDIT  VIEW", lip * 2, tb + (mb - PAINTBOX_GLYPH * lip) // 2, (20, 20, 20)):
        buf.pen = color.rgb(60, 60, 60)
        for i in range(3):
            buf.rectangle(lip * 2 + i * (w // 7), tb + mb // 3, w // 12, max(1, mb // 3))

    # Canvas.
    cx, cy = pw, tb + mb
    cw, ch = w - pw - lip, int(h * 0.80) - cy
    buf.pen = color.rgb(*PAINT_CANVAS)
    buf.rectangle(cx, cy, cw, ch)
    _paintbox_sunken(buf, cx, cy, cw, ch, lip)

    # What somebody drew on it: a house, a hill and a sun, low and to the left
    # so the middle of the canvas stays clear for the wearer's name.
    gy = int(h * 0.735)
    buf.pen = color.rgb(0, 128, 0)
    buf.rectangle(int(w * 0.21), gy, int(w * 0.38), max(1, lip * 2))
    buf.pen = color.rgb(*PAINT_INK2)
    buf.rectangle(int(w * 0.26), int(h * 0.655), int(w * 0.10), gy - int(h * 0.655))
    buf.pen = color.rgb(*PAINT_INK)
    buf.triangle(int(w * 0.24), int(h * 0.655), int(w * 0.38), int(h * 0.655),
                 int(w * 0.31), int(h * 0.605))
    buf.pen = color.rgb(255, 216, 0)
    buf.circle(int(w * 0.48), int(h * 0.635), max(2, int(h * 0.035)))

    # Tool column: two files of little raised buttons, each with its glyph.
    rows = max(1, PAINT_TOOLS // 2)
    bwid = (pw - lip * 3) // 2
    bhi = max(3, (int(h * 0.74) - cy) // rows)
    for i in range(PAINT_TOOLS):
        bx = lip + (i % 2) * (bwid + lip)
        by = cy + lip + (i // 2) * bhi
        _paintbox_raised(buf, bx, by, bwid, bhi - lip, lip)
        buf.pen = color.rgb(30, 30, 30)
        gx, gyy = bx + bwid // 4, by + bhi // 4
        gw, gh = max(1, bwid // 2), max(1, bhi // 2)
        if i % 4 == 0:
            buf.line(gx, gyy + gh, gx + gw, gyy)
        elif i % 4 == 1:
            buf.rectangle(gx, gyy, gw, max(1, gh // 2))
        elif i % 4 == 2:
            buf.circle(gx + gw // 2, gyy + gh // 2, max(1, gw // 2))
        else:
            buf.triangle(gx, gyy + gh, gx + gw, gyy + gh, gx + gw // 2, gyy)

    # Colour box along the bottom, with the two-square current-colour tile.
    sy = int(h * 0.83)
    sh = (h - lip - sy) // 2
    sx = pw
    sw = max(1, (w - lip - sx) // PAINT_SWATCHES)
    for row in range(2):
        for i in range(PAINT_SWATCHES):
            buf.pen = color.rgb(*PAINTBOX_STRIP[row * 14 + i])
            buf.rectangle(sx + i * sw, sy + row * sh, sw - lip, sh - lip)
    buf.pen = color.rgb(*PAINT_SHADOW)
    buf.rectangle(lip, sy, pw - lip * 3, sh * 2)
    buf.pen = color.rgb(*PAINT_INK)
    buf.rectangle(lip * 2, sy + lip, sh, sh)
    buf.pen = color.rgb(255, 255, 255)
    buf.rectangle(lip * 2 + sh // 2, sy + lip + sh // 2, sh, sh)


def _paintbox_a(buf, t):
    """Somebody sprays a squiggle, then rubs it out again.

    First half of the loop the airbrush lays ink down the path; second half the
    eraser follows the same path and the ink is simply not drawn behind it. At
    t = 1 the canvas is bare, which is exactly what t = 0 shows, so the stroke
    closes on a pixel instead of blinking off — and a stroke that appears and
    then is undone is what a paint program is FOR, which is the test for
    whether motion belongs to the picture.

    The tool button in the column goes in, the foreground swatch follows the
    tool, and the title bar keeps blinking that nothing has been saved.
    """
    w, h = buf.width, buf.height
    lip = _paintbox_lip(buf)
    n = max(2, PAINT_SPRAY)
    q = (t * PAINT_STROKES) % 1.0
    erasing = q >= 0.5
    head = n if erasing else int(q * 2.0 * n)
    # The eraser leads by one puff — it covers the one it is standing on — and
    # that is also what clears the last blob BEFORE the wrap instead of one
    # frame after it.
    tail = int((q - 0.5) * 2.0 * n + 0.9999) if erasing else 0
    r = max(1, int(h * 0.026))

    buf.pen = color.rgb(*PAINT_INK)
    for k in range(tail, head):
        x, y = _paintbox_brush_path(k, n, w, h)
        buf.circle(x + ((k * 37) % 3) - 1, y + ((k * 61) % 3) - 1, r)

    hx, hy = _paintbox_brush_path(tail if erasing else head, n, w, h)
    if erasing:
        buf.pen = color.rgb(20, 20, 20)
        buf.rectangle(hx - lip * 3, hy - lip * 3, lip * 6, lip * 6)
        buf.pen = color.rgb(*PAINT_CANVAS)
        buf.rectangle(hx - lip * 2, hy - lip * 2, lip * 4, lip * 4)
    else:
        buf.pen = color.rgb(20, 20, 20)
        buf.rectangle(hx - lip * 3, hy, lip * 7, lip)
        buf.rectangle(hx, hy - lip * 3, lip, lip * 7)
        for i in range(max(0, PAINT_MIST)):
            a = i * 2.4 + t * 2 * math.pi
            buf.pen = color.rgb(PAINT_INK[0], PAINT_INK[1], PAINT_INK[2],
                                70 + (i * 53) % 130)
            buf.rectangle(hx + int(r * 2.4 * math.cos(a)),
                          hy + int(r * 2.4 * math.sin(a)), lip, lip)

    # The tool that is in use is pushed in, the way a raised button does.
    tb = int(h * 0.105)
    cy = tb + int(h * 0.075)
    rows = max(1, PAINT_TOOLS // 2)
    bwid = (int(w * 0.17) - lip * 3) // 2
    bhi = max(3, (int(h * 0.74) - cy) // rows)
    ti = 4 if erasing else 2
    was = 2 if erasing else 4
    bx = lip + (ti % 2) * (bwid + lip)
    by = cy + lip + (ti // 2) * bhi
    buf.pen = color.rgb(*PAINT_SHADOW)
    buf.rectangle(bx, by, bwid, bhi - lip)
    buf.pen = color.rgb(*PAINT_FACE)
    buf.rectangle(bx + lip, by + lip, max(1, bwid - lip * 2), max(1, bhi - lip * 3))

    # The pointer travels between the two tool buttons rather than blinking
    # between them: it leaves the one it used and arrives on the next, which is
    # what explains the button going in and the swatch changing colour.
    g = (q % 0.5) / 0.09
    if g > 1.0:
        g = 1.0
    g = g * g * (3.0 - 2.0 * g)
    ox = lip + (was % 2) * (bwid + lip)
    oy = cy + lip + (was // 2) * bhi
    _paintbox_pointer(buf, ox + int((bx - ox) * g) + bwid // 3,
                      oy + int((by - oy) * g) + bhi // 3,
                      max(2, int(h * 0.045)))

    # The foreground swatch follows the tool: ink while spraying, paper while
    # erasing, which is the same lie every paint program tells.
    sy = int(h * 0.83)
    sh = (h - lip - sy) // 2
    buf.pen = color.rgb(*(PAINT_CANVAS if erasing else PAINT_INK))
    buf.rectangle(lip * 2, sy + lip, sh, sh)

    # Unsaved.
    if int(t * 8) % 2 == 0:
        buf.pen = color.rgb(255, 255, 255)
        buf.rectangle(int(w * 0.60), tb // 3, lip * 2, max(1, tb // 3))

# ── 3D PIPES ───────────────────────────────────────────
# 3D PIPES — fat plastic tubing with ball elbows crawls across a black room.

# @skinlab {"type":"color","label":"Room","group":"Palette"}
PIPE_ROOM = (6, 6, 10)


# @skinlab {"type":"color","label":"Pipe 1","group":"Palette"}
PIPE_A = (206, 58, 50)


# @skinlab {"type":"color","label":"Pipe 2","group":"Palette"}
PIPE_B = (66, 116, 216)


# @skinlab {"type":"color","label":"Pipe 3","group":"Palette"}
PIPE_C = (226, 186, 54)


# @skinlab {"type":"color","label":"Crawler 1","group":"Palette"}
PIPE_D = (78, 198, 118)


# @skinlab {"type":"number","label":"Pipe thickness","group":"Shape","min":0.30,"max":0.95,"step":0.05}
PIPE_FAT = 0.70


# @skinlab {"type":"integer","label":"Gloss","group":"Look","min":0,"max":255,"step":5}
PIPE_GLOSS = 150


# @skinlab {"type":"integer","label":"Finished pipes","group":"Layout","min":1,"max":3,"step":1}
PIPE_TRAILS = 3


# @skinlab {"type":"boolean","label":"Ball elbows","group":"Details"}
PIPE_BALLS = True


# @skinlab {"type":"color","label":"Crawler 2","group":"Palette"}
PIPE_E = (222, 108, 200)


# @skinlab {"type":"color","label":"Crawler 3","group":"Palette"}
PIPE_F = (86, 216, 226)


# @skinlab {"type":"number","label":"Laps per loop","group":"Motion","min":0.5,"max":2.0,"step":0.1}
PIPE_GROW = 1.0


# @skinlab {"type":"integer","label":"Crawlers","group":"Layout","min":1,"max":3,"step":1}
PIPE_CRAWLERS = 3


# @skinlab {"type":"number","label":"Crawler length","group":"Motion","min":0.6,"max":1.8,"step":0.1}
PIPE_SEGMENT = 1.55


# @skinlab {"type":"number","label":"Gloss travel","group":"Motion","min":0.0,"max":3.0,"step":0.25}
PIPE_SHINE = 1.0


# @skinlab {"type":"integer","label":"Lattice columns","group":"Layout","min":8,"max":14,"step":1}
PIPES_3D_COLS = 8


# @skinlab {"type":"integer","label":"Lattice rows","group":"Layout","min":6,"max":10,"step":1}
PIPES_3D_ROWS = 6


PIPES_3D_PIPE_1 = ((0, 5), (0, 0), (3, 0), (3, 4), (5, 4))


PIPES_3D_PIPE_2 = ((7, 5), (7, 3), (5, 3), (5, 0))


PIPES_3D_PIPE_3 = ((1, 3), (4, 3), (4, 5), (6, 5))


# CLOSED circuits, and every leg is at least two lattice cells long.
#
# Closed is the whole trick. A pipe that GROWS has to pop back to nothing once
# every four seconds, because `t` wraps; the screensaver got away with it by
# blanking the screen, and `animate()` cannot. A length of tube crawling a
# circuit never appears and never vanishes -- at t = 1 it stands exactly where
# it stood at t = 0 -- so the lattice can be alive without a seam.
#
# Two cells is the other half: the crawler is shorter than the shortest leg, so
# it spans at most two of them and rounds at most one elbow. That is what caps
# the animator at eight primitives per crawler no matter where it has got to.
PIPES_3D_LOOP_1 = ((1, 1), (6, 1), (6, 4), (1, 4))


PIPES_3D_LOOP_2 = ((2, 0), (5, 0), (5, 2), (7, 2), (7, 5), (4, 5), (4, 3), (2, 3))


PIPES_3D_LOOP_3 = ((0, 2), (3, 2), (3, 5), (0, 5))


def _pipes_3d_node(w, h, g):
    return int(w * (g[0] + 0.5) / PIPES_3D_COLS), int(h * (g[1] + 0.5) / PIPES_3D_ROWS)


def _pipes_3d_radius(buf):
    cell = min(buf.width // PIPES_3D_COLS, buf.height // PIPES_3D_ROWS)
    return max(1, int(cell * PIPE_FAT * 0.5))


def _pipes_3d_run(buf, x0, y0, x1, y1, r):
    """One straight length of tube, with a specular stripe near its top edge."""
    d = max(1, int(r * 0.55))
    o = int(r * 0.60)
    if y0 == y1:
        x, span = min(x0, x1), abs(x1 - x0) + 1
        buf.rectangle(x, y0 - r, span, r * 2 + 1)
        buf.pen = color.rgb(255, 255, 255, PIPE_GLOSS)
        buf.rectangle(x, y0 - o, span, d)
    else:
        y, span = min(y0, y1), abs(y1 - y0) + 1
        buf.rectangle(x0 - r, y, r * 2 + 1, span)
        buf.pen = color.rgb(255, 255, 255, PIPE_GLOSS)
        buf.rectangle(x0 - o, y, d, span)


def _pipes_3d_ball(buf, x, y, r):
    buf.circle(x, y, int(r * 1.12))
    buf.pen = color.rgb(255, 255, 255, PIPE_GLOSS)
    buf.circle(x - int(r * 0.38), y - int(r * 0.38), max(1, int(r * 0.38)))


def _pipes_3d_pipe(buf, path, tint, r):
    """One finished run of tube, elbow to elbow, all of it.

    It used to take a `reach` and draw a prefix, because `animate()` grew a
    pipe. Growing is what could not be made periodic, so the partial path went
    with it; `_pipes_3d_crawl` is the moving form now.
    """
    w, h = buf.width, buf.height
    px, py = _pipes_3d_node(w, h, path[0])
    for i in range(1, len(path)):
        qx, qy = _pipes_3d_node(w, h, path[i])
        buf.pen = color.rgb(*tint)
        if PIPE_BALLS:
            _pipes_3d_ball(buf, px, py, r)
            buf.pen = color.rgb(*tint)
        _pipes_3d_run(buf, px, py, qx, qy, r)
        px, py = qx, qy
    buf.pen = color.rgb(*tint)
    _pipes_3d_ball(buf, px, py, r)


def _pipes_3d_length(buf, path):
    w, h = buf.width, buf.height
    total = 0
    px, py = _pipes_3d_node(w, h, path[0])
    for i in range(1, len(path)):
        qx, qy = _pipes_3d_node(w, h, path[i])
        total += abs(qx - px) + abs(qy - py)
        px, py = qx, qy
    return total


def _pipes_3d_at(buf, path, at):
    """The point `at` pixels along an open path — arithmetic, no drawing."""
    w, h = buf.width, buf.height
    px, py = _pipes_3d_node(w, h, path[0])
    for i in range(1, len(path)):
        qx, qy = _pipes_3d_node(w, h, path[i])
        n = abs(qx - px) + abs(qy - py)
        if at <= n:
            n = max(1, n)
            return px + (qx - px) * at // n, py + (qy - py) * at // n
        at -= n
        px, py = qx, qy
    return px, py


def _pipes_3d_legs(buf, loop):
    """A closed circuit as (x0, y0, x1, y1, length) legs, and its perimeter."""
    w, h = buf.width, buf.height
    legs = []
    total = 0
    px, py = _pipes_3d_node(w, h, loop[0])
    for i in range(1, len(loop) + 1):
        qx, qy = _pipes_3d_node(w, h, loop[i % len(loop)])
        n = abs(qx - px) + abs(qy - py)
        legs.append((px, py, qx, qy, n))
        total += n
        px, py = qx, qy
    return legs, total


def _pipes_3d_crawl(buf, loop, tint, r, startf, seg):
    """One length of live tube crawling a closed circuit, `startf` of the way
    round it and `seg` pixels long.

    At most two legs are ever covered, so this is at most two runs, one elbow
    ball and one head ball: eight primitives, whatever the phase.
    """
    legs, total = _pipes_3d_legs(buf, loop)
    if total <= 0:
        return
    a = int(startf * total) % total
    b = a + seg
    hx, hy = legs[0][0], legs[0][1]
    elbow = None
    at = 0
    for x0, y0, x1, y1, n in legs:
        if n > 0:
            # The crawler is one interval, but the circuit is a ring, so the
            # copy one perimeter back is the part that has already come round.
            for lo, hi in ((a, b), (a - total, b - total)):
                c0 = lo if lo > at else at
                c1 = hi if hi < at + n else at + n
                if c1 <= c0:
                    continue
                ax = x0 + (x1 - x0) * (c0 - at) // n
                ay = y0 + (y1 - y0) * (c0 - at) // n
                bx = x0 + (x1 - x0) * (c1 - at) // n
                by = y0 + (y1 - y0) * (c1 - at) // n
                # An elbow only counts when the tube genuinely arrives from the
                # previous leg. `lo == at` is the tail sitting exactly on the
                # node, and balling that puts a phantom cap on the crawler for
                # one frame at t = 0 — the seam this whole design exists to
                # avoid.
                if lo < at:
                    elbow = (x0, y0)
                buf.pen = color.rgb(*tint)
                _pipes_3d_run(buf, ax, ay, bx, by, r)
                if c1 >= hi:
                    hx, hy = bx, by
        at += n
    if PIPE_BALLS and elbow is not None:
        buf.pen = color.rgb(*tint)
        _pipes_3d_ball(buf, elbow[0], elbow[1], r)
    buf.pen = color.rgb(*tint)
    _pipes_3d_ball(buf, hx, hy, r)


def _pipes_3d(buf):
    r = _pipes_3d_radius(buf)
    buf.pen = color.rgb(*PIPE_ROOM)
    buf.clear()
    finished = ((PIPES_3D_PIPE_1, PIPE_A), (PIPES_3D_PIPE_2, PIPE_B), (PIPES_3D_PIPE_3, PIPE_C))
    for i in range(min(PIPE_TRAILS, len(finished))):
        path, tint = finished[i]
        _pipes_3d_pipe(buf, path, tint, r)


PIPES_3D_CRAWLERS = ((PIPES_3D_LOOP_1, 0, 0.00, 1),
                     (PIPES_3D_LOOP_2, 1, 0.37, -1),
                     (PIPES_3D_LOOP_3, 2, 0.68, 1))


def _pipes_3d_a(buf, t):
    """The whole lattice alive: three lengths of tube crawling three circuits,
    and a gloss rolling along each pipe that was already there."""
    w, h = buf.width, buf.height
    r = _pipes_3d_radius(buf)
    cell = max(2, min(w // PIPES_3D_COLS, h // PIPES_3D_ROWS))
    seg = max(r * 2 + 1, int(cell * PIPE_SEGMENT))
    tints = (PIPE_D, PIPE_E, PIPE_F)

    for k in range(min(PIPE_CRAWLERS, len(PIPES_3D_CRAWLERS))):
        loop, ci, phase, way = PIPES_3D_CRAWLERS[k]
        _pipes_3d_crawl(buf, loop, tints[ci], r, phase + way * t * PIPE_GROW, seg)

    # Light rolling up and back down each finished pipe. The phase offset goes
    # INSIDE the cosine: offsetting the result instead would wrap mid-cycle and
    # snap the highlight back to the near elbow in the middle of its travel.
    if PIPE_SHINE > 0.0:
        gloss = min(255, PIPE_GLOSS + 60)
        finished = (PIPES_3D_PIPE_1, PIPES_3D_PIPE_2, PIPES_3D_PIPE_3)
        for i in range(min(PIPE_TRAILS, len(finished))):
            path = finished[i]
            q = 0.5 - 0.5 * math.cos((t * PIPE_SHINE + i * 0.31) * 2 * math.pi)
            gx, gy = _pipes_3d_at(buf, path, int(q * _pipes_3d_length(buf, path)))
            buf.pen = color.rgb(255, 255, 255, gloss)
            buf.circle(gx - int(r * 0.3), gy - int(r * 0.3), max(1, int(r * 0.55)))

# ── CRYOSTAT ───────────────────────────────────────────
# CRYOSTAT — the gold chandelier of a quantum computer hanging in its vacuum

# @skinlab {"type":"color","label":"Chamber","group":"Palette"}
CRYO_CHAMBER = (10, 12, 20)


# @skinlab {"type":"color","label":"Can wall","group":"Palette"}
CRYO_WALL = (26, 30, 44)


# @skinlab {"type":"color","label":"Gold plate","group":"Palette"}
CRYO_GOLD = (198, 148, 44)


# @skinlab {"type":"color","label":"Gold highlight","group":"Palette"}
CRYO_GOLD_LIT = (255, 226, 138)


# @skinlab {"type":"color","label":"Gold shadow","group":"Palette"}
CRYO_GOLD_DARK = (92, 60, 16)


# @skinlab {"type":"color","label":"Rods","group":"Palette"}
CRYO_ROD = (150, 112, 40)


# @skinlab {"type":"color","label":"Qubit light","group":"Palette"}
CRYO_QUBIT = (120, 214, 255)


# @skinlab {"type":"number","label":"Plate taper","group":"Layout","min":0.6,"max":0.95,"step":0.01}
CRYO_TAPER = 0.74


# @skinlab {"type":"integer","label":"Rods per tier","group":"Layout","min":3,"max":9,"step":1}
CRYO_RODS = 6


# @skinlab {"type":"integer","label":"Coil turns","group":"Layout","min":0,"max":9,"step":1}
CRYO_COILS = 7


# @skinlab {"type":"boolean","label":"Coax cables","group":"Details"}
CRYO_CABLES = True


# @skinlab {"type":"integer","label":"Qubit glow","group":"Look","min":0,"max":160,"step":5}
CRYO_GLOW = 90


# @skinlab {"type":"number","label":"Cooling pulse","group":"Motion","min":0.25,"max":4,"step":0.25}
CRYO_PULSE = 1.0


# @skinlab {"type":"integer","label":"Coil shimmer","group":"Layout","min":0,"max":5,"step":1}
CRYO_SHIMMER = 4


# @skinlab {"type":"integer","label":"Boil-off wisps","group":"Layout","min":0,"max":5,"step":1}
CRYO_VAPOUR = 4


# @skinlab {"type":"integer","label":"Field rings","group":"Layout","min":0,"max":3,"step":1}
CRYO_RINGS = 2


# @skinlab {"type":"boolean","label":"Microwave pulses","group":"Motion"}
CRYO_SIGNAL = True


CRYOSTAT_STAGE_FY = (0.03, 0.21, 0.58, 0.80)


def _cryostat_plate(buf, cx, y, half, th):
    buf.pen = color.rgb(*CRYO_GOLD)
    buf.rectangle(cx - half, y, half * 2, th)
    buf.pen = color.rgb(*CRYO_GOLD_LIT)
    buf.rectangle(cx - half, y, half * 2, max(1, th // 3))
    buf.pen = color.rgb(*CRYO_GOLD_DARK)
    buf.rectangle(cx - half, y + th, half * 2, max(1, th // 2))


def _cryostat(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, w // 160)          # hairlines keep their millimetres at HIRES
    cx = w // 2
    th = max(2, int(h * 0.045))

    # The vacuum can: a cold vertical gradient, darkest at the floor.
    for y in range(h):
        k = y / max(1, h - 1)
        buf.pen = color.rgb(
            int(CRYO_WALL[0] + (CRYO_CHAMBER[0] - CRYO_WALL[0]) * k),
            int(CRYO_WALL[1] + (CRYO_CHAMBER[1] - CRYO_WALL[1]) * k),
            int(CRYO_WALL[2] + (CRYO_CHAMBER[2] - CRYO_WALL[2]) * k),
        )
        buf.rectangle(0, y, w, 1)

    # Curved can wall: two dark flanks with a cold rim light down each edge.
    buf.pen = color.rgb(*CRYO_CHAMBER)
    buf.rectangle(0, 0, int(w * 0.07), h)
    buf.rectangle(w - int(w * 0.07), 0, int(w * 0.07), h)
    buf.pen = color.rgb(70, 86, 112)
    buf.rectangle(int(w * 0.07), 0, s, h)
    buf.rectangle(w - int(w * 0.07) - s, 0, s, h)

    stages = []
    for k, fy in enumerate(CRYOSTAT_STAGE_FY):
        stages.append((int(h * fy), int(w * 0.47 * (CRYO_TAPER ** k))))

    # Rods between the tiers, drawn before the plates so they tuck under them.
    for k in range(len(stages) - 1):
        y0, half0 = stages[k]
        y1, half1 = stages[k + 1]
        step = (half1 * 2) // max(1, CRYO_RODS - 1)
        for j in range(CRYO_RODS):
            x = cx - half1 + j * step
            buf.pen = color.rgb(*CRYO_ROD)
            buf.rectangle(x, y0, s * 2, y1 - y0 + th)
            buf.pen = color.rgb(*CRYO_GOLD_LIT)
            buf.rectangle(x, y0, s, y1 - y0 + th)

    # Coiled tubing hanging in the top bay only — high-frequency texture that
    # stays above the name band.
    y0, half0 = stages[0]
    y1, half1 = stages[1]
    for c in range(2):
        side = -1 if c == 0 else 1
        bx = cx + side * int(half1 * 0.78)
        for i in range(CRYO_COILS):
            yy = y0 + th + i * max(2, (y1 - y0 - th) // max(1, CRYO_COILS))
            off = u if i % 2 else -u
            buf.pen = color.rgb(*_cryostat_dim(CRYO_GOLD_LIT, 0.55 + 0.45 * (i % 2)))
            buf.rectangle(bx - u + (off // 2), yy, u * 2, max(1, s * 2))

    # Two coax lines dropping down the outside of the stack.
    if CRYO_CABLES:
        for c in range(2):
            side = -1 if c == 0 else 1
            buf.pen = color.rgb(96, 78, 58)
            for i in range(9):
                q0 = i / 9.0
                q1 = (i + 1) / 9.0
                ya = int(h * (0.06 + 0.74 * q0))
                yb = int(h * (0.06 + 0.74 * q1))
                xa = cx + side * int(w * (0.32 + 0.07 * math.sin(q0 * 3.1 + c)))
                xb = cx + side * int(w * (0.32 + 0.07 * math.sin(q1 * 3.1 + c)))
                buf.line(xa, ya, xb, yb)

    for k, (y, half) in enumerate(stages):
        _cryostat_plate(buf, cx, y, half, th)

    # The qubit package at the cold end, and its glow.
    qy = int(h * 0.90)
    for r, a in ((u * 4, CRYO_GLOW // 3), (u * 3, CRYO_GLOW * 2 // 3), (u * 2, CRYO_GLOW)):
        buf.pen = color.rgb(CRYO_QUBIT[0], CRYO_QUBIT[1], CRYO_QUBIT[2], a)
        buf.circle(cx, qy, r)
    buf.pen = color.rgb(24, 26, 34)
    buf.rectangle(cx - int(w * 0.08), qy - u, int(w * 0.16), u * 2)
    buf.pen = color.rgb(*CRYO_QUBIT)
    buf.rectangle(cx - int(w * 0.06), qy - s, int(w * 0.12), s * 2)

    # Frost specks on the can wall — scatter with different primes per axis.
    for i in range(14):
        x = (i * 137) % w
        y = (i * 89) % h
        if h * 0.24 < y < h * 0.62:
            continue
        buf.pen = color.rgb(180, 210, 235, 40 + (i * 31) % 70)
        buf.rectangle(x, y, s, s)


def _cryostat_dim(c, k):
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


def _cryostat_a(buf, t):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, w // 160)
    cx = w // 2

    # A cooling pulse runs down three rods of the long middle bay.
    y0 = int(h * CRYOSTAT_STAGE_FY[1])
    y1 = int(h * CRYOSTAT_STAGE_FY[2])
    half1 = int(w * 0.47 * (CRYO_TAPER ** 2))
    step = (half1 * 2) // max(1, CRYO_RODS - 1)
    for j in range(3):
        p = (t * CRYO_PULSE + j * 0.33) % 1.0
        x = cx - half1 + ((j * 2 + 1) % max(1, CRYO_RODS)) * step
        y = y0 + int((y1 - y0) * p)
        buf.pen = color.rgb(210, 240, 255, 200)
        buf.rectangle(x, y, s * 2, u * 2)
        buf.pen = color.rgb(140, 200, 255, 90)
        buf.rectangle(x, y - u * 2, s * 2, u * 2)

    # The qubit package breathes.
    b = 0.5 + 0.5 * math.sin(t * 2 * math.pi)
    qy = int(h * 0.90)
    buf.pen = color.rgb(CRYO_QUBIT[0], CRYO_QUBIT[1], CRYO_QUBIT[2], int(40 + 90 * b))
    buf.circle(cx, qy, int(u * (3 + 2 * b)))
    buf.pen = color.rgb(240, 252, 255, int(150 + 100 * b))
    buf.rectangle(cx - int(w * 0.04), qy - s, int(w * 0.08), s * 2)

    # Expanding field rings off the package. Each one ends at alpha 0, so the
    # ring that restarts at t = 0 has nothing to snap away from.
    for i in range(max(0, CRYO_RINGS)):
        p = (t * CRYO_PULSE + i / float(max(1, CRYO_RINGS))) % 1.0
        buf.pen = color.rgb(CRYO_QUBIT[0], CRYO_QUBIT[1], CRYO_QUBIT[2],
                            int(150 * (1.0 - p)))
        buf.circle(cx, qy, max(1, int(u * (1.5 + 5.0 * p))))

    # A highlight slides along the top plate, and the next tier down takes it
    # a beat later: one lamp travelling the stack, not two plates flashing.
    for k in (0, 1):
        hx = int(w * (0.08 + 0.84 * ((t * 0.5 + k * 0.18) % 1.0)))
        buf.pen = color.rgb(255, 244, 200, 190 - k * 60)
        buf.rectangle(hx, int(h * CRYOSTAT_STAGE_FY[k]), u * 2, max(2, int(h * 0.012)))

    # The coiled tubing in the top bay shimmers as the pulse passes behind it.
    y0 = int(h * CRYOSTAT_STAGE_FY[0])
    y1 = int(h * CRYOSTAT_STAGE_FY[1])
    half1 = int(w * 0.47 * (CRYO_TAPER ** 1))
    for i in range(max(0, CRYO_SHIMMER)):
        side = -1 if i % 2 else 1
        k = 0.5 + 0.5 * math.sin((t * CRYO_PULSE + i * 0.23) * 2 * math.pi)
        yy = y0 + int((y1 - y0) * (0.22 + 0.62 * ((i * 37) % 7) / 7.0))
        buf.pen = color.rgb(255, 238, 190, int(40 + 180 * k * k))
        buf.rectangle(cx + side * int(half1 * 0.62), yy, u, max(1, s * 2))

    # Microwave pulses running down the coax, one per side, half a loop apart.
    if CRYO_SIGNAL:
        for c in range(2):
            p = (t * 2 + c * 0.5) % 1.0
            yy = int(h * (0.06 + 0.74 * p))
            side = -1 if c == 0 else 1
            xx = cx + side * int(w * (0.32 + 0.07 * math.sin(p * 3.1 + c)))
            buf.pen = color.rgb(255, 214, 150, 230)
            buf.rectangle(xx - s, yy, s * 2, s * 2)

    # Boil-off drifting up the can wall. A whole band per loop, so every wisp
    # is back on its own start row at the wrap — and the bands are the two the
    # wearer's name never uses.
    for i in range(max(0, CRYO_VAPOUR)):
        top = i % 2 == 0
        yy0 = int(h * (0.04 if top else 0.64))
        span = max(2, int(h * (0.17 if top else 0.30)))
        yy = yy0 + span - 1 - ((i * 71) % span + int(t * span)) % span
        buf.pen = color.rgb(200, 226, 246, 60 + (i * 43) % 90)
        buf.rectangle(int(w * (0.10 + 0.78 * (((i * 137) % 61) / 61.0))), yy, s, s * 2)

    # Frost twinkles, top and bottom only.
    for i in range(3):
        if ((t * 2 + i * 0.37) % 1.0) < 0.3:
            buf.pen = color.rgb(220, 240, 255, 210)
            buf.rectangle((i * 53 + 11) % w, int(h * (0.08 + 0.78 * (i % 2))), s * 2, s * 2)

# ── DYSON SWARM ───────────────────────────────────────────
# DYSON SWARM — a star too big for the frame, its limb cutting off one corner

# @skinlab {"type":"color","label":"Space","group":"Palette"}
DYSON_SPACE = (4, 3, 10)


# @skinlab {"type":"color","label":"Limb","group":"Palette"}
DYSON_LIMB = (118, 22, 8)


# @skinlab {"type":"color","label":"Mid photosphere","group":"Palette"}
DYSON_MID = (206, 74, 12)


# @skinlab {"type":"color","label":"Hot zone","group":"Palette"}
DYSON_HOT = (246, 142, 24)


# @skinlab {"type":"color","label":"Core","group":"Palette"}
DYSON_CORE = (255, 216, 100)


# @skinlab {"type":"color","label":"Chromosphere rim","group":"Palette"}
DYSON_RIM = (255, 236, 176)


# @skinlab {"type":"color","label":"Collector","group":"Palette"}
DYSON_PANEL = (8, 6, 12)


# @skinlab {"type":"color","label":"Glint","group":"Palette"}
DYSON_GLINT = (198, 246, 255)


# @skinlab {"type":"integer","label":"Collectors","group":"Layout","min":4,"max":20,"step":1}
DYSON_PANELS = 12


# @skinlab {"type":"number","label":"Star size","group":"Layout","min":0.8,"max":1.6,"step":0.05}
DYSON_STAR_R = 1.0


# @skinlab {"type":"number","label":"Orbit height","group":"Layout","min":0.6,"max":0.95,"step":0.01}
DYSON_ARC = 0.86


# @skinlab {"type":"integer","label":"Starspots","group":"Details","min":0,"max":4,"step":1}
DYSON_SPOTS = 2


# @skinlab {"type":"number","label":"Glint travel","group":"Motion","min":0.25,"max":4,"step":0.25}
DYSON_GLINT_SPEED = 1.0


# @skinlab {"type":"integer","label":"Transiting collectors","group":"Layout","min":0,"max":5,"step":1}
DYSON_TRANSIT = 5


# @skinlab {"type":"integer","label":"Granulation","group":"Layout","min":0,"max":5,"step":1}
DYSON_GRAINS = 4


# @skinlab {"type":"integer","label":"Prominences","group":"Layout","min":1,"max":2,"step":1}
DYSON_FLARES = 2


DYSON_SWARM_BANDS = ((1.00, 0), (0.80, 1), (0.58, 2), (0.34, 3), (0.18, 4))


# @skinlab {"type":"integer","label":"Star slabs","group":"Layout","min":20,"max":120,"step":4}
DYSON_SWARM_STAR_ROWS = 60


def _dyson_swarm_band_color(i):
    return (DYSON_LIMB, DYSON_MID, DYSON_HOT, DYSON_CORE, DYSON_RIM)[i]


def _dyson_swarm_chain(w, h, i, n):
    """Position along the transiting orbit, i of n, bowing up in the middle."""
    q = i / max(1, n - 1)
    return int(w * (0.03 + 0.94 * q)), int(h * (DYSON_ARC - 0.20 * math.sin(math.pi * q))), q


def _dyson_swarm_orbit(w, h, q):
    """A NEARER orbit than the chain render() drew, running from off one edge
    to off the other so a collector entering or leaving does it outside the
    frame instead of appearing out of nothing at the wrap.

    Nearer matters: on the same arc the two files sit on top of each other and
    the transit reads as the static chain jittering.
    """
    x = int(w * (-0.12 + 1.24 * q))
    f = min(1.0, max(0.0, q))
    return x, int(h * (min(0.97, DYSON_ARC + 0.08) - 0.13 * math.sin(math.pi * f)))


def _dyson_swarm(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, w // 160)          # hairlines keep their millimetres at HIRES
    # The star's centre stays a FRACTION of the surface right up to the call
    # that draws. Rounding it to whole pixels first put the centre 0.6 px right
    # of scale at HIRES, which walked the limb off the right edge one row early
    # and made the chromosphere both shorter and cheaper on the bigger canvas.
    cx, cy = w * 0.18, h * 1.12
    big = DYSON_STAR_R * w

    buf.pen = color.rgb(*DYSON_SPACE)
    buf.clear()

    # Far stars in the corner space, before the disc covers the rest.
    for i in range(10):
        buf.pen = color.rgb(220, 224, 255, 90 + (i * 47) % 140)
        buf.rectangle((i * 137) % w, (i * 53) % (h // 2), s, s)

    # The star: nested discs, one filled row-slab at a time, hottest last.
    for f, ci in DYSON_SWARM_BANDS:
        r = big * f
        buf.pen = color.rgb(*_dyson_swarm_band_color(ci))
        for k in range(DYSON_SWARM_STAR_ROWS):
            y = h * k // DYSON_SWARM_STAR_ROWS
            rh = max(1, h * (k + 1) // DYSON_SWARM_STAR_ROWS - y)
            dy = y + rh / 2 - cy
            if abs(dy) < r:
                half = math.sqrt(r * r - dy * dy)
                x0 = max(0, int(cx - half))
                buf.rectangle(x0, y, int(min(w, cx + half)) - x0, rh)

    # The chromosphere: a bright rim following the limb where it crosses frame.
    buf.pen = color.rgb(*DYSON_RIM)
    for k in range(DYSON_SWARM_STAR_ROWS):
        y = h * k // DYSON_SWARM_STAR_ROWS
        rh = max(1, h * (k + 1) // DYSON_SWARM_STAR_ROWS - y)
        dy = y + rh / 2 - cy
        if abs(dy) < big:
            xe = cx + math.sqrt(big * big - dy * dy)
            if 0 <= xe < w:
                buf.rectangle(int(xe) - s * 3, y, s * 3, rh)

    # Starspots: big soft shapes, so they stay legible under the name.
    spots = ((0.17, 0.42, 3.4), (0.55, 0.80, 2.4), (0.30, 0.62, 1.8), (0.74, 0.94, 1.5))
    for i in range(min(DYSON_SPOTS, len(spots))):
        fx, fy, fr = spots[i]
        buf.pen = color.rgb(*_dyson_swarm_band_color(0))
        buf.circle(int(w * fx), int(h * fy), int(u * fr))
        buf.pen = color.rgb(52, 12, 8)
        buf.circle(int(w * fx), int(h * fy), int(u * fr * 0.55))

    # The swarm: a chain of collectors crossing the face, low and wide.
    n = DYSON_PANELS
    for i in range(n):
        x, y, q = _dyson_swarm_chain(w, h, i, n)
        pw = max(2, int(u * (0.9 + 1.2 * math.sin(math.pi * q))))
        ph = max(1, int(pw * 0.62))
        sk = max(1, pw // 3)
        buf.pen = color.rgb(*DYSON_PANEL)
        buf.triangle(x - pw, y - ph + sk, x + pw, y - ph - sk, x + pw, y + ph - sk)
        buf.triangle(x - pw, y - ph + sk, x + pw, y + ph - sk, x - pw, y + ph + sk)
        buf.pen = color.rgb(*DYSON_GLINT)
        buf.line(x - pw, y - ph + sk, x + pw, y - ph - sk)

    # Outriders far out in the dark corner, lit side toward the star.
    for i in range(4):
        x = int(w * (0.78 + 0.05 * (i % 3)))
        y = int(h * (0.04 + 0.07 * i))
        buf.pen = color.rgb(*DYSON_PANEL)
        buf.rectangle(x, y, max(2, u), max(1, u // 2))
        buf.pen = color.rgb(*DYSON_RIM)
        buf.rectangle(x, y + max(1, u // 2), max(2, u), max(1, s))


def _dyson_swarm_a(buf, t):
    """A swarm that swarms.

    render() froze one chain of collectors across the face; a glint running
    along it says the light moves but the machines do not. So a second file of
    collectors actually TRANSITS, entering and leaving off the edges, and the
    star underneath keeps turning over: granulation drifting along the limb,
    two prominences out of step, and the corner stars flickering.
    """
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, w // 160)
    n = DYSON_PANELS

    # The transit. Evenly spaced and offset by t, so at the wrap collector i
    # stands exactly where it stood — the chain is a ring, not a queue.
    m = max(0, DYSON_TRANSIT)
    for i in range(m):
        q = ((i + 0.5) / max(1, m) + t * DYSON_GLINT_SPEED) % 1.0
        x, y = _dyson_swarm_orbit(w, h, q)
        f = min(1.0, max(0.0, q))
        pw = max(2, int(u * (0.8 + 1.1 * math.sin(math.pi * f))))
        ph = max(1, int(pw * 0.62))
        sk = max(1, pw // 3)
        buf.pen = color.rgb(*DYSON_PANEL)
        buf.triangle(x - pw, y - ph + sk, x + pw, y - ph - sk, x + pw, y + ph - sk)
        buf.pen = color.rgb(*DYSON_GLINT)
        buf.line(x - pw, y - ph + sk, x + pw, y - ph - sk)

    # A wave of specular glint runs along the chain render() drew: exactly the
    # two panels nearest the wave front, so the cost cannot wander with the
    # collector count.
    # The sun angle swings and comes back rather than running off the end of
    # the chain and restarting at the other one.
    front = 0.5 - 0.5 * math.cos(t * 2 * math.pi * DYSON_GLINT_SPEED)
    for g in (0, 1):
        i = (int(front * n) + g) % max(1, n)
        x, y, q = _dyson_swarm_chain(w, h, i, n)
        pw = max(2, int(u * (0.9 + 1.2 * math.sin(math.pi * q))))
        ph = max(1, int(pw * 0.62))
        sk = max(1, pw // 3)
        buf.pen = color.rgb(255, 255, 255, 240 - g * 90)
        buf.line(x - pw, y - ph + sk, x + pw, y - ph - sk)
        buf.pen = color.rgb(DYSON_GLINT[0], DYSON_GLINT[1], DYSON_GLINT[2], 170 - g * 70)
        buf.rectangle(x - pw, y - ph - u, max(2, pw * 2), max(1, s * 2))

    # Prominences licking off the limb, out of step with each other, both well
    # clear of the name band.
    spots = ((0.83, 0.21), (0.62, 0.90))
    for i in range(min(max(1, DYSON_FLARES), len(spots))):
        b = 0.5 + 0.5 * math.sin((t + i * 0.41) * 2 * math.pi)
        px, py = int(w * spots[i][0]), int(h * spots[i][1])
        fl = int(u * (1.4 + 2.4 * b))
        buf.pen = color.rgb(240, 96, 26, 220)
        buf.triangle(px, py - fl, px + fl, py - fl // 2, px, py + fl)
        buf.pen = color.rgb(255, 186, 96, 230)
        buf.triangle(px, py - fl // 2, px + fl // 2, py, px, py + fl // 2)

    # Granulation crawling across the photosphere: a whole band per loop, kept
    # to the two strips the name never occupies.
    for i in range(max(0, DYSON_GRAINS)):
        top = i % 2 == 0
        x0 = int(w * (0.04 if top else 0.30))
        span = max(2, int(w * (0.42 if top else 0.60)))
        gx = x0 + ((i * 97) % span + int(t * span)) % span
        gy = int(h * (0.13 + 0.05 * (i % 2)) if top else h * (0.72 + 0.09 * (i % 2)))
        buf.pen = color.rgb(255, 214, 128, 120 + (i * 53) % 90)
        buf.rectangle(gx, gy, u, max(1, s * 2))

    # Two far stars twinkle in the dark corner.
    for i in range(2):
        if ((t * 2 + i * 0.4) % 1.0) < 0.35:
            buf.pen = color.rgb(255, 255, 255, 230)
            buf.rectangle(int(w * (0.90 - 0.07 * i)), int(h * (0.06 + 0.09 * i)), s * 2, s * 2)

# ── ION DRIVE ───────────────────────────────────────────
# ION DRIVE — the underside of a ship cropped across the top of the badge,

# @skinlab {"type":"color","label":"Void","group":"Palette"}
ION_VOID = (5, 3, 14)


# @skinlab {"type":"color","label":"Hull","group":"Palette"}
ION_METAL = (62, 60, 84)


# @skinlab {"type":"color","label":"Hull rim","group":"Palette"}
ION_RIM = (186, 194, 226)


# @skinlab {"type":"color","label":"Plume","group":"Palette"}
ION_PLUME = (104, 30, 226)


# @skinlab {"type":"color","label":"Core","group":"Palette"}
ION_CORE = (204, 242, 255)


# @skinlab {"type":"color","label":"Shock diamond","group":"Palette"}
ION_SHOCK = (255, 255, 255)


# @skinlab {"type":"number","label":"Hull depth","group":"Layout","min":0.16,"max":0.34,"step":0.01}
ION_THROAT = 0.22


# @skinlab {"type":"number","label":"Plume flare","group":"Layout","min":0.4,"max":1.3,"step":0.05}
ION_FLARE = 0.9


# @skinlab {"type":"integer","label":"Shock diamonds","group":"Layout","min":0,"max":8,"step":1}
ION_DIAMONDS = 5


# @skinlab {"type":"integer","label":"Ion sparks","group":"Layout","min":0,"max":40,"step":2}
ION_SPARKS = 22


# @skinlab {"type":"number","label":"Diamond drift","group":"Motion","min":0.25,"max":4,"step":0.25}
ION_DRIFT = 1.0


# @skinlab {"type":"number","label":"Throttle pulse","group":"Motion","min":0,"max":1,"step":0.05}
ION_PULSE = 0.55


# @skinlab {"type":"integer","label":"Turbulence bands","group":"Layout","min":0,"max":4,"step":1}
ION_TURB = 4


# @skinlab {"type":"integer","label":"Streaming ions","group":"Layout","min":0,"max":6,"step":1}
ION_STREAM = 6


# @skinlab {"type":"boolean","label":"Running lights","group":"Motion"}
ION_LIGHTS = True


# @skinlab {"type":"integer","label":"Void bands","group":"Layout","min":8,"max":48,"step":2}
ION_DRIVE_VOID_BANDS = 24                  # the backdrop ramp behind the cone


# @skinlab {"type":"integer","label":"Plume rows","group":"Layout","min":24,"max":120,"step":4}
ION_DRIVE_PLUME_ROWS = 72                  # slabs down the exhaust cone


# @skinlab {"type":"integer","label":"Nozzle rows","group":"Layout","min":3,"max":12,"step":1}
ION_DRIVE_NOZZLE_ROWS = 6                  # rows in the bell, throat to lip


def _ion_drive_mix(a, b, k):
    """Blend two colour tuples. k is clamped, so callers can overshoot."""
    if k < 0.0:
        k = 0.0
    elif k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _ion_drive_half(w, q):
    """Half-width of the plume, q = 0 at the nozzle lip, 1 at the bottom edge."""
    return int(w * (0.16 + ION_FLARE * 0.55 * (q ** 0.85)))


def _ion_drive(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, w // 160)          # hairlines keep their millimetres at HIRES
    cx = w // 2
    ty = int(h * ION_THROAT)      # the nozzle lip: everything above is hull
    span = max(1, h - ty)

    # The void, with the plume's own light bleeding up into it. A fixed band
    # count, so the ramp is the same picture at both resolutions and the same
    # price; the band edges are fractions of h, so nothing gaps.
    for i in range(ION_DRIVE_VOID_BANDS):
        y0 = h * i // ION_DRIVE_VOID_BANDS
        buf.pen = color.rgb(*_ion_drive_mix(ION_VOID, ION_PLUME,
                                  0.2 * (i + 0.5) / ION_DRIVE_VOID_BANDS))
        buf.rectangle(0, y0, w, max(1, h * (i + 1) // ION_DRIVE_VOID_BANDS - y0))

    # The plume: a bright barrel shock at the edge, a dark violet body, a hot
    # core. Three filled slabs a row, and the ramp does the rest. Fixed rows
    # again: q is the row's own position down the cone, not a pixel count.
    for i in range(ION_DRIVE_PLUME_ROWS):
        y = ty + span * i // ION_DRIVE_PLUME_ROWS
        rh = max(1, ty + span * (i + 1) // ION_DRIVE_PLUME_ROWS - y)
        q = (i + 0.5) / ION_DRIVE_PLUME_ROWS
        half = _ion_drive_half(w, q)
        buf.pen = color.rgb(*_ion_drive_mix(_ion_drive_mix(ION_PLUME, ION_VOID, 0.12), ION_VOID, q * 0.86))
        buf.rectangle(cx - half, y, half * 2, rh)
        # The barrel shock is a fixed-weight rim, not a fraction of the cone,
        # or it swallows the whole plume where the cone is narrow.
        rim = max(s * 2, half // 9)
        buf.pen = color.rgb(*_ion_drive_mix(_ion_drive_mix(ION_PLUME, ION_CORE, 0.55), ION_VOID, q * 0.9))
        buf.rectangle(cx - half, y, rim, rh)
        buf.rectangle(cx + half - rim, y, rim, rh)
        ch = int(w * (0.035 + 0.2 * (q ** 1.6)))
        buf.pen = color.rgb(*_ion_drive_mix(ION_CORE, ION_PLUME, q * 1.35))
        buf.rectangle(cx - ch, y, ch * 2, rh)

    # The ship, cropped to its underside: a slab of dark hull across the top,
    # deeper at the flanks, with the engine cut into the middle of it.
    buf.pen = color.rgb(*_ion_drive_mix(ION_METAL, ION_VOID, 0.55))
    buf.rectangle(0, 0, w, ty)
    buf.triangle(0, ty, 0, ty + int(h * 0.15), int(w * 0.36), ty)
    buf.triangle(w, ty, w, ty + int(h * 0.15), w - int(w * 0.36), ty)

    # Hull plating, and running lights out on the flanks.
    buf.pen = color.rgb(*_ion_drive_mix(ION_METAL, ION_RIM, 0.35))
    for k in range(3):
        yy = int(ty * (0.24 + 0.26 * k))
        buf.rectangle(0, yy, int(w * (0.30 - 0.06 * k)), s)
        buf.rectangle(w - int(w * (0.30 - 0.06 * k)), yy, int(w * (0.30 - 0.06 * k)), s)
    buf.pen = color.rgb(*ION_RIM)
    buf.rectangle(0, ty - s * 3, w, s * 2)
    buf.pen = color.rgb(120, 240, 255)
    buf.rectangle(int(w * 0.07), int(ty * 0.5), u * 3, s * 2)
    buf.rectangle(w - int(w * 0.07) - u * 3, int(ty * 0.5), u * 3, s * 2)

    # The nozzle: a short bell cut into the hull, flaring to the lip, glowing
    # from the throat down. Sits above the 0.24h..0.62h name band.
    ny = int(ty * 0.34)
    nspan = max(1, ty - ny)
    ns = max(1, nspan // max(1, ION_DRIVE_NOZZLE_ROWS - 1) + 1)
    for k in range(ION_DRIVE_NOZZLE_ROWS):
        q = k / max(1, ION_DRIVE_NOZZLE_ROWS - 1)
        y = ny + int(nspan * q)
        half = int(w * (0.10 + 0.11 * q * q))
        buf.pen = color.rgb(*_ion_drive_mix(_ion_drive_mix(ION_METAL, ION_RIM, 0.2), ION_PLUME, q * 0.95))
        buf.rectangle(cx - half, y, half * 2, ns)
        inner = int(half * 0.62)
        buf.pen = color.rgb(*_ion_drive_mix(_ion_drive_mix(ION_PLUME, ION_VOID, 0.45), ION_CORE, q * 0.8))
        buf.rectangle(cx - inner, y, inner * 2, ns)
    buf.pen = color.rgb(*_ion_drive_mix(ION_RIM, ION_CORE, 0.4))
    buf.rectangle(cx - int(w * 0.18), ty - s, int(w * 0.36), s * 2)

    # Ionised specks tracing the edge of the cone. Different primes per field,
    # and nothing lands in the name band.
    for i in range(ION_SPARKS):
        q = ((i * 29) % 97) / 97.0
        # The band test is on the unrounded height, or a spark sitting on the
        # boundary drops out at one resolution and not the other.
        fy = ty + span * q
        if h * 0.24 < fy < h * 0.62:
            continue
        side = 1 if i % 2 else -1
        x = cx + side * (_ion_drive_half(w, q) + s + (i * 7) % (u * 3))
        buf.pen = color.rgb(ION_CORE[0], ION_CORE[1], ION_CORE[2], 70 + (i * 53) % 150)
        buf.rectangle(x, int(fy), s * 2, s * 2)


def _ion_drive_a(buf, t):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, w // 160)
    cx = w // 2
    ty = int(h * ION_THROAT)
    span = max(1, h - ty)

    # Throttle: the throat breathes once per loop.
    b = 0.5 + 0.5 * math.sin(t * 2 * math.pi)
    a = int(90 + 165 * b * ION_PULSE)
    buf.pen = color.rgb(ION_CORE[0], ION_CORE[1], ION_CORE[2], a)
    buf.rectangle(cx - int(w * 0.08), ty - s * 2, int(w * 0.16), s * 3)
    buf.pen = color.rgb(255, 255, 255, min(255, a + 40))
    buf.rectangle(cx - int(w * 0.04), ty - s, int(w * 0.08), s * 2)

    # Shock diamonds, evenly spaced, sliding down the core and fading out.
    for i in range(ION_DIAMONDS):
        p = (t * ION_DRIFT + i / max(1, ION_DIAMONDS)) % 1.0
        y = ty + int(span * (0.06 + 0.86 * p))
        dw = max(2, int(u * (2.3 - 1.5 * p)))
        dh = max(3, int(dw * 1.8))
        buf.pen = color.rgb(ION_SHOCK[0], ION_SHOCK[1], ION_SHOCK[2],
                            int(250 * min(1.0, p * 5.0) * (1.0 - p)))
        buf.triangle(cx, y - dh, cx - dw, y, cx + dw, y)
        buf.triangle(cx - dw, y, cx + dw, y, cx, y + dh)

    # Two sparks flicker off the cone edge, below the name band.
    for i in range(2):
        q = 0.72 + 0.22 * ((t * 3 + i * 0.5) % 1.0)
        y = ty + int(span * q)
        side = 1 if i else -1
        buf.pen = color.rgb(255, 255, 255, 210)
        buf.rectangle(cx + side * (_ion_drive_half(w, q) + s * 2), y, s * 2, s * 2)

    # Turbulence washing down the cone: wide, slow, low-alpha bands, which is
    # the one kind of movement the name band tolerates. Each ends at alpha 0,
    # so the band that restarts at the throat has nothing to snap away from.
    for i in range(max(0, ION_TURB)):
        p = (t * ION_DRIFT + i / float(max(1, ION_TURB))) % 1.0
        q = 0.05 + 0.92 * p
        half = _ion_drive_half(w, q)
        buf.pen = color.rgb(ION_CORE[0], ION_CORE[1], ION_CORE[2], int(80 * (1.0 - p)))
        buf.rectangle(cx - half + s, ty + int(span * q), max(2, half * 2 - s * 2),
                      max(1, int(h * 0.013)))

    # Ions streaming off the cone edge, below the band, each fading to nothing
    # before it recycles.
    for i in range(max(0, ION_STREAM)):
        f = ((((i * 29) % 97) / 97.0) + t * 2.0) % 1.0
        q = 0.56 + 0.42 * f
        side = 1 if i % 2 else -1
        x = cx + side * (_ion_drive_half(w, q) + s * 2 + (i * 7) % max(1, u * 2))
        buf.pen = color.rgb(255, 255, 255, int(230 * (1.0 - f)))
        buf.rectangle(x, ty + int(span * q), s * 2, s * 2)

    # The throat is not steady: the core flickers at three times the loop.
    fk = 0.5 + 0.5 * math.sin(t * 6 * math.pi)
    cw = max(1, int(w * (0.028 + 0.030 * fk)))
    buf.pen = color.rgb(255, 255, 255, 205)
    buf.rectangle(cx - cw, ty + s * 2, cw * 2, max(1, s * 3))
    buf.pen = color.rgb(ION_CORE[0], ION_CORE[1], ION_CORE[2], 150)
    buf.rectangle(cx - cw * 2, ty + s * 5, cw * 4, max(1, s * 2))

    # Running lights on the flanks.
    if ION_LIGHTS and int(t * 4) % 2 == 0:
        buf.pen = color.rgb(210, 250, 255, 250)
        buf.rectangle(int(w * 0.07), int(ty * 0.5), u * 3, s * 2)
        buf.rectangle(w - int(w * 0.07) - u * 3, int(ty * 0.5), u * 3, s * 2)

# ── TERRAFORM ───────────────────────────────────────────
# TERRAFORM — a glass dome full of green standing on red desert under a dusty

# @skinlab {"type":"color","label":"Sky (high)","group":"Palette"}
TERRA_SKY_HIGH = (56, 30, 74)


# @skinlab {"type":"color","label":"Sky (horizon)","group":"Palette"}
TERRA_SKY_LOW = (236, 138, 84)


# @skinlab {"type":"color","label":"Sand","group":"Palette"}
TERRA_SAND = (146, 62, 40)


# @skinlab {"type":"color","label":"Sand (near)","group":"Palette"}
TERRA_SAND_DARK = (78, 34, 28)


# @skinlab {"type":"color","label":"Dome glass","group":"Palette"}
TERRA_DOME = (30, 98, 106)


# @skinlab {"type":"color","label":"Dome rim","group":"Palette"}
TERRA_DOME_LIT = (170, 246, 236)


# @skinlab {"type":"color","label":"Green inside","group":"Palette"}
TERRA_INNER = (58, 196, 118)


# @skinlab {"type":"color","label":"Structures","group":"Palette"}
TERRA_TOWER = (26, 16, 24)


# @skinlab {"type":"color","label":"Moons","group":"Palette"}
TERRA_MOON = (255, 226, 198)


# @skinlab {"type":"number","label":"Dome size","group":"Layout","min":0.26,"max":0.5,"step":0.01}
TERRA_DOME_R = 0.38


# @skinlab {"type":"integer","label":"Dome ribs","group":"Layout","min":0,"max":12,"step":1}
TERRA_RIBS = 7


# @skinlab {"type":"integer","label":"Dust haze","group":"Look","min":0,"max":30,"step":2}
TERRA_HAZE = 16


# @skinlab {"type":"number","label":"Vent speed","group":"Motion","min":0.25,"max":4,"step":0.25}
TERRA_VENT_SPEED = 1.0


# @skinlab {"type":"integer","label":"Vent puffs","group":"Layout","min":0,"max":6,"step":1}
TERRA_VENTS = 6


# @skinlab {"type":"integer","label":"Blowing dust","group":"Layout","min":0,"max":4,"step":1}
TERRA_DUST = 4


# @skinlab {"type":"integer","label":"Haze bands","group":"Layout","min":0,"max":3,"step":1}
TERRA_HAZE_BANDS = 3


# @skinlab {"type":"boolean","label":"Traffic","group":"Motion"}
TERRA_TRAFFIC = True


def _terraform_geom(w, h):
    """Horizon, dome centre and dome radius."""
    return int(h * 0.66), int(w * 0.60), int(h * TERRA_DOME_R)


def _terraform(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, w // 160)          # hairlines keep their millimetres at HIRES
    hy, dx, R = _terraform_geom(w, h)

    # Sky, thick with dust toward the horizon.
    for y in range(hy):
        k = (y / max(1, hy - 1)) ** 0.8
        buf.pen = color.rgb(
            int(TERRA_SKY_HIGH[0] + (TERRA_SKY_LOW[0] - TERRA_SKY_HIGH[0]) * k),
            int(TERRA_SKY_HIGH[1] + (TERRA_SKY_LOW[1] - TERRA_SKY_HIGH[1]) * k),
            int(TERRA_SKY_HIGH[2] + (TERRA_SKY_LOW[2] - TERRA_SKY_HIGH[2]) * k),
        )
        buf.rectangle(0, y, w, 1)

    # Twin moons, high left, out of the way of everything.
    buf.pen = color.rgb(*TERRA_MOON)
    buf.circle(int(w * 0.17), int(h * 0.13), u * 2)
    buf.pen = color.rgb(TERRA_SKY_HIGH[0] + 40, TERRA_SKY_HIGH[1] + 24, TERRA_SKY_HIGH[2] + 40)
    buf.circle(int(w * 0.17) - u, int(h * 0.13) - u // 2, int(u * 1.5))
    buf.pen = color.rgb(TERRA_MOON[0], TERRA_MOON[1], TERRA_MOON[2], 190)
    buf.circle(int(w * 0.30), int(h * 0.07), max(1, u))

    # Ground, darkening toward the wearer.
    for y in range(hy, h):
        k = (y - hy) / max(1, h - hy - 1)
        buf.pen = color.rgb(
            int(TERRA_SAND[0] + (TERRA_SAND_DARK[0] - TERRA_SAND[0]) * k),
            int(TERRA_SAND[1] + (TERRA_SAND_DARK[1] - TERRA_SAND[1]) * k),
            int(TERRA_SAND[2] + (TERRA_SAND_DARK[2] - TERRA_SAND[2]) * k),
        )
        buf.rectangle(0, y, w, 1)

    # A halo of lit dust around the dome — thin enough alpha to stay a glow.
    buf.pen = color.rgb(TERRA_DOME_LIT[0], TERRA_DOME_LIT[1], TERRA_DOME_LIT[2], TERRA_HAZE)
    buf.circle(dx, hy, R + u * 3)

    # The dome: a lit crescent, then the glass over it, offset down-right.
    buf.pen = color.rgb(*TERRA_DOME_LIT)
    buf.circle(dx, hy, R)
    buf.pen = color.rgb(*TERRA_DOME)
    buf.circle(dx + s * 2, hy + s * 2, R)

    # What grows inside, seen through the lower glass — below the name band.
    step = max(1, R // 7)
    y = hy - int(R * 0.44)
    while y < hy:
        dy = y - hy
        half = int(math.sqrt(max(0.0, R * R - dy * dy)))
        k = (y - (hy - R * 0.44)) / max(1.0, R * 0.44)
        buf.pen = color.rgb(
            int(TERRA_DOME[0] + (TERRA_INNER[0] - TERRA_DOME[0]) * k),
            int(TERRA_DOME[1] + (TERRA_INNER[1] - TERRA_DOME[1]) * k),
            int(TERRA_DOME[2] + (TERRA_INNER[2] - TERRA_DOME[2]) * k),
        )
        buf.rectangle(dx - half + u, y, half * 2 - u * 2, step)
        y += step

    # Canopy shadows inside the glass: scatter, different primes per axis.
    for i in range(9):
        px = dx - R + (i * 47) % max(1, R * 2)
        py = hy - u - (i * 13) % max(1, int(R * 0.34))
        buf.pen = color.rgb(12, 60, 44)
        buf.rectangle(px, py, max(1, u // 2), max(2, u))

    # Ribs: hemisphere meridians, drawn only on the lower half so the crown
    # stays a clean sheet of glare where the badge puts the name.
    buf.pen = color.rgb(TERRA_DOME_LIT[0], TERRA_DOME_LIT[1], TERRA_DOME_LIT[2], 150)
    for j in range(TERRA_RIBS):
        th = -math.pi / 2 + math.pi * (j + 0.5) / max(1, TERRA_RIBS)
        px, py = dx + int(R * math.sin(th)), hy
        for k in range(1, 5):
            p = k / 6.0
            qx = dx + int(R * math.sin(th) * math.cos(p * math.pi / 2))
            qy = hy - int(R * math.sin(p * math.pi / 2))
            if qy > h * 0.55:
                buf.line(px, py, qx, qy)
            px, py = qx, qy

    # One latitude ring low on the dome, and the foundation it stands on.
    ry = hy - int(R * 0.30)
    rh = int(math.sqrt(max(0.0, R * R - (ry - hy) ** 2)))
    buf.pen = color.rgb(TERRA_DOME_LIT[0], TERRA_DOME_LIT[1], TERRA_DOME_LIT[2], 120)
    buf.rectangle(dx - rh, ry, rh * 2, s)
    buf.pen = color.rgb(198, 186, 176)
    buf.rectangle(dx - R, hy - u, R * 2, u)
    buf.pen = color.rgb(*TERRA_SAND_DARK)
    buf.rectangle(dx - R, hy, R * 2, max(1, u // 2))

    # Atmosphere processors, left of the dome.
    for i, (fx, fh, fw) in enumerate(((0.10, 0.30, 0.05), (0.24, 0.21, 0.035))):
        tx = int(w * fx)
        top = hy - int(h * fh)
        tw = max(2, int(w * fw))
        buf.pen = color.rgb(*TERRA_TOWER)
        buf.triangle(tx - tw, hy, tx + tw, hy, tx + tw - u, top)
        buf.triangle(tx - tw, hy, tx + tw - u, top, tx - tw + u, top)
        buf.rectangle(tx - tw, top - max(2, u), tw * 2, max(2, u))
        buf.pen = color.rgb(255, 90, 70)
        buf.rectangle(tx - max(1, s), top - max(2, u) - s * 2, s * 2, s * 2)

    # Dunes and rocks in the near desert.
    for i in range(11):
        rx = (i * 137) % w
        ry2 = hy + u * 2 + (i * 61) % max(1, h - hy - u * 2)
        buf.pen = color.rgb(TERRA_SAND_DARK[0] + 22, TERRA_SAND_DARK[1] + 10, TERRA_SAND_DARK[2] + 8)
        buf.rectangle(rx, ry2, u * (2 + i % 3), max(1, s * 2))
    buf.pen = color.rgb(36, 15, 16)
    for i in range(12):
        bx = i * (w // 12)
        buf.rectangle(bx, h - u - int(u * math.sin(i * 1.1)), w // 12 + 1, u * 3)


def _terraform_a(buf, t):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, w // 160)
    hy, dx, R = _terraform_geom(w, h)

    # Vent plumes climbing off the processors. Each puff ends at alpha 0, so
    # the one that restarts at the stack head has nothing to snap away from.
    for i in range(max(0, TERRA_VENTS)):
        p = (t * TERRA_VENT_SPEED + i * 0.17) % 1.0
        tx = int(w * (0.10 if i % 2 else 0.24))
        top = hy - int(h * (0.30 if i % 2 else 0.21))
        y = top - int(h * 0.16 * p)
        buf.pen = color.rgb(240, 210, 190, int(160 * (1.0 - p)))
        buf.circle(tx + int(u * math.sin(p * 3.0 + i)), y, max(1, int(u * (0.6 + 1.6 * p))))

    # Dust drifting across the desert floor.
    for i in range(max(0, TERRA_DUST)):
        p = (t + i / float(max(1, TERRA_DUST))) % 1.0
        buf.pen = color.rgb(238, 176, 132, 90)
        buf.rectangle(int(w * (p * 1.2 - 0.1)), hy + u * (3 + (i % 2) * 4), u * 6, max(1, s))

    # A dust devil turning over in the near desert, well below the name band.
    dv = (t * 2) % 1.0
    buf.pen = color.rgb(228, 168, 128, int(140 * (1.0 - dv)))
    buf.rectangle(int(w * (0.40 + 0.22 * dv)) + int(u * math.sin(dv * 9.0)),
                  int(h * 0.86) - int(h * 0.10 * dv), max(1, s * 2),
                  max(2, int(u * (1.0 + 2.0 * dv))))

    # Dust haze sliding across the high sky, above the band.
    span = w + u * 10
    for i in range(max(0, TERRA_HAZE_BANDS)):
        x = -u * 5 + ((i * 137) % span + int(t * span)) % span
        buf.pen = color.rgb(TERRA_SKY_LOW[0], TERRA_SKY_LOW[1], TERRA_SKY_LOW[2], 46)
        buf.rectangle(x, int(h * (0.05 + 0.055 * i)), u * (8 + i * 2), max(1, u // 2))

    # Traffic: a rover crossing the near desert with its lamp on, and a second
    # craft high in the sky going the other way from the shuttle.
    if TERRA_TRAFFIC:
        rp = (t + 0.35) % 1.0
        rx = int(w * (1.06 - 1.14 * rp))
        ry = int(h * 0.90)
        buf.pen = color.rgb(*TERRA_TOWER)
        buf.rectangle(rx, ry, max(2, u), max(1, u // 2 + 1))
        buf.pen = color.rgb(255, 240, 190, 230)
        buf.rectangle(rx - max(1, u // 2), ry, max(1, s * 2), max(1, s * 2))
        cp = (t + 0.6) % 1.0
        cx2 = int(w * (-0.06 + 1.14 * cp))
        buf.pen = color.rgb(220, 232, 255, 190)
        buf.rectangle(cx2, int(h * (0.17 - 0.03 * cp)), max(2, u), max(1, s))

    # A gleam runs the dome's foundation ring — the one part of the glass that
    # is safely below the band.
    gp = 0.5 - 0.5 * math.cos(t * 2 * math.pi)
    buf.pen = color.rgb(255, 255, 255, 210)
    buf.rectangle(dx - R + int(R * 2 * gp) - u, hy - u, u * 2, max(1, s * 2))
    buf.pen = color.rgb(TERRA_DOME_LIT[0], TERRA_DOME_LIT[1], TERRA_DOME_LIT[2], 110)
    buf.rectangle(dx - R + int(R * 2 * gp) - u * 2, hy - u, u * 4, max(1, s))

    # Lights coming on inside the dome.
    for i in range(3):
        if ((t * 2 + i * 0.31) % 1.0) < 0.45:
            buf.pen = color.rgb(220, 255, 214, 220)
            buf.rectangle(dx - R + u * 3 + i * (R // 2), hy - u * 2 - (i % 2) * u, s * 2, s * 2)

    # A shuttle crossing the sky, with a short trail.
    p = (t * 1.0) % 1.0
    sx = int(w * (1.05 - 1.15 * p))
    sy = int(h * (0.10 + 0.06 * p))
    buf.pen = color.rgb(255, 240, 220, 200)
    buf.line(sx, sy, sx + u * 3, sy - u)
    buf.pen = color.rgb(255, 255, 255, 240)
    buf.rectangle(sx, sy, s * 2, s * 2)

# ── VISOR ───────────────────────────────────────────
# VISOR — the inside of an exosuit helmet: dark chrome around a letterbox of

# @skinlab {"type":"color","label":"Helmet shell","group":"Palette"}
VISOR_SHELL = (42, 46, 60)


# @skinlab {"type":"color","label":"Shell rim light","group":"Palette"}
VISOR_SHELL_LIT = (158, 172, 198)


# @skinlab {"type":"color","label":"Glass (top)","group":"Palette"}
VISOR_GLASS_TOP = (5, 8, 20)


# @skinlab {"type":"color","label":"Glass (low)","group":"Palette"}
VISOR_GLASS_LOW = (10, 34, 54)


# @skinlab {"type":"color","label":"HUD ink","group":"Palette"}
VISOR_HUD = (92, 255, 226)


# @skinlab {"type":"color","label":"Warning","group":"Palette"}
VISOR_WARN = (255, 176, 48)


# @skinlab {"type":"color","label":"Contact","group":"Palette"}
VISOR_TARGET = (228, 246, 255)


# @skinlab {"type":"number","label":"Aperture height","group":"Layout","min":0.5,"max":0.82,"step":0.01}
VISOR_APERTURE = 0.72


# @skinlab {"type":"integer","label":"Heading ticks","group":"Layout","min":4,"max":14,"step":1}
VISOR_TICKS = 9


# @skinlab {"type":"integer","label":"Power segments","group":"Layout","min":4,"max":14,"step":1}
VISOR_BARS = 9


# @skinlab {"type":"number","label":"Scan sweep","group":"Motion","min":0.25,"max":4,"step":0.25}
VISOR_SCAN_SPEED = 1.0


# @skinlab {"type":"integer","label":"Telemetry blips","group":"Layout","min":0,"max":4,"step":1}
VISOR_BLIPS = 3


# @skinlab {"type":"integer","label":"City lights","group":"Layout","min":0,"max":4,"step":1}
VISOR_CITY = 3


# @skinlab {"type":"boolean","label":"Horizon line","group":"Motion"}
VISOR_HORIZON = True


# @skinlab {"type":"boolean","label":"Heading bug","group":"Motion"}
VISOR_BUG = True


# @skinlab {"type":"text","label":"Top readout","group":"Details"}
VISOR_LABEL = "O2 98"


# @skinlab {"type":"text","label":"Bottom readout","group":"Details"}
VISOR_STATUS = "SYS OK"


# @skinlab {"type":"boolean","label":"Bloom the glass","group":"Look"}
VISOR_BLOOM = False


def _visor_glass(w, h):
    """Aperture rect: left, top, right, bottom."""
    return int(w * 0.07), int(h * 0.10), int(w * 0.93), int(h * (0.10 + VISOR_APERTURE))


def _visor_bracket(buf, x, y, arm, thick, sx, sy):
    """One L-shaped corner bracket, opening toward (sx, sy)."""
    buf.rectangle(x if sx > 0 else x - arm, y - (0 if sy > 0 else thick), arm, thick)
    buf.rectangle(x - (0 if sx > 0 else thick), y if sy > 0 else y - arm, thick, arm)


def _visor(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, w // 160)          # hairlines keep their millimetres at HIRES
    gx0, gy0, gx1, gy1 = _visor_glass(w, h)

    # Everything outside is glass first; the shell is painted over it after,
    # so the view can be drawn without clipping.
    for y in range(h):
        k = y / max(1, h - 1)
        buf.pen = color.rgb(
            int(VISOR_GLASS_TOP[0] + (VISOR_GLASS_LOW[0] - VISOR_GLASS_TOP[0]) * k),
            int(VISOR_GLASS_TOP[1] + (VISOR_GLASS_LOW[1] - VISOR_GLASS_TOP[1]) * k),
            int(VISOR_GLASS_TOP[2] + (VISOR_GLASS_LOW[2] - VISOR_GLASS_TOP[2]) * k),
        )
        buf.rectangle(0, y, w, 1)

    # Out there: a lit planet curving under a black sky, city lights on it.
    pcy = int(h * 1.62)
    buf.pen = color.rgb(255, 255, 255, 110)
    buf.circle(int(w * 0.38), pcy - s * 2, int(w * 0.78))
    buf.pen = color.rgb(38, 92, 118)
    buf.circle(int(w * 0.38), pcy, int(w * 0.78))
    buf.pen = color.rgb(20, 54, 76)
    buf.circle(int(w * 0.30), pcy + int(h * 0.10), int(w * 0.72))
    for i in range(9):
        buf.pen = color.rgb(VISOR_TARGET[0], VISOR_TARGET[1], VISOR_TARGET[2], 130 + (i * 31) % 110)
        buf.rectangle((i * 137) % w, int(h * 0.70) + (i * 29) % max(1, int(h * 0.10)), s, s)

    # The helmet: shell over everything outside the aperture, then bevels.
    # The brow is lit from above and the chin falls away, which is what makes
    # a flat frame read as a curved shell.
    for y in range(gy0):
        k = 1.0 - y / max(1, gy0)
        buf.pen = color.rgb(int(VISOR_SHELL[0] * (0.5 + 0.9 * k)),
                            int(VISOR_SHELL[1] * (0.5 + 0.9 * k)),
                            int(VISOR_SHELL[2] * (0.5 + 0.9 * k)))
        buf.rectangle(0, y, w, 1)
    for y in range(gy1, h):
        k = (y - gy1) / max(1, h - gy1)
        buf.pen = color.rgb(int(VISOR_SHELL[0] * (1.0 - 0.65 * k)),
                            int(VISOR_SHELL[1] * (1.0 - 0.65 * k)),
                            int(VISOR_SHELL[2] * (1.0 - 0.65 * k)))
        buf.rectangle(0, y, w, 1)
    buf.pen = color.rgb(*VISOR_SHELL)
    buf.rectangle(0, 0, gx0, h)
    buf.rectangle(gx1, 0, w - gx1, h)
    # Chin vents.
    buf.pen = color.rgb(int(VISOR_SHELL[0] * 0.4), int(VISOR_SHELL[1] * 0.4), int(VISOR_SHELL[2] * 0.4))
    for i in range(3):
        buf.rectangle(w // 2 - u * 5 + i * u * 4, gy1 + u * 3, u * 3, max(2, u))
    # Deep bevels: a visor aperture is a wide, shallow, heavily rounded
    # letterbox, and that outline is the whole silhouette at thumbnail size.
    buf.pen = color.rgb(*VISOR_SHELL)
    bev = u * 5
    for k in (0, 1):
        wide, tall = bev * (2 + k), bev * (2 - k) // 2 + bev // 2
        buf.triangle(gx0, gy0, gx0 + wide, gy0, gx0, gy0 + tall)
        buf.triangle(gx1, gy0, gx1 - wide, gy0, gx1, gy0 + tall)
        buf.triangle(gx0, gy1, gx0 + wide + bev, gy1, gx0, gy1 - tall - bev // 2)
        buf.triangle(gx1, gy1, gx1 - wide - bev, gy1, gx1, gy1 - tall - bev // 2)

    # Rim light along the shell, and a brow shadow above the glass.
    buf.pen = color.rgb(*VISOR_SHELL_LIT)
    buf.rectangle(0, gy0 - s * 2, w, s * 2)
    buf.rectangle(0, gy1, w, s)
    buf.pen = color.rgb(20, 22, 30)
    buf.rectangle(0, gy0 - u, w, s * 2)
    buf.rectangle(0, gy1 + u * 2, w, s * 2)

    # Rivets down the seal. Nothing says helmet like fasteners.
    for i in range(6):
        rx = int(w * (0.08 + 0.168 * i))
        for ry in (max(1, gy0 // 2), gy1 + u * 5):
            buf.pen = color.rgb(*VISOR_SHELL_LIT)
            buf.circle(rx, ry, max(1, u // 2))
            buf.pen = color.rgb(18, 20, 28)
            buf.circle(rx, ry, max(1, u // 4))

    # HUD: corner brackets just inside the glass.
    buf.pen = color.rgb(*VISOR_HUD)
    arm, thick = u * 5, s * 2
    _visor_bracket(buf, gx0 + u, gy0 + u, arm, thick, 1, 1)
    _visor_bracket(buf, gx1 - u, gy0 + u, arm, thick, -1, 1)
    _visor_bracket(buf, gx0 + u, gy1 - u, arm, thick, 1, -1)
    _visor_bracket(buf, gx1 - u, gy1 - u, arm, thick, -1, -1)

    # Heading tape along the top of the glass — dense detail, kept above 0.24h.
    ty = gy0 + u * 2
    span = (gx1 - gx0) - u * 12
    for i in range(VISOR_TICKS):
        x = gx0 + u * 6 + span * i // max(1, VISOR_TICKS - 1)
        tall = u * 2 if i % 3 == 0 else u
        buf.rectangle(x, ty, s * 2, tall)
    buf.pen = color.rgb(*VISOR_WARN)
    buf.triangle(w // 2, ty + u * 3, w // 2 - u, ty + u * 5, w // 2 + u, ty + u * 5)

    # Power tape along the bottom of the glass — below 0.62h.
    by = gy1 - u * 4
    seg = span // max(1, VISOR_BARS)
    for i in range(VISOR_BARS):
        lit = i < VISOR_BARS - 2
        buf.pen = color.rgb(*(VISOR_HUD if lit else VISOR_WARN))
        buf.rectangle(gx0 + u * 6 + i * seg, by, max(2, seg - s * 2), u)

    # The contact and its lock bracket, low right, clear of the name band.
    tx, tyy = int(w * 0.73), int(h * 0.70)
    buf.pen = color.rgb(*VISOR_TARGET)
    buf.rectangle(tx - u, tyy, u * 2, max(1, s * 2))
    buf.rectangle(tx - max(1, s), tyy - u, s * 2, u * 2)
    buf.pen = color.rgb(*VISOR_HUD)
    lock, lt = u * 2, s * 2
    _visor_bracket(buf, tx - u * 3, tyy - u * 3, lock, lt, 1, 1)
    _visor_bracket(buf, tx + u * 3, tyy - u * 3, lock, lt, -1, 1)
    _visor_bracket(buf, tx - u * 3, tyy + u * 3, lock, lt, 1, -1)
    _visor_bracket(buf, tx + u * 3, tyy + u * 3, lock, lt, -1, -1)

    # A sheen was tried across the glass and cut: even at alpha 16 a shape that
    # size reads as a grey plate over the artwork rather than as reflection.

    # Small type is chrome, not a paragraph: two short tokens, top and bottom.
    # ROM faces are fixed pixel heights, so a 12 px line that is chrome on the
    # badge would be a third of a 40x30 contact-sheet cell. Measure first and
    # only draw the readout where it stays small against the canvas.
    try:
        buf.font = font.sins
        tw, th = buf.measure_text(VISOR_LABEL)
        if int(th) * 8 <= h:
            buf.pen = color.rgb(*VISOR_HUD)
            buf.text(VISOR_LABEL, gx0 + u * 2, gy0 + u * 5)
            buf.pen = color.rgb(*VISOR_WARN)
            buf.text(VISOR_STATUS, gx1 - u * 11, gy1 - u * 9)
    except Exception:
        pass

    if VISOR_BLOOM:
        buf.bloom()


def _visor_a(buf, t):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, w // 160)
    gx0, gy0, gx1, gy1 = _visor_glass(w, h)

    # The scan sweep crosses the glass once per loop — one way, because that is
    # what a scan does — but it comes up out of nothing at the brow and is gone
    # again by the chin. Without that fade it was the largest single-frame jump
    # in the catalogue: a full-width bar teleporting from bottom to top.
    p = (t * VISOR_SCAN_SPEED) % 1.0
    sy = gy0 + int((gy1 - gy0) * p)
    fade = math.sin(math.pi * p)
    buf.pen = color.rgb(VISOR_HUD[0], VISOR_HUD[1], VISOR_HUD[2], int(180 * fade))
    buf.rectangle(gx0 + u, sy, gx1 - gx0 - u * 2, s * 2)
    buf.pen = color.rgb(VISOR_HUD[0], VISOR_HUD[1], VISOR_HUD[2], int(72 * fade))
    buf.rectangle(gx0 + u, sy - u * 2, gx1 - gx0 - u * 2, u * 2)

    # The lock spins four ticks around the contact.
    tx, tyy = int(w * 0.73), int(h * 0.70)
    a0 = t * 2 * math.pi
    buf.pen = color.rgb(255, 255, 255, 235)
    for i in range(4):
        a = a0 + i * math.pi / 2
        buf.rectangle(tx + int(u * 4.5 * math.cos(a)), tyy + int(u * 4.5 * math.sin(a)), s * 2, s * 2)

    # Power level jitters at the head of the tape; the warn segment blinks.
    span = (gx1 - gx0) - u * 12
    seg = span // max(1, VISOR_BARS)
    lvl = int(abs(math.sin(t * 2 * math.pi)) * 2)
    buf.pen = color.rgb(*VISOR_HUD)
    buf.rectangle(gx0 + u * 6 + (VISOR_BARS - 1 - lvl) * seg, gy1 - u * 4, max(2, seg - s * 2), u)
    if int(t * 8) % 2 == 0:
        buf.pen = color.rgb(*VISOR_WARN)
        buf.circle(gx1 - u * 3, gy0 + u * 3, max(1, u // 2))

    # The contact drifts a little, so the bracket has something to hold.
    dx = int(u * math.sin(t * 2 * math.pi))
    buf.pen = color.rgb(*VISOR_TARGET)
    buf.rectangle(tx - u + dx, tyy, u * 2, max(1, s * 2))

    # The heading tape belongs to render(), so what moves is the BUG on it and
    # the ticks it is passing. Redrawing the tape shifted would leave the
    # static one showing underneath and read as a smear.
    if VISOR_BUG:
        # A full cosine: the head turns and turns back. Half of one would put
        # the bug at the far end of the tape at t = 1 and snap it home.
        hp = 0.5 - 0.5 * math.cos(t * 2 * math.pi)
        bx = gx0 + u * 6 + int(span * hp)
        buf.pen = color.rgb(*VISOR_WARN)
        buf.triangle(bx, gy0 + u * 2, bx - u, gy0 + u * 4, bx + u, gy0 + u * 4)
        buf.pen = color.rgb(255, 255, 255, 220)
        buf.rectangle(bx - s, gy0 + u * 2, s * 2, u * 2)
        for i in range(3):
            j = int(hp * max(1, VISOR_TICKS - 1)) + i - 1
            if j < 0 or j >= VISOR_TICKS:
                continue
            buf.pen = color.rgb(255, 255, 255, 230 - abs(i - 1) * 110)
            buf.rectangle(gx0 + u * 6 + span * j // max(1, VISOR_TICKS - 1),
                          gy0 + u * 2, s * 2, u * 2)

    # An attitude line rolling behind everything: wide and slow, which is the
    # one kind of motion the name band takes without shouting.
    if VISOR_HORIZON:
        roll = math.sin(t * 2 * math.pi) * 0.10
        my = (gy0 + gy1) // 2
        buf.pen = color.rgb(VISOR_HUD[0], VISOR_HUD[1], VISOR_HUD[2], 90)
        buf.line(gx0 + u, my + int((gx1 - gx0) * 0.5 * roll),
                 gx1 - u, my - int((gx1 - gx0) * 0.5 * roll))
        buf.pen = color.rgb(VISOR_HUD[0], VISOR_HUD[1], VISOR_HUD[2], 150)
        buf.rectangle(w // 2 - s, my - s, s * 2, s * 2)

    # Telemetry arriving in the top-left corner, one line at a time.
    for i in range(max(0, VISOR_BLIPS)):
        k = (t * 3 + i * 0.31) % 1.0
        buf.pen = color.rgb(VISOR_HUD[0], VISOR_HUD[1], VISOR_HUD[2],
                            int(240 * (1.0 - k)))
        buf.rectangle(gx0 + u * 2, gy0 + u * 6 + i * (u + s), u * (2 + i % 3), s * 2)

    # A second contact acquired and lost again, low and left of the first: the
    # brackets close on it as it fades up and it is gone by the time they meet,
    # so there is nothing left on screen to snap away at the wrap.
    ap = (t * 2) % 1.0
    fade = int(230 * math.sin(math.pi * ap))
    ax, ay = int(w * 0.24), int(h * 0.72)
    buf.pen = color.rgb(VISOR_TARGET[0], VISOR_TARGET[1], VISOR_TARGET[2], fade)
    buf.rectangle(ax - s, ay - s, s * 2, s * 2)
    rr = u + int(u * 2 * (1.0 - ap))
    buf.pen = color.rgb(VISOR_HUD[0], VISOR_HUD[1], VISOR_HUD[2], fade)
    buf.rectangle(ax - rr, ay - rr, rr * 2, max(1, s))
    buf.rectangle(ax - rr, ay + rr, rr * 2, max(1, s))

    # City lights out there, coming on and going off as the ship passes over.
    for i in range(max(0, VISOR_CITY)):
        k = 0.5 + 0.5 * math.sin((t + i * 0.27) * 4 * math.pi)
        buf.pen = color.rgb(VISOR_TARGET[0], VISOR_TARGET[1], VISOR_TARGET[2],
                            int(30 + 210 * k * k))
        buf.rectangle(int(w * (0.14 + 0.17 * i)) + (i * 29) % max(1, u * 2),
                      int(h * 0.735) + (i * 13) % max(1, int(h * 0.06)), s * 2, s * 2)


# ── VERCEL ───────────────────────────────────────────
# The white Vercel triangle on black, mid-deploy: light climbs the mark and runners trace its slopes.

# @skinlab {"type":"color","label":"Field","group":"Palette"}
VRC_FIELD = (0, 0, 0)


# @skinlab {"type":"color","label":"Field lift","group":"Palette"}
VRC_LIFT = (26, 26, 26)


# @skinlab {"type":"color","label":"Grid","group":"Palette"}
VRC_GRID = (28, 28, 28)


# @skinlab {"type":"color","label":"Mark","group":"Palette"}
VRC_MARK = (255, 255, 255)


# @skinlab {"type":"color","label":"Deploy (start)","group":"Palette"}
VRC_SWEEP_A = (0, 112, 243)


# @skinlab {"type":"color","label":"Deploy (end)","group":"Palette"}
VRC_SWEEP_B = (248, 28, 229)


# @skinlab {"type":"number","label":"Mark width","group":"Layout","min":0.5,"max":0.98,"step":0.01}
VRC_TRI_W = 0.74


# @skinlab {"type":"number","label":"Mark top","group":"Layout","min":0.0,"max":0.2,"step":0.01}
VRC_TRI_Y = 0.14


# @skinlab {"type":"integer","label":"Halo steps","group":"Shape","min":0,"max":4,"step":1}
VRC_HALO = 2


# @skinlab {"type":"integer","label":"Grid cell","group":"Look","min":2,"max":10,"step":1}
VRC_GRID_CELL = 4


# @skinlab {"type":"integer","label":"Deploy trail","group":"Motion","min":0,"max":5,"step":1}
VRC_BANDS = 2


# @skinlab {"type":"number","label":"Front depth","group":"Motion","min":0.02,"max":0.14,"step":0.005}
VRC_BAND_H = 0.03


# @skinlab {"type":"integer","label":"Deploy laps","group":"Motion","min":1,"max":4,"step":1}
VRC_BAND_LAPS = 2


# @skinlab {"type":"integer","label":"Edge runners","group":"Motion","min":0,"max":3,"step":1}
VRC_EDGE_RUNS = 2


# @skinlab {"type":"number","label":"Runner length","group":"Motion","min":0.08,"max":0.5,"step":0.02}
VRC_EDGE_LEN = 0.22


# @skinlab {"type":"integer","label":"Runner laps","group":"Motion","min":1,"max":4,"step":1}
VRC_EDGE_LAPS = 2


# @skinlab {"type":"integer","label":"Log scans","group":"Motion","min":0,"max":4,"step":1}
VRC_SCANS = 2


# @skinlab {"type":"integer","label":"Edge nodes","group":"Motion","min":0,"max":6,"step":1}
VRC_NODES = 4


# @skinlab {"type":"integer","label":"Node laps","group":"Motion","min":1,"max":4,"step":1}
VRC_NODE_LAPS = 2


# @skinlab {"type":"integer","label":"Grid sweep laps","group":"Motion","min":0,"max":4,"step":1}
VRC_SWEEP_LAPS = 1


# @skinlab {"type":"boolean","label":"Base bloom","group":"Details"}
VRC_BLOOM = True


def _vercel_unit(buf):
    """A fortieth of the width: composition, so the picture is the same shape
    on the 40x30 thumbnail, the 160x120 panel and the 320x240 one."""
    return max(1, buf.width // 40)


def _vercel_stroke(buf):
    """A hairline that keeps its millimetres when the panel doubles."""
    return max(1, buf.width // 160)


def _vercel_mark(buf):
    """Centre x, apex y, base y, half-base -- the one source of the geometry."""
    w, h = buf.width, buf.height
    base = VRC_TRI_W * w
    tall = base * 0.8660254
    top = VRC_TRI_Y * h
    return w * 0.5, top, top + tall, base * 0.5


def _vercel_mix(a, b, k):
    if k < 0.0:
        k = 0.0
    elif k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _vercel_slab(buf, cx, top, tall, half, y0, y1):
    """The horizontal slice of the mark between two rows, exactly inscribed in
    it -- so light can cross the symbol without ever changing its silhouette.
    Two triangles sharing a diagonal; `line()` cannot do this and a rectangle
    would overhang the slope."""
    bot = top + tall
    if y0 < top:
        y0 = top
    if y1 > bot:
        y1 = bot
    if y1 < y0:
        y1 = y0
    k0 = (y0 - top) / tall
    k1 = (y1 - top) / tall
    a0, b0, ry0 = int(cx - half * k0), int(cx + half * k0), int(y0)
    a1, b1, ry1 = int(cx - half * k1), int(cx + half * k1), int(y1)
    buf.triangle(a0, ry0, b0, ry0, b1, ry1)
    buf.triangle(a0, ry0, b1, ry1, a1, ry1)


def _vercel_edge(buf, cx, top, tall, half, side, f0, f1, thick):
    """A slice of one of the mark's two slopes, drawn just OUTSIDE it, f being
    the fraction of the way up from the base corner to the apex. A slanted
    stroke is neither a `line()` (always 1 px) nor a `rectangle()`, so it is a
    rotated quad: two triangles sharing a diagonal."""
    if f0 < 0.0:
        f0 = 0.0
    if f1 > 1.0:
        f1 = 1.0
    if f1 < f0:
        f1 = f0
    bot = top + tall
    x0, y0 = cx + side * half * (1.0 - f0), bot - tall * f0
    x1, y1 = cx + side * half * (1.0 - f1), bot - tall * f1
    o = side * thick
    buf.triangle(int(x0), int(y0), int(x0 + o), int(y0), int(x1 + o), int(y1))
    buf.triangle(int(x0), int(y0), int(x1 + o), int(y1), int(x1), int(y1))


def _vercel(buf):
    w, h = buf.width, buf.height
    u, s = _vercel_unit(buf), _vercel_stroke(buf)

    buf.pen = color.rgb(*VRC_FIELD)
    buf.clear()

    # the field is not flat black: Geist's dark surfaces carry a little light
    # at the top and fall away to #000. Banded rather than one rect per row --
    # the whole ramp is under 30 levels, so half a unit per step is smooth and
    # costs the same handful of calls at every canvas size.
    step = max(1, u // 2)
    for y in range(0, h, step):
        k = 1.0 - y / max(1, h - 1)
        k = k * k
        buf.pen = color.rgb(int(VRC_FIELD[0] + (VRC_LIFT[0] - VRC_FIELD[0]) * k),
                            int(VRC_FIELD[1] + (VRC_LIFT[1] - VRC_FIELD[1]) * k),
                            int(VRC_FIELD[2] + (VRC_LIFT[2] - VRC_FIELD[2]) * k))
        buf.rectangle(0, y, w, step)

    # the platform grid, barely above the background the way it is on the site
    cell = max(2, u * VRC_GRID_CELL)
    buf.pen = color.rgb(*VRC_GRID)
    for x in range(cell // 2, w, cell):
        buf.rectangle(x, 0, s, h)
    for y in range(cell // 2, h, cell):
        buf.rectangle(0, y, w, s)

    cx, top, bot, half = _vercel_mark(buf)

    # a soft edge glow OUTSIDE the symbol -- drawn first and then covered by
    # the mark, so only its rim survives and the symbol itself stays pure
    # white. Pre-mixed against the field rather than drawn with alpha: these
    # are large shapes and a blended fill of this size is the one thing in the
    # skin that measurably costs.
    for i in range(VRC_HALO):
        g = (VRC_HALO - i) * u * 1.1
        tone = _vercel_mix(VRC_FIELD, VRC_SWEEP_A, 0.14 + i * 0.16)
        buf.pen = color.rgb(tone[0], tone[1], tone[2])
        buf.triangle(int(cx), int(top - g * 1.15),
                     int(cx - half - g), int(bot + g * 0.6),
                     int(cx + half + g), int(bot + g * 0.6))

    # the symbol: equilateral, apex up, one flat colour, no effects
    buf.pen = color.rgb(*VRC_MARK)
    buf.triangle(int(cx), int(top), int(cx - half), int(bot), int(cx + half), int(bot))


def _vercel_a(buf, t):
    """A deploy in flight. A front of light climbs the inside of the symbol,
    blue at the base grading to magenta at the apex; runners trace the two
    slopes up to it; the ground under the mark blooms as each one lands; and
    behind all of it the build log scans down, a column of the grid lights as
    the network sweeps across, and edge regions wake in the top corners."""
    w, h = buf.width, buf.height
    u, s = _vercel_unit(buf), _vercel_stroke(buf)
    cx, top, bot, half = _vercel_mark(buf)
    tall = bot - top

    # the log streaming down the field: broad, slow, low contrast, and the one
    # thing deliberately allowed to cross the band the wearer's name occupies
    for i in range(VRC_SCANS):
        p = (t + i / max(1, VRC_SCANS)) % 1.0
        buf.pen = color.rgb(VRC_SWEEP_A[0], VRC_SWEEP_A[1], VRC_SWEEP_A[2],
                            8 + int(20 * math.sin(math.pi * p)))
        buf.rectangle(0, int(h * p), w, u)

    # regions of the edge network waking up in the two empty top corners. The
    # columns follow the grid; the rows do NOT, because the grid is a knob and
    # a coarse setting would drop these into the band the wearer's name sits in.
    cell = max(2, u * VRC_GRID_CELL)
    cols = max(1, w // cell)
    nd = max(1, s * 2)
    for i in range(VRC_NODES):
        col = (i * 2) % max(1, cols // 3)
        gx = cell // 2 + (col if i % 2 == 0 else cols - 1 - col) * cell
        gy = int(h * (0.06 + 0.12 * ((i // 2) % 2)))
        b = 0.5 + 0.5 * math.sin(2 * math.pi * (t * VRC_NODE_LAPS + i * 0.19))
        buf.pen = color.rgb(VRC_SWEEP_A[0], VRC_SWEEP_A[1], VRC_SWEEP_A[2],
                            50 + int(200 * b))
        buf.rectangle(gx, gy, nd, nd)

    # a single grid column lit up as the network sweeps across
    if VRC_SWEEP_LAPS:
        gx = int(w * ((t * VRC_SWEEP_LAPS) % 1.0))
        buf.pen = color.rgb(VRC_SWEEP_A[0], VRC_SWEEP_A[1], VRC_SWEEP_A[2], 85)
        buf.rectangle(gx, 0, max(1, s), h)

    # the deploy itself: ONE front of light climbing the INSIDE of the symbol,
    # a bright leader over a falling-alpha tail so it reads as light and not as
    # a stripe. Blue at the base grading to magenta at the apex -- the accent
    # pair out of Vercel's own gradient. Every slab is inscribed in the mark, so
    # the silhouette of the trademark never changes; only the light on it does.
    depth = max(1.0, VRC_BAND_H * h)
    # the travel is the mark PLUS the whole tail, so the front is fully clear of
    # the symbol at both p = 0 and p = 1 and the loop joins on an empty mark
    lead = bot - ((t * VRC_BAND_LAPS) % 1.0) * (
        tall + depth * (VRC_BANDS + 1) * 1.35)
    for k in range(VRC_BANDS, 0, -1):
        y0 = lead + depth * k * 1.35
        tone = _vercel_mix(VRC_SWEEP_A, VRC_SWEEP_B, 1.0 - (y0 - top) / tall)
        buf.pen = color.rgb(tone[0], tone[1], tone[2],
                            max(22, 190 - (k - 1) * 60))
        _vercel_slab(buf, cx, top, tall, half, y0, y0 + depth * 1.35)
    tone = _vercel_mix(VRC_SWEEP_A, VRC_SWEEP_B, 1.0 - (lead - top) / tall)
    buf.pen = color.rgb(tone[0], tone[1], tone[2])
    _vercel_slab(buf, cx, top, tall, half, lead, lead + depth * 1.35)

    # runners tracing the two slopes up to the apex: the edge network lighting
    # up. They sit just outside the symbol, so they glow against the field
    # instead of touching the trademark.
    thick = max(1, u // 2 + s)
    for j in range(VRC_EDGE_RUNS):
        p = (t * VRC_EDGE_LAPS + j / max(1, VRC_EDGE_RUNS)) % 1.0
        f1 = p * (1.0 + VRC_EDGE_LEN)
        tone = _vercel_mix(VRC_SWEEP_A, VRC_SWEEP_B, min(1.0, f1))
        buf.pen = color.rgb(tone[0], tone[1], tone[2], 205 + int(50 * p))
        _vercel_edge(buf, cx, top, tall, half, -1, f1 - VRC_EDGE_LEN, f1, thick)
        _vercel_edge(buf, cx, top, tall, half, 1, f1 - VRC_EDGE_LEN, f1, thick)

    # the ground under the mark blooms as each deploy lands
    if VRC_BLOOM:
        b = 0.5 + 0.5 * math.sin(2 * math.pi * (t * VRC_BAND_LAPS - 0.25))
        buf.pen = color.rgb(VRC_SWEEP_B[0], VRC_SWEEP_B[1], VRC_SWEEP_B[2],
                            14 + int(40 * b))
        buf.rectangle(int(cx - half) - u * 2, int(bot) - u,
                      int(half * 2) + u * 4, u * 2)

# ── STRIPE ───────────────────────────────────────────
# Stripe's wordmark in white on blurple, under a gradient banner cut at the brand's own angle.

# @skinlab {"type":"color","label":"Blurple","group":"Palette"}
STRP_BLURPLE = (83, 58, 253)


# @skinlab {"type":"color","label":"Wordmark","group":"Palette"}
STRP_MARK = (255, 255, 255)


# @skinlab {"type":"color","label":"Gradient 1","group":"Palette"}
STRP_G1 = (144, 224, 255)


# @skinlab {"type":"color","label":"Gradient 2","group":"Palette"}
STRP_G2 = (169, 96, 238)


# @skinlab {"type":"color","label":"Gradient 3","group":"Palette"}
STRP_G3 = (255, 51, 61)


# @skinlab {"type":"color","label":"Gradient 4","group":"Palette"}
STRP_G4 = (255, 203, 87)


# @skinlab {"type":"integer","label":"Banner angle","group":"Shape","min":0,"max":12,"step":1}
STRP_TILT = 6


# @skinlab {"type":"number","label":"Banner depth","group":"Layout","min":0.10,"max":0.24,"step":0.005}
STRP_BANNER = 0.20


# @skinlab {"type":"integer","label":"Banner slices","group":"Look","min":6,"max":24,"step":1}
STRP_SLICES = 24


# @skinlab {"type":"number","label":"Shine","group":"Look","min":0,"max":0.6,"step":0.05}
STRP_SHINE = 0.3


# @skinlab {"type":"boolean","label":"Stripe stream","group":"Details"}
STRP_STREAM_ON = True


# @skinlab {"type":"integer","label":"Stripes in the stream","group":"Details","min":3,"max":8,"step":1}
STRP_STREAM = 5


# @skinlab {"type":"integer","label":"Laps per loop","group":"Motion","min":-3,"max":3,"step":1}
STRP_FLOW = 1


# @skinlab {"type":"number","label":"Wordmark width","group":"Layout","min":0.55,"max":0.98,"step":0.01}
STRP_MARK_W = 0.92


# @skinlab {"type":"number","label":"Wordmark baseline","group":"Layout","min":0.90,"max":1.00,"step":0.005}
STRP_MARK_Y = 0.985


_STEM = 0.2869


_ADV = (0.0, 0.7817, 1.3680, 1.9406, 2.3337, 3.2651)


_TOTAL = 4.1143


def _stripe_i(v):
    return int(v + 0.5) if v >= 0 else int(v - 0.5)


def _stripe_capsule(buf, cx, cy, r, d):
    """A vertical stadium: two discs and the rectangle between them.

    The radius FLOORS rather than rounds. Rounding it up grows a bowl by half a
    pixel on each side, and at 40x30 that is exactly enough to close the gap
    between `p` and `e` and fuse the pair into one blob.
    """
    ri = int(r)
    if ri < 1:
        return
    di = _stripe_i(d)
    if ri < 2:
        # A one-pixel-radius disc rasterises as a plus, which is a strange
        # shape for a counter. At that size a rectangle is the honest circle.
        buf.rectangle(_stripe_i(cx) - ri, _stripe_i(cy) - di - ri, ri * 2 + 1, (di + ri) * 2 + 1)
        return
    buf.circle(_stripe_i(cx), _stripe_i(cy) - di, ri)
    buf.circle(_stripe_i(cx), _stripe_i(cy) + di, ri)
    if di > 0:
        buf.rectangle(_stripe_i(cx) - ri, _stripe_i(cy) - di, ri * 2 + 1, di * 2)


def _stripe_wordmark(buf, x0, top, H, tr, ink, bg):
    """The lowercase `stripe` wordmark. `top` is the x-height line.

    `tr` is hinting tracking: extra pixels between glyphs, zero at any size
    where the real sidebearings survive rounding and about a pixel at 40x30,
    where they do not and the six letters otherwise run into one white bar.
    """
    s = _STEM * H
    st = max(1, _stripe_i(s))
    base = top + H

    # s -- two fat discs, notched right at the top and left at the bottom. What
    # is left between the notches is the diagonal spine the real letter has.
    x = x0 + _ADV[0] * H
    w = 0.7257 * H
    r = w / 2.0
    cx = x + r
    cy1 = top - 0.019 * H + r
    cy2 = top + 1.021 * H - r
    slot = max(0.55, (r - s) * 0.80)
    lean = (r + slot) * 0.60 if slot >= 1.0 else 0.0
    right = _stripe_i(x + w) + 1
    buf.pen = ink
    buf.circle(_stripe_i(cx), _stripe_i(cy1), _stripe_i(r))
    buf.circle(_stripe_i(cx), _stripe_i(cy2), _stripe_i(r))
    buf.pen = bg
    buf.rectangle(_stripe_i(cx - slot), _stripe_i(cy1 - slot), _stripe_i(r + slot) + 2, max(1, _stripe_i(2 * slot)))
    buf.triangle(_stripe_i(cx), _stripe_i(cy1 + slot), right, _stripe_i(cy1 + slot),
                 right, _stripe_i(cy1 + slot + lean))
    buf.rectangle(_stripe_i(x) - 1, _stripe_i(cy2 - slot), _stripe_i(r + slot) + 2, max(1, _stripe_i(2 * slot)))
    buf.triangle(_stripe_i(cx), _stripe_i(cy2 - slot), _stripe_i(x) - 1, _stripe_i(cy2 - slot),
                 _stripe_i(x) - 1, _stripe_i(cy2 - slot - lean))

    # t -- stem cut off at the brand's -12deg across the top, a foot that turns
    # right, and a crossbar that exists only on the right of the stem
    x = x0 + _ADV[1] * H + tr
    w = 0.4960 * H
    R = 0.294 * H
    asc = top - 0.248 * H
    foot = base + 0.021 * H
    buf.pen = ink
    buf.rectangle(_stripe_i(x), _stripe_i(asc), st, max(1, _stripe_i(foot - R - asc)))
    buf.circle(_stripe_i(x + R), _stripe_i(foot - R), _stripe_i(R))
    buf.pen = bg
    buf.rectangle(_stripe_i(x + R), _stripe_i(foot - 2 * R), _stripe_i(w) + 2, max(1, _stripe_i(R)))
    buf.triangle(_stripe_i(x) - 1, _stripe_i(asc) - 1, _stripe_i(x) + st, _stripe_i(asc) - 1,
                 _stripe_i(x) - 1, _stripe_i(asc + 0.059 * H))
    buf.pen = ink
    buf.rectangle(_stripe_i(x + R), _stripe_i(foot - s), _stripe_i(w - R) + 1, max(1, _stripe_i(s)))
    buf.rectangle(_stripe_i(x + 0.280 * H), _stripe_i(top), max(1, _stripe_i(0.216 * H)),
                  max(1, _stripe_i(0.243 * H)))

    # r -- stem and the shoulder
    x = x0 + _ADV[2] * H + 2 * tr
    w = 0.5029 * H
    buf.rectangle(_stripe_i(x), _stripe_i(top), st, max(1, _stripe_i(H)))
    buf.rectangle(_stripe_i(x) + st, _stripe_i(top), max(1, _stripe_i(w - s)), max(1, _stripe_i(0.300 * H)))

    # i -- stem, and the tittle: the slanted square that became Stripe's symbol
    x = x0 + _ADV[3] * H + 3 * tr
    w = 0.2869 * H
    buf.rectangle(_stripe_i(x), _stripe_i(top), st, max(1, _stripe_i(H)))
    buf.triangle(_stripe_i(x), _stripe_i(top - 0.320 * H), _stripe_i(x + w), _stripe_i(top - 0.381 * H),
                 _stripe_i(x + w), _stripe_i(top - 0.149 * H))
    buf.triangle(_stripe_i(x), _stripe_i(top - 0.320 * H), _stripe_i(x + w), _stripe_i(top - 0.149 * H),
                 _stripe_i(x), _stripe_i(top - 0.087 * H))

    # p -- stem through the descender with the bowl hung off it
    x = x0 + _ADV[4] * H + 4 * tr
    buf.rectangle(_stripe_i(x), _stripe_i(top - 0.019 * H), st, max(1, _stripe_i(1.350 * H)))
    _stripe_capsule(buf, x + 0.440 * H, top + 0.500 * H, 0.440 * H, 0.060 * H)
    buf.pen = bg
    _stripe_capsule(buf, x + 0.440 * H, top + 0.500 * H, 0.440 * H - s, 0.060 * H)

    # e -- ring, full-width bar, terminal cut away at the bottom right
    x = x0 + _ADV[5] * H + 5 * tr
    w = 0.8491 * H
    cx = x + 0.4246 * H
    cy = top + 0.500 * H
    buf.pen = ink
    _stripe_capsule(buf, cx, cy, 0.4246 * H, 0.0948 * H)
    buf.pen = bg
    _stripe_capsule(buf, cx, cy, 0.4246 * H - s, 0.0948 * H)
    rr = 1.15 * H
    buf.triangle(_stripe_i(cx), _stripe_i(cy), _stripe_i(cx + rr * 0.990), _stripe_i(cy + rr * 0.139),
                 _stripe_i(cx + rr * 0.469), _stripe_i(cy + rr * 0.883))
    buf.pen = ink
    buf.rectangle(_stripe_i(cx - 0.4246 * H), _stripe_i(cy - 0.105 * H), max(1, _stripe_i(0.8491 * H)),
                  max(1, _stripe_i(0.210 * H)))


def _stripe_mix(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)


def _stripe_sweep(u):
    """The four Chroma stops in hue order: one clean left-to-right sweep."""
    stops = (STRP_G1, STRP_G2, STRP_G3, STRP_G4)
    p = min(0.99999, max(0.0, u)) * 3.0
    i = int(p)
    return _stripe_mix(stops[i], stops[i + 1], p - i)


def _stripe_slab(buf, w, x0, x1, top, depth, drop):
    """The quad between two lines of the brand's slant, over x0..x1.

    Two triangles, and the pen must be OPAQUE: a translucent pair double-blends
    along the diagonal they share and draws a seam right across the ribbon.
    """
    a0 = top - drop * x0 / w
    a1 = top - drop * x1 / w
    buf.triangle(x0, int(a0), x1, int(a1), x1, int(a1 + depth))
    buf.triangle(x0, int(a0), x1, int(a1 + depth), x0, int(a0 + depth))


def _stripe(buf):
    w, h = buf.width, buf.height
    buf.pen = color.rgb(*STRP_BLURPLE)
    buf.clear()

    # the banner: Stripe's gradient beneath a divider cut at the brand angle.
    # Sliced into columns, and NOT because the platform lacks a gradient:
    # `brush.gradient` exists (LINEAR/RADIAL/CONICAL, up to 16 stops, C-speed,
    # `badgeware-docs/api/brush.md`), this comment used to say it did not, and
    # that was wrong in every vendored copy of this file.  The slices stay
    # because they are already measured, already shipping and drawn ONCE into a
    # cached buffer, so the primitive would buy clarity rather than frames --
    # and the two rules for anybody who does swap it are worth writing down:
    # construct the brush ONCE outside the frame (the stock launcher's own
    # comment prices a per-frame construction at ~2.6 ms, `menu/app.py:14-19`;
    # ~440 us and 1,096 B per construction on our own dossier numbers) and move
    # it with `.geometry()` rather than rebuilding it.  A fixed slice count is
    # also what makes this frame cost the same at every canvas size.
    drop = math.tan(math.radians(STRP_TILT)) * w
    bot = STRP_BANNER * h
    for j in range(STRP_SLICES):
        c = _stripe_sweep((j + 0.5) / STRP_SLICES)
        buf.pen = color.rgb(int(c[0]), int(c[1]), int(c[2]))
        _stripe_slab(buf, w, w * j // STRP_SLICES, w * (j + 1) // STRP_SLICES,
              -2, bot + 2, drop)

    # the wordmark, sitting below the band the app draws the wearer's name in
    span = STRP_MARK_W * w
    H = span / _TOTAL
    if H < 3:
        return
    tr = max(0.0, 1.3 - 0.051 * H)
    H = (span - 5.0 * tr) / _TOTAL
    x0 = (w - span) / 2.0
    top = STRP_MARK_Y * h - 0.331 * H - H
    _stripe_wordmark(buf, x0, top, H, tr, color.rgb(*STRP_MARK), color.rgb(*STRP_BLURPLE))


def _stripe_a(buf, t):
    w, h = buf.width, buf.height
    drop = math.tan(math.radians(STRP_TILT)) * w
    bot = STRP_BANNER * h

    # a shine running the length of the banner, once per loop. It is mixed off
    # the gradient it covers rather than laid over it, so it lightens the ribbon
    # instead of greying it.
    lw = max(2, w // 10)
    px = int(-3 * lw + t * STRP_FLOW * (w + 4 * lw)) % (w + 4 * lw) - 3 * lw
    for k in range(3):
        x0 = px + k * lw
        c = _stripe_mix(_stripe_sweep((x0 + lw * 0.5) / w), (255, 255, 255),
                 STRP_SHINE * (1.0 - 0.45 * abs(k - 1)))
        buf.pen = color.rgb(int(c[0]), int(c[1]), int(c[2]))
        _stripe_slab(buf, w, x0, x0 + lw, -2, bot + 2, drop)

    # stripes streaming out from under the banner. Each runs exactly one lap per
    # loop and is clear of the canvas at the wrap, so t=1 is t=0 to the pixel.
    if STRP_STREAM_ON:
        stops = (STRP_G1, STRP_G2, STRP_G3, STRP_G4)
        top2 = bot + h * 0.022
        seg = max(2, w * 5 // 32)
        for i in range(STRP_STREAM):
            c = stops[i % 4]
            buf.pen = color.rgb(c[0], c[1], c[2])
            x0 = int(((t * STRP_FLOW + i / STRP_STREAM) % 1.0) * (w + seg + 2)) - seg - 1
            _stripe_slab(buf, w, x0, x0 + seg, top2, h * 0.045, drop)

# ── RESEND ───────────────────────────────────────────
# The Resend lettermark at full height on Resend Black, sends running its leg's diagonal.

# @skinlab {"type":"color","label":"Mark","group":"Palette"}
RSND_INK = (253, 253, 253)


# @skinlab {"type":"color","label":"Paper","group":"Palette"}
RSND_PAPER = (0, 0, 0)


# @skinlab {"type":"color","label":"Grain tint","group":"Palette"}
RSND_FIELD = (17, 17, 21)


# @skinlab {"type":"color","label":"Send 1","group":"Palette"}
RSND_CYAN = (2, 252, 239)


# @skinlab {"type":"color","label":"Send 2","group":"Palette"}
RSND_AMBER = (255, 181, 43)


# @skinlab {"type":"color","label":"Send 3","group":"Palette"}
RSND_VIOLET = (160, 43, 254)


# @skinlab {"type":"number","label":"Mark height","group":"Layout","min":0.6,"max":1.5,"step":0.02}
RSND_MARK = 0.96


# @skinlab {"type":"number","label":"Mark centre","group":"Layout","min":0.2,"max":0.8,"step":0.01}
RSND_MARK_X = 0.5


# @skinlab {"type":"integer","label":"Sends","group":"Motion","min":0,"max":5,"step":1}
RSND_SENDS = 4


# @skinlab {"type":"integer","label":"Passes per loop","group":"Motion","min":1,"max":4,"step":1}
RSND_LAPS = 2


# @skinlab {"type":"integer","label":"Grain count","group":"Details","min":0,"max":80,"step":1}
RSND_GRAIN = 64


# @skinlab {"type":"boolean","label":"Rainbow rail","group":"Details"}
RSND_RAIL = True


def _resend_stroke(buf):
    return max(1, buf.width // 160)


def _resend_bar(buf, x0, y0, x1, y1, half):
    """A fat 45-degree bar as two triangles; line() has no thickness."""
    buf.triangle(int(x0 - half), int(y0 + half), int(x0 + half), int(y0 - half),
                 int(x1 + half), int(y1 - half))
    buf.triangle(int(x0 - half), int(y0 + half), int(x1 + half), int(y1 - half),
                 int(x1 - half), int(y1 + half))


def _resend_lettermark(buf, x0, y0, m):
    """The Resend lettermark, traced off the official SVG. Its box is a
    900-unit square and every fraction below is that trace divided by 900.

    Three things about the real drawing decide the construction. The bowl is an
    oval 1.15 wider than tall, so it is the union of two circles a twelfth of
    the square apart -- a stadium whose four extremes are exact and whose flat
    top spans 0.08 of the square. The counter is NOT a hole: the stroke's inner
    edge runs straight out to the left margin, so the notch is open, and the
    two rectangles cut it back to the bowl's own inner arc. And the hook at the
    bottom of the bowl turns on a round nose, not a point, which is why the
    fan below carries N1 and N2 either side of the leftmost vertex."""
    ink = color.rgb(*RSND_INK)
    buf.pen = ink
    bar_h = max(1, int(m * 0.1509))
    buf.rectangle(x0, y0, int(m * 0.6116), bar_h)
    # radius from the bowl's FULL height, halved once: int(m * 0.2681) twice
    # truncates twice and leaves the belly a row short of the bowl
    bowl_r = (int(m * 0.5362) + 1) // 2
    bowl_y = y0 + bowl_r
    bowl_l = x0 + int(m * 0.5708)
    buf.circle(bowl_l, bowl_y, bowl_r)
    buf.circle(x0 + int(m * 0.6524), bowl_y, bowl_r)
    # The two cuts start on the bowl's OWN leftmost pixel per band, computed
    # from the circle rather than from int(m * 0.3027): the two roundings
    # disagree by a pixel at thumbnail size and that pixel is a white spike
    # hanging inside the notch. Rounding out by one keeps the error on the
    # side that hides under the mark instead of the side that shows.
    buf.pen = color.rgb(*RSND_PAPER)
    cut = x0 + int(m * 0.4899)
    waist = int(m * 0.42)
    edge = bowl_r - int(math.sqrt(max(0, bowl_r * bowl_r
                                      - (waist - bowl_r) * (waist - bowl_r)))) - 1
    buf.rectangle(bowl_l - bowl_r, y0 + bar_h,
                  cut - bowl_l + bowl_r, waist - bar_h)
    buf.rectangle(bowl_l - bowl_r + edge, y0 + waist,
                  cut - bowl_l + bowl_r - edge, int(m * 0.10))
    buf.circle(cut, y0 + int(m * 0.2926), max(1, int(m * 0.142)))
    buf.pen = ink
    ltx, lty = x0 + int(m * 0.5138), y0 + int(m * 0.5362)
    fan = ((0.5097, 0.4414), (0.3191, 0.4924), (0.2659, 0.5236),
           (0.2477, 0.5708), (0.2572, 0.6096), (0.2864, 0.6483),
           (0.6565, 1.0), (1.0, 1.0))
    px, py = x0 + int(m * fan[0][0]), y0 + int(m * fan[0][1])
    for k in range(1, 8):
        qx, qy = x0 + int(m * fan[k][0]), y0 + int(m * fan[k][1])
        buf.triangle(ltx, lty, px, py, qx, qy)
        px, py = qx, qy


def _resend_rainbow(k):
    """The brand's own rainbow-border ramp, cyan to amber to violet, k in 0..1.

    The token is a 44%-alpha gradient over dark glass; on a 160x120 emissive
    panel that lands at a muddy quarter brightness, so the three stops are used
    at full strength here. The hexes are unchanged."""
    if k < 0.5:
        a, b, f = RSND_CYAN, RSND_AMBER, k * 2.0
    else:
        a, b, f = RSND_AMBER, RSND_VIOLET, (k - 0.5) * 2.0
    return (int(a[0] + (b[0] - a[0]) * f),
            int(a[1] + (b[1] - a[1]) * f),
            int(a[2] + (b[2] - a[2]) * f))


def _resend_geometry(buf):
    m = max(8, int(buf.height * RSND_MARK))
    return int(buf.width * RSND_MARK_X - m // 2), (buf.height - m) // 2, m


def _resend(buf):
    w, h, s = buf.width, buf.height, _resend_stroke(buf)

    # Resend Black is #000000 and the paper is FLAT. A row gradient was tried
    # here and reverted: the notch inside the lettermark has to be cut with the
    # paper colour, and against a lifted field that cut showed as a hard
    # vertical seam down the bowl. Depth comes from the grain instead, which
    # fades across the field and has no edge to give away.
    buf.pen = color.rgb(*RSND_PAPER)
    buf.clear()

    # noise texture: the brand's own hero treatment, deterministic, never
    # random. Kept a dozen levels above the paper -- brighter than that and the
    # 40x30 thumbnail reads as dust rather than as atmosphere.
    for i in range(RSND_GRAIN):
        x, y = (i * 137) % w, (i * 89) % h
        g = (i * 37) % 7 + (w - x) * RSND_FIELD[0] // max(1, w)
        buf.pen = color.rgb(g, g, g + 2)
        buf.rectangle(x, y, s, s)

    # the rainbow border, laid along the bottom edge
    if RSND_RAIL:
        seg = max(1, w // 14)
        for x in range(0, w, seg):
            buf.pen = color.rgb(*_resend_rainbow(min(1.0, x / max(1, w - seg))))
            buf.rectangle(x, h - s * 2, seg, s * 2)

    x0, y0, m = _resend_geometry(buf)
    _resend_lettermark(buf, x0, y0, m)


def _resend_a(buf, t):
    w, h, s = buf.width, buf.height, _resend_stroke(buf)
    half = max(1, w // 80)
    length = int(w * 0.38)

    # Sends run the leg's OWN 45-degree line, each behind a dim wake. Every
    # rail travels only its own visible chord, so they are all on the glass at
    # once, and both ends of the run sit a full body off-canvas: the wrap has
    # nothing to show. `half` is a hairline; at w // 40 the bar is eleven
    # pixels at LORES and reads as a slab rather than as speed.
    for i in range(RSND_SENDS):
        tone = (RSND_CYAN, RSND_AMBER, RSND_VIOLET)[i % 3]
        c = int(-w * 0.72 + (i + 0.5) * (w + h) * 0.72 / max(1, RSND_SENDS))
        lo = max(0, -c) - 2 * length
        hi = min(w, h - c) + length
        p = (t * RSND_LAPS + i / max(1, RSND_SENDS)) % 1.0
        tail = lo + int(p * (hi - lo))
        head = tail + length
        mid = head - length // 2
        buf.pen = color.rgb(tone[0] // 4, tone[1] // 4, tone[2] // 4)
        _resend_bar(buf, tail, tail + c, mid, mid + c, half)
        buf.pen = color.rgb(*tone)
        _resend_bar(buf, mid, mid + c, head, head + c, half)
        buf.pen = color.rgb(*RSND_INK)
        buf.rectangle(head - half, head + c - half, half * 2, half * 2)

    # the delivery pip, running the rainbow rail left to right. It is always
    # on the glass, so no phase of the loop is ever a still picture.
    if RSND_RAIL:
        q = (t * RSND_LAPS) % 1.0
        buf.pen = color.rgb(*RSND_INK)
        buf.rectangle(int(q * (w + length // 3)) - length // 3, h - s * 3,
                      length // 3, s * 3)

    # The mark goes back on LAST, so nothing ever crosses it. The brand kit
    # forbids effects, outlines and recolouring on the logo, and a send drawn
    # over the bowl would be all three.
    x0, y0, m = _resend_geometry(buf)
    _resend_lettermark(buf, x0, y0, m)

# ── BOLT ───────────────────────────────────────────
# BOLT.NEW - the bolt.new 'b' cropped huge in white over the brand's electric-blue glow, charge running down the bolt and firing out of its lightning flick.

# @skinlab {"type":"color","label":"Deep","group":"Palette"}
BOLT_BLACK = (10, 10, 10)


# @skinlab {"type":"color","label":"Field","group":"Palette"}
BOLT_FIELD = (20, 136, 252)


# @skinlab {"type":"color","label":"Electric blue","group":"Palette"}
BOLT_ACCENT = (20, 136, 252)


# @skinlab {"type":"color","label":"Glow","group":"Palette"}
BOLT_LIGHT = (101, 184, 255)


# @skinlab {"type":"color","label":"Mark","group":"Palette"}
BOLT_MARK = (255, 255, 255)


# @skinlab {"type":"number","label":"Dark floor","group":"Look","min":0.0,"max":0.38,"step":0.02}
BOLT_HORIZON = 0.38


# @skinlab {"type":"number","label":"Mark height","group":"Layout","min":0.6,"max":1.6,"step":0.02}
BOLT_SCALE = 1.16


# @skinlab {"type":"number","label":"Mark across","group":"Layout","min":0.2,"max":0.8,"step":0.01}
BOLT_X = 0.47


# @skinlab {"type":"number","label":"Flick tip height","group":"Layout","min":0.6,"max":1.2,"step":0.01}
BOLT_BASE = 0.94


# @skinlab {"type":"integer","label":"Shadow layers","group":"Shape","min":0,"max":5,"step":1}
BOLT_SHADOW = 2


# @skinlab {"type":"number","label":"Shadow spread","group":"Shape","min":0.02,"max":0.3,"step":0.01}
BOLT_SHADOW_GAP = 0.03


# @skinlab {"type":"integer","label":"Charges","group":"Motion","min":1,"max":2,"step":1}
BOLT_CHARGES = 1


# @skinlab {"type":"integer","label":"Runs per loop","group":"Motion","min":1,"max":4,"step":1}
BOLT_TRIPS = 2


# @skinlab {"type":"integer","label":"Core spin per loop","group":"Motion","min":0,"max":3,"step":1}
BOLT_ORBIT = 1


# @skinlab {"type":"integer","label":"Discharge streaks","group":"Details","min":0,"max":6,"step":1}
BOLT_FAN = 3


_ARCS = 2           # fat tiles spinning round the counter


_SPAN = 0.78        # how much of that ring one tile covers, in radians


_TRAIL = 5          # contiguous blocks: a comet down the bolt, not a ladder


_PULSE = 2          # core pulses per loop -- whole turns, so it joins at the wrap


_INSET = 0.58       # keep the charge off the stem's silhouette edge


_STEP = 0.105       # one trail block, as a fraction of the bolt's run


def _bolt_mix(a, b, k):
    """Blend two brand colours, k = 0..255. Opaque: no alpha plates anywhere."""
    return (a[0] + (b[0] - a[0]) * k // 255,
            a[1] + (b[1] - a[1]) * k // 255,
            a[2] + (b[2] - a[2]) * k // 255)


def _bolt_ground(y, h):
    """The field at row y: flat brand blue, sinking to the site's near-black
    only under BOLT_HORIZON at the very bottom, where the flick discharges.
    Constant and then monotonic, so it can never read as a band behind the
    name, and every row the name can land on is above the luminance the
    chosen ink would vanish into."""
    f = y / max(1, h - 1)
    edge = 1.0 - BOLT_HORIZON
    if f <= edge:
        return BOLT_FIELD
    k = (f - edge) / max(0.01, BOLT_HORIZON)
    return _bolt_mix(BOLT_FIELD, BOLT_BLACK, int(255 * k ** 1.4))


def _bolt_geom(buf):
    """One SVG unit in pixels, and where the mark's local (0, 0) lands."""
    h = buf.height
    s = h * BOLT_SCALE / 10.0
    return s, buf.width * BOLT_X - 4.0 * s, h * BOLT_BASE - 10.0 * s


def _bolt_mark(buf, s, ox, oy, grow, fill, eye):
    """The mark, optionally grown about its own centre for a shadow layer."""
    ss = s * (1.0 + grow)
    mx = ox + (4.0 * s - 4.0 * ss)
    my = oy + (5.0 * s - 5.0 * ss)
    buf.pen = color.rgb(fill[0], fill[1], fill[2])
    buf.circle(int(mx + 4.72 * ss), int(my + 5.50 * ss), max(1, int(3.28 * ss)))
    if eye is not None:
        buf.pen = color.rgb(eye[0], eye[1], eye[2])
        buf.circle(int(mx + 4.36 * ss), int(my + 5.50 * ss), max(1, int(1.20 * ss)))
        buf.pen = color.rgb(fill[0], fill[1], fill[2])
    top = int(my)
    foot = int(my + 8.614 * ss)
    ax, bx = int(mx + 2.222 * ss), int(mx + 4.591 * ss)
    cx, dx = int(mx + 2.657 * ss), int(mx + 0.287 * ss)
    buf.triangle(ax, top, bx, top, cx, foot)
    buf.triangle(ax, top, cx, foot, dx, foot)
    buf.triangle(dx, foot, cx, foot, int(mx), int(my + 10.0 * ss))


def _bolt(buf):
    w, h = buf.width, buf.height
    s, ox, oy = _bolt_geom(buf)

    # the field: one rectangle per row, so every pixel is covered
    buf.pen = color.rgb(BOLT_FIELD[0], BOLT_FIELD[1], BOLT_FIELD[2])
    buf.clear()
    for y in range(h):
        c = _bolt_ground(y, h)
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.rectangle(0, y, w, 1)

    # the shadow: the mark's own silhouette grown outwards, deepest against the
    # mark so the white keeps a hard edge on the blue, fading out into the
    # field. Flat colour, never a large translucent shape.
    for i in range(BOLT_SHADOW, 0, -1):
        c = _bolt_mix(BOLT_FIELD, BOLT_BLACK, 255 * (BOLT_SHADOW + 1 - i) // (BOLT_SHADOW + 1))
        _bolt_mark(buf, s, ox, oy, i * BOLT_SHADOW_GAP, c, None)

    # the counter is a SHADOWED hole rather than the black of the icon tile:
    # it sits dead centre of the name band, so it is held at 0.151 WCAG
    # luminance -- dark enough to read against the white at 5.2:1, light
    # enough that black ink never lands on top of it and vanishes.
    _bolt_mark(buf, s, ox, oy, 0.0, BOLT_MARK, _bolt_mix(BOLT_FIELD, BOLT_BLACK, 55))


def _bolt_a(buf, t):
    """Charge runs the bolt, fires out of the flick, and the core answers."""
    s, ox, oy = _bolt_geom(buf)

    # the charge: contiguous blocks down the bolt's slab. The conductor is
    # already white, so the comet reads by SATURATION -- a solid accent head
    # dissolving back into the mark -- not by brightness, which has no headroom.
    for n in range(BOLT_CHARGES):
        p = (t * BOLT_TRIPS + n / BOLT_CHARGES) % 1.0
        wide = 1.15 * s
        for j in range(_TRAIL):
            q0 = p - j * _STEP
            q1 = q0 + _STEP
            c = _bolt_mix(BOLT_MARK, BOLT_ACCENT, 255 - j * 46)
            buf.pen = color.rgb(c[0], c[1], c[2])
            l0 = ox + (2.222 - 1.935 * q0 + _INSET) * s
            l1 = ox + (2.222 - 1.935 * q1 + _INSET) * s
            y0 = oy + 8.614 * q0 * s
            y1 = oy + 8.614 * q1 * s
            buf.triangle(int(l0), int(y0), int(l0 + wide), int(y0), int(l1 + wide), int(y1))
            buf.triangle(int(l0), int(y0), int(l1 + wide), int(y1), int(l1), int(y1))

    # the flick discharges: streaks that grow as a charge runs the bolt and
    # snap off the instant it re-enters at the top. Whole strikes per loop, so
    # the sawtooth lands exactly on the wrap.
    fire = ((t * BOLT_TRIPS * BOLT_CHARGES) % 1.0) ** 3
    tipx, tipy = ox, oy + 10.0 * s
    hw = 0.30 * s
    for i in range(BOLT_FAN):
        a = 2.15 + i * 1.70 / max(1, BOLT_FAN - 1)
        run = (0.55 + 1.85 * fire * (0.6 + 0.4 * ((i * 7) % 3) / 2.0)) * s
        c = _bolt_mix(BOLT_ACCENT, BOLT_MARK, int(40 + 215 * fire))
        buf.pen = color.rgb(c[0], c[1], c[2])
        buf.triangle(int(tipx + run * math.cos(a)), int(tipy + run * math.sin(a)),
                     int(tipx - hw * math.sin(a)), int(tipy + hw * math.cos(a)),
                     int(tipx + hw * math.sin(a)), int(tipy - hw * math.cos(a)))

    # light spinning round the counter, on the white just outside it: whole
    # turns per loop, and wholly inside the bowl so it never bites the mark
    r_in, r_out = 1.42 * s, 1.86 * s
    bx, by = ox + 4.36 * s, oy + 5.50 * s
    for i in range(_ARCS):
        base = t * 2.0 * math.pi * BOLT_ORBIT + i * 2.0 * math.pi / _ARCS
        c = BOLT_LIGHT if i == 0 else BOLT_ACCENT
        buf.pen = color.rgb(c[0], c[1], c[2])
        for m in range(2):
            a0 = base + m * _SPAN / 2.0
            a1 = a0 + _SPAN / 2.0
            buf.triangle(int(bx + r_in * math.cos(a0)), int(by + r_in * math.sin(a0)),
                         int(bx + r_out * math.cos(a0)), int(by + r_out * math.sin(a0)),
                         int(bx + r_out * math.cos(a1)), int(by + r_out * math.sin(a1)))
            buf.triangle(int(bx + r_in * math.cos(a0)), int(by + r_in * math.sin(a0)),
                         int(bx + r_out * math.cos(a1)), int(by + r_out * math.sin(a1)),
                         int(bx + r_in * math.cos(a1)), int(by + r_in * math.sin(a1)))

    # the counter breathes: the mark's core, lit from inside
    k = 0.5 + 0.5 * math.sin(t * 2.0 * math.pi * _PULSE)
    core = max(1, int((0.30 + 0.45 * k) * 1.20 * s))
    ex, ey = int(ox + 4.36 * s), int(oy + 5.50 * s)
    buf.pen = color.rgb(BOLT_ACCENT[0], BOLT_ACCENT[1], BOLT_ACCENT[2])
    buf.circle(ex, ey, core)
    buf.pen = color.rgb(BOLT_LIGHT[0], BOLT_LIGHT[1], BOLT_LIGHT[2])
    buf.circle(ex, ey, max(1, core * 2 // 5))

# ── GRAFANA ───────────────────────────────────────────
# GRAFANA — the orange-to-yellow flame spiral filling Grafana's dark dashboard

# @skinlab {"type":"color","label":"Dashboard canvas","group":"Palette"}
GRAF_CANVAS = (17, 18, 23)


# @skinlab {"type":"color","label":"Flame (top)","group":"Palette"}
GRAF_FLAME_TOP = (240, 90, 40)


# @skinlab {"type":"color","label":"Flame (bottom)","group":"Palette"}
GRAF_FLAME_BOTTOM = (251, 202, 10)


# @skinlab {"type":"color","label":"Panel","group":"Palette"}
GRAF_PANEL = (24, 27, 31)


# @skinlab {"type":"color","label":"Series","group":"Palette"}
GRAF_SERIES = (115, 191, 105)


# @skinlab {"type":"color","label":"Alerting","group":"Palette"}
GRAF_ALERT = (242, 73, 92)


# @skinlab {"type":"number","label":"Mark size","group":"Layout","min":0.5,"max":1.4,"step":0.02}
GRAF_MARK_SIZE = 0.64


# @skinlab {"type":"number","label":"Mark x","group":"Layout","min":0.3,"max":0.9,"step":0.01}
GRAF_MARK_X = 0.59


# @skinlab {"type":"number","label":"Mark y","group":"Layout","min":0.3,"max":0.9,"step":0.01}
GRAF_MARK_Y = 0.69


# @skinlab {"type":"number","label":"Panel height","group":"Layout","min":0.0,"max":0.4,"step":0.01}
GRAF_PANEL_H = 0.15


# @skinlab {"type":"integer","label":"Samples","group":"Layout","min":8,"max":24,"step":1}
GRAF_SAMPLES = 18


# @skinlab {"type":"number","label":"Alert threshold","group":"Details","min":0.3,"max":1.0,"step":0.02}
GRAF_THRESHOLD = 0.70


# @skinlab {"type":"integer","label":"Screens per loop","group":"Motion","min":1,"max":4,"step":1}
GRAF_SCROLL = 1


# @skinlab {"type":"integer","label":"Charges","group":"Motion","min":0,"max":3,"step":1}
GRAF_SPARKS = 2


# @skinlab {"type":"integer","label":"Charge runs per loop","group":"Motion","min":1,"max":4,"step":1}
GRAF_SPARK_LAPS = 2


_ARM = (
    (78, 103, 127), (94, 112, 142), (109, 120, 154), (125, 128, 168), (140, 134, 180),
    (156, 140, 192), (172, 145, 201), (187, 145, 206), (203, 143, 211), (218, 144, 215),
    (234, 143, 222), (250, 144, 226), (265, 142, 229), (281, 141, 233), (296, 143, 238),
    (312, 147, 247), (328, 153, 258), (343, 160, 271), (359, 169, 283), (374, 179, 298),
    (390, 190, 317), (406, 205, 336), (421, 223, 351), (437, 241, 372), (452, 260, 398),
    (468, 277, 421), (484, 294, 441), (499, 312, 461), (515, 331, 478), (530, 350, 493),
    (546, 363, 508), (562, 373, 515), (577, 386, 518), (593, 393, 520), (608, 392, 519),
    (624, 385, 500), (640, 380, 482), (655, 372, 457), (671, 365, 431), (686, 358, 404),
    (702, 353, 378),
)


_PETALS = (
    (390, 80, 372, 406),
    (440, 104, 412, 458),
    (492, 122, 458, 506),
    (534, 149, 506, 552),
    (578, 159, 552, 606),
    (620, 112, 606, 642),
    (654, 81, 642, 690),
)


_EDGE = (44, 47, 53)


_TEXT = (204, 204, 220)


_NOTCH = 0.16          # how much of each flank the smooth edge keeps


_TOP = -0.608          # the mark's top edge, in mark widths above the centre


_GRAFANA_SPAN = 1.086          # the mark's full height, in mark widths


def _grafana_bump(p):
    """How far a flame point stands proud of the smooth outer edge at angle `p`.
    Measured off the file: the edge holds the smooth line out of the notch and
    then runs dead straight to the tip, so a point is a spike on a broad body
    rather than a lobe."""
    for tp, amp, b0, b1 in _PETALS:
        if b0 <= p <= b1:
            k = (p - b0) / (tp - b0) if p < tp else (b1 - p) / (b1 - tp)
            if k <= _NOTCH:
                return 0.0
            return amp * 0.001 * (k - _NOTCH) / (1.0 - _NOTCH)
    return 0.0


def _grafana_arm(p):
    """(inner, smooth outer) radius of the ribbon at angle `p`, in mark widths,
    with no flame point on it. The table is evenly spaced, so the index is
    arithmetic. This is the edge anything drawn ON the ribbon must follow: it
    never stands above the drawn silhouette, so a segment laid along it cannot
    leak out through a notch the way one laid along `_at` does."""
    n = len(_ARM)
    f = (p - 78) * (n - 1) / 624.0
    i = int(f)
    if i < 0:
        i = 0
    elif i > n - 2:
        i = n - 2
    g = f - i
    a = _ARM[i]
    b = _ARM[i + 1]
    return (a[1] + (b[1] - a[1]) * g) * 0.001, (a[2] + (b[2] - a[2]) * g) * 0.001


def _grafana_at(p):
    """(inner, outer) radius of the silhouette at angle `p`, flame point and all."""
    ri, ro = _grafana_arm(p)
    return ri, ro + _grafana_bump(p)


def _grafana_slices():
    """The angles the ribbon is cut at: an even sweep round the buried inner coil,
    then, per flame point, the two places its straight flanks leave the smooth
    edge and the tip itself — so every tip lands exactly on a vertex."""
    out = [78.0 + (294.0 * i) / 22.0 for i in range(22)]
    for tp, amp, b0, b1 in _PETALS:
        if out[-1] < b0:
            out.append(float(b0))
        out.append(b0 + (tp - b0) * _NOTCH)
        out.append(float(tp))
        out.append(b1 - (b1 - tp) * _NOTCH)
    out.append(702.0)
    return out


def _grafana_ink(v):
    """The mark's own gradient: #F05A28 falling to #FBCA0A, held flat above 30%
    and below 99% of the mark's height, exactly where the SVG puts its stops."""
    k = (v - 0.30) / 0.69
    if k < 0.0:
        k = 0.0
    elif k > 1.0:
        k = 1.0
    return color.rgb(
        int(GRAF_FLAME_TOP[0] + (GRAF_FLAME_BOTTOM[0] - GRAF_FLAME_TOP[0]) * k),
        int(GRAF_FLAME_TOP[1] + (GRAF_FLAME_BOTTOM[1] - GRAF_FLAME_TOP[1]) * k),
        int(GRAF_FLAME_TOP[2] + (GRAF_FLAME_BOTTOM[2] - GRAF_FLAME_TOP[2]) * k),
    )


def _grafana_mark(buf):
    """Spiral centre and scale in pixels. The scale IS the mark's width, so one
    knob crops it against any canvas."""
    return buf.width * GRAF_MARK_X, buf.height * GRAF_MARK_Y, buf.width * GRAF_MARK_SIZE


def _grafana_pt(cx, cy, s, p, r):
    a = p * math.pi / 180.0
    return int(cx + s * r * math.cos(a)), int(cy + s * r * math.sin(a))


def _grafana(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    st = max(1, w // 160)
    buf.pen = color.rgb(*GRAF_CANVAS)
    buf.clear()

    # the mark lives in its own panel: a hairline frame that runs off the bottom,
    # so the dashboard reads as a dashboard and not as a logo on a dark rectangle
    ph = int(h * GRAF_PANEL_H)
    buf.pen = color.rgb(*_EDGE)
    buf.rectangle(u, ph + u, w - u * 2, h)
    buf.pen = color.rgb(*GRAF_CANVAS)
    buf.rectangle(u + st, ph + u + st, w - u * 2 - st * 2, h)

    cx, cy, s = _grafana_mark(buf)
    top = cy + s * _TOP
    span = s * _GRAFANA_SPAN

    # the ribbon, one fat tile per slice. Each of the tile's two triangles takes
    # its own colour from its own centroid, so the gradient steps twice per tile
    # for no extra call. Slices overlap by a hair so they stay welded at 40x30.
    cut = _grafana_slices()
    for i in range(len(cut) - 1):
        p0 = cut[i]
        p1 = cut[i + 1] + 1.6
        i0, o0 = _grafana_at(p0)
        i1, o1 = _grafana_at(p1)
        ax, ay = _grafana_pt(cx, cy, s, p0, i0)
        bx, by = _grafana_pt(cx, cy, s, p0, o0)
        dx, dy = _grafana_pt(cx, cy, s, p1, o1)
        ex, ey = _grafana_pt(cx, cy, s, p1, i1)
        buf.pen = _grafana_ink(((ay + by + dy) / 3.0 - top) / span)
        buf.triangle(ax, ay, bx, by, dx, dy)
        buf.pen = _grafana_ink(((ay + dy + ey) / 3.0 - top) / span)
        buf.triangle(ax, ay, dx, dy, ex, ey)

    # the blunt end of the coil, where the ribbon stops dead beside the eye
    i0, o0 = _grafana_at(78.0)
    ex, ey = _grafana_pt(cx, cy, s, 78.0, (i0 + o0) * 0.5)
    buf.pen = _grafana_ink((ey - top) / span)
    buf.circle(ex, ey, max(1, int(s * (o0 - i0) * 0.5)))

    # the panel the series lives in: hairline border, plate, gridlines, alert rule
    if ph > u * 2:
        plot = ph - u
        buf.pen = color.rgb(*_EDGE)
        buf.rectangle(u - st, u - st, w - u * 2 + st * 2, plot + st * 2)
        buf.pen = color.rgb(*GRAF_PANEL)
        buf.rectangle(u, u, w - u * 2, plot)
        buf.pen = color.rgb(_TEXT[0], _TEXT[1], _TEXT[2], 26)
        for k in (1, 2, 3):
            buf.rectangle(u + (w - u * 2) * k // 4, u, st, plot)
        ty = u + int(plot * (1.0 - GRAF_THRESHOLD))
        buf.pen = color.rgb(GRAF_ALERT[0], GRAF_ALERT[1], GRAF_ALERT[2], 130)
        for k in range(0, w - u * 2, u * 4):
            buf.rectangle(u + k, ty, u * 2, st)


def _grafana_sample(j, n):
    """A plausible series that is EXACTLY periodic in j with period n, so a whole
    number of periods scrolls past per loop and the wrap has nothing to join."""
    a = 2.0 * math.pi * j / n
    v = 0.46 + 0.20 * math.sin(a) + 0.13 * math.sin(a * 3.0 + 1.1) + 0.07 * math.sin(a * 5.0 + 2.3)
    if v < 0.05:
        return 0.05
    if v > 0.98:
        return 0.98
    return v


def _grafana_a(buf, t):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    st = max(1, w // 160)
    n = GRAF_SAMPLES

    # the series scrolls right to left, a whole number of screens per loop
    ph = int(h * GRAF_PANEL_H)
    if ph > u * 2:
        plot = ph - u
        cw = (w - u * 2) / n
        off = t * GRAF_SCROLL * n
        base = int(off)
        frac = off - base
        for i in range(n + 1):
            v = _grafana_sample((i + base) % n, n)
            bh = int(plot * v)
            buf.pen = color.rgb(*GRAF_ALERT) if v > GRAF_THRESHOLD else color.rgb(*GRAF_SERIES)
            buf.rectangle(u + int((i - frac) * cw), u + plot - bh, int(cw) + 1, bh)

    # a charge running the coil outward: the ribbon itself lights up, head first,
    # two dimming segments behind it. Always drawn — the alpha is what changes at
    # the ends, so a frame never costs less than the frame before it.
    cx, cy, s = _grafana_mark(buf)
    for i in range(GRAF_SPARKS):
        f = (t * GRAF_SPARK_LAPS + i / max(1, GRAF_SPARKS)) % 1.0
        for k in (0, 1, 2):
            g = f - k * 0.05
            if g < 0.0:
                g = 0.0
            elif g > 1.0:
                g = 1.0
            p0 = 78.0 + 624.0 * g
            i0, o0 = _grafana_arm(p0)
            p1 = p0 + 4.6 / (i0 + o0)      # a constant ARC, so it stays a segment
            i1, o1 = _grafana_arm(p1)
            fade = min(1.0, g * 9.0, (1.0 - g) * 9.0)
            buf.pen = color.rgb(255, 246, 214, int((215 - k * 72) * fade))
            ax, ay = _grafana_pt(cx, cy, s, p0, i0)
            bx, by = _grafana_pt(cx, cy, s, p0, o0)
            dx, dy = _grafana_pt(cx, cy, s, p1, o1)
            ex, ey = _grafana_pt(cx, cy, s, p1, i1)
            buf.triangle(ax, ay, bx, by, dx, dy)
            buf.triangle(ax, ay, dx, dy, ex, ey)

    # the crosshair Grafana parks on the newest point
    if ph > u * 2:
        buf.pen = color.rgb(_TEXT[0], _TEXT[1], _TEXT[2], 215)
        buf.rectangle(w - u - st * 2, u, st, ph - u)

# ── DOPPLER ───────────────────────────────────────────
# Doppler's six-spoke asterisk at full height in its own gradient, firing hexagonal wavefronts across a cell field.

# @skinlab {"type":"color","label":"Field","group":"Palette"}
DPLR_FIELD = (28, 22, 36)


# @skinlab {"type":"color","label":"Field bloom","group":"Palette"}
DPLR_BLOOM = (44, 25, 72)


# @skinlab {"type":"color","label":"Mark lilac","group":"Palette"}
DPLR_LILAC = (255, 158, 250)


# @skinlab {"type":"color","label":"Mark orange","group":"Palette"}
DPLR_ORANGE = (245, 92, 21)


# @skinlab {"type":"color","label":"Mark rose","group":"Palette"}
DPLR_ROSE = (196, 74, 140)


# @skinlab {"type":"color","label":"Mark purple","group":"Palette"}
DPLR_PURPLE = (107, 19, 245)


# @skinlab {"type":"color","label":"Signal","group":"Palette"}
DPLR_SIGNAL = (0, 245, 117)


# @skinlab {"type":"color","label":"Warm white","group":"Palette"}
DPLR_INK = (241, 240, 236)


# @skinlab {"type":"number","label":"Mark size","group":"Layout","min":0.20,"max":0.42,"step":0.005}
DPLR_MARK_R = 0.31


# @skinlab {"type":"number","label":"Mark centre","group":"Layout","min":0.40,"max":0.72,"step":0.01}
DPLR_MARK_Y = 0.51


# @skinlab {"type":"number","label":"Spoke width","group":"Shape","min":0.10,"max":0.26,"step":0.004}
DPLR_ARM_W = 0.178


# @skinlab {"type":"number","label":"Spoke gap","group":"Shape","min":0.45,"max":0.85,"step":0.01}
DPLR_GAP = 0.665


# @skinlab {"type":"integer","label":"Cell edges","group":"Details","min":0,"max":16,"step":1}
DPLR_CELLS = 9


# @skinlab {"type":"boolean","label":"Wordmark","group":"Details"}
DPLR_WORDMARK = True


# @skinlab {"type":"integer","label":"Wavefronts","group":"Motion","min":1,"max":2,"step":1}
DPLR_WAVES = 2


# @skinlab {"type":"integer","label":"Waves per loop","group":"Motion","min":1,"max":4,"step":1}
DPLR_WAVE_TURNS = 2


# @skinlab {"type":"integer","label":"Charges per loop","group":"Motion","min":1,"max":5,"step":1}
DPLR_PULSE_TURNS = 2


# @skinlab {"type":"integer","label":"Wave brightness","group":"Look","min":40,"max":255,"step":5}
DPLR_WAVE_ALPHA = 165


_BASE = -math.pi / 12.0


_DOPPLER_STEP = math.pi / 3.0


_WARM = _BASE + math.pi


def _doppler_lerp(a, b, k):
    if k < 0.0:
        k = 0.0
    if k > 1.0:
        k = 1.0
    return (int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k))


def _doppler_brand(px, py):
    """The logo's own colour at a point given in mark radii.

    Sampled off the real mark rather than guessed. Hue is driven by ANGLE
    round the centre, not by a straight line across it: the spoke pointing
    at -15 degrees is flat #6B13F5, the one opposite is #F55C15, the core is
    the rose between them, and a #FF9EFA bloom sits over the warm spoke's
    tip. The 0.72 power is what makes the two side spokes land on the rose
    the real mark has there rather than halfway between the ends."""
    rr = math.sqrt(px * px + py * py)
    ka = (0.5 + 0.5 * math.cos(math.atan2(py, px) - _BASE)) ** 0.72
    k = 0.5 + (ka - 0.5) * min(1.0, rr * 1.7)
    if k < 0.42:
        base = _doppler_lerp(DPLR_ORANGE, DPLR_ROSE, k / 0.42)
    else:
        base = _doppler_lerp(DPLR_ROSE, DPLR_PURPLE, (k - 0.42) / 0.58)
    bx, by = px - 1.20 * math.cos(_WARM), py - 1.20 * math.sin(_WARM)
    return _doppler_lerp(base, DPLR_LILAC,
                 (1.0 - math.sqrt(bx * bx + by * by) / 1.05) * 0.85)


def _doppler_bar(buf, cx, cy, r0, r1, ang, hw):
    """A spoke segment from radius r0 to r1: a rotated rectangle, so two
    triangles. line() is always 1 px and there is no thick-line primitive."""
    ca, sa = math.cos(ang), math.sin(ang)
    nx, ny = -sa * hw, ca * hw
    x0, y0 = cx + r0 * ca, cy + r0 * sa
    x1, y1 = cx + r1 * ca, cy + r1 * sa
    ax, ay = int(x0 + nx), int(y0 + ny)
    bx, by = int(x1 + nx), int(y1 + ny)
    dx, dy = int(x1 - nx), int(y1 - ny)
    ex, ey = int(x0 - nx), int(y0 - ny)
    buf.triangle(ax, ay, bx, by, dx, dy)
    buf.triangle(ax, ay, dx, dy, ex, ey)


def _doppler_seg(buf, x1, y1, x2, y2, hw):
    """A thick straight segment between two loose points — two triangles."""
    dx, dy = x2 - x1, y2 - y1
    d = math.sqrt(dx * dx + dy * dy)
    if d < 1.0:
        d = 1.0
    nx, ny = -dy / d * hw, dx / d * hw
    buf.triangle(int(x1 + nx), int(y1 + ny), int(x2 + nx), int(y2 + ny),
                 int(x2 - nx), int(y2 - ny))
    buf.triangle(int(x1 + nx), int(y1 + ny), int(x2 - nx), int(y2 - ny),
                 int(x1 - nx), int(y1 - ny))


def _doppler_rim(q, w, h):
    """A point on the canvas border at perimeter distance q — a cell seed."""
    q = q % (2 * (w + h))
    if q < w:
        return (int(q), 0)
    q -= w
    if q < h:
        return (w - 1, int(q))
    q -= h
    if q < w:
        return (int(w - 1 - q), h - 1)
    return (0, int(h - 1 - (q - w)))


def _doppler(buf):
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    s = max(1, w // 160)
    cx, cy = w // 2, int(h * DPLR_MARK_Y)
    r = w * DPLR_MARK_R
    hw = r * DPLR_ARM_W

    # warm-black field, bloomed toward purple where the mark sits
    for y in range(h):
        buf.pen = color.rgb(*_doppler_lerp(DPLR_BLOOM, DPLR_FIELD,
                                   abs(y - cy) * 1.7 / max(1.0, float(h))))
        buf.rectangle(0, y, w, 1)

    # Doppler's other device: a cell field, shapes made from points on a
    # plane that never overlap and stay joined on every edge. An arrangement
    # of chords is that, and it is nine lines instead of a solver.
    buf.pen = color.rgb(DPLR_LILAC[0], DPLR_LILAC[1], DPLR_LILAC[2], 20)
    per = 2 * (w + h)
    for i in range(DPLR_CELLS):
        p0 = _doppler_rim((i * 211 + 37) % per, w, h)
        p1 = _doppler_rim((i * 373 + per // 2 + 91) % per, w, h)
        for k in range(s):
            buf.line(p0[0], p0[1] + k, p1[0], p1[1] + k)

    # the asterisk
    for k in range(6):
        ang = _BASE + k * _DOPPLER_STEP
        ca, sa = math.cos(ang), math.sin(ang)
        fused = k % 2 == 1
        r0 = 0.0 if fused else DPLR_GAP
        segs = 10 if fused else 4
        span = 1.0 - r0
        for i in range(segs):
            ra = r0 + span * i / segs
            rb = r0 + span * (i + 1) / segs
            m = (ra + rb) * 0.5
            buf.pen = color.rgb(*_doppler_brand(m * ca, m * sa))
            _doppler_bar(buf, cx, cy, ra * r - s, rb * r + s, ang, hw)
        buf.pen = color.rgb(*_doppler_brand(ca, sa))
        buf.circle(int(cx + r * ca), int(cy + r * sa), int(hw))
        if not fused:
            buf.pen = color.rgb(*_doppler_brand(r0 * ca, r0 * sa))
            buf.circle(int(cx + r0 * r * ca), int(cy + r0 * r * sa), int(hw))
    # the fused spokes meet in a filleted junction, not three crossing bars
    buf.pen = color.rgb(*_doppler_brand(0.0, 0.0))
    buf.circle(cx, cy, int(hw * 1.02))

    # the wordmark as chrome, and only where a 12 px face can be read: at
    # thumbnail sizes it would be wider than the canvas, so it drops out.
    if DPLR_WORDMARK:
        buf.font = font.sins
        tw, th = buf.measure_text("DOPPLER")
        if tw * s <= w * 0.40:
            buf.pen = color.rgb(*DPLR_SIGNAL)
            buf.rectangle(u, h - th * s - u - s, s * 2, th * s)
            buf.pen = color.rgb(*DPLR_INK)
            buf.text("DOPPLER", u + s * 4, h - th * s - u - s, s)


def _doppler_a(buf, t):
    w, h = buf.width, buf.height
    s = max(1, w // 160)
    cx, cy = w // 2, int(h * DPLR_MARK_Y)
    r = w * DPLR_MARK_R
    hw = r * DPLR_ARM_W
    # a wavefront is a STROKE, so its weight follows _stroke(), not the
    # composition unit — otherwise it vanishes in a 40 px thumbnail
    ww = max(float(s), hw * 0.13)

    # Wavefronts: the cell around the mark — a hexagon whose corners sit on
    # the six spokes — leaves the tips and swells off the canvas, another
    # behind it. Each edge carries the colour of the spoke it hangs off, so
    # the front really is red-shifted on one side and blue on the other.
    # Whole waves per loop, and sin(pi*p) is zero at both ends of a front's
    # life, so nothing is caught mid-flight when t wraps.
    for i in range(DPLR_WAVES):
        p = (t * DPLR_WAVE_TURNS + float(i) / DPLR_WAVES) % 1.0
        a = int(DPLR_WAVE_ALPHA * math.sin(math.pi * p))
        if a < 3:
            a = 3
        rw = r * (1.22 + p * 1.45)
        qx = cx + rw * math.cos(_BASE - _DOPPLER_STEP)
        qy = cy + rw * math.sin(_BASE - _DOPPLER_STEP)
        for k in range(6):
            ang = _BASE + k * _DOPPLER_STEP
            ca, sa = math.cos(ang), math.sin(ang)
            nx, ny = cx + rw * ca, cy + rw * sa
            c = _doppler_lerp(_doppler_brand(ca, sa), DPLR_LILAC, 0.45)
            buf.pen = color.rgb(c[0], c[1], c[2], a)
            _doppler_seg(buf, qx, qy, nx, ny, ww)
            qx, qy = nx, ny

    # a charge running out along each fused spoke, one third of a beat apart,
    # in the fluorescent green Doppler keeps for live things
    for i, k in enumerate((1, 3, 5)):
        p = (t * DPLR_PULSE_TURNS + i / 3.0) % 1.0
        a = int(250 * min(1.0, 5.0 * math.sin(math.pi * p)))
        rc = (0.32 + 0.70 * p) * r
        buf.pen = color.rgb(DPLR_SIGNAL[0], DPLR_SIGNAL[1], DPLR_SIGNAL[2], a)
        _doppler_bar(buf, cx, cy, rc - r * 0.13, rc + r * 0.13, _BASE + k * _DOPPLER_STEP,
             hw * 0.42)

# ── POSTHOG ───────────────────────────────────────────
# POSTHOG - the hedgehog logomark cropped huge on paper, jumping head-first.

# @skinlab {"type":"color","label":"Paper","group":"Palette"}
HOG_PAPER = (238, 239, 233)


# @skinlab {"type":"color","label":"Spike 1 (blue)","group":"Palette"}
HOG_BLUE = (2, 85, 255)


# @skinlab {"type":"color","label":"Spike 2 (red)","group":"Palette"}
HOG_RED = (239, 60, 0)


# @skinlab {"type":"color","label":"Spike 3 (yellow)","group":"Palette"}
HOG_YELLOW = (255, 183, 0)


# @skinlab {"type":"color","label":"Head","group":"Palette"}
HOG_INK = (17, 17, 17)


# @skinlab {"type":"number","label":"Mark width","group":"Layout","min":0.7,"max":1.6,"step":0.05}
HOG_WIDTH = 1.05


# @skinlab {"type":"number","label":"Ground line","group":"Layout","min":0.62,"max":0.96,"step":0.01}
HOG_BASE = 0.9


# @skinlab {"type":"integer","label":"Dashed rules","group":"Details","min":0,"max":4,"step":1}
HOG_RULES = 2


# @skinlab {"type":"integer","label":"Jumps per loop","group":"Motion","min":1,"max":4,"step":1}
HOG_JUMPS = 2


# @skinlab {"type":"number","label":"Jump height","group":"Motion","min":0,"max":0.45,"step":0.01}
HOG_HOP = 0.17


# @skinlab {"type":"number","label":"Airtime","group":"Motion","min":0.3,"max":1,"step":0.05}
HOG_AIR = 0.8


# @skinlab {"type":"number","label":"Part stagger","group":"Motion","min":0,"max":0.22,"step":0.01}
HOG_STAGGER = 0.1


# @skinlab {"type":"boolean","label":"Ground shadows","group":"Details"}
HOG_SHADOWS = True


# @skinlab {"type":"boolean","label":"Facet shading","group":"Look"}
HOG_FACETS = True


_SPIKES = ((0.0, 10.74, 4.54), (10.74, 21.96, 15.30), (21.96, 33.28, 26.63))


_TOP_L = 2.66     # where a spike's top edge meets its own left side


_TOP_M = 1.65     # midpoint of the rounded top-left corner ...


_TOP_MY = 0.22    # ... which is a 2.66-radius arc, not a chamfer


_TOP_P = 0.80     # the peak of the spike


_SLOPE = 1.03     # the 45-degree fall, in mark units


_FACET_A = 7.50   # first tonal division, at the spike's left side


_FACET_B = 18.23  # second tonal division


_HEAD = ((33.28, 7.75), (47.01, 21.96), (51.66, 25.22), (49.50, 28.0),
         (33.28, 28.0))


_EYE = (39.20, 21.76, 1.78)


_MARK_W = 52.0


_MARK_H = 28.0


_SHADOW_H = 1.7


_RULE_DASHES = 20


def _posthog_layout(buf):
    w, h = buf.width, buf.height
    mw = HOG_WIDTH * w
    sc = mw / _MARK_W
    base = h * HOG_BASE
    return w, h, sc, (w - mw) * 0.5, base - _MARK_H * sc, base


def _posthog_lit(c):
    """A spike's upper band. PostHog gives each band its own gradient; this
    tint lands on the published light stops (#0255FF -> #3F80FF, #EF3C00 ->
    #FF651E, #FFB700 -> #FFD849) and still tracks a recoloured spike."""
    if not HOG_FACETS:
        return c
    return (min(255, c[0] + 55), min(255, c[1] + 40), min(255, c[2] + 45))


def _posthog_dim(c):
    """A spike's lower band. Warm-biased, because the mark's dark stops go
    amber rather than olive (#FFB700 -> #FF9500)."""
    if not HOG_FACETS:
        return c
    return (c[0] * 92 // 100, c[1] * 78 // 100, c[2] * 78 // 100)


def _posthog_shade(c):
    """Paper in shadow: the dashed-rule grey (#D0D1C9) against #EEEFE9."""
    return (c[0] * 7 // 8, c[1] * 7 // 8, c[2] * 7 // 8)


def _posthog_spike(buf, sc, ox, oy, foot, spike, core):
    xa, xb, xp = spike
    ia, ib, ip = int(ox + xa * sc), int(ox + xb * sc), int(ox + xp * sc)
    im = int(ox + (xa + _TOP_M) * sc)
    yl, ym, yp = (int(oy + _TOP_L * sc), int(oy + _TOP_MY * sc),
                  int(oy + _TOP_P * sc))
    yr = int(oy + (_TOP_P + _SLOPE * (xb - xp)) * sc)
    fa, fb = (int(oy + _FACET_A * sc),
              int(oy + (_FACET_A + _SLOPE * (xb - xa)) * sc))
    # upper band: rounded corner, spike tip, the 45-degree fall, first division
    buf.pen = color.rgb(*_posthog_lit(core))
    buf.triangle(ia, yl, im, ym, ip, yp)
    buf.triangle(ia, yl, ip, yp, ib, yr)
    buf.triangle(ia, yl, ib, yr, ib, fb)
    buf.triangle(ia, yl, ib, fb, ia, fa)
    # middle band, down to the foot
    buf.pen = color.rgb(*core)
    buf.rectangle(ia, fb, ib - ia, foot - fb)
    buf.triangle(ia, fa, ib, fb, ia, fb)
    # lower band: the wedge the second division cuts off the bottom corner
    buf.pen = color.rgb(*_posthog_dim(core))
    buf.triangle(ia, int(oy + _FACET_B * sc),
                 int(ox + (xa + (_MARK_H - _FACET_B) / _SLOPE) * sc), foot,
                 ia, foot)


def _posthog_head(buf, sc, ox, oy, foot):
    px = [int(ox + p[0] * sc) for p in _HEAD]
    py = [int(oy + p[1] * sc) for p in _HEAD]
    py[3] = py[4] = foot
    buf.pen = color.rgb(*HOG_INK)
    buf.triangle(px[0], py[0], px[1], py[1], px[2], py[2])
    buf.triangle(px[0], py[0], px[2], py[2], px[3], py[3])
    buf.triangle(px[0], py[0], px[3], py[3], px[4], py[4])
    buf.pen = color.rgb(*HOG_PAPER)
    buf.circle(int(ox + _EYE[0] * sc), int(oy + _EYE[1] * sc),
               max(1, int(_EYE[2] * sc + 0.5)))


def _posthog_shadow(buf, sc, ox, base, xa, xb, lift):
    span = (xb - xa) * sc
    wide = span * (1.0 - 0.34 * lift)
    buf.pen = color.rgb(*_posthog_shade(HOG_PAPER))
    buf.rectangle(int(ox + xa * sc + (span - wide) * 0.5), int(base),
                  max(1, int(wide)), max(1, int(_SHADOW_H * sc)))


def _posthog_rule(buf, w, y, dash, weight):
    buf.pen = color.rgb(*_posthog_shade(HOG_PAPER))
    x = 0
    while x < w:
        buf.rectangle(x, y, dash, weight)
        x += dash * 2


def _posthog_lift(t, part):
    """How high one part is, 0..1. The head (part 3) leaves the ground first
    and the spikes follow right to left - the stagger `@posthog/brand`'s
    Logomark uses. HOG_JUMPS is a whole count per loop, so t wraps clean."""
    p = (t * HOG_JUMPS - HOG_STAGGER * (4 - part)) % 1.0
    if p >= HOG_AIR:
        return 0.0
    return math.sin(math.pi * p / HOG_AIR)


def _posthog_draw(buf, sc, ox, oy, foot, part):
    if part < 3:
        _posthog_spike(buf, sc, ox, oy, foot, _SPIKES[part],
               (HOG_BLUE, HOG_RED, HOG_YELLOW)[part])
    else:
        _posthog_head(buf, sc, ox, oy, foot)


def _posthog(buf):
    w, h, sc, ox, oy, base = _posthog_layout(buf)
    buf.pen = color.rgb(*HOG_PAPER)
    buf.clear()

    # A FIXED dash COUNT, not a fixed dash length: `w // 34` gave 20 dashes at
    # 160 and 18 at 320, so the rule's rhythm -- and the primitive count --
    # changed with resolution. That is the documented HEX FIELD class.
    dash, weight = max(1, w // (_RULE_DASHES * 2)), max(1, w // 160)
    for i in range(HOG_RULES):
        _posthog_rule(buf, w, int(oy * (i + 1) / (HOG_RULES + 1)), dash, weight)
    _posthog_rule(buf, w, int(base + _SHADOW_H * sc), dash, weight)

    foot = int(base)
    for i in range(4):
        span = _SPIKES[i] if i < 3 else (_HEAD[0][0], _HEAD[2][0], 0)
        if HOG_SHADOWS:
            _posthog_shadow(buf, sc, ox, base, span[0], span[1], 0.0)
        _posthog_draw(buf, sc, ox, oy, foot, i)


def _posthog_a(buf, t):
    w, h, sc, ox, oy, base = _posthog_layout(buf)
    hop = HOG_HOP * _MARK_H * sc
    tail = int(base + _SHADOW_H * sc)
    for i in range(4):
        lift = _posthog_lift(t, i)
        dy = -hop * lift
        span = _SPIKES[i] if i < 3 else (_HEAD[0][0], _HEAD[2][0], 0)
        ia, foot = int(ox + span[0] * sc), int(base + dy)
        # the strip the part has just left, plus its old shadow
        buf.pen = color.rgb(*HOG_PAPER)
        buf.rectangle(ia, foot, int(ox + span[1] * sc) - ia + 1, tail - foot)
        if HOG_SHADOWS:
            _posthog_shadow(buf, sc, ox, base, span[0], span[1], lift)
        _posthog_draw(buf, sc, ox, oy + dy, foot, i)

# ── ANTHROPIC ───────────────────────────────────────────
# Anthropic's coral burst thrown huge across brand cream, its twelve rays breathing.

# @skinlab {"type":"color","label":"Cream","group":"Palette"}
ANTH_CREAM = (240, 238, 230)


# @skinlab {"type":"color","label":"Coral","group":"Palette"}
ANTH_CORAL = (217, 119, 87)


# @skinlab {"type":"color","label":"Echo","group":"Palette"}
ANTH_ECHO = (232, 230, 220)


# @skinlab {"type":"color","label":"Ink","group":"Palette"}
ANTH_INK = (20, 20, 19)


# @skinlab {"type":"number","label":"Burst size","group":"Layout","min":0.3,"max":0.9,"step":0.02}
ANTH_SIZE = 0.72


# @skinlab {"type":"number","label":"Burst height","group":"Layout","min":0.2,"max":0.8,"step":0.02}
ANTH_CENTRE = 0.46


# @skinlab {"type":"number","label":"Echo size","group":"Layout","min":1.0,"max":2.4,"step":0.05}
ANTH_ECHO_SIZE = 1.5


# @skinlab {"type":"number","label":"Ray weight","group":"Shape","min":0.06,"max":0.32,"step":0.01}
ANTH_WEIGHT = 0.18


# @skinlab {"type":"number","label":"Core","group":"Shape","min":0.0,"max":0.45,"step":0.01}
ANTH_CORE = 0.22


# @skinlab {"type":"boolean","label":"Round tips","group":"Shape"}
ANTH_TIPS = True


# @skinlab {"type":"integer","label":"Breaths per loop","group":"Motion","min":1,"max":6,"step":1}
ANTH_BREATHS = 2


# @skinlab {"type":"number","label":"Breath depth","group":"Motion","min":0.0,"max":0.4,"step":0.02}
ANTH_REACH = 0.24


# @skinlab {"type":"integer","label":"Sways per loop","group":"Motion","min":0,"max":4,"step":1}
ANTH_SWAYS = 1


# @skinlab {"type":"number","label":"Sway degrees","group":"Motion","min":0.0,"max":10.0,"step":0.5}
ANTH_SWAY = 4.0


# @skinlab {"type":"boolean","label":"Show wordmark","group":"Details"}
ANTH_WORDMARK = True


# @skinlab {"type":"text","label":"Wordmark text","group":"Details"}
ANTH_LABEL = "ANTHROPIC"


_RAYS = (
    (13.78, 0.932, 0.95),
    (42.08, 0.937, 0.72),
    (57.10, 0.901, 1.04),
    (92.97, 0.912, 0.88),
    (124.18, 0.904, 0.83),
    (146.61, 0.863, 0.93),
    (181.03, 0.911, 0.73),
    (213.75, 0.927, 1.18),
    (244.26, 1.000, 1.34),
    (279.92, 0.898, 1.00),
    (310.94, 0.936, 1.48),
    (351.45, 0.915, 0.93),
)


_TAPER = 0.82      # half-width at the tip, against the ray's nominal weight


_ROOT = 1.15       # half-width where the stroke leaves the merged centre: the


_ECHO_TURN = 15.0  # the ghost sits half a ray-step round, so it fills the gaps


def _anthropic_geometry(buf):
    """Centre and radius of the mark, as fractions of the canvas."""
    return (buf.width // 2,
            int(buf.height * ANTH_CENTRE),
            buf.height * ANTH_SIZE)


def _anthropic_ray(buf, cx, cy, ang, r0, r1, hw0, hw1):
    """One tapered stroke from radius r0 to r1: a quad, so two triangles."""
    ca, sa = math.cos(ang), math.sin(ang)
    ax, ay = cx + r0 * ca, cy + r0 * sa
    bx, by = cx + r1 * ca, cy + r1 * sa
    p0x, p0y = int(ax - sa * hw0), int(ay + ca * hw0)
    p1x, p1y = int(ax + sa * hw0), int(ay - ca * hw0)
    p2x, p2y = int(bx + sa * hw1), int(by - ca * hw1)
    p3x, p3y = int(bx - sa * hw1), int(by + ca * hw1)
    buf.triangle(p0x, p0y, p1x, p1y, p2x, p2y)
    buf.triangle(p0x, p0y, p2x, p2y, p3x, p3y)


def _anthropic_flat(i):
    """A `grow` that does not grow: the still echo behind the mark.

    A named function rather than an inline anonymous one, because
    `extract-skins.py` refuses a Lambda -- a skin using one validates cleanly
    and then cannot be installed or opened in Skin Lab.
    """
    return 1.0


def _anthropic_burst(buf, cx, cy, radius, turn, flare, grow):
    """The whole mark. `grow(i)` scales ray i and `flare` fattens the roots, so
    one routine draws the still ghost and the breathing foreground alike."""
    for i in range(len(_RAYS)):
        ang, reach, weight = _RAYS[i]
        a = math.radians(ang + turn)
        hw = radius * ANTH_WEIGHT * weight * 0.5
        tip = hw * _TAPER
        end = radius * reach * grow(i)
        if ANTH_TIPS:
            end = end - tip
            _anthropic_ray(buf, cx, cy, a, 0.0, end, hw * flare, tip)
            buf.circle(int(cx + end * math.cos(a)),
                       int(cy + end * math.sin(a)), max(1, int(tip)))
        else:
            _anthropic_ray(buf, cx, cy, a, 0.0, end, hw * flare, tip)


def _anthropic_wordmark(buf):
    """The company name, ink on whatever is under it.

    A ROM face is a fixed pixel height, so a wordmark that is quiet chrome on
    the panel would be a third of a 40x30 contact-sheet cell: draw it only
    where a line of it stays under an eighth of the picture. It is drawn in
    render() so a still consumer still gets it, and again at the end of
    animate() because the rays are redrawn every frame and would otherwise
    swallow it.
    """
    if not ANTH_WORDMARK:
        return
    w, h = buf.width, buf.height
    u = max(1, w // 40)
    try:
        buf.font = font.sins
        scale = max(1, w // 160)
        _tw, th = buf.measure_text(ANTH_LABEL)
        if int(th) * scale * 8 <= h:
            buf.pen = color.rgb(*ANTH_INK)
            buf.text(ANTH_LABEL, u * 2, h - int(th) * scale - u, scale)
    except Exception:
        pass


def _anthropic(buf):
    cx, cy, radius = _anthropic_geometry(buf)

    buf.pen = color.rgb(*ANTH_CREAM)
    buf.clear()

    # A second, larger mark in the paper's own warm grey: depth without noise,
    # and no translucency, because a big alpha wash reads as a grey plate.
    buf.pen = color.rgb(*ANTH_ECHO)
    _anthropic_burst(buf, cx, cy, radius * ANTH_ECHO_SIZE, _ECHO_TURN, 1.0, _anthropic_flat)

    # The core is a disc, so it is the one part of the mark rotation cannot
    # move: it holds still in render() and gives the nickname flat brand
    # colour to sit on instead of twelve moving edges.
    buf.pen = color.rgb(*ANTH_CORAL)
    buf.circle(cx, cy, max(1, int(radius * ANTH_CORE)))

    _anthropic_wordmark(buf)


def _anthropic_a(buf, t):
    cx, cy, radius = _anthropic_geometry(buf)
    # Whole-mark sway and per-ray breath are both whole counts per loop, so
    # both land back on their starting value when t wraps.
    turn = ANTH_SWAY * math.sin(t * 2 * math.pi * ANTH_SWAYS)
    span = 2 * math.pi * ANTH_BREATHS
    step = 2 * math.pi / len(_RAYS)
    base = 1.0 - ANTH_REACH

    def grow(i):
        # The breath travels round the mark instead of pulsing in unison, so
        # the burst reads as radiating rather than as a beating dot.
        return base + ANTH_REACH * (0.5 + 0.5 * math.sin(span * t - i * step))

    buf.pen = color.rgb(*ANTH_CORAL)
    _anthropic_burst(buf, cx, cy, radius, turn, _ROOT, grow)
    _anthropic_wordmark(buf)


# ── PG SLEEP ───────────────────────────────────────────
# PG_SLEEP -- the reference SQL editor mid-query: select pg_sleep(Infinity);

# @skinlab {"type":"color","label":"Editor background","group":"Palette"}
BG = (24, 24, 24)


# @skinlab {"type":"color","label":"Text & spinner","group":"Palette"}
INK = (216, 216, 216)


# @skinlab {"type":"color","label":"Keyword","group":"Palette"}
KEYWORD = (86, 156, 214)


# @skinlab {"type":"color","label":"Brackets","group":"Palette"}
BRACKET = (255, 213, 79)


# @skinlab {"type":"color","label":"Argument","group":"Palette"}
VALUE = (181, 206, 168)


# @skinlab {"type":"integer","label":"Spinner turns per loop","group":"Motion","min":1,"max":8,"step":1}
SPIN = 5


# @skinlab {"type":"text","label":"Sleep argument","group":"Details"}
ARG = "Infinity"


# @skinlab {"type":"text","label":"Status text","group":"Details"}
STATUS = "Running..."


GAP = 0.2      # fraction of the circle that is open (keep < 0.5)


REST = 0.65    # where the gap sits at t = 0, in turns (matches the still)


def _pg_sleep_layout(w, h):
    u = max(1, w // 40)
    top_h = max(3, h // 12)                                # chrome strip
    sep_y = h * 7 // 10                                    # editor/results divider
    cy = (sep_y + h) // 2                                  # results bar centreline
    r_out = max(3, h // 16)                                # spinner outer radius
    r_in = max(1, r_out - max(1, (r_out * 2 + 4) // 9))    # stroke ~ 2/9 of radius
    cx = u * 2 + r_out
    return u, top_h, sep_y, cx, cy, r_in, r_out


def _pg_sleep_lift(c, k):
    return (min(255, c[0] + k), min(255, c[1] + k), min(255, c[2] + k))


def _pg_sleep_spinner(buf, w, h, phase):
    """The arc as a disc, a punched hole, and a background wedge: 3 calls."""
    u, top_h, sep_y, cx, cy, r_in, r_out = _pg_sleep_layout(w, h)
    buf.pen = color.rgb(*INK)
    buf.circle(cx, cy, r_out)
    buf.pen = color.rgb(*BG)
    buf.circle(cx, cy, r_in)
    a = (phase % 1.0) * 2.0 * math.pi
    half = GAP * math.pi
    d = r_out / max(0.25, math.cos(half)) + 2              # just past the ring
    buf.triangle(
        cx, cy,
        int(cx + d * math.cos(a - half)), int(cy + d * math.sin(a - half)),
        int(cx + d * math.cos(a + half)), int(cy + d * math.sin(a + half)),
    )


def _pg_sleep(buf):
    w, h = buf.width, buf.height
    u, top_h, sep_y, cx, cy, r_in, r_out = _pg_sleep_layout(w, h)

    # editor background
    buf.pen = color.rgb(*BG)
    buf.clear()

    # darker chrome strip along the top, faint scroll nub at its right end
    buf.pen = color.rgb(BG[0] * 2 // 3, BG[1] * 2 // 3, BG[2] * 2 // 3)
    buf.rectangle(0, 0, w, top_h)
    buf.pen = color.rgb(INK[0], INK[1], INK[2], 110)
    buf.rectangle(w - u, 0, max(1, u // 3), top_h * 2 // 3)

    # the query on its current-line highlight (filled box, subtle border)
    buf.font = font.winds
    th1 = max(1, buf.measure_text("pg")[1])
    sc = max(1, (h // 10) // th1)                          # text scale at hi-res
    th = th1 * sc
    sw = buf.measure_text("a a")[0] - buf.measure_text("aa")[0]
    sw = sw * sc if sw > 0 else max(2, u)

    box_y = top_h + 2
    box_h = th + u
    buf.pen = color.rgb(*_pg_sleep_lift(BG, 26))
    buf.rectangle(u // 2, box_y, w - u // 2, box_h)
    buf.pen = color.rgb(*_pg_sleep_lift(BG, 9))
    buf.rectangle(u // 2 + 1, box_y + 1, w - u // 2 - 2, box_h - 2)

    # syntax colours, in the reference's order
    segs = [
        ("select", KEYWORD),
        (None, None),                    # the space, advanced by hand
        ("pg_sleep", INK),
        ("(", BRACKET),
        (ARG, VALUE),
        (")", BRACKET),
        (";", INK),
    ]
    total = 0
    for s, c in segs:
        total += sw if s is None else buf.measure_text(s)[0] * sc
    x = u + 1
    if x + total > w - 1:                # a long argument slides left, then
        x = max(0, w - 1 - total)        # clips off the right, editor-style
    y = box_y + (box_h - th) // 2
    for s, c in segs:
        if s is None:
            x += sw
            continue
        buf.pen = color.rgb(*c)
        buf.text(s, x, y, sc)
        x += buf.measure_text(s)[0] * sc

    # divider above the results bar
    buf.pen = color.rgb(*_pg_sleep_lift(BG, 36))
    buf.rectangle(0, sep_y, w, 1)

    # status text; spinner baked at rest so the static thumbnail shows it too
    buf.pen = color.rgb(*INK)
    sth = buf.measure_text(STATUS)[1] * sc
    buf.text(STATUS, cx + r_out + u, cy - sth // 2, sc)
    _pg_sleep_spinner(buf, w, h, REST)


def _pg_sleep_a(buf, t):
    # SPIN whole turns per 4 s loop -> seamless wrap; 3 calls per frame,
    # everything else lives in render()'s saved background.
    _pg_sleep_spinner(buf, buf.width, buf.height, t * SPIN + REST)


# ── SUPABASE SELECT ───────────────────────────────────────────
# SUPABASE SELECT -- the event poster, as a tile grid with the wearer in it.

# @skinlab {"type":"color","label":"Frame","group":"Palette"}
SELECT_FRAME = (47, 167, 106)


# @skinlab {"type":"color","label":"Dark tile","group":"Palette"}
SELECT_DARK = (0, 0, 0)


# @skinlab {"type":"color","label":"Grey tile","group":"Palette"}
SELECT_GREY = (107, 111, 119)


# @skinlab {"type":"color","label":"Light tile","group":"Palette"}
SELECT_LIGHT = (255, 255, 255)


# @skinlab {"type":"color","label":"Accent","group":"Palette"}
SELECT_ACCENT = (47, 167, 106)


# @skinlab {"type":"number","label":"Frame thickness","group":"Layout","min":0.01,"max":0.09,"step":0.005}
SELECT_FRAME_FY = 0.038


# @skinlab {"type":"number","label":"Name band top","group":"Layout","min":0.20,"max":0.36,"step":0.005}
SELECT_BAND_TOP = 0.275


# @skinlab {"type":"number","label":"Name band bottom","group":"Layout","min":0.50,"max":0.70,"step":0.005}
SELECT_BAND_BOTTOM = 0.630


# @skinlab {"type":"integer","label":"Spark pulses per loop","group":"Motion","min":1,"max":6,"step":1}
SELECT_PULSE = 2


# @skinlab {"type":"integer","label":"Arrow chase steps per loop","group":"Motion","min":1,"max":8,"step":1}
SELECT_CHASE = 4


SELECT_GLYPHS = {
    "S": ("#####", "#....", "#....", "#####", "....#", "....#", "#####"),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#####"),
    "P": ("#####", "#...#", "#...#", "#####", "#....", "#....", "#...."),
    "A": ("..#..", ".#.#.", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "2": ("####.", "....#", "....#", ".###.", "#....", "#....", "#####"),
    "6": (".####", "#....", "#....", "#####", "#...#", "#...#", "#####"),
    "(": ("..##.", ".##..", "##...", "##...", "##...", ".##..", "..##."),
    ")": (".##..", "..##.", "...##", "...##", "...##", "..##.", ".##.."),
}


SELECT_SPARK = ("...##...", "..###...", ".####...", "#####...",
         "########", "...#####", "...####.", "...###..",
         "...##...", "...#....")


SELECT_ARROW = ("..#####", "..#####", "....###", "...###.",
         "..###..", ".###...", "###....", "##.....")


def _supabase_select_cell(buf):
    """One block edge in pixels. The whole poster is a multiple of this."""
    return max(1, int(buf.height * 0.0135))


def _supabase_select_grid(buf, rows, x, y, px, ink):
    """Blit a block table. One rectangle per RUN, not per pixel."""
    buf.pen = ink
    for ry, row in enumerate(rows):
        run = 0
        for rx in range(len(row) + 1):
            on = rx < len(row) and row[rx] == "#"
            if on:
                run += 1
            elif run:
                buf.rectangle(x + (rx - run) * px, y + ry * px, run * px, px)
                run = 0


def _supabase_select_word(buf, text, x, y, px, ink):
    """Blocks for a word, 5 wide plus one column of tracking."""
    for i, ch in enumerate(text):
        rows = SELECT_GLYPHS.get(ch)
        if rows:
            _supabase_select_grid(buf, rows, x + i * px * 6, y, px, ink)


def _supabase_select_layout(buf):
    w, h = buf.width, buf.height
    m = max(1, int(h * SELECT_FRAME_FY))
    ix, iy = m, m
    iw, ih = w - 2 * m, h - 2 * m
    top = int(h * SELECT_BAND_TOP)
    bottom = int(h * SELECT_BAND_BOTTOM)
    return m, ix, iy, iw, ih, top, bottom


def _supabase_select_static(buf):
    """Everything but the two moving tiles' contents."""
    w, h = buf.width, buf.height
    m, ix, iy, iw, ih, top, bottom = _supabase_select_layout(buf)
    px = _supabase_select_cell(buf)

    buf.pen = color.rgb(*SELECT_FRAME)
    buf.clear()

    # -- top row: the spark tile, then the wordmark tile -------------------
    split = ix + int(iw * 0.34)
    buf.pen = color.rgb(*SELECT_DARK)
    buf.rectangle(ix, iy, split - ix, top - iy)
    buf.pen = color.rgb(*SELECT_GREY)
    buf.rectangle(split, iy, ix + iw - split, top - iy)

    # SUPA / BASE, stacked as the poster stacks them
    tw = 4 * 6 * px
    tx = split + ((ix + iw - split) - tw) // 2
    gap = px
    block = 7 * px
    ty = iy + ((top - iy) - (2 * block + gap)) // 2
    _supabase_select_word(buf, "SUPA", tx, ty, px, color.rgb(*SELECT_LIGHT))
    _supabase_select_word(buf, "BASE", tx, ty + block + gap, px, color.rgb(*SELECT_LIGHT))

    # -- the name band: one white row, which is the whole point ------------
    buf.pen = color.rgb(*SELECT_LIGHT)
    buf.rectangle(ix, top, iw, bottom - top)

    # -- bottom row: arrow tile, then the year tile ------------------------
    asplit = ix + int(iw * 0.30)
    buf.pen = color.rgb(*SELECT_GREY)
    buf.rectangle(ix, bottom, asplit - ix, iy + ih - bottom)
    buf.pen = color.rgb(*SELECT_DARK)
    buf.rectangle(asplit, bottom, ix + iw - asplit, iy + ih - bottom)

    yw = 4 * 6 * px
    yx = asplit + ((ix + iw - asplit) - yw) // 2
    yy = bottom + ((iy + ih - bottom) - 7 * px) // 2
    _supabase_select_word(buf, "(", yx, yy, px, color.rgb(*SELECT_LIGHT))
    _supabase_select_word(buf, "26", yx + 6 * px, yy, px, color.rgb(*SELECT_ACCENT))
    _supabase_select_word(buf, ")", yx + 18 * px, yy, px, color.rgb(*SELECT_LIGHT))


def _supabase_select_spark_at(buf):
    m, ix, iy, iw, ih, top, bottom = _supabase_select_layout(buf)
    px = _supabase_select_cell(buf)
    split = ix + int(iw * 0.34)
    return (ix + ((split - ix) - 8 * px) // 2,
            iy + ((top - iy) - 10 * px) // 2, px)


def _supabase_select_arrow_at(buf):
    m, ix, iy, iw, ih, top, bottom = _supabase_select_layout(buf)
    px = _supabase_select_cell(buf)
    asplit = ix + int(iw * 0.30)
    return (ix + ((asplit - ix) - 7 * px) // 2,
            bottom + ((iy + ih - bottom) - 8 * px) // 2, px)


def _supabase_select(buf):
    _supabase_select_static(buf)
    sx, sy, px = _supabase_select_spark_at(buf)
    _supabase_select_grid(buf, SELECT_SPARK, sx, sy, px, color.rgb(*SELECT_ACCENT))
    ax, ay, px = _supabase_select_arrow_at(buf)
    _supabase_select_grid(buf, SELECT_ARROW, ax, ay, px, color.rgb(*SELECT_LIGHT))


def _supabase_select_a(buf, t):
    """The spark pulses; the arrow's steps light in sequence. Integer rates, so
    both join themselves at the wrap."""
    sx, sy, px = _supabase_select_spark_at(buf)
    k = 0.5 + 0.5 * math.sin(((t * SELECT_PULSE) % 1.0) * 2.0 * math.pi)
    buf.pen = color.rgb(*SELECT_DARK)
    buf.rectangle(sx, sy, 8 * px, 10 * px)
    _supabase_select_grid(buf, SELECT_SPARK, sx, sy, px,
          color.rgb(int(SELECT_ACCENT[0] + (232 - SELECT_ACCENT[0]) * k * 0.55),
                    int(SELECT_ACCENT[1] + (255 - SELECT_ACCENT[1]) * k * 0.55),
                    int(SELECT_ACCENT[2] + (214 - SELECT_ACCENT[2]) * k * 0.55)))

    ax, ay, px = _supabase_select_arrow_at(buf)
    buf.pen = color.rgb(*SELECT_GREY)
    buf.rectangle(ax, ay, 7 * px, 8 * px)
    lit = int(((t * SELECT_CHASE) % 1.0) * len(SELECT_ARROW))
    for ry, row in enumerate(SELECT_ARROW):
        ink = color.rgb(*SELECT_ACCENT) if ry == len(SELECT_ARROW) - 1 - lit else color.rgb(*SELECT_LIGHT)
        _supabase_select_grid(buf, (row,), ax, ay + ry * px, px, ink)


# ── registry ───────────────────────────────────────────────────────────────

# (name, group index, render, animate-or-None, face)
SKINS = (
    ("BUILD FURNACE", 0, _g_build_furnace, _g_build_furnace_a, "futile"),
    ("CONTAINER SEA", 0, _g_container_sea, _g_container_sea_a, "bacteria"),
    ("INTERLOCK", 0, _g_interlock, None, "ignore"),
    ("OXIDE", 0, _oxide, _oxide_anim, "curse"),
    ("SUPABASE", 0, _supabase, _supabase_anim, "badgewaremax"),
    ("TERMINAL", 0, _terminal, _terminal_anim, "smart"),
    ("TRACE MAP", 0, _g_trace_map, _g_trace_map_a, "absolute"),
    ("AMBER", 1, _amber, _amber_a, "yesterday"),
    ("BBS ANSI ART", 1, _g_bbs_ansi_art, _g_bbs_ansi_art_a, "badgeware"),
    ("BLUESCREEN", 1, _bluescreen, _bluescreen_a, "bacteria"),
    ("C64 READY.", 1, _g_c64_ready, _g_c64_ready_a, "badgewaremax"),
    ("CRT", 1, _crt, _crt_anim, "curse"),
    ("DMG BOOT", 1, _g_dmg_boot, _g_dmg_boot_a, "smart"),
    ("FLOPPY 1.44M", 1, _g_floppy_1_44m, None, "absolute"),
    ("OSCILLOSCOPE", 1, _g_oscilloscope, _g_oscilloscope_a, "outflank"),
    ("PLASMA", 1, _plasma, _plasma_anim, "more"),
    ("VECTOR", 1, _vector, _vector_anim, "ignore"),
    ("VHS TRACKING", 1, _g_vhs_tracking, _g_vhs_tracking_a, "unfair"),
    ("AURORA", 2, _aurora, _aurora_anim, "manticore"),
    ("FIREFLY WOOD", 2, _g_firefly_wood, _g_firefly_wood_a, "salty"),
    ("LAST TRAIN", 2, _g_last_train, _g_last_train_a, "yesterday"),
    ("LATE SHIFT", 2, _g_late_shift, _g_late_shift_a, "vest"),
    ("OUTER RIM", 2, _g_outer_rim, _g_outer_rim_a, "ignore"),
    ("RED MESA", 2, _g_red_mesa, _g_red_mesa_a, "more"),
    ("RIDGELINE", 2, _g_ridgeline, _g_ridgeline_a, "manticore"),
    ("STARFIELD", 2, _starfield, _starfield_anim, "troll"),
    ("STORM CAPE", 2, _g_storm_cape, _g_storm_cape_a, "curse"),
    ("SUNKEN LIGHT", 2, _g_sunken_light, _g_sunken_light_a, "bacteria"),
    ("ARCS", 3, _arcs, _arcs_a, "ziplock"),
    ("BAUHAUS", 3, _bauhaus, None, "futile"),
    ("DIAGONAL", 3, _diagonal, _diagonal_a, "unfair"),
    ("DOT SHOCK", 3, _g_dot_shock, _g_dot_shock_a, "ziplock"),
    ("ECLIPSE", 3, _g_eclipse, _g_eclipse_a, "more"),
    ("FLOOR", 3, _floor, _floor_a, "bacteria"),
    ("GRID BREAK", 3, _g_grid_break, None, "absolute"),
    ("ISO STACK", 3, _g_iso_stack, None, "compass"),
    ("MEMPHIS BLVD", 3, _g_memphis_blvd, _g_memphis_blvd_a, "ziplock"),
    ("OP RIPPLE", 3, _g_op_ripple, _g_op_ripple_a, "outflank"),
    ("RED WEDGE", 3, _g_red_wedge, None, "futile"),
    ("RISO", 3, _riso, None, "salty"),
    ("SQUARE TUNNEL", 3, _g_square_tunnel, _g_square_tunnel_a, "ignore"),
    ("VANISH POINT", 3, _g_vanish_point, _g_vanish_point_a, "compass"),
    ("CODE RAIN", 4, _g_code_rain, _g_code_rain_a, "smart"),
    ("DATAMOSH", 4, _g_datamosh, _g_datamosh_a, "curse"),
    ("GLITCH", 4, _glitch, _glitch_anim, "troll"),
    ("HEX FIELD", 4, _hexfield, _hexfield_anim, "ignore"),
    ("RAIN", 4, _rain, _rain_anim, "salty"),
    ("SYNTHWAVE", 4, _synthwave, _synthwave_anim, "more"),
    ("BLINKY", 5, _g_blinky, _g_blinky_a, "badgewaremax"),
    ("CLAW MACHINE", 5, _g_claw_machine, _g_claw_machine_a, "ziplock"),
    ("FACE", 5, _face, _face_anim, "more"),
    ("LAVA LAMP", 5, _d1, _d1_a, "bacteria"),
    ("MIXTAPE", 5, _g_mixtape, _g_mixtape_a, "salty"),
    ("NOT LOADING", 5, _g_not_loading, _g_not_loading_a, "smart"),
    ("PARTY MODE", 5, _g_party_mode, _g_party_mode_a, "futile"),
    ("PET ROCK", 5, _g_pet_rock, _g_pet_rock_a, "badgewaremax"),
    ("STICKERBOMB", 5, _d2, None, "unfair"),
    ("TEST CARD", 5, _testcard, _testcard_anim, "bacteria"),
    ('AERO RIBBON', 6, _aero_ribbon, _aero_ribbon_a, 'futile'),
    ('AQUA GEL', 6, _aqua_gel, _aqua_gel_a, 'more'),
    ('DEW GLASS', 6, _dew_glass, _dew_glass_a, 'holotype'),
    ('PALM GLOSS', 6, _palm_gloss, _palm_gloss_a, 'compass'),
    ('REEF TANK', 6, _reef_tank, _reef_tank_a, 'bacteria'),
    ('FROSTED STACK', 7, _frosted_stack, _frosted_stack_a, 'compass'),
    ('LOUVRE', 7, _louvre, _louvre_a, 'smart'),
    ('MENISCUS', 7, _meniscus, _meniscus_a, 'bacteria'),
    ('PRISM RING', 7, _prism_ring, _prism_ring_a, 'ignore'),
    ('SHEAR', 7, _shear, _shear_a, 'futile'),
    ('BLISS HILL', 8, _bliss_hill, _bliss_hill_a, 'yesterday'),
    ('CARD CASCADE', 8, _card_cascade, _card_cascade_a, 'manticore'),
    ('MINEFIELD', 8, _minefield, _minefield_a, 'smart'),
    ('PAINTBOX', 8, _paintbox, _paintbox_a, 'bacteria'),
    ('3D PIPES', 8, _pipes_3d, _pipes_3d_a, 'troll'),
    ('CRYOSTAT', 9, _cryostat, _cryostat_a, 'manticore'),
    ('DYSON SWARM', 9, _dyson_swarm, _dyson_swarm_a, 'futile'),
    ('ION DRIVE', 9, _ion_drive, _ion_drive_a, 'ignore'),
    ('TERRAFORM', 9, _terraform, _terraform_a, 'ziplock'),
    ('VISOR', 9, _visor, _visor_a, 'compass'),
    ('VERCEL', 10, _vercel, _vercel_a, 'absolute'),
    ('STRIPE', 10, _stripe, _stripe_a, 'bacteria'),
    ('RESEND', 10, _resend, _resend_a, 'smart'),
    ('BOLT', 10, _bolt, _bolt_a, 'badgewaremax'),
    ('GRAFANA', 10, _grafana, _grafana_a, 'bacteria'),
    ('DOPPLER', 10, _doppler, _doppler_a, 'badgewaremax'),
    ('POSTHOG', 10, _posthog, _posthog_a, 'ziplock'),
    ('ANTHROPIC', 10, _anthropic, _anthropic_a, 'badgewaremax'),
    ('PG SLEEP', 11, _pg_sleep, _pg_sleep_a, 'smart'),
    ('SUPABASE SELECT', 12, _supabase_select, _supabase_select_a, 'badgewaremax'),
)

COUNT = len(SKINS)


def name(index):
    return SKINS[index][0]


def group_of(index):
    return SKINS[index][1]


def font_name(index):
    """The ROM font proposed for this skin's nickname.

    A short name only — the caller resolves it, because how it resolves depends
    on where it is drawn: `font.<name>` reads /rom/fonts/<name>.ppf directly and
    caches, while `font.load(name)` also searches /system/assets/fonts, /fonts
    and /assets. Returning the name keeps this table free of either choice.
    """
    return SKINS[index][4]


# Widest single glyph, in pixels at scale 1, for every ROM face. Measured by
# running each glyph the keyboards can produce through the pinned picovector
# rasteriser; see namebadge/tests/test_skins_fonts.py for the method. The widest
# glyph is the right number because these faces are PROPORTIONAL: a mean advance
# understates "WWWWWWW", which is exactly the name someone will type.
FONT_WIDEST = {
    "absolute": 12, "ark": 7, "awesome": 9, "bacteria": 13, "badgeware": 11,
    "badgewaremax": 13, "compass": 11, "corset": 10, "curse": 10, "desert": 7,
    "fear": 11, "futile": 19, "holotype": 10, "hungry": 8, "ignore": 17,
    "kobold": 9, "lookout": 11, "loser": 7, "manticore": 11, "match": 9,
    "memo": 9, "more": 20, "nope": 10, "outflank": 13, "saga": 12, "salty": 11,
    "sins": 7, "smart": 9, "teatime": 8, "torch": 8, "troll": 15, "unfair": 12,
    "vest": 14, "winds": 6, "yesterday": 10, "yolk": 10, "ziplock": 15,
}


def max_nickname(index, width, scale=1):
    """How many characters this skin's proposed face fits across `width`.

    The cap belongs to the skin, not the product: a display name is chosen for
    effect, so a face is allowed to be enormous and hold three characters. The
    caller decides whether to apply a further product-wide ceiling.

    `width` and `scale` are passed in rather than read from `screen` so a
    thumbnail, a LORES panel and a HIRES panel each get their own honest answer,
    and so this stays testable off-device.
    """
    return max(1, (width - 2 * scale) // (FONT_WIDEST[SKINS[index][4]] * scale))


def first_of_group(group_index):
    for index, entry in enumerate(SKINS):
        if entry[1] == group_index:
            return index
    return 0


def render(buf, index):
    SKINS[index][2](buf)


def animated(index):
    return SKINS[index][3] is not None


def animate(dst, t, index):
    handler = SKINS[index][3]
    if handler is not None:
        handler(dst, t)
