"""THE SHIPPED EFFECT SET: a whole-card native filter the wearer chooses.

WHAT AN EFFECT IS, and what it deliberately is not.  It is ONE native
whole-surface filter applied to the finished card -- artwork, marks, name and
the empty badge's hint line, all of it -- at present time, on the worn view and
on `nametag`, which draws the same card.  It is NOT a skin (a skin is procedural
Python compiled into the build, ADR-002) and it is NOT part of the artwork: the
backdrop cache stores the UNFILTERED artwork and this runs after it, which is
why changing an effect invalidates nothing.

THE SET IS THE MEASURED ONE AND NOTHING ELSE.  `benchmark/results/reports/
2026-08-20-v3.0.2-filter-matrix.md` timed all 27 whole-surface operations
v3.0.2 exposes, at both resolutions, 100 samples each, on the
reference badge.  At HIRES **14 of the 27 fit inside one 11.43 ms VSYNC
quantum**, and the entries below are those 14 minus the TWO named further down,
each of which failed a check a cost matrix cannot make.  The four the owner named
are out for cause and the numbers are why, not taste:

    wave      64.629 ms at HIRES   6Q   (3.769 at LORES -- its amplitude
                                         arguments are in PIXELS and default to
                                         4 at either panel, so at HIRES it warps
                                         four times the surface with the same
                                         kernel; H/L 17.15, the worst in the
                                         matrix)
    synthwave 30.834 ms            3Q
    c64       23.203 ms            3Q
    phosphor  35.232 ms            4Q   (this is snake's filter, and it is why
                                         snake stays LORES)
    cga       38.484 ms            4Q
    blur      19.406 ms            2Q   (radius-independent, so 1 and 6 cost the
                                         same -- and both are two quanta)
    bloom     17.583 ms            2Q
    gameboy   13.899 ms            2Q
    nightvision 12.988 ms          2Q   (the near miss: 1.56 ms over)
    edgeglow  139.392 ms          13Q
    zoom      141.870 ms          13Q
    oilpaint  245.621 ms          22Q

CUT #1 OF 2, A DUPLICATE, AND IT IS A MEASUREMENT RATHER THAN A PREFERENCE.
`saturation(-256)` and `monochrome` produce **BYTE-IDENTICAL** pictures -- checked
in the pinned runtime over mixed content, 13 distinct results from 14 filters --
because full desaturation IS greyscale.  Shipping both would put two rows in the
wearer's list that do the same thing, which is a defect and not a choice, so
`monochrome` ships and `saturation` does not: it is **cheaper** (4.063 ms against
8.707), it takes no argument, and it is the honest name for what the picture is.
`setup/tests/test_card_effect.py` pins the exclusion WITH the reason, and
`playground/e2e/setup-effect.spec.ts` asserts the shipped set produces N
distinct framebuffers -- which is the assertion that found this in the first
place, on its first run.

**A "1Q" verdict is not "free".**  It means the filter alone fits one quantum;
the card still has to be composed in the same frame.  The badge screen's draw
median at HIRES is 33.778 ms (20.09 FPS, device, 2026-08-23), so an effect is a
few percent to a third of a frame on top -- which is why the row is ordered by
cost and why the cheap end is where the default lives.  ON `nametag` IT IS
CHEAPER THAN THAT: a still badge paints ONCE and then returns, so the filter is
applied exactly once per open.  A `motion` badge pays it per frame.

CUT #2 OF 2, `glitch`, AND IT IS NEAR-INERT: A ROW THAT SELECTS NOTHING.  It
shipped here until 2026-08-24 on the filter matrix's own reading of the one thing
that looked wrong about it -- it was the only row in the matrix to fail the
probe's mutation guard (`mutated: false`), which that report called a false
negative in the guard (the checksum samples an 8x8 grid 20 px apart and `glitch`
shifts narrow horizontal bands such a grid can straddle) rather than a no-op,
because 7.170 ms is where its per-pixel neighbours land.  **THAT READING DID NOT
SURVIVE A DENSER CHECK.**  `launcher/host/shuffle_cost.mjs` compares EVERY pixel
of the framebuffer against photo-ish content, over 5 amounts x 5 strengths in the
pinned runtime: **0.0% of the surface changed in 17 of the 25 cells** -- including
`glitch(4, ...)` and `glitch(1, ...)` at every strength -- and the 8 that moved
are non-monotonic (`glitch(8, 0.8)` reached 4.1%, `glitch(8, 1.0)` fell back to
0.7%).  It is deterministic, so this is not a clock.  That is not what a filter
with a coarse guard looks like, it is what a filter that mostly does nothing
looks like -- and a wearer who selects GLITCH selects nothing, which is a defect
and not a choice.  The launcher shuffle had already cut it by its own instrument;
this row is the same evidence reaching the card.  Restoring it needs a dense
per-pixel pass that MOVES, on device or on glass, not a cost figure.

NO RANDOM ENTRY, BY OWNER RULING: *"no random on the actual badge, just pick
one."*  There is no shuffle id, no `random` import, and nothing here reads a
clock.

IDS ARE THE NATIVE METHOD NAMES, which is one fewer mapping that can be wrong,
and they are FROZEN STRINGS rather than indices for the reason `card_model`'s
docstring gives about backgrounds: a position in a tuple means inserting one
entry rewrites every wearer's badge.  `LABELS` are display-only and may be
re-worded freely.

PURE, AND IT HAS TO BE.  `card_model` imports this and imports nothing else
that is not `card_faces`, so there is no Badgeware global here: `apply` takes
the surface and the `color` namespace as arguments.
"""

#: The absence of an effect, and what an unrecognised id draws as.
NONE = "none"

# (id, label, native method, HIRES median ms on the reference badge)
#
# ORDERED BY COST, cheapest first, because UP/DOWN walks this tuple and a
# browse row whose first steps are its cheapest steps is one a wearer can hold
# down without the panel getting slower under their thumb.  NONE leads.
SHIPPED = (
    (NONE,             "NONE",       None,             0.000),
    ("invert",         "INVERT",     "invert",         3.139),
    ("grid",           "GRID",       "grid",           3.283),
    ("monochrome",     "MONO",       "monochrome",     4.063),
    ("onebit",         "ONE BIT",    "onebit",         4.153),
    ("threshold",      "INK",        "threshold",      4.350),
    ("vignette",       "VIGNETTE",   "vignette",       5.435),
    ("chromatic",      "CHROMATIC",  "chromatic",      5.786),
    ("dither",         "DITHER",     "dither",         6.085),
    # `glitch(8)` sat here at 7.170 and is DELIBERATELY ABSENT: it changed 0.0%
    # of the surface in 17 of 25 amount x strength cells, so the row selected
    # nothing.  See CUT #2 in the docstring.
    ("contrast",       "CONTRAST",   "contrast",       7.672),
    # `saturation(-256)` sat here and is DELIBERATELY ABSENT: it is
    # byte-identical to `monochrome` above, which is cheaper and argument-free.
    ("noise",          "GRAIN",      "noise",          9.393),
    ("crt",            "CRT",        "crt",           10.297),
    ("palette_dither", "NAMETAG",     "palette_dither",10.322),
)

#: The quantum every cost above is judged against (v3.0.2 repin, both panels).
QUANTUM_MS = 11.43

# THE ONE THE BADGE SHIPS WEARING.  An OWNER CALL; this is the evidence under it,
# and swapping it is this one line.
#
# THE DECIDING RULE, stated first because it is what makes this a decision rather
# than a preference: the badge's one job is that a STRANGER READS THE NAME AT A
# METRE, so the default must make the name MORE legible, not merely no worse.
# Rendered 1:1 through the shipping `Nametag.worn` over four skins spanning the
# catalogue's luminance range (`setup/host/effect_sheet.mjs`, contact sheets
# per skin), exactly one candidate does that.
#
#   CONTRAST  the name goes crisp solid white, the brand green gets vivid, and on
#             the palest skin in the catalogue it is nearly a no-op -- so it is
#             never harmful.  WHAT IT COSTS, honestly: `contrast(64)` crushes
#             near-black, so a dark skin's soft background gradient flattens.
#             7.672 ms, the second-cheapest thing in the set that is visible.
#   GRAIN     RUNNER-UP, and the one to swap to if the effect should be SEEN
#             rather than flattering.  It preserves the artwork completely -- no
#             crush, no desaturation -- and reads as print grain on a pale skin.
#             Against it: 9.393 ms, and on the darkest skins the speckle in a
#             black field can read as a dirty panel rather than as an effect.
#   CRT/GRID  both rejected on the deciding rule and it is visible at 1:1: they
#             stripe and perforate the NAME.  Excellent as a wearer's choice.
#   INVERT    rejected -- it turns a dark badge white and takes the brand with it.
#   INK, ONE BIT, DITHER  rejected: on the palest skin the artwork collapses to a
#             black blob and the name partly disappears into it.
#   MONO, NAMETAG  rejected: they take the emerald out of a Supabase badge.
#
# EVERY FILTER IN THE SET IS DETERMINISTIC, which was checked rather than assumed
# because it decided the runner-up: `noise` re-applied to identical content is
# BYTE-IDENTICAL, so GRAIN is a function of position and does not shimmer between
# frames.  A shimmering default would have looked different on the editor's badge
# screen (redraws every frame) from the worn badge (paints once), and that would
# have ruled it out.
DEFAULT = "contrast"

# Arguments, by id.  Only the two that need a colour are absent from here, and
# `_args` builds those.  Values are the matrix's own, so a shipped effect costs
# what the row that measured it says it costs -- a `vignette(255)` would be a
# different filter wearing a measured number.
_ARGS = {
    "invert": (),
    "grid": (3, 64),
    "monochrome": (),
    "onebit": (),
    "vignette": (128,),
    "chromatic": (2,),
    "dither": (),
    "contrast": (64,),
    "noise": (24,),
    "crt": (3, 64),
}

# Built once per call from the injected namespace, because a `color` object
# cannot be a module constant in a file `card_model` imports.
#   threshold(level, lo, hi)      -- hard black-and-white at the midpoint
#   palette_dither(palette)       -- the matrix's four-swatch ramp
_NEEDS_COLOUR = ("threshold", "palette_dither")

IDS = tuple(row[0] for row in SHIPPED)
COUNT = len(SHIPPED)


def _row(effect_id):
    for row in SHIPPED:
        if row[0] == effect_id:
            return row
    return None


def known(effect_id):
    """Is this an id this build can draw?

    An UNKNOWN ID IS NOT AN ERROR.  `card_model`'s rule 3 keeps an unrecognised
    id on disk so a badge configured on a newer build degrades to "this build
    cannot show your new thing" rather than to "your badge is gone"; what this
    function decides is only what to DRAW, and the answer is NONE.
    """
    return _row(effect_id) is not None


def label(effect_id):
    """The menu's word for it, or NONE's for anything unrecognised."""
    row = _row(effect_id)
    return row[1] if row is not None else SHIPPED[0][1]


def index_of(effect_id):
    """Where this id sits in `SHIPPED`, or 0 for an unrecognised one.

    0 rather than -1 on purpose: this is what a browse row opens on, and an
    unknown id has no position to resume from. The wearer sees NONE selected,
    and the unknown id stays on disk until they commit something over it.
    """
    for position in range(COUNT):
        if SHIPPED[position][0] == effect_id:
            return position
    return 0


def cost_ms(effect_id):
    """The measured HIRES median for this filter alone, device figure."""
    row = _row(effect_id)
    return row[3] if row is not None else 0.0


def _args(native, color_api):
    args = _ARGS.get(native)
    if args is not None:
        return args
    if native == "threshold":
        return (128, color_api.black, color_api.white)
    if native == "palette_dither":
        return ([color_api.black, color_api.rgb(85, 85, 85),
                 color_api.rgb(170, 170, 170), color_api.white],)
    return ()


def apply(surface, effect_id, color_api):
    """Filter `surface` in place.  Returns the id actually applied.

    `NONE` back means nothing was drawn, for any of three reasons a caller
    cannot and should not tell apart: the effect IS none, the id is from a
    newer build, or this runtime does not carry the filter.

    NOT A HARD CALL, AND THIS IS THE ONE LINE THAT MATTERS MOST.  The method is
    reached through `getattr`, exactly as `snake_view` reaches `phosphor`: 27
    native filters exist on v3.0.2 and on the pinned playground runtime, but a
    view that hard-calls one would raise on any runtime that lacks it -- and an
    exception inside `update()` is a badge RESET, not a missing effect.  The
    whole call is guarded for the same reason: a filter that raises on some
    surface geometry must cost the wearer their effect and not their session.

    APPLIED ONCE PER PAINT, NEVER TWICE.  Filters compound -- two `invert`s are
    an identity and two `contrast`s are a different picture -- so the only
    correct home for this call is the end of a composition, which is why
    `Nametag.worn` owns it and no frame loop does.

    AND "ONCE PER PAINT" IS ALSO WHY THE COST IS AFFORDABLE, which is the part a
    reader tempted to move this into a draw loop needs.  Measured on device over
    180 samples per arm: the worn HIRES badge with `contrast` costs +8.246 ms of
    draw against the unfiltered control (the filter matrix predicted 7.672, so
    1.075x) for -2.25 FPS, and the frame p99 did not move at all (57.067 ->
    57.064 ms).  On `nametag` the same filter runs ONCE PER OPEN, 7.672 ms against
    a 1.1-2.0 s uncached arrival, which is the whole saving in one line.
    """
    if effect_id == NONE:
        return NONE
    row = _row(effect_id)
    if row is None:
        return NONE
    native = row[2]
    method = getattr(surface, native, None)
    if method is None:
        print("EFFECT_MISSING id=%s" % effect_id)
        return NONE
    try:
        method(*_args(native, color_api))
    except Exception as error:  # noqa: BLE001 - see the docstring
        print("EFFECT_FAIL id=%s error=%r" % (effect_id, error))
        return NONE
    return effect_id
