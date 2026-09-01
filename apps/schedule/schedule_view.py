"""Resolution-relative schedule renderer with a two-level HIRES type system.

Two things changed from the v1 renderer and both are measurements, not taste.

**Type.** v1 drew `font.sins` at scale 1 in both modes. LORES pixel-doubles it,
so the same 12 px line is 4.50 mm there and 2.25 mm at HIRES — a 7 px cap of
11.3 arcminutes at arm's length, under the repository's chosen 15 arcminute bar.
The fix is not a taller bitmap face (that spends the resolution on ink) but the
`.af` VECTOR outlines the badge already carries, at a fractional point size:
`UI_SCALE` x the 12 px LORES line, so 1.5 asks for an 18 pt face and gets an
11 px cap = 2.06 mm = 17.7 arcmin. See docs/engineering-findings.md.

**Rows.** v1 measured its own truncation glyph by glyph into a fixed-height row.
The firmware word-wraps and ellipsizes inside a bounded `rect` natively, and
`measure_text(text, rect(...))` reports the WRAPPED height, so a row is now a
variable-height block measured once into the layout cache: a title, then the
speaker lines the agenda names under it. Speakers are the reason — half of the
real ones are longer than the column, and wrapping shows them where truncation
would have eaten the job title. The real 2026 agenda made the second constraint
visible: keeping credits under the title column made every speaker repay the
permanent time gutter. Titles therefore stay at the proven 18 pt primary size,
while complete time ranges and speaker/company lines use a 15 pt metadata tier;
credits take the row width below the time/title line.
"""

from schedule_model import (
    CLOCK_TRUSTED,
    CLOCK_UNSET,
    KIND_BREAK,
    MARK_DAY_OF,
    MARK_OFFLINE,
    MARK_STALE,
    MARK_SUPERSEDED,
    MARK_SYNCED,
    PHASE_NEXT,
    PHASE_NOW,
    PHASE_PAST,
    STRIP_DONE,
    STRIP_EMPTY,
    STRIP_NEXT,
    STRIP_NOW,
    format_gap,
    format_range,
    format_time,
    subtitle_lines,
    strip_state,
)


# The LORES authoring metric this app was laid out against: `font.sins` at
# scale 1. Every size below is a multiple of it, so UI_SCALE is the one dial.
BASE_LINE_PX = 12

# 15 pt beside the 18 pt primary face at the shipping 1.5x scale. The pinned
# rasteriser measures a 10 px cap at 15 pt = 16.1 arcminutes at 400 mm, so this
# is a real secondary tier without dropping below the repository's chosen 15'
# design bar. A ratio keeps `UI_SCALE` the one build dial: 12/15/18/24 pt
# primaries resolve to 10/13/15/20 pt metadata rather than adding a second
# independently tuned setting.
META_NUM = 5
META_DEN = 6

# The only outline face on the badge with a full Latin-1 range. It is NOT on
# ROM: `font.<name>` opens /rom/fonts/<name>.ppf, while the .af outlines live on
# the FAT /system partition, so it must be addressed through `font.load` by bare
# short name and its absence must be survivable.
VECTOR_FACE = "MonaSans-Medium"

# The HIRES fallback when a unit's /system carries no outlines. NOT the
# `bacteria`/`ignore` pair the Name Badge falls back to: those are display
# faces, and on this text-dense screen `bacteria` measures 140 px for one time
# range against MonaSans@18's 87 on a 320 px canvas, which loses the column
# before it gains any height. `smart` is 16 px with a 6.4 px advance — the
# shortest face that is still taller than `sins`, measured 2026-08-15.
FALLBACK_FACE = "smart"

# Multiplier applied BETWEEN wrapped lines (the first line costs one em), which
# is how picovector's own line_height behaves.
LINE_HEIGHT = 1.25

# A pathological Phase-2 title or speaker credit gets this many wrapped lines
# and is then ellipsized. Every string in the published agenda fits inside it.
MAX_WRAP_LINES = 2

# THE DESCRIPTION GETS ONE LINE, AND THE DENSITY LEDGER IS WHY. `config.SOFTKEYS
# = False` ships because the 26 px band cost exactly one agenda block (three
# visible instead of two), on a screen whose whole job is "what is on and what is
# next".
#
# THE NUMBERS, MEASURED IN THE PINNED PICOVECTOR RUNTIME OVER EVERY REACHABLE
# SCROLL POSITION OF BOTH STAGES IN BOTH CLOCK STATES
# (`schedule/host/description_density.mjs`, which exits non-zero if they move):
# one described line is `_wrapped_height(..., 1, metadata=True)` + `pad // 2`,
# and the cap is `meta_h` rather than a primary line step, so the row grows by
# 17 px (`meta_h + pad // 2`). A SECOND wrapped line would add `meta_step`, 19
# px, taking the detail to 36 px. Against the real 13+13 agenda, the one-line
# form costs one readable block on the synced landing and two at worst; the
# 2026-08-27 sweep is `schedule/host/description_density.mjs`.
#
# Charged ONLY to rows that carry a description. The real agenda uses it for
# Atrium/location labels, so this is live
# density now rather than a future-schema allowance.
#
# It is a bound on the BLOCK, not on the data: the string is ellipsized here and
# stored in full, so a day-of override may hold a sentence and a future detail
# view could show all of it without a resync.
DESCRIPTION_WRAP_LINES = 1

# ── THE FRESHNESS MARK'S GEOMETRY ────────────────────────────────────────────
#
# OWNER RULING, 2026-08-24: the freshness text banners were too loud. What
# replaces them is "not super obvious, but easy to tell someone what it means if
# it matters" — so a glyph in the header, and no words anywhere.
#
# THE HEADER'S TOP-LEFT, AND THIS COMMENT SAID "RIGHT CORNER" UNTIL 2026-08-24.
# The right corner WAS the first draft and the captures killed it: the offline
# dash sat beside `11:50 PST` and read as a hyphen belonging to the clock. The
# mark leads the row now (`_draw_bar`), the event name follows it, and the clock
# keeps the corner it has always had. The description was wrong for a day while
# the code was right, which is why `mark_zoom.mjs` crops from x=0 and includes
# the first glyph of the event name: a mark that MOVED shows up in the evidence
# as a move rather than being cropped out of it.
#
# ONE CELL, `MARK_UNITS` chrome units on a side, so all five marks occupy the
# same box and the corner cannot shuffle as the verdict changes. The unit is
# `chrome_scale`, for the same reason the scroll chevrons use it:
# `shared/ui.py`'s 3 px marks are right at LORES because the panel doubles them,
# and at HIRES 1:1 the same three pixels read as a speck.
#
# 5 units is 10 px at HIRES = 1.88 mm on the ruler-measured panel, and 5 px at
# LORES = 1.88 mm after the panel doubles it. Deliberately at the small end: it
# has to be findable when somebody points at it and ignorable when nobody does.
MARK_UNITS = 5

# ── THE SOFTKEY BAR'S PHYSICAL GEOMETRY ──────────────────────────────────────
#
# READ THIS BEFORE THE BAR LOOKS UNDER-USED. It is `config.SOFTKEYS = False` by
# default since 2026-08-24 and the reason is the clock ruling, not a change of
# mind about labelling. §9.6's case for the bar was that B WROTE THE HARDWARE
# CLOCK while unlabelled; B is now bound to nothing, so the bar's middle slot is
# empty and the whole 26 px band exists to name A and C — two keys that move
# between stage TABS which are already drawn on screen with an active underline,
# and which the free `A/C` hint in the tab row already names. The band is kept as
# a one-line dial rather than deleted because the geometry is measured, pinned
# and cheap to re-enable if a fourth binding ever arrives.
#
# DUPLICATED FROM `shared/ui.py`, DELIBERATELY, and `docs/badge-button-rules.md`
# §9.6 names both honest options: build the real bar, or move this app onto
# `shared/ui.py`'s `Chrome`. This is the first, and the reasons for not taking
# the second are worth recording because it is the one the doc recommends:
#
#  * `Chrome` reads the badge's builtins (`screen`, `color`, `font`, `image`,
#    `rect`) off the global namespace, while this app INJECTS all five into
#    `ScheduleView`. That injection is what lets 115 existing tests drive the
#    real layout under CPython with no builtins hoisted, and `Chrome` would
#    require the `settings/tests/view_harness.install()` shape instead.
#  * `Chrome.__init__` calls `_load_vector(CHROME_FACE)` and `CHROME_FACE` is
#    `MonaSans-Medium` — the face this app already loads itself. Their memo would
#    share the object, but only if this app went through `_load_vector` too, so
#    adopting `Chrome` halfway would pay a SECOND 111 ms font load and a second
#    73,728 B (`VAL-020-CH`) on the app whose one recorded open gate is that
#    single unavoidable load.
#  * `Chrome` at HIRES also sizes its type at 17 pt against this app's 18, so
#    the bar would not be set in the same face size as the agenda above it.
#
# The consolidation is still right eventually and it is written up in the design
# record. Until then these four constants are the whole of the duplication, they
# are physical measurements rather than choices, and `SoftkeyGeometryTests` pins
# them against `shared/ui.py` so a change there fails a test here.
SOFTKEY_FX = (0.175, 0.45833, 0.79167)   # A/B/C button centres, x / screen width
SCROLL_FY = (0.27778, 0.72222)           # UP/DOWN button centres, y / height
LABEL_MAX_PX = 34                        # 12.75 mm, x scale; keeps 11 px of ink gutter
PANEL_MM = (60.0, 45.0)                  # ruler-measured panel
BAR_MM = 4.875                           # the band is a physical quantity, not a line


class ScheduleView:
    def __init__(self, screen, color, font, image, rect, schedule, scale=1.0, notice=None,
                 softkeys=False, face_state=None):
        self.screen = screen
        self.color = color
        self.font = font
        self.image = image
        self.rect = rect
        self.event = schedule["event"]
        self.stages = schedule["stages"]
        self.sessions = schedule["sessions"]
        self.stage_sessions = schedule["stage_sessions"]
        self.ui_scale = float(scale)
        self.softkeys = bool(softkeys)

        self.layout_cache = {}
        self.trusted = False
        self.clock_state = CLOCK_UNSET
        self.clock_date = None
        self.phases = ()
        # NOT A STRING ANY MORE. This was the freshness SENTENCE plus a boolean
        # saying whether to draw it in amber; it is one of `schedule_model`'s
        # five `MARK_*` values now, and the header draws a glyph for it.
        self.freshness = MARK_OFFLINE
        self.now_minutes = None
        self.current = ()
        self.next_session = None
        self.stage = 0
        # Each tab keeps its own place. Switching stages and switching back
        # should not silently rewind the day you were reading.
        self.selected = [0] * len(self.stages)
        self.scroll = [0] * len(self.stages)

        self.background = color.rgb(7, 10, 18)
        self.header = color.rgb(20, 25, 40)
        self.rule = color.rgb(46, 54, 72)
        self.text = color.rgb(238, 244, 255)
        self.muted = color.rgb(145, 157, 180)
        self.dim = color.rgb(96, 106, 128)
        # PAST IS DE-EMPHASISED, NEVER HIDDEN. A row that has ended is still the
        # answer to "what did I miss", and `docs/engineering-findings.md` is
        # explicit that this app must not hide the list. Two steps down from the
        # live pens, which at this contrast still reads as text rather than as a
        # disabled control.
        self.past_ink = color.rgb(120, 130, 152)
        self.past_muted = color.rgb(78, 87, 106)
        self.current_fill = color.rgb(18, 86, 65)
        self.now_fill = color.rgb(12, 49, 42)
        # A CURSOR IS NOT A SCHEDULE STATE. The magenta rail in the first real-
        # agenda capture was the brightest mark on the page and competed with
        # the green NOW fill/rail, even though it only meant "the row the keys
        # will move from". Neutral slate keeps it findable at the panel edge and
        # reserves hue for the stage/clock truth the wearer is scanning for.
        self.selection = color.rgb(172, 187, 214)
        self.hatch = color.rgb(30, 36, 52)
        self.notice_fill = color.rgb(58, 32, 12)
        self.notice_ink = color.rgb(255, 176, 84)
        # THE MARK'S TWO TONES, AND COLOUR IS THE REINFORCEMENT RATHER THAN THE
        # SIGNAL. Every pair of marks differs in SHAPE, because resolving green
        # against amber in a 10 px glyph on a lit panel at 400 mm is not
        # something to design around. Amber is already this app's "somebody needs
        # to know" colour (the override-rejected band), so the two marks that
        # want attention borrow it; `dim` is for the offline dash, which is the
        # normal state of every badge in an offline fleet and should be the
        # quietest thing on the screen.
        self.fresh_ink = color.rgb(145, 157, 180)
        self.fresh_warn = color.rgb(255, 176, 84)
        self.fresh_good = color.rgb(62, 207, 142)
        # OPAQUE, where `shared/ui.py`'s bar is 210/255 black. The translucent
        # one is right for the apps it was written for, whose content under the
        # band is artwork; here it is an AGENDA ROW, and a half-visible time and
        # title showing through three softkey labels reads as a rendering fault.
        # The same colour as the top bar, so the list sits between two matching
        # chrome bands instead of under a tinted overlay.
        self.bar_fill = self.header
        self.bar_edge = color.rgb(255, 255, 255, 64)
        self.chevron = color.rgb(255, 255, 255, 200)

        self._select_face(face_state)
        screen.font = self.face
        self.text_h = 0
        self.text_h = int(self._measure("Ag")[1])
        self.line_step = max(1, int(self.text_h * LINE_HEIGHT + 0.5))
        # Bitmap faces cannot express a fractional secondary size. That is a
        # safe fallback rather than a hidden second font: HIRES vector is the
        # only shipping surface, while a unit missing outlines still sees every
        # field at the primary bitmap metric instead of failing at launch.
        self.meta_size = (
            max(1, int(self.font_size * META_NUM / META_DEN + 0.5))
            if self.vector else self.font_size
        )
        self.meta_h = int(self._measure("Ag", font_size=self.meta_size)[1])
        self.meta_step = max(1, int(self.meta_h * LINE_HEIGHT + 0.5))
        self.pad = max(3, int(int(screen.width) / 64 + 0.5))
        self.gap = max(3, self.pad + self.pad // 2)
        # Descenders reach past the em box (measured: 2 px below at 18 pt), so a
        # rect sized to exactly the measured height clips them. Every drawn rect
        # gets this much slack; it is empty space, never an extra wrapped line,
        # because wrapping is decided by width alone.
        self.descent = max(2, int(self.text_h / 4 + 0.5))
        self.meta_descent = max(2, int(self.meta_h / 4 + 0.5))

        # Event/clock and NOW copy are metadata; stage names and session titles
        # remain primary. The smaller two chrome rows recover 8 px of the 240 px
        # panel without making the agenda itself smaller.
        self.bar_h = self.meta_step + self.pad // 2
        self.underline_h = max(2, int(self.ui_scale + 0.5))
        self.tab_h = self.line_step + self.pad // 2 + self.underline_h
        self.strip_h = self.meta_step + self.pad // 2
        self.block_gap = max(2, self.pad)
        # ONE OPTIONAL BAND, and it costs a row of the list only when it exists.
        # A rejected `/schedule.json` means the wearer is reading the BAKED
        # agenda, not the edit somebody made this morning; a badge that looks
        # like it took the edit is worse than either outcome. Serial is not a
        # channel a wearer has. `notice` is already sanitized by
        # `load_with_override`, and `_text` ellipsizes what will not fit.
        self.notice = notice or None
        self.notice_h = (self.meta_step + self.pad // 2) if self.notice else 0

        self._measure_softkey_bar()
        # Widest time range in the real data decides the column, so the column
        # is a fact about the schedule rather than a guess about time formats.
        # Measuring it in the metadata tier reclaims about 15 px at 1.5x while
        # retaining every start/end digit and the ASCII range separator.
        self.time_w = int(
            max([
                self._measure(format_range(session), font_size=self.meta_size)[0]
                for session in self.sessions
            ] or [0]) + 0.5
        )
        self.content_x = self.pad + self.time_w + self.gap
        # The scroll chevrons live on the right edge, so the content column
        # gives up their width rather than being drawn over. One pad each side
        # is measured, so wrapping accounts for it instead of discovering it.
        self.content_w = max(
            8, int(screen.width) - self.content_x - self.pad - self.scroll_gutter
        )
        # Speaker/company and description lines sit BELOW the time/title line,
        # so making them repay the time column bought no alignment and forced
        # the real longest credits into four wrapped lines. A two-pixel indent
        # clears the selection rail; the remainder of the row is their honest
        # width. At 15 pt this is enough for the two 47-character Supabase
        # credits that overflowed the old 18 pt / 209 px column.
        self.detail_x = self.pad + max(2, self.pad // 2)
        self.detail_w = max(
            8, int(screen.width) - self.detail_x - self.pad - self.scroll_gutter
        )
        self.tab_x, self.tab_w = self._tab_positions()
        # Every width a frame needs is measured HERE, once. Chrome is small
        # enough that re-measuring it per frame looks free, and it is exactly
        # the mistake this app's own layout cache exists to avoid.
        self.hint = "A/C"
        self.hint_w = int(self._measure(self.hint, font_size=self.meta_size)[0] + 0.5)
        # THE CLOCK CORNER SAYS ONE THING OR NOTHING, since the 2026-08-24 clock
        # ruling collapsed the three trust states into two presentations. It used
        # to have three candidates and two of them were the problem: a
        # `SUN 16 AUG` day-template for an off-day clock, and a `--:--`
        # placeholder for an unset one. A never-synced RTC naming the day IS the
        # assumption the ruling forbids, and a placeholder is an apology for not
        # knowing something the badge was never going to know. Both are silence
        # now, so the box only has to fit a trusted reading.
        #
        # THE MEASUREMENT LESSON THE DAY-TEMPLATE TAUGHT SURVIVES ITS DELETION
        # and is worth keeping in view: `SUN 00 SEP` looked like the wide case
        # and was not (MonaSans draws `AUG` wider than `SEP`), so the corner
        # ellipsized on the Sunday after the event. Anything added back here gets
        # MEASURED against every member of its set, never against a template
        # somebody picked. All-wide digits below, for the same reason: the
        # reading must not shuffle against the screen edge as the minute ticks.
        self.timezone = self.event.get("timezone") or ""
        self.clock_w = int(
            self._measure(
                # 12-hour presentation has no leading zero or suffix. ``12``
                # is the only two-digit hour and therefore the safe width
                # exemplar; the timezone remains the disambiguating header.
                "12:00 " + self.timezone if self.timezone else "12:00",
                font_size=self.meta_size,
            )[0] + 0.5
        )
        # THE FRESHNESS MARK'S CELL, AT THE HEADER'S TOP-LEFT CORNER, with the
        # event name after it. A fixed cell in a fixed corner: the mark is only
        # explainable to somebody ("the little mark in the top left") if it is
        # always in the same place, and it cannot be positioned relative to the
        # clock reading, which appears and disappears with the trust state.
        #
        # THE RIGHT CORNER WAS THE FIRST DRAFT AND THE CAPTURES KILLED IT. Beside
        # `11:50 PST` the offline DASH read as a hyphen belonging to the clock --
        # punctuation, not a mark -- and widening the gutter only made it a
        # hyphen with more space around it. On the left the mark leads the row
        # with nothing adjacent to be misread as, and it sits immediately before
        # the thing it qualifies: the mark is a statement about this AGENDA, and
        # the event name is what names the agenda. The clock keeps the right
        # corner it has always had, which is where a wearer looks for a time.
        self.mark_unit = max(1, self.chrome_scale)
        self.mark_px = MARK_UNITS * self.mark_unit
        self.mark_x = self.pad
        # THE SLOT THE FRESHNESS SENTENCE VACATED, which was itself the slot the
        # word `AGENDA` vacated. `AGENDA` named the app the wearer had just
        # opened; the event name is the one piece of chrome here that says
        # something the screen does not otherwise carry, and it comes from the
        # data rather than from a literal. It is not a time claim under any
        # clock state, so it is drawn unconditionally.
        self.title = self.event.get("name") or ""
        self.title_x = self.pad + self.mark_px + self.gap
        self.title_w = max(
            8, int(screen.width) - self.title_x - self.pad - self.clock_w - self.gap,
        )
        self._update_list_top()

    def _measure_softkey_bar(self):
        """Every softkey label and every band coordinate, once, at construction.

        THE LABELS NAME THEIR DESTINATION, not their key. `A/C` told the wearer
        which keys move the stage and not what they move to; `< MAIN` and
        `BUILD >` are the same width budget spent on the answer instead, and the
        short label is already in the schema for exactly this kind of use.
        """
        screen = self.screen
        width = int(screen.width)
        self.chrome_scale = max(1, width // 160)
        self.label_w = LABEL_MAX_PX * self.chrome_scale
        self.softkey_x = tuple(int(width * f + 0.5) for f in SOFTKEY_FX)
        self.scroll_y = tuple(int(int(screen.height) * f + 0.5) for f in SCROLL_FY)
        a, b, c = self.softkey_x
        self.zones = ((0, (a + b) // 2),
                      ((a + b) // 2 + 1, (b + c) // 2),
                      ((b + c) // 2 + 1, width - 1))
        # A physical band first, never shorter than the type it carries. Sizing
        # it from the font instead would give HIRES a 3.4 mm bar, thinner than
        # the 5 mm buttons it labels.
        self.softkey_h = (
            max(self.text_h + 1, int(BAR_MM * width / PANEL_MM[0] + 0.5))
            if self.softkeys else 0
        )
        # THE CHEVRON GUTTER IS UNCONDITIONAL, AND DECOUPLING IT FROM THE BAR IS
        # PART OF THE 2026-08-24 DENSITY CALL. It used to be `pad if softkeys
        # else 0`, so `SOFTKEYS = False` reproduced the pre-bar geometry EXACTLY
        # — including having no scroll affordance at all. That was defensible
        # while the bar was the default and the dense build was a comparison
        # shot; it is not defensible now the dense build SHIPS, because then
        # UP/DOWN would be the only live keys in the app with nothing on screen
        # naming them. The chevrons cost 3 px of the content column and no list
        # rows. The 26 px bar keeps three readable blocks at the real landing but
        # raises the whole Main day from 3.24 to 3.82 screens, so the two
        # affordances are not the same trade and must not share one switch.
        self.scroll_gutter = self.pad
        count = len(self.stages)
        rows = []
        for index in range(count):
            if count > 1:
                previous = self.stages[(index - 1) % count]["short"]
                following = self.stages[(index + 1) % count]["short"]
                # B'S SLOT IS EMPTY, and that is the honest bar. It read `TIME`
                # and opened the clock dial; the dial is deleted (2026-08-24) and
                # B is bound to nothing, so a label there would teach the wearer
                # that a dead key does something. `_draw_softkeys` already draws
                # nothing for an empty slot — the one-stage case has always
                # needed that for A and C.
                rows.append(("< " + previous, "", following + " >"))
            else:
                # One stage AND no dial: every slot is empty, so the band draws
                # its fill and nothing else. That is a real configuration rather
                # than a broken one, and it is the strongest argument for
                # `SOFTKEYS = False` being the default.
                rows.append(("", "", ""))
        self.stage_labels = tuple(rows)

    # -- construction ------------------------------------------------------

    def _select_face(self, face_state=None):
        """Pick the face and point size UI_SCALE asks for on this canvas.

        LORES is deliberately excluded from the dial. It is already
        pixel-doubled, so its 12 px line is 4.50 mm — bigger than anything
        HIRES reaches — and a pixel font takes integer scales only, so 1.5x
        cannot be expressed there at all and 2x would leave three rows on the
        screen. LORES therefore keeps exactly the layout it shipped with.
        """
        hires = int(self.screen.width) > 160
        self.font_size = 0
        self.vector = False
        if not hires:
            self.face = self.font.sins
            return
        if face_state is not None:
            # A changed snapshot constructs its view offscreen while the old
            # one remains live. Loading MonaSans again is not a cheap lookup:
            # VAL-020-CH measured every load as a distinct ~111 ms / 73,792 B
            # object. Both views have the same panel and UI scale, so sharing
            # the already-loaded immutable face avoids retaining two copies.
            self.face, self.vector, self.font_size = face_state
            if self.vector:
                # Antialias is screen state rather than face state. Reassert it
                # so this path has exactly the initial vector semantics.
                self.screen.antialias = self.image.X4
            return
        face = None
        name = VECTOR_FACE
        try:
            face = self.font.load(name)
        except OSError as err:
            print("SCHEDULE_FONT vector={} missing={}".format(name, err))
        if face is None:
            self.face = getattr(self.font, FALLBACK_FACE)
            return
        self.face = face
        self.vector = True
        self.font_size = max(1, int(BASE_LINE_PX * self.ui_scale + 0.5))
        # MANDATORY: picovector defaults antialias to OFF and outline glyphs
        # below ~16 pt shatter without it. X2 and X4 measure the same.
        self.screen.antialias = self.image.X4

    def _tab_positions(self):
        positions = []
        widths = []
        x = self.pad
        for stage in self.stages:
            width = int(self._measure(stage["name"])[0] + 0.5)
            positions.append(x)
            widths.append(width)
            x += width + self.gap
        return positions, widths

    def _measure(self, text, width=None, font_size=None):
        size = self.font_size if font_size is None else font_size
        if not text:
            if hasattr(self, "meta_size") and size == self.meta_size:
                return (0, self.meta_h)
            return (0, self.text_h if hasattr(self, "text_h") else 0)
        if width is None:
            return self.screen.measure_text(text, font_size=size)
        return self.screen.measure_text(
            text,
            self.rect(0, 0, int(width), 1 << 12),
            font_size=size,
            line_height=LINE_HEIGHT,
        )

    def _wrapped_height(self, text, width, lines=MAX_WRAP_LINES, metadata=False):
        """Measured wrapped height, capped at `lines` wrapped lines.

        The cap is an argument rather than a constant because the description
        line is allowed ONE (see DESCRIPTION_WRAP_LINES) while titles and speaker
        credits are allowed two. `metadata` selects the measured 15 pt tier for
        details while the default keeps titles at the primary metric.
        """
        size = self.meta_size if metadata else self.font_size
        text_h = self.meta_h if metadata else self.text_h
        line_step = self.meta_step if metadata else self.line_step
        height = int(self._measure(text, width, font_size=size)[1] + 0.5)
        ceiling = text_h + (lines - 1) * line_step
        return min(height, ceiling)

    def _measure_session(self, session):
        """Return one block's immutable layout entry.

        This is a separate unit because a network replacement arrives while
        the old agenda is still interactive.  Measuring one row per later
        frame keeps the complete real agenda from becoming one long callback
        pause, while startup can still run the same operation to completion
        under the loading screen.
        """

        title_h = self._wrapped_height(session["title"], self.content_w)
        speakers = []
        total = title_h
        for line in subtitle_lines(session):
            height = self._wrapped_height(line, self.detail_w, metadata=True)
            speakers.append((line, height))
            total += height + self.pad // 2
        # THE LABEL LINE, MEASURED HERE OR NOT AT ALL. An empty description
        # buys no measurement and no height, which is what makes a row
        # without one byte-identical to the build that shipped before the
        # field existed -- the fail-soft this app owes 800 badges.
        #
        # Indexed, not `.get()`, like `title`/`kind`/`speakers` beside it:
        # every view in this app is built from `normalize`, which always
        # supplies the key. A defensive default here would only hide a
        # session dict that came from somewhere it should not have.
        description = session["description"]
        description_h = 0
        if description:
            description_h = self._wrapped_height(
                description, self.detail_w, DESCRIPTION_WRAP_LINES, metadata=True)
            total += description_h + self.pad // 2
        return {
            "time": format_range(session),
            "title": session["title"],
            "title_h": title_h,
            "speakers": speakers,
            "description": description,
            "description_h": description_h,
            # A metadata time range is one line tall. `max` matters on the
            # bitmap fallback, where a tiny primary title must never let the
            # full range leak into the following block.
            "height": max(total, self.meta_h) + self.block_gap,
        }

    def begin_layout_cache(self):
        """Reset the cooperative row-measurement cursor for an offscreen view."""

        self.layout_cache = {}
        self._layout_index = 0

    def build_layout_step(self, on_session=None):
        """Measure at most one row; return True once every row is cached.

        The caller draws the existing view after each step.  Keeping this
        method bounded to one session is the frame-budget seam; a future agenda
        may move from ten Build rows to eight (or any other count) without a
        hard-coded batch size or a partial cache becoming visible.
        """

        index = getattr(self, "_layout_index", 0)
        if index >= len(self.sessions):
            return True
        session = self.sessions[index]
        if on_session:
            on_session("-- measuring %s" % session["id"][:12])
        self.layout_cache[session["id"]] = self._measure_session(session)
        self._layout_index = index + 1
        return self._layout_index >= len(self.sessions)

    def build_layout_cache(self, on_session=None):
        """Measure every block once. Never re-measure inside a frame.

        `on_session` is the loading screen's seam. This walks every published
        session, wrapping and measuring every line, which is the longest
        DIVISIBLE stretch in this app's load: it is a loop, so a frame fits
        between two iterations and the bar keeps moving through it. Naming the
        data instead of a row count keeps the scheduling invariant true when an
        operator replaces the agenda. Default None, so every other caller is
        unchanged.
        """
        self.begin_layout_cache()
        while not self.build_layout_step(on_session=on_session):
            pass
        return self.layout_cache

    # -- state -------------------------------------------------------------

    def visible(self):
        return self.stage_sessions[self.stage]

    def adopt_navigation(self, previous):
        """Preserve stage, selected session and scroll anchor by semantic ID.

        A whole-snapshot update can delete or reorder rows.  Numeric indexes
        alone would therefore move the wearer to an unrelated talk; IDs retain
        the same row when it survives, while clamped old indexes are the honest
        fallback when it does not (including a future ten-to-eight Build edit).
        """

        old_stage_by_id = {
            stage["id"]: index for index, stage in enumerate(previous.stages)
        }
        new_stage_by_id = {
            stage["id"]: index for index, stage in enumerate(self.stages)
        }
        for stage_id, new_index in new_stage_by_id.items():
            old_index = old_stage_by_id.get(stage_id)
            if old_index is None:
                continue
            old_rows = previous.stage_sessions[old_index]
            new_rows = self.stage_sessions[new_index]
            by_id = {row["id"]: index for index, row in enumerate(new_rows)}

            old_selected = previous.selected[old_index]
            selected_id = (
                old_rows[old_selected]["id"]
                if 0 <= old_selected < len(old_rows) else None
            )
            fallback = min(old_selected, max(0, len(new_rows) - 1))
            self.selected[new_index] = by_id.get(selected_id, fallback)

            old_scroll = previous.scroll[old_index]
            scroll_id = (
                old_rows[old_scroll]["id"]
                if 0 <= old_scroll < len(old_rows) else None
            )
            scroll_fallback = min(old_scroll, max(0, len(new_rows) - 1))
            self.scroll[new_index] = by_id.get(scroll_id, scroll_fallback)

        old_stage_id = (
            previous.stages[previous.stage]["id"]
            if previous.stages else None
        )
        self.stage = new_stage_by_id.get(old_stage_id, 0)
        self.ensure_visible()

    def _update_list_top(self):
        self.list_top = (
            self.bar_h + self.tab_h + self.notice_h
            + (self.strip_h if self.trusted else 0)
        )
        self.list_bottom = int(self.screen.height) - self.softkey_h
        self.list_h = max(1, self.list_bottom - self.list_top)

    def set_stage(self, index):
        count = len(self.stages)
        previous = self.stage
        self.stage = int(index) % count if count else 0
        if self.stage != previous:
            # Now/Next/phases are INDICES INTO THE VISIBLE STAGE, so switching
            # tabs invalidates them. Dropping them here means a frame drawn
            # between the switch and the next clock refresh shows no highlight
            # for one frame instead of indexing off the end of a shorter stage.
            # `phases` is in the list for the same reason and a weaker one: a
            # stale tuple cannot raise (`_phase` bounds-checks), so it would go
            # wrong QUIETLY, dimming a row on the new stage because the row at
            # that index on the old one had ended.
            self.current = ()
            self.next_session = None
            self.phases = ()
        self.ensure_visible()

    def cycle_stage(self, delta):
        self.set_stage(self.stage + int(delta))

    def set_clock(self, state, now_minutes, current, next_session, phases=(), date=None):
        """Adopt a clock reading. Indices are filtered to the visible stage.

        The caller computes them against one session list, and nothing stops
        that list from being the one that was on screen a moment ago. Filtering
        at the boundary keeps a stale reading from becoming an IndexError deep
        in a draw path — and `phases` gets the same treatment, because a tuple
        sized for the stage that was on screen a moment ago is the same defect
        wearing a different type.

        `state` is one of the three `CLOCK_*` values, not a boolean: the layout
        only cares whether NOW may be claimed, but the header has three
        different things to say and the dial affordance has two.
        """
        count = len(self.visible())
        trusted = state == CLOCK_TRUSTED
        changed = trusted != self.trusted
        self.clock_state = state
        self.trusted = trusted
        self.clock_date = date
        self.now_minutes = now_minutes
        self.current = tuple(index for index in current if 0 <= int(index) < count)
        self.next_session = (
            next_session if next_session is not None and 0 <= int(next_session) < count else None
        )
        self.phases = tuple(phases) if len(phases) == count else ()
        if changed:
            self._update_list_top()
            self.ensure_visible()

    def set_freshness(self, mark):
        """Adopt the freshness MARK -- one of `schedule_model`'s five `MARK_*`.

        IT USED TO TAKE A FORMATTED SENTENCE, and the reason that mattered was
        allocation: `UPDATED 6 MIN AGO` changes with the clock, so the string was
        built once per second here rather than on each of the ~44 frames it was
        true for. The mark has no relative reading in it at all, so the caller
        now hands over an interned constant and the concern is gone -- which is a
        real if small win of the 2026-08-24 freshness ruling.
        """
        self.freshness = mark or MARK_OFFLINE

    def select(self, index):
        """Put the cursor at an absolute index, CLAMPED.

        Clamped rather than wrapped because every caller is programmatic — the
        clock's auto-land, and the filtering that runs when a stage switch
        leaves the cursor past the end of a shorter stage. A wrap there would
        teleport a reader who pressed nothing.
        """
        sessions = self.visible()
        limit = len(sessions) - 1
        self.selected[self.stage] = max(0, min(limit if limit >= 0 else 0, int(index)))
        self.ensure_visible()

    def move(self, delta):
        """One row per press, WRAPPING at both ends: `docs/badge-button-rules.md` §B3.

        The wrap is the half this app was missing, and B3's own class detector is
        what makes it worth a change rather than a preference: press UP then DOWN
        and you must be byte-identically where you started. From row 0 with a
        clamp, UP did nothing and DOWN then moved to row 1 — so the first two
        presses a first-timer makes moved the cursor somewhere neither of them
        asked for.

        The stage tabs have always wrapped (`set_stage` is modular), so this also
        makes the two axes agree. `select` stays clamped; see it for why.
        """
        count = len(self.visible())
        if not count:
            return
        self.select((self.selected[self.stage] + int(delta)) % count)

    def _height(self, session):
        return self.layout_cache[session["id"]]["height"]

    def ensure_visible(self):
        """Scroll by whole blocks so the top row never starts mid-block.

        Blocks have different heights, so there is no rows-per-screen constant
        and nothing above the list top ever needs clipping.
        """
        sessions = self.visible()
        if not sessions:
            self.scroll[self.stage] = 0
            return
        selected = self.selected[self.stage]
        top = min(self.scroll[self.stage], selected)
        used = sum(self._height(sessions[i]) for i in range(top, selected + 1))
        # Drop blocks off the top until the selected one fits, but never past
        # it: a block taller than the window top-aligns instead of vanishing.
        while used > self.list_h and top < selected:
            used -= self._height(sessions[top])
            top += 1
        self.scroll[self.stage] = max(0, min(top, len(sessions) - 1))

    def visible_count(self):
        """How many blocks the current scroll position actually shows.

        AN EXACT MIRROR OF `draw`'s LOOP, and it was not one until 2026-08-24.
        It used to accumulate heights and stop when the total REACHED `list_h`,
        counting the block that crossed the boundary; `draw` stops when the next
        block's TOP is past `list_bottom`, and the two answers differ whenever a
        block straddles the edge. So this over-reported by one on exactly the
        screens where the count mattered.

        THAT ERROR WAS PUBLISHED. `visible_count` is what
        `schedule/host/render.mjs` and `schedule/badge/probe.py` report as
        `blocks_visible`, so the `blocks` column of the type-scale table in
        `schedule/README.md` carried it — and the 2026-08-24 table said `3/8` for
        a build whose own captured screenshot draws two rows. The table and the
        prose beside it disagreed for a day and nobody reconciled them, which is
        how a density figure becomes a lie: the number was derived from a helper
        nobody had checked against the renderer, and the screenshot was right.
        Found while re-measuring for the owner's density call, which is the one
        decision that figure exists to inform.

        `y` starts and advances exactly as `draw` does, including the `pad // 2`
        offset and `block_gap`, because "exactly" is the whole property.
        """
        sessions = self.visible()
        y = self.list_top + self.pad // 2
        count = 0
        for index in range(self.scroll[self.stage], len(sessions)):
            if y >= self.list_bottom:
                break
            # `_draw_block` returns `height - block_gap` and `draw` adds
            # `block_gap` back, so one block advances by its full cached height.
            y += self._height(sessions[index])
            count += 1
        return count

    # -- drawing -----------------------------------------------------------

    def _text(self, value, x, y, width, height, pen, metadata=False):
        size = self.meta_size if metadata else self.font_size
        descent = self.meta_descent if metadata else self.descent
        self.screen.pen = pen
        self.screen.text(
            value,
            self.rect(int(x), int(y), int(width), int(height) + descent),
            font_size=size,
            line_height=LINE_HEIGHT,
            align=(self.image.LEFT, self.image.TOP),
            overflow=self.image.ELLIPSES,
        )

    def _clock_reading(self):
        """`H:MM TZ`, or NOTHING. Two answers since 2026-08-24, and that is the
        whole clock ruling on one screen.

        The owner's words are "we either get a real time from a server or don't
        assume we know time". A trusted clock is one at or above the 2026 floor
        and inside the event window — which in practice means network-synced now,
        or an RTC still carrying a previous sync — and it may print what it says.
        EVERY OTHER STATE PRINTS NOTHING AT ALL.

        Two readings were deleted to get here, and both looked like honesty:

        * `SUN 16 AUG`, the day an off-day clock believed. It was defended as a
          diagnosis (a wearer reading it on the Friday knows the clock is two
          days out) and it is exactly the assumption the ruling forbids: nothing
          synced that RTC, so the badge does not know that it is Sunday. The
          diagnosis moved to the `SCHEDULE_CLOCK ... state=off_day` marker.
        * `--:--`, the placeholder for an unset clock. An apology for not knowing
          something this badge was never going to know on its own. Silence says
          the same thing and does not put a broken-looking glyph in the corner of
          an otherwise complete agenda.
        """
        if not self.trusted:
            return ""
        reading = format_time(self.now_minutes)
        return "{} {}".format(reading, self.timezone) if self.timezone else reading

    def _draw_bar(self):
        """The header row: the event name, the clock when there is one, the mark.

        THE LEFT SLOT HAS NOW HELD THREE THINGS and the third is the point. It
        read `AGENDA` (the name of the app the wearer had just opened), then the
        freshness SENTENCE, and the 2026-08-24 ruling took the sentence away
        again. The event name is what went back in: it is real information, it
        comes from the data rather than from a literal, and it cannot be a time
        claim under any clock state — where `AGENDA` was redundant and a date
        would have been a claim.
        """
        screen = self.screen
        screen.pen = self.header
        screen.rectangle(0, 0, int(screen.width), self.bar_h)
        # THE MARK LEADS THE ROW, then the event name it qualifies, then the
        # clock in the corner it has always had. Every one of the three has a
        # position that does not depend on the other two, because the clock
        # vanishes on an untrusted badge and a mark that moved with it would not
        # survive being described to somebody across a room.
        self._draw_fresh_mark(self.mark_x, self.bar_h // 2)
        text_y = max(0, (self.bar_h - self.meta_h) // 2)
        if self.title:
            self._text(
                self.title, self.title_x, text_y, self.title_w, self.meta_h,
                self.fresh_ink, metadata=True,
            )
        reading = self._clock_reading()
        if reading:
            self._text(
                reading,
                int(screen.width) - self.pad - self.clock_w,
                text_y,
                self.clock_w + 1,
                self.meta_h,
                self.muted,
                metadata=True,
            )

    def _draw_fresh_mark(self, x, mid_y):
        """Five glyphs, one cell, no words. `schedule/README.md` has the table.

        THE OWNER'S BRIEF, 2026-08-24: "not super obvious, but easy to tell
        someone what it means if it matters." So each mark is a primitive a
        person can describe out loud in one clause — a filled blob, an up
        triangle, a hollow ring, a plus, a dash — and SHAPE carries the whole
        meaning. (This sentence read "one dot, two dots, an empty dot, a dash, a
        triangle" until 2026-08-24: a draft vocabulary that never shipped, and
        the two-dots mark never existed at all. The five below are the language,
        and `schedule/README.md`'s table uses the same five words.) Colour
        agrees with it and is never the only difference between two marks,
        because a 10 px glyph on a lit panel at 400 mm is not where anyone should
        be resolving green against amber.

        Rectangles and one triangle, deliberately: they are the primitives this
        app already draws (the tab underline, the phase rail, the scroll
        chevrons), they need no measurement, and they cost nothing per frame.
        """
        screen = self.screen
        unit = self.mark_unit
        size = self.mark_px
        top = mid_y - size // 2
        mark = self.freshness
        if mark == MARK_SYNCED:
            # A SOLID BLOB: this agenda IS what the server last published.
            screen.pen = self.fresh_good
            screen.rectangle(x + unit, top + unit, size - unit * 2, size - unit * 2)
            return
        if mark == MARK_SUPERSEDED:
            # A TRIANGLE POINTING UP: there is a newer agenda above this one.
            # NOT a recoloured blob, and not two stacked bars -- the stacked pair
            # was drawn first and read as an EQUALS sign, which is the opposite
            # of what it meant. This is the one freshness fact that needs no
            # clock and matters most, so it must not depend on hue at all.
            #
            # THE FULL CELL, and the first draft inset it by a unit like the
            # blob. At 6x6 px the rasteriser turned it into a lump with no
            # discernible apex -- visible only on the 8x contact sheet, which is
            # what that sheet exists for. 10x10 is the smallest that reads as a
            # triangle at all.
            screen.pen = self.fresh_warn
            screen.triangle(x, top + size, x + size, top + size, x + size // 2, top)
            return
        if mark == MARK_STALE:
            # A HOLLOW RING: this badge has a link, so it COULD have been
            # updated, and what it is showing was never checked against it.
            # Hollow-for-uncertain is the vocabulary the dotted tab underline and
            # the dotted NEXT rail already use for "not the live thing".
            screen.pen = self.fresh_warn
            screen.rectangle(x, top, size, unit)
            screen.rectangle(x, top + size - unit, size, unit)
            screen.rectangle(x, top, unit, size)
            screen.rectangle(x + size - unit, top, unit, size)
            return
        if mark == MARK_DAY_OF:
            # A PLUS: something was ADDED to this badge by hand. It is a RECEIPT
            # rather than a verdict -- the operator who ran `mpremote fs cp` at
            # 07:50 otherwise finds out only on a serial console they do not
            # have -- so it takes the muted ink and not the amber.
            screen.pen = self.fresh_ink
            screen.rectangle(x + (size - unit) // 2, top, unit, size)
            screen.rectangle(x, top + (size - unit) // 2, size, unit)
            return
        # A DASH: no badgelink state on this badge at all, so there is nothing to
        # compare against and nothing to say. THE NORMAL STATE OF AN OFFLINE
        # FLEET, which is this feature's whole premise, so it is the quietest
        # thing on the screen -- one bar, in the dim pen, and never amber.
        screen.pen = self.dim
        screen.rectangle(x, top + (size - unit) // 2, size, unit)

    def _draw_tabs(self):
        screen = self.screen
        y = self.bar_h
        screen.pen = self.background
        screen.rectangle(0, y, int(screen.width), self.tab_h)
        for index, stage in enumerate(self.stages):
            width = self.tab_w[index]
            active = index == self.stage
            self._text(
                stage["name"], self.tab_x[index], y + self.pad // 4, width + 1, self.text_h,
                self.text if active else self.dim,
            )
            if active:
                # The page marks its live tab with a dotted rule in Supabase
                # green; the stage carries that colour in the schema.
                screen.pen = self.color.rgb(*stage["color"])
                bottom = y + self.tab_h - self.underline_h
                step = max(2, self.underline_h * 2)
                for dot in range(self.tab_x[index], self.tab_x[index] + width, step):
                    screen.rectangle(dot, bottom, self.underline_h, self.underline_h)
        if len(self.stages) > 1 and not self.softkeys:
            # THE DEFAULT BUILD'S A/C LABELLING SINCE 2026-08-24, and no longer a
            # fallback. With the bar on, A and C are named at the bottom with the
            # stage they move TO, which is strictly more than this hint says;
            # keeping both would be two labellings of one key. With the bar off
            # this is the naming, it sits in a row that already exists beside the
            # tabs it describes, and it costs no list space at all.
            self._text(
                self.hint,
                int(screen.width) - self.pad - self.hint_w,
                y + max(0, (self.tab_h - self.underline_h - self.meta_h) // 2),
                self.hint_w + 1,
                self.meta_h,
                self.dim,
                metadata=True,
            )
        screen.pen = self.rule
        screen.rectangle(0, y + self.tab_h - 1, int(screen.width), 1)

    def _draw_notice(self):
        """The one-line band that says the day-of override was not used."""
        if not self.notice:
            return
        screen = self.screen
        y = self.bar_h + self.tab_h
        screen.pen = self.notice_fill
        screen.rectangle(0, y, int(screen.width), self.notice_h)
        self._text(
            self.notice, self.pad, y + max(0, (self.notice_h - self.meta_h) // 2),
            int(screen.width) - self.pad * 2, self.meta_h, self.notice_ink,
            metadata=True,
        )

    def _strip_line(self):
        """The strip's sentence, decided by `strip_state` rather than in here.

        FOUR STATES, AND THE FOURTH USED TO BE A LIE. `DONE` and `EMPTY` shared
        one sentence, so at 19:00 a finished Main Stage read "NOTHING SCHEDULED
        ON THIS STAGE" -- which is what a stage with nothing on it says. The
        clock is trusted in both cases, so the app knows the difference and now
        says it. The relative countdowns are the other half of the owner's ask:
        a trusted clock makes "IN 12 MIN" free, and it is the reading somebody
        standing in a hallway actually wants.
        """
        sessions = self.visible()
        kind, index = strip_state(sessions, self.now_minutes)
        if kind == STRIP_NOW:
            session = sessions[index]
            value = "NOW  " + self.layout_cache[session["id"]]["title"]
            remaining = session["end"] - self.now_minutes
            if len(self.current) > 1:
                value += "  +{}".format(len(self.current) - 1)
            elif remaining > 0:
                value += "  ENDS IN " + format_gap(remaining)
            return value
        if kind == STRIP_NEXT:
            session = sessions[index]
            return "NEXT IN {}  {}".format(
                format_gap(session["start"] - self.now_minutes),
                self.layout_cache[session["id"]]["title"],
            )
        if kind == STRIP_DONE:
            return "THIS STAGE HAS FINISHED FOR THE DAY"
        return "NOTHING SCHEDULED ON THIS STAGE"

    def _draw_strip(self):
        """One line: what is on now, or what is next, or that nothing is.

        v1 drew a two-line NOW/NEXT block. At this type size that is 46 px of a
        160 px list, and the row it names is highlighted and scrolled to
        anyway; the strip only has a job once the reader has scrolled away.
        """
        if not self.trusted:
            return
        screen = self.screen
        y = self.bar_h + self.tab_h + self.notice_h
        screen.pen = self.now_fill
        screen.rectangle(0, y, int(screen.width), self.strip_h)
        self._text(
            self._strip_line(), self.pad, y + max(0, (self.strip_h - self.meta_h) // 2),
            int(screen.width) - self.pad * 2, self.meta_h, self.text,
            metadata=True,
        )

    def _draw_hatch(self, y, height):
        """The page's hatched break band, in the cheapest primitive that reads.

        Diagonals, not a flat tint: a break is the one row a reader should be
        able to skip without reading it, and a tint alone at this contrast was
        indistinguishable from the selection fill.
        """
        screen = self.screen
        screen.pen = self.hatch
        step = max(4, self.line_step // 3)
        width = int(screen.width)
        for start in range(-height, width, step):
            screen.line(start, y + height, start + height, y)

    def _phase(self, index):
        """The phase of one visible row, or None when there is no trusted clock."""
        if not self.phases or index >= len(self.phases):
            return None
        return self.phases[index]

    def _draw_phase_rail(self, index, y, height, phase):
        """The NOW/NEXT marker, drawn beside the time/title line.

        WHY THE GUTTER. `self.gap` sits between the time column and the content
        column on the first line, so a marker there costs no title characters,
        no list rows and no measurement. Credits use the full row underneath;
        the rail ends with the title rather than cutting through them. Every
        other candidate spends something: a `NOW` tag on the right takes width
        off every title, and the left edge is already the selection bar, which a
        phase marker must not be confusable with (one is where the wearer is,
        the other is where the clock is).

        Solid for the live row, a dotted run of the same bar for the next one --
        the same solid/dotted vocabulary the tab underline already uses for
        active-versus-not, so the screen has one visual idea instead of two.
        """
        if phase not in (PHASE_NOW, PHASE_NEXT):
            return
        screen = self.screen
        rail_w = max(2, self.underline_h)
        x = self.content_x - self.gap + max(0, (self.gap - rail_w) // 2)
        screen.pen = self.color.rgb(*self.stages[self.stage]["color"])
        if phase == PHASE_NOW:
            screen.rectangle(x, y, rail_w, height)
            return
        step = rail_w * 2
        for dot in range(y, y + height, step):
            screen.rectangle(x, dot, rail_w, min(rail_w, y + height - dot))

    def _draw_block(self, index, y):
        session = self.visible()[index]
        cached = self.layout_cache[session["id"]]
        screen = self.screen
        height = cached["height"] - self.block_gap
        phase = self._phase(index)
        past = phase == PHASE_PAST
        if session["kind"] == KIND_BREAK:
            self._draw_hatch(y - self.pad // 4, height + self.pad // 2)
        if index in self.current:
            screen.pen = self.current_fill
            screen.rectangle(0, y - self.pad // 4, int(screen.width), height + self.pad // 2)
        if index == self.selected[self.stage]:
            screen.pen = self.selection
            screen.rectangle(0, y - self.pad // 4, max(2, self.pad // 2), height + self.pad // 2)
        # Detail lines now span the row below this first line. Keeping the phase
        # marker beside the title preserves the empty-gutter placement without
        # drawing a rail through speaker names that legitimately cross under the
        # time column.
        self._draw_phase_rail(index, y, cached["title_h"], phase)
        # PAST IS TWO STEPS DOWN, NOT HIDDEN AND NOT GREYED OUT LIKE A DISABLED
        # CONTROL. A row that has ended still answers "what did I miss", and
        # `docs/engineering-findings.md` forbids hiding the list outright.
        if past:
            time_pen = self.past_muted
            title_pen = self.past_muted if session["kind"] == KIND_BREAK else self.past_ink
            speaker_pen = self.past_muted
            # THE ONE PLACE THE THREE-STEP HIERARCHY COLLAPSES TO TWO, and it is
            # a choice rather than an oversight: there is no pen below
            # `past_muted` that still reads as text instead of as a disabled
            # control, and a row that has ended is de-emphasised AS A WHOLE.
            description_pen = self.past_muted
        else:
            time_pen = self.muted
            # A literal hyphen remains a quiet placeholder for older/manual
            # artifacts. Current `Final Speaker` is authored text and therefore
            # uses normal ink; status never invents a subtitle in the renderer.
            title_pen = (
                self.muted
                if session["kind"] == KIND_BREAK or cached["title"] == "-"
                else self.text
            )
            speaker_pen = self.muted
            # THREE STEPS OF INK FOR THE BLOCK'S THREE LEVELS: what it is
            # (`text`), its subtitle (`muted`), the detail an eye may skip
            # (`dim`). The label is the only line here a wearer can ignore
            # without losing the agenda, so it is the quietest.
            # `dim` is a third readable step on the near-black list, but it
            # loses too much contrast on the green current fill. The live row
            # collapses speaker/description to one metadata ink just as the
            # past row collapses its lower tiers: hierarchy survives in size
            # and order, while the party's location remains legible.
            description_pen = self.muted if index in self.current else self.dim
        self._text(
            cached["time"], self.pad, y, self.time_w + 1, self.meta_h, time_pen,
            metadata=True,
        )
        self._text(cached["title"], self.content_x, y, self.content_w, cached["title_h"], title_pen)
        line_y = y + cached["title_h"] + self.pad // 2
        for line, line_h in cached["speakers"]:
            self._text(
                line, self.detail_x, line_y, self.detail_w, line_h, speaker_pen,
                metadata=True,
            )
            line_y += line_h + self.pad // 2
        # LAST, UNDER THE SUBTITLE, and the order is the block's reading order:
        # what, supporting label, then the detail. An empty description draws nothing at all
        # -- never an empty rect, which on a hatched break row would read as a
        # rendering fault rather than as an absent field.
        if cached["description"]:
            self._text(
                cached["description"], self.detail_x, line_y, self.detail_w,
                cached["description_h"], description_pen, metadata=True,
            )
        return height

    def _draw_softkeys(self, labels):
        """Three labels, one per key, each in its own bounded rect, drawn LAST.

        `docs/badge-button-rules.md` §B1, and every clause of it is load-bearing.
        Three separate `text` calls rather than one string: `profile` shipped
        `"A/C SKIN  UP STICKER  DOWN MODE  B EDIT"` at ~200 px on a 160 px canvas
        and the trailing `B EDIT` never rendered on the physical device, so the
        entry point to its sticker editor was invisible. A bounded rect with
        ELLIPSES rather than the default CLIP, so an oversized label degrades
        visibly instead of vanishing. And a 34 px x scale box, because at a 44 px
        cap the ink gutter between the A and B labels falls to one pixel and the
        wearer reads one phrase instead of two labels.

        An empty slot draws nothing and its key is inert, which is what one
        stage's A and C are.
        """
        if not self.softkeys:
            return
        screen = self.screen
        width = int(screen.width)
        y = int(screen.height) - self.softkey_h
        screen.pen = self.bar_fill
        screen.rectangle(0, y, width, self.softkey_h)
        screen.pen = self.bar_edge
        screen.rectangle(0, y - 1, width, 1)
        screen.pen = self.text
        for index in range(3):
            label = labels[index] if index < len(labels) else ""
            if not label:
                continue
            x = self.softkey_x[index] - self.label_w // 2
            low, high = self.zones[index]
            top = high - self.label_w
            x = low if x < low else (top if x > top else x)
            screen.text(
                label,
                self.rect(int(x), y, self.label_w, self.softkey_h),
                font_size=self.font_size,
                align=(self.image.CENTER, self.image.MIDDLE),
                overflow=self.image.ELLIPSES,
            )

    def _draw_scroll_hints(self, can_up, can_down):
        """Chevrons beside the two physical scroll buttons, inside the list.

        The bar has three slots and this app binds FOUR keys (five until the dial
        was deleted), so UP and DOWN cannot be named there -- and §9.6's
        complaint is that they were never named at all. The affordance sits
        beside the button that drives it; that adjacency is the point. Triangles
        because ROM faces have no arrow glyph, which is also why they cost no
        measurement.

        TWO THINGS THE FIRST DRAFT GOT WRONG, both visible only on a capture at
        panel scale:

        * SIZE. `shared/ui.py` draws a 3x4 px chevron, which is right at LORES
          because the panel doubles it. At HIRES 1:1 that is 1.1 x 1.5 mm and
          reads as a stray glyph fragment rather than as an arrow, so the mark
          scales with the chrome the way every other physical quantity here
          does.
        * PLACE. The UP button's centre is at y = 67 on a 240 px panel and this
          app's list starts at 77, so an unclamped chevron landed INSIDE the NOW
          strip -- a mark in the wrong band, pointing at a list it was not in.
          Clamping costs 13 px (4.9 mm) of adjacency and buys being in the right
          region.

        DRAWN WHETHER OR NOT THE BAR IS ON, since 2026-08-24. It used to return
        early on `not self.softkeys`, because the no-bar build existed only to
        reproduce the pre-bar geometry exactly for a side-by-side. That build
        SHIPS now, so the early return would have left UP and DOWN -- the two
        keys that do the most in this app -- with nothing on screen naming them.
        See `scroll_gutter` for why the two affordances no longer share a switch.
        """
        screen = self.screen
        mark = 2 * self.chrome_scale       # half-height; the triangle is 2x this
        span = 3 * self.chrome_scale       # base width
        x = int(screen.width) - 1 - span
        low = self.list_top + mark
        high = self.list_bottom - mark
        screen.pen = self.chevron
        if can_up:
            y = min(max(self.scroll_y[0], low), high)
            screen.triangle(x, y + mark, x + span, y + mark, x + span // 2, y - mark)
        if can_down:
            y = min(max(self.scroll_y[1], low), high)
            screen.triangle(x, y - mark, x + span, y - mark, x + span // 2, y + mark)

    def draw(self):
        screen = self.screen
        screen.font = self.face
        screen.pen = self.background
        screen.clear()
        self._draw_bar()
        self._draw_tabs()
        self._draw_notice()
        self._draw_strip()
        sessions = self.visible()
        y = self.list_top + self.pad // 2
        bottom = self.list_bottom
        drawn = 0
        for index in range(self.scroll[self.stage], len(sessions)):
            if y >= bottom:
                break
            height = self._draw_block(index, y)
            y += height + self.block_gap
            drawn += 1
            screen.pen = self.rule
            screen.rectangle(
                self.pad, y - self.block_gap // 2, int(screen.width) - self.pad * 2, 1
            )
        top = self.scroll[self.stage]
        self._draw_scroll_hints(top > 0, top + drawn < len(sessions))
        # LAST, on purpose: §B1's "no content in the band" is unshippable, so the
        # band is drawn over whatever the list left there rather than reserving
        # a region nothing may enter. `list_bottom` already keeps every whole
        # block above it; this only ever covers the gap below the last one.
        self._draw_softkeys(self.stage_labels[self.stage])

    # THERE IS NO `draw_dial`, AND THERE IS NO SECOND SCREEN AT ALL.
    #
    # `draw_dial` drew `SET EVENT TIME`, a panel-height `HH:MM`, a `BACK`/`SET`/
    # `+1 H` bar and `-5`/`+5` beside the two scroll buttons. The owner deleted
    # the feature on 2026-08-24: "we either get a real time from a server or
    # don't assume we know time." A dial is a human asserting a time the badge
    # has no way to verify, so a badge that took one would show a NOW marker
    # backed by nothing but somebody's watch.
    #
    # `docs/design/schedule.md` has always said "one screen plus a conditional
    # highlight; do not build multiple views", and this app now genuinely IS one
    # screen. The keys that read `B` are unbound; nothing draws over the agenda.
