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
# badge. Rows stay CONTIGUOUS in this source because the archived namebadge
# browses `SKINS` directly; badgecard's generated catalogue has its own declared
# order and treats groups as labels. Since SKINS is append-only, an existing
# group can only be extended while it is still the tail (as LIGHT is here);
# artwork separated from its group instead takes a new group.
GROUPS = ("BRAND", "RETRO", "SCENE", "GRAPHIC", "NEON", "PLAY",
          "AERO", "GLASS", "WIN9X", "FUTURE", "SPONSOR", "DEV", "EVENT", "LIGHT")


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


_SUPA_ASPECT = 1.058967


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
    bw = bh * _SUPA_ASPECT
    if bw > w * 0.98:
        bw = w * 0.98
        bh = bw / _SUPA_ASPECT
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


# ── RETRO ──────────────────────────────────────────────────────────────────


# ── GRAPHIC ────────────────────────────────────────────────────────────────


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


# ── PALM GLOSS ───────────────────────────────────────────
# PALM GLOSS - a macro tangle of waxy tropical leaves against a blown-out sky, wet sheen running down each blade, one frond swaying in front.


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


# ── LOUVRE ───────────────────────────────────────────
# Frosted glass slats standing over a vivid light that walks along behind them.


# ── MENISCUS ───────────────────────────────────────────
# A bead of liquid glass magnifying a banded field, rim-lit with a caustic under it.


# ── PRISM RING ───────────────────────────────────────────
# A thick ring of glass whose edges split into colour, turning a glint round itself.


# ── SHEAR ───────────────────────────────────────────
# A leaning sheet of glass laid over a banded field; everything under it steps.


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


# ── DYSON SWARM ───────────────────────────────────────────
# DYSON SWARM — a star too big for the frame, its limb cutting off one corner


# ── ION DRIVE ───────────────────────────────────────────
# ION DRIVE — the underside of a ship cropped across the top of the badge,


# ── TERRAFORM ───────────────────────────────────────────
# TERRAFORM — a glass dome full of green standing on red desert under a dusty


# ── VISOR ───────────────────────────────────────────
# VISOR — the inside of an exosuit helmet: dark chrome around a letterbox of


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


# @skinlab {"type":"number","label":"Open arc fraction","group":"Motion","min":0.05,"max":0.45,"step":0.01}
GAP = 0.2      # Keep below half so the spinner still reads as one interrupted ring.


# @skinlab {"type":"number","label":"Rest angle (turns)","group":"Motion","min":0,"max":1,"step":0.01}
REST = 0.65    # Preserve the authored still while allowing a full-turn phase adjustment.


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


# ── BREATH ───────────────────────────────────────────
# BREATH -- a single aperture of light, opening and closing on black.

# @skinlab {"type": "number", "label": "Small radius", "group": "Shape", "min": 0.05, "max": 0.5, "step": 0.005}
ORB_MIN = 0.15


# @skinlab {"type": "number", "label": "Large radius", "group": "Shape", "min": 0.1, "max": 0.7, "step": 0.005}
ORB_MAX = 0.37


# @skinlab {"type": "number", "label": "Edge softness", "group": "Shape", "min": 0.05, "max": 0.6, "step": 0.005}
ORB_EDGE = 0.22


# @skinlab {"type": "number", "label": "Centre Y", "group": "Layout", "min": 0.3, "max": 0.85, "step": 0.01}
ORB_FY = 0.5


# @skinlab {"type": "number", "label": "Dim value", "group": "Palette", "min": 0.1, "max": 1.0, "step": 0.01}
GLOW_MIN = 0.49


# @skinlab {"type": "number", "label": "Bright value", "group": "Palette", "min": 0.2, "max": 1.0, "step": 0.01}
GLOW_MAX = 1.0


# @skinlab {"type": "number", "label": "Saturation", "group": "Palette", "min": 0.0, "max": 1.0, "step": 0.01}
SAT = 0.9


# @skinlab {"type": "number", "label": "Hue at t=0", "group": "Palette", "min": 0.0, "max": 360.0, "step": 5.0}
HUE_START = 0.0


# @skinlab {"type": "number", "label": "Hue turns per loop", "group": "Motion", "min": -2.0, "max": 2.0, "step": 0.5}
HUE_TURNS = 1.0


# @skinlab {"type": "number", "label": "Breath peak at", "group": "Motion", "min": 0.0, "max": 1.0, "step": 0.01}
PEAK_AT = 0.25


# @skinlab {"type": "number", "label": "Glow dwell", "group": "Motion", "min": 1.0, "max": 6.0, "step": 0.1}
GLOW_EASE = 3.3


# @skinlab {"type": "number", "label": "Size dwell", "group": "Motion", "min": 0.5, "max": 3.0, "step": 0.05}
SIZE_EASE = 1.35


# @skinlab {"type": "integer", "label": "Grain", "group": "Look", "min": 0, "max": 32}
GRAIN = 6


# @skinlab {"type": "number", "label": "Still phase", "group": "Layout", "min": 0.0, "max": 1.0, "step": 0.01}
STILL_T = 0.12


_RAMP_STOPS = 13


def _breath_ease(x, p):
    """x ** p for x in 0..1, without `pow`'s domain surprises at x == 0."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return math.exp(p * math.log(x))


def _breath_hsv(h, s, v):
    """HSV to an 8-bit triple. The reference is a fully saturated light source,
    and saturation there is a constant 0.90 with the low channel landing on 25
    of 255 -- which is 255 * (1 - 0.90) to the count, so this is the same
    parameterisation the reference used."""
    h = h - 360.0 * math.floor(h / 360.0)
    c = v * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = v - c
    if h < 60.0:
        r, g, b = c, x, 0.0
    elif h < 120.0:
        r, g, b = x, c, 0.0
    elif h < 180.0:
        r, g, b = 0.0, c, x
    elif h < 240.0:
        r, g, b = 0.0, x, c
    elif h < 300.0:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (int((r + m) * 255.0 + 0.5), int((g + m) * 255.0 + 0.5), int((b + m) * 255.0 + 0.5))


def _breath_smoothstep(u):
    if u <= 0.0:
        return 0.0
    if u >= 1.0:
        return 1.0
    return u * u * (3.0 - 2.0 * u)


def _breath_breath(t):
    """The one shared clock. Returns (radius fraction, value, hue degrees).

    `x` is a raised cosine of the loop phase, so it is 1 at the peak, 0 at the
    trough and joins itself at the wrap -- which `animate` must, because `t`
    snaps from 1 to 0 every four seconds.
    """
    x = 0.5 * (1.0 + math.cos(2.0 * math.pi * (t - PEAK_AT)))
    radius = ORB_MIN + (ORB_MAX - ORB_MIN) * _breath_ease(x, SIZE_EASE)
    value = GLOW_MIN + (GLOW_MAX - GLOW_MIN) * (1.0 - _breath_ease(1.0 - x, GLOW_EASE))
    hue = HUE_START + 360.0 * HUE_TURNS * t
    return radius, value, hue


def _breath_paint(buf, t):
    """One native gradient fill, covering the canvas.

    The whole picture is inside the brush, so this both clears and draws: the
    stop table's last entry is black and the rasteriser CLAMPS past the edge
    point (probed: a stop table ending at r=120 still reads its last colour at
    r=160), so everything outside the orb is painted black by the same call.
    That is why `animate` does not need its own clear.

    THE BRUSH SIGNATURE IS (kind, cx, cy, ex, ey, stops) -- a centre point and
    an EDGE POINT, not a centre and two radii. Probed, because a note handed to
    this lane said `(cx, cy, r0, r1)` and it is wrong in a way that still draws
    a plausible picture: `gradient(RADIAL, 160, 120, 0, 120)` behaves as radius
    160 (the distance to (0,120)), not 120, and `(160, 120, 0, 240)` as radius
    200 (the distance to (0,240)). Every radius would have been silently wrong.
    """
    w, h = buf.width, buf.height
    cx, cy = w // 2, int(h * ORB_FY)
    radius, value, hue = _breath_breath(t)

    disc = radius * h                 # radius of the half-intensity contour
    edge = ORB_EDGE * h               # half-width of the soft edge, FIXED
    outer = disc + edge
    if outer < 2.0:
        outer = 2.0
    inner = disc - edge               # start of the falloff; may be negative

    # The profile, normalised so the centre always reaches full value. Without
    # the normalisation a small orb would also be a dim one, and the reference
    # keeps its peak at the value the breath asks for while the disc shrinks
    # underneath the blur.
    lead = (0.0 - inner) / (2.0 * edge) if edge > 0.0 else 0.0
    peak = 1.0 - _breath_smoothstep(lead)
    if peak < 0.02:
        peak = 0.02

    red, green, blue = _breath_hsv(hue, SAT, value)
    stops = []
    if inner > 0.0:
        stops.append((0.0, color.rgb(red, green, blue)))
        first = inner / outer
    else:
        first = 0.0
    for i in range(_RAMP_STOPS):
        u = i / float(_RAMP_STOPS - 1)
        pos = first + (1.0 - first) * u
        d = pos * outer
        level = (1.0 - _breath_smoothstep((d - inner) / (2.0 * edge))) / peak
        if level > 1.0:
            level = 1.0
        stops.append((pos, color.rgb(int(red * level), int(green * level), int(blue * level))))

    buf.pen = brush.gradient(brush.RADIAL, cx, cy, cx, cy + int(outer), stops)
    buf.clear()

    if GRAIN > 0:
        # SCOPED TO THE ORB, not applied to the whole surface, and the reason is
        # what `noise` does at the bottom of the range: it is a signed
        # perturbation that CLAMPS, so over pure black it returns 0..GRAIN with
        # a mean of GRAIN/4 (probed: base 0, noise 10 -> range 0..10, mean 2.54).
        # Whole-surface grain therefore lifts the reference's true black into a
        # speckle, and there is nothing out there to dither anyway -- the ramp
        # has already reached zero. `brush.noise` as a PEN perturbs only the
        # pixels the shape covers (probed: inside 130, outside 0), which is the
        # same filter with a bounding box, and the box shrinks with the orb.
        #
        # In `animate` this runs before the stickers and the name are drawn, so
        # it never touches type.
        reach = int(outer) + 1
        x0 = cx - reach
        y0 = cy - reach
        if x0 < 0:
            x0 = 0
        if y0 < 0:
            y0 = 0
        x1 = cx + reach
        y1 = cy + reach
        if x1 > w:
            x1 = w
        if y1 > h:
            y1 = h
        buf.pen = brush.noise(GRAIN)
        buf.rectangle(x0, y0, x1 - x0, y1 - y0)


def _breath(buf):
    _breath_paint(buf, STILL_T)


def _breath_a(buf, t):
    _breath_paint(buf, t)

# ── SCRIM ───────────────────────────────────────────
# SCRIM -- a lit rectangle hanging in a dark room, drifting cool to warm.

# @skinlab {"type": "number", "label": "Panel width", "group": "Layout", "min": 0.1, "max": 0.5, "step": 0.005}
BOX_FW = 0.3156


# @skinlab {"type": "number", "label": "Panel height", "group": "Layout", "min": 0.1, "max": 0.5, "step": 0.005}
BOX_FH = 0.3375


# @skinlab {"type": "number", "label": "Panel centre Y", "group": "Layout", "min": 0.25, "max": 0.75, "step": 0.01}
BOX_FY = 0.5


# @skinlab {"type": "number", "label": "Edge softness", "group": "Shape", "min": 0.01, "max": 0.3, "step": 0.005}
SOFT = 0.085


# @skinlab {"type": "number", "label": "Light value", "group": "Palette", "min": 0.2, "max": 1.0, "step": 0.01}
LIGHT_V = 0.898


# @skinlab {"type": "number", "label": "Light saturation", "group": "Palette", "min": 0.0, "max": 1.0, "step": 0.01}
LIGHT_S = 0.35


# @skinlab {"type": "number", "label": "Middle hue", "group": "Palette", "min": 0.0, "max": 360.0, "step": 5.0}
HUE_MID = 120.0


# @skinlab {"type": "number", "label": "Hue swing", "group": "Motion", "min": 0.0, "max": 180.0, "step": 5.0}
HUE_SWING = 90.0


# NO `@skinlab` ANNOTATION, AND THAT IS DELIBERATE RATHER THAN AN OVERSIGHT.
# One carrying `"type": "color"` stood here until 2026-08-28 and produced NO
# control: Skin Lab's colour literal is an `(r, g, b)` TUPLE
# (`skinlab/src/lib/python-parameters.ts`, `literalPrefix`), and a hex int
# matches neither that nor the number pattern, so the parser returned nothing
# at all.  It was invisible while this module was a standalone exemplar and
# `verify-catalogue-parameters.mjs` failed the moment it entered the catalogue
# -- 11 annotations, 10 controls.  The annotation is dropped rather than the
# constant rewritten: `_scrim_paint` decomposes ROOM with shifts, so the hex is
# the artwork and the promise of a slider was the wrong half.
ROOM = 0x06060A


# @skinlab {"type": "integer", "label": "Grain", "group": "Look", "min": 0, "max": 32}
SCRIM_GRAIN = 6


# @skinlab {"type": "number", "label": "Still phase", "group": "Layout", "min": 0.0, "max": 1.0, "step": 0.01}
SCRIM_STILL_T = 0.0


_EDGE_STOPS = 13


_SIGMAS = 3.0


def _scrim_hsv(h, s, v):
    """HSV to an 8-bit triple. The reference's low channel sits on 149 with a
    high of 229, which is exactly V 0.898 at S 0.35, so this is the same
    parameterisation it used."""
    h = h - 360.0 * math.floor(h / 360.0)
    c = v * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = v - c
    if h < 60.0:
        r, g, b = c, x, 0.0
    elif h < 120.0:
        r, g, b = x, c, 0.0
    elif h < 180.0:
        r, g, b = 0.0, c, x
    elif h < 240.0:
        r, g, b = 0.0, x, c
    elif h < 300.0:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (int((r + m) * 255.0 + 0.5), int((g + m) * 255.0 + 0.5), int((b + m) * 255.0 + 0.5))


def _scrim_cdf(z):
    """Normal CDF via the logistic approximation, which is what the reference's
    edge measures as. Clamped because `exp` of a large argument overflows and
    the answer past three sigma is a constant anyway."""
    if z > 8.0:
        return 1.0
    if z < -8.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-1.702 * z))


def _scrim_edge_stops(sigma, colour, room, alpha):
    """One soft edge as a stop table, running the FULL length of the gradient.

    `alpha` picks which of the two passes this is. False gives an opaque ramp
    from the room to the light, which is pass 1. True gives the room at an
    alpha that falls from 255 to 0, which is pass 2 -- and pass 2 is a multiply
    because "over" is a lerp; see the header.
    """
    stops = []
    # Rescaled so the two ends land on EXACTLY 0 and 1. Truncating the logistic
    # at three sigma leaves it at 0.994, and since the brush clamps past its end
    # point that 0.6% became a flat 1.5-count deficit over the whole plateau --
    # which a fit then tried to pay for by raising the light's value, i.e. by
    # making the whole artwork brighter to fix an edge-table rounding.
    lo = _scrim_cdf(-_SIGMAS)
    span = _scrim_cdf(_SIGMAS) - lo
    for i in range(_EDGE_STOPS):
        pos = i / float(_EDGE_STOPS - 1)
        level = (_scrim_cdf((pos * 2.0 - 1.0) * _SIGMAS) - lo) / span
        if alpha:
            stops.append((pos, color.rgb(room[0], room[1], room[2],
                                         int(255.0 * (1.0 - level) + 0.5))))
        else:
            stops.append((pos, color.rgb(
                int(room[0] + (colour[0] - room[0]) * level + 0.5),
                int(room[1] + (colour[1] - room[1]) * level + 0.5),
                int(room[2] + (colour[2] - room[2]) * level + 0.5))))
    return stops


def _scrim_paint(buf, t):
    w, h = buf.width, buf.height
    cx, cy = w // 2, int(h * BOX_FY)
    half_w = BOX_FW * w
    half_h = BOX_FH * h
    sigma = SOFT * h
    reach = _SIGMAS * sigma
    if reach < 1.0:
        reach = 1.0

    room = ((ROOM >> 16) & 0xFF, (ROOM >> 8) & 0xFF, ROOM & 0xFF)
    light = _scrim_hsv(HUE_MID + HUE_SWING * math.sin(2.0 * math.pi * t), LIGHT_S, LIGHT_V)

    # PASS 1 -- the horizontal profile, opaque, one gradient per half. Each
    # gradient runs from the OUTSIDE of its edge inwards, so the brush's clamp
    # past the end point paints the plateau for free.
    opaque = _scrim_edge_stops(sigma, light, room, False)
    left = cx - half_w
    buf.pen = brush.gradient(brush.LINEAR, int(left - reach), cy, int(left + reach), cy, opaque)
    buf.rectangle(0, 0, cx, h)
    right = cx + half_w
    buf.pen = brush.gradient(brush.LINEAR, int(right + reach), cy, int(right - reach), cy, opaque)
    buf.rectangle(cx, 0, w - cx, h)

    # PASS 2 -- the vertical profile as a multiply toward the room.
    veil = _scrim_edge_stops(sigma, light, room, True)
    top = cy - half_h
    buf.pen = brush.gradient(brush.LINEAR, cx, int(top - reach), cx, int(top + reach), veil)
    buf.rectangle(0, 0, w, cy)
    bottom = cy + half_h
    buf.pen = brush.gradient(brush.LINEAR, cx, int(bottom + reach), cx, int(bottom - reach), veil)
    buf.rectangle(0, cy, w, h - cy)

    if SCRIM_GRAIN > 0:
        buf.noise(SCRIM_GRAIN)


def _scrim(buf):
    _scrim_paint(buf, SCRIM_STILL_T)


def _scrim_a(buf, t):
    _scrim_paint(buf, t)

# ── DOT DASH ───────────────────────────────────────────
# DOT DASH -- a fifteen-ring dot disc, turning once per loop.

# @skinlab {"label": "Rings", "group": "Shape", "type": "integer", "min": 4, "max": 26}
DOT_RINGS = 15


# @skinlab {"label": "Disc", "group": "Layout", "type": "number", "min": 0.20, "max": 0.50, "step": 0.004}
DOT_DISC = 0.396


# @skinlab {"label": "Centre hole", "group": "Layout", "type": "number", "min": 0.02, "max": 0.40, "step": 0.004}
DOT_HOLE = 0.116


# @skinlab {"label": "Disc centre Y", "group": "Layout", "type": "number", "min": 0.30, "max": 0.75, "step": 0.005}
DOT_CENTRE = 0.5


# @skinlab {"label": "Arc pitch", "group": "Shape", "type": "number", "min": 0.7, "max": 2.2, "step": 0.02}
DOT_ARC = 1.167


# @skinlab {"label": "Dot weight", "group": "Shape", "type": "number", "min": 0.20, "max": 0.60, "step": 0.005}
DOT_WEIGHT = 0.503


# @skinlab {"label": "Ring stagger", "group": "Layout", "type": "number", "min": 0.0, "max": 1.0, "step": 0.005}
DOT_STAGGER = 0.618


# @skinlab {"label": "Turns per loop", "group": "Motion", "type": "integer", "min": -3, "max": 3}
DOT_TURNS = 1


# @skinlab {"label": "Ground", "group": "Palette", "type": "color"}
DOT_GROUND = (244, 239, 232)


# @skinlab {"label": "Ink", "group": "Palette", "type": "color"}
DOT_INK = (98, 86, 74)


# @skinlab {"label": "Hub", "group": "Details", "type": "number", "min": 0.0, "max": 2.5, "step": 0.05}
DOT_HUB = 1.15


# @skinlab {"label": "Hub eye", "group": "Details", "type": "number", "min": 0.0, "max": 1.0, "step": 0.02}
DOT_HUB_EYE = 0.30


# @skinlab {"label": "Facets", "group": "Shape", "type": "integer", "min": 3, "max": 8}
DOT_FACETS = 6


_TAU = 2.0 * math.pi


_PER_SHAPE = 160


_CACHE = {}


def _dot_dash_build(buf):
    """The fifteen rings, as retained `shape.custom` batches about the ORIGIN.

    Built about (0, 0) rather than in place so that one `mat3.trs(centre,
    degrees)` both rotates and positions the disc. A shape built at the canvas
    centre would have to be rotated about a point it does not own: translate,
    rotate, translate back, three matrix calls a frame instead of one.
    """
    w, h = buf.width, buf.height
    key = (w, h, DOT_RINGS, DOT_DISC, DOT_HOLE, DOT_ARC,
           DOT_WEIGHT, DOT_STAGGER, DOT_FACETS, DOT_CENTRE)
    if _CACHE.get("key") == key:
        return _CACHE
    sides = DOT_FACETS
    outer = min(w, h) * DOT_DISC
    inner = outer * DOT_HOLE
    # 15 rings between 11 px and 95 px on a 240 px canvas is a pitch of 6.0.
    pitch = (outer - inner) / (DOT_RINGS - 1) if DOT_RINGS > 1 else outer
    arc = pitch * DOT_ARC
    # The dot radius is a fraction of the RING PITCH, not of the canvas, so the
    # ink keeps its share of the disc when a designer moves the ring count.
    rad = pitch * DOT_WEIGHT
    step = _TAU / sides
    # The facet ring is PRE-SCALED by the dot radius, so the inner loop is one
    # add per coordinate instead of a multiply and an add. That matters for
    # ALLOCATION, not for arithmetic: every intermediate float in MicroPython is
    # a heap object, and folding `rad *` out of the vertex loop removes 8,472
    # of them from the build (measured 414 KB of transient allocation before,
    # 260 KB after, on a badge heap of 520 KB that already holds a 307,200 B
    # backdrop).
    ring = [(rad * math.cos(q * step), rad * math.sin(q * step))
            for q in range(sides)]
    # ONE pool of contours, rewritten for every batch. `shape.custom` copies the
    # floats out of each vec2 into its own path storage (generated/shape.cpp:26),
    # so the objects are free to be overwritten the moment it returns. That takes
    # the build from 708*sides vec2 allocations to 160*sides. Allocation count is
    # what cost `SUPABASE` 252 ms/frame, so it is worth the six lines.
    pool = [[vec2(0.0, 0.0) for _ in range(sides)] for _ in range(_PER_SHAPE)]
    batches = []
    slot = 0
    total = 0
    for j in range(DOT_RINGS):
        r = inner + pitch * j
        count = int(_TAU * r / arc) if arc > 0 else 0
        if count < 3:
            count = 3
        # A golden-ratio walk in cell fractions. Any fixed offset -- zero
        # included -- lets rings whose counts share a factor line their dots up
        # into radial spokes, which the reference does not have.
        phase = (j * DOT_STAGGER % 1.0) * _TAU / count
        astep = _TAU / count
        for i in range(count):
            a = phase + i * astep
            cx, cy = r * math.cos(a), r * math.sin(a)
            contour = pool[slot]
            for q in range(sides):
                ux, uy = ring[q]
                v = contour[q]
                v.x = cx + ux
                v.y = cy + uy
            slot += 1
            total += 1
            if slot == _PER_SHAPE:
                batches.append(shape.custom(*pool))
                slot = 0
    if slot:
        batches.append(shape.custom(*pool[:slot]))
    _CACHE["key"] = key
    _CACHE["batches"] = batches
    _CACHE["dots"] = total
    _CACHE["centre"] = vec2(w * 0.5, h * DOT_CENTRE)
    # Held rather than rebuilt: `animate` runs every frame, and a colour is a
    # heap object like everything else here.
    _CACHE["ground"] = color.rgb(DOT_GROUND[0], DOT_GROUND[1], DOT_GROUND[2])
    _CACHE["ink"] = color.rgb(DOT_INK[0], DOT_INK[1], DOT_INK[2])
    _CACHE["hub"] = max(1, int(round(pitch * DOT_HUB)))
    _CACHE["eye"] = int(round(pitch * DOT_HUB * DOT_HUB_EYE))
    return _CACHE


def _dot_dash_paint(buf, held, degrees):
    """One ground fill, five shape draws, one hub. Eight primitives, any size."""
    w, h = buf.width, buf.height
    was_aa = buf.antialias
    was_rule = buf.fill_rule
    # Antialias ON for the dots, and put back afterwards. At 160x120 -- the size
    # SAVE TO HOME bakes into the launcher film -- a dot is 1.5 px across, and at
    # 40x30 it is under half a pixel; with picovector's default (OFF,
    # image.hpp:153) most of the field falls below the sampling grid and the
    # wallpaper loses its artwork. Skins draw axis-aligned work, so switching it
    # on cost the whole catalogue 0.996x (engineering-findings) -- here it is
    # what makes the picture survive being made small.
    buf.antialias = image.X4
    # NON_ZERO, because EVEN_ODD draws NOTHING for a multi-contour shape whose
    # contours are disjoint and wound the same way: measured in the pinned
    # runtime, two separate squares in one `shape.custom` fill 3200 px under
    # NON_ZERO and 0 px under EVEN_ODD.
    buf.fill_rule = image.NON_ZERO
    buf.pen = held["ground"]
    buf.rectangle(0, 0, w, h)
    buf.pen = held["ink"]
    matrix = mat3.trs(held["centre"], degrees)
    for s in held["batches"]:
        s.transform = matrix
        buf.shape(s)
    # The hub: one larger ringed mark at the middle, the only thing in the
    # picture that does not turn. Measured off the reference at 7 px outer and
    # 2 px inner on a 240 px canvas.
    cx, cy = int(w * 0.5), int(h * DOT_CENTRE)
    buf.circle(cx, cy, held["hub"])
    if held["eye"] > 0:
        buf.pen = held["ground"]
        buf.circle(cx, cy, held["eye"])
    # LEAVE THE SURFACE AS IT WAS FOUND. `animate`'s buffer IS the screen and
    # both properties are sticky per surface: a stray NON_ZERO cost the owner a
    # badge whose menu glyphs filled their own counters (skins.py `_supabase`).
    buf.fill_rule = was_rule
    buf.antialias = was_aa


def _dot_dash(buf):
    _dot_dash_paint(buf, _dot_dash_build(buf), 0.0)


def _dot_dash_a(buf, t):
    # A WHOLE number of turns per loop, so t = 1 lands exactly on t = 0. The
    # reference turns once per 2,880 ms; this turns once per CYCLE_MS = 4,000,
    # which is 72% of the reference's angular speed. Retiming was chosen over
    # traversing 0.72 of a turn because a fractional turn SNAPS at the wrap --
    # the defect found in eight shipped skins on 2026-08-18, and the reason
    # every phase rate in the catalogue is now an integer count per loop.
    _dot_dash_paint(buf, _dot_dash_build(buf), 360.0 * DOT_TURNS * t)

# ── DOT MATRIX WAVE ───────────────────────────────────────────
# DOT MATRIX WAVE -- a lattice of soft lights with a diagonal wave in them.

# @skinlab {"label": "Columns", "group": "Layout", "type": "integer", "min": 3, "max": 16}
GLOW_COLS = 8


# @skinlab {"label": "Rows", "group": "Layout", "type": "integer", "min": 3, "max": 12}
GLOW_ROWS = 6


# @skinlab {"label": "Grid offset", "group": "Layout", "type": "number", "min": 0.0, "max": 1.0, "step": 0.05}
GLOW_OFFSET = 0.75


# @skinlab {"label": "Lamp size", "group": "Shape", "type": "number", "min": 0.15, "max": 0.90, "step": 0.02}
GLOW_LAMP = 0.85


# @skinlab {"label": "Softness", "group": "Shape", "type": "number", "min": 0.10, "max": 0.90, "step": 0.02}
GLOW_SOFT = 0.1875


# @skinlab {"label": "Wave step", "group": "Motion", "type": "number", "min": 0.0, "max": 3.2, "step": 0.02}
GLOW_STEP = 2.0


# @skinlab {"label": "Waves per loop", "group": "Motion", "type": "integer", "min": -3, "max": 3}
GLOW_SPEED = 1


# @skinlab {"label": "Dim", "group": "Palette", "type": "integer", "min": 0, "max": 120}
GLOW_DIM = 18


# @skinlab {"label": "Lit", "group": "Palette", "type": "integer", "min": 60, "max": 255}
GLOW_LIT = 255


# @skinlab {"label": "Tint", "group": "Palette", "type": "color"}
GLOW_TINT = (255, 255, 255)


# @skinlab {"label": "Ground", "group": "Palette", "type": "color"}
GLOW_GROUND = (0, 0, 0)


_DOT_MATRIX_WAVE_TAU = 2.0 * math.pi


_CELL = 16


_LEVELS = 32


_DOT_MATRIX_WAVE_FACETS = 32


_DOT_MATRIX_WAVE_RING = [
    (math.cos(_DOT_MATRIX_WAVE_TAU * q / _DOT_MATRIX_WAVE_FACETS),
     math.sin(_DOT_MATRIX_WAVE_TAU * q / _DOT_MATRIX_WAVE_FACETS))
    for q in range(_DOT_MATRIX_WAVE_FACETS)]


_DOT_MATRIX_WAVE_CACHE = {}


def _dot_matrix_wave_build():
    """The scratch image, its cell centres, and the level palette."""
    key = (GLOW_COLS, GLOW_ROWS, GLOW_OFFSET, GLOW_LAMP, GLOW_SOFT,
           GLOW_DIM, GLOW_LIT, GLOW_TINT, GLOW_GROUND)
    if _DOT_MATRIX_WAVE_CACHE.get("key") == key:
        return _DOT_MATRIX_WAVE_CACHE
    sw, sh = GLOW_COLS * _CELL, GLOW_ROWS * _CELL
    # A bytearray, never a bare `image(w, h)`: the buffer-less constructor is
    # `PV_MALLOC_NO_SCAN` with no memset, so on the badge it is whatever the heap
    # last held. It reads as zeros in the browser, which is exactly why this is
    # the trap that costs a day.
    buf = bytearray(sw * sh * 4)
    _DOT_MATRIX_WAVE_CACHE["key"] = key
    _DOT_MATRIX_WAVE_CACHE["raw"] = buf
    _DOT_MATRIX_WAVE_CACHE["scratch"] = image(sw, sh, buf)
    # NON_ZERO keeps disjoint contours visible; X4 preserves the round edge
    # until the radius-3 blur consumes it. These are private scratch settings,
    # so unlike the screen surface they need no save/restore around each frame.
    _DOT_MATRIX_WAVE_CACHE["scratch"].antialias = image.X4
    _DOT_MATRIX_WAVE_CACHE["scratch"].fill_rule = image.NON_ZERO
    _DOT_MATRIX_WAVE_CACHE["sw"] = sw
    _DOT_MATRIX_WAVE_CACHE["sh"] = sh
    _DOT_MATRIX_WAVE_CACHE["blur"] = max(1, int(round(_CELL * GLOW_SOFT)))
    _DOT_MATRIX_WAVE_CACHE["ground"] = color.rgb(GLOW_GROUND[0], GLOW_GROUND[1], GLOW_GROUND[2])
    # Brightness depends only on k+j, so thirteen retained multi-contour shapes
    # replace 48 per-frame lamp draws. A 32-gon is within 0.48% of its vertex
    # circle, matching the reference's measured 0.107-0.561% isotropy; the
    # 0.85-cell disc preserves the old square's emitting area after rounding.
    # The largest batch is 6*32 = 192 points, below shape.custom's silent
    # 1024-point ceiling. It copies coordinates into retained path storage, so
    # rewriting one six-contour pool avoids keeping 1,536 temporary vec2s.
    radius = max(0.5, _CELL * GLOW_LAMP * 0.5)
    pool = [[vec2(0.0, 0.0) for _ in range(_DOT_MATRIX_WAVE_FACETS)]
            for _ in range(min(GLOW_COLS, GLOW_ROWS))]
    diagonals = []
    for d in range(GLOW_COLS + GLOW_ROWS - 1):
        slot = 0
        for j in range(GLOW_ROWS):
            k = d - j
            if k < 0 or k >= GLOW_COLS:
                continue
            cx = int(round((k + GLOW_OFFSET) * _CELL))
            cy = int(round((j + GLOW_OFFSET) * _CELL))
            contour = pool[slot]
            for q in range(_DOT_MATRIX_WAVE_FACETS):
                ux, uy = _DOT_MATRIX_WAVE_RING[q]
                contour[q].x = cx + radius * ux
                contour[q].y = cy + radius * uy
            slot += 1
        diagonals.append((shape.custom(*pool[:slot]), d))
    _DOT_MATRIX_WAVE_CACHE["diagonals"] = diagonals
    r, g, b = GLOW_TINT
    _DOT_MATRIX_WAVE_CACHE["levels"] = [
        color.rgb(
            int(GLOW_DIM + (GLOW_LIT - GLOW_DIM) * (i / (_LEVELS - 1.0)) * r / 255.0),
            int(GLOW_DIM + (GLOW_LIT - GLOW_DIM) * (i / (_LEVELS - 1.0)) * g / 255.0),
            int(GLOW_DIM + (GLOW_LIT - GLOW_DIM) * (i / (_LEVELS - 1.0)) * b / 255.0))
        for i in range(_LEVELS)]
    return _DOT_MATRIX_WAVE_CACHE


def _dot_matrix_wave_paint(buf, t):
    held = _dot_matrix_wave_build()
    scratch = held["scratch"]
    levels = held["levels"]
    top = _LEVELS - 1
    # One cosine per cell, phase advancing GLOW_STEP radians per step in k and
    # in j -- so the crest travels along the k + j diagonal, which is what the
    # reference's per-cell DFT phases say it does.
    turn = _DOT_MATRIX_WAVE_TAU * GLOW_SPEED * t
    scratch.pen = held["ground"]
    scratch.rectangle(0, 0, held["sw"], held["sh"])
    for discs, d in held["diagonals"]:
        level = int((0.5 + 0.5 * math.cos(turn + d * GLOW_STEP)) * top + 0.5)
        scratch.pen = levels[level if level < top else top]
        scratch.shape(discs)
    # The whole glow, for one sixth of the canvas's pixels. A box blur is
    # O(1) in its radius here (measured flat from radius 4 to 24), so softness
    # is free once the pass is paid for.
    scratch.blur(held["blur"])
    # One filtered blit does the upscale AND the background: the scratch covers
    # every pixel, so nothing else has to clear the canvas. BILINEAR, because
    # NEAREST would make the lattice crawl in 4 px steps as the wave moves.
    buf.blit(scratch, rect(0, 0, buf.width, buf.height), image.BILINEAR)


def _dot_matrix_wave(buf):
    _dot_matrix_wave_paint(buf, 0.0)


def _dot_matrix_wave_a(buf, t):
    # An integer number of wave cycles per loop, so t = 1 lands on t = 0. The
    # reference runs one cycle per 2,880 ms and this runs one per CYCLE_MS =
    # 4,000, so the wave is 72% of the reference's speed. Retiming rather than
    # traversing 0.72 of a cycle, because a fractional cycle SNAPS at the wrap --
    # the defect found in eight shipped skins on 2026-08-18.
    _dot_matrix_wave_paint(buf, t)


# ── THRESHOLD ───────────────────────────────────────────
# THRESHOLD -- one soft horizontal band of light, riding up and down a dark room.

# @skinlab {"type": "number", "label": "Band softness", "group": "Shape", "min": 0.03, "max": 0.35, "step": 0.002}
BAND_SIGMA = 0.1246


# @skinlab {"type": "number", "label": "Travel", "group": "Motion", "min": 0.0, "max": 0.45, "step": 0.005}
BAND_TRAVEL = 0.1667


# @skinlab {"type": "number", "label": "Band centre Y", "group": "Layout", "min": 0.25, "max": 0.75, "step": 0.01}
BAND_FY = 0.5


# @skinlab {"type": "integer", "label": "Slides per loop", "group": "Motion", "min": -3, "max": 3}
BAND_CYCLES = 1


# @skinlab {"type": "color", "label": "Room", "group": "Palette"}
THRESHOLD_ROOM = (5, 5, 5)


# @skinlab {"type": "number", "label": "Band value", "group": "Palette", "min": 0.1, "max": 1.0, "step": 0.01}
BAND_V = 0.561


# @skinlab {"type": "number", "label": "Band saturation", "group": "Palette", "min": 0.0, "max": 1.0, "step": 0.01}
BAND_S = 0.692


# @skinlab {"type": "number", "label": "Hue at t=0", "group": "Palette", "min": 0.0, "max": 360.0, "step": 5.0}
THRESHOLD_HUE_START = 0.0


# @skinlab {"type": "number", "label": "Hue turns per loop", "group": "Motion", "min": -2.0, "max": 2.0, "step": 0.5}
THRESHOLD_HUE_TURNS = 1.0


# @skinlab {"type": "integer", "label": "Grain", "group": "Look", "min": 0, "max": 32}
THRESHOLD_GRAIN = 6


# @skinlab {"type": "number", "label": "Still phase", "group": "Layout", "min": 0.0, "max": 1.0, "step": 0.01}
THRESHOLD_STILL_T = 0.25


_STOPS = 13


_THRESHOLD_SIGMAS = 3.0


_PROFILE = [math.exp(-0.5 * (_THRESHOLD_SIGMAS * (1.0 - i / float(_STOPS - 1))) ** 2)
            for i in range(_STOPS)]


def _threshold_hsv(h, s, v):
    """HSV to an 8-bit triple.

    The reference is one channel at 143, one at 44 and one ramping between them,
    which is exactly this parameterisation at S = (143-44)/143 and V = 143/255,
    so it is the same one the reference used rather than a re-fit.
    """
    h = h - 360.0 * math.floor(h / 360.0)
    c = v * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = v - c
    if h < 60.0:
        r, g, b = c, x, 0.0
    elif h < 120.0:
        r, g, b = x, c, 0.0
    elif h < 180.0:
        r, g, b = 0.0, c, x
    elif h < 240.0:
        r, g, b = 0.0, x, c
    elif h < 300.0:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (int((r + m) * 255.0 + 0.5), int((g + m) * 255.0 + 0.5), int((b + m) * 255.0 + 0.5))


def _threshold_stops(band):
    """The half-profile as a stop table running room -> band colour.

    One table serves BOTH halves, because the profile is symmetric and each
    half's gradient is aimed inwards; that halves the per-frame colour
    allocations, which are the only Python-side cost in this skin.
    """
    table = []
    for i in range(_STOPS):
        level = _PROFILE[i]
        table.append((i / float(_STOPS - 1), color.rgb(
            int(THRESHOLD_ROOM[0] + (band[0] - THRESHOLD_ROOM[0]) * level + 0.5),
            int(THRESHOLD_ROOM[1] + (band[1] - THRESHOLD_ROOM[1]) * level + 0.5),
            int(THRESHOLD_ROOM[2] + (band[2] - THRESHOLD_ROOM[2]) * level + 0.5))))
    return table


def _threshold_paint(buf, t):
    w, h = buf.width, buf.height
    cx = w // 2
    # `floor`, not `round`, because the reference's centroids sit consistently
    # 0 to 0.7 px BELOW the continuous sine and land exactly on its floor.
    cy = int(math.floor(h * BAND_FY + h * BAND_TRAVEL
                        * math.sin(2.0 * math.pi * BAND_CYCLES * t)))
    reach = int(_THRESHOLD_SIGMAS * BAND_SIGMA * h)
    if reach < 2:
        reach = 2

    table = _threshold_stops(_threshold_hsv(THRESHOLD_HUE_START + 360.0 * THRESHOLD_HUE_TURNS * t, BAND_S, BAND_V))

    # TWO OPAQUE FILLS, COVERING THE CANVAS EXACTLY ONCE. Each gradient runs
    # from the outside of the band inwards; the clamp past the start point
    # paints the room for free, so neither half needs a clear and there is no
    # second pass to composite.
    if cy > 0:
        buf.pen = brush.gradient(brush.LINEAR, cx, cy - reach, cx, cy, table)
        buf.rectangle(0, 0, w, cy)
    if cy < h:
        buf.pen = brush.gradient(brush.LINEAR, cx, cy + reach, cx, cy, table)
        buf.rectangle(0, cy, w, h - cy)

    if THRESHOLD_GRAIN > 0:
        # SCOPED TO THE BAND, not applied to the whole surface. `noise` is a
        # signed perturbation that clamps, so over the (5,5,5) room it returns
        # roughly 0..GRAIN with a mean near GRAIN/4 -- a whole-surface pass would
        # lift the room into a speckle, and there is nothing out there to dither
        # anyway because the ramp has already reached the room. The pen form
        # perturbs only the pixels the shape covers, which is the same filter
        # with a bounding box.
        y0 = cy - reach
        y1 = cy + reach
        if y0 < 0:
            y0 = 0
        if y1 > h:
            y1 = h
        if y1 > y0:
            buf.pen = brush.noise(THRESHOLD_GRAIN)
            buf.rectangle(0, y0, w, y1 - y0)


def _threshold(buf):
    _threshold_paint(buf, THRESHOLD_STILL_T)


def _threshold_a(buf, t):
    _threshold_paint(buf, t)

# ── ACRYLIC ───────────────────────────────────────────
# ACRYLIC -- a lit column standing in a dark room, cycling through every hue.

# @skinlab {"type": "number", "label": "Column width", "group": "Layout", "min": 0.02, "max": 0.35, "step": 0.002}
COL_HALF = 0.1273


# @skinlab {"type": "number", "label": "Edge softness", "group": "Shape", "min": 0.01, "max": 0.30, "step": 0.002}
COL_SOFT = 0.1063


# @skinlab {"type": "number", "label": "Column centre X", "group": "Layout", "min": 0.2, "max": 0.8, "step": 0.01}
COL_FX = 0.5


# @skinlab {"type": "number", "label": "Lit from", "group": "Layout", "min": 0.0, "max": 0.5, "step": 0.005}
COL_TOP = 0.063


# @skinlab {"type": "number", "label": "Foot brightness", "group": "Palette", "min": 0.0, "max": 1.0, "step": 0.005}
COL_FOOT = 0.285


# @skinlab {"type": "color", "label": "Room", "group": "Palette"}
ACRYLIC_ROOM = (15, 15, 20)


# @skinlab {"type": "number", "label": "Light value", "group": "Palette", "min": 0.2, "max": 1.0, "step": 0.01}
ACRYLIC_LIGHT_V = 0.859


# @skinlab {"type": "number", "label": "Light saturation", "group": "Palette", "min": 0.0, "max": 1.0, "step": 0.01}
ACRYLIC_LIGHT_S = 0.502


# @skinlab {"type": "number", "label": "Hue at t=0", "group": "Palette", "min": 0.0, "max": 360.0, "step": 5.0}
ACRYLIC_HUE_START = 200.0


# @skinlab {"type": "number", "label": "Hue turns per loop", "group": "Motion", "min": -2.0, "max": 2.0, "step": 0.5}
ACRYLIC_HUE_TURNS = 1.0


# @skinlab {"type": "integer", "label": "Grain", "group": "Look", "min": 0, "max": 32}
ACRYLIC_GRAIN = 5


# @skinlab {"type": "number", "label": "Still phase", "group": "Layout", "min": 0.0, "max": 1.0, "step": 0.01}
ACRYLIC_STILL_T = 0.0


_ACRYLIC_EDGE_STOPS = 13


_ACRYLIC_CACHE = {}


def _acrylic_hsv(h, s, v):
    """HSV to an 8-bit triple.

    The reference's peak sits on max 219 / min 109 on every frame, which is
    exactly this parameterisation at V = 219/255 and S = (219-109)/219, so this
    is the parameterisation it used rather than a re-fit of one.
    """
    h = h - 360.0 * math.floor(h / 360.0)
    c = v * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = v - c
    if h < 60.0:
        r, g, b = c, x, 0.0
    elif h < 120.0:
        r, g, b = x, c, 0.0
    elif h < 180.0:
        r, g, b = 0.0, c, x
    elif h < 240.0:
        r, g, b = 0.0, x, c
    elif h < 300.0:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (int((r + m) * 255.0 + 0.5), int((g + m) * 255.0 + 0.5), int((b + m) * 255.0 + 0.5))


def _acrylic_build():
    """The room colour object and the edge's alpha stop table.

    The table runs from alpha 255 at the OUTSIDE of the edge to alpha 0 at the
    inside, so one table serves both edges: each gradient is aimed inwards and
    the brush's clamp paints the plateau (alpha 0, a no-op) and the room
    (alpha 255, an opaque overwrite) at the two ends.
    """
    key = (ACRYLIC_ROOM, _ACRYLIC_EDGE_STOPS)
    if _ACRYLIC_CACHE.get("key") == key:
        return _ACRYLIC_CACHE
    veil = []
    for i in range(_ACRYLIC_EDGE_STOPS):
        pos = i / float(_ACRYLIC_EDGE_STOPS - 1)
        # The raised cosine, running 0 at the outside to 1 at the inside.
        level = 0.5 * (1.0 - math.cos(math.pi * pos))
        veil.append((pos, color.rgb(ACRYLIC_ROOM[0], ACRYLIC_ROOM[1], ACRYLIC_ROOM[2],
                                    int(255.0 * (1.0 - level) + 0.5))))
    _ACRYLIC_CACHE["key"] = key
    _ACRYLIC_CACHE["veil"] = veil
    _ACRYLIC_CACHE["room"] = color.rgb(ACRYLIC_ROOM[0], ACRYLIC_ROOM[1], ACRYLIC_ROOM[2])
    return _ACRYLIC_CACHE


def _acrylic_paint(buf, t):
    w, h = buf.width, buf.height
    held = _acrylic_build()
    cx = int(w * COL_FX)
    inner = int(w * (COL_HALF - COL_SOFT))       # end of the flat core
    outer = int(w * (COL_HALF + COL_SOFT))       # where the light reaches zero
    if outer <= inner:
        outer = inner + 1
    left = cx - outer
    right = cx + outer
    if left < 0:
        left = 0
    if right > w:
        right = w

    light = _acrylic_hsv(ACRYLIC_HUE_START + 360.0 * ACRYLIC_HUE_TURNS * t, ACRYLIC_LIGHT_S, ACRYLIC_LIGHT_V)

    # FILLS 1-2 -- the room, flat, outside the column. Excluding these pixels
    # from the gradient and the alpha pass is where this skin's saving is; they
    # are 53% of the canvas and there is nothing in them.
    buf.pen = held["room"]
    if left > 0:
        buf.rectangle(0, 0, left, h)
    if right < w:
        buf.rectangle(right, 0, w - right, h)

    # FILL 3 -- the vertical ramp at FULL horizontal brightness, opaque, two
    # stops. The gradient starts at COL_TOP so the brush's clamp paints the flat
    # lit top for free, and ends at the bottom edge rather than off-canvas so
    # both stops are real samples of the measured line.
    foot = (int(ACRYLIC_ROOM[0] + (light[0] - ACRYLIC_ROOM[0]) * COL_FOOT + 0.5),
            int(ACRYLIC_ROOM[1] + (light[1] - ACRYLIC_ROOM[1]) * COL_FOOT + 0.5),
            int(ACRYLIC_ROOM[2] + (light[2] - ACRYLIC_ROOM[2]) * COL_FOOT + 0.5))
    buf.pen = brush.gradient(
        brush.LINEAR, cx, int(h * COL_TOP), cx, h,
        [(0.0, color.rgb(light[0], light[1], light[2])),
         (1.0, color.rgb(foot[0], foot[1], foot[2]))])
    buf.rectangle(left, 0, right - left, h)

    # FILLS 4-5 -- the horizontal profile, as a multiply toward the room. `over`
    # is a lerp, so painting the ROOM at alpha `1 - H(x)` gives
    # ROOM + (LIGHT-ROOM)*V(y)*H(x) exactly, with the picture underneath
    # reconstructed rather than veiled. Each rectangle is the EDGE STRIP only:
    # the plateau would be alpha 0 and the outside is already painted.
    veil = held["veil"]
    edge = outer - inner
    buf.pen = brush.gradient(brush.LINEAR, cx - outer, 0, cx - inner, 0, veil)
    buf.rectangle(cx - outer, 0, edge, h)
    buf.pen = brush.gradient(brush.LINEAR, cx + outer, 0, cx + inner, 0, veil)
    buf.rectangle(cx + inner, 0, edge, h)

    if ACRYLIC_GRAIN > 0:
        # SCOPED TO THE COLUMN. `noise` is a signed perturbation that clamps, so
        # over the (15,15,20) room it lifts a near-black into a speckle with
        # nothing to dither underneath -- the ramp has already reached the room
        # out there. The pen form perturbs only the pixels the shape covers.
        buf.pen = brush.noise(ACRYLIC_GRAIN)
        buf.rectangle(left, 0, right - left, h)


def _acrylic(buf):
    _acrylic_paint(buf, ACRYLIC_STILL_T)


def _acrylic_a(buf, t):
    _acrylic_paint(buf, t)

# ── CONVEX LENS ───────────────────────────────────────────
# CONVEX LENS -- a small bright lens orbiting inside a large still halo.

# @skinlab {"type": "color", "label": "Ground", "group": "Palette"}
GROUND = (40, 40, 45)


# @skinlab {"type": "color", "label": "Light", "group": "Palette"}
LIGHT = (250, 251, 255)


# @skinlab {"type": "number", "label": "Halo centre X", "group": "Layout", "min": 0.2, "max": 0.8, "step": 0.005}
HALO_FX = 0.508


# @skinlab {"type": "number", "label": "Halo centre Y", "group": "Layout", "min": 0.2, "max": 0.8, "step": 0.005}
HALO_FY = 0.510


# @skinlab {"type": "number", "label": "Halo size", "group": "Shape", "min": 0.05, "max": 0.45, "step": 0.002}
HALO_SIGMA = 0.189


# @skinlab {"type": "number", "label": "Halo strength", "group": "Palette", "min": 0.0, "max": 1.0, "step": 0.005}
HALO_A = 0.315


# @skinlab {"type": "number", "label": "Orbit centre X", "group": "Layout", "min": 0.2, "max": 0.8, "step": 0.005}
ORBIT_FX = 0.377


# @skinlab {"type": "number", "label": "Orbit centre Y", "group": "Layout", "min": 0.15, "max": 0.85, "step": 0.005}
ORBIT_FY = 0.336


# @skinlab {"type": "number", "label": "Orbit radius", "group": "Motion", "min": 0.0, "max": 0.35, "step": 0.002}
ORBIT_R = 0.081


# @skinlab {"type": "integer", "label": "Laps per loop", "group": "Motion", "min": -3, "max": 3}
ORBIT_TURNS = 1


# @skinlab {"type": "number", "label": "Orbit phase", "group": "Motion", "min": 0.0, "max": 360.0, "step": 5.0}
ORBIT_PHASE = 0.0


# @skinlab {"type": "number", "label": "Lens size", "group": "Shape", "min": 0.02, "max": 0.30, "step": 0.002}
LENS_SIGMA = 0.104


# @skinlab {"type": "number", "label": "Lens strength", "group": "Palette", "min": 0.0, "max": 1.0, "step": 0.005}
LENS_A = 0.632


# @skinlab {"type": "integer", "label": "Grain", "group": "Look", "min": 0, "max": 32}
CONVEX_LENS_GRAIN = 6


# @skinlab {"type": "number", "label": "Still phase", "group": "Layout", "min": 0.0, "max": 1.0, "step": 0.005}
CONVEX_LENS_STILL_T = 0.375


_CONVEX_LENS_STOPS = 13


_CONVEX_LENS_SIGMAS = 3.0


_CONVEX_LENS_PROFILE = [math.exp(-0.5 * (_CONVEX_LENS_SIGMAS * i / float(_CONVEX_LENS_STOPS - 1)) ** 2)
            for i in range(_CONVEX_LENS_STOPS)]


_CONVEX_LENS_CACHE = {}


def _convex_lens_build():
    key = (GROUND, LIGHT, HALO_A, LENS_A, _CONVEX_LENS_STOPS, _CONVEX_LENS_SIGMAS)
    if _CONVEX_LENS_CACHE.get("key") == key:
        return _CONVEX_LENS_CACHE
    halo = []
    lens = []
    for i in range(_CONVEX_LENS_STOPS):
        pos = i / float(_CONVEX_LENS_STOPS - 1)
        level = _CONVEX_LENS_PROFILE[i]
        # The halo is OPAQUE and ends on the ground colour, so the same call
        # that draws it also paints the background: `over` at alpha a is
        # dst*(1-a) + LIGHT*a, and with dst known to be the ground everywhere
        # that lerp can be evaluated here instead of by the blender.
        a = HALO_A * level
        halo.append((pos, color.rgb(
            int(GROUND[0] + (LIGHT[0] - GROUND[0]) * a + 0.5),
            int(GROUND[1] + (LIGHT[1] - GROUND[1]) * a + 0.5),
            int(GROUND[2] + (LIGHT[2] - GROUND[2]) * a + 0.5))))
        # The lens is drawn over an unknown background -- the halo -- so it has
        # to be a real alpha ramp and cannot be folded the same way.
        lens.append((pos, color.rgb(LIGHT[0], LIGHT[1], LIGHT[2],
                                    int(255.0 * LENS_A * level + 0.5))))
    _CONVEX_LENS_CACHE["key"] = key
    _CONVEX_LENS_CACHE["halo"] = halo
    _CONVEX_LENS_CACHE["lens"] = lens
    return _CONVEX_LENS_CACHE


def _convex_lens_paint(buf, t):
    w, h = buf.width, buf.height
    held = _convex_lens_build()

    # PASS 1 -- the halo, opaque, covering the canvas exactly once. No separate
    # clear: the stop table's last entry is the ground and the brush clamps past
    # its edge point, so everything outside three sigma is painted ground by the
    # same call.
    hx, hy = int(w * HALO_FX), int(h * HALO_FY)
    reach = int(_CONVEX_LENS_SIGMAS * HALO_SIGMA * h)
    if reach < 2:
        reach = 2
    buf.pen = brush.gradient(brush.RADIAL, hx, hy, hx, hy + reach, held["halo"])
    buf.clear()

    # PASS 2 -- the lens, over. A circle rather than its bounding rectangle:
    # both are correct because the ramp has reached transparent by three sigma,
    # and the circle is 21% fewer pixels of the one operation in this skin that
    # cannot use a blend fast path.
    angle = 2.0 * math.pi * (ORBIT_TURNS * t + ORBIT_PHASE / 360.0)
    lx = int(w * ORBIT_FX + h * ORBIT_R * math.cos(angle))
    ly = int(h * ORBIT_FY + h * ORBIT_R * math.sin(angle))
    span = int(_CONVEX_LENS_SIGMAS * LENS_SIGMA * h)
    if span < 2:
        span = 2
    buf.pen = brush.gradient(brush.RADIAL, lx, ly, lx, ly + span, held["lens"])
    buf.circle(lx, ly, span)

    if CONVEX_LENS_GRAIN > 0:
        # WHOLE SURFACE, unlike `breath.py` and `threshold.py`. Those two scope
        # their grain to the lit region because `noise` clamps at zero and would
        # turn their true-black rooms into speckle. This artwork's darkest pixel
        # is (40,40,45), so there is no black to protect and the ramp reaches
        # every corner -- scoping it would leave the corners banded and buy
        # nothing.
        buf.pen = brush.noise(CONVEX_LENS_GRAIN)
        buf.rectangle(0, 0, w, h)


def _convex_lens(buf):
    _convex_lens_paint(buf, CONVEX_LENS_STILL_T)


def _convex_lens_a(buf, t):
    _convex_lens_paint(buf, t)

# ── PRISMATIC ───────────────────────────────────────────
# PRISMATIC -- a pastel field turning through the whole hue circle, meeting its

# @skinlab {"type": "number", "label": "Edge at", "group": "Layout", "min": -0.2, "max": 0.6, "step": 0.005}
EDGE_AT = 0.097


# @skinlab {"type": "number", "label": "Edge softness", "group": "Layout", "min": 0.05, "max": 0.6, "step": 0.005}
EDGE_SOFT = 0.203


# @skinlab {"type": "number", "label": "Saturation", "group": "Palette", "min": 0.0, "max": 1.0, "step": 0.002}
PRISMATIC_SAT = 0.302


# @skinlab {"type": "number", "label": "Value", "group": "Palette", "min": 0.3, "max": 1.0, "step": 0.002}
VAL = 0.949


# @skinlab {"type": "number", "label": "Hue at t=0", "group": "Palette", "min": 0.0, "max": 360.0, "step": 0.1}
PRISMATIC_HUE_START = 249.9


# @skinlab {"type": "number", "label": "Edge hue offset", "group": "Palette", "min": 0.0, "max": 360.0, "step": 1.0}
EDGE_HUE = 180.0


# @skinlab {"type": "integer", "label": "Hue turns per loop", "group": "Motion", "min": -2, "max": 2}
PRISMATIC_HUE_TURNS = 1


# @skinlab {"type": "integer", "label": "Grain", "group": "Look", "min": 0, "max": 32}
PRISMATIC_GRAIN = 6


# @skinlab {"type": "number", "label": "Still phase", "group": "Layout", "min": 0.0, "max": 1.0, "step": 0.01}
PRISMATIC_STILL_T = 0.0


_PRISMATIC_RAMP_STOPS = 13


def _prismatic_hsv(h, s, v):
    """HSV to an 8-bit triple. The reference's flat field is a low channel of
    169 with a high of 242, which is exactly V 0.949 at S 0.302, so this is the
    same parameterisation it used."""
    h = h - 360.0 * math.floor(h / 360.0)
    c = v * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = v - c
    if h < 60.0:
        r, g, b = c, x, 0.0
    elif h < 120.0:
        r, g, b = x, c, 0.0
    elif h < 180.0:
        r, g, b = 0.0, c, x
    elif h < 240.0:
        r, g, b = 0.0, x, c
    elif h < 300.0:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (int((r + m) * 255.0 + 0.5), int((g + m) * 255.0 + 0.5), int((b + m) * 255.0 + 0.5))


def _prismatic_paint(buf, t):
    """One native gradient fill, covering the canvas.

    THE BRUSH SIGNATURE IS (kind, cx, cy, ex, ey, stops) -- for LINEAR that is
    a START POINT and an END POINT, not a point and two distances. Read as a
    centre and two radii it still draws a plausible ramp with the geometry
    silently wrong. The rasteriser CLAMPS past the end point (probed: a stop
    table ending at one edge still reads its last colour well beyond it), which
    is what paints the flat two thirds of this picture for free -- the whole
    frame is inside the brush, so this both clears and draws, and `animate`
    needs no separate clear.

    The gradient's START is OFF THE LEFT EDGE at -0.106 of the width. That is
    the measurement, not an accident: the reference never shows the complement
    at full strength, only the last quarter of the ramp into it.
    """
    w, h = buf.width, buf.height
    hue = PRISMATIC_HUE_START + 360.0 * PRISMATIC_HUE_TURNS * t
    near = _prismatic_hsv(hue + EDGE_HUE, PRISMATIC_SAT, VAL)
    far = _prismatic_hsv(hue, PRISMATIC_SAT, VAL)

    x0 = (EDGE_AT - EDGE_SOFT) * w
    x1 = (EDGE_AT + EDGE_SOFT) * w
    cy = h // 2

    stops = []
    for i in range(_PRISMATIC_RAMP_STOPS):
        u = i / float(_PRISMATIC_RAMP_STOPS - 1)
        level = u * u * (3.0 - 2.0 * u)
        stops.append((u, color.rgb(
            int(near[0] + (far[0] - near[0]) * level + 0.5),
            int(near[1] + (far[1] - near[1]) * level + 0.5),
            int(near[2] + (far[2] - near[2]) * level + 0.5))))

    buf.pen = brush.gradient(brush.LINEAR, int(x0), cy, int(x1), cy, stops)
    buf.clear()

    if PRISMATIC_GRAIN > 0:
        # SCOPED TO THE RAMP. Past x1 the picture is one flat colour, which the
        # panel reproduces exactly -- there is no ramp out there to dither, so
        # whole-surface grain would only add noise to two thirds of the frame.
        # `brush.noise` as a PEN perturbs just the pixels a shape covers
        # (probed: inside 130, outside 0), which is the same filter with a
        # bounding box. In `animate` this runs before the stickers and the name
        # are drawn, so it never touches type.
        reach = int(x1) + 1
        if reach > w:
            reach = w
        if reach > 0:
            buf.pen = brush.noise(PRISMATIC_GRAIN)
            buf.rectangle(0, 0, reach, h)


def _prismatic(buf):
    _prismatic_paint(buf, PRISMATIC_STILL_T)


def _prismatic_a(buf, t):
    _prismatic_paint(buf, t)

# ── DISC SERIES ───────────────────────────────────────────
# DISC SERIES -- one row of ten soft discs on a near-black room, with a wave

# @skinlab {"label": "Discs", "group": "Layout", "type": "integer", "min": 3, "max": 20}
DISC_COUNT = 10


# @skinlab {"label": "First disc", "group": "Layout", "type": "number", "min": 0.0, "max": 0.4, "step": 0.002}
DISC_X = 0.0937


# @skinlab {"label": "Spacing", "group": "Layout", "type": "number", "min": 0.04, "max": 0.25, "step": 0.001}
DISC_PITCH = 0.0944


# @skinlab {"label": "Row centre Y", "group": "Layout", "type": "number", "min": 0.25, "max": 0.75, "step": 0.005}
DISC_FY = 0.5


# @skinlab {"label": "Room", "group": "Palette", "type": "integer", "min": 0, "max": 120}
DISC_ROOM = 30


# @skinlab {"label": "Dim", "group": "Palette", "type": "integer", "min": 0, "max": 140}
DISC_DIM = 22


# @skinlab {"label": "Lit", "group": "Palette", "type": "integer", "min": 40, "max": 255}
DISC_LIT = 137


# @skinlab {"label": "Tint", "group": "Palette", "type": "color"}
DISC_TINT = (255, 255, 255)


# @skinlab {"label": "Wave step", "group": "Motion", "type": "number", "min": -90.0, "max": 90.0, "step": 0.05}
DISC_STEP = -28.55


# @skinlab {"label": "Phase at t=0", "group": "Motion", "type": "number", "min": -180.0, "max": 180.0, "step": 1.0}
DISC_PHASE = -89.65


# @skinlab {"label": "Waves per loop", "group": "Motion", "type": "integer", "min": -3, "max": 3}
DISC_SPEED = 1


# @skinlab {"label": "Grain", "group": "Look", "type": "integer", "min": 0, "max": 32}
DISC_GRAIN = 4


_DISC_SERIES_TAU = 2.0 * math.pi


_SW = 160


_SH = 120


_LAMP = 0.5


_RINGS = 5


_DISC_SERIES_TAPER = 1.2


_BLUR = 2


_PEAK = 0.685


_DISC_SERIES_LEVELS = 32


_DISC_SERIES_CACHE = {}


def _disc_series_build():
    """The scratch, the lamp stack, the disc centres and the level palettes."""
    key = (DISC_COUNT, DISC_X, DISC_PITCH, DISC_FY, DISC_ROOM,
           DISC_DIM, DISC_LIT, DISC_TINT)
    if _DISC_SERIES_CACHE.get("key") == key:
        return _DISC_SERIES_CACHE
    # A bytearray, never a bare `image(w, h)`: the buffer-less constructor is
    # `PV_MALLOC_NO_SCAN` with no memset, so on the badge it is whatever the
    # heap last held. It reads as zeros in the browser, which is exactly why
    # this is the trap that costs a day.
    raw = bytearray(_SW * _SH * 4)
    _DISC_SERIES_CACHE["key"] = key
    _DISC_SERIES_CACHE["raw"] = raw
    _DISC_SERIES_CACHE["scratch"] = image(_SW, _SH, raw)

    pitch = DISC_PITCH * _SW
    half = max(1, int(round(_LAMP * pitch)))
    sigma = half / _DISC_SERIES_TAPER
    # The stack, widest first, so the inner steps paint over the outer ones.
    _DISC_SERIES_CACHE["rings"] = [
        (int(round(half * j / float(_RINGS))),
         math.exp(-(int(round(half * j / float(_RINGS))) ** 2) / (2.0 * sigma * sigma)))
        for j in range(_RINGS, 0, -1)]
    _DISC_SERIES_CACHE["cx"] = [int(DISC_X * _SW + pitch * i) for i in range(DISC_COUNT)]
    _DISC_SERIES_CACHE["cy"] = int(DISC_FY * _SH)
    _DISC_SERIES_CACHE["ground"] = color.rgb(DISC_ROOM, DISC_ROOM, DISC_ROOM)

    # One palette per ring. `drive` is the level's distance from the room
    # divided by `_PEAK`; the ring paints a fraction of it.
    r, g, b = DISC_TINT
    palettes = []
    for _h, weight in _DISC_SERIES_CACHE["rings"]:
        row = []
        for i in range(_DISC_SERIES_LEVELS):
            level = DISC_DIM + (DISC_LIT - DISC_DIM) * (i / (_DISC_SERIES_LEVELS - 1.0))
            v = DISC_ROOM + (level - DISC_ROOM) * weight / _PEAK
            if v < 0.0:
                v = 0.0
            elif v > 255.0:
                v = 255.0
            row.append(color.rgb(int(v * r / 255.0), int(v * g / 255.0), int(v * b / 255.0)))
        palettes.append(row)
    _DISC_SERIES_CACHE["palettes"] = palettes
    return _DISC_SERIES_CACHE


def _disc_series_paint(buf, t):
    held = _disc_series_build()
    scratch = held["scratch"]
    rings = held["rings"]
    palettes = held["palettes"]
    cy = held["cy"]
    top = _DISC_SERIES_LEVELS - 1

    scratch.pen = held["ground"]
    scratch.rectangle(0, 0, _SW, _SH)
    turn = _DISC_SERIES_TAU * DISC_SPEED * t + math.radians(DISC_PHASE)
    step = math.radians(DISC_STEP)
    for i in range(DISC_COUNT):
        # 0..1 along the disc's own cosine, quantised onto the palette.
        u = 0.5 + 0.5 * math.cos(turn + step * i)
        q = int(u * top + 0.5)
        if q < 0:
            q = 0
        elif q > top:
            q = top
        cx = held["cx"][i]
        for k in range(len(rings)):
            h = rings[k][0]
            scratch.pen = palettes[k][q]
            scratch.rectangle(cx - h, cy - h, 2 * h + 1, 2 * h + 1)
    # The whole field, for a quarter of the canvas's pixels. A box blur is O(1)
    # in its radius here, so the softness is free once the pass is paid for.
    scratch.blur(_BLUR)
    # One filtered blit does the upscale AND the background: the scratch covers
    # every pixel, so nothing else has to clear the canvas. BILINEAR, because
    # NEAREST would make the row crawl in whole-scratch-pixel steps as the wave
    # moves.
    buf.blit(scratch, rect(0, 0, buf.width, buf.height), image.BILINEAR)

    if DISC_GRAIN > 0:
        # SCOPED TO THE ROW. Outside about +-3 sigma of the centre line the
        # picture is one flat value that the panel reproduces exactly, so grain
        # there is noise added to a field with no ramp in it. `brush.noise` as a
        # PEN perturbs only the pixels a shape covers, which is the same filter
        # with a bounding box. In `animate` this runs before the stickers and
        # the name are drawn, so it never touches type.
        w, h = buf.width, buf.height
        band = int(0.17 * h)
        y0 = int(DISC_FY * h) - band
        if y0 < 0:
            y0 = 0
        y1 = int(DISC_FY * h) + band
        if y1 > h:
            y1 = h
        buf.pen = brush.noise(DISC_GRAIN)
        buf.rectangle(0, y0, w, y1 - y0)


def _disc_series(buf):
    _disc_series_paint(buf, 0.0)


def _disc_series_a(buf, t):
    _disc_series_paint(buf, t)

# ── BLACK LINE ───────────────────────────────────────────
# BLACK LINE -- a flat field of one rotating hue, crossed by two soft dark lines.

# @skinlab {"type": "number", "label": "Field saturation", "group": "Palette", "min": 0.0, "max": 1.0, "step": 0.01}
FIELD_SAT = 0.299


# @skinlab {"type": "number", "label": "Field value", "group": "Palette", "min": 0.3, "max": 1.0, "step": 0.01}
FIELD_VAL = 0.918


# @skinlab {"type": "number", "label": "Hue at t=0", "group": "Palette", "min": 0.0, "max": 360.0, "step": 5.0}
BLACK_LINE_HUE_START = 0.0


# @skinlab {"type": "number", "label": "Hue turns per loop", "group": "Motion", "min": -2.0, "max": 2.0, "step": 0.5}
BLACK_LINE_HUE_TURNS = 1.0


# @skinlab {"type": "number", "label": "Line darkness", "group": "Shape", "min": 0.02, "max": 0.60, "step": 0.005}
LINE_DARK = 0.173


# @skinlab {"type": "number", "label": "Line softness", "group": "Shape", "min": 0.004, "max": 0.10, "step": 0.002}
LINE_SOFT = 0.0176


# @skinlab {"type": "number", "label": "Vertical line X", "group": "Layout", "min": 0.0, "max": 1.0, "step": 0.01}
LINE_X = 0.5


# @skinlab {"type": "number", "label": "Horizontal line Y", "group": "Layout", "min": 0.0, "max": 1.0, "step": 0.01}
LINE_Y = 0.5


# @skinlab {"type": "number", "label": "Still phase", "group": "Layout", "min": 0.0, "max": 1.0, "step": 0.01}
BLACK_LINE_STILL_T = 0.0


_BLACK_LINE_STOPS = 15


_REACH = 2.8


_BLACK_LINE_CACHE = {}


def _black_line_hsv(h, s, v):
    """HSV to an 8-bit triple. The reference's low channel sits on 164 with a
    high of 234, which is exactly V 0.9176 at S 0.2991, so this is the same
    parameterisation it used."""
    h = h - 360.0 * math.floor(h / 360.0)
    c = v * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = v - c
    if h < 60.0:
        r, g, b = c, x, 0.0
    elif h < 120.0:
        r, g, b = x, c, 0.0
    elif h < 180.0:
        r, g, b = 0.0, c, x
    elif h < 240.0:
        r, g, b = 0.0, x, c
    elif h < 300.0:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (int((r + m) * 255.0 + 0.5), int((g + m) * 255.0 + 0.5),
            int((b + m) * 255.0 + 0.5))


def _black_line_build(buf):
    """The two line brushes, held.

    They depend only on the canvas size: the lines never move and the black
    they composite has no hue, so the ONLY thing `animate` changes is the field
    colour underneath. Rebuilding a 15-stop gradient twice a frame would be 30
    colour allocations a frame for a picture that is identical every time.
    """
    w, h = buf.width, buf.height
    key = (w, h, LINE_DARK, LINE_SOFT, LINE_X, LINE_Y)
    if _BLACK_LINE_CACHE.get("key") == key:
        return _BLACK_LINE_CACHE
    sigma = LINE_SOFT * h
    if sigma < 0.4:
        sigma = 0.4
    reach = int(_REACH * sigma) + 1
    stops = []
    for i in range(_BLACK_LINE_STOPS):
        pos = i / float(_BLACK_LINE_STOPS - 1)
        d = (pos * 2.0 - 1.0) * reach
        a = LINE_DARK * math.exp(-d * d / (2.0 * sigma * sigma))
        stops.append((pos, color.rgb(0, 0, 0, int(255.0 * a + 0.5))))
    cx = int(w * LINE_X)
    cy = int(h * LINE_Y)
    _BLACK_LINE_CACHE["key"] = key
    # Both gradients run the full width of their band, so the brush's clamp past
    # the end point never has to paint anything: the end stops are alpha 0.
    _BLACK_LINE_CACHE["vpen"] = brush.gradient(brush.LINEAR, cx - reach, cy, cx + reach, cy, stops)
    _BLACK_LINE_CACHE["hpen"] = brush.gradient(brush.LINEAR, cx, cy - reach, cx, cy + reach, stops)
    _BLACK_LINE_CACHE["vrect"] = (cx - reach, 0, 2 * reach, h)
    _BLACK_LINE_CACHE["hrect"] = (0, cy - reach, w, 2 * reach)
    return _BLACK_LINE_CACHE


def _black_line_paint(buf, t):
    held = _black_line_build(buf)
    w, h = buf.width, buf.height
    r, g, b = _black_line_hsv(BLACK_LINE_HUE_START + 360.0 * BLACK_LINE_HUE_TURNS * t, FIELD_SAT, FIELD_VAL)
    # One opaque pass over the whole canvas. This is the cheap kind of pixel --
    # no read, no blend -- and it is also the clear, so `animate` needs no
    # separate `clear()` on top of the backdrop the app re-blits.
    buf.pen = color.rgb(r, g, b)
    buf.rectangle(0, 0, w, h)
    # Two alpha passes over 17.5% of the canvas. Order does not matter: black at
    # alpha commutes, because both are multiplies.
    x, y, bw, bh = held["vrect"]
    buf.pen = held["vpen"]
    buf.rectangle(x, y, bw, bh)
    x, y, bw, bh = held["hrect"]
    buf.pen = held["hpen"]
    buf.rectangle(x, y, bw, bh)


def _black_line(buf):
    _black_line_paint(buf, BLACK_LINE_STILL_T)


def _black_line_a(buf, t):
    _black_line_paint(buf, t)

# ── DOT SPHERE ───────────────────────────────────────────
# DOT SPHERE -- a cloud of dots on a sphere, turning once per loop.

# @skinlab {"label": "Dots", "group": "Shape", "type": "integer", "min": 16, "max": 200}
DOTS = 76


# @skinlab {"label": "Sphere radius", "group": "Layout", "type": "number", "min": 0.10, "max": 0.48, "step": 0.005}
SPHERE_R = 0.375


# @skinlab {"label": "Dot size", "group": "Shape", "type": "number", "min": 0.004, "max": 0.05, "step": 0.001}
SPHERE_DOT = 0.0140


# @skinlab {"label": "Depth size gain", "group": "Shape", "type": "number", "min": 0.0, "max": 0.8, "step": 0.01}
SPHERE_DEPTH_SIZE = 0.344


# @skinlab {"label": "Dot grey", "group": "Palette", "type": "integer", "min": 40, "max": 255}
SPHERE_MID = 180


# @skinlab {"label": "Depth grey swing", "group": "Palette", "type": "integer", "min": 0, "max": 110}
SPHERE_SWING = 64


# @skinlab {"label": "Ground", "group": "Palette", "type": "color"}
SPHERE_GROUND = (18, 18, 22)


# @skinlab {"label": "Turns per loop", "group": "Motion", "type": "integer", "min": -3, "max": 3}
SPHERE_TURNS = 1


# @skinlab {"label": "Sphere centre Y", "group": "Layout", "type": "number", "min": 0.25, "max": 0.75, "step": 0.005}
SPHERE_CENTRE = 0.5


# @skinlab {"type": "number", "label": "Still phase", "group": "Layout", "min": 0.0, "max": 1.0, "step": 0.01}
DOT_SPHERE_STILL_T = 0.0


_DOT_SPHERE_TAU = 2.0 * math.pi


_DOT_SPHERE_LEVELS = 24


_SEED = 11


_DOT_SPHERE_CACHE = {}


def _dot_sphere_build(buf):
    """The point cloud in screen units, the level palette, and the buckets.

    An integer LCG rather than a float hash. `random` is banned and a float
    hash of the `frac(sin(i)*43758)` kind is precision-sensitive: MicroPython's
    float width is a build option, so the browser and the badge could disagree
    on which picture this is. Integer arithmetic is exact everywhere, and this
    runs once.

    Points are stored PRE-SCALED to pixels, so the per-frame loop is four
    multiplies and two adds with no division: the depth divisor is folded into
    the level scale and the size gain below.
    """
    w, h = buf.width, buf.height
    key = (w, h, DOTS, SPHERE_R, SPHERE_DOT, SPHERE_DEPTH_SIZE, SPHERE_CENTRE)
    if _DOT_SPHERE_CACHE.get("key") == key:
        return _DOT_SPHERE_CACHE
    short = w if w < h else h
    radius = short * SPHERE_R
    cx = w * 0.5
    cy = h * SPHERE_CENTRE
    pts = []
    s = _SEED
    for _ in range(DOTS if DOTS > 0 else 1):
        # Uniform in z is uniform ON THE SPHERE (Archimedes), which is what the
        # reference's latitude counts measure as -- 6, 8, 13, 8, 11, 5, 5, 10
        # per 0.2 of z against 8.25 expected.
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        z = s / 1073741823.5 - 1.0
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        lon = _DOT_SPHERE_TAU * s / 2147483647.0
        ring = math.sqrt(1.0 - z * z) if z * z < 1.0 else 0.0
        pts.append((radius * ring * math.cos(lon),
                    int(cy + radius * z + 0.5),
                    radius * ring * math.sin(lon)))
    g = SPHERE_GROUND
    top = _DOT_SPHERE_LEVELS - 1
    _DOT_SPHERE_CACHE["key"] = key
    _DOT_SPHERE_CACHE["pts"] = pts
    _DOT_SPHERE_CACHE["cx"] = cx
    # Per PIXEL of depth, not per unit of it, so the loop never divides.
    _DOT_SPHERE_CACHE["lscale"] = top * 0.5 / radius
    _DOT_SPHERE_CACHE["ground"] = color.rgb(g[0], g[1], g[2])
    _DOT_SPHERE_CACHE["levels"] = [
        color.rgb(*(3 * (max(0, min(255, int(SPHERE_MID - SPHERE_SWING
                                            + 2.0 * SPHERE_SWING * i / top))),)))
        for i in range(_DOT_SPHERE_LEVELS)]
    # The radius ladder: one retained circle per depth level, about the ORIGIN
    # so that a plain translation places it. Both cues -- size and grey -- are
    # functions of the same level index, so the whole picture is 24 shapes.
    dot = short * SPHERE_DOT
    span = dot * SPHERE_DEPTH_SIZE
    _DOT_SPHERE_CACHE["discs"] = [
        shape.circle(0.0, 0.0, max(0.35, dot - span + 2.0 * span * i / top))
        for i in range(_DOT_SPHERE_LEVELS)]
    # Pre-allocated and cleared in place every frame. Growing 24 lists from
    # empty each time would be 24 allocations a frame for no reason.
    _DOT_SPHERE_CACHE["buckets"] = [[] for _ in range(_DOT_SPHERE_LEVELS)]
    return _DOT_SPHERE_CACHE


def _dot_sphere_paint(buf, t):
    held = _dot_sphere_build(buf)
    w, h = buf.width, buf.height
    buckets = held["buckets"]
    levels = held["levels"]
    discs = held["discs"]
    cx = held["cx"]
    lscale = held["lscale"]
    off = (_DOT_SPHERE_LEVELS - 1) * 0.5
    was_aa = buf.antialias
    # Antialias ON for the dots, and put back afterwards. At 160x120 -- the size
    # SAVE TO HOME bakes into the launcher film -- a dot is 3.4 px across and at
    # 40x30 it is under a pixel; picovector's default is OFF (`image.hpp:153`),
    # and this is the skin in the set whose wallpaper ink has the least room.
    # It only reaches the dots because they go through `buf.shape`; see the
    # header for what `image.circle` does with this setting.
    buf.antialias = image.X4
    buf.pen = held["ground"]
    buf.rectangle(0, 0, w, h)
    ang = _DOT_SPHERE_TAU * SPHERE_TURNS * t
    ca = math.cos(ang)
    sa = math.sin(ang)
    for b in buckets:
        del b[:]
    # One pass to place every dot in a depth bucket. The buckets ARE the
    # painter's order AND the radius ladder's index: a near dot must cover a far
    # one, the reference's blobs merge often enough that the order is visible,
    # and bucketing costs about 0.3 ms against a per-frame sort of 76 items.
    for px, py, pz in held["pts"]:
        buckets[int((px * sa + pz * ca) * lscale + off + 0.5)].append(
            vec2(cx + px * ca - pz * sa, py))
    for i in range(_DOT_SPHERE_LEVELS):
        bucket = buckets[i]
        if not bucket:
            continue
        buf.pen = levels[i]
        disc = discs[i]
        for at in bucket:
            disc.transform = mat3.trs(at, 0.0)
            buf.shape(disc)
    # LEAVE THE SURFACE AS IT WAS FOUND: `animate`'s buffer IS the screen and
    # antialias is sticky per surface.
    buf.antialias = was_aa


def _dot_sphere(buf):
    _dot_sphere_paint(buf, DOT_SPHERE_STILL_T)


def _dot_sphere_a(buf, t):
    _dot_sphere_paint(buf, t)

# ── DOT RING ───────────────────────────────────────────
# DOT RING -- ninety dots on a flat ring, tumbling end over end once per loop.

# @skinlab {"label": "Dots", "group": "Shape", "type": "integer", "min": 12, "max": 160}
RING_DOTS = 90


# @skinlab {"label": "Ring radius", "group": "Layout", "type": "number", "min": 0.10, "max": 0.48, "step": 0.005}
RING_R = 0.375


# @skinlab {"label": "Dot size", "group": "Shape", "type": "number", "min": 0.004, "max": 0.05, "step": 0.001}
RING_DOT = 0.0129


# @skinlab {"label": "Depth size gain", "group": "Shape", "type": "number", "min": 0.0, "max": 0.8, "step": 0.01}
RING_DEPTH_SIZE = 0.29


# @skinlab {"label": "Dot grey", "group": "Palette", "type": "integer", "min": 40, "max": 255}
RING_MID = 164


# @skinlab {"label": "Depth grey swing", "group": "Palette", "type": "integer", "min": 0, "max": 110}
RING_SWING = 51


# @skinlab {"label": "Ground", "group": "Palette", "type": "color"}
RING_GROUND = (20, 20, 20)


# @skinlab {"label": "Turns per loop", "group": "Motion", "type": "integer", "min": -3, "max": 3}
RING_TURNS = 1


# @skinlab {"label": "Ring centre Y", "group": "Layout", "type": "number", "min": 0.25, "max": 0.75, "step": 0.005}
RING_CENTRE = 0.5


# @skinlab {"type": "number", "label": "Still phase", "group": "Layout", "min": 0.0, "max": 1.0, "step": 0.01}
DOT_RING_STILL_T = 0.25


_DOT_RING_TAU = 2.0 * math.pi


_DOT_RING_LEVELS = 24


_DOT_RING_CACHE = {}


def _dot_ring_build(buf):
    """The rows, the level palette, and the ground colour.

    A row is every dot sharing one value of `R sin u`: same y, same depth, same
    size, same grey, differing only in x. `sin` takes each value twice in a
    turn, so 90 dots collapse to about 46 rows. The key is rounded because two
    mathematically equal sines can differ in their last bits -- a pair that
    fails to merge costs one extra pen change and draws the identical picture.
    """
    w, h = buf.width, buf.height
    key = (w, h, RING_DOTS, RING_R, RING_DOT, RING_DEPTH_SIZE, RING_CENTRE)
    if _DOT_RING_CACHE.get("key") == key:
        return _DOT_RING_CACHE
    short = w if w < h else h
    radius = short * RING_R
    cx = w * 0.5
    cy = h * RING_CENTRE
    rows = {}
    n = RING_DOTS if RING_DOTS > 2 else 3
    for i in range(n):
        u = _DOT_RING_TAU * i / n
        s = radius * math.sin(u)
        k = int(s * 64.0 + 0.5)
        xs = rows.get(k)
        if xs is None:
            rows[k] = [s, int(cx + radius * math.cos(u) + 0.5), -1]
        else:
            xs[2] = int(cx + radius * math.cos(u) + 0.5)
    # Sorted by the row key, which IS the depth order up to the sign of
    # cos(2*pi*t) -- see the header. This is what removes the per-frame sort.
    ordered = [rows[k] for k in sorted(rows)]
    g = RING_GROUND
    _DOT_RING_CACHE["key"] = key
    _DOT_RING_CACHE["rows"] = ordered
    _DOT_RING_CACHE["radius"] = radius
    _DOT_RING_CACHE["cy"] = cy
    _DOT_RING_CACHE["ground"] = color.rgb(g[0], g[1], g[2])
    top = _DOT_RING_LEVELS - 1
    _DOT_RING_CACHE["levels"] = [
        color.rgb(*(3 * (max(0, min(255, int(RING_MID - RING_SWING
                                             + 2.0 * RING_SWING * i / top))),)))
        for i in range(_DOT_RING_LEVELS)]
    # The radius ladder: one retained circle per depth level, about the ORIGIN
    # so a plain translation places it -- see the header for why a scale may not
    # be used here and why `image.circle` may not be used at all.
    dot = short * RING_DOT
    span = dot * RING_DEPTH_SIZE
    _DOT_RING_CACHE["discs"] = [
        shape.circle(0.0, 0.0, max(0.35, dot - span + 2.0 * span * i / top))
        for i in range(_DOT_RING_LEVELS)]
    return _DOT_RING_CACHE


def _dot_ring_paint(buf, t):
    held = _dot_ring_build(buf)
    w, h = buf.width, buf.height
    rows = held["rows"]
    levels = held["levels"]
    discs = held["discs"]
    radius = held["radius"]
    cy = held["cy"]
    was_aa = buf.antialias
    # Antialias ON for the dots, and put back afterwards. At 160x120 -- the size
    # SAVE TO HOME bakes into the launcher film -- a dot is 3 px across and at
    # 40x30 it is under a pixel; with picovector's default (OFF, image.hpp:153)
    # most of the ring falls below the sampling grid and the wallpaper loses its
    # artwork. Skins draw axis-aligned work, so switching it on cost the whole
    # catalogue 0.996x (engineering-findings). It only reaches the dots because
    # they go through `buf.shape`; see the header for what `image.circle` does.
    buf.antialias = image.X4
    buf.pen = held["ground"]
    buf.rectangle(0, 0, w, h)
    ang = _DOT_RING_TAU * RING_TURNS * t
    tilt = math.sin(ang)
    # `near` is -z, so a positive value is toward the viewer. Folded into the
    # row key here rather than computed per dot.
    lean = -math.cos(ang) / radius
    scale = (_DOT_RING_LEVELS - 1) * 0.5
    # Far to near. The row list is sorted by `R sin u`; depth is that times
    # -cos(2*pi*t), so the sign of the cosine chooses the DIRECTION of the walk
    # and there is nothing to sort.
    walk = range(len(rows) - 1, -1, -1) if lean > 0.0 else range(len(rows))
    for j in walk:
        row = rows[j]
        s = row[0]
        # One index serves three jobs: the pen, the radius, and (through the
        # walk direction above) the painter's order.
        lv = int(s * lean * scale + scale + 0.5)
        buf.pen = levels[lv]
        disc = discs[lv]
        y = cy + s * tilt
        disc.transform = mat3.trs(vec2(row[1], y), 0.0)
        buf.shape(disc)
        if row[2] >= 0:
            disc.transform = mat3.trs(vec2(row[2], y), 0.0)
            buf.shape(disc)
    # LEAVE THE SURFACE AS IT WAS FOUND. `animate`'s buffer IS the screen and
    # antialias is sticky per surface (skins.py `_supabase` is the cautionary
    # tale for its sibling `fill_rule`).
    buf.antialias = was_aa


def _dot_ring(buf):
    _dot_ring_paint(buf, DOT_RING_STILL_T)


def _dot_ring_a(buf, t):
    _dot_ring_paint(buf, t)


# ── registry ───────────────────────────────────────────────────────────────

# (name, group index, render, animate-or-None, face)
SKINS = (
    ("TRACE MAP", 0, _g_trace_map, _g_trace_map_a, "absolute"),
    ("OSCILLOSCOPE", 1, _g_oscilloscope, _g_oscilloscope_a, "outflank"),
    ("PLASMA", 1, _plasma, _plasma_anim, "more"),
    ("LATE SHIFT", 2, _g_late_shift, _g_late_shift_a, "vest"),
    ("OUTER RIM", 2, _g_outer_rim, _g_outer_rim_a, "ignore"),
    ("SYNTHWAVE", 4, _synthwave, _synthwave_anim, "more"),
    ("NOT LOADING", 5, _g_not_loading, _g_not_loading_a, "smart"),
    ("TEST CARD", 5, _testcard, _testcard_anim, "bacteria"),
    ('AERO RIBBON', 6, _aero_ribbon, _aero_ribbon_a, 'futile'),
    ('AQUA GEL', 6, _aqua_gel, _aqua_gel_a, 'more'),
    ('REEF TANK', 6, _reef_tank, _reef_tank_a, 'bacteria'),
    ('BLISS HILL', 8, _bliss_hill, _bliss_hill_a, 'yesterday'),
    ('CARD CASCADE', 8, _card_cascade, _card_cascade_a, 'manticore'),
    ('MINEFIELD', 8, _minefield, _minefield_a, 'smart'),
    ('PAINTBOX', 8, _paintbox, _paintbox_a, 'bacteria'),
    ('3D PIPES', 8, _pipes_3d, _pipes_3d_a, 'troll'),
    ('VERCEL', 10, _vercel, _vercel_a, 'absolute'),
    ('STRIPE', 10, _stripe, _stripe_a, 'bacteria'),
    ('RESEND', 10, _resend, _resend_a, 'smart'),
    ('BOLT', 10, _bolt, _bolt_a, 'badgewaremax'),
    ('GRAFANA', 10, _grafana, _grafana_a, 'bacteria'),
    ('DOPPLER', 10, _doppler, _doppler_a, 'badgewaremax'),
    ('POSTHOG', 10, _posthog, _posthog_a, 'ziplock'),
    ('ANTHROPIC', 10, _anthropic, _anthropic_a, 'badgewaremax'),
    ('PG SLEEP', 11, _pg_sleep, _pg_sleep_a, 'smart'),
    # MOVED TO THE TAIL, 2026-08-26, on the owner's instruction after a device
    # review: *"supabase is good, but no longer the default. move it to the end"*.
    # ITS GROUP CHANGED 0 -> 12 (BRAND -> EVENT) BECAUSE THE POSITION FORCED IT:
    # `test_entries_are_contiguous_within_their_group` holds each group to one
    # run, so a row at the tail must carry the tail group. EVENT is the honest
    # home -- it sits beside `SUPABASE SELECT`, the other entry drawn from the
    # same event's art. The group is an internal tag no app persists (see the
    # note above `GROUPS`), so this moved a jump-key stop and nothing else.
    ("SUPABASE", 12, _supabase, _supabase_anim, "badgewaremax"),
    ('BREATH', 13, _breath, _breath_a, 'badgewaremax'),
    ('SCRIM', 13, _scrim, _scrim_a, 'badgewaremax'),
    ('DOT DASH', 13, _dot_dash, _dot_dash_a, 'badgewaremax'),
    ('DOT MATRIX WAVE', 13, _dot_matrix_wave, _dot_matrix_wave_a, 'badgewaremax'),
    ('THRESHOLD', 13, _threshold, _threshold_a, 'badgewaremax'),
    ('ACRYLIC', 13, _acrylic, _acrylic_a, 'badgewaremax'),
    ('CONVEX LENS', 13, _convex_lens, _convex_lens_a, 'badgewaremax'),
    ('PRISMATIC', 13, _prismatic, _prismatic_a, 'badgewaremax'),
    ('DISC SERIES', 13, _disc_series, _disc_series_a, 'badgewaremax'),
    ('BLACK LINE', 13, _black_line, _black_line_a, 'badgewaremax'),
    ('DOT SPHERE', 13, _dot_sphere, _dot_sphere_a, 'badgewaremax'),
    ('DOT RING', 13, _dot_ring, _dot_ring_a, 'badgewaremax'),
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
