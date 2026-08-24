"""Pixels for the Settings tile, at HIRES. Every decision it makes is in
``settings_model``; every word it draws is in ``settings_copy``.

THIS APP IS HIRES-ONLY. 320x240, 1:1, real vector outlines — one app, no LORES
variant, no ``variant.py``, nothing to branch on. That holds for every identity
surface: ``badgecard`` and ``poster`` are HIRES-only too, and only the games and
the launcher are LORES.

WHAT THE OWNER SAW ON THE PHYSICAL BADGE (2026-08-21) AND WHERE IT CAME FROM.
Three defects in one screenshot of the Confirm screen, all of them the same
mistake — a layout that was checked by eye rather than measured:

* **``DECLINE`` read as ``ECLIN``, clipped at BOTH ends.** ``font.sins`` draws
  it 41 px wide; ``ui.Chrome``'s softkey box at LORES is 34 px, and a centred
  label wider than its box overhangs by 3.5 px on each side, where
  ``overflow=image.ELLIPSES`` clips it. The findings ledger had already written
  down that six characters need measuring at LORES and that ``DELETE`` (35 px)
  busts the box; nothing measured this label. At HIRES, ``MonaSans-Medium@17``
  draws ``DECLINE`` at 65.1 px in a 68 px box — and the copy rework retires the
  string anyway, because the C key now answers the screen's question with
  ``NO`` (23.5 px).
* **The prompt was ellipsized on a mostly empty screen.** "Does your phone show
  this code?" is 186 px of ``font.sins`` against 154 px of LORES content width.
  At HIRES it is 233.9 px against 308, so it fits on ONE line with 74 px spare —
  and the screen it sits on has 214 px of content height for four things.
* **Everything was a pixel-doubled bitmap.** LORES renders 160x120 and the panel
  doubles it, so ``font.sins``' 7 px cap arrives as 14 physical px of staircase.
  HIRES draws the same chrome from outlines at 17 pt: an 11 px cap, 2.06 mm,
  17.73 arcmin at 400 mm — physically 21% SMALLER than the bitmap it replaces
  and sharp instead of chunky.

NOTHING HERE IS CHECKED BY EYE ANY MORE. ``settings/tests/test_settings_fit.py``
prices every string this app can draw against the band it is drawn in, from an
advance table measured out of the pinned rasteriser
(``settings/host/measure_settings_type.mjs`` -> ``settings/tests/settings_metrics.py``),
and fails on an overrun. The worst cases are in it too, because the server is
allowed to send a 64-character owner hint.

THREE RULES THIS FILE FOLLOWS THAT THE LORES VERSION DID NOT.

1. **POINT FORM, NEVER RECT FORM, for anything carrying data.** The rect form of
   ``screen.text`` is the only form that parses ``[...]`` glyph markup, and the
   firmware resolves the renderer name through a bare dict lookup — so
   ``[sprite:x]`` in an owner hint raises ``KeyError`` INSIDE ``update()``, which
   is the traceback modal and a reset (``docs/engineering-findings.md`` § "What a
   ``[`` in wearer text ACTUALLY does"). Rect form also eats ``[[``, so it lies
   even when it does not crash. Every string here is drawn at an ``(x, y)``, and
   the only rect-form draw left in the app is ``ui.Chrome.bar``'s three fixed
   labels. That removes the whole crash class rather than escaping around it.
2. **THIS APP WRAPS ITS OWN TEXT; the renderer's wrap is not enough.**
   ``measure_text(text, rect(...))`` wraps on WIDTH at word boundaries and
   leaves an unbreakable token at full width — measured 2026-08-21, a
   44-character claim URL reports 350.6 px inside a 200 px rect. And
   ``image.ELLIPSES`` cannot save it, because U+2026 has ZERO ink in
   ``MonaSans-Medium``: at HIRES the "degrade visibly" overflow mode degrades
   INVISIBLY. So :func:`_wrap` breaks words and, when it must, characters, and
   nothing in this file passes ``overflow=`` at all.
3. **WRAP ONCE PER COPY CHANGE, NOT ONCE PER FRAME.** The wrapped lines and
   their widths are retained in :class:`_Wrap` blocks and recomputed only when
   the string or the band changes, which is a screen transition. So the steady
   frame measures NOTHING — the discipline ``docs/engineering-findings.md``
   states as "measure chrome once, at construction, even when it looks free",
   and the same discipline the QR plate below already applies to the modules.

THE QR ENCODER IS A GUARDED IMPORT and that is not a browser accommodation.
``qrcode`` is an undocumented native C usermod compiled into the Tufty firmware
and into nothing else, so a bare import would make this app refuse to start on
any unit whose firmware lacks it — and an import that raises inside ``launch()``
resets the badge. Without it the Pair screen prints the claim URL as text, which
is legible, honest and typeable, and says so.
"""

import settings_copy
import ui


# The Supabase launcher palette, so the tile looks like the launcher it hangs
# off rather than like a fifth visual language (`launcher/menu/ui.py`).
BLACK = None
BACKGROUND = None
PHOSPHOR = None
DIM = None
WARN = None

_chrome = None
_list = None
# `pairview.qr_layout`, handed in by the app. NOT imported here: `pairview` lives
# in `/system/lib`, the app already guards that import once, and a lazy import
# inside a draw call would work in a harness and fail on the first frame after
# boot (`pg_runtime` pops the app directory off `sys.path` in a `finally`).
_qr_layout = None

# The native encoder, or None on a unit whose firmware has no usermod.
try:
    import qrcode
except ImportError:  # pragma: no cover - device/browser difference, not logic
    qrcode = None

#: ECC level the 152-character capacity boundary was measured at (R2-4).
QR_ECC = "ECC_MEDIUM"

#: Module scale ceiling for the claim square, passed to ``pairview.qr_layout``
#: rather than taken from its ``QR_MAX_SCALE`` default of 4.
#:
#: THE POINT OF HIRES FOR THIS SCREEN IS A PHYSICALLY BIGGER QR, and stacking
#: the square over its caption does not deliver one. At LORES the square is 82
#: logical px, which the panel doubles to 164 PHYSICAL px at 4 physical px per
#: module. A HIRES vertical stack reaches scale 4 -> 164 logical px, so the
#: modules land at exactly the same physical size and the phone gains nothing.
#: Putting the caption BESIDE the square instead frees the full content height,
#: which reaches scale 5: a 205 px square at 5 physical px per module, 25%
#: bigger ink for the camera, on a canvas that had 214 px of height and was
#: using 82 of them.
QR_MAX_SCALE = 5

#: The most body lines any screen this app draws can produce (the revoked
#: network screen: status, reason, link state, restart instruction). One
#: retained wrap block per slot, and a fit test asserts no model exceeds it.
MAX_BODY_LINES = 5

#: Characters :func:`_pieces` prefers to break a long token after, and how far
#: back it will look for one. A claim URL should break after a ``/`` rather than
#: in the middle of a hostname.
BREAK_AFTER = "/#-._:?&="
BREAK_LOOKBACK = 8

#: The truncation marker, as three ASCII periods. NOT U+2026, which measures
#: ZERO in this face — an invisible truncation marker is worse than none,
#: because it looks like the string simply ended. Nothing the app draws today
#: reaches this; `test_settings_fit` proves it and would fail if it did.
ELLIPSIS = "..."


class _QrPlate:
    """The claim QR, rasterised once per code and blitted on later full draws.

    THE PIXELS ARE A PURE FUNCTION OF THE PAYLOAD, and the payload changes on
    `pairstate`'s five-minute schedule — not per frame. Drawn directly, one Pair
    frame constructed a fresh `qrcode.QRCode`, encoded the whole URL, queried
    `modules ** 2` = 1089 modules and drew one `screen.rectangle` per dark
    module (about half of them), and then did all of it again on the next frame
    for identical pixels. Measured on the reference badge, that screen ran
    46 ms p99 in isolation and 55 ms p99 with the live transport polling on the
    same frames, against a <50 ms gate, while every other Settings screen in the
    same session measured 12 ms
    (`benchmark/results/reports/2026-08-19-v3.0.1-badgelink-p4-transport.md`).

    The precedent is the HIRES nickname, measured in `docs/engineering-findings.md`:
    nine-pass outlined text cost 655 drawn directly and 35 blitted from a
    retained plate, so the retained form was ALSO the cheaper one. Here a full
    draw after the build becomes one blit plus four fixed strings, none of
    which is measured. The managed :class:`RetainedFrame` skips that full draw
    entirely while the model is equal.

    MICROPYTHON RULES THIS SHAPE. One instance lives for the app's lifetime and
    its buffer is allocated ONCE: a code rotation repaints the existing image in
    place instead of asking for another ~168 KB, so neither a repeated full
    draw nor the rotation frame allocates the plate. The backing `bytearray` is held in an
    attribute rather than passed as an inline temporary, because `image` keeps
    only a raw pointer to it and the collector's tolerance of that is an
    implementation detail, not a contract (findings: the bare-image and
    buffer-lifetime device probe). The blit position is a retained `vec2` for
    the same reason — building one per frame would put an allocation back into
    the draw path this exists to empty.

    THE PLATE IS NOT ANTIALIASED, and that is a scannability decision rather
    than a saving. `ui.Chrome` sets `screen.antialias = image.X4` because vector
    glyphs below ~16 pt shatter without it; an `image` defaults to OFF and this
    one is left there, because a QR module with a soft edge is a QR module a
    camera has to guess at. `test_settings_view` asserts it.
    """

    def __init__(self):
        # What the current pixels were drawn for. Compared field by field: an
        # `(payload, ...)` tuple would allocate on every frame.
        self.payload = None
        self.top = -1
        self.available = -1
        self.left = -1
        self.image = None    # the plate, or None while the encoder refuses
        self.buffer = None   # its backing store, retained EXPLICITLY
        self.at = None       # the retained blit position
        self.next_y = 0      # what a refused payload continues from
        self.builds = 0      # rasterisations; probes and tests read this

    def ready(self, payload, top, available, left):
        """Bring the plate up to date for this payload and hand it back.

        Allocation-free and encoder-free when the code has not changed, which
        is every full draw but the first of each code.
        """
        if (payload == self.payload and top == self.top
                and available == self.available and left == self.left):
            return self
        self._build(payload, top, available, left)
        return self

    def _build(self, payload, top, available, left):
        self.payload = payload
        self.top = top
        self.available = available
        self.left = left
        code = qrcode.QRCode(ecc=getattr(qrcode, QR_ECC))
        if not code.set_text(payload):
            # 152 characters is the measured ECC-medium byte-mode boundary
            # (R2-4). A refused payload is a real product fault, so it is named
            # rather than drawn as an empty square — and the refusal is retained
            # like any other result, because re-encoding a payload the encoder
            # has already rejected, once a frame, is the same defect in a
            # smaller coat.
            self.image = None
            self.next_y = top + _line_h()
            self.builds += 1
            return
        modules = code.get_size()[0]
        layout = _qr_layout(modules, max(1, available), max_scale=QR_MAX_SCALE)
        scale = layout["scale"]
        border = layout["border_modules"]
        extent = layout["extent"]
        plate = self.image
        if plate is None or plate.width != extent:
            # The one allocation in the whole path, and it lands on a code
            # change rather than inside a frame. It is reused across rotations:
            # the extent is a property of the canvas, not of the code.
            #
            # WHY A PLATE AT ALL, since drawing the modules directly is simpler:
            # on device the pre-plate Pair screen ran a 46 ms frame p99 in
            # isolation and 55 ms with the transport live, against a 50 ms gate,
            # while every other Settings screen in the same session measured
            # 12 ms. The plate is 564 primitives and 1,091 encoder calls per
            # frame collapsed to 10 primitives and no encoder calls. `bytearray`
            # is held on `self` because `image(w, h, buffer)` keeps only a raw
            # pointer to the bytes.
            self.buffer = bytearray(extent * extent * 4)
            plate = image(extent, extent, self.buffer)
            self.image = plate
        # White quiet zone: the encoder's contrast requirement, not decoration.
        # Opaque, and covering the whole plate, so it is also how the previous
        # code is erased — there is no API to clear an image back to
        # transparent, and every pixel here is written by this fill or by a
        # module rectangle on top of it.
        plate.pen = color.rgb(255, 255, 255)
        plate.rectangle(0, 0, extent, extent)
        plate.pen = color.rgb(0, 0, 0)
        for row in range(modules):
            for column in range(modules):
                if code.get_module(column, row):
                    plate.rectangle(
                        (column + border) * scale,
                        (row + border) * scale,
                        scale,
                        scale,
                    )
        placed = top + layout["offset"]
        self.at = vec2(left, placed)
        self.next_y = placed + extent + _chrome.scale
        self.builds += 1


class _Wrap:
    """One string, folded into lines that fit a band, RETAINED.

    Recomputed only when the string or the band changes — a screen transition,
    not a frame. The widths come back with the lines because centring and
    right-alignment need them and point-form drawing cannot ask the renderer for
    them after the fact.
    """

    def __init__(self):
        self.text = None
        self.budget = -1
        self.max_lines = -1
        self.lines = ()
        self.widths = ()
        self.truncated = False

    def ready(self, text, budget, max_lines=1):
        if (text == self.text and budget == self.budget
                and max_lines == self.max_lines):
            return self
        self.text = text
        self.budget = budget
        self.max_lines = max_lines
        lines, widths, truncated = _wrap(text, budget, max_lines)
        self.lines = lines
        self.widths = widths
        self.truncated = truncated
        return self

    def height(self):
        return len(self.lines) * _line_h()


# The one plate, and the retained copy blocks. Replaced by `build()` rather than
# reused across chromes: a rebuilt chrome can be a different canvas, and a plate
# sized for the old one would blit the QR into the wrong place at the wrong
# scale while a wrap sized for the old one would be measured in the wrong face.
_plate = _QrPlate()
_title = _Wrap()
_body = ()
_countdown = _Wrap()
_caption = _Wrap()


class RetainedFrame:
    """Draw a complete Settings frame only when its view-model changes.

    Badgeware normally clears before every managed update.  Settings owns a
    complete opaque frame, so that clear would erase the retained pixels on an
    unchanged update.  This helper therefore disables the managed clear for
    exactly its own lifetime, remembers the exact previous value, and restores
    it idempotently when its owner exits. The app
    uses the HOME ``on_exit`` seam; the standalone device probe uses a
    ``finally`` around its manual loop.

    The first model is always painted.  Afterwards equality is the contract:
    a newly-created but equal model is retained, while any unequal model takes
    the existing full clear-and-draw path below.  ``Settings.view()`` returns a
    fresh model, so keeping the previous one does not alias mutable app state.
    """

    def __init__(self, badge_api, label_for):
        self._badge = badge_api
        self._label_for = label_for
        self._default_clear = badge_api.default_clear
        self._active = True
        self._has_model = False
        self._model = None
        self.draws = 0
        badge_api.default_clear = None

    def draw(self, model):
        """Paint ``model`` when required; return whether pixels changed."""
        if self._has_model and model == self._model:
            return False
        draw(model, self._label_for)
        self.draws += 1
        self._model = model
        self._has_model = True
        return True

    def restore(self):
        """Restore the exact pre-Settings managed clear, once."""
        if self._active:
            self._badge.default_clear = self._default_clear
            self._active = False

    def invalidate(self):
        """Force one full draw after an out-of-band render dependency changes."""
        self._has_model = False


def build(qr_layout=None):
    """Construct the chrome after `badge.mode` and before the first frame.

    `ui.Chrome` reads `screen.width` in its constructor, so it cannot be built
    at import time above the mode call — that is the mistake `kbgrid`'s own
    entry point documents. `qr_layout` is `pairview.qr_layout` when the shared
    library is installed and `None` when it is not; with no library there is no
    claim code to draw either, so the two absences agree.

    THE FACE IS LOADED EXACTLY ONCE, HERE. `ui.Chrome` calls `font.load` in its
    constructor behind an `OSError` guard: the `.af` outlines live on the FAT
    `/system` partition rather than in ROM, `font.load` is UNCACHED (~66 KB read
    into a fresh ~74 KB object, and a second call returns a DIFFERENT object),
    and a badge whose `/system` was rebuilt without them must still boot. So a
    missing face degrades to a bitmap face and never to a reset, and nothing in
    a draw path ever loads a font.
    """
    global BLACK, BACKGROUND, PHOSPHOR, DIM, WARN, _chrome, _list, _qr_layout
    global _plate, _title, _body, _countdown, _caption
    _qr_layout = qr_layout
    _plate = _QrPlate()
    _title = _Wrap()
    _body = tuple(_Wrap() for _ in range(MAX_BODY_LINES))
    _countdown = _Wrap()
    _caption = _Wrap()
    BLACK = color.rgb(1, 4, 4)
    BACKGROUND = color.rgb(5, 18, 16)
    PHOSPHOR = color.rgb(62, 207, 142)
    DIM = color.rgb(255, 255, 255, 150)
    WARN = color.rgb(255, 176, 72)
    # The bitmap fallback is this app's own choice and not `shared/ui.py`'s
    # default; `settings_copy.BITMAP_FALLBACK` says why in full.
    _chrome = ui.Chrome(fallback=getattr(font, settings_copy.BITMAP_FALLBACK))
    _list = ui.ListView(_chrome)
    _derive()
    return _chrome


def list_view():
    """The shared ListView, so the app can keep its index in step with it."""
    return _list


# -- bands, all derived from the chrome and none of them a literal ------------
#
# DERIVED ONCE IN `build()`, AND THAT IS NOT MICRO-OPTIMISATION. The first draft
# of this file computed them per call: `_qr_band` returned a fresh tuple every
# frame and `_column_x` asked `pairview.qr_layout` for a fresh DICT every frame,
# which put two allocations straight back into the one draw path the retained
# plate exists to empty. None of these numbers can change without a new chrome,
# and `build()` is the only thing that makes one.

_MARGIN = 0
_LINE_H = 0
_CONTENT_W = 0
_QR_TOP = 0
_QR_AVAILABLE = 0
_QR_LEFT = 0
_QR_EXTENT = 0
_COLUMN_X = 0
_COLUMN_W = 0


def _derive():
    """Resolve every band from the chrome. Called by `build()` and nowhere else."""
    global _MARGIN, _LINE_H, _CONTENT_W, _QR_TOP, _QR_AVAILABLE, _QR_LEFT
    global _QR_EXTENT, _COLUMN_X, _COLUMN_W
    scale = _chrome.scale
    # Side margin: three logical pixels at LORES was 1.125 mm; this is that.
    _MARGIN = scale * 3
    # Body line pitch: the em box plus 0.24 em of descender air. `measure_text`
    # returns the em box, and at 17 pt the ink reaches about 2 px past it, so a
    # band sized to the measured height clips its own descenders (findings:
    # "give every drawn rect ~0.2 em of slack").
    _LINE_H = _chrome.text_h + 2 * scale
    _CONTENT_W = _chrome.width - 2 * _MARGIN
    # The claim square gets the whole content height. Its left edge is tight
    # because the plate carries its own four-module white quiet zone — 20 px of
    # it at scale 5 — so the visible gap to the panel edge IS the quiet zone.
    _QR_TOP = scale
    _QR_AVAILABLE = _chrome.content_h - 2 * scale
    _QR_LEFT = scale
    # A version-4 claim code is 33 modules and that is what the device measured,
    # but the extent is asked of `pairview.qr_layout` rather than assumed, and
    # the plate re-asks it with the encoder's real module count.
    if _qr_layout is None:
        _QR_EXTENT = 0
    else:
        _QR_EXTENT = _qr_layout(33, max(1, _QR_AVAILABLE),
                                max_scale=QR_MAX_SCALE)["extent"]
    _COLUMN_X = _QR_LEFT + _QR_EXTENT + scale * 4
    _COLUMN_W = _chrome.width - _COLUMN_X - _MARGIN


def _margin():
    return _MARGIN


def _line_h():
    return _LINE_H


def _content_w():
    return _CONTENT_W


def _qr_left():
    return _QR_LEFT


def _qr_band():
    """(top, available) for the claim square. Builds a tuple, so it is for
    harnesses and tests rather than for a frame; the draw path reads the
    globals."""
    return _QR_TOP, _QR_AVAILABLE


def _column_x():
    return _COLUMN_X


def _column_w():
    return _COLUMN_W


# -- wrapping -----------------------------------------------------------------


def _measure(text):
    """Panel width of `text` in the chrome face. `screen.font` must be set."""
    return screen.measure_text(text, font_size=_chrome.font_size)[0]


def _break_at(word, start, end):
    """A nicer place than `end` to cut `word[start:end]`, or `start`.

    Looks back a bounded distance for a URL-ish separator and cuts AFTER it, so
    a claim URL breaks at a slash rather than in the middle of a hostname. The
    bound is what stops a lone separator near the start of a long token from
    producing a two-character line.
    """
    floor = end - BREAK_LOOKBACK
    if floor <= start:
        floor = start + 1
    index = end - 1
    while index >= floor:
        if word[index] in BREAK_AFTER:
            return index + 1
        index -= 1
    return start


def _pieces(word, budget):
    """`word` cut into chunks that each fit `budget`. Never returns empty."""
    out = []
    start = 0
    total = len(word)
    while start < total:
        end = total
        while end > start + 1 and _measure(word[start:end]) > budget:
            end -= 1
        if end < total:
            cut = _break_at(word, start, end)
            if cut > start:
                end = cut
        out.append(word[start:end])
        start = end
    return out or [word]


def _wrap(text, budget, max_lines):
    """`text` as (lines, widths, truncated), every line within `budget`.

    Word-first and then character-level, because the renderer's own wrap does
    neither for an unbreakable token; see this module's docstring. `truncated`
    is True only when the copy genuinely does not fit `max_lines` bands, which
    nothing the app draws today does — `test_settings_fit` asserts that, so this
    is a guard rather than a mode.
    """
    screen.font = _chrome.font
    lines = []
    widths = []
    current = ""
    current_w = 0.0
    for word in text.split(" "):
        candidate = word if not current else current + " " + word
        width = _measure(candidate)
        if width <= budget:
            current, current_w = candidate, width
            continue
        if current:
            lines.append(current)
            widths.append(current_w)
            current, current_w = "", 0.0
        pieces = _pieces(word, budget)
        for piece in pieces[:-1]:
            lines.append(piece)
            widths.append(_measure(piece))
        current = pieces[-1]
        current_w = _measure(current)
    lines.append(current)
    widths.append(current_w)
    if len(lines) <= max_lines:
        return lines, widths, False
    # LAST RESORT, and it is ours rather than the renderer's: `image.ELLIPSES`
    # would mark this with a glyph that has no ink in this face.
    lines = lines[:max_lines]
    widths = widths[:max_lines]
    tail = lines[-1]
    while tail and _measure(tail + ELLIPSIS) > budget:
        tail = tail[:-1]
    lines[-1] = tail + ELLIPSIS
    widths[-1] = _measure(lines[-1])
    return lines, widths, True


# -- drawing ------------------------------------------------------------------


def draw(model, label_for):
    """Paint whichever screen `model` describes."""
    screen.pen = BACKGROUND
    screen.clear()
    if model["screen"] == "menu":
        _draw_menu(model, label_for)
    else:
        _draw_page(model)
    _chrome.bar(model["softkeys"])


def _draw_menu(model, label_for):
    _list.index = model["index"]
    _list.draw(len(model["rows"]), label_for, PHOSPHOR)


def _text(value, x, y, pen):
    """The one draw call in this file, and it is POINT form.

    Rect form parses `[...]` glyph markup and raises inside `update()` on a
    known renderer name with unusable parameters, which is a reset on a badge.
    Point form parses nothing.
    """
    screen.pen = pen
    screen.text(value, x, y, font_size=_chrome.font_size)


def _line_pen(text):
    # The restart instruction is the one line that is an ACTION rather than a
    # description, so it is the one line that is not white.
    return WARN if text == settings_copy.NET_LINE_REBOOT else DIM


def _draw_page(model):
    payload = model.get("qr_payload")
    manual_code = model.get("manual_code")
    screen.font = _chrome.font
    if payload is not None and manual_code and qrcode is not None \
            and _qr_layout is not None:
        _draw_claim_screen(model, payload, manual_code)
        return

    y = _draw_title(model.get("title", ""), _margin(), _content_w(), 2)
    if payload is not None:
        y = _draw_payload_text(payload, y)
    y = _draw_body(model, y)
    match_code = model.get("match_code")
    if match_code:
        _draw_match_code(match_code, y)
    countdown = model.get("countdown")
    if countdown:
        _draw_countdown(countdown)


def _draw_title(text, x, budget, max_lines):
    block = _title.ready(text, budget, max_lines)
    y = _chrome.scale
    for index in range(len(block.lines)):
        _text(block.lines[index], x, y, PHOSPHOR)
        y += _line_h()
    return y + _chrome.scale


def _draw_body(model, y):
    """The model's lines, wrapped, bounded by the bands that actually remain.

    THE BUDGET IS THE SCREEN, NOT THE LINE. Each model line can wrap, so a
    per-line cap bounds nothing: four lines that each wrap three ways is twelve
    bands. The remaining height is therefore divided up as the lines are drawn,
    and the last line that fits carries the truncation marker. Copy that runs
    under the softkey bar is the one overrun a screenshot cannot show, and it is
    what the bitmap-fallback path did with a 64-character owner hint before this
    counted.
    """
    lines = model.get("lines") or ()
    count = len(lines)
    if count > MAX_BODY_LINES:
        # Not reachable from any model this app builds (`test_settings_fit`
        # pins the maximum at four), and if it ever becomes reachable the extra
        # copy is dropped rather than drawn under the softkey bar.
        count = MAX_BODY_LINES
    budget = _content_w()
    pitch = _line_h()
    for index in range(count):
        remaining = (_chrome.content_h - y) // pitch
        if remaining < 1:
            break
        # Leave one band for each line still to come, so the LAST line — which
        # on the revoked screen is the restart instruction, the only line that
        # is an action — cannot be the one that gets squeezed out.
        allowance = remaining - (count - index - 1)
        if allowance < 1:
            allowance = 1
        block = _body[index].ready(lines[index], budget, allowance)
        for line_index in range(len(block.lines)):
            _text(block.lines[line_index], _margin(), y,
                  _line_pen(block.text))
            y += pitch
    return y


def _draw_countdown(text):
    """Top right, clear of the title's ink and clear of the softkey band.

    Right-aligned from a RETAINED width rather than measured per frame: the
    string changes once a second and the measurement changes with it, so the
    wrap block is the cache and the steady frame reads it.
    """
    block = _countdown.ready(text, _content_w(), 1)
    x = _chrome.width - _margin() - int(block.widths[0])
    _text(block.lines[0], x, _chrome.scale, PHOSPHOR)


def _draw_claim_screen(model, payload, manual_code):
    """The claim QR beside its caption, which is what buys the bigger modules.

    LORES stacked an 82 px square over a caption line and had to drop the title
    to fit. HIRES has 320x240, so the square takes the whole content HEIGHT and
    the title, countdown and typeable code go in the column beside it: a 205 px
    square at 5 physical pixels per module against LORES's 164 px at 4.
    """
    plate = _plate.ready(payload, _QR_TOP, _QR_AVAILABLE, _QR_LEFT)
    column = _COLUMN_X
    width = _COLUMN_W
    if plate.image is None:
        y = _draw_title(model.get("title", ""), _margin(), _content_w(), 2)
        _text(settings_copy.PAYLOAD_TOO_LONG, _margin(), y, WARN)
        countdown = model.get("countdown")
        if countdown:
            _draw_countdown(countdown)
        return
    screen.blit(plate.image, plate.at)
    y = _draw_title(model.get("title", ""), column, width, 3)
    countdown = model.get("countdown")
    if countdown:
        block = _countdown.ready(countdown, width, 1)
        _text(block.lines[0], column, y, PHOSPHOR)
    # Bottom-anchored, so the typeable fallback reads as the secondary route it
    # is and does not move when the title wraps to a different line count.
    prompt_y = _chrome.content_h - 2 * _line_h() - _chrome.scale
    _text(settings_copy.MANUAL_PROMPT, column, prompt_y, DIM)
    block = _caption.ready(manual_code, width, 1)
    _text(block.lines[0], column, prompt_y + _line_h(), PHOSPHOR)


def _draw_payload_text(payload, y):
    """The claim URL as text, on a unit with no encoder. NOT a fake QR.

    A rendered placeholder a phone cannot scan would be the one failure a
    bystander reads as working. The URL is 350.6 px at 17 pt against 308 px of
    content width and contains no space, so it is CHARACTER-wrapped by
    :func:`_pieces` — the renderer would have left it one 350 px line.
    """
    _text(settings_copy.NO_ENCODER, _margin(), y, DIM)
    y += _line_h()
    _text(settings_copy.NO_ENCODER_OPEN, _margin(), y, DIM)
    y += _line_h()
    block = _caption.ready(payload, _content_w(), 3)
    for index in range(len(block.lines)):
        _text(block.lines[index], _margin(), y, PHOSPHOR)
        y += _line_h()
    return y


def _draw_match_code(text, y):
    """The six-character confirm code, as big as the display face goes.

    Its entire job is being compared against a phone by eye, so it gets the
    largest clear treatment on the screen: `ui.DISPLAY_PT`'s ceiling of 48 pt,
    a 31 px cap = 5.81 mm = 49.9 arcmin at 400 mm, against the body's 17.7. The
    widest code the match alphabet can produce (`WWWWWW`) measures 249.8 px
    against the 304 px budget, so `fit_display` never has to come down from the
    ceiling — which `test_settings_fit` asserts rather than hopes.

    Centred in whatever band is left below the question, so the question is
    what the wearer reads first and the code is what they compare.
    """
    budget = _content_w() - 2 * _chrome.scale
    size, width, height = _chrome.fit_display(text, budget)
    band = _chrome.content_h - y
    top = y + (band - int(height)) // 2
    if top < y:
        top = y
    screen.pen = PHOSPHOR
    screen.text(text, (_chrome.width - int(width)) // 2, top, font_size=size)
    # Every other draw in this file uses the chrome face; leave it selected so a
    # later call cannot inherit the display face by accident.
    screen.font = _chrome.font
    return top + int(height)
