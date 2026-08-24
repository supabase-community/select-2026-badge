"""THE BADGE AS A STRANGER SEES IT: artwork, marks, name.  One code path.

Extracted verbatim from `identity/badge/identity/identity_view.py`, which is
still the only place any of it is edited from a product point of view -- this
module IS that code, moved, not a second rendering of the same idea.  Every
docstring below was written against the defect it prevents and is kept with the
code it explains.

WHY IT IS ITS OWN MODULE.  Two apps draw this picture: `identity`, where the
poster is the resting state of a 12,000-line editor, and `poster`, the
open-instantly wearer's badge reachable from the launcher's home screen.  A
badge app that "looks about right" is the exact failure the identity preview
was built to make impossible, so the two must not be two renderings -- they are
one object, constructed with the same injected APIs and called with the same
four-key plan.  `identity_view.IdentityView` DELEGATES here; it holds no copy.

Vendored into both apps byte-identically by `scripts/sync_ui.py`, for the
reason that script's header states: there is no `/system/lib` on the device and
an app that imports out of a neighbour's directory refuses to start when the
neighbour is not installed.  A copy is forced; a second EDITABLE copy is not.

THE ARTWORK MODULES ARE IMPORTED LAZILY AND EXACTLY ONE OF THEM RUNS.
`identity_view` used to import `skins` (666,336 B, ~120 function objects all
executed at import to build one tuple) and `glyphskin` (41,235 B) at module
scope, so every launch parsed both to draw one background.  A badge wears ONE
entry, and `identity_catalogue.kind_of` already knows which module can draw it,
so the import happens at the point of use.  Nothing about the picture changes;
the launch stops paying for the half of the catalogue it is not showing.

INJECTED, NEVER IMPORTED: `screen`, `image`, `color`, `font`, `vec2`, `rect`
and `ui.Chrome` all arrive through the constructor, which is what lets
`identity/tests` build a real renderer against a recording surface at CPython
speed and keeps `test_identity_purity` able to prove this module reads no
global it was not handed.
"""

import identity_catalogue as catalogue
import identity_faces as faces
import effects


# LAZY MODULE SLOTS.  `None` means "not imported yet"; the accessors below fill
# them in on first use and `sys.modules` makes the second call free.  They are
# module globals rather than locals so a test can substitute a double the way
# `test_identity_view` already substitutes `glyphskin.skin`.
skins = None
glyphskin = None
marks = None
backdrop_cache = None


def _skins():
    global skins
    if skins is None:
        import skins as module
        skins = module
    return skins


def _glyphskin():
    global glyphskin
    if glyphskin is None:
        import glyphskin as module
        glyphskin = module
    return glyphskin


def _marks():
    global marks
    if marks is None:
        import identity_marks as module
        marks = module
    return marks


def _cache():
    """The backdrop cache codec, or None if this build does not ship it.

    GUARDED, unlike the three accessors above, and the reason is what each one
    is for: without `skins` there is no artwork and the poster is broken, while
    without `backdrop` there is merely no cache and the poster is what it was
    last month.  A vendored copy that has not landed yet, or an app that chose
    not to carry the module, must degrade to the live render rather than raise
    on the launch path.
    """
    global backdrop_cache
    if backdrop_cache is None:
        try:
            import backdrop as module
        except ImportError:
            return None
        backdrop_cache = module
    return backdrop_cache


# Bumped whenever this renderer would draw DIFFERENT PIXELS from the same skin.
# `card_model.BAKE_VERSION`'s idiom and its exact reason: the cache answers
# "would re-rendering produce the same picture?", and the answer is no when the
# painter changed even though nothing the wearer owns did.  It is hashed into
# `cache_stamp`, so a bump invalidates every cached backdrop on every badge in
# the field, which is the whole point of having it.
#
# THE ARTWORK MODULE IS FINGERPRINTED SEPARATELY, by `catalogue.SKINS_REV`,
# because that is the change nobody would remember to bump this for: an edit to a
# skin changes the picture without changing anything here.  That constant is a
# CONTENT digest of `namebadge/badge/namebadge/skins.py` emitted by
# `badgecard/host/generate_catalogue.py`, so the two live together: this constant
# is the deliberate lever and the digest is the automatic net.
BACKDROP_CACHE_VERSION = 1


def cache_stamp(app_root="", module_name="skins"):
    """The fingerprint every cached backdrop is keyed on, or 0 for "no cache".

    Composed HERE rather than in each seam so the two apps cannot key their
    caches differently -- a writer and a reader that disagree about the stamp is
    a cache that never hits, and the symptom (everything works, nothing is
    faster) is one nobody would ever notice.  THAT SYMPTOM WAS REAL FROM
    2026-08-21 TO 2026-08-22, on every deployed badge and on no host lane, and
    the fix is the `SKINS_REV` branch below.

    THE ARTWORK FINGERPRINT IS CONTENT, NEVER THE FILE'S SIZE.  This used to be
    `module_bytes(app_root)`, a stat of the app's own `skins` module, and under
    source that is correct: `sync_ui.py` makes the vendored copies
    byte-identical, so the editor and the worn badge agree.  Under BYTECODE it
    cannot be: `mpy-cross` embeds the repo-relative source path as the traceback
    name, so `badgecard/badge/badgecard/skins.py` and
    `poster/badge/poster/skins.py` -- identical in content, six characters apart
    in path length -- compile to `.mpy` files six bytes apart in SIZE.  Every
    deployed badge therefore had an editor writing a cache the worn badge could
    never read.  `catalogue.SKINS_REV` is a digest of the bytes a human edits, so
    it is the same number in both apps and in both packaging modes.

    READING IT COSTS NO IMPORT, which is the other half of why it lives in the
    catalogue: `identity_catalogue` is imported at this module's scope already,
    while `skins` is 666,336 bytes the whole cache exists to not import on a hit.

    `app_root` is the seam's own install directory, which is the one thing this
    module cannot derive: it has no `__name__` to read and no business knowing
    where an app lives.  Empty means "do not fingerprint the artwork", which
    still keys on the version and the catalogue's shape.  It is still ACCEPTED
    and still used, for the fallback: a build whose catalogue predates
    `SKINS_REV` keys on the size exactly as it used to, so a partial install
    degrades to the old miss rather than to two apps agreeing on nothing.
    """
    module = _cache()
    if module is None:
        return 0
    artwork = getattr(catalogue, "SKINS_REV", 0) if module_name == "skins" else 0
    if not artwork:
        artwork = module.module_bytes(app_root, module_name) if app_root else 0
    return module.stamp(BACKDROP_CACHE_VERSION, catalogue.COUNT, artwork)


# EVERY PIXEL CONSTANT IN THIS MODULE IS A LOGICAL PIXEL, and every use site
# multiplies it by `ui.Chrome.scale`.  A logical pixel is 0.375 mm on the
# ruler-measured 60x45 mm panel at both resolutions -- 1 panel pixel at LORES
# (which the hardware doubles) and 2 at HIRES -- so a constant here is a
# PHYSICAL quantity that survives the flip.
#
# Content is inset from the left edge by this much, and the same amount from
# the right, so every line of copy has `width - 2 * TEXT_X` to live in.
TEXT_X = 6

# The poster's nickname block.  A fraction of the canvas rather than a pixel, so
# it survives the resolution flip the way `shared/ui.py` requires.
NAME_FY = 0.12
# Widest integer scale the display face is allowed to reach, per unit of
# `chrome.scale`.  Three is 36 px of type on a 120 px canvas, which is a poster;
# four would leave no room for the second line.  At HIRES the ceiling is six,
# which is the SAME 30% of the canvas -- a bitmap face drawn at scale 2 on a 1:1
# panel is pixel-identical to the same face at scale 1 on a pixel-doubled one,
# so the poster keeps its physical size and gains three more steps of headroom
# that LORES simply cannot reach.
# MOVED UP AND CAPPED SMALLER, 2026-08-21, on the owner's instruction after
# seeing it on the panel: a three-character name was drawn 120 px tall on a
# 240 px canvas -- exactly half the screen -- and it covered the artwork it was
# supposed to sit on. Measured, at HIRES with `badgewaremax`:
#
#     cap 6 (old)   SAM 234x120 px   spans 0.30 .. 0.80 of the height
#     cap 4 (new)   SAM 156x 80 px   spans 0.12 .. 0.45
#     any name of 9+ characters is scale 2 at EVERY cap -- 40 px, unchanged
#
# So the cap is a lever on SHORT names only, which are exactly the ones that
# were too big; long names are limited by the width budget and never reach it.
# That is why lowering it costs nothing elsewhere.
NAME_MAX_SCALE = 2

# Where the poster's type is drawn, as a fraction of the canvas, so the
# luminance sample and the draw cannot drift apart.  The band runs the full
# width because a centred name of unknown length can sit anywhere across it.
# MOVED WITH `NAME_FY`, and it has to be: this band is where the polarity
# decision samples luminance, and the comment above says the sample and the
# draw must not drift apart. It brackets the type -- two points above the name
# top, down past where the second line lands under the tallest short name
# (0.12 + 80/240 = 0.45).
NAME_BAND_FY = (0.10, 0.50)
# Every glyph is drawn eight times in the outline colour, then once in the fill.
# An OUTLINE, never a box: a plate behind the name hides the artwork the wearer
# chose, and the whole point of the picker is that they chose it.
OUTLINE_OFFSETS = ((-1, -1), (0, -1), (1, -1), (-1, 0),
                   (1, 0), (-1, 1), (0, 1), (1, 1))
# The transparent margin the retained name plate keeps around the type, in
# logical pixels.  It has to hold the outline, which is one logical pixel out on
# every side, plus whatever a face overshoots its measured box by -- four is
# `namebadge`'s eight at HIRES, expressed the way every other constant in this
# module is so it means the same distance in millimetres at both resolutions.
NAME_PLATE_PAD = 4
# Mean luminance below this and the name is drawn white on black, above it and
# the polarity flips.  `namebadge`'s number, and it is the same 0.36 the glyph
# treatment LUTs are cut at and `host/proto/proto-scrim-rule.mjs` bisects
# against; one threshold for the whole product.
DARK_ENOUGH = 0.36
# Every sixth LOGICAL pixel on both axes.  189 `get()` calls over the band,
# taken ONCE per background rather than per frame -- the answer cannot move
# until the artwork does.
#
# SCALED, so HIRES samples the same points at the same physical positions
# rather than four times as many.  Two reasons, and the second is the one that
# matters: `get()` boxes a `color` object per call, and the polarity of the type
# is then a property of the ARTWORK rather than of the resolution -- the two
# builds agree on which of the 76 backgrounds are pale, by construction.
LUMA_STEP = 6

# The two mark sheets, vendored byte-identically from `namebadge` by
# `scripts/sync_ui.py`.  NOT one asset at two sizes: 24 px 1-bit is authored for
# the pixel-doubled LORES canvas where the chunk IS the aesthetic, and 36 px
# MULTI-shade for 1:1 HIRES where a 1-bit threshold measurably breaks thin marks
# into dashes (docs/engineering-findings.md).  Which one loads is decided by
# `ui.Chrome.scale`, so a HIRES variant of either app changes nothing here.
#
# How many shades is NOT a constant and nothing here needs to know: a P8 sheet
# carries its own palette, and the generator spends whatever the 256 entries
# have left over after one per distinct brand ink.  It was 3 up to 84 inks and
# is 2 at the current 100.
MARK_SHEET_LORES = "assets/stickers-24-p8.png"
MARK_SHEET_HIRES = "assets/stickers-36-p8.png"
# The cell a mark falls back to when no sheet loaded, in LORES logical pixels.
# It matches the LORES sheet so the placement cursor is the same size either
# way -- a badge whose art did not install must still be a badge you can place
# marks on and get the same layout from once it does.
MARK_STUB_PX = 24

# THE ONE WEARER-FACING SENTENCE THIS MODULE OWNS, and it is here rather than
# in either app because both apps draw it in the same situation and a second
# copy would be the sentence drifting between the two.  I5's fifteen-second
# test is "boot the app, count to ten, look: does anything on screen name a
# key?", and an unconfigured badge is an abstract wash with no affordance at
# all without it.
EMPTY_HINT = "PRESS ANY BUTTON"

# The poster's own dark field, as three channels rather than as a `color`,
# because a `color` needs the injected API and this constant is read before
# there is one: the badge app paints this field at module scope BEFORE its
# first import, and `poster/tests/test_poster_app.py` fails if the literal it
# uses there and this tuple ever differ.
DARK_RGB = (9, 14, 24)

# THE POSTER'S LAST RUNG, hoisted out of the frame path.  It was
# `faces.ladder()[0]` inside a tuple display in `_poster_face`, and Python
# builds a tuple display EAGERLY -- so a 37-element `sorted()` with a lambda key
# ran on every frame that drew a name, even when the wearer's own face won on
# the first candidate, to produce this constant.  Pure-Python work is the slow
# kind on this device.
LADDER_HEAD = faces.ladder()[0]
# The 37 faces this build ships, as a membership test.  `identity_model` answers
# the same question with `face_id in FACES` and `test_identity_faces` pins
# `faces.ids() == model.FACES`, so this is that answer without dragging 48,490
# bytes of schema, migration and `json` into a renderer.
KNOWN_FACES = faces.ids()


def mark_origin(fx, fy, width, height, cell_w, cell_h):
    """Top-left pixel for a mark whose CENTRE sits at (fx, fy) of the canvas.

    THE STORED FRACTION IS THE MARK'S CENTRE, and that is the one decision here
    that a resolution flip can prove right or wrong.  `namebadge` stores the
    TOP-LEFT fraction, which is fine while the cell size is fixed and wrong the
    moment it is not: its LORES cell is 24 px on a 160 px canvas (0.150 of the
    width) and its HIRES cell is 36 on 320 (0.113), so the same saved fraction
    puts the mark's middle 1.9 px further left and 1.9 px further up at HIRES.
    Storing the centre moves the error onto the EDGES of the mark, where it is a
    fifth of the size and where nothing is aligned to anything.

    Pure, and a free function rather than a method, so `test_identity_view` can
    run it at 160x120 with a 24 px cell and at 320x240 with a 36 px cell and
    assert the drawn centre lands on the same fraction of the canvas.

    Rounded rather than truncated, for `ui.Chrome`'s reason: `int()` biases
    every position down by up to a pixel and makes the answer depend on float
    precision, which is how the same source resolved a softkey to 27 on the
    badge and 28 in the playground.
    """
    return (int(width * fx + 0.5) - cell_w // 2,
            int(height * fy + 0.5) - cell_h // 2)


def row_h(chrome):
    """One row of chrome type plus its breathing room."""
    return chrome.text_h + 2 * chrome.scale


def fallback_backdrop(buf, color_api):
    """The fallback background: a vertical wash and a horizon.

    NOT THE ONLY BACKGROUND -- `skins.render` draws the 87 procedural entries
    and `glyphskin` plays the 18 glyph ones -- but still the answer for a glyph
    entry whose pack will not open, and for an id from a catalogue this build
    does not ship (schema rule 2 keeps that id rather than discarding it).

    The poster falls back to this SILENTLY and identity's browser says so IN
    WORDS, and the asymmetry is deliberate: a poster that announced the gap
    would be the first thing a wearer saw, while somebody choosing a background
    is exactly the person who needs to know which entries cannot be drawn yet.

    One filled rectangle per row -- 120 C-backed calls at LORES and 240 at
    HIRES -- once per selection, never per frame.  What it has to be is DARK,
    because the badge draws white type over it at a metre.
    """
    width, height = buf.width, buf.height
    span = height - 1 if height > 1 else 1
    for y in range(height):
        t = y * 255 // span
        buf.pen = color_api.rgb(8 + t // 12, 12 + t // 7, 26 + t // 5)
        buf.rectangle(0, y, width, 1)
    horizon = height * 3 // 4
    buf.pen = color_api.rgb(62, 207, 142, 40)
    buf.rectangle(0, horizon, width, 1)
    buf.pen = color_api.rgb(255, 255, 255, 12)
    step = max(6, height // 8)
    for y in range(horizon + step, height, step):
        buf.rectangle(0, y, width, 1)


def plan_for(state, now_ms=0, frame=0, animate=None):
    """The four keys of `identity_app.plan` this renderer actually reads.

    `identity` passes its own 24-key plan and this function is never called
    there; the badge app has no controller and builds the same four fields.
    Written here rather than in that app so "what the poster reads" is stated
    once, next to the code that reads it.

    `animate` defaults to the motion policy a screen showing the badge's OWN
    background applies (`identity_app.animate_id`, third clause): the entry
    animates whenever `motion` is on.
    """
    background = state["background"]
    if animate is None:
        animate = background if state["motion"] else ""
    return {"state": state, "animate": animate, "now": now_ms, "frame": frame}


class Poster:
    """Artwork, marks and name, drawn with injected APIs and nothing else.

    `chrome` is a `ui.Chrome`, built by the caller because it reads the global
    `screen` in its constructor and the resolution has to be settled before
    either app builds anything at all.
    """

    def __init__(self, screen, image_api, color_api, font_api, vec2_api,
                 rect_api, chrome):
        self.screen = screen
        self.image = image_api
        self.color = color_api
        self.font = font_api
        self.vec2 = vec2_api
        self.rect = rect_api
        self.chrome = chrome
        scale = chrome.scale

        # The millimetre grid, resolved once.  Every draw call below reads one
        # of these rather than a literal, so a band cannot silently halve in
        # millimetres when the panel flips.
        self.text_x = TEXT_X * scale
        self.luma_step = LUMA_STEP * scale
        self.name_max_scale = NAME_MAX_SCALE * scale
        self.plate_pad = NAME_PLATE_PAD * scale
        # The `font_size` a ROM PIXEL face is drawn at for one step of the
        # millimetre grid.  0 is picovector's sentinel for "the face's own
        # size", i.e. nearest-neighbour scale 1, so LORES keeps the exact pixel
        # path -- and byte-identical output -- it has today, while HIRES draws
        # the same bitmap at scale 2 for the same physical size.
        self.rom_size = 0 if scale == 1 else scale
        # The face currently selected, the `font_size` it is drawn at, and
        # whether its metrics are exactly linear in that size.  `_use` is the
        # only writer; every measurement and every draw reads them, which is
        # what stops a caller drawing 17 px of chrome type at 2 pt.  ONE owner
        # of this state per app: `IdentityView` routes its own type through
        # here rather than keeping a second copy, because there is only one
        # `screen.font` and two trackers of it would desynchronise.
        self._face = None
        self._pt = 0
        self._pixel = True

        # THE WEARER'S FULL-CARD EFFECT, an id out of `effects.SHIPPED`.
        #
        # AN ATTRIBUTE RATHER THAN A FIELD OF THE PLAN, and the reason is the
        # archived app.  `identity` calls `worn()` with its own 24-key plan
        # whose state has no `effect` key at all, so reading one out of the plan
        # would be a `KeyError` inside a draw path -- which on a badge is
        # `badgeware.fatal_error` and a RESET.  Defaulting here means an app
        # that never heard of effects is provably unaffected, and the two apps
        # that have one set it from their own state: `poster` once at open,
        # `card_view._sync` every frame, so an APPLY shows on the next paint.
        self.effect = effects.NONE
        #: What the last `worn()` actually applied, which is not always what was
        #: asked for: an id from a newer build and a runtime missing the filter
        #: both degrade to NONE. The browser lane reads this rather than pixels.
        self.effect_applied = effects.NONE

        # THE FILL RULE TYPE HAS TO BE DRAWN UNDER, resolved once.  EVEN_ODD is
        # picovector's own per-surface default (`image.hpp`) and the only rule
        # that draws a hole from an inner contour whichever way it is wound;
        # `_use` restores it before every text draw.  None means a runtime that
        # does not name it, which degrades to "whatever the surface has".
        self._even_odd = getattr(image_api, "EVEN_ODD", None)

        self.dark = color_api.rgb(DARK_RGB[0], DARK_RGB[1], DARK_RGB[2])
        self.white = color_api.rgb(255, 255, 255)
        self.black = color_api.rgb(0, 0, 0)
        self.accent = color_api.rgb(62, 207, 142)
        self.band = color_api.rgb(0, 0, 0, 210)
        self.drift_ink = color_api.rgb(255, 255, 255, 16)

        # ONE full-screen buffer for the artwork, and one entry of cache.
        #
        # Full-screen rather than content-sized so the poster and identity's
        # browser share it: two sizes would mean two rasterises every time the
        # wearer opened the browser and came back, and the 13 px the bar covers
        # cost nothing to draw.  One entry is enough because a frame draws
        # exactly one background.
        #
        # BUFFER-BACKED, AND THAT IS WHAT MAKES THE PERSISTED CACHE POSSIBLE.
        # `image(w, h, buffer)` keeps a raw pointer to the bytes -- the same
        # property `_build_plate` and `card_bake.Baker.canvas` already rely on --
        # so `backdrop.load_into(self._backdrop_buf, ...)` repaints the surface
        # the poster blits every frame with no copy and no second allocation.
        # The pixel bytes are the same 307,200 either way at HIRES; what is new
        # is a Python reference to them.
        #
        # A RUNTIME THAT REFUSES THE THREE-ARGUMENT FORM STILL GETS A POSTER.
        # The fallback is the two-argument surface this line used to be, with
        # the cache silently switched off -- which is the same degrade-never-
        # fail trade `plated` makes for its plate and `marks_ready` for the
        # mark sheet.
        self._backdrop_buf = None
        try:
            # 307,200 B at HIRES (320 x 240 x 4), allocated ONCE here. It is the
            # largest single allocation the app makes, and it is deliberately
            # taken before the 953 KB mark sheet rather than beside it. It is
            # also what makes the persisted cache possible at all: the codec
            # loads into these bytes, which is why `_cache_ready` refuses when
            # this is None.
            self._backdrop_buf = bytearray(chrome.width * chrome.height * 4)
            self.backdrop = image_api(chrome.width, chrome.height,
                                      self._backdrop_buf)
        except (MemoryError, TypeError, ValueError):
            self._backdrop_buf = None
            self.backdrop = image_api(chrome.width, chrome.height)
        self._backdrop_id = ""
        # -- the persisted backdrop cache (shared/backdrop.py) --------------
        #
        # OFF UNTIL AN APP OPTS IN, by design.  `cache_stamp` is the fingerprint
        # of everything that decides the pixels and only a SEAM can compute it
        # -- it needs the artwork module's file size, and this module has no
        # business knowing an install path.  Zero means "no cache", which is
        # what every host test that does not ask for one gets.
        self.cache_stamp = 0
        self.cache_path = None
        self.cache_root = "/"
        # Did the bytes in `backdrop` come off the volume rather than out of the
        # rasteriser?  The app reads this to decide whether there is anything
        # worth writing back.
        self.cached = False
        # Test-observable for the same reason `renders` is: "the artwork was
        # read, not drawn" is not a thing anybody can judge by eye.
        self.hits = 0
        # The ink polarity `_sample_ink` chose, as the one bit the cache stores.
        self.pale = False
        # The write in flight, held so the surface's own bytes cannot change
        # underneath it unnoticed.  `_abandon_writer` is the only reader.
        self._writer = None
        # The glyph deck.  OPENED ON DEMAND: `open_pack` is one or two file
        # opens plus a ~600 B directory read, but reaching it means importing
        # `glyphskin`, and 58 of the 76 catalogue entries never need it.
        # `warm()` is how identity keeps its construction-time open.
        self._pack = None
        self._pack_open = False
        # ONE painter at a time, replaced whenever the background changes.  A
        # painter holds a tile cache of up to ~300 cells, so keeping one per
        # entry would be a megabyte to browse a deck of eighteen.  The one that
        # exists is RETARGETED rather than rebuilt where the cell geometry
        # allows, which is what keeps that cache warm across a browse.
        self.artist = None
        # Test-observable, and it exists to be ASSERTED rather than eyeballed:
        # "the artwork lands once" is not something anyone can judge by eye at
        # twenty rows a second.
        self.renders = 0
        # (name fill, name outline, second-line fill) for the artwork currently
        # in `backdrop`, chosen by `_sample_ink` when it is rendered.  The M3
        # colours are the starting value so a poster that has drawn no artwork
        # yet -- which is exactly what the badge app's first painted name sits
        # on -- still has something legible to draw with.
        self.ink = (self.white, self.black, self.accent)

        # THE MARK SHEET.  One `image.load` and one `spritesheet`, because a
        # mark is a fixed-dimension native P8 blit -- the hardware sweep
        # measures 148-172 us per cell-selection-plus-blit at LORES
        # (docs/engineering-findings.md), so a full badge of 24 marks is about
        # 4 ms against a ~22.8 ms frame.  Nothing here transforms art at
        # runtime: an animated mark SELECTS a pre-rendered cell.
        #
        # LOADED ON DEMAND, unlike the version this was extracted from, which
        # paid an estimated 38-78 ms at LORES in every constructor including
        # one for a badge with zero stickers.  `marks_ready()` is the single
        # acquisition path and `warm()` is identity's way of taking it at
        # construction, so the two apps differ in WHEN and never in WHAT.
        self.mark_sheet = None
        self._sheet_tried = False
        self._mark_ids = {}
        self.mark_w = self.mark_h = MARK_STUB_PX * scale

        # Resolved ROM faces, kept because `font.<name>` is a filesystem read
        # and identity's typeface list asks for up to five of them.  Bounded by
        # the 37 faces the ROM carries, which is also what makes an unbounded
        # dict safe here: the keys come from `identity_faces`, never from the
        # wearer.
        self._rom = {}

        # THE RETAINED NAME PLATE, and it is HIRES-ONLY BY DESIGN.  The nine
        # passes `outlined` makes are the most expensive thing a resting badge
        # draws; `namebadge` already measured that plating them is not merely
        # cheaper than the vector build (655 host units) but cheaper than the
        # BITMAP build it replaced (105 against a plate blit's 35), and ships
        # the keyed version.  This is that mechanism, moved into the renderer
        # both apps draw through instead of living in one app's `__init__`.
        #
        # `_plate_buf` is held ON PURPOSE and is not dead state.  `image(w, h,
        # buffer)` keeps only a raw pointer to the bytes; the 2026-08-16 device
        # probe found a plate built from an inline temporary surviving eight
        # rounds of churn but explicitly refused to call that a contract, and
        # named `namebadge`'s inline-temporary plates as the follow-up.  A
        # reference costs one slot and removes the question.
        #
        # `plates` is test-observable for the same reason `renders` is: "the
        # nine passes happen once" is not something anyone can judge by eye at
        # thirty frames a second.
        #
        # AND THE DEVICE AGREES WITH THE HOST UNITS ABOVE, which is the number to
        # keep if only one survives: warm 20.11 FPS with 0 plate builds against
        # cold 15.43 FPS with 180 builds in 180 frames -- +4.68 FPS (1.30x), and
        # 22.097 ms off the median frame for 58,240 B of retained buffer. Do not
        # "simplify" this into an inline temporary: that trades 58 KB for a third
        # of the frame rate.
        self.name_plate = None
        self._plate_key = None
        self._plate_buf = None
        self.plates = 0

    # -- resources ---------------------------------------------------------

    def warm(self):
        """Take every lazy resource NOW.  Identity's construction, unchanged.

        The editor opens the mark sheet before its first frame because its
        placement cursor, its filmstrip and its mark list all read `mark_w`
        with no sticker on the badge, and it opens the pack because its browser
        can reach a glyph entry from any row.  A wearer's badge does neither,
        which is the whole reason the accessors are lazy -- and calling them
        eagerly from one place keeps that a scheduling difference rather than a
        second code path.
        """
        self.pack
        self.marks_ready()

    @property
    def pack(self):
        """The glyph deck, opened once.

        `open_pack` is total -- a missing or corrupt pack is `None` and every
        glyph entry then draws the fallback wash.  A badge whose assets did not
        install must still be a badge.
        """
        if not self._pack_open:
            self._pack_open = True
            self._pack = _glyphskin().open_pack()
        return self._pack

    @pack.setter
    def pack(self, value):
        self._pack_open = True
        self._pack = value

    def marks_ready(self):
        """Load the mark sheet if it has not been tried.  Total on failure.

        The marks then draw as hollow squares of the same size, which is enough
        to keep placing, moving and deleting them honest, and identity's
        CATALOGUE says why in words.

        MEMORYERROR IS CAUGHT, AND IT IS THE ONE THAT MATTERS MOST NOW.  This
        sheet is the largest asset either app loads -- 953 KB resident at HIRES
        since 89 of the 116 marks animate, past the full-screen backdrop's 307 KB
        -- so it is the allocation most likely to fail on a fragmented heap, and
        the failure arrives HERE rather than anywhere quieter.  An uncaught
        MemoryError inside a screen build is `fatal_error()` -> modal ->
        `machine.reset()`: the wearer loses the badge, not the artwork.  A badge
        that draws hollow squares is still a badge you can place marks on, which
        is exactly the trade the rest of this method already makes for a missing
        or corrupt file.  `identity_view` catches it around its own asset load
        for the same reason.
        """
        if self._sheet_tried:
            return
        self._sheet_tried = True
        grid = _marks().GRID_COLS
        sheet = None
        try:
            sheet = self.image.load(MARK_SHEET_HIRES if self.chrome.scale > 1
                                    else MARK_SHEET_LORES)
        except (OSError, ValueError, MemoryError):
            sheet = None
        if sheet is not None:
            # Derived from the sheet, never assumed, so swapping the asset is
            # the whole change.
            self.mark_w = self.mark_h = int(sheet.width) // grid
            self.mark_sheet = sheet.spritesheet(
                grid, int(sheet.height) // self.mark_h)

    # -- type --------------------------------------------------------------

    def _use(self, face, size, pixel):
        """Select `face` AND remember how it has to be addressed.

        THE ONE WRITER of the type state, because the two kinds of face on this
        device take the same argument and mean different things by it.  A ROM
        `.ppf` reads `font_size` as an INTEGER NEAREST-NEIGHBOUR SCALE and
        cannot go below 1; a `.af` outline reads it as a POINT SIZE.  Selecting
        a face without recording which it is, is how a HIRES build draws its
        chrome at 2 pt -- a real failure mode, not a hypothetical, because 2 is
        exactly the scale the millimetre grid asks for.

        `size` keeps picovector's own sentinel: 0 means the face's default,
        which is scale 1 for a pixel font and 12 pt for an outline.  LORES
        therefore passes 0 everywhere it passes 0 today and the emitted calls
        are unchanged.
        """
        self.screen.font = face
        # AND THE FILL RULE, because type is what a wrong one breaks.  A skin's
        # animator is handed the SCREEN and `fill_rule` is STICKY, so an artwork
        # frame that stops on NON_ZERO fills the counter of every outline glyph
        # whose inner contour winds the same way as its body -- B, O, 8, Q, D, 0
        # and # in MonaSans-Medium, photographed on the owner's badge on
        # 2026-08-21 as "SUPA[]ASE" and "SAVE T() H()ME".  `_use` is the ONE
        # writer of the type state and it runs after the artwork on every frame
        # that draws a name, which is what makes it the right home.
        #
        # THE CONSTANT IS RESOLVED IN `__init__`, not read off `self.image`
        # here: that name is a CONSTRUCTOR as well as a namespace, and
        # `badgecard/tests/test_card_plate.py` legitimately replaces it with a
        # function to prove a refused allocation still draws the name.  A cache
        # must not be able to cost the wearer their badge, and neither may a
        # fill rule.
        if self._even_odd is not None:
            self.screen.fill_rule = self._even_odd
        self._face = face
        self._pt = size
        self._pixel = pixel

    def size(self, scale):
        """The `font_size` argument for `scale` steps of the millimetre grid."""
        return (self._pt or 1) * scale

    def text(self, message, x, y, pen=None, scale=1):
        if pen is not None:
            self.screen.pen = pen
        self.screen.text(message, x, y, self.size(scale))

    def measure(self, message, scale=1):
        """(width, height) in panel pixels, in the CURRENT font at `scale`.

        A pixel face is measured at ONE size and MULTIPLIED: its advance and
        line box scale exactly, so one `measure_text` answers every step and
        the LORES call is the same single call it has always been.

        An OUTLINE face is measured at the size it will actually be drawn at.
        Its metrics are close to linear but not guaranteed to be -- hinting and
        rounding live in the rasteriser -- and this measurement is what decides
        whether a name runs off the canvas, which is the one failure this
        hardware performs silently.
        """
        if self._pixel:
            width, height = self.screen.measure_text(
                message, font_size=self.size(1))
            return int(width) * scale, int(height) * scale
        width, height = self.screen.measure_text(
            message, font_size=self.size(scale))
        return int(width), int(height)

    def width(self, message, scale=1):
        return self.measure(message, scale)[0]

    def fit(self, message, budget, ceiling_scale, ceiling_h=0):
        """The largest integer step of the grid that fits `budget` wide.

        `ceiling_h`, when given, additionally keeps the result SHORTER than a
        line already drawn, which is how the poster's hierarchy is enforced.

        Two paths, because the two kinds of face fail differently.
        """
        if self._pixel:
            width, height = self.measure(message)
            scale = ceiling_scale
            while scale > 1 and (width * scale > budget
                                 or (ceiling_h and height * scale >= ceiling_h)):
                scale -= 1
            return scale
        # AN OUTLINE HAS NO INTEGER GRID.  It is already sized in points for
        # this panel, so it never grows here -- but it can do the one thing a
        # pixel face cannot, which is SHRINK CONTINUOUSLY.  So the answer is 1
        # when the string fits and a fraction of the point size when it does
        # not: at HIRES an over-long name gets smaller instead of running off
        # both edges of the canvas, which is exactly what LORES does today and
        # cannot be fixed there (`font.badgewaremax` cannot go below scale 1).
        #
        # Two measurements at most, and never per candidate step.  An outline's
        # width is very nearly linear in its point size, so the first ratio
        # lands within a pixel or two and the second pass turns "within" into
        # "under".  Fixed at two rather than looped to convergence because this
        # runs inside a draw call: a bounded cost is worth more here than a
        # guaranteed last pixel, and the caller centres what it measures.
        scale = 1.0
        for _ in range(2):
            width, height = self.measure(message, scale)
            room = 1.0
            if width > budget and width > 0:
                room = budget / float(width)
            if ceiling_h and height >= ceiling_h and height > 0:
                shorter = (ceiling_h - 1) / float(height)
                room = shorter if shorter < room else room
            if room >= 1.0:
                return scale
            scale *= room
            if scale <= 0.0:
                return 1.0
        return scale

    def chrome_font(self):
        """The chrome face: `font.sins` at LORES, MonaSans outlines at HIRES.

        `chrome.font_size` is non-zero exactly when `shared/ui.py` resolved a
        vector face, so it is both the point size and the flag.  A HIRES unit
        whose `/system` carries no `.af` falls back to a FINER bitmap face with
        a zero size, and lands on the pixel path here without a second test.
        """
        self._use(self.chrome.font, self.chrome.font_size,
                  not self.chrome.font_size)

    def display_font(self):
        """The face a name falls back to when its own is not in this build.

        `badgewaremax` at LORES; at HIRES the outline face at its display point
        size, which is the same object `shared/ui.py` hands the chrome and a
        very different size.
        """
        self._use(self.chrome.display_font,
                  self.chrome.display_size or self.rom_size,
                  not self.chrome.display_size)

    def rom_face(self, face_id, fallback):
        """A ROM face by name, cached.  Falls back rather than raising.

        A face the enum lists and this ROM does not carry must not be the reason
        a badge will not boot, and identity's typeface list asks for four or
        five faces every time it settles.  `False` is cached for a miss so a
        face that is not there costs one failed open rather than one per frame.
        """
        held = self._rom.get(face_id)
        if held is None:
            try:
                held = getattr(self.font, face_id)
            except (AttributeError, OSError):
                held = False
            self._rom[face_id] = held
        return held if held else fallback

    def poster_font(self, face_id):
        """Select a stored typeface, or the display face when it is not here.

        `state["face"]` is a FROZEN STRING, not an index, so a build that does
        not ship the face keeps the wearer's choice and falls back to something
        drawable -- rule 2 of the schema, rendered.

        It goes through `_use` rather than assigning `screen.font`, because the
        answer to "how do I address this face" differs between the two arms:
        a ROM face takes the integer grid step and an outline takes points, and
        a caller cannot tell which arm it landed in.
        """
        held = (self.rom_face(face_id, None)
                if face_id in KNOWN_FACES else None)
        if held is None:
            self.display_font()
        else:
            self._use(held, self.rom_size, True)

    def poster_face(self, face_id, text, budget):
        """Select the face for the name and return its scale.  Leaves it set.

        THE WEARER'S FACE FIRST, BUT A NAME THAT DOES NOT FIT IS NOT A NAME.
        `badgewaremax` is proportional and its `W` is 14 px, so the widest
        representable name -- twelve of them, exactly `NAME_MAX` -- measures
        165 px against a 148 px budget and a centred draw runs off BOTH edges
        of the canvas.  A pixel font takes integer scales only and cannot
        shrink below 1, so the only remaining move is a narrower face:
        `font.sins` advances 7 px on the same glyph, which caps any twelve
        character name at 84 px.  The fallback therefore always terminates.

        `None` in the middle of the ladder is the chrome face, which is the one
        rung that changes with the resolution: at LORES it is `font.sins` and
        at HIRES it is a real outline that could be fitted continuously.  It is
        still stepped rather than fitted, deliberately -- the wearer chose a
        BITMAP face from a list of thirty-seven, and a HIRES build that
        silently answered with a different typeface would be answering a
        different question from the one the picker asked.
        """
        for candidate in (face_id, None, LADDER_HEAD):
            if candidate is None:
                self.chrome_font()
            else:
                self.poster_font(candidate)
            if self.measure(text)[0] <= budget:
                return self.fit(text, budget, self.name_max_scale)
        return 1

    def outlined(self, message, x, y, scale, fill, outline):
        """Eight offset passes, then the fill.  An outline, never a box.

        A plate behind the name would hide the artwork the wearer just chose,
        and the whole point of the picker is that they chose it.  Nine C-backed
        `text` calls a frame is what `namebadge` already pays on the same
        hardware for the same reason.

        THE SIZE COMES FROM `size`, NOT FROM `scale`.  A grid step is not a
        `font_size`: at HIRES a ROM face wants twice the step and the chrome
        face wants seventeen times it, and passing the raw step here drew the
        poster's second line at ONE POINT.  It was invisible on screen and
        entirely invisible in the code -- the side-by-side capture is what
        found it, which is the third time that lane has caught what a review
        did not.
        """
        edge = self.chrome.scale
        size = self.size(scale)
        self.screen.pen = outline
        for offset_x, offset_y in OUTLINE_OFFSETS:
            self.screen.text(message, x + offset_x * edge, y + offset_y * edge,
                             size)
        self.screen.pen = fill
        self.screen.text(message, x, y, size)

    def plated(self, message, x, y, scale, fill, outline):
        """`outlined`, but the nine passes are RETAINED at HIRES.

        THE SAME PICTURE EITHER WAY, WITHIN A ROUNDING OF THE ANTIALIASED EDGE.
        The plate is those exact nine passes into a transparent buffer, blitted
        whole, so this is a scheduling change and not a second way of drawing a
        name -- but it is not byte-identical and the earlier "THE SAME PIXELS
        EITHER WAY" here was measurably wrong.  `badgecard/host/name_cost.mjs`
        draws a wash, then each path over it, and diffs: the ROM-face arms match
        exactly, and the FITTED VECTOR arm differs in 2,426 of 307,200 bytes at a
        worst channel of 4/255.  The cause is arithmetic and not a defect -- the
        direct path blends nine antialiased passes onto the artwork, the plate
        blends them onto TRANSPARENCY and blends the composite on, and those
        round differently at a coverage-masked edge.  Do not promise byte
        equality of the two paths in a test; promise it of the plate against
        itself, which is what `plates` and `plate_bytes` check.

        LORES KEEPS THE DIRECT PATH, and that is deliberate rather than
        unfinished: there the face is a ROM bitmap at scale 1 and the nine
        passes are the cheap kind, `namebadge` measured the plate winning only
        at HIRES and kept its own direct path for the same reason, and a
        160x120 badge is the build with the least heap to spend on a cache it
        does not need.  `chrome.scale` is the test, because that is what decides
        whether the face is a fitted outline in the first place.

        WHY IT IS ONLY THE NAME AND NOT `line2`.  One slot, keyed on content:
        two strings drawn from the same slot in one frame would evict each other
        every frame and pay the nine passes TWICE instead of never.  The name is
        the line that is always present, always the largest, and always the
        wearer's own -- and Badgecard has no second line at all (its D6).  A
        second slot is a later change with a measurement behind it, not a guess
        now.

        A FAILED ALLOCATION FALLS BACK RATHER THAN FAILING.  At HIRES this is up
        to ~100 KB beside a 307 KB backdrop and a 953 KB mark sheet, and the
        2026-08-20 conformance pass listed the free-heap margin for exactly this
        plate as an open device gate.  `MemoryError` here would otherwise be
        `fatal_error()` -> modal -> reset: the wearer losing the badge over a
        cache.  `marks_ready` already makes the same trade for the same reason.
        """
        if self.chrome.scale == 1:
            self.outlined(message, x, y, scale, fill, outline)
            return
        key = (message, self._face, self.size(scale), fill, outline)
        if self.name_plate is None or self._plate_key != key:
            self._build_plate(key, message, scale, fill, outline)
        if self.name_plate is None:
            self.outlined(message, x, y, scale, fill, outline)
            return
        pad = self.plate_pad
        self.screen.blit(self.name_plate, self.vec2(x - pad, y - pad))

    def _build_plate(self, key, message, scale, fill, outline):
        """Rasterise the nine passes once.  Leaves `name_plate` set, or None.

        THERE IS NO API TO CLEAR AN IMAGE BACK TO TRANSPARENT, so a rebuild is a
        fresh buffer and never a reset -- which is also why the key has to carry
        everything that can change a pixel: the string, the FACE object, the
        size it is drawn at and both inks.  The face is in there because
        `poster_face` walks a three-rung ladder and the same name at the same
        size in a different face is a different picture; `namebadge` could leave
        it out because it has exactly one display face and this renderer has
        thirty-eight.
        """
        self.name_plate = None
        self._plate_key = None
        self._plate_buf = None
        width, height = self.measure(message, scale)
        pad = self.plate_pad
        full_w = width + 2 * pad
        full_h = height + 2 * pad
        if full_w < 1 or full_h < 1:
            return
        try:
            # THE ONE ALLOCATION THIS WHOLE MECHANISM EXISTS TO PAY FOR, and it
            # is paid once per name rather than once per frame. Worst case in the
            # catalogue is 76,800 B; the worn HIRES badge holds 58,240 B. What it
            # buys per frame, measured on the host against the real rasteriser:
            # 575-705 us of direct outlining collapses to a 35-45 us blit, and
            # the whole `name()` path from 745 us to 65-85 us.
            buffer = bytearray(full_w * full_h * 4)
            plate = self.image(full_w, full_h, buffer)
        except MemoryError:
            return
        # X4 because picovector defaults antialiasing OFF per surface, and a
        # vector glyph below ~16 pt shatters without it -- `ui.Chrome` sets the
        # same value on the framebuffer and a plate that skipped it would draw a
        # visibly rougher name than the direct path it replaces.
        plate.antialias = self.image.X4
        plate.font = self._face
        edge = self.chrome.scale
        size = self.size(scale)
        plate.pen = outline
        for offset_x, offset_y in OUTLINE_OFFSETS:
            plate.text(message, pad + offset_x * edge, pad + offset_y * edge,
                       size)
        plate.pen = fill
        plate.text(message, pad, pad, size)
        self._plate_buf = buffer
        self.name_plate = plate
        self._plate_key = key
        self.plates += 1

    # -- artwork -----------------------------------------------------------

    def background(self, entry_id):
        """The full-screen buffer holding `entry_id`, rasterised at most once.

        THE ENTIRE COST MODEL OF THE PICTURE IS THIS METHOD.  A procedural skin
        is ~600 primitive calls and measured at 7.2-26.5 ms on device; a full
        screen written from a Python loop measured 703 ms.  So the artwork is
        drawn ONCE into an off-screen image and blitted thereafter, which is the
        contract `namebadge/badge/namebadge/skins.py` already states for its 58
        entries -- and identity's browser only ever asks for a new one on a
        SETTLE, so holding DOWN through 105 entries pays for one of them.

        `catalogue.index_of` IS the `skins.SKINS` index for a procedural entry:
        the generator emits the 87 skins first, in SKINS order, and
        `test_card_catalogue` pins both halves of that.  A parallel id-to-
        index table would be a second thing to keep in step for no gain.

        THE IMPORT OF THE ARTWORK MODULE HAPPENS HERE, which is what lets a
        badge wearing a procedural skin never parse `glyphskin` and a badge
        wearing a glyph entry never parse the 666,336 bytes of `skins`.

        AND THE PERSISTED CACHE IS READ HERE, for the same reason everything
        else about the cost model lives in this method: a hit costs one `open`,
        one 64-byte header, one `readinto` into the surface's own bytes and no
        rasteriser at all -- so the badge app's stage 2 becomes a blit, which is
        the owner's 2026-08-21 verdict answered.  A MISS COSTS 64 BYTES AND
        FALLS THROUGH to exactly the code that ran before this existed; the
        cache cannot make an open slower than a render.
        """
        if entry_id != self._backdrop_id:
            self._backdrop_id = entry_id
            # THE PIXELS ARE ABOUT TO BE REPLACED, so any write still in flight
            # over them is now writing the wrong picture under the right header.
            self._abandon_writer()
            if (catalogue.kind_of(entry_id) == catalogue.PROCEDURAL
                    and self._read_backdrop(entry_id)):
                # A PROCEDURAL ENTRY HAS NO PAINTER, so the artist a previous
                # glyph entry left behind is dropped exactly as the live path
                # below drops it.  `renders` is deliberately NOT bumped: it
                # counts rasterises, and the whole claim of this branch is that
                # there was not one.
                self.artist = None
                return self.backdrop
            self.cached = False
            self.renders += 1
            kind = catalogue.kind_of(entry_id)
            if kind == catalogue.GLYPH:
                self.artist = self._glyph_artist(entry_id)
            else:
                self.artist = None
            if kind == catalogue.PROCEDURAL:
                _skins().render(self.backdrop, catalogue.index_of(entry_id))
            elif self.artist is None:
                fallback_backdrop(self.backdrop, self.color)
            self._sample_ink()
        return self.backdrop

    # -- the persisted backdrop cache --------------------------------------

    def _cache_ready(self):
        """The codec, or None when this poster has no usable cache.

        Three conditions, and each one is a real build: no vendored module, no
        buffer-backed surface (the two-argument fallback in `__init__`), or an
        app that never set a stamp.  All three mean "render live", which is why
        they are answered together in one place rather than re-checked at two
        call sites.

        WHAT THE STAMP IS WORTH, so nobody deletes it as bookkeeping: on device,
        a cold `background()` is a 915.5 ms median on a MISS against 43.4 ms on a
        HIT -- 21.08x, about 872 ms off a wearer's arrival. The miss decomposes as
        a 626.9 ms cold `skins` import plus 257.3 ms of render, so the stamp is
        not saving a redraw, it is saving the 666 KB module import entirely.
        """
        if not self.cache_stamp or self._backdrop_buf is None:
            return None
        return _cache()

    def _read_backdrop(self, entry_id):
        """Fill the backdrop from the volume.  True if it now holds `entry_id`.

        Never raises: `backdrop.load_into` is total, and every one of its
        refusals -- no file, wrong magic, wrong id, wrong geometry, wrong stamp,
        wrong length -- lands here as False and therefore as a live render.
        """
        module = self._cache_ready()
        if module is None:
            return False
        header = module.load_into(self._backdrop_buf, entry_id,
                                 self.chrome.width, self.chrome.height,
                                 self.cache_stamp, self._path(module))
        if header is None:
            return False
        # THE INK COMES OUT OF THE HEADER, which is the second half of the
        # saving: `_sample_ink` is 189 `get()` calls and 189 boxed `color`
        # objects to answer one bit, and the bit was already measured against
        # these exact pixels when they were rendered.
        self._apply_ink(header["pale"])
        self.cached = True
        self.hits += 1
        return True

    def holds(self, entry_id):
        """Is `entry_id` the artwork currently in the backdrop?

        Public because a SCHEDULER needs it and reading `_backdrop_id` from
        outside would be reading a private: `backdrop_writer` returns None both
        for "this can never be cached" and for "the surface is showing something
        else right now", and a caller that cannot tell those apart either
        retries a glyph deck for ever or gives up on a skin for the session.
        """
        return self._backdrop_id == entry_id

    def backdrop_writer(self, entry_id):
        """A STEPPED writer for the rendered backdrop, or None.

        THE CALLER CHOOSES THE FRAMES, which is the whole reason this hands back
        a job instead of writing: a HIRES backdrop is ~300 KB of flash and
        `docs/badge-button-rules.md` I4 forbids a blocking write while a key is
        being serviced or real-time content is on screen.  The seam steps it on
        frames it judges spare.

        None -- nothing to write -- for four separate reasons, and each is a real
        state rather than a guard against a mistake: no cache on this build, the
        surface holds a different entry, the pixels CAME from the cache so
        writing them back would be a copy of a copy, or the entry is a glyph
        deck, whose painter owns the surface and would overwrite any cached
        frame with its own keyframe on the next open anyway.
        """
        module = self._cache_ready()
        if module is None:
            return None
        if self.cached or self._backdrop_id != entry_id:
            return None
        if catalogue.kind_of(entry_id) != catalogue.PROCEDURAL:
            return None
        self._writer = module.Writer(
            self._backdrop_buf, entry_id, self.chrome.width,
            self.chrome.height, self.cache_stamp, self.pale,
            self._path(module), self.cache_root)
        return self._writer

    def _abandon_writer(self):
        """Stop any write in flight, because the pixels under it just changed.

        THE BUG THIS EXISTS TO MAKE IMPOSSIBLE.  A `Writer` holds the SURFACE'S
        OWN BYTES, so a write still in flight when the wearer picks a different
        skin would put the second skin's pixels into a file whose header names
        the first.  That is the one failure mode of this whole design that a
        reader could not detect -- id, geometry, stamp and length would all
        agree -- so it is closed HERE, in the one method that knows the pixels
        are about to be replaced, rather than in a seam that might forget.
        """
        writer = self._writer
        if writer is not None:
            self._writer = None
            writer.abandon()

    def _path(self, module):
        return self.cache_path if self.cache_path else module.PATH

    def _glyph_artist(self, entry_id):
        """A painter for a glyph entry, or None if the deck cannot play it.

        The surface handed over is THIS APP'S OWN BACKDROP, which is the whole
        of `glyphskin`'s retained-surface model: the animation is diff-painted
        into the image the poster already blits every frame, so an animated
        glyph background costs the deltas and not a second full-screen write.

        RETARGETED WHERE POSSIBLE, because the glyph milestone built `retarget`
        for exactly this screen: the deck draws from one glyph bank and one
        palette, so most tiles are shared and a fresh painter per selection
        throws away a cache the next entry would have reused.  `retarget` itself
        refuses a stream that needs a different cell geometry, because every
        cached tile would then be the wrong size; all eighteen shipped streams
        are 32x12, so in practice it always succeeds.

        This used to be guarded by a remembered TREATMENT as well, since a
        retarget keeps the painter's LUT and a differing treatment would have
        made that silently the wrong palette.  With one LUT for the whole deck
        (below) the remembered value could never differ, so the guard was
        removed rather than left looking like a live decision.

        Cleared first.  The painter's record 0 is a full keyframe and a 32x12
        grid tiles a 160x120 canvas exactly, so nothing should survive
        underneath -- but "should" is doing work there, and a grid that does
        not divide the canvas would otherwise leave a border of the previous
        artwork around the new one.

        THE POSTER ALWAYS ASKS FOR `glyphskin.VIVID`, the byte-exact production
        palette: the owner rejected the old ghosted poster as barely visible on
        glass on 2026-08-16, and every glyph entry has wanted the full palette
        since.  It used to arrive through `catalogue.treatment_of`, a per-entry
        column whose eighteen glyph rows all said `vivid` -- a lookup that could
        only ever return one answer.  `home.finish` is deliberately NOT consulted
        here: that field is the wallpaper's, and this is the poster.  Authored
        mask coverage remains intact and the name keeps its polarity/outline.
        """
        pack = self.pack
        if pack is None:
            return None
        glyph = _glyphskin()
        self.backdrop.pen = self.black
        self.backdrop.clear()
        artist = None
        if self.artist is not None:
            if self.artist.retarget(pack.stream(entry_id)):
                artist = self.artist
        if artist is None:
            artist = glyph.skin(pack, entry_id, self.backdrop,
                                self.image, self.vec2, glyph.VIVID)
        if artist is None:
            return None
        self._converge(artist)
        return artist

    def _converge(self, artist):
        """Paint the whole of frame 0 NOW, rather than over the next few frames.

        `SkinPainter.advance` is deliberately BOUNDED -- at most twice its
        budget per call -- so one call from a cleared surface leaves a 384-cell
        grid between a quarter and a half painted.  With `motion` on the next
        frame finishes the job and nobody sees it.  With `motion` OFF there IS
        no next call, and the badge would show a half-drawn picture for as long
        as it is worn.  That is not a hypothetical: the first version of
        `identity/host/contact_sheet.mjs` captured after a single call and every
        glyph entry measured 0.000 luminance, which looked exactly like "the
        deck is too dark" rather than like a bug.

        The bound is a safety net rather than a budget: 384 cells over a 48-cell
        budget is eight calls, and `advance` is documented to converge for any
        budget >= 1.
        """
        for _ in range(24):
            if artist.caught_up:
                return
            artist.advance(0)

    def _sample_ink(self):
        """Pick the poster's type colours against the artwork actually rendered.

        THIS IS THE DEFECT THE CONTACT SHEET FOUND, and it is the whole argument
        for that lane.  M3's poster drew flat white type because the placeholder
        wash was always dark; with the real catalogue behind it, twelve of the
        fifty-eight skins are pale -- `bauhaus`, `riso`, `memphis-blvd`,
        `grid-break`, `dot-shock`, `stickerbomb`, `vanish-point`, `op-ripple`
        and friends -- and the name was WHITE ON WHITE.  A picker where a
        quarter of the choices make the badge unreadable is a trap, and it was
        completely invisible in the code.

        The fix is `namebadge`'s, unchanged, because it already measured the
        thing: sample the mean luminance of the band the type occupies and flip
        the polarity under 0.36.  Sampled once per background rather than per
        frame -- the answer cannot move until the artwork does, and it is 189
        `get()` calls, which is not a per-frame price for a constant.
        """
        top = int(self.chrome.height * NAME_BAND_FY[0])
        bottom = int(self.chrome.height * NAME_BAND_FY[1])
        total = 0.0
        samples = 0
        for y in range(top, min(bottom, self.chrome.height), self.luma_step):
            for x in range(0, self.chrome.width, self.luma_step):
                total += self.backdrop.get(x, y).luminance
                samples += 1
        dark = (total / samples if samples else 0.0) < DARK_ENOUGH
        self._apply_ink(not dark)

    def _apply_ink(self, pale):
        """The three type colours for a background of this polarity.

        SPLIT OUT OF `_sample_ink` so the cached path can reach the same answer
        without re-measuring it: the sweep above produces exactly one bit, the
        cache stores that bit beside the pixels it was measured from, and this
        is the one place that turns the bit into colours.  Two copies of this
        mapping would be the poster and its own cache disagreeing about the
        wearer's name.
        """
        self.pale = pale
        # The SECOND line keeps the accent over a dark background, because that
        # is the type hierarchy M3 established and the accent is legible there.
        # Over a pale one it goes black with the name: a 62,207,142 green on
        # cream is exactly the failure this method exists to remove.
        self.ink = (self.black, self.white, self.black) if pale else (
            self.white, self.black, self.accent)

    def overlay(self, plan, entry_id):
        """A procedural skin's own moving elements, over whatever was blitted.

        THE OTHER HALF OF B5, AND THE HALF NOBODY HAD SEPARATED.  `SETTLE_MS`
        defers the EXPENSIVE thing -- `render()`, the static layer -- and this
        is the cheap one.  Measured, per skin, by `badgecard/host/skin_cost.py`
        over a counting surface: every `render()` in the catalogue is 5 to 455
        primitive calls (median 121) and every `animate()` is 3 to 38 (median 24).
        The most expensive animator in the deck is 38 calls, which is cheaper
        than 71 of the 87 renders, so there is no entry that has to be excluded
        from running live and no cost class to maintain.  (Re-measured 2026-08-18
        [HOST]; the previous reading -- 5 to 210, median 95, and 1 to 28, median 7
        -- was the 58-entry catalogue's and had been stale since 2026-08-17.)

        Returns True when something was drawn, so the caller knows whether the
        fallback wash still owes the wearer some motion.  8 of the 87 skins are
        deliberately still and get nothing: dragging a foreign highlight across
        somebody's composition to prove a checkbox works is worse than the
        checkbox doing nothing here.

        A GLYPH ENTRY IS NOT HERE, and that is not an omission: `glyphskin`
        paints INTO the backdrop rather than over the screen, so its frame has
        to advance before the blit.  `advance` does that, from the same clock.
        """
        if catalogue.kind_of(entry_id) != catalogue.PROCEDURAL:
            return False
        module = _skins()
        index = catalogue.index_of(entry_id)
        if not module.animated(index):
            return False
        module.animate(self.screen, (plan["now"] % module.CYCLE_MS)
                       / float(module.CYCLE_MS), index)
        return True

    def drift(self, plan):
        """The fallback wash's own motion: one slow highlight crossing it.

        Only for a background with no artwork of its own -- an id from a build
        this one does not ship, or a glyph entry whose pack would not open.
        Without it `motion` would be a setting with no visible effect at all on
        a badge whose deck failed to install.
        """
        height = self.chrome.height
        scale = self.chrome.scale
        depth = max(4 * scale, height // 10)
        # SCALED, so the highlight crosses the panel in the same number of
        # SECONDS at either resolution.  A speed in panel pixels per frame is
        # half the physical speed once the panel is 1:1.
        y = (plan["frame"] * 3 * scale // 5) % (height + depth) - depth
        self.screen.pen = self.drift_ink
        self.screen.rectangle(0, y, self.chrome.width, depth)

    def motion(self, plan, entry_id):
        """Everything `motion` drives on a screen showing ONE background.

        The poster's case, where the static layer and the moving layer are the
        same entry by definition.  Identity's browser does not call this: while
        it scrubs those two are different entries, and telling them apart is the
        whole of that screen.
        """
        if self.overlay(plan, entry_id):
            return
        if catalogue.kind_of(entry_id) == catalogue.PROCEDURAL:
            return
        if self.artist is not None:
            return
        self.drift(plan)

    def advance(self, plan, entry_id):
        """Move a glyph background on, BEFORE the surface it lives in is blitted.

        Returns the buffer to blit, so every caller is a one-liner and none of
        them can get the ordering wrong.  `advance` is bounded by the painter's
        own budget and never raises: a surface that will not allocate is
        counted, and after three failures the painter stops trying rather than
        spending a budget of raising blits on every frame forever.
        """
        buffer = self.background(entry_id)
        if self.artist is not None and plan["animate"] == entry_id:
            self.artist.advance(plan["now"])
        return buffer

    # -- marks --------------------------------------------------------------

    def mark_index(self, mark_id):
        """`marks.index_of`, memoised.  -1 for an id this build does not ship.

        A linear scan of 69 is nothing a handful of times per screen -- which
        is exactly what `identity_catalogue` argues, and it is sized for that.
        It is NOT nothing once per mark per FRAME: the poster draws every mark
        on every frame for as long as the badge is worn, and a full one is 24
        of them, so the scan alone is ~1,650 Python comparisons against a
        22.8 ms budget.

        Bounded by the DATA, not by the wearer: the keys are sticker `kind`s,
        which `model.MAX_STICKERS` caps at 24, plus whatever identity's
        filmstrip has been scrolled past, which the table caps at 69.
        """
        index = self._mark_ids.get(mark_id)
        if index is None:
            index = _marks().index_of(mark_id)
            self._mark_ids[mark_id] = index
        return index

    def mark(self, mark_id, fx, fy, now_ms):
        """One mark, centred on (fx, fy).  Returns its top-left pixel.

        `now_ms` of 0 freezes the animation, which is what `motion` off means:
        `marks.cell` is stateless integer arithmetic over the clock, so there
        is no phase to reset and two badges started together stay in step.
        """
        self.marks_ready()
        grid = _marks().GRID_COLS
        x, y = mark_origin(fx, fy, self.chrome.width, self.chrome.height,
                           self.mark_w, self.mark_h)
        cell = _marks().cell(self.mark_index(mark_id), now_ms)
        if self.mark_sheet is None or cell < 0:
            # An unknown id -- schema rule 2 keeps one on purpose -- or no
            # sheet at all.  Drawn as an outline rather than skipped: a mark
            # the wearer cannot see is a mark they cannot move or delete, and
            # identity's list would then name a row with nothing behind it.
            self.screen.pen = self.accent
            edge = self.chrome.scale
            self.screen.rectangle(x, y, self.mark_w, edge)
            self.screen.rectangle(x, y + self.mark_h - edge, self.mark_w, edge)
            self.screen.rectangle(x, y, edge, self.mark_h)
            self.screen.rectangle(x + self.mark_w - edge, y, edge, self.mark_h)
        else:
            self.screen.blit(
                self.mark_sheet.sprite(cell % grid, cell // grid),
                self.vec2(x, y))
        return x, y

    def marks(self, plan, skip=-1):
        """Every mark on the badge, in stored order.

        Stored order IS top-to-bottom (`identity_model.sort_marks`), so a lower
        mark always overlaps the one above it -- the way a stack of real
        stickers does, and consistently rather than by accident of when each
        was placed.

        `skip` is the mark currently in identity's placement cursor.  It is
        still in `state` while it is being moved, so without this it would be
        drawn twice and the move would read as a duplicate.
        """
        stickers = plan["state"]["stickers"]
        now_ms = plan["now"] if plan["animate"] else 0
        for index in range(len(stickers)):
            if index == skip:
                continue
            mark = stickers[index]
            self.mark(mark["kind"], mark["x"], mark["y"], now_ms)

    # -- the picture ---------------------------------------------------------

    def badge(self, plan, skip=-1, name=True, marks=True):
        """The badge as a stranger sees it: artwork, marks, name.

        Every identity sticker screen draws this first and then adds its own
        chrome, which is what makes them previews rather than editors with a
        thumbnail: a mark is placed against the NAME as much as against the
        artwork, so the name has to be there while it is being placed.

        THE MARK LIST IS THE ONE SCREEN THAT PASSES `name=False`, and the
        screenshot is why.  Its four rows start at y = 51 and the poster's
        second line sits at about y = 58, so `SUPABASE` came through the scrim
        behind `GITHUB` -- text bleeding through a translucent band, which is
        the exact defect this repository has already shipped once and which was
        completely invisible in the code.

        `marks=False` is the badge app's STAGED first artwork frame and nothing
        else: it is the same composition with one layer not yet drawn, so the
        picture that arrives a moment later is the same call with the flag back
        on rather than a second rendering of the badge.
        """
        entry_id = plan["state"]["background"]
        self.screen.blit(self.advance(plan, entry_id), self.vec2(0, 0))
        if plan["animate"]:
            self.motion(plan, entry_id)
        if marks:
            self.marks(plan, skip)
        if name:
            self.name(plan)

    def name(self, plan):
        """The poster's two lines, over whatever is behind them.

        `ceiling` carries the name's drawn height down to the second line.
        THE NAME MUST NEVER BE THE SMALLER OF THE TWO: `badgewaremax` is a
        20 px face that a nine-character name already pins to scale 1, while
        `font.sins` at scale 2 is 24 px, so the obvious "fit each line to the
        width" rule drew SUPABASE taller than SAM MEECH.  It looked wrong in
        the picture and was invisible in the code.

        DRAWABLE BEFORE THE ARTWORK IS, which is what the badge app's staged
        arrival rests on: `ink` starts white-on-black-outline, the polarity
        that is legible over both halves of the catalogue by construction, and
        `_sample_ink` refines it the moment there is artwork to sample.  The
        face, the scale and the position are final from the first paint, so
        nothing reflows when the picture lands behind it.

        THE NAME GOES THROUGH `plated` AND THE SECOND LINE DOES NOT.  One
        retained plate, keyed, HIRES only; `plated` holds the whole argument,
        including why a single slot must not be shared with `line2`.  The
        polarity refinement above is the plate's main invalidation in practice:
        `_sample_ink` moves both inks once, on the frame the artwork lands, and
        the key catches it.
        """
        state = plan["state"]
        name = state["name"]
        budget = self.chrome.width - 2 * self.text_x
        y = int(self.chrome.height * NAME_FY)
        ceiling = 0
        fill, outline, second = self.ink
        if name:
            scale = self.poster_face(state["face"], name, budget)
            width, height = self.measure(name, scale)
            self.plated(name, (self.chrome.width - width) // 2, y, scale,
                        fill, outline)
            y += height + 2 * self.chrome.scale
            ceiling = height
        if state["line2"]:
            self.chrome_font()
            scale = self.fit(state["line2"], budget,
                             self.name_max_scale, ceiling)
            width, _height = self.measure(state["line2"], scale)
            self.outlined(state["line2"], (self.chrome.width - width) // 2, y,
                          scale, second, outline)

    def affordance(self):
        """The empty badge's one line of chrome, at the foot of the poster.

        What every wearer sees first, before anything is configured.  Without
        it the poster is an abstract wash with no affordance at all.
        """
        self.chrome_font()
        step = row_h(self.chrome)
        self.screen.pen = self.band
        self.screen.rectangle(0, self.chrome.height - step,
                              self.chrome.width, step)
        self.text(EMPTY_HINT, self.text_x,
                  self.chrome.height - step + self.chrome.scale, self.accent)

    def worn(self, plan, hint=True, marks=True):
        """At rest the badge is a poster: zero chrome, one name (D1).

        THE WHOLE RESTING PICTURE, and the reason this method exists rather
        than each app composing `badge()` and `affordance()` itself: those two
        call sites would be the drift.  `identity` calls this and then draws its
        softkey bar over it when the wearer wakes it; the badge app calls it and
        nothing else.

        AND IT IS WHERE THE WEARER'S EFFECT LANDS, LAST, OVER EVERYTHING.
        Three things follow from putting it exactly here and nowhere else:

        *   IT IS A FULL-CARD FILTER, which is what was asked for.  The name,
            the marks and the affordance line are all under it.  A filter over
            the artwork but not over the name reads as a defect rather than as
            an effect -- `snake_view` says the same thing about a game and its
            own HUD -- and it could not be otherwise anyway: the artwork lives
            in an off-screen surface that is composed onto the panel BEFORE the
            name is drawn.
        *   IT CANNOT COMPOUND.  Filters are not idempotent (two `invert`s are
            an identity; two `contrast`s are a third picture), and `poster` does
            not redraw a still badge -- `default_clear` is None and `update()`
            returns after one frame -- so a filter in a frame loop would be
            applied once on the badge that redraws and once per frame on the
            one that does not, forever.  Here it is one application per
            composition, by construction.
        *   IT DOES NOT TOUCH THE BACKDROP CACHE.  `card_cache` writes the
            artwork surface's OWN bytes, and this filters the panel, so the
            cached 307,264 B stay the unfiltered artwork: changing an effect
            invalidates nothing, and the browser lane's byte-identical
            cached-against-rendered claim still holds.  Baking the effect into
            the cache instead would have been cheaper per frame and wrong three
            ways -- `matches()` has no effect field to key on, so one wearer's
            cache would be served under another effect; the cache holds the
            artwork alone, so it could never carry a FULL-card filter; and
            `matches()` refuses another entry's file, so the first skin cached
            would be the only one that could ever be re-cached.
        """
        self.badge(plan, marks=marks)
        state = plan["state"]
        if hint and not state["name"] and not state["line2"]:
            self.affordance()
        self.effect_applied = effects.apply(self.screen, self.effect,
                                            self.color)
