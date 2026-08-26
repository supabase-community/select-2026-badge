"""ONE STATIC SHOT of the badge, installed as the launcher's wallpaper.

THE ONE IMPURE MODULE IN THIS APP.  It draws pixels and it writes a file, which
is why the controller reaches it through three injected callables (`bake`,
`unbake`, `recipe`) rather than an import: everything else in `badgecard/` runs
on CPython with no rasteriser, and this is the seam that keeps it that way.

WHAT IT IS DERIVED FROM, AND WHAT WAS TAKEN OUT.  This is
`identity/badge/identity/wallpaper_bake.py` with the animated film removed.
Every measured number below -- the 1.9 gamma, the 0.13/0.055 targets, the
15-not-16 scrim top, the mark margins, the integer filter scales -- is that
module's, and each one was paid for with a screenshot that caught a defect code
review had missed.  None of them is re-derived here.

WHAT IS GONE, and it is most of the file: `MOTION_FILMS`' SLOW and SMOOTH rows,
`source_moves`, `film_plan`, the per-frame measure loop, the worst-frame search,
and `_advance_deck` -- the gnarliest function in the original, which walked a
retained glyph painter to the midpoint of slice k and had a recorded defect
where leading with its own catch-up check made all eighteen decks bake twelve
byte-identical frames.  A one-frame film needs none of it: record 0 of a GPD1
stream IS a keyframe, so `advance(0)` on an unbounded painter is a complete
picture.

THE OWNER ASKED FOR EXACTLY THIS, 2026-08-17: "no animation, just that static
shot".  It is also where `identity` had already converged -- `identity_model`
records the owner rejecting the twelve-frame film as "laggy and blocky" and
ruling that the home screen is a sharp static badge while `poster` is where the
animation lives.  So the deletion is not a simplification of the product; it is
the product, with the machinery for the rejected half taken away.

    still film   1 frame, 160x120, RGBA8888   76,816 bytes
    twelve       12 frames of 80x60           230,416 bytes  -- NOT BUILT

The launcher's dependency on this app remains EXACTLY ZERO.  The whole contract
is one self-describing file at `/state/wallpaper.pgw`; the launcher imports
nothing from here and knows nothing of this schema.
"""

import os

import card_model as model
import identity_catalogue as catalogue
import identity_marks as marks
import wallpaper


# THE TWO ARTWORK MODULES ARE IMPORTED LAZILY, AND AT MOST ONE OF THEM RUNS.
# `poster.py`'s trick, for the same measured reason and one more that is
# specific to this file: `skins` is 667,219 bytes with ~120 function objects all
# executed at import, `glyphskin` is another 41,223 B, and a badge wears exactly
# ONE background.  The extra reason is that this module is imported by the SEAM,
# on the launch path, so that a wallpaper that was deleted by a host can be
# reconciled from a 16-byte read at boot -- and paying 180 KB of parse on every
# launch to answer that question would undo poster's work on the frame the
# wearer is watching.
#
# Module globals rather than locals so a test can substitute a double, which is
# what lets the bake job's whole step sequence be exercised with no rasteriser.
skins = None
glyphskin = None


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


# THE BACKDROP CACHE, and this module only ever DELETES from it.  Lazy for the
# launch-path reason above rather than for size: the seam imports this file at
# boot to reconcile a wallpaper a host deleted, and that path must not pay for a
# module it will not touch.  A module global so a test can substitute a double,
# which is the only way the eviction branch gets exercised without a filesystem.
backdrop = None


def _backdrop():
    global backdrop
    if backdrop is None:
        import backdrop as module
        backdrop = module
    return backdrop


# --------------------------------------------------------------------------
# launcher geometry, in the 160x120 pixels the film is addressed in
# --------------------------------------------------------------------------

FILM_W = 160
FILM_H = 120

# The launcher's own header: `ui.draw_header` paints an opaque band over y 0..14
# and a rule at y 14.
HEADER_H = 15

# `Apps.draw_label` puts a rounded pill at y 100..115.  y 98 gives it two rows of
# clearance.  Below this line the film is QUIETENED rather than blacked out: the
# pill is opaque but the strip either side of it is not, and a hard black band
# there reads as a letterbox.
LABEL_TOP = 98

# THE FIRST ROW THE LAUNCHER ACTUALLY SHOWS, AND IT IS 15, NOT 16.  A scrim
# starting at 16 leaves row 15 at full brightness; on `skin.stickerbomb` that
# was a one-pixel rainbow line straight across the top of the wallpaper --
# invisible in the code and impossible to miss in the screenshot.
SCRIM_TOP = HEADER_H

# A mark cell at LORES, from the 24 px sheet.
MARK_PX = 24
# WHERE A MARK CAN SURVIVE: between the opaque header and the label quiet zone,
# clamped so the whole cell fits.  Half a mark under the band is a mark the
# wearer placed and cannot see.
MARK_TOP = HEADER_H
MARK_BOTTOM = LABEL_TOP

# The poster's name row, resolved at LORES.
#
# MOVED AND CAPPED TO MATCH `shared/poster.py`, 2026-08-21. These are a SECOND,
# INDEPENDENT copy -- the film is baked here, not drawn by the poster -- so
# leaving them behind would have made the badge and its own wallpaper disagree
# about where the wearer's name goes. At 160x120 the old cap of 3 drew a short
# name 60 px tall on a 120 px film: half the picture, same defect as the panel's.
#
# MOVED AGAIN 2026-08-26, 0.12 -> 0.08, for the same reason and in the same
# breath: the film is the SAME COMPOSITION AT HALF SIZE, so a `NAME_FY` that
# tracked the poster once and stopped would put the wearer's name in one place
# on the badge and another on the badge's own home screen.  `NAME_BAND_FY` has
# no counterpart here -- this baker draws the name white and outlined, with no
# polarity sample -- so `NAME_FY` is the whole of the change.
#
# ⚠ IT DOES NOT RE-BAKE AN EXISTING FILM, and `BAKE_VERSION` was deliberately
# NOT bumped, following the 2026-08-22 precedent (`0c5382c1`) that moved these
# same two constants and left it alone.  A badge holding a film baked before
# this keeps the old name row on its launcher wallpaper until the wearer saves
# again.  Whether that is worth a bump -- which re-bakes every badge once -- is
# an owner call, not a silent one; `card_model.BAKE_VERSION`'s comment is the
# argument for, and `test_card_effect.RecipeTests` pins the number.
NAME_FY = 0.08
NAME_MARGIN = 6
NAME_MAX_SCALE = 2

# THE FILM.  One frame, full resolution, and the period is still mandatory --
# `wallpaper.encode` rejects anything under 33 ms even for a single frame.
FILM_FRAMES = 1
FILM_PERIOD_MS = wallpaper.DEFAULT_PERIOD_MS
FILM_BYTES = wallpaper.HEADER_BYTES + FILM_FRAMES * FILM_W * FILM_H * 4


# --------------------------------------------------------------------------
# free space
# --------------------------------------------------------------------------

# On top of the film itself.  `wallpaper.write` writes a `.tmp` and renames, so
# the new film has to fit BESIDE whatever is already there.  The slack is for
# the state save that follows and for LittleFS's own metadata churn: a volume
# filled to the last block cannot write `badgecard.json` either, and losing the
# badge to save the wallpaper is the wrong trade.
#
# IT IS TWO SLACKS, SPENT AT DIFFERENT MOMENTS, and splitting them is what makes
# the credit in `space_for` safe (2026-08-23, device-reported refusal).
#
# `WRITE_SLACK` has to be free AT THE PEAK, with the `.tmp` and the old film
# both on the volume.  A 76,816-byte file is 19 blocks of 4,096, LittleFS spends
# more than the payload on it (the CTZ skip-list pointers live INSIDE the data
# blocks) and creating then renaming an entry rewrites `/state`'s metadata pair,
# so a write with zero headroom is an ENOSPC even when the arithmetic says it
# fits to the byte.  Four blocks is the reserve for that churn.
WRITE_SLACK = 16384
# `STATE_SLACK` is for the `_commit(milestone=True)` a successful bake triggers
# -- `badgecard.json` PLUS its `.bak`, two copies -- and for the next app to
# write anything at all.  It is spent AFTER the rename, by which point the film
# that was replaced has already returned its blocks.
STATE_SLACK = 49152
# The total is unchanged, so a badge with no film to credit is asked for exactly
# what it was asked for before this split existed.
DISK_SLACK = WRITE_SLACK + STATE_SLACK

# `badge.disk_free()` is NOT used, deliberately: in the browser it answers 14 MB
# free for a volume the device ships at 1 MB, so a check written against it
# passes everywhere and has never been exercised.
UNKNOWN_FREE = -1


# Everything a stat of a file that may not be there can raise, on either
# runtime.  A missing file is the ORDINARY case here -- a badge that has never
# saved a home screen has no film to credit -- so nothing below may raise for
# it.
_SAFE = (OSError, AttributeError, TypeError, IndexError, ValueError)


def free_bytes(root="/"):
    """Free bytes on the writable volume, or `UNKNOWN_FREE`.  Never raises.

    Unknown means DO NOT REFUSE.  A runtime without `statvfs` is one this check
    cannot speak about, and refusing there would disable the feature rather than
    protect it; `wallpaper.write` still raises if the write genuinely runs out
    of room, and the job reports that.
    """
    try:
        stat = os.statvfs(root)
        return int(stat[0]) * int(stat[3])
    except _SAFE:
        return UNKNOWN_FREE


def file_bytes(path):
    """Size of `path`, or 0 when there is nothing there to measure."""
    try:
        return int(os.stat(path)[6])
    except _SAFE:
        return 0


def credit_for(path):
    """Bytes this bake gets back from the film it is about to replace.

    CAPPED AT `STATE_SLACK`, AND THE CAP IS THE WHOLE DESIGN.  `path` comes back
    at the RENAME, when the temp copy is already on the volume, so it cannot pay
    for that copy: what it can pay for is the part of the requirement nothing
    spends until afterwards.  Crediting it in full would let a bake start with
    no headroom at all at the write peak, and `WRITE_SLACK` says why that is not
    the same as fitting.

    WHICH ALSO MAKES THE CREDIT SAFE AGAINST A SLOW ALLOCATOR, and that is not
    theoretical: the 2026-08-23 sweep credited a file it was about to truncate,
    passed its preflight and still took `OSError: 28`, because opening a path
    for writing does not return the old blocks to the allocator in time
    (`benchmark/results/reports/2026-08-23-autonomous-sweep.md`, and
    `badgecard_probe.load_product` now removes before it checks).  Nothing here
    depends on that timing.  At the tightest passing volume the temp still fits
    inside `FILM_BYTES + WRITE_SLACK` of genuinely free space, and the state save
    that follows is `badgecard.json` plus its `.bak` -- 287 B each on device --
    which `WRITE_SLACK`'s remainder covers whether or not LittleFS has noticed
    the renamed-over film yet.

    A LEFTOVER `.tmp` IS NOT CREDITED, IT IS DELETED, for the same reason:
    `clear_temp` removes it and `statvfs` then reports the truth.
    """
    film = file_bytes(path)
    if film > STATE_SLACK:
        film = STATE_SLACK
    return film


def space_for(root="/", path=None):
    """`(ok, needed, free)`.  `ok` is False only when we KNOW it will not fit.

    `needed` is the film plus both slacks, unchanged.  `path` IS THE FILM THIS
    BAKE IS ABOUT TO REPLACE, and `credit_for` adds what overwriting it returns
    to `free`, so `free` is the figure the decision was MADE on and
    `ok == (free >= needed)` stays readable by a caller that logs both.

    WITHOUT THE CREDIT THIS REFUSED A SAVE THAT FITS, owner-reported from the
    badge on 2026-08-23, and it missed by THREE KILOBYTES while sitting on 76 KB
    of film it was about to overwrite:

        volume         1,048,576 B, 21 `/state` files, the warm 307,264 B
                       backdrop cache resident
        free            139,264 B  (`2026-08-23-autonomous-sweep.md`, the same
                                    figure the capture ENOSPC was measured at)
        asked for       142,352 B  -> `NEEDS 140K FREE`, refused, 3,088 short
        really needed    93,200 B  = 76,816 film + 16,384 WRITE_SLACK
        credited        188,416 B  -> fits, 46,064 B spare

    Same defect class as `backdrop.space_for`, fixed at `709819c0` the day
    before, and NOT the same fix: that writer REMOVES the old file before it
    writes, so it credits the whole thing.  This one RENAMES over it, so a full
    credit would be a lie about the peak.  Copying the other module's one-liner
    here would have passed every test and still broken the write.

    THE CREDIT IS OPT-IN, `path=None` credits nothing, because a caller that
    names no file has not said which one it is about to replace.
    """
    needed = FILM_BYTES + DISK_SLACK
    free = free_bytes(root)
    if free == UNKNOWN_FREE:
        return (True, needed, free)
    if path is not None:
        free += credit_for(path)
    return (free >= needed, needed, free)


# --------------------------------------------------------------------------
# the optional filter pass
# --------------------------------------------------------------------------

# ALL ZERO = the wallpaper is the artwork, with only the scrim over it. Owner
# ruling 2026-08-18: minimum processing, the picture as designed. Each is an
# INTEGER on its filter's own scale, and a float silently truncates to zero.
#
#   MUTED_SATURATION   0 .. -256, -256 being greyscale   (was -130)
#   MUTED_BLUR         radius in pixels, O(w*h)          (was 1)
#   GHOST_DUOTONE      map to ink/emerald, on or off     (was on)
#   GHOST_BLUR         radius in pixels                  (was 1)
#   VIGNETTE           corner darkening, strength/255    (was 90, unconditional)
MUTED_SATURATION = 0
MUTED_BLUR = 0
GHOST_DUOTONE = False
GHOST_BLUR = 0
VIGNETTE = 0


# --------------------------------------------------------------------------
# the legibility solve
# --------------------------------------------------------------------------

# The two bars a wallpaper has to clear over the region the launcher draws its
# icons and labels into.  p95 is what stops a BRIGHT PATCH swallowing one icon;
# the mean is what stops an evenly bright picture washing out all six.  Either
# alone passes a wallpaper the other rejects, so the solve satisfies both.
P95_TARGET = 0.13
MEAN_TARGET = 0.055

# Every eighth pixel from x = 2, so the sample is not aligned to the icon
# columns (32/80/128 are all even multiples of 8).  About 260 samples.
SAMPLE_STEP = 8
SAMPLE_X0 = 2
SAMPLE_TOP = SCRIM_TOP + 1

# THE EXPONENT THAT MAKES THE SOLVE A CLOSED FORM INSTEAD OF A BISECTION, and it
# is 1.9 rather than sRGB's 2.4 because of the `+0.055` offset in the decode.
# Swept over the ten brightest catalogue entries times three finishes: 2.4
# needed a correction 27 times in 30 (worst p95 0.1504) and 1.9 needed none
# (worst 0.1261).  1.9 is the largest value at which the verify pass is a
# VERIFICATION rather than a second guess.
GAMMA = 1.9

# Past this the wallpaper transmits 8% and the wearer has chosen a picture too
# bright for a background.  CAPPED rather than refused: a very dark badge is
# still their badge, and a refusal here is one they could not act on without
# changing the artwork they just chose.
SCRIM_MAX = 235


def solve_alpha(p95, mean, alpha=0):
    """The scrim alpha that puts both statistics under target.  Pure.

    `alpha` is the scrim ALREADY applied when the two were measured, which is
    what lets one function serve both passes.  MONOTONE BY CONSTRUCTION: a
    measurement already under target leaves the factor at 1.0, so the verify
    pass can only hold or darken.  A solve that could lighten would oscillate
    between the two bars.
    """
    keep = 1.0 - alpha / 255.0
    if keep < 0.0:
        keep = 0.0
    factor = 1.0
    if p95 > P95_TARGET and p95 > 0.0:
        factor = (P95_TARGET / p95) ** (1.0 / GAMMA)
    if mean > MEAN_TARGET and mean > 0.0:
        other = (MEAN_TARGET / mean) ** (1.0 / GAMMA)
        if other < factor:
            factor = other
    keep *= factor
    if keep > 1.0:
        keep = 1.0
    if keep < 0.0:
        keep = 0.0
    value = int((1.0 - keep) * 255.0 + 0.5)
    if value < 0:
        value = 0
    if value > SCRIM_MAX:
        value = SCRIM_MAX
    return value


def within_target(p95, mean):
    return p95 <= P95_TARGET and mean <= MEAN_TARGET


def extra_alpha(total, applied):
    """The SECOND scrim that finishes what `applied` started.  Pure.

    NOT `total - applied`, and getting that wrong is a silent under-darkening.
    Two black rectangles at a and b transmit `(1 - a/255) * (1 - b/255)`, so the
    second carries the RATIO of the transmissions rather than the difference of
    the alphas -- at a = 120 and total = 160 the difference is 40 and the right
    answer is 76.
    """
    first = 1.0 - applied / 255.0
    if first <= 0.0:
        return 0
    keep = (1.0 - total / 255.0) / first
    if keep >= 1.0:
        return 0
    if keep < 0.0:
        keep = 0.0
    return int((1.0 - keep) * 255.0 + 0.5)


def mark_origin(fx, fy):
    """Top-left of a mark's 24 px cell in film pixels, CLAMPED to the margins.

    The stored fraction is the mark's CENTRE, so the unclamped arithmetic is the
    poster's own at 160x120 and a mark that needs no clamping lands in the film
    exactly where the wearer put it.  What is added is the clamp, and the clamp
    is the whole reason this exists: the film's top fifteen rows are painted
    over by an opaque header and its bottom twenty-two are quietened under the
    app label, so a mark placed there is not subtle, it is gone.
    """
    x = int(FILM_W * fx + 0.5) - MARK_PX // 2
    y = int(FILM_H * fy + 0.5) - MARK_PX // 2
    if x < 0:
        x = 0
    if x > FILM_W - MARK_PX:
        x = FILM_W - MARK_PX
    if y < MARK_TOP:
        y = MARK_TOP
    if y > MARK_BOTTOM - MARK_PX:
        y = MARK_BOTTOM - MARK_PX
    return (x, y)


def stamp(parts):
    """`recipe_id` over pre-built parts.  NEVER 0, which means "nothing baked".

    `fnv1a16` can legitimately hash to 0 and `home["recipe"]` uses 0 for "no
    film I know about".  One badge in 65,536 would otherwise bake a film, record
    0, and read its own state back as unconfigured -- for ever, because
    re-baking produces the same 0.  Folding 0 onto 1 costs one collision that
    was already possible and removes a permanent one.
    """
    return wallpaper.recipe_id(*parts) or 1


def recipe_of(state):
    return stamp(model.recipe_parts(state))


# --------------------------------------------------------------------------
# outcomes
# --------------------------------------------------------------------------

OK = "ok"
NO_SPACE = "space"
FAILED = "failed"

# Short, because these are read in the second a toast lasts.  The space refusal
# NAMES ITS NUMBER: "not enough room" tells the wearer nothing they can act on,
# and the number is the difference between deleting one app and giving up.
NOTE_OK = "HOME SCREEN SET"
# THE SHORTFALL, NOT THE REQUIREMENT (2026-08-23).  This said
# `NEEDS %dK FREE` against `needed`, so the owner's badge -- 3,088 bytes short of
# a 142,352-byte ask, on a volume holding 307 KB of cache and the very film the
# bake was replacing -- reported `NEEDS 140K FREE`.  Every part of that was true
# and none of it was actionable: it named a total the wearer cannot compare
# against anything, when what they can act on is how much to delete.  A refusal
# now only survives an eviction of the regenerable cache, so the number is real
# space that has to come from somewhere else.
NOTE_SPACE = "FREE %dK TO SAVE"
NOTE_FAILED = "COULD NOT SAVE"

# What `step()` is doing, for the modal.  Words rather than a percentage: the
# bar already carries the proportion, and a stage name is what tells somebody
# watching that it is progressing rather than stuck.
STAGE_SPACE = "CHECKING SPACE"
STAGE_MEASURE = "MEASURING"
STAGE_SOLVE = "BALANCING"
STAGE_PAINT = "PAINTING"
STAGE_WRITE = "SAVING"
STAGE_DONE = "DONE"

# space, measure, solve, paint, write.  Five, and they are five separate frames
# so the modal moves.
STEPS = 5


class BakeJob:
    """One bake, stepped ONE UNIT PER RENDERED FRAME.

    A DECLARED MODAL STATE rather than a blocking call, and that is I4 rather
    than politeness: the whole bake is a second or two of real work, and a
    silent freeze of that length on a badge with no spinner is indistinguishable
    from a crash.  The controller draws the modal, then steps this once, then
    draws again.

    Read-only to the controller except `step()`.  `status`, `note`, `stage`,
    `progress` and `finished` are the whole surface.
    """

    def __init__(self, baker, state):
        self.baker = baker
        self.state = state
        self.badge = model.active(state)
        self.entry = self.badge["background"]
        # THERE IS NO FINISH HERE, and there is nothing left to carry one.  This
        # app has no finish row -- `identity` lets the wearer pick between vivid,
        # muted and ghost, the owner's five-row menu does not -- and the
        # catalogue's `treatment` column that stood in for the missing row was
        # deleted on 2026-08-18 once it was established that it selected nothing:
        # `_finish` below is pinned to zero and the glyph deck has a single LUT.
        # The scrim is what makes every wallpaper legible, and it is measured per
        # entry rather than proposed per entry.
        self.recipe = recipe_of(state)

        self.index = 0
        self.steps = STEPS
        self.stage = STAGE_SPACE
        self.status = OK
        self.note = ""
        self.finished = False
        self.alpha = 0
        self.p95 = 0.0
        self.mean = 0.0
        self.raw_p95 = 0.0
        self.raw_mean = 0.0
        self.tight = False
        # Did this bake have to spend the backdrop cache to fit?  Read by the
        # tests and worth having on the job: it is the difference between a save
        # that cost nothing and one that cost the next open 43 ms.
        self.evicted = False
        self._source = None
        self._buffer = None

    @property
    def progress(self):
        return self.index / float(self.steps) if self.steps else 1.0

    @property
    def ok(self):
        """Did the bake succeed?  A BOOLEAN, so the pure controller never has
        to know this module's status vocabulary.

        `card_app` may not import `card_bake` -- that is the whole point of the
        injected callables -- so a controller comparing `job.status == "ok"`
        would be a second copy of a string constant, drifting the first time one
        of them was renamed."""
        return self.finished and self.status == OK

    def step(self):
        """One unit of work.  TOTAL: any exception becomes a FAILED job.

        Swallowing here is right where it is wrong almost everywhere else in
        this repository, and the reason is the panel: this runs inside a modal
        the wearer is watching, and an escaping exception reaches
        `badgeware.fatal_error`, which flips the panel to HIRES, draws its own
        modal, BLOCKS until a keypress and then resets the badge.  A wallpaper
        that would not bake must be a sentence, not a reset.
        """
        if self.finished:
            return
        try:
            self._step()
        except Exception as error:  # noqa: BLE001 - see the docstring
            print("CARD_BAKE_FAIL step=%d error=%r" % (self.index, error))
            self._fail(FAILED, NOTE_FAILED)
            return
        # A STEP THAT FAILED IS ALREADY FINISHED, and re-checking here is what
        # stops the completion path running on top of it.  Without this, the
        # space refusal set `NEEDS 290K FREE` and then fell straight through
        # into `_done()`, which overwrote the note with `HOME SCREEN SET`: the
        # wearer saw a success message for a bake that never drew a pixel, and
        # `status` said NO_SPACE where nothing was reading it.
        if self.finished:
            return
        self.index += 1
        if self.index >= self.steps:
            self._done()

    def _fail(self, status, note):
        self.status = status
        self.note = note
        self.stage = STAGE_DONE
        self.finished = True
        self.index = self.steps
        self.baker.close_source()
        self._buffer = None

    def _done(self):
        self.stage = STAGE_DONE
        self.note = NOTE_OK
        self.finished = True
        self.baker.close_source()
        self._buffer = None

    def _step(self):
        if self.index == 0:
            self._step_space()
        elif self.index == 1:
            self._step_measure()
        elif self.index == 2:
            self._step_solve()
        elif self.index == 3:
            self._step_paint()
        else:
            self._step_write()

    def _step_space(self):
        """THE INVARIANT: A SAVE NEVER REFUSES WHEN THE FINISHED STATE WOULD FIT.

        Three things stand between the wearer and a refusal they cannot act on,
        in the order that spends least:

        1. `clear_temp` deletes wreckage from a write that died -- up to 76,816
           bytes of a file nothing reads.  REMOVE, NEVER CREDIT: the 2026-08-23
           sweep proved that a check which credits a file it is about to
           truncate can pass and still take `OSError: 28`.
        2. `space_for` credits the film being replaced (see `credit_for`).
        3. Only then, `evict_backdrop`: 307,264 bytes -- 30% of the volume -- of
           pixels that regenerate in one 43 ms live render, spent to keep a save
           the wearer asked for.  ONE COLD OPEN against a wallpaper that will not
           save is not a trade worth deliberating, and the editor re-bakes the
           cache by itself on the next open.  It is a FALLBACK, not the plan:
           the credit alone clears the owner's own volume with 46 KB spare, so
           this branch only runs on a volume that has grown past that.
        """
        self.stage = STAGE_MEASURE
        # THROUGH THE BAKER, not through the module function, so a test can
        # answer it without a full filesystem -- which is the only way the
        # refusal path gets exercised at all.  A branch that only runs on a
        # nearly-full 1 MB volume is a branch nobody has ever seen run.
        self.baker.clear_temp()
        ok, needed, free = self.baker.space_for()
        if not ok and self.baker.evict_backdrop():
            self.evicted = True
            ok, needed, free = self.baker.space_for()
        if not ok:
            # NAMED IN THE LOG TOO.  A refusal the wearer reports as four words
            # on a toast is one somebody then has to reconstruct; these are the
            # two numbers that make it arithmetic instead of guesswork.
            print("CARD_BAKE_SPACE needed=%d free=%d evicted=%d"
                  % (needed, free, 1 if self.evicted else 0))
            # LABELLED, and it leaves the previous film and the state untouched.
            short = needed - free
            self._fail(NO_SPACE, NOTE_SPACE % ((short + 1023) // 1024))

    def _step_measure(self):
        """Paint the badge once, bare, and read the two statistics off it."""
        self.stage = STAGE_SOLVE
        self._source = self.baker.open_source(self.entry)
        self.baker.paint(self._source, self.badge)
        self.raw_p95, self.raw_mean = self.baker.sample()

    def _step_solve(self):
        self.stage = STAGE_PAINT
        self.alpha = solve_alpha(self.raw_p95, self.raw_mean)

    def _step_paint(self):
        """Paint again, scrim, VERIFY, and correct if the verify came up short.

        Two paints rather than one because the scrim is a rectangle over the
        finished picture and a picture that has already been scrimmed cannot be
        measured for how much scrim it needed.  The verify is the contract: 1.9
        was chosen precisely so this pass has nothing to do.
        """
        self.stage = STAGE_WRITE
        self.baker.paint(self._source, self.badge)
        self.baker.scrim(self.alpha)
        self.p95, self.mean = self.baker.sample()
        if not within_target(self.p95, self.mean):
            self.tight = True
            total = solve_alpha(self.p95, self.mean, self.alpha)
            self.baker.scrim(extra_alpha(total, self.alpha))
            self.alpha = total
            self.p95, self.mean = self.baker.sample()
        # The launcher's own chrome, pre-darkened in AFTER the solve: both bands
        # only ever darken, so a film that met the target without them still
        # meets it with them, and measuring them would make the solve weaker for
        # exactly the region they cover.
        self.baker.bands()
        self._buffer = self.baker.capture()

    def _step_write(self):
        data = wallpaper.encode(
            [self._buffer], FILM_W, FILM_H,
            period_ms=FILM_PERIOD_MS,
            flags=wallpaper.FLAG_LEGIBLE,
            source=_source_code(self.entry),
            recipe_id=self.recipe)
        self._buffer = None
        wallpaper.write(data, self.baker.path)


def _source_code(entry_id):
    kind = catalogue.kind_of(entry_id)
    if kind == catalogue.PROCEDURAL:
        return wallpaper.SOURCE_SKIN
    if kind == catalogue.GLYPH:
        return wallpaper.SOURCE_GLYPH
    return wallpaper.SOURCE_UNKNOWN


# --------------------------------------------------------------------------
# the baker
# --------------------------------------------------------------------------

class Baker:
    """The pixels.  Owns one 160x120 work canvas and the assets a bake needs.

    Constructed once by the hardware seam with the Badgeware API injected, the
    same way the view is, so this module imports nothing from the runtime.
    """

    def __init__(self, image_api, color_api, vec2_api, rect_api, font_api,
                 pack=None, path=wallpaper.PATH, root="/",
                 sheet_path="assets/stickers-36-p8.png", cache_path=None):
        self.image = image_api
        self.color = color_api
        self.vec2 = vec2_api
        self.rect = rect_api
        self.font = font_api
        self.pack = pack
        self._pack_tried = pack is not None
        self.path = path
        self.root = root
        self.sheet_path = sheet_path
        # `None` means "whatever `backdrop` says", resolved at eviction time
        # rather than here: a default argument would import the module at
        # CONSTRUCTION, on the launch path, to name a file that is only ever
        # touched on a volume too full to save.
        self.cache_path = cache_path

        self.ink = color_api.rgb(2, 10, 9)
        self.emerald = color_api.rgb(62, 207, 142)
        self.black = color_api.rgb(0, 0, 0)
        self.white = color_api.rgb(255, 255, 255)
        # The launcher's own header colour, so the strip the bake blacks out and
        # the band drawn over it are the same near-black rather than two blacks
        # a millisecond apart.
        self.header_ink = color_api.rgb(3, 11, 10)
        self.label_ink = color_api.rgb(2, 8, 8, 110)

        # THE WORK CANVAS, allocated on the first bake rather than at
        # construction: a badge whose wearer never turns the wallpaper on should
        # not carry 76,800 bytes for it.
        self._canvas = None
        self._canvas_buffer = None
        # A second full-size surface, and only a glyph deck needs it.  The
        # painter's model is RETAINED, so it cannot share a canvas that gets
        # blurred, scrimmed and banded on top of it.
        self._deck = None
        self._sheet = None
        self._sheet_tried = False
        self._faces = {}

    # -- surfaces ------------------------------------------------------------

    def space_for(self):
        """`(ok, needed, free)` for this volume, CREDITING THE FILM IT REPLACES.

        A method rather than a bare call so the root is stated once and so a
        test can substitute it; `identity`'s Baker carries the same one for the
        same reason.  It names `self.path` for the same reason
        `backdrop.Writer._begin` names its own: the file this write is about to
        overwrite is the one thing the caller knows and `statvfs` does not.
        """
        return space_for(self.root, self.path)

    def clear_temp(self):
        """Delete a leftover `wallpaper.pgw.tmp`.  True if bytes went away.

        WRECKAGE, NOT DATA: `wallpaper.write` opens this name `"wb"` every time,
        so a temp that outlived its write is a partial film nothing will ever
        read.  Deleting it before the space check is the "remove first, then
        check" discipline the 2026-08-23 capture ENOSPC arrived at -- and it is
        safe here in a way it is not for the film, because there is nothing to
        protect.  `write` cleans up after itself since the same day; this covers
        the volume that was already carrying one.
        """
        if file_bytes(self.path + wallpaper.TMP_SUFFIX) <= 0:
            return False
        try:
            os.remove(self.path + wallpaper.TMP_SUFFIX)
            return True
        except _SAFE:
            return False

    def evict_backdrop(self):
        """Spend the backdrop cache to make room for a save.  True if it freed
        bytes.

        THE LAST RESORT AND A CHEAP ONE.  `/state/backdrop.bdr` is 307,264 bytes
        of pixels the app can rebuild -- a miss is a 43 ms live render and the
        editor writes it back on the next open -- so a volume that will not take
        a 76,816-byte film while holding it is not full, it is badly spent.
        Never raises: `backdrop.remove` is total, and an import that fails on a
        badge missing the module answers False rather than turning a refusal into
        a reset.
        """
        try:
            module = _backdrop()
            path = self.cache_path or module.PATH
            if file_bytes(path) <= 0:
                return False
            return bool(module.remove(path))
        except Exception:  # noqa: BLE001 - a failed eviction is not a failure
            return False

    def canvas(self):
        if self._canvas is None:
            self._canvas_buffer = bytearray(FILM_W * FILM_H * 4)
            self._canvas = self.image(FILM_W, FILM_H, self._canvas_buffer)
        return self._canvas

    def sheet(self):
        """The mark sheet, DOWNSCALED TO THE FILM at blit time.  None if it
        will not load.

        It was the 24 px LORES sheet until 2026-08-21, when that sheet was
        deleted with the rest of LORES -- and this baker kept asking for it, so
        every load failed, `_sheet` stayed None and every mark in a baked
        wallpaper came out as a hollow emerald square.  Nothing raised: the
        `except` here is doing exactly what it was written for, which is why the
        defect was invisible.

        THE FILM IS STILL 160x120 and the marks are still `MARK_PX`, because the
        LAUNCHER is still LORES -- only `badgecard` and `poster` went HIRES-only.
        So the 36 px sheet is opened here and each cell is blitted into a
        `MARK_PX` destination rect, which the runtime downscales (verified in the
        pinned build: a rect destination resamples, it does not clip).  A 36->24
        downscale is slightly softer than the authored 24 px art was, and it is
        a one-off bake rather than a frame budget, so the cost is quality and not
        time.
        """
        if self._sheet is None and not self._sheet_tried:
            self._sheet_tried = True
            try:
                loaded = self.image.load(self.sheet_path)
                cell = int(loaded.width) // marks.GRID_COLS
                self._sheet = loaded.spritesheet(
                    marks.GRID_COLS, int(loaded.height) // cell)
            except (OSError, ValueError, AttributeError, ZeroDivisionError):
                self._sheet = None
        return self._sheet

    def deck(self):
        if self.pack is None and not self._pack_tried:
            self._pack_tried = True
            self.pack = _glyphskin().open_pack()
        return self.pack

    # -- the source ----------------------------------------------------------

    def open_source(self, entry_id):
        """Whatever draws this background, as a `("kind", payload)` pair.

        THE DECK GETS `glyphskin.VIVID`, the byte-exact production palette, and
        it is named rather than passed in.  This took a `finish` argument that
        `BakeJob` filled from the catalogue's `treatment` column; all eighteen
        glyph entries proposed `vivid`, so the argument had one possible value
        and the poster made the same call.  The wearer-facing choice between the
        three LUTs lives in `identity`'s FINISH row, and this app has no such row.

        `("wash", None)` is the honest fallback for an id this build does not
        ship and for a glyph deck whose pack would not open -- the same answer
        the poster gives, because a badge whose assets did not install must
        still be a badge and its wallpaper must still be a wallpaper.
        """
        kind = catalogue.kind_of(entry_id)
        if kind == catalogue.PROCEDURAL:
            return ("skin", catalogue.index_of(entry_id))
        if kind == catalogue.GLYPH and self.deck() is not None:
            if self._deck is None:
                self._deck = self.image(FILM_W, FILM_H)
            self._deck.pen = self.black
            self._deck.clear()
            # `budget=0` is UNBOUNDED, which is right exactly here.  The
            # painter's budget bounds a LIVE frame; a bake is not a live frame,
            # and paying for the whole keyframe in one call is what makes this
            # a complete picture rather than a quarter-painted one.
            glyph = _glyphskin()
            artist = glyph.skin(self.pack, entry_id, self._deck,
                                self.image, self.vec2, glyph.VIVID,
                                budget=0)
            if artist is not None:
                # RECORD 0 OF A GPD1 STREAM IS A FULL KEYFRAME, so one advance
                # to time zero is the whole picture.  This is the entire
                # replacement for `identity`'s `_advance_deck`, whose job was to
                # walk a retained painter to the midpoint of film slice k.
                artist.advance(0)
                return ("glyph", artist)
        return ("wash", None)

    def close_source(self):
        self._deck = None

    # -- painting ------------------------------------------------------------

    def paint(self, source, badge):
        """The whole badge on the work canvas, untreated by the scrim.

        Artwork, then marks, then the name, then the finish -- in that order,
        because the finish is a treatment of the WHOLE wallpaper.  A mark
        composited after a blur would sit on the picture rather than in it, and
        a name left out of the duotone would be the one thing on a ghosted badge
        still wearing its own colours.
        """
        canvas = self.canvas()
        self._draw_source(canvas, source)
        self._draw_marks(canvas, badge)
        self._draw_name(canvas, badge)
        self._finish(canvas)

    def _draw_source(self, canvas, source):
        kind, payload = source
        if kind == "skin":
            # NO `animate` CALL.  A still film samples the artwork's resting
            # state, which is the frame every one of the 58 skins is authored to
            # look right in; phase 0 of an animator over a still is the animator
            # drawing its first frame on top of a picture nobody will see move.
            _skins().render(canvas, payload)
            return
        if kind == "glyph":
            canvas.blit(self._deck, self.vec2(0, 0))
            return
        self._draw_wash(canvas)

    def _draw_wash(self, canvas):
        """The no-artwork fallback: the poster's own field and scanlines.

        STILL, unlike `identity`'s, which drifted a highlight down the frame so
        a twelve-frame film of it was not twelve identical pictures.  There is
        one frame here, so there is nothing to differ.
        """
        canvas.pen = self.color.rgb(6, 20, 18)
        canvas.clear()
        canvas.pen = self.color.rgb(62, 207, 142, 22)
        for row in range(0, FILM_H, 8):
            if (row // 8) % 2 == 0:
                canvas.rectangle(0, row, FILM_W, 1)

    def _draw_marks(self, canvas, badge):
        sheet = self.sheet()
        for mark in badge["stickers"]:
            x, y = mark_origin(mark["x"], mark["y"])
            index = marks.index_of(mark["kind"])
            # `now_ms = 0` FREEZES AN ANIMATED MARK ON ITS FIRST CELL, which is
            # what a still film means and what the mark catalogue documents zero
            # to do.  Twenty of the 38 marks animate on the badge; on the
            # home screen they are the pose they were drawn in.
            cell = marks.cell(index, 0) if index >= 0 else -1
            if sheet is None or cell < 0:
                # The same hollow square the view draws for an unknown id, for
                # the same reason: a mark the wearer placed and cannot find is
                # worse than a mark drawn as a box.
                canvas.pen = self.emerald
                canvas.rectangle(x, y, MARK_PX, 1)
                canvas.rectangle(x, y + MARK_PX - 1, MARK_PX, 1)
                canvas.rectangle(x, y, 1, MARK_PX)
                canvas.rectangle(x + MARK_PX - 1, y, 1, MARK_PX)
                continue
            # A RECT DESTINATION, NOT A POINT: the sheet is 36 px and the film
            # wants MARK_PX, so this is where the downscale happens.
            canvas.blit(sheet.sprite(cell % marks.GRID_COLS,
                                     cell // marks.GRID_COLS),
                        self.rect(x, y, MARK_PX, MARK_PX))

    def _face(self, face_id):
        held = self._faces.get(face_id)
        if held is None:
            try:
                held = getattr(self.font, face_id)
            except (AttributeError, OSError):
                held = False
            self._faces[face_id] = held
        return held or None

    def _draw_name(self, canvas, badge):
        """The wearer's name, in the SKIN'S OWN FACE, outlined."""
        name = badge["name"]
        if not name:
            return
        budget = FILM_W - 2 * NAME_MARGIN
        face, scale = self._fit_name(canvas, badge["face"], name, budget)
        canvas.font = face
        width, _height = canvas.measure_text(name, font_size=0)
        self._outlined(canvas, name, (FILM_W - int(width) * scale) // 2,
                       int(FILM_H * NAME_FY), scale, self.white)

    def _fit_name(self, canvas, face_id, text, budget):
        """`(face, integer scale)` for a line that must not run off the film.

        The poster's ladder at one resolution: the skin's face, then the narrow
        chrome face, then the display face.  A pixel font cannot shrink below
        scale 1, so a name too wide for its own face has to change face --
        `badgewaremax` advances 14 px on a W and `sins` advances 7, which caps
        any twelve-character name at 84 px against a 148 px budget and makes the
        ladder terminate.

        IT SHOULD ALMOST NEVER FALL THROUGH.  `card_faces.cap_for` already
        capped the name to what the skin's own face fits across the panel, and
        the film is the same 160 logical pixels wide.  The ladder is the backstop
        for a state file written by hand or by a build with a wider cap.
        """
        ladder = []
        if face_id:
            ladder.append(self._face(face_id))
        ladder.append(self._face("sins"))
        ladder.append(self._face("badgewaremax"))
        chosen = None
        width = budget + 1
        for face in ladder:
            if face is None:
                continue
            canvas.font = face
            measured = canvas.measure_text(text, font_size=0)
            if chosen is None or int(measured[0]) <= budget:
                chosen = face
                width = int(measured[0])
            if int(measured[0]) <= budget:
                break
        if chosen is None:
            return (canvas.font, 1)
        scale = NAME_MAX_SCALE
        while scale > 1 and width * scale > budget:
            scale -= 1
        return (chosen, scale)

    # Eight offsets and then the fill: an OUTLINE, never a plate.  A box behind
    # the name would hide the artwork the wearer chose, which is the whole point
    # of having chosen it.
    _OUTLINE = ((-1, -1), (0, -1), (1, -1), (-1, 0),
                (1, 0), (-1, 1), (0, 1), (1, 1))

    def _outlined(self, canvas, message, x, y, scale, fill):
        canvas.pen = self.black
        for offset_x, offset_y in self._OUTLINE:
            canvas.text(message, x + offset_x, y + offset_y, scale)
        canvas.pen = fill
        canvas.text(message, x, y, scale)

    def _finish(self, canvas):
        """The optional filter pass over a baked wallpaper.  OFF by default.

        OWNER RULING, 2026-08-18: minimum processing, the artwork as its author
        designed it.  All five amounts are zero, so this method does nothing and
        the wallpaper is the badge's own picture with only the scrim over it.
        `identity/badge/identity/wallpaper_bake.py` has its own `_finish` and its
        own five constants, zeroed the same day.

        IT TAKES NO ARGUMENT, and that is the second half of the same story.  The
        filters were selected by the catalogue's `treatment_of` -- `MUTED if
        animated else VIVID`, a proxy for "busy artwork" -- and the 2026-08-18
        animation pass took the catalogue from 41 animated of 58 to 78 of 86, so
        the proxy returned MUTED for 91% of entries and discriminated between
        nothing: almost every badge got `saturation(-130) + blur(1)` whether it
        needed help or not, and `vignette(90)` ran unconditionally regardless of
        treatment.  With the amounts at zero the selector chose between five
        no-ops, so the column was deleted and the branch with it.  What is left
        is five switches, each guarded so a zero costs no full-canvas pass.

        THE NAMES KEEP THEIR OLD PREFIXES because they name the filter each
        amount drives, not a mode that still exists: `MUTED_*` is the
        desaturate-and-soften pair and `GHOST_*` the duotone pair.  Turning any
        of them on now treats EVERY wallpaper, which is the only thing it could
        mean once nothing sorts entries into treatments.

        The scrim is the part that does real work and it stays -- measured on the
        raw catalogue, 75 of 86 entries need one, and the solver already returns
        0 for the 11 that do not.

        Restoring any of these is a one-line change: set the amount non-zero.
        Keep them INTEGERS.  Both `saturation` and `vignette` take an int
        through the MicroPython binding, so the design prototype's
        `saturation(0.45)` and `vignette(0.30)` truncated to zero and silently
        did nothing at all -- which is the bug this file was written to record.
        `saturation` runs 0..-256 to greyscale; `vignette` darkens the corners
        by `strength/255`; `blur` is a radius in pixels and is O(w*h).
        """
        if MUTED_SATURATION:
            canvas.saturation(MUTED_SATURATION)
        if MUTED_BLUR:
            canvas.blur(MUTED_BLUR)
        if GHOST_DUOTONE:
            canvas.duotone(self.ink, self.emerald)
        if GHOST_BLUR:
            canvas.blur(GHOST_BLUR)
        if VIGNETTE:
            canvas.vignette(VIGNETTE)

    def scrim(self, alpha):
        if alpha <= 0:
            return
        canvas = self.canvas()
        canvas.pen = self.color.rgb(0, 0, 0, alpha)
        canvas.rectangle(0, SCRIM_TOP, FILM_W, FILM_H - SCRIM_TOP)

    def bands(self):
        canvas = self.canvas()
        canvas.pen = self.header_ink
        canvas.rectangle(0, 0, FILM_W, HEADER_H)
        canvas.pen = self.label_ink
        canvas.rectangle(0, LABEL_TOP, FILM_W, FILM_H - LABEL_TOP)

    # -- measurement and capture ---------------------------------------------

    def sample(self):
        """`(p95, mean)` relative luminance over the icon region.

        Sorted rather than histogrammed because 260 samples is nothing and a
        sort is exact: a histogram would need a bucket count chosen against the
        target, and the target is 0.13 on a scale where everything interesting
        is under 0.3.
        """
        canvas = self.canvas()
        values = []
        total = 0.0
        for y in range(SAMPLE_TOP, FILM_H, SAMPLE_STEP):
            for x in range(SAMPLE_X0, FILM_W, SAMPLE_STEP):
                value = canvas.get(x, y).luminance
                values.append(value)
                total += value
        values.sort()
        count = len(values)
        return (values[int(count * 0.95)], total / count)

    def capture(self):
        """The work canvas as the film's RGBA bytes.

        NO DOWNSCALE, because a still film is full resolution -- which is the
        whole reason the owner's "one static shot" is also the sharpest thing
        this format can hold.  `identity` needed a bilinear reduction here
        because three 160x120 frames fit in the 262,144-byte budget and four do
        not, so any film with motion had to be smaller than the panel.
        """
        buffer = bytearray(FILM_W * FILM_H * 4)
        frame = self.image(FILM_W, FILM_H, buffer)
        frame.blit(self.canvas(), self.vec2(0, 0))
        return buffer

    # -- what the controller asks for ----------------------------------------

    def bake(self, state):
        """A job the controller steps.  Never raises; never writes here."""
        try:
            return BakeJob(self, state)
        except Exception:  # noqa: BLE001 - a modal, not a reset
            return None

    def remove(self):
        return wallpaper.remove(self.path)

    def installed(self):
        return wallpaper.peek(self.path) is not None

    def reconcile(self, state):
        """Make `home` agree with the DISK.  Returns True if it changed.

        THE DISK IS THE TRUTH AND THE STATE IS THE CACHE, because the launcher
        reads the film without consulting this app's state at all.  A film
        deleted by a host, or a state restored from a backup written before the
        bake, would otherwise leave the two permanently disagreeing about
        whether the home screen is the wearer's badge.

        One 16-byte read, once, at boot.
        """
        head = wallpaper.peek(self.path)
        home = state["home"]
        on = head is not None
        recipe = head["recipe_id"] if head is not None else 0
        if home.get("on") == on and home.get("recipe") == recipe:
            return False
        home["on"] = on
        home["recipe"] = recipe
        return True
