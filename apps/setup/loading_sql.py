"""The SQL editor loading screen: a still window, and one turning spinner.

Pure Python, ZERO imports, no Badgeware globals of its own.  The destination
surface, the colour constructor and the font namespace are INJECTED, which is
the only reason this file can be unit-tested without a device.

IT NEEDS NOTHING INSTALLED, and that is new.  Every loading screen before it
played a binary pack from `/system/assets/`, which meant a provisioning step, a
"badge nobody dragged the file onto yet" failure mode, a staging path in the
browser lane and a build script to keep the pack honest against its source
deck.  All of that is deleted.  This screen is primitives on the app's own
surface, so there is nothing to install, nothing to version and nothing to go
missing.

WHAT IT DRAWS.  Supabase's SQL editor mid-query: a dark window, a chrome strip,
the statement on its current-line highlight with the editor's own syntax
colours, a divider, and a results bar reading `Running...` beside a spinner.
Everything is static except the spinner, and that is not a style choice -- see
below.

WHY EVERYTHING ELSE IS STILL.  The panel can only be repainted between
statements of the app's module body, and those gaps are uneven by nature: a
cheap import returns in microseconds and an image decode blocks for hundreds of
milliseconds.  Anything that redraws a lot per frame therefore stutters
whenever the app happens to be busy.  So the window is painted ONCE and the
only thing that moves is an arc drawn in THREE PRIMITIVES -- a disc, a punched
hole and a background wedge.  Three calls fit in almost any gap.

The design and the geometry are lifted from the `PG SLEEP` skin in
`namebadge/badge/namebadge/skins.py`, which is the same picture proved on the
panel, at both resolutions, before this file existed.

NO TRIG AT RUNTIME, AND NO `import math`.  The spinner needs a point on a
circle per frame, and the frames are a fixed cycle, so the ring is a table of
1024ths computed once by the generator in this file's commit message.  Forty
steps is nine degrees each, which makes the 72-degree gap exactly eight steps
and the half-gap exactly four -- so the wedge's two edges are just the ring
entry four steps either side of the head, with no rounding anywhere.

NOTHING HERE MAY RAISE.  This draws in front of every app, before any of them
has a frame loop to catch anything, and `badgeware.launch()` turns an escaping
exception into a modal that RESETS the badge.  `shared/loading.py` owns the
guarding; this file simply must not surprise it.
"""

STEPS = 40
_RING = (
    (1024, 0),
    (1011, 160),
    (974, 316),
    (912, 465),
    (828, 602),
    (724, 724),
    (602, 828),
    (465, 912),
    (316, 974),
    (160, 1011),
    (0, 1024),
    (-160, 1011),
    (-316, 974),
    (-465, 912),
    (-602, 828),
    (-724, 724),
    (-828, 602),
    (-912, 465),
    (-974, 316),
    (-1011, 160),
    (-1024, 0),
    (-1011, -160),
    (-974, -316),
    (-912, -465),
    (-828, -602),
    (-724, -724),
    (-602, -828),
    (-465, -912),
    (-316, -974),
    (-160, -1011),
    (0, -1024),
    (160, -1011),
    (316, -974),
    (465, -912),
    (602, -828),
    (724, -724),
    (828, -602),
    (912, -465),
    (974, -316),
    (1011, -160),
)

HALF_GAP = 4       # steps either side of the head; 4 of 40 == 36 degrees
UNIT = 1024        # the ring table's fixed-point scale

# The Supabase SQL editor's own palette, as the PG SLEEP skin records it.
BG = (24, 24, 24)
INK = (216, 216, 216)
KEYWORD = (86, 156, 214)
BRACKET = (255, 213, 79)
VALUE = (181, 206, 168)

# Words the editor paints as keywords.  Deliberately short: a statement is a
# few tokens on a 160-pixel panel, and a lexer that knows all of SQL would be
# bytes spent on words that never appear in the deck.
KEYWORDS = (
    "select", "from", "where", "insert", "into", "values", "update", "set",
    "delete", "create", "drop", "alter", "table", "view", "index", "grant",
    "on", "to", "order", "by", "group", "limit", "offset", "and", "or", "not",
    "null", "is", "as", "begin", "commit", "rollback", "vacuum", "analyze",
    "explain", "refresh", "materialized", "listen", "notify", "checkpoint",
    "reindex", "with", "join", "left", "inner", "count", "avg", "sum", "now",
)


def _lift(rgb, k):
    """A colour nudged toward white, for the chrome that sits above `BG`."""
    return (min(255, rgb[0] + k), min(255, rgb[1] + k), min(255, rgb[2] + k))


def tokenize(statement):
    """`[(text, colour)]` for one statement, in the editor's colours.

    Not a SQL parser and not trying to be.  It splits on the characters that
    change colour -- brackets, quotes, digits -- and looks the bare words up in
    `KEYWORDS`.  A word it does not know stays `INK`, which is what the editor
    does with an identifier, so being wrong is invisible rather than ugly.
    """
    spans = []
    word = ""

    def flush():
        if word:
            low = word.lower()
            if low in KEYWORDS:
                spans.append((word, KEYWORD))
            elif word[0].isdigit():
                spans.append((word, VALUE))
            else:
                spans.append((word, INK))

    quote = None
    for ch in statement:
        if quote is not None:
            word += ch
            if ch == quote:
                spans.append((word, VALUE))
                word = ""
                quote = None
            continue
        if ch in "'\"":
            flush()
            word = ch
            quote = ch
            continue
        if ch in "()":
            flush()
            word = ""
            spans.append((ch, BRACKET))
            continue
        if ch == " ":
            flush()
            word = ""
            spans.append((" ", INK))
            continue
        word += ch
    flush()
    return [span for span in spans if span[0]]


def coalesce(row):
    """Adjacent spans of one colour, joined.  AFTER wrapping, never before.

    Every span costs a `text` call, and the separators are the same colour as
    the identifiers around them, so a row arrives with far more spans than it
    has colours -- frame zero drew 22 primitives where 14 would do.

    THE ORDER IS THE WHOLE POINT.  Merging in `tokenize` would be simpler and
    is wrong: the wrapper breaks lines BETWEEN spans, so a merged
    `select pg_sleep(` is a unit it can only hard-split. Fine spans to wrap
    with, coarse spans to draw with, and this is the seam between them.
    """
    merged = []
    for text, ink in row:
        if merged and merged[-1][1] == ink:
            merged[-1] = (merged[-1][0] + text, ink)
        else:
            merged.append((text, ink))
    return merged


def wrap(surface, spans, limit):
    """Break coloured spans into rows no wider than `limit` PIXELS.

    MEASURED, NOT COUNTED, and that is the whole point of this function.  The
    editor face is PROPORTIONAL: `select pg_sleep(Infinity);` is 26 characters
    and 115 pixels, while 26 of the widest glyph in the deck would be 156.  A
    character cap therefore has to assume the worst case, which wraps a line
    that would have fitted -- the previous loading screen capped at 24 columns
    and broke exactly that statement across two rows for no reason.

    A span longer than a whole row is hard split as a last resort.  No
    statement in the shipped deck reaches it; it exists so that one added later
    degrades into an ugly line rather than a line drawn off the panel.
    """
    rows = []
    row = []
    used = 0
    for text, ink in spans:
        width = surface.measure_text(text)[0]
        if used + width <= limit:
            row.append((text, ink))
            used += width
            continue
        if text == " ":
            continue                      # never start a row with a space
        if row:
            rows.append(row)
            row = []
            used = 0
        while surface.measure_text(text)[0] > limit and len(text) > 1:
            cut = len(text)
            while cut > 1 and surface.measure_text(text[:cut])[0] > limit:
                cut -= 1
            rows.append([(text[:cut], ink)])
            text = text[cut:]
        row = [(text, ink)]
        used = surface.measure_text(text)[0]
    if row:
        rows.append(row)
    return rows


def layout(w, h):
    """Every dimension derived from the surface, so one file serves both modes.

    Taken from `_pg_sleep_layout` in the skin, which was tuned against the
    panel. At 160x120 this is u=4, chrome 10, divider at 84, spinner r=7 at
    x=15; at 320x240 every number doubles, which is why there is no LORES
    variant of this screen and no scale factor authored by hand.
    """
    u = max(1, w // 40)
    top_h = max(3, h // 12)
    sep_y = h * 7 // 10
    cy = (sep_y + h) // 2
    r_out = max(3, h // 16)
    r_in = max(1, r_out - max(1, (r_out * 2 + 4) // 9))
    cx = u * 2 + r_out
    return u, top_h, sep_y, cx, cy, r_in, r_out


def _reach(r_out):
    """How far the gap wedge must extend to clear the ring, and NO further.

    The wedge is a triangle from the centre to two points 36 degrees either
    side of the head. It only covers the ring where it reaches past it, and the
    nearest part of it to the centre is the chord, at `reach * cos(36)` ==
    `reach * 0.809`. So `reach` must exceed `r_out / 0.809`, i.e. 1.236 r_out;
    4/3 is the nearest cheap integer ratio above that.

    THE UPPER BOUND MATTERS MORE THAN THE LOWER. The wedge is painted in `BG`,
    so anything it overshoots it ERASES -- the first version used `(r_out + 2)
    * 2` and quietly ate the R of `Running...` on both panels. `paint` places
    the status text from this same number for exactly that reason.
    """
    return r_out * 4 // 3 + 2


def spinner(surface, color_ctor, geometry, step):
    """The turning arc.  THREE PRIMITIVES, and that is the whole budget.

    A filled disc, a hole punched in `BG`, then a wedge of `BG` laid over the
    ring to open the gap.  The wedge's edges are the ring table four steps
    either side of the head, so the 72-degree gap is exact and no trigonometry
    runs here.

    Three calls is what lets this be the one moving thing: it is small enough
    to fit in the gap between two statements of an app's module body, which is
    the only moment anything of ours gets to run during a load.
    """
    _u, _top, _sep, cx, cy, r_in, r_out = geometry
    surface.pen = color_ctor(INK[0], INK[1], INK[2])
    surface.circle(cx, cy, r_out)
    surface.pen = color_ctor(BG[0], BG[1], BG[2])
    surface.circle(cx, cy, r_in)
    head = step % STEPS
    reach = _reach(r_out)
    ax, ay = _RING[(head - HALF_GAP) % STEPS]
    bx, by = _RING[(head + HALF_GAP) % STEPS]
    surface.triangle(
        cx, cy,
        cx + ax * reach // UNIT, cy + ay * reach // UNIT,
        cx + bx * reach // UNIT, cy + by * reach // UNIT,
    )


def paint(surface, color_ctor, font_ns, statement, status="Running..."):
    """The whole window, once.  Returns the geometry the spinner needs.

    Called with the panel already the app's, before any of the app's own
    modules are imported.  Everything here is static for the rest of the load;
    only `spinner` runs again.
    """
    w, h = surface.width, surface.height
    geometry = layout(w, h)
    u, top_h, sep_y, cx, cy, _r_in, r_out = geometry

    surface.pen = color_ctor(BG[0], BG[1], BG[2])
    surface.clear()

    # the chrome strip, and the faint scroll nub at its right end
    surface.pen = color_ctor(BG[0] * 2 // 3, BG[1] * 2 // 3, BG[2] * 2 // 3)
    surface.rectangle(0, 0, w, top_h)
    surface.pen = color_ctor(INK[0], INK[1], INK[2], 110)
    surface.rectangle(w - u, 0, max(1, u // 3), top_h * 2 // 3)

    surface.font = font_ns.winds
    line_h = max(1, surface.measure_text("pg")[1])
    scale = max(1, (h // 10) // line_h)
    row_h = line_h * scale

    # WRAPPED IN SCALE-1 UNITS because `measure_text` reports them and `text`
    # multiplies afterwards; wrapping against the scaled width would break
    # every HIRES line in the wrong place.
    limit = (w - 2 * u) // scale
    rows = wrap(surface, tokenize(statement), limit)

    # The highlight grows with the wrap, which is what a real editor does to a
    # soft-wrapped line -- the whole logical line is the current line.
    box_y = top_h + 2
    box_h = row_h * len(rows) + u
    surface.pen = color_ctor(*_lift(BG, 26))
    surface.rectangle(u // 2, box_y, w - u, box_h)
    surface.pen = color_ctor(*_lift(BG, 9))
    surface.rectangle(u // 2 + 1, box_y + 1, w - u - 2, box_h - 2)

    y = box_y + u // 2
    for row in rows:
        x = u
        for text, ink in coalesce(row):
            if text.strip():
                surface.pen = color_ctor(ink[0], ink[1], ink[2])
                surface.text(text, x, y, scale)
            x += surface.measure_text(text)[0] * scale
        y += row_h

    surface.pen = color_ctor(*_lift(BG, 36))
    surface.rectangle(0, sep_y, w, 1)

    surface.pen = color_ctor(INK[0], INK[1], INK[2])
    status_h = surface.measure_text(status)[1] * scale
    surface.text(status, cx + _reach(r_out) + u, cy - status_h // 2, scale)
    spinner(surface, color_ctor, geometry, 0)
    return geometry
