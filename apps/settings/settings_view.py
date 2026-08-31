"""Pixels for the Settings tile, at HIRES. Every decision it makes is in
``settings_model``; every word it draws is in ``settings_copy``.

THIS APP IS HIRES-ONLY. 320x240, 1:1, real vector outlines — one app, no LORES
variant, no ``variant.py``, nothing to branch on. That holds for every identity
surface: ``setup`` and ``nametag`` are HIRES-only too, and only the games and
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
   states as "measure chrome once, at construction, even when it looks free".

**THE QR MACHINERY IS GONE (2026-08-28), AND SO IS THE DISPLAY-SIZE DRAW.** This
file carried a retained ``_QrPlate``, a guarded ``import qrcode`` for the
undocumented native usermod, the two-column claim layout, the typeable-URL
fallback and ``_draw_match_code`` -- the one place the app ever asked
``Chrome.fit_display`` for its 48 pt ceiling. Every one of them existed for the
Pair screen, which the owner deleted. What that leaves is worth stating because
it is now a property of the whole file rather than a rule about most of it:
**every string this app draws is a body line at ``Chrome.font_size``, drawn at an
``(x, y)``, from a model it was handed.** ``_draw_body`` is the only text path
with any branching left in it.
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

# THE FRAME SWEEP'S OWN FOUR INKS, and they are SOLID rather than alpha on
# purpose. `ui.Chrome.position` fades its progress thumb with an alpha white,
# which is the right tool when the backdrop underneath is unknown; the sweep's
# backdrop is a `BLACK` bed this same function paints one call earlier, so the
# blend has exactly one possible answer and pre-mixing it costs the compositor
# nothing per frame. They are also RESOLVED ONCE in `build()` for the reason
# every other constant here is: `color.rgb` needs the runtime, and a per-frame
# call would put four allocations into the one path that runs every frame.
TRAIL_1 = None
TRAIL_2 = None
TRAIL_3 = None
GRATICULE = None

_chrome = None
_list = None

#: The most body lines any screen this app draws can produce. One retained wrap
#: block per slot, and a fit test asserts no model exceeds it.
#:
#: EIGHT SINCE THE DIAGNOSTICS SCREEN (2026-08-27), and that screen is the whole
#: reason: push mode, event policy, link, sessions, doorbells, flags, last error
#: and the worst frame. It was five for the revoked network screen's four
#: (status, reason, link state, restart instruction) plus one of slack.
#:
#: THE NUMBER IS BOUNDED BY GEOMETRY AND NOT BY TASTE. The content height is
#: 214 px at a 21 px pitch, a one-line title costs the first band, and the
#: diagnostics screen reserves the last one for the sweep rail -- so eight bands
#: remain for eight lines, and `test_settings_fit` prices every one of them to
#: fit a single band so none can steal a neighbour's. A ninth line would have
#: nowhere to go; a ninth `_Wrap` block would cost RAM for a band that does not
#: exist.
MAX_BODY_LINES = 8

#: Characters :func:`_pieces` prefers to break a long token after, and how far
#: back it will look for one.
#:
#: KEPT AFTER THE CLAIM URL WAS DELETED, and worth saying why rather than
#: deleting as dead. The URL was the only string in the app that NEEDED
#: character-level breaking, and a URL is what these separators are chosen for --
#: but `_pieces` is the last resort of the general wrapper, not a URL feature,
#: and this table is what keeps its cut from landing mid-word when it fires.
#: Nothing the app draws today reaches it; `test_settings_fit` proves that and
#: would fail if a future line did.
BREAK_AFTER = "/#-._:?&="
BREAK_LOOKBACK = 8

#: The truncation marker, as three ASCII periods. NOT U+2026, which measures
#: ZERO in this face — an invisible truncation marker is worse than none,
#: because it looks like the string simply ended. Nothing the app draws today
#: reaches this; `test_settings_fit` proves it and would fail if it did.
ELLIPSIS = "..."


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


# The retained copy blocks. Replaced by `build()` rather than reused across
# chromes: a rebuilt chrome can be a different canvas, and a wrap sized for the
# old one would have been measured in the wrong face.
_title = _Wrap()
_body = ()


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


def build():
    """Construct the chrome after `badge.mode` and before the first frame.

    `ui.Chrome` reads `screen.width` in its constructor, so it cannot be built
    at import time above the mode call — that is the mistake `kbgrid`'s own
    entry point documents.

    IT TOOK A `qr_layout` ARGUMENT UNTIL 2026-08-28 -- `pairview.qr_layout`,
    handed in by the app so this file never imported from `/system/lib`. The
    claim square went with the Phone row, so the argument is gone and this file
    now has no dependency on the shared library at all, direct or injected.

    THE FACE IS LOADED EXACTLY ONCE, HERE. `ui.Chrome` calls `font.load` in its
    constructor behind an `OSError` guard: the `.af` outlines live on the FAT
    `/system` partition rather than in ROM, `font.load` is UNCACHED (~66 KB read
    into a fresh ~74 KB object, and a second call returns a DIFFERENT object),
    and a badge whose `/system` was rebuilt without them must still boot. So a
    missing face degrades to a bitmap face and never to a reset, and nothing in
    a draw path ever loads a font.
    """
    global BLACK, BACKGROUND, PHOSPHOR, DIM, WARN, _chrome, _list
    global _title, _body
    global TRAIL_1, TRAIL_2, TRAIL_3, GRATICULE
    _title = _Wrap()
    _body = tuple(_Wrap() for _ in range(MAX_BODY_LINES))
    BLACK = color.rgb(1, 4, 4)
    BACKGROUND = color.rgb(5, 18, 16)
    PHOSPHOR = color.rgb(62, 207, 142)
    DIM = color.rgb(255, 255, 255, 150)
    WARN = color.rgb(255, 176, 72)
    # `PHOSPHOR` at roughly 74% / 52% / 36%, then the graticule well under all
    # three. THE SEPARATION IS THE REQUIREMENT, not the exact values: the
    # dimmest trail chip passes over a graticule tick every 250 ms, and two inks
    # a reader cannot tell apart there would turn the tick into a flicker in the
    # tail rather than a fixed mark to measure a jump against.
    TRAIL_1 = color.rgb(46, 154, 106)
    TRAIL_2 = color.rgb(32, 108, 74)
    TRAIL_3 = color.rgb(22, 74, 51)
    GRATICULE = color.rgb(13, 40, 33)
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
# of this file computed them per call -- `_qr_band` returned a fresh tuple every
# frame and `_column_x` asked `pairview.qr_layout` for a fresh DICT every frame,
# which put two allocations straight back into the draw path. Those two bands
# are deleted with the claim screen; the discipline is kept for the ones that
# remain, because none of these numbers can change without a new chrome and
# `build()` is the only thing that makes one.

_MARGIN = 0
_LINE_H = 0
_CONTENT_W = 0
_SWEEP_H = 0
_SWEEP_TOP = 0
_SWEEP_SPAN = 0
_SWEEP_TICK_W = 0
_SWEEP_SEGMENTS = 0
_SWEEP_SEG_W = ()
_SWEEP_SEG_Y = ()
_SWEEP_SEG_BACK = ()
_SWEEP_SEG_PEN = ()

#: How many graduations the track carries, and therefore what one of them is
#: WORTH IN MILLISECONDS: the comet crosses the whole track in one
#: `settings_model.SWEEP_PERIOD_MS`, so a division is `period / 6` -- **250 ms
#: at the shipped 1500 ms period.** That is the number that makes the ticks an
#: instrument rather than decoration: the latched `worst` frame says a stall
#: happened at some point since the last RESET, and the ticks say how long THIS
#: jump was, by counting the marks the head crossed without being drawn on one.
#: Six, because 1500 divides into six whole quarter-seconds and a reader can
#: hold "three ticks is about three quarters of a second" without arithmetic;
#: eight would be 187.5 ms a tick and countable by nobody.
#:
#: The count is not derived FROM the period on purpose. The view owns no
#: decisions (`settings_model` does), and the drawing stays correct at any
#: period -- only the sentence above changes, which is why it is written down.
_SWEEP_DIVISIONS = 6


def _derive():
    """Resolve every band from the chrome. Called by `build()` and nowhere else."""
    global _MARGIN, _LINE_H, _CONTENT_W
    global _SWEEP_H, _SWEEP_TOP, _SWEEP_SPAN, _SWEEP_TICK_W
    global _SWEEP_SEGMENTS, _SWEEP_SEG_W, _SWEEP_SEG_Y, _SWEEP_SEG_BACK
    global _SWEEP_SEG_PEN
    scale = _chrome.scale
    # Side margin: three logical pixels at LORES was 1.125 mm; this is that.
    _MARGIN = scale * 3
    # Body line pitch: the em box plus 0.24 em of descender air. `measure_text`
    # returns the em box, and at 17 pt the ink reaches about 2 px past it, so a
    # band sized to the measured height clips its own descenders (findings:
    # "give every drawn rect ~0.2 em of slack").
    _LINE_H = _chrome.text_h + 2 * scale
    _CONTENT_W = _chrome.width - 2 * _MARGIN
    # THE FRAME SWEEP'S TRACK, along the bottom of the content area.
    #
    # 6 LOGICAL PX TALL (12 physical at HIRES) -- 2.25 mm, and it still costs
    # the body exactly ONE band, which is the constraint that actually binds.
    # THE PROOF IS ARITHMETIC AND `test_settings_fit` RUNS IT: `_draw_body`
    # fills downward and needs one whole pitch below the eighth line's top, so
    # in the VECTOR face (the tighter of the two -- 21 px against the bitmap
    # fallback's 20) the eighth line ends at y=193 and the floor handed to
    # `_draw_body` is `_SWEEP_TOP - scale` = 198. FIVE PIXELS OF SLACK, and a
    # ninth band was never available at either height.
    #
    # It was 4 logical px until 2026-08-27. The extra two are what let the tail
    # taper 12/8/6/4 instead of 8/6/4/2, where the last chip is a hairline --
    # and a hairline that vanishes is a trail that stops reading as direction.
    #
    # THE COMET SPANS ABOUT AN EIGHTH OF THE TRACK, which is the SAME
    # legibility budget the single block held and is kept for the same reason:
    # narrower and a 1,018 ms stall (the modal stalled frame with an undrained
    # USB CDC) moves it clean past its own body and the eye reads a teleport
    # rather than a jump; wider and its edges stop being where the position is
    # read from. 42 px against the old block's 38.
    #
    # WIDTHS ARE HEIGHTS, so every chip is square and the tail reads as one
    # object decaying rather than as four bars of assorted proportion. The gap
    # is 2 logical px: below that the chips fuse into a smear at speed, above it
    # they read as separate objects rather than as one comet.
    _SWEEP_H = scale * 6
    _SWEEP_TOP = _chrome.content_h - _SWEEP_H - scale
    _SWEEP_TICK_W = scale
    gap = scale * 2
    widths = (scale * 6, scale * 4, scale * 3, scale * 2)
    backs = []
    tops = []
    back = 0
    for width in widths:
        # `back` is the distance from the comet's LEADING EDGE to this chip's
        # left edge, because the leading edge is the sharp bright boundary an
        # eye actually reads a position off -- and it is the point the
        # graduations are spaced against, so a tick crossing is exactly one
        # division of wall time and not a division minus a chip width.
        back += width
        backs.append(back)
        tops.append(_SWEEP_TOP + (_SWEEP_H - width) // 2)
        back += gap
    _SWEEP_SEG_W = widths
    _SWEEP_SEG_Y = tuple(tops)
    _SWEEP_SEG_BACK = tuple(backs)
    _SWEEP_SEG_PEN = (PHOSPHOR, TRAIL_1, TRAIL_2, TRAIL_3)
    _SWEEP_SEGMENTS = len(widths)
    _SWEEP_SPAN = backs[-1]


def _margin():
    return _MARGIN


def _line_h():
    return _LINE_H


def _content_w():
    return _CONTENT_W


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
    """Title, body, and the one screen that also carries an instrument.

    ONE SHAPE FOR EVERY PAGE SINCE 2026-08-28. This function used to open with a
    branch into the claim-QR layout and close with three more for a match code, a
    countdown and a typeable URL; all four were the Pair screen's and went with
    it. Every page is now a title over `_draw_body`, and the sweep is the one
    thing that is not copy.

    A SCREEN THAT PUBLISHES `pages` GETS THE MENU'S OWN CHROME, and it is the
    menu's on purpose rather than a new element: `ui.ListView.draw` already
    ends with exactly this pair of calls on exactly this geometry, so a wearer
    who has scrolled the root list has already been taught what the rail and
    the chevrons mean. They also draw NO COPY, which is what makes them
    affordable here -- a "1/4" chip in the body would be a ninth band on a
    screen budgeted for eight and a new string in `every_string()`'s fit
    corpus. The ordinal goes in the TITLE instead, which the model composes.
    """
    screen.font = _chrome.font
    y = _draw_title(model.get("title", ""), _margin(), _content_w(), 2)
    # BEFORE THE SWEEP BRANCH, WHICH RETURNS. Diagnostics is a paged screen and
    # it is the one that leaves through the early return, so chrome drawn after
    # that branch would appear on Network and never on Diagnostics.
    #
    # ABSENT `pages` RESOLVES TO 1 AND DRAWS NOTHING AT ALL, which is what makes
    # every unpaged screen byte-identical to what it drew before paging existed.
    # `Chrome.position` short-circuits on `total <= 1` by itself; `scroll_hints`
    # does not, so the guard has to be here rather than left to the primitives.
    pages = model.get("pages") or 1
    if pages > 1:
        _chrome.position(model.get("page") or 0, pages)
        # BOTH CHEVRONS, UNCONDITIONALLY, BECAUSE THE PAGES WRAP. `_move` takes
        # the page modulo the count, so there is no end to arrive at -- and a
        # chevron that said "no further" on a control that wraps would be a lie
        # about the button, which on the one screen built to be trusted at a
        # venue is worse than no affordance.
        _chrome.scroll_hints(True, True)
    sweep = model.get("sweep")
    if sweep is not None:
        # THE ONE SCREEN THAT RESERVES A BAND FOR SOMETHING THAT IS NOT COPY.
        # The body has to stop above the rail rather than beside it: `_draw_body`
        # fills downward until it runs out of bands, so without a floor the last
        # line would be drawn through the moving block -- and the moving block is
        # the instrument, not decoration.
        _draw_body(model, y, floor=_SWEEP_TOP - _chrome.scale)
        _draw_sweep(sweep, model.get("sweep_period"))
        return
    _draw_body(model, y)


def _draw_title(text, x, budget, max_lines):
    block = _title.ready(text, budget, max_lines)
    y = _chrome.scale
    for index in range(len(block.lines)):
        _text(block.lines[index], x, y, PHOSPHOR)
        y += _line_h()
    return y + _chrome.scale


def _draw_sweep(phase, period):
    """The constant-rate comet, and the reason the whole screen redraws.

    IT MOVES AT A CONSTANT SPEED IN WALL TIME, NOT IN FRAMES, and that is the
    entire instrument. `phase` is milliseconds accumulated by
    `settings_model.FrameHealth` from the seam's own entry-to-entry
    `ticks_diff`, so the comet's position is a function of the CLOCK: a healthy
    badge shows smooth motion, a badge at half rate shows the same speed in
    visibly coarser steps, and a stalled badge shows the comet standing still
    and then jumping about 144 px for a 700 ms gap. A number cannot do that --
    a number that has stopped and a number updating slowly look identical at a
    glance, which is how a 701 ms network stall sat under a meter reporting
    `worst=58 ms`.

    **NOTHING HERE IS EASED, SPRUNG, DAMPED OR COUNTED IN FRAMES, and no shape
    this function draws may ever be.** Every one of those makes the drawn
    position a function of something other than elapsed milliseconds, which is
    the one property the screen exists for. The comet is prettier than the
    block it replaces; it is not smoothed, and a frame that looks steppy is the
    instrument WORKING.

    THREE THINGS CHANGED ON 2026-08-27 AND EACH ONE BUYS A READING.

    * **THE TRACK IS A LOOP, not a rail with a return flight.** The old block
      travelled `_CONTENT_W - block` and then teleported the whole way back, so
      once per period the screen showed a large legitimate jump -- and a stall
      landing on it was camouflaged by the one artefact the instrument cannot
      distinguish from its own subject. Every chip is now placed modulo
      `_CONTENT_W`, so it flows off the right edge and onto the left in the
      same frame. **After this, EVERY jump is a fault.**
    * **GRADUATIONS.** `_SWEEP_DIVISIONS` marks, one per 250 ms at the shipped
      period, spaced against the leading edge. The latch says a stall happened;
      the marks say how big THIS one was, without a stopwatch and without
      trusting a number that may itself be stale.
    * **A TAIL, which is direction and only direction.** Three chips at fixed
      offsets BEHIND the head, so the whole comet is a pure function of the
      same phase -- it is not a history buffer, it cannot lag the head, and it
      has nothing to allocate. It makes travel direction readable in a single
      frame and in a photograph, which the symmetric block never was.

    ALLOCATION-FREE, DELIBERATELY, on the one draw path that runs every frame.
    Integer arithmetic and `screen.rectangle` only -- no `vec2`, no tuple, no
    string, and the segment tables are built ONCE in `_derive()` and only
    indexed here. This screen's model changes every frame by construction (the
    phase moves), so `RetainedFrame` cannot skip it, and anything allocated
    here would be allocated ~37 times a second by the instrument measuring the
    cost of allocating things.

    `while` RATHER THAN `for ... in range()` for both loops, for that same
    rule: a `range` is an object, MicroPython's optimised-range path is a
    compiler option rather than a language guarantee, and this is not a path to
    find out on. An integer counter cannot allocate under any build.

    WHAT IT COSTS: **10 `screen.rectangle` calls, 11 at the 127 phases of 1500
    where a chip straddles the seam** (bed, 5 graduations, 4 chips, plus the
    split -- only one chip can contain the seam at a time), against the 2 the
    single block cost. At the device-measured ~0.063 ms per individual call
    (4.515 ms for 72, and that probe measured *within 2% between LORES and
    HIRES* because the cost is per-call boundary overhead rather than area --
    `docs/engineering-findings.md`) the addition is **~0.57 ms**. The ceiling is
    what matters rather than the delta: Settings' app work measured 12 ms p99 on
    device, VSYNC rounds a frame up to a whole 11.43 ms quantum, and 12.6 ms is
    in the same SECOND quantum 12 ms was. **The addition cannot buy a present**,
    which is the only way an animation could corrupt its own reading.

    DO NOT "OPTIMISE" THIS WITH `image.batch`, and the measurement is why it is
    tempting: batching the same 72 calls ran 1.82x faster on device. It takes a
    LIST OF TUPLES, so it allocates twice per frame on the one path in this app
    that may not allocate at all -- and rebuilt per frame it keeps only 1.28x,
    to buy 0.3 ms inside a quantum that already has ten to spare.

    WHAT IT STILL CANNOT SEE, stated so nobody reads more into the picture than
    is there: a stall of a whole multiple of the period lands the comet where it
    started, so POSITION alone cannot show one. The latched worst frame is what
    covers that, and it is why the two halves are on the same screen.

    NO `print` HERE OR ANYWHERE UNDER IT. That rule is measured rather than
    stylistic: with no host draining the USB CDC, shipping telemetry alone
    produced 192 stalled frames in 485 s, modal 1,018 ms and worst 3,032 ms,
    against ZERO on the same desk with the cable in
    (`benchmark/results/raw/2026-08-27-usb-cdc-print-blocking/`).
    """
    if not isinstance(period, int) or period <= 0:
        period = 1
    if not isinstance(phase, int) or phase < 0:
        phase = 0
    if _CONTENT_W <= 0:
        # Unreachable on a 320 px panel, and cheap next to the alternative: the
        # modulo below would raise on a zero-width track, and a raise on a draw
        # path is `fatal_error` -> `machine.reset()`, every frame, for ever.
        return
    # Integer arithmetic in this order so the multiply happens before the
    # divide: `phase // period * _CONTENT_W` is zero for every frame but the
    # last. `tip` is the leading edge as an OFFSET into the track, never a
    # screen x, because everything below is modular and a margin inside a
    # modulo is a bug waiting for the seam.
    tip = (phase % period) * _CONTENT_W // period
    screen.pen = BLACK
    screen.rectangle(_MARGIN, _SWEEP_TOP, _CONTENT_W, _SWEEP_H)
    screen.pen = GRATICULE
    index = 1
    while index < _SWEEP_DIVISIONS:
        screen.rectangle(_MARGIN + index * _CONTENT_W // _SWEEP_DIVISIONS,
                         _SWEEP_TOP, _SWEEP_TICK_W, _SWEEP_H)
        index += 1
    index = 0
    while index < _SWEEP_SEGMENTS:
        width = _SWEEP_SEG_W[index]
        top = _SWEEP_SEG_Y[index]
        # Python's `%` is non-negative for a positive modulus in both runtimes,
        # which is the whole reason the seam needs no special case: a chip
        # whose left edge is before the start of the track simply reappears at
        # the end of it.
        start = (tip - _SWEEP_SEG_BACK[index]) % _CONTENT_W
        over = start + width - _CONTENT_W
        screen.pen = _SWEEP_SEG_PEN[index]
        if over > 0:
            screen.rectangle(_MARGIN + start, top, width - over, width)
            screen.rectangle(_MARGIN, top, over, width)
        else:
            screen.rectangle(_MARGIN + start, top, width, width)
        index += 1


def _draw_body(model, y, floor=None):
    """The model's lines, wrapped, bounded by the bands that actually remain.

    THE BUDGET IS THE SCREEN, NOT THE LINE. Each model line can wrap, so a
    per-line cap bounds nothing: four lines that each wrap three ways is twelve
    bands. The remaining height is therefore divided up as the lines are drawn,
    and the last line that fits carries the truncation marker. Copy that runs
    under the softkey bar is the one overrun a screenshot cannot show.

    **A MODEL MAY NOMINATE LINES AS ITS SUBJECT** (`accent_lines`, a tuple of
    indices), and those lines are drawn in `PHOSPHOR` instead of `DIM`.

    **AND IT MAY NOMINATE A SPAN OF CHARACTERS AS ITS CURSOR** (`highlight`, a
    `(line, start, end)` tuple), which is drawn as REVERSE VIDEO: a solid
    `PHOSPHOR` rectangle over the character cell with the glyphs redrawn in the
    panel's own `BACKGROUND` on top of it. Only the Clock screen uses either
    today, for the owner's 2026-08-28 reason -- *"it's clearly highlighted on
    hour ... so it's very obvious that if I go up or down, I'm changing the
    hour"*.

    **IT HAD TO BE INK AND A RECTANGLE, BECAUSE THIS FILE HAS NO SECOND BODY
    SIZE TO SPEND.** `_text` draws every body line at `_chrome.font_size`; since
    the claim screen's match code went, that is the ONLY size this app resolves,
    `settings/tests/settings_metrics.py` models what was measured and the
    harness RAISES on anything else, and the body's cap is 17.7 arcmin at 400 mm
    against this project's chosen 15.0 floor -- under 3 arcmin of headroom before
    the copy is below a bar the tile enforces everywhere else. A bigger
    highlighted field was never available either: it would be a third size AND it
    would move every character after it, so the two rows would stop lining up
    under a press.

    **REVERSE VIDEO RATHER THAN A CARET, A BRACKET OR AN UNDERLINE**, and each
    alternative fails for its own reason. A caret or a bracket costs CHARACTERS,
    so the layout shifts as the cursor moves -- on a screen whose two rows are
    meant to sit digit over digit. An underline is one or two pixels of ink at
    the bottom of a band that already carries descender air; the block is 21 px
    tall and 18 px wide and is the only treatment here that reads across a room.
    It is also what a BIOS does, which is what the owner asked for by name.

    THREE RUNS RATHER THAN A LINE PLUS AN OVERDRAW. The highlighted line is
    drawn as prefix / field / suffix at measured offsets instead of being drawn
    whole and then painted over, so no glyph is ever rendered twice and no
    fringe of the original can survive under the block. `MonaSans-Medium` applies
    NO kerning -- `measure_text(s)` is exactly the sum of the per-glyph advances,
    verified to 0.000 px by the ruler generator -- so three runs land exactly
    where one string would. THAT PROPERTY IS LOAD-BEARING HERE and not merely
    convenient: a kerning face would put the suffix a fraction of a pixel out on
    every frame.

    IT MEASURES ON A COPY CHANGE, WHICH IS THIS FILE'S RULE AND NOT A BREACH OF
    IT. `RetainedFrame` redraws only an unequal model, the Clock model changes
    only when a key is pressed, and no other screen publishes a `highlight` --
    so the two extra `measure_text` calls happen per PRESS. The one screen whose
    model changes every frame is Diagnostics, and it has no highlight.

    AN INDEX AND NOT A STRING MATCH, for both. `_line_pen` keys on exact copy
    constants, which cannot identify a line whose text is five integers wide, and
    a prefix sniff on a draw path would silently re-ink any future line that
    happened to match it.
    """
    lines = model.get("lines") or ()
    accent = model.get("accent_lines") or ()
    # **THE SEVERITY MECHANISM, AND IT IS AN INDEX SET FOR THE REASON THIS
    # DOCSTRING ALREADY GIVES.** `_line_pen` keys on exact copy constants, which
    # cannot identify `Clock no  ntp_rejected: b` -- a line whose text is a
    # runtime literal. Before this key a model could not mark a line as a
    # warning at all; it could only hope its copy happened to BE that constant.
    #
    # A MODEL MAY NOT PUBLISH A SEVERITY WORD OR A PER-LINE DICT. That would put
    # a second vocabulary on the draw path and would allocate per frame on the
    # one screen whose model is rebuilt every frame. A tuple of small integers
    # allocates one tuple, the same as `accent_lines`, and is usually empty.
    warn = model.get("warn_lines") or ()
    highlight = model.get("highlight")
    count = len(lines)
    if count > MAX_BODY_LINES:
        # Not reachable from any model this app builds (`test_settings_fit`
        # pins the maximum at eight), and if it ever becomes reachable the extra
        # copy is dropped rather than drawn under the softkey bar.
        count = MAX_BODY_LINES
    budget = _content_w()
    pitch = _line_h()
    # THE FLOOR IS A PARAMETER SINCE THE DIAGNOSTICS SCREEN, and it defaults to
    # the whole content height so every other caller is untouched. That screen
    # reserves the bottom strip for the frame sweep, and the reservation has to
    # be taken out of the band arithmetic rather than drawn over afterwards --
    # this loop fills downward until it runs out.
    if floor is None:
        floor = _chrome.content_h
    for index in range(count):
        remaining = (floor - y) // pitch
        if remaining < 1:
            break
        # Leave one band for each line still to come, so the LAST line — which
        # on the revoked screen is the restart instruction, the only line that
        # is an action — cannot be the one that gets squeezed out.
        allowance = remaining - (count - index - 1)
        if allowance < 1:
            allowance = 1
        block = _body[index].ready(lines[index], budget, allowance)
        # THE WHOLE LINE, INCLUDING ITS WRAPPED CONTINUATIONS. An accented line
        # that changed ink halfway down would read as two different things.
        #
        # PRECEDENCE IS ACCENT > WARN > `_line_pen`. Accent is the Clock
        # editor's subject marker and only that screen publishes it, so the two
        # can never actually collide; stating the order removes the question.
        # `_line_pen` is KEPT rather than replaced, so `NET_LINE_REBOOT` keeps
        # its WARN ink with no model change and nothing regresses.
        if index in accent:
            pen = PHOSPHOR
        elif index in warn:
            pen = WARN
        else:
            pen = _line_pen(block.text)
        if (highlight is not None and highlight[0] == index
                and len(block.lines) == 1):
            # ONE LINE ONLY, AND THAT GUARD IS NOT DEFENSIVE STYLE. The span is
            # CHARACTER offsets into the model's string; a wrapped line has been
            # cut into pieces this function no longer knows the boundaries of, so
            # a block placed from those offsets would land on the wrong glyphs.
            # `test_settings_fit` proves nothing the app draws wraps here, which
            # makes this the same kind of unreached guard as the truncation path.
            _draw_highlighted(block.lines[0], highlight[1], highlight[2], y,
                              pen)
            y += pitch
            continue
        for line_index in range(len(block.lines)):
            _text(block.lines[line_index], _margin(), y, pen)
            y += pitch
    return y


def _draw_highlighted(text, start, end, y, pen):
    """One body line with a reverse-video block over ``text[start:end]``.

    See :func:`_draw_body` for why the cursor is a rectangle rather than a
    second point size, and why the line is drawn as three runs rather than
    overdrawn.

    THE BLOCK IS FLOORED ON THE LEFT AND CEILED ON THE RIGHT, so it always
    COVERS the ink it is behind rather than leaving a half-pixel of the glyph
    outside it. `screen.rectangle` takes integers; the text runs keep their
    measured float offsets, because rounding those would accumulate across three
    calls and pull the suffix off the grid the two rows line up on.

    THE BLOCK IS A FULL LINE PITCH TALL, which is the character cell rather than
    the em box: `_LINE_H` is the em box plus the 0.24 em of descender air the
    band already reserves, so a block sized to the measured height would clip its
    own descenders exactly as a band sized that way does.

    A SPAN OUTSIDE THE STRING DRAWS THE PLAIN LINE. Unreachable from a press --
    `clock_view` composes the spans from the same pieces it composes the string
    from -- but this is a draw path, where a slice that silently produced an
    empty run would put an invisible cursor on the one screen that exists to
    repair a badge.
    """
    if not 0 <= start < end <= len(text):
        _text(text, _margin(), y, pen)
        return
    left = _margin()
    prefix = text[:start]
    field = text[start:end]
    prefix_w = _measure(prefix) if prefix else 0.0
    field_w = _measure(field)
    if prefix:
        _text(prefix, left, y, pen)
    screen.pen = PHOSPHOR
    block_x = int(left + prefix_w)
    screen.rectangle(block_x, y, int(left + prefix_w + field_w) + 1 - block_x,
                     _line_h())
    # THE PANEL'S OWN GROUND, not `BLACK`: the digits read as cut OUT of the
    # block, which is what makes it a cursor rather than a badge with two inks
    # fighting. It is the colour `draw` already cleared the screen to, so the
    # highlighted cell is the only place on the panel where the background is
    # in front of something.
    _text(field, left + prefix_w, y, BACKGROUND)
    suffix = text[end:]
    if suffix:
        _text(suffix, left + prefix_w + field_w, y, pen)
