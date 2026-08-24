"""Frame controller: screens, input, save policy.  Pure Python, no Badgeware.

Everything interesting about a rich care app lives in the controller - the feed
cooldown, the care-ring cursor, the save debounce, the rule that the press which
opens a screen must not also act on it, entering and leaving the minigame - so
the controller is a plain class with injected clock, input and writer.  That puts
roughly all of the new behaviour in the fast CPython lane instead of in
ninety-second browser tests.  `pet_view` renders the plan this returns;
`__init__.py` is a thin hardware seam that wires Badgeware globals in.

It imports `ui` (the vendored interaction-standard module) for the real `Repeat`
and `Saver`, so the repeat curve and the 400/1000 ms save policy here are the
device-wide ones and not a reimplementation that can drift.
"""

import pet_clock as clock
import pet_game
import pet_model as model
import ui
from pet_tuning import (
    ANT_TIER_MIN_MS, COMMIT_COOLDOWN_MS, GAME_REVEAL_MS, IDLE_LIGHTS_MS,
    ATTENTION_IDLE_MS,
    LOW_HEALTH_T, POSTER_IDLE_MS, REACT_MS, STAGE_REVEAL_MS, TOAST_MS,
)


KEYS = ("A", "B", "C", "UP", "DOWN")

# Rows of a readout that fit above the softkey bar at 14 px per row.  STATS and
# LOG scroll this WINDOW rather than a hidden cursor, so every direction press
# either moves something visible or is at a boundary the chevrons have already
# stopped advertising.
LIST_ROWS = 6


def _diff(a, b):
    return a - b


def _permille_left(remaining, total):
    """How far through a countdown we are, 0..1000, in integers."""
    if total <= 0 or remaining <= 0:
        return 1000
    if remaining >= total:
        return 0
    return (total - remaining) * 1000 // total


class _Snapshot:
    """One poll of the five keys, read once and reused for the whole frame.

    `badge.pressed()` is a membership test over sets that refresh at the END of
    the loop body, so on device it is idempotent within a frame.  Snapshotting
    anyway costs five calls and removes any dependence on that being true, which
    matters because a latching implementation would make a routed press vanish
    depending on how many times the controller happened to ask.
    """

    def __init__(self, buttons):
        self._edges = {}
        self._down = {}
        for key in KEYS:
            self._edges[key] = bool(buttons.pressed(key))
            self._down[key] = bool(buttons.held(key))

    def pressed(self, key):
        return self._edges[key]

    def held(self, key):
        return self._down[key]

    def any_press(self):
        for key in KEYS:
            if self._edges[key]:
                return True
        return False


class PetApp:
    """One badge session.  `write(state, milestone)` is the only side effect."""

    def __init__(self, state, write, now_ms=0, load_status="missing",
                 report=None, random_below=None, ticks_diff=None):
        self.state = state
        self.load_status = load_status
        self._write = write
        self._random_below = random_below or (lambda n: 0)
        self._diff = ticks_diff or _diff
        self.saver = ui.Saver(self._commit_write)

        self.now_ms = now_ms
        self._session_ms = 0          # accumulated but unspent milliseconds
        self._last_ms = now_ms
        self._last_input_ms = now_ms
        self._pending_stage = ""

        # Test-observable surface, deliberately small and named as such:
        # `phase` proves no write happens mid-render, `writes` counts them, and
        # `dirty` proves navigation never persists.
        self.phase = "idle"
        self.writes = 0
        self.frames = 0

        self.index = model.suggest(state)
        self.top = 0
        self.game = None
        self.game_reveal_until = None
        self.toast = ""
        self.toast_until = now_ms
        self.reveal_until = None
        self.last_commit_ms = now_ms - COMMIT_COOLDOWN_MS - 1
        self.events = []
        # VIEW-ONLY reaction state.  The creature pulls a face for REACT_MS
        # after an action; nothing here is saved, reaches the model, or is
        # reconstructed on the next open, which is exactly why it can be a
        # wall-clock timer while the simulation is not.
        self.react = ""
        self.react_until = now_ms
        # The Ant's threat tier is HELD for a minimum, so a health bar falling
        # fast on the 120x clock cannot strobe him between two poses.
        self.ant_tier = 0
        self.ant_tier_ms = now_ms - ANT_TIER_MIN_MS - 1

        self._up = ui.Repeat()
        self._down = ui.Repeat()
        self._consume = True           # the launcher's own press must not act

        self.report = report or model.new_report()
        self.news = self.report if self._news_worthy(self.report) else None
        self.view = model.NEWS if self.news else model.view_for(state)
        if self.report.get("stage_up"):
            self.reveal_until = now_ms + STAGE_REVEAL_MS

    # -- persistence -------------------------------------------------------

    @property
    def dirty(self):
        return self.saver._dirty

    def _commit_write(self):
        self.writes += 1
        self._write(self.state, False)

    def _flush_milestone(self):
        """Transitions that must survive an immediate power cut.

        Deliberately NOT used by anything repeatable.  A milestone is two atomic
        flash writes (primary plus backup) at 7-185 ms each, so anything a player
        can press twice a second belongs on `touch()` and the 400/1000 ms policy;
        this is for pause, restore, stage-up, hatch and erase, which happen once.
        """
        self.phase = "commit"
        self.saver._dirty = False
        self.writes += 1
        self._write(self.state, True)
        self.phase = "idle"

    def touch(self, now_ms):
        self.saver.touch(now_ms)

    def on_exit(self):
        """Called from the HOME IRQ and from a normal return.  Never the only
        write path - the debounce ceiling is 1000 ms precisely so this is a
        backstop rather than a single point of failure."""
        self.phase = "exit"
        if self.saver._dirty:
            self.saver._dirty = False
            self.writes += 1
            self._write(self.state, False)
        self.phase = "idle"

    # -- session time ------------------------------------------------------

    def _tick(self, now_ms):
        """Spend whole seconds of monotonic session time on the simulation.

        Wall time is read once, at open.  Everything after that comes from the
        tick counter, so a badge with a dead RTC still shows a creature that ages
        while you watch it, and the playground's virtual clock reproduces the
        device exactly.  Never poll this less often than every frame: the
        increments must stay small for ticks_diff wraparound to be a non-issue.
        """
        delta = self._diff(now_ms, self._last_ms)
        self._last_ms = now_ms
        if delta < 0:
            delta = 0
        self._session_ms += delta
        seconds = self._session_ms // 1000
        if seconds <= 0:
            return model.new_report()
        self._session_ms -= seconds * 1000
        before = self.state["state"]
        # THE ATTENTION CLOCK.  Fast time is a property of the MOMENT, not of
        # the creature: the world runs at the creature's speed while somebody is
        # pressing keys and at real time when nobody is.  The multiplier is
        # chosen here, outside `advance`, so it stays an integer and additivity
        # is untouched - sum(a_i * S) == S * sum(a_i) still holds exactly.
        attended = self._diff(now_ms, self._last_input_ms) < ATTENTION_IDLE_MS
        # A RESTORE IS NEVER UNATTENDED, whatever the keys say.  The countdown
        # is FAST_RESTORE_REAL_S (20 s) and the attention window is also 20 s,
        # so a restore straddled the cliff: whether the wait was 20 seconds or
        # 139 depended on frame alignment, and the screen told the player to go
        # away, which is the one thing that made it worse.  The wait is a
        # promise the app made; it keeps it at full speed.
        restoring = self.state["state"] == model.RESTORING
        speed = model.speed_of(self.state) if (attended or restoring) else 1
        self.state, report = clock.session_tick(self.state, seconds, speed)
        if report["autovacuum"]:
            # The safety net announcing that it could not finish.  Postgres 14+
            # logs "N dead row versions cannot be removed yet, oldest xmin: ...";
            # this is that line, at 130 px.
            self._set_toast(now_ms, "AUTOVACUUM: 1 HELD")
        if report["stage_up"]:
            self._flush_milestone()
            if self.view == model.GAME:
                # THE ONE MOMENT THE APP CANNOT AFFORD TO DROP.  `game()` draws
                # no toast band, and TOAST_MS and STAGE_REVEAL_MS have both
                # elapsed by the time CARE comes back - so a creature that grew
                # up during a round of PLANNER grew up silently.  Defer the
                # announcement rather than widen the windows, which would only
                # move the problem.
                self._pending_stage = model.stage_name(self.state)
            else:
                self.reveal_until = now_ms + STAGE_REVEAL_MS
                self._set_toast(now_ms, "EVOLVED: " + model.stage_name(self.state))
        if self.state["state"] != before:
            self._flush_milestone()
        return report

    # -- input -------------------------------------------------------------

    def _set_toast(self, now_ms, text):
        self.toast = text
        self.toast_until = now_ms + TOAST_MS

    def _set_react(self, now_ms, event):
        """The face an outcome earns.  View state, deliberately: it is the one
        thing in this app that must NOT be reconstructed - a creature does not
        still look surprised six hours later."""
        if not event:
            return
        self.react = event
        self.react_until = now_ms + REACT_MS

    def _goto(self, view):
        """Every transition drains input (R16) and parks the ring ONCE.

        Screen entry is the only moment the cursor is allowed to move on its
        own.  Once the labels are drawn, the word above key B has to keep
        describing key B until the player moves the cursor themselves.
        """
        self.view = view
        self._up.block()
        self._down.block()
        self._consume = True
        if view == model.CARE:
            self.index = model.suggest(self.state)
            if self._pending_stage:
                # Replay the announcement the PLANNER swallowed, now that there
                # is a screen with a toast band to show it on.
                now = self.now_ms
                self.reveal_until = now + STAGE_REVEAL_MS
                self._set_toast(now, "EVOLVED: " + self._pending_stage)
                self._pending_stage = ""
        if view in (model.STATS, model.LOG):
            self.top = 0
        if view != model.GAME:
            self.game = None

    def _news_worthy(self, report):
        return (report.get("away_s", 0) >= model.news_min_away_s(self.state)
                and model.report_has_news(report))

    def _view_contradicts_state(self):
        """Is the screen one this state is not allowed to be on?

        `model.view_for` is the screen the app MUST be on for a state, ignoring
        navigation, and the care ring is the case that matters: it draws a live
        FEED verb above key B that a paused or restoring project can only ever
        reject.  Asserting it only on the frame a transition fires was not
        enough - RESTORING -> C (STATS) -> A landed back on CARE and stayed
        there for the whole five-minute wait.  STATS, LOG and CONFIRM are
        read-only or their own decision, so a paused project can still be
        inspected; only the acting screens are corrected.
        """
        wanted = model.view_for(self.state)
        if self.view in (model.PAUSED_VIEW, model.RESTORING_VIEW):
            return wanted != self.view
        if self.view in (model.CARE, model.GAME):
            return wanted != model.CARE
        return False

    def _scroll(self, now_ms, buttons):
        """UP and DOWN change exactly one integer by one step.  Nothing else."""
        step = self._down.step(buttons.held("DOWN"), now_ms)
        step -= self._up.step(buttons.held("UP"), now_ms)
        return step

    def _scroll_window(self, step, total, fresh):
        """Move the visible WINDOW of a readout by one row.

        The old code scrolled a selected-row integer that neither STATS nor LOG
        renders, so five of thirteen DOWN presses on STATS changed nothing at
        all on screen and the sixth jumped.  A readout with no per-row action
        does not need a cursor; it needs its window to move on every press that
        can move, and its chevrons to stop advertising the ones that cannot.

        R15 in one line: a held key stops dead at the boundary, and a FRESH
        press crosses it, so position sense survives an auto-repeat sweep.
        """
        highest = max(0, total - LIST_ROWS)
        top = self.top + step
        if top < 0:
            return highest if fresh else 0
        if top > highest:
            return 0 if fresh else highest
        return top

    def frame(self, now_ms, buttons):
        """One frame.  Returns the render plan; never draws anything itself."""
        self.now_ms = now_ms
        self.frames += 1
        self.events = []
        self.phase = "time"
        report = self._tick(now_ms)
        if report["paused"] or report["restored"] or self._view_contradicts_state():
            self._goto(model.view_for(self.state))

        self.phase = "input"
        buttons = _Snapshot(buttons)
        any_press = buttons.any_press()
        if any_press or buttons.held("UP") or buttons.held("DOWN"):
            self._last_input_ms = now_ms

        if self._consume:
            # Swallow the press that arrived with this screen, then read normally
            # from the next frame; `badge.pressed` is an edge, so one frame is
            # enough and no state has to be carried.
            self._consume = False
            self._scroll(now_ms, buttons)
        else:
            self._route(now_ms, buttons, any_press)

        if (self.view not in (model.POSTER, model.GAME)
                and self._diff(now_ms, self._last_input_ms) >= POSTER_IDLE_MS
                and self.view in (model.CARE, model.STATS, model.LOG)):
            self._goto(model.POSTER)

        self.phase = "persist"
        self.saver.poll(now_ms)
        self.phase = "idle"
        return self.plan(now_ms)

    def _route(self, now_ms, buttons, any_press):
        view = self.view
        if view == model.POSTER:
            if any_press:
                self._goto(model.view_for(self.state))
            return
        if view == model.NEWS:
            if buttons.pressed("B"):
                self.news = None
                self._goto(model.view_for(self.state))
            return
        if view == model.GAME:
            return self._route_game(now_ms, buttons)

        step = self._scroll(now_ms, buttons)
        fresh = buttons.pressed("UP") or buttons.pressed("DOWN")
        if view == model.CARE:
            if step:
                self.index = (self.index + step) % len(model.RING)
            if buttons.pressed("A"):
                self._goto(model.POSTER)
            elif buttons.pressed("C"):
                if self.state["stage"] == 0:
                    self._toggle_speed(now_ms)
                else:
                    self._goto(model.STATS)
            elif buttons.pressed("B"):
                self._commit_ring(now_ms)
            return
        if view == model.STATS:
            if step:
                self.top = self._scroll_window(
                    step, len(model.stats_rows(self.state)), fresh)
            if buttons.pressed("B"):
                # NEW is on B of STATS, not of LOG: see the note in
                # model.softkeys.  It is one screen from every root, so
                # handing the badge to the next person is C, B, C.
                self._goto(model.CONFIRM)
            elif buttons.pressed("A"):
                # Retreat to whatever the app's root is RIGHT NOW: a project
                # that paused while this screen was up has no care ring.
                self._goto(model.view_for(self.state))
            elif buttons.pressed("C"):
                self._goto(model.LOG)
            return
        if view == model.LOG:
            if step:
                self.top = self._scroll_window(
                    step, len(self.state["log"]), fresh)
            if buttons.pressed("A"):
                self._goto(model.STATS)
            return
        if view == model.CONFIRM:
            if buttons.pressed("A"):
                self._goto(model.STATS)
            elif buttons.pressed("C"):
                self._new_project(now_ms)
            return
        if view == model.PAUSED_VIEW:
            if buttons.pressed("C"):
                # A paused project can still be inspected - and reset, which is
                # the same three presses it is from an alive one.
                self._goto(model.STATS)
                return
            if buttons.pressed("B"):
                self.state, out = model.apply(self.state, model.RESTORE)
                if out["event"]:
                    self._set_toast(now_ms, out["text"])
                    self.events.append("restoring")
                    self._flush_milestone()
                    self._goto(model.RESTORING_VIEW)
            return
        if view == model.RESTORING_VIEW:
            if buttons.pressed("C"):
                self._goto(model.STATS)
            return

    def _toggle_speed(self, now_ms):
        """Only ever reachable on the EGG, where no simulated time has run."""
        self.state["fast"] = 0 if model.mode_of(self.state) else 1
        self._set_toast(now_ms, "FAST CLOCK" if self.state["fast"] else "REAL CLOCK")
        self.events.append("speed")
        self.touch(now_ms)

    def _commit_ring(self, now_ms):
        if self.state["stage"] == 0:
            self.state, out = model.apply(self.state, model.HATCH)
            self._set_toast(now_ms, out["text"] or "NOT YET")
            self._set_react(now_ms, out["event"])
            if out["event"]:
                self.events.append("hatched")
                self._flush_milestone()
                # PARK ON WHAT THE HATCHLING NEEDS, not on whatever the egg
                # screen left behind.  `suggest` returns 0 for an egg, so the
                # cursor sat on RING[0] = FEED - and a hatchling has DATA at MAX,
                # so key B read FEED while FEED was refusing with DUPLICATE KEY.
                # The very first frame of a new creature advertised an action it
                # would not perform.  Every other commit re-parks; this one
                # returns early and was missed.
                self.index = model.suggest(self.state)
            return
        # B IS INERT WHILE THE REACTION PLAYS.  This is what makes it safe for
        # the cursor to re-park below: D22 was right that relabelling B between
        # two taps of B commits a verb the player never read, so the label may
        # only change while the key is refusing to act.  REACT_MS is exactly the
        # window in which the creature is visibly reacting, so the pause reads
        # as the app responding rather than as a dropped press.
        if self._diff(self.react_until, now_ms) >= 0:
            return
        action = model.RING[self.index]
        ok, why = model.available(self.state, action)
        if not ok:
            self._set_toast(now_ms, why)
            return
        # ONE cooldown for the whole ring.  Every entry is repeatable and REST is
        # a free two-way toggle, so rate-limiting only FEED left the others able
        # to commit at frame rate - 3750 commits in a 60 s mash, each one a game
        # decision the player never read.
        if self._diff(now_ms, self.last_commit_ms) < COMMIT_COOLDOWN_MS:
            return
        self.last_commit_ms = now_ms
        if action == model.PLAY:
            self.game = pet_game.Planner(self._random_below)
            self.game_reveal_until = None
            self._goto(model.GAME)
            return
        self.state, out = model.apply(self.state, action)
        self._set_toast(now_ms, out["text"])
        self._set_react(now_ms, out["event"])
        self.events.append(out["event"] or out["rejected"])
        # Every ring action, REST included, goes through the device-wide
        # 400/1000 ms save policy.  REST used to flush a milestone - two atomic
        # writes - on every commit, inside the input loop, with no rate limit at
        # all; the sleep flag is reconstructible from `fatigue` on the next open,
        # so it never needed the power-cut guarantee that pause and restore do.
        self.touch(now_ms)
        # RE-PARK ON WHAT THE CREATURE NEEDS NEXT.
        #
        # This is the change that makes the app survivable by a stranger, and it
        # is the reverse of an earlier ruling, so the reason it is now safe is
        # written down: the cursor may move because key B is inert for REACT_MS
        # above, so the label can never change between two LIVE taps.
        #
        # Why it is needed: a booth visitor presses B and nothing else - nobody
        # discovers UP/DOWN on a device they have held for thirty seconds - so a
        # fixed cursor means they commit ONE verb forever.  Measured on the
        # build before this: mashing B parked them in the minigame while the
        # creature starved, and it PAUSED at 280 s.
        #
        # It is not a downgrade for a deliberate player either, because
        # `suggest` returns the SAME action while that need is still the most
        # pressing - four feeds in a row still take four presses of B.  It moves
        # only when what the creature needs has actually changed.
        self.index = model.suggest(self.state)

    def _route_game(self, now_ms, buttons):
        if self.game_reveal_until is not None:
            if self._diff(now_ms, self.game_reveal_until) < 0:
                return
            self.game_reveal_until = None
            if self.game.finished:
                self._finish_game(now_ms)
            else:
                self.game.next_round()
            return
        step = self._scroll(now_ms, buttons)
        if step:
            self.game.move(step)
        if buttons.pressed("A"):
            # A visible way out that costs nothing: no reward, no penalty.
            self.game = None
            self._goto(model.CARE)
            return
        if buttons.pressed("B"):
            self.game.commit()
            self.game_reveal_until = now_ms + GAME_REVEAL_MS

    def _finish_game(self, now_ms):
        won = self.game.won
        self.game = None
        # Nothing was written during the game; the result is one commit at the end.
        self.state, out = model.apply(
            self.state, model.PLAY_WIN if won else model.PLAY_LOSS)
        self._set_toast(now_ms, out["text"])
        if won:
            self._set_react(now_ms, out["event"])
        self.events.append("played")
        self.touch(now_ms)
        self._goto(model.CARE)

    def _new_project(self, now_ms):
        """ERASE, with the one-level backup R19 requires actually written.

        The order matters and is easy to get backwards: write the OLD creature
        to its keepsake slot FIRST, and only then write the fresh egg to the
        primary.  Doing it the other way round leaves the egg in both slots and
        the promise on the confirmation screen becomes a lie.

        The keepsake goes to `.prev`, NOT to the milestone backup: `.bak` is
        rewritten by the next milestone, and the very next thing this screen
        offers is B = INIT, which is one.  The backup used to survive a single
        button press.
        """
        self.phase = "commit"
        self.writes += 1
        self._write(self.state, False, True)
        self.phase = "idle"
        last_seen = self.state.get("last_seen", 0)
        self.state = model.new_state(model.MAX, last_seen)
        self.index = 0
        self._set_toast(now_ms, "NEW PROJECT")
        self.events.append("erased")
        self.phase = "commit"
        self.saver._dirty = False
        self.writes += 1
        self._write(self.state, False)
        self.phase = "idle"
        self._goto(model.CARE)

    # -- render plan -------------------------------------------------------

    def lights(self, now_ms):
        """R22: the case lights are REAR facing, so they are ambient signalling
        at rest and useless as feedback for an action just taken.  They run only
        after an idle window and only on the screens that are held up and shown
        to people rather than pressed."""
        if self._diff(now_ms, self._last_input_ms) < IDLE_LIGHTS_MS:
            return (0.0, 0.0, 0.0, 0.0)
        if self.view not in (model.POSTER, model.PAUSED_VIEW, model.RESTORING_VIEW):
            return (0.0, 0.0, 0.0, 0.0)
        state = self.state
        if state["state"] == model.PAUSED:
            return (0.0, 0.0, 0.0, 0.0)   # a paused project draws no power
        if state["state"] == model.RESTORING:
            index = (now_ms // 600) % 4
            return tuple(0.5 if i == index else 0.03 for i in range(4))
        if state["asleep"]:
            return (0.06, 0.0, 0.0, 0.0)
        if state["health"] <= LOW_HEALTH_T:
            phase = (now_ms // 500) % 8
            level = 0.55 if phase in (0, 2) else 0.0
            return (level, 0.0, level, 0.0)
        phase = (now_ms % 4000) / 4000.0
        level = 0.05 + 0.25 * (1.0 - abs(2.0 * phase - 1.0))
        return (level, level, level, level)

    def ant_tier_now(self, now_ms):
        """0..3, held for at least ANT_TIER_MIN_MS.

        The controller has always computed a continuous closing distance and the
        renderer used to throw it away and play the same two frames at every
        distance.  Tiers turn the meter into a story: a doorway silhouette, then
        walking in, then the stylus up, then a finger over the button.
        """
        permille = self.ant_permille()
        wanted = 0
        for index, threshold in enumerate((250, 550, 850)):
            if permille >= threshold:
                wanted = index + 1
        if wanted != self.ant_tier:
            if self._diff(now_ms, self.ant_tier_ms) < ANT_TIER_MIN_MS:
                return self.ant_tier
            self.ant_tier = wanted
            self.ant_tier_ms = now_ms
        return self.ant_tier

    def ant_permille(self):
        """0 when the Ant is off screen, 1000 when he is beside the creature.

        A continuously closing distance is the cheapest possible second read of
        the health bar, legible across a room, and it uses the meter half of the
        decided "meter plus threshold" instead of throwing it away.
        """
        state = self.state
        if state["state"] != model.ALIVE or state["health"] > LOW_HEALTH_T:
            return 0
        return 1000 - state["health"] * 1000 // LOW_HEALTH_T

    def plan(self, now_ms=None):
        now_ms = self.now_ms if now_ms is None else now_ms
        state = self.state
        labels = model.softkeys(state, self.view, self.index)
        return {
            "view": self.view,
            "labels": labels,
            "state": state,
            "index": self.index,
            # The cursor the player drives, and the action the model would
            # choose.  They are separate on purpose: the suggestion is drawn as
            # a passive outline the player can move to, never by moving the
            # cursor for them.
            "suggest": model.suggest(state),
            "top": self.top,
            "mood": model.mood_name(state),
            # A reaction face, and how far through it we are: the renderer
            # tweens the food along that number and then lets the mood back.
            "react": self.react if self._diff(self.react_until, now_ms) >= 0 else "",
            "react_p": _permille_left(self._diff(self.react_until, now_ms),
                                      REACT_MS),
            "ant_tier": self.ant_tier_now(now_ms),
            "toast": self.toast if self._diff(self.toast_until, now_ms) >= 0 else "",
            "ant": self.ant_permille(),
            "rate": model.health_rate_t(state),
            "news": self.news,
            "reveal": (self.reveal_until is not None
                       and self._diff(self.reveal_until, now_ms) >= 0),
            "game": self.game,
            "game_reveal": self.game_reveal_until is not None,
            "lights": self.lights(now_ms),
            "frame": self.frames,
        }
