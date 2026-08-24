"""WHEN the backdrop cache is written.  The editor's half of the owner's verdict.

`shared/backdrop.py` is the format and `shared/poster.py` decides WHAT may be
cached; this module is the only thing that decides WHEN, and it exists as a
module rather than as ten lines in the seam for a measured reason: the seam is
compiled in full before stage 0 puts a field on the panel
(`badgecard/tests/test_card_purity.py::EntryFootprintTests`), and this weight
belongs behind that first paint like every other module the arrival defers.

WHY THE EDITOR WRITES IT AND THE BADGE DOES NOT.  `poster` is a second WINDOW
onto one badge -- read-only by ruling, gated file by file in
`poster/tests/test_poster_app.py` -- so the only app that may fill the cache is
the one that already rasterised the skin the wearer picked.  Which makes it
nearly free: after an APPLY the browser's last render IS the new artwork,
sitting in the surface, and this writes those bytes out rather than making any.

BAKE-ON-CHANGE, NOT BAKE-ON-OPEN.  `held` is what the volume is believed to
contain, primed from the stage-2 READ rather than from a fresh `peek`: stage 2
has already opened the file and asked the question, and an editor that re-wrote
307 KB on every open would be flash wear buying nothing.  So a session writes
either once (the wearer changed skin, or the cache was absent) or not at all.

ONE CHUNK PER FRAME, because `docs/badge-button-rules.md` I4 forbids a blocking
operation while real-time content is on screen and a HIRES cache is ~300 KB of
flash.  `backdrop.Writer` owns the chunking; this owns the scheduling, and the
two screens it refuses to schedule on are the reason it needs a view at all.
"""


class Scheduler:
    """Steps one `backdrop.Writer` at a time.  Never raises.

    `poster` is the renderer whose surface holds the pixels, or None -- which is
    a real state and not a guard: a seam whose stage 1 failed has no renderer,
    and a test that only wants the frame loop can build one with None and get an
    object that correctly does nothing.
    """

    # The two screens a write may not start or continue on, and they are
    # excluded for two different reasons.  SKIN is the browser: a scrub already
    # pays a full rasterise per settle (`card_app.SETTLE_MS`) and must not also
    # pay a flash write.  BAKING is the wallpaper modal, which is doing its own
    # 76,816-byte write on those very frames.
    BUSY = ("skin", "baking")

    # `Writer.error` when the renderer pulled the pixels out from under a write
    # because the wearer picked another skin.  NOT a failure: the surface now
    # holds a different picture, and the right response is to write THAT one.
    ABANDONED = "abandoned"

    def __init__(self, poster, log=None):
        self.poster = poster
        # What the volume is believed to HOLD.  Two separate slots, because
        # "already cached" and "do not ask again" are different facts and one
        # variable holding both is how a glyph deck ends up recorded as cached.
        self.held = ""
        self.refused = ""
        self.writer = None
        self.writing = ""
        self.writes = 0
        self._log = log

    def prime(self, entry_id, hit):
        """Record what stage 2 found, so an unchanged badge writes nothing.

        `hit` is `poster.cached` after the arrival's artwork stage: True means
        the volume already holds this entry's pixels.
        """
        self.held = entry_id if hit else ""

    def step(self, entry_id, view):
        """One chunk, or one decision, or nothing.  Returns True if it worked.

        Called AFTER the frame is drawn, which is what lets it trust the
        surface: every screen but the browser draws the worn badge behind its
        own chrome, so by this point the renderer's backdrop holds the picture
        the wearer is looking at.
        """
        if self.writer is not None:
            return self._continue()
        if (self.poster is None or view in self.BUSY
                or entry_id == self.held or entry_id == self.refused):
            return False
        return self._start(entry_id)

    def _continue(self):
        writer = self.writer
        target = self.writing
        try:
            if writer.step():
                return True
        except Exception as error:  # noqa: BLE001 - a cache, never a reset
            self.writer = None
            self.refused = target
            self._say("CARD_CACHE done=0 id=%s error=%r" % (target, error))
            return False
        self.writer = None
        if writer.ok:
            self.writes += 1
            # THE ENTRY THE WRITER WAS FOR, never the one on screen now. The
            # wearer can change skin mid-write -- the renderer abandons the
            # write when it does -- and recording the CURRENT background here
            # would mark the volume as holding a picture it never received.
            self.held = target
        elif writer.error != self.ABANDONED:
            # A REFUSAL IS REMEMBERED FOR THE SESSION. Retrying a full volume
            # every frame is a badge that spends its whole session failing to
            # write; the next OPEN tries again, which is soon enough for a
            # cache. An ABANDONED write is not remembered, because the pixels
            # changed and the new ones are worth writing.
            self.refused = target
        self._say("CARD_CACHE done=%d id=%s error=%s"
                  % (1 if writer.ok else 0, target, writer.error or "-"))
        return True

    def _start(self, entry_id):
        try:
            writer = self.poster.backdrop_writer(entry_id)
        except Exception as error:  # noqa: BLE001
            self.refused = entry_id
            self._say("CARD_CACHE done=0 id=%s error=%r" % (entry_id, error))
            return False
        if writer is None:
            # THREE DIFFERENT ANSWERS BEHIND ONE None, and telling them apart is
            # the whole reason `Poster.holds` is public.
            if not self.poster.holds(entry_id):
                # TRANSIENT: the surface is showing something else this frame --
                # the keyboard draws no badge behind it, for instance. Ask
                # again next frame rather than giving up for the session.
                return False
            if self.poster.cached:
                # Already on the volume, which is where we wanted it.
                self.held = entry_id
            else:
                # A glyph deck (its painter owns the surface and would overwrite
                # a cached frame with its own keyframe), or a build with no
                # codec vendored. Neither will change this session.
                self.refused = entry_id
            return False
        self.writer = writer
        self.writing = entry_id
        self._say("CARD_CACHE start=%s steps=%d" % (entry_id, writer.steps))
        return True

    def abandon(self):
        """Drop a write in flight and take its file with it.  Never raises.

        The exit path.  What is left behind would be refused by the reader --
        it is short -- but 300 KB of rubbish on a 1 MB volume is 300 KB the
        wearer's own state might need, and the next open rewrites it in 76
        frames anyway.

        SEVENTY-SIX, NOT TWENTY, since `backdrop.CHUNK_BYTES` was measured on
        hardware and moved to one 4 KB block (2026-08-22).  Worth stating in
        real time rather than in frames, because "the next open rewrites it
        anyway" is doing more work in this argument than it looks: 76 frames is
        **4.3 s of editor dwell**, so a wearer who abandons and immediately
        leaves again may go several opens without a cache.  That is still the
        right trade -- a short file is dead weight either way -- but it is not
        free.
        """
        writer = self.writer
        if writer is None:
            return False
        self.writer = None
        try:
            writer.abandon()
        except Exception:  # noqa: BLE001
            return False
        self._say("CARD_CACHE abandoned=1")
        return True

    def _say(self, message):
        if self._log is not None:
            self._log(message)
