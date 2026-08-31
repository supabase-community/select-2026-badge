"""Small full-screen renderer and lifetime for a custom Nametag notice.

It imports nothing so a stale or incomplete ``/system/lib`` cannot make the
ordinary Nametag fail.  The entry seam passes the injected badgeware drawing
APIs and the MicroPython tick functions explicitly.
"""


INK = (241, 247, 255)
MUTED = (143, 163, 184)
PAPER = (0, 0, 0)
# Supabase's green is the only brand colour on the screen.  Keeping the rest
# black/white makes a room-wide instruction read before its decoration does.
ACCENT = (62, 207, 142)
ACCENT_DARK = (20, 83, 61)
LABEL = "BADGE NOTICE"
HINT = "PRESS ANY BUTTON"


def _fits(surface, text, size, width):
    return int(surface.measure_text(text)[0] + 0.5) * size <= width


def _wrap(surface, text, size, width):
    """Measured word wrap with a character fallback for one long token."""

    lines = []
    current = ""
    for word in text.split(" "):
        candidate = word if not current else current + " " + word
        if _fits(surface, candidate, size, width):
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        while word and not _fits(surface, word, size, width):
            cut = len(word) - 1
            while cut > 1 and not _fits(surface, word[:cut], size, width):
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return tuple(lines)


class Notice:
    """Pre-measured notice that dismisses on a press or one deadline."""

    def __init__(self, record, surface, started, ticks_add):
        self.text = record["text"]
        self.duration_s = record["duration_s"]
        self.deadline = ticks_add(started, self.duration_s * 1000)
        width = int(surface.width) - 40
        # Prefer the bolder three-times ROM face when it remains a compact
        # block.  Sixty-four characters always fit at size two within the
        # vertical budget, so no accepted payload can be clipped.
        lines = _wrap(surface, self.text, 3, width)
        if len(lines) <= 3:
            self.size = 3
            self.lines = lines
        else:
            self.size = 2
            self.lines = _wrap(surface, self.text, 2, width)

    def active(self, now, pressed, ticks_diff):
        return not pressed and ticks_diff(now, self.deadline) < 0

    def paint(self, surface, color, font):
        """Paint one complete frame; point-form text cannot parse markup."""

        width = int(surface.width)
        height = int(surface.height)
        surface.font = font.sins
        surface.pen = color.rgb(PAPER[0], PAPER[1], PAPER[2])
        surface.clear()

        # Two thin rails make the temporary mode distinct without competing
        # with the custom sentence for attention.
        surface.pen = color.rgb(ACCENT_DARK[0], ACCENT_DARK[1], ACCENT_DARK[2])
        surface.rectangle(0, 0, width, 5)
        surface.pen = color.rgb(ACCENT[0], ACCENT[1], ACCENT[2])
        surface.rectangle(0, 0, width, 2)
        surface.rectangle(40, height - 10, width - 80, 2)

        surface.pen = color.rgb(ACCENT[0], ACCENT[1], ACCENT[2])
        label_w = int(surface.measure_text(LABEL)[0] + 0.5)
        surface.text(LABEL, (width - label_w) // 2, 24, 1)

        line_h = 12 * self.size
        block_h = len(self.lines) * line_h
        y = max(56, (height - block_h) // 2 - 2)
        surface.pen = color.rgb(INK[0], INK[1], INK[2])
        for line in self.lines:
            line_w = int(surface.measure_text(line)[0] + 0.5) * self.size
            surface.text(line, max(10, (width - line_w) // 2), y, self.size)
            y += line_h

        surface.pen = color.rgb(MUTED[0], MUTED[1], MUTED[2])
        hint_w = int(surface.measure_text(HINT)[0] + 0.5)
        surface.text(HINT, (width - hint_w) // 2, height - 34, 1)


class Session:
    """Notice screen and its existing-library light pulse, one lifetime."""

    def __init__(self, record, surface, color, font, caselights, time_api,
                 emit=print):
        self.surface = surface
        self.color = color
        self.font = font
        self.caselights = caselights
        self.time = time_api
        self.emit = emit
        self.started = time_api.ticks_ms()
        surface.font = font.sins
        self.view = Notice(record, surface, self.started, time_api.ticks_add)
        self.player = None
        try:
            # Effect id 2 is the append-only library's calm `pulse`.  Reusing
            # it keeps this screen coordinated with the proven fleet effects
            # without recreating a ramp or reviving the retired set_lights verb.
            import effect_library

            self.player = effect_library.player_for(
                {"kind": "lights", "id": 2,
                 "duration_s": record["duration_s"]})
            self._step_lights(0)
        except Exception as error:
            self.player = None
            emit("NOTICE_FAIL stage=lights-start error=%r" % error)

    def paint(self):
        self.view.paint(self.surface, self.color, self.font)

    def active(self, pressed):
        now = self.time.ticks_ms()
        return self.view.active(now, pressed, self.time.ticks_diff)

    def step(self):
        now = self.time.ticks_ms()
        self._step_lights(self.time.ticks_diff(now, self.started))
        self.paint()

    def _step_lights(self, elapsed):
        player = self.player
        if player is None:
            return
        try:
            if player.step(elapsed) and player.case_level is not None:
                self.caselights(player.case_level)
        except Exception as error:
            self.player = None
            self.emit("NOTICE_FAIL stage=lights-frame error=%r" % error)

    def close(self):
        """End the pulse and restore Nametag's dark case LEDs. Never raises."""

        player = self.player
        self.player = None
        if player is not None:
            try:
                player.interrupt()
            except Exception as error:
                self.emit("NOTICE_FAIL stage=lights-stop error=%r" % error)
        # Unconditional: Nametag zeroed the lights on entry, and this also
        # closes the missing/stale effect-library degradation path.
        try:
            self.caselights(0)
        except Exception as error:
            self.emit("NOTICE_FAIL stage=lights-clear error=%r" % error)
